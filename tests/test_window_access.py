"""Synthetic reopen requests; never synthesize keystrokes or contact the game."""

import os
import sys
import threading
import time

import pytest

from wow_helper.window_access import WindowAccess, WindowsAPI, event_name, signal_existing
from wow_helper import window_access
from wow_helper.chat import ChatError


class API:
    def __init__(self, *, register=True):
        self.can_register = register
        self.events = {}
        self.press = threading.Event()
        self.registered_on = self.unregistered_on = None
        self.key = None

    def create_event(self, name):
        self.events[name] = False
        return name

    def signal_event(self, name):
        if name not in self.events:
            return False
        self.events[name] = True
        return True

    def take_event(self, name):
        result = self.events.get(name, False)
        if name in self.events:
            self.events[name] = False
        return result

    def close_event(self, name):
        self.events.pop(name, None)

    def register(self, key):
        self.key = key
        self.registered_on = threading.get_ident()
        return self.can_register

    def poll_hotkey(self):
        if self.press.is_set():
            self.press.clear()
            return True
        return False

    def unregister(self):
        self.unregistered_on = threading.get_ident()


def test_launch_signal_reopens_only_the_matching_live_instance(tmp_path):
    layout, other = tmp_path / "first.json", tmp_path / "second.json"
    api = API()
    access = WindowAccess(layout, api=api)
    try:
        assert not signal_existing(other, api=api)
        assert not access.requested()
        assert signal_existing(layout, api=api)
        assert signal_existing(layout, api=api)
        assert access.requested()
        assert not access.requested()
    finally:
        access.close()
    assert not signal_existing(layout, api=api)
    assert not access.requested()


def test_hotkey_runs_on_its_own_thread_and_unregisters_on_that_thread(tmp_path):
    api = API()
    access = WindowAccess(tmp_path / "windows.json", hotkey="F10", api=api)
    try:
        assert access.available
        assert access.shortcut == "Ctrl+Alt+F10" and api.key == 0x79
        assert api.registered_on != threading.get_ident()
        api.press.set()
        deadline = time.monotonic() + 2
        while not access.requested():
            assert time.monotonic() < deadline, "Synthetic shortcut was not delivered"
            time.sleep(0.01)
        assert not access.requested()
    finally:
        access.close()
    assert not access.available
    assert not access.thread.is_alive()
    assert api.unregistered_on == api.registered_on
    access.close()


def test_conflicting_shortcut_keeps_launch_signal_available(tmp_path):
    layout = tmp_path / "windows.json"
    api = API(register=False)
    access = WindowAccess(layout, api=api)
    try:
        assert not access.available
        assert signal_existing(layout, api=api)
        assert access.requested()
    finally:
        access.close()
    assert api.unregistered_on is None


def test_launch_reveals_existing_instance_without_starting_tk(monkeypatch):
    from wow_helper import chat_window, window_access
    monkeypatch.setattr(window_access, "signal_existing", lambda _: True)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert chat_window.launch() is None


def test_restart_event_is_separate_from_reveal_and_released_on_close(tmp_path):
    layout = tmp_path / "windows.json"
    api = API()
    access = WindowAccess(layout, api=api)
    name = event_name(layout, "Restart")
    try:
        assert api.signal_event(name)
        assert not access.requested()
        assert access.restart_requested()
        assert not access.restart_requested()
    finally:
        access.close()
    assert not api.signal_event(name)
    assert not access.restart_requested()


def test_restart_waits_for_the_saved_layout_to_be_released(tmp_path, monkeypatch):
    layout = tmp_path / "windows.json"
    api = API()
    name = event_name(layout, "Restart")
    api.create_event(name)
    attempts = []
    class Lock:
        def __init__(self, path):
            assert path == layout and api.events[name]
            attempts.append("acquire")
            if len(attempts) == 1:
                raise ChatError("Synthetic existing owner")
        def close(self):
            attempts.append("release")
    monkeypatch.setattr(window_access, "LayoutLock", Lock)
    assert window_access.restart_existing(layout, api=api)
    assert attempts == ["acquire", "acquire", "release"]


def test_restart_timeout_does_not_proceed_past_a_locked_layout(tmp_path, monkeypatch):
    layout = tmp_path / "windows.json"
    api = API()
    api.create_event(event_name(layout, "Restart"))
    def locked(_):
        raise ChatError("Synthetic existing owner")
    monkeypatch.setattr(window_access, "LayoutLock", locked)
    with pytest.raises(ChatError, match="could not finish restarting"):
        window_access.restart_existing(layout, api=api, timeout=0)


def test_restart_reports_older_versions_and_starts_normally_when_none_exist(tmp_path):
    layout = tmp_path / "windows.json"
    api = API()
    assert not window_access.restart_existing(layout, api=api)
    name = event_name(layout)
    api.create_event(name)
    with pytest.raises(ChatError, match="older companion"):
        window_access.restart_existing(layout, api=api)
    assert api.take_event(name)  # Reveal the older app so its Quit menu is reachable.


def test_restart_launcher_uses_only_the_companion_argv(monkeypatch):
    calls = []
    monkeypatch.setattr(window_access.sys, "executable", "synthetic-python.exe")
    monkeypatch.setattr(window_access.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)) or "process")
    assert window_access.start_restart("F10") == "process"
    args, options = calls[0]
    assert args[1:] == ["-m", "wow_helper", "chat", "--restart", "--hotkey", "F10"]
    assert options["shell"] is False
    assert options["stdin"] == options["stdout"] == options["stderr"] == window_access.subprocess.DEVNULL


def test_restart_launch_opens_fresh_ui_after_the_old_owner_exits(monkeypatch):
    from types import SimpleNamespace
    from wow_helper import chat_window, workspace
    calls = []
    access = SimpleNamespace(close=lambda: calls.append("release"))
    root = SimpleNamespace(mainloop=lambda: calls.append("run"))
    manager = SimpleNamespace(enable_reopening=lambda _: calls.append("enable"))
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root))
    monkeypatch.setattr(window_access, "restart_existing", lambda _: calls.append("restart"))
    monkeypatch.setattr(window_access, "signal_existing", lambda _: pytest.fail("Restart only revealed old UI"))
    monkeypatch.setattr(window_access, "WindowAccess", lambda *a, **kw: access)
    monkeypatch.setattr(workspace, "WindowManager", lambda _: manager)
    chat_window.launch(restart=True)
    assert calls == ["restart", "enable", "run", "release"]


@pytest.mark.skipif(os.name != "nt", reason="Windows named event and shortcut registration")
def test_native_event_delivery_and_registration_release(tmp_path):
    layout = tmp_path / "synthetic-layout.json"
    api = WindowsAPI()
    assert not signal_existing(layout)
    handle = api.create_event(event_name(layout))
    assert handle
    try:
        assert signal_existing(layout)
        assert api.take_event(handle)
        assert not api.take_event(handle)
        # Register a test-only F24 chord; no keypress is generated or required.
        registered = api.register(0x87)
        try:
            assert registered
            assert not api.poll_hotkey()
        finally:
            if registered:
                api.unregister()
    finally:
        api.close_event(handle)
    assert not signal_existing(layout)
