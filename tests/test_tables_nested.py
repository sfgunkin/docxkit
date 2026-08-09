"""A nested table is not this table — for the parts that are not rows.

``_table_core`` learned this first, and says so on ``rows_of``: a nested
table's rows are not its rows. The table's GRID and its PROPERTIES were
exempt, because they are found by searching rather than by walking, and
every one of those searches ran over the whole ``w:tbl`` — nested tables
included.

Questionnaires nest tables freely and these papers are full of them, so
the shapes below are ordinary rather than pathological: an outer table
that does not state a property while an inner one does, which is exactly
when a search for that property finds the wrong table's.
"""
from __future__ import annotations

import re

import pytest
from conftest import NS

from docxkit import tables
from docxkit._table_layout import (
    _AFTER_TBLLAYOUT,
    _TBLLAYOUT_RE,
    _own_grid,
    _own_tblpr,
    _set_tbl_pr,
    _side_margins,
)
from docxkit.errors import AnchorError
from docxkit.tables import fit_columns, read_all

FONT = "Arial Narrow"


def run(text: str) -> str:
    return (f'<w:r><w:rPr><w:rFonts w:ascii="{FONT}"/><w:sz w:val="20"/>'
            f"</w:rPr><w:t>{text}</w:t></w:r>")


def cell(content: str, *, w: int = 1000) -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
            f"<w:p>{content}</w:p></w:tc>")


def inner_table(*, pr: str) -> str:
    """A table nested inside a cell of the outer one."""
    return (
        '<w:tr><w:tc><w:tcPr><w:tcW w:w="1000" w:type="dxa"/></w:tcPr>'
        f"<w:tbl>{pr}"
        '<w:tblGrid><w:gridCol w:w="300"/><w:gridCol w:w="600"/></w:tblGrid>'
        "<w:tr>" + cell(run("in1"), w=300) + cell(run("in2"), w=600)
        + "</w:tr></w:tbl>"
        "<w:p>" + run("outer cell") + "</w:p></w:tc></w:tr>")


def doc(outer_pr: str, inner_pr: str) -> str:
    return (
        f"<w:document {NS}><w:body><w:tbl>{outer_pr}"
        '<w:tblGrid><w:gridCol w:w="1000"/><w:gridCol w:w="1000"/></w:tblGrid>'
        "<w:tr>" + cell(run("Label")) + cell(run("-0.250***")) + "</w:tr>"
        + inner_table(pr=inner_pr)
        + "</w:tbl></w:body></w:document>")


OUTER_W = '<w:tblPr><w:tblW w:w="2000" w:type="dxa"/></w:tblPr>'
INNER_FULL = ('<w:tblPr><w:tblW w:w="900" w:type="dxa"/>'
              '<w:tblLayout w:type="autofit"/>'
              '<w:tblCellMar><w:left w:w="55" w:type="dxa"/>'
              '<w:right w:w="55" w:type="dxa"/></w:tblCellMar></w:tblPr>')


def grids(xml: str) -> list[str]:
    return re.findall(r"<w:tblGrid>.*?</w:tblGrid>", xml, re.DOTALL)


def test_the_grid_read_counts_only_this_tables_columns():
    """A two-column table stayed two columns.

    The scan for `w:gridCol` ran over the whole `w:tbl`, so a nested
    table's columns were read as this one's: the outer table was
    rewritten with a FOUR-column grid whose widths summed to a total no
    row had cells for. Word does not lay that out, it repairs it.
    """
    xml = doc(OUTER_W, INNER_FULL)
    table = read_all(xml)[0]
    out, report = fit_columns(xml, table)

    assert len(report.columns) == 2
    assert grids(out)[0].count("<w:gridCol") == 2
    # the nested table's own grid is untouched
    assert grids(out)[1] == ('<w:tblGrid><w:gridCol w:w="300"/>'
                             '<w:gridCol w:w="600"/></w:tblGrid>')


