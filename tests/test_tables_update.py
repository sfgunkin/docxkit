"""tables.update — regenerating a manuscript table from data.

The promise under test: values land in the right cells with the OLD
cell's printed shape (decimals, separators, minus glyph, significance
stars), formatting survives, nothing is silently padded or dropped, and
the report separates re-rendering from data that actually moved.
"""
from __future__ import annotations

from typing import ClassVar

import pytest
from conftest import NS, para, run

from docxkit.errors import AnchorError
from docxkit.tables import Table, read_all, update


def cell(text: str, *, styled: bool = False) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if styled else ""
    return (f"<w:tc><w:tcPr><w:shd w:fill=\"DDDDDD\"/></w:tcPr>"
            f"<w:p><w:r>{rpr}<w:t>{text}</w:t></w:r></w:p></w:tc>")


def table_xml(rows: list[list[str]], *, styled: bool = False) -> str:
    trs = "".join(
        "<w:tr>" + "".join(cell(c, styled=styled) for c in row) + "</w:tr>"
        for row in rows)
    return f"<w:tbl>{trs}</w:tbl>"


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def one_table(xml: str) -> Table:
    (t,) = read_all(xml)
    return t


BASE = doc(para(run("Table 1. Results"))
           + table_xml([["Country", "AFI", "Gap"],
                        ["Poland", "0.31", "1,234"],
                        ["Chile", "−0.62**", "5.0%"]]))


def test_values_land_in_the_right_cells():
    xml, changes = update(BASE, one_table(BASE),
                          [["Poland", 0.298, 1305],
                           ["Chile", -0.641, 6.02]])
    rows = one_table(xml).rows
    assert rows[1] == ["Poland", "0.30", "1,305"]
    assert rows[2] == ["Chile", "−0.64**", "6.0%"]
    assert len(changes) == 4                    # "Poland" was unchanged


def test_printed_shape_is_the_old_cells():
    xml, _ = update(BASE, one_table(BASE), [["Poland", 0.2984, 1304.6]])
    rows = one_table(xml).rows
    # two decimals because the old cell showed two; comma because the old
    # cell had one; the value is rounded, not truncated
    assert rows[1] == ["Poland", "0.30", "1,305"]


def test_minus_stays_typographic_and_stars_survive():
    xml, _ = update(BASE, one_table(BASE), [[-0.7012]], row0=2, col0=1)
    assert one_table(xml).rows[2][1] == "−0.70**"


def test_strings_are_written_verbatim_and_none_empties():
    xml, _ = update(BASE, one_table(BASE), [["Chile*", None]], row0=2)
    assert one_table(xml).rows[2][:2] == ["Chile*", ""]


def test_unchanged_cells_produce_no_edit_and_no_report_entry():
    xml, changes = update(BASE, one_table(BASE), [["Poland", 0.31]])
    assert changes == []
    assert one_table(xml).rows == one_table(BASE).rows


def test_a_value_that_rerenders_identically_is_not_a_change():
    # 0.312 prints as "0.31" in a two-decimal cell: same text, no entry.
    # That is the property the "expected no-op" workflow leans on.
    _, changes = update(BASE, one_table(BASE), [["Poland", 0.312, 1290]])
    assert [c.col for c in changes] == [2]


def test_moved_sizes_the_raw_jump_not_the_rounded_one():
    _, changes = update(BASE, one_table(BASE), [[0.316]], col0=1)
    (c,) = changes
    assert c.new == "0.32"
    # raw 0.316 against printed 0.31 - not the 0.01 the rendering shows
    assert c.moved == pytest.approx(0.006)


def test_cell_formatting_survives():
    styled = doc(table_xml([["h1", "h2"], ["a", "0.5"]], styled=True))
    xml, _ = update(styled, one_table(styled), [["b", 0.7]])
    assert xml.count("<w:b/>") == styled.count("<w:b/>")
    assert xml.count('w:fill="DDDDDD"') == styled.count('w:fill="DDDDDD"')


def test_a_dataframe_is_taken_directly():
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame([["Poland", 0.298, 1400]])
    xml, _ = update(BASE, one_table(BASE), frame)
    assert one_table(xml).rows[1] == ["Poland", "0.30", "1,400"]


