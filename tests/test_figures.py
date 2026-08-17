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


# --- what the first mutation run found (2026-08-17, 30.8 %, 201 alive) ---
#
# Half of those survivors were the drawing WINDOW — `paras[i + 1:i + 1 +
# _DRAWING_WINDOW]`, written out five times, none of it asserted by
# value. Writing the tests found that only one of the five copies
# stopped at the next caption, so `find` could hand back a neighbour's
# image; the walk is now one function and the tests hold its edges.

def test_a_drawing_in_the_LAST_paragraph_of_the_window_belongs_to_the_figure():
    """Six paragraphs after the caption. A figure whose image sits
    behind a source note, a spacer and a panel label is ordinary, and
    a window one short drops it from the paper's figure list."""
    xml = document(para(run("Figure 1. Average AFI by country"))
                   + para(run("spacer")) * 5
                   + drawing("rId7"))

    figure, = find_all(xml)

    assert figure.embeds == ["rId7"]


def test_a_drawing_JUST_PAST_the_window_is_not_the_figures():
    """...and the window has to end somewhere, or a figure adopts
    whatever image appears later in the section."""
    xml = document(para(run("Figure 1. Average AFI by country"))
                   + para(run("spacer")) * 6
                   + drawing("rId7"))

    figure, = find_all(xml)

    assert figure.embeds == []


def test_the_CAPTION_paragraph_itself_is_not_searched():
    """The window opens at the paragraph AFTER the caption. A caption
    that happens to carry an inline image — a small panel letter — is
    still a caption, and off-by-one here reads it as the figure."""
    caption = ('<w:p><w:r><w:t>Figure 1. Average AFI</w:t></w:r>'
               '<w:r><w:drawing><wp:inline><a:blip r:embed="rIdCAPTION"/>'
               "</wp:inline></w:drawing></w:r></w:p>")
    xml = document(caption + drawing("rId7"))

    figure, = find_all(xml)

    assert figure.embeds == ["rId7"]


def test_a_figure_with_NO_image_does_not_adopt_the_NEXT_figures():
    """The defect the five copies of this walk disagreed about: only
    `alt_texts` stopped at the next caption. A figure whose own drawing
    is missing — the panel that failed to embed, the placeholder a
    co-author left — took the following figure's, and every caller
    downstream believed it: `set_alt_text` would describe Figure 2's
    picture under Figure 1, and the accessibility check would report
    both as done.
    """
    xml = document(para(run("Figure 1. The one that lost its image"))
                   + para(run("Figure 2. Average AFI by country"))
                   + drawing("rId7"))

    first, second = find_all(xml)

    assert first.embeds == []
    assert second.embeds == ["rId7"]
    assert find(xml, "Figure 1.").embeds == []


def test_a_MULTI_IMAGE_figure_keeps_its_drawings_in_document_order():
    """AFI's Figure 5 is three Lorenz curves; each needs its own alt
    text, addressed by position."""
    xml = document(para(run("Figure 5. Three panels"))
                   + drawing("rIdA") + drawing("rIdB") + drawing("rIdC"))

    figure, = find_all(xml)

    assert figure.embeds == ["rIdA", "rIdB", "rIdC"]


def test_the_drawings_END_at_the_first_paragraph_without_one():
    """Prose after the panels is not another panel: once a figure's
    drawings have started, the first paragraph without one closes it."""
    xml = document(para(run("Figure 5. Two panels"))
                   + drawing("rIdA")
                   + para(run("Source: authors' calculations."))
                   + drawing("rIdSTRAY"))

    figure, = find_all(xml)

    assert figure.embeds == ["rIdA"]


def test_a_drawing_BEFORE_any_caption_belongs_to_no_figure():
    xml = document(drawing("rIdLOGO")
                   + para(run("Figure 1. Average AFI"))
                   + drawing("rId7"))

    figure, = find_all(xml)

    assert figure.embeds == ["rId7"]


