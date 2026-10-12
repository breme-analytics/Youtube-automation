"""YouTube thumbnails: 1280x720 JPEG under YouTube's 2 MB limit. A background, a dark fade behind
the text, and a short headline in heavy capitals with an outline and a soft shadow; chosen words
are gold. The headline is sized as large as its box allows, over one to three lines."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from owd.backgrounds import glow_background
from owd.config import DISPLAY_FONT, THUMBNAIL_SIZE

MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ThumbnailStyle:
    text_color: tuple[int, int, int] = (255, 255, 255)
    accent_color: tuple[int, int, int] = (255, 212, 71)
    outline_color: tuple[int, int, int] = (0, 0, 0)
    box: tuple[float, float, float, float] = (0.05, 0.1, 0.58, 0.8)  # text area: x, y, width, height
    max_lines: int = 3
    max_font: int = 240
    min_font: int = 56
    line_gap: float = 0.12  # space between lines, as a fraction of the font size
    outline: float = 0.05  # outline width, as a fraction of the font size
    shade: int = 215  # opacity (0-255) of the dark fade at the left edge


def _layouts(words: list[str], max_lines: int):
    """Every way to break `words` into 1..max_lines lines without reordering them."""
    for lines in range(1, min(max_lines, len(words)) + 1):
        for cuts in itertools.combinations(range(1, len(words)), lines - 1):
            bounds = (0, *cuts, len(words))
            yield [words[a:b] for a, b in zip(bounds, bounds[1:])]


def _cap_height(font: ImageFont.FreeTypeFont) -> int:
    return -font.getbbox("H", anchor="ls")[1]


def fit_headline(
    words: list[str], box_size: tuple[int, int], style: ThumbnailStyle = ThumbnailStyle(), font_path: Path = DISPLAY_FONT
) -> tuple[ImageFont.FreeTypeFont, list[list[str]]]:
    """Font and line breaks for `words` (already upper-cased) in the box: as large as possible,
    but a slightly smaller font wins if it gives much more even lines (no lone "HE" on top)."""
    box_w, box_h = box_size
    best: tuple[float, ImageFont.FreeTypeFont, list[list[str]]] | None = None
    for size in range(style.max_font, style.min_font - 1, -4):
        if best is not None and size <= best[0]:
            break  # even perfectly even lines at this size can't beat the best so far
        font = ImageFont.truetype(str(font_path), size)
        outline = round(size * style.outline)
        space = font.getlength(" ")
        cap, gap = _cap_height(font), size * style.line_gap
        for layout in _layouts(words, style.max_lines):
            widths = [sum(font.getlength(w) for w in line) + space * (len(line) - 1) + 2 * outline for line in layout]
            height = len(layout) * cap + (len(layout) - 1) * gap + 2 * outline
            if max(widths) <= box_w and height <= box_h:
                score = size * (0.7 + 0.3 * min(widths) / max(widths))
                if best is None or score > best[0]:
                    best = (score, font, layout)
    if best is None:
        raise ValueError(f"Headline too long for a thumbnail: {' '.join(words)!r}")
    return best[1], best[2]


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, Image.Resampling.LANCZOS)


def _shade(size: tuple[int, int], reach: float, opacity: int) -> Image.Image:
    """A mask that is `opacity` at the left edge and fades to nothing at `reach` of the width."""
    width, height = size
    ramp = np.clip(1.0 - np.arange(width, dtype=np.float32) / (reach * width), 0.0, 1.0) ** 1.6
    return Image.fromarray(np.tile((ramp * opacity).astype(np.uint8), (height, 1)), "L")


def make_thumbnail(
    headline: str,
    out: Path,
    *,
    background: Path | Image.Image | None = None,
    accent: Iterable[str] = (),
    style: ThumbnailStyle = ThumbnailStyle(),
    size: tuple[int, int] = THUMBNAIL_SIZE,
    font_path: Path = DISPLAY_FONT,
) -> Path:
    """Draw `headline` over `background` (a file or image; a generated glow if None) and save a
    JPEG. Words in `accent` (matched without case) are drawn in the accent colour."""
    width, height = size
    if background is None:
        base = glow_background(size, palette="dawn", seed=7, center=(0.78, 0.4))
    else:
        base = _cover(Image.open(background) if isinstance(background, (str, Path)) else background, size)
    box_x, box_y, box_w, box_h = (round(v * d) for v, d in zip(style.box, (width, height, width, height)))
    canvas = Image.composite(Image.new("RGB", size, (0, 0, 0)), base, _shade(size, style.box[0] + style.box[2] + 0.12, style.shade))

    words = headline.upper().split()
    accent_words = {w.upper().strip(".,!?:;\"'") for w in accent}
    font, layout = fit_headline(words, (box_w, box_h), style, font_path)
    outline = round(font.size * style.outline)
    cap, gap, space = _cap_height(font), font.size * style.line_gap, font.getlength(" ")
    block = len(layout) * cap + (len(layout) - 1) * gap + 2 * outline
    top = box_y + (box_h - block) / 2 + outline

    text_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw, shadow_draw = ImageDraw.Draw(text_layer), ImageDraw.Draw(shadow_layer)
    for index, line in enumerate(layout):
        baseline = top + cap + index * (cap + gap)
        x = box_x + outline
        for word in line:
            colour = style.accent_color if word.strip(".,!?:;\"'") in accent_words else style.text_color
            draw.text((x, baseline), word, font=font, fill=colour, anchor="ls",
                      stroke_width=outline, stroke_fill=style.outline_color)
            shadow_draw.text((x + font.size * 0.03, baseline + font.size * 0.045), word, font=font,
                             fill=(0, 0, 0, 170), anchor="ls", stroke_width=outline, stroke_fill=(0, 0, 0, 170))
            x += font.getlength(word) + space
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(font.size * 0.05))
    result = Image.alpha_composite(Image.alpha_composite(canvas.convert("RGBA"), shadow_layer), text_layer).convert("RGB")

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    for quality in (92, 86, 80, 72, 64):
        buffer = BytesIO()
        result.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
        if buffer.tell() <= MAX_BYTES:
            Path(out).write_bytes(buffer.getvalue())
            return Path(out)
    raise ValueError("Thumbnail is over 2 MB even at low JPEG quality")
