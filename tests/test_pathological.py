"""Every mutator, over the shapes that have actually caused incidents.

The synthetic fixtures elsewhere are clean in ways real manuscripts
never are. Each document below reproduces a structure that once broke
something here, so a regression has to survive all of them, not just the
tidy case:

* a self-closing ``<w:hyperlink/>`` ghost — read as an open tag, it
  paired with a close tag 14 paragraphs downstream and unlinking then
  deleted the wrong end tag;
* a run whose ``<w:rPr>`` precedes its text — ``rfind("<w:r", 0, pos)``
  matched the ``<w:rPr`` and cut the XML mid-element;
* a merged cell — cell index and grid column diverge from there on;
* a nested table — a non-greedy ``<w:tbl>.*?</w:tbl>`` closes on the
  inner one and the fragment ends mid-cell;
* a run carrying two ``<w:t>`` children — two different node walks stop
  agreeing about offsets;
* an NBSP-only cell — ``str.strip()`` eats U+00A0 where XML does not;
* both hyperlink forms in one document — Word converts field to element
  on every save, so a real paper contains both;
* tracked content in a table cell — python-docx reads it as empty.

The invariants asserted are the ones every mutator shares: the result
parses, and the visible text survives unless the operation is defined to
change it.
"""
from __future__ import annotations

import pytest
from conftest import NS
from lxml import etree

from docxkit import tables
from docxkit._xml import visible_text
from docxkit.package import malformed_parts

W_NS = NS


def doc(*body: str) -> str:
    return (f"<w:document {W_NS}><w:body>" + "".join(body)
            + "</w:body></w:document>")


def p(*inner: str) -> str:
    return "<w:p>" + "".join(inner) + "</w:p>"


def r(text: str, rpr: str = "") -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def tc(inner: str, *, span: int | None = None, w: int = 800) -> str:
    s = f'<w:gridSpan w:val="{span}"/>' if span else ""
    return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{s}</w:tcPr>'
            f"{inner}</w:tc>")


def tbl(cols: int, *rows: str) -> str:
    grid = "".join('<w:gridCol w:w="800"/>' for _ in range(cols))
    pr = (f'<w:tblPr><w:tblW w:w="{cols * 800}" w:type="dxa"/></w:tblPr>'
          f"<w:tblGrid>{grid}</w:tblGrid>")
    return "<w:tbl>" + pr + "".join(rows) + "</w:tbl>"


# --------------------------------------------------------- the corpus -----

# The ghost must be FOLLOWED by a real link: read as an open tag it
# pairs with that link's close tag, and everything between is swallowed.
# The incident had 14 paragraphs in between.
GHOST_HYPERLINK = doc(
    p(r("Agostinelli (2024) argues, "),
      '<w:hyperlink w:anchor="dead"/>',          # self-closing ghost
      r("and so does Smith (2020).")),
    p(r("Intervening prose that must survive.")),
    p(r("See "),
      '<w:hyperlink w:anchor="Table1"><w:r><w:t>Table 1</w:t></w:r>'
      "</w:hyperlink>",
      r(" for the detail.")),
    p(r("Table 1. Results")))

STYLED_RUNS = doc(
    p(r("Coefficient ", '<w:rPr><w:i/><w:sz w:val="20"/></w:rPr>'),
      r("-0.250***", '<w:rPr><w:b/><w:rFonts w:ascii="Arial Narrow"/>'
                     "</w:rPr>")))

MERGED_CELLS = doc(tbl(
    4,
    "<w:tr>" + tc(p(r("Label"))) + tc(p(r("Group header")), span=2)
    + tc(p(r("N"))) + "</w:tr>",
    "<w:tr>" + tc(p(r("Child’s age"))) + tc(p(r("-0.250***")))
    + tc(p(r("0.047"))) + tc(p(r("3,168"))) + "</w:tr>"))

NESTED_TABLE = doc(tbl(
    1,
    "<w:tr>" + tc(tbl(1, "<w:tr>" + tc(p(r("inner"))) + "</w:tr>")
                  + p(r("after the inner table"))) + "</w:tr>"))

