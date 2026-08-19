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

from docxkit import tables
from docxkit._xml import visible_text
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


# ------------------------------------------- three-line (booktabs) style --


def _regression_table() -> str:
    """A group head over two columns, a sub-head, two country panels,
    and a summary block — the shape every results table here has."""
    rows = [
        "<w:tr>" + cell(frun(""), w=2000)
        + cell(frun("OLS Regression"), w=1600, span=2) + "</w:tr>",
        "<w:tr>" + cell(frun(""), w=2000) + cell(frun("Coeff."), w=800)
        + cell(frun("Std.Err"), w=800) + "</w:tr>",
    ]
    for label, a, b in (("Kyrgyzstan", "", ""),
                        ("Child's age", "0.054", "0.005"),
                        ("Turkmenistan", "", ""),
                        ("Child's age", "0.006", "0.004"),
                        ("Number of observations", "3,168", "")):
        rows.append("<w:tr>" + cell(frun(label), w=2000)
                    + cell(frun(a), w=800) + cell(frun(b), w=800)
                    + "</w:tr>")
    return doc(tbl([2000, 800, 800], *rows))


def _row_edges(xml: str) -> list[list[str]]:
    """The non-nil edges of each row, as `side:val` strings."""
    out = []
    for tr in re.findall(r"<w:tr>.*?</w:tr>", xml, re.DOTALL):
        edges = []
        for side, val in re.findall(
                r'<w:(top|bottom) w:val="(\w+)"', tr):
            if val != "nil":
                edges.append(f"{side}:{val}")
        out.append(sorted(set(edges)))
    return out


def test_the_plan_reads_the_shape_of_a_results_table():
    from docxkit.tables import plan_booktabs
    t = read_all(_regression_table())[0]
    plan = plan_booktabs(t)
    assert plan.header_rows == 2          # the two rows with no stub label
    assert plan.group_rows == [0]         # "OLS Regression" spans
    assert plan.panel_rows == [2, 4]      # the two country rows
    assert plan.stats_rows == [6]         # "Number of observations"


def test_three_line_style_draws_exactly_the_meaningful_rules():
    from docxkit.tables import booktabs
    xml = _regression_table()
    out, _ = booktabs(xml, read_all(xml)[0])
    edges = _row_edges(out)
    assert "top:single" in edges[0]            # top rule
    assert "bottom:single" in edges[0]         # cmidrule under the group
    assert "bottom:single" in edges[1]         # mid rule closes the header
    assert "top:single" in edges[2]            # panel
    assert edges[3] == []                      # a data row carries nothing
    assert "top:single" in edges[4]            # the second panel
    assert "top:single" in edges[6]            # above the summary block
    assert "bottom:double" in edges[6]         # and the double bottom


def test_the_partial_rule_covers_only_the_spanning_cells():
    """A cmidrule under the stub column would be a rule under nothing."""
    from docxkit.tables import booktabs
    xml = _regression_table()
    out, _ = booktabs(xml, read_all(xml)[0])
    first = re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL)[0]
    cells = re.findall(r"<w:tc>.*?</w:tc>", first, re.DOTALL)
    def bottom_of(cell: str) -> str:
        m = re.search(r"<w:bottom [^>]*/>", cell)
        assert m is not None, "every cell states its edges explicitly"
        return m.group(0)

    assert 'w:val="nil"' in bottom_of(cells[0])       # the stub: no rule
    assert 'w:val="single"' in bottom_of(cells[1])    # the group: ruled


def test_every_other_rule_is_cleared():
    """The tables arrived with rules stacked three deep; the style is
    defined by what it removes as much as by what it draws."""
    from docxkit.tables import booktabs
    xml = _regression_table()
    # a table boxed on every edge
    boxed = xml.replace(
        '<w:tcPr><w:tcW w:w="800" w:type="dxa"/></w:tcPr>',
        '<w:tcPr><w:tcW w:w="800" w:type="dxa"/><w:tcBorders>'
        '<w:top w:val="single"/><w:bottom w:val="single"/>'
        '<w:left w:val="single"/><w:right w:val="single"/>'
        "</w:tcBorders></w:tcPr>")
    out, _ = booktabs(boxed, read_all(boxed)[0])
    left = re.search(r"<w:left [^>]*/>", out)
    assert left is not None
    assert 'w:val="single"' not in left.group(0)      # no vertical rules
    assert _row_edges(out)[3] == []                   # data row is bare


