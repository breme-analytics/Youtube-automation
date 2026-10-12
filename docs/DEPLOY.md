# Deploying the bot (free, no Mac needed)

The bot runs on **GitHub Actions** in the `breme-analytics/Youtube-automation` repository. Nothing runs on a
computer of yours, and nothing costs money. This page lists every step, in order.

## How it runs

| When | Workflow | What it does |
|---|---|---|
| Monday and Thursday, 06:15 Nairobi | `produce.yml` | Picks the next book chapter, writes the script, narrates, renders and delivers one video |
| Every day, 05:40 Nairobi | `cleanup.yml` | Deletes the download files of posted videos (and of any older than `keep_days`), plus old caches and logs |
| Every push | `tests.yml` | Runs every test on a clean Linux machine |
| When the environment changes | `image.yml` | Builds the Docker image and tests inside it |

You can also run any of them by hand: **Actions** tab → choose the workflow → **Run workflow**. `produce` lets
you give an angle for that one video.

**Delivery** depends on `mode` in `channel.toml` `[schedule]`:

- `review` (the default, and the only option until YouTube's audit passes): the video, thumbnail, captions and
  description go into a GitHub release, and the bot opens an issue titled "Ready to post: ..." with download
  links and the checklist. GitHub emails you. You upload it in YouTube Studio, then close the issue. A few days
  later the cleanup deletes the files.
- `auto`: the bot uploads to YouTube itself, privately, scheduled to go public at the next posting slot
  (`publish_days`, `publish_time`, `timezone`), and adds the thumbnail and captions. The cleanup marks it posted
  once the time has passed.

## 1. Repository settings (once)

1. **Push access for development:** Settings → **Deploy keys** → the key named for this Mac, with **Allow write
   access** ticked. (Only needed to push from a computer. The workflows use GitHub's own token.)
2. **Let workflows write:** Settings → Actions → General → **Workflow permissions** → **Read and write
   permissions** → Save.
3. **Keep it free:** Settings → Billing and plans → make sure the Actions **spending limit is $0** (it is by
   default on a free account). If the free minutes ever ran out, runs would stop rather than cost money.
   A public repository has unlimited free minutes; a private one has 2,000 a month. One video takes roughly
   60 to 120 minutes on GitHub's machines, so two a week fit in a private repository.
4. Add a label named `ready-to-post` (Issues → Labels → New label), or let the bot create it on first use.

## 2. Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Secret | Where to get it (all free) | Needed for |
|---|---|---|
| `PIXABAY_API_KEY` | pixabay.com/api/docs, after signing in | Footage |
| `OPENROUTER_API_KEY` | openrouter.ai/keys | Writing the scripts (free models) |
| `GEMINI_API_KEY` | aistudio.google.com/apikey | Matching pictures to the words; script fallback |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard, right sidebar | Paintings for scenes no clip fits (recommended) |
| `CLOUDFLARE_AI_TOKEN` | Cloudflare → AI → Workers AI → **Use REST API** → Create a Workers AI API Token | Paintings (recommended) |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | Step 4 below | Only for `auto` mode |

Without the Cloudflare token there are no paintings: a scene that no clip fits uses the closest clip, and the
review list flags it.

## 3. Your first video (review mode)

Actions → **produce** → **Run workflow**. About one to two hours later, an issue "Ready to post: ..." appears
and GitHub emails you. Follow the checklist in the issue, then close it.

## 4. Posting on its own (auto mode)

YouTube locks every video uploaded through the API as **private** until the Google Cloud project passes YouTube's
free API compliance audit, and it can't be unlocked afterwards. So:

1. **Google Cloud project** (free): console.cloud.google.com → New project → enable **YouTube Data API v3**.
2. **OAuth consent screen** (Google Auth Platform): External; add the channel's Google account as a test user;
   scopes `youtube.upload` and `youtube.force-ssl`. Then **Publish app**: while it says "Testing", Google expires
   the sign-in after 7 days.
3. **Client:** Clients → Create client → **TVs and Limited Input devices**. Copy the client ID and secret into
   the secrets `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` (and into `.env` on the machine you sign in from).
4. **Sign in once**, from any computer with the project set up: `uv run python -m owd youtube-login`. It shows a
   code; open google.com/device on your phone, sign in as the channel's owner and allow. Put the printed token in
   the secret `YOUTUBE_REFRESH_TOKEN`.
5. **Apply for the audit:** the Audit and Quota Extension form (support.google.com/youtube/contact/yt_api_form).
   Use case: uploading your own original videos to your own channel. It's free; approval can take weeks.
6. When it's approved, set `mode = "auto"` in `channel.toml`.
7. To set custom thumbnails through the API, verify the channel once at youtube.com/verify (free, by phone).

## 5. Steering from anywhere

Edit `steering/instructions.md` on GitHub (the pencil icon), or upload a PDF, Word or text file into
`steering/references/` (Add file → Upload files). The next run uses it. Long documents are condensed once into
`<name>.digest.md`, which the bot commits back so you can read what it took from them.

## 6. What it costs: nothing

| Service | Free allowance | The bot's use |
|---|---|---|
| GitHub Actions | Unlimited (public repo) or 2,000 min/month (private) | About 4 to 8 hours a month |
| GitHub releases | No storage or bandwidth limit; files under 2 GiB | One release per video, deleted after posting |
| OpenRouter free models | 50 requests a day | About 5 per video |
| Gemini (AI Studio) | A few hundred Flash-Lite requests a day | About 50 per video (picture checks) |
| Pixabay | 100 requests a minute; searches cached 24 h | About 50 searches per video |
| Cloudflare Workers AI (recommended) | 10,000 neurons a day | About 40 paintings |
| YouTube Data API | 10,000 units and 100 uploads a day | About 500 units per video |

No service here has a card on file, so none of them can charge you.

## If something goes wrong

- A run failed: Actions → the red run → read the last lines. The video's entry in `state/videos.json` says
  `failed` with the reason, and the next run tries the same chapter again.
- "rate limited" everywhere: free models are busy; the next scheduled run usually works. Or run it by hand later.
- `invalid_grant` from YouTube: the sign-in expired (the OAuth app is still in Testing). Publish it, then
  repeat step 4.4.
