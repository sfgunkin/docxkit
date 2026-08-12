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
from docxkit.edit import replace_in_para
from docxkit.errors import AnchorError
from docxkit.find import (
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
