"""Synthetic frames exercise single-window capture and freshness rejection."""

from types import SimpleNamespace

import pytest

from wow_helper.chat import ChatError
from wow_helper.graphics_capture import grab_window


class FakeCapture:
    def __init__(self, frames, **options):
        self.frames, self.options = frames, options
        self.handlers = {}
        self.stopped = False

    def event(self, callback):
        self.handlers[callback.__name__] = callback
        return callback

    def stop(self):
        self.stopped = True

    def start(self):
        for frame in self.frames:
            self.handlers['on_frame_arrived'](frame, self)
            if self.stopped:
                break
        self.handlers['on_closed']()


def frame(timestamp, *, width=2, height=2, pixel=(1, 2, 3, 255)):
    return SimpleNamespace(timespan=timestamp, width=width, height=height,
                           frame_buffer=SimpleNamespace(tobytes=lambda: bytes(pixel) * width * height))


def test_discards_old_frames_and_captures_one_fresh_window_frame():
    capture = FakeCapture([frame(99), frame(101), frame(102, pixel=(9, 9, 9, 255))])
    def factory(**options):
        capture.options = options
        return capture
    result = grab_window(42, factory=factory, timestamp=lambda: 100)
    assert result.size == (2, 2) and result.getpixel((0, 0)) == (3, 2, 1)
    assert capture.stopped
    assert capture.options == {'window_hwnd': 42, 'monitor_index': None, 'cursor_capture': False}


@pytest.mark.parametrize('frames', [[], [frame(90)], [frame(101, width=0)],
                                  [frame(101, width=40000000)]])
def test_missing_stale_or_oversized_frames_fail_without_image(frames):
    capture = FakeCapture(frames)
    with pytest.raises(ChatError, match='fresh'):
        grab_window(42, factory=lambda **_: capture, timestamp=lambda: 100)


def test_no_fallback_or_raw_native_error_is_exposed():
    def failed(**_):
        raise RuntimeError('private native diagnostic')
    with pytest.raises(ChatError, match='fresh') as error:
        grab_window(42, factory=failed, timestamp=lambda: 100)
    assert 'private' not in str(error.value)
