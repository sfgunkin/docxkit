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
renumbering that follows a merge is the second, harder half, which
belongs beside this check and is not in it yet: sequential rules cannot
renumber sections (`5->4` then `6->5` cannot tell its own output from
its input, and a merge makes the map non-monotone), ranges must be
rewritten rather than mapped (`Sections 2 through 4` becomes
`Sections 2 and 3`), and a mention split across two runs must be
refused rather than missed.

Read-only. Never writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._xml import DOCUMENT, ENDNOTES, FOOTNOTES, PARA_RE, visible_text
from .find import heading_level

__all__ = [
    "Heading",
    "SectionReport",
    "audit",
    "headings",
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

_TEXT_PARTS = (DOCUMENT, FOOTNOTES, ENDNOTES)


@dataclass(frozen=True)
class Heading:
    """One heading paragraph: its number as the reader sees it, or ""."""

    number: str         # "1", "5.1", "A.3" — "" for an unnumbered heading
    title: str          # the text after the number
    level: int          # from `find.heading_level`


@dataclass
class SectionReport:
    """What :func:`audit` found. `ok` is the gate."""

    headings: list[Heading] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    breaches: list[str] = field(default_factory=list)
    mentions: int = 0

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
        if self.breaches:
            lines.append(f"  ** {len(self.breaches)} breach(es) of the "
                         "section numbering")
            lines += [f"     ** {b}" for b in self.breaches]
        else:
            lines.append("  ok - the headings run 1..N and every mention "
                         "resolves")
        return "\n".join(lines)


def headings(xml: str) -> list[Heading]:
    """Every heading in `xml`, in order, numbered as the reader sees it."""
    out = []
    for m in PARA_RE.finditer(xml):
        level = heading_level(m.group(0))
        if level is None:
            continue
        text = visible_text(m.group(0)).strip()
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
            bad.append(f"Section {h.number}: "
                       + (f"sits under Section {above}" if above
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
        for m in (*_APX_RE.finditer(text), *_BARE_RE.finditer(text)):
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


def audit(parts: dict[str, bytes]) -> SectionReport:
    """The numbering and every mention of it, across the body, the
    footnotes and the endnotes. Headings are the body's."""
    report = SectionReport()
    body = parts[DOCUMENT].decode("utf-8")
    report.headings = headings(body)
    exists = _check_headings(report.headings, report)
    report.sections = [h.number for h in report.headings if h.number]
    paras = [_prose(m.group(0))
             for name in _TEXT_PARTS if name in parts
             for m in PARA_RE.finditer(parts[name].decode("utf-8"))]
    _check_mentions(paras, exists, report)
    return report


def _prose(para_xml: str) -> str:
    """A paragraph's text for the mention scan — a heading's without its
    own number, which is not a mention of itself."""
    text = visible_text(para_xml)
    if heading_level(para_xml) is None:
        return text
    n = _NUMBER_RE.match(text.strip())
    return text.strip()[n.end():] if n else text
