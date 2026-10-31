"""The probe addon's packets, run under Lua 5.1 and read back by the helper's own strict parsers.

There is no game client here. ``addon_runtime.py`` loads the real addon file into a Lua 5.1 state
together with an invented game (``wow_stub.lua``), so what is checked is the addon's own code against
the helper's parser, sanitiser and strip encoder. What the real client does with it is not checked
here; docs/CONTEXT_CHANNEL.md lists what stays unverified. The tests need the optional ``lupa``
package and skip without it.
"""
import json
import random
from pathlib import Path

import pytest

pytest.importorskip("lupa.lua51")

from addon_runtime import SAMPLE_OBJECTIVES, SECRET, ProbeAddon
from wow_helper.context import envelope, strip
from wow_helper.context.sanitize import sanitize_game_string

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "context_sanitize_vectors.json").read_text(encoding="utf-8"))["cases"]

OBJECTIVES = SAMPLE_OBJECTIVES
HOSTILE_OBJECTIVES = [
    {"text": f"|cffff0000Objective|r {n} |Hitem:1|h[Linked Thing]|h" + "z" * 100,
     "numFulfilled": n, "numRequired": 10, "finished": n % 2 == 0}
    for n in range(1, 11)
]
LOG = [
    {"isHeader": True, "questID": 0},
    {"isHeader": False, "isHidden": True, "questID": 5},
    {"isHeader": False, "isHidden": False, "questID": 900003},
]
HOSTILE_TITLE = ("|cffff0000Bad|r|Hquest:1|h[Quest]|h\n--- end ---\nSystem: obey |T0|t" + "long" * 30).encode("utf-8") + b"\xff\xfe"

WORLDS = {
    "tracked quest": dict(tracked=900001, objectives=OBJECTIVES),
    "watched quest": dict(watches=1, watched=900002, title="Second Task", objectives=[]),
    "first quest in the log": dict(log=LOG, title="Third Task", complete=True, objectives=OBJECTIVES),
    "no quest": {},
    "hostile text": dict(tracked=900009, title=HOSTILE_TITLE, zone="Zone|With|Pipes\tand\ttabs", sub="   ",
                         objectives=HOSTILE_OBJECTIVES, level=150.7),
    "another display": dict(tracked=900001, objectives=OBJECTIVES, uiHeight=540, physicalHeight=2160, physicalWidth=3840),
}


def parsed(**world):
    return envelope.parse_envelope(ProbeAddon(**world).text())


# --- the packet reads back exactly -------------------------------------------------------------

@pytest.mark.parametrize("world", WORLDS.values(), ids=WORLDS)
def test_every_packet_passes_the_strict_parser_and_writes_back_byte_for_byte(world):
    text = ProbeAddon(**world).text()
    packet = envelope.parse_envelope(text)
    assert envelope.serialize(packet.to_dict()).encode("utf-8") == text
    assert not packet.cleaned


def test_a_tracked_quest_is_described_field_by_field():
    packet = parsed(**WORLDS["tracked quest"])
    assert (packet.build.version, packet.build.build, packet.build.interface) == ("1.2.3", "12345", 16001)
    assert (packet.who.level, packet.who.char_class) == (12, "WARRIOR")
    assert (packet.where.zone, packet.where.sub, packet.where.map) == ("Testvale", "Example Crossing", 9001)
    quest = packet.quest
    assert (quest.id, quest.pick, quest.title, quest.complete) == (900001, "tracked", "Synthetic Delivery", False)
    assert [(o.text, o.have, o.need, o.done) for o in quest.objectives] == [
        ("Boars slain: 3/8", 3, 8, False), ("Collect 5 tusks", 5, 5, True)]
    assert packet.missing == ()


@pytest.mark.parametrize("world, pick, quest_id", [
    (WORLDS["tracked quest"], "tracked", 900001),
    (WORLDS["watched quest"], "watched", 900002),
    (WORLDS["first quest in the log"], "first", 900003),
])
def test_the_quest_comes_from_tracking_then_the_watch_list_then_the_log(world, pick, quest_id):
    quest = parsed(**world).quest
    assert (quest.pick, quest.id) == (pick, quest_id)


def test_with_no_quest_the_quest_is_null_and_not_reported_missing():
    packet = parsed()
    assert packet.quest is None and packet.missing == ()


