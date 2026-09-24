r"""The section numbering, and every mention of it.

On 10 September 2026 the author of Aging_Well merged Section 3 and
Section 4 by hand, in Word — one deleted heading paragraph. The headings
then ran 1 2 3 5 6 7 8 9, seven sentences went on pointing at a Section 4
that no longer existed, and the paper was ingested, gated and BASELINED
that way, because not one of nine commands knows what a section number
is: `citations` reads the reference apparatus, `crossrefs` reads Figure /
Table / Box captions, `refstyle` the entry list, `lint` the markup,
`math` the equations, `footnotes` the notes, `pages` the sheets,
`compare` the revisions. A merge is the cheapest edit there is, and the
sections renumber themselves in the reader's head and nowhere in the
file.

`crossrefs --labels Section` looks like the extension point and is not:
`find.caption_re` wants a label word and a separator in a CAPTION
paragraph, while a section is a heading whose number is a prefix on its
title (`4.2 Model implications`). It found nothing and reported that
cleanly — the all-zero audit this toolkit's backlog has closed before.

So this reads two things and cross-checks them:

* the **headings** — every paragraph `find.heading_level` calls a
  heading whose text opens on a number. The top-level numbers must run
  1..N in document order; a `K.M` subhead must sit under heading `K`,
  and each parent's children must run 1..M; an appendix's `A.N` likewise,
  under its `Appendix A` heading, whatever the letter;
* every **mention** in the body, footnotes and endnotes — `Section N`,
  `Section N.M`, `§ N.M`, `Sections X and Y`, `Sections X, Y and Z`,
  `Sections X to Y` / `through` / `X–Y`, `Appendix A.N` and a bare `A.N`
  — must name a heading that exists, and a range must run upward.

The paper's own version of this (`r122_section_integrity.py`) found all
eight breaches on the merged truth, none on 69 redlines and three older
truths, and dated the merge to a hand pass six hours before anyone
looked. Two of its lessons are kept here rather than left in that file:
**a section number MOVES**, so a gate that holds one — the paper's
"every equation lives in Section 5" — reads it off the heading's title
through :meth:`SectionReport.number_of` instead of a literal; and the
renumbering that follows a merge is the second, harder half, which is
:func:`renumber` below: sequential rules cannot renumber sections
(`5->4` then `6->5` cannot tell its own output from its input, and a
merge makes the map non-monotone), ranges must be rewritten rather than
mapped (`Sections 2 through 4` becomes `Sections 2 and 3`), and a
mention split across two runs must be refused rather than missed.

A heading's number is the one the READER sees: typed at the start of its
text, or printed by Word from list numbering (:func:`list_numbers`). A
paper with no numbered heading at all is reported NOT CHECKED rather
than every mention a breach.

Nothing here writes a file: `audit` reads, and `renumber` returns a new
parts dict for the caller to save.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import pairwise

from ._xml import (
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    PARA_RE,
    T_RUN_RE,
    Parts,
    live_properties,
    run_spans,
    set_run_text,
    visible_text,
)
from .errors import AnchorError
from .find import _PSTYLE_RE, heading_level

__all__ = [
    "AnchorError",
    "Heading",
    "Renumbering",
    "SectionReport",
    "audit",
    "headings",
    "list_numbers",
    "renumber",
]

#: "1. Introduction" / "5.1 The model" / "2.1.3 Deeper" / "A.3 First-order
#: conditions" — a letter for an appendix, then digits, then the title.
#: The number ENDS at whitespace: "1.Introduction" is not numbered.
_NUMBER_RE = re.compile(
    r"^\s*(?:([A-Z])\.)?(\d+(?:\.\d+)*)\.?(?=\s|$)")
#: "Appendix", "Appendix A", "Appendix B: Proofs" — the heading that opens
#: an appendix and names its letter (A when it names none).
_APPENDIX_RE = re.compile(r"^\s*Appendix(?:\s+([A-Z]))?\b", re.IGNORECASE)

#: What joins the members of a list or range of sections. The range
#: words (and the dashes) are the ones that must run upward.
_JOIN = r"(?:,\s*|\s+and\s+|\s+through\s+|\s+to\s+|\s*[–—-]\s*)"
_NUM = r"\d+(?:\.\d+)?"
_LIST_RE = re.compile(rf"\bSections\s+({_NUM}(?:{_JOIN}{_NUM})+)")
_JOIN_RE = re.compile(_JOIN)
_RANGE_JOIN_RE = re.compile(r"^(?:\s*[–—-]\s*|\s+through\s+|\s+to\s+)$")
_ONE_RE = re.compile(rf"(?:\bSection\s+|§\s*)({_NUM})")
_APX_RE = re.compile(r"\bAppendix\s+([A-Z])\.(\d+)")
#: a bare "A.3": not after a word character or a dot (an initial, a
#: decimal), not an exhibit's number ("Table A.3"), and not the "A.3" of
#: "Appendix A.3", which `_APX_RE` already counts
_BARE_RE = re.compile(
    r"(?<![\w.])(?<!Appendix )(?<!Table )(?<!Figure )(?<!Box )(?<!Panel )"
    r"(?<!Chart )(?<!Equation )([A-Z])\.(\d+)(?!\d)")
#: What a bare "A.3" is when it is not a section, and the lookbehinds
#: above (one label, one space) cannot see: an equation's number, "(A.7)",
#: and an exhibit's in a plural, in a list or after a no-break space —
#: "Tables A.3 and A.4", "Figures A.1-A.2". Each read as a dangling
#: section, and `renumber` rewrote them (code review, 2026-09-13).
_NOT_A_SECTION_RE = re.compile(
    r"\b(?:Tables?|Figures?|Box(?:es)?|Panels?|Charts?|Equations?|Eqs?\.)"
    rf"\s+[A-Z]\.\d+(?:{_JOIN}[A-Z]\.\d+)*|\([A-Z]\.\d+\)")

_TEXT_PARTS = (DOCUMENT, FOOTNOTES, ENDNOTES)
_STYLES = "word/styles.xml"
_NUMBERING = "word/numbering.xml"

# ------------------------------------------------ Word's own list numbers ---
#
# Six of the eight manuscripts measured on 2026-09-12 type no number into a
# heading at all: the heading STYLE carries a `w:numPr` (AFI, HCW, HPPA, LE,
# LI) or the paragraph does (Parental), and Word prints "2.1." from
# numbering.xml. Reading typed numbers only, the audit found no section on
# any of them and reported every "Section N" in their prose as a breach — a
# gate red on six papers of eight, for nothing wrong.

#: Stops at the FIRST `</w:pPr>`, which is the snapshot's inside a
#: `w:pPrChange` when there is one: read what it holds through
#: `live_properties`, never as it stands (code review, 2026-09-13).
_PPR_RE = re.compile(r"<w:pPr>(.*?)</w:pPr>", re.DOTALL)
_NUMPR_RE = re.compile(r"<w:numPr>(.*?)</w:numPr>", re.DOTALL)
_NUMID_RE = re.compile(r'<w:numId w:val="(\d+)"')
_ILVL_RE = re.compile(r'<w:ilvl w:val="(\d+)"')
_STYLE_RE = re.compile(
    r'<w:style\b([^>]*)w:styleId="([^"]+)"[^>]*>(.*?)</w:style>', re.DOTALL)
_BASED_RE = re.compile(r'<w:basedOn w:val="([^"]+)"')
_NUM_RE = re.compile(r'<w:num\b[^>]*w:numId="(\d+)"[^>]*>(.*?)</w:num>',
                     re.DOTALL)
_ABSTRACT_ID_RE = re.compile(r'<w:abstractNumId w:val="(\d+)"')
_OVERRIDE_RE = re.compile(
    r'<w:lvlOverride w:ilvl="(\d+)"[^>]*>(.*?)</w:lvlOverride>', re.DOTALL)
_ABSTRACT_RE = re.compile(
    r'<w:abstractNum\b[^>]*w:abstractNumId="(\d+)"[^>]*>(.*?)</w:abstractNum>',
    re.DOTALL)
_LVL_RE = re.compile(r'<w:lvl\b[^>]*w:ilvl="(\d+)"[^>]*>(.*?)</w:lvl>',
                     re.DOTALL)
_STYLE_LINK_RE = re.compile(r'<w:numStyleLink w:val="([^"]+)"')


def _val(tag: str, xml: str) -> str | None:
    m = re.search(rf'<w:{tag} w:val="([^"]*)"', xml)
    return m.group(1) if m else None


@dataclass(frozen=True)
class _Level:
    start: int
    fmt: str
    text: str
    legal: bool          # w:isLgl: every placeholder printed as decimal
    style: str | None    # the paragraph style this level is linked to
    restart: int | None  # w:lvlRestart, one-based; None is "after any higher"


def _numbered(ppr: str) -> tuple[str | None, str | None]:
    """(numId, ilvl) a `w:pPr` body states, either possibly None."""
    m = _NUMPR_RE.search(live_properties(ppr))
    if m is None:
        return None, None
    num, lvl = _NUMID_RE.search(m.group(1)), _ILVL_RE.search(m.group(1))
    return (num.group(1) if num else None), (lvl.group(1) if lvl else None)


def _style_numbering(styles: str) -> tuple[
        dict[str, tuple[str | None, str | None]], str | None]:
    """Each paragraph style's (numId, ilvl), read up its `basedOn` chain
    one attribute at a time; and the default paragraph style's id."""
    raw: dict[str, tuple[str | None, str | None, str | None]] = {}
    default = None
    for m in _STYLE_RE.finditer(styles):
        head = m.group(0)[:m.start(3) - m.start()]     # the opening tag
        sid, body = m.group(2), m.group(3)
        if 'w:type="paragraph"' in head and 'w:default="1"' in head:
            default = sid
        ppr = _PPR_RE.search(body)
        num, lvl = _numbered(ppr.group(1)) if ppr else (None, None)
        based = _BASED_RE.search(body)
        raw[sid] = (num, lvl, based.group(1) if based else None)
    out: dict[str, tuple[str | None, str | None]] = {}
    for sid in raw:
        num = lvl = None
        seen: set[str] = set()
        at: str | None = sid
        while at is not None and at in raw and at not in seen:
            seen.add(at)
            n, v, up = raw[at]
            num = num if num is not None else n
            lvl = lvl if lvl is not None else v
            at = up
        out[sid] = (num, lvl)
    return out, default


