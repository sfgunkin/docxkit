"""The shared WordprocessingML primitives, tested directly.

`_xml` is where R1 and R6 put the one definition of a run, a text node, a
bookmark and a part name, and every editing module is built on it. It had
no test module: `set_run_text`, `matching_close`, `element_spans` and
`used_prefixes` were not named anywhere in the suite, and were exercised
only through whatever shapes their callers happened to produce.

A cosmic-ray pass over the file (357 mutants, 2026-08-09) said so
precisely — 49 survivors, and almost every viable one sat in exactly
those functions. Two clusters did the most work:

  * ten mutations of the `xml:space="preserve"` guard in `set_run_text`
    ALL survived, including inverting it outright. That guard is the
    reason a manuscript does not grow a phantom author edit on every
    round;
  * every self-closing-element branch survived — `<w:ins/>` is a
    property-level mark that neither nests nor closes, and getting it
    wrong makes a walk pair an open tag with someone else's close.

So the tests below are deliberately about the primitive rather than
about a caller: a bug reached through five modules is a bug found five
times over.
"""
from __future__ import annotations

import pytest
from conftest import NS, field

from docxkit._xml import (
    PARA_RE,
    dead_links,
    element_spans,
    internal_links,
    live_properties,
    matching_close,
    own_properties,
    set_run_property,
    set_run_text,
    used_prefixes,
    visible_text,
)


def run(text: str, *, rpr: str = "") -> str:
    return f"<w:r>{rpr}<w:t>{text}</w:t></w:r>"


# ------------------------------------------------------- set_run_text ----
# The mandatory last build step lives here as well as in edit.preserve_space:
# a bare `<w:t> x</w:t>` loses its edge space on every Word save, and the
# space then reappears as an author edit nobody made.


def test_an_edge_space_gets_xml_space_preserve():
    got = set_run_text(run("x"), " lead")
    assert '<w:t xml:space="preserve"> lead</w:t>' in got


def test_a_trailing_space_gets_it_too():
    assert 'xml:space="preserve"' in set_run_text(run("x"), "trail ")


@pytest.mark.parametrize("text", ["plain", "two words", ""])
def test_text_with_no_edge_whitespace_does_not(text):
    """Not decoration: writing it unconditionally would rewrite every run
    in the manuscript and show up as a diff on every paragraph."""
    assert "xml:space" not in set_run_text(run("x"), text)


def test_an_existing_preserve_is_not_written_twice():
    already = '<w:r><w:t xml:space="preserve">x</w:t></w:r>'
    got = set_run_text(already, " y")
    assert got.count("xml:space") == 1


def test_the_text_lands_in_the_first_run_and_the_others_are_blanked():
    """The multi-run case, which no caller in the suite produced: every
    mutation of the index arithmetic survived because `len(runs)` was
    always 1, so `idx` was 0 whatever the expression said."""
    two = run("a") + run("b")
    got = set_run_text(two, "Z")
    assert visible_text(got) == "Z"
    assert got.count("<w:t") == 2          # structure kept, text moved
    assert "<w:t>Z</w:t>" in got
    assert "<w:t></w:t>" in got


def test_three_runs_keep_their_order_and_their_formatting():
    three = (run("a", rpr="<w:rPr><w:b/></w:rPr>") + run("b") + run("c"))
    got = set_run_text(three, "Q")
    assert visible_text(got) == "Q"
    assert got.index("<w:t>Q</w:t>") < got.index("<w:t></w:t>")
    assert "<w:b/>" in got


def test_the_text_is_escaped():
    assert "R&amp;D" in set_run_text(run("x"), "R&D")
    assert "&lt;" in set_run_text(run("x"), "a<b")


def test_a_fragment_with_no_run_is_returned_unchanged():
    assert set_run_text("<w:p/>", "x") == "<w:p/>"


# ----------------------------------------------------- matching_close ----


def test_a_nested_element_of_the_same_name_closes_at_the_outer_one():
    xml = "<w:tc>A<w:tc>B</w:tc>C</w:tc>"
    assert matching_close(xml, len("<w:tc>"), "tc") == len(xml)


def test_a_self_closing_open_neither_nests_nor_closes():
    """`<w:ins/>` is a property-level mark. Counted as an open, the walk
    goes looking for a close that is not there and pairs the next one it
    finds with the wrong element."""
    xml = "<w:ins>X<w:ins/>Y</w:ins>"
    assert matching_close(xml, len("<w:ins>"), "ins") == len(xml)


def test_two_self_closing_marks_in_a_row_are_both_skipped():
    xml = "<w:ins><w:ins/><w:ins/>tail</w:ins>"
    assert matching_close(xml, len("<w:ins>"), "ins") == len(xml)


