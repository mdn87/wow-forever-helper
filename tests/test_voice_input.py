"""Synthetic dictation checks. Tests never open a microphone or send input."""

import threading
import time
import io
import sys
import types
import wave

import pytest

from wow_helper.voice_input import Dictation


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


def test_microphone_stream_closes_and_wav_is_bounded(monkeypatch):
    from wow_helper.voice_input import capture_audio
    stop = threading.Event()
    closed = []
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs['callback']
        def __enter__(self):
            self.callback(b'\0' * 16000, 8000, None, False)
            stop.set()
            return self
        def __exit__(self, *_):
            closed.append(True)
    monkeypatch.setitem(sys.modules, 'sounddevice', types.SimpleNamespace(RawInputStream=Stream))
    audio = capture_audio(stop, lambda: None)
    assert closed
    with wave.open(io.BytesIO(audio), 'rb') as wav:
        assert wav.getframerate() == 16000 and wav.getnframes() == 8000
    # A release before the worker starts must not open the device at all.
    closed.clear()
    assert capture_audio(stop, lambda: None) == b'' and not closed


def test_capture_error_preserves_no_audio_and_reports_failure():
    def fail(*_):
        raise OSError('Synthetic device failure')
    service = Dictation(capture=fail)
    service.start()
    assert 'Microphone unavailable' in wait_for(service, 'error')[1]
    service.close()


def test_recording_deadline_closes_stream_without_key_release(monkeypatch):
    from wow_helper.voice_input import capture_audio
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
    assert capture_audio(threading.Event(), lambda: None) == b''
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
