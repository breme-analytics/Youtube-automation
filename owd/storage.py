"""The storage rules: every video is stored in the cloud, and nothing piles up.

Where: a GitHub release in the bot's own repository (see owd/github.py). Free, with no limit on the
total size or on downloads; each file must be under 2 GiB (about 40 minutes of video at the bot's
quality, roughly 53 MB a minute). It needs no account or key beyond the workflow's own token.

Rules (channel.toml [storage]):
1. Every video is stored before it is posted, in both modes. If it can't be stored, the run fails.
2. A posted video's copy is kept `keep_days_after_posting` days (in case something went wrong on
   YouTube), then deleted.
3. A copy the owner discards (closes its issue as "not planned"), or the remains of a failed run,
   is deleted at the next cleanup.
4. Never more than `max_videos` stored at once. When a new video needs room, copies of posted videos
   go first (oldest first: they're safe on YouTube). If every stored video is still waiting to be
   posted, the bot makes no new video until one is posted or discarded.

Unposted videos are never deleted for age: the cap already bounds the storage, and deleting them
would throw away finished work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from owd.state import State, VideoRecord

FILE_LIMIT = 2 * 1024**3  # GitHub: each release file must be under 2 GiB


@dataclass(frozen=True)
class StoragePolicy:
    keep_days_after_posting: int = 7
    max_videos: int = 4

    @classmethod
    def from_settings(cls, settings: dict) -> "StoragePolicy":
        section = settings.get("storage", {})
        legacy = settings.get("schedule", {}).get("keep_days")  # where the setting used to live
        keep = int(section.get("keep_days_after_posting", legacy if legacy is not None else cls.keep_days_after_posting))
        cap = int(section.get("max_videos", cls.max_videos))
        if keep < 0:
            raise ValueError("storage.keep_days_after_posting can't be negative")
        if cap < 1:
            raise ValueError("storage.max_videos must be at least 1")
        return cls(keep, cap)

    def delete_on(self, record: VideoRecord) -> datetime | None:
        """When a posted video's copy is due for deletion (None if it isn't posted)."""
        if not record.posted_at:
            return None
        return datetime.fromisoformat(record.posted_at) + timedelta(days=self.keep_days_after_posting)


def expired(state: State, policy: StoragePolicy, now: datetime) -> list[VideoRecord]:
    """Stored copies that are due for deletion now (rules 2 and 3)."""
    due = []
    for record in state.stored():
        if record.status in ("discarded", "failed"):
            due.append(record)
        elif record.status in ("posted", "cleaned") and record.posted_at and policy.delete_on(record) <= now:
            due.append(record)
    return due


def make_room(state: State, policy: StoragePolicy, new: int = 1) -> tuple[list[VideoRecord], bool]:
    """Rule 4: the posted copies to delete early so that `new` more videos fit, oldest first, and
    whether there is room once they're gone."""
    stored = state.stored()
    excess = len(stored) + new - policy.max_videos
    if excess <= 0:
        return [], True
    posted = sorted((r for r in stored if not r.waiting), key=lambda r: r.posted_at or r.made_at)
    early = posted[:excess]
    return early, len(stored) - len(early) + new <= policy.max_videos


def summary(state: State, policy: StoragePolicy) -> list[str]:
    """One line per stored video, for the CLI and the logs."""
    lines = []
    for record in state.stored():
        size = f"{record.stored_bytes / 1e6:,.0f} MB" if record.stored_bytes else "size unknown"
        due = policy.delete_on(record)
        when = (f"deleted on {due:%d %b %Y}" if due else
                "kept until it's posted or discarded" if record.waiting else "deleted at the next cleanup")
        lines.append(f"{record.slug}: {record.status}, {size}, {when}")
    return lines
