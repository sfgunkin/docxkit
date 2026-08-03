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

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, overload

from ._xml import PARA_RE, matching_close, set_run_text, visible_text
from .errors import AnchorError
from .revisions import FINAL, _has_revisions, view_transform

__all__ = [
    "CellChange",
    "ColumnFit",
    "FitReport",
    "Table",
    "bottom_border",
    "by_caption",
    "find",
    "fit_columns",
    "parse_number",
    "read_all",
    "set_cell",
    "superscript_stars",
    "to_frame",
    "tolerance_for",
    "update",
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
    transform = view_transform(view)
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
    its top-left cell at (`row0`, `col0`); the default writes the data
    region under a one-row header. Each value is rendered by
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

    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - update the "
            f"clean build and rebuild the redline from it")
    trs = list(_TR_RE.finditer(body))
    if row0 + len(grid) > len(trs):
        raise AnchorError(
            f"block of {len(grid)} rows at row {row0} overruns table "
            f"{table.index}, which has {len(trs)} rows")

    changes: list[CellChange] = []
    edits: list[tuple[int, int, str]] = []      # (start, end) within body
    for i, incoming in enumerate(grid):
        tr = trs[row0 + i]
        tcs = list(_TC_RE.finditer(tr.group(0)))
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


# ------------------------------------------------- column-width fitting ----
# A results table ships with equal-width data columns, but its columns do
# not hold equal content: a coefficient cell carries a sign and up to
# three significance stars ("-0.250***") where its standard-error
# neighbour is a bare number ("0.047"). At equal widths the coefficient
# cells WRAP, doubling their rows' height — and rows per page is set by
# row height. fit_columns measures what each column actually holds and
# re-divides the table's width so numeric content never wraps: each
# column gets what its widest unbreakable content needs, which prices the
# sign and the stars into the coefficient columns and releases the excess
# the standard-error columns were hoarding; any shortfall is absorbed by
# the columns whose text wraps gracefully (the label column).
#
# Widths come from a font-metric model (Times and Helvetica family
# tables, scaled for Arial Narrow / Calibri / Cambria, with size, bold
# and super/subscript factors), padded by `pad` against model error. The
# model is why the result must still be LOOKED AT once in Word or a PDF
# render — it approximates the layout engine, it is not the layout
# engine.

_GRIDCOL_RE = re.compile(r'<w:gridCol w:w="(\d+)"/>')
_RUN_RE = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.DOTALL)
_T_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
_RPR_RE = re.compile(r"<w:r\b[^>]*>(<w:rPr>.*?</w:rPr>)?", re.DOTALL)
_SZ_RE = re.compile(r'<w:sz w:val="(\d+)"/>')
_ASCII_RE = re.compile(r'<w:rFonts[^>]*w:ascii="([^"]+)"')
_SPAN_RE = re.compile(r'<w:gridSpan w:val="(\d+)"/>')
_TCW_RE = re.compile(r'<w:tcW w:w="[^"]*" w:type="\w+"/>')
_BOLD_RE = re.compile(r'<w:b(?: w:val="(?:1|true|on)")?/>')
_VERT_RE = re.compile(r'<w:vertAlign w:val="(?:superscript|subscript)"/>')


def _widths(groups: dict[int, str]) -> dict[str, int]:
    return {ch: w for w, chars in groups.items() for ch in chars}