def test_the_fixed_layout_lands_on_this_table_not_the_nested_one():
    """The outer table states no tblLayout; the inner one does.

    `if "<w:tblLayout" in body` was true because of the INNER table, so
    the `count=1` substitution switched the nested table to fixed and
    left the outer one autofit — the one table whose division Word was
    being asked to honor.
    """
    xml = doc(OUTER_W, INNER_FULL)
    out, _ = fit_columns(xml, read_all(xml)[0])

    outer = _own_tblpr(out[out.index("<w:tbl>"):])
    assert outer is not None
    assert '<w:tblLayout w:type="fixed"/>' in outer[2]
    # and the nested table keeps the layout it declared
    assert '<w:tblLayout w:type="autofit"/>' in out


def test_the_margins_land_on_this_table_not_the_nested_one():
    xml = doc(OUTER_W, INNER_FULL)
    out, _ = fit_columns(xml, read_all(xml)[0], margin=60)

    outer = _own_tblpr(out[out.index("<w:tbl>"):])
    assert outer is not None
    assert 'w:w="60"' in outer[2]
    assert 'w:w="55"' in out          # the nested table's, still stated


def test_side_margins_are_read_from_this_tables_properties():
    """Measuring, not writing — and wrong in the same way.

    An outer table that states no margins was measured with the nested
    table's 55+55, so every column was fitted around a padding figure
    belonging to a different table. Absent margins mean Word's default.
    """
    xml = doc(OUTER_W, INNER_FULL)
    body = xml[xml.index("<w:tbl>"):xml.index("</w:body>")]
    assert _side_margins(body) == 216           # 108 + 108, Word's default


def test_a_table_with_no_width_of_its_own_is_given_one():
    """`tblW` was substituted, so an absent one was never written.

    The docstring promised a fixed-layout dxa table "throughout (grid,
    tblW, every tcW)" and delivered two of the three, because `re.sub`
    with nothing to match is a silent no-op. With a nested table in
    reach it was worse than a no-op: the inner table's width was the one
    that got rewritten.
    """
    xml = doc("", INNER_FULL)                   # outer states no tblPr at all
    out, report = fit_columns(xml, read_all(xml)[0])

    outer = _own_tblpr(out[out.index("<w:tbl>"):])
    assert outer is not None
    assert f'<w:tblW w:w="{report.total}" w:type="dxa"/>' in outer[2]
    assert '<w:tblW w:w="900" w:type="dxa"/>' in out    # nested, untouched


def test_a_created_tblpr_sorts_its_properties_the_way_the_schema_does():
    """CT_TblPr is a sequence; Word repairs a document that ignores it."""
    xml = doc('<w:tblPr><w:tblLook w:val="04A0"/></w:tblPr>', INNER_FULL)
    out, _ = fit_columns(xml, read_all(xml)[0], margin=60)

    own = _own_tblpr(out[out.index("<w:tbl>"):])
    assert own is not None
    order = [own[2].index(t) for t in
             ("<w:tblW", "<w:tblLayout", "<w:tblCellMar", "<w:tblLook")]
    assert order == sorted(order)


def test_a_tracked_property_change_is_not_where_the_width_is_written():
    """`w:tblPrChange` holds what a tracked change REPLACED.

    Writing there edits the historical record and leaves the page as it
    was — the lesson `live_properties` exists for, applied to a table's
    own properties rather than a run's.

    Exercised on the helper rather than through `fit_columns`, which
    refuses a table carrying revisions of any kind before it gets this
    far. That refusal is the real defence; this is the second one, and
    the one that has to hold if a caller ever reaches the helper by
    another road.
    """
    pr = ('<w:tblPr><w:tblW w:w="2000" w:type="dxa"/>'
          '<w:tblPrChange w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
          '<w:tblPr><w:tblW w:w="1234" w:type="dxa"/>'
          '<w:tblLayout w:type="autofit"/></w:tblPr>'
          "</w:tblPrChange></w:tblPr>")
    body = (f"<w:tbl>{pr}<w:tblGrid><w:gridCol w:w="
            '"1000"/></w:tblGrid><w:tr>' + cell(run("Label"))
            + "</w:tr></w:tbl>")

    out = _set_tbl_pr(body, _TBLLAYOUT_RE, '<w:tblLayout w:type="fixed"/>',
                      _AFTER_TBLLAYOUT)
    own = _own_tblpr(out)
    assert own is not None
    live, _, past = own[2].partition("<w:tblPrChange")
    assert '<w:tblLayout w:type="fixed"/>' in live
    # the snapshot still says what it always said
    assert '<w:tblW w:w="1234" w:type="dxa"/>' in past
    assert '<w:tblLayout w:type="autofit"/>' in past


