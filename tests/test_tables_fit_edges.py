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
