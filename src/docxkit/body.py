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

from ._xml import escape, visible_text
from .errors import AnchorError
from .find import para_slice

__all__ = [
    "cell",
    "insert_after",
    "insert_before",
    "para",
    "row",
    "run",
    "table",
]

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
    """
    return f"<w:p>{ppr}{content}</w:p>"


def cell(content: str, *, span: int = 1, tcpr: str = "", rpr: str = "",
         ppr: str = "") -> str:
    """One ``<w:tc>``.

    `content` may be plain text or ready-made paragraph XML; text is
    wrapped in a paragraph, because a ``w:tc`` with no ``w:p`` makes Word
    declare the document unreadable.
    """
    body = (content if content.lstrip().startswith("<w:p")
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
          header_rpr: str = "<w:rPr><w:b/></w:rPr>",
          cell_rpr: str = "") -> str:
    """A complete ``<w:tbl>`` from a header list and rows of text.

    `spans` gives each header cell's column span, for grouped headings
    (``[1, 3, 3]`` = a label then two three-column groups); the grid is
    sized from the total. `extra_header` is raw ``<w:tr>`` XML placed above
    the header row, for a second tier of headings.

    Ragged rows are an error rather than something to pad silently: a short
    row in a results table means the caller lost a value.
    """
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
    head = row([cell(h, span=s, tcpr=_HDR_TCPR, rpr=header_rpr)
                for h, s in zip(headers, spans, strict=True)], header=True)
    body = "".join(row([cell(c, rpr=cell_rpr) for c in r]) for r in rows)
    return (f"<w:tbl>{tblpr}<w:tblGrid>{grid}</w:tblGrid>"
            f"{extra_header}{head}{body}</w:tbl>")


_HDR_TCPR = ('<w:tcPr><w:tcW w:w="0" w:type="auto"/><w:tcBorders>'
             '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="auto"/>'
             "</w:tcBorders></w:tcPr>")


def insert_after(xml: str, sig: str, content: str, *,
                 allow_colon: bool = False) -> str:
    """Insert `content` immediately after the paragraph containing `sig`.

    Refuses when that paragraph ends in a colon, unless `allow_colon`: a
    lead-in like "...is defined as:" introduces the block that follows, and
    inserting between them silently splits the sentence from its equation
    or list. Anchor on the equation paragraph instead — which is where a
    definition of its symbols belongs anyway.
    """
    start, end = para_slice(xml, sig)
    if not allow_colon and visible_text(xml[start:end]).rstrip().endswith(":"):
        raise AnchorError(
            f"insert_after({sig[:40]!r}): that paragraph ends in a colon, so "
            "it introduces what follows and this would split them. Anchor on "
            "the following block, or pass allow_colon=True.")
    return xml[:end] + content + xml[end:]


def insert_before(xml: str, sig: str, content: str) -> str:
    """Insert `content` immediately before the paragraph containing `sig`."""
    start, _ = para_slice(xml, sig)
    return xml[:start] + content + xml[start:]
