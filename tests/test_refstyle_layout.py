"""Where the reference LIST sits, as opposed to how an entry reads.

Two house rules that drift on ordinary author rounds — the list starts on
a new page, and every entry is set with a 0.5" hanging indent, no space
before and 4 pt after — plus the alphabetical order, which `audit` could
report and nothing could repair until :func:`refstyle.refile`.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run

from docxkit import styles
from docxkit._xml import PARA_RE, visible_text
from docxkit.refstyle import (
    HOUSE_LAYOUT,
    Layout,
    audit,
    entry_layout_issues,
    layout,
    refile,
)

HOUSE_PPR = ('<w:pPr><w:spacing w:before="0" w:after="80"/>'
             '<w:ind w:left="720" w:hanging="720"/></w:pPr>')

A = 'Acemoglu, D. (2020). "Robots and Jobs." Journal of Political Economy.'
B = 'Barr, N. (2010). Pension Reform: A Short Guide. Oxford: OUP.'
C = 'Currie, J. (1999). "Health and the Labor Market." Handbook of Labor.'


def entry(text: str, ppr: str = HOUSE_PPR, pid: str = "11111111") -> str:
    return f'<w:p w14:paraId="{pid}" w14:textId="{pid}">{ppr}{run(text)}</w:p>'


def heading(text: str = "References", ppr: str = "") -> str:
    return f'<w:p w14:paraId="90000000">{ppr}{run(text)}</w:p>'


def reflist(*entries: str, head: str = heading()) -> str:
    return para(run("Body text before the list.")) + head + "".join(entries)


def codes(report) -> set[str]:
    return {i.code for i in report.issues}


# ------------------------------------------------------- the entry rule ---

def test_a_house_formatted_entry_has_nothing_to_say():
    assert entry_layout_issues(entry(A), None) == []


def test_a_pasted_entry_states_none_of_it():
    """What a browser paste looks like: no indent, no spacing of its own."""
    issues = entry_layout_issues(entry(A, ppr=""), None)
    assert {i.code for i in issues} == {"indent", "spacing"}
    # `before` is 0 either way, so only THREE of the four rules are open:
    # left, hanging and after.
    assert len(issues) == 3


def test_layout_sets_the_indent_and_the_spacing():
    parts = make_parts(reflist(entry(A, ppr=""), entry(B, ppr="")))
    report = layout(parts)
    doc = parts["word/document.xml"].decode()
    assert doc.count('<w:ind w:left="720" w:hanging="720"/>') == 2
    assert doc.count('<w:spacing w:after="80"/>') == 2
    assert len(report.indented) == 4         # left + hanging, twice
    assert len(report.spaced) == 2


def test_layout_corrects_a_wrong_value_and_keeps_the_others():
    """6 pt after and a 0.25" indent — the older house values."""
    old = ('<w:pPr><w:spacing w:after="120" w:line="240" w:lineRule="auto"/>'
           '<w:ind w:left="360" w:hanging="360" w:right="200"/></w:pPr>')
    parts = make_parts(reflist(entry(A, ppr=old)))
    layout(parts)
    doc = parts["word/document.xml"].decode()
    assert 'w:after="80"' in doc and 'w:after="120"' not in doc
    assert 'w:left="720"' in doc and 'w:hanging="720"' in doc
    # The paragraph's own line rule and right indent are not this rule's
    # to drop.
    assert 'w:line="240"' in doc and 'w:right="200"' in doc


def test_layout_is_idempotent_so_it_doubles_as_an_audit():
    parts = make_parts(reflist(entry(A, ppr=""), entry(B, ppr="")))
    layout(parts)
    first = parts["word/document.xml"]
    again = layout(parts)
    assert parts["word/document.xml"] == first
    assert not again


def test_an_inherited_house_value_is_left_to_the_style():
    """Word deletes a declaration equal to the inherited one, so writing
    one makes an audit that can never come back clean."""
    styles_xml = (
        "<w:styles><w:style w:type=\"paragraph\" w:styleId=\"Ref\">"
        '<w:pPr><w:spacing w:before="0" w:after="80"/>'
        '<w:ind w:left="720" w:hanging="720"/></w:pPr></w:style></w:styles>')
    styled = ('<w:pPr><w:pStyle w:val="Ref"/></w:pPr>')
    parts = make_parts(reflist(entry(A, ppr=styled)),
                       extra={"word/styles.xml": styles_xml})
    report = layout(parts)
    # The entry is untouched; only the heading's page break is written.
    assert entry(A, ppr=styled) in parts["word/document.xml"].decode()
    assert not report.indented and not report.spaced
    assert entry_layout_issues(entry(A, ppr=styled), styles_xml) == []


def test_an_unstated_zero_is_not_written_out():
    """`before` is 0 by default; declaring it would not survive a save."""
    parts = make_parts(reflist(entry(A, ppr="")))
    layout(parts)
    assert 'w:before=' not in parts["word/document.xml"].decode()


def test_the_spec_is_a_parameter_not_a_constant():
    parts = make_parts(reflist(entry(A, ppr="")))
    layout(parts, Layout(hanging=360, before=0, after=120, page_break=False))
    doc = parts["word/document.xml"].decode()
    assert 'w:left="360"' in doc and 'w:after="120"' in doc
    assert "pageBreakBefore" not in doc


