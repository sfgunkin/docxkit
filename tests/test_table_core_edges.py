"""`_table_core` — the shapes its 2026-09-29 sweep survivors needed.

The module measured whole at 178 real survivors of 2,048, nearly all in
code written after its last sweep: `set_result` and its fill helpers,
the decimal-comma reading, the line-aware `update`. Each test here names
the survivor it was written for; the argued rest is in equivalents.toml.
"""
from __future__ import annotations

import re
import typing

import pytest
from conftest import document, para, row, run, table
from lxml import etree
from test_tables_results import (
    ITALIC,
    STARRED,
    SUP,
    TWO_LINE,
    cell,
    line_texts,
    lines,
    r,
    results,
)

from docxkit import _table_core
from docxkit._xml import PARA_RE, RUN_RE, visible_text
from docxkit.errors import AnchorError
from docxkit.tables import (
    by_caption,
    clone_row,
    decimal_mark,
    parse_number,
    read_all,
    reorder_rows,
    set_cell,
    set_result,
    set_row,
    update,
)

#: A number run set at 10pt, and a star run set smaller and raised — the
#: two sizes a results table commonly gives them.
NUM10 = '<w:rPr><w:sz w:val="20"/></w:rPr>'
STAR7 = '<w:rPr><w:sz w:val="14"/><w:vertAlign w:val="superscript"/></w:rPr>'
MARK9 = '<w:rPr><w:sz w:val="18"/><w:vertAlign w:val="superscript"/></w:rPr>'


def sized(xml: str) -> list[list[tuple[str, bool, str | None]]]:
    """Each line of the results cell: its PRINTING runs as (text,
    superscript, half-point size) — what a reader sees, and at what size."""
    out = []
    for p in PARA_RE.finditer(cell(xml)):
        line = []
        for m in RUN_RE.finditer(p.group(0)):
            text = visible_text(m.group(0))
            if text:
                size = re.search(r'<w:sz w:val="(\d+)"/>', m.group(0))
                line.append((text, 'w:val="superscript"' in m.group(0),
                             size.group(1) if size else None))
        out.append(line)
    return out


def se_runs(xml: str) -> list[tuple[str, bool]]:
    """EVERY text run of the cell's second line, blanked ones included, as
    (text, italic): where the SE landed among the runs Word split it into.
    """
    second = list(PARA_RE.finditer(cell(xml)))[1].group(0)
    return [(visible_text(m.group(0)), "<w:i/>" in m.group(0))
            for m in RUN_RE.finditer(second)
            if re.search(r"<w:t\b", m.group(0))]


def paragraphs(xml: str) -> list[str]:
    """The cell's paragraphs in order, SELF-CLOSING ones included."""
    return [visible_text(p) for p in re.findall(
        r"<w:p\b[^>]*?/>|<w:p\b[^>]*>.*?</w:p>", cell(xml), re.DOTALL)]


# --- the typing contract ----------------------------------------------------


@pytest.mark.parametrize("function", [_table_core.find,
                                      _table_core.by_caption])
def test_find_and_by_caption_REGISTER_both_overloads(function):
    """`RemoveDecorator` on each of the four `@overload` lines. The
    overloads are why ``by_caption(xml, "Table 4.")`` types as a `Table`
    and not an `Optional` a paper script has to unwrap at every call; a
    stub that loses its decorator is a plain function silently rebound
    by the next `def`, and the contract is gone with no error anywhere
    at runtime. `typing.get_overloads` is where that contract lives."""
    overloads = typing.get_overloads(function)

    assert [(o.__annotations__["required"], o.__annotations__["return"])
            for o in overloads] == [("Literal[True]", "Table"),
                                    ("Literal[False]", "Table | None")]


# --- the decimal comma ------------------------------------------------------


def test_a_number_GROUPED_TWICE_is_thousands_even_in_a_decimal_comma_table():
    """`len(tails) > 1` read as `< 1` or `> 2`. Two commas can only be
    thousands groups, whatever the table's mark — so a population column
    in a table whose estimates print ``0,31`` must not be read as the
    decimal ``1.234.567``, which is no number at all and came back None.
    It also counts as evidence FOR the point: a tie between one grouped
    count and one decimal comma is no evidence either way."""
    assert parse_number("1,234,567", decimal=",") == 1234567.0
    assert decimal_mark(["1,234,567", "12,5"]) is None


