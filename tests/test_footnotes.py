"""Footnote font enforcement — the house rule, and the three traps.

`set_font` writes DIRECT run formatting, because that is what wins in
Word. The interesting cases are all about what it must NOT touch: the
equation runs whose face is load-bearing, the historical half of a
tracked formatting change, and Word's own separator notes.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from docxkit import footnotes
from docxkit._xml import RPR_ORDER, set_run_property

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')


def part(*notes: str) -> str:
    return f"<w:footnotes {NS}>{''.join(notes)}</w:footnotes>"


def note(nid: int | str, body: str) -> str:
    return f'<w:footnote w:id="{nid}"><w:p>{body}</w:p></w:footnote>'


def run(text: str, rpr: str = "") -> str:
    props = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return f"<w:r>{props}<w:t>{text}</w:t></w:r>"


def rpr_of(xml: str, which: int = 0) -> str:
    return str(re.findall(r"<w:rPr>(.*?)</w:rPr>", xml, re.DOTALL)[which])


def parses(xml: str) -> bool:
    ET.fromstring(xml)
    return True


def test_a_plain_run_gets_the_face_and_the_size():
    out, rep = footnotes.set_font(part(note(2, run("a note"))))
    assert 'w:ascii="Times New Roman"' in out
    assert 'w:sz w:val="20"' in out and 'w:szCs w:val="20"' in out
    assert (rep.notes, rep.runs_set) == (1, 1)
    assert parses(out)


@pytest.mark.parametrize("size,half",
                         [(10, 20), (10.5, 21), (9, 18), (12, 24)])
def test_a_point_size_is_stored_doubled(size, half):
    """Word records half-points; 10pt is w:val="20". Getting this wrong
    is a document at twice or half the intended size, which no test that
    only checks "an w:sz is present" would notice."""
    out, _ = footnotes.set_font(part(note(2, run("x"))), size=size)
    assert f'<w:sz w:val="{half}"/>' in out


def test_the_run_properties_stay_in_schema_order():
    """EG_RPrBase fixes the order and Word REJECTS a part that breaks
    it, so a property cannot simply be appended to w:rPr. Asserted as
    the ordering itself rather than one expected string, so it holds for
    whatever the run already carried."""
    existing = ('<w:rStyle w:val="FootnoteReference"/><w:i/>'
                '<w:vertAlign w:val="superscript"/><w:lang w:val="en-US"/>')
    out, _ = footnotes.set_font(part(note(2, run("x", existing))))
    names = re.findall(r"<w:(\w+)\b", rpr_of(out))
    ranks = [RPR_ORDER.index(n) for n in names]
    assert ranks == sorted(ranks), names
    assert parses(out)


def test_an_existing_size_is_replaced_not_duplicated():
    out, _ = footnotes.set_font(part(note(2, run("x", '<w:sz w:val="18"/>'))))
    assert rpr_of(out).count("<w:sz ") == 1
    assert 'w:val="18"' not in rpr_of(out)


def test_an_equation_run_keeps_its_face_and_is_counted():
    """A footnote carrying OMML holds runs declared in Cambria Math, and
    the text faces do not have those glyphs — rewriting them is how an
    equation becomes boxes. Skipped, and REPORTED, so "some runs were
    left" is visible rather than inferred from a count that looks low.
    """
    math = ('<m:oMath><w:r><w:rPr><w:rFonts w:ascii="Cambria Math"/></w:rPr>'
            "<w:t>x</w:t></w:r></m:oMath>")
    out, rep = footnotes.set_font(part(note(2, run("see ") + math)))
    assert 'w:ascii="Cambria Math"' in out
    assert rep.runs_set == 1 and rep.math_runs_skipped == 1
    assert "equation run(s) left alone" in rep.format()


def test_words_own_separator_notes_are_left_alone():
    """Ids 0 and -1 are the separator and continuation notes Word puts in
    every document. They are not footnotes and restyling them is editing
    furniture the author never sees."""
    sep = ('<w:footnote w:id="0"><w:p><w:r><w:separator/></w:r></w:p>'
           "</w:footnote>")
    out, rep = footnotes.set_font(part(sep + note(2, run("real"))))
    assert "<w:separator/></w:r>" in out, "the separator run was rewritten"
    assert rep.notes == 1


def test_a_tracked_formatting_change_is_not_edited_in_its_past():
    """w:rPrChange stores the properties a tracked change REPLACED, and
    the schema puts it last inside the live w:rPr. A writer that finds
    the first </w:rPr> edits that historical snapshot and leaves the
    page exactly as it was."""
    tracked = ('<w:r><w:rPr><w:b/><w:rPrChange w:id="9" w:author="A" '
               'w:date="2026-01-01T00:00:00Z">'
               '<w:rPr><w:sz w:val="18"/></w:rPr></w:rPrChange>'
               "</w:rPr><w:t>t</w:t></w:r>")
    out, _ = footnotes.set_font(part(note(2, tracked)))
    live = out.split("<w:rPrChange")[0]
    assert 'w:sz w:val="20"' in live, "the live properties were not set"
    assert '<w:rPr><w:sz w:val="18"/></w:rPr></w:rPrChange>' in out, (
        "the historical snapshot was rewritten")
    assert parses(out)


def test_setting_the_font_twice_changes_nothing_the_second_time():
    once, _ = footnotes.set_font(part(note(2, run("x", "<w:i/>"))))
    twice, _ = footnotes.set_font(once)
    assert twice == once


def test_the_audit_reports_an_unstated_face_as_inherited():
    """A run with no w:rFonts renders in whatever FootnoteText and
    docDefaults say. Reporting that as "Times New Roman 10" would be a
    guess about styles.xml — a part this module is never handed — and
    the guess would read as a clean bill of health."""
    seen = footnotes.fonts(part(note(2, run("bare"))))
    assert seen == {"inherited": 1}

    sized = footnotes.fonts(part(note(2, run("x", '<w:sz w:val="18"/>'))))
    assert sized == {"inherited face 9pt": 1}


def test_the_audit_answers_the_question_after_the_fix():
    xml = part(note(2, run("a") + run("b", '<w:sz w:val="18"/>')),
               note(3, run("c")))
    assert footnotes.fonts(xml) != {"Times New Roman 10pt": 3}
    out, _ = footnotes.set_font(xml)
    assert footnotes.fonts(out) == {"Times New Roman 10pt": 3}


def test_a_face_with_an_ampersand_is_escaped_into_the_attribute():
    out, _ = footnotes.set_font(part(note(2, run("x"))), name='Bell & "Co"')
    assert "&amp;" in out and "&quot;" in out
    assert parses(out)


# ------------------------------------- locating and appending ------------


def test_find_returns_the_matching_note_not_the_first_one():
    xml = part(note(2, run("the first note")),
               note(3, run("the second note")),
               note(4, run("the third note")))
    assert footnotes.find(xml, "second").id == "3"


def test_find_refuses_an_ambiguous_anchor():
    """Which is also why `return hits[0]` cannot be tested against
    `hits[-1]`: the refusal above guarantees there is exactly one, so
    the two index the same element. An equivalent mutant, recorded here
    rather than chased — a test that pinned it would pin an accident."""
    xml = part(note(2, run("a shared phrase here")),
               note(3, run("a shared phrase there")))
    with pytest.raises(Exception, match="2 hits"):
        footnotes.find(xml, "shared phrase")


def test_append_lands_inside_the_LAST_paragraph():
    """A run placed directly in `w:footnote`, or in the wrong paragraph,
    is what makes Word reject the part."""
    two = ('<w:footnote w:id="2">'
           f"<w:p>{run('first para')}</w:p>"
           f"<w:p>{run('second para')}</w:p></w:footnote>")
    out = footnotes.append(part(two), "second para", " appended.")
    assert parses(out)
    body = re.findall(r"<w:p>.*?</w:p>", out, re.DOTALL)
    assert " appended." not in body[0]
    assert body[1].endswith("appended.</w:t></w:r></w:p>"), body[1]


def test_append_puts_the_text_inside_the_paragraph_not_after_it():
    out = footnotes.append(part(note(2, run("a note"))), "a note", " more")
    assert "</w:p></w:footnote>" in out
    assert "</w:p><w:r>" not in out, "the run escaped its paragraph"


# ------------------------------- the guard that has never fired -----------
# `set_font` skips a `w:r` sitting INSIDE an `m:oMath` — legal markup, and
# how Word writes literal text in a formula. The module's own docstring
# says the skip has never fired on a real document: of the 1,940 footnote
# parts on this machine, 495 carry OMML and none of them puts a `w:r` in
# it, so the `m:r` rule does all the work. The mutation sweep found that
# no TEST fired it either -- 18 mutants lived on that one line across the
# two functions. It is the only thing standing between a formula and the
# body font the day the run pattern is widened.

MATH_WITH_A_TEXT_RUN = (
    '<m:oMath><m:r><m:t>x</m:t></m:r>'
    '<w:r><w:rPr><w:rFonts w:ascii="Cambria Math"/><w:sz w:val="24"/>'
    "</w:rPr><w:t> if </w:t></w:r>"
    "<m:r><m:t>y</m:t></m:r></m:oMath>")


def test_a_text_run_inside_an_equation_keeps_its_face():
    """Rewriting it to Times New Roman is how an equation turns into
    boxes: the text faces do not carry the math glyphs."""
    out, rep = footnotes.set_font(
        part(note(2, run("a note") + MATH_WITH_A_TEXT_RUN)))
    assert 'w:ascii="Cambria Math"' in out, "the equation run was restyled"
    assert out.count('w:ascii="Times New Roman"') == 1, "only the prose run"
    assert rep.runs_set == 1
    assert rep.math_runs_skipped == 1, "the skip is COUNTED, not inferred"
    assert parses(out)


def test_the_skip_is_reported_so_a_low_total_is_not_a_mystery():
    """"some runs were left" has to be visible rather than inferred from
    a total that looks low."""
    _, rep = footnotes.set_font(
        part(note(2, run("a") + MATH_WITH_A_TEXT_RUN + run("b"))))
    assert (rep.runs_set, rep.math_runs_skipped) == (2, 1)
    assert "1 equation run(s) left alone" in rep.format()


def test_a_run_after_an_equation_is_still_reached():
    """`continue`, not `break`: the skip must not end the walk, or every
    run after the first equation keeps the wrong size."""
    out, rep = footnotes.set_font(
        part(note(2, MATH_WITH_A_TEXT_RUN + run("prose after"))))
    assert rep.runs_set == 1
    assert 'w:sz w:val="20"' in out


def test_the_audit_does_not_count_an_equations_run_either():
    """`fonts` carries the same skip, and the same 14 mutants lived on
    it. A Cambria Math run in the tally reads as a footnote set in the
    wrong face."""
    seen = footnotes.fonts(part(note(2, run("a") + MATH_WITH_A_TEXT_RUN)))
    assert "Cambria Math" not in str(seen)
    assert seen == {"inherited": 1}


# --------------------------------------------- do they AGREE on a size ----
# The manuscript defect this exists for: one footnote rendered at 12pt
# among 10pt neighbours, and the offender carried NO w:sz at all — it
# inherited the body size, so searching for a wrong value found nothing.


SZ10, SZ12 = '<w:sz w:val="20"/>', '<w:sz w:val="24"/>'
#: the run that draws the little number, as Word writes it
MARK = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
        "<w:footnoteRef/></w:r>")


def test_footnotes_that_all_state_the_same_size_are_clean():
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10))))
    assert report.ok and report.house == 20 and report.counted == 2


def test_the_one_that_states_nothing_is_the_finding():
    """No wrong value exists to search for: the note is silent and
    inherits whatever the body is."""
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, run("the odd one out"))))
    assert not report.ok
    (odd,) = report.outliers
    assert odd.id == "4" and odd.stated == (None,)
    assert "states no size" in str(odd)
    assert "the odd one out" in str(odd), "a finding must say where"


def test_a_note_stating_a_different_size_is_also_a_finding():
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, run("c", SZ12))))
    assert [o.id for o in report.outliers] == ["4"]
    assert "12pt" in str(report.outliers[0])


def test_a_document_whose_footnotes_all_inherit_has_nothing_to_report():
    """Every size living in styles.xml is perfectly ordinary, and a check
    that flagged it would flag half the manuscripts on this machine."""
    report = footnotes.sizes(part(note(2, run("a")), note(3, run("b"))))
    assert report.ok and report.house is None


def test_the_reference_mark_does_not_count_as_a_silent_run():
    """The run holding w:footnoteRef is formatted by the
    FootnoteReference style and states no size ON PURPOSE. Counting it
    among the BODY runs would put every conforming document on the list
    — the mark is superscript and a size or two smaller by design."""
    report = footnotes.sizes(part(note(2, MARK + run("a", SZ10)),
                                  note(3, MARK + run("b", SZ10))))
    assert report.ok, report.format()
    assert report.mark_outliers == []


# --- the marks, against each OTHER -------------------------------------
#
# The exclusion above was recorded as a known edge with "Evidence:
# none", and the entry asked for a manuscript that sizes its marks
# before widening anything. Measured over 331 manuscripts with footnotes
# (2026-08-11): 26 state a size on the mark, and in 22 of them exactly
# ONE mark RESOLVES differently from the rest — 10pt against 11pt in
# IGM, TCC and Parental Style, several of them submitted. LI's is the
# clearest: every mark run is byte-identical, and one note's paragraph
# lost its `FootnoteText` style, so that mark alone falls through to the
# document default and is drawn a point larger.


def test_marks_that_all_resolve_alike_say_nothing():
    """The quiet the exclusion was protecting, kept: a document whose
    marks agree reports nothing however they are styled."""
    sized = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
             f'{SZ10}</w:rPr><w:footnoteRef/></w:r>')
    report = footnotes.sizes(part(note(2, sized + run("a", SZ10)),
                                  note(3, sized + run("b", SZ10))))
    assert report.ok, report.format()


def test_a_mark_that_resolves_larger_than_the_rest_is_reported():
    """And the body check cannot see it: every body run states the same
    size, so the note reads as conforming."""
    def mark(sz: str) -> str:
        return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                f'{sz}</w:rPr><w:footnoteRef/></w:r>')

    report = footnotes.sizes(part(note(2, mark(SZ10) + run("a", SZ10)),
                                  note(3, mark(SZ10) + run("b", SZ10)),
                                  note(4, mark(SZ12) + run("c", SZ10))))
    assert report.outliers == [], "the BODY sizes agree"
    assert not report.ok
    (found,) = report.mark_outliers
    assert found.id.startswith("4") and "reference mark" in found.id
    assert "12pt" in str(found)
    assert "reference marks" in report.format()


def test_a_mark_left_to_the_document_default_by_a_lost_pStyle():
    """LI7's shape exactly: the mark runs are identical and the
    PARAGRAPH differs, so nothing about the mark itself looks wrong."""
    styles = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:styleId="FootnoteText">'
              f'<w:rPr>{SZ10}</w:rPr></w:style></w:styles>')
    def styled(nid: int) -> str:
        return (f'<w:footnote w:id="{nid}"><w:p><w:pPr><w:pStyle '
                f'w:val="FootnoteText"/></w:pPr>{MARK}{run("a")}'
                "</w:p></w:footnote>")

    # three conforming notes, so the house is a majority rather than a
    # coin toss — two marks that differ have no house at all
    bare = (f'<w:footnote w:id="9"><w:p>{MARK}{run("b", SZ10)}'
            "</w:p></w:footnote>")
    report = footnotes.sizes(part(styled(2), styled(3), styled(4), bare),
                             styles_xml=styles)
    assert report.mark_house == 20
    (found,) = report.mark_outliers
    assert found.id.startswith("9")
    assert "12pt" in str(found) and "document default" in str(found)


def test_the_STYLED_marks_are_the_house_however_few_they_are():
    """Parental Style 2026-08-12, and the report was exactly backwards.

    Five footnote paragraphs carried no `w:pStyle` at all, fell through
    Normal to a 12pt `docDefaults`, and took the majority with them; the
    two the check FLAGGED were the two carrying `pStyle FootnoteText` —
    the well-formed ones. Acting on it would have stripped the correct
    style off the correct notes. A count cannot tell malformed from
    house; how the value RESOLVES can.
    """
    styles_xml = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr>'
                  '<w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>'
                  '<w:style w:type="paragraph" w:styleId="FootnoteText">'
                  f'<w:rPr>{SZ10}</w:rPr></w:style></w:styles>')

    def styled(nid: int) -> str:
        return (f'<w:footnote w:id="{nid}"><w:p><w:pPr><w:pStyle '
                f'w:val="FootnoteText"/></w:pPr>{MARK}{run("a", SZ10)}'
                "</w:p></w:footnote>")

    def bare(nid: int) -> str:
        # 10pt body text stated on every run, and a mark left to fall
        # through to the document default — which is the whole trap: the
        # BODY halves all agree, so only the marks disagree
        return (f'<w:footnote w:id="{nid}"><w:p>{MARK}{run("b", SZ10)}'
                "</w:p></w:footnote>")

    report = footnotes.sizes(
        part(styled(2), styled(3), *(bare(n) for n in range(4, 9))),
        styles_xml=styles_xml)

    assert report.outliers == [], "the BODY sizes agree"
    assert report.mark_house == 20, "the majority (12pt) set the house"
    assert report.mark_house_from == "style"
    assert sorted(o.id.split()[0] for o in report.mark_outliers) == \
        ["4", "5", "6", "7", "8"]
    assert report.unstyled == ["4", "5", "6", "7", "8"]
    assert "NO w:pStyle" in report.format()


def test_with_no_styled_mark_the_commonest_value_still_stands():
    """There is nothing better to go on then — but the report says which
    of the two answers it gave, because they deserve different
    confidence."""
    def mark(sz: str) -> str:
        return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                f'{sz}</w:rPr><w:footnoteRef/></w:r>')

    report = footnotes.sizes(part(note(2, mark(SZ10) + run("a", SZ10)),
                                  note(3, mark(SZ10) + run("b", SZ10)),
                                  note(4, mark(SZ12) + run("c", SZ10))))
    assert report.mark_house == 20
    assert report.mark_house_from == "majority"
    assert len(report.mark_outliers) == 1


def test_words_separator_notes_are_not_footnotes():
    """ids 0 and -1 are the separator and continuationSeparator. A naive
    sweep "fixes" two things nobody reads."""
    report = footnotes.sizes(part(note(0, run("---")), note(-1, run("---")),
                                  note(2, run("a", SZ10))))
    assert report.counted == 1 and report.ok


def test_a_mixed_footnote_is_reported_with_both_sizes():
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, run("c", SZ10) + run("d", SZ12))))
    (odd,) = report.outliers
    assert odd.stated == (20, 24)
    assert "10pt, 12pt" in str(odd)


def test_set_font_answers_the_finding():
    """The repair and the check are a pair: after set_font the audit
    comes back clean, which is what makes it worth running twice."""
    xml = part(note(2, run("a", SZ10)), note(3, run("b", SZ10)),
               note(4, run("silent")))
    assert not footnotes.sizes(xml).ok
    out, _ = footnotes.set_font(xml, size=10)
    assert footnotes.sizes(out).ok


# ------------------------------- what the STYLES answer that XML cannot ---


def styles(*defs: str, default: str = "24") -> str:
    return (f"<w:styles {NS}><w:docDefaults><w:rPrDefault><w:rPr>"
            f'<w:sz w:val="{default}"/></w:rPr></w:rPrDefault>'
            f"</w:docDefaults>{''.join(defs)}</w:styles>")


def style(sid: str, sz: str | None = None, based_on: str | None = None) -> str:
    inner = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    inner += f'<w:rPr><w:sz w:val="{sz}"/></w:rPr>' if sz else ""
    return f'<w:style w:type="paragraph" w:styleId="{sid}">{inner}</w:style>'


def styled_note(nid: int, text: str, pstyle: str) -> str:
    return (f'<w:footnote w:id="{nid}"><w:p>'
            f'<w:pPr><w:pStyle w:val="{pstyle}"/></w:pPr>'
            f"{run(text)}</w:p></w:footnote>")


def test_a_note_whose_STYLE_supplies_the_size_is_not_a_finding():
    """The false positive this check produced on the first real
    manuscript it was pointed at: Parental_style's footnote 6 carries
    `pStyle FootnoteText`, that style says `w:sz 20`, and it has always
    rendered at 10pt like its neighbours."""
    xml = part(note(2, run("a", SZ10)), note(3, run("b", SZ10)),
               styled_note(4, "styled", "FootnoteText"))
    assert not footnotes.sizes(xml).ok, "blind to styles, it is a finding"
    report = footnotes.sizes(xml, styles_xml=styles(
        style("FootnoteText", sz="20")))
    assert report.ok, report.format()


def test_a_style_that_does_not_supply_it_falls_back_to_the_default():
    """And that is the shape of the REAL offender: no pStyle at all, so
    the note takes docDefaults — 12pt among 10pt neighbours."""
    xml = part(note(2, run("a", SZ10)), note(3, run("b", SZ10)),
               note(4, run("the real one")))
    report = footnotes.sizes(xml, styles_xml=styles(default="24"))
    (odd,) = report.outliers
    assert odd.stated == (24,)
    assert "resolves to 12pt through the document default" in str(odd)


def test_the_based_on_chain_is_followed():
    """A style that states no size inherits one from its parent, and
    stopping at the first style would report the note as unresolved."""
    xml = part(note(2, run("a", SZ10)), note(3, run("b", SZ10)),
               styled_note(4, "styled", "NoteTight"))
    report = footnotes.sizes(xml, styles_xml=styles(
        style("NoteTight", based_on="FootnoteText"),
        style("FootnoteText", sz="20")))
    assert report.ok, report.format()


def test_a_based_on_cycle_does_not_hang():
    """Real files carry them."""
    xml = part(note(2, run("a", SZ10)), note(3, run("b", SZ10)),
               styled_note(4, "styled", "A"))
    report = footnotes.sizes(xml, styles_xml=styles(
        style("A", based_on="B"), style("B", based_on="A")))
    assert [o.id for o in report.outliers] == ["4"]


def test_without_the_styles_the_disagreement_is_still_reported():
    """The answer is genuinely not in footnotes.xml, and saying nothing
    would be a claim this cannot support."""
    xml = part(note(2, run("a", SZ10)), note(3, run("b", SZ10)),
               styled_note(4, "styled", "FootnoteText"))
    (odd,) = footnotes.sizes(xml).outliers
    assert odd.stated == (None,) and "states no size" in str(odd)


def test_a_half_point_size_is_reported_as_a_half_point():
    """Word records half-points, so 21 is 10.5pt. Reported with integer
    division it reads 10pt — a size that is wrong by half a point and
    looks like a clean number, which is the hardest kind to notice."""
    house, odd_one = '<w:sz w:val="21"/>', '<w:sz w:val="25"/>'
    report = footnotes.sizes(part(note(2, run("a", house)),
                                  note(3, run("b", house)),
                                  note(4, run("c", odd_one))))
    # BOTH sides have to carry an odd value: the house size and the
    # outlier are rendered by different code, and a test where either
    # halves evenly cannot tell `/ 2` from `// 2` there
    assert "house size 10.5pt" in report.format()
    (odd,) = report.outliers
    assert "12.5pt" in str(odd)


def test_the_audit_reports_a_half_point_face_size_too():
    seen = footnotes.fonts(part(note(2, run("x", '<w:sz w:val="21"/>'))))
    assert seen == {"inherited face 10.5pt": 1}


def test_the_report_prints_the_house_size_and_the_count():
    line = footnotes.sizes(part(note(2, run("a", SZ10)),
                                note(3, run("b", SZ10)),
                                note(4, run("c")))).format()
    assert "3 footnote(s), house size 10pt, 1 disagreeing" in line


# ------------------------------------------------- the primitive underneath

def test_set_run_property_gives_a_bare_run_its_properties():
    out = set_run_property("<w:r><w:t>x</w:t></w:r>", "b", "<w:b/>")
    assert out == "<w:r><w:rPr><w:b/></w:rPr><w:t>x</w:t></w:r>"


def test_set_run_property_removes_with_an_empty_element():
    styled = '<w:r><w:rPr><w:b/><w:i/></w:rPr><w:t>x</w:t></w:r>'
    assert set_run_property(styled, "b", "") == (
        '<w:r><w:rPr><w:i/></w:rPr><w:t>x</w:t></w:r>')


def test_set_run_property_leaves_a_non_run_alone():
    """Callers hand it whatever a run regex matched; a fragment that is
    not a run must come back unchanged rather than grow a stray rPr."""
    assert set_run_property("<w:bookmarkStart/>", "b", "<w:b/>") == (
        "<w:bookmarkStart/>")


def test_a_mark_whose_size_does_not_resolve_is_not_judged():
    """Read without styles.xml nothing resolves, and calling that a
    disagreement would put every document read without the part on the
    list. One mark states a size, the other inherits — and inheriting
    is not a finding until something can say what it inherits."""
    stated = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
              f'{SZ10}</w:rPr><w:footnoteRef/></w:r>')
    report = footnotes.sizes(part(note(2, stated + run("a", SZ10)),
                                  note(3, MARK + run("b", SZ10))))
    assert report.mark_house == 20
    assert report.mark_outliers == [], report.format()
    assert report.ok


def test_the_size_audit_skips_an_equation_run_in_a_LATER_paragraph():
    """The offset asked of the math spans is the run's position in the
    NOTE, not in its paragraph — `para.start() + r.start()`. With a
    single short paragraph the two are close enough that most ways of
    getting it wrong still land outside the span; with the equation in
    the second paragraph of the note they do not, and a 12pt Cambria
    Math run then reads as a footnote set in the wrong size."""
    long_first = run("A first paragraph long enough to move the offsets "
                     "well past anything the second one could reach.",
                     SZ10)
    second = MATH_WITH_A_TEXT_RUN + run(" and prose after it.", SZ10)

    two_paragraphs = long_first + "</w:p><w:p>" + second
    report = footnotes.sizes(part(
        note(2, two_paragraphs),
        note(3, run("an ordinary note", SZ10))))

    assert report.ok, [str(o) for o in report.outliers]
    assert report.house == 20


def test_the_run_IMMEDIATELY_after_an_equation_is_still_sized():
    """The span is half-open: a run starting exactly where the equation
    ends is outside it. Read as closed, the first run after every
    display equation drops out of the audit — and that is where a
    footnote's prose usually resumes."""
    odd = MATH_WITH_A_TEXT_RUN + run("resumes at the wrong size", SZ12)

    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, odd)))

    assert not report.ok
    assert [o.id for o in report.outliers] == ["4"]
    assert "12pt" in str(report.outliers[0])


