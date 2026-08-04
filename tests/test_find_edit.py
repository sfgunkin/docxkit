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
