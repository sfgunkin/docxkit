r"""Reference-format audit: the house author-date style, checked.

These papers cite in the AER/QJE/JPE author-date format:

    in text   (Smith and Jones 2020); Maestas et al. (2023, p. 45)
    entry     Acemoglu, D., and P. Restrepo. (2020). "Robots and Jobs."
              *Journal of Political Economy*, 128(6): 2188–2244.

:mod:`docxkit.citations` answers "is every citation LINKED"; this module
answers "is every citation and entry WRITTEN RIGHT". The checks encode
the style's rules — single initials, "and" never "&", the year in
parentheses, en-dashes in ranges, a comma before the final "and", the
list alphabetised, an italicised journal or book title in every entry —
because a paper assembled over years genuinely mixes styles: APA commas
("(Smith, 2020)") arrive with pasted text, spelled-out first names with
imported bibliographies, hyphen ranges with everything, and nobody
proofreads a 40-entry list by eye.

Two presets cover the styles these papers actually use:

    HOUSE     the skill: initials, "(2020).", et al. from 3 authors
    CHICAGO   AFI's author-date: full names, "2023.", et al. from 4

The audit is advisory: it reports and a human decides. It never edits.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass, field, replace

from ._xml import DOCUMENT, FOOTNOTES, PARA_RE, visible_text
from .citations import (
    _ACRONYM_RE,
    AUTHORS_PATTERN,
    DISCOURSE_LEADS,
    IGNORED_LEADS,
    REF_HEADINGS,
    REF_STOPS,
    YEAR_PATTERN,
    Citation,
    Reference,
    _entry_keys,
    find_citations,
    key_for,
    references,
)
from .citations import (
    resolve_lead as _resolve_lead,
)

__all__ = [
    "CHICAGO",
    "DISCOURSE_LEADS",
    "HOUSE",
    "IGNORED_LEADS",
    "Issue",
    "RefStyleReport",
    "Style",
    "audit",
    "check_entry",
    "check_prose",
]


@dataclass(frozen=True)
class Style:
    """The axes on which these papers' house styles actually differ."""

    year_parens: bool = True   # "(2020)." after the authors, not "2020."
    initials: bool = True      # given names as initials: "D.", not "Daron"
    etal_from: int = 3         # in text, this many authors is "et al."


HOUSE = Style()
CHICAGO = Style(year_parens=False, initials=False, etal_from=4)


@dataclass(frozen=True)
class Issue:
    """One departure from the style, tied to where it is visible."""

    code: str            # stable kebab-case id, e.g. "ampersand"
    message: str
    where: str = ""      # "¶12", "fn ¶3"; "" for list-level findings
    snippet: str = ""


# IGNORED_LEADS, DISCOURSE_LEADS and the lead strip live in
# :mod:`docxkit.citations` now — the link audit uses the same lists, and
# two copies would grow apart. Re-exported here because this module's
# callers pass them (grown) as ``ignore=``.

# The entry's own year: the first year-shaped token followed by
# punctuation, with the parentheses captured so the style check can see
# whether they are there. Same anchor parse_reference uses to date an
# entry, so the two never disagree about WHICH year dates it.
_ENTRY_YEAR_RE = re.compile(rf"(\()?\b({YEAR_PATTERN})\b(\))?\s*[.,]")
# APA leakage: "(Smith, 2020)" — the house style has no comma before the
# year, so citations.find_citations cannot even see this form; pasted
# text is where it comes from. Also fires mid-list after a semicolon.
_APA_COMMA_RE = re.compile(
    rf"[(;]\s*({AUTHORS_PATTERN}),\s+({YEAR_PATTERN})\b")
