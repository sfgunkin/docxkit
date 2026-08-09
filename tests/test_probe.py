"""probe answers the questions a batch has to know before it starts."""

from conftest import make_parts, write

from docxkit.probe import probe


def make_docx(tmp_path, body: str) -> str:
    return write(tmp_path / "probe.docx", make_parts(body))

FIELD_LINK = (
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText>HYPERLINK \\l "Table1txt" \\h</w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    "<w:r><w:t>Table 1</w:t></w:r>"
    '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

BODY = (
    '<w:p><w:r><w:t>We report it in </w:t></w:r>'
    '<w:hyperlink w:anchor="Smith2020"><w:r><w:t>Smith 2020</w:t></w:r>'
    "</w:hyperlink><w:r><w:t>.</w:t></w:r></w:p>"
    '<w:bookmarkStart w:id="1" w:name="Table1"/><w:bookmarkEnd w:id="1"/>'
    f"<w:p>{FIELD_LINK}<w:r><w:t>: Descriptive statistics.</w:t></w:r></w:p>"
    "<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr>"
    "<w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>"
    '<w:p><w:pPr><w:sectPr><w:pgSz w:w="15840" w:orient="landscape"/>'
    "</w:sectPr></w:pPr></w:p>")


def test_probe_names_the_link_form(tmp_path):
    # the whole point: a manuscript whose links are field form takes
    # crossrefs.unlink silently, and the approach has to change
    rep = probe(make_docx(tmp_path, BODY))
    assert "MIXED" in rep.link_form
    assert rep.field_links == {"Table1txt": 1}
    assert rep.element_links == {"Smith2020": 1}


def test_probe_maps_exhibits_to_their_table_and_section(tmp_path):
    rep = probe(make_docx(tmp_path, BODY))
    assert rep.exhibits == [("Table 1", "table, 2 rows", "landscape")]


def test_probe_reports_body_level_bookmarks(tmp_path):
    # a block move must carry these; a paragraph-oriented edit cannot see them
    rep = probe(make_docx(tmp_path, BODY))
    assert ("Table1", "body") in rep.bookmarks


def test_probe_shows_how_a_phrase_splits_across_runs(tmp_path):
    rep = probe(make_docx(tmp_path, BODY), ("Table 1: Descriptive",))
    (_, runs), = rep.anchors["Table 1: Descriptive"]
    assert runs == ["Table 1", ": Descriptive statistics."]


def test_probe_reports_a_missing_anchor_rather_than_raising(tmp_path):
    rep = probe(make_docx(tmp_path, BODY), ("nowhere in the paper",))
    assert rep.anchors["nowhere in the paper"] == []
    assert "NOT FOUND" in rep.report()
