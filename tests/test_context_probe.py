"""The context probe: read one packet from a chosen source, judge it, report without leaking game text."""
import json

import pytest

from context_render import blank, screen
from context_support import NOW, envelope, packet, payload
from wow_helper.__main__ import main
from wow_helper.context import clipboard, probe, strip
from wow_helper.context.envelope import serialize

SECRETS = ("Synthetic Delivery", "Testvale", "Example Crossing", "a1b2c3d4e5f60718", "WARRIOR", "Boars slain")


def clip(**changes):
    text = clipboard.PREFIX + serialize(packet(**changes))
    return lambda: text


def run(source="clipboard", **options):
    options.setdefault("now", NOW + 5)
    options.setdefault("state_file", None)
    return probe.run(source, **options)


def assert_paste_safe(result):
    blob = json.dumps(result) + probe.as_text(result)
    for secret in SECRETS:
        assert secret not in blob


# --- clipboard -----------------------------------------------------------------------------------

def test_a_fresh_clipboard_packet_reports_fields_and_numbers_but_no_game_text():
    code, result = run(reader=clip())
    assert code == 0
    assert (result["status"], result["source"], result["verdict"]) == ("ok", "clipboard", "fresh")
    assert (result["age_seconds"], result["new_session"], result["skipped"]) == (5, True, None)
    assert "quest.title" in result["packet"]["present"] and result["packet"]["objectives"] == 1
    assert_paste_safe(result)


def test_show_adds_the_cleaned_content():
    code, result = run(reader=clip(), show=True)
    assert code == 0 and result["content"]["quest"]["title"] == "Synthetic Delivery"
    assert "content" not in run(reader=clip())[1]


def test_nothing_on_the_clipboard_is_refused_as_no_packet():
    for reader in (lambda: None, lambda: "grocery list", lambda: ""):
        code, result = run(reader=reader)
        assert (code, result["status"], result["reason"]) == (2, "refused", "no-packet")
        assert result["detail"]


def test_a_corrupt_packet_is_refused_with_the_envelope_reason_and_no_text():
    code, result = run(reader=lambda: clipboard.PREFIX + serialize(packet(sid="not-a-session")))
    assert (code, result["reason"]) == (2, "bad-format")
    assert_paste_safe(result)
    code, result = run(reader=lambda: clipboard.PREFIX + serialize(packet())[:-9])
    assert (code, result["reason"]) == (2, "bad-json")


def test_an_unreadable_clipboard_is_an_error_not_a_refusal():
    def busy():
        raise clipboard.ClipboardUnavailable("busy")
    code, result = run(reader=busy)
    assert (code, result["status"], result["reason"]) == (3, "error", "clipboard-busy")


def test_text_output_is_readable_and_paste_safe():
    code, result = run(reader=clip())
    text = probe.as_text(result)
    assert "fresh" in text and "clipboard" in text
    assert_paste_safe(result)
    refused = probe.as_text(run(reader=lambda: "x")[1])
    assert "no-packet" in refused


# --- freshness across runs -------------------------------------------------------------------------

def test_repeating_the_same_packet_is_a_duplicate_and_a_new_one_is_fresh(tmp_path):
    state = tmp_path / "state.json"
    first = run(reader=clip(), state_file=state)[1]
    again = run(reader=clip(), state_file=state)[1]
    later = run(reader=clip(seq=8), state_file=state)[1]
    older = run(reader=clip(seq=3), state_file=state)[1]
    assert [r["verdict"] for r in (first, again, later, older)] == ["fresh", "duplicate", "fresh", "older"]
    assert later["skipped"] == 0 and again["state"] == "kept"
    assert first["state"] == "saved"


def test_a_new_session_is_fresh_even_with_a_lower_sequence(tmp_path):
    state = tmp_path / "state.json"
    run(reader=clip(seq=40), state_file=state)
    result = run(reader=clip(sid="fedcba9876543210", seq=1), state_file=state)[1]
    assert (result["verdict"], result["new_session"]) == ("fresh", True)


