r"""Figures: finding them, replacing their images, sizing and orienting.

Forty-odd files across the papers do this — AFI's ``swap_figure2/7/8``,
``integrate_fig*``, ``landscape_figures``, ``reembed_rescaled_figures``,
plus FLOPs, HPPA, DSI and the LE builders. The traps below are why they
kept going wrong:

* **A caption sits ABOVE its figure**, as it does above a table. Mapping
  captions to drawings by "the nearest one before" gets every figure
  wrong by one. **But not in every paper** — Aging_Well's diagrams carry
  the caption in the paragraph directly AFTER the image, and a
  forward-only window found no drawings for any of them, which left
  ``figures --check`` permanently red with the one writer that could
  clear it raising `AnchorError`. :func:`caption_side` reads the
  convention off the document, by majority, once.
* **One figure can be several images.** AFI's Figure 6 is three Lorenz
  curves, so image indices and figure numbers do not correspond.
* **Replacing image bytes changes every drawing that shares the
  relationship.** AFI's Figures 8, 11 and 12 all pointed at ``image10``;
  rewriting it for one changed all three. :func:`replace_image` refuses
  unless you say whether to isolate.
* **Extents are per-drawing.** A document-wide regex on ``<wp:extent>``
  resizes unrelated figures.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from ._xml import DOCUMENT, PARA_RE, SECTPR_RE, visible_text
from .errors import AnchorError, PackageError

__all__ = [
    "EMU_PER_INCH",
    "AltText",
    "AnchorError",
    "Figure",
    "PackageError",
    "alt_texts",
    "caption_side",
    "find",
    "find_all",
    "landscape",
    "replace_image",
    "scale_to_width",
    "section_properties",
    "set_alt_text",
    "set_extent",
    "shared_relationships",
]

EMU_PER_INCH = 914400
_EMBED_RE = re.compile(r'r:embed="([^"]+)"')
_EXTENT_RE = re.compile(r'<wp:extent cx="(\d+)" cy="(\d+)"/>')
_PGSZ_RE = re.compile(r'<w:pgSz([^/]*)/>')
# A caption is a label, a number, then a separator: "Figure 7." or
# "Рисунок 2:". Merely STARTING with "Figure" is not enough — an in-text
# sentence ("Figure 3 shows the gap") begins that way too, and counting
# those found 18 figures in AFI's 14-figure paper.
_CAPTION_RE = re.compile(
    r"^\s*(?:Figure|Рисунок|Fig\.?)\s+([\w.]+?)\s*[.:]\s")
# how many paragraphs away from a caption may hold its drawings
_DRAWING_WINDOW = 6


def _window(texts: list[str], caption_index: int,
            side: str = "after") -> range:
    """Paragraph indices this caption's drawings may sit in.

    Up to `_DRAWING_WINDOW` paragraphs on `side` of the caption,
    stopping early at the NEIGHBOURING caption: a figure whose own
    drawing is missing must not adopt the next figure's. This walk had
    five copies and only `alt_texts` stopped — so `find`, and everything
    addressing a drawing through it, could hand back a neighbour's
    image. `set_alt_text` on a captionless figure would then describe
    the next figure's picture, and the accessibility check would report
    both as done.

    Always ascending, whichever side it reads: `set_alt_text` addresses
    a multi-image figure by position, and position means document order.
    """
    if side == "before":
        floor = max(caption_index - _DRAWING_WINDOW, 0)
        for j in range(caption_index - 1, floor - 1, -1):
            if _CAPTION_RE.match(texts[j]):
                return range(j + 1, caption_index)
        return range(floor, caption_index)
    stop = min(caption_index + 1 + _DRAWING_WINDOW, len(texts))
    for j in range(caption_index + 1, stop):
        if _CAPTION_RE.match(texts[j]):
            return range(caption_index + 1, j)
    return range(caption_index + 1, stop)


def caption_side(doc_xml: str) -> str:
    """Which side of its captions this document keeps its drawings on.

    ``"after"`` is the convention this module was written for — a
    caption above its figure, as it sits above a table — and it is
    still the answer when nothing argues otherwise. ``"before"`` is the
    other one in use across these papers: Aging_Well's three figures
    are conceptual diagrams with the caption in the paragraph directly
    AFTER the image, and a forward-only window found no drawings for
    any of them, so `figures --check` could not go green and
    `set_alt_text` raised `AnchorError` on every caption — the one
    writer that would have cleared the gate.

    Decided by MAJORITY over the document rather than per figure, which
    is the part that matters. A per-figure "look both ways" would
    reintroduce exactly the wrong-neighbour bug `_window` exists to
    prevent: on a caption-below paper, a figure whose own drawing is
    missing would take the next caption's image from the forward side.
    A caption with drawings on both sides votes for neither, since it
    cannot tell them apart, and a document that never resolves keeps
    ``"after"``.
    """
    paras = list(PARA_RE.finditer(doc_xml))
    texts = [visible_text(p.group(0)).strip() for p in paras]
    return _side(paras, texts)


def _side(paras: list[re.Match[str]], texts: list[str]) -> str:
    before = after = 0
    for i, text in enumerate(texts):
        if not _CAPTION_RE.match(text):
            continue
        ahead = any(_EMBED_RE.search(paras[j].group(0))
                    for j in _window(texts, i, "after"))
        behind = any(_EMBED_RE.search(paras[j].group(0))
                     for j in _window(texts, i, "before"))
        if ahead and not behind:
            after += 1
        elif behind and not ahead:
            before += 1
    return "before" if before > after else "after"


def _read(doc_xml: str) -> tuple[list[re.Match[str]], list[str], str]:
    """The paragraphs, their visible text, and the caption convention.

    One place, because five call sites each recomputing the first two
    is how the window came to have five copies that disagreed.
    """
    paras = list(PARA_RE.finditer(doc_xml))
    texts = [visible_text(p.group(0)).strip() for p in paras]
    return paras, texts, _side(paras, texts)


@dataclass(frozen=True)
class Figure:
    """A caption and the images belonging to it."""

    caption: str
    caption_index: int          # paragraph index of the caption
    embeds: list[str]           # r:embed ids, in document order

    @property
    def number(self) -> str | None:
        m = _CAPTION_RE.match(self.caption)
        return m.group(1) if m else None


def find_all(doc_xml: str) -> list[Figure]:
    """Every figure caption and the drawings that follow it.

    A caption is a label + number + separator ("Figure 7."), not merely a
    paragraph beginning with "Figure": in-text sentences start that way
    too, and counting them found 18 figures in AFI's 14-figure paper. Its
    images are the ``r:embed`` references in the next few paragraphs,
    which is what makes a three-image figure one Figure with three
    embeds.
    """
    paras, texts, side = _read(doc_xml)
    out = []
    for i, text in enumerate(texts):
        if not _CAPTION_RE.match(text):
            continue
        out.append(Figure(caption=text, caption_index=i,
                          embeds=_embeds_in(paras, texts, i, side)))
    return out


def _embeds_in(paras: list[re.Match[str]], texts: list[str], i: int,
               side: str = "after") -> list[str]:
    """The ``r:embed`` ids belonging to the caption at `i`."""
    return [rid for j in _drawing_paras(paras, texts, i, side)
            for rid in _EMBED_RE.findall(paras[j].group(0))]


def _drawing_paras(paras: list[re.Match[str]], texts: list[str], i: int,
                   side: str) -> list[int]:
    """This figure's drawing-bearing paragraph indices, document order.

    Walked OUTWARD from the caption so that "the first paragraph
    without a drawing closes the figure" means the same thing on both
    sides — on a caption-below paper the source note sits above the
    image, and a walk that started at the far edge of the window would
    close the figure before reaching it.
    """
    window = _window(texts, i, side)
    found: list[int] = []
    for j in (window if side == "after" else reversed(window)):
        if _EMBED_RE.search(paras[j].group(0)):
            found.append(j)
        elif found:
            break              # drawings ended; the figure is complete
    return found if side == "after" else found[::-1]


def find(doc_xml: str, caption_prefix: str) -> Figure:
    """The single figure whose caption starts with `caption_prefix`."""
    paras, texts, side = _read(doc_xml)
    hits = [i for i, text in enumerate(texts)
            if text.startswith(caption_prefix)]
    if not hits:
        raise AnchorError(f"no caption starting {caption_prefix!r}")
    if len(hits) > 1:
        raise AnchorError(
            f"{len(hits)} captions start {caption_prefix!r} — "
            "'Figure 1.' also prefixes 'Figure 10.', so include the dot")
    i = hits[0]
    return Figure(caption=texts[i], caption_index=i,
                  embeds=_embeds_in(paras, texts, i, side))


def shared_relationships(doc_xml: str) -> dict[str, int]:
    """``r:embed`` id -> how many drawings use it.

    Anything above 1 is the AFI Figures 8/11/12 situation: replacing the
    image bytes behind that id changes every figure pointing at it.
    """
    counts: dict[str, int] = {}
    for rid in _EMBED_RE.findall(doc_xml):
        counts[rid] = counts.get(rid, 0) + 1
    return counts


def _relationship_target(rels_xml: str, rid: str) -> str:
    m = re.search(rf'Id="{rid}"[^>]*Target="([^"]+)"', rels_xml)
    if not m:
        raise PackageError(f"relationship {rid} not found in document rels")
    return "word/" + m.group(1).lstrip("/")


def _next_rid(rels_xml: str) -> str:
    used = {int(n) for n in re.findall(r'Id="rId(\d+)"', rels_xml)}
    return f"rId{max(used, default=0) + 1}"


def _png_size(blob: bytes) -> tuple[int, int]:
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise PackageError("not a PNG — cannot read its dimensions")
    width, height = struct.unpack(">II", blob[16:24])
    return width, height


def replace_image(parts: dict[str, bytes], caption_prefix: str,
                  image: str | Path, *, isolate: bool | None = None,
                  keep_width: bool = True) -> str:
    """Point one figure at a new image. Returns the media part written.

    When the figure's relationship is shared with other drawings, this
    raises unless `isolate` says what to do: ``isolate=True`` gives this
    figure its own media part and relationship, leaving the others alone;
    ``isolate=False`` accepts that they all change.

    With `keep_width`, the drawing keeps its displayed width and the
    height is recomputed from the new image's aspect, so Word does not
    stretch it.
    """
    image = Path(image)
    if not image.exists():
        raise PackageError(f"image not found: {image}")
    doc = parts[DOCUMENT].decode("utf-8")
    rels_name = "word/_rels/document.xml.rels"
    rels = parts[rels_name].decode("utf-8")

    figure = find(doc, caption_prefix)
    if not figure.embeds:
        raise AnchorError(f"{caption_prefix!r} has no drawing after it")
    rid = figure.embeds[0]

    uses = shared_relationships(doc).get(rid, 0)
    if uses > 1 and isolate is None:
        raise AnchorError(
            f"{caption_prefix!r} uses {rid}, which {uses} drawings share — "
            "replacing its bytes would change all of them. Pass "
            "isolate=True to give this figure its own image, or "
            "isolate=False to change them together.")

    blob = image.read_bytes()
    if uses > 1 and isolate:
        target = _new_media_part(parts, blob)
        new_rid = _next_rid(rels)
        rels = rels.replace(
            "</Relationships>",
            f'<Relationship Id="{new_rid}" Type="http://schemas.openxmlformats'
            '.org/officeDocument/2006/relationships/image" '
            f'Target="{target[len("word/"):]}"/></Relationships>')
        parts[rels_name] = rels.encode("utf-8")
        doc = _repoint_one_drawing(doc, figure, rid, new_rid)
        rid = new_rid
    else:
        target = _relationship_target(rels, rid)
        parts[target] = blob

    if keep_width:
        doc = _rescale_drawing(doc, rid, blob)
    parts[DOCUMENT] = doc.encode("utf-8")
    return target


# ------------------------------------------------------------ alt text ------
# Journals have started requiring alternative text on every figure
# (Elsevier's accessibility checks bounce a submission without it), and
# it is invisible in Word's normal view, so it is exactly the kind of
# thing to audit mechanically. Alt text lives in the drawing's
# ``wp:docPr descr`` attribute — per DRAWING, not per image part, so
# setting it is safe even for figures sharing a relationship.

_DRAWING_RE = re.compile(r"<w:drawing>.*?</w:drawing>", re.DOTALL)
_DOCPR_RE = re.compile(r"<wp:docPr\b[^>]*?/?>")
_DESCR_RE = re.compile(r'\sdescr="([^"]*)"')
_NAME_ATTR_RE = re.compile(r'\sname="([^"]*)"')


@dataclass(frozen=True)
class AltText:
    """One drawing's accessibility state."""

    caption: str | None      # the figure caption it belongs to, if any
    name: str                # wp:docPr name ("Picture 3")
    embed: str | None        # relationship id of the image
    descr: str | None        # the alt text; None or "" is the finding

    @property
    def missing(self) -> bool:
        return not (self.descr or "").strip()


