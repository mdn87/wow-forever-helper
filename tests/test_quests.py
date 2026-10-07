"""Quest snapshot, advice order, and the quests/install-addon CLI, with synthetic data only."""

import json
import os
import shutil
from pathlib import Path

import pytest

from wow_helper import __main__ as cli
from wow_helper import quests, wtf
from wow_helper.savedvars import SavedVariablesError, parse

FIXTURE = Path(__file__).parent / "fixtures" / "savedvariables_quests.lua"


def snapshot():
    return quests.load(parse(FIXTURE.read_text(encoding="utf-8")))


def test_plan_puts_turn_ins_first_and_hard_quests_last():
    steps = quests.plan(snapshot())
    assert [(s["id"], s["action"]) for s in steps] == [
        (900001, "turn in"),   # done
        (900006, "restart"),   # failed
        (900002, "finish"),    # in the player's zone
        (900003, "finish"),    # another zone, nearly done
        (900004, "finish"),    # gray: last of the doable ones
        (900005, "later"),     # six levels up, group of three
    ]
    by_id = {s["id"]: s for s in steps}
    assert by_id[900002]["remaining"] == ["Synthetic Pelt: 3/8"]
    assert by_id[900003]["remaining"] == ["Test Kobold slain (9/10)"]
    assert "more than half done" in by_id[900003]["notes"]
    assert any("low XP" in n for n in by_id[900004]["notes"])
    assert by_id[900004]["remaining"] == ["Talk to the Example Clerk"]
    assert by_id[900005]["notes"] == ["level 18 is well above you", "group quest for 3 players"]
    assert by_id[900002]["link"] == "https://www.wowhead.com/classic/quest=900002"
    assert quests.plan(snapshot(), "_retail_")[0]["link"] == "https://www.wowhead.com/quest=900001"


def test_nearby_objectives_come_first_within_the_zone():
    snap = snapshot()
    snap.quests = [q for q in snap.quests if q.id in (900002, 900004)]
    for quest in snap.quests:
        quest.level, quest.objectives = 12, []
    snap.quests[0].distance, snap.quests[1].distance = 400, 90
    assert [s["id"] for s in quests.plan(snap)] == [900004, 900002]


def test_gray_level_follows_the_classic_rule():
    assert [quests.gray_level(n) for n in (1, 5, 6, 12, 39, 40, 60)] == [0, 0, 1, 6, 31, 31, 47]


def test_report_warns_about_stale_data_and_hidden_quests():
    snap = snapshot()
    snap.collapsed = ["Otherfield"]
    result = quests.report(snap, mtime=1000, now=1000 + 20 * 60)
    assert result["age_seconds"] == 1200
    assert any("20 minutes old" in w for w in result["warnings"])
    assert any("Otherfield" in w for w in result["warnings"])
    fresh = quests.report(snapshot(), mtime=1000, now=1030)
    assert fresh["warnings"] == [] and fresh["quest_count"] == 6


def test_text_output_reads_as_a_short_list():
    text = quests.as_text(quests.report(snapshot(), mtime=1000, now=1030))
    lines = text.splitlines()
    assert lines[0] == "Quest log from just now: level 12 Warrior in Testvale, 6 quests."
    assert lines[1] == "1. Turn in: Synthetic Delivery (Testvale; objectives done; hand it in)"
    assert lines[3].startswith("3. Finish: Gather Synthetic Pelts (Testvale; Synthetic Pelt: 3/8")


def test_available_quests_skip_ones_in_the_log_or_already_done():
    result = quests.report(snapshot(), mtime=1000, now=1030)
    assert result["completed_count"] == 3
    assert [(a["id"], a["x"], a["y"], a["daily"]) for a in result["available"]] == [
        (900020, 45.1, 62.0, False), (900021, None, None, True)]
    assert result["available"][0]["quest_line"] == "Example Storyline"
    assert result["available"][0]["link"] == "https://www.wowhead.com/classic/quest=900020"
    lines = quests.as_text(result).splitlines()
    assert lines[-2:] == ["To pick up here: Synthetic Welcome (at 45.1, 62); Test Board Notice.",
                          "3 quests completed on this character."]


def test_available_quests_are_optional_and_an_empty_list_is_explained():
    old = quests.report(quests.load(parse('WoWCompanionDB = { ["schema"] = 1, ["quests"] = {} }')), mtime=1000, now=1000)
    assert old["available"] is None and old["completed_count"] is None
    assert quests.as_text(old).splitlines()[1:] == []
    empty = quests.load(parse('WoWCompanionDB = { ["quests"] = {}, ["available"] = {}, '
                              '["completedQuests"] = { 900010, "x", 0 } }'))
    result = quests.report(empty, mtime=1000, now=1000)
    assert result["available"] == [] and result["completed_count"] == 1
    assert "no quests to pick up" in quests.as_text(result)


def test_a_file_without_the_addon_table_is_refused():
    with pytest.raises(SavedVariablesError, match="/reload"):
        quests.load(parse("OtherAddonDB = {}"))


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """The CLI with no real install visible and settings kept in tmp_path."""
    monkeypatch.setattr(wtf, "registry_roots", lambda: [])
    monkeypatch.setattr(wtf, "DEFAULT_ROOTS", ())
    monkeypatch.setattr(cli, "SETTINGS", tmp_path / "runtime" / "companion.json")
    monkeypatch.setattr("time.sleep", lambda _: None)

    def invoke(*args):
        code = cli.main(list(args))
        return code, capsys.readouterr().out
    return invoke


