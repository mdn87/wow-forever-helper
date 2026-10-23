"""Synthetic window lifecycle checks; no real agent connection or game input."""

import json
import os
import threading
import time
import uuid

import pytest

from wow_helper.chat import ChatError, Message, Session
from wow_helper.workspace import WindowManager
from wow_helper.window_state import LayoutLock, MAX_WINDOWS, MIN_HEIGHT, MIN_WIDTH, window_bounds
from wow_helper.activities import ActivityService, TYPES

SESSIONS = [Session("codex", str(uuid.UUID(int=0)), "Synthetic planning", "ExampleProject", "idle"),
            Session("claude", str(uuid.UUID(int=1)), "Synthetic review", "ExampleProject", "idle")]


class Service:
    sessions = list(SESSIONS)

    def __init__(self):
        self.sent = []
        self.closed = False
        self.gate = None

    def discover(self):
        return self.sessions, []

    def history(self, session):
        return [Message("synthetic-reply", "assistant", session.title)]

    def send(self, session, body, request_id):
        if self.gate is not None and not self.gate.wait(5):
            raise RuntimeError("Synthetic send timed out")
        self.sent.append((session.key, body))
        return "queued"

    def close(self):
        self.closed = True


class SyntheticActivities(ActivityService):
    def __init__(self, path):
        super().__init__(path)
        self.calls = []

    def reports(self, steps, flavor):
        from pathlib import Path
        from wow_helper import character, quests
        from wow_helper.savedvars import parse
        self.calls.append((steps, flavor))
        parsed = parse((Path(__file__).parent / "fixtures" / "savedvariables_quests.lua").read_text())
        reports = {}
        for kind in steps:
            data = (quests.report(quests.load(parsed), 1000, flavor=flavor, now=1030) if kind == "quests"
                    else character.report(parsed, 1000, flavor=flavor, now=1030))
            reports[kind] = {"snapshot_at": 1000, "data": data,
                             "text": quests.as_text(data) if kind == "quests" else character.as_text(data)}
        return reports


class CreatingService(Service):
    def __init__(self):
        super().__init__()
        self.sessions = list(SESSIONS)
        self.created = []

    def create(self, provider, *, creation_id, **options):
        session = Session(provider, creation_id, "Synthetic new chat", "ExampleProject", "ready", managed=True)
        self.sessions.append(session)
        self.created.append((session, options))
        return session


@pytest.fixture
def manager_factory(tmp_path, desktop):
    tk, parent = desktop
    managers, views = [], []

    def create(path=tmp_path / "windows.json", service=Service, activity=None):
        root = tk.Toplevel(parent)
        root.withdraw()
        manager = WindowManager(root, service_factory=service,
                                activity_factory=activity or (lambda: SyntheticActivities(tmp_path / "activities")),
                                layout_path=path)
        managers.append(manager)
        root.update()
        for window in manager.windows:
            if window.view:
                views.append(window.view)
                settle(window.view)
        return manager

    yield create
    for manager in managers:
        views.extend(w.view for w in manager.windows if w.view)
        manager.close()
    for view in views:
        view.worker.shutdown(wait=True)
        for child in view.quest_chats.values():
            child.worker.shutdown(wait=True)
    parent.update()


def settle(view):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        view.root.update()
        if not view.busy:
            return
        time.sleep(0.01)
    pytest.fail("Synthetic chat did not finish")


def choose(window, index):
    window.view.session_picker.current(index)
    window.view.session_picker.event_generate("<<ComboboxSelected>>")
    settle(window.view)


def new_chat(manager, source):
    window = manager.new_window(source)
    window.chat_button.invoke()
    settle(window.view)
    return window


