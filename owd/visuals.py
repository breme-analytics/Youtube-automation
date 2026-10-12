"""Picking the pictures for each scene, so they show what George is saying at that moment.

For every scene: rank the stock clips for its footage search, let a free vision model score the best
few against the scene's narration, and keep the clips that fit (up to three, best first). A scene
that runs for several shots moves through those fitting clips, so it never wanders off to footage
about something else. If no clip fits, the scene gets a painting of the moment (`scene.image`,
owd.images); if no painting can be made, the closest clip is used and flagged for review.

When a scene's own search finds nothing usable, broader searches are tried: each word of the
search on its own, then the channel's fallback searches (channel.toml [footage] fallback), and
the vision model still decides whether any of them fits the words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from owd.config import VideoFormat
from owd.images import ImageError, SceneImages
from owd.stock import DESCRIBING, Pixabay, Rendition, StockVideo, rank, term_list
from owd.storyboard import Scene
from owd.vision import GOOD_ENOUGH, VisionJudge, thumbnail_bytes

CANDIDATES = 4  # clips shown to the vision model per scene
KEEP = 3  # fitting clips kept per scene, for scenes longer than one clip
DEFAULT_FALLBACKS = ("candle flame", "ink water", "book pages", "fog forest", "galaxy stars", "sunrise mountains")


@dataclass
class Visual:
    kind: str  # "clip" | "image" | "none"
    clips: list[tuple[StockVideo, Rendition]] = field(default_factory=list)  # best first
    image_path: object | None = None
    image_provider: str = ""
    score: int | None = None  # the vision model's score for the best clip (None: not judged)
    note: str = ""

    @property
    def clip(self) -> tuple[StockVideo, Rendition] | None:
        return self.clips[0] if self.clips else None


@dataclass
class Casting:
    visuals: list[Visual]
    warnings: list[str] = field(default_factory=list)
    vision_calls: int = 0
    images_made: int = 0


def _searches(scene: Scene, fallbacks: Sequence[str]) -> list[tuple[str, str | None]]:
    """(query, category) to try for a scene, most specific first."""
    tries: list[tuple[str, str | None]] = []
    if scene.category:
        tries.append((scene.visual, scene.category))
    tries.append((scene.visual, None))
    words = [w for w in term_list(scene.visual) if w not in DESCRIBING]
    tries += [(word, None) for word in words[1:]]  # "quill writing" -> "writing"
    tries += [(query, None) for query in fallbacks if query != scene.visual]
    return tries


def _pool(scene: Scene, stock: Pixabay, fmt: VideoFormat, seconds: float, max_upscale: float,
          exclude: set[int], fallbacks: Sequence[str]) -> list[tuple[StockVideo, Rendition]]:
    pool: list[tuple[StockVideo, Rendition]] = []
    seen: set[int] = set()
    for query, category in _searches(scene, fallbacks):
        ranked = rank(stock.search(query, category=category), query, seconds, fmt.size, exclude=exclude | seen,
                      max_upscale=max_upscale)
        for item in ranked:
            pool.append(item)
            seen.add(item[0].id)
        if len(pool) >= CANDIDATES:
            break
    return pool


def choose_visuals(
    scenes: Sequence[Scene],
    seconds_per_scene: Sequence[float],
    stock: Pixabay,
    fmt: VideoFormat,
    *,
    judge: VisionJudge | None,
    images: SceneImages | None,
    max_upscale: float = 1.0,
    fallbacks: Sequence[str] = DEFAULT_FALLBACKS,
    log: Callable[[str], None] = print,
) -> Casting:
    """One Visual per scene. `seconds_per_scene` is how long each scene is on screen."""
    visuals: list[Visual] = []
    warnings: list[str] = []
    used: set[int] = set()
    made = 0
    for index, (scene, seconds) in enumerate(zip(scenes, seconds_per_scene)):
        shortest_shot = min(seconds, 4.0)
        pool = _pool(scene, stock, fmt, shortest_shot, max_upscale, used, fallbacks)
        visual: Visual | None = None
        closest: Visual | None = None
        if pool and judge is not None and judge.enabled:
            candidates, stills = [], []
            for video, rendition in pool[: CANDIDATES * 2]:
                still = stock.preview(video)
                if still:
                    candidates.append((video, rendition))
                    stills.append(thumbnail_bytes(still))
                if len(candidates) == CANDIDATES:
                    break
            verdict = judge.judge(scene.text, scene.visual, stills) if stills else None
            if verdict is not None:
                ranked = verdict.ranked(GOOD_ENOUGH)
                if ranked:
                    visual = Visual("clip", [candidates[i] for i in ranked[:KEEP]], score=verdict.scores[ranked[0]],
                                    note=verdict.reason)
                else:
                    log(f"  scene {index + 1}: no clip fits {scene.visual!r} (best {max(verdict.scores)}/10)")
                    best = max(range(len(verdict.scores)), key=lambda i: verdict.scores[i])
                    closest = Visual("clip", [candidates[best]], score=verdict.scores[best], note="closest match")
            elif pool:
                visual = Visual("clip", pool[:KEEP], note="vision check unavailable: best tag matches")
        elif pool:
            visual = Visual("clip", pool[:KEEP])  # no vision model configured: best tag matches
        if visual is None and scene.image and images is not None and images.available:
            try:
                generated = images.generate(scene.image, seed=index)
                visual = Visual("image", image_path=generated.path, image_provider=generated.provider)
                made += 1
            except ImageError as error:
                warnings.append(f"Scene {index + 1}: no painting ({error})")
        elif visual is None and scene.image and images is not None:
            warnings.append(f"Scene {index + 1}: no painting ({images.reason})")
        if visual is None and closest is not None:
            visual = closest
            warnings.append(f"Scene {index + 1}: no clip matched the narration well ({closest.score}/10) and no "
                            f"painting was available; used the closest clip for {scene.visual!r}")
        if visual is None and pool:
            visual = Visual("clip", pool[:1], note="fallback: best tag match")
            warnings.append(f"Scene {index + 1}: used the best tag match for {scene.visual!r} unchecked")
        if visual is None:
            visual = Visual("none")
            warnings.append(f"Scene {index + 1}: nothing to show for {scene.visual!r}; used a plain background")
        used.update(video.id for video, _ in visual.clips)
        visuals.append(visual)
    calls = judge.calls if judge is not None else 0
    return Casting(visuals, warnings, calls, made)