def test_a_THREE_digit_head_is_still_the_ambiguous_shape():
    """`1 <= len(head) <= 3` read as `<= 2` or `< 3`. ``123,456`` is a
    count in an English table and 123.456 in a Russian one — the same
    question as ``1,234`` — so it must defer to the table, not be decided
    as a decimal comma by the string alone."""
    assert parse_number("123,456") == 123456.0
    assert parse_number("123,456", decimal=",") == pytest.approx(123.456)


def test_a_FOUR_digit_tail_is_a_decimal_comma_whatever_the_table_says():
    """`len(tails[0]) != 3` read as `< 3`. A thousands group is exactly
    three digits, so a Russian coefficient printed to four places —
    ``12,3456`` — says its comma is decimal; read as ambiguous, an
    English-defaulting table made it 123456."""
    assert parse_number("12,3456") == pytest.approx(12.3456)
    assert parse_number("12,3456", decimal=".") == pytest.approx(12.3456)


def test_a_TIE_reads_as_no_evidence_however_large_the_table():
    """`comma == point` read as `comma is point`. The two are counts of
    cells, and CPython shares int objects only up to 256: an appendix
    table of 50 countries by 12 columns is past that, and there a tie was
    settled as ``"."`` — the English reading made on no evidence at all."""
    assert decimal_mark(["0,5"] * 300 + ["0.5"] * 300) is None


# --- addressing a row -------------------------------------------------------


def test_a_negative_row_PAST_the_top_is_refused_not_wrapped():
    """`0 <= at` read as `-1 <= at`. ``set_row(t, -4, ...)`` on a
    three-row table is one row past the top; let through, the resolved
    index -1 is the LAST row, and a block meant for the head of the table
    is written over the bottom of it."""
    xml = document(table(row("Country", "N"), row("POL", "1"),
                         row("ALB", "2")))

    with pytest.raises(AnchorError) as exc:
        set_row(xml, read_all(xml)[0], -4, ["UZB", "3"])

    assert str(exc.value) == "table 0 has 3 rows, cannot set row -4"


def test_set_result_names_the_COLUMN_past_the_end():
    """`col >= len(tcs)` read as `>`, `==` or `is`. One past the last
    cell is the index a loop reaches, and past it the guard handed back a
    bare IndexError instead of the sentence that says which row is short
    — which, in a results table, is where a merged cell hides."""
    xml = results(STARRED)
    t = by_caption(xml, "Table 4.")

    for col in (2, 3):
        with pytest.raises(AnchorError) as exc:
            set_result(xml, t, 1, col, "0.017", stars="*")
        assert str(exc.value) == (f"row 1 has 2 cells, cannot set column "
                                  f"{col}")


# --- the refusals a reader acts on -----------------------------------------


def test_set_cell_QUOTES_the_first_twenty_characters_of_each_line():
    """The `[:20]` of `_write_text`'s refusal. The message is how a
    reader finds the cell — a two-line row LABEL here, the other thing
    that stacks in a results table — and it quotes each line to exactly
    twenty characters, so a long label is recognisable and still short."""
    xml = results(para(r("Log household income per capita"))
                  + para(r("(PPP, 2017 USD)")))

    with pytest.raises(AnchorError) as exc:
        set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "Log income")

    assert str(exc.value) == (
        "row 1 col 1 holds more than one line of text ('Log household "
        "income / (PPP, 2017 USD)'); one string cannot say what goes on "
        "which — use tables.set_result(..., se=...), or flatten=True")


