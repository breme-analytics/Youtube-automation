"""GitHub as free storage and notifications, through its REST API with the workflow's token:

- a release per video holds its stored copy (video, thumbnail, captions, description). Releases have
  no limit on total size or downloads; each file must be under 2 GiB. In a private repository only
  people signed in with access can download them;
- an issue per video tells the owner about it (GitHub emails her) and holds the checklist;
- cleanup deletes the release (files and tag) once the copy isn't needed, so nothing piles up.
"""

from __future__ import annotations

import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
UPLOAD_TRIES = 3


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    id: int
    tag: str
    url: str
    assets: dict[str, str]  # file name -> download URL
    created_at: str = ""


class GitHub:
    def __init__(self, repository: str, token: str, *, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if "/" not in repository:
            raise ValueError("repository must look like owner/name")
        self.repo = repository
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "youtube-automation-bot"}
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=900.0, write=900.0))
        self.sleep = sleep

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
                       {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}, data.get("created_at", ""))

    # Releases: the stored copies

    def create_release(self, tag: str, title: str, body: str) -> Release:
        data = self._call("POST", f"{API}/repos/{self.repo}/releases",
                          json={"tag_name": tag, "name": title, "body": body, "prerelease": True}).json()
        return self._release(data)

    def find_release(self, tag: str) -> Release | None:
        response = self._call("GET", f"{API}/repos/{self.repo}/releases/tags/{tag}", ok=(200, 404))
        return None if response.status_code == 404 else self._release(response.json())

    def list_releases(self) -> list[Release]:
        releases, page = [], 1
        while True:
            batch = self._call("GET", f"{API}/repos/{self.repo}/releases", params={"per_page": 100, "page": page}).json()
            releases += [self._release(data) for data in batch]
            if len(batch) < 100:
                return releases
            page += 1

    def upload_asset(self, release: Release, path: Path, name: str | None = None) -> str:
        """Upload one file to a release and return its download URL. A failed upload is retried, after
        removing whatever half-uploaded file GitHub kept under the same name."""
        name = name or Path(path).name
        size = Path(path).stat().st_size
        if size >= 2 * 1024**3:
            raise GitHubError(f"{name} is {size / 1024**3:.2f} GiB; GitHub release files must be under 2 GiB")
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"

        def chunks():
            with Path(path).open("rb") as handle:
                yield from iter(lambda: handle.read(1 << 20), b"")

        for attempt in range(1, UPLOAD_TRIES + 1):
            try:
                data = self._call("POST", f"{UPLOADS}/repos/{self.repo}/releases/{release.id}/assets",
                                  params={"name": name}, content=chunks(),
                                  headers={"Content-Type": kind, "Content-Length": str(size)}).json()
                return data["browser_download_url"]
            except GitHubError:
                if attempt == UPLOAD_TRIES:
                    raise
                self.sleep(5 * attempt)
                self._delete_asset_named(release.id, name)
        raise AssertionError("unreachable")

    def _delete_asset_named(self, release_id: int, name: str) -> None:
        assets = self._call("GET", f"{API}/repos/{self.repo}/releases/{release_id}/assets", params={"per_page": 100}).json()
        for asset in assets:
            if asset.get("name") == name:
                self._call("DELETE", f"{API}/repos/{self.repo}/releases/assets/{asset['id']}", ok=(204, 404))

    def delete_release(self, tag: str) -> bool:
        """Delete the release, its files and its tag. False if there was no release."""
        release = self.find_release(tag)
        if release is not None:
            self._call("DELETE", f"{API}/repos/{self.repo}/releases/{release.id}", ok=(204, 404))
        self._call("DELETE", f"{API}/repos/{self.repo}/git/refs/tags/{tag}", ok=(204, 404, 422))
        return release is not None

    # Issues: telling the owner

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

    def update_issue(self, number: int, *, title: str | None = None, labels: list[str] | None = None) -> None:
        payload = {key: value for key, value in (("title", title), ("labels", labels)) if value is not None}
        try:
            self._call("PATCH", f"{API}/repos/{self.repo}/issues/{number}", json=payload)
        except GitHubError as error:
            if labels is None or "422" not in str(error) or title is None:
                raise
            self._call("PATCH", f"{API}/repos/{self.repo}/issues/{number}", json={"title": title})

    def comment(self, issue: int, body: str) -> None:
        self._call("POST", f"{API}/repos/{self.repo}/issues/{issue}/comments", json={"body": body})

    def close_issue(self, issue: int, reason: str = "completed") -> None:
        self._call("PATCH", f"{API}/repos/{self.repo}/issues/{issue}", json={"state": "closed", "state_reason": reason})

    def issue(self, number: int) -> dict:
        return self._call("GET", f"{API}/repos/{self.repo}/issues/{number}").json()

    def open_issues(self, label: str) -> list[dict]:
        """Open issues with `label` (pull requests left out)."""
        items = self._call("GET", f"{API}/repos/{self.repo}/issues",
                           params={"state": "open", "labels": label, "per_page": 100}).json()
        return [item for item in items if "pull_request" not in item]

    # Actions: what this repository's workflows used

    def list_runs(self, created_since: str) -> list[dict]:
        """Workflow runs created on or after `created_since` (YYYY-MM-DD), newest first."""
        runs, page = [], 1
        while True:
            data = self._call("GET", f"{API}/repos/{self.repo}/actions/runs",
                              params={"created": f">={created_since}", "per_page": 100, "page": page}).json()
            batch = data.get("workflow_runs", [])
            runs += batch
            if len(batch) < 100:
                return runs
            page += 1

    def run_jobs(self, run_id: int) -> list[dict]:
        data = self._call("GET", f"{API}/repos/{self.repo}/actions/runs/{run_id}/jobs",
                          params={"per_page": 100, "filter": "latest"}).json()
        return data.get("jobs", [])
