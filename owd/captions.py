"""Captions from word timings.

Shorts get burned-in captions: up to three words at a time with the spoken word in gold, written
as ASS so ffmpeg's subtitles filter (libass) draws them. Long videos get an SRT file that is
uploaded with the video, so viewers can switch captions on or off.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from owd.config import DISPLAY_FONT, DISPLAY_FONT_NAME, SHORT
from owd.fonts import TextMeter
from owd.words import Word

_CLOSERS = "\"”’')\\]"
_CLAUSE_END = re.compile(rf"[.!?…;:][{_CLOSERS}]*$")  # a Short's caption page ends here
_SOFT_END = re.compile(rf"[,—–][{_CLOSERS}]*$")  # ...or here, once it has two words
_SENTENCE_END = re.compile(rf"[.!?…][{_CLOSERS}]*$")  # an SRT cue ends here


@dataclass(frozen=True)
class ShortCaptionStyle:
    font_size: int = 190  # ASS units: Anton's capitals come out about 95 px tall
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFD447"
    quote_color: str = "#F6E7C8"  # words read from the original book: warm cream, like old paper
    outline_color: str = "#000000"
    outline: float = 9.0
    shadow: float = 4.0
    margin_bottom: int = 700  # Shorts' title, channel name and description cover the bottom fifth
    margin_side: int = 130  # the like/comment/share buttons run down the right edge
    max_words: int = 3
    pause_break: float = 0.45  # a silence this long starts a new page
    hold: float = 0.3  # how long a page stays up after its last word when nothing follows at once
    uppercase: bool = True


def ass_color(hex_rgb: str, alpha: int | None = 0) -> str:
    """'#RRGGBB' in ASS order: &HAABBGGRR for styles, &HBBGGRR& (alpha=None) for override tags."""
    value = hex_rgb.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError(f"Expected a colour like #FFD447, got {hex_rgb!r}")
    bgr = (value[4:6] + value[2:4] + value[0:2]).upper()
    return f"&H{bgr}&" if alpha is None else f"&H{alpha:02X}{bgr}"


def ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    # Braces open override blocks and backslashes start tags such as \N.
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def short_text(text: str, uppercase: bool = True) -> str:
    """A word as a Short's caption shows it: no quote marks, no trailing commas or full stops."""
    text = text.strip().strip("\"“”«»()[]")
    text = re.sub(r"[\s.,;:—–-]+$", "", text)
    text = re.sub(r"^[\s—–-]+", "", text).strip("\"“”")
    return text.upper() if uppercase else text


def short_pages(
    words: Sequence[Word], style: ShortCaptionStyle, meter: TextMeter, max_width: float
) -> list[list[tuple[Word, str]]]:
    """Group words into caption pages of (word, caption text) that fit on one line.

    Phrases end at sentence or clause punctuation and at pauses. Each phrase is split into the
    fewest pages of at most `max_words`, avoiding single-word leftovers ("OR UNMADE | BY HIMSELF",
    not "OR UNMADE BY | HIMSELF") and preferring to break after commas."""
    phrases: list[list[tuple[Word, str]]] = [[]]
    for word in words:
        label = short_text(word.text, style.uppercase)
        if not label:
            continue
        if phrases[-1]:
            previous = phrases[-1][-1][0]
            if word.start - previous.end >= style.pause_break or _CLAUSE_END.search(previous.text):
                phrases.append([])
        phrases[-1].append((word, label))
    pages: list[list[tuple[Word, str]]] = []
    for phrase in phrases:
        start = 0
        for length in _page_lengths(phrase, style.max_words, meter, max_width):
            pages.append(phrase[start : start + length])
            start += length
    return pages


def _page_lengths(phrase: list[tuple[Word, str]], max_words: int, meter: TextMeter, max_width: float) -> list[int]:
    """Cheapest split of one phrase into pages: each page costs 1, a lone word 0.8 more, and a comma
    inside a page (rather than at its end) 0.5 more. Ties go to longer first pages."""
    n = len(phrase)
    best: list[tuple[float, list[int]]] = [(float("inf"), [])] * n + [(0.0, [])]
    for i in range(n - 1, -1, -1):
        for j in range(i + 1, min(i + max_words, n) + 1):
            page = phrase[i:j]
            if j - i > 1 and meter.width(" ".join(label for _, label in page)) > max_width:
                break  # longer pages from here are wider still
            cost = 1.0 + (0.8 if j - i == 1 and n > 1 else 0.0)
            cost += 0.5 * sum(1 for word, _ in page[:-1] if _SOFT_END.search(word.text))
            if cost + best[j][0] <= best[i][0]:
                best[i] = (cost + best[j][0], [j - i, *best[j][1]])
    return best[0][1]


