"""The section numbering and every mention of it.

Aging_Well, 2026-09-10: a merged heading left the sections running
1 2 3 5 6 7 8 9 and seven sentences pointing at a Section 4 that was
gone, and nine gates exited 0 on it. Every shape here is one the paper's
own `r122_section_integrity.py` met, or one its port had to generalise:
any heading depth, any appendix letter, lists of three, dashed ranges,
the `§` form, notes read as well as the body.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit import sections


def H(text: str, level: int = 1) -> str:
    return para(f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
                + run(text))


def OUTLINE(text: str, level: int = 1) -> str:
    return para(f'<w:pPr><w:outlineLvl w:val="{level - 1}"/></w:pPr>'
                + run(text))


def P(text: str) -> str:
    return para(run(text))


def doc(*body: str, footnotes: str | None = None) -> dict[str, bytes]:
    return make_parts("".join(body), footnotes=footnotes)


HEALTHY = (H("1. Introduction") + P("Section 2 sets out the model.")
           + H("2. The model") + H("2.1 Setup", 2) + H("2.2 Results", 2)
           + P("Sections 2.1 and 2.2 above; see also Appendix A.1 and A.2.")
           + H("3. Conclusion") + P("Sections 1 to 3 close the paper (§2.2).")
           + H("References") + H("Appendix A") + H("A.1 Proofs", 2)
           + H("A.2 Data", 2))


def test_a_healthy_numbering_reports_every_mention_and_no_breach():
    report = sections.audit(doc(HEALTHY))

    assert report.ok, report.breaches
    assert report.sections == ["1", "2", "2.1", "2.2", "3", "A.1", "A.2"]
    assert report.mentions == 6, "one per phrase, a list or range being one"
    assert "ok - the headings run 1..N" in report.format()


# --- Word's own list numbers ----------------------------------------------
#
# Six of eight real manuscripts number their headings through numbering.xml
# and type no digit, so the audit read none of their sections and reported
# every "Section N" as a breach (2026-09-12). The reader was held to Word's
# own ListString on those papers: 246 headings and list items, 0 differing.


def LVL(ilvl: int, text: str, *, fmt: str = "decimal", start: int = 1,
        style: str = "", legal: bool = False) -> str:
    return (f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="{start}"/>'
            f'<w:numFmt w:val="{fmt}"/>'
            + (f'<w:pStyle w:val="{style}"/>' if style else "")
            + ("<w:isLgl/>" if legal else "")
            + f'<w:lvlText w:val="{text}"/></w:lvl>')


def NUMBERING(levels: str, *, override: str = "") -> str:
    return ('<w:numbering><w:abstractNum w:abstractNumId="7">'
            f"{levels}</w:abstractNum>"
            '<w:num w:numId="4"><w:abstractNumId w:val="7"/>'
            f"{override}</w:num></w:numbering>")


def STYLE(sid: str, *, numpr: str = "", based: str = "") -> str:
    return (f'<w:style w:type="paragraph" w:styleId="{sid}">'
            + (f'<w:basedOn w:val="{based}"/>' if based else "")
            + (f"<w:pPr><w:numPr>{numpr}</w:numPr></w:pPr>" if numpr else "")
            + "</w:style>")


#: HCW's shape: Heading2 states only `ilvl` 1 and takes numId 4 from the
#: Heading1 it is based on.
HCW = {
    "word/styles.xml": "<w:styles>"
    + STYLE("Heading1", numpr='<w:numId w:val="4"/>')
    + STYLE("Heading2", numpr='<w:ilvl w:val="1"/>', based="Heading1")
    + "</w:styles>",
    "word/numbering.xml": NUMBERING(LVL(0, "%1.", style="Heading1")
                                    + LVL(1, "%1.%2.", style="Heading2")),
}


def NUM(text: str, ilvl: int, num: int = 4) -> str:
    return para(f'<w:pPr><w:pStyle w:val="Heading{ilvl + 1}"/><w:numPr>'
                f'<w:ilvl w:val="{ilvl}"/><w:numId w:val="{num}"/>'
                f"</w:numPr></w:pPr>" + run(text))


def test_word_numbers_a_heading_through_its_STYLE_and_the_basedOn_chain():
    parts = make_parts(H("Introduction") + H("Data") + H("Sources", 2)
                       + H("Coverage", 2) + H("Countries", 2) + H("Results")
                       + P("Section 2.3 and Sections 1 to 3 hold."),
                       extra=HCW)

    report = sections.audit(parts)

    assert [(h.number, h.listed) for h in report.headings] == [
        ("1", True), ("2", True), ("2.1", True), ("2.2", True),
        ("2.3", True), ("3", True)]
    assert report.ok and report.checked
    assert report.mentions == 2


def test_list_numbers_prints_what_Word_prints_and_RESTARTS_the_deeper_level():
    body = (H("A") + H("B", 2) + H("C", 2) + H("D", 2) + H("E") + H("F", 2)
            + P("plain"))

    nums = sections.list_numbers(make_parts(body, extra=HCW))

    assert nums == {0: "1.", 1: "1.1.", 2: "1.2.", 3: "1.3.", 4: "2.",
                    5: "2.1."}


def test_the_paragraphs_own_numPr_its_REMOVAL_a_start_override_and_formats():
    """A paragraph's own `numPr` over its style's, `numId` 0 as no
    number at all, `startOverride` over `start`, a roman top level, and
    `isLgl` printing the level beneath it in decimals."""
    numbering = NUMBERING(
        LVL(0, "%1.", fmt="upperRoman", start=3)
        + LVL(1, "%1.%2", legal=True),
        override='<w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/>'
                 "</w:lvlOverride>")
    body = (NUM("First", 0) + NUM("Sub", 1) + NUM("Unnumbered", 0, num=0)
            + NUM("Second", 0))

    nums = sections.list_numbers(make_parts(
        body, extra={"word/numbering.xml": numbering,
                     "word/styles.xml": "<w:styles/>"}))

    assert nums == {0: "V.", 1: "5.1", 3: "VI."}


def test_a_bullet_is_not_a_number_and_letters_run_on_past_z():
    numbering = NUMBERING(LVL(0, "%1)", fmt="lowerLetter", start=26)
                          + LVL(1, "•", fmt="bullet"))
    body = NUM("z", 0) + NUM("aa", 0) + NUM("dot", 1)

    nums = sections.list_numbers(make_parts(
        body, extra={"word/numbering.xml": numbering}))

    assert nums == {0: "z)", 1: "aa)"}


def test_a_paper_with_no_numbered_heading_is_NOT_CHECKED_not_all_breaches():
    """LEtrends marks no heading at all and cites Section 4 three times."""
    report = sections.audit(doc(
        P("The model in Section 4 corrects for it."),
        P("Sections 2 and 4 agree; Section 4 again.")))

    assert report.ok and report.breaches == []
    assert not report.checked
    assert report.mentions == 3
    assert "not checked - no heading carries a number" in report.format()


def test_a_listed_paper_still_reports_a_section_it_does_not_have():
    parts = make_parts(H("Introduction") + H("Results") + H("Conclusion")
                       + P("As Section 5 shows."), extra=HCW)

    assert sections.audit(parts).breaches == [
        "Section 5: no such section  …As Section 5 shows.…"]


def test_the_MERGE_is_found_in_the_headings_and_in_every_mention():
    """The one-keystroke edit: Section 4's heading deleted. The hole,
    the dangling mentions, and the range that ends on it."""
    merged = (H("1. Introduction") + H("2. Data") + H("3. Model")
              + P("The elasticity has not been estimated (Section 4).")
              + H("5. Results")
              + P("Sections 2 through 4 set this up; Section 5 tests it.")
              + H("6. Conclusion"))

    report = sections.audit(doc(merged))

    assert not report.ok
    assert report.breaches == [           # the headings, then document order
        "the top-level headings run 1 2 3 5 6 — expected 1 2 3 4 5",
        "Section 4: no such section  …The elasticity has not been estimated "
        "(Section 4).…",
        "Sections 2 through 4: no Section 4  …Sections 2 through 4 set this "
        "up; Section 5 tests it.…",
    ]


def test_a_subsection_under_the_wrong_parent_and_a_gap_in_the_minors():
    body = (H("1. One") + H("1.1 First", 2) + H("1.3 Third", 2)
            + H("2. Two") + H("1.2 Stray", 2) + H("3. Three")
            + H("3.1 Fine", 2))

    report = sections.audit(doc(body))

    assert report.breaches == [
        "Section 1.2: sits under Section 2",
        "Section 1: subsections run 1.1 1.3 1.2",
    ]


def test_a_subsection_with_no_heading_above_it_says_so():
    (breach,) = sections.audit(doc(H("2.1 Orphan", 2) + H("1. One"))).breaches
    assert breach == "Section 2.1: no top-level heading above it"


def test_a_subsection_that_SKIPS_a_level_names_the_level_it_skips():
    """"1.1.1" straight under "1." was reported as having no top-level
    heading above it, with Section 1 right there: what is missing is 1.1
    (mutation sweep, 2026-09-13)."""
    skipped = sections.audit(doc(H("1. One") + H("1.1.1 Deep", 3))).breaches
    deeper = sections.audit(doc(H("1. One") + H("1.1 A", 2)
                                + H("1.1.1.1 Deep", 4))).breaches

    assert skipped == ["Section 1.1.1: no Section 1.1 above it"]
    assert deeper == ["Section 1.1.1.1: no Section 1.1.1 above it"]


def test_a_number_used_twice_is_named_once():
    report = sections.audit(doc(H("1. One") + H("2. Two") + H("2. Again")
                                + H("3. Three")))

    assert report.breaches == ["Section 2: the number is used twice",
                               "the top-level headings run 1 2 2 3 — "
                               "expected 1 2 3 4"]


def test_the_appendix_runs_under_its_own_letter_whatever_it_is():
    body = (H("1. One") + H("Appendix B: Proofs") + H("B.1 First", 2)
            + H("B.3 Third", 2) + P("See Appendix B.2 and B.3, and B.1."))

    report = sections.audit(doc(body))

    assert report.breaches == [
        "the appendix subheads run B.1 B.3",
        "B.2: no such appendix section  …See Appendix B.2 and B.3, and "
        "B.1.…",
    ]


def test_an_appendix_subhead_before_the_appendix_heading_is_a_breach():
    (breach,) = sections.audit(doc(H("1. One") + H("A.1 Early", 2)
                                   + H("Appendix"))).breaches
    assert breach.startswith("A.1 'Early': an appendix subhead before")


def test_a_bare_letter_number_is_a_mention_only_where_the_paper_has_one():
    """"Table A.3" and a paper with no appendix at all: an initial, a
    decimal or an exhibit number must not read as a dangling section."""
    no_appendix = doc(H("1. One") + P("See A.3 and Table A.5; J. A.1 wrote."))
    with_one = doc(H("1. One") + H("Appendix A") + H("A.1 Only", 2)
                   + P("See Table A.5, then A.3, and J. A.1 wrote it."))

    assert sections.audit(no_appendix).ok
    assert sections.audit(with_one).breaches == [
        "A.3: no such appendix section  …See Table A.5, then A.3, and J. "
        "A.1 wrote it.…"]


def test_a_range_must_run_upward_but_a_list_may_be_in_any_order():
    body = (H("1. One") + H("2. Two") + H("3. Three")
            + P("Sections 3 to 1 is backwards; Sections 3, 1 and 2 is a "
                "list; Sections 1–3 is a range; Sections 3–1 is not."))

    report = sections.audit(doc(body))

    assert [b.split("  ")[0] for b in report.breaches] == [
        "Sections 3–1: the range does not run upward",
        "Sections 3–1: the range does not run upward"]
    assert report.mentions == 4


def test_a_list_of_three_is_checked_to_its_last_member():
    """`r122` read the first two members of "Sections 2, 3 and 4" and
    never saw the 4."""
    body = H("1. One") + H("2. Two") + P("Sections 1, 2 and 9 are cited.")

    (breach,) = sections.audit(doc(body)).breaches

    assert breach.startswith("Sections 1, 2 and 9: no Section 9")


def test_footnotes_are_read_and_the_section_sign_counts():
    foot = ('<w:footnotes><w:footnote w:id="1"><w:p>'
            + run("See §7 for the proof.") + "</w:p></w:footnote>"
            "</w:footnotes>")

    report = sections.audit(doc(H("1. One") + P("Body."), footnotes=foot))

    assert report.breaches == ["Section 7: no such section  …See §7 for the "
                               "proof.…"]


def test_a_heading_by_OUTLINE_level_counts_and_a_numbered_paragraph_does_not():
    body = (OUTLINE("1. Introduction") + P("2. Not a heading, a list item.")
            + OUTLINE("2. Model") + OUTLINE("2.1 Setup", 2))

    report = sections.audit(doc(body))

    assert report.ok and report.sections == ["1", "2", "2.1"]
    assert [h.level for h in report.headings] == [1, 1, 2]


def test_number_of_reads_a_section_off_its_TITLE():
    """The gate that held a literal 5 reported the paper's own displays
    as breaches after a renumbering. The title is what stays."""
    report = sections.audit(doc(HEALTHY))

    assert report.number_of("the model") == "2"
    assert report.number_of("SETUP") == "2.1"
    assert report.number_of("Proofs") == "A.1"
    assert report.number_of("Nowhere") is None


def test_the_report_names_the_breaches_and_the_run():
    text = sections.audit(doc(H("1. One") + H("3. Three"))).format()

    assert "2 heading(s), 2 section(s), 0 appendix subsection(s)" in text
    assert "sections : 1 3" in text
    assert "** 1 breach(es)" in text and "run 1 3 — expected 1 2" in text


# --- renumber: the second half ----------------------------------------------
#
# Ported from Aging_Well's R123 and held to it: run on the file R123 started
# from, the result is byte-identical to R123's in all three text parts.

MERGED = (H("1. Introduction") + H("2. Data") + H("3. Model")
          + P("Sections 2 through 4 set this up (Section 4).")
          + H("5. Results") + H("5.1 Main", 2) + H("5.2 Robustness", 2)
          + P("Section 5.2 and Section 6 check Section 5.")
          + H("6. Conclusion") + P("Sections 3, 4 and 5 hold; see §5.1."))


def _body(parts: dict[str, bytes]) -> str:
    from docxkit._xml import visible_text
    return visible_text(parts["word/document.xml"].decode("utf-8"))


def test_renumber_closes_a_MERGE_in_one_pass_with_the_ranges_rewritten():
    """4 went into 3 while 5 went down to 4: a map no sequential 5->4,
    6->5 can apply, and ranges that must be REWRITTEN, not mapped."""
    done = sections.renumber(doc(MERGED), merged_into={"4": "3"})

    after = sections.audit(done.parts)
    assert after.ok, after.breaches
    assert after.sections == ["1", "2", "3", "4", "4.1", "4.2", "5"]
    body = _body(done.parts)
    assert "Sections 2 and 3 set this up (Section 3)." in body
    assert "Section 4.2 and Section 5 check Section 4." in body
    assert "Sections 3 and 4 hold; see §4.1." in body
    assert done.numbers == {"5": "4", "5.1": "4.1", "5.2": "4.2", "6": "5",
                            "4": "3"}
    assert ("5", "4", "Results") in done.headings
    assert done.paragraphs == 7


def test_renumber_REFUSES_a_mention_it_cannot_place():
    import pytest

    from docxkit.errors import AnchorError

    with pytest.raises(AnchorError, match="Section 4 is mentioned and no "
                                          "heading carries it"):
        sections.renumber(doc(MERGED))


def test_renumber_refuses_what_it_cannot_do_SAFELY():
    import pytest

    from docxkit.errors import AnchorError

    gap = H("1. One") + H("2. Two") + H("4. Four")
    tabbed = para('<w:r><w:t xml:space="preserve">see Section </w:t>'
                  "<w:tab/><w:t>4</w:t></w:r>")
    tracked = para('<w:ins w:id="1" w:author="A"><w:r><w:t>See Section 4.'
                   "</w:t></w:r></w:ins>")
    cases = [
        (make_parts(H("Introduction") + H("Results"), extra=HCW),
         "Word numbers these headings itself"),
        (doc(gap + tabbed), "inside one plain run"),
        (doc(gap + tracked), "tracked changes"),
        (doc(H("1. One") + H("2. Two") + H("2. Again") + H("4. Four")),
         "used twice"),
        (doc(H("1. One") + H("2.1 Stray", 2) + H("3. Three")),
         "does not sit under Section 2"),
        (doc(P("Section 4 of nothing.")), "no heading carries a typed"),
    ]
    for parts, message in cases:
        with pytest.raises(AnchorError, match=message):
            sections.renumber(parts)


def test_renumber_checks_what_merged_into_SAYS():
    import pytest

    from docxkit.errors import AnchorError

    gap = doc(H("1. One") + H("2. Two") + H("4. Four") + P("See Section 3."))

    with pytest.raises(AnchorError, match="a heading still carries it"):
        sections.renumber(gap, merged_into={"2": "1"})
    with pytest.raises(AnchorError, match="to Section 7, and no heading"):
        sections.renumber(gap, merged_into={"3": "7"})


def test_a_healthy_numbering_comes_back_UNTOUCHED_and_a_rerun_is_a_no_op():
    healthy = doc(HEALTHY)
    assert sections.renumber(healthy).parts is healthy

    once = sections.renumber(doc(MERGED), merged_into={"4": "3"})
    twice = sections.renumber(once.parts, merged_into={"4": "3"})

    assert not twice.changed and twice.parts is once.parts
    assert "nothing to renumber" in twice.format()


def test_renumber_closes_an_APPENDIX_gap_under_its_own_letter():
    body = (H("1. One") + P("Appendix B.3 and B.2 hold.") + H("Appendix B")
            + H("B.1 First", 2) + H("B.3 Third", 2))

    done = sections.renumber(doc(body), merged_into={"B.2": "B.1"})

    assert "Appendix B.2 and B.1 hold." in _body(done.parts)
    assert sections.audit(done.parts).sections == ["1", "B.1", "B.2"]
    assert "heading B.3 -> B.2  Third" in done.format()


# --- code review, 2026-09-13 ------------------------------------------------


def _changed(live: str, old: str) -> str:
    """A `w:pPr` holding `live`, with a tracked change that replaced `old`."""
    return ("<w:pPr>" + live + '<w:pPrChange w:id="9" w:author="A">'
            "<w:pPr>" + old + "</w:pPr></w:pPrChange></w:pPr>")


def test_list_numbers_reads_the_LIVE_numbering_not_the_tracked_change():
    """`_PPR_RE` stops at the FIRST `</w:pPr>`, the one inside a
    `w:pPrChange`, so the strip meant to drop that snapshot found no close
    to match and the OLD `numPr` was read as current: a heading whose
    numbering the author removed went on being numbered. The same held for
    a style the change replaced."""
    unnumbered = para(_changed(
        '<w:pStyle w:val="Heading1"/>',
        '<w:pStyle w:val="Heading1"/><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="4"/></w:numPr>') + run("Was numbered"))
    own = {"word/numbering.xml": NUMBERING(LVL(0, "%1.")),
           "word/styles.xml": "<w:styles/>"}
    restyled = para(_changed("", '<w:pStyle w:val="Heading1"/>')
                    + run("Was a heading"))

    assert sections.list_numbers(make_parts(
        NUM("First", 0) + unnumbered + NUM("Second", 0), extra=own)
        ) == {0: "1.", 2: "2."}
    assert sections.list_numbers(make_parts(
        H("Intro") + restyled + H("Next"), extra=HCW)) == {0: "1.", 2: "2."}


def test_an_EQUATION_or_an_exhibit_list_is_not_an_appendix_section():
    """"(A.7)" is an equation, and "Tables A.3 and A.4", "Figures A.1–A.2"
    and "Table A.5" with a no-break space are exhibits. The bare reading
    took each for a section — a breach per mention in a paper whose
    appendix equations run past its subsections — and `renumber` rewrote
    the equation's number with the section's."""
    paper = doc(H("1. One") + H("Appendix A") + H("A.1 Proofs", 2)
                + H("A.2 Data", 2)
                + P("The first-order condition (A.7) gives it; Tables A.3 "
                    "and A.4, Figures A.1–A.2 and Table A.5 show it, "
                    "as A.2 says."))
    gap = doc(H("1. One") + P("By (A.3) and Table A.3, as A.3 shows.")
              + H("Appendix A") + H("A.1 First", 2) + H("A.3 Third", 2))

    report = sections.audit(paper)
    done = sections.renumber(gap)

    assert report.ok, report.breaches
    assert report.mentions == 1, "A.2, and nothing else"
    assert "By (A.3) and Table A.3, as A.2 shows." in _body(done.parts)


def test_renumber_sends_a_mention_ACROSS_letters_with_its_letter():
    """`merged_into={"A.3": "B.1"}` kept the A and swapped the number:
    "Appendix A.1", a section that exists, so the audit after passed it."""
    body = (H("1. One") + P("Appendix A.3 and A.3 moved.") + H("Appendix A")
            + H("A.1 First", 2) + H("A.2 Second", 2) + H("Appendix B")
            + H("B.1 Moved here", 2))

    done = sections.renumber(doc(body), merged_into={"A.3": "B.1"})

    assert "Appendix B.1 and B.1 moved." in _body(done.parts)


# --- mutation sweep, 2026-09-13 ---------------------------------------------


def test_renumber_REFUSES_a_range_that_does_not_run_upward():
    """`_list_phrase` listed "Sections 3 to 1" as an empty range and
    formatted its first member: an IndexError, where every other refusal
    names the phrase. The audit's rule decides, and it counts equal ends
    as not running upward too."""
    import re

    import pytest

    from docxkit.errors import AnchorError

    for phrase in ("Sections 3 to 1", "Sections 3–3"):
        gap = doc(H("1. One") + H("2. Two") + H("3. Three") + H("5. Five")
                  + P(f"{phrase} are cited."))
        with pytest.raises(AnchorError,
                           match=re.escape(f"{phrase!r} does not run up")):
            sections.renumber(gap)

    # judged by the LAST parts: a range of subsections runs upward though
    # its stem equals the first end's last part, or the final end's (three
    # members each, since a range of two is rewritten as "X and Y")
    stems = doc(H("1. One") + H("2. Two") + H("2.1 A", 2) + H("2.2 B", 2)
                + H("2.3 C", 2) + H("2.4 D", 2) + H("3. Three")
                + H("3.1 E", 2) + H("3.2 F", 2) + H("3.3 G", 2)
                + H("5. Five")
                + P("Sections 2.2 to 2.4, and Sections 3.1 to 3.3."))

    assert "Sections 2.2 to 2.4, and Sections 3.1 to 3.3." in _body(
        sections.renumber(stems).parts)
