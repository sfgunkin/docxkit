"""What `plan_booktabs` reads off a table, rule by rule.

The heuristic decides where every rule in a three-line table goes, and
the mutation pass put 78 survivors on it — 44 of them on the single
boolean that recognises a panel. It was reached by the existing tests
and asserted by almost none of them: they check that `booktabs` draws
SOMETHING, not that the shape it inferred is the right one.

Each rule below is one the module states in prose. Stating them as
tests is the difference between "the inference ran" and "the inference
is the one documented".
"""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit import tables


def tbl(rows: list[list[str]], *, width: int | None = None) -> str:
    cols = width or max(len(r) for r in rows)
    grid = "".join('<w:gridCol w:w="1000"/>' for _ in range(cols))
    trs = ""
    for row in rows:
        cells = "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="1000" w:type="dxa"/></w:tcPr>'
            f"<w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
        trs += f"<w:tr>{cells}</w:tr>"
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{1000 * cols}" '
            f'w:type="dxa"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
            f"{trs}</w:tbl>")


def plan_of(rows: list[list[str]], *, width: int | None = None):
    xml = (f"<w:document {NS}><w:body>{tbl(rows, width=width)}"
           f"</w:body></w:document>")
    return tables.plan_booktabs(tables.read_all(xml)[0])


# --------------------------------------------------------- the header ----
# "The header is the run of leading rows with an EMPTY first cell — every
# one of these papers labels its stub column only from the first data row
# down."


def test_the_header_is_the_run_of_rows_with_an_empty_stub():
    plan = plan_of([["", "(1)", "(2)"],
                    ["", "OLS", "IV"],
                    ["Age", "0.1", "0.2"]])
    assert plan.header_rows == 2


def test_a_table_whose_stub_is_filled_from_the_top_still_gets_one_header():
    """`max(header, 1)`. Most academic tables have a header row; a table
    that does not is the case `booktabs(plan=...)` exists to state."""
    plan = plan_of([["Age", "0.1"], ["Income", "0.2"]])
    assert plan.header_rows == 1


def test_the_count_starts_at_the_FIRST_row():
    """`header = 0`, then the walk. Starting the count at 1 skips the
    check of row 0 — so a table whose first row IS labelled and whose
    second is not (a stub label over a spanning group head, which is how
    a panelled table opens) reads as having two header rows, and the mid
    rule lands under the group instead of over it."""
    plan = plan_of([["Country", "AFI", "Dif."],
                    ["", "2020", "2024"],
                    ["Albania", "0.31", "0.02"]])

    assert plan.header_rows == 1


def test_every_row_having_an_empty_stub_does_not_run_off_the_end():
    plan = plan_of([["", "a"], ["", "b"]])
    assert plan.header_rows == 2


# ---------------------------------------------------- the group heads ----
# A header row that SPANS carries fewer cells than the table is wide. The
# LAST header row gets the full mid rule instead, so it is never a
# cmidrule row however it is built.


def test_a_short_header_row_with_content_is_a_group_head():
    plan = plan_of([["", "Discipline"],
                    ["", "(1)", "(2)"],
                    ["Age", "0.1", "0.2"]], width=3)
    assert plan.group_rows == [0]


def test_the_last_header_row_is_never_a_group_head():
    """It carries the mid rule that closes the header block, and a
    cmidrule under the same edge draws a rule on top of a rule."""
    plan = plan_of([["", "Discipline"],
                    ["Age", "0.1", "0.2"]], width=3)
    assert plan.group_rows == []


def test_a_short_header_row_with_no_content_is_not_a_group_head():
    """A rule under an empty cell is a rule under nothing."""
    plan = plan_of([["", ""],
                    ["", "(1)", "(2)"],
                    ["Age", "0.1", "0.2"]], width=3)
    assert plan.group_rows == []


def test_a_full_width_header_row_is_not_spanning_anything():
    """`len(row) < width` — a header row with a cell per column spans no
    group, so a cmidrule under it would be a second full-width rule
    directly above the mid rule."""
    plan = plan_of([["", "(1)", "(2)"],
                    ["", "OLS", "IV"],
                    ["Age", "0.1", "0.2"]])
    assert plan.group_rows == []


# --------------------------------------------------------- the panels ----
# A panel opens with a label and no values beside it.


def test_a_label_with_no_values_beside_it_opens_a_panel():
    plan = plan_of([["", "(1)"],
                    ["Age", "0.1"],
                    ["Kyrgyzstan", ""],
                    ["Income", "0.3"]])
    assert plan.panel_rows == [2]


def test_a_label_only_last_row_opens_nothing():
    """There is no panel below it to open, and the bottom rule is already
    going there."""
    plan = plan_of([["", "(1)"],
                    ["Age", "0.1"],
                    ["Notes", ""]])
    assert plan.panel_rows == []


