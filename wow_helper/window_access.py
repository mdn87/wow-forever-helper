"""Explicit Windows shortcuts and a local signal to reopen companion windows.

No keyboard hook, game input, network listener, or agent action is involved.
"""

import hashlib
import os
from pathlib import Path
import queue
import threading

HOTKEYS = {"H": (0x48, "Ctrl+Alt+H"), "F10": (0x79, "Ctrl+Alt+F10")}


def event_name(layout_path):
    identity = str(Path(layout_path).resolve()).casefold().encode("utf-8")
    return "Local\\WoWForeverHelper.Reopen." + hashlib.sha256(identity).hexdigest()[:32]


class WindowsAPI:
    """Small native boundary; messages belong to the helper's hotkey thread."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes = ctypes, wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.OpenEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.SetEvent.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user.RegisterHotKey.restype = wintypes.BOOL
        self.user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.UnregisterHotKey.restype = wintypes.BOOL
        self.user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                          wintypes.UINT, wintypes.UINT, wintypes.UINT]
        self.user.PeekMessageW.restype = wintypes.BOOL

    def create_event(self, name):
        # Auto-reset events coalesce repeated launches into one show request.
        return self.kernel.CreateEventW(None, False, False, name)

    def signal_event(self, name):
        handle = self.kernel.OpenEventW(0x0002, False, name)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        try:
            return bool(self.kernel.SetEvent(handle))
        finally:
            self.kernel.CloseHandle(handle)

    def take_event(self, handle):
        return bool(handle) and self.kernel.WaitForSingleObject(handle, 0) == 0

    def close_event(self, handle):
        if handle:
            self.kernel.CloseHandle(handle)

    def register(self, key):
        # CONTROL | ALT | NOREPEAT: one physical press, one reveal request.
        return bool(self.user.RegisterHotKey(None, 1, 0x4003, key))

    def poll_hotkey(self):
        message = self.wintypes.MSG()
        found = False
        # Only this thread's WM_HOTKEY messages; never inspect another app's queue.
        while self.user.PeekMessageW(self.ctypes.byref(message), self.wintypes.HWND(-1),
                                     0x0312, 0x0312, 0x0001):
            found = found or message.wParam == 1
        return found

    def unregister(self):
        self.user.UnregisterHotKey(None, 1)


def signal_existing(layout_path, *, api=None):
    if api is None:
        if os.name != "nt":
            return False
        api = WindowsAPI()
    return api.signal_event(event_name(layout_path))


class WindowAccess:
    """Transfer explicit reopen requests to Tk without calling Tk from a worker."""

    def __init__(self, layout_path, *, hotkey="H", api=None):
        self.key, self.shortcut = HOTKEYS[hotkey]
        self.available = False
        self.closed = False
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._requests = queue.Queue(maxsize=1)
        self.api = api if api is not None else (WindowsAPI() if os.name == "nt" else None)
        self.handle = self.api.create_event(event_name(layout_path)) if self.api else None
        self.thread = None
        if self.api:
            self.thread = threading.Thread(target=self._listen, name="companion-shortcut", daemon=True)
            self.thread.start()
            if not self._ready.wait(2):
                self.close()

    def _listen(self):
        registered = False
        try:
            registered = self.api.register(self.key)
            self.available = registered and not self.closed
            self._ready.set()
            while registered and not self._stop.wait(0.05):
                if self.api.poll_hotkey():
                    try:
                        self._requests.put_nowait(True)
                    except queue.Full:
                        pass
        except Exception:
            self.available = False
        finally:
            self._ready.set()
            if registered:
                self.api.unregister()

    def requested(self):
        if self.closed:
            return False
        try:
            hotkey = self._requests.get_nowait()
        except queue.Empty:
            hotkey = False
        return bool(self.api and self.api.take_event(self.handle)) or hotkey

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.available = False
        if self.api:
            self.api.close_event(self.handle)
        self.handle = None
