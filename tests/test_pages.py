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

from pathlib import Path
from typing import IO, Any

import pytest

from docxkit.pages import Sheet, problems, read_pdf, sheets

pymupdf = pytest.importorskip("pymupdf",
                              reason="the render layer needs docxkit[pdf]")

A4 = (595, 842)          # points, portrait
A4_LANDSCAPE = (842, 595)


def _render(tmp_path, pages):
    """`pages` is a list of (size, body, footer) or (size, body, footer,
    header) — the text of one sheet, placed where Word would place it."""
    doc = pymupdf.open()
    for size, body, footer, *rest in pages:
        header = rest[0] if rest else None
        page = doc.new_page(width=size[0], height=size[1])
        if body:
            page.insert_text((72, 200), body, fontsize=11)
        if footer is not None:
            # the footer band: Word prints the number inside the margin
            page.insert_text((size[0] / 2, size[1] - 40), footer,
                             fontsize=11)
        if header is not None:
            page.insert_text((size[0] / 2, 40), header, fontsize=11)
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


def test_a_sheet_holding_only_a_DRAWING_is_not_blank(tmp_path):
    """A figure page can be vector graphics and nothing else — no text,
    no embedded image. Reading it as BLANK fails `--check` on a paper
    whose figures are fine, and a gate that cries wolf on figures is one
    the next batch turns off."""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    page.draw_line((72, 200), (400, 500))
    page.draw_rect(pymupdf.Rect(72, 520, 400, 700))
    out = tmp_path / "figure.pdf"
    doc.save(str(out))
    doc.close()

    assert read_pdf(out)[0].blank is False


def test_a_sheet_holding_only_an_IMAGE_is_not_blank(tmp_path):
    """The other way a figure page carries nothing readable: one raster,
    a scanned or pasted exhibit, and not a character of text."""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(pymupdf.Rect(72, 200, 400, 500), pixmap=pix)
    out = tmp_path / "scan.pdf"
    doc.save(str(out))
    doc.close()

    assert read_pdf(out)[0].blank is False


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
    # the whole note: the parenthetical is what tells a reader the gap
    # is unnumbered sheets rather than missing pages
    assert problems(rows) == ["printed numbers JUMP on sheet 2: 5 -> 7 "
                              "(the sheets between print nothing)"]


def test_a_REPEATED_number_is_NOT_a_gap_but_a_restart():
    """`now <= was`, not `<`. Two sheets printing 7 is the same defect as
    going backwards: something addressing page 7 finds whichever the
    reader turns to first."""
    rows = [Sheet(1, "portrait", 7, False), Sheet(2, "portrait", 7, False)]

    assert problems(rows) == ["printed numbering RESTARTS on sheet 2: "
                              "7 -> 7"]


def test_CONSECUTIVE_numbers_are_not_a_jump():
    """`now > was + 1`. Off by one here calls every sound document
    broken, which is the loudest way for a gate to stop being read."""
    assert problems([Sheet(1, "portrait", 3, False),
                     Sheet(2, "portrait", 4, False)]) == []


def test_a_blank_sheet_carries_its_flag_in_the_row():
    assert str(Sheet(4, "portrait", 4, True)).endswith(" BLANK")
    assert not str(Sheet(4, "portrait", 4, False)).endswith(" BLANK")


def test_a_clean_render_has_no_problems():
    rows = [Sheet(i, "portrait", i, False) for i in range(1, 6)]
    assert problems(rows) == []


def test_an_ambiguous_footer_answers_None_rather_than_guessing(tmp_path):
    """A wrong number here would read as a numbering defect that is not
    there — worse than saying nothing."""
    pdf = _render(tmp_path, [(A4, "body", "Chapter 3 page 14")])
    assert read_pdf(pdf)[0].printed is None


def test_the_header_is_read_when_the_footer_carries_no_number(tmp_path):
    """A paper that numbers in the header is not a paper with no numbers.

    The body text is not decoration: the band is 12 % of the height, and
    mutated to `height / band` it is eight times too tall — it would
    still find the header on a sheet with nothing else on it. With a
    number in the body, the honest band reads the header alone and the
    swollen one sees two numbers and answers None.
    """
    pdf = _render(tmp_path, [(A4, "42", None, "7")])

    assert read_pdf(pdf)[0].printed == 7


def test_the_FOOTER_wins_when_a_sheet_numbers_in_BOTH(tmp_path):
    """The bands are tried bottom first, and a running head repeating
    the number is common enough that the order has to be stated: the
    footer is where Word's own page field goes."""
    pdf = _render(tmp_path, [(A4, "Section 1", "12", "7")])

    assert read_pdf(pdf)[0].printed == 12


