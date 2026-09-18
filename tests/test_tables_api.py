"""The table API's optional and refusal paths.

`find` and `by_caption` take `required=False` so a caller can probe for
a table that may not exist; `parse_number` and the value renderer decide
what a cell means. These are the seams the paper scripts build on, and
they were the last uncovered branches in the module.
"""
from __future__ import annotations

import re

import pytest
from conftest import document, ins, para, row, run, table

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


def _image() -> str:
    """A paragraph holding a picture — the exhibit that is not a table."""
    return ('<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Chart"/>'
            '<a:blip r:embed="rId7"/></wp:inline></w:drawing></w:r></w:p>')


def test_a_FIGURE_caption_does_not_take_the_LAST_table_above_it():
    """HCW's `working.docx`, and it cost that paper every table it has.

    The exhibits end `[Table 8][cap Figure 1][image]`, so "Figure 1."
    had no table under it and the table above was its only candidate —
    which is exactly the shape the propagation exists to honour. It
    handed Table 8's table over, and each table caption above it then
    shifted one exhibit up.

    The UNCAPTIONED grid at the top is what lets that run all the way:
    HCW sets equations (1) and (2) in 1x2 tables, so "Table 1." has two
    candidates of its own and the chain is forced only from the figure
    end. Twelve of the paper's nineteen gate tests went red on numbers
    read out of the wrong table, and eight lookups came back wrong
    without one of them being a `None` that `required=True` could fire
    on.
    """
    xml = document(
        table(row("AYWC = ...", "(2)"))
        + para(run("Table 1. Health-Capacity to Work Estimates"))
        + table(row("Country", "MW"), row("Poland", "3.1"))
        + para(run("Table 2. Trends in mortality"))
        + table(row("Country", "MEA"), row("Albania", "63.0"))
        + para(run("Figure 1. Mortality-equivalent age"))
        + _image())

    assert by_caption(xml, "Table 1.").header == ["Country", "MW"]
    assert by_caption(xml, "Table 2.").header == ["Country", "MEA"]
    assert by_caption(xml, "Figure 1.", required=False) is None


def test_a_figure_whose_PANELS_ARE_a_table_still_gets_it():
    """The other half of the same paper: HCW's Figure 8 is a 2x2 grid of
    panel images, a real table under a Figure caption. A picture inside a
    table sits after that table's start, so the nearer exhibit is the
    table — which is what keeps the rule above from taking this one away.
    """
    xml = document(
        para(run("Figure 8. Additional Years of Work Capacity"))
        + table(row("a. 1990 as base year", "b. 2000 as base year"),
                row(_image(), _image())))

    found = by_caption(xml, "Figure 8.")

    assert found is not None
    assert found.header == ["a. 1990 as base year", "b. 2000 as base year"]


def test_a_picture_behind_ANOTHER_caption_is_not_THIS_captions_exhibit():
    """The picture has to be unclaimed, on the same evidence a table
    does. Here "Table 7." sits underneath its table and Figure 2's
    caption stands between it and the next image: read that image as
    this caption's exhibit and the table above is orphaned instead.
    """
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 7. A caption underneath its table"))
        + para(run("Figure 2. Labor-Force Participation"))
        + _image())

    assert by_caption(xml, "Table 7.").header == ["Country", "Score"]


def _horizontal_rule() -> str:
    """Word's horizontal rule. `<w:pict>` is the VML spelling, which is
    also how a pasted image arrives — so the picture scan sees one."""
    return ('<w:p><w:r><w:pict><v:rect id="_x0000_s1026" o:hr="t" '
            'style="width:0;height:1.5pt"/></w:pict></w:r></w:p>')


