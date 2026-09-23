"""A DECIMAL comma is a decimal mark, not a thousands separator.

Backlog S1, 2026-09-18: `parse_number` stripped every comma, so a
Russian table's ``0,31`` read as 31.0, and `update` wrote 0.4 into that
cell as ``'0'`` — a table that looked updated and was wrong by two
orders of magnitude, with every comparison downstream reading both sides
through the same reader.

The number decides wherever it can (``0,31``, ``12,5``, ``1 234,5``);
only a ``1,234``-shaped number cannot, and for that the rest of the table
decides. Measured over 20,422 corpus tables before choosing that: 119
tables had an ambiguous number settled by a decimal comma beside it, and
the 70 left unsettled were English count tables — so no evidence reads
as English, which is what every English caller already relied on.
"""
from __future__ import annotations

import pytest
from conftest import document, para, row, run, table

from docxkit.tables import (
    _render_value,
    decimal_mark,
    parse_number,
    read_all,
    update,
)

NBSP = " "


@pytest.mark.parametrize(("text", "expected"), [
    ("0,31", 0.31),
    ("12,5", 12.5),
    ("-0,623", -0.623),
    ("−0,147**", -0.147),                 # typographic minus and stars
    (f"1{NBSP}234,5", 1234.5),            # the space grouping Word writes
    ("1 234,5", 1234.5),
    ("1234,567", 1234.567),               # a head of four digits: no group
    ("0,312", 0.312),                     # a zero head is never grouped
    ("39,5%", 39.5),
])
def test_a_number_that_SAYS_its_comma_is_decimal_reads_as_decimal(
        text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize(("text", "expected"), [
    ("1,234.5", 1234.5),
    ("1,234,567", 1234567.0),
    ("12, 13", 12.0),                     # a list, not a number
])
def test_a_number_that_says_its_comma_GROUPS_still_reads_as_before(
        text, expected):
    assert parse_number(text) == expected


def test_only_the_AMBIGUOUS_shape_listens_to_the_stated_mark():
    assert parse_number("1,234") == 1234.0             # English, as before
    assert parse_number("1,234", decimal=".") == 1234.0
    assert parse_number("1,234", decimal=",") == pytest.approx(1.234)
    # a number that says what it is ignores the caller
    assert parse_number("0,31", decimal=".") == pytest.approx(0.31)
    assert parse_number("1,234.5", decimal=",") == 1234.5


def test_a_mark_that_is_neither_is_refused():
    with pytest.raises(ValueError, match="decimal must be"):
        parse_number("1,234", decimal=";")


@pytest.mark.parametrize(("cells", "mark"), [
    (["1,234", "0,31", "12,5", "7,25", "3,1"], ","),
    (["1,234", "0.31", "12.5", "7.25", "3.1"], "."),
    (["1,234", "5,678", "12,345"], None),               # no evidence
    (["0,31", "0.5", "Coeff.", ""], None),              # a tie
    (["0,31", "0,5", "0.7"], ","),                      # the majority
])
def test_the_TABLE_says_which_mark_it_uses(cells, mark):
    assert decimal_mark(cells) == mark


def _russian() -> str:
    return document(
        para(run("Таблица 3. Оценки"))
        + table(row("Показатель", "Оценка", "N"),
                row("Доход", "0,31", "1,234"),
                row("Возраст", "12,5", "5,678"),
                row("Стаж", "-0,623**", "2,017")))


def test_numbers_reads_an_ambiguous_cell_the_way_its_TABLE_does():
    (t,) = read_all(_russian())
    nums = t.numbers()

    assert nums[1][1] == pytest.approx(0.31)
    assert nums[1][2] == pytest.approx(1.234)     # the table says ","
    assert nums[3][1] == pytest.approx(-0.623)
    assert t.numbers(decimal=".")[1][2] == 1234.0


def test_update_writes_a_RUSSIAN_cell_back_in_its_own_format():
    """The S1's consequence, end to end: the cell used to come back
    ``'0'``, and the report called that a change of 0.4 - 31.0."""
    xml = _russian()
    (t,) = read_all(xml)

    new, changes = update(xml, t, [[0.4, 3.5], [12.75, 6.25],
                                   [-0.5, 2.25]], col0=1)
    (after,) = read_all(new)

    assert after.rows[1][1:] == ["0,40", "3,500"]
    assert after.rows[2][1:] == ["12,8", "6,250"]
    assert after.rows[3][1:] == ["-0,500**", "2,250"]
    first = next(c for c in changes if (c.row, c.col) == (1, 1))
    assert first.moved == pytest.approx(0.09)


def test_update_leaves_an_ENGLISH_count_table_as_it_was():
    """The 70 tables with no evidence: ``1,234`` is a thousand."""
    xml = document(table(row("Country", "N"), row("Poland", "1,234"),
                         row("Chile", "5,678"), row("Peru", "12,345")))
    (t,) = read_all(xml)

    new, _ = update(xml, t, [[2345], [6789], [23456]], col0=1)

    assert [r[1] for r in read_all(new)[0].rows[1:]] == [
        "2,345", "6,789", "23,456"]


@pytest.mark.parametrize(("old", "value", "expected"), [
    ("0,31", 0.4, "0,40"),
    (f"1{NBSP}234,5", 2345.6, f"2{NBSP}345,6"),
    ("1 234,5", 12345.67, "12 345,7"),
    ("−0,147**", -0.2, "−0,200**"),
    ("0.31", 0.4, "0.40"),                           # unchanged for English
    ("1,234.5", 2345.6, "2,345.6"),
    (f"1{NBSP}234.5", 2345.6, f"2{NBSP}345.6"),       # keeps its grouping
])
def test_render_keeps_the_cell_s_decimal_mark_and_grouping(
        old, value, expected):
    assert _render_value(old, value) == expected


def test_render_follows_the_stated_mark_for_an_ambiguous_cell():
    assert _render_value("1,234", 2.5, decimal=",") == "2,500"
    assert _render_value("1,234", 2500, decimal=".") == "2,500"
