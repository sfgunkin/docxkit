"""`field_spans` and `run_open_before` — the walk that had three copies.

`_xml.py` was measured for the first time on 2026-08-17: 538 mutants,
8.7 % real survival, and 27 of the 45 survivors are these two functions.
They are the same walk — `field_spans` finds a field's bounds by asking
`run_open_before` where its begin run opens — and its docstring already
says what is at stake: it existed three times with three different
guards, only one of which defended against a field whose end tag is
missing.

One test reached it, in `test_pathological.py`, and it asks about
nesting. Nothing asked what a span IS, what the sentinel is when there
is no run, or what happens to the walk when a field cannot be closed.
Those are the three things the survivors sat on.
"""
from __future__ import annotations

from docxkit._xml import field_spans, run_open_before

BEGIN = '<w:fldChar w:fldCharType="begin"/>'
END = '<w:fldChar w:fldCharType="end"/>'
SEP = '<w:fldChar w:fldCharType="separate"/>'


def _run(inner: str) -> str:
    return f"<w:r>{inner}</w:r>"


def _field(anchor: str, label: str) -> str:
    return (_run(BEGIN)
            + _run(f'<w:instrText> HYPERLINK \\l "{anchor}" </w:instrText>')
            + _run(SEP) + _run(f"<w:t>{label}</w:t>") + _run(END))


# ------------------------------------------------------ run_open_before --

def test_run_open_before_answers_the_LAST_run_that_opened():
    """Not the first. The offset belongs to the run CONTAINING it, and
    every run before that one also opened before it.
    """
    xml = "<w:p>" + _run("<w:t>one</w:t>") + _run("<w:t>two</w:t>") + "</w:p>"
    first, second = xml.index("<w:r>"), xml.index("<w:r>", 6)

    assert run_open_before(xml, xml.index("two")) == second
    assert run_open_before(xml, xml.index("one")) == first


def test_run_open_before_finds_a_run_that_opens_at_offset_ZERO():
    """The search starts at 0, and a bare run string is the case that
    proves it: `field_spans` is not the only caller, and one that hands
    over a fragment has its run opening at the very first byte."""
    xml = _run("<w:t>only</w:t>")

    assert run_open_before(xml, len(xml) - 1) == 0


def test_run_open_before_answers_MINUS_ONE_when_no_run_opened():
    """The sentinel is negative on purpose: every caller tests `< 0`.
    Returning 0 would read as "the run opens at the top of the
    document", and the splice built on it starts there — which is how a
    repair cuts from the first byte of the part.
    """
    assert run_open_before("<w:p><w:bookmarkStart w:id='1'/></w:p>", 20) == -1
    assert run_open_before("", 0) == -1


def test_run_open_before_ignores_a_run_that_opens_AFTER_the_offset():
    xml = "<w:p>" + _run("<w:t>one</w:t>") + _run("<w:t>two</w:t>") + "</w:p>"
    first = xml.index("<w:r>")

    assert run_open_before(xml, first + 1) == -1, \
        "the run opening AT the offset has not opened before it"


# ---------------------------------------------------------- field_spans --

def test_a_field_span_starts_at_its_BEGIN_RUN_and_ends_after_the_last():
    """"Run boundaries in" is the contract other modules rely on —
    `edit._split_run` reads these spans to refuse splitting a field, and
    a span that started at the `fldChar` instead of its run would let a
    caller cut the run open."""
    lead = "<w:p>" + _run("<w:t>see </w:t>")
    xml = lead + _field("Table3txt", "Table 3") + "</w:p>"

    (start, end, body), = field_spans(xml)

    assert start == len(lead), "the span must open on the run, not the tag"
    assert xml[start:].startswith("<w:r>")
    assert end == xml.index("</w:p>")
    assert body.endswith("</w:r>")
    assert body.count(BEGIN) == body.count(END) == 1


def test_TWO_fields_come_back_in_document_order():
    xml = ("<w:p>" + _field("A", "first") + _run("<w:t> and </w:t>")
           + _field("B", "second") + "</w:p>")

    spans = field_spans(xml)

    assert len(spans) == 2
    assert spans[0][0] < spans[1][0]
    assert "first" in spans[0][2] and "second" in spans[1][2]


