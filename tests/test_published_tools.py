"""Synthetic F18 MCP stdio checks: authentication, framing, bounds and data isolation.

Uses the in-process handler and serve loop with byte streams, plus one windowless
subprocess round trip. All records are hand-written synthetic values in tmp_path.
"""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

from test_publications import JOURNAL, NOTE, OTHER_SESSION, SESSION, T0, env  # noqa: F401  (fixture)
from wow_helper import published_tools
from wow_helper.chat import ChatError
from wow_helper.publications import UNAVAILABLE, encode
from wow_helper.published_tools import MAX_REQUEST_BYTES, PROTOCOL_VERSION, PublishedTools, ProtocolError, serve

REPO = Path(__file__).resolve().parents[1]
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "synthetic", "version": "0"}}}
READY = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def call(request_id, name, arguments=None):
    params = {"name": name} if arguments is None else {"name": name, "arguments": arguments}
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": params}


def frames(*messages):
    return b"".join(m if isinstance(m, bytes) else encode(m) + b"\n" for m in messages)


def run(env, grant_id, token, *messages, source=None):
    target = io.BytesIO()
    code = serve(grant_id, source=source or io.BytesIO(frames(*messages)), target=target,
                 service=env.service, token=token)
    raw = target.getvalue()
    assert raw == b"" or raw.endswith(b"\n")
    replies = [json.loads(line) for line in raw.splitlines()]
    for reply in replies:
        assert reply["jsonrpc"] == "2.0" and set(reply) in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"})
    return code, replies, raw


def published(env, note_id=NOTE, **note):
    env.note(note_id, **note)
    grant_id, token = env.grant()
    record_id = env.service.publish(grant_id, JOURNAL, note_id)["record_id"]
    return grant_id, token, record_id


def tool_result(reply):
    result = reply["result"]
    assert set(result) == {"content", "isError"} and len(result["content"]) == 1
    return result["isError"], result["content"][0]["text"]


