"""Shortcut registration and bounded requests without real input."""
import queue
import threading
import time
from wow_helper.comparison_shortcut import ComparisonShortcut


class API:
    def __init__(self, conflict=False):
        self.conflict = conflict
        self.events = queue.Queue()
        self.released = []
        self.threads = set()
    def register(self, key, *, modifiers, hotkey_id):
        self.threads.add(threading.get_ident())
        return not (self.conflict and hotkey_id == 2)
    def poll_hotkey(self, **_):
        self.threads.add(threading.get_ident())
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return False
    def unregister(self, *, hotkey_id):
        self.threads.add(threading.get_ident())
        self.released.append(hotkey_id)


def test_press_is_consumed_once_and_cleanup_stays_on_registration_thread():
    api = API(); key = ComparisonShortcut(api=api)
    try:
        assert key.available and not key.requested()
        api.events.put(True)
        deadline = time.monotonic() + 2
        while key.events.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert key.requested() and not key.requested()
        key.events.put(time.monotonic()-3)
        assert not key.requested()
    finally:
        key.close()
    assert api.released == [1, 2] and len(api.threads) == 1
    assert not key.requested() and not key.available


def test_partial_registration_conflict_releases_first_chord():
    api = API(conflict=True)
    key = ComparisonShortcut(api=api)
    key.close()
    assert not key.available and api.released == [1]
