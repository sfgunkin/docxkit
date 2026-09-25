"""`docxkit.paragraph` — split, merge and drop, and what each refuses.

Every result is read back through `visible_text` against the operation's
text contract AND through `lint_parts`, because the failures the papers'
own copies had were the kind a text check passes: a field split across
two paragraphs, a duplicate paraId, a section break gone.
"""
from __future__ import annotations

import re

import pytest
from conftest import document, field, make_parts, para, run, table

from docxkit import paragraph
from docxkit._xml import PARA_RE, visible_text
from docxkit.errors import AnchorError
from docxkit.lint import lint_parts

SECT = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
        'w:left="1440"/></w:sectPr>')


def texts(xml: str) -> list[str]:
    return [visible_text(m.group(0)) for m in PARA_RE.finditer(xml)]


def body(xml: str) -> str:
    return xml[xml.index("<w:body>") + 8:xml.index("</w:body>")]


def clean(xml: str) -> None:
    """Word would open it: the openability lint finds nothing."""
    assert lint_parts(make_parts(body(xml))) == []


def doc(*paras: str) -> str:
    return document("".join(paras))


def bookmark(bid: int, name: str) -> tuple[str, str]:
    return (f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>',
            f'<w:bookmarkEnd w:id="{bid}"/>')


FOOTNOTE = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            '<w:footnoteReference w:id="2"/></w:r>')


# ---------------------------------------------------------------- split --


def test_split_cuts_INSIDE_a_run_and_drops_the_space_at_the_cut():
    xml = doc(para(run("Wages rose in ", preserve=True),
                   run("three regions. Prices ", preserve=True),
                   run("fell in five."), pid="0000000A"))

    out = paragraph.split(xml, "Wages rose", "Prices fell")

    assert texts(out) == ["Wages rose in three regions.",
                          "Prices fell in five."]
    clean(out)


def test_the_second_half_gets_NO_paraId_and_the_first_keeps_its_own():
    """Two paragraphs may not share a w14:paraId; Word mints a new one."""
    xml = doc(para(run("One. Two. Three."), pid="00ABCDEF"))

    out = paragraph.split(xml, "One.", "Two.")

    assert out.count('w14:paraId="00ABCDEF"') == 1
    first, second = (m.group(0) for m in PARA_RE.finditer(out))
    assert 'w14:paraId="00ABCDEF"' in first
    assert "w14:paraId" not in second and "w14:textId" not in second


def test_a_split_at_a_run_BOUNDARY_moves_whole_runs():
    xml = doc(para(run("Alpha beta. ", style="Emphasis"),
                   run("Gamma delta.")))

    out = paragraph.split(xml, "Alpha", "Gamma")

    first, second = (m.group(0) for m in PARA_RE.finditer(out))
    assert "Emphasis" in first and "Emphasis" not in second
    assert texts(out) == ["Alpha beta.", "Gamma delta."]


def test_a_note_mark_before_the_cut_STAYS_with_its_sentence():
    """A footnote reference has no width, and sits exactly at the cut
    once the space is gone. It belongs to the sentence it closes."""
    xml = doc(para(run("First claim."), FOOTNOTE, run(" Second claim.")))

    out = paragraph.split(xml, "First", "Second")

    first, second = (m.group(0) for m in PARA_RE.finditer(out))
    assert "footnoteReference" in first and "footnoteReference" not in second


def test_a_bookmark_START_at_the_cut_opens_the_second_paragraph():
    start, end = bookmark(7, "Smith2020txt")
    xml = doc(para(run("Before. ", preserve=True), start,
                   run("After it."), end))

    out = paragraph.split(xml, "Before", "After")

    first, second = (m.group(0) for m in PARA_RE.finditer(out))
    assert "bookmarkStart" in second and "bookmark" not in first
    clean(out)


