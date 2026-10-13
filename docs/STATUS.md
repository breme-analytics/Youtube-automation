# Where things stand

Last updated: 13 October 2026, evening. Every change keeps this page true (see `AGENTS.md`).

## Is it finished?

**Close, not proven.** Everything is built and on GitHub, and the daily run has already worked once on GitHub
(the 05:57 check of 13 October, green, which saved `state/videos.json`). Still to prove:

- the first **video** made on GitHub: Thursday 15 October, 06:15 Nairobi, from *The Kybalion*, chapter I
  (or sooner, if you press Run workflow);
- how many **minutes** a video really takes (estimated 1 to 2 hours);
- the **control panel** on GitHub Pages: built and tested, waiting for its public repository (`docs/GUIDE.md`,
  "Control panel");
- **posting to YouTube by itself**: needs your Google sign-in (`docs/DEPLOY.md`, step 4).

## Works, and was checked

- **On GitHub:** the daily run (13 Oct, 05:57): it read the state, applied the storage rules and committed the
  result as breme-analytics.
- **On the Mac (11 to 13 Oct):** scripts from free models only; George's narration and its check; pictures
  matched to the words; captions with clean line breaks; chapter titles and quotes; paintings (your Cloudflare
  token painted a test picture on 13 Oct); full renders of three long videos.
- **The five books:** every chapter of each was found and checked (43 chapters).
- **Automated tests:** 217 (Python) and 7 (control panel), with GitHub, YouTube and Google replaced by stand-ins.

## The two videos made on the Mac

Both were made again on 13 October with every fix: pictures checked against the words, paintings where no
footage fits, and the new caption line breaks. They're recorded in `state/videos.json` as made on the Mac
(status `local`), so the bot won't make those chapters again.

| Video | Folder on the Mac (`output/videos/`) | Notes |
|---|---|---|
| *The Mindset Mistake Keeping Your Life Stuck* (As a Man Thinketh, ch. 2) | `2026-10-12-the-mindset-mistake-keeping-your-life-stuck-v2/` | Gemini was overloaded during the render, so 45 of 100 shots were chosen by tags only. It's being re-rendered once more |
| *The Aimless Mistake That Keeps You Drifting* (ch. 4) | `2026-10-12-openrouter-ch4-v2/` | Being re-rendered |

Each folder has `video.mp4`, `thumbnail.jpg`, `captions.srt`, `review.md` and `POSTING.md` (title, description,
tags and settings to paste into YouTube Studio, with a suggested date). They're on the Mac only: post them from
here. The old versions are in the same place without `-v2`.

## Decisions for you

1. **Video days and minutes.** Two videos a week use about 1,080 of the 2,000 shared minutes a month (estimate).
   `monthly_minutes` is set to 1,000 as this bot's share; adjust it once you see the trading bot's use.
2. **Book order.** Books take turns now (`book_order = "balanced"`): The Kybalion first, then The Way of Peace,
   Meditations, Emerson, then round again. Say if you'd rather finish one book before the next (`"in order"`).
3. **Meditations translation.** Meric Casaubon's of 1634 is used: its text splits cleanly into the twelve books.
   George Long's of 1862 reads more easily but its text is full of footnote marks; it can be adapted if you
   prefer it.

## Your checklist

| Done | What | When |
|---|---|---|
| ✓ | Deploy key for this Mac, with write access | 12 Oct |
| ✓ | Repository secrets, including `CLOUDFLARE_AI_TOKEN` (each run's page lists the secrets it can see) | 13 Oct |
| ✓ | Workflow permissions: Read and write | 13 Oct |
| ✓ | Watch the repository (All Activity) | 13 Oct |
| ✓ | `CLOUDFLARE_AI_TOKEN` in the Mac's `.env` (checked: it works) | 13 Oct |
| | Make sure email is on for "Watching" (github.com/settings/notifications) | Now |
| | Control panel: public repository, deploy key, Pages, token (`docs/GUIDE.md`, "Control panel") | When you like |
| | Post the two Mac videos from their `POSTING.md` | When you like |
| | Two-factor sign-in on GitHub | |
| | Change the Amazon password you shared in the chat | |
| | Delete the unused R2 and Pexels lines from `.env`, and revoke the R2 token (`docs/KEYS.md`) | |
| | Optional: posting on its own (`docs/DEPLOY.md`, step 4) | |
| | Optional: verify the YouTube channel by phone, for custom thumbnails | |

## What the developer can and can't see

- **Can:** the code, and everything the bot commits back (`state/videos.json`, `state/status.json`, storyboards),
  through git.
- **Can't:** Actions runs, issues, releases or secrets. The repository is private, and this Mac's deploy key only
  allows git. The GitHub command-line login on this Mac belongs to another account and is never used for this
  project.

So when something goes wrong, paste the run's last lines or the issue's text into the chat.
