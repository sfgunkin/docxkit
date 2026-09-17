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
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
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
    escape_attr,
    live_properties,
    matching_close,
    own_properties,
    set_para_property,
    set_run_text,
    visible_text,
)
from .edit import replace_in_para
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

# Every property the width model reads is closed `\s*/>`: other producers
# write `<w:sz w:val="20" />`, and of 2,954 corpus packages 32 hold such a
# `w:sz`, 32 a `w:b`, 22 a `w:vertAlign` and 13 a `w:gridCol`. Read only
# as `…"/>`, a size fell back to the table's commonest, a bold or raised
# run measured plain, and a grid read as absent (2026-09-17).
_GRIDCOL_RE = re.compile(r'<w:gridCol w:w="(\d+)"\s*/>')
_RUN_RE = RUN_RE                       # the shared definition
_SZ_RE = re.compile(r'<w:sz w:val="(\d+)"\s*/>')
_ASCII_RE = re.compile(r'<w:rFonts[^>]*w:ascii="([^"]+)"')
# Word writes w:ascii and w:hAnsi together, but a document from another
# producer may state only the latter — and the two cover the same Latin
# text, so reading one and not the other silently drops the run to the
# table's fallback face. Theme fonts and style inheritance are still not
# resolved here; see the module docstring on what this model is.
_HANSI_RE = re.compile(r'<w:rFonts[^>]*w:hAnsi="([^"]+)"')
# Order-free, like `_TBLW_RE` below and for the same reason: 5 of 150
# manuscripts sampled on 2026-09-03 spell `w:type` first, and the
# order-bound spelling saw no width in those cells — so `_set_tc_w`
# wrote a second one beside the one it could not see.
_TCW_RE = re.compile(r"<w:tcW\b[^>]*/>")
_BOLD_RE = re.compile(r'<w:b(?: w:val="(?:1|true|on)")?\s*/>')
_VERT_RE = re.compile(
    r'<w:vertAlign w:val="(?:superscript|subscript)"\s*/>')


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

    "The first match is always its own" holds only while the table HAS
    one. A hand-built fragment need not, and the first `w:tblGrid` in
    the body is then a NESTED table's — reached by everything that asks
    this: `fit_columns` rewrote the inner table's grid, and `house`
    wrote the outer table's width into the inner table's properties and
    reported success. A grid that starts after the first row cannot be
    this table's, because CT_Tbl puts the grid before the rows.
    """
    grid = _TBLGRID_RE.search(body)
    first_row = body.find("<w:tr")
    if grid is not None and first_row != -1 and grid.start() > first_row:
        return None
    return grid


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
    if grid is not None:
        head = body[:grid.start()]
    else:
        # No grid to bound the search, so the first ROW does it: a
        # table's own properties precede its first row, and a nested
        # table can only live inside a cell of one. Unbounded, an outer
        # table with no properties of its own reached the inner table's
        # — the same defect this function exists for, one fragment
        # further out.
        first_row = body.find("<w:tr")
        head = body[:first_row] if first_row != -1 else body
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
        if grid is not None:
            # tblPr sits immediately before the grid — after any range
            # markup, which CT_Tbl allows to precede it.
            at = grid.start()
        else:
            # No grid: before the first row instead, and after the open
            # tag when a fragment has neither. `len(body)` was here, and
            # it appended the properties AFTER the last row — which is
            # not a table, and only a caller that writes the grid first
            # (`fit_columns` does) never reached it.
            first_row = body.find("<w:tr")
            at = first_row if first_row != -1 else body.index(">") + 1
        return body[:at] + f"<w:tblPr>{element}</w:tblPr>" + body[at:]
    start, end, inner = own
    live = live_properties(inner)
    # Taken OUT and put back in its slot, rather than replaced where it
    # stands. Replacing in place cannot repair an element that is in the
    # wrong place — and one release of `_house_width` wrote `w:tblW`
    # ahead of `w:tblStyle` on every table it touched, so the documents
    # needing the repair are exactly the ones a re-run has to fix. For a
    # property already in its slot the removal and the insert cancel.
    while (was := pattern.search(live)) is not None:
        # EVERY copy: two `w:tblW` in one `w:tblPr` is what a writer that
        # could not see the first one leaves behind, and this package
        # shipped one of those. Taking a single copy out then rewrites
        # the table's width with the STALE element still sorting ahead of
        # the new one, which is the reading Word takes.
        inner = inner[:was.start()] + inner[was.end():]
        live = live_properties(inner)
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


def _own_tcpr(cell: str) -> tuple[int, int, str] | None:
    """``(start, end, inner)`` of the cell's OWN ``w:tcPr``, or None.

    CT_Tc puts a cell's properties first, so a ``w:tcPr`` that does
    not open the cell belongs to a table nested inside it.
    """
    m = re.match(r"(<w:tc\b[^>]*>\s*)(<w:tcPr\b[^>]*?(/?)>)", cell)
    if m is None:
        return None
    if m.group(3) == "/":
        return m.start(2), m.end(2), ""
    close = matching_close(cell, m.end(2), "tcPr")
    return m.start(2), close, cell[m.end(2):close - len("</w:tcPr>")]


def _set_tc_w(cell: str, tcw: str) -> str:
    """`cell` with `tcw` as its own width, replacing or creating one.

    Confined to the cell's LIVE properties, like :func:`_set_tbl_pr`.
    The one caller is `fit_columns`, which refuses a table with tracked
    changes in it, so a `w:tcPrChange` snapshot holding an old width
    cannot be reached today — but the guard is a line, and the version
    without it was one caller away from writing into the historical
    record.
    """
    own = _own_tcpr(cell)
    if own is None:
        opening = re.match(r"<w:tc\b[^>]*>", cell)
        at = opening.end() if opening else 0
        return cell[:at] + f"<w:tcPr>{tcw}</w:tcPr>" + cell[at:]
    start, end, inner = own
    hits = list(_TCW_RE.finditer(live_properties(inner)))
    if hits:
        # Back to front, and all of them — see `_set_tbl_pr`. A second
        # `w:tcW` left standing is a column measured to the width it
        # used to have.
        for m in reversed(hits[1:]):
            inner = inner[:m.start()] + inner[m.end():]
        new_inner = inner[:hits[0].start()] + tcw + inner[hits[0].end():]
    else:
        # w:tcW's schema slot: after w:cnfStyle, before the rest
        cnf = re.match(r"<w:cnfStyle\b[^>]*/>", inner)
        at = cnf.end() if cnf else 0
        new_inner = inner[:at] + tcw + inner[at:]
    return cell[:start] + f"<w:tcPr>{new_inner}</w:tcPr>" + cell[end:]


def fit_columns(xml: str, table: Table, *, total: int | None = None,
                pad: float = 1.05, margin: int | None = None,
                pin_stub: bool = False) -> tuple[str, FitReport]:
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

    `pin_stub` gives the FIRST column exactly the width its longest
    entry needs on one line, and divides what is left over the others —
    equally, except where one of them needs more than an equal share.
    Use it for a table whose other columns hold VALUES: a value column
    has a widest number and anything past it is waste, so the room is
    there to give, and a row label broken in two costs a line on every
    data row where a column heading broken in two costs one line once.
    Proportional division cannot express that priority — it hands the
    stub the largest share of the slack in a table with room to spare
    and shaves it below its own need in a table without. Ignored, with
    the ordinary division kept, when pinning would push the other
    columns under their unbreakable minima.

    Check the result visually once (PDF render) — the width model
    approximates Word's layout engine, `pad` covering its error. That
    matters most with `pin_stub`, which spends the whole margin for
    error on `pad` and keeps no accidental cushion.
    """
    table = _fresh(xml, table, "fit_columns")
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
        # Either attribute order: `w:type` first is how 26 of 2,954
        # corpus packages write a dxa width, and a spelling bound to
        # `w:w` first divided their columns over the grid's sum instead.
        w_m = re.search(r'<w:tblW\b(?=[^>]*\bw:type="dxa")[^>]*\bw:w="(\d+)"'
                        r"[^>]*/>",
                        live_properties(own[2])) if own else None
        total = int(w_m.group(1)) if w_m else sum(grid)
    if total <= 0:
        raise AnchorError(
            f"table {table.index}: total={total} - a table width must be "
            f"positive, and a width in dxa is what Word divides")

    pinned = (_divide_pinned(grid, need_h, need_f, filled, total)
              if pin_stub else None)
    widths, cramped = pinned or _divide(grid, need_h, need_f, filled, total)
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
            # either attribute order, as for the table's own width
            e = re.search(rf'<w:{nm}\b(?=[^>]*\bw:type="dxa")'
                          r'[^>]*\bw:w="(\d+)"[^>]*/>',
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


def _water_fill(budget: int, needs: list[int]) -> list[int] | None:
    """`budget` split EQUALLY over `needs`, except a column needing more
    than an equal share takes its need and the rest re-divide.

    None when the needs cannot all be met — the caller then falls back
    to shaving, which is what `_divide` already does.

    Equal shares alone are wrong the moment one column's HEADING is much
    longer than its neighbours': "Percentage Points gained" wants 2,287
    dxa where an equal share is 908, and it would wrap to three lines to
    give six sibling columns width they do not need. Where the columns
    are homogeneous — a table of coefficients, a table of means — every
    need is under the share and this IS an equal division.
    """
    if sum(needs) > budget:
        return None
    alloc = [0] * len(needs)
    live = list(range(len(needs)))
    left = budget
    while live:
        share = left // len(live)
        big = [i for i in live if needs[i] > share]
        if not big:
            # `_round_to` rather than `share` each: the remainder from
            # the integer division has to land somewhere, and dropping
            # it leaves the table narrower than its own tblW.
            for i, w in zip(live, _round_to(left, [1.0] * len(live)),
                            strict=True):
                alloc[i] = w
            return alloc
        for i in big:
            alloc[i] = needs[i]
            left -= needs[i]
            live.remove(i)
    return alloc


def _divide_pinned(grid: list[int], need_h: list[int], need_f: list[int],
                   filled: list[bool], total: int
                   ) -> tuple[list[int], bool] | None:
    """`_divide`, but the STUB column gets exactly its one-line need.

    Returns None when pinning would leave the value columns under their
    unbreakable minima — there the stub cannot be satisfied at all and
    the caller keeps the ordinary division.

    Why the stub goes first: a row label broken in two costs a line on
    EVERY data row, and a column heading broken in two costs one line
    once. Proportional division has no way to express that, so it gave
    the stub the largest share of the slack in a table with room to
    spare (Table A2's stub held 797 dxa it had no use for) and shaved it
    below its own need in a table without (Table 2's stub sat at 1,627
    needing 2,093, and its country names wrapped on twenty rows).
    """
    live = [c for c in range(len(grid)) if filled[c]]
    if len(live) < 2:
        return None
    stub, rest = live[0], live[1:]
    avail = total - sum(grid[c] for c in range(len(grid)) if not filled[c])
    budget = avail - need_f[stub]
    if budget < sum(need_h[c] for c in rest):
        return None
    alloc = _water_fill(budget, [need_f[c] for c in rest])
    if alloc is None:
        # every value column's full need does not fit beside the pinned
        # stub, so shave them from full toward hard — the middle branch
        # of `_divide`, over the reduced budget
        room = [need_f[c] - need_h[c] for c in rest]
        cut = _round_to(sum(need_f[c] for c in rest) - budget,
                        [r if sum(room) else 1 for r in room])
        alloc = [need_f[c] - x for c, x in zip(rest, cut, strict=True)]
    widths = list(grid)
    widths[stub] = need_f[stub]
    for c, w in zip(rest, alloc, strict=True):
        widths[c] = w
    return widths, False


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
        # Through the cell's OWN tcPr, for the reason the comment above
        # gives about the table's: a cell can CONTAIN a table, and a
        # search over the whole cell finds the inner cells' properties.
        # With no width of its own to replace, this wrote the outer
        # column's width over the INNER cell's - 1178 dxa inside a 300
        # dxa grid - and with no properties of its own it put the
        # element inside the nested table's first cell.
        new_tc = _set_tc_w(tc.group(0), tcw)
        if new_tc != tc.group(0):
            edits.append((tr.start() + tc.start(),
                          tr.start() + tc.end(), new_tc))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return body


# ------------------------------------------------------ decimal places ----
# A results table states one precision, and a table that states several is
# reporting its estimator's default rather than a decision. Stata's
# `esttab` writes THREE SIGNIFICANT DIGITS, so one column comes out
# holding 1.660, 0.0277 and 0.00749 — three, four and five decimals — and
# the reader has to re-read the exponent on every line.
#
# Two things make this more than a `format()` call. The significance
# stars are usually their OWN superscript run, so the rewrite has to
# land on the numeric run and leave the run beside it alone; and the
# rounding is a SECOND one, because the exported value is already
# rounded — so the cells sitting exactly on a midpoint are named in the
# report rather than quietly resolved.

#: A cell that is one decimal number: optional bracket or paren, sign,
#: digits with a decimal point, significance stars, closing bracket.
#: The decimal point is REQUIRED — a year, a count and a cluster total
#: are integers and must not be given a fractional part.
_DECIMAL_CELL_RE = re.compile(
    r"^(?P<open>[(\[]?\s*)"
    r"(?P<sign>[-−+]?)"
    r"(?P<num>\d[\d,  ]*\.\d+)"
    r"(?P<tail>\s*\*{0,3}\s*)"
    r"(?P<close>[)\]]?)$")
_GROUPED_RE = re.compile(r"[,  ]")


class DecimalsReport(NamedTuple):
    """What :func:`set_decimals` did.

    `midpoints` names the cells whose printed value sat exactly on the
    rounding midpoint — ``(0.0165)`` asked for three places. The value
    in the document is already rounded, so rounding it again cannot know
    which way the original went, and this is where a double rounding can
    disagree with rounding the true estimate. Check those against the
    estimator if the last digit matters.
    """

    changed: int
    unchanged: int
    midpoints: list[str]


def _regroup(digits: str, sep: str) -> str:
    """`digits` with `sep` every three from the right."""
    out = []
    while len(digits) > 3:
        out.append(digits[-3:])
        digits = digits[:-3]
    out.append(digits)
    return sep.join(reversed(out))


def _to_places(text: str, places: int) -> tuple[str, bool]:
    """`text` at exactly `places` decimals, and whether it sat on a
    midpoint. Quantized as a DECIMAL, never a float: `round(2.675, 2)`
    is 2.67 because the binary value is under the midpoint, and a table
    of estimates is the last place to explain that."""
    sep = next((c for c in text if _GROUPED_RE.match(c)), "")
    plain = _GROUPED_RE.sub("", text)
    frac = plain.split(".")[1]
    midpoint = (len(frac) > places and frac[places] == "5"
                and set(frac[places + 1:]) <= {"0"})
    value = Decimal(plain).quantize(
        Decimal(1).scaleb(-places) if places else Decimal(1),
        rounding=ROUND_HALF_UP)
    out = f"{value:f}"
    if sep:
        whole, _, rest = out.partition(".")
        out = _regroup(whole, sep) + ("." + rest if rest else "")
    return out, midpoint


def set_decimals(xml: str, table: Table, places: int, *,
                 columns: Sequence[int] | None = None
                 ) -> tuple[str, DecimalsReport]:
    """Give every decimal value in `table` exactly `places` decimals.

    A cell is rewritten only if it is a single number that ALREADY
    carries a decimal point, so years, counts, cluster totals and every
    em dash are left as they are. Brackets, parentheses, the sign
    character as written (ASCII hyphen or U+2212) and trailing
    significance stars are all preserved: only the digits are replaced,
    through a run-aware edit, so stars raised to superscript stay in
    their own run.

    `columns` restricts the rewrite to those GRID column indices.

    Idempotent — a table already at `places` comes back unchanged.

    The rounding is HALF UP on the printed value. That is a second
    rounding: what the document holds has already been rounded once by
    whatever wrote it, so a cell sitting exactly on the midpoint cannot
    be resolved from the page. Those cells are named in the report.
    """
    if not 0 <= places <= 10:
        raise AnchorError(f"places must be between 0 and 10, not {places}")
    table = _fresh(xml, table, "set_decimals")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - set the "
            f"decimals on the clean build and rebuild the redline from it")

    wanted = None if columns is None else set(columns)
    changed = unchanged = 0
    midpoints: list[str] = []
    edits: list[tuple[int, int, str]] = []
    grid = _own_grid(body)
    n = len(_GRIDCOL_RE.findall(grid.group(0))) if grid is not None else 0
    for tr, tc, col, _span in _cell_walk(body, n):
        if wanted is not None and col not in wanted:
            continue
        cell = tc.group(0)
        m = _DECIMAL_CELL_RE.match(_cell_text(cell).strip())
        if m is None:
            continue
        new, midpoint = _to_places(m.group("num"), places)
        if midpoint:
            midpoints.append(_cell_text(cell).strip())
        if new == m.group("num"):
            unchanged += 1
            continue
        rebuilt = cell
        for para in PARA_RE.finditer(cell):
            if m.group("num") not in visible_text(para.group(0)):
                continue
            rebuilt = (rebuilt[:para.start()]
                       + replace_in_para(para.group(0), m.group("num"), new)
                       + rebuilt[para.end():])
            break
        if rebuilt != cell:
            changed += 1
            edits.append((tr.start() + tc.start(),
                          tr.start() + tc.end(), rebuilt))
    # Back to front, so an edit never moves the span of one not yet made.
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return (xml[:table.start] + body + xml[table.end:],
            DecimalsReport(changed, unchanged, midpoints))


