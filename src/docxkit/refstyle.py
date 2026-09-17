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
from collections import Counter
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher

from ._xml import (
    BOOKMARK_NAME_RE,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    PARA_RE,
    internal_links,
    live_properties,
    own_properties,
    set_para_property,
    visible_text,
)
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
from .edit import replace_in_para
from .errors import (
    AnchorError,
    ConversionRefused,
)
from .styles import paragraph_property

__all__ = [
    "CHICAGO",
    "DISCOURSE_LEADS",
    "HOUSE",
    "HOUSE_LAYOUT",
    "IGNORED_LEADS",
    "ConversionRefused",
    "ConvertReport",
    "Fix",
    "Issue",
    "Layout",
    "LayoutReport",
    "RefStyleReport",
    "RefileReport",
    "Style",
    "audit",
    "check_entry",
    "check_prose",
    "convert",
    "convert_entry",
    "convert_text",
    "entry_layout_issues",
    "layout",
    "refile",
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
                       "discussion paper", "mimeo", "unpublished",
                       "memorandum", "technical report")
# The same exemption by SHAPE rather than by name, because a numbered
# institutional series goes by more names than a list can hold: on
# Aging_Well the two italics findings were "Social Development Papers
# No. 1, Asian Development Bank" and "Research Memorandum, European
# Centre Vienna" — both the working-paper format the exemption already
# existed for, written under names it did not carry, and both of the
# paper's italics findings (2026-08-21).
#
# The capital on "No." is what keeps a real journal citation flagged: a
# Chicago issue number is written lowercase after the volume ("34, no.
# 4"), and exempting that would suppress the finding this check exists
# for. So the series word before it must be capitalised too.
_SERIES_NO_RE = re.compile(r"\b[A-ZÀ-ÿĀ-ſ][\w-]*\s+Nos?\.?\s*\d")


def _snippet(text: str, start: int, end: int, margin: int = 20) -> str:
    lo, hi = max(0, start - margin), min(len(text), end + margin)
    return " ".join(text[lo:hi].split())


def check_prose(text: str, style: Style = HOUSE, *,
                ignore: Collection[str] = ()) -> list[Issue]:
    """Style departures in one paragraph of body prose."""
    return _check_prose(text, style, find_citations(text), ignore=ignore)


def _check_prose(text: str, style: Style, cites: list[Citation],
                 known: Collection[str] = (),
                 ignore: Collection[str] = ()) -> list[Issue]:
    # `ignore` is the paper's own list of words that are not authors,
    # and it has to reach BOTH resolutions. `audit` passed it to its own
    # `_resolve_lead` and not to this one, so `--ignore Surveys` cleared
    # the missing-ref half of a finding and left the et-al half standing
    # on the same phrase: "3 authors named in text — write 'Surveys et
    # al.'", which no value of the flag could reach. The flag exists
    # because the paper cannot clear it any other way.
    # audit() already holds the paragraph's citations for its
    # cross-check; taking them here keeps the grammar from running twice
    # on every paragraph of every document. It also holds the reference
    # list, which is what tells a swallowed lead word from a real third
    # author — without it "in the United Kingdom, Chan and Koo (2011)"
    # asks the author to write "Kingdom et al." One paragraph on its own
    # has no such evidence, so check_prose can still say that.
    issues: list[Issue] = []
    for found in cites:
        c = _resolve_lead(found, known=known, ignore=ignore)
        cite = text[c.start:c.end]
        # A later work in a year group — "Sen (1985, 1992)" is two
        # citations and the second's span is "1992)" — shows no author
        # name. The checks below are about the name the sentence WRITES,
        # and it is written once, so reporting them per work would say
        # "3 authors named in text" twice about one phrase.
        if c.authors not in cite:
            continue
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


@dataclass(frozen=True)
class Fix:
    """One span of an entry's visible text, and what it should say.

    A FRAGMENT rather than a rewritten entry, and that is the whole
    design. Replacing a reference's text wholesale puts every word in
    one run, which destroys the italic outlet the entry is also being
    checked for — the conversion would create the finding beside it.
    Applied through :func:`docxkit.edit.replace_in_para`, each fix
    touches only the runs its own span crosses.
    """

    code: str            # the `Issue.code` this answers
    old: str
    new: str


#: Ranges are written closed here — "174–179", not "174–79". Both are
#: house styles somewhere; this one is the papers', and it is the
#: direction that ADDS digits, which is why the invariant below has to
#: know about it rather than forbidding it.
_RANGE_RE = re.compile(r"\b(\d{2,5})\s*[-—–]\s*(\d{1,5})\b")


def _expanded(lo: str, hi: str) -> str:
    """"174-79" -> "174–179"; "45-48" and "1875–1912" unchanged."""
    if len(hi) >= len(lo):
        return f"{lo}–{hi}"
    return f"{lo}–{lo[:len(lo) - len(hi)]}{hi}"


def _alnum(text: str) -> str:
    return "".join(c for c in text if c.isalnum()).casefold()


def _skip_token(token: str) -> bool:
    """A DOI, a URL or an ISBN keeps its hyphens."""
    low = token.lower()
    return ("http" in low or "doi" in low or token.startswith("10.")
            or low.count("-") >= 3)


