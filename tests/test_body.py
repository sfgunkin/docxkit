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


def test_cell_wraps_content_whose_tag_merely_starts_like_a_paragraph():
    """`<w:pPr`/`<w:pict` are not paragraphs.

    A prefix test on "<w:p" takes them for ready-made paragraph XML and
    leaves them unwrapped, landing a w:tc with no w:p in it — the exact
    "Word declares the document unreadable" failure this wrapping exists
    to prevent.
    """
    from docxkit.body import cell
    out = cell('<w:pict><v:shape id="x"/></w:pict>')
    assert "<w:p>" in out                       # the cell has a paragraph
    assert "&lt;w:pict&gt;" in out              # treated as text, escaped
    assert "<w:pict>" not in out                # never spliced in raw

    # a real paragraph is still passed through untouched
    passthrough = cell("<w:p><w:r><w:t>ready</w:t></w:r></w:p>")
    assert passthrough.count("<w:p>") == 1
    assert "&lt;" not in passthrough


@pytest.mark.parametrize("ready", ["<w:p/>", "<w:p\n  w:rsidR=\"1\"></w:p>"])
def test_cell_passes_through_a_paragraph_in_EVERY_spelling(ready):
    """The name was ended by a space or `>` only, so an EMPTY paragraph
    `<w:p/>` — the ordinary blank cell — or one whose name a newline
    ends was not a paragraph: it was escaped into a text run, and the
    cell showed its markup."""
    from docxkit.body import cell
    out = cell(ready)

    assert ready in out and "&lt;" not in out, out


def test_a_template_without_a_table_style_is_refused():
    """The equation-number carriers in a manuscript are borderless 1x2
    tables with no w:tblStyle. Cloning tables[-1] therefore hands back a
    template that renders a DATA table with no grid at all — valid
    markup, no complaint from anything, caught in a PDF render."""
    carrier = ('<w:tblPr><w:tblW w:w="5000" w:type="pct"/>'
               '<w:tblCellMar><w:left w:w="0" w:type="dxa"/></w:tblCellMar>'
               "</w:tblPr>")
    with pytest.raises(AnchorError, match="w:tblStyle"):
        table(["A", "B"], [["1", "2"]], tblpr=carrier)


def test_a_template_with_only_a_tblStyle_BAND_SIZE_is_refused_too():
    """Asked `"<w:tblStyle" in tblpr`, a tblPr whose only mention of a
    style is `w:tblStyleRowBandSize` — a sibling whose name begins with
    `tblStyle` — passed as styled, and the table rendered unstyled."""
    carrier = ('<w:tblPr><w:tblStyleRowBandSize w:val="1"/>'
               '<w:tblW w:w="5000" w:type="pct"/></w:tblPr>')
    with pytest.raises(AnchorError, match="w:tblStyle"):
        table(["A", "B"], [["1", "2"]], tblpr=carrier)


def test_a_deliberately_borderless_table_is_allowed():
    carrier = '<w:tblPr><w:tblW w:w="5000" w:type="pct"/></w:tblPr>'
    out = table(["A", "B"], [["1", "2"]], tblpr=carrier,
                require_style=False)
    assert "<w:tblStyle" not in out and "<w:tbl>" in out


def test_the_default_template_is_styled():
    assert "<w:tblStyle" in table(["A"], [["1"]])


# ------------------------------------------- properties worth cloning ----

def test_prose_props_skips_a_LINK_LABELS_properties():
    """The obvious version lifts the FIRST w:rPr in the paragraph, and a
    paragraph that opens on a citation is ordinary: its first run
    properties belong to the link, so the new paragraph renders blue and
    underlined, linking nowhere, with every text check passing."""
    from docxkit.body import prose_props

    p = ('<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>'
         '<w:hyperlink w:anchor="ref_B2020"><w:r><w:rPr>'
         '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>Bhalotra (2020)</w:t>'
         "</w:r></w:hyperlink>"
         '<w:r><w:rPr><w:i/></w:rPr><w:t> shows that</w:t></w:r></w:p>')

    ppr, rpr = prose_props(p)
    assert '<w:spacing w:after="120"/>' in ppr
    assert rpr == "<w:rPr><w:i/></w:rPr>", rpr
    assert "Hyperlink" not in rpr


