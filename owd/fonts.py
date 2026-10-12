"""How big libass will draw a font, worked out ahead of time so captions can be laid out in Python.

libass (like VSFilter) sizes text so that the font's Windows ascent plus descent equals the ASS
font size, which makes the em size font-dependent. Reading those numbers from the font file gives
the em size in pixels, and Pillow can then measure a caption's width as it will be drawn.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


@lru_cache
def font_metrics(path: str) -> tuple[int, int, int]:
    """(unitsPerEm, usWinAscent, usWinDescent) from a TrueType/OpenType font file."""
    data = Path(path).read_bytes()
    (num_tables,) = struct.unpack_from(">H", data, 4)
    tables = {}
    for index in range(num_tables):
        tag, _checksum, offset, _length = struct.unpack_from(">4sIII", data, 12 + 16 * index)
        tables[tag] = offset
    if b"head" not in tables or b"OS/2" not in tables:
        raise ValueError(f"{path} lacks a head or OS/2 table (font collections aren't supported)")
    (units_per_em,) = struct.unpack_from(">H", data, tables[b"head"] + 18)
    win_ascent, win_descent = struct.unpack_from(">HH", data, tables[b"OS/2"] + 74)
    return units_per_em, win_ascent, win_descent


def ass_em_pixels(path: Path | str, ass_size: float) -> float:
    """Em size in pixels that libass uses for font size `ass_size` (PlayRes equal to the video size)."""
    units_per_em, win_ascent, win_descent = font_metrics(str(path))
    return ass_size * units_per_em / (win_ascent + win_descent)


class TextMeter:
    """Width of one line of text as libass draws it, outline included."""

    def __init__(self, path: Path | str, ass_size: float, outline: float = 0.0):
        self.font = ImageFont.truetype(str(path), ass_em_pixels(path, ass_size))
        self.outline = outline

    def width(self, text: str) -> float:
        return self.font.getlength(text) + 2 * self.outline if text else 0.0
