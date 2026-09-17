"""The citation GRAMMAR and the parsing built on it.

What a citation looks like in prose, what a reference entry looks like
in a bibliography, and the key that pairs them. Empirically grown: the
comments through this module are a changelog of false positives found
paper by paper, which is why the patterns are cautious about
capitalised adjacency and lead words.

The bottom layer — it imports nothing from the other citation modules.
"""
from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

from ._xml import (
    RUN_OPEN_RE,
    RUN_RE,
    escape,
    live_properties,
    own_properties,
    run_holds_content,
    run_spans,
    set_run_text,
    span_holding,
    split_run,
    visible_text,
)
from .edit import _locate
from .errors import AnchorError

# A surname starts with a capital — including accented (U+00C0..U+00FF)
# and Latin Extended-A (U+0100..U+017F), because these papers cite
# Mühlbach — and continues with word characters, hyphen, apostrophe
# (straight or typographic) or period.
_NAME_CHAR = r"\w\-'.’"
# The initial capital, in the alphabets these papers cite in. `\w` already
# admits Cyrillic for the REST of a name, so a Russian paper's ministry
# citation was invisible to the finder for want of one character class — and
# the entry it pointed at then read as an orphan nobody cites. Kazakh and
# Ukrainian capitals are here for the same reason: these are Central Asian
# papers. See test_a_cyrillic_citation_is_found for the case.
_CYRILLIC_UPPER = "А-ЯЁЄІЇҐӘҒҚҢӨҰҮҺ"
_NAME = rf"[A-ZÀ-ÿĀ-ſ{_CYRILLIC_UPPER}][{_NAME_CHAR}]*"
# A surname can span tokens two ways: a capitalised prefix particle
# ("De Giorgi", "Van Reenen", "La Porta") and a lowercase join ("Bank of
# England", "Ministry of Health"). Free capitalised adjacency is NOT
# allowed — "As Smith (2020) shows" would file under "As Smith" — so a
# plain multi-word institution ("World Bank") is captured from its last
# word only; :mod:`docxkit.refstyle` reconciles that against the entry.
_PREFIX = r"(?:Da|De|Del|Della|Der|Des|Di|Du|La|Le|Ten|Ter|Van|Von)"
_PARTICLE = r"(?:da|de|del|den|der|des|di|du|la|le|of|ten|ter|van|von)"
# The lowercase particles may also LEAD a surname — "J. van Ours" is
# cited "(Picchio and van Ours 2013)" — except "of", which only joins
# ("Bank of England"): were it allowed to lead, "the work of Smith
# (2020)" would file under "of Smith".
_LEAD = r"(?:da|de|del|den|der|des|di|du|la|le|ten|ter|van|von)"
_SURNAME = (rf"\b(?:{_PREFIX}\s+|{_LEAD}\s+)*{_NAME}"
            rf"(?:\s+{_PARTICLE}(?:\s+{_PARTICLE})*\s+{_NAME})*")
# "Surname", "Surname et al.", "First and Second",
# "First, Second and Third", "First, Second, and Third"
# The trailing possessive is what a chain needs and a bare surname does
# not: the apostrophe is a name character, so "Becker's" is already
# inside _NAME, but "Doepke et al.'s (2019)" ends past it and the whole
# citation was invisible to the finder. :func:`lead_surname` drops the
# suffix again for the key; the SPAN keeps it, because it is what the
# sentence says.
_AUTHORS = (rf"{_SURNAME}"
            r"(?:\s+et\s+al\.?)?"
            rf"(?:(?:,\s+|,?\s+(?:and|&)\s+){_SURNAME})*"
            r"(?:['’]s)?")
_YEAR = r"\d{4}[a-z]?"
_YEAR_RE = re.compile(_YEAR)
# One author, SEVERAL works: "Sen (1985, 1992)", "Rowe and Kahn (1987,
# 1997)", "Sen's capability approach (1985, 1999, 2009)". A pattern that
# took a parenthesis holding exactly one year matched none of them, and
# the group did not degrade to its first work — it produced NO citation
# at all, so the author went missing with the extra years: `refstyle`
# called five cited works uncited and `link_all` skipped three mentions
# while reporting a clean sweep (Aging_Well, 2026-08-21).
#
# The list stops at anything that is not a year, which is what keeps the
# forms around it: "(Cameron et al. 2008, Roodman et al. 2019)" is still
# two works, and "(Sen 1999, 45)" still one work with a locator.
_YEARS = rf"{_YEAR}(?:\s*,\s*{_YEAR})*"
# In-text citations hide inside parenthesis GROUPS, which real papers
# fill with more than one work: "(Bernheim and Rangel 2009; Chetty
# 2015)", "(Cameron et al. 2008, Roodman et al. 2019)", "(e.g., Cahill
# et al. 2015)", "(Smith 2020, p. 45)". A whole-group pattern found none
# of these — the LE audit read ten cited entries as uncited. So the
# group is scanned for citation SEGMENTS, each anchored so its year
# CLOSES it (the group's end, a semicolon, or a comma) — "in Almaty
# 2005 the" does not cite.
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_SEGMENT_RE = re.compile(rf"({_AUTHORS})\s+({_YEARS})(?=\s*(?:[;,]|$))")
# The narrative parens may carry a locator: "Maestas et al. (2023, p. 45)".
_NARRATIVE_RE = re.compile(
    rf"({_AUTHORS})\s+\(({_YEARS})(?:,\s+pp?\.[^)]*)?\)")