def test_own_grid_and_own_tblpr_agree_about_which_table_this_is():
    xml = doc(OUTER_W, INNER_FULL)
    body = xml[xml.index("<w:tbl>"):xml.index("</w:body>")]
    grid, pr = _own_grid(body), _own_tblpr(body)
    assert grid is not None and pr is not None
    # properties come before the grid, and the grid before any row
    assert pr[1] <= grid.start() < body.index("<w:tr>")


def test_a_table_that_is_only_a_nested_table_still_fits_its_own_grid():
    """The outer table's grid is the first one even when its only cell
    holds another table — which is the shape that made the plain search
    look correct in the first place."""
    xml = doc(OUTER_W, INNER_FULL)
    _, report = fit_columns(xml, read_all(xml)[0])
    assert sum(c.new for c in report.columns) == report.total


@pytest.mark.parametrize("total", [0, -1])
def test_a_non_positive_total_is_refused(total):
    xml = doc(OUTER_W, INNER_FULL)
    with pytest.raises(AnchorError, match="must be positive"):
        fit_columns(xml, read_all(xml)[0], total=total)


def test_spacer_columns_that_eat_the_table_are_refused_not_negated():
    """`avail` went negative and every filled column was written as a
    negative `w:w`. That is not a narrow table: ST_TwipsMeasure is
    unsigned, so it is invalid OOXML and Word repairs the file."""
    xml = (f"<w:document {NS}><w:body>"
           '<w:tbl><w:tblPr><w:tblW w:w="5200" w:type="dxa"/></w:tblPr>'
           '<w:tblGrid><w:gridCol w:w="100"/><w:gridCol w:w="5000"/>'
           '<w:gridCol w:w="100"/></w:tblGrid><w:tr>'
           + cell(run("A"), w=100) + cell("", w=5000) + cell(run("B"), w=100)
           + "</w:tr></w:tbl></w:body></w:document>")
    with pytest.raises(AnchorError, match="spacer columns"):
        fit_columns(xml, read_all(xml)[0], total=1000)


def test_the_fit_of_a_plain_table_is_unchanged_by_all_of_this():
    """No nested table, nothing unusual: the ordinary path still runs."""
    xml = (f"<w:document {NS}><w:body>"
           '<w:tbl><w:tblPr><w:tblW w:w="3600" w:type="dxa"/>'
           '<w:tblLayout w:type="fixed"/></w:tblPr>'
           '<w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="800"/>'
           '<w:gridCol w:w="800"/></w:tblGrid><w:tr>'
           + cell(run("Label here"), w=2000) + cell(run("-0.250***"), w=800)
           + cell(run("0.047"), w=800)
           + "</w:tr></w:tbl></w:body></w:document>")
    out, report = fit_columns(xml, read_all(xml)[0])
    assert sum(c.new for c in report.columns) == 3600
    assert not report.cramped
    # the coefficient column, which carries a sign and three stars, ends
    # up wider than the bare standard error beside it
    assert report.columns[1].new > report.columns[2].new
    assert tables.read_all(out)[0].rows == [["Label here", "-0.250***",
                                             "0.047"]]
