"""Session-only, explicit comparison shortcut; accepts held comparison Shift."""

import os
import queue
import threading
import time

from .window_access import WindowsAPI


class ComparisonShortcut:
    def __init__(self, *, api=None):
        self.api = api or (WindowsAPI() if os.name == 'nt' else None)
        self.available = False
        self.events = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        if self.api:
            self.thread = threading.Thread(target=self._listen, daemon=True, name='compare-shortcut')
            self.thread.start()
            if not self.ready.wait(2):
                self.close()

    def _listen(self):
        registered = []
        try:
            for key_id, modifiers in ((1, 3), (2, 7)):
                if not self.api.register(0x78, modifiers=modifiers, hotkey_id=key_id):
                    return
                registered.append(key_id)
            self.available = not self.stop.is_set()
            self.ready.set()
            while not self.stop.wait(0.025):
                if self.api.poll_hotkey(hotkey_ids=(1, 2)):
                    try:
                        self.events.put_nowait(time.monotonic())
                    except queue.Full:
                        pass
        except Exception:
            self.available = False
        finally:
            self.available = False
            self.ready.set()
            for key_id in registered:
                self.api.unregister(hotkey_id=key_id)

    def requested(self):
        try:
            at = self.events.get_nowait()
            return not self.stop.is_set() and time.monotonic() - at <= 2
        except queue.Empty:
            return False

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.available = False
