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


def test_words_after_a_label_an_EQUATION_follows_are_refused_not_crashed():
    """The one place the reader's offset has no run starting at it: a
    label with an inline equation straight after it. `insert_in_para`
    raises a bare ValueError there ("max() iterable argument is
    empty"), which names nothing the caller did; this says what it is."""
    table = link_element("Table3", "Table 3")
    p = para(run("see "), table, OMATH, run(" below."))

    with pytest.raises(AnchorError, match="equation"):
        replace_keeping_links(p, "Table 3", "Table 3 with")


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
