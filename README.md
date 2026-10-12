# Old Wisdom, Decoded

A bot that makes original long-form YouTube videos: public-domain classics of the mind (James Allen, Haanel,
Wattles, Emerson, the Kybalion) explained in modern English and checked against modern psychology, narrated
by George, an older British storyteller (Kokoro `bm_george`), over mind-and-spirit footage. Quotes from the
books appear on screen as he reads them. Everything runs on free tools and free tiers.

**Steer the bot** in `steering/instructions.md` (plain English) and the reference files in
`steering/references/`. **What has been built, and why:** `docs/DEVLOG.md`.

## Set up (any machine)

You need [uv](https://docs.astral.sh/uv/) and an ffmpeg built with libass (for on-screen text).

| System | Install |
|---|---|
| macOS | `brew install uv ffmpeg-full` (the plain `ffmpeg` formula has no libass; `ffmpeg-full` is found automatically) |
| Ubuntu / Debian | `sudo apt-get install ffmpeg`, then [install uv](https://docs.astral.sh/uv/getting-started/installation/) |
| Small or Windows machine | Use GitHub Codespaces or Docker (below): nothing to install locally |

Then, in the project folder:

```bash
uv sync --frozen                         # exact package versions from uv.lock (Python 3.12 is fetched if needed)
cp .env.example .env                     # then paste your keys into .env
uv run python -m owd fetch-models        # pinned voice and speech-check models (about 500 MB, once)
uv run python -m pytest -q               # fast tests; add  -m "slow or not slow"  for all of them
```

## Make a video

```bash
uv run python -m owd write --chapter 2       # writes storyboards/<date>-<title>.toml (about 5 to 10 minutes)
# read and edit the storyboard if you like, then:
uv run python -m owd render storyboards/<the file it printed>
```

The finished files land in `output/videos/<name>/`: `video.mp4`, `thumbnail.jpg`, `captions.srt`,
`metadata.json` (title, description with chapters and credits) and `review.md`, the checklist to go through
before posting (title options, every factual claim, every quote, the narration check).

## Commands

| Command | What it does |
|---|---|
| `python -m owd write --chapter N [--book ID] [--angle "..."]` | Write a long-form storyboard from one chapter of a book in `channel.toml` |
| `python -m owd render STORYBOARD [--preview]` | Make the video. `--preview` downloads smaller footage (for slow connections) |
| `python -m owd news [--topic words] [--kind platform]` | Research stories the scripts can cite, or YouTube platform news |
| `python -m owd voices` | Read a sample paragraph in each candidate voice |
| `python -m owd fetch-models` | Download the pinned models ahead of time |
| `python -m owd demo` | A no-API technical test (generated backgrounds) |

Prefix each with `uv run` outside the dev container.

## How a video is made

1. **Script** (`write`): one chapter of a public-domain book (as numbered sentences), recent research from the
   news feeds, and the owner's steering go to a free language model. Quotes come back as sentence numbers, so
   the bot inserts the book's exact words. Short drafts are expanded one chapter at a time. Every factual claim
   is listed for review.
2. **Storyboard** (`storyboards/*.toml`): chapters and scenes, each with narration and a footage search such as
   `"candle flame"`. Paragraphs starting with `>` are book quotes. Edit freely before rendering.
3. **Quote check**: every quote must appear word for word in its source text (`sources/`), or nothing renders.
4. **Narration**: Kokoro reads the script, with word timings for cuts and on-screen text.
5. **Narration check**: faster-whisper transcribes the audio and compares it with the script.
6. **Footage**: landscape Pixabay clips tagged with each scene's subject (no AI-generated or low-quality clips),
   with one shared colour grade. Searches are cached for 24 hours, as Pixabay requires.
7. **Video**: crossfades on the pauses inside a chapter, a dip through black between chapters, chapter titles,
   and quote cards (footage dimmed, the book's words in Libre Baskerville). Loudness at YouTube's -14 LUFS.
8. **Thumbnail, description and review**: YouTube chapters, sources, research links, footage credits and an AI
   note in the description; `review.md` lists what to check before posting.

## Settings

- `steering/instructions.md` and `steering/references/`: how the bot should write (titles, retention,
  voice, visuals, YouTube rules). Plain English; read before every script.
- `channel.toml`: voice and speed, video length, books, language models (in fallback order), news feeds
  and research keywords.
- `.env` (local) or CI/Codespaces secrets: the API keys listed in `.env.example`.

## Working from a low-powered machine

**GitHub Codespaces** runs this project in the browser on GitHub's machines. Open the repository on
GitHub, then **Code → Codespaces → Create codespace**. The dev container (`.devcontainer/`) builds
from the same `Dockerfile` as the cloud, with packages and models already inside. Add the API keys at
github.com/settings/codespaces. A free personal account includes 120 core-hours a month, which is
about 60 hours on the 2-core machine. Stop the codespace when you're done so the hours aren't used up.

**Docker** works the same on any machine that runs containers:

```bash
docker build -t owd .
docker run --rm --env-file .env -v "$PWD/output:/app/output" -v "$PWD/storyboards:/app/storyboards" owd \
  python -m owd write --chapter 2
```

## Reproducibility

- `uv.lock` pins every Python package with hashes, for macOS and Linux (CPU-only torch on Linux).
- `owd/models.py` pins each model to an exact Hugging Face commit.
- The caption font (Anton, SIL Open Font License) and the book texts are in the repository.
- `.github/workflows/tests.yml` runs every test on a clean Ubuntu runner on each push.
  `image.yml` builds the Docker image and runs the tests inside it.

## Content rules the bot follows

- It explains and tests the books; it never just reads them aloud (YouTube doesn't pay for that).
- Quotes are checked word for word against the public-domain source.
- No promises of guaranteed results, no "you were chosen" bait, no health or money advice.
- The narrator never claims to be a human expert.
- Living teachers can be discussed, but their recordings, footage and text are never used.
- Footage creators and sources are credited in every description.
