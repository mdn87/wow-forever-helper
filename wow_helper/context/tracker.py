"""Decide whether a context packet is new, a repeat, out of order, too old or from the future.

Both transports can show the same packet more than once: the clipboard keeps its text until
something else replaces it, and the pixel strip stays on screen between redraws. A reader that
acts on every sighting would act on stale facts. The addon stamps each packet with a session id
(``sid``), a sequence number that rises within the session (``seq``) and the server time it was
made (``at``); this tracker turns those into one verdict.

Checks run in this order, and only a fresh packet changes what the tracker remembers:

1. ``stale`` if the packet is older than ``max_age`` seconds;
2. ``future`` if it is dated more than ``future_slack`` seconds ahead of this computer's clock;
3. ``duplicate`` if its session has already shown this sequence number;
4. ``older`` if its session has already shown a higher one;
5. ``fresh`` otherwise. A session not seen before is fresh whatever its sequence number.

The clock comparison trusts this computer's time to within the slack. A badly wrong clock shows up
as every packet being stale or from the future, and ``Judgement.age`` reports the measured value so
that can be seen rather than guessed.
"""
from dataclasses import dataclass

from .envelope import HEX16, SEQ_MAX

VERDICTS = ("fresh", "duplicate", "older", "stale", "future")


@dataclass(frozen=True)
class Judgement:
    verdict: str
    age: int
    new_session: bool
    skipped: int | None

    @property
    def fresh(self):
        return self.verdict == "fresh"


class Tracker:
    def __init__(self, *, max_age=120, future_slack=120, remember=8):
        if max_age <= 0 or future_slack < 0 or remember < 1:
            raise ValueError("max_age and remember must be positive and future_slack must not be negative")
        self.max_age = max_age
        self.future_slack = future_slack
        self.remember = remember
        self._seen = {}

    def judge(self, envelope, now):
        """Judge one parsed packet against the clock reading ``now`` (seconds since the epoch)."""
        age = int(now - envelope.at)
        if age > self.max_age:
            return Judgement("stale", age, False, None)
        if age < -self.future_slack:
            return Judgement("future", age, False, None)
        last = self._seen.get(envelope.sid)
        if last is not None:
            if envelope.seq == last:
                return Judgement("duplicate", age, False, None)
            if envelope.seq < last:
                return Judgement("older", age, False, None)
        self._remember(envelope.sid, envelope.seq)
        return Judgement("fresh", age, last is None, None if last is None else envelope.seq - last - 1)

    def _remember(self, sid, seq):
        self._seen.pop(sid, None)
        self._seen[sid] = seq
        while len(self._seen) > self.remember:
            del self._seen[next(iter(self._seen))]

    def state(self):
        """What to save between runs: recent sessions and their last sequence numbers, oldest first."""
        return {"sessions": [[sid, seq] for sid, seq in self._seen.items()]}

    @classmethod
    def from_state(cls, state, **limits):
        """Rebuild from saved state. The file is local but not trusted, so bad entries are dropped quietly."""
        tracker = cls(**limits)
        entries = state.get("sessions") if isinstance(state, dict) else None
        if not isinstance(entries, list):
            return tracker
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            sid, seq = entry
            if not isinstance(sid, str) or not HEX16.fullmatch(sid):
                continue
            if isinstance(seq, bool) or not isinstance(seq, int) or not 1 <= seq <= SEQ_MAX:
                continue
            tracker._remember(sid, seq)
        return tracker
