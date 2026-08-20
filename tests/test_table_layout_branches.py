"""The branches of `_table_layout` no fixture happened to produce.

A cosmic-ray pass over the module (2,217 mutants, 592 survivors) and
coverage agreed on where to look: six lines the whole suite never
executed, and a cluster of 34 survivors in `_set_jc` sitting on the one
alignment path a real manuscript takes most often — a paragraph that HAS
properties but states no `w:jc`.

The fixtures wrote paragraphs with no `w:pPr` at all, or with an
alignment already set. Word writes neither: a table cell out of a real
paper carries a `w:pStyle`, sometimes a `w:rPr`, and no alignment until
something sets one.
"""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit import tables
from docxkit._table_layout import (
    _AFTER_TBLLAYOUT,
    _TBLLAYOUT_RE,
    _alignment,
    _bump,
    _check_rule,
    _keep_with_table,
    _own_tblpr,
    _round_to,
    _set_jc,
    _set_properties,
    _set_tbl_pr,
)
from docxkit.errors import AnchorError

FIXED = '<w:tblLayout w:type="fixed"/>'


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def cell(text: str, *, w: int = 1000) -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")


# ------------------------------------------- an empty properties element --


def test_a_self_closing_tblpr_is_real_and_reports_no_inner():
    body = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
            "</w:tblGrid><w:tr>" + cell("x") + "</w:tr></w:tbl>")
    own = _own_tblpr(body)
    assert own is not None
    start, end, inner = own
    assert inner == ""
    assert body[start:end] == "<w:tblPr/>"


def test_a_self_closing_tblpr_is_expanded_not_duplicated():
    """Two `w:tblPr` in one `w:tbl` is schema-invalid — the same defect
    `_EDGE_RE` was widened for on `w:tcBorders`, where matching only the
    expanded form made the writer insert a second element beside the
    empty one."""
    body = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
            "</w:tblGrid><w:tr>" + cell("x") + "</w:tr></w:tbl>")
    out = _set_tbl_pr(body, _TBLLAYOUT_RE, FIXED, _AFTER_TBLLAYOUT)
    assert out.count("<w:tblPr") == 1
    assert f"<w:tblPr>{FIXED}</w:tblPr>" in out


def test_fit_columns_handles_a_table_whose_properties_are_empty():
    xml = doc('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
              '<w:gridCol w:w="1000"/></w:tblGrid><w:tr>'
              + cell("Label") + cell("-0.250***") + "</w:tr></w:tbl>")
    out, report = tables.fit_columns(xml, tables.read_all(xml)[0])
    assert sum(c.new for c in report.columns) == report.total
    assert out.count("<w:tblPr") == 1
    assert FIXED in out


# ------------------------------------------------ alignment on a pPr -----


def test_alignment_is_added_to_properties_that_state_none():
    """The ordinary case out of a real manuscript, and the one the suite
    never built: a paragraph with a style and no alignment."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"/></w:pPr>'
            "<w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "center")
    assert ('<w:pPr><w:pStyle w:val="Body"/><w:jc w:val="center"/></w:pPr>'
            in got)


def test_alignment_lands_before_the_properties_that_follow_it():
    """`CT_PPr` is a sequence: `w:jc` precedes `w:rPr`. Appending it at
    the end puts it after, and Word repairs a document whose paragraph
    properties are out of order."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"/>'
            "<w:rPr><w:b/></w:rPr></w:pPr><w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "left")
    inner = got[got.index("<w:pPr>"):got.index("</w:pPr>")]
    assert inner.index("<w:jc") < inner.index("<w:rPr")
    assert "<w:b/>" in got


