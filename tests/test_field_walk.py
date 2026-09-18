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

The whole sweep of 2026-09-17 added the readers on top of the walk,
`field_anchors` and `ref_anchor`: 66 survivors, and no test in this
harness had handed either one a field at all — a mutant that asked for
a regex group that does not exist lived. They are the last section.
"""
from __future__ import annotations

import re

import pytest

from docxkit._xml import (
    dead_links,
    field_anchors,
    field_spans,
    fields,
    internal_links,
    ref_anchor,
    run_open_before,
)

BEGIN = '<w:fldChar w:fldCharType="begin"/>'
END = '<w:fldChar w:fldCharType="end"/>'
SEP = '<w:fldChar w:fldCharType="separate"/>'


def _run(inner: str) -> str:
    return f"<w:r>{inner}</w:r>"


def _field(anchor: str, label: str) -> str:
    return (_run(BEGIN)
            + _run(f'<w:instrText> HYPERLINK \\l "{anchor}" </w:instrText>')
            + _run(SEP) + _run(f"<w:t>{label}</w:t>") + _run(END))


def _instr(text: str) -> str:
    return _run(f'<w:instrText xml:space="preserve">{text}</w:instrText>')


def _field_of(*pieces: str, shown: str = "Table 1") -> str:
    """A whole field whose instruction is split into ``pieces``, one run
    each — which is how Word writes one that was edited at an rsid
    boundary."""
    return (_run(BEGIN) + "".join(_instr(p) for p in pieces)
            + _run(SEP) + _run(f"<w:t>{shown}</w:t>") + _run(END))


def _instr_offsets(xml: str) -> list[int]:
    return [m.start() for m in re.finditer("<w:instrText", xml)]


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


def test_a_fldCharType_OUTSIDE_the_schema_opens_and_closes_nothing():
    """For `kind == "begin"` -> `kind <= "begin"`, and `kind == "end"`
    -> `kind <= "end"` in the `elif`.

    These were written off here as equivalent because "`FLDCHAR_RE`
    captures only begin, end and separate". It does not: it captures
    `(\\w+)`, any word. The schema allows three values, and a writer that
    capitalised one (`Begin`, `End` — both sort BELOW the lower-case
    words) is exactly the input a `<=` reads as a marker. Each half of
    the fixture pairs the odd value with a real one, so that inventing
    the odd marker is what produces a span.
    """
    odd_begin = '<w:fldChar w:fldCharType="Begin"/>'
    odd_end = '<w:fldChar w:fldCharType="End"/>'
    label = _run("<w:t>x</w:t>")

    assert field_spans("<w:p>" + _run(odd_begin) + label + _run(END)
                       + "</w:p>") == [], "`Begin` opened a field"
    assert field_spans("<w:p>" + _run(BEGIN) + label + _run(odd_end)
                       + "</w:p>") == [], "`End` closed a field"


def test_a_marker_CUT_OFF_mid_tag_is_not_a_marker_at_all():
    r"""`FLDCHAR_RE` ends at the type's closing quote, so it matched a
    `<w:fldChar` whose own tag never closed — a part that never parsed —
    and the walk read it as a SEPARATOR. The field then had a cached
    result beginning inside the broken tag, and `_compare_read`'s
    masking landed on a page number by luck rather than by design (S2,
    2026-09-18). A marker is a marker when its tag closes.
    """
    cut = '<w:fldChar w:fldCharType="separate"'
    xml = ("<w:p>" + _run(BEGIN) + _instr(r" REF Table1 \h ")
           + "<w:r>" + cut + "</w:r>" + _run("<w:t>Table 1</w:t>")
           + _run(END) + "</w:p>")

    field, = fields(xml)

    assert field.instr == r" REF Table1 \h ", "the field is still read"
    assert field.result is None, \
        "a `<w:fldChar` with no `>` is not this field's separator"


def test_a_fldCharType_OUTSIDE_the_schema_SEPARATES_and_CLOSES_nothing():
    """The same question at the other two comparisons, which are `>=`
    when they are mutated: `== "separate"` and `== "end"`.

    A value that sorts ABOVE both words is the input they read as a
    marker, and `unknown` is one. Taken as a separator it would give the
    field a result it has not got; taken as an end it would close the
    field early, at the odd marker's run rather than at the real one —
    so the fixture asks the two questions that tell those apart: what
    the field SHOWS, and where its span stops.
    """
    odd = '<w:fldChar w:fldCharType="unknown"/>'
    xml = ("<w:p>" + _run(BEGIN) + _instr(r" REF Table1 \h ") + _run(odd)
           + _run("<w:t>Table 1</w:t>") + _run(END) + "</w:p>")

    field, = fields(xml)
    assert field.result is None, \
        "a field with no separator of its own has no result"

    (_start, _end, body), = field_spans(xml)
    assert body.endswith(END + "</w:r>"), \
        "the field closes on its own end marker, not on the odd one"


# The rest of this walk's survivors are EQUIVALENT, claimed as such and
# left alive:
#
# * `close < 0` -> `close <= 0`, and `-> close < 1` with it. `close` is
#   `xml.find(..., m.end())` and `m.end()` is past the start of the
#   string, so a hit is never 0 and only the -1 miss is negative. The
#   OTHER half of that line is not equivalent and has a test:
#   `r_start` really can be 0, because a fragment opens its first run
#   at the first byte;
# * `-span[1]` -> `~span[1]` in the sort key. `~x` is `-x - 1`, which
#   orders identically to `-x` — a monotone relabelling cannot change
#   a sort.


def test_a_field_whose_BEGIN_RUN_starts_at_offset_ZERO():
    """The guard is `r_start < 0`, and 0 is a valid answer: a fragment
    handed over on its own — a paragraph's runs, a cell's contents —
    opens its first run at the very first byte. A guard written `< 1`
    would discard exactly those fields, and only those, so every
    fixture with a `<w:p>` wrapper around it passes either way.
    """
    xml = _field("Table3txt", "Table 3")

    (start, end, body), = field_spans(xml)

    assert start == 0, "the field opens at the first byte and is real"
    assert end == len(xml)
    assert "Table 3" in body


# ----------------------------------------------------------- ref_anchor --

def test_ref_anchor_by_DEFAULT_answers_only_a_REF_a_reader_can_click():
    """The default is `clickable=True`, and it is the reader's question:
    without `\\h` Word renders the reference as static text. Both halves,
    because each of the guard's mutants errs in ONE direction — dropping
    the `not` loses the clickable one, `or` and a `False` default keep
    the static one."""
    assert ref_anchor(r" REF _Ref211944524 \h \* MERGEFORMAT ") \
        == "_Ref211944524"
    assert ref_anchor(r" REF _Ref211944524 \* MERGEFORMAT ") is None


def test_ref_anchor_NOT_clickable_answers_every_REF_that_depends():
    """`clickable=False` is the question `crossrefs` asks before it
    removes a bookmark, and a switchless field still breaks when its
    target goes. `not clickable and ...` would answer None for exactly
    that field."""
    assert ref_anchor(r" REF _Ref211944524 \* MERGEFORMAT ",
                      clickable=False) == "_Ref211944524"
    assert ref_anchor(r" REF _Ref211944524 \h ",
                      clickable=False) == "_Ref211944524"


def test_ref_anchor_reads_the_name_BARE_and_QUOTED():
    """Group 1 is the quoted name, group 2 the bare one, and exactly one
    of them is set. A fixture in one form hides every mutant that reads
    the other group twice, so both forms, and the bare form is what
    catches the whole-match `group(0)` ("REF _Ref…")."""
    assert ref_anchor(r" REF _Ref211944524 \h ") == "_Ref211944524"
    assert ref_anchor(r' REF "_Ref211944524" \h ') == "_Ref211944524"


# -------------------------------------------------------- field_anchors --

def test_field_anchors_reports_the_anchor_at_its_INSTRUCTION_offset():
    """The name and the offset the docstring promises: the instruction's,
    not the `begin`'s. The offset is built as the body's start plus the
    instruction's place in the body, so the fixture puts both away from
    zero and makes them share a bit — two addends with no bit in common
    cannot tell `+` from `|` or `^`. The lead run is what moves the body
    start; the begin in a run of its own is what moves the instruction
    into the body.
    """
    lead = "<w:p>" + _run("<w:t>see </w:t>")
    xml = lead + _field_of(' HYPERLINK \\l "Table3txt" ') + "</w:p>"
    at, = _instr_offsets(xml)
    body_start = xml.index(BEGIN) + len(BEGIN)
    assert body_start & (at - body_start), \
        "the fixture no longer tells + from |"

    assert field_anchors(xml) == [("Table3txt", at)]


def test_field_anchors_by_DEFAULT_reads_a_switchless_REF_as_no_link():
    """The same default as `ref_anchor`, passed through — and a field
    that names nothing a reader can reach adds NOTHING, not a `None`
    entry: the guard in `add` is what keeps the list to names."""
    xml = ("<w:p>" + _field_of(r" REF _Ref211944524 \* MERGEFORMAT ")
           + "</w:p>")
    at, = _instr_offsets(xml)

    assert field_anchors(xml) == []
    assert field_anchors(xml, clickable=False) == [("_Ref211944524", at)]


def test_an_instruction_SPLIT_across_runs_is_read_JOINED():
    """Word splits an instruction wherever an edit left an rsid boundary,
    and retargeting a cross-reference by retyping its digit leaves
    exactly this: ` REF Table`, `2`, ` \\h `. No piece names the target
    on its own, so only the joined read gets `Table2` — reading the
    pieces one by one (the stray-instruction loop, if the field loop
    never ran) says `Table`, a bookmark that does not exist, or nothing.
    """
    xml = "<w:p>" + _field_of(" REF Table", "2", r" \h ") + "</w:p>"
    first = _instr_offsets(xml)[0]

    assert field_anchors(xml) == [("Table2", first)]
    assert field_anchors(xml, clickable=False) == [("Table2", first)]


def test_a_field_is_reported_ONCE_however_many_runs_its_instruction_has():
    """The pieces of a field's instruction are covered, so the loop for
    stray instructions skips them. Word writes the padding of a
    cross-reference in runs of its own — ` `, `REF _Ref… \\h`, ` ` — and
    the MIDDLE piece names the target by itself: any coverage test that
    stops covering the inside of the field reports it a second time, at
    its own offset. (Only the first piece sits at the body's start, so
    the one mutant that differs there needs the next test.)
    """
    xml = ("<w:p>" + _field_of(" ", r"REF _Ref211944524 \h", " ")
           + "</w:p>")
    first = _instr_offsets(xml)[0]

    assert field_anchors(xml) == [("_Ref211944524", first)]


def test_an_instruction_opening_AT_the_body_start_is_covered_too():
    """`lo <= start`, not `lo < start`. Word puts the `begin` in a run of
    its own, but the python-docx field recipe appends the `fldChar` and
    the `instrText` to ONE run, and then the instruction opens on the
    very first byte of the field body. Split as a retargeting edit
    splits it, that first piece read on its own names `Table` — a second
    entry at the same offset, which `seen` cannot fold into `Table2`.
    """
    xml = ("<w:p><w:r>" + BEGIN
           + '<w:instrText xml:space="preserve"> REF Table</w:instrText></w:r>'
           + _instr("2") + _instr(r" \h ") + _run(SEP)
           + _run("<w:t>Table 2</w:t>") + _run(END) + "</w:p>")
    first = _instr_offsets(xml)[0]
    assert first == xml.index(BEGIN) + len(BEGIN), \
        "the instruction no longer opens where the field body does"

    assert field_anchors(xml, clickable=False) == [("Table2", first)]


def test_a_field_with_NO_instruction_does_not_stop_the_walk():
    """The skip is a `continue`. An empty `<w:instrText/>` matches no
    instruction, and the field after it has its instruction split so
    that only the field loop can read it: stopped early, that field is
    left to the stray loop, which reads ` REF _Ref… ` without its `\\h`
    and reports nothing a reader can click."""
    empty = _run(BEGIN) + _run("<w:instrText/>") + _run(SEP) + _run(END)
    xml = ("<w:p>" + empty + _field_of(" REF _Ref211944524 ", r"\h ")
           + "</w:p>")
    first = _instr_offsets(xml)[1]

    assert field_anchors(xml) == [("_Ref211944524", first)]


def test_an_instruction_whose_field_was_CUT_is_still_reported():
    """The docstring's promise: "a field truncated by an edit still
    reports the bookmark it depends on". One field lost its `begin`
    (BEFORE a whole one), one lost its `end` (AFTER it) — the order is
    the fixture: a stray on each side of a covered range, so a coverage
    test that leaks leftward or rightward swallows one, and the covered
    instruction sits between them, so stopping at it loses the last.
    The first stray is HYPERLINK form and the second REF form, so each
    loop's reading of each form is exercised. The END-cut field comes
    last because one before a whole field would pair its `begin` with
    the whole field's `end`.
    """
    cut_begin = (_instr(' HYPERLINK \\l "Before" ') + _run(SEP)
                 + _run("<w:t>Figure 1</w:t>") + _run(END))
    whole = _field_of(' HYPERLINK \\l "Table3txt" ')
    cut_end = (_run(BEGIN) + _instr(r" REF After \h ") + _run(SEP)
               + _run("<w:t>Table 9</w:t>"))
    xml = "<w:p>" + cut_begin + whole + cut_end + "</w:p>"
    before, middle, after = _instr_offsets(xml)

    assert sorted(field_anchors(xml), key=lambda a: a[1]) == [
        ("Before", before), ("Table3txt", middle), ("After", after)]


def test_a_STRAY_instruction_is_read_from_its_TEXT_not_its_tags():
    """Group 1 of `INSTR_RE`, not the whole match. The two read alike
    wherever the name is followed by a space — the bare-name pattern
    stops there — so the fixture ends a piece ON the name, as Word does
    when it puts the `\\h` switch in a run of its own: read with its
    tags, the name runs on into `</w:instrText>`.
    """
    cut_begin = (_instr(" REF _Ref211944524") + _instr(r" \h ") + _run(SEP)
                 + _run("<w:t>Table 1</w:t>") + _run(END))
    xml = "<w:p>" + cut_begin + "</w:p>"
    first = _instr_offsets(xml)[0]

    assert field_anchors(xml, clickable=False) == [("_Ref211944524", first)]


# `field_anchors` survivors EQUIVALENT and claimed rather than tested —
# all three rest on the same fact, that a coverage range's ends are
# `fldChar` tags and an `<w:instrText` cannot start on one:
#
# * `m.start(1)` -> `m.start(0)` and `m.end(1)` -> `m.end(0)` in
#   `covered`: the range grows by the `begin` or the `end` tag, and a
#   tag cannot hold a `<` in well-formed XML;
# * `< hi` -> `<= hi`: `hi` is where the `end` tag's `<w:fldChar` starts.
# ------------------------------------------- fields NEST: paired by DEPTH --
#
# The readers on top of the walk — `field_anchors`, `internal_links`,
# `dead_links` — paired a `begin` with the FIRST `end` after it, which is
# not the field's end when another field sits inside it. Word writes one
# inside another whenever the text a REF copies held a link of its own,
# and everything inside a TOC. The instructions then joined into ONE
# string and the pair reported ONE anchor.


def _code(text: str) -> str:
    """One run of a field's CODE — Word splits it at rsid boundaries."""
    return _run(f'<w:instrText xml:space="preserve">{text}</w:instrText>')


