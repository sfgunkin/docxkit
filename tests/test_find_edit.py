"""Locating and editing by visible text, across Word's run fragmentation."""
from __future__ import annotations

import pytest
from conftest import document, para, row, run, table

from docxkit import (
    para_slice,
    paragraphs,
    preserve_space,
    rep,
    table_spans,
    text_of,
)
from docxkit.edit import insert_in_para, replace_in_para
from docxkit.errors import AnchorError
from docxkit.find import (
    body_elements,
    edit_para,
    find_para,
    heading_level,
    page_break_before,
    para_text_at,
    table_index_at,
)


def test_text_of_reassembles_fragmented_runs():
    """Word splits a sentence at rsid boundaries; a raw regex would miss it."""
    p = para(run("Figur"), run("e"), run(" 6 shows the gap."))
    assert text_of(p) == "Figure 6 shows the gap."
    assert "Figure 6" not in p          # the trap: not present in the XML


def test_para_slice_requires_exactly_one_match():
    xml = document(para(run("alpha")) + para(run("beta")))
    s, e = para_slice(xml, "alpha")
    assert text_of(xml[s:e]) == "alpha"
    with pytest.raises(AnchorError, match="0 hits"):
        para_slice(xml, "gamma")


def test_para_slice_rejects_ambiguous_anchor():
    xml = document(para(run("the gap")) + para(run("the gap again")))
    with pytest.raises(AnchorError, match="2 hits"):
        para_slice(xml, "the gap")


def test_para_slice_also_disambiguates():
    xml = document(para(run("equation (5) in shares"))
                   + para(run("equation (6) in shares")))
    s, e = para_slice(xml, "in shares", also="(6)")
    assert "(6)" in text_of(xml[s:e])


def test_table_spans_counts_and_expect_guard():
    xml = document(para(run("x")) + table(row("a", "b")) + table(row("c")))
    assert len(table_spans(xml)) == 2
    with pytest.raises(AnchorError, match="expected 3"):
        table_spans(xml, expect=3)


def test_table_index_at_locates_the_right_table():
    xml = document(table(row("first")) + para(run("mid")) + table(row("last")))
    spans = table_spans(xml)
    assert table_index_at(spans, xml.index("first")) == 0
    assert table_index_at(spans, xml.index("last")) == 1
    assert table_index_at(spans, xml.index("mid")) is None


def test_para_text_at_returns_containing_paragraph():
    xml = document(para(run("alpha")) + para(run("beta")))
    assert para_text_at(xml, xml.index("beta")) == "beta"


def test_para_text_at_returns_empty_outside_any_paragraph():
    xml = document(para(run("alpha")))
    assert para_text_at(xml, 5) == ""            # in the document header


def test_find_para_returns_none_when_the_signature_is_absent():
    xml = document(para(run("alpha")) + para(run("beta")))
    assert find_para(xml, "beta") is not None
    assert find_para(xml, "gamma") is None


def test_page_break_before_asserts_its_anchor():
    """The property pass breaks ten captions; a drifted one must fail
    loudly rather than silently leaving a table mid-page."""
    xml = document(para(run("Table 3: Results")))
    assert "<w:pageBreakBefore/>" in page_break_before(xml, "Table 3:")
    with pytest.raises(AnchorError):
        page_break_before(xml, "Table 9:")


def test_page_break_before_keeps_existing_paragraph_properties():
    xml = document(
        '<w:p><w:pPr><w:pStyle w:val="Caption"/>'
        '<w:jc w:val="center"/></w:pPr>' + run("Table 5: Results")
        + "</w:p>")
    out = page_break_before(xml, "Table 5:")
    assert ('<w:pStyle w:val="Caption"/><w:pageBreakBefore/>'
            '<w:jc w:val="center"/>') in out


@pytest.mark.parametrize("style,level", [
    ("Title", 1), ("Subtitle", 2), ("Heading3", 3), ("Heading", 1)])
def test_heading_level_reads_the_named_styles(style, level):
    xml = f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr></w:p>'
    assert heading_level(xml) == level


def test_rep_asserts_the_anchor_count():
    assert rep("a b a", "b", "B") == "a B a"
    with pytest.raises(AnchorError, match="0x"):
        rep("a b", "zzz", "!", tag="T1")
    with pytest.raises(AnchorError, match="2x"):
        rep("a a", "a", "!", tag="T2")


def test_preserve_space_protects_edge_whitespace():
    """A bare <w:t> with an edge space is trimmed by Word on every save."""
    xml = "<w:t> Only</w:t><w:t>solid</w:t>"
    fixed, n = preserve_space(xml)
    assert n == 1
    assert '<w:t xml:space="preserve"> Only</w:t>' in fixed
    assert "<w:t>solid</w:t>" in fixed


def test_preserve_space_ignores_nbsp():
    """Only XML whitespace is trimmed by a conforming reader. Marking a
    non-breaking space would add an attribute to every empty table cell
    Word produces, for no protection."""
    xml = "<w:t> </w:t><w:t> leading</w:t>"
    fixed, n = preserve_space(xml)
    assert n == 0
    assert fixed == xml


def test_preserve_space_is_idempotent():
    once, _ = preserve_space("<w:t> Only</w:t>")
    twice, n = preserve_space(once)
    assert n == 0 and twice == once


