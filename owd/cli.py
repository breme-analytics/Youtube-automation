"""Command line: python -m owd voices | demo"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

from owd.config import OUTPUT_DIR, SAMPLE_RATE, SHORT

# Original narration. The quoted line is checked against Project Gutenberg #4507 (As a Man
# Thinketh, 1903), where it reads "Man is made or unmade by himself; in the armoury of thought
# he forges the weapons by which he destroys himself"; the second sentence here paraphrases it.
SAMPLE_SCRIPT = """\
In 1903, a quiet English writer named James Allen wrote a line that sounds like a fridge magnet: \
"Man is made or unmade by himself." Cute, right? Keep reading, and it gets darker.

He says that in the armoury of thought, we forge the very weapons that destroy us. Modern \
psychologists have a name for that loop. They call it rumination. So, does a century-old idea \
survive modern science? Let's test it."""

SAMPLE_VOICES = [
    ("af_heart", "American female, warm (Kokoro's best-graded voice)"),
    ("bf_emma", "British female, calm"),
    ("am_michael", "American male, steady"),
    ("bm_george", "British male, storyteller"),
]
NUMBER_WORDS = ["one", "two", "three", "four", "five", "six"]


def cmd_voices(args: argparse.Namespace) -> None:
    """Read the same paragraph in each sample voice, normalised to the same loudness."""
    import soundfile

    from owd.ffmpeg import duration, normalize_audio
    from owd.tts import Kokoro

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    kokoro = Kokoro()
    combined: list[np.ndarray] = []
    with tempfile.TemporaryDirectory() as tmp:
        for number, (voice, description) in enumerate(SAMPLE_VOICES, start=1):
            started = time.perf_counter()
            narration = kokoro.synthesize(SAMPLE_SCRIPT, voice)
            seconds = time.perf_counter() - started
            raw = Path(tmp) / f"{voice}.wav"
            narration.save(raw)
            final = normalize_audio(raw, out / f"{number}-{voice}.wav")
            label = kokoro.synthesize(f"Voice {NUMBER_WORDS[number - 1]}.", voice).audio
            silence = lambda s: np.zeros(round(s * SAMPLE_RATE), dtype=np.float32)  # noqa: E731
            combined += [label, silence(0.6), narration.audio, silence(1.4)]
            print(f"{number}. {voice:11} {description:52} {duration(final):5.1f}s audio, made in {seconds:4.1f}s")
        everything = Path(tmp) / "all.wav"
        soundfile.write(str(everything), np.clip(np.concatenate(combined), -1, 1), SAMPLE_RATE, subtype="PCM_16")
        normalize_audio(everything, out / "0-all-voices.wav")
    print(f"Saved in {out}")


def cmd_demo(args: argparse.Namespace) -> None:
    """A technical test of the whole chain without any API: narration, word-timed captions,
    generated backgrounds with camera moves and crossfades, a thumbnail and an SRT file."""
    from owd.backgrounds import PALETTES, glow_background
    from owd.captions import shorts_ass, srt
    from owd.ffmpeg import duration
    from owd.render import MOTIONS, assemble, render_scene
    from owd.thumbnail import make_thumbnail
    from owd.timeline import choose_cuts, shot_lengths
    from owd.tts import Kokoro

    out = Path(args.out)
    work = out / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    started = time.perf_counter()
    narration = Kokoro().synthesize(SAMPLE_SCRIPT, args.voice, speed=args.speed)
    narration.save(work / "narration.wav", work / "words.json")
    print(f"narration: {narration.duration:.1f}s, {len(narration.words)} words ({time.perf_counter() - started:.1f}s)")

    (work / "captions.ass").write_text(shorts_ass(narration.words), encoding="utf-8")
    (out / "demo-long-captions.srt").write_text(srt(narration.words), encoding="utf-8")

    fade = 0.6
    cuts = choose_cuts(narration.words, args.shots)
    lengths = shot_lengths(cuts, narration.duration, fade)
    shots = []
    palettes = list(PALETTES)
    started = time.perf_counter()
    for index, seconds in enumerate(lengths):
        still = work / f"still-{index}.png"
        glow_background(SHORT.size, palette=palettes[index % len(palettes)], seed=index).save(still)
        shot = render_scene(still, work / f"shot-{index}.mp4", seconds=seconds, size=SHORT.size,
                            motion=MOTIONS[index % len(MOTIONS)])
        shots.append(shot)
    print(f"shots: {len(shots)} cut at {cuts} ({time.perf_counter() - started:.1f}s)")

    started = time.perf_counter()
    video = assemble(shots, lengths, work / "narration.wav", out / "demo-short.mp4",
                     captions=work / "captions.ass", fade=fade)
    print(f"video: {video} {duration(video):.2f}s ({time.perf_counter() - started:.1f}s)")

    thumb = make_thumbnail("He warned us in 1903", out / "demo-thumbnail.jpg", accent=["1903"])
    print(f"thumbnail: {thumb} ({thumb.stat().st_size // 1024} KB)")


