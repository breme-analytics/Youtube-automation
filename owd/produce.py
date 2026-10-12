"""From storyboard to finished files: video, captions, thumbnail and the text for YouTube.

    storyboard -> quote check -> narration -> narration check -> shot plan -> stock footage
    -> long videos: chapters (crossfades inside, a dip through black between) + quote and
       chapter cards; Shorts: one strip with word-by-word captions
    -> thumbnail -> metadata.json + review.md (what the owner checks before posting)
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Sequence

import numpy as np

from owd.backgrounds import glow_background
from owd.captions import long_caption_style_line, long_captions_events, shorts_ass, srt
from owd.config import LONG, SAMPLE_RATE, SHORT, VideoFormat
from owd.images import SceneImages
from owd.overlays import ChapterCard, QuoteCard, card_windows, overlays_ass
from owd.qa import compare, transcribe
from owd.quotes import check_quotes, quotes_in
from owd.render import GENTLE, MOTIONS, assemble, finish, grab_frame, join_shots, render_clip, render_scene
from owd.stock import EDGE_TRIM, MAX_SLOWDOWN, Pixabay, StockVideo, clip_window
from owd.storyboard import Storyboard
from owd.thumbnail import make_thumbnail
from owd.timeline import chapter_shots, plan_shots, shot_lengths
from owd.tts import PARAGRAPH_PAUSE, Cast, Kokoro, Narration, plan_chunks
from owd.vision import VisionJudge
from owd.visuals import DEFAULT_FALLBACKS, choose_visuals

MAX_SHOT = {"short": 5.5, "long": 9.0}
FADE = {"short": 0.5, "long": 0.8}
DIP = 0.35  # seconds of fade to and from black at each chapter boundary (long videos)
MAX_WORD_ERROR_RATE = 0.03  # above this the narration is flagged for a listen before posting
DESCRIPTION_LIMIT = 4900  # YouTube allows 5,000 characters
AI_NOTE = ("Narrated with an AI voice. Script written with AI help and reviewed by a human. "
           "Some illustrations are AI-generated paintings.")


@dataclass
class Production:
    folder: Path
    video: Path
    thumbnail: Path
    captions: Path
    metadata: Path
    review: Path
    warnings: list[str] = field(default_factory=list)


def narrate(storyboard: Storyboard, cast: Cast, kokoro: Kokoro) -> tuple[Narration, list[tuple[int, int]]]:
    """The whole narration, plus each scene's (first, last + 1) word index. Quotes are numbered in
    script order, so each quote's words can be found again for its on-screen card."""
    parts: list[np.ndarray] = []
    words = []
    spans = []
    clock = 0.0
    quotes_so_far = 0
    for index, scene in enumerate(storyboard.scenes):
        chunks = plan_chunks(scene.text, first_quote=quotes_so_far + 1)
        quotes_so_far = max([quotes_so_far, *(chunk.quote for chunk in chunks)])
        if index < len(storyboard.scenes) - 1:
            chunks[-1] = replace(chunks[-1], pause_after=PARAGRAPH_PAUSE)
        scene_parts, scene_words = kokoro.synthesize_chunks(chunks, cast, offset=clock)
        if not scene_words:
            raise ValueError(f"Scene {index + 1} produced no words")
        spans.append((len(words), len(words) + len(scene_words)))
        words.extend(scene_words)
        parts.extend(scene_parts)
        clock += sum(len(part) for part in scene_parts) / SAMPLE_RATE
    return Narration(np.concatenate(parts), words, cast), spans


def next_clip(visual, cursor: dict[int, float], seconds: float):
    """The footage for a scene's next shot: the first of the scene's fitting clips that still has
    enough unseen material for `seconds`, from where this video left off in it; if none has, the
    best clip again from its beginning. Returns (video, rendition, start)."""
    for video, rendition in visual.clips:
        start = cursor.get(video.id, EDGE_TRIM)
        if (video.duration - EDGE_TRIM - start) * MAX_SLOWDOWN >= seconds:
            return video, rendition, start
    video, rendition = visual.clips[0]
    return video, rendition, EDGE_TRIM