def _definitions(numbering: str,
                 by_style: dict[str, tuple[str | None, str | None]]
                 ) -> tuple[dict[str, tuple[str, dict[int, int]]],
                            dict[str, dict[int, _Level]]]:
    """numId -> (abstractNumId, start overrides) and each abstract's levels,
    with a `numStyleLink` followed to the levels it borrows."""
    nums: dict[str, tuple[str, dict[int, int]]] = {}
    for m in _NUM_RE.finditer(numbering):
        aid = _ABSTRACT_ID_RE.search(m.group(2))
        if aid is None:
            continue
        starts = {int(o.group(1)): int(s)
                  for o in _OVERRIDE_RE.finditer(m.group(2))
                  if (s := _val("startOverride", o.group(2))) is not None}
        nums[m.group(1)] = (aid.group(1), starts)
    abstracts: dict[str, dict[int, _Level]] = {}
    links: dict[str, str] = {}
    for m in _ABSTRACT_RE.finditer(numbering):
        levels = {}
        for lv in _LVL_RE.finditer(m.group(2)):
            body = lv.group(2)
            restart = _val("lvlRestart", body)
            levels[int(lv.group(1))] = _Level(
                start=int(_val("start", body) or 0),
                fmt=_val("numFmt", body) or "decimal",
                text=_val("lvlText", body) or "",
                legal="<w:isLgl" in body,
                style=_val("pStyle", body),
                restart=int(restart) if restart is not None else None)
        abstracts[m.group(1)] = levels
        if (link := _STYLE_LINK_RE.search(m.group(2))) is not None:
            links[m.group(1)] = link.group(1)
    for owner, style in links.items():
        num = by_style.get(style, (None, None))[0]
        if num is not None and num in nums and not abstracts.get(owner):
            abstracts[owner] = abstracts.get(nums[num][0], {})
    return nums, abstracts


