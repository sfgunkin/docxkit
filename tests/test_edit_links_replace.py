"""Editing a sentence AROUND the links in it, and trimming a paragraph's end.

`replace_in_para` refuses a match that crosses a link, and says why: the
following runs are emptied and the link's own label is one of them. The
refusal tells the caller to "split the replacement into one call on each
side of the link" — and every caller then wrote that split by hand. DSI's
UNFPA-definition batch (2026-09-16) replaced two whole paragraphs holding
linked citations, «…(Sen 1999).» and «…(Bongaarts and Bulatao 1999).»,
and needed ninety lines to do it: find the label spans inside the anchor,
require the replacement to carry each label in order, edit the pieces
right to left, turn a piece that only grows into an insertion — and
refuse a bare ")." piece because a text replace could not tell which
")." in the paragraph was meant. `replace_keeping_links` is that code,
with the last refusal gone: the pieces are edited by OFFSET.

The same batch trimmed a paragraph's trailing space (¶43) by hand, and
imported four run-walk helpers `edit` hands out without declaring them.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from enum import StrEnum

import pytest
from conftest import para, run

from docxkit import _xml, edit
from docxkit.edit import (
    replace_in_para,
    replace_keeping_links,
    rstrip_para,
    visible_text,
)
from docxkit.errors import AnchorError

FN_REF = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
          '<w:footnoteReference w:id="11"/></w:r>')
OMATH = "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"


def link_field(anchor: str, label: str, *, instr: str = "",
               styled: bool = True) -> str:
    """A field-form link as the builds write it: machinery, then a label."""
    rpr = '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>' if styled else ""
    code = instr or f'HYPERLINK \\l "{anchor}"'
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText>'
            "</w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f"<w:r>{rpr}<w:t>{label}</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def link_element(anchor: str, label: str) -> str:
    """The same link after an author's Word save: an element."""
    return (f'<w:hyperlink w:anchor="{anchor}" w:history="1"><w:r><w:rPr>'
            f'<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>{label}</w:t></w:r>'
            "</w:hyperlink>")


def txt_marked(field_xml: str, name: str = "Sen1999txt", bid: int = 7) -> str:
    """The in-text end of a citation's back-link: a bookmark round it."""
    return (f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>{field_xml}'
            f'<w:bookmarkEnd w:id="{bid}"/>')


SEN = txt_marked(link_field("Sen1999", "Sen 1999"))


# ------------------------------------------------------ the real shapes


def test_a_FIELD_citation_keeps_label_field_and_bookmark_as_its_sides_change():
    """The DSI ¶29 shape. The words before and after the citation are
    rewritten; the field, its label and the `Sen1999txt` bookmark round
    it come out byte for byte, and still contiguous."""
    p = para(run("As the capability approach argues ("), SEN,
             run("), freedom matters."))

    out = replace_keeping_links(
        p, "capability approach argues (Sen 1999), freedom matters.",
        "capability framework holds (Sen 1999), freedom is what matters.")

    assert visible_text(out) == ("As the capability framework holds "
                                 "(Sen 1999), freedom is what matters.")
    assert SEN in out
    assert _xml.internal_links(out) == [("Sen1999", "Sen 1999")]


def test_an_ELEMENT_link_is_edited_around_the_same_way():
    """After an author's save the same citation is a `w:hyperlink`, and
    the helper cannot care which form it meets."""
    table = link_element("Table3", "Table 3")
    p = para(run("The estimates in "), table, run(" rise with age."))

    out = replace_keeping_links(p, "estimates in Table 3 rise with age.",
                                "results in Table 3 fall with age.")

    assert visible_text(out) == "The results in Table 3 fall with age."
    assert table in out


def test_a_piece_that_is_NOT_unique_in_the_paragraph_is_edited_by_OFFSET():
    """DSI's version refused here. "It fell (" occurs twice in the
    paragraph, and only the second one is inside `old` — a text replace
    of the piece cannot say which is meant; its offset can."""
    p = para(run("It fell (A). It fell ("), SEN, run(")."))

    out = replace_keeping_links(p, "It fell (Sen 1999).",
                                "It rose (Sen 1999).")

    assert visible_text(out) == "It fell (A). It rose (Sen 1999)."
    assert SEN in out


def test_two_links_in_one_span_each_keep_their_place():
    first = link_element("Table3", "Table 3")
    second = link_element("Table4", "Table 4")
    p = para(run("See "), first, run(" and "), second, run(" below."))

    out = replace_keeping_links(p, "See Table 3 and Table 4 below.",
                                "Compare Table 3 with Table 4 above.")

    assert visible_text(out) == "Compare Table 3 with Table 4 above."
    assert first in out and second in out
    assert out.index(first) < out.index(second)


def test_a_repeated_LABEL_maps_to_the_occurrence_in_the_same_POSITION():
    """"Sen 1999" is also plain text inside `old`, before the link. It
    occurs twice in `old` and twice in `new`, so the link is the SECOND
    occurrence in both — not the first one a left-to-right search
    meets, which would move the link onto the prose mention."""
    p = para(run("Sen 1999 is cited ("), SEN, run(")."))

    out = replace_keeping_links(p, "Sen 1999 is cited (Sen 1999).",
                                "Sen 1999 is often cited (Sen 1999).")

    assert visible_text(out) == "Sen 1999 is often cited (Sen 1999)."
    assert SEN in out
    assert out.index("often") < out.index(SEN)


