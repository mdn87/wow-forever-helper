"""The pixel-strip transport: a packet drawn as black and white cells and read back from a frame.

Format v1, as drawn by the companion addon and read from a captured image of the game window.

Layout. A grid of square cells, ``columns + 1`` wide (160 + 1 by default). Row 0 is the *ruler*:
cells alternate white, black, white, ... and the last cell, the terminator, is white. Every later
row holds ``columns`` data cells and then a terminator-column cell that keeps alternating down the
strip: black on row 1, white on row 2, and so on. The strip always has an even number of data rows
(one empty row is added when needed), so its last terminator-column cell is white. A white cell is
a 1 bit and a black cell a 0 bit. Data bits run row by row, most significant bit of each byte
first, and unused data cells are black. The grid sits on an opaque black backdrop that extends
``QUIET`` (two) cells beyond it on every side.

Frame bytes. ``A7 3C`` (magic), version, flags, payload length (two bytes, big endian), the
payload, then a CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) of every byte from the version
through the payload, two bytes, big endian. Version is 1 and flags are 0.

Why two rulers. The reader does not know where the strip is, how large its cells are on screen, or
how bright white and black came out after the game's colour handling and the capture. The top
ruler and the terminator column give all of it. Each is a run of equal cells between long black
margins, so the reader finds the strip as that pattern, measures where every column and every row
begins and ends, takes the two levels from the white and black ruler cells, and samples each data
cell at its own centre. Measuring every boundary, rather than one pitch, is what keeps a frame
read correctly when it was resized by an uneven factor and cells came out five and six pixels
wide in turn.

Two readings of the geometry are tried, the measured boundaries and an even grid fitted to the
strip's ends, and the CRC decides. There is no error correction. A damaged cell fails the CRC and
the frame is refused with ``crc-mismatch``; wrong data is never returned. Whether error
correction is worth its cost depends on how the real client renders the strip, which the probe
is meant to measure first.

The reader works on 8-bit luminance (``GrayFrame``). ``frame_from_image`` adapts a Pillow image.
Cells narrower than about two pixels are not reliable.
"""
import math
import re
from binascii import crc_hqx
from dataclasses import dataclass

from .envelope import ENVELOPE_MAX_BYTES

MAGIC = b"\xa7\x3c"
VERSION = 1
FLAGS = 0
COLUMNS = 160
QUIET = 2
MIN_COLUMNS = 32
MAX_COLUMNS = 512
HEADER_BYTES = 6
CRC_BYTES = 2
MIN_CONTRAST = 60
ROW_CONTRAST = 30
ROW_STEP = 2
MAX_CANDIDATES = 8
MIN_PITCH = 2.0

# How far a failed read got, so that the most informative reason is the one reported.
_RANK = {"no-strip": 0, "low-contrast": 1, "bad-magic": 2, "unsupported-version": 3,
         "unsupported-flags": 3, "length-limit": 4, "truncated": 5, "crc-mismatch": 6}
REASONS = {
    "no-strip": "no strip was found in the frame",
    "low-contrast": "a strip was found but white and black are too close together to tell apart",
    "bad-magic": "a pattern like a strip was found but it does not start with the strip marker",
    "unsupported-version": "the strip is a version this reader does not understand",
    "unsupported-flags": "the strip sets flags this reader does not understand",
    "length-limit": "the strip claims a payload larger than the limit",
    "truncated": "the frame ends before the strip does",
    "crc-mismatch": "the strip was read but its checksum does not match, so some cells were misread",
}


def describe(code):
    return REASONS.get(code, "unknown reason")


class StripError(Exception):
    """No packet could be read. ``diagnostics`` holds measurements only, never payload bytes."""

    def __init__(self, code, diagnostics=None):
        super().__init__(code)
        self.code = code
        self.diagnostics = dict(diagnostics or {})

    def __str__(self):
        return f"{self.code}: {describe(self.code)}"


@dataclass(frozen=True)
class StripResult:
    payload: bytes
    diagnostics: dict


