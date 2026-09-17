"""probe answers the questions a batch has to know before it starts."""

import pytest
from conftest import make_parts, notes, para, run, write

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
    (_, runs), = rep.phrases["Table 1: Descriptive"]
    assert runs == ["Table 1", ": Descriptive statistics."]


def test_probe_reports_a_missing_anchor_rather_than_raising(tmp_path):
    rep = probe(make_docx(tmp_path, BODY), ("nowhere in the paper",))
    assert rep.phrases["nowhere in the paper"] == []
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
    assert [i for i, _ in rep.phrases["where x denotes"]] == [0]
    assert rep.phrases["where  denotes"] == []
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

    # what `edit` sees is the second, and it is the other way round: the
    # maths-less spelling is LOCATED — the refusal is about the equation
    # it crosses, not "not in paragraph". Writing it was allowed until
    # 2026-09-17, and moved the equation to the end of the replacement.
    with pytest.raises(AnchorError, match="crosses an equation"):
        replace_in_para(MATHY, "where  denotes", "REPLACED")
    with pytest.raises(AnchorError, match="not in paragraph"):
        replace_in_para(MATHY, "where x denotes", "REPLACED")
    assert rep.view_split["where  denotes"][1] == [0]


def test_an_ordinary_anchor_has_no_split_to_report(tmp_path):
    """The quiet case: no equation, one answer, nothing said."""
    path = make_docx(tmp_path, BODY)
    rep = probe(path, ("We report it in",))
    assert [i for i, _ in rep.phrases["We report it in"]] == [0]
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


# --- what the probe run of 2026-08-17 found ------------------------------
#
# 36.9 % real survival, the highest in the package — and probe is the
# report a batch reads BEFORE it picks an approach, which is the whole
# argument for pinning it: the two-table swap that cost forty minutes
# cost them because nobody knew which form the links took.
#
# Twenty of the survivors sit on the two WINDOWS below: how far after a
# caption a table still counts as its table, and how far a section break
# still counts as its orientation. Every fixture here puts them
# adjacent, where every arithmetic spelling of the window agrees.


def _caption_para(text: str = "Table 1: Descriptive statistics.") -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _filler(n: int) -> str:
    return "".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                   for i in range(n))


def _table(rows: int = 2) -> str:
    return ("<w:tbl>" + "<w:tr><w:tc><w:p/></w:tc></w:tr>" * rows
            + "</w:tbl>")


def test_a_table_TWO_blocks_after_the_caption_is_still_its_table(tmp_path):
    """`blocks[i + 1:i + 3]` — a caption is routinely followed by a note
    or a blank paragraph before the table, and a paper's own note sits
    there by house rule. Three blocks away it belongs to something
    else."""
    near = probe(make_docx(tmp_path, _caption_para() + _filler(1)
                           + _table(3)))
    far = probe(make_docx(tmp_path, _caption_para() + _filler(2)
                          + _table(3)))

    assert near.exhibits == [("Table 1", "table, 3 rows", "")]
    assert far.exhibits == [("Table 1", "(no table follows)", "")]


@pytest.mark.parametrize("before", [0, 1])
def test_the_table_ABOVE_a_caption_is_not_the_caption_s_table(tmp_path,
                                                              before):
    """The window opens at `i + 1`, and every fixture until now put the
    caption at block 0 — where `i - 1`, `i & 1` and `i ^ 1` all land on
    or before it and still find the right table, because there is
    nothing above it to find.

    A real paper never looks like that. Table 1's own table sits above
    Table 2's caption, so a window that opens one block early reports
    the PREVIOUS exhibit's table — the same number of rows question,
    answered about the wrong table, in the report a batch reads to
    decide whether a table has to be re-fitted.

    Two positions, because the wrong spellings disagree with each other:
    at i = 1 it is `i - 1` and `i ^ 1` that reach back, and at i = 2 it
    is `i & 1`, which collapses to 0 and opens the window at the top of
    the document.

    `i | 1` and `i * 1` stay equivalent, and are argued rather than
    tested: both can only open the window AT the caption, and a caption
    is not a table, so the first table they find is still the same
    one."""
    body = (_table(5) + _filler(before) + _caption_para()
            + _filler(1) + _table(3))

    rep = probe(make_docx(tmp_path, body))

    assert rep.exhibits == [("Table 1", "table, 3 rows", "")]


