"""tables.update — regenerating a manuscript table from data.

The promise under test: values land in the right cells with the OLD
cell's printed shape (decimals, separators, minus glyph, significance
stars), formatting survives, nothing is silently padded or dropped, and
the report separates re-rendering from data that actually moved.
"""
from __future__ import annotations

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
