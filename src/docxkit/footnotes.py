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

from ._xml import PARA_RE, escape, visible_text
from .errors import AnchorError

__all__ = ["Footnote", "append", "find", "find_all", "remap", "renumber_map"]

_FOOTNOTE_RE = re.compile(r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)'
                          r"</w:footnote>", re.DOTALL)
_REFERENCE_RE = re.compile(r'(w:footnoteReference w:id=")(-?\d+)(")')
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

