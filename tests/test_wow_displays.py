"""Synthetic two-display workflows; no provider requests or game input."""

import json
import time

import pytest

from test_workspace import manager_factory, settle
from wow_helper.chat import ChatError


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