def test_three_line_style_is_idempotent():
    from docxkit.tables import booktabs
    xml = _regression_table()
    once, _ = booktabs(xml, read_all(xml)[0])
    twice, _ = booktabs(once, read_all(once)[0])
    assert twice == once


def test_the_style_preserves_every_value():
    from docxkit.tables import booktabs
    xml = _regression_table()
    out, _ = booktabs(xml, read_all(xml)[0])
    assert read_all(out)[0].rows == read_all(xml)[0].rows
    from lxml import etree
    etree.fromstring(out.encode("utf-8"))


def test_a_stated_plan_overrides_the_inference():
    """A table whose stub column is filled from the first row has no
    empty-labelled header to detect; the caller says so instead."""
    from docxkit.tables import BooktabsPlan, booktabs
    xml = _regression_table()
    plan = BooktabsPlan(header_rows=1, group_rows=[], panel_rows=[],
                        stats_rows=[])
    out, used = booktabs(xml, read_all(xml)[0], plan=plan)
    assert used is plan
    assert "bottom:single" in _row_edges(out)[0]      # header closes at r0
    assert _row_edges(out)[2] == []                   # no panel rule now


# ------------------------------------ an empty <w:tcBorders/> is valid ----


def _cell_with(tcborders: str) -> str:
    tc = ('<w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/>' + tcborders
          + "</w:tcPr><w:p><w:r><w:t>0.054</w:t></w:r></w:p></w:tc>")
    return doc('<w:tbl><w:tblPr><w:tblW w:w="900" w:type="dxa"/></w:tblPr>'
               '<w:tblGrid><w:gridCol w:w="900"/></w:tblGrid>'
               f"<w:tr>{tc}</w:tr></w:tbl>")


@pytest.mark.parametrize("existing", [
    "<w:tcBorders/>",                                  # the empty form
    '<w:tcBorders w:x="1"/>',                          # with an attribute
    '<w:tcBorders><w:top w:val="single"/></w:tcBorders>',
    "",                                                # none at all
])
def test_a_cell_never_ends_up_with_two_border_elements(existing):
    """An empty <w:tcBorders/> is valid OOXML. Matching only the
    expanded form made both writers insert a SECOND element beside it —
    two w:tcBorders in one w:tcPr, which is schema-invalid, and which
    neither the write gate nor lint saw.
    """
    from docxkit.lint import lint_parts
    from docxkit.tables import booktabs, bottom_border
    xml = _cell_with(existing)
    for fn in (booktabs, bottom_border):
        out, _ = fn(xml, read_all(xml)[0])
        assert len(re.findall(r"<w:tcBorders\b", out)) == 1, fn.__name__
        assert not lint_parts({"word/document.xml": out.encode("utf-8")})


def test_bottom_border_keeps_the_other_edges_a_cell_states():
    from docxkit.tables import bottom_border
    xml = _cell_with('<w:tcBorders><w:top w:val="single" w:sz="4" '
                     'w:space="0" w:color="auto"/></w:tcBorders>')
    out, _ = bottom_border(xml, read_all(xml)[0])
    assert '<w:top w:val="single"' in out          # untouched
    assert '<w:bottom w:val="double"' in out       # added


def test_lint_reports_a_duplicated_property_child():
    from docxkit.lint import lint_parts
    xml = doc('<w:tbl><w:tr><w:tc><w:tcPr><w:tcBorders/>'
              '<w:tcBorders><w:top w:val="single"/></w:tcBorders>'
              "</w:tcPr><w:p/></w:tc></w:tr></w:tbl>")
    problems = lint_parts({"word/document.xml": xml.encode("utf-8")})
    assert problems and "two w:tcBorders" in problems[0]


def test_no_source_file_carries_a_control_character():
    """The bash-heredoc trap, which has now mangled a pattern four times
    in one session: `\b` in a non-raw context becomes U+0008 and the
    regex silently matches nothing. Cheap to make impossible to ship."""
    from pathlib import Path

    import docxkit
    for path in Path(docxkit.__file__).parent.glob("*.py"):
        blob = path.read_bytes()
        for ch in (b"\x08", b"\x00", b"\x01", b"\x0c"):
            assert ch not in blob, f"{path.name} carries {ch!r}"