_ROMAN = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
          (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"),
          (4, "iv"), (1, "i"))


def _format(n: int, fmt: str) -> str:
    """One counter as Word prints it in `fmt`."""
    if fmt in ("upperLetter", "lowerLetter"):
        letter = chr(ord("a") + (n - 1) % 26) * ((n - 1) // 26 + 1)
        return letter.upper() if fmt == "upperLetter" else letter
    if fmt in ("upperRoman", "lowerRoman"):
        out, rest = "", n
        for value, glyph in _ROMAN:
            while rest >= value:
                out, rest = out + glyph, rest - value
        return out.upper() if fmt == "upperRoman" else out
    if fmt == "decimalZero":
        return f"{n:02d}"
    return "" if fmt == "none" else str(n)


def list_numbers(parts: Parts) -> dict[int, str]:
    """The number Word prints before each numbered BODY paragraph, keyed
    by the paragraph's index in `PARA_RE` order — "2.1." as laid out.

    Resolved the way Word resolves it: the paragraph's own `w:numPr`
    over its style's, a style's read up its `basedOn` chain (HCW's
    Heading2 states only `ilvl` 1 and takes numId 4 from Heading1), a
    missing `ilvl` from the level linked to the style, then counted per
    abstract definition in document order with the deeper levels
    restarting. Bullets are not numbers and are left out.
    """
    blob = parts.get(_NUMBERING)
    if not blob:
        return {}
    by_style, default = _style_numbering(
        parts.get(_STYLES, b"").decode("utf-8"))
    nums, abstracts = _definitions(blob.decode("utf-8"), by_style)
    counters: dict[str, dict[int, int]] = {}
    started: set[str] = set()
    out: dict[int, str] = {}
    body = parts[DOCUMENT].decode("utf-8")
    for i, m in enumerate(PARA_RE.finditer(body)):
        ppr = _PPR_RE.search(m.group(0))
        live = live_properties(ppr.group(1)) if ppr else ""
        own_num, own_lvl = _numbered(live)
        style_m = _PSTYLE_RE.search(live)
        style = style_m.group(1) if style_m else default
        style_num, style_lvl = by_style.get(style or "", (None, None))
        num = own_num if own_num is not None else style_num
        if num is None or num == "0" or num not in nums:
            continue
        aid, overrides = nums[num]
        levels = abstracts.get(aid, {})
        if own_num is not None:
            lvl = own_lvl
        else:
            lvl = own_lvl if own_lvl is not None else style_lvl
            if lvl is None:
                lvl = next((str(k) for k, v in levels.items()
                            if v.style == style), "0")
        ilvl = int(lvl or 0)
        if ilvl not in levels or levels[ilvl].fmt == "bullet":
            continue
        count = counters.setdefault(aid, {})
        if num not in started:
            started.add(num)
            for k, value in overrides.items():
                count[k] = value - 1
        count[ilvl] = (count[ilvl] + 1 if ilvl in count
                       else levels[ilvl].start)
        for k in [k for k in count if k > ilvl]:
            restart = levels[k].restart if k in levels else None
            if restart != 0 and (restart is None or ilvl < restart):
                del count[k]
        level = levels[ilvl]

        def printed(match: re.Match[str], count: dict[int, int] = count,
                    levels: dict[int, _Level] = levels,
                    legal: bool = level.legal) -> str:
            k = int(match.group(1)) - 1
            at = levels.get(k)
            value = count.get(k, at.start if at else 0)
            return _format(value, "decimal" if legal or at is None
                           else at.fmt)

        out[i] = re.sub(r"%([1-9])", printed, level.text)
    return out


@dataclass(frozen=True)
class Heading:
    """One heading paragraph: its number as the reader sees it, or ""."""

    number: str         # "1", "5.1", "A.3" — "" for an unnumbered heading
    title: str          # the text after the number
    level: int          # from `find.heading_level`
    listed: bool = False
    """The number is Word's, from list numbering, not typed text."""


@dataclass
class SectionReport:
    """What :func:`audit` found. `ok` is the gate."""

    headings: list[Heading] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    breaches: list[str] = field(default_factory=list)
    mentions: int = 0
    checked: bool = True
    """False when no heading carries a number, typed or Word's: the
    mentions were counted and had nothing to resolve against."""

    @property
    def ok(self) -> bool:
        return not self.breaches

    def number_of(self, title: str) -> str | None:
        """The number of the heading whose title opens with `title`
        (case-insensitive), or None.

        For a gate that needs a section: Aging_Well's `r64` held the
        literal 5 for "every equation lives in Section 5 or the
        Appendix", and after the renumbering reported all five of the
        paper's displays as breaches — the paper right, the gate wrong,
        which is the worst way a gate can fail because the obvious
        response is to "fix" the paper. A section number moves; the
        title is what stays.
        """
        want = title.strip().casefold()
        for h in self.headings:
            if h.number and h.title.casefold().startswith(want):
                return h.number
        return None

    def format(self) -> str:
        tops = [s for s in self.sections if "." not in s]
        apx = [s for s in self.sections if s[:1].isalpha()]
        lines = [(f"{len(self.headings)} heading(s), {len(tops)} section(s)"
                  f", {len(apx)} appendix subsection(s), "
                  f"{self.mentions} mention(s)"),
                 "  sections : " + " ".join(tops),
                 "  appendix : " + " ".join(apx)]
        if not self.checked:
            lines.append(f"  not checked - no heading carries a number, "
                         f"typed or Word's own, so the {self.mentions} "
                         f"mention(s) have nothing to resolve against")
        elif self.breaches:
            lines.append(f"  ** {len(self.breaches)} breach(es) of the "
                         "section numbering")
            lines += [f"     ** {b}" for b in self.breaches]
        else:
            lines.append("  ok - the headings run 1..N and every mention "
                         "resolves")
        return "\n".join(lines)


#: A list number as Word prints it, "2.", "2.1." or "A.3": the number
#: and an optional closing dot. "Chapter 1" is not a section number.
_LISTED_RE = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+)*)\.?\s*$")


