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

import html
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
    live_properties,
    matching_close,
    own_properties,
    set_run_text,
    visible_text,
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
_SZ_RE = re.compile(r'<w:sz w:val="(\d+)"/>')
_ASCII_RE = re.compile(r'<w:rFonts[^>]*w:ascii="([^"]+)"')
# Word writes w:ascii and w:hAnsi together, but a document from another
# producer may state only the latter — and the two cover the same Latin
# text, so reading one and not the other silently drops the run to the
# table's fallback face. Theme fonts and style inheritance are still not
# resolved here; see the module docstring on what this model is.
_HANSI_RE = re.compile(r'<w:rFonts[^>]*w:hAnsi="([^"]+)"')
_TCW_RE = re.compile(r'<w:tcW w:w="[^"]*" w:type="\w+"/>')
_BOLD_RE = re.compile(r'<w:b(?: w:val="(?:1|true|on)")?/>')
_VERT_RE = re.compile(r'<w:vertAlign w:val="(?:superscript|subscript)"/>')


_TBLGRID_RE = re.compile(r"<w:tblGrid\b[^>]*>.*?</w:tblGrid>", re.DOTALL)
# `[^>]*` and not `w:w="..." w:type="..."`: XML attribute order carries no
# meaning, and the Corruption and Wages manuscript states
# `<w:tblW w:type="auto" w:w="0"/>`. The order-bound pattern matched
# NOTHING there, so the table kept its auto width while its columns were
# being divided in fixed dxa — the same failure the bookmark patterns in
# `_xml` carry the same warning about.
_TBLW_RE = re.compile(r"<w:tblW\b[^>]*/>")
_TBLLAYOUT_RE = re.compile(r"<w:tblLayout\b[^>]*/>")
_TBLCELLMAR_RE = re.compile(r"<w:tblCellMar\b[^>]*/>"
                            r"|<w:tblCellMar\b[^>]*>.*?</w:tblCellMar>",
                            re.DOTALL)

#: ``CT_TblPr`` is a SEQUENCE, so a property that is ABSENT has to be
#: inserted in its slot rather than appended. Each tuple lists what
#: FOLLOWS the property being written; the same shape as
#: ``_AFTER_BORDERS``, and for the same reason — Word repairs a document
#: whose properties are out of order.
_AFTER_TBLW = ("<w:jc", "<w:tblCellSpacing", "<w:tblInd", "<w:tblBorders",
               "<w:shd", "<w:tblLayout", "<w:tblCellMar", "<w:tblLook",
               "<w:tblCaption", "<w:tblDescription", "<w:tblPrChange")
_AFTER_TBLLAYOUT = ("<w:tblCellMar", "<w:tblLook", "<w:tblCaption",
                    "<w:tblDescription", "<w:tblPrChange")
_AFTER_TBLCELLMAR = ("<w:tblLook", "<w:tblCaption", "<w:tblDescription",
                     "<w:tblPrChange")


def _own_grid(body: str) -> re.Match[str] | None:
    """The table's OWN ``w:tblGrid``.

    ``CT_Tbl`` is ``(tblPr, tblGrid, rows)`` and a nested table can only
    appear inside a CELL, so everything before the first ``w:tblGrid``
    belongs to the outer table and the first match is always its own.

    This is :func:`_table_core.rows_of`'s rule — "a nested table's rows
    are not its rows" — applied to the parts of a table that are not
    rows. They were exempt from it, and a plain scan for ``w:gridCol``
    counted a nested table's columns as this one's: a two-column table
    was rewritten with a four-column grid, whose widths then summed to
    the wrong total and whose extra columns no row had cells for.
    """
    return _TBLGRID_RE.search(body)


def _own_tblpr(body: str) -> tuple[int, int, str] | None:
    """``(start, end, inner)`` of the table's OWN ``w:tblPr``, or None.

    Searched only ahead of the table's own grid, which is what keeps a
    nested table's properties out of reach. Reaching one was not a
    theoretical risk: a table with no ``w:tblLayout`` of its own, holding
    one that had, sent ``fit_columns``' fixed-layout switch and its cell
    margins into the INNER table and left the outer one autofit.

    An empty ``<w:tblPr/>`` reports ``inner == ""`` over the
    self-closing tag, so a caller expands it in place rather than
    writing a second properties element beside it.
    """
    grid = _own_grid(body)
    head = body[:grid.start()] if grid is not None else body
    m = re.search(r"<w:tblPr\b[^>]*?(/?)>", head)
    if m is None:
        return None
    if m.group(1) == "/":
        return m.start(), m.end(), ""
    close = matching_close(head, m.end(), "tblPr")
    return m.start(), close, head[m.end():close - len("</w:tblPr>")]


