"""Public-domain books as Project Gutenberg plain text, split into chapters.

The text between Gutenberg's START and END markers is the book. Its chapters are the entries of its
contents list (a line "CONTENTS", "Contents" or "Table of Contents"), in one of two styles:
- unnumbered titles in capitals, one per line ("THOUGHT AND CHARACTER"), as in As a Man Thinketh;
- titles numbered with Roman numerals ("II. SELF-RELIANCE", "I.  The Hermetic Philosophy"). The numerals
  are the chapter numbers; sub-entries numbered 1., 2., ... are sections, not chapters.
A chapter starts at its heading in the body (the same words in any case, perhaps with "THE " in front,
on a line of its own) and ends at the next heading of any other entry. A numeral line just above a
heading ("II.", "CHAPTER II") belongs to the chapter it introduces.

A book in channel.toml may list `chapters = ["SELF-RELIANCE", ...]`: only those become videos. The rest
of the contents still mark where chapters end. Unnumbered chapters are then numbered 1, 2, ... in the
order they're listed.

Two Gutenberg habits are cleaned away, for chapters and the quote check alike: footnote markers ("[12]")
and section numbers at the start of a paragraph ("IV. Of my mother I learned ..."), which nobody reads aloud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M)
_END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M)
_CONTENTS = re.compile(r"^[ \t]*(?:TABLE[ \t]+OF[ \t]+)?CONTENTS\.?[ \t]*$", re.M | re.I)
_ROMAN = r"(?=[MDCLXVI])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
_NUMBERED_ENTRY = re.compile(rf"^(?:CHAPTER[ \t]+)?({_ROMAN})\.[ \t]+(\S.*)$", re.I)
_SECTION_ENTRY = re.compile(r"^\d+\.[ \t]")
_NUMERAL_LINE = re.compile(rf"^[ \t]*(?:CHAPTER[ \t]+)?{_ROMAN}\.?[ \t]*$", re.I)
_SECTION_NUMBER = re.compile(rf"(\A|\n[ \t]*\n)[ \t]*{_ROMAN}\.[ \t]+(?=[A-Z])")
_FOOTNOTE_MARK = re.compile(r"\[\d{1,3}\]")


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


def clean_text(text: str) -> str:
    """The book's words as the bot uses them: no footnote markers, no paragraph-opening section numbers."""
    return _FOOTNOTE_MARK.sub("", _SECTION_NUMBER.sub(r"\1", text))


def book_text(path: Path | str) -> str:
    raw = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    start, end = _START.search(raw), _END.search(raw)
    return raw[start.end() if start else 0 : end.start() if end else len(raw)].strip()


def roman_value(numeral: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    digits = [values[ch] for ch in numeral.upper()]
    return sum(-d if i + 1 < len(digits) and d < digits[i + 1] else d for i, d in enumerate(digits))


def _key(line: str) -> str:
    """A title or heading for comparing: capitals and digits only ("Saints, Sages; ..." = "SAINTS SAGES ...")."""
    return " ".join(re.sub(r"[^A-Z0-9 ]", "", line.upper().replace("-", "").replace("\t", " ")).split())


def _contents(text: str) -> tuple[list[tuple[int | None, str]], int]:
    """The contents entries as (Roman number or None, title), and where the list ends."""
    match = _CONTENTS.search(text)
    if not match:
        raise ValueError("No CONTENTS heading found")
    entries: list[tuple[int | None, str]] = []
    numbered: bool | None = None
    blanks, end, offset = 0, match.end(), match.end()
    for line in text[match.end():].split("\n")[1:]:
        offset += len(line) + 1
        stripped = line.strip()
        if not stripped:
            blanks += 1
            if entries and blanks >= 2:
                break
            continue
        blanks = 0
        if numbered and _SECTION_ENTRY.match(stripped):
            end = offset
            continue  # "1.  The Principle of Mentalism": a section inside chapter II
        entry = _NUMBERED_ENTRY.match(stripped)
        if entry and numbered is not False:
            numbered = True
            entries.append((roman_value(entry.group(1)), " ".join(entry.group(2).split())))
        elif not numbered and stripped.upper() == stripped and re.search(r"[A-Z]", stripped):
            numbered = False
            entries.append((None, " ".join(stripped.split())))
        else:
            break  # the end of the list ("INTRODUCTION", "Next Volume", the first paragraph)
        end = offset
    if not entries:
        raise ValueError("The CONTENTS list is empty")
    return entries, end


def _headings(text: str, start: int, keys: set[str]) -> list[tuple[int, int, str]]:
    """Lines after `start` that are a contents title on their own: (line start, line end, title key).
    A heading starts a paragraph: a blank line or a numeral line ("II.") comes before it."""
    found = []
    lines = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"^.*$", text[start:], re.M)]
    for index, (begin, finish, line) in enumerate(lines):
        key = _key(line)
        title = key if key in keys else key[4:] if key.startswith("THE ") and key[4:] in keys else None
        if not title:
            continue
        before = lines[index - 1][2] if index else ""
        if before.strip() == "" or _NUMERAL_LINE.match(before):
            found.append((start + begin, start + finish, title))
    return found


