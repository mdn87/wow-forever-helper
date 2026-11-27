"""Synthetic tests for the spoken in-game live-test walkthrough."""

from __future__ import annotations

import json

from wow_helper import __main__ as cli
from wow_helper import live_test_guide
from wow_helper.live_test_guide import ITEMS, LiveTestGuide
from wow_helper.voice_commands import Interpreter


def test_all_spoken_instructions_are_concise_and_bridge_safe(tmp_path):
    guide = LiveTestGuide(store=tmp_path / "results.json")
    assert len(ITEMS) == 12
    assert {item.chip for item in ITEMS} == {"#30", "#21", "#22", "#23"}
    for item in ITEMS:
        spoken = guide.format_spoken_item(item)
        assert f"Test {item.number} of 12" in spoken
        assert len(spoken) <= 700  # comfortable for Lugos Voice TTS and well under 1200 bridge limit


def test_guide_progression_pass_fail_skip_goto_and_restart_persistence(tmp_path):
    store = tmp_path / "live-test-results.json"
    guide = LiveTestGuide(store=store)

    p1 = guide.next_prompt()
    assert "Test 1 of 12" in p1
    assert "Linen Cloth" in p1

    # Pass test 1 with note -> automatically speaks test 2
    _, p2 = guide.record("pass", note="house 111")
    assert "Passed test 1 (house 111)." in p2
    assert "Test 2 of 12" in p2

    # Skip test 2 -> speaks test 3
    _, p3 = guide.record("skipped")
    assert "Skipped test 2." in p3
    assert "Test 3 of 12" in p3

    # Fail test 3 -> speaks test 4
    _, p4 = guide.record("fail", note="mic missed word")
    assert "Failed test 3 (mic missed word)." in p4
    assert "Test 4 of 12" in p4

    # Fresh instance preserves results and current pointer across restart
    reloaded = LiveTestGuide(store=store)
    assert "Test 4 of 12" in reloaded.repeat_prompt()
    summary = reloaded.summary()
    assert summary["counts"] == {"pass": 1, "fail": 1, "skipped": 1, "pending": 9}
    assert "1 passed, 1 failed, 1 skipped, 9 pending" in reloaded.status_spoken()

    # Jump directly to test 10
    p10 = reloaded.goto(10)
    assert "Test 10 of 12" in p10
    assert "wfhprobe strip" in p10

    # Reset clears progress back to test 1
    reset_msg = reloaded.reset()
    assert "Cleared saved live test results." in reset_msg
    assert "Test 1 of 12" in reset_msg
    assert reloaded.summary()["counts"]["pending"] == 12


def test_voice_commands_drive_live_test_walkthrough(tmp_path, monkeypatch):
    store = tmp_path / "voice-live-tests.json"
    monkeypatch.setattr(live_test_guide, "DEFAULT_STORE", store)
    interp = Interpreter(manager=None, window=None)

    r1 = interp.handle("start live test")
    assert r1.kind == "done"
    assert "Test 1 of 12" in r1.detail

    r2 = interp.handle("repeat test")
    assert r2.kind == "done"
    assert "Test 1 of 12" in r2.detail

    r3 = interp.handle("pass test house 110")
    assert r3.kind == "done"
    assert "Passed test 1 (house 110)." in r3.detail
    assert "Test 2 of 12" in r3.detail

    r4 = interp.handle("skip test")
    assert r4.kind == "done"
    assert "Skipped test 2." in r4.detail
    assert "Test 3 of 12" in r4.detail

    r5 = interp.handle("go to test 9")
    assert r5.kind == "done"
    assert "Test 9 of 12" in r5.detail

    r6 = interp.handle("test status")
    assert r6.kind == "done"
    assert "1 passed, 0 failed, 1 skipped, 10 pending" in r6.detail

    # Ensure existing commands are unaffected
    assert interp.handle("help").kind == "done"
    assert interp.handle("look up frostbolt").kind == "browser"
    assert interp.handle("price check Linen Cloth").kind == "bnet"
    assert interp.handle("tell the agent hello").kind == "chat"


def test_live_test_cli_subcommands(tmp_path, monkeypatch, capsys):
    store = tmp_path / "cli-live-tests.json"
    monkeypatch.setattr(live_test_guide, "DEFAULT_STORE", store)

    assert cli.main(["live-test", "list", "--chip", "30", "--text"]) == 0
    out = capsys.readouterr().out
    assert "(#30)" in out
    assert "3 total" in out

    assert cli.main(["live-test", "next", "--text"]) == 0
    assert "Test 1 of 12" in capsys.readouterr().out

    assert cli.main(["live-test", "record", "pass", "--note", "house 111", "--text"]) == 0
    rec_out = capsys.readouterr().out
    assert "Passed test 1 (house 111)." in rec_out
    assert "Test 2 of 12" in rec_out

    assert cli.main(["live-test", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["pass"] == 1
