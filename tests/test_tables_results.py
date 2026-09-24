"""A RESULTS cell: number, superscript stars, and a standard error below.

BACKLOG S2 (Misconceptions W7, 770 cells): `set_cell` put the whole text
in the first run and blanked the rest, so the stars printed full size
and a two-line cell lost its SE line — and every cell read back exactly
as written, so nothing saw it. `set_cell` now routes stars and refuses
the second line; `set_result` writes all three.
"""
from __future__ import annotations

import re

import pytest
from conftest import document, make_parts, para

from docxkit._xml import PARA_RE, visible_text
from docxkit.errors import AnchorError
from docxkit.lint import lint_parts
from docxkit.tables import by_caption, set_cell, set_result

SUP = '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
ITALIC = "<w:rPr><w:i/></w:rPr>"


def r(text: str, rpr: str = "") -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def results(cell_xml: str) -> str:
    """A captioned results table: a header, and one row holding the cell."""
    return document(
        para(r("Table 4. Estimates"))
        + "<w:tbl><w:tr><w:tc>" + para(r("Variable")) + "</w:tc><w:tc>"
        + para(r("(1)")) + "</w:tc></w:tr><w:tr><w:tc>"
        + para(r("Age")) + "</w:tc><w:tc>" + cell_xml
        + "</w:tc></w:tr></w:tbl>")


STARRED = para(r("0.012"), r("**", SUP))
TWO_LINE = (para(r("0.012"), r("**", SUP))
            + para(r("("), r("0.004", ITALIC), r(")")))


def cell(xml: str) -> str:
    t = by_caption(xml, "Table 4.")
    cells: list[str] = re.findall(r"<w:tc>.*?</w:tc>", xml[t.start:t.end],
                                  re.DOTALL)
    return cells[-1]


def lines(xml: str) -> list[list[tuple[str, bool, bool]]]:
    """Each line of the cell: its text runs as (text, superscript, italic)."""
    return [[(visible_text(run), 'w:val="superscript"' in run, "<w:i/>" in run)
             for run in re.findall(r"<w:r>.*?</w:r>", p.group(0), re.DOTALL)
             if visible_text(run)]
            for p in PARA_RE.finditer(cell(xml))]


def test_set_cell_puts_the_STARS_in_the_superscript_run():
    xml = results(STARRED)

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.017***")

    assert lines(out) == [[("0.017", False, False), ("***", True, False)]]


def test_set_cell_writing_text_that_is_NOT_a_result_behaves_as_before():
    xml = results(STARRED)

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "n/a")

    assert lines(out) == [[("n/a", False, False)]]


def test_set_cell_REFUSES_a_two_line_cell_unless_asked_to_flatten():
    xml = results(TWO_LINE)
    table = by_caption(xml, "Table 4.")

    with pytest.raises(AnchorError, match=r"2 lines of text.*set_result"):
        set_cell(xml, table, 1, 1, "0.017***")
    flat = set_cell(xml, table, 1, 1, "x", flatten=True)
    assert visible_text(cell(flat)) == "x"


def test_set_result_writes_the_number_the_stars_and_the_SE_line():
    """The SE keeps its italic run and its parentheses keep theirs."""
    xml = results(TWO_LINE)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="***", se="0.005")

    assert lines(out) == [
        [("0.017", False, False), ("***", True, False)],
        [("(", False, False), ("0.005", False, True), (")", False, False)]]


def test_set_result_CLONES_a_star_run_when_the_cell_had_none():
    xml = results(para(r("0.012")))

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="*")

    assert lines(out) == [[("0.017", False, False), ("*", True, False)]]


def test_set_result_with_NO_stars_empties_the_star_run():
    xml = results(STARRED)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017")

    assert lines(out) == [[("0.017", False, False)]]


def test_set_result_GROWS_a_second_line_for_the_SE_when_there_is_none():
    xml = results('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                  + r("0.012") + r("**", SUP) + "</w:p>")

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.004")

    assert lines(out)[1] == [("(0.004)", False, False)]
    second = list(PARA_RE.finditer(cell(out)))[1].group(0)
    assert '<w:jc w:val="center"/>' in second, "the first line's pPr"


def test_a_second_line_is_LEFT_ALONE_without_se():
    xml = results(TWO_LINE)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.020",
                     stars="*")

    assert lines(out)[1] == lines(xml)[1]


def test_stars_that_are_not_asterisks_are_refused():
    xml = results(STARRED)

    with pytest.raises(ValueError, match="asterisks"):
        set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.1",
                   stars="+")


def test_the_written_cell_LINTS_clean():
    xml = results(TWO_LINE)
    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="***", se="0.005")
    body = out[out.index("<w:body>") + 8:out.index("</w:body>")]

    assert lint_parts(make_parts(body)) == []
