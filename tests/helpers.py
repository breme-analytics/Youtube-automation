from __future__ import annotations

import pytest

from owd.config import tool
from owd.words import Word


def ffmpeg_ready() -> bool:
    try:
        tool("ffmpeg")
        tool("ffprobe")
    except FileNotFoundError:
        return False
    from owd.ffmpeg import has_filter

    return all(has_filter(name) for name in ("subtitles", "zoompan", "xfade", "loudnorm"))


needs_ffmpeg = pytest.mark.skipif(
    not ffmpeg_ready(), reason="needs an ffmpeg with libass (macOS: brew install ffmpeg-full)"
)


def words_at(text: str, start: float = 0.0, step: float = 0.4, gap: float = 0.05) -> list[Word]:
    """Evenly spaced words: each lasts `step - gap` seconds, then a `gap` of silence."""
    words, clock = [], start
    for token in text.split():
        words.append(Word(token, round(clock, 3), round(clock + step - gap, 3)))
        clock += step
    return words
