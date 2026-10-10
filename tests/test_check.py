"""The snapshot check that turns the first real /reload into a checklist result. Synthetic data only."""

import json
import re
from pathlib import Path

import pytest

from wow_helper import __main__ as cli
from wow_helper import check
from wow_helper.savedvars import SavedVariablesError, parse

FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = FIXTURES / "savedvariables_check.lua"      # addon 0.4.0, modern API
OLDER = FIXTURES / "savedvariables_quests.lua"       # a snapshot from before client info existed
ADDON = Path(__file__).resolve().parents[1] / "wow_addon" / "WoWCompanion"


def result(path=CURRENT, **kwargs):
    kwargs.setdefault("interfaces", [16001, 120001])
    kwargs.setdefault("now", 1030)
    return check.report(parse(path.read_text(encoding="utf-8")), 1000, **kwargs)


def by_name(report):
    return {c["check"]: c for c in report["checks"]}


def test_current_addon_on_a_modern_client_confirms_every_check():
    report = result()
    assert report["counts"] == {"confirmed": 13, "missing": 0, "mismatch": 0}
    checks = by_name(report)
    assert checks["client_build"]["detail"] == "client 1.60.1 build 99999, interface 16001"
    assert checks["toc_interface"]["detail"] == "the .toc lists interface 16001"
    assert checks["quest_log"]["detail"] == "2 quests saved, 1 collapsed headers"
    assert checks["objective_counts"]["detail"] == "2 of 3 objectives carry counts"
    assert checks["distance"]["detail"] == "distance reported for 1 of 2 quests"
    assert checks["completed_quests"]["detail"] == "2 completed quest IDs"
    assert checks["available_quests"]["detail"].startswith("0 quests listed for map 9001; the game may list only")
    assert checks["character_status"]["detail"] == "money, 1 gear slots, 12 of 40 bag slots free"
    assert checks["player"]["detail"] == "level 12 warrior"
    assert checks["api_sources"]["detail"] == ("available from C_QuestLine, bags from C_Container, completed from C_QuestLog, "
                                               "distance from C_QuestLog, itemLevel from C_Item, objectives from C_QuestLog")
    assert report["client"] == {"version": "1.60.1", "build": "99999", "interface": 16001}
    assert report["warnings"] == []


def test_older_addon_snapshot_names_what_is_missing():
    report = result(OLDER)
    checks = by_name(report)
    assert {name for name, c in checks.items() if c["result"] == "missing"} == {
        "addon_version", "client_build", "toc_interface", "distance", "api_sources"}
    assert checks["addon_version"]["detail"] == "saved by an addon older than 0.4.0; run install-addon and /reload"
    assert checks["toc_interface"]["detail"] == "unknown until the addon saves the client build"
    assert checks["objective_counts"]["result"] == "confirmed"  # the older fixture already carried counts
    assert report["counts"]["mismatch"] == 0


def test_interface_outside_the_toc_is_a_mismatch_with_the_fix_spelled_out():
    parsed = parse(CURRENT.read_text(encoding="utf-8"))
    parsed["WoWCompanionDB"]["client"]["interface"] = 11507
    parsed["WoWCompanionDB"]["addon"] = "0.3.9"
    parsed["WoWCompanionDB"]["schema"] = 2
    report = check.report(parsed, 1000, now=1030, interfaces=[16001, 120001])
    checks = by_name(report)
    assert checks["toc_interface"]["result"] == "mismatch"
    assert checks["toc_interface"]["detail"] == ("the client reports interface 11507 but the .toc lists 16001, 120001; "
                                                 "tick Load out of date AddOns, then update the .toc")
    assert checks["addon_version"]["detail"] == "addon 0.3.9 saved it; this helper ships 0.4.0; run install-addon and /reload"
    assert checks["schema"]["detail"] == "data version 2; this helper reads 1"
    assert report["counts"]["mismatch"] == 3


def test_empty_or_classic_shapes_do_not_crash():
    parsed = {"WoWCompanionDB": {"schema": 1, "api": "classic", "quests": [], "player": {}}}
    checks = by_name(check.report(parsed, 1000, now=1030, interfaces=[16001]))
    assert checks["quest_log"]["result"] == "missing"
    assert checks["objective_counts"]["detail"] == "no objectives saved; pick up a quest with a counter, then /reload"
    assert checks["completed_quests"]["result"] == "missing"
    assert checks["available_quests"]["result"] == "missing"
    assert checks["character_status"]["result"] == "missing"
    assert checks["player"]["result"] == "missing"
    with pytest.raises(SavedVariablesError):
        check.report(parse("Other = 1"), 1000, now=1030, interfaces=[16001])


def test_stale_snapshot_warns():
    report = result(now=1000 + 20 * 60)
    assert report["warnings"] == ["The snapshot is 20 minutes old; /reload in game and check again."]


def test_text_and_json_carry_no_zone_quest_title_or_path():
    report = result(flavor="_classic_beta_")
    text = check.as_text(report)
    lines = text.splitlines()
    assert lines[0] == "Snapshot check from just now (edition _classic_beta_): 13 confirmed, 0 missing, 0 mismatched."
    assert lines[1] == "  confirmed  addon_version: addon 0.4.0 saved this snapshot"
    assert len(lines) == 14
    for leak in ("Testvale", "Example", "Synthetic", "Otherfield", "\\", "/"):
        assert leak not in text and leak not in json.dumps(report)


def test_toc_version_and_interfaces_match_the_helper_and_the_addon():
    interfaces, version = check.toc_lines()
    assert interfaces == [16001, 120001]
    assert version == check.ADDON_VERSION
    lua = (ADDON / "WoWCompanion.lua").read_text(encoding="utf-8")
    assert re.search(r'^local ADDON_VERSION = "([^"]+)"', lua, re.M).group(1) == check.ADDON_VERSION


def test_cli_check_snapshot(capsys):
    assert cli.main(["check-snapshot", "--file", str(CURRENT)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok" and report["counts"]["confirmed"] == 13 and report["flavor"] is None
    assert cli.main(["check-snapshot", "--file", str(CURRENT), "--text"]) == 0
    assert capsys.readouterr().out.startswith("Snapshot check from ")
    assert cli.main(["check-snapshot", "--file", str(CURRENT), "--flavor", "_retail_"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
