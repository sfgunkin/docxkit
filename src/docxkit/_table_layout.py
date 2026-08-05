r"""Measuring a table and setting how it looks.

The typography view: column widths fitted to what the cells actually
hold, significance stars raised, a closing rule under the last row. It
imports the :class:`Table` type from :mod:`_table_core` and nothing else
from it — the two halves of `docxkit.tables` share a type, not logic.

Widths come from a font-metric model (Times and Helvetica AFM tables,
scaled for Arial Narrow / Calibri / Cambria, with size, bold and
super/subscript factors), which is why a result must still be LOOKED AT
once in a PDF render: it approximates Word's layout engine rather than
being it.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple

from ._table_core import (
    _NUM_RE,
    _SPAN_RE,
    Table,
    _cell_text,
    _fresh,
    _Span,
    cells_of,
    rows_of,
)
from ._xml import (
    PARA_RE,
    RUN_RE,
    T_PARTS_RE,
    matching_close,
    set_run_text,
)
from .errors import AnchorError
from .revisions import _has_revisions

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
_RUN_RE = RUN_RE                       # the shared definition
_T_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
_RPR_RE = re.compile(r"<w:r\b[^>]*>(<w:rPr>.*?</w:rPr>)?", re.DOTALL)
_SZ_RE = re.compile(r'<w:sz w:val="(\d+)"/>')
_ASCII_RE = re.compile(r'<w:rFonts[^>]*w:ascii="([^"]+)"')
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
        tuple[_Span, _Span, int, int]]:
    """(row, cell, first grid column, span) for every cell in `body`.

    Rows wider than the `n`-column grid are truncated — a malformed
    row's overflow cells are not mapped onto columns that do not exist.
    """
    for tr in rows_of(body):
        c = 0
        for tc in cells_of(tr.group(0)):
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
    _fresh(xml, table, "fit_columns")
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
_RUN_T_RE = T_PARTS_RE                 # the shared definition


def _run_superscripted(run_xml: str) -> str:
    # the caller has already skipped runs carrying a vertAlign, so this
    # only ever sees a plain run
    tag = '<w:vertAlign w:val="superscript"/>'
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
    _fresh(xml, table, "superscript_stars")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - convert the "
            f"clean build and rebuild the redline from it")
    count = 0
    edits: list[tuple[int, int, str]] = []
    for tr in rows_of(body):
        for tc in cells_of(tr.group(0)):
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
            star_run = _run_superscripted(set_run_text(last.group(0), stars))
            new = star_run if not head \
                else set_run_text(last.group(0), head) + star_run
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
    _fresh(xml, table, "bottom_border")
    body = xml[table.start:table.end]
    trs = list(rows_of(body))
    if not trs:
        raise AnchorError(f"table {table.index} has no rows")
    last = trs[-1]
    edge = f'<w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="auto"/>'
    edits: list[tuple[int, int, str]] = []
    for tc in cells_of(last.group(0)):
        cell = tc.group(0)
        if edge in cell:
            continue
        # keep whatever other edges the cell states, replace the bottom
        existing = _EDGE_RE.search(cell)
        inner = ""
        if existing and not existing.group(0).endswith("/>"):
            inner = re.sub(r"<w:bottom [^>]*/>", "",
                           existing.group(0)[len("<w:tcBorders>"):
                                             -len("</w:tcBorders>")])
        new = _set_borders(cell, f"<w:tcBorders>{inner}{edge}</w:tcBorders>")
        edits.append((last.start() + tc.start(),
                      last.start() + tc.end(), new))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], len(edits)


# ------------------------------------------------ three-line (booktabs) ----
# The academic house style: no vertical rules, no box, and horizontal
# rules only where they carry meaning —
#
#   top       a single rule above the header
#   cmidrule  a PARTIAL rule under a spanning group head, covering only
#             that group's columns, so the reader sees what belongs to it
#   mid       a single rule closing the header block
#   panel     a single rule between stacked panels (Kyrgyzstan /
#             Turkmenistan / Uzbekistan) — strict three-line forbids it,
#             but a 48-row table without one is unreadable, and it is
#             ordinary booktabs practice
#   stats     a single rule above the summary block (N, F, clusters)
#   bottom    a DOUBLE rule, this house's variation on \bottomrule
#
# Everything else is cleared, which is most of the work: these tables
# arrived with rules stacked three deep at the top, headers that were
# never closed, and panel rules in some tables but not others.

_SIDES = ("top", "bottom", "left", "right")
#: Everything that follows w:tcBorders in the CT_TcPr sequence. The
#: ones before it — cnfStyle, tcW, gridSpan, hMerge, vMerge — stay put.
_AFTER_BORDERS = ("<w:shd", "<w:noWrap", "<w:tcMar", "<w:textDirection",
                  "<w:tcFitText", "<w:vAlign", "<w:hideMark",
                  "<w:headers", "<w:tcPrChange")

# BOTH forms: an empty <w:tcBorders/> is valid OOXML, and matching
# only the expanded form made the writers insert a SECOND element
# beside it — two tcBorders in one tcPr, which is schema-invalid
# and which neither the write gate (well-formed) nor lint caught.
_EDGE_RE = re.compile(r"<w:tcBorders\b[^>]*/>"
                      r"|<w:tcBorders\b[^>]*>.*?</w:tcBorders>",
                      re.DOTALL)
#: rows whose label marks the summary block rather than an estimate
_STATS_RE = re.compile(
    r"^\s*(?:number of observations|observations|n(?:um)?\.?\s*(?:of\s*)?"
    r"obs|sample size|r-?squared|r²|adj\.?\s*r|f-?stat|first[- ]stage|"
    r"clusters?|oblast clusters|wild p|mean of|log likelihood)\b",
    re.IGNORECASE)


def _edges(spec: dict[str, tuple[str, int]]) -> str:
    """A ``w:tcBorders`` element from ``{side: (val, sz)}``."""
    inner = "".join(
        f'<w:{side} w:val="{val}" w:sz="{sz}" w:space="0" w:color="auto"/>'
        for side in _SIDES if (pair := spec.get(side))
        for val, sz in [pair])
    return f"<w:tcBorders>{inner}</w:tcBorders>"


def _own_properties(cell: str) -> tuple[int, int, str] | None:
    """``(start, end, inner)`` of the cell's OWN ``w:tcPr``, or None.

    ``CT_Tc`` is ``(tcPr?, block-level content)``, so a cell's
    properties sit immediately after its open tag and anything found
    deeper belongs to a NESTED table. Searching the whole cell string
    instead rewrote the nested table's borders and left the outer cell
    unruled. Both forms are recognised: an empty ``<w:tcPr/>`` is valid,
    and treating it as absent prepended a second properties element.
    """
    open_tag = re.match(r"<w:tc\b[^>]*>\s*", cell)
    if open_tag is None:
        return None
    pr = re.compile(r"<w:tcPr\b[^>]*?(/?)>").match(cell, open_tag.end())
    if pr is None:
        return None
    if pr.group(1) == "/":
        return pr.start(), pr.end(), ""          # self-closing: no children
    close = matching_close(cell, pr.end(), "tcPr")
    return pr.start(), close, cell[pr.end():close - len("</w:tcPr>")]


def _set_borders(cell: str, borders: str) -> str:
    """`cell` carrying exactly `borders` in its own properties.

    The single place that knows where a ``w:tcBorders`` belongs in the
    ``tcPr`` schema order — and that the cell in question is the OUTER
    one.
    """
    own = _own_properties(cell)
    if own is None:            # no properties at all: give it some
        m = re.match(r"<w:tc\b[^>]*>", cell)
        at = m.end() if m else 0
        return cell[:at] + f"<w:tcPr>{borders}</w:tcPr>" + cell[at:]
    start, end, inner = own
    if _EDGE_RE.search(inner):
        inner = _EDGE_RE.sub(lambda _: borders, inner, count=1)
    else:
        # CT_TcPr is a SEQUENCE, so tcBorders has to land before every
        # property that follows it and after every one that precedes.
        # Anchoring on only shd/tcMar/vAlign put it after w:noWrap or
        # w:hideMark in a cell carrying neither of those three, and Word
        # repairs a document whose properties are out of order.
        at = min((p for p in (inner.find(t) for t in _AFTER_BORDERS)
                  if p != -1), default=len(inner))
        inner = inner[:at] + borders + inner[at:]
    return cell[:start] + f"<w:tcPr>{inner}</w:tcPr>" + cell[end:]


def _with_edges(cell: str, spec: dict[str, tuple[str, int]]) -> str:
    """`cell` carrying exactly `spec` — every other edge explicitly nil.

    Explicit rather than absent: an omitted edge inherits whatever the
    table style says, and these manuscripts are full of styles that draw
    a box.
    """
    full = {side: spec.get(side, ("nil", 0)) for side in _SIDES}
    return _set_borders(cell, _edges(full))


class BooktabsPlan(NamedTuple):
    """Which rows carry which rule. Inferred, but overridable — a table
    the inference reads wrongly should be stated, not fought."""

    header_rows: int             # leading rows forming the header block
    group_rows: list[int]        # header rows carrying spanning heads
    panel_rows: list[int]        # rows that open a stacked panel
    stats_rows: list[int]        # rows that open a summary block


def plan_booktabs(table: Table) -> BooktabsPlan:
    """Read a table's shape: header block, panels, summary block.

    The header is the run of leading rows with an EMPTY first cell —
    every one of these papers labels its stub column only from the first
    data row down. A panel row has a label and no values beside it. The
    summary block starts at the first trailing row whose label names a
    statistic rather than a regressor.
    """
    rows = table.rows
    header = 0
    while header < len(rows) and not (rows[header][:1] or [""])[0].strip():
        header += 1
    header = max(header, 1)

    # A header row that SPANS carries fewer cells than the table is
    # wide. The last header row gets the full mid rule instead, so it
    # is never a cmidrule row however it is built.
    width = max((len(r) for r in rows), default=0)
    groups = [i for i in range(header - 1)
              if len(rows[i]) < width and any(c.strip() for c in rows[i])]

    def label_of(i: int) -> str:
        return (rows[i][:1] or [""])[0].strip()

    panels, stats = [], []
    for i in range(header, len(rows)):
        label = label_of(i)
        rest = [c for c in rows[i][1:] if c.strip()]
        # a panel opens with a label and no values beside it — but two
        # such rows in a row are a heading and its first panel ("Panel A"
        # then "Kyrgyzstan"), and a rule between them rules off nothing
        if (label and not rest and i != len(rows) - 1
                and not (i > header and not [c for c in rows[i - 1][1:]
                                             if c.strip()]
                         and label_of(i - 1))):
            panels.append(i)
        # every summary block, not just the last: a panelled table
        # repeats N and the cluster count under each panel
        if label and _STATS_RE.match(label) and not (
                i > header and _STATS_RE.match(label_of(i - 1))):
            stats.append(i)
    return BooktabsPlan(header, groups, panels, stats)


def booktabs(xml: str, table: Table, *, plan: BooktabsPlan | None = None,
             rule: int = 4, bottom: str = "double"
             ) -> tuple[str, BooktabsPlan]:
    """Set `table` in three-line academic style.

    Clears every existing rule, then draws only the ones that carry
    meaning (see the note above this function). `bottom` is the house
    variation: a DOUBLE rule closes the table where booktabs proper
    draws a thick single one.

    Pass `plan` to state the shape when :func:`plan_booktabs` reads it
    wrongly — a table whose stub column is filled from the first row, for
    instance, has no empty-labelled header to detect.
    """
    _fresh(xml, table, "booktabs")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - rule the "
            f"clean build and rebuild the redline from it")
    shape = plan or plan_booktabs(table)
    trs = list(rows_of(body))
    if not trs:
        raise AnchorError(f"table {table.index} has no rows")

    edits: list[tuple[int, int, str]] = []
    for i, tr in enumerate(trs):
        cells = list(cells_of(tr.group(0)))
        spanned = _group_columns(cells) if i in shape.group_rows else []
        for j, tc in enumerate(cells):
            spec: dict[str, tuple[str, int]] = {}
            if i == 0:
                spec["top"] = ("single", rule)
            if i == shape.header_rows - 1:
                spec["bottom"] = ("single", rule)
            elif i in shape.group_rows and j in spanned:
                # the cmidrule: only under the cells that span
                spec["bottom"] = ("single", rule)
            if i in shape.panel_rows or i in shape.stats_rows:
                spec["top"] = ("single", rule)
            if i == len(trs) - 1:
                spec["bottom"] = (bottom, rule)
            new = _with_edges(tc.group(0), spec)
            if new != tc.group(0):
                edits.append((tr.start() + tc.start(),
                              tr.start() + tc.end(), new))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], shape


def _group_columns(cells: list[_Span]) -> set[int]:
    """Which cells of a header row actually span a group of columns.

    The stub cell and any empty spacer do not get a cmidrule — a rule
    under an empty cell is a rule under nothing.
    """
    out = set()
    for j, tc in enumerate(cells):
        span = _SPAN_RE.search(tc.group(0))
        if span and int(span.group(1)) > 1 and _cell_text(tc.group(0)):
            out.add(j)
    return out
