from dataclasses import dataclass

import pytest

from owd import tts
from owd.tts import Chunk, plan_chunks, split_sentences, words_from_tokens


def test_split_sentences_keeps_closing_quotes_and_skips_abbreviations_and_initials():
    text = (
        'James Allen wrote: "Man is made or unmade by himself." Dr. Haanel agreed. '
        "Charles F. Haanel wrote in 1912! Really? Yes...  Fine"
    )
    assert split_sentences(text) == [
        'James Allen wrote: "Man is made or unmade by himself."',
        "Dr. Haanel agreed.",
        "Charles F. Haanel wrote in 1912!",
        "Really?",
        "Yes...",
        "Fine",
    ]


def test_plan_chunks_packs_sentences_and_pauses_between_paragraphs():
    script = "Short one. Another short one. A third.\n\n  New paragraph here, with a clause.\n"
    assert plan_chunks(script) == [
        Chunk("Short one. Another short one. A third.", tts.PARAGRAPH_PAUSE),
        Chunk("New paragraph here, with a clause.", 0.0),
    ]


def test_plan_chunks_keeps_chunks_kokoro_sized_and_loses_no_text():
    script = "This sentence is about forty-five characters. " * 20
    chunks = plan_chunks(script)
    assert len(chunks) == 4
    assert all(len(chunk.text) <= tts.TARGET_CHARS for chunk in chunks)
    assert [chunk.pause_after for chunk in chunks] == [tts.SENTENCE_PAUSE] * 3 + [0.0]
    assert " ".join(chunk.text for chunk in chunks) == " ".join(script.split())


def test_pack_never_leaves_a_short_chunk_alone_when_it_can_join_a_neighbour():
    assert tts._pack(["x" * 250, "y" * 20]) == ["x" * 250 + " " + "y" * 20]
    assert tts._pack(["y" * 20, "x" * 250]) == ["y" * 20 + " " + "x" * 250]
    assert tts._pack(["x" * 300, "y" * 50]) == ["x" * 300, "y" * 50]  # joined would pass the hard limit


def test_long_sentence_is_cut_at_clause_punctuation():
    clause = "and the mind keeps weaving what it was taught to weave"
    sentence = ", ".join([clause] * 8) + "."
    parts = tts._split_long(sentence)
    assert len(parts) == 2
    assert all(len(part) <= tts.HARD_MAX_CHARS for part in parts)
    assert parts[0].endswith(",") and parts[1].endswith(".")
    assert " ".join(parts) == sentence


@dataclass
class T:
    text: str
    whitespace: str
    start_ts: float | None
    end_ts: float | None


# Shaped like real Kokoro output: punctuation gets its own token and its own (pause) timing.
KOKORO_TOKENS = [
    T("James", " ", 1.2875, 1.675),
    T("Allen", " ", 1.675, 1.975),
    T("wrote", "", 1.975, 2.475),
    T(":", " ", 2.475, 2.575),
    T('"', "", 2.575, 2.65),
    T("Man", " ", 2.65, 2.9),
    T("himself", "", 4.25, 5.125),
    T(".", "", 5.125, 5.225),
    T('"', " ", 5.225, 5.2875),
    T("darker", " ", 6.45, 6.925),
    T("—", " ", 6.925, 7.0),
    T("and", " ", 7.0, 7.125),
    T("Haanel", " ", None, None),
    T("", " ", None, None),
    T("agreed", "", 7.775, 8.5),
    T(".", "", 8.5, 8.65),
]


def test_words_from_tokens_attaches_punctuation_and_times_words_by_their_letters():
    words = words_from_tokens(KOKORO_TOKENS, offset=10.0)
    assert [w.text for w in words] == [
        "James", "Allen", "wrote:", '"Man', 'himself."', "darker —", "and", "Haanel", "agreed.",
    ]
    by_text = {w.text: w for w in words}
    assert (by_text["wrote:"].start, by_text["wrote:"].end) == pytest.approx((11.975, 12.475))
    assert (by_text['"Man'].start, by_text['"Man'].end) == pytest.approx((12.65, 12.9))
    assert (by_text['himself."'].start, by_text['himself."'].end) == pytest.approx((14.25, 15.125))
    assert (by_text["darker —"].start, by_text["darker —"].end) == pytest.approx((16.45, 16.925))
    # Kokoro couldn't time "Haanel": it sits at the previous word's end, with no length
    assert by_text["Haanel"].start == by_text["Haanel"].end == pytest.approx(17.125)
    assert (by_text["agreed."].start, by_text["agreed."].end) == pytest.approx((17.775, 18.5))


def test_synthesize_rejects_unknown_voices_before_loading_the_model():
    with pytest.raises(ValueError, match="Unknown voice"):
        tts.Kokoro().synthesize("Hello there.", "jf_alpha")
