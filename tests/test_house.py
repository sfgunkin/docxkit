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


TABLE = ("<w:tbl><w:tblPr/><w:tr><w:tc><w:p><w:r><w:t>1.5</w:t></w:r></w:p>"
         "</w:tc></w:tr></w:tbl>")


def starred_tables(n: int) -> list[str]:
    """`n` tables, each captioned above and noted below with a "*" line —
    ep3_sc's Table 3, whose note stayed in the body face (2026-11-03)."""
    out = []
    for k in range(1, n + 1):
        out += [para(run(f"Table {k}. Monthly costs {k}")), TABLE,
                para(run(f"* The monthly costs of item {k}."))]
    return out


def test_a_STAR_LED_note_inside_a_table_block_is_styled_and_audited():
    # 3 tables, and a "*" paragraph in the prose that belongs to none
    # an EMPTY <w:p/> ahead of them, as ep3_sc has: it is a body child,
    # and a walk that skipped it located every note one paragraph early
    parts = paper("<w:p/>", *starred_tables(3), para(run("Prose follows.")),
                  para(run("* An aside in the prose, not a note.")))
    before = house.audit(parts)

    got = house.apply(parts)

    assert got.notes == 3
    assert house.scope(parts).notes == 3
    for k in (1, 2, 3):
        note = holding(parts, f"costs of item {k}")
        assert '<w:sz w:val="20"/>' in note
        assert 'w:after="160" w:line="240" w:lineRule="auto"' in note
    assert "<w:sz" not in holding(parts, "An aside")
    assert len({f.split(":")[0] for f in before
                if f.startswith("note '* The monthly")}) == 3
    assert house.audit(parts) == []
    well_formed(parts)


def test_a_note_keeps_a_co_authors_pending_PARAGRAPH_MARK():
    """Review, 2026-11-09: behind a `w:spacing`, the mark's `w:rPr` was
    not found, the face replaced it whole, and the co-author's `w:ins`
    on the mark was gone — rejecting their change kept the paragraph."""
    from docxkit.revisions import by_author, reject

    marks = [f'<w:p><w:pPr><w:spacing w:after="0"/><w:rPr><w:ins w:id='
             f'"{70 + k}" w:author="Co" w:date="2026-11-01T00:00:00Z"/>'
             f"</w:rPr></w:pPr>{_ins_run(f'* Added note {k}.', 80 + k)}</w:p>"
             for k in (1, 2, 3)]
    tables = [part for k in (1, 2, 3)
              for part in (para(run(f"Table {k}. Costs {k}")), TABLE,
                           marks[k - 1])]
    parts = paper(*tables, para(run("Prose.")))

    house.apply(parts)

    xml = parts[DOCUMENT].decode()
    for k in (1, 2, 3):
        note = holding(parts, f"Added note {k}")
        assert f'<w:ins w:id="{70 + k}" w:author="Co"' in note
        assert '<w:sz w:val="20"/>' in note
    kept = reject(xml, where=by_author("Co"))
    assert "Added note" not in kept
    from docxkit.lint import lint_parts
    assert not [f for f in lint_parts(parts) if "order" in str(f).lower()]
    well_formed(parts)


def _ins_run(text: str, rid: int) -> str:
    return (f'<w:ins w:id="{rid}" w:author="Co" w:date="2026-11-01T00:00:'
            f'00Z">{run(text)}</w:ins>')


def test_a_block_note_above_an_equation_is_NOT_its_lead_in():
    """A '*' note is a note: styled as one, then re-spaced as an
    equation's lead-in, the audit after apply could never come back
    clean (review, 2026-11-09)."""
    blocks = [part for k in (1, 2, 3)
              for part in (*starred_tables(1)[:2],
                           para(run(f"* The monthly costs of item {k}.")),
                           para(M))]
    blocks = [b.replace("Table 1.", f"Table {i // 4 + 1}.")
              for i, b in enumerate(blocks)]
    parts = paper(*blocks)

    got = house.apply(parts, house.Rules(number_equations=False))

    assert got.notes == 3 and got.lead_ins == 0
    assert house.audit(parts, house.Rules(number_equations=False)) == []


def test_a_block_note_holding_MATHS_or_sitting_ABOVE_its_caption_is_a_note():
    """Two layouts `_span_notes` missed: the tree side reads `w:t` only,
    so a note with an inline OMML `p` failed the text check; and a scan
    from the later of body and caption never saw a note between them —
    a picture, its note, then the caption below (review, 2026-11-09)."""
    maths = ("<m:oMath><m:r><m:t>p</m:t></m:r></m:oMath>")
    with_maths = [part for k in (1, 2, 3)
                  for part in (para(run(f"Table {k}. Costs {k}")), TABLE,
                               para(run("* Significant at 5 percent; ",
                                        preserve=True), maths,
                                    run(f" below 0.05, panel {k}.",
                                        preserve=True)))]
    below = [part for k in (1, 2, 3)
             for part in (DRAWING, para(run(f"* Source: survey wave {k}.")),
                          para(run(f"Figure {k}. Wages {k}")))]
    parts = paper(*with_maths, para(run("Prose between.")), *below)

    got = house.apply(parts)

    assert got.notes == 6
    for words in ("panel 1", "panel 3", "survey wave 1", "survey wave 3"):
        assert '<w:sz w:val="20"/>' in holding(parts, words)
    assert not [f for f in house.audit(parts) if f.startswith("note")]


