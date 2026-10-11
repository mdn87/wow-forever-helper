"""Behavior tests with synthetic sessions and fake delivery; never contact an agent."""

import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from wow_helper import chat, codex_chat, __main__ as cli
from wow_helper.chat import ChatError, ChatService, Session

FIXTURES = Path(__file__).parent / "fixtures"
SESSION = str(uuid.UUID(int=0))
OTHER = str(uuid.UUID(int=1))
REQUEST = str(uuid.UUID(int=2))


class FakeCodex:
    def __init__(self):
        self.open = True
        self.sent = []
        self.fail = False

    def sessions(self):
        if self.fail:
            raise ChatError("Codex is unavailable.")
        return [{"id": SESSION, "name": "Synthetic Codex", "cwd": "ExampleProject",
                 "status": {"type": "idle"}}] if self.open else []

    def messages(self, _session):
        return json.loads((FIXTURES / "chat_codex_items.json").read_text())["items"]

    def send(self, session, text):
        self.sent.append((session, text))

    def close(self):
        pass


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "claude_sessions", lambda _home: [])
    return ChatService(tmp_path / "chat", FakeCodex())


def test_discovery_and_text_only_codex_history(service):
    sessions, notices = service.discover()
    assert notices == []
    assert sessions[0].project == "ExampleProject"
    assert [(m.role, m.text) for m in service.history(sessions[0])] == [
        ("user", "Which quest should I do next?"),
        ("assistant", "Check your nearby turn-ins first."),
    ]


def test_claude_transcript_omits_tools_thinking_sidechains_and_partial_lines(tmp_path):
    path = tmp_path / "synthetic.jsonl"
    path.write_bytes((FIXTURES / "chat_claude.jsonl").read_bytes() + b'{"type":"assistant"')
    messages = chat.claude_messages(path)
    assert [(m.role, m.text) for m in messages] == [
        ("user", "Which quest should I do next?"),
        ("assistant", "Check your nearby turn-ins first."),
    ]


def test_send_targets_one_session_and_refuses_duplicate_after_restart(service):
    session = service.discover()[0][0]
    text = 'A literal message: "hello" & $(example)\nNext line: café'
    assert service.send(session, text, REQUEST) == "queued"
    assert service.codex.sent == [(SESSION, text)]
    restarted = ChatService(service.state, service.codex)
    with pytest.raises(ChatError, match="already attempted"):
        restarted.send(session, text, REQUEST)
    assert len(service.codex.sent) == 1
    assert text not in (service.state / "outbox" / (REQUEST + ".json")).read_text()


def test_disconnect_refuses_send_without_recording_or_calling_cli(service):
    session = service.discover()[0][0]
    service.codex.open = False
    with pytest.raises(ChatError, match="no longer available"):
        service.send(session, "Hello", REQUEST)
    assert not service.state.exists()
    assert service.codex.sent == []


@pytest.mark.parametrize("text", ["", "  ", "x" * 6001, "hello\0world"])
def test_invalid_messages_never_send(service, text):
    with pytest.raises(ChatError):
        service.send(service.discover()[0][0], text, REQUEST)
    assert service.codex.sent == []


def test_uncertain_delivery_is_not_retried(service, monkeypatch):
    calls = []
    def fail(*args):
        calls.append(args)
        raise ChatError("Delivery is uncertain.")
    monkeypatch.setattr(service.codex, "send", fail)
    session = service.discover()[0][0]
    with pytest.raises(ChatError, match="uncertain"):
        service.send(session, "Hello", REQUEST)
    with pytest.raises(ChatError, match="already attempted"):
        service.send(session, "Hello", REQUEST)
    assert len(calls) == 1
    assert chat.read_json(service.state / "outbox" / (REQUEST + ".json"))["status"] == "uncertain"


def test_claude_discovery_rejects_stale_and_malformed_sessions(tmp_path, monkeypatch):
    registry = tmp_path / "sessions"
    registry.mkdir()
    monkeypatch.setattr(chat, "live_pids", lambda: {123})
    monkeypatch.setattr(chat, "pid_alive", lambda pid, pids: pid in pids)
    data = {"sessionId": SESSION, "pid": 123, "kind": "interactive", "status": "idle",
            "cwd": "ExampleProject", "name": "Synthetic Claude"}
    chat.write_json(registry / "live.json", data)
    chat.write_json(registry / "stale.json", {**data, "sessionId": OTHER, "pid": 456})
    (registry / "broken.json").write_text("{")
    chat.write_json(registry / "bad-id.json", {**data, "sessionId": "../../synthetic"})
    chat.write_json(registry / "bad-cwd.json", {**data, "cwd": ["synthetic"]})
    chat.write_json(registry / "bad-status.json", {**data, "status": ["idle"]})
    project = tmp_path / "projects" / "synthetic-project"
    project.mkdir(parents=True)
    (project / (SESSION + ".jsonl")).write_bytes((FIXTURES / "chat_claude.jsonl").read_bytes())
    sessions = chat.claude_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0].title == "Synthetic Claude"
    assert sessions[0].transcript == project / (SESSION + ".jsonl")


