"""Synthetic isolated-desktop regression tests for UX Batch 3 (U10-U13) and Codex UX-02."""

import threading
import uuid

from test_gear_ui import panel as gear_panel
from test_voice_input import FakeDictation, FakeKey
from test_workspace import SESSIONS, manager_factory, settle  # noqa: F401
from wow_helper.chat import Session
from wow_helper.search import SETTINGS_ACTIONS, open_row, search_index
from wow_helper.voice_ui import HandsFreeDialog, VoiceDialog


def test_u10_search_button_settings_actions_and_library_copy(manager_factory, monkeypatch):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    # Compact Search toolbar button opens SearchDialog.
    assert window.search_button.winfo_manager()
    window.search_button.invoke()
    manager.root.update()
    dialog = manager._search_dialog
    assert dialog is not None

    rows, _notices = search_index(manager)
    action_targets = {r["target"] for r in rows if r["kind"] == "command"}
    for key, _label in SETTINGS_ACTIONS:
        assert key in action_targets
    library_rows = [r for r in rows if r["kind"] == "library"]
    assert library_rows

    # Activating a library row copies the slash command without sending chat.
    copied = []
    monkeypatch.setattr(dialog.root, "clipboard_clear", lambda: None)
    monkeypatch.setattr(dialog.root, "clipboard_append", copied.append)
    dialog.query.set("ResampleSharpness")
    manager.root.update()
    assert dialog.matches and dialog.matches[0]["kind"] == "library"
    dialog.activate()
    manager.root.update()
    assert copied == ["/console ResampleSharpness -1"]
    assert view.service.sent == []

    # Opening several newly registered settings actions works cleanly.
    view.service.agents = object()
    for action in ("appearance", "setup", "voice_input", "handsfree", "model_settings", "live_gear", "combat", "fight", "bookmark"):
        open_row(manager, window, {"kind": "command", "target": action, "title": action})
        manager.root.update()
    assert view._appearance_dialog is not None
    assert view._setup_dialog is not None
    assert manager._voice_dialog is not None
    assert manager._handsfree_dialog is not None
    assert view._model_dialog is not None
    assert view._gear_dialog is not None
    assert "combat" in view._notebooks
    assert "fight" in view._notebooks
    assert view._bookmark_dialog is not None


def test_u11_conversation_picker_identity_and_codex_ux02(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)

    id_a = str(uuid.UUID(int=101))
    id_b = str(uuid.UUID(int=102))
    sess_a = Session("codex", id_a, "Raid notes", "synthetic-a", "running", None, True)
    sess_b = Session("codex", id_b, "Raid notes", "synthetic-b", "running", None, True)
    sess_closed = Session("codex", str(uuid.UUID(int=103)), "Old thread", "synthetic-c", "idle", None, True)

    discovered = [sess_a, sess_b, sess_closed]
    gate = None

    def fake_discover():
        if gate is not None:
            gate.wait(2.0)
        return list(discovered), []

    view.service.discover = fake_discover
    view.sessions = list(discovered)
    view._session_labels()
    view.selected = None
    settle(view)

    # Dynamic ModelSettingsDialog title when unconnected vs connected.
    view.show_model_settings()
    manager.root.update()
    assert view._model_dialog.chrome.caption.get() == "Find active sessions"
    view._model_dialog.close()

    # Open unified ConversationPicker and verify Active only filter + Refresh.
    view.choose_chat()
    picker = view._picker
    assert picker is not None
    manager.root.update()
    picker.active_only.set(True)
    picker._filter_changed()
    assert picker.keys == [sess_a.key, sess_b.key]

    # Select sess_b (row 1), then discover returns reordered [sess_b, sess_a] with duplicate titles.
    picker.rows.selection_clear(0, "end")
    picker.rows.selection_set(1)
    picker._selection_changed()
    assert picker.selected_key == sess_b.key

    discovered[:] = [sess_b, sess_a]
    picker.scan()
    settle(view)
    assert picker.keys == [sess_b.key, sess_a.key]
    assert picker.selected_key == sess_b.key
    assert picker.rows.curselection() == (0,)

    # Disappeared session between selection and confirmation refuses substitution.
    discovered[:] = [sess_a]
    picker.choose()
    settle(view)
    assert view._picker is picker and not picker.closed
    assert view.selected is None
    assert picker.selected_key is None
    assert "disabled" in picker.attach.state()
    assert "closed or became unavailable" in picker.notice.get().lower()

    # Stale out-of-order discovery result & closing mid-discovery never corrupt state.
    gate = threading.Event()
    discovered[:] = [sess_a, sess_b]
    assert picker.scan() is True
    picker.close()
    gate.set()
    settle(view)
    assert view._picker is None
    assert view.selected is None

    # Re-open picker, pick sess_b, confirm live verification attaches sess_b cleanly.
    gate = None
    view.choose_chat()
    picker = view._picker
    picker.scan()
    settle(view)
    idx = picker.keys.index(sess_b.key)
    picker.rows.selection_clear(0, "end")
    picker.rows.selection_set(idx)
    picker._selection_changed()
    picker.choose()
    settle(view)
    assert view._picker is None
    assert view.selected is not None and view.selected.key == sess_b.key

    # External Codex session shows inline override checkbutton on Next message tab + Change model title.
    ext_codex = Session("codex", str(uuid.UUID(int=104)), "External thread", "synthetic-d", "active", None, False)
    view.sessions = [ext_codex]
    view._select_session(ext_codex)
    settle(view)
    view.show_model_settings()
    manager.root.update()
    assert view._model_dialog.chrome.caption.get() == "Change model"
    main_tab = view._model_dialog.tabs.nametowidget(view._model_dialog.tabs.tabs()[0])
    labels = [w.cget("text") for w in main_tab.winfo_children() if w.winfo_class() == "TCheckbutton"]
    assert any("Override this Codex chat" in text for text in labels)
    view._model_dialog.close()


