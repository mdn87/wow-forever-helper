"""Synthetic F19 stage-one fakes: clock, free space, capture worker, writer, ffprobe.

Every value here is synthetic. Nothing launches a real capture, recorder or
ffprobe; tests inject these through the existing clock, free-space and
store-writer seams.
"""

import io
import os
from pathlib import Path
import subprocess
import uuid

from wow_helper import recording_log


def isolated_log_root(monkeypatch, tmp_path):
    """Point the store's project-runtime guard at a temporary project root."""
    monkeypatch.setattr(recording_log, "ROOT", tmp_path)
    return tmp_path / ".runtime" / "recording-logs"


class FakeClock:
    """Injected wall and monotonic clocks; sleep advances both."""

    def __init__(self, wall=1_700_000_000.0, monotonic=500.0, on_sleep=None):
        self.wall = wall
        self.mono = monotonic
        self.on_sleep = on_sleep
        self.sleeps = []

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds)
        if self.on_sleep is not None:
            self.on_sleep(self)


class FakeFreeSpace:
    """Injected free-space reader. Records queried paths; can fail."""

    def __init__(self, free_bytes=10**13):
        self.free_bytes = free_bytes
        self.error = None
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.free_bytes


class FakeCaptureRunner:
    """A synthetic capture worker that respects the one-ticket contract.

    `launch()` reserves the controller's worker slot; `exit()` reports the
    worker's result after it "exits". Each queued result is bytes (a sample),
    None (capture failed) or anything else (passed through unchanged, e.g. an
    invalid sample). The runner never retries or replays a result.
    """

    def __init__(self, controller, results=()):
        self.controller = controller
        self.results = list(results)
        self.ticket = None
        self.delivered = []

    def launch(self):
        self.ticket = self.controller.begin_capture()
        return self.ticket

    def exit(self, captured_at=None):
        ticket, self.ticket = self.ticket, None
        result = self.results.pop(0) if self.results else None
        accepted = self.controller.finish_capture(ticket, result, captured_at=captured_at)
        self.delivered.append((result, accepted))
        return accepted

    def capture(self, captured_at=None):
        self.launch()
        return self.exit(captured_at)


class FakeWriter:
    """Replaces one store's atomic writer to record order and inject faults.

    `fail` selects a destination name; `stage` chooses the failure point:
    "before_temp" (nothing written), "after_temp" (an interrupted temporary
    file is left behind, as a crash before replacement would), or
    "after_replace" (the write landed but an I/O error surfaced afterward).
    """

    def __init__(self, store, fail=None, stage="after_temp", times=1):
        self.store = store
        self.original = store.write_atomic
        self.fail = fail
        self.stage = stage
        self.times = times
        self.names = []
        store.write_atomic = self

    def __call__(self, name, raw):
        self.names.append(name)
        if self.fail is None or self.times <= 0 or not self.fail(name):
            return self.original(name, raw)
        self.times -= 1
        if self.stage == "before_temp":
            raise OSError("synthetic write failure")
        if self.stage == "after_temp":
            temporary = self.store.file("write-" + str(uuid.uuid4()) + ".tmp")
            temporary.write_bytes(raw)
            raise OSError("synthetic interruption before replacement")
        self.original(name, raw)
        raise OSError("synthetic failure after replacement")


def snapshot(directory):
    """Bytes and modification times for every file except the held lock byte."""
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(Path(directory).iterdir())
            if path.is_file() and path.name != "owner.lock"}


class FakeProbeProcess:
    """A synthetic ffprobe process; nothing is executed."""

    def __init__(self, output=b"", returncode=0, hang=False, on_wait=None):
        self.stdout = io.BytesIO(output)
        self.returncode = None
        self._final = returncode
        self.hang = hang
        self.on_wait = on_wait
        self.killed = False

    def wait(self, timeout=None):
        if self.on_wait is not None:
            self.on_wait()
            self.on_wait = None
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("ffprobe", timeout)
        self.returncode = self._final if not self.killed else 1
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


class FakeProbe:
    """Popen replacement recording each command and its window options."""

    def __init__(self, *processes):
        self.processes = list(processes)
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append((list(command), options))
        if not self.processes:
            raise OSError("synthetic: no fake process queued")
        return self.processes.pop(0)


class LogHarness:
    """Creates and reopens controllers with injected clocks and free space."""

    def __init__(self, monkeypatch, tmp_path):
        self.root = isolated_log_root(monkeypatch, tmp_path)
        self.clock = FakeClock()
        self.space = FakeFreeSpace()

    def _seams(self):
        return {"root": self.root, "clock": self.clock.time,
                "monotonic": self.clock.monotonic, "free_space": self.space}

    def create(self, policy=None):
        from wow_helper.recording_controller import RecordingController
        return RecordingController.create(policy=policy, **self._seams())

    def open(self, log_id, policy=None):
        from wow_helper.recording_controller import RecordingController
        return RecordingController.open(log_id, policy=policy, **self._seams())

    def directory(self, log_id):
        return self.root / log_id

    def samples(self, log_id):
        return sorted(path.name for path in self.directory(log_id).glob("sample-*.bin"))

    def index(self, log_id):
        import json
        return json.loads((self.directory(log_id) / "index.json").read_bytes())


def expected_window_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