# Adobe AFM widths in 1/1000 em. Unlisted characters fall back to 600.
_TIMES = _widths({
    250: " ,. ", 180: "'", 200: "|", 278: "/:;\\ijlt", 389: "Js",
    333: "!()-[]`Ifr‘’", 408: '"', 444: "?acez“”",
    469: "^", 480: "{}", 541: "~", 556: "FPS",
    500: "#$*_0123456789bdghknopquvxy–", 564: "+<=>−",
    611: "ELTZ", 667: "BCR", 722: "ADGHKNOQUVXYw", 778: "&m", 833: "%",
    889: "M", 921: "@", 944: "W", 1000: "—",
})
_ARIAL = _widths({
    191: "'", 222: "ijl‘’", 260: "|",
    278: " ,./:;\\ftI[] ", 333: "()-`r“”", 355: '"',
    389: "*", 469: "^", 500: "Jcksvxyz", 334: "{}",
    556: "#$?_0123456789Labdeghnopqu–", 584: "+<=>~−",
    611: "FTZ", 667: "ABESVXY&", 722: "CDHKNRUw", 778: "GOQ",
    833: "Mm", 889: "%", 944: "W", 1000: "—", 1015: "@",
})
# Arial Narrow is a true narrow design, not a geometric scaling of
# Arial: measured from a Word PDF render, its letters run ~0.835 of
# Arial but its digits are 501/1000 em (0.90) — a uniform 0.82 scale
# under-provides every numeric column by ~9%.
_ARIAL_NARROW = {ch: round(w * 0.835) for ch, w in _ARIAL.items()}
_ARIAL_NARROW.update(_widths({
    501: "0123456789", 250: ",.", 284: "-", 300: "()",
    329: "*", 500: "−–",
}))
_FONT_ALIASES: dict[str, tuple[dict[str, int], float]] = {
    "times new roman": (_TIMES, 1.0), "cambria": (_TIMES, 1.02),
    "georgia": (_TIMES, 1.08), "garamond": (_TIMES, 0.92),
    "arial": (_ARIAL, 1.0), "helvetica": (_ARIAL, 1.0),
    "arial narrow": (_ARIAL_NARROW, 1.0), "calibri": (_ARIAL, 0.915),
    "segoe ui": (_ARIAL, 0.98), "tahoma": (_ARIAL, 1.0),
    "verdana": (_ARIAL, 1.10),
}


def _unescape(text: str) -> str:
    for k, v in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(k, v)
    return text


def _cell_extents(tc_xml: str, fallback: tuple[str, int]
                  ) -> tuple[float, float, str]:
    """(hard, full, text) of a cell in dxa.

    `hard` is the widest unbreakable cluster (split on ordinary spaces
    only — a column cannot go below this without ugly mid-word wraps);
    `full` is the widest whole line (give a column this and nothing in
    it wraps at all).
    """
    hard = full = 0.0
    texts: list[str] = []
    for p in PARA_RE.finditer(tc_xml):
        chars: list[tuple[str, float]] = []
        for r in _RUN_RE.finditer(p.group(0)):
            head = _RPR_RE.match(r.group(0))
            rpr = (head.group(1) or "") if head else ""
            font_m = _ASCII_RE.search(rpr)
            sz_m = _SZ_RE.search(rpr)
            font = font_m.group(1) if font_m else fallback[0]
            sz = int(sz_m.group(1)) if sz_m else fallback[1]
            table, scale = _FONT_ALIASES.get(
                font.strip().lower(), (_TIMES, 1.0))
            factor = scale * sz * 10.0 / 1000.0   # sz half-points -> dxa/em
            if _BOLD_RE.search(rpr):
                factor *= 1.05
            if _VERT_RE.search(rpr):
                factor *= 0.65
            for t in _T_RE.finditer(r.group(0)):
                for ch in _unescape(t.group(1)):
                    chars.append((ch, table.get(ch, 600) * factor))
        while chars and chars[0][0] in " \t":
            chars.pop(0)
        while chars and chars[-1][0] in " \t":
            chars.pop()
        line = cluster = 0.0
        for ch, w in chars:
            line += w
            if ch in " \t":
                cluster = 0.0
                continue
            cluster += w
            hard = max(hard, cluster)
            if ch == "/":
                # Word breaks AFTER a slash — "Professional/vocational"
                # wraps gracefully, and the label column may count on
                # it. A hyphen also breaks in Word but is NOT split
                # here: a negative coefficient's sign must never be a
                # licensed break, or the dangling-minus wrap returns.
                cluster = 0.0
        full = max(full, line)
        if chars:
            texts.append("".join(ch for ch, _ in chars))
    return hard, full, " ".join(texts)


