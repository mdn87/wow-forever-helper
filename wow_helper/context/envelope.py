"""The context envelope: the one packet shape both transports carry.

A companion addon reads a few facts about what the game is showing (build, character class and
level, zone, the selected quest and its objectives) and hands them to this program as one JSON
object, either as text on the clipboard or as bytes drawn in a strip of pixels. This module is the
only place that turns those bytes into trusted-shaped values.

The input is untrusted. Other addons, pasted text and other programs can all put bytes where the
packet is expected, so the parser accepts exactly the documented shape and nothing else:

* the size is bounded before anything is decoded, and so are nesting depth and integer length;
* duplicate keys, floats, NaN and Infinity are refused;
* every key is required, and an unknown key is refused (a newer packet bumps ``v`` instead);
* every number has a range and every identifier has a fixed format;
* every piece of text from the game goes through ``sanitize.sanitize_game_string``, and the
  fields that changed are listed in ``Envelope.cleaned``;
* a refusal names a reason code and the field, never the offending value.

``null`` and ``missing`` mean different things. ``null`` says the thing does not exist (no
selected quest, no subzone). A name in ``missing`` says it exists but the addon could not read it
(a restricted value, an absent API). A consumer must never treat an unreadable value as an empty
one.
"""
import json
import re
from dataclasses import dataclass

from .sanitize import GAME_STRING_MAX, OBJECTIVE_TEXT_MAX, sanitize_game_string

ENVELOPE_VERSION = 1
ENVELOPE_MAX_BYTES = 8192
MAX_OBJECTIVES = 8
MAX_DEPTH = 6
MAX_INT_CHARS = 12
SEQ_MAX = 2 ** 31 - 1

CODES = {
    "too-large": "the packet is larger than the size limit",
    "not-utf8": "the packet bytes are not valid UTF-8",
    "bad-json": "the packet is not valid JSON",
    "too-deep": "the packet nests deeper than any real packet does",
    "not-object": "the packet is JSON but not an object",
    "duplicate-key": "an object repeats a key",
    "bad-number": "a number is a float, NaN or Infinity where only integers belong",
    "unsupported-version": "the packet version is not one this reader understands",
    "wrong-kind": "the packet is not a context packet",
    "unknown-key": "an object has a key the schema does not define",
    "missing-field": "an object lacks a required key",
    "bad-type": "a field has the wrong JSON type",
    "out-of-range": "a number is outside its allowed range",
    "bad-format": "a text field does not match its required format",
    "too-many": "a list has more entries than the schema allows",
}


def describe(code):
    return CODES.get(code, "unknown reason")


class ContextError(Exception):
    """A packet was refused. ``code`` is one of ``CODES``; ``path`` names the field, never its value."""

    def __init__(self, code, path=""):
        super().__init__(code, path)
        self.code = code
        self.path = path

    def __str__(self):
        where = f" at {self.path}" if self.path else ""
        return f"{self.code}{where}: {describe(self.code)}"


HEX16 = re.compile(r"[0-9a-f]{16}")
_CLASS = re.compile(r"[A-Z]{3,16}")
_VERSION = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,4}){1,3}")
_BUILD = re.compile(r"[0-9]{1,9}")
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,23}")

PICKS = ("tracked", "watched", "first")
_PICK = re.compile("|".join(PICKS))
MISSING_NAMES = (
    "who", "who.ref", "who.level", "who.class",
    "where", "where.zone", "where.sub", "where.map",
    "quest", "quest.title", "quest.complete", "quest.objectives",
)

# Key order is part of the contract: the addon writes keys in this order and so does serialize(),
# so the same packet is the same bytes on both sides.
_ORDER = {
    "": ("v", "kind", "sid", "seq", "at", "build", "who", "where", "quest", "scope", "missing"),
    "build": ("version", "build", "interface"),
    "who": ("ref", "level", "class"),
    "where": ("zone", "sub", "map"),
    "quest": ("id", "pick", "title", "complete", "objectives"),
    "objective": ("text", "have", "need", "done"),
    "scope": ("quests",),
}
_CHILD_KIND = {
    ("", "build"): "build", ("", "who"): "who", ("", "where"): "where", ("", "quest"): "quest",
    ("", "scope"): "scope", ("quest", "objectives"): "objective",
}


@dataclass(frozen=True)
class Build:
    version: str
    build: str
    interface: int


@dataclass(frozen=True)
class Who:
    ref: str | None
    level: int | None
    char_class: str | None


@dataclass(frozen=True)
class Where:
    zone: str | None
    sub: str | None
    map: int | None


@dataclass(frozen=True)
class Objective:
    text: str
    have: int | None
    need: int | None
    done: bool


@dataclass(frozen=True)
class Quest:
    id: int
    pick: str
    title: str | None
    complete: bool | None
    objectives: tuple | None


