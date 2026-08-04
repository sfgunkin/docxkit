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
