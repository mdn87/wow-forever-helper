"""Bounded private journals with immutable source evidence and explicit updates."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import uuid

from .chat import CHAT_STATE, ChatError, write_json
from .window_state import LayoutLock

JOURNAL_MAX_BYTES = 2_000_000
EVIDENCE_MAX_BYTES = 64_000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def identifier(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ChatError("That journal or note identifier is invalid.") from None


def bounded_text(value, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or "\0" in value or (not empty and not value.strip()):
        raise ValueError
    value.encode("utf-8")


def metadata(source=None, evidence=None, next_time=None):
    """Validate before copying; never silently truncate a reviewed selection."""
    result = {}
    try:
        if source is not None:
            if (not isinstance(source, dict) or set(source) - {"provider", "session_id", "message_id", "request_id"}
                    or source.get("provider") not in {"codex", "claude"}):
                raise ValueError
            identifier(source.get("session_id"))
            for field in ("message_id", "request_id"):
                if field in source:
                    bounded_text(source[field], 200)
            if "request_id" in source:
                identifier(source["request_id"])
            result["source"] = source
        if evidence is not None:
            if not isinstance(evidence, dict) or set(evidence) - {
                "text", "edition", "prepared_at", "snapshot_at", "quest_id", "slot", "image", "gaps", "urls"
            }:
                raise ValueError
            for key in ("text", "edition", "slot", "image"):
                if key in evidence:
                    bounded_text(evidence[key], 64_000 if key == "text" else 200, empty=key == "text")
            for key in ("prepared_at", "snapshot_at"):
                value = evidence.get(key)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                    raise ValueError
            if "quest_id" in evidence and (type(evidence["quest_id"]) is not int or evidence["quest_id"] <= 0):
                raise ValueError
            for key in ("gaps", "urls"):
                if key in evidence:
                    if not isinstance(evidence[key], list) or len(evidence[key]) > 100:
                        raise ValueError
                    for value in evidence[key]:
                        bounded_text(value, 4096)
            if "image" in evidence:
                name = evidence["image"]
                if not name.endswith(".png") or name != identifier(name[:-4]) + ".png":
                    raise ValueError
            if len(encoded(evidence)) > EVIDENCE_MAX_BYTES:
                raise ChatError("Evidence exceeds 64,000 UTF-8 bytes. Review a smaller selection.")
            result["evidence"] = evidence
        if next_time is not None:
            if (not isinstance(next_time, dict) or set(next_time) != {"text", "state"}
                    or next_time["state"] not in {"open", "done"}):
                raise ValueError
            bounded_text(next_time["text"], 2000)
            result["next_time"] = next_time
        return deepcopy(result)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ChatError("The saved source or evidence is invalid. Your draft is kept.") from None


class JournalService:
    def __init__(self, storage=CHAT_STATE):
        self.storage = Path(storage)

    def path(self, journal_id):
        return self.storage / "journals" / (identifier(journal_id) + ".json")

    def load(self, journal_id):
        path = self.path(journal_id)
        try:
            with path.open("rb") as stream:
                raw = stream.read(JOURNAL_MAX_BYTES + 1)
        except FileNotFoundError:
            return {"name": "My journal", "entries": []}
        except OSError:
            raise ChatError("The journal could not be read. Its existing file has been kept.") from None
        try:
            if len(raw) > JOURNAL_MAX_BYTES:
                raise ValueError
            data = json.loads(raw)
            if (not isinstance(data, dict) or set(data) - {"version", "name", "entries"}
                    or ("version" in data and (type(data["version"]) is not int or data["version"] != 1))
                    or not isinstance(data.get("entries"), list)):
                raise ValueError
            bounded_text(data.get("name"), 80)
            seen = set()
            for index, entry in enumerate(data["entries"]):
                if not isinstance(entry, dict) or set(entry) - {"id", "at", "text", "source", "evidence", "next_time", "goal"}:
                    raise ValueError
                bounded_text(entry.get("text"), 8000)
                bounded_text(entry.get("at"), 100)
                if "id" not in entry:
                    if "version" in data:
                        raise ValueError
                    entry["id"] = str(uuid.uuid5(uuid.UUID(identifier(journal_id)),
                                                str(index) + ":" + entry["at"] + ":" + entry["text"]))
                entry["id"] = identifier(entry["id"])
                if entry["id"] in seen:
                    raise ValueError
                seen.add(entry["id"])
                metadata(entry.get("source"), entry.get("evidence"), entry.get("next_time"))
                if "goal" in entry:
                    from .goals import validate_goal
                    validate_goal(entry["goal"])
            if sum(len(e["text"]) for e in data["entries"]) > 500_000:
                raise ValueError
            return data
        except (ValueError, TypeError, UnicodeError, RecursionError, ChatError):
            raise ChatError("The journal could not be read. Its existing file has been kept.") from None

    @contextmanager
    def locked(self, journal_id):
        path = self.path(journal_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                lock = LayoutLock(path)
            except ChatError:
                raise ChatError("Another window is saving this journal. Your draft is kept; try again when it finishes.") from None
            try:
                yield path, self.load(journal_id)
            finally:
                lock.close()
        except OSError:
            raise ChatError("The note could not be saved. Your draft is still here.") from None

    def _write(self, path, data):
        data["version"] = 1
        if sum(len(e["text"]) for e in data["entries"]) > 500_000 or len(encoded(data)) > JOURNAL_MAX_BYTES:
            raise ChatError("This journal is full. Create a new journal; existing notes are kept.")
        write_json(path, data)

    def add(self, journal_id, name, text, note_id=None, *, source=None, evidence=None, next_time=None, goal=None):
        try:
            bounded_text(text, 8000)
            bounded_text(name, 80, empty=True)
        except (ValueError, UnicodeError):
            raise ChatError("Write a note between 1 and 8,000 characters and a name up to 80 characters.") from None
        note_id = identifier(note_id) if note_id is not None else str(uuid.uuid4())
        fields = {"text": text.strip(), **metadata(source, evidence, next_time)}
        if goal is not None:
            from .goals import validate_goal
            fields['goal'] = validate_goal(goal)
        with self.locked(journal_id) as (path, data):
            previous = next((e for e in data["entries"] if e["id"] == note_id), None)
            if previous:
                if {k: v for k, v in previous.items() if k not in {"id", "at"}} != fields:
                    raise ChatError("This note was already saved with different text or metadata. Your draft is kept; start a new note.")
                return data
            data["name"] = name.strip() or "My journal"
            data["entries"].append({"id": note_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields})
            self._write(path, data)
            from .usage_study import record
            record(self.storage, "goals" if goal is not None else "journal", "save")
            return data

    def update_goal(self, journal_id, note_id, goal, next_time, *, expected):
        """Edit only manual goal fields; retain the original note and source evidence."""
        from .goals import validate_goal
        goal = validate_goal(goal)
        step = metadata(next_time=next_time)
        with self.locked(journal_id) as (path, data):
            entry = next((e for e in data['entries'] if e['id'] == note_id), None)
            if entry is None or entry != expected:
                raise ChatError('This note changed in another window. Your draft is kept; reopen it before saving.')
            entry['goal'] = goal
            entry.pop('next_time', None)
            entry.update(step)
            self._write(path, data)
            from .usage_study import record
            record(self.storage, "goals", "update")
            return data

    def set_next_time(self, journal_id, note_id, state):
        if state not in {"open", "done"}:
            raise ChatError("Choose open or done for this next step.")
        with self.locked(journal_id) as (path, data):
            entry = next((e for e in data["entries"] if e["id"] == note_id), None)
            if not entry or not entry.get("next_time"):
                raise ChatError("This note has no next-time item.")
            entry["next_time"]["state"] = state
            self._write(path, data)
            return data


def advice_selection(view, message, text):
    """Freeze one reply and only evidence associated with that conversation."""
    key = view.selection_key
    if not key or message.role != "assistant":
        raise ChatError("Select an assistant reply first.")
    source = {"provider": key[0], "session_id": key[1]}
    if message.id:
        source["message_id"] = message.id
    evidence = {"text": "", "gaps": ["Original preparation and capture time unknown."]}
    context = getattr(view, "context", None)
    if context is not None:
        evidence = {"text": json.dumps(context, ensure_ascii=False, indent=2),
                    "edition": context["edition"], "snapshot_at": context.get("snapshot_at"),
                    "gaps": ["Frozen quest context; later conversation evidence may be unavailable."]}
        if context.get("quest", {}).get("id"):
            evidence["quest_id"] = context["quest"]["id"]
    session = view.selected
    agents = getattr(view.service, "agents", None)
    if session and session.managed and agents and message.id.endswith(":assistant"):
        try:
            request_id = identifier(message.id.removesuffix(":assistant"))
            receipt = agents.result(session.id, request_id)
            if receipt.get("id") == request_id:
                source["request_id"] = request_id
                # Direct request bundles take precedence over the original startup bundle.
                activity = view.activity
                for candidate in (request_id, session.id):
                    path = activity.storage / "prepared" / (candidate + ".json")
                    try:
                        with path.open("rb") as stream:
                            raw = stream.read(JOURNAL_MAX_BYTES + 1)
                        if len(raw) > JOURNAL_MAX_BYTES:
                            raise ValueError
                        packet = json.loads(raw)
                        if not isinstance(packet, dict):
                            raise ValueError
                    except (OSError, ValueError, RecursionError):
                        continue
                    evidence = {"text": json.dumps({k: v for k, v in packet.items() if k != "image"},
                                                   ensure_ascii=False, indent=2),
                                "gaps": ["Other conversation evidence is unknown; this is the saved preparation."]}
                    if isinstance(packet.get("edition"), str):
                        evidence["edition"] = packet["edition"]
                    if packet.get("prepared_at") is not None:
                        evidence["prepared_at"] = packet["prepared_at"]
                    reports = packet.get("reports", {})
                    if isinstance(reports, dict):
                        quest_report = reports.get("quest_context", {})
                        frozen = quest_report.get("data", {}) if isinstance(quest_report, dict) else {}
                        if isinstance(frozen, dict):
                            quest = frozen.get("quest", {})
                            if isinstance(quest, dict) and quest.get("id"):
                                evidence["quest_id"] = quest["id"]
                            if frozen.get("snapshot_at") is not None:
                                evidence["snapshot_at"] = frozen["snapshot_at"]
                    if candidate == session.id:
                        evidence["gaps"].append("Startup context only; no preparation associated with this later request.")
                    if packet.get("image"):
                        image_path = Path(packet["image"])
                        if image_path.resolve().parent == (activity.storage / "captures").resolve():
                            evidence["image"] = image_path.name
                    break
                if receipt.get("status") != "completed":
                    evidence["gaps"].append("Reply completion is unverified.")
        except (ChatError, ValueError, TypeError):
            pass
    return deepcopy({"text": text, "source": source, "evidence": evidence})
