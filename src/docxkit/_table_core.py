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
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, NamedTuple, overload

from ._xml import (
    PARA_RE,
    element_spans,
    normalize_glyphs,
    set_run_text,
    visible_text,
)
from .errors import AnchorError
from .find import TABLE_LABELS, caption_re
from .revisions import FINAL, _has_revisions, rows_in_view, view_transform

_TR_RE = re.compile(r"<w:tr\b[^>]*(?<!/)>.*?</w:tr>", re.DOTALL)
_TC_RE = re.compile(r"<w:tc>.*?</w:tc>", re.DOTALL)
# a merged cell: structure, which is why it lives here and
# not with the width fitting that also consumes it. `\s*/>`: other
# producers close it ` />` (5,183 in 8 of 2,954 corpus packages), and read
# only as `…"/>` such a merge counted as one column
_SPAN_RE = re.compile(r'<w:gridSpan w:val="(\d+)"\s*/>')
# the vertical half of the same story: a continuation cell carries no
# text, so only the flag distinguishes "empty" from "merged upward"
_VMERGE_RE = re.compile(r'<w:vMerge(?:\s+w:val="(\w+)")?\s*/>')
_GRIDCOL_RE = re.compile(r"<w:gridCol\b")
# a leading signed number, tolerating the typographic minus and separators
_NUM_RE = re.compile(r"[-−+]?\d[\d,  ]*(?:\.\d+)?")
# a picture: the OTHER thing a caption can name. `w:pict` is the VML
# spelling Word still writes for a pasted image.
_IMAGE_RE = re.compile(r"<w:drawing[ >]|<w:pict[ >]")


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
        """The whole span — there are no captures to ask for.

        It refuses a group it has not got rather than handing back the
        element for any index at all. The stub ignored its argument
        until 2026-08-20, and seventeen mutants of `tc.group(0)` across
        this module could not be killed by any test because of it: a
        typo in a caller read as the answer it wanted.
        """
        if index:
            raise IndexError("no such group")
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
    #: Hash of this table's OWN bytes — ``xml[start:end]``. What
    #: `source` cannot say is whether a handle is stale because THIS
    #: table changed or because some other one did, and the second is
    #: harmless: an edit elsewhere leaves these bytes at these offsets.
    #: :func:`_fresh` asks that question and nothing wider — it never
    #: searches for the bytes at another offset, because the content of
    #: a table is what an edit changes, so content is not identity.
    #: `None` alongside `source`.
    body: int | None = None
    #: Which side of the tracked changes :attr:`rows` was read from.
    #:
    #: Carried because a mutator that re-reads the table to check its own
    #: work has to read it the SAME way, and `reorder_rows` did not: it
    #: took the default `final` whatever the caller had asked for, so a
    #: correct reorder of a redline read in `original` failed its own
    #: integrity check with a message about rows being lost.
    view: str = FINAL

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

    def numbers(self, *, decimal: str | None = None
                ) -> list[list[float | None]]:
        """Every cell as :func:`parse_number` reads it.

        A ``1,234``-shaped cell is read with the decimal mark the rest of
        the table uses (:func:`decimal_mark`) unless `decimal` states it.
        """
        _check_decimal(decimal)
        mark = decimal or decimal_mark(c for row in self.rows for c in row)
        return [[parse_number(c, decimal=mark) for c in row]
                for row in self.rows]

    def grid_columns(self, xml: str, row: int) -> list[int]:
        """First grid column of each cell in `row` — the bridge.

        ``[0, 1, 3]`` means the row's third cell starts at grid column 3
        because an earlier cell spans two. Use this to move between a
        :class:`FitReport` (grid columns) and :func:`set_cell` (cell
        indices) on purpose, instead of assuming they coincide — they
        only do in a table with no merged cells.

        Freshness-checked like every mutator. These two readers were the
        only ``(xml, table)`` entry points without the check, which was
        survivable while a handle died on the first edit anywhere and is
        not now that one legitimately outlives an edit to another table:
        a caller carrying a handle through a batch loop would otherwise
        get merge geometry read out of a neighbouring table's bytes, with
        ``rows`` still holding the right text — or a bare ``ValueError``
        from ``matching_close`` with nothing to say about a Table.
        """
        me = _fresh(xml, self, "grid_columns")
        trs = list(rows_of(xml[me.start:me.end]))
        if row >= len(trs):
            raise AnchorError(f"table {self.index} has {len(trs)} rows, "
                              f"cannot read row {row}")
        out, c = [], 0
        for tc in cells_of(trs[row].group(0)):
            out.append(c)
            s = _SPAN_RE.search(tc.group(0))
            c += int(s.group(1)) if s else 1
        return out

    def grid_rows(self, xml: str) -> list[list[str]]:
        """The table as a RECTANGLE: one entry per grid column, merges carried.

        :attr:`rows` is cell-indexed, so a row holding a merged cell is
        shorter than the grid is wide. Anything writing the table out as a
        grid — a CSV compared column-by-column against a statistical
        package's export — needs the rectangle instead, and needs the
        merged cells to say what a reader sees in the columns they cover:
        a horizontal span repeats its text across those columns, and a
        vertical continuation carries its origin's text down, because a
        continuation ``<w:tc>`` holds no text of its own and reading it
        plainly loses the row label entirely.

        Cells still come from the chosen `view`, so this reads a redline
        the same way :func:`read_all` does.

        Freshness-checked, for the reason given on :meth:`grid_columns`.
        """
        me = _fresh(xml, self, "grid_rows")
        body = xml[me.start:me.end]
        width = len(_GRIDCOL_RE.findall(body))
        rows = list(rows_of(body))
        if not width:                       # no tblGrid: take the widest row
            width = max((sum(int(m.group(1)) if (m := _SPAN_RE.search(
                tc.group(0))) else 1 for tc in cells_of(tr.group(0)))
                for tr in rows), default=0)
        carried: dict[int, str] = {}
        out: list[list[str]] = []
        for r, tr in enumerate(rows):
            row = [""] * width
            col = 0
            for tc, cell in zip(cells_of(tr.group(0)), self.rows[r],
                                strict=True):
                s = _SPAN_RE.search(tc.group(0))
                span = int(s.group(1)) if s else 1
                v = _VMERGE_RE.search(tc.group(0))
                text = (cell or carried.get(col, "")
                        if v is not None and v.group(1) != "restart" else cell)
                carried[col] = text
                for i in range(col, min(col + span, width)):
                    row[i] = text
                col += span
            out.append(row)
        return out