SPLIT_RUN = doc(
    p('<w:r><w:t xml:space="preserve">One run, </w:t>'
      '<w:t xml:space="preserve">two text nodes.</w:t></w:r>'))

NBSP_CELL = doc(tbl(
    2, "<w:tr>" + tc(p(r(" "))) + tc(p(r("0.047"))) + "</w:tr>"))

BOTH_LINK_FORMS = doc(
    p(r("See "),
      '<w:hyperlink w:anchor="Table1"><w:r><w:t>Table 1</w:t></w:r>'
      "</w:hyperlink>",
      r(" and ),"),
      '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
      '<w:r><w:instrText xml:space="preserve"> HYPERLINK  \\l "Table2" '
      "</w:instrText></w:r>"
      '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
      "<w:r><w:t>Table 2</w:t></w:r>"
      '<w:r><w:fldChar w:fldCharType="end"/></w:r>'),
    p(r("Table 1. First")), p(r("Table 2. Second")))

TRACKED_CELL = doc(tbl(
    2,
    "<w:tr>" + tc(p(r("Urban")))
    + tc('<w:p><w:ins w:id="9" w:author="A" w:date="2026-01-01T00:00:00Z">'
         "<w:r><w:t>0.022</w:t></w:r></w:ins></w:p>") + "</w:tr>"))

CORPUS = {
    "ghost_hyperlink": GHOST_HYPERLINK,
    "styled_runs": STYLED_RUNS,
    "merged_cells": MERGED_CELLS,
    "nested_table": NESTED_TABLE,
    "split_run": SPLIT_RUN,
    "nbsp_cell": NBSP_CELL,
    "both_link_forms": BOTH_LINK_FORMS,
    "tracked_cell": TRACKED_CELL,
}


@pytest.fixture(params=sorted(CORPUS), ids=sorted(CORPUS))
def specimen(request) -> str:
    return CORPUS[request.param]


def parses(xml: str) -> None:
    etree.fromstring(xml.encode("utf-8"))


def test_every_specimen_is_itself_well_formed(specimen):
    """The fixtures must be pathological, not broken."""
    parses(specimen)


# ------------------------------------------------ document-wide mutators ---


def text_preserving_mutators():
    """(name, fn) — each takes a part's XML and returns it rewritten,
    with the visible text unchanged by definition."""
    from docxkit import crossrefs, hygiene
    from docxkit.edit import preserve_space
    return [
        ("crossrefs.link", lambda x: crossrefs.link(x)[0]),
        ("crossrefs.link_more", lambda x: crossrefs.link_more(x)[0]),
        ("crossrefs.unlink", lambda x: crossrefs.unlink(x)[0]),
        ("preserve_space", lambda x: preserve_space(x)[0]),
        ("hygiene.smarten", lambda x: hygiene.smarten(x)[0]),
    ]


@pytest.mark.parametrize("name,fn", text_preserving_mutators(),
                         ids=[n for n, _ in text_preserving_mutators()])
def test_mutators_keep_the_document_parseable(specimen, name, fn):
    parses(fn(specimen))


@pytest.mark.parametrize("name,fn", text_preserving_mutators(),
                         ids=[n for n, _ in text_preserving_mutators()])
def test_mutators_keep_every_character_of_visible_text(specimen, name, fn):
    if name == "hygiene.smarten":
        pytest.skip("smarten rewrites quotes by design")
    assert visible_text(fn(specimen)) == visible_text(specimen)


@pytest.mark.parametrize("name,fn", text_preserving_mutators(),
                         ids=[n for n, _ in text_preserving_mutators()])
def test_mutators_are_idempotent(specimen, name, fn):
    once = fn(specimen)
    assert fn(once) == once


# ------------------------------------------------------ table mutators ----


def table_specimens():
    return [k for k in sorted(CORPUS)
            if tables.read_all(CORPUS[k]) and
            any(t.rows for t in tables.read_all(CORPUS[k]))]


@pytest.fixture(params=table_specimens(), ids=table_specimens())
def table_doc(request) -> str:
    return CORPUS[request.param]


