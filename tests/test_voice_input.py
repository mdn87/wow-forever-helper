"""Synthetic dictation checks. Tests never open a microphone or send input."""

import threading
import time
import io
import sys
import types
import wave
import queue

import pytest

from wow_helper.voice_input import Dictation


@pytest.mark.parametrize('frames, expected', [
    ([(True, True), (True, True), (False, True), (False, False)], ['ready', 'press', 'release']),
    ([(True, False)], ['ready', 'tap']),
    ([(True, True)], ['ready', 'press', 'release']),  # Closing a held shortcut releases it.
])
def test_keypad_minus_tracks_hold_release_and_ignores_repeats(frames, expected):
    from wow_helper.voice_input import PushToTalkKey
    class API:
        def __init__(self):
            self.frames = queue.Queue()
            for frame in frames:
                self.frames.put(frame)
            self.done = threading.Event()
            self.down = False
            self.unregistered = False
        def register(self, key, *, modifiers):
            assert key == 0x6D and modifiers == 0  # VK_SUBTRACT, no Ctrl/Alt.
            return True
        def poll_hotkey(self):
            try:
                pressed, self.down = self.frames.get_nowait()
                return pressed
            except queue.Empty:
                self.done.set()
                return False
        def key_down(self, key):
            assert key == 0x6D  # Never poll minus-row, modifiers, or mouse buttons.
            return self.down
        def unregister(self):
            self.unregistered = True
    api = API()
    key = PushToTalkKey(api=api)
    try:
        assert api.done.wait(2)
    finally:
        key.close()
    assert key.poll() == expected
    assert api.unregistered


def test_keypad_minus_conflict_is_reported_without_reading_key_state():
    from wow_helper.voice_input import PushToTalkKey
    class API:
        def register(self, key, *, modifiers):
            return False
    key = PushToTalkKey(api=API())
    key.thread.join(timeout=1)
    key.close()
    assert key.poll() == ['unavailable']


def wait_for(service, kind):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        for event in service.poll():
            if event[0] == kind:
                return event
        time.sleep(.01)
    raise AssertionError('Expected voice event did not arrive')


def test_release_closes_capture_before_transcribing_and_duplicate_press_is_ignored():
    released = threading.Event()
    def capture(stop, listening):
        listening(); stop.wait(1); released.set(); return b'synthetic audio'
    def transcribe(audio):
        assert released.is_set()
        return 'Compare this item'
    service = Dictation(capture=capture, transcribe=transcribe)
    assert service.start()
    assert not service.start()
    wait_for(service, 'listening')
    service.stop()
    assert wait_for(service, 'text')[1] == 'Compare this item'
    service.close()


def test_cancel_discards_audio_and_never_transcribes():
    calls = []
    def capture(stop, listening):
        listening(); stop.wait(1); return b'synthetic'
    service = Dictation(capture=capture, transcribe=lambda audio: calls.append(audio))
    service.start(); wait_for(service, 'listening'); service.close()
    assert not calls


def test_microphone_stays_open_and_discards_audio_outside_each_hold(monkeypatch):
    from wow_helper.voice_input import Microphone
    streams = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
            self.closed = False
            streams.append(self)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            self.closed = True
    monkeypatch.setitem(sys.modules, 'sounddevice', types.SimpleNamespace(RawInputStream=Stream))
    mic = Microphone()
    assert mic.ready.wait(1)
    stream = streams[0]
    for value in (b'\x01\0', b'\x02\0'):
        stream.callback(b'\xff' * 16000, 8000, None, False)  # Idle audio must be dropped.
        stop = threading.Event()
        def listening():
            stream.callback(value * 8000, 8000, None, False)
            stop.set()
            stream.callback(b'\xff' * 16000, 8000, None, False)  # Already released.
        audio = mic.capture(stop, listening)
        assert not stream.closed and len(streams) == 1
        with wave.open(io.BytesIO(audio), 'rb') as wav:
            assert wav.getframerate() == 16000 and wav.getnframes() == 8000
            assert wav.readframes(8000) == value * 8000
    assert mic.capture(stop, lambda: None) == b''
    mic.close()
    assert stream.closed


def test_capture_error_preserves_no_audio_and_reports_failure():
    def fail(*_):
        raise OSError('Synthetic device failure')
    service = Dictation(capture=fail)
    service.start()
    assert 'Microphone unavailable' in wait_for(service, 'error')[1]
    service.close()