def test_an_UNSTYLED_cross_reference_is_a_label_too():
    """Word's own Insert > Cross-reference writes `REF _Ref… \\h` with a
    result run that states no style. `replace_in_para` does not see a
    label there; this helper does, because a field's result is what
    Word regenerates — text written into it is not the author's either."""
    ref = link_field("", "Table 3", instr="REF _Ref1 \\h", styled=False)
    p = para(run("see "), ref, run(" for detail"))

    out = replace_keeping_links(p, "see Table 3 for detail",
                                "consult Table 3 for the detail")

    assert visible_text(out) == "consult Table 3 for the detail"
    assert ref in out


# ----------------------------------------------- pieces that only GROW


def test_text_put_BEFORE_a_link_that_opens_old_lands_outside_it():
    """`old` IS the label, so the piece before it is empty and there is
    no run of its own to write into. The words go in as a new run,
    outside the bookmark and the field."""
    p = para(run("A claim ("), SEN, run(")."))

    out = replace_keeping_links(p, "Sen 1999", "see Sen 1999")

    assert visible_text(out) == "A claim (see Sen 1999)."
    assert out.index("see ") < out.index(SEN)
    assert SEN in out


def test_text_put_AFTER_a_link_that_closes_old_lands_outside_it():
    p = para(run("A claim ("), SEN, run(")."))

    out = replace_keeping_links(p, "Sen 1999", "Sen 1999 and Nussbaum 2000")

    assert visible_text(out) == "A claim (Sen 1999 and Nussbaum 2000)."
    assert out.index(SEN) < out.index(" and Nussbaum")
    assert SEN in out


def test_text_put_BETWEEN_two_adjacent_links_touches_neither():
    first = link_element("Table3", "Table 3")
    second = link_element("Table4", "Table 4")
    p = para(run("See "), first, second, run("."))

    out = replace_keeping_links(p, "Table 3Table 4", "Table 3 and Table 4")

    assert visible_text(out) == "See Table 3 and Table 4."
    assert first in out and second in out
    assert out.index(first) < out.index(" and ") < out.index(second)


def test_a_NEW_run_takes_the_PROSE_formatting_not_the_link_s():
    """A bare `<w:r>` would drop the direct formatting every other run
    in a manuscript carries — the face and size set on runs rather than
    by style. The new run copies the nearest plain run's LIVE
    properties: never the Hyperlink style, never a tracked-change
    snapshot."""
    prose = ('<w:r><w:rPr><w:sz w:val="24"/><w:rPrChange w:id="3" '
             'w:author="A" w:date="2026-09-16T00:00:00Z"><w:rPr>'
             '<w:sz w:val="20"/></w:rPr></w:rPrChange></w:rPr>'
             "<w:t>A claim (</w:t></w:r>")
    p = para(prose, SEN, run(")."))

    out = replace_keeping_links(p, "Sen 1999", "see Sen 1999")

    new_run = out[out.index("A claim (</w:t></w:r>") + 21:out.index(SEN)]
    assert new_run == ('<w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
                       '<w:t xml:space="preserve">see </w:t></w:r>')


# ------------------------------------------------------------ refusals


@pytest.mark.parametrize("old,why", [
    ("not in it", "not in paragraph"),
    ("a", "occurs twice"),
])
def test_old_must_occur_EXACTLY_once(old, why):
    p = para(run("a claim, a claim ("), SEN, run(")."))

    with pytest.raises(AnchorError, match=why):
        replace_keeping_links(p, old, "x")


@pytest.mark.parametrize("old", ["1999), and more", "(Sen 19"])
def test_a_label_STRADDLING_an_edge_of_old_is_refused(old):
    """Half a label inside `old` cannot be kept whole by editing around
    it — the replacement would have to carry half a label."""
    p = para(run("A claim ("), SEN, run("), and more."))

    with pytest.raises(AnchorError, match="straddles"):
        replace_keeping_links(p, old, "anything")