@dataclass(frozen=True)
class GrayFrame:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self):
        if self.width < 1 or self.height < 1 or len(self.pixels) != self.width * self.height:
            raise ValueError("pixels must hold exactly width x height luminance bytes")

    def crop(self, left, top, right, bottom):
        left, top = max(0, left), max(0, top)
        right, bottom = min(self.width, right), min(self.height, bottom)
        if right <= left or bottom <= top:
            raise ValueError("the crop is empty")
        rows = [self.pixels[y * self.width + left:y * self.width + right] for y in range(top, bottom)]
        return GrayFrame(right - left, bottom - top, b"".join(rows))


def frame_from_image(image):
    """A ``GrayFrame`` from a Pillow image of any mode."""
    gray = image.convert("L")
    return GrayFrame(gray.width, gray.height, gray.tobytes())


# --- writing (the reference encoder, used by tests and the self-check) -----------------------------

def crc16(data):
    """CRC-16/CCITT-FALSE."""
    return crc_hqx(bytes(data), 0xFFFF)


def frame_bytes(payload, *, version=VERSION, flags=FLAGS):
    payload = bytes(payload)
    if len(payload) > 0xFFFF:
        raise ValueError("a strip payload is at most 65535 bytes")
    body = bytes([version, flags]) + len(payload).to_bytes(2, "big") + payload
    return MAGIC + body + crc16(body).to_bytes(2, "big")


def rows_needed(payload_length, columns=COLUMNS):
    """Data rows that the bits of a payload of this length fill (the strip adds one if that is odd)."""
    return math.ceil((HEADER_BYTES + payload_length + CRC_BYTES) * 8 / columns)


def encode_cells(payload, *, columns=COLUMNS, version=VERSION, flags=FLAGS):
    """The grid as rows of 0 and 1 cells: the ruler first, then the data rows, each ``columns + 1`` wide."""
    if columns % 2 or not MIN_COLUMNS <= columns <= MAX_COLUMNS:
        raise ValueError("columns must be even and within the supported range")
    data = frame_bytes(payload, version=version, flags=flags)
    bits = [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]
    needed = math.ceil(len(bits) / columns)
    rows = [[1 if index % 2 == 0 else 0 for index in range(columns + 1)]]
    for number in range(1, needed + needed % 2 + 1):
        chunk = bits[(number - 1) * columns:number * columns]
        rows.append(chunk + [0] * (columns - len(chunk)) + [1 if number % 2 == 0 else 0])
    return rows


def render_ideal(rows, cell=4, quiet=QUIET, white=255, black=0):
    """The grid as a ``GrayFrame`` with square cells and the black backdrop around it."""
    width = (len(rows[0]) + 2 * quiet) * cell
    margin = bytes([black]) * (quiet * cell)
    lines = [bytes([black]) * width] * (quiet * cell)
    for row in rows:
        line = margin + b"".join(bytes([white if bit else black]) * cell for bit in row) + margin
        lines.extend([line] * cell)
    lines.extend([bytes([black]) * width] * (quiet * cell))
    return GrayFrame(width, len(lines), b"".join(lines))


# --- finding a ruler --------------------------------------------------------------------------

_RUN = re.compile(rb"\x00+|\x01+")
_TABLES = {}


def _table(threshold):
    table = _TABLES.get(threshold)
    if table is None:
        table = _TABLES[threshold] = bytes(1 if value >= threshold else 0 for value in range(256))
    return table


def _runs_of(values, threshold):
    """(start, end, bit) for each run of equal bits once ``values`` are cut at the threshold."""
    binary = bytes(1 if value >= threshold else 0 for value in values)
    return [(m.start(), m.end(), binary[m.start()]) for m in _RUN.finditer(binary)]


def _edge(here, next_one, threshold, index):
    """Where the edge between pixel ``index`` and ``index + 1`` lies, to a fraction of a pixel.

    ``here`` and ``next_one`` are the luminance of those two pixels. A pixel's centre sits half a
    unit past its index, and the edge is where the luminance crosses the threshold between centres.
    """
    span = abs(next_one - here)
    fraction = 0.5 if span == 0 else min(1.0, abs(threshold - here) / span)
    return index + 0.5 + fraction