def test_a_citation_FIELD_at_the_cut_travels_whole():
    """Its begin, instruction and separate runs have no width. Decided
    one by one, the instruction stays behind and the label goes on."""
    cite = field('HYPERLINK \\l "Smith2020"', "Smith (2020)")
    xml = doc(para(run("Wages rose. ", preserve=True), cite,
                   run(" found the same.", preserve=True)))

    out = paragraph.split(xml, "Wages rose", "Smith (2020)")

    first, second = (m.group(0) for m in PARA_RE.finditer(out))
    assert "fldChar" not in first
    assert second.count('fldCharType="begin"') == 1
    assert second.count('fldCharType="end"') == 1
    assert texts(out) == ["Wages rose.", "Smith (2020) found the same."]
    clean(out)


def test_a_cut_INSIDE_a_field_is_refused():
    cite = field('HYPERLINK \\l "Smith2020"', "Smith and Jones (2020)")
    xml = doc(para(run("See "), cite, run(".")))

    with pytest.raises(AnchorError, match="inside a field"):
        paragraph.split(xml, "See", "Jones")


def test_a_cut_BETWEEN_the_runs_of_a_field_label_is_refused():
    """Begin and end would both stay left and the counts balance on each
    side — with half the label moved into the next paragraph unlinked."""
    label = run("Smith and ", preserve=True) + run("Jones (2020)")
    cite = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "S" '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'{label}<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    xml = doc(para(run("See "), cite, run(".")))

    with pytest.raises(AnchorError, match="inside a field"):
        paragraph.split(xml, "See", "Jones")


def test_a_cut_INSIDE_a_hyperlink_is_refused():
    link = ('<w:hyperlink w:anchor="Table3">'
            + run("Table 3 reports it") + "</w:hyperlink>")
    xml = doc(para(run("As "), link, run(".")))

    with pytest.raises(AnchorError, match="inside a <w:hyperlink>"):
        paragraph.split(xml, "As", "reports")


def test_a_cut_INSIDE_an_equation_is_refused():
    omath = ("<m:oMath><m:r><m:t>x+y</m:t></m:r></m:oMath>")
    xml = doc(para(run("Let "), omath, run(" hold.")))

    with pytest.raises(AnchorError, match="inside a <m:oMath>"):
        paragraph.split(xml, "Let", "+y")


def test_offsets_count_the_MATHS_before_the_cut():
    """An equation's glyphs are visible text; a walk that skipped them
    would cut every paragraph after one short by its length."""
    omath = ("<m:oMath><m:r><m:t>abcde</m:t></m:r></m:oMath>")
    xml = doc(para(run("With "), omath, run(" set. Then it holds.")))

    out = paragraph.split(xml, "With", "Then")

    assert texts(out) == ["With abcde set.", "Then it holds."]


def test_a_bookmark_pair_ACROSS_the_cut_is_refused():
    start, end = bookmark(3, "Caption1")
    xml = doc(para(start, run("One sentence. Two sentences."), end))

    with pytest.raises(AnchorError, match="'Caption1'"):
        paragraph.split(xml, "One", "Two")


def test_the_SECTION_BREAK_stays_on_the_second_half_only():
    """The sectPr is the paragraph MARK ending a section; after a split
    the original mark is the second paragraph's."""
    xml = doc(f"<w:p><w:pPr><w:jc w:val=\"both\"/>{SECT}</w:pPr>"
              f"{run('End of part one. Start of part two.')}</w:p>")

    out = paragraph.split(xml, "End of", "Start of")

    first, second = (m.group(0) for m in PARA_RE.finditer(out))
    assert "sectPr" not in first and '<w:jc w:val="both"/>' in first
    assert "sectPr" in second and '<w:jc w:val="both"/>' in second
    clean(out)


@pytest.mark.parametrize("before,match", [
    ("x", "3 hits"),
    ("Alpha", "starts"),
    ("absent", "0 hits"),
])
def test_an_anchor_that_does_not_name_ONE_place_is_refused(before, match):
    xml = doc(para(run("Alpha x. Beta x. Gamma x.")))

    with pytest.raises(AnchorError, match=match):
        paragraph.split(xml, "Alpha", before)


