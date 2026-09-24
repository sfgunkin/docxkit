"""`docxkit.house` — the house typography, applied and audited.

The rules are HCW's applier's, measured on that paper; these tests pin
what each one writes, that a second pass writes nothing new, and that
the audit reads a rule kept THROUGH the styles as kept — Word deletes a
paragraph property equal to the one it would inherit, and an audit that
read only the paragraph would report every such save as a violation.
"""
from __future__ import annotations

import re

import pytest
from conftest import make_parts, para, run

from docxkit import house
from docxkit._xml import DOCUMENT, PARA_RE, visible_text
from docxkit.lint import lint_parts

M = "<m:oMath><m:r><m:t>y=a+bx</m:t></m:r></m:oMath>"
DRAWING = ('<w:p><w:r><w:drawing><wp:inline xmlns:wp="urn:wp">'
           '<wp:extent cx="1" cy="1"/></wp:inline></w:drawing></w:r></w:p>')
LINK = ('<w:hyperlink w:anchor="Table1txt"><w:r><w:rPr>'
        '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>Table 1</w:t></w:r>'
        "</w:hyperlink>")


def paper(*body: str, styles: str | None = None) -> dict[str, bytes]:
    parts = make_parts("".join(body))
    if styles is not None:
        parts["word/styles.xml"] = (
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
            f'wordprocessingml/2006/main">{styles}</w:styles>').encode()
    return parts


def well_formed(parts: dict[str, bytes]) -> None:
    """The fixture and the result both parse: a regex-built test can
    pass over markup no reader would accept."""
    from lxml import etree
    etree.fromstring(parts[DOCUMENT])


def holding(parts: dict[str, bytes], words: str) -> str:
    xml = parts[DOCUMENT].decode()
    for m in PARA_RE.finditer(xml):
        if words in visible_text(m.group(0)):
            return m.group(0)
    raise AssertionError(words)


EXHIBIT = (para(LINK, run(". Wages by region", preserve=True)),
           DRAWING,
           para(run("Source: Survey data.")),
           para(run("Note: Standard errors in parentheses.")))


def test_a_CAPTION_gets_the_face_the_mark_keepNext_and_2pt_after():
    parts = paper(para(run("Prose.")), *EXHIBIT)

    got = house.apply(parts)

    cap = holding(parts, "Wages by region")
    assert got.captions == 1
    assert cap.count('w:ascii="Times New Roman"') == 3   # 2 runs + mark
    assert cap.count('<w:sz w:val="24"/>') == 3
    assert '<w:i w:val="false"/>' in cap
    assert "<w:keepNext/>" in cap and '<w:jc w:val="left"/>' in cap
    assert 'w:after="40" w:line="240" w:lineRule="auto"' in cap


def test_a_caption_LINK_keeps_its_style_and_stays_a_link():
    parts = paper(*EXHIBIT)

    house.apply(parts)

    cap = holding(parts, "Wages by region")
    assert '<w:hyperlink w:anchor="Table1txt">' in cap
    assert '<w:rStyle w:val="Hyperlink"/>' in cap


def test_NOTES_are_10pt_single_8pt_after_and_indented_only_under_a_figure():
    parts = paper(*EXHIBIT)

    got = house.apply(parts)

    source = holding(parts, "Source: Survey")
    note = holding(parts, "Note: Standard")
    assert (got.notes, got.figure_notes) == (2, 1)
    for p in (source, note):
        assert '<w:sz w:val="20"/>' in p
        assert 'w:after="160" w:line="240" w:lineRule="auto"' in p
    assert '<w:ind w:left="720" w:right="720"/>' in source
    assert "<w:ind" not in note


def test_a_notes_own_space_BEFORE_is_kept():
    parts = paper(f'<w:p><w:pPr><w:spacing w:before="120" w:after="400"/>'
                  f"</w:pPr>{run('Source: Kept gap.')}</w:p>")

    house.apply(parts)

    got = holding(parts, "Kept gap")
    assert '<w:spacing w:before="120" w:after="160" w:line="240"' in got


def test_applying_TWICE_writes_nothing_new():
    parts = paper(para(run("Abstract: We study wages.")), *EXHIBIT,
                  para(M, run(", (3)", preserve=True)))
    first = house.apply(parts)
    once = parts[DOCUMENT]

    second = house.apply(parts)

    assert parts[DOCUMENT] == once
    assert second.equations == 0
    assert (second.captions, second.notes) == (first.captions, first.notes)


def test_an_INLINE_abstract_bolds_the_label_and_nothing_else():
    bold_rest = ('<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">'
                 "Abstract: We study wages across regions.</w:t></w:r>")
    parts = paper(f"<w:p>{bold_rest}</w:p>", para(run("Introduction.")))

    got = house.apply(parts)

    abstract = holding(parts, "We study wages")
    runs = re.findall(r"<w:r>.*?</w:r>", abstract)
    bold = [visible_text(r) for r in runs if "<w:b/>" in r]
    assert got.abstract == "inline" and bold == ["Abstract"]
    assert '<w:ind w:left="720" w:right="720"/>' in abstract
    assert 'w:line="240"' in abstract
    assert visible_text(abstract) == "Abstract: We study wages across regions."