def convert_entry(text: str, style: Style = HOUSE) -> list[Fix]:
    """The fixes that would bring one entry to `style`, or none.

    The mechanical half of what :func:`check_entry` reports: the
    punctuation and the glyphs. It does NOT touch author names, and that
    is deliberate — reducing "Till Von Wachter" by last-word-is-surname
    gives "Wachter, T.", a renamed author in a pass whose whole premise
    is that no author changes, and the particle set that would prevent
    it is a claim about names rather than a fact about the document.
    Italics are the other one it leaves: they are not text, and this
    returns text. Both stay reported by `check_entry`.

    Every fix is checked by :func:`convert_text` before it is applied.
    """
    fixes: list[Fix] = []
    m = _ENTRY_YEAR_RE.search(text)
    if m is None:
        return fixes                 # not an entry; references() filters these
    year, at = m.group(2), m.start()
    head = text[:at]
    if "&" in head:
        fixes.append(Fix("ampersand", "&", "and"))
    # AFTER the ampersand, and written as the entry will read by then:
    # "D. & P." becomes "D. and P." above, and the house style wants the
    # comma before that final "and". Converting one and not the other
    # trades an `ampersand` finding for an `and-comma` one, which is not
    # a conversion — it is moving the complaint.
    if (conn := _AND_NO_COMMA_RE.search(head)) is not None:
        span = conn.group(0).replace("&", "and")
        fixes.append(Fix("and-comma", span, span.replace(".", ".,", 1)))
    want = f"({year})." if style.year_parens else f"{year}."
    if m.group(0).rstrip() != want:
        # The eight characters in front make the fragment unique: a bare
        # year is four digits, and four digits also sit in a DOI and in
        # a page range further down the entry.
        lead = text[max(0, at - 8):at]
        fixes.append(Fix("year-parens", lead + m.group(0), lead + want))
    for token in text[at:].split():
        if _skip_token(token):
            continue
        if (r := _RANGE_RE.search(token)) is not None:
            fixed = _expanded(r.group(1), r.group(2))
            if fixed != r.group(0):
                fixes.append(Fix("en-dash", r.group(0), fixed))
    for sp in _PAGE_SPACE_RE.finditer(text):
        fixes.append(Fix("page-space", text[sp.start():sp.end() + 3],
                         text[sp.start():sp.end()] + " "
                         + text[sp.end():sp.end() + 3]))
    for et in _ETAL_BARE_RE.finditer(text):
        # `new` CONTAINS `old` here — "et al" is a prefix of "et al." —
        # so the bare fragment matches the text its OWN fix has already
        # written. Every other fix writes something its own pattern no
        # longer reads; this is the exception, and it is applied with
        # `str.replace(old, new, 1)`, which takes the FIRST occurrence
        # wherever it happens to be.
        #
        # So the fragment has to be UNIQUE, not merely wider. One
        # character each side was the old rule and it held only while a
        # trailing character existed to take: an entry ENDING in a bare
        # "et al" has none, its `old` is then a plain " et al" — which
        # is a substring of the " et al. " an earlier occurrence has
        # already become — and the replace landed on that one instead.
        # `Smith, J., et al (2020). "A." Journal. See also Jones et al`
        # converted to "et al.." in the FIRST position with the trailing
        # one untouched, and `--fix` wrote that into the bibliography.
        #
        # Widening left until the fragment occurs once says what was
        # actually meant. A window another fix has since rewritten
        # simply vanishes from `out` and is re-derived on the next
        # pass, which is what the settle loop in `convert_text` is for.
        end = min(len(text), et.end() + 1)
        at = et.start()
        while at > 0 and text.count(text[at:end]) > 1:
            at -= 1
        fixes.append(Fix("et-al-period", text[at:end],
                         text[at:et.end()] + "." + text[et.end():end]))
    return fixes


#: How many times :func:`convert_text` re-reads an entry before giving
#: up on it. Two is what a real entry takes — one pass to apply, one to
#: come back empty.
_SETTLE_ROUNDS = 6


def convert_text(text: str, style: Style = HOUSE) -> tuple[str, list[Fix]]:
    """`convert_entry`, applied — and CHECKED, which is the point.

    The invariant is the valuable part: strip everything but letters and
    digits from the entry and require it identical before and after,
    once the two changes that legitimately alter those characters are
    accounted for — "&" becoming "and", and a page range being written
    out in full. Anything else — a dropped author, a lost DOI, a
    truncated title — fails here rather than in the file.

    Raises :class:`docxkit.errors.ConversionRefused` if it does, with
    both forms in the message. A conversion that cannot prove it
    preserved the entry has no business writing it.

    The fixes are RE-READ from the converted text until it settles, and
    that is not tidiness. `convert_entry` measures every fix against the
    text it was given, and two of them quote their surroundings to be
    unambiguous — `year-parens` carries the eight characters in front of
    the year, `page-space` and `et-al-period` a character or three each
    side. An earlier fix that rewrites inside one of those windows makes
    the later fix's `old` vanish, and a single pass then skipped it as
    already covered. "Smith, J. & Lee 2020. Title." lost its
    `year-parens` that way: the ampersand fix rewrote the window it
    quoted, `--fix` reported two fixes written with no REFUSED or
    SKIPPED line, and the next `audit` reported the same entry again.
    """
    out, rounds = text, 0
    applied: list[Fix] = []
    seen: set[Fix] = set()
    while True:
        rounds += 1
        done = len(applied)
        for fix in convert_entry(out, style):
            if fix in seen or fix.old not in out:
                continue      # applied already, or an earlier fix covered it
            out = out.replace(fix.old, fix.new, 1)
            applied.append(fix)
        if len(applied) == done:
            break
        # Only at the END of the pass: two occurrences of one fix reach
        # this list as the same `Fix` twice — an entry with two bare "et
        # al" is the case — and both belong to the pass that found them.
        # What the set stops is the NEXT pass re-applying either.
        seen.update(applied[done:])
        if rounds >= _SETTLE_ROUNDS:
            # Not reachable by the fixes here — each writes something its
            # own pattern no longer matches, so a pass or two settles it.
            # A backstop with a message rather than a hang, because
            # "never settles" is the shape a new fix would fail in.
            raise ConversionRefused(
                f"the fixes for this entry did not settle in "
                f"{_SETTLE_ROUNDS} passes — one of them keeps re-reading "
                f"as unapplied:\n  was: {text}\n  now: {out}\n"
                f"Nothing was written. The fixes applied were "
                f"{[f.code for f in applied]}.")
    # BOTH sides: `_alnum` drops the ampersand as punctuation, so
    # normalising one of them made an entry that KEEPS its "&" — a
    # title's, which this deliberately does not convert — read as
    # changed and refuse although nothing had been done to it.
    before = _alnum(text.replace("&", "and"))
    after = _alnum(out.replace("&", "and"))
    if before != after:
        for fix in applied:
            if fix.code == "en-dash":
                before = _alnum(
                    before.replace(_alnum(fix.old), _alnum(fix.new), 1))
    if before != after:
        raise ConversionRefused(
            f"converting this entry would change what it SAYS, not just "
            f"how it is punctuated:\n  was: {text}\n  now: {out}\n"
            f"Nothing was written. The fixes applied were "
            f"{[f.code for f in applied]}.")
    return out, applied


@dataclass
class ConvertReport:
    """What :func:`convert` changed, and what it would not touch."""

    changed: list[str] = field(default_factory=list)     # "¶12: year-parens"
    refused: list[str] = field(default_factory=list)
    #: Entries a fix could not be written into — a span meeting a
    #: hyperlink, almost always a linked DOI. Reported, never forced:
    #: `replace_in_para` refuses those for reasons this module does not
    #: get to overrule.
    skipped: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.changed)

    def format(self) -> str:
        head = (f"{len(self.changed)} fix(es) written, "
                f"{len(self.refused)} entr(ies) refused, "
                f"{len(self.skipped)} skipped")
        return "\n".join([head]
                         + [f"  {line}" for line in self.changed]
                         + [f"  REFUSED {line}" for line in self.refused]
                         + [f"  SKIPPED {line}" for line in self.skipped])


