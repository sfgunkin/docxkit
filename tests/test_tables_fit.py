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
from docxkit.tables import (
    bottom_border,
    fit_columns,
    read_all,
    superscript_stars,
)

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
        [1500, 750, 750],
        "<w:tr>" + cell(frun("Professional and vocational education "
                             "of the household head"), w=1500)
        + cell(frun("-0.250***"), w=750) + cell(frun("0.047"), w=750)
        + "</w:tr>"))
    out, rep = fit_columns(d, read_all(d)[0])
    label, coef, se = grid_of(out)
    assert label + coef + se == 3000
    assert label < 1500               # the label column paid for the fit
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


# ------------------------------------------------- superscript stars -------


def test_superscript_stars_splits_and_raises_the_stars():
    d = regression_doc()
    out, n = superscript_stars(d, read_all(d)[0])
    assert n == 1
    assert read_all(out)[0].rows[1][1] == "-0.250***"   # text unchanged
    star_run = re.search(r"<w:r>(?:(?!</w:r>).)*vertAlign(?:(?!</w:r>).)*"
                         r"</w:r>", out, re.DOTALL)
    assert star_run and ">***<" in star_run.group(0)
    assert 'w:ascii="Arial Narrow"' in star_run.group(0)   # rPr cloned
    assert re.search(r'<w:szCs w:val="20"/><w:vertAlign', star_run.group(0)
                     ) or "<w:vertAlign" in star_run.group(0)


def test_superscript_stars_is_idempotent():
    d = regression_doc()
    once, n1 = superscript_stars(d, read_all(d)[0])
    twice, n2 = superscript_stars(once, read_all(once)[0])
    assert (n1, n2) == (1, 0)
    assert twice == once


def test_superscript_stars_ignores_prose_and_bare_numbers():
    d = doc(tbl(
        [3000, 1000],
        "<w:tr>" + cell(frun("*** significant at the 1% level"), w=3000)
        + cell(frun("0.047"), w=1000) + "</w:tr>"))
    out, n = superscript_stars(d, read_all(d)[0])
    assert n == 0
    assert out == d


def test_superscript_stars_then_fit_narrows_the_coefficient_column():
    d = regression_doc()
    plain, _ = fit_columns(d, read_all(d)[0])
    raised, n = superscript_stars(d, read_all(d)[0])
    raised, _ = fit_columns(raised, read_all(raised)[0])
    assert n == 1
    assert grid_of(raised)[1] < grid_of(plain)[1]
    assert grid_of(raised)[0] > grid_of(plain)[0]   # label got the width


def test_superscript_stars_result_parses():
    from lxml import etree
    out, _ = superscript_stars(regression_doc(),
                               read_all(regression_doc())[0])
    etree.fromstring(out.encode("utf-8"))


# ------------------------------------------------- closing rule ------------


def test_bottom_border_rules_off_the_last_row():
    d = regression_doc()
    out, n = bottom_border(d, read_all(d)[0])
    assert n == 3
    last_tr = re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL)[-1]
    assert last_tr.count('<w:bottom w:val="double" w:sz="4" '
                         'w:space="0" w:color="auto"/>') == 3
    first_tr = re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL)[0]
    assert "double" not in first_tr          # only the last row


def test_bottom_border_replaces_an_existing_nil_edge():
    d = regression_doc().replace(
        '<w:tcPr><w:tcW w:w="832" w:type="dxa"/></w:tcPr>',
        '<w:tcPr><w:tcW w:w="832" w:type="dxa"/><w:tcBorders>'
        '<w:top w:val="nil"/><w:bottom w:val="nil"/></w:tcBorders></w:tcPr>')
    out, _ = bottom_border(d, read_all(d)[0])
    last_tr = re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL)[-1]
    assert '<w:bottom w:val="nil"/>' not in last_tr
    assert '<w:top w:val="nil"/>' in last_tr     # other edges untouched


def test_bottom_border_is_idempotent():
    d = regression_doc()
    once, n1 = bottom_border(d, read_all(d)[0])
    twice, n2 = bottom_border(once, read_all(once)[0])
    assert (n1, n2) == (3, 0)
    assert twice == once


