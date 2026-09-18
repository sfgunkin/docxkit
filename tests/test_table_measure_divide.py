"""What the width model measures, and how the total gets divided.

Two survivor clusters from the mutation pass: 33 in `_cell_extents` and
22 in `_divide`. Both were reached constantly and pinned loosely — the
existing tests assert that a fit HAPPENED and that nothing wrapped, which
a model scaled by almost any constant would satisfy.

The factors below are the model's whole content. `pad` covers its error,
but only if the thing being padded is the right size to begin with, and
a factor nothing checks is a factor that can drift by any amount.

One of these is a fresh debt of my own: the `w:tab` handling added when
`w:br` was, with a test asserting only that a tab makes the line LONGER.
Every mutation of how much longer survived.
"""
from __future__ import annotations

import pytest

from docxkit import tables
from docxkit._table_layout import (
    _TAB_SPACES,
    _cell_extents,
    _column_needs,
    _divide,
    _round_to,
)
from docxkit.errors import AnchorError

FALLBACK = ("Times New Roman", 24)


def rpr(font: str = "Times New Roman", sz: int = 24,
        extra: str = "") -> str:
    return (f'<w:rPr><w:rFonts w:ascii="{font}"/>'
            f'<w:sz w:val="{sz}"/>{extra}</w:rPr>')


def word(text: str, **kw) -> str:
    return f"<w:r>{rpr(**kw)}<w:t>{text}</w:t></w:r>"


def tab(**kw) -> str:
    return f"<w:r>{rpr(**kw)}<w:tab/></w:r>"


def brk(**kw) -> str:
    return f"<w:r>{rpr(**kw)}<w:br/></w:r>"


def cell_of(*runs: str) -> tuple[float, float, str]:
    """Measure a cell built from real runs — the shape Word writes."""
    return _cell_extents(f"<w:tc><w:p>{''.join(runs)}</w:p></w:tc>",
                         FALLBACK)


def extents(content: str, **kw) -> tuple[float, float, str]:
    return cell_of(word(content, **kw))


def full(content: str, **kw) -> float:
    return extents(content, **kw)[1]


# ------------------------------------------------------- the factors ----


def test_size_scales_the_width_linearly():
    """`scale * sz * 10.0 / 1000.0`. The model's linearity in size is
    what lets the alias scales be constants rather than a size curve."""
    assert full("Sample", sz=48) == pytest.approx(full("Sample", sz=24) * 2)


def test_the_conversion_from_half_points_to_dxa_is_pinned_absolutely():
    """`w:sz` is HALF-points, a point is 20 dxa, and the tables are per
    1000 em — so a character is `table[ch] / 1000 * sz * 10` dxa.

    Pinned as an absolute, because every other measurement here compares
    two widths and a wrong CONSTANT cancels out of a ratio. Offline, this
    is the only thing standing between a scale error and a build: the
    check that would otherwise catch it lives in `test_width_model.py`,
    which needs a real Word and is deselected by default.
    """
    assert full("M", sz=24) == pytest.approx(889 * 24 * 10 / 1000)
    assert full("M", sz=20) == pytest.approx(889 * 20 * 10 / 1000)


def test_bold_costs_five_percent():
    bold = full("Sample", extra="<w:b/>")
    assert bold == pytest.approx(full("Sample") * 1.05)


@pytest.mark.parametrize("val", ["superscript", "subscript"])
def test_a_raised_or_lowered_run_renders_at_two_thirds(val):
    """Which is why `superscript_stars` NARROWS a coefficient column —
    `fit_columns` prices the smaller stars in."""
    small = full("123", extra=f'<w:vertAlign w:val="{val}"/>')
    assert small == pytest.approx(full("123") * 0.65)


def test_an_unknown_font_is_measured_as_times():
    """A face nobody listed still has to produce a number, and Times is
    the one every manuscript here is set in."""
    assert full("Sample", font="Nonesuch Display") == \
        pytest.approx(full("Sample", font="Times New Roman"))


def test_a_character_the_table_does_not_list_takes_the_fallback():
    """600/1000 em. An OMITTED character is the failure mode the width
    tests are designed around: a wrong entry is off by a percent, a
    missing one by a factor."""
    assert full("€") == pytest.approx(full("M") * 600 / 889)


# ---------------------------------------------------- breaks and tabs ----


