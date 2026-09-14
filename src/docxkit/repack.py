r"""Which sheet is under-filled, and which exhibit's placement is the cause.

`placement` anchors an exhibit to its first mention and keeps it whole, and
says plainly why it stops there:

    moving the block further down the file to chase a page boundary would be
    guessing at a layout only the renderer knows.

That is right when there is no renderer. When there IS one, the guess becomes
a measurement, and this module makes it: it renders the manuscript, finds the
sheets that are mostly empty, works out which exhibit's forced break ended
each one short, and renders every alternative placement to see what it would
actually save. Every number in the report was seen on a rendered page.

**It reports and changes nothing.** The moves are ranked and printed with what
each costs in drift; the caller decides. A page layout is an editorial
judgement — which sheet a reader meets a figure on is not a thing to settle
by arithmetic behind the author's back — and the search is cheap to run
again once they have chosen.

**What the exhibits are is `exhibits`' answer, not this module's.** The
first version carried its own caption regex, its own block walk and its own
mention stem, and the code review of `a90be3a` found eight defects in them:
colon captions invisible, a caption claiming the exhibit above it, an image
absorbed as a spacer, no Box ever finding its mention. All of it is one
layer down now, and this module asks.

**Where an exhibit landed is read off the render in document order.** A
caption's text is not unique on the page — HCW's prose quotes the full
captions of Tables 6 and 7 fifteen sheets before the tables — so each
exhibit is looked for from where the one before it ended, after the prose
paragraph that precedes its block. A table's end is its last row with text,
and every sheet from the caption to that row is the exhibit's: a long
table's continuation pages are 25 % full of prose and 100 % full of table,
and reading them as short nominated the next exhibit for a move that could
not reach them.

**Fill is characters, measured against the fullest TEXT sheet.** A line
count reads a rendered table as enormous (every cell is a line) and a
full-page figure as empty (three lines of caption), and both are wrong in
the direction that matters.

**A move keeps the document's sections whole.** An exhibit that owns its own
section — a break paragraph on each side, AFI's landscape panels — moves
with both; one that closes a section it shares with the prose above leaves
the break where it stands; one alone in the final section cannot move at
all, because its geometry is the body's. A target lies in the exhibit's own
section, or, for a section owner, in one of the same geometry.

**What it does not do.** It never reorders prose, never resizes an exhibit
and never touches spacing: the only variable is which paragraph an exhibit
follows. On a manuscript the paragraph order carries the argument, and a
repacker that improved a page by moving a sentence would be editing.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from lxml import etree

from ._xml import DOCUMENT
from .errors import DocxKitError, PackageError, WordTimeout
from .exhibits import NOTE, Exhibit, exhibits, mention_of, text_of
from .find import DEFAULT_LABELS, heading_level

__all__ = [
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_THRESHOLD",
    "LABELS",
    "Landing",
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

#: The caption words looked for: the package's own, and Box, which
#: Aging_Well has two of and which is an exhibit only when asked for.
LABELS = (*DEFAULT_LABELS, "Box")

#: How much of a caption, a row or a mention is looked for on a sheet: its
#: first forty characters, cut before the whitespace goes. The tail is where
#: a renderer's line break or hyphenation lands.
_PROBE = 40


@dataclass(frozen=True)
class Sheet:
    """One rendered sheet: how much is on it, and whose exhibits span it."""
    number: int
    lines: int
    chars: int = 0
    exhibits: tuple[str, ...] = ()

    @property
    def carries_exhibit(self) -> bool:
        return bool(self.exhibits)


@dataclass(frozen=True)
class Landing:
    """Where one exhibit sits in a render: the sheets its caption and its
    end landed on, and the sheet of its first mention. None is "not
    found on any sheet", and stays None — a drift built on a guess is
    the review's finding 10."""
    name: str
    first: int | None
    last: int | None
    mention: int | None

    @property
    def drift(self) -> int | None:
        """Sheets from the mention to the exhibit; None when unmeasured."""
        if self.first is None or self.mention is None:
            return None
        return self.first - self.mention