def _fresh(xml: str, table: Table, what: str) -> Table:
    """The Table as it stands in `xml`, or a refusal.

    Editing a table returns a new document and moves every offset after
    it, so a `Table` read before that edit now slices the wrong bytes —
    silently, since the slice is still valid XML-ish text. Cheap to
    check: CPython caches a str's hash after the first call.

    **Why a handle survives an edit to ANOTHER table.** The guard used to
    compare a whole-DOCUMENT fingerprint and raise, which made the
    natural batch loop impossible: fetching a caption's two panels and
    styling each raised on the second pass, because editing the LATER
    table invalidated the handle on the EARLIER one — even though nothing
    before it had moved, and even though the loop was written in reverse
    for exactly that reason. Found on Health_Capacity_to_Work,
    2026-08-24. The message ("re-read after every edit") was right and
    still did not prevent it: it reads as *after every edit to THIS
    table*, and the fix people reach for — re-locating once per pass —
    fails the same way.

    So the question asked is not "is the document the same" but **"are
    this table's own bytes still exactly where they were"**. If they are,
    the edit lay elsewhere and this handle still means what it meant; the
    document hash is refreshed and nothing else changes.

    **It deliberately does NOT search for the table's bytes elsewhere**,
    and the first draft of this fix did. Two ways that goes wrong, both
    reproduced against the live tree before this was narrowed:

    * **the edit that creates the staleness also defeats the uniqueness
      check.** Two identical panels; edit one; the OTHER is now the only
      byte-match, so a reused handle silently rewrites the wrong panel.
      Guarding on "exactly one match" cannot see this, because there is
      exactly one match;
    * **a handle from a DIFFERENT document binds.** The whole-document
      hash was the only thing tying a `Table` to the file it was read
      from, and a content search throws that away. The clean-build and
      redline of one manuscript are two strings in one scope; a swapped
      variable was a loud refusal and would have become a silent write.

    Both are the cost of treating content as identity when the content is
    exactly what an edit changes. An in-place check has neither, is O(1)
    rather than O(document), and covers the case the defect was filed
    about — the entry's own words were *re-resolve when the edit provably
    lies after it*, and "the bytes are still here" is that proof.

    A handle whose table MOVED — text inserted above it, an exhibit added
    — is refused, as is one whose own table was rewritten. Both re-read.
    """
    if table.source is None or table.source == hash(xml):
        return table

    if table.body is None:
        # `source` without `body`: a Table assembled by hand from another
        # one's offsets. Nothing was fingerprinted, so the question this
        # function asks cannot be put — and saying "its content changed"
        # would send the reader looking for an edit that never happened.
        raise AnchorError(
            f"{what}: this Table was read from a different version of the "
            "document and carries no fingerprint of its own bytes, so "
            "whether it still means the same table cannot be decided. "
            "Re-read with read_all()/by_caption().")

    if hash(xml[table.start:table.end]) == table.body:
        return replace(table, source=hash(xml))

    raise AnchorError(
        f"{what}: this Table was read from a different version of the "
        "document, and its own bytes are no longer at its offsets — the "
        "edit since then either MOVED this table or rewrote it. A handle "
        "survives an edit to another table only while its own bytes stay "
        "put, which is why a batch loop runs in REVERSE document order. "
        "Re-read with read_all()/by_caption()/tables_after() and call "
        "again.")


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
                         source=hash(xml), body=hash(xml[start:end]),
                         view=view))
    return out


def _table_spans(xml: str) -> list[tuple[int, int]]:
    """(start, end) of every TOP-LEVEL table, nesting respected.

    A non-greedy ``<w:tbl>.*?</w:tbl>`` closes on the first end tag it
    meets, which for a table containing another table is the INNER one —
    the fragment then ends mid-cell. Questionnaires nest tables freely,
    and that is where this first bit.

    Through `element_spans`, which reads the open tag in any spelling: a
    table found as the exact string `<w:tbl>` was no table when its tag
    carried a namespace declaration, as a generated manuscript's did (9
    tables in 1 of 2,954 corpus packages; 2026-09-17).
    """
    return element_spans(xml, "tbl")


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


