"""Invariants every mutator shares, over generated documents.

The hand-written fixtures cover the shapes someone thought of; this
covers the combinations nobody did. Three properties hold for every
mutator in the family:

1. the result parses;
2. the visible text is unchanged, unless the operation is defined to
   change it;
3. running it twice is the same as running it once.

Documents are generated from the pieces that have actually caused
trouble — curly quotes, non-breaking spaces, ampersands, en dashes,
captions, citations, merged cells — so a counter-example is something
a manuscript could really contain.
"""
from __future__ import annotations

import pytest
from conftest import NS
from lxml import etree

pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from docxkit import crossrefs, hygiene, tables
from docxkit._xml import _PPR_RANK, escape, visible_text
from docxkit.edit import preserve_space
from docxkit.revisions import W as _W

SETTINGS = settings(max_examples=60, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])

#: Characters that have each broken something: the curly apostrophe and
#: quotes Word autocorrects to, U+00A0 (which str.strip eats and XML does
#: not), the en dash, an ampersand (escaping), and ordinary prose.
GLYPHS = "abc XY.,()'’“” –&%-0123456789"

text = st.text(alphabet=GLYPHS, min_size=0, max_size=30)


@st.composite
def run_xml(draw: st.DrawFn) -> str:
    body = escape(draw(text))
    rpr = draw(st.sampled_from(
        ["", "<w:rPr><w:i/></w:rPr>",
         '<w:rPr><w:rFonts w:ascii="Arial Narrow"/><w:sz w:val="20"/>'
         "</w:rPr>"]))
    space = ' xml:space="preserve"' if body != body.strip() else ""
    return f"<w:r>{rpr}<w:t{space}>{body}</w:t></w:r>"


@st.composite
def paragraph_xml(draw: st.DrawFn) -> str:
    kind = draw(st.sampled_from(["prose", "caption", "mention", "linked"]))
    if kind == "caption":
        label = draw(st.sampled_from(["Table", "Figure"]))
        num = draw(st.sampled_from(["1", "2", "A1", "3.2"]))
        return (f"<w:p>{para_properties(draw)}<w:r><w:t>{label} {num}. "
                f"{escape(draw(text))}</w:t></w:r></w:p>")
    if kind == "mention":
        label = draw(st.sampled_from(["Table", "Figure"]))
        num = draw(st.sampled_from(["1", "2", "A1", "3.2"]))
        return (f'<w:p><w:r><w:t xml:space="preserve">see {label} {num} '
                f"below</w:t></w:r></w:p>")
    if kind == "linked":
        return ('<w:p><w:r><w:t>As </w:t></w:r>'
                '<w:hyperlink w:anchor="Table1"><w:r><w:t>Table 1</w:t>'
                "</w:r></w:hyperlink>"
                "<w:r><w:t> shows.</w:t></w:r></w:p>")
    runs = "".join(draw(st.lists(run_xml(), min_size=1, max_size=3)))
    return f"<w:p>{para_properties(draw)}{runs}</w:p>"


@st.composite
def table_xml(draw: st.DrawFn) -> str:
    cols = draw(st.integers(min_value=1, max_value=3))
    span = draw(st.booleans()) and cols > 1
    grid = "".join('<w:gridCol w:w="900"/>' for _ in range(cols))

    def cell(inner: str, k: int | None = None) -> str:
        s = f'<w:gridSpan w:val="{k}"/>' if k else ""
        return (f'<w:tc><w:tcPr><w:tcW w:w="900" w:type="dxa"/>{s}'
                f"</w:tcPr><w:p>{inner}</w:p></w:tc>")

    rows = []
    if span:
        rows.append("<w:tr>" + cell("<w:r><w:t>Group</w:t></w:r>", cols)
                    + "</w:tr>")
    for _ in range(draw(st.integers(min_value=1, max_value=3))):
        cells = "".join(cell(draw(run_xml())) for _ in range(cols))
        rows.append(f"<w:tr>{cells}</w:tr>")
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{cols * 900}" w:type="dxa"/>'
            f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>"
            + "".join(rows) + "</w:tbl>")


@st.composite
def document_xml(draw: st.DrawFn) -> str:
    blocks = draw(st.lists(st.one_of(paragraph_xml(), table_xml()),
                           min_size=1, max_size=5))
    return f"<w:document {NS}><w:body>" + "".join(blocks) \
        + "</w:body></w:document>"


def parses(xml: str) -> None:
    etree.fromstring(xml.encode("utf-8"))


TEXT_PRESERVING = [
    ("crossrefs.link", lambda x: crossrefs.link(x)[0]),
    ("crossrefs.link_more", lambda x: crossrefs.link_more(x)[0]),
    ("crossrefs.unlink", lambda x: crossrefs.unlink(x)[0]),
    ("preserve_space", lambda x: preserve_space(x)[0]),
]


@pytest.mark.parametrize("name,fn", TEXT_PRESERVING,
                         ids=[n for n, _ in TEXT_PRESERVING])
@SETTINGS
@given(xml=document_xml())
def test_a_mutator_never_breaks_the_document(name, fn, xml):
    parses(fn(xml))


@pytest.mark.parametrize("name,fn", TEXT_PRESERVING,
                         ids=[n for n, _ in TEXT_PRESERVING])
@SETTINGS
@given(xml=document_xml())
def test_a_mutator_never_changes_what_the_reader_sees(name, fn, xml):
    assert visible_text(fn(xml)) == visible_text(xml)


@pytest.mark.parametrize("name,fn", TEXT_PRESERVING,
                         ids=[n for n, _ in TEXT_PRESERVING])