def headings(xml: str, numbers: Mapping[int, str] | None = None
             ) -> list[Heading]:
    """Every heading in `xml`, in order, numbered as the reader sees it.

    `numbers` is :func:`list_numbers` for the same body, the number Word
    prints before a paragraph, by index. A heading it numbers takes that
    number and keeps its whole text as the title; one it does not falls
    back to a number typed at the start of its text.
    """
    out = []
    for i, m in enumerate(PARA_RE.finditer(xml)):
        level = heading_level(m.group(0))
        if level is None:
            continue
        text = visible_text(m.group(0)).strip()
        listed = _LISTED_RE.match((numbers or {}).get(i, ""))
        if listed is not None:
            out.append(Heading(listed.group(1), text, level, listed=True))
            continue
        n = _NUMBER_RE.match(text)
        if n is None:
            out.append(Heading("", text, level))
            continue
        number = f"{n.group(1)}.{n.group(2)}" if n.group(1) else n.group(2)
        out.append(Heading(number, text[n.end():].strip(), level))
    return out


def _check_headings(heads: list[Heading], report: SectionReport) -> set[str]:
    """The numbering itself. Returns every number that exists."""
    bad = report.breaches
    seen: set[str] = set()
    children: dict[str, list[int]] = {"": []}
    chain: list[str] = []          # the numbers above the last heading
    appendix: str | None = None    # the letter the last Appendix heading set
    for h in heads:
        if not h.number:
            if (a := _APPENDIX_RE.match(h.title)) is not None:
                appendix = a.group(1) or "A"
                chain = []
            continue
        if h.number in seen:
            bad.append(f"Section {h.number}: the number is used twice")
        seen.add(h.number)
        parts = h.number.split(".")
        parent = ".".join(parts[:-1])
        if parts[0].isalpha():
            if appendix is None:
                bad.append(f"{h.number} {h.title[:40]!r}: an appendix "
                           f"subhead before any Appendix heading")
            children.setdefault(parent, []).append(int(parts[-1]))
            continue
        depth = len(parts)
        if depth > 1 and parent not in chain[:depth - 1]:
            above = chain[depth - 2] if len(chain) >= depth - 1 else None
            # a level skipped under a heading that IS there is that level
            # missing, not the top one (mutation sweep, 2026-09-13)
            bad.append(f"Section {h.number}: "
                       + (f"sits under Section {above}" if above
                          else f"no Section {parent} above it" if chain
                          else "no top-level heading above it"))
        chain = [".".join(parts[:i]) for i in range(1, depth + 1)]
        children.setdefault(parent, []).append(int(parts[-1]))
    for parent, got in children.items():
        want = list(range(1, len(got) + 1))
        if got == want:
            continue
        if parent == "":
            bad.append(f"the top-level headings run {_run(got)} — expected "
                       f"{_run(want)}")
        elif parent.isalpha():
            bad.append(f"the appendix subheads run "
                       f"{' '.join(f'{parent}.{g}' for g in got)}")
        else:
            bad.append(f"Section {parent}: subsections run "
                       f"{' '.join(f'{parent}.{g}' for g in got)}")
    return seen