def alt_texts(doc_xml: str) -> list[AltText]:
    """Every drawing's alt text, in document order.

    Drawings are attributed to the figure whose caption window they sit
    in (the same window :func:`find_all` uses); a drawing outside any
    window — a logo in a header paragraph, an inline scheme — reports
    ``caption=None`` but is still listed, because the accessibility
    check applies to it all the same.
    """
    paras, texts, side = _read(doc_xml)
    owner: dict[int, str] = {}
    for i, text in enumerate(texts):
        if _CAPTION_RE.match(text):
            for j in _window(texts, i, side):
                owner[j] = text
    out = []
    for j, p in enumerate(paras):
        for dm in _DRAWING_RE.finditer(p.group(0)):
            block = dm.group(0)
            docpr = _DOCPR_RE.search(block)
            name = descr = None
            if docpr is not None:
                if (nm := _NAME_ATTR_RE.search(docpr.group(0))) is not None:
                    name = nm.group(1)
                if (dm2 := _DESCR_RE.search(docpr.group(0))) is not None:
                    descr = dm2.group(1)
            embed = _EMBED_RE.search(block)
            out.append(AltText(caption=owner.get(j), name=name or "",
                               embed=embed.group(1) if embed else None,
                               descr=descr))
    return out


def set_alt_text(doc_xml: str, caption_prefix: str, text: str, *,
                 image_index: int = 0) -> str:
    """Set one drawing's alt text, addressed by its figure caption.

    `image_index` picks the drawing within a multi-image figure (AFI's
    Figure 5 is three Lorenz curves — each needs its own description).
    The attribute is per drawing, so figures sharing an image part do
    not inherit each other's text.
    """
    figure = find(doc_xml, caption_prefix)
    paras, texts, side = _read(doc_xml)
    blocks: list[tuple[int, int, str]] = []
    for j in _window(texts, figure.caption_index, side):
        p = paras[j]
        for dm in _DRAWING_RE.finditer(p.group(0)):
            blocks.append((p.start() + dm.start(), p.start() + dm.end(),
                           dm.group(0)))
    if image_index >= len(blocks):
        raise AnchorError(
            f"{caption_prefix!r} has {len(blocks)} drawing(s); no "
            f"image_index {image_index}")
    start, end, block = blocks[image_index]
    docpr = _DOCPR_RE.search(block)
    if docpr is None:
        raise PackageError(f"drawing under {caption_prefix!r} has no "
                           f"wp:docPr to carry alt text")
    safe = (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
    el = docpr.group(0)
    if _DESCR_RE.search(el):
        new_el = _DESCR_RE.sub(lambda _: f' descr="{safe}"', el, count=1)
    elif el.endswith("/>"):
        new_el = el[:-2] + f' descr="{safe}"/>'
    else:
        new_el = el[:-1] + f' descr="{safe}">'
    new_block = block.replace(el, new_el, 1)
    return doc_xml[:start] + new_block + doc_xml[end:]


def _new_media_part(parts: dict[str, bytes], blob: bytes) -> str:
    existing = [n for n in parts if n.startswith("word/media/image")]
    used = {int(m.group(1)) for n in existing
            if (m := re.search(r"image(\d+)\.", n))}
    name = f"word/media/image{max(used, default=0) + 1}.png"
    parts[name] = blob
    return name


def _repoint_one_drawing(doc: str, figure: Figure, old_rid: str,
                         new_rid: str) -> str:
    """Repoint only THIS figure's drawing, leaving its siblings on the
    shared relationship."""
    paras, texts, side = _read(doc)
    for j in _window(texts, figure.caption_index, side):
        p = paras[j]
        block = p.group(0)
        if f'r:embed="{old_rid}"' in block:
            fixed = block.replace(f'r:embed="{old_rid}"',
                                  f'r:embed="{new_rid}"', 1)
            return doc[:p.start()] + fixed + doc[p.end():]
    raise AnchorError("the figure's drawing vanished between passes")


def _rescale_drawing(doc: str, rid: str, blob: bytes) -> str:
    """Keep the drawing's width; set its height from the image aspect."""
    for p in PARA_RE.finditer(doc):
        block = p.group(0)
        if f'r:embed="{rid}"' not in block:
            continue
        m = _EXTENT_RE.search(block)
        if not m:
            return doc
        width, height = _png_size(blob)
        cx = int(m.group(1))
        cy = round(cx * height / width)
        return doc[:p.start()] + set_extent(block, cx, cy) + doc[p.end():]
    return doc


def set_extent(block: str, cx: int, cy: int) -> str:
    """Set one drawing block's extent, in EMU.

    Scoped to the block on purpose: a document-wide regex on
    ``<wp:extent>`` silently resizes every other figure too.
    """
    block = _EXTENT_RE.sub(f'<wp:extent cx="{cx}" cy="{cy}"/>', block, count=1)
    return re.sub(r'<a:ext cx="\d+" cy="\d+"/>',
                  f'<a:ext cx="{cx}" cy="{cy}"/>', block, count=1)


def scale_to_width(block: str, image: str | Path, width_inches: float) -> str:
    """Size a drawing to `width_inches`, height following the aspect."""
    blob = Path(image).read_bytes()
    width, height = _png_size(blob)
    cx = round(width_inches * EMU_PER_INCH)
    return set_extent(block, cx, round(cx * height / width))


def section_properties(doc_xml: str) -> str:
    """The body's final ``<w:sectPr>`` — the template for a new section."""
    hits: list[str] = SECTPR_RE.findall(doc_xml)
    if not hits:
        raise AnchorError("document has no sectPr")
    return hits[-1]


def landscape(sect_pr: str) -> str:
    """A copy of `sect_pr` turned landscape.

    Swaps the page dimensions and sets ``w:orient``; margins, headers and
    footer references are carried over, which is what makes the resulting
    section look like the rest of the document.
    """
    m = _PGSZ_RE.search(sect_pr)
    if not m:
        raise AnchorError("sectPr has no w:pgSz")
    attrs = m.group(1)
    w = re.search(r'w:w="(\d+)"', attrs)
    h = re.search(r'w:h="(\d+)"', attrs)
    if not (w and h):
        raise AnchorError("w:pgSz has no width/height")
    swapped = (f'<w:pgSz w:w="{h.group(1)}" w:h="{w.group(1)}" '
               'w:orient="landscape"/>')
    return sect_pr[:m.start()] + swapped + sect_pr[m.end():]
