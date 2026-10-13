"""The books added on 13 Oct 2026, the chapter finder's layouts, and which book goes next."""

import pytest

from owd.books import book_chapter, book_chapters, chapters, clean_text, roman_value
from owd.channel import load_settings
from owd.config import ROOT
from owd.quotes import in_source
from owd.state import State, VideoRecord, chapters_left, next_chapter

BOOKS = {book["id"]: book for book in load_settings()["books"]}


def test_every_book_splits_into_the_chapters_its_contents_list():
    expected = {"the-kybalion": 15, "as-a-man-thinketh": 7, "the-way-of-peace": 7, "meditations": 12, "emerson-essays": 2}
    for book_id, count in expected.items():
        found = book_chapters(BOOKS[book_id])
        assert len(found) == count, book_id
        assert all(chapter.words >= 500 for chapter in found), book_id


def test_the_kybalion_title_case_contents_with_roman_numerals_and_sections():
    found = book_chapters(BOOKS["the-kybalion"])
    assert [(c.number, c.title) for c in found[:2]] == [(1, "The Hermetic Philosophy"), (2, "The Seven Hermetic Principles")]
    assert found[6].title == '"The All" in All'  # quotes in a title still find its heading
    assert found[0].text.startswith('"The lips of wisdom are closed')
    assert found[2].text.endswith("the Hermetic Art of\nMental Transmutation.")  # a wrapped line that matches a title stays
    assert "CHAPTER" not in found[0].text.split("\n")[-1]  # the next chapter's "CHAPTER II" isn't left at the end


def test_emerson_keeps_its_essay_numbers_and_only_the_chosen_essays():
    found = book_chapters(BOOKS["emerson-essays"])
    assert [(c.number, c.title) for c in found] == [(2, "SELF-RELIANCE"), (9, "THE OVER-SOUL")]
    assert not found[0].text.rstrip().endswith("III.")  # the next essay's numeral belongs to it
    assert book_chapter(BOOKS["emerson-essays"], "9").title == "THE OVER-SOUL"
    assert book_chapter(BOOKS["emerson-essays"], "over-soul").number == 9


def test_meditations_loses_its_section_numbers_but_quotes_still_check():
    first = book_chapters(BOOKS["meditations"])[0]
    assert first.title == "FIRST BOOK" and first.text.startswith("Of my grandfather Verus I have learned")
    assert "\n\nII. " not in first.text
    source = (ROOT / BOOKS["meditations"]["file"]).read_text(encoding="utf-8")
    # Two sentences across a section break: the quote check reads the same cleaned text.
    paragraphs = first.text.split("\n\n")
    across = paragraphs[0].split(". ")[-1] + " " + paragraphs[1].split(". ")[0] + "."
    assert in_source(across, clean_text(source)) and not in_source(across, source)


def test_the_way_of_peace_matches_headings_whatever_the_punctuation():
    found = book_chapters(BOOKS["the-way-of-peace"])
    assert found[5].title == "SAINTS, SAGES, AND SAVIORS; THE LAW OF SERVICE"  # the body heading has a colon
    assert found[5].text.startswith("The spirit of Love")


def test_a_chapter_list_that_isnt_in_the_book_says_what_is():
    with pytest.raises(ValueError, match="Not in the book's contents: Self-Reliant. Contents: HISTORY; SELF-RELIANCE"):
        chapters(ROOT / BOOKS["emerson-essays"]["file"], ["Self-Reliant"])


def test_clean_text_and_roman_numerals():
    assert clean_text("I. Of my grandfather.\n\nII. Of my mother.[12] And I.\nThen") == \
        "Of my grandfather.\n\nOf my mother. And I.\nThen"  # a wrapped "I." mid-paragraph stays
    assert [roman_value(n) for n in ("I", "IV", "IX", "XII", "XIV")] == [1, 4, 9, 12, 14]


def records(*pairs):
    return State([VideoRecord(f"{b}{n}", "t", b, n, "s", status="posted") for b, n in pairs])


BOOK_LIST = [{"id": "kyb"}, {"id": "amt"}, {"id": "emerson"}]
NUMBERS = {"kyb": 15, "amt": 7, "emerson": [2, 9]}


def test_balanced_order_lets_the_books_take_turns_starting_with_the_first():
    state = records(("amt", 2), ("amt", 4))  # the two videos made on the Mac
    picks = []
    for _ in range(6):
        pick = next_chapter(state, BOOK_LIST, NUMBERS, "balanced")
        picks.append(pick)
        state.videos.append(VideoRecord("x", "t", pick[0], pick[1], "s", status="posted"))
    assert picks == [("kyb", 1), ("emerson", 2), ("kyb", 2), ("emerson", 9), ("kyb", 3), ("amt", 1)]


def test_in_order_finishes_each_book_first_and_failed_chapters_come_back():
    state = records(("kyb", 1))
    state.videos.append(VideoRecord("f", "t", "kyb", 2, "s", status="failed"))
    assert next_chapter(state, BOOK_LIST, NUMBERS, "in order") == ("kyb", 2)
    assert chapters_left(state, BOOK_LIST, NUMBERS) == 14 + 7 + 2
    with pytest.raises(ValueError, match="book_order"):
        next_chapter(state, BOOK_LIST, NUMBERS, "random")
