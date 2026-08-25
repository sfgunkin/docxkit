"""regrid — collapsing a phantom grid onto a table's real columns.

The scenario throughout is the one that motivated it: a regression table
pasted out of a fixed-width source, whose `w:tblGrid` records where the
CHARACTERS fell rather than where the columns are. Every row then picks
its own spans over that grid, so a boundary 24 grid columns in on one
row is 20 on the next — and Word draws the second block of rows shifted
against the first.
"""
from __future__ import annotations

import pytest

from docxkit.errors import AnchorError
from docxkit.tables import fit_columns, read_all, regrid


def cell(text: str, *, span: int | None = None, w: int | None = None) -> str:
    props = ""
    if w is not None:
        props += f'<w:tcW w:w="{w}" w:type="dxa"/>'
    if span:
        props += f'<w:gridSpan w:val="{span}"/>'
    tcpr = f"<w:tcPr>{props}</w:tcPr>" if props else ""
    return (f"<w:tc>{tcpr}<w:p w14:paraId=\"AA\"><w:r>"
            f"<w:rPr><w:rFonts w:ascii=\"Times New Roman\" "
            f"w:hAnsi=\"Times New Roman\"/><w:sz w:val=\"20\"/></w:rPr>"
            f"<w:t>{text}</w:t></w:r></w:p></w:tc>")


def row(*cells: str) -> str:
    return f"<w:tr>{''.join(cells)}</w:tr>"


def tbl(grid: list[int], *rows: str) -> str:
    pr = (f'<w:tblPr><w:tblW w:w="{sum(grid)}" w:type="dxa"/>'
          '<w:tblLook w:val="04A0"/></w:tblPr>')
    g = ("<w:tblGrid>"
         + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
         + "</w:tblGrid>")
    return f"<w:tbl>{pr}{g}{''.join(rows)}</w:tbl>"


def doc(body: str) -> str:
    return f"<w:document><w:body>{body}</w:body></w:document>"


def only(xml: str):
    return read_all(xml)[0]


def grid_of(xml: str) -> list[int]:
    import re
    g = re.search(r"<w:tblGrid>.*?</w:tblGrid>", xml, re.DOTALL)
    assert g is not None
    return [int(w) for w in
            re.findall(r'<w:gridCol w:w="(\d+)"/>', g.group(0))]


def spans_of(xml: str) -> list[list[int]]:
    """Every row's cell spans, as Word will read them."""
    import re
    out = []
    for tr in re.finditer(r"<w:tr\b.*?</w:tr>", xml, re.DOTALL):
        spans = []
        for tc in re.finditer(r"<w:tc>.*?</w:tc>", tr.group(0), re.DOTALL):
            m = re.search(r'<w:gridSpan w:val="(\d+)"/>', tc.group(0))
            spans.append(int(m.group(1)) if m else 1)
        out.append(spans)
    return out


# ------------------------------------------------------------------ the
# defect: three blocks of rows describing three columns three different
# ways. Column counts of 3, 5 and 7 rather than 1 and 2 — a wrong
# operator over small counts coincides with the right one too easily.

PHANTOM_GRID = [900, 300, 300, 300, 300, 300, 300, 300, 300, 700]


def phantom() -> str:
    """Ten grid columns describing a three-column table.

    Five rows put the boundary after grid column 4, three put it after
    5, and the widths differ in every block — which is the shift a
    reader sees.
    """
    rows = [row(cell("VARIABLES"), cell("Retired", span=4),
                cell("Disabled", span=5))]
    rows += [row(cell(f"var{i}"), cell(f"{i}.10", span=4),
                 cell(f"{i}.20", span=5)) for i in range(4)]
    rows += [row(cell(f"long label {i}", span=2), cell(f"{i}.30", span=3),
                 cell(f"{i}.40", span=5)) for i in range(3)]
    return tbl(PHANTOM_GRID, *rows)


