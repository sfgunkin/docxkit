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