def _caption_para(xml: str, caption: str) -> re.Match[str] | None:
    """The paragraph this caption NAMES, not the first to mention it.

    A caption OPENS its paragraph, and prose cross-references one at the
    end of a sentence — "…as do the EU and … Table 3." — which is house
    style, so most papers have both. Taking the first paragraph that
    CONTAINS the string takes the prose, and it is 395,000 characters
    ahead of the caption in AFI's `working.docx`: repkit's G4 reported
    "no table under caption 'Table 3.'" on a manuscript that plainly has
    one (2026-08-21).

    The loud half of that is a red gate on a correct paper. The silent
    half is worse and is the same anchor: let the shadowing prose sit
    beside an uncaptioned table and this hands that table back with no
    error at all, which `required=True` cannot fire on and a caller
    reordering rows would then edit.

    The "contains" match is kept as a FALLBACK, because some papers do
    run a caption inline — but only when no paragraph opens with it.
    """
    heads = [m for m in PARA_RE.finditer(xml)
             if visible_text(m.group(0)).strip().startswith(caption)]
    if heads:
        return heads[0]
    return next((m for m in PARA_RE.finditer(xml)
                 if caption in visible_text(m.group(0))), None)


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
    its table, so the table BELOW the caption is preferred. It is not
    evidence on its own: on AFI's `working.docx` Tables 3 and A3 have
    their captions underneath, and "the first table after the caption"
    handed both lookups the 2x2 grid holding Figure 5's panels — a
    `Table`, not a `None`, so `required=True` could not fire and a
    caller reordering rows would have damaged a different exhibit.

    So a candidate is refused when ANOTHER caption stands between it and
    this one: that table is the other caption's, whatever the
    convention. What is left is at most one table on each side, and a
    caption left with only ONE candidate owns it — which takes that
    table out of the reach of every other caption, and is what reads a
    whole run of captions-underneath correctly (:func:`_beside`). Only
    what is still ambiguous after that falls to the convention, and
    there the table below wins. If both sides are ruled out, this raises
    rather than returning a neighbour; a wrong table is worse than no
    table.

    (Figure captions sit above their images too, which is why
    offset-based caption-to-object mapping goes wrong if you assume
    otherwise.)
    """
    para = _caption_para(xml, caption)
    if para is None:
        if required:
            raise AnchorError(f"no paragraph containing caption {caption!r}")
        return None
    found = _beside(xml, para, read_all(xml, view=view))
    if found is None and required:
        raise AnchorError(
            f"caption {caption!r} has no table of its own: the nearest "
            f"table on each side is behind another caption, so it belongs "
            f"to that one")
    return found


def _sides(para: re.Match[str], tables: list[Table],
           captions: list[re.Match[str]], images: list[int],
           *, figure: bool = False) -> list[Table]:
    """The tables one caption paragraph could own, the convention's first.

    At most one on each side: a caption standing BETWEEN a candidate and
    this paragraph means that table is the other caption's, whatever the
    convention says.

    No need to exclude THIS caption from `captions`: both spans below
    are open at the caption paragraph's own offsets, so it cannot rule
    out either candidate. (Pinned as an equivalence, not asserted.)

    A caption whose own exhibit is a PICTURE owns no table at all, which
    is what `images` decides (:func:`_owns_an_image`). Leaving it out
    was a silent wrong answer on every table in a paper, not just on the
    figure: HCW's `working.docx` ends
    `[Table 8][cap Figure 1][image][cap Figure 2][image]...`, and with no
    table under "Figure 1." the table ABOVE it was that caption's only
    candidate — so :func:`_beside`'s propagation, which exists to honour
    a caption that has no choice, handed Table 8's table over. Every
    table caption then shifted one exhibit up: "Table 2." answered with
    Table 1's table and "Table 1." with the 1x2 grid holding equation
    (2). Eight lookups, eight wrong tables, not one of them a `None`.
    """
    below = next((t for t in tables if t.start >= para.end()), None)
    above = next((t for t in reversed(tables) if t.end <= para.start()), None)
    if below is not None and any(para.end() <= m.start() < below.start
                                 for m in captions):
        below = None
    if above is not None and any(above.end <= m.start() < para.start()
                                 for m in captions):
        above = None
    if _owns_an_image(para, below, captions, images, figure=figure):
        return []
    return [t for t in (below, above) if t is not None]


def _owns_an_image(para: re.Match[str], below: Table | None,
                   captions: list[re.Match[str]], images: list[int],
                   *, figure: bool) -> bool:
    """Is the exhibit under this caption a picture rather than a table?

    ``figure`` is the caption's own LABEL, and it is the first question
    asked. A caption reading "Table 1." names a table whatever follows
    it, and without that test ANY later picture could take its table
    away: with the caption UNDERNEATH its table there is no table below
    to rule the picture out, and `<w:pict>` is also what Word writes for
    a horizontal rule, `<w:drawing>` for an inline logo. So an ordinary
    horizontal rule anywhere after the caption returned "this caption
    owns a picture", `by_caption` handed back no table, and with
    ``required=True`` it raised — for a lookup whose table was sitting
    directly above the caption.

    Only the side the CONVENTION names is asked. A picture above a
    caption is as often the previous exhibit's as it is this one's, and
    a figure captioned underneath its image needs no help from here:
    the table above it is either behind another caption already or
    claimed by the caption that sits on top of it, which the
    propagation settles.

    A picture inside a table cannot fool this. It sits after that
    table's start, so the nearer-table test below rules it out — and
    when there is no table below, there is no table for it to be inside.
    """
    if not figure:
        return False
    picture = next((i for i in images if i >= para.end()), None)
    if picture is None or (below is not None and below.start < picture):
        return False
    return not any(para.end() <= m.start() < picture for m in captions)


def _beside(xml: str, para: re.Match[str],
            tables: list[Table]) -> Table | None:
    """The table this caption paragraph owns, or None.

    The refusal is what this is for. A caption BETWEEN the candidate and
    the caption paragraph means the candidate is spoken for — that is
    :func:`_sides`, and it settles the case where something else is
    captioned in between.

    It does not settle a run of exhibits whose captions sit UNDERNEATH
    them, because then nothing stands between a caption and the next
    table down. AFI's `working.docx` reads
    ``[Table 3][cap 3][Table A3][cap A3]``: table A3 stayed a live
    candidate for "Table 3." and the below-the-caption convention then
    preferred it, so `by_caption("Table 3.")` handed back A3 — a
    `Table`, not a `None`, which `required=True` cannot fire on and a
    caller reordering rows would have rewritten.

    So the captions are read TOGETHER. Each one gets the same pair of
    candidates, and a caption with only ONE takes it, which takes that
    table out of every other caption's reach: "Table A3." has no table
    after it, so A3 is its only candidate, so A3 was never "Table 3."'s
    to take — leaving 3, correctly, and the same propagation walks a
    whole run of them from either end.

    What survives that is ambiguous for real — a caption between two
    tables that nothing else claims — and only there does the convention
    decide: the table BELOW wins, which is what every well-formed
    manuscript here looks like.
    """
    # `caption_re` is THE caption definition and it lives in `find`, one
    # layer down — `crossrefs` is this module's facade's SIBLING, and the
    # walk below is three lines. Copying the REGEX would be the drift;
    # walking the paragraphs again is not.
    pattern = caption_re()
    # The caption's LABEL decides whether a picture can be its exhibit,
    # so each one is read once, here, where the text is already in hand.
    # A caption the pattern does not match — the inline fallback below —
    # is read as a table caption: it is the conservative answer, and the
    # figure captions this exists for all match.
    captions: list[re.Match[str]] = []
    figures: dict[tuple[int, int], bool] = {}
    for m in PARA_RE.finditer(xml):
        hit = pattern.match(visible_text(m.group(0)).strip())
        if hit is None:
            continue
        captions.append(m)
        figures[m.span()] = hit.group(1) not in TABLE_LABELS
    images = [m.start() for m in _IMAGE_RE.finditer(xml)]
    options = {m.span(): _sides(m, tables, captions, images,
                                figure=figures[m.span()])
               for m in captions}
    # `_caption_para` falls back to a caption running INLINE in its
    # paragraph, which the pattern above does not match. Such a caption
    # still needs its own candidates here — it just does not get to rule
    # anybody else's out.
    options.setdefault(para.span(),
                       _sides(para, tables, captions, images,
                              figure=figures.get(para.span(), False)))

    # Constraint propagation, and it is the whole fix: assign the
    # captions that have no choice, then look again, because each
    # assignment can leave another caption with no choice either.
    assigned: dict[tuple[int, int], Table] = {}
    taken: set[int] = set()
    while True:
        for span, cands in options.items():
            if span in assigned:
                continue
            free = [t for t in cands if t.start not in taken]
            if len(free) == 1:
                assigned[span] = free[0]
                taken.add(free[0].start)
                break
        else:
            break
    if (mine := assigned.get(para.span())) is not None:
        return mine
    free = [t for t in options[para.span()] if t.start not in taken]
    return free[0] if free else None


def tables_after(xml: str, caption: str, *, view: str = FINAL,
                 count: int = 1) -> list[Table]:
    """The `count` tables following `caption`, in body order.

    One caption can front SEVERAL ``<w:tbl>`` elements — AFI's Table A3
    is a country-rowed table and a 5x4 regression block under one
    caption — and :func:`by_caption` silently addresses the first of
    them. So the count is stated rather than discovered: an exhibit that
    grows or loses a block fails here instead of quietly rewriting half
    of itself, the same bargain as ``table_spans(expect=)``.

    There is no rule for where such a group ENDS that a document can be
    asked: a caption is text, and the next one may be a figure's. The
    caller knows how many blocks the exhibit has; this asserts it.

    **Editing one of these does not spoil the others.** Every handle in
    the list stays usable across edits to the OTHER tables — a stale one
    is re-resolved by identity, so the loop the return type invites works
    as written::

        for t in reversed(tables_after(xml, "Table A3.", count=2)):
            xml, _ = house(xml, t)

    What still invalidates a handle is an edit to ITS OWN table: those
    bytes are then not in the document any longer and there is nothing to
    find. Re-read that one — `tables_after` again, or `read_all` — before
    the next call on it. Two passes over the same table therefore need
    two lookups; two tables in one pass need one.
    """
    if count < 1:
        raise AnchorError(f"tables_after: count must be at least 1, not "
                          f"{count}")
    # The same anchor `by_caption` uses, and for the same reason: prose
    # that ends a sentence with "… Table 3." contains the string and
    # comes first, and this would then count the tables after the PROSE.
    para = _caption_para(xml, caption)
    if para is None:
        raise AnchorError(f"no paragraph containing caption {caption!r}")
    found = [t for t in read_all(xml, view=view) if t.start > para.start()]
    if len(found) < count:
        raise AnchorError(
            f"caption {caption!r} is followed by {len(found)} table(s), "
            f"expected {count}")
    return found[:count]


def row_signature(table: Table, *, skip_header: bool = True
                  ) -> Counter[tuple[str, ...]]:
    """The multiset of a table's rows, as normalized cell tuples.

    Whitespace is collapsed and Word's save-time glyph substitutions are
    folded (the shared table, as everywhere here), so a round-trip
    through Word is not a changed row.

    A COUNTER, not a set: two identical rows are two rows, and a reorder
    that dropped one of them is exactly the kind of loss this exists to
    catch.
    """
    rows = table.rows[1:] if skip_header else table.rows
    return Counter(tuple(" ".join(normalize_glyphs(cell).split())
                         for cell in row) for row in rows)


@dataclass(frozen=True)
class RowsReport:
    """What :func:`rows_preserved` found. Falsy when rows changed."""

    lost: list[tuple[str, ...]]
    """Rows in `before` that `after` does not have — with multiplicity."""
    gained: list[tuple[str, ...]]
    """Rows in `after` that `before` did not have."""
    rows: int
    """How many rows were compared, on the `before` side."""

    @property
    def ok(self) -> bool:
        return not (self.lost or self.gained)

    def __bool__(self) -> bool:
        return self.ok

    def format(self) -> str:
        if self.ok:
            return f"rows preserved: {self.rows} row(s), same multiset"
        out = [(f"{len(self.lost)} row(s) LOST, {len(self.gained)} GAINED "
                f"(of {self.rows} compared)")]
        out += [f"  lost   {row}" for row in self.lost]
        out += [f"  gained {row}" for row in self.gained]
        return "\n".join(out)


def rows_preserved(before: Table, after: Table, *,
                   skip_header: bool = True) -> RowsReport:
    """Did `after` keep exactly `before`'s rows, in any order?

    The question a REORDER raises, and the one a rendered diff cannot
    answer: it reports "rows moved", which is what was asked for, so the
    eye passes over the row whose values slipped a column. Order is
    deliberately ignored — that is the edit being checked — and a cell
    that moved WITHIN its row still shows up, because the tuple changed.

    Reports which rows appeared and vanished rather than a bare False:
    on a 30-row table "these two are not the same" is the whole finding.
    """
    a, b = (row_signature(before, skip_header=skip_header),
            row_signature(after, skip_header=skip_header))
    return RowsReport(lost=sorted((a - b).elements()),
                      gained=sorted((b - a).elements()),
                      rows=sum(a.values()))


_SPACES = " \u00a0"
#: A comma followed by a space ends the number: "12, 13" is a list.
_LIST_COMMA_RE = re.compile(r",[ \u00a0]")


def _leading(text: str) -> str:
    """The number a cell's text starts with, as printed, or ""."""
    m = _NUM_RE.match(text)
    if not m:
        return ""
    shown = m.group(0)
    cut = _LIST_COMMA_RE.search(shown)
    if cut:
        shown = shown[:cut.start()]
    return shown.rstrip("," + _SPACES)


