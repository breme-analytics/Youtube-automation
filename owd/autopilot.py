"""The bot on its own: what a scheduled run does, end to end, with no person at the keyboard.

`run` (python -m owd run):
    pick the next chapter -> write the storyboard -> render the video -> deliver it
    deliver, mode "review": a GitHub release holds the files; an issue tells the owner (GitHub
                            emails her) to download and post them. Used until YouTube's audit passes.
    deliver, mode "auto":   upload to YouTube as private with a scheduled publish time on the next
                            posting slot, plus thumbnail and captions.

`cleanup` (python -m owd cleanup):
    deletes a video's release files once it is posted (or keep_days after it was made, if nobody
    posted it), closes its issue, and clears local files. Nothing piles up, so nothing costs money.

Every step records progress in state/videos.json, which the workflow commits back to the repo.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from owd.books import chapters, find_chapter
from owd.channel import load_cast, load_settings
from owd.config import OUTPUT_DIR, ROOT, cache_dir
from owd.env import load_dotenv
from owd.state import STATE_FILE, State, VideoRecord, load_state, next_chapter, now_iso, save_state
from owd.storyboard import dump_storyboard, load_storyboard

Log = Callable[[str], None]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-") or "video"


@dataclass
class Context:
    settings: dict
    env: dict
    log: Log

    @property
    def schedule(self) -> dict:
        return self.settings.get("schedule", {})

    @property
    def mode(self) -> str:
        return str(self.schedule.get("mode", "review"))


def _context(log: Log) -> Context:
    load_dotenv()
    return Context(load_settings(), dict(os.environ), log)


def _github(ctx: Context):
    from owd.github import GitHub

    repository, token = ctx.env.get("GITHUB_REPOSITORY", ""), ctx.env.get("GITHUB_TOKEN", "")
    return GitHub(repository, token) if repository and token else None


def write_next(ctx: Context, state: State, angle: str = "") -> tuple[VideoRecord, Path] | None:
    from owd.llm import LLM, models_from_settings
    from owd.news import collect, load_feeds, research_for
    from owd.quotes import check_quotes
    from owd.steering import llm_condenser, load_steering
    from owd.writer import Targets, write_video

    books = ctx.settings.get("books", [])
    counts = {book["id"]: len(chapters(ROOT / book["file"])) for book in books}
    pick = next_chapter(state, books, counts)
    if pick is None:
        ctx.log("Every chapter of every book in channel.toml has a video: add a book to keep going.")
        return None
    book_id, number = pick
    book = next(b for b in books if b["id"] == book_id)
    book_file = ROOT / book["file"]
    chapter = find_chapter(book_file, str(number))
    ctx.log(f"next: {book['cite']}, chapter {number} ({chapter.title.title()})")
    llm = LLM(models_from_settings(ctx.settings), log=lambda line: ctx.log(f"  model {line}"))
    steering = load_steering(condense=llm_condenser(llm))
    items = collect(load_feeds(ctx.settings), cache_dir() / "news", log=lambda line: ctx.log(f"  news {line}"))
    research = research_for(items, ctx.settings.get("news", {}).get("keywords", []), days=90, limit=12)
    video = ctx.settings.get("video", {})
    targets = Targets(min_words=int(video.get("min_words", 1250)), max_words=int(video.get("max_words", 1700)))
    draft = write_video(chapter, book_file, book["cite"], research, steering, llm, targets=targets, angle=angle,
                        log=lambda line: ctx.log(f"  {line}"))
    problems = check_quotes(draft.storyboard)
    if problems:
        raise RuntimeError("Quote check failed: " + "; ".join(problems))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = f"{day}-{slugify(draft.storyboard.title)}"
    path = ROOT / "storyboards" / f"{slug}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "\n".join([f"Written by {draft.reply.model.label} on {day} from {book['cite']}, chapter {number}.",
                        *(f"PROBLEM: {p}" for p in draft.problems), *(f"WARNING: {w}" for w in draft.warnings)])
    path.write_text(dump_storyboard(draft.storyboard, header), encoding="utf-8")
    record = VideoRecord(slug=slug, title=draft.storyboard.title, book=book_id, chapter=number,
                         storyboard=str(path.relative_to(ROOT)), notes=draft.problems + draft.warnings)
    state.videos.append(record)
    save_state(state)
    return record, path


def render(ctx: Context, record: VideoRecord):
    from owd.env import require
    from owd.images import SceneImages
    from owd.produce import produce
    from owd.stock import Pixabay
    from owd.vision import VisionJudge

    video = ctx.settings.get("video", {})
    log = lambda line: ctx.log(f"  {line}")  # noqa: E731
    stock = Pixabay(require("PIXABAY_API_KEY"), cache_dir() / "pixabay")
    judge = VisionJudge(ctx.env.get("GEMINI_API_KEY"), log=log) if video.get("match_visuals", True) else None
    images = SceneImages(cache_dir() / "images", env=ctx.env, log=log) if video.get("paintings", True) else None
    return produce(load_storyboard(ROOT / record.storyboard), OUTPUT_DIR / "videos" / record.slug, cast=load_cast(),
                   stock=stock, judge=judge, images=images, burn_captions=bool(video.get("captions", True)), log=log)


def _review_body(record: VideoRecord, result, links: dict[str, str], metadata: dict) -> str:
    review = Path(result.review).read_text(encoding="utf-8")
    files = "\n".join(f"- [{name}]({url})" for name, url in links.items())
    return f"""**{record.title}** is ready ({metadata.get('duration', 0) / 60:.1f} minutes).

### Download
{files}

