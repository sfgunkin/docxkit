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

__all__ = ["lint", "lint_parts"]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

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


def lint(*roots: Any) -> list[str]:
    """Problems found across the given lxml roots. Empty means clean."""
    problems: list[str] = []
    revision_ids: dict[str | None, int] = {}

    for root in roots:
        if root is None:
            continue

        # 1. A run-level element sitting directly in a block-only container.
        #    Word rejects the part outright.
        run_level = {W + t for t in _RUN_LEVEL} | {M + t
                                                   for t in _RUN_LEVEL_MATH}
        for name in _BLOCK_CONTAINERS:
            for parent in root.iter(W + name):
                for child in parent:
                    if child.tag in run_level:
                        problems.append(
                            f"w:{name} has run-level child "
                            f"{_local(child.tag)} (must be inside w:p)")

        # 2. An empty w:ins / w:del that is not a paragraph-mark or row
        #    marker — a revision wrapping nothing.
        for tag in ("ins", "del"):
            for element in root.iter(W + tag):
                parent = element.getparent()
                parent_tag = parent.tag if parent is not None else None
                if len(element) == 0 and parent_tag not in (W + "rPr",
                                                            W + "trPr"):
                    problems.append(f"empty w:{tag} (not a marker)")

        # 3. Deleted text must be w:delText. A w:t inside w:del renders as
        #    live text that cannot be rejected. (m:t inside math is fine.)
        for element in root.iter(W + "del"):
            if element.find(".//" + W + "t") is not None:
                problems.append("w:del contains w:t (should be w:delText)")

        # 4. A block element inside a run-level revision.
        for tag in ("ins", "del"):
            for element in root.iter(W + tag):
                parent = element.getparent()
                if parent is not None and parent.tag in (W + "rPr",
                                                         W + "trPr"):
                    continue                       # a marker, not a range
                for child in element:
                    if child.tag in (W + "p", W + "tbl", W + "tr", W + "tc"):
                        problems.append(
                            f"block w:{_local(child.tag)} inside run-level "
                            f"w:{tag}")

        # 5. CT_PPr child order: nothing in _PPR_BEFORE_RPR may follow w:rPr.
        for ppr in root.iter(W + "pPr"):
            kids = [_local(c.tag) for c in ppr]
            if "rPr" in kids:
                after = set(kids[kids.index("rPr") + 1:])
                if bad := sorted(after & _PPR_BEFORE_RPR):
                    problems.append(f"w:pPr: {bad} after w:rPr (CT_PPr order)")

        # 6. w:rPrChange must be the last child of its w:rPr.
        for rpr in root.iter(W + "rPr"):
            kids = [_local(c.tag) for c in rpr]
            if "rPrChange" in kids and kids[-1] != "rPrChange":
                problems.append("w:rPr: w:rPrChange is not the last child")

        # 7. An empty oMath shell renders as garbage, or loses the equation.
        empty = sum(1 for om in root.iter(M + "oMath")
                    if not any(t.text or "" for t in om.iter(M + "t")))
        if empty:
            problems.append(f"{empty} empty m:oMath shell(s)")

        for element in root.iter():
            if element.tag in (W + "ins", W + "del", W + "rPrChange",
                               W + "pPrChange"):
                rid = element.get(W + "id")
                revision_ids[rid] = revision_ids.get(rid, 0) + 1

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
