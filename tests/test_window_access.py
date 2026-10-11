"""Synthetic reopen requests; never synthesize keystrokes or contact the game."""

import os
import sys
import threading
import time

import pytest

from wow_helper.window_access import WindowAccess, WindowsAPI, event_name, signal_existing


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
