"""Rules for text that came from the game, ported from NeverQuestAlone's sanitizeGameString.

The vectors are synthetic. Their expected values were produced by running the upstream rules
(MIT, see THIRD_PARTY_NOTICES.md) on invented inputs, so a mismatch here means the port drifted.
"""
import json
import re
import unicodedata
from pathlib import Path

import pytest

from wow_helper.context import sanitize

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests" / "fixtures" / "context_sanitize_vectors.json").read_text(encoding="ascii"))
CASES = VECTORS["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_matches_upstream_vectors(case):
    assert sanitize.sanitize_game_string(case["input"], case["max"]) == case["expected"]


def test_vectors_cover_the_rules_that_matter():
    names = " ".join(c["name"] for c in CASES)
    for needle in ("colour", "link", "texture", "atlas", "newline", "surrogate", "zero-width", "bidi", "cap"):
        assert needle in names


def test_output_is_one_clean_line_for_every_vector():
    for case in CASES:
        out = sanitize.sanitize_game_string(case["input"], case["max"])
        assert "|" not in out
        assert not re.search(r"[\x00-\x1f\x7f-\x9f  ]", out)
        assert out == out.strip(" ")
        assert "  " not in out
        assert len(out) <= case["max"]


def test_sanitising_twice_changes_nothing():
    for case in CASES:
        once = sanitize.sanitize_game_string(case["input"], case["max"])
        assert sanitize.sanitize_game_string(once, case["max"]) == once


def test_the_cap_is_in_code_points_not_bytes():
    out = sanitize.sanitize_game_string("\U0001f31e" * 100, 10)
    assert out == "\U0001f31e" * 10
    assert len(out.encode("utf-8")) == 40


def test_the_default_and_objective_caps():
    assert sanitize.GAME_STRING_MAX == 60
    assert sanitize.OBJECTIVE_TEXT_MAX == 80
    assert len(sanitize.sanitize_game_string("a" * 500)) == 60
    assert len(sanitize.sanitize_game_string("a" * 500, sanitize.OBJECTIVE_TEXT_MAX)) == 80


@pytest.mark.parametrize("value", [None, 5, 5.5, True, b"bytes", ["list"], {"a": 1}])
def test_anything_that_is_not_a_string_becomes_empty(value):
    assert sanitize.sanitize_game_string(value) == ""


def test_a_cap_of_zero_gives_nothing_and_a_negative_cap_is_refused():
    assert sanitize.sanitize_game_string("anything", 0) == ""
    with pytest.raises(ValueError):
        sanitize.sanitize_game_string("anything", -1)


def test_strip_escapes_leaves_text_without_a_pipe_alone():
    text = "No escapes here, only [brackets] and 100%."
    assert sanitize.strip_escapes(text) == text


def test_strip_escapes_keeps_a_stray_pipe_for_the_caller():
    assert sanitize.strip_escapes("a|b") == "a|b"
    assert sanitize.sanitize_game_string("a|b") == "ab"


def test_the_pinned_table_covers_every_format_character_this_python_knows():
    format_chars = [chr(cp) for cp in range(0x110000) if unicodedata.category(chr(cp)) == "Cf"]
    assert format_chars, "the Unicode database reports no format characters"
    missed = [f"U+{ord(ch):04X}" for ch in format_chars if sanitize.sanitize_game_string("a" + ch + "b") != "ab"]
    assert missed == []


def test_the_pinned_table_is_sorted_disjoint_and_names_its_unicode_version():
    ranges = sanitize.INVISIBLE_RANGES
    assert ranges == tuple(sorted(ranges))
    for (lo, hi), (next_lo, _) in zip(ranges, ranges[1:]):
        assert lo <= hi < next_lo
    assert sanitize.INVISIBLE_UNICODE_VERSION == "17.0"


def test_third_party_notice_names_the_source_of_the_rules():
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "NeverQuestAlone" in notice
    assert "chelinho139" in notice
    assert "Permission is hereby granted, free of charge" in notice