def test_claude_remains_available_when_codex_is_down(service, monkeypatch):
    session = Session("claude", OTHER, "Synthetic Claude", "ExampleProject", "idle")
    monkeypatch.setattr(chat, "claude_sessions", lambda _home: [session])
    service.codex.fail = True
    sessions, notices = service.discover()
    assert sessions == [session]
    assert notices == ["Codex is unavailable."]


def test_claude_queue_poll_ack_and_session_isolation(service, monkeypatch):
    session = Session("claude", OTHER, "Synthetic Claude", "ExampleProject", "idle")
    monkeypatch.setattr(chat, "claude_sessions", lambda _home: [session])
    assert service.send(session, "Synthetic question", REQUEST) == "waiting for Claude to poll"
    assert service.codex.sent == []
    assert chat.poll_claude(SESSION, state=service.state, wait=0)["status"] == "waiting"
    result = chat.poll_claude(OTHER, state=service.state, wait=0)
    assert result["status"] == "received"
    assert "Synthetic question" not in json.dumps(result)
    incoming = service.state / "claude" / OTHER / "incoming.json"
    assert chat.read_json(incoming)["text"] == "Synthetic question"
    assert chat.poll_claude(OTHER, state=service.state, wait=0)["status"] == "awaiting_ack"
    assert chat.acknowledge_claude(OTHER, REQUEST, state=service.state)["status"] == "acknowledged"
    assert chat.poll_claude(OTHER, state=service.state, wait=0)["status"] == "waiting"


def test_second_message_cannot_overwrite_unacknowledged_incoming(service, monkeypatch):
    session = Session("claude", OTHER, "Synthetic Claude", "ExampleProject", "idle")
    monkeypatch.setattr(chat, "claude_sessions", lambda _home: [session])
    service.send(session, "First", REQUEST)
    service.send(session, "Second", str(uuid.UUID(int=3)))
    chat.poll_claude(OTHER, state=service.state, wait=0)
    assert chat.poll_claude(OTHER, state=service.state, wait=0)["status"] == "awaiting_ack"
    with pytest.raises(ChatError, match="not the current"):
        chat.acknowledge_claude(OTHER, SESSION, state=service.state)
    assert chat.read_json(service.state / "claude" / OTHER / "incoming.json")["text"] == "First"


def test_concurrent_poll_refuses_and_lock_releases_after_error(tmp_path):
    folder = tmp_path / "claude" / SESSION
    with chat.inbox_lock(folder):
        with pytest.raises(ChatError, match="already has a poll"):
            chat.poll_claude(SESSION, state=tmp_path, wait=0)
    assert chat.poll_claude(SESSION, state=tmp_path, wait=0)["status"] == "waiting"


def test_poll_wait_is_bounded_without_sleeping_in_test(tmp_path):
    now = [0.0]
    def sleep(seconds):
        now[0] += seconds
    assert chat.poll_claude(SESSION, state=tmp_path, wait=0.5,
                           clock=lambda: now[0], sleep=sleep)["status"] == "waiting"
    assert now[0] == 0.5
    for value in [-1, 51, float("nan")]:
        with pytest.raises(ChatError):
            chat.poll_claude(SESSION, state=tmp_path, wait=value)


def test_claude_history_merges_human_inbox_messages_in_order(service):
    session = Session("claude", OTHER, "Synthetic Claude", "ExampleProject", "idle",
                      FIXTURES / "chat_claude.jsonl")
    chat.write_json(service.state / "claude" / OTHER / "inbox" / (REQUEST + ".json"),
                    {"id": REQUEST, "text": "A follow-up", "created_at": 1767268802.5})
    messages = service.history(session)
    assert [m.text for m in messages] == ["Which quest should I do next?", "A follow-up", "Check your nearby turn-ins first."]


def test_cli_poll_does_not_print_transcript_or_machine_details(monkeypatch, capsys):
    monkeypatch.setattr(chat, "poll_claude", lambda *a, **k: {"status": "waiting"})
    assert cli.main(["chat-poll", "--session", SESSION, "--wait", "0"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "waiting"}
    def fail(*a, **k):
        raise OSError("synthetic sensitive filesystem detail")
    monkeypatch.setattr(chat, "poll_claude", fail)
    assert cli.main(["chat-poll", "--session", SESSION]) == 3
    assert "sensitive" not in capsys.readouterr().out


def test_cli_chat_does_not_initialize_assistive_input(monkeypatch):
    from wow_helper import chat_window
    calls = []
    monkeypatch.setattr(chat_window, "launch", lambda **options: calls.append(options))
    monkeypatch.setattr(cli, "Assistant", lambda *_: pytest.fail("chat touched game input"))
    assert cli.main(["chat"]) == 0
    assert calls == [{"hotkey": "H", "restart": False}]
    assert cli.main(["chat", "--hotkey", "F10"]) == 0
    assert calls[-1] == {"hotkey": "F10", "restart": False}
    assert cli.main(["chat", "--restart"]) == 0
    assert calls[-1] == {"hotkey": "H", "restart": True}


def test_codex_send_uses_native_argv_and_never_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_chat, "codex_executable", lambda: "synthetic-codex.exe")
    monkeypatch.setattr(codex_chat.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0))
    body = 'hello & echo example | $(example) "quoted"\nUnicode: café'
    codex_chat.CodexClient().send(SESSION, body)
    args, options = calls[0]
    assert args == ["synthetic-codex.exe", "queue", "--thread", SESSION, "--message", body]
    assert options.get("shell", False) is False
    assert options["timeout"] == 20


