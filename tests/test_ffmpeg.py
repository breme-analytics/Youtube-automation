import numpy as np
import pytest
import soundfile

from owd.config import DISPLAY_FONT
from owd.ffmpeg import escape_filter_value, loudness_filter, measure_loudness, normalize_audio
from owd.fonts import ass_em_pixels, font_metrics
from tests.helpers import needs_ffmpeg


def test_escape_filter_value_matches_the_ffmpeg_manual_example():
    # From "Notes on filtergraph escaping" in the ffmpeg-filters manual
    value = "this is a 'string': may contain one, or more, special characters"
    assert escape_filter_value(value) == (
        r"this is a \\\'string\\\'\\: may contain one\, or more\, special characters"
    )
    assert escape_filter_value("/plain/path with spaces/captions.ass") == "/plain/path with spaces/captions.ass"


def test_anton_metrics_drive_the_ass_em_size():
    assert font_metrics(str(DISPLAY_FONT)) == (2048, 2876, 674)
    assert ass_em_pixels(DISPLAY_FONT, 3550) == pytest.approx(2048)


def _tone(path, seconds=3.0, amplitude=0.05, rate=24_000):
    t = np.arange(round(seconds * rate)) / rate
    soundfile.write(str(path), (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate)
    return path


@needs_ffmpeg
def test_normalize_audio_reaches_youtube_loudness(tmp_path):
    quiet = _tone(tmp_path / "quiet.wav")
    assert measure_loudness(quiet)["input_i"] < -25
    loud = normalize_audio(quiet, tmp_path / "loud.wav")
    assert measure_loudness(loud)["input_i"] == pytest.approx(-14.0, abs=1.0)


@needs_ffmpeg
def test_silence_is_left_alone(tmp_path):
    silent = tmp_path / "silent.wav"
    soundfile.write(str(silent), np.zeros(24_000, dtype=np.float32), 24_000)
    assert loudness_filter(silent) == "anull"
