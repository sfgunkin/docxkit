r"""Figures: finding them, replacing their images, sizing and orienting.

Forty-odd files across the papers do this — AFI's ``swap_figure2/7/8``,
``integrate_fig*``, ``landscape_figures``, ``reembed_rescaled_figures``,
plus FLOPs, HPPA, DSI and the LE builders. The traps below are why they
kept going wrong:

* **A caption sits ABOVE its figure**, as it does above a table. Mapping
  captions to drawings by "the nearest one before" gets every figure
  wrong by one.
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
    "Figure",
    "alt_texts",
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
# how many paragraphs after a caption may hold its drawings
_DRAWING_WINDOW = 6


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
    paras = list(PARA_RE.finditer(doc_xml))
    texts = [visible_text(p.group(0)).strip() for p in paras]
    out = []
    for i, text in enumerate(texts):
        if not _CAPTION_RE.match(text):
            continue
        embeds: list[str] = []
        for p in paras[i + 1:i + 1 + _DRAWING_WINDOW]:
            found = _EMBED_RE.findall(p.group(0))
            if found:
                embeds.extend(found)
            elif embeds:
                break              # drawings ended; the figure is complete
        out.append(Figure(caption=text, caption_index=i, embeds=embeds))
    return out


def find(doc_xml: str, caption_prefix: str) -> Figure:
    """The single figure whose caption starts with `caption_prefix`."""
    paras = list(PARA_RE.finditer(doc_xml))
    hits = [i for i, p in enumerate(paras)
            if visible_text(p.group(0)).strip().startswith(caption_prefix)]
    if not hits:
        raise AnchorError(f"no caption starting {caption_prefix!r}")
    if len(hits) > 1:
        raise AnchorError(
            f"{len(hits)} captions start {caption_prefix!r} — "
            "'Figure 1.' also prefixes 'Figure 10.', so include the dot")
    i = hits[0]
    embeds: list[str] = []
    for p in paras[i + 1:i + 1 + _DRAWING_WINDOW]:
        found = _EMBED_RE.findall(p.group(0))
        if found:
            embeds.extend(found)
        elif embeds:
            break
    return Figure(caption=visible_text(paras[i].group(0)).strip(),
                  caption_index=i, embeds=embeds)


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
    paras = list(PARA_RE.finditer(doc_xml))
    texts = [visible_text(p.group(0)).strip() for p in paras]
    owner: dict[int, str] = {}
    for i, text in enumerate(texts):
        if _CAPTION_RE.match(text):
            for j in range(i + 1, min(i + 1 + _DRAWING_WINDOW, len(paras))):
                if _CAPTION_RE.match(texts[j]):
                    break            # the next figure's window starts here
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
    paras = list(PARA_RE.finditer(doc_xml))
    blocks: list[tuple[int, int, str]] = []
    stop = min(figure.caption_index + 1 + _DRAWING_WINDOW, len(paras))
    for p in paras[figure.caption_index + 1:stop]:
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
    paras = list(PARA_RE.finditer(doc))
    for p in paras[figure.caption_index + 1:
                   figure.caption_index + 1 + _DRAWING_WINDOW]:
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