def _set_tbl_pr(body: str, pattern: re.Pattern[str], element: str,
                after: tuple[str, ...]) -> str:
    """`body` with `element` as the OUTER table's own ``tblPr`` property.

    Replaces the existing property or inserts it in its schema slot, and
    creates the ``w:tblPr`` when the table has none. Confined to the
    table's LIVE properties: ``w:tblPrChange`` holds a snapshot of what a
    tracked change replaced, and writing into that edits the historical
    record while leaving the page as it was.
    """
    own = _own_tblpr(body)
    if own is None:
        grid = _own_grid(body)
        # tblPr sits immediately before the grid — after any range
        # markup, which CT_Tbl allows to precede it.
        at = grid.start() if grid is not None else len(body)
        return body[:at] + f"<w:tblPr>{element}</w:tblPr>" + body[at:]
    start, end, inner = own
    live = live_properties(inner)
    if (was := pattern.search(live)) is not None:
        inner = inner[:was.start()] + element + inner[was.end():]
    else:
        at = min((p for p in (live.find(t) for t in after) if p != -1),
                 default=len(live))
        inner = inner[:at] + element + inner[at:]
    return body[:start] + f"<w:tblPr>{inner}</w:tblPr>" + body[end:]


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
# K and P are 667, as in the Helvetica AFM. Both were wrong here until
# they were measured against Word (2026-08-06): K sat in the 722 group,
# and P was in no group at all so it took the 600 fallback — 10% out in
# each direction. An OMITTED character is the worse failure of the two:
# "!" was missing as well and predicted 600 against a true 278, and
# nothing about the table's shape says which characters it forgot.
_ARIAL = _widths({
    191: "'", 222: "ijl‘’", 260: "|",
    278: " !,./:;\\ftI[] ", 333: "()-`r“”", 355: '"',
    389: "*", 469: "^", 500: "Jcksvxyz", 334: "{}",
    556: "#$?_0123456789Labdeghnopqu–", 584: "+<=>~−",
    611: "FTZ", 667: "ABEKPSVXY&", 722: "CDHNRUw", 778: "GOQ",
    833: "Mm", 889: "%", 944: "W", 1000: "—", 1015: "@",
})
# Arial Narrow IS a uniform 0.820 scaling of Arial: every printable
# ASCII character measures within 0.4% of it in Word, digits exactly
# (456 = 0.820 x 556). The table used to carry 0.835 plus hand-set
# overrides for digits, punctuation and dashes, "measured from a Word
# PDF render" — and every one of those overrides was too wide, digits by
# 9.9%, so numeric columns were bought a tenth more room than they need
# and the label column went short by the same. Do not reintroduce a
# special case here without a `pytest -m word` measurement behind it.
_ARIAL_NARROW = {ch: round(w * 0.820) for ch, w in _ARIAL.items()}
# An aliased face borrows another font's SHAPES and corrects the total
# with one number, so any single string can be a few percent out either
# way; the scale zeroes the MEAN over a corpus of table cells, which is
# what a column's width is actually spent on. Measured in Word and
# stable across 8/9/10/12pt — the model's linearity in size holds, so
# these are constants and not a size curve. Segoe UI is not installed
# here, so it keeps its unverified 0.98.
_FONT_ALIASES: dict[str, tuple[dict[str, int], float]] = {
    "times new roman": (_TIMES, 1.0), "cambria": (_TIMES, 1.05),
    "georgia": (_TIMES, 1.09), "garamond": (_TIMES, 0.956),
    "arial": (_ARIAL, 1.0), "helvetica": (_ARIAL, 1.0),
    "arial narrow": (_ARIAL_NARROW, 1.0), "calibri": (_ARIAL, 0.908),
    "segoe ui": (_ARIAL, 0.98), "tahoma": (_ARIAL, 0.993),
    "verdana": (_ARIAL, 1.145),
}


#: What a run contributes to a line, in document order: text, a hard
#: break, or a tab. Read as one scan rather than as a `w:t` scan, because
#: the BREAKS are what a width model gets wrong when it cannot see them.
_RUN_TOKEN_RE = re.compile(
    r"<w:t\b[^>]*>([^<]*)</w:t>|<w:(br|cr)\b[^>]*/?>|<w:(tab)\b[^>]*/>")

