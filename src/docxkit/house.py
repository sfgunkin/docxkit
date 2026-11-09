r"""House style: the typography every paper here shares, applied and audited.

The rules were written down before most of these papers started and were
broken by most of them anyway — Health_Capacity_to_Work's audit found
caption `keepNext` on 0 of 22, a figure-note indent on 0 of 8, and notes
at three different sizes. They decayed the same way every time: each new
exhibit was built by cloning whatever sat next to it, which propagates
the neighbour's defects and never converges on the standard. **A
convention remembered rather than applied is a convention that decays**,
so this is the applier, and :func:`audit` is the gate beside it.

Ported from HCW's `house_style.py` — "general to every paper, not this
one", its header said, and it lived in that paper's scripts.

**What it sets.**

* **Captions** ("Table 3.", "Figure 2:" — :func:`docxkit.find.caption_re`,
  THE caption definition): Times New Roman 12, not italic, left, 2 pt
  after, single spaced, and `keepNext`, so a caption never sits alone at
  the foot of a page.
* **Notes** ("Note:", "Notes:", "Source:"): Times New Roman 10, single
  spaced, left, 8 pt after — the author's figure, 2026-08-23, over the
  20 pt nine of HCW's notes carried. A note directly under a FIGURE also
  takes a 0.5" indent on both sides, matching the figure block rather
  than the text column. `w:before` is kept: single spacing is a
  line-height rule, not licence to close the gap between two exhibits.
* **The Abstract**: only the word "Abstract" bold, single spaced, 0.5"
  indents on both sides.
* **Numbered display equations** in the 1x3 grid of
  :func:`docxkit.equations.numbered_grid` — see
  :func:`~docxkit.equations.number_displays` for why a tab stop is not
  enough.
* **The paragraph that leads into a display equation**: 4 pt after —
  the author's rule, 2026-09-26 (Misconceptions). Only `w:after` is
  written; the paragraph keeps its own line spacing and space before.
  A caption, a note or another equation above an equation is not a
  lead-in and keeps its own rule.

Each face goes on the paragraph MARK as well as the runs: the mark's size
sets the height of an empty trailing line, and a note that looks right can
still sit on an 11 pt baseline. `rStyle` is never touched, so a caption's
link and a source note's citation stay links.

**What it does not set**, and says so: page flow. Every exhibit on its
own page, the single-line-title exception, and the blank pages two
adjacent breaks produce are HCW's four page rules; they are about the
render rather than the type, and are left to a paper's own pass and to
`pages --check`.

**Why the audit resolves through the styles.** Word deletes a paragraph
property equal to the one it would inherit, so a caption left-aligned by
its style comes back from a save with its `w:jc` gone. Read off the
paragraph, that is a violation; read through :class:`styles.Cascade`, it
is the rule kept. Run faces are read as written — the applier always
writes them, and Word keeps direct run formatting.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from lxml import etree

from . import exhibits as _exhibits
from ._xml import (
    DOCUMENT,
    FLDCHAR_RE,
    INSTR_RE,
    MARK_REVISION_RE,
    PARA_OPEN_RE,
    PARA_RE,
    RUN_RE,
    Parts,
    _own_children,
    element_spans,
    fields,
    live_properties,
    matching_close,
    own_properties,
    set_para_property,
    set_run_property,
    visible_text,
)
from .edit import embolden, is_field_run, set_run_properties
from .equations import (
    EQ_NUMBER_RE,
    OMATH_RE,
    display_equations,
    number_displays,
)
from .errors import AnchorError
from .find import caption_re
from .styles import Cascade

__all__ = [
    "HOUSE",
    "NOTE",
    "AnchorError",
    "Face",
    "HouseReport",
    "Rules",
    "Scope",
    "apply",
    "audit",
    "scope",
]

#: A note to an exhibit opens on its label. Narrower than
#: `exhibits.NOTE`, which also takes a bare `*` or `1)` line — right for
#: deciding what belongs to an exhibit's block, wrong for restyling every
#: paragraph in a document that happens to open that way. INSIDE a block
#: the wide one decides (:func:`_span_notes`): ep3_sc's Table 3 note opens
#: "* The monthly costs…", moved with its table, and kept the body face
#: because this pattern refused it (2026-11-03).
NOTE = re.compile(r"^\s*(?:Notes?|Sources?|Примечани[ея]|Источник[иа]?)\s*:",
                  re.IGNORECASE)
#: Body-level containers whose paragraphs are not body children.
_CONTAINERS = ("tbl", "sdt", "customXml")
_WS_RE = re.compile(r"\s+")


def _span_notes(xml: str) -> set[int]:
    """Start offsets of the body-level paragraphs an exhibit's block owns
    as NOTES — :data:`docxkit.exhibits.NOTE`, the definition that decided
    they travel with the exhibit, so the two can no longer disagree.

    Located by body-level paragraph ORDINAL, then checked by text: if the
    string walk and the tree disagree on either, the paragraph is left to
    :data:`NOTE` alone rather than guessed at.
    """
    try:
        root = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return set()
    body = root.find(_exhibits.W + "body")
    if body is None:
        return set()
    kids = list(body)
    owned: dict[int, str] = {}              # paragraph ordinal -> its text
    ordinal = {i: n for n, i in enumerate(
        i for i, el in enumerate(kids) if el.tag == _exhibits.W + "p")}
    for x in _exhibits.exhibits(body):
        if x.body_at is None:
            continue
        # the WHOLE block but its caption and body: a note can sit between
        # them — a picture, its "*" note, then a caption below — and a
        # scan from the later of the two never saw it (review, 2026-11-09)
        for i in range(x.start, x.stop):
            if i in (x.body_at, x.caption_at):
                continue
            text = _exhibits.text_of(kids[i]).strip()
            if (i in ordinal and text and _exhibits.NOTE.match(text)
                    and not caption_re().match(text)):
                owned[ordinal[i]] = text
    if not owned:
        return set()
    bodies = element_spans(xml, "body")
    if not bodies:
        return set()
    base, top = bodies[0]
    inner = xml[base:top]
    held = [sp for tag in _CONTAINERS for sp in element_spans(inner, tag)]
    paras: list[tuple[int, int]] = []
    pos = 0
    # an EMPTY <w:p/> is a body child too, and `element_spans` skips one
    # (it has no content to span): ep3_sc has one, and the ordinals were
    # off by one from it on (2026-11-09)
    while (m := PARA_OPEN_RE.search(inner, pos)) is not None:
        end = (m.end() if m.group(1) else
               matching_close(inner, m.end(), "p"))
        if not any(c <= m.start() < d for c, d in held):
            paras.append((m.start() + base, end + base))
        pos = end
    if len(paras) != len(ordinal):
        return set()
    out = set()
    for n, text in owned.items():
        a, b = paras[n]
        # the tree side reads `w:t` only, so the string side drops the
        # maths before comparing: a note holding an inline `p` in OMML
        # failed the check and kept the body face (review, 2026-11-09)
        shown = visible_text(OMATH_RE.sub("", xml[a:b]))
        if _WS_RE.sub("", shown) == _WS_RE.sub("", text):
            out.add(a)
    return out
#: The Abstract's label: alone as a heading, or opening its paragraph.
_ABSTRACT_RE = re.compile(r"^\s*(Abstract)\b\s*[:.\u2014\u2013-]?\s*",
                          re.IGNORECASE)
_SINGLE = "240"
#: A picture, in any of the three forms Word writes one, as `exhibits`
#: reads it.
_PICTURE_RE = re.compile(r"<w:(?:drawing|pict|object)\b")


@dataclass(frozen=True)
class Face:
    """A run face: font, size, and (optionally) italics forced off."""

    font: str = "Times New Roman"
    size_pt: float = 12
    #: False writes italics OFF — a caption style is italic in Word's
    #: default template. None leaves italics to the document.
    italic: bool | None = None

    @property
    def half_points(self) -> str:
        return str(round(self.size_pt * 2))

    def props(self) -> dict[str, str]:
        """`edit.set_run_properties`' form: CT_RPr tag -> element."""
        out = {"rFonts": (f'<w:rFonts w:ascii="{self.font}" '
                          f'w:hAnsi="{self.font}" w:cs="{self.font}"/>'),
               "sz": f'<w:sz w:val="{self.half_points}"/>',
               "szCs": f'<w:szCs w:val="{self.half_points}"/>'}
        if self.italic is not None:
            state = "" if self.italic else ' w:val="false"'
            out["i"] = f"<w:i{state}/>"
            out["iCs"] = f"<w:iCs{state}/>"
        return out