def test_a_sheet_with_no_number_in_either_band_reads_as_None(tmp_path):
    """Not 0, and not the physical index — the whole defect class here
    is the printed number and the sheet's position disagreeing."""
    pdf = _render(tmp_path, [(A4, "Title page", None)])

    assert read_pdf(pdf)[0].printed is None


# What the first mutation run (2026-08-17, 24.3 % real survival) left
# alive here that is not worth chasing, recorded so the next reader does
# not re-derive it:
#
# * `sheets()` — 15 survivors, all in the half that drives Word. Killing
#   them needs a machine with Word, which the everyday suite must not;
#   `pytest -m word` is where such a test would go.
# * `problems`: `now > was + 1` -> `now != was + 1` is EQUIVALENT. That
#   branch is an `elif` under `now <= was`, so `now < was + 1` never
#   reaches it and the two conditions differ nowhere.
# * `read_pdf`: `width > height` -> `>=` differs only on an exactly
#   square sheet, which no paper size is.

# --- sheets: where the render goes, and what happens to it afterwards ---
#
# `sheets` had 15 survivors, every one of them because no test ever
# called it. The function is four lines and each one is a decision: a
# named PDF is written where the caller asked and KEPT, an unnamed one
# goes to a staging directory that is removed, and the removal is told
# to ignore errors because on Windows a reader that has not released the
# file makes rmtree raise.

def _fake_render(monkeypatch, seen: dict[str, Any]) -> None:
    """Stand in for Word and for the PDF reader, and record both paths."""
    from docxkit import pages as pages_mod
    from docxkit import word as word_mod

    def export_pdf(docx, out_pdf, **kw):
        seen["asked"] = Path(out_pdf)
        Path(out_pdf).write_bytes(b"%PDF-1.4 not really\n")
        return Path(out_pdf)

    def read_pdf(pdf, *, band=0.0):
        seen["read"] = Path(pdf)
        seen["existed"] = Path(pdf).exists()
        seen["band"] = band
        return []

    monkeypatch.setattr(word_mod, "export_pdf", export_pdf)
    monkeypatch.setattr(pages_mod, "read_pdf", read_pdf)


def test_the_staging_sweep_survives_a_render_still_held_open(tmp_path,
                                                             monkeypatch):
    """`ignore_errors=True`. On Windows a file with a handle still on it
    cannot be removed, and the reader is the thing most likely to hold
    one — pymupdf keeps the PDF mapped until the document is closed.
    Without the flag the sweep raises AFTER the answer is in hand, and
    a table the caller already has is lost to the cleanup."""
    seen: dict[str, Any] = {}
    _fake_render(monkeypatch, seen)
    from docxkit import pages as pages_mod
    held: list[IO[bytes]] = []
    inner = pages_mod.read_pdf

    def read_and_hold(pdf, *, band=0.0):
        rows = inner(pdf, band=band)
        held.append(open(pdf, "rb"))     # noqa: SIM115 — held on purpose
        return rows

    monkeypatch.setattr(pages_mod, "read_pdf", read_and_hold)
    try:
        assert sheets(tmp_path / "paper.docx") == []
    finally:
        for handle in held:
            handle.close()


def test_a_named_pdf_is_written_where_it_was_asked_for_and_KEPT(tmp_path,
                                                                monkeypatch):
    """`keep_pdf is not None` — the branch that exists so a person can
    look at the render the table was read from."""
    seen: dict[str, Any] = {}
    _fake_render(monkeypatch, seen)
    wanted = tmp_path / "look-at-me.pdf"

    assert sheets(tmp_path / "paper.docx", keep_pdf=wanted, band=0.2) == []

    assert seen["asked"] == wanted
    assert seen["read"] == wanted and seen["band"] == 0.2
    assert wanted.exists(), "a kept PDF is the whole point of the argument"


def test_an_unnamed_render_goes_to_a_staging_file_that_is_REMOVED(
        tmp_path, monkeypatch):
    """The other branch: a temporary directory, a file inside it called
    render.pdf, and nothing left behind. `staging / "render.pdf"` is
    eleven of the survivors on its own — every arithmetic spelling of
    the path join raises, and none of them ever ran."""
    seen: dict[str, Any] = {}
    _fake_render(monkeypatch, seen)

    assert sheets(tmp_path / "paper.docx") == []

    staged = seen["read"]
    assert staged.name == "render.pdf"
    assert staged != tmp_path / "render.pdf", "not beside the document"
    assert seen["existed"], "the render is read before it is swept up"
    assert not staged.exists() and not staged.parent.exists()
