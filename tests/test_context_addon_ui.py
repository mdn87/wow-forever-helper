"""The probe addon's drawing and commands, run under Lua 5.1 against an invented game.

Like test_context_addon.py this checks the addon's own code, not a game client: the "screen" is the
list of rectangles the addon asks the interface to draw, turned into pixels the way the game would
snap them. How the real client renders them is not checked here. Needs the optional ``lupa`` package.
"""
import pytest

pytest.importorskip("lupa.lua51")

import addon_screen
from addon_runtime import ADDON_DIR, ROOT, SAMPLE_OBJECTIVES, ProbeAddon
from wow_helper.context import clipboard, envelope, strip

WORLD = dict(tracked=900001, objectives=SAMPLE_OBJECTIVES)
SMALL_INTERFACE_ON_4K = dict(uiHeight=540, physicalHeight=2160, physicalWidth=3840)


def attr(widget, name):
    """A field the addon set on a widget, for example the copy box's ``edit``."""
    return widget[name.encode()]


def is_shown(widget):
    return widget[b"_shown"]


def next_sequence(addon):
    return envelope.parse_envelope(addon.text()).seq


# --- the drawn strip --------------------------------------------------------------------------------

STRIPS = [
    pytest.param(2, 160, {}, id="2 px cells"),
    pytest.param(3, 40, {}, id="3 px cells, 40 columns"),
    pytest.param(4, 160, {}, id="4 px cells"),
    pytest.param(4, 256, {}, id="4 px cells, 256 columns"),
    pytest.param(8, 160, {}, id="8 px cells"),
    pytest.param(4, 160, SMALL_INTERFACE_ON_4K, id="4 px cells, 4K at a small interface scale"),
]


@pytest.mark.parametrize("cell, columns, display", STRIPS)
def test_the_rectangles_the_addon_draws_are_the_reference_picture_pixel_for_pixel(cell, columns, display):
    addon = ProbeAddon(**WORLD, **display)
    text = addon.show_strip(cell, columns)
    width, height, rects = addon.strip_pixels()
    reference = strip.render_ideal(strip.encode_cells(text, columns=columns), cell, strip.QUIET)
    assert addon_screen.backdrop_with_rectangles((width, height), rects) == reference


SCENES = [
    pytest.param("clutter", (0, 0), True, id="busy scene, top left corner, label noise below"),
    pytest.param("gradient", (37, 23), False, id="gradient, offset from the corner"),
    pytest.param("stripes", (0, 0), True, id="stripes close to the cell pitch, label noise below"),
]


@pytest.mark.parametrize("background, at, label", SCENES)
@pytest.mark.parametrize("cell", [2, 4, 8])
def test_the_helper_reads_back_what_the_addon_draws(cell, background, at, label):
    addon = ProbeAddon(**WORLD)
    text = addon.show_strip(cell)
    width, height, rects = addon.strip_pixels()
    size = (1920, 1080) if cell == 8 else (1280, 720)
    frame = addon_screen.on_screen((width, height), rects, size=size, at=at, background=background,
                                   label_clutter=label)
    assert strip.decode_strip(frame).payload == text


def test_the_drawn_backdrop_is_black_and_every_cell_is_white():
    addon = ProbeAddon(**WORLD)
    addon.show_strip()
    frame = addon.frame("WoWCompanionProbeStrip")
    colours = {(attr(child, "_layer"), addon.colour(child)) for child in addon.children(frame)
               if addon.colour(child) is not None}
    assert colours == {(b"BACKGROUND", (0, 0, 0, 1)), (b"ARTWORK", (1, 1, 1, 1))}


# --- commands ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("message", ["", "help", "bogus", "strip 9", "strip 4 33", "strip x", "strip 4 160 later"])
def test_help_and_bad_arguments_print_the_usage_and_draw_nothing(message):
    addon = ProbeAddon(**WORLD)
    addon.command(message)
    printed = "\n".join(addon.printed())
    assert "/wfhprobe strip" in printed and "/wfhprobe copy" in printed and "/wfhprobe off" in printed
    assert all(line.startswith("WFH probe:") for line in addon.printed())
    assert addon.stub.named[b"WoWCompanionProbeStrip"] is None
    assert addon.stub.named[b"WoWCompanionProbeCopy"] is None


