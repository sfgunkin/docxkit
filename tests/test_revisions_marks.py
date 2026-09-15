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
    """Asserted on the XML, because a range marker has NO visible text.

    This read `"moveFromRange" not in "".join(text(xml, view))` and so
    passed whether or not the markers were removed — the mutation sweep
    found it by deleting the loop that removes them and watching nothing
    go red. A marker left behind is a dangling `w:id` in a document that
    no longer has the move it belonged to.
    """
    from docxkit.revisions import accept, reject

    xml = document(
        '<w:p><w:moveFromRangeStart w:id="1" w:name="m1"/>'
        + run("text")
        + '<w:moveFromRangeEnd w:id="1"/>'
        + '<w:moveToRangeStart w:id="2" w:name="m1"/>'
        + '<w:moveToRangeEnd w:id="2"/></w:p>')
    for view in (accept, reject):
        out = view(xml)
        assert "moveFromRange" not in out, view.__name__
        assert "moveToRange" not in out, view.__name__
        assert "text" in out, "the prose between them went too"


def test_a_document_with_no_revisions_is_unchanged():
    xml = document(para(run("one")) + para(run("two")))
    assert text(xml, FINAL) == ["one", "two"]
    assert text(xml, ORIGINAL) == ["one", "two"]


# --- what a MERGE carries with it ---------------------------------------
#
# `_merge_into_next` is what "losing a paragraph mark joins this
# paragraph to the next" means in the markup, and six mutants lived in
# it. Each one is a different way of arriving at a document that opens
# cleanly and is missing something.


def test_a_merge_carries_the_paragraph_TEXT_and_does_not_drop_it():
    """`if nxt is None or nxt.tag != W + "p"` — the guard for "there is
    nothing to merge INTO", where the paragraph is simply removed.

    `is not` in place of `!=` is always true (the tag is a fresh string
    every time it is built), so every merge takes the removal branch:
    the paragraph count comes out right, the mark is gone, and the words
    are gone with it. Counting paragraphs cannot see that; reading them
    can."""
    from docxkit.revisions import reject

    out = reject(_split_paragraph())

    assert out.count("<w:p ") + out.count("<w:p>") == 1
    assert "Halliday" in out and "Working paper" in out


def test_a_BOOKMARK_in_the_merged_paragraph_survives_the_merge():
    """`if child.tag == W + "pPr"` skips the dying paragraph's own
    properties, because the surviving one's win. Read as `<=` it skips
    every child whose tag sorts BEFORE `pPr` — `bookmarkStart` does —
    and a citation anchor is dropped by a rule written about formatting.

    That is the shape of the loss BACKLOG records for a moved block: the
    document opens, the text is all there, and a link points nowhere."""
    from docxkit.revisions import reject

    xml = document(
        f'<w:p>{MARK_INS}<w:bookmarkStart w:id="7" w:name="Moran1950"/>'
        f'{run("A cited sentence.")}<w:bookmarkEnd w:id="7"/></w:p>'
        + para(run("The next paragraph.")))

    out = reject(xml)

    assert out.count("<w:bookmarkStart") == 1, out
    assert out.count("<w:bookmarkEnd") == 1
    assert "A cited sentence." in out


def test_the_merged_children_land_AFTER_the_surviving_properties():
    """`list(nxt).index(nxt_ppr) + 1`, and the mutants are `| 1` and
    `^ 1` — which agree with `+ 1` whenever the properties are the
    FIRST child, because 0 | 1 and 0 ^ 1 are both 1. Word allows range
    markup to precede `w:pPr`, and a redline is full of it: with a
    `bookmarkStart` ahead of the properties the index is 1, where the
    three spellings give 2, 1 and 0 — properties in the middle of the
    text, or before the bookmark that belongs to the paragraph above."""
    from docxkit.revisions import reject

    xml = document(
        f'<w:p>{MARK_INS}{run("First half")}</w:p>'
        f'<w:p><w:bookmarkStart w:id="3" w:name="Anchor"/>'
        f'<w:pPr><w:pStyle w:val="Body"/></w:pPr>'
        f'{run("Second half")}</w:p>')

    out = reject(xml)

    body = out[out.index("<w:bookmarkStart"):]
    assert body.index("<w:pPr>") < body.index("First half"), body
    assert body.index("First half") < body.index("Second half")


# --- the whole sweep of 2026-09-15 ------------------------------------


def test_a_paragraph_whose_mark_goes_is_never_merged_INTO_a_TABLE():
    """`if nxt is None or nxt.tag != W + "p"`. The walk to the next block
    stops at a paragraph or a table, and only a paragraph can take what
    the dying one still holds. Read as `<`, the test is false for the
    table too — its tag sorts above the paragraph's — and read as `is`
    it is false for everything, a tag being a fresh string each time; so
    the leftovers are inserted as the table's first children, ahead of
    its `w:tblPr`, where no run or bookmark can stand.

    The paragraph was INSERTED above the table and carries a bookmark,
    which is what is left once its text goes: an anchor is lifted out of
    a removed revision rather than removed with it."""
    from docxkit.revisions import reject

    tbl = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/></w:tblGrid>'
           f"<w:tr><w:tc><w:tcPr/>{para(run('cell'))}</w:tc></w:tr></w:tbl>")
    inserted = (f'<w:p>{MARK_INS}<w:ins w:id="82" w:author="A" w:date="d">'
                '<w:bookmarkStart w:id="5" w:name="Above"/>'
                f'{run("A new sentence.")}<w:bookmarkEnd w:id="5"/>'
                "</w:ins></w:p>")

    out = reject(document(inserted + tbl))

    assert tbl in out, out
    assert "A new sentence." not in out