# ----------------------------------------------------------- regrid -------
# A PHANTOM GRID is a table whose `w:tblGrid` declares far more columns
# than the table has, with every cell spanning a handful of them. It is
# what a paste out of a fixed-width source produces: the grid records
# where the CHARACTERS fell, not where the columns are.
#
# The damage is not the column count, which no reader sees. It is that
# each row then chooses its own spans, so a boundary 24 grid columns in
# on one row is 20 on the next and the two rows' cells do not line up.
# Word renders that exactly as written — one block of rows shifted
# against the block above it, starting at whatever row the spans change.
#
# `fit_columns` cannot repair it: it divides the grid it is given, and a
# phantom grid divided perfectly is still ragged. The grid itself has to
# go, which is what this does — and it is a SEPARATE step because
# collapsing the grid is a judgement about which cells are the same
# column, while fitting widths is arithmetic over their content.

class RegridReport(NamedTuple):
    """What :func:`regrid` did.

    `snapped` names the rows with a different number of cells from the
    canonical row, which had to be mapped onto it — a spanning header is
    the ordinary case and not a fault. `ragged` counts the rows whose
    boundaries did NOT fall on the canonical ones, which is the size of
    the defect: those are the rows a reader sees shifted.
    """

    before: int
    after: int
    widths: list[int]
    ragged: int
    snapped: list[str]


