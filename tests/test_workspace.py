"""Synthetic window lifecycle checks; no real agent connection or game input."""

import json
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


def test_first_launch_starts_one_chat_and_new_window_copies_size_with_chooser(manager_factory):
    manager = manager_factory()
    assert len(manager.windows) == 1
    first = manager.windows[0]
    assert first.kind == "chat"
    first.root.geometry("560x560+40+40")
    first.root.update()
    first.new_button.invoke()
    second = manager.windows[1]
    second.root.update()
    assert second.kind == "chooser" and second.view is None
    assert second.root.winfo_toplevel() is not first.root
    assert second.capture_bounds()["width"] == first.capture_bounds()["width"] == 560
    assert second.capture_bounds()["height"] == first.capture_bounds()["height"] == 560
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
    manager.close_window(second)
    assert len(manager.windows) == 1
    manager.close_window(first)
    assert manager.closed
    restored = manager_factory()
    assert len(restored.windows) == 1
    assert restored.windows[0].id == first.id


def test_minimum_size_keeps_chat_controls_visible_and_max_windows_is_enforced(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    first.root.geometry(f"{MIN_WIDTH}x{MIN_HEIGHT}+100+100")
    first.root.update()
    bottom = first.root.winfo_rooty() + first.root.winfo_height()
    assert first.view.editor.winfo_height() > 20
    assert first.view.transcript.winfo_height() > 20
    assert first.view.send_button.winfo_rooty() + first.view.send_button.winfo_height() < bottom
    for _ in range(MAX_WINDOWS - 1):
        manager.new_window(first)
    assert len(manager.windows) == MAX_WINDOWS
    assert manager.new_window(first) is None
    assert str(first.new_button["state"]) == "disabled"
    manager.close_window(manager.windows[-1])
    assert str(first.new_button["state"]) == "normal"


def test_window_menu_recovers_minimized_window(manager_factory):
    manager = manager_factory()
    first = manager.windows[0]
    second = manager.new_window(first)
    second.root.iconify()
    first.root.update()
    first.windows_menu.invoke(1)
    first.root.update()
    assert second.root.state() == "normal"


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