# ------------------------------------------- CT_TcPr is a SEQUENCE --------


@pytest.mark.parametrize("props,expected", [
    ('<w:tcW w:w="900" w:type="dxa"/><w:noWrap/><w:hideMark/>',
     ["tcW", "tcBorders", "noWrap", "hideMark"]),
    ('<w:tcW w:w="900" w:type="dxa"/><w:vMerge/><w:shd w:val="clear"/>',
     ["tcW", "vMerge", "tcBorders", "shd"]),
    ('<w:tcW w:w="900" w:type="dxa"/><w:headers w:val="h1"/>',
     ["tcW", "tcBorders", "headers"]),
    ('<w:tcW w:w="900" w:type="dxa"/><w:textDirection w:val="btLr"/>',
     ["tcW", "tcBorders", "textDirection"]),
    ('<w:gridSpan w:val="2"/><w:tcFitText/>',
     ["gridSpan", "tcBorders", "tcFitText"]),
])
def test_the_border_lands_in_its_schema_position(props, expected):
    """CT_TcPr is a sequence. Anchoring only on shd/tcMar/vAlign put the
    borders AFTER w:noWrap in a cell carrying none of those three, and
    Word repairs a document whose properties are out of order."""
    from docxkit.tables import booktabs
    xml = doc('<w:tbl><w:tblPr><w:tblW w:w="900" w:type="dxa"/></w:tblPr>'
              '<w:tblGrid><w:gridCol w:w="900"/></w:tblGrid>'
              f"<w:tr><w:tc><w:tcPr>{props}</w:tcPr>"
              "<w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    out, _ = booktabs(xml, read_all(xml)[0])
    tcpr = re.search(r"<w:tcPr>.*?</w:tcPr>", out, re.DOTALL)
    assert tcpr is not None
    order = re.findall(
        r"<w:(tcW|gridSpan|vMerge|tcBorders|shd|noWrap|tcMar|"
        r"textDirection|tcFitText|vAlign|hideMark|headers)\b", tcpr.group(0))
    assert order == expected


# ------------------------------------------------ nested tables -----------


def _nested_row_table() -> str:
    """A nested table in the FIRST of two outer cells — the shape that
    makes a non-nesting <w:tc>.*?</w:tc> stop at the inner cell."""
    inner = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="400"/></w:tblGrid>'
             "<w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>inner</w:t></w:r></w:p>"
             "</w:tc></w:tr></w:tbl>")
    return doc('<w:tbl><w:tblPr><w:tblW w:w="1800" w:type="dxa"/></w:tblPr>'
               '<w:tblGrid><w:gridCol w:w="900"/><w:gridCol w:w="900"/>'
               "</w:tblGrid>"
               '<w:tr><w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/></w:tcPr>'
               + inner + "<w:p><w:r><w:t>after inner</w:t></w:r></w:p>"
               "</w:tc>"
               '<w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/><w:tcBorders>'
               '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               "</w:tcBorders></w:tcPr>"
               "<w:p><w:r><w:t>SECOND</w:t></w:r></w:p></w:tc>"
               "</w:tr></w:tbl>")


def test_a_nested_table_does_not_truncate_the_outer_cell():
    """read_all reported the outer cell as the INNER one's text and lost
    the second cell entirely — silent data loss in every value test."""
    t = read_all(_nested_row_table())[0]
    assert len(t.rows[0]) == 2, t.rows
    assert "after inner" in t.rows[0][0]
    assert t.rows[0][1] == "SECOND"


def test_the_style_reaches_every_cell_of_a_row_with_a_nested_table():
    """booktabs promises it clears every rule; a cell the walk never
    reached kept its vertical border, which is a broken contract."""
    from docxkit.tables import booktabs
    xml = _nested_row_table()
    out, _ = booktabs(xml, read_all(xml)[0])
    outer = out[out.index("<w:tbl>"):]
    # the inner table keeps its own (untouched) markup; the OUTER cells
    # must both have been cleared and ruled
    first_left = re.search(r"<w:left [^>]*/>", outer)
    assert first_left is not None
    assert 'w:val="single"' not in first_left.group(0)
    assert out.count('<w:bottom w:val="double"') == 2   # both outer cells


# ----------------------------- the OUTER cell's own properties only -------