def test_a_rule_after_a_table_caption_does_not_take_its_table_away():
    """A caption reading "Table 1." names a table whatever follows it.

    With the caption UNDERNEATH its table there is no table below to
    rule a later picture out, so ANY `<w:pict>` after it — a horizontal
    rule, a pasted logo, the next figure two pages down — answered "this
    caption owns a picture" and the lookup came back with nothing. Under
    `required=True`, which is the default, it raised: for a table
    sitting directly above the caption that named it.
    """
    body = (table(row("Country", "Score"), row("Poland", "1.0"))
            + para(run("Table 1. A caption underneath its table")))
    xml = document(body)
    assert by_caption(xml, "Table 1.").header == ["Country", "Score"]

    with_rule = document(body + _horizontal_rule())
    assert by_caption(with_rule, "Table 1.").header == ["Country", "Score"]


def test_nor_does_a_logo_further_down_the_document():
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 1. A caption underneath its table"))
        + para(run("Some discussion of the results."))
        + _image())
    assert by_caption(xml, "Table 1.").header == ["Country", "Score"]


# --- where a caption, a table and a picture sit (2026-09-18) -----------
#
# `_sides` and `_owns_an_image` are eight comparisons over four offsets,
# and 29 of this module's survivors sit on them. Asked through
# `by_caption`, most of a wrong answer is repaired by the propagation in
# `_beside` — which is what the propagation is FOR — so a fixture that
# moves a boundary by one paragraph still comes back with the right
# table and pins nothing. These ask the two functions directly, where a
# boundary is a boundary.


def _pieces(xml: str) -> tuple[list[re.Match[str]], list[Table], list[int]]:
    """The three lists `_sides` reads: the BODY's paragraphs, the
    tables, and the picture offsets.

    A table's cells hold paragraphs of their own, and `PARA_RE` finds
    those too — so the first fixture here asked about a cell's paragraph
    and passed for the wrong reason. `_beside` reads captions by their
    text, which no cell paragraph here matches; this reads them by
    position, so it has to leave the cells out itself."""
    from docxkit._xml import PARA_RE
    tables = read_all(xml)
    paras = [m for m in PARA_RE.finditer(xml)
             if not any(t.start <= m.start() < t.end for t in tables)]
    return (paras, tables,
            [m.start() for m in _table_core._IMAGE_RE.finditer(xml)])


def _cap(xml: str) -> str:
    return para(run(xml))


def test_the_table_below_is_the_NEAREST_one_after_the_caption():
    """`t.start >= para.end()`: at or after, not exactly at. A caption
    with a sentence between it and its table — a note, a lead-in line —
    is ordinary, and read as "starts exactly where the caption ends" it
    has no table below at all."""
    xml = document(_cap("Table 1. Caption") + _cap("A lead-in sentence.")
                   + table(row("A", "1")))
    paras, tables, images = _pieces(xml)

    assert _table_core._sides(paras[0], tables, [paras[0]], images) == tables


def test_the_table_above_is_the_NEAREST_one_before_the_caption():
    """`t.end <= para.start()`, the mirror of it, for the captions this
    package keeps finding underneath their tables."""
    xml = document(table(row("A", "1")) + _cap("A closing sentence.")
                   + _cap("Table 1. Caption"))
    paras, tables, images = _pieces(xml)

    assert _table_core._sides(paras[1], tables, [paras[1]], images) == tables


def test_a_caption_between_takes_the_table_BELOW_out_of_reach():
    """The refusal `_sides` exists for, with the other caption a
    paragraph away — so "starts exactly at this caption's end" does not
    see it, and identity on two offsets past 256 does not either."""
    xml = document(_cap("Table 1. Caption") + _cap("Prose between them.")
                   + _cap("Table 2. Caption") + table(row("A", "1")))
    paras, tables, images = _pieces(xml)
    captions = [paras[0], paras[2]]

    assert _table_core._sides(paras[0], tables, captions, images) == []


def test_the_caption_DIRECTLY_under_this_one_counts_as_between():
    """The same refusal at the boundary itself: the next caption starts
    exactly where this paragraph ends, which a STRICT test misses — and
    two captions in a row is what a run of exhibits looks like."""
    xml = document(_cap("Table 1. Caption") + _cap("Table 2. Caption")
                   + table(row("A", "1")))
    paras, tables, images = _pieces(xml)

    assert _table_core._sides(paras[0], tables, paras[:2], images) == []


