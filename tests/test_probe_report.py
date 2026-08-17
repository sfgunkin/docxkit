"""`probe`, stated as the report it prints.

Measured for the first time on 2026-08-17: 36.9 % real survival, the
worst in the package, with 62 survivors of which 40 are `probe` itself
and 19 are `report`. The pattern across the whole measuring pass was the
same — the DIAGNOSTIC modules are the least-pinned (`probe` 36.9 %,
`pages` 24.3 %, `console` 24.1 %, `testing` 23.0 %) while the modules
that rewrite manuscripts sit at 4–8 %.

That ordering is defensible as far as consequence goes: a defect in
`edit` corrupts a paper, a defect here misleads whoever reads the
answer. But this module exists to be trusted BEFORE a batch picks its
approach — its whole argument is that a two-table swap took forty
minutes because nobody knew which form the links took. A probe that
reports the wrong form costs exactly that forty minutes back, and
silently.

So the report is asserted here as a VALUE, line by line, the way the
citation reports are.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run, write

from docxkit.probe import probe

ELEMENT_LINK = ('<w:hyperlink w:anchor="Table1txt">'
                '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                "<w:t>Table 1</w:t></w:r></w:hyperlink>")


def _field_link(anchor: str, label: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText> HYPERLINK \\l "{anchor}" \\h '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            f"<w:t>{label}</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _doc(tmp_path, body: str, name: str = "paper.docx"):
    return write(tmp_path / name, make_parts(body))


# ---------------------------------------------------- the link FORM ------

def test_a_document_with_no_links_says_none(tmp_path):
    got = probe(_doc(tmp_path, para(run("Plain prose."))))

    assert got.link_form == "none"
    assert got.report().splitlines()[1] == "  link form   none"


def test_ELEMENT_form_is_named_with_its_count(tmp_path):
    got = probe(_doc(tmp_path, "<w:p>" + ELEMENT_LINK + "</w:p>"))

    assert got.link_form == "element (1)"


def test_FIELD_form_says_the_tools_CANNOT_see_it(tmp_path):
    """The expensive fact, and the reason the module exists.
    `crossrefs.unlink`/`link` understand element form only: on a
    field-form manuscript unlink reports a healthy number of bookmarks
    removed and leaves every link standing.
    """
    got = probe(_doc(tmp_path, "<w:p>" + _field_link("T1", "Table 1")
                     + "</w:p>"))

    assert got.link_form.startswith("FIELD (1)")
    assert "CANNOT see these" in got.link_form
    assert "field-form anchors: T1" in got.report()


def test_MIXED_names_both_counts_in_order(tmp_path):
    """Both forms in one document is the case that decides an approach:
    neither route is safe on its own."""
    body = ("<w:p>" + ELEMENT_LINK + "</w:p>"
            + "<w:p>" + _field_link("T2", "Table 2") + "</w:p>")

    got = probe(_doc(tmp_path, body))

    assert got.link_form == "MIXED (1 element, 1 field)"


def test_a_MIXED_document_is_not_reported_as_either_alone(tmp_path):
    """`if el and fld` mutated to `or` makes a document with only one
    form report as MIXED — the answer that sends a batch down the
    teardown-and-rebuild route it did not need."""
    body = "<w:p>" + ELEMENT_LINK + "</w:p>"

    assert "MIXED" not in probe(_doc(tmp_path, body)).link_form


# ------------------------------------------------- what the report says --

def test_the_report_opens_with_the_FILE_NAME(tmp_path):
    got = probe(_doc(tmp_path, para(run("x")), name="AFI_v14.docx"))

    assert got.report().splitlines()[0] == "AFI_v14.docx"


def test_bookmarks_are_counted_WITH_how_many_are_body_level(tmp_path):
    """Word hoists a collapsed bookmark out of the paragraph it marks,
    and a body-level marker is a different thing to address than one
    inside a paragraph. The count alone would not say which."""
    # BETWEEN paragraphs is what body-level means: Word writes
    # `…</w:p><w:bookmarkStart/><w:p …>` when it hoists a collapsed one
    body = (para(run("first"))
            + '<w:bookmarkStart w:id="1" w:name="Hoisted"/>'
              '<w:bookmarkEnd w:id="1"/>'
            + '<w:p><w:bookmarkStart w:id="2" w:name="Inside"/>'
            + run("text") + '<w:bookmarkEnd w:id="2"/></w:p>')

    line = [ln for ln in probe(_doc(tmp_path, body)).report().splitlines()
            if "bookmarks" in ln][0]

    assert line == "  bookmarks   2 (1 body-level)"


def test_a_document_with_ONE_section_says_one(tmp_path):
    """`' -> '.join(...) or 'one'` — an empty join is the empty string,
    which would print a blank where the answer belongs."""
    line = [ln for ln in probe(_doc(tmp_path, para(run("x")))).report()
            .splitlines() if "sections" in ln][0]

    assert line == "  sections    one"


def test_an_ANCHOR_that_is_absent_says_NOT_FOUND(tmp_path):
    """The probe is asked before an edit is written. "No hits" printed
    as nothing at all reads as success."""
    got = probe(_doc(tmp_path, para(run("Some prose."))),
                anchors=("absent phrase",))

    report = got.report()
    assert "anchor 'absent phrase'" in report
    assert "NOT FOUND" in report


def test_an_ANCHOR_is_reported_with_its_paragraph_and_its_RUNS(tmp_path):
    """Word splits a phrase at rsid boundaries, and which runs it lands
    in decides whether a replace can address it at all."""
    body = para(run("The share "), run("rose to "), run("0.15."))

    got = probe(_doc(tmp_path, body), anchors=("rose to",))

    hits = got.anchors["rose to"]
    assert len(hits) == 1
    _idx, runs = hits[0]
    # the WHOLE paragraph's split, not just the matching run: the
    # question probe answers is "can a replace address this phrase",
    # and that depends on the boundaries either side of it
    assert runs == ["The share ", "rose to ", "0.15."], runs


def test_the_two_VIEWS_disagreeing_is_reported_as_a_split(tmp_path):
    """The whole reason `probe` reports rather than picks: `find` reads
    `w:t` and `m:t`, `edit` walks `w:r` runs, and an equation lives in
    `m:r` — so a phrase spanning one is findable by the first and
    invisible to the second.
    """
    maths = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
             'officeDocument/2006/math"><m:r><m:t>τ</m:t></m:r></m:oMath>')
    body = "<w:p>" + run("where ") + maths + run(" is time") + "</w:p>"

    got = probe(_doc(tmp_path, body), anchors=("where τ is",))

    assert "where τ is" in got.view_split, got.view_split
    assert "the two views disagree" in got.report()


@pytest.mark.parametrize("count", [1, 3])
def test_the_field_anchor_list_is_CUT_not_dumped(tmp_path, count):
    """Twelve is the cut. A manuscript with two hundred field links
    would otherwise print two hundred names where a reader wants to see
    that the form is FIELD."""
    body = "".join("<w:p>" + _field_link(f"T{n}", f"Table {n}") + "</w:p>"
                   for n in range(count))

    line = [ln for ln in probe(_doc(tmp_path, body)).report().splitlines()
            if "field-form anchors" in ln][0]

    assert line.count(",") == count - 1, line
