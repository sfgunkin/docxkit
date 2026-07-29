r"""Reading tracked changes.

Two things python-docx cannot do at all, because it only walks runs that
are direct children of a paragraph and a tracked insertion is nested
inside ``<w:ins>``: see the text of an insertion, and show either side of
a redline. A "blank" cell in a tracked document read through python-docx
is almost always this, not a real problem.
"""
from __future__ import annotations

import re

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

_OPEN_RE = re.compile(r"<w:(ins|del)\b[^>]*?(/?)>")
_INS_BLOCK_RE = re.compile(r"<w:ins\b[^>]*?>.*?</w:ins>", re.DOTALL)
_DEL_BLOCK_RE = re.compile(r"<w:del\b[^>]*?>.*?</w:del>", re.DOTALL)
_DELTEXT_OPEN_RE = re.compile(r"<w:delText([^>]*)>")


def spans(xml: str) -> list[tuple[int, int]]:
    """(start, end) of every run-level ``w:ins`` / ``w:del``, outermost only.

    Self-closing marks are skipped. A ``<w:ins/>`` with no content is a
    property-level revision — an inserted paragraph mark, table row, or
    run property — which is not a text range and cannot carry a comment
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


def accept(xml: str) -> str:
    """The document with every revision accepted (deletions removed)."""
    return _DEL_BLOCK_RE.sub("", xml)


def reject(xml: str) -> str:
    """The document with every revision rejected.

    Insertions are dropped and deleted text is restored to ordinary runs,
    which is what makes the result readable as normal text.
    """
    xml = _INS_BLOCK_RE.sub("", xml)
    xml = _DELTEXT_OPEN_RE.sub(r"<w:t\1>", xml)
    return xml.replace("</w:delText>", "</w:t>")


def text(xml: str, view: str = FINAL) -> list[str]:
    """Visible text per paragraph, on one side of the tracked changes."""
    if view not in (FINAL, ORIGINAL):
        raise ValueError(f"view must be {FINAL!r} or {ORIGINAL!r}")
    transform = accept if view == FINAL else reject
    out = []
    for m in PARA_RE.finditer(xml):
        para = transform(m.group(0))
        if (t := visible_text(para)).strip():
            out.append(t)
    return out


def revision_text(xml: str, span: tuple[int, int]) -> str:
    """Text a single revision spans, insertions and deletions alike."""
    return delta_text(xml[span[0]:span[1]])
