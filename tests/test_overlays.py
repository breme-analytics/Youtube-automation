from owd.captions import ass_color
from owd.fonts import TextMeter
from owd.overlays import (
    SERIF_ITALIC,
    ChapterCard,
    OverlayStyle,
    QuoteCard,
    balance,
    layout_quote,
    overlays_ass,
    roman,
    wrap_lines,
)

STYLE = OverlayStyle()
LONG_QUOTE = ("Man's mind may be likened to a garden, which may be intelligently cultivated or allowed to run wild; "
              "but whether cultivated or neglected, it must, and will, bring forth. If no useful seeds are put into "
              "it, then an abundance of useless weed-seeds will fall therein.")


def events(ass):
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


def test_layout_quote_fits_the_width_and_line_limit():
    for text in (LONG_QUOTE, f"{LONG_QUOTE} {LONG_QUOTE}"):
        size, lines = layout_quote(text)
        meter = TextMeter(SERIF_ITALIC, size)
        assert len(lines) <= STYLE.quote_max_lines and all(meter.width(line) <= STYLE.quote_width for line in lines)
        assert " ".join(lines) == text
    assert layout_quote(LONG_QUOTE)[0] == STYLE.quote_sizes[0]
    assert layout_quote(f"{LONG_QUOTE} {LONG_QUOTE}")[0] < STYLE.quote_sizes[0]  # twice as long: smaller type
    assert layout_quote("Peace, be still!") == (STYLE.quote_sizes[0], ["Peace, be still!"])


def test_balance_evens_out_lines_without_adding_any():
    meter = TextMeter(SERIF_ITALIC, 60)
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    greedy = wrap_lines(text, meter, 1000)
    even = balance(greedy, meter, 1000)
    assert len(even) == len(greedy) and " ".join(even) == text
    widths = [meter.width(line) for line in even]
    assert max(widths) - min(widths) <= max(meter.width(l) for l in greedy) - min(meter.width(l) for l in greedy)


def test_overlays_have_dimmed_quote_cards_and_roman_chapter_cards():
    ass = overlays_ass([QuoteCard("Mind is the {master} power", 20.0, 26.0, "James Allen, As a Man Thinketh (1903)")],
                       [ChapterCard(1, "The Garden", 40.0), ChapterCard(2, "The Weeds", 19.0)])
    found = events(ass)
    dims = [e for e in found if ",Dim," in e]
    quotes = [e for e in found if ",Quote," in e]
    chapters = [e for e in found if ",Chapter," in e]
    assert len(quotes) == 1 and "(master)" in quotes[0] and "{master}" not in quotes[0]
    assert "— James Allen, As a Man Thinketh (1903)" in quotes[0]
    assert ass_color(STYLE.quote_color, None) in quotes[0]
    assert quotes[0].split(",")[1] == "0:00:19.70" and quotes[0].split(",")[2] == "0:00:27.30"
    # Chapter II would start under the quote card, so it is dropped; chapter I is labelled "CHAPTER I"
    assert len(chapters) == 1 and "CHAPTER I\\N" in chapters[0] and "The Garden" in chapters[0]
    assert len(dims) == 2 and all("\\p1" in d for d in dims)
    assert "PlayResX: 1920" in ass and "PlayResY: 1080" in ass


def test_roman():
    assert [roman(n) for n in (1, 4, 9, 14, 40)] == ["I", "IV", "IX", "XIV", "XL"]
