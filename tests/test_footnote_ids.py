"""Footnote ids, back into reference order.

A footnote's DISPLAYED number comes from where its reference sits, so
Word does not care what the `w:id` is and no gate here did either:
restore a note the author deleted and it takes the next FREE id while
its reference sits fifteenth, and the paper still reads correctly.

What cares is anything that ADDRESSES a note by id. LI7's acceptance
suite does, re-keyed to baseline numbering, so an id out of reference
order silently shifted what it read and two criteria began failing on
footnotes nobody had touched (2026-08-15). The content was never wrong;
the index into it was.
"""
from __future__ import annotations

import pytest
from conftest import document, note, notes, para, run

from docxkit import renumber
from docxkit.errors import AnchorError


def _ref(nid: int) -> str:
    return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            f'<w:footnoteReference w:id="{nid}"/></w:r>')


def _parts(order: list[int], stored: list[int] | None = None,
           *, reserved: bool = True) -> dict[str, bytes]:
    """A document whose references appear in `order`."""
    body = "".join(para(run(f"sentence {i}"), _ref(nid))
                   for i, nid in enumerate(order, 1))
    items = [note(f"note text {nid}", nid=nid)
             for nid in (stored if stored is not None else sorted(order))]
    if reserved:
        items = [note("separator", nid=0), note("continuation", nid=-1),
                 *items]
    return {"word/document.xml": document(body).encode("utf-8"),
            "word/footnotes.xml": notes("footnotes", *items).encode("utf-8")}


def test_the_audit_names_the_disagreement():
    """The check that would have caught it, and cheap enough for a gate
    ladder."""
    found = renumber.footnote_audit(_parts([1, 2, 19, 3]))
    assert found and "do not follow reference order" in found[0]
    assert "19" in found[0]


def test_a_document_whose_ids_already_follow_order_is_silent():
    assert renumber.footnote_audit(_parts([1, 2, 3, 4])) == []
    assert renumber.footnotes(_parts([1, 2, 3, 4])) == {}


def test_ids_are_renumbered_into_reference_order():
    """The LI7 shape: a restored note took the next FREE id, 19, while
    its reference sits third of four."""
    parts = _parts([1, 2, 19, 3])

    moved = renumber.footnotes(parts)

    assert moved == {19: 3, 3: 4}
    referenced, stored = renumber.footnote_order(parts)
    assert referenced == [1, 2, 3, 4]
    assert stored == referenced, "the notes part still stores them shuffled"
    assert renumber.footnote_audit(parts) == []


def test_the_remap_goes_through_a_PLACEHOLDER():
    """A direct substitution collides — 19 -> 15 while 15 -> 16 shares
    the same id space — and the second pass rewrites what the first had
    already moved."""
    parts = _parts([1, 2, 3, 4, 19, 5])
    renumber.footnotes(parts)

    referenced, stored = renumber.footnote_order(parts)
    assert referenced == [1, 2, 3, 4, 5, 6]
    assert stored == referenced
    body = parts["word/document.xml"].decode("utf-8")
    assert "@" not in body, "a placeholder survived into the document"


def test_the_note_TEXT_follows_its_id():
    """The whole point: what the id addresses must not change."""
    parts = _parts([1, 19, 2])
    renumber.footnotes(parts)

    xml = parts["word/footnotes.xml"].decode("utf-8")
    from docxkit.footnotes import find_all
    by_id = {f.id: f.text for f in find_all(xml)}
    assert by_id["2"] == "note text 19", "id 2 now addresses another note"
    assert by_id["3"] == "note text 2"


def test_words_own_separator_notes_are_left_alone():
    parts = _parts([1, 19, 2])
    renumber.footnotes(parts)

    xml = parts["word/footnotes.xml"].decode("utf-8")
    assert 'w:id="0"' in xml and 'w:id="-1"' in xml
    assert xml.index('w:id="0"') < xml.index('w:id="1"'), \
        "the reserved notes must stay at the head of the part"


def test_a_reference_with_no_note_is_REFUSED():
    """Renumbering would point it somewhere else again, which is worse
    than leaving it dangling where an audit can see it."""
    parts = _parts([1, 2, 7], stored=[1, 2])
    with pytest.raises(AnchorError, match=r"which no note defines"):
        renumber.footnotes(parts)


def test_a_note_nothing_references_is_reported_not_renumbered():
    found = renumber.footnote_audit(_parts([1, 2], stored=[1, 2, 9]))
    assert any("note 9 has no reference" in f for f in found)


def test_a_document_with_no_footnotes_at_all():
    parts = {"word/document.xml": document(para(run("body"))).encode("utf-8")}
    assert renumber.footnote_audit(parts) == []
    assert renumber.footnotes(parts) == {}