def test_a_HEADING_abstract_bolds_the_heading_and_sets_the_paragraph_after():
    parts = paper(para(run("Abstract")), para(run("We study wages.")),
                  para(run("1. Introduction")))

    got = house.apply(parts)

    assert got.abstract == "heading"
    assert "<w:b/>" in holding(parts, "Abstract")
    body = holding(parts, "We study wages")
    assert '<w:ind w:left="720" w:right="720"/>' in body
    assert "<w:ind" not in holding(parts, "Introduction")


def test_no_abstract_is_reported_as_none():
    assert house.apply(paper(para(run("Just prose.")))).abstract == ""


def test_the_audit_is_EMPTY_after_apply_and_names_what_it_found_before():
    parts = paper(para(run("Prose.")), *EXHIBIT)

    before = house.audit(parts)
    house.apply(parts)

    assert house.audit(parts) == []
    assert any("no keepNext" in f for f in before)
    well_formed(parts)
    assert any("not Times New Roman" in f for f in before)
    assert lint_parts(parts) == []


def test_a_rule_kept_through_the_STYLE_is_kept():
    """Word deletes `jc=left` and `keepNext` a caption inherits. Strip
    them after applying, give the style the same values: still clean."""
    styles = ('<w:style w:type="paragraph" w:styleId="Caption">'
              "<w:pPr><w:keepNext/></w:pPr></w:style>")
    cap = (f'<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr>{LINK}'
           f'{run(". Wages by region", preserve=True)}</w:p>')
    parts = paper(cap, *EXHIBIT[1:], styles=styles)
    house.apply(parts)
    xml = parts[DOCUMENT].decode()
    parts[DOCUMENT] = (xml.replace('<w:jc w:val="left"/>', "", 1)
                       .replace("<w:keepNext/>", "", 1)).encode()
    well_formed(parts)

    assert house.audit(parts) == []


def test_a_FACE_inherited_from_the_style_is_the_face():
    """HCW, 2026-09-24: its notes state only `sz`, and are Times New Roman
    through `Normal`. Read off the run, that was sixty-one findings on a
    paper that renders every one of them correctly."""
    styles = ('<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
              '<w:rPr><w:rFonts w:ascii="Times New Roman"/>'
              '<w:sz w:val="24"/></w:rPr></w:style>')
    note = ('<w:p><w:pPr><w:spacing w:after="160" w:line="240"/>'
            '<w:jc w:val="left"/></w:pPr><w:r><w:rPr><w:sz w:val="20"/>'
            "</w:rPr><w:t>Source: Survey data.</w:t></w:r></w:p>")
    parts = paper(note, styles=styles)
    well_formed(parts)

    assert house.audit(parts) == []


def test_a_THEME_font_is_resolved_through_the_theme_part():
    styles = ('<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts '
              'w:asciiTheme="minorHAnsi"/><w:sz w:val="20"/></w:rPr>'
              "</w:rPrDefault></w:docDefaults>")
    note = ('<w:p><w:pPr><w:spacing w:after="160" w:line="240"/></w:pPr>'
            "<w:r><w:t>Source: Survey data.</w:t></w:r></w:p>")
    parts = paper(note, styles=styles)
    parts["word/theme/theme1.xml"] = (
        b'<a:theme xmlns:a="urn:a"><a:fontScheme><a:majorFont>'
        b'<a:latin typeface="Georgia"/></a:majorFont><a:minorFont>'
        b'<a:latin typeface="Aptos"/></a:minorFont></a:fontScheme></a:theme>')

    assert house.audit(parts) == [
        "note 'Source: Survey data.': a run is in Aptos, not Times New "
        "Roman"]


def test_a_STYLE_that_centres_the_caption_is_a_finding():
    styles = ('<w:style w:type="paragraph" w:styleId="Caption">'
              '<w:pPr><w:jc w:val="center"/></w:pPr></w:style>')
    cap = (f'<w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr>{LINK}'
           f'{run(". Wages by region", preserve=True)}</w:p>')
    parts = paper(cap, *EXHIBIT[1:], styles=styles)
    house.apply(parts)
    xml = parts[DOCUMENT].decode()
    parts[DOCUMENT] = xml.replace('<w:jc w:val="left"/>', "", 1).encode()
    well_formed(parts)

    assert any("aligned center" in f for f in house.audit(parts))


def test_a_NUMBERED_equation_goes_into_the_grid_and_the_audit_sees_both():
    parts = paper(para(run("Prose.")), para(M, run(", (3)", preserve=True)))

    before = house.audit(parts)
    got = house.apply(parts)

    assert any("equation (3)" in f for f in before)
    assert got.equations == 1
    xml = parts[DOCUMENT].decode()
    assert xml.count("<w:tc>") == 3 and "<m:oMathPara" in xml
    assert house.audit(parts) == []


def test_a_paper_that_numbers_its_own_way_turns_the_equation_rule_off():
    parts = paper(para(M, run(" (3)", preserve=True)))
    rules = house.Rules(number_equations=False)

    assert house.apply(parts, rules).equations == 0
    assert house.audit(parts, rules) == []


@pytest.mark.parametrize("size,want", [(11, "22"), (10.5, "21")])
def test_a_FACE_writes_half_points(size, want):
    face = house.Face(size_pt=size)

    assert face.props()["sz"] == f'<w:sz w:val="{want}"/>'
    assert "i" not in face.props()
