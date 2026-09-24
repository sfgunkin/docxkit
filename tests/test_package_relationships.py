"""`package` — the relationship and the content type a NEW part needs.

`figures.embed_image` and `pages.number` both add parts, and both answer
to the same two files. Each shape these must survive is one a paper's
hand-rolled copy did not.
"""
from __future__ import annotations

import pytest

from docxkit import package
from docxkit.errors import PackageError

CT = package.CONTENT_TYPES
FOOTER = ("application/vnd.openxmlformats-officedocument."
          "wordprocessingml.footer+xml")
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/x"


def test_the_rels_part_of_a_part_is_named_beside_it():
    assert package.rels_name("word/document.xml") == \
        "word/_rels/document.xml.rels"
    assert package.rels_name("word/header2.xml") == \
        "word/_rels/header2.xml.rels"


def test_a_relationship_gets_the_NEXT_free_id_whatever_the_order():
    parts = {"word/_rels/document.xml.rels":
             b'<Relationships><Relationship Id="rId7" Type="t" Target="a"/>'
             b'<Relationship Target="b" Id="rId3" Type="t"/></Relationships>'}

    rid = package.add_relationship(parts, "word/document.xml", REL, "x.xml")

    assert rid == "rId8"
    assert (f'<Relationship Id="rId8" Type="{REL}" Target="x.xml"/>'
            in parts["word/_rels/document.xml.rels"].decode())


def test_a_part_with_NO_rels_gets_one_and_an_EMPTY_one_is_expanded():
    fresh: dict[str, bytes] = {}
    empty = {"word/_rels/header1.xml.rels": b'<Relationships xmlns="r"/>'}

    package.add_relationship(fresh, "word/footer1.xml", REL, "media/a.png")
    package.add_relationship(empty, "word/header1.xml", REL, "media/b.png")

    assert 'Target="media/a.png"' in \
        fresh["word/_rels/footer1.xml.rels"].decode()
    got = empty["word/_rels/header1.xml.rels"].decode()
    assert got.startswith('<Relationships xmlns="r">')
    assert got.endswith("</Relationships>") and 'Target="media/b.png"' in got


def test_a_target_is_ESCAPED_into_its_attribute():
    parts: dict[str, bytes] = {}

    package.add_relationship(parts, "word/document.xml", REL, "a&b.xml")

    assert 'Target="a&amp;b.xml"' in \
        parts["word/_rels/document.xml.rels"].decode()


@pytest.mark.parametrize("types", [b"<Types/>", b'<Types xmlns="t"/>',
                                   b'<Types xmlns="t"></Types>'])
def test_a_default_and_an_override_are_added_ONCE_to_any_Types(types):
    parts = {CT: types}

    added = [package.declare_default(parts, "png", "image/png"),
             package.declare_default(parts, "PNG", "image/png"),
             package.declare_override(parts, "word/footer3.xml", FOOTER),
             package.declare_override(parts, "/word/footer3.xml", FOOTER)]

    xml = parts[CT].decode()
    assert added == [True, False, True, False]
    assert xml.count("<Default ") == 1 and xml.count("<Override ") == 1
    assert 'PartName="/word/footer3.xml"' in xml
    assert xml.endswith("</Types>")


def test_a_package_with_no_Content_Types_is_refused():
    with pytest.raises(PackageError, match=r"\[Content_Types\]"):
        package.declare_default({}, "png", "image/png")