def chapters(path: Path | str, only: Sequence[str] | None = None) -> list[Chapter]:
    """The book's chapters, in order. With `only`, just the chapters with those titles."""
    text = book_text(path)
    entries, contents_end = _contents(text)
    titles = {_key(title): (number, title) for number, title in entries}
    wanted = [_key(t) for t in only] if only else list(titles)
    missing = [t for t in (only or []) if _key(t) not in titles]
    if missing:
        raise ValueError(f"Not in the book's contents: {', '.join(missing)}. Contents: "
                         + "; ".join(title for _, title in entries))
    headings = _headings(text, contents_end, set(titles))
    result, cursor = [], contents_end
    for position, key in enumerate(wanted, start=1):
        number, title = titles[key]
        heading = next((h for h in headings if h[2] == key and h[0] >= cursor), None)
        if heading is None:
            raise ValueError(f"Chapter heading not found in the text: {title!r}")
        following = next((h for h in headings if h[0] > heading[1] and h[2] != key), None)
        stop = _above_numeral(text, heading[1], following[0] if following else len(text))
        lines = text[heading[1]:stop].split("\n")
        kept = [line for i, line in enumerate(lines)  # drop the title repeated as a heading (after an epigraph)
                if not (_key(line) in (key, f"THE {key}") and _blank(lines, i - 1) and _blank(lines, i + 1))]
        body = re.sub(r"\n{3,}", "\n\n", clean_text("\n".join(kept).strip())).strip()
        result.append(Chapter(number if number is not None else position, title, body))
        cursor = heading[1]
    return result


def _blank(lines: list[str], index: int) -> bool:
    return not 0 <= index < len(lines) or not lines[index].strip()


def _above_numeral(text: str, floor: int, stop: int) -> int:
    """Move a chapter's end up past the next chapter's numeral line ("III.") and the blank lines around it."""
    head = text[floor:stop].rstrip()
    last_line = head.rsplit("\n", 1)[-1]
    if _NUMERAL_LINE.match(last_line):
        return floor + len(head) - len(last_line)
    return stop


def find_chapter(path: Path | str, wanted: str, only: Sequence[str] | None = None) -> Chapter:
    """A chapter by number ("2") or by (part of) its title, ignoring case."""
    found = chapters(path, only)
    if wanted.strip().isdigit():
        match = next((chapter for chapter in found if chapter.number == int(wanted)), None)
        if match:
            return match
    key = wanted.strip().lower()
    matches = [chapter for chapter in found if key in chapter.title.lower()]
    if len(matches) != 1:
        options = ", ".join(f"{c.number}. {c.title}" for c in found)
        raise ValueError(f"Chapter {wanted!r} matched {len(matches)} chapters. Chapters: {options}")
    return matches[0]


# A book as channel.toml lists it ([[books]] with id, file, cite, author and, optionally, chapters)


def book_chapters(book: dict, root: Path | None = None) -> list[Chapter]:
    from owd.config import ROOT

    return chapters((root or ROOT) / book["file"], book.get("chapters") or None)


def book_chapter(book: dict, wanted: str, root: Path | None = None) -> Chapter:
    from owd.config import ROOT

    return find_chapter((root or ROOT) / book["file"], wanted, book.get("chapters") or None)
