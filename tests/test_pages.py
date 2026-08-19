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

import shutil
from pathlib import Path
from typing import IO, Any

import pytest

from docxkit.pages import (
    Sheet,
    problems,
    read_pdf,
    render_anchors,
    sheets,
)

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


def test_the_footer_band_is_a_FRACTION_of_the_page_not_a_power_of_it(
        tmp_path):
    """`height * (1 - band)`, and `**` in place of `*` is the survivor
    that reads as arithmetic nobody would write. It is also the one a
    page of numbers exposes: 842 ** 0.88 is about 400, so the "footer"
    becomes the bottom HALF of the sheet, and a results table sitting
    there is read as page numbers.

    Two numbers in the band is ambiguity, which answers None — so the
    defect this produces is not a wrong number but a paper whose sheets
    all report no printed number at all, which reads as a document that
    was never numbered."""
    doc = pymupdf.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_text((72, 200), "Table 3. Coefficients", fontsize=11)
    # a table value halfway down: inside a band of half the page, well
    # outside a band of a tenth
    page.insert_text((72, 500), "42", fontsize=11)
    page.insert_text((A4[0] / 2, A4[1] - 40), "12", fontsize=11)
    pdf = tmp_path / "with-a-table.pdf"
    doc.save(str(pdf))
    doc.close()

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
# * `sheets()` — 15 survivors, and this note used to say killing them
#   needed a machine with Word. That was wrong, and it stood for two
#   days: `sheets` calls `export_pdf` and `read_pdf`, and a test that
#   substitutes BOTH exercises every line of it without Word ever
#   starting. The tests are at the bottom of this file. What needs Word
#   is `export_pdf` itself, which is one function further down.
# * `problems`: `now > was + 1` -> `now != was + 1` is EQUIVALENT. That
#   branch is an `elif` under `now <= was`, so `now < was + 1` never
#   reaches it and the two conditions differ nowhere.
# * `read_pdf`: `width > height` -> `>=` differs only on an exactly
#   square sheet, which no paper size is.
# * `_printed_number`: the clip rect's LEFT edge, and `found[0]` written
#   as `found[-1]`. The band is the full page width and the branch runs
#   only when the band holds exactly one number, so neither can differ
#   from what is written.

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
        # the sweep this test defeats on purpose leaves the staging
        # directory behind, and a test that litters TEMP on every run is
        # its own small defect: finish the job the flag declined to do
        shutil.rmtree(Path(seen["read"]).parent, ignore_errors=True)


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

# --- the eye gate: render the page an anchor falls on -------------------
#
# BACKLOG S4. The one check no gate in the ladder can make — a glyph that
# went the wrong way, an equation that renders wrong, a table that split
# — because all three are correct MARKUP and defects of the page. Moved
# in from DSI's `revision/scripts/render_pages.py`, the last piece of a
# private gate ladder still alive after that paper re-pointed onto the
# shared commands.


def _pdf(tmp_path, *pages_text: str):
    """A real PDF, one page per string."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page(width=A4[0], height=A4[1])
        page.insert_text((72, 200), text, fontsize=11)
    out = tmp_path / "render.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_an_anchor_is_rendered_from_the_page_it_falls_on(tmp_path):
    """The page number is the point: a PNG of the wrong page is worse
    than none, because it looks like an answer."""
    pdf = _pdf(tmp_path, "the opening page", "Table 3 sits here",
               "the closing page")

    made = render_anchors(pdf, ["Table 3 sits here"], dpi=40)

    (png,) = made.values()
    assert png is not None and png.exists()
    assert png.name.endswith("__p2.png"), png.name
    assert png.read_bytes()[:4] == b"\x89PNG"


def test_an_anchor_on_NO_page_is_named_rather_than_raised(tmp_path):
    """Half a render is worth more than none: the caller asked to LOOK
    at several things, and the one that could not be found is named in
    the answer instead of taking the others down with it."""
    pdf = _pdf(tmp_path, "the opening page", "Table 3 sits here")

    made = render_anchors(pdf, ["Table 3 sits here", "Table 9"], dpi=40)

    assert made["Table 3 sits here"] is not None
    assert made["Table 9"] is None
    assert list(made) == ["Table 3 sits here", "Table 9"], "asked order"


def test_the_FIRST_page_carrying_an_anchor_is_the_one_rendered(tmp_path):
    """A running head repeats a phrase on every page. The first one is
    where a reader goes looking, and rendering all of them is a folder
    of PNGs nobody reads."""
    pdf = _pdf(tmp_path, "prose", "Employment by age", "Employment by age")

    (png,) = render_anchors(pdf, ["Employment by age"], dpi=40).values()

    assert png is not None and png.name.endswith("__p2.png")


def test_the_pngs_land_where_the_caller_asked(tmp_path):
    """`out_dir` and `stem` together: a batch renders beside itself,
    under its own name, so two batches in one folder do not overwrite
    each other's pages."""
    pdf = _pdf(tmp_path, "Table 3 sits here")
    where = tmp_path / "pages"

    (png,) = render_anchors(pdf, ["Table 3"], dpi=40, out_dir=where,
                            stem="batch_r2").values()

    assert png is not None
    assert png.parent == where and png.name == "batch_r2__p1.png"


