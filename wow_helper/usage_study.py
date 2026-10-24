"""Explicit, time-limited local counts of named companion actions only."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

from .chat import CHAT_STATE, ChatError, write_json
from .window_state import LayoutLock

FEATURES = frozenset({"companion", "chat", "quests", "character", "screen", "journal",
                      "goals", "build", "route", "chain", "search", "layouts", "pinned",
                      "activity_history", "research"})
ACTIONS = frozenset({"start", "open", "send", "save", "update", "capture", "received",
                     "completed", "failed", "cancelled", "interrupted", "read", "dismiss",
                     "restore", "retry"})
MAX_BYTES = 500_000
_lock = threading.RLock()


class UsageStudy:
    def __init__(self, storage=CHAT_STATE, *, clock=time.time):
        self.path = Path(storage) / "usage-study.json"
        self.clock = clock

    def load(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return {"version": 1, "studies": []}
        except OSError:
            raise ChatError("Usage study could not be read. Its file is kept.") from None
        try:
            data = json.loads(raw)
            if (len(raw) > MAX_BYTES or set(data) != {"version", "studies"} or data["version"] != 1
                    or not isinstance(data["studies"], list) or len(data["studies"]) > 12):
                raise ValueError
            for study in data["studies"]:
                if (set(study) != {"started_at", "ends_at", "stopped_at", "counts"}
                        or not 0 < study["started_at"] < study["ends_at"] < 4_102_444_800
                        or study["ends_at"] - study["started_at"] > 30 * 86400
                        or study["stopped_at"] is not None and not study["started_at"] <= study["stopped_at"] <= study["ends_at"]
                        or not isinstance(study["counts"], dict) or len(study["counts"]) > 32):
                    raise ValueError
                for day, features in study["counts"].items():
                    datetime.strptime(day, "%Y-%m-%d")
                    if not isinstance(features, dict) or set(features) - FEATURES:
                        raise ValueError
                    for actions in features.values():
                        if not isinstance(actions, dict) or set(actions) - ACTIONS:
                            raise ValueError
                        if any(type(n) is not int or not 0 <= n <= 1_000_000 for n in actions.values()):
                            raise ValueError
            return data
        except (TypeError, ValueError, KeyError, AttributeError, UnicodeError, RecursionError):
            raise ChatError("Usage study is unreadable. Its existing file is kept.") from None

    @contextmanager
    def edit(self):
        with _lock:
            lock = None
            try:
                lock = LayoutLock(self.path)
                data = self.load()
                yield data
                if len(json.dumps(data).encode()) > MAX_BYTES:
                    raise ChatError("Usage study reached its storage limit. Existing data is kept.")
                write_json(self.path, data)
            finally:
                if lock:
                    lock.close()

    def start(self, days=7):
        if type(days) is not int or not 1 <= days <= 30:
            raise ChatError("Choose a testing period from 1 to 30 days.")
        with self.edit() as data:
            if data["studies"] and self.active(data["studies"][-1]):
                return self.report(data)
            if len(data["studies"]) >= 12:
                raise ChatError("Twelve studies are retained. Archive them before starting another.")
            now = self.clock()
            data["studies"].append({"started_at": now, "ends_at": now + days * 86400,
                                    "stopped_at": None, "counts": {}})
        return self.report()

    def active(self, study):
        return study["stopped_at"] is None and study["started_at"] <= self.clock() < study["ends_at"]

    def stop(self):
        with self.edit() as data:
            if data["studies"] and self.active(data["studies"][-1]):
                data["studies"][-1]["stopped_at"] = self.clock()
        return self.report()

    def hit(self, feature, action):
        # Exact allowlists prevent content, paths and identifiers entering metrics.
        if not isinstance(feature, str) or not isinstance(action, str) or feature not in FEATURES or action not in ACTIONS:
            return False
        try:
            data = self.load()
            if not data["studies"] or not self.active(data["studies"][-1]):
                return False
            with self.edit() as data:
                study = data["studies"][-1]
                if not self.active(study):
                    return False
                day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
                counts = study["counts"].setdefault(day, {}).setdefault(feature, {})
                counts[action] = min(1_000_000, counts.get(action, 0) + 1)
            return True
        except (OSError, ChatError):
            # Instrumentation must never prevent normal companion use.
            return False

    def report(self, data=None):
        data = self.load() if data is None else data
        if not data["studies"]:
            return {"status": "not_started", "instrumented_features": sorted(FEATURES)}
        study = data["studies"][-1]
        totals, days = {}, {}
        for date, features in study["counts"].items():
            for feature, actions in features.items():
                days.setdefault(feature, []).append(date)
                dest = totals.setdefault(feature, {})
                for action, count in actions.items():
                    dest[action] = dest.get(action, 0) + count
        status = "active" if self.active(study) else "stopped" if study["stopped_at"] is not None else "finished"
        return {"status": status, "started_at": study["started_at"], "ends_at": study["ends_at"],
                "stopped_at": study["stopped_at"], "day_timezone": "UTC", "totals": totals,
                "days_used": days, "daily_counts": study["counts"], "instrumented_features": sorted(FEATURES),
                "limitations": "Counts measure recorded actions, not attention, time spent, usefulness, or gameplay. Window restoration and background polls are excluded. No content or identifiers are collected."}


def record(storage, feature, action):
    if storage is not None:
        return UsageStudy(storage).hit(feature, action)
    return False
