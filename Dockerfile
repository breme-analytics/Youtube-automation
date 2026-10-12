# syntax=docker/dockerfile:1
# The whole toolchain in one image: Python 3.12, ffmpeg with libass, every Python package from
# uv.lock and the pinned models. Used by the dev container (Codespaces) and the CI image check,
# and runnable on any cloud that runs containers.
#   docker build -t owd .
#   docker run --rm --env-file .env -v "$PWD/output:/app/output" -v "$PWD/storyboards:/app/storyboards" owd \
#     python -m owd write --chapter 2
FROM python:3.12-slim-trixie

# Debian's ffmpeg has libass (burned-in captions), libx264 and every filter the renderer uses.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

# The virtualenv lives outside the project folder, so a mounted checkout (dev container) reuses it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/opt/models \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app
# Dependencies before code, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

COPY . .
RUN python -m owd fetch-models

CMD ["python", "-m", "owd", "--help"]
