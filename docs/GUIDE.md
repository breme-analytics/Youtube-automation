# Using the bot

The bot lives in the private GitHub repository **github.com/breme-analytics/Youtube-automation** and runs itself
on GitHub Actions every morning. You control it from two places:

- **The control panel**, a small web page (`panel/`, hosted on GitHub Pages once it's set up, below). It covers
  the everyday things: what's happening, posting videos, steering, books, video days and minutes.
- **GitHub itself**, for everything else. Every control is listed below, so nothing depends on the panel.

How the bot works inside: `docs/HOW-IT-WORKS.md`. Keys and tokens: `docs/KEYS.md`.

## Where to do what

| You want to | Control panel | On GitHub |
|---|---|---|
| See what's happening | Overview, Recent runs | **Actions** → the newest run; its summary lists the secrets it saw, the storage and the minutes |
| Post a video | Videos waiting → open it → **Posted** | **Issues** → "Ready to post: ..." → follow its checklist → **Close issue** |
| Not post a video | Videos waiting → **Don't post** | The issue: **Close issue** ▾ → **Close as not planned** |
| Change how it writes | Steering → edit → **Save instructions** | `steering/instructions.md` → pencil icon → **Commit changes** |
| Give it a document to follow | Steering → Add a document | `steering/references/` → **Add file → Upload files** |
| Give one video an angle, or make one now | Make a video now | **Actions** → **produce** → **Run workflow** → angle → **Run workflow** |
| Add a book | Books → Add a book | **Actions** → **add-book** → **Run workflow** → the Gutenberg number |
| Change the video days | Video days and Actions minutes | `channel.toml`: `make_days = ["Mon", "Thu"]` |
| Change this bot's monthly minutes | Video days and Actions minutes | `channel.toml`: `monthly_minutes = 1000` |
| Change voice, length, captions, paintings, review or auto, storage, book order | — | `channel.toml` → pencil icon → **Commit changes**. Comments in the file explain each setting |
| Pause the bot | — | **Actions** → **produce** → **...** → **Disable workflow** (**Enable workflow** restarts it) |
| See the stored videos | — | **Releases**, on the right of the repository's main page |
| Check the free minutes | Overview (this bot's share) | **Settings → Billing and plans → Usage** (all repositories) |

A run uses whatever is on GitHub when it starts; a change made during a run applies to the next one.

## The daily run, and Actions minutes

The workflow **produce** runs every morning at 06:15 Nairobi:

- **Every day** (about 1 to 2 minutes): what you posted or discarded, whether scheduled videos went public,
  deleting stored copies that are due, the status file for the panel, and old caches and logs.
- **On video days** (`make_days`, Mondays and Thursdays now) or when you press **Run workflow**: a new video.
  Estimated at 1 to 2 hours; the first real run will measure it, and the panel then shows the measured figure.

GitHub's free plan gives **2,000 minutes a month for all your private repositories together**, so this bot
shares them with the trading bot. GitHub rounds every job up to a whole minute. A rough monthly total:

| Videos a week | This bot's minutes a month (estimate, videos at 2 hours) |
|---|---|
| 1 | about 570 |
| 2 (now) | about 1,080 |
| 3 | about 1,600 |

Plus about 5 to 10 minutes for each code change the developer pushes (tests).

**The budget:** `monthly_minutes` (now 1,000) is this bot's share. Before each video, the bot adds up what this
repository has used this month. If the video wouldn't fit, it makes no video and opens an issue "The bot paused:
this month's Actions minutes are used", until the minutes reset on the 1st. It can't see the trading bot's
use, so set the share to what the trading bot leaves: check **Settings → Billing and plans → Usage** after a few
days of both running. To use fewer minutes, choose fewer video days.

## Three ways to steer

1. **Standing instructions:** `steering/instructions.md`, plain English, newest at the top. They apply to every
   video until you change them.
2. **Documents:** `steering/references/`. The bot reads every document there before it writes. Long ones are
   condensed once into `<name>.digest.md`; open it to see what the bot took. Move a document into
   `references/off/` to switch it off.
3. **One video:** the angle box when you start a video ("tie it to exam stress").

## How the bot tells you things

GitHub emails you about every new issue, because you watch the repository (Watch → All Activity). Check that
github.com/settings/notifications has **Email** ticked under **Watching**.

| Issue | Means |
|---|---|
| "Ready to post: <title>" | A video is ready. Download, post, close the issue |
| "Scheduled: <title>" (auto mode) | It's on YouTube and goes public at the time given. Nothing to do |
| "The bot needs a new book" | 4 or fewer chapters left. Add a book; the issue closes itself once there are enough |
| "The bot is waiting for you to post videos" | 4 videos are stored and waiting, so it isn't making more |
| "The bot paused: this month's Actions minutes are used" | See the budget above |
| "The bot can't post to YouTube" | The YouTube sign-in expired or is missing; the issue says how to fix it |
| "The bot needs attention: a run failed" | Open the link; later failures add comments |

The "needs" issues close themselves when the problem is gone.

## When something goes wrong

1. Open the run from the issue's link. The reason is at the top of the page, or in the last lines of the red step.
2. Common reasons:

   | The run says | What to do |
   |---|---|
   | "Add these repository secrets" | A secret is missing or misnamed: Settings → Secrets and variables → Actions |
   | "rate limited", "busy" or "overloaded" | The free AI models were busy. Start the video again later |
   | "Every chapter of every book ... already has a video" | Add a book |
   | "invalid_grant" | The YouTube sign-in expired: `docs/DEPLOY.md`, caveat 2 |
   | "Not added:" (add-book) | The reason follows; often the chapters couldn't be found. Ask the developer |

3. Still stuck? Copy the last 30 lines of the red step and send them to the developer.

Every known limit, what the bot does about it, and the fix: `docs/DEPLOY.md`, "Caveats and fixes".

## Adding a book

The bot needs a steady supply of chapters: one per video. Five books are loaded (43 chapters, about 20 weeks at
two a week).

1. **Find the book** on gutenberg.org. It must be public domain (an author who died more than 70 years ago) and
   in English. Its number is in its web address: gutenberg.org/ebooks/**14209**.
2. **Add it** from the control panel (Books → Add a book) or from **Actions → add-book → Run workflow**. Give the
   number; optionally the chapters to use (titles from its contents, separated by commas) and how to credit it.
3. **The bot checks it** (about a minute): it downloads the book from Gutenberg's official mirror, makes sure every
   chapter can be found, saves it in `sources/` and lists it in `channel.toml`. If something's wrong, the run
   fails with the reason and an issue tells you.

Good next candidates: Emerson's other ten essays are already in `sources/` (remove the `chapters` line of
`emerson-essays` in `channel.toml` to use all twelve). For more, search gutenberg.org for authors such as James
Allen, Epictetus or Seneca, and check the book is in English.

## Control panel: setting it up (once)

GitHub Pages is free only for **public** repositories, so the panel lives in a small public repository of its
own that holds just the page (no bot code, no data, no keys). Your private repository stays private.

1. **Create the repository:** github.com/new → name `youtube-automation-panel` → **Public** → leave "Add a
   README" unticked → **Create repository**.
2. **Let this Mac publish to it:** in that repository, Settings → Deploy keys → **Add deploy key** → title
   "Mac (panel)", paste the key below, tick **Allow write access** → **Add key**.
   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILftFlBzNrLxdfM9o4K77N9v26K5Rn4CCdMa9pnW03m+ youtube-automation-panel deploy key (Mac)
   ```
   Then tell the developer, who runs `panel/publish.sh`. (Or upload the five files in `panel/`, without the tests,
   with **Add file → Upload files**.)
3. **Turn on Pages:** that repository's Settings → Pages → Source **Deploy from a branch** → Branch **main**,
   folder **/ (root)** → **Save**. The panel appears at **https://breme-analytics.github.io/youtube-automation-panel/**.
4. **Make the panel's token:** github.com/settings/personal-access-tokens → **Fine-grained tokens** → **Generate
   new token**. Name it "Control panel"; pick an expiry (90 days); **Only select repositories** →
   `Youtube-automation`; permissions **Actions**, **Contents** and **Issues** set to **Read and write** (Metadata
   is read-only automatically) → **Generate token**, and copy it.
5. **Open the panel** and paste the token. Tick "Remember on this device" only on your own phone or computer.

The token goes only to GitHub, from your browser. Anyone with it could change the bot, so treat it like a
password: if it leaks, delete it on the same GitHub page and make a new one. Before the panel is published, you
can also open `panel/index.html` from the Mac directly.

## On your phone

The GitHub mobile app shows notifications and issues, so you can read and close video issues there. The control
panel works in a phone's browser. For anything else, open github.com in the browser (switch to its desktop site
if a button is missing).

## Where things are written down

| File | What's in it |
|---|---|
| `docs/GUIDE.md` | This guide |
| `docs/HOW-IT-WORKS.md` | How the AI pieces make and post a video, step by step |
| `docs/KEYS.md` | Every key and token, and what it does |
| `docs/STATUS.md` | What's finished, what's proven, decisions, and your checklist |
| `docs/DEPLOY.md` | Setup, the storage rules, and every caveat with its fix |
| `docs/REQUESTS.md` | Everything you've asked for or raised, and what was done |
| `docs/DEVLOG.md` | Every change, newest first |
