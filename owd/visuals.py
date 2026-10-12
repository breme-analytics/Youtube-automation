"""Picking the picture for each scene, so it shows what George is saying at that moment.

For every scene: rank the stock clips for its footage search, let a free vision model score the best
few against the scene's narration, and use the best clip if it scores well enough. Otherwise use a
painting of the moment from `scene.image` (owd.images). A scene that runs for several shots stays
on its one chosen picture (another part of the same clip, or the same painting), so the picture
doesn't wander away from the words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from owd.config import VideoFormat
from owd.images import ImageError, SceneImages
from owd.stock import Pixabay, Rendition, StockVideo, rank
from owd.storyboard import Scene
from owd.vision import GOOD_ENOUGH, VisionJudge, thumbnail_bytes

CANDIDATES = 4  # clips shown to the vision model per scene


@dataclass
class Visual:
    kind: str  # "clip" | "image" | "none"
    clip: tuple[StockVideo, Rendition] | None = None
    image_path: object | None = None
    image_provider: str = ""
    score: int | None = None  # the vision model's score for the chosen clip (None: not judged)
    note: str = ""


@dataclass
class Casting:
    visuals: list[Visual]
    warnings: list[str] = field(default_factory=list)
    vision_calls: int = 0
    images_made: int = 0


def _pool(scene: Scene, stock: Pixabay, fmt: VideoFormat, seconds: float, max_upscale: float,
          exclude: set[int]) -> list[tuple[StockVideo, Rendition]]:
    searches = [scene.category, None] if scene.category else [None]
    found: dict[int, StockVideo] = {}
    pool: list[tuple[StockVideo, Rendition]] = []
    for category in searches:
        for video in stock.search(scene.visual, category=category):
            found.setdefault(video.id, video)
        pool = rank(found.values(), scene.visual, seconds, fmt.size, exclude=exclude, max_upscale=max_upscale)
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
    log: Callable[[str], None] = print,
) -> Casting:
    """One Visual per scene. `seconds_per_scene` is how long each scene is on screen."""
    visuals: list[Visual] = []
    warnings: list[str] = []
    used: set[int] = set()
    made = 0
    for index, (scene, seconds) in enumerate(zip(scenes, seconds_per_scene)):
        shortest_shot = min(seconds, 4.0)
        pool = _pool(scene, stock, fmt, shortest_shot, max_upscale, used)
        visual: Visual | None = None
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
                    best = ranked[0]
                    visual = Visual("clip", candidates[best], score=verdict.scores[best], note=verdict.reason)
                else:
                    log(f"  scene {index + 1}: no clip fits {scene.visual!r} (best {max(verdict.scores)}/10)")
        elif pool:
            visual = Visual("clip", pool[0])  # no vision model available: best tag match
        if visual is None and scene.image and images is not None:
            try:
                generated = images.generate(scene.image, seed=index)
                visual = Visual("image", image_path=generated.path, image_provider=generated.provider)
                made += 1
            except ImageError as error:
                warnings.append(f"Scene {index + 1}: no painting ({error})")
        if visual is None and pool:
            visual = Visual("clip", pool[0], note="fallback: best tag match")
            warnings.append(f"Scene {index + 1}: no clip matched the narration and no painting was available; "
                            f"used the best tag match for {scene.visual!r}")
        if visual is None:
            visual = Visual("none")
            warnings.append(f"Scene {index + 1}: nothing to show for {scene.visual!r}; used a plain background")
        if visual.clip:
            used.add(visual.clip[0].id)
        visuals.append(visual)
    calls = judge.calls if judge is not None else 0
    return Casting(visuals, warnings, calls, made)