CAPTION_STYLE = ('<w:style w:type="paragraph" w:styleId="Caption">'
                 '<w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/>'
                 '<w:color w:val="0E2841"/><w:sz w:val="18"/></w:rPr>'
                 "</w:style>")
CAP_PPR = '<w:pPr><w:pStyle w:val="Caption"/></w:pPr>'


def simple_caption(k: int) -> str:
    """Insert Caption's form: the number is a `w:fldSimple` result."""
    return (f"<w:p>{CAP_PPR}{run('Table ', preserve=True)}"
            r'<w:fldSimple w:instr=" SEQ Table \* ARABIC ">'
            f"{run(str(k))}</w:fldSimple>{run(f': Costs {k}')}</w:p>")


def complex_caption(k: int) -> str:
    """The fldChar form, its instruction split across two runs."""
    return (f"<w:p>{CAP_PPR}{run('Figure ', preserve=True)}"
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> SEQ Figure'
            '</w:instrText></w:r>'
            r'<w:r><w:instrText xml:space="preserve"> \* ARABIC '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f"{run(str(k))}"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            f"{run(f'. Wages {k}')}</w:p>")


def test_a_caption_NUMBER_field_gets_MERGEFORMAT_so_an_update_keeps_the_face():
    """ep3_sc, 2026-11-03: the XML said Times 12 black and the PDF drew
    the "1" in the Caption style, because Word regenerates a field result
    on print and only `\\* MERGEFORMAT` keeps the face it was given."""
    caps = [simple_caption(k) for k in (1, 2, 3)] + [
        complex_caption(k) for k in (1, 2, 3, 4, 5)]
    parts = paper(*caps, styles=CAPTION_STYLE)
    said = [f for f in house.audit(parts) if "MERGEFORMAT" in f]

    got = house.apply(parts)
    once = parts[DOCUMENT]
    house.apply(parts)

    xml = parts[DOCUMENT].decode()
    assert got.captions == 8 and len(said) == 8
    assert xml.count(r'w:instr=" SEQ Table \* ARABIC \* MERGEFORMAT "') == 3
    assert xml.count(r"> \* ARABIC \* MERGEFORMAT </w:instrText>") == 5
    assert parts[DOCUMENT] == once                      # idempotent
    assert not [f for f in house.audit(parts) if "MERGEFORMAT" in f]
    well_formed(parts)


def test_a_caption_style_that_IS_the_house_face_needs_no_switch():
    house_face = ('<w:style w:type="paragraph" w:styleId="Caption"><w:rPr>'
                  '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New '
                  'Roman"/><w:sz w:val="24"/></w:rPr></w:style>')
    parts = paper(*[simple_caption(k) for k in (1, 2, 3)], styles=house_face)

    assert not [f for f in house.audit(parts) if "MERGEFORMAT" in f]


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


# ---- the equation lead-in: 4 pt after (author, 2026-09-26, Misconceptions)

LEAD = ('<w:p><w:pPr><w:spacing w:before="60" w:after="160" w:line="480" '
        'w:lineRule="auto"/></w:pPr>'
        + run("The index is defined as follows:") + "</w:p>")


def test_an_equation_LEAD_IN_gets_4pt_after_and_keeps_the_rest():
    parts = paper(para(run("Prose.")), LEAD,
                  para(M, run(" (3)", preserve=True)))

    before = house.audit(parts)
    got = house.apply(parts)

    lead = holding(parts, "defined as follows")
    assert got.lead_ins == 1
    assert ('<w:spacing w:before="60" w:line="480" w:lineRule="auto" '
            'w:after="80"/>') in lead
    assert 'w:after="80"' not in holding(parts, "Prose.")
    assert ("equation lead-in 'The index is defined as follow': 8 pt "
            "after, not 4 pt") in before
    assert house.audit(parts) == []
    well_formed(parts)


def test_an_UNNUMBERED_display_equation_has_a_lead_in_too():
    parts = paper(para(run("Where:")), para(M))

    assert house.apply(parts).lead_ins == 1
    assert 'w:after="80"' in holding(parts, "Where:")


def test_afterLines_would_override_after_and_is_dropped():
    lead = ('<w:p><w:pPr><w:spacing w:afterLines="100" w:after="200"/>'
            f'</w:pPr>{run("Consider:")}</w:p>')
    parts = paper(lead, para(M))

    assert any("1 lines after" in f for f in house.audit(parts))
    house.apply(parts)

    assert "afterLines" not in holding(parts, "Consider:")
    assert house.audit(parts) == []


@pytest.mark.parametrize("above", [
    para(run("Note: Standard errors in parentheses.")),
    para(LINK, run(". Wages by region", preserve=True)),
    para(M),
])
def test_a_NOTE_a_CAPTION_or_another_EQUATION_above_is_not_a_lead_in(above):
    parts = paper(above, para(M))

    assert house.apply(parts).lead_ins == 0


def test_an_EMPTY_paragraph_between_breaks_the_lead_in():
    """PARA_RE skips a self-closing `<w:p/>`; the paragraph above it is not
    the one that sits over the equation on the page."""
    parts = paper(para(run("Far above.")), "<w:p/>", para(M))

    assert house.apply(parts).lead_ins == 0


def test_a_paper_that_spaces_its_own_way_turns_the_lead_in_rule_off():
    parts = paper(LEAD, para(M))
    rules = house.Rules(equation_lead_after=None)

    assert house.apply(parts, rules).lead_ins == 0
    assert house.audit(parts, rules) == []
    assert 'w:after="160"' in holding(parts, "defined as follows")
