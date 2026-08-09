"""The branches of `_table_layout` no fixture happened to produce.

A cosmic-ray pass over the module (2,217 mutants, 592 survivors) and
coverage agreed on where to look: six lines the whole suite never
executed, and a cluster of 34 survivors in `_set_jc` sitting on the one
alignment path a real manuscript takes most often — a paragraph that HAS
properties but states no `w:jc`.

The fixtures wrote paragraphs with no `w:pPr` at all, or with an
alignment already set. Word writes neither: a table cell out of a real
paper carries a `w:pStyle`, sometimes a `w:rPr`, and no alignment until
something sets one.
"""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit import tables
from docxkit._table_layout import (
    _AFTER_TBLLAYOUT,
    _TBLLAYOUT_RE,
    _alignment,
    _own_tblpr,
    _set_jc,
    _set_tbl_pr,
)
from docxkit.errors import AnchorError

FIXED = '<w:tblLayout w:type="fixed"/>'


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def cell(text: str, *, w: int = 1000) -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/></w:tcPr>'
            f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>")


# ------------------------------------------- an empty properties element --


def test_a_self_closing_tblpr_is_real_and_reports_no_inner():
    body = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
            "</w:tblGrid><w:tr>" + cell("x") + "</w:tr></w:tbl>")
    own = _own_tblpr(body)
    assert own is not None
    start, end, inner = own
    assert inner == ""
    assert body[start:end] == "<w:tblPr/>"


def test_a_self_closing_tblpr_is_expanded_not_duplicated():
    """Two `w:tblPr` in one `w:tbl` is schema-invalid — the same defect
    `_EDGE_RE` was widened for on `w:tcBorders`, where matching only the
    expanded form made the writer insert a second element beside the
    empty one."""
    body = ('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
            "</w:tblGrid><w:tr>" + cell("x") + "</w:tr></w:tbl>")
    out = _set_tbl_pr(body, _TBLLAYOUT_RE, FIXED, _AFTER_TBLLAYOUT)
    assert out.count("<w:tblPr") == 1
    assert f"<w:tblPr>{FIXED}</w:tblPr>" in out


def test_fit_columns_handles_a_table_whose_properties_are_empty():
    xml = doc('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
              '<w:gridCol w:w="1000"/></w:tblGrid><w:tr>'
              + cell("Label") + cell("-0.250***") + "</w:tr></w:tbl>")
    out, report = tables.fit_columns(xml, tables.read_all(xml)[0])
    assert sum(c.new for c in report.columns) == report.total
    assert out.count("<w:tblPr") == 1
    assert FIXED in out


# ------------------------------------------------ alignment on a pPr -----


def test_alignment_is_added_to_properties_that_state_none():
    """The ordinary case out of a real manuscript, and the one the suite
    never built: a paragraph with a style and no alignment."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"/></w:pPr>'
            "<w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "center")
    assert ('<w:pPr><w:pStyle w:val="Body"/><w:jc w:val="center"/></w:pPr>'
            in got)


def test_alignment_lands_before_the_properties_that_follow_it():
    """`CT_PPr` is a sequence: `w:jc` precedes `w:rPr`. Appending it at
    the end puts it after, and Word repairs a document whose paragraph
    properties are out of order."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"/>'
            "<w:rPr><w:b/></w:rPr></w:pPr><w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "left")
    inner = got[got.index("<w:pPr>"):got.index("</w:pPr>")]
    assert inner.index("<w:jc") < inner.index("<w:rPr")
    assert "<w:b/>" in got


def test_an_existing_alignment_is_replaced_not_stacked():
    para = ('<w:p><w:pPr><w:jc w:val="left"/></w:pPr>'
            "<w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "center")
    assert got.count("<w:jc") == 1
    assert 'w:val="center"' in got and 'w:val="left"' not in got


def test_alignment_is_written_to_the_live_properties_not_the_snapshot():
    """`w:pPrChange` holds what a tracked change REPLACED. Writing there
    aligns the historical record and leaves the page as it was."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"/>'
            '<w:pPrChange w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
            '<w:pPr><w:jc w:val="right"/></w:pPr></w:pPrChange>'
            "</w:pPr><w:r><w:t>x</w:t></w:r></w:p>")
    got = _set_jc(para, "center")
    live, _, past = got.partition("<w:pPrChange")
    assert 'w:val="center"' in live
    assert 'w:val="right"' in past          # the snapshot is untouched
    assert past.count("<w:jc") == 1


def test_a_fragment_that_is_not_a_paragraph_is_returned_unchanged():
    assert _set_jc("<w:tc/>", "center") == "<w:tc/>"
    assert _set_jc("", "center") == ""


def test_a_paragraph_with_no_properties_gets_some():
    got = _set_jc("<w:p><w:r><w:t>x</w:t></w:r></w:p>", "center")
    assert '<w:pPr><w:jc w:val="center"/></w:pPr>' in got


# --------------------------------------------------- refusals that stand --


def test_an_empty_alignment_sequence_is_refused():
    """`align=()` reaches `vals[min(i, -1)]` and silently aligns every
    column by the LAST element of an empty list — which is an IndexError
    at best and the wrong column at worst."""
    with pytest.raises(AnchorError, match="align= is empty"):
        _alignment([], 3)


def test_a_single_alignment_repeats_across_every_column():
    assert _alignment("center", 3) == ["center"] * 3


def test_the_last_alignment_repeats_when_there_are_more_columns():
    assert _alignment(("left", "center"), 4) == \
        ["left", "center", "center", "center"]


def test_booktabs_refuses_a_table_with_no_rows():
    xml = doc('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
              "</w:tblGrid></w:tbl>")
    with pytest.raises(AnchorError, match="no rows"):
        tables.booktabs(xml, tables.read_all(xml)[0])


def test_bottom_border_refuses_a_table_with_no_rows():
    xml = doc('<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="1000"/>'
              "</w:tblGrid></w:tbl>")
    with pytest.raises(AnchorError, match="no rows"):
        tables.bottom_border(xml, tables.read_all(xml)[0])