# The year that dates a reference entry. Both house styles occur across
# these papers and a parser that knows only one finds almost nothing:
#     Maestas, Nicole, ... 2023. "Title."      (AFI)
#     Bucher-Koenen, T., and S. Kluth. (2013). "Title."   (LE, HPPA)
_REF_YEAR_RE = re.compile(rf"\(?\b({_YEAR})\b\)?\s*[.,]")
# Zotero leaves field-code preambles in the paragraph text of the first
# reference when it re-runs inside Word.
_ZOTERO_RE = (
    re.compile(r"^\s*ADDIN\s+ZOTERO_(?:BIBL|ITEM)\b.*?CSL_BIBLIOGRAPHY\s+",
               re.DOTALL),
    re.compile(r"^\s*ADDIN\s+ZOTERO_\S+\s+"),
)
# Headings that start and end a reference list. Russian included: the DSI
# methodology document files its under «Литература».
_DEFAULT_HEADINGS = ("References", "Bibliography", "Литература",
                     "Список литературы")
# What comes AFTER a reference list and must not be read as part of it.
# The exhibits, and the journal back matter — a paper whose "Data
# availability" sentence carried a year had that sentence parsed as an
# entry, filed under the surname "The data are drawn from Eurostat", and
# a real "(Eurostat 2023)" then linked to it.
_DEFAULT_STOPS = (
    "Appendix", "Appendices", "Figures", "Tables",
    "Acknowledgement", "Acknowledgements", "Acknowledgment",
    "Acknowledgments", "Data availability", "Data and code",
    "Funding", "Notes", "Endnotes", "Supplementary", "Supporting",
    "Declaration", "Declarations", "Disclosure", "Conflict",
    "Conflicts", "Competing", "Author contributions", "Abbreviations",
    "Ethics", "ORCID",
    "Приложение", "Приложения", "Благодарности", "Финансирование",
    "Примечания", "Сокращения", "Конфликт")
# In these papers the figures and tables are moved below the references,
# so their captions end the list just as a heading would.
_CAPTION_START_RE = re.compile(
    r"^(?:Figure|Table|Рисунок|Таблица)\s+\S+[.:]")
# A repeated-author entry: "———. 2019." or "____. 2019." stands in for the
# author named on the entry above. The space is optional after the
# punctuation — API10 writes "________.(2024)." with none, and missing
# it files the entry under a row of underscores.
_CONTINUATION_RE = re.compile(r"^[-—–_—–]{2,}(?:[.,]\s*|\s)")

# Public names for the grammar and the section markers:
# :mod:`docxkit.refstyle` builds its format checks on the SAME patterns
# rather than defining a second citation grammar that would drift.
AUTHORS_PATTERN = _AUTHORS
YEAR_PATTERN = _YEAR
REF_HEADINGS = _DEFAULT_HEADINGS
REF_STOPS = _DEFAULT_STOPS

# Capitalised words that look like a citation's lead author but are not
# one — "Table (2020)", "in March (2020)". Grown from real false
# positives; used by the link audit here and the format audit in
# :mod:`docxkit.refstyle`.
IGNORED_LEADS = frozenset({
    "Section", "Table", "Figure", "Appendix", "Proposition", "Corollary",
    "Equation", "Step", "Part", "Band", "Index", "Panel", "Model", "Wave",
    "Round", "Vol", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
})

# A sentence adverb the grammar swallowed as a first author:
# "Similarly, Liebman and Luttmer (2015) show..." reads as a three-author
# citation led by "Similarly". Both audits strip the lead rather than
# drop the citation — the citation itself is real. Found on LE le15 ¶30.
DISCOURSE_LEADS = frozenset({
    "Accordingly", "Additionally", "Alternatively", "Also", "Consequently",
    "Conversely", "Finally", "First", "Fourth", "Further", "Furthermore",
    "Hence", "However", "Importantly", "Indeed", "Instead", "Likewise",
    "Meanwhile", "Moreover", "Nevertheless", "Nonetheless", "Notably",
    "Overall", "Recently", "Relatedly", "Second", "Similarly",
    "Specifically", "Third", "Thus", "Yet",
})
_LEAD_ADVERB_RE = re.compile(r"^([A-ZÀ-ÿĀ-ſ][a-zà-ÿā-ſ]+),\s+(.+)$",
                             re.DOTALL)
# Where one author ends and the next begins, in an in-text chain.
_CHAIN_SPLIT_RE = re.compile(r",|\s+(?:and|&)\s+|\s+et\s+al")
# The possessive that ends a name in prose but never in a bibliography:
# "Becker's" straight or typographic, and the plural "the Smiths' (2019)".
_POSSESSIVE_RE = re.compile(r"['’]s?$")


def strip_lead(authors: str) -> str:
    """Drop a leading discourse adverb the grammar mistook for an author."""
    m = _LEAD_ADVERB_RE.match(authors)
    if m and m.group(1) in DISCOURSE_LEADS:
        return m.group(2)
    return authors


def lead_surname(authors: str) -> str:
    """The first author of a chain, as the reference list would file it.

    A POSSESSIVE mention — "Becker's (1981) model", "Doepke et al.'s
    (2019)" — is a citation, and the name the bibliography files it under
    is the plain surname. The apostrophe is a name character (D'Souza,
    O'Brien) so the grammar takes "Becker's" whole and :func:`key_for`
    strips the punctuation without removing the *s*: the key came out
    ``beckers_1981``, matched no entry, and the mention could not be
    linked at all (Parental Style 2026-08-10). Only a TRAILING possessive
    is dropped, so a name whose apostrophe JOINS it is untouched.
    """
    return _POSSESSIVE_RE.sub("", _CHAIN_SPLIT_RE.split(authors)[0].strip())


