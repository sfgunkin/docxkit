"""Each check corresponds to markup Word refuses to open."""
from __future__ import annotations

import pytest
from conftest import NS, dele, ins, make_parts, para, run

from docxkit.body import para as bpara
from docxkit.body import run as brun
from docxkit.lint import lint_parts

lxml_etree = pytest.importorskip("lxml.etree")


def _parts(body: str, **extra: str) -> dict[str, bytes]:
    parts = make_parts(body)
    for name, xml in extra.items():
        parts[f"word/{name}.xml"] = xml.encode("utf-8")
    return parts


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
    assert lint_parts(_parts(body)) == []


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
