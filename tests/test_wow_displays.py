"""Synthetic two-display workflows; no provider requests or game input."""

import json
import time

import pytest

from test_workspace import manager_factory, settle
from wow_helper.chat import ChatError
from wow_helper.wow_displays import FLAVORS


def pair(manager, monkeypatch):
    areas = [(0, 0, 1280, 800), (1280, 0, 2560, 800)]
    monkeypatch.setattr("wow_helper.workspace.display_workareas", lambda _: areas)
    return manager.open_wow_displays(areas[0], areas[1])


def test_activity_cards_keep_independent_drafts_and_restart(manager_factory, monkeypatch):
    manager = manager_factory()
    quest, cards = pair(manager, monkeypatch)
    deck = cards.display
    journal = deck.open_activity("journal")
    settle(journal)
    journal.note.insert("1.0", "Synthetic next step")
    deck.show_cards()
    gear = deck.open_activity("character")
    settle(gear)
    gear.gear_goal.set("Synthetic healing goal")
    gear.refresh_panel()
    settle(gear)
    gear.editor.insert("1.0", "Unsent gear question")
    deck.show_cards()
    assert deck.open_activity("journal") is journal
    assert journal.note.get("1.0", "end-1c") == "Synthetic next step"
    deck.show_cards()
    assert all(not v.service.sent for v in deck.views.values())
    assert manager.save_layout()
    manager.close()
    restored = manager_factory()
    deck = next(w.display for w in restored.windows if w.kind == "activities")
    assert deck.active is None
    journal = deck.open_activity("journal")
    settle(journal)
    assert journal.note.get("1.0", "end-1c") == "Synthetic next step"
    gear = deck.open_activity("character")
    settle(gear)
    assert gear.gear_goal.get() == "Synthetic healing goal"
    assert gear.editor.get("1.0", "end-1c") == "Unsent gear question"
    assert not gear.service.sent
    assert not gear.activity.calls
    assert gear.panel_report


def test_active_workflow_returns_after_restart_and_retention_off_scrubs_drafts(manager_factory, monkeypatch):
    manager = manager_factory()
    _, cards = pair(manager, monkeypatch)
    deck = cards.display
    view = deck.open_activity("character")
    settle(view)
    view.editor.insert("1.0", "Private unsent synthetic text")
    manager.close()
    restored = manager_factory()
    cards = next(w for w in restored.windows if w.kind == "activities")
    assert cards.display.active == "character"
    assert cards.display.views["character"].editor.get("1.0", "end-1c") == "Private unsent synthetic text"
    cards.remember.set(False)
    cards.display.show_cards()
    assert restored.save_layout()
    data = json.loads(restored.layout_path.read_text())
    record = next(w for w in data["windows"] if w["kind"] == "activities")
    assert "draft" not in record["display"]["states"]["character"]


def test_unopened_activity_notebook_drafts_respect_retention_off(manager_factory, monkeypatch):
    manager = manager_factory()
    _, cards = pair(manager, monkeypatch)
    view = cards.display.open_activity('character')
    view.notebook_drafts['build'] = {'profile': 'Synthetic private draft'}
    cards.display.show_cards()
    manager.close()
    restored = manager_factory()
    cards = next(w for w in restored.windows if w.kind == 'activities')
    assert not cards.display.views
    cards.remember.set(False)
    assert restored.save_layout()
    state = cards.display.snapshot(False)['states']['character']['activity']
    assert 'notebooks' not in state


def test_missing_monitor_stays_hidden_even_on_reveal(manager_factory, monkeypatch):
    manager = manager_factory()
    quest, cards = pair(manager, monkeypatch)
    monkeypatch.setattr("wow_helper.workspace.display_workareas", lambda _: [(0, 0, 1280, 800)])
    manager.root.after_cancel(manager._display_after)
    manager._check_display_connections()
    assert cards.root.state() == "withdrawn"
    manager.close()
    monkeypatch.setattr("wow_helper.workspace.display_workareas", lambda _: [(0, 0, 1280, 800)])
    mapped = []
    original = manager.tk.Toplevel.deiconify
    def observe(window):
        mapped.append(window.title())
        return original(window)
    monkeypatch.setattr(manager.tk.Toplevel, "deiconify", observe)
    restored = manager_factory()
    cards = next(w for w in restored.windows if w.kind == "activities")
    assert cards.root.state() == "withdrawn"
    assert not any("Activity cards" in title for title in mapped)
    restored.reveal(cards)
    assert cards.root.state() == "withdrawn"