#: A tab in a table cell, as a multiple of the space advance. Word
#: advances to the next stop, which depends on the cell's own tab stops
#: and so is not knowable from the run — this approximates it, the way
#: `pad` approximates the model's error. Under-providing is the direction
#: that wraps a row, so it is deliberately generous.
_TAB_SPACES = 4.0


def _cell_extents(tc_xml: str, fallback: tuple[str, int]
                  ) -> tuple[float, float, str]:
    """(hard, full, text) of a cell in dxa.

    `hard` is the widest unbreakable cluster (split on ordinary spaces
    only — a column cannot go below this without ugly mid-word wraps);
    `full` is the widest whole line (give a column this and nothing in
    it wraps at all).

    A ``w:br`` ends a line exactly as a paragraph mark does. Until it was
    read, a cell holding ``Total<w:br/>expenditure`` measured as the
    single unbreakable cluster "Totalexpenditure" — 45% wider than the
    text it renders — and bought that column room out of the label
    column's, which is the one place the width has to come from.
    """
    hard = full = 0.0
    texts: list[str] = []
    for p in PARA_RE.finditer(tc_xml):
        chars: list[tuple[str, float]] = []
        for r in _RUN_RE.finditer(p.group(0)):
            head = own_properties(r.group(0), "rPr")
            rpr = head[2] if head else ""
            font_m = _ASCII_RE.search(rpr) or _HANSI_RE.search(rpr)
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
            for tok in _RUN_TOKEN_RE.finditer(r.group(0)):
                if tok.group(1) is not None:
                    # html.unescape, not a five-entity table of our own:
                    # the local copy left `&#x2013;` as eight characters
                    # and measured an en dash 79% too wide. It is also
                    # what `visible_text` reads the same text with, and
                    # two answers to "what does this cell say" is the
                    # drift R1 exists to stop.
                    for ch in html.unescape(tok.group(1)):
                        chars.append((ch, table.get(ch, 600) * factor))
                elif tok.group(2):
                    chars.append(("\n", 0.0))
                else:
                    chars.append(("\t", table.get(" ", 250) * factor
                                  * _TAB_SPACES))
        while chars and chars[0][0] in " \t":
            chars.pop(0)
        while chars and chars[-1][0] in " \t":
            chars.pop()
        line = cluster = 0.0
        for ch, w in chars:
            if ch == "\n":            # a hard break closes the line
                full = max(full, line)
                line = cluster = 0.0
                continue
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
            # the driver is quoted back to a reader, so a break reads as
            # the space it renders as rather than fusing two words
            texts.append("".join(" " if ch == "\n" else ch
                                 for ch, _ in chars))
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
    own_grid = _own_grid(body)
    grid = ([int(m.group(1)) for m in _GRIDCOL_RE.finditer(own_grid.group(0))]
            if own_grid is not None else [])
    if not grid:
        raise AnchorError(f"table {table.index} has no tblGrid")

    side = 2 * margin if margin is not None else _side_margins(body)
    need_h, need_f, driver, filled = _column_needs(body, grid, side, pad)
    if not any(filled):
        raise AnchorError(f"table {table.index} has no cell content to fit")
    if total is None:
        own = _own_tblpr(body)
        w_m = re.search(r'<w:tblW w:w="(\d+)" w:type="dxa"/>',
                        live_properties(own[2])) if own else None
        total = int(w_m.group(1)) if w_m else sum(grid)
    if total <= 0:
        raise AnchorError(
            f"table {table.index}: total={total} - a table width must be "
            f"positive, and a width in dxa is what Word divides")

    widths, cramped = _divide(grid, need_h, need_f, filled, total)
    body = _apply_widths(body, widths, total, margin)
    report = FitReport(
        columns=[ColumnFit(old, new, drv)
                 for old, new, drv in zip(grid, widths, driver,
                                          strict=True)],
        total=total, cramped=cramped)
    return xml[:table.start] + body + xml[table.end:], report


