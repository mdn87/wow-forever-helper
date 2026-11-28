"""Synthetic isolated-desktop check: controls stay whole at each window's minimum size.

A 27 Nov 2026 capture pass found rows of buttons running past the right edge and
dialog bodies pressing their buttons flat once a window was shrunk to its minimum.
Every surface below opens at its own minimum size, in Classic at 1.33 scaling and
Modern Synth at 1.67, with the default and a 20-point chat font, and every tab is visited.
Notebook tabs must also keep the width they have in a wide window, or their labels are cut.
Text areas that show a preview keep enough height for their own font size.

Tk keeps a point-size font at the scaling in effect when it was first made, for as long as
any widget uses it, so a case can draw some fonts at the other case's scaling. The checks
measure the widgets as drawn, so they hold either way, but sizes differ by test order.
"""

from tkinter import font

import pytest

from test_gear_ui import panel as gear_panel
from test_voice_input import FakeDictation, FakeKey
from test_workspace import SESSIONS, SyntheticActivities, manager_factory, settle  # noqa: F401
from wow_helper.chat import ChatError
from wow_helper.setup_health_ui import SetupHealthDialog
from wow_helper.voice_ui import HandsFreeDialog, VoiceDialog
from wow_helper.wow_displays import show_display_setup

WHOLE = {"TButton", "TCheckbutton", "TRadiobutton", "Label", "TLabel"}
FULL_HEIGHT = {"TEntry", "TCombobox", "TSpinbox"}


def cut_controls(top):
    """Mapped controls drawn smaller than they ask for, or past their row's right edge."""
    cut = []

    def walk(widget):
        for child in widget.winfo_children():
            # Scrolled canvas content may extend past the viewport by design.
            if not child.winfo_ismapped() or child.winfo_manager() == "canvas":
                continue
            kind = child.winfo_class()
            if kind in WHOLE | FULL_HEIGHT:
                short = child.winfo_height() < child.winfo_reqheight() - 1
                narrow = kind in WHOLE and child.winfo_width() < child.winfo_reqwidth() - 1
                past_edge = child.winfo_x() + child.winfo_width() > child.master.winfo_width() + 1
                if short or narrow or past_edge:
                    label = child.cget("text") if kind in WHOLE else kind
                    cut.append(f"{label} ({child.winfo_width()}x{child.winfo_height()} of "
                               f"{child.winfo_reqwidth()}x{child.winfo_reqheight()})")
            walk(child)

    walk(top)
    return cut


def notebooks(widget):
    found = [widget] if widget.winfo_class() == "TNotebook" else []
    for child in widget.winfo_children():
        found += notebooks(child)
    return found


def tab_spans(top):
    """Drawn width of each tab of every mapped notebook, by asking which tab lies under each point."""
    spans = {}
    for book in notebooks(top):
        shown = [tab for tab in book.tabs() if book.tab(tab, "state") != "hidden"]
        if not book.winfo_ismapped() or not shown:
            continue
        for y in range(1, 60, 2):
            hits = [book.tk.call(book._w, "index", f"@{x},{y}") for x in range(book.winfo_width())]
            hits = [int(hit) for hit in hits if str(hit) != ""]
            if len(set(hits)) == len(shown):
                spans.update({(str(book), book.tab(index, "text")): hits.count(index) for index in set(hits)})
                break
    return spans


def squeezed_tabs(top):
    """Tabs drawn narrower at this size than in a much wider window; Tk squeezes them and cuts the labels."""
    narrow = tab_spans(top)
    if not narrow:
        return []
    size = "%dx%d" % (top.winfo_width(), top.winfo_height())
    top.geometry("%dx%d" % (top.winfo_width() + 900, top.winfo_height()))
    top.update()
    wide = tab_spans(top)
    top.geometry(size)
    top.update()
    return [f"{key[1]} tab ({width} of {wide[key]} px wide)" for key, width in narrow.items()
            if key in wide and width < wide[key] - 1]


