"""Synthetic screens for the strip reader: the ideal grid on a busy background, then degraded.

Everything here is invented. The point is to cover the ways a real capture differs from the grid
the addon meant to draw (other colours for white and black, soft edges, noise, a different size)
without needing the game.
"""
import random

from wow_helper.context import strip


def _background(kind, width, height, seed):
    rng = random.Random(seed)
    if kind == "black":
        return [bytearray(width) for _ in range(height)]
    if kind == "white":
        return [bytearray(b"\xff" * width) for _ in range(height)]
    if kind == "gradient":
        return [bytearray(((x * 255) // max(1, width - 1) + y) % 256 for x in range(width)) for y in range(height)]
    if kind == "stripes":
        # Periodic bars close to the strip's own pitch: a ruler decoy in every row.
        return [bytearray(255 if (x // 5) % 2 == 0 else 0 for x in range(width)) for _ in range(height)]
    if kind == "clutter":
        # Blocks of random brightness, so bright and dark scene pixels touch the strip's margin.
        block_w, block_h = 7, 5
        columns = (width + block_w - 1) // block_w
        rows = []
        for by in range((height + block_h - 1) // block_h):
            levels = [rng.randrange(256) for _ in range(columns)]
            line = bytearray(b"".join(bytes([level]) * block_w for level in levels)[:width])
            rows.extend(bytearray(line) for _ in range(block_h))
        return rows[:height]
    raise ValueError(kind)


def _blur(rows, box, radius):
    left, top, right, bottom = box
    for y in range(top, bottom):
        line = rows[y][left:right]
        padded = [line[0]] * radius + list(line) + [line[-1]] * radius
        width = 2 * radius + 1
        rows[y][left:right] = bytes(sum(padded[x:x + width]) // width for x in range(len(line)))
    for x in range(left, right):
        column = [rows[y][x] for y in range(top, bottom)]
        padded = [column[0]] * radius + column + [column[-1]] * radius
        width = 2 * radius + 1
        for index, y in enumerate(range(top, bottom)):
            rows[y][x] = sum(padded[index:index + width]) // width


def screen(payload, *, cell=4, columns=strip.COLUMNS, size=(960, 540), at=(40, 30), background="clutter",
           white=255, black=0, gamma=1.0, blur=0, noise=0, seed=1, flip=(), version=strip.VERSION,
           flags=strip.FLAGS, quiet=strip.QUIET, rows=None):
    """The strip placed with its backdrop's corner at ``at`` on a ``size`` frame, then degraded.

    ``flip`` lists (grid row, grid column) cells to invert before drawing. ``rows`` replaces the
    encoded grid when a test needs a hand-made one.
    """
    grid = [list(row) for row in (rows or strip.encode_cells(payload, columns=columns, version=version, flags=flags))]
    for row, col in flip:
        grid[row][col] ^= 1
    ideal = strip.render_ideal(grid, cell, quiet)
    width, height = size
    canvas = _background(background, width, height, seed)
    x0, y0 = at
    for y in range(ideal.height):
        if 0 <= y0 + y < height:
            line = ideal.pixels[y * ideal.width:(y + 1) * ideal.width]
            clipped = line[max(0, -x0):max(0, width - x0)]
            canvas[y0 + y][max(0, x0):max(0, x0) + len(clipped)] = clipped
    levels = bytes(round(black + (white - black) * ((value / 255) ** gamma)) for value in range(256))
    for line in canvas:
        line[:] = line.translate(levels)
    box = (max(0, x0 - 6), max(0, y0 - 6), min(width, x0 + ideal.width + 6), min(height, y0 + ideal.height + 6))
    if blur:
        _blur(canvas, box, blur)
    if noise:
        rng = random.Random(seed + 1000)
        for y in range(box[1], box[3]):
            span = box[2] - box[0]
            jitter = rng.randbytes(span)
            line = canvas[y]
            line[box[0]:box[2]] = bytes(min(255, max(0, line[box[0] + i] + jitter[i] % (2 * noise + 1) - noise))
                                        for i in range(span))
    return strip.GrayFrame(width, height, b"".join(bytes(line) for line in canvas))


def payload_of(length, seed=0):
    return random.Random(seed).randbytes(length)


def blank(background, size=(960, 540), seed=1):
    """A frame with no strip on it."""
    width, height = size
    return strip.GrayFrame(width, height, b"".join(bytes(line) for line in _background(background, width, height, seed)))


def stack(top, bottom, gap=20):
    """Two frames one above the other, the narrower padded with black, with a black gap between."""
    width = max(top.width, bottom.width)

    def padded(frame):
        return [frame.pixels[y * frame.width:(y + 1) * frame.width].ljust(width, b"\x00") for y in range(frame.height)]

    lines = padded(top) + [bytes(width)] * gap + padded(bottom)
    return strip.GrayFrame(width, len(lines), b"".join(lines))