def test_collapses_the_grid_to_the_real_column_count():
    xml = doc(phantom())
    out, rep = regrid(xml, only(xml))
    assert (rep.before, rep.after) == (10, 3)
    assert len(grid_of(out)) == 3


def test_every_row_lands_on_the_same_boundaries():
    """The defect itself: cell i must be column i on every row."""
    xml = doc(phantom())
    out, _ = regrid(xml, only(xml))
    assert spans_of(out) == [[1, 1, 1]] * 8


def test_reports_how_many_rows_disagreed():
    xml = doc(phantom())
    _, rep = regrid(xml, only(xml))
    # the five-row block is canonical; the three-row block is not
    assert rep.ragged == 3


def test_a_spanning_header_is_not_RAGGED():
    """Its cuts are a subset of the body's, so its cells DO line up.

    Counting it as ragged made every grouped table look broken — and,
    worse, made regrid rewrite tables that had nothing wrong with them.
    """
    grid = [900, 300, 700]
    header = row(cell(""), cell("Both", span=2))
    body = [row(cell(f"v{i}"), cell("a"), cell("b")) for i in range(4)]
    xml = doc(tbl(grid, header, *body))
    out, rep = regrid(xml, only(xml))

    assert rep.ragged == 0
    assert rep.snapped == ["Both"]      # mapped, but not a fault
    assert out == xml                   # and so: left alone


def test_new_columns_inherit_the_widths_they_replace():
    """Widths are carried, not invented — fit_columns is the sizer."""
    xml = doc(phantom())
    out, rep = regrid(xml, only(xml))
    assert rep.widths == [900, 1200, 1900]
    assert grid_of(out) == [900, 1200, 1900]
    assert sum(rep.widths) == sum(PHANTOM_GRID)


def test_cell_widths_are_restated_against_the_new_grid():
    xml = doc(phantom())
    out, _ = regrid(xml, only(xml))
    assert '<w:tcW w:w="1900" w:type="dxa"/>' in out
    assert '<w:tcW w:w="300" w:type="dxa"/>' not in out


def test_no_text_is_lost():
    xml = doc(phantom())
    out, _ = regrid(xml, only(xml))
    for label in ("VARIABLES", "Retired", "Disabled", "long label 2", "2.40"):
        assert label in out


def test_a_spanning_header_keeps_covering_its_columns():
    """A header row with FEWER cells is snapped, not mapped across."""
    header = row(cell(""), cell("Robust", span=4), cell("Clustered", span=5))
    body = [row(cell(f"v{i}"), cell("a", span=4), cell("b", span=5))
            for i in range(5)]
    xml = doc(tbl(PHANTOM_GRID, header, *body))
    out, rep = regrid(xml, only(xml))
    assert spans_of(out)[0] == [1, 1, 1]
    # one cell per column already: mapped across, nothing to snap
    assert rep.snapped == []


def test_a_header_spanning_several_real_columns_snaps_to_them():
    """Two group headers over six data columns become spans of 3."""
    grid = [900] + [300] * 6 + [700]
    header = row(cell(""), cell("Robust", span=3), cell("Clustered", span=4))
    body = [row(cell(f"v{i}"), cell("a"), cell("b"), cell("c"),
                cell("d"), cell("e"), cell("f"), cell("g"))
            for i in range(5)]
    xml = doc(tbl(grid, header, *body))
    out, rep = regrid(xml, only(xml))
    assert rep.after == 8
    assert spans_of(out)[0] == [1, 3, 4]
    # the report names the snapped row by its text, so a wrong snap can
    # be read back against the page rather than counted
    assert rep.snapped == ["RobustClustered"]


def test_idempotent_on_a_table_that_is_already_right():
    grid = [900, 1200, 1900]
    rows = [row(cell("a"), cell("b"), cell("c")) for _ in range(5)]
    xml = doc(tbl(grid, *rows))
    out, rep = regrid(xml, only(xml))
    assert out == xml
    assert (rep.before, rep.after, rep.ragged) == (3, 3, 0)