def _outer_with_nested(outer_props: str) -> str:
    """A cell whose nested table HAS borders while the outer cell may
    not — the shape that made a whole-string search rewrite the wrong
    element."""
    nested = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="400"/>'
              "</w:tblGrid><w:tr><w:tc><w:tcPr><w:tcBorders>"
              '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
              "</w:tcBorders></w:tcPr><w:p><w:r><w:t>in</w:t></w:r></w:p>"
              "</w:tc></w:tr></w:tbl>")
    return doc('<w:tbl><w:tblPr><w:tblW w:w="900" w:type="dxa"/></w:tblPr>'
               '<w:tblGrid><w:gridCol w:w="900"/></w:tblGrid>'
               f"<w:tr><w:tc>{outer_props}{nested}"
               "<w:p><w:r><w:t>out</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")


@pytest.mark.parametrize("outer_props", [
    '<w:tcPr><w:tcW w:w="900" w:type="dxa"/></w:tcPr>',   # no borders yet
    "<w:tcPr/>",                                          # empty, valid
    "",                                                   # none at all
])
def test_the_outer_cell_is_ruled_not_the_nested_one(outer_props):
    """Searching the whole cell string found the NESTED table's borders
    and rewrote those, leaving the outer cell unruled — a rule drawn on
    the wrong table, silently."""
    from docxkit.lint import lint_parts
    from docxkit.tables import booktabs
    xml = _outer_with_nested(outer_props)
    out, _ = booktabs(xml, read_all(xml)[0])

    outer = re.match(r".*?<w:tc>(?:(?!<w:tbl>).)*", out, re.DOTALL)
    assert outer is not None
    assert "<w:tcBorders>" in outer.group(0), "the outer cell got no rule"
    assert 'w:val="double"' in outer.group(0)
    assert len(re.findall(r"<w:tcPr\b", outer.group(0))) == 1
    assert not lint_parts({"word/document.xml": out.encode("utf-8")})


