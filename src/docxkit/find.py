r"""Locating things inside ``word/document.xml``.

Prose anchors have to be located by VISIBLE TEXT, never by raw XML: Word
fragments a sentence across runs at rsid boundaries, so "Figure 6" is
routinely stored as ``Figur`` + ``e`` + ` 6` and a ``\bFigure 6\b`` regex
silently misses it. Everything here works on the concatenation of the
``<w:t>`` / ``<m:t>`` contents and maps back to offsets.
"""
from __future__ import annotations

import html
import re

__all__ = [
    "P_RE",
    "delta_text_of",
    "edit_para",
    "para_slice",
    "para_text_at",
    "paragraphs",
    "table_index_at",
    "table_spans",
    "text_of",
]

P_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)
_T_RE = re.compile(r"<(?:w|m):t[^>]*>([^<]*)</(?:w|m):t>")
# includes deleted text, for reading a revision's full before/after
_T_DEL_RE = re.compile(
    r"<(?:w|m):(?:t|delText)[^>]*>([^<]*)</(?:w|m):(?:t|delText)>")


def text_of(xml: str) -> str:
    """Visible text of a fragment (``w:t`` + ``m:t``), deletions excluded.

    Entities are unescaped, so anchors read the way the document reads:
    ``"R&D spending"`` matches a paragraph stored as ``R&amp;D spending``.
    """
    return html.unescape("".join(_T_RE.findall(xml)))


def delta_text_of(xml: str) -> str:
    """Visible text INCLUDING ``w:delText`` — what a revision spans."""
    return html.unescape("".join(_T_DEL_RE.findall(xml)))


def paragraphs(xml: str) -> list[re.Match]:
    """Every ``<w:p>`` as a match, so callers keep the offsets."""
    return list(P_RE.finditer(xml))


def para_slice(xml: str, sig: str, also: str | None = None) -> tuple[int, int]:
    """(start, end) of the ONE paragraph whose visible text contains `sig`.

    Raises unless exactly one matches: an anchor that hits two paragraphs
    is a latent bug that would otherwise edit whichever came first. Pass
    `also` to disambiguate (e.g. the equation number).
    """
    hits = [(m.start(), m.end()) for m in P_RE.finditer(xml)
            if sig in (t := text_of(m.group(0)))
            and (also is None or also in t)]
    if len(hits) != 1:
        raise AssertionError(
            f"para_slice({sig!r}, also={also!r}): {len(hits)} hits, need 1")
    return hits[0]


def edit_para(xml: str, sig: str, fn) -> str:
    """Apply `fn` to the single paragraph whose visible text contains `sig`."""
    s, e = para_slice(xml, sig)
    return xml[:s] + fn(xml[s:e]) + xml[e:]


def para_text_at(xml: str, pos: int) -> str:
    """Visible text of the paragraph containing offset `pos`."""
    for m in P_RE.finditer(xml):
        if m.start() <= pos < m.end():
            return text_of(m.group(0))
    return ""


def table_spans(xml: str, expect: int | None = None) -> list[tuple[int, int]]:
    """(start, end) of every ``<w:tbl>`` in body order.

    Index into this to identify WHICH manuscript table an offset falls in.
    `expect` asserts the count, so a table added or lost upstream fails
    loudly here instead of silently shifting every later index.
    """
    spans = []
    for m in re.finditer(r"<w:tbl>", xml):
        s = m.start()
        spans.append((s, xml.index("</w:tbl>", s) + len("</w:tbl>")))
    if expect is not None and len(spans) != expect:
        raise AssertionError(f"{len(spans)} tables, expected {expect}")
    return spans


def table_index_at(spans: list[tuple[int, int]], pos: int) -> int | None:
    """Index of the table containing `pos`, or None if outside every table."""
    return next((i for i, (s, e) in enumerate(spans) if s <= pos < e), None)
