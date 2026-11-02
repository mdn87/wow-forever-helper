"""Synthetic combat logs only: Testchar/Otherchar/Healchar on ExampleRealm against an invented Example Boss."""

import json
import os
from pathlib import Path
import time

import pytest

from wow_helper import combat_log
from wow_helper.chat import ChatError
from wow_helper.combat_log import TEXT_LIMIT, _Clock, find_combat_log, last_encounter_digest

FIXTURES = Path(__file__).parent / "fixtures" / "combat_log"
FORBIDDEN = ("Player-", "Creature-", "Pet-", "ExampleRealm", "0000000000000000", "0x512", "0xa48")
BOSS = 'Creature-0-0000-0000-00000-99999-0000000001,"Example Boss",0xa48,0x0'
NOBODY = "0000000000000000,nil,0x80000000,0x80000000"
HEADER = "COMBAT_LOG_VERSION,22,ADVANCED_LOG_ENABLED,1,BUILD_VERSION,11.0.5,PROJECT_ID,1"


def digest(name, **options):
    return last_encounter_digest(FIXTURES / name, **options)


def stamp(seconds):
    hours, rest = divmod(20 * 3600 + seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"11/4/2026 {int(hours):02d}:{int(minutes):02d}:{secs:07.4f}-5"


def guid(n):
    return f"Player-0000-{n:08d}"


def player(n):
    return f'{guid(n)},"Testchar{chr(97 + n % 26)}-ExampleRealm",0x512,0x0'


def adv(info, current=90000, maximum=100000):
    return f"{info},0000000000000000,{current},{maximum},1000,2000,3000,0,0,100,100,0,10.00,20.00,2000,1.5700,80"


def hit(seconds, n, spell_id, spell, amount, overkill=-1):
    return (f"{stamp(seconds)}  SPELL_DAMAGE,{BOSS},{player(n)},{spell_id},\"{spell}\",32,{adv(guid(n))},"
            f"{amount},{amount},{overkill},32,0,0,0,nil,nil,nil,ST")


def write_log(path, lines):
    path.write_text("# synthetic generated combat log for tests; no real play data\n" + "\n".join(lines) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def generated(path, players=4, deaths=(), spells=1, spell_name="Example Blast", lines=0, end=True):
    """A Retail-style advanced log: casts, steady damage to players, and listed (time, player) deaths."""
    out = [f"{stamp(0)}  {HEADER}", f'{stamp(1)}  ENCOUNTER_START,9999,"Example Boss",16,20,2000']
    out += [f"{stamp(1.5)}  SPELL_CAST_SUCCESS,{player(n)},{BOSS},100,\"Example Strike\",1,{adv(guid(n))}"
            for n in range(players)]
    count = max(lines, players * 4)
    for i in range(count):
        seconds = 2 + i * 0.01
        out.append(hit(seconds, i % players, 400000 + i % spells, f"{spell_name} {i % spells}", 1000 + i % 7))
    tail = 2 + count * 0.01
    for seconds, n in deaths:
        at = max(seconds, tail)
        out.append(hit(at, n, 400000, f"{spell_name} 0", 50000, 2000))
        out.append(f"{stamp(at + 0.05)}  UNIT_DIED,{NOBODY},{player(n)},0")
        tail = at + 0.1
    if end:
        out.append(f'{stamp(tail + 1)}  ENCOUNTER_END,9999,"Example Boss",16,20,0,{int((tail - 1) * 1000)}')
    return write_log(path, out)


def assert_private(result):
    blob = result["text"] + json.dumps(result["data"]) + json.dumps(result["gaps"])
    for value in FORBIDDEN:
        assert value not in blob


# Retail-style advanced log with baseAmount


def test_retail_wipe_reports_deaths_layout_and_fight_time():
    result = digest("retail_advanced_wipe.txt")
    data = result["data"]
    assert result["status"] == "ok"
    assert data["encounter"] == {"id": 9999, "name": "Example Boss", "difficulty_id": 16, "group_size": 20,
                                 "instance_id": 2000, "result": "wipe", "duration_s": 95.0,
                                 "duration_source": "fightTime"}
    assert data["log"] == {"version": "22", "build": "11.0.5", "project": "1", "advanced": True}
    assert data["layout"]["advanced_fields"] == 17 and data["layout"]["base_amount"] is True
    assert data["layout"]["advanced_length_from"] == "cast events"
    assert data["totals"] == {"player_deaths": 3, "players_seen": 4}
    assert [death["who"] for death in data["deaths"]] == ["Player 1", "Player 2", "Player 4"]
    assert [death["at_s"] for death in data["deaths"]] == [25.1, 55.2, 85.3]
    assert "Result: wipe; duration 1:35 (from fightTime)" in result["text"]
    assert len(result["text"].encode("utf-8")) <= TEXT_LIMIT


def test_one_shot_reports_overkill_and_high_hp_from_the_players_own_sample():
    one_shot = digest("retail_advanced_wipe.txt")["data"]["deaths"][0]
    assert one_shot["killing_blow"] == {"spell": "Example Annihilation", "spell_id": 400002, "source": "Example Boss",
                                        "amount": 400000, "overkill": 305000, "basis": "overkill"}
    # The +27 s line carries the boss's advanced info (0.5 % HP); only the player's own sample counts.
    assert one_shot["hp_percent_3s_before"] == 98
    assert one_shot["final_10s"]["total"] == 403000
    assert one_shot["last_hits"][0]["seconds_before"] == 0.1 and one_shot["last_hits"][0]["overkill"] is True


def test_attrition_and_no_overkill_deaths():
    deaths = digest("retail_advanced_wipe.txt")["data"]["deaths"]
    attrition, melee = deaths[1], deaths[2]
    assert attrition["hp_percent_3s_before"] == 22
    assert attrition["final_10s"] == {"total": 61000, "top_spells": [
        {"spell": "Example Rot", "spell_id": 400003, "total": 61000}]}
    assert len(attrition["last_hits"]) == 8
    assert melee["killing_blow"]["basis"] == "last hit, no overkill recorded"
    assert melee["killing_blow"]["spell"] == "Melee" and melee["killing_blow"]["overkill"] is None
    assert melee["hp_percent_3s_before"] is None
    assert "unknown (advanced combat logging off or no sample)" in digest("retail_advanced_wipe.txt")["text"]


def test_landed_variants_and_lines_after_the_end_are_ignored():
    result = digest("retail_advanced_wipe.txt")
    table = {row["spell"]: row for row in result["data"]["damage_taken_by_spell"]}
    assert table["Melee"] == {"spell": "Melee", "spell_id": None, "total": 140000, "hits": 8, "killing_blows": 1,
                              "players_hit": 2}
    assert table["Example Annihilation"]["total"] == 400000 and table["Example Annihilation"]["hits"] == 1
    assert table["Falling"]["total"] == 2000
    for value in ("888,888", "999,999", "777,777"):
        assert value not in result["text"]


def test_hp_requires_info_guid_to_match_the_destination(tmp_path):
    lines = [f"{stamp(0)}  {HEADER}", f'{stamp(1)}  ENCOUNTER_START,9999,"Example Boss",16,20,2000',
             f"{stamp(1.5)}  SPELL_CAST_SUCCESS,{player(1)},{BOSS},100,\"Example Strike\",1,{adv(guid(1))}",
             # Only a sample about another unit exists before the death.
             f"{stamp(5)}  SPELL_DAMAGE,{BOSS},{player(1)},400001,\"Example Jab\",1,"
             f"{adv('Creature-0-0000-0000-00000-99999-0000000001', 10, 100000)},10,10,-1,1,0,0,0,nil,nil,nil",
             hit(9, 1, 400002, "Example Blast", 90000, 5000),
             f"{stamp(9.1)}  UNIT_DIED,{NOBODY},{player(1)},0",
             f'{stamp(10)}  ENCOUNTER_END,9999,"Example Boss",16,20,0,9000']
    death = last_encounter_digest(write_log(tmp_path / "hp.txt", lines))["data"]["deaths"][0]
    assert death["hp_percent_3s_before"] is None


# Classic-style log without advanced fields or baseAmount


def test_classic_kill_without_advanced_fields():
    result = digest("classic_kill.txt")
    data = result["data"]
    assert result["status"] == "ok"
    assert data["encounter"]["result"] == "kill" and data["encounter"]["duration_source"] == "timestamps"
    assert data["encounter"]["duration_s"] == 44.0
    assert data["layout"]["advanced_fields"] == 0 and data["layout"]["base_amount"] is False
    assert data["totals"]["player_deaths"] == 1
    death = data["deaths"][0]
    assert death["killing_blow"]["spell"] == "Example Smash" and death["killing_blow"]["overkill"] == 1200
    assert death["hp_percent_3s_before"] is None
    assert any("Advanced combat logging was off" in gap for gap in result["gaps"])


def test_incomplete_encounter():
    result = digest("classic_incomplete.txt")
    assert result["status"] == "incomplete"
    assert result["data"]["encounter"]["result"] == "unknown"
    assert any("no ENCOUNTER_END" in gap for gap in result["gaps"])


def test_no_markers_falls_back_to_the_last_window():
    result = digest("classic_no_markers.txt")
    assert result["status"] == "no_encounter_markers"
    assert result["data"]["encounter"] is None and result["data"]["window"]["kind"] == "fallback"
    assert result["data"]["totals"]["player_deaths"] == 1
    assert any("No ENCOUNTER_START" in gap for gap in result["gaps"])


def test_fallback_window_is_180_seconds_before_the_final_timestamp(tmp_path):
    lines = [f"{stamp(0)}  {HEADER}",
             f"{stamp(0.5)}  SPELL_CAST_SUCCESS,{player(1)},{BOSS},100,\"Example Strike\",1,{adv(guid(1))}",
             hit(1, 1, 400001, "Example Early", 90000, 10), f"{stamp(1.1)}  UNIT_DIED,{NOBODY},{player(1)},0"]
    lines += [hit(10 + i, 2, 400002, "Example Blast", 100) for i in range(400)]
    lines.insert(-100, f"{stamp(310)}  SPELL_CAST_SUCCESS,{player(2)},{BOSS},100,\"Example Strike\",1,{adv(guid(2))}")
    lines += [hit(409.5, 3, 400003, "Example Late", 90000, 10), f"{stamp(409.6)}  UNIT_DIED,{NOBODY},{player(3)},0"]
    result = last_encounter_digest(write_log(tmp_path / "fallback.txt", lines))
    assert result["status"] == "no_encounter_markers"
    assert result["data"]["window"]["seconds"] == 180.0
    assert [death["killing_blow"]["spell"] for death in result["data"]["deaths"]] == ["Example Late"]


def test_the_later_of_two_encounters_is_chosen():
    result = digest("classic_two_encounters.txt")
    assert result["data"]["encounter"]["name"] == "Example Boss"
    assert result["data"]["encounter"]["result"] == "wipe"
    assert result["data"]["totals"]["player_deaths"] == 1
    assert "Example Warden" not in result["text"]


def test_midnight_rollover_keeps_time_monotonic():
    result = digest("classic_midnight.txt")
    assert result["status"] == "ok"
    assert result["data"]["encounter"]["duration_s"] == 50.0
    assert result["data"]["deaths"][0]["at_s"] == 34.2


def test_clock_wraps_without_a_date_change_and_across_a_year():
    clock = _Clock()
    assert clock("5/12 23:59:59.000") == pytest.approx(86399.0)
    assert clock("5/12 00:00:01.000") == pytest.approx(86401.0)
    clock = _Clock()
    first = clock("12/31 23:59:59.500")
    assert clock("1/1 00:00:00.500") - first == pytest.approx(1.0)
    clock = _Clock()
    first = clock("11/4/2026 20:15:00.1234-5")
    assert clock("11/4/2026 20:15:01.5000+3") - first == pytest.approx(1.3766)
    assert clock("not a time") is None and clock("13/40 10:00:00.000") is None


# Coverage limits and failures


def test_truncated_tail_records_a_gap(tmp_path):
    result = digest("classic_kill.txt", max_bytes=1500)
    assert result["data"]["read"]["truncated"] is True
    assert any(gap.startswith("Only the last 1,500 bytes of the log were read") for gap in result["gaps"])
    # The header and the encounter start fell outside what was read.
    assert result["status"] == "no_encounter_markers"
    assert any("COMBAT_LOG_VERSION" in gap for gap in result["gaps"])
    assert_private(result)


def test_line_cap_records_a_gap(monkeypatch):
    monkeypatch.setattr(combat_log, "MAX_LINES", 10)
    result = digest("classic_kill.txt")
    assert any("Reading stopped after 10 lines" in gap for gap in result["gaps"])


def test_unsupported_layout_makes_no_numeric_claims():
    result = digest("unsupported_layout.txt")
    assert result["status"] == "unsupported_layout"
    assert result["data"]["layout"] is None
    assert not {"deaths", "damage_taken_by_spell", "totals"} & set(result["data"])
    assert "version 9" in result["gaps"][0]
    for value in ("4242", "Player deaths", "died at", "Damage taken by", "Killing blow", "Totals"):
        assert value not in result["text"]


def test_ambiguous_advanced_length_without_cast_witness_is_unsupported(tmp_path):
    lines = (FIXTURES / "retail_advanced_wipe.txt").read_text(encoding="utf-8").splitlines()
    stripped = write_log(tmp_path / "no_casts.txt", [line for line in lines if "SPELL_CAST_SUCCESS" not in line])
    # Damage alone cannot tell 17 fields + baseAmount from 18 fields without it.
    assert last_encounter_digest(stripped)["status"] == "unsupported_layout"


def test_empty_logs(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert last_encounter_digest(empty)["status"] == "empty"
    comment_only = write_log(tmp_path / "comment.txt", [])
    result = last_encounter_digest(comment_only)
    assert result["status"] == "empty" and result["gaps"]


@pytest.mark.parametrize("target", ["missing.txt", "folder"])
def test_unreadable_path_raises_without_the_path(tmp_path, target):
    folder = tmp_path / "Secretfolder"
    folder.mkdir()
    (folder / "folder").mkdir()
    path = folder / target
    with pytest.raises(ChatError) as error:
        last_encounter_digest(path)
    message = str(error.value)
    assert message.startswith("The combat log could not be read.")
    assert "Secretfolder" not in message and str(tmp_path) not in message and target not in message


# Labels and privacy


def test_include_names_strips_realms():
    result = digest("retail_advanced_wipe.txt", include_names=True)
    assert [death["who"] for death in result["data"]["deaths"]] == ["Testchar", "Otherchar", "Healchar"]
    assert_private(result)


@pytest.mark.parametrize("own", ["Testchar", "testchar-ExampleRealm"])
def test_own_name_is_labelled_you(own):
    result = digest("retail_advanced_wipe.txt", own_name=own)
    assert [death["who"] for death in result["data"]["deaths"]] == ["You", "Player 1", "Player 3"]
    named = digest("retail_advanced_wipe.txt", own_name=own, include_names=True)
    assert [death["who"] for death in named["data"]["deaths"]] == ["You", "Otherchar", "Healchar"]


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURES.iterdir()))
@pytest.mark.parametrize("names", [False, True])
def test_guids_and_realms_never_appear(name, names):
    assert_private(digest(name, include_names=names, own_name="Otherchar"))


def test_fixtures_are_labelled_synthetic():
    for path in FIXTURES.iterdir():
        assert path.read_text(encoding="utf-8").startswith("# synthetic ")


# Bounds and performance


def test_text_stays_within_the_byte_bound_with_many_deaths(tmp_path):
    long_name = "Example Very Long Spell Name " * 8
    path = generated(tmp_path / "many.txt", players=30, spells=14, spell_name=long_name, lines=600,
                     deaths=[(10 + i, i % 30) for i in range(120)])
    result = last_encounter_digest(path)
    data = result["data"]
    assert result["status"] == "ok"
    assert len(result["text"].encode("utf-8")) <= TEXT_LIMIT
    assert data["totals"]["player_deaths"] == 120
    assert len(data["deaths"]) == 40 and data["deaths_not_shown"] == 80
    assert len(data["damage_taken_by_spell"]) == 10 and data["spells_not_shown"] == 4
    assert "more deaths not shown" in result["text"] and "4 more spells not shown" in result["text"]
    assert all(len(row["spell"]) <= 60 for row in data["damage_taken_by_spell"])
    assert_private(result)


def test_large_log_digests_quickly(tmp_path):
    path = generated(tmp_path / "large.txt", players=20, spells=12, lines=300_000,
                     deaths=[(3000 + i, i % 20) for i in range(30)])
    size = path.stat().st_size
    started = time.perf_counter()
    result = last_encounter_digest(path, max_bytes=size)  # every line, not just the default tail
    elapsed = time.perf_counter() - started
    assert result["status"] == "ok" and result["data"]["totals"]["player_deaths"] == 30
    assert sum(1 for _ in path.open(encoding="utf-8")) >= 300_000
    assert elapsed < 15, f"digest took {elapsed:.1f} s"


# Finding the log


def test_find_combat_log_picks_the_newest_timestamped_file(tmp_path):
    first, second = tmp_path / "RootA", tmp_path / "RootB"
    older = first / "_retail_" / "Logs" / "WoWCombatLog-110324_201530.txt"
    newer = second / "_retail_" / "Logs" / "WoWCombatLog-110424_201530.txt"
    other_flavor = first / "_classic_" / "Logs" / "WoWCombatLog.txt"
    decoys = [first / "_retail_" / "Logs" / "OtherLog.txt", first / "_retail_" / "Logs" / "WoWCombatLog-old.zip"]
    for index, path in enumerate([older, newer, other_flavor, *decoys]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic\n", encoding="utf-8")
        os.utime(path, (1_000_000 + index * 100, 1_000_000 + index * 100))
    for decoy in (*decoys, other_flavor):
        os.utime(decoy, (2_000_000, 2_000_000))
    (first / "_retail_" / "Logs" / "WoWCombatLog-folder.txt").mkdir()
    try:
        link = first / "_retail_" / "Logs" / "WoWCombatLog-link.txt"
        link.symlink_to(older)
        os.utime(link, (3_000_000, 3_000_000), follow_symlinks=False)
    except (OSError, NotImplementedError):
        pass  # symlinks need extra rights on Windows; the folder and decoys still cover the filter
    assert find_combat_log([first, second], "_retail_") == newer
    assert find_combat_log([first], "_classic_") == other_flavor
    assert find_combat_log([first, second, tmp_path / "Missing"], "_beta_") is None