def test_a_nested_field_sorts_AFTER_the_parent_that_contains_it():
    """Document order, and for a tie the WIDER span first — that is what
    the `-span[1]` in the sort key is for. A caller consuming the spans
    in order has to meet the outer one before the piece of it."""
    inner = _field("Inner", "1")
    xml = ("<w:p>" + _run(BEGIN)
           + _run("<w:instrText> REF Table1 </w:instrText>")
           + _run(SEP) + inner + _run("<w:t>Table 1</w:t>") + _run(END)
           + "</w:p>")

    spans = field_spans(xml)

    assert len(spans) == 2
    outer, nest = spans
    assert outer[0] < nest[0] and outer[1] > nest[1], \
        "the parent must come first and contain the nested one"


# ------------------------------------------ the field that cannot close --

def test_a_field_whose_END_RUN_never_closes_is_SKIPPED():
    """`xml.find("</w:r>")` returns -1 on a miss, and `-1 + 6` is 5 —
    an offset near the top of the part. A span built on it slices from
    there, and the splice lands mid-element. Skipped, not guessed at.
    """
    truncated = ("<w:p>" + _run("<w:t>see </w:t>")
                 + _run(BEGIN) + "<w:r>" + END)      # never closed

    assert field_spans(truncated) == []


def test_a_field_whose_BEGIN_is_in_no_run_is_skipped():
    """The other half of the guard. A marker outside any run has no run
    to open the span on, and `run_open_before` says so with -1."""
    stray = "<w:p>" + BEGIN + END + "</w:p>"

    assert field_spans(stray) == []


def test_a_BROKEN_field_does_not_stop_the_walk_finding_a_good_one():
    """The skip is a `continue`, not a `break`. A document with one
    damaged field still has its others, and a repair pass that stopped
    at the first would silently leave the rest untouched.

    The damage here is a marker outside any run, because that is the
    one shape that skips WITHOUT swallowing what follows: an unclosed
    `<w:r>` finds the next run's `</w:r>` instead and produces a span
    across both, which is a different question and not this one.
    """
    xml = "<w:p>" + BEGIN + END + _field("Good", "second") + "</w:p>"

    spans = field_spans(xml)

    assert len(spans) == 1, [s[2][:40] for s in spans]
    assert "second" in spans[0][2]


def test_an_END_with_no_BEGIN_is_not_a_field():
    """Word writes what it writes; an unmatched end marker is damage,
    and inventing a span for it would hand a caller a range to cut."""
    assert field_spans("<w:p>" + _run(END) + "</w:p>") == []


def test_a_BEGIN_with_no_END_is_not_a_field():
    xml = "<w:p>" + _run(BEGIN) + _run("<w:t>label</w:t>") + "</w:p>"

    assert field_spans(xml) == []


def test_two_fields_OPENING_IN_ONE_RUN_sort_wider_first():
    """The tie-break in the sort key, `-span[1]`, and the only shape
    that reaches it: two begin markers inside a single run give both
    fields the same start, so the end decides. Wider first, because a
    caller consuming the spans in order has to meet the parent before
    the piece of it — the same rule the nested case follows, at the one
    offset where document order cannot express it.
    """
    xml = ("<w:p><w:r>" + BEGIN + BEGIN + "</w:r>"
           + _run("<w:t>x</w:t>") + _run(END) + _run(END) + "</w:p>")

    spans = field_spans(xml)

    assert len(spans) == 2
    assert spans[0][0] == spans[1][0], "the fixture no longer ties"
    assert spans[0][1] > spans[1][1], "the wider span must come first"


# Three mutants in this walk are EQUIVALENT and left alive, each because
# the values reaching the comparison are a closed set:
#
# * `kind == "begin"` -> `kind <= "begin"`. `FLDCHAR_RE` captures only
#   "begin", "end" and "separate", and of those only "begin" sorts at or
#   below it;
# * `kind == "end"` -> `kind <= "end"`, in the `elif` — so "begin" is
#   already excluded and "separate" sorts above;
# * `close < 0` -> `close <= 0`. `close` is `xml.find(..., m.end())` and
#   `m.end()` is past the start of the string, so a hit is never 0 and
#   only the -1 miss is negative.
