"""Synthetic session bookmarks; generated images and fake sessions only, no game data or provider history."""

import json
import uuid
from datetime import datetime

import pytest

from wow_helper.chat import ChatError
from wow_helper.journal import JournalService
from wow_helper.journal_ui import note_summary

JOURNAL = str(uuid.UUID(int=0))
NOTE = str(uuid.UUID(int=1))
SOURCE = {"provider": "codex", "session_id": str(uuid.UUID(int=2))}
BOOKMARK = {"event_at": "2026-01-02T03:04:05+00:00", "image_captured_at": None, "manual_correction_seconds": 0}
CONTEXT = {"edition": "Classic Forever beta", "snapshot_at": 500,
           "quest": {"id": 123, "title": "Synthetic quest"}, "character": "Testchar", "realm": "ExampleRealm"}


# Journal service: bookmark records keep the existing validation and limits.

def test_bookmark_record_round_trips_across_restart(tmp_path):
    bookmark = dict(BOOKMARK, image_captured_at="2026-01-02T02:00:00+00:00", manual_correction_seconds=-120)
    JournalService(tmp_path).add(JOURNAL, "Example", "Pulled too early", NOTE, source=SOURCE,
                                 evidence={"image": str(uuid.UUID(int=50)) + ".png", "text": ""}, bookmark=bookmark)
    entry = JournalService(tmp_path).load(JOURNAL)["entries"][0]
    assert entry["bookmark"] == bookmark and entry["source"] == SOURCE
    assert JournalService(tmp_path).add(JOURNAL, "Example", "Pulled too early", NOTE, source=SOURCE,
                                        evidence={"image": str(uuid.UUID(int=50)) + ".png", "text": ""},
                                        bookmark=bookmark)["entries"] == [entry]


@pytest.mark.parametrize("bookmark", [
    {"event_at": "2026-01-02T03:04:05+00:00", "image_captured_at": None},
    dict(BOOKMARK, extra=1),
    dict(BOOKMARK, event_at=None),
    dict(BOOKMARK, event_at="2026-01-02T03:04:05"),
    dict(BOOKMARK, image_captured_at="2026-01-02T03:04:05"),
    dict(BOOKMARK, image_captured_at="not a time"),
    dict(BOOKMARK, event_at="2026-01-02T03:04:05+00:00" + " " * 100),
    dict(BOOKMARK, manual_correction_seconds=86_401),
    dict(BOOKMARK, manual_correction_seconds=True),
    dict(BOOKMARK, manual_correction_seconds=1.5),
    "2026-01-02T03:04:05+00:00",
], ids=["missing-key", "extra-key", "no-event", "naive-event", "naive-image", "bad-image", "long",
        "correction-range", "correction-bool", "correction-float", "not-dict"])
def test_invalid_bookmark_time_is_refused_and_writes_nothing(tmp_path, bookmark):
    service = JournalService(tmp_path)
    service.add(JOURNAL, "Example", "Existing")
    before = service.path(JOURNAL).read_bytes()
    with pytest.raises(ChatError, match="kept"):
        service.add(JOURNAL, "Example", "Bookmark", bookmark=bookmark)
    assert service.path(JOURNAL).read_bytes() == before