def convert(parts: dict[str, bytes], style: Style = HOUSE, *,
            heading: str | tuple[str, ...] = REF_HEADINGS,
            stop: tuple[str, ...] = REF_STOPS) -> ConvertReport:
    """Bring a manuscript's reference ENTRIES to `style`, in place.

    The other half of `audit`: a paper that decides to adopt the house
    style had a precise, machine-readable list of what was wrong and no
    way to act on it, and AFI r4 wrote ~250 lines across three scripts
    to convert 25 entries.

    Only the reference block, and only the entries in it — prose is not
    converted, because the in-text rules ("et al." from three authors)
    change what a sentence SAYS and belong to the author.

    Each fix goes in through :func:`docxkit.edit.replace_in_para`, so a
    span that meets a hyperlink is refused rather than flattened: an
    entry whose DOI is linked keeps its link, and the report says which.
    An entry that cannot be proved unchanged is refused whole — see
    :func:`convert_text`.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    matches = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in matches]
    report = ConvertReport()
    edits: list[tuple[re.Match[str], str]] = []
    for r in references(texts, heading=heading, stop=stop):
        where = f"¶{r.index + 1}"
        try:
            _, fixes = convert_text(texts[r.index], style)
        except ConversionRefused as exc:
            report.refused.append(f"{where}: {exc}")
            continue
        para = matches[r.index].group(0)
        for fix in fixes:
            try:
                para = replace_in_para(para, fix.old, fix.new)
            except AnchorError as exc:
                report.skipped.append(f"{where} {fix.code}: {exc}")
                continue
            report.changed.append(f"{where}: {fix.code}")
        if para != matches[r.index].group(0):
            edits.append((matches[r.index], para))

    for m, para in reversed(edits):
        doc = doc[:m.start()] + para + doc[m.end():]
    parts[DOCUMENT] = doc.encode("utf-8")
    return report


@dataclass(frozen=True)
class Layout:
    """How the reference LIST sits on the page, not how an entry reads.

    Distances are in twentieths of a point, Word's unit: the house 0.5"
    hanging indent is 720, 4 pt of space after an entry is 80.
    """

    hanging: int = 720
    before: int = 0
    after: int = 80
    page_break: bool = True


HOUSE_LAYOUT = Layout()


@dataclass
class LayoutReport:
    """What :func:`layout` set, and what it left inheriting on purpose."""

    page_break: str = ""
    indented: list[str] = field(default_factory=list)
    spaced: list[str] = field(default_factory=list)
    #: Entries whose STYLE already states the house value. Writing it on
    #: the paragraph would be deleted by Word on its next save, so they
    #: are counted and left alone — see :func:`docxkit.styles.
    #: paragraph_property`.
    inherited: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.page_break or self.indented or self.spaced)

    def format(self) -> str:
        head = (f"{len(self.indented)} indent(s), {len(self.spaced)} "
                f"spacing(s) set"
                + (", page break added" if self.page_break else "")
                + (f", {len(self.inherited)} left to the style"
                   if self.inherited else ""))
        return "\n".join([head]
                         + [f"  indent   {line}" for line in self.indented]
                         + [f"  spacing  {line}" for line in self.spaced])


@dataclass
class RefileReport:
    """What :func:`refile` moved, and why it would not move anything."""

    moved: list[str] = field(default_factory=list)
    refused: str = ""

    def __bool__(self) -> bool:
        return bool(self.moved)

    def format(self) -> str:
        if self.refused:
            return f"REFUSED: {self.refused}"
        if not self.moved:
            return "the list is already alphabetical"
        return "\n".join([f"{len(self.moved)} entr(ies) re-filed"]
                         + [f"  {line}" for line in self.moved])


def _pstyle_of(para_xml: str) -> str | None:
    m = re.search(r'<w:pStyle\b[^>]*w:val="([^"]+)"', _live_ppr(para_xml))
    return m.group(1) if m else None


def _live_ppr(para_xml: str) -> str:
    """The paragraph's own properties, minus the tracked-change snapshot.

    A ``w:pPrChange`` records the properties a tracked change REPLACED,
    so reading it answers for the past.
    """
    own = own_properties(para_xml, "pPr")
    return live_properties(own[2]) if own is not None else ""


def _declared(para_xml: str, tag: str, attr: str) -> str | None:
    """The paragraph's OWN value for ``w:<tag>/@w:<attr>``, or None."""
    m = re.search(rf'<w:{tag}\b[^>]*?\bw:{attr}="([^"]*)"',
                  _live_ppr(para_xml))
    return m.group(1) if m else None


def _effective(para_xml: str, styles_xml: str | None,
               tag: str, attr: str) -> tuple[int | None, bool]:
    """(the value a reader sees, is it declared on the paragraph?).

    None means nothing states it anywhere, which Word renders as 0.
    """
    own = _declared(para_xml, tag, attr)
    if own is not None:
        return (int(own) if own.lstrip("-").isdigit() else None), True
    got = paragraph_property(styles_xml, _pstyle_of(para_xml), tag, attr)
    return (int(got) if got is not None and got.lstrip("-").isdigit()
            else None), False


#: (tag, attribute, the Layout field it must equal, how to say it)
_LAYOUT_RULES = (
    ("ind", "left", "hanging", "left indent"),
    ("ind", "hanging", "hanging", "hanging indent"),
    ("spacing", "before", "before", "space before"),
    ("spacing", "after", "after", "space after"),
)


def entry_layout_issues(para_xml: str, styles_xml: str | None,
                        spec: Layout = HOUSE_LAYOUT) -> list[Issue]:
    """How one entry's PARAGRAPH departs from `spec`.

    Shared by :func:`audit` and :func:`layout` so the report and the
    repair cannot disagree about what the rule is — the class of bug
    where a paper is told about a defect no fixer removes, or has one
    silently fixed that the audit never mentioned.
    """
    issues = []
    for tag, attr, wanted, said in _LAYOUT_RULES:
        want = getattr(spec, wanted)
        have, _ = _effective(para_xml, styles_xml, tag, attr)
        if (have or 0) != want:
            code = "indent" if tag == "ind" else "spacing"
            issues.append(Issue(
                code, f"{said} is {have if have is not None else 'unset'}, "
                      f"the house rule is {want}"))
    return issues


