"""fit_columns and friends on the shapes real manuscripts turn out to have.

The happy paths live in test_tables_fit.py. This file covers the error
paths and the structural variants that only showed up once the feature
met actual papers: tables that already declare cell margins, cells with
no ``tcPr`` at all, borders that exist but carry no bottom edge, rows
wider than the grid, stars already raised by a previous run.
"""
from __future__ import annotations

import re

import pytest
from conftest import NS
from lxml import etree

from docxkit.errors import AnchorError
from docxkit.tables import (
    _bump,
    _const,
    _round_to,
    bottom_border,
    fit_columns,
    read_all,
    superscript_stars,
)

FONT = "Arial Narrow"


def frun(text: str, *, sz: int = 20, rpr: str | None = None) -> str:
    if rpr is None:
        rpr = (f'<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/>'
               f'<w:sz w:val="{sz}"/></w:rPr>')
    return f"<w:r>{rpr}<w:t>{text}</w:t></w:r>"


def cell(content: str, *, w: int | None = 1000, span: int | None = None,
         tcpr: str | None = None) -> str:
    if tcpr is None:
        inner = ""
        if w is not None:
            inner += f'<w:tcW w:w="{w}" w:type="dxa"/>'
        if span:
            inner += f'<w:gridSpan w:val="{span}"/>'
        tcpr = f"<w:tcPr>{inner}</w:tcPr>" if inner else ""
    return f'<w:tc>{tcpr}<w:p w14:paraId="AA">{content}</w:p></w:tc>'


def tbl(grid: list[int], *rows: str, pr_extra: str = "") -> str:
    pr = (f'<w:tblPr><w:tblW w:w="{sum(grid)}" w:type="dxa"/>'
          f'<w:tblLayout w:type="fixed"/>{pr_extra}'
          '<w:tblLook w:val="04A0"/></w:tblPr>')
    g = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid) \
        + "</w:tblGrid>"
    return f"<w:tbl>{pr}{g}{''.join(rows)}</w:tbl>"


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def grid_of(xml: str) -> list[int]:
    return [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"/>', xml)]


def two_col(label: str = "Label here", coef: str = "-0.250***",
            se: str = "0.047") -> str:
    return doc(tbl([2000, 800, 800],
                   "<w:tr>" + cell(frun(label), w=2000)
                   + cell(frun(coef), w=800) + cell(frun(se), w=800)
                   + "</w:tr>"))


# ----------------------------------------------------------- error paths ---


def test_fit_columns_rejects_a_table_with_no_grid():
    d = doc("<w:tbl><w:tblPr/><w:tr>" + cell(frun("x")) + "</w:tr></w:tbl>")
    with pytest.raises(AnchorError, match="no tblGrid"):
        fit_columns(d, read_all(d)[0])


def test_fit_columns_rejects_a_table_with_no_cell_content():
    d = doc(tbl([500, 500],
                "<w:tr>" + cell(frun(""), w=500) + cell(frun(""), w=500)
                + "</w:tr>"))
    with pytest.raises(AnchorError, match="no cell content"):
        fit_columns(d, read_all(d)[0])


def test_bottom_border_rejects_a_table_with_no_rows():
    d = doc(tbl([500]))
    with pytest.raises(AnchorError, match="no rows"):
        bottom_border(d, read_all(d)[0])


def test_superscript_stars_refuses_a_tracked_table():
    d = two_col().replace(
        "<w:p w14:paraId=\"AA\">" + frun("-0.250***"),
        '<w:p w14:paraId="AA"><w:ins w:id="7" w:author="A" '
        'w:date="2026-01-01T00:00:00Z">' + frun("-0.250***") + "</w:ins>", 1)
    with pytest.raises(AnchorError, match="tracked"):
        superscript_stars(d, read_all(d)[0])


def test_round_to_refuses_weightless_apportionment():
    with pytest.raises(AnchorError, match="nothing to apportion"):
        _round_to(100, [0, 0])


def test_round_to_sums_exactly_and_keeps_order():
    out = _round_to(100, [1, 1, 1])
    assert sum(out) == 100 and len(out) == 3
    assert max(out) - min(out) <= 1        # largest-remainder, not floor
    assert sum(_round_to(9361, [3.7, 1.1, 1.1])) == 9361


def test_bump_ignores_a_span_that_already_fits():
    needs = [500, 500]
    _bump(needs, [0, 1], -50)              # negative deficit: nothing to do
    assert needs == [500, 500]


# ------------------------------------------- the literal-replacement rule ---


def test_const_inserts_backslash_sequences_literally():
    """re expands \\1 in a replacement STRING; _const must not."""
    payload = '<w:tcW w:w="1\\2" w:type="dxa"/>'
    out = re.sub(r"XX", _const(payload), "aXXb")
    assert out == "a" + payload + "b"


def test_a_replacement_carrying_a_group_reference_survives_a_fit():
    # a table whose text contains \1 must come through unharmed
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun(r"path\1\2 label"), w=2000)
                + cell(frun("-0.250***"), w=800) + "</w:tr>"))
    out, _ = fit_columns(d, read_all(d)[0])
    assert read_all(out)[0].rows[0][0] == r"path\1\2 label"
    etree.fromstring(out.encode("utf-8"))


