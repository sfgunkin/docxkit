"""Constructing body content: runs, paragraphs, tables, insertion."""
from __future__ import annotations

import xml.dom.minidom as MD

import pytest
from conftest import document
from conftest import para as fpara
from conftest import run as frun

from docxkit.body import (
    cell,
    insert_after,
    insert_before,
    para,
    row,
    run,
    table,
)
from docxkit.errors import AnchorError

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"')


def _wellformed(fragment: str) -> None:
    MD.parseString(
        f"<w:document {NS}><w:body>{fragment}</w:body></w:document>")


# ------------------------------------------------------------------ runs ---

def test_run_escapes_text():
    assert "R&amp;D" in run("R&D spending")
    assert "<w:t>" in run("plain")


def test_run_preserves_edge_whitespace():
    """A bare <w:t> loses edge space on every Word save; the builder must
    not emit one."""
    assert 'xml:space="preserve"' in run(" leading")
    assert 'xml:space="preserve"' in run("trailing ")
    assert 'xml:space="preserve"' not in run("neither")


def test_run_carries_run_properties():
    assert "<w:b/>" in run("bold", "<w:rPr><w:b/></w:rPr>")


# ------------------------------------------------------------ paragraphs ---

def test_para_wraps_content_and_is_wellformed():
    p = para(run("hello"))
    assert p.startswith("<w:p>") and p.endswith("</w:p>")
    _wellformed(p)


def test_para_accepts_ready_made_xml_not_text():
    """`content` is XML so an equation can be placed directly."""
    p = para('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
             'officeDocument/2006/math"/>')
    assert "<m:oMath" in p


# ---------------------------------------------------------------- tables ---

def test_table_shape_and_wellformedness():
    t = table(["Country", "50+", "60+"],
              [["Albania", "-0.6", "+1.7"], ["Croatia", "-0.7", "+1.6"]])
    assert t.count("<w:tr>") == 3          # header + 2 rows
    assert t.count("<w:gridCol") == 3
    assert "Albania" in t and "+1.7" in t
    _wellformed(t)


def test_table_header_row_repeats_across_pages():
    t = table(["a"], [["1"]])
    assert "<w:tblHeader/>" in t


def test_table_grouped_headers_span_columns():
    t = table(["Country", "Gap", "OASI"], [["Albania"] + ["x"] * 6],
              spans=[1, 3, 3])
    assert '<w:gridSpan w:val="3"/>' in t
    assert t.count("<w:gridCol") == 7
    _wellformed(t)


def test_table_rejects_ragged_rows():
    """A short row in a results table means the caller lost a value."""
    with pytest.raises(AnchorError, match="row 0 has 2 cells"):
        table(["a", "b", "c"], [["1", "2"]])


def test_table_rejects_mismatched_spans():
    with pytest.raises(AnchorError, match="2 headers but 3 spans"):
        table(["a", "b"], [["1", "2"]], spans=[1, 1, 1])


def test_table_cells_are_escaped():
    t = table(["a"], [["R&D <fine>"]])
    assert "R&amp;D &lt;fine&gt;" in t


def test_cell_wraps_bare_text_in_a_paragraph():
    """A w:tc with no w:p makes Word declare the document unreadable."""
    assert "<w:p>" in cell("text")


def test_cell_passes_through_ready_made_paragraphs():
    assert cell(para(run("x"))).count("<w:p>") == 1


def test_row_marks_header_only_when_asked():
    assert "<w:tblHeader/>" in row([cell("a")], header=True)
    assert "<w:tblHeader/>" not in row([cell("a")])


# ------------------------------------------------------------- insertion ---

def test_insert_after_places_content_following_the_anchor():
    xml = document(fpara(frun("first")) + fpara(frun("second")))
    out = insert_after(xml, "first", para(run("INSERTED")))
    assert out.index("INSERTED") > out.index("first")
    assert out.index("INSERTED") < out.index("second")


def test_insert_before_places_content_ahead_of_the_anchor():
    xml = document(fpara(frun("first")) + fpara(frun("second")))
    out = insert_before(xml, "second", para(run("INSERTED")))
    assert out.index("first") < out.index("INSERTED") < out.index("second")


def test_insert_after_refuses_to_split_a_colon_from_what_it_introduces():
    """A lead-in ending in ':' introduces the block after it; inserting
    between them silently orphans the sentence from its equation."""
    xml = document(fpara(frun("is defined as:")) + fpara(frun("EQUATION")))
    with pytest.raises(AnchorError, match="ends in a colon"):
        insert_after(xml, "is defined as", para(run("X")))


def test_insert_after_colon_override_is_available():
    xml = document(fpara(frun("is defined as:")) + fpara(frun("EQUATION")))
    out = insert_after(xml, "is defined as", para(run("X")), allow_colon=True)
    assert "X" in out


def test_insert_after_requires_a_unique_anchor():
    xml = document(fpara(frun("same")) + fpara(frun("same")))
    with pytest.raises(AnchorError):
        insert_after(xml, "same", para(run("X")))


def test_insert_helpers_can_match_through_typography():
    """Anchors written with a straight apostrophe must find the curly one."""
    xml = document(fpara(frun("workers’ productivity")) + fpara(frun("next")))
    with pytest.raises(AnchorError):
        insert_after(xml, "workers' productivity", para(run("X")))
    out = insert_after(xml, "workers' productivity", para(run("X")),
                       normalize=True)
    assert "X" in out


def test_table_applies_cell_paragraph_properties():
    t = table(["a"], [["1"]], cell_ppr='<w:pPr><w:jc w:val="left"/></w:pPr>')
    assert t.count('<w:jc w:val="left"/>') == 2      # header + body cell
