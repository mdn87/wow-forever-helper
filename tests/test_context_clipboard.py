"""The clipboard transport: a prefixed JSON packet copied out of the game."""
import sys

import pytest

from context_support import envelope, packet, payload
from wow_helper.context import clipboard
from wow_helper.context.envelope import ENVELOPE_MAX_BYTES, ContextError, serialize

PREFIX = clipboard.PREFIX


def reason(text):
    with pytest.raises(ContextError) as caught:
        clipboard.parse_clipboard(text)
    return caught.value.code


def test_the_prefix_is_versioned():
    assert PREFIX == "WFHC1:"


def test_a_prefixed_packet_parses_to_the_same_envelope_as_the_bare_payload():
    assert clipboard.parse_clipboard(PREFIX + payload().decode("utf-8")) == envelope()


def test_surrounding_whitespace_and_a_trailing_nul_are_ignored():
    text = "  \r\n" + PREFIX + payload().decode("utf-8") + "\r\n\x00\x00"
    assert clipboard.parse_clipboard(text) == envelope()


@pytest.mark.parametrize("text", [
    "", "   ", "just some copied words", '{"v":1}', "WFHC2:{}", "wfhc1:{}", "x" + PREFIX + "{}", "WFHC:{}", None, 5, b"WFHC1:{}",
])
def test_text_without_the_prefix_is_no_packet(text):
    assert reason(text) == "no-packet"


def test_a_huge_unrelated_clipboard_is_no_packet_not_too_large():
    assert reason("a" * 2_000_000) == "no-packet"


def test_a_prefixed_packet_over_the_limit_is_too_large():
    assert reason(PREFIX + "x" * (ENVELOPE_MAX_BYTES + 200)) == "too-large"
    assert reason(PREFIX + "x" * 3_000_000) == "too-large"


def test_the_prefix_alone_is_bad_json():
    assert reason(PREFIX) == "bad-json"
    assert reason(PREFIX + "   ") == "bad-json"


def test_a_partial_copy_is_bad_json():
    body = payload().decode("utf-8")
    for cut in (1, 10, len(body) // 2, len(body) - 1):
        assert reason(PREFIX + body[:cut]) == "bad-json"


def test_a_copy_with_extra_text_after_the_packet_is_bad_json():
    assert reason(PREFIX + payload().decode("utf-8") + " and more") == "bad-json"


def test_envelope_refusals_pass_through_with_their_codes():
    assert reason(PREFIX + serialize(packet(v=2))) == "unsupported-version"
    assert reason(PREFIX + serialize(packet(sid="not-a-session"))) == "bad-format"
    assert reason(PREFIX + serialize(packet(kind="chat"))) == "wrong-kind"


def test_a_prefix_inside_the_json_is_not_a_second_packet():
    changed = packet()
    changed["quest"]["title"] = PREFIX + "{}"
    assert clipboard.parse_clipboard(PREFIX + serialize(changed)).quest.title == PREFIX + "{}"


def test_read_packet_uses_the_reader_it_is_given():
    assert clipboard.read_packet(lambda: PREFIX + payload().decode("utf-8")) == envelope()


def test_read_packet_treats_an_empty_clipboard_as_no_packet():
    with pytest.raises(ContextError) as caught:
        clipboard.read_packet(lambda: None)
    assert caught.value.code == "no-packet"


def test_read_packet_lets_an_unavailable_clipboard_through():
    def busy():
        raise clipboard.ClipboardUnavailable("busy")
    with pytest.raises(clipboard.ClipboardUnavailable) as caught:
        clipboard.read_packet(busy)
    assert caught.value.reason == "busy"


def test_unavailable_reasons_are_short_words():
    assert clipboard.ClipboardUnavailable("busy").reason == "busy"
    assert "busy" in str(clipboard.ClipboardUnavailable("busy"))


def test_the_reader_is_bounded_by_the_largest_text_a_packet_can_be():
    assert clipboard.CLIPBOARD_MAX_CHARS >= len(PREFIX) + ENVELOPE_MAX_BYTES
    assert clipboard.CLIPBOARD_MAX_CHARS < 100_000


@pytest.mark.skipif(sys.platform != "win32", reason="the system clipboard reader is Windows only")
def test_the_windows_reader_returns_text_or_nothing_without_raising():
    # Reads whatever the clipboard holds and checks only its type, so it neither changes the
    # clipboard nor depends on what a developer or a CI runner has copied.
    try:
        text = clipboard.read_clipboard_text()
    except clipboard.ClipboardUnavailable as unavailable:
        pytest.skip(f"clipboard not available here: {unavailable.reason}")
    assert text is None or isinstance(text, str)
    if text is not None:
        assert len(text) <= clipboard.CLIPBOARD_MAX_CHARS + 1
        assert "\x00" not in text


@pytest.mark.skipif(sys.platform == "win32", reason="checks the refusal on other platforms")
def test_other_platforms_report_the_reader_as_unavailable():
    with pytest.raises(clipboard.ClipboardUnavailable) as caught:
        clipboard.read_clipboard_text()
    assert caught.value.reason == "unsupported-platform"
