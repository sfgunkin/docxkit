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
from docxkit.hygiene import (
    _is_equation_carrier,
    _set_before,
    restore_math_glyphs,
    restore_parts,
    table_spacing,
)


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
    ppr_out = re.search(r"<w:pPr>.*?</w:pPr>", para_xml, re.DOTALL)
    assert ppr_out, "the rule left the paragraph with no pPr at all"
    return ppr_out.group(0)


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


# --- what the spacing report SAYS (2026-08-19) --------------------------
#
# The behaviour above is pinned by reading the XML back; the report is
# what a person reads, and none of it was asserted by value. `table_
# spacing` is run over a manuscript and its three lists are the record
# of what happened to forty tables — a truncation at the wrong length or
# a skip line naming the wrong equation is a record that has to be
# checked against the document it describes, which is the work it exists
# to save.


def test_the_report_names_the_paragraph_it_spaced_up_to_48_characters():
    """Long enough to identify the paragraph, short enough that forty of
    them read as a list."""
    resumes = ("The decomposition in this section is sensitive to the "
               "ranking of the components.")
    xml = doc(table("Region", "Value") + para(run(resumes)))

    _out, report = table_spacing(xml)

    assert report.spaced == [
        "The decomposition in this section is sensitive t"]
    assert len(report.spaced[0]) == 48


def test_the_report_names_the_NOTE_it_corrected_the_same_way():
    long_note = ("Примечание. D — база сравнения, а остальные компоненты "
                 "нормированы по ней.")
    p = ('<w:p><w:pPr><w:spacing w:before="120"/></w:pPr>'
         f"{run(long_note)}</w:p>")

    _out, report = table_spacing(doc(table("Region") + p))

    assert report.notes == ["Примечание. D — база сравнения, а остальные комп"]
    assert len(report.notes[0]) == 48


def test_a_skipped_carrier_is_named_by_its_equation_NUMBER():
    """`visible_text(tbl)[-8:]` — the tail, which is where the number
    is. The head of a carrier is the equation itself, and a report line
    reading "equation DRI = Σ(w" names nothing a person can look up."""
    carrier = table("DRI=Σw", "(3)")

    _out, report = table_spacing(doc(carrier + para(run("где k."))))

    assert report.skipped == ["equation RI=Σw(3): a carrier, not a table"]


def test_a_note_that_declares_LESS_than_the_house_value_is_corrected_too():
    """`declared != note_before`, not `>`: the rule is that a note's
    declared space must be the house one, and a note declaring 0 under a
    house `note_before` of 60 is as wrong as one declaring 120. Only the
    inherited case is left alone."""
    p = ('<w:p><w:pPr><w:spacing w:before="0"/></w:pPr>'
         f'{run("Примечание. D — база.")}</w:p>')

    out, report = table_spacing(doc(table("Region") + p), note_before=60)

    assert before_of(out, "Примечание") == "60"
    assert report.notes == ["Примечание. D — база."]


# --- the run of 2026-08-20: 4.9 % ---------------------------------------


def test_a_table_with_no_rows_is_not_an_equation_CARRIER():
    """`len(rows) != 1`, and `> 1` lets a table with NO rows through to
    `rows[0]`. A `w:tbl` holding only its properties is what a template
    leaves behind, and an IndexError out of a house-style pass is a
    build that stops on a document Word opens happily."""
    assert _is_equation_carrier("<w:tbl><w:tblPr/></w:tbl>") is False