def test_bottom_border_result_parses():
    from lxml import etree
    out, _ = bottom_border(regression_doc(), read_all(regression_doc())[0])
    etree.fromstring(out.encode("utf-8"))


# ------------------------------------------------- margins -----------------


def test_margin_shrinks_the_padding_and_is_written_to_the_table():
    d = doc(tbl(
        [1000, 700, 700],
        "<w:tr>" + cell(frun("Some label here"), w=1000)
        + cell(frun("-0.250***"), w=700) + cell(frun("0.047"), w=700)
        + "</w:tr>"))
    wide, _ = fit_columns(d, read_all(d)[0])
    tight, _rep = fit_columns(d, read_all(d)[0], margin=30)
    assert ('<w:tblCellMar><w:left w:w="30" w:type="dxa"/>'
            '<w:right w:w="30" w:type="dxa"/></w:tblCellMar>') in tight
    # 156 dxa less padding per column frees width for the label
    assert grid_of(tight)[0] > grid_of(wide)[0]


def test_margin_can_rescue_a_cramped_table():
    d = doc(tbl(
        [700, 600, 600, 600, 600],
        "<w:tr>" + cell(frun("Labels wrap fine"), w=700)
        + "".join(cell(frun("14.000"), w=600) for _ in range(4))
        + "</w:tr>"))
    _, default_rep = fit_columns(d, read_all(d)[0])
    _, tight_rep = fit_columns(d, read_all(d)[0], margin=20)
    assert default_rep.cramped and not tight_rep.cramped


# ------------------------------------------------- page break --------------


def test_page_break_before_inserts_and_is_idempotent():
    from docxkit.find import page_break_before
    d = doc("<w:p><w:pPr><w:pStyle w:val=\"Caption\"/></w:pPr>"
            "<w:r><w:t>Table 3: Results</w:t></w:r></w:p>")
    once = page_break_before(d, "Table 3:")
    assert ('<w:pStyle w:val="Caption"/><w:pageBreakBefore/>') in once
    assert page_break_before(once, "Table 3:") == once


def test_slash_is_a_break_opportunity_but_hyphen_is_not():
    def label_hard(text: str) -> int:
        d = doc(tbl(
            [900, 700, 700],
            "<w:tr>" + cell(frun(text), w=900)
            + cell(frun("-0.250***"), w=700) + cell(frun("0.047"), w=700)
            + "</w:tr>"))
        out, _ = fit_columns(d, read_all(d)[0])
        return grid_of(out)[0]
    # the slash splits the cluster; the hyphen must not (a negative
    # coefficient's sign is never a licensed break), so the slashed
    # variant needs far less width than the hyphenated one
    assert label_hard("Professional/vocational") \
        < label_hard("Professional-vocational") - 200


def test_arial_narrow_is_a_uniform_scaling_of_arial():
    """It is 0.820 of Arial in every character, digits included.

    This test used to assert the opposite — digits at 501 (0.90) and
    letters at 0.835 — because it was written from the same hand-tuned
    numbers it was meant to check, and a test that only repeats the
    model's belief cannot contradict it. Word says 456 for a digit
    (0.820 x 556) and agrees with 0.820 for every printable ASCII
    character within 0.4%; `tests/test_width_model.py -m word` is what
    holds these to a measurement rather than to each other.
    """
    from docxkit.tables import _ARIAL, _ARIAL_NARROW
    assert _ARIAL_NARROW["0"] == 456
    assert all(_ARIAL_NARROW[ch] == round(_ARIAL[ch] * 0.820)
               for ch in _ARIAL)
    # The two Arial entries the measurement corrected, kept here so a
    # revert shows up without Word: K was 722 (Helvetica's is 667) and P
    # was in no group at all, taking the 600 fallback.
    assert _ARIAL["K"] == 667
    assert _ARIAL["P"] == 667
    assert _ARIAL["!"] == 278