def _code_offsets(xml: str) -> list[int]:
    return [m.start() for m in re.finditer("<w:instrText", xml)]


def _around(instr: str, inner: str) -> str:
    """A field whose cached RESULT is the field `inner` — what Word
    writes when the bookmark a REF points at held a field itself."""
    return _run(BEGIN) + _code(instr) + _run(SEP) + inner + _run(END)


def _link(anchor: str, shown: str) -> str:
    return (_run(BEGIN) + _code(f' HYPERLINK \\l "{anchor}" ') + _run(SEP)
            + _run(f"<w:t>{shown}</w:t>") + _run(END))


def test_fields_gives_a_NESTED_field_its_own_instruction_and_result():
    """The primitive under all three readers. The outer field's
    instruction is its own — the inner one's belongs to the inner
    entry — and its result is everything it SHOWS, the nested field
    included, because that is what the reader sees."""
    inner = _link("Appendix", "Appendix A")
    xml = "<w:p>" + _around(r" REF Table1 \h ", inner) + "</w:p>"

    outer, nest = fields(xml)

    assert outer.instr == r" REF Table1 \h "
    assert nest.instr == ' HYPERLINK \\l "Appendix" '
    assert outer.start < nest.start and outer.end > nest.end
    sep_at = xml.index(SEP, nest.start) + len(SEP)
    assert nest.result == xml[sep_at:xml.index(END, sep_at)], \
        "a result runs from past its own separator to its own end marker"
    assert "instrText" not in (nest.result or ""), "a result is what it SHOWS"
    assert inner in (outer.result or ""), "and the outer shows the inner one"


