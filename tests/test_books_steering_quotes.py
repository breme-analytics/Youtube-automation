import pytest

from owd.books import book_text, chapters, find_chapter
from owd.config import ROOT
from owd.quotes import _display, repair_quote
from owd.steering import load_steering

BOOK = ROOT / "sources" / "as-a-man-thinketh.txt"


def test_as_a_man_thinketh_has_its_seven_chapters():
    found = chapters(BOOK)
    assert [c.title for c in found] == [
        "THOUGHT AND CHARACTER", "EFFECT OF THOUGHT ON CIRCUMSTANCES", "EFFECT OF THOUGHT ON HEALTH AND THE BODY",
        "THOUGHT AND PURPOSE", "THE THOUGHT-FACTOR IN ACHIEVEMENT", "VISIONS AND IDEALS", "SERENITY",
    ]
    assert found[1].text.startswith("MAN'S mind may be likened to a garden") and found[1].words > 2000
    assert found[6].text.endswith('"Peace, be still!"')
    text = book_text(BOOK)
    assert "START OF THE PROJECT GUTENBERG" not in text and "Project Gutenberg License" not in text


def test_find_chapter_by_number_or_title():
    assert find_chapter(BOOK, "3").number == 3
    assert find_chapter(BOOK, "serenity").title == "SERENITY"
    with pytest.raises(ValueError, match="matched 0 chapters"):
        find_chapter(BOOK, "9")
    with pytest.raises(ValueError, match="matched 2 chapters"):
        find_chapter(BOOK, "effect of thought")


def test_chapters_of_a_small_book_with_windows_line_endings(tmp_path):
    book = tmp_path / "book.txt"
    book.write_bytes(
        b"Header\r\n*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\r\nCONTENTS\r\n\r\nONE\r\n\r\nTWO PARTS\r\n\r\n\r\n"
        b"PREFACE\r\nWords.\r\n\r\nONE\r\nFirst body.\r\n\r\nTWO PARTS\r\nSecond body.\r\n"
        b"*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\r\nLicense"
    )
    assert [(c.title, c.text) for c in chapters(book)] == [("ONE", "First body."), ("TWO PARTS", "Second body.")]


def test_steering_loads_instructions_and_references_but_not_switched_off_ones(tmp_path):
    (tmp_path / "references" / "off").mkdir(parents=True)
    (tmp_path / "instructions.md").write_text("Use George.", encoding="utf-8")
    (tmp_path / "references" / "b.md").write_text("B rules", encoding="utf-8")
    (tmp_path / "references" / "a.md").write_text("A rules", encoding="utf-8")
    (tmp_path / "references" / "off" / "c.md").write_text("C rules", encoding="utf-8")
    steering = load_steering(tmp_path)
    assert [name for name, _ in steering.references] == ["a.md", "b.md"]
    prompt = steering.as_prompt()
    assert prompt.startswith("OWNER INSTRUCTIONS") and "Use George." in prompt and "C rules" not in prompt
    capped = load_steering(tmp_path, max_chars=len("Use George.") + 8)
    assert [name for name, _ in capped.references] == ["a.md"] and "b.md" in capped.warnings[0]


def test_the_real_steering_area_loads_within_limits():
    steering = load_steering()
    names = {name for name, _ in steering.references}
    assert {"titles-power-of-bad.md", "retention-mario-joos.md", "youtube-guardrails.md", "visual-style.md"} <= names
    assert "George" in steering.instructions and steering.warnings == ()


def test_repair_quote_finds_the_books_wording():
    source = BOOK.read_text(encoding="utf-8")
    slipped = "Man's mind may be compared to a garden, which may be intelligently cultivated"
    assert repair_quote(slipped, source) == "Man's mind may be likened to a garden, which may be intelligently cultivated"
    assert repair_quote("rockets and moon landings happened in the summer of sixty nine", source) is None
    assert _display(["MAN'S", "mind", "_bring", "forth._", "CALMNESS", "of"]) == "Man's mind bring forth. Calmness of"
