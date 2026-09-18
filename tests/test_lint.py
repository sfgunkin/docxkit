"""Each check corresponds to markup Word refuses to open."""
from __future__ import annotations

import pytest
from conftest import NS, dele, ins, make_parts, para, para_mark_ins, run

from docxkit.body import para as bpara
from docxkit.body import run as brun
from docxkit.lint import audit_parts, lint_parts

lxml_etree = pytest.importorskip("lxml.etree")


def _parts(body: str, **extra: str) -> dict[str, bytes]:
    parts = make_parts(body)
    for name, xml in extra.items():
        parts[f"word/{name}.xml"] = xml.encode("utf-8")
    return parts


# --- the rule TABLES -----------------------------------------------------
#
# `lint` is a rule engine: every check is a walk over a tag table, and
# cosmic-ray plans no mutant on a tuple's members. The data census of
# 2026-09-18 took each of the 55 members out alone and ran this harness:
# 39 of them could go with every test green — `w:trPr` out of the marker
# parents, so every tracked ROW insertion reads as an empty `w:ins`;
# ENDNOTES and COMMENTS out of `_PARTS`, so two of the four parts are
# never read at all; seven of the nine CT_PPr names; ten of the eleven
# stray properties. `revision/_losses` lost `m:t` from its glyph walk the
# same way.
#
# So each table is held to its CONTENTS, which is the claim it makes —
# `test_text_parts_covers_what_a_reader_reads` in `test_part_names.py` is
# the same shape one module over. Not parametrized OVER the table: a test
# that draws its cases from the list it is checking loses a case when the
# list loses a member, and passes.


def test_the_PARTS_read_are_the_four_text_bearing_ones():
    """A part missing from this tuple is a part nothing lints, silently:
    the walk reports on the three it has and the report looks clean."""
    from docxkit._xml import COMMENTS, DOCUMENT, ENDNOTES, FOOTNOTES
    from docxkit.lint import _PARTS

    assert _PARTS == (DOCUMENT, FOOTNOTES, ENDNOTES, COMMENTS)


def test_the_BLOCK_CONTAINERS_are_the_five_that_hold_blocks_only():
    from docxkit.lint import _BLOCK_CONTAINERS

    assert _BLOCK_CONTAINERS == ("footnote", "endnote", "body", "tc",
                                 "comment")


def test_the_RUN_LEVEL_tags_are_the_four_plus_the_two_math_ones():
    from docxkit.lint import _RUN_LEVEL, _RUN_LEVEL_MATH

    assert _RUN_LEVEL == ("r", "ins", "del", "hyperlink")
    assert _RUN_LEVEL_MATH == ("oMath", "oMathPara")


def test_the_CT_PPr_names_that_must_precede_rPr_are_the_nine():
    """The schema's order, and the list check 5 is: a name that falls
    out stops being an ordering error anywhere in the corpus."""
    from docxkit.lint import _PPR_BEFORE_RPR

    wanted = frozenset({
        "pStyle", "keepNext", "keepLines", "numPr", "spacing", "ind", "jc",
        "outlineLvl", "contextualSpacing"})

    assert wanted == _PPR_BEFORE_RPR


def test_the_STRAY_paragraph_properties_are_those_nine_and_eleven_more():
    """Check 1b's table: a property sitting directly in `w:p`, which
    Word drops in silence. Built from `_PPR_BEFORE_RPR` plus the rest of
    CT_PPr a builder reaches for, and `w:rPr` is deliberately NOT in it —
    it is the paragraph mark's own run properties and every tracked
    paragraph-mark revision carries one."""
    from docxkit.lint import _PPR_BEFORE_RPR, _PPR_STRAYS, W

    extras = {"pageBreakBefore", "widowControl", "pBdr", "shd", "tabs",
              "suppressLineNumbers", "textAlignment", "mirrorIndents",
              "adjustRightInd", "snapToGrid", "bidi"}
    wanted = frozenset(W + t for t in _PPR_BEFORE_RPR | extras)

    assert wanted == _PPR_STRAYS
    assert W + "rPr" not in _PPR_STRAYS


def test_the_PROPERTIES_elements_and_their_OWNERS_are_the_five():
    """7b walks the properties elements; 7c asks which element may carry
    one. Two tables about the same five, and they have to agree."""
    from docxkit.lint import _OWNER, _PROPS

    assert _PROPS == ("tcPr", "rPr", "pPr", "trPr", "tblPr")
    assert _OWNER == {"tc": "tcPr", "tr": "trPr", "tbl": "tblPr",
                      "p": "pPr", "r": "rPr"}
    assert set(_OWNER.values()) == set(_PROPS)


def test_the_BLOCK_CHILDREN_a_revision_may_not_hold_are_the_four():
    from docxkit.lint import _BLOCK_CHILDREN, W

    wanted = frozenset({W + "p", W + "tbl", W + "tr", W + "tc"})

    assert wanted == _BLOCK_CHILDREN


def test_the_MARKER_PARENTS_are_the_RUN_and_the_ROW_properties():
    """A revision inside one of these is a MARK, not a range: the
    paragraph mark's own `w:rPr` and the row's `w:trPr`. Losing either
    makes every marker of that kind read as an empty revision, which is
    a refusal on a file nothing is wrong with — the defect this list
    exists to prevent, which the census could take `w:trPr` out of with
    the whole suite green."""
    from docxkit.lint import _MARKER_PARENTS, W

    wanted = frozenset({W + "rPr", W + "trPr"})

    assert wanted == _MARKER_PARENTS


def test_a_tracked_ROW_revision_is_a_marker_and_not_an_empty_revision():
    """The behaviour behind the table above, on the half the harness
    could not see: Word marks an inserted table row with a self-closing
    `w:ins` inside the row's `w:trPr`, and every redline that adds a row
    carries one."""
    row = ('<w:tbl><w:tr><w:trPr><w:ins w:id="9" w:author="A" '
           'w:date="d"/></w:trPr><w:tc><w:p>' + run("a new row")
           + "</w:p></w:tc></w:tr></w:tbl>")

    assert lint_parts(_parts(para(run("prose")) + row)) == []