def test_an_EMPTY_table_does_not_swallow_the_next_exhibit(tmp_path):
    """`<w:tbl/>` opens nothing. Read as an open tag it ran on to the
    NEXT table's close, taking Table 2's caption into one block that
    starts `<w:tbl` — and a block that is a table is never a caption, so
    Table 2 was not reported at all."""
    body = (_caption_para() + _table(2) + "<w:tbl/>"
            + _caption_para("Table 2: Regressions.") + _table(3))

    rep = probe(make_docx(tmp_path, body))

    assert rep.exhibits == [("Table 1", "table, 2 rows", ""),
                            ("Table 2", "table, 3 rows", "")]


def test_a_table_holding_a_NESTED_table_is_one_block_with_its_OWN_rows(
        tmp_path):
    """A table was the non-greedy `<w:tbl>.*?</w:tbl>`, closed by the
    NESTED table's end tag: the exhibit's block stopped inside its own
    first cell, its rows were every `<w:tr` in that stretch — its first
    row and all of the nested table's — and the rest of it was walked as
    paragraphs, where a caption-shaped cell reads as an exhibit."""
    nested = ("<w:tbl><w:tr><w:tc>" + _table(4) + "<w:p/></w:tc></w:tr>"
              "<w:tr><w:tc>" + _caption_para("Table 9: Inside a cell.")
              + "</w:tc></w:tr></w:tbl>")
    body = (_caption_para() + nested
            + _caption_para("Table 2: Regressions.") + _table(3))

    rep = probe(make_docx(tmp_path, body))

    assert rep.exhibits == [("Table 1", "table, 2 rows", ""),
                            ("Table 2", "table, 3 rows", "")]


def test_a_body_whose_open_tag_is_spelled_OTHERWISE_is_still_read(tmp_path):
    """The body was found as the exact string `<w:body>`; `find` answered
    -1 for `<w:body >`, and the slice from -1 is the document's last
    character — every bookmark in the body went unreported."""
    path = write(tmp_path / "probe.docx", {
        name: (blob.replace(b"<w:body>", b"<w:body >")
               if name == "word/document.xml" else blob)
        for name, blob in make_parts(BODY).items()})

    rep = probe(path)

    assert ("Table1", "body") in rep.bookmarks


def test_a_caption_whose_table_follows_IMMEDIATELY(tmp_path):
    """The other edge of the same window: `i + 1` is the first block it
    looks at, and a caption sitting directly on its table is the
    ordinary layout. Under `i + 2` the window steps over it and the
    exhibit is reported with no table at all."""
    rep = probe(make_docx(tmp_path, _caption_para() + _table(4)))

    assert rep.exhibits == [("Table 1", "table, 4 rows", "")]


def test_the_FIRST_table_after_a_caption_is_the_one_reported(tmp_path):
    """`break`, not `continue`: two tables inside the window is a
    caption whose table is followed by the next exhibit's, and the
    walk has to keep the first. Under `continue` the last one in the
    window wins and the caption is reported with its neighbour's row
    count."""
    rep = probe(make_docx(tmp_path,
                          _caption_para() + _table(2) + _table(7)))

    assert rep.exhibits == [("Table 1", "table, 2 rows", "")]


def test_a_paragraph_that_is_no_caption_does_not_stop_the_walk(tmp_path):
    """`continue`, not `break`. Every document opens with prose, so the
    first block a paper hands this walk is not a caption — under `break`
    the walk ends there and a manuscript full of exhibits is reported as
    having none."""
    rep = probe(make_docx(tmp_path, _filler(2) + _caption_para()
                          + _table(2)))

    assert rep.exhibits == [("Table 1", "table, 2 rows", "")]