def _row_structure(body: str, n: int) -> list[list[int]]:
    """Every row's cell spans, truncated to the `n`-column grid."""
    out: list[list[int]] = []
    for tr in rows_of(body):
        spans: list[int] = []
        c = 0
        for tc in cells_of(tr.group(0)):
            if c >= n:
                break
            s = _SPAN_RE.search(tc.group(0))
            k = int(s.group(1)) if s else 1
            spans.append(k)
            c += k
        out.append(spans)
    return out


def _canonical(structs: Sequence[Sequence[int]]) -> list[int]:
    """The table's real column structure, as spans over the old grid.

    The modal row wins, and cell COUNT is settled before shape: a table
    whose rows describe the same seven columns with three different span
    patterns IS seven columns, and taking the most frequent SHAPE over
    all rows could return a spanning header's three instead.
    """
    counts = Counter(len(s) for s in structs)
    if not counts:
        raise AnchorError("regrid: the table has no rows")
    top = max(counts.values())
    # A tie on frequency goes to the FINER structure. A table split
    # evenly between six-cell and seven-cell rows is seven columns: the
    # seven can express the six, and the six cannot express the seven.
    width = max(k for k, v in counts.items() if v == top)
    shapes = Counter(tuple(s) for s in structs if len(s) == width)
    return list(shapes.most_common(1)[0][0])