def test_EVERY_text_bearing_part_is_linted_not_just_the_body():
    """Two of the four parts were unpinned: the walk reported on the
    ones it had and a document whose only damage was in the endnotes or
    in a comment read as clean."""
    edge = run(" leading space")          # check 3b, in whichever part
    endnotes = (f'<w:endnotes {NS}><w:endnote w:id="2"><w:p>{edge}'
                "</w:p></w:endnote></w:endnotes>")
    comments = (f'<w:comments {NS}><w:comment w:id="1"><w:p>{edge}'
                "</w:p></w:comment></w:comments>")

    for part, xml in (("endnotes", endnotes), ("comments", comments)):
        problems = lint_parts(_parts(para(run("clean")), **{part: xml}))
        assert any("edge whitespace" in p for p in problems), part


@pytest.mark.parametrize("kind", ["rPrChange", "pPrChange"])
def test_a_FORMATTING_revision_counts_toward_the_duplicate_id_check(kind):
    """The walk collects ids from four kinds and only the two CONTENT
    ones were pinned: it could stop reading either formatting kind with
    the suite green. Word gives a `w:rPrChange` or a `w:pPrChange` an id
    like any other revision, and two sharing one is what check 8 exists
    for — Word merges or drops them.

    One paragraph per revision, because a `w:pPrChange` lives in the
    paragraph's own `w:pPr` and a paragraph has one.
    """
    inner = ('<w:rPr><w:rPrChange w:id="7" w:author="A" w:date="d">'
             "<w:rPr/></w:rPrChange></w:rPr>" if kind == "rPrChange"
             else '<w:pPr><w:pPrChange w:id="7" w:author="A" w:date="d">'
                  "<w:pPr/></w:pPrChange></w:pPr>")
    one = (f"<w:p>{inner}" + run("a") + "</w:p>" if kind == "pPrChange"
           else f"<w:p><w:r>{inner}<w:t>a</w:t></w:r></w:p>")

    problems = lint_parts(_parts(one + one))

    assert any("duplicate revision w:id" in p for p in problems), problems


def test_clean_document_reports_nothing():
    assert lint_parts(_parts(para(run("ordinary prose")))) == []


def test_bare_w_t_with_edge_whitespace_is_flagged():
    """OOXML trims it, so the space survives in the tool that wrote it but is
    dropped by Word and by CompareDocuments. On the LE paper this looked like
    recurring "Word damage" for seven author rounds and shipped four typos."""
    problems = lint_parts(_parts(para(run(" Only after the citation"))))
    assert any("edge whitespace" in p for p in problems), problems


def test_edge_whitespace_is_fine_when_preserved():
    parts = _parts(para(run(" Only after the citation", preserve=True)))
    assert lint_parts(parts) == []


def test_interior_whitespace_is_not_flagged():
    assert lint_parts(_parts(para(run("two words")))) == []


def test_nbsp_is_not_edge_whitespace():
    """U+00A0 is an ordinary character to XML: nothing trims it, so it needs
    no xml:space="preserve". Word fills empty table cells with one, and
    flagging those buried the real hits in noise."""
    assert lint_parts(_parts(para(run(" ")))) == []
    assert lint_parts(_parts(para(run(" leading")))) == []


def test_the_builder_output_passes_the_rule():
    """docxkit.body must not emit markup its own linter rejects."""
    assert lint_parts(_parts(bpara(brun(" leading space")))) == []


def test_run_level_child_directly_in_a_block_container():
    """A w:r inside w:footnote (not wrapped in w:p) makes Word reject the
    part outright."""
    foot = (f'<w:footnotes {NS}><w:footnote w:id="2">'
            f"{run('stray run')}</w:footnote></w:footnotes>")
    problems = lint_parts(_parts(para(run("x")), footnotes=foot))
    assert any("run-level child" in p for p in problems)


def test_empty_revision_that_is_not_a_marker():
    empty_ins = ('<w:p><w:ins w:id="9" w:author="A" w:date="d">'
                 "</w:ins></w:p>")
    body = para(run("a")) + empty_ins
    assert any("empty w:ins" in p for p in lint_parts(_parts(body)))


def test_paragraph_mark_revision_is_a_legitimate_marker():
    """A self-closing w:ins inside w:rPr marks an inserted paragraph mark
    and must not be flagged."""
    body = ('<w:p><w:pPr><w:rPr><w:ins w:id="9" w:author="A" w:date="d"/>'
            "</w:rPr></w:pPr>" + run("tail") + "</w:p>")
    assert audit_parts(_parts(body)) == []


def test_a_paragraph_mark_MARKER_is_not_an_empty_revision_TO_LINT():
    """For `parent.tag if parent is not None else None` read as `parent
    is None`: `parent_tag` is then None for every revision, no revision
    matches `_MARKER_PARENTS`, and the markers stop being skipped.

    The marker test above asks `audit_parts`, which never runs check 2
    at all — so nothing in this harness put a self-closing `w:ins`
    inside a `w:rPr` through `lint`. Every tracked paragraph mark in
    every redline is that shape, and reported as an empty w:ins they
    would fail `revision validate`'s first gate on every round.
    """
    body = para_mark_ins() + para(run("ordinary prose"))

    assert lint_parts(_parts(body)) == []


@pytest.mark.parametrize("name,stray", [
    ("jc", '<w:jc w:val="center"/>'),
    ("shd", '<w:shd w:val="clear" w:fill="D9D9D9"/>'),
])
def test_a_paragraph_PROPERTY_sitting_directly_in_the_paragraph(name, stray):
    """Check 1b, which had no test in this harness at all, and
    `_PPR_STRAYS = frozenset(W + t for t in _PPR_BEFORE_RPR | {...})`
    read as `&` (the two halves are disjoint, so the set empties and 1b
    sees nothing ever again) and as `-` (the second half goes).

    One tag from each half, because only a tag from the second can tell
    `-` from the union: `w:jc` is in `_PPR_BEFORE_RPR` and `w:shd` is
    named only in the rest of CT_PPr beside it. Word keeps the runs and
    DISCARDS the property without a word — Parental_style's supplement
    shipped a title block at the default style for it.
    """
    body = ('<w:p><w:pPr><w:jc w:val="both"/></w:pPr>'
            + stray + run("a title") + "</w:p>")

    problems = lint_parts(_parts(body))

    assert len(problems) == 1, problems
    assert problems[0].startswith(f"w:{name} sits directly in w:p")
    assert "Word drops it silently" in problems[0]