def test_an_attribute_bearing_open_tag_still_counts():
    xml = '<w:tc><w:tc w:id="3">B</w:tc></w:tc>'
    assert matching_close(xml, len("<w:tc>"), "tc") == len(xml)


# ------------------------------------------------------ element_spans ----


def test_a_span_starting_at_the_very_beginning_is_found():
    """The scan starts at 0, and every mutation of that start survived —
    no test ever passed a string whose element sat at offset 0."""
    xml = "<w:tc>a</w:tc>"
    assert element_spans(xml, "tc") == [(0, len(xml))]


def test_only_the_outermost_elements_are_returned():
    xml = "<w:p><w:tc>A<w:tc>inner</w:tc></w:tc><w:tc>B</w:tc></w:p>"
    spans = element_spans(xml, "tc")
    assert len(spans) == 2
    assert xml[spans[0][0]:spans[0][1]].count("<w:tc") == 2   # rides along
    assert xml[spans[1][0]:spans[1][1]] == "<w:tc>B</w:tc>"


def test_a_self_closing_element_is_skipped_and_the_walk_goes_on():
    """`continue`, not `break`: a self-closing element has no content, but
    the elements AFTER it still do."""
    xml = "<w:p><w:tc/><w:tc>real</w:tc></w:p>"
    spans = element_spans(xml, "tc")
    assert [xml[s:e] for s, e in spans] == ["<w:tc>real</w:tc>"]


def test_nothing_to_find_is_an_empty_list():
    assert element_spans("<w:p>text</w:p>", "tc") == []


# ----------------------------------------------------- own_properties ----


def test_the_properties_are_the_child_right_after_the_open_tag():
    el = "<w:r><w:rPr><w:b/></w:rPr><w:t>x</w:t></w:r>"
    got = own_properties(el, "rPr")
    assert got is not None
    start, end, inner = got
    assert el[start:end] == "<w:rPr><w:b/></w:rPr>"
    assert inner == "<w:b/>"


def test_an_empty_self_closing_properties_element_is_real():
    el = "<w:tc><w:tcPr/><w:p/></w:tc>"
    got = own_properties(el, "tcPr")
    assert got is not None
    assert got[2] == ""
    assert el[got[0]:got[1]] == "<w:tcPr/>"


def test_a_nested_snapshot_does_not_end_the_properties_early():
    """A tracked FORMATTING change stores the old rPr INSIDE the new one,
    so a non-greedy close returns an element cut in half."""
    el = ("<w:r><w:rPr><w:i/><w:rPrChange w:id='1'><w:rPr><w:b/></w:rPr>"
          "</w:rPrChange></w:rPr><w:t>x</w:t></w:r>")
    got = own_properties(el, "rPr")
    assert got is not None
    assert got[2].endswith("</w:rPrChange>")
    assert live_properties(got[2]) == "<w:i/>"


def test_a_string_that_is_not_an_element_has_no_properties():
    """`open_tag is None or ...` — with `and` there, this raises
    AttributeError instead of answering."""
    assert own_properties("not markup at all", "rPr") is None
    assert own_properties("", "rPr") is None


def test_a_self_closing_element_has_no_properties():
    assert own_properties("<w:r/><w:rPr><w:b/></w:rPr>", "rPr") is None


def test_an_element_without_that_child_reports_none():
    assert own_properties("<w:r><w:t>x</w:t></w:r>", "rPr") is None


# ---------------------------------------------------- internal_links -----


def test_a_field_form_link_gives_its_anchor_and_its_visible_label():
    xml = field('HYPERLINK \\l "Table1"', "Table 1")
    assert internal_links(xml) == [("Table1", "Table 1")]


def test_an_element_form_link_gives_the_same_answer():
    xml = ('<w:hyperlink w:anchor="Table1">' + run("Table 1")
           + "</w:hyperlink>")
    assert internal_links(xml) == [("Table1", "Table 1")]


def test_a_field_that_is_not_a_hyperlink_is_skipped_not_a_full_stop():
    """`continue`, not `break`. A PAGEREF sits in every cross-reference
    these papers build, so stopping at the first one would report no
    links at all in a document full of them."""
    xml = (field("PAGEREF _Ref1 \\h", "12")
           + field('HYPERLINK \\l "Table1"', "Table 1"))
    assert internal_links(xml) == [("Table1", "Table 1")]