def cmd_render(args: argparse.Namespace) -> None:
    """Make a finished video, captions, thumbnail and metadata from a storyboard file."""
    from owd.channel import load_cast, load_settings
    from owd.config import cache_dir
    from owd.env import load_dotenv, require
    from owd.images import SceneImages
    from owd.produce import produce
    from owd.stock import Pixabay
    from owd.storyboard import load_storyboard
    from owd.vision import VisionJudge

    load_dotenv()
    settings = load_settings().get("video", {})
    fallbacks = load_settings().get("footage", {}).get("fallback") or None
    board = load_storyboard(args.storyboard)
    out = Path(args.out) if args.out else OUTPUT_DIR / "videos" / Path(args.storyboard).stem
    stock = Pixabay(require("PIXABAY_API_KEY"), cache_dir() / "pixabay")
    log = lambda line: print(f"  {line}")  # noqa: E731
    judge = VisionJudge(os.environ.get("GEMINI_API_KEY"), log=log) if settings.get("match_visuals", True) else None
    images = SceneImages(cache_dir() / "images", log=log) if settings.get("paintings", True) else None
    started = time.perf_counter()
    result = produce(board, out, cast=load_cast(), stock=stock, judge=judge, images=images,
                     burn_captions=bool(settings.get("captions", True)), max_upscale=1.4 if args.preview else 1.0,
                     **({"fallbacks": fallbacks} if fallbacks else {}))
    print(f"Done in {time.perf_counter() - started:.0f}s: {result.folder}")
    print(f"Before posting, read {result.review}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")