# --- what the footnotes run of 2026-08-18 found -------------------------
#
# 15 survivors in `SizeReport.format`, and ten of them on the ONE
# expression that turns the marks' house size from half-points into
# points. The body half of the same line is asserted twice over,
# half-point included; the mark half was only ever checked for the words
# "reference marks", so `/ 2` could be `// 2`, `+ 2`, `& 2` or `>> 2`
# and every test still passed.


def _mark(sz: str = "") -> str:
    return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
            f'{sz}</w:rPr><w:footnoteRef/></w:r>')


def test_the_MARK_house_size_is_printed_in_points_and_halves():
    """Word records half-points. The marks' line is the one a paper acts
    on — `set_font` writes the body, and a mark that disagrees is
    usually a paragraph that lost its style — so the number in it has to
    be the number to type. 21 half-points is 10.5pt, and every mutant of
    the arithmetic prints something that looks like a size."""
    house, odd = '<w:sz w:val="21"/>', '<w:sz w:val="25"/>'
    report = footnotes.sizes(part(
        note(2, _mark(house) + run("a", house)),
        note(3, _mark(house) + run("b", house)),
        note(4, _mark(odd) + run("c", house))))

    line = report.format()

    assert "reference marks: house 10.5pt" in line
    assert "1 disagreeing" in line


