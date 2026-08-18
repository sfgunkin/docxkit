r"""What the RENDER says: one row per sheet, and the defects XML hides.

``docxkit pages`` printed ``52`` and nothing else, and two pagination
defects shipped in `Parental_style` because nothing surfaced them — both
found by the author reading the PDF on 2026-08-12, neither visible to any
gate in this package:

* page numbering restarted at 1 after the References (a ``pgNumType
  w:start="1"`` on the second section), and ``titlePg`` was set on all
  four sections with no first-page footer, so the opening sheet of every
  section printed nothing. Rendered: ``… 28, -, -, 3, -, 5 …``;
* a blank landscape sheet between Tables 2 and 3, from two empty
  paragraphs that would not fit beside Table 2.

`lint` is clean on both. `compare` reports **zero** real change locations
for either FIX — correct, since neither moves a word, and exactly why no
text-layer check can ever see them.

**Pagination cannot be inferred from the markup.** Two plausible causes
for the blank page were derived from the XML and BOTH were falsified by
re-rendering: shrinking the ``sectPr`` host paragraph (still 53 pages)
and removing a redundant ``<w:br w:type="page"/>`` stacked on the section
break (still 53). Only the render found the real one. So this module
measures the PDF Word produces, and the analysis is deliberately split so
that only the first step needs Word at all:

    sheets(docx)  -> Word renders, then read_pdf reads      (Word + PyMuPDF)
    read_pdf(pdf) -> one Sheet per physical sheet           (PyMuPDF)
    problems(...) -> the verdicts --check exits on          (pure)
"""
from __future__ import annotations

import re
import shutil
import tempfile
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

__all__ = ["Sheet", "problems", "read_pdf", "sheets"]

#: How much of a sheet is footer, and how much is header. A page number
#: printed by Word sits inside the margin band; 12 % of the height is
#: what the hand-rolled version sampled on `Parental_style`, three times
#: in one session, and it read every number correctly there.
_BAND = 0.12
_NUMBER_RE = re.compile(r"^\d{1,4}$")


class Sheet(NamedTuple):
    """One physical sheet of the render."""

    number: int
    """1-based physical sheet — what a PDF reader's toolbar shows.

    NOT called `index`: a NamedTuple field of that name would shadow
    `tuple.index`, and a reader who calls the method gets a number that
    looks plausible."""
    orientation: str
    """``"portrait"`` or ``"landscape"`` — from the page box, not the
    ``sectPr``, because a section's orientation and the sheet the reader
    holds are not the same claim."""
    printed: int | None
    """The number PRINTED on the sheet, or None when it prints none. Not
    the index: the whole defect class here is the two disagreeing."""
    blank: bool
    """No text, no image, no drawing. A sheet that exists to be turned."""

    def __str__(self) -> str:
        printed = "-" if self.printed is None else str(self.printed)
        flags = " BLANK" if self.blank else ""
        return (f"{self.number:4d}  {self.orientation:9s} "
                f"prints {printed:>4s}{flags}")


def _import_pymupdf() -> Any:
    try:
        import pymupdf  # pyright: ignore[reportMissingImports]
    except ImportError as exc:                          # pragma: no cover
        raise ImportError(
            "reading the render needs PyMuPDF: pip install "
            "'docxkit[pdf]' (or pymupdf). Everything else in docxkit "
            "works without it.") from exc
    return pymupdf


def _printed_number(page: Any, band: float) -> int | None:
    """The page number printed in this sheet's margins, if exactly one.

    Both bands, because a paper that numbers in the header is not a
    paper with no numbers. Ambiguity answers None rather than guessing:
    a footer that also carries a running head can hold several numbers,
    and a wrong number here would read as a numbering defect that is not
    there.
    """
    height = page.rect.height
    for top, bottom in ((height * (1 - band), height), (0, height * band)):
        clip = page.rect.__class__(0, top, page.rect.width, bottom)
        found = [tok for tok in page.get_text(clip=clip).split()
                 if _NUMBER_RE.match(tok)]
        if len(found) == 1:
            return int(found[0])
    return None


def read_pdf(pdf: str | Path, *, band: float = _BAND) -> list[Sheet]:
    """One :class:`Sheet` per physical sheet of a rendered PDF."""
    pymupdf = _import_pymupdf()
    out: list[Sheet] = []
    with pymupdf.open(str(pdf)) as doc:
        for i, page in enumerate(doc, 1):
            rect = page.rect
            blank = not (page.get_text().strip() or page.get_images()
                         or page.get_drawings())
            out.append(Sheet(
                number=i,
                orientation="landscape" if rect.width > rect.height
                            else "portrait",
                printed=_printed_number(page, band),
                blank=blank))
    return out


def sheets(docx: str | Path, *, keep_pdf: str | Path | None = None,
           band: float = _BAND) -> list[Sheet]:
    """Render `docx` through Word and read the sheets back.

    `keep_pdf` writes the render where you can look at it; without it
    the PDF is a temporary file, because the answer wanted here is the
    table, not the artifact.
    """
    from .word import export_pdf

    if keep_pdf is not None:
        return read_pdf(export_pdf(docx, keep_pdf), band=band)
    staging = Path(tempfile.mkdtemp(prefix="docxkit_pages_"))
    try:
        return read_pdf(export_pdf(docx, staging / "render.pdf"), band=band)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def problems(rows: list[Sheet]) -> list[str]:
    """What ``--check`` exits on, in the order a reader meets them.

    Three verdicts, and each is a defect this package could not see
    before: a BLANK sheet, a numbering RESTART, and a GAP in the printed
    sequence. A sheet that prints nothing is REPORTED by the table and
    is not a failure on its own — a title page legitimately carries no
    number, and a gate that fails on every paper is a gate nobody runs.
    """
    out = [f"sheet {row.number} is BLANK" for row in rows if row.blank]
    numbered = [(row.number, row.printed) for row in rows
                if row.printed is not None]
    for (_, was), (sheet, now) in pairwise(numbered):
        if now <= was:
            out.append(f"printed numbering RESTARTS on sheet {sheet}: "
                       f"{was} -> {now}")
        elif now > was + 1:
            out.append(f"printed numbers JUMP on sheet {sheet}: {was} -> "
                       f"{now} (the sheets between print nothing)")
    return out