def _layout_findings(parts: dict[str, bytes], matches: list[re.Match[str]],
                     texts: list[str], entries: list[Reference],
                     spec: Layout) -> list[Issue]:
    """`audit`'s half of the layout rules — the same checks, unrepaired.

    Its own function so :func:`audit` does not grow a branch per rule:
    the complexity pin exists to make that growth deliberate, and four
    rules that belong together are one call.
    """
    if not entries:
        return []
    styles_xml = (parts["word/styles.xml"].decode("utf-8")
                  if "word/styles.xml" in parts else None)
    found: list[Issue] = []
    head = min(r.index for r in entries) - 1
    if spec.page_break and head >= 0 and not _starts_a_page(
            matches[head].group(0),
            matches[head - 1].group(0) if head > 0 else None):
        found.append(Issue(
            "page-break", "the reference list does not start on a new page",
            where=f"¶{head + 1}", snippet=texts[head][:60]))
    for r in entries:
        found.extend(
            replace(issue, where=f"¶{r.index + 1}", snippet=r.text[:60])
            for issue in entry_layout_issues(matches[r.index].group(0),
                                             styles_xml, spec))
    return found


def _pin(para_xml: str, tag: str, attr: str, value: int) -> str:
    """Set one attribute of one ``w:pPr`` child, keeping its others.

    ``w:spacing`` carries ``w:line`` and ``w:lineRule`` beside the value
    being set, and ``w:ind`` carries ``w:right`` and ``w:firstLine``;
    those are the paragraph's own and are not this rule's to drop.
    Placement is :func:`docxkit._xml.set_para_property`'s, which is the
    one place CT_PPr's element order is known.
    """
    m = re.search(rf"<w:{tag}\b[^>]*/>", _live_ppr(para_xml))
    if m is None:
        element = f'<w:{tag} w:{attr}="{value}"/>'
    else:
        # APPENDED, not prepended: the rules run left-then-hanging, and a
        # prepend would write them out backwards. Word's own order is not
        # semantic, but a stable one keeps `compare` and the idempotence
        # check reading byte-for-byte.
        stripped = re.sub(rf'\s*w:{attr}="[^"]*"', "", m.group(0))
        element = stripped[:-2].rstrip() + f' w:{attr}="{value}"/>'
    return set_para_property(para_xml, tag, element)


def _starts_a_page(head: str, before: str | None) -> str:
    """Why the heading already starts a page, or "" if it does not."""
    if re.search(r"<w:pageBreakBefore\b(?![^>]*w:val=\"(?:0|false|off)\")",
                 _live_ppr(head)):
        return "pageBreakBefore"
    if before is None:
        return "first paragraph"
    if re.search(r'<w:br\b[^>]*w:type="page"', before):
        return "an explicit page break above it"
    if "<w:sectPr" in before:
        return "a section break above it"
    return ""