def _snap(spans: Sequence[int], canon_cuts: Sequence[int], k: int
          ) -> list[int]:
    """`spans` re-expressed over `k` canonical columns.

    A row with one cell per canonical column maps straight across —
    cell *i* IS column *i*, whatever widths the old grid gave it. That
    is the case this exists for and it needs no measurement: the defect
    being repaired is precisely that two such rows were drawn against
    different boundaries.

    A row with FEWER cells is a spanning header, and there the old
    boundaries are the only evidence of which columns each cell covers,
    so they are snapped to the nearest canonical cut.
    """
    if len(spans) == k:
        return [1] * k
    if len(spans) > k:
        raise AnchorError(
            f"regrid: a row has {len(spans)} cells but the table has {k} "
            f"columns - no mapping can be inferred without dropping one")
    cuts, acc = [], 0
    for v in spans[:-1]:
        acc += v
        cuts.append(acc)
    out: list[int] = []
    taken = 0
    for i, cut in enumerate(cuts):
        # Leave room for the cells still to come, and at least one
        # column here: a snap that gave two cells the same boundary
        # would produce a zero-width cell, which Word drops.
        lo, hi = taken + 1, k - (len(cuts) - i)
        best = min(range(lo, hi + 1),
                   key=lambda j: (abs(canon_cuts[j - 1] - cut), j))
        out.append(best - taken)
        taken = best
    out.append(k - taken)
    return out