def fake_install(root, flavor="_classic_beta_"):
    folder = root / flavor / "WTF" / "Account" / "000000000" / "SavedVariables"
    folder.mkdir(parents=True)
    shutil.copyfile(FIXTURE, folder / "WoWCompanion.lua")
    return folder


def test_cli_finds_the_newest_snapshot_and_never_prints_paths(run, tmp_path):
    root = tmp_path / "Games" / "World of Warcraft"
    fake_install(root)
    code, out = run("quests", "--wow-root", str(root))
    result = json.loads(out)
    assert code == 0 and result["status"] == "ok" and result["plan"][0]["id"] == 900001
    assert str(tmp_path) not in out and "000000000" not in out and "Games" not in out
    # The root is remembered for the next call (for example one started by voice).
    code, text = run("quests", "--text")
    assert code == 0 and text.startswith("Quest log from")


def test_cli_reads_an_explicit_file(run):
    code, out = run("quests", "--file", str(FIXTURE))
    assert code == 0 and json.loads(out)["quest_count"] == 6


@pytest.mark.parametrize("command,items", [("quests", "plan"), ("character", "gear")])
def test_cli_can_select_an_older_edition_snapshot(run, tmp_path, command, items):
    root = tmp_path / "Games"
    classic = fake_install(root) / "WoWCompanion.lua"
    retail = fake_install(root, "_retail_") / "WoWCompanion.lua"
    retail.write_text(FIXTURE.read_text(encoding="utf-8")
                      .replace("Synthetic Delivery", "Synthetic Retail Delivery")
                      .replace("123456", "200000"), encoding="utf-8")
    os.utime(classic, (1000, 1000))
    os.utime(retail, (2000, 2000))

    code, out = run(command, "--wow-root", str(root), "--flavor", "_classic_beta_")
    assert code == 0
    report = json.loads(out)
    assert "/classic/" in report[items][0]["link"]
    assert (report["plan"][0]["title"] == "Synthetic Delivery" if command == "quests"
            else report["gold"] == "12g 34s 56c")
    assert str(tmp_path) not in out and "000000000" not in out

    # The edition selection applies to this call only; the default stays newest overall.
    code, out = run(command)
    assert code == 0
    report = json.loads(out)
    assert "/classic/" not in report[items][0]["link"]
    assert (report["plan"][0]["title"] == "Synthetic Retail Delivery" if command == "quests"
            else report["gold"] == "20g")


@pytest.mark.parametrize("command", ["quests", "character"])
def test_cli_refuses_a_missing_edition_without_falling_back(run, tmp_path, command):
    root = tmp_path / "Games"
    fake_install(root, "_retail_")
    code, out = run(command, "--wow-root", str(root), "--flavor", "_classic_beta_")
    assert code == 2
    assert json.loads(out) == {"status": "refused", "message":
        "No snapshot found for the selected game edition. Install the addon there, then /reload in that edition."}


@pytest.mark.parametrize("command", ["quests", "character"])
def test_cli_refuses_combining_file_and_edition(run, command):
    code, out = run(command, "--file", str(FIXTURE), "--flavor", "_retail_")
    assert code == 2
    assert json.loads(out) == {"status": "refused", "message":
        "Choose either an explicit snapshot file or a game edition, not both."}


def test_newest_selects_the_latest_matching_snapshot_across_roots(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    older = fake_install(first) / "WoWCompanion.lua"
    newer = fake_install(second) / "WoWCompanion.lua"
    retail = fake_install(first, "_retail_") / "WoWCompanion.lua"
    for path, at in [(older, 1000), (newer, 2000), (retail, 3000)]:
        os.utime(path, (at, at))
    assert wtf.newest([first, second], only="_classic_beta_") == ("_classic_beta_", newer)
    assert wtf.newest([first, second]) == ("_retail_", retail)


def test_cli_without_a_snapshot_explains_the_next_step(run, tmp_path):
    code, out = run("quests", "--wow-root", str(tmp_path))
    assert code == 2
    assert json.loads(out) == {"status": "refused",
                               "message": "No quest snapshot found. Install the addon, then /reload in game."}


def test_install_addon_copies_only_into_game_folders_that_have_run(run, tmp_path):
    root = tmp_path / "World of Warcraft"
    fake_install(root, "_classic_beta_")
    (root / "_never_run_").mkdir()
    code, out = run("install-addon", "--wow-root", str(root))
    assert code == 0 and json.loads(out)["flavors"] == ["_classic_beta_"]
    installed = root / "_classic_beta_" / "Interface" / "AddOns" / "WoWCompanion"
    assert sorted(p.name for p in installed.iterdir()) == ["WoWCompanion.lua", "WoWCompanion.toc"]
    assert not (root / "_never_run_" / "Interface").exists()
    assert str(tmp_path) not in out


def test_the_addon_declares_its_saved_variable_and_file():
    toc = (wtf.ADDON_SOURCE / "WoWCompanion.toc").read_text(encoding="utf-8")
    assert "## SavedVariables: WoWCompanionDB" in toc and "WoWCompanion.lua" in toc
    lua = (wtf.ADDON_SOURCE / "WoWCompanion.lua").read_text(encoding="utf-8")
    assert "WoWCompanionDB" in lua and "print(" not in lua
