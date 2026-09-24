"""`equations.numbered_grid` and `number_displays` — a number in a cell.

A number left as a run beside the maths makes Word demote the display to
inline on its next save (HCW's (3)-(7)); a two-column grid centres the
equation an eighth of an inch left of the page's centre. Three columns,
the number in the last.
"""
from __future__ import annotations

import re

import pytest
from conftest import make_parts, para, run

from docxkit import equations
from docxkit._xml import DOCUMENT, element_spans, visible_text
from docxkit.lint import lint_parts

M = "<m:oMath><m:r><m:t>y=a+bx</m:t></m:r></m:oMath>"
PORTRAIT = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:right="1440" w:left="1440" w:top="1440" '
            'w:bottom="1440"/></w:sectPr>')
LANDSCAPE = ('<w:p><w:pPr><w:sectPr><w:pgSz w:h="12240" w:w="15840" '
             'w:orient="landscape"/><w:pgMar w:left="1080" w:top="1440" '
             'w:right="1080" w:bottom="1440"/></w:sectPr></w:pPr></w:p>')


def eq(tail: str) -> str:
    return para(M, run(tail, preserve=True))


def widths(xml: str) -> list[int]:
    return [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"/>', xml)]


def test_the_grid_is_SPACER_equation_NUMBER_and_fills_the_column():
    got = equations.numbered_grid("<w:p/>", "(3)", 9360)

    assert widths(got) == [625, 8110, 625]
    cells = element_spans(got, "tc")
    assert len(cells) == 3
    assert visible_text(got[cells[2][0]:cells[2][1]]) == "(3)"
    assert got.count('w:val="nil"') == 6, "a grid that draws nothing"


def test_a_column_too_narrow_for_two_number_cells_is_refused():
    with pytest.raises(ValueError, match="no room"):
        equations.numbered_grid("<w:p/>", "(1)", 1250)


def test_the_number_leaves_the_paragraph_and_the_COMMA_stays_with_the_maths():
    xml = make_parts(eq(", (3)") + PORTRAIT)[DOCUMENT].decode()

    out, n = equations.number_displays(xml)

    assert n == 1
    cells = element_spans(out, "tc")
    middle = out[cells[1][0]:cells[1][1]]
    assert "<m:oMathPara" in middle
    assert visible_text(middle).endswith(",")
    assert "(3)" not in visible_text(middle)
    assert visible_text(out[cells[2][0]:cells[2][1]]) == "(3)"


def test_the_width_is_the_SECTIONS_holding_the_equation():
    """A sectPr ends its section: an equation before the landscape break
    is landscape, one after it is in the body's portrait section."""
    xml = make_parts(eq(" (1)") + LANDSCAPE + eq(" (2)")
                     + PORTRAIT)[DOCUMENT].decode()

    out, n = equations.number_displays(xml)

    assert n == 2
    first, second = re.findall(r"<w:tblGrid>.*?</w:tblGrid>", out)
    assert widths(first) == [625, 15840 - 2160 - 1250, 625]
    assert widths(second) == [625, 12240 - 2880 - 1250, 625]


def test_numbering_TWICE_moves_nothing_the_second_time():
    xml = make_parts(eq(" (A.2)") + PORTRAIT)[DOCUMENT].decode()
    once, n1 = equations.number_displays(xml)

    twice, n2 = equations.number_displays(once)

    assert (n1, n2) == (1, 0) and twice == once


def test_an_UNNUMBERED_display_and_a_notation_table_are_left_alone():
    notation = ("<w:tbl><w:tr><w:tc>" + para(M) + "</w:tc><w:tc>"
                + para(run("the outcome")) + "</w:tc></w:tr></w:tbl>")
    xml = make_parts(para(M) + notation + PORTRAIT)[DOCUMENT].decode()

    out, n = equations.number_displays(xml)

    assert (out, n) == (xml, 0)


def test_a_two_column_GRID_is_rebuilt_as_three():
    old = ("<w:tbl><w:tr><w:tc>" + para(M) + "</w:tc><w:tc>"
           + para(run("(4)")) + "</w:tc></w:tr></w:tbl>")
    xml = make_parts(old + PORTRAIT)[DOCUMENT].decode()

    out, n = equations.number_displays(xml)

    assert n == 1 and len(element_spans(out, "tc")) == 3


def test_a_grid_holding_a_BOOKMARK_is_not_rebuilt():
    old = ("<w:tbl><w:tr><w:tc>" + para(M) + "</w:tc><w:tc>"
           + para('<w:bookmarkStart w:id="1" w:name="Eq4"/>', run("(4)"),
                  '<w:bookmarkEnd w:id="1"/>')
           + "</w:tc></w:tr></w:tbl>")
    xml = make_parts(old + PORTRAIT)[DOCUMENT].decode()

    out, n = equations.number_displays(xml)

    assert (out, n) == (xml, 0)


def test_the_result_LINTS_clean():
    parts = make_parts(para(run("Prose.")) + eq(", (3)") + PORTRAIT)
    xml, _n = equations.number_displays(parts[DOCUMENT].decode())
    parts[DOCUMENT] = xml.encode()

    assert lint_parts(parts) == []