def _set_span(cell: str, span: int) -> str:
    """`cell` with `span` as its own ``w:gridSpan`` (removed when 1).

    Through the cell's LIVE properties only, for the reason
    :func:`_set_tc_w` gives: a cell can contain a table, and a search
    over the whole cell reaches the inner cells' spans.
    """
    own = _own_tcpr(cell)
    element = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
    if own is None:
        if not element:
            return cell
        opening = re.match(r"<w:tc\b[^>]*>", cell)
        at = opening.end() if opening else 0
        return cell[:at] + f"<w:tcPr>{element}</w:tcPr>" + cell[at:]
    start, end, inner = own
    hits = list(_SPAN_RE.finditer(live_properties(inner)))
    if hits:
        # Back to front, and all of them — see `_set_tbl_pr`. A second
        # `w:gridSpan` left standing is a cell still spanning what it
        # used to.
        for m in reversed(hits[1:]):
            inner = inner[:m.start()] + inner[m.end():]
        new_inner = inner[:hits[0].start()] + element + inner[hits[0].end():]
    elif element:
        # w:gridSpan's schema slot: after w:cnfStyle and w:tcW.
        at = 0
        for nm in ("cnfStyle", "tcW"):
            slot = re.compile(rf"<w:{nm}\b[^>]*/>").match(inner, at)
            if slot:
                at = slot.end()
        new_inner = inner[:at] + element + inner[at:]
    else:
        return cell
    return cell[:start] + f"<w:tcPr>{new_inner}</w:tcPr>" + cell[end:]


def regrid(xml: str, table: Table) -> tuple[str, RegridReport]:
    """Collapse `table`'s grid onto the columns it actually has.

    Rewrites ``w:tblGrid`` to one column per real column and restates
    every ``w:gridSpan`` against it, so the same boundary falls in the
    same place on every row. Column WIDTHS are carried over unchanged —
    each new column takes the sum of the old ones it replaces — so pass
    the result to :func:`fit_columns` to size them by content, which is
    almost always the next thing you want.

    Idempotent: a table already on its own grid comes back unchanged,
    with ``ragged == 0``.

    The structure is taken from the table's most common row. A row with
    one cell per column maps across directly; a row with fewer cells is
    read as a spanning header and its old boundaries are snapped to the
    nearest new one. A row with MORE cells than the table has columns is
    refused — collapsing it would have to merge two cells and lose one's
    content.
    """
    table = _fresh(xml, table, "regrid")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes - regrid the "
            f"clean build and rebuild the redline from it")
    own_grid = _own_grid(body)
    grid = ([int(m.group(1)) for m in _GRIDCOL_RE.finditer(own_grid.group(0))]
            if own_grid is not None else [])
    if not grid:
        raise AnchorError(f"table {table.index} has no tblGrid")

    n = len(grid)
    structs = _row_structure(body, n)
    canon = _canonical(structs)
    k = len(canon)

    cuts, widths, acc = [], [], 0
    for v in canon:
        widths.append(sum(grid[acc:acc + v]))
        acc += v
        cuts.append(acc)
    if acc != n:
        # The modal row does not span the grid, so its spans are not
        # reliable evidence of where the columns are, and rewriting the
        # grid from them would move content sideways.
        raise AnchorError(
            f"table {table.index}: its most common row covers {acc} of "
            f"{n} grid columns - the grid and the rows disagree by more "
            f"than a regrid can settle")

    ragged = 0
    snapped: list[str] = []
    new_spans: list[list[int]] = []
    edges = set(cuts)
    for spans, tr in zip(structs, rows_of(body), strict=True):
        # RAGGED is about boundaries, not about shape. A spanning header
        # has a different span tuple from the body and is not ragged at
        # all: its cuts are a SUBSET of the body's, so its cells still
        # line up with the columns beneath them. Comparing tuples
        # instead called every grouped table ragged and rewrote tables
        # that had nothing wrong with them.
        acc, cell_cuts = 0, []
        for v in spans[:-1]:
            acc += v
            cell_cuts.append(acc)
        if not set(cell_cuts) <= edges:
            ragged += 1
        if len(spans) != k:
            label = visible_text(tr.group(0)).strip()[:30]
            snapped.append(label or f"row {len(new_spans)}")
        new_spans.append(_snap(spans, cuts, k))

    report = RegridReport(before=n, after=k, widths=widths, ragged=ragged,
                          snapped=snapped)
    if n == k and ragged == 0:
        return xml, report

    new_grid = "<w:tblGrid>" + "".join(
        f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
    if own_grid is not None:
        body = body[:own_grid.start()] + new_grid + body[own_grid.end():]

    edits: list[tuple[int, int, str]] = []
    for row, tr in zip(new_spans, rows_of(body), strict=True):
        col = 0
        for span, tc in zip(row, cells_of(tr.group(0)), strict=False):
            cell = _set_span(tc.group(0), span)
            cell = _set_tc_w(
                cell, f'<w:tcW w:w="{sum(widths[col:col + span])}" '
                      f'w:type="dxa"/>')
            col += span
            if cell != tc.group(0):
                edits.append((tr.start() + tc.start(),
                              tr.start() + tc.end(), cell))
    # Back to front, so an edit never moves the span of one not yet made.
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], report


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
    table = _fresh(xml, table, "superscript_stars")
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
    table = _fresh(xml, table, "bottom_border")
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
    # The edge already there, in any attribute order or close: asked for
    # the exact string this writes, one spelled otherwise was rewritten
    # and counted as a change on every pass (2026-09-17).
    already = re.compile(rf'<w:bottom\b(?=[^>]*\bw:val="{re.escape(val)}")'
                         rf'(?=[^>]*\bw:sz="{sz}")(?=[^>]*\bw:space="0")'
                         r'(?=[^>]*\bw:color="auto")[^>]*/>')
    edits: list[tuple[int, int, str]] = []
    for tc in cells_of(last.group(0)):
        cell = tc.group(0)
        if already.search(cell):
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




