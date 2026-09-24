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

import re
from dataclasses import dataclass

from ._xml import (
    DOCUMENT,
    PARA_RE,
    RUN_RE,
    Parts,
    element_spans,
    live_properties,
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
#: paragraph in a document that happens to open that way.
NOTE = re.compile(r"^\s*(?:Notes?|Sources?|Примечани[ея]|Источник[иа]?)\s*:",
                  re.IGNORECASE)
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

    def format(self) -> str:
        return (f"captions {self.captions}, notes {self.notes} "
                f"({self.figure_notes} under a figure), runs restyled "
                f"{self.runs}, abstract {self.abstract or 'not found'}, "
                f"numbered equations set {self.equations}")


# ---------------------------------------------------------------- apply --


def _with_mark(para: str, face: Face) -> str:
    """The paragraph MARK given `face` — its size sets an empty line's."""
    ppr = own_properties(para, "pPr")
    mark = ""
    if ppr is not None:
        props = para[ppr[0]:ppr[1]]
        if (own := own_properties(props, "rPr")) is not None:
            mark = props[own[0]:own[1]]
    run = f"<w:r>{mark}</w:r>"
    for tag, element in face.props().items():
        run = set_run_property(run, tag, element)
    own = own_properties(run, "rPr")
    assert own is not None
    return set_para_property(para, "rPr", run[own[0]:own[1]])


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


def _styled(para: str, face: Face, after: int) -> tuple[str, int]:
    para, runs = set_run_properties(para, face.props())
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


def apply(parts: Parts, rules: Rules = HOUSE) -> HouseReport:
    """Set the house typography on the whole document. Edits `parts`.

    Idempotent: a second call writes the same XML and, since the counts
    are of paragraphs the rules APPLY to, reports the same numbers.
    """
    xml = parts[DOCUMENT].decode("utf-8")
    captions = notes = figure_notes = runs = 0
    cap_re = caption_re()
    paras = list(PARA_RE.finditer(xml))
    for i in range(len(paras) - 1, -1, -1):
        m = paras[i]
        text = visible_text(m.group(0)).strip()
        if cap_re.match(text):
            para, n = _styled(m.group(0), rules.caption, rules.caption_after)
            para = set_para_property(para, "keepNext", "<w:keepNext/>")
            captions += 1
        elif NOTE.match(text):
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
    parts[DOCUMENT] = xml.encode("utf-8")
    return HouseReport(captions=captions, notes=notes,
                       figure_notes=figure_notes, runs=runs,
                       abstract=abstract, equations=equations)


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
    texts = [visible_text(m.group(0)).strip() for m in PARA_RE.finditer(xml)]
    numbered = sum(
        1 for m in display_equations(xml)
        if EQ_NUMBER_RE.search(visible_text(OMATH_RE.sub("", m.group(0))))
        or any(lo <= m.start() < hi for lo, hi in element_spans(xml, "tbl")))
    return Scope(captions=sum(1 for t in texts if cap_re.match(t)),
                 notes=sum(1 for t in texts if NOTE.match(t)),
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
        elif NOTE.match(text):
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
    return out
