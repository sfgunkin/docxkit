"""fit_columns(pin_stub=True) — the stub gets its need, the rest share.

The priority this expresses: a row label broken in two costs a line on
EVERY data row; a column heading broken in two costs one line once. So
in a table whose other columns hold values — where a column has a widest
number and anything past it is waste — the stub is satisfied first.

Proportional division cannot say that. It handed one manuscript's stub
797 dxa it had no use for (every column scaled by the same 1.17), and
shaved another's to 1,627 while it needed 2,093, wrapping the country
names on twenty rows.
"""
from __future__ import annotations

import re

from docxkit.tables import fit_columns, read_all

FONT = "Times New Roman"


def run(text: str) -> str:
    return (f'<w:r><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/>'
            f'<w:sz w:val="20"/></w:rPr><w:t>{text}</w:t></w:r>')


def cell(text: str, *, w: int) -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
            f'<w:p w14:paraId="AA">{run(text)}</w:p></w:tc>')


def tbl(grid: list[int], rows: list[list[str]]) -> str:
    g = "".join(f'<w:gridCol w:w="{w}"/>' for w in grid)
    trs = "".join(
        "<w:tr>" + "".join(cell(c, w=grid[i]) for i, c in enumerate(r))
        + "</w:tr>" for r in rows)
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(grid)}" w:type="dxa"/>'
            f'<w:tblLayout w:type="fixed"/></w:tblPr>'
            f"<w:tblGrid>{g}</w:tblGrid>{trs}</w:tbl>")


def doc(body: str) -> str:
    return f"<w:document><w:body>{body}</w:body></w:document>"


def only(xml: str):
    return read_all(xml)[0]


def widths(xml: str) -> list[int]:
    g = re.search(r"<w:tblGrid>.*?</w:tblGrid>", xml, re.DOTALL)
    assert g is not None
    return [int(w) for w in
            re.findall(r'<w:gridCol w:w="(\d+)"/>', g.group(0))]


# Five value columns and a long stub — the shape of a descriptive-
# statistics table. Counts of 3, 5 and 7 throughout rather than 1 and 2.
LONG = "Impairments in Instrumental Activities of Daily Living (IADL)"
ROWS = [["Variable", "50-54", "55-59", "60-64", "65-69", "70-74"],
        [LONG, "0.064", "0.108", "0.129", "0.079", "0.193"],
        ["Mobility Limitations", "0.324", "0.355", "0.395", "0.415", "0.563"],
        ["Employed", "0.768", "0.611", "0.333", "0.054", "0.007"]]
GRID = [2937, 1284, 1285, 1284, 1285, 1285]


def test_the_stub_gets_exactly_what_its_longest_label_needs():
    xml = doc(tbl(GRID, ROWS))
    plain, _ = fit_columns(xml, only(xml))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    # proportional inflates the stub past its need; pinning does not
    assert widths(pinned)[0] < widths(plain)[0]


def test_the_remainder_goes_to_the_value_columns():
    xml = doc(tbl(GRID, ROWS))
    plain, _ = fit_columns(xml, only(xml))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    assert min(widths(pinned)[1:]) > max(widths(plain)[1:])


def test_homogeneous_value_columns_come_out_EQUAL():
    """The whole point for a table of one kind of number: every need is
    under the equal share, so water-filling IS an equal division."""
    xml = doc(tbl(GRID, ROWS))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    values = widths(pinned)[1:]
    assert max(values) - min(values) <= 1        # integer remainder only


def test_the_table_still_totals_its_own_width():
    xml = doc(tbl(GRID, ROWS))
    pinned, rep = fit_columns(xml, only(xml), pin_stub=True)

    assert sum(widths(pinned)) == rep.total == sum(GRID)


def test_a_column_needing_more_than_an_equal_share_takes_its_need():
    """Equal shares alone would wrap a long HEADING to give siblings
    width they do not need."""
    grid = [2000, 1000, 1000, 1000]
    rows = [["Country", "n", "Percentage Points gained over the period",
             "n"],
            ["Albania", "3", "5.3", "7"],
            ["Bosnia and Herzegovina", "5", "8.6", "3"]]
    xml = doc(tbl(grid, rows))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    w = widths(pinned)
    assert w[2] > w[1] and w[2] > w[3]
    assert abs(w[1] - w[3]) <= 1                 # the other two, equal


def test_a_stub_below_its_need_is_WIDENED_not_shaved():
    """The case proportional division gets backwards: no slack, and the
    stub is the column that must not wrap."""
    grid = [900] + [1400] * 6
    rows = [["Country",
             "Initial year of the series",
             "Final year of the series",
             "Mortality at age 60 in the initial year",
             "Percentage change in Mortality",
             "Years gained at age 60",
             "Percentage Points gained"],
            ["Bosnia and Herzegovina", "2001", "2023", "0.018", "-17.8",
             "2.0", "3.4"],
            ["Albania", "2002", "2023", "0.011", "-21.1", "3.2", "5.3"]]
    xml = doc(tbl(grid, rows))
    plain, rep = fit_columns(xml, only(xml))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    # the headings alone want more than the page, so the plain division
    # shaves every column — the stub with them, below its own need
    assert sum(c.new for c in rep.columns) == sum(grid)
    assert widths(plain)[0] < widths(pinned)[0]
    # what the stub gained, the value columns gave, to the dxa
    gained = widths(pinned)[0] - widths(plain)[0]
    assert sum(widths(plain)[1:]) - sum(widths(pinned)[1:]) == gained
    assert sum(widths(pinned)) == sum(grid)


def test_pinning_is_dropped_when_it_would_cramp_the_values():
    """A stub so long that satisfying it pushes the value columns under
    their unbreakable minima keeps the ordinary division instead."""
    grid = [500, 500, 500]
    rows = [["Variable", "Estimate", "Std. error"],
            ["A very long row label indeed, far longer than the page",
             "-0.00749", "0.000929"],
            ["Short", "1.660", "0.569"]]
    xml = doc(tbl(grid, rows))
    plain, _ = fit_columns(xml, only(xml))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    assert widths(pinned) == widths(plain)


def test_a_one_column_table_is_left_to_the_ordinary_division():
    grid = [2000]
    rows = [["Variable"], ["Employed"], ["Retired"]]
    xml = doc(tbl(grid, rows))
    plain, _ = fit_columns(xml, only(xml))
    pinned, _ = fit_columns(xml, only(xml), pin_stub=True)

    assert widths(pinned) == widths(plain)


def test_idempotent():
    xml = doc(tbl(GRID, ROWS))
    once, _ = fit_columns(xml, only(xml), pin_stub=True)
    twice, _ = fit_columns(once, only(once), pin_stub=True)

    assert widths(twice) == widths(once)


def test_off_by_default():
    xml = doc(tbl(GRID, ROWS))
    a, _ = fit_columns(xml, only(xml))
    b, _ = fit_columns(xml, only(xml), pin_stub=False)

    assert widths(a) == widths(b)