# -------------------------------------------------- structural variants ----


def test_existing_cell_margins_are_read_not_assumed():
    """A table that declares tight margins has more usable width.

    Same content and the same total either way; the only difference is
    what the table says its padding is. Assuming Word's 108-a-side
    default here would report a table as cramped when its own margins
    leave it room — the Table 1 failure mode, in miniature.
    """
    row = ("<w:tr>" + cell(frun("Wrappable label text"), w=1000)
           + cell(frun("-0.250***"), w=600) + cell(frun("0.047"), w=600)
           + "</w:tr>")
    default = doc(tbl([1000, 600, 600], row))
    declared = doc(tbl(
        [1000, 600, 600], row,
        pr_extra=('<w:tblCellMar><w:left w:w="10" w:type="dxa"/>'
                  '<w:right w:w="10" w:type="dxa"/></w:tblCellMar>')))
    _, assumed = fit_columns(default, read_all(default)[0])
    _, actual = fit_columns(declared, read_all(declared)[0])
    assert assumed.cramped and not actual.cramped


def test_margin_replaces_existing_cell_margins():
    mar = ('<w:tblCellMar><w:left w:w="108" w:type="dxa"/>'
           '<w:right w:w="108" w:type="dxa"/></w:tblCellMar>')
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun("Label here"), w=2000)
                + cell(frun("-0.250***"), w=800) + "</w:tr>",
                pr_extra=mar))
    out, _ = fit_columns(d, read_all(d)[0], margin=25)
    assert out.count("<w:tblCellMar>") == 1        # replaced, not appended
    assert '<w:left w:w="25" w:type="dxa"/>' in out
    assert 'w:w="108"' not in out
    etree.fromstring(out.encode("utf-8"))


def test_a_cell_without_tcw_gains_one():
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun("Label here"), w=None)
                + cell(frun("-0.250***"), w=None) + "</w:tr>"))
    assert "<w:tcW" not in d
    out, _ = fit_columns(d, read_all(d)[0])
    widths = grid_of(out)
    assert [int(w) for w in re.findall(r'<w:tcW w:w="(\d+)"', out)] == widths


def test_a_cell_with_tcpr_but_no_tcw_gains_one_in_place():
    tcpr = '<w:tcPr><w:vAlign w:val="bottom"/></w:tcPr>'
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun("Label here"), tcpr=tcpr)
                + cell(frun("-0.250***"), tcpr=tcpr) + "</w:tr>"))
    out, _ = fit_columns(d, read_all(d)[0])
    assert out.count("<w:vAlign") == 2             # kept
    assert out.count("<w:tcW") == 2                # added
    etree.fromstring(out.encode("utf-8"))


def test_a_row_wider_than_the_grid_is_truncated_not_mismapped():
    """A 2-column grid with a 3-cell row: the extra cell is ignored."""
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun("Label here"), w=2000)
                + cell(frun("-0.250***"), w=800)
                + cell(frun("stray"), w=800) + "</w:tr>"))
    out, rep = fit_columns(d, read_all(d)[0])
    assert len(rep.columns) == 2
    assert len(grid_of(out)) == 2
    etree.fromstring(out.encode("utf-8"))


