import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from owd import autopilot
from owd.github import GitHub, GitHubError
from owd.schedule import next_slot
from owd.state import State, VideoRecord, load_state, next_chapter, save_state
from owd.youtube import Credentials, YouTube, YouTubeError, device_login

UTC = timezone.utc


def test_state_round_trips_and_picks_the_next_unused_chapter(tmp_path):
    path = tmp_path / "videos.json"
    state = State([VideoRecord("a", "A", "allen", 1, "s.toml"), VideoRecord("b", "B", "allen", 2, "t.toml", status="failed")])
    save_state(state, path)
    loaded = load_state(path)
    assert [v.slug for v in loaded.videos] == ["a", "b"] and loaded.find("a").chapter == 1
    books = [{"id": "allen"}, {"id": "haanel"}]
    assert next_chapter(loaded, books, {"allen": 3, "haanel": 24}) == ("allen", 2)  # failed chapters are retried
    loaded.videos += [VideoRecord("c", "C", "allen", 2, "u"), VideoRecord("d", "D", "allen", 3, "v")]
    assert next_chapter(loaded, books, {"allen": 3, "haanel": 24}) == ("haanel", 1)
    assert next_chapter(State(), [], {}) is None
    assert load_state(tmp_path / "missing.json").videos == []


def test_next_slot_uses_posting_days_in_the_channel_timezone():
    monday_noon = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)  # 12:00 in Nairobi
    first = next_slot(monday_noon, ["Tue", "Fri"], "18:00", "Africa/Nairobi")
    assert first == datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # Tuesday 18:00 Nairobi
    second = next_slot(monday_noon, ["Tue", "Fri"], "18:00", "Africa/Nairobi", taken=[first])
    assert second == datetime(2026, 10, 16, 15, 0, tzinfo=UTC)  # Friday, because Tuesday is taken
    late = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)  # an hour before Tuesday's slot: too close
    assert next_slot(late, ["Tue", "Fri"], "18:00", "Africa/Nairobi") == second
    with pytest.raises(ValueError):
        next_slot(monday_noon, [], "18:00", "UTC")


def gh_client(handler):
    return GitHub("breme-analytics/Youtube-automation", "TOKEN", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_github_release_upload_issue_and_delete(tmp_path):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.host, request.url.path))
        assert request.headers["authorization"] == "Bearer TOKEN"
        if request.method == "POST" and request.url.path.endswith("/releases"):
            return httpx.Response(201, json={"id": 7, "tag_name": "video-x", "html_url": "https://gh/r/7", "assets": []})
        if request.url.host == "uploads.github.com":
            assert request.url.params["name"] == "video.mp4"
            return httpx.Response(201, json={"browser_download_url": "https://gh/d/video.mp4"})
        if request.method == "GET" and "/releases/tags/" in request.url.path:
            return httpx.Response(200, json={"id": 7, "tag_name": "video-x", "html_url": "u", "assets": []})
        if request.method == "POST" and request.url.path.endswith("/issues"):
            assert json.loads(request.content)["labels"] == ["ready-to-post"]
            return httpx.Response(201, json={"number": 12})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    github = gh_client(handler)
    release = github.create_release("video-x", "Title", "body")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"0" * 2048)
    assert github.upload_asset(release, video) == "https://gh/d/video.mp4"
    assert github.create_issue("Ready", "body", ["ready-to-post"]) == 12
    assert github.delete_release("video-x") is True
    assert ("DELETE", "api.github.com", "/repos/breme-analytics/Youtube-automation/git/refs/tags/video-x") in seen
    with pytest.raises(GitHubError, match="403"):
        gh_client(lambda r: httpx.Response(403, text="nope")).create_issue("x", "y")


def test_an_issue_is_still_opened_if_the_label_is_refused():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "labels" in body:
            return httpx.Response(422, text="Validation Failed")
        return httpx.Response(201, json={"number": 3})

    assert gh_client(handler).create_issue("Ready", "b", ["ready-to-post"]) == 3
    assert "labels" in bodies[0] and "labels" not in bodies[1]


def yt_handler(log):
    def handler(request):
        log.append((request.method, str(request.url)))
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "ACCESS", "expires_in": 3600})
        if request.url.path == "/upload/youtube/v3/videos" and request.method == "POST":
            meta = json.loads(request.content)
            assert meta["status"]["privacyStatus"] == "private" and meta["status"]["publishAt"] == "2026-10-13T15:00:00.000Z"
            assert meta["status"]["containsSyntheticMedia"] is True and meta["snippet"]["categoryId"] == "27"
            return httpx.Response(200, headers={"location": "https://upload.session/abc"})
        if request.url.host == "upload.session":
            total = int(request.headers["content-range"].split("/")[1])
            end = int(request.headers["content-range"].split("-")[1].split("/")[0])
            if end + 1 < total:
                return httpx.Response(308, headers={"range": f"bytes=0-{end}"})
            return httpx.Response(200, json={"id": "VIDEO123"})
        if "thumbnails" in request.url.path:
            return httpx.Response(403)  # an unverified channel can't set thumbnails yet
        if "captions" in request.url.path:
            assert b"WEBVTT" in request.content or b"00:00" in request.content
            return httpx.Response(200, json={"id": "cap"})
        return httpx.Response(404)
    return handler


