"""`refstyle` — the shapes its 2026-09-29 sweep survivors needed.

The module measured at 141 real survivors of 1,688; a harness gap
(`test_locator_separator.py`, now in the map) accounted for 52 of them.
Each test here names the survivor it was written for; the argued rest is
in equivalents.toml.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run
from test_locator_separator import entries
from test_refstyle import (
    _SWALLOWED,
    _entry_para,
    _linked,
    _mark,
    _ordered_list,
    irun,
)
from test_refstyle_layout import LONG_A, _list_with, entry, heading

from docxkit.refstyle import (
    _locator_findings,
    _read_label,
    audit,
    check_prose,
    convert_entry,
    convert_text,
    layout,
    refile,
)

# ------------------------------------- the locator audit's two bounds ---
#
# `_locator_findings` stays silent unless the majority separator holds
# at least 90 % of the list AND the dissenters are at most two. The
# existing fixtures sat far from both edges (41 of 42; 31 against 8;
# 5 against 1), so every arithmetic spelling of either bound that still
# separated those three survived. These sit ON the edges.


def _seps(found):
    return [(i.where, i.message) for i in found]


def test_NINE_of_ten_is_a_practice_and_the_tenth_is_reported():
    """`or n_top <= 0.9 * len(seen)` (L1041). Nine of ten is exactly the
    90 % line, and it is the smallest list whose one slip gets reported —
    a short bibliography, which is where an author least expects a
    tool to have noticed anything."""
    found = _locator_findings(entries(*(["12(3): 45–67"] * 9),
                                      "12(3); 45–67"))

    assert len(found) == 1, _seps(found)
    assert found[0].message == ('the issue takes ":" before the pages here '
                                '— this entry has ";", and 9 of 10 agree '
                                'on ":"')
    assert found[0].where == "¶20"


def test_EIGHT_of_nine_is_below_the_line_and_says_nothing():
    """L1041's other spellings — `and`, `==`, `is`, and the arithmetic
    that makes the 90 % bound unreachable (`0.9 - n`, `0.9 / n`, `0.9 **
    n`, `0.9 % n`, `0.9 // n`, `-0.1 * n`). Eight of nine clears the
    floor of eight and the cap of two dissenters, so the 90 % rule is the
    ONLY thing keeping it quiet: an 89 % majority is not yet a practice
    the ninth entry can be said to break."""
    assert _locator_findings(entries(*(["12(3): 45–67"] * 8),
                                     "12(3); 45–67")) == []


def test_TWO_slips_in_twenty_two_are_both_reported():
    """`> _LOCATOR_ODD` spelled `>=`, `==`, `is`, and `_LOCATOR_ODD = 1`
    (L1040, L1001). Two dissenters is the most the rule still calls
    slips — the Parental_style list had one, and a list with a comma
    slip AND a semicolon slip is the same defect twice."""
    found = _locator_findings(entries(*(["12(3): 45–67"] * 20),
                                      "12(3), 45–67", "12(3), 45–67"))

    assert [i.where for i in found] == ["¶31", "¶32"], _seps(found)
    assert all(i.message.endswith('this entry has ",", and 20 of 22 agree '
                                  'on ":"') for i in found), _seps(found)


def test_THREE_dissenters_are_a_second_convention_even_at_93_percent():
    """`and` for `or` between the floor and the cap, `/`, `//` and `>>`
    for the minus, `== _LOCATOR_ODD`, and `_LOCATOR_ODD = 3` (L1040,
    L1001). Forty against three passes the 90 % rule (40 of 43), so the
    cap of two is the only bound that holds it: three entries set the
    same other way are a source the list was assembled from, not a
    slip, and reporting them tells the author what they already know."""
    assert _locator_findings(entries(*(["12(3): 45–67"] * 40),
                                     *(["12(3), 45–67"] * 3))) == []


def test_a_SEMICOLON_slip_and_a_COMMA_slip_in_one_list_are_both_named():
    """`len(counts) != 2` (L1037). Three separators is the ordinary
    shape of a long list with two unrelated typos in it, and a guard
    written for "exactly two conventions" goes silent on it — the one
    list with the most to report."""
    found = _locator_findings(entries(*(["12(3): 45–67"] * 20),
                                      "12(3); 45–67", "12(3), 45–67"))

    assert [i.where for i in found] == ["¶31", "¶32"], _seps(found)
    assert '";"' in found[0].message and '","' in found[1].message


def test_a_FULL_WIDTH_colon_list_names_only_the_one_ascii_dissenter():
    """`sep is not top` (L1048). A bibliography typed through a CJK input
    method writes the full-width colon "：" (U+FF1A) throughout. CPython
    caches single Latin-1 characters, so for ":" ";" "," identity and
    equality agree — but a character outside Latin-1 is a new string
    object per match, and an identity test then reports every entry that
    AGREES with the majority as departing from it."""
    found = _locator_findings(entries(*(["12(3)：45–67"] * 20),
                                      "12(3): 45–67"))

    assert [i.where for i in found] == ["¶31"], _seps(found)
    assert '"："' in found[0].message and '20 of 21' in found[0].message


# ---------------------------------------------- the converter's edges ---


def test_a_YEAR_fix_behind_a_SHORT_institutional_author_quotes_all_of_it():
    """`max(0, at - 8)` spelled `max(-1, …)`, `max(1, …)` and `at ^ 8`
    (L430). "OECD. 2019." puts the year six characters in, so the
    eight-character lead is clipped at the START of the entry — and the
    three spellings clip it to nothing, to "ECD. ", and (6 ^ 8 = 14,
    past the year) to nothing again. Institutional authors are exactly
    the short leads a reference list has."""
    text = 'OECD. 2019. "Pensions at a Glance." Paris: OECD Publishing.'

    (year,) = [f for f in convert_entry(text) if f.code == "year-parens"]

    assert (year.old, year.new) == ("OECD. 2019.", "OECD. (2019).")


def test_a_title_word_CONTAINING_doi_does_not_end_the_range_scan():
    """`continue` spelled `break` (L434). The DOI exemption is a
    substring test, so "Doing" in "Doing Business 2020" reads as a DOI
    and is skipped — and a `break` there would skip every token after
    it, leaving the hyphen page range at the end unconverted while the
    audit keeps reporting it."""
    text = ("World Bank. (2020). Doing Business 2020. Washington, DC: "
            "World Bank, pp. 45-48.")

    out, fixes = convert_text(text)

    assert out.endswith("pp. 45–48.")
    assert [f.code for f in fixes] == ["en-dash"]


@pytest.mark.parametrize(("tail", "old", "new"), [
    ("2188—2244.", "2188—2244", "2188–2244"),     # an em-dash, pasted
    ("174–79.", "174–79", "174–179"),             # Chicago's abbreviation
])
def test_a_range_that_SORTS_BELOW_its_fix_is_still_fixed(tail, old, new):
    """`fixed != r.group(0)` spelled `>` (L437). The en-dash sorts above
    a hyphen, so a fixture of hyphen ranges cannot tell the two apart —
    but it sorts BELOW an em-dash (U+2013 < U+2014), and "174–179" sorts
    below "174–79". Both are ranges a list converted from another house
    style really holds."""
    out, fixes = convert_text(f'Smith, J. (2020). "T." Journal, 12(3): {tail}')

    assert [(f.code, f.old, f.new) for f in fixes] == [("en-dash", old, new)]
    assert out.endswith(new + ".")


def test_a_range_whose_EXPANSION_sorts_higher_still_passes_the_invariant():
    """`before != after` spelled `>` and `>=` (L553). The invariant's
    first test is what lets a legitimate expansion be accounted for; a
    `>` there accounts only for expansions that happen to sort the
    stripped entry DOWN. "945-50" becomes "945–950", which sorts UP
    ("94550" < "945950"), and the mutant refuses a correct conversion."""
    out, fixes = convert_text('Smith, J. (2020). "T." Journal, 12(3): 945-50.')

    assert out.endswith("945–950.")
    assert [f.code for f in fixes] == ["en-dash"]


def test_the_expansion_is_accounted_for_ONCE_when_its_digits_recur():
    """`replace(..., 1)` spelled `2` (L557). The accounting rewrites the
    stripped entry's FIRST occurrence of the range's digits; DOIs very
    often end in digits, and one that repeats the page numbers gives the
    string a second occurrence. Rewriting that one too makes a correct
    conversion read as a changed DOI, and refuses it."""
    text = ('Smith, J. (2020). "T." Journal, 12(3): 174-79. '
            "https://doi.org/10.1000/17479.")

    out, _ = convert_text(text)

    assert out == ('Smith, J. (2020). "T." Journal, 12(3): 174–179. '
                   "https://doi.org/10.1000/17479.")


def test_a_page_space_fix_rewrites_EXACTLY_the_three_characters_it_quotes():
    """`sp.end() + 3` spelled `^ 3` and `| 3`, on both the old and the new
    fragment (L452, L454). `+ 3` and `| 3` agree whenever the offset is a
    multiple of four, which every fixture's was; here it is not. A
    fragment one character short on either side still passes the
    letters-and-digits invariant — it only loses or doubles a DASH —
    so the output text is the only thing that shows it."""
    text = "Sen, A. (1999). Development as Freedom. New York: Knopf, p.87-110."

    out, _ = convert_text(text)

    assert out == ("Sen, A. (1999). Development as Freedom. New York: Knopf, "
                   "p. 87–110.")


# ------------------------------------------------ the prose-side scan ---


def test_a_YEAR_GROUP_does_not_end_the_checks_on_the_citations_after_it():
    """`continue` spelled `break` (L228). "Sen (1985, 1992)" is two
    citations, and the second's span is "1992)", which does not show the
    author — the per-name checks skip it. A `break` there skips every
    citation after it in the paragraph too, and the "&" three words on
    goes unreported."""
    issues = check_prose("Sen (1985, 1992) and Smith & Jones (2020) agree.")

    assert [(i.code, i.snippet) for i in issues] == [
        ("ampersand", "Smith & Jones (2020)")]


def test_an_IGNORED_lead_does_not_end_the_cited_scan_of_its_paragraph():
    """`continue` spelled `break` (L1575). "in March (2020)" is the
    grammar's own example of a capitalised word that is not an author;
    it is dropped by the ignore list. A `break` there drops every
    citation after it in the same sentence, and Smith's entry reads as
    UNCITED — a finding that invites deleting a cited work."""
    body = (para(run("Unemployment peaked in March (2020), as Smith (2020) "
                     "documents."))
            + para(run("References"))
            + para(run("Smith, J. (2020). "),
                   irun("The Lockdown Labor Market"),
                   run(". Princeton: Princeton University Press.")))

    report = audit(make_parts(body), page_layout=None)

    assert "smith_2020" in report.cited, report.cited
    assert "uncited-ref" not in {i.code for i in report.issues}


def test_a_link_to_a_TABLE_before_a_linked_citation_does_not_hide_it():
    """`continue` spelled `break` in `_credit_links` (L1354). A
    cross-reference to "Table 3" and a linked citation in one sentence is
    the ordinary paragraph of an empirical paper. The table's link points
    at no entry, and a `break` on it stops the walk before the citation's
    link — whose label is what re-reads the swallowed "Surveys and
    ILOSTAT (2024)" — so the paper gets a `missing-ref` it cannot clear."""
    parts = make_parts(
        para(run("As "), _linked("Table3", "Table 3"),
             run(" shows. " + _SWALLOWED),
             _linked("ILOSTAT2024", "ILOSTAT (2024)"),
             run(" data on employment."))
        + _mark("Table3")
        + para(run("References")) + _mark("ILOSTAT2024") + _entry_para())

    report = audit(parts)

    assert not {i.code for i in report.issues} & {"missing-ref",
                                                   "uncited-ref"}, [
        (i.code, i.snippet) for i in report.issues]
    assert list(report.cited) == ["ilostat_2024"]


