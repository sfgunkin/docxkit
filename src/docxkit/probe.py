"""One call that answers the questions a batch has to know first.

Written after a two-table swap took forty minutes, most of it spent
rediscovering four facts about the manuscript that no audit reports:
which FORM its links take, where the exhibit blocks and section breaks
sit, which bookmarks exist and whether they are body-level, and how a
phrase is split across runs. Each was a throwaway script; together they
were most of the wasted time.

The link form is the expensive one. ``crossrefs.unlink``/``link`` only
understand element-form ``<w:hyperlink>``. A manuscript whose links are
Word FIELD form (``HYPERLINK \\l "X" \\h`` in instrText) takes the
teardown-and-rebuild route silently: unlink reports a healthy number of
bookmarks removed and leaves every link standing. Knowing the form
before choosing the approach is the difference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ._xml import DOCUMENT, ENDNOTES, FOOTNOTES
from .package import read_parts

__all__ = ["Probe", "probe"]

_P_RE = re.compile(r"<w:p\b.*?</w:p>", re.DOTALL)
_T_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
_EL_LINK_RE = re.compile(r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>')
_FIELD_RE = re.compile(r"<w:instrText[^>]*>([^<]*)</w:instrText>")
_BM_RE = re.compile(r'<w:bookmarkStart[^>]*w:name="([^"]+)"')
_TR_RE = re.compile(r"<w:tr\b")
_SECT_RE = re.compile(r"<w:sectPr\b.*?</w:sectPr>", re.DOTALL)
_PGSZ_RE = re.compile(r'<w:pgSz[^>]*w:orient="([^"]+)"')
_CAPTION_RE = re.compile(r"^\s*((?:Table|Figure|Таблица|Рисунок)\s+[A-Z]?\d+)\s*[:.]")


def _visible(para: str) -> str:
    return "".join(_T_RE.findall(para))


@dataclass
class Probe:
    """What a batch needs to know before it picks an approach."""

    path: Path
    element_links: dict[str, int] = field(default_factory=dict)
    field_links: dict[str, int] = field(default_factory=dict)
    exhibits: list[tuple[str, str, str]] = field(default_factory=list)
    bookmarks: list[tuple[str, str]] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    anchors: dict[str, list[tuple[int, list[str]]]] = field(default_factory=dict)

    @property
    def link_form(self) -> str:
        el, fld = sum(self.element_links.values()), sum(self.field_links.values())
        if el and fld:
            return f"MIXED ({el} element, {fld} field)"
        if fld:
            return f"FIELD ({fld}) — crossrefs.unlink/link CANNOT see these"
        return f"element ({el})" if el else "none"

    def report(self) -> str:
        out = [f"{self.path.name}", f"  link form   {self.link_form}"]
        if self.field_links:
            out.append("  field-form anchors: "
                       + ", ".join(sorted(self.field_links)[:12]))
        out.append(f"  sections    {' -> '.join(self.sections) or 'one'}")
        out.append(f"  bookmarks   {len(self.bookmarks)}"
                   f" ({sum(1 for _, w in self.bookmarks if w == 'body')} body-level)")
        if self.exhibits:
            out.append("  exhibits")
            for label, follows, orient in self.exhibits:
                tail = f"  [{orient}]" if orient else ""
                out.append(f"    {label:12s} {follows}{tail}")
        for text, hits in self.anchors.items():
            out.append(f"  anchor {text!r}")
            if not hits:
                out.append("    NOT FOUND")
            for idx, runs in hits:
                out.append(f"    para {idx}: {runs}")
        return "\n".join(out)


def probe(path: str | Path, anchors: tuple[str, ...] = ()) -> Probe:
    """Characterise `path`; `anchors` are phrases to show run splits for."""
    path = Path(path)
    parts = read_parts(path)
    rep = Probe(path=path)

    for name in (DOCUMENT, FOOTNOTES, ENDNOTES):
        if name not in parts:
            continue
        xml = parts[name].decode("utf-8")
        for anchor in _EL_LINK_RE.findall(xml):
            rep.element_links[anchor] = rep.element_links.get(anchor, 0) + 1
        for instr in _FIELD_RE.findall(xml):
            m = re.search(r'HYPERLINK\s+\\l\s+"([^"]+)"', instr)
            if m:
                rep.field_links[m.group(1)] = rep.field_links.get(m.group(1), 0) + 1

    doc = parts[DOCUMENT].decode("utf-8")

    # bookmarks, and whether they sit between paragraphs (body-level) --
    # a block move has to carry those, and they are invisible to a
    # paragraph-oriented edit
    body = doc[doc.find("<w:body>"):]
    for m in _BM_RE.finditer(body):
        before = body.rfind("<w:p", 0, m.start())
        closed = body.rfind("</w:p>", 0, m.start())
        rep.bookmarks.append((m.group(1), "body" if closed > before else "nested"))

    for sect in _SECT_RE.findall(doc):
        o = _PGSZ_RE.search(sect)
        rep.sections.append(o.group(1) if o else "portrait")

    # exhibit captions, what follows them, and the section they close
    blocks = re.findall(r"<w:p\b.*?</w:p>|<w:tbl\b.*?</w:tbl>", doc, re.DOTALL)
    for i, blk in enumerate(blocks):
        if blk.startswith("<w:tbl"):
            continue
        cap = _CAPTION_RE.match(_visible(blk))
        if not cap:
            continue
        follows = "(no table follows)"
        for nxt in blocks[i + 1:i + 3]:
            if nxt.startswith("<w:tbl"):
                follows = f"table, {len(_TR_RE.findall(nxt))} rows"
                break
        orient = ""
        for nxt in blocks[i:i + 8]:
            s = _SECT_RE.search(nxt)
            if s:
                o = _PGSZ_RE.search(s.group(0))
                orient = o.group(1) if o else "portrait"
                break
        rep.exhibits.append((cap.group(1), follows, orient))

    paras = _P_RE.findall(doc)
    for text in anchors:
        hits = []
        for i, para in enumerate(paras):
            if text in _visible(para):
                hits.append((i, _T_RE.findall(para)[:10]))
        rep.anchors[text] = hits
    return rep