@dataclass(frozen=True)
class Move:
    """One alternative placement, and what the render said it would do."""
    name: str
    after: str                  # the target paragraph, as the author reads it
    target: int                 # its body-child index, which is what moved
    drift: int
    drift_before: int | None
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
    landings: list[Landing] = field(default_factory=list)
    underfull: list[int] = field(default_factory=list)
    blamed: dict[int, str | None] = field(default_factory=dict)
    moves: list[Move] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    renders: int = 0
    trials: int = 0
    threshold: float = DEFAULT_THRESHOLD
    full_chars: int = 0

    @property
    def best(self) -> Move | None:
        """The move worth applying, or None: a move that measured no
        change or a loss is reported, never advised."""
        return self.moves[0] if self.moves and self.moves[0].gain > 0 else None

    def format(self) -> str:
        head = (f"{len(self.sheets)} sheet(s); the fullest text sheet "
                f"carries {self.full_chars} characters, and a sheet "
                f"under {self.threshold:.0%} of that is reported")
        lines = [head]
        if not self.sheets:
            lines.append("  not rendered — nothing to measure")
            return "\n".join(lines + [f"  ! {x}" for x in self.problems])
        if not self.underfull:
            lines.append("  no under-filled sheet — nothing to repack")
        for n in self.underfull:
            s = next(x for x in self.sheets if x.number == n)
            share = s.chars / self.full_chars if self.full_chars else 0.0
            cause = self.blamed.get(n)
            why = (f"{cause} starts on sheet {n + 1}" if cause
                   else "no exhibit starts on the sheet after it")
            lines.append(f"  sheet {n}: {s.lines} line(s), {s.chars} "
                         f"characters, {share:.0%} full — {why}")
        if self.trials:
            lines.append(f"  {self.trials} placement(s) tried, "
                         f"{self.renders} render(s):")
        for m in self.moves:
            lines.append(f"    {_describe(m)}")
        if self.trials and not self.moves:
            lines.append("    none within the drift limit")
        return "\n".join(lines + [f"  ! {x}" for x in self.problems])


def _describe(m: Move) -> str:
    # Spelled out rather than signed. `+1 under-filled sheet(s)` was the
    # first wording and it says the OPPOSITE of what it means — the gain
    # is sheets REMOVED, so the best move in a ranked list read as the
    # one that made things worst.
    if m.gain > 0:
        verdict = f"{m.gain} fewer under-filled sheet(s)"
    elif m.gain < 0:
        verdict = f"{-m.gain} MORE under-filled sheet(s)"
    else:
        verdict = "no change"
    sheet = ("" if not m.costs_a_sheet else
             f", {m.sheets_before} -> {m.sheets_after} sheets")
    was = "" if m.drift_before is None else f" (was {m.drift_before:+d})"
    return (f"{m.name} after {m.after!r}: {verdict}{sheet}, "
            f"drift {m.drift:+d}{was}")


# ------------------------------------------------------------ the document

def _body(parts: dict[str, bytes]) -> etree._Element:
    if DOCUMENT not in parts:
        raise PackageError("no word/document.xml in these parts")
    root = etree.fromstring(parts[DOCUMENT])
    body = root.find(W + "body")
    if body is None:
        raise PackageError("word/document.xml has no w:body")
    return body


def _is_break(el: etree._Element) -> bool:
    """A paragraph that looks empty and ends a section."""
    return (el.tag == W + "p" and el.find(f"{W}pPr/{W}sectPr") is not None
            and not text_of(el).strip())


def _is_blank(el: etree._Element) -> bool:
    """A paragraph that puts nothing on the page: no text, no picture and
    no section break."""
    return (el.tag == W + "p" and not text_of(el).strip()
            and el.find(f"{W}pPr/{W}sectPr") is None and not _shows(el))


def _shows(el: etree._Element) -> bool:
    """A table, or a paragraph holding a picture: what a body puts on the
    page."""
    return el.tag == W + "tbl" or next(
        el.iter(W + "drawing", W + "pict", W + "object"), None) is not None


def _covered(found: Iterable[Exhibit]) -> set[int]:
    """Every body-child index inside some exhibit's span."""
    return {i for x in found for i in range(x.start, x.stop)}


def _geometry(sect: etree._Element | None) -> tuple[tuple[str, str], ...]:
    """What a section LOOKS like: page size, margins, columns. Header
    references and ids are left out — two portrait sections with
    different running heads are the same place to put a table."""
    if sect is None:
        return ()
    out: list[tuple[str, str]] = []
    for tag in ("pgSz", "pgMar", "cols"):
        el = sect.find(W + tag)
        if el is not None:
            out.extend((tag + "/" + str(k), str(v))
                       for k, v in sorted(el.attrib.items()))
    return tuple(out)