def test_a_linked_YEAR_GROUP_keeps_the_span_the_linker_gave_it():
    """`lab != span` spelled `lab is not span` (L1420), which the note in
    test_refstyle.py argues is equivalent. It is not: docxkit's own
    linker wraps each work of "Sen (1985, 1992)" separately, so the first
    link's label is "Sen (1985" — a string that does not parse alone and
    re-reads, parentheses restored, one character LONGER. Treating the
    equal label as a swallowed one moves the citation's end onto the
    comma, and the snippet the report quotes for the work with it."""
    def sen(year: str, title: str) -> str:
        return (_mark(f"Sen{year}")
                + para(run(f"Sen, A. ({year}). "), irun(title),
                       run(". Oxford: Oxford University Press.")))

    parts = make_parts(
        para(_linked("Sen1985", "Sen (1985"), run(", "),
             _linked("Sen1992", "1992)"), run(" argues it."))
        + para(run("References"))
        + sen("1985", "Commodities and Capabilities")
        + sen("1992", "Inequality Reexamined"))

    report = audit(parts, page_layout=None)

    assert report.cited == {"sen_1985": ("¶1", "Sen (1985"),
                            "sen_1992": ("¶1", "1992)")}


def test_a_PARENTHETICAL_label_is_read_back_at_its_own_END_too():
    """`end=f.end - 1` spelled `f.end ^ 1` (L1447). Every earlier fixture
    had an ODD end in the restored string, where `- 1` and `^ 1` agree.
    "(Kanbur 2007)" ends at 12: the shift gives 11, the end of the
    label, and the mutant 13 — two characters past a label eleven long,
    which is a snippet that runs into the next words of the sentence."""
    assert [(f.start, f.end) for f in _read_label("Kanbur 2007")] == [(0, 11)]