def test_bookmark_records_keep_size_and_version_limits(tmp_path):
    service = JournalService(tmp_path)
    service.add(JOURNAL, "Example", "Existing")
    before = service.path(JOURNAL).read_bytes()
    with pytest.raises(ChatError, match="8,000"):
        service.add(JOURNAL, "Example", "x" * 8001, bookmark=BOOKMARK)
    with pytest.raises(ChatError, match="64,000"):
        service.add(JOURNAL, "Example", "Context", evidence={"text": "🎮" * 16_000}, bookmark=BOOKMARK)
    assert service.path(JOURNAL).read_bytes() == before

    full = {"version": 1, "name": "Example", "entries": [
        {"id": str(uuid.UUID(int=100 + i)), "at": "unknown", "text": "x" * 7900, "bookmark": BOOKMARK}
        for i in range(63)]}
    path = service.path(JOURNAL)
    path.write_text(json.dumps(full), encoding="utf-8")
    before = path.read_bytes()
    assert len(service.load(JOURNAL)["entries"]) == 63
    with pytest.raises(ChatError, match="full"):
        service.add(JOURNAL, "Example", "y" * 3000, bookmark=BOOKMARK)
    assert path.read_bytes() == before

    for damage in ({"version": 2, "name": "Example", "entries": full["entries"][:1]},
                   {"version": 1, "name": "Example", "entries": [dict(full["entries"][0],
                                                                       bookmark=dict(BOOKMARK, event_at="soon"))]}):
        path.write_text(json.dumps(damage), encoding="utf-8")
        before = path.read_bytes()
        with pytest.raises(ChatError, match="kept"):
            service.add(JOURNAL, "Example", "New", bookmark=BOOKMARK)
        assert path.read_bytes() == before


def test_summary_keeps_event_image_and_correction_times_distinct():
    entry = {"id": NOTE, "at": "2026-01-02T03:04:06+00:00", "text": "Boss enraged",
             "evidence": {"text": "", "gaps": ["No context was selected; the full conversation was not stored."]},
             "bookmark": dict(BOOKMARK, image_captured_at="2026-01-02T02:00:00+00:00", manual_correction_seconds=-180)}
    summary = note_summary(entry)
    assert summary.startswith("SESSION BOOKMARK\nBoss enraged")
    assert "2026-01-02T03:04:05+00:00" in summary
    assert "Image capture time: 2026-01-02T02:00:00+00:00" in summary
    assert "Manual time correction: -3 minutes" in summary
    assert "Conversation: Unknown" in summary
    entry["bookmark"] = dict(BOOKMARK, manual_correction_seconds=0)
    summary = note_summary(entry)
    assert "Image capture time: Unknown" in summary and "Manual time correction" not in summary


# Companion UI: Menu -> Bookmark this moment, Resume session, and follow-up.

from test_workspace import SESSIONS, Service, choose, manager_factory, new_chat, settle  # noqa: E402,F401


class Offline(Service):
    sessions = []


def png(tmp_path, name="synthetic-moment.png"):
    from PIL import Image
    source = tmp_path / name
    Image.new("RGB", (320, 160), "purple").save(source)
    return source


def all_sent(manager):
    return [item for window in manager.windows if window.view for item in window.view.service.sent]


