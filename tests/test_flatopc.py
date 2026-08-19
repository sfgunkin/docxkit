"""The Flat OPC repacker — Word's save-hang bypass, without needing Word.

This path had no coverage: it only ran inside the Word pipeline, so a
regression would have surfaced as a corrupt deliverable. The Flat OPC
format is plain XML, so it can be exercised directly.
"""
from __future__ import annotations

import base64
import zipfile

import pytest

from docxkit.errors import PackageError
from docxkit.word import flat_opc_to_docx

PKG = "http://schemas.microsoft.com/office/2006/xmlPackage"
DOC_CT = ("application/vnd.openxmlformats-officedocument."
          "wordprocessingml.document.main+xml")
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# a part payload must be self-contained XML: Word declares the namespace
# on the part root, so the fixture does too
DOC_XML = f'<w:document xmlns:w="{W_NS}"/>'
EXTRA_XML = f'<w:extra xmlns:w="{W_NS}"/>'


def _flat(parts_xml: str) -> str:
    return (f'<?xml version="1.0" standalone="yes"?>'
            f'<pkg:package xmlns:pkg="{PKG}">{parts_xml}</pkg:package>')


def _xml_part(name: str, ctype: str, payload: str) -> str:
    return (f'<pkg:part pkg:name="{name}" pkg:contentType="{ctype}">'
            f"<pkg:xmlData>{payload}</pkg:xmlData></pkg:part>")


def _bin_part(name: str, ctype: str, blob: bytes) -> str:
    b64 = base64.b64encode(blob).decode("ascii")
    return (f'<pkg:part pkg:name="{name}" pkg:contentType="{ctype}">'
            f"<pkg:binaryData>{b64}</pkg:binaryData></pkg:part>")


@pytest.fixture
def flat_file(tmp_path):
    def make(parts_xml: str):
        p = tmp_path / "flat.xml"
        p.write_text(_flat(parts_xml), encoding="utf-8")
        return p
    return make


def test_repacks_xml_and_binary_parts(flat_file, tmp_path):
    flat = flat_file(
        _xml_part("/word/document.xml", DOC_CT, DOC_XML)
        + _bin_part("/word/media/image1.png", "image/png", b"\x89PNG\r\n"))
    out = tmp_path / "out.docx"
    assert flat_opc_to_docx(flat, out) == 2

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "[Content_Types].xml" in names
        assert "word/document.xml" in names
        assert z.read("word/media/image1.png") == b"\x89PNG\r\n"
        assert b"w:document" in z.read("word/document.xml")


def test_writes_a_content_types_override_for_each_part(flat_file, tmp_path):
    flat = flat_file(_xml_part("/word/document.xml", DOC_CT, DOC_XML))
    out = tmp_path / "out.docx"
    flat_opc_to_docx(flat, out)
    with zipfile.ZipFile(out) as z:
        ct = z.read("[Content_Types].xml").decode("utf-8")
    assert 'PartName="/word/document.xml"' in ct
    assert DOC_CT in ct
    assert 'Extension="png"' in ct          # defaults are always present


def test_relationship_parts_get_no_override(flat_file, tmp_path):
    """Rels are covered by the Default for the .rels extension; adding an
    Override as well makes Word reject the package."""
    rel_ct = "application/vnd.openxmlformats-package.relationships+xml"
    flat = flat_file(
        _xml_part("/word/document.xml", DOC_CT, DOC_XML)
        + _xml_part("/word/_rels/document.xml.rels", rel_ct,
                    "<Relationships/>"))
    out = tmp_path / "out.docx"
    flat_opc_to_docx(flat, out)
    with zipfile.ZipFile(out) as z:
        ct = z.read("[Content_Types].xml").decode("utf-8")
    assert 'PartName="/word/_rels/document.xml.rels"' not in ct
    assert 'Extension="rels"' in ct


def test_declares_the_xml_declaration_on_xml_parts(flat_file, tmp_path):
    flat = flat_file(_xml_part("/word/document.xml", DOC_CT, DOC_XML))
    out = tmp_path / "out.docx"
    flat_opc_to_docx(flat, out)
    with zipfile.ZipFile(out) as z:
        assert z.read("word/document.xml").startswith(b"<?xml version=")


def test_rejects_something_that_is_not_a_flat_opc_package(tmp_path):
    p = tmp_path / "nope.xml"
    p.write_text("<html><body>not a package</body></html>", encoding="utf-8")
    with pytest.raises(PackageError, match="no pkg:part"):
        flat_opc_to_docx(p, tmp_path / "out.docx")


def test_rejects_a_part_with_no_name(flat_file, tmp_path):
    # Without the explicit check this crashed as AttributeError on
    # None.lstrip, not as a PackageError naming the actual problem.
    flat = flat_file(f'<pkg:part pkg:contentType="{DOC_CT}">'
                     f"<pkg:xmlData>{DOC_XML}</pkg:xmlData></pkg:part>")
    with pytest.raises(PackageError, match="missing its pkg:name"):
        flat_opc_to_docx(flat, tmp_path / "out.docx")


def test_rejects_a_part_with_neither_payload(flat_file, tmp_path):
    flat = flat_file('<pkg:part pkg:name="/word/document.xml" '
                     f'pkg:contentType="{DOC_CT}"/>')
    with pytest.raises(PackageError, match="neither xmlData nor binaryData"):
        flat_opc_to_docx(flat, tmp_path / "out.docx")


def test_rejects_a_part_with_NO_xml_root(flat_file, tmp_path):
    """The other side of `len(children) != 1`, and the side that raises
    from somewhere else entirely: as `> 1` an EMPTY `pkg:xmlData` walks
    past the check and into `children[0]`, so what the caller gets is an
    IndexError from inside the reader rather than the sentence naming
    the part Word wrote wrong."""
    flat = flat_file(_xml_part("/word/document.xml", DOC_CT, ""))
    with pytest.raises(PackageError, match="expected 1 xmlData child"):
        flat_opc_to_docx(flat, tmp_path / "out.docx")


def test_rejects_a_part_with_multiple_xml_roots(flat_file, tmp_path):
    """And the guard is what makes its neighbour equivalent: the line
    under it reads `children[0]`, which cannot be told from
    `children[-1]` once exactly one child is the only shape that gets
    past here. Argued rather than tested (`tools/kill_check.py`,
    expect_kill=False)."""
    flat = flat_file(_xml_part("/word/document.xml", DOC_CT,
                               DOC_XML + EXTRA_XML))
    with pytest.raises(PackageError, match="expected 1 xmlData child"):
        flat_opc_to_docx(flat, tmp_path / "out.docx")