def _ruler_end(runs, start, limit):
    """Index of the last white run of the ruler whose first white run is ``start``.

    White runs of a ruler begin one period apart. Comparing those spacings, not the run lengths,
    keeps the test steady when pixels sitting on the threshold make white read a pixel wider and
    black a pixel narrower, or the other way round.
    """
    end, count, total = start, 0, 0
    while end + 2 < len(runs) and count < limit:
        spacing = runs[end + 2][0] - runs[end][0]
        if count and abs(spacing - total / count) > max(1.5, 0.25 * total / count):
            break
        end += 2
        count += 1
        total += spacing
    return end


def _row_candidates(runs, left, y):
    """Rulers in one thresholded row: white-start, white-end chains of runs of equal length."""
    found = []
    for k in range(1, len(runs) - 1):
        start, end, value = runs[k]
        if value != 1 or runs[k - 1][1] - runs[k - 1][0] < 1.2 * (end - start):
            continue
        j = _ruler_end(runs, k, MAX_COLUMNS)
        cells = j - k + 1
        if cells < MIN_COLUMNS + 1 or cells > MAX_COLUMNS + 1 or j + 1 >= len(runs):
            continue
        pitch = (runs[j][1] - runs[k][0]) / cells
        before = runs[k - 1][1] - runs[k - 1][0]
        after = runs[j + 1][1] - runs[j + 1][0]
        if runs[j + 1][2] != 0 or before < 1.4 * pitch or after < 1.4 * pitch:
            continue
        tolerance = max(1.5, 0.4 * pitch)
        if any(abs(runs[k + i][0] - (runs[k][0] + i * pitch)) > tolerance for i in range(cells)):
            continue
        found.append((left + runs[k][0], left + runs[j][1], cells, y))
    return found


def _search_region(frame, search):
    if search is None:
        return 0, 0, frame.width, frame.height
    left, top, right, bottom = search
    left, top = max(0, int(left)), max(0, int(top))
    right, bottom = min(frame.width, int(right)), min(frame.height, int(bottom))
    if right <= left or bottom <= top:
        raise ValueError("the search region is empty")
    return left, top, right, bottom