def test_padded_cell_text_does_not_inflate_its_column():
    plain, _ = fit_columns(two_col(), read_all(two_col())[0])
    padded_doc = two_col(coef="   -0.250***   ")
    padded, _ = fit_columns(padded_doc, read_all(padded_doc)[0])
    assert grid_of(padded)[1] == grid_of(plain)[1]


def test_a_group_header_may_wrap_but_an_unbreakable_one_may_not():
    """The span rule, pinned as a difference.

    A spanning cell is a group header: it wraps once per TABLE, where a
    body label wraps once per ROW. So a header constrains its columns
    only by its longest unbreakable word, never by its full one-line
    width — forcing "Non-violent discipline" onto one line above each
    coefficient/SE pair was measured to steal ~250 dxa per pair from
    the label column.
    """
    def widths(header: str) -> list[int]:
        d = doc(tbl([2400, 500, 500],
                    "<w:tr>" + cell(frun(""), w=2400)
                    + cell(frun(header), w=1000, span=2) + "</w:tr>",
                    "<w:tr>" + cell(frun("A wrappable label"), w=2400)
                    + cell(frun("0.054"), w=500)
                    + cell(frun("0.005"), w=500) + "</w:tr>"))
        out, _ = fit_columns(d, read_all(d)[0])
        return grid_of(out)

    spaced = widths("Non violent discipline")      # may wrap
    welded = widths("Nonviolentdiscipline")        # cannot wrap
    assert sum(spaced[1:]) < sum(welded[1:])
    assert spaced[0] > welded[0]                   # the label keeps it


def test_a_span_over_only_empty_columns_is_skipped():
    d = doc(tbl([2000, 400, 400],
                "<w:tr>" + cell(frun("Header text here"), w=2000)
                + cell(frun("Group"), w=800, span=2) + "</w:tr>",
                "<w:tr>" + cell(frun("Label here"), w=2000)
                + cell(frun(""), w=400) + cell(frun(""), w=400)
                + "</w:tr>"))
    out, rep = fit_columns(d, read_all(d)[0])
    assert [c.new for c in rep.columns][1:] == [400, 400]   # spacers kept
    etree.fromstring(out.encode("utf-8"))


# ------------------------------------------------- superscript variants ----


def test_stars_already_raised_are_left_alone():
    raised = ('<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
              "<w:t>***</w:t></w:r>")
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun("Label here"), w=2000)
                + cell(frun("-0.250") + raised, w=800) + "</w:tr>"))
    out, n = superscript_stars(d, read_all(d)[0])
    assert (n, out) == (0, d)


def test_a_run_without_rpr_gains_one_for_the_stars():
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell("<w:r><w:t>Label here</w:t></w:r>", w=2000)
                + cell("<w:r><w:t>-0.250***</w:t></w:r>", w=800)
                + "</w:tr>"))
    out, n = superscript_stars(d, read_all(d)[0])
    assert n == 1
    assert '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>' in out
    assert read_all(out)[0].rows[0][1] == "-0.250***"
    etree.fromstring(out.encode("utf-8"))


def test_an_empty_cell_is_not_mistaken_for_a_starred_one():
    d = doc(tbl([2000, 800],
                "<w:tr>" + cell(frun("Label here"), w=2000)
                + cell(frun(""), w=800) + "</w:tr>"))
    out, n = superscript_stars(d, read_all(d)[0])
    assert (n, out) == (0, d)


def test_stars_survive_the_typographic_minus_and_separators():
    for text in ("−0.250***", "1,234.5**", "0.047*"):
        d = doc(tbl([2000, 900],
                    "<w:tr>" + cell(frun("Label here"), w=2000)
                    + cell(frun(text), w=900) + "</w:tr>"))
        out, n = superscript_stars(d, read_all(d)[0])
        assert n == 1, text
        assert read_all(out)[0].rows[0][1] == text


def test_a_value_with_a_trailing_note_is_not_treated_as_stars():
    d = doc(tbl([2000, 900],
                "<w:tr>" + cell(frun("Label here"), w=2000)
                + cell(frun("0.047 (see note)"), w=900) + "</w:tr>"))
    _, n = superscript_stars(d, read_all(d)[0])
    assert n == 0


