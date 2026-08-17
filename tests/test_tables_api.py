"""The table API's optional and refusal paths.

`find` and `by_caption` take `required=False` so a caller can probe for
a table that may not exist; `parse_number` and the value renderer decide
what a cell means. These are the seams the paper scripts build on, and
they were the last uncovered branches in the module.
"""
from __future__ import annotations

import pytest
from conftest import document, para, row, run, table

from docxkit.errors import AnchorError
from docxkit.tables import (
    Table,
    _render_value,
    by_caption,
    find,
    parse_number,
    read_all,
    set_cell,
    superscript_stars,
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


def test_by_caption_returns_none_when_the_caption_trails_every_table():
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 7. A caption with no table after it")))
    assert by_caption(xml, "Table 7.", required=False) is None


def test_by_caption_says_which_half_failed():
    """A missing caption and a caption with no table are different
    problems, and the message has to say which — the builders locate
    ten tables by caption and a wrong one is a silent mis-edit."""
    xml = document(
        table(row("Country", "Score"))
        + para(run("Table 7. A caption with no table after it")))
    with pytest.raises(AnchorError, match="no paragraph containing"):
        by_caption(xml, "Table 9.")
    with pytest.raises(AnchorError, match="has no table after it"):
        by_caption(xml, "Table 7.")


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
