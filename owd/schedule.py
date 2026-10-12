"""When a video goes public: the next free slot on the channel's posting days, in its timezone."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MIN_LEAD = timedelta(hours=2)  # YouTube needs time to process the upload before it goes public


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
