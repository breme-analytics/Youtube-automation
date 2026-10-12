"""Free stock footage from Pixabay's API (https://pixabay.com/api/docs/).

Pixabay asks API users to cache every search for 24 hours, keep automated queries low, never mass
download, and show where the media comes from. So searches are cached on disk for a day, a clip
is downloaded only when a video uses it (and kept for reuse), and each clip carries a credit for
the video description. AI-generated and low-quality clips are skipped.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import httpx

API_URL = "https://pixabay.com/api/videos/"
SEARCH_TTL = 24 * 3600
CATEGORIES = frozenset(
    "backgrounds fashion nature science education feelings health people religion places animals "
    "industry computer food sports transportation travel buildings business music".split()
)
MAX_SLOWDOWN = 1.5  # a clip may play this much slower than real time to fill its shot
EDGE_TRIM = 0.4  # seconds skipped at each end of a clip, where many fade or settle
MIN_LANDSCAPE_RATIO = 1.5  # landscape videos only take clips at least this wide (16:9 is 1.78)
USER_AGENT = "old-wisdom-decoded/0.1 (+https://pixabay.com/api/docs/)"


class StockError(RuntimeError):
    pass


@dataclass(frozen=True)
class Rendition:
    name: str
    url: str
    width: int
    height: int
    size: int
    thumbnail: str = ""  # Pixabay's preview still for this rendition


@dataclass(frozen=True)
class StockVideo:
    id: int
    page_url: str
    tags: tuple[str, ...]
    duration: float
    user: str
    renditions: tuple[Rendition, ...]
    ai_generated: bool = False
    low_quality: bool = False
    downloads: int = 0

    @classmethod
    def from_api(cls, hit: dict) -> "StockVideo":
        renditions = tuple(
            Rendition(name, item.get("url", ""), int(item.get("width") or 0), int(item.get("height") or 0),
                      int(item.get("size") or 0), str(item.get("thumbnail") or ""))
            for name, item in (hit.get("videos") or {}).items()
            if item and item.get("url")
        )
        return cls(
            id=int(hit["id"]),
            page_url=str(hit.get("pageURL", "")),
            tags=tuple(tag.strip() for tag in str(hit.get("tags", "")).split(",") if tag.strip()),
            duration=float(hit.get("duration") or 0),
            user=str(hit.get("user", "")),
            renditions=renditions,
            ai_generated=bool(hit.get("isAiGenerated")),
            low_quality=bool(hit.get("isLowQuality")),
            downloads=int(hit.get("downloads") or 0),
        )

    @property
    def credit(self) -> str:
        return f"{self.user} on Pixabay: {self.page_url}"

    @property
    def preview_url(self) -> str:
        """The smallest rendition's preview still (Pixabay serves one per rendition)."""
        usable = [r for r in self.renditions if r.thumbnail]
        return min(usable, key=lambda r: r.width * r.height).thumbnail if usable else ""


def fill_scale(width: int, height: int, size: tuple[int, int]) -> float:
    """How much a width x height frame must be enlarged to fill `size` (above 1 means upscaling)."""
    return max(size[0] / width, size[1] / height)


def best_rendition(video: StockVideo, size: tuple[int, int], max_upscale: float = 1.0) -> Rendition | None:
    """The smallest rendition that fills `size` without enlarging more than `max_upscale`, else
    the largest one there is."""
    usable = [r for r in video.renditions if r.width > 0 and r.height > 0]
    sharp = [r for r in usable if fill_scale(r.width, r.height, size) <= max_upscale]
    if sharp:
        return min(sharp, key=lambda r: r.width * r.height)
    return max(usable, key=lambda r: r.width * r.height, default=None)


_WORD = re.compile(r"[a-z]+")


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def term_list(text: str) -> list[str]:
    """Search words in order, lightly stemmed (zebras -> zebra)."""
    return [_stem(word) for word in _WORD.findall(text.lower())]


def _terms(text: str) -> set[str]:
    return set(term_list(text))


# Describing words are never a search's subject: "old book pages" is about a book, "calm lake"
# about a lake.
DESCRIBING = frozenset(
    "old ancient antique calm dark bright slow fast beautiful golden misty foggy empty lonely quiet soft warm "
    "cold big small little young new close closeup macro aerial abstract blue red green white black purple "
    "orange glowing burning flowing falling rising floating drifting gentle peaceful still deep vast wild "
    "single lone sacred mystic mystical cosmic starry rainy stormy sunny snowy autumn winter spring summer "
    "morning evening night".split()
)


def subject(query: str) -> str | None:
    """A scene's subject: the first word of its footage search that isn't a describing word
    ("book" in "old book pages"), or the first word if they all are."""
    words = term_list(query)
    nouns = [word for word in words if word not in DESCRIBING]
    return (nouns or words or [None])[0]


# Clips tagged with any of these are skipped unless the search itself names one: a calm lake
# shouldn't come with a dog in it (owner's feedback, 11 Oct), and holiday scenes date a video.
AVOID_TAGS = frozenset(
    _stem(word)
    for word in (
        "animal animals wildlife pet pets dog dogs puppy cat cats kitten bird birds horse cow sheep goat pig "
        "deer fox wolf bear lion tiger zebra elephant giraffe monkey owl eagle duck swan goose pigeon parrot "
        "crow raven magpie elster chicken insect bee butterfly ant spider fish whale dolphin shark snake frog "
        "turtle rabbit squirrel mouse rat "
        "christmas xmas advent santa halloween easter valentine"
    ).split()
)