def test_a_self_closing_ghost_hyperlink_swallows_nothing_after_it():
    xml = ('<w:hyperlink w:anchor="Ghost"/>' + run("prose ")
           + '<w:hyperlink w:anchor="Real">' + run("label")
           + "</w:hyperlink>")
    assert ("Real", "label") in internal_links(xml)


# -------------------------------------------------------- dead_links -----
#
# A link that puts nothing on the page. The anchor still resolves, so no
# other check sees it: `citations` says the bookmark is linked,
# `crossrefs` counts it, `lint` is clean and Word opens the file. Found
# on Parental Style 2026-08-11 after an edit ran across a link, and the
# corpus then turned up ten more in three papers — two of them submitted.


def test_an_emptied_element_form_link_is_dead():
    xml = '<w:hyperlink w:anchor="Table5"><w:r><w:t></w:t></w:r></w:hyperlink>'
    assert dead_links(xml) == ["Table5"]


def test_an_emptied_field_form_link_is_dead():
    """LE's Elder2013 and five of LI's footnote citations are exactly
    this: begin, instrText, separate, end, with no result between the
    last two."""
    xml = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText>HYPERLINK \\l "Elder2013"</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:bookmarkEnd w:id="7"/>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    assert dead_links(xml) == ["Elder2013"]


def test_a_live_link_is_not_reported_in_either_form():
    xml = (field('HYPERLINK \\l "Table1"', "Table 1")
           + '<w:hyperlink w:anchor="Table2">' + run("Table 2")
           + "</w:hyperlink>")
    assert dead_links(xml) == []


def test_a_link_inside_a_tracked_deletion_is_not_dead():
    """It is not in the final document at all. Four sit in LE le12, and
    reporting them would put every redline on the list — which is how a
    check stops being run."""
    xml = ('<w:del w:id="9" w:author="A" w:date="2026-07-01T00:00:00Z">'
           '<w:hyperlink w:anchor="Yaari1965"><w:r>'
           "<w:delText>Yaari 1965</w:delText></w:r></w:hyperlink></w:del>")
    assert dead_links(xml) == []


@pytest.mark.parametrize("content", [
    "<w:r><w:drawing/></w:r>",                     # a linked figure
    "<w:r><w:footnoteReference w:id='3'/></w:r>",  # a linked note mark
])
def test_a_link_wrapping_something_other_than_text_is_not_dead(content):
    xml = f'<w:hyperlink w:anchor="Fig1">{content}</w:hyperlink>'
    assert dead_links(xml) == []


def test_a_field_with_no_result_yet_is_not_dead():
    """No `separate` means Word has not rendered the field — it fills it
    on open. That is an unrendered field, not an emptied one."""
    xml = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           '<w:r><w:instrText>HYPERLINK \\l "Table1"</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    assert dead_links(xml) == []


# --------------------------------------------------- set_run_property ----


def test_a_new_property_lands_in_its_schema_position():
    r = "<w:r><w:rPr><w:b/><w:sz w:val='20'/></w:rPr><w:t>x</w:t></w:r>"
    got = set_run_property(r, "i", "<w:i/>")
    assert "<w:rPr><w:b/><w:i/><w:sz w:val='20'/></w:rPr>" in got


def test_an_existing_property_is_replaced_and_its_neighbours_are_not():
    """`name == tag`, not `name >= tag`: with the comparison loosened,
    the first property that merely SORTS after the one asked for gets
    overwritten instead."""
    r = "<w:r><w:rPr><w:b/><w:sz w:val='20'/></w:rPr><w:t>x</w:t></w:r>"
    got = set_run_property(r, "b", '<w:b w:val="0"/>')
    assert '<w:b w:val="0"/>' in got
    assert "<w:sz w:val='20'/>" in got
    assert got.count("<w:b") == 1


def test_a_run_with_no_properties_gets_some():
    got = set_run_property("<w:r><w:t>x</w:t></w:r>", "i", "<w:i/>")
    assert "<w:rPr><w:i/></w:rPr>" in got


def test_an_empty_element_removes_the_property():
    r = "<w:r><w:rPr><w:b/><w:i/></w:rPr><w:t>x</w:t></w:r>"
    got = set_run_property(r, "i", "")
    assert "<w:i/>" not in got
    assert "<w:b/>" in got


def test_a_fragment_that_is_not_a_run_is_left_alone():
    assert set_run_property("<w:p/>", "i", "<w:i/>") == "<w:p/>"


# ------------------------------------------------------ used_prefixes ----


def test_every_prefix_on_an_element_or_an_attribute_is_reported():
    frag = '<m:oMath><w:ins w16du:dateUtc="x"><m:t>a</m:t></w:ins></m:oMath>'
    assert used_prefixes(frag) == {"m", "w", "w16du"}


