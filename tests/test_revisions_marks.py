"""Paragraph-mark and move semantics.

A naive accept/reject that only drops w:ins and w:del blocks gives wrong
answers on a perfectly good deliverable: on the LE paper it made a
bibliography entry look like it had lost its author, and the paragraph
counts came out 928 against 926. Both were artifacts of these rules.
"""
from __future__ import annotations

import re
import zipfile

import pytest
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


# --- what the triage of 2026-09-16 found -------------------------------


MARK_MOVE = ('<w:pPr><w:rPr><w:moveTo w:id="83" w:author="A" w:date="d"/>'
             "</w:rPr></w:pPr>")


def test_the_ANCHORS_of_a_paragraph_that_cannot_MERGE_are_kept():
    r"""The test above, with the bookmark counted rather than the table.

    A paragraph whose mark goes and whose next block is a TABLE has
    nothing to merge into, so it is removed outright — and the anchors
    `_lift_anchors` had just moved into it, out of the revision being
    rejected, go with it. Followed by a PARAGRAPH the same document
    keeps the pair (bookmarkStart x1, bookmarkEnd x1), followed by a
    table it keeps neither, and the baseline has one of each. Nothing
    reads a bookmark on the way past, so nothing said anything.

    What those anchors ARE decides whether that is litter, and it was
    measured rather than assumed (2026-09-16): of 301 manuscripts in the
    corpus, 28 carry moves and exactly one carries a bookmark INSIDE a
    move — `Brown2019txt`, in Aging_Well's own redline, with no leading
    underscore, so `_xml.word_minted` reads it as the author's. The
    reference list's entry for it holds `HYPERLINK \l "Brown2019txt"`:
    it is the back half of the paper's bidirectional citation pair, and
    a link that resolves to nothing is what dropping it costs. Word's
    OWN move markers are `w:moveToRangeStart` elements, which this
    module already removes by name.
    """
    from docxkit.revisions import reject

    tbl = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/></w:tblGrid>'
           f"<w:tr><w:tc><w:tcPr/>{para(run('cell'))}</w:tc></w:tr></w:tbl>")
    moved = (f'<w:p>{MARK_MOVE}<w:moveTo w:id="84" w:author="A" w:date="d">'
             '<w:bookmarkStart w:id="9" w:name="Brown2019txt"/>'
             f'{run("As Brown et al. (2019) showed.")}'
             '<w:bookmarkEnd w:id="9"/></w:moveTo></w:p>')
    elsewhere = ('<w:p><w:moveFrom w:id="85" w:author="A" w:date="d">'
                 f'{run("As Brown et al. (2019) showed.")}'
                 "</w:moveFrom></w:p>")

    out = reject(document(moved + tbl + elsewhere))

    assert out.count("<w:bookmarkStart") == 1, out
    assert out.count("<w:bookmarkEnd") == 1
    assert 'w:name="Brown2019txt"' in out
    assert out.index("<w:bookmarkStart") < out.index("<w:tbl>"), out
    assert tbl in out, "the table itself is untouched"


# --- the whole sweep of 2026-09-17 ------------------------------------


def test_a_COMMENT_REFERENCE_is_not_lifted_where_a_paragraph_cannot_MERGE():
    """`t != "commentReference"` in `_BLOCK_ANCHORS`, read as `<=`. Every
    other anchor tag sorts below that one, so `<=` differs from `!=` only
    by letting the reference itself through: the block set becomes
    `_ANCHOR_TAGS`, whole. The test above lifts a BOOKMARK, which both
    readings lift, so it cannot tell them apart.

    A comment can, because it is both kinds at once: its range markers
    are range markup a block may hold, its `w:commentReference` is run
    inner content no block may. The paragraph was inserted above a
    TABLE, so rejecting it removes it rather than merging it, and what
    stands where it stood is the range and nothing else. Under the
    mutant the reference is lifted too, and `w:body` gains an element
    the schema has no place for.
    """
    from docxkit.revisions import reject

    tbl = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="100"/></w:tblGrid>'
           f"<w:tr><w:tc><w:tcPr/>{para(run('cell'))}</w:tc></w:tr></w:tbl>")
    inserted = (f'<w:p>{MARK_INS}<w:ins w:id="82" w:author="A" w:date="d">'
                '<w:commentRangeStart w:id="4"/>'
                f'{run("A new sentence.")}<w:commentRangeEnd w:id="4"/>'
                '<w:r><w:commentReference w:id="4"/></w:r>'
                "</w:ins></w:p>")

    out = reject(document(inserted + tbl))

    lifted = out[out.index("<w:body>"):out.index("<w:tbl>")]
    assert lifted == ('<w:body><w:commentRangeStart w:id="4"/>'
                      '<w:commentRangeEnd w:id="4"/>'), out
    assert "<w:commentReference" not in out
    assert tbl in out, "the table itself is untouched"


# --- what WORD makes of the anchors the fix leaves ---------------------
#
# The fix WRITES `commentRangeStart`/`commentRangeEnd` at block level
# where nothing stood before, and the failure this toolkit has already
# paid for twice is a file Word refuses or silently repairs. The repo
# has the opposite direction Word-verified three times — a reference
# pointing at a definition that is gone is "unreadable content"
# (`comments.py`, DSI) and "the file appears to be corrupted"
# (`hygiene.py`, Health Capacity to Work, bisected) — and none of them
# covers a BALANCED range at block level whose definition is intact.
# So it is measured through Word rather than argued, and kept runnable.


