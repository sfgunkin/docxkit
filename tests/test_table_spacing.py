"""The house rule: text that RESUMES after a table gets space above it.

A table ends in a rule and the next paragraph starts hard against it. What
makes the rule more than a one-liner is what it must NOT touch: the note
belongs to the table and stays tight, a heading already carries a larger
gap of its own, and a numbered display equation is a table only to the
schema.
"""
from __future__ import annotations

import re

from conftest import NS, para, run

from docxkit._xml import visible_text
from docxkit.hygiene import table_spacing


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def table(*cells: str) -> str:
    tcs = "".join(f"<w:tc><w:tcPr/>{para(run(c))}</w:tc>" for c in cells)
    return f"<w:tbl><w:tblPr/><w:tr>{tcs}</w:tr></w:tbl>"


def before_of(xml: str, text: str) -> str | None:
    for m in re.finditer(r"<w:p\b.*?</w:p>", xml, re.DOTALL):
        if visible_text(m.group(0)).strip().startswith(text):
            sp = re.search(r'<w:spacing\b[^>]*w:before="(\d+)"', m.group(0))
            return sp.group(1) if sp else None
    raise AssertionError(f"no paragraph starts {text!r}")


def test_the_paragraph_after_a_table_gets_the_space():
    xml = doc(table("Region", "Value") + para(run("The table shows.")))
    out, report = table_spacing(xml)
    assert before_of(out, "The table shows") == "120"
    assert report.spaced == ["The table shows."]


def test_a_note_stays_tight_and_the_text_after_it_gets_the_space():
    """The note belongs to the table above it. The rule is about the text
    that RESUMES, which is the paragraph after the note."""
    xml = doc(table("Region") + para(run("Примечание. D — база."))
              + para(run("Ранжирование чувствительно.")))
    out, report = table_spacing(xml)
    assert before_of(out, "Примечание") is None       # left to inherit
    assert before_of(out, "Ранжирование") == "120"
    assert not report.notes
    assert report.spaced == ["Ранжирование чувствительно."]


def test_a_note_that_inherits_is_left_alone():
    """Writing an explicit 0 over an inherited 0 is a change Word DELETES
    on its next save — it did, on all eleven of DSI's notes, and the audit
    then reported the same eleven every run. A rule that cannot survive a
    save is not a rule."""
    xml = doc(table("Region") + para(run("Примечание. D — база.")))
    out, report = table_spacing(xml)
    assert out == xml and not report.notes


def test_a_note_that_declares_the_wrong_space_is_corrected():
    p = ('<w:p><w:pPr><w:spacing w:before="120" w:after="0"/></w:pPr>'
         f'{run("Примечание. D — база.")}</w:p>')
    out, report = table_spacing(doc(table("Region") + p))
    assert before_of(out, "Примечание") == "0"
    assert report.notes == ["Примечание. D — база."]
    assert 'w:after="0"' in out


def test_a_second_note_line_is_also_skipped():
    """«*» opens a note's continuation — Table 4's self-employment caveat."""
    xml = doc(table("Indicator") + para(run("Примечание. Ориентация."))
              + para(run("* Высокая доля занятости.")) + para(run("Prose.")))
    out, _ = table_spacing(xml)
    assert before_of(out, "*") is None
    assert before_of(out, "Prose") == "120"


def test_a_heading_keeps_its_own_spacing():
    """Heading2 carries 14pt before in these papers; 6pt would SHRINK the
    gap, which is the opposite of what the rule is for."""
    head = ('<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
            f'{run("6.2. Анализ")}</w:p>')
    xml = doc(table("Region") + head)
    out, report = table_spacing(xml)
    assert before_of(out, "6.2.") is None
    assert not report.spaced
    assert any("heading" in s for s in report.skipped)


def test_an_equation_carrier_is_not_a_table():
    """A numbered display equation is a 1x2 table whose second cell is «(N)»,
    and the «where …» after it continues the equation's own sentence."""
    carrier = table("DRI = ...", "(3)")
    xml = doc(carrier + para(run("где k — компонент.")))
    out, report = table_spacing(xml)
    assert before_of(out, "где") is None
    assert any("carrier" in s for s in report.skipped)


def test_an_existing_wrong_value_is_corrected():
    """Table 3's paragraph carried 80 — 4pt, close enough to look right and
    wrong enough to be inconsistent."""
    p = ('<w:p><w:pPr><w:spacing w:before="80" w:after="40"/>'
         '<w:jc w:val="both"/></w:pPr>'
         f'{run("Since the decompositions")}</w:p>')
    out, _ = table_spacing(doc(table("Level") + p))
    assert before_of(out, "Since") == "120"
    assert 'w:after="40"' in out            # the other side is left alone
    assert 'w:jc w:val="both"' in out