def test_the_xml_and_xmlns_prefixes_are_not_namespaces_to_declare():
    frag = '<w:t xml:space="preserve" xmlns:w="urn:w">x</w:t>'
    assert used_prefixes(frag) == {"w"}


def test_a_fragment_with_no_prefixes_needs_none():
    assert used_prefixes("<p>text</p>") == set()


def test_the_document_namespaces_round_trip(tmp_path):
    """A sanity check against the real declaration string the fixtures
    use, so the set above is not just self-consistent."""
    assert "w" in used_prefixes(f"<w:document {NS}><w:p/></w:document>")


# ---------------------------------------- one definition, and only one ---


def test_no_element_pattern_is_compiled_in_two_modules():
    """This module's own docstring says it holds THE definition of a run,
    a text node, a bookmark and a part name, and six of them had drifted
    into copies: the bookmark NAME in four modules (in two spellings),
    the hyperlink element in two — one of them carrying a comment
    pointing AT the twin here rather than importing it — and the
    paragraph, the instruction, the field separator and the section
    properties elsewhere.

    The cost is never the duplicate itself, it is the fix that lands in
    one copy: the field walk existed three times with three different
    guards and only one defended against a missing end tag; a `\b` and a
    ghost guard are exactly the kind of detail that gets added once.

    So the rule is mechanical, and this is the mechanism.
    """
    import ast
    import re
    from collections import defaultdict
    from pathlib import Path

    import docxkit

    src = Path(docxkit.__file__).parent
    literal = re.compile(r"""re\.compile\(\s*(?:rf?|fr?)?(['"])(.*?)\1""",
                         re.DOTALL)
    where: dict[str, set[str]] = defaultdict(set)
    for path in sorted(src.glob("*.py")):
        if path.name == "word_edits.py":       # a port, exempt by policy
            continue
        text = path.read_text(encoding="utf-8")
        ast.parse(text)                        # it must still be Python
        for _quote, pattern in literal.findall(text):
            # only WordprocessingML element shapes: a bare `\d+` or a
            # prose pattern is not this module's business
            if "<w:" in pattern or "<m:" in pattern:
                where[" ".join(pattern.split())].add(path.stem)
    twice = {pat: sorted(mods) for pat, mods in where.items()
             if len(mods) > 1}
    assert not twice, "\n".join(
        f"{mods}: {pat[:70]}" for pat, mods in sorted(twice.items()))


# ------------------------------------------------ the empty paragraph ----


def test_a_self_closing_paragraph_is_not_an_open_tag():
    """`<w:p/>` is an EMPTY paragraph. `[^>]*>` swallowed the slash and
    the walk then ran on to the next paragraph's close, so the span a
    caller got back began at the blank line BEFORE the one it asked for
    — and replacing that span deletes the author's blank line.

    Measured over 399 manuscripts: 816 spans in 233 of them started too
    early. Not one oracle saw it, because the TEXT of the merged block
    is the text of the paragraph that was asked for; only the offsets
    moved."""
    xml = "<w:p/><w:p><w:r><w:t>real</w:t></w:r></w:p>"
    got = [m.group(0) for m in PARA_RE.finditer(xml)]
    assert got == ["<w:p><w:r><w:t>real</w:t></w:r></w:p>"]


def test_an_attribute_bearing_empty_paragraph_too():
    """Word writes the attributes, so this is the form that actually
    occurs — the bare `<w:p/>` is in 28 documents here and the attributed
    one in 233."""
    xml = ('<w:p w14:paraId="4BD89DAE" w14:textId="77" w:rsidR="00A"/>'
           "<w:p><w:r><w:t>real</w:t></w:r></w:p>")
    got = [m.group(0) for m in PARA_RE.finditer(xml)]
    assert got == ["<w:p><w:r><w:t>real</w:t></w:r></w:p>"]


def test_an_ordinary_paragraph_still_matches_whole():
    """The guard must not cost the ordinary case: a `/` INSIDE the open
    tag's attributes, and a self-closing child, are both fine."""
    xml = ('<w:p w:rsidR="00A/B"><w:pPr><w:jc w:val="center"/></w:pPr>'
           "<w:r><w:t>x</w:t></w:r></w:p>")
    assert [m.group(0) for m in PARA_RE.finditer(xml)] == [xml]


# ------------------------------------------ the SELF-CLOSING run ---------

#: Word writes `<w:r/>` for an empty run, and 28 of 899 manuscripts
#: carry one (2026-08-15). `<w:r\b[^>]*>` swallowed the slash and paired
#: it with the NEXT close tag, merging the empty run with the real run
#: after it — the same defect PARA_RE was fixed for in 6acc545, and
#: harder to see: an empty run has no visible text, so every offset and
#: every text assertion stayed correct while the run IDENTITY was wrong.

