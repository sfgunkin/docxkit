r"""Reading, locating and rewriting manuscript tables.

Every paper's value tests read tables, and several papers build them, so
this had been written five or six ways: AFI's ``export_tables`` and its
``_docx_table_by_header``, Parental Style's five ``build_table*.py``,
Life Expectancy's ``read_table4``, DSI's ``check_table4_18``, Loneliness
Index's ``inspect_tables``.

It works on the XML rather than through python-docx, which matters for a
tracked-changes document: python-docx only walks runs that are direct
children of a paragraph, so a cell whose text is an insertion reads back
EMPTY. A redline table read through python-docx silently loses every
changed cell — :func:`read_all` takes a `view` instead and gives you the
accepted or the original side.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, overload

from ._xml import PARA_RE, matching_close, set_run_text, visible_text
from .errors import AnchorError
from .revisions import FINAL, ORIGINAL, accept, reject

__all__ = [
    "Table",
    "by_caption",
    "find",
    "parse_number",
    "read_all",
    "set_cell",
    "to_frame",
    "tolerance_for",
]

_TR_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
_TC_RE = re.compile(r"<w:tc>.*?</w:tc>", re.DOTALL)
# a leading signed number, tolerating the typographic minus and separators
_NUM_RE = re.compile(r"[-−+]?\d[\d,  ]*(?:\.\d+)?")


@dataclass(frozen=True)
class Table:
    """One ``<w:tbl>``: its position, and its cell text as rows."""

    index: int                   # position in body order
    start: int                   # offset in the document XML
    end: int
    rows: list[list[str]]

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.rows), max((len(r) for r in self.rows), default=0))

    def column(self, index: int) -> list[str]:
        """A column's cells, header excluded."""
        return [r[index] for r in self.rows[1:] if len(r) > index]

    def row_named(self, label: str) -> list[str] | None:
        """The first data row whose leading cell equals `label`."""
        return next((r for r in self.rows[1:] if r and r[0].strip() == label),
                    None)

    def numbers(self) -> list[list[float | None]]:
        return [[parse_number(c) for c in row] for row in self.rows]


def read_all(xml: str, *, view: str = FINAL) -> list[Table]:
    """Every table in the document, cells rendered as text.

    `view` picks the side of any tracked changes: ``final`` accepts the
    revisions, ``original`` rejects them.
    """
    if view not in (FINAL, ORIGINAL):
        raise ValueError(f"view must be {FINAL!r} or {ORIGINAL!r}")
    transform = accept if view == FINAL else reject
    out = []
    for i, (start, end) in enumerate(_table_spans(xml)):
        body = transform(xml[start:end])
        rows = []
        for tr in _TR_RE.finditer(body):
            cells = [_cell_text(tc.group(0)) for tc in _TC_RE.finditer(
                tr.group(0))]
            rows.append(cells)
        out.append(Table(index=i, start=start, end=end, rows=rows))
    return out


def _table_spans(xml: str) -> list[tuple[int, int]]:
    """(start, end) of every TOP-LEVEL table, nesting respected.

    A non-greedy ``<w:tbl>.*?</w:tbl>`` closes on the first end tag it
    meets, which for a table containing another table is the INNER one —
    the fragment then ends mid-cell. Questionnaires nest tables freely,
    and that is where this first bit.
    """
    spans, pos = [], 0
    while (at := xml.find("<w:tbl>", pos)) != -1:
        end = matching_close(xml, at + len("<w:tbl>"), "tbl")
        spans.append((at, end))
        pos = end                      # nested tables ride along inside
    return spans


def _cell_text(tc_xml: str) -> str:
    """Cell text, paragraphs joined by a space (cells wrap)."""
    parts = [visible_text(p.group(0)).strip()
             for p in PARA_RE.finditer(tc_xml)]
    return " ".join(p for p in parts if p).strip()


@overload
def find(tables: list[Table], header: list[str],
         *, required: Literal[True] = ...) -> Table: ...
@overload
def find(tables: list[Table], header: list[str],
         *, required: Literal[False]) -> Table | None: ...


