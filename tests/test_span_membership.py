"""One question, asked in four places: does this span contain this run?

`labels_a_link`, `label_end`, `_split_run` and `_outside` each decide
whether a run lies inside a protected element, and each writes it out
as ``lo <= run.start() < hi``. After the boundary passes of 2026-08-16
that comparison held most of what was left alive in `edit.py`, so this
file takes all four at once — the walk that lives in four places is the
walk that will disagree with itself, which is the argument
`field_spans`'s own docstring makes about its three predecessors.

Both ends need a run sitting exactly on them, and the two forms of link
supply different ones:

* an ELEMENT span begins at ``<w:hyperlink``, where no run can start —
  the tag is in the way — so mutating `lo <=` to `lo <` there changes
  nothing and is equivalent by construction. It ENDS at the close tag,
  and the next run starts exactly there;
* a FIELD span comes from `field_spans`, whose bounds are run
  boundaries, so a run starts on `lo` exactly.

Word also leaves `w:proofErr` between runs, which is what puts a GAP
either side of a run start — and a gap is the only thing that tells
``r.end() <= pos`` from ``r.end() == pos``.
"""
from __future__ import annotations

import pytest
from conftest import run

from docxkit import text_of
from docxkit._xml import RUN_RE
from docxkit.edit import _outside, insert_in_para, replace_in_para
from docxkit.errors import AnchorError

PROOF = '<w:proofErr w:type="spellStart"/>'