def test_deleted_text_must_be_delText():
    """A w:t inside w:del renders as live text that cannot be rejected."""
    body = ('<w:p><w:del w:id="9" w:author="A" w:date="d">'
            "<w:r><w:t>should have been delText</w:t></w:r>"
            "</w:del></w:p>")
    assert any("should be w:delText" in p for p in lint_parts(_parts(body)))


def test_block_element_inside_a_run_level_revision():
    body = ('<w:p><w:ins w:id="9" w:author="A" w:date="d">'
            + para(run("a whole paragraph")) + "</w:ins></w:p>")
    assert any("block w:p inside run-level" in p
               for p in lint_parts(_parts(body)))


def test_ppr_child_order_violation():
    """CT_PPr fixes the order: jc, spacing, ind and friends precede rPr."""
    body = ("<w:p><w:pPr><w:rPr><w:b/></w:rPr>"
            '<w:jc w:val="center"/></w:pPr>' + run("x") + "</w:p>")
    problems = lint_parts(_parts(body))
    assert any("after w:rPr" in p and "jc" in p for p in problems)


def test_ppr_in_the_right_order_is_accepted():
    body = ('<w:p><w:pPr><w:jc w:val="center"/><w:rPr><w:b/></w:rPr>'
            "</w:pPr>" + run("x") + "</w:p>")
    assert lint_parts(_parts(body)) == []


def test_rprchange_must_be_last():
    body = ('<w:p><w:r><w:rPr><w:rPrChange w:id="9" w:author="A" '
            'w:date="d"><w:rPr/></w:rPrChange><w:b/></w:rPr>'
            "<w:t>x</w:t></w:r></w:p>")
    assert any("rPrChange is not the last child" in p
               for p in lint_parts(_parts(body)))


def test_empty_omath_shell():
    """An equation with no text renders as garbage, or vanishes."""
    body = ('<w:p><m:oMath xmlns:m="http://schemas.openxmlformats.org/'
            'officeDocument/2006/math"><m:r><m:t></m:t></m:r></m:oMath>'
            "</w:p>")
    assert any("empty m:oMath shell" in p for p in lint_parts(_parts(body)))


def test_duplicate_revision_ids_across_the_package():
    """Word merges or drops revisions that share an id."""
    body = para(run("a"), ins("x", rid=7)) + para(dele("y", rid=7))
    problems = lint_parts(_parts(body))
    assert any("duplicate revision w:id" in p for p in problems)


def test_unique_revision_ids_are_fine():
    body = para(run("a"), ins("x", rid=7)) + para(dele("y", rid=8))
    assert lint_parts(_parts(body)) == []


def test_malformed_xml_is_reported_not_raised():
    parts = make_parts(para(run("x")))
    parts["word/document.xml"] = b"<w:document><w:body><w:p></w:document>"
    problems = lint_parts(parts)
    assert len(problems) == 1
    assert "not well-formed XML" in problems[0]


def test_the_advisory_half_reports_the_parse_failure_too():
    """`audit_parts` dropped the message and audited an EMPTY list of
    roots: "no duplicate bookmark names" for a document that could not
    be read at all. It is public API, and the duplicate-bookmark gate
    is a caller that reaches it on its own."""
    parts = make_parts(para(run("x")))
    parts["word/document.xml"] = b"<w:document><w:body><w:p></w:document>"
    problems = audit_parts(parts)
    assert len(problems) == 1
    assert "not well-formed XML" in problems[0]


def test_several_problems_are_all_reported():
    body = ('<w:p><w:del w:id="9" w:author="A" w:date="d">'
            "<w:r><w:t>bad</w:t></w:r></w:del></w:p>"
            '<w:p><w:pPr><w:rPr/><w:jc w:val="center"/></w:pPr></w:p>')
    problems = lint_parts(_parts(body))
    assert len(problems) >= 2


def test_an_empty_object_inside_a_surviving_equation_is_reported():
    """The check used to ask only whether a WHOLE equation had lost its
    text, which passes an equation carrying an emptied fraction — and
    Word draws that as a blank box beside the real content. On the DSI
    paper the split was 53 wholly-empty against 121 empty children, so
    the whole-equation test cleared the large majority of the damage."""
    body = ("<w:p><m:oMath>"
            "<m:f><m:num/><m:den/></m:f>"
            "<m:r><m:t>x</m:t></m:r>"
            "</m:oMath></w:p>")
    problems = lint_parts(_parts(body))
    assert any("empty math object" in p for p in problems), problems


def test_a_full_equation_is_not_reported_as_having_empty_objects():
    body = ("<w:p><m:oMath>"
            "<m:f><m:num><m:r><m:t>a</m:t></m:r></m:num>"
            "<m:den><m:r><m:t>b</m:t></m:r></m:den></m:f>"
            "</m:oMath></w:p>")
    assert lint_parts(_parts(body)) == []