def test_a_heading_and_its_first_panel_are_one_boundary_not_two():
    """"Panel A" then "Kyrgyzstan" — two label-only rows in a row. A rule
    between them rules off nothing, so only the first opens a panel."""
    plan = plan_of([["", "(1)"],
                    ["Age", "0.1"],
                    ["Panel A", ""],
                    ["Kyrgyzstan", ""],
                    ["Income", "0.3"]])
    assert plan.panel_rows == [2]


def test_the_first_panel_of_a_table_with_no_real_header_still_opens():
    """`i > header`, not `>=`. When the stub is filled from row 0 the
    header is FORCED to 1, so the first data row IS row `header` — and
    the guard must not read row 0 as a heading standing above it."""
    plan = plan_of([["Panel A", ""],
                    ["Kyrgyzstan", ""],
                    ["Age", "0.1"]])
    assert plan.panel_rows == [1]


def test_two_panels_separated_by_data_are_both_found():
    plan = plan_of([["", "(1)"],
                    ["Kyrgyzstan", ""],
                    ["Age", "0.1"],
                    ["Uzbekistan", ""],
                    ["Age", "0.2"]])
    assert plan.panel_rows == [1, 3]


def test_a_row_with_values_beside_its_label_is_not_a_panel():
    plan = plan_of([["", "(1)"],
                    ["Age", "0.1"],
                    ["Income", "0.2"]])
    assert plan.panel_rows == []


# ---------------------------------------------------- the summary block --
# "Every summary block, not just the last: a panelled table repeats N and
# the cluster count under each panel."


def test_the_summary_block_starts_at_its_first_row_only():
    plan = plan_of([["", "(1)"],
                    ["Age", "0.1"],
                    ["Observations", "1200"],
                    ["R-squared", "0.34"]])
    assert plan.stats_rows == [2]


def test_a_panelled_table_gets_a_rule_above_every_summary_block():
    plan = plan_of([["", "(1)"],
                    ["Age", "0.1"],
                    ["Observations", "1200"],
                    ["Income", "0.2"],
                    ["Observations", "900"]])
    assert plan.stats_rows == [2, 4]


@pytest.mark.parametrize("label", ["Observations", "N. of obs",
                                   "R-squared", "Clusters", "F-stat",
                                   "Mean of dependent variable"])
def test_the_labels_a_summary_block_opens_with(label):
    plan = plan_of([["", "(1)"], ["Age", "0.1"], [label, "1"]])
    assert plan.stats_rows == [2], f"{label!r} did not open a summary block"


def test_a_regressor_named_like_prose_does_not_open_one():
    plan = plan_of([["", "(1)"], ["Age", "0.1"], ["Observed care", "0.2"]])
    assert plan.stats_rows == []


# ------------------------------------- a span constrains by its longest --
# "A spanning cell is almost always a group header, and a header wraps for
# one line per TABLE where a body label wraps for one line per ROW — so
# spans constrain only by their unbreakable minimum, never by their full
# one-line width."


def spanned(head: str) -> str:
    span = ('<w:tc><w:tcPr><w:tcW w:w="2000" w:type="dxa"/>'
            '<w:gridSpan w:val="2"/></w:tcPr>'
            f"<w:p><w:r><w:t>{head}</w:t></w:r></w:p></w:tc>")
    def cell(text, w=1000):
        return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")
    body = ('<w:tbl><w:tblPr><w:tblW w:w="4000" w:type="dxa"/></w:tblPr>'
            '<w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="1000"/>'
            '<w:gridCol w:w="1000"/></w:tblGrid>'
            "<w:tr>" + cell("", 2000) + span + "</w:tr>"
            "<w:tr>" + cell("A label that wraps", 2000)
            + cell("-0.25***") + cell("0.04") + "</w:tr></w:tbl>")
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def test_a_longer_group_head_does_not_steal_the_label_column():
    """Both heads share the longest WORD, so the unbreakable minimum is
    the same and the fit should be identical. Constraining by the full
    one-line width instead was measured to take ~250 dxa per pair off the
    label column — which then wraps once per ROW to save the header
    wrapping once per TABLE."""
    short = tables.fit_columns(spanned("discipline"),
                               tables.read_all(spanned("discipline"))[0])[1]
    long_head = spanned("Extremely nonviolent discipline")
    wide = tables.fit_columns(long_head,
                              tables.read_all(long_head)[0])[1]
    assert [c.new for c in short.columns] == [c.new for c in wide.columns]