def _run(numbers: list[int]) -> str:
    return " ".join(str(n) for n in numbers)


def _bare(text: str, pos: int = 0) -> list[re.Match[str]]:
    """The bare "A.3" mentions in `text` from `pos`: `_BARE_RE`'s matches,
    less the equation and exhibit numbers `_NOT_A_SECTION_RE` claims."""
    taken = [m.span() for m in _NOT_A_SECTION_RE.finditer(text)]
    return [m for m in _BARE_RE.finditer(text, pos)
            if not any(lo <= m.start() < hi for lo, hi in taken)]


def _check_mentions(paras: list[str], exists: set[str],
                    report: SectionReport) -> None:
    bad = report.breaches
    for text in paras:
        for m in _LIST_RE.finditer(text):
            report.mentions += 1
            members = _JOIN_RE.split(m.group(1))
            joins = _JOIN_RE.findall(m.group(1))
            for member in members:
                if member not in exists:
                    bad.append(f"Sections {m.group(1)}: no Section {member}"
                               f"  {_around(text, m)}")
            for lo, join, hi in zip(members, joins, members[1:],
                                    strict=False):
                if (_RANGE_JOIN_RE.match(join) and lo in exists
                        and hi in exists and _key(lo) >= _key(hi)):
                    bad.append(f"Sections {lo}–{hi}: the range does not run "
                               f"upward  {_around(text, m)}")
        for m in _ONE_RE.finditer(text):
            report.mentions += 1
            if m.group(1) not in exists:
                bad.append(f"Section {m.group(1)}: no such section  "
                           f"{_around(text, m)}")
        for m in (*_APX_RE.finditer(text), *_bare(text)):
            key = f"{m.group(1)}.{m.group(2)}"
            if not any(s.startswith(m.group(1) + ".") for s in exists):
                continue                   # this paper has no such appendix
            report.mentions += 1
            if key not in exists:
                bad.append(f"{key}: no such appendix section  "
                           f"{_around(text, m)}")


def _key(number: str) -> tuple[int, ...]:
    return tuple(int(p) for p in number.split("."))


def _around(text: str, m: re.Match[str]) -> str:
    at = text[max(0, m.start() - 46):m.end() + 46].replace("\n", " ")
    return f"…{at}…"


def audit(parts: Parts) -> SectionReport:
    """The numbering and every mention of it, across the body, the
    footnotes and the endnotes. Headings are the body's."""
    report = SectionReport()
    body = parts[DOCUMENT].decode("utf-8")
    report.headings = headings(body, list_numbers(parts))
    exists = _check_headings(report.headings, report)
    report.sections = [h.number for h in report.headings if h.number]
    paras = [_prose(m.group(0))
             for name in _TEXT_PARTS if name in parts
             for m in PARA_RE.finditer(parts[name].decode("utf-8"))]
    if report.sections:
        _check_mentions(paras, exists, report)
        return report
    # Nothing to resolve against: count the mentions and judge none.
    # LEtrends marks no heading at all and cites "Section 4" three
    # times; read as breaches, that is a gate red on a paper with
    # nothing wrong (2026-09-12).
    counted = SectionReport()
    _check_mentions(paras, exists, counted)
    report.mentions, report.checked = counted.mentions, False
    return report