def test_the_orientation_is_read_from_a_section_break_EIGHT_blocks_out(
        tmp_path):
    """`blocks[i:i + 8]`: the break that turns the page landscape closes
    the section the exhibit is IN, so it sits after the table and after
    whatever notes follow it. Too short a window and a landscape table
    is reported as portrait — which is the report a batch uses to decide
    whether the table has to be re-fitted at all."""
    landscape = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="15840" '
                 'w:orient="landscape"/></w:sectPr></w:pPr></w:p>')

    # the caption is block i, the table i+1, so six fillers put the
    # break at i+8 — one past the window, and the only distance that
    # tells a window of eight from one of nine
    inside = probe(make_docx(tmp_path, _caption_para() + _table()
                             + _filler(5) + landscape))
    outside = probe(make_docx(tmp_path, _caption_para() + _table()
                              + _filler(6) + landscape))

    assert inside.exhibits[0][2] == "landscape"
    assert outside.exhibits[0][2] == "", "beyond the window, and not guessed"


def test_the_FIRST_section_break_after_a_caption_gives_the_orientation(
        tmp_path):
    """`break`, not `continue`. The break that closes the exhibit's own
    section is the first one after it; a second inside the window
    belongs to whatever comes next. Under `continue` the last one wins,
    so a landscape table followed by the return to portrait is reported
    as portrait — the report a batch reads to decide whether the table
    needs re-fitting says nothing needs doing."""
    landscape = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="15840" '
                 'w:orient="landscape"/></w:sectPr></w:pPr></w:p>')
    portrait = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="12240"/>'
                "</w:sectPr></w:pPr></w:p>")

    rep = probe(make_docx(tmp_path, _caption_para() + _table()
                          + landscape + _filler(1) + portrait))

    assert rep.exhibits == [("Table 1", "table, 2 rows", "landscape")]


def test_the_orientation_window_still_reaches_from_block_EIGHT(tmp_path):
    """`blocks[i:i + 8]`, with the caption deep in the document. Every
    fixture until now put it in the first eight blocks, where `i + 8`
    and `i | 8` are the same number — a paper's first exhibit is rarely
    that early, and at block 8 the two part company: `i | 8` is 8, the
    window closes on itself, and every exhibit past the eighth block
    reports no orientation at all."""
    rep = probe(make_docx(tmp_path, _filler(8) + _caption_para() + _table()
                          + '<w:p><w:pPr><w:sectPr><w:pgSz w:w="15840" '
                            'w:orient="landscape"/></w:sectPr></w:pPr></w:p>'))

    assert rep.exhibits == [("Table 1", "table, 2 rows", "landscape")]


def test_a_bookmark_INSIDE_a_paragraph_is_not_body_level(tmp_path):
    """`closed > before`: a body-level bookmark sits BETWEEN paragraphs
    and a block move has to carry it; one inside a paragraph travels
    with the paragraph and needs nothing. The test above has only the
    body-level case, where both spellings of the comparison agree."""
    between = ('<w:p><w:r><w:t>Before.</w:t></w:r></w:p>'
               '<w:bookmarkStart w:id="1" w:name="between_paras"/>'
               '<w:bookmarkEnd w:id="1"/>')
    within = ('<w:p><w:bookmarkStart w:id="2" w:name="inside_para"/>'
              "<w:r><w:t>Held.</w:t></w:r>"
              '<w:bookmarkEnd w:id="2"/></w:p>')

    rep = probe(make_docx(tmp_path, between + within))

    assert ("between_paras", "body") in rep.bookmarks
    assert ("inside_para", "nested") in rep.bookmarks


def test_a_bookmark_ABOVE_every_paragraph_is_body_level(tmp_path):
    """Found by mutation testing, 2026-08-18: `closed > before` reported
    this one as nested, and the two searches are equal only here —
    `</w:p>` does not contain `<w:p`, so both are -1 exactly when no
    paragraph precedes the bookmark at all.

    A bookmark at the top of the body has no paragraph to travel with,
    so a paragraph-oriented edit does not carry it and a block move must
    — which is the one thing this field is read for."""
    top = ('<w:bookmarkStart w:id="1" w:name="doc_top"/>'
           '<w:bookmarkEnd w:id="1"/>'
           "<w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>")

    rep = probe(make_docx(tmp_path, top))

    assert rep.bookmarks == [("doc_top", "body")]