def forbid_side_effects(view, monkeypatch):
    """Bookmarking must not capture, record, read reports, or queue background or agent work."""
    calls = []

    def refuse(name):
        def call(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(name + " must not run while bookmarking")
        return call

    from wow_helper import recording_controller, screen_capture
    monkeypatch.setattr(screen_capture, "capture_game", refuse("capture"))
    monkeypatch.setattr(screen_capture, "paste_image", refuse("paste"))
    monkeypatch.setattr(recording_controller.RecordingController, "__init__", refuse("recording"))
    monkeypatch.setattr(view, "_submit", refuse("submit"))
    monkeypatch.setattr(view, "send_message", refuse("send"))
    monkeypatch.setattr(view, "send_prepared", refuse("send_prepared"))
    return calls


def test_note_only_bookmark_works_without_a_provider(manager_factory, monkeypatch):
    manager = manager_factory(service=Offline)
    view = manager.windows[0].view
    assert view.selection_key is None
    calls = forbid_side_effects(view, monkeypatch)
    view.bookmark_moment()
    dialog = view._bookmark_dialog
    assert "No recording, screenshot, or agent request" in dialog.notice.get()
    assert not dialog.include_source.get() and not dialog.include_context.get() and not dialog.include_image.get()
    dialog.save()
    assert view._bookmark_dialog is dialog and "Write a short note" in dialog.notice.get()
    dialog.body.insert("1.0", "Synthetic wipe at the second pull")
    dialog.save()
    assert view._bookmark_dialog is None and "no request was sent" in view.activity_notice.get()
    entry = view.activity.journal(view.journal_id)["entries"][0]
    assert entry["text"] == "Synthetic wipe at the second pull"
    assert "source" not in entry and "image" not in entry["evidence"]
    assert entry["evidence"]["text"] == "" and "not stored" in entry["evidence"]["gaps"][0]
    assert entry["bookmark"]["image_captured_at"] is None and entry["bookmark"]["manual_correction_seconds"] == 0
    assert datetime.fromisoformat(entry["bookmark"]["event_at"]).utcoffset() is not None
    assert not calls and not all_sent(manager) and not view.activity.calls
    assert not (view.activity.storage / "prepared").exists()


def test_bookmark_freezes_selected_context_previews_image_and_keeps_times_separate(manager_factory, tmp_path, monkeypatch):
    from wow_helper.screen_capture import import_image
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.context = json.loads(json.dumps(CONTEXT))
    view.image_name = import_image(view.activity.storage, png(tmp_path))
    calls = forbid_side_effects(view, monkeypatch)
    view.bookmark_moment()
    dialog = view._bookmark_dialog
    # The reviewed image is shown before saving; context and image remain opt-in.
    assert dialog.image_photo is not None
    assert dialog.include_source.get() and not dialog.include_context.get() and not dialog.include_image.get()
    view.context["quest"]["title"] = "Changed after opening"
    dialog.body.insert("1.0", "Tank died during the synthetic patrol")

    dialog.image_time.insert(0, "2026-01-02T03:04:05")
    dialog.include_image.set(True)
    dialog.save()
    assert "time zone" in dialog.notice.get()
    dialog.image_time.delete(0, "end"); dialog.image_time.insert(0, "2026-01-02T03:04:05-05:00")
    dialog.include_image.set(False)
    dialog.save()
    assert "Select the reviewed image" in dialog.notice.get()
    dialog.include_image.set(True)
    for bad in ("1441", "-1441", "2.5", "soon"):
        dialog.correction.delete(0, "end"); dialog.correction.insert(0, bad)
        dialog.save()
        assert "whole-minute correction" in dialog.notice.get()
    assert not view.activity.journal(view.journal_id)["entries"]

    dialog.correction.delete(0, "end"); dialog.correction.insert(0, "-3")
    dialog.include_context.set(True)
    dialog.save()
    entry = view.activity.journal(view.journal_id)["entries"][0]
    assert entry["source"] == {"provider": SESSIONS[0].provider, "session_id": SESSIONS[0].id}
    assert "Synthetic quest" in entry["evidence"]["text"] and "Changed" not in entry["evidence"]["text"]
    assert entry["evidence"]["edition"] == "Classic Forever beta" and entry["evidence"]["snapshot_at"] == 500
    assert entry["evidence"]["image"] == view.image_name
    assert str(tmp_path) not in json.dumps(entry)
    bookmark = entry["bookmark"]
    assert bookmark["image_captured_at"] == "2026-01-02T08:04:05+00:00"
    assert bookmark["manual_correction_seconds"] == -180
    assert bookmark["event_at"] != bookmark["image_captured_at"]
    assert "Manual time correction: -3 minutes" in note_summary(entry)
    assert not calls and not all_sent(manager) and not view.activity.calls


def test_unavailable_image_preview_falls_back_to_note(manager_factory, monkeypatch):
    manager = manager_factory()
    view = manager.windows[0].view
    view.image_name = str(uuid.UUID(int=60)) + ".png"
    forbid_side_effects(view, monkeypatch)
    view.bookmark_moment()
    dialog = view._bookmark_dialog
    assert dialog.image_photo is None and not dialog.include_image.get()
    assert "preview is unavailable" in dialog.notice.get()
    dialog.include_image.set(True)
    dialog.body.insert("1.0", "Image went missing")
    dialog.save()
    assert "unavailable" in dialog.notice.get() and not view.activity.journal(view.journal_id)["entries"]
    dialog.include_image.set(False)
    dialog.save()
    assert view.activity.journal(view.journal_id)["entries"][0]["text"] == "Image went missing"


def test_missing_image_and_conversation_leave_bookmark_readable(manager_factory, tmp_path):
    from wow_helper.screen_capture import import_image, saved_image
    manager = manager_factory()
    journal = manager.new_window(kind="journal")
    view = journal.view
    settle(view)
    image = import_image(view.activity.storage, png(tmp_path))
    missing_source = {"provider": "codex", "session_id": str(uuid.UUID(int=900))}
    view.activity.add_note(view.journal_id, "Example", "Bookmark with lost sources", source=missing_source,
                           evidence={"text": "", "image": image, "gaps": ["Synthetic gap"]}, bookmark=BOOKMARK)
    view.activity.add_note(view.journal_id, "Example", "Bookmark without a chat", bookmark=BOOKMARK)
    saved_image(view.activity.storage, image).unlink()
    view.resume_session()
    resume = view._resume_dialog
    rows = resume.entries.get_children()
    assert [resume.entries.item(row, "values")[0] for row in rows] == ["Event · " + BOOKMARK["event_at"]] * 2
    resume.entries.selection_set(rows[1]); resume.selected()
    body = resume.preview.get("1.0", "end-1c")
    assert body.startswith("SESSION BOOKMARK\nBookmark with lost sources")
    assert "The saved image is unavailable. The note remains readable." in body
    assert "may no longer be available" in body
    resumed = resume.continue_conversation()
    settle(resumed)
    assert resumed.selected is None and not all_sent(manager)
    resume.entries.selection_set(rows[0]); resume.selected()
    body = resume.preview.get("1.0", "end-1c")
    assert "Bookmark without a chat" in body and "Original conversation unknown" in body
    assert resume.continue_conversation() is None and "remains readable" in resume.notice.get()
    assert not all_sent(manager)


def test_restart_preserves_bookmark_links_and_followup_is_text_only_to_chosen_chat(manager_factory, tmp_path):
    from wow_helper.screen_capture import import_image
    manager = manager_factory()
    view = manager.windows[0].view
    view._select_session(SESSIONS[0]); settle(view)
    view.image_name = import_image(view.activity.storage, png(tmp_path))
    view.bookmark_moment()
    dialog = view._bookmark_dialog
    dialog.body.insert("1.0", "Remember this synthetic pull")
    dialog.include_image.set(True)
    dialog.save()
    journal_id = view.journal_id
    saved = view.activity.journal(journal_id)
    manager.save_layout()
    path = manager.layout_path
    manager.close()

    restored = manager_factory(path)
    target = restored.windows[0].view
    settle(target)
    assert target.journal_id == journal_id and target.activity.journal(journal_id) == saved
    entry = saved["entries"][0]
    other = new_chat(restored, restored.windows[0])
    choose(other, 1)
    assert other.view.selection_key == SESSIONS[1].key
    target._select_session(SESSIONS[0]); settle(target)
    target.editor.insert("1.0", "Keep this draft")
    target.resume_session()
    resume = target._resume_dialog
    assert "Saved image reference retained" in resume.preview.get("1.0", "end-1c")
    assert not all_sent(restored)
    resume.prepare_followup()
    followup = resume.followup
    assert followup is not None and followup.target is target
    assert followup.task.get() == "Review this bookmarked moment with me."
    assert "image" not in followup.packet
    text = followup.packet["context_files"][0]["text"]
    assert "SESSION BOOKMARK" in text and "No image is attached" in text
    assert entry["evidence"]["image"] not in followup.preview.get("1.0", "end-1c")
    assert not all_sent(restored)
    followup.send(); followup.send()
    settle(target)
    sent = all_sent(restored)
    assert len(sent) == 1 and sent[0][0] == SESSIONS[0].key
    bundle = json.loads((target.activity.storage / "prepared" / (followup.request_id + ".json")).read_text())
    assert "image" not in bundle and entry["evidence"]["image"] not in json.dumps(bundle)
    assert target.editor.get("1.0", "end-1c") == "Keep this draft"
