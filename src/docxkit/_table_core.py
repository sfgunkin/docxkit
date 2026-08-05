r"""Reading a manuscript table, and rewriting its VALUES.

The data view: locate a table, read its cells as text, write a block of
regenerated numbers back into it. How it is LAID OUT — column widths,
borders, superscript stars — is :mod:`_table_layout`, which shares only
the :class:`Table` type with this module.

It works on the XML rather than through python-docx, which matters for a
tracked-changes document: python-docx only walks runs that are direct
children of a paragraph, so a cell whose text is an insertion reads back
EMPTY. A redline table read through python-docx silently loses every
changed cell — :func:`read_all` takes a `view` instead and gives you the
accepted or the original side.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, overload

from ._xml import (
    PARA_RE,
    element_spans,
    matching_close,
    set_run_text,
    visible_text,
)
from .errors import AnchorError
from .revisions import FINAL, _has_revisions, view_transform

_TR_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
_TC_RE = re.compile(r"<w:tc>.*?</w:tc>", re.DOTALL)
# a merged cell: structure, which is why it lives here and
# not with the width fitting that also consumes it
_SPAN_RE = re.compile(r'<w:gridSpan w:val="(\d+)"/>')
# a leading signed number, tolerating the typographic minus and separators
_NUM_RE = re.compile(r"[-−+]?\d[\d,  ]*(?:\.\d+)?")


@dataclass(frozen=True)
class _Span:
    """A located element, offering the slice of `re.Match` this module
    uses. Not a Match: the depth-aware walk finds spans by counting
    tags, and dressing that up as a regex result would only disguise
    where the offsets come from."""

    xml: str
    at: int
    to: int

    def start(self) -> int:
        return self.at

    def end(self) -> int:
        return self.to

    def group(self, index: int = 0) -> str:
        return self.xml


def _spans(xml: str, tag: str) -> list[_Span]:
    return [_Span(xml[s:e], s, e) for s, e in element_spans(xml, tag)]


def rows_of(body: str) -> list[_Span]:
    """The table's OWN rows — a nested table's rows are not its rows."""
    return _spans(body, "tr")


def cells_of(row: str) -> list[_Span]:
    """The row's OWN cells, likewise."""
    return _spans(row, "tc")


@dataclass(frozen=True)
class Table:
    """One ``<w:tbl>``: its position, and its cell text as rows.

    **Rows are CELL-indexed, not grid-column-indexed.** ``rows[r][c]`` is
    the c-th ``<w:tc>`` of the row, so a row containing a merged cell is
    SHORTER than the grid is wide, and its later cells sit at grid
    columns further right than their index suggests. Every mutator that
    takes a ``col`` here — :func:`set_cell`, :func:`update`,
    :meth:`column` — uses that same cell index, so the two agree.

    :func:`fit_columns` and :class:`FitReport`, by contrast, speak in
    GRID columns, because that is what a width belongs to. Mixing the
    two silently addresses a different cell the moment a ``gridSpan``
    appears; :meth:`grid_columns` converts deliberately.
    """

    index: int                   # position in body order
    start: int                   # offset in the document XML
    end: int
    rows: list[list[str]]
    #: Hash of the XML this was read from, so a mutator can tell that
    #: `start`/`end` no longer mean anything. Every edit here returns a
    #: NEW string and shifts every later offset, and the toolkit's own
    #: docstrings could only ASK callers to re-read. `None` on a
    #: hand-built Table, which is not anchored to any source.
    source: int | None = None

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

    def grid_columns(self, xml: str, row: int) -> list[int]:
        """First grid column of each cell in `row` — the bridge.

        ``[0, 1, 3]`` means the row's third cell starts at grid column 3
        because an earlier cell spans two. Use this to move between a
        :class:`FitReport` (grid columns) and :func:`set_cell` (cell
        indices) on purpose, instead of assuming they coincide — they
        only do in a table with no merged cells.
        """
        trs = list(rows_of(xml[self.start:self.end]))
        if row >= len(trs):
            raise AnchorError(f"table {self.index} has {len(trs)} rows, "
                              f"cannot read row {row}")
        out, c = [], 0
        for tc in cells_of(trs[row].group(0)):
            out.append(c)
            s = _SPAN_RE.search(tc.group(0))
            c += int(s.group(1)) if s else 1
        return out


def _fresh(xml: str, table: Table, what: str) -> None:
    """Refuse a Table whose offsets belong to a different string.

    Editing a table returns a new document and moves every offset after
    it, so a `Table` read before that edit now slices the wrong bytes —
    silently, since the slice is still valid XML-ish text. Cheap to
    check: CPython caches a str's hash after the first call.
    """
    if table.source is not None and table.source != hash(xml):
        raise AnchorError(
            f"{what}: this Table was read from a different version of the "
            "document — an edit since then moved its offsets. Re-read with "
            "read_all()/by_caption() after every edit.")