@dataclass(frozen=True)
class Rules:
    """The house, as data — a paper that differs passes its own."""

    caption: Face = Face(size_pt=12, italic=False)
    caption_after: int = 40              # twips: 2 pt, hugs its exhibit
    note: Face = Face(size_pt=10)
    note_after: int = 160                # twips: 8 pt
    figure_note_indent: int = 720        # twips: 0.5"
    abstract_indent: int = 720
    number_equations: bool = True
    #: twips after the prose paragraph leading into a display equation
    #: (4 pt); None leaves those paragraphs alone.
    equation_lead_after: int | None = 80


HOUSE = Rules()


@dataclass(frozen=True)
class HouseReport:
    """What :func:`apply` set. Counts of paragraphs, not of attempts."""

    captions: int
    notes: int
    figure_notes: int
    runs: int
    #: "inline" ("Abstract: …" in one paragraph), "heading" (a paragraph
    #: reading "Abstract" and the one after it), or "" — none found.
    abstract: str
    equations: int
    #: prose paragraphs leading into a display equation, spacing set
    lead_ins: int = 0

    def format(self) -> str:
        return (f"captions {self.captions}, notes {self.notes} "
                f"({self.figure_notes} under a figure), runs restyled "
                f"{self.runs}, abstract {self.abstract or 'not found'}, "
                f"numbered equations set {self.equations}, equation "
                f"lead-ins {self.lead_ins}")