def test_set_result_REFUSES_a_THIRD_line_and_quotes_all_three():
    """`len(lines) > 2` read as `> 3`, and the `[:20]` of the quote. A
    coefficient, its SE and a bootstrap p-value under it is not a number
    over its standard error: writing it as one left the p-value printing
    under a regenerated estimate it no longer belongs to."""
    xml = results(para(r("0.012"), r("**", SUP)) + para(r("(0.004)"))
                  + para(r("p = 0.003, wild bootstrap")))

    with pytest.raises(AnchorError) as exc:
        set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                   stars="**", se="0.005")

    assert str(exc.value) == (
        "row 1 col 1: not a number over its standard error ('0.012** / "
        "(0.004) / p = 0.003, wild boot') — lines broken inside a "
        "paragraph, or more than two")


def test_set_row_REFUSES_a_two_line_cell_by_default():
    """`flatten: bool = False` on `set_row`. Filling a cloned row whose
    coefficient sits over its SE would otherwise pull the old SE onto
    the coefficient's line and empty the second one — the S2 defect,
    back through the one writer whose default was not pinned."""
    xml = results(TWO_LINE)

    with pytest.raises(AnchorError, match="row 1 col 1 holds more than one"):
        set_row(xml, by_caption(xml, "Table 4."), 1, [None, "0.017***"])


def test_update_names_the_ROW_and_COLUMN_of_a_refused_cell():
    """`where=f"row {row0 + i} col {col0 + j}"`. The refusal is how a
    regeneration reports the one stacked cell in a block, and every other
    way of combining the offsets names a different cell: at row0=3,
    col0=3 the second row and column of the block are row 4, col 4, and
    no bitwise or other arithmetic operator lands there too."""
    body = [row(label, "0.10", "0.20", "0.30", "0.40")
            for label in ("Age", "Female", "Urban")]
    stacked = ("<w:tr>" + "".join(f"<w:tc>{para(run(c))}</w:tc>" for c in
                                  ("Income", "0.10", "0.20", "0.30"))
               + f"<w:tc>{para(run('0.012**'))}{para(run('(0.004)'))}"
               "</w:tc></w:tr>")
    xml = document(table(row("", "(1)", "(2)", "(3)", "(4)"), *body,
                         stacked))

    with pytest.raises(AnchorError) as exc:
        update(xml, read_all(xml)[0], [[0.21, 0.22], [0.31, 0.32]],
               row0=3, col0=3)

    assert str(exc.value) == (
        "row 4 col 4 holds more than one line of text ('0.012** / "
        "(0.004)'); one string cannot say what goes on which — use "
        "tables.set_result(..., se=...), or flatten=True")


# --- a blank cell ------------------------------------------------------------


def test_a_blank_cell_s_FIRST_empty_paragraph_takes_the_text():
    """`empty.start() < m.start()` read as `==`, `>`, `>=` or `is`. Word
    writes an empty paragraph self-closing, so a blank cell of two — the
    first bare, the second carrying its alignment — has only the SECOND
    as a paragraph the pattern can see. The text belongs in the first,
    the line a reader sees filled; it went into the second instead, and
    the value printed one line low."""
    xml = results('<w:p w14:paraId="0A0A0A0A"/>'
                  '<w:p><w:pPr><w:jc w:val="right"/></w:pPr></w:p>')

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.5")

    assert paragraphs(out) == ["0.5", ""]


def test_a_blank_cell_s_LATER_empty_paragraph_is_left_as_it_was():
    """`empty.start() < m.start()` read as `!=` or `is not`. An empty
    paragraph AFTER the one written into is not the writer's business,
    and expanding it rewrote a paragraph the edit never touched — noise
    in every compare of the clean build against the last one."""
    xml = results('<w:p><w:pPr><w:jc w:val="right"/></w:pPr></w:p>'
                  '<w:p w14:paraId="0B0B0B0B"/>')

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.5")

    assert paragraphs(out) == ["0.5", ""]
    assert '<w:p w14:paraId="0B0B0B0B"/>' in cell(out)


def test_set_result_into_a_BLANK_cell_grows_the_SE_line():
    """`len(lines) > 1` read as `!= 1`. A blank cell — a cloned row being
    filled, the usual way a new benchmark block is built — prints no line
    at all, so ``len(lines)`` is 0 and there is no second line to write
    the SE into: it has to be grown, not looked up."""
    xml = results("<w:p/>")

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.004")

    assert line_texts(out) == ["0.017**", "(0.004)"]