def test_a_field_NESTED_in_another_is_read_as_a_LINK_OF_ITS_OWN():
    r"""Both anchors, each at its own instruction. Joined, the two codes
    read `REF Table1 \h HYPERLINK \l "Appendix"`, which names the
    HYPERLINK and loses the REF — so `crossrefs.field_targets` did not
    hold Table1, `unlink` removed that bookmark and reported a healthy
    count, and the REF was left dangling.
    """
    xml = ("<w:p>" + _around(r" REF Table1 \h ", _link("Appendix", "A"))
           + "</w:p>")
    outer_at, inner_at = _code_offsets(xml)

    assert field_anchors(xml, clickable=False) == [
        ("Table1", outer_at), ("Appendix", inner_at)]
    assert field_anchors(xml) == [("Table1", outer_at), ("Appendix", inner_at)]


def test_a_switchless_REF_is_not_made_clickable_by_the_field_INSIDE_it():
    r"""The `\h` a field is judged by has to be its own. Read as one
    string, the inner field's switch made the static outer REF look
    like a link a reader can follow — and the inner field, the one that
    really is a link, was not reported at all.
    """
    xml = ("<w:p>" + _around(" REF Table1 ", _link("Appendix", "A"))
           + "</w:p>")
    outer_at, inner_at = _code_offsets(xml)

    assert field_anchors(xml) == [("Appendix", inner_at)], \
        "a REF with no switch is not a link a reader can click"
    assert field_anchors(xml, clickable=False) == [
        ("Table1", outer_at), ("Appendix", inner_at)], \
        "both still DEPEND on their bookmarks"


