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
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

from ._xml import (
    PARA_RE,
    RUN_RE,
    escape,
    internal_links,
    set_run_text,
    visible_text,
)
from .edit import _locate
from .errors import AnchorError
from .find import para_slice
from .package import read_parts

__all__ = [
    "AUTHORS_PATTERN",
    "IGNORED_LEADS",
    "REF_HEADINGS",
    "REF_STOPS",
    "YEAR_PATTERN",
    "Citation",
    "Reference",
    "anchor_names",
    "audit_links",
    "bookmark",
    "check_citations",
    "delete_bookmark",
    "find_citations",
    "hyperlink_field",
    "key_for",
    "link_in_para",
    "marker_bookmark",
    "next_bookmark_id",
    "parse_reference",
    "references",
    "wrap_link_in_bookmark",
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
# The lowercase particles may also LEAD a surname — "J. van Ours" is
# cited "(Picchio and van Ours 2013)" — except "of", which only joins
# ("Bank of England"): were it allowed to lead, "the work of Smith
# (2020)" would file under "of Smith".
_LEAD = r"(?:da|de|del|den|der|des|di|du|la|le|ten|ter|van|von)"
_SURNAME = (rf"(?:{_PREFIX}\s+|{_LEAD}\s+)*{_NAME}"
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


def strip_lead(authors: str) -> str:
    """Drop a leading discourse adverb the grammar mistook for an author."""
    m = _LEAD_ADVERB_RE.match(authors)
    if m and m.group(1) in DISCOURSE_LEADS:
        return m.group(2)
    return authors


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


# Every citation form carries a four-digit year. One C-speed scan
# rejects the ~90% of paragraphs that cannot cite before the expensive
# author grammar runs — the audits call this on every paragraph of
# every document they touch.
_YEAR_HINT_RE = re.compile(r"[12]\d{3}")


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
    if _YEAR_HINT_RE.search(text) is None:
        return []
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
    runs, spans, at, end = _locate(para_xml, text)
    covered = [(sp, r) for sp, r in zip(spans, runs, strict=True)
               if sp[1] > at and sp[0] < end]
    if not covered:  # pragma: no cover — _locate already raised
        raise AnchorError(f"link_in_para: {text[:40]!r} not found")
    (fs, _fe), first = covered[0]
    (ls, le), last = covered[-1]

    fbody = visible_text(first.group(0))
    lbody = visible_text(last.group(0))
    before = set_run_text(first.group(0), fbody[:at - fs]) if at > fs else ""
    after = set_run_text(last.group(0), lbody[end - ls:]) if end < le else ""

    if first is last:
        inner = _styled_run(first.group(0), fbody[at - fs:end - fs], style)
    else:
        head = _styled_run(first.group(0), fbody[at - fs:], style)
        tail = _styled_run(last.group(0), lbody[:end - ls], style)
        middle = RUN_RE.sub(lambda m: _add_style(m.group(0), style),
                            para_xml[first.end():last.start()])
        inner = head + middle + tail

    linked = f'<w:hyperlink w:anchor="{escape(anchor)}">{inner}</w:hyperlink>'
    return (para_xml[:first.start()] + before + linked + after
            + para_xml[last.end():])


def _styled_run(run_xml: str, text: str, style: str) -> str:
    """The run with `text` and a character style added."""
    return _add_style(set_run_text(run_xml, text), style)


def _add_style(run_xml: str, style: str) -> str:
    """Add a character style to a run, text untouched (rStyle is FIRST
    in the rPr sequence, so insertion is unambiguous)."""
    tag = f'<w:rStyle w:val="{style}"/>'
    if "<w:rStyle" in run_xml:
        return run_xml
    if "<w:rPr>" in run_xml:
        return run_xml.replace("<w:rPr>", f"<w:rPr>{tag}", 1)
    m = re.search(r"<w:r\b[^>]*>", run_xml)
    assert m is not None
    return run_xml[:m.end()] + f"<w:rPr>{tag}</w:rPr>" + run_xml[m.end():]


def bookmark(name: str, bookmark_id: int, inner: str = "") -> str:
    """Wrap `inner` in a bookmark. With no inner, a zero-length marker.

    Ids must be unique across the document: a duplicate leaves Word with
    an unbalanced start/end pair, which the papers have hit as
    "unreadable content".
    """
    return (f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{name}"/>'
            f'{inner}<w:bookmarkEnd w:id="{bookmark_id}"/>')


# ------------------------------------------------- link/bookmark repair ---
# Grown in the API10 and LE link-repair rounds, where each paper script
# carried its own copy — the second use is what moved them here.

_BOOKMARK_ID_RE = re.compile(r'<w:bookmark(?:Start|End)[^>]*w:id="(\d+)"')


def next_bookmark_id(*xmls: str) -> int:
    """One above the highest bookmark id across the given parts.

    Ids must be unique across the WHOLE document, so pass every part you
    will write bookmarks into — a footnote bookmark clashing with a body
    id is the same "unreadable content" failure as a body duplicate.
    """
    ids = [int(m) for xml in xmls for m in _BOOKMARK_ID_RE.findall(xml)]
    return max(ids, default=0) + 1


def marker_bookmark(xml: str, sig: str, name: str, bid: int) -> str:
    """A zero-length bookmark at the head of the ONE paragraph matching
    `sig` — INSIDE the paragraph, so it travels with any future move.

    Body-level markers between paragraphs do NOT travel: reordering
    API10's reference list stranded thirteen of them one entry off,
    because a paragraph cut takes the ``<w:p>`` and nothing beside it.
    """
    s, e = para_slice(xml, sig)
    para = xml[s:e]
    m = re.match(r"<w:p\b[^>]*>(<w:pPr>.*?</w:pPr>)?", para, re.DOTALL)
    assert m is not None
    return (xml[:s] + para[:m.end()] + bookmark(name, bid) + para[m.end():]
            + xml[e:])


def wrap_link_in_bookmark(xml: str, anchor: str, name: str,
                          bid: int) -> str:
    """Recreate `name` around the ONE link that points at `anchor`.

    The ``<key>txt`` convention's in-text end, rebuilt exactly where the
    surviving hyperlink sits — element form, or a complete fldChar
    field whose instruction carries the anchor.
    """
    start = f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
    end = f'<w:bookmarkEnd w:id="{bid}"/>'

    el = re.compile(rf'<w:hyperlink\b[^>]*w:anchor="{anchor}"[^>]*>'
                    r".*?</w:hyperlink>", re.DOTALL)
    hits = list(el.finditer(xml))
    if len(hits) == 1:
        m = hits[0]
        return xml[:m.start()] + start + m.group(0) + end + xml[m.end():]
    if hits:
        raise AnchorError(
            f"wrap_link_in_bookmark: {anchor} matched {len(hits)} elements")

    spans = []
    for bm in re.finditer(r'<w:fldChar\b[^>]*w:fldCharType="begin"', xml):
        r_start = xml.rfind("<w:r", 0, bm.start())
        e_off = xml.find('w:fldCharType="end"', bm.end())
        if r_start < 0 or e_off < 0:
            continue
        r_end = xml.find("</w:r>", e_off) + len("</w:r>")
        if f'"{anchor}"' in xml[r_start:r_end]:
            spans.append((r_start, r_end))
    if len(spans) != 1:
        raise AnchorError(
            f"wrap_link_in_bookmark: {anchor} found {len(spans)} fields")
    s, e = spans[0]
    return xml[:s] + start + xml[s:e] + end + xml[e:]


def delete_bookmark(xml: str, name: str) -> str:
    """Remove the Start/End pair `name` (id read off the Start)."""
    m = re.search(rf'<w:bookmarkStart w:id="(\d+)" w:name="{name}"/>', xml)
    if m is None:
        raise AnchorError(f"delete_bookmark: {name} not found")
    xml = xml[:m.start()] + xml[m.end():]
    endtag = f'<w:bookmarkEnd w:id="{m.group(1)}"/>'
    if xml.count(endtag) != 1:
        raise AnchorError(f"delete_bookmark: end of {name} not unique")
    return xml.replace(endtag, "")


# ------------------------------------------------------ the link audit ---

_BOOKMARK_NAME_RE = re.compile(r'<w:bookmarkStart[^>]*w:name="([^"]+)"')


def audit_links(parts: dict[str, bytes], *,
                heading: str | tuple[str, ...] = _DEFAULT_HEADINGS,
                ignore: frozenset[str] | set[str] = IGNORED_LEADS,
                ) -> tuple[list[str], dict[str, int]]:
    """Audit the bidirectional citation-link convention; (issues, stats).

    The papers' bookmark shape: the reference entry carries ``<name>``
    and the in-text mention ``<name>txt`` (``Halliday2020`` /
    ``Halliday2020txt``), each end hyperlinking to the other; figure and
    table first-mention links follow the same shape, so they audit
    identically. Documents built on :func:`anchor_names`'s
    ``cite_``/``ref_`` naming still get the orphan, broken-link and
    cross-reference checks — only the ``txt``-pairing checks are
    specific to the suffix shape.

    Anchors resolve against EVERY bookmark in the document — including
    Word's own ``_Toc``/``_Heading`` names. The audit this replaces
    excluded underscore names from its index and then reported links to
    them as broken; LE le15 shipped an audit round with nine of those
    false positives before the cause was found.
    """
    doc = parts["word/document.xml"].decode("utf-8")
    paras = list(PARA_RE.finditer(doc))
    texts = [visible_text(m.group(0)) for m in paras]

    bookmarks: dict[str, int] = {}          # first definition wins
    links: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for i, m in enumerate(paras):
        for name in _BOOKMARK_NAME_RE.findall(m.group(0)):
            bookmarks.setdefault(name, i)
        for anchor, label in internal_links(m.group(0)):
            links[anchor].append((i, label))
    for name in _BOOKMARK_NAME_RE.findall(doc):
        bookmarks.setdefault(name, -1)      # BODY-LEVEL, between paragraphs
    foot = parts.get("word/footnotes.xml")
    if foot:
        ftext = foot.decode("utf-8")
        for name in _BOOKMARK_NAME_RE.findall(ftext):
            bookmarks.setdefault(name, -2)  # defined in a footnote
        for anchor, label in internal_links(ftext):
            links[anchor].append((-2, label))

    cite_marks = {n: i for n, i in bookmarks.items()
                  if not n.startswith("_") and n.endswith("txt")}
    eq_marks = {n: i for n, i in bookmarks.items()
                if not n.startswith("_") and n.startswith("Eq")}
    ref_marks = {n: i for n, i in bookmarks.items()
                 if not n.startswith("_") and n not in cite_marks
                 and n not in eq_marks}

    def where(i: int) -> str:
        # "body" = a body-level definition between paragraphs. The first
        # audit round printed those as "fn" and the API repair went
        # hunting in footnotes.xml for bookmarks that were never there.
        return {-1: "body", -2: "fn"}.get(i) or f"¶{i + 1}"

    issues: list[str] = []
    for key, idx in sorted(ref_marks.items(), key=lambda kv: kv[1]):
        if not links.get(key):
            issues.append(f"ORPHAN REF: bookmark '{key}' ({where(idx)}) "
                          "has no in-text hyperlink pointing to it")
    for name, idx in sorted(cite_marks.items(), key=lambda kv: kv[1]):
        if not links.get(name):
            issues.append(f"NO BACK-LINK: in-text bookmark '{name}' "
                          f"({where(idx)}) has no reference back-link")
        if name[:-3] not in ref_marks:
            issues.append(f"MISSING REF: in-text citation '{name}' "
                          f"({where(idx)}) links to '{name[:-3]}' but no "
                          "reference bookmark exists")
    broken = 0
    for anchor, sites in sorted(links.items()):
        if anchor not in bookmarks:
            for i, label in sites:
                issues.append(f"BROKEN LINK: hyperlink to '{anchor}' "
                              f'({where(i)}, "{label[:40]}") '
                              "— no such bookmark")
                broken += 1

    # Unlinked citation-like text, on the shared grammar. Only body
    # prose before the reference list; the first five paragraphs are the
    # title block, where author names read as citations.
    wanted = {h.casefold()
              for h in ((heading,) if isinstance(heading, str) else heading)}
    head_idx = next((i for i, t in enumerate(texts)
                     if t.strip().rstrip(":").casefold() in wanted),
                    len(texts))
    ignored = {s.casefold() for s in ignore}
    labels = {lb.strip() for sites in links.values() for _, lb in sites}
    unlinked = 0
    for i, text in enumerate(texts[:head_idx]):
        if i < 5:
            continue
        for found in find_citations(text):
            c = replace(found, authors=strip_lead(found.authors))
            if c.surname.casefold() in ignored:
                continue
            cite = text[c.start:c.end].strip()
            cores = (f"{c.authors} {c.year}", f"{c.authors} ({c.year})")
            if any(cite in lb or cores[0] in lb or cores[1] in lb
                   for lb in labels):
                continue
            issues.append(f'UNLINKED: "{cite}" (¶{i + 1}) — looks like a '
                          "citation but is not hyperlinked")
            unlinked += 1

    cited_keys = {n[:-3] for n in cite_marks}
    cited_keys |= {a for a in links if a in ref_marks}
    for key in sorted(cited_keys - ref_marks.keys()):
        issues.append(f"CITE WITHOUT REF: '{key}' cited in text but no "
                      "reference bookmark")
    for key in sorted(ref_marks.keys() - cited_keys):
        issues.append(f"REF WITHOUT CITE: '{key}' "
                      f"({where(ref_marks[key])}) in references but never "
                      "cited in text")

    stats = {"paragraphs": len(paras), "bookmarks": len(bookmarks),
             "cite_bookmarks": len(cite_marks),
             "ref_bookmarks": len(ref_marks), "eq_bookmarks": len(eq_marks),
             "links": sum(len(v) for v in links.values()),
             "broken": broken, "unlinked": unlinked}
    return issues, stats


def check_citations(docx_path: str | Path) -> int:
    """Print the link audit for a manuscript; the count of issues found.

    The CLI entry (``docxkit citations``) and the drop-in replacement for
    the ported ``check_citation_links.py``: same contract (report to
    stdout, 0 issues means clean), same issue prefixes.
    """
    issues, stats = audit_links(read_parts(docx_path))
    print(f"Document: {docx_path}")
    print(f"Paragraphs: {stats['paragraphs']}")
    print(f"Bookmarks: {stats['bookmarks']} ({stats['cite_bookmarks']} "
          f"in-text, {stats['ref_bookmarks']} reference, "
          f"{stats['eq_bookmarks']} equation)")
    print(f"Hyperlinks: {stats['links']} total "
          f"({stats['broken']} broken, {stats['unlinked']} unlinked "
          "citation-like mentions)")
    print("=" * 60)
    if not issues:
        print("ALL CHECKS PASSED — no issues found.")
    else:
        print(f"FOUND {len(issues)} ISSUE(S):\n")
        for issue in issues:
            print(f"  - {issue}")
    return len(issues)

