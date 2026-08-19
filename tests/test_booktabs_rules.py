"""Which cell gets which rule, and which column gets which alignment.

`plan_booktabs` reads a table's shape and is now pinned rule by rule.
This is the other half: the loop that turns that shape into edges. The
re-run left 45 survivors here and none of them moved when the inference
was pinned, so they are about the DRAWING, not the reading.

Every edge is stated explicitly — an omitted one inherits whatever the
table style says, and these manuscripts are full of styles that draw a
box — so a cell's four edges are readable, and that is what these
assert.
"""
from __future__ import annotations

import re

import pytest
from conftest import NS

from docxkit import tables
from docxkit._table_layout import _column_needs, _divide, _side_margins
from docxkit.tables import read_all

CELL_RE = re.compile(r"<w:tc>.*?</w:tc>", re.DOTALL)
ROW_RE = re.compile(r"<w:tr>.*?</w:tr>", re.DOTALL)


def tbl(rows: list[list[str]], *, width: int | None = None,
        spans: dict[tuple[int, int], int] | None = None) -> str:
    cols = width or max(len(r) for r in rows)
    grid = "".join('<w:gridCol w:w="1000"/>' for _ in range(cols))
    trs = ""
    for i, row in enumerate(rows):
        cells = ""
        for j, text in enumerate(row):
            span = (spans or {}).get((i, j))
            pr = '<w:tcW w:w="1000" w:type="dxa"/>'
            if span:
                pr += f'<w:gridSpan w:val="{span}"/>'
            cells += (f"<w:tc><w:tcPr>{pr}</w:tcPr>"
                      f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")
        trs += f"<w:tr>{cells}</w:tr>"
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{1000 * cols}" '
            f'w:type="dxa"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
            f"{trs}</w:tbl>")


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def ruled(rows: list[list[str]], **kw) -> list[list[dict[str, str]]]:
    """`booktabs` applied; each row as a list of {side: val} per cell."""
    xml = doc(tbl(rows, width=kw.pop("width", None),
                  spans=kw.pop("spans", None)))
    out, _ = tables.booktabs(xml, read_all(xml)[0], **kw)
    got = []
    for tr in ROW_RE.finditer(out[out.index("<w:tbl>"):]):
        row = []
        for tc in CELL_RE.finditer(tr.group(0)):
            row.append(dict(re.findall(
                r"<w:(top|bottom|left|right) w:val=\"([^\"]+)\"",
                tc.group(0))))
        got.append(row)
    return got


BASIC = [["", "(1)"], ["Age", "0.1"], ["Income", "0.2"]]


# ----------------------------------------------------- where rules go ----


def test_the_top_rule_sits_on_the_first_row_and_nowhere_else():
    rows = ruled(BASIC)
    assert all(c["top"] == "single" for c in rows[0])
    assert all(c["top"] == "nil" for r in rows[1:] for c in r)


def test_the_mid_rule_closes_the_header_block():
    """Under the LAST header row — row 0 here, since the stub is empty
    only there."""
    rows = ruled(BASIC)
    assert all(c["bottom"] == "single" for c in rows[0])
    assert all(c["bottom"] == "nil" for c in rows[1])


def test_a_two_row_header_closes_after_the_second():
    rows = ruled([["", "(1)"], ["", "OLS"], ["Age", "0.1"]])
    assert all(c["bottom"] == "nil" for c in rows[0])
    assert all(c["bottom"] == "single" for c in rows[1])


def test_a_THREE_row_header_closes_after_the_third():
    """`shape.header_rows - 1`, and the mutant is `>>`: one minus one
    and one halved are both 0, two minus one and two halved are both 1,
    so a header of one or two rows cannot tell subtraction from a
    halving. Three can — and a three-row header is an ordinary stack:
    the group name, the sub-heading, the column numbers."""
    rows = ruled([["", "Discipline"], ["", "OLS"], ["", "(1)"],
                  ["Age", "0.1"]])

    assert all(c["bottom"] == "nil" for c in rows[0])
    assert all(c["bottom"] == "nil" for c in rows[1])
    assert all(c["bottom"] == "single" for c in rows[2])


def test_the_bottom_rule_is_double_and_only_on_the_last_row():
    rows = ruled(BASIC)
    assert all(c["bottom"] == "double" for c in rows[-1])
    assert not any(c["bottom"] == "double" for r in rows[:-1] for c in r)


