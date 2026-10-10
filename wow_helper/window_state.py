"""Bounded private window state and read-only desktop geometry discovery."""

import os
from pathlib import Path

from .chat import ChatError, Message, identifier

MIN_WIDTH, MIN_HEIGHT = 440, 540
MAX_WINDOWS = 8
MAX_HISTORY_CHARS = 200_000


def saved_selection(raw):
    if not isinstance(raw, dict) or raw.get("provider") not in ("codex", "claude"):
        return None
    try:
        return raw["provider"], identifier(raw.get("id"))
    except ChatError:
        return None


def history_state(messages):
    """Keep a bounded recent text snapshot; the provider remains authoritative."""
    result, remaining = [], MAX_HISTORY_CHARS
    for message in reversed(messages[-100:]):
        if message.role not in ("user", "assistant"):
            continue
        text = message.text
        if len(text) > 32_000:
            text = text[:32_000] + "\n[Saved preview shortened. Reconnect to read the full message.]"
        if len(text) > remaining:
            break
        result.append({"id": message.id[:200], "role": message.role, "text": text})
        remaining -= len(text)
    return list(reversed(result))


def restored_history(raw):
    messages = []
    if isinstance(raw, list):
        for item in raw[-100:]:
            if (isinstance(item, dict) and isinstance(item.get("id"), str)
                    and item.get("role") in ("user", "assistant") and isinstance(item.get("text"), str)):
                messages.append(Message(item["id"], item["role"], item["text"]))
    return [Message(**item) for item in history_state(messages)]


def display_workareas(root):
    """Read monitor work areas without changing focus, input, or game state."""
    fallback = [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
    if os.name != "nt":
        return fallback
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                          callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    areas = []

    @callback_type
    def collect(monitor, _dc, _rect, _data):
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            area = (r.left, r.top, r.right, r.bottom)
            if info.dwFlags & 1:
                areas.insert(0, area)
            else:
                areas.append(area)
        return True

    return areas if user32.EnumDisplayMonitors(None, None, collect, 0) and areas else fallback


def window_bounds(raw, areas):
    """Preserve negative monitor coordinates and recover windows from removed screens."""
    raw = raw if isinstance(raw, dict) else {}

    def integer(name, default, low, high):
        value = raw.get(name)
        return max(low, min(value, high)) if type(value) is int else default

    x, y = integer("x", 60, -32_000, 32_000), integer("y", 80, -32_000, 32_000)
    area = next((a for a in areas if a[0] <= x < a[2] - 80 and a[1] <= y < a[3] - 80), areas[0])
    left, top, right, bottom = area
    width = min(integer("width", 620, MIN_WIDTH, 4000), max(MIN_WIDTH, right - left - 24))
    height = min(integer("height", 700, MIN_HEIGHT, 3000), max(MIN_HEIGHT, bottom - top - 48))
    x = max(left, min(x, right - width - 12))
    y = max(top, min(y, bottom - height - 40))
    return {"x": x, "y": y, "width": width, "height": height}


class LayoutLock:
    """An OS-released lock prevents two helper processes from overwriting the layout."""

    def __init__(self, path):
        self.stream = None
        if path is None:
            return
        path = Path(path).with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+b")
        try:
            if not stream.tell():
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise ChatError("Companion windows are already open. Find them on the taskbar or in their Windows menu.") from None
        self.stream = stream

    def close(self):
        if self.stream is not None:
            # Closing the descriptor releases the lock, including after a crash.
            self.stream.close()
            self.stream = None
