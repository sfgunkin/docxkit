r"""Constructing body content: runs, paragraphs, tables.

Everything else in docxkit reads or edits a document that already exists.
This module is the other direction — a revision that ADDS an exhibit has to
emit WordprocessingML from nothing, and every paper had been hand-rolling
it: the AFI r2 round wrote ~90 lines of ``tblPr`` / ``tcPr`` / ``gridSpan``
/ ``tblGrid`` constants inline in its build script to add two appendix
tables, and the next paper to add one would have written them again.

The XML here is deliberately plain. It carries structure and the
``TableGrid`` style, not house formatting: papers differ on borders, fonts
and caption styles, and a toolkit that guessed would be wrong for most of
them. Style the result by passing ``ppr``/``rpr``/``tblpr``, or by cloning
those fragments off an existing paragraph in the document — which is the
reliable way to match a manuscript's own look.

    from docxkit.body import para, run, table, insert_after

    caption = para(run("Table A3. Cutoff sensitivity"), ppr=caption_ppr)
    tbl = table(["Country", "50+", "60+"], [["Albania", "-0.6", "+1.7"]])
    xml = insert_after(xml, "the paragraph this follows", caption + tbl)

Text is escaped, and a run whose text has edge whitespace gets
``xml:space="preserve"`` — bare ``<w:t> x</w:t>`` loses that space on every
Word save and comes back as a phantom author edit each round.
"""
from __future__ import annotations

import re

from ._xml import (
    HYPERLINK_ANY_RE,
    RUN_RE,
    escape,
    field_spans,
    own_properties,
    visible_text,
)
from .errors import AnchorError
from .find import para_slice

__all__ = [
    "DEFAULT_TBLPR",
    "AnchorError",
    "cell",
    "insert_after",
    "insert_before",
    "para",
    "prose_props",
    "row",
    "run",
    "table",
    "visible_text",
]

#: The character style Word puts on a link label. A run carrying
#: it is a label even where no `w:hyperlink` element encloses it,
#: which is the field form.
_HYPERLINK_STYLE = 'w:val="Hyperlink"'

#: A plain bordered table. Papers that want their own look pass `tblpr`.
DEFAULT_TBLPR = (
    '<w:tblPr><w:tblStyle w:val="TableGrid"/>'
    '<w:tblW w:w="5000" w:type="pct"/>'
    '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1"'
    ' w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
)
_TOTAL_WIDTH = 9360          # a US-Letter text column in twips


def run(text: str, rpr: str = "") -> str:
    """One ``<w:r>`` carrying `text`.

    `rpr` is a ready-made ``<w:rPr>`` fragment (bold, size, font). Edge
    whitespace is preserved explicitly rather than left to Word.
    """
    edge = text[:1].isspace() or text[-1:].isspace()
    space = ' xml:space="preserve"' if edge else ""
    return f"<w:r>{rpr}<w:t{space}>{escape(text)}</w:t></w:r>"


def para(content: str = "", ppr: str = "") -> str:
    """One ``<w:p>`` wrapping already-built runs (or inline OMML).

    `content` is XML, not text — compose it with :func:`run`, or pass an
    ``<m:oMath>`` from :mod:`docxkit.equations` to place an equation.

    `ppr` may arrive wrapped or bare and is normalised either way. It
    was spliced in VERBATIM, and the pair this function is documented
    with — `para(run(text, rpr), ppr)` over :func:`prose_props` — handed
    back a bare pPr, so the obvious composition wrote
    ``<w:p><w:spacing/><w:jc/>…<w:r>``: a paragraph whose properties are
    bare children of ``w:p``. Word keeps the runs and DISCARDS the
    schema-invalid children silently, so Parental_style's supplement
    shipped a title block rendered left-aligned at 16pt (2026-09-01),
    found by rasterising the PDF. `lint` refuses that shape now and
    `prose_props` returns the wrapper; this accepts both spellings so a
    caller that already wraps is not punished for it.
    """
    if ppr and not ppr.lstrip().startswith("<w:pPr"):
        ppr = f"<w:pPr>{ppr}</w:pPr>"
    return f"<w:p>{ppr}{content}</w:p>"


def cell(content: str, *, span: int = 1, tcpr: str = "", rpr: str = "",
         ppr: str = "") -> str:
    """One ``<w:tc>``.

    `content` may be plain text or ready-made paragraph XML; text is
    wrapped in a paragraph, because a ``w:tc`` with no ``w:p`` makes Word
    declare the document unreadable.
    """
    # `<w:p` alone also matches <w:pPr, <w:pict and <w:proofErr, any of
    # which would be taken for a ready-made paragraph and left unwrapped
    # — landing a w:tc with no w:p, the exact "unreadable" failure above.
    # And ANY end to the name: `[ >]` took an empty `<w:p/>` for text.
    stripped = content.lstrip()
    body = (content if re.match(r"<w:p(?=[\s/>])", stripped)
            else para(run(content, rpr), ppr))
    props = tcpr or '<w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
    if span > 1:
        if "<w:tcPr>" not in props:
            raise AnchorError(
                "cell: span needs a tcPr to insert gridSpan into")
        props = props.replace(
            "<w:tcPr>", f'<w:tcPr><w:gridSpan w:val="{span}"/>', 1)
    return f"<w:tc>{props}{body}</w:tc>"


def row(cells: list[str], *, header: bool = False) -> str:
    """One ``<w:tr>`` from ready-made cells.

    `header` marks it as a repeating header row, so a table breaking across
    pages carries its headings onto each one.
    """
    props = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return f"<w:tr>{props}{''.join(cells)}</w:tr>"


