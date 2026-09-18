"""Table reading — including from a redline, which python-docx cannot do."""
from __future__ import annotations

import pytest
from conftest import dele, document, ins, para, row, run, table

from docxkit.errors import AnchorError
from docxkit.revisions import FINAL, ORIGINAL
from docxkit.tables import (
    by_caption,
    find,
    parse_number,
    read_all,
    set_cell,
    tolerance_for,
)


def _doc():
    return document(
        para(run("Table 4. Decomposition"))
        + table(row("Country", "AFI (initial)", "Dif."),
                row("Poland", "0.31", "0.02"),
                row("Romania", "0.28", "-0.01"))
        + para(run("Source: authors."))
        + table(row("Occupation", "Score"), row("Clerks", "1.43")))


def test_reads_every_table_as_rows():
    tables = read_all(_doc())
    assert len(tables) == 2
    assert tables[0].header == ["Country", "AFI (initial)", "Dif."]
    assert tables[0].rows[1] == ["Poland", "0.31", "0.02"]
    assert tables[0].shape == (3, 3)


def test_find_matches_header_substrings():
    """Matching on substrings survives a footnote marker or a wrapped
    header cell, which exact equality would not."""
    tables = read_all(_doc())
    assert find(tables, ["Country", "AFI"]).index == 0
    assert find(tables, ["Occupation"]).index == 1


def test_find_raises_when_no_table_matches():
    with pytest.raises(AnchorError, match="no table with header"):
        find(read_all(_doc()), ["Nonexistent"])
    assert find(read_all(_doc()), ["Nonexistent"], required=False) is None


def test_by_caption_takes_the_table_below_the_caption():
    """House convention: a table caption sits ABOVE its table."""
    assert by_caption(_doc(), "Table 4.").index == 0


def test_by_caption_raises_for_an_unknown_caption():
    with pytest.raises(AnchorError, match="no paragraph containing caption"):
        by_caption(_doc(), "Table 99.")


def test_column_and_row_accessors():
    t = read_all(_doc())[0]
    assert t.column(0) == ["Poland", "Romania"]
    assert t.row_named("Romania") == ["Romania", "0.28", "-0.01"]
    assert t.row_named("Absent") is None


def test_reads_a_tracked_table_on_both_sides():
    """The bug this prevents: python-docx renders a cell whose text is a
    tracked insertion as EMPTY, so a redline table silently loses every
    changed cell."""
    xml = document(table(
        row("Country"),
        "<w:tr><w:tc>" + para(dele("Dif."), ins("Difference"))
        + "</w:tc></w:tr>"))
    assert read_all(xml, view=FINAL)[0].rows[1] == ["Difference"]
    assert read_all(xml, view=ORIGINAL)[0].rows[1] == ["Dif."]


def test_read_all_rejects_an_unknown_view():
    with pytest.raises(ValueError, match="final"):
        read_all(_doc(), view="sideways")


def test_cell_text_joins_wrapped_paragraphs():
    xml = document("<w:tbl><w:tr><w:tc>" + para(run("Labourers in Mining,"))
                   + para(run("Construction")) + "</w:tc></w:tr></w:tbl>")
    assert read_all(xml)[0].rows[0] == ["Labourers in Mining, Construction"]


@pytest.mark.parametrize(("text", "expected"), [
    ("0.31", 0.31),
    ("-0.01", -0.01),
    ("−0.147", -0.147),          # typographic minus, as Word writes it
    ("+0.056", 0.056),
    ("39%", 39.0),
    ("−0.623** [0.038]", -0.623),  # stars and a bracketed p-value
    ("1,234.5", 1234.5),
    # the thousands separator the docstring promises and no case here
    # asked for until 2026-09-18: the no-break space Word writes, and
    # the plain space a paste leaves behind. (With a decimal COMMA after
    # it — "1 234,5", as a Russian table writes it — the answer is
    # 12345.0, which is filed rather than pinned here.)
    ("1 234.5", 1234.5),
    ("1 234.5", 1234.5),
    ("", None),
    ("—", None),                  # em dash means "not applicable"
    ("n/a", None),
])
def test_parse_number_handles_what_these_tables_contain(text, expected):
    assert parse_number(text) == expected


def test_numbers_maps_the_whole_table():
    nums = read_all(_doc())[0].numbers()
    assert nums[0] == [None, None, None]      # header row
    assert nums[1] == [None, 0.31, 0.02]


def test_tolerance_follows_the_rendered_precision():
    """A cell printed as 0.31 could be anything in [0.305, 0.315)."""
    assert tolerance_for(2) == 0.005
    assert tolerance_for(3) == 0.0005
    assert abs(0.3149 - 0.31) < tolerance_for(1)


def test_set_cell_rewrites_one_cell_only():
    xml = _doc()
    t = read_all(xml)[0]
    out = set_cell(xml, t, 0, 2, "Difference")
    after = read_all(out)[0]
    assert after.header == ["Country", "AFI (initial)", "Difference"]
    assert after.rows[1] == ["Poland", "0.31", "0.02"]   # untouched


def test_set_cell_preserves_the_cell_formatting():
    xml = document(table(row("Country"), row("Poland")))
    styled = xml.replace("<w:t>Poland</w:t>",
                         '<w:t>Poland</w:t></w:r><w:r><w:rPr><w:b/></w:rPr>'
                         "<w:t></w:t>")
    t = read_all(styled)[0]
    out = set_cell(styled, t, 1, 0, "Romania")
    assert "<w:b/>" in out
    assert read_all(out)[0].rows[1] == ["Romania"]


def test_set_cell_rejects_an_out_of_range_target():
    xml = _doc()
    t = read_all(xml)[0]
    with pytest.raises(AnchorError, match="cannot set row"):
        set_cell(xml, t, 99, 0, "x")
    with pytest.raises(AnchorError, match="cannot set column"):
        set_cell(xml, t, 0, 99, "x")