def test_the_marks_line_says_the_house_came_from_a_STYLE():
    """Which is a claim about confidence: a styled mark is well-formed
    however few of them there are, and that sentence is what stops a
    paper acting on the majority — the Parental Style report was exactly
    backwards, and flagged the two correct notes."""
    styles = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr>'
              '<w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:styleId="FootnoteText">'
              f'<w:rPr>{SZ10}</w:rPr></w:style></w:styles>')

    def styled(nid: int) -> str:
        return (f'<w:footnote w:id="{nid}"><w:p><w:pPr><w:pStyle '
                f'w:val="FootnoteText"/></w:pPr>{MARK}{run("a", SZ10)}'
                "</w:p></w:footnote>")

    bare = (f'<w:footnote w:id="9"><w:p>{MARK}{run("b", SZ10)}'
            "</w:p></w:footnote>")

    line = footnotes.sizes(part(styled(2), bare), styles_xml=styles).format()

    assert "reference marks: house 10pt" in line
    assert "resolve through a STYLE" in line
    assert "commonest value" not in line


def test_the_marks_line_says_when_it_is_only_a_MAJORITY():
    """No mark in the document resolves through a style, so there is
    nothing better to go on than the count — and the report says so
    rather than letting a majority read as a standard."""
    house, odd = '<w:sz w:val="20"/>', '<w:sz w:val="24"/>'
    report = footnotes.sizes(part(
        note(2, _mark(house) + run("a", house)),
        note(3, _mark(house) + run("b", house)),
        note(4, _mark(odd) + run("c", house))))

    line = report.format()

    assert "reference marks: house 10pt" in line
    assert "commonest value" in line
    assert "resolve through a STYLE" not in line


