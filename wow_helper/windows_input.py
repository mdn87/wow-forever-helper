"""The sole native keyboard-input boundary. No game hooks or process-memory access."""

import ctypes as c
from ctypes import wintypes as w
import ntpath
import sys

from .assist import AssistError, Chord


WOW_EXECUTABLES = frozenset({"wow.exe", "wowb.exe", "wowclassic.exe"})


class KEYBDINPUT(c.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", c.c_size_t)]


class MOUSEINPUT(c.Structure):
    # Required to give the INPUT union its native size; no mouse events are built.
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", c.c_size_t)]


class INPUTUNION(c.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(c.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", w.DWORD), ("value", INPUTUNION)]


class WindowsInput:
    def __init__(self):
        if sys.platform != "win32":
            raise AssistError("Live key delivery requires Windows.")
        self.user = c.WinDLL("user32", use_last_error=True)
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.user.GetForegroundWindow.argtypes = []
        self.user.GetForegroundWindow.restype = w.HWND
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD
        self.user.GetAsyncKeyState.argtypes = [c.c_int]
        self.user.GetAsyncKeyState.restype = c.c_short
        self.user.SendInput.argtypes = [w.UINT, c.POINTER(INPUT), c.c_int]
        self.user.SendInput.restype = w.UINT
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = w.BOOL
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL

    def target(self):
        hwnd = self.user.GetForegroundWindow()
        pid = w.DWORD()
        if not hwnd or not self.user.GetWindowThreadProcessId(hwnd, c.byref(pid)):
            raise AssistError("Cannot identify the foreground window.")
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not handle:
            raise AssistError("Cannot identify the foreground application.")
        try:
            size = w.DWORD(32768)
            name = c.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, name, c.byref(size)):
                raise AssistError("Cannot identify the foreground application.")
            executable = ntpath.basename(name.value).lower()
        finally:
            self.kernel.CloseHandle(handle)
        if executable not in WOW_EXECUTABLES:
            raise AssistError("WoW must be the foreground application; no key was sent.")
        return hwnd, pid.value

    @staticmethod
    def event(vk, *, release=False):
        event = INPUT()
        event.type = 1
        event.ki.wVk = vk
        event.ki.dwFlags = 0x0002 if release else 0
        return event

    def send(self, events):
        packet = (INPUT * len(events))(*events)
        return self.user.SendInput(len(events), packet, c.sizeof(INPUT))

    def press(self, chord: Chord):
        target = self.target()
        # Reject interference instead of releasing a key the user is holding.
        guards = {*chord.codes, 0x10, 0x11, 0x12, 0x5B, 0x5C}
        if any(self.user.GetAsyncKeyState(vk) & 0x8000 for vk in guards):
            raise AssistError("Release held modifiers and the mapped key, then make a new request.")
        events = ([self.event(vk) for vk in chord.codes]
                  + [self.event(vk, release=True) for vk in reversed(chord.codes)])
        if self.target() != target:
            raise AssistError("The foreground game changed; no key was sent.")
        sent = self.send(events)
        if sent != len(events):
            # Release only keys with an accepted down event and no accepted up event.
            held = []
            for event in events[:sent]:
                vk = event.ki.wVk
                if event.ki.dwFlags & 0x0002:
                    held.remove(vk)
                else:
                    held.append(vk)
            if held:
                released = self.send([self.event(vk, release=True) for vk in reversed(held)])
                if released != len(held):
                    raise AssistError("Input incomplete and key release failed. Release the mapped keys manually; do not retry.")
            raise AssistError("Input delivery was incomplete; the spell outcome is unknown. No retry was made.")