_PAGE_HYPHEN_RE = re.compile(r"\bpp?\.\s*\d+\s*[-—]\s*\d+")
_PAGE_SPACE_RE = re.compile(r"\bpp?\.(?=\d)")
_ETAL_BARE_RE = re.compile(r"\bet al(?![.\w])")
_AUTHOR_SPLIT_RE = re.compile(r",|\band\b|&")
# A spelled-out given name: capitalised, two letters or more, no period.
_GIVEN_WORD_RE = re.compile(r"^[A-ZÀ-ÿĀ-ſ][a-zà-ÿā-ſ'’-]+$")
_DOUBLE_INITIAL_RE = re.compile(r"\b[A-ZÀ-ÿĀ-ſ]\.\s*[A-ZÀ-ÿĀ-ſ]\.")
_AND_NO_COMMA_RE = re.compile(r"[A-ZÀ-ÿĀ-ſ]\.\s+(?:and|&)\s")
_RANGE_HYPHEN_RE = re.compile(r"\d[-—]\d")
# An italic run mark that actually turns italics ON.
_ITALIC_RE = re.compile(r'<w:i\b(?![^>]*w:val="(?:0|false|none)")[^>]*>')
# Entries that legitimately carry no italics: the online-resource format
# ("Published online at ... Retrieved from: URL") and the working-paper
# format ("NBER Working Paper No. 29401.") — checked on AFI v13, where
# flagging those drowned the two entries that had really lost their
# journal italics. A REPORT title ("World Development Report 2020") is
# still flagged: the style italicises it like a book.
_NO_ITALICS_MARKERS = ("http", "www.", "retrieved", "published online",
                       "accessed", "available at", "working paper",
                       "discussion paper", "mimeo", "unpublished")


def _snippet(text: str, start: int, end: int, margin: int = 20) -> str:
    lo, hi = max(0, start - margin), min(len(text), end + margin)
    return " ".join(text[lo:hi].split())


def check_prose(text: str, style: Style = HOUSE) -> list[Issue]:
    """Style departures in one paragraph of body prose."""
    return _check_prose(text, style, find_citations(text))


def _check_prose(text: str, style: Style, cites: list[Citation],
                 known: Collection[str] = ()) -> list[Issue]:
    # audit() already holds the paragraph's citations for its
    # cross-check; taking them here keeps the grammar from running twice
    # on every paragraph of every document. It also holds the reference
    # list, which is what tells a swallowed lead word from a real third
    # author — without it "in the United Kingdom, Chan and Koo (2011)"
    # asks the author to write "Kingdom et al." One paragraph on its own
    # has no such evidence, so check_prose can still say that.
    issues: list[Issue] = []
    for found in cites:
        c = _resolve_lead(found, known=known)
        cite = text[c.start:c.end]
        if "&" in c.authors:
            issues.append(Issue(
                "ampersand", 'use "and", not "&", between authors',
                snippet=cite))
        names = [n for n in _AUTHOR_SPLIT_RE.split(c.authors) if n.strip()]
        if ("et al" not in c.authors and len(names) >= style.etal_from
                and not _institutional(c.authors)):
            issues.append(Issue(
                "et-al",
                f'{len(names)} authors named in text — write '
                f'"{names[0].strip()} et al."', snippet=cite))
    for m in _APA_COMMA_RE.finditer(text):
        issues.append(Issue(
            "year-comma",
            'no comma before the year: "(Smith 2020)", not "(Smith, 2020)"',
            snippet=_snippet(text, m.start(), m.end())))
    for m in _ETAL_BARE_RE.finditer(text):
        issues.append(Issue(
            "et-al-period", '"et al." takes a period',
            snippet=_snippet(text, m.start(), m.end())))
    for m in _PAGE_SPACE_RE.finditer(text):
        issues.append(Issue(
            "page-space", 'space after "p.": write "p. 45"',
            snippet=_snippet(text, m.start(), m.end() + 6)))
    for m in _PAGE_HYPHEN_RE.finditer(text):
        issues.append(Issue(
            "page-dash", 'page ranges take an en-dash: "pp. 45–48"',
            snippet=m.group(0)))
    return issues


def _institutional(authors: str) -> bool:
    """An organisation, not a personal name list — exempt from name rules."""
    return bool(_ACRONYM_RE.search(authors)) or " of " in authors