@dataclass(frozen=True)
class Citation:
    """An in-text citation and where it sits in the paragraph's text."""

    authors: str
    year: str
    start: int
    end: int
    narrative: bool         # "Author (Year)" rather than "(Author Year)"

    @property
    def surname(self) -> str:
        """The first author's surname, as the reference list would file it."""
        return lead_surname(self.authors)

    @property
    def key(self) -> str:
        return key_for(self.surname, self.year)


@dataclass(frozen=True)
class Reference:
    """One entry in the reference list."""

    text: str
    surname: str
    year: str
    index: int              # paragraph index in the document

    @property
    def key(self) -> str:
        return key_for(self.surname, self.year)


def key_for(surname: str, year: str) -> str:
    """The anchor key for a citation: ``maestas_2023``.

    Lower-cased and stripped of punctuation so that "Mühlbach", "Muhlbach"
    and "Mühlbach," all land on one anchor.
    """
    slug = re.sub(r"[^\w]+", "", surname.replace("’", "").replace("'", ""))
    return f"{slug.lower()}_{year}"


def resolve_lead(c: Citation, *,
                 known: Collection[str] = (),
                 ignore: Collection[str] = ()) -> Citation:
    """The citation without the lead word the grammar mistook for an author.

    "Word, First and Second" is exactly the shape of a three-author
    citation, so the grammar swallows whatever capitalised word sits
    before the comma. Two kinds really occur:

    * a sentence adverb — "Similarly, Liebman and Luttmer (2015)" (LE
      le15 ¶30), handled by the closed :data:`DISCOURSE_LEADS` list;
    * the tail of a longer capitalised phrase, which the grammar can
      only capture from its last word because free capitalised adjacency
      is not a surname — "in the United Kingdom, Chan and Koo (2011)"
      files under "Kingdom" (Parental Style). That left the mention
      unlinked, reported an already-linked one as UNLINKED, and had
      :mod:`docxkit.refstyle` asking the author for "Kingdom et al."

    Syntax cannot tell the second from a real three-author chain:
    "Kingdom, Chan and Koo" and "Chan, Koo and Smith" are the same
    string shape. So it is decided on EVIDENCE. Pass ``known``, the keys
    the reference list answers to, and the head is dropped only when the
    bibliography files nothing under it at ANY year and does file the
    next name at this citation's year.

    With no evidence — no ``known``, or neither name listed — the
    citation comes back untouched and is reported unmatched. What that
    leaves is narrow: a citation whose lead author is missing from the
    bibliography while a co-author has an entry of the same year. A
    document in that state has a worse problem than this link.

    ``ignore`` is the third kind, and the one an UNLINKED manuscript
    needs: a word the PAPER has declared is not an author. "…national
    Labor Force Surveys and ILOSTAT (2024) data…" is the two-author
    pattern with a capitalised common noun in front, and with no
    apparatus to read there is no fact to correct it with (Aging_Well,
    2026-08-21). Dropping the whole citation instead — which is what a
    caller filtering on the surname does — takes the REAL half with it,
    and ILOSTAT's entry is then reported as uncited: one false finding
    traded for another. So the head is stripped and the rest kept.

    The SPAN moves with the text. Trimming only ``authors`` left the
    hyperlink wrapping "Similarly, Liebman and Luttmer (2015)" — the
    right target under the wrong words, in every paper linked so far.
    """
    authors = strip_lead(c.authors)
    if known:
        authors = _drop_unlisted_head(authors, c.year, known)
    if ignore:
        authors = _drop_ignored_head(authors, ignore)
    if authors == c.authors:
        return c
    return replace(c, authors=authors,
                   start=c.start + len(c.authors) - len(authors))


# The word immediately before a span, across a space or a NON-BREAKING
# space — Word writes the latter inside an institution's name.
_PREV_WORD_RE = re.compile(r"(\S+)[ \u00a0]+$")
# Punctuation that ends a name: whatever precedes it belongs to a
# different phrase, however well its words match.
_STOPS_A_NAME = ",;:.…)]"
# …and punctuation that OPENS one. The word carrying it is part of the
# name; anything before it is not, so the walk takes it and stops.
_OPENS_A_PHRASE = "([{«\"'“"


def _bare(word: str) -> str:
    return re.sub(r"[^\w]", "", word).casefold()


