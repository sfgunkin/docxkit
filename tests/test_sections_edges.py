"""The survivors of the first full `sections.py` sweep (2026-09-13).

27.2 % of its mutants lived against `test_sections.py`: the numbering
reader's defaults and fallbacks, the formats Word prints, the audit's
arithmetic and `renumber`'s rewrites. Each test here holds one of those
readings on a fixture built to tell a mutant from the code — a format
read from the file rather than typed as the literal it is compared with,
a style whose attributes sit after its id, a range of three members.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run
from test_sections import LVL, NUM, NUMBERING, STYLE, H, P

from docxkit import sections

# --- the formats Word prints ------------------------------------------------


def test_each_FORMAT_prints_as_Word_prints_it_read_from_the_file():
    """Read out of numbering.xml, no format name is the very string the
    code compares with; and a format this reader does not spell, such as
    `arabicAlpha`, is printed as a plain number rather than dropped."""
    fmts = ["upperLetter", "lowerLetter", "upperRoman", "lowerRoman",
            "decimalZero", "none", "ordinal", "arabicAlpha"]
    numbering = NUMBERING("".join(LVL(i, f"%{i + 1}", fmt=f, start=3)
                                  for i, f in enumerate(fmts)))
    body = "".join(NUM(f, i) for i, f in enumerate(fmts))

    nums = sections.list_numbers(make_parts(
        body, extra={"word/numbering.xml": numbering}))

    assert nums == {0: "C", 1: "c", 2: "III", 3: "iii", 4: "03", 5: "",
                    6: "3", 7: "3"}


@pytest.mark.parametrize(("n", "roman"), [
    (3, "iii"), (4, "iv"), (8, "viii"), (9, "ix"), (10, "x"), (39, "xxxix"),
    (40, "xl"), (49, "xlix"), (50, "l"), (89, "lxxxix"), (90, "xc"),
    (99, "xcix"), (100, "c"), (399, "cccxcix"), (400, "cd"),
    (499, "cdxcix"), (500, "d"), (899, "dcccxcix"), (900, "cm"),
    (999, "cmxcix"), (1000, "m"), (2026, "mmxxvi")])
def test_a_roman_numeral_turns_at_its_value_and_not_one_below(n, roman):
    assert sections._format(n, "lowerRoman") == roman


# --- which paragraph is numbered, and at which level -------------------------


def test_the_DEFAULT_style_is_read_off_an_opening_tag_in_any_order():
    """`w:default` after `w:styleId`, the style first in the part, and a
    default CHARACTER style after it: a paragraph with no style of its own
    is numbered by the default paragraph style and by nothing else."""
    styles = ('<w:styles><w:style w:type="paragraph" w:styleId="Normal" '
              'w:default="1"><w:pPr><w:numPr><w:numId w:val="4"/>'
              "</w:numPr></w:pPr></w:style>"
              '<w:style w:type="character" w:default="1" '
              'w:styleId="DefaultParagraphFont"></w:style></w:styles>')

    nums = sections.list_numbers(make_parts(
        P("one") + P("two"),
        extra={"word/styles.xml": styles,
               "word/numbering.xml": NUMBERING(LVL(0, "%1."))}))

    assert nums == {0: "1.", 1: "2."}


def test_a_LEVEL_comes_down_the_basedOn_chain_with_no_level_linked_to_it():
    """Heading2 states `ilvl` 1 and takes numId 4 from Heading1, and here
    no level names a style to fall back on, so the level is the chain's.
    A chain that points at a style the part does not have just ends."""
    styles = ("<w:styles>"
              + STYLE("Heading1", numpr='<w:numId w:val="4"/>')
              + STYLE("Heading2", numpr='<w:ilvl w:val="1"/>',
                      based="Heading1")
              + STYLE("Orphan", numpr='<w:ilvl w:val="1"/>', based="Missing")
              + "</w:styles>")
    orphan = para('<w:pPr><w:pStyle w:val="Orphan"/></w:pPr>' + run("x"))

    nums = sections.list_numbers(make_parts(
        H("A") + H("B", 2) + orphan,
        extra={"word/styles.xml": styles,
               "word/numbering.xml": NUMBERING(LVL(0, "%1.")
                                               + LVL(1, "%1.%2."))}))

    assert nums == {0: "1.", 1: "1.1."}


def test_a_num_with_NO_abstract_is_passed_over_and_a_level_starts_at_ZERO():
    """A `w:num` naming no abstract definition does not end the reading of
    the ones after it, and a level that states no `w:start` counts from 0,
    Word's default."""
    numbering = ('<w:numbering><w:abstractNum w:abstractNumId="7">'
                 '<w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/>'
                 '<w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
                 '<w:num w:numId="3"></w:num>'
                 '<w:num w:numId="4"><w:abstractNumId w:val="7"/></w:num>'
                 "</w:numbering>")

    nums = sections.list_numbers(make_parts(
        NUM("a", 0) + NUM("b", 0),
        extra={"word/numbering.xml": numbering}))

    assert nums == {0: "0.", 1: "1."}


