"""Actions minutes and the monthly budget, video days, state/status.json, adding a book, `owd plan`."""

import json
import tomllib
from datetime import datetime, timezone

import httpx
import pytest

from owd import autopilot, minutes
from owd.addbook import BookError, add_to_channel, download, entry, prepare
from owd.config import ROOT
from owd.schedule import is_make_day, make_days
from owd.state import State, VideoRecord
from owd.status import build_status

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)  # a Thursday, 07:00 in Nairobi


def job(start, end):
    return {"started_at": start, "completed_at": end}


class RunsGitHub:
    """Workflow runs and their jobs, as GitHub's API returns them."""

    def __init__(self, runs):
        self.runs = runs

    def list_runs(self, created_since):
        assert created_since == "2026-10-01"
        return [{k: v for k, v in run.items() if k != "jobs"} for run in self.runs]

    def run_jobs(self, run_id):
        return next(run["jobs"] for run in self.runs if run["id"] == run_id)


def produce_run(run_id, minutes_long, conclusion="success"):
    """A produce run whose one job lasts `minutes_long` minutes and 30 seconds (billed minutes_long + 1)."""
    from datetime import timedelta

    start = datetime(2026, 10, run_id, 3, 0, tzinfo=UTC)
    end = start + timedelta(minutes=minutes_long, seconds=30)
    return {"id": run_id, "name": "produce", "status": "completed", "conclusion": conclusion,
            "jobs": [job(start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z"))]}


def test_jobs_are_billed_in_whole_minutes_and_a_running_job_counts_so_far():
    assert minutes.job_minutes(job("2026-10-01T03:00:00Z", "2026-10-01T03:00:05Z"), NOW) == 1
    assert minutes.job_minutes(job("2026-10-01T03:00:00Z", "2026-10-01T04:30:01Z"), NOW) == 91
    assert minutes.job_minutes(job("2026-10-22T03:58:00Z", None), NOW) == 2
    assert minutes.job_minutes({"started_at": None}, NOW) == 0


def test_month_usage_adds_every_workflow_and_learns_a_videos_length():
    github = RunsGitHub([
        produce_run(5, 95), produce_run(8, 105), produce_run(9, 1),  # a video, a video, a check-only day
        {"id": 50, "name": "tests", "status": "completed", "conclusion": "success",
         "jobs": [job("2026-10-10T10:00:00Z", "2026-10-10T10:06:10Z")]},
    ])
    usage = minutes.month_usage(github, NOW)
    assert usage.month == "2026-10" and usage.used == 96 + 106 + 2 + 7  # 1.5 minutes is billed as 2
    assert usage.by_workflow == {"produce": 204, "tests": 7} and sorted(usage.video_runs) == [96, 106]
    assert usage.per_video == 101  # the median of the measured video runs
    assert minutes.fits(usage, 400) and not minutes.fits(usage, 300) and minutes.fits(usage, 0)
    assert minutes.Usage("2026-10").per_video == minutes.DEFAULT_VIDEO_MINUTES  # nothing measured yet


def test_over_budget_pauses_the_video_and_asks_once(monkeypatch):
    issues = {}

    class Issues:
        def open_issues(self, label):
            return [{"number": n, **i} for n, i in issues.items() if i["state"] == "open"]

        def create_issue(self, title, body, labels=None):
            issues[len(issues) + 1] = {"title": title, "body": body, "state": "open", "labels": labels}
            return len(issues)

        def comment(self, number, body):
            issues[number]["comment"] = body

        def close_issue(self, number, reason="completed"):
            issues[number]["state"] = "closed"

    logs = []
    ctx = autopilot.Context({"actions": {"monthly_minutes": 300}}, {}, logs.append, github=Issues())
    usage = minutes.Usage("2026-10", used=250, video_runs=[100])
    assert autopilot._over_budget(ctx, usage) is True
    assert autopilot._over_budget(ctx, usage) is True  # asked again: still one issue
    assert len(issues) == 1 and issues[1]["title"].startswith("The bot paused")
    assert "01 November" in issues[1]["body"] and "trading bot" in issues[1]["body"]
    assert autopilot._over_budget(ctx, minutes.Usage("2026-11", used=10, video_runs=[100])) is False
    assert issues[1]["state"] == "closed"  # sorted by itself in the new month
    assert autopilot._over_budget(ctx, None) is False  # minutes unknown: never block a video


def test_video_days_are_settings_in_the_channel_timezone():
    settings = {"schedule": {"make_days": ["thursday", "Mon", "Mon"], "timezone": "Africa/Nairobi"}}
    assert make_days(settings) == ["Mon", "Thu"]
    assert is_make_day(settings, NOW)  # Thursday morning in Nairobi
    assert is_make_day(settings, datetime(2026, 10, 21, 22, 0, tzinfo=UTC))  # 01:00 Thursday in Nairobi
    assert not is_make_day(settings, datetime(2026, 10, 21, 20, 0, tzinfo=UTC))  # 23:00 Wednesday
    with pytest.raises(ValueError, match="isn't a day"):
        make_days({"schedule": {"make_days": ["Funday"]}})


def test_status_file_says_what_the_panel_needs():
    settings = tomllib.loads((ROOT / "channel.toml").read_text())
    state = State([VideoRecord("a", "A", "as-a-man-thinketh", 2, "s", status="local"),
                   VideoRecord("b", "B", "the-kybalion", 1, "s", status="released", release_tag="video-b", issue=7)])
    status = build_status(settings, state, NOW, minutes=minutes.Usage("2026-10", used=210), minutes_budget=1000,
                          needs=[{"title": "x", "issue": 9}])
    assert status["next"]["book"] == "the-way-of-peace"  # balanced: Kybalion and As a Man Thinketh have one or two
    assert status["storage"]["stored"] == 1 and status["videos"][1]["release"] == "video-b"
    assert status["minutes"]["used"] == 210 and status["minutes"]["per_video"] == minutes.DEFAULT_VIDEO_MINUTES
    assert status["schedule"]["make_days"] == ["Mon", "Thu"] and status["chapters_left"] == 43 - 2
    assert {row["id"]: row["left"] for row in status["books"]}["emerson-essays"] == 2
    json.dumps(status)  # it must be plain JSON


GUTENBERG = """The Project Gutenberg eBook of A Small Book
Title: A Small Book
Author: Some Author
Language: English
*** START OF THE PROJECT GUTENBERG EBOOK A SMALL BOOK ***
CONTENTS

  I. THE FIRST IDEA
  II. THE SECOND IDEA


I.

THE FIRST IDEA

{one}

II.

THE SECOND IDEA

{two}
*** END OF THE PROJECT GUTENBERG EBOOK A SMALL BOOK ***
""".format(one="Thought shapes the day. " * 80, two="Purpose steadies the mind. " * 80)


def test_a_book_is_prepared_only_if_its_chapters_are_found(tmp_path):
    book = prepare(123, GUTENBERG, tmp_path, cite="Some Author, A Small Book (1901)")
    assert (book.id, book.file, [c.number for c in book.chapters]) == ("a-small-book", "sources/a-small-book.txt", [1, 2])
    assert not list((tmp_path / "sources").glob("*.checking.txt"))  # the trial file is gone
    with pytest.raises(BookError, match="in French"):
        prepare(124, GUTENBERG.replace("Language: English", "Language: French"), tmp_path)
    with pytest.raises(BookError, match="couldn't be found"):
        prepare(125, GUTENBERG.replace("CONTENTS", "SUMMARY"), tmp_path)
    with pytest.raises(BookError, match="too short"):
        prepare(126, GUTENBERG.replace("Thought shapes the day. " * 80, "Too short."), tmp_path)


def test_adding_to_channel_keeps_comments_and_refuses_duplicates(tmp_path):
    channel = (ROOT / "channel.toml").read_text()
    book = prepare(123, GUTENBERG, tmp_path, cite="Some Author, A Small Book (1901)", only=["The Second Idea"])
    updated = add_to_channel(channel, book)
    assert updated.count("# Public-domain books the writer can use") == 1 and len(updated) > len(channel)
    ids = [b["id"] for b in tomllib.loads(updated)["books"]]
    assert ids[-1] == "a-small-book" and ids[:-1] == [b["id"] for b in tomllib.loads(channel)["books"]]
    assert tomllib.loads(updated)["books"][-1]["chapters"] == ["The Second Idea"]
    assert updated.index("a-small-book") < updated.index("[llm]")  # right after the other books
    with pytest.raises(BookError, match="already in channel.toml"):
        add_to_channel(updated, book)
    assert 'cite = "Some Author, A Small Book (1901)"' in entry(book)


def test_books_come_from_gutenbergs_mirror_only():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text=GUTENBERG) if "123" in str(request.url) else httpx.Response(404)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert "A Small Book" in download(123, http)
    assert seen == ["https://gutenberg.pglaf.org/cache/epub/123/pg123.txt"]
    with pytest.raises(BookError, match="no plain-text book number 9"):
        download(9, http)


def test_plan_says_whether_today_is_a_video_day(tmp_path, monkeypatch, capsys):
    from owd import cli

    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    cli.main(["plan"])
    assert output.read_text() == "make=true\n" and "started by hand" in capsys.readouterr().out
