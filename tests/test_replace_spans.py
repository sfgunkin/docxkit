"""`replace_in_para`'s span arithmetic, stated as values.

Ten mutants survived here on 2026-08-16, the largest cluster left in
`edit.py` — and it is the function every paper calls most. Its tests
asserted on the text that came out of the ORDINARY case, and nine
survivors show in the sample: four in the comparisons that decide which
runs the match touches, three equivalent by construction (listed at the
foot of this file), one in the signature and one in a message.

The four are boundaries:

* which runs the note guard inspects (`start >= end`);
* which runs the edit loop rewrites (the same `start >= end`, one
  character apart in meaning);
* whether the match runs on past a hyperlink's label (`end >
  label_end`), which mutates two ways.

A boundary comparison cannot be checked by a case that sits in the
middle of it. Every test here puts a run edge exactly ON the offset in
question, which is the only place these mutants are visible — and where
the real failures are too: the run boundary is wherever Word last split
the prose, so a manuscript hits these constantly and never twice in the
same place.
"""
from __future__ import annotations

import pytest
from conftest import para, run

from docxkit import text_of
from docxkit.edit import replace_in_para, visible_text
from docxkit.errors import AnchorError

FN_REF = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
          '<w:footnoteReference w:id="11"/></w:r>')


def test_the_guard_flags_are_KEYWORD_only():
    """`allow_hyperlink` and its neighbours turn OFF a guard against a
    silent wrong answer, so they have to be named at the call site. A
    positional bool reads as data — `replace_in_para(p, old, new, True)`
    says nothing about which guard it just disabled, and the diff that
    introduces it says nothing either.
    """
    p = para(run("The share rose."))
    with pytest.raises(TypeError):
        replace_in_para(p, "rose", "fell", True)   # type: ignore[call-arg]


def test_a_note_marker_BEYOND_the_match_does_not_refuse():
    """The note guard asks which runs the match TOUCHES. A marker later
    in the paragraph is not one of them, and refusing there would be a
    refusal no anchor can work around: a footnote anywhere after the
    edit would make the paragraph uneditable.

    The match ends mid-run on purpose. When it ends on a run edge the
    next run starts exactly at `end`, which the boundary excludes for a
    second, unrelated reason — so that arrangement cannot tell the two
    apart.
    """
    p = ("<w:p>" + run("Migration from South") + run(" Korea and Japan rose")
         + FN_REF + run(" after 2014.") + "</w:p>")

    out = replace_in_para(p, "from South Korea", "from Kazakhstan")

    assert text_of(out) == \
        "Migration from Kazakhstan and Japan rose after 2014."
    assert '<w:footnoteReference w:id="11"/>' in out


def test_a_LINK_run_starting_where_the_match_ENDS_is_left_alone():
    """A cross-reference immediately after the edited words is the
    commonest layout in these papers -- "see Table 3" is a link, and the
    lead-in before it is prose. The run boundary and the match end are
    the SAME offset there, so a comparison one character out either
    rewrites the label or refuses the edit outright.
    """
    p = para(run("see "), run("Table 3", style="Hyperlink"),
             run(" for detail"))

    out = replace_in_para(p, "see ", "cf. ")

    assert text_of(out) == "cf. Table 3 for detail"
    assert 'w:val="Hyperlink"' in out
    assert "<w:t>Table 3</w:t>" in out, "the label was rewritten"


# The label guard, at both of its edges. `test_find_edit.py` covers the
# match that runs PAST the label (refused) and the one that fills it
# exactly (allowed). Neither pins the third case -- a match ending
# strictly inside a longer label -- and that is the one a paper hits
# whenever it links a whole caption, which several do on purpose.

WHOLE_CAPTION = ('<w:hyperlink w:anchor="Table4txt" w:history="1">'
                 '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                 "<w:t>Table 4: The likelihood of using non-violent "
                 "discipline</w:t></w:r></w:hyperlink>")


def test_editing_a_word_INSIDE_a_longer_label_is_allowed():
    p = "<w:p>" + WHOLE_CAPTION + "</w:p>"

    out = replace_in_para(p, "non-violent", "coercive", allow_hyperlink=True)

    assert text_of(out) == ("Table 4: The likelihood of using coercive "
                            "discipline")
    assert out.count("<w:hyperlink") == 1, "the label was split in two"


