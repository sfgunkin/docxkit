r"""Rendering a manuscript as markdown, structure intact.

``docxkit text`` gives a flat text dump; this keeps what the flat dump
throws away — heading levels, tables as tables, equations as LaTeX,
footnotes as footnotes — so a manuscript can be read, diffed in git, or
loaded whole into an LLM context without opening Word.

Reading-oriented, like :func:`docxkit.equations.to_latex` underneath it:
an equation construct with no rendering shows an inline marker rather
than disappearing, and character formatting (bold, italics) is
deliberately not reproduced — in these manuscripts it is house styling,
not meaning, and half-faithful emphasis is worse than none.
"""
from __future__ import annotations

import re

from ._xml import DOCUMENT, FOOTNOTES, visible_text
from .crossrefs import DEFAULT_LABELS, caption_re
from .equations import EQ_NUMBER_RE, OMATH_RE, is_display, to_latex
from .find import body_elements, heading_level
from .footnotes import find_all as _footnotes
from .revisions import FINAL, view_transform
from .tables import read_all as _read_tables

__all__ = ["to_markdown"]

_FOOTNOTE_REF_RE = re.compile(
    r'<w:footnoteReference\b[^>]*w:id="(-?\d+)"[^>]*/>')
# the shared caption definition, plus the abbreviated form
_CAPTION_RE = caption_re((*DEFAULT_LABELS, "Fig."))
_MARKER = "\x00"


def _inline(para_xml: str) -> str:
    """Paragraph text with math as ``$...$`` and footnote markers kept.

    The substitutions ride through ``visible_text`` inside placeholder
    ``w:t`` elements, which is what keeps every piece at its right spot
    in the sentence — post-hoc concatenation loses the interleaving.
    """
    maths = [to_latex(m.group(0)) for m in OMATH_RE.finditer(para_xml)]
    xml = OMATH_RE.sub(f"<w:r><w:t>{_MARKER}</w:t></w:r>", para_xml)
    xml = _FOOTNOTE_REF_RE.sub(
        lambda m: f"<w:r><w:t>[^{m.group(1)}]</w:t></w:r>", xml)
    text = visible_text(xml)
    for latex in maths:
        text = text.replace(_MARKER, f"${latex}$", 1)
    return " ".join(text.split())


def _display(para_xml: str) -> str:
    maths = [to_latex(m.group(0)) for m in OMATH_RE.finditer(para_xml)]
    prose = visible_text(OMATH_RE.sub("", para_xml))
    body = " ".join(maths)
    if (num := EQ_NUMBER_RE.search(prose)) is not None:
        body += rf" \tag{{{num.group(1)}}}"
    return f"$$ {body} $$"


def _pipe_table(tbl_xml: str) -> str:
    # the fragment was already transformed to the requested view, so the
    # re-read inside read_all is a no-op pass over a clean table
    found = _read_tables(tbl_xml)
    if not found:
        return ""
    rows = [[cell.replace("|", r"\|") for cell in row]
            for row in found[0].rows]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "---|" * width]
    out += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(out)


def to_markdown(parts: dict[str, bytes], *, view: str = FINAL) -> str:
    """The manuscript as GitHub-flavoured markdown, in body order.

    `view` picks the side of any tracked changes. Headings map from
    ``outlineLvl`` (or the Heading-N style), tables become pipe tables,
    display equations ``$$...$$`` with their number as a ``\\tag``,
    inline math ``$...$`` in place, and footnotes ``[^id]`` markers with
    the definitions at the end.
    """
    transform = view_transform(view)
    xml = transform(parts[DOCUMENT].decode("utf-8"))

    blocks: list[str] = []
    for kind, start, end in body_elements(xml):
        frag = xml[start:end]
        if kind == "tbl":
            blocks.append(_pipe_table(frag))
            continue
        text = visible_text(frag).strip()
        if not text:
            continue
        if (level := heading_level(frag)) is not None:
            blocks.append("#" * level + " " + _inline(frag))
        elif is_display(frag):
            blocks.append(_display(frag))
        elif _CAPTION_RE.match(text):
            blocks.append(f"**{_inline(frag)}**")
        else:
            blocks.append(_inline(frag))

    if FOOTNOTES in parts:
        notes_xml = transform(parts[FOOTNOTES].decode("utf-8"))
        notes = [f"[^{f.id}]: {' '.join(f.text.split())}"
                 for f in _footnotes(notes_xml) if f.text]
        if notes:
            blocks.append("\n".join(notes))
    return "\n\n".join(b for b in blocks if b) + "\n"
