"""Reading the RENDER, which is the only thing that can see pagination.

Two defects shipped in `Parental_style` because nothing surfaced them —
a numbering restart after the References with unnumbered section
openings, and a blank landscape sheet — and BOTH survived every
text-layer gate in this package, correctly, since neither moves a word.

The PDFs here are BUILT by the tests rather than fixtures on disk: the
analysis needs a render and does not need Word, so making the render is
what keeps the whole layer testable on any machine.
"""
from __future__ import annotations

import pytest

from docxkit.pages import Sheet, problems, read_pdf

pymupdf = pytest.importorskip("pymupdf",
                              reason="the render layer needs docxkit[pdf]")

A4 = (595, 842)          # points, portrait
A4_LANDSCAPE = (842, 595)


def _render(tmp_path, pages):
    """`pages` is a list of (size, body_text, footer_text | None)."""
    doc = pymupdf.open()
    for size, body, footer in pages:
        page = doc.new_page(width=size[0], height=size[1])
        if body:
            page.insert_text((72, 200), body, fontsize=11)
        if footer is not None:
            # the footer band: Word prints the number inside the margin
            page.insert_text((size[0] / 2, size[1] - 40), footer,
                             fontsize=11)
    out = tmp_path / "render.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_a_sheet_reports_its_orientation_and_printed_number(tmp_path):
    pdf = _render(tmp_path, [(A4, "Section 1", "12"),
                             (A4_LANDSCAPE, "Table 2 sideways", "13")])
    rows = read_pdf(pdf)

    assert [r.number for r in rows] == [1, 2]
    assert [r.orientation for r in rows] == ["portrait", "landscape"]
    assert [r.printed for r in rows] == [12, 13]
    assert not any(r.blank for r in rows)


def test_a_BLANK_sheet_is_found(tmp_path):
    """Two empty paragraphs that would not fit beside Table 2 — no text,
    no image, nothing to read, and no text-layer check can see it."""
    pdf = _render(tmp_path, [(A4, "Table 2", "8"),
                             (A4_LANDSCAPE, "", None),
                             (A4, "Table 3", "10")])
    rows = read_pdf(pdf)

    assert [r.blank for r in rows] == [False, True, False]
    assert "sheet 2 is BLANK" in problems(rows)


def test_a_sheet_that_prints_NOTHING_is_reported_but_does_not_fail():
    """A title page legitimately carries no number, and a gate that
    fails on every paper is a gate nobody runs."""
    rows = [Sheet(1, "portrait", None, False),
            Sheet(2, "portrait", 2, False)]
    assert problems(rows) == []
    assert "prints    -" in str(rows[0])


def test_the_numbering_RESTART_is_caught():
    """Parental_style rendered `… 28, -, -, 3, -, 5 …`: a second section
    with pgNumType w:start="1" behind four titlePg openings."""
    rows = [Sheet(28, "portrait", 28, False),
            Sheet(29, "portrait", None, False),
            Sheet(30, "portrait", None, False),
            Sheet(31, "portrait", 3, False)]
    found = problems(rows)
    assert any("RESTARTS on sheet 31: 28 -> 3" in note for note in found)


def test_a_GAP_in_the_printed_sequence_is_caught():
    rows = [Sheet(1, "portrait", 5, False), Sheet(2, "portrait", 7, False)]
    assert any("JUMP on sheet 2: 5 -> 7" in n for n in problems(rows))


def test_a_clean_render_has_no_problems():
    rows = [Sheet(i, "portrait", i, False) for i in range(1, 6)]
    assert problems(rows) == []


def test_an_ambiguous_footer_answers_None_rather_than_guessing(tmp_path):
    """A wrong number here would read as a numbering defect that is not
    there — worse than saying nothing."""
    pdf = _render(tmp_path, [(A4, "body", "Chapter 3 page 14")])
    assert read_pdf(pdf)[0].printed is None


def test_the_header_is_read_when_the_footer_carries_no_number(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_text((A4[0] / 2, 40), "7", fontsize=11)     # header band
    page.insert_text((72, 300), "body text", fontsize=11)
    out = tmp_path / "header.pdf"
    doc.save(str(out))
    doc.close()

    assert read_pdf(out)[0].printed == 7
