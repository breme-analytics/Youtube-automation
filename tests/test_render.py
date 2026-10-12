import numpy as np
import pytest
import soundfile
from PIL import Image

from owd.backgrounds import glow_background
from owd.captions import shorts_ass
from owd.ffmpeg import ffmpeg, measure_loudness, probe
from owd.render import (
    PAN_RIGHT,
    PUSH_IN,
    Motion,
    _offset_arg,
    assemble,
    render_clip,
    render_scene,
    xfade_offsets,
    zoompan_filter,
)
from tests.helpers import needs_ffmpeg, words_at

SIZE = (360, 640)  # a Short at a third of the size keeps the tests quick


def test_zoompan_filter_eases_zoom_and_position():
    graph = zoompan_filter(Motion(1.0, 1.2, 0.0, 1.0), frames=91, size=(1080, 1920), fps=30)
    assert graph.startswith("zoompan=z='(1+(1.2-1)*(0.5-0.5*cos(PI*on/90)))'")
    assert "x='(iw-iw/zoom)*(0+(1-0)*(0.5-0.5*cos(PI*on/90)))'" in graph
    assert graph.endswith(":d=91:s=1080x1920:fps=30")


def test_xfade_offsets():
    assert xfade_offsets([3.0, 4.0, 5.0], 0.5) == pytest.approx([2.5, 6.0])
    assert xfade_offsets([3.0], 0.5) == []
    # 275/30 s is frame 275: the argument sits half a frame before it
    assert _offset_arg(275 / 30, 30) == "9.150000"


def _stream(info, kind):
    return next(s for s in info["streams"] if s["codec_type"] == kind)


def _frame(video, seconds, out):
    ffmpeg(["-ss", f"{seconds}", "-i", video, "-frames:v", "1", out])
    return np.asarray(Image.open(out).convert("RGB"), dtype=np.float32)


@needs_ffmpeg
def test_render_scene_makes_an_exact_length_clip(tmp_path):
    still = tmp_path / "still.png"
    glow_background(SIZE, seed=1).save(still)
    clip = render_scene(still, tmp_path / "shot.mp4", seconds=1.5, size=SIZE, motion=PAN_RIGHT)
    video = _stream(probe(clip), "video")
    assert (video["width"], video["height"], video["codec_name"]) == (360, 640, "h264")
    assert int(video["nb_frames"]) == 45


@needs_ffmpeg
def test_assemble_crossfades_burns_captions_and_normalises_audio(tmp_path):
    # Characters that need filtergraph escaping, in the folder holding the captions and fonts
    work = tmp_path / "we:ird, [dir]'s"
    work.mkdir()
    shots, lengths = [], [1.6, 1.8]
    for index, seconds in enumerate(lengths):
        still = work / f"still-{index}.png"
        glow_background(SIZE, palette=("dawn", "teal")[index], seed=index).save(still)
        shots.append(render_scene(still, work / f"shot-{index}.mp4", seconds=seconds, size=SIZE, motion=PUSH_IN))

    narration = work / "narration.wav"
    t = np.arange(round(2.6 * 24_000)) / 24_000
    soundfile.write(str(narration), (0.05 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), 24_000)
    captions = work / "captions.ass"
    # Captions are laid out at full Short size; libass scales them to the 360x640 frame
    captions.write_text(shorts_ass(words_at("the mind is a garden", start=0.2)), encoding="utf-8")

    with_captions = assemble(shots, lengths, narration, work / "with.mp4", captions=captions, fade=0.6)
    without = assemble(shots, lengths, narration, work / "without.mp4", fade=0.6)

    info = probe(with_captions)
    video, audio = _stream(info, "video"), _stream(info, "audio")
    assert (video["width"], video["height"], video["r_frame_rate"], video["profile"]) == (360, 640, "30/1", "High")
    assert (audio["codec_name"], audio["sample_rate"], audio["channels"]) == ("aac", "48000", 2)
    assert float(info["format"]["duration"]) == pytest.approx(2.6 + 0.5, abs=0.05)
    assert measure_loudness(with_captions)["input_i"] == pytest.approx(-14.0, abs=1.0)

    # At 0.5 s "THE" or "MIND" is on screen: the caption band differs, the sky above doesn't
    a, b = _frame(with_captions, 0.5, work / "a.png"), _frame(without, 0.5, work / "b.png")
    band = slice(int(640 * 0.55), int(640 * 0.68))
    assert np.abs(a[band] - b[band]).mean() > 8
    assert np.abs(a[:200] - b[:200]).mean() < 1.5


@needs_ffmpeg
def test_render_clip_crops_trims_and_slows_a_landscape_clip_into_a_vertical_shot(tmp_path):
    # A 3 s, 25 fps landscape test clip; a 4 s shot needs it slowed by about 1.8x, capped at 1.5x
    source = tmp_path / "clip.mp4"
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=3", "-c:v", "libx264", "-pix_fmt",
            "yuv420p", source])
    shot = render_clip(source, tmp_path / "shot.mp4", seconds=4.0, size=SIZE)
    info = _stream(probe(shot), "video")
    assert (info["width"], info["height"], info["r_frame_rate"]) == (360, 640, "30/1")
    assert int(info["nb_frames"]) == 120
    assert not any(s["codec_type"] == "audio" for s in probe(shot)["streams"])
    start = _frame(shot, 0.1, tmp_path / "start.png")
    end = _frame(shot, 3.9, tmp_path / "end.png")
    assert np.abs(start - end).mean() > 5  # it moves: not a frozen first frame


@needs_ffmpeg
def test_assemble_rejects_shots_too_short_for_the_crossfade(tmp_path):
    with pytest.raises(ValueError, match="too short"):
        assemble([tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"], [2.0, 1.0, 2.0],
                 tmp_path / "n.wav", tmp_path / "out.mp4", fade=0.6)
