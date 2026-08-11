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


# ------------------- the two definitions of "what this paragraph says" ---
#
# `find.para_slice` reads `visible_text` — w:t AND m:t — while
# `edit.replace_in_para` walks w:r runs, and OMML text lives in m:r. So a
# phrase spanning an equation is findable by one and invisible to the
# other. Measured over 399 real manuscripts while consolidating probe
# onto the shared patterns: the two answers differ on 256 of them, every
# difference an equation. probe is asked BEFORE an approach is chosen,
# so it reports the split rather than picking a side.

MATHY = ('<w:p><w:r><w:t xml:space="preserve">where </w:t></w:r>'
         "<m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"
         '<w:r><w:t xml:space="preserve"> denotes the index.</w:t></w:r>'
         "</w:p>")


def test_probe_reports_where_the_two_views_disagree(tmp_path):
    """The phrase reads "where x denotes" to `find` and "where  denotes"
    to `edit`; probe must not answer as though there were one reading."""
    path = make_docx(tmp_path, MATHY)
    rep = probe(path, ("where x denotes", "where  denotes"))
    assert [i for i, _ in rep.anchors["where x denotes"]] == [0]
    assert rep.anchors["where  denotes"] == []
    assert rep.view_split["where x denotes"] == ([0], [])
    assert rep.view_split["where  denotes"] == ([], [0])
    assert "the two views disagree" in rep.report()


def test_what_probe_reports_is_what_the_two_tools_actually_do(tmp_path):
    """The property, asserted against the tools themselves rather than
    against probe's own idea of them — a prediction nobody checks is how
    the two definitions drifted apart in the first place."""
    import pytest

    from docxkit.edit import replace_in_para
    from docxkit.errors import AnchorError
    from docxkit.find import para_slice

    path = make_docx(tmp_path, MATHY)
    rep = probe(path, ("where x denotes", "where  denotes"))
    doc = make_parts(MATHY)["word/document.xml"].decode("utf-8")

    # what `find` sees is the first element of the split
    para_slice(doc, "where x denotes")
    with pytest.raises(AnchorError):
        para_slice(doc, "where  denotes")
    assert rep.view_split["where x denotes"][0] == [0]

    # what `edit` sees is the second, and it is the other way round
    replace_in_para(MATHY, "where  denotes", "REPLACED")
    with pytest.raises(AnchorError):
        replace_in_para(MATHY, "where x denotes", "REPLACED")
    assert rep.view_split["where  denotes"][1] == [0]


def test_an_ordinary_anchor_has_no_split_to_report(tmp_path):
    """The quiet case: no equation, one answer, nothing said."""
    path = make_docx(tmp_path, BODY)
    rep = probe(path, ("We report it in",))
    assert [i for i, _ in rep.anchors["We report it in"]] == [0]
    assert rep.view_split == {}
    assert "disagree" not in rep.report()


def test_an_empty_self_closing_paragraph_does_not_swallow_the_next_block(
        tmp_path):
    """probe walked blocks with `<w:p\b.*?</w:p>`, which has no close tag
    to find on a self-closing `<w:p/>` and so runs on to the NEXT one —
    here the table's first cell. The caption then reports "(no table
    follows)" for a table sitting directly under it.

    Word writes `<w:p/>` for an empty paragraph, and a spacer line
    between a caption and its table is exactly where one goes."""
    body = ("<w:p><w:r><w:t>Table 1. Descriptive statistics.</w:t></w:r>"
            "</w:p><w:p/>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc>"
            "</w:tr><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>")
    rep = probe(make_docx(tmp_path, body))
    assert rep.exhibits, "the caption itself was not found"
    label, follows, _orient = rep.exhibits[0]
    assert label == "Table 1"
    assert follows.startswith("table,"), follows