def test_a_document_carrying_an_external_entity_is_refused(tmp_path):
    """The XXE answer, pinned — because the "fix" for it is a regression.

    A review will propose `XMLParser(resolve_entities=False, ...)`
    everywhere. lxml's DEFAULTS already refuse this file: `load_dtd` is
    off, so the declaration is never registered and the reference does
    not resolve. With `resolve_entities=False` the same document PARSES
    and `&xxe;` survives as literal text — the refusal below becomes an
    acceptance. See the section in CONTRIBUTING.md.
    """
    from docxkit.errors import PackageError
    from docxkit.package import malformed_parts, write_docx

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    hostile = (
        '<?xml version="1.0"?>'
        f'<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>'
        f"<w:document {NS}><w:body>{para(run('&xxe;'))}</w:body>"
        "</w:document>")
    parts = {"[Content_Types].xml": b"<Types/>",
             "word/document.xml": hostile.encode("utf-8")}

    problems = lint_parts(dict(parts))
    assert problems and "not well-formed" in problems[0]
    assert malformed_parts(dict(parts))
    with pytest.raises(PackageError, match="malformed XML"):
        write_docx(tmp_path / "out.docx", dict(parts))
    assert not (tmp_path / "out.docx").exists()
    # and nothing anywhere read the file it pointed at
    assert "TOP-SECRET" not in " ".join(problems)


def test_a_nonbreaking_space_counts_as_a_glyph():
    """A spacer run is deliberate typography, not an empty shell."""
    body = ("<w:p><m:oMath><m:r><m:t> </m:t></m:r>"
            "<m:r><m:t>x</m:t></m:r></m:oMath></w:p>")
    assert lint_parts(_parts(body)) == []


# --- what the first mutation run found (2026-08-17, 8.3 % real survival) --
#
# Two checks had NO test — 7b and 7c, the ones added for the "unreadable
# content" failures — and the sweep said so plainly: emptying their loops
# changed nothing anyone could see. The rest is the usual pattern, a
# check asserted on the case it FIRES on and never on the case it must
# stay quiet for.

def _cell(inner: str) -> str:
    return f"<w:tbl><w:tr><w:tc>{inner}</w:tc></w:tr></w:tbl>"


def test_a_properties_element_carrying_a_child_TWICE_is_reported():
    """Two w:tcBorders in one w:tcPr is schema-invalid and Word calls the
    document unreadable. A border writer that matched the expanded
    <w:tcBorders> and not the empty <w:tcBorders/> put a second one in."""
    body = _cell("<w:tcPr><w:tcBorders/><w:tcBorders/></w:tcPr>"
                 + para(run("x")))

    problems = lint_parts(_parts(body))

    assert problems == ["w:tcPr carries two w:tcBorders children "
                        "(each may appear once)"]


def test_a_properties_element_with_DISTINCT_children_is_fine():
    body = _cell("<w:tcPr><w:tcBorders/><w:tcW w:w=\"0\" w:type=\"auto\"/>"
                 "</w:tcPr>" + para(run("x")))

    assert lint_parts(_parts(body)) == []


def test_a_cell_carrying_TWO_tcPr_elements_is_reported():
    """7b cannot see this one: it inspects a properties element's
    children, and here the properties element itself is doubled. A
    self-closing <w:tcPr/> read as "absent" got a second one prepended
    beside it."""
    body = _cell("<w:tcPr/><w:tcPr/>" + para(run("x")))

    problems = lint_parts(_parts(body))

    assert problems == ["w:tc carries 2 w:tcPr elements (it may carry one)"]


def test_ONE_properties_element_per_owner_is_fine():
    body = _cell("<w:tcPr/>" + para(run("x")))

    assert lint_parts(_parts(body)) == []


def test_a_paragraph_carrying_two_pPr_elements_is_reported():
    """Every owner in the table, not just cells."""
    body = "<w:p><w:pPr/><w:pPr/>" + run("x") + "</w:p>"

    assert lint_parts(_parts(body)) == [
        "w:p carries 2 w:pPr elements (it may carry one)"]


def test_a_LONGER_pPr_in_the_right_order_is_still_accepted():
    """The order check slices the children AFTER w:rPr, and with rPr at
    index 0 or 1 an arithmetic slip on that index reads the same. With
    three elements before it, `index & 1` and friends hand back the whole
    list — and every correctly-ordered paragraph is reported wrong."""
    body = ('<w:p><w:pPr><w:pStyle w:val="Body"/><w:keepNext/>'
            '<w:spacing w:after="120"/><w:rPr><w:b/></w:rPr></w:pPr>'
            + run("x") + "</w:p>")

    assert lint_parts(_parts(body)) == []


def test_the_pPr_order_report_names_ONLY_what_is_out_of_place():
    body = ('<w:p><w:pPr><w:pStyle w:val="Body"/><w:keepNext/>'
            '<w:rPr><w:b/></w:rPr><w:spacing w:after="120"/></w:pPr>'
            + run("x") + "</w:p>")

    assert lint_parts(_parts(body)) == [
        "w:pPr: ['spacing'] after w:rPr (CT_PPr order)"]


def test_an_rPr_ENDING_in_rPrChange_is_accepted():
    """The check reads `kids[-1] != "rPrChange"`, and `!=` on two equal
    strings built by slicing is not `is not` — the identity version calls
    every correctly-formed tracked run malformed."""
    body = ('<w:p><w:r><w:rPr><w:b/><w:rPrChange w:id="9" w:author="A" '
            'w:date="d"><w:rPr/></w:rPrChange></w:rPr>'
            "<w:t>x</w:t></w:r></w:p>")

    assert lint_parts(_parts(body)) == []


def test_rPrChange_followed_by_a_LATER_SORTING_sibling_is_reported():
    """`!=`, not `<`: `w:sz` sorts after `rPrChange` and an ordering
    comparison would call that pair fine."""
    body = ('<w:p><w:r><w:rPr><w:rPrChange w:id="9" w:author="A" '
            'w:date="d"><w:rPr/></w:rPrChange><w:sz w:val="20"/></w:rPr>'
            "<w:t>x</w:t></w:r></w:p>")

    assert any("rPrChange is not the last child" in p
               for p in lint_parts(_parts(body)))


def test_TRAILING_edge_whitespace_is_flagged_like_leading():
    """`text != text.strip()`. An ordering comparison catches the leading
    case and misses the trailing one — ' a' sorts before 'a', 'a ' after
    — and trailing is the commoner half: it is what a sentence built by
    concatenation ends with."""
    problems = lint_parts(_parts(para(run("ending in a space "))))

    assert any("edge whitespace" in p for p in problems), problems