def _styled(text: str) -> str:
    return ('<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            f"<w:t>{text}</w:t></w:r>")


def _element(*labels: str) -> str:
    return ('<w:hyperlink w:anchor="Table3txt" w:history="1">'
            + "".join(_styled(t) for t in labels) + "</w:hyperlink>")


def _field(*labels: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l '
            '"Table3txt" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + "".join(_styled(t) for t in labels)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


LINKED = {"element": _element("Table 3"), "field": _field("Table 3")}


def _paragraph(form: str) -> str:
    """Prose, a link, prose — with no gap on either side of the link, so
    the run after it starts exactly where the span ends."""
    return ("<w:p>" + run("see ") + LINKED[form]
            + run(" and the notes below") + "</w:p>")


# ------------------------------------------ the run BEFORE the span ------

@pytest.mark.parametrize("form", ["element", "field"])
def test_a_run_before_the_span_is_outside_it(form):
    """`lo <= run.start()` mutated to `lo != run.start()` calls every
    run in the paragraph inside the link, including the ones in front of
    it — and the guard then refuses an edit that never goes near it."""
    out = replace_in_para(_paragraph(form), "see", "cf.")

    assert text_of(out) == "cf. Table 3 and the notes below"


@pytest.mark.parametrize("form", ["element", "field"])
def test_an_insert_in_the_run_before_the_span_is_allowed(form):
    """The same comparison, in `_split_run`'s protected check."""
    out = insert_in_para(_paragraph(form), 2, "e")

    assert text_of(out) == "seee Table 3 and the notes below"


# ------------------------------- the run starting where the span ENDS ----

@pytest.mark.parametrize("form", ["element", "field"])
def test_a_run_starting_where_the_span_ends_is_outside_it(form):
    """`run.start() < hi` mutated to `<=` swallows the run that begins
    exactly at the closing tag, which is the ordinary case: a
    cross-reference followed straight by the rest of the sentence.
    """
    out = replace_in_para(_paragraph(form), "notes", "figures")

    assert text_of(out) == "see Table 3 and the figures below"


@pytest.mark.parametrize("form", ["element", "field"])
def test_an_insert_in_the_run_after_the_span_is_allowed(form):
    p = _paragraph(form)
    at = len("see Table 3 and the ")

    out = insert_in_para(p, at, "end ")

    assert text_of(out) == "see Table 3 and the end notes below"


# --------------------------------------------- the walk along a label ----

def test_the_label_walk_takes_ONE_styled_run_at_a_time():
    """A field form has no element to ask, so the label is the run's
    styled neighbours, reached one at a time. Stepping two at a time
    still ends on a styled run — it just ends on the WRONG one, and the
    guard then refuses an edit that stays inside the label.
    """
    p = ("<w:p>" + _field("Table", " 4", ": Discipline")
         + run(" follows.") + "</w:p>")

    out = replace_in_para(p, "Table 4: Discipline", "Table 5: Violence",
                          allow_hyperlink=True)

    assert text_of(out) == "Table 5: Violence follows."


def test_the_walk_still_stops_at_the_end_of_the_label():
    """The counterpart: one run further and the label would swallow the
    sentence, which is the S1 this guard exists for."""
    p = ("<w:p>" + _field("Table", " 4", ": Discipline")
         + run(" follows.") + "</w:p>")

    with pytest.raises(AnchorError, match="swallow"):
        replace_in_para(p, "Table 4: Discipline follows.", "Table 5.",
                        allow_hyperlink=True)


# --------------------------- a styled run that is NOT inside an element --
#
# Word leaves `rStyle Hyperlink` on runs beside a link as freely as it
# leaves it on the label itself, so "looks like a link" and "is inside
# the link element" are different questions. `label_end` asks the
# element first and falls back to the styled neighbours, and the two
# answers differ — which is only visible when a styled run sits OUTSIDE
# the element, on one side or the other.

def test_a_styled_run_BEFORE_the_element_has_its_own_extent():
    """`lo <= run.start()` mutated to `lo != run.start()` makes the
    element claim a run in front of it, and the guard then measures the
    match against the LINK's end instead of this run's — so a
    replacement that would grow this pseudo-label is allowed through.
    """
    p = ("<w:p>" + _styled("See ") + run("the note ")
         + _element("Table 3") + "</w:p>")

    with pytest.raises(AnchorError, match="swallow"):
        replace_in_para(p, "See the note", "See the notes",
                        allow_hyperlink=True)


def test_a_styled_run_AFTER_the_element_has_its_own_extent():
    """The mirror: `run.start() < hi` mutated to `is not hi` makes the
    element claim a run BEYOND it, whose extent then ends before the
    match even starts — and an ordinary edit is refused.

    The `w:proofErr` matters. Without it the styled run begins exactly
    where the element closes, `run.start()` and `hi` are the same small
    integer and therefore the same OBJECT, and `is not` answers what
    `<` answers. The gap is what separates identity from order — the
    third time that distinction has decided a test in this module.
    """
    p = ("<w:p>" + _element("Table 3") + PROOF + _styled(" and more")
         + run(" plain.") + "</w:p>")

    out = replace_in_para(p, " and more", " and further",
                          allow_hyperlink=True)

    assert text_of(out) == "Table 3 and further plain."


# ------------------------------------------------ _outside, across a GAP --

def _runs(para_xml: str) -> list:
    return list(RUN_RE.finditer(para_xml))


def test_outside_is_NONE_when_a_run_ends_before_the_offset_but_not_at_it():
    """`r.end() <= pos` mutated to `r.end() == pos` needs a gap to tell
    apart, and Word supplies one: `w:proofErr` sits between runs all
    over a real document. With text on both sides the answer is None —
    the caller really is splitting a label — and the mutant instead
    reports the position available before the whole element, which
    moves an insert somewhere the caller did not ask for.
    """
    p = "<w:p>" + _styled("Kan") + PROOF + _styled("bur") + "</w:p>"
    runs = _runs(p)
    span = (runs[0].start(), runs[-1].end())

    assert runs[0].end() < runs[1].start(), "the fixture lost its gap"
    assert _outside(runs, span, runs[1].start()) is None


def test_outside_is_NONE_when_a_run_starts_after_the_offset_but_not_at_it():
    """The same, at the other edge: `r.start() >= pos` against `==`."""
    p = "<w:p>" + _styled("Kan") + PROOF + _styled("bur") + "</w:p>"
    runs = _runs(p)
    span = (runs[0].start(), runs[-1].end())

    assert _outside(runs, span, runs[0].end()) is None


def test_outside_ignores_a_run_that_starts_AFTER_the_span():
    """`span[0] <= r.start() < span[1]` mutated to `r.start() !=
    span[1]` lets a run beyond the element count as one of its own —
    and a run adjacent to the span cannot show it, because its start IS
    span[1]. The gap is what makes it visible.
    """
    p = ("<w:p>" + _styled("label") + PROOF
         + "<w:r><w:t> tail</w:t></w:r></w:p>")
    runs = _runs(p)
    span = (runs[0].start(), runs[0].end())

    assert runs[1].start() > span[1], "the fixture lost its gap"
    assert _outside(runs, span, runs[0].end()) == span[1]


# Six mutants across these four sites are EQUIVALENT and left alive,
# recorded so the next survivor report is not read as a gap:
#
# * `lo <= run.start()` -> `lo < run.start()`, in `labels_a_link`,
#   `label_end` and `_split_run`. An ELEMENT span opens at
#   `<w:hyperlink`, where no run can start because the tag occupies
#   those bytes. It would be killable on a span whose bounds ARE run
#   bounds — `field_spans` — but `_split_run` never receives the
#   field's own begin run to split: that run shows nothing, so an
#   offset cannot fall inside it;
# * `lo <= r.start()` -> `lo is not r.start()` in `label_end`'s `inside`
#   list. The list is read only as `inside[-1]`, and admitting runs from
#   in FRONT of the link cannot change which run is last;
# * `0 <= i` -> `1 <= i` and `i < len(runs)` -> `i != len(runs)` in
#   `styled`. It is only ever called as `styled(hi_i + 1)` with
#   `hi_i >= 0`, so the index is never 0 and never past the end.
