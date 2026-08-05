"""Reading a redline: the two views python-docx cannot produce."""
from __future__ import annotations

import pytest
from conftest import dele, document, ins, para, para_mark_ins, run

from docxkit.revisions import (
    FINAL,
    ORIGINAL,
    accept,
    counts,
    reject,
    revision_text,
    spans,
    text,
)


def _redline():
    return document(
        para(run("The estimate "), dele("recovers"), ins("identifies"),
             run(" the effect."))
        + para(run("Unchanged paragraph.")))


def test_final_view_accepts_the_revisions():
    assert text(_redline(), FINAL) == [
        "The estimate identifies the effect.", "Unchanged paragraph."]


def test_original_view_rejects_them():
    """Deleted text comes back as ordinary runs, so it reads as prose."""
    assert text(_redline(), ORIGINAL) == [
        "The estimate recovers the effect.", "Unchanged paragraph."]


def test_the_two_views_differ_only_at_the_revision():
    final, original = text(_redline(), FINAL), text(_redline(), ORIGINAL)
    assert final[1] == original[1]
    assert final[0] != original[0]


def test_text_rejects_an_unknown_view():
    with pytest.raises(ValueError, match="final"):
        text(_redline(), "sideways")


def test_accept_and_reject_are_defined_on_raw_xml():
    xml = _redline()
    assert "recovers" not in accept(xml)
    assert "identifies" not in reject(xml)


def test_counts_reports_markup_volume():
    """A deliverable whose counts collapsed was opened in Word and
    accepted - the check that caught exactly that on the AFI paper."""
    assert counts(_redline()) == (1, 1)
    assert counts(accept(_redline()))[1] == 0


def test_spans_ignore_property_level_marks():
    xml = document(para(run("a"), ins("x")) + para_mark_ins())
    assert len(spans(xml)) == 1


def test_revision_text_includes_deleted_text():
    xml = _redline()
    got = [revision_text(xml, s) for s in spans(xml)]
    assert got == ["recovers", "identifies"]


def test_nested_revision_is_taken_as_one_span():
    """Word can wrap a deletion inside an insertion (text inserted then
    removed). The outer span owns it; it must not be counted twice."""
    inner = ('<w:ins w:id="1" w:author="A" w:date="d">'
             '<w:del w:id="2" w:author="A" w:date="d">'
             "<w:r><w:delText>gone</w:delText></w:r></w:del></w:ins>")
    xml = document(para(run("keep "), inner))
    assert len(spans(xml)) == 1


# ------------------------------------------------- equation skeletons ------


def _math_doc(*inner: str) -> str:
    return document("<w:p><m:oMath>" + "".join(inner) + "</m:oMath></w:p>")


def _del(rid: int, *inner: str) -> str:
    return (f'<w:del w:id="{rid}" w:author="A" w:date="2026-01-01T00:00:00Z">'
            + "".join(inner) + "</w:del>")


def _mr(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def test_accepting_a_deletion_inside_an_equation_leaves_no_shell():
    """The DSI bug: an emptied fraction survives as <m:f><m:num/><m:den/>,
    which Word renders as a blank fraction box beside the real content.

    Word's own AcceptAllRevisions prunes these, which is exactly why the
    fault only ever appeared on the XML path — and why it took a visual
    render of a shipped document to catch it.
    """
    out = accept(_math_doc(
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>",
        _mr("x")))
    assert "<m:f>" not in out and "<m:num" not in out
    assert "<m:t>x</m:t>" in out


def test_a_partly_emptied_object_keeps_its_surviving_glyphs():
    """Only what is text-free goes. A fraction that still has a numerator
    is a fraction, and pruning its slots would be schema-invalid anyway:
    m:den is REQUIRED by m:f."""
    out = accept(_math_doc(
        f"<m:f><m:num>{_mr('a')}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>"))
    assert "<m:f>" in out and "<m:den" in out
    assert "<m:t>a</m:t>" in out


def test_pruning_leaves_the_glyph_sequence_alone():
    """The invariant that makes the prune safe to run at all."""
    from docxkit._xml import visible_text
    doc = _math_doc(
        _mr("y"),
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>",
        f"<m:d><m:e>{_mr('z')}</m:e></m:d>")
    out = accept(doc)
    assert visible_text(out) == "yz"


def test_a_deliberate_spacer_is_not_an_empty_shell():
    """U+00A0 in an equation is typography. Stripping it as "no text"
    changes the render, so plain truthiness is the test, not .strip()."""
    out = accept(_math_doc(
        f"<m:d><m:e>{_mr(chr(160))}</m:e></m:d>",
        f"<m:f><m:num>{_del(1, _mr('a'))}</m:num>"
        f"<m:den>{_del(2, _mr('b'))}</m:den></m:f>"))
    assert "<m:d>" in out and "<m:f>" not in out


def test_an_equation_no_revision_touched_is_left_exactly_alone():
    """A legitimately empty object elsewhere in the document is the
    author's business — the prune is confined to equations a removal
    actually reached into."""
    doc = document(
        "<w:p><m:oMath><m:f><m:num/><m:den/></m:f></m:oMath></w:p>"
        + para(run("before "), dele("gone"), run(" after")))
    out = accept(doc)
    assert "<m:f><m:num/><m:den/></m:f>" in out
    assert "gone" not in out


# -------------------------------------------- verifying by text, not count ---


def test_changed_paragraphs_reports_only_what_moved():
    before = document(para(run("First.")) + para(run("Second."))
                      + para(run("Third.")))
    after = document(para(run("First.")) + para(run("Second, edited."))
                     + para(run("Third.")))
    from docxkit.revisions import changed_paragraphs
    got = changed_paragraphs(before, after)
    assert [(c.paragraph, c.before, c.after) for c in got] == [
        (1, "Second.", "Second, edited.")]


def test_changed_paragraphs_survives_a_paragraph_merge():
    """Accepting an inserted paragraph mark MERGES two paragraphs. Under
    index pairing every paragraph after the merge reads as changed, which
    is the noise that makes count-based verification useless."""
    from docxkit.revisions import changed_paragraphs
    before = document(para(run("First.")) + para(run("Second."))
                      + para(run("Third.")) + para(run("Fourth.")))
    after = document(para(run("First.")) + para(run("Second.Third."))
                     + para(run("Fourth.")))
    got = changed_paragraphs(before, after)
    assert [c.paragraph for c in got] == [1, 2]
    assert got[-1].after == ""          # the absorbed paragraph
    assert "Fourth." not in [c.before for c in got]


def test_changed_paragraphs_is_empty_when_nothing_changed():
    from docxkit.revisions import changed_paragraphs
    doc = document(para(run("Only.")))
    assert changed_paragraphs(doc, doc) == []