# -------------------------------------------------------- the page rule ---

def test_the_list_is_given_a_page_of_its_own():
    parts = make_parts(reflist(entry(A)))
    report = layout(parts)
    doc = parts["word/document.xml"].decode()
    assert "<w:pageBreakBefore/>" in doc
    assert report.page_break
    # on the HEADING, not on the first entry
    assert doc.index("<w:pageBreakBefore/>") < doc.index("References")


def test_a_page_break_already_there_is_left_alone():
    head = heading(ppr="<w:pPr><w:pageBreakBefore/></w:pPr>")
    parts = make_parts(reflist(entry(A), head=head))
    before = parts["word/document.xml"]
    report = layout(parts)
    assert parts["word/document.xml"] == before
    assert not report.page_break


def test_an_explicit_break_above_the_heading_counts():
    """A paper that starts the page with a break RUN is already right, and
    replacing it with a property would be a change nobody asked for."""
    body = (para(run("Body."), '<w:r><w:br w:type="page"/></w:r>')
            + heading() + entry(A))
    parts = make_parts(body)
    report = layout(parts)
    assert not report.page_break
    assert "<w:pageBreakBefore/>" not in parts["word/document.xml"].decode()


def test_a_section_break_above_the_heading_counts():
    body = (para(run("Body."), "<w:pPr><w:sectPr><w:type "
                               'w:val="nextPage"/></w:sectPr></w:pPr>')
            + heading() + entry(A))
    parts = make_parts(body)
    assert not layout(parts).page_break


# ------------------------------------------------------------ the audit ---

def test_audit_reports_what_layout_repairs():
    parts = make_parts(reflist(entry(A, ppr=""), entry(B, ppr="")))
    found = codes(audit(parts))
    assert {"indent", "spacing", "page-break"} <= found
    layout(parts)
    assert not ({"indent", "spacing", "page-break"} & codes(audit(parts)))


def test_a_paper_that_sets_its_list_differently_can_say_so():
    parts = make_parts(reflist(entry(A, ppr=""), entry(B, ppr="")))
    found = codes(audit(parts, page_layout=None))
    assert not ({"indent", "spacing", "page-break"} & found)


# ------------------------------------------------------------- refiling ---

def test_refile_sorts_the_list():
    parts = make_parts(reflist(entry(C, pid="00000001"),
                               entry(A, pid="00000002"),
                               entry(B, pid="00000003")))
    report = refile(parts)
    doc = parts["word/document.xml"].decode()
    assert doc.index("Acemoglu") < doc.index("Barr") < doc.index("Currie")
    assert report.moved


def test_refile_is_a_no_op_on_a_list_already_filed():
    parts = make_parts(reflist(entry(A), entry(B), entry(C)))
    before = parts["word/document.xml"]
    report = refile(parts)
    assert parts["word/document.xml"] == before
    assert not report.moved and not report.refused


def test_an_entry_moves_with_the_bookmark_word_hoisted_out_of_it():
    """The trap: Word puts a whole-paragraph bookmark BESIDE the paragraph,
    so a sorter built on the `w:p` matches drops every entry anchor and
    only `citations` notices."""
    def anchored(text: str, name: str, bid: int, pid: str) -> str:
        return (f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
                f'<w:bookmarkEnd w:id="{bid}"/>' + entry(text, pid=pid))

    parts = make_parts(reflist(anchored(C, "Currie1999", 1, "00000001"),
                               anchored(A, "Acemoglu2020", 2, "00000002")))
    refile(parts)
    doc = parts["word/document.xml"].decode()
    assert doc.count("<w:bookmarkStart") == 2
    assert doc.index("Acemoglu2020") < doc.index("Acemoglu, D.")
    assert doc.index("Acemoglu2020") < doc.index("Currie1999")


def test_refile_refuses_a_list_with_continuation_dashes():
    """"———. (2015)." files under the name above it; sorting scatters it."""
    parts = make_parts(reflist(entry(A, pid="00000001"),
                               entry("———. (2021). A Later Book. Oxford.",
                                     pid="00000002")))
    report = refile(parts)
    assert "continuation" in report.refused
    assert not report.moved


def test_refile_refuses_an_EMPTY_paragraph_inside_the_list():
    """A blank line pasted in with an entry. `_xml.PARA_RE` skips a
    self-closing `<w:p …/>`, so it is invisible to every text-layer
    check — and sorting around it drops it somewhere arbitrary."""
    blank = '<w:p w14:paraId="4321EAFC" w14:textId="77777777"/>'
    parts = make_parts(reflist(entry(A, pid="00000001"),
                               blank + entry(C, pid="00000002"),
                               entry(B, pid="00000003")))
    report = refile(parts)
    assert "empty paragraph" in report.refused
    assert not report.moved


def test_refile_refuses_a_stray_paragraph_inside_the_list():
    parts = make_parts(reflist(entry(C, pid="00000001"),
                               entry("A note that is not a reference entry "
                                     "at all.", pid="00000002"),
                               entry(A, pid="00000003")))
    report = refile(parts)
    # WHICH guard refused matters: the stray scan and the gap scan can
    # both reject this document, and only the stray scan reads
    # `entries[-1]` — so asserting the message is what makes
    # `entries[-1]` -> `entries[False]` a different answer.
    assert "sits inside the list and is not an entry" in report.refused
    assert not report.moved


