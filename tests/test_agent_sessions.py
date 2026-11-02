"""Synthetic CLI processes and transcripts; no account or live agent calls."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import uuid

import pytest

from wow_helper import agent_sessions as agents
from wow_helper.chat import ChatError, read_json, write_json


def uid(number):
    return str(uuid.UUID(int=number))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents, "claude_command", lambda: ["synthetic-claude"])
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *args, **kwargs: object())
    return agents.AgentSessions(tmp_path)


def fake_cli(monkeypatch, events, *, code=0, timeout=False):
    instances = []
    class Process:
        def __init__(self, args, **kwargs):
            self.args, self.kwargs, self.returncode = args, kwargs, None
            self.inputs, self.killed = [], False
            kwargs["stdout"].write(b"\n".join(json.dumps(e).encode() for e in events))
            kwargs["stdout"].flush()
            instances.append(self)

        def communicate(self, input=None, timeout=None):
            self.inputs.append(input)
            if fake_timeout[0] and not self.killed:
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = -1 if self.killed else code
            return None, None

        def poll(self): return self.returncode

        def kill(self): self.killed = True

    fake_timeout = [timeout]
    monkeypatch.setattr(agents.subprocess, "Popen", Process)
    return instances


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_durable_turn_resumes_native_conversation_and_never_replays(store, monkeypatch, provider):
    session = store.create(provider, startup="Synthetic startup context", creation_id=uid(10))
    store.send(session, "First question", uid(11))
    if provider == "codex":
        events = [{"type": "thread.started", "thread_id": uid(12)},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "First answer"}}]
    else:
        events = [{"type": "system", "session_id": uid(12)},
                  {"type": "result", "is_error": False, "result": "First answer"}]
    processes = fake_cli(monkeypatch, events)
    agents.run_turn(store.storage, session.id, uid(11))
    assert store.result(session.id, uid(11))["status"] == "completed"
    assert b"Synthetic startup context" in processes[0].inputs[0]
    assert read_json(store.folder(session.id) / "session.json")["native_id"] == uid(12)
    agents.run_turn(store.storage, session.id, uid(11))
    assert len(processes) == 1
    with pytest.raises(ChatError, match="already attempted"):
        agents.AgentSessions(store.storage).send(session, "First question", uid(11))
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *args, **kwargs: object())
    store.send(session, "Second question", uid(13))
    # An old helper cannot clear another turn's active marker.
    agents.run_turn(store.storage, session.id, uid(11))
    assert read_json(store.folder(session.id) / "session.json")["active"] == uid(13)
    processes = fake_cli(monkeypatch, events)
    agents.run_turn(store.storage, session.id, uid(13))
    assert uid(12) in processes[0].args
    assert processes[0].inputs == [b"Second question"]
    assert [m.role for m in store.history(session)] == ["user", "assistant", "user", "assistant"]


def test_launch_failure_is_durable_and_does_not_leave_session_busy(store, monkeypatch):
    session = store.create("codex")
    def broken(*args, **kwargs): raise OSError("Synthetic private diagnostic")
    monkeypatch.setattr(agents.subprocess, "Popen", broken)
    with pytest.raises(ChatError, match="not delivered"):
        store.send(session, "Question", uid(1))
    assert store.result(session.id, uid(1))["status"] == "failed"
    assert read_json(store.folder(session.id) / "session.json")["active"] is None
    assert "private diagnostic" not in str(store.history(session))


def test_structured_request_has_readable_history_without_changing_native_prompt(store, monkeypatch):
    session = store.create('codex')
    store.send(session, 'Synthetic extraction instructions', uid(44),
               display_body='Compare these items', schema={'type': 'object'})
    assert not store.idle(session)
    assert [m.text for m in store.history(session)] == ['Compare these items', 'Processing this request…']
    with pytest.raises(ChatError, match='not ready'):
        store.present(session, uid(44), 'Premature answer')
    processes = fake_cli(monkeypatch, [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}}])
    agents.run_turn(store.storage, session.id, uid(44))
    assert store.idle(session)
    store.present(session, uid(44), 'Validated comparison')
    assert [m.text for m in store.history(session)] == ['Compare these items', 'Validated comparison']
    assert b'Synthetic extraction instructions' in processes[0].inputs[0]


def test_timeout_terminates_native_process_and_allows_a_new_explicit_turn(store, monkeypatch):
    session = store.create("claude")
    store.send(session, "Question", uid(1), timeout=30)
    processes = fake_cli(monkeypatch, [], timeout=True)
    ticks = iter([0, 31])
    # State locks use monotonic too; only replace once the running claim is written.
    original_write = agents.write_json
    def write(path, data):
        original_write(path, data)
        if data.get("status") == "running":
            monkeypatch.setattr(agents, "time", SimpleNamespace(
                time=agents.time.time, sleep=agents.time.sleep, monotonic=lambda: next(ticks, 100)))
    monkeypatch.setattr(agents, "write_json", write)
    agents.run_turn(store.storage, session.id, uid(1))
    assert processes[0].killed
    assert store.result(session.id, uid(1))["status"] == "failed"
    assert "time or output limit" in store.result(session.id, uid(1))["error"]
    assert read_json(store.folder(session.id) / "session.json")["active"] is None


def test_unfinished_turn_prevents_parallel_send_and_restore_does_not_dispatch(store):
    session = store.create("codex")
    store.send(session, "Question", uid(1))
    restored = agents.AgentSessions(store.storage)
    assert restored.discover()[0].managed
    with pytest.raises(ChatError, match="unfinished"):
        restored.send(session, "Another question", uid(2))
    assert len(restored.history(session)) == 1


def test_parser_excludes_tools_and_private_errors_and_accepts_structured_reply(tmp_path):
    path = tmp_path / "events.jsonl"
    guide = {"summary": "Synthetic guide", "steps": [], "sources": [], "caveats": []}
    events = [{"type": "item.completed", "item": {"type": "command_execution", "output": "private"}},
              {"type": "item.completed", "item": None},
              {"type": "result", "structured_output": guide, "session_id": uid(1)},
              {"type": "error", "message": "private"}]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n{torn", encoding="utf-8")
    native, body, structured, failed = agents.output(path)
    assert native == uid(1) and not body and structured == guide and failed


def test_codex_schema_output_follows_progress_messages(tmp_path):
    path = tmp_path / "events.jsonl"
    guide = {"summary": "Synthetic guide", "steps": [], "sources": [], "caveats": []}
    events = [{"type": "item.completed", "item": {"type": "agent_message", "id": str(i), "text": text}}
              for i, text in enumerate(["I will check the source.", json.dumps(guide)])]
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    assert agents.output(path)[2] == guide


def test_commands_disable_interactive_permission_prompts_and_use_fixed_arguments(store, tmp_path):
    schema = tmp_path / "schema.json"
    write_json(schema, {"type": "object"})
    codex = agents.command("codex", uid(1), schema=schema, effort="high")
    claude = agents.command("claude", uid(1), schema=schema, effort="high")
    assert codex[-1] == "-" and "read-only" in codex and "never" in codex and "--search" in codex
    assert "--resume" in claude and "dontAsk" in claude
    assert "Bash" not in " ".join(claude)
    with pytest.raises(ChatError):
        agents.command("unknown")


TOOLS = {"command": "synthetic-pythonw", "args": ["-m", "wow_helper", "published-tools", "serve", "--grant-id", uid(5)],
         "env": {"PYTHONPATH": "synthetic-checkout", "WOW_HELPER_TOOL_TOKEN": "synthetic-token-" + "x" * 32}}


def test_published_tools_attach_to_one_invocation_without_the_token_in_arguments(store):
    claude = agents.command("claude", tools=TOOLS)
    codex = agents.command("codex", tools=TOOLS)
    assert not any("synthetic-token" in arg for arg in claude + codex)
    config = json.loads(claude[claude.index("--mcp-config") + 1])
    assert config == {"mcpServers": {"wow_journal": {
        "type": "stdio", "command": "synthetic-pythonw", "args": TOOLS["args"],
        "env": {"PYTHONPATH": "synthetic-checkout", "WOW_HELPER_TOOL_TOKEN": "${WOW_HELPER_TOOL_TOKEN}"}}}}
    assert "--strict-mcp-config" in claude
    assert claude[claude.index("--allowedTools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch,mcp__wow_journal"
    assert claude[claude.index("--tools") + 1] == "Read,Glob,Grep,WebSearch,WebFetch"
    overrides = [codex[i + 1] for i, arg in enumerate(codex[:codex.index("exec")]) if arg == "-c"]
    assert 'mcp_servers.wow_journal.command="synthetic-pythonw"' in overrides
    assert "mcp_servers.wow_journal.args=" + json.dumps(TOOLS["args"]) in overrides
    assert 'mcp_servers.wow_journal.env={PYTHONPATH = "synthetic-checkout"}' in overrides
    assert 'mcp_servers.wow_journal.env_vars=["WOW_HELPER_TOOL_TOKEN"]' in overrides
    assert "-s" in codex and "read-only" in codex


def test_commands_without_published_tools_are_unchanged(store):
    assert "--mcp-config" not in agents.command("claude")
    assert not any("mcp_servers" in arg for arg in agents.command("codex"))


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_turn_passes_an_active_grant_token_only_through_the_environment(tmp_path, monkeypatch, provider):
    from wow_helper import publications
    monkeypatch.setattr(agents, "codex_executable", lambda: "synthetic-codex")
    monkeypatch.setattr(agents, "claude_command", lambda: ["synthetic-claude"])
    monkeypatch.setattr(publications, "ROOT", tmp_path)
    chat_state = tmp_path / ".runtime" / "chat"
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *args, **kwargs: object())
    store = agents.AgentSessions(chat_state / "agents")
    session = store.create(provider, startup="Synthetic startup context", creation_id=uid(20))
    grant = publications.PublicationService(chat_state).create(provider, session.id)["grant_id"]
    store.send(session, "Synthetic question", uid(21))
    events = ([{"type": "item.completed", "item": {"type": "agent_message", "text": "Answer"}}] if provider == "codex"
              else [{"type": "result", "is_error": False, "result": "Answer"}])
    processes = fake_cli(monkeypatch, events)
    agents.run_turn(store.storage, session.id, uid(21))
    token = publications.PublicationService(chat_state).private_setup(grant)["env"]["WOW_HELPER_TOOL_TOKEN"]
    assert processes[0].kwargs["env"]["WOW_HELPER_TOOL_TOKEN"] == token
    assert not any(token in arg for arg in processes[0].args) and grant in " ".join(processes[0].args)
    publications.PublicationService(chat_state).revoke(grant)
    monkeypatch.setattr(agents.subprocess, "Popen", lambda *args, **kwargs: object())
    store.send(session, "Second question", uid(22))
    processes = fake_cli(monkeypatch, events)
    agents.run_turn(store.storage, session.id, uid(22))
    assert processes[0].kwargs.get("env") is None and grant not in " ".join(processes[0].args)
