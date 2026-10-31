"""Puts the rectangles the probe addon asks the game to draw onto invented screens for the strip reader.

Everything is synthetic. A rectangle is (left, top, width, height) in physical pixels, measured from
the strip's own top left corner, as ``ProbeAddon.strip_pixels`` reports it.
"""
import random

import context_render
from wow_helper.context import strip


def backdrop_with_rectangles(frame_size, rects):
    """The strip on its own: a black backdrop with the white rectangles on it."""
    width, height = frame_size
    lines = [bytearray(width) for _ in range(height)]
    for left, top, span, rows in rects:
        for y in range(top, top + rows):
            lines[y][left:left + span] = bytes([255]) * span
    return strip.GrayFrame(width, height, b"".join(bytes(line) for line in lines))


def on_screen(frame_size, rects, *, size=(1280, 720), at=(0, 0), background="clutter", seed=1, label_clutter=False):
    """The strip placed on an invented screen.

    ``label_clutter`` scatters bright specks in the band just under the backdrop, where the addon's
    text label sits in the game, so the reader meets glyph-like noise next to the last row.
    """
    width, height = size
    base = context_render.blank(background, size, seed)
    canvas = [bytearray(base.pixels[y * width:(y + 1) * width]) for y in range(height)]
    frame_width, frame_height = frame_size
    left0, top0 = at
    for y in range(frame_height):
        canvas[top0 + y][left0:left0 + frame_width] = bytes(frame_width)
    for left, top, span, rows in rects:
        for y in range(top0 + top, top0 + top + rows):
            canvas[y][left0 + left:left0 + left + span] = bytes([255]) * span
    if label_clutter:
        rng = random.Random(seed)
        for x in range(left0, min(width - 2, left0 + 560), 6):
            for _ in range(2):
                speck = x + rng.randrange(0, 4)
                top = top0 + frame_height + 3 + rng.randrange(0, 8)
                for y in range(top, min(height, top + rng.randrange(2, 7))):
                    if speck + 2 <= width:
                        canvas[y][speck:speck + 2] = bytes([255, 255])
    return strip.GrayFrame(width, height, b"".join(bytes(line) for line in canvas))
