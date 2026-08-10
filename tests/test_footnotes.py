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


# --------------------------------------------- do they AGREE on a size ----
# The manuscript defect this exists for: one footnote rendered at 12pt
# among 10pt neighbours, and the offender carried NO w:sz at all — it
# inherited the body size, so searching for a wrong value found nothing.


SZ10, SZ12 = '<w:sz w:val="20"/>', '<w:sz w:val="24"/>'


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
    would put every conforming document on the list."""
    marked = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
              "<w:footnoteRef/></w:r>")
    report = footnotes.sizes(part(note(2, marked + run("a", SZ10)),
                                  note(3, marked + run("b", SZ10))))
    assert report.ok, report.format()


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