def test_an_empty_paragraph_is_stepped_over_not_spaced():
    """A landscape page is made by putting a sectPr in an empty paragraph
    right after the table. That paragraph is not the text that resumes, and
    spacing it moves nothing a reader sees — DSI's landscape catalogue page
    is exactly this shape."""
    spacer = ('<w:p><w:pPr><w:sectPr><w:pgSz w:w="16838" w:h="11906" '
              'w:orient="landscape"/></w:sectPr></w:pPr></w:p>')
    xml = doc(table("Region") + spacer + para(run("Prose resumes.")))
    out, report = table_spacing(xml)
    assert before_of(out, "Prose resumes") == "120"
    assert report.spaced == ["Prose resumes."]
    assert 'w:orient="landscape"' in out
    assert '<w:spacing' not in out.split(spacer[:20])[1].split("</w:p>")[0]


def test_it_is_idempotent_so_a_second_run_is_an_audit():
    xml = doc(table("Region") + para(run("Prose.")))
    once, first = table_spacing(xml)
    twice, second = table_spacing(once)
    assert twice == once
    assert first.spaced and not second.spaced and not second.notes


def test_the_audit_survives_a_word_save_that_drops_redundant_zeros():
    """The round trip that broke it: Word strips `w:before="0"` when 0 is
    what the paragraph would inherit, so a pass that writes those zeros
    reports the same notes for ever. Simulated by deleting them."""
    xml = doc(table("Region") + para(run("Примечание. D — база."))
              + para(run("Ранжирование чувствительно.")))
    once, _ = table_spacing(xml)
    saved = re.sub(r'\s*w:before="0"', "", once)     # what Word gives back
    again, report = table_spacing(saved)
    assert again == saved
    assert not report.notes and not report.spaced


def test_the_paragraph_keeps_its_text_and_the_document_still_parses():
    import xml.etree.ElementTree as ET
    xml = doc(table("Region") + para(run("Prose about it.")))
    out, _ = table_spacing(xml)
    ET.fromstring(out)
    assert visible_text(out).count("Prose about it.") == 1


# --- what the first mutation run found (2026-08-17, hygiene 21.2 %) -----
#
# 51 of the 116 survivors were in `_set_before`, and all of them on the
# branch that INSERTS a `w:spacing` into an existing `w:pPr` — where in
# the pPr it goes. The tests reached the two easy shapes (a spacing
# element already there, no pPr at all) and never that one. Word reads
# CT_PPr as an ordered sequence: an element out of place is dropped on
# the next save, so the spacing silently stops applying, weeks later,
# with nothing in any diff.

def _spaced(ppr: str) -> str:
    """The pPr of the paragraph after a table, once the rule has run."""
    body = (table("cell") + f"<w:p>{ppr}<w:r><w:t>resumes</w:t></w:r></w:p>")
    out, _report = table_spacing(doc(body))
    para_xml = re.findall(r"<w:p\b(?![^>]*/>).*?</w:p>", out, re.DOTALL)[-1]
    return re.search(r"<w:pPr>.*?</w:pPr>", para_xml, re.DOTALL).group(0)


def test_the_spacing_goes_BEFORE_jc_and_after_pStyle():
    """CT_PPr fixes the order: pStyle, then spacing, then ind / jc, then
    rPr last."""
    got = _spaced('<w:pPr><w:pStyle w:val="Body"/><w:jc w:val="both"/>'
                  "</w:pPr>")

    assert got == ('<w:pPr><w:pStyle w:val="Body"/>'
                   '<w:spacing w:before="120"/><w:jc w:val="both"/></w:pPr>')


def test_the_spacing_goes_BEFORE_ind():
    got = _spaced('<w:pPr><w:ind w:left="720"/></w:pPr>')

    assert got == ('<w:pPr><w:spacing w:before="120"/>'
                   '<w:ind w:left="720"/></w:pPr>')


def test_the_spacing_goes_BEFORE_rPr():
    """rPr is the LAST child of a pPr, so everything else precedes it —
    including a spacing inserted here."""
    got = _spaced("<w:pPr><w:rPr><w:b/></w:rPr></w:pPr>")

    assert got == ('<w:pPr><w:spacing w:before="120"/>'
                   "<w:rPr><w:b/></w:rPr></w:pPr>")


def test_with_nothing_to_precede_the_spacing_goes_LAST():
    """A pPr holding only a pStyle: there is no anchor element, so the
    spacing goes at the end — which is still after pStyle, and still in
    order."""
    got = _spaced('<w:pPr><w:pStyle w:val="Body"/></w:pPr>')

    assert got == ('<w:pPr><w:pStyle w:val="Body"/>'
                   '<w:spacing w:before="120"/></w:pPr>')


