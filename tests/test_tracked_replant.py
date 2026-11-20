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
    end = (xml.find(f'<w:bookmarkEnd w:id="{m.group(1)}"/>', m.end())
           if m else -1)
    if not m or end < 0:
        return "LOST"
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

    done = tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()})

    # not set over the bold "copy": the neighbour route holds it instead,
    # on the deleted run that touches the insertion, and says so
    acc, rej = _views(parts)
    assert len(done) == 1 and "holds it in the rejected view" in done[0]
    assert _marked(rej) == ") and earnings in Brazil."
    assert _marked(acc) == "Chen and Park 2021"


# --- bookmark tags BETWEEN the pair (Month_of_birth R23, 2026-11-20) ------
# "(Table A7 and Figure 4)." -> "(Figure 4).": Compare put the start of the
# kept label's bookmark between its deletion and its insertion, and only
# its end inside the insertion, next to the removed label's empty marker.

POINT = '<w:bookmarkStart w:id="7" w:name="Gone2020txt"/>'
POINT_END = '<w:bookmarkEnd w:id="7"/>'
#: as R23 has it: the removed label's marker opens, the kept one's starts,
#: the removed one's closes — a straddle around a point bookmark
GAP = POINT + MARK.format(i=12) + POINT_END
#: and, as there, the insertion OPENS with the label, so a start just
#: before it marks the label and nothing else
STRADDLED = (f'<w:ins w:id="11" {REV}>'
             + _field("Chen2021", "Chen and Park 2021")
             + END.format(i=12) + run(").") + "</w:ins>")


def test_a_bookmark_STARTING_between_the_deletion_and_insertion_is_lost_too():
    """The premise: rejecting keeps the start and drops the end with the
    insertion, so the bookmark is gone as surely as in R19's shape."""
    acc, rej = _views(_redline(DELETED, GAP, STRADDLED))

    assert _marked(acc) == "Chen and Park 2021"
    assert _marked(rej) == "LOST"


def test_the_straddling_bookmark_is_set_over_BOTH_copies():
    parts = _redline(DELETED, GAP, STRADDLED)
    acc0, rej0 = _views(parts)

    done = tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert [d.split(":")[0] for d in done] == ["bookmark 'Chen2021txt'"]
    assert _marked(rej) == _marked(acc) == "Chen and Park 2021"
    assert visible_text(acc) == visible_text(acc0)
    assert visible_text(rej) == visible_text(rej0)


def test_the_point_bookmark_in_the_gap_keeps_its_ACCEPTED_place():
    """It goes in front of the pair, which the accepted view cannot tell
    from where it was: just before the inserted text."""
    parts = _redline(DELETED, GAP, STRADDLED)
    acc0, _ = _views(parts)

    tracked.replant_reinserted_bookmarks(parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)

    def before_point(xml: str) -> str:
        return visible_text(xml[:xml.index(POINT)])

    assert before_point(acc) == before_point(acc0) == "Mixed"
    assert POINT in rej and POINT_END in rej


def test_an_END_after_an_insertion_that_comes_first_is_pulled_in_too():
    ins = (f'<w:ins w:id="11" {REV}>' + run("; ", preserve=True)
           + MARK.format(i=12) + _field("Chen2021", "Chen and Park 2021")
           + "</w:ins>")
    parts = _redline(ins, POINT + POINT_END + END.format(i=12), DELETED)

    tracked.replant_reinserted_bookmarks(parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert _marked(rej) == _marked(acc) == "Chen and Park 2021"


def test_a_gap_holding_a_bookmark_that_COVERS_text_is_left_alone():
    """Moving a start whose end is elsewhere would move the range it
    covers, which neither view's text can show — so the pair is not
    rewritten, and the refusal names the cause."""
    reaching = ('<w:bookmarkStart w:id="8" w:name="Wide"/>'
                + MARK.format(i=12))
    parts = _redline(DELETED, reaching, STRADDLED,
                     run(" tail"), '<w:bookmarkEnd w:id="8"/>')
    before = dict(parts)

    assert tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()}) == []
    assert parts == before