def test_fit_columns_survives_every_table_shape(table_doc):
    t = tables.read_all(table_doc)[0]
    if not any(t.rows):
        pytest.skip("no cells")
    try:
        out, _ = tables.fit_columns(table_doc, t)
    except Exception as exc:
        # a tracked table is REFUSED, loudly, by design
        assert "tracked" in str(exc), exc
        return
    parses(out)
    assert visible_text(out) == visible_text(table_doc)


def test_bottom_border_survives_every_table_shape(table_doc):
    t = tables.read_all(table_doc)[0]
    out, _ = tables.bottom_border(table_doc, t)
    parses(out)
    assert visible_text(out) == visible_text(table_doc)


def test_superscript_stars_survives_every_table_shape(table_doc):
    t = tables.read_all(table_doc)[0]
    try:
        out, _ = tables.superscript_stars(table_doc, t)
    except Exception as exc:
        assert "tracked" in str(exc), exc
        return
    parses(out)
    assert visible_text(out) == visible_text(table_doc)


def test_a_ghost_hyperlink_does_not_swallow_the_links_after_it():
    """A self-closing <w:hyperlink/> wraps nothing.

    Read as an open tag it is never popped, so every later link in the
    paragraph is reported as nested inside it — and in the incident that
    produced this fixture, an unlink pass then deleted the close tag of
    a link 14 paragraphs downstream and the file would not open.
    """
    from docxkit.citations import _doubled_links, audit_links

    para = ('<w:p><w:hyperlink w:anchor="dead"/>'
            '<w:hyperlink w:anchor="Table1"><w:r><w:t>Table 1</w:t>'
            "</w:r></w:hyperlink></w:p>")
    assert _doubled_links(para) == []

    issues, _ = audit_links(
        {"word/document.xml": GHOST_HYPERLINK.encode("utf-8")})
    assert not [i for i in issues if "DOUBLED LINK" in i], issues


def test_nested_tables_are_read_as_one_outer_table():
    """The non-greedy close-tag bug: the outer span must not end at the
    inner table's </w:tbl>, or the fragment stops mid-cell."""
    read = tables.read_all(NESTED_TABLE)
    assert len(read) == 1
    assert "after the inner table" in visible_text(
        NESTED_TABLE[read[0].start:read[0].end])


def test_a_merged_row_reports_fewer_cells_than_the_grid_is_wide():
    t = tables.read_all(MERGED_CELLS)[0]
    assert len(t.rows[0]) == 3 and len(t.rows[1]) == 4
    assert t.grid_columns(MERGED_CELLS, 0) == [0, 1, 3]


def test_an_nbsp_cell_is_not_treated_as_empty_whitespace():
    """XML trims space/tab/CR/LF — never U+00A0. Python's strip() does,
    which produced spurious preserve attributes and false lint hits."""
    from docxkit.edit import preserve_space
    out, n = preserve_space(NBSP_CELL)
    assert n == 0
    parses(out)


# ---------------------------------------------------- the write gate ------


def test_write_docx_refuses_a_malformed_part(tmp_path):
    from docxkit.errors import PackageError
    from docxkit.package import write_docx
    parts = {"word/document.xml":
             b"<w:document><w:body><w:p><w:r></w:p></w:body></w:document>"}
    target = tmp_path / "broken.docx"
    with pytest.raises(PackageError, match="refusing to write malformed"):
        write_docx(target, parts)
    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_write_docx_ignores_non_xml_members(tmp_path):
    from docxkit.package import read_parts, write_docx
    parts = {"word/document.xml": doc(p(r("ok"))).encode("utf-8"),
             "word/media/image1.png": b"\x89PNG\r\n\x1a\n not xml at all"}
    target = tmp_path / "fine.docx"
    write_docx(target, parts)
    assert read_parts(target)["word/media/image1.png"].startswith(b"\x89PNG")


def test_malformed_parts_names_the_offender():
    bad = malformed_parts({
        "word/document.xml": doc(p(r("fine"))).encode("utf-8"),
        "word/footnotes.xml": b"<w:footnotes><w:footnote></w:footnotes>",
    })
    assert len(bad) == 1 and bad[0].startswith("word/footnotes.xml")
