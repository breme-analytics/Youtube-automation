# Using the bot: GitHub is the control panel

There is no separate app or website. The bot lives in the GitHub repository
**github.com/breme-analytics/Youtube-automation**, and GitHub's own pages are its controls:

- you **steer** it by editing two files and uploading documents,
- you **hear from it** through issues (GitHub emails you),
- you **start, pause and watch** it from the **Actions** tab.

**Why there's no app:** a website for a private repository would need GitHub Pages, which on a free account only
works for public repositories, or a separately hosted app with its own login and keys to protect. One costs money
and the other adds risk. GitHub's pages are free, already behind your login, and work on a phone. Friendlier
controls can be added inside GitHub for free (see `docs/STATUS.md`, "Decisions for you").

## Where to do what

| You want to | Where |
|---|---|
| Change how it writes (tone, titles, topics, do's and don'ts) | `steering/instructions.md` → pencil icon (**Edit**) → type → **Commit changes** |
| Give it a document to follow (PDF, Word, text, Markdown) | `steering/references/` → **Add file → Upload files** → **Commit changes** |
| Switch a document off | Open it → pencil icon → in the file-name box, type `off/` before the name → **Commit changes** |
| Give one video a particular angle | **Actions** → **produce** → **Run workflow** → type the angle → **Run workflow** |
| Make a video now | The same, with the angle left empty |
| See what it's doing | **Actions** → the newest run (yellow: running; green: finished; red: failed). The run's summary lists the secrets it could see and what's stored |
| Review and post a video | **Issues** → "Ready to post: ..." → follow its checklist → **Close issue** |
| Not post a video | On its issue: **Close issue** ▾ → **Close as not planned**. The stored copy is deleted at the next cleanup |
| See the stored videos | **Releases** (right-hand side of the repository's main page) |
| Change the voice, length, captions, paintings, review or auto posting, posting days and time, or storage | `channel.toml` → pencil icon → change the value → **Commit changes**. Comments in the file explain each setting |
| Change which days it makes videos | `.github/workflows/produce.yml`, the `cron` line. Times are in UTC; days are 0 (Sunday) to 6 |
| Pause the bot | **Actions** → **produce** → **...** (top right) → **Disable workflow**. **Enable workflow** restarts it |
| Add a book | See "Adding a book" below |
| Check it's still free | **Settings → Billing and plans → Usage** (Actions minutes) |

A run uses whatever is on GitHub when it starts, so a change made during a run applies to the next one.

## Three ways to steer

1. **Standing instructions:** `steering/instructions.md`. These apply to every video until you change them. Put the
   newest at the top, in plain English: "Mention one everyday example in every chapter."
2. **Documents:** `steering/references/`. The bot reads every document there before it writes. Long ones are
   condensed once into `<name>.digest.md`; open it to see exactly what the bot took.
3. **One video:** the angle box when you run **produce** by hand: "tie it to exam stress".

Settings that aren't about writing (voice, length, schedule, storage, books) are in `channel.toml`.

## How you hear from the bot

GitHub emails you about new issues in repositories you watch. Check this once:

1. On the repository's main page: **Watch** → **All Activity** (or **Custom** → **Issues**).
2. At github.com/settings/notifications, under **Watching**, tick **Email**.

The issues you'll get:

- **"Ready to post: <title>"**: a video is ready. Download, post, close the issue.
- **"Scheduled: <title>"** (auto mode only): the video is on YouTube and goes public at the time given. Nothing to do.
- **"The bot needs attention: a run failed"**: a run stopped. Open its link. Later failures add comments to the
  same issue instead of opening new ones.
- **Heads-ups** at the top of a video's issue, for example when only a few book chapters are left.

## When something goes wrong

1. Open the run from the issue's link. The reason is at the top of the page (yellow or red notes), or in the last
   lines of the step with the red cross.
2. Common reasons:

   | The run says | What to do |
   |---|---|
   | "Add these repository secrets" | A secret is missing or misnamed: Settings → Secrets and variables → Actions |
   | "rate limited", "busy" or "overloaded" | The free AI models were busy. Run **produce** again later |
   | "Every chapter of every book ... already has a video" | Add a book (below) |
   | "Storage is full" (a yellow note; nothing failed) | Post or discard the videos waiting in your issues |
   | "invalid_grant" | The YouTube sign-in expired: `docs/DEPLOY.md`, caveat 2 |

3. Still stuck? Copy the last 30 lines of the red step and send them to the developer.

Every known limit, with what the bot does about it and the fix, is in `docs/DEPLOY.md`, "Caveats and fixes".

## On your phone

The GitHub mobile app shows notifications and issues, so you can read, discuss and close video issues there. To
edit files, upload documents or run a workflow, open github.com in the phone's browser. If a button is missing,
switch the browser to its desktop site.

## Adding a book

The bot works through the books in `channel.toml` in order, one chapter per video. Each video's issue warns when
4 or fewer chapters are left; when none are left, runs fail with "Add a book".

A book has to be:

- **public domain:** on Project Gutenberg (gutenberg.org), by an author who died more than 70 years ago;
- **its "Plain Text UTF-8" file,** with a CONTENTS list whose chapter titles are in capitals (that's how the bot
  finds the chapters, and it checks every quote against this text).

The simplest route is to ask the developer: they check the chapters are found before the bot relies on them. To
do it yourself:

1. Download the book's **Plain Text UTF-8** file from Project Gutenberg and upload it into `sources/`
   (**Add file → Upload files**), with a short name like `the-kybalion.txt`.
2. In `channel.toml`, copy the `[[books]]` block and change `id`, `file`, `cite`, `author` and `gutenberg` (the
   book's number on Project Gutenberg).
3. Commit. If the next run fails with "No CONTENTS heading found", the file needs adapting: ask the developer.

## Where things are written down

| File | What's in it |
|---|---|
| `docs/GUIDE.md` | This guide: how to use and steer the bot |
| `docs/STATUS.md` | Is it finished? What's proven, what isn't, the gaps, and your checklist |
| `docs/DEPLOY.md` | Setup, the storage rules, and every caveat with its fix |
| `docs/REQUESTS.md` | Everything you've asked for or raised, and what was done about it |
| `docs/DEVLOG.md` | Every change, newest first: what, why, and what was checked |
| `README.md` | What the bot is, and the commands for running it on a computer |
