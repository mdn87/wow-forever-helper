"""Synthetic saved arrangements; no real sessions, files, or gameplay data."""

from copy import deepcopy
import json
import uuid

import pytest

from wow_helper import activity_layouts
from wow_helper.activity_layouts import SavedLayouts, normalize_record
from wow_helper.chat import ChatError
from wow_helper.window_state import LayoutLock


def record():
    return {"id": str(uuid.UUID(int=0)), "kind": "quests", "topmost": True,
            "bounds": {"x": -1200, "y": 40, "width": 620, "height": 700},
            "chat": {"session": {"provider": "codex", "id": str(uuid.UUID(int=1))},
                     "title": "Synthetic conversation", "activity": {"tab": 1}}}


def test_named_storage_requires_explicit_replace_and_strips_executable_state(tmp_path):
    store = SavedLayouts(tmp_path / "layouts.json")
    raw = record()
    raw["chat"].update(launch={"prompt": "Never run"}, pending={"body": "Never send"},
                       response_waits=["Never poll"], draft="Private draft", messages=["Private history"])
    raw["chat"]["activity"].update(quest_chats=["Never open"], guide_keys={"key": "Never research"},
                                   pending_note={"body": "Never save"}, note="Unsent note")
    store.save("  Leveling  ", [raw])
    saved = SavedLayouts(store.path).get("LEVELING")
    assert saved["name"] == "Leveling"
    assert saved["windows"] == [normalize_record(raw)]
    assert saved["windows"][0]["chat"]["activity"] == {"tab": 1}
    assert not {"launch", "pending", "response_waits", "draft", "messages"} & set(saved["windows"][0]["chat"])
    before = store.path.read_bytes()
    with pytest.raises(ChatError, match="already saved"):
        store.save("leveling", [raw])
    assert store.path.read_bytes() == before
    raw["topmost"] = False
    store.save("Leveling", [raw], replace=True)
    assert len(store.load()["layouts"]) == 1
    assert store.get("Leveling")["windows"][0]["topmost"] is False


@pytest.mark.parametrize("data", [
    {"version": 2, "layouts": []}, {"version": True, "layouts": []},
    {"version": 1, "layouts": [{"name": "Bad", "windows": [dict(record(), kind="unknown")]}]},
    {"version": 1, "layouts": [{"name": "Duplicate", "windows": [record(), record()]}]},
    {"version": 1, "layouts": [{"name": "Same", "windows": [record()]}, {"name": "same", "windows": [record()]}]},
    {"version": 1, "layouts": [None]},
])
def test_damaged_saved_layout_is_kept_on_read_and_save(tmp_path, data):
    path = tmp_path / "layouts.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    original = path.read_bytes()
    store = SavedLayouts(path)
    with pytest.raises(ChatError, match="damaged or unsupported"):
        store.load()
    with pytest.raises(ChatError, match="damaged or unsupported"):
        store.save("New", [record()])
    assert path.read_bytes() == original


def test_failed_or_concurrent_save_preserves_previous_arrangement(tmp_path, monkeypatch):
    store = SavedLayouts(tmp_path / "layouts.json")
    store.save("Review", [record()])
    original = store.path.read_bytes()
    lock = LayoutLock(store.path)
    try:
        with pytest.raises(ChatError, match="Another window"):
            store.save("Review", [dict(record(), topmost=False)], replace=True)
    finally:
        lock.close()
    def fail(*args):
        raise OSError("Synthetic write failure")
    monkeypatch.setattr(activity_layouts, "write_json", fail)
    with pytest.raises(ChatError, match="previous save are kept"):
        store.save("Review", [dict(record(), topmost=False)], replace=True)
    assert store.path.read_bytes() == original


def test_limits_and_invalid_window_references_are_rejected(tmp_path, monkeypatch):
    store = SavedLayouts(tmp_path / "layouts.json")
    for name in ("", " ", "x" * 81, "bad\0name"):
        with pytest.raises(ChatError):
            store.save(name, [record()])
    for change in ({"id": "invalid"}, {"bounds": {"x": True}}, {"topmost": "true"},
                   {"kind": "screen", "chat": {"activity": {"image": "../image.png"}}}):
        with pytest.raises(ChatError):
            normalize_record(dict(record(), **change))
    store.save("One", [record()])
    before = store.path.read_bytes()
    monkeypatch.setattr(activity_layouts, "MAX_LAYOUTS", 1)
    with pytest.raises(ChatError, match="Twenty"):
        store.save("Two", [record()])
    monkeypatch.setattr(activity_layouts, "MAX_BYTES", len(before) + 10)
    changed = deepcopy(record())
    changed["chat"]["profile"] = {"instructions": "🧭" * 100}
    with pytest.raises(ChatError, match="full"):
        store.save("One", [changed], replace=True)
    assert store.path.read_bytes() == before