def test_prose_props_skips_a_FIELD_form_label_too():
    from docxkit.body import prose_props

    p = ("<w:p>"
         '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
         r'<w:r><w:instrText xml:space="preserve"> HYPERLINK \l "x" '
         "</w:instrText></w:r>"
         '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
         '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
         "<w:t>Smith (2019)</w:t></w:r>"
         '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
         '<w:r><w:rPr><w:b/></w:rPr><w:t> argues</w:t></w:r></w:p>')

    assert prose_props(p)[1] == "<w:rPr><w:b/></w:rPr>"


def test_a_paragraph_that_is_ALL_link_answers_with_no_rPr():
    """No properties at all is a template a caller can see through; a
    link's are not."""
    from docxkit.body import prose_props

    p = ('<w:p><w:hyperlink w:anchor="a"><w:r><w:rPr>'
         '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>only</w:t></w:r>'
         "</w:hyperlink></w:p>")
    assert prose_props(p) == ("", "")


def test_prose_props_on_an_ordinary_paragraph():
    from docxkit.body import prose_props

    p = ('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
         '<w:r><w:rPr><w:b/></w:rPr><w:t>Table A4</w:t></w:r></w:p>')
    # BOTH wrapped: the pair goes straight to `para(run(t, rpr), ppr)`,
    # and a bare pPr made that write `<w:p><w:jc/>…`, which Word drops
    # silently (BACKLOG S2, 2026-09-01).
    assert prose_props(p) == ('<w:pPr><w:jc w:val="center"/></w:pPr>',
                              "<w:rPr><w:b/></w:rPr>")


# --- what the first mutation run found unasserted (2026-08-17, 14.7 %) ---
#
# The shape of a built table was pinned — counts of `w:tr`, `w:gridCol`,
# a gridSpan — and none of its NUMBERS were. Eleven mutants lived on the
# one line that sizes the grid.

def test_the_GRID_divides_the_text_column_between_the_columns():
    """A `w:gridCol` is a width, and Word lays the table out on it. The
    line computing it carried eleven live mutants — floor division into
    addition, into a shift, into a bitwise and — because every table
    test counted the columns and none read their width. A table whose
    grid says 9360 twips per column renders three times wider than the
    page."""
    t = table(["a", "b", "c"], [["1", "2", "3"]])

    assert t.count('<w:gridCol w:w="3120"/>') == 3       # 9360 // 3


def test_ONE_column_takes_the_WHOLE_text_column():
    """9360 twips, a US-Letter text column. Floor division hides a
    number that is off by one at every other width — 9361 // 3 is 3120
    too — so the single-column table is where the constant itself is
    readable."""
    t = table(["Note"], [["a"]])

    assert '<w:gridCol w:w="9360"/>' in t


def test_the_grid_is_sized_by_COLUMNS_not_by_HEADERS():
    """Grouped headings: three header cells over seven columns. Sizing
    by the header count would give each column more than double its
    width, and the table would run off the page."""
    t = table(["Country", "Gap", "OASI"], [["Albania"] + ["x"] * 6],
              spans=[1, 3, 3])

    assert t.count('<w:gridCol w:w="1337"/>') == 7       # 9360 // 7


def test_FEWER_spans_than_headers_is_refused_too():
    """`!=`, not `>`. A short `spans` list would otherwise reach the
    zip and fail there — as a ValueError about argument 2, from inside a
    builder, instead of the sentence naming what the caller got wrong."""
    with pytest.raises(AnchorError, match="3 headers but 2 spans"):
        table(["a", "b", "c"], [["1", "2", "3"]], spans=[1, 2])


def test_a_row_with_TOO_MANY_cells_is_refused():
    """`!=`, not `<`. A long row is the same lost value as a short one —
    a column inserted upstream and nothing told the header."""
    with pytest.raises(AnchorError, match="row 0 has 4 cells"):
        table(["a", "b", "c"], [["1", "2", "3", "4"]])


def test_a_PLAIN_cell_carries_no_gridSpan():
    """`span > 1`, and the default is 1. Mutated to `>=`, or to a default
    of 2, every ordinary cell claims to span a column it does not own and
    the row no longer lines up with the grid."""
    assert "gridSpan" not in cell("Albania")