def table(headers: list[str], rows: list[list[str]], *,
          spans: list[int] | None = None,
          extra_header: str = "",
          tblpr: str = DEFAULT_TBLPR,
          require_style: bool = True,
          header_rpr: str = "<w:rPr><w:b/></w:rPr>",
          cell_rpr: str = "",
          cell_ppr: str = "") -> str:
    """A complete ``<w:tbl>`` from a header list and rows of text.

    `spans` gives each header cell's column span, for grouped headings
    (``[1, 3, 3]`` = a label then two three-column groups); the grid is
    sized from the total. `extra_header` is raw ``<w:tr>`` XML placed above
    the header row, for a second tier of headings.

    Ragged rows are an error rather than something to pad silently: a short
    row in a results table means the caller lost a value.

    `tblpr` is usually cloned off an existing table so the new one
    matches the manuscript, and `require_style` guards the way that
    goes wrong: a manuscript's equation-number carriers are borderless
    1x2 tables with no ``w:tblStyle``, so cloning ``tables[-1]`` hands
    back a template that renders a DATA table with no grid at all. The
    document stays valid and nothing complains — it was caught in a PDF
    render. Pass ``require_style=False`` when a borderless table is
    what you actually want.
    """
    if require_style and "<w:tblStyle" not in tblpr:
        raise AnchorError(
            "table: the tblPr carries no w:tblStyle, so this table would "
            "render unstyled - clone a DATA table's properties, or pass "
            "require_style=False for a deliberately borderless one")
    spans = spans or [1] * len(headers)
    if len(spans) != len(headers):
        raise AnchorError(
            f"table: {len(headers)} headers but {len(spans)} spans")
    columns = sum(spans)
    for i, r in enumerate(rows):
        if len(r) != columns:
            raise AnchorError(
                f"table: row {i} has {len(r)} cells, header spans {columns} "
                "columns")

    width = _TOTAL_WIDTH // columns
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for _ in range(columns))
    head = row([cell(h, span=s, tcpr=_HDR_TCPR, rpr=header_rpr, ppr=cell_ppr)
                for h, s in zip(headers, spans, strict=True)], header=True)
    body = "".join(row([cell(c, rpr=cell_rpr, ppr=cell_ppr) for c in r])
                   for r in rows)
    return (f"<w:tbl>{tblpr}<w:tblGrid>{grid}</w:tblGrid>"
            f"{extra_header}{head}{body}</w:tbl>")


_HDR_TCPR = ('<w:tcPr><w:tcW w:w="0" w:type="auto"/><w:tcBorders>'
             '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="auto"/>'
             "</w:tcBorders></w:tcPr>")


def insert_after(xml: str, sig: str, content: str, *,
                 allow_colon: bool = False, normalize: bool = False) -> str:
    """Insert `content` immediately after the paragraph containing `sig`.

    Refuses when that paragraph ends in a colon, unless `allow_colon`: a
    lead-in like "...is defined as:" introduces the block that follows, and
    inserting between them silently splits the sentence from its equation
    or list. Anchor on the equation paragraph instead — which is where a
    definition of its symbols belongs anyway.
    """
    start, end = para_slice(xml, sig, normalize=normalize)
    if not allow_colon and visible_text(xml[start:end]).rstrip().endswith(":"):
        raise AnchorError(
            f"insert_after({sig[:40]!r}): that paragraph ends in a colon, so "
            "it introduces what follows and this would split them. Anchor on "
            "the following block, or pass allow_colon=True.")
    return xml[:end] + content + xml[end:]


def insert_before(xml: str, sig: str, content: str, *,
                  normalize: bool = False) -> str:
    """Insert `content` immediately before the paragraph containing `sig`."""
    start, _ = para_slice(xml, sig, normalize=normalize)
    return xml[:start] + content + xml[start:]


def prose_props(para_xml: str) -> tuple[str, str]:
    """``(pPr, rPr)`` to clone from a paragraph — from its PROSE runs.

    **Both come WRAPPED**, and that symmetry is the fix for a defect the
    asymmetry caused. The rPr always carried its wrapper and the pPr
    never did, while the two are documented as a pair to hand straight
    to :func:`para` — which spliced them in verbatim. See `para`.

    The obvious version lifts the FIRST ``w:rPr`` in the paragraph, and
    a paragraph that opens on a citation is ordinary: its first run
    properties belong to the LINK. The new paragraph then renders blue
    and underlined, linking nowhere, and no text-layer check can see it
    — the words are right, the style is a lie (LI7, 2026-08-15).

    So runs inside a ``w:hyperlink`` element, runs inside a fldChar
    field, and runs carrying the ``Hyperlink`` character style are all
    skipped. A paragraph whose runs are ALL link labels answers with an
    empty ``rPr`` rather than a link's, because no properties at all is
    a template a caller can see through, and a link's are not.
    """
    ppr = own_properties(para_xml, "pPr")
    masked = para_xml
    for lo, hi in [(m.start(), m.end())
                   for m in HYPERLINK_ANY_RE.finditer(para_xml)] + \
                  [(lo, hi) for lo, hi, _ in field_spans(para_xml)]:
        masked = masked[:lo] + " " * (hi - lo) + masked[hi:]
    for run_match in RUN_RE.finditer(masked):
        run_xml = para_xml[run_match.start():run_match.end()]
        if _HYPERLINK_STYLE in run_xml:
            continue
        own = own_properties(run_xml, "rPr")
        return (f"<w:pPr>{ppr[2]}</w:pPr>" if ppr else "",
                f"<w:rPr>{own[2]}</w:rPr>" if own else "")
    return (f"<w:pPr>{ppr[2]}</w:pPr>" if ppr else ""), ""
