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