@dataclass(frozen=True)
class Envelope:
    sid: str
    seq: int
    at: int
    build: Build
    who: Who | None
    where: Where | None
    quest: Quest | None
    missing: tuple
    cleaned: tuple = ()

    def to_dict(self):
        """The packet in its documented shape, ready for ``serialize``."""
        who = None if self.who is None else {
            "ref": self.who.ref, "level": self.who.level, "class": self.who.char_class}
        where = None if self.where is None else {
            "zone": self.where.zone, "sub": self.where.sub, "map": self.where.map}
        quest = None
        if self.quest is not None:
            objectives = None
            if self.quest.objectives is not None:
                objectives = [{"text": o.text, "have": o.have, "need": o.need, "done": o.done}
                              for o in self.quest.objectives]
            quest = {"id": self.quest.id, "pick": self.quest.pick, "title": self.quest.title,
                     "complete": self.quest.complete, "objectives": objectives}
        return {
            "v": ENVELOPE_VERSION, "kind": "context", "sid": self.sid, "seq": self.seq, "at": self.at,
            "build": {"version": self.build.version, "build": self.build.build, "interface": self.build.interface},
            "who": who, "where": where, "quest": quest,
            "scope": {"quests": "one"}, "missing": list(self.missing),
        }

    def shape(self):
        """Evidence that is safe to paste: which fields arrived, never what they held."""
        present = []
        for section, fields in (("who", self.who), ("where", self.where), ("quest", self.quest)):
            if fields is None:
                continue
            present.append(section)
            for key, value in sorted(vars(fields).items()):
                if value is not None:
                    present.append(f"{section}.{'class' if key == 'char_class' else key}")
        objectives = len(self.quest.objectives) if self.quest is not None and self.quest.objectives else 0
        return {"v": ENVELOPE_VERSION, "present": sorted(present), "objectives": objectives,
                "missing": list(self.missing), "cleaned": list(self.cleaned)}


# --- parsing ------------------------------------------------------------------------------------

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContextError("duplicate-key")
        result[key] = value
    return result


def _parse_int(token):
    if len(token) > MAX_INT_CHARS:
        raise ContextError("out-of-range")
    return int(token)


def _refuse_number(_token):
    raise ContextError("bad-number")


def _check_depth(text):
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ContextError("too-deep")
        elif char in "]}" and depth:
            depth -= 1


def _join(path, key):
    return f"{path}.{key}" if path else str(key)


def _safe_key(key):
    return key if isinstance(key, str) and _KEY.fullmatch(key) else "?"


def _object(value, path, kind):
    if not isinstance(value, dict):
        raise ContextError("bad-type", path)
    keys = _ORDER[kind]
    for key in value:
        if key not in keys:
            raise ContextError("unknown-key", _join(path, _safe_key(key)))
    for key in keys:
        if key not in value:
            raise ContextError("missing-field", _join(path, key))
    return value