def test_the_whitespace_report_CUTS_the_offending_text():
    """Thirty characters. A paragraph of prose printed in full, once per
    hit, is how a lint report stops being read."""
    long_text = "  " + "a sentence that goes on and on " * 4

    problems = lint_parts(_parts(para(run(long_text))))

    quoted = problems[0].split("(")[1].split(")")[0]
    assert quoted == repr(long_text[:30]), quoted


def test_a_MATH_element_directly_in_a_block_container_is_reported():
    """`_RUN_LEVEL_TAGS` unions the w: run tags with the m: math ones,
    and set arithmetic that dropped the math half would leave a bare
    equation sitting in a table cell unreported."""
    body = _cell('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
                 'officeDocument/2006/math"><m:r><m:t>x</m:t></m:r>'
                 "</m:oMath>")

    assert lint_parts(_parts(body)) == [
        "w:tc has run-level child oMath (must be inside w:p)"]


def test_a_revision_after_a_MARKER_is_still_examined():
    """`continue`, not `break`: the marker case is the FIRST thing many
    documents carry — an inserted paragraph mark in the opening
    paragraph — and stopping there would skip every revision after it."""
    marker = ('<w:p><w:pPr><w:rPr><w:ins w:id="9" w:author="A" w:date="d"/>'
              "</w:rPr></w:pPr>" + run("first") + "</w:p>")
    empty = '<w:p><w:ins w:id="10" w:author="A" w:date="d"></w:ins></w:p>'

    assert any("empty w:ins" in p
               for p in lint_parts(_parts(marker + empty)))


def test_a_revision_after_an_rPrChange_is_still_examined():
    """The same walk carries w:rPrChange and w:pPrChange, which are not
    ranges and are skipped — but only this one."""
    change = ('<w:p><w:r><w:rPr><w:b/><w:rPrChange w:id="9" w:author="A" '
              'w:date="d"><w:rPr/></w:rPrChange></w:rPr><w:t>x</w:t>'
              "</w:r></w:p>")
    empty = '<w:p><w:del w:id="10" w:author="A" w:date="d"></w:del></w:p>'

    assert any("empty w:del" in p for p in lint_parts(_parts(change + empty)))


def test_an_equation_after_an_EMPTY_one_is_still_examined():
    """Two counts, and the walk must reach the second equation: an empty
    shell is skipped for the orphan count, not counted as the end of the
    document."""
    m = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
    body = (f"<w:p><m:oMath {m}><m:r><m:t></m:t></m:r></m:oMath></w:p>"
            f"<w:p><m:oMath {m}><m:r><m:t>x</m:t></m:r>"
            "<m:f><m:num/><m:den/></m:f></m:oMath></w:p>")

    problems = lint_parts(_parts(body))

    assert "1 empty m:oMath shell(s)" in problems
    assert any("1 empty math object(s)" in p for p in problems), problems


def test_the_empty_shell_count_is_a_COUNT():
    m = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
    one = f"<w:p><m:oMath {m}><m:r><m:t></m:t></m:r></m:oMath></w:p>"

    assert "2 empty m:oMath shell(s)" in lint_parts(_parts(one + one))


def test_a_revision_with_NO_id_sorts_LAST_among_the_duplicates():
    """`(x is None, x)` — two ids that are None are duplicates too, and
    None cannot be compared with a string. The key puts the real ids in
    order and the nameless pair at the end, where a reader looking for a
    w:id to search for is not stopped by it."""
    body = (para(run("a"))
            + '<w:p><w:ins w:id="5" w:author="A" w:date="d">'
            + run("one") + "</w:ins></w:p>"
            + '<w:p><w:ins w:id="5" w:author="A" w:date="d">'
            + run("two") + "</w:ins></w:p>"
            + '<w:p><w:ins w:author="A" w:date="d">' + run("three")
            + "</w:ins></w:p>"
            + '<w:p><w:ins w:author="A" w:date="d">' + run("four")
            + "</w:ins></w:p>")

    dup = next(p for p in lint_parts(_parts(body)) if "duplicate" in p)

    assert dup.endswith("['5', None]"), dup


# --- the run of 2026-08-20: 3.6 %, and two things it could not see ------


def test_a_document_carrying_an_XML_COMMENT_is_linted_not_crashed():
    """`_local` splits a tag at its namespace brace and takes what
    follows. lxml hands an XML comment a tag that is a FUNCTION, not a
    string — there is no brace in it — so an index that assumes the
    split produced two pieces raises instead of naming the element.

    A comment inside a `w:pPr` is what a house-style script leaves
    behind, and a linter that dies on one takes the whole build with
    it: the check it was in the middle of never reports."""
    commented = ("<w:p><w:pPr><!-- house style: keep this indent -->"
                 '<w:ind w:left="720"/></w:pPr>'
                 "<w:r><w:t>Prose.</w:t></w:r></w:p>")

    assert lint_parts(_parts(commented)) == []


def test_an_rPrChange_that_IS_last_is_not_reported():
    """`kids[-1]`, the last child of a `w:rPr`, against a fixed index.
    Word puts `w:rPrChange` last and the check exists to catch the
    builds that do not — so the case that must stay silent is a run
    with formatting BEFORE its change record, which is every tracked
    formatting edit in a real document.

    A second index also asks for `kids[1]` of an `rPr` whose only child
    is the change record, which is an IndexError inside a linter."""
    both = ('<w:p><w:r><w:rPr><w:i/><w:b/>'
            '<w:rPrChange w:id="9" w:author="T" '
            'w:date="2026-01-01T00:00:00Z">'
            "<w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr>"
            "<w:t>Prose.</w:t></w:r></w:p>")
    alone = ('<w:p><w:r><w:rPr>'
             '<w:rPrChange w:id="9" w:author="T" '
             'w:date="2026-01-01T00:00:00Z">'
             "<w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr>"
             "<w:t>Prose.</w:t></w:r></w:p>")

    assert lint_parts(_parts(both)) == []
    assert lint_parts(_parts(alone)) == []


