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


# --- what the _table_layout run of 2026-08-18 found ----------------------
#
# 12 survivors in `_house_width`, every one on the arithmetic that
# splices the width into the properties — and the tests above assert
# that the two elements are somewhere `in out`, which is true wherever
# they land. Asking WHERE found an S2: `<w:tblW>` was going in FIRST,
# ahead of the `<w:tblStyle>` that CT_TblPr requires before it.


def _styled_doc() -> str:
    """A table built the way `body.table` builds one — with a tblStyle,
    which is what makes the order visible."""
    from docxkit.body import table as body_table
    return document(para(run("Table A4: Data sources"))
                    + body_table(["Country", "Source"], [["KZ", "UNFPA"]]))


def test_the_width_goes_in_its_SCHEMA_SLOT_not_at_the_front():
    """CT_TblPr is a sequence: tblStyle, then tblW, then tblLayout, then
    tblLook. Word repairs a table whose properties are out of order — it
    drops the misplaced ones on the next save, so the width silently
    stops applying some weeks later with nothing in any diff. The same
    failure `table_spacing` records for CT_PPr, and the same shape.

    `fit_columns` has done this correctly through `_set_tbl_pr` all
    along; this path spliced at `props.index(">") + 1` instead."""
    xml = _styled_doc()

    out, report = house(xml, read_all(xml)[0])

    assert report.width
    props = out[out.index("<w:tblPr>"):out.index("</w:tblPr>")]
    order = [props.index(t) for t in ("<w:tblStyle", "<w:tblW",
                                      "<w:tblLayout", "<w:tblLook")]
    assert order == sorted(order), props


def test_the_width_REPLACES_one_already_there_in_its_own_slot():
    """`body.table`'s default already carries a tblW — in the right
    place. Replacing it must not move it to the front either."""
    xml = _styled_doc()
    assert '<w:tblW w:w="5000" w:type="pct"/>' in xml

    out, _ = house(xml, read_all(xml)[0])

    props = out[out.index("<w:tblPr>"):out.index("</w:tblPr>")]
    assert props.count("<w:tblW") == 1
    assert props.count("<w:tblLayout") == 1
    assert props.index("<w:tblStyle") < props.index("<w:tblW")


def test_a_table_with_NO_properties_still_gets_them_first():
    """`w:tblPr` is CT_Tbl's first child, and a hand-built fragment has
    none at all — the other half of the same function."""
    xml = _doc()                      # conftest's bare <w:tbl>

    out, report = house(xml, read_all(xml)[0])

    assert report.width
    at = out.index("<w:tbl>")
    assert out[at:].startswith("<w:tbl><w:tblPr>")
    assert '<w:tblW w:w="5000" w:type="pct"/>' in out
    assert '<w:tblLayout w:type="autofit"/>' in out


def test_the_width_is_written_into_the_OUTER_table_not_a_nested_one():
    """`_set_tbl_pr`'s own warning, which this path did not have: a
    `re.sub` over the body writes into whichever tblPr comes first, and
    a nested table's is first whenever the outer table has none."""
    inner = ('<w:tbl><w:tblPr><w:tblStyle w:val="Inner"/></w:tblPr>'
             + row("x", "y") + "</w:tbl>")
    xml = document(para(run("Table A4: Data sources"))
                   + ("<w:tbl>" + "<w:tr><w:tc>" + inner + "</w:tc></w:tr>"
                      + "</w:tbl>"))

    out, _ = house(xml, read_all(xml)[0])

    start = out.index("<w:tbl>")
    outer = out[start:out.index("<w:tbl>", start + 1)]
    assert '<w:tblW w:w="5000" w:type="pct"/>' in outer, \
        "the outer table is the one that was asked for"
    assert 'w:val="Inner"' in out, "and the nested one keeps its own"


# The other half of the same cluster: 10 survivors in `_keep_with_table`,
# every one on the branch for a caption paragraph that ALREADY has a
# `w:pPr`. Every caption in a real manuscript has one — a Caption style,
# a justification, or both — and `_doc()` above builds one that has
# none, so the branch had never run.


def _captioned(ppr: str, text: str = "Table A4: Data sources") -> str:
    return document(f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"
                    + table(row("Country", "Source"),
                            row("Kazakhstan", "UNFPA")))


def _parses(xml: str) -> None:
    from lxml import etree
    etree.fromstring(xml.encode("utf-8"))


def test_keepNext_goes_after_the_pStyle_and_INSIDE_the_pPr():
    """S1: `existing[0] + existing[2].index(">") + 1` adds an offset
    INTO the properties' content to the offset OF the properties
    element, which are different coordinate systems. On a caption styled
    `Caption` it spliced the tag into the middle of an attribute —
    `w:val="Cap<w:keepNext/>tion"` — and reported success. The document
    does not open.

    CT_PPr also fixes where it belongs once it is inside: pStyle first,
    keepNext straight after it."""
    xml = _captioned('<w:pPr><w:pStyle w:val="Caption"/></w:pPr>')

    out, report = house(xml, read_all(xml)[0], caption="Table A4:")

    assert report.caption
    _parses(out)
    assert '<w:pStyle w:val="Caption"/><w:keepNext/>' in out
    assert 'w:val="Caption"' in out, "the style survived intact"


