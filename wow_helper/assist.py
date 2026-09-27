"""Resolve a human request to one configured chord, never a gameplay sequence."""

from contextlib import closing
from dataclasses import dataclass
import re
import sqlite3
import time
from pathlib import Path


class AssistError(Exception):
    """A safe, path-free error suitable for the CLI."""


ACTION = "teleport-orgrimmar"
SPELL = "Teleport: Orgrimmar"
MAX_AGE = 15.0
KEYS = {**{chr(n): n for n in range(65, 91)},
        **{str(n): 48 + n for n in range(10)},
        **{f"F{n}": 111 + n for n in range(1, 13)}}
MODIFIERS = {"CTRL": 0x11, "ALT": 0x12, "SHIFT": 0x10}


@dataclass(frozen=True)
class Chord:
    name: str
    codes: tuple[int, ...]


def parse_key(value: str) -> Chord:
    parts = value.upper().replace(" ", "").split("+")
    modifiers, key = parts[:-1], parts[-1]
    if (key not in KEYS or any(m not in MODIFIERS for m in modifiers)
            or len(set(modifiers)) != len(modifiers)):
        raise AssistError("Use one letter, digit, or F1-F12, optionally with CTRL, ALT, SHIFT.")
    if "ALT" in modifiers and key == "F4":
        raise AssistError("ALT+F4 is a window command, not a supported game binding.")
    ordered = [m for m in MODIFIERS if m in modifiers]
    return Chord("+".join([*ordered, key]), tuple([MODIFIERS[m] for m in ordered] + [KEYS[key]]))


def resolve(text: str) -> str:
    if not isinstance(text, str) or len(text) > 200:
        raise AssistError("Use one short, explicit spell request.")
    normalized = " ".join(text.lower().strip().rstrip(".!?").split())
    if re.fullmatch(r"(?:please )?(?:cast )?teleport(?: to|:)? orgrimmar(?: on my mage)?(?: please)?", normalized):
        return ACTION
    raise AssistError("Command not recognized. Say: cast teleport to Orgrimmar on my mage.")


def check_age(issued_at: float, now: float) -> None:
    # This comparison also rejects NaN and infinities.
    if not 0 <= now - issued_at <= MAX_AGE:
        raise AssistError("Request expired or has an invalid timestamp; make a new request.")


class Assistant:
    def __init__(self, path: Path, desktop=None, clock=time.time):
        self.path, self.desktop, self.clock = path, desktop, clock
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS controls (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO controls VALUES ('enabled', '0');
                CREATE TABLE IF NOT EXISTS bindings (action TEXT PRIMARY KEY, chord TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, action TEXT NOT NULL, outcome TEXT NOT NULL);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=2)

    def enable(self, enabled: bool):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE controls SET value=? WHERE name='enabled'", (str(int(enabled)),))
        return {"status": "enabled" if enabled else "stopped"}

    def bind(self, action: str, key: str):
        if action != ACTION:
            raise AssistError("Only teleport-orgrimmar is supported in this first version.")
        chord = parse_key(key)
        with closing(self.connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO bindings VALUES (?, ?)", (action, chord.name))
        return {"status": "bound", "action": action, "key": chord.name}

    def status(self):
        with closing(self.connect()) as db:
            enabled = db.execute("SELECT value FROM controls WHERE name='enabled'").fetchone()[0] == "1"
            bindings = dict(db.execute("SELECT action, chord FROM bindings"))
        return {"enabled": enabled, "bindings": bindings}

    def request(self, text: str, *, execute=False, request_id=None, issued_at=None):
        action = resolve(text)
        with closing(self.connect()) as db:
            row = db.execute("SELECT chord FROM bindings WHERE action=?", (action,)).fetchone()
        if not row:
            raise AssistError("Bind teleport-orgrimmar to its in-game action-bar key first.")
        chord = parse_key(row[0])
        result = {"status": "preview", "action": action, "spell": SPELL, "key": chord.name}
        if not execute:
            return result
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise AssistError("Execution needs a stable request ID from the original human command.")
        if issued_at is None:
            raise AssistError("Execution needs the original command's Unix timestamp (--issued-at).")
        check_age(issued_at, self.clock())
        if self.desktop is None:
            raise AssistError("No Windows input backend is available.")
        # Commit the reservation BEFORE input. A crash must never make a retry replay it.
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM requests WHERE id=?", (request_id,)).fetchone():
                raise AssistError("This request ID was already consumed; input will not be replayed.")
            if db.execute("SELECT value FROM controls WHERE name='enabled'").fetchone()[0] != "1":
                raise AssistError("Assistive input is stopped. Enable it before issuing a new command.")
            db.execute("INSERT INTO requests VALUES (?, ?, 'reserved')", (request_id, action))
        # Serialize STOP and dispatch; there is no queue or held-key loop to cancel.
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT value FROM controls WHERE name='enabled'").fetchone()[0] != "1":
                raise AssistError("Assistive input was stopped before dispatch.")
            if db.execute("SELECT chord FROM bindings WHERE action=?", (action,)).fetchone()[0] != chord.name:
                raise AssistError("The binding changed; make a new request.")
            check_age(issued_at, self.clock())
            # The earlier reservation survives rollback, including unknown delivery results.
            self.desktop.press(chord)
            db.execute("UPDATE requests SET outcome='sent' WHERE id=?", (request_id,))
        return {**result, "status": "sent", "message": "Key sent once; spell success is not verified."}