def _comma_role(shown: str) -> str | None:
    """What the comma in a printed number is, read from that number alone.

    ``"decimal"`` (``0,31``, ``12,5``, ``1 234,5``), ``"thousands"``
    (``1,234.5``, ``1,234,567``), ``"ambiguous"`` (``1,234`` — 1234 in an
    English table, 1.234 in a Russian one), or None for no comma.

    A thousands group is exactly three digits behind a head of one to
    three digits that does not start with zero, and it never shares a
    number with space grouping — so anything else with ONE comma is a
    decimal comma.
    """
    core = shown.lstrip("-−+")
    if "," not in core:
        return None
    if "." in core:
        return "thousands"
    head, *tails = core.split(",")
    if len(tails) > 1:
        return "thousands"
    if any(c in head for c in _SPACES):
        return "decimal"
    if (len(tails[0]) != 3 or not 1 <= len(head) <= 3
            or head.startswith("0")):
        return "decimal"
    return "ambiguous"


def decimal_mark(texts: Iterable[str]) -> str | None:
    """The decimal mark a set of cells uses — ``","``, ``"."`` or None.

    What a reader does with ``1,234``: look at the rest of the table. A
    ``0,31`` elsewhere says the commas are decimal; a ``1,234.5`` or a
    ``0.31`` says they are not. The majority decides; no evidence, or a
    tie, is None. Measured over 20,422 tables on 2026-09-23: 119 had an
    ambiguous number settled by a decimal comma beside it, and every one
    of the 70 left unsettled that was sampled was an English count table
    ("143,070") — so None reads as English.
    """
    comma = point = 0
    for text in texts:
        shown = _leading(text.strip())
        role = _comma_role(shown)
        if role == "decimal":
            comma += 1
        elif role == "thousands" or (role is None and "." in shown):
            point += 1
    if comma == point:
        return None
    return "," if comma > point else "."