def test_a_replacement_that_DROPS_a_label_is_refused():
    p = para(run("A claim ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="drops the link label 'Sen 1999'"):
        replace_keeping_links(p, "claim (Sen 1999).", "claim.")


def test_a_replacement_that_REORDERS_the_labels_is_refused():
    first = link_element("Table3", "Table 3")
    second = link_element("Table4", "Table 4")
    p = para(run("See "), first, run(" and "), second, run("."))

    with pytest.raises(AnchorError, match="order"):
        replace_keeping_links(p, "Table 3 and Table 4",
                              "Table 4 and Table 3")


def test_a_label_the_replacement_says_MORE_often_than_old_is_ambiguous():
    """`new` mentions "Sen 1999" twice where `old` did once. Which of the
    two is the link is not something the text can say, so the helper
    does not guess."""
    p = para(run("A claim ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="ambiguous"):
        replace_keeping_links(p, "claim (Sen 1999).",
                              "claim, after Sen 1999 (Sen 1999).")


def test_a_NOTE_marker_inside_a_rewritten_piece_is_refused_like_replace():
    p = para(run("A claim"), FN_REF, run(" here ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="crosses footnote 11"):
        replace_keeping_links(p, "claim here (Sen 1999)",
                              "point made (Sen 1999)")

    out = replace_keeping_links(p, "claim here (Sen 1999)",
                                "point made (Sen 1999)", allow_notes=True)
    assert visible_text(out) == "A point made (Sen 1999)."


def test_a_NOTE_marker_where_new_words_would_go_is_refused():
    """The piece after the link is empty and a marker sits exactly
    there: "Sen 1999¹ and others" and "Sen 1999 and others¹" are both
    readings of the same `new`."""
    p = para(run("A claim ("), SEN, FN_REF, run(")."))

    with pytest.raises(AnchorError, match="footnote 11"):
        replace_keeping_links(p, "Sen 1999", "Sen 1999 and others")

    out = replace_keeping_links(p, "Sen 1999", "Sen 1999 and others",
                                allow_notes=True)
    assert visible_text(out) == "A claim (Sen 1999 and others)."


def test_an_EQUATION_between_two_labels_is_refused():
    """The runs' text puts the two labels side by side; the page puts an
    equation between them, and new words have no one place to go."""
    first = link_element("Table3", "Table 3")
    second = link_element("Table4", "Table 4")
    p = para(run("See "), first, OMATH, second, run("."))

    with pytest.raises(AnchorError, match="equation"):
        replace_keeping_links(p, "Table 3Table 4", "Table 3, Table 4")


def test_words_after_a_label_an_EQUATION_follows_go_BETWEEN_the_two():
    """A label with an inline equation straight after it: the reader's
    offset has no run starting at it. `insert_in_para` raised a bare
    ValueError there until 2026-09-17; the words now go between the
    link and the maths, outside both."""
    table = link_element("Table3", "Table 3")
    p = para(run("see "), table, OMATH, run(" below."))

    out = replace_keeping_links(p, "Table 3", "Table 3 with ")

    assert visible_text(out) == "see Table 3 with x below."
    assert table in out
    assert out.index(table) < out.index("with ") < out.index("<m:oMath>")


def test_the_guard_flags_are_KEYWORD_only():
    p = para(run("A claim."))
    with pytest.raises(TypeError):
        replace_keeping_links(p, "claim", "point", True)  # type: ignore[call-arg]


# ----------------------------------------------- the ordinary cases


def test_a_span_crossing_NO_label_is_exactly_replace_in_para():
    """A link elsewhere in the paragraph is not in the way, and the
    answer is byte for byte the one `replace_in_para` gives."""
    p = para(run("The share "), run("rose sharply"), run(" in ("), SEN,
             run(")."))

    assert (replace_keeping_links(p, "share rose sharply", "share fell")
            == replace_in_para(p, "share rose sharply", "share fell"))


def test_an_unchanged_replacement_returns_the_paragraph_untouched():
    p = para(run("A claim ("), SEN, run(")."))

    assert replace_keeping_links(p, "claim (Sen 1999).",
                                 "claim (Sen 1999).") == p


def test_normalize_matches_through_Word_s_glyphs_and_writes_new_verbatim():
    p = para(run("The workers’ view ("), SEN, run(")."))

    out = replace_keeping_links(p, "workers' view (Sen 1999)",
                                "workers’ own view (Sen 1999)",
                                normalize=True)

    assert visible_text(out) == "The workers’ own view (Sen 1999)."
    assert SEN in out


# ------------------------ three defects found writing the helper above
#
# All three in `edit` itself, measured 2026-09-17 while building
# `replace_keeping_links` on top of `replace_in_para` and
# `insert_in_para`, and fixed where they live.


REF_TABLE3 = link_field("", "Table 3", instr="REF _Ref1 \\h", styled=False)


def test_replace_in_para_REFUSES_to_write_through_an_UNSTYLED_cross_ref():
    """Word's Insert > Cross-reference writes `REF _Ref… \\h` with a
    result run that states no style, and `replace_in_para` asked only
    about the Hyperlink style and the `w:hyperlink` element. Measured:

        replace_in_para(see [REF: Table 3] for detail,
                        "see Table 3 for", "consult Table 4 for")
        -> no refusal; the field's result run EMPTIED, "Table 4" in the
           plain run before it

    The page read correctly until the next field update, when Word
    writes "Table 3" back into the empty result beside the new words.
    It is a label for the same reason a hyperlink's is."""
    p = para(run("see "), REF_TABLE3, run(" for detail"))

    with pytest.raises(AnchorError, match="field"):
        replace_in_para(p, "see Table 3 for", "consult Table 4 for")
    with pytest.raises(AnchorError, match="field"):
        replace_in_para(p, "Table 3 for", "Table 4 for")


def test_a_match_WHOLLY_inside_a_field_result_needs_the_same_opt_in():
    """Inside the label, as for a hyperlink: `allow_hyperlink=True` is the
    deliberate retitle, and the default refuses."""
    p = para(run("see "), REF_TABLE3, run(" for detail"))

    with pytest.raises(AnchorError, match="field"):
        replace_in_para(p, "Table 3", "Table 4")

    out = replace_in_para(p, "Table 3", "Table 4", allow_hyperlink=True)
    assert visible_text(out) == "see Table 4 for detail"
    assert "REF _Ref1" in out


def test_a_match_beside_a_field_result_is_still_an_ordinary_replace():
    p = para(run("see "), REF_TABLE3, run(" for detail"))

    out = replace_in_para(p, "for detail", "for the detail")

    assert visible_text(out) == "see Table 3 for the detail"
    assert REF_TABLE3 in out


def test_replace_in_para_REFUSES_a_match_that_crosses_an_inline_EQUATION():
    """The anchor is matched in the runs' text, where an equation is not,
    so "where  is" matched across the maths. Measured:

        replace_in_para(where [x] is the rate., "where  is", "here, is")
        -> 'here, isx the rate.'

    The replacement went into the run before the equation and the words
    after it were emptied: the equation moved to the end of the new
    text, and no gate reads maths order in prose."""
    p = para(run("where "), OMATH, run(" is the rate."))

    with pytest.raises(AnchorError, match="equation"):
        replace_in_para(p, "where  is", "here, is")


@pytest.mark.parametrize("old,new,want", [
    ("where ", "here ", "here x is the rate."),
    (" is the", " was the", "where x was the rate."),
])
def test_a_match_that_only_TOUCHES_the_equation_is_not_refused(old, new, want):
    p = para(run("where "), OMATH, run(" is the rate."))

    assert visible_text(replace_in_para(p, old, new)) == want


def test_a_piece_of_replace_keeping_links_that_crosses_maths_is_refused():
    """The pieces are written by the same `_rewrite_span`, so the
    equation guard reaches them too."""
    p = para(run("where "), OMATH, run(" is ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="equation"):
        replace_keeping_links(p, "where  is (Sen 1999)",
                              "here, is (Sen 1999)")


def test_insert_in_para_goes_BEFORE_an_inline_equation_at_its_offset():
    """Measured: `insert_in_para(where [x] is it., 6, "now ")` raised
    `ValueError: max() iterable argument is empty` — no run STARTS at
    the offset where an equation does. The words go in as a run right
    before the `m:oMath`."""
    p = para(run("where "), OMATH, run(" is it."))

    out = edit.insert_in_para(p, 6, "now ")

    assert visible_text(out) == "where now x is it."
    assert out.index("now ") < out.index("<m:oMath>")
    assert "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>" in out


def test_insert_before_an_equation_goes_AFTER_a_marker_that_ends_there():
    """"At offset N" means after everything that ended there — the rule
    `_between_runs` states. A note marker is a zero-width run AT the
    offset, and the maths after it is where the words go."""
    p = para(run("where"), FN_REF, OMATH, run(" is it."))

    out = edit.insert_in_para(p, 5, " now ")

    assert visible_text(out) == "where now x is it."
    assert (out.index("footnoteReference") < out.index(" now ")
            < out.index("<m:oMath>"))


def test_insert_before_a_DISPLAY_equation_lands_outside_the_oMathPara():
    """`m:oMathPara` holds its `m:oMath`, and both begin at the same
    offset: a run inside the display block is not a place Word accepts."""
    display = f"<m:oMathPara>{OMATH}</m:oMathPara>"
    p = para(display, run(" defines x."))

    out = edit.insert_in_para(p, 0, "Here, ")

    assert visible_text(out) == "Here, x defines x."
    assert out.index("Here, ") < out.index("<m:oMathPara>")


def test_an_offset_INSIDE_an_equation_is_refused_in_the_package_s_words():
    p = para(run("where "), "<m:oMath><m:r><m:t>xy</m:t></m:r></m:oMath>",
             run(" is it."))

    with pytest.raises(AnchorError, match="inside an equation"):
        edit.insert_in_para(p, 7, "now ")


# ------------------------------------------------------------ rstrip_para


def test_a_trailing_WHITESPACE_run_is_removed():
    p = para(run("A claim."), run(" ", preserve=True))

    out = rstrip_para(p)

    assert out == para(run("A claim."))


def test_the_last_text_run_s_trailing_blanks_are_trimmed():
    p = para(run("A claim.  \t", preserve=True))

    out = rstrip_para(p)

    assert visible_text(out) == "A claim."
    assert out.count("<w:r>") == 1


def test_several_blank_and_EMPTY_runs_all_go():
    p = para(run("A claim. ", preserve=True), run("  ", preserve=True),
             "<w:r><w:rPr><w:i/></w:rPr></w:r>", run(" ", preserve=True))

    out = rstrip_para(p)

    assert visible_text(out) == "A claim."
    assert out.count("<w:r>") == 1


def test_a_bookmark_END_after_the_blank_run_stays():
    p = para('<w:bookmarkStart w:id="1" w:name="x"/>', run("A claim."),
             run(" ", preserve=True), '<w:bookmarkEnd w:id="1"/>')

    out = rstrip_para(p)

    assert out == para('<w:bookmarkStart w:id="1" w:name="x"/>',
                       run("A claim."), '<w:bookmarkEnd w:id="1"/>')


@pytest.mark.parametrize("tail", [
    pytest.param(FN_REF, id="note_reference"),
    pytest.param(link_element("Table3", "Table 3 "), id="link_element"),
    pytest.param('<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                 '<w:t xml:space="preserve">Table 3 </w:t></w:r>',
                 id="styled_label"),
    pytest.param(link_field("Table3", "Table 3 "), id="field"),
    pytest.param(OMATH, id="equation"),
    pytest.param('<w:r><w:drawing/></w:r>', id="drawing"),
    pytest.param('<w:r><w:tab/></w:r>', id="tab"),
    pytest.param('<w:ins w:id="5" w:author="A" w:date="2026-09-16T00:00:00Z">'
                 '<w:r><w:t xml:space="preserve"> </w:t></w:r></w:ins>',
                 id="tracked_insertion"),
])
def test_nothing_is_trimmed_PAST_content_that_is_not_plain_prose(tail):
    """The blank before a note marker, a label's own trailing space, a
    field's result, a tracked insertion: each is somebody else's, and a
    trim that reached past one would edit it, move it or de-track it."""
    p = para(run("A claim. ", preserve=True), tail)

    assert rstrip_para(p) == p


def test_a_NO_BREAK_space_is_a_glyph_not_trailing_whitespace():
    p = para(run("A claim. "))

    assert rstrip_para(p) == p


def test_a_paragraph_with_nothing_to_strip_is_returned_unchanged():
    p = para(run("A claim."))

    assert rstrip_para(p) == p
    assert rstrip_para(para()) == para()


# --------------------------------------------------------------- exports


@pytest.mark.parametrize("name", ["run_spans", "field_spans",
                                  "own_properties", "internal_links",
                                  "replace_keeping_links", "rstrip_para"])
def test_the_helpers_a_paper_needs_are_DECLARED(name):
    """DSI imported the four run-walk helpers from `edit`, where they are
    documented, and Pyright answered `reportPrivateImportUsage` on each:
    a name a module hands out without declaring is private to a typed
    consumer. The primitives stay `_xml`'s — declared here, not copied."""
    assert name in edit.__all__
    if hasattr(_xml, name):
        assert getattr(edit, name) is getattr(_xml, name)


# =============================== the survivors of the 2026-09-17 sweep
#
# The code above landed the same day as the sweep, and the sweep found
# where its tests had not been: offsets past CPython's small-int cache,
# a label that is not the only one, a note marker that is not where the
# words go, the face a new run takes when the nearest prose is not the
# run beside it, and an equation that is not the paragraph's only one.

#: Long enough that every offset after it is a fresh int object: `is`
#: and `==` agree on 0..256 and nowhere else. It holds none of the
#: anchors the tests below look for.
PAST_THE_CACHE = ("Discipline practices vary widely across the region; "
                  "the gradient by education is steeper in the countries "
                  "that reformed their family codes earliest, which the "
                  "next table sets out in full for each of the "
                  "twenty-eight countries in the sample, alongside the "
                  "standard errors of every estimate reported. ")


def sized(text: str, size: int) -> str:
    """A prose run with a direct face, as manuscripts carry on every run."""
    return (f'<w:r><w:rPr><w:sz w:val="{size}"/></w:rPr>'
            f'<w:t xml:space="preserve">{text}</w:t></w:r>')


# ------------------------------------------ replace_keeping_links, again


def test_normalize_is_OFF_unless_asked_for():
    """A straight apostrophe does not find a curly one by default: the
    flag is the caller's to set, as it is on `replace_in_para`."""
    p = para(run("The workers’ view ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="not in paragraph"):
        replace_keeping_links(p, "workers' view (Sen 1999)",
                              "workers' own view (Sen 1999)")


@pytest.mark.parametrize("old,edge", [
    pytest.param("1999), and more", "start", id="label_starts_before"),
    pytest.param("(Sen 19", "end", id="label_ends_after"),
    pytest.param("Sen 19", "end", id="label_starts_WITH_old"),
])
def test_the_straddle_refusal_names_the_EDGE_it_crosses(old, edge):
    """Which edge to widen is the whole of the advice. The third case
    starts `old` exactly on the label's first character: it straddles
    the END, and an `<=` in place of `<` calls it the start."""
    p = para(run("A claim ("), SEN, run("), and more."))

    with pytest.raises(AnchorError, match=f"straddles the {edge} of"):
        replace_keeping_links(p, old, "anything")


def test_a_label_the_replacement_says_LESS_often_than_old_is_ambiguous():
    """The other direction of "more often": `new` drops the prose mention
    of "Sen 1999" and keeps the link. Which of old's two it kept is not
    something the text says, and asked only whether `new` has MORE, the
    call reached for the second of one and fell over."""
    p = para(run("Sen 1999 is cited ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="ambiguous"):
        replace_keeping_links(p, "Sen 1999 is cited (Sen 1999).",
                              "It is cited (Sen 1999).")


def test_label_COUNTS_past_256_are_compared_by_value():
    """301 mentions of the label's text in `old` and in `new` — the counts
    agree, and `len()` hands back a fresh object for each past 256."""
    prose = "ab " * 300
    link = link_element("Ab", "ab")
    p = para(run(prose + "("), link, run(")."))

    out = replace_keeping_links(p, prose + "(ab).", prose + "[ab].")

    assert visible_text(out) == prose + "[ab]."
    assert link in out


def test_labels_that_OVERLAP_in_new_are_refused_as_out_of_order():
    """"ab" then "bc" in `old`; in `new` they share the "b". Neither can
    be kept whole beside the other. Measured with the order test asked
    of the label's END, or with `after` set to the previous START: no
    refusal, three empty pieces, and the paragraph came back UNCHANGED —
    "abbc" — from a call asked for "abc"."""
    p = para(run("x "), link_element("A", "ab"), link_element("B", "bc"),
             run(" y"))

    with pytest.raises(AnchorError, match="order"):
        replace_keeping_links(p, "abbc", "abc")


def test_an_UNCHANGED_piece_is_left_alone_even_across_a_marker():
    """Only the piece after the link changes. The piece before it crosses
    footnote 11 and is the same text in `new` — so it is not rewritten,
    and nothing about the marker is at stake. Rewriting an equal piece
    would put it through the note guard, which refuses."""
    p = para(run("A claim"), FN_REF, run(" here ("), SEN, run(")."))

    out = replace_keeping_links(p, "claim here (Sen 1999).",
                                "claim here (Sen 1999), again.")

    assert visible_text(out) == "A claim here (Sen 1999), again."
    assert (out.index("A claim") < out.index("footnoteReference")
            < out.index(" here ("))


def test_an_EMPTY_link_inside_a_rewritten_piece_is_refused():
    """An empty `w:hyperlink` has no label, so it is no piece boundary;
    it is a zero-width marker inside the piece, and rewriting the piece
    moves it to the end of the new words the way a note marker moves.
    The pieces are written with `allow_hyperlink=False` for exactly
    this."""
    ghost = ('<w:hyperlink w:anchor="Table3"><w:r><w:rPr><w:rStyle '
             'w:val="Hyperlink"/></w:rPr><w:t></w:t></w:r></w:hyperlink>')
    p = para(run("A claim"), ghost, run(" here ("), SEN, run(")."))

    with pytest.raises(AnchorError, match="link"):
        replace_keeping_links(p, "claim here (Sen 1999)",
                              "point made (Sen 1999)")


@pytest.mark.parametrize("new,want", [
    pytest.param("see Sen 1999", "(see Sen 1999).", id="before_the_label"),
    pytest.param("Sen 1999 and others", "(Sen 1999 and others).",
                 id="after_the_label"),
])
def test_an_EMPTY_piece_past_256_characters_still_gets_its_words(new, want):
    """The piece's two ends are one offset reached two ways — `old`'s
    start and the label's, or the label's end in two run walks — and
    past 256 they are equal and not identical. Asked by identity, the
    words before the label were silently dropped and the words after it
    were refused as "between two labels with an equation"."""
    p = para(run(PAST_THE_CACHE + "("), SEN, run(")."))

    out = replace_keeping_links(p, "Sen 1999", new)

    assert visible_text(out) == PAST_THE_CACHE + want
    assert SEN in out


def test_new_words_beside_ONE_of_two_links_go_beside_THAT_one():
    """Words for the empty piece before Table 4 go before Table 4, and
    words after Table 3 go after Table 3 — the OTHER label, with prose
    between, is not a neighbour. `lab.end <= at` made Table 3 the left
    neighbour of the first; `lab.start >= at` made Table 4 the right
    neighbour of the second; both then refused as an equation gap."""
    p = para(run("See "), link_element("Table3", "Table 3"), run(" and "),
             link_element("Table4", "Table 4"), run(" below."))

    out = replace_keeping_links(p, "Table 4", "also Table 4")
    assert visible_text(out) == "See Table 3 and also Table 4 below."

    out = replace_keeping_links(p, "Table 3", "Table 3 (left)")
    assert visible_text(out) == "See Table 3 (left) and Table 4 below."


def test_note_markers_ELSEWHERE_in_the_paragraph_do_not_block_new_words():
    """The marker check asks about the OFFSET the words go to. Footnote 11
    sits before it and footnote 12 after it; neither is in the way."""
    later = FN_REF.replace('w:id="11"', 'w:id="12"')
    p = para(run("A claim"), FN_REF, run(" here ("), SEN, run(") and more"),
             later, run("."))

    out = replace_keeping_links(p, "Sen 1999", "see Sen 1999")

    assert visible_text(out) == "A claim here (see Sen 1999) and more."


def test_a_marker_INSIDE_the_prose_run_before_the_words_is_not_in_the_way():
    """The run before the label holds footnote 11 between "A claim" and
    " here (" — seven characters before the words go in, not at their
    offset. The check is for a marker AT the offset; with `lo == hi` read
    as `lo <= hi`, every text run merely ENDING there was searched for a
    marker anywhere inside it, and this edit was refused."""
    prose = ('<w:r><w:t>A claim</w:t><w:footnoteReference w:id="11"/>'
             '<w:t xml:space="preserve"> here (</w:t></w:r>')
    p = para(prose, SEN, run(")."))

    out = replace_keeping_links(p, "Sen 1999", "see Sen 1999")

    assert visible_text(out) == "A claim here (see Sen 1999)."


def test_a_marker_where_new_words_go_PAST_256_characters_is_refused():
    """The marker's zero width is `start == stop` of ONE run, and its
    place is an offset computed elsewhere: past 256, identity says
    neither, and the words went in with no refusal."""
    p = para(run(PAST_THE_CACHE + "("), SEN, FN_REF, run(")."))

    with pytest.raises(AnchorError, match="footnote 11"):
        replace_keeping_links(p, "Sen 1999", "Sen 1999 and others")


# -------------------------------------------- the face new words take

#: Five runs, each a different answer to "which run's face": prose far
#: back (20), prose right before the link (24), a zero-width page-break
#: mark Word leaves in a run of its own (bold), the link at run index 3
#: (odd), prose right after it (28). Past the cache, so the zero-width
#: mark and the offsets are fresh objects.
FACES = para(sized(PAST_THE_CACHE, 20), sized("claim (", 24),
             '<w:r><w:rPr><w:b/></w:rPr><w:lastRenderedPageBreak/></w:r>',
             link_element("Sen1999", "Sen 1999"), sized(").", 28))


def test_words_BEFORE_a_link_take_the_face_of_the_prose_ending_there():
    """The run ending exactly where the words go is "before them" —
    `<=`, not `<` — and a zero-width mark after it is no prose at all."""
    out = replace_keeping_links(FACES, "Sen 1999", "see Sen 1999")

    assert visible_text(out) == PAST_THE_CACHE + "claim (see Sen 1999)."
    assert sized("see ", 24) + "<w:hyperlink" in out


def test_words_AFTER_a_link_take_the_face_of_the_NEAREST_prose_before():
    """Not the link's own run (it is a label, whatever index it sits at),
    not the prose that STARTS where the words go, not the first prose
    run of the paragraph: the nearest one ending before. A leading space
    in the words needs `xml:space`, as a trailing one does."""
    out = replace_keeping_links(FACES, "Sen 1999", "Sen 1999 and others")

    assert visible_text(out) == (PAST_THE_CACHE
                                 + "claim (Sen 1999 and others).")
    assert "</w:hyperlink>" + sized(" and others", 24) + sized(").", 28) \
        in out


def test_words_before_a_link_that_OPENS_the_paragraph_take_the_next_prose():
    """No prose before the words, so the FIRST prose run after them — the
    one right after the link, not the one after that, and never the link
    itself at run index 0. Words with no edge whitespace get a bare
    `<w:t>`."""
    p = para(link_element("Table3", "Table 3"), sized(") is new.", 24),
             sized(" Here.", 20))

    out = replace_keeping_links(p, "Table 3", "(Table 3")

    assert visible_text(out) == "(Table 3) is new. Here."
    assert ('<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>(</w:t></w:r>'
            "<w:hyperlink") in out


# ------------------------------------------------- insert_in_para, again


#: Two equations; the first starts late enough that searching on from
#: TWICE its offset skips the second.
TWO_EQUATIONS = para(run("where the rate of growth ", preserve=True),
                     "<m:oMath><m:r><m:t>xy</m:t></m:r></m:oMath>",
                     run(" and the level ", preserve=True), OMATH,
                     run(" are set."))


def _settled(call: Callable[[], object], seconds: float = 10.0
             ) -> dict[str, object]:
    """`call()`'s value or exception — and a FAILURE if it never returns.

    A search loop that stops advancing hangs rather than fails, and a
    hang stops a suite (and a mutation replay) instead of reporting.
    The call runs on a daemon thread, so a spinning one dies with the
    process."""
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = call()
        except Exception as exc:          # the caller asserts on it
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"the call did not return in {seconds}s"
    return box


def test_insert_before_the_SECOND_equation_of_a_paragraph():
    """The search walks every equation until one starts at the offset;
    the first one it meets starts EARLIER, which is not a reason to
    stop, and the next search starts just past it."""
    first = TWO_EQUATIONS.index("<m:oMath")
    second = TWO_EQUATIONS.index("<m:oMath", first + 1)
    assert second < 2 * first, "the fixture no longer tests what it says"

    out = edit.insert_in_para(TWO_EQUATIONS, 42, "now ")

    assert visible_text(out) == ("where the rate of growth xy and the level "
                                 "now x are set.")
    assert out.index("now ") < out.index(OMATH)


def test_an_offset_inside_the_FIRST_of_two_equations_is_refused_promptly():
    """Offset 26 is inside "xy". The search passes that equation, meets
    the next one starting LATER, and stops: refused, as for a lone
    equation. Not placed before the second one, and not a loop that
    stays on it forever."""
    got = _settled(lambda: edit.insert_in_para(TWO_EQUATIONS, 26, "now "))

    assert isinstance(got.get("error"), AnchorError), got
    assert "inside an equation" in str(got["error"])


def test_insert_before_an_equation_PAST_256_characters():
    """A zero-width marker at the offset and an equation after it, both
    past the cache: the marker's start and stop, and the equation's
    offset and the caller's, are equal and not identical."""
    lead = PAST_THE_CACHE + "where"
    p = para(run(lead), FN_REF, OMATH, run(" is it."))

    out = edit.insert_in_para(p, len(lead), " now ")

    assert visible_text(out) == lead + " now x is it."
    assert (out.index("footnoteReference") < out.index(" now ")
            < out.index("<m:oMath>"))


def test_a_run_boundary_and_the_END_past_256_characters():
    """The two ordinary offsets — where one run starts, and the end —
    past the cache. Asked by identity, the first was taken for maths
    (or found no run starting there at all) and so was the second."""
    p = para(run(PAST_THE_CACHE), run("tail."))
    n = len(PAST_THE_CACHE)

    assert visible_text(edit.insert_in_para(p, n, "MID ")) \
        == PAST_THE_CACHE + "MID tail."
    assert visible_text(edit.insert_in_para(p, n + 5, " END")) \
        == PAST_THE_CACHE + "tail. END"


def test_the_END_of_a_paragraph_is_after_its_LAST_run():
    """Three runs: with two, "the second run" and "the last run" are the
    same run."""
    out = edit.insert_in_para(para(run("a"), run("b"), run("c")), 3, "X")

    assert visible_text(out) == "abcX"


def test_a_NEGATIVE_offset_is_outside_the_paragraph():
    """-1 is refused as what it is. Let through, it reached the maths
    search and was refused as an offset "inside an equation" in a
    paragraph that has none."""
    with pytest.raises(AnchorError, match="outside the paragraph"):
        edit.insert_in_para(para(run("abc")), -1, "X")


def test_an_offset_inside_a_BOOKMARK_needs_its_flag():
    """Between two runs a bookmark spans, the bookmark would grow over
    the new text — refused unless `allow_bookmark=True` says so."""
    p = para('<w:bookmarkStart w:id="1" w:name="Result"/>', run("abc"),
             run("def"), '<w:bookmarkEnd w:id="1"/>')

    with pytest.raises(AnchorError, match="bookmark"):
        edit.insert_in_para(p, 3, "X")

    out = edit.insert_in_para(p, 3, "X", allow_bookmark=True)
    assert visible_text(out) == "abcXdef"


def test_words_passed_as_a_StrEnum_member_get_a_plain_w_t():
    """`content != content.strip()` decides `xml:space`, and a caller's
    words need not be an exact `str`: a `StrEnum` member is a subclass,
    and `strip()` on one returns a NEW string even when nothing was
    stripped. Compared by identity, such words always got
    `xml:space="preserve"`."""
    class Phrase(StrEnum):
        NOW = "now"

    out = edit.insert_in_para(para(run("ab")), 1, Phrase.NOW)

    assert "<w:r><w:t>now</w:t></w:r>" in out


# ---------------------------------------------- remove_link's label runs


def test_remove_link_on_a_FIELD_keeps_only_the_label_run_unstyled():
    """Begin, instruction, separate and end go; the result run stays, with
    the Hyperlink style and the empty `w:rPr` shell it leaves taken off."""
    p = para(run("See "), link_field("Sen1999", "Sen 1999"), run("."))

    out, label = edit.remove_link(p, "Sen1999")

    assert out == para(run("See "), run("Sen 1999"), run("."))
    assert label == "Sen 1999"


def test_remove_link_drops_an_EMPTY_run_the_label_left_behind():
    """A styled run with no text in it — Word leaves these at a label's
    edge — carries nothing to keep. Kept, it came out as `<w:r></w:r>`."""
    link = ('<w:hyperlink w:anchor="Sen1999" w:history="1"><w:r><w:rPr>'
            '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>Sen 1999</w:t></w:r>'
            '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr></w:r>'
            "</w:hyperlink>")

    out, _ = edit.remove_link(para(run("See "), link, run(".")), "Sen1999")

    assert out == para(run("See "), run("Sen 1999"), run("."))


# ------------------------------------------------------ rstrip_para, again


def test_a_run_with_ATTRIBUTES_is_trimmed_like_a_bare_one():
    """Where the run's body starts is read off its opening tag's `>`. A
    bare `<w:r>` puts that at index 4, and `4 + 1`, `4 ^ 1` and `4 | 1`
    are all 5 — an rsid attribute moves it to an odd index, where they
    are not."""
    tagged = ('<w:r w:rsidR="00AB12CD"><w:t xml:space="preserve">'
              "A claim. </w:t></w:r>")
    assert tagged.index(">") % 2 == 1, "the fixture no longer tests it"

    out = rstrip_para(para(tagged))

    assert out == para('<w:r w:rsidR="00AB12CD"><w:t xml:space="preserve">'
                       "A claim.</w:t></w:r>")