def read_all(xml: str, *, view: str = FINAL) -> list[Table]:
    """Every table in the document, cells rendered as text.

    `view` picks the side of any tracked changes: ``final`` accepts the
    revisions, ``original`` rejects them.
    """
    transform = view_transform(view)
    out = []
    for i, (start, end) in enumerate(_table_spans(xml)):
        body = transform(xml[start:end])
        rows = []
        for tr in rows_of(body):
            cells = [_cell_text(tc.group(0)) for tc in cells_of(tr.group(0))]
            rows.append(cells)
        out.append(Table(index=i, start=start, end=end, rows=rows,
                         source=hash(xml)))
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

    `col` is a CELL index, matching ``table.rows[row][col]`` — not a grid
    column. In a row with a merged cell the two differ; see
    :meth:`Table.grid_columns`.

    The cell keeps its own run properties: only the first ``w:t`` in the
    cell takes the new text and any others are blanked, so fonts,
    borders and shading survive.
    """
    _fresh(xml, table, "set_cell")
    body = xml[table.start:table.end]
    trs = list(rows_of(body))
    if row >= len(trs):
        raise AnchorError(f"table {table.index} has {len(trs)} rows, "
                          f"cannot set row {row}")
    tr = trs[row]
    tcs = list(cells_of(tr.group(0)))
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


# ------------------------------------------------- rebuild from data --------
# The inverse of to_frame: results tables are regenerated from Stata or
# Python output every revision round, and each paper had its own splice
# script for it. The engine half — write the values, keep the formatting,
# refuse what does not fit, report what moved — is the same everywhere;
# WHICH table and WHICH decimals are the paper's business.


class CellChange(NamedTuple):
    """One cell :func:`update` rewrote.

    `moved` compares the incoming DATA against the old printed value, so
    it sizes the jump before rounding. There is deliberately no
    within-tolerance flag: a numeric cell's text only changes when the
    data crossed a rounding boundary, which by construction exceeds
    :func:`tolerance_for` — so "changed but within tolerance" is a
    near-empty class, and a flag that is almost always true reads as
    information while carrying none. The report being non-empty when you
    expected identical data IS the finding; `moved` tells you which
    jumps deserve reading.
    """

    row: int
    col: int
    old: str
    new: str
    moved: float | None      # |data - old printed value|, None if either
    #                          side holds no number


def _render_value(old: str, value: object) -> str:
    """`value` as this cell prints it.

    A number takes the OLD text's printed shape — decimal places,
    thousands separators, the typographic minus, and any suffix after the
    number (significance stars, ``%``, a bracketed standard error) — so a
    regenerated 0.3171 lands in a cell showing "0.32**" as "0.32**", not
    as a 16-digit float that torpedoes the layout. Strings are written
    verbatim; None empties the cell.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, int | float):
        raise TypeError(f"cell value must be str, number or None, "
                        f"not {type(value).__name__}")
    m = _NUM_RE.match(old.strip())
    if m is None:
        # the old cell shows no number to copy the shape of
        return f"{value:g}"
    shown = m.group(0)
    decimals = len(shown.split(".")[1]) if "." in shown else 0
    comma = "," if "," in shown else ""
    text = f"{value:{comma}.{decimals}f}"
    if "−" in shown:
        text = text.replace("-", "−")
    return text + old.strip()[m.end():]


def update(xml: str, table: Table, rows: Iterable[Sequence[object]], *,
           row0: int = 1, col0: int = 0
           ) -> tuple[str, list[CellChange]]:
    """Rewrite a block of `table` from `rows`, preserving formatting.

    `rows` is anything rectangular — lists of lists, or a pandas
    DataFrame directly (its ``.values`` are taken). The block lands with
    its top-left cell at (`row0`, `col0`), both CELL indices matching
    ``table.rows`` rather than grid columns (:meth:`Table.grid_columns`
    converts); the default writes the data region under a one-row
    header. Each value is rendered by
    :func:`_render_value`, so printed precision, separators and
    significance stars survive a regeneration.

    Refuses what silent code would get wrong: a block that overruns the
    table (a vanished row means the data and the manuscript disagree —
    that is a finding, not something to pad over) and a table containing
    tracked changes (the first ``w:t`` of a revised cell can sit inside
    ``w:ins``, so the write would land inside the revision; update the
    clean build and rebuild the redline instead).

    Returns the new XML and a :class:`CellChange` per cell whose text
    actually changed. An update you expected to be a no-op (same data,
    regenerated) returning a non-empty report is the data and the paper
    disagreeing — read it before shipping.
    """
    values = getattr(rows, "values", None)      # a DataFrame, duck-typed
    if values is not None and hasattr(values, "tolist"):
        rows = values.tolist()
    grid: list[list[object]] = [list(r) for r in rows]
    if not grid:
        raise AnchorError("update: no rows given")

    _fresh(xml, table, "update")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - update the "
            f"clean build and rebuild the redline from it")
    trs = list(rows_of(body))
    if row0 + len(grid) > len(trs):
        raise AnchorError(
            f"block of {len(grid)} rows at row {row0} overruns table "
            f"{table.index}, which has {len(trs)} rows")

    changes: list[CellChange] = []
    edits: list[tuple[int, int, str]] = []      # (start, end) within body
    for i, incoming in enumerate(grid):
        tr = trs[row0 + i]
        tcs = list(cells_of(tr.group(0)))
        if col0 + len(incoming) > len(tcs):
            raise AnchorError(
                f"row {row0 + i} of table {table.index} has {len(tcs)} "
                f"cells; {len(incoming)} values at column {col0} overrun it")
        for j, value in enumerate(incoming):
            tc = tcs[col0 + j]
            old = _cell_text(tc.group(0))
            new = _render_value(old, value)
            if new == old:
                continue
            raw = float(value) if isinstance(value, int | float) \
                else parse_number(new)
            was = parse_number(old)
            moved = abs(raw - was) if raw is not None and was is not None \
                else None
            changes.append(CellChange(row0 + i, col0 + j, old, new, moved))
            edits.append((tr.start() + tc.start(), tr.start() + tc.end(),
                          set_run_text(tc.group(0), new)))

    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], changes


