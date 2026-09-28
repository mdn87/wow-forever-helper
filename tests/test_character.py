"""Character status from the companion snapshot, and the character CLI, with synthetic data only."""

import json
from pathlib import Path

import pytest

from wow_helper import __main__ as cli
from wow_helper import character, wtf
from wow_helper.savedvars import SavedVariablesError, parse

FIXTURE = Path(__file__).parent / "fixtures" / "savedvariables_quests.lua"


def result(**kwargs):
    return character.report(parse(FIXTURE.read_text(encoding="utf-8")), 1000, now=1030, **kwargs)


def test_status_sums_up_gold_rest_gear_and_bags():
    status = result()
    assert status["gold"] == "12g 34s 56c" and status["copper"] == 123456
    assert status["rested_percent_of_level"] == 50
    assert status["average_item_level"] == 14.0  # the shirt does not count
    assert status["lowest_durability"] == {"slot": "legs", "percent": 20}
    assert status["bags"] == {"free": 2, "total": 40}
    assert [g["slot"] for g in status["gear"]] == ["head", "shirt", "legs", "main hand"]
    assert status["gear"][0]["link"] == "https://www.wowhead.com/classic/item=900101"
    assert result(flavor="_retail_")["gear"][0]["link"] == "https://www.wowhead.com/item=900101"
    assert status["warnings"] == ["Repair soon: the legs item is at 20%.", "Bags nearly full: 2 free slots."]


def test_text_is_one_speakable_line_plus_warnings():
    lines = character.as_text(result()).splitlines()
    assert lines[0] == ("Character status from just now: 12g 34s 56c gold, rested for 50% of a level, "
                        "2 of 40 bag slots free, most worn item 20% (legs), average item level 14.")
    assert lines[1:] == ["Repair soon: the legs item is at 20%.", "Bags nearly full: 2 free slots."]


def test_gold_formatting():
    assert [character.gold(n) for n in (0, 5, 100, 10000, 10203)] == ["0c", "5c", "1s", "1g", "1g 2s 3c"]


def test_broken_gear_and_stale_data_are_called_out():
    parsed = parse('WoWCompanionDB = { ["player"] = {}, ["character"] = { ["gear"] = { '
                   '{ ["slot"] = 8, ["id"] = 900105, ["durability"] = 0, ["durabilityMax"] = 30 } } } }')
    status = character.report(parsed, 1000, now=1000 + 16 * 60)
    assert status["warnings"] == ["The snapshot is 16 minutes old; /reload in game for current status.",
                                  "Repair soon: the feet item is broken."]
    assert status["gold"] is None and status["bags"] is None and status["average_item_level"] is None
    assert character.as_text(status).startswith("Character status from 16 minutes ago: most worn item 0% (feet).")


def test_junk_entries_are_skipped():
    parsed = parse('WoWCompanionDB = { ["character"] = { ["money"] = "lots", ["gear"] = { 7, '
                   '{ ["slot"] = 99, ["id"] = 1 }, { ["slot"] = 2 } } } }')
    status = character.report(parsed, 1000, now=1000)
    assert status["gear"] == [] and status["gold"] is None


def test_an_old_addon_without_character_status_is_refused():
    with pytest.raises(SavedVariablesError, match="update it"):
        character.report(parse('WoWCompanionDB = { ["quests"] = {} }'), 1000, now=1000)


def test_character_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wtf, "registry_roots", lambda: [])
    monkeypatch.setattr(wtf, "DEFAULT_ROOTS", ())
    monkeypatch.setattr(cli, "SETTINGS", tmp_path / "runtime" / "companion.json")
    monkeypatch.setattr("time.sleep", lambda _: None)
    assert cli.main(["character", "--file", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["gold"] == "12g 34s 56c" and str(tmp_path) not in out
    assert cli.main(["character", "--file", str(FIXTURE), "--text"]) == 0
    assert capsys.readouterr().out.startswith("Character status from")