# ---------------------------------------------------------------- apply --


def _with_mark(para: str, face: Face) -> str:
    """The paragraph MARK given `face` — its size sets an empty line's.

    The mark's `w:rPr` is found among the pPr's DIRECT children, wherever
    it sits: `own_properties` answers only for a FIRST child, so behind a
    `w:spacing` the mark was rebuilt from nothing, and a co-author's
    pending mark `w:ins`/`w:del` went with it — rejecting their change
    no longer removed the paragraph (review, 2026-11-09). Those revision
    marks open CT_ParaRPr and stay first; the face goes after them."""
    ppr = own_properties(para, "pPr")
    mark = ""
    if ppr is not None:
        for tag, start, end in _own_children(ppr[2]):
            if tag == "rPr":
                mark = ppr[2][start:end]
    revs = "".join(MARK_REVISION_RE.findall(mark))
    run = f"<w:r>{MARK_REVISION_RE.sub('', mark)}</w:r>"
    for tag, element in face.props().items():
        run = set_run_property(run, tag, element)
    own = own_properties(run, "rPr")
    assert own is not None
    face_rpr = run[own[0]:own[1]]
    face_inner = face_rpr[face_rpr.index(">") + 1:face_rpr.rindex("<")]
    return set_para_property(para, "rPr", f"<w:rPr>{revs}{face_inner}</w:rPr>")


def _spacing(para: str, after: int) -> str:
    """Single spaced, `after` twips after, the paragraph's own `before`."""
    ppr = own_properties(para, "pPr")
    keep = ""
    if ppr is not None:
        m = re.search(r"<w:spacing\b[^>]*/>", live_properties(ppr[2]))
        if m is not None:
            keep = " ".join(re.findall(
                r'\bw:before(?:Lines|Autospacing)?="[^"]*"', m.group(0)))
    keep = f" {keep}" if keep else ""
    return set_para_property(
        para, "spacing",
        f'<w:spacing{keep} w:after="{after}" w:line="{_SINGLE}" '
        'w:lineRule="auto"/>')


#: The fields a caption numbers itself with: Insert Caption writes SEQ,
#: chapter numbering adds STYLEREF.
_NUMBERING_RE = re.compile(r"^\s*(?:SEQ|STYLEREF)\b", re.IGNORECASE)
#: Either switch keeps the face a result was given across an update.
_KEEPS_FACE_RE = re.compile(r"\\\*\s*(?:MERGEFORMAT|CHARFORMAT)\b",
                            re.IGNORECASE)
_FLDSIMPLE_RE = re.compile(
    r'(<w:fldSimple\b[^>]*?\bw:instr=")([^"]*)("[^>]*?)(/?)>')
_SWITCH = r" \* MERGEFORMAT "


