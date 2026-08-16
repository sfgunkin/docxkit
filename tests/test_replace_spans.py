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
from docxkit.edit import replace_in_para
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
