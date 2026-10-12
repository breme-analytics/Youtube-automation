from datetime import datetime, timezone

import httpx
import pytest

from owd import news
from owd.news import (
    Feed,
    Fetcher,
    NewsError,
    NewsItem,
    canonical_url,
    clean_text,
    collect,
    load_feeds,
    parse_feed,
    relevance,
    research_for,
)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Lab</title>
<item><title>Rumination &amp; sleep: a new study</title>
<link>https://lab.example/story/?utm_source=rss&amp;id=4</link>
<pubDate>Fri, 10 Oct 2026 08:00:00 GMT</pubDate>
<description><![CDATA[<p>People who <b>ruminate</b> sleep worse.</p><script>alert(1)</script>]]></description></item>
<item><title>No link here</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
<entry><title>YouTube updates its policies</title><link href="https://blog.example/policy"/>
<updated>2026-10-01T12:00:00Z</updated><summary>New rules for creators.</summary></entry>
</feed>"""

FEED = Feed("lab", "Lab", "https://lab.example/feed", "research")


def test_parse_rss_and_atom():
    items = parse_feed(FEED, RSS)
    assert len(items) == 1
    item = items[0]
    assert item.title == "Rumination & sleep: a new study"
    assert item.link == "https://lab.example/story?id=4"
    assert item.published == "2026-10-10T08:00:00+00:00"
    assert item.summary == "People who ruminate sleep worse."
    atom = parse_feed(Feed("blog", "Blog", "https://blog.example/feed", "platform"), ATOM)
    assert [(i.title, i.kind, i.published[:10]) for i in atom] == [("YouTube updates its policies", "platform", "2026-10-01")]


def test_clean_text_and_canonical_url():
    assert clean_text("<p>a&nbsp;b</p><style>x{}</style>  c") == "a b c"
    assert clean_text("word " * 200, limit=20).endswith("…")
    assert canonical_url("HTTPS://Example.COM/a/b/?utm_medium=x&fbclid=1&page=2") == "https://example.com/a/b?page=2"


def test_feeds_must_be_https_and_never_youtube_or_google():
    with pytest.raises(NewsError):
        Feed("x", "x", "http://plain.example/feed", "research")
    with pytest.raises(NewsError):
        Feed("x", "x", "https://www.youtube.com/feeds/videos.xml?channel_id=1", "platform")
    with pytest.raises(ValueError):
        Feed("x", "x", "https://ok.example/feed", "gossip")


def make_fetcher(routes):
    def handler(request: httpx.Request):
        response = routes.get(str(request.url))
        return response() if callable(response) else (response or httpx.Response(404))
    return Fetcher(http=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False))


def test_fetcher_obeys_robots_follows_redirects_and_caps_size(monkeypatch):
    fetcher = make_fetcher({
        "https://a.example/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /private\n"),
        "https://a.example/feed": httpx.Response(301, headers={"location": "https://a.example/new-feed"}),
        "https://a.example/new-feed": httpx.Response(200, content=RSS),
        "https://a.example/private/feed": httpx.Response(200, content=RSS),
        "https://b.example/robots.txt": httpx.Response(503),
        "https://b.example/feed": httpx.Response(200, content=RSS),
        "https://a.example/to-youtube": httpx.Response(302, headers={"location": "https://www.youtube.com/x"}),
        "https://a.example/huge": httpx.Response(200, content=b"x" * 3000),
    })
    assert fetcher.get("https://a.example/feed") == RSS
    with pytest.raises(NewsError, match="robots"):
        fetcher.get("https://a.example/private/feed")
    with pytest.raises(NewsError, match="robots"):
        fetcher.get("https://b.example/feed")  # robots.txt unreachable: treated as disallow
    with pytest.raises(NewsError, match="Blocked"):
        fetcher.get("https://a.example/to-youtube")
    monkeypatch.setattr(news, "MAX_BYTES", 1000)
    with pytest.raises(NewsError, match="larger"):
        fetcher.get("https://a.example/huge")


def test_collect_caches_dedupes_and_survives_a_broken_feed(tmp_path):
    hits = []

    def feed_body():
        hits.append(1)
        return httpx.Response(200, content=RSS)

    fetcher = make_fetcher({
        "https://lab.example/robots.txt": httpx.Response(404),
        "https://lab.example/feed": feed_body,
        "https://lab.example/copy": httpx.Response(200, content=RSS),
        "https://down.example/robots.txt": httpx.Response(404),
        "https://down.example/feed": httpx.Response(500),
    })
    feeds = [FEED, Feed("copy", "Copy", "https://lab.example/copy", "research"),
             Feed("down", "Down", "https://down.example/feed", "research")]
    logs = []
    items = collect(feeds, tmp_path, fetcher=fetcher, clock=lambda: 1000.0, log=logs.append)
    assert len(items) == 1  # same story from two feeds counts once
    assert any("down: skipped" in line for line in logs)
    collect(feeds, tmp_path, fetcher=fetcher, clock=lambda: 2000.0)
    assert len(hits) == 1  # still fresh in the cache


def test_relevance_and_research_for():
    item = NewsItem("lab", "research", "Rumination and sleep", "https://x", "2026-10-10T08:00:00+00:00",
                    "People who worry sleep worse.")
    old = NewsItem("lab", "research", "Rumination in 1990", "https://y", "2026-01-01T00:00:00+00:00", "")
    platform = NewsItem("blog", "platform", "Rumination policy", "https://z", "2026-10-10T08:00:00+00:00", "")
    assert relevance(item, ["rumination", "worry", "gratitude"]) == 3
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    assert research_for([item, old, platform], ["rumination"], days=60, now=now) == [item]


def test_load_feeds_skips_disabled():
    settings = {"news": {"feeds": [
        {"id": "a", "name": "A", "url": "https://a.example/feed", "kind": "research"},
        {"id": "b", "url": "https://b.example/feed", "kind": "platform", "enabled": False},
    ]}}
    assert [feed.id for feed in load_feeds(settings)] == ["a"]