def _check_decimal(decimal: str | None) -> None:
    if decimal not in (None, ",", "."):
        raise ValueError(f"decimal must be ',', '.' or None, not {decimal!r}")


def _comma_is_decimal(shown: str, decimal: str | None) -> bool:
    role = _comma_role(shown)
    return role == "decimal" or (role == "ambiguous" and decimal == ",")


def parse_number(text: str, *, decimal: str | None = None) -> float | None:
    """Leading numeric value of a cell, or None if it holds no number.

    Handles what these tables actually contain: a typographic minus
    (U+2212), a leading ``+``, thousands separators including the
    non-breaking kind, a trailing ``%``, and significance stars or
    bracketed p-values after the value (``-0.623** [0.038]``).

    A DECIMAL comma is read as one wherever the number itself says so —
    ``0,31`` is 0.31, ``1 234,5`` is 1234.5. It used to be stripped as a
    thousands separator, which made ``0,31`` 31.0 in every Russian table
    (backlog S1, 2026-09-18). Only ``1,234``-shaped numbers cannot tell
    from the string; `decimal` says which mark the table uses (see
    :func:`decimal_mark`), and without it they read as English.
    """
    _check_decimal(decimal)
    shown = _leading(text.strip())
    if not shown:
        return None
    raw = shown.replace("−", "-")
    for space in _SPACES:
        raw = raw.replace(space, "")
    raw = (raw.replace(",", ".") if _comma_is_decimal(shown, decimal)
           else raw.replace(",", ""))
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


