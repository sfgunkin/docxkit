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

`caption_problems` is the verdict that needs the words as well — which
sheet each figure caption landed on — and `sheets_and_texts` reads both
off one render.

`render_anchors` is the other thing a render is for: not the table, but
the PAGE — the one check that catches a glyph that went the wrong way,
an equation that renders wrong, a table that split. It rasterises the
page each anchor falls on and leaves a PNG to look at.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from itertools import pairwise
from os.path import commonprefix
from pathlib import Path
from typing import Any, NamedTuple

from .errors import PackageError

__all__ = ["Sheet", "caption_problems", "page_texts", "problems",
           "read_pdf", "read_texts", "render_anchors", "sheets",
           "sheets_and_texts"]

#: How much of a sheet is footer, and how much is header. A page number
#: printed by Word sits inside the margin band; 12 % of the height is
#: what the hand-rolled version sampled on `Parental_style`, three times
#: in one session, and it read every number correctly there.
_BAND = 0.12
_NUMBER_RE = re.compile(r"^\d{1,4}$")
#: How much of a caption finds it on a sheet, whitespace removed: the
#: probe `placement` reads a table's caption with.
_PROBE = 40
#: Image parts a render draws as an IMAGE. A metafile is drawn as paths,
#: and a sheet of plain text has paths too — an underline, a table rule,
#: the footnote separator — so its absence cannot be told from a sheet.
_RASTER = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff")


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
    corner: str | None = None
    """WHERE the number is printed — ``"lower right"``, ``"upper
    centre"`` — or None when none is printed.

    The number being present and the number being in the right place are
    two claims, and only the first was ever measured: `_printed_number`
    scans the whole width of the band, so a paper numbering bottom-left
    or centre read exactly like the house's bottom-right. The house rule
    for these papers is a right-aligned footer (see the paper-formatting
    conventions), and a numbering position that drifts mid-document is
    the shape a section break with its own footer leaves behind."""
    images: int = 0
    """How many images the sheet DRAWS, counted where they are placed, so
    one inside a form object counts too. A caption on a sheet that draws
    none has been parted from its raster figure: :func:`caption_problems`."""

    def __str__(self) -> str:
        printed = "-" if self.printed is None else str(self.printed)
        flags = " BLANK" if self.blank else ""
        where = f"  {self.corner}" if self.corner else ""
        return (f"{self.number:4d}  {self.orientation:9s} "
                f"prints {printed:>4s}{where}{flags}")


def _import_pymupdf() -> Any:
    try:
        import pymupdf  # pyright: ignore[reportMissingImports]
    except ImportError as exc:                          # pragma: no cover
        raise ImportError(
            "reading the render needs PyMuPDF: pip install "
            "'docxkit[pdf]' (or pymupdf). Everything else in docxkit "
            "works without it.") from exc
    return pymupdf


def render_anchors(pdf: str | Path, anchors: Sequence[str], *,
                   dpi: int = 150, out_dir: str | Path | None = None,
                   stem: str | None = None) -> dict[str, Path | None]:
    """Rasterise the first page carrying each anchor. ``{anchor: png}``.

    An anchor no page carries maps to None rather than raising: the
    caller asked to LOOK at something, and half a render is worth more
    than none — the missing one is named in the answer. A BLANK anchor
    is dropped instead: it is a shell artifact, and it would match the
    first page and render it for nothing.

    Matched with whitespace FOLDED on both sides: the extracted text
    carries a newline at every line end, so a phrase that wraps — the
    ordinary fate of a sentence's first line on a narrow measure — was
    on no page at all. The anchors `revision validate` names by itself
    are a paragraph's first words, and a paragraph starts a line, but
    forty characters still wrap in a two-column journal.

    Pages are walked by INDEX rather than `enumerate(doc)`: PyMuPDF's
    Document is iterable at run time and its stubs do not say so, and
    this package is type-checked twice.
    """
    pymupdf = _import_pymupdf()
    pdf = Path(pdf)
    where = Path(out_dir) if out_dir is not None else pdf.parent
    where.mkdir(parents=True, exist_ok=True)
    name = stem or pdf.stem
    out: dict[str, Path | None] = {}
    with pymupdf.open(str(pdf)) as doc:
        texts = [" ".join(doc[i].get_text().split())
                 for i in range(doc.page_count)]
        for anchor in dict.fromkeys(a for a in anchors if a.strip()):
            out[anchor] = None
            wanted = " ".join(anchor.split())
            for i in range(doc.page_count):
                page = doc[i]
                if wanted not in texts[i]:
                    continue
                png = where / f"{name}__p{i + 1}.png"
                page.get_pixmap(dpi=dpi).save(str(png))
                out[anchor] = png
                break
    return out