def test_keepNext_goes_FIRST_when_there_is_no_pStyle():
    """Nothing in CT_PPr may precede keepNext except pStyle, so a
    paragraph that only carries a justification takes it at the front."""
    xml = _captioned('<w:pPr><w:jc w:val="center"/></w:pPr>')

    out, _ = house(xml, read_all(xml)[0], caption="Table A4:")

    _parses(out)
    assert '<w:pPr><w:keepNext/><w:jc w:val="center"/></w:pPr>' in out


def test_an_EMPTY_pPr_is_expanded_rather_than_written_past():
    """`<w:pPr/>` is real Word output, and its span covers a
    self-closing tag: inserting after it puts `keepNext` outside the
    properties, where it is a paragraph child the schema has no slot
    for."""
    xml = _captioned("<w:pPr/>")

    out, _ = house(xml, read_all(xml)[0], caption="Table A4:")

    _parses(out)
    assert "<w:pPr><w:keepNext/></w:pPr>" in out


def test_keepNext_is_not_added_TWICE_to_a_styled_caption():
    """The idempotence the file already asserts, on the branch that had
    never run."""
    xml = _captioned('<w:pPr><w:pStyle w:val="Caption"/></w:pPr>')

    once, _ = house(xml, read_all(xml)[0], caption="Table A4:")
    twice, report = house(once, read_all(once)[0], caption="Table A4:")

    assert twice == once
    assert not report.caption
    assert once.count("<w:keepNext/>") == 1


# --- what a review of the fix above found (2026-08-18) -------------------
#
# Three more shapes on the same branch, each reported as success:


def test_keepNext_is_read_from_the_LIVE_properties_not_the_history():
    """`w:pPrChange` carries the formatting a tracked change REPLACED,
    and a caption whose history had keepNext was reported as already
    done while its live properties never got it. The caption then splits
    from its table at the page break, and `house` said it was fine."""
    xml = _captioned('<w:pPr><w:pStyle w:val="Caption"/>'
                     '<w:pPrChange w:id="1" w:author="a"><w:pPr>'
                     "<w:keepNext/></w:pPr></w:pPrChange></w:pPr>")

    out, report = house(xml, read_all(xml)[0], caption="Table A4:")

    assert report.caption
    _parses(out)
    assert '<w:pStyle w:val="Caption"/><w:keepNext/><w:pPrChange' in out
    assert out.count("<w:keepNext/>") == 2, "the snapshot keeps its own"


def test_a_pStyle_written_with_a_CLOSING_tag_still_comes_first():
    """`<w:pStyle .../>` and `<w:pStyle ...></w:pStyle>` are the same
    element; matching only the first put keepNext ahead of the style,
    which is the out-of-order property Word drops on the next save."""
    xml = _captioned('<w:pPr><w:pStyle w:val="Caption"></w:pStyle></w:pPr>')

    out, _ = house(xml, read_all(xml)[0], caption="Table A4:")

    _parses(out)
    assert ('<w:pStyle w:val="Caption"></w:pStyle><w:keepNext/>' in out)


def test_a_keepNext_declared_OFF_is_rewritten_not_doubled():
    """ST_OnOff again: `w:val="0"` is a keepNext that says no. CT_PPr
    allows one, so adding a second leaves Word to choose between them on
    open — and it may choose the one that says no."""
    xml = _captioned('<w:pPr><w:pStyle w:val="Caption"/>'
                     '<w:keepNext w:val="0"/></w:pPr>')

    out, report = house(xml, read_all(xml)[0], caption="Table A4:")

    assert report.caption
    _parses(out)
    assert out.count("<w:keepNext") == 1
    assert 'w:val="0"' not in out


def test_a_keepNext_already_ON_is_left_alone():
    xml = _captioned('<w:pPr><w:pStyle w:val="Caption"/><w:keepNext/></w:pPr>')

    out, report = house(xml, read_all(xml)[0], caption="Table A4:")

    assert not report.caption
    assert out.count("<w:keepNext/>") == 1


def test_the_width_reaches_an_outer_table_that_has_NO_GRID_of_its_own():
    """The nested-table guard, in the case the fixture above missed: the
    outer table has no `w:tblGrid`, so the first one in the body is the
    INNER table's. `house` wrote the outer table's width into the inner
    table's properties and reported success."""
    inner = ('<w:tbl><w:tblPr><w:tblStyle w:val="Inner"/>'
             '<w:tblW w:w="1234" w:type="dxa"/></w:tblPr>'
             '<w:tblGrid><w:gridCol w:w="800"/></w:tblGrid>'
             + row("x") + "</w:tbl>")
    xml = document(para(run("Table A4: Data sources"))
                   + "<w:tbl><w:tr><w:tc>" + inner + "</w:tc></w:tr></w:tbl>")

    out, report = house(xml, read_all(xml)[0])

    assert report.width
    start = out.index("<w:tbl>")
    outer = out[start:out.index("<w:tbl>", start + 1)]
    assert '<w:tblW w:w="5000" w:type="pct"/>' in outer
    assert 'w:w="1234"' in out, "the nested table keeps its own width"