def _row_at(table: Table, count: int, index: int, verb: str) -> int:
    """`index` as a row number from the top, negatives from the end.

    `set_row(t, -1, ...)` already meant the last row, because `trs[row]`
    says so; `clone_row(t, -1)` did not, because its splice reads
    ``trs[:index + 1]`` and `-1` makes that `trs[:0]` — the copy landed
    at the TOP of the table, above the header. `clone_row(t, -1,
    count=4)` is the natural spelling of that function's own motivating
    example ("a four-row block at the end") and it silently rewrote the
    head of the table instead.

    So the negative is resolved once, here, and out of range raises an
    `AnchorError` rather than reaching a list index — which the `>=`
    guards this replaces let a negative walk straight past.
    """
    at = index + count if index < 0 else index
    if not 0 <= at < count:
        raise AnchorError(f"table {table.index} has {count} rows, "
                          f"cannot {verb} row {index}")
    return at


def set_cell(xml: str, table: Table, row: int, col: int, text: str) -> str:
    """Rewrite one cell's text, preserving its formatting.

    `col` is a CELL index, matching ``table.rows[row][col]`` — not a grid
    column. In a row with a merged cell the two differ; see
    :meth:`Table.grid_columns`.

    The cell keeps its own run properties: only the first ``w:t`` in the
    cell takes the new text and any others are blanked, so fonts,
    borders and shading survive.
    """
    table = _fresh(xml, table, "set_cell")
    body = xml[table.start:table.end]
    trs = list(rows_of(body))
    row = _row_at(table, len(trs), row, "set")
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


def _rows_replaced(xml: str, table: Table, rows: list[str]) -> str:
    """The document with this table's `w:tr` elements replaced by `rows`.

    One splice for the whole table rather than one per row: every write
    shifts the offsets after it, and a per-row loop over stale spans is
    the shape that has bitten this file before.
    """
    body = xml[table.start:table.end]
    trs = list(rows_of(body))
    if not trs:
        raise AnchorError(f"table {table.index} has no rows to write")
    new_body = (body[:trs[0].start()] + "".join(rows)
                + body[trs[-1].end():])
    return xml[:table.start] + new_body + xml[table.end:]