def _slug(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-") or "video"


def cmd_write(args: argparse.Namespace) -> None:
    """Write a long-form storyboard from one chapter of a book, recent research and the steering."""
    from datetime import date

    from owd.books import book_chapter
    from owd.channel import load_settings
    from owd.config import ROOT, cache_dir
    from owd.llm import LLM, models_from_settings
    from owd.news import collect, load_feeds, research_for
    from owd.quotes import check_quotes
    from owd.steering import llm_condenser, load_steering
    from owd.storyboard import dump_storyboard
    from owd.writer import Targets, write_video

    settings = load_settings()
    books = {book["id"]: book for book in settings.get("books", [])}
    if args.book not in books:
        raise SystemExit(f"Unknown book {args.book!r}. Books in channel.toml: {', '.join(books) or 'none'}")
    book = books[args.book]
    book_file = ROOT / book["file"]
    chapter = book_chapter(book, args.chapter)
    items = collect(load_feeds(settings), cache_dir() / "news", log=lambda line: print(f"  news {line}"))
    research = research_for(items, settings.get("news", {}).get("keywords", []), days=90, limit=args.research)
    video = settings.get("video", {})
    targets = Targets(min_words=int(video.get("min_words", 1250)), max_words=int(video.get("max_words", 1700)))
    llm = LLM(models_from_settings(settings), log=lambda line: print(f"  model {line}"))
    draft = write_video(chapter, book_file, book["cite"], research, load_steering(condense=llm_condenser(llm)), llm,
                        targets=targets, angle=args.angle or "", log=lambda line: print(f"  {line}"))

    problems = check_quotes(draft.storyboard)
    if problems:
        raise SystemExit("Quote check failed: " + "; ".join(problems))
    out = Path(args.out) if args.out else ROOT / "storyboards" / f"{date.today():%Y-%m-%d}-{_slug(draft.storyboard.title)}.toml"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = "\n".join(
        [f"Written by {draft.reply.model.label} on {date.today():%d %b %Y} from {book['cite']}, chapter "
         f"{chapter.number} ({chapter.title.title()}).",
         "Edit anything here, then render with: uv run python -m owd render " + str(out.relative_to(ROOT) if out.is_relative_to(ROOT) else out),
         *(f"PROBLEM: {problem}" for problem in draft.problems),
         *(f"WARNING: {warning}" for warning in draft.warnings)]
    )
    out.write_text(dump_storyboard(draft.storyboard, header), encoding="utf-8")

    board = draft.storyboard
    narration_words = sum(len(scene.text.split()) for scene in board.scenes if not scene.text.startswith(">"))
    print(f"\nTitle: {board.title}")
    for title in board.alt_titles:
        print(f"   or: {title}")
    print(f"Thumbnail: {board.thumbnail_text}  |  {len(board.chapter_starts())} chapters, {len(board.scenes)} scenes, "
          f"about {narration_words} words of narration, {sum(1 for s in board.scenes if s.text.startswith('>'))} quotes")
    for problem in draft.problems:
        print(f"PROBLEM: {problem}")
    for warning in draft.warnings:
        print(f"WARNING: {warning}")
    print(f"Saved: {out}")


def cmd_run(args: argparse.Namespace) -> None:
    """Write, render and deliver the next video on its own (what the scheduled workflow runs)."""
    from owd.autopilot import run

    record = run(angle=args.angle or "", log=print)
    print("No new video this time (see the storage note above)." if record is None else
          f"Done: {record.title} ({record.status})")


def cmd_cleanup(args: argparse.Namespace) -> None:
    """Apply the storage rules: delete stored copies that are due (see owd/storage.py)."""
    from owd.autopilot import cleanup

    deleted = cleanup(log=print)
    print(f"Deleted {len(deleted)} stored cop{'y' if len(deleted) == 1 else 'ies'}.")


def cmd_add_book(args: argparse.Namespace) -> None:
    """Add a public-domain book by its Project Gutenberg number, after checking its chapters can be found."""
    from owd.addbook import BookError, add_book
    from owd.config import ROOT

    if args.number < 1:
        raise SystemExit("Give the book's Project Gutenberg number, like 14209")
    only = [title.strip() for title in (args.chapters or "").split(",") if title.strip()] or None
    try:
        book = add_book(args.number, ROOT, only=only, cite=(args.cite or "").strip(), year=(args.year or "").strip())
    except BookError as error:
        raise SystemExit(f"Not added: {error}") from None
    lines = [f"Added {book.cite}: {len(book.chapters)} chapters, saved as {book.file} and listed in channel.toml."]
    lines += [f"- {chapter.number}. {chapter.title.title()} ({chapter.words:,} words)" for chapter in book.chapters]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### " + "\n".join(lines) + "\n")


def cmd_plan(args: argparse.Namespace) -> None:
    """Is today a video day? The daily workflow asks first; a run started by hand always makes a video."""
    from datetime import datetime, timezone

    from owd.channel import load_settings
    from owd.schedule import is_make_day, make_days

    settings = load_settings()
    by_hand = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    make = by_hand or is_make_day(settings, datetime.now(timezone.utc))
    days = ", ".join(make_days(settings))
    print(("Making a video today" + (" (started by hand)." if by_hand else f" (video days: {days}).")) if make
          else f"No video today (video days: {days}); only the daily checks and clean-up.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"make={'true' if make else 'false'}\n")


def cmd_storage(args: argparse.Namespace) -> None:
    """Show what is stored in the cloud and when each copy will be deleted (reads state/videos.json)."""
    from owd.channel import load_settings
    from owd.state import load_state
    from owd.storage import StoragePolicy, summary

    policy, state = StoragePolicy.from_settings(load_settings()), load_state()
    lines = summary(state, policy)
    print(f"{len(lines)} of at most {policy.max_videos} videos stored; posted ones are kept "
          f"{policy.keep_days_after_posting} days.")
    for line in lines:
        print(f"  {line}")


def cmd_youtube_login(args: argparse.Namespace) -> None:
    """Sign in to YouTube once, in a browser on this computer, and print the refresh token to store as a secret."""
    from owd.env import require
    from owd.youtube import Credentials, YouTube, browser_login

    client_id, client_secret = require("YOUTUBE_CLIENT_ID"), require("YOUTUBE_CLIENT_SECRET")
    token = browser_login(client_id, client_secret)
    channel = YouTube(Credentials(client_id, client_secret, token), log=lambda line: None).channel_title()
    print(f"\nSigned in. This token posts to the YouTube channel: {channel}")
    print("If that's the right channel, add the token below as the GitHub secret YOUTUBE_REFRESH_TOKEN (Settings > "
          "Secrets and variables > Actions), and keep it private:\n")
    print(token)


def cmd_steering(args: argparse.Namespace) -> None:
    """Read every steering document and condense long ones (saved next to them as .digest.md)."""
    from owd.channel import load_settings
    from owd.llm import LLM, models_from_settings
    from owd.steering import llm_condenser, load_steering

    llm = LLM(models_from_settings(load_settings()), log=lambda line: print(f"  model {line}"))
    steering = load_steering(condense=llm_condenser(llm))
    for name, text in steering.references:
        print(f"{name}: {len(text.split())} words")
    for warning in steering.warnings:
        print(f"WARNING: {warning}")


def cmd_fetch_models(args: argparse.Namespace) -> None:
    """Download every model file (pinned versions) ahead of time."""
    from owd.channel import load_cast
    from owd.models import fetch_all

    voices = {*load_cast().voices, *(voice for voice, _ in SAMPLE_VOICES)}
    for path in fetch_all(voices):
        print(path)


def cmd_news(args: argparse.Namespace) -> None:
    """Show research stories matching the channel's keywords (or a topic), or platform news."""
    from owd.channel import load_settings
    from owd.config import cache_dir
    from owd.news import collect, load_feeds, research_for

    settings = load_settings()
    items = collect(load_feeds(settings), cache_dir() / "news", log=lambda line: print(f"  {line}"))
    if args.kind == "platform":
        chosen = [item for item in items if item.kind == "platform"][: args.limit]
    else:
        keywords = args.topic.split(",") if args.topic else settings.get("news", {}).get("keywords", [])
        chosen = research_for(items, keywords, days=args.days, limit=args.limit)
    for item in chosen:
        print(f"\n{(item.published or '')[:10]}  [{item.feed}] {item.title}\n    {item.link}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m owd")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="write, render and deliver the next video (what the schedule runs)")
    run.add_argument("--angle", help="an idea or angle to steer this one video")
    run.set_defaults(run=cmd_run)

    clean = commands.add_parser("cleanup", help="delete stored copies that are due (posted long enough ago, discarded)")
    clean.set_defaults(run=cmd_cleanup)

    storage = commands.add_parser("storage", help="show the stored videos and when each will be deleted")
    storage.set_defaults(run=cmd_storage)

    add = commands.add_parser("add-book", help="add a public-domain book by its Project Gutenberg number")
    add.add_argument("number", type=int, help="the book's number on gutenberg.org, e.g. 14209")
    add.add_argument("--chapters", help="only these chapters: comma-separated titles from its contents")
    add.add_argument("--cite", help='how to credit it, e.g. "Three Initiates, The Kybalion (1908)"')
    add.add_argument("--year", help="the year it was first published, for the credit")
    add.set_defaults(run=cmd_add_book)

    plan = commands.add_parser("plan", help="is today a video day? (used by the daily workflow)")
    plan.set_defaults(run=cmd_plan)

    login = commands.add_parser("youtube-login", help="sign in to YouTube once (opens a browser) and print the token")
    login.set_defaults(run=cmd_youtube_login)

    steer = commands.add_parser("steering", help="read the steering documents and condense long ones")
    steer.set_defaults(run=cmd_steering)

    write = commands.add_parser("write", help="write a long-form storyboard from a book chapter")
    write.add_argument("--book", default="as-a-man-thinketh", help="a book id from channel.toml")
    write.add_argument("--chapter", required=True, help="chapter number or part of its title")
    write.add_argument("--angle", help="an idea or angle to steer this one video")
    write.add_argument("--research", type=int, default=12, help="how many research stories to offer the writer")
    write.add_argument("--out", help="storyboard file (default: storyboards/<date>-<title>.toml)")
    write.set_defaults(run=cmd_write)

    news = commands.add_parser("news", help="research stories for scripts, or YouTube platform news")
    news.add_argument("--kind", choices=("research", "platform"), default="research")
    news.add_argument("--topic", help="comma-separated words to match instead of the channel keywords")
    news.add_argument("--days", type=int, default=60)
    news.add_argument("--limit", type=int, default=10)
    news.set_defaults(run=cmd_news)

    render = commands.add_parser("render", help="make a video from a storyboard (.toml)")
    render.add_argument("storyboard")
    render.add_argument("--out", help="output folder (default: output/videos/<storyboard name>)")
    render.add_argument("--preview", action="store_true",
                        help="smaller footage downloads, slightly softer picture (for slow connections)")
    render.set_defaults(run=cmd_render)

    fetch = commands.add_parser("fetch-models", help="download the pinned model files")
    fetch.set_defaults(run=cmd_fetch_models)

    voices = commands.add_parser("voices", help="read a sample paragraph in each candidate voice")
    voices.add_argument("--out", default=OUTPUT_DIR / "voice-samples")
    voices.set_defaults(run=cmd_voices)

    demo = commands.add_parser("demo", help="render a technical test Short and thumbnail (no API keys)")
    demo.add_argument("--voice", default="bm_george")
    demo.add_argument("--speed", type=float, default=1.0)
    demo.add_argument("--shots", type=int, default=4)
    demo.add_argument("--out", default=OUTPUT_DIR / "demo")
    demo.set_defaults(run=cmd_demo)

    args = parser.parse_args(argv)
    args.run(args)