def _numbering_fields(para: str) -> list[tuple[int, int, str]]:
    """``(start, end, instruction)`` of the place each caption-number
    field's instruction is WRITTEN — the `w:instr` value of a
    `w:fldSimple`, or the last `w:instrText` of a fldChar field — for
    every one that SHOWS a result. Only the field's own instruction: a
    field nested inside another's is its own entry."""
    out = []
    for m in _FLDSIMPLE_RE.finditer(para):
        if not m.group(4) and _NUMBERING_RE.match(html.unescape(m.group(2))):
            out.append((m.start(2), m.end(2), html.unescape(m.group(2))))
    for f in fields(para):
        if f.result is None or f.at < 0 or not _NUMBERING_RE.match(f.instr):
            continue
        depth, last = 0, None
        marks = sorted([*FLDCHAR_RE.finditer(para, f.start, f.end),
                        *INSTR_RE.finditer(para, f.start, f.end)],
                       key=lambda x: x.start())
        for x in marks:
            if x.re is INSTR_RE:
                if depth == 1:
                    last = x
            elif x.group(1) == "begin":
                depth += 1
            elif x.group(1) == "end":
                depth -= 1
            elif depth == 1:                 # this field's `separate`
                break
        if last is not None:
            out.append((last.start(1), last.end(1), f.instr))
    return sorted(out)


def _keep_number_face(para: str) -> str:
    r"""`para` with ``\* MERGEFORMAT`` on each caption-number field that
    lacks a face-keeping switch. Without it Word regenerates the result
    in the PARAGRAPH style on its next field update — which printing and
    PDF export both run — and the face just written to the result runs
    is thrown away: ep3_sc's "1" printed 9 pt accent-blue under a caption
    whose XML said Times 12 black (2026-11-03)."""
    for a, b, instr in reversed(_numbering_fields(para)):
        if _KEEPS_FACE_RE.search(instr):
            continue
        written = para[a:b]
        para = para[:a] + written.rstrip() + _SWITCH + para[b:]
    return para


def _styled(para: str, face: Face, after: int) -> tuple[str, int]:
    para, runs = set_run_properties(para, face.props())
    para = _keep_number_face(para)
    para = _with_mark(para, face)
    para = set_para_property(para, "jc", '<w:jc w:val="left"/>')
    return _spacing(para, after), runs


def _abstract(xml: str, rules: Rules) -> tuple[str, str]:
    """The Abstract, set; and which form it was in."""
    paras = list(PARA_RE.finditer(xml))
    for i, m in enumerate(paras):
        text = visible_text(m.group(0))
        label = _ABSTRACT_RE.match(text)
        if label is None:
            continue
        inline = bool(text[label.end():].strip())
        if not inline and i + 1 >= len(paras):
            return xml, ""
        body = m if inline else paras[i + 1]
        para, _runs = set_run_properties(body.group(0),
                                         {"b": "", "bCs": ""})
        if inline:
            para = embolden(para, label.group(1), within=text.strip()[:60])
        para = _spacing(para, _after_of(para))
        para = set_para_property(
            para, "ind", f'<w:ind w:left="{rules.abstract_indent}" '
                         f'w:right="{rules.abstract_indent}"/>')
        xml = xml[:body.start()] + para + xml[body.end():]
        if not inline:
            head = embolden(m.group(0), label.group(1))
            xml = xml[:m.start()] + head + xml[m.end():]
        return xml, "inline" if inline else "heading"
    return xml, ""


def _after_of(para: str) -> int:
    """The paragraph's own space-after, in twips, or 0."""
    ppr = own_properties(para, "pPr")
    if ppr is not None and (m := re.search(
            r'<w:spacing\b[^>]*\bw:after="(\d+)"', live_properties(ppr[2]))):
        return int(m.group(1))
    return 0


#: Between a lead-in and its equation only these may sit: whitespace,
#: bookmarks, proofing marks. Anything else — an empty paragraph, the
#: end of a table — means the paragraph above is not the lead-in.
_ADJACENT_RE = re.compile(
    r"(?:\s|<w:(?:bookmarkStart|bookmarkEnd|proofErr|permStart|permEnd)"
    r"\b[^>]*/>)*")


