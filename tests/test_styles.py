"""styles — template application with the dangling-reference audit."""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit.errors import PackageError
from docxkit.styles import apply_template, ensure, read, used


def style(sid: str, name: str, *, kind: str = "paragraph",
          based_on: str | None = None) -> str:
    base = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    return (f'<w:style w:type="{kind}" w:styleId="{sid}">'
            f'<w:name w:val="{name}"/>{base}</w:style>')


def styles_part(*defs: str) -> bytes:
    return f"<w:styles {NS}>{''.join(defs)}</w:styles>".encode()


def doc_part(body: str) -> bytes:
    return (f"<w:document {NS}><w:body>{body}</w:body></w:document>"
            ).encode()


def make_parts() -> dict[str, bytes]:
    body = ('<w:p><w:pPr><w:pStyle w:val="MyHeading"/></w:pPr>'
            '<w:r><w:rPr><w:rStyle w:val="MyEmphasis"/></w:rPr>'
            "<w:t>x</w:t></w:r></w:p>"
            '<w:tbl><w:tblPr><w:tblStyle w:val="MyTable"/></w:tblPr>'
            "<w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>")
    return {
        "word/document.xml": doc_part(body),
        "word/styles.xml": styles_part(
            style("MyHeading", "My Heading"),
            style("MyEmphasis", "My Emphasis", kind="character"),
            style("MyTable", "My Table", kind="table")),
        "word/footnotes.xml": (
            f'<w:footnotes {NS}><w:footnote w:id="2"><w:p><w:pPr>'
            f'<w:pStyle w:val="MyNote"/></w:pPr></w:p></w:footnote>'
            f"</w:footnotes>").encode(),
    }


TEMPLATE = {"word/styles.xml": styles_part(
    style("JnlHeading", "Journal Heading"),
    style("JnlNote", "Journal Note"),
    style("MyEmphasis", "Emphasis", kind="character"))}


def test_read_parses_id_name_type_and_base():
    styles = read(make_parts())
    by_id = {s.sid: s for s in styles}
    assert by_id["MyHeading"].name == "My Heading"
    assert by_id["MyTable"].type == "table"


def test_used_sees_all_three_reference_kinds():
    xml = make_parts()["word/document.xml"].decode("utf-8")
    assert used(xml) == {"MyHeading", "MyEmphasis", "MyTable"}


def test_apply_template_remaps_and_reports_the_dangling():
    parts = make_parts()
    report = apply_template(parts, TEMPLATE,
                            remap={"MyHeading": "JnlHeading",
                                   "MyNote": "JnlNote"})
    doc = parts["word/document.xml"].decode("utf-8")
    notes = parts["word/footnotes.xml"].decode("utf-8")
    assert 'w:pStyle w:val="JnlHeading"' in doc
    assert 'w:pStyle w:val="JnlNote"' in notes
    assert report.remapped == {"MyHeading": 1, "MyNote": 1}
    # MyEmphasis exists in the template under the same id: not missing.
    # MyTable was neither remapped nor defined: the audit must say so.
    assert report.missing == ["MyTable"]


def test_a_chainable_remap_does_not_chain():
    parts = {
        "word/document.xml": doc_part(
            '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="B"/></w:pPr></w:p>'),
        "word/styles.xml": styles_part(style("A", "a"), style("B", "b")),
    }
    template = {"word/styles.xml": styles_part(style("B", "b"),
                                               style("C", "c"))}
    apply_template(parts, template, remap={"A": "B", "B": "C"})
    doc = parts["word/document.xml"].decode("utf-8")
    assert 'w:val="B"' in doc and 'w:val="C"' in doc


def test_template_without_styles_refuses():
    with pytest.raises(PackageError, match="template"):
        apply_template(make_parts(), {})


def test_ensure_appends_once():
    parts = make_parts()
    new = style("CaptionX", "Caption X")
    assert ensure(parts, new) is True
    assert ensure(parts, new) is False
    assert parts["word/styles.xml"].decode("utf-8").count(
        'w:styleId="CaptionX"') == 1