def test_a_report_BUILT_BY_HAND_prints_rather_than_raising():
    """`SizeReport` is a public dataclass and `format()` a public method.
    Through `sizes()` the mark house is never None while there are mark
    outliers — the two mutants in that arm are unreachable that way, and
    the arm stays for this: an `assert` in its place raised for a caller
    that filled the list itself, and under `python -O` it was stripped
    and left `None / 2`."""
    report = footnotes.SizeReport()
    report.mark_outliers = [footnotes.SizeOutlier("2 (reference mark)",
                                                  (24,), "x", "direct")]

    line = report.format()

    assert "reference marks: house none stated" in line
    assert "1 disagreeing" in line


# --- the size walk, note by note (2026-08-19) --------------------------
#
# footnotes measured at 7.8 % with 16 of its 31 survivors inside
# `sizes`. Every one of them is a `continue` in the run walk or a term
# in the vote that decides the house size — and every fixture above has
# ONE run per note, so a walk that stopped early would look exactly like
# one that carried on.

_LONG = ("The normalisation is by the sample mean rather than by the "
         "base year, so the two panels are comparable throughout.")


def test_an_outlier_names_its_note_in_forty_eight_characters():
    """The finding is read next to the document and the text is how a
    person finds the note — the id alone is Word's numbering, which the
    next save changes."""
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, run(_LONG, SZ12))))

    (odd,) = report.outliers
    assert odd.text == "The normalisation is by the sample mean rather t"
    assert len(odd.text) == 48


def test_a_note_whose_MARK_comes_first_still_has_its_text_sized():
    """`continue`, not `break`, after the reference mark. Word writes
    the mark as the first run of the note, so under `break` no footnote
    in a real document would ever be sized — every one of them would
    stop at its own first run."""
    marked = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
              "<w:footnoteRef/></w:r>")
    report = footnotes.sizes(part(note(2, marked + run("a", SZ10)),
                                  note(3, marked + run("b", SZ10)),
                                  note(4, marked + run("c", SZ12))))

    assert report.counted == 3
    assert [o.id for o in report.outliers] == ["4"]


def test_an_EMPTY_run_does_not_end_the_note_either():
    """The other `continue`. A run holding a space, or nothing at all,
    is what an edit leaves behind — and the size that disagrees is
    routinely in the run after it."""
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, run(" ", SZ10) + run("c", SZ12))))

    (odd,) = report.outliers
    assert odd.id == "4"
    assert odd.stated == (24,), "the empty run states 10pt and is skipped"


