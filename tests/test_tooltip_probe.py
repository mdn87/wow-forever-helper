"""Synthetic checks for the explicit, one-shot live-tooltip diagnostic."""

import pytest

from wow_helper.chat import ChatError
from wow_helper.tooltip_probe import probe


class API:
    def __init__(self, *, available=True, pressed=True):
        self.available, self.pressed = available, pressed
        self.registered = self.closed = False
        self.registrations = []
        self.released = []

    def register(self, key, *, modifiers=3, hotkey_id=1):
        self.registered = True
        self.registrations.append((key, modifiers, hotkey_id))
        return self.available

    def poll_hotkey(self, *, hotkey_ids=(1,)):
        return self.pressed

    def unregister(self, *, hotkey_id=1):
        self.released.append(hotkey_id)
        self.closed = True


def run_probe(tmp_path, *, api=None, foreground=None, identify=None, capture=None, timeout=1):
    records, captures = [], []
    api = api or API()
    def save(storage, flavor):
        captures.append(flavor)
        return "synthetic.png"
    ticks = iter(range(100))
    result = probe(tmp_path, "_classic_beta_", api=api,
                   identify=identify or (lambda _: 42),
                   foreground=foreground or (lambda: 42),
                   capture=capture or save, publish=records.append,
                   clock=lambda: next(ticks) * 0.1, sleep=lambda _: None,
                   timeout=timeout)
    return result, records, captures, api


def test_press_captures_once_and_releases_shortcut(tmp_path):
    result, records, captures, api = run_probe(tmp_path)
    assert captures == ["_classic_beta_"]
    assert [record["state"] for record in records] == ["ready", "capturing", "captured"]
    assert result["image"] == "synthetic.png"
    assert result["focus_unchanged"] is True
    assert result["capture_seconds"] > 0
    assert api.closed


def test_no_game_never_arms_or_captures(tmp_path):
    def absent(_):
        raise ChatError("No visible game")
    result, _, captures, api = run_probe(tmp_path, identify=absent)
    assert result["state"] == "unavailable"
    assert not api.registered and not captures


@pytest.mark.parametrize("available,pressed,state", [(False, True, "shortcut-unavailable"),
                                                     (True, False, "expired")])
def test_no_capture_without_successful_shortcut(tmp_path, available, pressed, state):
    result, _, captures, api = run_probe(tmp_path, api=API(available=available, pressed=pressed))
    assert result["state"] == state and not captures
    assert api.closed == available


def test_foreground_mismatch_refuses_capture(tmp_path):
    result, _, captures, api = run_probe(tmp_path, foreground=lambda: 7)
    assert result["state"] == "wrong-foreground" and not captures and api.closed


def test_capture_failure_is_terminal_and_does_not_expose_exception(tmp_path):
    calls = []
    def fail(*_):
        calls.append(True)
        raise OSError("private diagnostic detail")
    result, records, _, api = run_probe(tmp_path, capture=fail)
    assert result["state"] == "capture-failed" and len(calls) == 1 and api.closed
    assert "private diagnostic" not in str(records)


def test_focus_change_is_recorded_as_unverified(tmp_path):
    windows = iter([42, 9])
    result, _, _, _ = run_probe(tmp_path, foreground=lambda: next(windows))
    assert result["focus_unchanged"] is False


def test_changed_game_window_does_not_capture(tmp_path):
    windows = iter([42, 43])
    result, _, captures, api = run_probe(tmp_path, identify=lambda _: next(windows))
    assert result["state"] == "game-changed" and not captures and api.closed


def test_comparison_shift_chord_is_accepted_and_both_chords_released(tmp_path):
    class ShiftAPI(API):
        def poll_hotkey(self, *, hotkey_ids=(1,)):
            return 2 in hotkey_ids
    result, _, captures, api = run_probe(tmp_path, api=ShiftAPI())
    assert result["state"] == "captured" and len(captures) == 1
    assert api.registrations == [(0x78, 3, 1), (0x78, 7, 2)]
    assert api.released == [1, 2]


def test_shift_chord_conflict_releases_first_registration_without_capture(tmp_path):
    class ConflictAPI(API):
        def register(self, key, *, modifiers=3, hotkey_id=1):
            super().register(key, modifiers=modifiers, hotkey_id=hotkey_id)
            return hotkey_id == 1
    result, _, captures, api = run_probe(tmp_path, api=ConflictAPI())
    assert result["state"] == "shortcut-unavailable" and not captures
    assert api.released == [1]
