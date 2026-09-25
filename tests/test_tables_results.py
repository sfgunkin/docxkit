"""A RESULTS cell: number, superscript stars, and a standard error below.

BACKLOG S2 (Misconceptions W7, 770 cells): `set_cell` put the whole text
in the first run and blanked the rest, so the stars printed full size
and a two-line cell lost its SE line — and every cell read back exactly
as written, so nothing saw it. `set_cell` now routes stars and refuses
the second line; `set_result` writes all three.
"""
from __future__ import annotations

import re

import pytest
from conftest import document, make_parts, para

from docxkit._xml import PARA_RE, visible_text
from docxkit.errors import AnchorError
from docxkit.lint import lint_parts
from docxkit.tables import by_caption, set_cell, set_result

SUP = '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
ITALIC = "<w:rPr><w:i/></w:rPr>"


def r(text: str, rpr: str = "") -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def results(cell_xml: str) -> str:
    """A captioned results table: a header, and one row holding the cell."""
    return document(
        para(r("Table 4. Estimates"))
        + "<w:tbl><w:tr><w:tc>" + para(r("Variable")) + "</w:tc><w:tc>"
        + para(r("(1)")) + "</w:tc></w:tr><w:tr><w:tc>"
        + para(r("Age")) + "</w:tc><w:tc>" + cell_xml
        + "</w:tc></w:tr></w:tbl>")


STARRED = para(r("0.012"), r("**", SUP))
TWO_LINE = (para(r("0.012"), r("**", SUP))
            + para(r("("), r("0.004", ITALIC), r(")")))


def cell(xml: str) -> str:
    t = by_caption(xml, "Table 4.")
    cells: list[str] = re.findall(r"<w:tc>.*?</w:tc>", xml[t.start:t.end],
                                  re.DOTALL)
    return cells[-1]


def lines(xml: str) -> list[list[tuple[str, bool, bool]]]:
    """Each line of the cell: its text runs as (text, superscript, italic)."""
    return [[(visible_text(run), 'w:val="superscript"' in run, "<w:i/>" in run)
             for run in re.findall(r"<w:r>.*?</w:r>", p.group(0), re.DOTALL)
             if visible_text(run)]
            for p in PARA_RE.finditer(cell(xml))]


def test_set_cell_puts_the_STARS_in_the_superscript_run():
    xml = results(STARRED)

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.017***")

    assert lines(out) == [[("0.017", False, False), ("***", True, False)]]


def test_set_cell_writing_text_that_is_NOT_a_result_behaves_as_before():
    xml = results(STARRED)

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "n/a")

    assert lines(out) == [[("n/a", False, False)]]


def test_set_cell_REFUSES_a_two_line_cell_unless_asked_to_flatten():
    xml = results(TWO_LINE)
    table = by_caption(xml, "Table 4.")

    with pytest.raises(AnchorError, match=r"more than one line.*set_result"):
        set_cell(xml, table, 1, 1, "0.017***")
    flat = set_cell(xml, table, 1, 1, "x", flatten=True)
    assert visible_text(cell(flat)) == "x"


def test_set_result_writes_the_number_the_stars_and_the_SE_line():
    """The SE keeps its italic run and its parentheses keep theirs."""
    xml = results(TWO_LINE)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="***", se="0.005")

    assert lines(out) == [
        [("0.017", False, False), ("***", True, False)],
        [("(", False, False), ("0.005", False, True), (")", False, False)]]


def test_set_result_CLONES_a_star_run_when_the_cell_had_none():
    xml = results(para(r("0.012")))

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="*")

    assert lines(out) == [[("0.017", False, False), ("*", True, False)]]


def test_set_result_with_NO_stars_empties_the_star_run():
    xml = results(STARRED)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017")

    assert lines(out) == [[("0.017", False, False)]]


def test_set_result_GROWS_a_second_line_for_the_SE_when_there_is_none():
    xml = results('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                  + r("0.012") + r("**", SUP) + "</w:p>")

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.004")

    assert lines(out)[1] == [("(0.004)", False, False)]
    second = list(PARA_RE.finditer(cell(out)))[1].group(0)
    assert '<w:jc w:val="center"/>' in second, "the first line's pPr"


def test_a_second_line_is_LEFT_ALONE_without_se():
    xml = results(TWO_LINE)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.020",
                     stars="*")

    assert lines(out)[1] == lines(xml)[1]


def test_stars_that_are_not_asterisks_are_refused():
    xml = results(STARRED)

    with pytest.raises(ValueError, match="asterisks"):
        set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.1",
                   stars="+")


