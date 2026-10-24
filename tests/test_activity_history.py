"""Synthetic outcome records; no provider, game, or real account data."""

from concurrent.futures import ThreadPoolExecutor
import json
import uuid

import pytest

from wow_helper.activity_history import ActivityHistory, MAX_ACTIONS
from wow_helper.chat import ChatError, ChatService, Session, write_json


def source(number=1):
    return {"type": "chat", "provider": "codex", "session_id": str(uuid.UUID(int=1)),
            "request_id": str(uuid.UUID(int=number))}


def test_restart_and_repeated_receipts_preserve_dismissal_and_manual_history(tmp_path):
    store = ActivityHistory(tmp_path)
    key = store.record(source(), "received", "Synthetic conversation", 1000)
    store.act(key, "read")
    store.act(key, "read")
    store.act(key, "dismiss")
    restored = ActivityHistory(tmp_path)
    for _ in range(4):
        restored.record(source(), "received", "Renamed source", 1000)
    assert restored.entries() == []
    assert len(restored.entries(True)) == 1
    assert [a["action"] for a in restored.load()["actions"]] == ["read", "dismiss"]
    restored.act(key, "restore")
    assert restored.entries()[0]["read"]
    assert "body" not in restored.path.read_text()


def test_concurrent_windows_do_not_lose_outcomes_or_dismissals(tmp_path):
    def save(number):
        store = ActivityHistory(tmp_path)
        key = store.record(source(number), "failed", "Synthetic", 1000 + number)
        store.act(key, "dismiss")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(1, 21)))
    store = ActivityHistory(tmp_path)
    assert len(store.entries(True)) == 20
    assert store.entries() == []
    assert len(store.load()["actions"]) == 20


def test_retention_does_not_resurrect_evicted_receipts(monkeypatch):
    from wow_helper import activity_history as module
    monkeypatch.setattr(module, "MAX_EVENTS", 3)
    store = ActivityHistory()
    for i in range(1, 5):
        store.record(source(i), "failed", "Synthetic", 1000 + i)
    assert len(store.entries()) == 3
    store.record(source(1), "failed", "Old synthetic request", 1001)
    assert len(store.entries()) == 3
    assert all(e["source"] != source(1) for e in store.entries())
    key = store.entries()[0]["id"]
    for _ in range(MAX_ACTIONS + 2):
        store.act(key, "retry")
    assert len(store.load()["actions"]) == MAX_ACTIONS


@pytest.mark.parametrize("raw", ["not-json", "[]", '{"version": 9}',
                                 json.dumps({"version": 1, "floor": 0, "events": [{}], "actions": []})])
def test_corrupt_history_is_never_overwritten(tmp_path, raw):
    store = ActivityHistory(tmp_path)
    store.path.write_text(raw)
    with pytest.raises(ChatError, match="kept"):
        store.record(source(), "completed", "Synthetic", 1000)
    assert store.path.read_text() == raw


def test_progress_and_bad_references_cannot_be_outcomes():
    store = ActivityHistory()
    for outcome in ("running", "queued", "acknowledged"):
        with pytest.raises(ChatError):
            store.record(source(), outcome, "Synthetic", 1000)
    with pytest.raises(ChatError):
        store.record({**source(), "session_id": "../outside"}, "failed", "Synthetic", 1000)
    assert store.entries() == []


def test_retry_body_is_scoped_and_does_not_send(tmp_path):
    service = ChatService(tmp_path)
    session = Session("codex", source()["session_id"], "Synthetic", "", "idle")
    request = source()["request_id"]
    path = tmp_path / "outbox" / (request + ".json")
    write_json(path, {"provider": "codex", "session": session.id, "body": "Synthetic request"})
    assert service.retry_body(session, request) == "Synthetic request"
    other = Session("codex", str(uuid.UUID(int=2)), "Other synthetic", "", "idle")
    assert service.retry_body(other, request) == ""
    write_json(path, {"body": "x" * 200_001})
    assert service.retry_body(session, request) == ""
    service.close()