def test_the_sort_key_files_a_single_author_entry_before_a_joint_one():
    """`(` sorts before `,`, which is what an author's own list does:
    "Scott, A. (2024)" before "Scott, A., Ellison, M. ... (2021)"."""
    solo = "Scott, A. (2024). The Longevity Imperative. Dublin: Murray."
    joint = ('Scott, A., Ellison, M., and D. Sinclair. (2021). "The Economic '
             'Value of Targeting Aging." Nature Aging.')
    parts = make_parts(reflist(entry(solo, pid="00000001"),
                               entry(joint, pid="00000002")))
    assert not refile(parts).moved


def test_diacritics_file_where_the_letter_files():
    parts = make_parts(reflist(entry("Mühlbach, N. (2021). A Paper. Journal.",
                                     pid="00000001"),
                               entry("Mz, Q. (2020). Another. Journal.",
                                     pid="00000002")))
    assert not refile(parts).moved


# ------------------------------------------- the inheritance resolver ---

def test_paragraph_property_walks_based_on_then_doc_defaults():
    xml = ('<w:styles><w:docDefaults><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="160"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
           '<w:name w:val="Normal"/></w:style>'
           '<w:style w:type="paragraph" w:styleId="Ref">'
           '<w:basedOn w:val="Normal"/><w:pPr>'
           '<w:ind w:left="720" w:hanging="720"/></w:pPr></w:style>'
           "</w:styles>")
    assert styles.paragraph_property(xml, "Ref", "ind", "hanging") == "720"
    assert styles.paragraph_property(xml, "Ref", "spacing", "after") == "160"
    assert styles.paragraph_property(xml, None, "ind", "hanging") is None
    assert styles.paragraph_property(None, "Ref", "ind", "hanging") is None


def test_a_value_is_inherited_from_the_PARENT_over_doc_defaults():
    """The chain has to be walked, not just started.

    The fixture above cannot see this: its `Normal` carries no `w:pPr`,
    so `Ref` -> `Normal` -> docDefaults and a mutation that breaks the
    middle step still arrives at the same 160 by the same route. Here
    the parent disagrees with the default, so only an actual walk
    answers 240 — which is the case the function exists for, since
    "would writing this be redundant?" is asked against what the
    paragraph really inherits.
    """
    xml = ('<w:styles><w:docDefaults><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="160"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
           '<w:pPr><w:spacing w:after="240"/></w:pPr></w:style>'
           '<w:style w:type="paragraph" w:styleId="Ref">'
           '<w:basedOn w:val="Normal"/><w:pPr>'
           '<w:ind w:hanging="720"/></w:pPr></w:style>'
           "</w:styles>")

    assert styles.paragraph_property(xml, "Ref", "spacing", "after") == "240"


def test_a_paragraph_naming_NO_style_inherits_the_default_ones():
    """`w:default="1"` names the style a paragraph without a `w:pStyle`
    is IN, and its properties are what such a paragraph inherits —
    docDefaults only after that. Asserted against a default style that
    DISAGREES with docDefaults, because agreeing proves nothing."""
    xml = ('<w:styles><w:docDefaults><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="160"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
           '<w:pPr><w:spacing w:after="240"/></w:pPr></w:style>'
           "</w:styles>")

    assert styles.paragraph_property(xml, None, "spacing", "after") == "240"


def test_a_paragraph_naming_a_style_the_STYLESHEET_LACKS_still_answers():
    """The case this module's own docstring is about: a document that
    references a style the part does not define, which Word renders in
    its defaults silently. `paragraph_property` has to answer what the
    paragraph really inherits — the defaults — rather than raise, since
    every caller is asking it in order to decide whether to write a
    value, and a crash there stops a formatting pass on the one
    manuscript that most needs one.
    """
    xml = ('<w:styles><w:docDefaults><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="160"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:styleId="Normal">'
           '<w:pPr><w:spacing w:after="240"/></w:pPr></w:style>'
           "</w:styles>")

    assert styles.paragraph_property(xml, "NoSuchStyle", "spacing",
                                     "after") == "160"


def test_doc_defaults_are_not_read_out_of_pprdefault_as_an_empty_blob():
    """`<w:pPrDefault>` starts with the same seven characters as `<w:pPr>`;
    without a word boundary the match runs to the INNER close tag."""
    xml = ('<w:styles><w:docDefaults><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="160"/></w:pPr></w:pPrDefault>'
           "</w:docDefaults></w:styles>")
    assert styles.paragraph_property(xml, None, "spacing", "after") == "160"


def test_house_layout_is_the_stated_rule():
    assert (HOUSE_LAYOUT.hanging, HOUSE_LAYOUT.before, HOUSE_LAYOUT.after,
            HOUSE_LAYOUT.page_break) == (720, 0, 80, True)


# --- what mutation analysis asked for, 2026-08-23 ---------------------


def test_refile_reports_the_entries_it_moved_by_name():
    """`report.moved` is what a log records; a count with no names is a
    claim nobody can check."""
    parts = make_parts(reflist(entry(C, pid="00000001"),
                               entry(A, pid="00000002"),
                               entry(B, pid="00000003")))
    report = refile(parts)
    assert len(report.moved) == 1
    assert report.moved[0].startswith("Currie, J. (1999).")


