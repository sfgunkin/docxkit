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
    # `…</w:p><w:bookmarkStart/><w:p …>` when it hoists a collapsed one.
    # TWO hoisted against ONE inside, deliberately: with one of each the
    # count of body-level and the count of nested are the same number,
    # and a report that had counted the wrong kind would still read "1".
    body = (para(run("first"))
            + '<w:bookmarkStart w:id="1" w:name="Hoisted"/>'
              '<w:bookmarkEnd w:id="1"/>'
            + '<w:p><w:bookmarkStart w:id="2" w:name="Inside"/>'
            + run("text") + '<w:bookmarkEnd w:id="2"/></w:p>'
            + '<w:bookmarkStart w:id="3" w:name="AlsoHoisted"/>'
              '<w:bookmarkEnd w:id="3"/>'
            + para(run("last")))

    line = next(ln for ln in probe(_doc(tmp_path, body)).report().splitlines()
                if "bookmarks" in ln)

    assert line == "  bookmarks   3 (2 body-level)"


def test_a_document_with_ONE_section_says_one(tmp_path):
    """`' -> '.join(...) or 'one'` — an empty join is the empty string,
    which would print a blank where the answer belongs."""
    line = next(ln for ln in probe(_doc(tmp_path, para(run("x")))).report()
                .splitlines() if "sections" in ln)

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

    line = next(ln for ln in probe(_doc(tmp_path, body)).report().splitlines()
                if "field-form anchors" in ln)

    assert line.count(",") == count - 1, line


# --- the lines of the report nothing had read (2026-08-19) --------------
#
# probe re-measured at 25.0 % — still the highest in the package — with
# 13 of the 42 survivors in `report` itself. What was left is the shape
# of each line rather than the numbers in it: whether a section prints
# at all, what an exhibit looks like without an orientation, and the
# fallbacks that keep a blank out of an answer.


def _exhibit_doc(orient: str = "") -> str:
    """A caption, a table under it, and optionally a landscape break."""
    sect = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="15840" '
            f'w:orient="{orient}"/></w:sectPr></w:pPr></w:p>'
            ) if orient else ""
    return (para(run("Table 1: Descriptive statistics."))
            + "<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr>"
              "<w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>" + sect)


def test_a_document_with_NO_exhibits_prints_no_exhibit_section(tmp_path):
    """The heading is worth its line only when something follows it. A
    report that lists "exhibits" and then nothing reads as a paper whose
    captions were not recognised — which is the failure this command is
    consulted about."""
    lines = probe(_doc(tmp_path, para(run("Plain prose, no captions.")))
                  ).report().splitlines()

    assert not [ln for ln in lines if "exhibits" in ln]


def test_an_exhibit_prints_its_LABEL_what_follows_it_and_nothing_else(
        tmp_path):
    """No section break anywhere, so the orientation is unknown and the
    line ends after what follows the caption. `[  ]` in its place is a
    reader asking what the empty brackets mean."""
    got = probe(_doc(tmp_path, _exhibit_doc()))

    lines = got.report().splitlines()
    at = lines.index("  exhibits")
    assert lines[at + 1] == "    Table 1      table, 2 rows"


def test_an_exhibit_in_a_LANDSCAPE_section_says_so_on_the_same_line(
        tmp_path):
    """Which is the answer a batch wants before it re-fits a table: a
    landscape table has half again the width to work with."""
    got = probe(_doc(tmp_path, _exhibit_doc("landscape")))

    lines = got.report().splitlines()
    at = lines.index("  exhibits")
    assert lines[at + 1] == "    Table 1      table, 2 rows  [landscape]"


def test_TWO_sections_are_printed_in_order_with_their_orientations(
        tmp_path):
    """`' -> '.join(...)`: the order is the document's, and a paper that
    turns landscape for its appendix and back reads as three sections,
    not as "portrait" once."""
    def sect(orient: str) -> str:
        return ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="15840" '
                f'w:orient="{orient}"/></w:sectPr></w:pPr></w:p>')

    body = para(run("prose")) + sect("landscape") + sect("portrait")

    line = next(ln for ln in probe(_doc(tmp_path, body)).report().splitlines()
                if "sections" in ln)

    assert line == "  sections    landscape -> portrait"


def test_a_section_with_no_ORIENTATION_attribute_reads_portrait(tmp_path):
    """Word omits `w:orient` for the default, and "portrait" is what the
    reader would otherwise have to know to infer from silence."""
    body = (para(run("prose"))
            + '<w:p><w:pPr><w:sectPr><w:pgSz w:w="12240"/></w:sectPr>'
              "</w:pPr></w:p>")

    line = next(ln for ln in probe(_doc(tmp_path, body)).report().splitlines()
                if "sections" in ln)

    assert line == "  sections    portrait"


def test_the_view_split_says_NOTHING_where_a_view_sees_nothing(tmp_path):
    """`seen or 'nothing'` — the sentence exists to contrast the two
    views, and under `and` the side that DID see something prints
    "nothing" while the empty one prints an empty string. Both halves
    then read as the same answer, which is the opposite of the finding.
    """
    maths = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
             'officeDocument/2006/math"><m:r><m:t>τ</m:t></m:r></m:oMath>')
    body = "<w:p>" + run("where ") + maths + run(" is time") + "</w:p>"

    got = probe(_doc(tmp_path, body), anchors=("where τ is",))

    split = next(ln for ln in got.report().splitlines()
                 if "the two views disagree" in ln)
    assert "find/para_slice [0]" in split, "the view that DID see it"
    assert "edit/replace_in_para nothing" in split