# Argued rather than pinned, from the same run:
#
# * `rsplit("}", 1)` written `rsplit("}", 2)`. A tag has one brace, so
#   a second split has nothing to find.
# * `{W + t ...} | {M + t ...}` written `^`. The two sets are built
#   with different namespace prefixes and cannot intersect.
# * `len(element) == 0` written `<= 0`, and `n > 1` written `!= 1` over
#   a Counter's values: neither a child count nor a count that reached
#   a Counter can be negative or zero.
# * `tag == W + "del"` written `<=`. The walk that reaches it iterates
#   `w:ins` and `w:del`, and "ins" sorts after "del".
# * `text != text.strip(XML_WS)` written `is not`. `str.strip` hands
#   back the string it was given when there is nothing to strip.
# * the five mutants on `kids[kids.index("rPr") + 1:]`. Each of them
#   starts the slice at the `rPr` itself instead of after it, and the
#   only element they add to `after` is "rPr" — which is not in
#   `_PPR_BEFORE_RPR`, so the intersection below is unchanged.
# * `el is not om` written `!=`. lxml elements define no `__eq__`, so
#   equality IS identity for them.


# --- 8b: a bookmark NAME is defined once (2026-08-21) -------------------


def _mark(name: str, bid: int) -> str:
    return (f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
            f'<w:bookmarkEnd w:id="{bid}"/>')


def test_a_bookmark_name_defined_TWICE_is_a_finding():
    """Word keeps whichever definition it meets first, so every link to
    the name lands on a coin flip — and Compare discards the extras.

    Measured on 400 real manuscripts: 24 carry a duplicate and all 24
    are ONE paper, whose submitted file defines 12 names twice or more.
    Nothing said so — lint was clean and `citations` reported ALL CHECKS
    PASSED, because an audit that keys bookmarks BY NAME cannot see a
    name twice. A one-word Compare round came back 20 bookmarks lighter.
    """
    body = (para(_mark("WorldBank2024txt", 1) + run("first mention"))
            + para(_mark("WorldBank2024txt", 2) + run("second mention")))

    (problem,) = audit_parts(_parts(body))

    assert problem.startswith("1 bookmark name(s) defined more than once")
    assert "WorldBank2024txt x2" in problem
    assert "coin flip" in problem


def test_the_bookmark_namespace_is_the_PACKAGE_not_the_part():
    """A citation's `<key>txt` marker legitimately sits in footnotes.xml
    while the entry links to it from the body — so the same name in two
    PARTS is the same collision, not two innocent ones."""
    foot = (f'<w:footnotes {NS}><w:footnote w:id="2"><w:p>'
            + _mark("Sastry2024txt", 7) + run("a note")
            + "</w:p></w:footnote></w:footnotes>")
    parts = make_parts(para(_mark("Sastry2024txt", 1) + run("body")),
                       footnotes=foot)

    (problem,) = audit_parts(parts)

    assert "Sastry2024txt x2" in problem


def test_distinct_names_and_a_lone_marker_are_clean():
    body = (para(_mark("Table1", 1) + run("a caption"))
            + para(_mark("Table1txt", 2) + run("a mention"))
            + para('<w:bookmarkStart w:id="3"/>' + run("no name at all")))

    assert lint_parts(_parts(body)) == []


def test_a_DUPLICATE_never_refuses_a_write():
    """The regression this split exists for. `lint_parts` answers ONE
    question — will Word refuse to open this — and three callers refuse
    a write on its answer. Shipping the bookmark check inside it bricked
    every mutating command on a manuscript that already had a duplicate,
    under a message that was not true of it ("the package would not open
    cleanly in Word"). Word opens it; the links are just wrong.

    That is the S3 shape this repo's backlog ranks above a wrong output:
    a gate nobody can satisfy, on a condition the toolkit offered no way
    to clear.
    """
    body = (para(_mark("WorldBank2024txt", 1) + run("first mention"))
            + para(_mark("WorldBank2024txt", 2) + run("second mention")))

    assert lint_parts(_parts(body)) == []
    assert audit_parts(_parts(body)) != []


def test_the_worst_offender_is_never_the_one_elided():
    """Only eight names are listed, so the ORDER decides what a reader
    sees — and sorting by name means the one that matters survives on
    alphabetical luck. On the paper this check was found in it did:
    `AykutEtAl2026txt x6` happens to sort first. Name it `Zhang` and
    the message would have led with eight x2 entries and hidden the
    six behind the ellipsis, reading as a much smaller problem than
    it is.
    """
    marks, mark_id = "", 0
    #        z-first, so alphabetical order would bury the worst
    for name, count in (("zWorst", 6), ("aMild", 2), ("bMild", 2),
                        ("cMild", 2), ("dMild", 2), ("eMild", 2),
                        ("fMild", 2), ("gMild", 2), ("hMild", 2),
                        ("yBad", 4)):
        for _ in range(count):
            mark_id += 1
            marks += para(_mark(name, mark_id) + run("x"))

    (problem,) = audit_parts(_parts(marks))

    assert problem.startswith("10 bookmark name(s) defined more than once")
    listed = problem.split(": ", 1)[1]
    assert listed.startswith("zWorst x6, yBad x4")
    assert "..." in listed          # eight of ten, so it is truncated
    assert "hMild" not in listed    # and the truncation drops the mild


def _defined_twice(*names: str) -> str:
    """One paragraph per definition, every name defined exactly twice."""
    body, mark_id = "", 0
    for name in names:
        for _ in range(2):
            mark_id += 1
            body += para(_mark(name, mark_id) + run("x"))
    return body


def test_DISTINCT_bookmark_names_are_clean_TO_AUDIT():
    """For `c > 1` read as `c > 0` and as `c >= 1`, which report every
    name a document defines once as "defined more than once".

    The clean case above asks `lint_parts`, which never runs the
    bookmark walk, so nothing held the AUDIT to silence on an ordinary
    document — and this is the finding `revision validate` prints to an
    author, about a manuscript with nothing wrong with it.
    """
    body = (para(_mark("Table1", 1) + run("a caption"))
            + para(_mark("Table1txt", 2) + run("a mention")))

    assert audit_parts(_parts(body)) == []