def extend_to_name(text: str, c: Citation, name: str) -> Citation:
    """Widen a citation's span back over the institutional name it ends.

    The grammar captures a plain multi-word institution from its LAST
    word only — free capitalised adjacency is not a surname, or "As
    Smith" would be one. That is right for FINDING the entry, which
    answers to every word run of its name. It is wrong for the LINK: the
    Global Initiative to End All Corporal Punishment, cited "(End
    Corporal Punishment 2024)", was underlined from "Punishment"
    (Parental Style). The underline is what a reader sees.

    The entry's own filed name says how far back to go: a preceding word
    counts only if the entry names it, so ordinary prose ("the", "in")
    stops the walk, and so does punctuation. The span then settles on a
    capitalised word — an institution's name does not begin with "of".
    Anything else is returned untouched, including a chain of human
    authors and an acronym the name does not spell.
    """
    if len(_CHAIN_SPLIT_RE.split(c.authors)) > 1:
        return c                       # a chain of authors, not a name
    words = {_bare(w) for w in name.split()}
    if len(words) < 2 or _bare(c.authors.split()[0]) not in words:
        return c
    at = c.start
    while (m := _PREV_WORD_RE.search(text[:at])):
        word = m.group(1)
        if word[-1] in _STOPS_A_NAME or _bare(word) not in words:
            break
        at = m.start(1)
        if word[0] in _OPENS_A_PHRASE:     # "(End Corporal Punishment"
            break
    # Settle on a capital: the walk may have crossed "of" or "to", and the
    # word it stopped on can carry the citation group's own "(".
    for wm in re.finditer(r"\S+", text[at:c.start]):
        first = re.search(r"[^\W\d_]", wm.group(0))
        if first is not None and first.group(0).isupper():
            return replace(c, start=at + wm.start() + first.start())
    return c


#: where one author ends and the NEXT begins — the same separators
#: :data:`_AUTHORS` joins a chain with, read left to right
_FIRST_SEP_RE = re.compile(r",\s+|,?\s+(?:and|&)\s+")


def _drop_ignored_head(authors: str, ignore: Collection[str]) -> str:
    """Strip a lead the paper has declared is not an author.

    Only from a CHAIN, and only the head: a lone ignored word ("Table
    (2020)") has no rest to keep, and its caller filters it out
    afterwards. Repeated, so "Surveys and Table and ILOSTAT" reduces
    the whole way down.

    The contract is the ignore list's own: this word is NEVER an author.
    A paper that cites James March has to take "March" off its list —
    which is already true today, because a caller filtering on the
    surname drops that citation whole. What changes is the failure:
    narrowed and visible rather than silently absent from both the audit
    and the linker.
    """
    ignored = {s.casefold() for s in ignore}
    while (m := _FIRST_SEP_RE.search(authors)) is not None:
        head, rest = authors[:m.start()], authors[m.end():]
        if _POSSESSIVE_RE.sub("", head).casefold() not in ignored or not rest:
            break
        authors = rest
    return authors


def _drop_unlisted_head(authors: str, year: str,
                        known: Collection[str]) -> str:
    head, sep, rest = authors.partition(",")
    if not sep or not (rest := rest.strip()):
        return authors
    # `key_for(head, "")` is the key's alpha part with its separator —
    # "kingdom_" — so this asks "filed under that name at any year".
    prefix = key_for(head.strip(), "")
    if any(k.startswith(prefix) for k in known):
        return authors
    return rest if key_for(lead_surname(rest), year) in known else authors


def anchor_names(key: str) -> tuple[str, str]:
    """(citation anchor, reference anchor) for a key.

    The house convention across these papers: the in-text mention is
    wrapped in ``cite_<key>`` and links to ``ref_<key>``; the reference
    entry is wrapped in ``ref_<key>`` and links back to ``cite_<key>``.
    That pairing is what makes the links bidirectional, and what
    :func:`check_citations` audits.
    """
    return f"cite_{key}", f"ref_{key}"


# Every citation form carries a four-digit year. One C-speed scan
# rejects the ~90% of paragraphs that cannot cite before the expensive
# author grammar runs — the audits call this on every paragraph of
# every document they touch.
_YEAR_HINT_RE = re.compile(r"[12]\d{3}")


#: No work in these papers is published after this. A four-digit PAGE
#: number is indistinguishable from a year by shape, so the ordering
#: rule below does most of the work and this is the backstop for a
#: locator that happens to sort after the year it follows.
_LATEST_PLAUSIBLE_YEAR = 2100


def _works(found: list[re.Match[str]]) -> int:
    """How many of a group's four-digit numbers are WORKS, not a locator.

    "Sen (1985, 1992)" is two works; "Acemoglu and Robinson (2012,
    1215)" is one work and a page. Both read as a comma-separated list
    of years, and a locator of four digits is routine — AER, JPE and QJE
    volumes all run past page 1000 — so counting it as a second work
    invented a citation of the year 1215, reported the phantom as
    `UNLINKED: "1215)"`, and inflated the `Mentions: X of Y linked`
    completeness line by one per occurrence.

    A list of one author's works runs FORWARD, so a number earlier than
    the first year is a page and closes the list. The upper bound
    catches the other direction, where a page sorts after the year it
    follows.
    """
    first = int(found[0].group(0)[:4])
    n = 1
    for m in found[1:]:
        year = int(m.group(0)[:4])
        if year < first or year > _LATEST_PLAUSIBLE_YEAR:
            break
        n += 1
    return n


def _per_year(authors: str, years: str, *, at: int, years_at: int,
              end: int, narrative: bool) -> list[Citation]:
    """One :class:`Citation` per year in a group, spans TILING the match.

    "Rowe and Kahn (1987, 1997)" cites two works and a reader clicks two
    labels: "Rowe and Kahn (1987" and "1997)". So the matched span is
    cut at the commas rather than repeated — the first piece carries the
    authors and its own year, each later piece carries just its year,
    and the last takes whatever closed the match. Overlapping spans
    would be worse than the defect: the linker wraps each one, and two
    hyperlinks over the same words is the shape `audit_links` calls a
    DOUBLED LINK.

    A single year is the whole match, exactly as before — and so is a
    year followed by a four-digit PAGE (:func:`_works`), whose span
    keeps the locator because that is what the sentence says.
    """
    found = list(_YEAR_RE.finditer(years))
    found = found[:_works(found)]
    return [Citation(
        authors=authors, year=m.group(0),
        start=at if i == 0 else years_at + m.start(),
        end=end if i == len(found) - 1 else years_at + m.end(),
        narrative=narrative) for i, m in enumerate(found)]


