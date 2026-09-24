"""`figures.embed_image` — a NEW picture, and everything outside the run.

The run is the easy half. What Health's hand-rolled insert got wrong was
the rest: an extent fixed whatever the picture, a guessed drawing id,
and no Content_Types Default — a package that declares no `png` does
not open. Each of those is a test here.
"""
from __future__ import annotations

import re
import struct
import zlib

import pytest
from conftest import make_parts, para, run

from docxkit import body, figures
from docxkit._xml import DOCUMENT
from docxkit.errors import PackageError
from docxkit.lint import lint_parts

RELS = "word/_rels/document.xml.rels"
CT = "[Content_Types].xml"


def png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)))


def jpeg(width: int, height: int) -> bytes:
    """SOI, an APP0 segment to walk past, then a baseline frame header."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = (b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1)
           + b"\x01\x11\x00")
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def drawing_para(rid: str, pid: int) -> str:
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:docPr id="{pid}" '
            f'name="P"/><a:blip r:embed="{rid}"/></wp:inline></w:drawing>'
            f"</w:r></w:p>")


def rid_of(run_xml: str) -> str:
    m = re.search(r'r:embed="([^"]+)"', run_xml)
    assert m, run_xml[:80]
    return m.group(1)


def pid_of(run_xml: str) -> str:
    m = re.search(r'<wp:docPr id="(\d+)"', run_xml)
    assert m, run_xml[:80]
    return m.group(1)


def extent(run_xml: str) -> tuple[int, int]:
    m = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', run_xml)
    assert m
    return int(m.group(1)), int(m.group(2))


def test_the_extent_follows_the_PICTURES_aspect():
    parts = make_parts(para(run("Text.")))

    got = figures.embed_image(parts, png(1500, 900), width_inches=5.0)

    cx, cy = extent(got)
    assert cx == 5 * figures.EMU_PER_INCH
    assert cy == round(cx * 900 / 1500)
    assert f'<a:ext cx="{cx}" cy="{cy}"/>' in got


def test_the_media_part_the_relationship_and_the_TYPE_are_all_written():
    parts = make_parts(para(run("Text.")))

    got = figures.embed_image(parts, png(3, 5), width_inches=2)

    assert parts["word/media/image1.png"] == png(3, 5)
    rid = rid_of(got)
    rels = parts[RELS].decode()
    assert re.search(rf'Id="{rid}"[^>]*Target="media/image1.png"', rels)
    assert '<Default Extension="png" ContentType="image/png"/>' in \
        parts[CT].decode()


def test_an_extension_ALREADY_declared_is_not_declared_twice():
    parts = make_parts(para(run("Text.")))
    parts[CT] = (b'<Types xmlns="x"><Default Extension="PNG" '
                 b'ContentType="image/png"/></Types>')

    figures.embed_image(parts, png(3, 5), width_inches=2)

    assert parts[CT].decode().lower().count('extension="png"') == 1


def test_a_JPEG_is_named_and_typed_as_one():
    parts = make_parts(para(run("Text.")))

    got = figures.embed_image(parts, jpeg(640, 480), width_inches=4)

    assert "word/media/image1.jpeg" in parts
    assert 'ContentType="image/jpeg"' in parts[CT].decode()
    cx, cy = extent(got)
    assert cy == round(cx * 480 / 640)


def test_the_drawing_id_is_one_PAST_every_id_in_the_package():
    """Headers count: Word wants a docPr id unique across the document."""
    parts = make_parts(drawing_para("rId3", 3) + drawing_para("rId5", 7))
    parts["word/header1.xml"] = (
        b'<w:hdr><wp:docPr id="11" name="Logo"/></w:hdr>')

    got = figures.embed_image(parts, png(3, 5), width_inches=1)

    assert '<wp:docPr id="12" ' in got and '<pic:cNvPr id="12" ' in got


def test_three_embeds_get_three_ids_three_parts_three_relationships():
    parts = make_parts(para(run("Text.")))

    runs = [figures.embed_image(parts, png(3, 5), width_inches=1)
            for _ in range(3)]

    rids = {rid_of(r) for r in runs}
    pids = {pid_of(r) for r in runs}
    assert len(rids) == len(pids) == 3
    assert {n for n in parts if n.startswith("word/media/")} == {
        f"word/media/image{i}.png" for i in (1, 2, 3)}


def test_placing_SOME_embeds_between_calls_still_never_reuses_an_id():
    """Embed two, place only the SECOND, embed a third. The ids in the
    XML and the pending relationships have to add up to fresh ones."""
    parts = make_parts(para(run("Anchor.")))
    first = figures.embed_image(parts, png(3, 5), width_inches=1)
    second = figures.embed_image(parts, png(3, 5), width_inches=1)
    doc = parts[DOCUMENT].decode()
    parts[DOCUMENT] = body.insert_after(doc, "Anchor",
                                        body.para(second)).encode()

    third = figures.embed_image(parts, png(3, 5), width_inches=1)

    ids = [pid_of(r) for r in (first, second, third)]
    assert len(set(ids)) == 3, ids


def test_an_EMPTY_rels_part_is_expanded_rather_than_written_past():
    parts = make_parts(para(run("Text.")))
    parts[RELS] = b'<Relationships xmlns="x"/>'

    figures.embed_image(parts, png(3, 5), width_inches=1)

    assert "<Relationship Id=" in parts[RELS].decode()


def test_a_HEADER_picture_goes_in_the_headers_own_rels():
    parts = make_parts(para(run("Text.")))
    parts["word/header1.xml"] = b"<w:hdr/>"

    figures.embed_image(parts, png(3, 5), width_inches=1,
                        part="word/header1.xml")

    rels = parts["word/_rels/header1.xml.rels"].decode()
    assert 'Target="media/image1.png"' in rels
    assert RELS not in parts


def test_alt_text_and_name_are_ESCAPED_into_the_attributes():
    parts = make_parts(para(run("Text.")))

    got = figures.embed_image(parts, png(3, 5), width_inches=1,
                              alt='Wages & "prices" < 5', name="Fig 1")

    assert 'descr="Wages &amp; &quot;prices&quot; &lt; 5"' in got
    assert 'name="Fig 1"' in got


def test_NO_alt_text_leaves_it_missing_for_alt_texts_to_report():
    parts = make_parts(para(run("Text.")))
    got = figures.embed_image(parts, png(3, 5), width_inches=1)

    doc = parts[DOCUMENT].decode().replace(
        "</w:body>", body.para(run("Figure 1. Wages.")) + body.para(got)
        + "</w:body>")

    assert "descr=" not in got
    assert [a.missing for a in figures.alt_texts(doc)] == [True]


def test_the_placed_figure_LINTS_clean():
    parts = make_parts(para(run("Before the figure.")))
    got = figures.embed_image(parts, png(1200, 800), width_inches=6,
                              alt="A chart")

    doc = parts[DOCUMENT].decode()
    parts[DOCUMENT] = body.insert_after(
        doc, "Before the figure", body.para(got)).encode()

    assert lint_parts(parts) == []


@pytest.mark.parametrize("blob", [b"GIF89a....", b"%PDF-1.7", b""])
def test_anything_but_a_PNG_or_a_JPEG_is_refused(blob):
    parts = make_parts(para(run("Text.")))

    with pytest.raises(PackageError, match="PNG or a JPEG"):
        figures.embed_image(parts, blob, width_inches=1)
    assert not any(n.startswith("word/media/") for n in parts)


def test_a_width_that_is_not_one_is_refused():
    with pytest.raises(ValueError, match="not a width"):
        figures.embed_image(make_parts(para(run("x"))), png(3, 5),
                            width_inches=0)