def test_a_caption_between_takes_the_table_ABOVE_out_of_reach():
    """The above side, with the blocking caption a paragraph away from
    the table — the shape that tells `==` from `<=` there."""
    xml = document(table(row("A", "1")) + _cap("Prose after the table.")
                   + _cap("Table 1. Caption") + _cap("Table 2. Caption"))
    paras, tables, images = _pieces(xml)
    captions = [paras[1], paras[2]]

    assert _table_core._sides(paras[2], tables, captions, images) == []


def test_the_caption_DIRECTLY_under_the_table_counts_as_between():
    """And with it flush against the table, which is where a strict
    bound stops seeing it."""
    xml = document(table(row("A", "1")) + _cap("Table 1. Caption")
                   + _cap("Table 2. Caption"))
    paras, tables, images = _pieces(xml)

    assert _table_core._sides(paras[1], tables, paras, images) == []


def test_a_TABLE_caption_keeps_its_table_with_a_picture_in_between():
    """`_sides(..., figure=False)` is the default, and the label is what
    sets it: a caption reading "Table 1." names a table whatever follows
    it. Defaulted the other way, the picture between this caption and
    its table answers for it and the lookup comes back empty — which is
    the incident `_owns_an_image` opens with, arriving through the
    default instead of through the label."""
    xml = document(_cap("Table 1. Caption") + _image()
                   + table(row("Country", "Score")))
    paras, tables, images = _pieces(xml)

    assert _table_core._sides(paras[0], tables, [paras[0]], images) == tables


def test_a_picture_BEFORE_the_caption_is_not_its_exhibit():
    """`i >= para.end()`: the picture has to be AFTER the caption. Read
    as "any picture at all", the image belonging to the exhibit above
    answers for this caption, and the table under it is orphaned."""
    xml = document(_image() + _cap("Figure 1. Caption") + table(row("A", "1")))
    paras, tables, images = _pieces(xml)
    below = tables[0]

    assert _table_core._owns_an_image(paras[1], below, [paras[1]], images,
                                      figure=True) is False


def test_a_table_BEFORE_the_picture_is_the_nearer_exhibit():
    """`below.start < picture` — the table wins when it comes first, and
    the picture wins when IT does. An inequality that only asks whether
    the two differ hands every figure caption its table back."""
    xml = document(_cap("Figure 1. Caption") + _image() + table(row("A", "1")))
    paras, tables, images = _pieces(xml)

    assert _table_core._owns_an_image(paras[0], tables[0], [paras[0]],
                                      images, figure=True) is True


def test_a_caption_between_takes_the_PICTURE_out_of_reach():
    """The picture must be unclaimed on the same evidence a table is,
    and the caption that claims it may be the very next paragraph."""
    xml = document(_cap("Figure 1. Caption") + _cap("Figure 2. Caption")
                   + _image())
    paras, _tables, images = _pieces(xml)

    assert _table_core._owns_an_image(paras[0], None, paras[:2], images,
                                      figure=True) is False


def test_a_caption_between_at_a_DISTANCE_takes_it_too():
    """The same, with a paragraph in the gap: what tells `<=` from `==`
    and from identity."""
    xml = document(_cap("Figure 1. Caption") + _cap("Prose between them.")
                   + _cap("Figure 2. Caption") + _image())
    paras, _tables, images = _pieces(xml)

    assert _table_core._owns_an_image(paras[0], None, [paras[0], paras[2]],
                                      images, figure=True) is False