# ------------------------------------------------------ border variants ----


def test_border_is_added_to_tcborders_that_lack_a_bottom():
    tcpr = ('<w:tcPr><w:tcW w:w="800" w:type="dxa"/>'
            '<w:tcBorders><w:top w:val="single"/></w:tcBorders></w:tcPr>')
    d = doc(tbl([800], "<w:tr>" + cell(frun("x"), tcpr=tcpr) + "</w:tr>"))
    out, n = bottom_border(d, read_all(d)[0])
    assert n == 1
    assert '<w:top w:val="single"/>' in out          # untouched
    assert '<w:bottom w:val="double"' in out
    etree.fromstring(out.encode("utf-8"))


def test_border_reaches_a_cell_with_no_tcpr_at_all():
    d = doc(tbl([800], "<w:tr><w:tc><w:p w14:paraId='AA'>"
                + frun("x") + "</w:p></w:tc></w:tr>"))
    assert "<w:tcPr>" not in d
    out, n = bottom_border(d, read_all(d)[0])
    assert n == 1
    assert "<w:tcPr><w:tcBorders>" in out
    etree.fromstring(out.encode("utf-8"))


def test_border_style_and_weight_are_configurable():
    out, _ = bottom_border(two_col(), read_all(two_col())[0],
                           val="single", sz=12)
    assert '<w:bottom w:val="single" w:sz="12"' in out


# ---------------------------------------------------------- integration ----


def chain(xml: str) -> tuple[str, tuple[int, int]]:
    """The paper's property pass: stars, fit, closing rule."""
    out, stars = superscript_stars(xml, read_all(xml)[0])
    out, _ = fit_columns(out, read_all(out)[0])
    out, ruled = bottom_border(out, read_all(out)[0])
    return out, (stars, ruled)


def realistic() -> str:
    """Two country panels of a coefficient/SE table with a group header."""
    rows = [
        "<w:tr>" + cell(frun(""), w=2400)
        + cell(frun("OLS"), w=1600, span=2) + "</w:tr>",
        "<w:tr>" + cell(frun(""), w=2400) + cell(frun("Coeff."), w=800)
        + cell(frun("Std.Err"), w=800) + "</w:tr>",
    ]
    for label, coef, se in (
            ("Kyrgyzstan", "", ""),
            ("Professional/vocational education", "-0.250***", "0.047"),
            ("Child’s age", "0.054**", "0.005"),
            ("Urban", "0.022", "0.037")):
        rows.append("<w:tr>" + cell(frun(label), w=2400)
                    + cell(frun(coef), w=800) + cell(frun(se), w=800)
                    + "</w:tr>")
    return doc(tbl([2400, 800, 800], *rows))


def test_the_whole_property_chain_is_a_fixed_point():
    once, counts = chain(realistic())
    twice, again = chain(once)
    assert counts == (2, 3)      # two starred cells; the last row's 3 ruled
    assert again == (0, 0)
    assert twice == once


def test_the_chain_preserves_every_cell_of_text():
    before = read_all(realistic())[0].rows
    after = read_all(chain(realistic())[0])[0].rows
    assert after == before


def test_the_chain_keeps_tcw_consistent_with_the_grid():
    out, _ = chain(realistic())
    widths = grid_of(out)
    for tr in re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL):
        tcw = [int(w) for w in re.findall(r'<w:tcW w:w="(\d+)"', tr)]
        assert sum(tcw) == sum(widths), tr[:80]
    etree.fromstring(out.encode("utf-8"))


def test_raising_the_stars_first_buys_the_label_column_width():
    """The reason the paper runs superscript_stars before fit_columns."""
    plain, _ = fit_columns(realistic(), read_all(realistic())[0])
    raised, _ = chain(realistic())
    assert grid_of(raised)[0] > grid_of(plain)[0]
    assert grid_of(raised)[1] < grid_of(plain)[1]


# ------------------------------------------------------------ packaging ----


def test_the_package_ships_the_py_typed_marker():
    """Without it a consumer's type checker silently treats us as Any."""
    from pathlib import Path

    import docxkit
    assert (Path(docxkit.__file__).parent / "py.typed").is_file()
