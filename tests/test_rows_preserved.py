"""Did a REORDER keep the rows it was given?

The question a row reorder raises, and the one a rendered diff cannot
answer: it reports "rows moved", which is what was asked for, so the eye
passes over the row whose values slipped a column.

Hit on AFI (2026-08-17, r3 task TE15.2): seven tables reordered into one
common country order, with a row-tuple multiset comparison against a
pre-edit snapshot as the acceptance criterion. With nothing in the
toolkit that meant snapshotting eleven tables to TSV and comparing by
hand.
"""
from __future__ import annotations

import pytest
from conftest import document, para, row, run, table

from docxkit.errors import AnchorError
from docxkit.tables import (
    read_all,
    row_signature,
    rows_preserved,
    tables_after,
)


def _doc(*rows_text: tuple[str, ...]) -> str:
    return document(table(*(row(*cells) for cells in rows_text)))


HEADER = ("Country", "50+", "60+")
DATA = [("Albania", "-0.6", "+1.7"),
        ("Croatia", "-0.7", "+1.6"),
        ("Serbia", "-0.4", "+1.9")]


def test_a_pure_REORDER_preserves_the_rows():
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(HEADER, DATA[2], DATA[0], DATA[1]))

    report = rows_preserved(before, after)

    assert report.ok
    assert report.format() == "rows preserved: 3 row(s), same multiset"


def test_a_cell_that_slipped_a_COLUMN_is_caught():
    """The failure a reorder actually produces: the row moves and one
    value stays behind, so both tables have the same cells and neither
    the row count nor the column totals change."""
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(HEADER, ("Albania", "+1.7", "-0.6"),
                           DATA[1], DATA[2]))

    report = rows_preserved(before, after)

    assert not report.ok
    assert report.lost == [("Albania", "-0.6", "+1.7")]
    assert report.gained == [("Albania", "+1.7", "-0.6")]


def test_the_report_NAMES_what_went_and_what_arrived():
    """On a thirty-row table "these two are not the same" is the whole
    finding, and the two rows are what a reader needs to see."""
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(HEADER, DATA[0], DATA[1],
                           ("Serbia", "-0.4", "+1.8")))

    text = rows_preserved(before, after).format()

    assert text.splitlines()[0] == "1 row(s) LOST, 1 GAINED (of 3 compared)"
    assert "  lost   ('Serbia', '-0.4', '+1.9')" in text
    assert "  gained ('Serbia', '-0.4', '+1.8')" in text


def test_a_LOST_row_is_reported_even_when_nothing_arrived():
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(HEADER, DATA[0], DATA[1]))

    report = rows_preserved(before, after)

    assert report.lost == [("Serbia", "-0.4", "+1.9")]
    assert report.gained == []
    # counted on the BEFORE side: "of 2 compared" would describe the
    # table that lost the row rather than the one it was lost from
    assert report.rows == 3
    assert "(of 3 compared)" in report.format()


def test_a_row_that_ARRIVED_is_a_finding_too():
    """Not only losses: a reorder that pasted a row twice, or brought a
    row in from the table above, leaves the paper claiming a country it
    has no estimate for."""
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(HEADER, *DATA, ("Bosnia", "-0.5", "+1.5")))

    report = rows_preserved(before, after)

    assert not report.ok
    assert report.lost == []
    assert report.gained == [("Bosnia", "-0.5", "+1.5")]


def test_the_report_is_FALSY_when_rows_changed():
    """So the caller can write `assert rows_preserved(a, b), report()`
    the way every other gate here reads."""
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(HEADER, DATA[0], DATA[1]))

    assert not rows_preserved(before, after)
    assert rows_preserved(before, before)


def test_TWO_identical_rows_are_two_rows():
    """A counter, not a set. A table listing the same country twice —
    two survey waves, two specifications — and a reorder that dropped
    one of them is exactly what this is for."""
    twice = [DATA[0], DATA[0], DATA[1]]
    before, = read_all(_doc(HEADER, *twice))
    after, = read_all(_doc(HEADER, DATA[0], DATA[1]))

    report = rows_preserved(before, after)

    assert report.lost == [("Albania", "-0.6", "+1.7")]


