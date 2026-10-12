# Development log

Every change to the bot, newest first: what was done, why, and what was checked. Development agents add an
entry here for each change (see `AGENTS.md`). The owner's standing instructions live in
`steering/instructions.md`.

---

## 2026-10-12: Milestone 3, long-form only, one voice, mind and spirit visuals

**Owner's feedback on the wildlife Short (11 Oct):** video quality great; the crop cut out too much; wildlife
didn't fit a script about the mind; don't mix voices (keep George); Shorts not dense enough, so focus on
long-form; titles from *The Power of Bad*; retention from Mario Joos; a place to give the bot instructions;
document every step; push to GitHub.

### What changed

- **Steering area** (`steering/`). `instructions.md` is the owner's plain-English instructions, read before
  every script; `references/*.md` are reference files the bot follows, and moving one into `references/off/`
  switches it off. Written so far:
  - `titles-power-of-bad.md`: the negativity effect (bad is stronger than good, the rule of four, loss
    aversion) turned into title and thumbnail rules, with a line that must not be crossed: no false fear,
    and the video must answer the title's threat.
  - `retention-mario-joos.md`: 15 principles paraphrased from Mario Joos's own words (Net Influencer
    interview, 16 Jun 2025; his newsletter, Sep to Nov 2024; VidSummit 2026 as reported by AIR), and how
    this channel applies them.
  - `youtube-guardrails.md`: transform, don't read; no misleading metadata; no expert persona; AI disclosure;
    rights; report studies honestly.
  - `channel-voice.md` (George's voice and banned phrases) and `visual-style.md` (searches for mind and
    spirit footage; no animals).
  - `youtube-success-in-30-days.md`: a placeholder. The Kindle book (ASIN B0GPSLVJKY is Brian Chesson's
    *YouTube Success in 30 Days*) can't be read by the bot: Kindle needs the owner's Amazon login and is
    copy-protected. The owner can paste notes or highlights there.
- **One voice:** `channel.toml` sets `quote = ""`, so George reads everything, quotes included.
- **Long-form by default:** `[video] format = "long"`, 1,250 to 1,700 spoken words (about 9 to 12 minutes).
  Shorts still render (`format = "short"`) but are paused. The old wildlife Short became a test fixture
  (`tests/fixtures/garden-short.toml`).
- **No more bad crops:** long videos take landscape clips only (at least 1.5:1); vertical clips are skipped
  rather than cropped to a strip.
- **Mind and spirit footage:** visual searches like "candle flame", "ink water", "galaxy stars" and
  "book pages". A search's subject now skips describing words ("old book pages" must be tagged "book").
- **Script writer** (`owd/writer.py`, `python -m owd write --chapter N`):
  - Input: one chapter of a public-domain book, recent research from the feeds, and the steering.
  - The chapter is sent as numbered sentences (S1, S2, ...), and the model quotes by number plus the quote's
    first four words. The bot inserts the book's exact words, so quotes can't be invented; if the number and
    the words disagree, the quote is moved to the sentence those words start.
  - Research items are fenced as untrusted text (they come from public feeds).
  - Every factual claim is listed with its basis (a research item, the book, or general knowledge) for the
    owner to check.
  - Checks: structure (rejected and retried), then length, chapter and quote counts and title length (one
    revision). Drafts that are still short are expanded one chapter at a time.
- **Free language models** (`owd/llm.py`): Gemini Flash models, then Flash-Lite, then OpenRouter `:free`
  models, then Cloudflare. A busy model (HTTP 503) is retried once after 20 s; a rate limit or bad JSON moves
  on to the next model; a key error skips the whole provider. Keys never appear in logs or errors.
- **Long-form video** (`owd/produce.py`, `owd/overlays.py`):
  - Chapters: crossfades inside a chapter, a short dip through black between chapters.
  - Quote cards: the footage dims and the quote appears in Libre Baskerville italic (SIL Open Font
    License) with the author's name while George reads it.
  - Chapter titles appear with Roman numerals.
  - `captions.srt` for YouTube's subtitle upload.
  - The description has YouTube chapters (0:00 lines), sources, research links, an AI note and footage
    credits, kept under 5,000 characters.
  - `review.md` is a checklist for the owner: title options, claims to check, quotes, the narration check
    and warnings.