def _bump(needs: list[int], cols: list[int], deficit: int) -> None:
    """Grow `needs` over `cols` by `deficit`, proportionally."""
    if deficit <= 0:
        return
    base = sum(needs[c] for c in cols)
    grown = _round_to(deficit, [needs[c] if base else 1 for c in cols])
    for c, extra in zip(cols, grown, strict=True):
        needs[c] += extra


def _round_to(total: int, weights: Sequence[float]) -> list[int]:
    """Integers proportional to `weights` summing exactly to `total`."""
    s = sum(weights)
    if s <= 0:
        raise AnchorError("fit_columns: nothing to apportion")
    raw = [w * total / s for w in weights]
    out = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i],
                   reverse=True)
    for i in range(total - sum(out)):
        out[order[i % len(order)]] += 1
    return out


class ColumnFit(NamedTuple):
    """One column's reallocation: `driver` is the cell text that set
    its minimum (empty for a spacer column, which keeps its width)."""

    old: int
    new: int
    driver: str


class FitReport(NamedTuple):
    """What :func:`fit_columns` did.

    `cramped` means even the unbreakable minima exceed the table width —
    widths were scaled down and mid-word wraps remain. Before reaching
    for a smaller font or fewer columns, check the width itself: a
    table in a LANDSCAPE section fit to the portrait text width reads
    as cramped when it merely got a page's worth less room than it has
    (`margin` is the other lever — Word's default padding across many
    columns adds up to real inches).
    """

    columns: list[ColumnFit]
    total: int
    cramped: bool


def _const(text: str) -> Callable[[re.Match[str]], str]:
    """An ``re`` replacement inserting `text` literally.

    Always the callable form, never the string one: ``re`` expands
    backslash escapes in a replacement string, so a generated ``\\1``
    would land as a control character — a bug this codebase has shipped
    more than once.
    """
    return lambda _: text


def _cell_walk(body: str, n: int) -> Iterable[
        tuple[re.Match[str], re.Match[str], int, int]]:
    """(row, cell, first grid column, span) for every cell in `body`.

    Rows wider than the `n`-column grid are truncated — a malformed
    row's overflow cells are not mapped onto columns that do not exist.
    """
    for tr in _TR_RE.finditer(body):
        c = 0
        for tc in _TC_RE.finditer(tr.group(0)):
            if c >= n:
                break
            s = _SPAN_RE.search(tc.group(0))
            k = int(s.group(1)) if s else 1
            yield tr, tc, c, k
            c += k


def fit_columns(xml: str, table: Table, *, total: int | None = None,
                pad: float = 1.05, margin: int | None = None
                ) -> tuple[str, FitReport]:
    """Re-divide `table`'s width by what each column actually holds.

    Every column gets the width of its widest content (so coefficient
    columns price in their sign and significance stars, and
    standard-error columns give back what equal division wasted); slack
    or shortfall lands on the columns whose text wraps gracefully. Row
    heights then stay single-line, which is what fits the maximum number
    of rows on a page. Wholly empty columns are spacers and keep their
    width.

    `total` overrides the table's width in dxa — needed when the table
    declares itself in pct units; otherwise the current width is kept.
    `margin` rewrites the table's cell side margins (Word's default is
    108 dxa a side, which across a 16-column table is a third of an
    inch of pure padding) — the lever that rescues a wide table the
    default margins leave cramped. The table is rewritten as
    fixed-layout dxa throughout (grid, tblW, every tcW), which is what
    makes Word honor the division. Offsets in other Table objects are
    stale after this; re-read them.

    Check the result visually once (PDF render) — the width model
    approximates Word's layout engine, `pad` covering its error.
    """
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - fit the "
            f"clean build and rebuild the redline from it")
    grid = [int(m.group(1)) for m in _GRIDCOL_RE.finditer(body)]
    if not grid:
        raise AnchorError(f"table {table.index} has no tblGrid")

    side = 2 * margin if margin is not None else _side_margins(body)
    need_h, need_f, driver, filled = _column_needs(body, grid, side, pad)
    if not any(filled):
        raise AnchorError(f"table {table.index} has no cell content to fit")
    if total is None:
        w_m = re.search(r'<w:tblW w:w="(\d+)" w:type="dxa"/>', body)
        total = int(w_m.group(1)) if w_m else sum(grid)

    widths, cramped = _divide(grid, need_h, need_f, filled, total)
    body = _apply_widths(body, widths, total, margin)
    report = FitReport(
        columns=[ColumnFit(old, new, drv)
                 for old, new, drv in zip(grid, widths, driver,
                                          strict=True)],
        total=total, cramped=cramped)
    return xml[:table.start] + body + xml[table.end:], report