def layout(parts: dict[str, bytes], spec: Layout = HOUSE_LAYOUT, *,
           heading: str | tuple[str, ...] = REF_HEADINGS,
           stop: tuple[str, ...] = REF_STOPS) -> LayoutReport:
    """Set the reference list's page position and entry indents, in place.

    Two house rules, and both of them drift on ordinary author rounds:
    the list starts on a NEW PAGE, and every entry is set with a 0.5"
    hanging indent, no space before and 4 pt after. An entry pasted from
    a browser arrives with neither, and Word gives a paragraph typed at
    the end of the list whatever the one above it had — which is how a
    list ends up 46 entries in house format and 14 in none.

    **A value the paragraph would INHERIT is left alone.** Word deletes a
    declaration equal to the inherited one on its next save, so writing
    an explicit ``w:before="0"`` over an inherited 0 makes a rule that
    reports the same entries every run for ever (measured on eleven DSI
    table notes). The check resolves the style chain first and only
    corrects an explicit disagreement or a genuinely missing value.

    Idempotent, so a second call reports nothing — which makes it an
    audit as well as a repair.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    styles_xml = (parts["word/styles.xml"].decode("utf-8")
                  if "word/styles.xml" in parts else None)
    matches = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in matches]
    entries = references(texts, heading=heading, stop=stop)
    report = LayoutReport()
    if not entries:
        return report

    edits: list[tuple[re.Match[str], str]] = []
    for r in entries:
        para = before = matches[r.index].group(0)
        for tag, attr, wanted, said in _LAYOUT_RULES:
            want = getattr(spec, wanted)
            have, declared = _effective(para, styles_xml, tag, attr)
            if (have or 0) == want:
                # Already right. Say so when the STYLE is what makes it
                # right and the paragraph states nothing: writing the
                # value would be deleted by Word on its next save, so
                # the entry is counted and left alone.
                #
                # This lived one branch DOWN until 2026-08-24, as `not
                # declared and have is None and want == 0` — which no
                # input can reach: `have is None` makes `(have or 0)`
                # zero, so the `continue` above fires for exactly the
                # `want == 0` case its own condition required.
                # `LayoutReport.inherited`, its docstring and the
                # ", N left to the style" clause in `format` were all
                # live and fed by nothing, and a sweep of this module
                # read twenty mutants there as untested rather than as
                # unreachable.
                if not declared and have is not None:
                    report.inherited.append(f"¶{r.index + 1}: {said}")
                continue
            para = _pin(para, tag, attr, want)
            was = have if have is not None else "-"
            line = f"¶{r.index + 1}: {said} {was} -> {want}"
            (report.indented if tag == "ind" else report.spaced).append(line)
        if para != before:
            edits.append((matches[r.index], para))

    if spec.page_break:
        head = min(r.index for r in entries) - 1
        if head >= 0:
            para = matches[head].group(0)
            why = _starts_a_page(
                para, matches[head - 1].group(0) if head else None)
            if not why:
                edits.append((matches[head], set_para_property(
                    para, "pageBreakBefore", "<w:pageBreakBefore/>")))
                report.page_break = f"¶{head + 1}: {texts[head].strip()[:40]}"

    for m, para in sorted(edits, key=lambda e: e[0].start(), reverse=True):
        doc = doc[:m.start()] + para + doc[m.end():]
    parts[DOCUMENT] = doc.encode("utf-8")
    return report


def _list_key(surname: str, text: str) -> tuple[str, str]:
    """Where an entry files: its folded surname, then its own whole text.

    Both halves are load-bearing, and each is wrong alone.

    The SURNAME decides first, folded by :func:`_fold` — diacritics
    flattened so Mühlbach files at Mu, punctuation dropped so "U.S.
    Census Bureau" files after "United Nations", which is where the
    style manuals and LI7's list put it. Sorting the raw text instead
    puts it before, because ``.`` sorts ahead of a letter.

    The TEXT breaks the tie, punctuation kept — and that is what settles
    two orderings a surname alone cannot, because ``(`` sorts before
    ``,``::

        Scott, A. (2024).  ...before...  Scott, A., Ellison, M., and ...
        Venkatapuram, S. (2011).  ...before...  Venkatapuram, S., and ...

    Same-author entries then run oldest first on their own, since the
    year is the next thing that differs.
    """
    flat = unicodedata.normalize("NFKD", text.strip())
    whole = "".join(c for c in flat
                    if not unicodedata.combining(c)).casefold()
    return _fold(surname), whole


def _order_findings(entries: list[Reference]) -> list[Issue]:
    """Every entry that is not where the list would file it.

    **Not a neighbour test.** Until 2026-08-23 this compared each entry's
    surname with the one above it, and an appended run of misfiled
    entries inverted only at its first pair: Aging_Well's author added
    Diller (2016) and Sen (2004) after Zaidi, and the audit named
    Diller alone. Fixing the named one and re-running to a clean report
    would have said the list was sorted when it was not. Same key
    :func:`refile` sorts by, so the report and the repair cannot
    disagree about where an entry belongs.

    Silent on a list of CONTINUATION entries ("———. (2015)."), whose
    key is the entry above them; `year-order` covers those, and
    :func:`refile` refuses them.
    """
    if any(_CONTINUATION_RE.match(r.text) for r in entries):
        return []
    keys = [_list_key(r.surname, r.text) for r in entries]
    order = sorted(entries, key=lambda r: _list_key(r.surname, r.text))
    at = {id(r): i for i, r in enumerate(order)}
    found = []
    for i in _misfiled(keys):
        r, j = entries[i], at[id(entries[i])]
        before = order[j - 1].surname if j else None
        after = order[j + 1].surname if j + 1 < len(order) else None
        where = ("after " + f'"{before}"' if after is None else
                 "before " + f'"{after}"' if before is None else
                 f'between "{before}" and "{after}"')
        found.append(Issue(
            "order", f'"{r.surname}" is out of alphabetical order — '
                     f"it files {where}",
            where=f"¶{r.index + 1}", snippet=r.text[:60]))
    return found


#: `12(3): 45–67` — a volume, a parenthesised issue, the separator, the
#: first page. The separator is the punctuation between them, and the
#: whole point of the rule is that this module does not know which one
#: is right: journals differ, and a paper that consistently writes
#: `40(2), 355` is not making an error.
_LOCATOR_RE = re.compile(r"\b\d{1,4}\s*\(\s*[\w–—/-]{1,12}\s*\)\s*"
                         r"([^\s\w]{1,2})\s*\d")
#: Enough entries to constitute a PRACTICE. Measured: half the mixed
#: lists in the corpus have a "majority" of one or two entries — a
#: convention of one entry is not a convention, and the honest answer
#: below this floor is silence rather than a guess.
_LOCATOR_FLOOR = 8
#: A slip is one or two entries. A list running 31 one way and 8 the
#: other holds two conventions at once — a literature review assembled
#: from several sources — and reporting the 8 tells the author their
#: document has variety, which they know. That is a description, not a
#: finding.
_LOCATOR_ODD = 2


def _locator_findings(entries: list[Reference]) -> list[Issue]:
    """Entries whose issue-to-pages separator departs from the list's own.

    An author edit turned one entry's ``6(1):`` into ``6(1);`` and the
    whole audit reported the file clean — 74 entries, 74 cited, one
    finding, and that one about a different entry's position in the
    list. `refstyle` audits everything around this separator (initials,
    ``(2020).``, "and" not "&", en-dashes in the page range,
    alphabetical order, cited-vs-listed), which is exactly why its
    silence read as approval (backlog S2, Parental_style 2026-09-01).

    Judged against the paper's own MAJORITY, not a hard-coded character
    — the same rule the citation grammar learns the ``txt``-suffix
    convention by, and the one the back-link audit asks of a reference
    list. Journals differ; a paper consistently writing ``40(2), 355``
    is following its journal, and a module that preferred the colon
    would report a house style as an error in every such paper.

    MEASURED over 300 manuscripts before it shipped: 195 carry a
    ``vol(issue)`` locator, and at this threshold **24 documents report
    25 findings**, every one of which is a real slip on reading. Loosen
    either bound and it starts reporting lists that simply hold two
    conventions: without the floor, "1 of 2 agree"; without the cap, the
    eight BibTeX-shaped entries in a hand-assembled review.

    Several of the 25 are the SAME entry across four and five
    generations of one paper — Weber & Luzzi, Singer (2016), Leopold &
    Leopold — which is the argument for the rule. Nobody caught them by
    reading, round after round.
    """
    seen = [(m.group(1), r) for r in entries
            for m in _LOCATOR_RE.finditer(r.text)]
    counts = Counter(sep for sep, _ in seen)
    if len(counts) < 2:
        return []
    top, n_top = counts.most_common(1)[0]
    if (n_top < _LOCATOR_FLOOR or len(seen) - n_top > _LOCATOR_ODD
            or n_top < 0.9 * len(seen)):
        return []
    return [Issue(
        "locator-sep",
        f'the issue takes "{top}" before the pages here — this entry has '
        f'"{sep}", and {n_top} of {len(seen)} agree on "{top}"',
        where=f"¶{r.index + 1}", snippet=_snippet_locator(r.text))
        for sep, r in seen if sep != top]


def _snippet_locator(text: str) -> str:
    """The locator itself, not the head of the entry.

    Every other snippet in this module shows the entry's first 60
    characters, which for this finding is the authors and the year — the
    part that is right. A reader has to see the separator.
    """
    m = _LOCATOR_RE.search(text)
    return _snippet(text, m.start(), m.end()) if m else text[:60]


def _misfiled(keys: list[tuple[str, str]]) -> list[int]:
    """Indices of the entries that have to MOVE, and no others.

    The smallest set, not everyone who is not where they will end up: an
    entry filed at the end pushes nothing, but a naive "did your index
    change" reports every entry below the one that is wrong, and two
    entries swapped report as two when moving either fixes the list.
    What a reader needs is the entries to pick up.
    """
    moved: list[int] = []
    for op, i1, i2, _j1, _j2 in SequenceMatcher(
            None, keys, sorted(keys)).get_opcodes():
        if op in ("delete", "replace"):
            moved.extend(range(i1, i2))
    return moved


_CONTINUATION_RE = re.compile(r"^\s*[—–\-_]{2,}")


def refile(parts: dict[str, bytes], *,
           heading: str | tuple[str, ...] = REF_HEADINGS,
           stop: tuple[str, ...] = REF_STOPS) -> RefileReport:
    """Sort the reference list alphabetically, in place.

    The other half of the `order` finding, which until now a paper could
    only read and then fix by hand.

    **An entry is not its paragraph.** Word HOISTS a bookmark that wraps
    a whole paragraph out of it, so a linked list keeps each entry's
    anchor in the gap ABOVE its ``w:p``, as a sibling. A sorter built on
    the paragraph matches alone drops every one of them and nothing in
    the text or the order looks wrong — `citations` is what notices,
    with `CITE WITHOUT REF` on most of the paper. So the unit that moves
    runs from the END of the previous paragraph to the end of this one.

    Refused, rather than guessed at, when:

    * the list uses CONTINUATION entries ("———. (2015)."), whose sort
      key is the entry above them — sorting those scatters the group;
    * a non-entry paragraph sits inside the block, since its place
      afterwards would be arbitrary;
    * the gap between two entries holds anything but bookmarks.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    matches = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in matches]
    entries = references(texts, heading=heading, stop=stop)
    report = RefileReport()
    if len(entries) < 2:
        return report

    lo, hi = entries[0].index, entries[-1].index
    listed = {r.index for r in entries}
    strays = [i for i in range(lo, hi + 1) if i not in listed]
    if strays:
        report.refused = (f"¶{strays[0] + 1} sits inside the list and is not "
                          f"an entry: {texts[strays[0]].strip()[:40]!r}")
        return report
    if any(_CONTINUATION_RE.match(texts[r.index]) for r in entries):
        report.refused = ("the list uses continuation dashes, whose entries "
                          "file under the name above them")
        return report

    units: list[tuple[tuple[str, str], str]] = []
    at = matches[lo - 1].end() if lo else matches[lo].start()
    for r in entries:
        gap = doc[at:matches[r.index].start()]
        if not re.fullmatch(r"(<w:bookmark(?:Start|End)\b[^>]*/>)*", gap):
            # An EMPTY paragraph is the common case and deserves its own
            # sentence: `_xml.PARA_RE` skips a self-closing `<w:p …/>` on
            # purpose, so a blank line pasted into a reference list is
            # invisible to every text-layer check and turns up here.
            blank = re.search(r"<w:p[\s/]", gap) is not None
            report.refused = (
                f"an empty paragraph sits above ¶{r.index + 1}; delete it "
                f"first, or sorting moves a blank line into the middle of "
                f"the list" if blank else
                f"¶{r.index + 1} has {gap[:60]!r} above it, which is not "
                f"a bookmark")
            return report
        units.append((_list_key(r.surname, texts[r.index]),
                      doc[at:matches[r.index].end()]))
        at = matches[r.index].end()

    order = sorted(units, key=lambda u: u[0])
    if order == units:
        return report

    # Only the entries that MOVED, by the same reckoning `audit` reports
    # them: an insertion pushes every entry below it down, and a report
    # naming all of them hides the one that matters.
    report.moved.extend(texts[entries[k].index].strip()[:60]
                        for k in _misfiled([u[0] for u in units]))

    start = matches[lo - 1].end() if lo else matches[lo].start()
    doc = doc[:start] + "".join(u[1] for u in order) + doc[at:]
    parts[DOCUMENT] = doc.encode("utf-8")
    return report


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


