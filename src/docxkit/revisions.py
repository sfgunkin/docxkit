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
from typing import Any, NamedTuple

from ._xml import (
    MATH_OBJECTS,
    PARA_RE,
    delta_text,
    matching_close,
    visible_text,
)
from .errors import DocxKitError

__all__ = [
    "FINAL",
    "ORIGINAL",
    "ParagraphChange",
    "Revision",
    "accept",
    "by_author",
    "changed_paragraphs",
    "counts",
    "reject",
    "revision_text",
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
_ELEMENT_PREFIX_RE = re.compile(r"</?([A-Za-z][\w.-]*):")
_ATTR_PREFIX_RE = re.compile(r"\s([A-Za-z][\w.-]*):[\w.-]+=")
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
    used = {m.group(1) for m in _ELEMENT_PREFIX_RE.finditer(xml)}
    used |= {m.group(1) for m in _ATTR_PREFIX_RE.finditer(xml)}
    used -= {"xmlns", "xml"}
    extra = "".join(f' xmlns:{p}="{_PLACEHOLDER}{p}"'
                    for p in sorted(used - declared))
    return _NS + extra


def _parse(xml: str) -> tuple[Any, bool]:
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


def _serialize(root: Any, was_wrapped: bool) -> str:
    from lxml import etree

    if not was_wrapped:
        return str(etree.tostring(root, encoding="unicode"))
    return "".join(etree.tostring(child, encoding="unicode")
                   for child in root)


def _content_elements(root: Any, tag: str) -> list[Any]:
    """Elements of `tag` that wrap CONTENT, not the paragraph-mark flag.

    The flag inside ``w:rPr`` shares the element name; treating it as
    content is what breaks naive handlers.
    """
    return [el for el in root.iter(W + tag)
            if el.getparent() is not None
            and el.getparent().tag != W + "rPr"]


@dataclass(frozen=True)
class Revision:
    """What a selective accept/reject predicate gets to decide on."""

    kind: str      # "ins" | "del" | "paragraph-mark"
    author: str
    date: str
    text: str      # the text the revision spans; "" for a paragraph mark


Where = Callable[[Revision], bool]

_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _info(el: Any, kind: str) -> Revision:
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


def _unwrap(el: Any) -> None:
    parent = el.getparent()
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


def _enclosing_math(el: Any) -> Any | None:
    """The ``m:oMath`` this element sits in, if any."""
    node = el.getparent()
    while node is not None:
        if node.tag == MATH + "oMath":
            return node
        node = node.getparent()
    return None


def _glyphs(root: Any) -> str:
    """Every math glyph in document order — the pruning invariant."""
    return "\x00".join(t.text or "" for t in root.iter(MATH + "t"))


def _has_glyph(el: Any) -> bool:
    """Any descendant ``m:t`` carrying text.

    Plain truthiness, so U+00A0 counts: a non-breaking space in an
    equation is a deliberate spacer, and pruning it changes the render.
    """
    return any(t.text for t in el.iter(MATH + "t"))


def _prune_math(maths: list[Any]) -> None:
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
                continue
            if _local(el.tag) in MATH_OBJECTS and not _has_glyph(el):
                el.getparent().remove(el)
        if _glyphs(om) != before:          # never possible; never silent
            raise DocxKitError(
                "revisions: pruning an empty equation shell changed the "
                f"glyphs {before!r} -> {_glyphs(om)!r}")
        if not _has_glyph(om):
            om.getparent().remove(om)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _mark_flag(para: Any, tags: tuple[str, ...]) -> Any | None:
    """The paragraph-mark revision element inside ``pPr/rPr``, if any."""
    ppr = para.find(W + "pPr")
    rpr = None if ppr is None else ppr.find(W + "rPr")
    if rpr is None:
        return None
    return next((el for t in tags
                 if (el := rpr.find(W + t)) is not None), None)


def _merge_into_next(para: Any) -> None:
    """Word: losing a paragraph mark joins this paragraph to the next."""
    parent = para.getparent()
    nxt = para.getnext()
    while nxt is not None and nxt.tag not in (W + "p", W + "tbl"):
        nxt = nxt.getnext()
    if nxt is None or nxt.tag != W + "p":
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
_PROPERTY_MARKERS = ("<w:tcPrChange", "<w:trPrChange", "<w:tblPrChange",
                     "<w:pPrChange", "<w:rPrChange", "<w:sectPrChange",
                     "<w:tblGridChange")


def _has_content_revisions(xml: str) -> bool:
    """An insertion, deletion or move — what accept/reject simulate."""
    return any(marker in xml for marker in _CONTENT_MARKERS)


def _has_revisions(xml: str) -> bool:
    """ANY tracked change, including a formatting-only one."""
    return (_has_content_revisions(xml)
            or any(marker in xml for marker in _PROPERTY_MARKERS))


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


def _simulate_where(xml: str, mode: str, where: Where | None = None) -> str:
    # A document with no revisions is its own accepted AND rejected view,
    # so there is nothing to simulate. Worth checking first: most
    # manuscripts are clean, and parsing a 1.7MB part to discover that
    # costs ~20ms every time — per table, in tables.read_all.
    # content revisions only: this models ins/del/move, and a
    # formatting snapshot is not something it can 'apply'
    if not _has_content_revisions(xml):
        return xml
    root, wrapped = _parse(xml)
    vanish, keep = (("del", "moveFrom"), ("ins", "moveTo")) \
        if mode == FINAL else (("ins", "moveTo"), ("del", "moveFrom"))

    def wants(el: Any, kind: str) -> bool:
        return where is None or where(_info(el, kind))

    # equations a removal reaches into, so the prune below can be
    # confined to them; collected BEFORE the element leaves the tree
    touched: list[Any] = []
    for tag in vanish:
        for el in _content_elements(root, tag):
            if where is not None and tag in ("moveFrom", "moveTo"):
                continue               # moves are a pair; see accept()
            if wants(el, tag):
                om = _enclosing_math(el)
                if om is not None and not any(om is seen for seen in touched):
                    touched.append(om)
                el.getparent().remove(el)
    for tag in keep:
        for el in _content_elements(root, tag):
            if where is not None and tag in ("moveFrom", "moveTo"):
                continue
            if not wants(el, tag):
                continue
            if mode == ORIGINAL:
                # restore this deletion's text to ordinary runs; global
                # conversion would also de-track the deletions a
                # predicate chose to LEAVE
                for dt in list(el.iter(W + "delText")):
                    dt.tag = W + "t"
            _unwrap(el)
    if where is None:
        for tag in _RANGE_MARKERS:
            for el in list(root.iter(W + tag)):
                el.getparent().remove(el)
    if touched:
        _prune_math(touched)
    for para in list(root.iter(W + "p")):
        flag = _mark_flag(para, vanish)
        if flag is not None and wants(flag, "paragraph-mark"):
            _merge_into_next(para)
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