def test_a_cell_KEEPS_a_tcPr_it_was_given():
    """`tcpr or <default>`. Mutated to `and`, a caller's cell properties
    — a shaded cell, a border — are silently replaced by the default."""
    mine = '<w:tcPr><w:shd w:val="clear" w:fill="D9D9D9"/></w:tcPr>'

    assert mine in cell("x", tcpr=mine)


def test_a_cell_given_no_tcPr_gets_an_AUTO_WIDTH_one():
    assert '<w:tcW w:w="0" w:type="auto"/>' in cell("x")


def test_a_spanning_cell_needs_somewhere_to_put_the_gridSpan():
    with pytest.raises(AnchorError, match="span needs a tcPr"):
        cell("x", span=2, tcpr="<w:tcPr2/>")


def test_insert_before_does_NOT_fold_typography_unless_asked():
    """`normalize` defaults to False here as everywhere: folding glyphs
    silently is how an anchor matches a paragraph the caller did not
    mean. The curly apostrophe is the one that keeps happening —
    autocorrect ran on some paragraphs and not others."""
    xml = "<w:body>" + para(run("workers’ productivity")) + "</w:body>"

    with pytest.raises(AnchorError):
        insert_before(xml, "workers' productivity", para(run("new")))

    assert "new" in insert_before(xml, "workers' productivity",
                                  para(run("new")), normalize=True)


def test_the_colon_refusal_QUOTES_the_anchor_it_refused():
    """The message is the whole value of the refusal: a build script
    passes several anchors, and "that paragraph ends in a colon" without
    saying WHICH sends the reader back through all of them."""
    xml = "<w:body>" + para(run("The index is defined as:")) + "</w:body>"

    with pytest.raises(AnchorError, match="insert_after\\('defined as'\\)"):
        insert_after(xml, "defined as", para(run("x")))


def test_a_LONG_anchor_is_cut_in_the_message_not_dumped():
    """40 characters. A build script anchors on whole sentences, and a
    refusal that reprints one buries the instruction after it."""
    sentence = ("The age-friendliness index is defined for every "
                "occupation in the sample as:")
    xml = "<w:body>" + para(run(sentence)) + "</w:body>"

    with pytest.raises(AnchorError) as exc:
        insert_after(xml, sentence, para(run("x")))

    quoted = str(exc.value).split("'")[1]
    assert quoted == sentence[:40], quoted


def test_prose_props_walks_PAST_a_styled_link_run_to_the_prose():
    """`continue`, not `break`. Word leaves runs carrying the Hyperlink
    character style with no `w:hyperlink` around them — a link the
    author deleted the address of. Stopping at the first one answers
    "no properties" for a paragraph that has them two runs later."""
    from docxkit.body import prose_props

    p = ('<w:p><w:pPr><w:jc w:val="both"/></w:pPr>'
         '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
         "<w:t>Bhalotra (2020)</w:t></w:r>"
         '<w:r><w:rPr><w:i/></w:rPr><w:t> shows that</w:t></w:r></w:p>')

    assert prose_props(p) == ('<w:pPr><w:jc w:val="both"/></w:pPr>',
                              "<w:rPr><w:i/></w:rPr>")


def test_an_ALL_LINK_paragraph_still_answers_with_its_pPr():
    """Only the rPr is refused. The paragraph properties — centred, the
    spacing — belong to the paragraph and are what a caller cloning a
    caption is usually after."""
    from docxkit.body import prose_props

    p = ('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
         '<w:hyperlink w:anchor="a"><w:r><w:rPr>'
         '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>only</w:t></w:r>'
         "</w:hyperlink></w:p>")

    assert prose_props(p) == ('<w:pPr><w:jc w:val="center"/></w:pPr>', "")


# --- the run of 2026-08-20: 2.4 %, and the one that was real ------------


