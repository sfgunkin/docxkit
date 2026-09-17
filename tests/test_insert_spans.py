"""`insert_in_para`'s offset arithmetic, and where it lands between runs.

The residue after `test_edit_boundaries.py` pinned the refusals: seven
survivors in `insert_in_para` and four in `_between_runs`, all of them
in the arithmetic that decides WHERE, not whether. The refusals were
tested because they are the dramatic part; the position was not,
although it is what the function is for.

The offsets here are chosen so that a wrong operator gives a wrong
answer. `at - start` mutates to `at | start` and `at ^ start`, and for
most pairs of small numbers those land past the end of the run, where
the slice quietly yields the whole body and an empty tail — the content
then appears AFTER the run instead of inside it, which a text assertion
sees and a "did it raise?" assertion does not.
"""
from __future__ import annotations

import pytest
from conftest import para, run

from docxkit import text_of
from docxkit.edit import insert_in_para
from docxkit.errors import AnchorError

FN_REF = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
          '<w:footnoteReference w:id="11"/></w:r>')


def test_the_flags_are_KEYWORD_only():
    """As on `replace_in_para`: these turn off a guard against a silent
    wrong answer, and a positional bool says nothing about which."""
    p = para(run("The share rose."))
    with pytest.raises(TypeError):
        insert_in_para(p, 4, "x", True)        # type: ignore[call-arg]


def test_an_insert_INSIDE_a_run_splits_it_at_the_right_character():
    """The run boundary is at 13 and the insertion at 19, so the offset
    within the run is 6 — a number no bitwise operator on (19, 13)
    produces."""
    p = para(run("The share of "), run("older workers"))

    out = insert_in_para(p, 19, "female ")

    assert text_of(out) == "The share of older female workers"


MATH = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
        'officeDocument/2006/math"><m:r><m:t>{}</m:t></m:r></m:oMath>')


def test_an_offset_after_an_EQUATION_counts_the_equation():
    """The DSI incident, third instance. Offsets index `visible_text`,
    which counts everything a reader sees — and the maths lives in an
    `m:r` inside an `m:oMath` SIBLING of the runs, so a cursor advanced
    across `w:r` alone is short by the equation's glyph count and every
    offset after it lands early.

    That was diagnosed and fixed twice, in two copies of the walk (DSI
    §6.2 in `wrap_visible_span`, §6.3 in `_locate`). This function had a
    third copy and neither fix: on 2026-08-16 it put the content four
    characters late, inside the following word, and no test in the suite
    noticed because none inserted near an equation.
    """
    p = ("<w:p>" + run("where ") + MATH.format("τxyz")
         + run(" is time, in years.") + "</w:p>")
    at = len("where τxyz is time,")

    out = insert_in_para(p, at, " measured")

    assert text_of(out) == "where τxyz is time, measured in years."


def test_the_END_of_a_paragraph_counts_the_equation_too():
    """The bound `at > cursor` is measured by the same walk, so an
    undercount also refuses a legitimate offset near the end."""
    p = "<w:p>" + run("where ") + MATH.format("τxyz") + run(" is time")
    p += "</w:p>"

    out = insert_in_para(p, len("where τxyz is time"), " in years")

    assert text_of(out) == "where τxyz is time in years"


def test_a_paragraph_that_ENDS_on_an_equation_has_an_end_AFTER_it():
    """The bound is measured by the run walk, whose cursor stops at the
    last `w:r` — so an equation AFTER the last run is visible text the
    count does not reach. Measured 2026-09-18: the paragraph reads seven
    characters and its own end was refused as "outside the paragraph's 6
    visible characters"."""
    p = "<w:p>" + run("where ") + MATH.format("x") + "</w:p>"

    out = insert_in_para(p, len("where x"), " holds")

    assert text_of(out) == "where x holds"
    assert out.index("</m:oMath>") < out.index("holds")


def test_words_still_go_BEFORE_a_trailing_equation_at_its_own_offset():
    """The offset where the equation BEGINS is still the equation's, and
    the words go before it — the end of the last run and the end of the
    paragraph are two different places now."""
    p = "<w:p>" + run("where ") + MATH.format("x") + "</w:p>"

    out = insert_in_para(p, len("where "), "now ")

    assert text_of(out) == "where now x"
    assert out.index("now ") < out.index("<m:oMath")


def test_an_offset_inside_a_TRAILING_equation_is_still_refused():
    p = "<w:p>" + run("where ") + MATH.format("xy") + "</w:p>"

    with pytest.raises(AnchorError, match="inside an equation"):
        insert_in_para(p, len("where x"), "now ")