#: The in-text scanner, told what the reference list already knows.
#:
#: The grammar cannot read a surname of two capitalised words on its
#: own, and deliberately: free capitalised adjacency would file "As
#: Smith (2020) shows" under "As Smith". That refusal is right for
#: guessing and wrong when the answer is in the document — "de São José
#: et al. (2019)" linked as "José et al. (2019)", leaving `de São `
#: black immediately before a blue underlined `José` (Aging_Well,
#: 2026-08-23). The entry side parses the surname correctly, particle
#: and all; only the in-text side was guessing.
#:
#: Cached because a scan calls this once per paragraph with the same
#: name list, and compiling an alternation of ninety surnames each time
#: is the sort of cost that turns a document-wide pass into a coffee
#: break.
@lru_cache(maxsize=8)
def _patterns_for(names: tuple[str, ...]) -> tuple[re.Pattern[str],
                                                   re.Pattern[str]]:
    if not names:
        return _SEGMENT_RE, _NARRATIVE_RE
    # LONGEST first: with both "José" and "de São José" known, the
    # alternation must not settle for the shorter one and re-create the
    # defect it is here to fix.
    known = "|".join(re.escape(n) for n in
                     sorted({n for n in names if n}, key=len, reverse=True))
    surname = rf"(?:{known}|{_SURNAME})"
    authors = (rf"{surname}"
               r"(?:\s+et\s+al\.?)?"
               rf"(?:(?:,\s+|,?\s+(?:and|&)\s+){surname})*"
               r"(?:['’]s)?")
    return (re.compile(rf"({authors})\s+({_YEARS})(?=\s*(?:[;,]|$))"),
            re.compile(rf"({authors})\s+\(({_YEARS})"
                       r"(?:,\s+pp?\.[^)]*)?\)"))


def find_citations(text: str,
                   names: Sequence[str] | tuple[str, ...] = ()) -> list[
                       Citation]:
    """Every in-text citation in a paragraph's visible text.

    Both forms, in document order. A parenthesis group holding several
    works — "(Bernheim and Rangel 2009; Chetty 2015)" — yields one
    :class:`Citation` per work, each with its own span, and so does a
    group holding several YEARS under one author: "Sen (1985, 1992)" is
    two citations of Sen whose spans tile the group. A narrative
    citation inside a parenthetical aside — "(see Maestas et al.
    (2023))" — is reported once, as the narrative form; the two loops
    cannot double-report, because a segment's text can hold no
    parenthesis and a narrative match must hold its "(year)".

    `names` is what the REFERENCE LIST says the surnames are, and
    passing it is how a caller stops this from guessing at the ones the
    grammar cannot infer. A surname of two capitalised words is the
    case: "de São José et al. (2019)" scanned as "José et al. (2019)",
    because free capitalised adjacency is refused here on purpose — it
    would file "As Smith (2020) shows" under "As Smith". Told the name,
    the scanner matches it whole.
    """
    if _YEAR_HINT_RE.search(text) is None:
        return []
    segment_re, narrative_re = _patterns_for(tuple(names))
    found: list[Citation] = []
    for pm in _PAREN_RE.finditer(text):
        base = pm.start(1)
        for m in segment_re.finditer(pm.group(1)):
            found += _per_year(m.group(1), m.group(2),
                               at=base + m.start(), years_at=base + m.start(2),
                               end=base + m.end(), narrative=False)
    for m in narrative_re.finditer(text):
        found += _per_year(m.group(1), m.group(2), at=m.start(),
                           years_at=m.start(2), end=m.end(), narrative=True)
    return sorted(found, key=lambda c: c.start)


def citations_clear_of(text: str, masked: str,
                       names: Sequence[str] = ()) -> list[Citation]:
    r"""Citations whose span is not already inside a link.

    The wide span a known surname gives is an improvement — until the
    earlier words are already inside somebody else's link, where taking
    it would nest one link in another. `link_rest`'s widening had a
    guard for exactly that and abandoned the widening, keeping the
    narrow span: *"linking less prettily, never worse"*.

    Telling the scanner the surname made the wide span the FIRST one it
    sees, so the blocked case stopped falling back and started skipping
    the mention altogether — worse, not less pretty. This restores the
    ladder: the wide capture when it is clear, the grammar's narrower
    one when it is not, and nothing only when both are blocked.

    `masked` is :func:`masked_visible_text` of the same paragraph — a
    NUL at an offset means that offset is already linked.
    """
    out: list[Citation] = []
    narrow: list[Citation] | None = None
    for wide in find_citations(text, names):
        if "\x00" not in masked[wide.start:wide.end]:
            out.append(wide)
            continue
        if narrow is None:                    # scanned once, and only if
            narrow = find_citations(text)     # a wide span was blocked
        out += [n for n in narrow
                if n.year == wide.year
                and wide.start <= n.start and n.end <= wide.end
                and "\x00" not in masked[n.start:n.end]]
    return out


