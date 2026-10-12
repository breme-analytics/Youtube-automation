"""Chapters of public-domain books in Project Gutenberg's plain-text format.

The text between Gutenberg's START and END markers is the book. Chapter headings are the
upper-case lines listed after its CONTENTS heading; each chapter runs from its heading (after the
contents list) to the next heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M)
_END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M)


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


def book_text(path: Path | str) -> str:
    raw = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    start, end = _START.search(raw), _END.search(raw)
    return raw[start.end() if start else 0 : end.start() if end else len(raw)].strip()


def _contents(text: str) -> list[str]:
    """The upper-case titles after the CONTENTS heading. Titles may be separated by single blank
    lines; the list ends at two blank lines in a row or at a line that isn't a heading."""
    match = re.search(r"^\s*CONTENTS\s*$", text, re.M)
    if not match:
        raise ValueError("No CONTENTS heading found")
    titles: list[str] = []
    blanks = 0
    for line in text[match.end() :].splitlines():
        line = line.strip()
        if not line:
            blanks += 1
            if titles and blanks >= 2:
                break
            continue
        blanks = 0
        if line.upper() != line or not re.search(r"[A-Z]", line):
            break
        titles.append(" ".join(line.split()))
    if not titles:
        raise ValueError("The CONTENTS list is empty")
    return titles


def chapters(path: Path | str) -> list[Chapter]:
    text = book_text(path)
    titles = _contents(text)
    contents_end = text.find(titles[-1]) + len(titles[-1])
    positions = []
    for title in titles:
        pattern = re.compile(r"^\s*" + r"\s+".join(map(re.escape, title.split())) + r"\s*$", re.M)
        found = pattern.search(text, contents_end)
        if not found:
            raise ValueError(f"Chapter heading not found in the text: {title!r}")
        positions.append((found.start(), found.end(), title))
    result = []
    for index, (start, end, title) in enumerate(positions):
        stop = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        body = re.sub(r"\n{3,}", "\n\n", text[end:stop]).strip()
        result.append(Chapter(index + 1, title, body))
    return result


def find_chapter(path: Path | str, wanted: str) -> Chapter:
    """A chapter by number ("2") or by (part of) its title, ignoring case."""
    found = chapters(path)
    if wanted.strip().isdigit():
        number = int(wanted)
        if 1 <= number <= len(found):
            return found[number - 1]
    key = wanted.strip().lower()
    matches = [chapter for chapter in found if key in chapter.title.lower()]
    if len(matches) != 1:
        options = ", ".join(f"{c.number}. {c.title}" for c in found)
        raise ValueError(f"Chapter {wanted!r} matched {len(matches)} chapters. Chapters: {options}")
    return matches[0]
