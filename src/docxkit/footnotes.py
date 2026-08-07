r"""Footnotes: locating them, editing them, and surviving Word's renumbering.

Twenty-four files across the papers touch footnotes. Two things make it
awkward, and both are encoded here:

* **Word renumbers footnote ids on save.** An author's paragraph spliced
  raw carries ids that mean a different note in the build, so a splice
  silently repoints the reference. :func:`remap` matches by definition
  TEXT instead.
* **A footnote is a block container.** Its content lives in ``w:p``
  children; putting a run directly inside ``w:footnote`` makes Word
  reject the part — which is why :mod:`docxkit.lint` checks for it.

Ids 0 and -1 are the separator and continuation notes Word keeps in every
document, not real footnotes; :func:`find_all` skips them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ._xml import (
    PARA_RE,
    RUN_RE,
    escape,
    escape_attr,
    live_properties,
    own_properties,
    set_run_property,
    visible_text,
)
from .errors import AnchorError

__all__ = [
    "FontReport",
    "Footnote",
    "append",
    "find",
    "find_all",
    "fonts",
    "remap",
    "renumber_map",
    "set_font",
]

_FOOTNOTE_RE = re.compile(r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)'
                          r"</w:footnote>", re.DOTALL)
_REFERENCE_RE = re.compile(r'(w:footnoteReference\b[^>]*?w:id=")(-?\d+)(")')
# Word's own separator/continuation notes, present in every document
_RESERVED_IDS = {"0", "-1"}


class Footnote:
    """One footnote: its id, its text, and where it sits in the part."""

    __slots__ = ("end", "id", "start", "text", "xml")

    def __init__(self, id: str, xml: str, start: int, end: int) -> None:
        self.id = id
        self.xml = xml
        self.start = start
        self.end = end
        self.text = visible_text(xml).strip()

    def __repr__(self) -> str:
        return f"Footnote(id={self.id!r}, text={self.text[:40]!r})"


def find_all(footnotes_xml: str, *, include_reserved: bool = False
             ) -> list[Footnote]:
    """Every real footnote, Word's separator notes excluded."""
    out = []
    for m in _FOOTNOTE_RE.finditer(footnotes_xml):
        if not include_reserved and m.group(1) in _RESERVED_IDS:
            continue
        out.append(Footnote(m.group(1), m.group(0), m.start(), m.end()))
    return out


def find(footnotes_xml: str, contains: str) -> Footnote:
    """The single footnote whose text contains `contains`."""
    hits = [f for f in find_all(footnotes_xml) if contains in f.text]
    if len(hits) != 1:
        raise AnchorError(
            f"footnote containing {contains!r}: {len(hits)} hits, need 1")
    return hits[0]


def append(footnotes_xml: str, contains: str, text: str) -> str:
    """Append `text` to the end of a footnote's last paragraph.

    Adds a run inside the existing ``w:p`` rather than after it: a run
    placed directly in ``w:footnote`` is what makes Word reject the part.
    """
    note = find(footnotes_xml, contains)
    paras = list(PARA_RE.finditer(note.xml))
    if not paras:
        raise AnchorError(f"footnote {note.id} has no paragraph to append to")
    last = paras[-1]
    run = f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
    patched = (note.xml[:last.end() - len("</w:p>")] + run
               + note.xml[last.end() - len("</w:p>"):])
    return (footnotes_xml[:note.start] + patched
            + footnotes_xml[note.end:])


def renumber_map(source_xml: str, target_xml: str) -> dict[str, str]:
    """Footnote id in `source_xml` -> the id of the same note in `target_xml`.

    Matched on definition text, because the ids themselves are not
    stable: Word renumbers them on save.
    """
    target = {f.text: f.id for f in find_all(target_xml) if f.text}
    return {f.id: target[f.text] for f in find_all(source_xml)
            if f.text in target}


def remap(xml: str, mapping: dict[str, str]) -> str:
    """Rewrite every ``w:footnoteReference`` id through `mapping`.

    Apply to a paragraph taken from another document before splicing it
    in, or its footnote markers will point at whatever note happens to
    hold that id here.
    """
    return _REFERENCE_RE.sub(
        lambda m: m.group(1) + mapping.get(m.group(2), m.group(2))
        + m.group(3), xml)


# --------------------------------------------------------------- the font
# "Footnotes are Times New Roman 10" is a house rule, and the house is the
# PAPER's — so the size and the face are arguments. They are also the
# defaults, because that is the rule every manuscript here has asked for.
#
# This writes DIRECT run formatting rather than editing the FootnoteText
# style. The style is the tidier XML and the less reliable outcome: it
# only reaches a run if styles.xml actually defines FootnoteText AND the
# footnote's paragraph carries a pStyle referencing it, and manuscripts
# that satisfy neither are ordinary. Direct formatting is what wins in
# Word, which is the only test that counts.

_MATH_RE = re.compile(r"<m:oMath\b.*?</m:oMath>", re.DOTALL)
_RFONTS_RE = re.compile(r"<w:rFonts\b[^>]*?/>")
# `[^>]*` before w:val, not `<w:sz w:val=`: XML attribute order carries no
# meaning, and patterns here that hard-coded Word's habitual order have
# silently matched nothing on a conforming document before.
_SZ_RE = re.compile(r'<w:sz\b[^>]*w:val="(\d+)"[^>]*/>')
_ASCII_RE = re.compile(r'w:ascii="([^"]*)"')


