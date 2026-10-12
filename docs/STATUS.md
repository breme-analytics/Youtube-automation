# Where things stand

Last updated: 13 October 2026. Every change keeps this page true (see `AGENTS.md`).

## Is it finished?

**Not yet.** Everything is built and on GitHub, and each part has worked on the Mac. But:

- the bot hasn't done a full run on GitHub's machines yet;
- it has book chapters for only about two and a half more weeks;
- posting to YouTube by itself needs your one-time Google sign-in.

Until those are done, treat it as ready to try, not proven.

## Works, and was checked (on the Mac, 11 to 13 October)

- **Scripts from free models only** (OpenRouter), with every book quote checked word for word: one full script
  (chapter 4) with no problems flagged.
- **George's narration**, and the check that compares what he says with the script.
- **Pictures matched to the words** by a free vision model. Each chapter's pictures were measured in sync to
  within 7 ms, and you checked frames of the second video.
- **Captions** (spoken word in gold), chapter titles, on-screen quotes, and suspense pauses.
- **Two full long videos** rendered: 10:38 and 10:33.
- **Storage rules, posting and sign-in logic:** 193 automated tests pass, with GitHub, YouTube and Google
  replaced by stand-ins. Each storage rule was broken on purpose (9 times) and a test caught it every time.

## Built, but not proven yet

- **A full run on GitHub:** how long it takes, storing the video in a release, opening the issue, saving
  progress. It happens when you run **produce** by hand, or at the scheduled run on Thursday 15 October, 06:15
  Nairobi.
- **The daily cleanup on GitHub.** Its first run is 13 October, 05:40 Nairobi. With nothing stored yet, it only
  records an empty list.
- **Paintings:** never made for real, because there was no Workers AI token until now. The first run shows
  whether your token works.
- **The failure issue and the list of secrets on each run's page** (added 13 October). Their shell steps were run
  on the Mac with a stand-in for GitHub's tool.
- **Posting to YouTube by itself, and the browser sign-in.** These need your Google Cloud client
  (`docs/DEPLOY.md`, step 4).

## Decisions for you

1. **Which books come next.** Only *As a Man Thinketh* (7 chapters) is loaded. If the two videos made on the Mac
   count (point 2), 5 new videos are left: 15, 19, 22, 26 and 29 October. After that, runs stop with "Add a
   book". Candidates on Project Gutenberg:
   - *The Kybalion* (1908, #14209)
   - Emerson's *Essays, First Series* (1841, #2944): Self-Reliance, Compensation, Spiritual Laws, The Over-Soul
   - Marcus Aurelius's *Meditations* (#2680)
   - James Allen's *The Way of Peace* (#10740)
   - Wattles's *The Science of Getting Rich* (1910, #59844). It's about money, so it needs care with the
     channel's no-financial-advice rule.

   Haanel's *The Master Key System* isn't on Project Gutenberg.
2. **The two videos made on the Mac.** They are chapter 2 (*The Mindset Mistake Keeping Your Life Stuck*) and
   chapter 4 (*The Aimless Mistake That Keeps You Drifting*), both in `output/videos/` on the Mac. The bot has no
   record of them, so it would make those chapters again, on its 2nd and 4th runs. Should they be marked as
   done? Have you posted them?
3. **Friendlier controls.** There's no separate app; `docs/GUIDE.md` explains why, and where everything is.
   Free options inside GitHub:
   - forms under **New issue** ("Steer the bot", "Make a video about..."), so you fill in boxes instead of
     editing files;
   - a pinned status issue that the bot updates after every run: what's stored, what's waiting, chapters left,
     the next run, and any problems.

   Say if you want either.
4. **Already decided:** the Kindle book isn't used (Amazon's terms and copy protection); export your highlights
   into `steering/references/` instead. Shorts are paused (your choice, 11 October).

## Your checklist

| Done | What | When |
|---|---|---|
| ✓ | Deploy key for this Mac, with write access | 12 Oct |
| ✓ | Repository secrets, including `CLOUDFLARE_AI_TOKEN` (as you reported; each run's page now lists the secrets it can see) | 13 Oct |
| ✓ | Workflow permissions: Read and write | 13 Oct |
| | Actions tab: did "tests" and "image" pass after the pushes? | Now |
| | Watch the repository, with email on (`docs/GUIDE.md`, "How you hear from the bot") | Now |
| | First video: **Actions → produce → Run workflow**, or wait for Thursday | |
| | `CLOUDFLARE_AI_TOKEN` in the Mac's `.env`. It isn't there: the file was last saved on 11 October. Only needed for making videos on the Mac | |
| | Two-factor sign-in on GitHub | |
| | Change the Amazon password you shared in the chat | |
| | The decisions above: books, the Mac videos, controls | |
| | Optional: posting on its own (`docs/DEPLOY.md`, step 4) | |
| | Optional: verify the YouTube channel by phone, for custom thumbnails | |

## What the developer can and can't see

- **Can:** the code, and everything the bot commits back (`state/videos.json`, storyboards), through git.
- **Can't:** Actions runs, issues, releases or secrets. The repository is private, and this Mac's deploy key only
  allows git. The GitHub command-line login on this Mac belongs to another account and is never used for this
  project.

So when something goes wrong, paste the run's last lines or the issue's text into the chat.