# --- the label carried AWAY from its deletion (Month_of_birth R27) --------
# "(Imbens and Lemieux 2008; Lee and Lemieux 2010)" became "(Imbens and
# Lemieux 2008)", and "(Lee and Lemieux 2010)" reappeared sentences later
# inside an insertion whose neighbour is an unrelated deletion. No single
# bookmark can mark the label in both views with kept text between the
# copies, so the insertion's neighbouring deleted run holds it in the
# rejected view (Word: Reject All 'if selection', Accept All the label).

NEIGHBOUR = f'<w:del w:id="13" {REV}>' + _drun("if selection") + "</w:del>"
CARRIED = (f'<w:ins w:id="14" {REV}>'
           + run("which requires control (", preserve=True)
           + MARK.format(i=12) + _field("Chen2021", "Chen and Park 2021")
           + END.format(i=12) + run("). Selection") + "</w:ins>")
KEPT = run(" kept text between ", preserve=True)


def test_a_label_carried_away_LOSES_its_bookmark_on_reject():
    """The premise, R27's shape."""
    acc, rej = _views(_redline(DELETED, KEPT, NEIGHBOUR, CARRIED))

    assert _marked(acc) == "Chen and Park 2021"
    assert _marked(rej) == "LOST"


def test_the_neighbouring_deletion_HOLDS_it_in_the_rejected_view():
    parts = _redline(DELETED, KEPT, NEIGHBOUR, CARRIED)
    acc0, rej0 = _views(parts)

    done = tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert len(done) == 1
    assert "'if selection' holds it in the rejected view" in done[0]
    assert _marked(acc) == "Chen and Park 2021"
    assert _marked(rej) == "if selection"
    assert visible_text(acc) == visible_text(acc0)
    assert visible_text(rej) == visible_text(rej0)


def test_the_neighbour_route_WRITES_no_revision_content():
    parts = _redline(DELETED, KEPT, NEIGHBOUR, CARRIED)
    runs_before = sorted(re.findall(r"<w:r>.*?</w:r>", parts[DOC].decode()))

    tracked.replant_reinserted_bookmarks(parts, {DOC: ORIGINAL.encode()})

    xml = parts[DOC].decode()
    assert sorted(re.findall(r"<w:r>.*?</w:r>", xml)) == runs_before
    ids = re.findall(r'<w:(?:ins|del) w:id="(\d+)"', xml)
    assert len(ids) == len(set(ids))


def test_a_deletion_AFTER_the_insertion_holds_it_the_same_way():
    after = (f'<w:del w:id="13" {REV}>' + _drun("ly") + _drun(" so")
             + "</w:del>")
    parts = _redline(DELETED, KEPT, CARRIED, after)
    acc0, rej0 = _views(parts)

    tracked.replant_reinserted_bookmarks(parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert _marked(acc) == "Chen and Park 2021"
    assert _marked(rej) == "ly"          # the run that touches, no more
    assert visible_text(acc) == visible_text(acc0)
    assert visible_text(rej) == visible_text(rej0)


def test_a_neighbour_with_NO_visible_text_is_left_for_the_refusal():
    """A field character holds no text a view shows: Word drops an empty
    range with what it spanned, so nothing would be held."""
    bare = (f'<w:del w:id="13" {REV}>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:del>')
    parts = _redline(DELETED, KEPT, bare, CARRIED)
    before = dict(parts)

    assert tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()}) == []
    assert parts == before


def test_the_EXACT_route_wins_when_the_copy_is_the_other_neighbour():
    """An unrelated deletion before, the label's own copy after: both
    views keep the label itself, not the neighbour's text."""
    parts = _redline(NEIGHBOUR, INSERTED, DELETED)

    done = tracked.replant_reinserted_bookmarks(
        parts, {DOC: ORIGINAL.encode()})

    acc, rej = _views(parts)
    assert len(done) == 1 and "set over both copies" in done[0]
    assert _marked(rej) == _marked(acc) == "Chen and Park 2021"