# ----------------------------------- what the list-level reports quote ---


RUSSIAN_HEADING = "Список использованных источников и литературы"


def test_the_page_break_line_quotes_FORTY_characters_of_a_long_heading():
    """`[:40]` spelled `[:39]` and `[:41]` (L913). The ГОСТ heading the
    DSI paper's list sits under is 45 characters, so the width is
    visible: the line is a record a reader matches against the document,
    and it says exactly what it promised to quote."""
    parts = make_parts(para(run("Body text before the list."))
                       + heading(RUSSIAN_HEADING) + entry(LONG_A))

    report = layout(parts, heading=RUSSIAN_HEADING)

    assert report.page_break == "¶2: " + RUSSIAN_HEADING[:40], \
        report.page_break


def test_the_order_finding_quotes_SIXTY_characters_of_the_entry():
    """`r.text[:60]` spelled `[:59]` and `[:61]` (L980). The other
    findings on an entry quote sixty characters, and a report whose rows
    quote different widths for the same entry reads as two entries."""
    currie = ('Currie, J. (1999). "Health." Handbook of Labor Economics, '
              "3(1), 5-60.")
    found = [i for i in audit(_ordered_list(
        currie,
        'Acemoglu, D. (2020). "Robots." Journal of Political Economy, 1(1), '
        "1-20.",
        "Barr, N. (2010). Pension Reform: A Short Guide. Oxford: OUP Press.",
        'Diller, M. (2016). "Ageing." Journal of Ageing Studies, 2(2), 9-30.',
    )).issues if i.code == "order"]

    assert [i.snippet for i in found] == [currie[:60]]


