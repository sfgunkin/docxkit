r"""Structural checks for the "Word says the file is corrupted" bug classes.

Ported from the DSI paper's ``dsidocx.lint``, which was built after
repeatedly shipping markup Word refused to open. Every check here
corresponds to something that actually happened: an offline lint catches
it in milliseconds, where the alternative is a Word round-trip and a
dialog that says only "unreadable content".

Run it before writing any document you edited structurally —
:func:`docxkit.tracked.build` does, and ``docxkit lint FILE`` does it to
an existing file.
"""
from __future__ import annotations

from typing import Any

from ._xml import XML_WS

__all__ = ["lint", "lint_parts"]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Containers that may hold only block-level children.
_BLOCK_CONTAINERS = ("footnote", "endnote", "body", "tc", "comment")
# Elements that belong inside a paragraph, never directly in the above.
_RUN_LEVEL = ("r", "ins", "del", "hyperlink")
_RUN_LEVEL_MATH = ("oMath", "oMathPara")
# CT_PPr fixes this order: all of these must precede w:rPr.
_PPR_BEFORE_RPR = frozenset({
    "pStyle", "keepNext", "keepLines", "numPr", "spacing", "ind", "jc",
    "outlineLvl", "contextualSpacing",
})
# Parts worth checking, in the order a reader would care about.
_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml",
          "word/comments.xml")


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


# Tag sets for the walks below, built once.
#: property containers whose children may each appear once
_PROPS = ("tcPr", "rPr", "pPr", "trPr", "tblPr")
_RUN_LEVEL_TAGS = frozenset({W + t for t in _RUN_LEVEL}
                            | {M + t for t in _RUN_LEVEL_MATH})
_BLOCK_CHILDREN = frozenset({W + "p", W + "tbl", W + "tr", W + "tc"})
_MARKER_PARENTS = frozenset({W + "rPr", W + "trPr"})


def lint(*roots: Any) -> list[str]:
    """Problems found across the given lxml roots. Empty means clean.

    Iteration stays C-filtered: ``root.iter(tag, tag, ...)`` walks in
    lxml's C layer, and measured on real manuscripts it beats a single
    Python-level walk that dispatches on every element (that rewrite
    was tried and was SLOWER than the original). What made the original
    slow was one full un-filtered ``root.iter()`` just to collect
    revision ids, plus separate passes per revision check — both now
    share one multi-tag walk. Findings are collected per check and
    emitted in the original check order, so the report reads exactly as
    before.
    """
    problems: list[str] = []
    revision_ids: dict[str | None, int] = {}

    for root in roots:
        if root is None:
            continue

        # 1. A run-level element sitting directly in a block-only
        #    container. Word rejects the part outright.
        for parent in root.iter(*(W + t for t in _BLOCK_CONTAINERS)):
            for child in parent:
                if child.tag in _RUN_LEVEL_TAGS:
                    problems.append(
                        f"w:{_local(parent.tag)} has run-level child "
                        f"{_local(child.tag)} (must be inside w:p)")

        # 2/3/4 + id collection, one multi-tag C-filtered walk.
        c2: list[str] = []
        c3: list[str] = []
        c4: list[str] = []
        for element in root.iter(W + "ins", W + "del", W + "rPrChange",
                                 W + "pPrChange"):
            rid = element.get(W + "id")
            revision_ids[rid] = revision_ids.get(rid, 0) + 1
            tag = element.tag
            if tag not in (W + "ins", W + "del"):
                continue
            parent = element.getparent()
            parent_tag = parent.tag if parent is not None else None
            if parent_tag in _MARKER_PARENTS:
                continue                       # a marker, not a range
            # 2. An empty w:ins / w:del that is not a marker.
            if len(element) == 0:
                c2.append(f"empty w:{_local(tag)} (not a marker)")
            # 3. Deleted text must be w:delText; a w:t inside w:del
            #    renders as live text that cannot be rejected.
            if tag == W + "del" and \
                    element.find(".//" + W + "t") is not None:
                c3.append("w:del contains w:t (should be w:delText)")
            # 4. A block element inside a run-level revision.
            for child in element:
                if child.tag in _BLOCK_CHILDREN:
                    c4.append(f"block w:{_local(child.tag)} inside "
                              f"run-level w:{_local(tag)}")
        problems += c2

        # 3b. A w:t carrying edge whitespace without xml:space="preserve".
        #     OOXML trims it, so the space survives in the tooling that
        #     wrote it but is dropped by every conforming reader — Word on
        #     open, on save, and inside CompareDocuments. On the LE paper
        #     this masqueraded as recurring "Word damage" for seven author
        #     rounds and shipped four typos into the journal's copy.
        #     Only real XML whitespace is trimmed: a leading NBSP is safe,
        #     and Word puts one in every empty table cell.
        c3b: list[str] = []
        for element in root.iter(W + "t"):
            text = element.text or ""
            if (text != text.strip(XML_WS)
                    and element.get(XML_SPACE) != "preserve"):
                c3b.append(
                    'w:t has edge whitespace without '
                    'xml:space="preserve" '
                    f"({text[:30]!r}) - run "
                    "docxkit.edit.preserve_space as the last build step")
        problems += c3 + c3b + c4

        # 5. CT_PPr child order: nothing in _PPR_BEFORE_RPR follows w:rPr.
        for ppr in root.iter(W + "pPr"):
            kids = [_local(c.tag) for c in ppr]
            if "rPr" in kids:
                after = set(kids[kids.index("rPr") + 1:])
                if bad := sorted(after & _PPR_BEFORE_RPR):
                    problems.append(
                        f"w:pPr: {bad} after w:rPr (CT_PPr order)")

        # 6. w:rPrChange must be the last child of its w:rPr.
        for rpr in root.iter(W + "rPr"):
            kids = [_local(c.tag) for c in rpr]
            if "rPrChange" in kids and kids[-1] != "rPrChange":
                problems.append("w:rPr: w:rPrChange is not the last child")

        # 7. An empty oMath shell renders as garbage, or loses the math.
        empty = sum(1 for om in root.iter(M + "oMath")
                    if not any(t.text or "" for t in om.iter(M + "t")))
        if empty:
            problems.append(f"{empty} empty m:oMath shell(s)")

        # 7b. A properties element may carry each child ONCE. Two
        #     w:tcBorders in one w:tcPr is schema-invalid and reads as
        #     "unreadable content", and neither the write gate (a
        #     duplicate is still well-formed) nor anything else here
        #     saw it — a border writer that matched only the expanded
        #     <w:tcBorders> and not the empty <w:tcBorders/> inserted a
        #     second one beside it.
        for props in root.iter(*(W + t for t in _PROPS)):
            seen: set[str] = set()
            for child in props:
                tag = _local(child.tag)
                if tag in seen:
                    problems.append(
                        f"w:{_local(props.tag)} carries two w:{tag} "
                        "children (each may appear once)")
                seen.add(tag)

    # 8. Revision ids must be unique across the whole package; Word merges
    #    or drops revisions that share one.
    dups = sorted((i for i, n in revision_ids.items() if n > 1),
                  key=lambda x: (x is None, x))
    if dups:
        problems.append(f"duplicate revision w:id across parts: {dups}")
    return problems


def lint_parts(parts: dict[str, bytes]) -> list[str]:
    """Lint the text-bearing parts of a package."""
    from lxml import etree

    roots = []
    for name in _PARTS:
        if name in parts:
            try:
                roots.append(etree.fromstring(parts[name]))
            except etree.XMLSyntaxError as exc:
                return [f"{name} is not well-formed XML: {exc}"]
    return lint(*roots)
