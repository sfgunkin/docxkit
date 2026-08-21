"""The table API's optional and refusal paths.

`find` and `by_caption` take `required=False` so a caller can probe for
a table that may not exist; `parse_number` and the value renderer decide
what a cell means. These are the seams the paper scripts build on, and
they were the last uncovered branches in the module.
"""
from __future__ import annotations

import pytest
from conftest import document, para, row, run, table

from docxkit import _table_core
from docxkit.errors import AnchorError
from docxkit.tables import (
    Table,
    _render_value,
    by_caption,
    clone_row,
    find,
    parse_number,
    read_all,
    reorder_rows,
    set_cell,
    set_row,
    superscript_stars,
    tables_after,
    to_frame,
)


def _doc() -> str:
    return document(
        para(run("Table 4. Decomposition"))
        + table(row("Country", "AFI (initial)", "Dif."),
                row("Poland", "0.31", "0.02"))
        + para(run("Source: authors.")))


# ------------------------------------------------------------- probing ----


def test_find_returns_none_when_not_required():
    assert find(read_all(_doc()), ["Occupation"], required=False) is None


def test_find_skips_a_table_narrower_than_the_wanted_header():
    tables = read_all(_doc())
    assert find(tables, ["Country", "AFI", "Dif.", "Extra"],
                required=False) is None


def test_by_caption_returns_none_for_an_unknown_caption():
    assert by_caption(_doc(), "Table 9.", required=False) is None


def test_by_caption_takes_the_table_ABOVE_when_the_caption_trails_it():
    """The convention is that a caption sits above its table, and two
    of AFI's six do not. Nothing else stands between this caption and
    the table before it, so that table is what it names."""
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 7. A caption underneath its table")))

    found = by_caption(xml, "Table 7.")

    assert found is not None and found.header == ["Country", "Score"]


def test_by_caption_REFUSES_a_table_that_belongs_to_another_caption():
    """The AFI defect, in the shape it was found: "Table 3." sits under
    its own table, and the next table down is the 2x2 grid holding
    Figure 5's panels. The old rule handed that grid back — a `Table`,
    not a `None`, so `required=True` could not fire and a caller
    reordering rows would have rewritten a different exhibit.
    """
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 3. A caption underneath its table"))
        + para(run("Figure 5. Panels"))
        + table(row("a. Tajikistan", "b. Albania")))

    found = by_caption(xml, "Table 3.")

    assert found is not None and found.header == ["Country", "Score"]


def test_by_caption_still_prefers_the_table_BELOW_when_both_are_free():
    """The convention, applied where it can still be true. A caption
    between two tables that nothing else claims is a caption above its
    table — which is what every well-formed manuscript here looks like.
    """
    xml = document(
        table(row("Country", "Score"))
        + para(run("Table 2. A caption above its table"))
        + table(row("Region", "Share")))

    found = by_caption(xml, "Table 2.")

    assert found is not None and found.header == ["Region", "Share"]


def test_by_caption_reads_a_RUN_of_captions_UNDER_their_tables():
    """The refusal above needs another caption to stand BETWEEN, and in
    this layout none does: AFI's `working.docx` runs
    `[Table 3][cap 3][Table A3][cap A3]`, so table A3 stayed a live
    candidate for "Table 3." and the below-the-caption convention then
    preferred it. Both lookups came back wrong, as `Table`s that
    `required=True` cannot fire on.

    "Table A3." has no table after it, so A3 is its only candidate —
    which is what says A3 was never "Table 3."'s to take.
    """
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 3. A caption underneath its table"))
        + table(row("Region", "Share"), row("EU", "2.0"))
        + para(run("Table A3. A caption underneath its table")))

    assert by_caption(xml, "Table 3.").header == ["Country", "Score"]
    assert by_caption(xml, "Table A3.").header == ["Region", "Share"]


def test_by_caption_propagates_along_a_WHOLE_run_of_them():
    """One assignment is not enough: each caption freed by the one below
    it settles the next, and only the last has no table after it. Three
    pairs is the shortest fixture where a single pass gets it wrong."""
    xml = document(
        table(row("A", "1")) + para(run("Table 1. Under it"))
        + table(row("B", "2")) + para(run("Table 2. Under it"))
        + table(row("C", "3")) + para(run("Table 3. Under it")))

    assert [by_caption(xml, f"Table {n}.").header for n in (1, 2, 3)] == [
        ["A", "1"], ["B", "2"], ["C", "3"]]


def test_by_caption_says_which_half_failed():
    """A missing caption and a caption with no table are different
    problems, and the message has to say which — the builders locate
    ten tables by caption and a wrong one is a silent mis-edit."""
    xml = document(
        table(row("Country", "Score"))
        + para(run("Figure 1. The panels above"))
        + para(run("Table 7. A caption whose own table is gone")))
    with pytest.raises(AnchorError, match="no paragraph containing"):
        by_caption(xml, "Table 9.")
    with pytest.raises(AnchorError, match="has no table of its own"):
        by_caption(xml, "Table 7.")
    assert by_caption(xml, "Table 7.", required=False) is None


