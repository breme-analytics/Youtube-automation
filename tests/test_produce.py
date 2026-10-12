import numpy as np
import pytest
import soundfile
from PIL import Image

from owd.ffmpeg import duration, ffmpeg, probe
from owd.overlays import ChapterCard, QuoteCard, overlays_ass
from owd.produce import (
    AI_NOTE,
    chapter_of_scenes,
    describe,
    quote_cards,
    review_text,
    timestamp,
)
from owd.qa import Comparison
from owd.render import finish, join_shots
from owd.storyboard import Claim, Research, Scene, Source, Storyboard
from owd.tts import Cast, Narration
from owd.words import Word
from tests.helpers import needs_ffmpeg

SOURCE = Source(__import__("owd.config").config.ROOT / "sources" / "as-a-man-thinketh.txt", "James Allen, As a Man Thinketh (1903)")


def board(**extra):
    scenes = (
        Scene("storm clouds", "Hook words.", chapter="The hook"),
        Scene("book pages", "> Man is made or unmade by himself."),
        Scene("candle flame", "More words.", chapter="The garden"),
    )
    return Storyboard(title="T", format="long", scenes=scenes, description="Summary.", sources=(SOURCE,), **extra)


def test_chapter_of_scenes_and_timestamps():
    assert chapter_of_scenes(board()) == ([0, 0, 1], ["The hook", "The garden"])
    untitled = Storyboard("T", "long", (Scene("a", "x"), Scene("b", "y", chapter="Two")))
    assert chapter_of_scenes(untitled) == ([0, 1], ["Intro", "Two"])
    assert [timestamp(s) for s in (0, 75.9, 3725)] == ["0:00", "1:15", "1:02:05"]


def test_description_lists_chapters_sources_research_ai_note_and_fits_youtubes_limit():
    research = (Research("R1", "Worry study", "https://example.org/w", "psypost"),)
    credits = [f"creator{i} on Pixabay: https://pixabay.com/videos/id-{i}/" for i in range(400)]
    chapters = [(0.0, "The hook"), (61.2, "The garden"), (130.0, "The science")]
    text = describe(board(research=research), chapters, credits, limit=1500)
    assert len(text) <= 1500
    assert "Chapters\n0:00 The hook\n1:01 The garden\n2:10 The science" in text
    assert "- James Allen, As a Man Thinketh (1903)" in text and "- Worry study: https://example.org/w" in text
    assert AI_NOTE in text and "Footage from Pixabay by creator0, creator1" in text and " others." in text
    short = describe(Storyboard("T", "short", (Scene("a", "x"),)), [], ["a on Pixabay: u"])
    assert short.endswith("#Shorts") and "Chapters" not in short


def test_quote_cards_follow_the_spoken_words_and_review_lists_claims():
    words = [Word("Hook", 0.0, 0.4), Word("Man", 1.0, 1.2, 1), Word("himself.", 2.0, 2.5, 1), Word("More", 3.0, 3.4)]
    narration = Narration(np.zeros(24_000 * 4, dtype=np.float32), words, Cast())
    cards = quote_cards(board(), narration)
    assert cards == [QuoteCard("Man is made or unmade by himself.", 1.0, 2.5, "James Allen, As a Man Thinketh (1903)")]
    text = review_text(board(claims=(Claim("Worry harms sleep", "R1"),), alt_titles=("Other",)), 4.0,
                       Comparison(1, 10, [("made", "maid")]), ["Check footage"], cards)
    assert "- [ ] Check every claim below is true" in text and "- Worry harms sleep (basis: R1)" in text
    assert "2. Other" in text and "script 'made' / heard 'maid'" in text and "- Check footage" in text


def _color_clip(path, colour, seconds, size="320x180"):
    ffmpeg(["-f", "lavfi", "-i", f"color=c={colour}:s={size}:r=30:d={seconds}", "-c:v", "libx264", "-pix_fmt",
            "yuv420p", path])
    return path


def _mean(video, at, out):
    ffmpeg(["-ss", f"{at}", "-i", video, "-frames:v", "1", out])
    return float(np.asarray(Image.open(out).convert("L"), dtype=np.float32).mean())


@needs_ffmpeg
def test_chapters_join_with_a_dip_through_black_and_finish_with_overlays(tmp_path):
    first = [_color_clip(tmp_path / "a.mp4", "white", 2.3), _color_clip(tmp_path / "b.mp4", "white", 2.3)]
    second = [_color_clip(tmp_path / "c.mp4", "white", 2.0)]
    one = join_shots(first, [2.3, 2.3], tmp_path / "ch1.mp4", fade=0.6, dip_out=0.35)
    two = join_shots(second, [2.0], tmp_path / "ch2.mp4", fade=0.6, dip_in=0.35)
    assert int(next(s for s in probe(one)["streams"])["nb_frames"]) == 120  # 2.3 + 2.3 - 0.6 = 4.0 s
    assert int(next(s for s in probe(two)["streams"])["nb_frames"]) == 60

    narration = tmp_path / "n.wav"
    t = np.arange(round(6.0 * 24_000)) / 24_000
    soundfile.write(str(narration), (0.05 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), 24_000)
    overlays = tmp_path / "o.ass"
    overlays.write_text(overlays_ass([QuoteCard("A short quote", 1.0, 2.0)], [ChapterCard(1, "Two", 4.0)],
                                     size=(320, 180)), encoding="utf-8")
    video = finish([one, two], narration, tmp_path / "video.mp4", overlays=overlays)
    assert duration(video) == pytest.approx(6.5, abs=0.05)
    assert _mean(video, 0.5, tmp_path / "f1.png") > 200  # plain white
    assert _mean(video, 3.99, tmp_path / "f2.png") < 60  # the dip to black at the chapter change
    assert _mean(video, 1.6, tmp_path / "f3.png") < 200  # dimmed under the quote card
