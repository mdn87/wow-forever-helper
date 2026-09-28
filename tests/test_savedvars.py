"""Restricted SavedVariables parser (docs/PLAN.md section 5.1), synthetic input only."""

import os
import random
from pathlib import Path

import pytest

from wow_helper.savedvars import MAX_BYTES, MAX_DEPTH, SavedVariablesError, as_list, parse, read_stable

FIXTURE = Path(__file__).parent / "fixtures" / "savedvariables_quests.lua"


def test_the_game_format_parses_into_tables():
    db = parse(FIXTURE.read_text(encoding="utf-8"))["WoWCompanionDB"]
    assert db["player"]["level"] == 12
    quests = as_list(db["quests"])
    assert [q["id"] for q in quests] == [900001, 900002, 900003, 900004, 900005, 900006]
    assert quests[2]["title"] == 'Clear the "Example" Mine'
    assert quests[3]["objectives"][1]["text"] == "Talk to the |cffffd200Example Clerk|r"
    assert db["collapsedHeaders"] == {}


def test_escapes_numbers_and_literals():
    parsed = parse('A = { "q\\"b\\\\s\\nn\\124p\\195\\169", -2, 1.5e3, true, false, nil, ["k"] = { [7] = 0 } }')
    assert as_list(parsed["A"])[:6] == ['q"b\\s\nn|pé', -2, 1500.0, True, False, None]
    assert parsed["A"]["k"] == {7: 0}
    assert parse("B = nil\nC = {};") == {"B": None, "C": {}}
    assert parse("\ufeffD = {\n} -- [1] trailing comment\n") == {"D": {}}


@pytest.mark.parametrize("text", [
    'X = os.execute("x")',
    "X = { a = 1 }",
    "X = { [1] = 1 + 2 }",
    "X = { f() }",
    'X = "top-level string"',
    "X = 3",
    "X = { 1, 2",
    "X = { 1 } }",
    "--[[ block comment ]] X = {}",
    "X = { [true] = 1 }",
    "X = { [1.5] = 1 }",
    'X = { "\\999" }',
    'X = { "\\x41" }',
    'X = { "unterminated }',
    "X = { " + "9" * 41 + " }",
    "X = { 12abc }",
    "true = {}",
    "X = { ... }",
    "X = { [[long string]] }",
])
def test_anything_outside_the_subset_is_rejected(text):
    with pytest.raises(SavedVariablesError):
        parse(text)


def test_depth_and_size_are_capped():
    assert parse("X = " + "{" * MAX_DEPTH + "}" * MAX_DEPTH)
    with pytest.raises(SavedVariablesError, match="nested"):
        parse("X = " + "{" * (MAX_DEPTH + 1) + "}" * (MAX_DEPTH + 1))
    with pytest.raises(SavedVariablesError, match="4 MB"):
        parse("X = { " + " " * MAX_BYTES + " }")


def test_mutated_input_only_ever_parses_or_raises_the_parser_error():
    source = FIXTURE.read_text(encoding="utf-8")
    alphabet = '{}[]=,;"\\-.0123456789eE\n abcnilrtufs\x00'
    rng = random.Random(20260928)
    for _ in range(1500):
        chars = list(source)
        for _ in range(rng.randint(1, 8)):
            at = rng.randrange(len(chars))
            roll = rng.random()
            if roll < 0.35:
                del chars[at]
            elif roll < 0.7:
                chars.insert(at, rng.choice(alphabet))
            else:
                chars[at] = rng.choice(alphabet)
        try:
            assert isinstance(parse("".join(chars)), dict)
        except SavedVariablesError:
            pass


def test_a_file_the_game_is_still_writing_is_not_trusted(tmp_path):
    path = tmp_path / "WoWCompanion.lua"
    path.write_text("X = {}", encoding="utf-8")
    parsed, mtime = read_stable(path, wait=0, sleep=lambda _: None)
    assert parsed == {"X": {}} and mtime == path.stat().st_mtime

    def rewrite(_):
        path.write_text("X = { 1 }", encoding="utf-8")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 5_000_000_000))
    with pytest.raises(SavedVariablesError, match="still writing"):
        read_stable(path, wait=0, sleep=rewrite)


def test_errors_never_name_the_path(tmp_path):
    missing = tmp_path / "Account" / "000000000" / "WoWCompanion.lua"
    with pytest.raises(SavedVariablesError) as caught:
        read_stable(missing, wait=0, sleep=lambda _: None)
    assert str(tmp_path) not in str(caught.value) and "000000000" not in str(caught.value)
