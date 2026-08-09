"""The column-width model, measured against Word itself.

`fit_columns` predicts how much room a cell's text needs, and every other
table routine spends that prediction. Nothing checked it. The tables were
hand-tuned "from a Word PDF render", the suite pinned the numbers that
tuning produced, and so the suite agreed with the model about everything
including its mistakes: Arial's K sat in the wrong group (722 for a true
667), P and "!" were in no group at all and took the 600 fallback, and
every hand-set Arial Narrow override was too wide — digits by 9.9%, which
bought numeric columns a tenth more room than they need and took it from
the label column. All four were found the hour this file first ran.

Marked `word`: it drives a real Word instance, so a plain `pytest`
deselects it (see pyproject). Run it before a release, and after ANY edit
to a width table:

    python -m pytest -m word

Method: a character's advance is `(w(c*40) - w(c*20)) / 20`, which
cancels side bearings and edge effects; a whole string is measured
directly. Word is asked for the position of the text's start and end on
the page, which agrees with the AFM tables for Times to 0.2% — that
agreement is what says the METHOD is sound before it is used to judge a
font it disagrees with.

WHAT IS DELIBERATELY NOT HERE: an end-to-end "fit a table, render it,
assert no row wrapped" check. It was written, and it could not fail.

* `Range.ComputeStatistics(wdStatisticLines)` returns **0** for a table
  cell — not 1, not the real count — so the obvious `lines > 1` assertion
  never fires. Comparing the line NUMBER at each end of the cell range
  does detect a wrap.
* Even with a working detector it stayed green through a model scaled to
  0.600, cell margins forced to zero, and `pad` cut to 0.90 — separately
  and together. `fit_columns` divides a FIXED total, so a uniform error
  changes only how the leftover is shared out; and sizing the table to
  the model's own claim does not help, because the shortfall lands on
  the label column, which turns out to have room to spare (this fixture
  wrapped between 1060 and 1301 dxa, against a claimed need of 1560).

So it certified nothing while reading as a guarantee — the exact failure
this file was written to end. The per-character and per-cell tests below
are the sharp instruments: they fail on a 3% drift, and they found four
real defects on their first run.
"""
from __future__ import annotations

import statistics

import pytest

from docxkit._table_layout import (
    _ARIAL,
    _ARIAL_NARROW,
    _FONT_ALIASES,
    _TIMES,
    _cell_extents,
)

pytestmark = pytest.mark.word

pytest.importorskip("win32com.client", reason="needs pywin32 and Word")

SIZE_PT = 10.0
DXA_PER_EM = SIZE_PT * 20                      # 1 em at SIZE_PT, in dxa


#: Every printable ASCII character, plus the dashes and quotes the tables
#: list. Exhaustive on purpose: an omitted character is silently 600, and
#: nothing about a table's shape says which ones it forgot.
CHARS = "".join(chr(c) for c in range(0x20, 0x7F)) + "–—−‘’“”"

#: The tables that are a font in their own right, tested per character.
REAL = [("Times New Roman", _TIMES), ("Arial", _ARIAL),
        ("Arial Narrow", _ARIAL_NARROW)]

#: Table cells, for the aliased faces: a borrowed shape table corrected
#: by one number is only meaningful in aggregate.
CELLS = [
    "Kazakhstan", "Russian Federation", "Kyrgyz Republic", "Uzbekistan",
    "0.312", "-0.045***", "1,234,567", "(0.0031)", "12.7", "-0.008",
    "Employment rate, ages 55-64", "Observations", "N = 12,480",
    "Life expectancy at birth (years)", "Log GDP per capita",
    "Health expenditure (% of GDP)", "Pension replacement rate",
    "Within-occupation change", "Std. error", "R-squared",
    "Country fixed effects", "Yes", "No", "0.842", "[0.19, 0.47]",
]


@pytest.fixture(scope="module")
def measure():
    """One Word process for the whole module — starting it is the
    expensive part, and every test here measures the same way.

    A passing run still prints one to five first-chance Windows RPC
    exceptions as Word tears down (see :func:`docxkit.word.ruler`); the
    exit code is what to read, not the dump.
    """
    from docxkit.word import ruler, session
    with session(fast=False) as word, ruler(word, size_pt=SIZE_PT) as m:
        yield m