def _prose(para_xml: str) -> str:
    """A paragraph's text for the mention scan — a heading's without its
    own number, which is not a mention of itself."""
    text = visible_text(para_xml)
    if heading_level(para_xml) is None:
        return text
    n = _NUMBER_RE.match(text.strip())
    return text.strip()[n.end():] if n else text


# ------------------------------------------------------------- renumber ---


@dataclass
class Renumbering:
    """What :func:`renumber` did. `parts` is the new package, or the one it
    was handed, unchanged, when nothing needed to move."""

    parts: Parts
    numbers: dict[str, str] = field(default_factory=dict)
    """old -> new, for every heading or merged number that moved"""
    headings: list[tuple[str, str, str]] = field(default_factory=list)
    """(old, new, title) for each heading renumbered"""
    mentions: list[tuple[str, str, str]] = field(default_factory=list)
    """(part, as it read, as it reads now) for each mention rewritten"""
    paragraphs: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.headings or self.mentions)

    def format(self) -> str:
        if not self.changed:
            return "nothing to renumber - the headings already run 1..N"
        lines = [(f"{len(self.headings)} heading(s) and "
                  f"{len(self.mentions)} mention(s) in "
                  f"{self.paragraphs} paragraph(s)"),
                 "  map : " + " ".join(f"{old}->{new}" for old, new
                                       in self.numbers.items())]
        lines += [f"  heading {old} -> {new}  {title[:50]}"
                  for old, new, title in self.headings]
        lines += [f"  {part.split('/')[-1]}: {was!r} -> {now!r}"
                  for part, was, now in self.mentions]
        return "\n".join(lines)


def _masked(text: str, heading: bool) -> str:
    """`text` with its heading number and every section mention replaced
    by one mark, so two readings that differ only there compare equal."""
    if heading:
        text = _NUMBER_RE.sub("§", text, count=1)
    for pattern in (_LIST_RE, _ONE_RE, _APX_RE):
        text = pattern.sub("§", text)
    for m in reversed(_bare(text)):
        text = text[:m.start()] + "§" + text[m.end():]
    return text


#: What a run may hold besides its text for the rewrite to be a plain one.
_UNSAFE_RUN_RE = re.compile(
    r"<w:(?:tab|br|cr|sym|noBreakHyphen|softHyphen|ptab|fldChar|instrText)\b")


def _rewrite(para: str, at: int, end: int, new: str, where: str) -> str:
    """`para` with its visible `[at, end)` reading `new`, in ONE run.

    The smallest change that does it: the head and tail the old and new
    text share stay where they are, so "Sections 2 through 4" becoming
    "Sections 2 and 3" rewrites "through 4" alone, and a mention whose
    "Section" sits in another run than its number is still one edit. What
    one plain run cannot hold is refused rather than approximated — the
    paper's own renumber checked all 43 of its mentions for that first.
    """
    old = visible_text(para)[at:end]
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while (tail < min(len(old), len(new)) - head
           and old[len(old) - 1 - tail] == new[len(new) - 1 - tail]):
        tail += 1
    lo, hi, repl = at + head, end - tail, new[head:len(new) - tail]
    runs, spans, _end = run_spans(para)
    for run, (start, stop) in zip(runs, spans, strict=True):
        if not (start <= lo and hi <= stop if lo < hi else start < lo <= stop):
            continue
        xml = run.group(0)
        if len(T_RUN_RE.findall(xml)) != 1 or _UNSAFE_RUN_RE.search(xml):
            break
        body = visible_text(xml)
        return (para[:run.start()]
                + set_run_text(xml, body[:lo - start] + repl
                               + body[hi - start:])
                + para[run.end():])
    raise AnchorError(
        f"renumber: {where}: {old!r} cannot become {new!r} inside one plain "
        f"run — the number is split across runs, or shares a run with a tab "
        f"or a field. Retype it by hand, then run this again")


