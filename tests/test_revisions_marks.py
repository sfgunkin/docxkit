"""Paragraph-mark and move semantics.

A naive accept/reject that only drops w:ins and w:del blocks gives wrong
answers on a perfectly good deliverable: on the LE paper it made a
bibliography entry look like it had lost its author, and the paragraph
counts came out 928 against 926. Both were artifacts of these rules.
"""
from __future__ import annotations

from conftest import document, para, run

from docxkit.revisions import FINAL, ORIGINAL, text

MARK_INS = ('<w:pPr><w:rPr><w:ins w:id="80" w:author="A" w:date="d"/>'
            "</w:rPr></w:pPr>")
MARK_DEL = ('<w:pPr><w:rPr><w:del w:id="81" w:author="A" w:date="d"/>'
            "</w:rPr></w:pPr>")


def _split_paragraph() -> str:
    """Compare encodes a SPLIT paragraph as an inserted mark: the author
    broke one paragraph into two, so rejecting must put it back."""
    return document(
        f'<w:p>{MARK_INS}{run("Halliday, T., Mazumder, B., and A. Wong.")}'
        "</w:p>"
        + para(run("(2020). Working paper.")))


def test_rejecting_an_inserted_mark_rejoins_the_paragraph():
    assert text(_split_paragraph(), ORIGINAL) == [
        "Halliday, T., Mazumder, B., and A. Wong.(2020). Working paper."]


def test_accepting_an_inserted_mark_keeps_both_paragraphs():
    assert text(_split_paragraph(), FINAL) == [
        "Halliday, T., Mazumder, B., and A. Wong.",
        "(2020). Working paper."]


def _merged_paragraph() -> str:
    """A DELETED mark is the other direction: the author joined two
    paragraphs, so accepting must join them."""
    return document(
        f'<w:p>{MARK_DEL}{run("First half.")}</w:p>'
        + para(run("Second half.")))


def test_accepting_a_deleted_mark_joins_the_paragraphs():
    assert text(_merged_paragraph(), FINAL) == ["First half.Second half."]


def test_rejecting_a_deleted_mark_keeps_them_apart():
    assert text(_merged_paragraph(), ORIGINAL) == ["First half.",
                                                   "Second half."]


def test_the_mark_flag_is_not_treated_as_content():
    """Removing the rPr flag as if it were a content revision is the bug
    that breaks naive handlers -- the run beside it must survive."""
    xml = document(f'<w:p>{MARK_INS}{run("kept text")}</w:p>')
    assert text(xml, FINAL) == ["kept text"]


def _moved_text() -> str:
    """Compare writes a move as its own pair, invisible to code that only
    knows ins/del."""
    move_from = ('<w:moveFrom w:id="90" w:author="A" w:date="d">'
                 f'{run("relocated sentence.")}</w:moveFrom>')
    move_to = ('<w:moveTo w:id="91" w:author="A" w:date="d">'
               f'{run("relocated sentence.")}</w:moveTo>')
    return document(
        f'<w:p>{run("Intro. ")}{move_from}</w:p>'
         f'<w:p>{run("Later. ")}{move_to}</w:p>')


def test_accept_keeps_the_destination_and_drops_the_source():
    assert text(_moved_text(), FINAL) == ["Intro. ",
                                          "Later. relocated sentence."]


def test_reject_keeps_the_source_and_drops_the_destination():
    assert text(_moved_text(), ORIGINAL) == ["Intro. relocated sentence.",
                                             "Later. "]


def test_move_range_markers_are_removed():
    xml = document(
        '<w:p><w:moveFromRangeStart w:id="1" w:name="m1"/>'
        + run("text") + '<w:moveFromRangeEnd w:id="1"/></w:p>')
    for view in (FINAL, ORIGINAL):
        assert "moveFromRange" not in "".join(text(xml, view))


def test_a_document_with_no_revisions_is_unchanged():
    xml = document(para(run("one")) + para(run("two")))
    assert text(xml, FINAL) == ["one", "two"]
    assert text(xml, ORIGINAL) == ["one", "two"]