def _set_jc(para: str, val: str) -> str:
    """`para` aligned `val`, in the one place ``CT_PPr`` allows."""
    return set_para_property(para, "jc", f'<w:jc w:val="{val}"/>')


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
    data row down — plus the leading rows that SPAN, and the row that
    follows the last of them.

    That second clause is not a refinement, it is the common case. A
    table whose group heads sit above a row of column names that DOES
    label the stub ("VARIABLES", "Country") satisfies neither the
    empty-first-cell test on the group row nor on the names row, so the
    header came back as 1 and the mid rule was drawn under the group
    heads — ruling the column names off into the data. Measured on a
    manuscript where nine tables had been ruled by hand: the rule below
    reproduces all nine, the empty-first-cell rule alone reproduced
    three.

    A panel row has a label and no values beside it. The summary block
    starts at the first trailing row whose label names a statistic
    rather than a regressor.
    """
    rows = table.rows
    width = max((len(r) for r in rows), default=0)

    def spans(i: int) -> bool:
        """Row `i` is a group head: fewer cells than the table is wide."""
        return len(rows[i]) < width and any(c.strip() for c in rows[i])

    def holds_values(i: int) -> bool:
        """Row `i` is DATA: something beside its label parses as a
        number. A row of column NAMES does not."""
        return any(_NUM_RE.match(c.strip()) for c in rows[i][1:])

    header = 0
    while header < len(rows) and (
            not (rows[header][:1] or [""])[0].strip() or spans(header)):
        header += 1
    # A group head is never the LAST header row — the row of column
    # names it heads is — so a header that stopped on one takes the row
    # below it as well. Unless that row holds VALUES: a lone spanning
    # head over a table whose first data row follows it directly is a
    # one-row header, and swallowing that row would rule off real data.
    if (header and spans(header - 1) and header < len(rows)
            and not holds_values(header)):
        header += 1
    header = max(header, 1)

    # A header row that SPANS carries fewer cells than the table is
    # wide. The last header row gets the full mid rule instead, so it
    # is never a cmidrule row however it is built.
    groups = [i for i in range(header - 1) if spans(i)]

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
    table = _fresh(xml, table, "booktabs")
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
    table = _fresh(xml, table, "drop_blank_rows")
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


# --------------------------------------------------------- house style ---
#
# `booktabs` sets the RULES and stops there. Everything else the house
# style specifies had no home in the toolkit and was re-derived per
# paper: the face at run level AND in each cell's paragraph default so
# an EMPTY cell inherits it, full width with autofit, `cantSplit` on
# every row, `keepNext` on the caption.
#
# What that cost, on LI7 2026-08-15: a new appendix table was built with
# `body.table`'s defaults — whose `tblStyle` is `TableGrid`, a full box
# grid, the exact opposite of the three-line house style — and its
# caption's properties were cloned from the nearest existing table.
# That paper has two generations of table in it, and the nearest one was
# the OLD generation, so "match the neighbouring table" propagated the
# wrong style. Matching a CAPTION turned out not to match a TABLE at
# all. The author caught it by eye.

#: Word stores a point size doubled, and the complex-script mirror has
#: to move with it or a run reads at two sizes in one cell.
_HOUSE_FONT_ATTRS = ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia")
#: The row's `w:trPr`, the slash CAPTURED: an empty `<w:trPr/>` (139 in
#: 16 of 2,954 corpus packages) is still the row's properties, and a
#: pattern that skipped it gave the row a SECOND `w:trPr`. MATCHED at the
#: row's properties slot (`_row_properties_at`), never searched for.
_TRPR_RE = re.compile(r"\s*<w:trPr\b[^>]*?(/?)>")
#: `w:cantSplit` in any spelling, and ON (CT_OnOff). Asked for the exact
#: string `<w:cantSplit/>`, a row closing it ` />` (637 in 5 corpus
#: packages) or stating it OFF got a second one beside it (2026-09-17).
_CANT_SPLIT_ANY_RE = re.compile(r"<w:cantSplit\b[^>]*/>")
_CANT_SPLIT_ON_RE = re.compile(
    r'<w:cantSplit\b(?![^>]*\bw:val="(?:0|false|off)")[^>]*/>')


def _row_properties_at(row: str) -> int:
    """Where `row`'s OWN `w:trPr` sits, or would go.

    CT_Row is ``tblPrEx?, trPr?, tc*``: straight after the open tag, or
    after the row's table-property exceptions when it has them — past the
    WHOLE element, since `w:tblPrEx` holds properties of its own and
    writing past its open tag lands inside it. Word writes one on every
    row whose borders or width differ from the table's, and a `w:trPr` in
    front of one is the order the schema does not allow; the lxml twin is
    `placement._trpr`.

    Asked of the whole row string instead, `w:trPr` and `w:cantSplit`
    answer from a NESTED table's rows whenever the row's own are missing
    (2026-09-17).
    """
    exceptions = own_properties(row, "tblPrEx")
    return exceptions[1] if exceptions is not None else row.index(">") + 1


@dataclass
class HouseReport:
    """What :func:`house` set."""

    runs: int = 0            # cell runs given the face
    paragraphs: int = 0      # cell paragraph defaults given it too
    rows: int = 0            # rows given cantSplit
    width: bool = False      # tblW/tblLayout written
    caption: bool = False    # keepNext added

    def format(self) -> str:
        return (f"house style: {self.runs} run(s) and {self.paragraphs} "
                f"cell paragraph(s) set, {self.rows} row(s) cantSplit"
                + (", full width" if self.width else "")
                + (", caption kept with the table" if self.caption else ""))


def house_rpr(font: str, size: float, *, bold: bool = False) -> str:
    """The house run properties: face on all four attributes, both sizes.

    `w:cs` and `w:eastAsia` are not decoration. A cell holding a
    non-Latin character or a complex script falls back to a different
    face for exactly that character otherwise, which reads as a stray
    glyph in one cell of an otherwise uniform table.
    """
    fonts = " ".join(f'{a}="{escape_attr(font)}"' for a in _HOUSE_FONT_ATTRS)
    half = round(size * 2)
    return (f"<w:rPr>{'<w:b/>' if bold else ''}<w:rFonts {fonts}/>"
            f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/></w:rPr>')


def house_ppr(font: str, size: float) -> str:
    """A cell paragraph's default: no spacing, single line, the face.

    The face belongs HERE as well as on the runs, because an empty cell
    has no run to carry it and would otherwise sit at the document
    default — visible as soon as a column has a gap in it.
    """
    return ('<w:pPr><w:spacing w:after="0" w:line="240" '
            f'w:lineRule="auto"/>{house_rpr(font, size)}</w:pPr>')


def house(xml: str, table: Table, *, font: str = "Arial Narrow",
          size: float = 10, header_bold: bool = True,
          width: bool = True, caption: str | None = None,
          ) -> tuple[str, HouseReport]:
    """Set `table` in the house style: face, width, unbreakable rows.

    Composes with :func:`booktabs`, which draws the rules — run this
    first, re-read the table, then rule it. Neither touches the other's
    settings.

    `caption` is the caption paragraph's text (or a unique part of it):
    it gets ``keepNext``, so the caption never sits alone at the foot of
    the page before its table. Omitted, the caption is left alone.

    A row may carry only ONE ``w:trPr``, and `body.table` already gives
    the header row one for ``tblHeader`` — a second is invalid and
    `lint` reports it, so `cantSplit` MERGES into an existing element
    and creates one only where there is none.

    Refuses a table carrying tracked changes, like every other mutator
    here: style the clean build and rebuild the redline from it.
    """
    table = _fresh(xml, table, "house")
    body = xml[table.start:table.end]
    if _has_revisions(body):
        raise AnchorError(
            f"table {table.index} contains tracked changes — style the "
            f"clean build and rebuild the redline from it")
    report = HouseReport()
    cell_ppr = house_ppr(font, size)
    head_rpr = house_rpr(font, size, bold=True)
    cell_rpr = house_rpr(font, size)

    edits: list[tuple[int, int, str]] = []
    for i, tr in enumerate(rows_of(body)):
        row = tr.group(0)
        rpr = head_rpr if (i == 0 and header_bold) else cell_rpr
        new_row = row
        for tc in reversed(cells_of(row)):
            cell, runs, paras = _house_cell(tc.group(0), rpr, cell_ppr)
            report.runs += runs
            report.paragraphs += paras
            new_row = new_row[:tc.start()] + cell + new_row[tc.end():]
        at = _row_properties_at(new_row)
        m = _TRPR_RE.match(new_row, at)
        if m is not None and not m.group(1):
            shut = new_row.index("</w:trPr>", m.end())
            own = new_row[m.end():shut]
            if not _CANT_SPLIT_ON_RE.search(own):
                new_row = (new_row[:m.end()] + "<w:cantSplit/>"
                           + _CANT_SPLIT_ANY_RE.sub("", own) + new_row[shut:])
                report.rows += 1
        else:                           # none, or an empty `<w:trPr/>`
            new_row = (new_row[:at] + "<w:trPr><w:cantSplit/></w:trPr>"
                       + new_row[at if m is None else m.end():])
            report.rows += 1
        if new_row != row:
            edits.append((tr.start(), tr.end(), new_row))
    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]

    if width:
        body, report.width = _house_width(body)
    out = xml[:table.start] + body + xml[table.end:]
    if caption is not None:
        out, report.caption = _keep_with_table(out, caption)
    return out, report


def _set_properties(element: str, tag: str, wanted: str) -> tuple[str, bool]:
    """Give `element` exactly `wanted` as its own ``w:tag``. Idempotent.

    `own_properties` answers with the INNER text and a span covering the
    whole element, so the comparison and the write read different halves
    of it — comparing against the wrapped form never matches, and this
    would report every run as changed on every run of the pass.
    """
    inner = wanted[wanted.index(">") + 1:wanted.rindex("</")]
    existing = own_properties(element, tag)
    if existing is not None:
        if existing[2] == inner:
            return element, False
        return element[:existing[0]] + wanted + element[existing[1]:], True
    at = element.index(">") + 1
    return element[:at] + wanted + element[at:], True


def _house_cell(tc: str, rpr: str, ppr: str) -> tuple[str, int, int]:
    """One cell's runs and paragraph defaults, set to the house face."""
    runs = paragraphs = 0
    out = tc
    for para in reversed(list(PARA_RE.finditer(tc))):
        new = para.group(0)
        for run in reversed(list(RUN_RE.finditer(new))):
            body, changed = _set_properties(run.group(0), "rPr", rpr)
            runs += changed
            new = new[:run.start()] + body + new[run.end():]
        new, changed = _set_properties(new, "pPr", ppr)
        paragraphs += changed
        out = out[:para.start()] + new + out[para.end():]
    return out, runs, paragraphs


