"""Bugs found by sweeping 347 real manuscripts.

Each of these passed the synthetic suite and failed on documents nobody
wrote the rules for: survey questionnaires, Russian methodology papers,
the papers' own tracked deliverables.
"""
from __future__ import annotations

from conftest import document, ins, para, run

from docxkit.revisions import FINAL, ORIGINAL, accept, text
from docxkit.tables import read_all

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def test_a_document_with_a_byte_order_mark_is_parsed():
    """KGZ_LFS_Questionnaire.docx starts with U+FEFF. str.lstrip() does
    not remove it, so the document looked like a fragment, got wrapped,
    and then had an XML declaration in the middle of an element."""
    xml = "﻿" + document(para(run("body text")))
    assert text(xml, FINAL) == ["body text"]


def test_a_fragment_using_an_undeclared_prefix_is_parsed():
    """Fragments carry prefixes declared on the document root — wp14 on
    AFI's drawings, w16du on LE's revision dates, o and v on the survey
    questionnaires' VML. A fixed declaration list cannot keep up, and
    this broke tables.read_all on the papers' own tracked files."""
    fragment = ('<w:tbl><w:tr><w:tc><w:p><w:r>'
                '<w:t>cell</w:t></w:r>'
                '<w:drawing><wp:inline wp14:anchorId="12345678">'
                "</wp:inline></w:drawing></w:p></w:tc></w:tr></w:tbl>")
    assert read_all(fragment)[0].rows == [["cell"]]


def test_a_revision_date_prefix_does_not_break_a_table():
    """w16du:dateUtc appears on every revision Word Compare writes."""
    fragment = ('<w:tbl><w:tr><w:tc><w:p>'
                '<w:ins w:id="1" w:author="A" w:date="d" '
                'w16du:dateUtc="2026-07-29T00:00:00Z">'
                "<w:r><w:t>added</w:t></w:r></w:ins>"
                "</w:p></w:tc></w:tr></w:tbl>")
    assert read_all(fragment, view=FINAL)[0].rows == [["added"]]
    assert read_all(fragment, view=ORIGINAL)[0].rows == [[""]]


def test_nested_tables_do_not_truncate_the_outer_one():
    """Questionnaires nest tables freely. A non-greedy <w:tbl>.*?</w:tbl>
    closes on the INNER end tag, leaving a fragment that ends mid-cell —
    which then fails to parse at all."""
    inner = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>inner</w:t></w:r>"
             "</w:p></w:tc></w:tr></w:tbl>")
    outer = (f"<w:tbl><w:tr><w:tc>{inner}</w:tc></w:tr>"
             "<w:tr><w:tc><w:p><w:r><w:t>after</w:t></w:r></w:p>"
             "</w:tc></w:tr></w:tbl>")
    found = read_all(document(outer))
    assert len(found) == 1, "the outer table must be one table, not two"
    assert found[0].rows[-1] == ["after"], "the outer table was truncated"


def test_a_clean_document_short_circuits_the_transform():
    """Most manuscripts have no revisions, so accept/reject are the
    identity. Parsing a 1.7MB part to discover that cost ~20ms per call,
    per table."""
    xml = document(para(run("no revisions here")))
    assert accept(xml) is xml, "a clean document should not be re-parsed"


def test_the_short_circuit_does_not_skip_real_revisions():
    xml = document(para(run("keep "), ins("added")))
    assert accept(xml) is not xml
    assert text(xml, ORIGINAL) == ["keep "]