def test_a_tab_advances_by_its_documented_multiple_of_a_space():
    """The magnitude, not just the direction. `_TAB_SPACES` is an
    approximation of a stop nobody can know from the run — but an
    approximation that can be mutated to any value is not one."""
    space = full("a b") - full("ab")
    tabbed = cell_of(word("a"), tab(), word("b"))[1] - full("ab")
    assert tabbed == pytest.approx(space * _TAB_SPACES)


def test_a_hard_break_ends_the_line_rather_than_widening_it():
    plain = full("ab")
    broken = cell_of(word("a"), brk(), word("b"))[1]
    assert broken < plain
    assert broken == pytest.approx(max(full("a"), full("b")))


def test_a_slash_licenses_a_break_and_a_hyphen_does_not():
    """Word breaks after a slash, so "Professional/vocational" wraps
    gracefully. A hyphen also breaks in Word and is deliberately NOT
    split here: a negative coefficient's sign must never be a licensed
    break, or the dangling-minus wrap returns."""
    slashed = extents("aaaa/bb")[0]
    hyphened = extents("aaaa-bb")[0]
    assert slashed == pytest.approx(extents("aaaa/")[0])
    assert hyphened == pytest.approx(extents("aaaa-bb")[1])
    assert hyphened > slashed


def test_the_driver_text_reads_as_the_cell_reads():
    """It is quoted back to a person in `ColumnFit.driver`, so a break
    has to read as the space it renders as rather than fusing words."""
    _, _, text = cell_of(word("Total"), brk(), word("expenditure"))
    assert text == "Total expenditure"


# ------------------------------------------------- dividing the total ----


def tbl(total: int, grid: list[int], cells: list[str]) -> str:
    from conftest import NS
    cols = "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
    tcs = "".join(
        f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr><w:p><w:r>'
        f'<w:rPr><w:rFonts w:ascii="Times New Roman"/><w:sz w:val="20"/>'
        f"</w:rPr><w:t>{t}</w:t></w:r></w:p></w:tc>"
        for w, t in zip(grid, cells, strict=True))
    return (f"<w:document {NS}><w:body><w:tbl><w:tblPr>"
            f'<w:tblW w:w="{total}" w:type="dxa"/></w:tblPr>'
            f"<w:tblGrid>{cols}</w:tblGrid><w:tr>{tcs}</w:tr>"
            f"</w:tbl></w:body></w:document>")


CELLS = ["A label that can wrap across lines", "-0.250***", "0.047"]
GRID = [3000, 900, 900]


def fit(total: int):
    xml = tbl(total, GRID, CELLS)
    return tables.fit_columns(xml, tables.read_all(xml)[0], total=total)[1]


def test_room_to_spare_gives_every_column_its_full_line():
    """`sum_f <= avail` — nothing wraps at all."""
    report = fit(12000)
    assert not report.cramped
    assert sum(c.new for c in report.columns) == 12000


def test_room_to_spare_shares_the_table_out_by_full_need():
    """WHICH branch ran, not just that the widths sum. The slack is
    divided in proportion to what each column needs for a whole line;
    the shaving branch divides by the ROOM above each column's
    unbreakable minimum instead, and reaches the same total by a
    different split."""
    from docxkit._table_layout import _column_needs, _side_margins

    xml = tbl(12000, GRID, CELLS)
    body = xml[xml.index("<w:tbl>"):xml.index("</w:body>")]
    _, need_f, _, _ = _column_needs(body, GRID, _side_margins(body), 1.05)

    widths = [c.new for c in fit(12000).columns]
    want = sum(need_f)
    for got, need in zip(widths, need_f, strict=True):
        assert got / 12000 == pytest.approx(need / want, abs=0.002)


def test_a_tight_total_shaves_the_wrap_tolerant_column_first():
    """`sum_h <= avail` — the numeric columns keep their unbreakable
    content and the label column, which wraps gracefully, gives up the
    difference."""
    roomy, tight = fit(12000), fit(3400)
    assert not tight.cramped
    # The share, not the absolute width: with room to spare every column
    # is scaled up proportionally, so what changes under pressure is
    # WHERE the shortfall lands — on the column whose text wraps
    # gracefully rather than on the coefficients.
    assert (tight.columns[0].new / tight.total
            < roomy.columns[0].new / roomy.total)