def test_failed_pair_save_rolls_back_without_losing_work(manager_factory, monkeypatch):
    manager = manager_factory()
    original = manager.windows[0]
    original.view.editor.insert("1.0", "Keep this draft")
    monkeypatch.setattr(manager, "save_layout", lambda: False)
    with pytest.raises(ChatError, match="could not be saved"):
        pair(manager, monkeypatch)
    assert manager.windows == [original]
    assert original.view.editor.get("1.0", "end-1c") == "Keep this draft"


def test_pair_is_reused_and_return_preserves_other_windows(manager_factory, monkeypatch):
    manager = manager_factory()
    original = manager.windows[0]
    quest, cards = pair(manager, monkeypatch)
    assert pair(manager, monkeypatch) == (quest, cards)
    assert len(manager.windows) == 3
    manager.return_to_dias()
    assert quest.root.state() == cards.root.state() == "withdrawn"
    assert original.root.state() != "withdrawn"
    manager.close()
    restored = manager_factory()
    assert all(w.root.state() == "withdrawn" for w in restored.windows if w.display)


def test_quest_display_reads_only_on_request_and_keeps_age(manager_factory, monkeypatch):
    manager = manager_factory()
    quest, cards = pair(manager, monkeypatch)
    view = quest.display
    assert not view.activity.calls
    view.refresh()
    deadline = time.monotonic() + 4
    while view.busy and time.monotonic() < deadline:
        manager.root.update()
    assert not view.busy
    assert view.rows
    assert view.saved_at == 1000
    view.select_row(0)
    assert view.detail.get("1.0", "end-1c").strip()
    assert len(view.activity.calls) == 1
    manager.close()
    restored = manager_factory()
    view = next(w.display for w in restored.windows if w.kind == "questlog")
    assert view.saved_at == 1000
    assert view.rows
    assert not view.activity.calls


def test_invalid_display_state_is_preserved(manager_factory, tmp_path):
    manager = manager_factory()
    path = manager.layout_path
    manager.close()
    data = json.loads(path.read_text())
    data["windows"][0].update(kind="activities", display={"version": 999})
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(ChatError, match="display"):
        manager_factory()
    assert path.read_bytes() == before


def test_pair_validates_capacity_and_distinct_monitors(manager_factory, monkeypatch):
    manager = manager_factory()
    area = manager.areas[0]
    with pytest.raises(ChatError):
        manager.open_wow_displays(area, area)
    assert len(manager.windows) == 1
    for _ in range(6):
        manager.new_window()
    with pytest.raises(ChatError, match="Eight"):
        pair(manager, monkeypatch)
    assert len(manager.windows) == 7


def test_display_windows_stay_opaque_over_dias(manager_factory, monkeypatch):
    manager = manager_factory()
    chat = manager.windows[0]
    manager.interface = {"theme": "classic", "opacity": 65, "solid_when_active": True}
    quest, cards = pair(manager, monkeypatch)
    manager.preview_interface(None)
    chat.view.editor.focus_force()
    manager.root.update()
    assert chat.root.attributes("-alpha") == 1
    assert quest.root.attributes("-alpha") == cards.root.attributes("-alpha") == 1
    chat.root.focus_force()
    manager.root.update()
    assert quest.root.attributes("-alpha") == cards.root.attributes("-alpha") == 1


class StubReports:
    """Synthetic quest reports for the display's exit cases; never reads a real snapshot."""
    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    def reports(self, steps, flavor):
        self.calls.append((steps, flavor))
        if self.error:
            raise self.error
        return {"quests": {"snapshot_at": 2000, "data": self.data}}