def test_linked_reply_save_freezes_source_and_resume_keeps_drafts(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    choose(window, 0)
    view = window.view
    view.editor.insert("1.0", "Unsent conversation draft")
    view.transcript.focus_force()
    view.root.update()
    view.transcript.event_generate("<Control-j>")
    view.root.update()
    dialog = view._journal_dialog
    source = dict(dialog.selection["source"])
    choose(window, 1)
    dialog.next_time.set("Check the route")
    journal_id = dialog.new_id
    dialog.save()
    entry = view.activity.journal(journal_id)["entries"][0]
    assert entry["source"] == source and entry["text"] == SESSIONS[0].title
    journal = manager.new_window(kind="journal")
    journal.view.journal_id = journal_id
    journal.view.show_journal(view.activity.journal(journal_id))
    journal.view.note.insert("1.0", "Unsent journal draft")
    journal.view.resume_session()
    resume = journal.view._resume_dialog
    resume.entries.selection_set(entry["id"])
    resumed = resume.continue_conversation()
    settle(resumed)
    assert resumed.selection_key == SESSIONS[0].key
    assert len(manager.windows) == 3  # Do not replace the window now displaying another chat.
    assert journal.view.note.get("1.0", "end-1c") == "Unsent journal draft"
    resume.mark_done()
    assert view.activity.journal(journal_id)["entries"][0]["next_time"]["state"] == "done"
    assert not any(w.view.service.sent for w in manager.windows)
    choose(window, 0)
    assert view.editor.get("1.0", "end-1c") == "Unsent conversation draft"
    assert manager.resume_conversation(source) is view


def test_resume_unavailable_source_and_window_limit_never_create_or_send(manager_factory):
    manager = manager_factory(service=CreatingService)
    source = {"provider": "codex", "session_id": str(uuid.UUID(int=900)), "message_id": "missing"}
    resumed = manager.resume_conversation(source)
    settle(resumed)
    assert resumed.selected is None and resumed.desired_key == ("codex", source["session_id"])
    assert not resumed.service.created and not resumed.service.sent
    while len(manager.windows) < MAX_WINDOWS:
        manager.new_window()
    other = dict(source, session_id=str(uuid.UUID(int=901)))
    with pytest.raises(ChatError, match="Eight"):
        manager.resume_conversation(other)
    assert len(manager.windows) == MAX_WINDOWS


def test_journal_followup_reviews_history_and_refresh_sends_once(manager_factory):
    manager = manager_factory()
    target = manager.windows[0]
    choose(target, 0)
    target.view.editor.insert("1.0", "Keep this draft")
    journal = manager.new_window(kind="journal")
    view = journal.view
    settle(view)
    entry = view.activity.add_note(view.journal_id, "Example", "Historical advice",
                                  source={"provider": SESSIONS[0].provider, "session_id": SESSIONS[0].id},
                                  evidence={"edition": "Classic Forever beta", "text": json.dumps({"reports": {
                                      "quests": {"snapshot_at": 500, "text": "Old snapshot"}}})})["entries"][0]
    view.resume_session()
    resume = view._resume_dialog
    resume.prepare_followup()
    followup = resume.followup
    followup.refresh_report()
    settle(view)
    assert not target.view.service.sent
    assert followup.packet is not None, followup.notice.get()
    assert "Old snapshot" in followup.packet["context_files"][0]["text"]
    assert '"snapshot_at": 1000' in followup.packet["context_files"][0]["text"]
    assert followup.entry == entry
    from copy import deepcopy
    from wow_helper.activities import packet_preview
    packet = deepcopy(followup.packet)
    assert followup.preview.get("1.0", "end-1c") == packet_preview(packet)
    followup.send()
    followup.send()
    settle(target.view)
    assert len(target.view.service.sent) == 1
    saved = json.loads((view.activity.storage / "prepared" / (followup.request_id + ".json")).read_text())
    assert saved == packet
    assert target.view.editor.get("1.0", "end-1c") == "Keep this draft"
    manager.save_layout()
    path = manager.layout_path
    manager.close()
    restored = manager_factory(path)
    assert all(not window.view.service.sent for window in restored.windows)


def test_followup_session_change_invalidates_preview_even_after_switching_back(manager_factory):
    manager = manager_factory()
    target = manager.windows[0]
    choose(target, 0)
    journal = manager.new_window(kind="journal")
    view = journal.view
    view.activity.add_note(view.journal_id, "Example", "Advice", source={"provider": "codex", "session_id": SESSIONS[0].id})
    view.resume_session()
    view._resume_dialog.prepare_followup()
    dialog = view._resume_dialog.followup
    choose(target, 1)
    choose(target, 0)
    dialog.send()
    assert not target.view.service.sent and dialog.packet is None


def test_linked_notes_survive_restart_with_chat_retention_off(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    choose(window, 0)
    window.remember.set(False)
    window.view.save_to_journal()
    dialog = window.view._journal_dialog
    key = dialog.new_id
    dialog.save()
    saved = window.view.activity.journal(key)
    manager.save_layout()
    path = manager.layout_path
    manager.close()
    restored = manager_factory(path)
    assert restored.windows[0].view.activity.journal(key) == saved


def test_quest_reply_save_and_resume_reuse_tab_without_opening_request(manager_factory):
    manager = manager_factory(service=CreatingService)
    window = manager.new_window(kind="quests")
    view = window.view
    settle(view)
    _, child = open_synthetic_quest_chat(view)
    before = len(child.service.sent)
    child.editor.insert("1.0", "Unsent quest question")
    view.save_to_journal()
    dialog = child._journal_dialog
    assert dialog.selection["evidence"]["quest_id"] == child.context["quest"]["id"]
    original = dialog.selection["evidence"]["text"]
    view.book.select(view.panel)
    child._show([Message("newer", "assistant", "A later reply")])
    key = dialog.new_id
    dialog.save()
    entry = child.activity.journal(key)["entries"][0]
    assert entry["evidence"]["text"] == original
    assert entry["text"] != "A later reply"
    assert manager.resume_conversation(entry["source"]) is child
    assert view.active_quest_chat() is child
    assert child.editor.get("1.0", "end-1c") == "Unsent quest question"
    assert len(child.service.sent) == before


def test_interface_preview_cancel_and_save_preserve_chats(manager_factory):
    from wow_helper.theme import PALETTES, settings_icon
    manager = manager_factory()
    first = manager.windows[0]
    choose(first, 0)
    first.view.editor.insert("1.0", "Synthetic unsent draft")
    transcript = first.view.transcript.get("1.0", "end-1c")
    second = new_chat(manager, first)
    custom = {"background": "#ffffff", "text": "#112233", "user_text": "#663300"}
    second.view.set_appearance(custom)
    manager.show_interface(first)
    dialog = manager._interface_dialog
    manager.show_interface(second)
    assert manager._interface_dialog is dialog
    for _ in range(2):
        dialog.theme_buttons["modern"].invoke()
        first.root.update()
        assert first.view.transcript.cget("bg") == PALETTES["modern"].PANEL
        assert second.view.transcript.cget("bg") == "#ffffff"
        assert first.chrome.title_font.actual("family") == "Segoe UI"
        assert str(first.options_menu.cget("bg")) == PALETTES["modern"].PANEL
        assert str(first.menu_button.cget("image")[0]) == str(settings_icon(first.root))
        dialog.theme_buttons["classic"].invoke()
    dialog.theme_buttons["modern"].invoke()
    dialog.solid_when_active.set(False)
    dialog.set_opacity(82)
    assert first.root.attributes("-alpha") == pytest.approx(.82, abs=.01)
    assert dialog.root.attributes("-alpha") == 1
    manager.save_layout()  # Ordinary autosaves must not commit a preview.
    saved = json.loads(manager.layout_path.read_text())["interface"]
    assert saved["theme"] == "classic" and saved["opacity"] == 100
    dialog.close()
    assert first.root.attributes("-alpha") == 1
    assert first.view.transcript.cget("bg") == PALETTES["classic"].PANEL
    assert first.view.editor.get("1.0", "end-1c") == "Synthetic unsent draft"
    assert first.view.transcript.get("1.0", "end-1c") == transcript
    assert first.view.service.sent == second.view.service.sent == []
    manager.show_interface(first)
    dialog = manager._interface_dialog
    dialog.theme_buttons["modern"].invoke()
    dialog.solid_when_active.set(False)
    dialog.set_opacity(87)
    dialog.save_button.invoke()
    assert manager._interface_dialog is None
    manager.close()
    restored = manager_factory()
    assert restored.interface == {"theme": "modern", "opacity": 87, "solid_when_active": False}
    first, second = restored.windows
    assert first.root.attributes("-alpha") == pytest.approx(.87, abs=.01)
    assert first.view.transcript.cget("bg") == PALETTES["modern"].PANEL
    assert second.view.transcript.cget("bg") == "#ffffff"
    assert first.view.editor.get("1.0", "end-1c") == "Synthetic unsent draft"
    assert first.view.service.sent == []


def test_interface_failed_save_keeps_preview_and_cancel_restores(manager_factory, monkeypatch):
    from wow_helper.interface import INTERFACE_DEFAULTS
    manager = manager_factory()
    manager.show_interface(manager.windows[0])
    dialog = manager._interface_dialog
    dialog.theme_buttons["modern"].invoke()
    with monkeypatch.context() as patch:
        def fail(*_): raise OSError("Synthetic disk failure")
        patch.setattr("wow_helper.workspace.write_json", fail)
        dialog.save_button.invoke()
        assert manager._interface_dialog is dialog
        assert "Could not save" in dialog.error.get()
        assert manager.interface == INTERFACE_DEFAULTS
    dialog.close()
    assert manager.display_settings == INTERFACE_DEFAULTS


def test_native_opacity_follows_focus_and_survives_hiding(manager_factory, monkeypatch):
    manager = manager_factory()
    errors = []
    monkeypatch.setattr(manager.root._root(), "report_callback_exception", lambda *args: errors.append(args[1]))
    first = manager.windows[0]
    second = new_chat(manager, first)
    manager.interface = {"theme": "modern", "opacity": 78, "solid_when_active": True}
    manager.preview_interface(None)
    first.view.editor.focus_force()
    manager.root.update()
    assert first.root.attributes("-alpha") == 1
    assert second.root.attributes("-alpha") == pytest.approx(.78, abs=.01)
    first.view.session_picker.event_generate("<Button-1>")
    manager.root.update()
    assert manager.root.tk.call("winfo", "ismapped", str(first.view.session_picker) + ".popdown")
    first.view.session_picker.event_generate("<Escape>")
    manager.root.update()
    assert not first.notice.get()
    second.view.editor.focus_force()
    manager.root.update()
    assert second.root.attributes("-alpha") == 1
    assert first.root.attributes("-alpha") == pytest.approx(.78, abs=.01)
    first.root.withdraw()
    manager.reveal(first)
    manager.root.update()
    assert first.root.state() == "normal"
    assert not first.opacity.closed
    first.opacity.schedule()
    manager.close_window(first)
    manager.root.update()
    assert first.opacity.closed and first.opacity._after is None
    assert not errors


def test_modern_new_windows_dialogs_and_reports_fit_and_follow_theme(manager_factory):
    from wow_helper.theme import PALETTES
    manager = manager_factory()
    manager.interface = {"theme": "modern", "opacity": 85, "solid_when_active": False}
    manager.preview_interface(None)
    for kind in ("chooser", "quests", "character", "journal", "screen"):
        window = manager.new_window(kind=kind)
        window.chrome.place("440x580+40+40")
        if window.view:
            settle(window.view)
        window.root.update()
        assert window.body.cget("bg") == PALETTES["modern"].PANEL
        assert window.root.attributes("-alpha") == pytest.approx(.85, abs=.01)
        for control in (window.new_button, window.menu_button, window.chrome.close_button):
            assert control.winfo_ismapped()
            assert control.winfo_rootx() + control.winfo_width() <= window.root.winfo_rootx() + 440
        if kind == "journal":
            window.view.note.insert("1.0", "Synthetic journal draft")
            assert window.view.note.cget("bg") == PALETTES["modern"].EDITOR
    manager.show_interface(manager.windows[0])
    dialog = manager._interface_dialog
    dialog.chrome.place("460x600+40+40")
    dialog.root.update()
    assert dialog.save_button.winfo_ismapped()
    assert dialog.slider.winfo_ismapped()
    assert dialog.save_button.winfo_rooty() + dialog.save_button.winfo_height() < dialog.root.winfo_rooty() + 600
    dialog.slider.focus_force()
    dialog.root.update()
    dialog.slider.event_generate("<Left>")
    dialog.root.update()
    assert dialog.values()["opacity"] == 84
    dialog.close()
    manager.preview_interface({"theme": "classic"})
    manager.root.update()
    for window in manager.windows:
        if window.kind == "journal":
            assert window.view.note.get("1.0", "end-1c") == "Synthetic journal draft"
    manager.preview_interface(None)


@pytest.mark.parametrize("height", [MIN_HEIGHT, 600])
def test_first_launch_starts_one_chat_and_new_window_copies_size_with_chooser(manager_factory, height):
    manager = manager_factory()
    assert len(manager.windows) == 1
    first = manager.windows[0]
    assert first.kind == "chat"
    first.root.geometry(f"560x{height}+40+40")
    first.root.update()
    first.new_button.invoke()
    second = manager.windows[1]
    second.root.update()
    assert second.kind == "chooser" and second.view is None
    assert second.root.winfo_toplevel() is not first.root
    assert second.capture_bounds()["width"] == first.capture_bounds()["width"] == 560
    assert second.capture_bounds()["height"] == first.capture_bounds()["height"] == height
    assert second.capture_bounds()["x"] == first.capture_bounds()["x"] + 32
    assert second.topmost.get() and second.root.attributes("-topmost")
    second.chat_button.invoke()
    settle(second.view)
    assert second.kind == "chat" and second.view.selection_key is None
    assert second.view.service is not first.view.service


def test_two_windows_route_independently_while_one_send_waits(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    second = new_chat(manager, first)
    choose(first, 0)
    choose(second, 1)
    gate = threading.Event()
    first.view.service.gate = gate
    try:
        first.view.editor.insert("1.0", "Plan the next step")
        second.view.editor.insert("1.0", "Review the plan")
        first.view.send()
        second.view.send()
        settle(second.view)
        assert first.view.busy
        assert second.view.service.sent == [(SESSIONS[1].key, "Review the plan")]
        assert "Review the plan" not in first.view.transcript.get("1.0", "end")
    finally:
        gate.set()
        settle(first.view)
    assert first.view.service.sent == [(SESSIONS[0].key, "Plan the next step")]
    manager.close_window(first)
    first.view.worker.shutdown(wait=True)
    assert first.view.service.closed
    assert not second.view.closed
    assert not second.view.service.closed


def test_quit_and_restart_preserves_ids_geometry_chooser_sessions_drafts_and_history(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    choose(first, 1)
    first.view.editor.insert("1.0", "Remember this draft")
    first.root.geometry("580x580+140+60")
    first.topmost.set(False)
    first.set_topmost()
    chooser = manager.new_window(first)
    first.root.update()
    before = [window.snapshot() for window in manager.windows]
    manager.close()
    restored = manager_factory()
    assert [w.id for w in restored.windows] == [r["id"] for r in before]
    chat, new = restored.windows
    assert chat.capture_bounds() == before[0]["bounds"]
    assert not chat.topmost.get()
    assert chat.view.selection_key == SESSIONS[1].key
    assert chat.view.editor.get("1.0", "end-1c") == "Remember this draft"
    assert "Synthetic review" in chat.view.transcript.get("1.0", "end")
    assert new.kind == "chooser" and new.view is None
    assert chat.view.service.sent == []
    assert chooser.id == new.id


def test_offline_cached_conversation_stays_visible_without_falling_back(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    choose(window, 0)
    window.view.editor.insert("1.0", "Offline draft")
    manager.close()

    class Offline(Service):
        sessions = [SESSIONS[1]]

    restored = manager_factory(service=Offline)
    view = restored.windows[0].view
    assert view.selected is None and view.selection_key == SESSIONS[0].key
    assert "Saved history" in view.subtitle.get()
    assert "Synthetic planning" in view.transcript.get("1.0", "end")
    assert view.editor.get("1.0", "end-1c") == "Offline draft"
    assert str(view.send_button["state"]) == "disabled"
    view.service.sessions = list(SESSIONS)
    view.refresh()
    settle(view)
    assert view.selected.key == SESSIONS[0].key
    assert view.service.sent == []


def test_restored_offline_history_starts_at_bottom(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    choose(window, 0)
    messages = [Message(f"synthetic-{i}", "assistant", f"Saved reply {i}: " + "Long saved text. " * 40)
                for i in range(30)]
    window.view._show(messages)
    window.root.update()
    window.view.transcript.yview_moveto(0.0)
    manager.close()

    class Offline(Service):
        sessions = []

    restored = manager_factory(service=Offline)
    view = restored.windows[0].view
    view.root.update()
    assert view.selected is None
    assert "Saved reply 29" in view.transcript.get("1.0", "end")
    assert view.transcript.bbox("end-2c") is not None
    last_line = view.transcript.bbox("end-1c")
    padding = sum(int(view.transcript.cget(option)) for option in ("pady", "borderwidth", "highlightthickness"))
    assert last_line is not None
    assert last_line[1] + last_line[3] == view.transcript.winfo_height() - padding


def test_draft_before_session_selection_survives_restart(manager_factory):
    manager = manager_factory()
    manager.windows[0].view.editor.insert("1.0", "Choose the session after writing")
    manager.close()
    restored = manager_factory()
    window = restored.windows[0]
    assert window.view.editor.get("1.0", "end-1c") == "Choose the session after writing"
    choose(window, 0)
    assert window.view.editor.get("1.0", "end-1c") == "Choose the session after writing"


def test_interrupted_send_restores_an_unconfirmed_receipt_and_never_replays(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    choose(window, 0)
    gate = threading.Event()
    window.view.service.gate = gate
    try:
        window.view.editor.insert("1.0", "One explicit request")
        window.view.send()
        manager.close()
        restored = manager_factory()
        view = restored.windows[0].view
        assert "DELIVERY UNCONFIRMED" in view.transcript.get("1.0", "end")
        assert view.service.sent == []
    finally:
        gate.set()
        window.view.worker.shutdown(wait=True)
    assert len(window.view.service.sent) == 1


def test_signed_native_window_positions_are_saved(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    window.root.geometry("500x550+-700+40")
    window.root.update()
    bounds = window.capture_bounds()
    assert bounds["x"] == -700 and bounds["y"] == 40
    manager.save_layout()
    assert json.loads(manager.layout_path.read_text())["windows"][0]["bounds"] == bounds


def test_remember_can_be_disabled_and_clears_saved_chat_text(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    choose(window, 0)
    window.view.editor.insert("1.0", "Private unsent draft")
    manager.save_layout()
    assert "Private unsent draft" in manager.layout_path.read_text()
    window.options_menu.invoke(1)
    data = json.loads(manager.layout_path.read_text())
    assert not data["windows"][0]["remember"]
    assert "messages" not in data["windows"][0]["chat"]
    assert "Private unsent draft" not in manager.layout_path.read_text()
    assert data["windows"][0]["chat"]["session"]["id"] == SESSIONS[0].id
    assert window.view.editor.get("1.0", "end-1c") == "Private unsent draft"


def test_close_one_removes_it_but_last_close_keeps_final_window_for_restart(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    second = manager.new_window(first)
    second.chrome.close_button.invoke()
    assert len(manager.windows) == 1
    first.chrome.close_button.invoke()
    assert manager.closed
    restored = manager_factory()
    assert len(restored.windows) == 1
    assert restored.windows[0].id == first.id


def test_custom_title_drag_and_corner_resize_preserve_window_bounds(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    window.root.geometry("620x700+100+100")
    window.root.update()
    moved_sizes = []
    window.root.bind("<Configure>", lambda event: moved_sizes.append((event.width, event.height))
                     if event.widget is window.root else None, add="+")

    def drag(widget, dx, dy):
        widget.event_generate("<ButtonPress-1>", x=10, y=10, rootx=200, rooty=200)
        widget.event_generate("<B1-Motion>", x=10, y=10, rootx=200 + dx, rooty=200 + dy)
        widget.event_generate("<ButtonRelease-1>", x=10, y=10, rootx=200 + dx, rooty=200 + dy)
        window.root.update()

    drag(window.chrome.titlebar, 80, 60)
    assert window.capture_bounds() == {"width": 620, "height": 700, "x": 180, "y": 160}
    if os.name == "nt":
        assert moved_sizes and set(moved_sizes) == {(620, 700)}
    drag(window.chrome.grip, 60, 40)
    assert window.capture_bounds() == {"width": 680, "height": 740, "x": 180, "y": 160}
    drag(window.chrome.grip, -1000, -1000)
    assert window.capture_bounds() == {"width": MIN_WIDTH, "height": MIN_HEIGHT, "x": 180, "y": 160}
    assert window.chrome.drag_start is None


@pytest.mark.skipif(os.name != "nt", reason="Windows native frame behavior")
def test_custom_caption_keeps_native_resize_minimize_maximize_and_saved_normal_size(manager_factory):
    import ctypes
    from ctypes import wintypes
    from tkinter import font

    manager = manager_factory()
    window = manager.windows[0]
    window.root.geometry(f"560x{MIN_HEIGHT}+100+100")
    window.root.update()
    normal = window.capture_bounds()
    assert normal["height"] == MIN_HEIGHT
    assert font.Font(root=window.root, font=window.chrome.title_font).actual("family") == "Marcellus"
    assert window.chrome.native_caption_hidden
    user32 = ctypes.WinDLL("user32")
    get_style = getattr(user32, "GetWindowLongPtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "GetWindowLongW")
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    style = get_style(int(window.root.frame(), 0), -16)
    assert style & 0x00C00000 != 0x00C00000  # WS_CAPTION requires both bits.
    assert style & 0x00070000 == 0x00070000  # Native resize, minimize, maximize.
    window.chrome.maximize_button.invoke()
    window.root.update()
    assert window.root.state() == "zoomed"
    assert window.capture_bounds() == normal
    window.chrome.maximize_button.invoke()
    window.root.update()
    assert window.root.state() == "normal"
    assert window.capture_bounds() == normal
    window.chrome.minimize_button.invoke()
    window.root.update()
    assert window.root.state() == "iconic"
    manager.reveal(window)
    window.root.update()
    assert window.capture_bounds() == normal
    window.topmost.set(False)
    window.set_topmost()
    window.root.update()
    assert get_style(int(window.root.frame(), 0), -16) & 0x00C00000 != 0x00C00000
    assert window.capture_bounds() == normal


def test_minimum_size_keeps_chat_controls_visible_and_max_windows_is_enforced(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    first.root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}+100+100")
    first.root.update()
    bottom = first.root.winfo_rooty() + first.root.winfo_height()
    assert first.view.editor.winfo_height() > 20
    assert first.view.transcript.winfo_height() > 20
    assert first.view.send_button.winfo_rooty() + first.view.send_button.winfo_height() < bottom
    toolbar_buttons = first.new_button.master.winfo_children()
    for button in toolbar_buttons:
        assert button.winfo_width() >= button.winfo_reqwidth()
    for _ in range(MAX_WINDOWS - 1):
        manager.new_window(first)
    assert len(manager.windows) == MAX_WINDOWS
    assert manager.new_window(first) is None
    assert str(first.new_button["state"]) == "disabled"
    manager.close_window(manager.windows[-1])
    assert str(first.new_button["state"]) == "normal"


@pytest.mark.parametrize("size", ["440x580", "620x700"])
def test_compact_toolbar_and_composer_keep_actions_visible(manager_factory, size):
    manager = manager_factory()
    window = manager.windows[0]
    window.chrome.place(size + "+100+100")
    window.root.update()
    view = window.view
    controls = [window.new_button, view.session_picker, view.refresh_button, window.menu_button]
    centers = [widget.winfo_rooty() + widget.winfo_height() / 2 for widget in controls]
    assert max(centers) - min(centers) <= 2
    assert max(widget.winfo_height() for widget in controls) <= 30
    assert view.session_picker.winfo_width() >= 120
    for left, right in zip(controls, controls[1:]):
        assert left.winfo_rootx() + left.winfo_width() <= right.winfo_rootx()
    assert controls[-1].winfo_rootx() + controls[-1].winfo_width() < window.root.winfo_rootx() + window.root.winfo_width()
    assert view.transcript.winfo_height() >= window.root.winfo_height() / 2
    assert view.send_button.winfo_ismapped()
    assert view.editor.winfo_rootx() + view.editor.winfo_width() <= view.send_button.winfo_rootx()
    assert view.send_button.winfo_rooty() >= view.editor.winfo_rooty()
    assert view.send_button.winfo_rooty() + view.send_button.winfo_height() <= view.editor.winfo_rooty() + view.editor.winfo_height()
    choose(window, 1)
    assert window.options_menu.entrycget(view.setup_menu_index, "state") == "normal"
    window.options_menu.invoke(view.setup_menu_index)
    dialog = next(child for child in view.root.winfo_children() if isinstance(child, manager.tk.Toplevel))
    assert dialog.title() == "Connect this Claude session"
    dialog.destroy()
    choose(window, 0)
    assert window.options_menu.entrycget(view.setup_menu_index, "state") == "disabled"


@pytest.mark.parametrize("selected", [False, True])
def test_appearance_is_independent_and_survives_restart_without_chat_retention(manager_factory, selected):
    from wow_helper.appearance import DEFAULTS
    manager = manager_factory()
    first = manager.windows[0]
    second = new_chat(manager, first)
    if selected:
        choose(first, 0)
    first.view.editor.insert("1.0", "Synthetic private draft")
    first.remember.set(False)
    first.options_menu.invoke(first.appearance_menu_index)
    dialog = first.view._appearance_dialog
    for key, value in {"background": "#ffffff", "text": "#112233", "user_text": "#663300", "font_size": 18}.items():
        dialog.variables[key].set(value)
    family = next(name for name in dialog.families if name != DEFAULTS["font_family"])
    dialog.variables["font_family"].set(family)
    dialog.save_button.invoke()
    assert first.view._appearance_dialog is None
    assert second.view.appearance == DEFAULTS
    expected = dict(first.view.appearance)
    assert first.view.editor.get("1.0", "end-1c") == "Synthetic private draft"
    manager.close()
    restored = manager_factory()
    view = restored.windows[0].view
    assert view.appearance == expected
    assert view.transcript.cget("background") == view.editor.cget("background") == "#ffffff"
    assert view.transcript.cget("foreground") == "#112233"
    assert view.editor.cget("foreground") == "#663300"
    assert view.editor.get("1.0", "end-1c") == ""
    assert restored.windows[1].view.appearance == DEFAULTS
    assert view.service.sent == []


def test_malformed_saved_appearance_does_not_prevent_windows_opening(manager_factory, tmp_path):
    from wow_helper.appearance import DEFAULTS
    path = tmp_path / "invalid-appearance.json"
    path.write_text(json.dumps({"version": 1, "windows": [{"kind": "chat", "chat": {"appearance": {
        "background": "not a Tk color", "text": [], "font_family": {"bad": "font"}, "font_size": True}}}]}))
    manager = manager_factory(path=path)
    assert manager.windows[0].view.appearance == DEFAULTS


def test_existing_speaker_color_migrates_to_user_messages(manager_factory, tmp_path):
    path = tmp_path / "legacy-appearance.json"
    path.write_text(json.dumps({"version": 1, "windows": [{"kind": "chat", "chat": {"appearance": {
        "background": "#ffffff", "text": "#112233", "labels": "#663300", "font_size": 16}}}]}))
    manager = manager_factory(path=path)
    view = manager.windows[0].view
    assert view.appearance["user_text"] == "#663300"
    assert view.appearance["text"] == "#112233"
    assert view.appearance["font_size"] == 16
    choose(manager.windows[0], 0)
    assert view.transcript.tag_cget("user", "foreground") == "#663300"
    assert view.editor.cget("foreground") == "#663300"
    manager.save_layout()
    saved = json.loads(path.read_text())["windows"][0]["chat"]["appearance"]
    assert saved["user_text"] == "#663300" and "labels" not in saved


def test_saved_footer_is_hidden_but_save_failures_remain_visible(manager_factory, monkeypatch):
    manager = manager_factory()
    window = manager.windows[0]
    manager.save_layout()
    window.root.update()
    assert not window.notice_label.winfo_ismapped()
    height = window.view.transcript.winfo_height()
    with monkeypatch.context() as patch:
        def fail(*_):
            raise OSError("Synthetic save failure")
        patch.setattr("wow_helper.workspace.write_json", fail)
        assert not manager.save_layout()
        window.root.update()
        assert window.notice_label.winfo_ismapped()
        assert "Could not save" in window.notice.get()
        assert window.view.transcript.winfo_height() < height
    assert manager.save_layout()
    window.root.update()
    assert not window.notice_label.winfo_ismapped()
    assert window.view.transcript.winfo_height() == height


def test_appearance_dialog_and_largest_text_fit_at_minimum_size(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    window.chrome.place("440x580+100+100")
    window.options_menu.invoke(window.appearance_menu_index)
    dialog = window.view._appearance_dialog
    dialog.chrome.place("440x480+100+100")
    dialog.variables["font_size"].set(36)
    dialog.root.update()
    bottom = dialog.root.winfo_rooty() + dialog.root.winfo_height()
    assert dialog.preview.winfo_height() >= 50
    assert dialog.save_button.winfo_ismapped()
    assert dialog.save_button.winfo_rooty() + dialog.save_button.winfo_height() < bottom
    dialog.save_button.invoke()
    window.root.update()
    view = window.view
    assert view.transcript.winfo_height() >= 80
    assert view.send_button.winfo_ismapped()
    assert view.send_button.winfo_rooty() + view.send_button.winfo_height() < window.root.winfo_rooty() + window.root.winfo_height()


def test_window_menu_recovers_minimized_window(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    second = manager.new_window(first)
    second.root.iconify()
    first.root.update()
    first.windows_menu.invoke(1)
    first.root.update()
    assert second.root.state() == "normal"


class Access:
    api = True
    available = True
    shortcut = "Ctrl+Alt+H"
    hotkey = "H"
    restart_handle = True
    restart_pending = False
    pending = False
    closed = False

    def requested(self):
        result, self.pending = self.pending, False
        return result

    def restart_requested(self):
        result, self.restart_pending = self.restart_pending, False
        return result

    def close(self):
        self.closed = True


def test_hide_and_reopen_keep_all_windows_sessions_and_drafts(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    second = new_chat(manager, first)
    choose(first, 0)
    choose(second, 1)
    first.view.editor.insert("1.0", "Keep the first draft")
    second.view.editor.insert("1.0", "Keep the second draft")
    access = Access()
    manager.enable_reopening(access)
    first.root.update()
    before = [window.snapshot() for window in manager.windows]
    first.options_menu.invoke(first.hide_menu_index)
    first.root.update()
    assert not manager.closed
    assert all(window.root.state() == "withdrawn" for window in manager.windows)
    access.pending = True
    manager._check_reopen()
    first.root.update()
    assert all(window.root.state() == "normal" for window in manager.windows)
    assert [window.snapshot() for window in manager.windows] == before
    assert all(window.view.service.sent == [] for window in manager.windows)
    callback = manager._access_after
    manager.close()
    assert access.closed
    assert callback not in first.root.tk.call("after", "info")


def test_last_close_hides_with_shortcut_and_full_quit_preserves_restart(manager_factory):
    manager = manager_factory()
    access = Access()
    manager.enable_reopening(access)
    window = manager.windows[0]
    window.view.editor.insert("1.0", "Do not lose this draft")
    manager.close_window(window)
    assert not manager.closed and not window.closed
    assert window.root.state() == "withdrawn"
    manager.show_all()
    window.root.update()
    assert window.view.editor.get("1.0", "end-1c") == "Do not lose this draft"
    manager.close()
    assert manager.closed and access.closed
    restored = manager_factory()
    assert restored.windows[0].view.editor.get("1.0", "end-1c") == "Do not lose this draft"


def test_restart_request_saves_all_windows_and_drafts(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    second = new_chat(manager, first)
    choose(first, 0)
    choose(second, 1)
    first.view.editor.insert("1.0", "First retained draft")
    second.view.editor.insert("1.0", "Second retained draft")
    access = Access()
    manager.enable_reopening(access)
    before = [w.snapshot() for w in manager.windows]
    access.restart_pending = True
    manager._check_reopen()
    assert manager.closed and access.closed
    restored = manager_factory()
    assert [w.snapshot() for w in restored.windows] == before
    assert all(w.view.service.sent == [] for w in restored.windows)


def test_restart_menu_launches_once_and_waits_for_graceful_exit(manager_factory, monkeypatch):
    from types import SimpleNamespace
    from wow_helper import workspace
    calls = []
    monkeypatch.setattr(workspace, "start_restart", lambda hotkey: calls.append(hotkey) or SimpleNamespace(poll=lambda: None))
    manager = manager_factory()
    access = Access()
    manager.enable_reopening(access)
    window = manager.windows[0]
    window.options_menu.invoke(window.restart_menu_index)
    manager.restart()
    assert calls == ["H"]
    assert not manager.closed
    assert window.options_menu.entrycget(window.restart_menu_index, "state") == "disabled"
    access.restart_pending = True
    manager._check_reopen()
    assert manager.closed


@pytest.mark.parametrize("spawn_error", [True, False])
def test_restart_launcher_failure_keeps_current_windows_usable(manager_factory, monkeypatch, spawn_error):
    from types import SimpleNamespace
    from wow_helper import workspace
    def fail(_):
        if spawn_error:
            raise OSError("Synthetic launch failure")
        return SimpleNamespace(poll=lambda: 2)
    monkeypatch.setattr(workspace, "start_restart", fail)
    manager = manager_factory()
    manager.enable_reopening(Access())
    manager.restart()
    manager._check_reopen()
    assert not manager.closed
    window = manager.windows[0]
    assert window.root.state() == "normal"
    assert window.options_menu.entrycget(window.restart_menu_index, "state") == "normal"
    assert "restart" in window.notice.get().lower()


def test_unavailable_shortcut_cannot_leave_last_window_hidden(manager_factory):
    manager = manager_factory()
    access = Access()
    access.available = False
    manager.enable_reopening(access)
    window = manager.windows[0]
    assert "unavailable" in window.notice.get()
    assert window.options_menu.entrycget(window.hide_menu_index, "state") == "disabled"
    manager.hide_all()
    assert window.root.state() == "normal"
    manager.close_window(window)
    assert manager.closed and access.closed


def test_failed_save_keeps_windows_visible_and_shortcut_registered(manager_factory, monkeypatch):
    from wow_helper import workspace
    manager = manager_factory()
    access = Access()
    manager.enable_reopening(access)
    window = manager.windows[0]
    def fail(*_):
        raise OSError("Synthetic storage failure")
    with monkeypatch.context() as patch:
        patch.setattr(workspace, "write_json", fail)
        patch.setattr(workspace, "start_restart", lambda _: pytest.fail("Restart started despite a save failure"))
        manager.hide_all()
        manager.close_window(window)
        manager.close()
        manager.restart()
        window.root.withdraw()
        access.restart_pending = True
        manager._check_reopen()
        assert not manager.closed and not access.closed
        assert window.root.state() == "normal"


def test_negative_coordinates_and_removed_monitor_recovery():
    areas = [(0, 0, 1920, 1040), (-1440, -200, 0, 2300)]
    raw = {"width": 620, "height": 700, "x": -1200, "y": -100}
    assert window_bounds(raw, areas) == raw
    recovered = window_bounds(raw, areas[:1])
    assert recovered["x"] >= 0 and recovered["y"] >= 0
    assert recovered["width"] == raw["width"]
    malformed = window_bounds({"width": None, "height": -1, "x": True, "y": []}, areas)
    assert malformed["width"] >= MIN_WIDTH and malformed["height"] >= MIN_HEIGHT


def test_malformed_state_starts_one_usable_window(manager_factory, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"version":1,"windows":[null,{"kind":[]},42]}')
    manager = manager_factory(path)
    assert len(manager.windows) == 1 and manager.windows[0].kind == "chat"


def test_duplicate_window_ids_are_repaired(manager_factory, tmp_path):
    path = tmp_path / "duplicates.json"
    record = {"id": str(uuid.UUID(int=9)), "number": 1, "kind": "chooser"}
    path.write_text(json.dumps({"version": 1, "windows": [record, record]}))
    manager = manager_factory(path)
    assert len({w.id for w in manager.windows}) == 2
    assert len({w.number for w in manager.windows}) == 2


def test_layout_lock_refuses_second_writer_and_releases_on_close(tmp_path):
    first = LayoutLock(tmp_path / "windows.json")
    try:
        with pytest.raises(ChatError, match="already open"):
            LayoutLock(tmp_path / "windows.json")
    finally:
        first.close()
    next_lock = LayoutLock(tmp_path / "windows.json")
    next_lock.close()


def test_save_failure_does_not_expose_paths_or_stop_other_windows(manager_factory, monkeypatch):
    manager = manager_factory()
    window = manager.windows[0]
    previous = manager.layout_path.read_bytes() if manager.layout_path.exists() else None

    def fail(*_):
        raise OSError("Synthetic private detail")

    monkeypatch.setattr("wow_helper.workspace.write_json", fail)
    manager.save_layout()
    assert "Could not save" in window.notice.get()
    assert "private detail" not in window.notice.get()
    assert manager.new_window(window) is not None
    manager.close()
    assert not manager.closed
    if previous:
        assert manager.layout_path.read_bytes() == previous


def test_chooser_offers_all_five_working_types_at_minimum_size(manager_factory):
    manager = manager_factory()
    chooser = manager.new_window(manager.windows[0])
    chooser.root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}")
    chooser.root.update()
    assert set(chooser.type_buttons) == set(TYPES)
    for button in chooser.type_buttons.values():
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() < chooser.root.winfo_rooty() + MIN_HEIGHT
    chooser.type_buttons["quests"].invoke()
    settle(chooser.view)
    assert chooser.kind == "quests" and chooser.view.book.index("current") == 0
    assert chooser.view.service.sent == []


@pytest.mark.parametrize("kind", ["quests", "character"])
def test_report_windows_work_without_agent_and_do_not_repeat_preparation_on_restore(manager_factory, tmp_path, kind):
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(activity=lambda: activity)
    window = manager.new_window(kind=kind)
    settle(window.view)
    assert activity.calls == [([kind], "_classic_beta_")]
    window.view.report_button.invoke()
    settle(window.view)
    text = (" ".join(window.view.quest_tree.tree.item(k, "text") for k in window.view.quest_tree.quests)
            if kind == "quests" else window.view.report_text.get("1.0", "end"))
    assert ("Synthetic" if kind == "quests" else "12g 34s 56c") in text
    assert activity.calls == [([kind], "_classic_beta_")] * 2
    assert window.view.service.sent == []
    manager.close()
    restored = manager_factory(activity=lambda: activity)
    assert restored.windows[1].kind == kind
    assert activity.calls == [([kind], "_classic_beta_")] * 2
    assert restored.windows[1].view.service.sent == []


def open_synthetic_quest_chat(view, key=None):
    settle(view)
    key = key or next(iter(view.quest_tree.quests))
    view.quest_tree.tree.focus(key)
    view.quest_tree.tree.selection_set(key)
    view.quest_chat_button.invoke()
    child = view.active_quest_chat()
    assert child is not None
    settle(child)
    return key, child


def test_quest_chat_carries_only_selected_quest_and_gathered_sources(manager_factory, tmp_path):
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(service=CreatingService, activity=lambda: activity)
    window = manager.new_window(kind="quests")
    view = window.view
    settle(view)
    choose(window, 1)  # Match the explicitly selected Claude provider, using a new conversation.
    view.editor.insert("1.0", "Keep the general chat draft")
    key = next(iter(view.quest_tree.quests))
    view.quest_tree.set_guide(key, {"status": "completed", "tier": "easy", "session": "private-worker-id",
                                   "guide": {"summary": "Synthetic directions", "steps": ["Go to Example Village"],
                                             "sources": [{"title": "Synthetic source", "url": "https://example.com/quest"}],
                                             "caveats": ["Beta details unverified"]}})
    _, child = open_synthetic_quest_chat(view, key)
    assert len(child.service.created) == len(child.service.sent) == 1
    assert child.selected.provider == "claude" and child.selected.key != view.selected.key
    assert view.service.sent == [] and view.editor.get("1.0", "end-1c") == "Keep the general chat draft"
    session, options = child.service.created[0]
    packet = json.loads((tmp_path / "prepared" / (session.id + ".json")).read_text(encoding="utf-8"))
    context = packet["reports"]["quest_context"]["data"]
    assert context["quest"] == view.quest_tree.quests[key]
    assert context["edition"] == "Classic Forever beta" and context["snapshot_at"] == 1000
    assert context["research"]["guide"]["sources"][0]["url"] == "https://example.com/quest"
    assert "session" not in context["research"] and "quest" in options["startup"].lower()
    assert list(packet["reports"]) == ["quest_context"]
    assert packet["skills"] and "historical" in packet["instructions"]
    assert activity.calls == [(["quests"], "_classic_beta_"), ([], "_classic_beta_")]
    assert not view.selector.winfo_ismapped() and child.selector.winfo_ismapped()
    assert not child.session_picker.winfo_ismapped()
    # Reopening, even after progress changes, neither duplicates the tab nor sends again.
    view.quest_tree.quests[key]["remaining"] = ["Updated synthetic progress"]
    view.book.select(0)
    view.open_quest_chat()
    assert view.active_quest_chat() is child and len(view.quest_chats) == 1
    assert len(child.service.sent) == 1


def test_quest_chat_uses_the_displayed_snapshot_edition_after_setup_changes(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind="quests").view
    settle(view)
    view.profile["flavor"] = "_retail_"  # Setup changed, but the report has not refreshed yet.
    view.profile["startup_context"] = False
    _, child = open_synthetic_quest_chat(view)
    assert child.context["edition"] == "Classic Forever beta"
    packet = json.loads((view.activity.storage / "prepared" / (child.selected.id + ".json")).read_text(encoding="utf-8"))
    assert packet["edition"] == "Classic Forever beta"
    assert packet["skills"] == [] and packet["context_files"] == []
    assert packet["reports"]["quest_context"]["data"]["quest"] == child.context["quest"]


def test_quest_tabs_restore_drafts_waits_and_context_without_dispatch(manager_factory, tmp_path):
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind="quests").view
    key, child = open_synthetic_quest_chat(view)
    child.editor.insert("1.0", "Quest follow-up draft")
    saved_key, saved_context = child.selection_key, child.context
    assert manager.save_layout()
    layout = json.loads((tmp_path / "windows.json").read_text())
    tab_id = layout["windows"][1]["chat"]["activity"]["quest_chats"][0]
    assert isinstance(tab_id, str)  # Large history lives in a separate private file.
    manager.close()
    restored = manager_factory(service=CreatingService)
    loaded = restored.windows[1].view
    chat = loaded.quest_chats[tab_id]
    settle(chat)
    assert loaded.active_quest_chat() is chat
    assert chat.selection_key == saved_key and chat.context == saved_context
    assert chat.editor.get("1.0", "end-1c") == "Quest follow-up draft"
    assert chat.response_waits[saved_key]
    assert chat.service.created == [] and chat.service.sent == []
    assert not loaded.service.sent
    restored.windows[1].remember.set(False)
    assert restored.save_layout()
    state = json.loads(loaded._quest_chat_path(tab_id).read_text(encoding="utf-8"))
    assert "draft" not in state and "response_waits" not in state and "messages" not in state
    assert state["context"] == saved_context


def test_quest_tab_close_is_independent_and_context_survives_research_failure(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind="quests").view
    settle(view)
    view.open_quest_chat()
    assert "Select a quest" in view.activity_notice.get()
    keys = list(view.quest_tree.quests)
    view.quest_tree.set_guide(keys[0], {"status": "failed", "tier": "complicated"})
    _, first = open_synthetic_quest_chat(view, keys[0])
    view.book.select(0)
    _, second = open_synthetic_quest_chat(view, keys[1])
    assert first.service is not second.service
    assert first.context["research"]["status"] == "failed"
    assert first.context["quest"]["id"] != second.context["quest"]["id"]
    second.editor.insert("1.0", "Second quest draft")
    view.book.select(first.root)
    view.outer.update()
    first.close_tab_button.invoke()
    first.worker.shutdown(wait=True)
    assert first.closed and first.service.closed
    assert len(view.quest_chats) == 1 and not second.closed and not view.service.closed
    assert second.editor.get("1.0", "end-1c") == "Second quest draft"
    assert not first.selector.winfo_exists()
    manager.close()
    assert second.closed


def test_failed_quest_tab_save_keeps_the_previous_layout(manager_factory, tmp_path, monkeypatch):
    from wow_helper import task_window
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind="quests").view
    _, child = open_synthetic_quest_chat(view)
    assert manager.save_layout()
    before = (tmp_path / "windows.json").read_bytes()
    child.editor.insert("1.0", "Unsaved follow-up")
    def fail(*_): raise OSError("Synthetic disk full")
    monkeypatch.setattr(task_window, "write_json", fail)
    assert not manager.save_layout()
    assert (tmp_path / "windows.json").read_bytes() == before
    assert "Could not save" in manager.windows[1].notice.get()
    assert not child.closed


def test_quest_creation_failure_stays_in_the_new_tab_and_can_be_retried(manager_factory):
    class Missing(CreatingService):
        def create(self, *args, **kwargs): raise ChatError("Synthetic CLI unavailable")
    manager = manager_factory(service=Missing)
    view = manager.new_window(kind="quests").view
    _, child = open_synthetic_quest_chat(view)
    assert "CLI unavailable" in child.status.get()
    assert child.service.sent == [] and child.context["quest"]
    assert not child.pending_creation and not child.selected
    child.service.create = lambda *args, **kwargs: CreatingService.create(child.service, *args, **kwargs)
    child.editor.insert("1.0", "Retry with the saved quest context")
    child.send()
    settle(child)
    assert len(child.service.created) == len(child.service.sent) == 1


def test_closed_quest_tab_during_creation_does_not_send_later(manager_factory):
    gate = threading.Event()
    class Slow(CreatingService):
        def create(self, *args, **kwargs):
            if not gate.wait(4): raise ChatError("Synthetic timeout")
            return super().create(*args, **kwargs)
    manager = manager_factory(service=Slow)
    view = manager.new_window(kind="quests").view
    settle(view)
    view.quest_tree.tree.focus(next(iter(view.quest_tree.quests)))
    view.open_quest_chat()
    child = view.active_quest_chat()
    deadline = time.monotonic() + 3
    try:
        while not child.pending_creation and time.monotonic() < deadline:
            child.root.update()
            time.sleep(.01)
        assert child.pending_creation
        child.close_tab_button.invoke()
    finally:
        gate.set()
        child.worker.shutdown(wait=True)
    assert not child.service.sent and not view.quest_chats and child.closed


def test_unreadable_saved_quest_context_keeps_its_file_and_other_tabs(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind="quests").view
    _, child = open_synthetic_quest_chat(view)
    tab_id = next(iter(view.quest_chats))
    manager.close()
    path = view._quest_chat_path(tab_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["context"]["edition"] = []  # Malformed local data must not crash the workspace.
    path.write_text(json.dumps(state), encoding="utf-8")
    restored = manager_factory(service=CreatingService)
    restored_view = restored.windows[1].view
    assert not restored_view.quest_chats and len(restored_view.book.tabs()) == 2
    assert "could not be loaded" in restored_view.activity_notice.get() and path.exists()


def test_quest_tab_limit_keeps_existing_conversations_and_all_tabs_accessible(manager_factory):
    from wow_helper.quest_chat import MAX_QUEST_CHATS
    manager = manager_factory(service=CreatingService)
    window = manager.new_window(kind="quests")
    window.root.geometry("440x580")
    view = window.view
    settle(view)
    keys = list(view.quest_tree.quests)
    for key in keys[:MAX_QUEST_CHATS]:
        open_synthetic_quest_chat(view, key)
    assert len(view.quest_chats) == MAX_QUEST_CHATS
    view.book.select(0)
    view.quest_tree.tree.focus(keys[MAX_QUEST_CHATS])
    view.quest_chat_button.invoke()
    assert "Four quest chats" in view.activity_notice.get()
    assert len(view.quest_chats) == MAX_QUEST_CHATS
    # Every tab must have a clickable position at the minimum window width.
    view.outer.update()
    visible = set()
    for x in range(view.book.winfo_width()):
        try:
            visible.add(view.book.index(f"@{x},10"))
        except view.tk.TclError:
            pass
    assert visible == set(range(MAX_QUEST_CHATS + 2))


def test_response_completed_during_restart_is_observed_without_resending(manager_factory):
    receipt = {"status": "running"}
    class Receipts(Service):
        def response_status(self, *_): return receipt["status"]
    manager = manager_factory(service=Receipts)
    window = manager.windows[0]
    choose(window, 0)
    window.view.send_message("Synthetic restart question")
    settle(window.view)
    assert window.view.response_waits[window.view.selection_key]
    manager.close()
    receipt["status"] = "completed"
    restored = manager_factory(service=Receipts)
    view = restored.windows[0].view
    assert not view.service.sent and not view.response_waits[view.selection_key]
    assert "Response complete" in view.status.get()


def test_setup_preview_and_delivery_preserve_the_chat_draft_and_do_not_replay(manager_factory, tmp_path):
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(activity=lambda: activity)
    window = manager.new_window(kind="quests")
    settle(window.view)
    choose(window, 0)
    view = window.view
    view.editor.insert("1.0", "Keep this unrelated draft")
    view.show_setup()
    dialog = view._setup_dialog
    dialog.fields["opening"].delete("1.0", "end")
    dialog.fields["opening"].insert("1.0", "Explain the first suggested quest.")
    dialog.save()
    assert view.service.sent == [] and activity.calls == [(["quests"], "_classic_beta_")]
    view.prepare_request()
    settle(view)
    request = view._request_dialog
    assert request is not None
    assert "Explain the first suggested quest." in request.preview.get("1.0", "end")
    assert view.service.sent == []
    request.send()
    request.send()  # a repeated callback cannot send the same prepared request twice
    settle(view)
    assert len(view.service.sent) == 1
    assert view.service.sent[0][0] == SESSIONS[0].key
    assert view.editor.get("1.0", "end-1c") == "Keep this unrelated draft"
    packet = json.loads(next((tmp_path / "prepared").glob("*.json")).read_text())
    assert packet["task"] == "Explain the first suggested quest."
    assert packet["reports"]["quests"]["data"]["quest_count"] == 6
    manager.close()
    restored = manager_factory(activity=lambda: activity)
    view = restored.windows[1].view
    assert view.service.sent == []
    assert len(activity.calls) == 2
    assert view.profile["opening"] == packet["task"]
    assert view.editor.get("1.0", "end-1c") == "Keep this unrelated draft"


def test_prepared_request_cannot_silently_follow_a_changed_session(manager_factory, tmp_path):
    manager = manager_factory(activity=lambda: SyntheticActivities(tmp_path))
    window = manager.windows[0]
    choose(window, 0)
    window.view.prepare_request()
    settle(window.view)
    request = window.view._request_dialog
    choose(window, 1)
    request.send()
    assert "session changed" in request.notice.get()
    assert window.view.service.sent == []


def test_saved_preset_reopens_setup_and_creates_a_window_without_session_data(manager_factory, tmp_path, monkeypatch):
    from tkinter import filedialog, simpledialog
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(activity=lambda: activity)
    window = manager.new_window(kind="quests")
    settle(window.view)
    choose(window, 0)
    view = window.view
    view.profile["instructions"] = "Synthetic saved instructions"
    monkeypatch.setattr(simpledialog, "askstring", lambda *args, **kwargs: "Example preset")
    view.save_preset()
    path = next((tmp_path / "presets").glob("*.json"))
    data = json.loads(path.read_text())
    assert set(data) == {"version", "name", "kind", "profile"}
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kwargs: str(path))
    view.show_setup()
    previous = view._setup_dialog
    previous.fields["instructions"].insert("end", " Unsaved change")
    view.load_preset()
    assert view._setup_dialog is not previous
    assert view._setup_dialog.fields["instructions"].get("1.0", "end-1c") == "Synthetic saved instructions"
    chooser = manager.new_window(window)
    chooser.open_preset()
    settle(chooser.view)
    assert chooser.kind == "quests" and chooser.view.profile == view.profile
    assert chooser.view.selection_key is None
    assert chooser.view.service.sent == [] and view.service.sent == []
    assert activity.calls == [(["quests"], "_classic_beta_")] * 2


def test_failed_preparation_does_not_send_and_setup_cancel_does_not_change_profile(manager_factory, tmp_path):
    class Broken(SyntheticActivities):
        def reports(self, *_):
            raise ChatError("Synthetic snapshot unavailable")
    manager = manager_factory(activity=lambda: Broken(tmp_path))
    window = manager.new_window(kind="quests")
    settle(window.view)
    choose(window, 0)
    before = dict(window.view.profile)
    window.view.show_setup()
    dialog = window.view._setup_dialog
    dialog.fields["opening"].insert("end", " Should not save")
    dialog.close()
    assert window.view.profile == before
    window.view.prepare_request()
    settle(window.view)
    assert window.view._request_dialog is None
    assert "unavailable" in window.view.activity_notice.get()
    assert window.view.service.sent == []


def test_setup_tabs_keep_controls_visible_at_minimum_size(manager_factory):
    window = manager_factory().windows[0]
    window.view.show_setup()
    dialog = window.view._setup_dialog
    dialog.root.geometry("460x480")
    for index in range(4):
        dialog.book.select(index)
        dialog.root.update()
        assert dialog.save_button.winfo_ismapped()
        assert dialog.save_button.winfo_rooty() + dialog.save_button.winfo_height() < dialog.root.winfo_rooty() + 480
        if index >= 2:
            key = "context_files" if index == 2 else "skill_files"
            box = dialog.file_lists[key]
            assert box.winfo_ismapped() and box.winfo_height() >= 20
            for button in dialog.file_buttons[key]:
                assert button.winfo_ismapped()
                assert button.winfo_rooty() + button.winfo_height() < dialog.save_button.winfo_rooty()


def test_first_message_creates_one_session_and_preserves_text_typed_during_startup(manager_factory, tmp_path):
    activity = SyntheticActivities(tmp_path)
    gate = threading.Event()
    class Slow(CreatingService):
        def create(self, *args, **kwargs):
            if not gate.wait(3): raise RuntimeError("Synthetic timeout")
            return super().create(*args, **kwargs)
    manager = manager_factory(service=Slow, activity=lambda: activity)
    view = manager.windows[0].view
    view.editor.insert("1.0", "First request")
    try:
        view.send()
        view.send()
        view.editor.insert("end", " plus an unsent thought")
        assert view.pending_creation and not view.service.sent
    finally:
        gate.set()
    settle(view)
    assert len(view.service.created) == len(view.service.sent) == 1
    assert view.service.sent[0][1] == "First request"
    assert view.editor.get("1.0", "end-1c") == "First request plus an unsent thought"
    assert view.selected.managed and view.selected.provider == "codex"
    assert view.pending_creation is None


def test_provider_buttons_prepare_new_chats_and_startup_settings_are_respected(manager_factory, tmp_path):
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(service=CreatingService, activity=lambda: activity)
    window = manager.new_window(kind="quests")
    view = window.view
    settle(view)
    view.show_setup()
    setup = view._setup_dialog
    setup.startup["startup_opening"].set(False)
    setup.save()
    view.provider_buttons["claude"].invoke()
    settle(view)
    assert view.selected.provider == "claude" and view.selected.managed
    assert view.service.sent == []
    assert activity.calls == [(["quests"], "_classic_beta_")] * 2
    packets = [json.loads(p.read_text()) for p in (tmp_path / "prepared").glob("*.json")]
    assert packets[0]["task"] == "Use this context to answer the user's message."
    assert packets[0]["skills"] and packets[0]["reports"]["quests"]
    assert view.actions_menu.entrycget(view.setup_menu_index, "state") == "disabled"
    manager.close()
    restored = manager_factory(service=CreatingService, activity=lambda: activity)
    assert restored.windows[1].view.profile["startup_opening"] is False
    assert len(activity.calls) == 2 and restored.windows[1].view.service.created == []


def test_failed_new_session_keeps_draft_and_never_sends(manager_factory, tmp_path):
    class Broken(CreatingService):
        def create(self, *args, **kwargs): raise ChatError("Synthetic CLI unavailable")
    manager = manager_factory(service=Broken, activity=lambda: SyntheticActivities(tmp_path))
    view = manager.windows[0].view
    view.editor.insert("1.0", "Keep my first message")
    view.send()
    settle(view)
    assert "CLI unavailable" in view.status.get()
    assert view.editor.get("1.0", "end-1c") == "Keep my first message"
    assert view.service.sent == [] and view.selected is None


def test_selection_change_during_creation_prevents_unintended_send(manager_factory, tmp_path):
    gate = threading.Event()
    class Slow(CreatingService):
        def create(self, *args, **kwargs):
            if not gate.wait(3): raise RuntimeError("Synthetic timeout")
            return super().create(*args, **kwargs)
    manager = manager_factory(service=Slow, activity=lambda: SyntheticActivities(tmp_path))
    view = manager.windows[0].view
    view.editor.insert("1.0", "For the new chat only")
    try:
        view.send()
        view.session_picker.current(1)
        view.select()
    finally:
        gate.set()
    settle(view)
    assert view.selected.key == SESSIONS[1].key
    assert view.service.sent == [] and len(view.service.created) == 1


def test_restart_during_creation_keeps_draft_but_never_resends(manager_factory, tmp_path):
    gate = threading.Event()
    class Slow(CreatingService):
        def create(self, *args, **kwargs):
            if not gate.wait(3): raise RuntimeError("Synthetic timeout")
            return super().create(*args, **kwargs)
    manager = manager_factory(service=Slow, activity=lambda: SyntheticActivities(tmp_path))
    view = manager.windows[0].view
    view.editor.insert("1.0", "Preserve across startup interruption")
    view.send()
    try:
        manager.close()
    finally:
        gate.set()
    view.worker.shutdown(wait=True)
    restored = manager_factory(service=CreatingService, activity=lambda: SyntheticActivities(tmp_path))
    after = restored.windows[0].view
    assert after.editor.get("1.0", "end-1c") == "Preserve across startup interruption"
    assert len(view.service.created) == 1 and view.service.sent == []
    assert after.service.created == [] and after.service.sent == []


def test_screen_ask_creates_a_session_and_sends_without_file_picker_or_preview(manager_factory, tmp_path):
    from PIL import Image
    from wow_helper.screen_capture import import_image
    source = tmp_path / "synthetic.png"
    Image.new("RGB", (80, 60), "gold").save(source)
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(service=CreatingService, activity=lambda: activity)
    view = manager.new_window(kind="screen").view
    settle(view)
    view.ask_button.invoke()
    assert not view.service.created and "image first" in view.activity_notice.get()
    view._image_result(import_image(tmp_path, source), None)
    view.ask_button.invoke()
    settle(view)
    assert len(view.service.created) == len(view.service.sent) == 1
    assert view._request_dialog is None and view.book.index("current") == 1


def test_quest_tree_expansion_requests_one_guide_and_preserves_manual_collapse(manager_factory, tmp_path):
    class Research:
        def __init__(self): self.calls = []
        def request(self, *args, **kwargs): self.calls.append((args, kwargs)); return "a" * 64
        def poll(self): pass
        def get(self, key): return {"status": "running", "tier": "easy"}
    manager = manager_factory(activity=lambda: SyntheticActivities(tmp_path))
    view = manager.new_window(kind="quests").view
    settle(view)
    view._guidance = research = Research()
    tree = view.quest_tree
    key = next(iter(tree.quests))
    tree.tree.focus(key)
    tree.tree.item(key, open=True)
    tree.tree.event_generate("<<TreeviewOpen>>")
    view.on_tick()
    settle(view)
    tree.tree.event_generate("<<TreeviewOpen>>")
    view.on_tick()
    settle(view)
    assert len(research.calls) == 1
    assert research.calls[0][0][0] == "quest" and research.calls[0][0][2] == "Classic Forever beta"
    assert tree.open_ids() == [key]
    tree.tree.item(key, open=False)
    tree.tree.event_generate("<<TreeviewClose>>")
    view.refresh_panel()
    settle(view)
    assert tree.open_ids() == [] and len(research.calls) == 1
    view.guide_auto.set(False)
    view._guide_settings()
    other = list(tree.quests)[1]
    tree.tree.focus(other)
    tree.tree.event_generate("<<TreeviewOpen>>")
    view.on_tick()
    settle(view)
    assert len(research.calls) == 1


def test_find_gear_uses_fresh_snapshot_selected_slot_and_build(manager_factory, tmp_path):
    class Research:
        def request(self, *args, **kwargs): self.args = args; return "b" * 64
        def poll(self): pass
        def get(self, key): return {"status": "running"}
    activity = SyntheticActivities(tmp_path)
    manager = manager_factory(activity=lambda: activity)
    view = manager.new_window(kind="character").view
    settle(view)
    view._guidance = research = Research()
    view.gear_slot.set("chest")
    view.gear_goal.set("Tanking")
    view.find_gear()
    settle(view)
    kind, context, edition, tier, provider = research.args
    assert kind == "gear" and tier == "complicated" and provider == "codex"
    assert context["slot"] == "chest" and context["build_or_goal"] == "Tanking"
    assert context["character"]["player"]["class"] == "WARRIOR"
    assert context["character"]["gear"] and "age_seconds" not in context["character"]
    assert activity.calls == [(["character"], "_classic_beta_")] * 2
    assert view.service.sent == []


def test_journal_keeps_notes_and_unsent_note_across_restart_without_chat_retention(manager_factory):
    manager = manager_factory()
    window = manager.new_window(kind="journal")
    settle(window.view)
    window.remember.set(False)
    window.view.note.insert("1.0", "Synthetic session goal")
    window.view.note_button.invoke()
    settle(window.view)
    assert "Synthetic session goal" in window.view.report_text.get("1.0", "end")
    assert window.view.note.get("1.0", "end-1c") == ""
    window.view.note.insert("1.0", "Unfinished note")
    key = window.view.journal_id
    manager.close()
    restored = manager_factory()
    view = restored.windows[1].view
    assert view.journal_id == key
    assert "Synthetic session goal" in view.report_text.get("1.0", "end")
    assert view.note.get("1.0", "end-1c") == "Unfinished note"
    assert view.service.sent == []


def test_journal_save_finishing_after_close_does_not_duplicate_the_note(manager_factory, tmp_path):
    gate = threading.Event()
    class Slow(ActivityService):
        def add_note(self, *args):
            assert gate.wait(5)
            return super().add_note(*args)
    manager = manager_factory(activity=lambda: Slow(tmp_path))
    window = manager.new_window(kind="journal")
    settle(window.view)
    window.view.note.insert("1.0", "Save once, even across closing")
    window.view.add_note()
    try:
        manager.close()
    finally:
        gate.set()
        window.view.worker.shutdown(wait=True)
    restored = manager_factory(activity=lambda: Slow(tmp_path))
    view = restored.windows[1].view
    assert view.note.get("1.0", "end-1c") == ""
    assert len(view.activity.journal(view.journal_id)["entries"]) == 1
    assert view.pending_note is None


def test_screen_window_previews_a_managed_image_and_only_sends_after_review(manager_factory, tmp_path):
    from PIL import Image
    from wow_helper.screen_capture import import_image
    manager = manager_factory()
    window = manager.new_window(kind="screen")
    settle(window.view)
    source = tmp_path / "synthetic-scene.png"
    Image.new("RGB", (640, 360), "#224466").save(source)
    view = window.view
    name = import_image(view.activity.storage, source)
    view._image_result(name, None)
    window.root.update()
    assert view._preview_image is not None
    assert view.service.sent == []
    choose(window, 1)
    view.prepare_request()
    settle(view)
    assert view._request_dialog.packet["image"].endswith(name)
    view._request_dialog.send()
    settle(view)
    assert len(view.service.sent) == 1 and view.service.sent[0][0] == SESSIONS[1].key


def test_pinned_advice_freezes_and_restores_without_sending(manager_factory, tmp_path):
    manager = manager_factory()
    source = manager.windows[0]
    choose(source, 0)
    source.remember.set(False)
    source.view.editor.insert('1.0', 'Keep my unsent draft')
    source.view.pin_to_play()
    dialog = source.view._pin_dialog
    dialog.objective.set('Reach the example camp')
    dialog.next_step.set('Follow the eastern road')
    choose(source, 1)
    dialog.save()
    card = manager.windows[-1]
    assert card.kind == 'play' and card.mode == 'play'
    assert card.pin['source']['session_id'] == SESSIONS[0].id
    assert card.pin['text'] == SESSIONS[0].title
    assert card.root.minsize() == (340, 300)
    choose(source, 0)
    assert source.view.editor.get('1.0', 'end-1c') == 'Keep my unsent draft'
    card.root.geometry('360x320+80+90'); card.root.update()
    card.toggle_play()
    assert card.mode == 'desk' and card.root.minsize() == (440, 580)
    assert SESSIONS[0].title in card.card.text.get('1.0', 'end-1c')
    card.root.geometry('650x720+90+100'); card.root.update()
    card.toggle_play(); card.root.update()
    assert card.capture_bounds()['width'] == 360
    assert card.card.open_source() is source.view
    assert not source.view.service.sent
    frozen = dict(card.pin)
    manager.close()
    restored = manager_factory()
    card = restored.windows[-1]
    assert card.pin == frozen and card.mode == 'play'
    assert card.capture_bounds()['width'] == 360
    card.toggle_play(); card.root.update()
    assert card.capture_bounds()['width'] == 650
    assert not any(w.view.service.sent for w in restored.windows if w.view)


def test_pin_failure_preserves_review_and_window_limit(manager_factory, monkeypatch):
    manager = manager_factory()
    source = manager.windows[0]
    choose(source, 0)
    source.view.pin_to_play()
    dialog = source.view._pin_dialog
    dialog.objective.set('Example objective')
    dialog.next_step.set('Example step')
    monkeypatch.setattr(manager, 'save_layout', lambda: False)
    dialog.save()
    assert len(manager.windows) == 1 and source.view._pin_dialog is dialog
    assert 'save' in dialog.notice.get().lower()
    while len(manager.windows) < MAX_WINDOWS:
        manager.new_window()
    dialog.save()
    assert len(manager.windows) == MAX_WINDOWS
    assert 'Eight' in dialog.notice.get()
    assert dialog.next_step.get() == 'Example step'


def test_pin_missing_source_stays_readable(manager_factory):
    manager = manager_factory()
    pin = {'text':'Saved synthetic advice', 'evidence':{'gaps':['Source time unknown.']}}
    card = manager.pin_advice(pin, 'Example objective', 'Example next step')
    assert card.card.open_source() is None
    card.toggle_play()
    assert 'Saved synthetic advice' in card.card.text.get('1.0', 'end-1c')
    assert not manager.windows[0].view.service.sent


def test_quest_step_pin_uses_frozen_snapshot_without_starting_research(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind='quests').view
    settle(view)
    key = next(iter(view.quest_tree.quests))
    view.quest_tree.tree.focus(key)
    calls = list(view.activity.calls)
    view.pin_quest_step()
    dialog = view._pin_dialog
    expected = dict(dialog.selection)
    view.quest_tree.quests[key]['title'] = 'Changed after opening review'
    dialog.save()
    card = manager.windows[-1]
    assert card.pin['objective'] == expected['objective']
    assert card.pin['evidence']['snapshot_at'] == 1000
    assert 'source' not in card.pin
    assert view.activity.calls == calls and not view.quest_chats
    assert not view.service.sent and not view.service.created


def test_pin_active_quest_reply_and_new_reply_never_replaces_it(manager_factory):
    manager = manager_factory(service=CreatingService)
    view = manager.new_window(kind='quests').view
    _, child = open_synthetic_quest_chat(view)
    child._show([Message('synthetic-first', 'assistant', 'First saved quest advice')])
    sent_before = list(child.service.sent)
    view.pin_to_play()
    dialog = child._pin_dialog
    dialog.next_step.set('Check the example route')
    dialog.save()
    card = manager.windows[-1]
    child._show([Message('synthetic-second', 'assistant', 'Later different advice')])
    card.card.poll()
    assert card.pin['text'] == 'First saved quest advice'
    assert card.pin['source']['session_id'] == child.selection_key[1]
    assert card.pin['evidence']['quest_id'] == child.context['quest']['id']
    assert child.service.sent == sent_before
    assert card.card.open_source() is child


def test_pin_validation_and_damaged_layout_keep_existing_file(manager_factory, tmp_path):
    from wow_helper.pinned_advice import pinned_selection, validate_pin
    with pytest.raises(ChatError):
        pinned_selection({'text': 'x' * 8001}, 'Goal', 'Step')
    with pytest.raises(ChatError):
        pinned_selection({'text': 'Advice', 'evidence': {'text': '🧭' * 17000}}, 'Goal', 'Step')
    pin = pinned_selection({'text':'Advice'}, 'Goal', 'Step')
    for bad in (dict(pin, version=2), dict(pin, version=True), dict(pin, objective=''), dict(pin, next_step=[])):
        with pytest.raises(ChatError):
            validate_pin(bad)
    path = tmp_path / 'damaged.json'
    raw = json.dumps({'version':1, 'windows':[{'kind':'play','pin':dict(pin,version=2)}]})
    path.write_text(raw)
    with pytest.raises(ChatError):
        manager_factory(path)
    assert path.read_text() == raw


@pytest.mark.parametrize('theme', ['classic', 'modern'])
def test_compact_card_keyboard_theme_opacity_and_monitor_recovery(manager_factory, theme):
    from wow_helper.theme import palette
    manager = manager_factory()
    card = manager.pin_advice({'text':'Readable saved advice'}, 'Example objective', 'Check the next step', {'font_size': 24})
    manager.preview_interface({'theme':theme, 'opacity':65, 'solid_when_active':False})
    card.root.geometry('340x300+80+80'); card.root.update()
    assert card.card.text.cget('bg') == palette(card.root).PANEL
    assert float(card.root.attributes('-alpha')) == pytest.approx(.65, abs=.01)
    for button in (card.card.expand, card.card.source):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= card.root.winfo_rooty() + card.root.winfo_height()
    card.card.text.focus_force(); card.root.update()
    card.card.text.event_generate('<Control-e>'); card.root.update()
    assert card.mode == 'desk'
    card.card.text.event_generate('<Control-e>'); card.root.update()
    assert card.mode == 'play'
    assert card.card.text.tk.call('tk_focusNext', str(card.card.text))
    bounds = window_bounds({'x':-3000,'y':-2000,'width':340,'height':300}, [(0,0,1920,1080)], card.minimum)
    assert bounds['width'] == 340 and bounds['height'] == 300
    assert bounds['x'] >= 0 and bounds['y'] >= 0
    manager.preview_interface(None)


def test_journal_selection_can_pin_without_changing_note_or_draft(manager_factory):
    manager = manager_factory()
    journal = manager.new_window(kind='journal').view
    settle(journal)
    journal.activity.add_note(journal.journal_id, 'Synthetic journal', 'Keep this saved advice',
                              next_time={'text':'Check the example route','state':'open'})
    journal.note.insert('1.0', 'Unsent journal draft')
    original = journal.activity.journal(journal.journal_id)
    journal.resume_session()
    journal._resume_dialog.pin_selected()
    dialog = journal._pin_dialog
    assert dialog.next_step.get() == 'Check the example route'
    dialog.save()
    assert manager.windows[-1].pin['text'] == 'Keep this saved advice'
    assert journal.note.get('1.0', 'end-1c') == 'Unsent journal draft'
    assert journal.activity.journal(journal.journal_id) == original
    assert not journal.service.sent


def test_named_layout_reuses_current_conversation_and_keeps_omitted_drafts(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    choose(first, 0)
    first.root.geometry('480x620+80+90'); first.root.update()
    manager.save_activity_layout('Leveling')
    choose(first, 1)
    first.view.editor.insert('1.0', 'Keep the current conversation draft')
    other = manager.new_window(kind='journal')
    other.view.note.insert('1.0', 'Unsent note outside the layout')
    first.root.geometry('700x800+200+200'); first.root.update()
    plan = manager.preview_activity_layout('Leveling')
    assert len(plan['reuse']) == 1 and not plan['create'] and len(plan['keep']) == 1
    manager.restore_activity_layout(plan)
    assert first.view.selection_key == SESSIONS[1].key
    assert first.view.editor.get('1.0', 'end-1c') == 'Keep the current conversation draft'
    assert other.view.note.get('1.0', 'end-1c') == 'Unsent note outside the layout'
    assert first.capture_bounds()['width'] == 480
    manager.restore_activity_layout(manager.preview_activity_layout('Leveling'))
    assert len(manager.windows) == 2
    assert not any(w.view.service.sent for w in manager.windows)


def test_named_layout_recreates_closed_windows_without_refresh_or_requests(manager_factory):
    manager = manager_factory(service=CreatingService)
    quest = manager.new_window(kind='quests')
    settle(quest.view)
    choose(quest, 0)
    card = manager.pin_advice({'text':'Saved synthetic advice'}, 'Example goal', 'Example step')
    card.toggle_play()
    manager.save_activity_layout('Review')
    manager.close_window(quest)
    manager.close_window(card)
    plan = manager.preview_activity_layout('Review')
    assert len(plan['create']) == 2
    manager.restore_activity_layout(plan)
    restored = next(w for w in manager.windows if w.kind == 'quests')
    settle(restored.view)
    assert restored.view.selection_key == SESSIONS[0].key
    assert not restored.view.activity.calls and not restored.view.service.sent and not restored.view.service.created
    restored_card = next(w for w in manager.windows if w.kind == 'play')
    assert restored_card.mode == 'desk' and restored_card.pin == card.pin
    manager.restore_activity_layout(manager.preview_activity_layout('Review'))
    assert len(manager.windows) == 3


def test_named_layout_limit_preview_and_stale_preview_preserve_windows(manager_factory):
    manager = manager_factory()
    extra = manager.new_window(kind='journal')
    manager.save_activity_layout('Preparation')
    manager.close_window(extra)
    while len(manager.windows) < MAX_WINDOWS:
        manager.new_window()
    plan = manager.preview_activity_layout('Preparation')
    assert len(plan['skipped']) == 1
    with pytest.raises(ChatError, match='Eight'):
        manager.restore_activity_layout(plan)
    assert len(manager.windows) == MAX_WINDOWS
    manager.restore_activity_layout(plan, allow_partial=True)
    manager.close_window(manager.windows[-1])
    with pytest.raises(ChatError, match='changed'):
        manager.restore_activity_layout(plan, allow_partial=True)
    manager.restore_activity_layout(manager.preview_activity_layout('Preparation'))
    assert len(manager.windows) == MAX_WINDOWS and any(w.kind == 'journal' for w in manager.windows)


def test_named_layout_restart_retention_off_and_changed_window_kind(manager_factory, tmp_path):
    path = tmp_path / 'windows.json'
    manager = manager_factory(path)
    chooser = manager.new_window()
    original_id = chooser.id
    manager.windows[0].remember.set(False)
    choose(manager.windows[0], 0)
    manager.windows[0].view.editor.insert('1.0', 'Do not copy this draft')
    manager.save_activity_layout('Leveling')
    chooser.open_chat()
    chooser.view.editor.insert('1.0', 'Keep changed window draft')
    manager.restore_activity_layout(manager.preview_activity_layout('Leveling'))
    replacement = next(w for w in manager.windows if w.kind == 'chooser')
    assert replacement.id != original_id and replacement.layout_key == original_id
    assert chooser.view.editor.get('1.0', 'end-1c') == 'Keep changed window draft'
    manager.close()
    restored = manager_factory(path)
    plan = restored.preview_activity_layout('Leveling')
    assert not plan['create'] and len(plan['reuse']) == 2
    restored.restore_activity_layout(plan)
    assert len(restored.windows) == 3
    assert restored.windows[0].view.editor.get('1.0', 'end-1c') == ''
    assert restored.windows[0].view.selection_key == SESSIONS[0].key


def test_named_layout_recreated_window_keeps_retention_off(manager_factory):
    manager = manager_factory()
    chat = new_chat(manager, manager.windows[0])
    chat.remember.set(False)
    choose(chat, 0)
    chat.view.editor.insert('1.0', 'Do not save my draft in a named arrangement')
    manager.save_activity_layout('Private review')
    manager.close_window(chat)
    manager.restore_activity_layout(manager.preview_activity_layout('Private review'))
    restored = manager.windows[-1]
    assert restored.id == chat.id and not restored.remember.get()
    assert restored.view.selection_key == SESSIONS[0].key
    assert restored.view.editor.get('1.0', 'end-1c') == ''


def test_named_layout_failed_restore_rolls_back_and_keeps_quest_tab(manager_factory, monkeypatch):
    from wow_helper import workspace
    manager = manager_factory(service=CreatingService)
    quest = manager.new_window(kind='quests')
    _, child = open_synthetic_quest_chat(quest.view)
    child.editor.insert('1.0', 'Keep quest draft')
    card = manager.pin_advice({'text':'Saved advice'}, 'Example goal', 'Example step')
    manager.save_activity_layout('Review')
    manager.close_window(card)
    quest.root.geometry('740x800+50+50'); quest.root.update()
    quest.view.book.select(child.root)
    previous = quest.capture_bounds()
    with monkeypatch.context() as patch:
        patch.setattr(workspace, 'display_workareas', lambda _: [(0, 0, 1280, 720)])
        patch.setattr(manager, 'save_layout', lambda: False)
        with pytest.raises(ChatError, match='previous windows and drafts are kept'):
            manager.restore_activity_layout(manager.preview_activity_layout('Review'))
    assert len(manager.windows) == 2
    assert quest.capture_bounds() == previous
    assert quest.view.active_quest_chat() is child
    assert child.editor.get('1.0', 'end-1c') == 'Keep quest draft'


def test_named_layout_monitor_recovery_and_changed_saved_preview(manager_factory, monkeypatch):
    from wow_helper import workspace
    manager = manager_factory()
    card = manager.pin_advice({'text':'Saved advice'}, 'Example goal', 'Example step')
    manager.save_activity_layout('Review')
    saved = manager.saved_layouts.get('Review')
    for record in saved['windows']:
        record['bounds'].update(x=-3000, y=-2000)
    manager.saved_layouts.save('Review', saved['windows'], replace=True)
    plan = manager.preview_activity_layout('Review')
    saved['windows'][0]['topmost'] = False
    manager.saved_layouts.save('Review', saved['windows'], replace=True)
    with pytest.raises(ChatError, match='changed'):
        manager.restore_activity_layout(plan)
    monkeypatch.setattr(workspace, 'display_workareas', lambda _: [(0, 0, 1920, 1080)])
    manager.restore_activity_layout(manager.preview_activity_layout('Review'))
    for window in manager.windows:
        assert window.capture_bounds()['x'] >= 0 and window.capture_bounds()['y'] >= 0
    assert card.capture_bounds()['width'] == 380
    assert not manager.windows[0].topmost.get()


@pytest.mark.parametrize('theme', ['classic', 'modern'])
def test_named_layout_dialog_save_preview_restore_and_minimum_controls(manager_factory, theme):
    manager = manager_factory()
    manager.preview_interface({'theme': theme})
    manager.show_activity_layouts(manager.windows[0])
    dialog = manager._layouts_dialog
    dialog.name.set('Leveling')
    dialog.save_button.invoke()
    assert dialog.selected.get() == 'Leveling'
    assert str(dialog.restore_button.cget('state')) == 'disabled'
    dialog.preview_button.invoke()
    assert 'Reposition: Agent chat' in dialog.details.get('1.0', 'end-1c')
    dialog.root.geometry('480x540+30+30'); dialog.root.update()
    for control in (dialog.save_button, dialog.selector, dialog.preview_button, dialog.replace_button, dialog.restore_button):
        assert control.winfo_ismapped()
        assert control.winfo_rooty() + control.winfo_height() <= dialog.root.winfo_rooty() + dialog.root.winfo_height()
    dialog.restore_button.invoke()
    assert dialog.message.get().startswith('Restored 1 windows.')
    dialog.name_entry.focus_force(); dialog.root.update()
    dialog.name_entry.event_generate('<Escape>'); manager.root.update()
    assert manager._layouts_dialog is None
    manager.preview_interface(None)


def test_search_unicode_notes_and_navigation_preserve_drafts(manager_factory):
    manager = manager_factory(service=CreatingService)
    window = manager.windows[0]
    choose(window, 0)
    window.view.editor.insert('1.0', 'Keep my draft')
    journal_id = str(uuid.uuid4())
    window.view.activity.add_note(journal_id, 'Expedition', 'Explore the café route',
        source={'provider': 'codex', 'session_id': SESSIONS[0].id},
        next_time={'text': 'Check the northern camp', 'state': 'open'})
    manager.show_search(window)
    dialog = manager._search_dialog
    dialog.query.set('CAFE\u0301')
    assert len(dialog.matches) == 1 and dialog.matches[0]['kind'] == 'note'
    assert 'northern camp' in dialog.preview.get('1.0', 'end-1c')
    dialog.activate()
    assert window.view.editor.get('1.0', 'end-1c') == 'Keep my draft'
    assert not window.view.service.sent and not window.view.service.created


def test_search_quest_and_layout_navigation_does_not_research_or_restore(manager_factory):
    manager = manager_factory(service=CreatingService)
    quest = manager.new_window(kind='quests')
    settle(quest.view)
    manager.save_activity_layout('Synthetic Leveling')
    calls = list(quest.view.activity.calls)
    manager.show_search(quest)
    dialog = manager._search_dialog
    row = next(r for r in dialog.rows if r['kind'] == 'quest')
    dialog.open_result(row)
    assert quest.view.quest_tree.selected() == row['target'][1]
    assert quest.view.activity.calls == calls and not quest.view.quest_chats
    manager.show_search(quest)
    dialog = manager._search_dialog
    dialog.open_result(next(r for r in dialog.rows if r['kind'] == 'layout'))
    assert manager._layouts_dialog.selected.get() == 'Synthetic Leveling'
    assert len(manager.windows) == 2 and not quest.view.service.sent


def test_search_refresh_missing_source_and_keyboard(manager_factory):
    manager = manager_factory()
    window = manager.windows[0]
    window.view.editor.insert('1.0', 'Keep this entire line')
    window.view.editor.mark_set('insert', '1.0')
    window.view.editor.focus_force(); window.root.update()
    window.view.editor.event_generate('<Control-k>'); window.root.update()
    dialog = manager._search_dialog
    assert window.view.editor.get('1.0', 'end-1c') == 'Keep this entire line'
    journal_id = str(uuid.uuid4())
    window.view.activity.add_note(journal_id, 'Offline notes', 'Synthetic missing source')
    dialog.refresh()
    dialog.query.set('missing source')
    assert len(dialog.matches) == 1
    assert str(dialog.open_button.cget('state')) == 'disabled'
    assert 'Synthetic missing source' in dialog.preview.get('1.0', 'end-1c')
    dialog.query.set('')
    dialog.entry.focus_force(); dialog.root.update()
    before = dialog.results.selection()
    dialog.entry.event_generate('<Down>'); dialog.root.update()
    assert dialog.results.selection() != before
    dialog.entry.event_generate('<Escape>'); manager.root.update()
    assert manager._search_dialog is None


def test_search_commands_are_quiet_and_stale_targets_keep_palette(manager_factory):
    manager = manager_factory(service=CreatingService)
    manager.show_search(manager.windows[0])
    dialog = manager._search_dialog
    dialog.open_result(next(r for r in dialog.rows if r['kind'] == 'command' and r['target'] == 'quests'))
    quest = manager.windows[-1]
    settle(quest.view)
    assert not quest.view.activity.calls and not quest.view.service.created and not quest.view.service.sent
    manager.show_search(manager.windows[0])
    dialog = manager._search_dialog
    row = next(r for r in dialog.rows if r['kind'] == 'window' and r['target'] == quest.id)
    manager.close_window(quest)
    with pytest.raises(ChatError, match='closed'):
        dialog.open_result(row)
    assert manager._search_dialog is dialog
    with pytest.raises(ChatError, match='unavailable'):
        dialog.open_result({'kind': 'arbitrary', 'target': 'execute'})


def test_search_restart_duplicate_labels_and_bad_journal(manager_factory, tmp_path):
    path = tmp_path / 'windows.json'
    manager = manager_factory(path)
    window = manager.windows[0]
    for _ in range(2):
        window.view.activity.add_note(str(uuid.uuid4()), 'Same name', 'Same synthetic note')
    bad = window.view.activity.storage / 'journals' / (str(uuid.uuid4()) + '.json')
    bad.write_text('{bad', encoding='utf-8')
    manager.close()
    manager = manager_factory(path)
    manager.show_search(manager.windows[0])
    dialog = manager._search_dialog
    dialog.query.set('Same synthetic note')
    assert len(dialog.matches) == 2
    assert dialog.matches[0]['target'] != dialog.matches[1]['target']
    assert 'unreadable' in dialog.notice.get()
    assert bad.read_text() == '{bad'


@pytest.mark.parametrize('theme', ['classic', 'modern'])
def test_search_minimum_controls_and_quest_editor_shortcut(manager_factory, theme):
    manager = manager_factory(service=CreatingService)
    quest = manager.new_window(kind='quests')
    _, child = open_synthetic_quest_chat(quest.view)
    child.editor.insert('1.0', 'Preserve quest follow-up')
    child.editor.mark_set('insert', '1.0')
    manager.preview_interface({'theme': theme})
    child.editor.focus_force(); quest.root.update()
    child.editor.event_generate('<Control-k>'); quest.root.update()
    dialog = manager._search_dialog
    assert child.editor.get('1.0', 'end-1c') == 'Preserve quest follow-up'
    dialog.chrome.place('480x540+30+30'); dialog.root.update()
    for control in (dialog.entry, dialog.results, dialog.preview, dialog.open_button):
        assert control.winfo_ismapped()
        assert control.winfo_rooty() + control.winfo_height() <= dialog.root.winfo_rooty() + dialog.root.winfo_height()
    dialog.close()
    manager.preview_interface(None)
