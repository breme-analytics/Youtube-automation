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

import numpy as np

from owd.backgrounds import glow_background
from owd.captions import shorts_ass, srt
from owd.config import LONG, SAMPLE_RATE, SHORT, VideoFormat
from owd.overlays import ChapterCard, QuoteCard, overlays_ass
from owd.qa import compare, transcribe
from owd.quotes import check_quotes, quotes_in
from owd.render import assemble, finish, grab_frame, join_shots, render_clip, render_scene
from owd.stock import EDGE_TRIM, Pixabay, Rendition, StockVideo, clip_window, rank, subject
from owd.storyboard import Scene, Storyboard
from owd.thumbnail import make_thumbnail
from owd.timeline import chapter_shots, plan_shots, shot_lengths
from owd.tts import PARAGRAPH_PAUSE, Cast, Kokoro, Narration, plan_chunks

MAX_SHOT = {"short": 5.5, "long": 7.0}
FADE = {"short": 0.5, "long": 0.8}
DIP = 0.35  # seconds of fade to and from black at each chapter boundary (long videos)
MAX_WORD_ERROR_RATE = 0.03  # above this the narration is flagged for a listen before posting
DESCRIPTION_LIMIT = 4900  # YouTube allows 5,000 characters
AI_NOTE = "Narrated with an AI voice. Script written with AI help and reviewed by a human."


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


def _footage_pool(
    scene: Scene, stock: Pixabay, fmt: VideoFormat, seconds: float, max_upscale: float, warnings: list[str]
) -> list[tuple[StockVideo, Rendition]]:
    """Clips for one scene, best first. Only clips tagged with the scene's subject count, searched
    in the scene's category first and then in all of Pixabay. If none exist, the best partial
    matches are used and the video is flagged for a look before posting."""
    searches = [scene.category, None] if scene.category else [None]
    found: dict[int, StockVideo] = {}
    pool: list[tuple[StockVideo, Rendition]] = []
    for category in searches:
        for video in stock.search(scene.visual, category=category):
            found.setdefault(video.id, video)
        pool = rank(found.values(), scene.visual, seconds, fmt.size, max_upscale=max_upscale)
        if len(pool) >= 3:
            return pool
    if pool:
        return pool
    pool = rank(found.values(), scene.visual, seconds, fmt.size, max_upscale=max_upscale, require_subject=False)
    if pool:
        warnings.append(f"No footage tagged {subject(scene.visual)!r} for {scene.visual!r}: used the closest matches")
    else:
        warnings.append(f"No usable footage for {scene.visual!r}: used a generated background")
    return pool


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
    pools = [_footage_pool(scene, stock, fmt, min(max_shot, 4.0), max_upscale, warnings) for scene in storyboard.scenes]
    shots: list[Path] = []
    credits: list[str] = []
    cursor: dict[int, float] = {}  # how far into each clip this video has used, in source seconds
    first_clip: tuple[Path, StockVideo] | None = None
    for index, (scene_index, seconds) in enumerate(zip(shot_scenes, lengths)):
        scene, pool = storyboard.scenes[scene_index], pools[scene_index]
        out = work / f"shot-{index:03d}.mp4"
        choice = next((item for item in pool if item[0].id not in cursor), None)
        if choice is None and pool:  # every clip used once: show an unseen part of the longest-lasting one
            choice = max(pool, key=lambda item: item[0].duration - cursor[item[0].id])
        if choice is None:
            still = work / f"still-{index:03d}.png"
            glow_background(fmt.size, seed=index).save(still)
            shots.append(render_scene(still, out, seconds=seconds, size=fmt.size))
            continue
        video, rendition = choice
        clip = stock.download(video, rendition)
        begin, span, _ = clip_window(video.duration, seconds, cursor.get(video.id, EDGE_TRIM))
        cursor[video.id] = begin + span
        shots.append(render_clip(clip, out, seconds=seconds, size=fmt.size, start=begin))
        credits.append(video.credit)
        first_clip = first_clip or (clip, video)
        log(f"  shot {index + 1}/{len(lengths)} {seconds:4.1f}s  {scene.visual!r} -> #{video.id} at {begin:.1f}s "
            f"{rendition.width}x{rendition.height} ({', '.join(video.tags[:3])})")
    log(f"footage: {len(shots)} shots from {len(cursor)} clips ({time.perf_counter() - started:.0f}s)")

    captions_path = folder / "captions.srt"
    captions_path.write_text(srt(narration.words), encoding="utf-8")
    cards = quote_cards(storyboard, narration)
    started = time.perf_counter()
    if long_form:
        chapters = [(start, chapter_titles[i]) for i, (start, _, _) in enumerate(plan)]
        overlay_file = work / "overlays.ass"
        overlay_file.write_text(
            overlays_ass(cards, [ChapterCard(i, title, start) for i, (start, title) in enumerate(chapters) if i > 0]),
            encoding="utf-8",
        )
        pictures, taken = [], 0
        for index, (_, _, chapter_lengths) in enumerate(plan):
            count = len(chapter_lengths)
            pictures.append(join_shots(shots[taken : taken + count], chapter_lengths, work / f"chapter-{index:02d}.mp4",
                                       fade=fade, dip_in=DIP if index > 0 else 0.0,
                                       dip_out=DIP if index < len(plan) - 1 else 0.0))
            taken += count
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