# --- the review of 2026-09-24: nine gaps in the fix above ---------------


def results_row(*cells: str) -> str:
    """A captioned table whose data row holds `cells` after its label."""
    tcs = "".join(f"<w:tc>{c}</w:tc>" for c in cells)
    heads = "".join(f"<w:tc>{para(r(f'({i})'))}</w:tc>"
                    for i in range(1, len(cells) + 1))
    return document(
        para(r("Table 4. Estimates"))
        + "<w:tbl><w:tr><w:tc>" + para(r("Variable")) + "</w:tc>" + heads
        + "</w:tr><w:tr><w:tc>" + para(r("Age")) + "</w:tc>" + tcs
        + "</w:tr></w:tbl>")


def line_texts(xml: str) -> list[str]:
    return [visible_text(p.group(0)) for p in PARA_RE.finditer(cell(xml))]


def test_UPDATE_keeps_the_stars_superscript():
    """Gap 1: `update` — the documented regenerate-from-data path —
    still wrote every cell through `set_run_text`."""
    from docxkit.tables import update
    xml = results(STARRED)

    out, _ = update(xml, by_caption(xml, "Table 4."), [[0.0171]],
                    row0=1, col0=1)

    assert lines(out) == [[("0.017", False, False), ("**", True, False)]]


def test_UPDATE_refuses_a_coefficient_over_its_SE():
    """Its text reads as ONE string, so the old SE rode onto line 1 as the
    number's suffix — ``0.017** (0.004)`` — and the SE line emptied."""
    from docxkit.tables import update
    xml = results(TWO_LINE)

    with pytest.raises(AnchorError, match="set_result"):
        update(xml, by_caption(xml, "Table 4."), [[0.0171]], row0=1, col0=1)


def test_SET_ROW_keeps_the_stars_superscript():
    from docxkit.tables import set_row
    xml = results(STARRED)

    out = set_row(xml, by_caption(xml, "Table 4."), 1, [None, "0.017***"])

    assert lines(out) == [[("0.017", False, False), ("***", True, False)]]


def test_FLATTEN_puts_a_result_on_ONE_line_with_its_stars_raised():
    """Gap 2: the star branch ignored `flatten` and spliced the old SE
    back under the new coefficient: ['0.017***', '(0.004)']."""
    xml = results(TWO_LINE)

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.017***",
                   flatten=True)

    assert line_texts(out) == ["0.017***", ""]
    assert lines(out)[0] == [("0.017", False, False), ("***", True, False)]


@pytest.mark.parametrize("se_line", [
    para(r("("), r("0.0", ITALIC), r("10", ITALIC), r(")")),
    para(r("("), r("0.004", ITALIC), r(")"), r(" ")),
])
def test_the_SE_stays_italic_however_many_runs_its_line_has(se_line):
    """Gap 3: any count but three wrote "(se)" into the upright "(" run —
    13 of 42 SEs in Misconceptions Table 6."""
    xml = results(para(r("0.012"), r("**", SUP)) + se_line)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.005")

    assert [t for t in lines(out)[1] if t[0].strip()] == [
        ("(", False, False), ("0.005", False, True), (")", False, False)]


def test_set_cell_CLONES_a_star_run_in_a_table_that_raises_its_stars():
    """Gap 4: a bare coefficient that has just become significant, beside
    a starred one."""
    xml = results_row(STARRED, para(r("0.012")))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 2, "0.017**")

    assert lines(out) == [[("0.017", False, False), ("**", True, False)]]


def test_set_cell_leaves_FULL_SIZE_stars_in_a_table_that_prints_them_so():
    """The other half of gap 4: no superscript star anywhere in the table
    is that paper's house, and a clone would break it."""
    xml = results(para(r("0.012**")))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.017***")

    assert lines(out) == [[("0.017***", False, False)]]


def test_an_NBSP_paragraph_is_NOT_a_second_line():
    """Gap 5: 141 real cells were refused as two-line, and following the
    refusal's advice corrupted them."""
    xml = results(para(r("Country")) + para(r(" ")))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "Economy")

    assert line_texts(out)[0] == "Economy"