def _given_suspects(authors: str) -> list[str]:
    """Words sitting where a given name goes, spelled out in full.

    Only two slots are inspected: right after the FIRST comma (the first
    author is "Last, F.") and right after "and"/"&" (the last author is
    "F. Last"). A capitalised word anywhere else is usually a surname
    part ("J. Van Reenen") or a middle author's surname ("..., Friedman,
    J., ..."), and flagging those buries the real findings.
    """
    suspects = []
    rest = authors.partition(",")[2]
    tokens = rest.split()
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1].rstrip(",") if i else ""
        if i and prev not in ("and", "&"):
            continue
        word = tok.rstrip(".,;")
        if not tok.rstrip(",;").endswith(".") and _GIVEN_WORD_RE.match(word):
            suspects.append(word)
    return suspects


def check_entry(text: str, style: Style = HOUSE) -> list[Issue]:
    """Style departures in one reference-list entry (its visible text)."""
    issues: list[Issue] = []
    m = _ENTRY_YEAR_RE.search(text)
    if m is None:
        return issues            # not an entry; references() filters these
    year = m.group(2)
    if style.year_parens and not (m.group(1) and m.group(3)):
        issues.append(Issue(
            "year-parens", f'the year takes parentheses: "({year})."',
            snippet=_snippet(text, m.start(), m.end())))
    elif not style.year_parens and (m.group(1) or m.group(3)):
        issues.append(Issue(
            "year-parens", f'this style writes the year bare: "{year}."',
            snippet=_snippet(text, m.start(), m.end())))

    authors = text[:m.start()].rstrip(" .,(")
    if "&" in authors:
        issues.append(Issue(
            "ampersand", 'use "and", not "&", between authors',
            snippet=authors[-40:]))
    # An institutional author ("World Bank. (2020).") has no comma before
    # the year, and none of the personal-name rules apply to it. But
    # "Ministry of Health, Labour and Welfare (MHLW). (2013)." DOES carry
    # commas, and the name rules read "Labour" and "Welfare" as spelled-out
    # given names (LE le15 ¶254) — a self-naming acronym or an " of "
    # marks the author as an institution, commas or not.
    if style.initials and "," in authors and not _institutional(authors):
        if suspects := _given_suspects(authors):
            shown = ", ".join(f'"{s}"' for s in suspects[:3])
            issues.append(Issue(
                "initials",
                f"given names as single initials — {shown} spelled out",
                snippet=authors[:70]))
        if (d := _DOUBLE_INITIAL_RE.search(authors)) is not None:
            issues.append(Issue(
                "initials", f'one initial per author: "{d.group(0)}"',
                snippet=_snippet(authors, d.start(), d.end())))
        if _AND_NO_COMMA_RE.search(authors):
            issues.append(Issue(
                "and-comma",
                'comma before the final "and": "..., F., and F. Last"',
                snippet=authors[:70]))

    for token in text.split():
        low = token.lower()
        if "http" in low or "doi" in low or token.startswith("10."):
            continue                       # a URL or DOI keeps its hyphens
        if low.count("-") >= 3:
            continue                       # ISBN-shaped; not a range
        if _RANGE_HYPHEN_RE.search(token):
            issues.append(Issue(
                "en-dash",
                f'ranges take an en-dash (–): "{token.strip(".,;")}"'))
            break
    return issues


def _fold(surname: str) -> str:
    """Alphabetisation key: diacritics folded so Mühlbach files at Mu,
    punctuation dropped so "U.S." files as "US" — after "United", which
    is where the style manuals and LI7's list actually put it."""
    flat = unicodedata.normalize("NFKD", surname)
    return "".join(c for c in flat
                   if c.isalnum() or c.isspace()).casefold()


def _italic_styles(styles_xml: bytes | None) -> frozenset[str]:
    """Ids of character styles that turn italics on.

    Word's Compare drops a redundant direct ``<w:i/>`` and keeps the
    ``Emphasis`` run style, so a journal name in a compared document is
    italic without any ``<w:i>`` in the paragraph (LE round 7 spent a
    repair cycle "fixing" exactly those three journal names).
    """
    if not styles_xml:
        return frozenset()
    text = styles_xml.decode("utf-8")
    return frozenset(
        m.group(1)
        for m in re.finditer(
            r'<w:style\b[^>]*w:styleId="([^"]+)"(.*?)</w:style>',
            text, re.DOTALL)
        if _ITALIC_RE.search(m.group(2)))


