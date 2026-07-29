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