def test_a_note_with_NOTHING_VISIBLE_does_not_end_the_walk():
    """`if not seen: continue` — a note holding only its mark says
    nothing about sizes, and the notes after it still do. Under `break`
    a single separator-shaped note early in the part hides every finding
    below it."""
    marked = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
              "<w:footnoteRef/></w:r>")
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, marked),
                                  note(5, run("c", SZ12))))

    assert [o.id for o in report.outliers] == ["5"]


def test_a_MIXED_note_does_not_vote_for_the_house_size():
    """`len(s) == 1`: a note that states two sizes is the finding, not
    the evidence. Under `>=` its first size joins the vote, and with two
    of them it wins — so the house becomes the size the broken notes
    share and every correct note is reported as an outlier."""
    # both of the mixed note's sizes are LARGER than the good one's, so
    # its smallest — the value `s[0]` a wrong filter would let vote — is
    # not the house value. With the two overlapping, the vote is the
    # same either way and the mutant is invisible.
    sz14 = '<w:sz w:val="28"/>'
    mixed = run("c", SZ12) + run("d", sz14)
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, mixed),
                                  note(4, mixed)))

    assert report.house == 20, "the one note that states a single size"
    assert [o.id for o in report.outliers] == ["3", "4"]


def test_the_notes_that_state_NOTHING_do_not_vote_either():
    """`and s[0] is not None`: a silent note inherits, and there is no
    value in it to count. Under `or` the Nones join the vote and win,
    and the house size becomes "no size at all"."""
    report = footnotes.sizes(part(note(2, run("a")),
                                  note(3, run("b")),
                                  note(4, run("c", SZ10))))

    assert report.house == 20
    assert sorted(o.id for o in report.outliers) == ["2", "3"]


def test_a_mark_finding_names_its_note_in_forty_eight_characters_too():
    """The mark half of the report carries the same 48-character
    extract, written on its own line of the source and read by nothing
    — and a mark finding is the harder one to place by hand, because
    the mark itself is a number Word renumbers."""
    def mark(sz: str) -> str:
        return ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/>'
                f'{sz}</w:rPr><w:footnoteRef/></w:r>')

    report = footnotes.sizes(part(note(2, mark(SZ10) + run("a", SZ10)),
                                  note(3, mark(SZ10) + run("b", SZ10)),
                                  note(4, mark(SZ12) + run(_LONG, SZ10))))

    (found,) = report.mark_outliers
    assert found.text == "The normalisation is by the sample mean rather t"
    assert len(found.text) == 48


# --- definitions stored out of REFERENCE order -------------------------


def _notes_part(*ids: int) -> str:
    return ("<w:footnotes>" + "".join(
        f'<w:footnote w:id="{i}"><w:p><w:r><w:t>note {i}</w:t></w:r></w:p>'
        f"</w:footnote>" for i in ids) + "</w:footnotes>")


def _refs(*ids: int) -> str:
    return ("<w:document><w:body>" + "".join(
        f'<w:p><w:r><w:t>Sentence.</w:t></w:r>'
        f'<w:r><w:footnoteReference w:id="{i}"/></w:r></w:p>'
        for i in ids) + "</w:body></w:document>")


def test_out_of_order_answers_nothing_for_a_file_word_wrote():
    from docxkit.footnotes import out_of_order

    assert out_of_order(_refs(2, 3, 4), _notes_part(2, 3, 4)) == []


def test_out_of_order_names_every_id_that_would_MOVE():
    """A note appended to the END of the part with its reference in the
    middle — the AFI shape. Word renders it correctly and Compare
    rewrites the definitions into document order, so three of the four
    move, and the answer names all three rather than the smallest set
    that could be reordered: a caller reporting this quotes them."""
    from docxkit.footnotes import out_of_order

    moved = out_of_order(_refs(2, 5, 3, 4), _notes_part(2, 3, 4, 5))

    assert moved == ["3", "4", "5"]


def test_out_of_order_ignores_a_definition_NOTHING_references():
    """A note whose marker was deleted is a different defect, and
    counting it here would fire the order line on documents whose order
    is right."""
    from docxkit.footnotes import out_of_order

    assert out_of_order(_refs(2, 3), _notes_part(2, 3, 9)) == []


def test_out_of_order_ignores_a_reference_with_NO_definition():
    """The other half of the same asymmetry: this function answers one
    question."""
    from docxkit.footnotes import out_of_order

    assert out_of_order(_refs(2, 7, 3), _notes_part(2, 3)) == []


def test_out_of_order_reads_ENDNOTES_the_same_way():
    """An endnote is a footnote at the back of the paper, and Compare
    reorders that part too."""
    from docxkit.footnotes import out_of_order

    notes = ("<w:endnotes>" + "".join(
        f'<w:endnote w:id="{i}"><w:p><w:r><w:t>note {i}</w:t></w:r></w:p>'
        f"</w:endnote>" for i in (2, 3)) + "</w:endnotes>")
    doc = ("<w:document><w:body>" + "".join(
        f'<w:p><w:r><w:endnoteReference w:id="{i}"/></w:r></w:p>'
        for i in (3, 2)) + "</w:body></w:document>")

    assert out_of_order(doc, notes, kind="endnote") == ["2", "3"]


def test_out_of_order_skips_words_own_separator_notes():
    """Ids 0 and -1 are the separator and continuation notes Word puts
    in every document, referenced by nothing in the body."""
    from docxkit.footnotes import out_of_order

    notes = ('<w:footnotes><w:footnote w:id="-1"><w:p/></w:footnote>'
             '<w:footnote w:id="0"><w:p/></w:footnote>'
             + _notes_part(2, 3)[len("<w:footnotes>"):])

    assert out_of_order(_refs(2, 3), notes) == []


# --- creating a note and its reference as a PAIR -----------------------
#
# What a paper hand-rolled, and the reason the entry above exists: an
# appended definition renders correctly and costs the NEXT batch.


def _package(*, on: dict[int, int] | None = None) -> dict[str, bytes]:
    """Three sentences; `on` says which of them carries which note.

    The MIDDLE one is left bare by default, because a note added to a
    paragraph that already has one lands after it, and that says
    nothing about where the definition went.
    """
    on = {1: 2, 3: 3} if on is None else on
    part = ('<w:footnotes><w:footnote w:id="-1"><w:p/></w:footnote>'
            + "".join(f'<w:footnote w:id="{i}"><w:p><w:r><w:t>note {i}'
                      f"</w:t></w:r></w:p></w:footnote>"
                      for i in sorted(on.values()))
            + "</w:footnotes>")
    body = "".join(
        f"<w:p><w:r><w:t>Sentence {n}.</w:t></w:r>"
        + (f'<w:r><w:footnoteReference w:id="{on[n]}"/></w:r>'
           if n in on else "")
        + "</w:p>" for n in (1, 2, 3))
    return {"word/document.xml":
            f"<w:document><w:body>{body}</w:body></w:document>".encode(),
            "word/footnotes.xml": part.encode()}


def _order(parts: dict[str, bytes]) -> tuple[list[str], list[str]]:
    doc = parts["word/document.xml"].decode("utf-8")
    notes = parts["word/footnotes.xml"].decode("utf-8")
    return (re.findall(r'footnoteReference w:id="(\d+)"', doc),
            [f.id for f in footnotes.find_all(notes)])


def test_add_writes_the_definition_in_REFERENCE_order():
    """The whole point. A note whose reference lands in the middle of
    the body gets its definition in the middle of the part, so the file
    is one Word could have written — and `out_of_order` says so."""
    from docxkit.footnotes import add, out_of_order

    parts = _package()

    new = add(parts, after="Sentence 2.", text="A new note.")

    assert new == "4", "one past the highest id the part held"
    refs, defs = _order(parts)
    assert refs == ["2", "4", "3"]
    assert defs == ["2", "4", "3"]
    assert out_of_order(parts["word/document.xml"].decode("utf-8"),
                        parts["word/footnotes.xml"].decode("utf-8")) == []


