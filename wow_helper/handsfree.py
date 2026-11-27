"""Hands-free voice: one companion window driven by finished Lugos Voice turns.

The controller owns the voice bridge binding. Each turn is first matched against
the spoken command grammar in voice_commands; a recognized game command goes
through the existing assistive input checks; a browser command drives the
companion's own voice browser on a worker thread; anything else is sent to the
window's selected chat. Every turn is answered in the bridge's results folder,
which Lugos Voice speaks.
"""

import queue
import sqlite3
import threading

from .bnet_voice import BnetVoiceLookup
from .chat import ROOT
from .voice_bridge import VoiceBridge
from .voice_browser import Browser, BrowserError
from .voice_commands import Interpreter

POLL_MS = 250
HISTORY = 6


def default_assistant():
    from .assist import Assistant
    assistant = Assistant(ROOT / ".runtime" / "assist.sqlite", None)
    if assistant.stubbed():
        from .stub_input import StubInput
        assistant.desktop = StubInput(assistant.path.parent / "stub-presses.jsonl")
    else:
        from .windows_input import WindowsInput
        assistant.desktop = WindowsInput()
    return assistant


def is_game_command(text):
    from .assist import AssistError, resolve
    try:
        resolve(text)
        return True
    except AssistError:
        return False


class HandsFree:
    def __init__(self, manager, *, bridge_factory=VoiceBridge, assistant_factory=default_assistant,
                 browser_factory=Browser, bnet_factory=BnetVoiceLookup):
        self.manager = manager
        self.bridge = bridge_factory()
        self.assistant_factory = assistant_factory
        self.browser_factory, self._browser = browser_factory, None
        self.bnet_factory, self._bnet = bnet_factory, None
        self.finished = queue.Queue()   # browser and Battle.net results, answered on the interface thread
        self.window = None
        self.auto = False
        self.commands_only = False
        self.history = []
        self.listeners = []
        self.exclude = set()
        self._after = None
        self._last_chat = None

    @property
    def connected(self):
        return self.window is not None and self.bridge.connected

    def settings(self):
        data = {"auto": self.auto, "window": self.window.id if self.window else self._saved_window}
        if self.commands_only:
            data["commands_only"] = True
        return data

    _saved_window = None

    def restore(self, data):
        """Reconnect at startup only when the player chose that in the panel."""
        data = data if isinstance(data, dict) else {}
        self.auto = data.get("auto") is True
        self.commands_only = data.get("commands_only") is True
        self._saved_window = data.get("window") if isinstance(data.get("window"), str) else None
        if self.auto:
            window = next((w for w in self.manager.windows if w.id == self._saved_window), None)
            window = window or next((w for w in self.manager.windows if w.view and hasattr(w.view, "editor")), None)
            if window is not None:
                self.connect(window)

    def set_auto(self, value):
        self.auto = bool(value)
        self.manager.schedule_save()
        self._changed()

    def set_commands_only(self, value):
        self.commands_only = bool(value)
        self.manager.schedule_save()
        self._changed()

    def connect(self, window):
        if self.connected:
            self.disconnect()
        self.window = window
        self._saved_window = window.id
        self._last_chat = None
        self.bridge.connect(window.caption or "Companion window", "companion")
        self._schedule()
        self._note("", "connected", f"Connected to {window.caption or 'this window'}.")
        self.manager.refresh_mode_badges()
        self.manager.schedule_save()

    def disconnect(self, reason="Hands-free voice disconnected."):
        was = self.connected
        self.bridge.disconnect()
        self.window = None
        if self._after is not None:
            try:
                self.manager.root.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        if was:
            self._note("", "disconnected", reason)
        self.manager.refresh_mode_badges()

    def window_closed(self, window):
        if window is self.window:
            self.disconnect("The connected window closed, so hands-free voice disconnected.")

    def close(self):
        self.disconnect()
        self.listeners.clear()

    def _schedule(self):
        self._after = self.manager.root.after(POLL_MS, self.poll)

    def _changed(self):
        for listener in list(self.listeners):
            listener()

    def _note(self, text, status, detail):
        self.history = (self.history + [(text, status, detail)])[-HISTORY:]
        if self.window is not None and not self.window.closed:
            self.window.set_notice(detail[:200])
        self._changed()

    def poll(self):
        self._after = None
        if not self.connected:
            return
        if self.window.closed:
            self.disconnect("The connected window closed, so hands-free voice disconnected.")
            return
        self.bridge.heartbeat()
        self.answer_finished()
        for request in self.bridge.pending():
            self.handle(request)
            if not self.connected:
                return
        self._schedule()

    def interpreter(self):
        return Interpreter(self.manager, self.window, exclude=self.exclude, game=is_game_command)

    def handle(self, request):
        request_id, text = request["id"], request["text"]
        try:
            outcome = self.interpreter().handle(text)
        except Exception:
            # A widget that vanished mid-command must not stop the inbox.
            self.bridge.report(request_id, "failed", "That command could not finish. Nothing else was changed.")
            self._note(text, "failed", "That command could not finish.")
            return
        if outcome.kind == "chat":
            if self.commands_only and outcome.text.strip() == text.strip():
                detail = 'Commands-only mode is on. Say "ask the agent" or "tell the agent" before a chat question.'
                self.bridge.report(request_id, "rejected", detail)
                self._note(text, "refused", detail)
                return
            self.send_chat(request_id, outcome.text)
        elif outcome.kind == "game":
            self.run_game(request_id, outcome.text, request.get("spoken_at"))
        elif outcome.kind == "browser":
            self.run_browser(request_id, text, outcome.detail, outcome.text)
        elif outcome.kind == "bnet":
            self.run_bnet(request_id, text, outcome.detail, outcome.text)
        elif outcome.kind == "refused":
            self.bridge.report(request_id, "rejected", outcome.detail)
            self._note(text, "refused", outcome.detail)
        else:
            self.bridge.report(request_id, "done", outcome.detail)
            self._note(text, "done", outcome.detail)
            if outcome.kind == "disconnect":
                self.disconnect(outcome.detail)

    def send_chat(self, request_id, text):
        view = self.interpreter().view()
        def keep_question():
            if view is None or view.closed:
                return
            current = view.editor.get("1.0", "end-1c")
            if current != text and not current.endswith("\n" + text):
                view.replace_draft("\n".join(filter(None, (current, text))))

        if view is None or view.selected is None:
            if view:
                keep_question()
                view.choose_chat()
            detail = "Choose a chat, then say send. Your spoken question is in the draft."
            self.bridge.report(request_id, "rejected", detail)
            self._note(text, "refused", detail)
            return
        key, title = view.selected.key, view.selected.title
        changed = self._last_chat is not None and self._last_chat != key
        detail = f"That went to {title[:60]}." if changed else ""

        def delivered(result, error):
            if error and view.selection_key == key:
                keep_question()
            self.bridge.report(request_id, "failed" if error else "sent", error or detail)
            self._note(text, "failed" if error else "sent", error or ("Sent. " + detail).strip())

        if view.send_message(text, request_id=request_id, on_delivery=delivered):
            self._last_chat = key
        else:
            keep_question()
            detail = view.status.get() or "The chat is busy. Your question is in the draft."
            self.bridge.report(request_id, "rejected", detail)
            self._note(text, "refused", detail)

    def run_game(self, request_id, text, spoken_at):
        from .assist import AssistError
        try:
            result = self.assistant_factory().request(text, execute=True, request_id=request_id, issued_at=spoken_at)
        except AssistError as error:
            self.bridge.report(request_id, "rejected", str(error))
            self._note(text, "refused", str(error))
            return
        except (OSError, sqlite3.Error, ImportError):
            detail = "Local input or state storage is unavailable; no automatic retry."
            self.bridge.report(request_id, "failed", detail)
            self._note(text, "failed", detail)
            return
        detail = result.get("message", "Key sent once; spell success is not verified.")
        self.bridge.report(request_id, "done", detail)
        self._note(text, "done", detail)

    @property
    def browser(self):
        if self._browser is None:
            self._browser = self.browser_factory()
        return self._browser

    def run_browser(self, request_id, text, action, argument):
        """Drive the voice browser off the interface thread; poll() answers when it finishes."""
        def work():
            try:
                result = ("done", self.browser.run(action, argument))
            except BrowserError as error:
                result = ("rejected", str(error))
            except Exception:
                result = ("failed", "The voice browser did not answer. Nothing else was changed.")
            self.finished.put((request_id, text) + result)

        threading.Thread(target=work, name="voice-browser", daemon=True).start()

    @property
    def bnet(self):
        if self._bnet is None:
            self._bnet = self.bnet_factory()
        return self._bnet

    def run_bnet(self, request_id, text, action, argument):
        """Run a cached Battle.net lookup off the UI thread; fall back to the voice browser when signaled."""
        def work():
            try:
                outcome = self.bnet.run(action, argument)
                if outcome.status == "fallback" and outcome.fallback_query:
                    try:
                        browser_reply = self.browser.run("classic", outcome.fallback_query)
                        result = ("done", f"Not in the Forever item API; checked Classic Wowhead instead. {browser_reply}")
                    except BrowserError as error:
                        result = ("rejected", f"{outcome.detail} {error}")
                    except Exception:
                        result = ("failed", f"{outcome.detail} The voice browser fallback did not answer.")
                else:
                    result = (outcome.status, outcome.detail)
            except Exception:
                result = ("failed", "The Battle.net lookup did not finish. Nothing else was changed.")
            self.finished.put((request_id, text) + result)

        threading.Thread(target=work, name="bnet-lookup", daemon=True).start()

    def answer_finished(self):
        while True:
            try:
                request_id, text, status, detail = self.finished.get_nowait()
            except queue.Empty:
                return
            self.bridge.report(request_id, status, detail)
            self._note(text, {"done": "done", "rejected": "refused"}.get(status, status), detail)