def test_a_caption_AFTER_the_picture_does_not_take_it():
    """The upper bound of that same test. A caption further down the
    document belongs to the next exhibit, and counted here it takes this
    caption's own picture away — leaving a figure caption holding the
    table above it."""
    xml = document(_cap("Figure 1. Caption") + _image()
                   + _cap("Figure 2. Caption"))
    paras, _tables, images = _pieces(xml)

    assert _table_core._owns_an_image(paras[0], None,
                                      [paras[0], paras[2]], images,
                                      figure=True) is True


def test_a_caption_running_INLINE_still_names_a_table():
    """`figures.get(para.span(), False)` — the label of a caption the
    pattern did not match. `_caption_para` falls back to a paragraph
    that merely CONTAINS the caption, and such a paragraph has no label
    to read: taken for a FIGURE caption it can own a picture, and the
    picture two paragraphs down then takes its table away.

    Read as a table caption it keeps the conservative answer, which is
    the one the docstring states."""
    xml = document(
        table(row("Country", "Score"), row("Poland", "1.0"))
        + _cap("As the EU shows, see Table 1. for the decomposition.")
        + _image())

    found = by_caption(xml, "Table 1.")

    assert found is not None and found.header == ["Country", "Score"]


def test_reorder_rows_pairs_the_two_ROW_COUNTS_past_256():
    """`len(shown) != len(trs)` and `sum(shown) != len(table.rows)`, the
    guard that says the view walk and the row walk disagree. Read as
    identity they answer "disagree" for any table with more rows than
    CPython caches integers for — 257 of them — and the refusal it
    raises names a docxkit bug on a table that is perfectly well formed.

    An appendix data table of this size is ordinary; it is the fixtures
    that are small."""
    rows = [row(f"r{i:03}", str(256 - i)) for i in range(257)]
    xml = document(table(*rows))
    table_read = read_all(xml)[0]

    out = reorder_rows(xml, table_read, key=lambda cells: cells[0],
                       header=0)

    assert [r[0] for r in read_all(out)[0].rows[:3]] == ["r000", "r001",
                                                        "r002"]


def test_a_figure_caption_owns_a_PASTED_picture_too():
    """`_IMAGE_RE` reads two spellings, and only one of them was held by
    any test in the package: `w:drawing`, which is what INSERTING a
    picture writes. `w:pict` is the VML spelling Word writes for a
    PASTED one — the ordinary case for anybody who copies a figure in —
    and without it this caption has no picture to own, so it takes the
    table above instead and that table's own caption loses it.

    A census on 2026-09-18 deleted the alternative with all 8,000 tests
    green.

    The picture stands between the caption and the table, so it is the
    only thing that can decide this: read as no picture at all, the
    figure caption takes the table under it."""
    pasted = ('<w:p><w:r><w:pict><v:shape id="_x0000_i1025" '
              'style="width:300pt;height:200pt"><v:imagedata r:id="rId8"/>'
              "</v:shape></w:pict></w:r></w:p>")
    xml = document(
        para(run("Figure 3. A pasted chart")) + pasted
        + table(row("Country", "Score"), row("Poland", "1.0"))
        + para(run("Table 4. A caption underneath its table")))

    assert by_caption(xml, "Figure 3.", required=False) is None
    assert by_caption(xml, "Table 4.").header == ["Country", "Score"]


def test_a_gridSpan_of_more_than_nine_columns_is_read_whole():
    """`_SPAN_RE`'s `(\\d+)`, which nothing held: every fixture in the
    suite spans two or three columns, and `(\\d)` reads those exactly as
    well. A summary row spanning a twelve-column table — the shape that
    tells them apart — then reads as spanning ONE, and every cell after
    it lands a column early.

    The pattern is also the one that just gained its `\\s*` for a
    producer that closes the tag with a space, so the two members are
    pinned apart: this fixture closes it tight."""
    wide = ("<w:tbl><w:tblGrid>" + "<w:gridCol w:w=\"600\"/>" * 12
            + "</w:tblGrid>"
            + "<w:tr><w:tc><w:tcPr><w:gridSpan w:val=\"12\"/></w:tcPr>"
            + para(run("Panel A. Whole-table heading")) + "</w:tc></w:tr>"
            + "<w:tr>" + "".join(
                f"<w:tc>{para(run(str(i)))}</w:tc>" for i in range(12))
            + "</w:tr></w:tbl>")
    read = read_all(document(wide))[0]

    grid = read.grid_rows(document(wide))

    assert len(grid[0]) == 12
    assert grid[0] == ["Panel A. Whole-table heading"] * 12
    assert grid[1] == [str(i) for i in range(12)]


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