def test_an_empty_properties_element_is_expanded_not_duplicated():
    """<w:tcPr/> is valid. Reading it as absent prepended a SECOND
    properties element beside it."""
    from docxkit.lint import lint_parts
    from docxkit.tables import booktabs, bottom_border
    xml = doc('<w:tbl><w:tblPr><w:tblW w:w="900" w:type="dxa"/></w:tblPr>'
              '<w:tblGrid><w:gridCol w:w="900"/></w:tblGrid>'
              "<w:tr><w:tc><w:tcPr/>"
              "<w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    for fn in (booktabs, bottom_border):
        out, _ = fn(xml, read_all(xml)[0])
        assert len(re.findall(r"<w:tcPr\b", out)) == 1, fn.__name__
        assert not lint_parts({"word/document.xml": out.encode("utf-8")})


def test_lint_reports_a_duplicated_properties_element():
    from docxkit.lint import lint_parts
    xml = doc("<w:tbl><w:tr><w:tc><w:tcPr><w:tcBorders/></w:tcPr>"
              "<w:tcPr/><w:p/></w:tc></w:tr></w:tbl>")
    problems = lint_parts({"word/document.xml": xml.encode("utf-8")})
    assert problems and "2 w:tcPr" in problems[0]


# --------------------------------- a formatting-only tracked change -------


def _property_change_cell() -> str:
    """Word stores a property change as a snapshot of the OLD properties
    NESTED inside the new ones — a second w:tcPr, with its own borders,
    and no content revision marker anywhere in the cell."""
    return doc('<w:tbl><w:tblPr><w:tblW w:w="900" w:type="dxa"/></w:tblPr>'
               '<w:tblGrid><w:gridCol w:w="900"/></w:tblGrid>'
               '<w:tr><w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/>'
               '<w:tcPrChange w:id="7" w:author="A" '
               'w:date="2026-01-01T00:00:00Z"><w:tcPr><w:tcBorders>'
               '<w:bottom w:val="single" w:sz="4" w:space="0" '
               'w:color="auto"/></w:tcBorders></w:tcPr></w:tcPrChange>'
               "</w:tcPr><w:p><w:r><w:t>0.054</w:t></w:r></w:p>"
               "</w:tc></w:tr></w:tbl>")


def test_a_formatting_only_revision_counts_as_a_tracked_change():
    """The guard looked for insertions and deletions, so a cell whose
    ONLY revision is a property snapshot read as clean."""
    from docxkit.revisions import _has_revisions
    assert _has_revisions(_property_change_cell())


@pytest.mark.parametrize("writer", ["booktabs", "bottom_border",
                                    "fit_columns", "superscript_stars"])
def test_every_writer_refuses_a_formatting_revision(writer):
    from docxkit import tables as T
    from docxkit.errors import AnchorError
    xml = _property_change_cell()
    with pytest.raises(AnchorError, match="tracked changes"):
        getattr(T, writer)(xml, read_all(xml)[0])


def test_the_historical_snapshot_is_never_the_element_rewritten():
    """Defence in depth: even with the guard bypassed, the search must
    not reach into the past. It found the snapshot's rule, rewrote THAT,
    and left the live cell with no border at all."""
    from docxkit._table_layout import _set_borders
    cell = ('<w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/>'
            '<w:tcPrChange w:id="7" w:author="A" '
            'w:date="2026-01-01T00:00:00Z"><w:tcPr><w:tcBorders>'
            '<w:bottom w:val="single" w:sz="4" w:space="0" '
            'w:color="auto"/></w:tcBorders></w:tcPr></w:tcPrChange>'
            "</w:tcPr><w:p/></w:tc>")
    out = _set_borders(cell, '<w:tcBorders><w:bottom w:val="double" '
                             'w:sz="4" w:space="0" w:color="auto"/>'
                             "</w:tcBorders>")
    snapshot = re.search(r"<w:tcPrChange.*?</w:tcPrChange>", out, re.DOTALL)
    assert snapshot is not None
    assert "double" not in snapshot.group(0), "the past was rewritten"
    assert 'w:val="single"' in snapshot.group(0), "the past was preserved"
    current = out[:out.index("<w:tcPrChange")]
    assert "double" in current, "the live cell got no rule"


# ------------------------------------------------------- alignment ---------


def _aligned_table() -> str:
    def tc(text: str, span: int = 1) -> str:
        s = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
        return (f'<w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/>{s}</w:tcPr>'
                f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r>'
                "</w:p></w:tc>")

    def tr(*cells: str) -> str:
        return "<w:tr>" + "".join(cells) + "</w:tr>"

    return (f"<w:document {NS}><w:body><w:tbl>"
            '<w:tblPr><w:tblW w:w="4500" w:type="dxa"/></w:tblPr>'
            "<w:tblGrid>" + '<w:gridCol w:w="900"/>' * 5 + "</w:tblGrid>"
            + tr(tc(""), tc("Boys", 2), tc("Girls", 2))
            + tr(tc("Child age"), tc("-0.25"), tc("0.04"), tc("-0.11"),
                 tc("0.03"))
            + "</w:tbl></w:body></w:document>")


def test_align_sets_the_stub_left_and_the_rest_centred():
    """The house convention, and the last value repeating is what makes
    ("left", "center") mean it whatever the table's width."""
    xml = _aligned_table()
    t = tables.read_all(xml)[0]
    out, _ = tables.booktabs(xml, t, align=("left", "center"))
    rows = re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL)
    assert re.findall(r'<w:jc w:val="(\w+)"/>', rows[1]) == \
        ["left", "center", "center", "center", "center"]


def test_align_follows_grid_columns_not_cell_positions():
    """A spanning header takes the alignment of the column it STARTS in.
    Cell index and grid column only coincide without merged cells, and
    assuming they do is what italicised the wrong column once already."""
    xml = _aligned_table()
    t = tables.read_all(xml)[0]
    out, _ = tables.booktabs(xml, t, align=("left", "center", "right"))
    header = re.findall(r"<w:tr>.*?</w:tr>", out, re.DOTALL)[0]
    # three cells at grid columns 0, 1 and 3 -> left, center, right
    assert re.findall(r'<w:jc w:val="(\w+)"/>', header) == \
        ["left", "center", "right"]


def test_align_is_idempotent_and_keeps_the_text():
    xml = _aligned_table()
    out, _ = tables.booktabs(xml, tables.read_all(xml)[0], align="center")
    again, _ = tables.booktabs(out, tables.read_all(out)[0], align="center")
    assert again == out
    assert visible_text(out) == visible_text(xml)
    # one per cell, no duplicates: 3 header cells (two of them spanning)
    # plus 5 data cells
    assert out.count("<w:jc") == 8