def _side_margins(body: str) -> int:
    """Left + right cell margin of the table, in dxa."""
    mar = re.search(r"<w:tblCellMar>.*?</w:tblCellMar>", body, re.DOTALL)

    def one(*names: str) -> int:
        for nm in names:
            e = re.search(rf'<w:{nm} w:w="(\d+)" w:type="dxa"/>',
                          mar.group(0)) if mar else None
            if e:
                return int(e.group(1))
        return 108                       # Word's default cell margin
    return one("left", "start") + one("right", "end")


def _column_needs(body: str, grid: list[int], side: int, pad: float
                  ) -> tuple[list[int], list[int], list[str], list[bool]]:
    """Measure every column: (hard needs, full needs, drivers, filled).

    Needs are dxa including margins and `pad`; a column no single-span
    cell writes into is unfilled (a spacer) and needs nothing.
    """
    n = len(grid)
    fonts = Counter(_ASCII_RE.findall(body))
    sizes = Counter(_SZ_RE.findall(body))
    fallback = (fonts.most_common(1)[0][0] if fonts else "Times New Roman",
                int(sizes.most_common(1)[0][0]) if sizes else 24)

    hard = [0.0] * n
    full = [0.0] * n
    driver = [""] * n
    filled = [False] * n
    spans: list[tuple[int, int, float]] = []
    for _tr, tc, c, k in _cell_walk(body, n):
        h, f, text = _cell_extents(tc.group(0), fallback)
        if not text:
            continue
        if k == 1:
            filled[c] = True
            if h > hard[c]:
                hard[c], driver[c] = h, text
            full[c] = max(full[c], f)
        else:
            spans.append((c, k, h))

    need_h = [math.ceil(hard[c] * pad) + side if filled[c] else 0
              for c in range(n)]
    need_f = [math.ceil(full[c] * pad) + side if filled[c] else 0
              for c in range(n)]
    # A spanning cell is almost always a group header, and a header
    # wraps for one line per TABLE where a body label wraps for one
    # line per ROW — so spans constrain only by their unbreakable
    # minimum, never by their full one-line width. Forcing "Non-violent
    # discipline" onto one line above a coefficient/SE pair was
    # measured to steal ~250 dxa per pair from the label column.
    for c0, k, h in spans:
        cols = [c for c in range(c0, min(c0 + k, n)) if filled[c]]
        if not cols:
            continue
        fixed = sum(grid[c] for c in range(c0, min(c0 + k, n))
                    if not filled[c])
        _bump(need_h, cols,
              math.ceil(h * pad) + side - fixed - sum(need_h[c]
                                                      for c in cols))
    need_f = [max(need_f[c], need_h[c]) for c in range(n)]
    return need_h, need_f, driver, filled


def _divide(grid: list[int], need_h: list[int], need_f: list[int],
            filled: list[bool], total: int) -> tuple[list[int], bool]:
    """Divide `total` over the filled columns; spacers keep their width.

    Full needs when they fit; otherwise the wrap-tolerant columns are
    shaved toward their hard minima; past that everything scales down
    and the division is cramped.
    """
    live = [c for c in range(len(grid)) if filled[c]]
    avail = total - sum(grid[c] for c in range(len(grid)) if not filled[c])
    sum_h = sum(need_h[c] for c in live)
    sum_f = sum(need_f[c] for c in live)
    cramped = False
    if sum_f <= avail:
        alloc = _round_to(avail, [need_f[c] for c in live])
    elif sum_h <= avail:
        room = [need_f[c] - need_h[c] for c in live]
        cut = _round_to(sum_f - avail, [r if sum(room) else 1
                                        for r in room])
        alloc = [need_f[c] - x for c, x in zip(live, cut, strict=True)]
    else:
        cramped = True
        alloc = _round_to(avail, [need_h[c] for c in live])
    widths = list(grid)
    for c, w in zip(live, alloc, strict=True):
        widths[c] = w
    return widths, cramped