def test_a_paragraph_with_TRACKED_CHANGES_is_refused():
    xml = doc(para(run("Kept. "),
                   '<w:ins w:id="5" w:author="A" '
                   'w:date="2026-01-01T00:00:00Z">'
                   + run("Added.") + "</w:ins>"))

    with pytest.raises(AnchorError, match="tracked changes"):
        paragraph.split(xml, "Kept", "Added")


def test_a_space_that_SHARES_a_run_with_a_tab_is_kept_rather_than_refused():
    xml = doc(para(run("Head. "),
                   '<w:r><w:tab/><w:t xml:space="preserve"> </w:t></w:r>',
                   run("Tail.")))

    out = paragraph.split(xml, "Head", "Tail")

    assert texts(out)[1] == "Tail."
    assert "".join(texts(out)) == "Head.  Tail."


def test_escaped_text_is_cut_as_the_reader_reads_it():
    xml = doc(para(run("R&amp;D rose. Output &lt; 5 fell.")))

    out = paragraph.split(xml, "R&D", "Output")

    assert texts(out) == ["R&D rose.", "Output < 5 fell."]
    clean(out)


# ---------------------------------------------------------------- merge --


def test_merge_joins_with_the_separator_and_leaves_the_second_runs_alone():
    xml = doc(para(run("First part."), pid="0000000A"),
              para(run("Second", style="Emphasis"),
                   run(" part.", preserve=True),
                   pid="0000000B"),
              para(run("Untouched."), pid="0000000C"))

    out = paragraph.merge(xml, "First part", "Second")

    assert texts(out) == ["First part. Second part.", "Untouched."]
    merged = next(PARA_RE.finditer(out)).group(0)
    assert 'w14:paraId="0000000A"' in merged
    assert run("Second", style="Emphasis") in merged
    clean(out)


def test_the_separator_does_NOT_wear_a_link_or_a_note_mark():
    """The first paragraph ENDS on a note mark after a linked citation.
    Its last prose run is the one before them."""
    prose = '<w:r><w:rPr><w:i/></w:rPr><w:t>Italic prose</w:t></w:r>'
    link = ('<w:hyperlink w:anchor="X"><w:r><w:rPr>'
            '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>(Smith 2020)</w:t>'
            "</w:r></w:hyperlink>")
    xml = doc(para(prose, link, FOOTNOTE), para(run("Next.")))

    out = paragraph.merge(xml, "Italic prose", "Next.")

    sep = re.findall(r"<w:r>(?:(?!</w:r>).)*?<w:t xml:space=\"preserve\"> "
                     r"</w:t></w:r>", out)
    assert sep == ['<w:r><w:rPr><w:i/></w:rPr>'
                   '<w:t xml:space="preserve"> </w:t></w:r>']


def test_sep_EMPTY_joins_the_text_directly():
    xml = doc(para(run("Hyphen-")), para(run("ated word.")))

    out = paragraph.merge(xml, "Hyphen-", "ated", sep="")

    assert texts(out) == ["Hyphen-ated word."]


@pytest.mark.parametrize("between", [
    para(run("A paragraph in between.")),
    table("<w:tr><w:tc>" + para(run("cell")) + "</w:tc></w:tr>"),
])
def test_a_merge_with_a_paragraph_that_is_NOT_next_is_refused(between):
    xml = doc(para(run("One.")), between, para(run("Three.")))

    with pytest.raises(AnchorError, match="immediately after"):
        paragraph.merge(xml, "One.", "Three.")


def test_both_anchors_in_ONE_paragraph_is_refused():
    xml = doc(para(run("Alpha and beta.")), para(run("Gamma.")))

    with pytest.raises(AnchorError, match="immediately after"):
        paragraph.merge(xml, "Alpha", "beta")


def test_markers_Word_HOISTED_between_the_two_move_into_the_join():
    start, end = bookmark(9, "Jones2019")
    xml = doc(para(run("Entry one.")), start + end,
              para(run("Jones (2019) entry.")))

    out = paragraph.merge(xml, "Entry one", "Jones (2019)")

    (merged,) = [m.group(0) for m in PARA_RE.finditer(out)]
    assert merged.index("bookmarkStart") < merged.index("Jones (2019)")
    assert merged.index("Entry one") < merged.index("bookmarkStart")
    clean(out)