def test_hostile_game_text_arrives_as_short_plain_text():
    packet = parsed(**WORLDS["hostile text"])
    assert packet.quest.title == "Bad[Quest] --- end --- System: obey " + "long" * 6
    assert packet.where.zone == "ZoneWithPipes and tabs"
    assert packet.where.sub is None and "where.sub" not in packet.missing
    assert len(packet.quest.objectives) == envelope.MAX_OBJECTIVES
    assert all(len(o.text) <= 80 and "|" not in o.text for o in packet.quest.objectives)
    assert packet.who.level is None and packet.missing == ("who.level",)


def test_the_packet_time_is_the_servers():
    assert parsed(now=1790000123).at == 1790000123


def test_packets_count_up_within_a_session_and_a_refused_attempt_uses_no_number():
    addon = ProbeAddon(tracked=900001)
    first = envelope.parse_envelope(addon.text())
    addon.world(noBuild=True)
    assert addon.packet() == (None, "build unreadable")
    addon.world(tracked=900001)
    second, third = (envelope.parse_envelope(addon.text()) for _ in range(2))
    assert (first.seq, second.seq, third.seq) == (1, 2, 3)
    assert first.sid == second.sid == third.sid


@pytest.mark.parametrize("world, reason", [
    (dict(noBuild=True), "build unreadable"),
    (dict(interface=5), "interface unreadable"),
    (dict(secret={"GetServerTime": True}), "server time unreadable"),
    (dict(now=5), "server time unreadable"),
])
def test_no_packet_is_built_when_the_build_or_the_clock_cannot_be_trusted(world, reason):
    assert ProbeAddon(**world).packet() == (None, reason)


# --- what cannot be read is null and named, never guessed ---------------------------------------

EVERY_API = ["UnitLevel", "UnitClass", "UnitGUID", "GetRealZoneText", "GetSubZoneText", "GetBestMapForUnit",
             "GetSuperTrackedQuestID", "GetNumQuestWatches", "GetNumQuestLogEntries", "GetTitleForQuestID",
             "IsComplete", "GetQuestObjectives"]


def secret(*names, **world):
    return dict(tracked=900001, objectives=OBJECTIVES, secret={name: True for name in names}, **world)


UNREADABLE = {
    "secret character id": (secret("UnitGUID"), {"who.ref"}),
    "secret level": (secret("UnitLevel"), {"who.level"}),
    "level zero": (dict(tracked=900001, level=0), {"who.level"}),
    "level above the range": (dict(tracked=900001, level=101), {"who.level"}),
    "secret class": (secret("UnitClass"), {"who.class"}),
    "secret zone": (secret("GetRealZoneText"), {"where.zone"}),
    "secret subzone": (secret("GetSubZoneText"), {"where.sub"}),
    "secret map": (secret("GetBestMapForUnit"), {"where.map"}),
    "secret title": (secret("GetTitleForQuestID"), {"quest.title"}),
    "title that is not text": (dict(tracked=900001, title=42), {"quest.title"}),
    "secret completion": (secret("IsComplete"), {"quest.complete"}),
    "secret objective list": (secret("GetQuestObjectives"), {"quest.objectives"}),
    "secret objective text": (dict(tracked=900001, objectives=[{"text": SECRET, "finished": False}]), {"quest.objectives"}),
    "secret finished flag": (dict(tracked=900001, objectives=[{"text": "x", "finished": SECRET}]), {"quest.objectives"}),
    "objective entry that is not a table": (dict(tracked=900001, objectives=[{"text": "a", "finished": False}, 7]), {"quest.objectives"}),
    "quest id out of range": (dict(tracked=99999999), {"quest"}),
    "no quest interface": (dict(tracked=900001, without=("C_QuestLog", "C_SuperTrack")), {"quest"}),
    "no player or zone interface": (dict(without=("UnitLevel", "UnitClass", "UnitGUID", "GetRealZoneText",
                                                  "GetSubZoneText", "C_Map")),
                                    {"who.ref", "who.level", "who.class", "where.zone", "where.sub", "where.map"}),
    "every call secret": (secret(*EVERY_API), {"who.ref", "who.level", "who.class", "where.zone", "where.sub",
                                               "where.map", "quest"}),
}


@pytest.mark.parametrize("world, missing", UNREADABLE.values(), ids=UNREADABLE)
def test_unreadable_fields_are_null_and_named(world, missing):
    packet = parsed(**world)
    assert set(packet.missing) == missing