def _apply_widths(body: str, widths: list[int], total: int,
                  margin: int | None) -> str:
    """Write the division back: grid, tblW, fixed layout, margins, tcWs."""
    new_grid = "<w:tblGrid>" + "".join(
        f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
    body = re.sub(r"<w:tblGrid>.*?</w:tblGrid>", _const(new_grid), body,
                  count=1, flags=re.DOTALL)
    body = re.sub(r'<w:tblW w:w="[^"]*" w:type="\w+"/>',
                  _const(f'<w:tblW w:w="{total}" w:type="dxa"/>'),
                  body, count=1)
    if "<w:tblLayout" in body:
        body = re.sub(r'<w:tblLayout w:type="\w+"/>',
                      '<w:tblLayout w:type="fixed"/>', body, count=1)
    else:
        pr = re.search(r"<w:tblPr>.*?</w:tblPr>", body, re.DOTALL)
        if pr:
            at = min(pr.group(0).find(t) for t in
                     ("<w:tblCellMar", "<w:tblLook", "</w:tblPr>")
                     if pr.group(0).find(t) != -1)
            body = (body[:pr.start() + at]
                    + '<w:tblLayout w:type="fixed"/>'
                    + body[pr.start() + at:])
    if margin is not None:
        cellmar = (f'<w:tblCellMar>'
                   f'<w:left w:w="{margin}" w:type="dxa"/>'
                   f'<w:right w:w="{margin}" w:type="dxa"/>'
                   f'</w:tblCellMar>')
        if "<w:tblCellMar>" in body:
            body = re.sub(r"<w:tblCellMar>.*?</w:tblCellMar>",
                          _const(cellmar), body, count=1,
                          flags=re.DOTALL)
        else:                       # schema slot: right after tblLayout
            body = body.replace('<w:tblLayout w:type="fixed"/>',
                                '<w:tblLayout w:type="fixed"/>' + cellmar,
                                1)

    edits: list[tuple[int, int, str]] = []
    for tr, tc, c, k in _cell_walk(body, len(widths)):
        tcw = f'<w:tcW w:w="{sum(widths[c:c + k])}" w:type="dxa"/>'
        new_tc, hits = _TCW_RE.subn(_const(tcw), tc.group(0), count=1)
        if not hits:
            if "<w:tcPr>" in new_tc:
                new_tc = new_tc.replace("<w:tcPr>", f"<w:tcPr>{tcw}", 1)
            else:
                new_tc = new_tc.replace(
                    "<w:tc>", f"<w:tc><w:tcPr>{tcw}</w:tcPr>", 1)
        if new_tc != tc.group(0):
            edits.append((tr.start() + tc.start(),
                          tr.start() + tc.end(), new_tc))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return body


# ------------------------------------------------- superscript stars -------

# exactly a number (the shared cell grammar) with trailing stars
_STARRED_CELL_RE = re.compile(rf"^{_NUM_RE.pattern}\*{{1,3}}$")
_RUN_T_RE = re.compile(r"(<w:t[^>]*>)([^<]*)(</w:t>)")


def _run_retext(run_xml: str, text: str) -> str:
    return _RUN_T_RE.sub(lambda m: m.group(1) + text + m.group(3),
                         run_xml, count=1)


def _run_superscripted(run_xml: str) -> str:
    tag = '<w:vertAlign w:val="superscript"/>'
    if "<w:vertAlign" in run_xml:
        return run_xml
    if "<w:rPr>" in run_xml:
        # vertAlign sorts after sz/szCs and before w:lang in the schema
        at = run_xml.find("<w:lang")
        if at == -1:
            at = run_xml.find("</w:rPr>")
        return run_xml[:at] + tag + run_xml[at:]
    m = re.match(r"<w:r\b[^>]*>", run_xml)
    assert m is not None
    return (run_xml[:m.end()] + f"<w:rPr>{tag}</w:rPr>"
            + run_xml[m.end():])


def superscript_stars(xml: str, table: Table) -> tuple[str, int]:
    """Raise the significance stars of `table`'s cells into superscript.

    House style for results tables — and it narrows the coefficient
    columns, because superscript renders at roughly two-thirds size and
    :func:`fit_columns` prices that in. Only cells that are exactly a
    number with trailing stars are touched (a note paragraph explaining
    the stars never matches), the star run clones the number run's
    formatting, and cells whose stars are already superscript are left
    alone, so the pass is idempotent. Returns (xml, cells converted);
    other Table objects' offsets are stale afterwards.
    """
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - convert the "
            f"clean build and rebuild the redline from it")
    count = 0
    edits: list[tuple[int, int, str]] = []
    for tr in _TR_RE.finditer(body):
        for tc in _TC_RE.finditer(tr.group(0)):
            if not _STARRED_CELL_RE.match(_cell_text(tc.group(0))):
                continue
            last = None
            for r in _RUN_RE.finditer(tc.group(0)):
                t = _RUN_T_RE.search(r.group(0))
                if t and t.group(2):
                    last = r
            if last is None:
                continue
            text = _RUN_T_RE.search(last.group(0)).group(2)  # type: ignore[union-attr]
            m = re.match(r"^(.*?)(\*{1,3})$", text)
            if m is None or "<w:vertAlign" in last.group(0):
                continue                 # stars already split and raised
            head, stars = m.group(1), m.group(2)
            star_run = _run_superscripted(_run_retext(last.group(0), stars))
            new = star_run if not head \
                else _run_retext(last.group(0), head) + star_run
            at = tr.start() + tc.start() + last.start()
            edits.append((at, at + len(last.group(0)), new))
            count += 1
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], count