@pytest.mark.parametrize("maths", [
    pytest.param(MATH.format("x"), id="inline"),
    pytest.param(f"<m:oMathPara>{MATH.format('x')}</m:oMathPara>",
                 id="display"),
])
def test_a_paragraph_that_is_ONLY_an_equation_has_BOTH_its_edges(maths):
    """Every display equation is such a paragraph. With no runs the
    cursor is 0, so offset 0 was the paragraph's END as well as its
    start: the words went in through the `not runs` branch, before
    `</w:p>` and AFTER the maths, and the search for an equation
    beginning at the offset was never reached."""
    p = "<w:p>" + maths + "</w:p>"

    before = insert_in_para(p, 0, "Let ")
    after = insert_in_para(p, 1, " holds")

    assert text_of(before) == "Let x"
    assert before.index("Let ") < before.index("<m:oMath")
    assert text_of(after) == "x holds"
    assert after.index("</m:oMath>") < after.index(" holds")


def test_the_run_SPANS_are_measured_from_the_running_cursor():
    """Each span ends at `cursor + len(body)`. Mutated to `cursor |
    len(body)` the end lands short, the offset stops looking like it is
    inside the run, and the insert falls through to the between-runs
    path — which has no run starting there at all.
    """
    p = para(run("The share of "), run("older workers"))

    out = insert_in_para(p, 20, "x")

    assert text_of(out) == "The share of older wxorkers"


def test_content_with_a_LEADING_space_keeps_it():
    p = para(run("Poverty fell."))

    out = insert_in_para(p, 12, " sharply")

    assert 'xml:space="preserve"' in out
    assert text_of(out) == "Poverty fell sharply."


def test_content_with_a_TRAILING_space_keeps_it():
    p = para(run("Poverty fell."))

    out = insert_in_para(p, 8, "sharply ")

    assert 'xml:space="preserve"' in out
    assert text_of(out) == "Poverty sharply fell."


# ---------------------------------------------------------- between runs --

def test_an_insert_at_the_END_goes_after_the_LAST_run():
    """Three runs, because with two the last run is also the second and
    `runs[-1]` mutated to `runs[1]` cannot be told apart."""
    p = para(run("Alpha "), run("beta "), run("gamma"))

    out = insert_in_para(p, 16, " delta")

    assert text_of(out) == "Alpha beta gamma delta"


def test_an_insert_at_a_run_BOUNDARY_lands_between_the_runs():
    p = para(run("Alpha "), run("beta "), run("gamma"))

    out = insert_in_para(p, 6, "and ")

    assert text_of(out) == "Alpha and beta gamma"


def test_the_position_is_after_EVERY_zero_width_run_that_ends_there():
    """A note marker has no width, so it shares its offset with the
    prose either side. "At offset N" means after everything that ended
    there — otherwise inserting beside a footnote moves the marker."""
    p = ("<w:p>" + run("Poverty fell") + FN_REF + run(" in 2014.")
         + "</w:p>")

    out = insert_in_para(p, 12, " sharply")

    assert text_of(out) == "Poverty fell sharply in 2014."
    assert out.index('<w:footnoteReference w:id="11"/>') < out.index("sharply")


LONG = ("The share of workers aged 55 and over rose steadily across the "
        "region over the decade, and the gradient by education widened "
        "in every country that reformed its pension rules early, which "
        "the next table sets out in full for each of the twenty-eight "
        "countries in the sample. ")


def test_the_END_of_a_LONG_paragraph_is_still_its_end():
    """`at == cursor` mutated to `at is cursor` passes every short
    fixture, because CPython interns integers to 256 and no test
    paragraph was longer than that. Two computed offsets that are equal
    must compare equal at any length.
    """
    assert len(LONG) > 256, "the fixture no longer tests what it says"
    p = para(run(LONG))

    out = insert_in_para(p, len(LONG), "Table 4 has it.")

    assert text_of(out) == LONG + "Table 4 has it."


def test_a_run_BOUNDARY_in_a_long_paragraph_is_still_a_boundary():
    """The same identity trap, on the other comparison: the run whose
    span starts exactly at the offset is found with `s == at`."""
    p = para(run(LONG), run("Table 4 sets it out."))

    out = insert_in_para(p, len(LONG), "See ")

    assert text_of(out) == LONG + "See Table 4 sets it out."


# `if s == at` mutated to `if s <= at` is EQUIVALENT and left alive. The
# expression takes the MAXIMUM XML start among the runs it selects, and
# widening the selection to every run starting at or before the offset
# adds only runs further left, which cannot beat the one that starts
# exactly there. It would matter if a run could start after `at` and
# still be wanted, and none can.
