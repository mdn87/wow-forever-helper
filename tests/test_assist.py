"""Synthetic requests only; these tests never send native input."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from wow_helper.assist import ACTION, Assistant, AssistError, check_age, parse_key, resolve


class Desktop:
    def __init__(self):
        self.presses = []

    def press(self, chord):
        self.presses.append(chord.name)


@pytest.fixture
def assistant(tmp_path):
    instance = Assistant(tmp_path / "assist.sqlite", Desktop(), clock=lambda: 100)
    instance.bind(ACTION, "SHIFT+F4")
    return instance


def run(assistant, request_id="synthetic-command", issued_at=99):
    return assistant.request("cast teleport to orgrimmar on my mage", execute=True,
                             request_id=request_id, issued_at=issued_at)


@pytest.mark.parametrize("phrase", ["cast teleport to Orgrimmar on my mage",
    "Please cast teleport: Orgrimmar.", "teleport Orgrimmar", "  CAST  TELEPORT TO ORGRIMMAR! "])
def test_explicit_spell_requests(phrase):
    assert resolve(phrase) == ACTION


@pytest.mark.parametrize("phrase", ["don't cast teleport to orgrimmar", "how do I teleport to orgrimmar?",
    "cast teleport to orgrimmar then cast fireball", "cast portal to orgrimmar", "go home",
    "repeat teleport to orgrimmar", "cast teleport to stormwind", "" , "x" * 201])
def test_questions_negation_sequences_and_other_spells_are_refused(phrase):
    with pytest.raises(AssistError):
        resolve(phrase)


@pytest.mark.parametrize("key, canonical, codes", [("shift+7", "SHIFT+7", (16, 55)),
    ("shift+f4", "SHIFT+F4", (16, 115)), ("shift+ctrl+1", "CTRL+SHIFT+1", (17, 16, 49))])
def test_user_keybinds(key, canonical, codes):
    assert (parse_key(key).name, parse_key(key).codes) == (canonical, codes)


@pytest.mark.parametrize("key", ["ALT+F4", "WIN+R", "CTRL+CTRL+7", "ENTER", "F13", "7,8", ""])
def test_bad_chords(key):
    with pytest.raises(AssistError):
        parse_key(key)


def test_preview_has_no_input_or_request_reservation(assistant):
    assert assistant.request("teleport to orgrimmar")["status"] == "preview"
    assert not assistant.desktop.presses
    with sqlite3.connect(assistant.path) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


def test_default_disabled_and_stop_persists(assistant):
    with pytest.raises(AssistError, match="stopped"):
        run(assistant)
    assistant.enable(True)
    assistant.enable(False)
    restarted = Assistant(assistant.path, assistant.desktop, clock=lambda: 100)
    with pytest.raises(AssistError, match="stopped"):
        run(restarted)
    assert not assistant.desktop.presses


def test_one_command_sends_one_chord_and_does_not_claim_spell_success(assistant):
    assistant.enable(True)
    result = run(assistant)
    assert result["status"] == "sent"
    assert "not verified" in result["message"]
    assert assistant.desktop.presses == ["SHIFT+F4"]


def test_duplicate_is_rejected_after_restart(assistant):
    assistant.enable(True)
    run(assistant)
    restarted = Assistant(assistant.path, assistant.desktop, clock=lambda: 100)
    with pytest.raises(AssistError, match="consumed"):
        run(restarted)
    assert assistant.desktop.presses == ["SHIFT+F4"]


def test_concurrent_duplicate_sends_only_once(assistant):
    assistant.enable(True)
    def submit(_):
        try:
            return run(assistant)["status"]
        except AssistError:
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == ["refused", "sent"]
    assert assistant.desktop.presses == ["SHIFT+F4"]


def test_unknown_delivery_is_consumed_not_retried(assistant):
    assistant.enable(True)
    def fail(chord):
        assistant.desktop.presses.append(chord.name)
        raise AssistError("synthetic delivery failure")
    assistant.desktop.press = fail
    with pytest.raises(AssistError, match="delivery failure"):
        run(assistant)
    with pytest.raises(AssistError, match="consumed"):
        run(assistant)
    assert len(assistant.desktop.presses) == 1


@pytest.mark.parametrize("issued_at", [84, 101, float("nan"), float("inf"), float("-inf")])
def test_stale_future_and_nonfinite_requests(assistant, issued_at):
    assistant.enable(True)
    with pytest.raises(AssistError, match="timestamp"):
        run(assistant, issued_at=issued_at)
    assert not assistant.desktop.presses


def test_expiry_is_checked_again_at_dispatch(assistant):
    assistant.enable(True)
    times = iter([100, 120])
    assistant.clock = lambda: next(times)
    with pytest.raises(AssistError, match="expired"):
        run(assistant)
    assert not assistant.desktop.presses


def test_missing_mapping_and_request_metadata(tmp_path):
    assistant = Assistant(tmp_path / "assist.sqlite", Desktop(), clock=lambda: 100)
    with pytest.raises(AssistError, match="Bind"):
        run(assistant)
    assistant.bind(ACTION, "SHIFT+7")
    assistant.enable(True)
    with pytest.raises(AssistError, match="request ID"):
        run(assistant, request_id=None)
    with pytest.raises(AssistError, match="timestamp"):
        run(assistant, issued_at=None)
    assert not assistant.desktop.presses