def test_a_total_below_the_unbreakable_minima_is_cramped():
    """Past the hard minima everything scales down and mid-word wraps
    remain — reported rather than hidden, because the fix is a smaller
    font or fewer columns and only a person can choose."""
    assert fit(900).cramped


def test_spacers_that_take_the_whole_table_are_refused_at_the_boundary():
    """`avail <= 0`, not `< 0`. At exactly zero every filled column is
    apportioned a share of nothing and the table is written with
    zero-width columns, which is not a narrow table but an invisible
    one."""
    xml = tbl(600, [100, 500, 100], ["A", "", "B"])
    with pytest.raises(AnchorError, match="spacer columns"):
        tables.fit_columns(xml, tables.read_all(xml)[0], total=500)


# ---------------------------------------- what the mutation sweep found ---
#
# 2,217 mutants, 382 real survivors (2026-08-11). The apportioning maths
# was the densest untested part: _round_to had four survivors on three
# lines and _divide's two branch edges had none. Each was confirmed by
# applying it and watching the whole suite stay green.
#
# The 98 survivors inside `_widths` are NOT here, and the reason is
# already written down: `test_width_model.py` has a note addressed to
# whoever next runs this tool, saying that a +-1 NumberReplacer on an
# AFM entry falls INSIDE the 2.5% tolerance that gate declares, so
# surviving is the right answer rather than a missing check.
#
# Checked again rather than taken on trust (2026-08-11): the apostrophe
# at 180 per 1000 em, mutated to 181, passes the everyday suite AND
# `pytest -m word` against a real Word. So the note is right, and the
# gate's promise is "no character is out by more than 2.5%", not "every
# entry is exact". A test written here would pin the model to itself.


def test_round_to_apportions_by_weight_and_sums_exactly():
    """Two mutants live here and one fixture separates both, which the
    first attempt at this test did not: weights that divide EXACTLY
    (1000 over 1:2:7) give the same answer under `/` and `//` and leave
    every remainder at zero, so neither the division nor the ordering is
    doing anything a test can see. 10 over 1:2 does both."""
    assert _round_to(10, [1.0, 2.0]) == [3, 7]
    assert _round_to(1000, [1.0, 2.0, 7.0]) == [100, 200, 700]


def test_round_to_gives_the_remainder_to_the_largest_fractions_first():
    """The largest-remainder rule: 3.33 and 6.67 leave one spare unit,
    and it belongs to the .67. Sorted the other way it goes to the
    column that needed it least — and floor-dividing first flattens
    both fractions to zero, which hands it to whichever column sorts
    first."""
    assert _round_to(10, [1.0, 2.0]) == [3, 7]
    assert _round_to(100, [1.0, 2.0, 4.0]) == [14, 29, 57]


def test_round_to_spreads_the_remainder_over_DIFFERENT_columns():
    """`i % len(order)` as `i // len(order)` puts every spare unit on one
    column: the remainder is always smaller than the column count, so
    the index collapses to 0 and one column absorbs the lot."""
    got = _round_to(11, [1.0, 1.0, 1.0])
    assert sum(got) == 11
    assert sorted(got) == [3, 4, 4], got


def test_divide_takes_the_full_widths_when_they_fit_EXACTLY():
    """The edge itself. `sum_f <= avail` as `<` is EQUIVALENT here and
    that is worth knowing rather than testing around: on an exact fit
    the shaving branch apportions `sum_f - avail == 0`, so it hands back
    the full widths the first branch would have. The two branches meet
    at the boundary."""
    widths, cramped = _divide([100, 100], [40, 40], [60, 40],
                              [True, True], 100)
    assert widths == [60, 40] and not cramped


def test_divide_shaves_to_the_hard_widths_when_they_fit_EXACTLY():
    """The second edge, one branch down."""
    widths, cramped = _divide([100, 100], [50, 50], [90, 60],
                              [True, True], 100)
    assert sum(widths) == 100 and not cramped
    assert widths == [50, 50]


# ------------------------------------------ what a COLUMN is measured at --
#
# `_column_needs` turns the per-cell measurement above into one need per
# column: the widest cell wins, a spanning cell bumps the columns it
# covers, and a cell that states neither face nor size is measured at
# what the table mostly uses. The 2026-09-18 sweep left 22 survivors here
# and the fixtures below are what they were missing — a column with two
# cells of different widths, a cell with no run properties at all, and a
# span that stops short of the last column.


