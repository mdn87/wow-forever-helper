"""Local Whisper dictation with a reusable, cancellable worker and in-memory audio."""

import argparse
import io
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time
import wave

from .chat import ChatError, MAX_MESSAGE

RATE = 16000
MAX_AUDIO = RATE * 2 * 30 + 1024
MODEL_DIR = Path(__file__).resolve().parents[1] / '.runtime' / 'voice-models' / 'small.en'
MODEL_REPO = 'Systran/faster-whisper-small.en'
MODEL_REVISION = 'd1d751a5f8271d482d14ca55d9e2deeebbae577f'
MODEL_FILES = ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')


def worker_context():
    context = multiprocessing.get_context('spawn')
    if os.name == 'nt':
        # A headless python.exe parent can otherwise create a visible console
        # for each child. Explicitly select the GUI-subsystem interpreter.
        executable = Path(sys.executable).with_name('pythonw.exe')
        if not executable.is_file():
            raise ChatError('Windowless Python is unavailable. Repair the voice installation before retrying.')
        context.set_executable(str(executable))
    return context


def decode_wave(audio):
    try:
        if not isinstance(audio, bytes) or len(audio) > MAX_AUDIO:
            raise ValueError
        with wave.open(io.BytesIO(audio), 'rb') as stream:
            if (stream.getframerate() != RATE or stream.getnchannels() != 1
                    or stream.getsampwidth() != 2 or stream.getnframes() > RATE * 30):
                raise ValueError
            pcm = stream.readframes(stream.getnframes())
            if len(pcm) != stream.getnframes() * 2:
                raise ValueError
            return pcm
    except (ValueError, wave.Error, EOFError):
        raise ChatError('The recording is invalid or exceeds the 30-second limit. Your draft is unchanged.') from None


def load_model(model_dir):
    if not all((Path(model_dir) / name).is_file() for name in MODEL_FILES):
        raise ChatError('Local speech model is missing. Run python -m wow_helper.voice_transcription --download-model, then retry.')
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ChatError('Whisper voice dependencies are missing. Install the optional voice package, then restart the companion.') from None
    return WhisperModel(str(model_dir), device='cpu', compute_type='int8', cpu_threads=4,
                        num_workers=1, local_files_only=True)


def recognize(model, pcm):
    import numpy as np
    # Our recorder supplies known PCM; avoid a general media decoder and temporary files.
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    segments, _ = model.transcribe(samples, language='en', beam_size=5, temperature=0,
                                   condition_on_previous_text=False, vad_filter=True)
    parts = []
    length = 0
    for segment in segments:
        text = segment.text.strip()
        length += len(text) + 1
        if length > MAX_MESSAGE + 1:
            raise ChatError('Local transcription was too long. Your draft is unchanged.')
        if text:
            parts.append(text)
    return ' '.join(parts)


def _serve(connection, model_dir):
    # The worker is offline. Only the separate, explicit model setup command downloads.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    model = None
    try:
        while True:
            audio = connection.recv_bytes(MAX_AUDIO)
            try:
                pcm = decode_wave(audio)
                if not pcm.strip(b'\0'):
                    result = {'text': ''}
                else:
                    if model is None:
                        model = load_model(model_dir)
                    result = {'text': recognize(model, pcm)}
            except Exception as error:
                result = {'error': str(error) if isinstance(error, ChatError) else
                          'Local Whisper transcription failed. Your draft is unchanged; check the voice installation.'}
            connection.send_bytes(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    except (EOFError, OSError):
        pass
    finally:
        connection.close()


class LocalWhisper:
    """One worker per enabled voice panel. Cancellation stops only our own process."""
    def __init__(self, model_dir=MODEL_DIR, *, timeout=90, worker=_serve):
        self.model_dir, self.timeout, self.worker = model_dir, timeout, worker
        self.process = self.connection = None
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.call_lock = threading.Lock()

    def _stop(self):
        with self.lock:
            if self.process is not None:
                if self.process.pid is not None:
                    if self.process.is_alive():
                        self.process.terminate()
                    self.process.join(timeout=1)
                self.process = None
            if self.connection is not None:
                self.connection.close()
                self.connection = None

    def transcribe(self, audio, cancelled=None):
        if self.closed.is_set() or (cancelled and cancelled.is_set()):
            return ''
        pcm = decode_wave(audio)
        if not pcm.strip(b'\0'):
            return ''
        with self.call_lock:
            expired = threading.Event()
            timer = None
            def expire():
                expired.set()
                self._stop()
            try:
                with self.lock:
                    if self.closed.is_set() or (cancelled and cancelled.is_set()):
                        return ''
                    if self.process is None:
                        context = worker_context()
                        self.connection, child = context.Pipe()
                        self.process = context.Process(target=self.worker, args=(child, self.model_dir), daemon=True)
                        try:
                            self.process.start()
                        finally:
                            child.close()
                    connection = self.connection
                # Do not hold the lifecycle lock during a pipe write: closing the
                # panel must be able to terminate a stalled reader immediately.
                timer = threading.Timer(self.timeout, expire)
                timer.daemon = True
                timer.start()
                connection.send_bytes(audio)
                deadline = time.monotonic() + self.timeout
                while True:
                    if self.closed.is_set() or (cancelled and cancelled.is_set()):
                        self._stop(); return ''
                    if connection.poll(.05):
                        result = json.loads(connection.recv_bytes(32_000))
                        if self.closed.is_set() or (cancelled and cancelled.is_set()):
                            self._stop(); return ''
                        if not isinstance(result, dict):
                            raise ValueError
                        if result.get('error'):
                            raise ChatError(str(result['error']))
                        text = result.get('text')
                        if not isinstance(text, str) or len(text) > MAX_MESSAGE or '\0' in text:
                            raise ValueError
                        return text.strip()
                    if time.monotonic() >= deadline:
                        raise ChatError('Local transcription timed out. Your draft is unchanged.')
            except (OSError, EOFError, ValueError, RuntimeError, ChatError) as error:
                self._stop()
                if self.closed.is_set() or (cancelled and cancelled.is_set()):
                    return ''
                if expired.is_set():
                    raise ChatError('Local transcription timed out. Your draft is unchanged.') from None
                if isinstance(error, ChatError):
                    raise
                raise ChatError('Local transcription did not finish. Your draft is unchanged; try again.') from None
            finally:
                if timer:
                    timer.cancel()
                    timer.join(timeout=2)

    def close(self):
        self.closed.set()
        self._stop()


def download_model():
    root = MODEL_DIR.parent
    os.environ['HF_HOME'] = str(root / 'hub-cache')
    os.environ['HF_XET_CACHE'] = str(root / 'xet-cache')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION, local_dir=MODEL_DIR,
                      allow_patterns=list(MODEL_FILES), token=False)


def main():
    parser = argparse.ArgumentParser(description='Set up the local English dictation model (about 500 MB).')
    parser.add_argument('--download-model', action='store_true', required=True)
    parser.parse_args()
    try:
        download_model()
    except Exception:
        print('Speech model setup failed. Check the voice dependencies and network connection, then retry.')
        return 1
    print('Local English speech model is ready. Recorded audio is never uploaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
