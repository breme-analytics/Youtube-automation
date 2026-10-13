"""When a video goes public: the next free slot on the channel's posting days, in its timezone."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MIN_LEAD = timedelta(hours=2)  # YouTube needs time to process the upload before it goes public
DEFAULT_MAKE_DAYS = ("Mon", "Thu")


def make_days(settings: dict) -> list[str]:
    """The days the bot makes a video (channel.toml [schedule] make_days), as "Mon", "Tue", ..."""
    days = settings.get("schedule", {}).get("make_days", list(DEFAULT_MAKE_DAYS))
    result = []
    for day in days:
        short = str(day).strip()[:3].title()
        if short not in DAYS:
            raise ValueError(f"schedule.make_days: {day!r} isn't a day (use Mon, Tue, Wed, Thu, Fri, Sat or Sun)")
        if short not in result:
            result.append(short)
    return sorted(result, key=DAYS.index)


def is_make_day(settings: dict, now: datetime) -> bool:
    """Whether `now` falls on a video day in the channel's timezone."""
    zone = ZoneInfo(settings.get("schedule", {}).get("timezone", "UTC"))
    return DAYS[now.astimezone(zone).weekday()] in make_days(settings)


def next_slot(
    now: datetime,
    days: Iterable[str],
    at: str,
    zone: str,
    taken: Iterable[datetime] = (),
    lead: timedelta = MIN_LEAD,
) -> datetime:
    """The first posting slot at least `lead` from `now` that no other video holds, in UTC."""
    tz = ZoneInfo(zone)
    wanted = {DAYS.index(day[:3].title()) for day in days}
    if not wanted:
        raise ValueError("schedule.publish_days is empty")
    hour, minute = (int(part) for part in at.split(":"))
    busy = {t.astimezone(timezone.utc).replace(second=0, microsecond=0) for t in taken}
    local = now.astimezone(tz)
    for offset in range(0, 400):
        day = (local + timedelta(days=offset)).date()
        if day.weekday() not in wanted:
            continue
        slot = datetime.combine(day, time(hour, minute), tz).astimezone(timezone.utc)
        if slot - now >= lead and slot not in busy:
            return slot
    raise ValueError("No free posting slot within a year")
