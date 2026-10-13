"""Adding a public-domain book by its Project Gutenberg number (`python -m owd add-book 14209`, the
add-book workflow, or the control panel's "Add a book").

The file comes from Project Gutenberg's official mirror (gutenberg.pglaf.org): Gutenberg's own site is for
people only and blocks automated downloads. The book is added only if its chapters can be found (see
owd/books.py); the file is saved unchanged in sources/, and a [[books]] entry is added to channel.toml
after the last one, keeping every comment in the file.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import httpx

from owd.books import Chapter, chapters

MIRROR = "https://gutenberg.pglaf.org/cache/epub/{n}/pg{n}.txt"
USER_AGENT = "old-wisdom-decoded (adds one public-domain book on its owner's request)"
MAX_BYTES = 8 * 1024 * 1024


class BookError(ValueError):
    pass


@dataclass(frozen=True)
class NewBook:
    id: str
    title: str
    author: str
    cite: str
    gutenberg: int
    file: str  # relative to the project root
    chapters: list[Chapter]
    only: list[str]


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{name}:[ \t]*(.+)$", text, re.M)
    return " ".join(match.group(1).split()) if match else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50].rstrip("-") or "book"


def download(number: int, http: httpx.Client | None = None) -> str:
    http = http or httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        response = http.get(MIRROR.format(n=number))
    except httpx.HTTPError as error:
        raise BookError(f"Couldn't reach Project Gutenberg's mirror ({type(error).__name__}); try again later") from None
    if response.status_code == 404:
        raise BookError(f"Project Gutenberg has no plain-text book number {number}")
    if response.status_code != 200:
        raise BookError(f"Project Gutenberg's mirror answered {response.status_code}; try again later")
    if len(response.content) > MAX_BYTES:
        raise BookError(f"Book {number} is over {MAX_BYTES // 1024**2} MB, which is far too long for this channel")
    text = response.content.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if "*** START OF" not in text:
        raise BookError(f"Book {number} doesn't look like a Project Gutenberg text")
    return text


def prepare(number: int, text: str, root: Path, *, only: list[str] | None = None, cite: str = "",
            year: str = "") -> NewBook:
    """Check the book and work out its entry. Raises BookError with the reason if it can't be used."""
    title, author = _field(text, "Title"), _field(text, "Author")
    if not title:
        raise BookError(f"Book {number} has no title in its header")
    language = _field(text, "Language")
    if language and language.lower() != "english":
        raise BookError(f"Book {number} is in {language}; the channel is in English")
    book_id = slug(title)
    path = root / "sources" / f"{book_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    trial = path.with_suffix(".checking.txt")
    trial.write_text(text, encoding="utf-8")
    try:
        found = chapters(trial, only or None)
    except ValueError as error:
        raise BookError(f"The chapters of book {number} couldn't be found ({error}). Ask the developer to adapt it, "
                        "or give the chapter titles to use.") from None
    finally:
        trial.unlink(missing_ok=True)
    if len(found) < 1:
        raise BookError(f"Book {number} has no chapters the bot can use")
    short = [c.title for c in found if c.words < 300]
    if short:
        raise BookError(f"These chapters are too short for a video (under 300 words): {', '.join(short)}. "
                        "Choose the chapters to use.")
    cite = cite or f"{author or 'Unknown author'}, {title}" + (f" ({year})" if year else "")
    return NewBook(book_id, title, author, cite, number, f"sources/{book_id}.txt", found, list(only or []))


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def entry(book: NewBook) -> str:
    lines = ["[[books]]", f"id = {_toml_string(book.id)}", f"file = {_toml_string(book.file)}",
             f"cite = {_toml_string(book.cite)}", f"author = {_toml_string(book.author or book.cite.split(',')[0])}",
             f"gutenberg = {book.gutenberg}"]
    if book.only:
        lines.append("chapters = [" + ", ".join(_toml_string(t) for t in book.only) + "]")
    return "\n".join(lines) + "\n"


def add_to_channel(channel_text: str, book: NewBook) -> str:
    """channel.toml's text with the book's [[books]] entry after the last one (comments kept)."""
    settings = tomllib.loads(channel_text)
    if any(b.get("id") == book.id for b in settings.get("books", [])):
        raise BookError(f"{book.title} ({book.id}) is already in channel.toml")
    if any(b.get("gutenberg") == book.gutenberg for b in settings.get("books", [])):
        raise BookError(f"Project Gutenberg book {book.gutenberg} is already in channel.toml")
    lines = channel_text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == "[[books]]"]
    if not starts:
        updated = channel_text.rstrip("\n") + "\n\n" + entry(book)
    else:
        end = next((i for i in range(starts[-1] + 1, len(lines)) if lines[i].startswith("[")), len(lines))
        while end > starts[-1] + 1 and not lines[end - 1].strip():
            end -= 1  # insert right after the last entry's last line
        updated = "\n".join(lines[:end] + [""] + entry(book).rstrip("\n").split("\n") + lines[end:])
    tomllib.loads(updated)  # never write a broken settings file
    return updated


def add_book(number: int, root: Path, *, only: list[str] | None = None, cite: str = "", year: str = "",
             http: httpx.Client | None = None) -> NewBook:
    channel = root / "channel.toml"
    text = download(number, http)
    book = prepare(number, text, root, only=only, cite=cite, year=year)
    updated = add_to_channel(channel.read_text(encoding="utf-8"), book)
    (root / book.file).write_text(text, encoding="utf-8")
    channel.write_text(updated, encoding="utf-8")
    return book
