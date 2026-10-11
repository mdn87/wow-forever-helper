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


@pytest.fixture
def manager_factory(tmp_path, desktop):
    tk, parent = desktop
    managers, views = [], []

    def create(path=tmp_path / "windows.json", service=Service):
        root = tk.Toplevel(parent)
        root.withdraw()
        manager = WindowManager(root, service_factory=service, layout_path=path)
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
def test_compact_toolbar_keeps_all_chat_actions_on_one_row(manager_factory, size):
    manager = manager_factory()
    window = manager.windows[0]
    window.chrome.place(size + "+100+100")
    window.root.update()
    view = window.view
    controls = [window.new_button, view.session_picker, view.refresh_button,
                view.send_button, window.menu_button]
    centers = [widget.winfo_rooty() + widget.winfo_height() / 2 for widget in controls]
    assert max(centers) - min(centers) <= 2
    assert max(widget.winfo_height() for widget in controls) <= 30
    assert view.session_picker.winfo_width() >= 120
    for left, right in zip(controls, controls[1:]):
        assert left.winfo_rootx() + left.winfo_width() <= right.winfo_rootx()
    assert controls[-1].winfo_rootx() + controls[-1].winfo_width() < window.root.winfo_rootx() + window.root.winfo_width()
    assert view.transcript.winfo_height() >= window.root.winfo_height() / 2
    choose(window, 1)
    assert window.options_menu.entrycget(view.setup_menu_index, "state") == "normal"
    window.options_menu.invoke(view.setup_menu_index)
    dialog = next(child for child in view.root.winfo_children() if isinstance(child, manager.tk.Toplevel))
    assert dialog.title() == "Connect this Claude session"
    dialog.destroy()
    choose(window, 0)
    assert window.options_menu.entrycget(view.setup_menu_index, "state") == "disabled"


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