def tc(*runs: str, span: int = 1) -> str:
    props = (f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>'
             if span > 1 else "")
    return f"<w:tc>{props}<w:p>{''.join(runs)}</w:p></w:tc>"


def tr(*cells: str) -> str:
    return f"<w:tr>{''.join(cells)}</w:tr>"


def needs(grid: list[int], *rows: str, pad: float = 1.0, side: int = 0):
    """`_column_needs` over a table of `rows`, with no padding to hide
    an arithmetic difference behind."""
    cols = "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
    body = f"<w:tbl><w:tblGrid>{cols}</w:tblGrid>{''.join(rows)}</w:tbl>"
    return _column_needs(body, list(grid), side, pad)


def test_a_cell_that_states_NO_size_is_measured_at_the_tables_OWN():
    """`sizes.most_common(1)[0][0]` is the most common `w:sz` VALUE.
    Read as `[0][1]` or `[0][-1]` it is that value's COUNT — a size in
    half-points of however many cells happen to state it, so one table
    measures its unstated cells at 1 pt and the next at 6 pt, and
    neither number has anything to do with the type on the page.

    A run with no `w:rPr` is what Word writes wherever the paragraph
    style carries the face, so this is an ordinary body cell rather than
    an edge: the three cells here are the same word at the same size,
    and only one of them says so."""
    stated, bare = word("Sample", sz=20), "<w:r><w:t>Sample</w:t></w:r>"

    need_h, _full, _driver, _filled = needs(
        [4000, 4000, 4000], tr(tc(stated), tc(bare), tc(stated)))

    assert need_h[1] == need_h[0] == need_h[2]


def test_a_columns_need_is_its_WIDEST_cell_and_the_report_names_it():
    """`h > hard[c]`. As `!=` — or as `is not`, which is true of every
    pair of floats the model produces — the LAST cell wins instead, and
    a label column sized to its narrowest row wraps on all the others.
    The driver is the text the fit report names for the column, so it
    is the reader's way back to the cell that took the room."""
    wide = "Non-violent discipline"

    need_h, _full, driver, _filled = needs(
        [6000], tr(tc(word(wide))), tr(tc(word("7"))))
    alone, _f, _d, _fl = needs([6000], tr(tc(word(wide))))

    assert need_h[0] == alone[0]
    assert driver[0] == wide


def test_the_FIRST_of_two_cells_of_EQUAL_width_stays_the_driver():
    """`>` keeps the first, `>=` takes the last, and the two can only
    disagree where the widths are EQUAL — which two anagrams are, since
    the model measures character by character. Nothing else in this
    file can separate them: every other fixture's cells differ in
    width, where both spellings agree."""
    _need, _full, driver, _filled = needs(
        [6000], tr(tc(word("AB"))), tr(tc(word("BA"))))

    assert driver[0] == "AB"


def test_a_spans_bump_reaches_only_the_filled_columns_it_COVERS():
    """`range(c0, min(c0 + k, n))` twice: once for the columns the bump
    is spread over, once for the grid width of the SPACER columns inside
    the span, which the span does not have to pay for. Read as `c0 * k`,
    `c0 | k` or `c0 << k` the two ranges move — and a header spanning
    three columns of six, with a spacer inside it and another outside,
    is the shape where all three readings differ from the sum.

    The span here covers columns 1, 2 and 3, of which 3 is a spacer: so
    its need is met by columns 1 and 2 plus that spacer's own grid
    width, and column 4 — filled, and outside the span — is left at
    what its own cell needs."""
    wide = "Non-violent discipline and its correlates"
    #: column 3 is the gutter between two panels: narrow, and no cell
    #: writes into it, so the span pays for the rest and not for it
    grid = [1000, 1000, 1000, 100, 1000, 1000]
    body = tr(tc(word("a")), tc(word("b")), tc(word("c")),
              tc(), tc(word("d")), tc())

    need_h, _full, _driver, filled = needs(
        grid,
        tr(tc(word("a")), tc(word(wide), span=3), tc(word("d")), tc()),
        body, body)

    assert filled == [True, True, True, False, True, False]
    span_need = needs([20000], tr(tc(word(wide))))[0][0]
    assert need_h[1] + need_h[2] + grid[3] == span_need
    assert need_h[4] == needs([6000], tr(tc(word("d"))))[0][0]