def test_refile_names_a_moved_entry_by_its_first_SIXTY_characters():
    """`[:60]` spelled `[:61]` (L1154). `report.moved` is what a log of
    the re-filing records, at the same width every entry finding
    quotes. Two entries swapped name ONE mover — the one the matcher
    lifts out — and here that is Acemoglu, filed below Currie."""
    currie = ('Currie, J. (1999). "Health and the Labor Market." Handbook of '
              "Labor Economics.")
    parts = make_parts(para(run("Body text before the list.")) + heading()
                       + entry(currie, pid="00000001")
                       + entry(LONG_A, pid="00000002"))

    report = refile(parts)

    assert report.moved == [LONG_A[:60]]


ENTRY_A = 'Acemoglu, D. (2020). "Robots." Journal, 1(1), 1-20.'
ENTRY_B = 'Brown, A. (2019). "A Title." Journal, 2(2), 30-40.'
ENTRY_C = 'Chen, L. (2021). "Another." Journal, 3(3), 50-60.'


def test_an_EMPTY_paragraph_above_an_ODD_index_entry_is_numbered_right():
    """`r.index + 1` spelled `^ 1` and `| 1` (L1137). They agree with
    `+ 1` on every EVEN index, which is where the existing fixture's
    entry fell. One more body paragraph puts it at index 5: ¶6, where
    the mutants print ¶4 and ¶5 — the entry above the blank line, or the
    list's first entry."""
    parts = _list_with(
        para(run("Body one.")), para(run("Body two.")),
        para(run("Body three.")), para(run("References")),
        para(run(ENTRY_A)), "<w:p/>", para(run(ENTRY_B)),
        para(run(ENTRY_C)))

    report = refile(parts)

    assert report.refused.startswith(
        "an empty paragraph sits above ¶6;"), report.refused


def test_a_NON_bookmark_above_an_ODD_index_entry_is_numbered_right():
    """`r.index + 1` spelled `^ 1` and `| 1` (L1140), the same parity
    gap: the entry under the stranded markup sits at index 5 here."""
    stranded = '<w:commentRangeEnd w:id="1"/>'
    body = "".join(para(run(f"Body paragraph {n}.")) for n in range(3))
    parts = make_parts(body + heading() + entry(LONG_A) + stranded
                       + entry(ENTRY_B))

    report = refile(parts)

    assert report.refused.startswith("¶6 has "), report.refused
