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
cite Mühlbach and Türkiye — and it recognises the Oxford comma, "&", and
"et al." with or without the final period.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ._citation_audit import check_citations
from ._xml import escape

__all__ = [
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
# "Surname", "Surname et al.", "First and Second",
# "First, Second and Third", "First, Second, and Third"
_AUTHORS = (rf"{_NAME}"
            r"(?:\s+et\s+al\.?)?"
            rf"(?:(?:,\s+|,?\s+(?:and|&)\s+){_NAME})*")
_YEAR = r"\d{4}[a-z]?"
_PARENTHETICAL_RE = re.compile(
    rf"\(({_AUTHORS})(?:\s+\(\d{{4}}\))?\s+({_YEAR})\)")
_NARRATIVE_RE = re.compile(rf"({_AUTHORS})\s+\(({_YEAR})\)")
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

    Both forms, in document order. A narrative citation that sits inside
    a parenthetical one — "(see Maestas et al. (2023))" — is reported
    once, as the parenthetical.
    """
    found: list[Citation] = []
    taken: list[tuple[int, int]] = []
    for m in _PARENTHETICAL_RE.finditer(text):
        found.append(Citation(authors=m.group(1), year=m.group(2),
                              start=m.start(), end=m.end(), narrative=False))
        taken.append((m.start(), m.end()))
    for m in _NARRATIVE_RE.finditer(text):
        if any(s <= m.start() and m.end() <= e for s, e in taken):
            continue
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

