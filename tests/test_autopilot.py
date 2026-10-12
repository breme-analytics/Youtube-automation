import base64
import hashlib
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

from owd import autopilot
from owd.github import GitHub, GitHubError, Release
from owd.schedule import next_slot
from owd.state import State, VideoRecord, load_state, next_chapter, save_state
from owd.youtube import SCOPES, Credentials, YouTube, YouTubeError, browser_login

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


def test_youtube_status_of_a_missing_video_is_empty_and_the_channel_is_named():
    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "A", "expires_in": 3600})
        if request.url.path.endswith("/videos"):
            return httpx.Response(200, json={"items": []})
        assert request.url.params["mine"] == "true"
        return httpx.Response(200, json={"items": [{"snippet": {"title": "Old Wisdom, Decoded"}}]})

    youtube = YouTube(Credentials("a", "b", "c"), http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert youtube.status("gone") == {} and youtube.channel_title() == "Old Wisdom, Decoded"


def _browser(answer: dict, seen: dict):
    """Plays the owner's browser: reads the sign-in link, then lands on the bot's local page with Google's answer."""
    def open_browser(url):
        query = parse_qs(urlparse(url).query)
        seen.update({key: values[0] for key, values in query.items()})
        params = {"state": seen["state"], **answer}

        def visit():
            base = seen["redirect_uri"]
            for path in ("favicon.ico", "?" + urlencode(params)):  # browsers also ask for an icon
                try:
                    urllib.request.urlopen(base + path, timeout=5).read()
                except urllib.error.HTTPError:
                    pass

        threading.Thread(target=visit, daemon=True).start()
    return open_browser


def test_browser_login_uses_pkce_and_returns_the_refresh_token():
    seen, exchanged = {}, {}

    def token_endpoint(request):
        exchanged.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "A", "refresh_token": "REFRESH"})

    token = browser_login("cid", "secret", http=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
                          show=lambda line: None, open_browser=_browser({"code": "CODE"}, seen), timeout=20)
    assert token == "REFRESH"
    assert seen["scope"] == SCOPES and seen["access_type"] == "offline" and seen["prompt"] == "consent"
    assert seen["redirect_uri"].startswith("http://127.0.0.1:") and seen["code_challenge_method"] == "S256"
    verifier = exchanged["code_verifier"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == seen["code_challenge"] and exchanged["code"] == ["CODE"]
    assert exchanged["redirect_uri"] == [seen["redirect_uri"]] and exchanged["grant_type"] == ["authorization_code"]


@pytest.mark.parametrize(("answer", "message"), [
    ({"error": "access_denied"}, "didn't allow access"),
    ({"code": "CODE", "state": "forged"}, "didn't match"),
])
def test_browser_login_refuses_a_denied_or_forged_answer(answer, message):
    no_token_call = httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("no token exchange expected")))
    with pytest.raises(YouTubeError, match=message):
        browser_login("cid", "secret", http=no_token_call, show=lambda line: None,
                      open_browser=_browser(answer, {}), timeout=20)


def test_upload_retries_after_clearing_a_half_uploaded_file(tmp_path):
    calls, waits = [], []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.host == "uploads.github.com":
            uploads = sum(1 for method, path in calls if path.endswith("/assets") and method == "POST")
            return httpx.Response(502 if uploads == 1 else 201, json={"browser_download_url": "https://dl/video.mp4"})
        if request.method == "GET" and request.url.path.endswith("/releases/7/assets"):
            return httpx.Response(200, json=[{"id": 99, "name": "video.mp4"}, {"id": 98, "name": "other.jpg"}])
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    github = GitHub("o/r", "T", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=waits.append)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"0" * 1000)
    assert github.upload_asset(Release(7, "video-x", "u", {}), video) == "https://dl/video.mp4"
    assert ("DELETE", "/repos/o/r/releases/assets/99") in calls and ("DELETE", "/repos/o/r/releases/assets/98") not in calls
    assert waits == [5]


def test_listing_releases_follows_pages():
    def handler(request):
        page = int(request.url.params["page"])
        count = 100 if page == 1 else 3
        return httpx.Response(200, json=[{"id": page * 1000 + n, "tag_name": f"video-{page}-{n}", "html_url": "u",
                                          "assets": [], "created_at": "2026-10-01T00:00:00Z"} for n in range(count)])

    releases = gh_client(handler).list_releases()
    assert len(releases) == 103 and releases[-1].tag == "video-2-2" and releases[0].created_at.startswith("2026")


def test_relabelling_an_issue_still_renames_it_if_the_label_is_refused():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(422 if "labels" in bodies[-1] else 200, json={})

    gh_client(handler).update_issue(4, title="Ready to post: X", labels=["ready-to-post"])
    assert bodies == [{"title": "Ready to post: X", "labels": ["ready-to-post"]}, {"title": "Ready to post: X"}]


def test_slugify():
    assert autopilot.slugify("The Mindset Mistake Keeping Your Life Stuck!") == "the-mindset-mistake-keeping-your-life-stuck"
    assert autopilot.slugify("???") == "video"
