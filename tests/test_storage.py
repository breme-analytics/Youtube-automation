"""The storage requirement: every video is stored in the cloud, deleted a set time after it's
posted, and never piles up. GitHub and YouTube are replaced by small in-memory fakes."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from owd import autopilot
from owd.github import GitHubError, Release
from owd.state import State, VideoRecord, load_state, save_state
from owd.storage import StoragePolicy, expired, make_room, summary
from owd.youtube import YouTubeError

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 3, 15, tzinfo=UTC)  # a Monday, when produce runs


def ago(**delta) -> str:
    return (NOW - timedelta(**delta)).isoformat()


def later(**delta) -> str:
    return (NOW + timedelta(**delta)).isoformat()


class FakeGitHub:
    def __init__(self):
        self.releases: dict[str, dict] = {}
        self.issues: dict[int, dict] = {}
        self.fail_uploads = 0
        self.fail_issues = False

    def _release(self, tag):
        data = self.releases[tag]
        return Release(data["id"], tag, f"https://github.com/o/r/releases/tag/{tag}", dict(data["assets"]), data["created_at"])

    def add_release(self, tag, created_at, files=("video.mp4",)):
        self.releases[tag] = {"id": len(self.releases) + 1, "assets": {f: f"https://dl/{tag}/{f}" for f in files},
                              "created_at": created_at}

    def find_release(self, tag):
        return self._release(tag) if tag in self.releases else None

    def create_release(self, tag, title, body):
        self.add_release(tag, ago(seconds=0), files=())
        self.releases[tag]["body"] = body
        return self._release(tag)

    def upload_asset(self, release, path):
        if self.fail_uploads:
            self.fail_uploads -= 1
            raise GitHubError("GitHub POST answered 502")
        url = f"https://dl/{release.tag}/{Path(path).name}"
        self.releases[release.tag]["assets"][Path(path).name] = url
        return url

    def delete_release(self, tag):
        return self.releases.pop(tag, None) is not None

    def list_releases(self):
        return [self._release(tag) for tag in self.releases]

    def create_issue(self, title, body, labels=None):
        if self.fail_issues:
            raise GitHubError("GitHub POST answered 503")
        number = len(self.issues) + 1
        self.issues[number] = {"title": title, "body": body, "labels": labels or [], "state": "open", "comments": []}
        return number

    def update_issue(self, number, *, title=None, labels=None):
        if title is not None:
            self.issues[number]["title"] = title
        if labels is not None:
            self.issues[number]["labels"] = labels

    def comment(self, number, body):
        self.issues[number]["comments"].append(body)

    def close_issue(self, number, reason="completed"):
        self.issues[number].update(state="closed", state_reason=reason, closed_at=NOW.isoformat())

    def issue(self, number):
        return self.issues[number]


class FakeYouTube:
    def __init__(self, statuses=None, refuse=""):
        self.statuses, self.refuse, self.uploads = statuses or {}, refuse, []

    def upload(self, video, *, title, description, tags, publish_at):
        if self.refuse:
            raise YouTubeError(self.refuse)
        self.uploads.append((title, publish_at, tags))
        return "VID1"

    def set_thumbnail(self, video_id, image):
        return False  # an unverified channel can't set custom thumbnails

    def add_captions(self, video_id, srt):
        return True

    def status(self, video_id):
        return self.statuses.get(video_id, {})


@dataclass
class FakeResult:
    folder: Path
    video: Path
    thumbnail: Path
    captions: Path
    metadata: Path
    review: Path


def make_result(folder: Path) -> FakeResult:
    folder.mkdir(parents=True, exist_ok=True)
    files = {"video": ("video.mp4", b"v" * 5000), "thumbnail": ("thumbnail.jpg", b"j" * 300),
             "captions": ("captions.srt", b"1\n00:00:00,000 --> 00:00:01,000\nHi\n"),
             "metadata": ("metadata.json", json.dumps({"duration": 630.0, "description": "About drift."}).encode()),
             "review": ("review.md", b"## Review\nAll good.\n")}
    paths = {}
    for key, (name, data) in files.items():
        (folder / name).write_bytes(data)
        paths[key] = folder / name
    return FakeResult(folder, **paths)


SETTINGS = {"schedule": {"mode": "review", "timezone": "Africa/Nairobi", "publish_days": ["Tue", "Fri"],
                         "publish_time": "18:00"},
            "storage": {"keep_days_after_posting": 7, "max_videos": 4},
            "books": [{"id": "allen", "author": "James Allen"}]}


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """The autopilot wired to fakes and a temporary state file."""
    state_file = tmp_path / "state" / "videos.json"
    github, youtube, logs = FakeGitHub(), FakeYouTube(), []
    settings = json.loads(json.dumps(SETTINGS))
    monkeypatch.setattr(autopilot, "load_state", lambda: load_state(state_file))
    monkeypatch.setattr(autopilot, "save_state", lambda s: save_state(s, state_file))
    monkeypatch.setattr(autopilot, "_context", lambda log: autopilot.Context(settings, {}, logs.append))
    monkeypatch.setattr(autopilot, "_github", lambda ctx: github)
    monkeypatch.setattr(autopilot, "_youtube", lambda ctx: youtube)
    monkeypatch.setattr(autopilot, "OUTPUT_DIR", tmp_path / "output")

    class Bot:
        pass

    b = Bot()
    b.github, b.youtube, b.logs, b.settings, b.tmp = github, youtube, logs, settings, tmp_path
    b.state_file = state_file
    b.ctx = lambda: autopilot.Context(settings, {}, logs.append)
    b.load = lambda: load_state(state_file)
    b.save = lambda state: save_state(state, state_file)
    return b


def record(slug, status, **fields):
    defaults = {"release_tag": f"video-{slug}" if status not in ("made",) else "", "made_at": ago(days=3)}
    return VideoRecord(slug, slug.title(), "allen", fields.pop("chapter", 1), f"storyboards/{slug}.toml",
                       status=status, **{**defaults, **fields})


# The rules


def test_policy_comes_from_channel_settings():
    assert StoragePolicy.from_settings({}) == StoragePolicy(7, 4)
    assert StoragePolicy.from_settings({"storage": {"keep_days_after_posting": 3, "max_videos": 2}}) == StoragePolicy(3, 2)
    assert StoragePolicy.from_settings({"schedule": {"keep_days": 5}}).keep_days_after_posting == 5  # the old place
    with pytest.raises(ValueError):
        StoragePolicy.from_settings({"storage": {"max_videos": 0}})
    with pytest.raises(ValueError):
        StoragePolicy.from_settings({"storage": {"keep_days_after_posting": -1}})


def test_what_is_due_for_deletion_and_how_room_is_made():
    state = State([
        record("posted-long-ago", "posted", posted_at=ago(days=8)),
        record("posted-recently", "posted", posted_at=ago(days=2)),
        record("discarded", "discarded"),
        record("failed-half-stored", "failed"),
        record("failed-before-storing", "failed", release_tag=""),
        record("waiting-for-owner", "released", made_at=ago(days=60)),  # unposted copies never expire
        record("scheduled", "scheduled", publish_at=later(days=1)),
        record("already-cleaned", "cleaned", posted_at=ago(days=30), cleaned_at=ago(days=23)),
    ])
    policy = StoragePolicy(7, 4)
    assert sorted(r.slug for r in expired(state, policy, NOW)) == ["discarded", "failed-half-stored", "posted-long-ago"]
    for r in expired(state, policy, NOW):
        r.cleaned_at = NOW.isoformat()
    assert make_room(state, policy) == ([], True)  # 3 stored + 1 new fits in 4
    early, room = make_room(state, StoragePolicy(7, 3))
    assert [r.slug for r in early] == ["posted-recently"] and room  # posted copies go first
    early, room = make_room(state, StoragePolicy(7, 2))
    assert [r.slug for r in early] == ["posted-recently"] and not room  # the rest are still waiting


def test_storage_summary_says_when_each_copy_goes():
    state = State([record("a", "posted", posted_at="2026-10-14T15:00:00+00:00", stored_bytes=550_000_000),
                   record("b", "released")])
    lines = summary(state, StoragePolicy(7, 4))
    assert lines[0] == "a: posted, 550 MB, deleted on 21 Oct 2026"
    assert lines[1] == "b: released, size unknown, kept until it's posted or discarded"


# Storing and delivering


def test_review_mode_stores_every_file_then_tells_the_owner(bot):
    state = State([record("new-video", "made")])
    bot.save(state)
    result = make_result(bot.tmp / "output" / "videos" / "new-video")
    autopilot.deliver(bot.ctx(), state, state.videos[0], result, bot.github)
    video = bot.load().videos[0]
    assert video.status == "released" and video.release_tag == "video-new-video" and video.stored
    assert set(bot.github.releases["video-new-video"]["assets"]) == {"video.mp4", "thumbnail.jpg", "captions.srt",
                                                                     "metadata.json"}
    assert video.stored_bytes == sum(p.stat().st_size for p in (result.video, result.thumbnail, result.captions,
                                                                  result.metadata))
    issue = bot.github.issues[video.issue]
    assert issue["title"] == "Ready to post: New-Video" and issue["labels"] == ["ready-to-post"]
    assert "https://dl/video-new-video/video.mp4" in issue["body"] and "Close as not planned" in issue["body"]
    assert "deleted 7 days later" in issue["body"]


def test_a_half_stored_copy_is_recorded_and_cleaned_up(bot, monkeypatch):
    bot.github.fail_uploads = 99
    result = make_result(bot.tmp / "output" / "videos" / "x")
    monkeypatch.setattr(autopilot, "write_next", lambda ctx, state, angle: _written(state, "half"))
    monkeypatch.setattr(autopilot, "render", lambda ctx, rec: result)
    with pytest.raises(GitHubError):
        autopilot.run(log=bot.logs.append)
    video = bot.load().videos[0]
    assert video.status == "failed" and video.release_tag == "video-half" and video.stored
    assert "video-half" in bot.github.releases  # the half-made release exists...
    assert autopilot.cleanup(log=bot.logs.append, now=NOW) == ["half"]
    assert "video-half" not in bot.github.releases and not bot.load().videos[0].stored  # ...until the cleanup


def _written(state, slug):
    rec = VideoRecord(slug, slug.title(), "allen", len(state.videos) + 1, f"storyboards/{slug}.toml")
    state.videos.append(rec)
    autopilot.save_state(state)
    return rec, Path(rec.storyboard)


def test_auto_mode_also_stores_a_copy_and_schedules_it(bot):
    bot.settings["schedule"]["mode"] = "auto"
    state = State([record("auto-video", "made")])
    autopilot.deliver(bot.ctx(), state, state.videos[0], make_result(bot.tmp / "v"), bot.github)
    video = bot.load().videos[0]
    assert video.status == "scheduled" and video.youtube_id == "VID1" and video.stored
    slot = datetime.fromisoformat(video.publish_at)
    assert slot.weekday() in (1, 4) and (slot.hour, slot.minute) == (15, 0) and slot > datetime.now(UTC)  # 18:00 Nairobi
    issue = bot.github.issues[video.issue]
    assert issue["title"].startswith("Scheduled: ") and issue["labels"] == ["scheduled"]
    assert "Nothing to do" in issue["body"] and "https://dl/video-auto-video/video.mp4" in issue["body"]
    assert any("thumbnail refused" in note for note in video.notes)
    assert bot.youtube.uploads[0][2][0] == "James Allen"  # tags start with the book's author


@pytest.mark.parametrize(("refusal", "fix"), [
    ("Couldn't get a YouTube access token (400). invalid_grant: the sign-in has expired", "Publish app"),
    ("YouTube refused the upload (403): quotaExceeded", "resets at midnight Pacific"),
])
def test_auto_mode_hands_the_stored_copy_to_the_owner_when_youtube_refuses(bot, refusal, fix):
    bot.settings["schedule"]["mode"] = "auto"
    bot.youtube.refuse = refusal
    state = State([record("refused", "made")])
    autopilot.deliver(bot.ctx(), state, state.videos[0], make_result(bot.tmp / "v"), bot.github)
    video = bot.load().videos[0]
    assert video.status == "released" and video.stored and not video.youtube_id
    body = bot.github.issues[video.issue]["body"]
    assert "YouTube didn't take it" in body and fix in body and "### Post it" in body


def test_auto_mode_without_youtube_secrets_says_what_to_add(bot, monkeypatch):
    bot.settings["schedule"]["mode"] = "auto"
    monkeypatch.setattr(autopilot, "_youtube", lambda ctx: None)
    state = State([record("no-secrets", "made")])
    autopilot.deliver(bot.ctx(), state, state.videos[0], make_result(bot.tmp / "v"), bot.github)
    body = bot.github.issues[bot.load().videos[0].issue]["body"]
    assert "needs the secrets" in body and "DEPLOY.md" in body


def test_a_video_already_on_youtube_is_never_made_again(bot, monkeypatch):
    bot.settings["schedule"]["mode"] = "auto"
    bot.github.fail_issues = True
    result = make_result(bot.tmp / "v")
    monkeypatch.setattr(autopilot, "write_next", lambda ctx, state, angle: _written(state, "uploaded"))
    monkeypatch.setattr(autopilot, "render", lambda ctx, rec: result)
    with pytest.raises(GitHubError):
        autopilot.run(log=bot.logs.append)
    assert bot.load().videos[0].status == "scheduled"  # not "failed", so the chapter isn't uploaded twice


# Catching up


def test_catch_up_reads_issues_and_youtube(bot):
    gh = bot.github
    for n in range(1, 8):
        gh.issues[n] = {"title": f"#{n}", "labels": [], "state": "open", "comments": []}
    gh.issues[1].update(state="closed", state_reason="completed", closed_at="2026-10-16T09:00:00Z")
    gh.issues[2].update(state="closed", state_reason="not_planned", closed_at="2026-10-16T09:00:00Z")
    bot.youtube.statuses = {"PUB": {"privacyStatus": "public", "uploadStatus": "processed"},
                            "LOCK": {"privacyStatus": "private", "uploadStatus": "processed"}}
    state = State([
        record("owner-posted", "released", issue=1),
        record("owner-discarded", "released", issue=2),
        record("went-public", "scheduled", issue=3, youtube_id="PUB", publish_at=ago(days=1)),
        record("kept-private", "scheduled", issue=4, youtube_id="LOCK", publish_at=ago(days=1)),
        record("not-yet", "scheduled", issue=5, youtube_id="LOCK", publish_at=later(days=1)),
        record("stopped-run", "made", made_at=ago(days=2)),
        record("still-waiting", "released", issue=7),
    ])
    autopilot.catch_up(bot.ctx(), state, gh, bot.youtube, NOW)
    status = {r.slug: r for r in state.videos}
    assert status["owner-posted"].status == "posted" and status["owner-posted"].posted_at == "2026-10-16T09:00:00+00:00"
    assert status["owner-discarded"].status == "discarded"
    assert status["went-public"].status == "posted" and gh.issues[3]["state"] == "closed"
    assert "youtu.be/PUB" in gh.issues[3]["comments"][0] and "will be deleted on 25 October 2026" in gh.issues[3]["comments"][0]
    assert status["kept-private"].status == "released"
    assert gh.issues[4]["title"] == "Ready to post: Kept-Private" and gh.issues[4]["labels"] == ["ready-to-post"]
    assert "yt_api_form" in gh.issues[4]["comments"][0] and "### Post it" in gh.issues[4]["comments"][0]
    assert status["not-yet"].status == "scheduled"
    assert status["stopped-run"].status == "failed"  # its chapter is made again
    assert status["still-waiting"].status == "released"


def test_without_youtube_secrets_a_scheduled_copy_is_kept(bot):
    state = State([record("unchecked", "scheduled", youtube_id="X", publish_at=ago(days=2))])
    autopilot.catch_up(bot.ctx(), state, bot.github, None, NOW)
    assert state.videos[0].status == "scheduled" and state.videos[0].stored
    assert any("no YouTube secrets" in line for line in bot.logs)


# Cleanup and the cap


def test_cleanup_deletes_what_is_due_and_stray_copies(bot):
    gh = bot.github
    state = State([
        record("posted-8-days-ago", "posted", posted_at=ago(days=8)),
        record("posted-yesterday", "posted", posted_at=ago(days=1)),
        record("discarded", "discarded"),
        record("waiting", "released"),
    ])
    bot.save(state)
    for r in state.videos:
        gh.add_release(r.release_tag, ago(days=10))
    gh.add_release("video-stray-old", ago(days=3))  # no record knows it: deleted
    gh.add_release("video-stray-new", ago(hours=2))  # may belong to a run in progress: kept
    gh.add_release("v1.0", ago(days=90))  # not a video: never touched
    deleted = autopilot.cleanup(log=bot.logs.append, now=NOW)
    assert sorted(deleted) == ["discarded", "posted-8-days-ago", "video-stray-old"]
    assert sorted(gh.releases) == ["v1.0", "video-posted-yesterday", "video-stray-new", "video-waiting"]
    after = {r.slug: r for r in bot.load().videos}
    assert after["posted-8-days-ago"].status == "cleaned" and after["discarded"].status == "discarded"
    assert not after["discarded"].stored and after["posted-yesterday"].stored and after["waiting"].stored
    assert any(line.startswith("Storage: 2 of at most 4 videos stored") for line in bot.logs)


def test_a_failed_deletion_is_kept_and_tried_again(bot, monkeypatch):
    state = State([record("due", "posted", posted_at=ago(days=9))])
    bot.save(state)
    monkeypatch.setattr(bot.github, "delete_release", lambda tag: (_ for _ in ()).throw(GitHubError("503")))
    assert autopilot.cleanup(log=bot.logs.append, now=NOW) == []
    assert bot.load().videos[0].stored and any("trying again next time" in line for line in bot.logs)


def test_run_makes_nothing_while_every_stored_video_is_waiting(bot, monkeypatch):
    bot.save(State([record(f"waiting-{n}", "released", chapter=n) for n in range(1, 5)]))
    monkeypatch.setattr(autopilot, "write_next", lambda *a: pytest.fail("no new video when storage is full"))
    assert autopilot.run(log=bot.logs.append) is None
    assert any("Storage is full: 4 videos are waiting" in line for line in bot.logs)


def test_run_deletes_a_posted_copy_early_to_make_room(bot, monkeypatch):
    state = State([record(f"waiting-{n}", "released", chapter=n) for n in range(1, 4)]
                  + [record("posted", "posted", chapter=4, posted_at=ago(days=1))])
    bot.save(state)
    for r in state.videos:
        bot.github.add_release(r.release_tag, ago(days=2))
    result = make_result(bot.tmp / "v")
    monkeypatch.setattr(autopilot, "write_next", lambda ctx, st, angle: _written(st, "fresh"))
    monkeypatch.setattr(autopilot, "render", lambda ctx, rec: result)
    made = autopilot.run(log=bot.logs.append)
    after = {r.slug: r for r in bot.load().videos}
    assert made.slug == "fresh" and after["fresh"].status == "released"
    assert after["posted"].status == "cleaned" and "video-posted" not in bot.github.releases
    assert len(bot.load().stored()) == 4


def test_run_refuses_to_work_without_cloud_storage(bot, monkeypatch):
    monkeypatch.setattr(autopilot, "_github", lambda ctx: None)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        autopilot.run(log=bot.logs.append)


def test_a_mistyped_mode_fails_before_any_work(bot):
    bot.settings["schedule"]["mode"] = "automatic"
    with pytest.raises(ValueError, match='"review" or "auto"'):
        autopilot.run(log=bot.logs.append)


def test_github_actions_warnings_are_escaped(capsys):
    ctx = autopilot.Context({}, {"GITHUB_ACTIONS": "true"}, lambda line: None)
    ctx.warn("50% full\nsecond line")
    assert capsys.readouterr().out == "::warning::50%25 full%0Asecond line\n"


def test_old_state_files_still_load(tmp_path):
    path = tmp_path / "videos.json"
    path.write_text(json.dumps({"videos": [{"slug": "a", "title": "A", "book": "b", "chapter": 1, "storyboard": "s",
                                            "status": "released", "release_tag": "video-a", "retired_field": 1}]}))
    video = load_state(path).videos[0]
    assert video.stored and video.waiting and video.stored_bytes == 0
