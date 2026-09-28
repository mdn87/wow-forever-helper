"""Read a SavedVariables file with a restricted grammar. Nothing from disk is ever executed.

Accepted (docs/PLAN.md section 5.1): top-level `Name = { ... }` or `Name = nil` assignments;
tables of `[key] = value` and positional entries; string or integer keys; string, number,
true, false, nil, and nested table values; the game's `-- [n]` line comments; and the string
escapes \\" \\\\ \\n \\r \\t and decimal \\ddd. Everything else is an error.
"""

import os
import re
import time
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 32

_SPACE = re.compile(r"(?:\s+|--(?!\[=*\[)[^\n]*)+")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_STRING = re.compile(r'"((?:[^"\\\n]|\\(?:\d{1,3}|["\\nrt]))*)"')
_ESCAPE = re.compile(r"\\(\d{1,3}|.)")
_SIMPLE = {'"': 0x22, "\\": 0x5C, "n": 0x0A, "r": 0x0D, "t": 0x09}


class SavedVariablesError(ValueError):
    """The file is not in the accepted subset. Messages never contain paths."""


def _decode(body):
    out = bytearray()
    last = 0
    for match in _ESCAPE.finditer(body):
        out += body[last:match.start()].encode("utf-8")
        code = match.group(1)
        value = int(code) if code.isdigit() else _SIMPLE[code]
        if value > 255:
            raise SavedVariablesError("A string escape is out of range.")
        out.append(value)
        last = match.end()
    out += body[last:].encode("utf-8")
    return out.decode("utf-8", errors="replace")


class _Parser:
    def __init__(self, text):
        self.text, self.pos = text, 0

    def fail(self, what):
        line = self.text.count("\n", 0, self.pos) + 1
        raise SavedVariablesError(f"Unsupported SavedVariables content at line {line}: {what}.")

    def skip(self):
        match = _SPACE.match(self.text, self.pos)
        if match:
            self.pos = match.end()

    def peek(self):
        self.skip()
        return self.text[self.pos:self.pos + 1]

    def expect(self, char):
        if self.peek() != char:
            self.fail(f"expected '{char}'")
        self.pos += 1

    def name(self):
        self.skip()
        match = _NAME.match(self.text, self.pos)
        if not match:
            self.fail("expected a name")
        self.pos = match.end()
        return match.group(0)

    def document(self):
        result = {}
        while self.peek():
            name = self.name()
            if name in {"true", "false", "nil"}:
                self.fail("expected a variable name")
            self.expect("=")
            if self.peek() == "{":
                result[name] = self.table(1)
            elif self.name() == "nil":
                result[name] = None
            else:
                self.fail("top-level values must be tables or nil")
            if self.peek() == ";":
                self.pos += 1
        return result

    def table(self, depth):
        if depth > MAX_DEPTH:
            self.fail("tables are nested too deeply")
        self.expect("{")
        table, index = {}, 1
        while self.peek() != "}":
            if not self.peek():
                self.fail("a table is not closed")
            if self.peek() == "[":
                self.pos += 1
                key = self.scalar()
                if isinstance(key, float) and key.is_integer():
                    key = int(key)
                if isinstance(key, bool) or not isinstance(key, (str, int)):
                    self.fail("keys must be strings or integers")
                self.expect("]")
                self.expect("=")
                table[key] = self.value(depth)
            else:
                table[index] = self.value(depth)
                index += 1
            if self.peek() in {",", ";"}:
                self.pos += 1
            elif self.peek() != "}":
                self.fail("expected ',' or '}'")
        self.pos += 1
        return table

    def value(self, depth):
        return self.table(depth + 1) if self.peek() == "{" else self.scalar()

    def scalar(self):
        self.skip()
        char = self.text[self.pos:self.pos + 1]
        if char == '"':
            match = _STRING.match(self.text, self.pos)
            if not match:
                self.fail("a string is malformed")
            self.pos = match.end()
            return _decode(match.group(1))
        match = _NUMBER.match(self.text, self.pos)
        if match and not _NAME.match(self.text, match.end()):
            self.pos = match.end()
            number = match.group(0)
            if len(number) > 40:
                self.fail("a number is too long")
            return float(number) if any(c in number for c in ".eE") else int(number)
        words = {"true": True, "false": False, "nil": None}
        match = _NAME.match(self.text, self.pos)
        if match and match.group(0) in words:
            self.pos = match.end()
            return words[match.group(0)]
        self.fail("expected a string, number, true, false, nil, or table")


def parse(text):
    """Parse SavedVariables text into {name: dict or None}. Lua tables become dicts."""
    if not isinstance(text, str):
        raise SavedVariablesError("SavedVariables must be text.")
    if len(text.encode("utf-8", errors="replace")) > MAX_BYTES:
        raise SavedVariablesError("The SavedVariables file is larger than 4 MB.")
    return _Parser(text.lstrip("\ufeff")).document()


def as_list(table):
    """A Lua array (keys 1..n) as a list; any other table as its values in key order."""
    if not isinstance(table, dict):
        return []
    if list(table) == list(range(1, len(table) + 1)):
        return list(table.values())
    return [table[key] for key in sorted(table, key=lambda k: (isinstance(k, str), k))]


def read_stable(path, *, wait=1.0, sleep=None):
    """Parse a file only after its size and mtime stay unchanged for `wait` seconds.

    The game rewrites SavedVariables on /reload and logout; a half-written file must not be
    trusted. Returns (parsed, mtime).
    """
    path = Path(path)
    try:
        before = os.stat(path)
        if before.st_size > MAX_BYTES:
            raise SavedVariablesError("The SavedVariables file is larger than 4 MB.")
        data = path.read_bytes()
        (sleep or time.sleep)(wait)
        after = os.stat(path)
    except FileNotFoundError:
        raise SavedVariablesError("No SavedVariables file yet: /reload or log out once with the addon enabled.") from None
    except OSError:
        raise SavedVariablesError("The SavedVariables file could not be read.") from None
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size) or len(data) != after.st_size:
        raise SavedVariablesError("The game is still writing SavedVariables; try again in a moment.")
    return parse(data.decode("utf-8", errors="replace")), after.st_mtime