### Findings

- **Free models write short.** Asked for 1,500 words, Gemini Flash wrote 914, Flash-Lite 559, and a full
  revision reached 965. Expanding one chapter per call works: chapter 4 went from 168 to 418 words in one
  call, taking the script to 1,358 spoken words (about 9.7 minutes).
- **Gemini's free Flash models are often busy** (HTTP 503 on 3.8, 3.7 and 3.5 Flash on 12 Oct). Flash-Lite
  answers in seconds but writes thinner scripts. The fallback order handles this.
- **Facts:** the first script's research claims matched the feed summaries (no invented studies), but its
  wording was stronger than the studies' ("drives", "rewires"). Added guardrail 9: report studies honestly.
- **Cloudflare:** `CLOUDFLARE_API_TOKEN` in `.env` is valid for the account, but has no Workers AI
  permission (HTTP 401 on `ai/run`); it's probably the R2 storage token. Cloudflare (images, and the last
  text fallback) needs a separate token named `CLOUDFLARE_AI_TOKEN` with "Workers AI: Read" and "Workers AI:
  Edit".
- **GitHub:** `breme-analytics/Trading-bot` isn't visible without signing in (private or empty). This Mac's
  GitHub CLI is signed in to a different account, which isn't used for this project, and no SSH key here
  is registered with GitHub. Pushing uses a deploy key limited to this one repository.

### Checked

- 114 fast tests and 1 slow test pass. New tests cover the LLM client (mocked HTTP), the writer (validation,
  quote alignment, revision, expansion), book chapters, steering, quote repair, overlays, chapter joins and
  the description.
- A live script was written from *As a Man Thinketh* chapter 2: all 5 quotes found word for word in the book.

### First bot-written long video

`storyboards/2026-10-12-the-mindset-mistake-keeping-your-life-stuck.toml`, rendered to
`output/videos/2026-10-12-the-mindset-mistake-keeping-your-life-stuck/`:

- **Title:** "The Mindset Mistake Keeping Your Life Stuck", with three alternatives in `metadata.json`.
- **Length:** 10:38, 1,353 spoken words, 6 chapters, 51 scenes, 5 quotes.
- **Picture:** 114 shots from 109 Pixabay clips; 1920x1080 H.264 High at about 7.3 Mbps; -14.2 LUFS.
- **Render time on the Mac:** 23 minutes (narration 1.5 min, footage 15 min with first downloads, final
  encode 6 min).

### Fixes after watching it

- **Chapter cards:** the Roman numeral was too small to read. Now "CHAPTER II" at 40 px, with the footage
  dimmed a little more under it.
- **Narration check noise:** "Alan" for Allen and "90%" for "ninety percent" were counted as errors. Numbers
  are now spelled out on both sides, and known name spellings are mapped (`SOUNDS_ALIKE` in `owd/qa.py`).
  Differences fell from 23 to 11; the rest are worth a listen (2:07 "bind", 8:42 "impure").