def test_a_field_that_lost_its_END_does_not_swallow_the_NEXT_one():
    """The other half of pairing by depth. A field an edit truncated
    used to take the next field's `end` for its own, so the whole field
    after it disappeared into it — instruction, anchor and all.
    """
    cut = (_run(BEGIN) + _code(r" REF Table1 \h ") + _run(SEP)
           + _run("<w:t>Table 1</w:t>"))
    whole = _run(BEGIN) + _code(r" REF Table2 \h ") + _run(SEP) \
        + _run("<w:t>Table 2</w:t>") + _run(END)
    xml = "<w:p>" + cut + whole + "</w:p>"
    first, second = _code_offsets(xml)

    assert field_anchors(xml) == [("Table1", first), ("Table2", second)]


def test_internal_links_reads_the_NESTED_field_as_a_link_of_its_own():
    """The same pairing, one reader further out: the label is what the
    field SHOWS, and the nested link is a link in its own right."""
    xml = ("<w:p>" + _around(r" REF Table1 \h ", _link("Appendix", "A"))
           + "</w:p>")

    assert internal_links(xml) == [("Table1", "A"), ("Appendix", "A")]


def test_a_field_an_edit_TRUNCATED_is_not_a_link_a_reader_can_CLICK():
    """Two questions, and the walk answers both. `field_anchors` reports
    the bookmark a cut field still DEPENDS on — removing it is what
    turns the field into "Error! Reference source not found" — while
    `internal_links` and `dead_links` report what is on the PAGE, and a
    field with no end is not something Word renders as a link at all.
    """
    cut = (_run(BEGIN) + _code(' HYPERLINK \\l "Appendix" ') + _run(SEP)
           + _run("<w:t>A</w:t>"))
    xml = "<w:p>" + cut + "</w:p>"
    at, = _code_offsets(xml)

    assert field_anchors(xml) == [("Appendix", at)]
    assert internal_links(xml) == []
    assert dead_links(xml) == []


