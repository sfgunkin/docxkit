"""fit_columns — content-aware column widths for results tables.

The scenario throughout is the one that motivated the feature: a
regression table whose equal-width data columns hide unequal content —
coefficient cells carry a sign and significance stars, standard-error
cells are bare numbers — so the coefficient cells wrap and double their
rows' height.
"""
from __future__ import annotations

import re

import pytest
from conftest import NS

from docxkit.errors import AnchorError
from docxkit.tables import fit_columns, read_all

FONT = "Arial Narrow"


def frun(text: str, *, sz: int = 20, bold: bool = False,
         va: str | None = None) -> str:
    rpr = (f'<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/>'
           + ("<w:b/>" if bold else "")
           + (f'<w:vertAlign w:val="{va}"/>' if va else "")
           + f'<w:sz w:val="{sz}"/></w:rPr>')
    return f"<w:r>{rpr}<w:t>{text}</w:t></w:r>"


def cell(content: str, *, w: int = 1000, span: int | None = None) -> str:
    tcpr = (f'<w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>'
            + (f'<w:gridSpan w:val="{span}"/>' if span else "")
            + "</w:tcPr>")
    return f'<w:tc>{tcpr}<w:p w14:paraId="AA">{content}</w:p></w:tc>'


def tbl(grid: list[int], *rows: str, layout: str | None = "fixed",
        tblw: tuple[int, str] | None = None) -> str:
    if tblw is None:
        tblw = (sum(grid), "dxa")
    pr = (f'<w:tblPr><w:tblW w:w="{tblw[0]}" w:type="{tblw[1]}"/>'
          + (f'<w:tblLayout w:type="{layout}"/>' if layout else "")
          + '<w:tblLook w:val="04A0"/></w:tblPr>')
    g = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid) \
        + "</w:tblGrid>"
    return f"<w:tbl>{pr}{g}{''.join(rows)}</w:tbl>"


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def regression_doc() -> str:
    """Label + coefficient + SE columns, equal data widths (832 dxa)."""
    return doc(tbl(
        [2700, 832, 832],
        "<w:tr>" + cell(frun(""), w=2700)
        + cell(frun("Coeff."), w=832) + cell(frun("Std.Err"), w=832)
        + "</w:tr>",
        "<w:tr>" + cell(frun("Professional/vocational education"), w=2700)
        + cell(frun("-0.250***"), w=832) + cell(frun("0.047"), w=832)
        + "</w:tr>",
    ))


def grid_of(xml: str) -> list[int]:
    return [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"/>', xml)]


def test_coefficient_column_outgrows_the_se_column():
    out, rep = fit_columns(regression_doc(), read_all(regression_doc())[0])
    label, coef, se = grid_of(out)
    assert coef > se, (coef, se)
    assert se < 832 < coef            # the SE column funds the widening
    assert label + coef + se == 2700 + 832 + 832
    assert rep.columns[1].driver == "-0.250***"
    assert not rep.cramped


def test_total_width_and_tcw_stay_consistent():
    out, _ = fit_columns(regression_doc(), read_all(regression_doc())[0])
    widths = grid_of(out)
    assert f'<w:tblW w:w="{sum(widths)}" w:type="dxa"/>' in out
    for tr in re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL):
        tcw = [int(w) for w in re.findall(r'<w:tcW w:w="(\d+)"', tr)]
        assert tcw == widths


def test_fitting_twice_is_a_fixed_point():
    once, _ = fit_columns(regression_doc(), read_all(regression_doc())[0])
    twice, rep = fit_columns(once, read_all(once)[0])
    assert grid_of(twice) == grid_of(once)
    assert all(c.old == c.new for c in rep.columns)


def test_superscript_stars_cost_less_than_inline_stars():
    def variant(stars: str) -> int:
        d = doc(tbl(
            [2000, 1000, 1000],
            "<w:tr>" + cell(frun("Label word here"), w=2000)
            + cell(frun("-0.250") + stars, w=1000)
            + cell(frun("0.047"), w=1000) + "</w:tr>"))
        out, _ = fit_columns(d, read_all(d)[0])
        return grid_of(out)[1]
    assert variant(frun("***", va="superscript")) < variant(frun("***"))


