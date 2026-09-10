"""Which sheet is under-filled, and which exhibit's placement is the cause.

`placement` anchors an exhibit to its first mention and keeps it whole, and
says plainly why it stops there:

    moving the block further down the file to chase a page boundary would be
    guessing at a layout only the renderer knows.

That is right when there is no renderer. When there IS one, the guess becomes
a measurement, and this module makes it: it renders the manuscript, finds the
sheets that are mostly empty, works out which exhibit forced the break above
them, and renders each alternative placement to see what it would actually
save. Every number in the report was seen on a rendered page.

**It reports and changes nothing.** The moves are ranked and printed with what
each costs in drift; the caller decides and `placement.place` applies. A page
layout is an editorial judgement — which sheet a reader meets a figure on is
not a thing to settle by arithmetic behind the author's back — and the search
is cheap to run again once they have chosen.

**Fill is measured against the fullest TEXT sheet, and exhibit sheets are
excluded from the verdict.** A sheet holding a full-page figure carries three
lines of caption and nothing else; counted naively it is 9% full and the
worst page in the document, which is exactly backwards — it is full by
construction. Measured on a real manuscript: a line count alone nominated
three sheets, two of which were the figure pages themselves and only one of
which was a fault.

**An exhibit in its own section moves as its SECTION.**
`placement.exhibit_block`
already carries the TRAILING section break, because that paragraph looks empty
and is the block's own. The break that OPENS the section sits in the paragraph
before the caption and belongs to the block just as much: leave it behind and
the exhibit keeps its landscape page while the text that used to precede it
inherits one. So the span this module moves starts at that break when there is
one — the only asymmetry in the whole routine, and the one thing a hand-rolled
version of it would get wrong.

**What it does not do.** It never reorders prose, never resizes an exhibit and
never touches spacing: the only variable is which paragraph an exhibit follows.
That is a deliberate limit — on a manuscript the paragraph order carries the
argument, and a repacker that improved a page by moving a sentence would be
editing.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from lxml import etree

from ._xml import DOCUMENT
from .errors import PackageError
from .placement import CAPTION, MENTION, NOTE, _text

__all__ = [
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_THRESHOLD",
    "Move",
    "PackageError",
    "RepackReport",
    "Sheet",
    "repack",
]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: A sheet below this share of the fullest text sheet is worth reporting.
#: 0.6 is not a discovered constant — it is the point at which a reader
#: notices, and it is a parameter for that reason.
DEFAULT_THRESHOLD = 0.6

#: How many alternative placements to render per under-filled sheet. Each one
#: costs a full render — seconds, through Word — so the search is bounded and
#: the report says what it cost rather than hiding it.
DEFAULT_MAX_CANDIDATES = 8


@dataclass(frozen=True)
class Sheet:
    """One rendered sheet: how much is on it, and whether that is by design."""
    number: int
    lines: int
    chars: int = 0
    exhibits: tuple[str, ...] = ()

    @property
    def carries_exhibit(self) -> bool:
        return bool(self.exhibits)


@dataclass(frozen=True)
class Move:
    """One alternative placement, and what the render said it would do."""
    number: int
    caption: str
    after: str
    drift: int
    underfull_before: int
    underfull_after: int
    sheets_before: int
    sheets_after: int

    @property
    def gain(self) -> int:
        """Under-filled sheets removed. Negative means it made things worse."""
        return self.underfull_before - self.underfull_after

    @property
    def costs_a_sheet(self) -> int:
        return self.sheets_after - self.sheets_before


@dataclass
class RepackReport:
    sheets: list[Sheet] = field(default_factory=list)
    underfull: list[int] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    renders: int = 0
    threshold: float = DEFAULT_THRESHOLD
    full_lines: int = 0

    def format(self) -> str:
        head = (f"{len(self.sheets)} sheet(s); the fullest text sheet "
                f"carries {self.full_lines} characters, and a sheet "
                f"under {self.threshold:.0%} of that is reported")
        lines = [head]
        if not self.sheets:
            lines.append("  not rendered — nothing to measure")
            return "\n".join(lines + [f"  ! {x}" for x in self.problems])
        if not self.underfull:
            lines.append("  no under-filled sheet — nothing to repack")
        for n in self.underfull:
            s = next(x for x in self.sheets if x.number == n)
            share = s.chars / self.full_lines if self.full_lines else 0.0
            lines.append(f"  sheet {n}: {s.lines} line(s), {s.chars} "
                         f"characters, {share:.0%} full")
        if self.moves:
            lines.append(f"  {len(self.moves)} placement(s) tried, "
                         f"{self.renders} render(s):")
            for m in self.moves:
                # Spelled out rather than signed. `+1 under-filled sheet(s)`
                # was the first wording and it says the OPPOSITE of what it
                # means — the gain is sheets REMOVED, so the best move in the
                # list read as the one that made things worst.
                if m.gain > 0:
                    verdict = f"{m.gain} fewer under-filled sheet(s)"
                elif m.gain < 0:
                    verdict = f"{-m.gain} MORE under-filled sheet(s)"
                else:
                    verdict = "no change"
                sheet = ("" if not m.costs_a_sheet else
                         f", {m.sheets_before} -> {m.sheets_after} sheets")
                lines.append(
                    f"    {m.caption.split('.')[0]} after {m.after[:44]!r}: "
                    f"{verdict}{sheet}, drift {m.drift:+d}")
        elif self.underfull:
            lines.append(f"  {self.renders} render(s), no placement improves "
                         "it within the drift limit")
        return "\n".join(lines + [f"  ! {x}" for x in self.problems])


def _body(parts: dict[str, bytes]) -> etree._Element:
    if DOCUMENT not in parts:
        raise PackageError("no word/document.xml in these parts")
    root = etree.fromstring(parts[DOCUMENT])
    body = root.find(W + "body")
    if body is None:
        raise PackageError("word/document.xml has no w:body")
    return body


def _ends_section(el: etree._Element) -> bool:
    return el.find(W + "pPr/" + W + "sectPr") is not None


def _is_body(el: etree._Element) -> bool:
    """A table, or a paragraph carrying a drawing."""
    return (el.tag == W + "tbl"
            or (el.tag == W + "p"
                and el.find(".//" + W + "drawing") is not None))


def _label_of(text: str) -> str:
    """The exhibit WORD a caption opens with, lowercased: figure/table/box.

    Keyed by number alone, `Figure 1`, `Table 1` and `Box 1` are one entry and
    two of them are lost — silently, because a dict just keeps the last. On the
    manuscript this was written for that left one exhibit out of three, and the
    anchor search then matched "Figure 1 shows…" against TABLE 1's block and
    offered a move for it. The label comes from the caption's own first word
    rather than from a second capture group, so `placement.CAPTION` and every
    one-group pattern a caller already has keep working.
    """
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    return first.rstrip(".").lower()


def _exhibits(body: etree._Element, caption: re.Pattern[str],
              note: re.Pattern[str] = NOTE
              ) -> dict[tuple[str, int], list[etree._Element]]:
    """Each exhibit's block, whichever side its caption sits on.

    `placement._blocks` looks FORWARD from a caption, because a table's
    caption sits above it, and that is the whole convention for tables. A
    FIGURE is captioned underneath — image first, caption second — and against
    that layout the forward search finds no exhibit body at all and reports no
    blocks, silently: the manuscript this was written for has two figures and
    the caption-above reading found neither.

    So the body is looked for on BOTH sides, backwards first: the nearest
    table or drawing across intervening empty paragraphs. Backwards first
    because a paragraph of prose between two captions would otherwise be
    claimed by the one above it.
    """
    kids = list(body)
    out: dict[tuple[str, int], list[etree._Element]] = {}
    for i, el in enumerate(kids):
        # A BOX carries its caption in its own first cell, so the table IS
        # the exhibit and there is nothing beside it to find. Measured: the
        # two boxes of the manuscript this was written for were invisible
        # while only body-level paragraphs were considered as captions.
        if el.tag == W + "tbl":
            inner = "".join(t.text or "" for t in el.iter(W + "t"))
            m = caption.match(inner)
            if m:
                key = (_label_of(inner), int(m.group(1)))
                out[key] = kids[i:_after_notes(kids, i, note)]
            continue
        if el.tag != W + "p":
            continue
        m = caption.match(_text(el))
        if not m:
            continue
        key = (_label_of(_text(el)), int(m.group(1)))
        back = _walk(kids, i, -1)
        if back is not None and _is_body(kids[back]):
            out[key] = kids[back:_after_notes(kids, i, note)]
            continue
        fwd = _walk(kids, i, +1)
        if fwd is not None and _is_body(kids[fwd]):
            out[key] = kids[i:_after_notes(kids, fwd, note)]
    return out


def _walk(kids: list[etree._Element], start: int, step: int) -> int | None:
    """The nearest element either side of a caption that could be its body.

    Skips what sits between an image and its caption and is not either of
    them: text-less paragraphs, and **hoisted bookmarks**. Word lifts a
    bookmark out of the paragraph it marks, so a captioned figure reads
    `bookmarkStart, caption` at body level — and a walk that stops at the
    first non-paragraph stops on that marker. Measured: it made Figure 2
    invisible, and worse, sent Figure 1's caption FORWARD to claim the next
    exhibit body it found, which was Box 1's table.
    """
    j = start + step
    while 0 <= j < len(kids):
        el = kids[j]
        if _is_body(el):
            return j
        if el.tag.startswith(W + "bookmark"):
            j += step
            continue
        if el.tag == W + "p" and not _text(el).strip():
            j += step
            continue
        return None
    return None


def _after_notes(kids: list[etree._Element], last: int,
                 note: re.Pattern[str]) -> int:
    """One past the block, absorbing the notes that belong under it.

    A figure's `Source: …` line and a table's `Примечание.` are the block's,
    and leaving one behind is invisible to every count: an orphaned note is
    still a paragraph.
    """
    j = last + 1
    while j < len(kids) and kids[j].tag == W + "p":
        text = _text(kids[j]).strip()
        if text and not note.match(text):
            break
        j += 1
    return j


def _span(body: etree._Element,
          block: list[etree._Element]) -> list[etree._Element]:
    """The block, plus the section break that OPENS it if there is one.

    `exhibit_block` already carries the trailing break. The leading one is
    the paragraph before the caption when that paragraph ends a section: an
    exhibit given its own landscape page is opened by a break as well as
    closed by one, and moving only half of the pair leaves the exhibit's page
    behind for whatever text lands there next.
    """
    kids = list(body)
    first = kids.index(block[0])
    if first and _ends_section(kids[first - 1]) and not _text(kids[first - 1]):
        return [kids[first - 1], *block]
    return list(block)


def _sheet_of(sheets: list[str], needle: str) -> int | None:
    probe = " ".join(needle.split())[:40]
    if not probe:
        return None
    for i, s in enumerate(sheets, 1):
        if probe in " ".join(s.split()):
            return i
    return None


def _profile(sheets: list[str], captions: Iterable[str]) -> list[Sheet]:
    out = []
    caps = list(captions)
    for i, text in enumerate(sheets, 1):
        flat = " ".join(text.split())
        here = tuple(c for c in caps
                     if " ".join(c.split())[:40] and
                     " ".join(c.split())[:40] in flat)
        rows = [ln for ln in text.splitlines() if ln.strip()]
        out.append(Sheet(number=i, lines=len(rows),
                         chars=len("".join(rows)), exhibits=here))
    return out


def _verdict(profile: list[Sheet], threshold: float) -> tuple[list[int], int]:
    """Under-filled sheets, and the fullest text sheet's character count.

    **Characters, not lines, and that was measured rather than assumed.** A
    line count reads a rendered TABLE as enormous — every cell is its own line
    — so the notation table in the appendix of the manuscript this was written
    for scored 70 lines against a full prose page's 36, became the yardstick,
    and put twenty ordinary pages at "51% full". By characters the same pages
    are 90-100% and the one real fault stands alone at 17%. A page is full of
    words, and words are what a reader sees.

    The FIRST and LAST sheets are never under-filled. A title page is short
    because it is a title page, and a document ends where it ends; counting
    either as slack nominates every manuscript ever written.
    """
    text_sheets = [s for s in profile if not s.carries_exhibit]
    full = max((s.chars for s in text_sheets), default=0)
    if not full:
        return [], 0
    edges = {profile[0].number, profile[-1].number} if profile else set()
    under = [s.number for s in text_sheets
             if s.number not in edges and s.chars / full < threshold]
    return under, full


def _caption_text(block: list[etree._Element],
                  caption: re.Pattern[str]) -> str:
    """The caption's text, wherever in the block it sits.

    A BOX has no caption paragraph: the words are the table's own first
    cell. Returning "" for it left the sheet-matching with nothing to search
    for, so the box's sheet was never recognised as carrying an exhibit.
    """
    for el in block:
        if el.tag == W + "p" and caption.match(_text(el)):
            return _text(el).strip()
    for el in block:
        if el.tag == W + "tbl":
            inner = "".join(t.text or "" for t in el.iter(W + "t"))
            if caption.match(inner):
                return inner.strip()
    return ""


#: How much of the label a mention has to share for it to be the same
#: exhibit. Four characters, because a mention is DECLINED in some languages
#: — «Таблица 5» is captioned and «в таблице 5» is mentioned — so the label
#: cannot simply be searched for, and the caller's own `mention` pattern is
#: what finds the candidates.
_STEM = 4


def _anchor_of(body: etree._Element, label: str, number: int,
               block: list[etree._Element],
               mention: re.Pattern[str]) -> etree._Element | None:
    """The first paragraph mentioning THIS exhibit and not part of it.

    `placement._anchor` matches on the NUMBER alone, so with `Figure 1` and
    `Table 1` both in a document it returns whichever mention comes first for
    both — the same conflation `_label_of` exists to stop, one layer up. Here
    the caller's `mention` pattern finds the candidates and the label decides
    between them, on a stem rather than the whole word so that a declined
    mention still matches its caption.
    """
    owned = {id(e) for e in block}
    stem = label[:_STEM].lower()
    for el in body:
        if el.tag != W + "p" or id(el) in owned:
            continue
        for m in mention.finditer(_text(el)):
            if int(m.group(1)) != number:
                continue
            if m.group(0)[:_STEM].lower() == stem:
                return el
    return None


def _moved(parts: dict[str, bytes], key: tuple[str, int], target_text: str,
           caption: re.Pattern[str],
           note: re.Pattern[str] = NOTE) -> dict[str, bytes]:
    """A copy of `parts`, the exhibit at `key` moved after `target_text`."""
    out = dict(parts)
    body = _body(out)
    blocks = _exhibits(body, caption, note)
    if key not in blocks:
        raise PackageError(
            f"no exhibit {key[0]} {key[1]} with a caption to move")
    span = _span(body, blocks[key])
    owned = {id(e) for e in span}
    target = next((el for el in body
                   if el.tag == W + "p" and id(el) not in owned
                   and _text(el).strip() == target_text), None)
    if target is None:
        raise PackageError(f"no paragraph reads {target_text[:40]!r}")
    for el in span:
        body.remove(el)
    at = list(body).index(target)
    for offset, el in enumerate(span, 1):
        body.insert(at + offset, el)
    out[DOCUMENT] = etree.tostring(body.getroottree().getroot(),
                                   xml_declaration=True, encoding="UTF-8",
                                   standalone=True)
    return out


def _candidates(body: etree._Element, span: list[etree._Element],
                anchor: etree._Element, limit: int) -> list[str]:
    """Paragraphs the exhibit could follow, in order, from its mention on.

    Only paragraphs are offered, and only ones with text: an exhibit anchored
    after an empty paragraph or a table lands in a place the author cannot
    name, and the report has to read as an instruction.

    The block's CURRENT predecessor is skipped. It is a legal placement and it
    is the one already in force, so offering it spends a render to discover
    that nothing changed and then prints "no change" beside a move that is not
    one.
    """
    kids = list(body)
    owned = {id(e) for e in span}
    first = kids.index(span[0])
    current = _text(kids[first - 1]).strip() if first else ""
    start = kids.index(anchor)
    out = []
    for el in kids[start:]:
        if el.tag != W + "p" or id(el) in owned or _ends_section(el):
            continue
        text = _text(el).strip()
        if text and text != current:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def repack(parts: dict[str, bytes], *,
           render: Callable[[dict[str, bytes]], list[str]],
           caption: re.Pattern[str] = CAPTION,
           mention: re.Pattern[str] = MENTION,
           note: re.Pattern[str] = NOTE,
           threshold: float = DEFAULT_THRESHOLD,
           max_drift: int = 1,
           max_candidates: int = DEFAULT_MAX_CANDIDATES,
           ) -> RepackReport:
    """Report which sheets are under-filled and which move would fill them.

    `render` is called once for the manuscript as it stands and once per
    alternative placement; it returns the text of each sheet, in order.
    Nothing is written and `parts` is not modified.
    """
    rep = RepackReport(threshold=threshold)
    sheets = render(parts)
    rep.renders = 1
    body = _body(parts)
    blocks = _exhibits(body, caption, note)
    captions = {k: _caption_text(b, caption) for k, b in blocks.items()}
    rep.sheets = _profile(sheets, captions.values())
    rep.underfull, rep.full_lines = _verdict(rep.sheets, threshold)
    if not rep.underfull:
        return rep
    if not blocks:
        rep.problems.append("no exhibit has a caption this pattern matches, "
                            "so nothing can be repositioned")
        return rep

    tried: set[tuple[str, int, str]] = set()
    for sheet_no in rep.underfull:
        # the exhibit that forced the break is the first one landing after
        # this sheet — the break above it is what ended the sheet short
        after = [k for k, cap in captions.items()
                 if (s := _sheet_of(sheets, cap)) is not None and s > sheet_no]
        if not after:
            rep.problems.append(
                f"sheet {sheet_no} is short and no exhibit follows it — "
                "the cause is not a placement this routine can move")
            continue
        key = min(after, key=lambda k: _sheet_of(sheets, captions[k]) or 0)
        label, number = key
        block = blocks[key]
        anchor = _anchor_of(body, label, number, block, mention)
        if anchor is None:
            rep.problems.append(
                f"{label} {number} is mentioned nowhere, so it has no anchor "
                "to drift from and will not be moved")
            continue
        mention_sheet = _sheet_of(sheets, _text(anchor).strip())
        span = _span(body, block)
        for target in _candidates(body, span, anchor, max_candidates):
            # Two under-filled sheets in a row nominate the same exhibit, and
            # rendering its candidates twice costs seconds to print the same
            # row twice. The first run on a real manuscript did exactly that.
            if (label, number, target) in tried:
                continue
            tried.add((label, number, target))
            try:
                trial = _moved(parts, key, target, caption, note)
            except PackageError as exc:            # pragma: no cover - guard
                rep.problems.append(str(exc))
                continue
            out = render(trial)
            rep.renders += 1
            profile = _profile(out, captions.values())
            under = _verdict(profile, threshold)[0]
            landed = _sheet_of(out, captions[key])
            drift = (0 if landed is None or mention_sheet is None
                     else landed - mention_sheet)
            if abs(drift) > max_drift:
                continue
            rep.moves.append(Move(
                number=number, caption=captions[key], after=target,
                drift=drift,
                underfull_before=len(rep.underfull),
                underfull_after=len(under),
                sheets_before=len(sheets), sheets_after=len(out)))

    rep.moves.sort(key=lambda m: (-m.gain, m.costs_a_sheet, abs(m.drift)))
    return rep