def _new_numbers(heads: list[Heading]) -> dict[str, str]:
    """Each typed heading's number, old -> new, counted by POSITION.

    Built whole before anything is written, and applied in one pass:
    `5->4` and then `6->5` cannot tell their own output from their input,
    and a merge makes the map non-monotone (Aging_Well's 4 went DOWN to 3
    while 5 went down to 4). A structure a position cannot read — a
    number used twice, a subsection under the wrong parent — is refused.
    """
    out: dict[str, str] = {}
    top = 0
    children: dict[str, int] = {}
    chain: list[tuple[str, str]] = []        # (old, new) of the headings above
    appendix: str | None = None
    for h in heads:
        if not h.number:
            if (a := _APPENDIX_RE.match(h.title)) is not None:
                appendix, chain = a.group(1) or "A", []
            continue
        if h.number in out:
            raise AnchorError(
                f"renumber: Section {h.number} is used twice, and which one "
                f"a mention means is not in the file")
        parts = h.number.split(".")
        if parts[0].isalpha():
            if appendix != parts[0] or len(parts) != 2:
                raise AnchorError(
                    f"renumber: {h.number} {h.title[:40]!r} does not sit "
                    f"under an Appendix {parts[0]} heading")
            n = children[parts[0]] = children.get(parts[0], 0) + 1
            out[h.number] = f"{parts[0]}.{n}"
            continue
        depth = len(parts)
        if depth == 1:
            top += 1
            new = str(top)
        else:
            parent = ".".join(parts[:-1])
            if len(chain) < depth - 1 or chain[depth - 2][0] != parent:
                raise AnchorError(
                    f"renumber: Section {h.number} does not sit under "
                    f"Section {parent}; repair the structure first")
            above = chain[depth - 2][1]
            n = children[above] = children.get(above, 0) + 1
            new = f"{above}.{n}"
        chain = [*chain[:depth - 1], (h.number, new)]
        out[h.number] = new
    return out


def _look(number: str, full: Mapping[str, str], where: str) -> str:
    if number not in full:
        raise AnchorError(
            f"renumber: {where}: Section {number} is mentioned and no heading "
            f"carries it. Say where its text went, merged_into="
            f"{{'{number}': '<the section it joined>'}}, or correct the "
            f"mention by hand")
    return full[number]


def _list_phrase(m: re.Match[str], full: Mapping[str, str],
                 where: str) -> str:
    """The `Sections …` phrase `m` read, renumbered through `full`.

    A RANGE is rewritten, not mapped: `Sections 2 through 4` after 4 joins
    3 names two sections, and `Sections 2 through 3` is how nobody writes
    that. Two become `X and Y`, one becomes `Section X`.
    """
    body = m.group(1)
    members, joins = _JOIN_RE.split(body), _JOIN_RE.findall(body)
    word = m.group(0)[:m.start(1) - m.start(0)]
    single = word.replace("Sections", "Section")
    if any(_RANGE_JOIN_RE.match(j) for j in joins):
        if len(members) != 2:
            raise AnchorError(f"renumber: {where}: {m.group(0)!r} mixes a "
                              f"range with a list; rewrite it by hand")
        lo, hi = (x.split(".") for x in members)
        if len(lo) != len(hi) or lo[:-1] != hi[:-1]:
            raise AnchorError(f"renumber: {where}: {m.group(0)!r} is not a "
                              f"range of sibling sections")
        if int(lo[-1]) >= int(hi[-1]):
            # the audit's rule: "3 to 1" named no section, and formatting
            # the first of none raised an IndexError (mutation sweep,
            # 2026-09-13)
            raise AnchorError(f"renumber: {where}: {m.group(0)!r} does not "
                              f"run upward; correct the range by hand")
        stem = ".".join(lo[:-1])
        named = [f"{stem}.{n}" if stem else str(n)
                 for n in range(int(lo[-1]), int(hi[-1]) + 1)]
        new = sorted({_look(x, full, where) for x in named}, key=_key)
        firsts = [_key(x) for x in new]
        if any(b[:-1] != a[:-1] or b[-1] != a[-1] + 1
               for a, b in pairwise(firsts)):
            raise AnchorError(f"renumber: {where}: {m.group(0)!r} would name "
                              f"sections that no longer run in one piece")
        if len(new) == 1:
            return single + new[0]
        if len(new) == 2:
            return f"{word}{new[0]} and {new[1]}"
        return f"{word}{new[0]}{joins[0]}{new[-1]}"
    mapped = list(dict.fromkeys(_look(x, full, where) for x in members))
    if len(mapped) == len(members):
        return word + "".join(x + j for x, j in zip(mapped, [*joins, ""],
                                                    strict=True))
    if len(mapped) == 1:
        return single + mapped[0]
    last = joins[-1] if "and" in joins[-1] else " and "
    return f"{word}{', '.join(mapped[:-1])}{last}{mapped[-1]}"