def test_connection_failure_is_reported_before_any_hold(monkeypatch):
    def fail(**_):
        raise OSError('Synthetic private device details')
    monkeypatch.setitem(sys.modules, 'sounddevice', types.SimpleNamespace(RawInputStream=fail))
    service = Dictation()
    assert wait_for(service, 'device_error')[1] == 'Microphone unavailable. Check Windows input and microphone permissions.'
    service.close()


def test_closing_microphone_during_hold_discards_audio(monkeypatch):
    from wow_helper.voice_input import Microphone
    class Stream:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
    monkeypatch.setitem(sys.modules, 'sounddevice', types.SimpleNamespace(RawInputStream=Stream))
    mic = Microphone()
    assert mic.ready.wait(1)
    assert mic.capture(threading.Event(), mic.close) == b''
    assert mic.closed.is_set() and not mic.thread.is_alive()


def test_recording_deadline_ends_segment_but_keeps_microphone_open(monkeypatch):
    from wow_helper.voice_input import Microphone
    monkeypatch.setattr('wow_helper.voice_input.MAX_SECONDS', .01)
    closed = []
    class Stream:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_):
            closed.append(True)
    monkeypatch.setitem(sys.modules, 'sounddevice', types.SimpleNamespace(RawInputStream=Stream))
    mic = Microphone()
    assert mic.ready.wait(1)
    assert mic.capture(threading.Event(), lambda: None) == b''
    assert not closed
    mic.close()
    assert closed


from test_workspace import manager_factory, SESSIONS, settle  # noqa: E402,F401


class FakeKey:
    def poll(self):
        return []
    def close(self):
        pass


class FakeDictation:
    busy = False
    def __init__(self):
        self.events = []
        self.closed = False
    def start(self):
        self.busy = True; return True
    def stop(self):
        self.busy = False
        self.events.append(('text', 'Compare this item'))
    def poll(self):
        events, self.events = self.events, []
        return events
    def close(self):
        self.closed = True


@pytest.mark.parametrize('theme', ['classic', 'modern'])
def test_voice_adds_to_draft_without_sending_or_changing_focus(manager_factory, theme):
    from wow_helper.voice_ui import VoiceDialog
    manager = manager_factory(); manager.preview_interface({'theme': theme})
    window = manager.windows[0]; view = window.view
    view.editor.insert('1.0', 'Existing draft.')
    panel = manager._voice_dialog = VoiceDialog(manager, window, dictation_factory=FakeDictation, key_factory=FakeKey)
    panel.chrome.place('440x480'); manager.root.update()
    assert panel.dictation is None  # Merely opening settings never records.
    panel.enable(); panel.start()
    prior_focus = manager.root.focus_get()
    panel.stop(); panel.poll()
    assert view.editor.get('1.0', 'end-1c') == 'Existing draft. Compare this item'
    assert manager.root.focus_get() == prior_focus
    assert not view.service.sent
    backend = panel.dictation
    panel.close(); assert backend.closed


def test_changed_session_or_full_draft_retains_transcript_without_insertion(manager_factory):
    from wow_helper.voice_ui import VoiceDialog
    from wow_helper.chat import MAX_MESSAGE
    manager = manager_factory(); window = manager.windows[0]; view = window.view
    panel = manager._voice_dialog = VoiceDialog(manager, window, dictation_factory=FakeDictation, key_factory=FakeKey)
    panel.enable(); panel.start()
    view._select_session(SESSIONS[0]); settle(view)
    view.editor.insert('1.0', 'New session draft')
    panel.stop(); panel.poll()
    assert view.editor.get('1.0', 'end-1c') == 'New session draft'
    assert 'destination changed' in panel.notice.get()
    assert panel.transcript.get('1.0', 'end-1c') == 'Compare this item'
    view.editor.delete('1.0', 'end'); view.editor.insert('1.0', 'x' * MAX_MESSAGE)
    panel.start(); panel.stop(); panel.poll()
    assert 'draft is full' in panel.notice.get()
    assert len(view.editor.get('1.0', 'end-1c')) == MAX_MESSAGE
    assert not view.service.sent
    backend = panel.dictation
    manager.new_window()
    manager.close_window(window)
    assert backend.closed and manager._voice_dialog is None
