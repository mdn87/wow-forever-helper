"""Synthetic isolated-desktop regression tests for UX Batch 1 (U01-U05)."""

from dataclasses import replace
import uuid

import pytest
from PIL import Image

from test_gear_ui import Key, panel as gear_panel
from test_voice_input import FakeDictation, FakeKey
from test_workspace import SESSIONS, manager_factory, settle  # noqa: F401
from wow_helper.chat import Message
from wow_helper.gear_ui import GearDialog
from wow_helper.voice_ui import HandsFreeDialog, VoiceDialog
from wow_helper.wow_displays import monitor_labels, show_display_setup


def _contrast(fg_hex, bg_hex):
    def channel(value):
        s = int(value, 16) / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    def lum(code):
        r, g, b = channel(code[1:3]), channel(code[3:5]), channel(code[5:7])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1, l2 = sorted((lum(fg_hex), lum(bg_hex)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_u01_wm_delete_window_cleans_up_voice_gear_and_journal_dialogs(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    # VoiceDialog WM_DELETE_WINDOW releases fake mic/key and clears singleton ref.
    voice = manager._voice_dialog = VoiceDialog(
        manager, window, dictation_factory=FakeDictation, key_factory=FakeKey
    )
    voice.enable()
    backend = voice.dictation
    manager.root.tk.call(voice.root.protocol("WM_DELETE_WINDOW"))
    assert backend.closed and manager._voice_dialog is None
    manager.show_voice_input(window)
    assert manager._voice_dialog is not None
    manager._voice_dialog.close()

    # GearDialog WM_DELETE_WINDOW releases shortcut and clears singleton ref.
    _, gear = gear_panel(manager)
    gear.review_region()
    gear.enable()
    key = gear.key
    manager.root.tk.call(gear.root.protocol("WM_DELETE_WINDOW"))
    assert key.closed and view._gear_dialog is None
    view.show_live_gear()
    assert view._gear_dialog is not None
    view._gear_dialog.close()

    # HandsFreeDialog, BookmarkDialog, ResumeDialog all clean up on WM_DELETE_WINDOW.
    hf = manager._handsfree_dialog = HandsFreeDialog(manager, window)
    manager.root.tk.call(hf.root.protocol("WM_DELETE_WINDOW"))
    assert manager._handsfree_dialog is None

    view.bookmark_moment()
    assert view._bookmark_dialog is not None
    manager.root.tk.call(view._bookmark_dialog.root.protocol("WM_DELETE_WINDOW"))
    assert view._bookmark_dialog is None

    view.resume_session()
    assert view._resume_dialog is not None
    manager.root.tk.call(view._resume_dialog.root.protocol("WM_DELETE_WINDOW"))
    assert view._resume_dialog is None


def test_u01_dialogs_inherit_topmost_escape_and_secondary_monitor_placement(manager_factory, monkeypatch):
    areas = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]
    monkeypatch.setattr("wow_helper.window_state.display_workareas", lambda _root: areas)
    monkeypatch.setattr("wow_helper.workspace.display_workareas", lambda _root: areas)

    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)
    view.editor.insert("1.0", "Keep my draft across Escape")
    window.topmost.set(True)
    window.set_topmost()
    window.bounds = {"x": 2000, "y": 100, "width": 620, "height": 700}
    window._place()
    manager.root.update()

    view.bookmark_moment()
    dialog = view._bookmark_dialog
    manager.root.update()
    assert bool(dialog.root.attributes("-topmost")) is True
    assert dialog.root.winfo_x() >= 1920
    assert dialog.root.winfo_x() + dialog.root.winfo_width() <= 3840
    dialog.root.focus_force()
    manager.root.update()
    dialog.root.event_generate("<Escape>")
    manager.root.update()
    assert view._bookmark_dialog is None
    assert view.editor.get("1.0", "end-1c") == "Keep my draft across Escape"

    # Display setup uses WindowFrame, inherits topmost, and labels monitor positions.
    labels = monitor_labels([(0, 0, 1920, 1080), (-1920, 0, 0, 1080), (1920, 0, 3840, 1080)])
    assert labels == [
        "Screen 1 · 1920 × 1080 · Primary",
        "Screen 2 · 1920 × 1080 · Left",
        "Screen 3 · 1920 × 1080 · Right",
    ]
    display_dialog = show_display_setup(manager, window.root)
    manager.root.update()
    assert hasattr(display_dialog, "_companion_frame")
    assert bool(display_dialog.attributes("-topmost")) is True
    assert display_dialog.winfo_x() >= 1920
    display_dialog.destroy()


def test_u01_journal_treeview_refreshes_on_live_theme_switch(manager_factory):
    from tkinter import ttk
    from wow_helper.theme import PALETTES

    manager = manager_factory()
    view = manager.windows[0].view
    settle(view)
    view.resume_session()
    dialog = view._resume_dialog
    style = ttk.Style(dialog.root)
    manager.preview_interface({"theme": "modern"})
    manager.root.update()
    assert style.lookup("Journal.Treeview", "background").lower() == PALETTES["modern"].PANEL.lower()
    manager.preview_interface({"theme": "classic"})
    manager.root.update()
    assert style.lookup("Journal.Treeview", "background").lower() == PALETTES["classic"].PANEL.lower()
    dialog.close()


def test_u02_save_layout_preserves_window_notices_and_plain_chat_surfaces_feedback(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)

    window.set_notice("Hands-free voice connected to Chat 1.")
    assert manager.save_layout()
    assert window.notice.get() == "Hands-free voice connected to Chat 1."

    # Edit reviewed image is disabled in plain Agent chat, enabled in Screen adviser.
    assert str(window.tools_menu.entrycget("Edit reviewed image…", "state")) == "disabled"
    screen = manager.new_window(kind="screen")
    assert str(screen.tools_menu.entrycget("Edit reviewed image…", "state")) == "normal"

    # Activity notices in plain Agent chat mirror visibly into view.status.
    view.activity_notice.set("Bookmark saved locally.")
    assert view.status.get() == "Bookmark saved locally."


def test_u03_live_gear_switches_to_result_and_restores_reviewed_region(manager_factory):
    manager = manager_factory()
    view, dialog = gear_panel(manager)
    dialog.region = [0, 0, 400, 300]
    dialog.review_region()
    assert dialog.book.select() == str(dialog.review)
    dialog.enable()
    dialog.engine.capture = lambda *_, **__: dialog.preview_name
    dialog.engine.identify = lambda _: 42
    dialog.engine.foreground = lambda: 42
    dialog.engine.begin(background=False)
    dialog.poll()
    manager.root.update()
    assert dialog.book.select() == str(dialog.result)
    assert "Comparison complete" in dialog.notice.get()
    # Save a non-full-frame reviewed region and verify reopening restores it without enabling.
    dialog.region = [10, 20, 200, 150]
    dialog.review_region()
    saved_preview = dialog.preview_name
    dialog.close()

    reopened = view._gear_dialog = GearDialog(view, key_factory=Key)
    reopened.preview_flavor = view.profile["flavor"]
    reopened.load_preview(saved_preview)
    assert reopened.region == [10, 20, 200, 150]
    assert reopened.key is None and reopened.engine.approval is None
    reopened.close()


@pytest.mark.parametrize("theme", ["classic", "modern"])
def test_u04_conversation_picker_selection_contrast_is_accessible(manager_factory, theme):
    manager = manager_factory()
    manager.preview_interface({"theme": theme})
    view = manager.windows[0].view
    settle(view)
    view.choose_chat()
    picker = view._picker
    bg = picker.rows.cget("selectbackground")
    fg = picker.rows.cget("selectforeground")
    assert _contrast(fg, bg) >= 4.5
    other = "modern" if theme == "classic" else "classic"
    manager.preview_interface({"theme": other})
    manager.root.update()
    assert _contrast(picker.rows.cget("selectforeground"), picker.rows.cget("selectbackground")) >= 4.5
    picker.close()


@pytest.mark.parametrize("theme", ["classic", "modern"])
def test_u04_plain_ttk_frames_labels_and_tree_headings_use_the_theme(desktop, theme):
    # Unstyled ttk.Frame/ttk.Label rows (Change model's active sessions, Provider
    # usage, Command library search) and default Treeview headings (Activity
    # history, Search, Command library) must not fall back to stock grey or white.
    from tkinter import ttk
    from wow_helper.theme import apply_theme, palette

    _, root = desktop
    previous = getattr(root, "_companion_theme", "classic")
    apply_theme(root, theme)
    try:
        style, colors = ttk.Style(root), palette(root)
        assert style.lookup("TFrame", "background").lower() == colors.PANEL.lower()
        assert style.lookup("TLabel", "background").lower() == colors.PANEL.lower()
        assert style.lookup("TLabel", "foreground").lower() == colors.TEXT.lower()
        surfaces = {colors.PANEL.lower(), colors.TITLE.lower()}
        for state in ([], ["active"]):
            assert style.lookup("Treeview.Heading", "background", state).lower() in surfaces
        assert style.lookup("Treeview.Heading", "foreground").lower() == colors.TEXT.lower()
        assert style.lookup("Treeview", "lightcolor").lower() == colors.EDGE.lower()
        for name in ("TEntry", "TSpinbox"):  # match the combobox edge instead of a white bevel
            assert style.lookup(name, "lightcolor").lower() == colors.EDGE.lower(), name
        # The waiting bar under a chat (BusyBar) kept a stock light-grey trough in Classic.
        assert style.lookup("Horizontal.TProgressbar", "troughcolor").lower() == colors.EDITOR.lower()
    finally:
        apply_theme(root, previous)


@pytest.mark.parametrize("theme", ["classic", "modern"])
def test_u04_notebook_tab_outlines_use_the_theme_edge(desktop, theme):
    # Classic tabs and the tab page frame kept clam's light grey bevel instead of the gold edge.
    from tkinter import ttk
    from wow_helper.theme import apply_theme, palette

    _, root = desktop
    previous = getattr(root, "_companion_theme", "classic")
    apply_theme(root, theme)
    try:
        style, colors = ttk.Style(root), palette(root)
        for name in ("TNotebook", "TNotebook.Tab", "Touch.TNotebook", "Touch.TNotebook.Tab"):
            for option in ("bordercolor", "lightcolor", "darkcolor"):
                assert style.lookup(name, option).lower() == colors.EDGE.lower(), (name, option)
    finally:
        apply_theme(root, previous)


def test_u05_smart_scroll_preserves_anchored_passage_across_append_resize_and_font_change(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    view = window.view
    settle(view)
    view._select_session(SESSIONS[0])
    settle(view)

    messages = [
        Message(f"m-{i}", "assistant" if i % 2 else "user",
                f"Passage {i:02d}: " + ("synthetic quest step details " * 8))
        for i in range(40)
    ]
    view._show(messages)
    manager.root.update()
    assert view.transcript.yview()[1] >= 0.98
    assert not view.jump_latest_button.winfo_manager()

    # Scroll up to Passage 10 and capture content anchor.
    target_start = next(start for key, start, _ in view.message_ranges if key == "m-10")
    view.transcript.yview(target_start)
    view._capture_scroll_anchor()
    manager.root.update()
    assert view._pinned_to_bottom is False
    assert view._scroll_anchor[0] == "m-10"
    assert view.jump_latest_button.winfo_manager()

    def top_line_text():
        idx = view.transcript.index("@0,0")
        return view.transcript.get(f"{idx} linestart", f"{idx} lineend")

    assert "Passage 10:" in top_line_text()

    # 1. Appending a long reply keeps Passage 10 anchored at top.
    messages.append(Message("m-40", "assistant", "Long new reply.\n" * 60))
    view._show(messages)
    manager.root.update()
    assert "Passage 10:" in top_line_text()
    assert view.jump_latest_button.winfo_manager()

    # 2. Resizing window width keeps Passage 10 anchored at top.
    window.bounds = {"x": 80, "y": 80, "width": 460, "height": 580}
    window._place()
    manager.root.update()
    assert "Passage 10:" in top_line_text()

    # 3. Changing font size keeps Passage 10 anchored at top.
    view.set_appearance({**view.appearance, "font_size": 15})
    manager.root.update()
    assert "Passage 10:" in top_line_text()

    # 4. Clicking Jump to latest returns to bottom and hides the button.
    view.jump_latest_button.invoke()
    manager.root.update()
    assert view._pinned_to_bottom is True
    assert view.transcript.yview()[1] >= 0.98
    assert not view.jump_latest_button.winfo_manager()
