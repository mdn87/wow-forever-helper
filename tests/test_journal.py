"""Synthetic linked notes; no provider history or game data."""

import json
import uuid

import pytest

from wow_helper.chat import ChatError
from wow_helper.journal import JournalService

JOURNAL = str(uuid.UUID(int=0))
NOTE = str(uuid.UUID(int=1))
SOURCE = {"provider": "codex", "session_id": str(uuid.UUID(int=2)), "message_id": "synthetic-reply"}


def test_legacy_open_is_read_only_and_ids_survive_explicit_save(tmp_path):
    service = JournalService(tmp_path)
    path = service.path(JOURNAL)
    path.parent.mkdir()
    raw = '{"name":"Example","entries":[{"at":"unknown","text":"Old note"}]}'
    path.write_text(raw)
    first = service.load(JOURNAL)
    assert first["entries"][0]["id"] == service.load(JOURNAL)["entries"][0]["id"]
    assert path.read_text() == raw
    service.add(JOURNAL, "Example", "New note")
    assert service.load(JOURNAL)["entries"][0] == first["entries"][0]
    assert json.loads(path.read_text())["version"] == 1


def test_linked_save_is_frozen_idempotent_and_conflicts_do_not_write(tmp_path):
    service = JournalService(tmp_path)
    evidence = {"text": "Historical snapshot", "edition": "Classic", "gaps": ["Capture time unknown"]}
    saved = service.add(JOURNAL, "Example", "Advice", NOTE, source=SOURCE, evidence=evidence,
                        next_time={"text": "Try the route", "state": "open"})
    assert service.add(JOURNAL, "Example", "Advice", NOTE, source=SOURCE, evidence=evidence,
                       next_time={"text": "Try the route", "state": "open"}) == saved
    before = service.path(JOURNAL).read_bytes()
    evidence["text"] = "Different snapshot"
    with pytest.raises(ChatError, match="already saved"):
        service.add(JOURNAL, "Example", "Advice", NOTE, source=SOURCE, evidence=evidence)
    assert service.path(JOURNAL).read_bytes() == before
    service.set_next_time(JOURNAL, NOTE, "done")
    entry = JournalService(tmp_path).load(JOURNAL)["entries"][0]
    assert entry["evidence"]["text"] == "Historical snapshot"
    assert entry["next_time"]["state"] == "done"


@pytest.mark.parametrize("damage", [
    {"version": 2, "name": "Example", "entries": []},
    {"version": 1, "name": "Example", "entries": [{"at": "unknown", "text": "Note", "source": {"provider": "other"}}]},
])
def test_unsupported_or_corrupt_file_is_kept(tmp_path, damage):
    service = JournalService(tmp_path)
    path = service.path(JOURNAL)
    path.parent.mkdir()
    path.write_text(json.dumps(damage))
    before = path.read_bytes()
    with pytest.raises(ChatError, match="kept"):
        service.add(JOURNAL, "Example", "New note")
    assert path.read_bytes() == before


def test_limits_and_failed_writes_preserve_prior_notes(tmp_path, monkeypatch):
    from wow_helper import journal
    service = JournalService(tmp_path)
    service.add(JOURNAL, "Example", "Existing")
    before = service.path(JOURNAL).read_bytes()
    with pytest.raises(ChatError, match="64,000"):
        service.add(JOURNAL, "Example", "Advice", evidence={"text": "🎮" * 16000})
    with pytest.raises(ChatError, match="8,000"):
        service.add(JOURNAL, "Example", "x" * 8001)
    def fail(*_):
        raise OSError("Synthetic disk failure")
    monkeypatch.setattr(journal, "write_json", fail)
    with pytest.raises(ChatError, match="draft"):
        service.add(JOURNAL, "Example", "New note")
    assert service.path(JOURNAL).read_bytes() == before


def test_missing_image_does_not_make_saved_note_unreadable(tmp_path):
    service = JournalService(tmp_path)
    evidence = {"image": str(uuid.UUID(int=50)) + ".png", "text": "Historical image description"}
    service.add(JOURNAL, "Example", "Advice", evidence=evidence)
    assert service.load(JOURNAL)["entries"][0]["evidence"] == evidence
    with pytest.raises(ChatError):
        service.add(JOURNAL, "Example", "Bad image", evidence={"image": "../example.png"})


def test_reply_evidence_uses_receipt_or_frozen_quest_never_current_report(tmp_path):
    from types import SimpleNamespace
    from wow_helper.chat import Message, Session, write_json
    from wow_helper.activities import ActivityService
    from wow_helper.journal import advice_selection
    session = Session("codex", str(uuid.UUID(int=30)), "Example", "ExampleProject", "ready", managed=True)
    request_id = str(uuid.UUID(int=31))
    packet = {"edition": "Classic", "prepared_at": 1000, "reports": {"quests": {"snapshot_at": 900, "text": "Original report"}}}
    activity = ActivityService(tmp_path)
    write_json(tmp_path / "prepared" / (request_id + ".json"), packet)
    agents = SimpleNamespace(result=lambda *_: {"id": request_id, "status": "completed"})
    view = SimpleNamespace(selection_key=session.key, selected=session, service=SimpleNamespace(agents=agents),
                           activity=activity, panel_report={"text": "Unrelated new report"})
    message = Message(request_id + ":assistant", "assistant", "Saved answer")
    selected = advice_selection(view, message, message.text)
    assert selected["source"]["request_id"] == request_id
    assert "Original report" in selected["evidence"]["text"]
    assert "Unrelated" not in selected["evidence"]["text"]
    quest_packet = {"edition": "Classic", "reports": {"quest_context": {"data": {
        "quest": {"id": 123}, "snapshot_at": 500}}}}
    write_json(tmp_path / "prepared" / (request_id + ".json"), quest_packet)
    managed_quest = advice_selection(view, message, message.text)
    assert managed_quest["evidence"]["quest_id"] == 123
    assert managed_quest["evidence"]["snapshot_at"] == 500
    view.selected = Session("codex", session.id, "Example", "ExampleProject", "idle")
    view.context = {"quest": {"id": 123, "title": "Synthetic quest"}, "edition": "Classic", "snapshot_at": 500}
    selected = advice_selection(view, Message("external", "assistant", "Quest advice"), "Quest advice")
    view.context["quest"]["title"] = "Changed"
    assert "Synthetic quest" in selected["evidence"]["text"]
    assert "request_id" not in selected["source"]