def test_running_it_twice_changes_nothing_the_second_time():
    xml = doc(phantom())
    once, _ = regrid(xml, only(xml))
    twice, rep = regrid(once, only(once))
    assert twice == once
    assert rep.ragged == 0


def test_regrid_then_fit_columns_sizes_by_content():
    """The pair: regrid decides the columns, fit_columns their widths."""
    xml = doc(phantom())
    out, _ = regrid(xml, only(xml))
    out, fit = fit_columns(out, only(out))
    assert len(fit.columns) == 3
    # the label column holds the longest text and must not be the
    # narrowest afterwards
    widths = [c.new for c in fit.columns]
    assert widths[0] == max(widths)


def test_a_row_with_more_cells_than_columns_is_refused():
    """Collapsing it would merge two cells and lose one's content."""
    grid = [900, 300, 300, 700]
    rows = [row(cell("a"), cell("b", span=2), cell("c")) for _ in range(4)]
    extra = row(cell("a"), cell("b"), cell("c"), cell("d"))
    xml = doc(tbl(grid, *rows, extra))
    with pytest.raises(AnchorError, match="no mapping can be inferred"):
        regrid(xml, only(xml))


def test_a_grid_the_rows_do_not_cover_is_refused():
    """Rows spanning 4 of 10 columns are not evidence of where the
    columns are, and rewriting the grid from them moves content."""
    grid = [900] * 10
    rows = [row(cell("a"), cell("b"), cell("c"), cell("d"))
            for _ in range(4)]
    xml = doc(tbl(grid, *rows))
    with pytest.raises(AnchorError, match="disagree by more than"):
        regrid(xml, only(xml))


def test_a_table_with_tracked_changes_is_refused():
    grid = [900, 300, 300, 700]
    rows = [row(cell("a"), cell("b", span=2), cell("c")) for _ in range(3)]
    rows.append(row(cell("x", span=2), cell("y"), cell("z")))
    marked = tbl(grid, *rows).replace(
        "<w:tr>", '<w:tr><w:trPr><w:ins w:id="9" w:author="A"/></w:trPr>', 1)
    xml = doc(marked)
    with pytest.raises(AnchorError, match="tracked changes"):
        regrid(xml, only(xml))


def test_a_table_with_no_grid_is_refused():
    pr = '<w:tblPr><w:tblW w:w="3000" w:type="dxa"/></w:tblPr>'
    rows = "".join(row(cell("a"), cell("b")) for _ in range(3))
    xml = doc(f"<w:tbl>{pr}{rows}</w:tbl>")
    with pytest.raises(AnchorError, match="no tblGrid"):
        regrid(xml, only(xml))


def test_span_is_dropped_rather_than_written_as_one():
    """`w:gridSpan w:val="1"` is the default; writing it is noise Word
    strips on its next save, which would make regrid non-idempotent."""
    xml = doc(phantom())
    out, _ = regrid(xml, only(xml))
    assert '<w:gridSpan w:val="1"/>' not in out


def test_a_nested_table_keeps_its_own_grid():
    """The outer regrid must not reach into a table inside a cell."""
    inner = tbl([500, 500], row(cell("i"), cell("j")))
    outer_rows = [row(cell("a"), cell("b", span=2), cell("c"))
                  for _ in range(4)]
    holder = (f"<w:tr>{cell('a')}"
              f"<w:tc><w:tcPr><w:gridSpan w:val=\"2\"/></w:tcPr>{inner}"
              f"<w:p w14:paraId=\"BB\"/></w:tc>{cell('c')}</w:tr>")
    xml = doc(tbl([900, 300, 300, 700], *outer_rows, holder))
    out, rep = regrid(xml, only(xml))
    assert rep.after == 3
    assert '<w:gridCol w:w="500"/>' in out       # the inner grid survived