# --- counting, not just noticing (2026-08-19) ---------------------------
#
# Every link in this file's fixtures is one link to one anchor, and
# `n + 1` starting from zero is one whichever operator stands in its
# place. What the count is consulted for is the opposite case: an anchor
# cited three times is the one whose unlink leaves two dead references.


def _field_link(anchor: str) -> str:
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText>HYPERLINK \\l "{anchor}" \\h</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>see</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def _el_link(anchor: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>see</w:t></w:r>'
            "</w:hyperlink>")


def test_an_anchor_cited_THREE_times_is_counted_three_times(tmp_path):
    """`element (3)` is the number that says an unlink costs three
    references, not one. Reached only from a count above one: the first
    citation is `0 + 1`, which any arithmetic in that slot agrees on."""
    body = "".join(f"<w:p>{_el_link('Smith2020')}</w:p>" for _ in range(3))

    rep = probe(make_docx(tmp_path, body))

    assert rep.element_links == {"Smith2020": 3}
    assert rep.link_form == "element (3)"


def test_a_FIELD_anchor_cited_twice_is_counted_twice(tmp_path):
    """And the field count is what the warning quantifies — 'CANNOT see
    these' is advice about a number of references, not a yes/no."""
    body = "".join(f"<w:p>{_field_link('Table1txt')}</w:p>" for _ in range(2))

    rep = probe(make_docx(tmp_path, body))

    assert rep.field_links == {"Table1txt": 2}
    assert "FIELD (2)" in rep.link_form


def test_links_in_the_FOOTNOTES_are_counted_with_the_body_ones(tmp_path):
    """A citation living only in a footnote is still a citation, and a
    manuscript whose field links are all in its notes would otherwise
    read as element-form — the approach that then fails."""
    parts = make_parts(
        f"<w:p>{_el_link('Smith2020')}</w:p>",
        footnotes=notes("footnotes",
                        f'<w:footnote w:id="2"><w:p>{_field_link("Ntable")}'
                        "</w:p></w:footnote>"))

    rep = probe(write(tmp_path / "notes.docx", parts))

    assert rep.element_links == {"Smith2020": 1}
    assert rep.field_links == {"Ntable": 1}
    assert rep.link_form == "MIXED (1 element, 1 field)"


def test_a_missing_footnotes_part_does_not_end_the_scan(tmp_path):
    """`continue`, not `break`: the parts are looked at in a fixed order
    and most manuscripts have no footnotes. Stopping at the first one
    absent would leave every endnote link uncounted — and a paper that
    cites only in its endnotes would read as having no links at all."""
    parts = make_parts(
        f"<w:p>{_el_link('Smith2020')}</w:p>",
        extra={"word/endnotes.xml":
               notes("endnotes",
                     f'<w:endnote w:id="2"><w:p>{_el_link("Moran1950")}'
                     "</w:p></w:endnote>")})
    assert "word/footnotes.xml" not in parts

    rep = probe(write(tmp_path / "endnotes.docx", parts))

    assert rep.element_links == {"Smith2020": 1, "Moran1950": 1}


def test_only_TWELVE_field_anchors_are_listed(tmp_path):
    """The line is a sample, not an inventory — `len(field_links)` above
    it carries the total. Thirteen anchors printed in full would push
    the rest of the report off a terminal.

    Written into the document backwards, so that the order printed is
    the sort's and not the document's: two runs of probe over the same
    manuscript edited in between should differ where the manuscript
    does, and nowhere else."""
    body = "".join(f"<w:p>{_field_link(f'Anchor{i:02d}')}</w:p>"
                   for i in reversed(range(13)))

    line = next(ln for ln in probe(make_docx(tmp_path, body)).report()
                .splitlines() if "field-form anchors" in ln)

    assert line.endswith("Anchor00, Anchor01, Anchor02, Anchor03, Anchor04, "
                         "Anchor05, Anchor06, Anchor07, Anchor08, Anchor09, "
                         "Anchor10, Anchor11")
    assert "Anchor12" not in line, "last alphabetically, written first"


