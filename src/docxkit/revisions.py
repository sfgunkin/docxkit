r"""Reading tracked changes, with Word's own accept/reject semantics.

Two things python-docx cannot do at all, because it only walks runs that
are direct children of a paragraph and a tracked insertion is nested
inside ``<w:ins>``: see the text of an insertion, and show either side of
a redline. A "blank" cell in a tracked document read through python-docx
is almost always this, not a real problem.

Simulating accept/reject correctly needs more than dropping ``w:ins`` and
``w:del`` blocks, and a naive version gives wrong answers on a perfectly
good deliverable:

* **A paragraph-mark revision MERGES paragraphs.** Compare encodes a
  split paragraph as an inserted mark, so rejecting it must join the
  remnant to the next paragraph rather than leave it standing. On the LE
  paper this made a bibliography entry look like it had lost its author
  and the paragraph counts come out 928 against 926 — both artifacts.
* **The mark flags live inside ``w:rPr`` and are NOT content.** Removing
  them as if they were is the bug that breaks naive handlers.
* **Moves are their own pair.** Compare writes ``w:moveFrom`` /
  ``w:moveTo``, which behave like del/ins but are invisible to code that
  only knows the latter.

The semantics here follow ``verify_tracked.py`` from the Life Expectancy
paper, which was written against Word's actual behaviour after a COM
accept-all hung for 25 minutes.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    # lxml is imported lazily in the functions below so `import docxkit`
    # does not pay for the parser; the ELEMENT type is still named, so
    # the stubs the dev extra installs see every call in this file. It
    # was `Any` throughout until 2026-09-03, which switched them off at
    # the one seam — accept/reject under the reject-all gate — where
    # they were meant to look (review, row 7).
    from lxml.etree import _Element

from ._xml import (
    MATH_OBJECTS,
    PARA_RE,
    delta_text,
    matching_close,
    used_prefixes,
    visible_text,
)
from .errors import DocxKitError

__all__ = [
    "FINAL",
    "ORIGINAL",
    "REVISION_RE",
    "DocxKitError",
    "ParagraphChange",
    "Revision",
    "accept",
    "by_author",
    "changed_paragraphs",
    "counts",
    "reject",
    "revision_elements",
    "revision_text",
    "rows_in_view",
    "spans",
    "text",
    "view_transform",
    "whitespace_only",
]

FINAL = "final"        # revisions accepted: what the document becomes
ORIGINAL = "original"  # revisions rejected: what it was before

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MATH = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_OPEN_RE = re.compile(r"<w:(ins|del)\b[^>]*?(/?)>")
# Only these two need their real URIs: they are the namespaces this
# module looks elements up by. Every other prefix a fragment might use —
# wp14 on a drawing, w16du on a revision date, o and v on the survey
# questionnaires' VML — is opaque here, and the list of them is
# open-ended because Word adds more with each version. Chasing that list
# is what broke tables.read_all on the papers' own tracked deliverables,
# so unknown prefixes now get a placeholder URI instead: the element
# names survive serialization, which is all the text passes need.
_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
       ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')
_WRAPPER = "docxkitFragment"
_PLACEHOLDER = "urn:docxkit:undeclared:"
_RANGE_MARKERS = ("moveFromRangeStart", "moveFromRangeEnd",
                  "moveToRangeStart", "moveToRangeEnd")


def spans(xml: str) -> list[tuple[int, int]]:
    """(start, end) of every run-level ``w:ins`` / ``w:del``, outermost only.

    Self-closing marks are skipped. A ``<w:ins/>`` with no content is a
    property-level revision — a paragraph mark, table row, or run
    properties — which is not a text range and cannot carry a comment
    anchor. That one test is what separates the two kinds.
    """
    out, pos = [], 0
    while (m := _OPEN_RE.search(xml, pos)):
        if m.group(2) == "/":
            pos = m.end()
            continue
        end = matching_close(xml, m.end(), m.group(1))
        out.append((m.start(), end))
        pos = end                       # nested revisions ride along
    return out


def counts(xml: str) -> tuple[int, int]:
    """(insertions, deletions) as element counts.

    Useful as a health check on a deliverable: a redline whose counts have
    collapsed to single digits was opened in Word and accepted.
    """
    return (len(re.findall(r"<w:ins ", xml)),
            len(re.findall(r"<w:del ", xml)))


def _fragment_declarations(xml: str) -> str:
    """xmlns declarations covering every prefix the fragment uses."""
    declared = set(re.findall(r'xmlns:([\w.-]+)=', _NS))
    extra = "".join(f' xmlns:{p}="{_PLACEHOLDER}{p}"'
                    for p in sorted(used_prefixes(xml) - declared))
    return _NS + extra


def _parse(xml: str) -> tuple[_Element, bool]:
    """Parse a document or a bare fragment; True if it was wrapped.

    The BOM matters: ``str.lstrip()`` does not remove U+FEFF, so a
    document written with one looked like a fragment, got wrapped, and
    then had an XML declaration in the middle of an element.
    """
    from lxml import etree

    # str.lstrip() does not remove U+FEFF, so a document written with
    # a BOM looked like a fragment: it got wrapped, and then had an XML
    # declaration in the middle of an element.
    stripped = xml.lstrip("\ufeff \t\r\n")
    if stripped.startswith(("<?xml", "<w:document")):
        return etree.fromstring(stripped.encode("utf-8")), False
    wrapped = f"<{_WRAPPER} {_fragment_declarations(xml)}>{xml}</{_WRAPPER}>"
    return etree.fromstring(wrapped.encode("utf-8")), True


def _serialize(root: _Element, was_wrapped: bool) -> str:
    from lxml import etree

    if not was_wrapped:
        return str(etree.tostring(root, encoding="unicode"))
    return "".join(etree.tostring(child, encoding="unicode")
                   for child in root)


#: Parents whose `w:ins`/`w:del` child is a FLAG on the thing itself, not a
#: wrapper around content: `w:rPr` flags a paragraph mark, `w:trPr` a row.
#: Both share the element name with the content form, and treating either as
#: content is what breaks naive handlers — a row flag removed as if it were a
#: wrapper leaves the row standing, so an inserted table survived rejection.
_FLAG_PARENTS = (W + "rPr", W + "trPr")


#: Position markers that belong to the DOCUMENT, not to the revision
#: they happen to sit inside. Word writes a moved paragraph's citation
#: anchors INSIDE its `w:moveTo`, so rejecting the move removed the
#: element and took them with it — measured on DSI (2026-08-19): 127
#: bookmarks in the baseline, 125 in the rejected view, and the
#: bidirectional citation links the paper depends on quietly
#: one-directional. Comment markers are the same shape: a comment whose
#: range start is inside a rejected insertion is one Word reports as
#: damaged.
_ANCHOR_TAGS = ("bookmarkStart", "bookmarkEnd", "commentRangeStart",
                "commentRangeEnd", "commentReference")

#: Of those, the markers a BLOCK may hold. The four range markers are
#: `EG_RangeMarkupElements`, which `EG_BlockLevelElts` admits directly —
#: Word writes a `w:bookmarkStart` between two block elements itself.
#: `w:commentReference` is not one: it is run INNER content, valid only
#: inside a `w:r`, so lifting one to where a dropped PARAGRAPH stood
#: would put an element where the schema has no place for it.
_BLOCK_ANCHORS = tuple(t for t in _ANCHOR_TAGS if t != "commentReference")


def _lift_anchors(el: _Element,
                  tags: tuple[str, ...] = _ANCHOR_TAGS) -> None:
    """Move `el`'s position markers out to where `el` stands.

    Called before a revision element is REMOVED. The markers keep their
    order and their nesting relative to each other, so a start still
    precedes its end; what they no longer wrap is the text, because on
    a move that text is being restored somewhere else. Gate 5 is what
    says whether that is acceptable — `reject-all == baseline` sees both
    the count (`structure_counts`) and the empty paragraph left behind
    (`_paras`), which is the honest answer for a move this tool cannot
    undo cleanly.

    `tags` narrows what is lifted to what the destination can legally
    hold — see :data:`_BLOCK_ANCHORS`.
    """
    wanted = {W + tag for tag in tags}
    # `iter()` walks in document order, so the markers keep theirs and a
    # start still precedes its end
    markers = [m for m in el.iter() if m.tag in wanted]
    if not markers:
        return
    parent = el.getparent()
    if parent is None:
        return
    at = list(parent).index(el)
    for offset, marker in enumerate(markers):
        _parent(marker).remove(marker)
        parent.insert(at + offset, marker)


def _parent(el: _Element) -> _Element:
    """The parent of an element this engine found UNDER a root.

    Every element a revision pass removes or unwraps was reached by
    iterating a root, so it has one — and `_parse` wraps a bare
    fragment in a root for exactly that reason. Said here rather than
    assumed at fifteen call sites: `getparent()` is ``_Element | None``,
    and while the annotations were `Any` the checkers could not see the
    fourteen sites that used the value unchecked, or the one that
    checked it AFTER (`_drop_row`, 2026-09-03).
    """
    parent = el.getparent()
    if parent is None:
        raise DocxKitError(
            f"revisions: {_local(str(el.tag))} has no parent — a revision "
            f"element cannot be the root")
    return parent


def _content_elements(root: _Element, tag: str) -> list[_Element]:
    """Elements of `tag` that wrap CONTENT, not a property-level flag."""
    return [el for el in root.iter(W + tag)
            if (parent := el.getparent()) is not None
            and parent.tag not in _FLAG_PARENTS]


@dataclass(frozen=True)
class Revision:
    """What a selective accept/reject predicate gets to decide on."""

    kind: str      # "ins" | "del" | "paragraph-mark"
    author: str
    date: str
    text: str      # the text the revision spans; "" for a paragraph mark


Where = Callable[[Revision], bool]

_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _info(el: _Element, kind: str) -> Revision:
    text = "".join(t.text or "" for t in el.iter(
        W + "t", W + "delText", _M + "t"))
    return Revision(kind=kind,
                    author=el.get(W + "author", ""),
                    date=el.get(W + "date", ""),
                    text=text)


def by_author(*names: str) -> Where:
    """Predicate: the revision was made by one of `names`."""
    wanted = set(names)
    return lambda r: r.author in wanted


def whitespace_only(r: Revision) -> bool:
    """Predicate: an ins/del whose entire text is whitespace.

    The respacing noise a Compare with whitespace ON produces — safe to
    accept in bulk so the author reviews only substance. A paragraph
    mark is NOT whitespace by this rule: accepting one merges paragraphs,
    which is never a trivial change.
    """
    return r.kind in ("ins", "del") and r.text != "" and r.text.strip() == ""


def _unwrap(el: _Element) -> None:
    parent = _parent(el)
    at = list(parent).index(el)
    for child in list(el):
        parent.insert(at, child)
        at += 1
    parent.remove(el)


class ParagraphChange(NamedTuple):
    """One paragraph that a revision operation actually altered."""

    # `paragraph`, not `index`: a NamedTuple field called index shadows
    # tuple.index, which both type checkers reject and which would make
    # the method unreachable on every instance.
    paragraph: int          # 0-based position in the BEFORE document
    before: str             # "" when the paragraph was added
    after: str              # "" when the paragraph was removed


def changed_paragraphs(before: str, after: str) -> list[ParagraphChange]:
    """Which paragraphs a revision operation actually changed, by TEXT.

    The check to run after a selective accept or reject, because the
    obvious one lies. Word reports how many revisions it processed, and
    that number answers a different question: rejecting one author's
    changes through ``Revisions(i).Reject()`` reported 4 of 9 handled,
    while the paragraph-level insert/delete pairs came out as plain
    untracked text and only the run-level edits reverted. Nothing was
    corrupt and the count looked reasonable, which is what made it hard
    to see. Text is the thing the reader gets; count it instead.

    Paragraphs are aligned by content rather than by index, because
    accepting an inserted paragraph mark MERGES two paragraphs — under
    index pairing every paragraph after the merge reads as changed.
    """
    old = [visible_text(m.group(0)) for m in PARA_RE.finditer(before)]
    new = [visible_text(m.group(0)) for m in PARA_RE.finditer(after)]
    out: list[ParagraphChange] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(
            None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        width = max(i2 - i1, j2 - j1)
        for k in range(width):
            out.append(ParagraphChange(
                paragraph=i1 + k,
                before=old[i1 + k] if i1 + k < i2 else "",
                after=new[j1 + k] if j1 + k < j2 else ""))
    return out


def _enclosing_math(el: _Element) -> _Element | None:
    """The ``m:oMath`` this element sits in, if any."""
    node = el.getparent()
    while node is not None:
        if node.tag == MATH + "oMath":
            return node
        node = node.getparent()
    return None


def _glyphs(root: _Element) -> str:
    r"""Every math glyph in document order — the pruning invariant.

    An ``m:t`` with no text carries no glyph, and is skipped for the
    same reason :func:`_has_glyph` reads plain truthiness: the two have
    to agree about what a GLYPH is. They did not, and an author's empty
    run in an equation was the difference — `_has_glyph` called it a
    shell and the prune removed it, `_glyphs` counted it and the guard
    below then reported the removal as a change to the maths, so
    `accept` refused the whole document (2026-09-16).

    The ``\x00`` between them is still load-bearing: it keeps one run
    holding `ab` distinct from two holding `a` and `b`, so a prune that
    regrouped the glyphs a reader sees would not pass unnoticed.
    """
    return "\x00".join(text for t in root.iter(MATH + "t")
                       if (text := t.text))


def _has_glyph(el: _Element) -> bool:
    """Any descendant ``m:t`` carrying text.

    Plain truthiness, so U+00A0 counts: a non-breaking space in an
    equation is a deliberate spacer, and pruning it changes the render.
    """
    return any(t.text for t in el.iter(MATH + "t"))


def _prune_math(maths: list[_Element]) -> None:
    """Drop the empty skeletons a removed revision leaves behind.

    Deleting the runs inside a fraction leaves ``<m:f><m:num/><m:den/>
    </m:f>`` standing, and Word renders that as an empty fraction box
    beside the surviving content — a visibly broken equation from a
    document the toolkit called clean. Word's own AcceptAllRevisions
    prunes these, which is exactly why the fault only ever appeared on
    the XML path, and why it took a visual render to catch.

    Only objects are pruned, never the slots they live in, and only
    inside equations a removal actually touched — a legitimately empty
    ``m:f`` elsewhere in the document is the author's business.

    Bottom-up, so a fraction emptied only by pruning its own children is
    seen as empty in the same pass.
    """
    for om in maths:
        if om.getparent() is None:
            continue                       # a nested one, already dropped
        before = _glyphs(om)
        for el in reversed(list(om.iter())):
            if el is om or el.getparent() is None:
                continue             # om itself, or gone with an ancestor
            # A comment or a processing instruction answers a CALLABLE
            # for `.tag`, and `_local` then `rsplit`s it — an
            # AttributeError naming cython, raised at an author whose
            # manuscript is the thing that failed (2026-09-16). Neither
            # is an equation object, so neither is the prune's business.
            if (isinstance(el.tag, str) and _local(el.tag) in MATH_OBJECTS
                    and not _has_glyph(el)):
                _parent(el).remove(el)
        if _glyphs(om) != before:          # never possible; never silent
            raise DocxKitError(
                "revisions: pruning an empty equation shell changed the "
                f"glyphs {before!r} -> {_glyphs(om)!r}")
        if not _has_glyph(om):
            _parent(om).remove(om)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _mark_flag(para: _Element, tags: tuple[str, ...]) -> _Element | None:
    """The paragraph-mark revision element inside ``pPr/rPr``, if any."""
    ppr = para.find(W + "pPr")
    rpr = None if ppr is None else ppr.find(W + "rPr")
    if rpr is None:
        return None
    return next((el for t in tags
                 if (el := rpr.find(W + t)) is not None), None)


def _row_flag(row: _Element, tags: tuple[str, ...]) -> _Element | None:
    """The row-level revision element inside ``trPr``, if any."""
    trpr = row.find(W + "trPr")
    if trpr is None:
        return None
    return next((el for t in tags
                 if (el := trpr.find(W + t)) is not None), None)


def _drop_row(row: _Element) -> None:
    """Remove a row, and the table with it if nothing is left.

    Word deletes a table whose every row goes; leaving an empty ``w:tbl``
    behind would report one more table than the document has and, on the
    reject side, would not restore the baseline.
    """
    table = _parent(row)
    table.remove(row)
    if not table.findall(W + "tr"):
        parent = table.getparent()
        if parent is not None:
            parent.remove(table)


#: A CELL's own revision flag, inside `w:tcPr`. Same shape as the row's
#: in `trPr` and named differently, so `_row_flag` cannot answer for it:
#: an accepted `w:cellDel` takes the whole `w:tc` with it.
#:
#: `w:cellMerge` is deliberately absent. It records a merge or a split,
#: not an appearance or a disappearance, and applying it means
#: recomputing `gridSpan` and `vMerge` across the row — a different
#: operation with a different failure mode, and no manuscript in the
#: corpus carries one to measure against.
_CELL_FLAG = {"del": "cellDel", "ins": "cellIns"}


def _cell_flags(cell: _Element, tags: tuple[str, ...]) -> list[_Element]:
    """EVERY cell-level revision element inside ``tcPr``, for these tags.

    A list rather than the first, because a rejected ``w:tcPrChange``
    can leave two: the snapshot brings its own ``w:cellDel`` and
    :data:`_OUTSIDE_SNAPSHOT` carries the live one across beside it.
    Removing one of a pair leaves the view still reporting a revision.
    """
    tcpr = cell.find(W + "tcPr")
    if tcpr is None:
        return []
    return [el for t in tags if (name := _CELL_FLAG.get(t))
            for el in tcpr.findall(W + name)]


def _grid_span(cell: _Element) -> int:
    """How many grid columns this cell occupies."""
    span = cell.find(f"{W}tcPr/{W}gridSpan")
    if span is None:
        return 1
    try:
        return max(1, int(span.get(W + "val", "1")))
    except ValueError:
        return 1


def _apply_cell_changes(root: _Element, vanish: tuple[str, ...],
                        keep: tuple[str, ...],
                        wants: Callable[[_Element, str], bool]) -> None:
    """:func:`_apply_cell_revisions` over every table in the tree.

    Its own function for the reason the other extractions here are:
    inline, the two lines took `_simulate_where` from 24 to 25 and
    `test_complexity_debt` refused the commit.
    """
    for table in list(root.iter(W + "tbl")):
        _apply_cell_revisions(table, vanish, keep, wants)


def _apply_cell_revisions(table: _Element, vanish: tuple[str, ...],
                          keep: tuple[str, ...],
                          wants: Callable[[_Element, str], bool]) -> None:
    """Apply the CELL-level revisions in one table.

    Word serializes a deleted COLUMN cell-wise: every row keeps its
    ``w:tc``, marked ``w:cellDel`` in its ``w:tcPr`` with the content
    inside ``w:del``. Nothing here walked that. Accepting removed the
    content and left the emptied cell and its empty ``w:p`` standing, so
    "accept every revision" had four paragraphs the clean copy did not
    and `tracked.build`'s accept gate refused a batch Word itself
    accepts correctly (Aging_Well R79, 2026-09-02):

        UNACCEPTED body ¶44: intended ''  accepted ''

    Same family as the footnote-deletion shells `prune_orphans` cleans
    up: the deliverable is fine and the XML approximation of Word's
    accept is what was short.

    **The grid is corrected only when the deletion IS a column.** A
    table's ``w:tblGrid`` declares the columns the rows lay out against,
    so dropping a cell per row without dropping a ``w:gridCol`` leaves a
    phantom column. But cells can be deleted raggedly — different grid
    positions in different rows — and there is no column to remove then.
    Guessing one would corrupt the geometry of a table that is merely
    edited, so a ragged deletion takes its cells and leaves the grid
    alone.
    """
    rows = table.findall(W + "tr")
    if not rows:
        return
    doomed: list[frozenset[int]] = []
    for row in rows:
        at = 0
        gone: set[int] = set()
        for cell in row.findall(W + "tc"):
            span = _grid_span(cell)
            doomed_here = [f for f in _cell_flags(cell, vanish)
                           if wants(f, "cell")]
            if doomed_here:
                gone.update(range(at, at + span))
                row.remove(cell)
            else:
                # The SURVIVING side's mark is not content, so nothing
                # above reaches it: an accepted table kept one
                # `w:cellIns` per inserted cell and still reported it as
                # a revision. Applying one means removing its markup on
                # both sides — the same rule the row and paragraph-mark
                # handlers follow.
                for kept in _cell_flags(cell, keep):
                    if wants(kept, "cell"):
                        _parent(kept).remove(kept)
            at += span
        doomed.append(frozenset(gone))

    if not doomed[0] or len(set(doomed)) != 1:
        return                       # nothing went, or it went raggedly
    grid = table.find(W + "tblGrid")
    if grid is None:
        return
    for i, col in reversed(list(enumerate(grid.findall(W + "gridCol")))):
        if i in doomed[0]:
            grid.remove(col)


def _merge_into_next(para: _Element) -> None:
    """Word: losing a paragraph mark joins this paragraph to the next."""
    parent = _parent(para)
    nxt = para.getnext()
    while nxt is not None and nxt.tag not in (W + "p", W + "tbl"):
        nxt = nxt.getnext()
    if nxt is None or nxt.tag != W + "p":
        # Nothing can take what it holds — but the position markers are
        # the DOCUMENT's, not the dying paragraph's, so they stay where
        # it stood rather than going with it. Rejecting a moved
        # paragraph that preceded a TABLE dropped the pair Word had put
        # inside the `w:moveTo`: bookmarkStart x0 where the same
        # document followed by a PARAGRAPH keeps x1, and where the
        # baseline has one of each. In this corpus that bookmark is a
        # live `HYPERLINK` target, not litter (2026-09-16).
        _lift_anchors(para, _BLOCK_ANCHORS)
        parent.remove(para)
        return
    at = 0
    nxt_ppr = nxt.find(W + "pPr")
    if nxt_ppr is not None:
        at = list(nxt).index(nxt_ppr) + 1
    for child in list(para):
        if child.tag == W + "pPr":
            continue                    # the surviving paragraph's own wins
        nxt.insert(at, child)
        at += 1
    parent.remove(para)


#: Content revisions — an insertion, a deletion, a move.
_CONTENT_MARKERS = ("<w:ins ", "<w:del ", "<w:ins/", "<w:del/",
                    "w:moveFrom", "w:moveTo")
#: FORMATTING revisions. Word records a property change as a snapshot of
#: the OLD properties nested inside the new ones — `w:tcPrChange` holds a
#: whole `w:tcPr`. A cell whose only revision is one of these carries no
#: content marker at all, so a guard that looked for insertions alone
#: called the table clean and let a writer edit the historical snapshot.
#: A CELL's own flag belongs here rather than among the content markers:
#: it sits in `w:tcPr` like the other property revisions, and a cell
#: whose content was already empty carries nothing else at all.
_PROPERTY_MARKERS = ("<w:tcPrChange", "<w:trPrChange", "<w:tblPrChange",
                     "<w:pPrChange", "<w:rPrChange", "<w:sectPrChange",
                     "<w:tblGridChange",
                     "<w:cellIns", "<w:cellDel", "<w:cellMerge")


#: Every element whose presence means a tracked change is PENDING, as one
#: pattern rather than as a predicate — because a caller that needs to
#: COUNT them, or read their authors, cannot use the booleans below and
#: was therefore writing its own narrower list.
#:
#: `revision.state` did exactly that: it counted `<w:ins ` and `<w:del `
#: alone, so a manuscript whose only pending change was a MOVE or a
#: FORMATTING change reported "0 pending -> TRUTH". That is the number the
#: protocol decides everything on. `build` refuses a baseline with pending
#: revisions because Word's Compare rebuilds a redline from ACCEPTED
#: content — so the guard that stops an author's open verdicts being
#: flattened into plain text was blind to five of the seven ways a verdict
#: can be open.
#:
#: The lookahead is load-bearing: without it `w:moveFrom` also matches
#: `w:moveFromRangeStart`, and a move would be counted twice.
#:
#: The cell trio was the EIGHTH way, found while teaching accept/reject
#: to apply them (2026-09-02). A `w:cellDel` is the whole record of a
#: deleted cell — Word writes no content marker for one that was already
#: empty, and none at all for a `w:cellMerge` — so a table whose column
#: deletion had nothing in it read as 0 pending, which is the number the
#: protocol decides everything on. Same defect as the move, one more
#: spelling.
_REVISION_NAMES = ("ins", "del", "moveFrom", "moveTo", "tcPrChange",
                   "trPrChange", "tblPrChange", "pPrChange", "rPrChange",
                   "sectPrChange", "tblGridChange",
                   "cellIns", "cellDel", "cellMerge")
REVISION_RE = re.compile(
    r"<w:(?:" + "|".join(_REVISION_NAMES) + r")(?=[ />])[^>]*>")


def revision_elements(xml: str) -> list[str]:
    """Every pending-revision element in `xml`, as its opening tag.

    The tag rather than a count, so a caller can read `w:author` off it —
    which is the whole reason the narrower copy existed.
    """
    return REVISION_RE.findall(xml)


def _has_content_revisions(xml: str) -> bool:
    """An insertion, deletion or move — what accept/reject simulate."""
    return any(marker in xml for marker in _CONTENT_MARKERS)


def _has_revisions(xml: str) -> bool:
    """ANY tracked change, including a formatting-only one."""
    return (_has_content_revisions(xml)
            or any(marker in xml for marker in _PROPERTY_MARKERS))


#: The FORMATTING revisions, and what applying one means. Word records
#: a property change as a SNAPSHOT of the old properties nested inside
#: the new ones::
#:
#:     <w:rPr><w:sz w:val="20"/>
#:       <w:rPrChange …><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrChange>
#:     </w:rPr>
#:
#: — the live properties are 10pt and the record says they were 12pt. So
#: accepting is dropping the record, and rejecting is putting the
#: snapshot back. Neither happened here for as long as this module
#: existed: both simulations passed a `*PrChange` straight through, so
#: an XML-accepted file still counted as a proposal, and `reject-all ==
#: baseline` — the gate that proves an author's veto is real — could not
#: fail on a formatting-only batch. `state` has known all seven kinds
#: since `22d5181`; the simulator knew three.
_PROPERTY_CHANGES = ("rPrChange", "pPrChange", "tcPrChange", "trPrChange",
                     "tblPrChange", "sectPrChange", "tblGridChange")

#: What the SNAPSHOT cannot hold, and where it sits in the live element.
#: A reject replaces the live properties with the snapshot's, so anything
#: the snapshot's own content model excludes has to be carried across by
#: hand or it is silently lost:
#:
#: * `pPrChange/pPr` is CT_PPrBase — no `w:rPr` (the paragraph MARK's own
#:   run properties, which carry the mark's insert/delete flag) and no
#:   `w:sectPr` (a section break lives there);
#: * `sectPrChange/sectPr` is CT_SectPrBase, which drops every header and
#:   footer reference — a rejected section-formatting change would take
#:   the running heads with it;
#: * a `w:tcPr`/`w:trPr` also carries the cell's and the row's own
#:   tracked insert/delete flags, and the row handler above needs the
#:   row's to still be there.
#:
#: The side says where they go back: CT_SectPr puts its references
#: FIRST, CT_PPr and CT_TcPr put theirs LAST.
_OUTSIDE_SNAPSHOT: dict[str, tuple[tuple[str, ...], str]] = {
    "pPrChange": (("rPr", "sectPr"), "last"),
    "sectPrChange": (("headerReference", "footerReference"), "first"),
    "tcPrChange": (("cellIns", "cellDel", "cellMerge"), "last"),
    "trPrChange": (("ins", "del"), "last"),
}


def _apply_property_changes(root: _Element, mode: str,
                            wants: Callable[[_Element, str], bool]) -> None:
    """Accept or reject every formatting revision in the tree."""
    for tag in _PROPERTY_CHANGES:
        for change in list(root.iter(W + tag)):
            parent = change.getparent()
            if parent is None or not wants(change, tag):
                continue
            if mode == FINAL:
                parent.remove(change)      # the live properties stay
                continue
            names, side = _OUTSIDE_SNAPSHOT.get(tag, ((), "last"))
            carried = [c for c in parent if c is not change
                       and isinstance(c.tag, str)
                       and c.tag.rsplit("}", 1)[-1] in names]
            # the snapshot is the child the record's schema NAMES — `w:rPr`
            # in a `w:rPrChange`, `w:tblGrid` in a `w:tblGridChange` — and a
            # record with none says "there were no properties", for which
            # emptying the parent is exactly right. Not the first child:
            # XML allows a comment anywhere (2026-09-16), and markup
            # compatibility an ignorable extension element (2026-09-17),
            # and with either AHEAD of the snapshot the first child was
            # restored in its place — no properties, so the run came back
            # with none and nothing said. The first of two snapshots is
            # the one Word reads.
            snapshot = change.find(W + tag.removesuffix("Change"))
            for child in list(parent):
                parent.remove(child)
            for child in (snapshot if snapshot is not None else ()):
                parent.append(child)
            for i, child in enumerate(carried):
                if side == "first":
                    parent.insert(i, child)
                else:
                    parent.append(child)


def _simulate(xml: str, mode: str, where: Where | None = None) -> str:
    # The predicate-free views are CACHED: the audits and the sweep ask
    # for the same view of the same document several times in a row, and
    # simulating a 1,400-revision redline costs ~50ms each time. CPython
    # caches a str's hash, so repeat lookups on the same object are
    # near-free; maxsize stays small because each entry is a
    # megabyte-scale string.
    if where is None:
        return _simulate_clean(xml, mode)
    return _simulate_where(xml, mode, where)


@lru_cache(maxsize=4)
def _simulate_clean(xml: str, mode: str) -> str:
    return _simulate_where(xml, mode, None)


def _apply_content(root: _Element, vanish: tuple[str, ...],
                   keep: tuple[str, ...],
                   wants: Callable[[_Element, str], bool], *,
                   mode: str, selective: bool) -> list[_Element]:
    """Remove the side that goes and untrack the side that stays.

    Returns the equations a removal reached into, collected BEFORE the
    element leaves the tree so the caller's prune can be confined to
    them — which is the whole reason this hands something back.

    `selective` is "a predicate is in force". Under one MOVES are never
    touched: a ``moveFrom`` and its ``moveTo`` are one revision in two
    places, and applying one side alone rewrites the document into
    something neither version says. See :func:`accept`.
    """
    touched: list[_Element] = []
    for tag in vanish:
        for el in _content_elements(root, tag):
            if selective and tag in ("moveFrom", "moveTo"):
                continue               # moves are a pair; see accept()
            if wants(el, tag):
                om = _enclosing_math(el)
                if om is not None and not any(om is seen for seen in touched):
                    touched.append(om)
                _lift_anchors(el)
                _parent(el).remove(el)
    for tag in keep:
        for el in _content_elements(root, tag):
            if selective and tag in ("moveFrom", "moveTo"):
                continue           # the pair is left whole; see accept()
            if not wants(el, tag):
                continue
            if mode == ORIGINAL:
                # restore this deletion's text to ordinary runs; global
                # conversion would also de-track the deletions a
                # predicate chose to LEAVE
                for dt in list(el.iter(W + "delText")):
                    dt.tag = W + "t"
            _unwrap(el)
    return touched


def _apply_rows(root: _Element, vanish: tuple[str, ...], keep: tuple[str, ...],
                wants: Callable[[_Element, str], bool]) -> None:
    """Table ROWS carry their own revision flag, in `trPr`, and it is the
    whole row that appears or disappears — an inserted table is encoded
    as nothing but flagged rows, so a simulation blind to them leaves
    the entire table standing (emptied of text) where Word removes it.

    Called BEFORE :func:`_apply_marks`: a row that goes takes its
    paragraphs with it.
    """
    for row in list(root.iter(W + "tr")):
        flag = _row_flag(row, vanish)
        if flag is not None and wants(flag, "row"):
            _drop_row(row)
            continue
        kept = _row_flag(row, keep)
        if kept is not None and wants(kept, "row"):
            _parent(kept).remove(kept)


def _apply_marks(root: _Element, vanish: tuple[str, ...],
                 keep: tuple[str, ...],
                 wants: Callable[[_Element, str], bool]) -> None:
    """Paragraph-MARK revisions, which are not content.

    The surviving side's flag is not content either, so unwrapping runs
    never reaches it: an accepted document kept one `w:ins` per inserted
    paragraph mark and still reported those as revisions. Applying a
    revision means removing its markup on both sides.
    """
    for para in list(root.iter(W + "p")):
        flag = _mark_flag(para, vanish)
        if flag is not None and wants(flag, "paragraph-mark"):
            _merge_into_next(para)
            continue
        kept = _mark_flag(para, keep)
        if kept is not None and wants(kept, "paragraph-mark"):
            _parent(kept).remove(kept)


def _simulate_where(xml: str, mode: str, where: Where | None = None) -> str:
    # A document with no revisions is its own accepted AND rejected view,
    # so there is nothing to simulate. Worth checking first: most
    # manuscripts are clean, and parsing a 1.7MB part to discover that
    # costs ~20ms every time — per table, in tables.read_all.
    #
    # This asked `_has_content_revisions`, on the reasoning that a
    # formatting snapshot is not something a text simulation can apply.
    # It is: see `_apply_property_changes`. A batch of nothing but
    # `w:rPrChange` came back byte-identical from BOTH views, which is
    # what let gate 5 pass on it without deciding anything.
    if not _has_revisions(xml):
        return xml
    root, wrapped = _parse(xml)
    vanish, keep = (("del", "moveFrom"), ("ins", "moveTo")) \
        if mode == FINAL else (("ins", "moveTo"), ("del", "moveFrom"))

    def wants(el: _Element, kind: str) -> bool:
        return where is None or where(_info(el, kind))

    touched = _apply_content(root, vanish, keep, wants,
                             mode=mode, selective=where is not None)
    if where is None:
        for tag in _RANGE_MARKERS:
            for el in list(root.iter(W + tag)):
                _parent(el).remove(el)
    if touched:
        _prune_math(touched)
    _apply_rows(root, vanish, keep, wants)
    _apply_marks(root, vanish, keep, wants)

    # LAST, so the row and paragraph-mark handlers above still see the
    # `w:ins`/`w:del` flags a rejected `trPrChange`/`pPrChange` restore
    # would otherwise have moved out from under them.
    _apply_property_changes(root, mode, wants)

    # CELLS after it, which is the opposite placement and measured
    # rather than chosen. A `w:tcPrChange`'s SNAPSHOT carries its own
    # `w:cellDel` — Word records the cell's pre-change properties
    # including the delete mark — so a reject that runs the restore
    # afterwards puts back a flag stripped before it, and the rejected
    # view still reported a revision (Aging_Well R79). The vanish side
    # survives the restore either way: `_OUTSIDE_SNAPSHOT` carries the
    # live `cellIns`/`cellDel` across on purpose, which is what makes
    # this order safe where it is not for the row.
    _apply_cell_changes(root, vanish, keep, wants)
    return _serialize(root, wrapped)


def accept(xml: str, *, where: Where | None = None) -> str:
    """The document with revisions accepted.

    `where` accepts selectively: only revisions the predicate approves
    are applied and the rest stay tracked, which is the author-round
    workflow — accept the noise (:func:`whitespace_only`, or one
    author's edits via :func:`by_author`), leave the substance pending
    for a human. Under a predicate MOVES are never touched: a
    ``moveFrom`` and its ``moveTo`` are one revision in two places, and
    applying one side alone rewrites the document into something neither
    version says. Accept or reject moves with the full pass.
    """
    return _simulate(xml, FINAL, where)


def reject(xml: str, *, where: Where | None = None) -> str:
    """The document with revisions rejected.

    Insertions are dropped and deleted text is restored to ordinary runs,
    which is what makes the result readable as normal text. `where`
    rejects selectively, with the same move caveat as :func:`accept`.
    """
    return _simulate(xml, ORIGINAL, where)


def view_transform(view: str) -> Callable[[str], str]:
    """:func:`accept` for ``final``, :func:`reject` for ``original``.

    The one place the view names are validated — four modules used to
    carry their own copy of this dispatch, which is one modules'-worth
    of drift per error message.
    """
    if view == FINAL:
        return accept
    if view == ORIGINAL:
        return reject
    raise ValueError(f"view must be {FINAL!r} or {ORIGINAL!r}")


def rows_in_view(table_xml: str, view: str) -> list[bool]:
    """For each of a table's OWN rows, in order: is it in `view`?

    The raw→view row mapping, and the reason it exists: a table's rows
    in the document and its rows in a VIEW are not the same list. A row
    whose ``w:trPr`` carries ``w:del`` is gone from ``final``, one
    carrying ``w:ins`` is gone from ``original``, and a caller holding
    both — raw ``w:tr`` elements on one side, `Table.rows` on the
    other — cannot pair them by index.

    :func:`accept` and :func:`reject` only ever DROP rows here; nothing
    adds or reorders them. So a per-row answer is the whole mapping: the
    True entries, in order, are the view's rows.

    Nested tables are not this table's rows, matching ``tables.rows_of``
    — the two are read together, so they have to agree about what a row
    is.
    """
    view_transform(view)                   # validates the view name
    vanish = ("del", "moveFrom") if view == FINAL else ("ins", "moveTo")
    root, wrapped = _parse(table_xml)
    tbl = root.find(W + "tbl") if wrapped else root
    if tbl is None:
        return []
    return [_row_flag(tr, vanish) is None for tr in tbl.findall(W + "tr")]


def text(xml: str, view: str = FINAL) -> list[str]:
    """Visible text per paragraph, on one side of the tracked changes."""
    view_transform(view)                # validates; _simulate takes the name
    return list(_text_cached(xml, view))


@lru_cache(maxsize=8)
def _text_cached(xml: str, view: str) -> tuple[str, ...]:
    # Cached for the same reason as _simulate_clean; the walk over ~900
    # paragraphs costs ~7ms per call and callers repeat it. The public
    # function copies to a list so a caller mutating its result cannot
    # poison the cache.
    out = []
    for m in PARA_RE.finditer(_simulate(xml, view)):
        if (t := visible_text(m.group(0))).strip():
            out.append(t)
    return tuple(out)


def revision_text(xml: str, span: tuple[int, int]) -> str:
    """Text a single revision spans, insertions and deletions alike."""
    return delta_text(xml[span[0]:span[1]])