def test_layout_keeps_going_after_a_rule_the_style_already_states():
    """`continue`, not `break`: an entry can inherit the indent from its
    style and still need the spacing written. Breaking out of the rule
    loop at the first inherited value left the rest of the entry alone,
    and every fixture where the FIRST rule needed writing agreed."""
    styles_xml = ('<w:styles><w:style w:type="paragraph" w:styleId="Ref">'
                  '<w:pPr><w:ind w:left="720" w:hanging="720"/></w:pPr>'
                  "</w:style></w:styles>")
    styled = '<w:pPr><w:pStyle w:val="Ref"/></w:pPr>'
    parts = make_parts(reflist(entry(A, ppr=styled)),
                       extra={"word/styles.xml": styles_xml})
    report = layout(parts)

    assert not report.indented          # the style already says it
    assert len(report.spaced) == 1      # and the spacing still gets set
    assert 'w:after="80"' in parts["word/document.xml"].decode()


def test_an_indent_finding_and_a_spacing_finding_are_not_interchangeable():
    """The two codes route to different halves of the report and to
    different fixers; `tag == "ind"` inverted swapped them and a test
    asserting the SET of codes could not see it."""
    issues = entry_layout_issues(entry(A, ppr=""), None)
    codes = [(i.code, i.message.split(" is ")[0]) for i in issues]
    assert ("indent", "left indent") in codes
    assert ("indent", "hanging indent") in codes
    assert ("spacing", "space after") in codes
    assert not [c for c, _ in codes if c == "page-break"]


def test_the_layout_report_files_indents_and_spacings_apart():
    parts = make_parts(reflist(entry(A, ppr="")))
    report = layout(parts)
    assert all("indent" in line for line in report.indented)
    assert all("space after" in line for line in report.spaced)
    assert len(report.indented) == 2 and len(report.spaced) == 1


def test_the_page_break_looks_at_the_paragraph_ABOVE_the_first_entry():
    """`head - 1` and `head > 0`: the heading is found by counting back
    from the first entry, and an off-by-one there reads the wrong
    paragraph for the break that is already present."""
    body = (para(run("Body one."))
            + para(run("Body two."), '<w:r><w:br w:type="page"/></w:r>')
            + heading() + entry(A))
    parts = make_parts(body)
    assert not layout(parts).page_break

    # the same break one paragraph too high is NOT this heading's
    body = (para(run("Body one."), '<w:r><w:br w:type="page"/></w:r>')
            + para(run("Body two."))
            + heading() + entry(A))
    parts = make_parts(body)
    assert layout(parts).page_break



# --- what the layout report SAYS (mutation round, 2026-08-24) -----------
#
# Nothing called `LayoutReport.format()`, and 46 mutants lived in its six
# lines: the counts, the two optional clauses, the units, and the body.
# It is what a person reads after a layout pass, and the pass itself is
# well covered — which is the whole shape: the algorithm was tested and
# the sentence about it was not.

def _report(**kw):
    from docxkit.refstyle import LayoutReport
    return LayoutReport(**kw)


THREE = ["Acemoglu 2020", "Brown 2020", "Chen 2021"]
FIVE = [*THREE, "Dahl 2019", "Evans 2022"]
SEVEN = [*FIVE, "Foster 2013", "Garcia 2024"]


def test_a_report_that_set_NOTHING_still_states_both_counts():
    """Zero and zero. A renderer that dropped the head when there was
    nothing to list would be indistinguishable from a pass that did not
    run — the same argument the audit's "clean" line is there for."""
    assert _report().format() == "0 indent(s), 0 spacing(s) set"


def test_the_two_counts_are_the_two_LISTS_and_not_each_other():
    """3 indents and 5 spacings, which no arithmetic mutant can swap
    into the other or produce from the wrong list."""
    got = _report(indented=THREE, spaced=FIVE).format()

    assert got.splitlines()[0] == "3 indent(s), 5 spacing(s) set"
    assert [ln for ln in got.splitlines() if ln.startswith("  indent")] == [
        f"  indent   {name}" for name in THREE]
    assert [ln for ln in got.splitlines() if ln.startswith("  spacing")] == [
        f"  spacing  {name}" for name in FIVE]


def test_the_page_break_clause_appears_only_when_one_was_added():
    """It is a fact about the list, not a count, so it reads as a phrase
    — and a reader who sees it on a pass that added none would go
    looking for a page break nobody inserted."""
    assert ", page break added" in _report(page_break="Ref").format()
    assert "page break" not in _report(indented=THREE).format()


def test_the_INHERITED_clause_names_what_was_deliberately_left_alone():
    """Entries whose style already states the house value: writing it on
    the paragraph would be deleted by Word on its next save, so they are
    counted and left. Silence would read as "the pass missed seven"."""
    got = _report(indented=THREE, inherited=SEVEN).format()

    assert got.splitlines()[0] == (
        "3 indent(s), 0 spacing(s) set, 7 left to the style")
    assert not [ln for ln in got.splitlines() if "Foster" in ln], \
        "counted, not listed — they are the ones nothing was done to"