def _sections(kids: list[etree._Element]) -> list[int]:
    """The section each body child is in, by number, and the geometry of
    each section is read by :func:`_geometry_of`."""
    out, n = [], 0
    for el in kids:
        out.append(n)
        if _is_break(el):
            n += 1
    return out


def _geometry_of(kids: list[etree._Element], body: etree._Element,
                 index: int) -> tuple[tuple[str, str], ...]:
    """The geometry governing body child `index`: the next break's
    `sectPr`, or the body's own for the final section."""
    for el in kids[index:]:
        if _is_break(el):
            return _geometry(el.find(f"{W}pPr/{W}sectPr"))
    return _geometry(body.find(W + "sectPr"))


# ----------------------------------------------------------- the render

def _flat(text: str) -> str:
    return "".join(text.split())


def _flow(sheets: list[str]) -> tuple[str, list[int]]:
    """Every sheet flattened into one string, and where each one starts."""
    flats = [_flat(s) for s in sheets]
    starts, at = [], 0
    for f in flats:
        starts.append(at)
        at += len(f)
    return "".join(flats), starts


def _sheet_at(starts: list[int], pos: int) -> int:
    return bisect_right(starts, pos)


def _end_probes(x: Exhibit) -> list[str]:
    """Text that marks the exhibit's END on the page, last first.

    A table's last rows with text, cells separated as the page reads
    them; a box's last paragraphs. Several rather than one, because a
    row is not always on the page as the markup spells it: LE's Table 9
    ends on a row of parameter symbols set in OMML, which `w:t` does
    not carry, and the row before it is where the table can be seen to
    end. Empty for a figure, whose end is its caption.
    """
    tables = [e for e in x.elements if e.tag == W + "tbl"]
    if not tables:
        return []
    if x.kind == "box":
        lines = [text_of(p).strip() for p in tables[-1].iter(W + "p")]
    else:
        lines = [" ".join(text_of(tc) for tc in tr.findall(W + "tc")).strip()
                 for tr in tables[-1].findall(W + "tr")]
    return [ln for ln in reversed(lines) if ln][:5]


def _land(sheets: list[str], kids: list[etree._Element],
          found: list[Exhibit], mentions: dict[tuple[str, str], int | None],
          ) -> list[Landing]:
    """Where each exhibit sits in this render, in document order.

    The cursor never moves backwards: each exhibit is looked for from
    where the previous one ended, and from the prose paragraph in front
    of its block when that is found first. That is what keeps a caption
    quoted in earlier prose from being read as the exhibit (HCW's
    Tables 6 and 7, quoted on sheet 13, sit on 29 and 30).
    """
    text, starts = _flow(sheets)
    covered = _covered(found)
    out: list[Landing] = []
    cursor = 0
    for x in found:
        mention = _mention_sheet(text, starts, kids, mentions.get(x.key))
        probe = _flat(x.caption[:_PROBE])
        at = -1
        if x.start and x.start - 1 not in covered:
            # from the prose in front of the block, when it is found —
            # and from the cursor when the caption is not found after
            # it, since prose can be quoted too
            lead = _flat(text_of(kids[x.start - 1]).strip()[:_PROBE])
            lead_at = text.find(lead, cursor) if lead else -1
            if lead_at >= 0 and probe:
                at = text.find(probe, lead_at)
        if at < 0:                          # else from the cursor
            at = text.find(probe, cursor) if probe else -1
        if at < 0:
            out.append(Landing(x.name, None, None, mention))
            continue
        first = _sheet_at(starts, at)
        cursor = at + len(probe)
        last: int | None = first
        for end in (_flat(e[:_PROBE]) for e in _end_probes(x)):
            hit = text.find(end, cursor)
            if hit >= 0:
                cursor = hit + len(end)
                last = _sheet_at(starts, cursor - 1)
                break
        else:
            if _end_probes(x):
                last = None
        out.append(Landing(x.name, first, last, mention))
    return out


def _mention_sheet(text: str, starts: list[int], kids: list[etree._Element],
                   index: int | None) -> int | None:
    if index is None:
        return None
    probe = _flat(text_of(kids[index]).strip()[:_PROBE])
    at = text.find(probe) if probe else -1
    return _sheet_at(starts, at) if at >= 0 else None


