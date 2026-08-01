r"""Citations: finding them in prose, parsing the reference list, linking.

``link_citations.py`` exists twice — AFI's 659 lines and HPPA's 518 —
because every paper wants the same thing: each in-text citation
hyperlinked to its reference entry, and each entry back-linked to where
it is first cited. What differs between papers is the house style, the
institutional-author aliases and which heading starts the references, so
those stay with the paper. What is shared is here: recognising a
citation, parsing an entry, and building the field/bookmark XML.

Two forms occur and both must be handled, because a paper mixes them:

    parenthetical   ... rises with age (Maestas et al. 2023).
    narrative       Maestas et al. (2023) estimate willingness to pay.

The detection is deliberately conservative about what a surname looks
like — accented and Latin-Extended capitals included, since these papers
cite Mühlbach and Türkiye — and it recognises the Oxford comma, "&",
"et al." with or without the final period, prefix particles ("De
Giorgi", "Van Reenen"), several works in one parenthesis ("(Cameron et
al. 2008; Roodman et al. 2019)"), a prefixed aside ("(e.g., Cahill et
al. 2015)") and a page suffix ("(Smith 2020, p. 45)").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ._citation_audit import check_citations
from ._xml import escape

__all__ = [
    "AUTHORS_PATTERN",
    "REF_HEADINGS",
    "REF_STOPS",
    "YEAR_PATTERN",
    "Citation",
    "Reference",
    "anchor_names",
    "bookmark",
    "check_citations",
    "find_citations",
    "hyperlink_field",
    "key_for",
    "parse_reference",
    "references",
]

# A surname starts with a capital — including accented (U+00C0..U+00FF)
# and Latin Extended-A (U+0100..U+017F), because these papers cite
# Mühlbach — and continues with word characters, hyphen, apostrophe
# (straight or typographic) or period.
_NAME_CHAR = r"\w\-'.’"
_NAME = rf"[A-ZÀ-ÿĀ-ſ][{_NAME_CHAR}]*"
# A surname can span tokens two ways: a capitalised prefix particle
# ("De Giorgi", "Van Reenen", "La Porta") and a lowercase join ("Bank of
# England", "Ministry of Health"). Free capitalised adjacency is NOT
# allowed — "As Smith (2020) shows" would file under "As Smith" — so a
# plain multi-word institution ("World Bank") is captured from its last
# word only; :mod:`docxkit.refstyle` reconciles that against the entry.
_PREFIX = r"(?:Da|De|Del|Della|Der|Des|Di|Du|La|Le|Ten|Ter|Van|Von)"
_PARTICLE = r"(?:da|de|del|den|der|des|di|du|la|le|of|ten|ter|van|von)"
_SURNAME = (rf"(?:{_PREFIX}\s+)*{_NAME}"
            rf"(?:\s+{_PARTICLE}(?:\s+{_PARTICLE})*\s+{_NAME})*")
# "Surname", "Surname et al.", "First and Second",
# "First, Second and Third", "First, Second, and Third"
_AUTHORS = (rf"{_SURNAME}"
            r"(?:\s+et\s+al\.?)?"
            rf"(?:(?:,\s+|,?\s+(?:and|&)\s+){_SURNAME})*")
_YEAR = r"\d{4}[a-z]?"
# In-text citations hide inside parenthesis GROUPS, which real papers
# fill with more than one work: "(Bernheim and Rangel 2009; Chetty
# 2015)", "(Cameron et al. 2008, Roodman et al. 2019)", "(e.g., Cahill
# et al. 2015)", "(Smith 2020, p. 45)". A whole-group pattern found none
# of these — the LE audit read ten cited entries as uncited. So the
# group is scanned for citation SEGMENTS, each anchored so its year
# CLOSES it (the group's end, a semicolon, or a comma) — "in Almaty
# 2005 the" does not cite.
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_SEGMENT_RE = re.compile(rf"({_AUTHORS})\s+({_YEAR})(?=\s*(?:[;,]|$))")
# The narrative parens may carry a locator: "Maestas et al. (2023, p. 45)".
_NARRATIVE_RE = re.compile(
    rf"({_AUTHORS})\s+\(({_YEAR})(?:,\s+pp?\.[^)]*)?\)")
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
_DEFAULT_STOPS = ("Appendix", "Appendices", "Figures", "Tables",
                  "Приложение", "Приложения")
# In these papers the figures and tables are moved below the references,
# so their captions end the list just as a heading would.
_CAPTION_START_RE = re.compile(
    r"^(?:Figure|Table|Рисунок|Таблица)\s+\S+[.:]")
# A repeated-author entry: "———. 2019." or "____. 2019." stands in for the
# author named on the entry above.
_CONTINUATION_RE = re.compile(r"^[-—–_—–]{2,}[.,]?\s")

# Public names for the grammar and the section markers:
# :mod:`docxkit.refstyle` builds its format checks on the SAME patterns
# rather than defining a second citation grammar that would drift.
AUTHORS_PATTERN = _AUTHORS
YEAR_PATTERN = _YEAR
REF_HEADINGS = _DEFAULT_HEADINGS
REF_STOPS = _DEFAULT_STOPS


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
        lead = re.split(r",|\s+(?:and|&)\s+|\s+et\s+al", self.authors)[0]
        return lead.strip()

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


def anchor_names(key: str) -> tuple[str, str]:
    """(citation anchor, reference anchor) for a key.

    The house convention across these papers: the in-text mention is
    wrapped in ``cite_<key>`` and links to ``ref_<key>``; the reference
    entry is wrapped in ``ref_<key>`` and links back to ``cite_<key>``.
    That pairing is what makes the links bidirectional, and what
    :func:`check_citations` audits.
    """
    return f"cite_{key}", f"ref_{key}"


def find_citations(text: str) -> list[Citation]:
    """Every in-text citation in a paragraph's visible text.

    Both forms, in document order. A parenthesis group holding several
    works — "(Bernheim and Rangel 2009; Chetty 2015)" — yields one
    :class:`Citation` per work, each with its own span. A narrative
    citation inside a parenthetical aside — "(see Maestas et al.
    (2023))" — is reported once, as the narrative form; the two loops
    cannot double-report, because a segment's text can hold no
    parenthesis and a narrative match must hold its "(year)".
    """
    found: list[Citation] = []
    for pm in _PAREN_RE.finditer(text):
        base = pm.start(1)
        for m in _SEGMENT_RE.finditer(pm.group(1)):
            found.append(Citation(authors=m.group(1), year=m.group(2),
                                  start=base + m.start(),
                                  end=base + m.end(), narrative=False))
    for m in _NARRATIVE_RE.finditer(text):
        found.append(Citation(authors=m.group(1), year=m.group(2),
                              start=m.start(), end=m.end(), narrative=True))
    return sorted(found, key=lambda c: c.start)


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
    surname = (lead.split(",", 1)[0] if "," in lead
               else lead.split(".", 1)[0])
    surname = surname.strip()
    if not surname:
        return None
    return Reference(text=text.strip(), surname=surname, year=m.group(1),
                     index=index)


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
        if text.rstrip(":").casefold() in {s.casefold() for s in stop}:
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


def bookmark(name: str, bookmark_id: int, inner: str = "") -> str:
    """Wrap `inner` in a bookmark. With no inner, a zero-length marker.

    Ids must be unique across the document: a duplicate leaves Word with
    an unbalanced start/end pair, which the papers have hit as
    "unreadable content".
    """
    return (f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{name}"/>'
            f'{inner}<w:bookmarkEnd w:id="{bookmark_id}"/>')

