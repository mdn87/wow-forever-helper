"""Bounded outcome references and explicit user actions, never transcript copies."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid

from .chat import ChatError, write_json
from .window_state import LayoutLock

MAX_EVENTS = 500
MAX_ACTIONS = 1000
MAX_BYTES = 1_500_000
LABELS = {"received": "Reply received", "completed": "Reply complete",
          "research": "Research finished", "failed": "Request failed",
          "cancelled": "Request cancelled", "interrupted": "Request interrupted"}
_lock = threading.RLock()


def _timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 4_102_444_800


def _id(value):
    return isinstance(value, str) and str(uuid.UUID(value)) == value


def _valid_source(source):
    if not isinstance(source, dict):
        return False
    if source.get("type") == "chat":
        return (set(source) == {"type", "provider", "session_id", "request_id"}
                and source["provider"] in {"codex", "claude"}
                and _id(source["session_id"]) and _id(source["request_id"]))
    return (set(source) == {"type", "key", "attempt"} and source.get("type") == "research"
            and isinstance(source["key"], str) and len(source["key"]) == 64
            and all(c in "0123456789abcdef" for c in source["key"]) and _id(source["attempt"]))


def event_id(source, outcome):
    return hashlib.sha256(json.dumps([source, outcome], sort_keys=True).encode()).hexdigest()


class ActivityHistory:
    def __init__(self, storage=None):
        self.path = Path(storage) / "activity-history.json" if storage is not None else None
        self.memory = self.empty()

    @staticmethod
    def empty():
        return {"version": 1, "floor": 0, "events": [], "actions": []}

    def load(self):
        if self.path is None:
            return deepcopy(self.memory)
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return self.empty()
        except OSError:
            raise ChatError("Activity history could not be read. Its file is kept.") from None
        try:
            data = json.loads(raw)
            if (len(raw) > MAX_BYTES or not isinstance(data, dict)
                    or set(data) != {"version", "floor", "events", "actions"}
                    or type(data["version"]) is not int or data["version"] != 1 or not _timestamp(data["floor"])
                    or not isinstance(data["events"], list) or len(data["events"]) > MAX_EVENTS
                    or not isinstance(data["actions"], list) or len(data["actions"]) > MAX_ACTIONS):
                raise ValueError
            ids = set()
            for e in data["events"]:
                if (set(e) != {"id", "at", "outcome", "title", "source", "read", "dismissed"}
                        or e["outcome"] not in LABELS or not _valid_source(e["source"])
                        or e["id"] != event_id(e["source"], e["outcome"]) or e["id"] in ids
                        or not _timestamp(e["at"]) or not isinstance(e["title"], str)
                        or len(e["title"]) > 160 or "\0" in e["title"]
                        or type(e["read"]) is not bool or type(e["dismissed"]) is not bool):
                    raise ValueError
                ids.add(e["id"])
            for a in data["actions"]:
                if (set(a) != {"event", "action", "at"} or a["event"] not in ids
                        or a["action"] not in {"read", "dismiss", "restore", "retry"}
                        or not _timestamp(a["at"])):
                    raise ValueError
            return data
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
            raise ChatError("Activity history is unreadable. Its existing file is kept.") from None

    @contextmanager
    def editing(self):
        with _lock:
            lock = None
            try:
                if self.path:
                    lock = LayoutLock(self.path)
                data = self.load()
                yield data
            except OSError:
                raise ChatError("Activity history could not be saved. Try again when local storage is available.") from None
            finally:
                if lock:
                    lock.close()

    def save(self, data):
        if self.path:
            write_json(self.path, data)
        else:
            self.memory = deepcopy(data)

    def record(self, source, outcome, title, at):
        try:
            valid = _valid_source(source)
        except (ValueError, TypeError, AttributeError, KeyError):
            valid = False
        if not valid or outcome not in LABELS or not _timestamp(at):
            raise ChatError("That activity reference is invalid.")
        key = event_id(source, outcome)
        with self.editing() as data:
            if any(e["id"] == key for e in data["events"]) or at <= data["floor"]:
                return key
            data["events"].append({"id": key, "at": at, "outcome": outcome,
                                   "title": str(title).replace("\0", "")[:160], "source": deepcopy(source),
                                   "read": False, "dismissed": False})
            data["events"].sort(key=lambda e: (e["at"], e["id"]))
            if len(data["events"]) > MAX_EVENTS:
                # Keep a time boundary so old receipts cannot resurrect evicted notices.
                data["floor"] = data["events"][-MAX_EVENTS - 1]["at"]
                data["events"] = data["events"][-MAX_EVENTS:]
            ids = {e["id"] for e in data["events"]}
            data["actions"] = [a for a in data["actions"] if a["event"] in ids]
            self.save(data)
        return key

    def act(self, key, action):
        if action not in {"read", "dismiss", "restore", "retry"}:
            raise ChatError("That activity action is unavailable.")
        with self.editing() as data:
            event = next((e for e in data["events"] if e["id"] == key), None)
            if event is None:
                raise ChatError("That activity has left the retained history. Refresh the list.")
            if action == "read":
                if event["read"]:
                    return
                event["read"] = True
            elif action in {"dismiss", "restore"}:
                value = action == "dismiss"
                if event["dismissed"] == value:
                    return
                event["dismissed"] = value
            data["actions"] = (data["actions"] + [{"event": key, "action": action, "at": time.time()}])[-MAX_ACTIONS:]
            self.save(data)

    def entries(self, dismissed=False):
        return [e for e in reversed(self.load()["events"]) if dismissed or not e["dismissed"]]