#: `<w:tbl\b`, not `<w:tbl`: after "tbl" comes "P" in `<w:tblPr>`, both
#: word characters, so there is no boundary and an unguarded pattern
#: opens a table at every table's PROPERTIES. The same reading
#: `_compare_read.STRUCT_TAG_RE` takes, and for the same reason.
_TBL_OPEN_RE = re.compile(r"<w:tbl\b[^>]*(?<!/)>")
_TR_OPEN_RE = re.compile(r"<w:tr\b[^>]*(?<!/)>")


def _header_rows(doc: str) -> list[tuple[int, int]]:
    """The span of the FIRST row of every table.

    Walked from each `<w:tbl>` to the next `<w:tr>` rather than by
    matching a whole table, because a non-greedy `<w:tbl>.*?</w:tbl>`
    closes a nested table on the INNER end tag and reads the rest of the
    outer one as body. Taking the first row after each opening tag gives
    a nested table its own header, which is what it has.
    """
    spans: list[tuple[int, int]] = []
    opens = [m.start() for m in _TBL_OPEN_RE.finditer(doc)]
    for tbl in _TBL_OPEN_RE.finditer(doc):
        tr = _TR_OPEN_RE.search(doc, tbl.end())
        # Not past the next TABLE. A `<w:tbl>` with no row of its own —
        # `<w:tbl><w:tblPr/></w:tbl>`, which Word writes — otherwise took
        # the next table's first row as its header and the same span was
        # recorded twice. Harmless to the membership test that reads
        # these, and a trap for anything that ever counts them.
        #
        # A NESTED table does not trip this: it opens inside its
        # parent's first row, so the parent's `<w:tr>` still comes first.
        after = next((at for at in opens if at > tbl.start()), len(doc))
        if tr is None or tr.start() >= after:
            continue
        end = doc.find("</w:tr>", tr.end())
        spans.append((tr.start(), end if end != -1 else len(doc)))
    return spans


