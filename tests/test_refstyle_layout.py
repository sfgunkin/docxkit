"""Where the reference LIST sits, as opposed to how an entry reads.

Two house rules that drift on ordinary author rounds — the list starts on
a new page, and every entry is set with a 0.5" hanging indent, no space
before and 4 pt after — plus the alphabetical order, which `audit` could
report and nothing could repair until :func:`refstyle.refile`.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit import styles
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