def check_lengths(clips: list[Path], planned: list[float], fps: int = 30) -> None:
    """Every chapter's picture must be exactly as long as planned, or the pictures would drift away
    from the narration (and the video would end on a frozen frame). Stops the run if not."""
    from owd.ffmpeg import duration as media_duration

    for index, (clip, seconds) in enumerate(zip(clips, planned)):
        actual = media_duration(clip)
        if abs(actual - seconds) > 1.5 / fps:
            raise RuntimeError(f"Chapter {index + 1}'s picture is {actual:.2f}s long instead of {seconds:.2f}s; "
                               "the video would drift out of sync, so it was not finished")


def chapter_of_scenes(storyboard: Storyboard) -> tuple[list[int], list[str]]:
    """Each scene's chapter index, and the chapter titles. Scenes before the first titled chapter
    form an untitled opening chapter."""
    indexes, titles = [], []
    for scene in storyboard.scenes:
        if scene.chapter or not titles:
            titles.append(scene.chapter or "Intro")
        indexes.append(len(titles) - 1)
    return indexes, titles


def timestamp(seconds: float) -> str:
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def quote_cards(storyboard: Storyboard, narration: Narration) -> list[QuoteCard]:
    """One card per quote, timed to when the narrator reads it."""
    texts = quotes_in(storyboard)
    author = storyboard.sources[0].cite if storyboard.sources else ""
    cards = []
    for number, text in enumerate(texts, start=1):
        spoken = [word for word in narration.words if word.quote == number]
        if spoken:
            cards.append(QuoteCard(text, spoken[0].start, spoken[-1].end, author))
    return cards


def describe(
    storyboard: Storyboard, chapters: list[tuple[float, str]], credits: list[str], limit: int = DESCRIPTION_LIMIT
) -> str:
    """The YouTube description: summary, chapters (YouTube turns 0:00-style lines into chapters),
    books, research links, AI note and footage credits, kept under YouTube's length limit."""
    lines = [storyboard.description] if storyboard.description else []
    if storyboard.format == "long" and len(chapters) >= 3:
        lines += ["", "Chapters", *(f"{timestamp(start)} {title}" for start, title in chapters)]
    if storyboard.sources:
        lines += ["", "Quoted from (public domain):", *(f"- {source.cite}" for source in storyboard.sources)]
    if storyboard.research:
        lines += ["", "Research mentioned:", *(f"- {item.title}: {item.link}" for item in storyboard.research)]
    lines += ["", AI_NOTE]
    names = list(dict.fromkeys(credit.split(" on Pixabay")[0] for credit in credits))
    footer = ["", "#Shorts"] if storyboard.format == "short" else []
    text = "\n".join(lines)
    if names:
        budget = limit - len(text) - len("\n".join(footer)) - 80
        shown: list[str] = []
        for name in names:
            if len(", ".join([*shown, name])) > budget:
                break
            shown.append(name)
        rest = len(names) - len(shown)
        credit_line = "Footage from Pixabay by " + ", ".join(shown) + (f" and {rest} others" if rest else "") + "."
        text += "\n" + credit_line
    if footer:
        text += "\n" + "\n".join(footer)
    return text.strip()


def review_text(
    storyboard: Storyboard, duration: float, heard, warnings: list[str], quotes: list[QuoteCard]
) -> str:
    lines = [f"# Review before posting: {storyboard.title}", "", f"Length: {timestamp(duration)}", "",
             "- [ ] Watch the whole video (picture, sound, quote cards, chapter titles)",
             "- [ ] Check every claim below is true",
             "- [ ] Pick the title, then upload video.mp4, thumbnail.jpg and captions.srt (Subtitles > Upload file)",
             "- [ ] In YouTube Studio, paste the description from metadata.json and set Altered content to "
             "'Yes' if asked about realistic AI content (the voice is AI; nothing else is realistic AI)",
             "", "## Title options", f"1. {storyboard.title} (chosen)"]
    lines += [f"{i}. {title}" for i, title in enumerate(storyboard.alt_titles, start=2)]
    lines += ["", f"Thumbnail text: {storyboard.thumbnail_text}", "", "## Claims to check"]
    lines += [f"- {claim.claim} (basis: {claim.basis})" for claim in storyboard.claims] or ["- (none listed)"]
    if storyboard.research:
        lines += ["", "## Research used"] + [f"- {r.id}: {r.title} {r.link}" for r in storyboard.research]
    lines += ["", "## Quotes (each checked word for word against the source)"]
    lines += [f"- {timestamp(card.start)} \"{card.text}\"" for card in quotes] or ["- (none)"]
    lines += ["", f"## Narration check: {heard.errors} differences in {heard.reference_words} words"]
    lines += [f"- script {a!r} / heard {b!r}" for a, b in heard.differences[:20]]
    if warnings:
        lines += ["", "## Warnings"] + [f"- {warning}" for warning in warnings]
    return "\n".join(lines) + "\n"