def shorts_ass(
    words: Sequence[Word],
    style: ShortCaptionStyle = ShortCaptionStyle(),
    size: tuple[int, int] = SHORT.size,
    font_path: Path = DISPLAY_FONT,
    font_name: str = DISPLAY_FONT_NAME,
) -> str:
    """ASS captions for a Short: one event per word, so exactly the spoken word is highlighted."""
    width, height = size
    meter = TextMeter(font_path, style.font_size, outline=style.outline)
    max_width = width - 2 * style.margin_side
    pages = short_pages(words, style, meter, max_width)
    highlight, normal = ass_color(style.highlight_color, None), ass_color(style.text_color, None)
    quote = ass_color(style.quote_color, None)

    lines = [
        "[Script Info]",
        "; Made by old-wisdom-decoded",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",  # never wrap: pages are measured to fit one line
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Short,{font_name},{style.font_size},{ass_color(style.text_color)},{ass_color(style.highlight_color)},"
        f"{ass_color(style.outline_color)},{ass_color('#000000', 0x80)},0,0,0,0,100,100,0,0,1,"
        f"{style.outline:g},{style.shadow:g},2,{style.margin_side},{style.margin_side},{style.margin_bottom},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for index, page in enumerate(pages):
        last = page[-1][0]
        page_end = last.end + style.hold
        if index + 1 < len(pages):
            page_end = min(page_end, pages[index + 1][0][0].start)
        page_end = max(page_end, last.end)
        page_text = " ".join(text for _, text in page)
        page_width = meter.width(page_text)
        # A single word too long for the line is squeezed rather than run off the screen.
        squeeze = ""
        if page_width > max_width:
            scale = int(100 * max_width / page_width)
            squeeze = f"{{\\fscx{scale}\\fscy{scale}}}"
        for k, (word, _) in enumerate(page):
            start = word.start
            end = page[k + 1][0].start if k + 1 < len(page) else page_end
            if round(end * 100) <= round(start * 100):
                continue  # untimed or zero-length word: it shows, but is never the highlighted one
            parts = []
            for j, (other, text) in enumerate(page):
                colour = highlight if j == k else (quote if other.quote else normal)
                parts.append(f"{{\\c{colour}}}{_ass_escape(text)}")
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Short,,0,0,0,,{squeeze}{' '.join(parts)}")
    return "\n".join(lines) + "\n"


def wrap_cue(text: str, max_line: int = 42) -> list[str]:
    """One line, or two balanced lines of at most `max_line` characters (preferring a split after
    punctuation); longer text falls back to plain wrapping."""
    if len(text) <= max_line:
        return [text]
    words = text.split(" ")
    best: tuple[int, list[str]] | None = None
    for i in range(1, len(words)):
        top, bottom = " ".join(words[:i]), " ".join(words[i:])
        if len(top) <= max_line and len(bottom) <= max_line:
            score = max(len(top), len(bottom)) - (6 if top.endswith((",", ";", ":", "—")) else 0)
            if best is None or score < best[0]:
                best = (score, [top, bottom])
    return best[1] if best else textwrap.wrap(text, max_line)


def srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _cue_fits(group: Sequence[Word], max_line: int, max_duration: float) -> bool:
    lines = wrap_cue(" ".join(word.text for word in group), max_line)
    return len(lines) <= 2 and all(len(line) <= max_line for line in lines) and (
        group[-1].end - group[0].start <= max_duration
    )


def _split_cue(group: list[Word], max_line: int, max_duration: float) -> list[list[Word]]:
    """Halve a sentence that won't fit one cue, preferring a comma or colon near the middle, and
    repeat until every part fits."""
    if len(group) == 1 or _cue_fits(group, max_line, max_duration):
        return [group]
    texts = [word.text for word in group]
    total = len(" ".join(texts))
    best, best_score, left = 1, float("inf"), -1
    for i in range(1, len(group)):
        left += len(texts[i - 1]) + 1  # length of " ".join(texts[:i])
        score = abs(left - (total - left - 1)) - (30 if _SOFT_END.search(texts[i - 1]) or texts[i - 1].endswith((";", ":")) else 0)
        if score < best_score:
            best, best_score = i, score
    return _split_cue(group[:best], max_line, max_duration) + _split_cue(group[best:], max_line, max_duration)


def srt_cues(
    words: Sequence[Word],
    max_line: int = 42,
    max_duration: float = 6.0,
    pause_break: float = 0.6,
    min_duration: float = 1.0,
) -> list[tuple[float, float, list[str]]]:
    """(start, end, lines) cues: one sentence per cue, split into balanced parts when it doesn't
    fit in two lines of `max_line` characters and `max_duration` seconds."""
    sentences: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        if current and word.start - current[-1].end >= pause_break:
            sentences.append(current)
            current = []
        current.append(word)
        if _SENTENCE_END.search(word.text):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    groups = [part for sentence in sentences for part in _split_cue(sentence, max_line, max_duration)]

    cues = []
    for index, group in enumerate(groups):
        start, end = group[0].start, group[-1].end
        end = max(end, start + min_duration)  # short cues stay up long enough to read...
        if index + 1 < len(groups):
            end = min(end, groups[index + 1][0].start)  # ...but never overlap the next one
        end = max(end, group[-1].end)
        cues.append((start, end, wrap_cue(" ".join(w.text for w in group), max_line)))
    return cues


def srt(words: Sequence[Word], **options) -> str:
    blocks = [
        f"{number}\n{srt_time(start)} --> {srt_time(end)}\n" + "\n".join(lines)
        for number, (start, end, lines) in enumerate(srt_cues(words, **options), start=1)
    ]
    return "\n\n".join(blocks) + "\n"


CAPTION_FONT = DISPLAY_FONT.parent / "Lato-Bold.ttf"  # SIL Open Font License, see OFL-Lato.txt
CAPTION_FONT_NAME = "Lato"


@dataclass(frozen=True)
class LongCaptionStyle:
    """Burned-in captions for long videos: a short phrase at a time near the bottom, the spoken
    word in gold. Many viewers watch without sound, and following the words keeps people watching."""

    font_size: int = 58
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFD447"
    outline_color: str = "#000000"
    outline: float = 3.5
    shadow: float = 1.5
    margin_bottom: int = 74
    max_words: int = 7
    max_width: int = 1500
    pause_break: float = 0.45
    hold: float = 0.35
    uppercase: bool = False


def _blocked(start: float, end: float, windows: Sequence[tuple[float, float]]) -> bool:
    return any(start < w_end and end > w_start for w_start, w_end in windows)


def long_captions_events(
    words: Sequence[Word],
    style: LongCaptionStyle = LongCaptionStyle(),
    hidden: Sequence[tuple[float, float]] = (),
    font_path: Path = CAPTION_FONT,
) -> list[str]:
    """Dialogue lines for long-video captions. Words spoken while a quote or chapter card is on
    screen (`hidden` windows) get no caption, since the card already shows the words."""
    meter = TextMeter(font_path, style.font_size, outline=style.outline)
    short_style = ShortCaptionStyle(max_words=style.max_words, pause_break=style.pause_break, hold=style.hold,
                                    uppercase=style.uppercase)
    pages = short_pages([w for w in words if not w.quote], short_style, meter, style.max_width)
    highlight, normal = ass_color(style.highlight_color, None), ass_color(style.text_color, None)
    lines = []
    for index, page in enumerate(pages):
        last = page[-1][0]
        page_end = last.end + style.hold
        if index + 1 < len(pages):
            page_end = min(page_end, pages[index + 1][0][0].start)
        page_end = max(page_end, last.end)
        for k, (word, _) in enumerate(page):
            start = word.start
            end = page[k + 1][0].start if k + 1 < len(page) else page_end
            if round(end * 100) <= round(start * 100) or _blocked(start, end, hidden):
                continue
            parts = [f"{{\\c{highlight if j == k else normal}}}{_ass_escape(text)}" for j, (_, text) in enumerate(page)]
            lines.append(f"Dialogue: 2,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{' '.join(parts)}")
    return lines


def long_caption_style_line(style: LongCaptionStyle = LongCaptionStyle(), font_name: str = CAPTION_FONT_NAME) -> str:
    return (
        f"Style: Caption,{font_name},{style.font_size},{ass_color(style.text_color)},{ass_color(style.highlight_color)},"
        f"{ass_color(style.outline_color)},{ass_color('#000000', 0x60)},-1,0,0,0,100,100,0,0,1,"
        f"{style.outline:g},{style.shadow:g},2,160,160,{style.margin_bottom},1"
    )