def test_add_puts_a_FIRST_note_before_every_other_definition():
    """The branch with no note in front of it: the definition goes at
    the head of the part, not at its end."""
    from docxkit.footnotes import add, out_of_order

    parts = _package(on={2: 2, 3: 3})

    add(parts, after="Sentence 1.", text="Now the first.")

    refs, defs = _order(parts)
    assert refs == ["4", "2", "3"] and defs == ["4", "2", "3"]
    assert out_of_order(parts["word/document.xml"].decode("utf-8"),
                        parts["word/footnotes.xml"].decode("utf-8")) == []


def test_the_new_note_carries_its_TEXT_and_the_reference_mark():
    """A footnote's first run is the mark Word renders as the number —
    `w:footnoteRef` — and the text follows it after a space, which is
    what Word writes when a person types one."""
    from docxkit.footnotes import add, find

    parts = _package()
    add(parts, after="Sentence 2.", text="Data are from Eurostat (2023).")

    note = find(parts["word/footnotes.xml"].decode("utf-8"), "Eurostat")
    assert "<w:footnoteRef/>" in note.xml
    assert note.text == "Data are from Eurostat (2023)."
    assert 'w:rStyle w:val="FootnoteReference"' in note.xml


def test_the_reference_lands_where_the_anchor_ENDS():
    """Immediately behind the anchor text, which is where a note
    marker goes — a marker before the full stop reads as belonging to
    the next sentence."""
    from docxkit.footnotes import add

    parts = _package(on={})
    add(parts, after="Sentence 2.", text="A note.")

    doc = parts["word/document.xml"].decode("utf-8")
    (para_xml,) = [p for p in re.findall(r"<w:p>.*?</w:p>", doc, re.DOTALL)
                   if "Sentence 2." in p]
    assert para_xml.index("Sentence 2.") < para_xml.index("footnoteReference")
    from docxkit._xml import visible_text
    assert visible_text(para_xml) == "Sentence 2."


def test_the_text_is_ESCAPED_into_the_part():
    from docxkit.footnotes import add, find

    parts = _package()
    add(parts, after="Sentence 2.", text="R&D spending < 3% of GDP")

    part = parts["word/footnotes.xml"].decode("utf-8")
    assert "R&amp;D" in part and "&lt; 3%" in part
    assert find(part, "R&D").text == "R&D spending < 3% of GDP"


def test_add_refuses_a_package_with_NO_footnote_part():
    """The scaffold Word writes for its first note is not built here,
    and inventing half of one is how a package comes back unreadable."""
    from docxkit.errors import AnchorError
    from docxkit.footnotes import add

    parts = {"word/document.xml":
             b"<w:document><w:body><w:p><w:r><w:t>Only.</w:t></w:r>"
             b"</w:p></w:body></w:document>"}

    with pytest.raises(AnchorError, match="never held a footnote"):
        add(parts, after="Only.", text="x")


def test_a_note_added_to_a_part_of_SEPARATORS_ONLY_gets_a_real_id():
    """Word's separator notes are -1 and 0, so "one past the highest"
    over a part that holds only those answers 0 — the id of the
    separator line itself, which is what a reference to it renders as.
    A paper with a footnote scaffold and no footnotes yet is the
    ordinary shape of a first note."""
    from docxkit.footnotes import add, find_all

    parts = _package(on={})

    new = add(parts, after="Sentence 2.", text="The first note.")

    assert new == "1"
    part = parts["word/footnotes.xml"].decode("utf-8")
    assert [f.id for f in find_all(part)] == ["1"]
    assert 'w:id="1"' in parts["word/document.xml"].decode("utf-8")


def test_add_finds_the_predecessor_when_the_new_note_is_THIRD():
    """`order[order.index(new_id) - 1]`. With the new note first or
    second, the index arithmetic agrees with every bitwise spelling of
    itself — `1 - 1`, `1 % 1`, `1 >> 1` and `1 ^ 1` are all 0 — so the
    two fixtures above cannot tell them apart. Both later positions are
    checked because they part from DIFFERENT spellings: at the third the
    modulus and the xor go wrong, at the fourth the shift does. A
    manuscript's notes are rarely two.
    """
    from docxkit.footnotes import add, out_of_order

    for anchor, want in (("Sentence 2.", ["2", "3", "6", "5"]),
                         ("Sentence 3.", ["2", "3", "5", "6"])):
        parts = _package(on={1: 2, 2: 3, 3: 5})

        add(parts, after=anchor, text="A note.")

        refs, defs = _order(parts)
        assert refs == want, (anchor, refs)
        assert defs == refs, (anchor, defs)
        assert out_of_order(parts["word/document.xml"].decode("utf-8"),
                            parts["word/footnotes.xml"].decode(
                                "utf-8")) == []


def test_the_FIRST_real_note_in_a_part_of_separators_lands_INSIDE_it():
    """The other arm of the same branch: no note to sit after and none
    to sit in front of, so the definition goes at the end of the part —
    which is the end MINUS the closing tag. Landing after it puts the
    footnote outside `w:footnotes` altogether, and Word repairs the file
    by dropping it.
    """
    from docxkit.footnotes import add, find

    parts = _package(on={})
    parts["word/footnotes.xml"] = (
        b'<w:footnotes><w:footnote w:id="-1"><w:p/></w:footnote>'
        b'<w:footnote w:id="0"><w:p/></w:footnote></w:footnotes>')

    add(parts, after="Sentence 2.", text="The very first note.")

    notes = parts["word/footnotes.xml"].decode("utf-8")
    assert notes.endswith("</w:footnotes>"), notes[-60:]
    assert notes.count("</w:footnotes>") == 1
    assert find(notes, "very first").text == "The very first note."


# --- the whole sweep of 2026-09-15 ------------------------------------
#
# 97 real survivors, and more than half of them in `orphans` and
# `prune_orphans`: their tests live in test_note_orphans.py, which the
# footnotes harness does not run, so every mutant of the reader and the
# pruner lived here. Most of the rest are fixtures one shape short —
# one-digit ids, where two regex matches share a cached string; an
# anchor at offset 0, where `+` and `^` agree; an equation with nothing
# on its far side.


#: Word's separator and continuation notes, as every document carries
#: them: referenced by nothing, and never orphans.
_SEPARATORS = ('<w:footnote w:id="-1"><w:p><w:r><w:continuationSeparator/>'
               '</w:r></w:p></w:footnote><w:footnote w:id="0"><w:p><w:r>'
               "<w:separator/></w:r></w:p></w:footnote>")


def _definition(nid: int, words: str = "", *, kind: str = "footnote",
                extra: str = "") -> str:
    """A note definition as Word writes one: the mark, then the words.

    With no `words` it is a SHELL — what an XML accept leaves of a note
    whose reference was deleted.
    """
    said = f"<w:r><w:t>{words}</w:t></w:r>" if words else ""
    return (f'<w:{kind} w:id="{nid}"><w:p><w:r><w:{kind}Ref/></w:r>'
            f"{said}{extra}</w:p></w:{kind}>")


def _paper(refs: tuple[int, ...], *definitions: str,
           kind: str = "footnote", prose: str = "") -> dict[str, bytes]:
    """A body referencing `refs` in order, then `prose` as one bare
    paragraph; and a notes part of the separators and `definitions`."""
    body = "".join(f"<w:p><w:r><w:t>Claim {i}.</w:t></w:r>"
                   f'<w:r><w:{kind}Reference w:id="{i}"/></w:r></w:p>'
                   for i in refs)
    if prose:
        body += (f'<w:p><w:r><w:t xml:space="preserve">{prose}</w:t>'
                 "</w:r></w:p>")
    head = _SEPARATORS.replace("footnote", kind)
    return {
        "word/document.xml":
            f"<w:document {NS}><w:body>{body}</w:body></w:document>".encode(),
        f"word/{kind}s.xml": (f"<w:{kind}s {NS}>{head}"
                              f"{''.join(definitions)}</w:{kind}s>").encode()}


def test_orphans_names_the_definition_NO_REFERENCE_points_at():
    """The reader itself, which this harness had never called. Every
    wrong spelling of the part choice, of the loop over the two kinds
    and of the missing-part skip answers `[]` here or raises: a footnote
    looked for in the endnotes part is not there, and a missing part
    decoded is an AttributeError. `empty` is asserted as the very
    `False`, because a property that lost its decorator is a bound
    method, and a method is truthy."""
    parts = _paper((2,), _definition(2, "Kept."),
                   _definition(3, "Lost its marker."))

    found = footnotes.orphans(parts)

    assert found == [footnotes.Orphan("footnote", "3", "Lost its marker.", 0)]
    assert found[0].empty is False