def test_an_empty_anchor_asks_for_nothing(tmp_path):
    """`--render` with a stray empty string is a shell artifact, not a
    request to render every page."""
    pdf = _pdf(tmp_path, "Table 3 sits here")

    assert render_anchors(pdf, ["", " ".strip()], dpi=40) == {}


def test_the_DEFAULT_render_is_150_dpi(tmp_path):
    """`dpi: int = 150`, and every test here passes 40 to keep itself
    quick — so the number a caller actually gets was free.

    150 is the eye gate's working resolution: `revision validate
    --render` exists to be LOOKED at, and a page rendered at 40 dpi
    answers "is there a table here" but not "is this the right table".
    The pixel width is the only place the choice is visible."""
    pdf = _pdf(tmp_path, "Table 3 sits here")

    (default,) = render_anchors(pdf, ["Table 3"]).values()

    assert default is not None

    def png_width(path) -> int:
        # bytes 16-19 of a PNG are the width, big-endian; no image
        # library needed, and none is a dependency of this package
        return int.from_bytes(path.read_bytes()[16:20], "big")

    with pymupdf.open(str(pdf)) as doc:
        points = doc[0].rect.width          # PDF points, 72 to the inch
    assert png_width(default) == round(points / 72 * 150)


def test_the_output_directory_is_created_with_its_PARENTS(tmp_path):
    """`mkdir(parents=True)`. `--render` is given a path a person typed,
    and `revision/build/pages/` under a fresh project has neither
    component: without the parents the run dies on the first anchor with
    a FileNotFoundError instead of writing what it was asked for."""
    pdf = _pdf(tmp_path, "Table 3 sits here")
    deep = tmp_path / "revision" / "build" / "pages"

    (png,) = render_anchors(pdf, ["Table 3"], dpi=40, out_dir=deep).values()

    assert png is not None and png.parent == deep


def test_a_SQUARE_sheet_is_not_landscape(tmp_path):
    """`rect.width > rect.height`, and `>=` calls a square page
    landscape. A square sheet is not exotic in this corpus — a poster
    or a figure page set to 210x210mm — and "landscape" is what
    `problems` uses to explain a blank sheet, so the wrong answer sends
    a person looking for a section break that is not there."""
    pdf = _render(tmp_path, [((500, 500), "A square figure page", "3")])

    (row,) = read_pdf(pdf)

    assert row.orientation == "portrait"


def test_a_number_printed_ABOVE_the_footer_band_is_not_read(tmp_path):
    """`height * (1 - band)` — the footer band is the bottom 12% of the
    sheet, and a number is only the sheet's number if Word printed it
    there (or in the matching band at the top).

    A digit in the BODY — a table cell, a year, a coefficient — is not
    a page number, and a band computed as `1 + band` or `band` alone
    swallows the whole page: every table of figures then reads as a
    numbering defect."""
    pdf = _render(tmp_path, [(A4, "The coefficient is 7", None)])

    (row,) = read_pdf(pdf)

    assert row.printed is None, "a number in the body is not the folio"


def test_a_number_in_the_HEADER_band_is_read(tmp_path):
    """The other band, and the reason there are two: a paper that
    numbers in the header is not a paper with no numbers. `(0, height *
    band)` is that band, and a mutant that collapses it reads every
    header-numbered paper as unnumbered."""
    pdf = _render(tmp_path, [(A4, "Section 1", None, "41")])

    (row,) = read_pdf(pdf)

    assert row.printed == 41


def test_a_JUMP_is_reported_on_page_numbers_ABOVE_the_int_cache(tmp_path):
    """`now > was + 1` — and `is not` in its place is true of every pair
    of ints CPython does not cache, so a document whose folios pass 256
    reports a jump between every consecutive sheet.

    A thesis reaches page 257. So does a long appendix, which is exactly
    the part of a document nobody rereads."""
    rows = [Sheet(number=n, orientation="portrait", printed=p,
                  blank=False)
            for n, p in ((1, 300), (2, 301), (3, 305))]

    found = problems(rows)

    assert len(found) == 1, found
    assert "JUMP" in found[0] and "301 -> 305" in found[0]


# --- what is left in pages.py, and why ----------------------------------
#
# `clip = page.rect.__class__(0, top, page.rect.width, bottom)` -> a
# left edge of 1 instead of 0. The clip is a horizontal band across the
# whole sheet and a page number sits in the middle of it; one point of
# margin at the left cannot exclude anything Word prints there. Argued
# rather than tested — a fixture would have to place a digit in the
# first point of the page, which is not a folio.
#
# `elif now > was + 1` -> `!= was + 1`. The branch is only reached when
# `now > was` (the `if` above catches the restart), so "not exactly one
# more" and "more than one more" are the same question there. The
# IDENTITY spelling of it is a real defect and is tested, at 300.