def test_a_span_of_ONE_or_less_writes_no_gridSpan():
    """`span > 1`, not `span != 1`. A `w:gridSpan` of 0 is markup Word
    opens with a repair warning, and a caller computing a span — a
    header built from a group whose members were all filtered out — can
    hand this a zero without meaning anything by it.

    The upper side is pinned above; this is the side where an ordering
    comparison and an equality part company."""
    assert "gridSpan" not in cell("x", span=1, tcpr="<w:tcPr></w:tcPr>")
    assert "gridSpan" not in cell("x", span=0, tcpr="<w:tcPr></w:tcPr>")
    assert 'w:gridSpan w:val="2"' in cell("x", span=2,
                                          tcpr="<w:tcPr></w:tcPr>")


# Argued rather than pinned, from the same run:
#
# * `span: int = 1` in the signature, mutated to 0. The default reaches
#   one line — `if span > 1` — and 0 and 1 are the same answer to it.
# * `props.replace("<w:tcPr>", …, 1)` written 2. `props` is one cell's
#   properties element, which holds one opening `<w:tcPr>`.
# * `len(spans) != len(headers)` and `len(r) != columns` as `is not`.
#   Both sides are column counts, and CPython hands out one object per
#   integer below 257; a table with 257 columns is not a table.
# * `zip(headers, spans, strict=True)` written `strict=False`. The
#   length check four lines above has already raised for a table where
#   they differ, so the strictness is a second lock on a door that
#   cannot open.


# --- the pPr normalisation nothing had asked about (2026-09-18) ---------
#
# `para` learned to accept a bare pPr on 2026-09-01, after Parental_style
# shipped a title block Word had silently discarded. Three mutants lived
# on that one guard: the tests above pass a wrapped pPr to `table` and
# read `prose_props` back, and none of them asks what `para` itself
# writes for each of the three shapes of `ppr`.


def _children(para_xml: str) -> list[str]:
    """The DIRECT child tags of the `w:p`, which is the whole question:
    Word keeps schema-invalid children of `w:p` out of the render."""
    doc = MD.parseString(
        f"<w:document {NS}><w:body>{para_xml}</w:body></w:document>")
    p = doc.getElementsByTagName("w:p")[0]
    return [n.tagName for n in p.childNodes if n.nodeType == n.ELEMENT_NODE]


def test_NO_ppr_writes_no_properties_element_at_all():
    """`if ppr and …`, mutated to `if not ppr and …` and to
    `if ppr or …`. Both wrap the EMPTY string, so every paragraph this
    package builds without properties — which is nearly all of them —
    opens with an empty `<w:pPr></w:pPr>`.

    Asserted as the whole string: the mutants' paragraph is well-formed
    and reads right, so a shape test cannot see them.
    """
    assert para(run("hello")) == "<w:p><w:r><w:t>hello</w:t></w:r></w:p>"
    assert para() == "<w:p></w:p>"


def test_a_BARE_pPr_is_WRAPPED_so_Word_does_not_discard_it():
    """The defect the guard was written for (Parental_style, 2026-09-01):
    spliced in verbatim, a bare fragment became a direct child of `w:p`,
    which Word drops silently — the supplement's title block shipped
    left-aligned at 16pt and only a PDF raster caught it.

    `if ppr and not …` mutated to `if ppr and …` leaves the bare
    fragment unwrapped, which is that defect again.
    """
    p = para(run("Title"), '<w:jc w:val="center"/>')

    assert p == ('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                 "<w:r><w:t>Title</w:t></w:r></w:p>")
    _wellformed(p)
    assert _children(p) == ["w:pPr", "w:r"]


def test_a_pPr_that_ARRIVES_WRAPPED_is_not_wrapped_again():
    """The other half of the same guard, and the shape `prose_props`
    hands back — the pair is documented to go straight into `para`.

    Under `if ppr and ppr.lstrip().startswith("<w:pPr")` (the `not`
    dropped) and under `if ppr or not …`, it is wrapped a second time:
    `<w:pPr><w:pPr>…</w:pPr></w:pPr>` parses, so only counting the
    element says so, and a nested pPr is the discarded-properties defect
    one level down.
    """
    ppr = '<w:pPr><w:spacing w:after="120"/></w:pPr>'

    p = para(run("Body text"), ppr)

    assert p == f"<w:p>{ppr}<w:r><w:t>Body text</w:t></w:r></w:p>"
    assert p.count("<w:pPr>") == 1
    assert _children(p) == ["w:pPr", "w:r"]