_RSTYLE_RE = re.compile(r'<w:rStyle w:val="([^"]+)"')

# A table's source column often holds a citation and nothing else —
# "Cette et al. 2019" in LE le15's calibration table — with no
# parentheses for either in-text form to anchor on. Only a paragraph
# that IS such a citation counts; the pattern never scans inside prose.
_BARE_CITE_RE = re.compile(rf"({AUTHORS_PATTERN})\s+({YEAR_PATTERN})")


@dataclass
class RefStyleReport:
    """Everything :func:`audit` found, and the sizes it found it in."""

    issues: list[Issue] = field(default_factory=list)
    entries: int = 0
    cited: int = 0               # distinct works cited in the text

    def format(self) -> str:
        lines = [(f"{self.entries} reference entries, "
                  f"{self.cited} works cited in text")]
        for i in self.issues:
            where = i.where or "list"
            tail = f'  "{i.snippet}"' if i.snippet else ""
            lines.append(f"  {where:<7} {i.code:<13} {i.message}{tail}")
        if not self.issues:
            lines.append("  clean — no style departures found")
        return "\n".join(lines)

    def as_rows(self) -> list[dict[str, str]]:
        return [{"code": i.code, "where": i.where, "message": i.message,
                 "snippet": i.snippet} for i in self.issues]


