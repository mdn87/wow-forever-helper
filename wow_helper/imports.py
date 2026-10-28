"""Bounded desktop text imports and versioned import records; no Lua execution or chat transport."""

from pathlib import Path
import re
import time

from .chat import ChatError

IMPORT_VERSION = 1
CONTEXT_FILE_LIMIT = 64_000
IDENTITY_PATTERNS = (
    ("user folder", re.compile(r"(?i)\b([A-Z]:[\\/]+Users[\\/]+)[^\\/\s\"'<>|]+"), r"\1<user>"),
    ("user folder", re.compile(r"(/(?:Users|home)/)[^/\s\"'<>|]+"), r"\1<user>"),
    ("account folder", re.compile(r"(?i)(WTF[\\/]+Account[\\/]+)[^\\/\s\"'<>|]+"), r"\1<account>"),
)


def read_text(path, limit=CONTEXT_FILE_LIMIT):
    """Check size before decoding, then require readable UTF-8 text."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError:
        raise ChatError("That text file is unavailable. Your draft is kept.") from None
    if len(raw) > limit:
        raise ChatError(f"Choose a text file at most {limit:,} bytes.")
    try:
        body = raw.decode("utf-8-sig")
    except UnicodeError:
        raise ChatError("That file is not readable UTF-8 text. Your draft is kept.") from None
    if "\0" in body:
        raise ChatError("That file contains binary data. Paste or import readable text.")
    return body


def replace_identity(text, terms=()):
    """Replace local paths, account folders, and user-listed words; report counts, never the values."""
    counts = {}
    for label, pattern, replacement in IDENTITY_PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[label] = counts.get(label, 0) + n
    for term in terms:
        text, n = re.subn(re.escape(term), "<redacted>", text, flags=re.I)
        if n:
            counts["listed word"] = counts.get("listed word", 0) + n
    return text, counts


def import_record(source_kind, source_version, edition, payload, *, coverage, warnings,
                  captured_at="Unknown", profile=None):
    """A versioned record; the original is not retained, so there is no private reference to keep."""
    return {"format_version": IMPORT_VERSION, "source_kind": source_kind,
            "source_version": source_version or "Unknown", "profile": profile, "edition": edition,
            "timestamps": {"captured": captured_at, "imported": time.time()},
            "coverage": coverage, "warnings": warnings, "payload": payload,
            "original": "Not retained; only the reviewed text below is kept."}
