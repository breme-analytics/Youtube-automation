import re

import pytest

from owd.captions import (
    ShortCaptionStyle,
    ass_color,
    ass_time,
    leans_forward,
    short_pages,
    short_text,
    shorts_ass,
    srt,
    srt_cues,
    srt_time,
    wrap_cue,
)
from owd.config import DISPLAY_FONT
from owd.fonts import TextMeter
from owd.words import Word
from tests.helpers import words_at

STYLE = ShortCaptionStyle()
WIDE = 10_000  # page width that never binds, to test the grouping rules alone


def pages_of(words, max_width=WIDE, style=STYLE):
    meter = TextMeter(DISPLAY_FONT, style.font_size, style.outline)
    return [" ".join(label for _, label in page) for page in short_pages(words, style, meter, max_width)]


def test_colours_and_times_use_ass_conventions():
    assert ass_color("#FFD447") == "&H0047D4FF"
    assert ass_color("#FFD447", None) == "&H47D4FF&"
    assert ass_color("#000000", 0x80) == "&H80000000"
    with pytest.raises(ValueError):
        ass_color("gold")
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(3661.239) == "1:01:01.24"
    assert srt_time(3661.2394) == "01:01:01,239"


@pytest.mark.parametrize(
    ("word", "caption"),
    [('"Man', "MAN"), ('himself."', "HIMSELF"), ("right?", "RIGHT?"), ("thought —", "THOUGHT"),
     ("don't", "DON'T"), ("century-old", "CENTURY-OLD"), ("—", "")],
)
def test_short_text(word, caption):
    assert short_text(word) == caption


def test_pages_split_phrases_evenly_without_lone_words():
    assert pages_of(words_at('"Man is made or unmade by himself."')) == ["MAN IS MADE", "OR UNMADE", "BY HIMSELF"]


@pytest.mark.parametrize(
    ("word", "leans"),
    [("the", True), ('"The', True), ("of", True), ("and", True), ("has", True),
     ("the,", False), ("of.", False), ("this", False), ("does", False), ("purpose", False), ("—", False)],
)
def test_leaning_words(word, leans):
    assert leans_forward(word) is leans


def test_pages_never_end_on_a_leaning_word():
    # Before: "YOU SPEND YEARS BATTLING THE | STUBBORN FACTS OF YOUR LIFE"
    style = ShortCaptionStyle(max_words=5)
    assert pages_of(words_at("You spend years battling the stubborn facts of your life."), style=style) == [
        "YOU SPEND YEARS BATTLING", "THE STUBBORN FACTS", "OF YOUR LIFE",
    ]


def test_srt_lines_never_end_on_a_leaning_word():
    # The evenest break would be "...has become the / conscious, intelligent wielder".
    assert wrap_cue("He who does this has become the conscious, intelligent wielder") == [
        "He who does this has become", "the conscious, intelligent wielder",
    ]


def test_an_srt_cue_that_can_only_break_after_into_is_split():
    words = words_at("Do not allow thoughts to wander into ephemeral fancies, longings, imaginings.", step=0.3)
    cues = [lines for _, _, lines in srt_cues(words)]
    assert all(not leans_forward(lines[0].split()[-1]) for lines in cues if len(lines) == 2)
    assert " ".join(" ".join(lines) for lines in cues) == " ".join(w.text for w in words)


def test_a_spoken_dash_is_a_break_like_a_comma():
    words = words_at("When the drift pulls and it will bring the mind back.")
    words.insert(4, Word("—", words[3].end, words[3].end))  # Kokoro gives a dash its own, silent token
    words.insert(8, Word("—", words[7].end, words[7].end))
    pages = short_pages(words, ShortCaptionStyle(max_words=7), TextMeter(DISPLAY_FONT, 190, 9.0), WIDE)
    assert [word.text for word, _ in pages[0]][-1] == "will—"  # "...and it will —" is a fine place to break
    assert [label for page in pages for _, label in page] == "WHEN THE DRIFT PULLS AND IT WILL BRING THE MIND BACK".split()


def test_pages_end_at_sentence_ends_and_pauses():
    words = words_at("Cute, right? Keep reading.") + words_at("Then silence.", start=3.0)
    assert pages_of(words) == ["CUTE RIGHT?", "KEEP READING", "THEN SILENCE"]


