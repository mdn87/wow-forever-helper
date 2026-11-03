"""File inbox for hands-free turns from Lugos Voice into one bound chat.

The protocol is documented in docs/VOICE_BRIDGE.md. The companion owns the
binding; a sender may only address the binding that is current right now.
"""

import json
import os
from pathlib import Path
import time
import uuid

from .chat import MAX_MESSAGE, ROOT, write_json

BRIDGE = ROOT / ".runtime" / "voice-bridge"
VERSION = 1
FRESH_SECONDS = 60
FUTURE_SKEW = 5
HEARTBEAT_SECONDS = 5
MAX_FILE = 64_000
BATCH = 5


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


class VoiceBridge:
    """One companion-side binding. Every request is answered once in results/."""

    def __init__(self, storage=BRIDGE, *, clock=time.time):
        self.storage, self.clock = Path(storage), clock
        self.binding = None
        self._beat = 0

    @property
    def connected(self):
        return self.binding is not None

    def connect(self, label, provider):
        binding_id = str(uuid.uuid4())
        self.binding = {"version": VERSION, "binding_id": binding_id, "label": str(label)[:80],
                        "provider": provider if provider in {"codex", "claude"} else "unknown",
                        "connected_at": self.clock(), "heartbeat": self.clock()}
        for folder in ("inbox", "claimed", "results"):
            (self.storage / folder).mkdir(parents=True, exist_ok=True)
            if folder != "inbox":
                self._prune(self.storage / folder)
        write_json(self.storage / "binding.json", self.binding)
        self._beat = self.clock()
        return binding_id

    def _prune(self, folder):
        # Receipts older than a day cannot match a fresh request; keep the folder bounded.
        cutoff = time.time() - 86_400
        for path in folder.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def disconnect(self):
        """Remove the binding only if it is still ours."""
        if self.binding is None:
            return
        path = self.storage / "binding.json"
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if current.get("binding_id") == self.binding["binding_id"]:
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass
        self.binding = None

    def heartbeat(self):
        if self.binding is not None and self.clock() - self._beat >= HEARTBEAT_SECONDS:
            self.binding["heartbeat"] = self._beat = self.clock()
            write_json(self.storage / "binding.json", self.binding)

    def report(self, request_id, status, detail=""):
        write_json(self.storage / "results" / (request_id + ".json"),
                   {"version": VERSION, "id": request_id, "status": status, "detail": str(detail)[:300], "at": self.clock()})

    def pending(self):
        """Claim up to BATCH inbox requests. Invalid ones are answered as rejected here."""
        inbox = self.storage / "inbox"
        try:
            paths = sorted(p for p in inbox.iterdir() if p.suffix == ".json")[:BATCH]
        except OSError:
            return []
        accepted = []
        for path in paths:
            request_id = _uuid(path.stem)
            message = self._read(path)
            try:
                path.unlink()
            except OSError:
                continue  # The sender is still writing or another reader owns it.
            if request_id is None or request_id != path.stem:
                continue  # No valid id to answer under.
            try:
                # Exclusive creation: a repeated id is never delivered twice, even across restarts.
                with (self.storage / "claimed" / (request_id + ".json")).open("x", encoding="utf-8") as stream:
                    json.dump({"at": self.clock()}, stream)
            except FileExistsError:
                continue
            except OSError:
                continue
            problem = self._problem(message, request_id)
            if problem:
                self.report(request_id, "rejected", problem)
            else:
                accepted.append({"id": request_id, "text": message["text"].strip()})
        return accepted

    def _read(self, path):
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE + 1)
            value = json.loads(raw) if len(raw) <= MAX_FILE else None
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def _problem(self, message, request_id):
        if message is None or message.get("id") != request_id:
            return "Malformed request."
        if self.binding is None or message.get("binding_id") != self.binding["binding_id"]:
            return "No WoW Helper chat is bound to this voice connection now."
        text = message.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE or "\0" in text:
            return f"Text must be 1 to {MAX_MESSAGE} characters."
        spoken = message.get("spoken_at")
        if not isinstance(spoken, (int, float)) or isinstance(spoken, bool):
            return "Missing spoken time."
        age = self.clock() - spoken
        if age > FRESH_SECONDS or age < -FUTURE_SKEW or spoken < self.binding["connected_at"]:
            return "The spoken turn is stale or predates this connection."
        return None


def write_request(text, *, storage=BRIDGE, spoken_at=None, request_id=None, clock=time.time):
    """Reference sender used by tests and docs. Lugos Voice has its own copy."""
    storage = Path(storage)
    try:
        binding = json.loads((storage / "binding.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if clock() - binding.get("heartbeat", 0) > 3 * HEARTBEAT_SECONDS:
        return None
    request_id = request_id or str(uuid.uuid4())
    target = storage / "inbox" / (request_id + ".json")
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps({"version": VERSION, "id": request_id, "binding_id": binding["binding_id"],
                                     "text": text, "spoken_at": clock() if spoken_at is None else spoken_at}),
                         encoding="utf-8")
    os.replace(temporary, target)
    return request_id
