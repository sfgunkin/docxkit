"""set_decimals — one precision per table, and what must survive it.

The scenario is a regression table exported by Stata's `esttab`, which
writes three SIGNIFICANT digits: one column then holds 1.660, 0.0277 and
0.00749, and the reader re-reads the exponent on every line.

Two things make it more than a `format()` call. Significance stars are
their own superscript run, so the rewrite has to land on the numeric run
and leave the run beside it alone. And the rounding is a SECOND one — the
exported value is already rounded — so cells on a midpoint are named
rather than quietly resolved.
"""
from __future__ import annotations

import re

import pytest

from docxkit.errors import AnchorError
from docxkit.tables import read_all, set_decimals

FONT = "Times New Roman"


def run(text: str, *, sup: bool = False) -> str:
    rpr = (f'<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/>'
           + ('<w:vertAlign w:val="superscript"/>' if sup else "")
           + '<w:sz w:val="20"/></w:rPr>')
    return f"<w:r>{rpr}<w:t>{text}</w:t></w:r>"


def cell(*runs: str) -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="1200" w:type="dxa"/></w:tcPr>'
            f'<w:p w14:paraId="AA">{"".join(runs)}</w:p></w:tc>')


def row(*cells: str) -> str:
    return f"<w:tr>{''.join(cells)}</w:tr>"


def tbl(ncols: int, *rows: str) -> str:
    grid = "".join('<w:gridCol w:w="1200"/>' for _ in range(ncols))
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{1200 * ncols}" '
            f'w:type="dxa"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
            f"{''.join(rows)}</w:tbl>")


def doc(body: str) -> str:
    return f"<w:document><w:body>{body}</w:body></w:document>"


def only(xml: str):
    return read_all(xml)[0]


def texts(xml: str) -> list[str]:
    """Every cell's visible text, in order."""
    out = []
    for tc in re.finditer(r"<w:tc>.*?</w:tc>", xml, re.DOTALL):
        out.append("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                                      tc.group(0))))
    return out


# Counts of 3, 5 and 7 rather than 1 and 2: a wrong operator over small
# counts coincides with the right one too easily.
ESTTAB = tbl(
    3,
    row(cell(run("VARIABLES")), cell(run("Retired")), cell(run("Other"))),
    row(cell(run("Mobility")), cell(run("1.660")), cell(run("0.0277"))),
    row(cell(), cell(run("(0.569)")), cell(run("(0.00880)"))),
    row(cell(run("Health index")), cell(run("0.00749")),
        cell(run("-19.00"))),
    row(cell(), cell(run("(0.00807)")), cell(run("(0.660)"))),
)


def test_one_precision_across_the_table():
    xml = doc(ESTTAB)
    out, rep = set_decimals(xml, only(xml), 3)

    values = [t for t in texts(out) if re.match(r"^[(-]?\d", t)]
    assert values == ["1.660", "0.028", "(0.569)", "(0.009)",
                      "0.007", "-19.000", "(0.008)", "(0.660)"]
    assert rep.changed == 5
    assert rep.unchanged == 3


def test_significance_stars_stay_in_their_own_run():
    """They are superscripted; a whole-cell rewrite would flatten them."""
    xml = doc(tbl(2,
                  row(cell(run("Age")),
                      cell(run("0.0277"), run("***", sup=True)))))
    out, _ = set_decimals(xml, only(xml), 3)

    assert "0.028" in out
    assert '<w:vertAlign w:val="superscript"/>' in out
    assert texts(out)[1] == "0.028***"


def test_integers_are_left_alone():
    """A year, a count and a cluster total have no fractional part, and
    2023.000 is not a year."""
    xml = doc(tbl(4, row(cell(run("2023")), cell(run("3,024")),
                         cell(run("4")), cell(run("—")))))
    out, rep = set_decimals(xml, only(xml), 3)

    assert texts(out) == ["2023", "3,024", "4", "—"]
    assert rep.changed == 0


def test_brackets_parentheses_and_the_sign_survive():
    xml = doc(tbl(3, row(cell(run("(0.0165)")), cell(run("[-0.44]")),
                         cell(run("−1.9")))))
    out, _ = set_decimals(xml, only(xml), 3)

    assert texts(out) == ["(0.017)", "[-0.440]", "−1.900"]


def test_a_typographic_minus_is_not_turned_into_a_hyphen():
    """U+2212 is the sign an equation and a table share; swapping it for
    a hyphen is a glyph change no text diff reports."""
    xml = doc(tbl(1, row(cell(run("−0.0131")))))
    out, _ = set_decimals(xml, only(xml), 3)

    assert texts(out) == ["−0.013"]
    assert "−" in out


def test_rounding_is_decimal_not_float():
    """round(2.675, 2) is 2.67 because the binary value is under the
    midpoint. A table of estimates is the last place to explain that."""
    xml = doc(tbl(3, row(cell(run("2.675")), cell(run("1.005")),
                         cell(run("8.835")))))
    out, _ = set_decimals(xml, only(xml), 2)

    assert texts(out) == ["2.68", "1.01", "8.84"]


def test_midpoint_cells_are_named_not_silently_resolved():
    """The value on the page is ALREADY rounded, so rounding it again
    cannot know which way the original went."""
    xml = doc(tbl(3, row(cell(run("(0.0165)")), cell(run("(0.0795)")),
                         cell(run("0.123")))))
    _, rep = set_decimals(xml, only(xml), 3)

    assert rep.midpoints == ["(0.0165)", "(0.0795)"]


def test_thousands_separators_are_kept():
    xml = doc(tbl(1, row(cell(run("17,059.4")))))
    out, _ = set_decimals(xml, only(xml), 3)

    assert texts(out) == ["17,059.400"]


def test_columns_restricts_the_rewrite():
    xml = doc(tbl(3, row(cell(run("1.5")), cell(run("2.5")),
                         cell(run("3.5")))))
    out, rep = set_decimals(xml, only(xml), 3, columns=[1])

    assert texts(out) == ["1.5", "2.500", "3.5"]
    assert rep.changed == 1


def test_idempotent():
    xml = doc(ESTTAB)
    once, _ = set_decimals(xml, only(xml), 3)
    twice, rep = set_decimals(once, only(once), 3)

    assert twice == once
    assert rep.changed == 0


def test_a_cell_that_is_not_one_number_is_left_alone():
    """Ranges, prose and intervals are not a single value."""
    xml = doc(tbl(4, row(cell(run("55 – 82")), cell(run("years; %")),
                         cell(run("-1.95 [-3.47, -0.43]")),
                         cell(run("2002 (LFS)")))))
    out, rep = set_decimals(xml, only(xml), 3)

    assert texts(out) == ["55 – 82", "years; %", "-1.95 [-3.47, -0.43]",
                          "2002 (LFS)"]
    assert rep.changed == 0


def test_places_of_zero_drops_the_fractional_part():
    xml = doc(tbl(2, row(cell(run("1.660")), cell(run("0.4")))))
    out, _ = set_decimals(xml, only(xml), 0)

    assert texts(out) == ["2", "0"]


def test_a_silly_precision_is_refused():
    xml = doc(ESTTAB)
    with pytest.raises(AnchorError, match="between 0 and 10"):
        set_decimals(xml, only(xml), 11)


def test_a_table_with_tracked_changes_is_refused():
    marked = ESTTAB.replace(
        "<w:tr>", '<w:tr><w:trPr><w:ins w:id="9" w:author="A"/></w:trPr>', 1)
    xml = doc(marked)
    with pytest.raises(AnchorError, match="tracked changes"):
        set_decimals(xml, only(xml), 3)