@pytest.mark.parametrize("words,carriers,empty,said", [
    ("", 0, True, "footnote 3 (empty)"),
    ("Lost its marker.", 0, False, "footnote 3 (holds 'Lost its marker.')"),
    ("", 1, False, "footnote 3 (holds no words, and 1 other item)"),
    ("", 2, False, "footnote 3 (holds no words, and 2 other items)"),
    ("A link, and words.", 1, False,
     "footnote 3 (holds 'A link, and words.')"),
])
def test_an_orphan_is_EMPTY_only_with_no_words_AND_no_carriers(
        words, carriers, empty, said):
    """`not text and not carriers`, and either half alone is wrong: a
    definition holding only a bookmark has nothing to read and a link
    still points at it, and one holding words is the real loss the
    pruner leaves for its caller. All four corners, because each mutant
    of the expression is right on some of them. The string says `empty`
    for the shell alone — the word a refusal prints."""
    orphan = footnotes.Orphan("footnote", "3", words, carriers)

    assert orphan.empty is empty
    assert str(orphan) == said


def test_an_ENDNOTES_ONLY_paper_is_read_and_its_shell_pruned():
    """A journal that sets endnotes has no footnotes part at all, so the
    reader's first kind finds nothing, and `continue` there is what
    reaches the second — under `break` the whole paper has no orphans.
    The pruner then has to write to the endnotes part: a kind test that
    sends an endnote to `word/footnotes.xml` asks for a part that is not
    there."""
    parts = _paper((2,), _definition(2, "Kept.", kind="endnote"),
                   _definition(3, kind="endnote"), kind="endnote")
    shell = footnotes.Orphan("endnote", "3", "", 0)

    assert "word/footnotes.xml" not in parts
    assert footnotes.orphans(parts) == [shell]
    assert footnotes.prune_orphans(parts) == [shell]
    left = parts["word/endnotes.xml"].decode("utf-8")
    assert [n.id for n in footnotes.find_all(left, kind="endnote")] == ["2"]


def test_a_definition_cannot_vouch_for_ITSELF():
    """Only the OTHER parts are searched for references. Reading the
    notes part as well — which `or` does, and `is not` does too, since a
    package's key is never the very string `_xml` holds — lets a shell
    whose one run names its own id keep itself, and the pruner never
    takes it."""
    selfish = _definition(
        3, extra='<w:r><w:footnoteReference w:id="3"/></w:r>')
    parts = _paper((2,), _definition(2, "Kept."), selfish)

    (orphan,) = footnotes.orphans(parts)

    assert (orphan.id, orphan.empty) == ("3", True)
    assert footnotes.prune_orphans(parts) == [orphan]


def test_the_package_MEDIA_is_never_decoded_for_references():
    """Only `.xml` parts are read. A package carries images, and under
    `or` the name test admits every one of them — a PNG is not UTF-8."""
    parts = _paper((2,), _definition(2, "Kept."))
    parts["word/media/image1.png"] = b"\x89PNG\r\n\x1a\n\x00\x00"

    assert footnotes.orphans(parts) == []


def test_a_KIND_built_at_run_time_reads_the_footnotes_part():
    """`kind` is compared with `==`, not `is`. A kind that arrives from a
    command line or a config file is a string made at run time, not the
    interned literal, and under `is` it reads the endnotes part."""
    parts = _paper((2,), _definition(2, "Kept."), _definition(3, "Lost."))

    kind = "".join(["foot", "note"])

    assert [o.id for o in footnotes.orphans(parts, kind=kind)] == ["3"]


def test_prune_takes_the_SHELL_and_leaves_every_other_definition_whole():
    """The shell is found by EQUAL id, and the fixture is built so that
    every other comparison picks a different note: a lower id (10) and a
    higher one (15) stand in front of the shell (12), and the ids have
    two digits, because two regex matches of a one-digit id are the same
    cached string and `is` would agree with `==`. An orphan WITH words
    (11) comes first, so a `break` where the pruner passes it stops
    before the shell. The part is compared whole: the shell's bytes, and
    only those, are gone."""
    kept = (_definition(10, "Referenced."),
            _definition(11, "Lost its marker."),
            _definition(15, "Referenced as well."))
    parts = _paper((10, 15), *kept, _definition(12))
    want = _paper((10, 15), *kept)["word/footnotes.xml"]

    gone = footnotes.prune_orphans(parts)

    assert gone == [footnotes.Orphan("footnote", "12", "", 0)]
    assert parts["word/footnotes.xml"] == want


def test_two_SHELLS_on_one_id_both_go_and_the_part_still_parses():
    """`break` after the cut, not `continue`: the notes were located in
    the part as it stood BEFORE the cut, so every offset after it is
    stale. A second definition on the same id — what a raw splice
    leaves, since Word renumbers ids on save — is then cut at the wrong
    place, and the part loses its closing tag."""
    parts = _paper((10,), _definition(10, "Referenced."), _definition(12),
                   _definition(12))
    want = _paper((10,), _definition(10, "Referenced."))["word/footnotes.xml"]

    gone = footnotes.prune_orphans(parts)

    assert gone == [footnotes.Orphan("footnote", "12", "", 0)] * 2
    assert parts["word/footnotes.xml"] == want
    assert parses(parts["word/footnotes.xml"].decode("utf-8"))


def test_the_reference_follows_an_anchor_in_the_MIDDLE_of_its_paragraph():
    """`index + len`, and every fixture above anchors at offset 0, where
    `^` and `|` agree with `+`. Here the anchor starts at 15 and is 17
    long: 32 is its end, while 30 and 31 put the marker inside `show.`,
    in front of its last letter or of the full stop it belongs after."""
    parts = _paper(
        (), prose="Growth slowed, as the data show. Prices did not.")

    new = footnotes.add(parts, after="as the data show.", text="Eurostat.")

    from docxkit._xml import visible_text
    doc = parts["word/document.xml"].decode("utf-8")
    before, after = doc.split(f'<w:footnoteReference w:id="{new}"/>')
    assert visible_text(before) == "Growth slowed, as the data show."
    assert visible_text(after) == " Prices did not."


def test_a_FIRST_note_is_stored_AFTER_the_separator_notes():
    """With no real note in the part the definition goes at its end,
    which is the end MINUS the closing tag. Every other spelling of that
    subtraction by the tag's length (`%`, `&`, `//`, `>>`) answers a far
    smaller number, which lands in front of the separators or inside the
    root's opening tag. The earlier test of this branch asked only that
    the note be found and the part closed, and a note written inside a
    bare `<w:footnotes>` tag passes both."""
    parts = _paper((), prose="The first sentence to carry a note.")

    footnotes.add(parts, after="carry a note.", text="The first note.")

    notes_xml = parts["word/footnotes.xml"].decode("utf-8")
    assert [f.id for f in footnotes.find_all(
        notes_xml, include_reserved=True)] == ["-1", "0", "1"]
    assert parses(notes_xml)


def test_add_finds_its_predecessor_by_EQUAL_id_not_by_where_ids_sort():
    """The LI7 shape: a restored note took a free id, 15, while its
    reference sits in front of 12's, so a part in reference order stores
    15 before 12. The new note goes after 12. The first note at or past
    "12" as a STRING is 15, which is where `>=` puts it; and with two
    digits no two regex matches are one cached string, so `is` finds no
    predecessor at all."""
    parts = _paper((15, 12), _definition(15, "Restored."),
                   _definition(12, "Original."), prose="A third claim.")

    new = footnotes.add(parts, after="A third claim.", text="A new note.")

    assert new == "16"
    refs, defs = _order(parts)
    assert refs == defs == ["15", "12", "16"]


