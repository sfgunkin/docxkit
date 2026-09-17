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

import io
import zipfile
from xml.etree import ElementTree

import pytest
from conftest import NS, field

from docxkit._xml import (
    PARA_RE,
    ZIP_STAMP,
    append_before_close,
    dead_links,
    element_spans,
    internal_links,
    live_properties,
    matching_close,
    own_properties,
    printed_text,
    set_para_property,
    set_run_property,
    set_run_text,
    split_run,
    used_prefixes,
    visible_text,
    zip_entry,
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


def test_the_PARTS_MAPPING_is_refused_by_name():
    """Almost every sibling in this namespace takes `parts`, and this
    takes one part's XML. Passing the mapping used to raise "expected
    string or bytes-like object, got 'dict'" from inside a regex — a
    message naming this function's line and not the caller's mistake.

    Refused rather than accepted: which parts it would read is a real
    question, the body alone and the body-plus-notes are different
    answers, and the caller is the one who knows which they mean.
    """
    with pytest.raises(TypeError, match="ONE part's XML"):
        internal_links({"word/document.xml": b"<w:p/>"})   # type: ignore[arg-type]


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


# ------------------------------- set_run_text and element_spans, by value --
#
# The residue of the first `_xml.py` mutation run (2026-08-17) after the
# field walk was pinned. Three of it is real and below; the rest is
# equivalent, and recorded at the foot of this file so a later survivor
# report is not read as a gap.

def test_set_run_text_puts_the_text_in_the_FIRST_run_of_four():
    """It writes into the first `w:t` and empties the rest, so a caller
    can rewrite a phrase Word fragmented across runs without losing the
    run properties on any of them.

    Four runs, not two: the index is `len(runs) - 1 - i` over a REVERSED
    walk, and with two or three runs several wrong arithmetics still
    identify the first one. At four they part company.
    """
    from docxkit._xml import set_run_text

    xml = ("<w:r>" + "".join(f"<w:t>{part}</w:t>"
                             for part in ("Ta", "ble", " ", "4")) + "</w:r>")

    out = set_run_text(xml, "Table 5")

    assert out.count("<w:t>") == 4, "runs must survive, emptied"
    assert "<w:t>Table 5</w:t>" in out
    assert out.index("Table 5") < out.index("</w:r>")
    assert out.count("<w:t></w:t>") == 3


def test_set_run_text_adds_xml_space_ONLY_for_an_edge_space():
    """The attribute is not free: Word writes it, diffs show it, and a
    build that adds it everywhere makes every run look edited."""
    from docxkit._xml import set_run_text

    plain = set_run_text("<w:r><w:t>x</w:t></w:r>", "Table 4")
    spaced = set_run_text("<w:r><w:t>x</w:t></w:r>", " Table 4")

    assert "xml:space" not in plain, plain
    assert 'xml:space="preserve"' in spaced, spaced


# Equivalent mutants in this module, left alive with their reasons:
#
# * `group(1) == "/"` -> `>= "/"` or `is "/"`, at all FOUR self-closing
#   tests (`matching_close`, `element_spans`, `own_properties` twice).
#   The regexes capture with `(/?)`, which always participates, so the
#   value is "/" or "" and nothing else: "" sorts below "/" and a
#   one-character string is interned, so all three spellings agree;
# * `set_run_text`'s `len(runs) - 1 - i` -> `^`. The index is read only
#   as `idx == 0`, and `(n - 1) ^ i` is zero exactly when `i == n - 1`
#   — the same run, by a different arithmetic;
# * `idx == 0` -> `<= 0`, where the index is never negative;
# * `internal_links` and `dead_links` slicing `m.group(1)` -> `group(0)`.
#   Group 0 adds the `fldChar` and `instrText` markup around the field's
#   content, and neither carries visible text, so the label is the same
#   string either way; [WRONG for the two SLICES, killed 2026-09-17 —
#   see the begin-marker tests at the foot of this file]
# * `set_run_property`'s `_RPR_RANK.get(name, ...) > rank` -> `>=`. An
#   equal rank means the same property name, and that case returns above
#   this line by replacing in place; [WRONG for two unknown names, killed
#   2026-09-17]
# * `body != body.strip()` -> `body is not body.strip()`, in
#   `set_run_text`. CPython's `str.strip()` returns the SAME OBJECT
#   when it removes nothing, so identity and equality agree at both
#   ends of the question. The test above states the behaviour anyway,
#   because "only for an edge space" is worth saying out loud — it
#   just does not kill that mutant, and claiming it would be false.


# --- CT_PPr, in one place instead of four -------------------------------
#
# `set_para_property` is the paragraph's answer to `set_run_property`.
# Four writers had a copy of this — keepNext, jc, spacing,
# pageBreakBefore — and every defect the copies had, they had
# SEPARATELY: `find.page_break_before` still carried all three that were
# fixed in `_keep_with_table` hours earlier, including the one that put
# two `w:pPr` in a paragraph.


def _keep(para: str) -> str:
    return set_para_property(para, "keepNext", "<w:keepNext/>")


def test_a_paragraph_with_no_properties_gets_them():
    assert _keep("<w:p><w:r><w:t>x</w:t></w:r></w:p>") == (
        "<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:t>x</w:t></w:r></w:p>")


def test_a_SELF_CLOSING_paragraph_is_expanded():
    """`<w:p/>` is a real empty paragraph. Writing after its open tag
    puts the properties outside the paragraph they belong to."""
    assert _keep("<w:p/>") == "<w:p><w:pPr><w:keepNext/></w:pPr></w:p>"


def test_an_EMPTY_pPr_is_expanded_rather_than_written_past():
    """`<w:pPr/>` is real Word output, and its span covers a
    self-closing tag: `find.page_break_before` wrote a SECOND `w:pPr`
    beside it, which is two properties elements in one paragraph."""
    assert _keep("<w:p><w:pPr/><w:r/></w:p>") == (
        "<w:p><w:pPr><w:keepNext/></w:pPr><w:r/></w:p>")


def test_the_property_lands_in_its_SCHEMA_SLOT():
    """CT_PPr is a sequence: only `pStyle` precedes `keepNext`, and
    everything from `spacing` on follows it. Word drops a misplaced
    property on the next save."""
    para = ('<w:p><w:pPr><w:pStyle w:val="C"/>'
            '<w:spacing w:before="120"/><w:jc w:val="both"/></w:pPr></w:p>')

    out = _keep(para)

    inner = out[out.index("<w:pPr>"):out.index("</w:pPr>")]
    order = [inner.index(t) for t in ("<w:pStyle", "<w:keepNext",
                                      "<w:spacing", "<w:jc")]
    assert order == sorted(order), inner


def test_BOTH_spellings_of_the_preceding_property_are_recognised():
    """`<w:pStyle .../>` and `<w:pStyle ...></w:pStyle>` are the same
    element; matching one put keepNext ahead of the other."""
    out = _keep('<w:p><w:pPr><w:pStyle w:val="C"></w:pStyle></w:pPr></w:p>')

    assert '<w:pStyle w:val="C"></w:pStyle><w:keepNext/>' in out


def test_a_property_that_says_NO_is_rewritten_not_doubled():
    """ST_OnOff: `w:val="0"` is the property present and switched off.
    CT_PPr allows one, and Word chooses between two on open."""
    out = _keep('<w:p><w:pPr><w:keepNext w:val="0"/></w:pPr></w:p>')

    assert out == "<w:p><w:pPr><w:keepNext/></w:pPr></w:p>"


def test_the_TRACKED_CHANGE_snapshot_is_neither_read_nor_written():
    """`w:pPrChange` holds the properties a tracked change REPLACED.
    Reading it answered for the past — the paragraph looked done and the
    live properties never got the flag — and writing into it edits the
    historical record while the page stays as it was."""
    para = ('<w:p><w:pPr><w:pStyle w:val="C"/>'
            '<w:pPrChange w:id="1" w:author="a"><w:pPr><w:keepNext/>'
            "</w:pPr></w:pPrChange></w:pPr></w:p>")

    out = _keep(para)

    assert '<w:pStyle w:val="C"/><w:keepNext/><w:pPrChange' in out
    assert out.count("<w:keepNext/>") == 2, "the snapshot keeps its own"


def test_a_property_already_in_place_is_left_BYTE_identical():
    """Which is how every caller tells "already done" from "changed":
    they compare the string they got back."""
    para = '<w:p><w:pPr><w:pStyle w:val="C"/><w:keepNext/></w:pPr></w:p>'

    assert _keep(para) == para


def test_a_MISPLACED_property_is_moved_into_its_slot():
    """An older writer leaves one behind, and replacing an element where
    it stands cannot repair that — the same argument as `_set_tbl_pr`'s,
    for the same reason."""
    para = ('<w:p><w:pPr><w:keepNext/><w:pStyle w:val="C"/></w:pPr></w:p>')

    out = _keep(para)

    assert out == ('<w:p><w:pPr><w:pStyle w:val="C"/><w:keepNext/>'
                   "</w:pPr></w:p>")


def test_a_property_is_not_written_INSIDE_a_complex_sibling():
    """`w:pBdr`, `w:tabs`, `w:rPr` and `w:sectPr` hold elements of their
    own. A flat scan for `<w:...>` reads those as siblings and ranks
    `w:top` inside `w:pBdr` as an unknown property — putting the new one
    inside the border definition."""
    para = ('<w:p><w:pPr><w:pBdr><w:top w:val="single"/></w:pBdr>'
            "</w:pPr></w:p>")

    out = _keep(para)

    assert out.index("<w:keepNext/>") < out.index("<w:pBdr>")


def test_an_element_can_be_REMOVED():
    para = '<w:p><w:pPr><w:pStyle w:val="C"/><w:keepNext/></w:pPr></w:p>'

    out = set_para_property(para, "keepNext", "")

    assert out == '<w:p><w:pPr><w:pStyle w:val="C"/></w:pPr></w:p>'


def test_something_that_is_not_a_paragraph_is_left_alone():
    assert _keep("<w:r><w:t>x</w:t></w:r>") == "<w:r><w:t>x</w:t></w:r>"


def test_removing_from_an_EMPTY_pPr_changes_nothing_at_all():
    """The empty-properties branch is not only about expanding: asked to
    REMOVE a property from `<w:pPr/>`, it hands the paragraph back
    exactly as it was. The general path would write `<w:pPr></w:pPr>` —
    the same document, and a line in the next comparison for a paragraph
    nobody edited."""
    para = "<w:p><w:pPr/><w:r/></w:p>"

    assert set_para_property(para, "keepNext", "") == para


def test_a_property_present_TWICE_comes_out_in_FULL():
    """Two `w:keepNext` in one `w:pPr` is invalid and does happen — a
    writer that could not see the first one wrote a second, and a style
    that turns the flag OFF writes `w:val="0"` beside the one that turns
    it on.

    This was pinned the other way on 2026-08-19 ("the document
    unchanged; repairing a duplicate is `lint`'s finding"), off the
    identical-twin fixture — which is the one shape where the harm does
    not show. With the off-copy in it the old walk left
    `<w:keepNext w:val="0"/><w:keepNext/>`: the STALE element first, in a
    document where the writer was asked to make the flag true. And the
    removal below did not remove.

    Taking every copy out is the same repair this writer already makes
    when it moves a misplaced property into its slot, and the offsets
    objection in the old note is answered by re-reading the properties
    after each cut."""
    para = ('<w:p><w:pPr><w:keepNext/><w:keepNext w:val="0"/></w:pPr>'
            "</w:p>")

    assert _keep(para) == "<w:p><w:pPr><w:keepNext/></w:pPr></w:p>"
    assert (set_para_property(para, "keepNext", "")
            == "<w:p><w:pPr></w:pPr></w:p>")


def test_a_RUN_property_present_twice_comes_out_in_full_too():
    """The run writer replaced the first and returned, which left the
    second — a `remove` that does not remove. A run salvaged out of two
    carries `w:sz` twice as often as not."""
    run_xml = '<w:r><w:rPr><w:i/><w:i w:val="0"/></w:rPr><w:t>x</w:t></w:r>'

    assert (set_run_property(run_xml, "i", "<w:i/>")
            == '<w:r><w:rPr><w:i/></w:rPr><w:t>x</w:t></w:r>')
    assert (set_run_property(run_xml, "i", "")
            == '<w:r><w:rPr></w:rPr><w:t>x</w:t></w:r>')


def test_a_property_is_not_written_INSIDE_a_numbered_paragraphs_numPr():
    """`_own_children` skips over what a child CONTAINS, and the sibling
    test above cannot see it do that: `w:pBdr` outranks `w:keepNext`, so
    the walk stops at the first child either way. Here the new property
    sorts AFTER the complex one, so the walk has to step over
    `w:numPr`'s two children — and a scan that reads them as siblings
    ranks `w:ilvl` as unknown and writes the alignment INSIDE the
    numbering definition, which is a list paragraph Word will not
    open."""
    para = ('<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/>'
            "</w:numPr></w:pPr></w:p>")

    out = set_para_property(para, "jc", '<w:jc w:val="center"/>')

    assert out == ('<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
                   '<w:numId w:val="3"/></w:numPr><w:jc w:val="center"/>'
                   "</w:pPr></w:p>")


def test_a_PAIRED_property_element_is_replaced_WHOLE():
    """`<w:pStyle w:val="Body"></w:pStyle>` is the same element as
    `<w:pStyle w:val="Body"/>` and Word writes both. Cut at the end of
    its OPEN tag rather than at its close, the replacement leaves a
    stray `</w:pStyle>` in the properties — the shape named in this
    writer's own docstring as one of the four defects it consolidated."""
    para = ('<w:p><w:pPr><w:pStyle w:val="Body"></w:pStyle></w:pPr>'
            "</w:p>")

    out = set_para_property(para, "pStyle", '<w:pStyle w:val="Quote"/>')

    assert out == ('<w:p><w:pPr><w:pStyle w:val="Quote"/></w:pPr></w:p>')


# --- the empty w:t Word writes (2026-08-19) ----------------------------
#
# S1: `set_run_text` matched only the paired `<w:t>…</w:t>`, and a run
# whose text has been deleted arrives as `<w:t/>`. The write landed
# nowhere and every caller reported success — `tables.set_cell` handed
# back the document unchanged, which is the shape a paper script uses to
# fill a blank cell.
#
# Found while reading `package.set_core_property`, which had the same
# blindness on `<dc:title/>`, and which `lint`'s check 7c already names
# for `<w:tcPr/>`. Three instances of one shape: an EMPTY element is
# self-closing, and a pattern written for the paired form calls it
# absent.


def test_set_run_text_writes_into_an_EMPTY_run():
    from docxkit._xml import set_run_text

    out = set_run_text('<w:r><w:rPr><w:b/></w:rPr><w:t/></w:r>', "0.31")

    assert out == ('<w:r><w:rPr><w:b/></w:rPr><w:t>0.31</w:t></w:r>')


def test_an_empty_run_KEEPS_its_attributes_when_it_is_filled():
    """`<w:t xml:space="preserve"/>` is what Word leaves when it empties
    a run that had edge whitespace, and the attribute is the one thing
    on the tag that must survive being filled."""
    from docxkit._xml import set_run_text

    out = set_run_text('<w:r><w:t xml:space="preserve"/></w:r>', "x")

    assert out == '<w:r><w:t xml:space="preserve">x</w:t></w:r>'


def test_set_cell_fills_a_BLANK_cell():
    """The S1 as a caller meets it. A table typed with its value column
    left empty is the ordinary starting point for a generated table, and
    `set_cell` reported success on every one of them while changing
    nothing."""
    from docxkit import tables

    doc = ("<w:document><w:body><w:tbl><w:tblPr/><w:tblGrid>"
           '<w:gridCol w:w="900"/><w:gridCol w:w="900"/></w:tblGrid>'
           "<w:tr><w:tc><w:p><w:r><w:t>Country</w:t></w:r></w:p></w:tc>"
           "<w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>"
           "<w:tr><w:tc><w:p><w:r><w:t>Poland</w:t></w:r></w:p></w:tc>"
           "<w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t/></w:r></w:p>"
           "</w:tc></w:tr></w:tbl></w:body></w:document>")
    t = tables.read_all(doc)[0]

    out = tables.set_cell(doc, t, 1, 1, "0.31")

    assert tables.read_all(out)[0].rows == [["Country", "Value"],
                                            ["Poland", "0.31"]]
    assert "<w:b/>" in out, "the cell's formatting is the paper's"


def test_a_run_property_is_placed_before_the_FIRST_child_it_outranks():
    """`break`, on the walk that finds the slot. A run with two
    properties the new one sorts ahead of is the ordinary case — `w:i`
    and `w:sz` are what a table cell out of a paper states — and
    without the break the insert lands before the LAST of them instead
    of the first, which is a `w:b` after the italic and a run Word
    refuses.

    `w:sz` also has to be the tag that is REPLACED here: the same-name
    scan compares a regex group against the caller's string, and a
    one-character property name (`i`, `b`) is interned, so an identity
    reading of it holds for those and fails for every longer one."""
    run_xml = '<w:r><w:rPr><w:i/><w:sz w:val="24"/></w:rPr><w:t>x</w:t></w:r>'

    assert set_run_property(run_xml, "b", "<w:b/>") == (
        '<w:r><w:rPr><w:b/><w:i/><w:sz w:val="24"/></w:rPr>'
        "<w:t>x</w:t></w:r>")
    assert set_run_property(run_xml, "sz", '<w:sz w:val="20"/>') == (
        '<w:r><w:rPr><w:i/><w:sz w:val="20"/></w:rPr><w:t>x</w:t></w:r>')


# --- the run of 2026-08-20: 4.5 % (20/448) ----------------------------
#
# Four of the twenty are the tests above. The other sixteen are argued,
# and all sixteen were put through kill_check to check the argument
# rather than assume it. (A re-measurement the same afternoon sampled
# the lines this round CHANGED and found two more holes in them: the
# slot walk's `break` and the same-name scan read as an identity, both
# pinned by the test above. Two more equivalences came with them, at
# the foot of this note.):
#
# * ELEVEN readings of `(/?)`, the optional slash in an open tag, across
#   `matching_close`, `element_spans`, `own_properties`, `_own_children`
#   and `_para_with_properties`. The group can only be "" or "/", so
#   `>= "/"` is `== "/"` on that domain, and `is "/"` is too — a
#   one-character ASCII string comes back interned. `<= "/"` is the odd
#   one out, because "" satisfies it, and that one IS a test above.
# * `pos = 0` written `pos = -1` in the two scan loops. A negative `pos`
#   handed to `re.Pattern.search` is clamped to 0 by SRE before the
#   scan, so the first search reads the whole string either way and the
#   variable is reassigned from the match after that.
# * `body != body.strip()` written `is not` in `set_run_text`. `strip`
#   returns the string ITSELF when there is nothing to take off, so the
#   two agree at both ends of the question.
# * the two `w:fldCharType` comparisons read as `<=`. ST_FldCharType has
#   exactly three values — begin, separate, end — and "begin" is the
#   first of the three alphabetically, so nothing legal sorts under it;
#   "separate" sorts above "end", so the second comparison cannot widen
#   either.
# * `(span[0], -span[1])` written `~span[1]`: bit-inversion is
#   -x - 1, which orders the second key exactly as negation does.
# * the two `m.group(1)` written `m.group(0)` on the field grammar.
#   Group 0 is the begin marker, group 1, and the end marker. For
#   `dead_links` that adds two `w:fldChar` tags to a findall for
#   `w:instrText`, which matches neither. For the label in
#   `internal_links` the slice start is an offset into group 1, so
#   reading group 0 moves the window back by the length of the begin
#   tag — 34 characters for the bare form, against the 37 of the
#   separate marker it lands inside. The window therefore opens in the
#   middle of a `w:fldChar` tag, and `visible_text` needs a matched
#   `w:t` pair to read anything at all. [The findall half holds. The
#   slice half does NOT: a begin marker with attributes is longer than
#   the separate one, and the window then opens before it — killed
#   2026-09-17, in `dead_links` as well.]
# * `not inner and ... endswith("/>")` read as `or` in
#   `set_para_property`. The two differ only for `<w:pPr></w:pPr>` —
#   empty but paired — and there the expand branch writes the same text
#   the general path does, for both a set and a remove.
# * `> rank` read as `>=` in `set_run_property`. Equal ranks mean equal
#   names, which the branch above has already returned on, or two
#   properties the table does not know — and RPR_ORDER is the COMPLETE
#   EG_RPrBase, so a second unranked child is one that cannot be in a
#   run's properties in the first place. [The TAG is the caller's, and
#   need not be in the table: killed 2026-09-17, both writers.]
#
# From the re-measurement:
#
# * `idx = len(runs) - 1 - i` read as `- 1 ^ i` in `set_run_text`. The
#   index is only ever compared against 0, and a xor is zero exactly
#   when its operands are equal — which is exactly when the subtraction
#   is.
# * `> rank` read as `>=` in `set_para_property`, the paragraph's answer
#   to the rPr slot walk. Same argument as that one, on the same
#   grounds: PPR_ORDER is the complete CT_PPr, and the same-name copies
#   are taken out above.


# ------------------------------------------------------------ split_run --
#
# A run's children that PRINT and are not `w:t` — a no-break hyphen, a
# tab, a line break. `visible_text` walks `w:t` only, so none of them
# contributes a character to it and no text gate can see one arrive.
# Rebuilding a fragment with `set_run_text` kept the run's structure and
# therefore COPIED them: Aging_Well's §1 turned one hyphen into seven
# over four citation wraps, printed them inside the citations, and
# `compare` called the two documents identical (backlog S1, 2026-08-21).

HYPHEN_RUN = ('<w:r><w:rPr><w:b/></w:rPr>'
              '<w:t xml:space="preserve">Neither trade</w:t>'
              "<w:noBreakHyphen/>"
              '<w:t xml:space="preserve">offs and more</w:t></w:r>')


@pytest.mark.parametrize("at", [0, 5, 13, 17, 26, 99])
def test_a_printing_child_survives_a_split_exactly_ONCE(at):
    left, right = split_run(HYPHEN_RUN, at)

    assert (left + right).count("<w:noBreakHyphen/>") == 1, (left, right)


def test_the_printing_child_rides_with_the_text_it_FOLLOWS():
    """Document order decides: what stands before the cut goes left. The
    hyphen sits after "Neither trade", so a cut at 5 leaves it right and
    a cut at 17 leaves it left."""
    assert "<w:noBreakHyphen/>" in split_run(HYPHEN_RUN, 5)[1]
    assert "<w:noBreakHyphen/>" in split_run(HYPHEN_RUN, 17)[0]


@pytest.mark.parametrize("at", [0, 5, 13, 17, 26])
def test_a_split_keeps_every_character_of_the_visible_text(at):
    left, right = split_run(HYPHEN_RUN, at)

    assert visible_text(left) + visible_text(right) == visible_text(HYPHEN_RUN)
    assert visible_text(left) == visible_text(HYPHEN_RUN)[:at]


def test_both_halves_keep_the_run_PROPERTIES():
    """`w:rPr` is formatting, not content: it belongs to every fragment
    of what it formatted, which is why it is the one child copied."""
    left, right = split_run(HYPHEN_RUN, 5)

    assert "<w:b/>" in left and "<w:b/>" in right


def test_a_split_past_the_end_yields_the_whole_run_and_nothing():
    left, right = split_run(HYPHEN_RUN, 99)

    assert visible_text(left) == visible_text(HYPHEN_RUN)
    assert right == ""


def test_a_NEGATIVE_offset_is_refused():
    """A caller that computed one has miscounted somewhere the halves
    cannot show."""
    with pytest.raises(ValueError, match="before the run"):
        split_run(HYPHEN_RUN, -1)


def test_something_that_is_not_a_run_comes_back_whole():
    assert split_run("<w:bookmarkStart w:id=\"1\" w:name=\"x\"/>", 3) == (
        "<w:bookmarkStart w:id=\"1\" w:name=\"x\"/>", "")


# ---------------------------------------------------------- printed_text --

def test_printed_text_renders_what_visible_text_leaves_out():
    """Four characters a reader sees and a `w:t` walk does not."""
    xml = ("<w:r><w:t>trade</w:t><w:noBreakHyphen/><w:t>offs</w:t>"
           "<w:tab/><w:t>then</w:t><w:br/><w:t>next</w:t></w:r>")

    assert visible_text(xml) == "tradeoffsthennext"
    assert printed_text(xml) == "trade\u2011offs\tthen\nnext"


def test_printed_text_keeps_the_children_in_DOCUMENT_order():
    """The stream is compared position by position, so a hyphen that
    moved from one side of a word to the other has to read as a
    difference."""
    a = "<w:r><w:t>a</w:t><w:noBreakHyphen/><w:t>b</w:t></w:r>"
    b = "<w:r><w:noBreakHyphen/><w:t>a</w:t><w:t>b</w:t></w:r>"

    assert printed_text(a) != printed_text(b)
    assert visible_text(a) == visible_text(b), "the reading that was blind"


def test_printed_text_unescapes_like_visible_text_does():
    xml = "<w:r><w:t>Rowe &amp; Kahn</w:t></w:r>"

    assert printed_text(xml) == "Rowe & Kahn"


def test_a_w_sym_is_NOT_rendered():
    """Its character lives in an attribute against a font, so rendering
    one is a lookup and not a constant — and a wrong guess would report
    a difference that is not there."""
    xml = '<w:r><w:t>a</w:t><w:sym w:font="Symbol" w:char="F0B7"/></w:r>'

    assert printed_text(xml) == "a"


def test_the_TEXT_layer_compares_the_printed_reading():
    """The gate's own blindness, end to end: six hyphens deleted from
    inside Aging_Well's citations gave `REAL change locations: 0`, and
    the tool called the two documents identical while the page
    differed."""
    from docxkit._compare_read import Para

    clean = Para("<w:p><w:r><w:t>Neither trade</w:t><w:noBreakHyphen/>"
                 "<w:t>offs (Rowe 1987) nor more</w:t></w:r></w:p>")
    strayed = Para("<w:p><w:r><w:t>Neither trade</w:t><w:noBreakHyphen/>"
                   "<w:t>offs (</w:t></w:r><w:r><w:noBreakHyphen/>"
                   "<w:t>Rowe 1987</w:t></w:r>"
                   "<w:r><w:t>) nor more</w:t></w:r></w:p>")

    assert clean.text != strayed.text
    assert "(\u2011Rowe" in strayed.text


# --- a tab STOP is not a printed tab ------------------------------------
#
# `<w:tab/>` is two elements. As a RUN child it is a tab character on the
# page; inside `w:pPr/w:tabs` it DEFINES a tab stop and prints nothing.
# The printing-children pattern matched the tag wherever it stood, so
# every tab stop a paragraph defined read as a tab at its start, and a
# paragraph whose stops changed \u2014 a formatting edit \u2014 was reported by
# `compare` as a TEXT edit that failed `--expect-clean` (2026-09-17).

_LEFT_RIGHT = "<w:r><w:t>Left</w:t><w:tab/><w:t>Right</w:t></w:r>"
_ONE_STOP = '<w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs>'
_TWO_STOPS = ('<w:tabs><w:tab w:val="left" w:pos="720"/>'
              '<w:tab w:val="right" w:pos="9000"/></w:tabs>')


@pytest.mark.parametrize("stops", [_ONE_STOP, _TWO_STOPS],
                         ids=["one_stop", "two_stops"])
def test_a_tab_STOP_in_the_paragraph_properties_prints_nothing(stops):
    xml = f"<w:p><w:pPr>{stops}</w:pPr>{_LEFT_RIGHT}</w:p>"

    assert printed_text(xml) == "Left\tRight"


def test_the_stops_in_a_TRACKED_formatting_snapshot_print_nothing_either():
    """`w:pPrChange` keeps the OLD properties, tab stops included, inside
    the live `w:pPr` \u2014 the same element one level deeper."""
    xml = (f"<w:p><w:pPr>{_ONE_STOP}<w:pPrChange w:id=\"4\" w:author=\"A\">"
           f"<w:pPr>{_TWO_STOPS}</w:pPr></w:pPrChange></w:pPr>"
           f"{_LEFT_RIGHT}</w:p>")

    assert printed_text(xml) == "Left\tRight"


def test_an_EMPTY_tabs_element_does_not_swallow_the_text_after_it():
    """`<w:tabs/>` defines no stops and opens nothing: read as an opening
    tag, it would pair with the next paragraph's `</w:tabs>` and every
    word between the two would vanish from the comparison."""
    xml = (f"<w:p><w:pPr><w:tabs/></w:pPr>{_LEFT_RIGHT}</w:p>"
           f"<w:p><w:pPr>{_ONE_STOP}</w:pPr>{run('Next')}</w:p>")

    assert printed_text(xml) == "Left\tRightNext"


def test_a_tab_CHARACTER_still_prints_beside_a_paragraph_with_stops():
    """The fix may not buy its silence by going blind: the run's own tab
    is still a character, and two of them are still two."""
    xml = (f"<w:p><w:pPr>{_ONE_STOP}</w:pPr><w:r><w:t>a</w:t><w:tab/>"
           f"<w:tab/><w:t>b</w:t></w:r></w:p>")

    assert printed_text(xml) == "a\t\tb"


def test_printed_text_can_be_asked_for_SOME_of_the_children():
    """`snapshot` reads a paragraph as `visible_text` does plus a tab \u2014
    the reading a protocol copies its anchors out of \u2014 and asks this
    function for exactly that, so the tab-stop guard lives in one place."""
    xml = ("<w:p><w:pPr>" + _ONE_STOP + "</w:pPr><w:r><w:t>trade</w:t>"
           "<w:noBreakHyphen/><w:t>offs</w:t><w:tab/><w:t>x</w:t><w:br/>"
           "</w:r></w:p>")

    assert printed_text(xml, printing={"tab": "\t"}) == "tradeoffs\tx"


def _compare_exit(monkeypatch, tmp_path, a_ppr: str, b_ppr: str,
                  b_run: str = _LEFT_RIGHT) -> int | str | None:
    from conftest import make_parts, write

    from docxkit.cli import main

    a = write(tmp_path / "a.docx",
              make_parts(f"<w:p><w:pPr>{a_ppr}</w:pPr>{_LEFT_RIGHT}</w:p>"))
    b = write(tmp_path / "b.docx",
              make_parts(f"<w:p><w:pPr>{b_ppr}</w:pPr>{b_run}</w:p>"))
    monkeypatch.setattr("sys.argv", ["docxkit", "compare", a, b,
                                     "--expect-clean"])
    with pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code


def test_COMPARE_passes_a_pair_that_differs_only_in_TAB_STOPS(
        monkeypatch, tmp_path, capsys):
    """The end-to-end shape: one stop against two, the same words. It
    printed `EDGE leading: '\\t' -> '\\t\\t'` under TEXT and exited 1."""
    code = _compare_exit(monkeypatch, tmp_path, _ONE_STOP, _TWO_STOPS)
    out = capsys.readouterr().out

    assert code in (0, None), out
    assert "EDGE leading" not in out


def test_COMPARE_still_fails_a_pair_whose_TAB_CHARACTERS_differ(
        monkeypatch, tmp_path, capsys):
    """The control: the same stops on both sides, and a real tab CHARACTER
    opening the paragraph on one of them — which Word prints as an indent
    and the TEXT layer reads at the paragraph's edge."""
    indented = "<w:r><w:tab/><w:t>Left</w:t><w:tab/><w:t>Right</w:t></w:r>"

    code = _compare_exit(monkeypatch, tmp_path, _ONE_STOP, _ONE_STOP,
                         b_run=indented)
    out = capsys.readouterr().out

    assert code == 1
    assert "EDGE leading: '' -> '\\t'" in out


# --- the sweep of 2026-09-17: what the writers stand on ------------------
#
# A whole sweep left `zip_entry` and `append_before_close` alive in every
# mutation — nothing in this harness called either by name, and every
# package writer goes through both — and `split_run` alive wherever its
# TAGS changed, because the tests above read the halves through
# `visible_text`, which cannot see a tag.


def test_ZIP_STAMP_is_the_zip_EPOCH():
    """Pinned by value, because the value is the zip format's and not
    this package's. A member's timestamp is an MS-DOS date: years count
    from 1980, months and days from 1, so 1980-01-01 00:00:00 is the
    earliest stamp a member can carry, and `zipfile` refuses a year
    before it. Any fixed stamp makes the bytes reproducible; the source
    comment promises this one."""
    assert ZIP_STAMP == (1980, 1, 1, 0, 0, 0)
    with pytest.raises(ValueError, match="before 1980"):
        zipfile.ZipInfo("x", date_time=(1979, 12, 31, 23, 59, 58))


def test_a_zip_entry_writes_what_writestr_writes_for_a_BARE_NAME(
        monkeypatch):
    """`zip_entry` promises everything `writestr` sets from a bare string
    name, with the clock taken out — and CPython can be asked for that
    reading directly: it stamps a bare-name member with
    `SOURCE_DATE_EPOCH` when one is set. At the zip epoch the two
    archives must be the same bytes.

    The permission bits are compared on the entry too, before anything
    writes it: `zipfile` fills in `0o600 << 16` for an entry whose
    `external_attr` is ZERO, so an entry that lost them altogether would
    still write this archive."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "315532800")   # 1980-01-01 UTC
    name, data = "word/document.xml", b"<w:document/>"

    def archive(member: str | zipfile.ZipInfo) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(member, data)
        return buf.getvalue()

    bare = archive(name)

    assert archive(zip_entry(name)) == bare
    with zipfile.ZipFile(io.BytesIO(bare)) as z:
        assert zip_entry(name).external_attr == z.getinfo(name).external_attr


def test_append_before_close_writes_the_addition_as_the_LAST_child():
    """The splice `hygiene` and `comments` add relationships, overrides
    and comments with. A close tag spelled with a prefix other than `w:`
    is the ordinary case for the comment side parts."""
    ex = '<w15:commentsEx><w15:commentEx w15:paraId="1"/></w15:commentsEx>'

    assert append_before_close(ex, "</w15:commentsEx>",
                               '<w15:commentEx w15:paraId="2"/>') == (
        '<w15:commentsEx><w15:commentEx w15:paraId="1"/>'
        '<w15:commentEx w15:paraId="2"/></w15:commentsEx>')


def test_a_split_at_the_run_END_gives_the_whole_run_back_BYTE_for_byte():
    """`wrap_visible_span` cuts the last run it wraps at the wrap's end,
    and when the wrap reaches the end of that run it throws the RIGHT
    half away. So at that offset the right half has to be empty and the
    left the whole run — the tab after the last `w:t` included, which
    stands exactly at the cut. Handed to the right half there, the tab
    is deleted by the caller.

    Compared as bytes, and with a property element in the run: a left
    half that carried the run's own close tag inside its content, or its
    properties twice, reads the same through `visible_text`."""
    run_xml = '<w:r><w:rPr><w:i/></w:rPr><w:t>Rowe 1987</w:t><w:tab/></w:r>'

    assert split_run(run_xml, 9) == (run_xml, "")


def test_a_cut_w_t_keeps_its_OWN_open_tag_in_both_halves():
    """Each half of a cut `w:t` is still that element, attributes and
    all. Rebuilt from a bare `<w:t>`, "Neith" loses nothing a text
    comparison sees, which is why the offset tests above cannot."""
    left, right = split_run(HYPHEN_RUN, 5)

    assert left == ('<w:r><w:rPr><w:b/></w:rPr>'
                    '<w:t xml:space="preserve">Neith</w:t></w:r>')
    assert right == ('<w:r><w:rPr><w:b/></w:rPr>'
                     '<w:t xml:space="preserve">er trade</w:t>'
                     "<w:noBreakHyphen/>"
                     '<w:t xml:space="preserve">offs and more</w:t></w:r>')


@pytest.mark.parametrize(("at", "left", "right"), [
    (3, "<w:t>one</w:t>", '<w:t xml:space="preserve"> two</w:t>'),
    (4, '<w:t xml:space="preserve">one </w:t>', "<w:t>two</w:t>"),
], ids=["space_leads_the_right", "space_ends_the_left"])
def test_a_half_gets_xml_space_ONLY_where_the_cut_leaves_an_edge_space(
        at, left, right):
    """The halves' own space guard. A BARE `<w:t>` cut beside its space,
    at both of its sides: the half with the space at its edge needs the
    attribute or Word drops the space on save, and the other must not
    get it. Both sides, because a leading space sorts BELOW the stripped
    text and a trailing one above it, so an ordering reading of "differs
    from its strip" holds on one side only."""
    assert split_run("<w:r><w:t>one two</w:t></w:r>", at) == (
        f"<w:r>{left}</w:r>", f"<w:r>{right}</w:r>")


def test_a_run_cut_off_before_its_close_is_split_as_if_it_closed_at_the_end():
    """No caller hands over such a fragment today; the branch for it is
    there, and what it prevents is `rfind`'s -1 used as a slice end,
    which eats the fragment's last character — the `>` of its `w:t` —
    and leaves a text node no pattern reads."""
    assert split_run("<w:r><w:t>abcd</w:t>", 2) == (
        "<w:r><w:t>ab</w:t></w:r>", "<w:r><w:t>cd</w:t></w:r>")


def test_the_run_properties_come_out_of_its_content_ONCE():
    """The run's own `w:rPr` is copied to both halves and taken out of
    the content once. A text box anchored in the run holds runs of its
    own, and their properties can read exactly as the anchoring run's
    do — taken out a second time, the box loses its formatting.

    The cut is in the run's own text, before the box, so the box rides
    right whole."""
    box = ("<w:pict><v:shape><v:textbox><w:txbxContent><w:p><w:r>"
           "<w:rPr><w:b/></w:rPr><w:t>box</w:t></w:r></w:p>"
           "</w:txbxContent></v:textbox></v:shape></w:pict>")
    run_xml = f"<w:r><w:rPr><w:b/></w:rPr><w:t>ab</w:t>{box}</w:r>"

    assert split_run(run_xml, 1) == (
        "<w:r><w:rPr><w:b/></w:rPr><w:t>a</w:t></w:r>",
        f"<w:r><w:rPr><w:b/></w:rPr><w:t>b</w:t>{box}</w:r>")


def _field_with_code_text(result: str) -> str:
    """A HYPERLINK field whose begin marker carries `w:fldLock` and
    `w:dirty` — 29 characters more than the separate marker — and whose
    code half holds a `w:t` just before the separate. Word writes the
    code as `w:instrText`; the `w:t` is schema-valid, and it is what
    makes a window that opens early SHOW something."""
    return ('<w:r><w:fldChar w:fldCharType="begin" w:fldLock="true" '
            'w:dirty="true"/></w:r>'
            '<w:r><w:instrText>HYPERLINK \\l "Table1"</w:instrText>'
            '<w:t>code</w:t><w:fldChar w:fldCharType="separate"/></w:r>'
            + result
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_a_field_label_is_read_from_the_SEPARATE_whatever_the_begin_holds():
    """The separator is found in the field's CONTENT, so its offset is
    into the content. Applied to the whole match, which starts at the
    begin marker, the window opens as many characters early as that
    marker is long — harmless for the bare marker, which is shorter than
    the separate one the window then opens inside, and not for a marker
    with attributes."""
    xml = _field_with_code_text("<w:r><w:t>Table 1</w:t></w:r>")

    assert internal_links(xml) == [("Table1", "Table 1")]


def test_a_field_whose_RESULT_is_empty_is_dead_whatever_its_code_holds():
    """The same offset, in `dead_links`: read from the begin marker, the
    window reaches back into the code half, finds text there, and calls
    an emptied link alive."""
    xml = _field_with_code_text('<w:bookmarkEnd w:id="7"/>')

    assert dead_links(xml) == ["Table1"]


def test_a_run_property_AFTER_a_duplicate_pair_is_kept_whole():
    """The later copies come out back to front and the first is replaced
    last, so by then the text after the first copy has shrunk by every
    later one — and reading the tail from the LAST copy's old end cuts
    into whatever follows it. The twin test above has nothing after the
    pair, which is the one shape where the two readings agree."""
    run_xml = ('<w:r><w:rPr><w:i/><w:i w:val="0"/><w:sz w:val="20"/>'
               "</w:rPr><w:t>x</w:t></w:r>")

    assert set_run_property(run_xml, "i", "<w:i/>") == (
        '<w:r><w:rPr><w:i/><w:sz w:val="20"/></w:rPr><w:t>x</w:t></w:r>')


def test_a_property_the_ORDER_does_not_know_is_written_after_EVERY_child():
    """"An unknown property sorts LAST", in `RPR_ORDER`'s own words, and
    `set_para_property` places by the same rule. Last is after a live
    child the order does not know either: two unknowns RANK equal, and
    the slot walk must not stop in front of the first one it meets.

    Both writers take the tag from the caller — `edit`'s run sweep from
    a paper script's mapping — so a name newer than the order is theirs
    to pass."""
    run_xml = '<w:r><w:rPr><w:b/><w:newerA/></w:rPr><w:t>x</w:t></w:r>'
    para = '<w:p><w:pPr><w:jc w:val="left"/><w:newerA/></w:pPr></w:p>'

    assert set_run_property(run_xml, "newerB", "<w:newerB/>") == (
        "<w:r><w:rPr><w:b/><w:newerA/><w:newerB/></w:rPr>"
        "<w:t>x</w:t></w:r>")
    assert set_para_property(para, "newerB", "<w:newerB/>") == (
        '<w:p><w:pPr><w:jc w:val="left"/><w:newerA/><w:newerB/></w:pPr>'
        "</w:p>")


# --- a run property written as a PAIR (2026-09-17) ----------------------
#
# S1: `<w:b></w:b>` is the same element as `<w:b/>`, and Word writes
# both. `set_run_property` found its own property with a scan for
# OPENING tags, so a replace wrote the new element over the open tag and
# left `</w:b>` standing, and a remove left the close alone. Properties
# like that do not parse, which is what Word calls unreadable content —
# reported by a call that returned a string and looked like it worked.
#
# `set_para_property` was fixed for this exact shape (see
# `test_a_PAIRED_property_element_is_replaced_WHOLE` above, whose
# docstring is the one that says Word writes both forms). The run
# writer, "the same shape" by its own docstring, was not: the fix is
# `_own_children`, which is how the paragraph writer reads a child.

PAIRED_RUN = ('<w:r><w:rPr><w:b></w:b><w:sz w:val="20"></w:sz></w:rPr>'
              "<w:t>x</w:t></w:r>")


def _parsed(fragment: str) -> ElementTree.Element:
    """The fragment PARSED, its namespaces declared on its own root.

    Every text assertion in this file passed while the writer was
    emitting `<w:b w:val="0"/></w:b>`: reading the result as a string
    cannot see a close tag that belongs to nothing. A parser sees it at
    once, and it is the reading Word performs on open.
    """
    return ElementTree.fromstring(fragment.replace(">", f" {NS}>", 1))


@pytest.mark.parametrize(("tag", "element", "want"), [
    ("b", '<w:b w:val="0"/>',
     '<w:r><w:rPr><w:b w:val="0"/><w:sz w:val="20"></w:sz></w:rPr>'
     "<w:t>x</w:t></w:r>"),
    ("b", "",
     '<w:r><w:rPr><w:sz w:val="20"></w:sz></w:rPr><w:t>x</w:t></w:r>'),
    ("sz", '<w:sz w:val="24"/>',
     '<w:r><w:rPr><w:b></w:b><w:sz w:val="24"/></w:rPr><w:t>x</w:t></w:r>'),
], ids=["replace_the_first", "remove_it", "replace_a_later_one"])
def test_a_PAIRED_run_property_is_taken_WHOLE(tag, element, want):
    """All three doors into the same cut: the first child, its removal,
    and a child the walk reaches past another paired one."""
    out = set_run_property(PAIRED_RUN, tag, element)

    _parsed(out)
    assert out == want


def test_a_PAIRED_run_property_present_TWICE_comes_out_in_full():
    """The duplicate copies are cut by the same reading, so they left a
    close tag each. A run salvaged out of two carries `w:sz` twice as
    often as not, and either spelling of the pair is one Word wrote."""
    run_xml = ('<w:r><w:rPr><w:i></w:i><w:i w:val="0"></w:i>'
               '<w:sz w:val="20"/></w:rPr><w:t>x</w:t></w:r>')

    out = set_run_property(run_xml, "i", "<w:i/>")

    _parsed(out)
    assert out == ('<w:r><w:rPr><w:i/><w:sz w:val="20"/></w:rPr>'
                   "<w:t>x</w:t></w:r>")


def test_a_PAIRED_property_does_not_move_where_a_NEW_one_lands():
    """The slot walk reads the same children, and a paired one must be
    stepped over whole: ranking its close tag as a child of its own put
    the new property inside the pair it had just walked past."""
    run_xml = ('<w:r><w:rPr><w:i></w:i><w:sz w:val="24"></w:sz></w:rPr>'
               "<w:t>x</w:t></w:r>")

    out = set_run_property(run_xml, "b", "<w:b/>")

    _parsed(out)
    assert out == ('<w:r><w:rPr><w:b/><w:i></w:i><w:sz w:val="24"></w:sz>'
                   "</w:rPr><w:t>x</w:t></w:r>")