def test_an_INCH_is_914400_EMU():
    """The scaling test computes its expected width FROM this constant,
    so a mutation moves both sides together and the test cannot see it.
    An inch is an inch: state the number."""
    assert EMU_PER_INCH == 914400


def test_scale_to_width_gives_a_six_inch_drawing_its_EMU(tmp_path):
    img = tmp_path / "i.png"
    img.write_bytes(png(1000, 500))

    out = scale_to_width(drawing("rId7"), img, 6.0)

    assert 'cx="5486400" cy="2743200"' in out


def test_a_replaced_image_keeps_its_WIDTH_and_ROUNDS_the_height(tmp_path):
    """`round`, not floor. The rounding is a single EMU and no reader
    could see it; stating it is how the arithmetic stays the arithmetic
    that was chosen, in a function whose whole job is not to stretch the
    author's picture."""
    new = tmp_path / "new.png"
    new.write_bytes(png(7, 2))
    parts = _parts()

    replace_image(parts, "Figure 1.", new)

    doc = parts["word/document.xml"].decode("utf-8")
    cx = 5486400
    assert f'cx="{cx}" cy="1567543"' in doc          # round(cx * 2 / 7)
    assert f'cx="{cx}" cy="{cx * 2 // 7}"' not in doc


def test_isolating_takes_the_NEXT_free_media_number(tmp_path):
    """image1..image4 exist, so the new part is image5 — not a name that
    overwrites one of them, which is the whole point of isolating."""
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    parts = _parts()

    target = replace_image(parts, "Figure 2.", new, isolate=True)

    assert target == "word/media/image5.png"


def test_isolating_takes_the_NEXT_free_RELATIONSHIP_id(tmp_path):
    """rId7..rId10 are taken, so the new one is rId11. Reusing a live id
    would point another drawing at this figure's image."""
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    parts = _parts()

    replace_image(parts, "Figure 2.", new, isolate=True)

    doc = parts["word/document.xml"].decode("utf-8")
    assert find(doc, "Figure 2.").embeds[0] == "rId11"


def test_isolate_on_an_UNSHARED_image_still_writes_over_its_media(tmp_path):
    """`uses > 1 and isolate`, not `or`: isolate answers the question
    "what about the other drawings", and with no other drawings there is
    nothing to isolate from. Making a second copy would leave the
    original media part orphaned in the package."""
    new = tmp_path / "new.png"
    new.write_bytes(png(800, 400))
    parts = _parts()
    before = {n for n in parts if n.startswith("word/media/")}

    target = replace_image(parts, "Figure 1.", new, isolate=True)

    assert target == "word/media/image1.png"
    assert {n for n in parts if n.startswith("word/media/")} == before


def test_the_next_relationship_id_is_one_PAST_the_highest():
    """Tested here rather than only through `replace_image`, because
    the fixture's highest id is even and `max | 1` reads the same on an
    even number — the parity of a fixture is not a proof."""
    from docxkit.figures import _next_rid

    assert _next_rid('<Relationships><Relationship Id="rId11"/>'
                     '<Relationship Id="rId3"/></Relationships>') == "rId12"


def test_the_next_relationship_id_in_an_EMPTY_rels_is_rId1():
    """rId0 is not a name Word writes, and starting there would collide
    with nothing today and everything the first time one is added."""
    from docxkit.figures import _next_rid

    assert _next_rid("<Relationships></Relationships>") == "rId1"


def test_the_next_media_part_is_one_PAST_the_highest(tmp_path):
    from docxkit.figures import _new_media_part

    parts = {"word/media/image5.png": b"x", "word/media/image2.png": b"y"}

    assert _new_media_part(parts, b"z") == "word/media/image6.png"


def test_the_first_media_part_in_a_package_with_none_is_image1():
    from docxkit.figures import _new_media_part

    assert _new_media_part({}, b"z") == "word/media/image1.png"