def _house_width(body: str) -> tuple[str, bool]:
    """Full width and autofit, through the table's OWN ordered `tblPr`.

    Laid out from the CONTENT rather than from fixed column widths —
    `fit_columns` is the deliberate opposite, and a paper that wants
    measured widths runs it after this.

    Both properties go in with :func:`_set_tbl_pr`, which `fit_columns`
    has used all along and this path did not. Splicing them at the front
    of `w:tblPr` put `w:tblW` AHEAD of the `w:tblStyle` that CT_TblPr
    requires before it, and Word repairs a table whose properties are
    out of order by dropping the misplaced ones on the next save — so
    the width stopped applying some weeks later with nothing in any
    diff. `hygiene.table_spacing` records the same failure for CT_PPr.

    The old path also wrote into whichever `w:tblPr` came first, which
    is a NESTED table's whenever the outer table has none.
    """
    # LAST property first. `_set_tbl_pr` places an element before the
    # first of the elements that must FOLLOW it, so those have to be in
    # their own slots already — and on a table the previous release
    # wrote, `w:tblLayout` is one of the misplaced ones. Repairing it
    # first gives `w:tblW` a correct anchor to sit before; the other
    # order leaves tblW where it was and reports success.
    out = _set_tbl_pr(body, _TBLLAYOUT_RE, '<w:tblLayout w:type="autofit"/>',
                      _AFTER_TBLLAYOUT)
    out = _set_tbl_pr(out, _TBLW_RE, '<w:tblW w:w="5000" w:type="pct"/>',
                      _AFTER_TBLW)
    return out, out != body


def _keep_with_table(xml: str, caption: str) -> tuple[str, bool]:
    """`keepNext` on the caption paragraph, so it travels with its table.

    Through `_xml.set_para_property`, which knows CT_PPr's order and the
    four shapes this used to get wrong on its own: the flag read out of a
    `w:pPrChange` snapshot, a `w:pStyle` written with a closing tag, a
    `w:keepNext w:val="0"` given a second element beside it, and a
    `<w:pPr/>` written past rather than expanded.
    """
    hits = [m for m in PARA_RE.finditer(xml)
            if caption in visible_text(m.group(0))]
    if len(hits) != 1:
        raise AnchorError(
            f"house: caption {caption[:40]!r} matched {len(hits)} "
            f"paragraphs, need exactly 1")
    para = hits[0].group(0)
    new = set_para_property(para, "keepNext", "<w:keepNext/>")
    if new == para:
        return xml, False
    return xml[:hits[0].start()] + new + xml[hits[0].end():], True