def test_page_break_before_creates_ppr_when_missing():
    from lxml import etree

    from docxkit.find import page_break_before
    d = doc("<w:p><w:r><w:t>Table 4: More results</w:t></w:r></w:p>")
    out = page_break_before(d, "Table 4:")
    assert "<w:pPr><w:pageBreakBefore/></w:pPr><w:r>" in out
    etree.fromstring(out.encode("utf-8"))


# ---------------------------------------- what the mutation sweep found ---

def test_a_run_that_states_only_hAnsi_is_measured_in_that_font():
    """The comment on `_HANSI_RE` says a document from another producer
    may state only w:hAnsi, and that reading one and not the other drops
    the run to the table's fallback face. Every fixture here states
    BOTH, so the fallback chain could be inverted and nothing noticed."""
    # The table-level FALLBACK is what the hAnsi half feeds, and a run
    # that states a font of its own never asks for it. So the cell that
    # has to be measured states nothing, and the rest of the table
    # states w:hAnsi only — which is the shape a non-Word producer
    # writes, and the one where reading w:ascii alone silently drops the
    # whole table to Times. Two earlier versions of this test could not
    # tell the two readings apart, because every run named its own font.
    def table_of(measured: str, neighbour: str) -> list[int]:
        d = tbl([2000, 2000],
                f"<w:tr>{cell(measured, w=2000)}{cell(neighbour, w=2000)}"
                "</w:tr>")
        out, _ = fit_columns(d, read_all(d)[0])
        return grid_of(out)

    def r(text: str, rfonts: str = "") -> str:
        return (f'<w:r><w:rPr>{rfonts}<w:sz w:val="20"/></w:rPr>'
                f"<w:t>{text}</w:t></w:r>")

    # The reference is measured from the run's OWN w:ascii, which no
    # fallback rule can touch. Comparing two FALLBACK tables to each
    # other cannot work: the misreading sends both of them to Times, so
    # they agree with each other while both being wrong.
    stated = table_of(r("WWWWWWWWWW", f'<w:rFonts w:ascii="{FONT}"/>'),
                      r("x", f'<w:rFonts w:ascii="{FONT}"/>'))
    hansi = f'<w:rFonts w:hAnsi="{FONT}"/>'
    inherited = table_of(r("WWWWWWWWWW"), r("x", hansi))
    assert inherited == stated, \
        "the bare run fell back to Times: w:hAnsi was not read"
    other = '<w:rFonts w:hAnsi="Times New Roman"/>'
    assert table_of(r("WWWWWWWWWW"), r("x", other)) != stated, \
        "the fixture cannot see a font change at all"


def test_superscript_stars_survives_a_run_with_no_text_node():
    """`if t and t.group(2)` as `or` dereferences None the moment a
    starred cell holds a run with no w:t — a bookmark run, a break, a
    field. The suite's starred cells were all plain text runs."""
    starred = ("<w:r><w:rPr><w:noProof/></w:rPr></w:r>"
               + frun("-0.250***"))
    d = tbl([2000, 2000],
            f"<w:tr>{cell(frun('Label'), w=2000)}{cell(starred, w=2000)}"
            "</w:tr>")
    out, n = superscript_stars(d, read_all(d)[0])
    assert n == 1
    assert read_all(out)[0].rows[0][1] == "-0.250***"
    assert "vertAlign" in out


@pytest.mark.parametrize("sz", [97, 200, -1])
def test_a_border_size_outside_words_range_is_refused(sz):
    """ST_EighthPointMeasure is 0..96 and Word CLAMPS outside it, so a
    number out here is a caller's mistake rather than a hairline rule —
    which is why the guard exists and why its edge has to be pinned."""
    d = tbl([2000], f"<w:tr>{cell(frun('x'), w=2000)}</w:tr>")
    with pytest.raises(AnchorError, match="eighths of a point"):
        bottom_border(d, read_all(d)[0], sz=sz)


def test_a_border_size_at_the_edge_is_accepted():
    d = tbl([2000], f"<w:tr>{cell(frun('x'), w=2000)}</w:tr>")
    out, n = bottom_border(d, read_all(d)[0], sz=96)
    assert n == 1 and 'w:sz="96"' in out