def test_preserve_space_sees_through_attributes_and_junk_namespace():
    """<w:t w:space="preserve"> is a wrong-namespace no-op Word ignores —
    one misplaced set() ate ten reference-list spaces on Parental Style.
    The check must look through attributes, honour only a real xml:space,
    and strip the junk attribute so it cannot mask the fragility again."""
    xml = ('<w:t w:space="preserve">tail </w:t>'
           '<w:t xml:space="preserve">kept </w:t>'
           '<w:t w:val="x">solid</w:t>')
    fixed, n = preserve_space(xml)
    assert n == 1
    assert '<w:t xml:space="preserve">tail </w:t>' in fixed
    assert '<w:t xml:space="preserve">kept </w:t>' in fixed
    assert '<w:t w:val="x">solid</w:t>' in fixed


def test_replace_in_para_spans_fragmented_runs():
    p = para(run("The ECA average rose from "), run("0.15"), run(" in 2014."))
    out = replace_in_para(p, "0.15", "0.17")
    assert text_of(out) == "The ECA average rose from 0.17 in 2014."


def test_replace_in_para_preserves_other_runs():
    """Only the matched span changes; neighbouring runs keep their markup."""
    p = para(run("see "), run("Table 3", style="Hyperlink"),
             run(" for detail"))
    out = replace_in_para(p, "for detail", "for details")
    assert 'w:val="Hyperlink"' in out
    assert text_of(out) == "see Table 3 for details"


def test_replace_in_para_refuses_to_bleed_into_a_hyperlink():
    """The bug this guards: the replacement lands in the link run and turns
    the whole sentence into a hyperlink, invisible to any text diff."""
    p = para(run("see "), run("Table 3", style="Hyperlink"), run(" now"))
    with pytest.raises(AnchorError, match="hyperlink"):
        replace_in_para(p, "Table 3", "Table 4")
    # explicit opt-in still works, for editing the label itself
    out = replace_in_para(p, "Table 3", "Table 4", allow_hyperlink=True)
    assert text_of(out) == "see Table 4 now"


# A link is broken two ways by one function, and only the first was
# guarded. Parental Style 2026-08-11: the prose read exactly right and
# the manuscript carried a <w:hyperlink w:anchor="Table5"> with nothing
# in it — the anchor still resolved, so `citations`, `crossrefs` and
# `lint` were all green.

