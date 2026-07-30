"""Each check corresponds to markup Word refuses to open."""
from __future__ import annotations

import pytest
from conftest import NS, dele, ins, make_parts, para, run

from docxkit.body import para as bpara
from docxkit.body import run as brun
from docxkit.lint import lint_parts

lxml_etree = pytest.importorskip("lxml.etree")


def _parts(body: str, **extra: str) -> dict[str, bytes]:
    parts = make_parts(body)
    for name, xml in extra.items():
        parts[f"word/{name}.xml"] = xml.encode("utf-8")
    return parts


def test_clean_document_reports_nothing():
    assert lint_parts(_parts(para(run("ordinary prose")))) == []


def test_bare_w_t_with_edge_whitespace_is_flagged():
    """OOXML trims it, so the space survives in the tool that wrote it but is
    dropped by Word and by CompareDocuments. On the LE paper this looked like
    recurring "Word damage" for seven author rounds and shipped four typos."""
    problems = lint_parts(_parts(para(run(" Only after the citation"))))
    assert any("edge whitespace" in p for p in problems), problems


def test_edge_whitespace_is_fine_when_preserved():
    parts = _parts(para(run(" Only after the citation", preserve=True)))
    assert lint_parts(parts) == []


def test_interior_whitespace_is_not_flagged():
    assert lint_parts(_parts(para(run("two words")))) == []


def test_the_builder_output_passes_the_rule():
    """docxkit.body must not emit markup its own linter rejects."""
    assert lint_parts(_parts(bpara(brun(" leading space")))) == []


def test_run_level_child_directly_in_a_block_container():
    """A w:r inside w:footnote (not wrapped in w:p) makes Word reject the
    part outright."""
    foot = (f'<w:footnotes {NS}><w:footnote w:id="2">'
            f"{run('stray run')}</w:footnote></w:footnotes>")
    problems = lint_parts(_parts(para(run("x")), footnotes=foot))
    assert any("run-level child" in p for p in problems)


def test_empty_revision_that_is_not_a_marker():
    empty_ins = ('<w:p><w:ins w:id="9" w:author="A" w:date="d">'
                 "</w:ins></w:p>")
    body = para(run("a")) + empty_ins
    assert any("empty w:ins" in p for p in lint_parts(_parts(body)))


def test_paragraph_mark_revision_is_a_legitimate_marker():
    """A self-closing w:ins inside w:rPr marks an inserted paragraph mark
    and must not be flagged."""
    body = ('<w:p><w:pPr><w:rPr><w:ins w:id="9" w:author="A" w:date="d"/>'
            "</w:rPr></w:pPr>" + run("tail") + "</w:p>")
    assert lint_parts(_parts(body)) == []


def test_deleted_text_must_be_delText():
    """A w:t inside w:del renders as live text that cannot be rejected."""
    body = ('<w:p><w:del w:id="9" w:author="A" w:date="d">'
            "<w:r><w:t>should have been delText</w:t></w:r>"
            "</w:del></w:p>")
    assert any("should be w:delText" in p for p in lint_parts(_parts(body)))


def test_block_element_inside_a_run_level_revision():
    body = ('<w:p><w:ins w:id="9" w:author="A" w:date="d">'
            + para(run("a whole paragraph")) + "</w:ins></w:p>")
    assert any("block w:p inside run-level" in p
               for p in lint_parts(_parts(body)))


def test_ppr_child_order_violation():
    """CT_PPr fixes the order: jc, spacing, ind and friends precede rPr."""
    body = ("<w:p><w:pPr><w:rPr><w:b/></w:rPr>"
            '<w:jc w:val="center"/></w:pPr>' + run("x") + "</w:p>")
    problems = lint_parts(_parts(body))
    assert any("after w:rPr" in p and "jc" in p for p in problems)


def test_ppr_in_the_right_order_is_accepted():
    body = ('<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:b/></w:rPr>'
            "</w:pPr>" + run("x") + "</w:p>")
    assert lint_parts(_parts(body)) == []


def test_rprchange_must_be_last():
    body = ('<w:p><w:r><w:rPr><w:rPrChange w:id="9" w:author="A" '
            'w:date="d"><w:rPr/></w:rPrChange><w:b/></w:rPr>'
            "<w:t>x</w:t></w:r></w:p>")
    assert any("rPrChange is not the last child" in p
               for p in lint_parts(_parts(body)))


def test_empty_omath_shell():
    """An equation with no text renders as garbage, or vanishes."""
    body = ('<w:p><m:oMath xmlns:m="http://schemas.openxmlformats.org/'
            'officeDocument/2006/math"><m:r><m:t></m:t></m:r></m:oMath>'
            "</w:p>")
    assert any("empty m:oMath shell" in p for p in lint_parts(_parts(body)))


def test_duplicate_revision_ids_across_the_package():
    """Word merges or drops revisions that share an id."""
    body = para(run("a"), ins("x", rid=7)) + para(dele("y", rid=7))
    problems = lint_parts(_parts(body))
    assert any("duplicate revision w:id" in p for p in problems)


def test_unique_revision_ids_are_fine():
    body = para(run("a"), ins("x", rid=7)) + para(dele("y", rid=8))
    assert lint_parts(_parts(body)) == []


def test_malformed_xml_is_reported_not_raised():
    parts = make_parts(para(run("x")))
    parts["word/document.xml"] = b"<w:document><w:body><w:p></w:document>"
    problems = lint_parts(parts)
    assert len(problems) == 1
    assert "not well-formed XML" in problems[0]


def test_several_problems_are_all_reported():
    body = ('<w:p><w:del w:id="9" w:author="A" w:date="d">'
            "<w:r><w:t>bad</w:t></w:r></w:del></w:p>"
            '<w:p><w:pPr><w:rPr/><w:jc w:val="center"/></w:pPr></w:p>')
    problems = lint_parts(_parts(body))
    assert len(problems) >= 2