def test_grid_columns_reads_a_span_closed_WITH_A_SPACE():
    """`<w:gridSpan w:val="2" />` is the same merge (5,183 in 8 corpus
    packages are written so). Read only as `…"/>`, the merged cell
    counted as one column and every cell after it sat one column early."""
    xml = re.sub(r'(<w:gridSpan w:val="\d+")/>', r"\1 />", _spanned_table())
    assert '" />' in xml
    t = read_all(xml)[0]

    assert t.grid_columns(xml, 0) == [0, 1, 3]
    assert t.grid_rows(xml)[0] == ["LABEL", "MERGED", "MERGED", "LAST"]


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


def test_the_row_and_cell_patterns_say_what_they_MATCH():
    """`_TR_RE` and `_TC_RE` are re-exports for the paper scripts —
    `_table_core` itself never uses them — and the facade test above
    pins their NAMES. What they match is what the callers use, and
    nothing in the package stated it: a census on 2026-09-18 deleted
    `re.DOTALL` from each and every member of the row pattern with the
    suite still green.

    Imported through `tables`, which is the path those callers take.

    Three statements, one per member the census could reach: rows and
    cells are matched NON-GREEDILY, so two of them are two matches and
    not one; the match runs across the newlines a pretty-printed part
    carries (`re.DOTALL`); and a self-closing `<w:tr/>` — a row with no
    children, which the schema allows — is not an opening tag, so a
    pattern reading one as the start of a row cannot swallow everything
    up to the next real row's end.
    """
    from docxkit.tables import _TC_RE, _TR_RE

    part = ("<w:tbl>\n<w:tr>\n<w:tc>\n<w:p/>\n</w:tc>\n</w:tr>\n"
            "<w:tr>\n<w:tc>\n<w:p/>\n</w:tc>\n<w:tc>\n<w:p/>\n</w:tc>\n"
            "</w:tr>\n</w:tbl>")

    rows = [m.group(0) for m in _TR_RE.finditer(part)]
    assert len(rows) == 2, "two rows, matched one at a time"
    assert [len(_TC_RE.findall(r)) for r in rows] == [1, 2]
    assert all(r.endswith("</w:tr>") and "\n" in r for r in rows)

    empty_first = "<w:tr/>\n" + rows[1]
    assert [m.group(0) for m in _TR_RE.finditer(empty_first)] == [rows[1]]


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


# --- a row the VIEW hides ---------------------------------------------
#
# The case the row-count guard fired on, and the one no fixture here
# carried: a row-level revision makes the document's row list and the
# view's row list different lengths, so pairing them by index moves the
# wrong rows. The guard refused instead and said "re-read it before
# reordering", which reproduces the identical refusal — it is a property
# of the transform, not a stale handle.

def _six_countries() -> str:
    """Seven rows, of which the `final` view shows five: two data rows
    carry a row-level `w:del`, so the two lists differ by two.

    Counts chosen so a wrong list cannot coincide with the right one:
    seven raw rows, five in the view, four of them movable."""
    return document(
        para(run("Table 5. By country"))
        + table(row("Country", "Score"),
                row("POL", "0.31"),
                row("MDA", "0.42", revision="del", rid=95),
                row("ALB", "0.22"),
                row("UZB", "0.15"),
                row("KGZ", "0.19", revision="del", rid=96),
                row("SRB", "0.28")))


