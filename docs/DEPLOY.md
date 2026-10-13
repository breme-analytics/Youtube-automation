# Deploying the bot (free, no Mac needed)

The bot runs on **GitHub Actions** in the private repository `breme-analytics/Youtube-automation`. Nothing runs on
a computer of yours, and nothing costs money. This page lists every step in order, then every known caveat and
its fix.

## How it runs

| When | Workflow | What it does |
|---|---|---|
| Every day, 06:15 Nairobi | `produce.yml` | Daily checks and clean-up (the storage rules below, whether scheduled videos went public, old caches and logs), about 1 to 2 minutes. On video days (`channel.toml` `make_days`, Mondays and Thursdays) it also makes one video: next chapter → script → narration → render → **stored** → delivered, estimated 1 to 2 hours |
| When you start it | `add-book.yml` | Adds a public-domain book by its Project Gutenberg number, after checking its chapters |
| Every push (not the bot's own progress commits) | `tests.yml` | Runs every test on a clean Linux machine |
| When the environment changes | `image.yml` | Builds the Docker image and tests inside it |

Any of them can be run by hand: **Actions** tab → the workflow → **Run workflow**. Starting `produce` by hand
always makes a video, with an optional angle. `produce` and `add-book` queue behind each other, never at the same
time. If one fails, it opens an issue "The bot needs attention" with a link to the run (later failures add
comments to the same issue). Before each video, the bot checks its monthly Actions minutes (`[actions]
monthly_minutes`; see caveat 7). The separate daily `cleanup.yml` of 13 October was merged into `produce.yml`
the same evening. How to use it day to day: `docs/GUIDE.md`; how it works inside: `docs/HOW-IT-WORKS.md`.

## Where videos are stored, and when they're deleted

Every video is stored in the cloud before it's posted, in both modes: a **GitHub release** in this repository
(tag `video-<date>-<title>`), holding `video.mp4`, `thumbnail.jpg`, `captions.srt` and `metadata.json`. GitHub
releases are free, with no limit on total size or downloads; each file must be under 2 GiB. A 10-minute video is
about 550 MB. The rules (`channel.toml` `[storage]`, code in `owd/storage.py`):

1. **Always stored.** If the copy can't be stored, the run fails, and the next run makes that chapter again.
2. **Deleted after posting.** A posted video's copy is kept `keep_days_after_posting` (7) days, in case something
   went wrong on YouTube, then deleted. Posted means: you closed its issue (review mode), or YouTube shows it
   public (auto mode).
3. **Discarded copies go at once.** Close a video's issue as **not planned** and its copy is deleted at the next
   cleanup. A failed run's half-stored copy is deleted the same way, and so is any `video-` release that nothing
   knows about.
4. **Never more than `max_videos` (4) stored**, about 2.2 GB. When a new video needs room, copies of posted videos
   are deleted first. If all 4 are still waiting to be posted, the bot makes no new video (the run page says so)
   until you post or discard one. Unposted videos are never deleted for age, so finished work isn't thrown away.

`python -m owd storage` lists what's stored and when each copy goes.

## Delivery: `mode` in `channel.toml` `[schedule]`

- `review` (the default): the bot opens an issue "Ready to post: ..." with the stored copy's download links, the
  title, the description and the checklist. GitHub emails you. Upload it in YouTube Studio, then close the issue.
- `auto`: the bot uploads to YouTube itself, private, scheduled to go public at the next posting slot
  (`publish_days`, `publish_time`, `timezone`), with the thumbnail and captions. Its issue "Scheduled: ..." says
  when. Once the video is public the bot closes the issue. If YouTube refuses the upload, or the video isn't public
  30 minutes after its time, the issue becomes "Ready to post: ...", says why and what fixes it, and you post the
  stored copy by hand.

## 1. Repository settings (once)

1. **Push access for development:** Settings → **Deploy keys** → the key for each computer you push from, with
   **Allow write access** ticked. (The workflows use GitHub's own token and need no key.)
2. **Let workflows write:** Settings → Actions → General → **Workflow permissions** → **Read and write
   permissions** → Save. The workflows ask for the permissions they need (store releases, open issues, save
   progress); this makes sure nothing blocks them.
3. **Keep it free:** don't add a payment method to the account. Without one, GitHub blocks usage at the free
   allowance instead of billing for it (see "Caveats" below).
4. **Turn on two-factor sign-in** for the GitHub account (Settings → Password and authentication): the repository
   holds the keys to your channel.
5. **Hear from the bot:** on the repository's main page, **Watch** → **All Activity**; and at
   github.com/settings/notifications, under **Watching**, tick **Email**. The bot tells you everything through
   issues (caveat 13).

## 2. Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Secret | Where to get it (all free) | Needed for |
|---|---|---|
| `PIXABAY_API_KEY` | pixabay.com/api/docs, after signing in | Footage |
| `OPENROUTER_API_KEY` | openrouter.ai/keys | Writing the scripts (free models) |
| `GEMINI_API_KEY` | aistudio.google.com/apikey | Matching pictures to the words; script fallback |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard, right sidebar | Paintings for scenes no clip fits (recommended) |
| `CLOUDFLARE_AI_TOKEN` | Cloudflare → AI → Workers AI → **Use REST API** → Create a Workers AI API Token | Paintings (recommended) |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | Step 4 below | Only for `auto` mode |

Without the Cloudflare token there are no paintings: a scene no clip fits uses the closest clip, flagged for review.

## 3. Your first video (review mode)

Actions → **produce** → **Run workflow**. One to two hours later an issue "Ready to post: ..." appears and GitHub
emails you. Follow its checklist, then close it. (How long a run takes on GitHub's 2-core machines hasn't been
measured yet; the first run will tell.)

## 4. Posting on its own (auto mode)

1. **Google Cloud project** (free, no card): console.cloud.google.com → New project → APIs & Services → enable
   **YouTube Data API v3**.
2. **Google Auth Platform → Audience:** user type **External**, then **Publish app**. See caveat 2 for why
   publishing matters.
3. **Data access:** add the scopes `.../auth/youtube.upload` and `.../auth/youtube.force-ssl`.
4. **Clients → Create client → Desktop app.** Put the client ID and secret into the secrets `YOUTUBE_CLIENT_ID` and
   `YOUTUBE_CLIENT_SECRET`, and into `.env` on the computer you'll sign in from.
5. **Sign in once**, on any computer with a browser and this project set up: `uv run python -m owd youtube-login`.
   A Google page opens; sign in as the channel's owner and allow access. Because Google hasn't reviewed the app,
   it first shows "Google hasn't verified this app": choose **Advanced**, then **Go to <your app's name>
   (unsafe)**. It's safe here: the app is yours and only you use it. The command prints the channel it will post
   to and a token: put the token in the secret `YOUTUBE_REFRESH_TOKEN`.
6. Optional but recommended: **verify the channel** at youtube.com/verify (free, by phone) for custom thumbnails.
7. Set `mode = "auto"` in `channel.toml` (edit it on GitHub). Watch the first video's issue: if YouTube keeps it
   private, see caveat 1.

## 5. Steering from anywhere

Edit `steering/instructions.md` on GitHub (the pencil icon), or upload a PDF, Word or text file into
`steering/references/` (Add file → Upload files). The next run uses it. Long documents are condensed once into
`<name>.digest.md`, which the bot commits back so you can read what it took from them.

## Caveats and fixes

Checked against Google's and GitHub's documentation on 12 and 13 October 2026.

| # | Caveat | What the bot does | Fix |
|---|---|---|---|
| 1 | **YouTube may keep API uploads private.** Since July 2020, videos uploaded through a Google Cloud project that hasn't passed YouTube's API audit were locked private, and a locked video can't be made public. YouTube's reference pages now say such uploads are *not* restricted, but the change isn't announced in the API's revision history, so the bot doesn't rely on it. | Checks every scheduled video after its publish time. If it isn't public, its issue becomes "Ready to post", explains, and links the stored copy. | Post the stored copy by hand and delete the private one in Studio. Apply for the free audit (support.google.com/youtube/contact/yt_api_form; use case: uploading your own videos to your own channel). Until it's approved, set `mode = "review"`. |
| 2 | **Sign-ins expire after 7 days while the OAuth app is in "Testing".** | The upload fails with `invalid_grant`; the video goes to you by hand, and the issue says so. | Publish the app (Google Auth Platform → Audience → Publish app), run `youtube-login` again and update `YOUTUBE_REFRESH_TOKEN`. A published but unverified app shows a warning screen at sign-in and allows 100 users, which is plenty for one owner. |
| 3 | **A sign-in can stop working later**: unused for 6 months, access removed at myaccount.google.com/permissions, or more than 100 sign-ins for the same client. | Same as 2. | Run `youtube-login` again and update the secret. In auto mode the token is used twice a week, so it never sits unused. |
| 4 | **Google's "enter a code at google.com/device" sign-in can't grant uploads of captions** (it allows only the `youtube` and `youtube.readonly` scopes). | Fixed in the bot: `youtube-login` now uses the desktop-app browser sign-in with PKCE. | Create a **Desktop app** client (step 4.4), not a "TVs and Limited Input devices" one. |
| 5 | **Custom thumbnails need a verified YouTube account**; so do videos over 15 minutes. | The thumbnail is skipped with a note (YouTube picks a frame); the video is still posted. The bot's videos are about 9 to 12 minutes. | Verify once at youtube.com/verify (free, by phone). |
| 6 | **YouTube's daily allowance**: 10,000 units and 100 uploads a day per project. A video uses 1 upload plus about 450 units (captions 400, thumbnail 50, checks 1 each). | If it's ever used up, the upload fails and the video goes to you by hand. | Nothing needed at two videos a week. It resets at midnight Pacific time. More quota needs the audit form. |
| 7 | **GitHub Actions minutes**: a free account gets 2,000 minutes a month for **all** its private repositories together (here, also the trading bot), on 2-core machines; GitHub rounds each job up to a whole minute. A public repository's minutes are unlimited. Two videos a week at an estimated 1 to 2 hours each, plus the daily 1 to 2 minute check and tests, is roughly 600 to 1,150 minutes a month. Jobs stop after 6 hours (`produce` stops itself at 5). | Before each video the bot adds up this repository's minutes this month; if the video wouldn't fit its share (`[actions] monthly_minutes`, 1,000), it makes none and opens "The bot paused: this month's Actions minutes are used". Without a payment method, GitHub blocks all runs (the trading bot's too) once the account's minutes are gone; it never bills. | Set `monthly_minutes` to what the trading bot leaves (check Settings → Billing and plans → Usage). Use fewer video days (`make_days`, or the panel). Making this repository public would give unlimited minutes, but its stored videos, scripts and issues would become public. |
| 8 | **GitHub release files must be under 2 GiB** each: about 40 minutes of video at the bot's quality. | A larger file stops the run before anything is uploaded, with a clear message. | Keep videos under about 35 minutes, or lower the bitrate in `owd/render.py`. |
| 9 | **The repository is private**, so release downloads need you signed in to GitHub. | Links in the issues work when you're signed in. | Sign in on the device you download from. |
| 10 | **GitHub's terms allow limiting "excessive" file hosting.** | Storage is capped at 4 videos and deleted after posting, so use stays small. | Nothing needed; don't raise `max_videos` far. |
| 11 | **Workflow caches**: 10 GB per repository; entries unused for 7 days are removed. | Footage unused for 30 days is dropped from the cache, and old caches are deleted daily. | Nothing needed. |
| 12 | **Free AI models are sometimes busy or limited** (OpenRouter's free models about 50 requests a day; Gemini's free tier is small). | Each model is tried in turn (`channel.toml` `[llm]`); if all fail, the run fails and the next one tries again. | Run `produce` by hand later, or reorder the models in `channel.toml`. |
| 13 | **GitHub emails about a scheduled run only the person who first created the workflow** (GitHub's docs). The workflows were pushed with a deploy key, so that may not be you, and a failed run could go unnoticed. | A failed `produce` or `cleanup` run opens an issue "The bot needs attention: a run failed" with a link; later failures comment on it. GitHub emails you about new issues in repositories you watch. | Watch the repository with email on (step 1.5). |
| 14 | **The bot needs a steady supply of chapters**: one per video. Five books are loaded (43 chapters, about 20 weeks at two a week). | From 4 chapters left, it opens "The bot needs a new book" (and each video's issue carries a heads-up); with none left, runs fail with "Add a book". | Add books from the control panel or Actions → add-book (`docs/GUIDE.md`, "Adding a book"). |
| 15 | **GitHub Pages is free only for public repositories**, so the control panel can't be hosted from the private bot repository. | The panel lives in its own public repository that holds only the page: no bot code, no data, no keys. It reads and changes the private repository from your browser, with your token. | Create the public repository and turn on Pages (`docs/GUIDE.md`, "Control panel"). |
| 16 | **Project Gutenberg's website blocks automated downloads** ("for human users only"; IP addresses get blocked). | Books are downloaded from Gutenberg's official mirror, gutenberg.pglaf.org, which is meant for this. | Nothing needed. |
| 17 | **The control panel's token can change the bot**: anyone with it could start runs or edit settings. | It's a fine-grained token for this one repository, kept only in your browser, sent only to GitHub. | Give it an expiry, tick "Remember" only on your own devices, and delete it on GitHub if it leaks (`docs/KEYS.md`). |

## What it costs: nothing

| Service | Free allowance | The bot's use |
|---|---|---|
| GitHub Actions (private repository) | 2,000 minutes a month | Roughly 650 to 1,250 minutes (estimate) |
| GitHub releases (video storage) | No limit on total size or downloads; files under 2 GiB | At most 4 videos (about 2.2 GB) at a time |
| OpenRouter free models | About 50 requests a day | About 5 per video |
| Gemini (AI Studio) | A few hundred Flash-Lite requests a day | About 50 per video (picture checks) |
| Pixabay | 100 requests a minute; searches cached 24 h | About 50 searches per video |
| Cloudflare Workers AI (recommended) | 10,000 neurons a day | About 40 paintings |
| YouTube Data API | 10,000 units and 100 uploads a day | About 450 units per video |

No service here has a card on file, so none of them can charge you.

## If something goes wrong

A failed run opens an issue "The bot needs attention" with a link to it; `docs/GUIDE.md`, "When something goes
wrong", lists the common reasons. In short:

- **A run failed**: Actions → the red run → read the last lines. The video's entry in `state/videos.json` says
  `failed` with the reason; the next run makes the same chapter again, and the cleanup deletes any half-stored copy.
- **"Storage is full"** on a produce run: four videos are waiting for you. Post them (close their issues) or close
  the ones you don't want as not planned.
- **"rate limited" everywhere**: the free models are busy; the next scheduled run usually works, or run it by hand.
- **`invalid_grant` from YouTube**: see caveat 2.