# --------------------------------------------------------- cell values ----


@pytest.mark.parametrize("text", ["", "   ", "n/a", "—", "(dropped)"])
def test_parse_number_returns_none_for_a_cell_holding_no_number(text):
    assert parse_number(text) is None


def test_parse_number_never_raises_on_arbitrary_cell_text():
    """Every cell in every table is fed to this; it must not throw.

    (Its `except ValueError` is unreachable in practice — the pattern
    only ever yields a string float() accepts — but the guarantee
    callers rely on is this one, so pin it directly.)
    """
    hyp = pytest.importorskip("hypothesis")
    from hypothesis import strategies as st

    @hyp.given(st.text(alphabet="0123456789-−+.,  %*eE()", max_size=24))
    @hyp.settings(max_examples=400, deadline=None)
    def check(text: str) -> None:
        out = parse_number(text)
        assert out is None or isinstance(out, float)

    check()


def test_render_value_refuses_a_type_a_cell_cannot_hold():
    with pytest.raises(TypeError, match="str, number or None"):
        _render_value("0.31", [1, 2])


def test_render_value_falls_back_when_the_cell_shows_no_number():
    # nothing to copy a shape from, so the value renders plainly
    assert _render_value("Coeff.", 0.25) == "0.25"
    assert _render_value("", 1200.0) == "1200"


def test_render_value_empties_a_cell_for_none():
    assert _render_value("0.31**", None) == ""


# ------------------------------------------------------------- to_frame ---


def test_superscript_stars_skips_a_cell_whose_text_is_not_in_a_run():
    """Defensive: `w:t` outside a `w:r` is invalid OOXML, but Word has
    shipped stranger, and a cell that reads as starred must not be
    rewritten when there is no run to rewrite."""
    xml = document(
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="800"/></w:tblGrid>'
        '<w:tr><w:tc><w:p w14:paraId="AA">'
        "<w:t>-0.250***</w:t>"          # no enclosing w:r
        "</w:p></w:tc></w:tr></w:tbl>")
    t = read_all(xml)[0]
    assert t.rows[0][0] == "-0.250***"   # it does read as starred
    out, n = superscript_stars(xml, t)
    assert (n, out) == (0, xml)


def test_to_frame_pads_short_rows_to_the_header_width():
    pd = pytest.importorskip("pandas")
    t = Table(index=0, start=0, end=0,
              rows=[["Country", "Score", "N"], ["Poland", "0.31"]])
    df = to_frame(t)
    assert list(df.columns) == ["Country", "Score", "N"]
    assert df.iloc[0].tolist() == ["Poland", "0.31", ""]
    assert isinstance(df, pd.DataFrame)


def test_to_frame_can_take_a_later_header_row():
    pytest.importorskip("pandas")
    t = Table(index=0, start=0, end=0,
              rows=[["OLS", "", ""], ["Country", "Score", "N"],
                    ["Poland", "0.31", "512"]])
    df = to_frame(t, header_row=1)
    assert list(df.columns) == ["Country", "Score", "N"]
    assert len(df) == 1


# ------------------------------------------------- coordinate systems -----


