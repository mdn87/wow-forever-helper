"""Mock the OS boundary: no keys are delivered to any live application."""

import ctypes
import sys
from types import SimpleNamespace

import pytest

from wow_helper.assist import AssistError, parse_key
from wow_helper.windows_input import INPUT, WindowsInput


def backend(targets=None, held=False, counts=None):
    instance = object.__new__(WindowsInput)
    snapshots = iter(targets or [(123, 456), (123, 456)])
    instance.target = lambda: next(snapshots)
    instance.user = SimpleNamespace(GetAsyncKeyState=lambda vk: 0x8000 if held else 0)
    calls = []
    responses = iter(counts) if counts is not None else None
    def send(events):
        calls.append([(event.type, event.ki.wVk, event.ki.dwFlags) for event in events])
        return next(responses) if responses is not None else len(events)
    instance.send = send
    return instance, calls


def test_shift_f4_is_one_ordered_packet_with_reverse_releases():
    instance, calls = backend()
    instance.press(parse_key("SHIFT+F4"))
    assert calls == [[(1, 16, 0), (1, 115, 0), (1, 115, 2), (1, 16, 2)]]


def test_focus_change_sends_nothing():
    instance, calls = backend(targets=[(123, 456), (321, 654)])
    with pytest.raises(AssistError, match="changed"):
        instance.press(parse_key("SHIFT+7"))
    assert calls == []


def test_held_modifier_sends_nothing():
    instance, calls = backend(held=True)
    with pytest.raises(AssistError, match="Release"):
        instance.press(parse_key("SHIFT+7"))
    assert calls == []


@pytest.mark.parametrize("accepted, releases", [(0, []), (1, [(1, 16, 2)]),
    (2, [(1, 115, 2), (1, 16, 2)]), (3, [(1, 16, 2)])])
def test_partial_delivery_only_releases_accepted_downs(accepted, releases):
    instance, calls = backend(counts=[accepted, len(releases)])
    with pytest.raises(AssistError, match="incomplete"):
        instance.press(parse_key("SHIFT+F4"))
    assert calls[1:] == ([releases] if releases else [])


def test_release_failure_is_reported():
    instance, calls = backend(counts=[1, 0])
    with pytest.raises(AssistError, match="release failed"):
        instance.press(parse_key("SHIFT+F4"))
    assert len(calls) == 2


def test_foreground_identification_uses_query_only_and_closes_handle():
    instance = object.__new__(WindowsInput)
    closed, access = [], []
    def pid(hwnd, out):
        out._obj.value = 456
        return 1
    def open_process(flags, inherit, process):
        access.append((flags, inherit, process))
        return 789
    def name(handle, flags, buffer, size):
        buffer.value = "wow.exe"
        return True
    instance.user = SimpleNamespace(GetForegroundWindow=lambda: 123, GetWindowThreadProcessId=pid)
    instance.kernel = SimpleNamespace(OpenProcess=open_process, QueryFullProcessImageNameW=name,
                                      CloseHandle=lambda handle: closed.append(handle))
    assert instance.target() == (123, 456)
    assert access == [(0x1000, False, 456)]
    assert closed == [789]
    def other(handle, flags, buffer, size):
        buffer.value = "notepad.exe"
        return True
    instance.kernel.QueryFullProcessImageNameW = other
    with pytest.raises(AssistError, match="foreground"):
        instance.target()
    assert closed == [789, 789]


def test_native_abi_and_read_only_api_initialization():
    if sys.platform == "win32":
        assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        instance = WindowsInput()
        assert instance.user.GetForegroundWindow.restype is not None