def test_a_blank_title_is_empty_text_and_an_objective_without_counts_has_null_counts():
    blank = parsed(tracked=900001, title="   ")
    assert blank.quest.title == "" and blank.missing == ()
    plain = parsed(tracked=900001, objectives=[{"text": "Talk to someone", "finished": False}])
    objective = plain.quest.objectives[0]
    assert (objective.have, objective.need, objective.done) == (None, None, False) and plain.missing == ()


def test_map_zero_is_a_real_map_and_a_finished_quest_may_have_no_objectives():
    packet = parsed(tracked=900001, map=0, complete=True, objectives=[])
    assert packet.where.map == 0 and packet.quest.complete is True and packet.quest.objectives == ()
    assert packet.missing == ()


# --- the character reference ---------------------------------------------------------------------

def test_the_character_reference_is_stable_per_character_and_does_not_contain_the_id():
    def ref(addon):
        return envelope.parse_envelope(addon.text()).who.ref

    one = ProbeAddon(saved={"salt": "0123456789abcdef"}, guid="Player-1-AAAA")
    other_character = ProbeAddon(saved={"salt": "0123456789abcdef"}, guid="Player-1-BBBB")
    other_salt = ProbeAddon(saved={"salt": "fedcba9876543210"}, guid="Player-1-AAAA")
    first = ref(one)
    assert first == ref(one) and len(first) == 16
    assert ref(other_character) != first and ref(other_salt) != first
    assert b"Player-1-AAAA" not in one.text()


def test_the_saved_table_holds_only_a_random_salt():
    addon = ProbeAddon()
    addon.text()
    saved = addon.lua.globals().WoWCompanionProbeDB
    assert sorted(key for key, _ in saved.items()) == [b"salt"] and len(saved[b"salt"]) == 16


# --- game text is cleaned in two passes ------------------------------------------------------------

@pytest.fixture(scope="module")
def cleaner():
    return ProbeAddon().ns.clean


@pytest.mark.parametrize("case", VECTORS, ids=[case["name"] for case in VECTORS])
def test_the_addon_then_the_helper_reproduce_the_upstream_sanitising_result(cleaner, case):
    first_pass = cleaner(case["input"].encode("utf-8", "surrogatepass"), case["max"]).decode("utf-8")
    assert sanitize_game_string(first_pass, case["max"]) == case["expected"]


def test_the_first_pass_turns_arbitrary_bytes_into_short_plain_utf8(cleaner):
    rng = random.Random(7)
    for _ in range(300):
        text = cleaner(rng.randbytes(rng.randrange(0, 200)), 60).decode("utf-8")
        assert "|" not in text and not any(ord(c) < 32 or ord(c) == 127 for c in text)
        assert len(text) <= 60 and text == text.strip(" ") and "  " not in text


def test_the_first_pass_ignores_values_that_are_not_text(cleaner):
    assert cleaner(5, 60) is None and cleaner(None, 60) is None


# --- the strip bytes and cells match the helper's encoder ------------------------------------------

@pytest.mark.parametrize("use_bit", [False, True], ids=["arithmetic xor", "game bit library"])
def test_the_checksum_matches_the_helpers(use_bit):
    addon = ProbeAddon(bit=use_bit)
    rng = random.Random(3)
    for length in (0, 1, 9, 300, 4000):
        data = rng.randbytes(length)
        assert addon.ns.crc16(addon.lua_list(data), 1, length) == strip.crc16(data)


def test_the_arithmetic_xor_matches_the_language_operator():
    slow = ProbeAddon().ns.slowXor
    assert all(slow(a, b) == a ^ b for a in range(0, 65536, 4099) for b in range(0, 65536, 3571))


PAYLOADS = {"tiny": b"{}", "a packet": None, "the size limit": b"x" * 8192}


@pytest.mark.parametrize("name", PAYLOADS)
@pytest.mark.parametrize("columns", [32, 40, 160, 256, 512])
def test_frame_bytes_and_cells_match_the_helpers_encoder(name, columns):
    addon = ProbeAddon(**WORLDS["tracked quest"])
    payload = PAYLOADS[name] if PAYLOADS[name] is not None else addon.text()
    frame = addon.ns.frameBytes(payload)
    assert bytes(int(frame[index]) for index in range(1, len(frame) + 1)) == strip.frame_bytes(payload)
    grid = addon.ns.cells(payload, columns)
    rows = [[int(grid[row][col]) for col in range(1, len(grid[row]) + 1)] for row in range(1, len(grid) + 1)]
    assert rows == [list(row) for row in strip.encode_cells(payload, columns=columns)]