def test_the_whole_head_reads_as_one_sentence_in_order():
    """All four parts at once, because the clauses are assembled by
    concatenation and the order is what makes it a sentence."""
    got = _report(indented=THREE, spaced=FIVE, page_break="Ref",
                  inherited=SEVEN).format()

    assert got.splitlines()[0] == (
        "3 indent(s), 5 spacing(s) set, page break added, "
        "7 left to the style")


def test_a_report_is_TRUTHY_only_when_it_changed_something():
    """`inherited` alone is a pass that deliberately did nothing, and a
    caller printing on truthiness must not announce it."""
    assert not _report()
    assert not _report(inherited=SEVEN)
    assert _report(indented=THREE)
    assert _report(spaced=FIVE)
    assert _report(page_break="Ref")



# --- what `refile` says when it REFUSES (mutation round, 2026-08-24) -----

def _list_with(*paragraphs: str) -> dict[str, bytes]:
    """A body whose reference list starts at a known paragraph index."""
    return make_parts("".join(paragraphs))


ENTRY_A = 'Acemoglu, D. (2020). "Robots." Journal, 1(1), 1-20.'
ENTRY_B = 'Brown, A. (2019). "A Title." Journal, 2(2), 30-40.'
ENTRY_C = 'Chen, L. (2021). "Another." Journal, 3(3), 50-60.'


def test_a_STRAY_paragraph_inside_the_list_is_named_by_its_own_number():
    """The refusal is the whole output when `refile` declines, and it
    sends a person to one paragraph out of a list of forty. Off by one
    and they are looking at the entry above the problem, which reads
    correctly — so the wrong number does not look like a wrong number.

    The stray is at index 5, printing as 6: a value `5 + 1` produces and
    `5 % 1`, `5 & 1`, `5 * 1` and `5 >> 1` do not."""
    parts = _list_with(
        para(run("Body one.")), para(run("Body two.")),
        para(run("Body three.")), para(run("References")),
        para(run(ENTRY_A)),
        para(run("A stray note nobody meant to leave here.")),
        para(run(ENTRY_B)))

    report = refile(parts)

    assert not report.moved
    assert report.refused.startswith("\u00b66 sits inside the list"), \
        report.refused
    assert "A stray note nobody meant" in report.refused


def test_the_stray_is_QUOTED_so_the_author_can_see_which_one():
    """A number alone makes them count paragraphs. The text is
    truncated, because a stray can be a whole pasted paragraph and a
    refusal that prints it is a refusal nobody reads."""
    long_stray = "This stray is far longer than forty characters and runs on."
    parts = _list_with(
        para(run("Body one.")), para(run("References")),
        para(run(ENTRY_A)), para(run(long_stray)), para(run(ENTRY_B)))

    report = refile(parts)

    assert repr(long_stray[:40]) in report.refused, report.refused
    assert long_stray[:41] not in report.refused, "truncated at 40"


def test_an_EMPTY_paragraph_above_an_entry_gets_its_own_sentence():
    """`_xml.PARA_RE` skips a self-closing `<w:p/>` on purpose, so a
    blank line pasted into a reference list is invisible to every
    text-layer check and turns up only here. It names the entry BELOW
    the blank, which is the one that would move."""
    parts = _list_with(
        para(run("Body one.")), para(run("Body two.")),
        para(run("References")),
        para(run(ENTRY_A)), "<w:p/>", para(run(ENTRY_B)),
        para(run(ENTRY_C)))

    report = refile(parts)

    assert not report.moved
    assert report.refused.startswith(
        "an empty paragraph sits above \u00b65"), report.refused
    assert "delete it first" in report.refused



# --- WHERE a finding points, and what it quotes (2026-08-24) -------------

#: Long enough that a 60-character truncation is observable. A real
#: reference entry always is; a fixture built from a short one pins
#: nothing about the width.
LONG_A = ('Acemoglu, D., and P. Restrepo. (2020). "Robots and Jobs: '
          'Evidence from US Labor Markets." Journal of Political Economy.')


def _deep_list(*entries: str) -> dict[str, bytes]:
    """Four body paragraphs, then the heading at index 4."""
    body = "".join(para(run(f"Body paragraph {n}.")) for n in range(4))
    return make_parts(body + heading() + "".join(entries))


def test_the_page_break_finding_points_at_the_HEADING_paragraph():
    """`¶5`, and the whole value of the finding is that number: the
    house rule is that the list starts on a new page, and the paragraph
    to put the break on is the heading, not the first entry."""
    report = audit(_deep_list(entry(LONG_A, ppr=""), entry(B, ppr="")))

    (issue,) = [i for i in report.issues if i.code == "page-break"]

    assert issue.where == "\u00b65", issue
    assert issue.snippet.startswith("References")