def _printed_number(page: Any, band: float) -> tuple[int | None, str | None]:
    """The page number printed in this sheet's margins, and WHERE.

    Both bands, because a paper that numbers in the header is not a
    paper with no numbers. Ambiguity answers None rather than guessing:
    a footer that also carries a running head can hold several numbers,
    and a wrong number here would read as a numbering defect that is not
    there.

    The corner comes from the word's own box rather than from the
    footer's `w:jc`: what is being checked is the sheet a reader holds,
    and a right-aligned footer inside a wrongly-indented paragraph
    prints in the middle of the page while its XML says "right".
    """
    height, width = page.rect.height, page.rect.width
    for edge, top, bottom in (("lower", height * (1 - band), height),
                              ("upper", 0.0, height * band)):
        clip = page.rect.__class__(0, top, width, bottom)
        line = _outermost_line(page.get_text("words", clip=clip), edge)
        if len(line) != 1 or not _NUMBER_RE.match(line[0][4]):
            continue
        x0, x1 = line[0][0], line[0][2]
        middle = (x0 + x1) / 2
        side = ("left" if middle < width / 3 else
                "right" if middle > 2 * width / 3 else "centre")
        return int(line[0][4]), f"{edge} {side}"
    return None, None


def _outermost_line(words: list[Any], edge: str) -> list[Any]:
    """The bottom-most (or top-most) line of text in a band.

    **The band is not the footer.** A paper with FOOTNOTES puts them in
    the same 12 % of the sheet, and their text is full of bare numbers —
    the marker that opens each note, and the note's own citations. On
    Aging_Well that made three sheets read as printing NOTHING (two
    numbers in the band is ambiguity, and ambiguity answers None) and
    one read the footnote marker at the top of the body as its page
    number: `… 3, -, 5 …` and a "numbering RESTARTS 7 -> 5" that was
    not there. Every one of those was a false alarm about a correctly
    numbered document, which is the kind of gate a reader learns to
    ignore.

    Word sets the footer BELOW the footnote separator, so the page
    number is the last line on the sheet — measured on that paper, the
    number sits at y 742.8 against the footnotes' 720.1. Taking the
    outermost line, and requiring it to be a lone number, tells the two
    apart. A running head that shares the line ("Chapter 3 page 14") is
    still ambiguous and still answers None.
    """
    if not words:
        return []
    key = (max(w[3] for w in words) if edge == "lower"
           else min(w[1] for w in words))
    # 3 pt of tolerance: words on one line differ slightly in their box
    # depending on ascenders and descenders.
    return [w for w in words
            if abs((w[3] if edge == "lower" else w[1]) - key) <= 3.0]


@contextmanager
def _rendered(docx: str | Path,
              keep_pdf: str | Path | None) -> Generator[Path, None, None]:
    """A render of `docx` through Word, for as long as the block runs.

    A named PDF is written where the caller asked and KEPT; an unnamed one
    goes to a staging directory that is removed afterwards. The removal
    ignores errors because on Windows a reader that has not released the
    file makes it raise, AFTER the answer is in hand.
    """
    from .word import export_pdf

    if keep_pdf is not None:
        yield export_pdf(docx, keep_pdf)
        return
    staging = Path(tempfile.mkdtemp(prefix="docxkit_pages_"))
    try:
        yield export_pdf(docx, staging / "render.pdf")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def page_texts(docx: str | Path) -> list[str]:
    """The TEXT of each rendered sheet, in order.

    :func:`sheets` answers "what does this sheet look like" — orientation,
    printed number, blank — and carries no text at all, by design. A caller
    that needs to know WHICH sheet a caption or a paragraph landed on needs
    the words, and had no way to get them: `cmd_fit` reached for
    ``[str(row) for row in sheets(...)]`` and handed `placement.audit` a list
    of formatted rows — ``1  portrait  prints  1  lower right`` — in which no
    caption can ever be found. That is the renderer contract
    `placement`/`repack` expect, so this is it.
    """
    with _rendered(docx, None) as pdf:
        return read_texts(pdf)


