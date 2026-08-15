"""The house style for a table, in one call instead of per paper.

`booktabs` sets the RULES and stopped there. Everything else — the face
at run level AND in each cell's paragraph default so an empty cell
inherits it, full width with autofit, `cantSplit` on every row,
`keepNext` on the caption — was re-derived in every paper that needed
it.

What that cost on LI7 (2026-08-15): a new appendix table built with
`body.table`'s defaults, whose `tblStyle` is `TableGrid` — a full box
grid, the exact opposite of the three-line house style — with its
caption's properties cloned from the nearest existing table. That paper
has two generations of table in it and the nearest was the OLD one, so
"match the neighbouring table" propagated the wrong style. The author
caught it by eye.
"""
from __future__ import annotations

import pytest
from conftest import document, para, row, run, table

from docxkit.errors import AnchorError
from docxkit.tables import by_caption, house, house_rpr, read_all


def _doc(caption: str = "Table A4: Data sources") -> str:
    return document(
        para(run(caption))
        + table(row("Country", "Source"),
                row("Kazakhstan", "UNFPA"),
                row("", "")))          # the empty cell that must inherit


def test_the_face_lands_on_runs_AND_on_the_cell_paragraph_default():
    xml = _doc()
    out, report = house(xml, read_all(xml)[0])

    assert report.runs and report.paragraphs
    body = out[out.index("<w:tbl"):]
    assert body.count('w:ascii="Arial Narrow"') >= 6, \
        "runs and paragraph defaults both carry the face"
    assert '<w:sz w:val="20"/>' in body, "10 pt is stored doubled"
    # the EMPTY cell has no run at all, so only the pPr can carry it
    empty = body[body.rindex("<w:tr"):]
    assert 'w:ascii="Arial Narrow"' in empty


def test_the_header_row_is_bold_and_the_body_is_not():
    xml = _doc()
    from docxkit.tables import rows_of

    out, _ = house(xml, read_all(xml)[0])

    body = out[out.index("<w:tbl"):out.index("</w:tbl>")]
    rows = [m.group(0) for m in rows_of(body)]
    assert "<w:b/>" in rows[0], "the header row"
    assert not any("<w:b/>" in r for r in rows[1:]), "a data row was bolded"


def test_every_row_gets_cantSplit_and_never_a_SECOND_trPr():
    """A row may carry only one `w:trPr`, and `body.table` gives the
    header row one for `tblHeader` — a second is invalid, and `lint`
    reports it as "w:tr carries 2 w:trPr elements"."""
    xml = _doc().replace("<w:tr>", "<w:tr><w:trPr><w:tblHeader/></w:trPr>", 1)
    out, report = house(xml, read_all(xml)[0])

    body = out[out.index("<w:tbl"):]
    assert body.count("<w:cantSplit/>") == 3 == report.rows
    assert body.count("<w:trPr>") == 3, "a second w:trPr was appended"
    assert "<w:tblHeader/>" in body, "the existing trPr content survived"


def test_the_table_is_set_to_full_width_and_autofit():
    xml = _doc()
    out, report = house(xml, read_all(xml)[0])
    assert report.width
    assert '<w:tblW w:w="5000" w:type="pct"/>' in out
    assert '<w:tblLayout w:type="autofit"/>' in out


def test_a_width_already_set_is_REPLACED_not_doubled():
    xml = _doc().replace("<w:tblPr>",
                         '<w:tblPr><w:tblW w:w="9360" w:type="dxa"/>', 1)
    out, _ = house(xml, read_all(xml)[0])
    assert out.count("<w:tblW") == 1
    assert 'w:type="dxa"' not in out


def test_the_caption_is_kept_with_its_table():
    """Otherwise the caption sits alone at the foot of the page before
    the table it names."""
    xml = _doc()
    out, report = house(xml, read_all(xml)[0], caption="Table A4:")
    assert report.caption
    assert "<w:keepNext/>" in out[:out.index("<w:tbl")]


def test_a_caption_that_is_not_unique_is_REFUSED():
    xml = document(para(run("Table A4: twice")) + para(run("Table A4: twice"))
                   + table(row("a", "b")))
    with pytest.raises(AnchorError, match="matched 2 paragraphs"):
        house(xml, read_all(xml)[0], caption="Table A4:")


def test_running_it_twice_changes_nothing_the_second_time():
    xml = _doc()
    once, _ = house(xml, read_all(xml)[0], caption="Table A4:")
    twice, report = house(once, read_all(once)[0], caption="Table A4:")
    assert twice == once
    assert (report.runs, report.paragraphs, report.rows) == (0, 0, 0)
    assert not report.width and not report.caption


def test_the_font_and_size_are_the_papers_to_choose():
    xml = _doc()
    out, _ = house(xml, read_all(xml)[0], font="Calibri", size=9)
    assert 'w:ascii="Calibri"' in out
    assert '<w:sz w:val="18"/>' in out


def test_house_composes_with_booktabs():
    """One sets the face and the width, the other the rules; neither
    touches the other's settings. Re-read the table between them."""
    from docxkit.tables import booktabs

    xml = _doc()
    styled, _ = house(xml, read_all(xml)[0])
    ruled, _ = booktabs(styled, read_all(styled)[0])

    assert 'w:ascii="Arial Narrow"' in ruled
    assert "<w:cantSplit/>" in ruled
    assert "<w:tblBorders" in ruled or "<w:tcBorders" in ruled


def test_a_tracked_table_is_refused():
    xml = _doc().replace(
        "<w:tc>", '<w:tc><w:p><w:ins w:id="9" w:author="A" '
        'w:date="2026-01-01T00:00:00Z"><w:r><w:t>new</w:t></w:r>'
        "</w:ins></w:p>", 1)
    with pytest.raises(AnchorError, match="tracked changes"):
        house(xml, read_all(xml)[0])


def test_house_rpr_names_the_face_on_all_four_attributes():
    """A cell holding a non-Latin character falls back to a different
    face for exactly that character otherwise — a stray glyph in one
    cell of an otherwise uniform table."""
    rpr = house_rpr("Arial Narrow", 10)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        assert f'{attr}="Arial Narrow"' in rpr
    assert '<w:szCs w:val="20"/>' in rpr


def test_by_caption_finds_the_table_this_styles():
    xml = _doc()
    _, report = house(xml, by_caption(xml, "Table A4:"))
    assert report.runs