# --- the star run -----------------------------------------------------------


def test_the_cell_s_OWN_star_run_takes_the_stars_and_its_size():
    """`runs[at + 1:]` read as `runs[at + 2:]`, and `not _is_superscript`
    dropped from the SE line's model run. The stars belong in the run
    that already holds them, at ITS size — 7pt here beside a 10pt number;
    a clone of the number run printed them at 10pt. And a grown SE line
    takes the NUMBER's run, not the smaller raised one."""
    xml = results(para(r("0.012", NUM10), r("**", STAR7)))

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="***", se="0.005")

    assert sized(out) == [[("0.017", False, "20"), ("***", True, "14")],
                          [("(0.005)", False, "20")]]


def test_TWO_leading_markers_do_not_move_where_the_stars_go():
    """`runs[at + 1:]` read as `at << 1` or `at & 1`. With two superscript
    note markers before the number the plain run is the THIRD, and those
    readings either look past the star run (cloning a 10pt one) or back
    to the first marker (``**0.017``)."""
    xml = results(para(r("a,", SUP), r("b", SUP), r("0.012", NUM10),
                       r("*", STAR7)))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.017**")

    assert sized(out) == [[("0.017", False, "20"), ("**", True, "14")]]


def test_a_line_of_ONLY_superscript_runs_is_rebuilt_from_the_FIRST():
    """`runs[0]` read as `runs[-1]` or `runs[1]` in `_fill_result` and in
    the grown SE line, and the star run's `group(0)`, `raised=True` and
    `if stars`. A cell holding only note markers — "a" at 9pt, "b" at
    7pt — gets a plain number run, a raised star run and an SE line, all
    three in the FIRST run's properties, as the docstring promises."""
    xml = results(para(r("a", MARK9), r("b", STAR7)))

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.004")

    assert sized(out) == [[("0.017", False, "18"), ("**", True, "18")],
                          [("(0.004)", False, "18")]]


def test_an_EMPTIED_star_run_is_reused_and_the_stars_print_ONCE():
    """`number if sup or clone or not stars` read as `not sup`. A
    coefficient that lost its significance keeps an EMPTY star run, and
    once no star is left in the table it no longer counts as raising its
    stars. Regaining one then wrote the stars into the number AND into
    that run: ``0.017*`` + ``*`` — a significance level nobody estimated.
    """
    xml = results(STARRED)
    lost = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.009")

    out = set_cell(lost, by_caption(lost, "Table 4."), 1, 1, "0.017*")

    assert lines(out) == [[("0.017", False, False), ("*", True, False)]]


def test_FULL_SIZE_stars_after_a_leading_marker_stay_in_the_number():
    """`number + stars`, and `not stars` in the condition before it. A
    house that prints its stars full size, with a superscript note marker
    before the coefficient: the marker makes this a results line, and
    with no star run after the number the stars go INTO it. Every
    operator in place of the `+` raised; dropping the `not` lost them."""
    xml = results(para(r("a", SUP), r("0.012**")))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.017***")

    assert lines(out) == [[("0.017***", False, False)]]


# --- the SE line ------------------------------------------------------------