def predicted(font: str, text: str) -> float:
    """The model's `full` width for one cell of `text`, in dxa."""
    tc = (f"<w:tc><w:p><w:r><w:rPr>"
          f'<w:rFonts w:ascii="{font}"/><w:sz w:val="{int(SIZE_PT * 2)}"/>'
          f"</w:rPr><w:t>{text}</w:t></w:r></w:p></w:tc>")
    return _cell_extents(tc, ("Times New Roman", int(SIZE_PT * 2)))[1]


@pytest.mark.parametrize("font,table", REAL, ids=[f for f, _ in REAL])
def test_every_character_is_within_2_5_percent_of_word(font, table, measure):
    """Per character, because that is the unit the table stores. The
    tolerance is tight on purpose: these fonts have real metric tables,
    so a character more than 2.5% out is an error, not approximation.

    A note for whoever next runs mutation testing over `_table_layout`:
    it will report ~87 survivors sitting on the font tables, and they are
    NOT gaps. 2.5% of a 556-unit width is ±13 units, so cosmic-ray's
    ±1 `NumberReplacer` mutations fall inside the tolerance this test
    declares, and surviving is the correct answer rather than a missing
    check. Measured 2026-08-09: 556→557 and 0.820→0.821 survive here,
    while 556→600, 722→760, 0.820→0.900 and dropping 'K' from its group
    (so it takes the 600 fallback — the V4 defect) are all killed. The
    gate works; the mutation operator is simply finer-grained than the
    contract. Some of those ±1 mutants DO die in the offline suite, which
    is incidental: `test_tables_fit*` pins exact divided widths, and an
    exact pin is sensitive to changes the model never promised to
    resolve.
    """
    wide = measure(font, [f"x{ch * 40}" for ch in CHARS])
    narrow = measure(font, [f"x{ch * 20}" for ch in CHARS])
    off = []
    for ch, w40, w20 in zip(CHARS, wide, narrow, strict=True):
        em = (w40 - w20) / 20 / DXA_PER_EM * 1000
        model = table.get(ch, 600)
        err = (model - em) / em * 100
        if abs(err) > 2.5:
            listed = "listed" if ch in table else "NOT IN THE TABLE (600)"
            off.append(f"{ch!r}: model {model} vs Word {em:.1f} "
                       f"({err:+.1f}%, {listed})")
    assert not off, f"{font}:\n  " + "\n  ".join(off)


@pytest.mark.parametrize("font", [f for f, _ in REAL])
def test_whole_cells_are_within_3_percent_of_word(font, measure):
    """What a column is actually sized by. Per-character accuracy does
    not guarantee this: errors could cancel, or accumulate."""
    widths = measure(font, CELLS)
    off = [f"{text!r}: model {predicted(font, text):.0f} vs Word {w:.0f}"
           for text, w in zip(CELLS, widths, strict=True)
           if w and abs(predicted(font, text) - w) / w > 0.03]
    assert not off, f"{font}:\n  " + "\n  ".join(off)


def test_every_alias_scale_zeroes_the_mean_error(measure):
    """An aliased face borrows another font's shapes, so a single string
    is a few percent out either way and only the MEAN is meaningful — it
    is what a column's width is spent on. A face this machine does not
    have is skipped, not measured through Word's substitute.
    """
    from docxkit.errors import FontMissing
    checked, off = [], []
    for font in sorted(_FONT_ALIASES):
        try:
            widths = measure(font.title(), CELLS)
        except FontMissing:
            continue
        errs = [(predicted(font, t) - w) / w * 100
                for t, w in zip(CELLS, widths, strict=True) if w]
        mean = statistics.mean(errs)
        checked.append(font)
        if abs(mean) > 3:
            scale = _FONT_ALIASES[font][1]
            implied = statistics.mean(
                scale * w / predicted(font, t)
                for t, w in zip(CELLS, widths, strict=True)
                if w and predicted(font, t))
            off.append(f"{font}: mean {mean:+.1f}% at scale {scale} "
                       f"(measures {implied:.3f})")
    assert checked, "no aliased font installed - nothing was verified"
    assert not off, "\n  " + "\n  ".join(off)


def test_the_method_agrees_with_the_afm_tables(measure):
    """A guard on the measurement itself. Times New Roman IS the Adobe
    AFM table, to a fraction of a percent — so if this one drifts, the
    ruler has changed, not the font, and the other failures here are
    telling you about the wrong thing."""
    widths = measure("Times New Roman", CELLS)
    errs = [abs(predicted("Times New Roman", t) - w) / w
            for t, w in zip(CELLS, widths, strict=True) if w]
    assert max(errs) < 0.01, f"worst {max(errs) * 100:.1f}%"