def test_youtube_resumable_upload_with_schedule_thumbnail_and_captions(tmp_path, monkeypatch):
    monkeypatch.setattr("owd.youtube.CHUNK", 1024)
    log, messages = [], []
    youtube = YouTube(Credentials("cid", "secret", "refresh"), http=httpx.Client(transport=httpx.MockTransport(yt_handler(log))),
                      log=messages.append)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"v" * 2500)
    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpg")
    video_id = youtube.upload(video, title="T" * 120, description="D", tags=["a"],
                              publish_at=datetime(2026, 10, 13, 15, 0, tzinfo=UTC))
    assert video_id == "VIDEO123"
    assert sum(1 for method, url in log if "upload.session" in url) == 3  # 2500 bytes in 1024-byte pieces
    youtube.set_thumbnail(video_id, thumb)
    youtube.add_captions(video_id, srt)
    assert any("verify the channel" in m for m in messages)
    assert sum(1 for method, url in log if url.endswith("/token")) == 1  # the access token is reused


def test_youtube_explains_an_expired_refresh_token():
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(YouTubeError, match="publish it"):
        YouTube(Credentials("a", "b", "c"), http=http).status("x")


def test_device_login_waits_for_the_owner_then_returns_the_refresh_token():
    answers = iter([
        httpx.Response(200, json={"device_code": "D", "user_code": "ABCD-EFGH", "verification_url": "https://google.com/device",
                                  "interval": 5, "expires_in": 600}),
        httpx.Response(428, json={"error": "authorization_pending"}),
        httpx.Response(200, json={"access_token": "A", "refresh_token": "REFRESH"}),
    ])
    shown, waits = [], []
    token = device_login("cid", "secret", http=httpx.Client(transport=httpx.MockTransport(lambda r: next(answers))),
                         show=shown.append, sleep=waits.append)
    assert token == "REFRESH" and "ABCD-EFGH" in shown[0] and waits == [5, 5]


class FakeGitHub:
    def __init__(self, closed=None):
        self.closed = closed or {}
        self.deleted, self.comments, self.closed_issues = [], [], []

    def issue(self, number):
        when = self.closed.get(number)
        return {"state": "closed", "closed_at": when} if when else {"state": "open"}

    def delete_release(self, tag):
        self.deleted.append(tag)
        return True

    def comment(self, issue, body):
        self.comments.append(issue)

    def close_issue(self, issue):
        self.closed_issues.append(issue)


def test_cleanup_deletes_files_after_posting_or_after_keep_days(tmp_path, monkeypatch):
    now = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)
    state_file = tmp_path / "videos.json"
    state = State([
        VideoRecord("posted-long-ago", "A", "b", 1, "s", status="released", release_tag="video-a", issue=1,
                    made_at=(now - timedelta(days=20)).isoformat()),
        VideoRecord("posted-yesterday", "B", "b", 2, "s", status="released", release_tag="video-b", issue=2,
                    made_at=(now - timedelta(days=3)).isoformat()),
        VideoRecord("never-posted", "C", "b", 3, "s", status="released", release_tag="video-c", issue=3,
                    made_at=(now - timedelta(days=9)).isoformat()),
        VideoRecord("scheduled", "D", "b", 4, "s", status="scheduled", youtube_id="Y",
                    publish_at=(now - timedelta(days=10)).isoformat(), made_at=(now - timedelta(days=12)).isoformat()),
        VideoRecord("fresh", "E", "b", 5, "s", status="released", release_tag="video-e", issue=5,
                    made_at=(now - timedelta(days=1)).isoformat()),
    ])
    save_state(state, state_file)
    github = FakeGitHub(closed={1: (now - timedelta(days=15)).isoformat(), 2: (now - timedelta(days=1)).isoformat()})
    monkeypatch.setattr(autopilot, "load_state", lambda: load_state(state_file))
    monkeypatch.setattr(autopilot, "save_state", lambda s: save_state(s, state_file))
    monkeypatch.setattr(autopilot, "_github", lambda ctx: github)
    monkeypatch.setattr(autopilot, "_context", lambda log: autopilot.Context({"schedule": {"keep_days": 7}}, {}, log))
    monkeypatch.setattr(autopilot, "OUTPUT_DIR", tmp_path / "output")
    cleaned = autopilot.cleanup(log=lambda m: None, now=now)
    assert sorted(cleaned) == ["never-posted", "posted-long-ago", "scheduled"]
    assert sorted(github.deleted) == ["video-a", "video-c"] and sorted(github.closed_issues) == [1, 3]
    after = {v.slug: v for v in load_state(state_file).videos}
    assert after["posted-yesterday"].status == "posted"  # posted, but kept a few more days
    assert after["fresh"].status == "released" and after["scheduled"].status == "cleaned"


def test_slugify():
    assert autopilot.slugify("The Mindset Mistake Keeping Your Life Stuck!") == "the-mindset-mistake-keeping-your-life-stuck"
    assert autopilot.slugify("???") == "video"