def test_the_SENTINELS_a_cut_field_and_a_codeless_one_report():
    """`Field.end` is -1 where nothing closed the field and `Field.at` is
    -1 where the field has no instruction at all. Both are read as
    `< 0` — here, in `field_spans` and in `internal_links` — so a
    sentinel that drifts to 0 or 1 makes a field those two then try to
    close, and an offset of -2 is a documented value that is not the
    documented one."""
    stray = _code(' HYPERLINK \\l "Cut" ')            # its `begin` cut off
    cut = (_run(BEGIN) + _code(r" REF Table1 \h ") + _run(SEP)
           + _run("<w:t>T</w:t>"))                    # its `end` cut off
    codeless = _run(BEGIN) + _run(SEP) + _run("<w:t>x</w:t>") + _run(END)

    (orphan,) = fields("<w:p>" + stray + "</w:p>")
    (unclosed,) = fields("<w:p>" + cut + "</w:p>")
    (quiet,) = fields("<w:p>" + codeless + "</w:p>")

    assert (orphan.end, orphan.at) == (-1, orphan.start)
    assert unclosed.end == -1
    assert (quiet.at, quiet.instr) == (-1, "")
    assert quiet.end > 0, "it closed; only its instruction is missing"


def test_an_instruction_PAST_its_field_SEPARATOR_belongs_to_no_field():
    """`sep_end` is what says a field has stopped collecting code. An
    instruction in the RESULT half is one whose `begin` an edit cut off,
    and joining it to the field that shows it reads two codes as one —
    the defect the depth pairing exists for, one level in."""
    xml = ("<w:p>" + _run(BEGIN) + _code(r" REF Table1 \h ") + _run(SEP)
           + _code(' HYPERLINK \\l "Orphan" ') + _run("<w:t>T</w:t>")
           + _run(END) + "</w:p>")

    outer, orphan = fields(xml)

    assert outer.instr == r" REF Table1 \h "
    assert orphan.instr == ' HYPERLINK \\l "Orphan" '
    assert orphan.end == -1, "it is not a field a reader can click"


