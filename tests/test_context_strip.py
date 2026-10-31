"""The pixel-strip transport: format, reference encoder, and a reader tested on synthetic frames.

Every frame here is synthetic. The reader must return the exact payload or a named error, and
never different data, whatever happens to the picture.
"""
import random

import pytest

from context_render import blank, payload_of, screen, stack
from wow_helper.context import strip
from wow_helper.context.envelope import ENVELOPE_MAX_BYTES
from wow_helper.context.strip import GrayFrame, StripError, decode_strip

DATA = payload_of(200)


def slow_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def fail(frame, **options):
    with pytest.raises(StripError) as caught:
        decode_strip(frame, **options)
    return caught.value


def ok(frame, expected=DATA, **options):
    result = decode_strip(frame, **options)
    assert result.payload == expected
    return result.diagnostics


# --- the format and the reference encoder -------------------------------------------------------

def test_crc16_is_ccitt_false():
    assert strip.crc16(b"123456789") == 0x29B1
    for seed in range(5):
        sample = payload_of(37, seed)
        assert strip.crc16(sample) == slow_crc(sample)


def test_frame_bytes_layout():
    framed = strip.frame_bytes(b"ABC")
    assert framed[:2] == b"\xa7\x3c"
    assert (framed[2], framed[3]) == (1, 0)
    assert framed[4:6] == b"\x00\x03" and framed[6:9] == b"ABC"
    assert framed[9:] == slow_crc(framed[2:9]).to_bytes(2, "big")
    assert len(framed) == 11


def test_a_payload_over_the_length_field_is_refused():
    assert len(strip.frame_bytes(bytes(65535))) == 65535 + 8
    with pytest.raises(ValueError):
        strip.frame_bytes(bytes(65536))


@pytest.mark.parametrize("length,rows", [(0, 1), (12, 1), (13, 2), (32, 2), (33, 3), (150, 8)])
def test_rows_needed_counts_the_bits_a_payload_fills(length, rows):
    assert strip.rows_needed(length) == rows