def test_lifecycle_lists_and_reads_only_the_bound_grants_records(env):
    grant_id, token, record_id = published(env)
    code, replies, raw = run(env, grant_id, token, INIT, READY, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                             call(3, "list_published_records", {}), call(4, "read_published_record", {"record_id": record_id}),
                             {"jsonrpc": "2.0", "id": 5, "method": "ping"})
    assert code == 0
    assert [reply["id"] for reply in replies] == [1, 2, 3, 4, 5]
    assert replies[0]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert replies[0]["result"]["capabilities"] == {"tools": {"listChanged": False}}
    tools = replies[1]["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"list_published_records", "read_published_record"}
    assert all(tool["annotations"]["readOnlyHint"] and not tool["annotations"]["destructiveHint"] for tool in tools)
    error, text = tool_result(replies[2])
    assert not error and [r["record_id"] for r in json.loads(text)["records"]] == [record_id]
    error, text = tool_result(replies[3])
    data = json.loads(text)
    assert not error and data["record_id"] == record_id and data["data"]["note"] == "Synthetic advice for Testchar"
    assert replies[4]["result"] == {}
    for secret in (token, SESSION, JOURNAL, NOTE, str(env.root), "WOW_HELPER_TOOL_TOKEN"):
        assert secret.encode() not in raw


@pytest.mark.parametrize("token", ["", "z" * 43, None])
def test_wrong_or_missing_token_never_starts_a_session(env, token, capsys):
    grant_id, real, _ = published(env)
    code, replies, raw = run(env, grant_id, token, INIT, READY, call(2, "list_published_records", {}))
    assert code == 2 and raw == b""
    err = capsys.readouterr().err
    assert real not in err and (token or "§") not in err


def test_another_grants_token_cannot_select_its_records(env):
    grant_id, token, record_id = published(env)
    other_grant, other_token = env.grant(session=OTHER_SESSION)
    code, _, raw = run(env, grant_id, other_token, INIT)
    assert code == 2 and raw == b""
    code, replies, _ = run(env, other_grant, other_token, INIT, READY, call(2, "list_published_records", {}),
                           call(3, "read_published_record", {"record_id": record_id}))
    assert code == 0
    assert json.loads(tool_result(replies[1])[1]) == {"records": []}
    assert tool_result(replies[2]) == (True, UNAVAILABLE)


@pytest.mark.parametrize("state", ["expired", "revoked", "before_creation"])
def test_expired_or_revoked_grants_cannot_start(env, state):
    grant_id, token, _ = published(env)
    if state == "expired":
        env.clock.now = T0 + 24 * 3600
    elif state == "before_creation":
        env.clock.now = T0 - 60
    else:
        env.service.revoke(grant_id)
    code, _, raw = run(env, grant_id, token, INIT)
    assert code == 2 and raw == b""


def test_methods_require_initialization_in_order(env):
    grant_id, token, _ = published(env)
    code, replies, _ = run(env, grant_id, token,
                           {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                           dict(INIT, id=2),
                           {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                           dict(INIT, id=4),
                           READY,
                           {"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    assert code == 0
    assert replies[0]["error"]["code"] == -32000
    assert "result" in replies[1]
    assert replies[2]["error"]["code"] == -32000
    assert replies[3]["error"]["code"] == -32602
    assert "tools" in replies[4]["result"]


@pytest.mark.parametrize("params", [{}, {"protocolVersion": "", "capabilities": {}, "clientInfo": {}},
                                    {"protocolVersion": PROTOCOL_VERSION, "capabilities": [], "clientInfo": {}},
                                    {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}}])
def test_initialize_requires_declared_fields(env, params):
    grant_id, token, _ = published(env)
    _, replies, _ = run(env, grant_id, token, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params},
                        {"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert replies[0]["error"]["code"] == -32602
    assert replies[1]["error"]["code"] == -32000


MALFORMED = [
    (b"{not json\n", -32600),
    (b"[]\n", -32600),
    (frames([dict(INIT, id=9)]), -32600),
    (b'{"jsonrpc":"2.0","id":9,"id":10,"method":"ping"}\n', -32600),
    (frames({"jsonrpc": "1.0", "id": 9, "method": "ping"}), -32600),
    (frames({"jsonrpc": "2.0", "id": 9}), -32600),
    (frames({"jsonrpc": "2.0", "id": 9, "method": "ping", "extra": 1}), -32600),
    (frames({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": []}), -32602),
    (frames({"jsonrpc": "2.0", "id": True, "method": "ping"}), -32600),
    (frames({"jsonrpc": "2.0", "id": 1.5, "method": "ping"}), -32600),
    (frames({"jsonrpc": "2.0", "id": None, "method": "ping"}), -32600),
    (frames({"jsonrpc": "2.0", "id": "x" * 129, "method": "ping"}), -32600),
    (frames({"jsonrpc": "2.0", "id": 2 ** 60, "method": "ping"}), -32600),
    (b"\xff\xfe\n", -32600),
    (frames({"jsonrpc": "2.0", "id": 9, "method": "resources/list"}), -32601),
    (frames({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {"cursor": "x"}}), -32602),
    (frames({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "read_published_record", "arguments": [], }}), -32602),
    (frames({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "x", "path": "/"}}), -32602),
    (frames(call(9, "read_file", {"path": "../tool-publications.json"})), -32602),
    (frames(call(9, "list_published_records", {"grant_id": str(uuid.UUID(int=5))})), -32602),
    (frames(call(9, "read_published_record", {"record_id": 7})), -32602),
    (frames(call(9, "read_published_record", {"record_id": "x", "grant_id": "y"})), -32602),
    (frames(call(9, "read_published_record")), -32602),
]


@pytest.mark.parametrize("raw,code", MALFORMED)
def test_malformed_requests_get_fixed_errors_and_the_connection_continues(env, raw, code):
    grant_id, token, record_id = published(env)
    status, replies, out = run(env, grant_id, token, INIT, READY, raw, {"jsonrpc": "2.0", "id": 50, "method": "ping"})
    assert status == 0
    assert len(replies) == 3
    assert replies[1]["error"]["code"] == code
    assert replies[2] == {"jsonrpc": "2.0", "id": 50, "result": {}}
    assert b"Synthetic advice" not in out and token.encode() not in out


@pytest.mark.parametrize("record_id", ["../tool-publications.json", "..\\tool-access\\x.json", "", "*",
                                       str(uuid.UUID(int=999)), "C:/Windows/win.ini"])
def test_unpublished_or_path_like_record_ids_return_the_fixed_unavailable_result(env, record_id):
    grant_id, token, _ = published(env)
    _, replies, out = run(env, grant_id, token, INIT, READY, call(2, "read_published_record", {"record_id": record_id}))
    assert tool_result(replies[1]) == (True, UNAVAILABLE)
    assert b"Synthetic advice" not in out


def test_notifications_never_return_data(env):
    grant_id, token, record_id = published(env)
    note = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "read_published_record", "arguments": {"record_id": record_id}}}
    _, replies, out = run(env, grant_id, token, INIT, READY, note, {"jsonrpc": "2.0", "method": "tools/list"})
    assert len(replies) == 1 and b"Synthetic advice" not in out


def test_removal_and_expiry_apply_to_the_next_request_on_an_open_connection(env):
    grant_id, token, record_id = published(env)
    env.note(str(uuid.UUID(int=11)), text="Second synthetic note")
    second = env.service.publish(grant_id, JOURNAL, str(uuid.UUID(int=11)))["record_id"]
    steps = iter([
        (None, INIT), (None, READY),
        (None, call(2, "read_published_record", {"record_id": record_id})),
        (lambda: env.service.revoke(grant_id, record_id), call(3, "read_published_record", {"record_id": record_id})),
        (None, call(4, "list_published_records", {})),
        (lambda: setattr(env.clock, "now", T0 + 24 * 3600), call(5, "read_published_record", {"record_id": second})),
        (None, {"jsonrpc": "2.0", "id": 6, "method": "tools/list"}),
        (None, {"jsonrpc": "2.0", "id": 7, "method": "ping"}),
    ])

    class Source:
        def readline(self, limit):
            try:
                action, message = next(steps)
            except StopIteration:
                return b""
            if action:
                action()
            return frames(message)

    code, replies, out = run(env, grant_id, token, source=Source())
    assert code == 0
    assert tool_result(replies[1])[0] is False
    assert tool_result(replies[2]) == (True, UNAVAILABLE)
    assert [r["record_id"] for r in json.loads(tool_result(replies[3])[1])["records"]] == [second]
    assert tool_result(replies[4]) == (True, UNAVAILABLE)
    assert replies[5]["error"] == {"code": -32001, "message": UNAVAILABLE}
    assert replies[6]["error"] == {"code": -32001, "message": UNAVAILABLE}


def test_oversized_request_is_refused_and_closes_the_connection(env):
    grant_id, token, _ = published(env)
    big = b'{"jsonrpc":"2.0","id":9,"method":"ping","params":{"_meta":"' + b"x" * MAX_REQUEST_BYTES + b'"}}\n'
    code, replies, _ = run(env, grant_id, token, INIT, READY, big, {"jsonrpc": "2.0", "id": 10, "method": "ping"})
    assert code == 2
    assert len(replies) == 2 and replies[1]["error"]["code"] == -32600 and replies[1]["id"] is None


def test_request_at_the_frame_limit_is_accepted(env):
    grant_id, token, _ = published(env)
    prefix, suffix = b'{"jsonrpc":"2.0","id":9,"method":"ping","params":{"_meta":"', b'"}}\n'
    exact = prefix + b"x" * (MAX_REQUEST_BYTES - len(prefix) - len(suffix)) + suffix
    assert len(exact) == MAX_REQUEST_BYTES
    code, replies, _ = run(env, grant_id, token, INIT, READY, exact)
    assert code == 0 and replies[1] == {"jsonrpc": "2.0", "id": 9, "result": {}}


def test_unterminated_final_frame_is_refused(env):
    grant_id, token, _ = published(env)
    code, replies, _ = run(env, grant_id, token, INIT, READY, b'{"jsonrpc":"2.0","id":9,"method":"ping"}')
    assert code == 2 and replies[-1]["error"]["code"] == -32600


def test_oversized_response_is_replaced_by_a_bounded_error(env, monkeypatch):
    grant_id, token, record_id = published(env)
    monkeypatch.setattr(published_tools, "MAX_RESPONSE_BYTES", 400)
    _, replies, out = run(env, grant_id, token, INIT, READY, call(2, "read_published_record", {"record_id": record_id}))
    assert replies[1]["error"]["code"] == -32002 and replies[1]["id"] == 2
    assert all(len(line) <= 400 for line in out.splitlines())
    assert b"Synthetic advice" not in out


def test_largest_publishable_record_still_fits_a_response(env):
    # Quotes and control characters double or septuple in nested JSON encoding.
    text = ('"\\' * 14_000) + ("\x01" * 1_000)
    grant_id, token, record_id = published(env, evidence={"text": text})
    record = env.service.query(grant_id, token, record_id)
    assert len(encode(record["data"])) > 60_000
    _, replies, out = run(env, grant_id, token, INIT, READY, call(2, "read_published_record", {"record_id": record_id}))
    error, body = tool_result(replies[1])
    assert not error and json.loads(body)["data"]["evidence"]["text"] == text
    assert max(len(line) for line in out.splitlines()) <= published_tools.MAX_RESPONSE_BYTES


def test_connection_frame_count_is_bounded(env, monkeypatch):
    grant_id, token, _ = published(env)
    monkeypatch.setattr(published_tools, "MAX_REQUESTS", 3)
    ping = {"jsonrpc": "2.0", "id": 9, "method": "ping"}
    code, replies, _ = run(env, grant_id, token, INIT, READY, ping, ping, ping)
    assert code == 0 and len(replies) == 2


def test_handler_rechecks_authorization_for_every_data_method(env):
    grant_id, token, record_id = published(env)
    calls = []
    original = env.service.authorize

    def counted(*args):
        calls.append(args)
        return original(*args)

    env.service.authorize = counted
    server = PublishedTools(env.service, grant_id, token)
    server.handle("initialize", INIT["params"])
    server.ready = True
    server.handle("tools/list", {})
    server.handle("ping", {})
    assert len(calls) == 3
    env.service.revoke(grant_id)
    with pytest.raises(ChatError, match=UNAVAILABLE):
        server.handle("tools/list", {})
    assert server.handle("tools/call", {"name": "list_published_records", "arguments": {}}) == {
        "content": [{"type": "text", "text": UNAVAILABLE}], "isError": True}
    with pytest.raises(ProtocolError):
        server.handle("tools/call", {"name": "read_published_record", "arguments": {"record_id": record_id, "x": 1}})


def test_windowless_stdio_round_trip(env):
    env.clock.now = time.time()
    grant_id, token, record_id = published(env)
    bootstrap = ("import sys; from pathlib import Path; from wow_helper import publications, published_tools; "
                 "publications.ROOT = Path(sys.argv[1]); "
                 "sys.exit(published_tools.serve(sys.argv[2], service=publications.PublicationService("
                 "Path(sys.argv[1]) / '.runtime' / 'chat')))")
    executable = Path(sys.executable)
    flags = 0
    if os.name == "nt":
        executable = executable.with_name("pythonw.exe")
        flags = subprocess.CREATE_NO_WINDOW
    child_env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", published_tools.TOKEN_ENV}}
    child_env.update(PYTHONPATH=str(REPO), **{published_tools.TOKEN_ENV: token})
    request = frames(INIT, READY, call(2, "read_published_record", {"record_id": record_id}),
                     call(3, "read_published_record", {"record_id": str(uuid.UUID(int=999))}))
    done = subprocess.run([str(executable), "-c", bootstrap, str(env.root), grant_id], input=request,
                          capture_output=True, timeout=60, cwd=str(REPO), env=child_env, creationflags=flags)
    assert done.returncode == 0 and done.stderr == b""
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert json.loads(tool_result(replies[1])[1])["record_id"] == record_id
    assert tool_result(replies[2]) == (True, UNAVAILABLE)
    assert token.encode() not in done.stdout and str(env.root).encode() not in done.stdout
