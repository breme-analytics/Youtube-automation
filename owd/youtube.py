"""Posting to YouTube through the YouTube Data API v3, free (uploads have their own daily quota of
100; a video uses 1 upload plus about 50 + 50 + 400 units for thumbnail, captions and checks, out
of 10,000 a day).

Authorisation is done once, from any device, with Google's device flow (`python -m owd youtube-login`):
the bot shows a code, the owner enters it at google.com/device signed in to the channel's account, and
the bot receives a refresh token. That token is stored as a GitHub secret and used on every run.

Important limits (YouTube's, not the bot's):
- Until the Google Cloud project passes YouTube's free API audit, every API upload is locked as
  private, and that can't be undone. So the bot runs in "review" mode (the owner uploads in YouTube
  Studio) until the audit is approved, then switches to "auto". See docs/DEPLOY.md.
- While the OAuth app is in "Testing", Google expires the refresh token after 7 days. Publish the app
  (Google Auth Platform > Audience > Publish app) to keep it working.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CAPTIONS_URL = "https://www.googleapis.com/upload/youtube/v3/captions"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHUNK = 16 * 1024 * 1024  # resumable upload pieces (a multiple of 256 KiB)
EDUCATION = "27"


class YouTubeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    refresh_token: str


def device_login(client_id: str, client_secret: str, *, http: httpx.Client | None = None,
                 show: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> str:
    """Google's device flow: shows a code to enter at google.com/device, waits, returns the refresh token."""
    http = http or httpx.Client(timeout=30)
    start = http.post(DEVICE_URL, data={"client_id": client_id, "scope": SCOPES})
    if start.status_code != 200:
        raise YouTubeError(f"Google refused the sign-in request ({start.status_code}): {start.text[:300]}")
    data = start.json()
    show(f"On any phone or computer, open {data['verification_url']} and enter the code: {data['user_code']}")
    show("Sign in with the Google account that owns the YouTube channel, and allow access.")
    interval = int(data.get("interval", 5))
    deadline = time.monotonic() + int(data.get("expires_in", 1800))
    while time.monotonic() < deadline:
        sleep(interval)
        poll = http.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                                          "device_code": data["device_code"],
                                          "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        body = poll.json()
        if poll.status_code == 200 and body.get("refresh_token"):
            return body["refresh_token"]
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise YouTubeError(f"Sign-in failed: {error or poll.status_code}")
    raise YouTubeError("The code expired before it was entered; run the command again")


class YouTube:
    def __init__(self, credentials: Credentials, *, http: httpx.Client | None = None, log: Callable[[str], None] = print):
        self.credentials = credentials
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=600.0, write=600.0))
        self.log = log
        self._token: str | None = None
        self._expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._expires - 60:
            return self._token
        response = self.http.post(TOKEN_URL, data={"client_id": self.credentials.client_id,
                                                   "client_secret": self.credentials.client_secret,
                                                   "refresh_token": self.credentials.refresh_token,
                                                   "grant_type": "refresh_token"})
        if response.status_code != 200:
            hint = (" The token has expired: if the OAuth app is still in Testing, publish it, then run "
                    "`python -m owd youtube-login` again." if "invalid_grant" in response.text else "")
            raise YouTubeError(f"Couldn't get a YouTube access token ({response.status_code}).{hint}")
        body = response.json()
        self._token, self._expires = body["access_token"], time.monotonic() + int(body.get("expires_in", 3600))
        return self._token

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def upload(self, video: Path, *, title: str, description: str, tags: list[str], publish_at: datetime | None,
               language: str = "en", synthetic: bool = True) -> str:
        """Upload `video`; private until `publish_at` (when given), then public. Returns the video ID."""
        status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": synthetic}
        if publish_at is not None:
            status["publishAt"] = publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        metadata = {"snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30],
                                "categoryId": EDUCATION, "defaultLanguage": language, "defaultAudioLanguage": language},
                    "status": status}
        size = Path(video).stat().st_size
        start = self.http.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                               headers={**self._auth(), "Content-Type": "application/json; charset=UTF-8",
                                        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                               content=json.dumps(metadata))
        if start.status_code != 200 or "location" not in start.headers:
            raise YouTubeError(f"YouTube refused the upload ({start.status_code}): {start.text[:400]}")
        session = start.headers["location"]
        sent = 0
        with Path(video).open("rb") as handle:
            while True:
                handle.seek(sent)
                piece = handle.read(CHUNK)
                end = sent + len(piece) - 1
                response = self.http.put(session, headers={**self._auth(), "Content-Length": str(len(piece)),
                                                           "Content-Range": f"bytes {sent}-{end}/{size}"}, content=piece)
                if response.status_code in (200, 201):
                    video_id = response.json()["id"]
                    self.log(f"uploaded to YouTube: {video_id}")
                    return video_id
                if response.status_code == 308:
                    received = response.headers.get("range", "")
                    sent = int(received.split("-")[1]) + 1 if received else 0
                    self.log(f"  upload {sent * 100 // size}%")
                    continue
                raise YouTubeError(f"Upload failed at byte {sent} ({response.status_code}): {response.text[:300]}")

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        response = self.http.post(THUMBNAIL_URL, params={"videoId": video_id},
                                  headers={**self._auth(), "Content-Type": "image/jpeg"}, content=Path(image).read_bytes())
        if response.status_code != 200:
            # Custom thumbnails need a verified channel (youtube.com/verify, free): warn, don't fail.
            self.log(f"thumbnail not set ({response.status_code}); verify the channel at youtube.com/verify")

    def add_captions(self, video_id: str, srt: Path, language: str = "en", name: str = "English") -> None:
        boundary = "owdcaptionsboundary"
        meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}})
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + Path(srt).read_bytes() + \
            f"\r\n--{boundary}--\r\n".encode()
        response = self.http.post(CAPTIONS_URL, params={"uploadType": "multipart", "part": "snippet"},
                                  headers={**self._auth(), "Content-Type": f"multipart/related; boundary={boundary}"},
                                  content=body)
        if response.status_code not in (200, 201):
            self.log(f"captions not added ({response.status_code}): {response.text[:200]}")

    def status(self, video_id: str) -> dict:
        response = self.http.get(VIDEOS_URL, params={"part": "status", "id": video_id}, headers=self._auth())
        if response.status_code != 200:
            raise YouTubeError(f"Couldn't read the video's status ({response.status_code})")
        items = response.json().get("items") or []
        return items[0]["status"] if items else {}