@pytest.mark.parametrize("pad", ["", "x"], ids=["even", "odd"])
def test_a_RESULT_starts_past_the_WHOLE_separator_marker(pad):
    """`close + 1` is the byte after the marker's `>`, not after the
    attribute the pattern matched: the caller reads a result as XML, and
    one that starts inside `/>` is not.

    Two fixtures a byte apart because `close ^ 1` and `close | 1` both
    give `close + 1` whenever that offset is EVEN, so a single fixture
    can only see them half the time — which is how both survived a
    suite that already pins a nested field's result exactly.
    """
    xml = ("<w:p>" + _run(f"<w:t>{pad}</w:t>") + _run(BEGIN)
           + _code(r" REF Table1 \h ") + _run(SEP)
           + _run("<w:t>Table 1</w:t>") + _run(END) + "</w:p>")

    (field,) = fields(xml)

    assert field.result == xml[xml.index(SEP) + len(SEP):xml.index(END)]


def test_field_spans_SKIPS_a_field_that_never_closed_and_walks_ON():
    """A field with no `end` has nothing to close on, and the walk has to
    step OVER it rather than stop: the cut one comes first here, so a
    `break` where the `continue` is loses the whole field behind it.

    Only that. The `f.end < 0` test above it decides nothing on its own —
    `xml.find("</w:r>", -1)` searches the last character alone and cannot
    match a six-character close tag, so the very same field is refused a
    line later by `close < 0`. Measured, not assumed: both halves of that
    sentinel survive every test in this file. `internal_links` writes the
    same line and there it IS load-bearing, which is why the two readers
    disagree about how much that guard is worth.
    """
    cut = (_run(BEGIN) + _code(r" REF Table1 \h ") + _run(SEP)
           + _run("<w:t>T</w:t>"))
    whole = _link("Appendix", "A")
    xml = "<w:p>" + cut + whole + "</w:p>"

    spans = field_spans(xml)

    assert len(spans) == 1, "one span: the field that closed"
    assert spans[0][0] >= xml.index(whole), "and it is the second one"


def test_internal_links_walks_PAST_a_field_that_never_closed():
    """Same step, the other reader: a cut field is not a link on the
    page, and the link after it still is."""
    cut = (_run(BEGIN) + _code(' HYPERLINK \\l "Cut" ') + _run(SEP)
           + _run("<w:t>C</w:t>"))
    xml = "<w:p>" + cut + _link("Appendix", "A") + "</w:p>"

    assert internal_links(xml) == [("Appendix", "A")]


def test_spans_that_TIE_are_wider_first_when_the_NARROW_one_is_found_first():
    """The other side of `-span[1]`. Where two fields merely open in one
    run the outer is found first anyway, so the tie-break decides
    nothing; here the first field CLOSES inside the run the second opens
    in, so the narrower span is found first and the key is the only
    thing that puts the wider one in front of it."""
    xml = ("<w:p><w:r>" + BEGIN + END + BEGIN + "</w:r>"
           + _run("<w:t>x</w:t>") + _run(END) + "</w:p>")

    spans = field_spans(xml)

    assert len(spans) == 2
    assert spans[0][0] == spans[1][0], "the fixture no longer ties"
    assert spans[0][1] > spans[1][1], "wider first, however it was found"


def test_dead_links_sees_the_label_that_follows_a_nested_field():
    """A field's result ends at ITS end, not at the first one. Cut short
    at the nested field's end, the label after it was invisible and the
    link read as empty — a report of damage where there is none, which
    is the costly direction for a gate nobody can check by eye.
    """
    shown = _link("Appendix", "")            # emptied by an edit: really dead
    live = ("<w:p>" + _run(BEGIN) + _code(' HYPERLINK \\l "Table1" ')
            + _run(SEP) + shown + _run("<w:t>Table 1</w:t>") + _run(END)
            + "</w:p>")

    assert dead_links(live) == ["Appendix"], \
        "only the emptied inner link is dead; the outer one shows a label"
