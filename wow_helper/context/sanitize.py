"""Make text that came from the game safe to read, show or log.

Everything that comes from the game is forgeable: quest titles, zone names and objective text can
carry text that other addons, pasted macros or other players put there. A context packet is read by
a program and may be shown to a person or passed to a model, so every string in it goes through
here first. The rules are a port of sanitizeGameString from NeverQuestAlone (MIT, derived from
chelinho139/wow-ai, MIT); THIRD_PARTY_NOTICES.md carries the licence text.

The order is part of the contract, and tests/fixtures/context_sanitize_vectors.json pins it:

1. Game escapes go whole: colours (``|cAARRGGBB`` and ``|cn...:``), the colour end ``|r``, textures
   (``|T...|t``) and atlases (``|A...|a``). A link (``|H...|h[Name]|h``) keeps its text.
2. Format and default-ignorable characters go, and so do unpaired surrogates. These can hide text
   a reader never sees: bidirectional controls, zero-width characters, fillers, tag characters.
3. Controls (C0, DEL, C1) and the line and paragraph separators become spaces, so no string can
   start a new line.
4. Any ``|`` that is left goes, so no game escape survives and none leaves a half escape behind.
5. Whitespace collapses, the ends trim, and the length is capped in code points.

Because escapes are stripped before invisible characters, a zero-width character inside an escape
stops the escape from matching. The pipe is then dropped and the letters stay ("cffff0000X"). That
is upstream behaviour, kept so both implementations agree, and it is harmless: nothing is left
that reads as a control sequence.

The caller bounds the size of the whole packet before any string gets here. These functions do not
cut their input first, because the cap counts characters left after escapes are removed.
"""
import re

GAME_STRING_MAX = 60
OBJECTIVE_TEXT_MAX = 80

# Unicode version of the table below. Python's own database may be older, and a character added to
# the format category later would pass through unnoticed; pinning a recent table closes that gap.
INVISIBLE_UNICODE_VERSION = "17.0"

# Every code point in \p{Cf} or \p{Default_Ignorable_Code_Point} as of Unicode 17.0, generated with
# Node 24's own tables (the same predicate the upstream regular expression uses). Surrogates are
# handled separately in the pattern below.
INVISIBLE_RANGES = (
    (0x00ad, 0x00ad), (0x034f, 0x034f), (0x0600, 0x0605), (0x061c, 0x061c),
    (0x06dd, 0x06dd), (0x070f, 0x070f), (0x0890, 0x0891), (0x08e2, 0x08e2),
    (0x115f, 0x1160), (0x17b4, 0x17b5), (0x180b, 0x180f), (0x200b, 0x200f),
    (0x202a, 0x202e), (0x2060, 0x206f), (0x3164, 0x3164), (0xfe00, 0xfe0f),
    (0xfeff, 0xfeff), (0xffa0, 0xffa0), (0xfff0, 0xfffb), (0x110bd, 0x110bd),
    (0x110cd, 0x110cd), (0x13430, 0x1343f), (0x1bca0, 0x1bca3), (0x1d173, 0x1d17a),
    (0xe0000, 0xe0fff),
)


def _class_body(ranges):
    parts = []
    for low, high in ranges:
        parts.append(f"\\U{low:08x}" if low == high else f"\\U{low:08x}-\\U{high:08x}")
    return "".join(parts)


_INVISIBLE = re.compile("[" + _class_body(INVISIBLE_RANGES) + r"\ud800-\udfff]")
_BREAKS = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
# The spaces that can still be present once controls and format characters are gone.
_SPACES = re.compile(r"[    -   　]+")
_LINE_END = r"\n\r  "

_ESCAPES = (
    (re.compile(r"\|c[0-9a-fA-F]{8}"), ""),
    (re.compile(r"\|cn[^:|]*:"), ""),
    (re.compile(r"\|r"), ""),
    (re.compile(r"\|H[^|]*\|h([^" + _LINE_END + r"]*?)\|h"), r"\1"),
    (re.compile(r"\|T[^|]*\|t"), ""),
    (re.compile(r"\|A[^|]*\|a"), ""),
)


def strip_escapes(text):
    """Take game escape sequences out whole; a link keeps its text. A lone ``|`` stays for the caller."""
    if "|" not in text:
        return text
    for pattern, replacement in _ESCAPES:
        text = pattern.sub(replacement, text)
    return text


def sanitize_game_string(value, max_chars=GAME_STRING_MAX):
    """One game string made safe: one line, no escapes, controls or invisible characters, capped.

    Anything that is not a string becomes an empty string; the packet parser decides whether that
    is acceptable for the field.
    """
    if max_chars < 0:
        raise ValueError("max_chars must not be negative")
    if not isinstance(value, str):
        return ""
    text = strip_escapes(value)
    text = _INVISIBLE.sub("", text)
    text = _BREAKS.sub(" ", text)
    text = text.replace("|", "")
    text = _SPACES.sub(" ", text).strip(" ")
    return text[:max_chars].strip(" ")
