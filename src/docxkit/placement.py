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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from lxml import etree

from ._xml import DOCUMENT, PPR_ORDER
from .errors import PackageError

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
    "PackageError",
    "Placement",
    "PlacementReport",
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
#: A note BELONGS to the table above it and travels with it.
#:
#: The keywords are not enough, and a manuscript proved it: DSI's таблица 4
#: carries «Примечание. Ориентация…» AND, under it, «* Высокая доля
#: самостоятельной занятости…» — the gloss on the `*` marking one of its rows.
#: The keyword-only pattern ended the block at the first note, so the second
#: was left behind when the table moved, and nothing reported it: an orphaned
#: note is still a paragraph, so no count changes.
#:
#: A LEADING FOOTNOTE MARKER is therefore a note too. The set is deliberately
#: small — `*`, `†`, `‡` and the `a)` / `1)` forms — because this pattern
#: decides where a block ENDS, and anything looser starts swallowing prose:
#: the paragraph after таблица 2 opens «Геометрическая форма не является…»
#: and must stay behind.
NOTE = re.compile(
    r"^\s*(?:(?:Примечание|Источник|Note|Source)\b"
    r"|[*†‡]"
    r"|[0-9]{1,2}\)"
    # the class spans BOTH alphabets on purpose: a Russian manuscript
    # letters its notes with Cyrillic, an English one with Latin
    r"|[a-zа-яё]\))", re.IGNORECASE)  # noqa: RUF001

#: the gap below a table block, in points — after the last note, or before the
#: paragraph that resumes when the table has no note
GAP_PT = 8.0
#: the gap below a caption, in points
CAPTION_AFTER_PT = 2.0

_PPR_RANK = {name: i for i, name in enumerate(PPR_ORDER)}


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
    """
    return " ".join(_text(tc) for tc in row.findall(W + "tc"))


def _blocks(body: etree._Element, caption: re.Pattern[str],
            note: re.Pattern[str] = NOTE) -> dict[int, list[etree._Element]]:
    """Каждый table's block: its caption, the table, and any notes under it.

    A caption sits ABOVE its table, and a note BELOW — get that backwards
    and every table moves with the wrong words. The block ends at the
    first paragraph that is neither a note nor empty.
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
        while (j < len(kids) and kids[j].tag == W + "p"
               and not _text(kids[j]).strip()):
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
        head = i
        while head > 0 and kids[head - 1].tag in (W + "bookmarkStart",
                                                  W + "bookmarkEnd"):
            head -= 1
        block = kids[head:j + 1]
        k = j + 1
        while k < len(kids) and kids[k].tag == W + "p":
            txt = _text(kids[k]).strip()
            if txt and not note.match(txt):
                break
            block.append(kids[k])
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


def _is_exhibit_body(el: etree._Element) -> bool:
    """A table, or a paragraph carrying a drawing rather than words."""
    if el.tag == W + "tbl":
        return True
    # `.find`, not `any(el.iter(...))`: `iter` hands back a GENERATOR,
    # which is truthy whether or not it will yield anything, so the
    # `any` form answers True for every paragraph in the document — and
    # then every caption is its own exhibit body and the table under it
    # is left behind. Caught by hand before this had a test, which is
    # the argument for having one.
    return (el.tag == W + "p"
            and any(el.find(f".//{W}{t}") is not None
                    for t in ("drawing", "pict", "object")))


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

    j = i if _is_exhibit_body(kids[i]) else i + 1
    while (j < len(kids) and kids[j].tag == W + "p"
           and not _text(kids[j]).strip() and not _is_exhibit_body(kids[j])):
        j += 1
    if j >= len(kids) or not _is_exhibit_body(kids[j]):
        raise PackageError(
            f"caption {caption!r} has no table or image under it — this "
            f"returns an exhibit's span, and there is no exhibit here")

    # the hoisted bookmarks in front: Word puts a table's bookmarkStart
    # at BODY level, before the caption. See `_blocks`.
    head = i
    while head > 0 and kids[head - 1].tag in (W + "bookmarkStart",
                                              W + "bookmarkEnd"):
        head -= 1
    k = j + 1
    while k < len(kids) and kids[k].tag == W + "p":
        txt = _text(kids[k]).strip()
        if txt and not note.match(txt):
            break
        k += 1
    block = kids[head:k]

    content = [el for el in kids if el.tag in (W + "p", W + "tbl")]
    before = kids[head - 1] if head else None
    return Block(
        caption=_caption_of(block),
        elements=block,
        ends_a_section=any(_ends_section(el) for el in block),
        shares_a_page=(before is not None and _ends_section(before)
                       and kids[i].find(f"{W}pPr/{W}pageBreakBefore") is None),
        last_in_body=bool(content) and content[-1] is block[-1])