def test_a_numStyleLink_BORROWS_levels_only_when_it_has_none_of_its_own():
    """Abstract 8 has no levels and links to ListStyle, whose numId 4 uses
    abstract 7: it counts with 7's levels, on its own counter. Abstract 11
    links too but has a level of its own, and keeps it. Links to a style
    with no numbering, or to a numId nothing defines, borrow nothing and
    break nothing."""
    numbering = ("<w:numbering>"
                 '<w:abstractNum w:abstractNumId="7">' + LVL(0, "%1)")
                 + "</w:abstractNum>"
                 '<w:abstractNum w:abstractNumId="8">'
                 '<w:numStyleLink w:val="ListStyle"/></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="9">'
                 '<w:numStyleLink w:val="Bare"/></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="10">'
                 '<w:numStyleLink w:val="Ghost"/></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="11">' + LVL(0, "(%1)")
                 + '<w:numStyleLink w:val="ListStyle"/></w:abstractNum>'
                 '<w:num w:numId="4"><w:abstractNumId w:val="7"/></w:num>'
                 '<w:num w:numId="5"><w:abstractNumId w:val="8"/></w:num>'
                 '<w:num w:numId="6"><w:abstractNumId w:val="11"/></w:num>'
                 "</w:numbering>")
    styles = ("<w:styles>"
              + STYLE("ListStyle", numpr='<w:numId w:val="4"/>')
              + STYLE("Bare")
              + STYLE("Ghost", numpr='<w:numId w:val="99"/>')
              + "</w:styles>")

    nums = sections.list_numbers(make_parts(
        NUM("a", 0, num=5) + NUM("b", 0, num=5) + NUM("c", 0, num=6),
        extra={"word/numbering.xml": numbering, "word/styles.xml": styles}))

    assert nums == {0: "1)", 1: "2)", 2: "(1)"}


def test_numId_ZERO_is_no_number_even_where_the_part_defines_one():
    numbering = NUMBERING(LVL(0, "%1.")).replace(
        "</w:numbering>",
        '<w:num w:numId="0"><w:abstractNumId w:val="7"/></w:num>'
        "</w:numbering>")

    nums = sections.list_numbers(make_parts(
        NUM("a", 0) + NUM("off", 0, num=0) + NUM("b", 0),
        extra={"word/numbering.xml": numbering}))

    assert nums == {0: "1.", 2: "2."}


def test_a_paragraph_stating_only_its_LEVEL_takes_its_numId_from_its_style():
    styles = ("<w:styles>" + STYLE("Heading1", numpr='<w:numId w:val="4"/>')
              + "</w:styles>")
    sub = para('<w:pPr><w:pStyle w:val="Heading1"/><w:numPr>'
               '<w:ilvl w:val="1"/></w:numPr></w:pPr>' + run("Sub"))

    nums = sections.list_numbers(make_parts(
        H("Intro") + sub,
        extra={"word/styles.xml": styles,
               "word/numbering.xml": NUMBERING(
                   LVL(0, "%1.", style="Heading1") + LVL(1, "%1.%2."))}))

    assert nums == {0: "1.", 1: "1.1."}


def test_a_style_with_NO_level_is_numbered_at_the_level_LINKED_to_it():
    """The link is found by the style's id among levels whose own ids sort
    both above and below it, and the printed number reads every placeholder
    from its own level: 3, 5 and 7 start apart so none can stand in for
    another."""
    styles = ("<w:styles>" + STYLE("Sub", numpr='<w:numId w:val="4"/>')
              + "</w:styles>")
    numbering = NUMBERING(LVL(0, "%1.", start=3, style="Zulu")
                          + LVL(1, "%1.%2.", start=5, style="Alpha")
                          + LVL(2, "%1.%2.%3.", start=7, style="Sub"))

    nums = sections.list_numbers(make_parts(
        para('<w:pPr><w:pStyle w:val="Sub"/></w:pPr>' + run("x")),
        extra={"word/styles.xml": styles, "word/numbering.xml": numbering}))

    assert nums == {0: "3.5.7."}


