"""Synthetic PCM and isolated fake recognizers; no microphone or downloads."""

import io
import json
import os
import sys
import threading
import time
import types
import wave

import pytest

from wow_helper.chat import ChatError
from wow_helper.voice_transcription import LocalWhisper, decode_wave, load_model


def wav(*, rate=16000, channels=1, seconds=.5):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(channels); stream.setsampwidth(2); stream.setframerate(rate)
        stream.writeframes(b'\1\0' * int(rate * channels * seconds))
    return output.getvalue()


def fake_worker(connection, model_dir):
    try:
        if str(model_dir) == 'never-reads':
            time.sleep(30)
        while True:
            data = connection.recv_bytes()
            if str(model_dir) == 'slow':
                time.sleep(30)
            text = f'Synthetic transcript from {os.getpid()}'
            if str(model_dir) == 'oversized':
                text = 'x' * 6001
            connection.send_bytes(json.dumps({'text': text}).encode())
    except EOFError:
        pass
    finally:
        connection.close()


@pytest.mark.parametrize('audio', [b'not a wav', wav(rate=8000), wav(channels=2), wav(seconds=31)],
                         ids=['invalid-header', 'wrong-rate', 'stereo', 'too-long'])
def test_rejects_malformed_or_unexpected_recording_before_loading_model(audio):
    with pytest.raises(ChatError, match='recording'):
        decode_wave(audio)


def test_decodes_only_the_recorded_pcm():
    assert decode_wave(wav()) == b'\1\0' * 8000


def test_missing_model_is_actionable_and_never_downloaded(tmp_path):
    with pytest.raises(ChatError, match='download-model'):
        load_model(tmp_path)


def test_model_load_is_local_only_and_does_not_require_gpu(tmp_path, monkeypatch):
    from wow_helper.voice_transcription import MODEL_FILES
    for name in MODEL_FILES:
        (tmp_path / name).write_text('synthetic model placeholder')
    observed = []
    monkeypatch.setitem(sys.modules, 'faster_whisper', types.SimpleNamespace(
        WhisperModel=lambda path, **options: observed.append(options) or 'synthetic model'))
    assert load_model(tmp_path) == 'synthetic model'
    assert observed[0]['local_files_only'] is True
    assert observed[0]['device'] == 'cpu' and observed[0]['compute_type'] == 'int8'


def test_worker_stays_warm_between_recordings_and_closes():
    engine = LocalWhisper(worker=fake_worker, timeout=10)
    try:
        first = engine.transcribe(wav())
        assert first.startswith('Synthetic transcript')
        assert engine.transcribe(wav()) == first  # Same worker process.
        process = engine.process
    finally:
        engine.close()
    assert not process.is_alive()
    assert engine.transcribe(wav()) == ''


def test_cancellation_terminates_the_owned_worker_and_discards_result():
    cancelled = threading.Event()
    engine = LocalWhisper(model_dir='slow', worker=fake_worker, timeout=10)
    timer = threading.Timer(.3, cancelled.set)
    timer.start()
    try:
        assert engine.transcribe(wav(), cancelled) == ''
        assert engine.process is None
    finally:
        timer.join(); engine.close()


@pytest.mark.parametrize('mode', ['slow', 'never-reads'])
def test_timeout_stops_worker_and_preserves_draft(mode):
    engine = LocalWhisper(model_dir=mode, worker=fake_worker, timeout=.1)
    try:
        with pytest.raises(ChatError, match='timed out'):
            engine.transcribe(wav(seconds=30))
        assert engine.process is None
    finally:
        engine.close()


def test_unbounded_transcript_is_not_returned():
    engine = LocalWhisper(model_dir='oversized', worker=fake_worker, timeout=10)
    try:
        with pytest.raises(ChatError, match='transcription'):
            engine.transcribe(wav())
    finally:
        engine.close()


def test_cancelled_request_does_not_start_worker():
    cancelled = threading.Event(); cancelled.set()
    engine = LocalWhisper(worker=fake_worker)
    assert engine.transcribe(wav(), cancelled) == ''
    assert engine.process is None
    engine.close()


@pytest.mark.parametrize('mode', ['slow', 'never-reads'])
def test_closing_panel_during_transcription_discards_reply_and_stops_worker(mode):
    engine = LocalWhisper(model_dir=mode, worker=fake_worker, timeout=10)
    result = []
    thread = threading.Thread(target=lambda: result.append(engine.transcribe(wav(seconds=30))))
    thread.start()
    deadline = time.monotonic() + 2
    while engine.process is None:
        assert time.monotonic() < deadline
        time.sleep(.01)
    started = time.monotonic()
    engine.close()
    assert time.monotonic() - started < 2
    thread.join(timeout=2)
    assert not thread.is_alive() and result == ['']
    assert engine.process is None