def reorder_rows(xml: str, table: Table, key: Callable[[list[str]], Any], *,
                 header: int = 1, last: Collection[str] = ()) -> str:
    """Permute a table's data rows by `key`, and PROVE nothing else moved.

    "Apply one country order to Tables 1, 3, 4, 5, A3 and A4" is an
    ordinary referee ask, and it was `w:tr` surgery every time: ~40 lines
    of regex per paper, with the gate written again beside it.

    `key` is called with the row's CELL TEXT — ``key=lambda c:
    order.index(c[0])`` is the usual form. `header` is how many leading
    rows stay put; `last` names the leading cell values that stay at the
    BOTTOM, which is where a total or an "all countries" row lives.

    The gate is the reason this is worth sharing. Row COUNT is preserved
    by any bug that swaps two cells, so it proves nothing; the multiset
    of every row's cells is not, and :func:`rows_preserved` compares it
    before and after. "No value changed, only the order" is then a
    claim rather than a hope.

    **Everything here speaks the table's own `view`.** `key` is called
    with the cell text as the CALLER read it, and the check re-reads the
    result the same way. Both used to take the default `final` whatever
    had been asked for, so a table read with ``view="original"`` — which
    `by_caption` and `tables_after` both offer — was permuted on one
    side of the tracked changes and audited against the other. The
    permutation was correct and the audit said ``2 row(s) LOST, 2
    GAINED``; two cells inside a ``w:ins`` was enough to produce it.

    **A row the view HIDES does not move, and does not stop the sort.**
    A row-level revision — ``w:del`` in ``trPr``, or ``w:ins`` read as
    ``original`` — means the document has one more row than the view
    does, and pairing the two lists by index would move the wrong rows
    while still passing the multiset check below. This refused instead,
    and told the caller to re-read, which reproduces the same mismatch:
    it is a property of the view, not a stale handle. So the lists are
    PAIRED, by :func:`revisions.rows_in_view` — the transform only ever
    drops rows, so its per-row answer is the mapping — and the hidden
    row keeps the slot it has. `header` counts the rows the CALLER can
    see, which is the only reading that survives a deleted row above the
    header.
    """
    table = _fresh(xml, table, "reorder_rows")
    body = xml[table.start:table.end]
    trs = [tr.group(0) for tr in rows_of(body)]
    shown = rows_in_view(body, table.view)
    if len(shown) != len(trs) or sum(shown) != len(table.rows):
        # Not reachable through a row-level revision any more — those
        # are what `shown` accounts for. This is the transform and the
        # row walk disagreeing about what a row is, which is a defect
        # here rather than anything the caller can act on.
        raise AnchorError(
            f"table {table.index} has {len(trs)} rows in the document and "
            f"{len(table.rows)} in the {table.view} view, and they could "
            f"not be paired ({sum(shown)} of the document's rows are in "
            f"that view) — this is a docxkit bug, not a stale handle")
    # Where a MOVABLE row may land: the slots holding a visible row past
    # the header. Everything else — the header, and every row the view
    # hides — stays exactly where it is.
    slots, seen = [], 0
    for i, visible in enumerate(shown):
        if visible:
            if seen >= header:
                slots.append(i)
            seen += 1
    movable, cells = [trs[i] for i in slots], table.rows[header:]
    tail = [i for i, c in enumerate(cells) if c and c[0] in last]
    order = [i for i in range(len(movable)) if i not in tail]
    order.sort(key=lambda i: key(cells[i]))
    rows = list(trs)
    for slot, i in zip(slots, order + tail, strict=True):
        rows[slot] = movable[i]
    # The RAW gate, and it is not the one below: `rows_preserved` reads
    # the view, where a hidden row is not there to be counted, so a row
    # this loop dropped or duplicated would pass it as "a correct sort
    # of the visible rows". Unreachable while the loop above only
    # ASSIGNS — kept because the bug it names (building `rows` from
    # `slots` alone, and losing every hidden row) is one refactor away,
    # and nothing else in this function would see it.
    if sorted(rows) != sorted(trs):    # pragma: no cover - defensive
        raise AnchorError(
            f"reordering table {table.index} did not permute its "
            f"document rows: {len(trs)} in, {len(rows)} out, and the "
            f"multiset differs")
    out = _rows_replaced(xml, table, rows)
    moved = read_all(out, view=table.view)[table.index]
    if not (report := rows_preserved(table, moved, skip_header=False)):
        raise AnchorError(
            f"reordering table {table.index} changed its rows, not just "
            f"their order:\n{report.format()}")
    return out


def clone_row(xml: str, table: Table, index: int, *, count: int = 1) -> str:
    """Copy row `index` `count` times, immediately after it.

    The other half of "add a four-row benchmark block to Table 1": a new
    row has to come from somewhere, and building one from nothing means
    inventing the cell properties — borders, shading, widths, the
    `w:tblHeader` mark — that make it look like the table it joins.
    Copying the row above inherits all of them.

    The copy carries the source row's TEXT too. Fill it with
    :func:`set_row`, which is why that takes a whole row of values: a
    cloned row half-filled is the old numbers under a new label.

    Negative `index` counts from the bottom, so ``clone_row(t, -1,
    count=4)`` is the block above spelled without counting the rows.

    Offsets move, so re-read the table before the next call — the
    freshness guard says so if you forget.
    """
    table = _fresh(xml, table, "clone_row")
    if count < 1:
        raise AnchorError(f"clone_row: count must be at least 1, not {count}")
    body = xml[table.start:table.end]
    trs = [tr.group(0) for tr in rows_of(body)]
    index = _row_at(table, len(trs), index, "clone")
    rows = trs[:index + 1] + [trs[index]] * count + trs[index + 1:]
    return _rows_replaced(xml, table, rows)