@SETTINGS
@given(xml=document_xml())
def test_a_mutator_run_twice_is_a_mutator_run_once(name, fn, xml):
    once = fn(xml)
    assert fn(once) == once


@SETTINGS
@given(xml=document_xml())
def test_smarten_only_ever_rewrites_quotes(xml):
    out, _ = hygiene.smarten(xml)
    parses(out)
    plain = str.maketrans({"’": "'", "“": '"', "”": '"'})
    assert visible_text(out).translate(plain) == \
        visible_text(xml).translate(plain)


@SETTINGS
@given(xml=document_xml())
def test_the_table_mutators_hold_their_invariants(xml):
    read = tables.read_all(xml)
    if not read or not any(t.rows for t in read):
        return
    t = read[0]
    for fn in (lambda d, tb: tables.fit_columns(d, tb)[0],
               lambda d, tb: tables.bottom_border(d, tb)[0],
               lambda d, tb: tables.superscript_stars(d, tb)[0]):
        try:
            out = fn(xml, t)
        except Exception as exc:
            # the documented refusals, and nothing else
            assert any(w in str(exc) for w in
                       ("tracked", "no cell content", "no tblGrid",
                        "no rows")), exc
            continue
        parses(out)
        assert visible_text(out) == visible_text(xml)


@SETTINGS
@given(xml=document_xml())
def test_reading_a_document_never_raises(xml):
    """read_all and find_captions run over every part of every paper;
    a crash there stops a build dead."""
    tables.read_all(xml)
    crossrefs.find_captions(xml)
    crossrefs.audit(xml)


# --- what the generated documents were missing (2026-08-19) ------------
#
# The generator above builds paragraphs out of runs, captions, mentions
# and links, which is what the mutators READ. What they WRITE into is a
# `w:pPr`, and no generated paragraph had one — so the invariant that
# has now cost this package two S1s (a property spliced into the wrong
# place in CT_PPr, which Word drops on the next save) had no
# counter-example to find.
#
# Both defects were found by hand, on a manuscript, after shipping:
# `keepNext` written into the middle of a caption's style NAME, and a
# table width written ahead of the `tblStyle` that CT_TblPr wants first.
# The rule is mechanical and the check is three lines.

_PPR_SAMPLE = [
    "",
    '<w:pPr><w:pStyle w:val="Caption"/></w:pPr>',
    '<w:pPr><w:pStyle w:val="BodyText"/><w:spacing w:before="120"/>'
    '<w:jc w:val="both"/></w:pPr>',
    '<w:pPr><w:keepNext/><w:spacing w:after="0"/></w:pPr>',
    '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>'
    "</w:pPr>",
    '<w:pPr><w:spacing w:before="120"/><w:rPr><w:b/></w:rPr></w:pPr>',
    '<w:pPr><w:jc w:val="center"/><w:sectPr><w:pgSz w:w="12240"/>'
    "</w:sectPr></w:pPr>",
]


def para_properties(draw: st.DrawFn) -> str:
    """A `w:pPr` Word could have written, or none at all."""
    return draw(st.sampled_from(_PPR_SAMPLE))


def ppr_order_holds(xml: str) -> None:
    """Every `w:pPr` in `xml` lists its children in CT_PPr order.

    The schema is a SEQUENCE: Word reads the properties in order and
    drops the first one that arrives out of turn, silently, on the next
    save. Nothing in a lint or a glyph check sees that — the document
    parses, the text is identical, and the formatting is gone.
    """
    root = etree.fromstring(xml.encode("utf-8"))
    for ppr in root.iter(_W + "pPr"):
        ranks = [_PPR_RANK.get(etree.QName(child).localname, -1)
                 for child in ppr if isinstance(child.tag, str)]
        known = [r for r in ranks if r >= 0]
        assert known == sorted(known), (
            "CT_PPr is a sequence and this one is out of order: "
            + ", ".join(etree.QName(c).localname for c in ppr
                        if isinstance(c.tag, str)))


@SETTINGS
@given(xml=document_xml())
def test_the_generated_documents_are_themselves_in_order(xml):
    """The generator is part of the check: a fixture that is already
    wrong cannot prove a mutator kept it right."""
    ppr_order_holds(xml)


@pytest.mark.parametrize("name,fn", TEXT_PRESERVING,
                         ids=[n for n, _ in TEXT_PRESERVING])
@SETTINGS
@given(xml=document_xml())
def test_a_mutator_leaves_every_pPr_in_SCHEMA_ORDER(name, fn, xml):
    ppr_order_holds(fn(xml))


@SETTINGS
@given(xml=document_xml())
def test_table_spacing_holds_the_same_three_invariants(xml):
    """It writes `w:spacing` into paragraphs that may already carry a
    style, a justification or a section break — which is the shape the
    order rule is about."""
    out, _report = hygiene.table_spacing(xml)

    parses(out)
    assert visible_text(out) == visible_text(xml)
    ppr_order_holds(out)
    again, _ = hygiene.table_spacing(out)
    assert again == out, "not idempotent"


def test_the_order_CHECK_can_fail():
    """A checker nothing has seen fail is a checker that passes. `jc`
    before `pStyle` is the shape both of this package's CT_PPr defects
    took: Word parses the paragraph, drops the property that arrived out
    of turn on the next save, and reports nothing."""
    bad = (f"<w:document {NS}><w:body><w:p><w:pPr>"
           '<w:jc w:val="both"/><w:pStyle w:val="Caption"/>'
           "</w:pPr></w:p></w:body></w:document>")

    with pytest.raises(AssertionError, match="out of order: jc, pStyle"):
        ppr_order_holds(bad)
