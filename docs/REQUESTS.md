# Your requests and concerns

Everything you've asked for or raised, with what was done, where it's written up, and where it stands. Newest
first. Every new request or concern is added here in the same change that deals with it (`AGENTS.md`).

**Status:** **Done**; **Built, not proven** (works on the Mac and in tests, not yet run on GitHub or YouTube);
**Waiting for you**; **Decision needed**; **Declined** (with the reason and an alternative); **Replaced** (by a
later request of yours).

## 13 October 2026 (evening)

| You asked or raised | What was done | Where | Status |
|---|---|---|---|
| You turned on Watch (All Activity); the 05:57 "cleanup" run was green | Recorded. That run saved `state/videos.json` on GitHub: the first proof the daily run works end to end | `STATUS.md` | Done |
| Friendlier controls: a minimal static page on github.io | A control panel (`panel/`): overview, videos waiting (Posted / Don't post), make a video with an angle, instructions and documents, add a book, video days and minutes, recent runs. github.io is free only for public repositories, so the panel gets its own small public repository holding only the page; the bot's repository stays private | `GUIDE.md`, "Control panel" | Built and tested; waiting for you to create the public repository |
| Next video from *The Kybalion*; also Emerson (Self-Reliance, The Over-Soul), Marcus Aurelius's *Meditations*, James Allen's *The Way of Peace* | All four added from Gutenberg's official mirror, every chapter checked. The Kybalion is first, so Thursday's video is its chapter I; then the books take turns | `channel.toml` `[[books]]`; `STATUS.md`, decision 2 | Done |
| Document everything, including how the AI pieces work together to make and post a video | Step by step, with which AI does what, the fallbacks, and how posting works | `HOW-IT-WORKS.md` | Done |
| If it needs a book, or anything else, tell me by email | "The bot needs ..." issues (GitHub emails you): a new book, posting waiting videos, minutes used up, YouTube sign-in. One issue per need, closed by the bot when it's sorted | `GUIDE.md`, "How the bot tells you things" | Done |
| The Cloudflare AI token is now in the Mac's `.env`. Document what it and the other keys do | Checked: it works (listed models, painted a test picture). Every key and token explained, plus the unused ones you can delete | `KEYS.md` | Done |
| The two Mac videos had issues you highlighted: post them if fixed, otherwise discard or rebrand | Both made again with every fix (matched pictures, paintings, clean caption breaks). Checking the first one also found six lines that overstated studies; they were softened and it's being rendered once more. Posting kits with suggested slots (16 and 20 October); recorded so their chapters aren't repeated. The bot can't post them for you yet (no YouTube sign-in), so they're scheduled by hand in YouTube Studio | `STATUS.md`, "The two videos made on the Mac" | In progress: renders finishing on the Mac |
| Adding more books: a friendlier way, or written steps | Panel: Books → Add a book. GitHub: Actions → add-book. Both check the book first | `GUIDE.md`, "Adding a book" | Done |
| How often does the full workflow run, and how many minutes? The 2,000 free minutes are shared with the trading bot. Fix it | Answer: a video twice a week (1 to 2 hours each, not yet measured), plus a 1 to 2 minute check daily. Fixed: video days are one setting; the bot counts its own minutes and won't go over its monthly share (`monthly_minutes`, 1,000), and emails you if it pauses; the separate cleanup job was merged into the daily run; the model cache no longer resets when settings change | `GUIDE.md`, "The daily run, and Actions minutes" | Done; real minutes measured after Thursday |

## 13 October 2026

| You asked or raised | What was done | Where | Status |
|---|---|---|---|
| Document everything: every concern you raise, and the caveats from my replies | This register; `STATUS.md` (where things stand); caveats with fixes in `DEPLOY.md`; a standing rule for whoever works on the bot | `REQUESTS.md`, `STATUS.md`, `DEPLOY.md`, `AGENTS.md` | Done, ongoing |
| Is there a UI for the bot? | No separate app: GitHub is the control panel. Why, and where every control is. Free friendlier options offered (forms, a status issue) | `GUIDE.md`; `STATUS.md`, decision 3 | Decision needed |
| Where will I steer the agent from? | `steering/instructions.md` (typed instructions), `steering/references/` (documents), the angle box on **Run workflow** (one video), `channel.toml` (settings) | `GUIDE.md`, "Three ways to steer" | Done |
| Is everything complete now? | No. What's proven, what isn't, the gaps, and your checklist | `STATUS.md` | Answered |
| You set the secrets on GitHub (including the Cloudflare AI token) and in `.env`, and set workflow permissions to Read and write | Recorded. Each run's page now lists which secrets it can see (names only), and warns if paintings are off. The Mac's `.env` has no `CLOUDFLARE_AI_TOKEN` yet (last saved 11 October) | `STATUS.md`, checklist | Done on GitHub; `.env` waiting for you |
| You added the deploy key: carry on | Pushed. Your "Initial commit" and MIT licence are kept; my commits sit on top (no force push) | `DEVLOG.md`, milestone 5 | Done |
| Videos must be stored, and deleted some time after posting, so storage never fills | Stored in a GitHub release before delivery, in both modes; deleted 7 days after posting; discarded copies deleted at the next cleanup; at most 4 stored | `DEPLOY.md`, "Where videos are stored"; `channel.toml` `[storage]` | Built, not proven |
| Document the caveats (review-mode delivery; YouTube keeping uploads private) and state the fixes | Every caveat (14 so far), each with what the bot does and the fix. Corrected: YouTube's reference no longer says unaudited uploads are locked, so the bot checks each video instead | `DEPLOY.md`, "Caveats and fixes" | Done |
| A caption ended on "the" (your frame from the second video) | Captions no longer end on words like "the", "of" or "into": 34 such breaks in that video, 0 now. The rendered file still has the old breaks | `DEVLOG.md`, milestone 4 | Done for new videos |

## 12 October 2026

| You asked or raised | What was done | Where | Status |
|---|---|---|---|
| The first long video was great, but the stock footage wasn't in sync with the narration and distracted from the story | A free vision model checks that each clip shows what George is saying, and paintings are used when nothing fits. A drift bug was found and fixed. You checked frames of the new render | `DEVLOG.md`, milestone 4 | Done |
| Add captions | Burned in at the bottom, with the spoken word in gold; hidden under quote and chapter cards | `DEVLOG.md`, milestone 4 | Done |
| Add suspense; follow Mario Joos | An open question answered at the end, chapter cliffhangers, short silences before reveals; 27 sourced principles | `steering/references/retention-mario-joos.md` | Done |
| Steer by typing, or by uploading a document | PDF, Word, text and Markdown in `steering/references/`; long ones condensed into a readable digest | `steering/instructions.md`, `GUIDE.md` | Done |
| Use the Kindle book *YouTube Success in 30 Days* (Brian Chesson) | Not read: it needs your Amazon login, and extracting a copy-protected ebook breaks Amazon's terms. Export your highlights into the placeholder instead, and change the password you shared in the chat | `steering/references/youtube-success-in-30-days.md` | Declined, with an alternative |
| Commits must show "breme-analytics" | Every commit is authored as breme-analytics | `DEVLOG.md`, milestone 4 | Done |
| The repository is `breme-analytics/Youtube-automation`, not Trading-bot | Remote set, pushed | `DEVLOG.md`, milestone 5 | Done |
| Run anywhere for $0, in the cloud, not on the Mac | GitHub Actions workflows; every service on a free tier with no card | `DEPLOY.md` | Built, not proven |
| Post or schedule on its own. Without Kiro, the free OpenRouter models must write good scripts | Auto mode (upload, schedule, check it went public). A full OpenRouter-only script was tested and two flaws were fixed | `DEPLOY.md`, step 4; `DEVLOG.md`, milestone 4 | Built, not proven; needs your Google sign-in |
| Clean up videos once they're posted | Storage rules (reworked 13 October) | `DEPLOY.md` | Built, not proven |
| Pixabay instead of Pexels (Pexels isn't issuing keys) | Pixabay for all footage | `DEVLOG.md`, milestone 2 | Done |
| Keep Breme separate, and don't use other people's accounts or keys | Breme's ideas rebuilt, Breme untouched. The other GitHub login on this Mac is never used; a deploy key for this repository only | `DEVLOG.md`, milestones 2 and 3 | Done |
| Document every step | Dev log for every change | `DEVLOG.md` | Done, ongoing |

## 11 October 2026 (the wildlife Short, and the plan)

| You asked or raised | What was done | Where | Status |
|---|---|---|---|
| Video quality great, but the crop cut out too much | Long videos use landscape clips only; vertical ones are skipped, not cropped | `DEVLOG.md`, milestone 3 | Done |
| Wildlife didn't fit a script about the mind | Mind and spirit visuals; animals and holidays skipped unless a scene asks for one | `steering/references/visual-style.md` | Done |
| Don't mix the voices: keep George | George reads everything, quotes included | `channel.toml` `[voices]` | Done |
| Shorts aren't dense enough: focus on long-form | Long videos of about 9 to 12 minutes by default; Shorts paused | `channel.toml` `[video]` | Done |
| Titles from *The Power of Bad* (Tierney and Baumeister) | Title and thumbnail rules from the negativity effect, with a line never to cross (no false fear; the video answers the title) | `steering/references/titles-power-of-bad.md` | Done |
| A place to give the bot instructions | The steering folder | `steering/instructions.md` | Done |
| Push to GitHub | Done once the deploy key was added (12 to 13 October) | `DEVLOG.md`, milestone 5 | Done |
| You liked George and Heart (voices 4 and 1) | George narrates; Heart read quotes until you asked for one voice | `DEVLOG.md`, milestone 2 | Replaced (one voice) |
| Wildlife footage | Tried in a Short | `DEVLOG.md`, milestone 2 | Replaced (mind and spirit visuals) |
| Reproducible, runs in the cloud, can be developed later on a weaker machine | `uv.lock`, pinned models, Dockerfile, a Codespaces dev container, GitHub Actions | `README.md` | Done |
| Reuse what Breme built (news and so on) | Breme's polite news collector rebuilt; its YouTube data isn't used (Breme's compliance notes) | `DEVLOG.md`, milestone 2 | Done |
| Original content only, no reposting | Videos explain and test public-domain books, never just read them | `README.md`, content rules | Done |
| A niche you care about: spirituality and the mind | "Old Wisdom, Decoded": classics of the mind, checked against modern psychology | `README.md` | Done |
| Free only: not a single dollar, ever | Free tiers only, no card on any service; costs table | `DEPLOY.md`, "What it costs" | Done |