def test_reorder_rows_SORTS_a_table_holding_a_row_level_deletion():
    """It refused, and told the caller to do the one thing that cannot
    help. One country order across Tables 1, 3, 4, 5, A3 and A4 over a
    Word Compare redline is the documented core workflow, and a redline
    is where row-level deletions live."""
    xml = _six_countries()
    t = read_all(xml)[0]
    assert [r[0] for r in t.rows] == ["Country", "POL", "ALB", "UZB", "SRB"], \
        "the fixture only bites if the two row lists really differ"

    out = reorder_rows(xml, t, key=_by_name(["ALB", "POL", "SRB", "UZB"]))

    assert [r[0] for r in read_all(out)[0].rows] == [
        "Country", "ALB", "POL", "SRB", "UZB"]
    assert read_all(out)[0].rows[1] == ["ALB", "0.22"], \
        "and every cell travelled with its row"


def test_a_row_the_view_HIDES_keeps_its_place_and_its_cells():
    """Where the deleted rows go is the question the pairing has to
    answer, and "nowhere" is the answer: they are not in the order the
    caller sorted, so they hold the slots they had. Read in `original`,
    which is the only view that can see them at all."""
    xml = _six_countries()

    out = reorder_rows(xml, read_all(xml)[0],
                       key=_by_name(["ALB", "POL", "SRB", "UZB"]))

    assert [r[0] for r in read_all(out, view="original")[0].rows] == [
        "Country", "ALB", "MDA", "POL", "SRB", "KGZ", "UZB"]
    assert [r[1] for r in read_all(out, view="original")[0].rows] == [
        "Score", "0.22", "0.42", "0.31", "0.28", "0.19", "0.15"], \
        "the hidden rows keep their own values, not a neighbour's"


def test_the_MIRROR_case_an_inserted_row_read_as_original():
    """The exposure is not only deletions. An inserted row survives into
    `final` — counts stay equal, and reorder always worked there — but
    it is gone from `original`, which `by_caption` and `tables_after`
    both hand out."""
    xml = document(
        para(run("Table 3. By country"))
        + table(row("Country", "Score"),
                row("POL", "0.31"),
                row("ZZZ", "0.99", revision="ins", rid=97),
                row("ALB", "0.22"),
                row("UZB", "0.15")))

    out = reorder_rows(xml, read_all(xml, view="original")[0],
                       key=_by_name(["ALB", "POL", "UZB"]))

    assert [r[0] for r in read_all(out, view="original")[0].rows] == [
        "Country", "ALB", "POL", "UZB"]
    assert [r[0] for r in read_all(out)[0].rows] == [
        "Country", "ALB", "ZZZ", "POL", "UZB"], \
        "and the inserted row kept the slot it was inserted at"


def test_reorder_rows_still_refuses_when_the_two_lists_CANNOT_be_paired(
        monkeypatch):
    """The guard that is left. It no longer fires on a row-level
    revision — that is what the pairing accounts for — so what reaches
    it is the row walk and the view transform disagreeing about what a
    row is, which is a defect here and says so instead of sending the
    caller round the re-read loop again."""
    xml = _six_countries()
    t = read_all(xml)[0]
    monkeypatch.setattr(_table_core, "rows_in_view",
                        lambda body, view: [True] * 7)

    with pytest.raises(AnchorError, match="could not be paired"):
        reorder_rows(xml, t, key=_by_name(["ALB", "POL", "SRB", "UZB"]))


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


#  --- a handle that only MOVED is not a handle that went wrong --------
#
# Found 2026-08-24 on Health_Capacity_to_Work, styling one caption's TWO
# panels. The guard compared a whole-DOCUMENT fingerprint, so editing the
# LATER table invalidated the handle on the EARLIER one — even though
# nothing before it had moved, and even though the loop was written in
# reverse for exactly that reason:
#
#     for t in reversed(tables_after(xml, "Table 9.", count=2)):
#         xml, _ = house(xml, t)        # AnchorError on the second pass
#
# The message was right and still did not prevent it: "re-read after
# every edit" reads as *after every edit to THIS table*, and the fix
# people reach for — re-locating once per pass — fails the same way.
# `tables_after` invites it by returning a LIST: the API hands you
# several handles and only the first was usable.


