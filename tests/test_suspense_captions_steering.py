import re

import zipfile

from owd.captions import LongCaptionStyle, long_caption_style_line, long_captions_events
from owd.overlays import ChapterCard, QuoteCard, card_windows, overlays_ass
from owd.steering import DIGEST_SUFFIX, digest_document, load_steering, read_docx
from owd.tts import BEAT_PAUSE, PARAGRAPH_PAUSE, plan_chunks
from owd.words import Word
from tests.helpers import words_at


def test_pause_markers_become_held_beats():
    chunks = plan_chunks("You replay it for days. [pause] Allen saw why.\n\n> Man is made or unmade by himself.\n\nEnd. [PAUSE]")
    assert [(c.text, c.pause_after, c.quote) for c in chunks] == [
        ("You replay it for days.", BEAT_PAUSE, 0),
        ("Allen saw why.", PARAGRAPH_PAUSE, 0),
        ("Man is made or unmade by himself.", PARAGRAPH_PAUSE, 1),
        ("End.", BEAT_PAUSE, 0),
    ]
    assert all("[" not in c.text for c in chunks)


def test_long_captions_highlight_each_word_and_hide_under_cards():
    words = words_at("You spend years battling the stubborn facts of your life.")
    words.append(Word("quoted", 5.0, 5.3, 1))  # quote words never get captions (the quote card shows them)
    events = long_captions_events(words, LongCaptionStyle(max_words=5))
    assert len(events) == 10 and all(",Caption," in e for e in events)
    assert "{\\c&H47D4FF&}You" in events[0] and "{\\c&H47D4FF&}spend" in events[1]
    hidden = long_captions_events(words, LongCaptionStyle(max_words=5), hidden=[(0.0, 1.0)])
    assert len(hidden) == 7  # the words spoken under a card at 0-1 s are skipped
    assert long_caption_style_line().startswith("Style: Caption,Lato,58,")


def test_long_captions_never_end_a_page_on_the():
    # Seen in the second video, at 10:25: "He who does this has become the" | "conscious, ..."
    words = words_at("He who does this has become the conscious, intelligent wielder of his mental powers.")
    pages = []
    for event in long_captions_events(words):
        text = re.sub(r"\{[^}]*\}", "", event.split(",,0,0,0,,", 1)[1])
        if not pages or pages[-1] != text:
            pages.append(text)
    assert pages == ["He who does this has become", "the conscious", "intelligent wielder of his mental powers"]


def test_card_windows_and_overlay_with_captions():
    quotes, chapters = [QuoteCard("A quote", 10.0, 14.0)], [ChapterCard(1, "Two", 30.0)]
    assert card_windows(quotes, chapters) == [(9.7, 15.3), (29.65, 33.05)]
    ass = overlays_ass(quotes, chapters, captions=["Dialogue: 2,0:00:01.00,0:00:02.00,Caption,,0,0,0,,{\\c&HFFFFFF&}Hi"],
                       caption_style=long_caption_style_line())
    assert "Style: Caption,Lato" in ass and ass.rstrip().endswith("Hi")


def make_docx(path, paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def make_pdf(path, text):
    """A one-page PDF with `text`, written by hand (so the test needs no PDF library)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


def test_uploaded_pdf_and_word_documents_are_read(tmp_path):
    references = tmp_path / "references"
    references.mkdir(parents=True)
    make_docx(references / "notes.docx", ["Open on the stakes.", "Never recap."])
    make_pdf(references / "book.pdf", "Titles name a loss.")
    (references / "broken.pdf").write_bytes(b"not a pdf")
    assert read_docx(references / "notes.docx") == "Open on the stakes.\nNever recap."
    steering = load_steering(tmp_path)
    names = dict(steering.references)
    assert "Titles name a loss." in names["book.pdf"] and "Never recap." in names["notes.docx"]
    assert any("broken.pdf" in w for w in steering.warnings)


def test_long_documents_are_condensed_once_and_the_digest_is_kept(tmp_path):
    references = tmp_path / "references"
    references.mkdir(parents=True)
    book = references / "long.md"
    book.write_text("A rule about titles. " * 1000, encoding="utf-8")
    calls = []

    def condense(name, text):
        calls.append(name)
        return "- Titles name a loss.\n- Hooks open a question."

    steering = load_steering(tmp_path, condense=condense)
    assert dict(steering.references)["long.md"].startswith("- Titles name a loss.")
    digest = references / ("long.md" + DIGEST_SUFFIX)
    assert digest.is_file() and calls == ["long.md"]
    load_steering(tmp_path, condense=condense)  # second run reuses the saved digest
    assert calls == ["long.md"]
    assert "long.md.digest.md" not in dict(load_steering(tmp_path).references)  # digests aren't references
    book.write_text("A changed rule. " * 1000, encoding="utf-8")
    assert digest_document(book, book.read_text(), condense) and calls == ["long.md", "long.md"]  # source changed
    digest.write_text("<!-- edited -->\n- My own rules.", encoding="utf-8")
    assert "My own rules." in dict(load_steering(tmp_path, condense=condense).references)["long.md"]  # owner edit kept


def test_long_documents_without_a_model_are_cut_with_a_warning(tmp_path):
    (tmp_path / "references").mkdir(parents=True)
    (tmp_path / "references" / "huge.txt").write_text("x " * 20_000, encoding="utf-8")
    steering = load_steering(tmp_path)
    assert len(dict(steering.references)["huge.txt"]) <= 12_000
    assert any("python -m owd steering" in w for w in steering.warnings)