def test_the_SECOND_paragraphs_section_break_is_carried_onto_the_merge():
    xml = doc(para(run("Last of one.")),
              f"<w:p><w:pPr>{SECT}</w:pPr>{run('Last of two.')}</w:p>")

    out = paragraph.merge(xml, "Last of one", "Last of two")

    (merged,) = [m.group(0) for m in PARA_RE.finditer(out)]
    assert "sectPr" in merged
    clean(out)


def test_the_FIRST_paragraphs_section_break_refuses_the_merge():
    xml = doc(f"<w:p><w:pPr>{SECT}</w:pPr>{run('Ends section one.')}</w:p>",
              para(run("Opens section two.")))

    with pytest.raises(AnchorError, match="section break"):
        paragraph.merge(xml, "Ends section", "Opens section")


def test_split_then_merge_gives_the_text_back():
    words = "Wages rose in three regions. Prices fell in five."
    xml = doc(para(run(words)))

    out = paragraph.merge(paragraph.split(xml, "Wages", "Prices"),
                          "Wages", "Prices")

    assert texts(out) == [words]


# ----------------------------------------------------------------- drop --


def test_drop_removes_the_one_paragraph_and_nothing_else():
    xml = doc(para(run("Keep one.")), para(run("Drop me.")),
              para(run("Keep three.")), para(run("Keep four.")),
              para(run("Keep five.")))

    out = paragraph.drop(xml, "Drop me")

    assert texts(out) == ["Keep one.", "Keep three.", "Keep four.",
                          "Keep five."]
    clean(out)


def test_a_BOOKMARK_is_refused_by_name_and_taken_when_allowed():
    start, end = bookmark(4, "Table2txt")
    xml = doc(para(run("Keep.")), para(start, run("Drop me."), end))

    with pytest.raises(AnchorError, match="'Table2txt'"):
        paragraph.drop(xml, "Drop me")
    out = paragraph.drop(xml, "Drop me", allow_bookmarks=True)
    assert "Table2txt" not in out
    clean(out)


def test_Words_own_GoBack_needs_no_permission():
    start, end = bookmark(0, "_GoBack")
    xml = doc(para(run("Keep.")), para(start, run("Drop me."), end))

    assert texts(paragraph.drop(xml, "Drop me")) == ["Keep."]


def test_the_HOISTED_head_bookmark_goes_with_its_paragraph():
    start, end = bookmark(6, "Brewer2007")
    xml = doc(para(run("Keep.")), start + end, para(run("Brewer (2007).")))

    with pytest.raises(AnchorError, match="'Brewer2007'"):
        paragraph.drop(xml, "Brewer")
    out = paragraph.drop(xml, "Brewer", allow_bookmarks=True)
    assert "Brewer2007" not in out and "bookmarkEnd" not in out
    clean(out)


def test_a_hoisted_head_bookmark_LONGER_than_2048_chars_goes_too():
    """Review of 2026-09-24: a docxkit-built head bookmark redeclares its
    namespaces (~2,524 characters on API8), and the 2,048-character
    lookback never reached its start — the marker stayed behind."""
    ns = " ".join(f'xmlns:n{i}="urn:example:namespace:{i:04d}"'
                  for i in range(80))
    start = f'<w:bookmarkStart {ns} w:id="6" w:name="Brewer2007"/>'
    assert len(start) > 2048
    xml = doc(para(run("Keep.")), start + '<w:bookmarkEnd w:id="6"/>',
              para(run("Brewer (2007).")))

    out = paragraph.drop(xml, "Brewer", allow_bookmarks=True)

    assert "Brewer2007" not in out and "bookmarkEnd" not in out


def test_a_lone_END_in_the_gap_is_somebody_elses_and_stays():
    start, end = bookmark(8, "Span")
    xml = doc(para(start, run("Keep.")), end, para(run("Drop me.")))

    out = paragraph.drop(xml, "Drop me")

    assert '<w:bookmarkEnd w:id="8"/>' in out
    clean(out)