def test_a_strip_hides_itself_after_fifteen_seconds():
    addon = ProbeAddon(**WORLD)
    addon.command("strip")
    frame = addon.frame("WoWCompanionProbeStrip")
    assert is_shown(frame)
    addon.advance(14)
    assert is_shown(frame)
    addon.advance(2)
    assert not is_shown(frame)


def test_drawing_again_restarts_the_clock_so_the_first_timer_cannot_hide_the_second_strip():
    addon = ProbeAddon(**WORLD)
    addon.command("strip")
    addon.advance(10)
    addon.command("strip")
    frame = addon.frame("WoWCompanionProbeStrip")
    addon.advance(6)
    assert is_shown(frame)
    addon.advance(10)
    assert not is_shown(frame)


def test_off_hides_everything():
    addon = ProbeAddon(**WORLD)
    addon.command("strip")
    addon.command("copy")
    addon.command("off")
    assert not is_shown(addon.frame("WoWCompanionProbeStrip"))
    assert not is_shown(addon.frame("WoWCompanionProbeCopy"))


def test_live_mode_redraws_every_two_seconds_for_half_a_minute_then_stops():
    addon = ProbeAddon(**WORLD)
    addon.command("strip 4 160 live")
    addon.advance(31)
    assert next_sequence(addon) == 1 + 15 + 1
    frame = addon.frame("WoWCompanionProbeStrip")
    assert is_shown(frame)
    addon.advance(10)
    assert not is_shown(frame)
    assert next_sequence(addon) == 1 + 15 + 1 + 1


def test_off_stops_a_running_live_mode():
    addon = ProbeAddon(**WORLD)
    addon.command("strip 4 160 live")
    addon.advance(5)
    addon.command("off")
    addon.advance(60)
    assert next_sequence(addon) == 4
    assert not is_shown(addon.frame("WoWCompanionProbeStrip"))


def test_a_new_strip_command_replaces_a_running_live_mode():
    addon = ProbeAddon(**WORLD)
    addon.command("strip 4 160 live")
    addon.advance(3)
    addon.command("strip")
    addon.advance(60)
    assert next_sequence(addon) == 4


def test_a_refused_packet_draws_nothing_and_says_why():
    addon = ProbeAddon(noBuild=True)
    addon.command("strip")
    addon.command("copy")
    assert addon.printed() == ["WFH probe: cannot build a packet: build unreadable"] * 2
    assert addon.stub.named[b"WoWCompanionProbeStrip"] is None


def test_status_reports_which_features_this_client_has():
    full = ProbeAddon(**WORLD)
    full.command("status")
    lines = full.printed()
    assert lines[0] == f"WFH probe: version {full.ns.VERSION.decode()}, interface 16001, build 12345."
    assert "issecretvalue: present; CopyToClipboard: present" in lines[1]
    assert "physical screen 1920 x 1080; one pixel = 0.7111 interface units." in lines[2]
    bare = ProbeAddon(without=("issecretvalue", "CopyToClipboard"))
    bare.command("status")
    assert "issecretvalue: absent; CopyToClipboard: absent" in bare.printed()[1]


# --- the copy box -----------------------------------------------------------------------------------

def test_the_copy_box_holds_a_packet_the_helpers_clipboard_parser_accepts():
    addon = ProbeAddon(**WORLD)
    addon.command("copy")
    box = addon.frame("WoWCompanionProbeCopy")
    edit = attr(box, "edit")
    shown_text = attr(edit, "_text").decode("utf-8")
    assert shown_text.startswith(clipboard.PREFIX)
    packet = clipboard.parse_clipboard(shown_text)
    assert (packet.seq, packet.quest.id) == (1, 900001)
    assert attr(attr(box, "status"), "_text") == f"{len(shown_text)} characters, packet 1.".encode()
    assert attr(box, "button") is None


def test_typing_in_the_copy_box_is_undone_and_escape_closes_it():
    addon = ProbeAddon(**WORLD)
    addon.command("copy")
    box = addon.frame("WoWCompanionProbeCopy")
    edit = attr(box, "edit")
    original = attr(edit, "_text")
    addon.stub.type(edit, b"tampered")
    assert attr(edit, "_text") == original
    edit[b"_scripts"][b"OnEscapePressed"]()
    assert not is_shown(box)


