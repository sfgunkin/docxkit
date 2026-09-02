r"""A tracked COLUMN deletion never passed the accept gate.

Measured on Aging_Well R79, 2026-09-02. A batch drops Table 1's third
column. Word's Compare serializes it correctly and CELL-WISE: every row
keeps its third `w:tc`, marked `w:cellDel` in its `w:tcPr` with the
content inside `w:del`, and the author sees a struck column.
`revisions.accept` walked the `w:del` and not the cell, so it removed
the content and left the emptied cell and its empty `<w:p>` standing —
four paragraphs the clean copy does not have, and `tracked.build`'s
accept gate refused:

    UNACCEPTED body ¶44: intended ''  accepted ''   (and ¶47, ¶50, ¶53)

Word's OWN accept was right all along: AcceptAllRevisions on the same
batch compares CLEAN against the clean edit on every content layer. So
the deliverable was never harmed — the gap was in this module's XML
approximation of Word's accept, the same family as the footnote-deletion
shells `footnotes.prune_orphans` cleans up.

The fixture at the bottom is the real thing: the shape is taken from
that redline, including the two facts that make the naive fix wrong —
the `w:tcPrChange` snapshot carries its OWN `w:cellDel`, and the live
one is carried across a reject beside it.
"""
from __future__ import annotations

import re

from docxkit import revisions

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
      '2006/main"')
WHEN = 'w:author="Michael Lokshin" w:date="2026-09-02T00:37:00Z"'


def cell(text: str, *, mark: str = "", change: str = "",
         span: int = 1) -> str:
    """One `w:tc`. `mark` is `cellDel`/`cellIns`; `change` a snapshot."""
    flag = f'<w:{mark} w:id="56" {WHEN}/>' if mark else ""
    grid = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
    snap = (f'<w:tcPrChange w:id="55" {WHEN}><w:tcPr>'
            f'<w:tcW w:w="1895" w:type="dxa"/>{change}</w:tcPr>'
            f"</w:tcPrChange>" if change is not None and change != "" else "")
    body = (f'<w:del w:id="57" {WHEN}><w:r>'
            f"<w:delText>{text}</w:delText></w:r></w:del>"
            if mark == "cellDel"
            else f"<w:r><w:t>{text}</w:t></w:r>")
    return (f'<w:tc><w:tcPr><w:tcW w:w="1895" w:type="dxa"/>{grid}{flag}'
            f"{snap}</w:tcPr><w:p>{body}</w:p></w:tc>")


def table(rows: list[list[str]], *, cols: int | None = None) -> str:
    grid = "".join('<w:gridCol w:w="1895"/>'
                   for _ in range(cols if cols is not None else len(rows[0])))
    body = "".join(f"<w:tr>{''.join(r)}</w:tr>" for r in rows)
    return (f"<w:document {NS}><w:body><w:tbl>"
            f"<w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl></w:body>"
            f"</w:document>")


def deleted_column(*, change: str = "") -> str:
    """Word's shape for "drop the third column of a 3-column table"."""
    return table([[cell(f"r{i}c0"), cell(f"r{i}c1"),
                   cell(f"r{i}c2", mark="cellDel", change=change)]
                  for i in range(4)])


def shape(xml: str) -> tuple[int, int, int, int]:
    """(rows, cells in row 0, gridCol, w:p)."""
    rows = re.findall(r"<w:tr\b[^>]*(?<!/)>.*?</w:tr>", xml, re.DOTALL)
    first = re.findall(r"<w:tc>.*?</w:tc>", rows[0], re.DOTALL) if rows else []
    return (len(rows), len(first), xml.count("<w:gridCol"),
            len(re.findall(r"<w:p[ >]", xml)))


# ------------------------------------------------------------- accepting


def test_accepting_a_deleted_column_removes_the_CELLS():
    """4 rows x 3 cells with one column struck, and 12 paragraphs; the
    clean copy has 4 x 2 and 8."""
    assert shape(deleted_column()) == (4, 3, 3, 12)

    assert shape(revisions.accept(deleted_column())) == (4, 2, 2, 8)


def test_the_emptied_cell_was_the_whole_defect():
    """Before the fix the content went and the cell stayed, so the
    accepted view had a paragraph per row that the clean copy did not —
    which is exactly what the gate reported, as `intended '' accepted ''`."""
    accepted = revisions.accept(deleted_column())

    assert "<w:cellDel" not in accepted
    assert "r0c2" not in accepted
    assert accepted.count("<w:p>") == 8


