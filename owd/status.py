"""state/status.json: where things stand, written by the bot after every run and committed back. The
control panel (panel/) shows it; it's also readable on GitHub as it is.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from owd.config import ROOT
from owd.state import State, next_chapter
from owd.storage import StoragePolicy

STATUS_FILE = ROOT / "state" / "status.json"
RUN_TIME_UTC = (3, 15)  # produce.yml runs daily at 03:15 UTC; keep in step with its cron line


def book_status(settings: dict, state: State) -> tuple[list[dict], dict | None]:
    """Each book's progress, and the chapter the next video will use (None when none are left)."""
    from owd.books import book_chapters

    books = settings.get("books", [])
    rows, numbers, titles = [], {}, {}
    for book in books:
        try:
            found = book_chapters(book)
        except Exception as error:  # a broken book shouldn't hide everything else
            rows.append({"id": book["id"], "cite": book.get("cite", book["id"]), "error": str(error)[:200]})
            continue
        numbers[book["id"]] = [chapter.number for chapter in found]
        titles[book["id"]] = {chapter.number: chapter.title for chapter in found}
        made = state.used_chapters(book["id"]) & set(numbers[book["id"]])
        rows.append({"id": book["id"], "cite": book.get("cite", book["id"]), "chapters": len(found),
                     "made": len(made), "left": len(found) - len(made)})
    order = settings.get("schedule", {}).get("book_order", "balanced")
    pick = next_chapter(state, [b for b in books if b["id"] in numbers], numbers, order)
    upcoming = None
    if pick:
        cite = next(b.get("cite", b["id"]) for b in books if b["id"] == pick[0])
        upcoming = {"book": pick[0], "cite": cite, "chapter": pick[1], "title": titles[pick[0]][pick[1]].title()}
    return rows, upcoming


def build_status(settings: dict, state: State, now: datetime | None = None, *, minutes=None,
                 minutes_budget: int = 0, needs: list[dict] | None = None) -> dict:
    from owd.schedule import make_days

    now = now or datetime.now(timezone.utc)
    policy = StoragePolicy.from_settings(settings)
    schedule = settings.get("schedule", {})
    books, upcoming = book_status(settings, state)
    videos = []
    for record in state.videos:
        if record.status in ("failed",) and not record.stored:
            continue
        due = policy.delete_on(record)
        videos.append({"slug": record.slug, "title": record.title, "status": record.status, "book": record.book,
                       "chapter": record.chapter, "made_at": record.made_at, "issue": record.issue,
                       "release": record.release_tag if record.stored else "", "youtube_id": record.youtube_id,
                       "publish_at": record.publish_at, "posted_at": record.posted_at,
                       "delete_on": due.isoformat() if due and record.stored else ""})
    status = {
        "updated": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": schedule.get("mode", "review"),
        "schedule": {"make_days": make_days(settings), "timezone": schedule.get("timezone", "UTC"),
                     "run_time_utc": "%02d:%02d" % RUN_TIME_UTC, "publish_days": schedule.get("publish_days", []),
                     "publish_time": schedule.get("publish_time", ""), "book_order": schedule.get("book_order", "balanced")},
        "storage": {"stored": len(state.stored()), "max_videos": policy.max_videos,
                    "keep_days_after_posting": policy.keep_days_after_posting},
        "books": books,
        "chapters_left": sum(row.get("left", 0) for row in books),
        "next": upcoming,
        "videos": videos[-30:],
        "needs": needs or [],
    }
    if minutes is not None:
        status["minutes"] = {"month": minutes.month, "used": minutes.used, "budget": minutes_budget,
                             "per_video": minutes.per_video, "measured": bool(minutes.video_runs),
                             "by_workflow": minutes.by_workflow}
    return status


def save_status(status: dict, path: Path | None = None) -> None:
    path = path or STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