@dataclass
class RefStyleReport:
    """Everything :func:`audit` found, and the two collections it read.

    `entries` and `cited` were COUNTS until 2026-08-24, under those
    names, and two scripts hit `TypeError: 'int' object is not iterable`
    in one afternoon (HCW, backlog S4). They are the collections now,
    with the counts as `n_entries` and `n_cited` — which is the shape
    that was wanted anyway: `audit` parses the reference list and then
    discarded it one line later, so a caller wanting to look at an entry
    had to re-extract what the audit had just built.
    """

    issues: list[Issue] = field(default_factory=list)
    entries: list[Reference] = field(default_factory=list)
    """The reference list as parsed, in document order."""
    cited: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Distinct works cited in the text: key -> (where, snippet)."""

    @property
    def n_entries(self) -> int:
        return len(self.entries)

    @property
    def n_cited(self) -> int:
        return len(self.cited)

    def format(self) -> str:
        lines = [(f"{self.n_entries} reference entries, "
                  f"{self.n_cited} works cited in text")]
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


def _note_paragraphs(
        parts: dict[str, bytes]) -> Iterator[tuple[str, str, str]]:
    """(xml, text, where) for every paragraph of BOTH note parts.

    Several journals take the whole apparatus as endnotes, and a
    citation there was neither checked nor counted as cited — the audit
    reported one work where the paper had two, and "cited but not
    listed" could not fire for any of them.

    Numbered per part: `fn ¶1` and `en ¶1` are different paragraphs of
    different files, and a manuscript may hold both.
    """
    for part, label in ((FOOTNOTES, "fn"), (ENDNOTES, "en")):
        blob = parts.get(part)
        if not blob:
            continue
        for j, m in enumerate(PARA_RE.finditer(blob.decode("utf-8"))):
            if (t := visible_text(m.group(0))).strip():
                yield m.group(0), t, f"{label} ¶{j + 1}"


def _entry_anchors(doc: str, matches: list[re.Match[str]],
                   entries: list[Reference]) -> dict[str, int]:
    """Every bookmark the reference ENTRIES carry, and whose entry it is.

    The gap above each entry counts: Word hoists a marker out of a
    paragraph head on save, and the entry still answers to it. A link
    pointing at one of these is a citation the document has already
    resolved — which is the fact :func:`_trust_the_links` reads instead
    of guessing at a pattern, and the fact that answers "is this work
    cited?" for a form no grammar parses.
    """
    found: dict[str, int] = {}
    for i, r in enumerate(entries):
        m = matches[r.index]
        gap = doc[(matches[r.index - 1].end() if r.index else 0):m.start()]
        for name in BOOKMARK_NAME_RE.findall(gap + m.group(0)):
            found.setdefault(name, i)
    return found


def _credit_links(xml: str, entry_anchors: dict[str, int], where: str,
                  seen: list[tuple[int, str, str]]) -> list[str]:
    """Note every entry this paragraph LINKS to, and return the labels.

    **A link to an entry is the document saying the work is cited**, and
    that settles a form no grammar reaches. "Sen's capability approach
    (1985, 1999, 2009)" names the author four words before the
    parenthesis, so `find_citations` yields nothing for it and the entry
    read as `uncited-ref` — while `citations`, counting the same links,
    reported the same manuscript 79 of 79 linked. Two tools in one
    toolkit disagreeing about one document is the part that mattered: a
    paper acting on that finding would have deleted a cited entry
    (Aging_Well, 2026-08-23).

    Collected rather than credited on the spot, because "has anything
    else already counted this work?" cannot be answered until the whole
    walk is done — see :func:`_credit_unread`.

    The labels are :func:`_trust_the_links`'s input, which is the other
    question a link answers: which part of a matched span is the real
    citation.
    """
    labels: list[str] = []
    for anchor, label in internal_links(xml):
        i = entry_anchors.get(anchor)
        if i is None:
            continue
        labels.append(label)
        seen.append((i, where, label))
    return labels


def _credit_unread(seen: list[tuple[int, str, str]],
                   entry_keys: list[tuple[str, frozenset[str]]],
                   cited: dict[str, tuple[str, str]]) -> None:
    """Count a linked work the prose scan never read, and only that one.

    **A link to an entry is the document saying the work is cited**, and
    that settles a form no grammar reaches. "Sen's capability approach
    (1985, 1999, 2009)" puts four words between the name and the
    parenthesis, so `find_citations` yields nothing for it and the entry
    read as `uncited-ref` — while `citations`, counting the same links,
    reported the same manuscript 79 of 79 linked. Two tools in one
    toolkit disagreeing about one document is the part that mattered: a
    paper acting on that finding would have deleted a cited entry
    (Aging_Well, 2026-08-23).

    Only a work NOTHING else has credited, and under the ENTRY's own
    key. An entry answers to several — the prose writes "(National
    Academies 2020)" where the list files "National Academies of
    Sciences, Engineering, and Medicine." — so crediting a link the
    prose scan has already counted files one work twice, and the header
    line reads "60 reference entries, 62 works cited in text", a
    discrepancy a reader would go looking for.

    After the whole walk, for the same reason: the prose that reads a
    work may sit in a later paragraph than the link that points at it.
    """
    for i, where, label in seen:
        canonical, answers_to = entry_keys[i]
        if not (answers_to & cited.keys()):
            cited[canonical] = (where, label)


def _trust_the_links(text: str, cites: list[Citation],
                     labels: list[str]) -> list[Citation]:
    """Re-read any citation that SWALLOWED a linked one.

    "X and Y (2024)" is the two-author pattern, and the word before
    "and" only has to be capitalised -- so *"consolidated from
    standardized national Labor Force Surveys and ILOSTAT (2024) data"*
    read as a citation of "Surveys and ILOSTAT", reported `missing-ref`
    against a reference list that holds ILOSTAT, and could not be
    cleared: the paper cannot reach an empty report, so the audit stops
    working as a gate (AFI r4).

    The apparatus already knew. `ILOSTAT (2024)` is a live hyperlink to
    the entry's own bookmark, and a link to an ENTRY is the document
    saying what it means -- which is a fact, not a guess at a pattern.
    So where a matched span strictly CONTAINS such a label, the label is
    re-read in its place, at its own offsets, and the swallowed prose in
    front of it is prose again.

    Only for a span that contains the label and differs from it. A
    citation the pattern read exactly right is left exactly alone,
    linked or not, and so is every citation in an unlinked manuscript --
    for which the pattern is still all there is.
    """
    out: list[Citation] = []
    for c in cites:
        span = text[c.start:c.end]
        inner = next((lab for lab in labels if lab and lab in span
                      and lab != span), None)
        if inner is None or not _read_label(inner):
            out.append(c)
            continue
        at = text.index(inner, c.start)
        out += [replace(found, start=at + found.start, end=at + found.end)
                for found in _read_label(inner)]
    return out


def _read_label(label: str) -> list[Citation]:
    """The citations in a link's LABEL, read as the label alone.

    A parenthetical citation does not survive being lifted out of its
    parentheses: "(Kanbur 2007)" is a citation and `Kanbur 2007` is two
    words, so the grammar finds nothing in the label a link actually
    carries. Dropping the citation there would take a cited work out of
    the cross-check and report its entry as UNCITED — the finding one
    row down from the one being fixed.

    So the parentheses are put back for a second reading, and the
    offsets shifted for the character that adds. If it still says
    nothing, the caller keeps the citation it already had: this narrows
    a match, it does not delete one.
    """
    if found := find_citations(label):
        return found
    return [replace(f, start=f.start - 1, end=f.end - 1)
            for f in find_citations(f"({label})") if f.start >= 1]


def _ambiguous_findings(entries: list[Reference]) -> list[Issue]:
    """Two entries that render to the SAME in-text citation.

    Author-date has one answer — 2013a, 2013b — and nothing here asked
    for it: applying "et al. from three authors" to DSI collapsed
    Foster, McGillivray, and Seth (2013) and Foster, Seth, Lokshin, and
    Sajaia (2013) into one «Foster et al. 2013», the linker could then
    resolve only one of the three mentions, and the audit still reported
    no issues. Keyed on surname+year, so a suffixed pair is distinct and
    never flagged.
    """
    same: dict[str, list[Reference]] = {}
    for r in entries:
        same.setdefault(key_for(r.surname, r.year), []).append(r)
    issues = []
    for group in same.values():
        if len(group) < 2:
            continue
        letters = ", ".join(f"{group[0].year}{chr(ord('a') + i)}"
                            for i in range(len(group)))
        issues += [Issue(
            "ambiguous-cite",
            f"{len(group)} entries cite as "
            f'"{r.surname} {r.year}" — distinguish them as {letters}',
            where=f"¶{r.index + 1}", snippet=r.text[:60]) for r in group]
    return issues


def _crosscheck_findings(entries: list[Reference],
                         answers_to: list[set[str]],
                         cited: dict[str, tuple[str, str]],
                         listed: set[str]) -> list[Issue]:
    """The two sides against each other: every citation should have an
    entry and every entry a citation.
    """
    if not entries:
        return [Issue("no-list", f"{len(cited)} works cited but no "
                      "reference list found")] if cited else []
    issues = [Issue("missing-ref", "cited but not in the reference list",
                    where=where, snippet=snip)
              for key, (where, snip) in cited.items() if key not in listed]
    issues += [Issue("uncited-ref",
                     "in the reference list but never cited",
                     where=f"¶{r.index + 1}", snippet=r.text[:60])
               for r, keys in zip(entries, answers_to, strict=True)
               if not (keys & cited.keys())]
    return issues


def audit(parts: dict[str, bytes], style: Style = HOUSE, *,
          heading: str | tuple[str, ...] = REF_HEADINGS,
          stop: tuple[str, ...] = REF_STOPS,
          ignore: frozenset[str] | set[str] = IGNORED_LEADS,
          aliases: dict[str, str] | None = None,
          page_layout: Layout | None = HOUSE_LAYOUT) -> RefStyleReport:
    """Check a whole manuscript against the reference style.

    Prose paragraphs (and footnotes) get the in-text checks; the
    reference section gets the entry checks, an alphabetical-order pass
    and an italics pass; and the two sides are cross-checked — every
    citation should have an entry and every entry a citation. Table
    source notes count as prose, so a "Source: Maestas et al. (2023)"
    under an exhibit keeps that entry from reading as uncited.

    `page_layout` adds the rules about where the list SITS rather than
    how it reads — a new page, a 0.5" hanging indent, 4 pt after — using
    the same checker :func:`layout` repairs with, so the report and the
    fixer cannot disagree. Pass None for a paper that sets its list
    differently on purpose.

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

    header_rows = _header_rows(doc)
    report = RefStyleReport()
    cited: dict[str, tuple[str, str]] = {}    # key -> (where, snippet)

    entry_anchors = _entry_anchors(doc, matches, entries)
    entry_keys = [(key_for(r.surname, r.year), frozenset(ks))
                  for r, ks in zip(entries, answers_to, strict=True)]
    linked: list[tuple[int, str, str]] = []

    def prose(text: str, where: str, xml: str, *,
              in_header: bool = False) -> None:
        cites = _trust_the_links(
            text, find_citations(text),
            _credit_links(xml, entry_anchors, where, linked))
        for issue in _check_prose(text, style, cites, listed,
                                  ignore=ignored):
            report.issues.append(replace(issue, where=where))
        # A whole paragraph that IS an author-year pair and nothing
        # else is a narrative citation — unless it is a column head,
        # where `Base 1990` is a label and a reference is not cited
        # from one (backlog S4, HCW: two headers per paper, cleared
        # by a per-paper ignore list that then hides real misses).
        if not cites and not in_header and (
                m := _BARE_CITE_RE.fullmatch(text.strip())):
            cites = [Citation(authors=m.group(1), year=m.group(2),
                              start=0, end=len(text), narrative=False)]
        for found in cites:
            c = _resolve_lead(found, known=listed, ignore=ignored)
            if c.surname.casefold() in ignored:
                continue
            key = key_for(filed_as.get(c.surname, c.surname), c.year)
            cited.setdefault(key, (where, text[c.start:c.end]))

    for i, text in enumerate(texts):
        if head_idx is not None and head_idx <= i <= last_entry:
            continue              # the reference section is not prose
        prose(text, f"¶{i + 1}", matches[i].group(0),
              in_header=any(a <= matches[i].start() < b
                            for a, b in header_rows))
    for xml, text, where in _note_paragraphs(parts):
        prose(text, where, xml)
    _credit_unread(linked, entry_keys, cited)

    istyles = _italic_styles(parts.get("word/styles.xml"))

    def has_italics(xml: str) -> bool:
        return (_ITALIC_RE.search(xml) is not None
                or any(v in istyles for v in _RSTYLE_RE.findall(xml)))

    report.issues.extend(_order_findings(entries))
    report.issues.extend(_locator_findings(entries))
    if page_layout is not None:
        report.issues.extend(_layout_findings(
            parts, matches, texts, entries, page_layout))

    prev: Reference | None = None
    for r in entries:
        where = f"¶{r.index + 1}"
        for issue in check_entry(r.text, style):
            report.issues.append(replace(issue, where=where))
        low = r.text.casefold()
        if (not has_italics(matches[r.index].group(0))
                and not any(mark in low for mark in _NO_ITALICS_MARKERS)
                and _SERIES_NO_RE.search(r.text) is None):
            report.issues.append(Issue(
                "italics", "no italicised title or journal in this entry",
                where=where, snippet=r.text[:60]))
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

    report.issues.extend(_ambiguous_findings(entries))
    report.entries = entries
    report.cited = cited
    report.issues.extend(_crosscheck_findings(entries, answers_to, cited,
                                              listed))
    return report
