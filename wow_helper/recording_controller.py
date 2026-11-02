"""Explicit lifecycle ownership for F19 logs, with no native capture loop.

A future backend must finish each ticket only after its worker exits, including
cancelled work. Pause/stop invalidate results but never pretend a worker exited.
"""

from dataclasses import dataclass
from copy import deepcopy
import threading
import time
import uuid

from .chat import ChatError
from .recording_log import (DEFAULT_ROOT, MAX_SAMPLE_BYTES, GAP_REASONS,
                            LogStore, StoragePolicy, next_state, number)


@dataclass(frozen=True)
class CaptureTicket:
    run_id: str
    generation: int
    request_id: str


class RecordingController:
    """One process owner per log; all public operations serialize locally."""

    def __init__(self, store, *, clock=time.time, monotonic=time.monotonic):
        self._store = store
        self._clock = clock
        self._monotonic = monotonic
        self._origin = number(monotonic())
        self._run_id = str(uuid.uuid4())
        self._generation = 0
        self._pending = None
        self._closed = False
        self._fault = False
        self._mutex = threading.RLock()
        self._data = {"version": 1, "id": store.path.name, "state": None, "events": []}
        self._state = None
        self.recovery = {"complete_events": 0, "orphan_files": 0,
                         "unfinished_writes": 0, "interrupted": False, "pause_saved": None}

    @classmethod
    def create(cls, *, root=DEFAULT_ROOT, policy=None, clock=time.time,
               monotonic=time.monotonic, free_space=None):
        """Create a ready log. Creation itself starts no capture or recording."""
        store = LogStore(root, str(uuid.uuid4()), policy or StoragePolicy(),
                         free_space=free_space, create=True)
        try:
            controller = cls(store, clock=clock, monotonic=monotonic)
            controller._append("created", {})
            return controller
        except Exception:
            store.close()
            raise

    @classmethod
    def open(cls, log_id, *, root=DEFAULT_ROOT, policy=None, clock=time.time,
             monotonic=time.monotonic, free_space=None):
        """Recover complete snapshots; interrupted runs require explicit resume."""
        store = LogStore(root, log_id, policy or StoragePolicy(), free_space=free_space)
        try:
            controller = cls(store, clock=clock, monotonic=monotonic)
            controller._data, controller.recovery = store.load()
            controller._state = controller._data["state"]
            controller.recovery["pause_saved"] = None
            if controller.recovery["interrupted"]:
                try:
                    controller._append("recovered", {})
                    controller.recovery["pause_saved"] = True
                except ChatError:
                    # Full storage must still allow inspection of complete events.
                    # _append has disabled writes and paused the in-memory owner.
                    controller.recovery["pause_saved"] = False
            return controller
        except Exception:
            store.close()
            raise

    @property
    def log_id(self):
        return self._data["id"]

    def status(self):
        with self._mutex:
            return {"log_id": self.log_id, "state": self._state,
                    "last_confirmed_state": self._data["state"], "closed": self._closed,
                    "write_failed": self._fault, "worker_pending": self._pending is not None,
                    "complete_events": len(self._data["events"]),
                    "recovery": dict(self.recovery)}

    def _usable(self):
        if self._closed:
            raise ChatError("This recording-log controller is closed.")
        if self._fault:
            raise ChatError("Recording-log writes failed. Close and reopen the log before resuming; existing files are kept.")

    def events(self, *, after=0, limit=100):
        """Read a bounded copy of complete events; no provider is contacted."""
        with self._mutex:
            if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
                raise ChatError("Choose a nonnegative event offset and a page of 1 to 1,000 events.")
            return deepcopy(self._data["events"][after:after + limit])

    def _append(self, kind, detail, sample=None):
        self._usable()
        try:
            state = next_state(self._data["state"], kind, detail)
            elapsed = number(self._monotonic() - self._origin)
            if self._data["events"] and self._data["events"][-1]["run_id"] == self._run_id:
                elapsed = max(elapsed, self._data["events"][-1]["elapsed"])
            event = {"seq": len(self._data["events"]) + 1, "at": number(self._clock()),
                     "run_id": self._run_id, "elapsed": elapsed, "kind": kind, "detail": detail}
            data = {**self._data, "state": state, "events": self._data["events"] + [event]}
            self._store.commit(data, sample)
        except (OSError, ValueError, TypeError, OverflowError, ChatError) as exc:
            # Atomic replace may have completed before an I/O failure surfaced.
            # Never retry the event, reuse its sequence, or overwrite from memory.
            self._fault = True
            self._state = "paused"
            self._generation += 1
            if isinstance(exc, ChatError):
                raise
            raise ChatError("Recording-log writing failed. Existing files are kept; close and reopen the log.") from None
        self._data = data
        self._state = state

    def start(self, *, source_available=False):
        with self._mutex:
            self._usable()
            if self._state != "ready" or type(source_available) is not bool:
                raise ChatError("Only a ready log can start, with an explicit source-availability value.")
            self._append("started", {"source_available": source_available})
            return self.status()

    def resume(self, *, source_available=False):
        with self._mutex:
            self._usable()
            if self._state != "paused" or type(source_available) is not bool:
                raise ChatError("Only a paused log can resume, with an explicit source-availability value.")
            self._append("resumed", {"source_available": source_available})
            return self.status()

    def pause(self):
        with self._mutex:
            self._usable()
            if self._state == "paused":
                return self.status()
            if self._state not in {"recording", "unavailable"}:
                raise ChatError("Start the log before pausing it.")
            self._generation += 1
            self._append("paused", {})
            return self.status()

    def source_changed(self, available):
        with self._mutex:
            self._usable()
            if type(available) is not bool:
                raise ChatError("Source availability must be true or false.")
            if self._state == "recording" and not available:
                self._generation += 1
                self._append("source_unavailable", {})
            elif self._state == "unavailable" and available:
                self._append("source_available", {})
            # Source recovery cannot undo a deliberate user pause.
            return self.status()

    def stop(self):
        with self._mutex:
            if self._closed:
                raise ChatError("This recording-log controller is closed.")
            self._generation += 1
            if self._fault:
                self._state = "stopped"
            elif self._state != "stopped":
                try:
                    self._append("stopped", {})
                finally:
                    if self._fault:
                        self._state = "stopped"
            return self.status()

    def begin_capture(self):
        """Reserve one worker slot. This method launches no worker."""
        with self._mutex:
            self._usable()
            if self._state != "recording":
                raise ChatError("Capture requires an explicitly running log and an available source.")
            if self._pending is not None:
                raise ChatError("The previous capture worker has not exited yet.")
            self._pending = CaptureTicket(self._run_id, self._generation, str(uuid.uuid4()))
            return self._pending

    def finish_capture(self, ticket, sample=None, *, captured_at=None):
        """Call after worker exit. Return true only for a committed sample.

        Sample bytes are opaque, local, immutable data (1..8 MB); image decoding,
        masking, encoding, provider publication, and scheduling belong to stage 2.
        None records a failed-capture gap. Invalidated results are discarded.
        """
        with self._mutex:
            if ticket is not self._pending or ticket is None:
                return False
            self._pending = None
            try:
                if self._closed or self._fault or self._state != "recording" or ticket.generation != self._generation:
                    return False
                if sample is None:
                    self._append("gap", {"reason": "capture_failed"})
                    return False
                try:
                    if type(sample) is not bytes or not 1 <= len(sample) <= MAX_SAMPLE_BYTES:
                        raise ValueError
                    if captured_at is not None:
                        number(captured_at)
                except (ValueError, TypeError, OverflowError):
                    self._append("gap", {"reason": "capture_failed"})
                    raise ChatError("That sample or capture time is invalid. The failed capture is recorded as a gap.") from None
                self._append("sample", {"media_id": str(uuid.uuid4()), "bytes": len(sample),
                                        "captured_at": captured_at}, sample)
                return True
            finally:
                if self._closed:
                    self._store.close()

    def gap(self, reason="missed_interval"):
        with self._mutex:
            self._usable()
            if not isinstance(reason, str) or reason not in GAP_REASONS or self._state != "recording":
                raise ChatError("A running log accepts only a missed-interval or failed-capture gap.")
            self._append("gap", {"reason": reason})

    def storage_report(self):
        with self._mutex:
            if self._closed:
                raise ChatError("This recording-log controller is closed.")
            try:
                from .recording_log import encoded
                return self._store.capacity(len(encoded(self._data)))
            except OSError:
                raise ChatError("Recording-log storage information is unavailable.") from None

    def close(self):
        """Release the lifetime lock after the outstanding worker has exited.

        Closing a running log preserves its interrupted state on disk. Reopening
        pauses it; closing never silently resumes or finalizes a recording.
        """
        with self._mutex:
            self._closed = True
            self._generation += 1
            if self._pending is None:
                self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