def _commented_shells():
    """A real package for Word to open, carrying a comments part.

    The synthetic fixtures in this file are not ones Word will open —
    "The file appears to be corrupted" — which is why this builds on a
    manuscript, as `test_WORD_reads_two_ADJACENT_tables_as_ONE` does.
    It must already HAVE `word/comments.xml`: adding one means adding
    the content-type override and the relationship with it, and a shell
    assembled wrong would produce the very refusal this test exists to
    rule out.
    """
    from pathlib import Path

    for candidate in Path(r"F:\OneDrive\__Documents").rglob("*.docx"):
        if candidate.name.startswith("~$"):
            continue
        try:
            with zipfile.ZipFile(candidate) as z:
                if "word/comments.xml" in z.namelist():
                    yield candidate
                    return
        except (zipfile.BadZipFile, OSError):
            continue


def _first_comment_id(parts: dict[str, bytes]) -> str | None:
    com = parts.get("word/comments.xml", b"").decode("utf-8", "replace")
    m = re.search(r'<w:comment w:id="(\d+)"', com)
    return m.group(1) if m else None


@pytest.mark.word
def test_WORD_reads_a_LIFTED_comment_range_as_CONTENT_not_damage(tmp_path):
    """Three bodies on one real shell, so a difference is attributable.

    `lifted` is the shape the fix leaves: a balanced range at BLOCK
    level, in order, its definition intact in `comments.xml`, and no
    `commentReference` — because run-inner content has no place at block
    level, so :data:`_BLOCK_ANCHORS` leaves it behind. `orphan` is the
    same document with no range at all, which isolates "a definition
    nothing references" from "a bare range". `anchored` is the control
    that proves this harness can see a comment at all.

    What is being asked: does Word OPEN it without repairing, what is
    `Comments.Count`, and does a save keep the range or drop it. The
    third is the one that says whether Word reads a bare range as
    content or as litter.

    Measured 2026-09-16. All three opened with no repair, the table and
    the prose intact:

        lifted    comments 0; saved back with range 0, reference 0,
                  definitions 0
        orphan    identical, to the number
        anchored  comments 1; range 1, reference 1, definitions 1

    So Word reads a comment as its REFERENCE. With none, the definition
    is not a comment it counts or shows, and it collects both that
    definition and the bare range on the next save. The shape the fix
    leaves is litter to Word rather than content — and litter Word
    clears itself, not damage it refuses or repairs. `lifted` and
    `orphan` agreeing to the number is what makes that attributable:
    the markers the fix writes change nothing Word sees.
    """
    from docxkit import package
    from docxkit.word import WD_FORMAT_DOCX, open_doc, session

    shell = next(_commented_shells(), None)
    if shell is None:
        pytest.skip("no real .docx with a comments part to build on")
    cid = _first_comment_id(package.read_parts(shell))
    if cid is None:
        pytest.skip("the shell's comments part holds no comment")

    tbl = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="4000"/></w:tblGrid>'
           f"<w:tr><w:tc><w:tcPr/>{para(run('cell'))}</w:tc></w:tr></w:tbl>")
    tail = para(run("After the table."))
    bodies = {
        "lifted": (f'<w:commentRangeStart w:id="{cid}"/>'
                   f'<w:commentRangeEnd w:id="{cid}"/>' + tbl + tail),
        "orphan": tbl + tail,
        "anchored": (para(run("Before. "),
                          f'<w:commentRangeStart w:id="{cid}"/>',
                          run("commented text"),
                          f'<w:commentRangeEnd w:id="{cid}"/>',
                          f'<w:r><w:commentReference w:id="{cid}"/></w:r>')
                     + tbl + tail),
    }

    def built(body: str, name: str):
        made = package.read_parts(shell)
        doc = made["word/document.xml"].decode("utf-8")
        at = doc.index("<w:body>") + len("<w:body>")
        stop = doc.rindex("</w:body>")
        sect = re.search(r"<w:sectPr\b.*?</w:sectPr>", doc[at:stop], re.DOTALL)
        made["word/document.xml"] = (
            doc[:at] + body + (sect.group(0) if sect else "")
            + doc[stop:]).encode()
        path = tmp_path / name
        package.write_docx(path, made, order=list(made))
        return path

    seen: dict[str, dict[str, object]] = {}
    with session(deadline=240) as word:
        for label, body in bodies.items():
            with open_doc(word, built(body, f"{label}.docx")) as doc:
                # AS OPENED, before any save: a repair would show here
                opened = {"comments": doc.Comments.Count,
                          "tables": doc.Tables.Count,
                          "text": "After the table." in doc.Range().Text}
                saved = tmp_path / f"{label}-saved.docx"
                doc.SaveAs2(str(saved), FileFormat=WD_FORMAT_DOCX)
            with zipfile.ZipFile(saved) as z:
                back = z.read("word/document.xml").decode("utf-8", "replace")
                com = z.read("word/comments.xml").decode("utf-8", "replace") \
                    if "word/comments.xml" in z.namelist() else ""
            opened["range_after_save"] = back.count("<w:commentRangeStart")
            opened["reference_after_save"] = back.count("<w:commentReference")
            opened["definitions_after_save"] = com.count("<w:comment ")
            seen[label] = opened
    print("\nWord's answers:", *seen.items(), sep="\n  ")

    # Word opened all three and kept the document: no repair, nothing lost
    for label, got in seen.items():
        assert got["tables"] == 1, (label, got)
        assert got["text"] is True, (label, got)
    # the control proves the harness can see a comment when one is anchored
    assert seen["anchored"]["comments"] == 1, seen
    assert seen["anchored"]["range_after_save"] == 1, seen
    # A comment is its REFERENCE: with none, Word counts no comment and
    # drops the definition and the bare range together on the next save.
    assert seen["lifted"]["comments"] == 0, seen
    assert seen["lifted"]["range_after_save"] == 0, seen
    assert seen["lifted"]["definitions_after_save"] == 0, seen
    # and the markers the fix writes change nothing Word sees
    assert seen["lifted"] == seen["orphan"], seen