def test_stale_and_future_packets_are_judged_not_refused(tmp_path):
    state = tmp_path / "state.json"
    code, stale = run(reader=clip(), state_file=state, now=NOW + 500, max_age=120)
    assert (code, stale["verdict"], stale["age_seconds"]) == (0, "stale", 500)
    code, future = run(reader=clip(), state_file=state, now=NOW - 1000)
    assert (code, future["verdict"]) == (0, "future")
    assert run(reader=clip(), state_file=state, now=NOW)[1]["verdict"] == "fresh"


def test_no_state_file_means_every_run_is_independent():
    assert run(reader=clip())[1]["verdict"] == run(reader=clip())[1]["verdict"] == "fresh"
    assert run(reader=clip())[1]["state"] == "off"


def test_a_damaged_state_file_is_ignored_and_replaced(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{ not json", encoding="utf-8")
    assert run(reader=clip(), state_file=state)[1]["verdict"] == "fresh"
    assert json.loads(state.read_text(encoding="utf-8"))["v"] == 1
    assert run(reader=clip(), state_file=state)[1]["verdict"] == "duplicate"


def test_a_state_file_that_cannot_be_written_is_reported_but_does_not_fail_the_probe(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder is needed", encoding="utf-8")
    code, result = run(reader=clip(), state_file=blocker / "state.json")
    assert (code, result["verdict"], result["state"]) == (0, "fresh", "not-saved")


# --- window and image ---------------------------------------------------------------------------

def test_a_window_grab_with_a_strip_is_decoded_and_the_measurements_are_reported():
    frame = screen(payload(), cell=4, background="clutter", size=(1280, 720), at=(0, 0))
    code, result = run("window", flavor="_retail_", grab=lambda flavor: frame)
    assert (code, result["status"], result["verdict"]) == (0, "ok", "fresh")
    assert result["strip"]["columns"] == 160 and result["strip"]["pitch_x"] == 4.0
    assert result["strip"]["weakest_margin"] == 1.0
    assert set(result["timings_ms"]) >= {"read", "decode", "parse"}
    assert_paste_safe(result)


def test_the_window_grab_is_asked_for_the_chosen_game_folder():
    asked = []
    frame = screen(payload(), at=(0, 0), size=(1280, 720))
    run("window", flavor="_classic_beta_", grab=lambda flavor: asked.append(flavor) or frame)
    assert asked == ["_classic_beta_"]


def test_a_window_without_a_strip_is_refused_with_the_strip_reason_and_measurements():
    code, result = run("window", flavor="_retail_", grab=lambda flavor: blank("clutter", (1280, 720)))
    assert (code, result["status"], result["reason"]) == (2, "refused", "no-strip")
    assert result["strip"]["candidates"] == 0


def test_a_damaged_strip_is_refused_with_how_far_it_got():
    frame = screen(payload(), flip=[(3, 50)], size=(1280, 720), at=(0, 0))
    code, result = run("window", flavor="_retail_", grab=lambda flavor: frame)
    assert (code, result["reason"]) == (2, "crc-mismatch")
    assert result["strip"]["pitch_x"] == 4.0 and "weakest_margin" in result["strip"]


def test_a_good_strip_with_a_bad_packet_is_refused_by_the_envelope_rules():
    frame = screen(b'{"v":1,"kind":"context"}', size=(1280, 720), at=(0, 0))
    code, result = run("window", flavor="_retail_", grab=lambda flavor: frame)
    assert (code, result["reason"]) == (2, "missing-field")
    assert result["strip"]["columns"] == 160


@pytest.mark.parametrize("corner,at,found", [
    ("topleft", (0, 0), True), ("topleft", (1200, 700), False),
    ("topright", (1920 - 700, 0), True), ("bottomleft", (0, 1080 - 200), True),
    ("bottomright", (1920 - 700, 1080 - 200), True), ("full", (700, 400), True), ("topleft", (500, 400), True),
])
def test_the_corner_option_limits_where_the_strip_is_looked_for(corner, at, found):
    frame = screen(payload(), at=at, size=(1920, 1080), background="black")
    code, result = run("window", flavor="_retail_", grab=lambda flavor: frame, corner=corner)
    assert (code == 0) is found


def test_window_needs_a_game_folder():
    code, result = run("window", grab=lambda flavor: None)
    assert (code, result["status"], result["reason"]) == (2, "refused", "flavor-required")


def test_a_capture_failure_is_an_error_with_a_safe_message():
    def failing(flavor):
        raise probe.CaptureFailed("Capture failed. Open one visible WoW window for the selected edition, or open an image.")
    code, result = run("window", flavor="_retail_", grab=failing)
    assert (code, result["status"], result["reason"]) == (3, "error", "capture-failed")
    assert "Capture failed" in result["detail"]


def test_an_image_file_is_read_and_its_path_is_never_printed(tmp_path):
    image = pytest.importorskip("PIL.Image")
    frame = screen(payload(), at=(0, 0), size=(1280, 720))
    target = tmp_path / "shot.png"
    image.frombytes("L", (frame.width, frame.height), frame.pixels).save(target)
    code, result = run("image", image_path=str(target))
    assert (code, result["verdict"]) == (0, "fresh")
    assert str(tmp_path) not in json.dumps(result) and "shot.png" not in json.dumps(result)


def test_an_unreadable_image_is_an_error(tmp_path):
    pytest.importorskip("PIL.Image")
    (tmp_path / "text.png").write_text("not an image", encoding="utf-8")
    for path in (str(tmp_path / "missing.png"), str(tmp_path / "text.png")):
        code, result = run("image", image_path=path)
        assert (code, result["status"], result["reason"]) == (3, "error", "image-unreadable")
        assert str(tmp_path) not in json.dumps(result)
    assert run("image")[1]["reason"] == "image-required"


def test_an_unknown_source_is_refused():
    code, result = run("telepathy")
    assert (code, result["reason"]) == (2, "unknown-source")


# --- the command line ---------------------------------------------------------------------------

def test_the_command_prints_json_and_returns_the_exit_code(tmp_path, capsys, monkeypatch):
    image = pytest.importorskip("PIL.Image")
    frame = screen(payload(), at=(0, 0), size=(1280, 720))
    target = tmp_path / "shot.png"
    image.frombytes("L", (frame.width, frame.height), frame.pixels).save(target)
    monkeypatch.setattr(probe, "_now", lambda: NOW + 2)
    assert main(["context-probe", "--source", "image", "--image", str(target), "--no-state"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "fresh" and printed["age_seconds"] == 2
    assert main(["context-probe", "--source", "image", "--image", str(target), "--no-state", "--text"]) == 0
    assert "fresh" in capsys.readouterr().out


def test_the_command_exits_2_for_a_refusal_and_3_for_an_error(tmp_path, capsys):
    pytest.importorskip("PIL.Image")
    assert main(["context-probe", "--source", "image", "--image", str(tmp_path / "missing.png"), "--no-state"]) == 3
    assert json.loads(capsys.readouterr().out)["reason"] == "image-unreadable"
    assert main(["context-probe", "--source", "window", "--no-state"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "flavor-required"


def test_the_command_refuses_an_unknown_game_folder_before_capturing(capsys):
    assert main(["context-probe", "--source", "window", "--flavor", "..\\elsewhere", "--no-state"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "flavor-unknown"


def test_the_default_state_file_is_inside_the_ignored_runtime_folder():
    assert probe.DEFAULT_STATE.parts[-2:] == (".runtime", "context-probe.json")
    ignored = (probe.DEFAULT_STATE.parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert ".runtime/" in ignored


def test_envelope_helper_matches_what_the_probe_parses():
    assert envelope().seq == 7