def _side_margins(body: str) -> int:
    """Left + right cell margin of the table, in dxa.

    Read from the table's OWN properties: a table that states no margins
    while containing one that does used to be measured with the INNER
    table's, and every column was then fitted around a padding figure
    belonging to a different table.
    """
    own = _own_tblpr(body)
    mar = _TBLCELLMAR_RE.search(live_properties(own[2])) if own else None

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
    fonts = Counter(_ASCII_RE.findall(body) or _HANSI_RE.findall(body))
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
    # Spacer columns keep their width unconditionally, so they can eat the
    # whole table. Past that `_round_to` apportions a NEGATIVE total and
    # every filled column is written as a negative w:w — which is not a
    # narrow table but invalid OOXML (ST_TwipsMeasure is unsigned), and
    # Word repairs the document rather than laying it out.
    if avail <= 0:
        raise AnchorError(
            f"fit_columns: the spacer columns hold {total - avail} dxa of a "
            f"{total} dxa table, leaving nothing for the {len(live)} "
            f"column(s) with content - widen the table, or pass a total= "
            f"that matches the section's text width")
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
    grid = _own_grid(body)
    if grid is not None:
        body = body[:grid.start()] + new_grid + body[grid.end():]
    # Each of these goes through the table's OWN tblPr. A `re.sub` over
    # the whole body wrote into a NESTED table whenever the outer one
    # lacked the property being set — and the tblW substitution, having
    # nothing to replace, simply did nothing, so a table that declared no
    # width was left without the one this docstring promises.
    body = _set_tbl_pr(body, _TBLW_RE,
                       f'<w:tblW w:w="{total}" w:type="dxa"/>', _AFTER_TBLW)
    body = _set_tbl_pr(body, _TBLLAYOUT_RE, '<w:tblLayout w:type="fixed"/>',
                       _AFTER_TBLLAYOUT)
    if margin is not None:
        cellmar = (f'<w:tblCellMar>'
                   f'<w:left w:w="{margin}" w:type="dxa"/>'
                   f'<w:right w:w="{margin}" w:type="dxa"/>'
                   f'</w:tblCellMar>')
        body = _set_tbl_pr(body, _TBLCELLMAR_RE, cellmar, _AFTER_TBLCELLMAR)

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
    own = own_properties(run_xml, "rPr")
    if own is not None:
        start, end, inner = own
        # vertAlign sorts after sz/szCs and before w:lang in the schema.
        # Offsets are measured INSIDE the run's own properties: a tracked
        # formatting change nests a snapshot of the old rPr here, and
        # searching the whole run put the tag in that historical record.
        live = live_properties(inner)
        at = live.find("<w:lang")
        if at == -1:
            at = len(live)
        body = inner[:at] + tag + inner[at:]
        return run_xml[:start] + f"<w:rPr>{body}</w:rPr>" + run_xml[end:]
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
    the stars never matches), and the star run clones the number run's
    formatting. Returns (xml, cells converted); other Table objects'
    offsets are stale afterwards.

    A star run that ALREADY states a vertical alignment is left as it is
    — which is what makes the pass idempotent, that being the case this
    is for, and which also leaves a SUBSCRIPT one alone. Wider than
    "already superscript" on purpose: :func:`_run_superscripted` writes a
    ``w:vertAlign`` rather than reconciling one, so the skip is what
    guarantees it never meets a run carrying its own.
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
            own = own_properties(last.group(0), "rPr")
            raised = own is not None and "<w:vertAlign" in live_properties(
                own[2])
            if m is None or raised:
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
    _check_rule(val, sz, "bottom_border")
    _fresh(xml, table, "bottom_border")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - rule the "
            f"clean build and rebuild the redline from it")
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

#: ``ST_Border``, the members a manuscript actually rules with. The check
#: is not pedantry about the enumeration: `val` is interpolated straight
#: into an attribute, so one carrying a quote closes it early and the
#: result is a document Word calls unreadable. The write gate refuses to
#: ship that, but it refuses several hundred lines away from the call
#: that caused it — this says which argument was wrong.
_BORDER_VALUES = frozenset({
    "nil", "none", "single", "thick", "double", "dotted", "dashed",
    "dotDash", "dotDotDash", "triple", "wave", "dashSmallGap",
    "dashDotStroked", "threeDEmboss", "threeDEngrave", "outset", "inset",
})


def _check_rule(val: str, sz: int, where: str) -> None:
    """Refuse a border this house cannot draw, at the call that asked."""
    if val not in _BORDER_VALUES:
        raise AnchorError(
            f"{where}: {val!r} is not a border style - use one of "
            f"{', '.join(sorted(_BORDER_VALUES))}")
    # ST_EighthPointMeasure: Word draws 2..96 eighths of a point and
    # clamps outside it, so a number out here is a caller's mistake
    # rather than a hairline rule.
    if not 0 <= sz <= 96:
        raise AnchorError(
            f"{where}: sz={sz} is outside Word's 0-96 eighths of a point")