def test_pages_respect_the_line_width():
    meter = TextMeter(DISPLAY_FONT, STYLE.font_size, STYLE.outline)
    narrow = meter.width("PSYCHOLOGISTS") + 1
    assert meter.width("HAVE NAMES") <= narrow < meter.width("MODERN PSYCHOLOGISTS")
    assert pages_of(words_at("modern psychologists have names"), max_width=narrow) == [
        "MODERN", "PSYCHOLOGISTS", "HAVE NAMES",
    ]


def _events(ass: str):
    events = []
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            _, start, end, *_rest = line.split(",", 9)
            text = line.split(",", 9)[9]
            events.append((start, end, text))
    return events


def _seconds(stamp: str) -> float:
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def test_shorts_ass_highlights_exactly_the_spoken_word():
    words = words_at("In 1903, a quiet English writer named James Allen.")
    ass = shorts_ass(words)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert re.search(r"^Style: Short,Anton,190,", ass, re.M)
    events = _events(ass)
    assert len(events) == len(words)
    highlight = ass_color(STYLE.highlight_color, None)
    for (start, end, text), word in zip(events, words):
        assert text.count(highlight) == 1
        assert re.search(rf"\\c{re.escape(highlight)}\}}{re.escape(short_text(word.text))}(\s|$)", text)
        assert _seconds(start) == pytest.approx(word.start, abs=0.01)
    times = [(_seconds(s), _seconds(e)) for s, e, _ in events]
    assert all(start < end for start, end in times)
    assert all(end <= next_start + 1e-9 for (_, end), (next_start, _) in zip(times, times[1:]))


def test_shorts_ass_squeezes_a_word_too_wide_for_the_line():
    ass = shorts_ass([Word("Antidisestablishmentarianism", 0.0, 1.0)])
    assert re.search(r"\{\\fscx(\d+)\\fscy\1\}", _events(ass)[0][2])


def test_quote_words_are_drawn_in_the_quote_colour():
    words = [Word("Allen", 0.0, 0.4), Word("wrote:", 0.45, 0.9), Word('"Mind', 1.5, 1.9, True),
             Word("is", 1.95, 2.1, True), Word('master."', 2.15, 2.6, True)]
    events = _events(shorts_ass(words))
    quote, white = ass_color(STYLE.quote_color, None), ass_color(STYLE.text_color, None)
    # Pages: "ALLEN WROTE" (the colon ends it), then "MIND IS MASTER"
    assert f"{{\\c{white}}}WROTE" in events[0][2]  # 'ALLEN' highlighted, 'WROTE' white
    assert f"{{\\c{quote}}}IS" in events[2][2]  # 'MIND' highlighted, 'IS' cream


def test_wrap_cue_balances_two_lines_and_prefers_punctuation():
    text = "He says that in the armoury of thought, we forge the very weapons that destroy us."
    assert wrap_cue(text) == ["He says that in the armoury of thought,", "we forge the very weapons that destroy us."]
    assert wrap_cue("Short line.") == ["Short line."]


def test_srt_cues_fit_two_lines_six_seconds_and_never_overlap():
    words = words_at(" ".join(["thought shapes the world we walk in every day"] * 4) + ".", step=0.3)
    words += words_at("Yes.", start=words[-1].end + 0.2)
    cues = srt_cues(words)
    assert len(cues) > 2
    for start, end, lines in cues:
        assert 1 <= len(lines) <= 2 and all(len(line) <= 42 for line in lines)
        assert end - start <= 6.0 + 1e-9
    assert all(end <= next_start for (_, end, _), (next_start, _, _) in zip(cues, cues[1:]))
    # The one-word sentence at the end gets a readable minimum duration
    assert cues[-1][2] == ["Yes."] and cues[-1][1] - cues[-1][0] == pytest.approx(1.0)


def test_srt_starts_a_cue_at_each_sentence_and_formats_blocks():
    text = srt(words_at("Cute, right? Keep reading, and it gets darker."))
    # "Cute, right?" would stay up for the 1 s minimum, but the next sentence starts at 0.8 s
    assert text == (
        "1\n00:00:00,000 --> 00:00:00,800\nCute, right?\n\n"
        "2\n00:00:00,800 --> 00:00:03,150\nKeep reading, and it gets darker.\n"
    )