_EMPTY_RUN_PARA = (
    '<w:p><w:r><w:t xml:space="preserve">The share rose to </w:t></w:r>'
    "<w:r/>"
    '<w:r><w:rPr><w:i/></w:rPr><w:t>0.15</w:t></w:r>'
    '<w:r><w:t xml:space="preserve"> in 2024.</w:t></w:r></w:p>')


def test_RUN_RE_does_not_read_a_self_closing_run_as_an_open_tag():
    from docxkit._xml import RUN_RE

    runs = [m.group(0) for m in RUN_RE.finditer(_EMPTY_RUN_PARA)]
    assert len(runs) == 3, runs
    assert not any(r.startswith("<w:r/>") for r in runs), \
        "the empty run was merged with the run after it"
    assert "<w:i/>" in runs[1], "the italic run kept its own properties"


def test_RUN_OPEN_RE_does_not_match_an_empty_run():
    from docxkit._xml import RUN_OPEN_RE

    assert [m.group(0) for m in RUN_OPEN_RE.finditer(_EMPTY_RUN_PARA)] == \
        ["<w:r>", "<w:r>", "<w:r>"]


def test_an_edit_across_an_empty_run_keeps_it_and_the_text():
    from docxkit._xml import visible_text
    from docxkit.edit import replace_in_para

    out = replace_in_para(_EMPTY_RUN_PARA, "0.15", "0.17")
    assert visible_text(out) == "The share rose to 0.17 in 2024."
    assert "<w:r/>" in out, "the empty run was consumed by the rewrite"
    assert out.count("<w:i/>") == 1


def test_the_paragraph_open_pattern_in_crossrefs_is_guarded_too():
    from docxkit.crossrefs import _P_OPEN_RE

    assert _P_OPEN_RE.match("<w:p/>") is None
    assert _P_OPEN_RE.match('<w:p w14:paraId="1">') is not None


# ------------------------------------------- in_span, at both of its edges --
#
# Eight call sites across `edit`, `footnotes` and `_cite_grammar` wrote
# `lo <= x.start() < hi` by hand before this was one function. The copies
# had NOT drifted — unlike `run_spans`, where two of three carried a fix
# the third did not — so this is stated here rather than inferred from
# any one caller.
#
# Measured after the extraction (2026-08-16): the edit suite kills a
# change at either edge, the footnotes suite kills one, and the citation
# suite kills neither. That asymmetry is the point of having one
# definition: the least-tested callers are now guarded by the
# best-tested one, which is not something a comment in each copy could
# have arranged.

def test_in_span_includes_the_START_and_excludes_the_END():
    from docxkit._xml import in_span

    assert in_span(5, (5, 9)), "a span from field_spans starts ON a run"
    assert in_span(8, (5, 9))
    assert not in_span(9, (5, 9)), \
        "the run after an element begins exactly at its end, and is outside"
    assert not in_span(4, (5, 9))


def test_span_holding_answers_WHICH_span_and_None_for_none():
    from docxkit._xml import span_holding

    spans = [(0, 4), (10, 20)]
    assert span_holding(0, spans) == (0, 4)
    assert span_holding(15, spans) == (10, 20)
    assert span_holding(4, spans) is None, "the end of the first is outside it"
    assert span_holding(20, spans) is None
    assert span_holding(3, []) is None


def test_overlaps_treats_a_ZERO_WIDTH_span_as_strictly_inside():
    """A footnote reference is a run of no visible width, span ``(s,
    s)``. It overlaps only when `s` lies strictly inside the other span
    — which is what makes "the match ABUTS a marker" a different answer
    from "the match CROSSES it", and crossing one moves the marker to
    the end of the replacement, silently.
    """
    from docxkit._xml import overlaps

    assert not overlaps((5, 5), (5, 9)), "abutting the start is not crossing"
    assert not overlaps((9, 9), (5, 9)), "abutting the end is not crossing"
    assert overlaps((7, 7), (5, 9)), "strictly inside IS crossing"


def test_overlaps_at_the_edges_of_two_real_spans():
    from docxkit._xml import overlaps

    assert not overlaps((0, 5), (5, 9)), "touching end-to-start is not overlap"
    assert not overlaps((9, 12), (5, 9))
    assert overlaps((4, 6), (5, 9))
    assert overlaps((8, 12), (5, 9))
    assert overlaps((0, 20), (5, 9)), "a span containing the other overlaps it"
