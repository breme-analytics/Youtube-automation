"""Shared paths, video formats and tool locations."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
OUTPUT_DIR = ROOT / "output"
MODELS_DIR = ROOT / "models"


def cache_dir() -> Path:
    """Downloaded stock clips and cached searches: $OWD_CACHE_DIR, else output/cache."""
    return Path(os.environ.get("OWD_CACHE_DIR") or OUTPUT_DIR / "cache")

SAMPLE_RATE = 24_000  # Kokoro's output rate
FPS = 30


@dataclass(frozen=True)
class VideoFormat:
    name: str
    width: int
    height: int

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


SHORT = VideoFormat("short", 1080, 1920)
LONG = VideoFormat("long", 1920, 1080)
THUMBNAIL_SIZE = (1280, 720)

DISPLAY_FONT = FONTS_DIR / "Anton-Regular.ttf"  # SIL Open Font License, see OFL-Anton.txt
DISPLAY_FONT_NAME = "Anton"

# Burned-in captions need an ffmpeg built with libass. Homebrew's `ffmpeg` formula lacks it;
# `ffmpeg-full` has it but is keg-only, so it isn't on PATH.
_FFMPEG_DIRS = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin")


@lru_cache
def tool(name: str) -> str:
    """Path to ffmpeg or ffprobe: $OWD_FFMPEG_DIR if set, else Homebrew's ffmpeg-full, else PATH."""
    override = os.environ.get("OWD_FFMPEG_DIR")
    for directory in [override] if override else _FFMPEG_DIRS:
        path = Path(directory) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    if override:
        raise FileNotFoundError(f"{name} not found in OWD_FFMPEG_DIR={override}")
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(
            f"{name} not found. Install an ffmpeg built with libass (macOS: brew install ffmpeg-full) "
            "or set OWD_FFMPEG_DIR to the folder that contains it."
        )
    return found