def test_an_unknown_alignment_is_refused():
    xml = _aligned_table()
    with pytest.raises(AnchorError, match="align"):
        tables.booktabs(xml, tables.read_all(xml)[0], align="middle")


# ---------------------------------------------------- what a line IS -------
# The model measures characters, so anything that is not a character and
# still moves the text is invisible to it until it is read for.


def _extents(cell_xml: str):
    from docxkit._table_layout import _cell_extents
    return _cell_extents(cell_xml, ("Times New Roman", 20))


def _para(*content: str) -> str:
    return "<w:tc><w:p>" + "".join(content) + "</w:p></w:tc>"


def test_a_hard_break_ends_a_line_the_way_a_paragraph_mark_does():
    """`Total<w:br/>expenditure` is two lines, not one long word.

    The scan read `w:t` only, so the break vanished and the two words
    fused into the single unbreakable cluster "Totalexpenditure" — 45%
    wider than anything the cell renders. `hard` is the floor a column
    cannot go below, so the cell bought that width out of the label
    column, which is the one place it can come from.
    """
    plain = _para('<w:r><w:t>Total expenditure</w:t></w:r>')
    broken = _para('<w:r><w:t>Total</w:t></w:r>', "<w:r><w:br/></w:r>",
                   '<w:r><w:t>expenditure</w:t></w:r>')
    split = ('<w:tc><w:p><w:r><w:t>Total</w:t></w:r></w:p>'
             '<w:p><w:r><w:t>expenditure</w:t></w:r></w:p></w:tc>')

    hard_b, full_b, text_b = _extents(broken)
    hard_s, full_s, _ = _extents(split)
    hard_p, full_p, _ = _extents(plain)

    # a break behaves exactly like the paragraph mark it stands in for
    assert (hard_b, full_b) == (hard_s, full_s)
    # and neither claims the whole one-line width
    assert full_b < full_p
    # the widest word, not the two of them run together
    assert hard_b == hard_p
    assert "Totalexpenditure" not in text_b


def test_a_carriage_return_breaks_the_line_too():
    br = _para('<w:r><w:t>a</w:t></w:r>', "<w:r><w:br/></w:r>",
               '<w:r><w:t>b</w:t></w:r>')
    cr = _para('<w:r><w:t>a</w:t></w:r>', "<w:r><w:cr/></w:r>",
               '<w:r><w:t>b</w:t></w:r>')
    assert _extents(cr)[:2] == _extents(br)[:2]


def test_a_page_break_is_still_a_break():
    """`<w:br w:type="page"/>` — the attribute does not stop it ending
    the line, and a pattern that demanded a bare `<w:br/>` missed it."""
    typed = _para('<w:r><w:t>a</w:t></w:r>',
                  '<w:r><w:br w:type="page"/></w:r>',
                  '<w:r><w:t>b</w:t></w:r>')
    bare = _para('<w:r><w:t>a</w:t></w:r>', "<w:r><w:br/></w:r>",
                 '<w:r><w:t>b</w:t></w:r>')
    assert _extents(typed)[:2] == _extents(bare)[:2]


def test_a_tab_advances_the_line_instead_of_vanishing():
    """A tab is layout-bearing content. Read as nothing, a cell holding
    one measured as though its two halves were adjacent."""
    # the same letter both sides, so the halves are directly comparable
    tabbed = _para('<w:r><w:t>a</w:t></w:r>', "<w:r><w:tab/></w:r>",
                   '<w:r><w:t>a</w:t></w:r>')
    joined = _para('<w:r><w:t>aa</w:t></w:r>')
    assert _extents(tabbed)[1] > _extents(joined)[1]
    # and it breaks the cluster, as any whitespace does
    assert _extents(tabbed)[0] == _extents(joined)[0] / 2


@pytest.mark.parametrize("ref", ["&#x2013;", "&#8211;"])
def test_a_numeric_character_reference_measures_as_one_character(ref):
    """`&#x2013;` is an en dash, not eight ASCII characters.

    The module carried a five-entity table of its own where
    `visible_text` reads the same text with `html.unescape`, so the two
    disagreed about what a cell says — and the width came out 79% over.
    """
    literal = _para('<w:r><w:t>2010–2020</w:t></w:r>')
    encoded = _para(f'<w:r><w:t>2010{ref}2020</w:t></w:r>')
    assert _extents(encoded) == _extents(literal)