def test_a_numId_with_no_level_is_level_0_and_a_MISSING_level_prints_0():
    nums = sections.list_numbers(make_parts(
        para('<w:pPr><w:numPr><w:numId w:val="4"/></w:numPr></w:pPr>'
             + run("x")),
        extra={"word/numbering.xml": NUMBERING(LVL(0, "%1.%2", start=4))}))

    assert nums == {0: "4.0"}


def test_a_BULLET_first_does_not_end_the_numbering_after_it():
    numbering = NUMBERING(LVL(0, "%1.") + LVL(1, "•", fmt="bullet"))

    nums = sections.list_numbers(make_parts(
        NUM("dot", 1) + NUM("one", 0) + NUM("two", 0),
        extra={"word/numbering.xml": numbering}))

    assert nums == {1: "1.", 2: "2."}


def test_a_start_override_is_counted_FROM_one_below_it():
    """An even override: 4 - 1 and 4 ^ 1 part company, where 5's agree."""
    numbering = NUMBERING(
        LVL(0, "%1."),
        override='<w:lvlOverride w:ilvl="0"><w:startOverride w:val="4"/>'
                 "</w:lvlOverride>")

    nums = sections.list_numbers(make_parts(
        NUM("a", 0) + NUM("b", 0), extra={"word/numbering.xml": numbering}))

    assert nums == {0: "4.", 1: "5."}


def test_lvlRestart_restarts_a_level_after_the_levels_ABOVE_it_only():
    """Level 3 restarts after level 0 alone (`w:lvlRestart` 1, one-based):
    a level-2 or a level-1 paragraph between its items leaves its count
    running, and only the next level-0 paragraph starts it again."""
    level3 = ('<w:lvl w:ilvl="3"><w:start w:val="1"/>'
              '<w:numFmt w:val="decimal"/><w:lvlRestart w:val="1"/>'
              '<w:lvlText w:val="%4)"/></w:lvl>')
    numbering = NUMBERING(LVL(0, "%1.") + LVL(1, "%2.") + LVL(2, "%3.")
                          + level3)
    body = (NUM("A", 0) + NUM("a", 3) + NUM("b", 3) + NUM("B2", 2)
            + NUM("c", 3) + NUM("B1", 1) + NUM("d", 3) + NUM("A2", 0)
            + NUM("e", 3))

    nums = sections.list_numbers(make_parts(
        body, extra={"word/numbering.xml": numbering}))

    assert nums == {0: "1.", 1: "1)", 2: "2)", 3: "1.", 4: "3)", 5: "1.",
                    6: "4)", 7: "2.", 8: "1)"}


def test_a_level_and_a_heading_are_FROZEN():
    """Read once per definition and once per heading, then handed to every
    reader after: neither may change under one of them."""
    import dataclasses

    for value in (sections._Level(1, "decimal", "%1.", False, None, None),
                  sections.Heading("1", "One", 1)):
        first = dataclasses.fields(value)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, first, None)


# --- the audit ---------------------------------------------------------------


def test_the_report_COUNTS_and_lists_the_appendix_subsections():
    text = sections.audit(make_parts(
        H("1. One") + H("Appendix A") + H("A.1 Proofs", 2)
        + H("A.2 Data", 2))).format()

    assert text.splitlines()[:3] == [
        "4 heading(s), 1 section(s), 2 appendix subsection(s), 0 mention(s)",
        "  sections : 1", "  appendix : A.1 A.2"]


def test_an_Appendix_heading_that_names_NO_letter_opens_appendix_A():
    report = sections.audit(make_parts(
        H("1. One") + H("Appendix") + H("A.1 Only", 2)))

    assert report.ok, report.breaches


def test_an_early_appendix_subhead_is_named_by_its_first_FORTY_characters():
    title = "Early " + "x" * 50

    (breach,) = sections.audit(make_parts(
        H("1. One") + H(f"A.1 {title}", 2) + H("Appendix"))).breaches

    assert breach == (f"A.1 {title[:40]!r}: an appendix subhead before any "
                      "Appendix heading")