def test_the_GRID_loses_a_column_with_the_cells():
    """A `w:tblGrid` declaring three columns for rows that lay out two is
    a phantom column."""
    assert revisions.accept(deleted_column()).count("<w:gridCol") == 2


def test_a_gridSpan_cell_takes_its_whole_SPAN_out_of_the_grid():
    """A merged cell occupies several grid columns, and removing one
    entry for it would leave the table one column wide of its rows."""
    wide = table([[cell("keep"), cell("gone", mark="cellDel", span=2)]
                  for _ in range(2)], cols=3)

    assert shape(wide) == (2, 2, 3, 4)
    assert shape(revisions.accept(wide)) == (2, 1, 1, 2)


# ------------------------------------------------------------- rejecting


def test_rejecting_keeps_the_cell_and_drops_the_MARK():
    rejected = revisions.reject(deleted_column())

    assert shape(rejected) == (4, 3, 3, 12)
    assert "<w:cellDel" not in rejected, "the view still reports a revision"
    assert "r0c2" in rejected


def test_the_tcPrChange_SNAPSHOT_carries_its_own_cellDel():
    """The fact that decided where this pass runs. Word records the
    cell's pre-change properties INCLUDING its delete mark, so a reject
    that restores the snapshot puts back a flag stripped before it — and
    `_OUTSIDE_SNAPSHOT` carries the live one across beside it, so there
    can be TWO. Removing the first of a pair leaves the view reporting a
    revision that has been rejected.

    Taken from the real redline, whose marked cells all carry one.
    """
    with_snapshot = deleted_column(change=f'<w:cellDel w:id="56" {WHEN}/>')

    assert with_snapshot.count("<w:cellDel") == 8      # live + snapshot

    rejected = revisions.reject(with_snapshot)

    assert "<w:cellDel" not in rejected
    assert shape(rejected) == (4, 3, 3, 12)


def test_accepting_a_cell_with_that_snapshot_still_removes_it():
    accepted = revisions.accept(
        deleted_column(change=f'<w:cellDel w:id="56" {WHEN}/>'))

    assert shape(accepted) == (4, 2, 2, 8)
    assert "<w:cellDel" not in accepted


# ------------------------------------------------------- inserted cells


def test_an_INSERTED_cell_goes_on_reject_and_stays_on_accept():
    """`w:cellIns` is the mirror, and a handler that read only the
    deletion would leave a rejected column standing."""
    added = table([[cell(f"r{i}c0"), cell(f"r{i}c1", mark="cellIns")]
                   for i in range(3)])

    assert shape(revisions.reject(added)) == (3, 1, 1, 3)
    kept = revisions.accept(added)
    assert shape(kept) == (3, 2, 2, 6)
    assert "<w:cellIns" not in kept, "the surviving side keeps no markup"


# ----------------------------------------------------- what it leaves be


def test_a_RAGGED_deletion_takes_its_cells_and_leaves_the_grid():
    """Cells deleted at different grid positions in different rows are
    an edit, not a column. There is no column to remove, and guessing
    one would corrupt the geometry of a table that is merely edited."""
    ragged = table([[cell("a", mark="cellDel"), cell("b"), cell("c")],
                    [cell("d"), cell("e"), cell("f", mark="cellDel")]])

    accepted = revisions.accept(ragged)

    assert shape(accepted) == (2, 2, 3, 4), "cells gone, grid untouched"


def test_a_table_with_no_cell_revisions_is_untouched():
    plain = table([[cell("a"), cell("b")], [cell("c"), cell("d")]])

    assert shape(revisions.accept(plain)) == (2, 2, 2, 4)
    assert shape(revisions.reject(plain)) == (2, 2, 2, 4)


def test_a_cellMerge_is_deliberately_left_alone():
    """It records a merge or a split, not an appearance — applying it
    means recomputing `gridSpan` and `vMerge` across the row, which is a
    different operation with a different failure mode, and no manuscript
    in the corpus carries one to measure against."""
    merged = table([[cell("a", mark="cellMerge"), cell("b")]])

    assert shape(revisions.accept(merged)) == (1, 2, 2, 2)


# ------------------------------------------------------- the predicate


def test_a_WHERE_predicate_decides_a_cell_like_any_other_revision():
    from docxkit.revisions import by_author

    both = table([[cell("keep"),
                   cell("mine", mark="cellDel")]])
    other = both.replace('w:author="Michael Lokshin"', 'w:author="Someone"')

    assert shape(revisions.accept(both, where=by_author(
        "Michael Lokshin"))) == (1, 1, 1, 1)
    assert shape(revisions.accept(other, where=by_author(
        "Michael Lokshin"))) == (1, 2, 2, 2)