def read_texts(pdf: str | Path) -> list[str]:
    """The text of each sheet of a rendered PDF, in order."""
    pymupdf = _import_pymupdf()
    with pymupdf.open(str(pdf)) as doc:
        return [page.get_text() for page in doc]


def read_pdf(pdf: str | Path, *, band: float = _BAND) -> list[Sheet]:
    """One :class:`Sheet` per physical sheet of a rendered PDF."""
    pymupdf = _import_pymupdf()
    out: list[Sheet] = []
    with pymupdf.open(str(pdf)) as doc:
        for i, page in enumerate(doc, 1):
            rect = page.rect
            blank = not (page.get_text().strip() or page.get_images()
                         or page.get_drawings())
            printed, corner = _printed_number(page, band)
            out.append(Sheet(
                number=i,
                orientation="landscape" if rect.width > rect.height
                            else "portrait",
                printed=printed,
                blank=blank,
                corner=corner,
                images=len(page.get_image_info())))
    return out


def sheets(docx: str | Path, *, keep_pdf: str | Path | None = None,
           band: float = _BAND) -> list[Sheet]:
    """Render `docx` through Word and read the sheets back.

    `keep_pdf` writes the render where you can look at it; without it
    the PDF is a temporary file, because the answer wanted here is the
    table, not the artifact.
    """
    with _rendered(docx, keep_pdf) as pdf:
        return read_pdf(pdf, band=band)


def sheets_and_texts(docx: str | Path, *,
                     keep_pdf: str | Path | None = None,
                     band: float = _BAND) -> tuple[list[Sheet], list[str]]:
    """:func:`sheets` and :func:`page_texts` off ONE render.

    ``--check`` asks both of every paper: what each sheet looks like, and
    where each figure caption landed. Two renders would take twice as long
    and could lay the document out twice, differently.
    """
    with _rendered(docx, keep_pdf) as pdf:
        return read_pdf(pdf, band=band), read_texts(pdf)


def problems(rows: list[Sheet], *,
             corner: str | None = "lower right",
             expect_sheets: int | None = None) -> list[str]:
    """What ``--check`` exits on, in the order a reader meets them.

    Four verdicts, and each is a defect this package could not see
    before: a BLANK sheet, a numbering RESTART, a GAP in the printed
    sequence, and a number printed somewhere other than `corner`. A
    sheet that prints nothing is REPORTED by the table and is not a
    failure on its own — a title page legitimately carries no number,
    and a gate that fails on every paper is a gate nobody runs.

    `corner` is the house rule for these papers, a right-aligned footer,
    and it is checked against the RENDER rather than the footer's `w:jc`
    — a right-aligned paragraph that is indented off-centre prints in
    the middle of the page and its XML still says "right". A paper that
    numbers elsewhere on purpose passes ``corner=None``, which is what
    ``--corner any`` does.

    `expect_sheets` pins the COUNT, for a paper whose length is known,
    and it comes first because it is about the whole render. Nothing
    else compares the count with anything: on Aging_Well (2026-09-12,
    R131) one caption sentence took the render from 40 sheets to 41, with
    every sheet numbered and none blank, and the count was the only
    figure that moved.
    """
    out: list[str] = []
    if expect_sheets is not None and len(rows) != expect_sheets:
        out.append(f"the render has {len(rows)} sheet(s), not the "
                   f"{expect_sheets} expected")
    out += [f"sheet {row.number} is BLANK" for row in rows if row.blank]
    numbered = [(row.number, row.printed) for row in rows
                if row.printed is not None]
    for (_, was), (sheet, now) in pairwise(numbered):
        if now <= was:
            out.append(f"printed numbering RESTARTS on sheet {sheet}: "
                       f"{was} -> {now}")
        elif now > was + 1:
            out.append(f"printed numbers JUMP on sheet {sheet}: {was} -> "
                       f"{now} (the sheets between print nothing)")
    out += [f"sheet {row.number} prints its number {row.corner}, not "
            f"{corner}" for row in rows
            if corner is not None and row.corner not in (None, corner)]
    return out