def _lead_ins(xml: str) -> list[re.Match[str]]:
    """The prose paragraph directly above each display equation, in
    document order. A numbered equation sits in its grid, so "above" is
    above the TABLE; an equation whose paragraph above is a caption, a
    note or another equation has no lead-in."""
    tables = element_spans(xml, "tbl")
    paras = list(PARA_RE.finditer(xml))
    cap_re = caption_re()
    # a block's "*" note is a note too: styled as one and then re-spaced
    # as a lead-in, it could never audit clean (review, 2026-11-09)
    block_notes = _span_notes(xml)
    found: dict[int, re.Match[str]] = {}
    for eq in display_equations(xml):
        top = min((lo for lo, hi in tables if lo <= eq.start() < hi),
                  default=eq.start())
        above = [p for p in paras if p.end() <= top]
        if not above:
            continue
        lead = above[-1]
        if not _ADJACENT_RE.fullmatch(xml, lead.end(), top):
            continue
        text = visible_text(OMATH_RE.sub("", lead.group(0))).strip()
        if (not text or cap_re.match(text) or NOTE.match(text)
                or lead.start() in block_notes
                or EQ_NUMBER_RE.fullmatch(text)):
            continue
        found[lead.start()] = lead
    return [found[k] for k in sorted(found)]


def _with_after(para: str, after: int) -> str:
    """`after` twips after; every other spacing attribute kept. `afterLines`
    and `afterAutospacing` go, because Word lets either override `after`."""
    ppr = own_properties(para, "pPr")
    keep = ""
    if ppr is not None and (m := re.search(
            r"<w:spacing\b([^>]*?)/>", live_properties(ppr[2]))):
        keep = re.sub(r'\s*\bw:after(?:Lines|Autospacing)?="[^"]*"', "",
                      m.group(1))
    return set_para_property(para, "spacing",
                             f'<w:spacing{keep} w:after="{after}"/>')


def apply(parts: Parts, rules: Rules = HOUSE) -> HouseReport:
    """Set the house typography on the whole document. Edits `parts`.

    Idempotent: a second call writes the same XML and, since the counts
    are of paragraphs the rules APPLY to, reports the same numbers.
    """
    xml = parts[DOCUMENT].decode("utf-8")
    captions = notes = figure_notes = runs = 0
    cap_re = caption_re()
    paras = list(PARA_RE.finditer(xml))
    in_block = _span_notes(xml)
    for i in range(len(paras) - 1, -1, -1):
        m = paras[i]
        text = visible_text(m.group(0)).strip()
        if cap_re.match(text):
            para, n = _styled(m.group(0), rules.caption, rules.caption_after)
            para = set_para_property(para, "keepNext", "<w:keepNext/>")
            captions += 1
        elif NOTE.match(text) or m.start() in in_block:
            para, n = _styled(m.group(0), rules.note, rules.note_after)
            notes += 1
            if i and _PICTURE_RE.search(paras[i - 1].group(0)):
                indent = rules.figure_note_indent
                para = set_para_property(
                    para, "ind",
                    f'<w:ind w:left="{indent}" w:right="{indent}"/>')
                figure_notes += 1
        else:
            continue
        runs += n
        xml = xml[:m.start()] + para + xml[m.end():]

    xml, abstract = _abstract(xml, rules)
    equations = 0
    if rules.number_equations:
        xml, equations = number_displays(xml)
    lead_ins = 0
    if rules.equation_lead_after is not None:
        # AFTER the numbering: it moves each equation into a table, and
        # the lead-in is whatever sits above the table then.
        for m in reversed(_lead_ins(xml)):
            para = _with_after(m.group(0), rules.equation_lead_after)
            xml = xml[:m.start()] + para + xml[m.end():]
            lead_ins += 1
    parts[DOCUMENT] = xml.encode("utf-8")
    return HouseReport(captions=captions, notes=notes,
                       figure_notes=figure_notes, runs=runs,
                       abstract=abstract, equations=equations,
                       lead_ins=lead_ins)


# ---------------------------------------------------------------- audit --


#: A run's character style, in either attribute spelling Word writes.
_RSTYLE_RE = re.compile(r'<w:rStyle\b[^>]*\bw:val="([^"]*)"')
#: The theme's Latin face for each slot. `[^>]*` stays inside one tag.
_THEME_FONT_RE = {
    kind: re.compile(rf"<a:{kind}Font>.*?<a:latin\b[^>]*\b"
                     r'typeface="([^"]*)"', re.DOTALL)
    for kind in ("minor", "major")
}