def test_no_vertical_rules_anywhere():
    """Three-line style: no left or right edges at all."""
    rows = ruled(BASIC)
    assert all(c["left"] == "nil" and c["right"] == "nil"
               for r in rows for c in r)


def test_a_panel_and_a_summary_block_take_a_rule_above():
    rows = ruled([["", "(1)"],
                  ["Age", "0.1"],
                  ["Kyrgyzstan", ""],
                  ["Income", "0.2"],
                  ["Observations", "900"]])
    assert all(c["top"] == "single" for c in rows[2])    # panel
    assert all(c["top"] == "single" for c in rows[4])    # summary
    assert all(c["top"] == "nil" for c in rows[3])


def test_the_cmidrule_covers_only_the_cells_that_span():
    """A partial rule under a group head, so the reader sees what belongs
    to it — and not under the stub, which spans nothing."""
    rows = ruled([["", "Discipline"], ["", "(1)", "(2)"],
                  ["Age", "0.1", "0.2"]],
                 width=3, spans={(0, 1): 2})
    assert rows[0][0]["bottom"] == "nil"       # the stub
    assert rows[0][1]["bottom"] == "single"    # the group head


# --------------------------------------------------- how thick, and what -


def test_the_default_rule_is_four_eighths_of_a_point():
    xml = doc(tbl(BASIC))
    out, _ = tables.booktabs(xml, read_all(xml)[0])
    assert 'w:val="single" w:sz="4"' in out


def test_the_rule_width_is_settable():
    xml = doc(tbl(BASIC))
    out, _ = tables.booktabs(xml, read_all(xml)[0], rule=8)
    assert 'w:val="single" w:sz="8"' in out
    assert 'w:sz="4"' not in out


def test_the_closing_rule_style_is_settable():
    xml = doc(tbl(BASIC))
    out, _ = tables.booktabs(xml, read_all(xml)[0], bottom="thick")
    assert 'w:val="thick"' in out
    assert 'w:val="double"' not in out


def test_a_table_already_in_this_style_is_returned_unchanged():
    """`if new != tc.group(0)` — an idempotent pass must not churn bytes,
    or a second run reports every cell as edited."""
    xml = doc(tbl(BASIC))
    once, _ = tables.booktabs(xml, read_all(xml)[0])
    twice, _ = tables.booktabs(once, read_all(once)[0])
    assert twice == once


# ------------------------------------------------------- alignment -----


def aligned(rows, align, **kw):
    xml = doc(tbl(rows, width=kw.pop("width", None),
                  spans=kw.pop("spans", None)))
    out, _ = tables.booktabs(xml, read_all(xml)[0], align=align)
    return [re.findall(r'<w:jc w:val="(\w+)"/>', tr.group(0))
            for tr in ROW_RE.finditer(out[out.index("<w:tbl>"):])]


def test_the_last_alignment_repeats_across_the_remaining_columns():
    got = aligned([["", "(1)", "(2)", "(3)"],
                   ["Age", "1", "2", "3"]], ("left", "center"))
    assert got[1] == ["left", "center", "center", "center"]


def test_one_alignment_applies_to_every_column():
    got = aligned([["", "(1)"], ["Age", "1"]], "right")
    assert got[1] == ["right", "right"]


def test_a_row_wider_than_the_grid_does_not_index_past_the_alignments():
    """`min(columns[j], len(jc) - 1)`.

    A malformed row carries more cells than the grid has columns —
    `_cell_walk` truncates for widths, and the clamp here is the same
    guard for alignment. Without it the extra cell indexes past the end
    of a list built from the GRID, and a table nobody could see a problem
    with raises.
    """
    # width=2 explicitly: the grid is NARROWER than the row, which is the
    # whole point and does not happen if the grid is derived from the
    # widest row
    got = aligned([["", "(1)"], ["Age", "1", "2", "3"]], ("left", "center"),
                  width=2)
    assert got[1][:2] == ["left", "center"]
    assert all(v == "center" for v in got[1][2:])


def test_a_spanning_cell_takes_the_alignment_of_the_column_it_starts_in():
    """`columns[j]`, not `j`. Cell index and grid column coincide only in
    a table with no merged cells — and the existing test for this could
    not tell them apart, because its alignments happened to repeat at
    both positions.
    """
    got = aligned([["", "A", "B"], ["Age", "1", "2", "3"]],
                  ("left", "center", "right", "both"),
                  width=4, spans={(0, 1): 2})
    # header cells sit at grid columns 0, 1 and 3
    assert got[0] == ["left", "center", "both"]