def _two_panels() -> str:
    return document(
        para(run("Table 9. Two panels"))
        + table(row("Panel A", "n"), row("Men", "1"))
        + table(row("Panel B", "n"), row("Women", "2")))


def test_the_batch_loop_the_API_invites_now_WORKS():
    """The whole finding, as the caller wrote it: fetch the batch, edit
    each. Reverse order, so no earlier table's offsets are disturbed."""
    xml = _two_panels()

    for t in reversed(tables_after(xml, "Table 9.", count=2)):
        xml = set_cell(xml, t, 1, 1, "9")

    assert [r[1] for r in read_all(xml)[0].rows] == ["n", "9"]
    assert [r[1] for r in read_all(xml)[1].rows] == ["n", "9"]


def test_an_edit_to_ANOTHER_table_leaves_this_handle_usable():
    """The narrow claim underneath it. Editing table 1 moves nothing
    inside table 0, so table 0's handle still means what it meant."""
    xml = _two_panels()
    first, second = read_all(xml)

    xml = set_cell(xml, second, 1, 1, "22")
    out = set_cell(xml, first, 1, 1, "11")

    assert read_all(out)[0].rows[1] == ["Men", "11"]
    assert read_all(out)[1].rows[1] == ["Women", "22"]


def test_a_FORWARD_loop_is_refused_because_the_handle_really_did_move():
    """The other order, and the reason `tables_after`'s docstring says to
    run in reverse. Editing panel A shifts panel B's offsets, so B's own
    bytes are no longer at them — indistinguishable, without searching
    the document for its content, from B having been rewritten. It is
    refused, and the message says to re-read."""
    xml = _two_panels()
    first, second = read_all(xml)
    grown = set_cell(xml, first, 1, 0, "Men and women of working age")

    with pytest.raises(AnchorError, match="MOVED this table or rewrote it"):
        set_cell(grown, second, 1, 1, "9")


def test_a_table_whose_OWN_content_changed_is_still_refused():
    """The case the guard exists for. These bytes are not at these
    offsets any more, and the handle is not a way to find them."""
    xml = _two_panels()
    t = read_all(xml)[0]
    out = set_cell(xml, t, 1, 1, "9")

    with pytest.raises(AnchorError, match="different version"):
        set_cell(out, t, 1, 0, "Men and women")


def test_editing_ONE_of_two_identical_panels_does_not_redirect_the_handle():
    """The regression that killed the first draft of this fix, found by
    review and reproduced four times.

    That draft re-resolved a stale handle by searching the document for
    its bytes, guarded on the match being UNIQUE. The guard cannot fire
    here, because the edit that makes the handle stale is the same edit
    that destroys the twin: after panel 1 is written, panel 2 is the only
    byte-match left, so the second call silently rewrote the OTHER panel.
    Content is not identity when content is what an edit changes.
    """
    twin = table(row("Country", "Estimate"), row("Poland", ""))
    xml = document(para(run("Table 9. Two panels")) + twin + twin)
    t = read_all(xml)[0]
    step = set_cell(xml, t, 1, 1, "0.31")

    with pytest.raises(AnchorError, match="different version"):
        set_cell(step, t, 1, 0, "Poland (rural)")

    assert read_all(step)[1].rows[1] == ["Poland", ""], \
        "the untouched panel stays untouched"


