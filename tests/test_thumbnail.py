import numpy as np
import pytest
from PIL import Image

from owd.backgrounds import glow_background
from owd.thumbnail import MAX_BYTES, ThumbnailStyle, fit_headline, make_thumbnail


def test_thumbnail_is_a_1280x720_jpeg_under_2mb_with_the_accent_colour(tmp_path):
    out = make_thumbnail("He warned us in 1903", tmp_path / "thumb.jpg", accent=["1903"])
    image = Image.open(out)
    assert (image.format, image.size) == ("JPEG", (1280, 720))
    assert out.stat().st_size <= MAX_BYTES
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    gold = np.abs(pixels - np.array(ThumbnailStyle().accent_color)).sum(axis=2) < 60
    assert gold[:, : int(1280 * 0.63)].sum() > 2000  # the accent word, inside the text box


def test_thumbnail_accepts_a_background_of_any_shape(tmp_path):
    odd = glow_background((900, 1600), palette="violet", seed=3)
    out = make_thumbnail("Thought is a seed", tmp_path / "t.jpg", background=odd)
    assert Image.open(out).size == (1280, 720)


def test_fit_headline_shrinks_long_headlines_and_keeps_word_order():
    box = (742, 576)
    short_font, short_layout = fit_headline(["MIND", "IS", "MASTER"], box)
    long_words = "THE 1912 BOOK THAT EXPLAINS MANIFESTATION BETTER THAN TIKTOK".split()
    long_font, long_layout = fit_headline(long_words, box)
    assert long_font.size < short_font.size
    assert [w for line in long_layout for w in line] == long_words
    assert len(long_layout) <= 3


def test_fit_headline_refuses_what_cannot_fit():
    with pytest.raises(ValueError, match="too long"):
        fit_headline(["WORD"] * 40, (742, 576))
