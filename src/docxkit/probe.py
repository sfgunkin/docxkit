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

from ._xml import (
    BOOKMARK_NAME_RE,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    INSTR_ANCHOR_RE,
    INSTR_RE,
    PARA_RE,
    SECTPR_RE,
    T_RE,
    editable_text,
    element_spans,
    matching_close,
    visible_text,
)
from .package import read_parts

__all__ = ["Probe", "probe"]

# Everything above the next line is the SHARED definition. This module
# had its own copy of the paragraph, the text node, the instruction, the
# bookmark name and the section properties — five of them, one of which
# was called `_FIELD_RE` while `_xml._FIELD_RE` means the whole field,
# and one of which (`<w:p\b.*?</w:p>`) is the unsafe spelling: after a
# self-closing `<w:p/>` it runs on to the NEXT paragraph's close tag and
# reports the two as one.
_EL_LINK_RE = re.compile(r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>')
_PGSZ_RE = re.compile(r'<w:pgSz[^>]*w:orient="([^"]+)"')
_CAPTION_RE = re.compile(
    r"^\s*((?:Table|Figure|Таблица|Рисунок)\s+[A-Z]?\d+)\s*[:.]")
#: a paragraph OR a table, in document order, on the shared spelling of
#: a paragraph — the two walks below have to agree about where one ends.
#: The table half carries the paragraph's `(?<!/)>` guard too: an empty
#: `<w:tbl/>` read as an open tag ran on to the next table's close and
#: took the caption between into a block that is never read as one.
_BLOCK_RE = re.compile(
    rf"{PARA_RE.pattern}|(?P<table><w:tbl\b[^>]*(?<!/)>).*?</w:tbl>",
    re.DOTALL)


def _blocks(doc: str) -> list[str]:
    """`_BLOCK_RE`'s blocks, each table WHOLE.

    Its table half closes on the first `</w:tbl>` it meets, which for a
    table holding another is the NESTED one's: the exhibit's block ended
    inside its own cell, its rows were counted with the nested table's,
    and the rest of it was walked as paragraphs (3 captioned tables in 3
    of 2,954 corpus packages, 2026-09-17).
    """
    out: list[str] = []
    pos = 0
    while (m := _BLOCK_RE.search(doc, pos)) is not None:
        end = (m.end() if m.group("table") is None
               else matching_close(doc, m.end("table"), "tbl"))
        out.append(doc[m.start():end])
        pos = end
    return out


@dataclass
class Probe:
    """What a batch needs to know before it picks an approach."""

    path: Path
    element_links: dict[str, int] = field(default_factory=dict)
    field_links: dict[str, int] = field(default_factory=dict)
    exhibits: list[tuple[str, str, str]] = field(default_factory=list)
    bookmarks: list[tuple[str, str]] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    #: each PHRASE asked about -> the paragraphs holding it and how its
    #: runs are split. Not "anchors": everywhere else in this toolkit an
    #: anchor is a bookmark NAME, and this report prints both senses —
    #: `docxkit locate prev.docx cite_kakwani_1977` answered NOT FOUND,
    #: confidently, for a bookmark that is in the file (2026-08-21).
    phrases: dict[str, list[tuple[int, list[str]]]] = field(
        default_factory=dict)

    @property
    def anchors(self) -> dict[str, list[tuple[int, list[str]]]]:
        """The old name for :attr:`phrases`. Same reason as `probe`'s."""
        return self.phrases

    #: phrases the two definitions of "what this paragraph says" disagree
    #: about, as (what `find` sees, what `edit` sees). They are both in
    #: this package and they differ over OMML: `visible_text` reads
    #: `w:t` AND `m:t`, while `edit.replace_in_para` walks `w:r` runs,
    #: and math lives in `m:r` — so a phrase spanning an equation is
    #: findable by one and invisible to the other. Probe exists to be
    #: asked BEFORE choosing an approach, so it reports the split rather
    #: than picking a side.
    view_split: dict[str, tuple[list[int], list[int]]] = field(
        default_factory=dict)

    @property
    def link_form(self) -> str:
        el = sum(self.element_links.values())
        fld = sum(self.field_links.values())
        if el and fld:
            return f"MIXED ({el} element, {fld} field)"
        if fld:
            return f"FIELD ({fld}) — crossrefs.unlink/link CANNOT see these"
        return f"element ({el})" if el else "none"

    def report(self) -> str:
        out = [f"{self.path.name}", f"  link form   {self.link_form}"]
        if self.field_links:
            out.append("  field-form anchors (bookmark names): "
                       + ", ".join(sorted(self.field_links)[:12]))
        out.append(f"  sections    {' -> '.join(self.sections) or 'one'}")
        body_level = sum(1 for _, w in self.bookmarks if w == "body")
        out.append(f"  bookmarks   {len(self.bookmarks)}"
                   f" ({body_level} body-level)")
        if self.exhibits:
            out.append("  exhibits")
            for label, follows, orient in self.exhibits:
                tail = f"  [{orient}]" if orient else ""
                out.append(f"    {label:12s} {follows}{tail}")
        for text, hits in self.phrases.items():
            out.append(f"  phrase {text!r}")
            if not hits:
                out.append("    NOT FOUND")
            for idx, runs in hits:
                out.append(f"    para {idx}: {runs}")
            if text in self.view_split:
                seen, editable = self.view_split[text]
                out.append(f"    ** the two views disagree: find/para_slice "
                           f"{seen or 'nothing'}, edit/replace_in_para "
                           f"{editable or 'nothing'} — a phrase spanning an "
                           f"equation is visible to one and not the other, "
                           f"and replace_in_para writes across the maths "
                           f"in neither spelling: anchor beside it")
        return "\n".join(out)


def probe(path: str | Path, phrases: tuple[str, ...] = (), *,
          anchors: tuple[str, ...] | None = None,
          parts: dict[str, bytes] | None = None) -> Probe:
    """Characterise `path`; `phrases` are the ones to show run splits for.

    Called PHRASES, not anchors: this module reports bookmark names too,
    and the two senses met in one report (see :attr:`Probe.phrases`).

    ``anchors=`` is the old spelling, kept because docxkit is the shared
    toolkit every paper imports and the CLI kept `--anchors-from` for
    exactly this rename — a paper script should not break on one half of
    a change that was careful about the other.

    `parts` is a package the caller has already read — the CLI's
    snapshot, when Word holds the file. Reading `path` again regardless
    is what made this refuse an author round under a printed snapshot
    banner, the same defect `citations` carried; `path` stays what the
    report NAMES.
    """
    if anchors is not None:
        phrases = tuple(anchors) + tuple(phrases)
    path = Path(path)
    if parts is None:
        parts = read_parts(path)
    rep = Probe(path=path)

    for name in (DOCUMENT, FOOTNOTES, ENDNOTES):
        if name not in parts:
            continue
        xml = parts[name].decode("utf-8")
        for anchor in _EL_LINK_RE.findall(xml):
            rep.element_links[anchor] = rep.element_links.get(anchor, 0) + 1
        for instr in INSTR_RE.findall(xml):
            m = INSTR_ANCHOR_RE.search(instr)
            if m:
                at = m.group(1)
                rep.field_links[at] = rep.field_links.get(at, 0) + 1

    doc = parts[DOCUMENT].decode("utf-8")

    # bookmarks, and whether they sit between paragraphs (body-level) --
    # a block move has to carry those, and they are invisible to a
    # paragraph-oriented edit
    # The body's open tag in any spelling. Found as the exact string
    # `<w:body>`, `find` answered -1 for `<w:body >`, and the slice from
    # -1 is the document's last character: no bookmark was reported.
    opened = re.search(r"<w:body\b[^>]*(?<!/)>", doc)
    body = doc[opened.start():] if opened else ""
    for m in BOOKMARK_NAME_RE.finditer(body):
        before = body.rfind("<w:p", 0, m.start())
        closed = body.rfind("</w:p>", 0, m.start())
        # `>=`, not `>`: the two are equal only when both are -1, which
        # is a bookmark that precedes every paragraph in the body — a
        # sibling of them, with no paragraph to travel with. Reported as
        # "nested" it reads as one a paragraph-oriented edit carries for
        # free, and a block move then drops it. (`</w:p>` does not
        # contain `<w:p`, so the two searches cannot otherwise agree.)
        where = "body" if closed >= before else "nested"
        rep.bookmarks.append((m.group(1), where))

    for sect in SECTPR_RE.findall(doc):
        o = _PGSZ_RE.search(sect)
        rep.sections.append(o.group(1) if o else "portrait")

    # exhibit captions, what follows them, and the section they close
    blocks = _blocks(doc)
    for i, blk in enumerate(blocks):
        if blk.startswith("<w:tbl"):
            continue
        cap = _CAPTION_RE.match(visible_text(blk))
        if not cap:
            continue
        follows = "(no table follows)"
        for nxt in blocks[i + 1:i + 3]:
            if nxt.startswith("<w:tbl"):
                follows = f"table, {len(element_spans(nxt, 'tr'))} rows"
                break
        orient = ""
        for nxt in blocks[i:i + 8]:
            s = SECTPR_RE.search(nxt)
            if s:
                o = _PGSZ_RE.search(s.group(0))
                orient = o.group(1) if o else "portrait"
                break
        rep.exhibits.append((cap.group(1), follows, orient))

    paras = [m.group(0) for m in PARA_RE.finditer(doc)]
    for text in phrases:
        hits = [(i, T_RE.findall(para)[:10])
                for i, para in enumerate(paras)
                if text in visible_text(para)]
        rep.phrases[text] = hits
        # …and the same question asked the way `edit` asks it. Measured
        # over 399 real manuscripts, the two answers differ on 256 of
        # them, and every difference is an equation: DSI's methodology
        # paragraph reads "где DRID, DRIS, DRIH обозначают…" to `find`
        # (the subindex names are math-italic letters in OMML) and
        # "где , ,  обозначают…" to `replace_in_para`, which walks w:r
        # runs and cannot see an m:r.
        editable = [i for i, para in enumerate(paras)
                    if text in editable_text(para)]
        if [i for i, _ in hits] != editable:
            rep.view_split[text] = ([i for i, _ in hits], editable)
    return rep
