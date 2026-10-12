"""The pictures must stay in step with the narration for the whole video.

A real failure (12 Oct 2026): one shot rendered 2.7 s shorter than planned, the crossfade chain for
its chapter ended early, every later picture ran 156 s ahead of George's words, and the video ended
on a frozen frame. These tests keep that from happening again.
"""

import numpy as np
import pytest
from PIL import Image

from owd.ffmpeg import ffmpeg, probe
from owd.produce import check_lengths, next_clip
from owd.render import join_shots
from owd.stock import EDGE_TRIM, StockVideo
from owd.visuals import Visual
from tests.helpers import needs_ffmpeg


def colour_clip(path, colour, seconds):
    ffmpeg(["-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r=30:d={seconds}", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", path])
    return path


def brightness(video, at, out):
    ffmpeg(["-ss", f"{at}", "-i", video, "-frames:v", "1", out])
    return float(np.asarray(Image.open(out).convert("L"), dtype=np.float32).mean())


@needs_ffmpeg
def test_a_shot_shorter_than_planned_cannot_cut_its_chapter_short(tmp_path):
    short = colour_clip(tmp_path / "short.mp4", "white", 1.0)  # planned 2.3 s, but the file is only 1 s
    after = colour_clip(tmp_path / "after.mp4", "black", 2.3)
    last = colour_clip(tmp_path / "last.mp4", "white", 2.3)
    chapter = join_shots([short, after, last], [2.3, 2.3, 2.3], tmp_path / "chapter.mp4", fade=0.6)
    stream = next(s for s in probe(chapter)["streams"] if s["codec_type"] == "video")
    assert int(stream["nb_frames"]) == round((2.3 * 3 - 0.6 * 2) * 30)  # exactly the planned 5.7 s
    assert brightness(chapter, 1.4, tmp_path / "a.png") > 200  # the short shot's last frame is held
    assert brightness(chapter, 2.85, tmp_path / "b.png") < 40  # the second shot arrives on time
    assert brightness(chapter, 5.4, tmp_path / "c.png") > 200  # and so does the third


@needs_ffmpeg
def test_check_lengths_stops_a_video_that_would_drift(tmp_path):
    clip = colour_clip(tmp_path / "one.mp4", "white", 1.0)
    check_lengths([clip], [1.0])
    with pytest.raises(RuntimeError, match="drift out of sync"):
        check_lengths([clip], [2.0])


def video(id_, duration):
    return StockVideo(id=id_, page_url="", tags=("candle",), duration=duration, user="u", renditions=())


def test_next_clip_moves_through_the_scene_clips_then_starts_again():
    first, second = (video(1, 10.0), "r1"), (video(2, 20.0), "r2")
    visual = Visual("clip", [first, second])
    assert next_clip(visual, {}, 5.0)[0].id == 1 and next_clip(visual, {}, 5.0)[2] == EDGE_TRIM
    used_up_first = {1: 9.0}
    pick = next_clip(visual, used_up_first, 5.0)
    assert pick[0].id == 2 and pick[2] == EDGE_TRIM  # the second fitting clip, from its start
    assert next_clip(visual, {1: 3.0}, 5.0)[2] == 3.0  # continues where the first clip left off
    both_used = {1: 9.0, 2: 19.0}
    assert next_clip(visual, both_used, 5.0)[0].id == 1 and next_clip(visual, both_used, 5.0)[2] == EDGE_TRIM