### Post it
1. Download `video.mp4`, `thumbnail.jpg` and `captions.srt` above.
2. In YouTube Studio: **Create > Upload videos**, choose `video.mp4`, paste the title and description below, set the
   thumbnail, and under **Subtitles** upload `captions.srt`. Schedule it, or publish now.
3. Close this issue once it's posted (paste the YouTube link in a comment if you like). The bot then deletes
   these download files after a few days, so nothing piles up and nothing ever costs money.

### Title
{record.title}

### Description
```
{metadata.get('description', '')}
```

{review}"""


def deliver(ctx: Context, state: State, record: VideoRecord, result) -> None:
    import json

    metadata = json.loads(Path(result.metadata).read_text(encoding="utf-8"))
    if ctx.mode == "auto":
        _post_to_youtube(ctx, state, record, result, metadata)
        return
    github = _github(ctx)
    if github is None:
        ctx.log("Review mode, but no GitHub token here: the files stay in " + str(result.folder))
        return
    tag = f"video-{record.slug}"[:120]
    release = github.find_release(tag) or github.create_release(
        tag, record.title, f"Review copy of '{record.title}'. Deleted automatically after it's posted.")
    links = {}
    for path in (result.video, result.thumbnail, result.captions, result.metadata):
        links[Path(path).name] = github.upload_asset(release, Path(path))
    record.release_tag = tag
    record.issue = github.create_issue(f"Ready to post: {record.title}", _review_body(record, result, links, metadata),
                                       labels=["ready-to-post"])
    record.status = "released"
    save_state(state)
    ctx.log(f"review copy: {release.url} (issue #{record.issue})")


def _post_to_youtube(ctx: Context, state: State, record: VideoRecord, result, metadata: dict) -> None:
    from owd.schedule import next_slot
    from owd.youtube import Credentials, YouTube

    credentials = Credentials(ctx.env.get("YOUTUBE_CLIENT_ID", ""), ctx.env.get("YOUTUBE_CLIENT_SECRET", ""),
                              ctx.env.get("YOUTUBE_REFRESH_TOKEN", ""))
    if not all((credentials.client_id, credentials.client_secret, credentials.refresh_token)):
        raise RuntimeError("Auto mode needs YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN")
    schedule = ctx.schedule
    taken = [datetime.fromisoformat(v.publish_at) for v in state.videos if v.publish_at and v.status == "scheduled"]
    slot = next_slot(datetime.now(timezone.utc), schedule.get("publish_days", ["Tue", "Fri"]),
                     schedule.get("publish_time", "18:00"), schedule.get("timezone", "UTC"), taken)
    youtube = YouTube(credentials, log=ctx.log)
    tags = ["James Allen", "psychology", "self improvement", "philosophy", "mindset", "old wisdom"]
    video_id = youtube.upload(Path(result.video), title=record.title, description=metadata["description"], tags=tags,
                              publish_at=slot)
    youtube.set_thumbnail(video_id, Path(result.thumbnail))
    youtube.add_captions(video_id, Path(result.captions))
    record.youtube_id, record.publish_at, record.status = video_id, slot.isoformat(), "scheduled"
    save_state(state)
    ctx.log(f"scheduled: https://youtu.be/{video_id} goes public {slot.isoformat()}")


def run(angle: str = "", log: Log = print) -> VideoRecord | None:
    """One full run: write, render and deliver the next video. Returns its record."""
    ctx = _context(log)
    state = load_state()
    written = write_next(ctx, state, angle)
    if written is None:
        return None
    record, _ = written
    try:
        result = render(ctx, record)
        deliver(ctx, state, record, result)
    except Exception as error:
        record.status = "failed"
        record.notes.append(f"{type(error).__name__}: {str(error)[:300]}")
        save_state(state)
        raise
    return record


def cleanup(log: Log = print, now: datetime | None = None) -> list[str]:
    """Delete review files that aren't needed any more. Returns what was cleaned."""
    ctx = _context(log)
    state = load_state()
    now = now or datetime.now(timezone.utc)
    keep = timedelta(days=int(ctx.schedule.get("keep_days", 7)))
    github = _github(ctx)
    cleaned = []
    for record in state.videos:
        if record.status in ("cleaned", "failed"):
            continue
        posted = record.posted_at or _posted_from_issue(github, record)
        if record.status == "scheduled" and record.publish_at and datetime.fromisoformat(record.publish_at) <= now:
            record.status, record.posted_at = "posted", record.publish_at
            posted = record.posted_at
        if posted and not record.posted_at:
            record.status, record.posted_at = "posted", posted
        anchor = datetime.fromisoformat(record.posted_at or record.made_at)
        if now - anchor < keep:
            continue
        if github is not None and record.release_tag:
            github.delete_release(record.release_tag)
            if record.issue:
                github.comment(record.issue, "Cleaned up: the review files were deleted to save space.")
                github.close_issue(record.issue)
        shutil.rmtree(OUTPUT_DIR / "videos" / record.slug, ignore_errors=True)
        record.status, record.cleaned_at = "cleaned", now_iso()
        cleaned.append(record.slug)
        log(f"cleaned: {record.slug}")
    save_state(state)
    return cleaned


def _posted_from_issue(github, record: VideoRecord) -> str:
    """When the owner closed the review issue (she posted it), or "" if it's still open."""
    if github is None or not record.issue:
        return ""
    try:
        issue = github.issue(record.issue)
    except Exception:
        return ""
    if issue.get("state") == "closed" and issue.get("closed_at"):
        return issue["closed_at"].replace("Z", "+00:00")
    return ""


__all__ = ["run", "cleanup", "write_next", "render", "deliver", "STATE_FILE"]
