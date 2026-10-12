import pytest

from owd.qa import compare, normalize
from tests.helpers import needs_ffmpeg


def test_normalize_unifies_spelling_and_punctuation():
    assert normalize("The armoury of Thought — realised; a century-old idea.") == [
        "the", "armory", "of", "thought", "realized", "a", "century", "old", "idea",
    ]


def test_compare_counts_and_names_the_differences():
    result = compare("Man is made or unmade by himself.", "man is made or by himself today")
    assert result.errors == 2
    assert result.differences == [("unmade", ""), ("", "today")]
    assert result.word_error_rate == pytest.approx(2 / 7)
    assert compare("the armoury of thought", "The armory of thought.").errors == 0
    assert compare("> Man is made.", "Man is made.").errors == 0  # quote markers aren't words


@pytest.mark.slow
@needs_ffmpeg
def test_two_voice_narration_is_heard_as_written(tmp_path):
    from owd.qa import transcribe
    from owd.tts import Cast, Kokoro

    script = "The mind is a garden. James Allen said it best.\n\n> Man is made or unmade by himself."
    narration = Kokoro().synthesize(script, Cast())
    narration.save(tmp_path / "n.wav")
    assert compare(script, transcribe(tmp_path / "n.wav")).errors <= 1

    words = narration.words
    assert [w.text for w in words][:3] == ["The", "mind", "is"]
    assert [w.quote for w in words] == [False] * 10 + [True] * 7
    assert all(0 <= w.start <= w.end <= narration.duration for w in words)
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))
