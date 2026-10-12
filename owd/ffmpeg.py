"""Running ffmpeg and ffprobe, plus the escaping and loudness helpers the renderer needs.

Commands are argument lists (never a shell string), so file names with spaces or quotes are safe.
"""

from __future__ import annotations

import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from owd.config import tool

# YouTube plays everything at about -14 LUFS and turns louder videos down, so aim there.
TARGET_LUFS = -14.0
TARGET_TRUE_PEAK = -1.5  # headroom for the AAC encoder's overshoot
TARGET_LRA = 11.0


class FFmpegError(RuntimeError):
    def __init__(self, command: Sequence[str], stderr: str):
        self.command = list(command)
        self.stderr = stderr
        tail = "\n".join(stderr.strip().splitlines()[-25:])
        super().__init__(f"{Path(self.command[0]).name} failed:\n{tail}")


def ffmpeg(args: Sequence[str | Path], *, cwd: Path | None = None) -> str:
    """Run ffmpeg (overwriting outputs, never reading stdin) and return its log."""
    command = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", *map(str, args)]
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(command, proc.stderr)
    return proc.stderr


def probe(path: Path | str) -> dict:
    command = [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(command, proc.stderr)
    return json.loads(proc.stdout)


def duration(path: Path | str) -> float:
    return float(probe(path)["format"]["duration"])


@lru_cache
def has_filter(name: str) -> bool:
    proc = subprocess.run([tool("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True, errors="replace")
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines())


def escape_filter_value(value: str) -> str:
    """Escape a filter option value (a file path, a caption) for use inside a filtergraph.

    ffmpeg unescapes twice, once when splitting the graph into filters and once when splitting a
    filter's options ("Notes on filtergraph escaping" in the ffmpeg-filters manual).
    """
    option_level = "".join("\\" + char if char in "\\':" else char for char in value)
    return "".join("\\" + char if char in "\\'[],;" else char for char in option_level)


def measure_loudness(path: Path | str) -> dict[str, float]:
    """First loudnorm pass: the input's integrated loudness, true peak, range and threshold."""
    log = ffmpeg(
        ["-i", path, "-vn", "-af",
         f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA={TARGET_LRA}:print_format=json", "-f", "null", "-"]
    )
    start, end = log.rfind("{"), log.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"loudnorm printed no measurement for {path}")
    values: dict[str, float] = {}
    for key, value in json.loads(log[start : end + 1]).items():
        try:
            values[key] = float(value)
        except (TypeError, ValueError):
            pass  # normalization_type
    return values


def loudness_filter(path: Path | str) -> str:
    """Second-pass loudnorm using the first pass's numbers, so the gain is one linear change
    instead of loudnorm's pumping dynamic mode. Silence passes through unchanged."""
    measured = measure_loudness(path)
    if not math.isfinite(measured.get("input_i", -math.inf)):
        return "anull"
    return (
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA={TARGET_LRA}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true"
    )


def normalize_audio(src: Path | str, dst: Path | str, sample_rate: int = 48_000) -> Path:
    """Write `src` loudness-normalised to `dst` (format from the extension, e.g. .wav or .m4a)."""
    ffmpeg(["-i", src, "-vn", "-af", f"{loudness_filter(src)},aresample={sample_rate}", "-ar", str(sample_rate), dst])
    return Path(dst)
