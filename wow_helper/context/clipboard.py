"""The clipboard transport: a packet the player copied out of the game as text.

The companion addon shows the packet in a small edit box and highlights it; the player presses
Ctrl+C. The text is ``WFHC1:`` followed by the envelope JSON. This module reads the system
clipboard on demand and parses what it finds. It never writes to the clipboard, never watches it
and never runs on its own: a caller asks once and gets one answer.

The clipboard is shared with every other program, so most of the time it holds something else.
That is the ordinary case and is reported as ``no-packet``, not as corruption. Text that does start
with the prefix is held to the envelope rules, and a size cap applies before anything is parsed.
"""
import os
import time

from .envelope import ENVELOPE_MAX_BYTES, ContextError, parse_envelope

PREFIX = "WFHC1:"
# The packet, the prefix, and a little whitespace the copy may have added around them.
CLIPBOARD_MAX_CHARS = len(PREFIX) + ENVELOPE_MAX_BYTES + 64
_LEAD = 64
_PAD = " \t\r\n\x00"


class ClipboardUnavailable(Exception):
    """The clipboard could not be read at all (busy, no text support, not Windows)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def parse_clipboard(text):
    """Turn clipboard text into an ``Envelope``, or raise ``ContextError``.

    ``no-packet`` means the text does not start with the prefix, which includes an empty clipboard.
    """
    if not isinstance(text, str) or not text[:_LEAD].lstrip(_PAD).startswith(PREFIX):
        raise ContextError("no-packet")
    if len(text) > CLIPBOARD_MAX_CHARS:
        raise ContextError("too-large")
    body = text.strip(_PAD)[len(PREFIX):]
    return parse_envelope(body)


def read_packet(reader=None):
    """Read the clipboard once and parse it. ``reader`` returns text or None and can be replaced in tests."""
    return parse_clipboard((reader or read_clipboard_text)())


def read_clipboard_text(max_chars=CLIPBOARD_MAX_CHARS):
    """The clipboard's text, cut to at most ``max_chars + 1`` characters, or None if it holds no text."""
    if os.name != "nt":
        raise ClipboardUnavailable("unsupported-platform")
    return _read_windows(max_chars)


def _read_windows(max_chars):
    import ctypes
    from ctypes import wintypes

    cf_unicodetext = 13
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    # Another program may hold the clipboard for a moment while it copies.
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        raise ClipboardUnavailable("busy")
    try:
        if not user32.IsClipboardFormatAvailable(cf_unicodetext):
            return None
        handle = user32.GetClipboardData(cf_unicodetext)
        if not handle:
            raise ClipboardUnavailable("no-data")
        size = kernel32.GlobalSize(handle)
        address = kernel32.GlobalLock(handle)
        if not address:
            raise ClipboardUnavailable("locked")
        try:
            # The block can be larger than the text and need not be zero filled, so read only as
            # far as the cap and cut at the first terminator.
            text = ctypes.wstring_at(address, min(size // 2, max_chars + 1))
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return text.split("\x00", 1)[0]
