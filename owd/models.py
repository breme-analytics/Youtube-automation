"""Model files, pinned to exact Hugging Face commits so every machine runs the same models.

Files download once into the Hugging Face cache (HF_HOME, default ~/.cache/huggingface) and are
reused after that. `python -m owd fetch-models` downloads everything ahead of time (CI and the
Docker image do this, so runs don't download during rendering).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_REVISION = "f3ff3571791e39611d31c381e3a41a3af07b4987"  # main on 2025-04-10 (v1.0 weights)
KOKORO_FILES = ("config.json", "kokoro-v1_0.pth")

WHISPER_REPO = "Systran/faster-whisper-base.en"
WHISPER_REVISION = "3d3d5dee26484f91867d81cb899cfcf72b96be6c"
WHISPER_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def _download(repo: str, filename: str, revision: str) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo, filename=filename, revision=revision))


def kokoro_files() -> tuple[Path, Path]:
    """(config.json, weights) for Kokoro-82M."""
    config, weights = (_download(KOKORO_REPO, name, KOKORO_REVISION) for name in KOKORO_FILES)
    return config, weights


def kokoro_voice(voice: str) -> Path:
    return _download(KOKORO_REPO, f"voices/{voice}.pt", KOKORO_REVISION)


def whisper_dir() -> Path:
    """Folder holding the faster-whisper model used to check narration."""
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo_id=WHISPER_REPO, revision=WHISPER_REVISION, allow_patterns=list(WHISPER_FILES)))


def fetch_all(voices: Iterable[str]) -> list[Path]:
    paths = [*kokoro_files(), *(kokoro_voice(voice) for voice in sorted(set(voices))), whisper_dir()]
    return paths
