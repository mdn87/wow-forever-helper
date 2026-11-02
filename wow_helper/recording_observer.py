"""Explicit, bounded recording measurements; source files are never modified.

Names and paths stay internal. Quiet metadata is only a probe candidate, never
proof that NVIDIA (or another recorder) has stopped or finalized a file.
"""

import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import time

from .chat import ChatError
from .codex_chat import process_options

MEDIA_SUFFIXES = frozenset({".mp4", ".mov", ".mkv"})
MAX_ENTRIES = 2048
MAX_FILES = 64
MAX_EVENTS = 256
MAX_PROBES = 8
MAX_PROBE_OUTPUT = 32_000


def fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def regular_stat(path):
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise OSError
    return info


def probe_format(path, expected, *, timeout, executable=None):
    """Read bounded format/stream metadata after quiescence; export no frames.

    Callers must establish quiescence first. A before/after metadata check detects
    observed changes during the probe; an unchanged result still proves no finalization.
    """
    result = {"status": "unavailable", "finalization": "unverified"}
    if executable is None:
        return result
    try:
        if fingerprint(regular_stat(path)) != expected:
            return {**result, "status": "changed_before_probe"}
        command = [executable, "-v", "error", "-protocol_whitelist", "file",
                   "-format_whitelist", "mov,matroska", "-max_streams", "16", "-probesize", "1048576",
                   "-analyzeduration", "1000000", "-read_intervals", "%+1",
                   "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, **process_options())
    except OSError:
        return {**result, "status": "unavailable"}
    output = {}

    def read_output():
        try:
            raw = process.stdout.read(MAX_PROBE_OUTPUT + 1)
            output["raw"] = raw
            if len(raw) > MAX_PROBE_OUTPUT:
                process.kill()
        except (OSError, ValueError):
            output["failed"] = True

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        try:
            process.wait(timeout=timeout)
            result["status"] = "returned"
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                result["status"] = "worker_not_exited"
        reader.join(timeout=1)
        if not reader.is_alive():
            process.stdout.close()
    if result["status"] != "returned":
        return result
    raw = output.get("raw", b"")
    if reader.is_alive() or output.get("failed") or len(raw) > MAX_PROBE_OUTPUT:
        return {**result, "status": "output_limit_or_unavailable"}
    try:
        if fingerprint(regular_stat(path)) != expected:
            return {**result, "status": "changed_during_probe"}
        if process.returncode != 0:
            return {**result, "status": "unreadable"}
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
            raise ValueError
        duration = data.get("format", {}).get("duration")
        try:
            duration = float(duration)
            if not math.isfinite(duration) or duration < 0:
                duration = None
        except (TypeError, ValueError, OverflowError):
            duration = None
        return {**result, "status": "metadata_readable", "duration_seconds": duration,
                "video_stream": any(isinstance(item, dict) and item.get("codec_type") == "video"
                                    for item in data["streams"])}
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return {**result, "status": "unreadable"}


class RecordingObserver:
    """A single selected directory, bounded aliases and transition history."""

    def __init__(self, directory, *, quiet_seconds=10, probe=False, clock=time.monotonic):
        try:
            selected = Path(directory)
            if os.name == "nt" and selected.anchor.startswith("\\\\"):
                raise OSError
            if selected.is_symlink() or not selected.is_dir():
                raise OSError
            self.directory = selected.resolve()
            if os.name == "nt" and self.directory.anchor.startswith("\\\\"):
                raise OSError
            info = self.directory.stat(follow_symlinks=False)
            self.directory_identity = info.st_dev, info.st_ino
        except (OSError, ValueError, TypeError, RuntimeError):
            raise ChatError("Choose an accessible local recording directory. No source files were changed.") from None
        if type(quiet_seconds) is not int or not 2 <= quiet_seconds <= 300 or type(probe) is not bool:
            raise ChatError("Choose a quiet period of 2 to 300 seconds and an explicit format-probe setting.")
        self.clock = clock
        self.origin = clock()
        self.quiet_seconds = quiet_seconds
        self.probe_enabled = probe
        self.executable = shutil.which("ffprobe") if probe else None
        self.records = []
        self.current = {}
        self.events = []
        self.dropped_events = 0
        self.probes = 0
        self.probe_history = []
        self.polls = 0
        self.skipped_entries = 0
        self.finished_reason = None
        self.initial_free_bytes = self._free_bytes()

    def _free_bytes(self):
        try:
            return shutil.disk_usage(self.directory).free
        except OSError:
            return None

    def _event(self, record, state, now):
        record["state"] = state
        event = {"file_id": record["file_id"], "elapsed_seconds": round(now - self.origin, 3),
                 "state": state, "bytes": record["last_bytes"]}
        if len(self.events) < MAX_EVENTS:
            self.events.append(event)
        else:
            self.dropped_events += 1

    def poll(self, *, deadline=None):
        """Scan metadata, then optionally probe quiet files; never write sources."""
        if self.finished_reason:
            return
        now, seen = self.clock(), set()
        self.polls += 1
        try:
            info = self.directory.stat(follow_symlinks=False)
            if (not stat.S_ISDIR(info.st_mode) or self.directory.is_symlink()
                    or (info.st_dev, info.st_ino) != self.directory_identity):
                self.finished_reason = "directory_changed"
                return
            with os.scandir(self.directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_ENTRIES:
                        self.finished_reason = "directory_entry_limit"
                        return
                    if Path(entry.name).suffix.lower() not in MEDIA_SUFFIXES:
                        continue
                    try:
                        # DirEntry.stat() zeroes st_dev/st_ino on Windows; identity needs os.stat.
                        info = os.stat(entry.path, follow_symlinks=False)
                        if entry.is_symlink() or not stat.S_ISREG(info.st_mode):
                            continue
                    except OSError:
                        self.skipped_entries += 1
                        continue
                    seen.add(entry.name)
                    tag = fingerprint(info)
                    record = self.current.get(entry.name)
                    if record is not None and record["_identity"] != tag[:2]:
                        self._event(record, "replaced", now)
                        record = None
                    if record is None:
                        if len(self.records) >= MAX_FILES:
                            self.finished_reason = "file_limit"
                            return
                        record = {"file_id": "recording-" + str(len(self.records) + 1).zfill(3),
                                  "first_bytes": info.st_size, "last_bytes": info.st_size,
                                  "first_seen_seconds": round(now - self.origin, 3),
                                  "last_seen_seconds": round(now - self.origin, 3),
                                  "last_change_seconds": round(now - self.origin, 3),
                                  "observed_growth_bytes": 0, "max_interval_bytes_per_second": 0,
                                  "changes": 0, "state": "observed", "format_probe": {"status": "not_attempted"},
                                  "_identity": tag[:2], "_tag": tag, "_last_poll": now,
                                  "_last_change": now, "_probe_tag": None, "_path": Path(entry.path)}
                        self.records.append(record)
                        self.current[entry.name] = record
                        self._event(record, "observed", now)
                    elif record["_tag"] != tag:
                        growth = max(0, info.st_size - record["last_bytes"])
                        elapsed = now - record["_last_poll"]
                        rate = growth / elapsed if elapsed > 0 else 0
                        record["observed_growth_bytes"] += growth
                        record["max_interval_bytes_per_second"] = max(record["max_interval_bytes_per_second"], round(rate, 3))
                        record["changes"] += 1
                        record["last_bytes"] = info.st_size
                        record["_tag"] = tag
                        record["_last_change"] = now
                        record["last_change_seconds"] = round(now - self.origin, 3)
                        record["format_probe"] = {"status": "not_attempted"}
                        self._event(record, "growing" if growth else "changed", now)
                    elif now - record["_last_change"] >= self.quiet_seconds:
                        if record["state"] != "quiescent_candidate":
                            self._event(record, "quiescent_candidate", now)
                    elif record["state"] not in {"observed", "waiting_for_quiescence"}:
                        self._event(record, "waiting_for_quiescence", now)
                    record["_last_poll"] = now
                    record["last_seen_seconds"] = round(now - self.origin, 3)
            for name in set(self.current) - seen:
                self._event(self.current.pop(name), "removed_or_unreadable", now)
        except OSError:
            self.finished_reason = "directory_unavailable"
            return
        # Release the directory iterator before any optional subprocess work.
        for record in self.current.values():
            remaining = (deadline - self.clock()) if deadline is not None else 3
            if remaining <= 0 or self.probes >= MAX_PROBES:
                break
            if (self.probe_enabled and record["state"] == "quiescent_candidate"
                    and record["_probe_tag"] != record["_tag"]):
                record["_probe_tag"] = record["_tag"]
                self.probes += 1
                record["format_probe"] = probe_format(record["_path"], record["_tag"],
                                                       timeout=min(3, remaining), executable=self.executable)
                self.probe_history.append({"file_id": record["file_id"],
                                           "elapsed_seconds": round(self.clock() - self.origin, 3),
                                           "bytes": record["last_bytes"], "result": dict(record["format_probe"])})
                if record["format_probe"]["status"] == "worker_not_exited":
                    self.finished_reason = "probe_worker_not_exited"
                    break

    def report(self):
        status = "observed" if self.finished_reason in {None, "duration_complete", "user_stopped"} else "partial"
        return {"version": 1, "status": status, "finished_reason": self.finished_reason,
                "elapsed_seconds": round(self.clock() - self.origin, 3), "polls": self.polls,
                "quiet_seconds": self.quiet_seconds, "format_probe_enabled": self.probe_enabled,
                "format_probe_available": self.executable is not None, "probe_attempts": self.probes,
                "format_probes": list(self.probe_history),
                "initial_free_bytes": self.initial_free_bytes, "final_free_bytes": self._free_bytes(),
                "skipped_entries": self.skipped_entries, "dropped_events": self.dropped_events,
                "finalization": "unverified", "identity": "filesystem metadata only",
                "files": [{key: value for key, value in record.items() if not key.startswith("_")}
                          for record in self.records], "events": list(self.events)}


def observe(directory, *, seconds=60, interval=2, quiet_seconds=10, probe=False):
    if type(seconds) is not int or not 1 <= seconds <= 3600 or type(interval) is not int or not 1 <= interval <= 60:
        raise ChatError("Choose an observation duration of 1 to 3,600 seconds and an interval of 1 to 60 seconds.")
    if type(quiet_seconds) is not int or quiet_seconds < 2 * interval:
        raise ChatError("The quiet period must span at least two observation intervals.")
    observer = RecordingObserver(directory, quiet_seconds=quiet_seconds, probe=probe)
    deadline = observer.origin + seconds
    try:
        while observer.clock() < deadline and observer.finished_reason is None:
            observer.poll(deadline=deadline)
            delay = min(interval, max(0, deadline - observer.clock()))
            if delay and observer.finished_reason is None:
                time.sleep(delay)
        if observer.finished_reason is None:
            observer.finished_reason = "duration_complete"
    except KeyboardInterrupt:
        observer.finished_reason = "user_stopped"
    return observer.report()