def _theme_fonts(parts: Parts) -> dict[str, str]:
    """``{"theme:minorHAnsi": "Aptos", ...}`` from the document's theme."""
    theme = next((blob.decode("utf-8", "replace") for name, blob
                  in sorted(parts.items())
                  if name.startswith("word/theme/")), "")
    out = {}
    for kind, pattern in _THEME_FONT_RE.items():
        if (m := pattern.search(theme)) is not None:
            for slot in ("HAnsi", "Ascii", "Bidi", "EastAsia"):
                out[f"theme:{kind}{slot}"] = m.group(1)
    return out


def _face_findings(para: str, face: Face, cascade: Cascade, *,
                   pstyle: str | None, what: str,
                   themes: dict[str, str]) -> list[str]:
    """The first way a run departs from `face`, RESOLVED through the
    styles: a run in the house font because its paragraph style says so
    is in the house font (HCW, 2026-09-24: sixty-one false findings on a
    paper whose notes all render in Times New Roman through `Normal`)."""
    for r in RUN_RE.finditer(para):
        run = r.group(0)
        if is_field_run(run) or not visible_text(run).strip():
            continue
        own = own_properties(run, "rPr")
        rpr = run[own[0]:own[1]] if own else ""
        style = _RSTYLE_RE.search(rpr)
        rstyle = style.group(1) if style else None
        font = cascade.font(rpr=rpr, rstyle=rstyle, pstyle=pstyle)
        font = themes.get(font or "", font)
        if font != face.font:
            stated = font or "no stated font"
            return [f"{what}: a run is in {stated}, not {face.font}"]
        size = cascade.resolve("sz", rpr=rpr, rstyle=rstyle,
                               pstyle=pstyle).value
        if size != face.half_points:
            shown = "unset" if size is None else f"{int(size) / 2:g} pt"
            return [f"{what}: a run is {shown}, not {face.size_pt:g} pt"]
        if face.italic is False and cascade.toggle(
                "i", rpr=rpr, rstyle=rstyle, pstyle=pstyle):
            return [f"{what}: a run is italic"]
    return []


def _style_gives(cascade: Cascade, pstyle: str | None, face: Face,
                 themes: dict[str, str]) -> bool:
    """Does the paragraph STYLE alone set `face`? Then a field result
    Word regenerates in that style comes back in the house face, and a
    missing ``\\* MERGEFORMAT`` costs nothing."""
    font = cascade.font(rpr="", rstyle=None, pstyle=pstyle)
    size = cascade.resolve("sz", rpr="", rstyle=None, pstyle=pstyle).value
    italic = cascade.toggle("i", rpr="", rstyle=None, pstyle=pstyle)
    return (themes.get(font or "", font) == face.font
            and size == face.half_points
            and not (face.italic is False and italic))


def _para_findings(para: str, cascade: Cascade, pstyle: str | None,
                   what: str, after: int) -> list[str]:
    ppr = own_properties(para, "pPr")
    inner = live_properties(ppr[2]) if ppr else None
    out = []
    jc = cascade.para_attr("jc", "val", ppr=inner, pstyle=pstyle)
    if jc not in (None, "left", "start"):
        out.append(f"{what}: aligned {jc}, not left")
    line = cascade.para_attr("spacing", "line", ppr=inner, pstyle=pstyle)
    if line not in (None, _SINGLE):
        out.append(f"{what}: not single spaced (line {line})")
    got = cascade.para_attr("spacing", "after", ppr=inner, pstyle=pstyle)
    if (got or "0") != str(after):
        out.append(f"{what}: {int(got or 0) / 20:g} pt after, not "
                   f"{after / 20:g}")
    return out


@dataclass(frozen=True)
class Scope:
    """What :func:`audit` has to read: a clean audit of NOTHING is not a
    pass, and printing the count is how a reader tells the two apart."""

    captions: int
    notes: int
    numbered_equations: int

    @property
    def empty(self) -> bool:
        return not (self.captions or self.notes or self.numbered_equations)


def scope(parts: Parts) -> Scope:
    """How many captions, notes and numbered display equations there are
    — in a grid or not — for the rules to apply to."""
    xml = parts[DOCUMENT].decode("utf-8")
    cap_re = caption_re()
    in_block = _span_notes(xml)
    found = [(m.start(), visible_text(m.group(0)).strip())
             for m in PARA_RE.finditer(xml)]
    texts = [t for _, t in found]
    numbered = sum(
        1 for m in display_equations(xml)
        if EQ_NUMBER_RE.search(visible_text(OMATH_RE.sub("", m.group(0))))
        or any(lo <= m.start() < hi for lo, hi in element_spans(xml, "tbl")))
    return Scope(captions=sum(1 for t in texts if cap_re.match(t)),
                 notes=sum(1 for at, t in found
                           if NOTE.match(t) or at in in_block),
                 numbered_equations=numbered)


