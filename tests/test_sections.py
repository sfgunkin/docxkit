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
