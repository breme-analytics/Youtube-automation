"""Where to cut between shots, and how long each shot runs so its crossfade lands on the cut."""

from __future__ import annotations

import math
import re
from typing import Sequence

from owd.config import FPS
from owd.words import Word

_SENTENCE_END = re.compile(r"[.!?…][\"”’')\]]*$")


def choose_cuts(
    words: Sequence[Word], count: int, min_shot: float = 1.5, start: float = 0.0, end: float | None = None
) -> list[float]:
    """Up to `count - 1` cut times that split the window `start`..`end` (default: 0 to the last
    word's end) into shots of similar length. Each cut sits in the pause between two words; a
    sentence end within about a quarter of a shot's length of the ideal spot is preferred."""
    if count < 2 or len(words) < 2:
        return []
    end = words[-1].end if end is None else end
    total = end - start
    window = 0.25 * total / count
    gaps = [
        ((before.end + after.start) / 2, bool(_SENTENCE_END.search(before.text)))
        for before, after in zip(words, words[1:])
    ]
    cuts: list[float] = []
    previous = start
    for k in range(1, count):
        target = start + total * k / count
        options = [g for g in gaps if g[0] - previous >= min_shot and end - g[0] >= min_shot]
        if not options:
            break
        time, _ = min(options, key=lambda g: abs(g[0] - target) - (window if g[1] else 0.0))
        cuts.append(round(time, 3))
        previous = time
    return cuts


def snap_fade(fade: float, fps: int = FPS) -> float:
    """A crossfade of an even number of frames (at least two), so half of it is whole frames."""
    return max(2, 2 * round(fade * fps / 2)) / fps


def shot_lengths(cuts: Sequence[float], total: float, fade: float, fps: int = FPS) -> list[float]:
    """Shot durations for render.assemble: crossfades centred on the cuts, the last shot ending at
    `total`. Adjacent shots overlap by the fade, so the lengths add up to total + fade per cut.

    Everything is counted in whole frames from the cut times themselves, so rounding never builds
    up: the hundredth crossfade is as close to its cut as the first."""
    half = round(snap_fade(fade, fps) * fps / 2)
    bounds = [0, *(round(cut * fps) for cut in cuts), round(total * fps)]
    count = len(bounds) - 1
    lengths = []
    for index in range(count):
        frames = bounds[index + 1] - bounds[index] + (half if index > 0 else 0) + (half if index < count - 1 else 0)
        lengths.append(frames / fps)
    return lengths


def scene_bounds(words: Sequence[Word], scene_spans: Sequence[tuple[int, int]], total: float) -> list[float]:
    """[0, boundary 1, ..., total]: each scene boundary sits in the pause between the scenes."""
    bounds = [0.0]
    for (_, end), (start, _) in zip(scene_spans, scene_spans[1:]):
        bounds.append(round((words[end - 1].end + words[start].start) / 2, 3))
    bounds.append(total)
    return bounds


def plan_shots(
    words: Sequence[Word],
    scene_spans: Sequence[tuple[int, int]],
    total: float,
    max_shot: float,
    min_shot: float = 1.5,
) -> tuple[list[float], list[int]]:
    """Cut times for the whole video, and the scene each shot belongs to.

    Every scene change is a cut, placed in the pause between the scenes. A scene longer than
    `max_shot` is split into several shots of similar length, cut between words.
    `scene_spans` gives each scene's (first, last + 1) word index.
    """
    bounds = scene_bounds(words, scene_spans, total)
    cuts: list[float] = []
    scenes: list[int] = []
    for index, (first, last) in enumerate(scene_spans):
        begin, finish = bounds[index], bounds[index + 1]
        count = max(1, math.ceil((finish - begin) / max_shot))
        inner = choose_cuts(words[first:last], count, min_shot, start=begin, end=finish) if count > 1 else []
        if index > 0:
            cuts.append(begin)
        cuts.extend(inner)
        scenes.extend([index] * (len(inner) + 1))
    return cuts, scenes


def chapter_shots(
    cuts: Sequence[float],
    shot_scenes: Sequence[int],
    chapter_of_scene: Sequence[int],
    total: float,
    fade: float,
    fps: int = FPS,
) -> list[tuple[float, float, list[float]]]:
    """Per chapter: (start, end, shot lengths). Inside a chapter adjacent shots crossfade (each
    fade centred on its cut); a chapter starts and ends exactly on its boundary, so chapters can
    be joined end to end. All times are whole frames counted from the cut times themselves, so
    the chapters add up exactly to the whole video."""
    chapters: list[list[int]] = []
    for shot, scene in enumerate(shot_scenes):
        if not chapters or chapter_of_scene[scene] != chapter_of_scene[shot_scenes[chapters[-1][0]]]:
            chapters.append([])
        chapters[-1].append(shot)
    frames = [0, *(round(cut * fps) for cut in cuts), round(total * fps)]  # frames[k]: start of shot k
    result = []
    for shots in chapters:
        first, last = shots[0], shots[-1]
        start_f, end_f = frames[first], frames[last + 1]
        inner = [(frames[k] - start_f) / fps for k in range(first + 1, last + 1)]
        lengths = shot_lengths(inner, (end_f - start_f) / fps, fade, fps)
        result.append((start_f / fps, end_f / fps, lengths))
    return result