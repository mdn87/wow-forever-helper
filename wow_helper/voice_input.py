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


class Microphone:
    """Keep one input stream open; retain samples only inside an explicit hold."""
    def __init__(self, notify=lambda *_: None):
        self.notify = notify
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.error = None
        self.segment = None
        self.thread = threading.Thread(target=self._run, daemon=True, name='companion-microphone')
        self.thread.start()

    def _run(self):
        try:
            try:
                import sounddevice as sd
            except ImportError:
                raise ChatError('Voice dependencies are missing. Install the optional voice package, then reopen this panel.') from None
            with sd.RawInputStream(samplerate=RATE, channels=1, dtype='int16', callback=self._receive):
                self.ready.set()
                if not self.closed.is_set():
                    self.notify('ready', '')
                self.closed.wait()
        except Exception as error:
            self.error = (str(error) if isinstance(error, ChatError) else
                          'Microphone unavailable. Check Windows input and microphone permissions.')
            self.ready.set()
            if not self.closed.is_set():
                self.notify('device_error', self.error)

    def _receive(self, data, frames, timing, status):
        with self.lock:
            segment = self.segment
            if segment is None or segment['stop'].is_set() or self.closed.is_set():
                return  # No idle audio retained, including during transcription.
            if time.monotonic() >= segment['deadline']:
                segment['stop'].set(); return
            if status:
                segment['overflow'] = True
            remaining = RATE * 2 * MAX_SECONDS - segment['size']
            chunk = bytes(data[:remaining])
            segment['chunks'].append(chunk)
            segment['size'] += len(chunk)
            if len(data) >= remaining:
                segment['stop'].set()

    def capture(self, stop, listening):
        while not self.ready.wait(.02):
            if stop.is_set() or self.closed.is_set():
                return b''
        if stop.is_set() or self.closed.is_set():
            return b''
        if self.error:
            raise ChatError(self.error)
        segment = dict(stop=stop, deadline=time.monotonic() + MAX_SECONDS, chunks=[], size=0, overflow=False)
        with self.lock:
            if self.closed.is_set() or stop.is_set():
                return b''
            self.segment = segment
        try:
            listening()
            stop.wait(MAX_SECONDS)
        finally:
            with self.lock:
                self.segment = None
        if self.closed.is_set():
            return b''
        if segment['overflow']:
            raise ChatError('Audio was interrupted. Your draft is unchanged; try another recording.')
        if segment['size'] < RATE // 2:
            return b''
        output = io.BytesIO()
        with wave.open(output, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(RATE)
            audio.writeframes(b''.join(segment['chunks']))
        return output.getvalue()

    def close(self):
        self.closed.set()
        with self.lock:
            if self.segment:
                self.segment['stop'].set()
        self.thread.join(timeout=1)


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
    def __init__(self, *, capture=None, transcribe=None):
        self.events = queue.Queue()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.transcribe = transcribe or (lambda audio: transcribe_audio(audio, self.cancelled))
        self.busy = False
        self.thread = None
        self.microphone = Microphone(lambda *event: self.events.put(event)) if capture is None else None
        self.capture = capture if capture is not None else self.microphone.capture

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
        if self.microphone:
            self.microphone.close()
        if self.thread:
            self.thread.join(timeout=1)


class PushToTalkKey:
    """Register unmodified keypad minus and observe only its held state; no hooks."""
    def __init__(self, *, api=None):
        self.api = api
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._listen, daemon=True, name='companion-voice-shortcut')
        self.thread.start()

    def _listen(self):
        if os.name != 'nt' and self.api is None:
            self.events.put('unavailable'); return
        from .window_access import WindowsAPI
        api = self.api if self.api is not None else WindowsAPI()
        registered = False
        held = False
        try:
            registered = api.register(0x6D, modifiers=0)  # VK_SUBTRACT, distinct from row minus.
            self.events.put('ready' if registered else 'unavailable')
            while registered and not self.stop.wait(.02):
                pressed = api.poll_hotkey()
                down = api.key_down(0x6D)
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
