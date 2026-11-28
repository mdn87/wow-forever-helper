"""Synthetic tests for the spoken walkthrough of the runbook's play-time checks."""

from __future__ import annotations

import json
import re

from wow_helper import __main__ as cli
from wow_helper import live_test_guide
from wow_helper.live_test_guide import ITEMS, MOMENT_WORDS, MOMENTS, LiveTestGuide
from wow_helper.voice_commands import Interpreter

RUNBOOK_IDS = set(
    "2.5 2.13 2.14 4.7 6.4 4.6 "                                   # at login
    "2.1 2.4 2.3 2.2 2.15 2.25 4.8 2.27 6.6 2.17 4.12 4.11 2.26 "  # while you play
    "2.18 2.23 2.24 4.9 4.10 "                                     # after a fight
    "2.22 2.19 2.20 2.21 "                                         # in town
    "4.3 "                                                         # at logout
    "1.25 1.22 1.23 1.24 0.4".split()                              # any time
)


def test_items_are_the_runbook_play_time_checks_grouped_by_moment(tmp_path):
    guide = LiveTestGuide(store=tmp_path / "results.json")
    assert [item.number for item in ITEMS] == list(range(1, 35))
    assert {item.id for item in ITEMS} == RUNBOOK_IDS
    order = [moment.key for moment in MOMENTS]
    assert [order.index(item.moment) for item in ITEMS] == sorted(order.index(item.moment) for item in ITEMS)
    assert cli.LIVE_TEST_MOMENTS == tuple(order)
    assert {item.chip for item in ITEMS} == {"", "#21", "#22", "#23"}
    for item in ITEMS:
        assert set(item.editions) <= {"retail", "forever"}
        spoken = guide.format_spoken_item(item)
        assert spoken.startswith(f"Test {item.number} of 34, ")
        assert len(spoken) <= 700  # comfortable for Lugos Voice TTS and well under the 1200 bridge limit
        assert not re.search(r"[`→×+]", spoken), spoken  # read aloud: no markup or key-chord symbols
        assert "Linen Cloth" not in spoken  # the parked Battle.net checks stay in the runbook's blocked list
    assert "Test 1 of 34, at login, on Retail: Probe status." in guide.format_spoken_item(ITEMS[0])
    assert "Test 30 of 34, any time: Push-to-talk accuracy." in guide.format_spoken_item(ITEMS[29])


def test_progression_pass_fail_skip_goto_reset_and_restart_persistence(tmp_path):
    store = tmp_path / "live-test-results.json"
    guide = LiveTestGuide(store=store)

    assert "Test 1 of 34" in guide.next_prompt()

    _, p2 = guide.record("pass", note="status printed")
    assert "Passed test 1 (status printed)." in p2
    assert "Test 2 of 34" in p2

    _, p3 = guide.record("skipped")
    assert "Skipped test 2." in p3
    assert "Test 3 of 34" in p3

    _, p4 = guide.record("fail", note="pickups empty")
    assert "Failed test 3 (pickups empty)." in p4
    assert "Test 4 of 34" in p4

    reloaded = LiveTestGuide(store=store)
    assert "Test 4 of 34" in reloaded.repeat_prompt()
    assert reloaded.summary()["counts"] == {"pass": 1, "fail": 1, "skipped": 1, "pending": 31}
    status = reloaded.status_spoken()
    assert "1 passed, 1 failed, 1 skipped, 31 pending out of 34." in status
    assert ("Open: 4 at login, 13 while you play, 5 after a fight, 4 in town, 1 at logout, 5 any time. "
            "Next is test 4: Forever quests and links.") in status
    assert json.loads(store.read_text(encoding="utf-8"))["results"]["2.14"]["note"] == "pickups empty"

    p10 = reloaded.goto(10)
    assert "Test 10 of 34, while you play, on Retail: Exclusive fullscreen." in p10
    assert "followed by what you saw" in p10

    reset_msg = reloaded.reset()
    assert "Cleared saved live test results." in reset_msg
    assert "Test 1 of 34" in reset_msg
    assert reloaded.summary()["counts"]["pending"] == 34


def test_moments_jump_and_the_next_test_stays_in_the_same_moment(tmp_path):
    guide = LiveTestGuide(store=tmp_path / "results.json")

    assert "Test 20 of 34, after a fight, on Retail: Bookmark and coaching." in guide.moment("fight")
    assert "Test 21 of 34" in guide.record("pass")[1]
    assert "Test 22 of 34" in guide.record("pass")[1]

    guide.goto(24)
    assert "Test 22 of 34" in guide.record("pass")[1]  # wraps back within the fight tests
    assert "Test 23 of 34" in guide.record("pass")[1]
    assert "Test 25 of 34, in town, on Retail: Research spot check." in guide.record("pass")[1]

    no_fight = guide.moment("fight")
    assert no_fight.startswith("No fight tests are left. Live test status: 5 passed")
    assert "Test 29 of 34, at logout, on Classic Forever: Logout guard." in guide.moment("logout")