@dataclass
class FontReport:
    """What :func:`set_font` changed, and what it deliberately did not."""

    notes: int = 0
    runs_set: int = 0
    math_runs_skipped: int = 0

    def format(self) -> str:
        out = [f"{self.runs_set} run(s) in {self.notes} footnote(s) set"]
        if self.math_runs_skipped:
            out.append(f"  {self.math_runs_skipped} equation run(s) left "
                       "alone (Cambria Math is not interchangeable with a "
                       "text face)")
        return "\n".join(out)


def _half_points(size: float) -> int:
    """Word stores a point size doubled: 10pt is ``w:val="20"``.

    Half-point steps are the finest Word records, so 10.5 is expressible
    and 10.3 is not — rounding here rather than truncating keeps the
    error under a quarter point instead of losing a half.
    """
    return round(size * 2)


def _math_spans(xml: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _MATH_RE.finditer(xml)]


def set_font(footnotes_xml: str, *, name: str = "Times New Roman",
             size: float = 10, include_reserved: bool = False,
             ) -> tuple[str, FontReport]:
    """Set the face and size of every run in every real footnote.

    An equation's runs keep their face. A footnote carrying OMML holds
    runs declared in Cambria Math, and the text faces do not have those
    glyphs — rewriting them to the body font is how an equation turns
    into boxes.

    Two things prevent it, and both are deliberate. OMML's own runs are
    ``m:r``, which ``RUN_RE`` does not match at all; and a ``w:r`` that
    sits inside an ``m:oMath`` — legal, and how Word writes literal text
    in a formula — is skipped explicitly and COUNTED, so "some runs were
    left" is visible rather than inferred from a total that looks low.

    Measured over the 1,940 footnote parts on this machine: 495 contain
    OMML and none of them put a ``w:r`` inside it, so the explicit skip
    never fired and the ``m:r`` rule did all the work. Keep both. The
    day someone widens the run pattern to reach math runs, the skip is
    the only thing standing between a formula and the body font.

    Word's separator and continuation notes (ids 0 and -1) are not
    footnotes and are left alone unless `include_reserved`.
    """
    sz = _half_points(size)
    face = escape_attr(name)
    rfonts = (f'<w:rFonts w:ascii="{face}" w:hAnsi="{face}" w:cs="{face}"/>')
    report = FontReport()

    out: list[str] = []
    cursor = 0
    for note in find_all(footnotes_xml, include_reserved=include_reserved):
        out.append(footnotes_xml[cursor:note.start])
        cursor = note.end
        report.notes += 1

        math = _math_spans(note.xml)
        pieces: list[str] = []
        at = 0
        for m in RUN_RE.finditer(note.xml):
            if any(s <= m.start() < e for s, e in math):
                report.math_runs_skipped += 1
                continue
            fixed = set_run_property(m.group(0), "rFonts", rfonts)
            fixed = set_run_property(fixed, "sz", f'<w:sz w:val="{sz}"/>')
            fixed = set_run_property(fixed, "szCs", f'<w:szCs w:val="{sz}"/>')
            pieces.append(note.xml[at:m.start()])
            pieces.append(fixed)
            at = m.end()
            report.runs_set += 1
        pieces.append(note.xml[at:])
        out.append("".join(pieces))

    out.append(footnotes_xml[cursor:])
    return "".join(out), report


def _run_font(run_xml: str) -> tuple[str | None, int | None]:
    """The face and half-point size this run carries ITSELF.

    ``None`` means the run states nothing and inherits — which is not
    the same claim as "conforms", and reporting it as the latter would
    be a guess about styles.xml, a part this module is never given.
    """
    own = own_properties(run_xml, "rPr")
    if own is None:
        return None, None
    live = live_properties(own[2])
    face = None
    if (m := _RFONTS_RE.search(live)) and (a := _ASCII_RE.search(m.group(0))):
        face = a.group(1)
    sz = int(s.group(1)) if (s := _SZ_RE.search(live)) else None
    return face, sz


def fonts(footnotes_xml: str, *, include_reserved: bool = False
          ) -> dict[str, int]:
    """Every distinct face/size a footnote run states, with run counts.

    The question "are the footnotes Times New Roman 10?" asked of a file
    rather than imposed on it. A run that states nothing is reported as
    ``"inherited"`` and never folded into a face it might well render
    as: the answer lives in styles.xml and docDefaults, and claiming it
    from here would be a guess.
    """
    seen: dict[str, int] = {}
    for note in find_all(footnotes_xml, include_reserved=include_reserved):
        math = _math_spans(note.xml)
        for m in RUN_RE.finditer(note.xml):
            if any(s <= m.start() < e for s, e in math):
                continue
            face, sz = _run_font(m.group(0))
            if face is None and sz is None:
                key = "inherited"
            else:
                pts = "inherited" if sz is None else f"{sz / 2:g}pt"
                key = f"{face or 'inherited face'} {pts}"
            seen[key] = seen.get(key, 0) + 1
    return seen