def _spanned_table() -> str:
    def tc(text, span=None):
        s = f'<w:gridSpan w:val="{span}"/>' if span else ""
        return (f'<w:tc><w:tcPr><w:tcW w:w="800" w:type="dxa"/>{s}</w:tcPr>'
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")
    return document(
        "<w:tbl><w:tblGrid>"
        + "".join('<w:gridCol w:w="800"/>' for _ in range(4))
        + "</w:tblGrid>"
        + "<w:tr>" + tc("LABEL") + tc("MERGED", span=2) + tc("LAST")
        + "</w:tr>"
        + "<w:tr>" + tc("a") + tc("b") + tc("c") + tc("d") + "</w:tr>"
        + "</w:tbl>")


def test_rows_and_set_cell_share_one_coordinate_system():
    """Both are CELL indices, so a merged row stays self-consistent."""
    xml = _spanned_table()
    t = read_all(xml)[0]
    assert t.rows[0] == ["LABEL", "MERGED", "LAST"]     # 3 cells, 4 columns
    out = set_cell(xml, t, 0, 2, "WRITTEN")
    assert read_all(out)[0].rows[0] == ["LABEL", "MERGED", "WRITTEN"]


def test_grid_columns_exposes_where_the_two_systems_diverge():
    xml = _spanned_table()
    t = read_all(xml)[0]
    assert t.grid_columns(xml, 0) == [0, 1, 3]   # cell 2 starts at column 3
    assert t.grid_columns(xml, 1) == [0, 1, 2, 3]   # no span: they coincide


def test_grid_columns_rejects_a_row_that_is_not_there():
    xml = _spanned_table()
    with pytest.raises(AnchorError, match="cannot read row"):
        read_all(xml)[0].grid_columns(xml, 9)


def test_grid_rows_widens_a_span_across_the_columns_it_covers():
    """The rectangle a CSV needs: cell-indexed rows would misalign it."""
    xml = _spanned_table()
    t = read_all(xml)[0]
    assert t.rows[0] == ["LABEL", "MERGED", "LAST"]          # 3 cells
    assert t.grid_rows(xml)[0] == ["LABEL", "MERGED", "MERGED", "LAST"]
    assert t.grid_rows(xml)[1] == ["a", "b", "c", "d"]       # unmerged: same


def _vmerged_table() -> str:
    """A row label merged down over two rows, as Table 1 of FLOPs has it."""
    def tc(text, vmerge=None):
        v = f'<w:vMerge{vmerge}/>' if vmerge is not None else ""
        return (f"<w:tc><w:tcPr>{v}</w:tcPr>"
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")
    return document(
        "<w:tbl><w:tblGrid>"
        + "".join('<w:gridCol w:w="800"/>' for _ in range(2))
        + "</w:tblGrid>"
        + "<w:tr>" + tc("Training", vmerge=' w:val="restart"') + tc("Export")
        + "</w:tr>"
        + "<w:tr>" + tc("", vmerge="") + tc("Domestic") + "</w:tr>"
        + "</w:tbl>")


def test_grid_rows_carries_a_vertical_merge_down_to_its_continuation():
    """A continuation <w:tc> holds no text: read plainly, the label is lost."""
    xml = _vmerged_table()
    t = read_all(xml)[0]
    assert t.rows[1] == ["", "Domestic"]                     # what is stored
    assert t.grid_rows(xml)[1] == ["Training", "Domestic"]   # what is read


def test_grid_rows_falls_back_to_the_widest_row_without_a_grid():
    """A hand-built fragment may carry no tblGrid; the shape still holds."""
    xml = document("<w:tbl>" + row("a", "b") + "</w:tbl>")
    t = read_all(xml)[0]
    assert t.grid_rows(xml) == [["a", "b"]]


def test_the_fallback_width_COUNTS_a_span_rather_than_the_cell():
    """Without a tblGrid the width is the widest row, and a row with a
    merged cell is wider than its cell count says — measured as cells,
    the rectangle comes out one column short and every value after the
    merge lands under the wrong heading."""
    def tc(text, span=None):
        s = f'<w:gridSpan w:val="{span}"/>' if span else ""
        return (f"<w:tc><w:tcPr>{s}</w:tcPr>"
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")

    xml = document("<w:tbl>"                       # no tblGrid at all
                   + "<w:tr>" + tc("MERGED", span=3) + "</w:tr>"
                   + "<w:tr>" + tc("a") + tc("b") + tc("c") + "</w:tr>"
                   + "</w:tbl>")

    grid = read_all(xml)[0].grid_rows(xml)

    assert grid == [["MERGED", "MERGED", "MERGED"], ["a", "b", "c"]]


def test_an_EMPTY_table_has_a_width_of_none_rather_than_raising():
    xml = document("<w:tbl></w:tbl>")

    assert read_all(xml)[0].grid_rows(xml) == []


# The fallback width's `default=` is EQUIVALENT at any value: it is
# reached only when the table has no rows at all, and the loop that uses
# the width then produces nothing either way.
#
# `_Span.group(n)` returns the located XML whatever `n` is — it exists to
# offer `re.Match`'s slice, not its groups — so every mutation of the
# argument in a `tc.group(0)` / `tr.group(0)` call in this module is
# EQUIVALENT by construction. That is most of what a mutation run leaves
# here, and it is a property of the type rather than a gap in these
# tests.


# ------------------------------------------------------ stale offsets -----


def test_a_table_read_before_an_edit_is_refused_not_misapplied():
    """The hazard the docstrings could only ask callers to avoid.

    Every edit returns a new string and shifts every later offset, so a
    Table read beforehand slices the wrong bytes — silently, because the
    slice is still plausible-looking XML.
    """
    from docxkit.tables import bottom_border, fit_columns, superscript_stars
    xml = _spanned_table()
    stale = read_all(xml)[0]                    # read BEFORE the edit
    edited, _ = bottom_border(xml, stale)

    for fn in (fit_columns, superscript_stars, bottom_border):
        with pytest.raises(AnchorError, match="different version"):
            fn(edited, stale)                   # stale offsets
    with pytest.raises(AnchorError, match="different version"):
        set_cell(edited, stale, 0, 0, "x")


def test_re_reading_after_an_edit_is_what_the_error_asks_for():
    from docxkit.tables import bottom_border
    xml = _spanned_table()
    once, _ = bottom_border(xml, read_all(xml)[0])
    twice, n = bottom_border(once, read_all(once)[0])   # re-read: fine
    assert n == 0 and twice == once


def test_a_hand_built_table_is_not_anchored_to_any_source():
    """to_frame and the value tests construct Tables directly; those
    carry no offsets to go stale, so they must not be refused."""
    t = Table(index=0, start=0, end=0, rows=[["a"], ["1"]])
    assert t.source is None
    # The guard every other to_frame test in this file carries; this one
    # was missed, and it was the single test in 1,386 that a pandas-free
    # environment failed. It sits AFTER the source assertion so the
    # staleness contract — the thing this test is named for — still runs
    # where pandas is absent.
    pytest.importorskip("pandas")
    assert to_frame(t).shape == (1, 1)


# --------------------------------------------------- the facade contract --


def test_the_tables_facade_still_offers_every_name():
    """`tables` is a facade over _table_core and _table_layout; the
    import path is the API the papers build against."""
    import docxkit.tables as T
    for name in T.__all__:
        assert hasattr(T, name), f"{name} vanished from the facade"
    for name in ("_TR_RE", "_TC_RE", "_SPAN_RE", "_RUN_RE", "_cell_text",
                 "_render_value", "_table_spans", "_const", "_bump",
                 "_round_to", "_ARIAL", "_ARIAL_NARROW"):
        assert hasattr(T, name), f"{name} vanished from the facade"


def test_the_table_layers_stay_one_directional():
    """Layout may lean on the core; the core must not know about widths,
    or the two concerns are one concern again."""
    import ast
    from pathlib import Path

    import docxkit
    src = Path(docxkit.__file__).parent
    core = ast.parse((src / "_table_core.py").read_text(encoding="utf-8"))
    for node in ast.walk(core):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in ("_table_layout", "tables"), (
                f"_table_core imports {node.module} — that is a cycle")


# --- finding a table by its header, at the edges (2026-08-19) ----------
#
# `find` walks the tables and skips the ones too NARROW to carry the
# header asked for. Both ends of that test were free: no fixture asked
# for a header exactly as wide as the table's, and none put a narrow
# table BEFORE the matching one — which is the ordinary manuscript,
# because a one-column layout table is how these papers set a display
# equation.


def test_a_header_exactly_as_wide_as_the_table_matches():
    """`len(cells) < len(header)`, not `<=`: asking for every column by
    name is the precise form of the query, and skipping it would leave
    only the loose ones — the shape most likely to match two tables."""
    tables = read_all(_doc())

    found = find(tables, ["Country", "AFI (initial)", "Dif."])

    assert found.index == 0


def test_a_NARROW_table_before_the_match_does_not_end_the_search():
    """`continue`, not `break`. A display equation in these papers is a
    one-column table, so the manuscript's first table is routinely
    narrower than anything a caller asks for — under `break` the search
    stops there and the paper's real tables become unfindable."""
    xml = document(
        table(row("θ = 1"))
        + table(row("Country", "AFI (initial)"), row("Poland", "0.31")))

    found = find(read_all(xml), ["Country", "AFI"])

    assert found.index == 1
    assert found.rows[1] == ["Poland", "0.31"]


def test_the_refusal_shows_the_first_THREE_columns_of_each_table():
    """`t.header[:3]`: the message is read next to the document and its
    job is to let a person recognise the table they meant. A whole
    twelve-column header per table is a paragraph, and the first three
    are what a header is recognised by."""
    xml = document(
        table(row("Country", "AFI (initial)", "Dif.", "Rank", "Weight"),
              row("Poland", "0.31", "0.02", "4", "1.0")))

    with pytest.raises(AnchorError) as exc:
        find(read_all(xml), ["Nonexistent"])

    assert "['Country', 'AFI (initial)', 'Dif.']" in str(exc.value)
    assert "Rank" not in str(exc.value)


# --- the _table_core run of 2026-08-20: 8.7 % --------------------------


def test_the_row_JUST_PAST_the_last_is_refused_by_name():
    """`row >= len(trs)`. One past the end is the index a loop reaches,
    and the existing fixture asked for row 9 of a two-row table — which
    every comparison refuses. At the boundary the mutant falls through
    to `trs[row]` and the caller gets an IndexError out of a method
    whose contract is an AnchorError naming the table."""
    xml = _spanned_table()

    with pytest.raises(AnchorError, match="cannot read row"):
        read_all(xml)[0].grid_columns(xml, 2)


def test_the_shape_of_a_table_with_NO_rows_is_zero_by_zero():
    """`max(..., default=0)`. A table element with no `w:tr` is what a
    template leaves behind, and a width of -1 or 1 for it is a number
    that goes on to size a grid."""
    assert Table(index=0, start=0, end=0, rows=[]).shape == (0, 0)


def test_a_column_SKIPS_the_rows_that_are_too_short():
    """`len(r) > index`, which is a guard against a ragged table — the
    shape a merged cell leaves in `rows` — and every fixture for it was
    rectangular. Off by one, the guard admits the row whose last index
    is one below the column asked for, and the read raises IndexError
    from inside a getter."""
    ragged = Table(index=0, start=0, end=0,
                   rows=[["Country", "AFI"], ["Poland"], ["Chile", "0.62"]])

    assert ragged.column(1) == ["0.62"]

    # and a row with NO cells, which is what `>` and `!=` disagree
    # about: the row above is one short of the column asked for, where
    # both readings skip it. `<w:tr/>` with nothing in it is real —
    # `booktabs` guards for it too — and inequality lets it through into
    # an IndexError inside a getter.
    empty = Table(index=0, start=0, end=0,
                  rows=[["Country", "AFI"], [], ["Chile", "0.62"]])

    assert empty.column(1) == ["0.62"]


def test_row_named_reads_the_DATA_rows_and_ALL_of_them():
    """`self.rows[1:]`: the header is not a data row, and the first data
    row is. A table whose header's leading cell repeats a label — a
    "Total" column head above a "Total" line — answers with the header
    under one mutant and misses the row entirely under the other, and a
    fixture whose label sits anywhere else cannot see either."""
    t = Table(index=0, start=0, end=0,
              rows=[["Total", "2019"], ["Total", "5"], ["Other", "7"]])

    assert t.row_named("Total") == ["Total", "5"]


def test_a_vertical_merge_that_RESTARTS_empty_carries_nothing_down():
    """`v.group(1) != "restart"`, and the restart branch is only visible
    when the restarting cell is EMPTY: `cell or carried` gives the
    cell's own text whenever it has any, so a restart with a label
    reads the same under either operator.

    A merge group that restarts with no label is a real row — the FLOPs
    table has one where an unnamed block follows a named one — and
    carrying the previous group's label into it invents a value the
    document does not show."""
    def tc(text, vmerge=None):
        v = f"<w:vMerge{vmerge}/>" if vmerge is not None else ""
        return (f"<w:tc><w:tcPr>{v}</w:tcPr>"
                f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")

    xml = document(
        "<w:tbl><w:tblGrid>" + '<w:gridCol w:w="800"/>' * 2 + "</w:tblGrid>"
        + "<w:tr>" + tc("Training", ' w:val="restart"') + tc("Export")
        + "</w:tr><w:tr>" + tc("", "") + tc("Domestic")
        + "</w:tr><w:tr>" + tc("", ' w:val="restart"') + tc("Inference")
        + "</w:tr><w:tr>" + tc("", "") + tc("Training") + "</w:tr></w:tbl>")

    assert read_all(xml)[0].grid_rows(xml) == [
        ["Training", "Export"], ["Training", "Domestic"],
        ["", "Inference"], ["", "Training"]]


def test_to_frame_pads_a_row_missing_MORE_than_one_cell():
    """`width - len(row)`, which agrees with `width % len(row)` for a
    row one cell short of a three-column header — the only fixture this
    had. Two cells short of four is where they part, and a frame built
    with the wrong pad is a column of data misaligned against its
    heading rather than an error."""
    pytest.importorskip("pandas")
    t = Table(index=0, start=0, end=0,
              rows=[["Country", "AFI", "Gap", "N"], ["Poland", "0.31"]])

    assert to_frame(t).iloc[0].tolist() == ["Poland", "0.31", "", ""]


# Argued rather than pinned, from the same run:
#
# * every `tc.group(1)` / `tr.group(-1)` mutant — seventeen of them —
#   was equivalent because `_Span.group` ignored its argument and
#   handed back the whole element for any index. It raises now, so they
#   are killed by the tests that already walk those calls.
# * `len(r) is not index` in `column`. Both sides are small ints, and
#   CPython hands out one object for each below 257; a table with more
#   than 256 columns is not a table.
# * `xml.find("<w:tbl>", pos) != -1` written `> -1` and `is not -1`.
#   `find` answers -1 or an offset, and -1 is one of the integers
#   CPython caches.
# * `t.start > para.start()` in `by_caption` written `>=`. Two elements
#   cannot begin at the same offset in one string.
# * `except ValueError` in `parse_number`, mutated to an exception the
#   body cannot raise. `_NUM_RE` has already matched sign, digits,
#   separators and at most one decimal point, and the substitutions
#   strip the separators — what reaches `float` is always a float.
# * the `@overload` decorators and the `*` in an overload's signature:
#   typing, which no test run evaluates.
# * the fallback width's `default=0` written `-1`. It is reached only by
#   a table with no rows, and both `[""] * 0` and `[""] * -1` are the
#   empty row the walk then writes nothing into.
# * `t.start > para.start()` in `tables_after` written `>=`: two
#   elements cannot begin at the same offset in one string.


def test_set_cell_refuses_the_row_and_the_column_JUST_PAST_the_last():
    """The same boundary as `grid_columns`, in the writer. One past the
    end is the index a loop reaches, and past it the guard hands back an
    IndexError from inside a function whose contract is an AnchorError
    naming the table and the count."""
    xml = document(
        '<w:tbl><w:tblGrid><w:gridCol w:w="800"/></w:tblGrid>'
        "<w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>")
    t = read_all(xml)[0]

    with pytest.raises(AnchorError, match="cannot set row 1"):
        set_cell(xml, t, row=1, col=0, text="x")
    with pytest.raises(AnchorError, match="cannot set column 1"):
        set_cell(xml, t, row=0, col=1, text="x")


def test_a_bare_TABLE_fragment_is_found():
    """The scan starts at offset 0, and a caller holding one table
    rather than a document is the ordinary way this module is used from
    a paper's own script — `read_all(body)` where `body` IS the table.
    Starting one character in loses it, and the answer is an empty list
    rather than an error."""
    tbl = ('<w:tbl><w:tblGrid><w:gridCol w:w="800"/></w:tblGrid>'
           "<w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc></w:tr>"
           "</w:tbl>")

    tables = read_all(tbl)

    assert [t.rows for t in tables] == [[["a"]]]


def test_a_table_whose_ROWS_disagree_with_the_xml_is_refused():
    """`strict=True` on the zip of cells against stored cells. The two
    come from one walk and cannot normally disagree — but a `Table` is
    a public dataclass a caller can build, and a rectangle read from a
    row it does not describe is silently short a column, which is the
    misalignment `grid_rows` exists to prevent."""
    xml = document(
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>b</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
    real = read_all(xml)[0]
    short = Table(index=real.index, start=real.start, end=real.end,
                  rows=[["a"]], source=real.source)

    with pytest.raises(ValueError, match="shorter"):
        short.grid_rows(xml)


# --- _table_core's whole survivor list, 2026-08-20: 1.7 % (7/415) -----
#
# Measured WHOLE for the first time (the earlier figure of 1.0 % came
# from a run that stopped at 675 of 903 mutants, and flattered). Six of
# the seven are equivalent, each checked with `kill_check`:
#
# * the two `@overload` decorators, mutated away. Overloads are
#   declarations for the type checker; the runtime binds the
#   implementation under them either way, and `mypy` and `pyright` are
#   two of the five gates.
# * the `*` in those same two overload signatures, read as `/`. Same
#   interface constraint the survivor tool already discounts elsewhere
#   — it does not recognise them inside an `@overload` stub.
# * `grid_rows`' `default=0` on the widest-row `max`, read as -1. The
#   default is reached only for a table with NO rows, and the loop that
#   would use the width does not run for one.
# * `tables_after`'s `t.start > para.start()` read as `>=`. A table and
#   a paragraph cannot begin at the same offset in one string.
#
# The seventh is the test above.


# ------------------------------------------- prose that shadows a caption ---
#
# Body prose cross-references a table by number at the end of a sentence
# — house style, so most papers have it. On AFI's `working.docx` that
# sentence sits 395,000 characters ahead of the caption, and taking the
# first paragraph CONTAINING "Table 3." took the prose: repkit's G4
# reported "no table under caption 'Table 3.'" on a manuscript that
# plainly has one (2026-08-21).

def test_by_caption_prefers_the_paragraph_the_caption_OPENS():
    xml = document(
        para(run("Four ECA economies have positive values, as do "
                 "the EU and Table 3."))
        + para(run("Some other prose."))
        + para(run("Table 3. Distribution of workers"))
        + table(row("Country", "Share"), row("Poland", "0.31")))

    found = by_caption(xml, "Table 3.")

    assert found is not None and found.header == ["Country", "Share"]


def test_prose_that_shadows_a_caption_does_not_hand_back_ITS_neighbour():
    """The silent half, and the worse one: with an uncaptioned table
    beside the shadowing prose, the old anchor returned that table with
    no error at all — which `required=True` cannot fire on, and a caller
    reordering rows would then edit the wrong exhibit."""
    xml = document(
        para(run("Four ECA economies have positive values, as do "
                 "the EU and Table 3."))
        + table(row("Wrong", "Table"), row("a", "b"))
        + para(run("Table 3. Distribution of workers"))
        + table(row("Country", "Share"), row("Poland", "0.31")))

    found = by_caption(xml, "Table 3.")

    assert found is not None and found.header == ["Country", "Share"]


def test_tables_after_takes_the_CAPTION_as_its_anchor_too():
    """Same anchor, same reason: counting from the prose counts the
    wrong tables, and this one asserts a COUNT — so it would refuse a
    correct exhibit or accept the exhibit next door."""
    xml = document(
        para(run("As reported in Table 3."))
        + table(row("Wrong", "Table"))
        + para(run("Table 3. Distribution"))
        + table(row("Country", "Share"))
        + table(row("Country", "Block")))

    found = tables_after(xml, "Table 3.", count=2)

    assert [t.header[1] for t in found] == ["Share", "Block"]


def test_the_FIRST_paragraph_opening_with_the_caption_wins():
    """A continuation caption — "Table 3. (continued)" over the second
    half of a long table — opens with the same words. The exhibit is the
    first one; taking the last hands back the continuation's table and
    every row before it stays unedited."""
    xml = document(
        para(run("Table 3. Distribution"))
        + table(row("Country", "Share"))
        + para(run("Table 3. (continued)"))
        + table(row("Country", "Rest")))

    found = by_caption(xml, "Table 3.")

    assert found is not None and found.header == ["Country", "Share"]


def test_clone_row_refuses_the_row_ONE_PAST_the_end():
    """`>=`, not `>`: a table with five rows has no row 5, and the
    difference between the two spellings is an AnchorError naming the
    table and an IndexError from inside the walk."""
    xml = _countries()
    t = read_all(xml)[0]

    with pytest.raises(AnchorError, match="cannot clone row 5"):
        clone_row(xml, t, len(t.rows))


def test_a_caption_run_INLINE_is_still_found():
    """Some papers do run the caption into the paragraph, so "contains"
    stays as the fallback — it is only the PREFERENCE that changed."""
    xml = document(
        para(run("Notes and then Table 7. Something inline"))
        + table(row("Country", "Share")))

    found = by_caption(xml, "Table 7.")

    assert found is not None and found.header == ["Country", "Share"]


# ------------------------------------------------------------ the rows ---
#
# "Apply one country order to Tables 1, 3, 4, 5, A3 and A4" and "add a
# four-row benchmark block to Table 1" are two ordinary referee asks,
# and neither had a toolkit path: ~40 lines of `w:tr` regex to reorder
# with a gate, ~25 more to clone a row as a template and fill it.

def _countries() -> str:
    return document(
        para(run("Table 1. By country"))
        + table(row("Country", "Score"),
                row("UZB", "1.0"), row("ALB", "2.0"), row("POL", "3.0"),
                row("All", "2.0")))


def _by_name(order: list[str]):
    return lambda cells: order.index(cells[0])


def test_reorder_rows_permutes_the_DATA_rows_only():
    xml = _countries()
    t = read_all(xml)[0]

    out = reorder_rows(xml, t, key=_by_name(["ALB", "POL", "UZB", "All"]))

    assert [r[0] for r in read_all(out)[0].rows] == [
        "Country", "ALB", "POL", "UZB", "All"]


def test_reorder_rows_keeps_a_TOTAL_row_at_the_bottom():
    """"All countries" sorts under A and belongs under everything. A
    key that has to encode that is a key every paper writes twice."""
    xml = _countries()
    t = read_all(xml)[0]

    out = reorder_rows(xml, t, key=_by_name(["ALB", "POL", "UZB"]),
                       last=("All",))

    assert [r[0] for r in read_all(out)[0].rows] == [
        "Country", "ALB", "POL", "UZB", "All"]


def test_reorder_rows_carries_each_row_WHOLE():
    """The failure a row COUNT cannot see: values that slipped a column.
    Every cell travels with its row or the gate below fires."""
    xml = _countries()
    t = read_all(xml)[0]

    out = reorder_rows(xml, t, key=_by_name(["ALB", "POL", "UZB", "All"]))

    assert read_all(out)[0].rows[1] == ["ALB", "2.0"]


def test_reorder_rows_REFUSES_when_the_rows_themselves_moved(monkeypatch):
    """The gate is the reason this is worth sharing. Row count is
    preserved by any bug that swaps two cells; the multiset of every
    row's cells is not."""
    xml = _countries()
    t = read_all(xml)[0]
    splice = _table_core._rows_replaced
    monkeypatch.setattr(_table_core, "_rows_replaced",
                        lambda x, table, rows: splice(x, table, rows[:-1]))

    with pytest.raises(AnchorError, match="not just their order"):
        reorder_rows(xml, t, key=_by_name(["ALB", "POL", "UZB", "All"]))


def test_clone_row_copies_the_row_BELOW_itself_with_its_formatting():
    """A new row built from nothing has to invent the cell properties —
    borders, shading, widths — that make it look like the table it
    joins. The row above already has them."""
    xml = document(
        para(run("Table 1. By country"))
        + "<w:tbl><w:tr><w:tc><w:tcPr><w:shd w:fill=\"D9D9D9\"/></w:tcPr>"
        + para(run("UZB")) + "</w:tc></w:tr></w:tbl>")
    t = read_all(xml)[0]

    out = clone_row(xml, t, 0)

    assert out.count('w:fill="D9D9D9"') == 2
    assert [r[0] for r in read_all(out)[0].rows] == ["UZB", "UZB"]


def test_clone_row_makes_a_BLOCK_when_asked_for_several():
    xml = _countries()
    t = read_all(xml)[0]

    out = clone_row(xml, t, 1, count=3)

    assert [r[0] for r in read_all(out)[0].rows] == [
        "Country", "UZB", "UZB", "UZB", "UZB", "ALB", "POL", "All"]


def test_clone_row_refuses_a_row_that_is_not_there():
    xml = _countries()
    t = read_all(xml)[0]

    with pytest.raises(AnchorError, match="cannot clone row 9"):
        clone_row(xml, t, 9)
    with pytest.raises(AnchorError, match="at least 1"):
        clone_row(xml, t, 1, count=0)


def test_clone_row_counts_a_NEGATIVE_index_from_the_bottom():
    """`clone_row(t, -1, count=4)` is the natural spelling of this
    function's own motivating example — "a four-row block at the end" —
    and the splice reads `trs[:index + 1]`, so -1 made that `trs[:0]`
    and put the copies at the TOP, above the header. The guard only
    tested `index >= len(trs)`, so a negative walked straight past it.
    """
    xml = _countries()
    t = read_all(xml)[0]

    out = clone_row(xml, t, -1, count=2)

    assert [r[0] for r in read_all(out)[0].rows] == [
        "Country", "UZB", "ALB", "POL", "All", "All", "All"]
    with pytest.raises(AnchorError, match="cannot clone row -9"):
        clone_row(xml, t, -9)


def test_set_row_refuses_FEWER_values_than_the_row_has_cells():
    """The same half-filled row from the other side: the trailing cells
    would keep what they were cloned from — the old numbers under a new
    label — and `zip` said nothing about it. `None` is how a cell is
    left on purpose, so a short sequence has a spelling already."""
    xml = _countries()
    t = read_all(xml)[0]

    with pytest.raises(AnchorError, match="only 1 value"):
        set_row(xml, t, 1, ["BENCH"])


def test_set_row_writes_every_cell_it_is_given():
    xml = _countries()
    t = read_all(xml)[0]

    out = set_row(xml, t, 1, ["BENCH", "9.9"])

    assert read_all(out)[0].rows[1] == ["BENCH", "9.9"]


def test_set_row_takes_the_WHOLE_row_so_a_clone_is_never_half_filled():
    """A cloned row holds the values it was copied from, so filling
    three of its four cells leaves the fourth reading as the row above —
    true, plausible and wrong. `None` is how a cell is left on purpose."""
    xml = _countries()
    t = read_all(xml)[0]

    out = set_row(xml, t, 1, ["BENCH", None])

    assert read_all(out)[0].rows[1] == ["BENCH", "1.0"]


def test_set_row_blanks_the_TAIL_of_a_cell_split_across_runs():
    """Word splits a cell's text at an rsid boundary whenever it likes.
    Writing into the first run and leaving the rest keeps the old tail
    hanging off the new value — invisible in a row count, visible in the
    rendered table."""
    split = ("<w:tbl><w:tr><w:tc><w:p>" + run("UZ") + run("B")
             + "</w:p></w:tc></w:tr></w:tbl>")
    xml = document(para(run("Table 1. By country")) + split)
    t = read_all(xml)[0]

    out = set_row(xml, t, 0, ["ALB"])

    assert read_all(out)[0].rows[0] == ["ALB"]


def test_set_row_refuses_more_values_than_the_row_has_cells():
    """A merged cell makes a row SHORTER than the grid is wide, and a
    caller counting grid columns would silently write past the end."""
    xml = _countries()
    t = read_all(xml)[0]

    with pytest.raises(AnchorError, match="3 values were given"):
        set_row(xml, t, 1, ["a", "b", "c"])


def test_a_row_operation_refuses_a_table_read_from_OLDER_xml():
    """Every one of these returns a new string and shifts every later
    offset. The freshness guard is what turns "re-read between calls"
    from advice into a rule."""
    xml = _countries()
    t = read_all(xml)[0]
    out = clone_row(xml, t, 1)

    for call in (lambda: clone_row(out, t, 1),
                 lambda: set_row(out, t, 1, ["x", "y"]),
                 lambda: reorder_rows(out, t, key=_by_name(
                     ["UZB", "ALB", "POL", "All"]))):
        with pytest.raises(AnchorError):
            call()


#
# `trs[:index + 1] + [trs[index]] * count + trs[index + 1:]` in
# `clone_row` is EQUIVALENT to the `index`/`index` spelling and left
# alive: the copy is the row it came from, so a run of n+1 identical
# rows sits in the same place whichever side the copies go on. The
# spelling stays because "immediately after it" is what the docstring
# promises and what a reader checks against.


# `_table_core`'s other real survivors from the 2026-08-21 round,
# argued:
#
# `_beside`'s `m.start() < below.start` -> `<=`. A caption paragraph and
# a table cannot begin at the same offset, so the two spellings decide
# every document alike.
#
# `_Span.group(index=0)` -> `index=1`, which makes a bare `.group()`
# raise. Nothing in the package calls it bare — all 26 call sites pass
# 0 — and the argument exists to REFUSE a group this stub has not got.
#
# `max(..., default=0)` in `grid_rows` -> `default=1`: reached only for
# a `w:tbl` holding no `w:tr` at all, which is not a table Word writes
# and not one this module can be handed by `read_all`.