def parse_reference(text: str, index: int = -1) -> Reference | None:
    """Parse a reference entry into (surname, year), or None.

    The surname is everything before the FIRST comma; an institutional
    entry with no comma before the year takes everything up to the
    preceding period, so "Eurofound. 2021." files under Eurofound.
    """
    for pattern in _ZOTERO_RE:
        text = pattern.sub("", text)
    m = _REF_YEAR_RE.search(text)
    if not m:
        return None
    lead = text[:m.start()].rstrip(" .,")
    if "," in lead:
        surname = lead.split(",", 1)[0]
    else:
        # The institutional split stops at a SENTENCE period, not at a
        # dotted acronym's: "U.S. Census Bureau. (2023)" must file under
        # the full name — splitting at the first period filed it under
        # "U", which broke the order check and the cited/listed pairing
        # on LI7. A period preceded by a single capital is the acronym's.
        m2 = re.search(r"(?<!\b[A-Z])\.(?=\s)", lead)
        surname = lead[:m2.start()] if m2 else lead
    surname = surname.strip()
    if not surname:
        return None
    return Reference(text=text.strip(), surname=surname, year=m.group(1),
                     index=index)


def reference_head(text: str) -> str | None:
    """An entry's head: everything through the year, terminator dropped.

    "Kanbur, R. (2007). Poverty and distribution. Journal." has the head
    "Kanbur, R. (2007)", and that is the span `link_all` wraps to point
    the entry back at the sentence citing it.

    It reads the year with :data:`_REF_YEAR_RE`, the same expression
    :func:`parse_reference` uses to decide the paragraph IS an entry.
    That is the point of the function. `_cite_build` had its own regex
    for the head, and the two disagreed over one token — `_REF_YEAR_RE`
    allows whitespace before the year's terminator and the other did
    not — so "Kanbur, R. (2007) . Poverty." parsed as an entry and then
    had no head, and the entry shipped with no back-link while its
    in-text mention was linked: half a pair, and only a line in the
    report to say so.
    """
    m = _REF_YEAR_RE.search(text)
    if m is None:
        return None
    return text[:m.end()].rstrip().rstrip(".,").rstrip() or None


# Words that legitimately sit lowercase inside an author field, so that
# "van der Berg" and "Ministry of Health of the Republic" are names and
# "The data are drawn from Eurostat" is not.
_CONNECTIVES = frozenset((
    "of", "for", "and", "the", "in", "on", "at", "de", "del", "della",
    "der", "den", "des", "di", "do", "dos", "du", "da", "el", "la", "le",
    "van", "von", "y", "ter", "ten", "af", "av", "bin", "ibn", "al"))


def _reads_as_prose(surname: str) -> bool:
    """Does this author field read as a SENTENCE rather than a name?

    A paragraph of back matter carrying a year parses as a reference
    entry — `parse_reference` cannot tell "The data are drawn from
    Eurostat (2023)." from "World Bank Group. (2024)." because they have
    the same shape — and the entry then answers to a real citation. The
    bounds in `references` are the fix; this is what catches the case
    the bounds miss, so that it is REPORTED rather than silent.

    The test is a lowercase word that is not a connective, which is why
    it is limited to Latin script: a Cyrillic institution is full of
    lowercase content words ("Министерство здравоохранения Республики
    Казахстан") and would be called prose every time. Being wrong there
    would cost the DSI paper a false line on every build, and a report
    nobody believes is worse than no report.
    """
    words = [w.strip(".,;:()[]") for w in surname.split()]
    if len(words) < 4:
        return False                  # "de Souza", "U.S. Census Bureau"
    if not all(unicodedata.name(ch, "").startswith("LATIN")
               for ch in surname if ch.isalpha()):
        return False
    return any(w and w[0].islower() and w.casefold() not in _CONNECTIVES
               for w in words)


def _ends_the_list(text: str, stops: set[str]) -> bool:
    """Does this paragraph end the reference list?

    A stop word used to have to be the WHOLE paragraph, which is true of a
    bare "Appendix" and false of every appendix heading that carries a letter
    and a title — "Приложение А. Характеристика показателей", "Appendix B.
    Robustness". The list then ran on into the appendix, where one prose
    paragraph containing "(Jensen 1906)" parsed as an entry, minted a bookmark
    out of the surrounding equation glyphs, and left the real Jensen entry
    reading as never cited.

    So a stop word now counts at the START of the paragraph too — but only
    when the paragraph is not itself an entry. A reference is never a heading,
    and that is what stops an author named Tables from ending the list.

    The start is matched as a PREFIX at a word boundary rather than as the
    first word, because the back-matter headings are two words ("Data
    availability", "Author contributions") and a first-word test can only
    ever see one of them.
    """
    flat = text.rstrip(":").casefold()
    if flat in stops:
        return True
    if not any(flat.startswith(stop)
               and (len(flat) == len(stop) or not flat[len(stop)].isalnum())
               for stop in stops):
        return False
    return parse_reference(text) is None


def references(paragraphs: list[str], *,
               heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
               stop: tuple[str, ...] = _DEFAULT_STOPS) -> list[Reference]:
    """Parse the reference SECTION, not the whole document.

    :func:`parse_reference` answers "could this paragraph be an entry?",
    and body prose containing "(2023)." can. Applied document-wide it
    finds 63 entries in a paper with 28. The reference list has to be
    located first: from the heading paragraph to the next heading that
    ends it (Appendices, Figures, Tables), or the end of the document.
    """
    wanted = (heading,) if isinstance(heading, str) else heading
    start = next((i for i, p in enumerate(paragraphs)
                  if p.strip().rstrip(":").casefold()
                  in {h.casefold() for h in wanted}), None)
    if start is None:
        return []
    out: list[Reference] = []
    for i in range(start + 1, len(paragraphs)):
        text = paragraphs[i].strip()
        if not text:
            continue
        if _ends_the_list(text, {s.casefold() for s in stop}):
            break
        if _CAPTION_START_RE.match(text):
            break                     # figures/tables moved to the end
        ref = parse_reference(text, i)
        if ref is None:
            continue
        if _CONTINUATION_RE.match(text) and out:
            # "———. 2019." repeats the previous author rather than naming
            # them; without this the entry files under a row of dashes and
            # reads as never cited.
            ref = Reference(text=ref.text, surname=out[-1].surname,
                            year=ref.year, index=i)
        out.append(ref)
    return out