@pytest.mark.parametrize("how_many", [3, 8])
def test_a_list_that_FITS_names_every_repeat_and_elides_nothing(how_many):
    """For `repeated[:8]` read as `[: 7]`, and the `len(repeated) > 8`
    behind the ellipsis read as `!= 8`, `> 7` and `>= 8`. The ten-name
    test above steps over every one of those: `> 7` and `>= 8` differ
    only at EXACTLY eight, and `!= 8` only BELOW it — where it appends
    an ellipsis to a list that is already complete.

    An ellipsis is a claim that there are more names than the reader can
    see, and eight `x2` entries is the shape the paper this check was
    written for actually had.
    """
    names = ("aOne", "bTwo", "cThree", "dFour",
             "eFive", "fSix", "gSeven", "hEight")[:how_many]

    (problem,) = audit_parts(_parts(_defined_twice(*names)))

    assert problem.startswith(
        f"{how_many} bookmark name(s) defined more than once")
    listed = problem.split(": ", 1)[1]
    assert all(f"{n} x2" in listed for n in names), listed
    assert "..." not in listed, "nothing is hidden, so nothing is claimed"


def test_the_NINTH_repeated_name_is_HIDDEN_and_the_ellipsis_says_so():
    """For `repeated[:8]` read as `[: 9]`, which names all nine, and
    `len(repeated) > 8` read as `> 9`, which drops the ninth in silence.

    Nine equal counts, so the order is alphabetical and the name left
    out is known: a reader who is shown eight of nine and told nothing
    reads the message as the whole list.
    """
    names = ("aOne", "bTwo", "cThree", "dFour", "eFive",
             "fSix", "gSeven", "hEight", "iNine")

    (problem,) = audit_parts(_parts(_defined_twice(*names)))

    assert problem.startswith("9 bookmark name(s) defined more than once")
    listed = problem.split(": ", 1)[1]
    assert listed.count(" x2") == 8, listed
    assert "iNine" not in listed
    assert "..." in listed


def test_names_with_the_SAME_count_are_listed_ALPHABETICALLY():
    """For `key=lambda item: (-item[1], item[0])` read as `item[ 1]` and
    as `item[ -1]`: both of those are the COUNT a second time, so ties
    fall back on `sorted`'s stability — the order the names were first
    MET. The ten-name test above defines its eight tied names
    alphabetically, so insertion order and name order agree there and
    neither mutant can show. Here they are defined backwards.
    """
    (problem,) = audit_parts(_parts(_defined_twice("zTie", "mTie", "aTie")))

    listed = problem.split(": ", 1)[1]

    assert listed.startswith("aTie x2, mTie x2, zTie x2"), listed


# ------------------------------------- a field with no end (2026-08-27) ---
#
# Aging_Well, dropping a figure whose in-text mention was a field-form
# hyperlink: deleting the sentence took the field's display runs and
# left `begin` + `instrText` standing. `lint` said "clean - no
# structural problems found" and exited 0. What DID exit 1 was
# `citations`, for an unbalanced SPAN two paragraphs away in a link that
# is fine, and `crossrefs --audit`, calling it a misplaced anchor.
# Three tools, three misleading descriptions, none of them "a field has
# no end".

def _fld(kind: str) -> str:
    return f'<w:r><w:fldChar w:fldCharType="{kind}"/></w:r>'


def _instr(text: str) -> str:
    return f'<w:r><w:instrText xml:space="preserve">{text}</w:instrText></w:r>'


def _field(instruction: str, shown: str) -> str:
    """A whole field: begin, its instruction, the text Word displays, end."""
    return (_fld("begin") + _instr(instruction) + _fld("separate")
            + run(shown) + _fld("end"))


def test_a_WHOLE_field_is_not_a_finding():
    body = para(run("As ") + _field(r' HYPERLINK \l "Figure2" ', "Figure 2")
                + run(" shows, the gradient steepens."))

    assert audit_parts(_parts(body)) == []


def test_a_field_BEGIN_with_no_end_is_a_finding():
    """The sentence went and took the display runs with it."""
    body = para(_fld("begin") + _instr(r' HYPERLINK \l "Figure2" '))

    (problem,) = audit_parts(_parts(body))

    assert problem.startswith("field BEGIN with no end")
    assert "Figure2" in problem, "the instruction is what identifies it"
    assert "swallows the rest of the paragraph" in problem


def test_a_field_END_with_no_begin_is_a_finding():
    """The other half of the same cut, and the opposite mistake: Word
    reads back from it into text that was never part of a field."""
    body = para(run("ordinary prose") + _fld("end"))

    (problem,) = audit_parts(_parts(body))

    assert problem.startswith("field END with no begin")
    assert "ordinary prose" in problem


def test_a_field_spanning_MANY_paragraphs_is_not_a_finding():
    """A TOC field opens in one paragraph and closes several later, so
    the balance is counted per PART. Counted per paragraph, every table
    of contents in every paper reports twice."""
    body = (para(_fld("begin") + _instr(r' TOC \o "1-3" \h ')
                 + _fld("separate") + run("1. Introduction"))
            + para(run("2. The capability framework"))
            + para(run("3. Evidence") + _fld("end")))

    assert audit_parts(_parts(body)) == []


def test_NESTED_fields_are_counted_by_DEPTH_not_by_totals():
    """A HYPERLINK inside a cross-reference is ordinary markup. Two
    counts would call `end begin` balanced — and that is two orphans,
    the exact damage a cut between two fields leaves behind."""
    nested = para(_fld("begin") + _instr(" REF _Ref1 ") + _fld("separate")
                  + _field(r' HYPERLINK \l "Table1" ', "Table 1")
                  + _fld("end"))
    assert audit_parts(_parts(nested)) == []

    crossed = para(_fld("end") + run("between two cuts") + _fld("begin")
                   + _instr(" REF _Ref2 "))
    assert len(audit_parts(_parts(crossed))) == 2


