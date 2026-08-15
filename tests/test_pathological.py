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
* tracked content in a table cell — python-docx reads it as
  empty;
* a FORMATTING-only revision — the old properties survive as a
  snapshot nested in the new ones, with no content marker to
  find, so a writer edited the past and left the present bare;
* ``w:id`` written second — attribute order means nothing in XML,
  and the patterns that hard-coded it matched nothing at all;
* a NESTED field — the outer field closed on the inner one's end;
* the same on a paragraph and on a run — ``<w:pPr>.*?</w:pPr>``
  closes on the snapshot, so five modules read a properties
  element cut in half: one copied the fragment into a rebuilt run
  and emitted XML with more ``<w:rPr>`` opens than closes.

The invariants asserted are the ones every mutator shares: the result
parses, and the visible text survives unless the operation is defined to
change it.
"""
from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from conftest import NS
from lxml import etree

from docxkit import tables
from docxkit._xml import visible_text
from docxkit.errors import DocxKitError
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

#: The same shape where a mutator actually reaches it. SPLIT_RUN has
#: been in this corpus since the beginning and never caught the linker
#: dropping a sibling w:t, because it holds no caption and no mention:
#: crossrefs.link is a NO-OP on it, so the specimen rode through every
#: invariant untested. A fixture only covers the code it reaches.
SPLIT_RUN_CAPTION = doc(
    p('<w:r><w:t xml:space="preserve">Table 1. </w:t>'
      '<w:t xml:space="preserve">Results by cohort</w:t>'
      '<w:footnoteReference w:id="4"/></w:r>'),
    p(r("See "),
      '<w:r><w:t xml:space="preserve">Table</w:t>'
      '<w:t xml:space="preserve"> 1</w:t><w:br/></w:r>',
      r(" for the detail.")))

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

#: A FORMATTING-only revision. Word stores the old properties as a
#: snapshot NESTED inside the new ones, so the cell carries a second
#: w:tcPr with its own borders and NO content marker at all — the
#: tracked-changes guard looked for insertions and called it clean.
PROPERTY_CHANGE_CELL = doc(
    "<w:tbl>"
    '<w:tblPr><w:tblW w:w="800" w:type="dxa"/></w:tblPr>'
    '<w:tblGrid><w:gridCol w:w="800"/></w:tblGrid>'
    '<w:tr><w:tc><w:tcPr><w:tcW w:w="800" w:type="dxa"/>'
    '<w:tcPrChange w:id="7" w:author="A" w:date="2026-01-01T00:00:00Z">'
    '<w:tcPr><w:tcBorders><w:bottom w:val="single" w:sz="4" '
    'w:space="0" w:color="auto"/></w:tcBorders></w:tcPr>'
    "</w:tcPrChange></w:tcPr>"
    + p(r("0.054")) + "</w:tc></w:tr></w:tbl>")

#: The same revision on a PARAGRAPH. `w:pPrChange` holds a complete
#: `w:pPr` of its own, so the first `</w:pPr>` in the string closes the
#: snapshot rather than the live properties — and every module that
#: stepped over the properties to reach a paragraph's content landed
#: inside the historical record instead.
PARAGRAPH_PROPERTY_CHANGE = doc(
    '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="40"/>'
    '<w:pPrChange w:id="11" w:author="A" w:date="2026-01-01T00:00:00Z">'
    '<w:pPr><w:jc w:val="left"/></w:pPr>'
    "</w:pPrChange></w:pPr>"
    + r("Table 1. Results") + "</w:p>",
    p(r("See Table 1 for the detail.")))

#: The same revision on a RUN, and the one that reached furthest. The
#: snapshot carries italics, a vertAlign and a w:lang — every property
#: the run writers look for — so reading the whole run answers each
#: question with the formatting the author REMOVED. `crossrefs` also
#: copies the matched properties into the runs it rebuilds around a
#: link, which spliced half an element into the document: the result
#: had one more `<w:rPr>` open than close and would not open in Word.
RUN_PROPERTY_CHANGE = doc(
    p('<w:r><w:rPr><w:b/>'
      '<w:rPrChange w:id="12" w:author="A" w:date="2026-01-01T00:00:00Z">'
      '<w:rPr><w:i/><w:vertAlign w:val="superscript"/>'
      '<w:lang w:val="en-GB"/></w:rPr>'
      "</w:rPrChange></w:rPr>"
      '<w:t xml:space="preserve">Table 2. Estimates</w:t></w:r>'),
    p(r("See Table 2 for the detail.")))

#: Attribute order carries no meaning in XML, so `w:id` need not come
#: first — and every pattern that assumed it did matched NOTHING here.
#: The comment count read zero and the scaffold builder died on max() of
#: an empty sequence; compare's integrity layer found no bookmarks at
#: all, which it reports as balanced.
ATTRIBUTE_ORDER = doc(
    p('<w:bookmarkStart w:name="Table1" w:id="4"/>',
      '<w:commentRangeStart w:id="0"/>',
      r("Table 1. Results"),
      '<w:commentRangeEnd w:id="0"/>',
      '<w:r><w:commentReference w:id="0"/></w:r>',
      '<w:bookmarkEnd w:id="4"/>'),
    p(r("See Table 1.")))

#: Fields NEST: Word writes a HYPERLINK inside a REF and anything at all
#: inside a TOC. Ending the outer field at the first `end` after its
#: `begin` closed it on the INNER field, yielding a fragment with two
#: begins and one end that never reached the content past the nest.
NESTED_FIELD = doc(
    p(r("see "),
      '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
      '<w:r><w:instrText xml:space="preserve"> REF Table1 \\h </w:instrText>'
      "</w:r>"
      '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
      '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
      '<w:r><w:instrText xml:space="preserve"> PAGEREF _Toc9 </w:instrText>'
      "</w:r>"
      '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
      "<w:r><w:t>12</w:t></w:r>"
      '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
      "<w:r><w:t>Table 1</w:t></w:r>"
      '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
      r(" above")),
    p(r("Table 1. Results")))

CORPUS = {
    "attribute_order": ATTRIBUTE_ORDER,
    "nested_field": NESTED_FIELD,
    "ghost_hyperlink": GHOST_HYPERLINK,
    "property_change": PROPERTY_CHANGE_CELL,
    "property_change_para": PARAGRAPH_PROPERTY_CHANGE,
    "property_change_run": RUN_PROPERTY_CHANGE,
    "styled_runs": STYLED_RUNS,
    "merged_cells": MERGED_CELLS,
    "nested_table": NESTED_TABLE,
    "split_run": SPLIT_RUN,
    "split_run_caption": SPLIT_RUN_CAPTION,
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


def refusing_is_safe(fn: Callable[[str], str]) -> Callable[[str], str]:
    """Wrap a mutator so a DELIBERATE refusal counts as leaving the
    document alone.

    A mutator that raises a DocxKitError on a specimen it cannot handle
    faithfully has done the safe thing: nothing was written, so parseable
    / text-preserving / idempotent all hold trivially. Only an
    uncontrolled exception is a failure. `crossrefs.unlink` refuses the
    both_link_forms specimen for exactly this reason — it cannot see
    field-form links, and removing the bookmarks alone would leave the
    links live while reporting success.
    """
    def run(xml: str) -> str:
        try:
            return fn(xml)
        except DocxKitError:
            return xml
    return run


def text_preserving_mutators():
    """(name, fn) — each takes a part's XML and returns it rewritten,
    with the visible text unchanged by definition."""
    from docxkit import crossrefs, hygiene
    from docxkit.edit import preserve_space
    return [
        ("crossrefs.link", lambda x: crossrefs.link(x)[0]),
        ("crossrefs.link_more", lambda x: crossrefs.link_more(x)[0]),
        ("crossrefs.unlink",
         refusing_is_safe(lambda x: crossrefs.unlink(x)[0])),
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
    try:
        out, _ = tables.bottom_border(table_doc, t)
    except Exception as exc:
        # a tracked table is REFUSED by every writer, loudly and alike
        assert "tracked" in str(exc), exc
        return
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


def test_linking_a_tracked_caption_keeps_the_properties_balanced():
    """The splice that produced a file Word would not open.

    ``crossrefs`` copies a run's properties into the runs it rebuilds
    around a new hyperlink. Read with a non-greedy close, those
    "properties" end at the snapshot's ``</w:rPr>`` — so the copy carries
    an open ``w:rPrChange`` and no close, and the document gained one
    more ``<w:rPr>`` open than it had closes. Caught only by parsing:
    every text-level check passes on XML this broken.
    """
    from docxkit import crossrefs
    out, _ = crossrefs.link(RUN_PROPERTY_CHANGE)
    parses(out)
    assert out.count("<w:rPr>") == out.count("</w:rPr>")
    # Linking SPLITS the caption run, and both halves carry the change —
    # that is what Word does to a split run, so the count rises. What may
    # never happen is a half element: every open still has its close, and
    # the revision is not quietly dropped either.
    assert out.count("<w:rPrChange") == out.count("</w:rPrChange>") >= 1


def test_a_snapshot_is_never_what_a_run_writer_rewrites():
    """Every run-property writer edits the live formatting.

    The snapshot in this fixture carries italics, a vertAlign and a
    w:lang deliberately: those are the three things the writers search
    for, and finding them in the historical record made one skip the run
    as "already done" and the others insert into the past.
    """
    from docxkit._table_layout import _run_superscripted
    from docxkit._xml import live_properties, own_properties
    from docxkit.edit import _run_italic, _run_vert_align

    run = ('<w:r><w:rPr><w:b/>'
           '<w:rPrChange w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
           '<w:rPr><w:i/><w:vertAlign w:val="superscript"/>'
           '<w:lang w:val="en-GB"/></w:rPr>'
           "</w:rPrChange></w:rPr><w:t>-0.250***</w:t></w:r>")

    for name, out, want in [
            ("italic", _run_italic(run), "<w:i/>"),
            ("vertAlign", _run_vert_align(run, "superscript"), "<w:vertAlign"),
            ("superscript", _run_superscripted(run), "<w:vertAlign")]:
        parses(f"<w:p {W_NS}>{out}</w:p>")
        own = own_properties(out, "rPr")
        assert own is not None, name
        # written to the formatting in force...
        assert want in live_properties(own[2]), f"{name}: skipped the run"
        # ...and the record of what the author changed is untouched
        assert out[out.index("<w:rPrChange"):] == \
            run[run.index("<w:rPrChange"):], f"{name}: rewrote the past"


def test_a_paragraph_writer_steps_over_the_whole_properties_element():
    """A mark placed after ``</w:pPr>`` — the live one, not the snapshot's.

    ``w:bookmarkStart`` inside ``w:pPr`` is schema-invalid, and the
    marker it anchors would not travel with the paragraph anyway.
    """
    from docxkit._cite_repair import _mark_para_head
    from docxkit.crossrefs import _wrap_paragraph_in_bookmark

    para = PARAGRAPH_PROPERTY_CHANGE[
        PARAGRAPH_PROPERTY_CHANGE.index("<w:p>"):
        PARAGRAPH_PROPERTY_CHANGE.index("</w:p>") + len("</w:p>")]
    for out in (_mark_para_head(para, "cite_x", 9),
                _wrap_paragraph_in_bookmark(para, "Table1", 9)):
        parses(f"<w:body {W_NS}>{out}</w:body>")
        assert out.index("<w:bookmarkStart") > out.rindex("</w:pPr>")


def test_own_properties_reads_the_element_not_the_snapshot_or_the_nest():
    """The one helper the five call sites now share."""
    from docxkit._xml import live_properties, own_properties

    # a nested table's cell properties are NOT this cell's
    outer = ('<w:tc><w:tcPr><w:tcW w:w="800" w:type="dxa"/></w:tcPr>'
             '<w:tbl><w:tr><w:tc><w:tcPr><w:tcBorders/></w:tcPr>'
             "<w:p/></w:tc></w:tr></w:tbl></w:tc>")
    own = own_properties(outer, "tcPr")
    assert own is not None and own[2] == '<w:tcW w:w="800" w:type="dxa"/>'

    # the empty form is properties, not their absence
    empty = own_properties("<w:tc><w:tcPr/><w:p/></w:tc>", "tcPr")
    assert empty == (6, 15, "")

    # no properties at all, and properties that are not the first child
    assert own_properties("<w:tc><w:p/></w:tc>", "tcPr") is None
    assert own_properties("<w:p><w:r/><w:pPr/></w:p>", "pPr") is None

    # and the live/past split
    centred = '<w:jc w:val="center"/>'
    inner = (centred + '<w:pPrChange w:id="1">'
             '<w:pPr><w:jc w:val="left"/></w:pPr></w:pPrChange>')
    assert live_properties(inner) == centred
    assert live_properties(centred) == centred


def test_a_prefix_number_never_links_a_longer_one():
    """"Table 1" is not the "Table 1" inside "Table 1.1" or "Table 1A".

    Refusing a following DIGIT keeps Table 1 out of Table 10 but not out
    of these: the match landed on a DIFFERENT exhibit, left the rest of
    its number as plain text, and then reported that exhibit as never
    mentioned. The reproduction linked Table 1 and orphaned ".1".
    """
    from docxkit import crossrefs

    d = doc(p(r("Table 1. Overall")), p(r("Table 1.1. Subsample")),
            p(r("Table 1A. Appendix")), p(r("Table 10. Robustness")),
            p(r("See Table 1.1, Table 1A, Table 10 and Table 1.")))
    out, rep = crossrefs.link(d)
    assert not rep.no_mention, rep.format()
    linked = dict(re.findall(
        r'<w:hyperlink w:anchor="([^"]+?)(?:txt)?">.*?<w:t[^>]*>([^<]+)</w:t>',
        out))
    for anchor, text in (("Table1", "Table 1"), ("Table1_1", "Table 1.1"),
                         ("Table1A", "Table 1A"), ("Table10", "Table 10")):
        assert linked.get(anchor) == text, (anchor, linked)


def test_a_mention_still_ends_at_a_full_stop():
    """The boundary refuses "1.1" without refusing "1." — by far the
    commonest thing after a mention is the end of the sentence."""
    from docxkit import crossrefs
    _, rep = crossrefs.link(
        doc(p(r("Table 1. Overall")), p(r("The estimates are in Table 1."))))
    assert not rep.no_mention, rep.format()


def test_ids_are_read_whatever_order_the_attributes_come_in():
    """`<w:comment w:author="A" w:id="7">` is as valid as the id-first
    form. Reading it as zero comments is not a cosmetic miscount: the
    scaffold builder took max() of an empty sequence and raised."""
    from docxkit._xml import BOOKMARK_END_ID_RE, BOOKMARK_START_ID_RE
    from docxkit.comments import _Scaffold
    from docxkit.tracked import package_counts

    com = ('<w:comments><w:comment w:author="A" w:id="7" '
           'w:date="2026-01-01T00:00:00Z" w:initials="A">'
           "<w:p><w:r><w:t>note</w:t></w:r></w:p></w:comment></w:comments>")
    parts = {"word/document.xml": ATTRIBUTE_ORDER.encode("utf-8"),
             "word/comments.xml": com.encode("utf-8")}

    assert package_counts(parts)["comments"] == 1
    assert _Scaffold.read(parts).next_id == 8
    assert BOOKMARK_START_ID_RE.findall(ATTRIBUTE_ORDER) == ["4"]
    assert BOOKMARK_END_ID_RE.findall(ATTRIBUTE_ORDER) == ["4"]


def test_a_nested_field_does_not_close_its_parent():
    """Depth, not the first end tag after the begin.

    The truncated outer span had two begins and one end and stopped
    short of the nested field's sibling content — so the repair that
    consumed it cut there, leaving the outer field's tail and its
    unmatched end marker behind.
    """
    from docxkit._xml import field_spans

    spans = field_spans(NESTED_FIELD)
    assert len(spans) == 2
    outer, inner = spans                       # document order, outer first
    assert outer[0] < inner[0] and outer[1] > inner[1]
    for *_, body in spans:
        assert body.count('w:fldCharType="begin"') == \
            body.count('w:fldCharType="end"'), body
    assert "Table 1" in visible_text(outer[2])   # reaches past the nest
    assert "Table 1" not in visible_text(inner[2])


def test_removing_an_outer_field_leaves_no_half_field_behind():
    from docxkit._cite_repair import remove_outer_field

    xml = doc(p(
        r("see "),
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> HYPERLINK "http://dead" '
        "</w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGEREF _Toc9 </w:instrText>'
        "</w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>12</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:hyperlink w:anchor="Smith2020"><w:r><w:t>Smith (2020)</w:t>'
        "</w:r></w:hyperlink>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
        r(" here")))
    out = remove_outer_field(xml, "http://dead", "Smith2020")
    parses(out)
    assert visible_text(out) == "see Smith (2020) here"
    for marker in ("fldChar", "instrText"):
        assert marker not in out, marker


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