def cut_on_every_tab(top):
    top.update()
    cut = set(cut_controls(top) + squeezed_tabs(top))
    for book in notebooks(top):
        selected = book.select()
        for tab in book.tabs():
            book.select(tab)
            top.update()
            cut |= {f"{book.tab(tab, 'text')} tab: {item}" for item in cut_controls(top) + squeezed_tabs(top)}
        if selected:
            book.select(selected)
    return sorted(cut)


class FailingActivities(SyntheticActivities):
    def reports(self, steps, flavor):
        raise ChatError("No snapshot for this edition. Enable WoW Companion and /reload in game, then Refresh.")


def open_task(kind):
    def opener(manager, _tmp):
        window = manager.new_window(kind=kind)
        settle(window.view) if window.view else None
        return window.root
    return opener


def open_chat(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    return manager.windows[0].root


def open_model(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_model_settings()
    settle(view)
    return view._model_dialog.root


def open_goal(manager, _tmp):
    view = manager.windows[0].view
    view.show_goals()
    view._resume_dialog.edit_goal(new=True)
    return view._resume_dialog.goal_dialog.root


def open_coaching(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_combat_coaching()
    return view._notebooks["combat"].root


def open_window_setup(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_setup()
    return view._setup_dialog.root


def open_bookmark(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.bookmark_moment()
    return view._bookmark_dialog.root


def open_fight_question(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_fight_question()
    return view._notebooks["fight"].root


def open_economy(manager, _tmp):
    view = manager.windows[0].view
    view._select_session(SESSIONS[0])
    settle(view)
    view.show_economy_notebook()
    return view._notebooks["economy"].root


def open_live_gear(manager, _tmp):
    _, dialog = gear_panel(manager)
    # The longest status the Result tab shows; a fixed wrap cut it at the minimum width.
    dialog.progress.set("Shortcut enabled · Comparison complete — review Result · capture age 0s · "
                        "capture 0.0s, extraction 0.0s, explanation 0.0s")
    return dialog.root


def open_appearance(manager, _tmp):
    view = manager.windows[0].view
    view.show_appearance()
    return view._appearance_dialog.root


def open_resume(manager, _tmp):
    view = manager.windows[0].view
    view.resume_session()
    return view._resume_dialog.root


def open_goals(manager, _tmp):
    view = manager.windows[0].view
    view.show_goals()
    return view._resume_dialog.root


def open_voice(manager, _tmp):
    return VoiceDialog(manager, manager.windows[0], dictation_factory=FakeDictation, key_factory=FakeKey).root


def open_handsfree(manager, _tmp):
    manager._handsfree_dialog = HandsFreeDialog(manager, manager.windows[0])
    return manager._handsfree_dialog.root


def open_displays(manager, _tmp):
    return show_display_setup(manager, manager.windows[0].root)


def open_setup_health(manager, tmp):
    window = manager.windows[0]
    settle(window.view)
    dialog = SetupHealthDialog(manager, window, settings_path=tmp / "companion.json",
                               assist_path=tmp / "assist.sqlite", roots_fn=lambda _cfg=None: [],
                               install_fn=lambda *_args, **_kwargs: None)
    return dialog.root


SURFACES = {
    "chat": (open_chat, None),
    "chooser": (open_task("chooser"), None),
    "quests": (open_task("quests"), None),
    "quests needing setup": (open_task("quests"), FailingActivities),
    "character": (open_task("character"), None),
    "journal": (open_task("journal"), None),
    "screen adviser": (open_task("screen"), None),
    "change model": (open_model, None),
    "personal goal": (open_goal, None),
    "post-fight coaching": (open_coaching, None),
    "window setup": (open_window_setup, None),
    "bookmark": (open_bookmark, None),
    "ask about the last fight": (open_fight_question, None),
    "session economy analysis": (open_economy, None),
    "live gear comparison": (open_live_gear, None),
    "voice input": (open_voice, None),
    "hands-free voice": (open_handsfree, None),
    "companion displays": (open_displays, None),
    "setup health": (open_setup_health, None),
    "chat appearance": (open_appearance, None),
    "resume session": (open_resume, None),
    "goals and wishlist": (open_goals, None),
}


@pytest.mark.parametrize("font_size", [None, 20])
@pytest.mark.parametrize("theme,scaling", [("classic", 1.33), ("modern", 1.67)])
@pytest.mark.parametrize("surface", list(SURFACES))
def test_controls_stay_whole_at_minimum_size(manager_factory, tmp_path, surface, theme, scaling, font_size):
    opener, activities = SURFACES[surface]
    manager = manager_factory(activity=lambda: activities(tmp_path)) if activities else manager_factory()
    manager.interface = {**manager.interface, "theme": theme}
    manager.preview_interface(None)
    view = manager.windows[0].view
    if font_size:
        settle(view)
        view.set_appearance({**view.appearance, "font_size": font_size})
    root = manager.windows[0].root
    original = root.tk.call("tk", "scaling")
    root.tk.call("tk", "scaling", scaling)
    try:
        top = opener(manager, tmp_path)
        if font_size:  # a window the opener created keeps its own default appearance
            for window in manager.windows:
                if window.view and window.view.appearance["font_size"] != font_size:
                    window.view.set_appearance({**window.view.appearance, "font_size": font_size})
                    settle(window.view)
        top.geometry("%dx%d" % top.minsize())
        cut = cut_on_every_tab(top)
        assert not cut, f"{top.minsize()} wants {top.winfo_reqwidth()}x{top.winfo_reqheight()}: " + "; ".join(cut)
    finally:
        root.tk.call("tk", "scaling", original)


def themed(manager_factory, theme, font_size=None):
    manager = manager_factory()
    manager.interface = {**manager.interface, "theme": theme}
    manager.preview_interface(None)
    view = manager.windows[0].view
    settle(view)
    if font_size:
        view.set_appearance({**view.appearance, "font_size": font_size})
    return manager, view


def visible_lines(text):
    """Whole lines of the text's own font that fit inside its visible area."""
    inset = 2 * sum(int(text.cget(option)) for option in ("pady", "borderwidth", "highlightthickness"))
    return (text.winfo_height() - inset) // font.Font(root=text, font=text.cget("font")).metrics("linespace")


@pytest.mark.parametrize("theme,scaling", [("classic", 1.33), ("modern", 1.67)])
def test_chat_appearance_preview_shows_every_line_as_the_font_grows(manager_factory, theme, scaling):
    # At 20 points the preview kept its 11-point height and cut the second message.
    manager, view = themed(manager_factory, theme)
    root = manager.windows[0].root
    original = root.tk.call("tk", "scaling")
    root.tk.call("tk", "scaling", scaling)
    try:
        view.show_appearance()
        dialog = view._appearance_dialog
        top = dialog.root
        top.update()
        base = top.minsize()
        for size in (20, 28, 11):
            dialog.variables["font_size"].set(str(size))
            top.update()
            top.geometry("%dx%d" % top.minsize())
            top.update()
            assert dialog.preview.yview() == (0.0, 1.0), (
                f"{size} pt preview cut at {top.winfo_width()}x{top.winfo_height()}, minimum {top.minsize()}")
        # Back at the default size, the dialog's own minimum applies again.
        assert top.minsize() == base
        dialog.close()
    finally:
        root.tk.call("tk", "scaling", original)


@pytest.mark.parametrize("opener", [open_resume, open_goals])
@pytest.mark.parametrize("theme,scaling", [("classic", 1.33), ("modern", 1.67)])
def test_saved_advice_reading_pane_keeps_three_lines_at_minimum_size(manager_factory, tmp_path, theme, scaling,
                                                                    opener):
    # With a 20-point chat font the pane under the buttons showed one line at the minimum size.
    manager, view = themed(manager_factory, theme, font_size=20)
    root = manager.windows[0].root
    original = root.tk.call("tk", "scaling")
    root.tk.call("tk", "scaling", scaling)
    try:
        top = opener(manager, tmp_path)
        top.update()
        top.geometry("%dx%d" % top.minsize())
        top.update()
        pane = view._resume_dialog.preview
        assert visible_lines(pane) >= 3, f"{visible_lines(pane)} lines at {top.winfo_width()}x{top.winfo_height()}"
        assert not cut_controls(top)
    finally:
        root.tk.call("tk", "scaling", original)
