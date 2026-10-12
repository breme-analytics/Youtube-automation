"""Posting to YouTube through the YouTube Data API v3, free. Per video: 1 upload (100 a day allowed)
plus about 50 units for the thumbnail, 400 for the captions and a few 1-unit checks, out of the
10,000 units a day every project gets.

Sign-in is done once, on any computer with a browser (`python -m owd youtube-login`): the bot opens
Google's sign-in page, the owner signs in with the channel's account and allows access, and the bot
prints a refresh token to store as a GitHub secret. It uses a "Desktop app" OAuth client with a
loopback redirect and PKCE. (Google's device-code flow, "enter a code at google.com/device", only
allows the youtube and youtube.readonly scopes, so it can't grant caption uploads.)

YouTube's limits, and what the bot does about them, are in docs/DEPLOY.md ("Caveats and fixes"):
uploads from an unaudited project may be kept private, sign-ins of an app in "Testing" expire after
7 days, and custom thumbnails need a verified channel.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CAPTIONS_URL = "https://www.googleapis.com/upload/youtube/v3/captions"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
CHUNK = 16 * 1024 * 1024  # resumable upload pieces (a multiple of 256 KiB)
EDUCATION = "27"


class YouTubeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    refresh_token: str


# One-time sign-in (desktop app, loopback redirect, PKCE)


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for PKCE with S256."""
    verifier = secrets.token_urlsafe(64)  # 86 characters from the allowed set
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def sign_in_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline",  # ask for a refresh token...
        "prompt": "consent",  # ...every time, even if this account allowed the app before
    })


class _Catcher(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server's naming)
        query = parse_qs(urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)  # the browser asking for /favicon.ico and the like
            self.end_headers()
            return
        self.server.answer = {key: values[0] for key, values in query.items()}
        done = "error" not in query
        page = ("<h1>Signed in</h1><p>You can close this tab and go back to the terminal.</p>" if done else
                "<h1>Not signed in</h1><p>Google said: " + query["error"][0].replace("<", "") + "</p>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<!doctype html><title>YouTube sign-in</title>{page}".encode())

    def log_message(self, *args):  # keep the terminal quiet
        pass


def browser_login(client_id: str, client_secret: str, *, http: httpx.Client | None = None,
                  show: Callable[[str], None] = print, open_browser: Callable[[str], object] = webbrowser.open,
                  timeout: float = 600) -> str:
    """Open Google's sign-in page, wait for the owner to allow access, return the refresh token."""
    http = http or httpx.Client(timeout=30)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    server = HTTPServer(("127.0.0.1", 0), _Catcher)  # any free port on this computer only
    server.answer = None
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    url = sign_in_url(client_id, redirect_uri, challenge, state)
    show("Opening Google's sign-in page. If no browser opens, paste this link into a browser on this computer:")
    show(url)
    show("Sign in with the Google account that owns the YouTube channel, and allow access.")
    open_browser(url)
    deadline = time.monotonic() + timeout
    try:
        while server.answer is None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise YouTubeError("Nobody signed in within 10 minutes; run the command again")
            server.timeout = min(left, 5)
            server.handle_request()
    finally:
        server.server_close()
    answer = server.answer
    if answer.get("state") != state:
        raise YouTubeError("The sign-in answer didn't match this request; run the command again")
    if "error" in answer:
        raise YouTubeError(f"Google didn't allow access: {answer['error']}")
    response = http.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret, "code": answer["code"],
                                          "code_verifier": verifier, "grant_type": "authorization_code",
                                          "redirect_uri": redirect_uri})
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200:
        raise YouTubeError(f"Google refused the sign-in ({response.status_code}): {body.get('error_description') or body.get('error') or response.text[:200]}")
    if not body.get("refresh_token"):
        raise YouTubeError("Google sent no refresh token; remove the app's access at myaccount.google.com/permissions and sign in again")
    return body["refresh_token"]


# The API


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
            hint = (" invalid_grant: the sign-in has expired or was revoked. If the OAuth app is still in Testing, "
                    "publish it; then run `python -m owd youtube-login` again and update YOUTUBE_REFRESH_TOKEN."
                    if "invalid_grant" in response.text else "")
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

    def set_thumbnail(self, video_id: str, image: Path) -> bool:
        response = self.http.post(THUMBNAIL_URL, params={"videoId": video_id},
                                  headers={**self._auth(), "Content-Type": "image/jpeg"}, content=Path(image).read_bytes())
        if response.status_code != 200:
            # Custom thumbnails need a verified channel (youtube.com/verify, free): warn, don't fail.
            self.log(f"thumbnail not set ({response.status_code}); verify the channel at youtube.com/verify")
            return False
        return True

    def add_captions(self, video_id: str, srt: Path, language: str = "en", name: str = "English") -> bool:
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
            return False
        return True

    def status(self, video_id: str) -> dict:
        """The video's status (privacyStatus, uploadStatus, publishAt, ...), or {} if it isn't on YouTube."""
        response = self.http.get(VIDEOS_URL, params={"part": "status", "id": video_id}, headers=self._auth())
        if response.status_code != 200:
            raise YouTubeError(f"Couldn't read the video's status ({response.status_code}): {response.text[:200]}")
        items = response.json().get("items") or []
        return items[0].get("status", {}) if items else {}

    def channel_title(self) -> str:
        """The name of the channel these credentials post to."""
        response = self.http.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"}, headers=self._auth())
        if response.status_code != 200:
            raise YouTubeError(f"Couldn't read the channel ({response.status_code}): {response.text[:200]}")
        items = response.json().get("items") or []
        if not items:
            raise YouTubeError("This Google account has no YouTube channel")
        return items[0]["snippet"]["title"]
