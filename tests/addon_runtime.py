"""Runs WoWCompanionProbe under Lua 5.1 against the invented game in wow_stub.lua.

Needs the optional ``lupa`` package (``pip install ".[addon-tests]"``); the tests that import this
module skip without it. No game client, game data or Blizzard code is involved: the "game" is a
table of made-up answers.
"""
from pathlib import Path

from lupa import lua51

ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "wow_addon" / "WoWCompanionProbe"
ADDON_FILE = ADDON_DIR / "WoWCompanionProbe.lua"
STUB_FILE = Path(__file__).with_name("wow_stub.lua")

# Stands for a value the client marks secret wherever a test describes the invented game.
SECRET = object()

# An invented quest log entry, in the shape the interface returns objectives.
SAMPLE_OBJECTIVES = [
    {"text": "Boars slain: 3/8", "numFulfilled": 3, "numRequired": 8, "finished": False},
    {"text": "Collect 5 tusks", "numFulfilled": 5, "numRequired": 5, "finished": True},
]


class ProbeAddon:
    """One fresh Lua state with the addon loaded.

    Keyword arguments describe what the invented game reports (see ``wow_stub.lua``). ``without``
    names interface functions or tables the client does not have, ``bit`` supplies the game's bit
    library, ``saved`` is the saved-variables table the client would hand the addon, and ``source``
    replaces the addon text.
    """

    def __init__(self, *, without=(), bit=False, saved=None, source=None, **world):
        self.lua = lua51.LuaRuntime(encoding=None, unpack_returned_tuples=True)
        self.error = lua51.LuaError
        self.lua.execute(STUB_FILE.read_bytes())
        names = self.lua.globals()
        self.stub = names.Stub
        for name in without:
            names[name.encode()] = None
        if bit:
            names.bit = self.lua.table_from({b"bxor": lambda a, b: int(a) ^ int(b)})
        if saved is not None:
            names.WoWCompanionProbeDB = self._lua(saved)
        self.world(**world)
        self.ns = self.lua.table()
        self.stub.load(source if source is not None else ADDON_FILE.read_bytes(), self.ns)

    # --- describing the invented game -------------------------------------------------------

    def world(self, **knobs):
        """Replace everything the invented game reports."""
        self.stub.env = self._lua(knobs)

    def _lua(self, value):
        if value is SECRET:
            return self.stub.SECRET
        if isinstance(value, str):
            return value.encode("utf-8")
        if isinstance(value, dict):
            return self.lua.table_from({self._key(key): self._lua(item) for key, item in value.items()
                                        if item is not None})
        if isinstance(value, (list, tuple)):
            return self.lua.table_from([self._lua(item) for item in value])
        return value

    @staticmethod
    def _key(key):
        return key.encode("utf-8") if isinstance(key, str) else key

    # --- the addon's entry points -----------------------------------------------------------

    def packet(self):
        """``(text, None)`` for a packet, or ``(None, reason)`` when none can be built."""
        text, second = self.ns.packetText()
        if text is None:
            return None, second.decode("utf-8")
        return text, None

    def text(self):
        text, reason = self.packet()
        assert text is not None, f"no packet: {reason}"
        return text

    def show_strip(self, cell=4, columns=160):
        """Draw the strip and return the packet text it encodes."""
        text, _grid, _rects = self.ns.showStrip(cell, columns)
        return text

    def command(self, message=""):
        self.lua.globals().SlashCmdList[b"WFHPROBE"](message.encode("utf-8"))

    def advance(self, seconds):
        self.stub.advance(seconds)

    # --- what the addon did ---------------------------------------------------------------

    def printed(self):
        lines = self.stub.printed
        return [lines[index].decode("utf-8") for index in range(1, len(lines) + 1)]

    def frame(self, name):
        return self.stub.named[name.encode()]

    def frames(self):
        frames = self.stub.frames
        return [frames[index] for index in range(1, len(frames) + 1)]

    @staticmethod
    def field(widget, name):
        """A stub widget's recorded state, for example ``_shown`` or ``_text``."""
        return widget[name.encode()]

    def strip_pixels(self):
        """``(width, height, rects)`` of the strip as drawn, in physical pixels; rects are (left, top, width, height)."""
        width, height, flat = self.stub.stripPixels()
        values = [flat[index] for index in range(1, len(flat) + 1)]
        return width, height, [tuple(values[at:at + 4]) for at in range(0, len(values), 4)]

    @staticmethod
    def children(widget):
        kids = widget[b"_children"]
        return [kids[index] for index in range(1, len(kids) + 1)]

    @staticmethod
    def colour(widget):
        """The (red, green, blue, alpha) a texture was filled with, or None."""
        values = widget[b"_color"]
        return None if values is None else tuple(values[index] for index in range(1, 5))

    def click(self, button):
        button[b"_scripts"][b"OnClick"]()

    def globals_read(self):
        return {key.decode() for key, _ in self.stub.globalsRead.items()}

    def globals_written(self):
        return {key.decode() for key, _ in self.stub.globalsWritten.items()}

    def lua_list(self, values):
        """A Lua array from Python numbers, for functions that take a table of bytes."""
        return self.lua.table_from(list(values))