def find(tables: list[Table], header: list[str],
         *, required: bool = True) -> Table | None:
    """The table whose header row matches `header`.

    Each entry is matched as a SUBSTRING of the corresponding cell, so
    ``["Country", "AFI (initial)"]`` finds the table regardless of a
    trailing footnote marker or a line break in the cell.

    Raises when nothing matches; pass ``required=False`` to get None
    instead. The overloads mean callers of the default form get a
    ``Table``, not an ``Optional`` they would have to keep unwrapping.
    """
    for t in tables:
        cells = t.header
        if len(cells) < len(header):
            continue
        if all(want in cells[i] for i, want in enumerate(header)):
            return t
    if required:
        raise AnchorError(
            f"no table with header {header}; saw "
            f"{[t.header[:3] for t in tables]}")
    return None


@overload
def by_caption(xml: str, caption: str, *, view: str = ...,
               required: Literal[True] = ...) -> Table: ...
@overload
def by_caption(xml: str, caption: str, *, view: str = ...,
               required: Literal[False]) -> Table | None: ...


def by_caption(xml: str, caption: str, *, view: str = FINAL,
               required: bool = True) -> Table | None:
    """The table belonging to a caption such as ``"Table 4."``.

    House convention in these papers is that a table caption sits ABOVE
    its table, so this takes the first table starting after the caption
    paragraph. (Figure captions sit above their images too, which is why
    offset-based caption-to-object mapping goes wrong if you assume
    otherwise.)
    """
    para = next((m for m in PARA_RE.finditer(xml)
                 if caption in visible_text(m.group(0))), None)
    if para is None:
        if required:
            raise AnchorError(f"no paragraph containing caption {caption!r}")
        return None
    for t in read_all(xml, view=view):
        if t.start > para.start():
            return t
    if required:
        raise AnchorError(f"caption {caption!r} has no table after it")
    return None


def parse_number(text: str) -> float | None:
    """Leading numeric value of a cell, or None if it holds no number.

    Handles what these tables actually contain: a typographic minus
    (U+2212), a leading ``+``, thousands separators including the
    non-breaking kind, a trailing ``%``, and significance stars or
    bracketed p-values after the value (``-0.623** [0.038]``).
    """
    text = text.strip()
    if not text:
        return None
    m = _NUM_RE.match(text)
    if not m:
        return None
    raw = (m.group(0).replace("−", "-").replace(",", "")
           .replace(" ", "").replace(" ", ""))
    try:
        return float(raw)
    except ValueError:
        return None


def tolerance_for(decimals: int) -> float:
    """Comparison tolerance for a cell rendered to `decimals` places.

    Half of the last printed digit: a cell showing 0.31 could be anything
    in [0.305, 0.315), so that is the most the data may differ by before
    the rendering is genuinely wrong.
    """
    return float(0.5 * 10 ** -decimals)


def set_cell(xml: str, table: Table, row: int, col: int, text: str) -> str:
    """Rewrite one cell's text, preserving its formatting.

    The cell keeps its own run properties: only the first ``w:t`` in the
    cell takes the new text and any others are blanked, so fonts,
    borders and shading survive.
    """
    body = xml[table.start:table.end]
    trs = list(_TR_RE.finditer(body))
    if row >= len(trs):
        raise AnchorError(f"table {table.index} has {len(trs)} rows, "
                          f"cannot set row {row}")
    tr = trs[row]
    tcs = list(_TC_RE.finditer(tr.group(0)))
    if col >= len(tcs):
        raise AnchorError(f"row {row} has {len(tcs)} cells, "
                          f"cannot set column {col}")
    tc = tcs[col]
    new_tc = set_run_text(tc.group(0), text)
    new_tr = tr.group(0)[:tc.start()] + new_tc + tr.group(0)[tc.end():]
    new_body = body[:tr.start()] + new_tr + body[tr.end():]
    return xml[:table.start] + new_body + xml[table.end:]


def to_frame(table: Table, *, header_row: int = 0) -> Any:
    """The table as a pandas DataFrame (pandas imported only if used)."""
    import pandas as pd  # type: ignore[import-untyped]

    head = table.rows[header_row]
    data = table.rows[header_row + 1:]
    width = len(head)
    padded = [row[:width] + [""] * (width - len(row)) for row in data]
    return pd.DataFrame(padded, columns=head)