def test_the_ruler_alternates_and_ends_on_white():
    ruler = strip.encode_cells(b"")[0]
    assert len(ruler) == strip.COLUMNS + 1
    assert ruler == [1, 0] * (strip.COLUMNS // 2) + [1]


def test_data_rows_are_even_in_number_and_the_terminator_column_alternates():
    for length, data_rows in ((0, 2), (12, 2), (13, 2), (33, 4), (150, 8)):
        grid = strip.encode_cells(bytes(length))
        assert len(grid) - 1 == data_rows
        assert [row[-1] for row in grid] == [1 if index % 2 == 0 else 0 for index in range(len(grid))]
        assert grid[-1][-1] == 1


def test_data_bits_run_row_by_row_most_significant_bit_first():
    grid = strip.encode_cells(DATA)
    assert grid[1][:8] == [1, 0, 1, 0, 0, 1, 1, 1]          # 0xA7
    assert grid[1][8:16] == [0, 0, 1, 1, 1, 1, 0, 0]        # 0x3C
    bits = [bit for row in grid[1:] for bit in row[:-1]]
    rebuilt = bytes(sum(bit << (7 - n) for n, bit in enumerate(bits[i:i + 8])) for i in range(0, len(strip.frame_bytes(DATA)) * 8, 8))
    assert rebuilt == strip.frame_bytes(DATA)


def test_unused_cells_are_black():
    grid = strip.encode_cells(b"")
    used = len(strip.frame_bytes(b"")) * 8
    bits = [bit for row in grid[1:] for bit in row[:-1]]
    assert not any(bits[used:])


@pytest.mark.parametrize("columns", [31, 33, 30, 514, 0, -2])
def test_unsupported_column_counts_are_refused(columns):
    with pytest.raises(ValueError):
        strip.encode_cells(b"x", columns=columns)


# --- reading ideal and placed frames -------------------------------------------------------------

@pytest.mark.parametrize("cell", [2, 3, 4, 6, 8])
@pytest.mark.parametrize("length", [0, 1, 12, 13, 150, 480])
def test_a_clean_strip_round_trips_at_every_cell_size(cell, length):
    payload = payload_of(length, seed=length)
    frame = screen(payload, cell=cell, background="black", size=(165 * cell + 120, 120 + cell * (strip.rows_needed(length) + 12)))
    found = ok(frame, payload)
    assert found["columns"] == 160 and found["pitch_x"] == cell and found["pitch_y"] == cell
    assert found["contrast"] == 255 and found["weakest_margin"] == 1.0


@pytest.mark.parametrize("columns", [32, 40, 80, 160, 256, 512])
def test_other_column_counts_round_trip(columns):
    frame = screen(DATA, columns=columns, cell=3, background="black", size=(1700, 400))
    assert ok(frame)["columns"] == columns


@pytest.mark.parametrize("background", ["clutter", "white", "stripes", "gradient"])
def test_the_strip_is_found_on_a_busy_background(background):
    for seed in (1, 2, 3):
        ok(screen(DATA, background=background, seed=seed))


@pytest.mark.parametrize("at", [(0, 0), (1, 1), (300, 200), (960 - 165 * 4 - 40, 540 - 40 * 4)])
def test_placement_anywhere_with_the_margin_on_screen(at):
    ok(screen(DATA, at=at, size=(960, 540)))


def test_the_search_window_limits_where_the_reader_looks():
    frame = screen(DATA, at=(500, 300), size=(1400, 700))
    ok(frame, search=(400, 250, 1400, 700))
    assert fail(frame, search=(0, 0, 400, 250)).code == "no-strip"
    with pytest.raises(ValueError):
        decode_strip(frame, search=(10, 10, 5, 5))


def test_a_decoy_ruler_above_the_real_strip_does_not_stop_the_search():
    decoy = screen(DATA, version=2, size=(960, 300))
    real = screen(DATA, size=(960, 300), seed=5)
    found = ok(stack(decoy, real))
    assert found["candidates"] == 2


# --- levels, noise and softness -----------------------------------------------------------------

@pytest.mark.parametrize("white,black", [(170, 50), (255, 100), (140, 30), (200, 0), (255, 60)])
def test_reduced_contrast_and_raised_blacks_still_read(white, black):
    ok(screen(DATA, white=white, black=black))


def test_noise_is_tolerated_and_the_margin_shows_it():
    quiet = ok(screen(DATA, noise=0))["weakest_margin"]
    noisy = ok(screen(DATA, noise=40))["weakest_margin"]
    assert quiet == 1.0 and 0.3 < noisy < 1.0


@pytest.mark.parametrize("blur,cell", [(1, 4), (1, 6), (2, 6)])
def test_soft_edges_still_read(blur, cell):
    ok(screen(DATA, blur=blur, cell=cell, background="black", size=(1100, 700)))


def test_gamma_changes_do_not_matter_to_a_two_level_picture():
    ok(screen(DATA, gamma=0.5, blur=1, cell=6, size=(1100, 700)))
    ok(screen(DATA, gamma=2.2, blur=1, cell=6, size=(1100, 700)))


def test_white_and_black_too_close_together_are_reported_as_low_contrast():
    error = fail(screen(DATA, white=110, black=60, background="black"))
    assert error.code == "low-contrast"
    assert error.diagnostics["contrast"] == 50.0


# --- resized frames -----------------------------------------------------------------------------

PIL = pytest.importorskip("PIL.Image")
METHODS = {"nearest": PIL.NEAREST, "bilinear": PIL.BILINEAR, "bicubic": PIL.BICUBIC, "lanczos": PIL.LANCZOS}


def resized(frame, sx, sy, method):
    image = PIL.frombytes("L", (frame.width, frame.height), frame.pixels)
    image = image.resize((max(1, round(frame.width * sx)), max(1, round(frame.height * sy))), METHODS[method])
    return strip.frame_from_image(image)


@pytest.fixture(scope="module")
def bases():
    return {(cell, background): screen(DATA, cell=cell, background=background, size=(1400, 700))
            for cell in (4, 6) for background in ("black", "clutter")}


SCALES = [(0.6, 0.6), (0.75, 0.75), (0.9, 0.9), (1.25, 1.25), (1.5, 1.5), (2.0, 2.0), (3.0, 3.0),
          (1.5, 1.0), (1.0, 1.5), (0.75, 1.0)]


@pytest.mark.parametrize("method", list(METHODS))
@pytest.mark.parametrize("background", ["black", "clutter"])
def test_resized_frames_read_when_cells_stay_wide_enough(bases, method, background):
    for sx, sy in SCALES:
        ok(resized(bases[(6, background)], sx, sy, method))
        if min(sx, sy) >= 0.75:
            ok(resized(bases[(4, background)], sx, sy, method))


@pytest.mark.parametrize("method", list(METHODS))
def test_halving_a_four_pixel_strip_gives_the_payload_or_a_named_error_never_other_data(bases, method):
    for background in ("black", "clutter"):
        try:
            ok(resized(bases[(4, background)], 0.5, 0.5, method))
        except StripError as error:
            assert error.code in strip.REASONS


def test_uneven_scaling_that_makes_cells_five_and_six_pixels_wide_in_turn_reads_with_nearest_sampling(bases):
    for scale in (1.1, 1.25, 1.375, 1.7):
        ok(resized(bases[(4, "black")], scale, scale, "nearest"))


# --- damage -------------------------------------------------------------------------------------

def test_one_wrong_data_cell_fails_the_checksum():
    error = fail(screen(DATA, flip=[(3, 50)]))
    assert error.code == "crc-mismatch"
    assert "weakest_margin" in error.diagnostics and "length" in error.diagnostics


def test_a_wrong_magic_cell_is_named():
    assert fail(screen(DATA, flip=[(1, 0)])).code == "bad-magic"


def test_a_newer_version_and_unknown_flags_are_named():
    assert fail(screen(DATA, version=2)).code == "unsupported-version"
    assert fail(screen(DATA, flags=1)).code == "unsupported-flags"


def test_a_payload_over_the_limit_is_refused_before_it_is_read():
    frame = screen(DATA)
    error = fail(frame, max_payload=100)
    assert error.code == "length-limit" and error.diagnostics["length"] == 200
    ok(frame, max_payload=200)
    with pytest.raises(ValueError):
        decode_strip(frame, max_payload=0)
    with pytest.raises(ValueError):
        decode_strip(frame, max_payload=70000)


def test_the_default_limit_is_the_envelope_limit():
    big = payload_of(ENVELOPE_MAX_BYTES, seed=9)
    ok(screen(big, cell=3, background="black", size=(600, 1500), at=(10, 10)), big)
    over = payload_of(ENVELOPE_MAX_BYTES + 1, seed=9)
    error = fail(screen(over, cell=3, background="black", size=(600, 1500), at=(10, 10)))
    assert error.code == "length-limit"


def test_a_frame_that_ends_inside_the_strip_is_truncated():
    payload = payload_of(480, seed=3)
    frame = screen(payload, size=(960, 540), at=(40, 30))
    cut = frame.crop(0, 0, frame.width, 30 + 4 * 20)
    error = fail(cut)
    assert error.code == "truncated" and error.diagnostics["rows_seen"] < strip.rows_needed(480)


def test_a_frame_that_ends_inside_the_header_row_is_not_read():
    frame = screen(DATA, at=(40, 30))
    assert fail(frame.crop(0, 0, frame.width, 30 + 4 * 3)).code in {"no-strip", "truncated"}


def test_a_damaged_ruler_never_gives_data():
    for col in (5, 40, 100, 159):
        try:
            result = decode_strip(screen(DATA, flip=[(0, col)]))
        except StripError as error:
            assert error.code in strip.REASONS
        else:
            assert result.payload == DATA


@pytest.mark.parametrize("kind", ["black", "white", "gradient", "stripes", "clutter"])
def test_a_frame_without_a_strip_says_so(kind):
    assert fail(blank(kind, (960, 540), seed=4)).code == "no-strip"


def test_random_cell_damage_is_caught_or_harmless_and_never_returns_other_data():
    payload = payload_of(120, seed=11)
    used_bits = len(strip.frame_bytes(payload)) * 8
    rng = random.Random(2024)
    caught = 0
    for trial in range(40):
        flips = []
        for _ in range(rng.randint(1, 6)):
            bit = rng.randrange(used_bits)
            flips.append((1 + bit // strip.COLUMNS, bit % strip.COLUMNS))
        try:
            result = decode_strip(screen(payload, flip=flips, seed=trial))
        except StripError as error:
            assert error.code in strip.REASONS
            caught += 1
        else:
            assert result.payload == payload
    assert caught == 40


def test_damage_to_unused_cells_after_the_payload_does_not_matter():
    payload = payload_of(20, seed=1)
    used_bits = len(strip.frame_bytes(payload)) * 8
    flips = [(1 + bit // strip.COLUMNS, bit % strip.COLUMNS) for bit in range(used_bits + 3, used_bits + 40)]
    ok(screen(payload, flip=flips), payload)


# --- frames and images --------------------------------------------------------------------------

@pytest.mark.parametrize("width,height,size", [(0, 5, 0), (5, 0, 0), (4, 4, 15), (4, 4, 17), (-1, 4, 4)])
def test_a_frame_must_match_its_pixel_count(width, height, size):
    with pytest.raises(ValueError):
        GrayFrame(width, height, bytes(size))


def test_crop_returns_the_window_and_refuses_an_empty_one():
    frame = GrayFrame(4, 3, bytes(range(12)))
    assert frame.crop(1, 1, 3, 3).pixels == bytes([5, 6, 9, 10])
    assert frame.crop(-5, -5, 100, 100) == frame
    with pytest.raises(ValueError):
        frame.crop(2, 2, 2, 3)


@pytest.mark.parametrize("mode", ["L", "RGB", "RGBA", "P"])
def test_images_of_any_mode_convert_and_read(mode, tmp_path):
    frame = screen(DATA, cell=3, background="black", size=(700, 330))
    image = PIL.frombytes("L", (frame.width, frame.height), frame.pixels).convert("RGB").convert(mode)
    target = tmp_path / f"strip-{mode}.png"
    image.save(target)
    with PIL.open(target) as loaded:
        ok(strip.frame_from_image(loaded))
