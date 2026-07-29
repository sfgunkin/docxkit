"""Figures — every test here is a trap one of the papers fell into."""
from __future__ import annotations

import struct
import zlib

import pytest
from conftest import document, make_parts, para, run

from docxkit.errors import AnchorError, PackageError
from docxkit.figures import (
    EMU_PER_INCH,
    find,
    find_all,
    landscape,
    replace_image,
    scale_to_width,
    section_properties,
    set_extent,
    shared_relationships,
)


def png(width: int, height: int) -> bytes:
    """A real (tiny) PNG, so the dimension reader has something to read."""
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)))


def drawing(rid: str, cx: int = 5486400, cy: int = 3200400) -> str:
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="{cx}" '
            f'cy="{cy}"/><a:graphic><a:graphicData><pic:pic><pic:blipFill>'
            f'<a:blip r:embed="{rid}"/></pic:blipFill><a:spPr><a:xfrm>'
            f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm></a:spPr></pic:pic>'
            "</a:graphicData></a:graphic></wp:inline></w:drawing>"
            "</w:r></w:p>")


def _doc():
    return document(
        para(run("Figure 1. Average AFI by country"))
        + drawing("rId7")
        + para(run("Source: authors."))
        + para(run("Figure 2. Lorenz curves"))
        + drawing("rId8") + drawing("rId9") + drawing("rId10")
        + para(run("Figure 10. Shares a relationship with Figure 2"))
        + drawing("rId8"))


RELS = ('<Relationships><Relationship Id="rId7" Target="media/image1.png"/>'
        '<Relationship Id="rId8" Target="media/image2.png"/>'
        '<Relationship Id="rId9" Target="media/image3.png"/>'
        '<Relationship Id="rId10" Target="media/image4.png"/>'
        "</Relationships>")


def _parts(doc=None):
    parts = make_parts("")
    parts["word/document.xml"] = (doc or _doc()).encode("utf-8")
    parts["word/_rels/document.xml.rels"] = RELS.encode("utf-8")
    for i in (1, 2, 3, 4):
        parts[f"word/media/image{i}.png"] = png(400, 300)
    return parts


def test_caption_sits_above_its_figure():
    """Mapping a caption to the nearest drawing BEFORE it gets every
    figure wrong by one."""
    fig = find(_doc(), "Figure 1.")
    assert fig.embeds == ["rId7"]


def test_one_figure_can_be_several_images():
    """AFI's Figure 6 is three Lorenz curves, so image indices and figure
    numbers do not correspond."""
    fig = find(_doc(), "Figure 2.")
    assert fig.embeds == ["rId8", "rId9", "rId10"]


def test_find_all_returns_every_caption():
    figs = find_all(_doc())
    assert [f.number for f in figs] == ["1", "2", "10"]


def test_a_prefix_that_matches_two_captions_is_refused():
    """'Figure 1' also prefixes 'Figure 10' — the dot matters."""
    with pytest.raises(AnchorError, match="2 captions start"):
        find(_doc(), "Figure 1")


def test_missing_caption_is_reported():
    with pytest.raises(AnchorError, match="no caption starting"):
        find(_doc(), "Figure 99.")


def test_shared_relationships_are_counted():
    """The AFI Figures 8/11/12 situation: one image behind three
    drawings."""
    assert shared_relationships(_doc())["rId8"] == 2
    assert shared_relationships(_doc())["rId7"] == 1


def test_replacing_a_shared_image_is_refused_by_default(tmp_path):
    """Rewriting the bytes would change Figure 10 as well."""
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    with pytest.raises(AnchorError, match="drawings share"):
        replace_image(_parts(), "Figure 2.", new)


def test_isolating_leaves_the_sibling_figure_untouched(tmp_path):
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    parts = _parts()
    target = replace_image(parts, "Figure 2.", new, isolate=True)

    assert parts[target] == png(800, 400)
    # the shared image is untouched, and Figure 10 still points at it
    assert parts["word/media/image2.png"] == png(400, 300)
    doc = parts["word/document.xml"].decode("utf-8")
    assert find(doc, "Figure 10.").embeds == ["rId8"]
    assert find(doc, "Figure 2.").embeds[0] != "rId8"


def test_isolating_registers_a_new_relationship(tmp_path):
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    parts = _parts()
    replace_image(parts, "Figure 2.", new, isolate=True)
    rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
    doc = parts["word/document.xml"].decode("utf-8")
    rid = find(doc, "Figure 2.").embeds[0]
    assert f'Id="{rid}"' in rels, "the new drawing points at nothing"


def test_replacing_an_unshared_image_writes_over_its_media(tmp_path):
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    parts = _parts()
    target = replace_image(parts, "Figure 1.", new)
    assert target == "word/media/image1.png"
    assert parts[target] == png(800, 400)


def test_replacement_keeps_the_width_and_fixes_the_height(tmp_path):
    """Otherwise Word stretches the new image to the old box."""
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 200))            # 4:1
    parts = _parts()
    replace_image(parts, "Figure 1.", new)
    doc = parts["word/document.xml"].decode("utf-8")
    cx, cy = (int(v) for v in
              __import__("re").search(r'<wp:extent cx="(\d+)" cy="(\d+)"',
                                      doc).groups())
    assert cx == 5486400                      # unchanged
    assert cy == round(cx / 4)                # follows the new aspect


def test_a_non_png_is_reported_clearly(tmp_path):
    bad = tmp_path / "not.png"
    bad.write_bytes(b"GIF89a")
    with pytest.raises(PackageError, match="not a PNG"):
        replace_image(_parts(), "Figure 1.", bad)


def test_missing_image_file_is_reported(tmp_path):
    with pytest.raises(PackageError, match="image not found"):
        replace_image(_parts(), "Figure 1.", tmp_path / "absent.png")


def test_set_extent_touches_only_its_own_block():
    """A document-wide regex would resize every other figure too."""
    doc = _doc()
    block = drawing("rId7")
    resized = set_extent(block, 111, 222)
    assert 'cx="111" cy="222"' in resized
    assert resized.count('cx="111"') == 2      # wp:extent and a:ext
    assert 'cx="5486400"' in doc               # the document is unchanged


def test_scale_to_width_uses_the_image_aspect(tmp_path):
    img = tmp_path / "i.png"
    img.write_bytes(png(1000, 250))
    out = scale_to_width(drawing("rId7"), img, 6.5)
    cx = round(6.5 * EMU_PER_INCH)
    assert f'cx="{cx}" cy="{round(cx / 4)}"' in out


def test_landscape_swaps_the_page_and_sets_orient():
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440"/></w:sectPr>')
    out = landscape(sect)
    assert 'w:w="16838" w:h="11906"' in out
    assert 'w:orient="landscape"' in out
    assert "<w:pgMar" in out, "margins must carry over"


def test_section_properties_returns_the_body_sectpr():
    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
    doc = document(para(run("body")) + sect)
    assert section_properties(doc) == sect


def test_landscape_rejects_a_sectpr_without_page_size():
    with pytest.raises(AnchorError, match="no w:pgSz"):
        landscape("<w:sectPr><w:pgMar w:top='1440'/></w:sectPr>")
