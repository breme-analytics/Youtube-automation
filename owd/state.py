"""What the bot has made and posted: state/videos.json, committed back to the repository after
every run, so any machine (or the next GitHub Actions run) knows where things stand.

    made -> released (review copy on GitHub) -> scheduled / posted (on YouTube) -> cleaned
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from owd.config import ROOT

STATE_FILE = ROOT / "state" / "videos.json"
STATUSES = ("made", "released", "scheduled", "posted", "cleaned", "failed")


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
    release_tag: str = ""  # GitHub release holding the review copy
    issue: int = 0  # GitHub issue asking the owner to review and post
    youtube_id: str = ""
    publish_at: str = ""  # when YouTube makes it public (UTC, ISO 8601)
    posted_at: str = ""
    cleaned_at: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class State:
    videos: list[VideoRecord] = field(default_factory=list)

    def find(self, slug: str) -> VideoRecord | None:
        return next((video for video in self.videos if video.slug == slug), None)

    def used_chapters(self, book: str) -> set[int]:
        return {v.chapter for v in self.videos if v.book == book and v.status != "failed"}


def load_state(path: Path = STATE_FILE) -> State:
    if not path.is_file():
        return State()
    data = json.loads(path.read_text(encoding="utf-8"))
    return State([VideoRecord(**video) for video in data.get("videos", [])])


def save_state(state: State, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"videos": [asdict(video) for video in state.videos]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def next_chapter(state: State, books: list[dict], chapter_counts: dict[str, int]) -> tuple[str, int] | None:
    """The first (book id, chapter number) not made yet, going through the books in channel.toml
    order. None when every chapter of every book has a video."""
    for book in books:
        used = state.used_chapters(book["id"])
        for number in range(1, chapter_counts.get(book["id"], 0) + 1):
            if number not in used:
                return book["id"], number
    return None