def test_bold_costs_more_than_regular():
    def variant(bold: bool) -> int:
        d = doc(tbl(
            [2000, 1000, 1000],
            "<w:tr>" + cell(frun("Label word here"), w=2000)
            + cell(frun("-0.250***", bold=bold), w=1000)
            + cell(frun("0.047"), w=1000) + "</w:tr>"))
        out, _ = fit_columns(d, read_all(d)[0])
        return grid_of(out)[1]
    assert variant(True) > variant(False)


def test_span_header_grows_its_columns_when_they_are_too_narrow():
    d = doc(tbl(
        [2000, 400, 400],
        "<w:tr>" + cell(frun("Heading"), w=2000)
        + cell(frun("Unbreakable-Header-Token"), w=800, span=2) + "</w:tr>",
        "<w:tr>" + cell(frun("A label with words"), w=2000)
        + cell(frun("1.0"), w=400) + cell(frun("2.0"), w=400) + "</w:tr>"))
    out, _ = fit_columns(d, read_all(d)[0])
    _, c1, c2 = grid_of(out)
    assert c1 + c2 > 800              # the span forced them wider
    assert sum(grid_of(out)) == 2800


def test_empty_spacer_column_keeps_its_width():
    d = doc(tbl(
        [2000, 1000, 146, 1000],
        "<w:tr>" + cell(frun("A label with words"), w=2000)
        + cell(frun("-0.250***"), w=1000) + cell(frun(""), w=146)
        + cell(frun("0.047"), w=1000) + "</w:tr>"))
    out, rep = fit_columns(d, read_all(d)[0])
    assert grid_of(out)[2] == 146
    assert rep.columns[2].driver == ""
    assert sum(grid_of(out)) == 4146


def test_shortfall_is_taken_from_the_wrappable_label_column():
    # a narrow table: numeric needs are non-negotiable, the label wraps
    d = doc(tbl(
        [1400, 700, 700],
        "<w:tr>" + cell(frun("Professional and vocational education "
                             "of the household head"), w=1400)
        + cell(frun("-0.250***"), w=700) + cell(frun("0.047"), w=700)
        + "</w:tr>"))
    out, rep = fit_columns(d, read_all(d)[0])
    label, coef, se = grid_of(out)
    assert label + coef + se == 2800
    assert label < 1400               # the label column paid for the fit
    assert coef > se
    assert not rep.cramped


def test_cramped_when_even_hard_minima_do_not_fit():
    d = doc(tbl(
        [400, 400],
        "<w:tr>" + cell(frun("Wide-unbreakable-content-here"), w=400)
        + cell(frun("-0.999*** wide"), w=400) + "</w:tr>"))
    out, rep = fit_columns(d, read_all(d)[0])
    assert rep.cramped
    assert sum(grid_of(out)) == 800   # still sums to the table width


def test_pct_table_needs_an_explicit_total():
    d = doc(tbl([2000, 1000, 1000],
                "<w:tr>" + cell(frun("A label with words"), w=2000)
                + cell(frun("-0.250***"), w=1000)
                + cell(frun("0.047"), w=1000) + "</w:tr>",
                layout=None, tblw=(4959, "pct")))
    out, rep = fit_columns(d, read_all(d)[0], total=9360)
    assert rep.total == 9360
    assert sum(grid_of(out)) == 9360
    assert '<w:tblW w:w="9360" w:type="dxa"/>' in out
    assert '<w:tblLayout w:type="fixed"/>' in out
    assert "pct" not in out


def test_refuses_a_tracked_table():
    d = regression_doc().replace(
        "</w:tr>",
        '</w:tr><w:tr><w:tc><w:tcPr><w:tcW w:w="832" w:type="dxa"/>'
        '</w:tcPr><w:p><w:ins w:id="9" w:author="A" '
        'w:date="2026-01-01T00:00:00Z"><w:r><w:t>x</w:t></w:r></w:ins>'
        "</w:p></w:tc></w:tr>", 1)
    with pytest.raises(AnchorError, match="tracked"):
        fit_columns(d, read_all(d)[0])


def test_result_still_parses_as_xml():
    from lxml import etree
    out, _ = fit_columns(regression_doc(), read_all(regression_doc())[0])
    etree.fromstring(out.encode("utf-8"))