def produce(
    storyboard: Storyboard,
    folder: Path,
    *,
    cast: Cast = Cast(),
    stock: Pixabay,
    kokoro: Kokoro | None = None,
    judge: VisionJudge | None = None,
    images: SceneImages | None = None,
    burn_captions: bool = True,
    fallbacks: Sequence[str] = DEFAULT_FALLBACKS,
    max_upscale: float = 1.0,
    log=print,
) -> Production:
    problems = check_quotes(storyboard)
    if problems:
        raise ValueError("Quote check failed: " + "; ".join(problems))
    long_form = storyboard.format == "long"
    fmt: VideoFormat = LONG if long_form else SHORT
    folder = Path(folder)
    work = folder / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    warnings: list[str] = []

    started = time.perf_counter()
    narration, spans = narrate(storyboard, cast, kokoro or Kokoro())
    narration.save(work / "narration.wav", work / "words.json")
    log(f"narration: {narration.duration:.1f}s, {len(narration.words)} words, {len(spans)} scenes "
        f"({time.perf_counter() - started:.0f}s)")

    started = time.perf_counter()
    heard = compare(storyboard.script, transcribe(work / "narration.wav"))
    log(f"narration check: {heard.errors} word differences in {heard.reference_words} "
        f"({time.perf_counter() - started:.0f}s)")
    if heard.word_error_rate > MAX_WORD_ERROR_RATE:
        warnings.append(f"Narration check heard {heard.errors} differences: {heard.differences[:8]}")

    fade, max_shot = FADE[storyboard.format], MAX_SHOT[storyboard.format]
    cuts, shot_scenes = plan_shots(narration.words, spans, narration.duration, max_shot)
    scene_chapter, chapter_titles = chapter_of_scenes(storyboard)
    if long_form:
        plan = chapter_shots(cuts, shot_scenes, scene_chapter, narration.duration, fade)
        lengths = [length for _, _, chapter_lengths in plan for length in chapter_lengths]
    else:
        plan = []
        lengths = shot_lengths(cuts, narration.duration, fade)

    started = time.perf_counter()
    scene_seconds = [0.0] * len(storyboard.scenes)
    for scene_index, seconds in zip(shot_scenes, lengths):
        scene_seconds[scene_index] += seconds
    casting = choose_visuals(storyboard.scenes, scene_seconds, stock, fmt, judge=judge, images=images,
                             max_upscale=max_upscale, fallbacks=fallbacks, log=log)
    warnings += casting.warnings
    shots: list[Path] = []
    credits: list[str] = []
    painted: list[str] = []
    cursor: dict[int, float] = {}  # how far into each clip this video has used, in source seconds
    first_clip: tuple[Path, StockVideo] | None = None
    first_image: Path | None = None
    for index, (scene_index, seconds) in enumerate(zip(shot_scenes, lengths)):
        scene, visual = storyboard.scenes[scene_index], casting.visuals[scene_index]
        out = work / f"shot-{index:03d}.mp4"
        if visual.kind == "clip":
            video, rendition, start = next_clip(visual, cursor, seconds)
            clip = stock.download(video, rendition)
            begin, span, _ = clip_window(video.duration, seconds, start)
            cursor[video.id] = begin + span
            shots.append(render_clip(clip, out, seconds=seconds, size=fmt.size, start=begin))
            credits.append(video.credit)
            first_clip = first_clip or (clip, video)
            judged = f"vision {visual.score}/10" if visual.score is not None else "tags only"
            log(f"  shot {index + 1}/{len(lengths)} {seconds:4.1f}s  scene {scene_index + 1} {scene.visual!r} -> "
                f"clip #{video.id} at {begin:.1f}s ({judged})")
        elif visual.kind == "image":
            motion = GENTLE[index % len(GENTLE)] if long_form else MOTIONS[index % len(MOTIONS)]
            shots.append(render_scene(Path(visual.image_path), out, seconds=seconds, size=fmt.size, motion=motion))
            painted.append(visual.image_provider)
            first_image = first_image or Path(visual.image_path)
            log(f"  shot {index + 1}/{len(lengths)} {seconds:4.1f}s  scene {scene_index + 1} painting ({visual.image_provider})")
        else:
            still = work / f"still-{index:03d}.png"
            glow_background(fmt.size, seed=index).save(still)
            shots.append(render_scene(still, out, seconds=seconds, size=fmt.size))
    log(f"pictures: {len(shots)} shots; {len(cursor)} clips, {casting.images_made} paintings; "
        f"{casting.vision_calls} vision checks ({time.perf_counter() - started:.0f}s)")

    captions_path = folder / "captions.srt"
    captions_path.write_text(srt(narration.words), encoding="utf-8")
    cards = quote_cards(storyboard, narration)
    started = time.perf_counter()
    if long_form:
        chapters = [(start, chapter_titles[i]) for i, (start, _, _) in enumerate(plan)]
        chapter_cards = [ChapterCard(i, title, start) for i, (start, title) in enumerate(chapters) if i > 0]
        burned_captions = (long_captions_events(narration.words, hidden=card_windows(cards, chapter_cards))
                           if burn_captions else [])
        overlay_file = work / "overlays.ass"
        overlay_file.write_text(
            overlays_ass(cards, chapter_cards, captions=burned_captions,
                         caption_style=long_caption_style_line() if burn_captions else None),
            encoding="utf-8",
        )
        pictures, taken = [], 0
        for index, (_, _, chapter_lengths) in enumerate(plan):
            count = len(chapter_lengths)
            pictures.append(join_shots(shots[taken : taken + count], chapter_lengths, work / f"chapter-{index:02d}.mp4",
                                       fade=fade, dip_in=DIP if index > 0 else 0.0,
                                       dip_out=DIP if index < len(plan) - 1 else 0.0))
            taken += count
        check_lengths(pictures, [end - start for start, end, _ in plan])
        video_path = finish(pictures, work / "narration.wav", folder / "video.mp4", overlays=overlay_file)
    else:
        chapters = []
        burned = work / "captions.ass"
        burned.write_text(shorts_ass(narration.words), encoding="utf-8")
        video_path = assemble(shots, lengths, work / "narration.wav", folder / "video.mp4", captions=burned, fade=fade)
    log(f"video: {video_path} ({time.perf_counter() - started:.0f}s)")

    background = None
    if first_clip:
        background = grab_frame(first_clip[0], work / "thumbnail-frame.png", at=first_clip[1].duration / 3)
    elif first_image is not None:
        background = first_image
    thumbnail = make_thumbnail(storyboard.thumbnail_text or storyboard.title, folder / "thumbnail.jpg",
                               background=background, accent=storyboard.thumbnail_accent)

    metadata = folder / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "title": storyboard.title,
                "alt_titles": list(storyboard.alt_titles),
                "description": describe(storyboard, chapters, credits),
                "chapters": [{"start": round(start, 2), "title": title} for start, title in chapters],
                "format": storyboard.format,
                "duration": round(narration.duration, 2),
                "category": "Education",
                "made_for_kids": False,
                "cast": asdict(cast),
                "claims": [asdict(claim) for claim in storyboard.claims],
                "research": [asdict(item) for item in storyboard.research],
                "narration_check": {"errors": heard.errors, "words": heard.reference_words,
                                    "differences": heard.differences},
                "credits": list(dict.fromkeys(credits)),
                "warnings": warnings,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review = folder / "review.md"
    review.write_text(review_text(storyboard, narration.duration, heard, warnings, cards), encoding="utf-8")
    return Production(folder, video_path, thumbnail, captions_path, metadata, review, warnings)