def test_a_ONE_cell_row_is_not_an_equation_carrier_either():
    """`len(cells) == 2`, and `<= 2` lets one cell — or none — reach
    `cells[-1]`. The shape this recognises is an equation beside its
    number; a single-cell row is an ordinary one-column table."""
    def tc(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"

    assert _is_equation_carrier("<w:tbl><w:tr>" + tc("x = 1")
                                + "</w:tr></w:tbl>") is False
    # and the row with NO cells, which is where `<= 2` reaches for
    # `cells[-1]` and finds nothing there
    assert _is_equation_carrier("<w:tbl><w:tr></w:tr></w:tbl>") is False
    assert _is_equation_carrier("<w:tbl><w:tr>" + tc("x = 1") + tc("(3)")
                                + "</w:tr></w:tbl>") is True


def test_an_EMPTY_row_or_cell_is_counted_not_merged_into_the_next():
    """`<w:tr/>` and `<w:tc/>` open nothing. Read as open tags they ran on
    to the next close: a table of two rows, one of them empty, counted as
    one, and a row of three cells as two — both then passed for the 1×2
    equation carrier, and the table lost the rule below it."""
    def tc(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"

    assert _is_equation_carrier("<w:tbl><w:tr/><w:tr>" + tc("x = 1")
                                + tc("(3)") + "</w:tr></w:tbl>") is False
    assert _is_equation_carrier("<w:tbl><w:tr><w:tc/>" + tc("x = 1")
                                + tc("(3)") + "</w:tr></w:tbl>") is False


def test_restoring_a_part_needs_the_content_types_on_BOTH_sides():
    """`and`, not `or`. The document being repaired may have no
    `[Content_Types].xml` at all — a caller assembling parts by hand, or
    a package Word wrote without one — and the `or` reading reaches for
    it in `parts` anyway. A KeyError from a repair pass is worse than
    the missing override it was going to add."""
    parts = {"word/document.xml": b"<d/>"}
    source = {"word/document.xml": b"<d/>",
              "word/media/image1.png": b"PNG",
              "[Content_Types].xml":
                  b'<Types><Override PartName="/word/media/image1.png"/>'
                  b"</Types>"}

    assert restore_parts(parts, source, prefixes=("word/media/",)) == [
        "word/media/image1.png"]
    assert parts["word/media/image1.png"] == b"PNG"


def test_a_document_with_no_glyph_to_restore_reports_NOTHING():
    """The map's own guard: an entry whose "restored" form IS the
    downgraded one would have every untouched formula reported as
    restored — a line saying work was done where none was.

    (`!=` written `is not` there is equivalent, and for a reason worth
    keeping: `_downgraded` is a chain of `str.replace`, which hands back
    the string it was given when it replaces nothing, so the two are one
    object exactly when they are equal.)"""
    ns = ('xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/'
          'math"')

    def doc(text: str) -> dict[str, bytes]:
        return {"word/document.xml":
                (f"<w:document {ns}><m:oMath><m:r><m:t>{text}</m:t></m:r>"
                 "</m:oMath></w:document>").encode()}

    assert restore_math_glyphs(doc("x - 1"), doc("x - 1")) == []
    assert restore_math_glyphs(doc("x - 1"), doc("x − 1")) == [
        "word/document.xml: 'x - 1' -> 'x − 1'"]


def test_a_note_ALREADY_at_the_pinned_spacing_is_left_alone():
    """`declared != note_before`, over two numbers a caller can set as
    high as it likes. Below 257 CPython hands out one object per integer
    and identity agrees with equality; at 300 — fifteen points, which is
    a spacing a house style can ask for — they part, and a note already
    correct is rewritten and reported every run.

    An audit that never comes back clean is the failure the note branch
    was written for in the first place."""
    note = ('<w:p><w:pPr><w:spacing w:before="300"/></w:pPr>'
            "<w:r><w:t>Note. Already at the house value.</w:t></w:r></w:p>")
    xml = doc(table("Region") + note + para(run("Text resumes here.")))

    out, report = table_spacing(xml, note_before=300)

    assert report.notes == []
    assert before_of(out, "Note.") == "300"


def test_a_heading_that_keeps_its_own_spacing_is_named_to_FORTY():
    """`text[:40]`, in the one line this pass writes about a paragraph
    it did NOT change. A heading carries its own, larger spacing, and
    the reader needs to recognise which heading — forty characters of a
    section title is a title, thirty-nine of it is the same title minus
    a letter, which reads as damage."""
    heading = ('<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>'
               "The Age-Friendly Index and its four domains, revised"
               "</w:t></w:r></w:p>")
    xml = doc(table("Region") + heading)

    _out, report = table_spacing(xml)

    assert report.skipped == [
        "heading 'The Age-Friendly Index and its four doma': has its own"]


# Argued rather than pinned, from the same run:
#
# * `rows[0]` written `rows[-1]`, and `cells[-1]` written `cells[1]` or
#   `cells[+1]`: each sits under a length check that has already fixed
#   the count at one and two.
# * `stream.count('"') % 2 == 0` written `<= 0`: a remainder of 2 is 0
#   or 1.
# * `if ch == "'"` and `elif ch == '"'` written `is`: one-character
#   strings are one object in CPython.
# * `sorted(..., key=lambda pair: -pair[0].start())` written `~`: both
#   are strictly decreasing in the offset, so the order is the same.
# * `zip(wts, out_texts, strict=True)` written `strict=False`:
#   `out_texts` is built one per `wts` entry.
# * `replace("<w:spacing", …, 1)` written 2: a `w:pPr` holds one.
# * `out != para_xml` written `is not` in `_set_before`, and `out !=
#   text` written `>` or `>=` in `restore_math_glyphs`. `str.replace`
#   and `re.sub` hand back the string they were given when they change
#   nothing, so identity agrees there; and the ordering pair holds
#   because `MATH_DOWNGRADES` maps U+2212 to "-" — every restoration
#   sorts ABOVE what it replaces. A downgrade added the other way round
#   would make those two real, which is worth knowing before adding
#   one.
# * `len(texts) == 1` written `<= 1`: the sets in `intent` are built by
#   `.add()` and are never empty.
# * `changed = False` in the note branch of `table_spacing` is GONE
#   rather than argued: the branch ends in `continue` and nothing read
#   the flag, so the mutant that set it True could not be killed by any
#   input. A value assigned and never read is the one survivor class
#   that answers to a deletion.


# Stacked exhibits. Every fixture above has ONE table with prose under
# it, and the walk for "the text that resumes" had no boundary — so on
# two tables in a row it stepped over the spacer between them, correctly
# (a spacer is not text that resumes), and landed in the NEXT TABLE'S
# first cell.

def test_a_SPACER_between_two_tables_does_not_send_the_rule_into_the_second():
    """Figures and tables stacked at the end, each separated by an empty
    paragraph, is what this house style produces — so this is the
    ordinary shape of the back of a paper, not an edge case. Unbounded,
    the second table's header row is pushed down 6pt and the report
    claims it as a paragraph spaced, which is the part that would have
    kept it hidden."""
    xml = doc(table("Region", "Value")
              + para(run(""))
              + table("Country", "Share")
              + para(run("The tables show.")))

    out, report = table_spacing(xml)

    assert report.spaced == ["The tables show."]
    assert before_of(out, "Country") is None, "spacing inside the next table"
    assert before_of(out, "The tables show") == "120"


def test_two_tables_with_NOTHING_between_them_are_left_alone():
    """The same boundary with no spacer to step over: the next
    paragraph in document order is already inside the second table."""
    xml = doc(table("Region", "Value")
              + table("Country", "Share")
              + para(run("The tables show.")))

    out, report = table_spacing(xml)

    assert report.spaced == ["The tables show."]
    assert before_of(out, "Country") is None


def test_a_table_that_ENDS_the_document_spaces_nothing():
    """The other end of the same bound: no next table and no paragraph
    after it either, so the walk has to run off the end and stop."""
    xml = doc(para(run("Before.")) + table("Region", "Value"))

    out, report = table_spacing(xml)

    assert report.spaced == []
    assert before_of(out, "Before") is None


def test_a_heading_a_tracked_change_DEMOTED_is_not_a_heading_any_more():
    """`w:pPrChange` records the properties a tracked change REPLACED,
    so a change that turned a Heading2 into body text leaves the only
    `w:pStyle` in the paragraph inside that snapshot. Searching the
    whole paragraph reads it and answers for the past — the defect
    `_declared_before` states, in this same file, twenty lines away.

    The cost is not a misread flag. A heading is treated as carrying its
    own spacing and BREAKS the walk, so the paragraph that really does
    resume gets no space and the table is abandoned with a skip line
    about a heading nobody can see in the document."""
    demoted = ('<w:p><w:pPr><w:pPrChange w:id="7" w:author="A" '
               'w:date="2026-08-24T00:00:00Z"><w:pPr>'
               '<w:pStyle w:val="Heading2"/></w:pPr></w:pPrChange></w:pPr>'
               "<w:r><w:t>The table shows.</w:t></w:r></w:p>")
    xml = doc(table("Region", "Value") + demoted)

    out, report = table_spacing(xml)

    assert report.skipped == [], report.skipped
    assert report.spaced == ["The table shows."]
    assert before_of(out, "The table shows") == "120"


def test_a_paragraph_that_IS_a_heading_is_still_skipped():
    """The other side of the same read: a live `w:pStyle` still counts,
    and a heading carries its own, larger spacing from its style —
    giving it 6pt would make the gap smaller, not larger."""
    heading = ('<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
               "<w:r><w:t>Results</w:t></w:r></w:p>")
    xml = doc(table("Region", "Value") + heading)

    out, report = table_spacing(xml)

    assert report.spaced == []
    assert any("heading" in line for line in report.skipped), report.skipped
    assert before_of(out, "Results") is None


def test_the_paragraph_MARKS_character_spacing_is_not_the_paragraphs():
    """CT_PPr's own `w:rPr` is a CT_ParaRPr, and that has a `w:spacing`
    too — character spacing, in a different unit, about the pilcrow.
    Ordinary Word output.

    Searching the whole `pPr` found it and carried its attributes up, so
    a paragraph that had declared no spacing at all came out with
    `<w:spacing w:before="120" w:val="20"/>` as a direct child of `pPr`.
    `w:val` is not a CT_Spacing attribute: a schema-invalid element,
    written by a repair."""
    para_xml = ('<w:p><w:pPr><w:rPr><w:spacing w:val="20"/></w:rPr></w:pPr>'
                "<w:r><w:t>The table shows.</w:t></w:r></w:p>")

    out, changed = _set_before(para_xml, 120)

    assert changed
    assert '<w:spacing w:before="120"/>' in out, out
    assert 'w:before="120" w:val' not in out, out
    # …and the mark's own spacing is left exactly as it was
    assert '<w:rPr><w:spacing w:val="20"/></w:rPr>' in out, out


def test_a_LONG_FORM_spacing_keeps_the_attributes_beside_the_one_being_set():
    """`<w:spacing w:after="0" w:line="240"></w:spacing>` is legal and
    is the same element as the self-closing spelling. Matched only in
    the short form, the branch that KEEPS the paragraph's other
    attributes was skipped and a bare `w:before` replaced the lot —
    `w:after` and `w:line` gone, which is the exact loss this function
    builds the element by hand to prevent."""
    para_xml = ('<w:p><w:pPr><w:spacing w:after="0" w:line="240" '
                'w:lineRule="auto"></w:spacing></w:pPr>'
                "<w:r><w:t>The table shows.</w:t></w:r></w:p>")

    out, changed = _set_before(para_xml, 120)

    assert changed
    assert 'w:before="120"' in out
    assert 'w:after="0"' in out, out
    assert 'w:line="240"' in out, out
    assert 'w:lineRule="auto"' in out, out


# --- the survivors of 2026-09-14 ------------------------------------------


def test_the_MIDDLE_of_three_tables_is_bounded_by_the_one_after_it():
    """The walk from a table stops at the NEXT table's start. With two
    tables, the table before the first and the table after it are one
    and the same, so only a middle table tells the next from any other."""
    xml = doc(table("A") + para(run("After A."))
              + table("B") + para(run("After B."))
              + table("C") + para(run("After C.")))

    out, report = table_spacing(xml)

    assert sorted(report.spaced) == ["After A.", "After B.", "After C."]
    for text in ("After A", "After B", "After C"):
        assert before_of(out, text) == "120", text


def test_a_document_of_MORE_THAN_256_TABLES_reaches_its_last_one():
    """`i + 1 < len(spans)` compares ints, and past 256 CPython builds a
    new object for each: two equal numbers compared by identity differ,
    and the last table then looks for a table after it that is not
    there."""
    body = "".join(table(f"T{i}") + para(run(f"After {i}."))
                   for i in range(300))

    out, report = table_spacing(doc(body))

    assert len(report.spaced) == 300
    assert before_of(out, "After 299") == "120"


# --- the survivor of 2026-09-15 ---------------------------------------------


def test_the_spacing_written_back_is_ONE_well_formed_element():
    """`_own_spacing` turns the tag it found into the self-closing form,
    and every test above read the result by ATTRIBUTE: `w:before`,
    `w:after` and `w:line` all present. With its test inverted both
    spellings still passed that — the short form came back as
    `…w:line="276"//>` and the long form as an opening tag never closed,
    so the paragraph no longer parsed. Read here as the whole element, and
    by parsing the paragraph it went into."""
    import xml.etree.ElementTree as ET

    for spacing, expected in (
            ('<w:spacing w:after="240" w:line="276"/>',
             '<w:spacing w:before="120" w:after="240" w:line="276"/>'),
            ('<w:spacing w:after="0" w:line="240" w:lineRule="auto">'
             "</w:spacing>",
             '<w:spacing w:before="120" w:after="0" w:line="240" '
             'w:lineRule="auto"/>')):
        para_xml = (f"<w:p><w:pPr>{spacing}</w:pPr>"
                    "<w:r><w:t>The table shows.</w:t></w:r></w:p>")

        out, changed = _set_before(para_xml, 120)

        assert changed
        assert re.findall(r"<w:spacing\b[^>]*>", out) == [expected], out
        assert "</w:spacing>" not in out, out
        ET.fromstring(doc(out))                 # the paragraph still parses