def test_an_EMPTY_pPr_gets_the_spacing_and_nothing_else():
    got = _spaced("<w:pPr></w:pPr>")

    assert got == '<w:pPr><w:spacing w:before="120"/></w:pPr>'


def test_a_paragraph_with_NO_pPr_gets_one_holding_the_spacing():
    body = table("cell") + "<w:p><w:r><w:t>resumes</w:t></w:r></w:p>"

    out, _report = table_spacing(doc(body))

    assert '<w:p><w:pPr><w:spacing w:before="120"/></w:pPr>' in out


def test_an_existing_spacing_KEEPS_its_other_attributes():
    """`w:after` belongs to the paragraph and this rule is about
    `w:before`; rewriting the element wholesale would drop it."""
    got = _spaced('<w:pPr><w:spacing w:after="240" w:line="276"/></w:pPr>')

    assert 'w:after="240"' in got and 'w:line="276"' in got
    assert 'w:before="120"' in got


def test_a_table_BEFORE_an_equation_carrier_is_still_spaced():
    """`continue`, not `break`: the walk goes over the tables in reverse,
    so stopping at a carrier leaves every table EARLIER in the document
    unspaced — and a paper's carriers are in the middle of the methods,
    with its results tables after them."""
    body = (table("Level") + para(run("Text after the real table."))
            + table("DRI = ...", "(3)") + para(run("где k — компонент.")))

    out, report = table_spacing(doc(body))

    assert before_of(out, "Text after") == "120"
    assert any("carrier" in s for s in report.skipped)


def test_a_TWO_ROW_table_is_a_table_however_its_last_cell_reads():
    """One row, two cells: a results table whose final cell happens to
    hold «(3)» is not an equation, and skipping it would leave the text
    under it hard against the rule."""
    body = ("<w:tbl><w:tblPr/>"
            f"<w:tr><w:tc><w:tcPr/>{para(run('Coefficient'))}</w:tc>"
            f"<w:tc><w:tcPr/>{para(run('(1)'))}</w:tc></w:tr>"
            f"<w:tr><w:tc><w:tcPr/>{para(run('0.15'))}</w:tc>"
            f"<w:tc><w:tcPr/>{para(run('(3)'))}</w:tc></w:tr></w:tbl>"
            + para(run("The text below it.")))

    out, report = table_spacing(doc(body))

    assert before_of(out, "The text below") == "120"
    assert report.skipped == []


def test_a_ONE_ROW_table_of_THREE_cells_is_a_table():
    """Two cells exactly. The number sits in the LAST one here too, so
    the count is what decides — a three-column layout row is not an
    equation however its last cell reads."""
    body = (table("DRI = ...", "note", "(3)") + para(run("Text below.")))

    out, _report = table_spacing(doc(body))

    assert before_of(out, "Text below") == "120"


def test_a_final_cell_that_is_not_a_NUMBER_in_brackets_is_a_table():
    """«(3)», «(A.1)» — a label, not a sentence. A 1x2 table whose second
    cell reads «(see the appendix)» is a layout table."""
    body = (table("Some text", "(see the appendix)")
            + para(run("Text below.")))

    out, _report = table_spacing(doc(body))

    assert before_of(out, "Text below") == "120"


def test_a_final_cell_that_MERELY_CONTAINS_a_number_is_a_table():
    """The whole cell is the label, not a cell with one in it: matched
    loosely, a results row ending «(3) see notes» reads as an equation
    and the text under the table stays hard against the rule."""
    body = table("Some text", "(3) see notes") + para(run("Text below."))

    out, report = table_spacing(doc(body))

    assert before_of(out, "Text below") == "120"
    assert report.skipped == []


def test_the_number_is_read_from_the_LAST_cell_not_the_first():
    """A carrier is «equation ... (3)», in that order. Reading the first
    cell makes every equation a table and the «where …» after it gets a
    gap in the middle of its own sentence."""
    body = table("(3)", "AFI = ...") + para(run("Text below."))

    out, _report = table_spacing(doc(body))

    assert before_of(out, "Text below") == "120"


def test_a_LETTERED_equation_number_is_still_a_carrier():
    """Appendix equations are «(A.1)», and the pattern takes word
    characters and dots for that reason."""
    body = table("AFI = ...", "(A.1)") + para(run("where the weights"))

    out, report = table_spacing(doc(body))

    assert before_of(out, "where the weights") is None
    assert any("carrier" in s for s in report.skipped)
