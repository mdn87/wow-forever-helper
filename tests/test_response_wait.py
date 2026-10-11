"""Synthetic response receipts; no provider requests or native transcripts."""

import uuid

from wow_helper.chat import ChatService, Message, Session, write_json
from wow_helper.response_wait import ResponseWait, elapsed

REQUEST = str(uuid.UUID(int=2))


def test_attached_reply_requires_the_new_matching_user_turn():
    wait = ResponseWait(REQUEST, "Where next?", started=1000, previous_ids=frozenset({"old-user", "old-reply"}))
    old = [Message("old-user", "user", "Where next?"), Message("old-reply", "assistant", "Old answer")]
    assert wait.observe(old + [Message("late-reply", "assistant", "Still the previous turn")]) is None
    messages = old + [Message("new-user", "user", "Where next?")]
    assert wait.observe(messages) is None  # Delivery is not a response.
    assert wait.observe(messages + [Message("new-reply", "assistant", "Next step")]) == "received"


def test_two_identical_requests_do_not_claim_the_same_receipt():
    first, second = ResponseWait(REQUEST, "Next?"), ResponseWait(str(uuid.UUID(int=3)), "Next?")
    messages = [Message("first", "user", "Next?"), Message("reply", "assistant", "First answer")]
    assert first.observe(messages) == "received"
    assert second.observe(messages, claimed={first.user_id}) is None
    assert second.user_id is None
    assert second.observe(messages) is None  # The first wait has already been removed.


def test_owned_progress_does_not_end_a_wait_before_terminal_receipt():
    wait = ResponseWait(REQUEST, "Next?")
    messages = [Message("user", "user", "Next?"), Message("progress", "assistant", "Checking sources")]
    assert wait.observe(messages, "running") is None
    assert wait.observe(messages, "unconfirmed") is None
    for status in ("completed", "failed", "cancelled", "interrupted"):
        assert wait.observe(messages, status) == status


def test_wait_restore_keeps_elapsed_time_and_rejects_malformed_state():
    wait = ResponseWait(REQUEST, "Next?", 1000, frozenset({"previous"}), "receipt")
    assert ResponseWait.restore(wait.snapshot()) == wait
    assert elapsed(1000, 1075) == "1:15"
    assert elapsed(1000, 4661) == "1:01:01"
    assert elapsed(1000, 900) == "0:00"
    for raw in (None, [], {}, {**wait.snapshot(), "request_id": "invalid"},
                {**wait.snapshot(), "started": float("nan")}, {**wait.snapshot(), "started": float("inf")}):
        assert ResponseWait.restore(raw) is None


def test_managed_request_receipts_detect_failure_and_interruption(tmp_path, monkeypatch):
    from wow_helper import chat
    session = Session("codex", str(uuid.UUID(int=1)), "Synthetic", "ExampleProject", "running", managed=True)
    service = ChatService(tmp_path)
    path = service.agents.folder(session.id) / "requests" / (REQUEST + ".json")
    monkeypatch.setattr(chat.time, "time", lambda: 1000)
    assert service.response_status(session, REQUEST) == "unconfirmed"
    write_json(path, {"status": "running", "heartbeat": 980})
    assert service.response_status(session, REQUEST) == "running"
    write_json(path, {"status": "running", "heartbeat": 960})
    assert service.response_status(session, REQUEST) == "interrupted"
    write_json(path, {"status": "completed", "heartbeat": 960})
    assert service.response_status(session, REQUEST) == "completed"
    attached = Session("claude", session.id, "Synthetic", "", "idle")
    assert service.response_status(attached, REQUEST) == "queued"
    claim = tmp_path / "claude" / session.id / "claimed" / (REQUEST + ".json")
    write_json(claim, {"status": "claimed"})
    assert service.response_status(attached, REQUEST) == "claimed"
    write_json(claim, {"status": "acknowledged"})
    assert service.response_status(attached, REQUEST) == "acknowledged"
