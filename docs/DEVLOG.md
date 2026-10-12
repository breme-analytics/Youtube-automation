# Development log

Every change to the bot, newest first: what was done, why, and what was checked. Development agents add an
entry here for each change (see `AGENTS.md`). The owner's standing instructions live in
`steering/instructions.md`.

---

## 2026-10-12 (evening): Milestone 4, pictures that match the words, captions, suspense, runs on its own

**Owner's feedback on the first long video:** great video, but the stock footage wasn't in sync with the
narration and distracted instead of helping; add captions; add suspense (Mario Joos); let me steer by uploading
documents; read the Kindle book; commits should show "breme-analytics"; run anywhere for $0, reproducibly;
post or schedule on its own (no Kiro, free OpenRouter models); clean up videos after posting so storage never
fills up; document everything. The repository is `breme-analytics/Youtube-automation` (not Trading-bot).

### Pictures that match what George is saying

- **Why it was off:** each scene's clips were picked by tags alone ("candle"), which says what's in a clip, not
  what it means; long scenes then cycled through several unrelated clips.
- **Fix (`owd/vision.py`, `owd/visuals.py`):** for every scene, the best 4 tag-matched clips are shown (one
  preview still each) to a free vision model (Gemini Flash-Lite) next to the sentence George is reading. It
  scores each from 0 to 10, in meaning and mood as well as subject. The best clip scoring 6 or more is used.
  Tested on the real Pixabay candle clips: it picked a dark, solitary candle (9/10) for a sentence about hope
  burning out, over the cosy and festive ones.
- **When no clip fits:** the scene gets a painting of the moment (`owd/images.py`). The writer now gives every
  scene an `image` description. Paintings come from Cloudflare Workers AI FLUX.2 [klein] inside its free daily
  allowance (about 40 a day), so they need `CLOUDFLARE_AI_TOKEN`. Without it, the scene uses the closest clip
  the vision check found and is flagged for review. Paintings drift very slowly (Mario Joos: no needless
  camera moves).
- **Pollinations dropped:** it was the no-key painting fallback, and the first test painting worked, but during
  the live render it began answering HTTP 402 to every request. Its docs now say all generation needs a key and
  paid credits ("pollen"), so it was removed: nothing in the bot may cost money.
- **One picture per scene:** a scene that runs over several shots stays on its one picture (another part of
  the same clip), so the picture never wanders away from the words. Shots in long videos can last up to 9 s.
- **Writer:** one scene is one idea in 35 to 60 words, with a footage search that literally shows that idea.

### Captions

- Burned-in captions on long videos (`owd/captions.py`): a short phrase at the bottom in Lato Bold (SIL Open
  Font License), the spoken word in gold. They hide while a quote card or chapter title is on screen.
  `captions = true` in `channel.toml`; `captions.srt` is still uploaded for YouTube's own subtitles.

### Suspense (Mario Joos)

- Read Mario Joos's two LinkedIn posts of retention tips and added them to `steering/references/retention-mario-joos.md`
  (now 27 principles, each sourced).
- **Silence before reveals:** a `[pause]` in a script makes George hold a 1.1-second beat (principle 16).
- **Open loop:** the hook raises one question (`open_loop`) that only the last chapter answers.
- **Cliffhangers:** every chapter but the last ends on a turn, a question or a reveal.
- The writer's checks require an open loop and 2 to 8 pauses, and ask for a revision if either is missing.

### Steering by document

- `steering/references/` now accepts PDF, Word (.docx), text and Markdown files, uploaded on GitHub (Add file >
  Upload files). Documents over 12,000 characters are condensed once by a free model into
  `<name>.digest.md`, saved next to them so the owner can read (and edit) exactly what the bot took. A broken
  or empty upload is skipped with a warning, never stopping a run.
- **The Kindle book:** not read. Signing in to the owner's Amazon account with her password, and extracting a
  copy-protected ebook, would break Amazon's terms and copyright. She can export her highlights or notes instead.
  She should also change the password she shared in the chat.

### Runs on its own, for $0

- **`python -m owd run`** (`owd/autopilot.py`): picks the next unused chapter (`state/videos.json`), writes the
  script, renders the video and delivers it.
- **Delivery, `review` mode (default):** a GitHub release holds the video, thumbnail, captions and metadata
  (GitHub releases have no storage or bandwidth limit; files under 2 GiB), and an issue "Ready to post: ..."
  with download links and the checklist (GitHub emails the owner).
- **Delivery, `auto` mode:** uploads to YouTube as private with `publishAt` set to the next posting slot
  (Tue/Fri 18:00 Nairobi by default), `containsSyntheticMedia` true, category Education, plus thumbnail and
  captions (`owd/youtube.py`). The one-time sign-in uses Google's device flow (`python -m owd youtube-login`),
  so it works from a phone.
- **Why review mode first:** YouTube locks every API upload as private until the project passes YouTube's free
  API audit, and it can't be unlocked afterwards.
- **Cleanup (`python -m owd cleanup`, daily workflow):** a video is "posted" when its YouTube time has passed or
  the owner closes its issue. Its release files are deleted `keep_days` (7) after that, or 7 days after it was
  made if nobody posts it, and the issue is closed. Old workflow caches and run logs are deleted too.
- **Workflows:** `produce.yml` (Mon and Thu), `cleanup.yml` (daily), plus `tests.yml` and `image.yml`. Each run
  commits `state/` and the storyboard back, so any machine can pick up where the last run stopped.
- **Models:** OpenRouter's free models now come first (`channel.toml` `[llm]`, five of them), because Gemini's
  free text quota is small and is better spent on the picture checks.
