"""The blank row a Word table uses instead of a rule.

A table typed by hand separates its blocks with an empty row, because it
has no rules to separate them with. Setting it in three-line style makes
that row wrong twice over — the rule marks the boundary, and the gap
above the rule rules off nothing. So `drop_blank_rows` removes them and
hands back exactly what `booktabs` needs to draw the rule in their place.

What the tests are really guarding is the arithmetic: the indices it
returns are indices in the table AFTER the removal, and getting that off
by one draws the panel rule through the middle of a block.
"""
from __future__ import annotations

import re

import pytest
from conftest import NS

from docxkit.errors import AnchorError
from docxkit.tables import (
    BooktabsPlan,
    booktabs,
    drop_blank_rows,
    read_all,
)


def cell(text: str) -> str:
    inner = f"<w:r><w:t>{text}</w:t></w:r>" if text else ""
    return f'<w:tc><w:tcPr/><w:p w14:paraId="AA">{inner}</w:p></w:tc>'


def table(*rows: tuple[str, ...]) -> str:
    trs = "".join(f"<w:tr>{''.join(cell(c) for c in r)}</w:tr>" for r in rows)
    return f"<w:tbl><w:tblPr/><w:tblGrid/>{trs}</w:tbl>"


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


CATALOGUE = doc(table(
    ("Компонент", "Показатель"),        # 0  header
    ("D", "Доля детей"),                # 1
    ("", "Рождаемость"),                # 2
    ("", ""),                           # 3  spacer
    ("S", "Медианная плата"),           # 4
    ("", "Безработица"),                # 5
    ("", ""),                           # 6  spacer
    ("H", "Продолжительность"),         # 7
))


def rows_of_first(xml: str) -> list[list[str]]:
    return read_all(xml)[0].rows


def test_the_spacer_rows_go_and_the_panels_are_named():
    out, panels = drop_blank_rows(CATALOGUE, read_all(CATALOGUE)[0])
    rows = rows_of_first(out)
    assert len(rows) == 6
    assert [r[0] for r in rows] == ["Компонент", "D", "", "S", "", "H"]
    # in the RETURNED table «S» is row 3 and «H» is row 5
    assert panels == [3, 5]


def test_the_indices_are_the_ones_booktabs_needs():
    """The point of the return value: hand it straight to the plan and the
    rules land on the rows that open a block."""
    out, panels = drop_blank_rows(CATALOGUE, read_all(CATALOGUE)[0])
    ruled, _ = booktabs(out, read_all(out)[0],
                        plan=BooktabsPlan(1, [], panels, []),
                        bottom="single")
    tops = [i for i, tr in enumerate(re.findall(r"<w:tr\b.*?</w:tr>", ruled,
                                                re.DOTALL))
            if '<w:top w:val="single"' in tr]
    assert tops == [0, 3, 5]
    assert [r[0] for r in rows_of_first(ruled)] == ["Компонент", "D", "",
                                                    "S", "", "H"]


def test_a_table_with_no_blank_rows_is_returned_unchanged():
    xml = doc(table(("Регион", "DRI"), ("Абай", "0,461")))
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert out == xml and panels == []


def test_a_trailing_blank_row_opens_nothing():
    xml = doc(table(("Регион", "DRI"), ("Абай", "0,461"), ("", "")))
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert len(rows_of_first(out)) == 2
    assert panels == []


def test_a_leading_blank_row_does_not_name_row_zero():
    """Row 0 already carries the top rule; naming it as a panel would
    declare the same edge twice for no reason."""
    xml = doc(table(("", ""), ("Регион", "DRI"), ("Абай", "0,461")))
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert [r[0] for r in rows_of_first(out)] == ["Регион", "Абай"]
    assert panels == []


def test_two_blank_rows_in_a_row_open_one_panel():
    xml = doc(table(("A", "1"), ("", ""), ("", ""), ("B", "2")))
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert len(rows_of_first(out)) == 2
    assert panels == [1]


def test_a_row_holding_a_picture_is_not_blank():
    """It renders nothing into the text and is not a spacer — the
    table-level form of «a run with a drawing is not an empty run»."""
    xml = doc(table(("A", "1"), ("", ""), ("B", "2"))).replace(
        "<w:tc><w:tcPr/><w:p w14:paraId=\"AA\"></w:p></w:tc>"
        "<w:tc><w:tcPr/><w:p w14:paraId=\"AA\"></w:p></w:tc>",
        '<w:tc><w:tcPr/><w:p w14:paraId="AA"><w:r><w:drawing/></w:r></w:p>'
        '</w:tc><w:tc><w:tcPr/><w:p w14:paraId="AA"/></w:tc>')
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert out == xml and panels == []
    assert "<w:drawing/>" in out


def test_a_row_holding_an_equation_is_not_blank():
    xml = doc(table(("A", "1"), ("", ""), ("B", "2"))).replace(
        '<w:p w14:paraId="AA"></w:p></w:tc><w:tc><w:tcPr/>'
        '<w:p w14:paraId="AA"></w:p>',
        '<w:p w14:paraId="AA"><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>'
        '</w:p></w:tc><w:tc><w:tcPr/><w:p w14:paraId="AA"/>')
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert out == xml and panels == []


def test_it_refuses_a_table_carrying_tracked_changes():
    xml = doc(table(("A", "1"), ("", ""), ("B", "2"))).replace(
        "<w:r><w:t>B</w:t></w:r>",
        '<w:ins w:id="1" w:author="T" w:date="2026-08-09T00:00:00Z">'
        "<w:r><w:t>B</w:t></w:r></w:ins>")
    with pytest.raises(AnchorError, match="tracked changes"):
        drop_blank_rows(xml, read_all(xml)[0])


def test_it_refuses_a_table_that_is_nothing_but_blank_rows():
    xml = doc(table(("", ""), ("", "")))
    with pytest.raises(AnchorError, match="entirely blank"):
        drop_blank_rows(xml, read_all(xml)[0])


def test_a_stale_table_is_refused_rather_than_slicing_the_wrong_bytes():
    """Offsets read before an earlier edit point into the wrong bytes, and
    the slice is still valid-looking XML — so it has to be refused, not
    detected afterwards."""
    xml = doc(table(("A", "1"), ("", ""), ("B", "2")))
    stale = read_all(xml)[0]
    shifted = xml.replace("<w:body>",
                          "<w:body><w:p><w:r><w:t>preamble</w:t></w:r></w:p>")
    with pytest.raises(AnchorError, match="different version"):
        drop_blank_rows(shifted, stale)


def test_the_document_around_the_table_is_untouched():
    xml = doc("<w:p><w:r><w:t>before</w:t></w:r></w:p>"
              + table(("A", "1"), ("", ""), ("B", "2"))
              + "<w:p><w:r><w:t>after</w:t></w:r></w:p>")
    out, panels = drop_blank_rows(xml, read_all(xml)[0])
    assert out.startswith(xml[:xml.index("<w:tbl>")])
    assert out.endswith("<w:p><w:r><w:t>after</w:t></w:r></w:p>"
                        "</w:body></w:document>")
    assert panels == [1]


def test_it_is_idempotent():
    once, first = drop_blank_rows(CATALOGUE, read_all(CATALOGUE)[0])
    twice, second = drop_blank_rows(once, read_all(once)[0])
    assert twice == once and first == [3, 5] and second == []