def _profile(sheets: list[str], landings: list[Landing]) -> list[Sheet]:
    on: dict[int, list[str]] = {n: [] for n in range(1, len(sheets) + 1)}
    for x in landings:
        if x.first is None:
            continue
        for n in range(x.first, (x.last or x.first) + 1):
            if n in on:
                on[n].append(x.name)
    out = []
    for i, page in enumerate(sheets, 1):
        rows = [ln for ln in page.splitlines() if ln.strip()]
        out.append(Sheet(number=i, lines=len(rows),
                         chars=len("".join(rows)), exhibits=tuple(on[i])))
    return out


def _verdict(profile: list[Sheet], threshold: float) -> tuple[list[int], int]:
    """Under-filled sheets, and the fullest text sheet's character count.

    A sheet an exhibit spans is an exhibit sheet, whatever it holds:
    a full-page figure carries three lines of caption, and a long
    table's middle pages carry no prose at all. The FIRST and LAST
    sheets are never under-filled: a title page is short because it is
    a title page, and a document ends where it ends.
    """
    text_sheets = [s for s in profile if not s.carries_exhibit]
    full = max((s.chars for s in text_sheets), default=0)
    if not full:
        return [], 0
    edges = {profile[0].number, profile[-1].number} if profile else set()
    under = [s.number for s in text_sheets
             if s.number not in edges and s.chars / full < threshold]
    return under, full


def _blame(underfull: list[int],
           landings: list[Landing]) -> dict[int, str | None]:
    """The exhibit whose forced break ended each short sheet: the one
    that STARTS on the sheet after it. A short sheet followed by prose —
    a heading with a page break before it, a section's last page — is
    nobody's, and says so rather than nominating the next exhibit down."""
    return {n: next((x.name for x in landings if x.first == n + 1), None)
            for n in underfull}


# ------------------------------------------------------------- the moves

def _move_span(kids: list[etree._Element], x: Exhibit,
               ) -> tuple[int, int] | str:
    """What moves when `x` moves — `(start, stop)` — or why it cannot.

    A section-break paragraph on each side means the exhibit OWNS a
    section (a landscape page of panels), and both travel with it. A
    break under it alone closes a section it shares with the prose
    above, and stays where it stands; one above it alone opens a section
    it shares with what follows, and stays too. An exhibit alone in the
    FINAL section has the body's own `sectPr` for geometry, which cannot
    travel.
    """
    if x.body_at is None:
        return "has no table or image of its own"
    start, stop = x.start, x.stop
    opens = start > 0 and _is_break(kids[start - 1])
    # A blank under the closing break is the NEXT section's, and `exhibits`
    # absorbs it into the span all the same: judged with it, an exhibit
    # that owns its section read as sharing one and moved without either
    # break (code review, 2026-09-13).
    last = stop
    while last > start and _is_blank(kids[last - 1]):
        last -= 1
    breaks = [i for i in range(start, last) if _is_break(kids[i])]
    # A note under the closing break is absorbed the same way and is NOT
    # the next section's: asked whether the span ended on a break, an owner
    # with one read as sharing its section again (mutation sweep,
    # 2026-09-13). The section is closed when no body follows the break.
    ends = bool(breaks) and not any(map(_shows, kids[breaks[-1]:last]))
    if opens and ends:
        return start - 1, last
    if breaks:
        stop = breaks[0]                     # the break is not the block's
    if opens and all(not (el.tag in (W + "p", W + "tbl")
                          and (text_of(el).strip() or el.tag == W + "tbl"))
                     for el in kids[x.stop:]):
        return "is alone in the final section, whose geometry is the body's"
    return start, stop


#: The heading that opens a reference list, in the languages these
#: manuscripts are written in.
_REFERENCES = re.compile(
    r"^\s*(?:references|bibliography|works cited|literature(?: cited)?"
    r"|список литературы|литература|библиография)\b", re.IGNORECASE)


def _reference_zone(kids: list[etree._Element]) -> set[int]:
    """Body-child indices inside the reference list: from its heading to
    the next heading. Not a place for an exhibit, and for the exhibits
    grouped behind it the nearest prose there is — Parental_style's
    Table 1 was offered eight reference entries to follow."""
    zone: set[int] = set()
    inside = False
    for i, el in enumerate(kids):
        if el.tag != W + "p":
            continue
        level = heading_level(etree.tostring(el, encoding="unicode"))
        if level is not None:
            inside = _REFERENCES.match(text_of(el)) is not None
        elif inside:
            zone.add(i)
    return zone