def test_a_handle_from_a_DIFFERENT_document_does_not_bind():
    """The whole-document hash was the only thing tying a `Table` to the
    file it was read from, and a content search throws that away.

    A clean build and its redline are two strings in one scope, and so
    are a manuscript and its journal copy; a swapped variable has to stay
    a loud refusal rather than become a silent write into the wrong
    document. Same table, two documents, captions of different lengths —
    so the shared table does not sit at the same offsets either.
    """
    shared = table(row("Country", "Estimate"), row("Poland", "0.31"))
    doc_a = document(para(run("Table 9. Manuscript A")) + shared)
    doc_b = document(para(run("Table 3. A different manuscript")) + shared)

    with pytest.raises(AnchorError, match="different version"):
        set_cell(doc_b, read_all(doc_a)[0], 1, 1, "X")


#  --- a mutator re-reads the table the way the CALLER read it --------


def _redline_panel() -> str:
    """Two data rows whose scores are tracked INSERTIONS, so the two
    views disagree about every one of them."""
    return document(
        para(run("Table 4. Scores"))
        + "<w:tbl>"
        + "<w:tr><w:tc>" + para(run("Country")) + "</w:tc><w:tc>"
        + para(run("Score")) + "</w:tc></w:tr>"
        + "<w:tr><w:tc>" + para(run("POL")) + "</w:tc><w:tc>"
        + para(ins("0.31", 90)) + "</w:tc></w:tr>"
        + "<w:tr><w:tc>" + para(run("ALB")) + "</w:tc><w:tc>"
        + para(ins("0.22", 91)) + "</w:tc></w:tr>"
        + "</w:tbl>")


def test_reorder_rows_audits_its_work_in_the_CALLERS_view():
    """`reorder_rows` re-read the result with the DEFAULT view whatever
    the caller had asked for, so a table read as `original` was permuted
    on one side of the tracked changes and audited against the other.

    The permutation was correct and the gate said `2 row(s) LOST, 2
    GAINED`. Two cells inside a `w:ins` is enough, which makes this
    ordinary on any redline rather than exotic — and `by_caption` and
    `tables_after` both hand callers an `original`-view handle.
    """
    xml = _redline_panel()
    before = read_all(xml, view="original")[0]
    assert [r[1] for r in before.rows[1:]] == ["", ""], \
        "the fixture only bites if the two views really disagree"

    out = reorder_rows(xml, before, key=lambda c: ["ALB", "POL"].index(c[0]))

    assert [r[0] for r in read_all(out, view="original")[0].rows[1:]] == \
        ["ALB", "POL"]
    assert [r[1] for r in read_all(out)[0].rows[1:]] == ["0.22", "0.31"], \
        "and the accepted side moved with it"


def test_the_KEY_is_given_the_cells_the_caller_read_too():
    """The other half, and the one that would have gone on being wrong
    silently. `key` was called with text scraped from the raw XML rather
    than from the view, so on a redline it saw both sides of every
    revision at once — an ordering function reading `0.310.22` where the
    caller's own `table.rows` says `0.31`."""
    xml = _redline_panel()
    seen: list[list[str]] = []

    def _by_country(cells: list[str]) -> str:
        seen.append(cells)
        return cells[0]

    reorder_rows(xml, read_all(xml)[0], key=_by_country)

    assert seen == [["POL", "0.31"], ["ALB", "0.22"]], \
        "the accepted side, which is what view='final' means"


def test_a_view_the_table_was_NOT_read_in_is_not_used():
    """The field is carried, not guessed: a handle read as `original`
    keeps saying so after a freshness re-check, or the audit silently
    goes back to the default."""
    xml = _redline_panel()
    first, = read_all(xml, view="original")
    grown = xml.replace("<w:body>", "<w:body>" + para(run("Preamble")))

    assert first.view == "original"
    assert _table_core._fresh(xml, first, "probe").view == "original"
    assert read_all(grown, view="final")[0].view == "final"


def test_a_HAND_BUILT_table_is_not_anchored_and_is_left_alone():
    """`source` is None on a Table nobody read out of a document, so the
    guard has nothing to compare and no business objecting."""
    loose = Table(index=0, start=0, end=0, rows=[["a"], ["1"]])

    assert _table_core._fresh("<w:document/>", loose, "probe") is loose


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