def hyperlink_field(anchor: str, label: str, *, style: str = "Hyperlink",
                    rpr: str = "") -> str:
    """A ``HYPERLINK \\l`` field pointing at an internal bookmark.

    Written as a field rather than a ``w:hyperlink`` element because that
    is what Word produces for a cross-reference, and what the papers'
    existing documents contain — mixing the two makes the audit's
    back-link pairing fail.
    """
    props = rpr or f'<w:rPr><w:rStyle w:val="{style}"/></w:rPr>'
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText>HYPERLINK \\l "{anchor}" \\h</w:instrText>'
            "</w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f"<w:r>{props}<w:t>{escape(label)}</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def link_in_para(para_xml: str, text: str, anchor: str, *,
                 style: str = "Hyperlink") -> str:
    """Wrap exactly `text` in a ``<w:hyperlink w:anchor=...>`` element.

    The repair form for a citation that LOST its link: Word converts
    field links to elements on every save anyway, so a repair writes the
    element directly. A span fragmented across runs (Word splits entry
    heads at rsid boundaries — LI7's Hudiyana entry) is wrapped whole:
    the edge runs are split at the span's edges, every covered run gains
    the character style, and anything sitting between runs (a bookmark,
    a proof-error mark) rides along inside the link.
    """
    _, _, at, end = _locate(para_xml, text)
    return wrap_visible_span(para_xml, at, end, anchor, style=style)


def wrap_visible_span(para_xml: str, at: int, end: int, anchor: str, *,
                      style: str = "Hyperlink") -> str:
    """Wrap the visible-text span ``[at, end)`` in an internal hyperlink.

    The positional core of :func:`link_in_para`, public because the
    every-mention passes (:func:`link_rest` here and
    :func:`docxkit.crossrefs.link_more`) target a SPECIFIC occurrence —
    "(Doepke et al. 2019)" cited twice in one paragraph is exactly the
    case a unique-anchor locate cannot express.

    Offsets are into the paragraph's VISIBLE text, not its XML, and they
    are checked: an inverted or out-of-range span used to pass silently
    — the "before" and "after" slices then overlapped and the paragraph
    came out with a stretch of manuscript text DUPLICATED, no exception
    raised and nothing in any report to say so.
    """
    text_len = len(visible_text(para_xml))
    if not 0 <= at <= end <= text_len:
        raise AnchorError(
            f"wrap_visible_span: span [{at}, {end}) is not inside the "
            f"paragraph's {text_len} characters of visible text "
            f"({visible_text(para_xml)[:40]!r})")
    # COUNT WHAT SITS BETWEEN THE RUNS. The offsets come from
    # visible_text(para_xml), which includes OMML — maths lives in `m:r`, and
    # RUN_RE matches `w:r` only. Advancing the cursor solely across w:r runs
    # therefore under-counted every paragraph containing an equation, and each
    # span after the maths landed short by its glyph count: on DSI §6.2 the
    # citation moved 20 characters and the link wrapped the closing full stop
    # instead of "(Foster et al. 2013a)".
    runs, spans, _cursor = run_spans(para_xml)
    covered = [(sp, r) for sp, r in zip(spans, runs, strict=True)
               if sp[1] > at and sp[0] < end]
    if not covered:
        raise AnchorError(f"wrap_visible_span: span {at}..{end} is empty")
    (fs, _fe), first = covered[0]
    (ls, le), last = covered[-1]

    # CUT the runs rather than rebuilding each fragment from the whole
    # one. `set_run_text` keeps a run's structure, which is right for a
    # run being rewritten and wrong for one being SPLIT: a
    # `w:noBreakHyphen` is structure by that reading and a printed
    # character by every other, so before/inner/after each got a copy.
    # Aging_Well's §1 turned one hyphen into seven over four wraps and
    # printed them inside the citations, and no layer of `compare` could
    # see it — `visible_text` walks `w:t` only (backlog S1, 2026-08-21).
    if first is last:
        before, rest = split_run(first.group(0), at - fs)
        mid, after = split_run(rest, end - at)
        inner = _add_style(mid, style)
    else:
        before, head = split_run(first.group(0), at - fs)
        tail, after = split_run(last.group(0), end - ls)
        middle = RUN_RE.sub(lambda m: _add_style(m.group(0), style),
                            para_xml[first.end():last.start()])
        inner = (_add_style(head, style) + middle
                 + _add_style(tail, style))
    # A half cut at the run's own edge is usually the run's SHELL — open
    # tag, properties, close — and putting that beside the link leaves a
    # zero-width formatting island the next edit inherits. It is not
    # always the shell: every printing child in front of the run's first
    # `w:t` rides LEFT with it, by the document order that keeps the end
    # of a wrap whole, so dropping the half on sight deleted a tab, a
    # no-break hyphen or a line break from the page — and `visible_text`
    # renders none of them, so every text assertion here still passed.
    if at <= fs and not run_holds_content(before):
        before = ""
    if end >= le and not run_holds_content(after):
        after = ""

    linked = f'<w:hyperlink w:anchor="{escape(anchor)}">{inner}</w:hyperlink>'
    return (para_xml[:first.start()] + before + linked + after
            + para_xml[last.end():])