def _candidates(kids: list[etree._Element], body: etree._Element,
                found: list[Exhibit], x: Exhibit, *, span: tuple[int, int],
                anchor: int, limit: int) -> list[tuple[int, str]]:
    """``(body index, what the author is told)`` for each place the
    exhibit could follow, from its mention on, nearest to where it sits
    first.

    Two kinds of place. A prose paragraph — not another exhibit's
    caption or note (the review's case 12: a trial that put Figure 1
    between Table 1's caption and its table, and ranked it first), not
    a heading, not a section break, not a reference entry. And the END
    of another exhibit's block, which is the only kind of place there is
    for the exhibits grouped at the back of a paper, where every one of
    them sits twenty sheets from its mention and the cure for a short
    sheet is a shorter table first.

    In a section the exhibit may sit in: its own, or, when it owns one,
    any of the same geometry. The place it already follows is skipped,
    since that trial can only say "no change". Nearest first, because
    the likeliest fix for a page break is a small move, and a limit
    counted from the mention never reached the back of the paper.
    """
    ms, me = span
    owns = ms < x.start
    sections = _sections(kids)
    home = _geometry_of(kids, body, ms) if owns else sections[x.start]
    ends = {y.stop - 1: f"{y.name} and its notes" for y in found
            if y.key != x.key}
    covered = _covered(found) | _reference_zone(kids)
    out: list[tuple[int, str]] = []
    for j in range(anchor, len(kids)):
        el = kids[j]
        if ms <= j < me or j == ms - 1:
            continue
        if j in ends:
            label = ends[j]
        elif (j in covered or el.tag != W + "p" or not text_of(el).strip()
                or _is_break(el)
                or heading_level(etree.tostring(el, encoding="unicode"))
                is not None):
            continue
        else:
            label = text_of(el).strip()[:60]
        # inserted AFTER `j`: a block that ends on a section break lands
        # in the section the break opens, not the one it closes
        at = j + 1 if _is_break(el) and j + 1 < len(kids) else j
        there = _geometry_of(kids, body, at) if owns else sections[at]
        if there == home:
            out.append((j, label))
    out.sort(key=lambda c: abs(c[0] - ms))
    return out[:limit]


def _moved(parts: dict[str, bytes], key: tuple[str, str], target: int, *,
           labels: tuple[str, ...], note: re.Pattern[str]) -> dict[str, bytes]:
    """A copy of `parts` with the exhibit at `key` moved to just after
    body child `target`. By INDEX, not by text: three figures each
    followed by the same `Source:` line put Figure 2 under Figure 1's."""
    out = dict(parts)
    body = _body(out)
    kids = list(body)
    x = next((e for e in exhibits(body, labels=labels, note=note)
              if e.key == key), None)
    if x is None:
        raise PackageError(f"no exhibit {key[0]} {key[1]} with a caption")
    span = _move_span(kids, x)
    if isinstance(span, str):
        raise PackageError(f"{x.name} {span}")
    ms, me = span
    if ms <= target < me:
        raise PackageError(f"the target lies inside {x.name}'s own block")
    block, after = kids[ms:me], kids[target]
    for el in block:
        body.remove(el)
    at = list(body).index(after)
    for offset, el in enumerate(block, 1):
        body.insert(at + offset, el)
    out[DOCUMENT] = etree.tostring(body.getroottree().getroot(),
                                   xml_declaration=True, encoding="UTF-8",
                                   standalone=True)
    return out


def _measure(parts: dict[str, bytes], render: Callable[[dict[str, bytes]],
                                                       list[str]], *,
             labels: tuple[str, ...], note: re.Pattern[str],
             threshold: float) -> tuple[list[str], list[Landing], list[int]]:
    """One render: its sheets, where every exhibit landed, what is short."""
    body = _body(parts)
    kids = list(body)
    found = exhibits(body, labels=labels, note=note)
    mentions = {x.key: mention_of(body, x) for x in found}
    sheets = render(parts)
    landings = _land(sheets, kids, found, mentions)
    return sheets, landings, _verdict(_profile(sheets, landings), threshold)[0]


