"""News from RSS and Atom feeds, in two kinds:

- research: fresh psychology and neuroscience findings, the "test it against modern psychology"
  half of each video. The script writer cites them; it never copies them.
- platform: YouTube and creator-economy news for the channel owner (policy changes and so on).

The approach follows Breme's news collector: feeds only (never YouTube or Google pages),
robots.txt obeyed, an honest User-Agent, time and size limits, no automatic redirects to other
hosts, and feed text handled as untrusted input. Feeds are listed in channel.toml.
"""

from __future__ import annotations

import calendar
import html
import json
import re
import time
import urllib.robotparser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

USER_AGENT = "OldWisdomDecodedBot/0.1 (reads public RSS feeds for research citations)"
TIMEOUT = 20.0
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
MAX_SUMMARY_CHARS = 600
CACHE_SECONDS = 6 * 3600  # a feed is read at most every six hours
KINDS = ("research", "platform")
# Never fetched, whatever a feed or redirect says: the YouTube API rules forbid scraping YouTube.
BLOCKED_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "ytimg.com", "googlevideo.com", "google.com")
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$|ref$)")


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    url: str
    kind: str

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Feed {self.id}: kind must be one of {KINDS}")
        check_allowed(self.url)


@dataclass(frozen=True)
class NewsItem:
    feed: str
    kind: str
    title: str
    link: str
    published: str | None  # ISO 8601, UTC
    summary: str

    @property
    def published_at(self) -> datetime | None:
        return datetime.fromisoformat(self.published) if self.published else None


class NewsError(RuntimeError):
    pass


def check_allowed(url: str) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise NewsError(f"Only https feed URLs are allowed: {url}")
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_HOSTS):
        raise NewsError(f"Blocked host: {host}")


def canonical_url(url: str) -> str:
    """The link without tracking parameters or a trailing slash, host in lower case."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def clean_text(raw: str, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Plain text from feed HTML: tags and scripts removed, entities decoded, whitespace collapsed,
    cut at a word boundary."""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw or "")
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _title_key(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def parse_feed(feed: Feed, content: bytes) -> list[NewsItem]:
    """Items from feed bytes. feedparser only ever gets bytes, so it never fetches anything."""
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""), 300)
        link = entry.get("link", "")
        if not title or not link.startswith(("https://", "http://")):
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc).isoformat() if stamp else None
        )
        summary = entry.get("summary", "") or " ".join(c.get("value", "") for c in entry.get("content", []) or [])
        items.append(NewsItem(feed.id, feed.kind, title, canonical_url(link), published, clean_text(summary)))
    return items


class Fetcher:
    """Polite HTTP for feeds: robots.txt per host (RFC 9309: a missing robots.txt allows all, an
    unreachable one blocks), redirects followed by hand and re-checked, size and time limits."""

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=False)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                response = self.http.get(origin + "/robots.txt")
            except httpx.HTTPError:
                self._robots[origin] = None  # unreachable: treated as "disallow all"
                return None
            if response.status_code >= 500:
                self._robots[origin] = None
                return None
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            self._robots[origin] = parser
        return self._robots[origin]

    def get(self, url: str) -> bytes:
        for _ in range(MAX_REDIRECTS + 1):
            check_allowed(url)
            robots = self._robots_for(url)
            if robots is None or not robots.can_fetch(USER_AGENT, url):
                raise NewsError(f"robots.txt does not allow {url}")
            with self.http.stream("GET", url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = str(response.url.join(response.headers.get("location", "")))
                    continue
                if response.status_code != 200:
                    raise NewsError(f"{url} answered {response.status_code}")
                body = bytearray()
                for block in response.iter_bytes():
                    body += block
                    if len(body) > MAX_BYTES:
                        raise NewsError(f"{url} is larger than {MAX_BYTES} bytes")
                return bytes(body)
        raise NewsError(f"Too many redirects for {url}")


def relevance(item: NewsItem, keywords: Iterable[str]) -> int:
    """How many of `keywords` (whole words or phrases, any case) the title and summary mention;
    the title counts double."""
    title, body = item.title.lower(), item.summary.lower()
    total = 0
    for keyword in keywords:
        pattern = re.compile(rf"\b{re.escape(keyword.lower())}")
        total += 2 * bool(pattern.search(title)) + bool(pattern.search(body))
    return total


def collect(
    feeds: Iterable[Feed],
    cache_dir: Path,
    *,
    fetcher: Fetcher | None = None,
    clock: Callable[[], float] = time.time,
    log: Callable[[str], None] = lambda message: None,
) -> list[NewsItem]:
    """Items from every feed, newest first, without duplicates. Each feed's items are cached for
    CACHE_SECONDS, so running this often doesn't hit the sites more than every few hours. A feed
    that fails is skipped (and logged); the others still count."""
    fetcher = fetcher or Fetcher()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    items: list[NewsItem] = []
    for feed in feeds:
        path = cache_dir / f"{feed.id}.json"
        cached = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        if cached and clock() - cached["fetched_at"] < CACHE_SECONDS and cached.get("url") == feed.url:
            items += [NewsItem(**item) for item in cached["items"]]
            continue
        try:
            fresh = parse_feed(feed, fetcher.get(feed.url))
        except (NewsError, httpx.HTTPError) as error:
            log(f"{feed.id}: skipped ({type(error).__name__}: {error})")
            if cached:
                items += [NewsItem(**item) for item in cached["items"]]
            continue
        path.write_text(json.dumps({"fetched_at": clock(), "url": feed.url, "items": [asdict(i) for i in fresh]}),
                        encoding="utf-8")
        log(f"{feed.id}: {len(fresh)} items")
        items += fresh
    seen_links, seen_titles, unique = set(), set(), []
    for item in sorted(items, key=lambda i: i.published or "", reverse=True):
        key = _title_key(item.title)
        if item.link in seen_links or key in seen_titles:
            continue
        seen_links.add(item.link)
        seen_titles.add(key)
        unique.append(item)
    return unique


def research_for(items: Iterable[NewsItem], keywords: Iterable[str], *, days: int = 60, now: datetime | None = None,
                 limit: int = 10) -> list[NewsItem]:
    """The research items most related to `keywords` from the last `days` days."""
    now = now or datetime.now(timezone.utc)
    keywords = list(keywords)
    scored = []
    for item in items:
        if item.kind != "research":
            continue
        when = item.published_at
        if when is not None and (now - when).days > days:
            continue
        value = relevance(item, keywords)
        if value:
            scored.append((value, item.published or "", item))
    scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [item for _, _, item in scored[:limit]]


def load_feeds(settings: dict) -> list[Feed]:
    """Enabled feeds from channel settings ([[news.feeds]] in channel.toml)."""
    feeds = []
    for raw in settings.get("news", {}).get("feeds", []):
        if raw.get("enabled", True) is False:
            continue
        feeds.append(Feed(id=raw["id"], name=raw.get("name", raw["id"]), url=raw["url"], kind=raw["kind"]))
    return feeds
