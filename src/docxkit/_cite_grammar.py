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
from dataclasses import dataclass

from ._xml import (
    RUN_RE,
    escape,
    set_run_text,
    visible_text,
)
from .edit import _locate
from .errors import AnchorError

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
_SURNAME = (rf"\b(?:{_PREFIX}\s+|{_LEAD}\s+)*{_NAME}"
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
    """
    flat = text.rstrip(":").casefold()
    if flat in stops:
        return True
    head = re.match(r"[^\W\d_]+", text, re.UNICODE)
    if head is None or head.group(0).casefold() not in stops:
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
    runs, spans, cursor = [], [], 0
    for r in RUN_RE.finditer(para_xml):
        body = visible_text(r.group(0))
        runs.append(r)
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)
    covered = [(sp, r) for sp, r in zip(spans, runs, strict=True)
               if sp[1] > at and sp[0] < end]
    if not covered:
        raise AnchorError(f"wrap_visible_span: span {at}..{end} is empty")
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
        if any(s <= tm.start() < e for s, e in regions):
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