#: A tracked FORMATTING change: `<w:tcPrChange>` holds a snapshot of the
#: properties as they were. Groups: open tag, content, close tag — the
#: content is masked so a search cannot reach into the past, while the
#: tags stay visible so the schema anchor still finds them.
_CHANGE_RE = re.compile(r"(<w:\w+Change\b[^>]*>)(.*?)(</w:\w+Change>)",
                        re.DOTALL)

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


_JC_RE = re.compile(r"<w:jc\b[^>]*/>")
#: Everything that follows w:jc in the CT_PPr sequence. Alignment is a
#: PARAGRAPH property even inside a table, so this is the pPr order, not
#: the tcPr one.
_AFTER_JC = ("<w:textDirection", "<w:textAlignment", "<w:textboxTightWrap",
             "<w:outlineLvl", "<w:divId", "<w:cnfStyle", "<w:rPr",
             "<w:sectPr", "<w:pPrChange")


def _set_jc(para: str, val: str) -> str:
    """`para` aligned `val`, in the one place ``CT_PPr`` allows."""
    own = own_properties(para, "pPr")
    if own is None:
        m = re.match(r"<w:p\b[^>]*>", para)
        if m is None:
            return para
        return (para[:m.end()] + f'<w:pPr><w:jc w:val="{val}"/></w:pPr>'
                + para[m.end():])
    start, end, inner = own
    live = live_properties(inner)
    tag = f'<w:jc w:val="{val}"/>'
    if (was := _JC_RE.search(live)) is not None:
        inner = inner[:was.start()] + tag + inner[was.end():]
    else:
        at = min((p for p in (live.find(t) for t in _AFTER_JC) if p != -1),
                 default=len(live))
        inner = inner[:at] + tag + inner[at:]
    return para[:start] + f"<w:pPr>{inner}</w:pPr>" + para[end:]


def _align_cell(tc: str, val: str) -> str:
    """Every paragraph in the cell aligned `val`."""
    out, at = [], 0
    for m in PARA_RE.finditer(tc):
        out.append(tc[at:m.start()])
        out.append(_set_jc(m.group(0), val))
        at = m.end()
    out.append(tc[at:])
    return "".join(out)


def _alignment(align: str | Sequence[str], columns: int) -> list[str]:
    """Per-GRID-column alignment, the last value repeating.

    So ``("left", "center")`` is the house convention — stub column
    left, every number column centred — however many columns there are.
    """
    vals = [align] if isinstance(align, str) else list(align)
    if not vals:
        raise AnchorError("booktabs: align= is empty")
    bad = [v for v in vals if v not in _JC_VALUES]
    if bad:
        raise AnchorError(
            f"booktabs: align={bad} - use {sorted(_JC_VALUES)}")
    return [vals[min(i, len(vals) - 1)] for i in range(columns)]


_JC_VALUES = frozenset({"left", "center", "right", "both", "start", "end"})


def _edges(spec: dict[str, tuple[str, int]]) -> str:
    """A ``w:tcBorders`` element from ``{side: (val, sz)}``."""
    inner = "".join(
        f'<w:{side} w:val="{val}" w:sz="{sz}" w:space="0" w:color="auto"/>'
        for side in _SIDES if (pair := spec.get(side))
        for val, sz in [pair])
    return f"<w:tcBorders>{inner}</w:tcBorders>"