def test_the_button_reports_what_the_games_clipboard_function_did():
    addon = ProbeAddon(**WORLD)
    addon.command("copy api")
    box = addon.frame("WoWCompanionProbeCopy")
    button = attr(box, "button")
    status = attr(box, "status")
    addon.click(button)
    assert addon.stub.copied == attr(attr(box, "edit"), "_text")
    assert attr(status, "_text") == b"CopyToClipboard ran and returned nil"
    addon.world(copyBlocked=True, **WORLD)
    addon.click(button)
    assert attr(status, "_text").startswith(b"CopyToClipboard was refused: ")
    addon.lua.globals().CopyToClipboard = None
    addon.click(button)
    assert attr(status, "_text") == b"CopyToClipboard is not present in this client."
    addon.command("copy")
    assert not is_shown(button)


def test_the_button_still_appears_when_the_client_has_no_button_template():
    addon = ProbeAddon(noTemplates=True, **WORLD)
    addon.command("copy api")
    assert attr(addon.frame("WoWCompanionProbeCopy"), "button") is not None


# --- what the addon touches -------------------------------------------------------------------------

READ_ONLY_GAME_INTERFACE = {
    "C_Map", "C_QuestLog", "C_SuperTrack", "C_Timer", "CopyToClipboard", "CreateFrame", "GetBuildInfo",
    "GetPhysicalScreenSize", "GetRealZoneText", "GetServerTime", "GetSubZoneText", "SlashCmdList", "UIParent",
    "UnitClass", "UnitGUID", "UnitLevel", "WoWCompanionProbeDB", "bit", "issecretvalue",
}
LUA_LIBRARY = {"ipairs", "math", "pcall", "print", "string", "table", "tonumber", "tostring", "type"}


def use_everything():
    addon = ProbeAddon(bit=True, **WORLD)
    for message in ["", "help", "strip", "strip 6", "strip 3 80", "strip 4 160 live", "copy", "copy api", "status", "off"]:
        addon.command(message)
    addon.advance(40)
    addon.world(copyBlocked=True, **WORLD)
    addon.click(attr(addon.frame("WoWCompanionProbeCopy"), "button"))
    return addon


def test_the_addon_reads_only_these_game_functions():
    assert use_everything().globals_read() <= READ_ONLY_GAME_INTERFACE | LUA_LIBRARY


def test_the_addon_writes_only_its_slash_command_and_its_saved_table():
    assert use_everything().globals_written() == {"SLASH_WFHPROBE1", "WoWCompanionProbeDB"}


def test_the_addon_registers_no_events_and_runs_nothing_every_frame():
    addon = use_everything()
    for frame in addon.frames():
        calls = {name.decode() for _, name in frame[b"_calls"].items()}
        assert not {name for name in calls if name.startswith("Register")}
        assert {name.decode() for name, _ in frame[b"_scripts"].items()} <= {"OnClick", "OnEscapePressed", "OnTextChanged"}


@pytest.mark.parametrize("absent", [("issecretvalue",), ("C_Timer",), ("SlashCmdList",), ("CopyToClipboard",)])
def test_the_addon_loads_and_draws_when_an_optional_interface_is_absent(absent):
    addon = ProbeAddon(without=absent, **WORLD)
    assert envelope.parse_envelope(addon.show_strip()).quest.id == 900001


# --- agreement with the helper and the packaging ------------------------------------------------------

def toc_fields(path):
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and ":" in line:
            key, _, value = line[3:].partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_the_toc_and_the_code_agree():
    fields = toc_fields(ADDON_DIR / "WoWCompanionProbe.toc")
    companion = toc_fields(ROOT / "wow_addon" / "WoWCompanion" / "WoWCompanion.toc")
    addon = ProbeAddon()
    assert fields["Version"] == addon.ns.VERSION.decode()
    assert fields["SavedVariables"] == "WoWCompanionProbeDB"
    assert fields["Interface"] == companion["Interface"]
    listed = [line.strip() for line in (ADDON_DIR / "WoWCompanionProbe.toc").read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")]
    assert listed == ["WoWCompanionProbe.lua"]


def test_the_addon_and_the_helper_agree_on_the_prefix_and_the_missing_names():
    addon = ProbeAddon()
    names = addon.ns.MISSING_NAMES
    assert addon.ns.PREFIX.decode() == clipboard.PREFIX
    assert [names[index].decode() for index in range(1, len(names) + 1)] == list(envelope.MISSING_NAMES)