def test_edition_offers_its_own_tests_and_those_that_need_no_game(tmp_path):
    store = tmp_path / "results.json"
    guide = LiveTestGuide(store=store)

    first = guide.set_edition("forever")
    assert first.startswith("Playing Classic Forever: offering its tests and the ones that need no game. "
                            "Test 4 of 34, at login, on Classic Forever: Forever quests and links.")
    assert "Test 5 of 34" in guide.record("pass")[1]
    assert "Test 23 of 34, after a fight, on Classic Forever" in guide.moment("fight")
    assert guide.moment("town").startswith("No town tests are left on Classic Forever.")
    assert LiveTestGuide(store=store).summary()["edition"] == "forever"
    assert "Open on Classic Forever: 2 at login," in guide.status_spoken()

    # Record every other offered test: Forever, both editions, and no game.
    for _ in range(15):
        state, spoken = guide.record("pass")
    assert set(state["results"]) == {item.id for item in ITEMS if not item.editions or "forever" in item.editions}
    assert "Every Classic Forever test is recorded. Live test status: 16 passed, 0 failed, 0 skipped, 18 pending" in spoken
    assert "Next is" not in spoken

    assert guide.set_edition(None).startswith("Offering tests for every edition. Test 1 of 34")


def test_skipped_tests_come_back_last(tmp_path):
    guide = LiveTestGuide(store=tmp_path / "results.json")
    for _ in range(33):
        guide.record("pass")
    _, spoken = guide.record("skipped")
    assert spoken.startswith("Skipped test 34. Only skipped tests are left.")
    assert "Next is test 34: Voice turn with no window connected." in spoken
    assert "Test 34 of 34" in guide.next_prompt()
    _, done = guide.record("pass")
    assert done.startswith("Passed test 34. All live tests have been recorded. Live test status: 34 passed")


def test_voice_commands_drive_the_walkthrough(tmp_path, monkeypatch):
    store = tmp_path / "voice-live-tests.json"
    monkeypatch.setattr(live_test_guide, "DEFAULT_STORE", store)
    interp = Interpreter(manager=None, window=None)

    def said(text):
        outcome = interp.handle(text)
        assert outcome.kind == "done", (text, outcome)
        return outcome.detail

    assert "Test 1 of 34" in said("start live test")
    assert "Test 1 of 34" in said("repeat test")
    assert "Passed test 1 (status printed)." in said("pass test status printed")
    assert "Skipped test 2." in said("skip test")
    assert "Test 9 of 34" in said("go to test 9")
    assert "1 passed, 0 failed, 1 skipped, 32 pending" in said("test status")

    for phrase, number in [
        ("fight tests", 20), ("next fight test", 20), ("tests after a fight", 20), ("boss tests", 20),
        ("login tests", 3), ("reload tests", 3), ("tests for login", 3),
        ("play tests", 7), ("tests while playing", 7),
        ("town tests", 25), ("tests in town", 25), ("logout tests", 29), ("tests at logout", 29),
        ("any time tests", 30), ("okay run the anytime tests", 30),
    ]:
        assert f"Test {number} of 34" in said(phrase), phrase
    for word in MOMENT_WORDS:
        said(f"{word} tests")

    assert said("i'm playing forever").startswith("Playing Classic Forever")
    assert said("retail tests").startswith("Playing Retail")
    assert said("any edition").startswith("Offering tests for every edition.")

    # Existing commands are unaffected
    assert "test walkthrough" in said("help")
    assert interp.handle("look up frostbolt").kind == "browser"
    assert interp.handle("price check Linen Cloth").kind == "bnet"
    assert interp.handle("tell the agent hello").kind == "chat"


def test_live_test_cli_subcommands(tmp_path, monkeypatch, capsys):
    store = tmp_path / "cli-live-tests.json"
    monkeypatch.setattr(live_test_guide, "DEFAULT_STORE", store)

    assert cli.main(["live-test", "list", "--chip", "21", "--text"]) == 0
    out = capsys.readouterr().out
    assert "(#21)" in out
    assert "5 total" in out

    assert cli.main(["live-test", "list", "--moment", "logout", "--text"]) == 0
    out = capsys.readouterr().out
    assert "1 total" in out
    assert "4.3   F  logout   Logout guard (#22)" in out

    assert cli.main(["live-test", "next", "--text"]) == 0
    assert "Test 1 of 34" in capsys.readouterr().out

    assert cli.main(["live-test", "record", "pass", "--note", "status printed", "--text"]) == 0
    rec_out = capsys.readouterr().out
    assert "Passed test 1 (status printed)." in rec_out
    assert "Test 2 of 34" in rec_out

    assert cli.main(["live-test", "record", "skipped", "--id", "2.15", "--text"]) == 0
    assert "Skipped test 11." in capsys.readouterr().out
    assert cli.main(["live-test", "record", "pass", "--id", "99", "--text"]) == 0
    assert "There is no test 99." in capsys.readouterr().out

    assert cli.main(["live-test", "moment", "fight", "--text"]) == 0
    assert "Test 20 of 34" in capsys.readouterr().out
    assert cli.main(["live-test", "edition", "forever", "--text"]) == 0
    assert capsys.readouterr().out.startswith("Playing Classic Forever")

    assert cli.main(["live-test", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["pass"] == 1
    assert payload["counts"]["skipped"] == 1
    assert payload["edition"] == "forever"
