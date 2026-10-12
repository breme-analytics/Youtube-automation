"""Quote checking: every quote in a storyboard must appear, word for word, in one of its sources.

Matching ignores case, punctuation, line breaks and Project Gutenberg's _italics_ marks, so
"Man's mind may be likened to a garden" matches "MAN'S mind may be likened to a garden," in the
book. It never ignores words: a missing, changed or reordered word fails.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from owd.storyboard import Storyboard
from owd.tts import _quote_text

_PARAGRAPH = re.compile(r"\n\s*\n")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("_", " ")
    text = re.sub(r"[-–—]+", " ", text)
    text = re.sub(r"'", "", text)  # man's -> mans, on both sides
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {' '.join(text.split())} "


@lru_cache(maxsize=32)
def _source_text(path: str) -> str:
    return normalize(Path(path).read_text(encoding="utf-8"))


def quotes_in(storyboard: Storyboard) -> list[str]:
    quotes = []
    for scene in storyboard.scenes:
        for paragraph in _PARAGRAPH.split(scene.text.strip()):
            quoted = _quote_text(paragraph)
            if quoted:
                quotes.append(quoted)
    return quotes


def check_quotes(storyboard: Storyboard) -> list[str]:
    """Problems found: quotes that no source contains, or quotes with no sources at all."""
    quotes = quotes_in(storyboard)
    if quotes and not storyboard.sources:
        return ["the storyboard quotes a book but lists no [[sources]] to check against"]
    texts = [_source_text(str(source.file)) for source in storyboard.sources]
    problems = []
    for quote in quotes:
        needle = normalize(quote)
        if needle.strip() and not any(needle in text for text in texts):
            suggestions = [repair_quote(quote, Path(source.file).read_text(encoding="utf-8")) for source in storyboard.sources]
            hint = next((f"; the book says: {s!r}" for s in suggestions if s), "")
            problems.append(f"not found word for word in any source: {quote!r}{hint}")
    return problems


def in_source(quote: str, source_text: str) -> bool:
    needle = normalize(quote)
    return bool(needle.strip()) and needle in normalize(source_text)


def _display(words: list[str]) -> str:
    """Source words as a quote should show them: Gutenberg's _italic_ marks removed and its
    all-capitals chapter openings ("MAN'S mind") in normal case."""
    shown = []
    for index, word in enumerate(words):
        word = word.replace("_", "")
        letters = [ch for ch in word if ch.isalpha()]
        if len(letters) > 1 and all(ch.isupper() for ch in letters) and word.upper() != "I":
            word = word.capitalize() if index == 0 or shown[-1].endswith((".", "!", "?")) else word.lower()
        shown.append(word)
    return " ".join(shown)


def repair_quote(quote: str, source_text: str, min_ratio: float = 0.85) -> str | None:
    """`quote` as the source actually words it, if the source has a passage that is clearly the
    same (at least `min_ratio` of the words match in order), else None. Fixes the small slips
    language models make when copying ("compared" for "likened", a dropped "the")."""
    import difflib

    target = normalize(quote).split()
    if not target:
        return None
    raw_words = source_text.replace("\r\n", "\n").split()
    keys = [normalize(word).strip() for word in raw_words]
    size = len(target)
    best: tuple[float, int, int] | None = None
    anchors = set(target)
    for start in range(len(keys)):
        if keys[start] not in anchors:
            continue  # a quote's first words are almost always in it; skip windows that can't match
        for length in (size - 2, size - 1, size, size + 1, size + 2):
            if length < 1 or start + length > len(keys):
                continue
            window = [k for k in keys[start : start + length] if k]
            ratio = difflib.SequenceMatcher(None, target, window, autojunk=False).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, start, length)
    if best is None or best[0] < min_ratio:
        return None
    _, start, length = best
    text = _display(raw_words[start : start + length])
    return text.strip(" ,;:—-")