def test_a_fldSimple_pairs_with_NOTHING_and_is_not_reported():
    """It carries its instruction as an attribute and has no halves to
    lose, so it must not read as an unterminated field."""
    body = para(f'<w:fldSimple w:instr=" PAGE ">{run("7")}</w:fldSimple>')

    assert audit_parts(_parts(body)) == []


def test_a_fldChar_with_NO_TYPE_is_NEITHER_half_of_a_field():
    """For `kind == "begin"` and `kind == "end"` read as `<=`. A
    `w:fldChar` with no `w:fldCharType` gives `kind is None`, and
    `None <= "begin"` raises TypeError inside an advisory walk — in a
    function whose whole job is to describe a file that is already
    damaged, and which `validate` runs over whatever it is handed.

    The attribute is what a half is paired on, so one without it pairs
    with nothing, and the whole field beside it still balances.
    """
    body = para(run("prose ") + "<w:r><w:fldChar/></w:r>"
                + _field(r' HYPERLINK \l "Figure2" ', "Figure 2"))

    assert audit_parts(_parts(body)) == []


def test_an_orphan_in_the_FOOTNOTES_is_found_too():
    """Compare rewrites every part it touches, and a figure mention in a
    note is as ordinary as one in the body."""
    foot = (f'<w:footnotes {NS}><w:footnote w:id="2"><w:p>'
            + _fld("begin") + _instr(r' HYPERLINK \l "Table3" ')
            + "</w:p></w:footnote></w:footnotes>")

    (problem,) = audit_parts(make_parts(para(run("body")), footnotes=foot))

    assert "Table3" in problem


def test_an_unterminated_field_does_NOT_refuse_the_write():
    """Word opens the file — it just reads it wrongly. The refusal path
    is for markup Word rejects outright, and putting a correctness
    finding there is what bricked every mutating command once already."""
    body = para(_fld("begin") + _instr(r' HYPERLINK \l "Figure2" '))

    assert lint_parts(_parts(body)) == []
    assert audit_parts(_parts(body)) != []


def test_a_BODY_paragraph_opening_on_whitespace_is_an_advisory_finding():
    """Word prints it as an indent, and a paper whose truth already
    carries one has nothing for `compare` to report it against
    (Aging_Well A.4, 2026-09-11). Advisory: Word opens the file."""
    body = para(run("Clean.")) + para(run(" The following values",
                                          preserve=True))

    (finding,) = audit_parts(_parts(body))

    assert "opens on whitespace" in finding and "The following" in finding
    assert lint_parts(_parts(body)) == []


def test_a_TAB_counts_and_a_paragraph_of_nothing_but_space_does_not():
    tabbed = para("<w:r><w:tab/></w:r>" + run("Indented by hand."))
    blank = para(run("   ", preserve=True))

    assert audit_parts(_parts(tabbed)) == [], "a w:tab is not a w:t"
    assert audit_parts(_parts(blank)) == []
    assert audit_parts(_parts(para(run("\tText", preserve=True)))) != []


def test_a_FOOTNOTE_opening_on_a_space_is_NOT_reported():
    """Eleven of twelve on that paper open on the space after the note
    mark, which is how a footnote is typed. The body only."""
    foot = (f'<w:footnotes {NS}><w:footnote w:id="2"><w:p>'
            + run(" A note, as typed.", preserve=True)
            + "</w:p></w:footnote></w:footnotes>")

    assert audit_parts(make_parts(para(run("body")), footnotes=foot)) == []


def test_a_package_with_NO_document_part_reads_NO_OTHER_part_as_the_body():
    """For `r.tag == W + "document"` read as `<=`, `>=` and `is not`.
    Each of them picks a root when there is no document part to pick:
    `w:comments` sorts BEFORE `w:document` and `w:footnotes` after it,
    and `is not` is true of every tag, since the tag it is compared with
    is built right there and is never the same object.

    Both parts here open on the space a note and a comment are typed
    with — 11 of 12 on Aging_Well — so a part read as the body reports
    every note in the paper as an indent the author made.
    """
    foot = (f'<w:footnotes {NS}><w:footnote w:id="2"><w:p>'
            + run(" A note, as typed.", preserve=True)
            + "</w:p></w:footnote></w:footnotes>")
    note = (f'<w:comments {NS}><w:comment w:id="1"><w:p>'
            + run(" A comment, as typed.", preserve=True)
            + "</w:p></w:comment></w:comments>")

    parts = {"word/footnotes.xml": foot.encode("utf-8"),
             "word/comments.xml": note.encode("utf-8")}

    assert audit_parts(parts) == []


def test_lint_SKIPS_a_MISSING_part_and_reads_THE_ONES_AFTER_IT():
    """For the `continue` on a None root read as `break`, which stops at
    the first part a caller does not have. `lint` takes one root per
    part and its signature accepts None for each, so which part is
    absent would decide whether the parts after it are linted at all.
    The None goes FIRST, or the mutant has nothing to stop early.
    """
    from docxkit.lint import lint

    root = lxml_etree.fromstring(
        _parts(para(run(" leading whitespace")))["word/document.xml"])

    assert any("edge whitespace" in p for p in lint(None, root))


def test_audit_SKIPS_a_MISSING_part_and_reads_THE_ONES_AFTER_IT():
    """The same `continue` read as `break` in BOTH of audit's walks —
    the bookmark tally and the field balance. One document after the
    None, carrying one finding of each kind, so either walk stopping
    early shows.
    """
    from docxkit.lint import audit

    body = (para(_mark("WorldBank2024txt", 1) + run("first mention"))
            + para(_mark("WorldBank2024txt", 2) + run("second mention"))
            + para(_fld("begin") + _instr(r' HYPERLINK \l "Figure2" ')))
    root = lxml_etree.fromstring(_parts(body)["word/document.xml"])

    findings = audit(None, root)

    assert any("defined more than once" in f for f in findings), findings
    assert any(f.startswith("field BEGIN with no end") for f in findings)
