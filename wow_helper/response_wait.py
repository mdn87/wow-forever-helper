"""Response tracking independent of transport delivery and transcript rendering."""

from dataclasses import dataclass, field
import math
import time
import uuid


def elapsed(started, now=None):
    seconds = max(0, int((time.time() if now is None else now) - started))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


@dataclass
class ResponseWait:
    request_id: str
    body: str
    started: float = field(default_factory=lambda: time.time())
    previous_ids: frozenset = field(default_factory=frozenset)
    user_id: str | None = None

    def snapshot(self):
        return {"request_id": self.request_id, "body": self.body, "started": self.started,
                "previous_ids": sorted(self.previous_ids)[-200:], "user_id": self.user_id}

    @classmethod
    def restore(cls, raw):
        if not isinstance(raw, dict):
            return None
        try:
            request_id = str(uuid.UUID(raw.get("request_id")))
            started = raw["started"]
            if (type(started) not in (int, float) or not math.isfinite(started)
                    or not 0 < started <= time.time() + 60 or not isinstance(raw.get("body"), str)):
                return None
        except (ValueError, TypeError, AttributeError, KeyError):
            return None
        ids = raw.get("previous_ids")
        ids = frozenset(i[:200] for i in ids[:200] if isinstance(i, str)) if isinstance(ids, list) else frozenset()
        user_id = raw.get("user_id")
        return cls(request_id, raw["body"][:6000], started, ids,
                   user_id[:200] if isinstance(user_id, str) else None)

    def observe(self, messages, status=None, claimed=()):
        """Managed turns have a completion receipt; attached CLIs expose replies only."""
        if status is not None:
            return status if status in {"completed", "acknowledged", "failed", "cancelled", "interrupted"} else None
        # Another queued request may finish and disappear before the next poll.
        # Remember its receipt so identical messages cannot later claim it again.
        self.previous_ids |= frozenset(claimed) - {self.user_id}
        if not self.user_id:
            match = next((m for m in messages if m.role == "user" and m.id not in self.previous_ids
                          and m.id not in claimed and m.text.strip() == self.body.strip()), None)
            if match:
                self.user_id = match.id
        # Require the matching outgoing message before accepting a new reply.
        # An unrelated reply from the previous turn must not end this timer.
        seen_user = False
        for message in messages:
            if message.id == self.user_id:
                seen_user = True
            elif seen_user and message.role == "assistant" and message.id not in self.previous_ids and message.text.strip():
                return "received"
        return None