# ------------------------------------------------- closing rule ------------


def bottom_border(xml: str, table: Table, *, val: str = "double",
                  sz: int = 4) -> tuple[str, int]:
    """Rule off `table`'s last row with a `val` bottom border.

    The exhibit convention: a table closes with a double line under its
    final row. Every cell of the last row gets the border (an existing
    bottom edge — usually ``nil`` — is replaced), so the rule runs the
    full width. Returns (xml, cells changed); idempotent once applied.
    """
    body = xml[table.start:table.end]
    trs = list(_TR_RE.finditer(body))
    if not trs:
        raise AnchorError(f"table {table.index} has no rows")
    last = trs[-1]
    edge = f'<w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="auto"/>'
    edits: list[tuple[int, int, str]] = []
    for tc in _TC_RE.finditer(last.group(0)):
        cell = tc.group(0)
        if edge in cell:
            continue
        if "<w:tcBorders>" in cell:
            new, n = re.subn(r"<w:bottom [^>]*/>", _const(edge),
                             cell, count=1)
            if not n:
                b = cell.find("</w:tcBorders>")
                new = cell[:b] + edge + cell[b:]
        elif "<w:tcPr>" in cell:
            # tcBorders sorts before shd/tcMar/vAlign in the tcPr schema
            at = min(p for p in (cell.find("<w:shd"), cell.find("<w:tcMar"),
                                 cell.find("<w:vAlign"),
                                 cell.find("</w:tcPr>")) if p != -1)
            new = (cell[:at] + f"<w:tcBorders>{edge}</w:tcBorders>"
                   + cell[at:])
        else:
            new = cell.replace(
                "<w:tc>",
                f"<w:tc><w:tcPr><w:tcBorders>{edge}</w:tcBorders></w:tcPr>",
                1)
        edits.append((last.start() + tc.start(),
                      last.start() + tc.end(), new))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], len(edits)
