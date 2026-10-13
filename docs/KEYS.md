# Keys and tokens: what each one does

Every key below is free. Keys live in two places: **GitHub secrets** (Settings → Secrets and variables →
Actions), which the daily run uses, and **`.env`** on a computer, for making videos there. `.env` is never
committed. Never paste a key into a chat, an issue or a document.

## The keys the bot uses

| Name | Service | What it does | Without it | Where |
|---|---|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter (openrouter.ai/keys) | Writes the scripts with free models (tried first) | Gemini writes them; with neither, no video | Secret + `.env` |
| `GEMINI_API_KEY` | Google AI Studio (aistudio.google.com/apikey) | Looks at candidate footage and scores how well it shows George's words; backup script writer | Pictures chosen by tags only (flagged); no backup writer | Secret + `.env` |
| `PIXABAY_API_KEY` | Pixabay (pixabay.com/api/docs) | Searches and downloads stock footage | No video can be made | Secret + `.env` |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard (right sidebar) | Says which Cloudflare account the AI token belongs to | No paintings | Secret + `.env` |
| `CLOUDFLARE_AI_TOKEN` | Cloudflare → AI → Workers AI → Use REST API → Create a Workers AI API Token | **Paints** a scene when no footage fits (FLUX.2 [klein], about 40 a day free), and is the last backup script writer | Scenes with no fitting clip use the closest clip, flagged for review | Secret + `.env` |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | Google Cloud → Clients → Desktop app (`docs/DEPLOY.md`, step 4) | Identify the bot's own Google app to YouTube | Auto mode can't post (review mode is unaffected) | Secret + `.env` |
| `YOUTUBE_REFRESH_TOKEN` | Made by `python -m owd youtube-login` | Lets the bot upload to your channel without your password | Same | Secret only |
| `GITHUB_TOKEN` | Made by GitHub for each run, automatically | Stores videos (releases), opens issues, saves progress, counts minutes. Expires when the run ends | — | Nothing to set |

**Checked on 13 October 2026:** the `CLOUDFLARE_AI_TOKEN` in the Mac's `.env` works. It listed Workers AI
models and painted a test picture (1344 × 768, in 30 seconds). The copy in GitHub's secrets can't be read by
anyone, so each daily run's page lists which secrets it can see (names only).

## Access that isn't a key in `.env`

| What | Where it lives | What it may do |
|---|---|---|
| **Deploy key "Mac"** (`~/.ssh/youtube_automation_deploy`) | This Mac; its public half in the repository's Settings → Deploy keys | Push and pull this one repository, nothing else |
| **Deploy key "Mac (panel)"** (`~/.ssh/youtube_automation_panel_deploy`) | This Mac; its public half in the panel repository's deploy keys | Publish the control panel to its public repository, nothing else |
| **Control panel token** | Only in your browser (you paste it into the panel) | A fine-grained GitHub token for this one repository: **Actions** read and write (start runs, add a book), **Contents** read and write (instructions, documents, settings), **Issues** read and write (mark videos posted). Make it at github.com/settings/personal-access-tokens → Fine-grained → Generate; "Only select repositories": `Youtube-automation`. Pick an expiry (90 days is a good habit) |

## Keys in `.env` that nothing uses any more

`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCESS_KEY_ID`, `CLOUDFLARE_SECRET_ACCESS_KEY` and
`CLOUDFLARE_S3_API_ENDPOINT` were for Cloudflare R2 storage, which was dropped (GitHub releases store the videos
instead). `PEXELS_API_KEY` is empty and unused (Pixabay replaced Pexels). You can delete these lines, and revoke
the R2 token in Cloudflare (My Profile → API Tokens) so it can't be misused.

## Replacing a key

1. Make a new one on the service's page (links above) and revoke the old one there.
2. Update the GitHub secret with the same name (Settings → Secrets and variables → Actions → the secret → Update).
3. Update `.env` on any computer that makes videos.

A refused key shows up as a failed run and a "The bot needs attention" issue. A refused YouTube sign-in opens
"The bot can't post to YouTube", with the fix.