def test_appendix_SUBSUBSECTIONS_run_by_their_last_part():
    report = sections.audit(make_parts(
        H("1. One") + H("Appendix A") + H("A.1 X", 2) + H("A.1.1 Y", 3)
        + H("A.1.2 Z", 3)))

    assert report.ok, report.breaches


def test_a_THIRD_level_sits_under_its_parent_however_deep_the_chain():
    report = sections.audit(make_parts(
        H("1. One") + H("1.1 A", 2) + H("1.1.1 Deep", 3)
        + H("1.1.2 Deeper", 3) + H("1.2 B", 2)))

    assert report.ok, report.breaches


@pytest.mark.parametrize(("body", "first"), [
    (H("1. One") + H("2. Two") + H("2.1 A", 2) + H("2.1.1 Deep", 3)
     + H("1.2 Stray", 2), "Section 1.2: sits under Section 2"),
    (H("1. One") + H("1.1 A", 2) + H("2.1.1 Stray", 3),
     "Section 2.1.1: sits under Section 1.1"),
    (H("1. One") + H("1.1 A", 2) + H("1.1.1 B", 3) + H("2.1.1.1 Stray", 4),
     "Section 2.1.1.1: sits under Section 1.1.1"),
], ids=["depth 2 under a longer chain", "depth 3", "depth 4"])
def test_a_misplaced_subsection_names_the_heading_it_SITS_UNDER(body, first):
    assert sections.audit(make_parts(body)).breaches[0] == first


def test_a_bare_mention_counts_at_the_START_before_an_exhibit_and_after_one():
    """Only what an equation or exhibit number covers is passed over: "A.3"
    opening the paragraph, "A.4" ahead of "Table A.5", and "A.6" starting
    the very character after "(A.7)" are mentions."""
    report = sections.audit(make_parts(
        H("1. One") + H("Appendix A") + H("A.1 Only", 2)
        + P("A.3 opens it; as A.4 shows, and Table A.5, and (A.7)A.6 too.")))

    assert [b.split("  ")[0] for b in report.breaches] == [
        "A.3: no such appendix section", "A.4: no such appendix section",
        "A.6: no such appendix section"]


def test_a_range_whose_ends_are_EQUAL_does_not_run_upward():
    report = sections.audit(make_parts(
        H("1. One") + H("2. Two") + P("Sections 2–2 again.")))

    assert report.breaches == [
        "Sections 2–2: the range does not run upward  …Sections 2–2 again.…"]


def test_a_mention_of_a_letter_the_paper_LACKS_does_not_end_the_scan():
    report = sections.audit(make_parts(
        H("1. One") + H("Appendix A") + H("A.1 Only", 2)
        + P("B.2 first, then A.3.")))

    assert report.breaches == [
        "A.3: no such appendix section  …B.2 first, then A.3.…"]


def test_a_breach_quotes_FORTY_SIX_characters_either_side():
    text = "x" * 60 + " Section 9 " + "y" * 60

    report = sections.audit(make_parts(H("1. One") + P(text)))

    assert report.breaches == ["Section 9: no such section  …" + "x" * 45
                               + " Section 9 " + "y" * 45 + "…"]


# --- what renumber reports --------------------------------------------------


def test_a_renumbering_of_HEADINGS_alone_has_changed_something():
    done = sections.renumber(make_parts(H("1. One") + H("3. Three")))

    assert done.changed and done.headings and not done.mentions


def test_the_renumbering_report_cuts_a_title_at_FIFTY_and_names_the_part():
    title = "T" * 60

    lines = sections.renumber(make_parts(
        H("1. One") + H(f"3. {title}") + P("See Section 3."))).format(
        ).splitlines()

    assert f"  heading 3 -> 2  {'T' * 50}" in lines
    assert "  document.xml: 'Section 3' -> 'Section 2'" in lines