def test_a_spacer_under_a_span_pays_its_own_share_of_the_head():
    """`- fixed`, not `+ fixed`.

    A spacer column keeps its width whatever happens, so the width it
    already contributes is part of what the group head has to sit over.
    Charging the FILLED columns for it as well demands twice the spacer's
    width more than the head needs, and every dxa of that comes out of
    the label column.
    """
    import math

    from docxkit._table_layout import _cell_extents, _column_needs

    # the head must be WIDER than its columns' own content, or `_bump`
    # sees no deficit, returns early, and the sign is never exercised
    span_text = "Nonviolentdisciplinemeasure"
    spacer = 300
    grid = [2000, 1000, spacer, 1000]
    head = ('<w:tc><w:tcPr><w:tcW w:w="2300" w:type="dxa"/>'
            '<w:gridSpan w:val="3"/></w:tcPr>'
            f"<w:p><w:r><w:t>{span_text}</w:t></w:r></w:p></w:tc>")

    def cell(text: str, w: int) -> str:
        return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")

    body = ('<w:tbl><w:tblPr><w:tblW w:w="4300" w:type="dxa"/></w:tblPr>'
            "<w:tblGrid>"
            + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
            + "</w:tblGrid><w:tr>" + cell("", 2000) + head + "</w:tr>"
            "<w:tr>" + cell("Label", 2000) + cell("1", 1000)
            + cell("", spacer) + cell("2", 1000) + "</w:tr></w:tbl>")

    side, pad = 216, 1.05
    need_h, _, _, filled = _column_needs(body, grid, side, pad)
    assert not filled[2], "column 2 should read as a spacer"

    hard, _, _ = _cell_extents(head, ("Times New Roman", 24))
    demanded = math.ceil(hard * pad) + side
    # `_bump` grows the filled columns to exactly what the head needs
    # LESS what the spacer already holds. Adding it instead asks for
    # 2 x 300 dxa more than the head does, out of the label column.
    assert sum(need_h[c] for c in (1, 3)) == demanded - spacer


def test_the_group_head_still_sets_a_floor_for_its_own_columns():
    """Not ignored — constrained by the longest unbreakable word."""
    narrow = spanned("x")
    wide = spanned("supercalifragilistic")
    a = tables.fit_columns(narrow, tables.read_all(narrow)[0])[1]
    b = tables.fit_columns(wide, tables.read_all(wide)[0])[1]
    assert sum(c.new for c in b.columns[1:]) > \
        sum(c.new for c in a.columns[1:])


def test_a_plain_column_needs_its_TEXT_times_pad_plus_the_margins():
    """`math.ceil(width * pad) + side`, for a column no span touches.

    The test beside this one reads columns a group head BUMPED, and the
    bump overwrites what this expression computed — so five mutants
    lived on these two lines, `* pad` as `+ pad` and `/ pad` among them.

    `pad` is a multiplier because the slack a column needs scales with
    its text: at 1.05 a 2000 dxa label gets 100 dxa and a one-character
    cell gets 10. Added instead, every column gets the same 1 dxa, the
    widest column loses ~100, and its longest word wraps — which is the
    thing the whole measurement exists to prevent.

    `hard` and `full` differ here on purpose: the hard need is the
    longest unbreakable WORD, the full need is the whole line, and a
    fixture of one word cannot tell the two lists apart.
    """
    import math

    from docxkit._table_layout import _cell_extents, _column_needs

    def cell(text: str, w: int) -> str:
        return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")

    label = "Nonviolent discipline"          # two words: hard < full
    grid = [3000, 1000]
    body = ('<w:tbl><w:tblPr><w:tblW w:w="4000" w:type="dxa"/></w:tblPr>'
            "<w:tblGrid>"
            + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
            + "</w:tblGrid><w:tr>" + cell(label, 3000) + cell("1", 1000)
            + "</w:tr></w:tbl>")
    side, pad = 216, 1.05

    need_h, need_f, driver, filled = _column_needs(body, grid, side, pad)

    hard, full, text = _cell_extents(cell(label, 3000),
                                     ("Times New Roman", 24))
    assert hard < full, "the fixture has to tell the two needs apart"
    assert (driver[0], filled[0]) == (text, True)
    assert need_h[0] == math.ceil(hard * pad) + side
    assert need_f[0] == math.ceil(full * pad) + side


def test_a_LAST_row_that_is_only_a_label_opens_no_panel():
    """A panel rule under the last row rules off nothing — the row it
    would separate from what follows has nothing following it.

    An EVEN row count is what this needs: `i != len(rows) - 1` read as
    `len(rows) ^ 1` is the same number for an odd count, so a
    three-row or five-row fixture cannot tell the two apart. The
    contrast below is the same table with one more row under it, where
    the label row IS a panel."""
    rows = [["", "A", "B"], ["x", "1", "2"], ["y", "3", "4"],
            ["Trailing label", "", ""]]
    assert len(rows) % 2 == 0, "an odd count hides the reading this pins"

    assert plan_of(rows).panel_rows == []
    assert plan_of([*rows, ["z", "5", "6"]]).panel_rows == [3]