def test_out_of_order_places_a_note_by_its_FIRST_reference():
    """A note whose reference appears twice in the body is placed where
    it first appears, and counted once. Under `or` the second appearance
    is counted again, the two lists no longer pair up, and the strict
    zip raises on a document whose order is right."""
    assert footnotes.out_of_order(_refs(2, 3, 2), _notes_part(2, 3)) == []


def test_out_of_order_REFUSES_a_part_that_defines_one_id_TWICE():
    """The two lists are zipped STRICTLY. A doubled definition makes the
    stored side one longer, and a zip that stopped at the shorter would
    answer `[]` — "in reference order" — for a part that is not a
    well-formed notes part at all.

    The refusal is caught by PAIR, not by `ValueError` alone: what this
    test is for is that a doubled definition is refused, and the toolkit's
    own `DocxKitError` is not a `ValueError`, so naming one type here
    would make a friendlier refusal a failing test. `revision status` and
    `revision build` call this uncaught, so today the reader meets zip's
    own words."""
    from docxkit.errors import DocxKitError

    with pytest.raises((ValueError, DocxKitError)):
        footnotes.out_of_order(_refs(2, 3), _notes_part(2, 3, 3))


def _notes_part_of(kind: str, *ids: int) -> str:
    """`_notes_part` for either kind — the endnotes part is the same
    shape under a different name, and the refusal has to name the one it
    actually read."""
    return (f"<w:{kind}s>" + "".join(
        f'<w:{kind} w:id="{i}"><w:p><w:r><w:t>note {i}</w:t></w:r></w:p>'
        f"</w:{kind}>" for i in ids) + f"</w:{kind}s>")


def _refs_of(kind: str, *ids: int) -> str:
    return ("<w:document><w:body>" + "".join(
        f'<w:p><w:r><w:{kind}Reference w:id="{i}"/></w:r></w:p>'
        for i in ids) + "</w:body></w:document>")


@pytest.mark.parametrize("kind,part", [("footnote", "word/footnotes.xml"),
                                       ("endnote", "word/endnotes.xml")])
def test_out_of_order_NAMES_the_doubled_id_and_its_PART(kind, part):
    """The refusal above, as the author meets it.

    `revision status` and `revision build` call this uncaught, so what a
    person asking for a status was handed is zip's own sentence — "zip()
    argument 2 is shorter than argument 1" — a message about an ARCHIVE,
    naming neither the note to fix nor the file to open it in. The CLI
    prints a `DocxKitError` as a clean line and lets everything else
    traceback, so the refusal has to be one, and it has to say WHICH id
    and WHICH part: a manuscript's notes part holds hundreds, and
    "somewhere in this document" is not an instruction.
    """
    from docxkit.errors import DocxKitError

    with pytest.raises(DocxKitError) as caught:
        footnotes.out_of_order(_refs_of(kind, 2, 3),
                               _notes_part_of(kind, 2, 3, 3), kind=kind)

    said = str(caught.value)
    assert f"{kind} 3" in said, said
    assert part in said, said


def test_out_of_order_compares_TWO_DIGIT_ids_by_value():
    """Every fixture above used ids under 10, and two regex matches of a
    one-character id are the same cached string, so `is not` agreed with
    `!=`. From 10 up each match is its own string, and under `is not` a
    part in perfect order names every note as moved."""
    assert footnotes.out_of_order(_refs(10, 11, 12),
                                  _notes_part(10, 11, 12)) == []


def test_the_font_audit_leaves_the_SEPARATOR_notes_out_by_default():
    """As `set_font` does: ids 0 and -1 are Word's furniture, and each
    one's run states nothing, so counting them would add two "inherited"
    runs to every document's tally."""
    xml = part(_SEPARATORS, note(2, run("x", SZ10)))

    assert footnotes.fonts(xml) == {"inherited face 10pt": 1}
    assert footnotes.fonts(xml, include_reserved=True) == {
        "inherited face 10pt": 1, "inherited": 2}


def test_the_font_audit_goes_on_PAST_an_equation():
    """`continue` after the skip, not `break`: the earlier fixture put
    the equation LAST, where stopping and carrying on look the same."""
    seen = footnotes.fonts(part(note(2, MATH_WITH_A_TEXT_RUN
                                     + run("after", SZ10))))

    assert seen == {"inherited face 10pt": 1}


def test_the_font_report_compares_as_a_WHOLE():
    """A dataclass: built from its fields and compared by them. Without
    the decorator it takes no arguments and equals only itself."""
    _, rep = footnotes.set_font(part(note(2, run("a")
                                          + MATH_WITH_A_TEXT_RUN)))

    assert rep == footnotes.FontReport(notes=1, runs_set=1,
                                       math_runs_skipped=1)


def test_a_report_BUILT_BY_HAND_counts_nothing_until_it_is_told():
    """The head line of an empty report, whole. `counted` is filled in by
    `sizes()`, and a caller that builds the report itself has counted
    zero footnotes, not one and not minus one."""
    assert footnotes.SizeReport().format() == (
        "0 footnote(s), house size none stated, 0 disagreeing")


def test_a_house_source_READ_BACK_as_text_still_says_STYLE():
    """`==`, not `is`. Through `sizes()` the word is the interned literal
    `_judge_marks` assigns, and identity happens to agree; a report
    rebuilt from a saved one holds the same word as a string made at run
    time, and under `is` a styled house reads as "the commonest
    value"."""
    report = footnotes.SizeReport(mark_house=20,
                                  mark_house_from="".join(["sty", "le"]))
    report.mark_outliers = [footnotes.SizeOutlier(
        "9 (reference mark)", (24,), "x", "the document default")]

    line = report.format()

    assert "resolve through a STYLE" in line
    assert "commonest value" not in line


def test_a_mark_SMALLER_than_the_rest_is_reported_too():
    """`!=`, not `>`. Every mark finding above was a mark drawn LARGER;
    one set a size smaller disagrees just the same."""
    small = '<w:sz w:val="16"/>'
    report = footnotes.sizes(part(note(2, _mark(SZ10) + run("a", SZ10)),
                                  note(3, _mark(SZ10) + run("b", SZ10)),
                                  note(4, _mark(small) + run("c", SZ10))))

    assert report.mark_house == 20
    assert [(o.id, o.stated) for o in report.mark_outliers] == [
        ("4 (reference mark)", (16,))]


def test_marks_past_256_half_points_are_compared_by_VALUE():
    """Each size is an `int` parsed afresh, and CPython shares an int
    object only up to 256. Three marks at 150pt agree; under `is not`
    every one but the first is another object and reads as an
    outlier."""
    big = '<w:sz w:val="300"/>'
    report = footnotes.sizes(part(*(note(n, _mark(big) + run("x", SZ10))
                                    for n in (2, 3, 4))))

    assert report.mark_house == 300
    assert report.mark_outliers == []


def test_a_run_BEFORE_an_equation_is_still_sized():
    """The span is asked `s <= at`, so a run in front of the equation is
    outside it. Under `s != at` everything before an equation reads as
    inside it, and a note whose wrong size sits there says nothing."""
    before = run("set in the wrong size, then ", SZ12) + MATH_WITH_A_TEXT_RUN
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, before)))

    (odd,) = report.outliers
    assert (odd.id, odd.stated) == ("4", (24,))


def test_a_run_WELL_AFTER_an_equation_is_still_sized():
    """And `at < e`. The run straight after an equation starts AT its
    end, where `at != e` agrees, so the fixture for that edge could not
    tell them apart; a second run after it can. Under `!=` it reads as
    inside the equation, and the note's second size goes unseen."""
    later = (MATH_WITH_A_TEXT_RUN + run("prose resumes", SZ10)
             + run(" and changes size", SZ12))
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, later)))

    (odd,) = report.outliers
    assert (odd.id, odd.stated) == ("4", (20, 24))


def test_a_half_SILENT_note_lists_its_stated_size_before_NOTHING():
    """`None` sorts last. The silent run comes first in the note, so the
    order asserted is the sort's and not the document's."""
    report = footnotes.sizes(part(note(2, run("a", SZ10)),
                                  note(3, run("b", SZ10)),
                                  note(4, run("silent")
                                       + run(" sized", SZ10))))

    (odd,) = report.outliers
    assert odd.stated == (20, None)
    assert "states 10pt, nothing" in str(odd)