def test_renumber_names_the_FIRST_THREE_breaches_its_result_still_has(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def audit(_parts: dict[str, bytes]) -> sections.SectionReport:
        return sections.SectionReport(breaches=["a", "b", "c", "d"])

    monkeypatch.setattr(sections, "audit", audit)

    with pytest.raises(sections.AnchorError, match=r"numbering: a; b; c$"):
        sections.renumber(make_parts(H("1. One") + H("3. Three")))


# --- renumber: the structure it reads ---------------------------------------


@pytest.mark.parametrize(("body", "message"), [
    (H("Appendix A") + H("A.1 X", 2) + H("A.1.2 " + "Z" * 50, 3),
     f"A.1.2 {'Z' * 40!r} does not sit under an Appendix A heading"),
    (H("Appendix B") + H("A.1 X", 2),
     "A.1 'X' does not sit under an Appendix A heading"),
    (H("Appendix A") + H("B.1 X", 2),
     "B.1 'X' does not sit under an Appendix B heading"),
], ids=["a third part", "a letter before", "a letter after"])
def test_renumber_REFUSES_an_appendix_subhead_its_heading_does_not_own(
        body, message):
    import re

    with pytest.raises(sections.AnchorError,
                       match=re.escape(f"renumber: {message}")):
        sections.renumber(make_parts(H("1. One") + body))


def test_renumber_counts_THIRD_and_FOURTH_levels_under_their_new_parents():
    body = (H("1. One") + H("1.1 A", 2) + H("1.1.1 B", 3) + H("1.1.2 C", 3)
            + H("1.2 D", 2) + H("1.2.1 E", 3) + H("3. Three")
            + H("3.1 F", 2) + H("3.1.1 G", 3) + H("3.1.1.1 H", 4)
            + H("3.1.1.2 I", 4))

    done = sections.renumber(make_parts(body))

    assert done.numbers == {"3": "2", "3.1": "2.1", "3.1.1": "2.1.1",
                            "3.1.1.1": "2.1.1.1", "3.1.1.2": "2.1.1.2"}
    assert sections.audit(done.parts).ok


@pytest.mark.parametrize(("body", "message"), [
    (H("2.1 Stray", 2) + H("1. One"),
     "Section 2.1 does not sit under Section 2;"),
    (H("1. One") + H("1.1.1 Deep", 3),
     "Section 1.1.1 does not sit under Section 1.1;"),
    (H("1. One") + H("2. Two") + H("1.2 Stray", 2),
     "Section 1.2 does not sit under Section 1;"),
], ids=["nothing above it", "a level skipped", "a parent sorting after"])
def test_renumber_REFUSES_a_subsection_its_chain_cannot_place(body, message):
    import re

    with pytest.raises(sections.AnchorError, match=re.escape(message)):
        sections.renumber(make_parts(body))


def test_a_heading_number_after_LEADING_space_is_renumbered_where_it_stands():
    from docxkit._xml import visible_text

    done = sections.renumber(make_parts(
        H("1. One") + H("Appendix A") + H("A.1 First", 2)
        + H(" A.3 Third", 2)))

    assert " A.2 Third" in visible_text(
        done.parts["word/document.xml"].decode("utf-8"))


def test_renumber_moves_Section_10_to_9_though_9_SORTS_after_10():
    """Compared as strings "9" is greater than "10", so a rewrite kept only
    when it sorts lower would leave the heading, the mention and the list
    all alone."""
    from docxkit._xml import visible_text

    heads = "".join(H(f"{n}. S{n}") for n in range(1, 9)) + H("10. Ten")

    done = sections.renumber(make_parts(
        heads + P("Section 10 and Sections 10 and 8.")))

    text = visible_text(done.parts["word/document.xml"].decode("utf-8"))
    assert "9. Ten" in text
    assert "Section 9 and Sections 9 and 8." in text


def test_renumber_leaves_a_mention_that_does_not_move_UNTOUCHED():
    done = sections.renumber(make_parts(
        H("1. One") + H("2. Two") + H("4. Four") + H("Appendix A")
        + H("A.1 Only", 2) + P("Sections 1 and 2, Section 2, and A.1 stand.")
        + P("Section 4 moves.")))

    assert done.mentions == [("word/document.xml", "Section 4", "Section 3")]
    assert done.paragraphs == 2


# --- renumber: what it rewrites ---------------------------------------------


def _text(parts: dict[str, bytes], name: str = "word/document.xml") -> str:
    from docxkit._xml import visible_text

    return visible_text(parts[name].decode("utf-8"))


def test_a_mention_keeps_its_WORDS_wherever_it_stands_in_the_paragraph():
    """"Section " and "Appendix " are kept by their offset from the
    mention's own start; a mention at the start of its paragraph cannot
    tell that offset from an arithmetic on the paragraph's."""
    done = sections.renumber(make_parts(
        H("1. One") + H("2. Two") + H("4. Four") + P("Look at Section 4.")
        + H("Appendix A") + H("A.1 First", 2) + H("A.3 Third", 2)
        + P("See also Appendix A.3.")))

    assert "Look at Section 3." in _text(done.parts)
    assert "See also Appendix A.2." in _text(done.parts)


def test_a_mention_of_a_letter_the_paper_LACKS_does_not_end_the_rewrite():
    done = sections.renumber(make_parts(
        H("1. One") + H("Appendix A") + H("A.1 First", 2)
        + H("A.3 Third", 2) + P("B.2 aside, A.3 moves.")))

    assert "B.2 aside, A.2 moves." in _text(done.parts)


def test_merged_into_is_CHECKED_when_10_moves_to_9():
    """The one number that moves, 10, sorts before its new 9 as a string:
    whether the numbering is settled asks for equality, not order."""
    import re

    heads = "".join(H(f"{n}. S{n}") for n in range(1, 9)) + H("10. Ten")

    with pytest.raises(sections.AnchorError, match=re.escape(
            "names Section 8, and a heading still carries it")):
        sections.renumber(make_parts(heads), merged_into={"8": "7"})


def test_a_SETTLED_numbering_takes_every_merge_after_one_it_carries():
    done = sections.renumber(
        make_parts(H("1. One") + H("2. Two") + H("3. Three")
                   + P("Section 4 went into 3.")),
        merged_into={"2": "1", "4": "3"})

    assert "Section 3 went into 3." in _text(done.parts)


def test_renumber_rewrites_ENDNOTES_with_no_footnotes_and_keeps_parts_whole():
    from lxml import etree

    notes = ('<w:endnotes xmlns:w="http://schemas.openxmlformats.org/'
             'wordprocessingml/2006/main"><w:endnote w:id="1"><w:p>'
             + run("See Section 3.") + "</w:p></w:endnote></w:endnotes>")
    parts = make_parts(H("1. One") + H("3. Three"),
                       extra={"word/endnotes.xml": notes})
    parts.pop("word/footnotes.xml", None)

    done = sections.renumber(parts)

    assert "See Section 2." in _text(done.parts, "word/endnotes.xml")
    for name in ("word/document.xml", "word/endnotes.xml"):
        etree.fromstring(done.parts[name])


def test_only_a_BODY_heading_has_its_leading_number_renumbered():
    """A prose paragraph opening on "4." and a heading-styled paragraph in
    a footnote both keep theirs: neither is a section heading."""
    foot = ('<w:footnotes><w:footnote w:id="1"><w:p><w:pPr>'
            '<w:pStyle w:val="Heading1"/></w:pPr>' + run("4. Note text")
            + "</w:p></w:footnote></w:footnotes>")

    done = sections.renumber(make_parts(
        H("1. One") + H("2. Two") + H("4. Four")
        + P("4. items are listed here."), footnotes=foot))

    assert "3. Four" in _text(done.parts)
    assert "4. items are listed here." in _text(done.parts)
    assert "4. Note text" in _text(done.parts, "word/footnotes.xml")


@pytest.mark.parametrize("tail", ["moves.x", "moves"],
                         ids=["a character more", "a character less"])
def test_renumber_REFUSES_a_rewrite_that_changes_MORE_than_numbers(
        monkeypatch: pytest.MonkeyPatch, tail: str) -> None:
    real = sections._rewrite

    def rewrite(para: str, at: int, end: int, new: str, where: str) -> str:
        return real(para, at, end, new, where).replace("moves.", tail)

    monkeypatch.setattr(sections, "_rewrite", rewrite)

    with pytest.raises(sections.AnchorError,
                       match="would change by more than its section numbers"):
        sections.renumber(make_parts(
            H("1. One") + H("3. Three") + P("Section 3 moves.")))


def test_a_refusal_names_the_PART_and_the_paragraphs_first_forty_characters():
    import re

    text = "Section 3 " + "w" * 50
    tracked = para('<w:ins w:id="1" w:author="A"><w:r><w:t>' + text
                   + "</w:t></w:r></w:ins>")

    with pytest.raises(sections.AnchorError, match=re.escape(
            f"renumber: document.xml {text[:40]!r}: the paragraph carries "
            "tracked changes")):
        sections.renumber(make_parts(H("1. One") + H("3. Three") + tracked))


# --- renumber: lists and ranges ---------------------------------------------

#: 4 is gone: 5, 6 and 7 move down one
TOP = "".join(H(f"{n}. S{n}") for n in (1, 2, 3, 5, 6, 7))
#: 3 is gone: 4 and its subsections move down one
SUBS = (H("1. One") + H("2. Two") + H("4. Four") + H("4.1 A", 2)
        + H("4.2 B", 2) + H("4.3 C", 2))
#: 3 is gone, and 4 and 5 both have subsections
TWO = (H("1. One") + H("2. Two") + H("4. Four") + H("4.1 A", 2)
       + H("4.2 B", 2) + H("5. Five") + H("5.1 C", 2) + H("5.2 D", 2)
       + H("5.3 E", 2))


def _moved(heads: str, prose: str,
           merged: dict[str, str] | None = None) -> str:
    done = sections.renumber(make_parts(heads + P(prose)), merged_into=merged)
    return _text(done.parts)


def test_a_range_MID_paragraph_keeps_its_word_and_runs_to_its_last_member():
    assert "As shown, Sections 4 to 6 hold." in _moved(
        TOP, "As shown, Sections 5 to 7 hold.")


def test_a_range_of_SUBSECTIONS_is_rewritten_under_its_stem():
    assert "Sections 3.1 to 3.3 and Sections 3.1 and 3.2." in _moved(
        SUBS, "Sections 4.1 to 4.3 and Sections 4.1 to 4.2.")


@pytest.mark.parametrize(("heads", "prose", "merged", "message"), [
    (TOP, "Sections 5, 6 to 7 hold.", None,
     "'Sections 5, 6 to 7' mixes a range with a list"),
    (TWO, "Sections 4.1 to 5.2 hold.", None,
     "'Sections 4.1 to 5.2' is not a range of sibling sections"),
    (TWO, "Sections 5.1 to 4.2 hold.", None,
     "'Sections 5.1 to 4.2' is not a range of sibling sections"),
    (H("1. One") + H("2. Two") + H("3. Three") + H("5. Five") + H("6. Six"),
     "Sections 3 to 5 hold.", {"4": "1"},
     "'Sections 3 to 5' would name sections that no longer run in one piece"),
    (TWO, "Sections 4.2 to 4.3 hold.", {"4.3": "5.3"},
     "'Sections 4.2 to 4.3' would name sections that no longer run in one "
     "piece"),
], ids=["a range mixed with a list", "stems apart", "a stem above",
        "a merge out of the run", "a merge under another stem"])
def test_renumber_REFUSES_a_range_it_cannot_rewrite_as_a_range(
        heads, prose, merged, message):
    import re

    with pytest.raises(sections.AnchorError, match=re.escape(message)):
        _moved(heads, prose, merged)


def test_a_range_and_a_list_that_now_name_ONE_section_say_so():
    assert "Section 3 and Section 3 agree." in _moved(
        H("1. One") + H("2. Two") + H("3. Three") + H("5. Five"),
        "Sections 3 to 4 and Sections 3 and 4 agree.", {"4": "3"})


def test_a_list_that_keeps_every_member_keeps_every_JOIN_as_written():
    assert "Sections 4,5 and 6 hold." in _moved(
        TOP, "Sections 5,6 and 7 hold.")


def test_a_list_that_loses_a_member_keeps_its_LAST_join_as_written():
    assert "Sections 3, 4  and  5 agree." in _moved(
        TOP, "Sections 3, 4, 5  and  6 agree.", {"4": "3"})


# --- renumber: the smallest rewrite -----------------------------------------

#: 4 is gone: 5 moves down one
GAP = H("1. One") + H("2. Two") + H("3. Three") + H("5. Five")


def _runs(*texts: str) -> str:
    return para("".join(run(t) for t in texts))


def test_a_mention_split_across_RUNS_is_rewritten_in_the_run_that_changes():
    """"Section " in one run and its number in the next: the head the two
    readings share stays put, and the edit lands in the number's run,
    ending exactly where that run does."""
    done = sections.renumber(make_parts(
        GAP + _runs("See Section ", "5", " now.")))

    assert "See Section 4 now." in _text(done.parts)


def test_a_shared_TAIL_keeps_a_rewrite_inside_the_run_that_changes():
    done = sections.renumber(make_parts(
        GAP + _runs("Sections 5", " and 2 hold.")))

    assert "Sections 4 and 2 hold." in _text(done.parts)


def test_a_rewrite_in_a_LATER_run_is_placed_by_that_runs_own_start():
    """The run starts at 9 and the number sits 8 into it, offsets that
    subtraction, XOR and a shift all read differently."""
    done = sections.renumber(make_parts(
        GAP + _runs("Look at: ", "Section 5 now.")))

    assert "Look at: Section 4 now." in _text(done.parts)


def test_a_head_shared_through_an_EN_DASH_ends_where_the_change_starts():
    """Past U+00FF a character read out of a string is a new object every
    time, so the shared head has to be compared by value to reach the
    number after the dash, in its own run."""
    done = sections.renumber(
        make_parts(H("1. One") + H("2. Two") + H("4. Four") + H("5. Five")
                   + _runs("Sections 1–", "5 hold.")),
        merged_into={"3": "2"})

    assert "Sections 1–4 hold." in _text(done.parts)


def test_a_new_number_that_PREFIXES_the_old_one_deletes_the_rest():
    """"Section 11" merged into Section 1: the shared head is all of the
    new text, and the tail may not count those characters a second
    time."""
    heads = "".join(H(f"{n}. S{n}") for n in range(1, 11))

    done = sections.renumber(make_parts(heads + P("See Section 11 here.")),
                             merged_into={"11": "1"})

    assert "See Section 1 here." in _text(done.parts)


def test_an_INSERTED_digit_lands_in_the_run_of_the_number_it_extends():
    """Section 1 merged into what is now Section 10: the rewrite only adds a
    digit, at the end of the number's run or inside a longer run, and it
    goes into the run that holds the "1"."""
    import re

    heads = "".join(H(f"{n}. S{n}") for n in range(2, 12))

    done = sections.renumber(
        make_parts(heads + _runs("See Section 1", " here.")
                   + P("Section 1 is where it starts.")),
        merged_into={"1": "11"})

    xml = done.parts["word/document.xml"].decode("utf-8")
    (see,) = [p for p in xml.split("</w:p>") if "See Section" in p]
    assert re.findall(r"<w:t[^>]*>([^<]*)</w:t>", see) == [
        "See Section 10", " here."]
    assert "Section 10 is where it starts." in _text(done.parts)


def test_a_DELETED_digit_is_bounded_by_the_head_the_readings_share():
    """"Sections 11 and 3" into 1 shares a head and a tail that would both
    claim the second 1, and "Section 12" into 2 a tail one character long:
    the tail steps one character at a time and stops where the head
    leaves off."""
    heads = "".join(H(f"{n}. S{n}") for n in range(1, 11))

    done = sections.renumber(
        make_parts(heads + P("Sections 11 and 3 agree.")
                   + P("See Section 12.")),
        merged_into={"11": "1", "12": "2"})

    assert "Sections 1 and 3 agree." in _text(done.parts)
    assert "See Section 2." in _text(done.parts)


def test_numbers_and_counts_past_256_are_COMPARED_by_value():
    """CPython keeps one object for each small int up to 256; past it a
    number or a count computed twice is two objects, and only equality can
    say that 258 follows 257, or that a list of 257 kept every member."""
    heads = "".join(H(f"{n}. S{n}") for n in (*range(1, 261), 262))
    many = "Sections " + ", ".join(str(n) for n in range(1, 258)) + " hold."

    done = sections.renumber(make_parts(
        heads + P("Sections 257 to 260 hold.") + P(many)))

    assert "Sections 257 to 260 hold." in _text(done.parts)
    assert many in _text(done.parts)


def test_a_shared_head_or_tail_LONGER_than_256_characters_bounds_the_edit():
    """Section 100 merged into Section 10 at the end of a long list, where
    the new reading is all head, and at its start, where it is all head and
    tail: the bounds are ints past 256, which identity cannot compare."""
    heads = "".join(H(f"{n}. S{n}") for n in range(1, 100))
    rest = ", ".join(str(n) for n in (*range(1, 10), *range(11, 100)))

    done = sections.renumber(
        make_parts(heads + P(f"Sections {rest} and 100 hold.")
                   + P(f"Sections 100, {rest} hold.")),
        merged_into={"100": "10"})

    text = _text(done.parts)
    assert f"Sections {rest} and 10 hold." in text
    assert f"Sections 10, {rest} hold." in text


@pytest.mark.parametrize("mention", [
    "<w:r><w:tab/><w:t>Section 4</w:t></w:r>",
    '<w:r><w:t xml:space="preserve">Section </w:t><w:t>4</w:t></w:r>',
], ids=["one w:t and a tab", "two w:t"])
def test_renumber_REFUSES_a_run_that_is_not_ONE_plain_w_t(mention):
    with pytest.raises(sections.AnchorError, match="inside one plain run"):
        sections.renumber(make_parts(
            H("1. One") + H("2. Two") + H("4. Four") + para(mention)))
