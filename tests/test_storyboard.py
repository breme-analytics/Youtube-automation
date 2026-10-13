import pytest

from owd.channel import load_cast, load_settings
from owd.config import ROOT
from owd.news import load_feeds
from owd.quotes import check_quotes, normalize
from owd.storyboard import (
    Claim,
    Research,
    Scene,
    Source,
    Storyboard,
    dump_storyboard,
    load_storyboard,
    parse_storyboard,
)
from owd.tts import Cast, Chunk, plan_chunks

FIXTURE = ROOT / "tests" / "fixtures" / "garden-short.toml"
SOURCE = ROOT / "sources" / "as-a-man-thinketh.txt"


def board(text, sources=True, **extra):
    data = {"title": "T", "format": "short", "scene": [{"visual": "owl", "text": text}], **extra}
    if sources:
        data["sources"] = [{"file": str(SOURCE), "cite": "James Allen, As a Man Thinketh (1903)"}]
    return parse_storyboard(data)


def test_short_fixture_still_loads_and_its_quote_is_in_the_book():
    sample = load_storyboard(FIXTURE)
    assert sample.format == "short" and len(sample.scenes) == 6
    assert sample.scenes[0].category == "animals"
    assert check_quotes(sample) == []


def test_format_defaults_to_long():
    assert parse_storyboard({"title": "T", "scene": [{"visual": "candle flame", "text": "Hello."}]}).format == "long"


def test_storyboard_validation_lists_every_problem():
    with pytest.raises(ValueError) as error:
        parse_storyboard({"format": "tiktok", "scene": [{"visual": "", "text": ""}],
                          "sources": [{"file": "sources/missing.txt"}]})
    message = str(error.value)
    for problem in ("title is missing", "format must be", "no visual", "no text", "source file not found"):
        assert problem in message


def test_quote_check_ignores_case_and_punctuation_but_not_words_and_suggests_the_real_wording():
    assert normalize("MAN'S mind—may _be_ likened,") == " mans mind may be likened "
    good = "> man's mind may be likened to a garden, which may be intelligently cultivated"
    assert check_quotes(board(good)) == []
    problems = check_quotes(board("> Man's mind may be compared to a garden, which may be intelligently cultivated"))
    assert "not found word for word" in problems[0]
    assert "the book says: \"Man's mind may be likened to a garden, which may be intelligently cultivated\"" in problems[0]
    assert "lists no [[sources]]" in check_quotes(board(good, sources=False))[0]
    assert check_quotes(board("No quotes here, just narration.", sources=False)) == []


def test_quote_paragraphs_are_numbered_and_read_by_the_narrator_by_default():
    script = "Allen put it simply.\n\n> Man is made or unmade by himself.\n> In the armoury of thought.\n\nThen.\n\n> Second."
    chunks = plan_chunks(script)
    assert [(c.text, c.quote) for c in chunks] == [
        ("Allen put it simply.", 0),
        ("Man is made or unmade by himself. In the armoury of thought.", 1),
        ("Then.", 0),
        ("Second.", 2),
    ]
    assert [c.quote for c in plan_chunks(script, first_quote=5)] == [0, 5, 0, 6]
    assert Cast().voice_for(chunks[1]) == ("bm_george", 1.0)
    assert Cast(quote="af_heart").voice_for(Chunk("x", 0, 1)) == ("af_heart", 0.95)
    with pytest.raises(ValueError):
        Cast(narrator="george")


def test_channel_settings_are_valid():
    """channel.toml is the owner's to change: check it's usable, not what it says."""
    from owd.books import book_chapters
    from owd.llm import models_from_settings
    from owd.minutes import budget
    from owd.schedule import make_days
    from owd.state import BOOK_ORDERS
    from owd.storage import StoragePolicy
    from owd.storyboard import FORMATS

    settings = load_settings()
    assert isinstance(load_cast(), Cast)  # the voices exist (Cast validates them)
    assert settings["video"]["format"] in FORMATS
    assert 0 < settings["video"]["min_words"] <= settings["video"]["max_words"]
    ids = [book["id"] for book in settings["books"]]
    assert len(ids) == len(set(ids)), "two books share an id"
    for book in settings["books"]:
        assert (ROOT / book["file"]).is_file() and book_chapters(book), book["id"]
        assert book["cite"]
    assert models_from_settings(settings)
    assert all(feed.kind in ("research", "platform") for feed in load_feeds(settings))
    assert make_days(settings) and settings["schedule"].get("book_order", "balanced") in BOOK_ORDERS
    assert budget(settings) >= 0 and StoragePolicy.from_settings(settings)


def test_dump_storyboard_round_trips():
    original = Storyboard(
        title='Why "you" can\'t stop \\ replaying',
        format="long",
        scenes=(
            Scene("storm clouds", "It's late.\nYou replay it again.", chapter="The loop"),
            Scene("book pages", "> Man is made or unmade by himself."),
            Scene("candle flame", "Text with ''' inside", category="backgrounds"),
        ),
        thumbnail_text="Stop the loop",
        thumbnail_accent=("STOP",),
        description="Two lines.\nSecond line.",
        sources=(Source(SOURCE, "James Allen, As a Man Thinketh (1903)"),),
        alt_titles=("One", "Two"),
        research=(Research("R1", "Worry study", "https://example.org/a?b=1&c=2", "psypost"),),
        claims=(Claim("Worry harms sleep", "R1"),),
    )
    path = ROOT / "tests" / "fixtures" / "_roundtrip.toml"
    try:
        path.write_text(dump_storyboard(original, "Header line\n\nWARNING: x"), encoding="utf-8")
        loaded = load_storyboard(path)
    finally:
        path.unlink(missing_ok=True)
    assert loaded.title == original.title and loaded.alt_titles == original.alt_titles
    assert [(s.visual, s.text.strip(), s.category, s.chapter) for s in loaded.scenes] == [
        (s.visual, s.text.strip(), s.category, s.chapter) for s in original.scenes
    ]
    assert loaded.research == original.research and loaded.claims == original.claims
    assert loaded.sources[0].file.resolve() == SOURCE.resolve()
    assert loaded.chapter_starts() == [(0, "The loop")]
    assert loaded.description == original.description
