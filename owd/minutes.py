"""GitHub Actions minutes: what this repository's workflows used this month, and whether the next
video fits the bot's monthly budget (channel.toml [actions] monthly_minutes).

A free account's 2,000 minutes a month are shared by all of its private repositories (here, also the
trading bot). This module can only see this repository's runs, so the budget is this bot's share. GitHub
bills each job rounded up to a whole minute, so the same rounding is used here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_VIDEO_MINUTES = 120  # assumed for a video until real runs have been measured
MAKE_WORKFLOW = "produce"
MIN_VIDEO_RUN = 15  # a produce run shorter than this made no video (a cleanup-only day, or full storage)


def _when(stamp: str | None) -> datetime | None:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None


def job_minutes(job: dict, now: datetime) -> int:
    """A job's billed minutes: its run time rounded up to a whole minute (a running job counts so far)."""
    started = _when(job.get("started_at"))
    if started is None:
        return 0
    finished = _when(job.get("completed_at")) or now
    return max(1, math.ceil((finished - started).total_seconds() / 60)) if finished > started else 0


@dataclass
class Usage:
    month: str  # YYYY-MM (UTC), the month GitHub's free minutes reset on
    used: int = 0
    by_workflow: dict[str, int] = field(default_factory=dict)
    video_runs: list[int] = field(default_factory=list)  # minutes of recent produce runs that made a video

    @property
    def per_video(self) -> int:
        """Expected minutes for the next video: the median of recent video runs, or a cautious default."""
        recent = self.video_runs[:5]
        return round(statistics.median(recent)) if recent else DEFAULT_VIDEO_MINUTES


def month_usage(github, now: datetime | None = None) -> Usage:
    """This month's billed minutes for this repository, from its workflow runs and their jobs."""
    now = now or datetime.now(timezone.utc)
    start = now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = Usage(start.strftime("%Y-%m"))
    for run in github.list_runs(created_since=start.strftime("%Y-%m-%d")):
        minutes = sum(job_minutes(job, now) for job in github.run_jobs(run["id"]))
        name = run.get("name") or run.get("path", "?")
        usage.used += minutes
        usage.by_workflow[name] = usage.by_workflow.get(name, 0) + minutes
        if name == MAKE_WORKFLOW and run.get("status") == "completed" and run.get("conclusion") == "success" \
                and minutes >= MIN_VIDEO_RUN:
            usage.video_runs.append(minutes)
    return usage


def budget(settings: dict) -> int:
    """The bot's monthly share of Actions minutes (0: no limit)."""
    value = int(settings.get("actions", {}).get("monthly_minutes", 0))
    if value < 0:
        raise ValueError("actions.monthly_minutes can't be negative")
    return value


def fits(usage: Usage, limit: int) -> bool:
    """Whether one more video fits this month's budget."""
    return not limit or usage.used + usage.per_video <= limit


def summary(usage: Usage, limit: int) -> str:
    share = f" of this bot's {limit:,}" if limit else ""
    return (f"Actions minutes in {usage.month}: {usage.used:,}{share} used by this repository; "
            f"a video takes about {usage.per_video} ({'measured' if usage.video_runs else 'estimate'}).")
