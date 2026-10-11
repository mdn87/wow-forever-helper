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