def test_an_ENTRY_finding_points_at_its_OWN_paragraph_and_quotes_it():
    """Each entry answers for itself. A finding that named the list's
    first entry for all of them would send an author to fix a paragraph
    that is already right, forty times."""
    report = audit(_deep_list(entry(LONG_A, ppr=""), entry(B, ppr="")))

    # The CODES this line produces, not "any issue at that paragraph".
    # `italics` and `uncited-ref` are stamped somewhere else entirely and
    # land on the same paragraphs, so asking only for \u00b66 passed whatever
    # the layout finding did with its number \u2014 measured: the mutant that
    # points every entry finding at \u00b61 survived the first version.
    layout_codes = ("indent", "spacing")
    first = [i for i in report.issues
             if i.where == "\u00b66" and i.code in layout_codes]
    second = [i for i in report.issues
              if i.where == "\u00b67" and i.code in layout_codes]

    assert first and second, [(i.code, i.where) for i in report.issues]
    assert all(i.snippet == LONG_A[:60] for i in first), first[0].snippet
    assert len(first[0].snippet) == 60, "truncated, and at 60"


def test_LAYOUT_reports_the_paragraph_it_put_the_break_on():
    """The repair's own record, read by whoever checks what it did. It
    quotes 40 characters where the audit quotes 60, and both numbers are
    load-bearing for a reader scanning a list of changes."""
    parts = _deep_list(entry(LONG_A, ppr=""), entry(B, ppr=""))

    report = layout(parts)

    assert report.page_break.startswith("\u00b65: References"), \
        report.page_break



def test_the_lines_layout_writes_name_the_rule_the_entry_and_BOTH_values():
    """What a person reads to check a pass, one line per rule per entry.

    The renderer was tested with lists handed to it; this is the code
    that BUILDS them, and every part of the line was free: which
    paragraph, which rule, what it was, what it became. `- -> 720` is
    the shape for a value nothing stated, and the dash matters — `0 ->
    720` would say the entry declared a zero indent, which is a
    different document.
    """
    parts = _deep_list(entry(LONG_A, ppr=""), entry(B, ppr=""))

    report = layout(parts)

    assert report.indented == [
        "\u00b66: left indent - -> 720", "\u00b66: hanging indent - -> 720",
        "\u00b67: left indent - -> 720", "\u00b67: hanging indent - -> 720"]
    assert report.spaced == ["\u00b66: space after - -> 80",
                             "\u00b67: space after - -> 80"]
    # `space before` is 0 in the house spec and 0 by default, so there is
    # nothing to write and nothing a style provided: neither a change nor
    # an inheritance.
    assert report.inherited == []


def test_an_OLD_VALUE_is_quoted_as_itself_not_as_a_dash():
    """The dash means "nothing stated it". An entry that states 360 has
    to say 360, because "the entry sets a quarter-inch indent" and "the
    entry sets nothing" are different problems with different fixes."""
    quarter = '<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr>'
    parts = _deep_list(entry(LONG_A, ppr=quarter))

    report = layout(parts)

    assert "\u00b66: left indent 360 -> 720" in report.indented
    assert "\u00b66: hanging indent 360 -> 720" in report.indented


def test_a_value_the_STYLE_provides_is_counted_and_left_alone():
    """The `inherited` list, which was fed by nothing until 2026-08-24:
    its condition sat one branch below the `continue` that already
    caught every case it asked for, so `LayoutReport.inherited`, its
    docstring and the ", N left to the style" clause were all live and
    unreachable.

    Word deletes a paragraph declaration equal to the inherited value on
    its next save, so writing one makes an audit that can never come
    back clean. Counting it says the pass SAW the entry."""
    styles_xml = (
        '<w:styles><w:style w:type="paragraph" w:styleId="Ref">'
        '<w:pPr><w:spacing w:before="0" w:after="80"/>'
        '<w:ind w:left="720" w:hanging="720"/></w:pPr></w:style></w:styles>')
    styled = '<w:pPr><w:pStyle w:val="Ref"/></w:pPr>'
    body = "".join(para(run(f"Body paragraph {n}.")) for n in range(4))
    parts = make_parts(body + heading() + entry(LONG_A, ppr=styled),
                       extra={"word/styles.xml": styles_xml})

    report = layout(parts)

    assert report.inherited == [
        "\u00b66: left indent", "\u00b66: hanging indent",
        "\u00b66: space before", "\u00b66: space after"]
    assert not report.indented and not report.spaced, "nothing was written"
    assert "4 left to the style" in report.format()



def test_something_that_is_NOT_a_bookmark_between_entries_is_QUOTED():
    """`refile` moves whole spans, so whatever sits between two entries
    moves with one of them. Bookmarks are safe — they belong to the
    entry either way — and anything else is a decision the tool will not
    make silently.

    The refusal has to quote what it found: "not a bookmark" sends an
    author looking at XML they cannot see in Word, and a comment anchor
    stranded by an accepted revision looks like nothing at all on the
    page. Truncated at 60, because the gap can be an entire tracked
    deletion."""
    stranded = ('<w:proofErr w:type="spellStart"/>'
                '<w:commentRangeEnd w:id="1"/>'
                '<w:proofErr w:type="spellEnd"/>')
    body = "".join(para(run(f"Body paragraph {n}.")) for n in range(4))
    parts = make_parts(body + heading() + entry(LONG_A)
                       + stranded + entry(B))

    report = refile(parts)

    assert not report.moved
    assert report.refused.startswith("\u00b67 has "), report.refused
    assert repr(stranded[:60]) in report.refused
    assert report.refused.endswith("which is not a bookmark")