def read(manager, view):
    view.refresh()
    deadline = time.monotonic() + 4
    while view.busy and time.monotonic() < deadline:
        manager.root.update()
    assert not view.busy


def age_label(manager, view, expected):
    """The age label refreshes on a 250 ms tick; wait for it instead of reading it early."""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        manager.root.update()
        if expected(view.age.cget("text")):
            break
        time.sleep(0.02)
    return view.age.cget("text")


def synthetic(plan, available=None, warnings=()):
    return {"plan": plan, "available": available, "quest_count": len(plan), "warnings": list(warnings)}


def test_failed_read_keeps_prior_quests_and_age(manager_factory, monkeypatch):
    manager = manager_factory()
    view = pair(manager, monkeypatch)[0].display
    read(manager, view)
    rows, saved_at = list(view.rows), view.saved_at
    view.activity = StubReports(error=OSError("synthetic failure"))
    read(manager, view)
    assert view.rows == rows and view.saved_at == saved_at
    assert "Previous data is kept" in view.notice.cget("text")
    assert str(view.read_button.cget("state")) == "normal"


def test_edition_change_clears_and_discards_late_reads(manager_factory, monkeypatch):
    manager = manager_factory()
    view = pair(manager, monkeypatch)[0].display
    read(manager, view)
    assert view.rows
    view.edition.set(next(name for name in FLAVORS if name != view.edition.get()))
    view.change_edition()
    assert view.rows == [] and view.saved_at is None
    assert age_label(manager, view, lambda text: "unknown" in text).startswith("Snapshot time unknown")
    # A read started for one edition must not fill the list after switching to another.
    old = view.flavor
    view.refresh()
    view.flavor = "_other_"
    deadline = time.monotonic() + 4
    while view.busy and time.monotonic() < deadline:
        manager.root.update()
    assert view.rows == [] and view.activity.calls[-1][1] == old


def test_pickups_are_labelled_or_reported_unavailable(manager_factory, monkeypatch):
    manager = manager_factory()
    view = pair(manager, monkeypatch)[0].display
    quest = {"action": "finish", "title": "Testchar Errand", "zone": "ExampleRealm Fields", "remaining": ["0/3 Synthetic"]}
    view.activity = StubReports(synthetic([quest], available=[{"title": "Synthetic Offer"}]))
    read(manager, view)
    assert [r["title"] for r in view.rows] == ["Finish · Testchar Errand", "Pickup · Synthetic Offer"]
    assert "current availability is unverified" in view.rows[1]["detail"]
    assert "unavailable" not in view.summary
    view.activity = StubReports(synthetic([quest], available=None))
    read(manager, view)
    assert [r["title"] for r in view.rows] == ["Finish · Testchar Errand"]
    assert "Nearby pickups are unavailable for this snapshot." in view.summary


def test_quests_without_ids_or_zones_still_render(manager_factory, monkeypatch):
    manager = manager_factory()
    view = pair(manager, monkeypatch)[0].display
    view.activity = StubReports(synthetic([{"action": "turn in", "title": "Unnumbered Synthetic Task"}]))
    read(manager, view)
    assert view.rows[0]["title"] == "Turn In · Unnumbered Synthetic Task"
    assert "Zone unknown" in view.detail.get("1.0", "end-1c")


def test_age_label_marks_stale_snapshots(manager_factory, monkeypatch):
    manager = manager_factory()
    view = pair(manager, monkeypatch)[0].display

    def label(saved_at, suffix):
        view.saved_at = saved_at
        return age_label(manager, view, lambda text: text.endswith(suffix) or text.startswith(suffix))

    assert label(time.time() - 5 * 60, "not live") == "Saved 5 minutes ago · saved snapshot, not live"
    assert label(time.time() - 20 * 60, "stale") == "Saved 20 minutes ago · stale"
    assert label(None, "Snapshot time unknown").startswith("Snapshot time unknown")
