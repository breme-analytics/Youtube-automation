"""The bot on its own: what a scheduled run does, end to end, with no person at the keyboard.

`run` (python -m owd run), what .github/workflows/produce.yml runs:
    1. catch up: which waiting videos were posted or discarded (their issues) or published (YouTube)
    2. make room: at most [storage] max_videos are stored; copies of posted videos are deleted early
       if needed, and if every stored video is still waiting to be posted, stop (no new video)
    3. pick the next chapter -> write the storyboard -> render the video
    4. store it in the cloud: a GitHub release in this repository, always, in both modes
    5. deliver it:
       review: an issue tells the owner (GitHub emails her) to post the stored copy.
       auto:   upload to YouTube, private, scheduled for the next posting slot, with thumbnail and
               captions; an issue says when it goes public. If YouTube refuses the upload, the issue
               asks the owner to post the stored copy instead, and says how to fix the cause.

`cleanup` (python -m owd cleanup), what .github/workflows/cleanup.yml runs every day:
    catch up as above (a scheduled video that YouTube didn't make public goes back to the owner),
    delete the copies that are due (owd/storage.py), keep within max_videos, and delete any stray
    "video-" release that no record knows about.

Every step records progress in state/videos.json, which the workflows commit back to the repository.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from owd.books import chapters, find_chapter
from owd.channel import load_cast, load_settings
from owd.config import OUTPUT_DIR, ROOT, cache_dir
from owd.env import load_dotenv
from owd.state import STATE_FILE, WAITING, State, VideoRecord, load_state, next_chapter, now_iso, save_state
from owd.storage import FILE_LIMIT, StoragePolicy, expired, make_room, summary
from owd.storyboard import dump_storyboard, load_storyboard

Log = Callable[[str], None]
TAG_PREFIX = "video-"
READY_LABEL, SCHEDULED_LABEL = "ready-to-post", "scheduled"
PUBLISH_GRACE = timedelta(minutes=30)  # YouTube makes a scheduled video public at its time; allow some slack
STALE_RUN = timedelta(hours=24)  # a video still "made" after this belongs to a run that was stopped
ORPHAN_AGE = timedelta(hours=24)  # a stray release younger than this may belong to a run in progress
AUDIT_FORM = "https://support.google.com/youtube/contact/yt_api_form"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-") or "video"


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).astimezone(timezone.utc)


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
        mode = str(self.schedule.get("mode", "review"))
        if mode not in ("review", "auto"):
            raise ValueError(f'channel.toml [schedule] mode must be "review" or "auto", not {mode!r}')
        return mode

    @property
    def storage(self) -> StoragePolicy:
        return StoragePolicy.from_settings(self.settings)

    def warn(self, text: str) -> None:
        """Log, and on GitHub Actions also show it at the top of the run's page."""
        self.log(text)
        if self.env.get("GITHUB_ACTIONS") == "true":
            print("::warning::" + text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"), flush=True)

    def report(self, lines: list[str]) -> None:
        """Add lines to the run's summary page on GitHub Actions (nothing elsewhere)."""
        path = self.env.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")

    def when(self, stamp: str) -> str:
        zone = ZoneInfo(self.schedule.get("timezone", "UTC"))
        return f"{_utc(stamp).astimezone(zone):%A %d %B %Y, %H:%M} ({zone.key})"


def _context(log: Log) -> Context:
    load_dotenv()
    return Context(load_settings(), dict(os.environ), log)


def _github(ctx: Context):
    from owd.github import GitHub

    repository, token = ctx.env.get("GITHUB_REPOSITORY", ""), ctx.env.get("GITHUB_TOKEN", "")
    return GitHub(repository, token) if repository and token else None


def _youtube(ctx: Context):
    from owd.youtube import Credentials, YouTube

    credentials = Credentials(ctx.env.get("YOUTUBE_CLIENT_ID", ""), ctx.env.get("YOUTUBE_CLIENT_SECRET", ""),
                              ctx.env.get("YOUTUBE_REFRESH_TOKEN", ""))
    if not all((credentials.client_id, credentials.client_secret, credentials.refresh_token)):
        return None
    return YouTube(credentials, log=ctx.log)


# Making a video


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
    fallbacks = ctx.settings.get("footage", {}).get("fallback") or None
    return produce(load_storyboard(ROOT / record.storyboard), OUTPUT_DIR / "videos" / record.slug, cast=load_cast(),
                   stock=stock, judge=judge, images=images, burn_captions=bool(video.get("captions", True)), log=log,
                   **({"fallbacks": fallbacks} if fallbacks else {}))


# Storing and delivering


def store(ctx: Context, state: State, record: VideoRecord, result, github) -> tuple[dict[str, str], str]:
    """Storage rule 1: put the finished video in the cloud before anything else. Returns the files'
    download links and the release page."""
    files = [Path(result.video), Path(result.thumbnail), Path(result.captions), Path(result.metadata)]
    for path in files:
        if path.stat().st_size >= FILE_LIMIT:
            raise RuntimeError(f"{path.name} is {path.stat().st_size / 1024**3:.2f} GiB, and GitHub stores files only "
                               "under 2 GiB (about 40 minutes of video): shorten the video or lower its bitrate")
    tag = f"{TAG_PREFIX}{record.slug}"[:120]
    record.release_tag = tag  # written down first, so even a half-stored copy is found and deleted later
    save_state(state)
    if github.find_release(tag) is not None:
        github.delete_release(tag)  # left by an earlier attempt that didn't finish
    keep = ctx.storage.keep_days_after_posting
    release = github.create_release(tag, record.title, f"Stored copy of \u201c{record.title}\u201d, made "
                                    f"{record.made_at[:10]}. Deleted automatically {keep} days after it's posted.")
    links = {path.name: github.upload_asset(release, path) for path in files}
    record.stored_at, record.stored_bytes = now_iso(), sum(path.stat().st_size for path in files)
    save_state(state)
    ctx.log(f"stored: {release.url} ({record.stored_bytes / 1e6:,.0f} MB)")
    return links, release.url


POSTING_STEPS = """1. Download `video.mp4`, `thumbnail.jpg` and `captions.srt` above (signed in to GitHub).
2. In YouTube Studio: **Create > Upload videos**, choose `video.mp4`, paste the title and description below, set the
   thumbnail, and under **Subtitles** upload `captions.srt`. Schedule it, or publish now.
3. **Close this issue** once it's posted (paste the YouTube link in a comment if you like). The stored copy is
   deleted {keep} days later. Not posting it? **Close as not planned**, and the copy is deleted at the next cleanup."""


def explain(problem: str) -> str:
    """What went wrong with YouTube, in plain words, and the fix."""
    text = problem.lower()
    if "invalid_grant" in text:
        return ("The YouTube sign-in has expired or was revoked. Fix: if the OAuth app is still in Testing, publish it "
                "(Google Auth Platform > Audience > Publish app); then run `python -m owd youtube-login` on any computer "
                "and update the secret YOUTUBE_REFRESH_TOKEN.")
    if "needs the secrets" in text:
        return ('Fix: add the YouTube secrets (docs/DEPLOY.md, step 4), or set mode = "review" in channel.toml.')
    if "quotaexceeded" in text or "uploadlimitexceeded" in text or "ratelimitexceeded" in text:
        return "YouTube's daily allowance for this project is used up; it resets at midnight Pacific time."
    return "If this happens again, set mode = \"review\" in channel.toml until it's fixed, and see docs/DEPLOY.md."


def _issue_body(ctx: Context, record: VideoRecord, metadata: dict, links: dict[str, str], release_url: str,
                review: str, problem: str = "") -> str:
    keep = ctx.storage.keep_days_after_posting
    minutes = metadata.get("duration", 0) / 60
    files = "\n".join(f"- [{name}]({url})" for name, url in links.items())
    if record.status == "scheduled":
        head = f"""**{record.title}** ({minutes:.1f} minutes) is on YouTube, private, and goes public on **{ctx.when(record.publish_at)}**.

- In YouTube Studio: https://studio.youtube.com/video/{record.youtube_id}/edit
- Nothing to do. Once it's public the bot closes this issue, and deletes the stored copy {keep} days later.
- To stop it going public: YouTube Studio > Content > this video > Visibility > Private; then close this issue as
  not planned.
- If YouTube doesn't publish it, the bot says so here, and you post the stored copy by hand."""
        action = ""
    else:
        head = f"**{record.title}** is ready ({minutes:.1f} minutes)."
        if problem:
            flat = " ".join(problem.split())
            head += f"\n\n> **YouTube didn't take it:** {flat}\n>\n> {explain(problem)}"
        action = "### Post it\n" + POSTING_STEPS.format(keep=keep)
    return f"""{head}

### Stored copy
{files}

Release page: {release_url}

{action}

### Title
{record.title}

### Description
```
{metadata.get('description', '')}
```

{review}"""


def deliver(ctx: Context, state: State, record: VideoRecord, result, github) -> None:
    metadata = json.loads(Path(result.metadata).read_text(encoding="utf-8"))
    links, release_url = store(ctx, state, record, result, github)
    problem = ""
    if ctx.mode == "auto":
        try:
            _post_to_youtube(ctx, state, record, result, metadata)
        except Exception as error:
            if record.youtube_id:  # it's on YouTube; only an extra (thumbnail, captions) failed
                record.notes.append(f"YouTube: {type(error).__name__}: {str(error)[:200]}")
            else:  # YouTube said no: the owner posts the stored copy instead
                problem = f"{type(error).__name__}: {str(error)[:400]}"
                record.notes.append(f"YouTube upload failed: {problem}")
                ctx.warn(f"YouTube upload failed, so the owner is asked to post it by hand. {problem}")
    review = Path(result.review).read_text(encoding="utf-8")
    body = _issue_body(ctx, record, metadata, links, release_url, review, problem)
    if record.status == "scheduled":
        record.issue = github.create_issue(f"Scheduled: {record.title}", body, labels=[SCHEDULED_LABEL])
    else:
        record.status = "released"
        record.issue = github.create_issue(f"Ready to post: {record.title}", body, labels=[READY_LABEL])
    save_state(state)
    ctx.log(f"{record.status}: issue #{record.issue}")


def _post_to_youtube(ctx: Context, state: State, record: VideoRecord, result, metadata: dict) -> None:
    from owd.schedule import next_slot

    youtube = _youtube(ctx)
    if youtube is None:
        raise RuntimeError("auto mode needs the secrets YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN")
    schedule = ctx.schedule
    taken = [_utc(v.publish_at) for v in state.videos if v.publish_at and v.status == "scheduled"]
    slot = next_slot(datetime.now(timezone.utc), schedule.get("publish_days", ["Tue", "Fri"]),
                     schedule.get("publish_time", "18:00"), schedule.get("timezone", "UTC"), taken)
    book = next((b for b in ctx.settings.get("books", []) if b["id"] == record.book), {})
    tags = [t for t in (book.get("author"), "psychology", "self improvement", "philosophy", "mindset", "old wisdom") if t]
    video_id = youtube.upload(Path(result.video), title=record.title, description=metadata["description"], tags=tags,
                              publish_at=slot)
    record.youtube_id, record.publish_at, record.status = video_id, slot.isoformat(), "scheduled"
    save_state(state)
    if not youtube.set_thumbnail(video_id, Path(result.thumbnail)):
        record.notes.append("YouTube: custom thumbnail refused (verify the channel at youtube.com/verify)")
    if not youtube.add_captions(video_id, Path(result.captions)):
        record.notes.append("YouTube: captions file refused (YouTube's automatic captions are used)")
    save_state(state)
    ctx.log(f"scheduled: https://youtu.be/{video_id} goes public {ctx.when(record.publish_at)}")


# Catching up, and the storage rules


def catch_up(ctx: Context, state: State, github, youtube, now: datetime) -> None:
    """Work out what happened since the last run: posted, discarded, published, or kept private."""
    for record in state.videos:
        if record.status == "made" and now - _utc(record.made_at) > STALE_RUN:
            record.status = "failed"
            record.notes.append("The run stopped before the video was delivered (time limit?); the chapter is made again.")
            continue
        if record.status not in WAITING:
            continue
        issue = _issue(github, record)
        if issue.get("state") == "closed" and issue.get("state_reason") == "not_planned":
            record.status = "discarded"
            ctx.log(f"discarded by the owner: {record.slug}")
            if record.youtube_id and record.publish_at and _utc(record.publish_at) > now and github:
                _tell(ctx, "comment on the discarded video's issue", lambda: github.comment(
                    record.issue, "Discarded: the stored copy will be deleted. This video is still scheduled on "
                    "YouTube; to stop it, set it to Private in YouTube Studio."))
            continue
        if record.status == "released" and issue.get("state") == "closed":
            record.status, record.posted_at = "posted", _utc(issue.get("closed_at") or now_iso()).isoformat()
            ctx.log(f"posted by the owner: {record.slug}")
            continue
        if record.status == "scheduled" and record.publish_at and now >= _utc(record.publish_at) + PUBLISH_GRACE:
            _check_published(ctx, state, record, github, youtube, now)


def _issue(github, record: VideoRecord) -> dict:
    if github is None or not record.issue:
        return {}
    try:
        return github.issue(record.issue)
    except Exception:
        return {}


def _check_published(ctx: Context, state: State, record: VideoRecord, github, youtube, now: datetime) -> None:
    if youtube is None:
        ctx.warn(f"{record.title} should be public by now, but there are no YouTube secrets here to check; its stored "
                 "copy is kept.")
        return
    try:
        status = youtube.status(record.youtube_id)
    except Exception as error:
        ctx.warn(f"Couldn't check {record.title} on YouTube ({str(error)[:200]}); trying again next time.")
        return
    privacy, upload = status.get("privacyStatus"), status.get("uploadStatus")
    if privacy in ("public", "unlisted") and upload not in ("failed", "rejected", "deleted"):
        record.status, record.posted_at = "posted", record.publish_at
        ctx.log(f"public on YouTube: {record.slug}")
        if github and record.issue:
            due = ctx.storage.delete_on(record)
            _tell(ctx, "tell the owner it's public", lambda: (
                github.comment(record.issue, f"Now {privacy} on YouTube: https://youtu.be/{record.youtube_id}\n\n"
                                             f"The stored copy will be deleted on {due:%d %B %Y}."),
                github.close_issue(record.issue)))
        return
    if privacy == "private" and status.get("publishAt") and _utc(status["publishAt"]) > now:
        record.publish_at = _utc(status["publishAt"]).isoformat()  # the owner moved it in YouTube Studio
        return
    if not status:
        reason = "It isn't on YouTube any more (deleted?)."
    elif upload in ("failed", "rejected", "deleted"):
        reason = f"YouTube {upload} it ({status.get('failureReason') or status.get('rejectionReason') or 'no reason given'})."
    else:
        reason = ("YouTube still shows it as private after its publish time. If you made it private yourself, close this "
                  "issue as not planned. Otherwise YouTube has most likely locked it: videos uploaded through a Google "
                  "Cloud project that hasn't passed YouTube's API audit can be kept private, and a locked video can't be "
                  f"made public.\n\n**Fix:** post the stored copy by hand (steps below) and delete the private one in "
                  f"Studio. Apply for the free audit at {AUDIT_FORM}, and until it's approved set mode = \"review\" in "
                  "channel.toml.")
    _back_to_owner(ctx, record, github, reason)


def _back_to_owner(ctx: Context, record: VideoRecord, github, reason: str) -> None:
    """YouTube didn't publish it: the owner posts the stored copy instead."""
    record.status = "released"
    record.notes.append(f"Not published by YouTube: {reason.splitlines()[0]}")
    ctx.warn(f"{record.title} wasn't published by YouTube; its issue now asks the owner to post it by hand.")
    if github and record.issue:
        steps = POSTING_STEPS.format(keep=ctx.storage.keep_days_after_posting)
        _tell(ctx, "ask the owner to post it by hand", lambda: (
            github.comment(record.issue, f"**YouTube didn't publish this video.** {reason}\n\n### Post it\n{steps}"),
            github.update_issue(record.issue, title=f"Ready to post: {record.title}", labels=[READY_LABEL])))


def _delete_copy(ctx: Context, record: VideoRecord, github, why: str) -> bool:
    try:
        github.delete_release(record.release_tag)
    except Exception as error:  # kept for now; the next cleanup tries again
        ctx.warn(f"Couldn't delete the stored copy of {record.slug} ({str(error)[:200]}); trying again next time.")
        return False
    shutil.rmtree(OUTPUT_DIR / "videos" / record.slug, ignore_errors=True)
    record.cleaned_at = now_iso()
    if record.status == "posted":
        record.status = "cleaned"
    ctx.log(f"deleted the stored copy of {record.slug} ({why})")
    return True


def _tell(ctx: Context, what: str, action: Callable[[], object]) -> None:
    """Comment on or update an issue; a failure is reported but never stops the storage rules."""
    try:
        action()
    except Exception as error:
        ctx.warn(f"Couldn't {what} ({str(error)[:200]}).")


def _apply_rules(ctx: Context, state: State, github, now: datetime, new: int) -> tuple[list[str], bool]:
    """Delete what's due, then make room for `new` more videos. Returns (deleted slugs, room?)."""
    deleted = []
    for record in expired(state, ctx.storage, now):
        why = {"discarded": "discarded", "failed": "left by a failed run"}.get(record.status, "posted long enough ago")
        if _delete_copy(ctx, record, github, why):
            deleted.append(record.slug)
    early, _ = make_room(state, ctx.storage, new)
    for record in early:
        if _delete_copy(ctx, record, github, "posted; deleted early to make room"):
            deleted.append(record.slug)
    return deleted, len(state.stored()) + new <= ctx.storage.max_videos


def _sweep_strays(ctx: Context, state: State, github, now: datetime) -> list[str]:
    """Delete "video-" releases that no record knows about (say, a run's progress was never saved)."""
    known = {record.release_tag for record in state.stored()}
    swept = []
    try:
        releases = github.list_releases()
    except Exception as error:
        ctx.warn(f"Couldn't list the stored copies ({str(error)[:200]}); stray ones are looked for next time.")
        return swept
    for release in releases:
        if not release.tag.startswith(TAG_PREFIX) or release.tag in known or not release.created_at:
            continue
        if now - _utc(release.created_at) > ORPHAN_AGE:
            try:
                github.delete_release(release.tag)
            except Exception as error:
                ctx.warn(f"Couldn't delete the stray copy {release.tag} ({str(error)[:200]}).")
                continue
            swept.append(release.tag)
            ctx.log(f"deleted a stray stored copy: {release.tag}")
    return swept


def _storage_report(ctx: Context, state: State) -> None:
    policy = ctx.storage
    stored = state.stored()
    total = sum(record.stored_bytes for record in stored) / 1e9
    head = f"Storage: {len(stored)} of at most {policy.max_videos} videos stored ({total:.1f} GB)."
    lines = summary(state, policy)
    ctx.log(head)
    for line in lines:
        ctx.log(f"  {line}")
    ctx.report([f"### {head}", *(f"- {line}" for line in lines)])


# The two entry points


def run(angle: str = "", log: Log = print) -> VideoRecord | None:
    """One full run: catch up, make room, then write, render, store and deliver the next video."""
    ctx = _context(log)
    _ = ctx.mode, ctx.storage  # a mistyped setting fails now, not after an hour of rendering
    github = _github(ctx)
    if github is None:
        raise RuntimeError("Every video is stored on GitHub before it's posted, so `run` needs GITHUB_REPOSITORY and "
                           "GITHUB_TOKEN (the produce workflow sets both). To make a video on this computer instead, use "
                           "`python -m owd render <storyboard>`.")
    state = load_state()
    now = datetime.now(timezone.utc)
    catch_up(ctx, state, github, _youtube(ctx), now)
    _, room = _apply_rules(ctx, state, github, now, new=1)
    save_state(state)
    if not room:
        waiting = [record for record in state.stored() if record.waiting]
        ctx.warn(f"Storage is full: {len(waiting)} videos are waiting to be posted (max_videos = "
                 f"{ctx.storage.max_videos} in channel.toml), so no new video was made. Post one, or close its issue as "
                 "not planned, and the next run carries on. Waiting: " + "; ".join(r.title for r in waiting))
        _storage_report(ctx, state)
        return None
    written = write_next(ctx, state, angle)
    if written is None:
        return None
    record, _ = written
    try:
        result = render(ctx, record)
        deliver(ctx, state, record, result, github)
    except Exception as error:
        record.notes.append(f"{type(error).__name__}: {str(error)[:300]}")
        if not record.youtube_id:  # never retry a chapter that is already on YouTube
            record.status = "failed"
        save_state(state)
        raise
    _storage_report(ctx, state)
    return record


def cleanup(log: Log = print, now: datetime | None = None) -> list[str]:
    """Apply the storage rules. Returns what was deleted."""
    ctx = _context(log)
    github = _github(ctx)
    if github is None:
        log("No GitHub token here (GITHUB_REPOSITORY and GITHUB_TOKEN): the stored copies are cleaned up by the "
            "cleanup workflow.")
        return []
    state = load_state()
    now = now or datetime.now(timezone.utc)
    catch_up(ctx, state, github, _youtube(ctx), now)
    deleted, _ = _apply_rules(ctx, state, github, now, new=0)
    save_state(state)
    deleted += _sweep_strays(ctx, state, github, now)
    _storage_report(ctx, state)
    return deleted


__all__ = ["run", "cleanup", "catch_up", "write_next", "render", "store", "deliver", "explain", "STATE_FILE"]
