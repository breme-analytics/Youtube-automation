"""What the bot has made and posted: state/videos.json, committed back to the repository after
every run, so any machine (or the next GitHub Actions run) knows where things stand.

    made -> released (stored; waiting for the owner to post it)   -> posted -> cleaned
         -> scheduled (stored; uploaded, waiting for publish time) -> posted -> cleaned
    released / scheduled -> discarded (the owner closed its issue as "not planned")
    made -> failed (the run stopped; the chapter is tried again)
    local: made on a computer and posted by hand from there; recorded so its chapter isn't made again

A video is *stored* while its copy (a GitHub release) exists: from delivery until cleanup deletes it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from owd.config import ROOT

STATE_FILE = ROOT / "state" / "videos.json"
STATUSES = ("made", "released", "scheduled", "posted", "cleaned", "discarded", "failed", "local")
WAITING = ("released", "scheduled")  # stored and not yet posted


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class VideoRecord:
    slug: str
    title: str
    book: str
    chapter: int
    storyboard: str
    status: str = "made"
    made_at: str = field(default_factory=now_iso)
    release_tag: str = ""  # GitHub release holding the stored copy
    stored_at: str = ""  # when the whole copy was stored
    stored_bytes: int = 0
    issue: int = 0  # GitHub issue that tells the owner about this video
    youtube_id: str = ""
    publish_at: str = ""  # when YouTube makes it public (UTC, ISO 8601)
    posted_at: str = ""
    cleaned_at: str = ""  # when the stored copy was deleted
    notes: list[str] = field(default_factory=list)

    @property
    def stored(self) -> bool:
        """True while a copy (or part of one) is in the cloud."""
        return bool(self.release_tag) and not self.cleaned_at

    @property
    def waiting(self) -> bool:
        """Stored and not posted yet: the owner (or YouTube's schedule) still needs this copy."""
        return self.stored and self.status in WAITING


@dataclass
class State:
    videos: list[VideoRecord] = field(default_factory=list)

    def find(self, slug: str) -> VideoRecord | None:
        return next((video for video in self.videos if video.slug == slug), None)

    def used_chapters(self, book: str) -> set[int]:
        return {v.chapter for v in self.videos if v.book == book and v.status != "failed"}

    def stored(self) -> list[VideoRecord]:
        return [video for video in self.videos if video.stored]


_FIELDS = {f.name for f in fields(VideoRecord)}


def load_state(path: Path = STATE_FILE) -> State:
    if not path.is_file():
        return State()
    data = json.loads(path.read_text(encoding="utf-8"))
    # Unknown keys (from an older or newer version of the bot) are ignored rather than fatal.
    return State([VideoRecord(**{k: v for k, v in video.items() if k in _FIELDS}) for video in data.get("videos", [])])


def save_state(state: State, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"videos": [asdict(video) for video in state.videos]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


BOOK_ORDERS = ("balanced", "in order")


def _numbers(value: int | Sequence[int]) -> list[int]:
    return list(range(1, value + 1)) if isinstance(value, int) else list(value)


def next_chapter(state: State, books: list[dict], chapter_numbers: dict[str, int | Sequence[int]],
                 order: str = "in order") -> tuple[str, int] | None:
    """The next (book id, chapter number) to make, or None when every chapter has a video.

    `chapter_numbers` gives each book's chapter count or its list of chapter numbers. Order:
    "in order": finish the first book in channel.toml, then the next;
    "balanced": the book with the fewest videos so far goes next (ties in channel.toml order),
    so the books take turns."""
    if order not in BOOK_ORDERS:
        raise ValueError(f'book_order must be one of {", ".join(BOOK_ORDERS)}, not {order!r}')
    open_books = []
    for position, book in enumerate(books):
        used = state.used_chapters(book["id"])
        unused = [n for n in _numbers(chapter_numbers.get(book["id"], 0)) if n not in used]
        if unused:
            open_books.append((len(used) if order == "balanced" else 0, position, book["id"], unused[0]))
    if not open_books:
        return None
    _, _, book_id, number = min(open_books)
    return book_id, number


def chapters_left(state: State, books: list[dict], chapter_numbers: dict[str, int | Sequence[int]]) -> int:
    """How many chapters, across all books, have no video yet."""
    return sum(len(set(_numbers(chapter_numbers.get(book["id"], 0))) - state.used_chapters(book["id"]))
               for book in books)