def caption_problems(parts: Mapping[str, bytes], rows: Sequence[Sheet],
                     texts: Sequence[str]) -> list[str]:
    """Figure captions a sheet break parted from their figures.

    Measured on Aging_Well (2026-09-12, R131). One sentence added to
    Figure 2's caption made it six lines, on a landscape sheet that holds
    the figure and four, and Word set the last two on a sheet of their
    own. :func:`problems` stayed green, correctly: that sheet is not blank,
    it prints its number, and the sequence does not jump. What a reader
    turning to the figure meets is a figure without the end of its
    caption.

    Two ways a sheet break parts them, both read off the words:

    * the caption is SPLIT, opening on one sheet and ending on the next —
      the shape above, and what widow control does to a caption of four
      lines or more;
    * the caption is whole on a sheet that draws NO image, which is where
      widow control moves a short caption left a line of room. Asked only
      of a figure that draws a raster image, since a metafile or an SVG
      renders as paths and a sheet of text has paths too; and of the sheet
      the figure should share — the one the caption opens on when the
      figure stands above it, and the one it ends on when it stands below.

    Measured before it shipped, over the renders of eight papers: all 36
    figure captions located and none reported, once an SVG's fallback PNG
    stopped counting as an image (:func:`_raster`). Aging_Well with R131's
    sentence put back reads SPLIT, and the same caption held together reads
    as a caption on a sheet that draws no image.

    A caption is found by its opening words on the LAST sheet carrying
    them, since a list of figures repeats every caption and comes first.
    It is followed only as far as the render spells it the way the markup
    does, so a caption holding a note mark or a field the markup keeps no
    text for reads as whole where it stops matching: that is silence, not
    a verdict, and a verdict needs the words.
    """
    from ._xml import DOCUMENT
    from .figures import caption_side

    doc = parts[DOCUMENT].decode("utf-8")
    rels = parts.get("word/_rels/document.xml.rels", b"").decode("utf-8")
    below = caption_side(doc) == "before"
    out: list[str] = []
    for name, first, last, raster in _placed_captions(doc, rels, texts):
        if last != first:
            out.append(f"{name}'s caption is SPLIT: it opens on sheet "
                       f"{first + 1} and ends on sheet {last + 1}")
        shared = first if below else last
        if raster and shared < len(rows) and not rows[shared].images:
            out.append(f"{name}'s caption is on sheet {shared + 1}, which "
                       f"draws no image: its figure is on another sheet")
    return out


def _placed_captions(doc: str, rels: str, texts: Sequence[str],
                     ) -> list[tuple[str, int, int, bool]]:
    """Each figure caption the render shows: its name, the sheets it opens
    and ends on (0-based), and whether its figure draws a raster image."""
    from .figures import find_all
    from .placement import _flat

    flats = [_flat(text) for text in texts]
    out: list[tuple[str, int, int, bool]] = []
    for figure in find_all(doc):
        caption = _flat(figure.caption)
        probe = caption[:_PROBE]
        homes = [i for i, flat in enumerate(flats) if probe in flat]
        if not homes:
            continue
        first = last = homes[-1]
        at = flats[first].rindex(probe)
        rest = caption[len(commonprefix((caption, flats[first][at:]))):]
        after = flats[first + 1] if first + 1 < len(flats) else ""
        if rest and rest[:_PROBE] in after:
            last = first + 1
        name = " ".join(figure.caption.split()[:2]).rstrip(".:")
        out.append((name, first, last, _raster(figure.embeds, rels)))
    return out


def _raster(embeds: Sequence[str], rels: str) -> bool:
    """Whether a figure draws a raster image — what a render counts as an
    image, where a metafile renders as paths.

    **An SVG picture is stored as a PNG with the SVG nested inside its
    blip**, and Word draws the SVG, as paths. The PNG is a fallback for
    readers that cannot draw SVG, and it comes right before the SVG among
    the embeds. Counting it read both of Parental_style's figures as raster
    and its Figure 1 — on sheet 48 with its caption, drawn as 48 paths and
    no image — as a figure on another sheet (measured 2026-09-12).
    """
    from .figures import _relationship_target

    targets: list[str] = []
    for rid in embeds:
        try:
            targets.append(_relationship_target(rels, rid).lower())
        except PackageError:
            targets.append("")
    fallbacks = {k - 1 for k, target in enumerate(targets)
                 if target.endswith(".svg")}
    return any(target.endswith(_RASTER) for k, target in enumerate(targets)
               if k not in fallbacks)