def masked_visible_text(para_xml: str) -> str:
    """The paragraph's visible text with already-linked characters masked.

    Characters inside a ``<w:hyperlink>`` element or a ``HYPERLINK`` field
    span come back as ``\\x00``, so a scanner can find the occurrences of
    a phrase that are still PLAIN — the only ones an every-mention pass
    may touch. Same node walk as :func:`_xml.visible_text`, so offsets
    line up with :func:`wrap_visible_span`.
    """
    from ._xml import _FIELD_RE, _HYPERLINK_EL_RE, T_RE
    regions = [(m.start(), m.end())
               for m in _HYPERLINK_EL_RE.finditer(para_xml)]
    regions += [(m.start(), m.end()) for m in _FIELD_RE.finditer(para_xml)]
    out = []
    for tm in T_RE.finditer(para_xml):
        txt = html.unescape(tm.group(1))
        if span_holding(tm.start(), regions) is not None:
            out.append("\x00" * len(txt))
        else:
            out.append(txt)
    return "".join(out)


def _styled_run(run_xml: str, text: str, style: str) -> str:
    """The run with `text` and a character style added."""
    return _add_style(set_run_text(run_xml, text), style)


def _add_style(run_xml: str, style: str) -> str:
    """Add a character style to a run, text untouched (rStyle is FIRST
    in the rPr sequence, so insertion is unambiguous)."""
    tag = f'<w:rStyle w:val="{style}"/>'
    # The run's OWN properties, in any spelling. Asked for the exact
    # string `<w:rPr>`, an EMPTY `<w:rPr/>` — 18,172 in 248 of 2,954
    # corpus packages — was not found, and a second `w:rPr` went in front
    # of it; and a style only in a `w:rPrChange` snapshot, what the run
    # USED to wear, read as present and left it unstyled (2026-09-17).
    own = own_properties(run_xml, "rPr")
    if own is None:
        m = RUN_OPEN_RE.search(run_xml)
        assert m is not None
        return run_xml[:m.end()] + f"<w:rPr>{tag}</w:rPr>" + run_xml[m.end():]
    start, end, inner = own
    if "<w:rStyle" in live_properties(inner):
        return run_xml
    return run_xml[:start] + f"<w:rPr>{tag}{inner}</w:rPr>" + run_xml[end:]


def bookmark(name: str, bookmark_id: int, inner: str = "") -> str:
    """Wrap `inner` in a bookmark. With no inner, a zero-length marker.

    Ids must be unique across the document: a duplicate leaves Word with
    an unbalanced start/end pair, which the papers have hit as
    "unreadable content".
    """
    return (f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{name}"/>'
            f'{inner}<w:bookmarkEnd w:id="{bookmark_id}"/>')


#: What a citation LINK's label says, in each house form: names, then the
#: year or years — "Rowe and Kahn 1987, 1997". Written against `_YEAR`,
#: the one definition of a year this grammar has. The names are read
#: loosely (any text holding a letter and no bracket) because the label is
#: already a link to an entry: whether it names someone is settled, and
#: `_AUTHORS` would refuse an acronym like "WHO" that the papers cite.
_LABEL_YEARS = rf"{_YEAR}(?:,\s*{_YEAR})*"
_LABEL_NAMES = r"[^()]*?[^\W\d_][^()]*?"
_LABEL_SHAPES = (
    ("narrative", re.compile(
        rf"(?P<names>{_LABEL_NAMES})\s+\((?P<years>{_LABEL_YEARS})\)")),
    ("bracketed", re.compile(
        rf"\((?P<names>{_LABEL_NAMES})\s+(?P<years>{_LABEL_YEARS})\)")),
    ("bare", re.compile(
        rf"(?P<names>{_LABEL_NAMES})\s+(?P<years>{_LABEL_YEARS})")),
)


def citation_shape(label: str) -> tuple[str, str, str] | None:
    """Which house FORM a citation link's label is in:
    ``(form, names, years)``, or None.

    The forms are the ones the house convention tells apart:

    * ``"narrative"`` — ``Name (Year)``, the year's brackets inside the
      link;
    * ``"bare"`` — ``Name Year``, a parenthetical citation whose brackets
      belong to the sentence and stay outside the link;
    * ``"bracketed"`` — ``(Name Year)``, a parenthetical citation whose
      link swallowed both brackets. A convention in some papers and a
      defect in others, which is why the audit judges it against the
      document rather than here.

    None for anything that is not one work and a year — an exhibit link
    ("Table 5"), a year alone ("(2019)"), a span with an unmatched bracket
    (:func:`unbalanced_span`'s business), a reference entry's back-link —
    so a caller converting or judging a citation refuses rather than
    guesses. Read by `to_narrative` and `to_parenthetical`, which move the
    brackets between the forms, and by the audit's BRACKETED SPAN, which
    counts the forms a document uses.
    """
    text = label.strip()
    for form, pattern in _LABEL_SHAPES:
        if (m := pattern.fullmatch(text)) is not None:
            return form, m.group("names").strip(), m.group("years")
    return None


