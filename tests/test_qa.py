import pytest

from owd.qa import compare, normalize, number_words
from tests.helpers import needs_ffmpeg


def test_normalize_unifies_spelling_and_punctuation():
    assert normalize("The armoury of Thought — realised; a century-old idea.") == [
        "the", "armory", "of", "thought", "realized", "a", "century", "old", "idea",
    ]


def test_normalize_spells_out_numbers_and_maps_known_name_spellings():
    assert [number_words(n) for n in (7, 30, 90, 105, 1903)] == [
        ["seven"], ["thirty"], ["ninety"], ["one", "hundred", "five"],
        ["one", "thousand", "nine", "hundred", "three"],
    ]
    assert normalize("About 90% of 1,200 people, said Alan.") == [
        "about", "ninety", "percent", "of", "one", "thousand", "two", "hundred", "people", "said", "allen",
    ]
    assert compare("roughly ninety percent, wrote James Allen in 1903", "roughly 90%, wrote James Alan in 1903").errors == 0
    assert compare("thirty years", "30 years").errors == 0


def test_compare_counts_and_names_the_differences():
    result = compare("Man is made or unmade by himself.", "man is made or by himself today")
    assert result.errors == 2
    assert result.differences == [("unmade", ""), ("", "today")]
    assert result.word_error_rate == pytest.approx(2 / 7)
    assert compare("the armoury of thought", "The armory of thought.").errors == 0
    assert compare("> Man is made.", "Man is made.").errors == 0  # quote markers aren't words


@pytest.mark.slow
@needs_ffmpeg
def test_narration_is_heard_as_written_and_quotes_are_numbered(tmp_path):
    from owd.qa import transcribe
    from owd.tts import Cast, Kokoro

    script = "The mind is a garden. James Allen said it best.\n\n> Man is made or unmade by himself."
    narration = Kokoro().synthesize(script, Cast())  # one voice: George reads the quote too
    narration.save(tmp_path / "n.wav")
    assert compare(script, transcribe(tmp_path / "n.wav")).errors <= 1

    words = narration.words
    assert [w.text for w in words][:3] == ["The", "mind", "is"]
    assert [w.quote for w in words] == [0] * 10 + [1] * 7
    assert all(0 <= w.start <= w.end <= narration.duration for w in words)
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))
