"""Explicit local push-to-talk. No provider requests, game input, or audio files."""

import base64
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import wave

from .chat import ChatError, MAX_MESSAGE

MAX_SECONDS = 30
RATE = 16000


def capture_audio(stop, listening):
    try:
        import sounddevice as sd
    except ImportError:
        raise ChatError('Voice dependencies are missing. Install the optional voice package, then reopen this panel.') from None
    chunks = []
    size = 0
    overflow = threading.Event()

    def receive(data, frames, timing, status):
        nonlocal size
        if status:
            overflow.set()
        if size + len(data) <= RATE * 2 * MAX_SECONDS:
            chunks.append(bytes(data)); size += len(data)
        else:
            stop.set()

    if stop.is_set():
        return b''
    with sd.RawInputStream(samplerate=RATE, channels=1, dtype='int16', callback=receive):
        if not stop.is_set():
            listening()
            stop.wait(MAX_SECONDS)
    # The input stream is closed before any recognition starts.
    if overflow.is_set():
        raise ChatError('Audio was interrupted. Your draft is unchanged; try another recording.')
    if size < RATE // 2:
        return b''
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(RATE)
        audio.writeframes(b''.join(chunks))
    return output.getvalue()


def transcribe_audio(audio, cancelled=None):
    if os.name != 'nt':
        raise ChatError('Local voice input requires Windows.')
    if len(audio) > RATE * 2 * MAX_SECONDS + 1024:
        raise ChatError('Recording exceeds the 30-second limit.')
    shell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        with subprocess.Popen([str(shell), '-NoProfile', '-NonInteractive', '-File',
                               str(Path(__file__).with_name('voice_transcribe.ps1'))],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW) as process:
            deadline = time.monotonic() + 45
            first = True
            while True:
                if cancelled and cancelled.is_set():
                    process.terminate(); process.communicate(); return ''
                try:
                    output, _ = process.communicate(input=base64.b64encode(audio) if first else None, timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    if time.monotonic() >= deadline:
                        process.kill(); process.communicate()
                        raise ChatError('Local transcription timed out. Your draft is unchanged.')
            returncode = process.returncode
        data = json.loads(output.decode('utf-8-sig'))
        text = data.get('text', '')
        if returncode or data.get('error'):
            raise ChatError('Windows dictation is unavailable. Check the installed speech language and try again.')
        if not isinstance(text, str) or len(text) > MAX_MESSAGE or '\0' in text:
            raise ValueError
        return text.strip()
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError, AttributeError):
        raise ChatError('Local transcription did not finish. Your draft is unchanged; try again.') from None


class Dictation:
    def __init__(self, *, capture=capture_audio, transcribe=None):
        self.capture = capture
        self.events = queue.Queue()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.transcribe = transcribe or (lambda audio: transcribe_audio(audio, self.cancelled))
        self.busy = False
        self.thread = None

    def start(self):
        if self.busy or self.cancelled.is_set():
            return False
        self.busy = True
        self.release.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='companion-dictation')
        self.thread.start()
        return True

    def _run(self):
        try:
            audio = self.capture(self.release, lambda: self.events.put(('listening', '')))
            if self.cancelled.is_set():
                return
            self.events.put(('transcribing', ''))
            text = self.transcribe(audio) if audio else ''
            if not self.cancelled.is_set():
                self.events.put(('text', text))
        except Exception as error:
            if not self.cancelled.is_set():
                message = str(error) if isinstance(error, ChatError) else 'Microphone unavailable. Check Windows input and microphone permissions.'
                self.events.put(('error', message))

    def stop(self):
        self.release.set()

    def poll(self):
        events = []
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return events
            if event[0] in ('text', 'error'):
                self.busy = False
            events.append(event)

    def close(self):
        self.cancelled.set(); self.release.set()
        if self.thread:
            self.thread.join(timeout=1)


class PushToTalkKey:
    """Register only Ctrl+Alt+V. Observe only that chord's held state; no hooks."""
    def __init__(self):
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._listen, daemon=True, name='companion-voice-shortcut')
        self.thread.start()

    def _listen(self):
        if os.name != 'nt':
            self.events.put('unavailable'); return
        from .window_access import WindowsAPI
        import ctypes
        api = WindowsAPI()
        api.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        api.user.GetAsyncKeyState.restype = ctypes.c_short
        registered = False
        held = False
        try:
            registered = api.register(0x56)
            self.events.put('ready' if registered else 'unavailable')
            while registered and not self.stop.wait(.02):
                pressed = api.poll_hotkey()
                down = all(api.user.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x56))
                if pressed and down and not held:
                    held = True; self.events.put('press')
                elif pressed and not down:
                    self.events.put('tap')
                if held and not down:
                    held = False; self.events.put('release')
        except Exception:
            self.events.put('unavailable')
        finally:
            if registered:
                api.unregister()
            if held:
                self.events.put('release')

    def poll(self):
        items = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return items

    def close(self):
        self.stop.set(); self.thread.join(timeout=1)