def score(
    video: StockVideo,
    query: str,
    seconds: float,
    size: tuple[int, int],
    max_upscale: float = 1.0,
    require_subject: bool = True,
) -> float | None:
    """How well a clip suits a shot (higher is better), or None if it can't be used at all: AI
    made, low quality, too short even slowed down, a different shape from the frame (a vertical
    clip in a landscape video would lose most of the picture to cropping), or (with
    `require_subject`) not tagged with the subject, so "zebra herd" never settles for cows."""
    if video.ai_generated or video.low_quality:
        return None
    rendition = best_rendition(video, size, max_upscale)
    if rendition is None or (video.duration - 2 * EDGE_TRIM) * MAX_SLOWDOWN < seconds:
        return None
    if size[0] > size[1] and rendition.width / rendition.height < MIN_LANDSCAPE_RATIO:
        return None
    wanted, tags = _terms(query), {term for tag in video.tags for term in _terms(tag)}
    if tags & AVOID_TAGS and not wanted & AVOID_TAGS:
        return None  # an animal or a holiday the scene didn't ask for
    if require_subject and subject(query) not in tags:
        return None
    relevance = len(wanted & tags) / max(len(wanted), 1)
    sharpness = 1.0 if fill_scale(rendition.width, rendition.height, size) <= max_upscale else 0.0
    popularity = min(math.log10(1 + video.downloads) / 6, 1.0)
    orientation = 1.0 if (rendition.height > rendition.width) == (size[1] > size[0]) else 0.0
    plays_real_time = 1.0 if video.duration - 2 * EDGE_TRIM >= seconds else 0.0
    return 2.0 * relevance + 0.6 * sharpness + 0.4 * popularity + 0.3 * orientation + 0.3 * plays_real_time


def rank(
    videos: Iterable[StockVideo],
    query: str,
    seconds: float,
    size: tuple[int, int],
    *,
    exclude: Iterable[int] = (),
    max_upscale: float = 1.0,
    require_subject: bool = True,
) -> list[tuple[StockVideo, Rendition]]:
    excluded = set(exclude)
    scored = []
    for video in videos:
        if video.id in excluded:
            continue
        value = score(video, query, seconds, size, max_upscale, require_subject)
        if value is not None:
            scored.append((value, video))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    return [(video, best_rendition(video, size, max_upscale)) for _, video in scored]


def clip_window(
    duration: float, seconds: float, start: float | None = None, max_slowdown: float = MAX_SLOWDOWN
) -> tuple[float, float, float]:
    """(source start, source seconds used, slowdown) to fill `seconds` of screen time from a clip
    of `duration`. With no `start`, the middle of the clip is used. A start too close to the end
    (a clip already used up) goes back to the beginning."""
    first, last = EDGE_TRIM, max(duration - EDGE_TRIM, EDGE_TRIM + 0.1)
    if start is not None and last - start < min(1.0, seconds):
        start = first
    begin = first if start is None else max(first, start)
    available = last - begin
    slowdown = min(max(seconds / available, 1.0), max_slowdown)
    span = min(seconds / slowdown, available)
    if start is None:
        begin = first + (available - span) / 2
    return round(begin, 3), round(span, 3), round(slowdown, 5)


class Pixabay:
    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        *,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._key = api_key
        self.cache_dir = Path(cache_dir)
        self.http = http or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(30.0, read=120.0))
        self.clock, self.sleep = clock, sleep

    def search(self, query: str, *, category: str | None = None, per_page: int = 50) -> list[StockVideo]:
        params = {"q": query[:100], "video_type": "film", "safesearch": "true", "order": "popular", "per_page": per_page}
        if category:
            if category not in CATEGORIES:
                raise ValueError(f"Unknown Pixabay category {category!r}")
            params["category"] = category
        digest = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / "search" / f"{digest}.json"
        data = None
        if path.is_file():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if self.clock() - cached.get("fetched_at", 0) < SEARCH_TTL:
                data = cached["data"]
        if data is None:
            data = self._get(params)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": self.clock(), "params": params, "data": data}), encoding="utf-8")
        return [StockVideo.from_api(hit) for hit in data.get("hits", [])]

    def _get(self, params: dict) -> dict:
        for _ in range(3):
            try:
                response = self.http.get(API_URL, params={**params, "key": self._key})
            except httpx.HTTPError as error:  # the message would include the URL, and with it the key
                raise StockError(f"Pixabay search failed: {type(error).__name__}") from None
            if response.status_code == 429:
                self.sleep(min(float(response.headers.get("X-RateLimit-Reset") or 60), 60.0))
                continue
            if response.status_code != 200:
                raise StockError(f"Pixabay search failed ({response.status_code}): {response.text[:200]}")
            return response.json()
        raise StockError("Pixabay rate limit still exceeded after waiting")

    def preview(self, video: StockVideo) -> bytes | None:
        """The clip's preview still (JPEG), cached; None if Pixabay has none."""
        url = video.preview_url
        if not url:
            return None
        path = self.cache_dir / "previews" / f"{video.id}.jpg"
        if path.is_file() and path.stat().st_size:
            return path.read_bytes()
        try:
            response = self.http.get(url, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith("image"):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return response.content

    def download(self, video: StockVideo, rendition: Rendition) -> Path:
        dest = self.cache_dir / "clips" / f"{video.id}-{rendition.name}.mp4"
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        try:
            with self.http.stream("GET", rendition.url, follow_redirects=True) as response:
                if response.status_code != 200:
                    raise StockError(f"Clip {video.id} download failed ({response.status_code})")
                with part.open("wb") as handle:
                    for block in response.iter_bytes(1 << 20):
                        handle.write(block)
        except httpx.HTTPError as error:
            part.unlink(missing_ok=True)
            raise StockError(f"Clip {video.id} download failed: {type(error).__name__}") from None
        part.replace(dest)
        return dest
