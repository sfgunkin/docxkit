"""Where a table sits: next to what mentions it, and whole on one page.

Two jobs that pull against each other. A table belongs beside the text that
discusses it, and it belongs entire on one sheet — and the second is decided by
a renderer, not by the XML. Nothing in a `.docx` says where a page ends.

So this module does the first in XML and hands the second to Word:

* **anchor** — the block (caption, table, its notes) moves to just after the
  paragraph that first mentions it. That is a physical reorder, and it must be
  a CLEAN edit: Word's `CompareDocuments` serialises a moved block as
  `w:moveFrom`/`w:moveTo` and emits the table TWICE, once under each, with no
  revision marking the duplicate. Measured on DSI's §6: 27 tables in, 28 out,
  and `accept` and `reject` both left 28. `tracked.build` refuses that redline
  since `4480971`, which is the check, not the workaround.
* **fit** — every row gets `w:cantSplit` and every row but the last gets
  `keepNext`, with `keepNext` on the caption too. Word then carries the whole
  block to the next sheet rather than breaking it. This is what Word is for;
  moving the block further down the file to chase a page boundary would be
  guessing at a layout only the renderer knows.
* **oversized** — a table taller than the text column cannot be kept together
  at all. It gets a page break before it, so it starts on a fresh sheet and
  splits as late as possible, and its header row is marked to repeat.

**The renderer is a callback, and optional.** Without one, the anchoring and
the keep-together properties are applied and the report says so. With one, the
result is measured: each table's caption sheet, its last sheet, whether it
split, and how far it drifted from the sheet its mention is on. Everything the
report calls a defect was seen on a rendered page.

**The paper's vocabulary stays with the paper.** «Таблица 5» and "Table 5" are
the same idea in different manuscripts, so `caption` and `mention` are patterns
the caller supplies. The defaults recognise both, and nothing here knows which
language it is reading.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from lxml import etree

from ._xml import DOCUMENT, PPR_ORDER
from .errors import PackageError

# THE exhibit definition, from one layer down: which caption owns which
# body, on either side, with the notes and hoisted bookmarks that travel
# with it. `NOTE` lived here and is re-exported; `exhibit_block` is that
# engine asked about one caption. What a MARKER is comes from there too:
# this module kept a list of its own, and the two disagreed.
from .exhibits import NOTE, exhibits, is_body, is_end_marker, is_marker

# THE caption definition, from one layer down: `crossrefs` classifies by
# the same regex and is this module's SIBLING, which the layering gate
# refuses — and rightly, since a second spelling here is the drift that
# file records having had three times.
from .find import caption_re

__all__ = [
    "CAPTION",
    "CAPTION_AFTER_PT",
    "GAP_PT",
    "MENTION",
    "NOTE",
    "Block",
    "FitFinding",
    "FitReport",
    "PackageError",
    "Placement",
    "PlacementReport",
    "audit",
    "exhibit_block",
    "keep_together",
    "own_page",
    "place",
    "space_block",
]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: a caption OPENS its paragraph — «Таблица 5. …» / "Table 5. …"
CAPTION = re.compile(
    r"^\s*(?:Таблица|Табл\.|Table|Tab\.)\s*(\d+)\s*\.", re.IGNORECASE)
#: a mention appears anywhere in prose, in any case — «в таблице 5», "Table 5"
MENTION = re.compile(r"(?:таблиц\w*|table)\s*(\d+)", re.IGNORECASE)
#: the gap below a table block, in points — after the last note, or before the
#: paragraph that resumes when the table has no note
GAP_PT = 8.0
#: the gap below a caption, in points
CAPTION_AFTER_PT = 2.0

_PPR_RANK = {name: i for i, name in enumerate(PPR_ORDER)}

#: `CT_TrPrBase`'s children, and the three `CT_TrPr` appends after them.
#:
#: The base is an unbounded CHOICE, so the order among its own children is
#: free; what the extension fixes is that `w:ins`, `w:del` and
#: `w:trPrChange` follow every one of them. This module wrote the revision
#: mark FIRST — `['ins', 'cantSplit']` on every row it marked — which is
#: that sequence backwards.
#:
#: Word repairs it rather than refusing it, which is why no gate here ever
#: said anything: measured through Word automation on 2026-09-16, a row
#: written `['ins', 'cantSplit']` still reads as a tracked insertion
#: (`Revisions.Count` 1), still honours `cantSplit`
#: (`AllowBreakAcrossPages` false), and comes back out of Word as
#: `['cantSplit', 'ins']`. A repair performed by one consumer is not a
#: licence to emit the file: it happens only once Word has opened and
#: saved it, and every other reader of the package sees the invalid order.
#:
#: The home for this is beside `_xml.PPR_ORDER`, with the order tables the
#: other writers share. It is here because this is the only module in the
#: package that writes a `w:trPr` child today — and PRIVATE because of
#: that: published from `placement`, the name would have to be WITHDRAWN
#: from the public surface when it moves, which breaks a caller where an
#: internal rename does not.
_TRPR_ORDER = (
    "cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter",
    "cantSplit", "trHeight", "tblHeader", "tblCellSpacing", "jc", "hidden",
    "ins", "del", "trPrChange",
)
_TRPR_RANK = {name: i for i, name in enumerate(_TRPR_ORDER)}

#: which schema order governs the children of a properties element
_RANKS = {"pPr": _PPR_RANK, "trPr": _TRPR_RANK}


def _twips(pt: float) -> str:
    """Word measures paragraph spacing in twentieths of a point."""
    return str(round(pt * 20))


@dataclass
class Placement:
    """What happened to one table, and what the render said about it."""
    number: int
    caption: str
    anchor_text: str = ""
    moved: bool = False
    kept_together: bool = False
    spaced: bool = False
    own_page: bool = False
    caption_sheet: int | None = None
    last_sheet: int | None = None
    mention_sheet: int | None = None

    @property
    def split(self) -> bool:
        return (self.caption_sheet is not None and self.last_sheet is not None
                and self.last_sheet != self.caption_sheet)

    @property
    def unmeasured(self) -> bool:
        """The caption was found on the page and the table's end was not.

        A third state, because `split` has only two and a `None`
        `last_sheet` falls into the wrong one: not split, therefore
        whole, therefore no escalation to `own_page` — and `rendered`
        stays True, which is the report's own claim that the fit WAS
        measured. The check watched a proxy and the proxy agreed.
        """
        return self.caption_sheet is not None and self.last_sheet is None

    @property
    def drift(self) -> int | None:
        """Sheets between the mention and the table. None if not rendered."""
        if self.mention_sheet is None or self.caption_sheet is None:
            return None
        return self.caption_sheet - self.mention_sheet


@dataclass
class PlacementReport:
    placements: list[Placement] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    rendered: bool = False

    def format(self) -> str:
        n = self.placements
        head = (f"{len(n)} table(s): {sum(p.moved for p in n)} moved, "
                f"{sum(p.kept_together for p in n)} kept together, "
                f"{sum(p.spaced for p in n)} spaced, "
                f"{sum(p.own_page for p in n)} given their own page")
        lines = [head]
        if not self.rendered:
            # ...and the PROBLEMS either way. They used to be printed
            # only under a render, and half of them cannot come from
            # one: a table nothing mentions, a block that carries a
            # section break and a move that would cross a boundary are
            # all decided in the XML. A caller that printed this report
            # without a renderer was told the fit was unverified and
            # nothing else.
            lines.append("  not rendered — fit is unverified")
        else:
            for p in self.placements:
                where = (f"sheet {p.caption_sheet}" if p.caption_sheet
                         else "not found")
                state = ("split" if p.split else
                         "END NOT FOUND" if p.unmeasured else "whole")
                drift = "" if p.drift is None else f", drift {p.drift:+d}"
                lines.append(f"  table {p.number}: {where}, {state}{drift}")
        return "\n".join(lines + [f"  ! {x}" for x in self.problems])


def _body(parts: dict[str, bytes]) -> etree._Element:
    if DOCUMENT not in parts:
        raise PackageError("no word/document.xml in these parts")
    root = etree.fromstring(parts[DOCUMENT])
    body = root.find(W + "body")
    if body is None:
        raise PackageError("word/document.xml has no w:body")
    return body


def _text(el: etree._Element) -> str:
    return "".join(t.text or "" for t in el.iter(W + "t"))


def _row_text(row: etree._Element) -> str:
    """A table row as the PAGE reads it: cells separated.

    `_text` joins every `w:t` under an element with nothing between
    them, which is right for a paragraph and wrong across cells. A row
    of three came out
    `'Social connectednessNussbaum's Affiliati'` while the render — where
    those are separate table cells — reads
    `'Social connectedness Nussbaum's Affiliat'`. `_sheet_of` collapses
    runs of whitespace on both sides but cannot insert a separator that
    is not there, so the needle never matched and `last_sheet` came back
    None on every table with columns.

    A single-column table has no cell boundary to lose, which is why the
    render path looked like it worked: boxes measured, and every real
    paper table skipped the measurement in silence.

    Matching has been whitespace-free since `_flat`, so the separator no
    longer decides whether a row is found. It still decides where the
    forty-character probe is cut.
    """
    return " ".join(_text(tc) for tc in row.findall(W + "tc"))


# MARKERS — body children that carry no content of their own — are
# `exhibits.is_marker`, and the ones that CLOSE something
# `exhibits.is_end_marker`. This module had its own list of ten tags,
# written when a `bookmarkEnd` between a caption and its table hid the
# exhibit (1 placement to 0, `audit` tables 1 to 0, while the exhibit list
# still named the caption). The list fixed the ten and left the rest: a
# body-level `w:proofErr` did the same thing again, and `_next_content`
# stopped at one and took it for what keeps two tables apart.


def _closes_inside(kids: list[etree._Element], start: int, at: int) -> bool:
    """Is `kids[at]` an end marker whose start lies inside the block?

    `exhibits._paired_end`, which this deliberately agrees with. An end
    marker under a block is the block's own only when what it closes
    opened inside it; one closing a bookmark from further up the document
    stays where it is, because moving it would put the end before the
    start — the inversion the leading walk below exists to prevent, in
    the other direction.
    """
    el = kids[at]
    if not is_end_marker(el):
        return False
    ident = el.get(W + "id")
    if ident is None:
        return False
    opener = el.tag.replace("End", "Start")
    return any(node.get(W + "id") == ident
               for e in kids[start:at] for node in e.iter(opener))


def _blocks(body: etree._Element, caption: re.Pattern[str],
            note: re.Pattern[str] = NOTE) -> dict[int, list[etree._Element]]:
    """Каждый table's block: its caption, the table, and any notes under it.

    A caption sits ABOVE its table, and a note BELOW — get that backwards
    and every table moves with the wrong words. The block ends at the
    first paragraph that is neither a note nor empty.

    MARKERS ARE TRANSPARENT, on both sides: they carry nothing, and a walk
    that stops at one loses the exhibit under it (between the caption and
    the table) or the notes under it (below the table). They travel with
    the block, since an element standing inside an exhibit's span is that
    exhibit's — except an end marker closing something from outside the
    block, which stays put: under the table it ends the walk, and in
    front of the caption it is not taken.

    TWO BLOCKS NEVER SHARE AN ELEMENT, as two `exhibits` spans never do.
    Both roads to one element in two blocks ran through where exhibits
    MEET: an end marker there, closing the upper exhibit's bookmark, and
    a caption a caller's `note` pattern also matches.
    """
    kids = list(body)
    out: dict[int, list[etree._Element]] = {}
    for i, el in enumerate(kids):
        if el.tag != W + "p":
            continue
        m = caption.match(_text(el))
        if not m:
            continue
        j = i + 1
        while j < len(kids) and (is_marker(kids[j])
                                 or (kids[j].tag == W + "p"
                                     and not _text(kids[j]).strip())):
            j += 1
        if j >= len(kids) or kids[j].tag != W + "tbl":
            continue                      # a caption with no table under it
        # WORD HOISTS A TABLE'S BOOKMARK TO BODY LEVEL, immediately before
        # the caption: the bookmarkStart naming the table is a sibling
        # of the paragraph, not a child of it. Leaving it behind while the
        # caption moves inverts the bookmark: on DSI all twelve came back
        # with END BEFORE START, and `citations.audit_links` reported no
        # issue, because it checks that a bookmark is PAIRED and that links
        # resolve, not that it opens before it closes.
        #
        # The walk is `exhibits._leading`: back over every marker, then
        # forward past the END markers at the front of that run. One of
        # those closes something opened EARLIER — where two exhibits meet,
        # the bookmark around the one above, whose note walk takes it. It
        # was taken here too, by a walk that took any bookmarkStart or
        # bookmarkEnd, so both blocks held it and it went wherever the last
        # move put it: END BEFORE START again when only this block moved,
        # and when both did, a block whose first element stood behind the
        # other block, measured out of order and lost.
        head = i
        while head > 0 and is_marker(kids[head - 1]):
            head -= 1
        while head < i and is_end_marker(kids[head]):
            head += 1
        block = kids[head:j + 1]
        k = j + 1
        # A BODY is never absorbed, whatever it looks like: an image is a
        # paragraph with no text, and without this clause the next
        # figure's picture travelled with the table's notes.
        while k < len(kids):
            under = kids[k]
            if is_marker(under):
                # one the block closes goes with it; one that closes
                # something further up, or opens something for what comes
                # next, stays — and what follows it is no longer the
                # block's either
                if not _closes_inside(kids, head, k):
                    break
            elif under.tag != W + "p" or is_body(under):
                break
            else:
                txt = _text(under).strip()
                # a CAPTION is never a note, whatever `note` matches: the
                # next block begins with it (`exhibits` reads a caption
                # first, and a note only after)
                if txt and (caption.match(txt) or not note.match(txt)):
                    break
            block.append(under)
            k += 1
        out[int(m.group(1))] = block
    return out


@dataclass(frozen=True)
class Block:
    """One exhibit's elements, and what moving them would cost.

    The elements are what :func:`keep_together`, :func:`own_page` and
    :func:`space_block` already take, so a caller that has one of these
    can hand `block.elements` straight to them.

    The three flags are the traps a hand-rolled span walked into on AFI
    (2026-08-19, four figures to the appendix). None of them is
    reachable by reading the words: every word survived that move, the
    caption inventory balanced, the text diff was clean and a 560-check
    verifier passed, while two landscape orientations and eight footer
    parts were gone.
    """

    caption: str
    elements: list[etree._Element]
    #: The block ENDS a section — its last paragraph carries `w:sectPr`.
    #: For AFI's wide by-country panels that section is the landscape
    #: one, and the paragraph holding it looks empty.
    ends_a_section: bool
    #: This block gets its own page only because the block BEFORE it
    #: ends a section. Move it somewhere with nothing in front and it
    #: shares a page with whatever it lands under.
    shares_a_page: bool
    #: It is the last content in the body. Moving it leaves the
    #: body-level `sectPr` governing nothing, which renders as a blank
    #: page — the last block's geometry has to be promoted into it.
    last_in_body: bool


def _caption_re() -> re.Pattern[str]:
    """THE caption definition, borrowed rather than copied.

    `CAPTION` above knows Table and Таблица because `place` moves
    tables; an exhibit is also a figure, and the numbers run "A2" and
    "1-A". `crossrefs.caption_re` is the definition every other module
    classifies by, and a second spelling here is the drift that file's
    docstring records having had three times.
    """
    return caption_re()


def _ends_section(el: etree._Element) -> bool:
    return el.tag == W + "p" and el.find(f"{W}pPr/{W}sectPr") is not None


def exhibit_block(parts: dict[str, bytes], caption: str, *,
                  note: re.Pattern[str] = NOTE) -> Block:
    """The full span of one exhibit, INCLUDING a trailing section break.

    `placement.place` has understood a TABLE's block since it was
    written — caption above, notes below, hoisted bookmarks in front —
    and every paper moving a FIGURE hand-rolled the span again. The span
    is easy to get wrong in a way no text gate sees, and was: a figure
    here is caption, image, source, and one more paragraph that looks
    empty and carries the section break.

    So the rule is the table rule, generalised by one clause: the
    exhibit's body is a `w:tbl` OR a paragraph holding a drawing, and
    everything after it that is a note or carries no text belongs to the
    block — which is what makes the section-break paragraph part of it
    rather than a spacer to leave behind.

    The walk itself is `exhibits.exhibits`, since 2026-09-11, which is
    what lets a figure captioned UNDERNEATH its image (Aging_Well,
    Parental_style) have a span at all; this asks it about one caption
    and keeps the refusals a caller can act on.

    Read-only. It answers what the span IS and what moving it would
    cost; the caller moves it, because where an exhibit belongs is not
    a question this can be asked.
    """
    body = _body(parts)
    kids = list(body)
    heads = [i for i, el in enumerate(kids)
             if el.tag == W + "p" and caption in _text(el)
             and _caption_re().match(_text(el).strip())]
    if not heads:
        raise PackageError(
            f"no caption paragraph containing {caption!r} — a caption "
            f"OPENS its paragraph, so a mention of it in prose is not one")
    if len(heads) > 1:
        raise PackageError(
            f"{len(heads)} caption paragraphs contain {caption!r}; say "
            f"which by passing more of it")
    i = heads[0]

    found = next((x for x in exhibits(body, note=note) if x.caption_at == i),
                 None)
    if found is None or found.body_at is None:
        raise PackageError(
            f"caption {caption!r} has no table or image beside it — this "
            f"returns an exhibit's span, and there is no exhibit here")
    head, block = found.start, list(found.elements)

    content = [el for el in kids if el.tag in (W + "p", W + "tbl")]
    before = kids[head - 1] if head else None
    return Block(
        caption=found.caption[:70],
        elements=block,
        ends_a_section=any(_ends_section(el) for el in block),
        shares_a_page=(before is not None and _ends_section(before)
                       and kids[i].find(f"{W}pPr/{W}pageBreakBefore") is None),
        last_in_body=bool(content) and content[-1] is block[-1])


def _caption_of(block: list[etree._Element]) -> str:
    """The block may open with the markers Word hoisted in front of it;
    the caption is the first paragraph in it."""
    for el in block:
        if el.tag == W + "p":
            return _text(el).strip()[:70]
    return ""


def _anchor(body: etree._Element, number: int, owned: set[int],
            mention: re.Pattern[str]) -> etree._Element | None:
    """The first paragraph of PROSE that mentions this table.

    `owned` holds every element of every block, not just this table's own.
    A caption is not prose and neither is a note: «Таблица 2. Продолжение
    таблицы 1» mentions table 1 by the letter of the pattern, and reading
    it as the sentence that introduces table 1 does two things at once —
    it anchors the table on a caption belonging to another exhibit, and it
    lands this block INSIDE that exhibit, between its caption and its own
    table. Measured on 2026-09-16: `moved` True, `problems` empty, and
    `audit` then saw one table where the manuscript had two, because the
    two tables ended up against each other (see `_would_join_tables`).

    A table whose only mention is inside another exhibit is now reported
    as one nothing mentions and left where it is, which is the truth and
    is visible.
    """
    for el in body:
        if el.tag != W + "p" or id(el) in owned:
            continue
        for m in mention.finditer(_text(el)):
            if int(m.group(1)) == number:
                return el
    return None


def _ppr(el: etree._Element) -> etree._Element:
    ppr = el.find(W + "pPr")
    if ppr is None:
        ppr = etree.Element(W + "pPr")
        el.insert(0, ppr)
    return ppr


def _in_order(props: etree._Element, tag: str) -> etree._Element:
    """Find or create a properties child, where its schema puts it.

    The rank table is `_xml.PPR_ORDER` for a `w:pPr`, shared with the four
    other writers that need it, so this is not a fifth private copy of the
    schema's order — only the lxml insertion, which those do on strings — and
    `_TRPR_ORDER` for a `w:trPr`.

    Inserting at index 0 (which this did) is right for `pStyle` and wrong for
    everything else: it puts `keepNext` AHEAD of a `pStyle` that is already
    there. `lint` did not catch it, because its CT_PPr check asks only that
    nothing which must precede `w:rPr` follows it.

    ONE rank table was as wrong for a `w:trPr` as index 0 was for a `w:pPr`,
    and silently: `cantSplit`, `tblHeader`, `ins`, `del` and `trPrChange` are
    none of them in `PPR_ORDER`, so every one of them ranked last, no
    sibling ever sorted above another, and the new property was appended —
    behind the `w:ins` or `w:del` marking a tracked row. Which is the one
    order `CT_TrPr` does not allow.

    **A child is not always a property.** An XML comment a converter left
    inside the properties is a child like any other, its `.tag` is the
    factory that makes one, and `etree.QName` refuses that with
    `ValueError: Invalid input tag` — out of `place`, `keep_together`,
    `space_block` and `own_page` alike, before anything was reported. It
    has no rank, so it is stepped over: the new property goes in front of
    the first PROPERTY that outranks it, wherever the comment stands. The
    test is fused positive rather than a `continue` on the negative, for
    the reason `revisions` gives: lxml-stubs types `.tag` as `str`, and
    mypy's `warn_unreachable` refuses the branch.
    """
    node = props.find(W + tag)
    if node is not None:
        return node
    node = etree.Element(W + tag)
    rank_of = _RANKS.get(etree.QName(props).localname, _PPR_RANK)
    last = len(rank_of)
    rank = rank_of.get(tag, last)
    for sib in props:
        if (isinstance(sib.tag, str)
                and rank_of.get(etree.QName(sib).localname, last) > rank):
            sib.addprevious(node)
            return node
    props.append(node)
    return node


def _flag(parent: etree._Element, tag: str, on: bool = True) -> None:
    """Set or clear a boolean property, in the one place Word accepts it."""
    node = parent.find(W + tag)
    if on and node is None:
        _in_order(parent, tag)
    elif not on and node is not None:
        parent.remove(node)


def keep_together(block: list[etree._Element], *, on: bool = True) -> None:
    """Make Word carry the whole block to the next sheet rather than break it.

    `cantSplit` stops a ROW straddling a page; `keepNext` binds each row
    to the one after and the caption to the table. Both are needed:
    without cantSplit a tall row still breaks, and without keepNext the
    table breaks between rows. The LAST row must not keep with next, or
    Word drags whatever follows the table onto the table's page.
    """
    for el in block:
        if el.tag == W + "p":
            _flag(_ppr(el), "keepNext", on)
    for tbl in (e for e in block if e.tag == W + "tbl"):
        rows = tbl.findall(W + "tr")
        for n, row in enumerate(rows):
            trpr = row.find(W + "trPr")
            if trpr is None:
                trpr = etree.Element(W + "trPr")
                row.insert(0, trpr)
            _flag(trpr, "cantSplit", on)
            last = n == len(rows) - 1
            for para in row.iter(W + "p"):
                _flag(_ppr(para), "keepNext", on and not last)
    # The note after the table must not keep with what follows it — but
    # ONLY a paragraph that comes AFTER the table. Walking back from the end
    # and clearing the first paragraph found unbinds the CAPTION from its own
    # table whenever the table has no note, because then the caption is the
    # last paragraph in the block. Stopping at the table is what tells the
    # two cases apart.
    for el in reversed(block):
        if el.tag == W + "tbl":
            break
        if el.tag == W + "p":
            _flag(_ppr(el), "keepNext", False)
            break


def _section_ends(body: etree._Element) -> list[int]:
    """Body-child indices of the paragraphs that END a section."""
    return [i for i, el in enumerate(body)
            if el.tag == W + "p" and el.find(W + "pPr/" + W + "sectPr")
            is not None]


def _section_of(ends: list[int], index: int) -> int:
    """Which section a body child belongs to.

    A paragraph's `pPr/sectPr` describes the section that ENDS at it, so a
    child belongs to the first section whose end is at or after it.
    """
    for n, end in enumerate(ends):
        if index <= end:
            return n
    return len(ends)


def _next_content(el: etree._Element) -> etree._Element | None:
    """The next sibling that carries content: past every marker.

    NOT simply `getnext()`. Word hoists a table's bookmark to body level, so
    the element after a block is very often the NEXT table's `bookmarkStart`
    rather than its caption — and a rule that only looks at `w:p` then does
    nothing at all, silently. DSI's таблица 11 is followed by таблица 7's
    hoisted bookmark, and that is exactly how its caption kept the 8 pt
    before-spacing this function exists to zero.

    Every marker, not the two halves of a bookmark alone: a reviewer's
    `commentRangeEnd`, a converter's XML comment and Word's spelling marks
    sit in the same place and carry as little.
    """
    nxt = el.getnext()
    while nxt is not None and is_marker(nxt):
        nxt = nxt.getnext()
    return nxt


def _paragraph_or_table(el: etree._Element | None, *,
                        backwards: bool = False) -> etree._Element | None:
    """`el`, or the nearest sibling past it, that is a `w:p` or a `w:tbl`.

    The neighbour that decides whether two tables JOIN, which is not
    `_next_content`'s: see `_would_join_tables`. Everything else is stepped
    over, because only a paragraph was seen to keep two tables apart.
    """
    while el is not None and el.tag not in (W + "p", W + "tbl"):
        el = el.getprevious() if backwards else el.getnext()
    return el


def _would_join_tables(block: list[etree._Element],
                       anchor: etree._Element) -> str | None:
    """Would this move leave one `w:tbl` directly against another?

    **WORD READS TWO ADJACENT TABLES AS ONE**, and that is why this
    refuses rather than reports. Measured through Word automation on
    2026-09-16: two `w:tbl` of two rows each, written with nothing
    between them, open as `Tables.Count` 1 — a single table of four rows
    — and Word writes the package back holding one `w:tbl`. The second
    exhibit is not misplaced, it is GONE, with its caption still in the
    text naming it. A marker between them does not save it: a
    `bookmarkEnd`, a `commentRangeEnd` and an XML comment each merged
    too, and only a PARAGRAPH between kept the two apart.

    **So the neighbours compared are the nearest paragraph or table**,
    and everything between is stepped over. They were `_next_content`'s,
    which stepped over this module's own list of ten marker tags and
    stopped at anything else — so a body-level `w:proofErr` or an element
    in an extension namespace passed for a separator, and the move set
    the table against another with only that between them. A content
    control or a `w:customXml` is stepped over as well: it was not
    measured, and refusing is the side that loses nothing.

    Two ways a move does it: the block LANDS against the table that
    follows its mention, or the hole it leaves closes a table above the
    block onto a table below it.
    """
    tail = next((e for e in reversed(block) if not is_marker(e)), None)
    landing = _paragraph_or_table(anchor.getnext())
    if (tail is not None and tail.tag == W + "tbl"
            and landing is not None and landing.tag == W + "tbl"):
        return ("the paragraph that mentions it is followed by a table, so "
                "the move would set this table against that one")
    before = _paragraph_or_table(block[0].getprevious(), backwards=True)
    after = _paragraph_or_table(block[-1].getnext())
    if (before is not None and before.tag == W + "tbl"
            and after is not None and after.tag == W + "tbl"):
        return ("a table stands above this block and another below it, so "
                "moving it away would set those two against each other")
    return None


def space_block(block: list[etree._Element],
                following: etree._Element | None, *,
                gap_pt: float = GAP_PT,
                caption_after_pt: float = CAPTION_AFTER_PT) -> None:
    """The two gaps a table block owns: under its caption, and under itself.

    * **the caption** is single-spaced with `caption_after_pt` under it, so
      the title sits tight against the table it names rather than floating
      at the body's line spacing (1.5 in DSI, which put half a line between
      a caption and its own table on three of twelve).
    * **the block** gets `gap_pt` under its last note. A TABLE cannot carry
      spacing — `w:spacing` is a paragraph property — so when a table has no
      note the gap goes on the paragraph that resumes after it, which is the
      only place it can live. Whichever side owns the gap, the other is
      zeroed, so the result is `gap_pt` and not `gap_pt` plus whatever the
      resuming paragraph happened to carry.

    **A HEADING KEEPS ITS OWN SPACING.** A heading's space-before belongs to
    its style, and overriding it here would leave the two headings that
    happen to follow a table sitting closer to the text above them than
    every other heading in the paper. So a heading is never written to —
    which also means a note-less table followed by a heading gets no gap
    from this function at all, and that is the correct answer rather than a
    gap applied somewhere it does not belong.
    """
    paras = [e for e in block if e.tag == W + "p"]
    if not paras:
        return
    spacing = _in_order(_ppr(paras[0]), "spacing")
    spacing.set(W + "after", _twips(caption_after_pt))
    spacing.set(W + "line", "240")
    spacing.set(W + "lineRule", "auto")

    style = (following.find(W + "pPr/" + W + "pStyle")
             if following is not None and following.tag == W + "p" else None)
    heading = (style is not None
               and str(style.get(W + "val")).lower().startswith("heading"))

    # the last element that CARRIES something: a block ending with its own
    # bookmarkEnd still ends with its note, and the gap belongs on the note
    tail = next((e for e in reversed(block) if not is_marker(e)), None)
    last = paras[-1] if tail is not None and tail.tag == W + "p" else None
    if last is not None and last is not paras[0]:
        _in_order(_ppr(last), "spacing").set(W + "after", _twips(gap_pt))
        if following is not None and following.tag == W + "p" and not heading:
            _in_order(_ppr(following), "spacing").set(W + "before", "0")
    elif following is not None and following.tag == W + "p" and not heading:
        _in_order(_ppr(following), "spacing").set(W + "before", _twips(gap_pt))


def own_page(block: list[etree._Element]) -> None:
    """An oversized table: a fresh sheet, and a header that repeats.

    `keepNext`/`cantSplit` cannot make an oversized table fit — nothing can —
    so the goal changes from "do not split" to "split as late as possible and
    stay readable across the break".
    """
    for el in block:
        if el.tag == W + "p":
            _flag(_ppr(el), "pageBreakBefore", True)
            break
    for tbl in (e for e in block if e.tag == W + "tbl"):
        rows = tbl.findall(W + "tr")
        if not rows:
            continue
        trpr = rows[0].find(W + "trPr")
        if trpr is None:
            trpr = etree.Element(W + "trPr")
            rows[0].insert(0, trpr)
        _flag(trpr, "tblHeader", True)
        for row in rows:
            rpr = row.find(W + "trPr")
            if rpr is not None:
                _flag(rpr, "cantSplit", False)


@dataclass(frozen=True)
class FitFinding:
    """One exhibit breaking the fit rule, and which half it broke."""

    number: int
    caption: str
    kind: str                    # "row may split", "row unbound", "straddles"
    detail: str

    def __str__(self) -> str:
        return f"table {self.number} ({self.caption[:40]}): {self.detail}"


@dataclass
class FitReport:
    """What :func:`audit` found. `ok` is the gate."""

    findings: list[FitFinding] = field(default_factory=list)
    tables: int = 0
    rendered: bool = False

    @property
    def ok(self) -> bool:
        return not self.findings

    def format(self) -> str:
        head = (f"{self.tables} table(s): {len(self.findings)} fit "
                f"finding(s)")
        if not self.rendered:
            head += " — markup only; pass a renderer to see what STRADDLES"
        return "\n".join([head] + [f"  ! {f}" for f in self.findings])


def _has(el: etree._Element | None, tag: str) -> bool:
    """Is this property present and not switched off?

    `<w:cantSplit w:val="false"/>` is the property saying the opposite,
    and reading it as present is how an audit reports a rule kept by a
    document that switches it off.
    """
    if el is None:
        return False
    found = el.find(W + tag)
    return found is not None and found.get(W + "val") not in ("false", "0",
                                                              "off")


def audit(parts: dict[str, bytes], *,
          caption: re.Pattern[str] = CAPTION,
          note: re.Pattern[str] = NOTE,
          render: Callable[[dict[str, bytes]], list[str]] | None = None,
          ) -> FitReport:
    """Does every exhibit obey the house fit rule? (report, not a repair.)

    The rule `keep_together` writes, read back: every row carries
    `w:cantSplit`, every row but the last binds to the next with
    `keepNext`, and the caption binds to the table. Nothing audited for
    its ABSENCE — `refstyle` has `audit` beside its writers and the table
    rules had no equivalent — so the rule was enforceable only by
    remembering to run a writer, which is a rule that decays. Aging_Well
    is the proof: its Table 1 was hand-typed and dropped in whole, so no
    build ever had the chance to style it, and eight rounds of green
    gates went by while it straddled sheets 8 and 9.

    Two layers, and the first needs no renderer. The MARKUP question —
    "is the property there?" — is the one that would have prevented the
    split, and it is cheap enough for any paper's `[verify]` block. Give
    it a `render` callback and it also reports what actually STRADDLES a
    boundary, which is the only way to catch a table too tall to fit at
    all: `cantSplit` cannot make an oversized table fit, and nothing can.

    `pages --check` was the other candidate home. It renders, and its
    questions are about the SHEETS — blank ones, numbering restarts, the
    corner a number prints in. This defect is about the content that
    landed on them, which is a different question and belongs beside the
    code that writes the property.
    """
    body = _body(parts)
    blocks = _blocks(body, caption, note)
    report = FitReport(tables=len(blocks))

    for number, block in sorted(blocks.items()):
        text = _caption_of(block)
        tbl = next((e for e in block if e.tag == W + "tbl"), None)
        if tbl is None:
            continue
        head = next((e for e in block if e.tag == W + "p"), None)
        if head is not None and not _has(head.find(W + "pPr"), "keepNext"):
            report.findings.append(FitFinding(
                number, text, "caption unbound",
                "its caption does not keep with the table, so Word may "
                "leave the caption behind on the sheet above"))
        rows = tbl.findall(W + "tr")
        loose = [n for n, row in enumerate(rows)
                 if not _has(row.find(W + "trPr"), "cantSplit")]
        if loose:
            report.findings.append(FitFinding(
                number, text, "row may split",
                f"{len(loose)} of {len(rows)} row(s) carry no cantSplit — "
                f"a tall one will break ACROSS a page, mid-row"))
        unbound = [n for n, row in enumerate(rows[:-1])
                   if not all(_has(p.find(W + "pPr"), "keepNext")
                              for p in row.iter(W + "p"))]
        if unbound:
            report.findings.append(FitFinding(
                number, text, "row unbound",
                f"{len(unbound)} row(s) do not keep with the row after — "
                f"the table may break BETWEEN rows"))

    if render is not None:
        report.rendered = True
        found = _locate_tables(render(parts), blocks)
        for number, block in sorted(blocks.items()):
            tbl = next((e for e in block if e.tag == W + "tbl"), None)
            rows = tbl.findall(W + "tr") if tbl is not None else []
            first, last = found[number]
            if first and last and last != first:
                report.findings.append(FitFinding(
                    number, _caption_of(block), "straddles",
                    f"it starts on sheet {first} and ends on sheet {last}"))
            elif first and rows and last is None:
                report.findings.append(FitFinding(
                    number, _caption_of(block), "end not found",
                    f"its caption is on sheet {first} and its last row is "
                    f"on none of them — the fit is UNMEASURED"))
    return report


def place(parts: dict[str, bytes], *,
          caption: re.Pattern[str] = CAPTION,
          mention: re.Pattern[str] = MENTION,
          only: Iterable[int] | None = None,
          skip: Iterable[int] | None = None,
          note: re.Pattern[str] = NOTE,
          move: bool = True,
          fit: bool = True,
          space: bool = True,
          gap_pt: float = GAP_PT,
          caption_after_pt: float = CAPTION_AFTER_PT,
          max_drift: int = 1,
          render: Callable[[dict[str, bytes]], list[str]] | None = None,
          ) -> tuple[dict[str, bytes], PlacementReport]:
    """Anchor each table to its first mention and keep it whole on one sheet.

    Returns new parts and a report. `render` is a callback taking parts and
    returning one string per sheet — supply it and the fit is MEASURED; omit it
    and the properties are applied unverified, which the report says plainly.

    `only`/`skip` take table numbers. A manuscript that numbers display
    equations with one-row layout tables must skip nothing here — those
    carry no caption, so `_blocks` never sees them.
    """
    parts = dict(parts)
    body = _body(parts)
    blocks = _blocks(body, caption, note)
    wanted = set(blocks) if only is None else set(only) & set(blocks)
    wanted -= set(skip or ())
    report = PlacementReport()
    # EVERY block's elements, and not only the one being placed: a caption,
    # a note or a blank paragraph belonging to another exhibit is not the
    # prose that introduces this one. `only` and `skip` do not narrow this
    # — a block this call is not placing is still an exhibit, and its
    # caption is still not a sentence.
    owned = {id(e) for b in blocks.values() for e in b}

    for number in sorted(wanted):
        block = blocks[number]
        pl = Placement(number=number, caption=_caption_of(block))
        anchor = _anchor(body, number, owned, mention)
        if anchor is None:
            report.problems.append(
                f"table {number}: nothing in the prose mentions it"
                " — left where it is")
        elif move:
            # A BLOCK THAT LIVES IN ITS OWN SECTION IS ALREADY PLACED.
            # DSI's таблица 4 is wide and owns a landscape section: the note
            # under it carries the `sectPr`, so the section spans the whole
            # block. Moving the block to its mention left the `sectPr`
            # behind — the landscape section came to hold one stranded
            # paragraph (a blank landscape sheet) and the table itself came
            # to rest in the portrait section, typeset in an orientation it
            # was never laid out for. Nothing saw it: `moved` was True, links
            # audited clean, and the structure gate counted the same three
            # `sectPr` before and after, because the break was orphaned
            # rather than deleted. Counting section breaks cannot see one
            # that stopped containing anything.
            ends = _section_ends(body)
            kids = list(body)
            here = _section_of(ends, kids.index(block[0]))
            there = _section_of(ends, kids.index(anchor))
            owns = any(list(e.iter(W + "sectPr")) for e in block)
            if owns:
                report.problems.append(
                    f"table {number}: its block carries a section break "
                    f"— left where it is, because moving it would strand "
                    f"the section")
            elif here != there:
                report.problems.append(
                    f"table {number}: its mention is in another section "
                    f"— left where it is, because the move would cross a "
                    f"section boundary")
            else:
                already = anchor.getnext() is block[0]
                joins = None if already else _would_join_tables(block, anchor)
                if joins is not None:
                    report.problems.append(
                        f"table {number}: {joins} — left where it is, "
                        f"because Word reads two tables with nothing "
                        f"between them as ONE table")
                else:
                    if not already:
                        at = anchor
                        for el in block:
                            at.addnext(el)
                            at = el
                        pl.moved = True
                    pl.anchor_text = _text(anchor).strip()[:70]
        if fit:
            keep_together(block)
            pl.kept_together = True
        if space:
            space_block(block, _next_content(block[-1]),
                        gap_pt=gap_pt, caption_after_pt=caption_after_pt)
            pl.spaced = True
        report.placements.append(pl)

    def freeze() -> None:
        parts[DOCUMENT] = etree.tostring(
            body.getroottree(), xml_declaration=True,
            encoding="UTF-8", standalone=True)

    freeze()
    if render is None:
        return parts, report

    report.rendered = True
    _measure_and_fix(report, blocks, max_drift,
                     render=render, parts=parts, freeze=freeze)
    return parts, report


#: How much of a caption, a row or a mention is looked for on a sheet: its
#: first forty characters as the MARKUP spells them, cut before whitespace
#: is removed. The tail is where a renderer's line break or hyphenation lands.
_PROBE = 40


def _flat(text: str) -> str:
    """`text` with no whitespace at all: the only spelling the markup and
    the rendered page share.

    A render puts whitespace where the markup has none. LE_trends' Table 1
    ends on a narrow cell holding `Japan 1966-2000 (34y)`; Word wrapped it
    after the hyphen, and the page text reads `Japan 1966-` then
    `2000 (34y)`. Collapsing runs of whitespace, which this module did,
    keeps that break as a space the markup does not have, so the row was
    found on no sheet, and a table whole on sheet 4 was reported
    UNMEASURED: exit 2 from `fit --render --check`.

    The markup also lacks whitespace the page has. A caption set with a
    tab is `Table 2.` and `Every group` in `w:t`, the tab an element of
    its own; Word's page puts a gap there, the caption was found on no
    sheet, and a table straddling two sheets produced no finding at all
    (measured through Word by
    `test_fit_RENDER_through_WORD_reports_the_straddle_and_nothing_else`).
    """
    return "".join(text.split())


def _sheet_of(sheets: list[str], needle: str, start: int = 0) -> int | None:
    needle = _flat(needle)
    for i in range(start, len(sheets)):
        if needle and needle in _flat(sheets[i]):
            return i + 1
    return None


def _flow(sheets: list[str]) -> tuple[str, list[int]]:
    """Every sheet flattened into one string, and where each one starts."""
    flats = [_flat(sheet) for sheet in sheets]
    starts: list[int] = []
    at = 0
    for flat in flats:
        starts.append(at)
        at += len(flat)
    return "".join(flats), starts


def _sheet_at(starts: list[int], pos: int) -> int:
    """The 1-based sheet that position `pos` of the flowed text is on."""
    return bisect_right(starts, pos)


def _position(block: list[etree._Element]) -> int:
    parent = block[0].getparent()
    return parent.index(block[0]) if parent is not None else 0


def _locate(text: str, starts: list[int], block: list[etree._Element],
            cursor: int) -> tuple[int | None, int | None, int]:
    """One table in the flowed render: (caption sheet, last sheet, cursor).

    **The caption is the occurrence the table's rows follow most
    closely**, not the first one. HCW's prose on sheet 13 quotes the full
    captions of Tables 6 and 7; the first sheet carrying that text was
    taken as each table's, and both read "starts on sheet 13 and ends on
    sheet 29" (and 30) — whole tables, exit 2. A List of Tables would do
    the same to every table. Nor can the first row say which table it
    is: five of HCW's tables open on the same header row. So each
    occurrence is measured against the distance to the table's first row
    with text, or to its last where the first is not on the page.

    **The end is the last row WITH text.** A blank last row is a probe of
    nothing, found on no sheet, and was read as UNMEASURED.

    A caption whose text is on no sheet answers (None, None), as before.
    The next table's search starts at the returned cursor.
    """
    caption = _flat(_caption_of(block)[:_PROBE])
    tbl = next((e for e in block if e.tag == W + "tbl"), None)
    rows = [t for t in (_row_text(r).strip() for r in
                        (tbl.findall(W + "tr") if tbl is not None else []))
            if t]
    first = _flat(rows[0][:_PROBE]) if rows else ""
    last = _flat(rows[-1][:_PROBE]) if rows else ""

    best: tuple[int, int, int] | None = None        # (gap, caption, body)
    at = text.find(caption, cursor) if caption else -1
    while at >= 0:
        after = at + len(caption)
        body = text.find(first, after) if first else -1
        if body < 0 and last:
            body = text.find(last, after)
        gap = body - after if body >= 0 else len(text)
        if best is None or gap < best[0]:
            best = (gap, at, body)
        at = text.find(caption, after)
    if best is None:
        return None, None, cursor

    _, at, body = best
    start = body if body >= 0 else at + len(caption)
    end = text.find(last, start) if last else -1
    if end < 0:
        return _sheet_at(starts, at), None, start
    stop = end + len(last)
    return _sheet_at(starts, at), _sheet_at(starts, stop - 1), stop


def _locate_tables(sheets: list[str],
                   blocks: dict[int, list[etree._Element]],
                   ) -> dict[int, tuple[int | None, int | None]]:
    """`_locate` for every table, in the order the document now holds
    them. Each search starts where the table before it ended, so text
    quoted before that point is never a candidate."""
    text, starts = _flow(sheets)
    found: dict[int, tuple[int | None, int | None]] = {}
    cursor = 0
    for number, block in sorted(blocks.items(),
                                key=lambda item: _position(item[1])):
        first, last, cursor = _locate(text, starts, block, cursor)
        found[number] = (first, last)
    return found


def _measure_and_fix(report: PlacementReport,
                     blocks: dict[int, list[etree._Element]],
                     max_drift: int, *,
                     render: Callable[[dict[str, bytes]], list[str]],
                     parts: dict[str, bytes],
                     freeze: Callable[[], None]) -> None:
    """Render, locate every table, fix what split, and render again.

    `freeze` writes the LIVE tree back into `parts`. Re-parsing `parts`
    here instead would read back the bytes written before these edits and
    silently discard them — which is what the first version did, and the
    own-page test is what said so.

    One re-render at most: a page break changes pagination, so the
    numbers in the report come from a SECOND render rather than from the
    first one plus a guess.
    """
    sheets = render(parts)
    fixed = False
    found = _locate_tables(sheets, blocks)
    for pl in report.placements:
        block = blocks[pl.number]
        pl.caption_sheet, pl.last_sheet = found[pl.number]
        if pl.anchor_text:
            pl.mention_sheet = _sheet_of(sheets, pl.anchor_text[:_PROBE])
        if pl.split:
            own_page(block)
            pl.own_page, fixed = True, True

    if fixed:
        freeze()
        found = _locate_tables(render(parts), blocks)
        for pl in report.placements:
            pl.caption_sheet, pl.last_sheet = found[pl.number]

    for pl in report.placements:
        if pl.unmeasured:
            report.problems.append(
                f"table {pl.number}: its caption is on sheet "
                f"{pl.caption_sheet} and its last row was not found on any "
                f"sheet — the fit is UNMEASURED, so a split would not have "
                f"been seen and `own_page` could not fire")
    for pl in report.placements:
        # `and not pl.own_page` was here, and it made the line
        # unreachable for the case it describes: `own_page` is applied to
        # every table that split, so a table that STILL splits after it
        # always has the flag set. The report then read "1 given their
        # own page" with no problem under it — a table nothing can fix
        # presented as one that was fixed.
        if pl.split:
            report.problems.append(
                f"table {pl.number}: "
                f"{'still ' if pl.own_page else ''}splits across sheets "
                f"{pl.caption_sheet}-{pl.last_sheet}")
        if pl.drift is not None and pl.drift > max_drift:
            report.problems.append(
                f"table {pl.number}: {pl.drift} sheets after its mention "
                f"(limit {max_drift}) — place it by hand")