def _own_properties(cell: str) -> tuple[int, int, str] | None:
    """``(start, end, inner)`` of the cell's OWN ``w:tcPr``, or None.

    ``CT_Tc`` is ``(tcPr?, block-level content)``, so a cell's properties
    sit immediately after its open tag and anything found deeper belongs
    to a NESTED table — the shared rule, and the shared helper.
    """
    return own_properties(cell, "tcPr")


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
    # Word records a property change as a snapshot of the OLD properties
    # NESTED inside the new ones, so a w:tcPr can contain a whole second
    # w:tcPr with its own borders. Mask those before looking: the search
    # found the historical rule, rewrote it, and left the live cell bare.
    masked = _CHANGE_RE.sub(
        lambda m: m.group(1) + "\x01" * len(m.group(2)) + m.group(3), inner)
    hit = _EDGE_RE.search(masked)
    if hit is not None:
        inner = inner[:hit.start()] + borders + inner[hit.end():]
    else:
        # CT_TcPr is a SEQUENCE, so tcBorders has to land before every
        # property that follows it and after every one that precedes.
        # Anchoring on only shd/tcMar/vAlign put it after w:noWrap or
        # w:hideMark in a cell carrying neither of those three, and Word
        # repairs a document whose properties are out of order.
        at = min((p for p in (masked.find(t) for t in _AFTER_BORDERS)
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
             rule: int = 4, bottom: str = "double",
             align: str | Sequence[str] | None = None
             ) -> tuple[str, BooktabsPlan]:
    """Set `table` in three-line academic style.

    Clears every existing rule, then draws only the ones that carry
    meaning (see the note above this function). `bottom` is the house
    variation: a DOUBLE rule closes the table where booktabs proper
    draws a thick single one.

    Pass `plan` to state the shape when :func:`plan_booktabs` reads it
    wrongly — a table whose stub column is filled from the first row, for
    instance, has no empty-labelled header to detect.

    `align` sets column alignment, which the rules alone do not: a
    three-line table with left-aligned numerics is the usual next
    complaint. One value applies to every column; a sequence gives them
    per column with the LAST repeating, so ``align=("left", "center")``
    is the house convention — stub column left, every number column
    centred — whatever the width. Omitted, alignment is left alone.

    Columns are GRID columns, so a spanning header takes the alignment
    of the column it starts in rather than of its position in the row;
    those two only coincide in a table with no merged cells.
    """
    _check_rule(bottom, rule, "booktabs")
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
    jc = (_alignment(align, body.count("<w:gridCol") or len(table.rows[0]))
          if align is not None else None)

    edits: list[tuple[int, int, str]] = []
    for i, tr in enumerate(trs):
        cells = list(cells_of(tr.group(0)))
        spanned = _group_columns(cells) if i in shape.group_rows else []
        columns = table.grid_columns(xml, i) if jc else []
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
            if jc is not None and j < len(columns):
                new = _align_cell(new, jc[min(columns[j], len(jc) - 1)])
            if new != tc.group(0):
                edits.append((tr.start() + tc.start(),
                              tr.start() + tc.end(), new))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], shape


#: What makes a textless row content anyway. An image, a shape or an
#: embedded object renders nothing into `visible_text`, and a row holding
#: one is not a spacer — this is the table-level form of the rule that a
#: run with a `w:drawing` and no `w:t` is not an empty run.
_ROW_CONTENT = ("<w:drawing", "<w:pict", "<w:object", "<w:sdt")


def drop_blank_rows(xml: str, table: Table) -> tuple[str, list[int]]:
    """Remove a table's empty separator rows; say where the rules go now.

    A table typed in Word separates its blocks with a BLANK ROW, because
    it has no rules to separate them with. Set in three-line style that
    row is both redundant and wrong: the panel rule already marks the
    boundary, and a blank row above it opens a gap that rules off
    nothing. Every table in these papers that reads as panelled — see
    :func:`booktabs` — closes its blocks with a rule and no blank row.

    Returns the document with those rows gone, and the row indices IN THE
    TABLE AS RETURNED at which a panel now opens, ready to hand to
    ``BooktabsPlan.panel_rows``. Two are deliberately not in that list: a
    blank row that TRAILS the table opens nothing, and one at the very
    top would name row 0, which already carries the top rule.

    A row is blank only when it renders nothing at all. A row whose cells
    hold an image, a shape or an embedded object carries no text and is
    not a spacer, so it stays — the same rule that keeps a `w:drawing`
    run from being swept up as an empty run.
    """
    _fresh(xml, table, "drop_blank_rows")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - drop the rows "
            f"in the clean build and rebuild the redline from it")
    trs = list(rows_of(body))
    blank = [i for i, tr in enumerate(trs)
             if not visible_text(tr.group(0)).strip()
             and not any(tag in tr.group(0) for tag in _ROW_CONTENT)]
    if not blank:
        return xml, []
    if len(blank) == len(trs):
        raise AnchorError(f"table {table.index} is entirely blank rows")

    gone = set(blank)
    after = {i: n for n, i in enumerate(i for i in range(len(trs))
                                        if i not in gone)}
    panels = set()
    for b in blank:
        successor = next((j for j in range(b + 1, len(trs)) if j not in gone),
                         None)
        if successor is not None and after[successor] > 0:
            panels.add(after[successor])

    for i in sorted(blank, reverse=True):
        body = body[:trs[i].start()] + body[trs[i].end():]
    return xml[:table.start] + body + xml[table.end:], sorted(panels)


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
