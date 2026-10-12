"""Video assembly with ffmpeg: stills become slow camera moves, shots are joined with crossfades,
captions are burned in and the narration is added at YouTube's loudness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from owd.config import FONTS_DIR, FPS
from owd.ffmpeg import duration as media_duration
from owd.ffmpeg import escape_filter_value, ffmpeg, loudness_filter
from owd.timeline import snap_fade


@dataclass(frozen=True)
class Motion:
    """A slow move over a still. Zoom at the start and end, and where the visible window sits in
    the spare margin (0 = left/top edge, 0.5 = centre, 1 = right/bottom edge)."""

    zoom_start: float = 1.0
    zoom_end: float = 1.12
    x_start: float = 0.5
    x_end: float = 0.5
    y_start: float = 0.5
    y_end: float = 0.5


PUSH_IN = Motion()
PULL_OUT = Motion(zoom_start=1.12, zoom_end=1.0)
PAN_RIGHT = Motion(1.12, 1.12, 0.0, 1.0)
PAN_LEFT = Motion(1.12, 1.12, 1.0, 0.0)
RISE = Motion(1.10, 1.14, 0.5, 0.5, 1.0, 0.0)
MOTIONS = (PUSH_IN, PAN_RIGHT, PULL_OUT, PAN_LEFT, RISE)
# Paintings in long videos: a barely-there drift, so the eye stays on the picture, not the camera.
GENTLE = (Motion(1.0, 1.06), Motion(1.05, 1.05, 0.2, 0.8), Motion(1.06, 1.0), Motion(1.05, 1.05, 0.8, 0.2))


def _lerp(start: float, end: float, ease: str) -> str:
    return f"({start:g}+({end:g}-{start:g})*{ease})"


def zoompan_filter(motion: Motion, frames: int, size: tuple[int, int], fps: int = FPS) -> str:
    """zoompan for one still, eased in and out so the move starts and stops gently."""
    width, height = size
    ease = f"(0.5-0.5*cos(PI*on/{max(frames - 1, 1)}))"
    zoom = _lerp(motion.zoom_start, motion.zoom_end, ease)
    x = f"(iw-iw/zoom)*{_lerp(motion.x_start, motion.x_end, ease)}"
    y = f"(ih-ih/zoom)*{_lerp(motion.y_start, motion.y_end, ease)}"
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps}"


def frame_count(seconds: float, fps: int = FPS) -> int:
    return max(2, round(seconds * fps))


def render_scene(
    image: Path,
    out: Path,
    *,
    seconds: float,
    size: tuple[int, int],
    motion: Motion = PUSH_IN,
    fps: int = FPS,
    oversample: int = 2,
) -> Path:
    """One shot: `image` filling the frame with a slow camera move, as a silent high-quality clip.

    zoompan crops in whole pixels, which makes slow zooms shimmer; working on a copy `oversample`
    times the output size turns those steps into fractions of an output pixel.
    """
    width, height = size
    frames = frame_count(seconds, fps)
    big_w, big_h = width * oversample, height * oversample
    graph = ",".join(
        [
            f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={big_w}:{big_h}",
            "format=yuv444p",  # no chroma subsampling, so the crop can move one pixel at a time
            zoompan_filter(motion, frames, size, fps),
            "format=yuv420p",
            "setsar=1",
        ]
    )
    ffmpeg(["-i", image, "-vf", graph, "-frames:v", frames, "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "16", "-an", out])
    return Path(out)


def render_clip(
    src: Path,
    out: Path,
    *,
    seconds: float,
    size: tuple[int, int],
    start: float | None = None,
    fps: int = FPS,
    grade: bool = True,
) -> Path:
    """One shot from a stock clip, starting at `start` seconds into it (default: its middle),
    filling the frame (cropped, never letterboxed) at `fps`, slowed down a little if the clip is
    too short, with a light shared colour grade so footage from different creators looks like one
    film. Silent. See stock.clip_window for which part of the clip is used."""
    from owd.stock import clip_window

    width, height = size
    begin, span, slowdown = clip_window(media_duration(src), seconds, start)
    chain = [
        f"setpts=(PTS-STARTPTS)*{slowdown:.5f}",
        f"fps={fps}",
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={width}:{height}",
    ]
    if grade:
        chain += ["eq=contrast=1.04:saturation=1.08", "vignette=angle=PI/6"]
    # If the clip still runs out (rounding, or a very short clip), hold its last frame.
    chain += ["tpad=stop_mode=clone:stop_duration=2", "format=yuv420p", "setsar=1"]
    ffmpeg(["-ss", f"{begin:.3f}", "-t", f"{span + 0.5:.3f}", "-i", src, "-vf", ",".join(chain),
            "-frames:v", frame_count(seconds, fps), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out])
    return Path(out)


def grab_frame(src: Path, out: Path, at: float) -> Path:
    """One full-resolution frame from `src` at `at` seconds, as PNG."""
    ffmpeg(["-ss", f"{max(at, 0):.3f}", "-i", src, "-frames:v", "1", out])
    return Path(out)


def xfade_offsets(durations: Sequence[float], fade: float) -> list[float]:
    """When each crossfade starts: shot k fades into shot k + 1 over its last `fade` seconds."""
    offsets, clock = [], 0.0
    for seconds in durations[:-1]:
        clock += seconds - fade
        offsets.append(clock)
    return offsets


def _offset_arg(offset: float, fps: int) -> str:
    """xfade starts on the first frame whose time is >= offset. Half a frame early, the intended
    frame always qualifies and the one before never does, whatever the decimal rounding."""
    return f"{(round(offset * fps) - 0.5) / fps:.6f}"


def joined_duration(durations: Sequence[float], fade: float) -> float:
    return sum(durations) - fade * max(len(durations) - 1, 0)


def assemble(
    shots: Sequence[Path],
    shot_seconds: Sequence[float],
    narration: Path,
    out: Path,
    *,
    captions: Path | None = None,
    fade: float = 0.6,
    transition: str = "fade",
    tail: float = 0.5,
    fps: int = FPS,
    crf: int = 18,
    preset: str = "medium",
    fonts_dir: Path = FONTS_DIR,
) -> Path:
    """Crossfade the shots, burn in `captions` (ASS), add the narration at -14 LUFS plus `tail`
    seconds of silence, and encode an MP4 the way YouTube recommends (H.264 High, closed GOP of
    half the frame rate, AAC 48 kHz stereo, moov atom first). If the shots end before the audio,
    the last frame is held. Used for Shorts; long videos use join_shots per chapter, then finish."""
    if not shots or len(shots) != len(shot_seconds):
        raise ValueError("Give one duration per shot")
    fade = snap_fade(fade, fps)
    seconds = _checked_lengths(shot_seconds, fade, fps)
    final = media_duration(narration) + tail
    parts, last = _crossfades(len(shots), seconds, fade, fps, transition)
    hold = max(0.0, final - joined_duration(seconds, fade)) + 1.0
    parts.append(f"[{last}]{_picture_chain(hold, captions, fonts_dir)}[vout]")
    parts.append(_audio_chain(len(shots), narration, tail))
    args: list[str | Path] = []
    for shot in shots:
        args += ["-i", shot]
    args += ["-i", narration, "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
             "-t", f"{final:.3f}", *_delivery(fps, crf, preset), out]
    ffmpeg(args)
    return Path(out)


def _checked_lengths(shot_seconds: Sequence[float], fade: float, fps: int) -> list[float]:
    # The clips hold whole frames, so time the crossfades on what render_scene actually made.
    seconds = [frame_count(s, fps) / fps for s in shot_seconds]
    for index, length in enumerate(seconds):
        inner = 0 < index < len(seconds) - 1
        if len(seconds) > 1 and length <= (2 if inner else 1) * fade:
            raise ValueError(f"Shot {index} lasts {length:.2f}s, too short for {fade}s crossfades")
    return seconds


def _crossfades(count: int, seconds: Sequence[float], fade: float, fps: int, transition: str = "fade"):
    """Filtergraph parts that crossfade inputs 0..count-1, and the label of the result."""
    parts = [f"[{i}:v]fps={fps},settb=AVTB,format=yuv420p,setsar=1[s{i}]" for i in range(count)]
    last = "s0"
    for index, offset in enumerate(xfade_offsets(seconds, fade), start=1):
        parts.append(
            f"[{last}][s{index}]xfade=transition={transition}:duration={fade:.6f}"
            f":offset={_offset_arg(offset, fps)}[x{index}]"
        )
        last = f"x{index}"
    return parts, last


def _picture_chain(hold: float, overlays: Path | None, fonts_dir: Path) -> str:
    chain = [f"tpad=stop_mode=clone:stop_duration={hold:.3f}"]
    if overlays is not None:
        chain.append(
            f"subtitles=filename={escape_filter_value(str(overlays))}:fontsdir={escape_filter_value(str(fonts_dir))}"
        )
    chain.append("format=yuv420p")
    return ",".join(chain)


def _audio_chain(index: int, narration: Path, tail: float) -> str:
    return (f"[{index}:a]{loudness_filter(narration)},aresample=48000,"
            f"aformat=channel_layouts=stereo,apad=pad_dur={tail:g}[aout]")


def _delivery(fps: int, crf: int, preset: str) -> list[str]:
    """Encoder settings for the file uploaded to YouTube."""
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high", "-pix_fmt", "yuv420p",
            # Quality-first CRF, capped at YouTube's recommended upload bitrate for 1080p30
            "-maxrate", "8M", "-bufsize", "16M",
            "-r", str(fps), "-g", str(max(fps // 2, 1)), "-bf", "2", "-flags", "+cgop",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart"]


def join_shots(
    shots: Sequence[Path],
    shot_seconds: Sequence[float],
    out: Path,
    *,
    fade: float = 0.8,
    dip_in: float = 0.0,
    dip_out: float = 0.0,
    fps: int = FPS,
    crf: int = 14,
) -> Path:
    """One chapter's picture: its shots crossfaded, optionally fading up from black over `dip_in`
    seconds and down to black over `dip_out`. Silent, and exactly as long as the shots joined."""
    if not shots or len(shots) != len(shot_seconds):
        raise ValueError("Give one duration per shot")
    fade = snap_fade(fade, fps)
    seconds = _checked_lengths(shot_seconds, fade, fps)
    frames = round(joined_duration(seconds, fade) * fps)
    parts, last = _crossfades(len(shots), seconds, fade, fps)
    chain = []
    if dip_in > 0:
        chain.append(f"fade=t=in:st=0:d={dip_in:.3f}")
    if dip_out > 0:
        chain.append(f"fade=t=out:st={frames / fps - dip_out:.3f}:d={dip_out:.3f}")
    chain.append("format=yuv420p")
    parts.append(f"[{last}]{','.join(chain)}[vout]")
    args: list[str | Path] = []
    for shot in shots:
        args += ["-i", shot]
    args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-frames:v", str(frames), "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", out]
    ffmpeg(args)
    return Path(out)


def finish(
    clips: Sequence[Path],
    narration: Path,
    out: Path,
    *,
    overlays: Path | None = None,
    tail: float = 0.5,
    fps: int = FPS,
    crf: int = 18,
    preset: str = "medium",
    fonts_dir: Path = FONTS_DIR,
) -> Path:
    """Join chapter pictures end to end, burn in `overlays` (ASS), add the narration at -14 LUFS
    and encode the upload file (see assemble)."""
    if not clips:
        raise ValueError("No chapters to join")
    final = media_duration(narration) + tail
    inputs = "".join(f"[{i}:v]" for i in range(len(clips)))
    joined = f"{inputs}concat=n={len(clips)}:v=1:a=0,settb=AVTB" if len(clips) > 1 else "[0:v]settb=AVTB"
    hold = max(0.0, final - sum(media_duration(clip) for clip in clips)) + 1.0
    parts = [f"{joined},{_picture_chain(hold, overlays, fonts_dir)}[vout]", _audio_chain(len(clips), narration, tail)]
    args: list[str | Path] = []
    for clip in clips:
        args += ["-i", clip]
    args += ["-i", narration, "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
             "-t", f"{final:.3f}", *_delivery(fps, crf, preset), out]
    ffmpeg(args)
    return Path(out)