def test_a_result_stacked_with_a_LINE_BREAK_is_refused():
    """The other half of gap 5: coefficient and SE in ONE paragraph were
    not refused, and the SE was blanked."""
    stacked = para(r("0.012"), r("**", SUP), "<w:r><w:br/></w:r>",
                   r("("), r("0.004", ITALIC), r(")"))
    xml = results(stacked)
    table = by_caption(xml, "Table 4.")

    with pytest.raises(AnchorError, match="more than one line"):
        set_cell(xml, table, 1, 1, "0.017***")
    with pytest.raises(AnchorError, match="broken inside a paragraph"):
        set_result(xml, table, 1, 1, "0.017", stars="***")


def test_a_table_with_TRACKED_CHANGES_is_refused_by_every_writer():
    """Gap 6: `set_result` wrote inside the `w:ins`, so reject-all gave
    ``0.012*`` for ``0.012**``, and its clones copied revision ids."""
    from docxkit.tables import set_row
    tracked = para('<w:ins w:id="7" w:author="R" '
                   'w:date="2026-09-24T00:00:00Z">'
                   + r("0.015") + "</w:ins>", r("**", SUP))
    xml = results(tracked)
    table = by_caption(xml, "Table 4.")

    for write in (lambda: set_result(xml, table, 1, 1, "0.017", stars="*"),
                  lambda: set_cell(xml, table, 1, 1, "0.017*"),
                  lambda: set_row(xml, table, 1, [None, "0.017*"])):
        with pytest.raises(AnchorError, match="tracked changes"):
            write()


def test_set_result_finds_the_SE_line_past_an_EMPTY_spacer():
    """Gap 7: by raw paragraph index the spacer was the "SE line", and
    the old SE went on printing under the new one."""
    xml = results(para(r("0.012"), r("**", SUP)) + para()
                  + para(r("("), r("0.004", ITALIC), r(")")))

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="***", se="0.005")

    assert line_texts(out) == ["0.017***", "", "(0.005)"]


def test_a_LEADING_superscript_marker_does_not_take_the_stars():
    """Gap 8: ``[a (sup)][0.012]`` printed ``**0.017``."""
    xml = results_row(STARRED, para(r("a", SUP), r("0.012")))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 2, "0.017**")

    assert visible_text(cell(out)) == "0.017**"
    assert lines(out) == [[("0.017", False, False), ("**", True, False)]]


def test_a_line_with_ONLY_a_superscript_run_gets_a_plain_one():
    """Gap 8, second half: it raised, where the old writer wrote the text
    (Job Tenure, Table 4, the Moldova row)."""
    xml = results(para(r("a", SUP)))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "12")

    assert lines(out) == [[("12", False, False)]]


def test_a_cloned_run_does_NOT_copy_the_number_runs_tab():
    """Gap 9: the star run was the whole number run re-styled, so its
    `w:tab` came too and the stars printed at the next tab stop."""
    xml = results(para('<w:r><w:tab/><w:t>0.012</w:t></w:r>'))

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.004")

    assert cell(out).count("<w:tab/>") == 1
    assert line_texts(out) == ["0.017**", "(0.004)"]


# --- a cell with NO run (BACKLOG S2, 2026-09-25) -------------------------
# 9,360 of 81,386 cells in a 150-manuscript sample: every blank cell Word
# writes. `set_run_text` writes into an existing `w:t` or nowhere, so the
# write vanished — and `update` reported the cell CHANGED.


def test_set_cell_WRITES_into_a_cell_with_no_run():
    xml = results("<w:p/>")

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.5")

    assert line_texts(out) == ["0.5"]


def test_update_does_what_its_report_says_on_a_blank_cell():
    from docxkit.tables import update
    xml = results("<w:p/>")

    out, changes = update(xml, by_caption(xml, "Table 4."), [[0.5]],
                          row0=1, col0=1)

    assert [c.new for c in changes] == ["0.5"]
    assert by_caption(out, "Table 4.").rows[1][1] == "0.5"


def test_the_new_run_takes_the_paragraph_MARKs_properties():
    """What Word uses for text typed into an empty paragraph."""
    xml = results('<w:p><w:pPr><w:jc w:val="center"/>'
                  "<w:rPr><w:b/></w:rPr></w:pPr></w:p>")

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.5",
                     stars="**")

    assert re.search(r"<w:r><w:rPr><w:b/></w:rPr><w:t[^>]*>0\.5</w:t>",
                     cell(out))
    assert lines(out) == [[("0.5", False, False), ("**", True, False)]]


def test_the_written_cell_LINTS_clean():
    xml = results(TWO_LINE)
    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="***", se="0.005")
    body = out[out.index("<w:body>") + 8:out.index("</w:body>")]

    assert lint_parts(make_parts(body)) == []