def test_u12_mode_badges_compact_voice_dialog_and_handsfree_commands_only(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    assert not window.mode_bar.winfo_manager()

    # Hands-free pill appears on connect and opens HandsFreeDialog when clicked.
    manager.handsfree.connect(window)
    manager.root.update()
    assert window.mode_bar.winfo_manager()
    badge_texts = [str(b.cget("text")) for b in window._mode_badges]
    assert any("Hands-free" in t for t in badge_texts)
    window._mode_badges[0].invoke()
    manager.root.update()
    hf = manager._handsfree_dialog
    assert hf is not None
    assert "MENUS & WINDOWS" in hf.help.get("1.0", "end-1c")

    # Commands-only refuses bare chat text and accepts explicit "tell the agent ...".
    hf.commands_only.set(True)
    manager.handsfree.set_commands_only(True)
    assert manager.handsfree.settings().get("commands_only") is True

    manager.handsfree.handle({"id": str(uuid.UUID(int=201)), "text": "what spec should I play?"})
    settle(view)
    assert view.service.sent == []
    assert "ask the agent" in manager.handsfree.history[-1][2].lower()

    manager.handsfree.handle({"id": str(uuid.UUID(int=202)), "text": "tell the agent what spec should I play"})
    settle(view)
    assert len(view.service.sent) == 1
    assert "what spec should i play" in view.service.sent[0][1].lower()

    manager.handsfree.set_commands_only(False)
    assert "commands_only" not in manager.handsfree.settings()
    hf.close()

    # Compact VoiceDialog fits at 360x230, hides transcript by default, and shows Mic badge.
    voice = manager._voice_dialog = VoiceDialog(
        manager, window, dictation_factory=FakeDictation, key_factory=FakeKey
    )
    manager.root.update()
    assert not voice._transcript_box.winfo_manager()
    voice.toggle_transcript()
    assert voice._transcript_box.winfo_manager()
    voice.toggle_transcript()
    assert not voice._transcript_box.winfo_manager()
    voice.enable()
    manager.root.update()
    assert any("Mic (Keypad -)" in str(b.cget("text")) for b in window._mode_badges)

    # Live gear badge appears when shortcut enabled.
    _, gear = gear_panel(manager)
    gear.review_region()
    gear.enable()
    manager.root.update()
    assert any("Live gear" in str(b.cget("text")) for b in window._mode_badges)

    # Disabling all three hides mode_bar cleanly.
    gear.close()
    voice.close()
    manager.handsfree.disconnect()
    manager.root.update()
    assert not window.mode_bar.winfo_manager()


def test_u13_journal_picker_rename_and_fight_crosslinks(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    window.open_kind("journal") if window.kind == "chooser" else None
    jwin = manager.new_window(window)
    jwin.open_kind("journal")
    jview = jwin.view
    settle(jview)

    # Create two named journals and one unreadable corrupt journal file.
    id_one = str(uuid.UUID(int=301))
    id_two = str(uuid.UUID(int=302))
    jview.activity.add_note(id_one, "Raid prep", "Bring flasks and food.")
    jview.activity.add_note(id_two, "Alt leveling", "Check dungeon quests.")
    corrupt = jview.activity.storage / "journals" / (str(uuid.UUID(int=303)) + ".json")
    corrupt.write_text("{corrupt json", encoding="utf-8")

    # OpenJournalDialog lists titles (never raw UUIDs) and skips corrupt file cleanly.
    jview.open_journal()
    picker = jview._open_journal_dialog
    assert picker is not None
    manager.root.update()
    displayed = [picker.tree.item(iid, "text") for iid in picker.tree.get_children()]
    assert set(displayed) == {"Raid prep", "Alt leveling"}
    assert all(id_one not in text and id_two not in text for text in displayed)
    assert "skipped 1 unreadable" in picker.notice.get().lower()
    assert corrupt.exists()

    # Selecting "Raid prep" switches the active journal cleanly.
    picker.tree.selection_set(id_one)
    picker.open_selected()
    manager.root.update()
    assert jview._open_journal_dialog is None
    assert jview.journal_id == id_one
    assert jview.journal_name.get() == "Raid prep"

    # Explicit Rename persists to disk immediately without adding any note.
    jview.journal_name.set("Heroic raid prep")
    jview.rename_button.invoke()
    manager.root.update()
    reloaded = jview.activity.journal(id_one)
    assert reloaded["name"] == "Heroic raid prep"
    assert len(reloaded["entries"]) == 1

    # Fight analysis cross-links preserve drafts across both dialogs.
    jview.show_fight_question()
    fight = jview._notebooks["fight"]
    fight.editors["question"].insert("1.0", "Why did our tank drop on pull 2?")
    fight.changed()
    fight.switch_coach_button.invoke()
    manager.root.update()
    assert "combat" in jview._notebooks
    assert jview.notebook_drafts["fight"]["question"] == "Why did our tank drop on pull 2?"

    coach = jview._notebooks["combat"]
    coach.fields["encounter"].set("Example Boss")
    coach.switch_fight_button.invoke()
    manager.root.update()
    assert jview.notebook_drafts["combat"]["encounter"] == "Example Boss"
    assert "fight" in jview._notebooks