def repack(parts: dict[str, bytes], *,
           render: Callable[[dict[str, bytes]], list[str]],
           labels: tuple[str, ...] = LABELS,
           note: re.Pattern[str] = NOTE,
           threshold: float = DEFAULT_THRESHOLD,
           max_drift: int = 1,
           max_candidates: int = DEFAULT_MAX_CANDIDATES,
           ) -> RepackReport:
    """Report which sheets are under-filled and which move would fill them.

    `render` is called once for the manuscript as it stands and once per
    alternative placement; it returns the text of each sheet, in order.
    A trial whose render fails is reported and skipped; a second failure
    in a row ends the search, since a renderer that has stopped
    answering will not answer the next one. Nothing is written and
    `parts` is not modified.
    """
    rep = RepackReport(threshold=threshold)
    body = _body(parts)
    kids = list(body)
    found = exhibits(body, labels=labels, note=note)
    mentions = {x.key: mention_of(body, x) for x in found}
    sheets = render(parts)
    rep.renders = 1
    rep.landings = _land(sheets, kids, found, mentions)
    rep.sheets = _profile(sheets, rep.landings)
    rep.underfull, rep.full_chars = _verdict(rep.sheets, threshold)
    _unlocated(rep, found)
    if not rep.underfull:
        return rep
    rep.blamed = _blame(rep.underfull, rep.landings)
    by_name = {x.name: x for x in found}
    landed = {x.name: x for x in rep.landings}
    tried: set[tuple[tuple[str, str], int]] = set()
    failed = 0
    for n in rep.underfull:
        name = rep.blamed[n]
        if name is None:
            continue
        x = by_name[name]
        span = _move_span(kids, x)
        if isinstance(span, str):
            rep.problems.append(f"{name} {span} — left where it is")
            continue
        anchor = mentions[x.key]
        if anchor is None:
            rep.problems.append(f"{name} is mentioned nowhere, so it has no "
                                "anchor to drift from and will not be moved")
            continue
        before = landed[name].drift
        # an exhibit already twenty sheets from its mention — every one
        # grouped at the back of a paper — may move as long as it comes
        # no further away; the absolute limit is for the rest
        allowed = max(max_drift, abs(before)) if before is not None else (
            max_drift)
        for target, after in _candidates(kids, body, found, x, span=span,
                                         anchor=anchor, limit=max_candidates):
            if (x.key, target) in tried:
                continue
            tried.add((x.key, target))
            try:
                trial = _moved(parts, x.key, target, labels=labels, note=note)
                out, landings, under = _measure(
                    trial, render, labels=labels, note=note,
                    threshold=threshold)
            except WordTimeout:
                raise
            except DocxKitError as exc:
                rep.trials += 1
                failed += 1
                rep.problems.append(f"{name} after {after!r}: the render "
                                    f"failed and the move is unmeasured "
                                    f"({exc})")
                if failed >= 2:
                    rep.problems.append("two renders failed in a row — the "
                                        "search stopped there")
                    return _ranked(rep)
                continue
            failed = 0
            rep.renders += 1
            rep.trials += 1
            there = next(z for z in landings if z.name == name)
            if there.drift is None:
                what = "its caption" if there.first is None else "its mention"
                rep.problems.append(
                    f"{name} after {after!r}: {what} was found on no sheet "
                    f"of the trial render, so the drift is unmeasured — "
                    f"not offered")
                continue
            if abs(there.drift) > allowed:
                continue
            rep.moves.append(Move(
                name=name, after=after, target=target, drift=there.drift,
                drift_before=before,
                underfull_before=len(rep.underfull),
                underfull_after=len(under),
                sheets_before=len(sheets), sheets_after=len(out)))
    return _ranked(rep)


def _unlocated(rep: RepackReport, found: list[Exhibit]) -> None:
    kinds = {x.name: x.kind for x in found}
    for z in rep.landings:
        if z.first is None:
            rep.problems.append(f"{z.name}: its caption was found on no "
                                "sheet, so no sheet is counted as its")
        elif z.last is None and kinds.get(z.name) != "figure":
            rep.problems.append(f"{z.name}: its last row was found on no "
                                f"sheet after its caption (sheet {z.first}), "
                                "so only that sheet is counted as its")


def _ranked(rep: RepackReport) -> RepackReport:
    rep.moves.sort(key=lambda m: (-m.gain, m.costs_a_sheet, abs(m.drift)))
    return rep