def audit(parts: Parts, rules: Rules = HOUSE) -> list[str]:
    """Every departure from the house typography, as sentences.

    Read-only; empty means conformant. None of these fails lint, a text
    diff or `compare` — every one is valid markup — so without this the
    only detector is the author opening the file, which is how HCW's
    five rules reached them one at a time.
    """
    xml = parts[DOCUMENT].decode("utf-8")
    styles = parts.get("word/styles.xml")
    cascade = Cascade(styles.decode("utf-8") if styles else None)
    themes = _theme_fonts(parts)
    cap_re = caption_re()
    out: list[str] = []
    paras = list(PARA_RE.finditer(xml))
    in_block = _span_notes(xml)
    for i, m in enumerate(paras):
        para = m.group(0)
        text = visible_text(para).strip()
        pstyle = Cascade.paragraph_style(para)
        ppr = own_properties(para, "pPr")
        inner = live_properties(ppr[2]) if ppr else None
        if cap_re.match(text):
            what = f"caption {text[:30]!r}"
            out += _face_findings(para, rules.caption, cascade,
                                  pstyle=pstyle, what=what, themes=themes)
            out += _para_findings(para, cascade, pstyle, what,
                                  rules.caption_after)
            keep = cascade.para_element("keepNext", ppr=inner, pstyle=pstyle)
            if keep is None or re.search(r'w:val="(?:0|false|off)"', keep):
                out.append(f"{what}: no keepNext — it can be left alone "
                           f"at the foot of a page")
            if (_keep_number_face(para) != para
                    and not _style_gives(cascade, pstyle, rules.caption,
                                         themes)):
                out.append(f"{what}: its number is a field without "
                           r"\* MERGEFORMAT — Word's next field update "
                           f"redraws it in the caption style")
        elif NOTE.match(text) or m.start() in in_block:
            what = f"note {text[:30]!r}"
            out += _face_findings(para, rules.note, cascade,
                                  pstyle=pstyle, what=what, themes=themes)
            out += _para_findings(para, cascade, pstyle, what,
                                  rules.note_after)
            if i and _PICTURE_RE.search(paras[i - 1].group(0)):
                left = cascade.para_attr("ind", "left", ppr=inner,
                                         pstyle=pstyle)
                right = cascade.para_attr("ind", "right", ppr=inner,
                                          pstyle=pstyle)
                want = str(rules.figure_note_indent)
                if (left, right) != (want, want):
                    out.append(f"{what}: under a figure, not indented "
                               f"{rules.figure_note_indent / 1440:g}\" "
                               f"both sides")
    tables = element_spans(xml, "tbl")
    for m in display_equations(xml):
        if any(lo <= m.start() < hi for lo, hi in tables):
            continue
        prose = visible_text(OMATH_RE.sub("", m.group(0))).strip()
        number = EQ_NUMBER_RE.search(prose)
        if rules.number_equations and number is not None:
            out.append(f"equation {number.group(0)} "
                       f"carries its number in its own paragraph — Word "
                       f"demotes that display to inline on save")
    if rules.equation_lead_after is not None:
        lead_after = rules.equation_lead_after
        for m in _lead_ins(xml):
            para = m.group(0)
            ppr = own_properties(para, "pPr")
            inner = live_properties(ppr[2]) if ppr else None
            pstyle = Cascade.paragraph_style(para)
            got = cascade.para_attr("spacing", "after", ppr=inner,
                                    pstyle=pstyle)
            lines = cascade.para_attr("spacing", "afterLines", ppr=inner,
                                      pstyle=pstyle)
            if (got or "0") != str(lead_after) or lines not in (None, "0"):
                shown = (f"{int(lines) / 100:g} lines" if lines not in
                         (None, "0") else f"{int(got or 0) / 20:g} pt")
                text = visible_text(para).strip()
                out.append(f"equation lead-in {text[:30]!r}: {shown} "
                           f"after, not {lead_after / 20:g} pt")
    return out