def test_at_most_TEN_runs_of_a_split_anchor_are_shown(tmp_path):
    """Word can split a sentence into a run per word after a spell-check
    pass; the point of the list is the shape of the split, and the first
    ten carry it."""
    body = "<w:p>" + "".join(f"<w:r><w:t>w{i} </w:t></w:r>"
                            for i in range(12)) + "</w:p>"

    rep = probe(make_docx(tmp_path, body), phrases=("w0 w1",))

    (_, runs), = rep.phrases["w0 w1"]
    assert len(runs) == 10
    assert runs[0] == "w0 " and runs[-1] == "w9 "


def test_an_anchor_found_TWICE_reports_both_paragraphs(tmp_path):
    """Which paragraph to edit is the question being asked, and a phrase
    the author reused answers it with two — a report naming one would
    send the edit to a paragraph chosen by position in the file."""
    body = (para(run("The index is defined below.")) + para(run("filler"))
            + para(run("The index is defined below.")))

    rep = probe(make_docx(tmp_path, body), phrases=("index is defined",))

    assert [i for i, _ in rep.phrases["index is defined"]] == [0, 2]


def test_a_caption_BELOW_its_table_has_no_table_after_it(tmp_path):
    """`blocks[i + 1:…]` starts AFTER the caption, and the arithmetic
    that says so is invisible while the caption is the first block:
    `i * 1`, `i | 1`, `i % 1` and `i & 1` all give 0 or 1 there. With
    the caption at block 3 and a table at block 1 — a table with its
    caption underneath, which is a house style, not a corner case —
    a window that starts at 0 or 1 reports the table ABOVE the caption
    as the one it introduces."""
    body = (_filler(1) + _table(3) + _filler(1)
            + _caption_para("Table 1: Descriptive statistics."))

    got = probe(make_docx(tmp_path, body))

    assert got.exhibits == [("Table 1", "(no table follows)", "")]


def test_a_caption_DEEP_in_the_document_still_finds_its_table(tmp_path):
    """The other side: at block 3 a doubled index (`i << 1`) puts the
    window past the table entirely, and the paper's fourth exhibit
    reports as having none."""
    body = (_filler(3) + _caption_para("Table 1: Descriptive statistics.")
            + _table(3))

    got = probe(make_docx(tmp_path, body))

    assert got.exhibits == [("Table 1", "table, 3 rows", "")]


# `probe.py` measured 5.4 % (9/168) on 2026-08-20, and all nine are
# equivalent:
#
# * `w == "body"` in the report's count, written `<=` and `is`. The two
#   values are "body" and "nested", written as literals in this module —
#   "nested" sorts after "body", and one object each.
# * `body.rfind("<w:p", 0, …)` and `rfind("</w:p>", 0, …)` written with
#   a start of 1. `body` opens at `<w:body>`, so nothing this searches
#   for can sit at offset 0 for the one-character window to hide.
# * the five on `blocks[i + 1:i + 3]`, the two blocks after a caption.
#   Every one of them starts the slice AT the caption instead, and the
#   loop above has already skipped every block that is a table — so the
#   extra entry is a block that cannot answer the question being asked
#   of it.


def test_the_old_anchors_spelling_still_works(tmp_path):
    """docxkit is the shared toolkit every paper imports, and the CLI
    kept `--anchors-from` for exactly this rename: a paper script should
    not break on one half of a change that was careful about the other.
    """
    path = make_docx(tmp_path, BODY)

    old = probe(path, anchors=("Table 1: Descriptive",))
    new = probe(path, ("Table 1: Descriptive",))

    assert old.phrases == new.phrases
    assert old.anchors == old.phrases
