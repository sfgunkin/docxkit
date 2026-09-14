"""The survivors of the first `_tracked_gates` and `_tracked_report` sweeps
(2026-09-13).

9.5 % and 10.1 %, and the shapes the suite had not built: an anchor the
redline ADDS rather than loses, an equation longer than its quote, a
difference whose clean side sorts first, two strings that part only in
length, a paper with more than 256 equations, Word counting MORE body
revisions than the package holds, and the accept-side refusals for a
lost note and an unaccepted paragraph, which no build in the suite had
tripped.
"""
from __future__ import annotations

import re

import pytest
from conftest import ins, make_parts, para, run

from docxkit._tracked_gates import (
    _first_difference,
    _revision_gap,
    accepted_losses,
    accepted_math,
    compare_collateral,
)
from docxkit._tracked_report import (
    _ACCEPT_ESCAPE,
    BuildReport,
    _refuse_accept_side,
)
from docxkit.errors import PackageError

# --- what the redline loses, and not what it gains --------------------------


def test_a_bookmark_the_redline_ADDS_is_not_reported_as_lost():
    """Dropped means in the clean copy and gone from the other: a set
    difference, one way. An anchor only the redline or the accepted view
    carries is not a loss."""
    clean = make_parts(para(run("Text.")))
    marked = make_parts(para('<w:bookmarkStart w:id="1" w:name="Added"/>'
                             + run("Text.") + '<w:bookmarkEnd w:id="1"/>'))

    assert compare_collateral(clean, marked) == []
    assert accepted_losses(clean, marked) == []


# --- equations ---------------------------------------------------------------


def _equations(*texts: str) -> dict[str, bytes]:
    return make_parts("".join(f"<w:p><m:oMath><m:r><m:t>{t}</m:t></m:r>"
                              "</m:oMath></w:p>" for t in texts))


def test_an_equation_is_quoted_at_SIXTY_characters_either_side_first():
    """The clean copy's hyphen sorts BELOW the accepted minus sign, and the
    difference sits past the quote, which is sixty characters of each."""
    clean = "x" * 64 + "-" + "y" * 5
    accepted = "x" * 64 + "−" + "y" * 5

    assert accepted_math(_equations(clean), _equations(accepted)) == [
        f"equation 1: {clean[:60]!r} in the clean copy, {accepted[:60]!r} "
        "accepted — differs at char 64: '-' U+002D (HYPHEN-MINUS) vs '−' "
        "U+2212 (MINUS SIGN)"]


def test_257_equations_that_all_agree_are_no_finding():
    """Past 256 two equal counts are two objects, so only equality can say
    the clean copy and the accepted view hold as many equations."""
    both = _equations(*["a + b"] * 257)

    assert accepted_math(both, both) == []


@pytest.mark.parametrize(("was", "now", "said"), [
    ("−x", "−y", " — differs at char 1: 'x' U+0078 (LATIN SMALL LETTER X) "
                 "vs 'y' U+0079 (LATIN SMALL LETTER Y)"),
    ("ab", "a", " — one is longer: 'b' U+0062 (LATIN SMALL LETTER B) at "
                "char 1"),
    ("a", "ab", " — one is longer: 'b' U+0062 (LATIN SMALL LETTER B) at "
                "char 1"),
], ids=["an equal minus sign first", "the clean side longer",
        "the accepted side longer"])
def test_the_first_difference_is_named_by_CODEPOINT_or_by_the_longer_side(
        was, now, said):
    """A minus sign read twice is two objects, so characters are compared by
    value; and two strings that agree as far as the shorter goes differ in
    the character the longer one carries next, on either side."""
    assert _first_difference(was, now) == said


# --- the revision count Word and the package disagree on ---------------------


def test_Word_counting_MORE_body_revisions_than_the_package_groups_none():
    """Grouping explains Word counting FEWER elements than the body holds;
    counting more is not grouping, and no remainder is offered."""
    parts = make_parts(para(ins("one")) + para(ins("two"))
                       + para(ins("three")))

    assert _revision_gap(parts, 5, 3) == (
        "  (Word counts 5 in the body; the package holds 3 revision "
        "elements)")


# --- the accept-side refusals ------------------------------------------------


@pytest.mark.parametrize(("field", "words"), [
    ("orphan_notes", "note definition(s) with nothing referencing them"),
    ("unaccepted", "paragraph(s) differ"),
])
def test_the_accept_side_REFUSES_a_lost_note_and_an_unaccepted_paragraph(
        field, words):
    """Both refusals name the escape last, and neither fires when only the
    equations are being judged."""
    report = BuildReport()
    setattr(report, field, ["the finding"])

    with pytest.raises(PackageError, match=re.escape(words)) as refused:
        _refuse_accept_side(report, "clean.docx")

    assert str(refused.value).endswith(_ACCEPT_ESCAPE)
    _refuse_accept_side(report, "clean.docx", math_only=True)


def test_the_report_names_parts_from_the_BASELINE_only_when_there_are_some():
    report = BuildReport()
    assert "come from the BASELINE" not in report.format()

    report.carried_from_baseline = ["customXml/item1.xml"]

    assert ("come from the BASELINE: customXml/item1.xml"
            in report.format())