def test_the_named_entities_still_decode():
    assert _extents(_para('<w:r><w:t>R&amp;D</w:t></w:r>')) == \
        _extents(_para("<w:r><w:t>R&D</w:t></w:r>"))


def test_a_run_naming_only_hansi_is_not_dropped_to_the_fallback():
    """Word writes w:ascii and w:hAnsi together; another producer need
    not, and they cover the same Latin text."""
    both = _para(f'<w:r><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/>'
                 '<w:sz w:val="20"/></w:rPr><w:t>Narrow</w:t></w:r>')
    hansi = _para(f'<w:r><w:rPr><w:rFonts w:hAnsi="{FONT}"/>'
                  '<w:sz w:val="20"/></w:rPr><w:t>Narrow</w:t></w:r>')
    assert _extents(hansi) == _extents(both)


# ------------------------------------------------- a rule Word can draw ----


@pytest.mark.parametrize("val", ['single" w:hack="x', "hairline", ""])
def test_a_border_style_word_does_not_know_is_refused(val):
    """`val` is interpolated into an attribute, so one carrying a quote
    closes it early and produces a document Word calls unreadable. The
    write gate refuses to ship that; this says which argument was wrong,
    at the call that passed it."""
    xml = two_col()
    with pytest.raises(AnchorError, match="not a border style"):
        bottom_border(xml, read_all(xml)[0], val=val)


def test_a_border_width_outside_words_range_is_refused():
    xml = two_col()
    with pytest.raises(AnchorError, match="eighths of a point"):
        bottom_border(xml, read_all(xml)[0], sz=400)


def test_booktabs_checks_its_closing_rule_too():
    xml = two_col()
    with pytest.raises(AnchorError, match="not a border style"):
        tables.booktabs(xml, read_all(xml)[0], bottom="quadruple")


def test_a_width_written_in_the_other_attribute_order_is_still_replaced():
    """`<w:tblW w:type="auto" w:w="0"/>` is the same element.

    Word writes `w:w` first and the old pattern required that, so on a
    manuscript that writes `w:type` first it matched nothing: the table
    kept its AUTO width while its columns were divided in fixed dxa, and
    Word sized the result by neither. Found in an accepted paper, not
    invented — attribute order carries no meaning, which is what the
    bookmark patterns in `_xml` say about their own `[^>]*`.
    """
    xml = doc(
        '<w:tbl><w:tblPr><w:tblW w:type="auto" w:w="0"/></w:tblPr>'
        '<w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="800"/>'
        "</w:tblGrid><w:tr>" + cell(frun("Label here"), w=2000)
        + cell(frun("-0.250***"), w=800) + "</w:tr></w:tbl>")
    out, report = fit_columns(xml, read_all(xml)[0], total=2800)

    assert '<w:tblW w:w="2800" w:type="dxa"/>' in out
    assert 'w:type="auto"' not in out
    # and exactly one width element survives, not the old beside the new
    assert out.count("<w:tblW") == 1
    assert sum(c.new for c in report.columns) == 2800


def test_the_border_styles_the_house_uses_are_all_accepted():
    for val in ("single", "double", "nil", "none", "thick", "dotted"):
        xml = two_col()
        out, n = bottom_border(xml, read_all(xml)[0], val=val)
        assert n == 3
        assert f'w:val="{val}"' in out


def test_spacer_columns_that_eat_the_table_are_REFUSED_by_the_numbers():
    """`avail <= 0`, and the message's arithmetic. A spacer column keeps
    its width unconditionally, so a grid whose spacers are wider than
    the table leaves nothing to apportion — and `_round_to` would then
    divide a NEGATIVE total, writing every filled column as a negative
    `w:w`. That is not a narrow table: ST_TwipsMeasure is unsigned, and
    Word repairs the document rather than laying it out.

    The refusal has to say how much is held and of what, because the
    fix is a number the caller chooses — a wider table, or a `total=`
    that matches the section's text width."""
    d = doc(tbl([2500, 1000],
                "<w:tr>" + cell(frun(""), w=2500) + cell(frun("x"), w=1000)
                + "</w:tr>"))

    with pytest.raises(AnchorError) as exc:
        fit_columns(d, read_all(d)[0], total=2000)

    assert "the spacer columns hold 2500 dxa of a 2000 dxa table" in \
        str(exc.value)
    assert "the 1 column(s) with content" in str(exc.value)