- **Cloudflare R2 dropped:** from this network, every R2 host fails the TLS handshake (even a random
  account's), while api.cloudflare.com works. GitHub releases do the same job for free, so `owd/storage.py` was
  removed and the R2 keys are no longer needed.

### Findings

- **OpenRouter free models alone** wrote a complete script for *As a Man Thinketh* chapter 4 with no problems
  flagged: 1,500 words, 6 chapters, 4 quotes (all found word for word), 4 pauses, a painting for every scene;
  about 15 minutes.
  - **Model results that day:** Nemotron Ultra answered in 2 to 3 minutes; Nemotron Super sometimes cut off,
    other times answered; Gemma 4 31B was rate-limited; Inkling refused the key (403).
  - **Two flaws found and fixed:** the model pasted research ids into the narration ("...the night. R1"), so
    George would have read them aloud; they're now removed automatically. It also overstated one-study findings
    ("rewires", "protects the heart"); the prompt now demands the study's own wording, and the sample's lines
    were softened by hand.
- Gemini's free image models (Nano Banana) answered "quota exceeded" on this key, so they aren't used.

### GitHub

- The remote is now `git@github.com:breme-analytics/Youtube-automation.git`. Commits from this repository show
  `breme-analytics` (`341067996+breme-analytics@users.noreply.github.com`), set for this repository only.
- The key the owner added (ending `...dlBLcSs6s`, fingerprint `SHA256:HkFZLtQt...`) has its private half on
  another computer, not this Mac, so this Mac can't use it. A deploy key for this Mac was made instead
  (`~/.ssh/youtube_automation_deploy`); pushing waits until the owner adds it. The old, never-registered
  Trading-bot key was deleted. The Mac's `id_ed25519` turned out to be a deploy key for `Trading-bot` and is
  left alone.

### Checked

- 148 tests pass (fast and slow). New tests cover:
  - the vision judge (scores, pacing, rate limits, a refused key);
  - scene visuals (vision pick, painting fallback, closest-clip fallback, fallback searches);
  - the painting maker (cache, refused token, used-up allowance, no token);
  - pauses, captions hidden under cards, PDF and Word steering, digests;
  - state and next chapter, posting slots, the GitHub client, the YouTube upload, schedule, thumbnail,
    captions and device login, and cleanup timing;
  - picture-to-narration sync (`tests/test_sync.py`).
- Live: the vision check on Pixabay candles; a full OpenRouter-only script; a full render of it.

### Bug found in the second video: pictures drifting ahead of the narration

- **What happened:** checking frames of the OpenRouter-written video, a shot of bare feet on a beach appeared
  while George said "Imagine a seedling pushing through dark soil", although the vision check had picked a
  seedling clip (9/10) for that scene. Measuring every chapter showed chapter 4's picture was 48.6 s long
  instead of 204.3 s.
- **Cause:** when a scene ran longer than its clip, a shot rendered short (4.2 s instead of 6.9 s, because only
  2 s of the clip's last frame was held). One short input ends ffmpeg's crossfade chain early, so the rest of the
  chapter was lost, every later picture ran 156 s ahead of the words, and the video ended on a 2.5-minute frozen
  frame.
- **The first long video was not affected:** all its chapters matched their planned length to the frame, so
  the owner's "not in sync" was about meaning, which the vision check fixes.
- **Fixes:**
  - every shot is forced to exactly its planned number of frames before crossfading (the last frame is held
    if a file is short);
  - a shot that runs out of footage holds its last frame for as long as needed;
  - a scene keeps up to three clips that fit its words and moves to the next one when a clip runs out;
  - before the final encode, every chapter's picture length is checked against the plan, and the run stops
    rather than deliver a drifting video.
- **Footage fallbacks:** a scene whose own search finds nothing (like "quill writing") now tries each word on
  its own, then the channel's fallback searches (`channel.toml` `[footage] fallback`), and the vision check
  still decides whether anything fits.
- **Re-rendered and verified:** every chapter's picture matches its planned length to within 7 ms; the
  seedling clip is on screen exactly when George says "seedling"; the last minute moves normally; 49 clips,
  41 vision checks, 14 minutes on the Mac. One scene ("brain neurons", best clip 4/10) used its closest clip
  because there is no Cloudflare token yet for paintings, and was flagged in `review.md`.
- **Checked by the owner:** her frames from the new render show the seedling clip under "Imagine a seedling
  pushing through dark soil", a lotus under "Pick one legitimate purpose", the chapter V card with the
  captions hidden, and changing pictures to the very end.
- **Caption breaks:** one of her frames showed a caption ending on "the" ("He who does this has become the",
  then "conscious, ..."). In that video 34 of 249 caption pages ended on a word that leans on the next one
  ("the", "of", "into", "and", "his"). Subtitle style guides (BBC, Netflix) break before such words, never
  after. Now caption pages, the uploaded SRT's line breaks and its cue splits avoid ending on them, unless
  punctuation follows; a dash spoken as its own word counts as a break, like a comma. Measured on the same
  video's words: 0 of 256 pages and 0 of 210 SRT cues end that way, and the SRT text is unchanged. The
  rendered file still has the old breaks (it was made before the fix); every new video gets the new ones.

### Next

1. The owner adds this Mac's deploy key to `Youtube-automation` with write access; then push, and watch the
   first `tests` and `image` runs on GitHub.
2. Add the repository secrets (docs/DEPLOY.md step 2), ideally with a free `CLOUDFLARE_AI_TOKEN` for paintings.
3. Run `produce` by hand once and measure how long a video takes on GitHub's 2-core machine (not measured yet;
   estimated 60 to 120 minutes).
4. For posting on its own: Google Cloud OAuth client, `python -m owd youtube-login`, and YouTube's free API
   audit; then `mode = "auto"`.

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