def test_a_block_overrunning_the_rows_refuses():
    with pytest.raises(AnchorError, match="overruns table"):
        update(BASE, one_table(BASE), [["a"], ["b"], ["c"]])


def test_a_row_overrunning_the_columns_refuses():
    with pytest.raises(AnchorError, match="overrun"):
        update(BASE, one_table(BASE), [["a", "b", "c", "d"]])


def test_a_tracked_table_refuses():
    tracked = doc(
        "<w:tbl><w:tr><w:tc><w:p>"
        '<w:ins w:id="9" w:author="R"><w:r><w:t>0.5</w:t></w:r></w:ins>'
        "</w:p></w:tc></w:tr></w:tbl>")
    with pytest.raises(AnchorError, match="tracked changes"):
        update(tracked, one_table(tracked), [[0.6]], row0=0)


def test_empty_input_refuses():
    with pytest.raises(AnchorError, match="no rows"):
        update(BASE, one_table(BASE), [])


# --- what the first HONEST measurement found (2026-08-17, 12.9 %) -------
#
# The first run of this module reported 44.9 % with 216 survivors in
# `update`, because this file was not in the harness. With it in, the
# figure is 12.9 % and what is left in `update` is its REPORT: the
# coordinates each CellChange carries and the sentence the refusals
# print. A paper reads that report to check a regeneration — "13 cells
# changed, none by more than 0.01" is the whole verification — so a
# coordinate that is off by row0 is a check of the wrong cell.

def test_a_change_carries_the_cell_it_HAPPENED_IN():
    """Absolute row and column, not the offset within the block: a
    caller reading the report against its own data is looking at the
    table, where row 2 is row 2."""
    _xml, changes = update(BASE, one_table(BASE),
                           [["Chile", -0.641, 6.02]], row0=2, col0=0)

    assert [(c.row, c.col) for c in changes] == [(2, 1), (2, 2)]


def test_a_block_written_at_an_OFFSET_reports_the_real_columns():
    xml, changes = update(BASE, one_table(BASE), [[0.298], [-0.641]],
                          row0=1, col0=1)

    assert [(c.row, c.col) for c in changes] == [(1, 1), (2, 1)]
    assert one_table(xml).rows[1] == ["Poland", "0.30", "1,234"]


def test_a_change_reports_the_RAW_jump_and_the_printed_sides():
    """`moved` is the distance in the data, not in the rendering: a cell
    that prints 0.30 either way moved 0.002, and that is the number a
    reader gates on."""
    _xml, changes = update(BASE, one_table(BASE), [["Poland", 0.3, 1234]])

    (change,) = changes
    assert (change.old, change.new) == ("0.31", "0.30")
    assert change.moved == pytest.approx(0.01)


def test_the_row_overrun_refusal_names_the_ROW_and_both_counts():
    """The message is the finding: a vanished column means the data and
    the manuscript disagree, and which row it was seen in is where the
    reader starts."""
    with pytest.raises(AnchorError) as exc:
        update(BASE, one_table(BASE), [["a", "b", "c"], ["d", "e", "f", "g"]])

    assert "row 2 of table 0 has 3 cells; 4 values at column 0" in str(
        exc.value)


def test_the_block_overrun_refusal_counts_the_rows_it_would_need():
    with pytest.raises(AnchorError) as exc:
        update(BASE, one_table(BASE), [["a"], ["b"], ["c"]], row0=1)

    assert "block of 3 rows at row 1 overruns table 0, which has 3 rows" \
        in str(exc.value)


# --- what the _table_core run of 2026-08-18 found ------------------------
#
# `update` is the largest cluster left in the package at 32, and the
# three below are the ones a fixture cannot reach by accident: the row
# it writes into is `trs[row0 + i]`, and at the DEFAULT row0 of 1 with
# two rows, `1 << 1` is 2 — the same cell the addition names. Three rows
# at row 2 tell them apart.

TALL = doc(para(run("Table 1. Results"))
           + table_xml([["Country", "AFI", "Gap"],
                        ["Poland", "0.31", "1,234"],
                        ["Chile", "−0.62**", "5.0%"],
                        ["Kenya", "0.44", "2.1%"],
                        ["Nepal", "0.09", "0.4%"]]))