def test_alignment_is_left_alone_when_none_is_asked_for():
    xml = doc(tbl(BASIC))
    out, _ = tables.booktabs(xml, read_all(xml)[0])
    assert "<w:jc" not in out


@pytest.mark.parametrize("align", ["middle", "justify"])
def test_an_alignment_word_does_not_know_is_refused(align):
    from docxkit.errors import AnchorError

    xml = doc(tbl(BASIC))
    with pytest.raises(AnchorError, match="align"):
        tables.booktabs(xml, read_all(xml)[0], align=align)


# ------------------------------------------------ margin is PER SIDE ----


def test_the_margin_is_charged_to_both_sides_of_every_cell():
    """`side = 2 * margin`. `margin` names one side — Word's default is
    108 a side — so the width a column loses to padding is twice it.
    Charging one side would give every column 108 dxa it does not have,
    and the table would overrun its own width.
    """
    xml = doc(tbl([["Label here", "-0.250***", "0.047"]]))
    table = read_all(xml)[0]
    out, report = tables.fit_columns(xml, table, margin=60)

    body = xml[table.start:table.end]
    grid = [1000, 1000, 1000]
    need_h, need_f, _, filled = _column_needs(body, grid, 2 * 60, 1.05)
    expected, _ = _divide(grid, need_h, need_f, filled, report.total)
    assert [c.new for c in report.columns] == expected

    # and the margins written are per side, which is what Word reads
    written = out[out.index("<w:tbl>"):]
    assert _side_margins(written) == 120
    assert '<w:left w:w="60" w:type="dxa"/>' in written
    assert '<w:right w:w="60" w:type="dxa"/>' in written


def test_an_empty_span_BESIDE_a_group_head_gets_no_cmidrule():
    """`span > 1 and _cell_text(...)` as `or`: a rule under an empty
    cell is a rule under nothing, and the docstring says so.

    It takes both in ONE row to show. A row whose only span is empty is
    not a group row at all — `plan_booktabs` never lists it, so
    `_group_columns` is not consulted and the guard is unreachable from
    there. The shape that reaches it is a real one: a group head over
    the first block of columns and a spanned gap over the rest."""
    rows = ruled([["", "Discipline", ""],
                  ["", "(1)", "(2)", "(3)", "(4)"],
                  ["Age", "0.1", "0.2", "0.3", "0.4"]],
                 width=5, spans={(0, 1): 2, (0, 2): 2})
    assert rows[0][1]["bottom"] == "single", "the group head lost its rule"
    assert rows[0][2]["bottom"] == "nil", "an empty span was ruled"


def test_a_heading_and_its_FIRST_panel_are_not_ruled_apart():
    """`label_of(i - 1)` — the row BEFORE, and the mutants read the row
    after or the row itself.

    Two label-only rows in a row are a heading and its first panel
    ("Panel A", then "Kyrgyzstan"), and a rule between them rules off
    nothing: the reader sees a line with a bare heading above it. The
    guard suppresses the second one's rule.

    Reading the row AFTER instead is invisible unless that row's own
    label is empty, which is why the data row under the panel carries
    none here."""
    rows = ruled([["", "(1)"],
                  ["Panel A", ""],
                  ["Kyrgyzstan", ""],
                  ["", "0.1"],
                  ["Age", "0.2"]])

    assert all(c["top"] == "single" for c in rows[1]), "the heading rules"
    assert all(c["top"] == "nil" for c in rows[2]), (
        "a rule between a heading and its own first panel rules off "
        "nothing")


def test_a_panel_under_a_BLANK_row_still_takes_its_rule():
    """The same guard from the other side. A blank spacer row is not a
    heading — it has no label — so the panel below it opens normally,
    and `label_of(i - 1)` is what tells the two apart. Mutated to
    `label_of(i)` the test is the panel's OWN label, which is always
    there, and every panel under a blank row loses its rule."""
    rows = ruled([["", "(1)"],
                  ["Age", "0.1"],
                  ["", ""],
                  ["Kyrgyzstan", ""],
                  ["Income", "0.2"]])

    assert all(c["top"] == "single" for c in rows[3])