- **Animals and holidays crept back:** 3 of 114 clips had a dog, birds or a Christmas cat in them ("lake
  calm", "tree seasons", "candle flame"). Clips tagged with an animal or a holiday are now skipped unless the
  scene's search asks for one (`AVOID_TAGS` in `owd/stock.py`).
- **Tests no longer pin the owner's choices:** the tests for `channel.toml` and `steering/` check that they
  load and are valid, not what they say, so editing them never breaks the build.
- **GitHub:** a deploy key limited to `breme-analytics/Trading-bot` was created on this Mac
  (`~/.ssh/owd_breme_analytics_deploy`) and set for this repository only (`git config core.sshCommand`).
  The push waits until the owner adds the public key on GitHub with write access.

### Next

1. Push to GitHub (waiting for the deploy key) and check that both workflows pass on GitHub's runners.
2. `CLOUDFLARE_AI_TOKEN` with Workers AI permission, for concept images and the last text fallback.
3. Telegram approval: the bot sends the thumbnail, title options and review list, plus an R2 download link
   for the video; Approve or Redo.
4. Scheduled runs on GitHub Actions: write and render one long video a week. The time on a 2-core runner is
   not measured yet; a rough estimate is 1 to 1.5 hours a video, well inside the 2,000 free minutes.
5. Review list: point to the exact time of each narration difference, so the owner can listen in seconds.

---

## 2026-10-11: Milestone 2, wildlife sample, Pixabay, reproducibility, news

**Owner's input:** liked voices 4 (George) and 1 (Heart) and asked for wildlife footage; wanted the project
reproducible and cloud-run, developable on a weaker machine; Pexels isn't issuing keys, so Pixabay; reuse
what Breme built (news etc.).

- **Two voices** (George narrates, Heart reads quotes): later reversed by the owner (12 Oct).
- **Pixabay footage** (`owd/stock.py`): searches cached 24 h (Pixabay's rule), clips downloaded once and
  reused, AI-generated and low-quality clips skipped, each clip credited. A clip must be tagged with the
  scene's subject (the first run put cows under "zebra herd").
- **Reproducibility:** `uv` with `uv.lock` (112 packages, hashes, macOS and Linux; CPU-only torch on Linux),
  models pinned to Hugging Face commits (`owd/models.py`), fonts and book texts in the repo, a `Dockerfile`,
  a dev container for GitHub Codespaces (about 60 free hours a month on 2 cores), and two GitHub Actions
  workflows (tests on Ubuntu; build the image and test inside it). A clean copy of the files rebuilt from
  scratch passed all 70 tests. Docker couldn't build on this Mac (Docker Desktop requires an organisation
  sign-in set by an administrator).
- **Narration check** moved from ffmpeg's whisper filter to faster-whisper (pip, any OS). faster-whisper
  1.2.1's own audio decoder breaks on PyAV 19, so audio is decoded by ffmpeg instead.
- **News** (`owd/news.py`, `python -m owd news`): rebuilt Breme's polite feed collector (robots.txt, honest
  User-Agent, size and time limits, manual redirects re-checked, YouTube and Google hosts blocked, 6-hour
  cache). Five research feeds (ScienceDaily Mind & Brain, PsyPost, Greater Good, Psyche, Aeon) and two
  platform feeds (YouTube Official Blog, Tubefilter). The Conversation is skipped: its robots.txt disallows us.
- **Breme:** read without changes. News, hooks and the free-model pattern hold no YouTube data and are
  safe to reuse. Trending lists and channel stats are YouTube API data that Breme's compliance notes forbid
  passing to an outside bot until YouTube answers. Breme has no licence file and belongs to its owner, so
  ideas were rebuilt rather than code copied.
- **Sample:** a 55-second wildlife Short, *Why you replay embarrassing moments*, with its quote checked
  against the book.

---

## 2026-10-11: Milestone 1, voice samples and the render pipeline

- **Plan agreed:** original content only (reposting other creators' videos earns nothing on YouTube and
  risks the channel); niche "old wisdom, decoded", chosen from the owner's own interests (spirituality and
  mind-power classics); free tools only.
- **Built:** Kokoro-82M narration (Apache-2.0, runs on CPU) with word timings; word-by-word ASS captions for
  Shorts and SRT for long videos; slow camera moves over stills; crossfades centred on pauses between
  sentences (frame-exact, no drift); two-pass loudness to YouTube's -14 LUFS; H.264 High with YouTube's
  recommended settings; thumbnails in the Anton font (SIL Open Font License) with an auto-fitted headline.
- **Voice samples:** af_heart, bf_emma, am_michael and bm_george read the same paragraph; a transcription
  check found 0 to 1 word errors each.
- **Installed on the Mac:** Homebrew `ffmpeg-full` (the plain formula lacks libass for captions) and `uv`.
