"""Exhibit links can be Word FIELD form, which link/unlink cannot see.

Parental_style holds 53 element-form and 160 field-form links at once.
`unlink` reported "24 bookmarks removed" there and left every caption
link live — a wrong answer wearing a healthy number.
"""

import pytest
from conftest import make_parts, para, run

from docxkit import crossrefs
from docxkit.errors import ConversionGap


def field_link(anchor: str, shown: str) -> str:
    """A complete HYPERLINK field, as Word writes it."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">'
        f' HYPERLINK \\l "{anchor}" \\h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r><w:t>{shown}</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def doc(body: str) -> str:
    return make_parts(body)["word/document.xml"].decode("utf-8")


CAPTION_AND_MENTION = (
    para(run("As reported in ")) .replace("</w:p>", "") + field_link(
        "Table1", "Table 1") + "<w:r><w:t>, rates differ.</w:t></w:r></w:p>"
    + para(run("Table 1: Descriptive statistics.")))


def test_field_targets_finds_what_the_element_scan_misses():
    xml = doc(CAPTION_AND_MENTION)
    assert crossrefs.field_targets(xml) == {"Table1"}
    # and the element-form scan sees nothing at all
    assert 'w:anchor="Table1"' not in xml


def test_unlink_refuses_rather_than_reporting_a_healthy_count():
    xml = doc(CAPTION_AND_MENTION)
    with pytest.raises(ConversionGap) as exc:
        crossrefs.unlink(xml)
    assert "FIELD form" in str(exc.value)
    assert "Table1" in str(exc.value)


def test_unlink_still_works_on_an_ordinary_element_document():
    body = (para(run("See "))
            + para(run("Table 1: Descriptive statistics.")))
    xml = doc(body)
    linked, _ = crossrefs.link(xml)
    out, removed = crossrefs.unlink(linked)
    assert removed >= 0
    assert "FIELD" not in out


def test_link_reports_a_field_linked_object_instead_of_doubling_it():
    xml = doc(CAPTION_AND_MENTION)
    out, report = crossrefs.link(xml)
    assert report.field_form == ["Table1"]
    assert "Table1" not in report.linked
    # nothing added on top of the field
    assert out.count('w:anchor="Table1"') == 0
    assert "ALREADY LINKED BY A WORD FIELD" in report.format()
