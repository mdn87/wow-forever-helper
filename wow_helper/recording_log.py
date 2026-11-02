"""F19 foundation: bounded private logs; no capture backend or provider access.

All mutations belong to RecordingController. Snapshots replace atomically and
sample files commit first. Interrupted writes and unreferenced samples are kept.
"""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import uuid

from .chat import ROOT, ChatError
from .window_state import LayoutLock

DEFAULT_ROOT = ROOT / ".runtime" / "recording-logs"
MAX_INDEX_BYTES = 4_000_000
MAX_SAMPLE_BYTES = 8_000_000
MAX_EVENTS = 10_000
MAX_FILES = 20_100
STATES = frozenset({"ready", "recording", "unavailable", "paused", "stopped"})
GAP_REASONS = frozenset({"missed_interval", "capture_failed"})


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError
    return value


def integer(value, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError
    return value


@dataclass(frozen=True)
class StoragePolicy:
    """Budget for this log's volume, including expected external video growth."""

    max_log_bytes: int = 256_000_000
    reserve_bytes: int = 1_000_000_000
    external_bytes_per_second: int = 0
    horizon_seconds: int = 600

    def __post_init__(self):
        integer(self.max_log_bytes, MAX_INDEX_BYTES, 2**50)
        integer(self.reserve_bytes)
        integer(self.external_bytes_per_second)
        integer(self.horizon_seconds, 0, 86_400)


def volume_budget(*, free_bytes, pending_bytes, reserve_bytes,
                  external_bytes_per_second=0, horizon_seconds=600):
    """Evaluate one volume. Call separately for external video on another volume.

    External growth is a supplied estimate, never a recording-state claim.
    This function neither reads video content nor controls another recorder.
    """
    for value in (free_bytes, pending_bytes, reserve_bytes, external_bytes_per_second):
        integer(value)
    integer(horizon_seconds, 0, 86_400)
    projected = external_bytes_per_second * horizon_seconds
    required = pending_bytes + reserve_bytes + projected
    return {"free_bytes": free_bytes, "pending_bytes": pending_bytes,
            "reserve_bytes": reserve_bytes, "projected_external_bytes": projected,
            "required_bytes": required, "allowed": free_bytes >= required}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def next_state(state, kind, detail):
    """Validate an event and replay its lifecycle transition."""
    if not isinstance(detail, dict):
        raise ValueError
    if kind == "created" and state is None and detail == {}:
        return "ready"
    if kind in {"started", "resumed"}:
        expected = "ready" if kind == "started" else "paused"
        if state != expected or set(detail) != {"source_available"} or type(detail["source_available"]) is not bool:
            raise ValueError
        return "recording" if detail["source_available"] else "unavailable"
    if kind == "paused" and state in {"recording", "unavailable"} and detail == {}:
        return "paused"
    if kind == "stopped" and state in STATES - {"stopped"} and detail == {}:
        return "stopped"
    if kind == "source_unavailable" and state == "recording" and detail == {}:
        return "unavailable"
    if kind == "source_available" and state == "unavailable" and detail == {}:
        return "recording"
    if kind == "recovered" and state in {"recording", "unavailable"} and detail == {}:
        return "paused"
    if kind == "gap" and state == "recording" and set(detail) == {"reason"} and detail["reason"] in GAP_REASONS:
        return state
    if kind == "sample" and state == "recording" and set(detail) == {"media_id", "bytes", "captured_at"}:
        identifier(detail["media_id"])
        integer(detail["bytes"], 1, MAX_SAMPLE_BYTES)
        if detail["captured_at"] is not None:
            number(detail["captured_at"])
        return state
    raise ValueError


class LogStore:
    """A private log with an OS-released lifetime lock and strict reader."""

    def __init__(self, root, log_id, policy, *, free_space=None, create=False):
        self.lock = None
        self.policy = policy
        self.free_space = free_space or (lambda path: shutil.disk_usage(path).free)
        try:
            if not isinstance(policy, StoragePolicy):
                raise ValueError
            identifier(log_id)
            self.root = Path(root).resolve()
            # External bulk destinations require a later explicit destination flow.
            runtime = (ROOT / ".runtime").resolve()
            if not runtime.is_relative_to(ROOT.resolve()) or not self.root.is_relative_to(runtime):
                raise ChatError("Choose a recording-log directory inside this project's ignored runtime directory.")
            self.path = self.root / log_id
            self._safe(self.path)
            if create:
                self.path.mkdir(parents=True, exist_ok=False)
            elif not self.path.is_dir():
                raise ChatError("That recording log is unavailable. No new log was created.")
            self._safe(self.path)
            self.file("owner.lock")
            try:
                self.lock = LayoutLock(self.path / "owner")
            except ChatError:
                raise ChatError("This recording log is already open in another controller.") from None
        except (OSError, ValueError, TypeError):
            self.close()
            raise ChatError("The recording log could not be opened. Existing files are kept.") from None

    def _safe(self, path):
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise ChatError("The recording log contains an unsupported file link. Existing files are kept.")

    def file(self, name):
        if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."} or "\\" in name:
            raise ChatError("The recording-log filename is invalid.")
        path = self.path / name
        self._safe(self.path)
        self._safe(path)
        return path

    def accounting(self):
        sizes = {"index_bytes": 0, "media_bytes": 0, "other_bytes": 0}
        count = 0
        for path in self.path.iterdir():
            count += 1
            if count > MAX_FILES:
                raise ChatError("The recording log has too many files. Existing files are kept.")
            self._safe(path)
            if not path.is_file():
                raise ChatError("The recording log contains an unsupported entry. Existing files are kept.")
            key = "index_bytes" if path.name == "index.json" else "media_bytes" if path.name.startswith("sample-") and path.suffix == ".bin" else "other_bytes"
            sizes[key] += path.stat().st_size
        return {**sizes, "total_bytes": sum(sizes.values()), "file_count": count}

    def capacity(self, index_bytes, sample_bytes=0):
        usage = self.accounting()
        if usage["file_count"] > MAX_FILES - 3:
            raise ChatError("The recording log has too many files. Existing files are kept.")
        projected = usage["total_bytes"] - usage["index_bytes"] + index_bytes + sample_bytes
        if projected > self.policy.max_log_bytes:
            raise ChatError("The recording log reached its storage budget. Existing data is kept.")
        # Both the old and replacement index exist during an atomic write.
        space = volume_budget(free_bytes=self.free_space(self.path),
                              pending_bytes=index_bytes + sample_bytes,
                              reserve_bytes=self.policy.reserve_bytes,
                              external_bytes_per_second=self.policy.external_bytes_per_second,
                              horizon_seconds=self.policy.horizon_seconds)
        if not space["allowed"]:
            raise ChatError("The recording-log volume lacks its required free-space reserve. Existing data is kept.")
        return {**usage, **space, "projected_log_bytes": projected}

    def write_atomic(self, name, raw):
        destination = self.file(name)
        temporary = self.file("write-" + str(uuid.uuid4()) + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if os.name != "nt":
            descriptor = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        # Preserve the temporary if any operation fails; recovery reports it.

    def commit(self, data, sample=None):
        raw = encoded(data)
        if len(raw) > MAX_INDEX_BYTES or len(data["events"]) > MAX_EVENTS:
            raise ChatError("The recording log reached its event limit. Existing data is kept.")
        self.capacity(len(raw), len(sample) if sample is not None else 0)
        if sample is not None:
            media = data["events"][-1]["detail"]["media_id"]
            destination = self.file("sample-" + media + ".bin")
            if destination.exists():
                raise ChatError("That recording sample already exists. Existing data is kept.")
            self.write_atomic(destination.name, sample)
        self.write_atomic("index.json", raw)

    def load(self):
        """Refuse damaged/unsupported logs without repair, truncation or deletion."""
        try:
            with self.file("index.json").open("rb") as stream:
                raw = stream.read(MAX_INDEX_BYTES + 1)
            data = json.loads(raw, object_pairs_hook=unique_object)
            if (len(raw) > MAX_INDEX_BYTES or not isinstance(data, dict)
                    or set(data) != {"version", "id", "state", "events"}
                    or type(data["version"]) is not int or data["version"] != 1
                    or data["id"] != self.path.name or not isinstance(data["events"], list)
                    or not 1 <= len(data["events"]) <= MAX_EVENTS):
                raise ValueError
            state, media_ids, runs, last_elapsed = None, set(), set(), {}
            for seq, event in enumerate(data["events"], 1):
                if not isinstance(event, dict) or set(event) != {"seq", "at", "run_id", "elapsed", "kind", "detail"}:
                    raise ValueError
                integer(event["seq"], seq, seq)
                number(event["at"])
                identifier(event["run_id"])
                elapsed = number(event["elapsed"])
                run = event["run_id"]
                if elapsed < last_elapsed.get(run, 0):
                    raise ValueError
                # A process run cannot disappear and later rejoin the history.
                if run in runs and run != data["events"][seq - 2]["run_id"]:
                    raise ValueError
                runs.add(run)
                last_elapsed[run] = elapsed
                state = next_state(state, event["kind"], event["detail"])
                if event["kind"] == "sample":
                    detail = event["detail"]
                    media = detail["media_id"]
                    if media in media_ids:
                        raise ValueError
                    media_ids.add(media)
                    if self.file("sample-" + media + ".bin").stat().st_size != detail["bytes"]:
                        raise ValueError
            if data["state"] != state:
                raise ValueError
            inventory = self.accounting()
            if inventory["total_bytes"] > self.policy.max_log_bytes:
                raise ChatError("This recording log exceeds the selected budget. Existing data is kept.")
            orphans, unfinished = 0, 0
            referenced = {"sample-" + media + ".bin" for media in media_ids}
            for path in self.path.iterdir():
                if path.name in {"index.json", "owner.lock"}:
                    continue
                if path.name.endswith(".tmp"):
                    unfinished += 1
                elif path.name not in referenced:
                    orphans += 1
            return data, {"complete_events": len(data["events"]), "orphan_files": orphans,
                          "unfinished_writes": unfinished, "interrupted": state in {"recording", "unavailable"}}
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
            raise ChatError("The recording log is incomplete, damaged, or unsupported. Existing files are kept.") from None

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None