def _candidates(frame, region):
    left, top, right, bottom = region
    seen = []
    for y in range(top, bottom, ROW_STEP):
        row = frame.pixels[y * frame.width + left:y * frame.width + right]
        low, high = min(row), max(row)
        if high - low < ROW_CONTRAST:
            continue
        binary = row.translate(_table((low + high + 1) // 2))
        runs = [(m.start(), m.end(), binary[m.start()]) for m in _RUN.finditer(binary)]
        for first, last, cells, _ in _row_candidates(runs, left, y):
            if any(abs(first - s) <= 2 and cells == c and abs(y - sy) <= 8 for s, c, sy in seen):
                continue
            seen.append((first, cells, y))
            yield {"y": y, "first": first, "last": last, "cells": cells}


# --- measuring the strip ----------------------------------------------------------------------

def _boundaries(values, runs, first, last, threshold, offset):
    """Edge positions from the start of runs[first] to the end of runs[last], in frame coordinates."""
    out = []
    for index in range(first, last + 2):
        pixel = runs[index][0] if index <= last else runs[last][1]
        out.append(offset + _edge(values[pixel - 1], values[pixel], threshold, pixel - 1))
    return out


def _vertical_chain(frame, column, near, coarse_pitch):
    """Row boundaries down the terminator column, ruler row first. None if the column has no strip.

    Returns the boundary positions: one more than the number of rows seen.
    """
    reach = int(3 * coarse_pitch) + 3
    low_y, high_y = max(0, near - reach), min(frame.height - 1, near + reach)
    window = [frame.pixels[y * frame.width + column] for y in range(low_y, high_y + 1)]
    bright, dark = max(window), min(window)
    if bright - dark < ROW_CONTRAST:
        return None
    threshold = (bright + dark) / 2
    values = [frame.pixels[y * frame.width + column] for y in range(low_y, frame.height)]
    runs = _runs_of(values, threshold)
    target = near - low_y

    def gap(index):
        # The scan row that found the ruler can sit on its soft top edge, just outside the solid run.
        start, stop, _ = runs[index]
        return 0 if start <= target < stop else min(abs(target - start), abs(target - (stop - 1)))

    holders = [i for i, run in enumerate(runs) if run[2] == 1 and gap(i) <= 2]
    if not holders:
        return None
    k = min(holders, key=gap)
    if k == 0:
        return None
    end = _ruler_end(runs, k, MAX_COLUMNS)
    if end + 1 >= len(runs):
        end -= 2  # the last white run runs off the frame, so its far side is not an edge
    rows = end - k + 1
    if rows < 3:
        return None
    pitch = (runs[end][1] - runs[k][0]) / rows
    if runs[k - 1][1] - runs[k - 1][0] < 1.4 * pitch:
        return None
    return _boundaries(values, runs, k, end, threshold, low_y)


def _horizontal_chain(frame, row_y, first, last, cells, coarse_pitch):
    """Column boundaries along the ruler row, or None if its edges do not line up with the search."""
    row = frame.pixels[row_y * frame.width:(row_y + 1) * frame.width]
    pad = 3 * int(coarse_pitch + 1)
    start = max(0, first - pad)
    window = row[start:min(frame.width, last + pad)]
    threshold = (min(window) + max(window)) / 2
    runs = _runs_of(window, threshold)
    holders = [i for i, (s, e, v) in enumerate(runs) if v == 1 and i > 0 and abs(start + s - first) <= 4]
    if not holders:
        return None
    k = min(holders, key=lambda i: abs(start + runs[i][0] - first))
    end = k + cells - 1
    if end + 1 >= len(runs) or runs[end][2] != 1 or abs(start + runs[end][1] - last) > 4:
        return None
    return _boundaries(window, runs, k, end, threshold, start)


def _cell_mean(frame, cx, cy, half):
    """Mean luminance of the pixels whose centres lie within ``half`` of the point, or None if off frame."""
    x0, x1 = math.ceil(cx - half - 0.5), math.floor(cx + half - 0.5)
    y0, y1 = math.ceil(cy - half - 0.5), math.floor(cy + half - 0.5)
    if x1 < x0:
        x0 = x1 = math.floor(cx)
    if y1 < y0:
        y0 = y1 = math.floor(cy)
    if x0 < 0 or y0 < 0 or x1 >= frame.width or y1 >= frame.height:
        return None
    total = 0
    for y in range(y0, y1 + 1):
        base = y * frame.width
        total += sum(frame.pixels[base + x0:base + x1 + 1])
    return total / ((x1 - x0 + 1) * (y1 - y0 + 1))


def _read_grid(frame, xb, yb, max_payload, info):
    """Sample every cell at its centre given the column and row boundaries, and check the frame."""
    cells, rows_seen = len(xb) - 1, len(yb) - 1
    columns = cells - 1
    pitch_x, pitch_y = (xb[-1] - xb[0]) / cells, (yb[-1] - yb[0]) / rows_seen
    half = max(0.5, 0.25 * min(pitch_x, pitch_y))
    centre_x = [(xb[i] + xb[i + 1]) / 2 for i in range(cells)]
    centre_y = [(yb[i] + yb[i + 1]) / 2 for i in range(rows_seen)]

    ruler = [_cell_mean(frame, x, centre_y[0], half) for x in centre_x]
    if None in ruler:
        raise StripError("no-strip", info)
    whites, blacks = ruler[0::2], ruler[1::2]
    white, black = sum(whites) / len(whites), sum(blacks) / len(blacks)
    info.update(white=round(white, 1), black=round(black, 1), contrast=round(white - black, 1))
    if white - black < MIN_CONTRAST:
        raise StripError("low-contrast", info)
    middle = (white + black) / 2
    if min(whites) <= middle or max(blacks) >= middle:
        raise StripError("no-strip", info)
    info["origin"] = [round(xb[0], 1), round(yb[0], 1)]

    sampled = []
    weakest = [1.0]
    done = [0]

    def sample_until(last_row):
        """Read data rows up to ``last_row`` (row 0 is the ruler). False if the strip ends first."""
        if last_row > rows_seen - 1:
            return False
        while done[0] < last_row:
            index = done[0] + 1
            values = [_cell_mean(frame, centre_x[col], centre_y[index], half) for col in range(columns)]
            if None in values:
                return False
            for value in values:
                weakest[0] = min(weakest[0], abs(value - middle) / ((white - black) / 2))
                sampled.append(1 if value >= middle else 0)
            done[0] = index
        return True

    def read_bytes(count):
        return bytes(sum(bit << (7 - n) for n, bit in enumerate(sampled[i * 8:i * 8 + 8])) for i in range(count))

    if not sample_until(math.ceil(HEADER_BYTES * 8 / columns)):
        raise StripError("truncated", info)
    head = read_bytes(HEADER_BYTES)
    if head[:2] != MAGIC:
        raise StripError("bad-magic", info)
    if head[2] != VERSION:
        raise StripError("unsupported-version", info)
    if head[3] != FLAGS:
        raise StripError("unsupported-flags", info)
    length = int.from_bytes(head[4:6], "big")
    info["length"] = length
    if length > max_payload:
        raise StripError("length-limit", info)
    info["rows"] = rows_needed(length, columns)
    if not sample_until(info["rows"]):
        raise StripError("truncated", info)
    data = read_bytes(HEADER_BYTES + length + CRC_BYTES)
    info["weakest_margin"] = round(weakest[0], 2)
    if crc16(data[2:HEADER_BYTES + length]) != int.from_bytes(data[HEADER_BYTES + length:], "big"):
        raise StripError("crc-mismatch", info)
    return StripResult(data[HEADER_BYTES:HEADER_BYTES + length], info)


def _decode_candidate(frame, candidate, max_payload):
    cells, y_row = candidate["cells"], candidate["y"]
    first, last = candidate["first"], candidate["last"]
    coarse_pitch = (last - first) / cells
    info = {"columns": cells - 1, "pitch_x": round(coarse_pitch, 2)}

    yb = _vertical_chain(frame, int(first + (cells - 0.5) * coarse_pitch), y_row, coarse_pitch)
    if yb is None:
        raise StripError("no-strip", info)
    rows_seen = len(yb) - 1
    xb = _horizontal_chain(frame, min(frame.height - 1, int((yb[0] + yb[1]) / 2)), first, last, cells, coarse_pitch)
    left, right = (xb[0], xb[-1]) if xb else (float(first), float(last))
    pitch_x, pitch_y = (right - left) / cells, (yb[-1] - yb[0]) / rows_seen
    info.update(pitch_x=round(pitch_x, 2), pitch_y=round(pitch_y, 2), rows_seen=rows_seen)
    if not 0.5 * pitch_x <= pitch_y <= 2.0 * pitch_x or min(pitch_x, pitch_y) < MIN_PITCH:
        raise StripError("no-strip", info)

    readings = []
    if xb is not None:
        readings.append((xb, yb))
    readings.append(([left + i * pitch_x for i in range(cells + 1)], [yb[0] + i * pitch_y for i in range(rows_seen + 1)]))
    failure = None
    for columns_at, rows_at in readings:
        try:
            return _read_grid(frame, columns_at, rows_at, max_payload, dict(info))
        except StripError as error:
            if failure is None or _RANK[error.code] > _RANK[failure.code]:
                failure = error
    raise failure


def decode_strip(frame, *, max_payload=ENVELOPE_MAX_BYTES, search=None):
    """Find a strip in the frame and return its payload, or raise ``StripError`` naming the reason.

    ``search`` is an optional ``(left, top, right, bottom)`` window to look in. A pattern that looks
    like a ruler but does not decode does not stop the search; the failure that got furthest is the
    one reported if nothing decodes.
    """
    if not 1 <= max_payload <= 0xFFFF:
        raise ValueError("max_payload must be between 1 and 65535")
    region = _search_region(frame, search)
    best, tried = None, 0
    for candidate in _candidates(frame, region):
        tried += 1
        try:
            result = _decode_candidate(frame, candidate, max_payload)
        except StripError as error:
            if best is None or _RANK[error.code] > _RANK[best.code]:
                best = error
        else:
            result.diagnostics["candidates"] = tried
            return result
        if tried >= MAX_CANDIDATES:
            break
    if best is None:
        raise StripError("no-strip", {"candidates": 0})
    best.diagnostics["candidates"] = tried
    raise best