def test_a_MULTI_ROW_block_at_an_offset_lands_row_by_row():
    """`trs[row0 + i]`. At row0=1 with two rows every shift-shaped
    mutation coincides with the sum; at row0=2 with three they part, and
    a block written to rows 2, 4, 8 either overruns the table or
    overwrites the wrong countries — which is a results table saying
    something nobody computed."""
    xml, changes = update(TALL, one_table(TALL),
                          [[0.401], [0.402], [0.403]], row0=2, col0=1)

    rows = one_table(xml).rows
    # row 2's old cell carried significance stars, and they survive a
    # regeneration — which is the other half of what `update` promises
    assert [r[1] for r in rows] == ["AFI", "0.31", "0.40**", "0.40", "0.40"]
    assert [(c.row, c.col) for c in changes] == [(2, 1), (3, 1), (4, 1)]


def test_a_block_that_overruns_the_COLUMNS_from_an_offset_refuses():
    """`col0 + len(incoming) > len(tcs)`: three values starting at
    column 1 need four columns and the table has three. Written with a
    bitwise operator in place of the sum, `1 | 3` is 3 and the check
    passes — then the write runs off the end of the row."""
    with pytest.raises(AnchorError, match="overrun"):
        update(TALL, one_table(TALL), [[1, 2, 3]], row0=1, col0=1)


def test_the_row_and_column_offsets_are_KEYWORD_only():
    """Two small integers at a call site, and swapping them silently
    writes a block into the wrong quadrant of the table."""
    with pytest.raises(TypeError):
        update(TALL, one_table(TALL), [[0.4]], 2, 1)  # type: ignore[call-arg]


def test_an_object_with_VALUES_but_no_tolist_is_iterated_as_rows():
    """`values is not None and hasattr(values, "tolist")` — the pandas
    duck-type. Under `or`, anything carrying a `values` attribute (a
    mapping, a namedtuple, a paper's own wrapper) is asked for `.tolist`
    and raises inside docxkit rather than being read as the rows it is."""
    class Wrapper:
        values: ClassVar[list[list[str]]] = [["not", "the", "rows"]]

        def __iter__(self):
            return iter([[0.401]])

    xml, changes = update(TALL, one_table(TALL), Wrapper(),
                          row0=2, col0=1)

    assert one_table(xml).rows[2][1] == "0.40**"
    assert [(c.row, c.col) for c in changes] == [(2, 1)]


# --- the _table_core run of 2026-08-20, the update half ----------------


def test_the_block_lands_at_the_COLUMN_it_was_given():
    """`tcs[col0 + j]` and the `col0 + j` the change record carries.
    Every other way of combining two small numbers agrees with `+` when
    one of them is 0 — which `col0` is by default and `j` is on the
    first value of a row — so a block written at column 1 is the
    smallest fixture that can tell them apart.

    Written with `|`, the second value overwrites the first cell and the
    third column keeps its old text; recorded with `^`, the report names
    a column the value did not land in."""
    xml = doc(table_xml([["Country", "AFI", "Gap"],
                         ["Poland", "0.31", "1.20"],
                         ["Chile", "0.62", "3.40"]]))

    out, changes = update(xml, one_table(xml), [["0.98", "7.60"]],
                          row0=1, col0=1)

    assert one_table(out).rows[1] == ["Poland", "0.98", "7.60"]
    assert [(c.row, c.col) for c in changes] == [(1, 1), (1, 2)]


def test_an_overrunning_row_is_named_by_ITS_OWN_number():
    """`row {row0 + i}`. The refusal has to say which row is short or a
    reader goes looking in the wrong one, and `row0 << i` gives the same
    number as `row0 + i` whenever `row0` is 1 — the default, and the
    only value the earlier fixtures used. A block starting at row 2
    separates them."""
    xml = doc(table_xml([["Country", "AFI"],
                         ["Poland", "0.31"],
                         ["Chile", "0.62"],
                         ["Peru"]]))

    with pytest.raises(AnchorError, match="row 3 of table 0 has 1 cells"):
        update(xml, one_table(xml), [["0.5"], ["0.6"]], row0=2, col0=1)