def test_codex_rpc_refuses_mutating_methods():
    client = codex_chat.CodexClient()
    for method in ["thread/start", "thread/resume", "turn/start", "thread/shellCommand"]:
        with pytest.raises(ChatError, match="Unsupported"):
            client.rpc(method, {})


@pytest.mark.parametrize("invalid_utf8", [False, True])
def test_large_codex_frames_use_strict_native_decoding(monkeypatch, invalid_utf8):
    websocket = pytest.importorskip("websocket")
    import websocket._abnf as framing

    def frame(data):
        return websocket.ABNF(1, 0, 0, 0, websocket.ABNF.OPCODE_TEXT, 0, data).format()

    body = b'{"id": 2, "result": {"text": "' + b"x" * 5_000_000
    body += b'\xff"}}' if invalid_utf8 else 'café"}}'.encode("utf-8")

    class Pipe:
        closed = False
        data = frame(b'{"id": 1, "result": {}}') + frame(body)
        def __init__(self, _): pass
        def send(self, data): return len(data)
        def settimeout(self, _): pass
        def gettimeout(self): return 6
        def close(self): self.closed = True
        def recv(self, size):
            data, self.data = self.data[:size], self.data[size:]
            return data

    def connect(_url, *, socket, **options):
        ws = websocket.WebSocket(**options)
        ws.sock = socket
        ws.connected = True
        return ws

    validation_calls = []
    original = framing.validate_utf8
    def validate(data):
        validation_calls.append(len(data))
        return original(data)

    monkeypatch.setattr(framing, "validate_utf8", validate)
    monkeypatch.setattr(codex_chat, "codex_executable", lambda: "synthetic-codex.exe")
    monkeypatch.setattr(codex_chat.subprocess, "Popen", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(codex_chat, "PipeSocket", Pipe)
    monkeypatch.setattr(websocket, "create_connection", connect)
    client = codex_chat.CodexClient()
    try:
        if invalid_utf8:
            with pytest.raises(ChatError, match="connection closed"):
                client.rpc("thread/read", {})
            assert client.ws is None
        else:
            assert client.rpc("thread/read", {})["text"] == "x" * 5_000_000 + "café"
        assert validation_calls == []  # No byte-by-byte Python pass competing with Tk.
    finally:
        client.close()


def test_codex_loaded_sessions_are_paginated_and_children_excluded(monkeypatch):
    client = codex_chat.CodexClient()
    def rpc(method, params):
        if method == "thread/loaded/list":
            return {"data": [OTHER], "nextCursor": None} if params["cursor"] else {"data": [SESSION], "nextCursor": "next"}
        if params["threadId"] == OTHER:
            return {"thread": {"id": OTHER, "source": {"subAgent": "synthetic"}}}
        return {"thread": {"id": SESSION, "source": "cli", "status": {"type": "idle"}}}
    monkeypatch.setattr(client, "rpc", rpc)
    assert [s["id"] for s in client.sessions()] == [SESSION]


def test_rpc_ignores_unrelated_notifications_and_redacts_provider_errors():
    class Socket:
        def send(self, _): pass
        def settimeout(self, _): pass
        replies = iter([{"method": "synthetic/notice"}, {"id": 1, "error": {"message": "synthetic private provider detail"}}])
        def recv(self): return json.dumps(next(self.replies))
    client = codex_chat.CodexClient()
    client.ws = Socket()
    with pytest.raises(ChatError) as error:
        client.rpc("thread/loaded/list", {})
    assert "private" not in str(error.value)
    assert client.ws is None


def test_connection_instructions_target_the_selected_claude_session():
    content = chat.claude_connection_text(Session("claude", OTHER, "Synthetic Claude", "ExampleProject", "idle"))
    assert f"chat-poll --session {OTHER}" in content
    assert f"chat-ack --session {OTHER}" in content
    assert "must not trigger game input" in content


@pytest.mark.parametrize("bad", ["../synthetic", "", None])
def test_invalid_identifiers_refuse_before_touching_disk(tmp_path, bad):
    with pytest.raises(ChatError):
        chat.poll_claude(bad, state=tmp_path, wait=0)
    assert list(tmp_path.iterdir()) == []
