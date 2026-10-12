"""On-screen text for long videos, drawn by ffmpeg's subtitles filter (libass):

- quote cards: while the narrator reads a line from the book, the footage dims and the words
  appear in a classic serif with the author's name underneath;
- chapter cards: a short title at the start of each chapter after the first (the hook starts
  straight away, with no title card in front of it).

Text is wrapped here with the real font metrics, so nothing runs off screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from owd.captions import ass_color, ass_time
from owd.config import FONTS_DIR, LONG
from owd.fonts import TextMeter

SERIF = FONTS_DIR / "LibreBaskerville.ttf"  # SIL Open Font License, see OFL-LibreBaskerville.txt
SERIF_ITALIC = FONTS_DIR / "LibreBaskerville-Italic.ttf"
SERIF_NAME = "Libre Baskerville"


@dataclass(frozen=True)
class QuoteCard:
    text: str
    start: float  # when the narrator starts reading it
    end: float  # when they finish
    cite: str = ""


@dataclass(frozen=True)
class ChapterCard:
    number: int
    title: str
    start: float


@dataclass(frozen=True)
class OverlayStyle:
    quote_color: str = "#F6E7C8"  # warm cream, like old paper
    cite_color: str = "#C9A86A"  # muted gold
    title_color: str = "#FFFFFF"
    quote_sizes: tuple[int, ...] = (68, 62, 56, 50, 46)
    quote_width: int = 1360
    quote_max_lines: int = 6
    cite_size: int = 34
    chapter_size: int = 84
    chapter_label_size: int = 40
    quote_dim: int = 0x66  # ASS alpha of the black layer behind quotes: 0x00 opaque ... 0xFF clear
    chapter_dim: int = 0x88
    fade_in: int = 450  # milliseconds
    fade_out: int = 600
    lead: float = 0.3  # a quote card appears this long before the first word...
    hold: float = 1.3  # ...and stays this long after the last
    chapter_seconds: float = 3.4


def wrap_lines(text: str, meter: TextMeter, max_width: float) -> list[str]:
    """Greedy word wrap by measured width."""
    lines: list[str] = []
    for word in text.split():
        if lines and meter.width(f"{lines[-1]} {word}") <= max_width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def balance(lines: list[str], meter: TextMeter, max_width: float) -> list[str]:
    """The same number of lines, with the widths evened out (no one-word last line)."""
    words = " ".join(lines).split()
    count = len(lines)
    if count < 2:
        return lines
    low, high = max(meter.width(word) for word in words), max_width
    best = lines
    for _ in range(20):  # binary search for the narrowest width that still fits in `count` lines
        middle = (low + high) / 2
        attempt = wrap_lines(" ".join(words), meter, middle)
        if len(attempt) <= count:
            best, high = attempt, middle
        else:
            low = middle
    return best


def layout_quote(text: str, style: OverlayStyle = OverlayStyle()) -> tuple[int, list[str]]:
    """(font size, lines) for a quote: the largest size that fits in quote_max_lines."""
    for size in style.quote_sizes:
        meter = TextMeter(SERIF_ITALIC, size)
        lines = wrap_lines(text, meter, style.quote_width)
        if len(lines) <= style.quote_max_lines:
            return size, balance(lines, meter, style.quote_width)
    size = style.quote_sizes[-1]
    meter = TextMeter(SERIF_ITALIC, size)
    return size, wrap_lines(text, meter, style.quote_width)


def roman(number: int) -> str:
    values = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
              (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for value, letters in values:
        while number >= value:
            out += letters
            number -= value
    return out


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def _dim(start: float, end: float, alpha: int, size: tuple[int, int], fade: tuple[int, int]) -> str:
    width, height = size
    return (
        f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Dim,,0,0,0,,"
        f"{{\\an7\\pos(0,0)\\fad({fade[0]},{fade[1]})\\1a&H{alpha:02X}&\\p1}}"
        f"m 0 0 l {width} 0 {width} {height} 0 {height}{{\\p0}}"
    )


def overlays_ass(
    quotes: Sequence[QuoteCard],
    chapters: Sequence[ChapterCard],
    style: OverlayStyle = OverlayStyle(),
    size: tuple[int, int] = LONG.size,
) -> str:
    width, height = size
    quote, cite, title = (ass_color(c, None) for c in (style.quote_color, style.cite_color, style.title_color))
    lines = [
        "[Script Info]",
        "; Made by old-wisdom-decoded",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Dim,Arial,20,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: Quote,{SERIF_NAME},{style.quote_sizes[0]},{ass_color(style.quote_color)},&H000000FF,"
        f"&H00000000,&H96000000,0,-1,0,0,100,100,0,0,1,0,3,5,120,120,0,1",
        f"Style: Chapter,{SERIF_NAME},{style.chapter_size},{ass_color(style.title_color)},&H000000FF,"
        f"&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,0,3,5,120,120,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fade = (style.fade_in, style.fade_out)
    quote_windows = []
    for card in quotes:
        start, end = max(card.start - style.lead, 0.0), card.end + style.hold
        quote_windows.append((start, end))
        font_size, text_lines = layout_quote(card.text, style)
        body = "\\N".join(_escape(line) for line in text_lines)
        if card.cite:
            body += f"\\N{{\\fs{style.cite_size // 2}}} \\N{{\\fs{style.cite_size}\\i0\\c{cite}}}— {_escape(card.cite)}"
        lines.append(_dim(start, end, style.quote_dim, size, fade))
        lines.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Quote,,0,0,0,,"
            f"{{\\fad({fade[0]},{fade[1]})\\fs{font_size}\\c{quote}}}{body}"
        )
    for card in chapters:
        start, end = max(card.start - 0.35, 0.0), card.start - 0.35 + style.chapter_seconds
        for q_start, q_end in quote_windows:  # never on top of a quote card
            if q_start < end and q_end > start:
                end = min(end, q_start - 0.05)
        if end - start < 1.5:
            continue  # too little room before a quote card: skip the title rather than flash it
        label = f"{{\\fs{style.chapter_label_size}\\fsp6\\c{cite}}}CHAPTER {roman(card.number)}"
        lines.append(_dim(start, end, style.chapter_dim, size, (350, 500)))
        lines.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Chapter,,0,0,0,,"
            f"{{\\fad(350,500)}}{label}\\N{{\\fsp0\\fs{style.chapter_size}\\c{title}}}{_escape(card.title)}"
        )
    return "\n".join(lines) + "\n"