def set_row(xml: str, table: Table, row: int,
            values: Sequence[object]) -> str:
    """Write a whole row's cells, keeping each cell's formatting.

    One call per ROW, not per cell, and deliberately: a cloned row holds
    the values it was copied from, so filling three of its four cells
    leaves the fourth reading as the row above — true, plausible, and
    wrong. Passing the row states what every cell now says.

    `None` leaves a cell alone, for the row that legitimately repeats a
    value — and it is the ONLY way to leave one alone, because a short
    sequence is refused rather than zipped off the end. Negative `row`
    counts from the bottom.

    Each cell keeps its own run properties: the text goes into
    the first ``w:t`` and any others are blanked, so a value split
    across runs does not keep its old tail hanging off the new one.
    """
    table = _fresh(xml, table, "set_row")
    body = xml[table.start:table.end]
    trs = list(rows_of(body))
    row = _row_at(table, len(trs), row, "set")
    tr = trs[row].group(0)
    tcs = list(cells_of(tr))
    if len(values) > len(tcs):
        raise AnchorError(
            f"row {row} has {len(tcs)} cells and {len(values)} values were "
            f"given — a merged cell makes a row SHORTER than the grid is "
            f"wide, and Table.grid_columns converts deliberately")
    # And SHORT is the same refusal from the other side: the trailing
    # cells would keep whatever the row was cloned from, which is the
    # half-filled row this function exists to prevent. `None` is the way
    # to leave one alone, and it says so at the call site.
    if len(values) < len(tcs):
        raise AnchorError(
            f"row {row} has {len(tcs)} cells and only {len(values)} "
            f"value(s) were given — the rest would keep the values they "
            f"were cloned from. Pass None for the cells that stay.")
    for tc, value in reversed(list(zip(tcs, values, strict=True))):
        if value is None:
            continue
        tr = (tr[:tc.start()] + set_run_text(tc.group(0), str(value))
              + tr[tc.end():])
    rows = [t.group(0) for t in trs]
    rows[row] = tr
    return _rows_replaced(xml, table, rows)


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


def _render_value(old: str, value: object, *,
                  decimal: str | None = None) -> str:
    """`value` as this cell prints it.

    A number takes the OLD text's printed shape — decimal places and
    decimal mark, thousands separators, the typographic minus, and any
    suffix after the number (significance stars, ``%``, a bracketed
    standard error) — so a regenerated 0.3171 lands in a cell showing
    "0.32**" as "0.32**", not as a 16-digit float that torpedoes the
    layout, and in a cell showing "0,32**" as "0,32**". Strings are
    written verbatim; None empties the cell. `decimal` settles a
    ``1,234``-shaped old value, as in :func:`parse_number`.
    """
    _check_decimal(decimal)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, int | float):
        raise TypeError(f"cell value must be str, number or None, "
                        f"not {type(value).__name__}")
    old = old.strip()
    shown = _leading(old)
    if not shown:
        # the old cell shows no number to copy the shape of
        return f"{value:g}"
    comma_decimal = _comma_is_decimal(shown, decimal)
    mark = "," if comma_decimal else "."
    whole, _, frac = shown.partition(mark)
    decimals = len(frac)
    group = next((c for c in ("," if not comma_decimal else "") + _SPACES
                  if c in whole), "")
    text = f"{value:,.{decimals}f}" if group else f"{value:.{decimals}f}"
    # Python writes "," and "."; swap in the cell's own marks in one pass.
    text = text.translate({ord(","): group, ord("."): mark})
    if "−" in shown:
        text = text.replace("-", "−")
    return text + old[len(shown):]


def update(xml: str, table: Table, rows: Iterable[Sequence[object]], *,
           row0: int = 1, col0: int = 0, decimal: str | None = None
           ) -> tuple[str, list[CellChange]]:
    """Rewrite a block of `table` from `rows`, preserving formatting.

    `rows` is anything rectangular — lists of lists, or a pandas
    DataFrame directly (its ``.values`` are taken). The block lands with
    its top-left cell at (`row0`, `col0`), both CELL indices matching
    ``table.rows`` rather than grid columns (:meth:`Table.grid_columns`
    converts); the default writes the data region under a one-row
    header. Each value is rendered by
    :func:`_render_value`, so printed precision, separators and
    significance stars survive a regeneration — including a DECIMAL
    comma: a Russian cell showing ``0,31`` updated to 0.4 is written
    ``0,40``, not ``0`` as it was until the S1 fix of 2026-09-23. A
    ``1,234``-shaped cell takes the decimal mark the whole table uses
    (:func:`decimal_mark`), or `decimal` when the caller states it.

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

    table = _fresh(xml, table, "update")
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

    _check_decimal(decimal)
    mark = decimal or decimal_mark(
        _cell_text(tc.group(0)) for tr in trs for tc in cells_of(tr.group(0)))
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
            new = _render_value(old, value, decimal=mark)
            if new == old:
                continue
            raw = float(value) if isinstance(value, int | float) \
                else parse_number(new, decimal=mark)
            was = parse_number(old, decimal=mark)
            moved = abs(raw - was) if raw is not None and was is not None \
                else None
            changes.append(CellChange(row0 + i, col0 + j, old, new, moved))
            edits.append((tr.start() + tc.start(), tr.start() + tc.end(),
                          set_run_text(tc.group(0), new)))

    for start, end, replacement in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]
    return xml[:table.start] + body + xml[table.end:], changes