def _edits(text: str, heading: bool, full: Mapping[str, str],
           letters: set[str], where: str) -> list[tuple[int, int, str, str]]:
    """(at, end, new text, the heading's old number or "") for every number
    in one paragraph that moves — the grammar :func:`audit` reads."""
    out: list[tuple[int, int, str, str]] = []
    skip = 0
    if heading and (n := _NUMBER_RE.match(text)) is not None:
        skip = n.end()
        start = n.start(1) if n.group(1) else n.start(2)
        old = text[start:n.end(2)]
        if full.get(old, old) != old:
            out.append((start, n.end(2), full[old], old))
    for m in _LIST_RE.finditer(text, skip):
        if (new := _list_phrase(m, full, where)) != m.group(0):
            out.append((m.start(), m.end(), new, ""))
    for m in _ONE_RE.finditer(text, skip):
        if (num := _look(m.group(1), full, where)) != m.group(1):
            out.append((m.start(), m.end(),
                        m.group(0)[:m.start(1) - m.start()] + num, ""))
    for m in (*_APX_RE.finditer(text, skip), *_bare(text, skip)):
        if m.group(1) not in letters:
            continue                        # this paper has no such appendix
        key = f"{m.group(1)}.{m.group(2)}"
        if (num := _look(key, full, where)) != key:
            # The letter goes too: `merged_into={"A.3": "B.1"}` kept the A
            # and wrote "Appendix A.1", a section that exists, so the audit
            # after passed it (code review, 2026-09-13).
            out.append((m.start(), m.end(),
                        m.group(0)[:m.start(1) - m.start()] + num, ""))
    return out


def renumber(parts: Parts, *,
             merged_into: Mapping[str, str] | None = None) -> Renumbering:
    """Close a gap in the typed section numbering: every heading renumbered
    by its position, and every mention with it, in ONE pass.

    The second half of the check above, ported from Aging_Well's R123
    after a merged heading left 1 2 3 5 6 7 8 9. What a merge does to the
    GONE number is an editorial fact the file does not hold, so it is
    given: ``merged_into={"4": "3"}`` sends old Section 4's mentions to
    the section its text joined, in the numbering as it stands. A mention
    of a number no heading carries and the map does not name is refused.

    Returns the package, never writes one. Refused outright: headings
    Word numbers itself (a merge renumbers those on the spot and leaves no
    gap to read), a paragraph with tracked changes, a number split across
    runs, and any paragraph whose text would change by more than its
    section numbers. The result must pass :func:`audit`. Run again on its
    own output, it finds nothing to do.
    """
    body = parts[DOCUMENT].decode("utf-8")
    heads = headings(body, list_numbers(parts))
    if any(h.listed for h in heads):
        raise AnchorError(
            "renumber: Word numbers these headings itself, so a merge "
            "renumbered them on the spot and left no gap to read the old "
            "numbers from; correct the mentions against the version before")
    typed = _new_numbers(heads)
    if not typed:
        raise AnchorError("renumber: no heading carries a typed number")
    settled = all(old == new for old, new in typed.items())
    full = dict(typed)
    for gone, into in (merged_into or {}).items():
        if gone in typed:
            if settled:
                continue          # renumbered already: a heading carries it
            raise AnchorError(f"renumber: merged_into names Section {gone}, "
                              f"and a heading still carries it")
        if into not in typed:
            raise AnchorError(f"renumber: merged_into sends Section {gone} "
                              f"to Section {into}, and no heading carries it")
        full[gone] = typed[into]
    report = Renumbering(parts=parts, numbers={
        old: new for old, new in full.items() if old != new})
    if not report.numbers:
        return report
    letters = {n.split(".")[0] for n in typed if n[:1].isalpha()}
    out = dict(parts)
    for name in _TEXT_PARTS:
        if name not in parts:
            continue
        xml = parts[name].decode("utf-8")
        pieces: list[str] = []
        cursor = 0
        for pm in PARA_RE.finditer(xml):
            para, text = pm.group(0), visible_text(pm.group(0))
            is_head = name == DOCUMENT and heading_level(para) is not None
            where = f"{name.split('/')[-1]} {text.strip()[:40]!r}"
            edits = _edits(text, is_head, full, letters, where)
            if not edits:
                continue
            if re.search(r"<w:(?:ins|del|moveFrom|moveTo)\b", para):
                raise AnchorError(f"renumber: {where}: the paragraph carries "
                                  f"tracked changes; settle them first")
            fixed = para
            for at, end, new, _old in sorted(edits, reverse=True):
                fixed = _rewrite(fixed, at, end, new, where)
            if _masked(visible_text(fixed), is_head) != _masked(text, is_head):
                raise AnchorError(f"renumber: {where}: the paragraph would "
                                  f"change by more than its section numbers")
            for at, end, new, old in sorted(edits):
                if old:
                    report.headings.append(
                        (old, new, text[end:].lstrip(".").strip()))
                else:
                    report.mentions.append((name, text[at:end], new))
            pieces.append(xml[cursor:pm.start()] + fixed)
            cursor = pm.end()
            report.paragraphs += 1
        if pieces:
            out[name] = ("".join(pieces) + xml[cursor:]).encode("utf-8")
    report.parts = out
    if not (after := audit(out)).ok:
        raise AnchorError("renumber: the result still breaches the numbering: "
                          + "; ".join(after.breaches[:3]))
    return report
