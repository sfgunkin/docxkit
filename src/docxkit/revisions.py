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
from typing import Any

from ._xml import PARA_RE, delta_text, matching_close, visible_text

__all__ = [
    "FINAL",
    "ORIGINAL",
    "accept",
    "counts",
    "reject",
    "revision_text",
    "spans",
    "text",
]

FINAL = "final"        # revisions accepted: what the document becomes
ORIGINAL = "original"  # revisions rejected: what it was before

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
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


def _unwrap(el: Any) -> None:
    parent = el.getparent()
    at = list(parent).index(el)
    for child in list(el):
        parent.insert(at, child)
        at += 1
    parent.remove(el)


def _has_mark_flag(para: Any, tags: tuple[str, ...]) -> bool:
    ppr = para.find(W + "pPr")
    rpr = None if ppr is None else ppr.find(W + "rPr")
    if rpr is None:
        return False
    return any(rpr.find(W + t) is not None for t in tags)


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


def _has_revisions(xml: str) -> bool:
    return any(marker in xml for marker in
               ("<w:ins ", "<w:del ", "<w:ins/", "<w:del/",
                "w:moveFrom", "w:moveTo"))


def _simulate(xml: str, mode: str) -> str:
    # A document with no revisions is its own accepted AND rejected view,
    # so there is nothing to simulate. Worth checking first: most
    # manuscripts are clean, and parsing a 1.7MB part to discover that
    # costs ~20ms every time — per table, in tables.read_all.
    if not _has_revisions(xml):
        return xml
    root, wrapped = _parse(xml)
    vanish, keep = (("del", "moveFrom"), ("ins", "moveTo")) \
        if mode == FINAL else (("ins", "moveTo"), ("del", "moveFrom"))

    for tag in vanish:
        for el in _content_elements(root, tag):
            el.getparent().remove(el)
    for tag in keep:
        for el in _content_elements(root, tag):
            _unwrap(el)
    if mode == ORIGINAL:
        for dt in list(root.iter(W + "delText")):
            dt.tag = W + "t"
    for tag in _RANGE_MARKERS:
        for el in list(root.iter(W + tag)):
            el.getparent().remove(el)
    for para in list(root.iter(W + "p")):
        if _has_mark_flag(para, vanish):
            _merge_into_next(para)
    return _serialize(root, wrapped)


def accept(xml: str) -> str:
    """The document with every revision accepted."""
    return _simulate(xml, FINAL)


def reject(xml: str) -> str:
    """The document with every revision rejected.

    Insertions are dropped and deleted text is restored to ordinary runs,
    which is what makes the result readable as normal text.
    """
    return _simulate(xml, ORIGINAL)


def text(xml: str, view: str = FINAL) -> list[str]:
    """Visible text per paragraph, on one side of the tracked changes."""
    if view not in (FINAL, ORIGINAL):
        raise ValueError(f"view must be {FINAL!r} or {ORIGINAL!r}")
    out = []
    for m in PARA_RE.finditer(_simulate(xml, view)):
        if (t := visible_text(m.group(0))).strip():
            out.append(t)
    return out


def revision_text(xml: str, span: tuple[int, int]) -> str:
    """Text a single revision spans, insertions and deletions alike."""
    return delta_text(xml[span[0]:span[1]])