@pytest.mark.parametrize(("se_line", "expected"), [
    pytest.param(para(r("(0.004)")), [("(0.005)", False)], id="one-run"),
    pytest.param(para(r("("), r("0.004)")),
                 [("(0.005)", False), ("", False)], id="paren-joined"),
    pytest.param(para(r(" "), r("("), r("0.004)")),
                 [("(0.005)", False), ("", False), ("", False)],
                 id="lead-paren-joined"),
    pytest.param(para(r(" "), r("("), r("0.004", ITALIC), r(")")),
                 [("", False), ("(", False), ("0.005", True), (")", False)],
                 id="lead-house"),
    pytest.param(para(r("(", ITALIC), r("0.004", ITALIC), r(")", ITALIC)),
                 [("(", True), ("0.005", True), (")", True)],
                 id="all-italic"),
    pytest.param(para(r(" "), r("(", ITALIC), r("0.004", ITALIC),
                      r(")", ITALIC)),
                 [("", False), ("(", True), ("0.005", True), (")", True)],
                 id="lead-all-italic"),
    pytest.param(para(r("("), r("0.004"), r(")")),
                 [("(", False), ("0.005", False), (")", False)],
                 id="all-upright"),
    pytest.param(para(r(" "), r("("), r("0.004"), r(")")),
                 [("", False), ("(", False), ("0.005", False), (")", False)],
                 id="lead-all-upright"),
    pytest.param(para(r("("), r("0.0", ITALIC), r("10", ITALIC), r(")")),
                 [("(", False), ("0.005", True), ("", True), (")", False)],
                 id="se-split"),
    pytest.param(para(r("(0.004")), [("(0.005)", False)], id="no-close"),
    pytest.param(para(r("("), r(" ", NUM10), r("0.004", ITALIC), r(")")),
                 [("(", False), ("", False), ("0.005", True), (")", False)],
                 id="upright-space-run"),
])
def test_the_SE_lands_in_the_run_that_has_its_ROLE(se_line, expected):
    """`_fill_se` over the SE lines Word actually splits: which run keeps
    ``(``, which gets the SE, which keeps ``)``, and which are blanked.

    Each shape separates readings the three-run house line cannot: the
    SE and its parenthesis in one run (the gap test, `> 1` against `>= 1`
    and `!= 1`); a leading space run, so ``(`` is not run 0 (every other
    operator on `close_at - open_at`, and on `open_at + 1`); a house that
    sets the WHOLE line italic, so the ``(`` run is italic too (the start
    of `middle`); an all-upright house, where the SE takes the run after
    ``(`` by default; an SE split over two italic runs, which starts in
    the first; a line missing its ``)`` (`and` read as `or`, which
    subtracted None); and an upright run WITH properties between ``(``
    and the italic SE (`_is_italic`, which must say no to it)."""
    xml = results(STARRED + se_line)

    out = set_result(xml, by_caption(xml, "Table 4."), 1, 1, "0.017",
                     stars="**", se="0.005")

    assert se_runs(out) == expected


# --- reordering rows ---------------------------------------------------------


def test_reorder_rows_keeps_a_TWO_row_header_in_place():
    """`seen += 1` read as `+= 2`. A balance table heads its columns over
    two rows — the groups, then the column numbers — and with the count
    of visible rows stepping by two, the second header row became a slot
    a data row could be sorted into."""
    xml = document(table(row("", "Treated", "Control"),
                         row("Country", "(1)", "(2)"),
                         row("POL", "0.1", "0.2"),
                         row("ALB", "0.3", "0.4")))

    out = reorder_rows(xml, read_all(xml)[0], key=lambda c: c[0], header=2)

    assert read_all(out)[0].rows == [["", "Treated", "Control"],
                                     ["Country", "(1)", "(2)"],
                                     ["ALB", "0.3", "0.4"],
                                     ["POL", "0.1", "0.2"]]


def test_reorder_rows_with_NO_header_checks_every_row():
    """`rows_preserved(..., skip_header=False)` read as `True`. A second
    block under one caption has no header row of its own (AFI's Table A3),
    so ``header=0`` moves the first row too — and a check that skipped it
    compared the wrong rows and refused a correct sort."""
    xml = document(table(row("POL", "1"), row("ALB", "2"), row("UZB", "3")))

    out = reorder_rows(xml, read_all(xml)[0], key=lambda c: c[0], header=0)

    assert read_all(out)[0].rows == [["ALB", "2"], ["POL", "1"],
                                     ["UZB", "3"]]


# --- the two defects the round found, fixed (2026-09-29) --------------------

NBSP = "\u00a0"


@pytest.mark.parametrize(("stars_in_table", "value"), [
    (False, "0.7"), (True, "0.7"), (True, "0.7*")],
    ids=["plain-table", "raising-table-unstarred", "raising-table-starred"])