ELEMENT_LINK = ('<w:hyperlink w:anchor="Table5" w:history="1">'
                '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                "<w:t>Table 5</w:t></w:r></w:hyperlink>")
#: the same link in FIELD form, whose label is the run after `separate`
FIELD_LINK = (
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "Table5" '
    "</w:instrText></w:r>"
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    "<w:t>Table 5</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
#: an element-form link whose label run states NO style — the element is
#: then the only thing that says this run is a label
BARE_LINK = ('<w:hyperlink w:anchor="Table5" w:history="1">'
             "<w:r><w:t>Table 5</w:t></w:r></w:hyperlink>")


def _crossing(link: str) -> str:
    return ('<w:p><w:r><w:t xml:space="preserve">the practices of '
            "</w:t></w:r>" + link
            + '<w:r><w:t xml:space="preserve"> as well</w:t></w:r></w:p>')


@pytest.mark.parametrize("link", [ELEMENT_LINK, FIELD_LINK, BARE_LINK])
def test_replace_in_para_refuses_to_cross_a_hyperlink(link):
    p = _crossing(link)
    with pytest.raises(AnchorError, match="spans a hyperlink"):
        replace_in_para(p, "the practices of Table 5 as well",
                        "the harsher practices of Table 5 persist")
    assert text_of(p) == "the practices of Table 5 as well"


# ------------------------------------------------- note references -------

#: Word puts a note's marker in its own run, styled, carrying NO text.
FN_REF = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
          '<w:footnoteReference w:id="11"/></w:r>')


def _noted(ref: str = FN_REF) -> str:
    return ('<w:p><w:r><w:t xml:space="preserve">from South Korea (UN 2024).'
            "</w:t></w:r>" + ref
            + '<w:r><w:t xml:space="preserve"> The left panel of Figure 1'
            "</w:t></w:r></w:p>")


def test_replace_in_para_refuses_to_cross_a_NOTE_reference():
    """The LI7 regression (2026-08-15).

    A `w:footnoteReference` carries no visible text, so the anchor reads
    as contiguous prose. The replacement goes into the run holding the
    start of the match and the tail is emptied, so the MARKER moves to
    the end of the new text — and Word's Compare then re-emitted the
    note as an insertion with no matching deletion, which reject-all
    could not undo.
    """
    p = _noted()
    with pytest.raises(AnchorError, match="crosses footnote 11"):
        replace_in_para(p, "). The left panel of ",
                        "), and Figure 1 shows. The left panel of ")
    assert text_of(p) == \
        "from South Korea (UN 2024). The left panel of Figure 1"


@pytest.mark.parametrize("kind,ident", [("endnote", "3"), ("comment", "7")])
def test_the_guard_covers_endnotes_and_comments_too(kind, ident):
    """All three anchor the same way and move the same way."""
    ref = f'<w:r><w:{kind}Reference w:id="{ident}"/></w:r>'
    with pytest.raises(AnchorError, match=f"crosses {kind} {ident}"):
        replace_in_para(_noted(ref), "). The left panel of ", "). Figure 1 ")


def test_a_match_that_ABUTS_a_marker_is_not_refused():
    """The marker has zero visible width, so "up to it" does not cross
    it. Refusing here would make the guard unusable: anchoring beside a
    marker is the correct way to edit that sentence."""
    out = replace_in_para(_noted(), "from South Korea (UN 2024).",
                          "from Japan (UN 2024).")
    assert text_of(out) == "from Japan (UN 2024). The left panel of Figure 1"
    assert '<w:footnoteReference w:id="11"/>' in out


def test_a_match_after_the_marker_is_not_refused():
    out = replace_in_para(_noted(), " The left panel of Figure 1",
                          " The right panel of Figure 2")
    assert text_of(out) == \
        "from South Korea (UN 2024). The right panel of Figure 2"
    assert '<w:footnoteReference w:id="11"/>' in out


def test_the_note_guard_has_its_own_opt_in():
    out = replace_in_para(_noted(), "). The left panel of ", "). Figure 1 ",
                          allow_notes=True)
    assert '<w:footnoteReference w:id="11"/>' in out


def test_the_opt_in_still_crosses_a_hyperlink():
    """One flag for "I know a link is involved" — the caller that means
    to rewrite the label keeps its escape hatch."""
    out = replace_in_para(_crossing(ELEMENT_LINK),
                          "the practices of Table 5 as well", "gone",
                          allow_hyperlink=True)
    assert text_of(out) == "gone"


def test_a_replacement_beside_a_link_is_untouched_by_the_guard():
    """The guard must not refuse the ordinary edit: same paragraph, same
    link, a span that does not reach it."""
    p = _crossing(ELEMENT_LINK)
    out = replace_in_para(p, "the practices of", "the harsher practices of")
    assert text_of(out) == "the harsher practices of Table 5 as well"
    assert 'w:anchor="Table5"' in out


# The counterpart of the crossing guard, and the same silent wrong
# answer wearing the opposite mask: the opt-in that lets a match TOUCH a
# link was also, silently, permission for the label to ABSORB text.
# Parental Style's Table 4 caption 2026-08-12 — every gate green, two
# thirds of the caption drawn blue and underlined.

def _caption(link: str) -> str:
    return ("<w:p>" + link
            + '<w:r><w:t xml:space="preserve">: The likelihood of using '
            "non-violent discipline</w:t></w:r></w:p>")


CAPTION_LINK = ('<w:hyperlink w:anchor="Table4txt" w:history="1">'
                '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                "<w:t>Table 4</w:t></w:r></w:hyperlink>")
CAPTION_FIELD = (
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "Table4txt" '
    "</w:instrText></w:r>"
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    "<w:t>Table 4</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


@pytest.mark.parametrize("link", [CAPTION_LINK, CAPTION_FIELD])
def test_the_opt_in_does_not_let_a_label_swallow_the_caption(link):
    p = _caption(link)
    old = "Table 4: The likelihood of using non-violent discipline"
    new = "Table 4: The likelihood of using coercive discipline"
    with pytest.raises(AnchorError, match="swallow"):
        replace_in_para(p, old, new, allow_hyperlink=True)
    assert text_of(p) == old               # nothing written


def test_a_deliberate_retitle_says_so():
    """The two questions are separable, so the caller that really means
    to grow the label has its own way to say it."""
    p = _caption(CAPTION_LINK)
    out = replace_in_para(p, "Table 4: The likelihood of using non-violent "
                          "discipline", "Table 4: Discipline",
                          allow_hyperlink=True, grow_link_label=True)
    assert text_of(out) == "Table 4: Discipline"


def test_editing_a_label_within_its_own_extent_is_untouched():
    """The refusal is about the label GROWING, not about editing it: a
    span that ends inside the label is the ordinary retitle."""
    p = _caption(CAPTION_LINK)
    out = replace_in_para(p, "Table 4", "Table 5", allow_hyperlink=True)
    assert text_of(out).startswith("Table 5: The likelihood")
    assert "<w:t>Table 5</w:t>" in out      # still the label, nothing more


def test_a_fragmented_label_is_one_label():
    """Word splits a label across runs as freely as it splits prose, so
    the extent is the whole hyperlink element and not one run."""
    p = ('<w:p><w:hyperlink w:anchor="Table4txt">'
         "<w:r><w:t>Table</w:t></w:r>"
         '<w:r><w:t xml:space="preserve"> 4</w:t></w:r></w:hyperlink>'
         '<w:r><w:t xml:space="preserve"> and after</w:t></w:r></w:p>')
    # ends inside the label: allowed
    out = replace_in_para(p, "Table 4", "Table 6", allow_hyperlink=True)
    assert text_of(out) == "Table 6 and after"
    # runs past it: refused
    with pytest.raises(AnchorError, match="swallow"):
        replace_in_para(p, "Table 4 and after", "Table 6 and later",
                        allow_hyperlink=True)


def test_replace_in_para_rejects_missing_or_ambiguous():
    p = para(run("alpha beta alpha"))
    with pytest.raises(AnchorError, match="not in paragraph"):
        replace_in_para(p, "gamma", "x")
    with pytest.raises(AnchorError, match="twice"):
        replace_in_para(p, "alpha", "x")


def test_replace_in_para_escapes_markup():
    p = para(run("plain"))
    out = replace_in_para(p, "plain", "a < b & c")
    assert "&lt;" in out and "&amp;" in out
    assert text_of(out) == "a < b & c"


def test_paragraphs_returns_offsets():
    xml = document(para(run("one")) + para(run("two")))
    ms = paragraphs(xml)
    assert [text_of(m.group(0)) for m in ms] == ["one", "two"]
    assert ms[0].start() < ms[1].start()


# ----------------------------------------------------------- italicize ---

def test_italicize_splits_the_run_at_the_span():
    """Only the title takes <w:i/>; the visible text never changes."""
    from docxkit.edit import italicize
    p = para(run("Altman, D. (2006). Cost of dichotomising. "
                 "British Medical Journal, 332:1080."))
    out = italicize(p, "British Medical Journal")
    assert text_of(out) == text_of(p)
    assert out.count("<w:i/>") == 1
    import re
    ital = next(r for r in re.finditer(r"<w:r>.*?</w:r>", out)
                if "<w:i/>" in r.group(0))
    assert "British Medical Journal" in ital.group(0)
    assert "Altman" not in ital.group(0)
    assert "332:1080" not in ital.group(0)


def test_italicize_spans_fragmented_runs():
    from docxkit.edit import italicize
    p = para(run("See the "), run("British Medical"), run(" Journal here."))
    out = italicize(p, "British Medical Journal")
    assert text_of(out) == "See the British Medical Journal here."
    assert out.count("<w:i/>") == 2      # both covered runs, split edges
    assert "here." in out


def test_italicize_is_idempotent_on_an_italic_run():
    from docxkit.edit import italicize
    p = ('<w:p><w:r><w:rPr><w:i/></w:rPr>'
         "<w:t>Journal of Things</w:t></w:r></w:p>")
    assert italicize(p, "Journal of Things").count("<w:i/>") == 1


def test_italicize_respects_run_property_order():
    """<w:i/> must follow rStyle/rFonts/b per the schema sequence."""
    from docxkit.edit import italicize
    p = ('<w:p><w:r><w:rPr><w:rStyle w:val="X"/><w:b/></w:rPr>'
         "<w:t>Title</w:t></w:r></w:p>")
    out = italicize(p, "Title")
    assert '<w:rStyle w:val="X"/><w:b/><w:i/>' in out


def test_italicize_asserts_its_anchor():
    from docxkit.edit import italicize
    with pytest.raises(AnchorError):
        italicize(para(run("no such title")), "Journal")


# -------------------------------------------------- sub / superscript ---

def test_subscript_lowers_only_the_span():
    """An author typing "Ct" for a Cₜ that is real math elsewhere in the
    sentence: the t drops, the C does not, the text is unchanged."""
    from docxkit.edit import subscript
    p = para(run("where Ct denotes parental consumption at period t."))
    import re
    out = subscript(p, "t", within="Ct")
    assert text_of(out) == text_of(p)
    lowered = [r.group(0) for r in re.finditer(r"<w:r>.*?</w:r>", out)
               if "subscript" in r.group(0)]
    assert [text_of(r) for r in lowered] == ["t"]


def test_a_single_letter_needs_a_scope():
    """Without `within` the ambiguous anchor must fail, not guess."""
    from docxkit.edit import subscript
    p = para(run("where Ct denotes parental consumption at period t."))
    with pytest.raises(AnchorError, match="occurs twice"):
        subscript(p, "t")


def test_within_asserts_its_own_anchor():
    from docxkit.edit import subscript
    p = para(run("Ct and Lt and Ct again."))
    with pytest.raises(AnchorError, match=r"within=.*occurs twice"):
        subscript(p, "t", within="Ct")
    with pytest.raises(AnchorError, match=r"within=.*not in paragraph"):
        subscript(p, "t", within="Zt")
    with pytest.raises(AnchorError, match=r"not in within="):
        subscript(p, "q", within="Lt")


def test_vert_align_sorts_before_lang_in_the_rpr():
    """vertAlign comes after sz/szCs and before rtl/lang in EG_RPrBase;
    Word rejects the file outright if run properties are out of order."""
    from docxkit.edit import superscript
    p = ('<w:p><w:r><w:rPr><w:sz w:val="20"/><w:lang w:val="en-US"/></w:rPr>'
         "<w:t>abc</w:t></w:r></w:p>")
    out = superscript(p, "abc")
    assert ('<w:sz w:val="20"/><w:vertAlign w:val="superscript"/>'
            '<w:lang w:val="en-US"/>') in out


def test_vert_align_with_no_rpr_and_no_lang():
    from docxkit.edit import subscript
    assert '<w:rPr><w:vertAlign w:val="subscript"/></w:rPr>' in \
        subscript(para(run("xy")), "y")
    p = '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>xy</w:t></w:r></w:p>'
    assert '<w:b/><w:vertAlign w:val="subscript"/></w:rPr>' in \
        subscript(p, "y")


def test_vert_align_replaces_rather_than_stacks():
    from docxkit.edit import subscript, superscript
    out = subscript(superscript(para(run("xy")), "y"), "y")
    assert out.count("<w:vertAlign") == 1
    assert "superscript" not in out


def test_para_slice_starts_at_the_paragraph_it_was_asked_for():
    """The span is what a caller splices, so a start that includes the
    EMPTY paragraph above deletes the author's blank line. `<w:p/>` was
    read as an open tag and the walk ran on to the next close."""
    xml = document('<w:p w14:paraId="4BD89DAE"/>'
                   + para(run("The paragraph the caller wants.")))
    s, e = para_slice(xml, "the caller wants")
    assert xml[s:].startswith("<w:p w14:paraId=\"11111111\"") or \
        xml[s:].startswith("<w:p>"), xml[s:s + 40]
    assert "4BD89DAE" not in xml[s:e], "the empty paragraph rode along"
    # and splicing the span keeps the blank line
    rebuilt = xml[:s] + para(run("REPLACED")) + xml[e:]
    assert "4BD89DAE" in rebuilt


# ------------------- the two readings, named --------------------------
#
# `visible_text` is what a reader (and `docxkit text`, and `para_slice`)
# sees: w:t AND m:t. `editable_text` is what a run walk can address: the
# w:r runs alone, and an equation's text is in an m:r inside a sibling
# m:oMath. Both are right for what they do; the package has always had
# both and used to say so nowhere.

MATH_PARA = ('<w:p><w:r><w:t xml:space="preserve">where </w:t></w:r>'
             "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"
             '<w:r><w:t xml:space="preserve"> denotes it.</w:t></w:r></w:p>')


def test_the_two_readings_differ_exactly_over_the_maths():
    from docxkit._xml import editable_text, visible_text
    assert visible_text(MATH_PARA) == "where x denotes it."
    assert editable_text(MATH_PARA) == "where  denotes it."


def test_the_maths_is_the_ONLY_thing_they_differ_over():
    """Both unescape, because `editable_text` is built from
    `visible_text` per run rather than from a raw `w:t` walk. A third
    reading is what `probe` used to have, and it disagreed with both
    over entities as well — pinned here so the narrow one is not
    "simplified" back into a raw walk."""
    from docxkit._xml import editable_text, visible_text
    p = para(run("R&amp;D spending"))
    assert visible_text(p) == editable_text(p) == "R&D spending"


def test_replace_in_para_says_WHY_it_cannot_see_a_phrase_over_maths():
    """The confusing case: `docxkit text` shows the phrase, `para_slice`
    finds it, and the editor refuses. Saying "not in paragraph" and
    stopping is what sends someone hunting for a typo that is not
    there."""
    from docxkit._xml import visible_text
    from docxkit.find import para_slice
    doc = document(MATH_PARA)
    start, end = para_slice(doc, "where x denotes")
    assert visible_text(doc[start:end]) == "where x denotes it."
    with pytest.raises(AnchorError, match="spans an equation"):
        replace_in_para(MATH_PARA, "where x denotes", "REPLACED")


def test_an_ordinary_miss_is_still_an_ordinary_message():
    """The explanation must not attach itself to every failure — a
    phrase that is in NEITHER reading is simply absent."""
    with pytest.raises(AnchorError, match="not in paragraph") as exc:
        replace_in_para(MATH_PARA, "a phrase nobody wrote", "X")
    assert "spans an equation" not in str(exc.value)


def test_the_editor_still_works_either_side_of_the_maths():
    out = replace_in_para(MATH_PARA, "where ", "wherever ")
    assert "wherever " in out and "<m:t>x</m:t>" in out


# --------------------------------------------- inserting between runs ----

#: `Parental_style` 2026-08-13: the paragraph OPENS on its citation's
#: link, so its first `w:t` IS the label and "prepend to the paragraph"
#: means "prepend inside the link" unless something knows better.
_LED_BY_LINK = (
    '<w:p><w:hyperlink w:anchor="ref_B2020"><w:r><w:rPr><w:rStyle '
    'w:val="Hyperlink"/></w:rPr><w:t>Bhalotra and Clarke (2020)</w:t>'
    "</w:r></w:hyperlink>"
    '<w:r><w:t xml:space="preserve"> show that twins are not random.'
    "</w:t></w:r></w:p>")


def _label(para: str) -> str:
    return text_of(para[para.index("<w:hyperlink"):
                        para.index("</w:hyperlink>")])


def test_insert_at_the_front_of_a_LINK_LED_paragraph_stays_outside_it():
    """The measured failure: the connective sentence went INSIDE the
    link and rendered blue and underlined across the whole sentence,
    with every text-layer check passing because the words really are in
    that order."""
    out = insert_in_para(_LED_BY_LINK, 0, "A further consideration. ")

    assert text_of(out) == ("A further consideration. Bhalotra and Clarke "
                            "(2020) show that twins are not random.")
    assert _label(out) == "Bhalotra and Clarke (2020)", "the link GREW"
    assert out.index("A further") < out.index("<w:hyperlink")


def test_text_is_wrapped_in_a_run_and_edge_space_is_preserved():
    out = insert_in_para(_LED_BY_LINK, 0, "See also. ")
    assert '<w:t xml:space="preserve">See also. </w:t>' in out


def test_xml_content_goes_in_verbatim_and_splits_the_run():
    """Splicing an inline equation into prose: the run is REBUILT as two
    through set_run_text, never cut at a hand-found boundary --
    `head.rfind("<w:r")` matches `<w:rPr` and destroyed an equation
    label two screens away."""
    p = ("<w:p><w:r><w:rPr><w:i/></w:rPr>"
         "<w:t>the parameter is small</w:t></w:r></w:p>")
    out = insert_in_para(p, len("the parameter "), "<m:oMath/>")

    assert text_of(out) == "the parameter is small"
    assert "<m:oMath/>" in out
    assert out.count("<w:i/>") == 2, "both halves keep the run's italics"
    assert out.index("<m:oMath/>") > out.index("the parameter ")


def test_inserting_INSIDE_a_label_is_refused():
    with pytest.raises(AnchorError, match="INSIDE a hyperlink"):
        insert_in_para(_LED_BY_LINK, 5, "X")


def test_the_label_split_has_its_own_opt_in():
    out = insert_in_para(_LED_BY_LINK, 5, "X", allow_hyperlink=True)
    assert text_of(out) == ("BhaloXtra and Clarke (2020) show that twins "
                            "are not random.")


def test_inserting_at_the_END_of_a_link_lands_after_the_element():
    out = insert_in_para(_LED_BY_LINK, len("Bhalotra and Clarke (2020)"),
                         " (their Table 2)")
    assert _label(out) == "Bhalotra and Clarke (2020)"
    assert out.index("their Table 2") > out.index("</w:hyperlink>")


def test_a_bookmark_span_is_not_grown_by_an_insert_at_its_edge():
    p = ('<w:p><w:bookmarkStart w:id="7" w:name="B2020txt"/>'
         "<w:r><w:t>Bhalotra (2020)</w:t></w:r>"
         '<w:bookmarkEnd w:id="7"/>'
         '<w:r><w:t xml:space="preserve"> and others</w:t></w:r></w:p>')
    out = insert_in_para(p, 0, "See ")
    assert out.index("See ") < out.index("<w:bookmarkStart")
    assert text_of(out) == "See Bhalotra (2020) and others"


def test_a_fldChar_FIELD_is_never_split():
    """The halves would not be two fields; they would be one broken
    one -- so there is no opt-in for this."""
    p = ("<w:p>"
         '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
         '<w:r><w:instrText xml:space="preserve"> REF Table5 </w:instrText>'
         "</w:r>"
         '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
         "<w:r><w:t>Table 5</w:t></w:r>"
         '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
         "<w:r><w:t> follows</w:t></w:r></w:p>")
    # offset 3 splits the field's own RESULT: "Tab|le 5". The whole
    # field is one element, so there is nowhere outside it that holds
    # that position.
    with pytest.raises(AnchorError, match="fldChar field"):
        insert_in_para(p, 3, "X")
    # ...while prepending to the paragraph lands BEFORE the field, which
    # is where a field-led paragraph's new sentence belongs
    out = insert_in_para(p, 0, "See ")
    assert out.index("See ") < out.index("<w:fldChar")
    assert text_of(out) == "See Table 5 follows"


def test_an_offset_past_the_end_is_an_AnchorError_not_a_silent_append():
    with pytest.raises(AnchorError, match="outside the paragraph"):
        insert_in_para(_LED_BY_LINK, 9999, "x")


def test_inserting_at_the_very_end_appends_after_the_last_run():
    out = insert_in_para(_LED_BY_LINK, len(text_of(_LED_BY_LINK)), " QED.")
    assert text_of(out).endswith("not random. QED.")


def test_an_empty_paragraph_takes_the_content_inside_the_w_p():
    out = insert_in_para("<w:p><w:pPr/></w:p>", 0, "first words")
    assert text_of(out) == "first words"
    assert out.endswith("</w:p>")


# ---- what the first mutation run found unasserted (2026-08-17, 13.4 %) ---

def test_a_page_break_goes_FIRST_in_a_pPr_that_has_no_style():
    """Eleven mutants lived on the offset this branch computes, because
    the styled case was asserted by value and this one only by "the flag
    is in there somewhere". Word reads `w:pPr` as an ordered sequence and
    a flag in the wrong place is dropped on the next save — the caption
    stops breaking, weeks later, with nothing in any diff.
    """
    xml = document('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                   + run("Table 6: Results") + "</w:p>")

    out = page_break_before(xml, "Table 6:")

    assert '<w:pPr><w:pageBreakBefore/><w:jc w:val="center"/></w:pPr>' in out


def test_para_text_at_includes_the_paragraphs_FIRST_offset():
    """`m.start() <= pos`. Half-open the other way, an offset landing on
    the opening `<w:p>` — which is what every span-based caller hands in
    — reads as outside every paragraph."""
    xml = document(para(run("alpha")) + para(run("beta")))
    start = xml.index("<w:p ")

    assert para_text_at(xml, start) == "alpha"


def test_para_text_at_treats_the_END_offset_as_the_NEXT_paragraph():
    """`pos < m.end()`. Paragraphs are adjacent, so one paragraph's end
    IS the next one's start, and an inclusive test would answer with the
    paragraph that just closed."""
    xml = document(para(run("alpha")) + para(run("beta")))
    end_of_first = xml.index("</w:p>") + len("</w:p>")

    assert para_text_at(xml, end_of_first) == "beta"


def test_a_table_SPAN_covers_the_whole_table_and_stops_there():
    """The end offset was only ever used as an opaque number. It has to
    be one past the closing tag: short, and `xml[s:e]` hands a caller a
    truncated table; long, and it swallows the prose after it."""
    xml = document(table(row("a", "b")) + para(run("between"))
                   + table(row("c")) + para(run("after"))
                   + table(row("d", "e", "f")))

    spans = table_spans(xml)

    assert len(spans) == 3
    for s, e in spans:
        assert xml[s:e].startswith("<w:tbl>"), xml[s:e][:40]
        assert xml[s:e].endswith("</w:tbl>"), xml[s:e][-40:]
    assert "between" not in xml[spans[0][0]:spans[0][1]]


def test_expect_fails_on_TOO_MANY_tables_as_well_as_too_few():
    """`!=`, not `<`. The guard exists because a table added upstream
    shifts every later index — which is the too-many direction."""
    xml = document(table(row("a")) + table(row("b")))

    with pytest.raises(AnchorError, match="2 tables, expected 1"):
        table_spans(xml, expect=1)


def test_table_index_at_counts_the_tables_FIRST_offset_as_inside_it():
    """`s <= pos`, and callers pass the span start straight back in."""
    xml = document(table(row("a")) + para(run("between"))
                   + table(row("b")))
    spans = table_spans(xml)

    assert table_index_at(spans, spans[1][0]) == 1
    assert table_index_at(spans, spans[0][1]) is None    # one past the end


@pytest.mark.parametrize("val,level", [
    ("0", 1),        # outlineLvl is 0-based and the levels here are 1-based
    ("2", 3),
    ("8", 6),        # capped: markdown has no deeper heading to render
])
def test_an_outline_level_is_read_ONE_BASED_and_capped(val, level):
    xml = f'<w:p><w:pPr><w:outlineLvl w:val="{val}"/></w:pPr></w:p>'

    assert heading_level(xml) == level


def test_a_GERMAN_heading_style_keeps_its_own_level():
    """`style == "Title"` mutated to `>=` catches every style that sorts
    after it — and Word's German heading id, which the umlaut drops out
    of, does: `berschrift3` would come back as a level 1 Title, so a
    third-level heading renders as the document's title.
    """
    xml = '<w:p><w:pPr><w:pStyle w:val="berschrift3"/></w:pPr></w:p>'

    assert heading_level(xml) == 3


def test_a_heading_DEEPER_than_six_is_capped_not_dropped():
    xml = '<w:p><w:pPr><w:pStyle w:val="Heading9"/></w:pPr></w:p>'

    assert heading_level(xml) == 6


def test_body_elements_are_in_DOCUMENT_order_not_by_kind():
    """`sort(key=el[1])` — the offset. Keyed on the tag instead, every
    paragraph sorts before every table, and a reader walking the result
    (word count, markdown export) renders the whole paper and then the
    exhibits."""
    from docxkit.find import body_elements

    xml = document(table(row("a")) + para(run("after the table")))

    assert [kind for kind, _s, _e in body_elements(xml)] == ["tbl", "p"]


def test_rep_refuses_MORE_anchors_than_it_was_told_to_expect():
    """`!= n`, not `< n`. Too many hits is the dangerous direction: the
    replace succeeds, silently edits a sentence nobody looked at, and
    the build reports the edit it was asked for."""
    with pytest.raises(AnchorError, match=r"found 3x \(need 2\)"):
        rep("a b a b a b", "a", "A", 2, tag="R7")


def test_the_anchor_count_refusal_QUOTES_the_anchor():
    """A build passes dozens of anchors; "found 3x" without saying which
    sends the reader back through all of them."""
    with pytest.raises(AnchorError, match="the missing sentence"):
        rep("some text", "the missing sentence", "x", 1, tag="R7")


def test_rep_counts_NORMALIZED_hits_the_same_way():
    """The glyph-folding path has its own count, and its own guard."""
    xml = "workers’ pay and workers' hours and workers’ rights"

    with pytest.raises(AnchorError, match=r"found 3x \(need 1\)"):
        rep(xml, "workers' ", "staff ", 1, tag="R8", normalize=True)

    out = rep(xml, "workers' ", "staff ", 3, tag="R8", normalize=True)
    assert out.count("staff ") == 3


def test_a_normalized_rep_writes_the_replacement_VERBATIM():
    """Matching through Word's substitutions does not mean writing
    through them: the caller's text lands exactly as typed."""
    out = rep("the workers’ share", "workers' share", "workers’ take",
              normalize=True)

    assert out == "the workers’ take"


def test_preserve_space_strips_the_WRONG_NAMESPACE_attribute():
    """`w:space="preserve"` is a no-op Word ignores — it is `xml:space`
    that protects an edge space. Left in place it reads as protection to
    a person looking at the XML, which is how one went unfixed."""
    xml = '<w:p><w:r><w:t w:space="preserve">no edge space</w:t></w:r></w:p>'

    out, fixed = preserve_space(xml)

    assert 'w:space="preserve"' not in out
    assert "<w:t>no edge space</w:t>" in out
    assert fixed == 1


def test_a_run_that_is_ALREADY_protected_is_left_exactly_as_it_is():
    """The real attribute is there, so nothing is at risk and nothing is
    rewritten — junk beside it included. `preserve_space` runs on every
    build and a pass that rewrites runs it does not have to is a diff
    the next comparison has to explain."""
    xml = ('<w:p><w:r><w:t w:space="preserve" xml:space="preserve"> pad '
           "</w:t></w:r></w:p>")

    out, fixed = preserve_space(xml)

    assert out == xml
    assert fixed == 0


def test_the_junk_attribute_goes_from_a_run_with_NO_edge_space():
    """Stripped on its own account, not as a side effect of adding the
    real one: a `w:space="preserve"` that never did anything reads as
    protection to whoever looks at the XML next."""
    xml = ('<w:p><w:r><w:t w:space="preserve" w:val="x">no edge space'
           "</w:t></w:r></w:p>")

    out, fixed = preserve_space(xml)

    assert '<w:t w:val="x">no edge space</w:t>' in out
    assert fixed == 1


def test_italicize_a_WHOLE_run_leaves_it_one_run():
    """`lo == 0 and hi == len(body)`: the span covers the run exactly,
    so it is styled where it stands. Splitting it into empty pieces
    either side would rewrite the run for nothing — three runs where the
    manuscript had one, in a comparison the author then has to read."""
    from docxkit.edit import italicize

    p = para(run("See the "), run("British Medical Journal"), run(" here."))

    out = italicize(p, "British Medical Journal")

    assert out.count("<w:r>") == 3                  # unchanged
    assert out.count("<w:i/>") == 1
    assert text_of(out) == "See the British Medical Journal here."


def test_italicize_a_WHOLE_run_does_not_REWRITE_its_text():
    """The fast path styles the run where it stands rather than
    rebuilding its `w:t`. Rebuilding is not wrong — it would add
    `xml:space="preserve"` to this one — but it is a change to a run
    nobody edited, and every one of those is a line the next comparison
    has to explain."""
    from docxkit.edit import italicize

    p = para(run("See "), run("Journal of Things "), run("here."))

    out = italicize(p, "Journal of Things ")

    assert "xml:space" not in out
    assert "<w:t>Journal of Things </w:t>" in out


def test_italicize_a_run_PREFIX_splits_it_in_two():
    from docxkit.edit import italicize

    p = para(run("Journal of Things, 12(3)."))

    out = italicize(p, "Journal of Things")

    assert out.count("<w:r>") == 2
    assert out.count("<w:i/>") == 1


def test_italicize_a_run_SUFFIX_splits_it_in_two():
    from docxkit.edit import italicize

    p = para(run("in the Journal of Things"))

    out = italicize(p, "Journal of Things")

    assert out.count("<w:r>") == 2
    assert out.count("<w:i/>") == 1
    assert text_of(out) == "in the Journal of Things"


# The three shapes `find` carried from before CT_PPr order lived in one
# place. Each was fixed in `_table_layout._keep_with_table` hours
# earlier and each was still here, which is the whole argument for
# `set_para_property`.


def test_a_page_break_in_the_tracked_change_SNAPSHOT_is_not_current():
    """`w:pPrChange` holds what a tracked change REPLACED. Read as the
    paragraph's own, the caption looked done and never got the break —
    the table then opens mid-page and the pass reports success."""
    xml = document(
        '<w:p><w:pPr><w:pStyle w:val="Caption"/>'
        '<w:pPrChange w:id="1" w:author="a"><w:pPr><w:pageBreakBefore/>'
        "</w:pPr></w:pPrChange></w:pPr>" + run("Table 3: Results")
        + "</w:p>")

    out = page_break_before(xml, "Table 3:")

    assert '<w:pStyle w:val="Caption"/><w:pageBreakBefore/><w:pPrChange' in out


def test_a_page_break_declared_OFF_is_rewritten_not_doubled():
    """ST_OnOff: `w:val="0"` is the flag present and switched off. Two
    `w:pageBreakBefore` siblings is a schema violation Word repairs by
    choosing one — possibly the one that says no."""
    xml = document('<w:p><w:pPr><w:pageBreakBefore w:val="0"/></w:pPr>'
                   + run("Table 3: Results") + "</w:p>")

    out = page_break_before(xml, "Table 3:")

    assert out.count("<w:pageBreakBefore") == 1
    assert 'w:val="0"' not in out


def test_an_EMPTY_pPr_does_not_get_a_SECOND_one_beside_it():
    """`<w:pPr/>` is real Word output. The old path tested for
    `"<w:pPr>" in para`, missed it, and wrote a second properties
    element after the paragraph's open tag — two `w:pPr` in one
    paragraph, which is not a paragraph."""
    xml = document("<w:p><w:pPr/>" + run("Table 3: Results") + "</w:p>")

    out = page_break_before(xml, "Table 3:")

    assert out.count("<w:pPr") == 1
    assert "<w:pPr><w:pageBreakBefore/></w:pPr>" in out


# --- the run of 2026-08-20: 4.0 % ---------------------------------------


_CURLY = "<w:p><w:r><w:t>It is the author’s own.</w:t></w:r></w:p>"
_PLAIN = "<w:p><w:r><w:t>Another line.</w:t></w:r></w:p>"
_STRAIGHT = "It is the author's own."


def test_para_slice_does_NOT_normalize_unless_it_is_asked_to():
    """`normalize: bool = False` — a default every test passed
    explicitly, so the value in the signature was free.

    It is not a cosmetic default. Folding Word's substitutions makes an
    anchor written with a straight apostrophe match a paragraph Word
    autocorrected — which is what a caller wants when they ASK, and a
    silent widening of every anchor in the package when they do not: two
    paragraphs that differ only in their quotes stop being two
    paragraphs, and `para_slice` edits whichever came first."""
    xml = f"<w:body>{_CURLY}{_PLAIN}</w:body>"

    with pytest.raises(AnchorError, match="0 hits"):
        para_slice(xml, _STRAIGHT)

    assert para_slice(xml, _STRAIGHT, normalize=True)[0] > 0


def test_edit_para_does_NOT_normalize_unless_it_is_asked_to():
    """The same default, one call up — and the one that WRITES. A caller
    who did not ask for folding gets the refusal, not somebody else's
    paragraph rewritten."""
    xml = f"<w:body>{_CURLY}{_PLAIN}</w:body>"

    with pytest.raises(AnchorError, match="0 hits"):
        edit_para(xml, _STRAIGHT, lambda p: p)

    assert edit_para(xml, _STRAIGHT, str.upper, normalize=True) != xml


def test_a_table_at_offset_ZERO_is_found():
    """`pos = 0`: the scan starts at the beginning of what it was given.
    A caller holding a body fragment that OPENS with a table — a table
    and its note, pulled out to be placed — loses it at `pos = 1`, and
    the paragraphs inside it are then reported as body paragraphs
    because nothing knows they are in a table."""
    cell = "<w:p><w:r><w:t>inside</w:t></w:r></w:p>"
    xml = f"<w:tbl><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"

    assert [kind for kind, _, _ in body_elements(xml)] == ["tbl"]


# Argued rather than pinned, from the same run:
#
# * `return hits[0]` written `hits[-1]`, under a guard that has already
#   raised for anything but one hit.
# * `len(out) != expect` written `is not`: both are table counts, and
#   CPython hands out one object per integer below 257.
# * `xml.find("<w:tbl>", pos) != -1` written `> -1` and `is not -1`:
#   `find` answers -1 or an offset, and -1 is one of the cached ones.
# * `out.sort(key=lambda el: el[1])` written `el[2]` — start against
#   end. Every span in that list is disjoint from every other (a
#   paragraph inside a table is not in it, and a nested table rides
#   inside its outer one rather than appearing beside it), and disjoint
#   spans sort the same way by either edge.