def test_a_BOOKMARK_between_two_entries_is_not_a_refusal():
    """The half that must NOT refuse. A citation's anchor sits exactly
    there, on every paper this tool is for, so a rule that called it an
    obstruction would refuse every real reference list."""
    marks = ('<w:bookmarkStart w:id="7" w:name="ref_Barr2010"/>'
             '<w:bookmarkEnd w:id="7"/>')
    body = "".join(para(run(f"Body paragraph {n}.")) for n in range(4))
    parts = make_parts(body + heading() + entry(C, pid="00000001")
                       + marks + entry(A, pid="00000002"))

    report = refile(parts)

    assert not report.refused, report.refused
    assert report.moved, "Currie after Acemoglu: it had work to do"



# --- what the refile report SAYS (mutation round, 2026-08-24) -----------

def _refile_report(**kw):
    from docxkit.refstyle import RefileReport
    return RefileReport(**kw)


def test_a_refusal_is_the_whole_report_and_says_so_first():
    """A refused pass moved nothing, so the counts would all be zero and
    a reader would take it for a clean list. The word REFUSED is what
    separates "nothing to do" from "I would not touch this"."""
    got = _refile_report(refused="\u00b64 sits inside the list").format()

    assert got == "REFUSED: \u00b64 sits inside the list"


def test_a_list_already_filed_says_so_rather_than_printing_nothing():
    """Silence is indistinguishable from a command that failed to run —
    the same argument the audit's "clean" line is there for."""
    assert _refile_report().format() == "the list is already alphabetical"


def test_the_report_counts_the_entries_and_then_names_them():
    """The count first, because it is what a reader checks against the
    number of entries they expected to move."""
    got = _refile_report(moved=["Currie, J. (1999).", "Barr, N. (2010)."])

    assert got.format().splitlines() == [
        "2 entr(ies) re-filed",
        "  Currie, J. (1999).",
        "  Barr, N. (2010)."]


def test_the_DISPLACED_entries_are_not_named_either_way_round():
    """`test_refile_reports_the_entries_it_moved_by_name` covers a first
    entry that belongs last. This is the other direction — a LAST entry
    that belongs in the middle — because the rule is about which entry
    is misfiled, not about where in the list it sits, and one ordering
    cannot tell those apart.

    Sorting moves most of the list: an entry out of place displaces
    every entry between its old and new position. Naming all of them
    buries the one an author has to look at."""
    last_middle = _deep_list(entry(A, pid="00000001"), entry(C, pid="2"),
                             entry(B, pid="3"))

    moved = refile(last_middle).moved

    assert len(moved) == 1, moved
    assert moved[0].startswith("Barr"), moved
    assert len(moved[0]) == 60, "the entry text is quoted, truncated at 60"



def test_a_list_that_IS_the_top_of_the_document_needs_no_page_break():
    """There is nothing above it to break from. A finding here would ask
    an author to insert a page break before the first line of the file.

    The guard that gets this right also stops the lookup running off the
    front: `matches[head - 1]` with `head == 0` is `matches[-1]`, the
    LAST paragraph of the document, so a version without it answers "does
    the list start a page?" by looking at how the paper ENDS — and a
    manuscript that happens to close with a section break would report
    a clean list."""
    parts = make_parts(heading() + entry(A) + entry(B))

    report = audit(parts)
    repaired = layout(make_parts(heading() + entry(A) + entry(B)))

    assert "page-break" not in codes(report), codes(report)
    assert not repaired.page_break


def test_the_AUDIT_reads_the_paragraph_above_the_heading_too():
    """`layout` has a test for a break above the heading; the audit's
    own copy of that lookup did not, so it could read the paragraph
    BELOW instead — the first entry — and report a page break needed on
    a list that already starts one. The two must agree, because the
    audit is what says whether the repair has anything to do."""
    body = (para(run("Body."), '<w:r><w:br w:type="page"/></w:r>')
            + heading() + entry(A) + entry(B))

    assert "page-break" not in codes(audit(make_parts(body)))


def test_a_list_at_the_top_is_not_rescued_by_a_break_at_the_BOTTOM():
    """The same guard, asked the way that separates it from `head >= 0`
    rather than from nothing. The document ends with a section break —
    which IS one of the things `_starts_a_page` accepts — so a lookup
    that wrapped to the end would find it and call the list correctly
    placed for the wrong reason."""
    tail = para(run("Appendix."), "<w:pPr><w:sectPr><w:type "
                                  'w:val="nextPage"/></w:sectPr></w:pPr>')
    parts = make_parts(heading() + entry(A) + entry(B) + tail)

    assert "page-break" not in codes(audit(parts)), "still the first line"


@pytest.mark.parametrize("pad", [0, 1])
def test_a_stray_ABOVE_THE_LAST_ENTRY_is_caught_wherever_the_list_starts(pad):
    """The scanned span is `range(lo, hi + 1)`, and `hi` is the last
    entry's own index — which is always in `listed`, so the `+ 1` says
    "the closed span of the list" and nothing depends on it. What DOES
    depend on the arithmetic is the far end: a span computed as `hi ^ 1`
    is `hi + 1` when `hi` is even and `hi - 1` when it is odd, and the
    odd case stops one paragraph short — exactly the paragraph a stray
    directly above the last entry sits in.

    The case was already covered, and covered at one parity: a body of
    three paragraphs put the last entry at an even index, where that
    arithmetic happens to agree. One paragraph either way is not a
    property of the manuscript, so the test should not have an opinion
    about it."""
    body = [para(run(f"Body {i}.")) for i in range(3 + pad)]
    parts = _list_with(*body, para(run("References")),
                       para(run(ENTRY_A)),
                       para(run("A stray note nobody meant to leave here.")),
                       para(run(ENTRY_B)))

    report = refile(parts)

    assert not report.moved
    assert "sits inside the list and is not an entry" in (report.refused or "")
    assert "A stray note nobody meant" in report.refused


