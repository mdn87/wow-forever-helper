"""Synthetic window preparation and storage; never read real snapshots or recordings."""

import json
import os
from pathlib import Path
import uuid

import pytest

from wow_helper import activities, character, quests
from wow_helper.activities import ActivityService, profile_settings
from wow_helper.chat import ChatError, MAX_MESSAGE
from wow_helper.savedvars import parse
from wow_helper.window_state import LayoutLock

FIXTURE = Path(__file__).parent / "fixtures" / "savedvariables_quests.lua"


def test_reports_use_one_stable_snapshot_of_the_selected_edition(tmp_path, monkeypatch):
    calls = []
    parsed = parse(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr(activities.wtf, "roots", lambda _: [tmp_path])
    monkeypatch.setattr(activities.wtf, "newest", lambda roots, only: calls.append(only) or (only, FIXTURE))
    monkeypatch.setattr(activities, "read_stable", lambda path, wait: calls.append(path) or (parsed, 1000))
    monkeypatch.setattr(activities.time, "time", lambda: 1030)
    result = ActivityService(tmp_path).reports(["quests", "character"], "_classic_beta_")
    assert calls == ["_classic_beta_", FIXTURE]
    assert result["quests"]["data"]["quest_count"] == 6
    assert result["character"]["data"]["gold"] == "12g 34s 56c"
    assert result["quests"]["data"]["age_seconds"] == result["character"]["data"]["age_seconds"] == 30


def test_missing_edition_is_refused_without_cross_edition_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(activities.wtf, "roots", lambda _: [tmp_path])
    monkeypatch.setattr(activities.wtf, "newest", lambda roots, only: None)
    with pytest.raises(ChatError, match="No snapshot for this edition"):
        ActivityService(tmp_path).reports(["quests"], "_classic_beta_")


def test_preparation_keeps_whole_skills_and_context_without_sending_or_executing(tmp_path, monkeypatch):
    context = tmp_path / "notes.txt"
    context.write_text("Synthetic context. " * 2000, encoding="utf-8")
    skill = tmp_path / "SKILL.md"
    skill.write_text("Synthetic custom instructions", encoding="utf-8")
    profile = profile_settings("chat", {"steps": ["arbitrary-command"], "skills": ["wow-journal"],
                                       "context_files": [str(context)], "skill_files": [str(skill)]})
    service = ActivityService(tmp_path / "private")
    assert profile["steps"] == []
    packet = service.prepare("chat", profile)
    assert len(packet["skills"]) == 2
    assert packet["context_files"][0]["text"] == context.read_text()
    assert not service.storage.exists()
    request = str(uuid.UUID(int=0))
    message = service.request_message(packet, request)
    assert len(message) < MAX_MESSAGE
    assert json.loads((service.storage / "prepared" / (request + ".json")).read_text()) == packet


def test_missing_or_oversized_selected_file_stops_preparation(tmp_path):
    profile = profile_settings("chat", {"context_files": [str(tmp_path / "missing.md")]})
    with pytest.raises(ChatError, match="could not be read"):
        ActivityService(tmp_path).prepare("chat", profile)
    path = tmp_path / "large.md"
    path.write_text("x" * 64_001)
    profile["context_files"] = [str(path)]
    with pytest.raises(ChatError, match="64 KB"):
        ActivityService(tmp_path).prepare("chat", profile)


def test_journal_survives_window_lifetime_and_refuses_overwriting_damaged_file(tmp_path):
    service = ActivityService(tmp_path)
    key = str(uuid.UUID(int=0))
    service.add_note(key, "Synthetic goals", "Find the example quest.")
    restored = ActivityService(tmp_path)
    restored.add_note(key, "Synthetic goals", "Finish the example quest.")
    assert [e["text"] for e in restored.journal(key)["entries"]] == ["Find the example quest.", "Finish the example quest."]
    path = service.journal_path(key)
    path.write_text("damaged", encoding="utf-8")
    with pytest.raises(ChatError, match="existing file has been kept"):
        restored.add_note(key, "Example", "Do not overwrite")
    assert path.read_text() == "damaged"


def test_concurrent_journal_save_preserves_existing_notes(tmp_path):
    service = ActivityService(tmp_path)
    key = str(uuid.UUID(int=0))
    service.add_note(key, "Example", "Existing note")
    lock = LayoutLock(service.journal_path(key))
    try:
        with pytest.raises(ChatError, match="Another window is saving"):
            service.add_note(key, "Example", "New note")
    finally:
        lock.close()
    assert len(service.journal(key)["entries"]) == 1


def test_unicode_journal_cannot_save_beyond_its_readable_byte_limit(tmp_path):
    service = ActivityService(tmp_path)
    key = str(uuid.UUID(int=0))
    # Synthetic notes near the byte limit but below the character limit.
    data = {"name": "Example", "entries": [
        {"at": "2026-01-01T00:00:00+00:00", "text": "\U0001f3ae" * 8000} for _ in range(62)]}
    path = service.journal_path(key)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    assert service.journal(key) == data
    with pytest.raises(ChatError, match="journal is full"):
        service.add_note(key, "Example", "\U0001f3ae" * 4000)
    assert path.read_bytes() == before
    assert service.journal(key) == data


def test_import_strips_metadata_and_preparation_uses_only_managed_images(tmp_path):
    from PIL import Image, PngImagePlugin
    from wow_helper.screen_capture import import_image, saved_image
    source = tmp_path / "synthetic.png"
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("comment", "Synthetic metadata")
    Image.new("RGB", (320, 180), "#334455").save(source, pnginfo=metadata)
    service = ActivityService(tmp_path / "private")
    name = import_image(service.storage, source)
    path = saved_image(service.storage, name)
    with Image.open(path) as image:
        assert image.size == (320, 180) and image.info == {}
    packet = service.prepare("screen", profile_settings("screen"), image=name)
    assert packet["image"] == str(path.resolve())
    with pytest.raises(ChatError):
        service.prepare("screen", profile_settings("screen"), image="../synthetic.png")


def test_clipboard_image_is_copied_without_metadata_and_empty_clipboard_is_reported(tmp_path, monkeypatch):
    from PIL import Image, ImageGrab
    from wow_helper.screen_capture import paste_image, saved_image
    source = Image.new("RGB", (80, 60), "gold")
    source.info["comment"] = "Synthetic metadata"
    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: source)
    path = saved_image(tmp_path, paste_image(tmp_path))
    with Image.open(path) as result:
        assert result.size == (80, 60) and result.info == {}
    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: None)
    with pytest.raises(ChatError, match="No single image"):
        paste_image(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows native capture process")
def test_capture_failure_never_falls_back_to_a_desktop_capture(tmp_path, monkeypatch):
    from wow_helper import screen_capture
    calls = []
    monkeypatch.setattr(screen_capture.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    def fail(args, **kwargs):
        calls.append((args, kwargs))
        raise screen_capture.subprocess.TimeoutExpired(args, 10)
    monkeypatch.setattr(screen_capture.subprocess, "run", fail)
    with pytest.raises(ChatError, match="Capture did not finish"):
        screen_capture.capture_game(tmp_path, "_classic_beta_")
    assert len(calls) == 1 and calls[0][0][-1] == "_classic_beta_"
    assert calls[0][1]["timeout"] == 10