def test_a_value_goes_into_the_PRINTING_line_not_a_spacer_above_it(
        stars_in_table, value):
    """BACKLOG S2. A cell laid out as an NBSP spacer paragraph over its
    value — a way of pushing the number down a line — had the spacer's
    `w:t` first, and a plain value was written THERE: the number moved up
    a line and the printing line went blank, while the cell's text read
    back as the value, so no gate saw it. A starred value in a raising
    table already went into the right line; now every value does."""
    neighbour = (para(r("0.1"), r("*", SUP)) if stars_in_table
                 else para(r("(1)")))
    xml = document(
        para(r("Table 4. Estimates"))
        + "<w:tbl><w:tr><w:tc>" + para(r("Variable")) + "</w:tc><w:tc>"
        + neighbour + "</w:tc></w:tr><w:tr><w:tc>" + para(r("Age"))
        + "</w:tc><w:tc>" + para(r(NBSP)) + para(r("0.5"))
        + "</w:tc></w:tr></w:tbl>")

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, value)

    assert line_texts(out) == [NBSP, value]


def test_a_spacer_BELOW_the_line_is_left_as_it_was():
    """The same writer blanked every other text node in the cell, a
    trailing NBSP spacer's included; it now writes the line and nothing
    else."""
    xml = results(para(r("0.5")) + para(r(NBSP)))

    out = set_cell(xml, by_caption(xml, "Table 4."), 1, 1, "0.7")

    assert line_texts(out) == ["0.7", NBSP]


def _controlled(*rows_xml: str) -> str:
    """Rows inside a content control, as a template's repeating section."""
    return "<w:sdt><w:sdtPr/><w:sdtContent>" + "".join(rows_xml) \
        + "</w:sdtContent></w:sdt>"


def test_a_table_with_a_row_in_a_CONTENT_CONTROL_can_be_reordered():
    """BACKLOG S4. `rows_of` found the row inside `w:sdt` and
    `rows_in_view` did not (direct children only), so the self-check
    refused the table as "a docxkit bug". The control stays where it
    stood, and the row the sort puts there takes it."""
    xml = document(table(row("Country", "N"), row("POL", "1"),
                         row("ALB", "2"), _controlled(row("UZB", "3"))))

    out = reorder_rows(xml, read_all(xml)[0], key=lambda c: c[0])

    assert read_all(out)[0].rows == [["Country", "N"], ["ALB", "2"],
                                     ["POL", "1"], ["UZB", "3"]]
    # The rows were written from the first `w:tr` to the last in one
    # splice, over the control's opening tags: a `</w:sdt>` with no
    # `<w:sdt>`, which `read_all` (a string reader) read back happily.
    etree.fromstring(out.encode())
    assert re.search(r"<w:sdt><w:sdtPr/><w:sdtContent><w:tr>.*?UZB", out)


def test_a_row_in_a_content_control_is_COPIED_inside_it():
    """`clone_row` writes through the same splice; the copies of a
    controlled row join it in its control, as Word's repeating section
    does, and the rows around it are untouched."""
    xml = document(table(row("Country", "N"), _controlled(row("UZB", "3")),
                         row("Total", "3")))

    out = clone_row(xml, read_all(xml)[0], 1, count=2)

    etree.fromstring(out.encode())
    assert read_all(out)[0].rows == [["Country", "N"], ["UZB", "3"],
                                     ["UZB", "3"], ["UZB", "3"],
                                     ["Total", "3"]]
    inside = re.search(r"<w:sdtContent>(.*)</w:sdtContent>", out)
    assert inside is not None and inside.group(1).count("<w:tr>") == 3


def test_a_DELETED_row_in_a_content_control_goes_with_its_control():
    """The accept side of the same row: `accept` always dropped it, and
    left the content control standing EMPTY in the table. The control
    goes with its last row; the table, which has others, stays."""
    from docxkit.revisions import accept, rows_in_view

    tbl = table(row("Country", "N"), row("POL", "1"),
                _controlled(row("UZB", "3", revision="del")))

    assert rows_in_view(tbl, "final") == [True, True, False]
    out = accept(document(tbl))

    assert read_all(out)[0].rows == [["Country", "N"], ["POL", "1"]]
    assert "<w:sdt" not in out