def test_a_HEADER_may_be_reworded_without_being_a_lost_row():
    """The header is not a row of data and a reorder does not touch it;
    including it would report every retitled column as a row loss."""
    before, = read_all(_doc(HEADER, *DATA))
    after, = read_all(_doc(("Country", "Aged 50+", "Aged 60+"), *DATA))

    assert rows_preserved(before, after).ok
    assert not rows_preserved(before, after, skip_header=False).ok


def test_WORD_typography_is_not_a_changed_row():
    """A round trip through Word turns a hyphen-minus into a typographic
    minus and straightens quotes; the shared glyph table folds those, as
    it does in compare and ingest."""
    before, = read_all(_doc(HEADER, ("Albania", "-0.6", "the “gap”")))
    after, = read_all(_doc(HEADER, ("Albania", "−0.6", 'the "gap"')))

    assert rows_preserved(before, after).ok


def test_a_row_whose_SPACING_changed_is_the_same_row():
    before, = read_all(_doc(HEADER, ("North  Macedonia", " -0.6 ", "+1.7")))
    after, = read_all(_doc(HEADER, ("North Macedonia", "-0.6", "+1.7")))

    assert rows_preserved(before, after).ok


def test_row_signature_counts_the_rows_it_compared():
    table_, = read_all(_doc(HEADER, *DATA))

    assert sum(row_signature(table_).values()) == 3
    assert sum(row_signature(table_, skip_header=False).values()) == 4


# ------------------------------------------- one caption, several tables ---

def _two_under_one_caption() -> str:
    return document(
        para(run("Table A3. Sensitivity"))
        + table(row("Country", "Value"), row("Albania", "0.31"))
        + table(row("Term", "Coefficient"), row("Age", "0.02")))


def test_tables_after_returns_EVERY_block_the_caller_declares():
    """One caption can front several w:tbl elements — AFI's Table A3 is
    a country-rowed table and a regression block — and by_caption
    addresses the first of them and says nothing about the second."""
    found = tables_after(_two_under_one_caption(), "Table A3.", count=2)

    assert [t.header for t in found] == [["Country", "Value"],
                                         ["Term", "Coefficient"]]


def test_tables_after_stops_at_the_count_it_was_given():
    """The tables after those are the NEXT exhibit's — nothing in the
    document says where a caption's group ends, which is why the count
    is the caller's to state."""
    xml = document(para(run("Table A3. Sensitivity"))
                   + table(row("Country", "Value"))
                   + table(row("Term", "Coefficient"))
                   + para(run("Table A4. Something else"))
                   + table(row("Wave", "N")))

    found = tables_after(xml, "Table A3.", count=2)

    assert [t.header for t in found] == [["Country", "Value"],
                                         ["Term", "Coefficient"]]


def test_tables_after_REFUSES_when_the_exhibit_lost_a_block():
    """The count is the point: an exhibit that loses a block fails here
    instead of quietly rewriting half of itself."""
    one = document(para(run("Table A3. Sensitivity"))
                   + table(row("Country", "Value")))

    with pytest.raises(AnchorError, match="followed by 1 table"):
        tables_after(one, "Table A3.", count=2)


def test_tables_after_needs_its_caption_to_exist():
    with pytest.raises(AnchorError, match="Table Z9"):
        tables_after(_two_under_one_caption(), "Table Z9.")


def test_tables_after_refuses_a_count_below_one():
    with pytest.raises(AnchorError, match="at least 1"):
        tables_after(_two_under_one_caption(), "Table A3.", count=0)


def test_tables_after_takes_the_tables_FOLLOWING_the_caption():
    """House convention: a table caption sits above its table."""
    xml = document(table(row("Earlier", "table"))
                   + para(run("Table A3. Sensitivity"))
                   + table(row("Country", "Value")))

    found = tables_after(xml, "Table A3.")

    assert found[0].header == ["Country", "Value"]
