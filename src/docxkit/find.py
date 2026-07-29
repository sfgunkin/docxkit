r"""Locating things inside ``word/document.xml``.

Prose anchors have to be located by VISIBLE TEXT, never by raw XML: Word
fragments a sentence across runs at rsid boundaries, so "Figure 6" is
routinely stored as ``Figur`` + ``e`` + ` 6` and a ``\bFigure 6\b`` regex
silently misses it. Everything here works on the concatenation of the
``<w:t>`` / ``<m:t>`` contents and maps back to offsets.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from ._xml import PARA_RE, delta_text, visible_text
from .errors import AnchorError

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

# kept as an alias: several paper scripts import P_RE from here
P_RE = PARA_RE
text_of = visible_text
delta_text_of = delta_text


def paragraphs(xml: str) -> list[re.Match[str]]:
    """Every ``<w:p>`` as a match, so callers keep the offsets."""
    return list(PARA_RE.finditer(xml))


def para_slice(xml: str, sig: str, also: str | None = None) -> tuple[int, int]:
    """(start, end) of the ONE paragraph whose visible text contains `sig`.

    Raises unless exactly one matches: an anchor that hits two paragraphs
    is a latent bug that would otherwise edit whichever came first. Pass
    `also` to disambiguate (e.g. the equation number).
    """
    hits = [(m.start(), m.end()) for m in PARA_RE.finditer(xml)
            if sig in (t := visible_text(m.group(0)))
            and (also is None or also in t)]
    if len(hits) != 1:
        raise AnchorError(
            f"para_slice({sig!r}, also={also!r}): {len(hits)} hits, need 1")
    return hits[0]


def edit_para(xml: str, sig: str,
              fn: Callable[[str], str]) -> str:
    """Apply `fn` to the single paragraph whose visible text contains `sig`."""
    s, e = para_slice(xml, sig)
    return xml[:s] + fn(xml[s:e]) + xml[e:]


def find_para(xml: str, sig: str) -> re.Match[str] | None:
    """First paragraph whose visible text contains `sig`, or None."""
    return next((m for m in PARA_RE.finditer(xml)
                 if sig in visible_text(m.group(0))), None)


def para_text_at(xml: str, pos: int) -> str:
    """Visible text of the paragraph containing offset `pos`."""
    for m in PARA_RE.finditer(xml):
        if m.start() <= pos < m.end():
            return visible_text(m.group(0))
    return ""


def table_spans(xml: str, expect: int | None = None) -> list[tuple[int, int]]:
    """(start, end) of every ``<w:tbl>`` in body order.

    Index into this to identify WHICH manuscript table an offset falls in.
    `expect` asserts the count, so a table added or lost upstream fails
    loudly here instead of silently shifting every later index.
    """
    out = []
    for m in re.finditer(r"<w:tbl>", xml):
        s = m.start()
        out.append((s, xml.index("</w:tbl>", s) + len("</w:tbl>")))
    if expect is not None and len(out) != expect:
        raise AnchorError(f"{len(out)} tables, expected {expect}")
    return out


def table_index_at(spans: list[tuple[int, int]], pos: int) -> int | None:
    """Index of the table containing `pos`, or None if outside every table."""
    return next((i for i, (s, e) in enumerate(spans) if s <= pos < e), None)