def test_an_existing_alignment_is_replaced_not_stacked():
    para = ('<w:p><w:pPr><w:jc w:val="left"/></w:pPr>'
            "<w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "center")
    assert got.count("<w:jc") == 1
    assert 'w:val="center"' in got and 'w:val="left"' not in got


def test_alignment_is_written_to_the_live_properties_not_the_snapshot():
    """`w:pPrChange` holds what a tracked change REPLACED. Writing there
    aligns the historical record and leaves the page as it was."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"/>'
            '<w:pPrChange w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
            '<w:pPr><w:jc w:val="right"/></w:pPr></w:pPrChange>'
            "</w:pPr><w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "center")
    live, _, past = got.partition("<w:pPrChange")
    assert 'w:val="center"' in live
    assert 'w:val="right"' in past          # the snapshot is untouched
    assert past.count("<w:jc") == 1


def test_a_fragment_that_is_not_a_paragraph_is_returned_unchanged():
    assert _set_jc("<w:tc/>", "center") == "<w:tc/>"
    assert _set_jc("", "center") == ""


def test_a_paragraph_with_no_properties_gets_some():
    got = _set_jc("<w:p><w:r><w:t>x</w:t></w:r></w:p>", "center")
    assert '<w:pPr><w:jc w:val="center"/></w:pPr>' in got


# --------------------------------------------------- refusals that stand --


def test_an_empty_alignment_sequence_is_refused():
    """`align=()` reaches `vals[min(i, -1)]` and silently aligns every
    column by the LAST element of an empty list — which is an IndexError
    at best and the wrong column at worst."""
    with pytest.raises(AnchorError, match="align= is empty"):
        _alignment([], 3)


def test_a_single_alignment_repeats_across_every_column():
    assert _alignment("center", 3) == ["center"] * 3


def test_the_last_alignment_repeats_when_there_are_more_columns():
    assert _alignment(("left", "center"), 4) == \
        ["left", "center", "center", "center"]


def test_booktabs_refuses_a_table_with_no_rows():
    xml = doc('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
              "</w:tblGrid></w:tbl>")
    with pytest.raises(AnchorError, match="no rows"):
        tables.booktabs(xml, tables.read_all(xml)[0])


def test_bottom_border_refuses_a_table_with_no_rows():
    xml = doc('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
              "</w:tblGrid></w:tbl>")
    with pytest.raises(AnchorError, match="no rows"):
        tables.bottom_border(xml, tables.read_all(xml)[0])


# ------------------------------------- the run of 2026-08-20: 7.8 % --


def test_a_deficit_of_ONE_dxa_is_still_apportioned():
    """`if deficit <= 0: return` is the whole guard, and one twentieth
    of a point is a deficit like any other — the arithmetic that
    produces it is a `ceil`, so it lands on 1 often.

    It is also the smallest total `_round_to` can be handed, and the
    only one where every share floors to zero: `sum(out)` is then 0,
    and the remainder loop that reads `total - sum(out)` is the one
    that survives a modulo there rather than dividing by it."""
    needs = [10, 10]

    _bump(needs, [0, 1], 1)

    assert needs == [11, 10], "the widest share takes the odd dxa"
    assert _round_to(1, [10, 10]) == [1, 0]


def test_a_border_size_of_ZERO_is_the_nil_rule_not_a_mistake():
    """The range starts at 0 because `_clear_borders` asks for exactly
    that: every side it is not drawing is written as `("nil", 0)`. A
    check that starts at 1 refuses the module's own erasing pass."""
    _check_rule("nil", 0, "booktabs")           # the nil rule: no raise

    with pytest.raises(AnchorError, match="outside Word"):
        _check_rule("single", 97, "booktabs")


def test_a_property_that_sorts_ABOVE_the_house_one_is_still_replaced():
    """`existing == inner` decides whether the run is already in house
    style, and the two sides are XML strings. Read as `>=` it answers
    "already right" for every run whose properties happen to sort after
    the house ones — `w:sz` after `w:rFonts`, which is the ordinary
    case, since a table out of a paper states its size and nothing
    else. The pass then rewrites nothing and reports 0 runs set.

    The second half is the write: the span ends at the CLOSE of the
    existing element, and cut at its start instead the replacement
    leaves the old properties standing beside the new ones."""
    run_xml = '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>x</w:t></w:r>'
    wanted = ('<w:rPr><w:rFonts w:ascii="Times New Roman"/>'
              '<w:sz w:val="20"/></w:rPr>')
    inner = wanted[wanted.index(">") + 1:wanted.rindex("</")]
    assert inner <= '<w:sz w:val="24"/>', (
        "the fixture has to sort the wrong way round to pin the reading")

    out, changed = _set_properties(run_xml, "rPr", wanted)

    assert changed is True
    assert out == f'<w:r>{wanted}<w:t>x</w:t></w:r>'


def test_a_caption_that_matches_NOTHING_names_the_count():
    """`len(hits) != 1` covers both sides of "exactly one": a typo in
    the caption matches zero paragraphs, and read as `> 1` that falls
    through the raise into `hits[0]` — an IndexError from inside the
    house pass, where the message it replaces tells the caller which
    caption to fix."""
    xml = doc("<w:p><w:r><w:t>Table 3: Data sources</w:t></w:r></w:p>")

    with pytest.raises(AnchorError, match="matched 0 paragraphs"):
        _keep_with_table(xml, "Table 4:")

    with pytest.raises(AnchorError, match="matched 2 paragraphs"):
        _keep_with_table(xml + xml, "Table 3:")


def test_a_span_over_SPACER_columns_does_not_stop_the_ones_after_it():
    """A spanning cell whose columns are all unfilled constrains
    nothing — there is no column under it to grow. `continue` is what
    makes that free; `break` ends the walk over the REST of the spans,
    and the first span in a table of this shape is the stub head, which
    is exactly the one that constrains nothing.

    Then the group head above the two number columns never sets their
    floor, and "Non-violent discipline" wraps into the two-line label
    the pass exists to prevent."""
    import math

    from docxkit._table_layout import _cell_extents, _column_needs

    def tc(text: str, w: int, span: int = 0) -> str:
        sp = f'<w:gridSpan w:val="{span}"/>' if span else ""
        return (f"<w:tc><w:tcPr>{sp}"
                f'<w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")

    head = "Non-violent discipline"
    grid = [500, 500, 900, 900]
    body = ('<w:tbl><w:tblPr><w:tblW w:w="2800" w:type="dxa"/></w:tblPr>'
            "<w:tblGrid>"
            + "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
            + "</w:tblGrid>"
            + "<w:tr>" + tc("Regressor", 1000, 2) + tc(head, 1800, 2)
            + "</w:tr><w:tr>" + tc("Mother's schooling", 1000, 2)
            + tc("1", 900) + tc("2", 900) + "</w:tr></w:tbl>")
    side, pad = 216, 1.05

    need_h, _need_f, _driver, filled = _column_needs(body, grid, side, pad)

    assert filled == [False, False, True, True], (
        "the stub columns must be spanned only, or the first span is "
        "not the one that constrains nothing")
    hard, _full, _text = _cell_extents(tc(head, 1800, 2),
                                       ("Times New Roman", 24))
    assert need_h[2] + need_h[3] == math.ceil(hard * pad) + side
    digit, _f, _t = _cell_extents(tc("1", 900), ("Times New Roman", 24))
    assert need_h[2] > math.ceil(digit * pad) + side, (
        "the head has to be wider than its columns, or nothing bumps")


def test_a_cell_that_states_a_span_of_ONE_is_not_a_group_head():
    """`w:gridSpan w:val="1"` is a cell like any other — Word writes it
    after a merge is undone. Read as `>= 1`, every stated span becomes a
    group head and gets a cmidrule under it, which is a rule under one
    column."""
    from docxkit._table_core import cells_of
    from docxkit._table_layout import _group_columns

    def tc(text: str, span: int) -> str:
        return (f'<w:tc><w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")

    tr = "<w:tr>" + tc("Unmerged", 1) + tc("A group", 2) + "</w:tr>"

    assert _group_columns(list(cells_of(tr))) == {1}


def test_a_table_with_no_GRID_to_count_is_ruled_without_alignment():
    """Two guards for one shape. The column count for `align=` falls
    back to the first row's cell count when the table states no
    `w:gridCol` — and a first row with no cells at all is the shape
    `(rows[i][:1] or [""])` is written for elsewhere in this module. The
    fallback then answers 0, `_alignment` returns an empty list, and the
    per-cell guard is what keeps the alignment lookup off it.

    Read as `or`, that lookup runs against an empty list and the pass
    dies with an IndexError inside a table it could still have ruled.
    Counting the SECOND row instead would align the table off a count
    the caller never gave."""
    from docxkit import tables

    trs = ""
    for cells in ([], ["x", "1"], ["y", "2"]):
        trs += ("<w:tr>" + "".join(
            f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>"
            for c in cells) + "</w:tr>")
    xml = doc(f"<w:tbl><w:tblPr/>{trs}</w:tbl>")
    table = tables.read_all(xml)[0]
    assert table.rows[0] == [], "an empty first row is the point"

    out, _plan = tables.booktabs(xml, table, align=("left", "center"))

    assert "<w:jc" not in out, "no grid to align against"
    assert out.count("<w:tcBorders") == 4, "and the rules are still drawn"


# --- the argued half of the 2026-08-20 run ----------------------------
#
# Thirty-four survivors, thirteen of them the tests above. The other
# twenty-one are equivalent, and each went through kill_check rather
# than being asserted:
#
# * `_own_grid`: `grid.start() > first_row` read as `>=`. Two different
#   elements cannot begin at the same offset.
# * `_own_tblpr`: `first_row != -1` read as `!= 1`. `find` answers -1 or
#   an offset inside a `<w:tbl ...>` open tag, never 1 — and on -1 the
#   mutant reads `body[:-1]`, which drops the last `>` of `</w:tbl>`,
#   behind both the properties search and its depth count.
# * `_set_tbl_pr`: `p != -1` read as `is not -1`. CPython caches that
#   int, and every value here comes from `str.find`.
# * the two `ch == chr(10)` in `_cell_extents`, read as `is`: a
#   one-character string is interned.
# * `_own_tcpr`: `m.end(2)` read as `m.end(3)`. Group 3 is the
#   zero-width `(/?)` at the END of group 2, so the depth count starts
#   one character earlier — on the `>` that closes the open tag, which
#   cannot begin an element.
# * `_set_tc_w`: `at = opening.end() if opening else 0` read as `else 1`.
#   The one caller walks `<w:tc ...>` matches, so a fragment with no
#   open tag cannot reach it; the docstring already says a second caller
#   needs the guard.
# * `_column_needs`: `sizes.most_common(1)[0]` read as `most_common(2)`.
#   Same first element either way.
# * `_column_needs`: the unfilled column`s `need_f` of 0 read as -1. The
#   line under it takes `max(need_f[c], need_h[c])`, and `need_h` is 0
#   for exactly the columns that reach it.
# * `_apply_widths`: `new_tc != tc.group(0)` read as `is not`.
#   `_set_tc_w` builds its answer, so identity always differs and every
#   cell joins the edit list — where splicing a span with the text
#   already in it leaves the body character for character the same.
# * five in `plan_booktabs` on `(rows[i][:1] or [""])[0]`: `or [""]`
#   makes it a one-element list, so a wider slice does not move index 0
#   and index -1 of one element IS index 0.
# * two on `max((len(r) for r in rows), default=0)`. The default is
#   reached only for a table with NO rows, and `header` is then 1, so
#   `range(header - 1)` is empty and the width is never compared.
# * `i != len(rows) - 1` read as `i < len(rows) - 1`: `i` never exceeds
#   the last index it is iterating over.
# * three on `i > header` read as `!=` or `is not`: the loop starts AT
#   `header`.
# * `drop_blank_rows`: `len(blank) == len(trs)` read as `is`. The
#   standing small-int argument — a table would need more than 256 rows,
#   all of them blank, for the two to part company.
# * `drop_blank_rows`: `range(b + 1, len(trs))` read as `range(b * 1,
#   ...)`. `b` came out of `blank`, and `gone` is the set of `blank`, so
#   the extra candidate is dropped by the comprehension`s own guard.