def _int(value, path, low, high, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextError("bad-type", path)
    if not low <= value <= high:
        raise ContextError("out-of-range", path)
    return value


def _bool(value, path, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, bool):
        raise ContextError("bad-type", path)
    return value


def _formatted(value, path, pattern, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ContextError("bad-type", path)
    if not pattern.fullmatch(value):
        raise ContextError("bad-format", path)
    return value


class _Reader:
    def __init__(self):
        self.cleaned = []

    def text(self, value, path, cap, nullable=False):
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            raise ContextError("bad-type", path)
        clean = sanitize_game_string(value, cap)
        if clean != value:
            self.cleaned.append(path)
        return clean

    def build(self, value):
        data = _object(value, "build", "build")
        return Build(_formatted(data["version"], "build.version", _VERSION),
                     _formatted(data["build"], "build.build", _BUILD),
                     _int(data["interface"], "build.interface", 10000, 999999))

    def who(self, value):
        if value is None:
            return None
        data = _object(value, "who", "who")
        return Who(_formatted(data["ref"], "who.ref", HEX16, True),
                   _int(data["level"], "who.level", 1, 100, True),
                   _formatted(data["class"], "who.class", _CLASS, True))

    def where(self, value):
        if value is None:
            return None
        data = _object(value, "where", "where")
        return Where(self.text(data["zone"], "where.zone", GAME_STRING_MAX, True),
                     self.text(data["sub"], "where.sub", GAME_STRING_MAX, True),
                     _int(data["map"], "where.map", 0, 999999, True))

    def objective(self, value, path):
        data = _object(value, path, "objective")
        return Objective(self.text(data["text"], _join(path, "text"), OBJECTIVE_TEXT_MAX),
                         _int(data["have"], _join(path, "have"), 0, 1_000_000_000, True),
                         _int(data["need"], _join(path, "need"), 0, 1_000_000_000, True),
                         _bool(data["done"], _join(path, "done")))

    def quest(self, value):
        if value is None:
            return None
        data = _object(value, "quest", "quest")
        pick = _formatted(data["pick"], "quest.pick", _PICK)
        objectives = data["objectives"]
        if objectives is not None:
            if not isinstance(objectives, list):
                raise ContextError("bad-type", "quest.objectives")
            if len(objectives) > MAX_OBJECTIVES:
                raise ContextError("too-many", "quest.objectives")
            objectives = tuple(self.objective(item, f"quest.objectives.{index}")
                               for index, item in enumerate(objectives))
        return Quest(_int(data["id"], "quest.id", 1, 10_000_000), pick,
                     self.text(data["title"], "quest.title", GAME_STRING_MAX, True),
                     _bool(data["complete"], "quest.complete", True), objectives)


def _missing(value, data):
    if not isinstance(value, list):
        raise ContextError("bad-type", "missing")
    if len(value) > len(MISSING_NAMES):
        raise ContextError("too-many", "missing")
    names = []
    for name in value:
        if not isinstance(name, str):
            raise ContextError("bad-type", "missing")
        if name not in MISSING_NAMES or name in names:
            raise ContextError("bad-format", "missing")
        names.append(name)
    for name in names:
        section, _, field = name.partition(".")
        node = data[section]
        if field:
            node = None if node is None else node[field]
            if data[section] is None:
                raise ContextError("bad-format", "missing")
        if node is not None:
            raise ContextError("bad-format", "missing")
    return tuple(names)


def _decode(payload, max_bytes):
    if not isinstance(payload, (str, bytes, bytearray, memoryview)):
        raise ContextError("bad-json")
    # Characters are at least one byte each, so a long text is refused before it is encoded.
    if len(payload) > max_bytes:
        raise ContextError("too-large")
    try:
        raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    except UnicodeError:
        raise ContextError("not-utf8") from None
    if len(raw) > max_bytes:
        raise ContextError("too-large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ContextError("not-utf8") from None


def parse_envelope(payload, *, max_bytes=ENVELOPE_MAX_BYTES):
    """Parse one packet from text or bytes, or raise ``ContextError`` naming the reason."""
    text = _decode(payload, max_bytes)
    _check_depth(text)
    try:
        data = json.loads(text, object_pairs_hook=_pairs, parse_int=_parse_int,
                          parse_float=_refuse_number, parse_constant=_refuse_number)
    except ContextError:
        raise
    except RecursionError:
        raise ContextError("too-deep") from None
    except ValueError:
        raise ContextError("bad-json") from None
    if not isinstance(data, dict):
        raise ContextError("not-object")

    version = data.get("v", ...)
    if version is ...:
        raise ContextError("missing-field", "v")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ContextError("bad-type", "v")
    if version != ENVELOPE_VERSION:
        raise ContextError("unsupported-version", "v")
    if "kind" not in data:
        raise ContextError("missing-field", "kind")
    if not isinstance(data["kind"], str):
        raise ContextError("bad-type", "kind")
    if data["kind"] != "context":
        raise ContextError("wrong-kind", "kind")

    _object(data, "", "")
    reader = _Reader()
    sid = _formatted(data["sid"], "sid", HEX16)
    seq = _int(data["seq"], "seq", 1, SEQ_MAX)
    at = _int(data["at"], "at", 1_500_000_000, 4_100_000_000)
    build = reader.build(data["build"])
    who = reader.who(data["who"])
    where = reader.where(data["where"])
    quest = reader.quest(data["quest"])
    scope = _object(data["scope"], "scope", "scope")
    if not isinstance(scope["quests"], str):
        raise ContextError("bad-type", "scope.quests")
    if scope["quests"] != "one":
        raise ContextError("bad-format", "scope.quests")
    parsed = {
        "who": None if who is None else {"ref": who.ref, "level": who.level, "class": who.char_class},
        "where": None if where is None else {"zone": where.zone, "sub": where.sub, "map": where.map},
        "quest": None if quest is None else {"title": quest.title, "complete": quest.complete,
                                             "objectives": quest.objectives},
    }
    missing = _missing(data["missing"], parsed)
    return Envelope(sid, seq, at, build, who, where, quest, missing, tuple(reader.cleaned))


# --- writing ------------------------------------------------------------------------------------

def _string(text):
    out = ['"']
    for char in text:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "|" or ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _write(value, kind):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_write(item, kind) for item in value) + "]"
    if isinstance(value, dict):
        keys = _ORDER[kind]
        if set(value) != set(keys):
            raise ValueError(f"keys do not match the {kind or 'packet'} schema")
        parts = []
        for key in keys:
            child = _CHILD_KIND.get((kind, key), "")
            parts.append(_string(key) + ":" + _write(value[key], child))
        return "{" + ",".join(parts) + "}"
    raise ValueError("value cannot be written")


def serialize(packet):
    """Compact JSON in schema key order, with ``|`` and controls escaped. Matches the addon byte for byte."""
    return _write(packet, "")
