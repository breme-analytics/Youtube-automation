"""GitHub as free storage and notifications, through its REST API with the workflow's token:

- a release per video holds the review copy (video, thumbnail, captions, description) for download.
  Releases have no storage or bandwidth charge; each file must be under 2 GiB;
- an issue per video tells the owner it's ready (GitHub emails her) and holds the checklist;
- cleanup deletes the release (and its files) once the video is posted, so nothing piles up.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

import httpx

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    id: int
    tag: str
    url: str
    assets: dict[str, str]  # file name -> download URL


class GitHub:
    def __init__(self, repository: str, token: str, *, http: httpx.Client | None = None):
        if "/" not in repository:
            raise ValueError("repository must look like owner/name")
        self.repo = repository
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "youtube-automation-bot"}
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=900.0, write=900.0))

    def _call(self, method: str, url: str, ok=(200, 201, 204), **kwargs) -> httpx.Response:
        try:
            response = self.http.request(method, url, headers={**self._headers, **kwargs.pop("headers", {})}, **kwargs)
        except httpx.HTTPError as error:
            raise GitHubError(f"GitHub {method} failed: {type(error).__name__}") from None
        if response.status_code not in ok:
            raise GitHubError(f"GitHub {method} {url.split('.com', 1)[-1]} answered {response.status_code}: {response.text[:300]}")
        return response

    @staticmethod
    def _release(data: dict) -> Release:
        return Release(data["id"], data["tag_name"], data["html_url"],
                       {a["name"]: a["browser_download_url"] for a in data.get("assets", [])})

    def create_release(self, tag: str, title: str, body: str) -> Release:
        data = self._call("POST", f"{API}/repos/{self.repo}/releases",
                          json={"tag_name": tag, "name": title, "body": body, "prerelease": True}).json()
        return self._release(data)

    def find_release(self, tag: str) -> Release | None:
        response = self._call("GET", f"{API}/repos/{self.repo}/releases/tags/{tag}", ok=(200, 404))
        return None if response.status_code == 404 else self._release(response.json())

    def upload_asset(self, release: Release, path: Path, name: str | None = None) -> str:
        name = name or Path(path).name
        size = Path(path).stat().st_size
        if size >= 2 * 1024**3:
            raise GitHubError(f"{name} is over GitHub's 2 GiB limit")
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"

        def chunks():
            with Path(path).open("rb") as handle:
                yield from iter(lambda: handle.read(1 << 20), b"")

        data = self._call("POST", f"{UPLOADS}/repos/{self.repo}/releases/{release.id}/assets", params={"name": name},
                          headers={"Content-Type": kind, "Content-Length": str(size)}, content=chunks()).json()
        return data["browser_download_url"]

    def delete_release(self, tag: str) -> bool:
        """Delete the release and its files, and its tag. False if there was none."""
        release = self.find_release(tag)
        if release is None:
            return False
        self._call("DELETE", f"{API}/repos/{self.repo}/releases/{release.id}")
        self._call("DELETE", f"{API}/repos/{self.repo}/git/refs/tags/{tag}", ok=(204, 404, 422))
        return True

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> int:
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        try:
            return self._call("POST", f"{API}/repos/{self.repo}/issues", json=payload).json()["number"]
        except GitHubError as error:
            if not labels or "422" not in str(error):
                raise
            # A missing or refused label must never stop the owner hearing about her video.
            return self._call("POST", f"{API}/repos/{self.repo}/issues", json={"title": title, "body": body}).json()["number"]

    def comment(self, issue: int, body: str) -> None:
        self._call("POST", f"{API}/repos/{self.repo}/issues/{issue}/comments", json={"body": body})

    def close_issue(self, issue: int) -> None:
        self._call("PATCH", f"{API}/repos/{self.repo}/issues/{issue}", json={"state": "closed", "state_reason": "completed"})

    def issue(self, number: int) -> dict:
        return self._call("GET", f"{API}/repos/{self.repo}/issues/{number}").json()