def test_a_match_FILLING_a_label_is_allowed_at_any_offset():
    """The guard compares two computed offsets, and equal offsets have
    to compare equal wherever they fall. CPython interns small integers
    and not large ones, so an identity test in place of an equality test
    passes every short fixture and refuses the same edit in a real
    paragraph -- which is why the prose here is long enough to push the
    label past the cache.
    """
    lead = ("Discipline practices vary widely across the region, and the "
            "gradient by education is steeper in the countries that "
            "reformed their family codes earliest, which the next table "
            "sets out in full for each of the twenty-eight countries in "
            "the sample, alongside the standard errors. ")
    link = ('<w:hyperlink w:anchor="Table4txt">'
            '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            "<w:t>Table 4</w:t></w:r></w:hyperlink>")
    p = "<w:p>" + run(lead, preserve=True) + link + "</w:p>"
    assert len(lead) > 256, "the fixture no longer tests what it says"

    out = replace_in_para(p, "Table 4", "Table 5", allow_hyperlink=True)

    assert text_of(out) == lead + "Table 5"
    assert "<w:t>Table 5</w:t>" in out


def test_an_ambiguous_anchor_is_QUOTED_but_not_dumped():
    """Both refusals name the anchor, and both cut it at the same
    length: an anchor is often a whole sentence, and a message that
    prints it entire is a message nobody reads to the end.
    """
    long_anchor = ("the share of workers aged 55 and over in the region "
                   "rose steadily over the decade")
    p = para(run(f"{long_anchor} A {long_anchor} B"))

    with pytest.raises(AnchorError) as plain:
        replace_in_para(p, long_anchor, "X")
    with pytest.raises(AnchorError) as norm:
        replace_in_para(p, long_anchor, "X", normalize=True)

    for excinfo in (plain, norm):
        message = str(excinfo.value)
        assert "occurs twice" in message
        assert long_anchor[:60] in message
        assert long_anchor[:61] not in message, "the anchor was not cut"


# Two mutants in this function are EQUIVALENT and are left alive
# deliberately, recorded here so the next reader does not spend the
# afternoon twice:
#
# * `zip(spans, runs, strict=True)` -> `strict=False`. The two lists are
#   built together by `_locate`, one span per run, and
#   `test_locate_spans.py` pins that invariant at the source. `strict`
#   here is a second lock on a door that is already bolted.
# * `hits[0]` -> `hits[-1]` on the normalized path. The line above it
#   raises when `len(hits) > 1`, so the list has exactly one element and
#   the two index expressions cannot disagree.


# --- the run of 2026-08-20: what the refusals QUOTE ---------------------
#
# Four cuts, four mutants, and the same argument for each: a refusal is
# read by a person deciding where to anchor next, and the quotation is
# how they find the place. Whole, it is a paragraph of XML-ish prose in
# a traceback; too short, two anchors read alike.

_LONG = ("the quick brown fox jumps over the lazy dog and keeps running "
         "past it")


def _refused(para_xml: str, old: str, new: str, **kw) -> str:
    with pytest.raises(AnchorError) as caught:
        replace_in_para(para_xml, old, new, **kw)
    return str(caught.value)


def test_a_missing_anchor_is_quoted_to_SIXTY_characters():
    """`old[:60]`, in the refusal every caller meets first."""
    said = _refused(f"<w:p>{run('Nothing here.')}</w:p>", _LONG, "x")

    assert "'the quick brown fox jumps over the lazy dog and keeps runnin'" \
        in said, said


def test_the_note_crossing_refusal_quotes_THIRTY_of_the_replacement():
    """`new[:30]`. The message's point is that the marker moves to the
    END of what is written, so what is written has to be visible in
    it."""
    para_xml = (f"<w:p>{run('The claim')}"
                '<w:r><w:footnoteReference w:id="11"/></w:r>'
                f"{run(' stands firm.')}</w:p>")

    said = _refused(para_xml, "claim stands", _LONG)

    assert "MOVES to the end of 'the quick brown fox jumps over'" in said, said


def test_the_label_swallow_refusal_quotes_FORTY_of_the_replacement():
    """`new[:40]`, and it is the longest of the four on purpose: this
    message is about what the LINK would come to say, so the reader is
    being shown a title."""
    para_xml = (f"<w:p>{run('See ')}"
                '<w:hyperlink w:anchor="a"><w:r><w:t>the label here</w:t>'
                f"</w:r></w:hyperlink>{run(' and beyond it.')}</w:p>")

    said = _refused(para_xml, "label here and beyond", _LONG,
                    allow_hyperlink=True)

    assert "writing 'the quick brown fox jumps over the lazy '" in said, said


def test_the_emptying_refusal_quotes_THIRTY_of_the_LABEL():
    """`visible_text(run_xml)[:30]` — the label about to be emptied,
    which is the one thing a reader needs to recognise the link."""
    label = "a link label that is quite long indeed"
    para_xml = (f"<w:p>{run('Start ')}"
                f'<w:hyperlink w:anchor="a"><w:r><w:t>{label}</w:t>'
                f"</w:r></w:hyperlink>{run(' end.')}</w:p>")

    said = _refused(para_xml, f"Start {label} end.", "x")

    assert "emptying 'a link label that is quite lon'" in said, said


def test_a_note_reference_with_NO_id_is_named_by_its_kind():
    """`m.group(1)` is the KIND — "footnote", "endnote" — and the
    fallback for a reference carrying no `w:id` is that word alone. The
    whole match is markup, and a refusal that says "the match crosses
    <w:footnoteReference/>" is a message about the file rather than
    about the sentence a person is editing.

    Word always writes the id; this is the branch that decides what a
    document Word did not write reads like."""
    from docxkit.edit import _note_in

    assert _note_in('<w:r><w:footnoteReference w:id="11"/></w:r>') \
        == "footnote 11"
    assert _note_in("<w:r><w:footnoteReference/></w:r>") == "footnote"
    assert _note_in("<w:r><w:t>plain</w:t></w:r>") is None


# --- the run of 2026-09-17: fields, notes and maths at their edges -------
#
# Three guards met on 2026-09-17: a cross-reference's result is a label
# even with no style on it, a match may not cross an inline equation, and
# the note guard `_rewrite_span` inherited. The survivors the sweep left
# in them sat exactly where the fixtures never went — a marker sharing a
# run with words, a field result at an ODD run index or split across two
# runs, an equation at the second seam, offsets past CPython's small-int
# cache.

#: Long enough that every offset after it is a fresh int object: `is`
#: and `==` agree on 0..256 and nowhere else. No "see", " and ", "where"
#: or "Table" in it, so the anchors after it stay unique.
_PAST_THE_CACHE = ("Discipline practices vary widely across the region; "
                   "the gradient by education is steeper in the countries "
                   "that reformed their family codes earliest, which the "
                   "next table sets out in full for each of the "
                   "twenty-eight countries in the sample, alongside the "
                   "standard errors of every estimate reported. ")
_EQ = "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"


def _ref(name: str, *result: str) -> str:
    """Word's Insert > Cross-reference: `REF name \\h`, result unstyled."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> REF {name} \\h '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + "".join(result)
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


_REF3 = _ref("_Ref1", run("Table 3"))
_REF4_SPLIT = _ref("_Ref2", run("Table"), run(" 4", preserve=True))


def test_a_marker_SHARING_a_run_with_the_words_is_not_crossed():
    """One touched run cannot move a marker: the words are rewritten
    where they stand and the reference after them stays after them. That
    is what `len(touched) <= 1` says, and it is invisible unless the
    marker lives in the very run the match is in — Word gives a reference
    a run of its own, a build script need not."""
    p = para(run("The "), "<w:r><w:t>claim stands</w:t>"
             '<w:footnoteReference w:id="11"/></w:r>', run(" firm."))

    out = replace_in_para(p, "claim", "point")

    assert text_of(out) == "The point stands firm."
    assert out.index("point stands") < out.index("footnoteReference")


def test_a_marker_in_the_SECOND_of_two_touched_runs_is_crossed():
    """Two touched runs are enough to move one: the replacement goes into
    the first, the second is emptied around its reference, and the marker
    ends up after the new words. Every other fixture gives the marker a
    run of its own, so THREE runs were touched and a guard asking for
    more than two passed them all."""
    p = para(run("The claim"), '<w:r><w:footnoteReference w:id="11"/>'
             '<w:t xml:space="preserve"> stands</w:t></w:r>', run(" firm."))

    with pytest.raises(AnchorError, match="crosses footnote 11"):
        replace_in_para(p, "claim stands", "point holds")


@pytest.mark.parametrize("before,old,verb", [
    pytest.param((), "Table 3 for", "starts in", id="starts_in"),
    pytest.param((run("see "),), "see Table 3 for", "crosses", id="crosses"),
])
def test_the_field_refusal_says_where_the_match_MEETS_the_result(
        before, old, verb):
    """"starts in" and "crosses" ask for different anchors, so the
    refusal has to say which one it is.

    With nothing before the field its result is run 3 — begin,
    instruction, separate, result. `range(first, last + 1)` written as
    `last ^ 1` or `last | 1` leaves an ODD last index out of the label,
    and a lead-in run had put every earlier result at an even one."""
    p = para(*before, _REF3, run(" for detail"))

    with pytest.raises(AnchorError,
                       match=f"the match {verb} the result of a field"):
        replace_in_para(p, old, "x for")


@pytest.mark.parametrize("lead", [
    pytest.param("", id="short"),
    pytest.param(_PAST_THE_CACHE, id="past_256"),
])
def test_a_field_result_SPLIT_across_runs_is_ONE_label(lead):
    """Word fragments a field's result as freely as prose. The two runs
    of "Table 4" are one label: filling it with `allow_hyperlink=True`
    is the deliberate retitle, not a match that "ends outside" a label
    one run long. The prose between two fields is nobody's label. And a
    match crossing a field is refused on the RESULT, quoting its words —
    not on the begin marker, which shows nothing.

    Two fields, because merging a run into "the last label" and into
    "the first label" are the same thing while there is only one; and
    past 256 characters, because a merge that asks whether two offsets
    are the SAME int object, or a zero-width run whose start and stop
    are, answers differently there."""
    assert len(_PAST_THE_CACHE) > 256, "the fixture no longer tests it"
    p = para(run(lead + "see ", preserve=True), _REF3,
             run(" and ", preserve=True), _REF4_SPLIT, run(" below."))

    out = replace_in_para(p, "Table 4", "Table 5", allow_hyperlink=True)
    assert visible_text(out) == lead + "see Table 3 and Table 5 below."
    assert "REF _Ref2" in out

    out = replace_in_para(p, " and ", " or ")
    assert visible_text(out) == lead + "see Table 3 or Table 4 below."

    with pytest.raises(AnchorError) as crossed:
        replace_in_para(p, "see Table 3", "consult Table 3")
    assert "'Table 3' would return beside" in str(crossed.value)


@pytest.mark.parametrize("old,new,want", [
    pytest.param("rate", "level", "where x is the level.", id="after_it"),
    pytest.param("wher", "Wher", "Where x is the rate.", id="before_it"),
])
def test_an_equation_wholly_OUTSIDE_the_match_is_not_crossed(old, new, want):
    """The guard's two inequalities, each from the side the touching
    cases leave open: an equation that ENDS before the match starts, and
    one that STARTS after it ends. Neither is crossed, and both sit on a
    run seam the loop inspects."""
    p = para(run("where "), _EQ, run(" is the rate."))

    assert visible_text(replace_in_para(p, old, new)) == want


@pytest.mark.parametrize("head,tail", [
    pytest.param((), (" is", " it."), id="first_seam"),
    pytest.param(("a ",), (" is it.",), id="second_seam"),
])
def test_the_maths_refusal_NAMES_the_equation_at_any_seam(head, tail):
    """The equation is read off the gap between run i and run i + 1.

    Three runs either way. At the SECOND seam `i ^ 1` and `i | 1` point
    back at the first run and see no gap, and `range(len(runs) >> 1)`
    never reaches it. At the FIRST, with a run beyond the one after the
    maths, `runs[i - 1]` wraps to the last run and quotes prose as the
    equation — and every other rewrite of `i + 1` quotes nothing."""
    p = para(*(run(t, preserve=True) for t in head),
             run("where ", preserve=True), _EQ,
             *(run(t, preserve=True) for t in tail))

    with pytest.raises(AnchorError, match=r"crosses an equation \('x'\)"):
        replace_in_para(p, "where  is", "here, is")


def test_a_seam_past_256_characters_is_compared_by_VALUE():
    """Past the small-int cache, two equal offsets computed apart are two
    objects. The match crosses a plain seam (no maths: the reader's
    offsets do not jump there) and ENDS on the equation (touching it,
    not crossing it) — and both answers are "not crossed" only when the
    offsets are compared with `>` and `<`, not by identity."""
    assert len(_PAST_THE_CACHE) > 256, "the fixture no longer tests it"
    p = para(run(_PAST_THE_CACHE), run("where ", preserve=True), _EQ,
             run(" is it."))

    out = replace_in_para(p, "ported. where ", "ported. here ")

    assert visible_text(out) == _PAST_THE_CACHE + "here x is it."