def test_HALF_a_bookmark_in_the_paragraph_is_refused_even_when_allowed():
    start, end = bookmark(5, "Across")
    xml = doc(para(start, run("Drop me.")), para(run("Keep."), end))

    with pytest.raises(AnchorError, match="only half"):
        paragraph.drop(xml, "Drop me", allow_bookmarks=True)


def test_a_NOTE_reference_is_refused_and_taken_when_allowed():
    xml = doc(para(run("Keep.")), para(run("Drop me."), FOOTNOTE))

    with pytest.raises(AnchorError, match="prune_orphans"):
        paragraph.drop(xml, "Drop me")
    assert "footnoteReference" not in paragraph.drop(
        xml, "Drop me", allow_notes=True)


@pytest.mark.parametrize("inside,match", [
    ('<w:commentRangeStart w:id="1"/>', "comment"),
    ('<w:del w:id="2" w:author="A" w:date="2026-01-01T00:00:00Z">'
     '<w:r><w:delText>gone</w:delText></w:r></w:del>', "tracked"),
])
def test_a_comment_anchor_or_a_revision_is_refused_outright(inside, match):
    xml = doc(para(run("Keep.")), para(inside, run("Drop me.")))

    with pytest.raises(AnchorError, match=match):
        paragraph.drop(xml, "Drop me")


def test_the_paragraph_ENDING_A_SECTION_is_refused():
    xml = doc(para(run("Keep.")),
              f"<w:p><w:pPr>{SECT}</w:pPr>{run('Drop me.')}</w:p>")

    with pytest.raises(AnchorError, match="ends a section"):
        paragraph.drop(xml, "Drop me")


def test_the_ONLY_paragraph_of_a_cell_is_refused_one_of_three_is_not():
    tcpr = '<w:tcPr><w:tcW w:w="2000" w:type="dxa"/></w:tcPr>'
    alone = doc(table(f"<w:tr><w:tc>{tcpr}{para(run('Lone cell.'))}"
                      f"</w:tc></w:tr>"))
    three = doc(table(f"<w:tr><w:tc>{tcpr}{para(run('One.'))}"
                      f"{para(run('Drop me.'))}{para(run('Three.'))}"
                      f"</w:tc></w:tr>"))

    with pytest.raises(AnchorError, match="only paragraph"):
        paragraph.drop(alone, "Lone cell")
    assert texts(paragraph.drop(three, "Drop me")) == ["One.", "Three."]


def test_a_cell_with_an_EMPTY_tcPr_is_still_a_cell():
    """`<w:tcPr/>` is as real as a full one. Read only as `...</w:tcPr>`,
    the guard missed the cell and emptied it — a file Word will not open
    (found by the regex registry's probe, 2026-09-24)."""
    alone = doc(table("<w:tr><w:tc><w:tcPr/>" + para(run("Lone cell."))
                      + "</w:tc></w:tr>"))

    with pytest.raises(AnchorError, match="only paragraph"):
        paragraph.drop(alone, "Lone cell")


def test_a_bookmark_written_NAME_FIRST_is_still_seen():
    """Word writes both attribute orders."""
    xml = doc(para(run("Keep.")),
              para('<w:bookmarkStart w:name="Lee2021" w:id="12"/>',
                   run("Drop me."), '<w:bookmarkEnd w:id="12"/>'))

    with pytest.raises(AnchorError, match="'Lee2021'"):
        paragraph.drop(xml, "Drop me")


def test_drop_works_on_a_NOTES_part_too():
    notes = ('<w:footnotes><w:footnote w:id="2">'
             + para(run("Note text."), pid="1")
             + para(run("Drop me."), pid="2")
             + para(run("More."), pid="3") + "</w:footnote></w:footnotes>")

    out = paragraph.drop(notes, "Drop me")

    assert texts(out) == ["Note text.", "More."]
    with pytest.raises(AnchorError, match="only paragraph"):
        paragraph.drop('<w:footnote w:id="3">' + para(run("Solo.")) +
                       "</w:footnote>", "Solo")
