"""`tracked.replant_reinserted_bookmarks` — a kept label Compare re-inserted.

Month_of_birth R19 (2026-11-19, backlog S2): a trim on both sides of a
first-mention label it kept. Compare deleted the whole stretch, label
included, inserted ``"; " + label + ")."`` after it, and left the marker
bookmark only inside the ``w:ins`` — so rejecting the round dropped it.
The pinned shape is Compare's own, cut down: a field-link label in
``fldChar`` runs, the deleted copy in ``delInstrText``/``delText``.
"""
from __future__ import annotations

import re

from conftest import document, run

from docxkit import tracked
from docxkit._xml import visible_text

DOC = "word/document.xml"
REV = 'w:author="Probe" w:date="2026-11-19T00:00:00Z"'


def _field(key: str, label: str, *, deleted: bool = False) -> str:
    instr, txt = ("delInstrText", "delText") if deleted else ("instrText", "t")
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:{instr}>HYPERLINK \\l "{key}" \\h</w:{instr}></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f"<w:r><w:{txt}>{label}</w:{txt}></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _drun(text: str) -> str:
    return f'<w:r><w:delText xml:space="preserve">{text}</w:delText></w:r>'


MARK = '<w:bookmarkStart w:id="{i}" w:name="Chen2021txt"/>'
END = '<w:bookmarkEnd w:id="{i}"/>'

ORIGINAL = document(
    '<w:p>' + run("Mixed. Later entry in China (", preserve=True)
    + MARK.format(i=5) + _field("Chen2021", "Chen and Park 2021")
    + END.format(i=5) + run(") and earnings in Brazil.") + "</w:p>")

DELETED = (f'<w:del w:id="10" {REV}>' + _drun(". Later entry in China (")
           + _field("Chen2021", "Chen and Park 2021", deleted=True)
           + _drun(") and earnings in Brazil.") + "</w:del>")
INSERTED = (f'<w:ins w:id="11" {REV}>' + run("; ", preserve=True)
            + MARK.format(i=12) + _field("Chen2021", "Chen and Park 2021")
            + END.format(i=12) + run(").") + "</w:ins>")


def _redline(*pieces: str) -> dict[str, bytes]:
    return {DOC: document('<w:p>' + run("Mixed") + "".join(pieces)
                          + "</w:p>").encode()}


def _marked(xml: str) -> str:
    """The visible text the Chen2021txt bookmark wraps, or LOST."""
    m = re.search(r'<w:bookmarkStart w:id="(\d+)" w:name="Chen2021txt"/>', xml)
    if not m:
        return "LOST"
    end = xml.index(f'<w:bookmarkEnd w:id="{m.group(1)}"/>', m.end())
    return visible_text(xml[m.end():end])


def _views(parts: dict[str, bytes]) -> tuple[str, str]:
    return (tracked.accepted_view(parts)[DOC].decode(),
            tracked.rejected_view(parts)[DOC].decode())


def test_Compare_s_own_shape_LOSES_the_bookmark_on_reject():
    """The premise, as Word wrote it — what the repair is for."""
    acc, rej = _views(_redline(DELETED, INSERTED))

    assert _marked(acc) == "Chen and Park 2021"
    assert _marked(rej) == "LOST"


def test_the_bookmark_is_set_over_BOTH_copies_and_each_view_keeps_the_label():
    parts = _redline(DELETED, INSERTED)
    acc0, rej0 = _views(parts)

    done = tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert [d.split(":")[0] for d in done] == ["bookmark 'Chen2021txt'"]
    assert _marked(rej) == "Chen and Park 2021"
    assert _marked(acc) == "Chen and Park 2021"
    # and neither view's text moved: the order of an adjacent deletion and
    # insertion is invisible to both
    assert visible_text(acc) == visible_text(acc0)
    assert visible_text(rej) == visible_text(rej0)


def test_no_revision_content_is_WRITTEN_only_Compare_s_runs_regrouped():
    parts = _redline(DELETED, INSERTED)
    runs_before = sorted(re.findall(r"<w:r>.*?</w:r>", parts[DOC].decode()))

    tracked.replant_reinserted_bookmarks(parts, {DOC: ORIGINAL.encode()})

    xml = parts[DOC].decode()
    assert sorted(re.findall(r"<w:r>.*?</w:r>", xml)) == runs_before
    ids = re.findall(r'<w:(?:ins|del) w:id="(\d+)"', xml)
    # del[pre] ins["; "] del[label] ins[label] ins[")."] del[rest], each
    # with an id of its own
    assert len(ids) == len(set(ids)) == 6
    assert xml.count("<w:del ") == 3 and xml.count("<w:ins ") == 3


def test_the_INSERTION_first_order_is_repaired_the_same_way():
    parts = _redline(INSERTED, DELETED)

    tracked.replant_reinserted_bookmarks(parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert _marked(rej) == _marked(acc) == "Chen and Park 2021"


def test_a_label_the_deletion_holds_TWICE_is_left_for_the_refusal():
    twice = DELETED.replace(
        "</w:del>", _field("Chen2021", "Chen and Park 2021", deleted=True)
        + "</w:del>")
    parts = _redline(twice, INSERTED)
    before = dict(parts)

    assert tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()}) == []
    assert parts == before


def test_a_bookmark_the_ORIGINAL_never_had_is_not_touched():
    """New in the clean edit: Compare carries no new bookmark, and that is
    a different refusal, not this repair's."""
    parts = _redline(DELETED, INSERTED)
    before = dict(parts)
    no_mark = ORIGINAL.replace(MARK.format(i=5), "").replace(
        END.format(i=5), "")

    assert tracked.replant_reinserted_bookmarks(
        parts, {DOC: no_mark.encode()}) == []
    assert parts == before


def test_a_label_relocated_AWAY_from_its_deletion_is_left_alone():
    """R17's shape: the deleted copy is not the insertion's neighbour."""
    parts = _redline(DELETED, run(" kept text between "), INSERTED)
    before = dict(parts)

    assert tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()}) == []
    assert parts == before


def test_a_deletion_whose_label_is_FORMATTED_differently_is_not_a_copy():
    bold = DELETED.replace(
        "<w:r><w:delText>Chen and Park 2021",
        "<w:r><w:rPr><w:b/></w:rPr><w:delText>Chen and Park 2021")
    parts = _redline(bold, INSERTED)
    before = dict(parts)

    assert tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()}) == []
    assert parts == before