def audit(parts: dict[str, bytes], style: Style = HOUSE, *,
          heading: str | tuple[str, ...] = REF_HEADINGS,
          stop: tuple[str, ...] = REF_STOPS,
          ignore: frozenset[str] | set[str] = IGNORED_LEADS,
          aliases: dict[str, str] | None = None) -> RefStyleReport:
    """Check a whole manuscript against the reference style.

    Prose paragraphs (and footnotes) get the in-text checks; the
    reference section gets the entry checks, an alphabetical-order pass
    and an italics pass; and the two sides are cross-checked — every
    citation should have an entry and every entry a citation. Table
    source notes count as prose, so a "Source: Maestas et al. (2023)"
    under an exhibit keeps that entry from reading as uncited.

    `aliases` maps a cited surname to the name the entry files under —
    ``{"WHO": "World Health Organization"}`` — because a paper cites the
    acronym and lists the full name. The MAP stays with the paper (AFI
    keeps ``_AUTHOR_ALIASES`` in its own code); the hook lives here so
    the cross-check does not report both ends of every alias. An acronym
    the entry names itself by — "Health Promotion Board (HPB)" — needs
    no map: see :func:`_entry_keys`.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    matches = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in matches]
    entries = references(texts, heading=heading, stop=stop)

    wanted = {h.casefold()
              for h in ((heading,) if isinstance(heading, str) else heading)}
    head_idx = next((i for i, t in enumerate(texts)
                     if t.strip().rstrip(":").casefold() in wanted), None)
    last_entry = max((r.index for r in entries), default=-1)
    ignored = {s.casefold() for s in ignore}
    filed_as = aliases or {}
    # Every key the bibliography answers to, needed BEFORE the prose scan:
    # it is the evidence resolve_lead decides a swallowed lead word on.
    answers_to = [_entry_keys(r) for r in entries]
    listed = set().union(*answers_to) if entries else set()

    report = RefStyleReport()
    cited: dict[str, tuple[str, str]] = {}    # key -> (where, snippet)

    def prose(text: str, where: str) -> None:
        cites = find_citations(text)
        for issue in _check_prose(text, style, cites, listed):
            report.issues.append(replace(issue, where=where))
        if not cites and (m := _BARE_CITE_RE.fullmatch(text.strip())):
            cites = [Citation(authors=m.group(1), year=m.group(2),
                              start=0, end=len(text), narrative=False)]
        for found in cites:
            c = _resolve_lead(found, known=listed)
            if c.surname.casefold() in ignored:
                continue
            key = key_for(filed_as.get(c.surname, c.surname), c.year)
            cited.setdefault(key, (where, text[c.start:c.end]))

    for i, text in enumerate(texts):
        if head_idx is not None and head_idx <= i <= last_entry:
            continue              # the reference section is not prose
        prose(text, f"¶{i + 1}")
    foot = parts.get(FOOTNOTES)
    if foot:
        for j, m in enumerate(PARA_RE.finditer(foot.decode("utf-8"))):
            if (t := visible_text(m.group(0))).strip():
                prose(t, f"fn ¶{j + 1}")

    istyles = _italic_styles(parts.get("word/styles.xml"))

    def has_italics(xml: str) -> bool:
        return (_ITALIC_RE.search(xml) is not None
                or any(v in istyles for v in _RSTYLE_RE.findall(xml)))

    prev: Reference | None = None
    for r in entries:
        where = f"¶{r.index + 1}"
        for issue in check_entry(r.text, style):
            report.issues.append(replace(issue, where=where))
        low = r.text.casefold()
        if (not has_italics(matches[r.index].group(0))
                and not any(mark in low for mark in _NO_ITALICS_MARKERS)):
            report.issues.append(Issue(
                "italics", "no italicised title or journal in this entry",
                where=where, snippet=r.text[:60]))
        if prev is not None and _fold(prev.surname) > _fold(r.surname):
            report.issues.append(Issue(
                "order",
                f'"{r.surname}" is filed after "{prev.surname}" — '
                "the list is not alphabetical", where=where))
        if (prev is not None and _fold(prev.surname) == _fold(r.surname)
                and r.year[:4] < prev.year[:4]
                and r.text.lstrip()[:1] in "—–-_"):
            # API10's WHO block ran 2002, 2019, 2018, 2021, 2015 and
            # nothing flagged it: same-author entries run oldest first.
            # Only CONTINUATION entries ("———. (2015).") qualify — a
            # shared lead surname over different co-author lists (Alkire
            # & Foster after Alkire, Roche et al.) orders by co-author,
            # not year, and flagging it buried the real findings.
            report.issues.append(Issue(
                "year-order",
                f"same-author entries run oldest first: ({r.year}) "
                f"follows ({prev.year})", where=where,
                snippet=r.text[:50]))
        prev = r

    # Two entries that render to the SAME in-text citation. Author-date has one
    # answer — 2013a, 2013b — and nothing here asked for it: applying "et al.
    # from three authors" to DSI collapsed Foster, McGillivray, and Seth (2013)
    # and Foster, Seth, Lokshin, and Sajaia (2013) into one «Foster et al.
    # 2013», the linker could then resolve only one of the three mentions, and
    # the audit still reported no issues. Keyed on surname+year, so a suffixed
    # pair is distinct and never flagged.
    same: dict[str, list[Reference]] = {}
    for r in entries:
        same.setdefault(key_for(r.surname, r.year), []).append(r)
    for group in same.values():
        if len(group) < 2:
            continue
        letters = ", ".join(f"{group[0].year}{chr(ord('a') + i)}"
                            for i in range(len(group)))
        for r in group:
            report.issues.append(Issue(
                "ambiguous-cite",
                f"{len(group)} entries cite as "
                f'"{r.surname} {r.year}" — distinguish them as {letters}',
                where=f"¶{r.index + 1}", snippet=r.text[:60]))

    report.entries = len(entries)
    report.cited = len(cited)
    if entries:
        for key, (where, snip) in cited.items():
            if key not in listed:
                report.issues.append(Issue(
                    "missing-ref", "cited but not in the reference list",
                    where=where, snippet=snip))
        for r, keys in zip(entries, answers_to, strict=True):
            if not (keys & cited.keys()):
                report.issues.append(Issue(
                    "uncited-ref", "in the reference list but never cited",
                    where=f"¶{r.index + 1}", snippet=r.text[:60]))
    elif cited:
        report.issues.append(Issue(
            "no-list",
            f"{len(cited)} works cited but no reference list found"))
    return report