def test_refiling_the_list_leaves_EVERYTHING_ABOVE_IT_untouched():
    """The rewrite is `doc[:start] + sorted entries + doc[at:]`, and
    `start` is the end of the paragraph before the first entry. Get that
    index wrong and the splice does not misplace anything — it DELETES
    whatever sits between the wrong start and the list: the "References"
    heading, or the last paragraph of the paper.

    Nothing held it. The fixtures put the list two paragraphs in, where
    `lo - 1`, `lo >> 1` and `lo & 1` all land on the same paragraph and
    every wrong index reads as right. Three body paragraphs and a
    heading separate them, which is also what a manuscript looks like.
    """
    body = [para(run("Intro one.")), para(run("Intro two.")),
            para(run("Intro three.")), para(run("References"))]
    parts = _list_with(*body, para(run(ENTRY_C)), para(run(ENTRY_A)),
                       para(run(ENTRY_B)))

    report = refile(parts)

    assert report.moved == [ENTRY_C]
    doc = parts["word/document.xml"].decode("utf-8")
    got = [visible_text(m.group(0)) for m in PARA_RE.finditer(doc)]
    assert got == ["Intro one.", "Intro two.", "Intro three.", "References",
                   ENTRY_A, ENTRY_B, ENTRY_C]


# `head` is `min(entry index) - 1` — the paragraph the heading sits in.
# It cannot go negative: `references` finds no list at all without a
# heading above it, so the first entry is never paragraph 0. Every
# fixture here also put exactly ONE body paragraph above the heading,
# which pinned `head` at 1 — where `head - 1`, `head >> 1`, `head ^ 1`
# and `head % 1` all land on paragraph 0 and cannot be told apart.

def test_paragraphs_that_LOOK_like_entries_are_not_a_list_without_a_heading():
    """Two house-formatted entries and nothing above them. `references`
    wants a heading, so this is body text that happens to be shaped like
    a bibliography — a paper whose opening quotes a reference, say — and
    the layout rules have no list to act on.

    Written first as a test of the page rule's lower bound, which it is
    not: with no entries there is no `head` to bound. `kill_check` said
    so by killing nothing, and the claim is recorded in
    tools/equivalents.toml instead."""
    parts = make_parts(entry(A) + entry(B, pid="22222222"))
    before = parts["word/document.xml"]

    report = layout(parts)

    assert not report.page_break
    assert not report.indented and not report.spaced
    assert parts["word/document.xml"] == before


def test_the_AUDIT_reads_the_paragraph_DIRECTLY_above_the_heading():
    """Four body paragraphs, and the break on the fourth. `head` is 4,
    so `head - 1` is 3 while `head >> 1` is 2, `head ^ 1` is 5 and
    `head % 1` is 0 — four different paragraphs. At `head == 1`, which
    is all this file used to have, they are one paragraph and the
    arithmetic is unfalsifiable. Three is not enough either: `3 ^ 1` is
    2, which is `head - 1` again.

    Reading the wrong paragraph finds no break and reports a list that
    DOES start on a new page as though it did not."""
    body = (para(run("Body one.")) + para(run("Body two."))
            + para(run("Body three."))
            + para(run("Body four."), '<w:r><w:br w:type="page"/></w:r>')
            + heading() + entry(A))

    report = audit(make_parts(body))

    assert not [i for i in report.issues if i.code == "page-break"], \
        [i.where for i in report.issues if i.code == "page-break"]


def test_the_REPAIR_reads_the_paragraph_directly_above_the_heading_too():
    """`audit` and `layout` carry the same rule twice, and the pair is
    the thing that goes wrong: a paper told about a defect no fixer
    removes, or one silently fixed the audit never mentioned. So the
    fixer gets the same four paragraphs."""
    body = (para(run("Body one.")) + para(run("Body two."))
            + para(run("Body three."))
            + para(run("Body four."), '<w:r><w:br w:type="page"/></w:r>')
            + heading() + entry(A))
    parts = make_parts(body)

    report = layout(parts)

    assert not report.page_break
    assert "<w:pageBreakBefore/>" not in parts["word/document.xml"].decode()


def test_neither_side_reports_a_page_when_the_HEADING_OPENS_the_document():
    """`head` is 0: no paragraph above to carry a break, and a first
    paragraph already starts one. Both halves have to agree about that,
    and `_starts_a_page` is where they do — its "first paragraph" answer
    is the only thing keeping the rule quiet here."""
    parts = make_parts(heading() + entry(A) + entry(B, pid="22222222"))
    doc_before = parts["word/document.xml"]

    assert not [i for i in audit(parts).issues if i.code == "page-break"]
    assert not layout(parts).page_break
    assert parts["word/document.xml"] == doc_before