def _caption_of(block: list[etree._Element]) -> str:
    """The block may open with hoisted bookmarks; the caption is the
    first paragraph in it."""
    for el in block:
        if el.tag == W + "p":
            return _text(el).strip()[:70]
    return ""


def _anchor(body: etree._Element, number: int, block: list[etree._Element],
            mention: re.Pattern[str]) -> etree._Element | None:
    """The first paragraph that mentions this table and is not part of it."""
    owned = {id(e) for e in block}
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


def _in_order(ppr: etree._Element, tag: str) -> etree._Element:
    """Find or create a `w:pPr` child, in the position CT_PPr requires.

    The rank table is `_xml.PPR_ORDER`, shared with the four other writers
    that need it, so this is not a fifth private copy of the schema's order —
    only the lxml insertion, which those do on strings.

    Inserting at index 0 (which this did) is right for `pStyle` and wrong for
    everything else: it puts `keepNext` AHEAD of a `pStyle` that is already
    there. `lint` did not catch it, because its CT_PPr check asks only that
    nothing which must precede `w:rPr` follows it.
    """
    node = ppr.find(W + tag)
    if node is not None:
        return node
    node = etree.Element(W + tag)
    rank = _PPR_RANK.get(tag, len(PPR_ORDER))
    for sib in ppr:
        name = etree.QName(sib).localname
        if _PPR_RANK.get(name, len(PPR_ORDER)) > rank:
            sib.addprevious(node)
            return node
    ppr.append(node)
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
    """The next sibling that is a paragraph or a table.

    NOT simply `getnext()`. Word hoists a table's bookmark to body level, so
    the element after a block is very often the NEXT table's `bookmarkStart`
    rather than its caption — and a rule that only looks at `w:p` then does
    nothing at all, silently. DSI's таблица 11 is followed by таблица 7's
    hoisted bookmark, and that is exactly how its caption kept the 8 pt
    before-spacing this function exists to zero.
    """
    nxt = el.getnext()
    while nxt is not None and nxt.tag in (W + "bookmarkStart",
                                          W + "bookmarkEnd"):
        nxt = nxt.getnext()
    return nxt


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

    last = paras[-1] if block and block[-1].tag == W + "p" else None
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

    for number in sorted(wanted):
        block = blocks[number]
        pl = Placement(number=number, caption=_caption_of(block))
        anchor = _anchor(body, number, block, mention)
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


def _sheet_of(sheets: list[str], needle: str, start: int = 0) -> int | None:
    needle = " ".join(needle.split())
    for i in range(start, len(sheets)):
        if needle and needle in " ".join(sheets[i].split()):
            return i + 1
    return None


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
    for pl in report.placements:
        block = blocks[pl.number]
        pl.caption_sheet = _sheet_of(sheets, _caption_of(block)[:40])
        tbl = next((e for e in block if e.tag == W + "tbl"), None)
        if tbl is not None and pl.caption_sheet:
            rows = tbl.findall(W + "tr")
            if rows:
                pl.last_sheet = _sheet_of(
                    sheets, _row_text(rows[-1]).strip()[:40],
                    pl.caption_sheet - 1)
        if pl.anchor_text:
            pl.mention_sheet = _sheet_of(sheets, pl.anchor_text[:40])
        if pl.split:
            own_page(block)
            pl.own_page, fixed = True, True

    if fixed:
        freeze()
        sheets = render(parts)
        for pl in report.placements:
            block = blocks[pl.number]
            pl.caption_sheet = _sheet_of(sheets, _caption_of(block)[:40])
            tbl = next((e for e in block if e.tag == W + "tbl"), None)
            rows = tbl.findall(W + "tr") if tbl is not None else []
            if rows and pl.caption_sheet:
                pl.last_sheet = _sheet_of(
                    sheets, _row_text(rows[-1]).strip()[:40],
                    pl.caption_sheet - 1)

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
