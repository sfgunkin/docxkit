"""Reference-format audit: the house author-date style, checked."""
from __future__ import annotations

import re

import pytest
from conftest import NS, make_parts, note, notes, para, run

from docxkit import refstyle
from docxkit._cite_grammar import Reference
from docxkit.citations import find_citations
from docxkit.errors import ConversionRefused
from docxkit.refstyle import (
    CHICAGO,
    HOUSE,
    Issue,
    RefStyleReport,
    _read_label,
    _trust_the_links,
    audit,
    check_entry,
    check_prose,
    convert,
    convert_entry,
    convert_text,
)


def _codes(issues):
    return {i.code for i in issues}


def irun(text: str) -> str:
    """A run with real italics on — what a journal title looks like."""
    return f"<w:r><w:rPr><w:i/></w:rPr><w:t>{text}</w:t></w:r>"


# ------------------------------------------------------------- entries ---

CLEAN_ARTICLE = ('Acemoglu, D., and P. Restrepo. (2020). "Robots and Jobs: '
                 "Evidence from US Labor Markets.\" Journal of Political "
                 "Economy, 128(6): 2188–2244.")


def test_a_house_style_entry_is_clean():
    assert check_entry(CLEAN_ARTICLE) == []


# The house style is written out for a human in the `reference-format`
# skill (~/.claude/skills/reference-format/SKILL.md). These are its own
# worked examples, one per entry kind. A prose spec and a preset drift
# the moment nobody checks them against each other, so HOUSE has to call
# every one of them clean — and if a rule here ever changes, the skill is
# the other half of the edit.
SKILL_EXAMPLES = [
    # journal article, two authors
    'Acemoglu, D., and P. Restrepo. (2020). "Robots and Jobs: Evidence '
    'from US Labor Markets." Journal of Political Economy, 128(6): '
    "2188–2244.",
    # journal article, three authors — the serial comma before "and"
    'Chetty, R., Friedman, J., and E. Saez. (2013). "Using Differences in '
    "Knowledge across Neighborhoods to Uncover the Impacts of the EITC on "
    'Earnings." American Economic Review, 103(7): 2683–2721.',
    # book
    "Angrist, J., and J. Pischke. (2009). Mostly Harmless Econometrics: "
    "An Empiricist's Companion. Princeton, NJ: Princeton University Press.",
    # chapter in an edited volume
    'Card, D. (1999). "The Causal Effect of Education on Earnings." In '
    "Handbook of Labor Economics, Vol. 3A, edited by O. Ashenfelter and "
    "D. Card, 1801–1863. Amsterdam: Elsevier.",
    # working paper
    'Autor, D., Dorn, D., and G. Hanson. (2021). "On the Persistence of '
    'the China Shock." NBER Working Paper No. 29401.',
    # institutional report — no personal-name rules apply
    "World Bank. (2020). World Development Report 2020: Trading for "
    "Development in the Age of Global Value Chains. Washington, DC: "
    "World Bank.",
    # online resource, with a URL whose hyphens are not page ranges
    'Ritchie, H. (2023). "Why Do Women Live Longer Than Men?" Published '
    "online at OurWorldinData.org. Retrieved from: "
    "https://ourworldindata.org/why-do-women-live-longer-than-men.",
]

SKILL_CITATIONS = [
    "Smith (2020) shows this, and so does (Smith 2020).",
    "Smith and Jones (2020) agree with (Smith and Jones 2020).",
    "Smith et al. (2020) and (Smith et al. 2020) concur.",
    "Several works agree (Smith 2019, 2020; Jones 2021).",
    "The estimate is precise (Smith 2020, p. 45) or (Smith 2020, pp. 45–48).",
]


@pytest.mark.parametrize("entry", SKILL_EXAMPLES)
def test_every_documented_entry_kind_is_clean_under_house(entry):
    assert check_entry(entry, HOUSE) == []


@pytest.mark.parametrize("text", SKILL_CITATIONS)
def test_every_documented_citation_form_is_clean_under_house(text):
    assert check_prose(text, HOUSE) == []


def test_a_bare_year_flags_under_house_style():
    """AFI's Chicago entries date themselves '2023.', the house '(2023).'."""
    issues = check_entry("Maestas, N., and D. Powell. 2023. "
                         "“Population Aging.” AEJ: Macro, 15(2): 306–32.")
    assert "year-parens" in _codes(issues)


def test_a_parenthesised_year_flags_under_chicago():
    assert "year-parens" in _codes(check_entry(CLEAN_ARTICLE, CHICAGO))
    assert "year-parens" not in _codes(check_entry(
        "Maestas, N., and D. Powell. 2023. “Aging.” AEJ, 15(2): 306–32.",
        CHICAGO))


def test_spelled_out_given_names_flag_as_initials():
    """Both slots: after the first comma, and after the final 'and'."""
    issues = check_entry("Acemoglu, Daron, and Pascual Restrepo. (2020). "
                         "“Robots.” JPE, 128(6): 2188–2244.")
    initials = [i for i in issues if i.code == "initials"]
    assert initials, issues
    assert "Daron" in initials[0].message
    assert "Pascual" in initials[0].message


def test_a_capitalised_surname_particle_is_not_a_given_name():
    """'J. Van Reenen' spells no first name out; flagging it buried the
    real findings."""
    issues = check_entry("Card, D., and J. Van Reenen. (2012). “Title.” "
                         "Journal, 1(1): 1–2.")
    assert "initials" not in _codes(issues)


def test_a_middle_authors_surname_is_not_a_given_name():
    """'..., Friedman, J., ...' — Friedman follows a comma but is a
    surname; only the FIRST comma opens a given-name slot."""
    issues = check_entry("Chetty, R., Friedman, J., and E. Saez. (2013). "
                        "“Using Differences in Knowledge.” AER, "
                        "103(7): 2683–2721.")
    assert "initials" not in _codes(issues)


def test_two_initials_for_one_author_flag():
    issues = check_entry("Bucher-Koenen, T. A., and S. Kluth. (2013). "
                         "“Title.” Journal, 1(1): 1–2.")
    assert "initials" in _codes(issues)


def test_a_missing_comma_before_and_flags():
    issues = check_entry("Angrist, J. and J. Pischke. (2009). “Title.” "
                         "Journal, 1(1): 1–2.")
    assert "and-comma" in _codes(issues)
    assert "and-comma" not in _codes(check_entry(CLEAN_ARTICLE))


def test_an_ampersand_between_authors_flags():
    issues = check_entry("Angrist, J., & J. Pischke. (2009). “Title.” "
                         "Journal, 1(1): 1–2.")
    assert "ampersand" in _codes(issues)


def test_a_hyphen_page_range_flags_but_a_doi_does_not():
    hyphen = check_entry('Card, D. (1999). "Education." Handbook, '
                         "Vol. 3A, 1801-1863.")
    assert "en-dash" in _codes(hyphen)
    dashed = check_entry('Card, D. (1999). "Education." Handbook, '
                         "Vol. 3A, 1801–1863. https://doi.org/10.1016/"
                         "S1573-4463(99)03011-4")
    assert "en-dash" not in _codes(dashed)


def test_an_institutional_entry_is_exempt_from_name_rules():
    """'World Bank. (2020).' has no comma before the year: none of the
    personal-name checks apply."""
    issues = check_entry("World Bank. (2020). World Development Report "
                         "2020. Washington, DC: World Bank.")
    assert issues == []


def test_an_institution_with_commas_in_its_name_is_still_institutional():
    """'Ministry of Health, Labour and Welfare (MHLW). (2013).' carries
    commas, and the name rules read 'Labour' and 'Welfare' as spelled-out
    given names (LE le15 ¶254)."""
    issues = check_entry("Ministry of Health, Labour and Welfare (MHLW). "
                         "(2013). Health Japan 21 (the second term). "
                         "Tokyo: MHLW.")
    assert "initials" not in _codes(issues)
    assert "and-comma" not in _codes(issues)


# --------------------------------------------------------------- prose ---

def test_a_house_citation_is_clean():
    assert check_prose("Robots displace (Acemoglu and Restrepo 2020).") == []


def test_an_ampersand_in_a_citation_flags():
    assert "ampersand" in _codes(check_prose("(Smith & Jones 2020)"))


def test_three_authors_spelled_out_flag_under_house_style():
    text = "(Smith, Jones, and Brown 2020)"
    issues = check_prose(text)
    assert "et-al" in _codes(issues)
    assert "Smith et al." in next(i for i in issues
                                  if i.code == "et-al").message
    # Chicago spells out up to three authors
    assert "et-al" not in _codes(check_prose(text, CHICAGO))


def test_an_apa_comma_before_the_year_flags():
    assert "year-comma" in _codes(check_prose("as shown (Smith, 2020)."))
    assert "year-comma" in _codes(
        check_prose("(Acemoglu and Restrepo 2020; Smith, 2020)"))
    assert "year-comma" not in _codes(check_prose("(Smith 2020)"))


def test_et_al_without_its_period_flags():
    assert "et-al-period" in _codes(check_prose("(Smith et al 2020)"))
    assert "et-al-period" not in _codes(check_prose("(Smith et al. 2020)"))


def test_page_formats():
    assert "page-dash" in _codes(check_prose("(Smith 2020, pp. 45-48)"))
    assert "page-space" in _codes(check_prose("(Smith 2020, p.45)"))
    assert _codes(check_prose("(Smith 2020, pp. 45–48)")) == set()


def test_a_discourse_adverb_is_not_a_first_author():
    """'Similarly, Liebman and Luttmer (2015) show...' — the grammar
    swallows 'Similarly' as an author, which read as 3 named authors and
    advised 'write "Similarly et al."' (LE le15 ¶30)."""
    issues = check_prose("Similarly, Liebman and Luttmer (2015) show "
                         "information changes behavior.")
    assert "et-al" not in _codes(issues)
    # a real three-author citation behind an adverb still gets the advice
    issues = check_prose("However, Smith, Jones, and Brown (2020) argue.")
    advice = [i for i in issues if i.code == "et-al"]
    assert advice and "Smith et al." in advice[0].message


def test_a_swallowed_place_name_is_not_a_first_author():
    """"in the United Kingdom, Chan and Koo (2011)" read as three named
    authors and advised 'write "Kingdom et al."' (Parental Style). No
    word list catches this one — the audit holds the reference list, and
    that is what says "Kingdom" files nothing while "Chan" files this."""
    body = (para(run("In the United Kingdom, Chan and Koo (2011) report "
                     "a gradient."))
            + para(run("References"))
            + para(run("Chan, T., and A. Koo. (2011). “Parenting Style.” "),
                   irun("European Journal of Population"),
                   run(", 27(3): 385–399.")))
    report = audit(make_parts(body))
    assert not any(i.code == "et-al" for i in report.issues)
    assert not any(i.code == "missing-ref" for i in report.issues)
    # …and one paragraph on its own has no such evidence, so it still says
    # what it can see. The advice is wrong there and unavoidable; the
    # document-level audit is the one an author reads.
    assert "et-al" in _codes(check_prose(
        "In the United Kingdom, Chan and Koo (2011) report a gradient."))


# --------------------------------------------------------------- audit ---

def body_paragraphs() -> str:
    return (
        para(run("Robots reduce employment (Acemoglu and Restrepo 2020) "
                 "and Maestas et al. (2023) concur."))
        + para(run("Angrist and Pischke (2009) survey the toolkit."))
        + para(run("References"))
        + para(run("Acemoglu, D., and P. Restrepo. (2020). "
                   "“Robots and Jobs.” "),
               irun("Journal of Political Economy"),
               run(", 128(6): 2188–2244."))
        + para(run("Angrist, J., and J. Pischke. (2009). "),
               irun("Mostly Harmless Econometrics"),
               run(". Princeton, NJ: Princeton University Press."))
        + para(run("Brown, A. (2020). “A Quoted Title.” Some Journal, "
                   "1(1): 5–6."))
    )


def test_audit_cross_checks_cited_against_listed():
    report = audit(make_parts(body_paragraphs()))
    assert report.n_entries == 3
    missing = [i for i in report.issues if i.code == "missing-ref"]
    assert [i.snippet for i in missing] == ["Maestas et al. (2023)"]
    uncited = [i for i in report.issues if i.code == "uncited-ref"]
    assert len(uncited) == 1
    assert uncited[0].snippet.startswith("Brown")


def test_audit_flags_an_entry_with_no_italics():
    """Every entry format italicises something — journal or title. The
    Brown entry above has none, so its journal name lost its italics."""
    report = audit(make_parts(body_paragraphs()))
    italics = [i for i in report.issues if i.code == "italics"]
    assert len(italics) == 1
    assert italics[0].snippet.startswith("Brown")


def test_audit_skips_the_reference_section_as_prose():
    """'Restrepo. (2020)' inside an entry must not read as a narrative
    citation, or every entry self-cites."""
    report = audit(make_parts(body_paragraphs()))
    assert not any(i.code == "year-comma" for i in report.issues)
    assert report.n_cited == 3   # acemoglu, maestas, angrist — no echoes


def test_audit_reports_a_disordered_list():
    body = (para(run("Cited: (Zebra 2020) and (Aksoy 2026)."))
            + para(run("References"))
            + para(run("Zebra, A. (2020). “Z first.” "), irun("J"),
                   run(", 1(1): 1–2."))
            + para(run("Aksoy, C. (2026). “A second.” "), irun("J"),
                   run(", 1(1): 1–2.")))
    report = audit(make_parts(body))
    order = [i for i in report.issues if i.code == "order"]
    assert len(order) == 1
    # The message says where it BELONGS, not merely that it is wrong:
    # moving either entry of a swapped pair fixes the list, so a reader
    # needs to be told which one to pick up and where to put it.
    assert '"Aksoy" is out of alphabetical order' in order[0].message
    assert 'it files before "Zebra"' in order[0].message


def test_diacritics_fold_for_ordering():
    """Mühlbach files at Mu-h, before Mullen — not after Z."""
    body = (para(run("(Mühlbach 2022) and (Mullen 2023)."))
            + para(run("References"))
            + para(run("Mühlbach, N. (2022). “First.” "), irun("J"),
                   run(", 1(1): 1–2."))
            + para(run("Mullen, K. (2023). “Second.” "), irun("J"),
                   run(", 1(1): 1–2.")))
    assert not any(i.code == "order"
                   for i in audit(make_parts(body)).issues)


def test_a_bare_citation_cell_counts_as_cited():
    """A table's source column holds 'Cette et al. 2019' and nothing
    else — no parentheses for either in-text form (LE le15 ¶136). Only a
    paragraph that IS the citation counts; prose stays untouched."""
    body = (para(run("Cette et al. 2019 "))
            + para(run("Cette wrote more in 2019 about labor."))
            + para(run("References"))
            + para(run("Cette, G., Koehl, L., and T. Philippon. (2019). "
                       "“Labor share.” "), irun("Economics Letters"),
                   run(", 188: 108979.")))
    report = audit(make_parts(body))
    assert not any(i.code == "uncited-ref" for i in report.issues)


def test_a_footnote_citation_counts_as_cited():
    body = (para(run("A claim without an in-text citation."))
            + para(run("References"))
            + para(run("Card, D. (1999). “Education.” "), irun("Handbook"),
                   run(", 1801–1863.")))
    footnotes = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f"<w:footnotes {NS}><w:footnote w:id=\"2\">"
                 f"{para(run('See Card (1999) for the survey.'))}"
                 f"</w:footnote></w:footnotes>")
    report = audit(make_parts(body, footnotes=footnotes))
    assert not any(i.code == "uncited-ref" for i in report.issues)


def test_ignored_leads_do_not_read_as_citations():
    body = (para(run("Estimates are shown in Table (2020) format… "
                     "surveyed in March (2020)."))
            + para(run("References"))
            + para(run("Card, D. (1999). “Education.” "), irun("Handbook"),
                   run(", 1801–1863.")))
    report = audit(make_parts(body))
    assert not any(i.code == "missing-ref" for i in report.issues)


def test_ignore_clears_the_ET_AL_half_of_the_same_finding():
    """`--ignore` reached `audit`'s own `_resolve_lead` and not the one
    inside `_check_prose`, so a paper could clear the missing-ref half
    of a finding and be left with an et-al finding on the SAME phrase —
    "3 authors named in text — write 'Surveys et al.'" — that no value
    of the flag could reach. The flag exists because the paper cannot
    clear it any other way."""
    body = (para(run("Data from Regional Household Surveys and Cameron "
                     "and Roodman (2019) are used."))
            + para(run("References"))
            + para(run("Cameron, A., and D. Roodman. (2019). “Bootstrap.” "),
                   irun("Journal of Econometrics"), run(", 1(1): 1–2.")))
    parts = make_parts(body)

    plain = [i.code for i in audit(parts).issues]
    assert "et-al" in plain

    cleared = [i.code for i in
               audit(parts, ignore={"Surveys"}).issues]
    assert "et-al" not in cleared, cleared


def test_two_entries_that_cite_alike_are_flagged():
    """Author-date's one rule with a name: 2013a, 2013b. Nothing asked for it,
    so applying «et al. from three authors» to DSI collapsed Foster,
    McGillivray, and Seth (2013) and Foster, Seth, Lokshin, and Sajaia (2013)
    into a single «Foster et al. 2013» — the linker could resolve only one of
    the three mentions, and the audit still reported no issues."""
    body = (para(run("Both matter (Foster et al. 2013)."))
            + para(run("References"))
            + para(run("Foster, J., McGillivray, M., and S. Seth. (2013). "
                       "“Composite Indices.” "), irun("Econometric Reviews"),
                   run(", 32(1): 35–56."))
            + para(run("Foster, J., Seth, S., Lokshin, M., and Z. Sajaia. "
                       "(2013). "), irun("A Unified Approach"),
                   run(". Washington, DC: World Bank.")))
    issues = [i for i in audit(make_parts(body)).issues
              if i.code == "ambiguous-cite"]
    assert len(issues) == 2
    assert "2013a, 2013b" in issues[0].message


def test_a_suffixed_year_is_not_ambiguous():
    """Which is the fix, so applying it must silence the finding."""
    body = (para(run("Both matter (Foster et al. 2013a, 2013b)."))
            + para(run("References"))
            + para(run("Foster, J., McGillivray, M., and S. Seth. (2013a). "
                       "“Composite Indices.” "), irun("Econometric Reviews"),
                   run(", 32(1): 35–56."))
            + para(run("Foster, J., Seth, S., Lokshin, M., and Z. Sajaia. "
                       "(2013b). "), irun("A Unified Approach"),
                   run(". Washington, DC: World Bank.")))
    assert not any(i.code == "ambiguous-cite"
                   for i in audit(make_parts(body)).issues)


def test_an_alias_reconciles_an_acronym_with_the_filed_name():
    """The CLI dropped this argument, so a paper citing «(UNFPA 2021)» against
    an entry filed under the full name was reported as BOTH a missing reference
    and an uncited entry — twice over, for the same work."""
    body = (para(run("The programme began in 2021 (UNFPA 2021)."))
            + para(run("References"))
            + para(run("United Nations Population Fund. (2021). "),
                   irun("Decade of Demographic Resilience"),
                   run(". Geneva: UNFPA.")))
    bare = audit(make_parts(body))
    assert {"missing-ref", "uncited-ref"} <= _codes(bare.issues)
    aliased = audit(make_parts(body),
                    aliases={"UNFPA": "United Nations Population Fund"})
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in aliased.issues)


def test_no_reference_list_is_its_own_finding():
    body = para(run("A citation exists (Smith 2020) but no list."))
    report = audit(make_parts(body))
    assert _codes(report.issues) == {"no-list"}


def test_an_online_resource_entry_needs_no_italics():
    body = (para(run("(Ritchie 2023) shows the gap."))
            + para(run("References"))
            + para(run("Ritchie, H. (2023). “Why Do Women Live Longer?” "
                       "Published online at OurWorldinData.org. Retrieved "
                       "from: https://ourworldindata.org/. ")))
    report = audit(make_parts(body))
    assert not any(i.code == "italics" for i in report.issues)


def test_a_working_paper_entry_needs_no_italics():
    """The working-paper format is italic-free by design — on AFI v13
    flagging these drowned the entries that had really lost italics."""
    body = (para(run("(Autor et al. 2021) persists."))
            + para(run("References"))
            + para(run("Autor, D., Dorn, D., and G. Hanson. (2021). “On "
                       "the Persistence of the China Shock.” NBER Working "
                       "Paper No. 29401.")))
    report = audit(make_parts(body))
    assert not any(i.code == "italics" for i in report.issues)


@pytest.mark.parametrize("entry", [
    # Aging_Well's two italics findings, both of them false, and both of
    # them the working-paper format under a name the marker list did not
    # carry (2026-08-21).
    'Sen, A. (2000). “Social Exclusion: Concept, Application, and '
    'Scrutiny.” Social Development Papers No. 1, Asian Development Bank.',
    'Zaidi, A., and E. Zolyomi. (2013). “Active Ageing Index 2012.” '
    "Research Memorandum, European Centre Vienna.",
    'Ito, K. (2019). “Long-term care.” Technical Report No. 8, OECD.',
])
def test_a_NUMBERED_SERIES_entry_needs_no_italics(entry):
    body = (para(run("(Sen 2000) and others."))
            + para(run("References")) + para(run(entry)))
    report = audit(make_parts(body))
    assert not any(i.code == "italics" for i in report.issues)


@pytest.mark.parametrize("entry", [
    # A Chicago issue number is lowercase and follows the volume, so the
    # capital on "No." is what tells a SERIES from an issue. Exempting
    # this would suppress the finding the check exists for.
    'Brown, T. (2019). “Wages and hours.” Labour Economics 34, no. 4: '
    "3–30.",
    # …and a REPORT title is a title: the style italicises it like a book.
    'World Bank. (2020). World Development Report 2020. Washington, DC.',
])
def test_an_entry_that_only_LOOKS_like_a_series_is_still_flagged(entry):
    body = (para(run("(Brown 2019) and (World Bank 2020)."))
            + para(run("References")) + para(run(entry)))
    report = audit(make_parts(body))
    assert any(i.code == "italics" for i in report.issues)


def test_an_entry_that_names_its_acronym_licenses_it():
    """'Health Promotion Board (HPB). (2023).' is what '(HPB 2023)'
    cites — the alias is in the entry itself, no map needed (LE le15)."""
    body = (para(run("Singapore runs such a program (HPB 2023)."))
            + para(run("References"))
            + para(run("Health Promotion Board (HPB). (2023). Live Well, "
                       "Age Well Programme. Singapore: HPB.")))
    report = audit(make_parts(body))
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in report.issues)


def test_an_all_caps_lead_licenses_the_acronym_citation():
    """'UNDP (United Nations Development Programme). (2025).' files under
    the acronym itself; 'UNDP (2025)' in prose must find it (LE le15)."""
    body = (para(run("Life expectancy is rising (UNDP 2025)."))
            + para(run("References"))
            + para(run("UNDP (United Nations Development Programme). "
                       "(2025). Human Development Report. New York: UNDP.")))
    report = audit(make_parts(body))
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in report.issues)


def test_a_truncated_institutional_citation_reconciles():
    """The grammar joins authors only on commas and 'and', so a narrative
    'World Bank (2025a)' is captured as 'Bank (2025a)' and 'National Bank
    of Kazakhstan (2021)' as 'Kazakhstan (2021)' (LE le15 ¶128/¶132)."""
    body = (para(run("According to the World Bank (2025a), growth slowed. "
                     "The National Bank of Kazakhstan (2021) targets "
                     "inflation."))
            + para(run("References"))
            + para(run("National Bank of Kazakhstan. (2021). Monetary "
                       "Policy Strategy 2030. Almaty: NBK."))
            + para(run("World Bank. (2025a). "),
                   irun("World Development Indicators"),
                   run(". Washington, DC: World Bank.")))
    report = audit(make_parts(body))
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in report.issues)


def test_a_discourse_adverb_does_not_orphan_the_real_entry():
    """'Similarly, Liebman and Luttmer (2015)' filed under 'Similarly',
    so the citation went missing AND the entry read uncited (LE le15)."""
    body = (para(run("Similarly, Liebman and Luttmer (2015) find effects."))
            + para(run("References"))
            + para(run("Liebman, J., and E. Luttmer. (2015). “Would "
                       "people behave differently?” "),
                   irun("AEJ: Economic Policy"), run(", 7(1): 275–299.")))
    report = audit(make_parts(body))
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in report.issues)


def test_style_derived_italics_count_as_italics():
    """Word's Compare drops a redundant direct <w:i/> and keeps the
    Emphasis run style — the journal name is italic with no <w:i> in the
    paragraph (LE round 7 'de-italicised journal names' false positive)."""
    body = (para(run("Beliefs matter (Hurd 2005)."))
            + para(run("References"))
            + para(run("Hurd, M. (2005). “Subjective probabilities.” "),
                   run("Journal of Applied Econometrics", style="Emphasis"),
                   run(", 20(1): 1–2.")))
    parts = make_parts(body)
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<w:styles {NS}>'
              f'<w:style w:type="character" w:styleId="Emphasis">'
              f"<w:rPr><w:i/></w:rPr></w:style>"
              f'<w:style w:type="character" w:styleId="Hyperlink">'
              f"<w:rPr><w:u w:val=\"single\"/></w:rPr></w:style>"
              f"</w:styles>")
    bare = audit(dict(parts))
    assert any(i.code == "italics" for i in bare.issues)
    parts["word/styles.xml"] = styles.encode("utf-8")
    assert not any(i.code == "italics" for i in audit(parts).issues)


def test_an_entrys_initialism_licenses_the_acronym_citation():
    """AFI cites '(WHO 2015)' for 'World Health Organization' and API10
    '(UN 2024)' for 'United Nations, Department of...' — the reader
    connects an initialism without a map, so the audit must too."""
    body = (para(run("Healthy ageing is defined broadly (WHO 2015)."))
            + para(run("References"))
            + para(run("World Health Organization. (2015). "),
                   irun("World Report on Ageing and Health"),
                   run(". Geneva: WHO.")))
    report = audit(make_parts(body))
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in report.issues)


def test_a_word_run_of_the_institution_licenses_the_citation():
    """API10 ¶183 cites '(World Bank 2024)' — captured as 'Bank 2024' —
    against an entry filed under 'World Bank Group'."""
    body = (para(run("Implementation gaps persist (World Bank 2024)."))
            + para(run("References"))
            + para(run("World Bank Group. (2024). "),
                   irun("Women, Business and the Law"),
                   run(". Washington, DC.")))
    report = audit(make_parts(body))
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in report.issues)


def test_aliases_reconcile_abbreviations_the_entry_cannot_derive():
    """'(GoK 2021)' for 'Government of Kazakhstan' is neither named in
    the entry nor its initialism — the map stays with the paper, the
    hook is the audit's."""
    body = (para(run("Pensions were indexed (GoK 2021)."))
            + para(run("References"))
            + para(run("Government of Kazakhstan. (2021). "),
                   irun("Social Protection Strategy"), run(". Astana.")))
    bare = audit(make_parts(body))
    assert any(i.code == "missing-ref" for i in bare.issues)
    aliased = audit(make_parts(body),
                    aliases={"GoK": "Government of Kazakhstan"})
    assert not any(i.code in ("missing-ref", "uncited-ref")
                   for i in aliased.issues)


def test_report_format_reads_as_a_checklist():
    report = audit(make_parts(body_paragraphs()))
    text = report.format()
    assert text.startswith("3 reference entries, 3 works cited in text")
    assert "missing-ref" in text
    rows = report.as_rows()
    assert all({"code", "where", "message", "snippet"} <= set(r) for r in rows)


def test_dotted_acronyms_order_without_their_periods():
    """"U.S." files as "US" — after "United", which is where the style
    manuals and LI7's own list put it; comparing the dot against the
    letters flagged the correct order as broken."""
    body = (para(run("Cited (United Nations 2019) and (Bureau 2023)."))
            + para(run("References"))
            + para(run("United Nations (2019). "), irun("World Population"),
                   run(". New York: UN."))
            + para(run('U.S. Census Bureau. (2023). '), irun("Age Heaping"),
                   run(". Washington, DC.")))
    report = audit(make_parts(body))
    assert not any(i.code == "order" for i in report.issues)


def test_same_author_entries_run_oldest_first():
    """API10's WHO block ran 2002, 2019, 2018, 2021, 2015 and nothing
    flagged it."""
    body = (para(run("Cited (WHO 2019) and (WHO 2018)."))
            + para(run("References"))
            + para(run("WHO. (2019). "), irun("Estimates"), run(". Geneva."))
            + para(run("———. (2018). "), irun("Network"), run(". Geneva.")))
    report = audit(make_parts(body))
    orders = [i for i in report.issues if i.code == "year-order"]
    assert len(orders) == 1 and "(2018)" in orders[0].message


# --- WHERE the audit says an issue is (2026-08-19) ----------------------
#
# refstyle re-measured at 44.1 % real survival — the worst module in the
# package by a factor of three — with 87 of its 173 survivors in `audit`
# alone. Almost all of them sit on `f"¶{r.index + 1}"` and the snippet
# slices beside it: not one of this file's 47 tests read `i.where`, so
# every issue could have been reported against the wrong paragraph and
# the suite would have stayed green.
#
# `where` is the whole usefulness of the report. A style audit that says
# "the list is not alphabetical" without saying which entry is a list of
# forty entries to re-read by eye, which is the job the module exists to
# remove. Indices are chosen ODD on purpose: `3 + 1` is 4, `3 | 1` is 3
# and `3 ^ 1` is 2, while at an even index `+` and `|` agree.


def _rows(report) -> list[tuple[str, str]]:
    return [(i.code, i.where) for i in report.issues]


def _entry_paragraphs() -> str:
    """Two prose paragraphs, a heading, three entries — entries at
    indices 3, 4 and 5, so the paragraph numbers they report are 4, 5
    and 6."""
    return (
        para(run("Robots reduce employment (Acemoglu and Restrepo 2020) "
                 "and Maestas et al. (2023) concur."))
        + para(run("Angrist and Pischke (2009) survey the toolkit."))
        + para(run("References"))
        + para(run("Acemoglu, D., and P. Restrepo. (2020). "), irun("JPE"),
               run(", 128(6): 2188–2244."))
        + para(run("Angrist, J., and J. Pischke. (2009). "),
               irun("Mostly Harmless Econometrics"),
               run(". Princeton, NJ: Princeton University Press."))
        + para(run("Brown, A. (2020). “A Quoted Title Long Enough To Be "
                   "Cut By The Sixty Character Limit.” Some Journal, "
                   "pp. 45-48."))
    )


def test_every_issue_names_the_paragraph_it_was_found_in():
    """The third entry is the sixth paragraph, and all three of its
    issues have to say so. `¶6` against `¶5` sends a person to the entry
    above the one that is wrong — in a list where every line looks like
    every other, that is worse than no location at all.

    The layout rules are off here so the assertion stays about WHERE a
    finding points; they have their own test, and a bare fixture states
    none of the indents they ask for."""
    report = audit(make_parts(_entry_paragraphs()), page_layout=None)

    assert sorted(_rows(report)) == [
        ("en-dash", "¶6"),          # "pp. 45-48" wants an en-dash
        ("italics", "¶6"),          # Brown's journal lost its italics
        ("missing-ref", "¶1"),      # Maestas, cited in the first paragraph
        ("uncited-ref", "¶6"),      # Brown, listed and never cited
    ]


def test_the_entry_snippet_is_the_first_sixty_characters():
    """`r.text[:60]` — enough to recognise the entry, short enough for a
    terminal line. The report is read next to the document, so the
    snippet's job is to confirm the paragraph number found the right
    entry."""
    report = audit(make_parts(_entry_paragraphs()))

    brown = [i for i in report.issues if i.where == "¶6" and i.snippet]
    assert {i.snippet for i in brown} == {
        "Brown, A. (2020). “A Quoted Title Long Enough To Be Cut By T"}


def test_the_LAST_entry_is_not_also_read_as_prose():
    """`head_idx <= i <= last_entry`, inclusive at the top: with `<` the
    final entry falls through to the prose checks as well as the entry
    checks. Brown's "pp. 45-48" is what makes that visible — the entry
    rule calls a hyphen range `en-dash`, the PROSE rule calls it
    `page-dash`, and both firing on one paragraph is the report
    describing a document that does not exist."""
    report = audit(make_parts(_entry_paragraphs()))

    assert not [i for i in report.issues if i.code == "page-dash"]


def test_a_footnote_issue_numbers_the_FOOTNOTE_paragraph():
    """`fn ¶4`, not `¶4`: footnote paragraphs and body paragraphs are
    numbered in separate sequences, and a report that mixed them would
    send a person to the fourth paragraph of the paper."""
    foot = notes("footnotes", note("First note.", nid=2),
                 note("Second.", nid=3), note("Third.", nid=4),
                 note("As shown (Smith, 2020) here.", nid=5))
    body = para(run("Prose (Acemoglu and Restrepo 2020)."))

    report = audit(make_parts(body, footnotes=foot))

    assert ("year-comma", "fn ¶4") in _rows(report)


def test_a_reference_HEADING_with_nothing_under_it_swallows_nothing():
    """`max(..., default=-1)`: with no entries parsed there is no
    reference section, and every paragraph is prose. A default of 0 or 1
    instead makes the paragraphs right after the heading disappear from
    the audit — the shape a paper has while its list is still in another
    file, and exactly when a person runs this."""
    body = (para(run("References"))
            + para(run("As stated (Smith, 2020) elsewhere."))
            + para(run("And again (Jones, 2021) here.")))

    report = audit(make_parts(body))

    assert report.n_entries == 0
    assert sorted(_rows(report)) == [("year-comma", "¶2"),
                                     ("year-comma", "¶3")]


def test_two_entries_that_cite_alike_are_lettered_a_then_b():
    """`chr(ord("a") + i)` — the suffixes the style asks for, in order.
    Under `|` the second is "a" again, which reads as a report that has
    not understood its own recommendation."""
    body = (para(run("Two works (Foster et al. 2013)."))
            + para(run("References"))
            + para(run("Foster, J., McGillivray, M., and S. Seth. (2013). "),
                   irun("J"), run(", 1(1): 1–2."))
            + para(run("Foster, J., Seth, S., and M. Lokshin. (2013). "),
                   irun("J"), run(", 2(2): 3–4.")))

    issues = [i for i in audit(make_parts(body)).issues
              if i.code == "ambiguous-cite"]

    assert [i.where for i in issues] == ["¶3", "¶4"]
    assert all("distinguish them as 2013a, 2013b" in i.message
               for i in issues)
    assert issues[0].snippet == ("Foster, J., McGillivray, M., and S. Seth. "
                                 "(2013). J, 1(1): 1")


# --- the SNIPPET a prose issue carries ----------------------------------
#
# `_snippet` takes 20 characters either side, and 22 of the module's
# survivors were on that one line. Every fixture in this file was short
# enough that both margins clamped, where `start - 20`, `start | 20` and
# `start % 20` are one number. These are long enough to cut.

LONG_PROSE = ("The estimates in this section follow the identification "
              "strategy set out by (Smith, 2020) and extended in later "
              "work by several other authors working on the same panel.")


def test_the_snippet_is_twenty_characters_either_side():
    """Enough context to find the phrase in the paragraph, little enough
    to stay on one line. The offsets here are 76 and 88 against a margin
    of 20 — no two of `-`, `|`, `^`, `&` and `%` agree on either."""
    issue, = check_prose(LONG_PROSE)

    assert issue.code == "year-comma"
    assert issue.snippet == ("strategy set out by (Smith, 2020) and "
                             "extended in la")


def test_a_snippet_at_the_START_of_a_paragraph_keeps_its_first_letter():
    """`max(0, start - margin)`: the margin runs off the front here, and
    0 is where the text begins. A floor of 1 drops the opening
    character, which for a citation-shaped snippet is the parenthesis
    the check is about."""
    issue, = check_prose("(Smith, 2020) is the earliest estimate of the "
                         "elasticity anyone has published.")

    assert issue.snippet.startswith("(Smith, 2020)")


def test_the_page_snippet_reaches_PAST_the_match_to_show_the_number():
    """`m.end() + 6`: the match is "p." and a lookahead, so it ends
    before the digits. Without the six the snippet stops at the very
    thing the reader has to see — the page number that is jammed
    against the period."""
    issue, = check_prose("The result is reported on p.45 of the working "
                         "paper, which surveys the earlier literature in "
                         "some detail.")

    assert issue.code == "page-space"
    assert issue.snippet == "sult is reported on p.45 of the working paper, w"


# --- the SNIPPET an entry issue carries ---------------------------------

MANY_AUTHORS = ('Acemoglu, D., Autor, D., Dorn, D., Hanson, G., Price, B., '
                'Restrepo, P. & Johnson, S. (2020). "Title." Journal, '
                "1(1): 1–2.")


def test_an_ampersand_snippet_shows_the_END_of_the_author_list():
    """`authors[-40:]`: the "&" is between the last two authors, so the
    tail is where it is. The head of a seven-author list does not
    contain the thing being reported."""
    amp, = [i for i in check_entry(MANY_AUTHORS) if i.code == "ampersand"]

    assert amp.snippet == "G., Price, B., Restrepo, P. & Johnson, S"
    assert len(amp.snippet) == 40


def test_a_name_snippet_shows_the_START_of_the_author_list():
    """`authors[:70]` — the other direction, because a spelled-out given
    name or a missing serial comma is a fault of the list's shape and
    the shape is legible from its beginning. Seventy characters, not the
    whole of a seven-author list."""
    entry = MANY_AUTHORS.replace("Johnson, S.", "Johnson, Simon")
    named, = [i for i in check_entry(entry) if i.code == "and-comma"]

    assert len(named.snippet) == 70
    assert named.snippet == entry[:70]


# --- the rules' other side (2026-08-19) ---------------------------------
#
# The second half of the same measurement: 28 survivors in `check_entry`
# and 15 in `_check_prose`. The shape is the one CONTRIBUTING calls a
# guard asserted from one side only — every exemption in the token loop
# was tested by the case it fires on and none by the case it must stay
# quiet for, and the loop's own `continue`s were free.


def test_a_URL_with_a_hyphenated_path_is_not_a_page_range():
    """The exemption is `http` OR `doi` OR a bare DOI prefix, not all
    three: a publisher URL carrying a year range in its path
    ("/2020-2021/") is the ordinary case, and under `and` a URL without
    the word "doi" in it stops being exempt."""
    entry = ('Smith, J. (2020). "Title." Journal, 1(1): 1–2. '
             "http://example.org/reports/2020-2021/summary.pdf")

    assert "en-dash" not in _codes(check_entry(entry))


def test_a_real_range_AFTER_a_url_is_still_flagged():
    """`continue`, not `break`: the loop skips the URL and keeps
    reading. Under `break` every entry that cites a DOI before its page
    numbers is silently exempt — which is most of a modern list."""
    entry = ('Smith, J. (2020). "Title." https://doi.org/10.1234/abc '
             "Journal, 1(1): 45-48.")

    assert "en-dash" in _codes(check_entry(entry))


def test_an_ISBN_is_not_a_page_range():
    """`>= 3` hyphens, not `> 3`: an ISBN-13 written in the short form
    carries exactly three, and a book entry flagged for its ISBN teaches
    a person to stop reading the en-dash findings."""
    entry = ("Angrist, J. (2009). Mostly Harmless Econometrics. "
             "Princeton University Press. ISBN 0-262-03384-8.")

    assert "en-dash" not in _codes(check_entry(entry))


def test_a_real_range_AFTER_an_isbn_is_still_flagged():
    entry = ("Angrist, J. (2009). Mostly Harmless Econometrics. "
             "ISBN 0-262-03384-8, pp. 45-48.")

    assert "en-dash" in _codes(check_entry(entry))


def test_only_the_FIRST_range_in_an_entry_is_reported():
    """`break`: the finding is "this entry uses hyphens", and an entry
    with a volume range and a page range would otherwise report the same
    fault twice. One line per entry is what makes a forty-entry audit
    readable."""
    entry = ('Smith, J. (2020). "Title." Journal, Vol. 3, 1801-1863, '
             "pp. 45-48.")

    ranges = [i for i in check_entry(entry) if i.code == "en-dash"]
    assert len(ranges) == 1
    assert ranges[0].message.endswith('"1801-1863"'), "the first one"


def test_an_institution_named_by_its_department_needs_no_acronym():
    """`_ACRONYM_RE.search(...) or " of " in authors` — either mark is
    enough. "Ministry of Health, Labour and Welfare" carries commas and
    no acronym at all, and under `and` its department names read as
    spelled-out given names (LE le15 ¶254 reported "Labour" and
    "Welfare" as authors' first names)."""
    entry = ("Ministry of Health, Labour and Welfare. (2013). "
             "Vital Statistics of Japan. Tokyo.")

    assert "initials" not in _codes(check_entry(entry))


def test_a_year_with_ONE_parenthesis_still_flags():
    """`not (m.group(1) and m.group(3))` — both or neither. A half-open
    "(2020." or "2020)." is what a hand edit leaves behind, and under
    `or` the check passes anything with a parenthesis on either side."""
    opened = check_entry('Smith, J. (2020. "Title." Journal, 1(1): 1–2.')
    closed = check_entry('Smith, J. 2020). "Title." Journal, 1(1): 1–2.')

    assert "year-parens" in _codes(opened)
    assert "year-parens" in _codes(closed)


def test_chicago_flags_a_year_with_ONE_parenthesis_too():
    """The mirror: `m.group(1) or m.group(3)` — a style that writes the
    year bare wants NEITHER parenthesis, and under `and` a half-open
    year passes both checks and is reported by nobody."""
    closed = check_entry('Smith, J. 2020). "Title." Journal, 1(1): 1–2.',
                         CHICAGO)

    assert "year-parens" in _codes(closed)


def test_at_most_three_spelled_out_names_are_quoted_in_one_message():
    """`suspects[:3]` — the message names examples, not the whole list.
    A five-author entry with every given name spelled out would put five
    quoted words on a line that already carries the rule."""
    entry = ("Smith, John and Jones, Mary and Brown, Sara and Davis, "
             'Paul. (2020). "Title." Journal, 1(1): 1–2.')

    named, = [i for i in check_entry(entry) if i.code == "initials"]
    assert named.message == ('given names as single initials — "John", '
                             '"Jones", "Brown" spelled out')
    assert "Davis" not in named.message, "four found, three shown"


def test_FOUR_authors_named_in_text_flag_under_house_style():
    """`len(names) >= style.etal_from`, not `==`: the house rule is "et
    al. from three", and four is more than three. `==` would report the
    three-author case and let every longer list through — the lists most
    in need of the abbreviation."""
    text = ("Acemoglu, Autor, Dorn and Hanson (2020) estimate the effect.")

    assert "et-al" in _codes(check_prose(text))


def test_chicago_abbreviates_from_FOUR_authors_not_three():
    """The preset's own number, from both sides. AFI's style spells
    three authors out and abbreviates four — a preset that agreed with
    HOUSE on this would make the CHICAGO option pointless."""
    three = "Acemoglu, Autor and Dorn (2020) estimate the effect."
    four = "Acemoglu, Autor, Dorn and Hanson (2020) estimate the effect."

    assert "et-al" not in _codes(check_prose(three, CHICAGO))
    assert "et-al" in _codes(check_prose(four, CHICAGO))


def test_chicago_leaves_spelled_out_given_names_alone():
    """`initials=False`: Chicago author-date writes "Acemoglu, Daron",
    and the house rule would report every entry in an AFI list."""
    entry = ("Acemoglu, Daron, and Simon Johnson. 2020. "
             '"Title." Journal, 1(1): 1–2.')

    assert _codes(check_entry(entry, CHICAGO)) == set()


def test_THREE_entries_that_cite_alike_are_lettered_a_b_c():
    """`len(group) < 2`, not `!= 2`: a group of three is the case that
    most needs the suffixes, and `!=` skips exactly it while still
    reporting pairs."""
    body = (para(run("Three works (Foster et al. 2013)."))
            + para(run("References"))
            + para(run("Foster, J., McGillivray, M., and S. Seth. (2013). "),
                   irun("J"), run(", 1(1): 1–2."))
            + para(run("Foster, J., Seth, S., and M. Lokshin. (2013). "),
                   irun("J"), run(", 2(2): 3–4."))
            + para(run("Foster, J., and A. Shorrocks. (2013). "),
                   irun("J"), run(", 3(3): 5–6.")))

    issues = [i for i in audit(make_parts(body)).issues
              if i.code == "ambiguous-cite"]

    assert [i.where for i in issues] == ["¶3", "¶4", "¶5"]
    assert all("2013a, 2013b, 2013c" in i.message for i in issues)


def test_a_paragraph_AFTER_the_reference_list_is_still_prose():
    """`continue`, not `break`: the reference section is skipped, not
    the rest of the document. An appendix, a data statement or an
    acknowledgements paragraph sits after the list in most of these
    papers, and under `break` none of them is ever audited."""
    body = (para(run("Cited (Acemoglu and Restrepo 2020)."))
            + para(run("References"))
            + para(run("Acemoglu, D., and P. Restrepo. (2020). "),
                   irun("JPE"), run(", 128(6): 2188–2244."))
            + para(run("Appendix A. The instrument follows (Smith, 2020) "
                       "closely.")))

    report = audit(make_parts(body))

    assert ("year-comma", "¶4") in _rows(report)


def test_two_entries_by_the_SAME_author_are_not_out_of_order():
    """`>` on the folded surname, not `>=`: an author with two works is
    the ordinary case in every list, and `>=` reports every one of them
    as misfiled. The finding then appears once per repeated author and
    the real transposition is lost in it."""
    body = (para(run("Cited (Smith 2019) and (Smith 2020)."))
            + para(run("References"))
            + para(run("Smith, J. (2019). “First.” "), irun("J"),
                   run(", 1(1): 1–2."))
            + para(run("Smith, J. (2020). “Second.” "), irun("J"),
                   run(", 2(2): 3–4.")))

    report = audit(make_parts(body))

    assert not [i for i in report.issues if i.code == "order"]


# --- what the report PRINTS ---------------------------------------------

def test_an_issue_with_no_paragraph_prints_as_list():
    """`i.where or "list"` — the cross-check findings that belong to the
    list as a whole carry no paragraph, and a blank column reads as a
    location that failed to print rather than one that does not apply.
    """
    report = RefStyleReport(issues=[Issue("no-list", "nothing found")])

    line = report.format().splitlines()[1]
    assert line.startswith("  list    no-list")


def test_a_snippet_is_quoted_after_the_message():
    report = RefStyleReport(
        issues=[Issue("order", "out of order", where="¶4", snippet="Zebra")])

    assert report.format().splitlines()[1].endswith('out of order  "Zebra"')


def test_an_issue_with_no_snippet_prints_no_trailing_quotes():
    """`if i.snippet else ""`: an empty pair of quotes at the end of a
    line reads as a snippet that came out blank — which is a different
    finding from an issue that carries none."""
    report = RefStyleReport(issues=[Issue("order", "out of order",
                                          where="¶4")])

    assert report.format().splitlines()[1].endswith("out of order")


def test_a_clean_report_says_so_rather_than_printing_nothing():
    """A report whose second line is absent is indistinguishable from a
    command that failed to run."""
    entries = [Reference(f"Author{i}, A. ({2000 + i}). A paper. Journal.",
                         f"Author{i}", str(2000 + i), i)
               for i in range(12)]
    cited = {r.key: (f"P{i}", r.text[:20]) for i, r in enumerate(entries)}

    assert RefStyleReport(entries=entries, cited=cited).format() == (
        "12 reference entries, 12 works cited in text\n"
        "  clean — no style departures found")


def test_an_empty_report_counts_nothing():
    """The dataclass defaults, which the CLI prints before anything has
    been audited."""
    assert RefStyleReport().format().startswith(
        "0 reference entries, 0 works cited in text")


def test_the_report_hands_back_the_ENTRIES_it_parsed_not_just_how_many():
    """`entries` and `cited` were ints under collection names until
    2026-08-24, and two scripts hit `TypeError: 'int' object is not
    iterable` in one afternoon (backlog S4). The counts are `n_entries`
    and `n_cited` now; the collections are the collections.

    Worth a test beyond the rename, because the reason to prefer the
    collections was never the TypeError: `audit` parses the reference
    list and used to discard it one line later, so a caller wanting to
    look at an entry had to re-extract what the audit had just built —
    a second parse that can disagree with the first."""
    report = audit(make_parts(body_paragraphs()))

    assert report.n_entries == len(report.entries) > 0
    assert report.n_cited == len(report.cited) > 0
    assert all(r.surname and r.year for r in report.entries)
    # The two sides key alike, which is what makes "cited but not
    # listed" answerable — but they are NOT nested: this fixture cites
    # `maestas_2023` and does not list it, and that gap IS the finding.
    assert set(report.cited) & {r.key for r in report.entries}
    assert all(len(v) == 2 for v in report.cited.values()), "where, snippet"


# --- the second refstyle pass, from the re-measurement ------------------
#
# 44.1 % -> 8.9 % after the two rounds above, and what is left clusters
# on the CONTINUATION-entry rule: three conditions that only ever fired
# together, so a fixture where one holds and the others do not tells the
# `and` from the `or` and the `<` from the `<=`.


def _same_author(second: str, *, cite: str = "(WHO 2019) and (WHO 2018)"
                 ) -> str:
    return (para(run(f"Cited {cite}."))
            + para(run("References"))
            + para(run("WHO. (2019). "), irun("Estimates"), run(". Geneva."))
            + para(run(second), irun("Network"), run(". Geneva.")))


def test_an_entry_that_SPELLS_ITS_AUTHOR_OUT_is_not_a_year_order_issue():
    """`and r.text.lstrip()[:1] in "—–-_"` — a CONTINUATION entry only.
    A shared lead surname over different co-author lists orders by
    co-author, not by year (Alkire & Foster after Alkire, Roche et al.),
    and flagging those buried the real findings on API10.

    Two mutants live in that condition and this fixture is both their
    counter-example: `or` in place of `and` flags every same-author pair
    whose years run backwards, and `[:0]` — the empty string, which is
    "in" every string — flags them too."""
    body = _same_author("WHO. (2018). ")

    report = audit(make_parts(body))

    assert not [i for i in report.issues if i.code == "year-order"]


def test_two_entries_of_the_SAME_year_are_not_out_of_order():
    """`r.year[:4] < prev.year[:4]`, not `<=`: an author with two works
    in one year is the ordinary case — that is what 2013a and 2013b are
    for — and the pair is reported by `ambiguous-cite`, which asks for
    the suffixes, not by `year-order`, which would ask the author to
    swap them."""
    body = _same_author("———. (2019). ",
                        cite="(WHO 2019) and (WHO 2019)")

    report = audit(make_parts(body))

    assert not [i for i in report.issues if i.code == "year-order"]


def test_a_SUFFIXED_year_is_compared_on_its_first_four_characters():
    """`r.year[:4]`: "2019a" and "2019b" are the same YEAR, and this
    rule is about years. Suffixes are assigned in citation order as
    often as alphabetically, so a list running 2019b then 2019a is not
    an author whose works are out of order — under `[:5]` the letters
    join the comparison and it is reported as one."""
    body = (para(run("Cited (WHO 2019b) and (WHO 2019a)."))
            + para(run("References"))
            + para(run("WHO. (2019b). "), irun("Estimates"), run(". Geneva."))
            + para(run("———. (2019a). "), irun("Network"), run(". Geneva.")))

    report = audit(make_parts(body))

    assert not [i for i in report.issues if i.code == "year-order"]


def test_the_year_order_finding_quotes_the_first_fifty_characters():
    """The snippet is what a person finds the entry by, and a
    continuation entry begins with a dash — the fifty characters after
    it are the only thing telling one from the next."""
    long_second = ("———. (2018). A very long entry title that runs past "
                   "the fifty-character cut by a good margin. ")
    body = (para(run("Cited (WHO 2019) and (WHO 2018)."))
            + para(run("References"))
            + para(run("WHO. (2019). "), irun("Estimates"), run(". Geneva."))
            + para(run(long_second), irun("Network"), run(". Geneva.")))

    (order,) = [i for i in audit(make_parts(body)).issues
                if i.code == "year-order"]

    assert order.snippet == ("———. (2018). A very long entry title that "
                             "runs pas")
    assert len(order.snippet) == 50
    assert "(2018) follows (2019)" in order.message


def test_a_DOI_token_is_exempt_from_the_hyphen_rule_on_its_own():
    """`"http" in low OR "doi" in low OR token.startswith("10.")` — three
    independent marks, and the fixtures had only the first two together.
    A bare DOI ("10.1257/aer.20-1234") carries neither word."""
    doi_only = ('Smith, J. (2020). "Title." Journal, 1(1): 1–2. '
                "doi:10.1257/aer.20-1234")
    bare = ('Smith, J. (2020). "Title." Journal, 1(1): 1–2. '
            "10.1257/aer.20-1234")

    assert "en-dash" not in _codes(check_entry(doi_only))
    assert "en-dash" not in _codes(check_entry(bare))


def test_the_year_the_refusal_QUOTES_is_the_year_itself():
    """`m.group(2)` — the year, not the parenthesis either side of it.
    The message shows the corrected form, and a reader checks it against
    the entry in front of them."""
    (issue,) = [i for i in check_entry('Smith, J. 2020. "Title." J, 1: 1.')
                if i.code == "year-parens"]

    assert issue.message == 'the year takes parentheses: "(2020)."'


def test_an_ENDNOTE_issue_is_found_and_numbered_in_its_own_sequence():
    """`en ¶4`. The audit read the body and the footnotes, and several
    journals take the whole apparatus as ENDNOTES — so a paper that
    files its notes at the back had every citation in them unchecked
    and uncounted, and the report said so in the confident voice it
    uses for a paper it has read."""
    ends = notes("endnotes", note("First note.", nid=2, kind="endnote"),
                 note("Second.", nid=3, kind="endnote"),
                 note("Third.", nid=4, kind="endnote"),
                 note("As shown (Smith, 2020) here.", nid=5,
                      kind="endnote"))
    body = para(run("Prose (Acemoglu and Restrepo 2020)."))

    report = audit(make_parts(
        body, extra={"word/endnotes.xml": ends}))

    assert ("year-comma", "en ¶4") in _rows(report)


def test_a_work_cited_only_in_an_endnote_COUNTS_as_cited():
    """The other half, and the one that changes a verdict rather than
    adding a line: `cited` is what "N works cited but no reference
    list" counts and what "cited but not listed" compares against. A
    citation the walk never reached was a work the paper did not have.
    """
    body = para(run("The trend is clear (Maestas et al. 2023)."))
    ends = notes("endnotes",
                 note("See also Smith (2020) on this.", nid=2,
                      kind="endnote"))

    report = audit(make_parts(body, extra={"word/endnotes.xml": ends}))

    (issue,) = [i for i in report.issues if i.code == "no-list"]
    assert issue.message.startswith("2 works cited")


def test_the_two_note_parts_are_numbered_SEPARATELY():
    """`fn ¶1` and `en ¶1` are different paragraphs of different parts,
    and a paper may hold both — Word keeps two id spaces for exactly
    that. One shared sequence would send a person to the wrong note in
    the wrong place."""
    foot = notes("footnotes", note("As in (Smith, 2020).", nid=2))
    ends = notes("endnotes", note("And in (Jones, 2021).", nid=2,
                                  kind="endnote"))

    report = audit(make_parts(para(run("Body prose.")), footnotes=foot,
                              extra={"word/endnotes.xml": ends}))

    where = {i.where for i in report.issues if i.code == "year-comma"}
    assert where == {"fn ¶1", "en ¶1"}, where


# --- the quotes an issue carries, and the guards around the scan --------


def test_an_initials_issue_quotes_SEVENTY_characters_of_the_authors():
    """`snippet=authors[:70]`. The snippet is how a person finds the
    entry the issue is about, and an author list runs to a line and a
    half in a paper with six co-authors; uncut, one issue fills the
    report with the entry it is already pointing at."""
    long_authors = ("Acemoglu, Daron, and Pascual Restrepo, and Jonathan "
                    "Gruber, and Amy Finkelstein")
    assert len(long_authors) > 71
    body = (para(run("References"))
            + para(run(f"{long_authors}. (2020). A paper. "), irun("JPE"),
                   run(", 1(1): 1-10.")))

    report = audit(make_parts(body))

    snippets = [i.snippet for i in report.issues if i.code == "initials"]
    assert snippets, [(i.code, i.snippet) for i in report.issues]
    assert all(len(s) <= 70 for s in snippets), snippets


def test_an_ISBN_keeps_its_hyphens():
    """`low.count("-") >= 3` — a token with three hyphens or more is a
    number, not a range. An ISBN has four and a DOI suffix can have
    several, and "ranges take an en-dash" on one of those sends a person
    to change a hyphen that belongs to an identifier.

    `== 3` is the mutant that hides: the fixture everyone writes has
    exactly three."""
    body = (para(run("References"))
            + para(run("Deaton, A. (2013). The Great Escape. "
                       "ISBN 978-0-691-15354-4. Princeton.")))

    report = audit(make_parts(body))

    assert not [i for i in report.issues if i.code == "en-dash"], \
        [(i.code, i.message) for i in report.issues]


def test_a_bare_citation_paragraph_quotes_the_WHOLE_of_itself():
    """`start=0, end=len(text)` on the synthetic Citation a bare
    reference line produces — a paragraph that is nothing but "Author
    Year", which is how a stripped citation arrives when the author
    retyped it without brackets.

    The pair is what the report quotes back (`text[c.start:c.end]`), so
    an offset of one loses the first character of the name — the part a
    reader scans for."""
    body = (para(run("Maestas et al. 2023"))
            + para(run("References"))
            + para(run("Angrist, J., and J. Pischke. (2009). "),
                   irun("Mostly Harmless"), run(". Princeton.")))

    report = audit(make_parts(body))

    missing = [i for i in report.issues if i.code == "missing-ref"]
    assert missing, [(i.code, i.message) for i in report.issues]
    assert missing[0].snippet == "Maestas et al. 2023"


# --- what is left in refstyle.py, and why -------------------------------
#
# `narrative=False` on the synthetic Citation a bare reference line
# produces. Nothing in `src/` reads `.narrative` — it is part of what
# `find_citations` reports, and the one consumer is a test — so the flag
# on a citation this module builds for itself cannot be observed.
#
# `max((r.index for r in entries), default=-1)` -> `0` and `-2`. The
# default stands for "there are no entries", and it is used only in
# `head_idx <= i <= last_entry`. With no entries there is nothing after
# the heading to skip, and any default at or below the heading's own
# index skips nothing — the three spellings differ only in how far below
# zero they sit.


# --- the run of 2026-08-20: 4.8 % ---------------------------------------


def test_the_initials_issue_quotes_SEVENTY_characters_of_the_authors():
    """`authors[:70]`. An author field with four names spelled out runs
    past that, and the snippet is how a person finds the entry in a list
    of ninety — the code and the message are the same for every one of
    them."""
    entry = ('Abramovich, Daniel, Bartholomew, Elena, Christodoulou, '
             'Fyodor, and Gabriela Dimitropoulos. (2020). "A paper." '
             "Journal, 1(1): 1–10.")

    (issue,) = [i for i in check_entry(entry) if i.code == "initials"]

    assert issue.snippet == ("Abramovich, Daniel, Bartholomew, Elena, "
                            "Christodoulou, Fyodor, and Gab")
    assert len(issue.snippet) == 70


def test_a_token_with_TWO_hyphens_is_still_a_range():
    """`low.count("-") >= 3` skips ISBN-shaped tokens. At two the skip
    swallows an ordinary page range that has been typed with an extra
    hyphen — "10-20-30" is a range a copy-editor should see, and the
    whole point of the en-dash rule is that a hyphen there is invisible
    to a reader and wrong to a typesetter."""
    codes = [i.code for i in check_entry(
        'Smith, J. (2020). "A title." Journal, 1(1): 10-20-30.')]

    assert "en-dash" in codes


def test_a_continuation_entry_in_ASCENDING_years_is_not_flagged():
    """`r.year[:4] < prev.year[:4]`, read as `!=`. Same-author entries
    run oldest first, so a continuation whose year is LATER than the one
    above it is the correct order — and inequality flags every one of
    them. A gate that fires on a well-ordered list is one the next
    reader waves through."""
    body = (para(run("Prose paragraph with no citations at all."))
            + para(run("References"))
            + para(run('World Health Organization. (2015). "First." WHO.'))
            + para(run('———. (2019). "Second." WHO.')))

    codes = [i.code for i in audit(make_parts(body)).issues]

    assert "year-order" not in codes, codes


def test_a_year_order_problem_IS_flagged_when_it_is_one():
    """The other side of the same comparison, so neither reading of it
    can pass by being silent."""
    body = (para(run("Prose paragraph with no citations at all."))
            + para(run("References"))
            + para(run('World Health Organization. (2019). "First." WHO.'))
            + para(run('———. (2015). "Second." WHO.')))

    issues = [i for i in audit(make_parts(body)).issues
              if i.code == "year-order"]

    assert len(issues) == 1
    assert "(2015) follows (2019)" in issues[0].message


def test_a_single_entry_group_does_not_END_the_ambiguity_scan():
    """`continue`. The groups are walked in the order the entries were
    read, so a work cited once before a genuinely ambiguous pair is the
    ordinary arrangement — and a `break` there reports nothing at all
    for the document that has the problem."""
    body = (para(run("As (Alpha 2001) and (Beta 2002) show."))
            + para(run("References"))
            + para(run('Alpha, A. (2001). "Only one." Journal, 1(1): 1–2.'))
            + para(run('Beta, B. (2002). "First of two." Journal, 2(1): 3–4.'))
            + para(run('Beta, B. (2002). "Second of two." Journal, 2(2): '
                       "5–6.")))

    ambiguous = [i for i in audit(make_parts(body)).issues
                 if i.code == "ambiguous-cite"]

    assert len(ambiguous) == 2
    assert all("distinguish them as 2002a, 2002b" in i.message
               for i in ambiguous)


# Argued rather than pinned, from the same run:
#
# * the three on `_fold(prev.surname) == _fold(r.surname)` in the
#   year-order check. The condition beside it requires `r.text` to open
#   with a continuation dash, and `references` files a continuation
#   under the PREVIOUS entry's surname — so the two folded names are
#   equal wherever the check can fire, and `<=`, `>=` and `is not` all
#   agree there.
# * `r.year[:4]` written `[:5]` on the same line. The suffix a fifth
#   character carries ("2015a") cannot flip a comparison against a
#   four-digit prefix: it only ever makes the left side sort later
#   within the same year.
# * `group[0].year` written `[-1]` or `[1]` in the ambiguity message.
#   The group is keyed on surname AND year, so every entry in it has
#   the same year — which is what the key comment says the suffix
#   distinction is for.
# * `zip(entries, answers_to, strict=True)` written `strict=False`:
#   `answers_to` is built one entry at a time from the same list.
#
# The four on `max(..., default=-1)` — the sentinel for a document whose
# reference list did not parse — are argued too, and the argument is
# two lines rather than the fixture it looked like it needed:
#
# * the values BELOW zero (`-2`, `~1`) leave `head_idx <= i <=
#   last_entry` empty, because a paragraph index is never negative;
# * the value AT zero (`-0`, `not 1`) can only add the paragraph at
#   index 0 to the skipped range, and only when the heading IS that
#   paragraph — and a heading paragraph's text equals a heading word
#   exactly, which is how `head_idx` found it. There is nothing in it
#   for the prose scan to report either way.
#
# The `head_idx <= i` on the line that uses it goes the same way: read
# as `<`, the paragraph it stops skipping is that same heading.
#
# So refstyle is CLOSED: every survivor argued and put through
# kill_check.


# ----------------------------------------- the apparatus knows better ---

_ILOSTAT = ('ILOSTAT. (2024). "Statistics on Employment." ')
_SWALLOWED = ("Employment is consolidated from standardized national "
              "Labor Force Surveys and ")


def _entry_para() -> str:
    return para(run(_ILOSTAT) + irun("ILO Data") + run("."))


def _linked(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>{label}</w:t>'
            f"</w:r></w:hyperlink>")


def _mark(name: str) -> str:
    return (f'<w:bookmarkStart w:id="3" w:name="{name}"/>'
            f'<w:bookmarkEnd w:id="3"/>')


def test_a_LINKED_citation_swallowed_by_the_two_author_pattern_is_re_read():
    """`X and Y (Year)` only needs X capitalised, so "…national Labor
    Force Surveys and ILOSTAT (2024) data…" read as a citation of
    "Surveys and ILOSTAT" and reported `missing-ref` against a list that
    holds ILOSTAT. The paper could not reach a clean report, which is
    what stops the audit being usable as a gate (AFI r4).

    The document had already answered: that span is a live hyperlink to
    the entry's own bookmark.
    """
    parts = make_parts(
        para(run(_SWALLOWED), _linked("ILOSTAT2024", "ILOSTAT (2024)"),
             run(" data on employment."))
        + para(run("References")) + _mark("ILOSTAT2024") + _entry_para())

    report = audit(parts)

    assert "missing-ref" not in _codes(report.issues), [
        (i.code, i.snippet) for i in report.issues]
    assert "uncited-ref" not in _codes(report.issues), [
        (i.code, i.snippet) for i in report.issues]
    assert report.n_cited == 1


def test_a_link_to_something_that_is_NOT_an_entry_governs_nothing():
    """The rule is "the document resolved this citation", and a
    cross-reference to a table has resolved nothing about it. Trusting
    any link would let a caption anchor rewrite a citation's extent.
    """
    parts = make_parts(
        para(run(_SWALLOWED), _linked("Table3", "ILOSTAT (2024)"),
             run(" data on employment."))
        + _mark("Table3")
        + para(run("References")) + _entry_para())

    report = audit(parts)

    assert "missing-ref" in _codes(report.issues), [
        (i.code, i.snippet) for i in report.issues]


def test_a_citation_the_pattern_reads_EXACTLY_is_left_alone():
    """The label equals the span, so there is nothing to re-read — and
    a rule that fired here would re-parse every linked citation in the
    manuscript for no gain.
    """
    parts = make_parts(
        para(run("As "), _linked("ILOSTAT2024", "ILOSTAT (2024)"),
             run(" reports, it rises."))
        + para(run("References")) + _mark("ILOSTAT2024") + _entry_para())

    report = audit(parts)

    assert not _codes(report.issues) & {"missing-ref", "uncited-ref"}, [
        (i.code, i.snippet) for i in report.issues]
    assert report.n_cited == 1


def test_the_re_read_citation_KEEPS_ITS_PLACE_in_the_paragraph():
    """Offsets, not just the answer. Every prose check reports
    `text[c.start:c.end]` as its snippet, so a citation re-read at the
    wrong offset is a finding pointing at the wrong words.
    """
    text = ("Employment is consolidated from standardized national Labor "
            "Force Surveys and ILOSTAT (2024) data on employment.")

    out = _trust_the_links(text, find_citations(text), ["ILOSTAT (2024)"])

    assert [text[c.start:c.end] for c in out] == ["ILOSTAT (2024)"]


def test_a_PARENTHETICAL_label_is_read_back_inside_its_parentheses():
    """"(Kanbur 2007)" is a citation; `Kanbur 2007` is two words. The
    label a link carries is the second, so reading it alone finds
    nothing — and dropping the citation would take a cited work out of
    the cross-check and report its entry as UNCITED.
    """
    text = "It rose sharply (Labor Force Surveys and ILOSTAT 2024) last year."

    out = _trust_the_links(text, find_citations(text), ["ILOSTAT 2024"])

    assert [text[c.start:c.end] for c in out] == ["ILOSTAT 2024"]


def test_a_parenthetical_label_with_a_LEADING_WORD_reads_at_its_own_offset():
    """`_read_label` puts the parentheses back and shifts the offsets by
    the one character that adds. Every fixture for it had the citation
    at the very start of the label, where the shift is 1 - 1 = 0 and
    three spellings of the arithmetic agree. A link that swallowed a
    leading word — "as Kanbur 2007" — has it four characters in, and
    the shift is the difference between naming the citation and naming
    four characters of prose in front of it.
    """
    found = _read_label("as Kanbur 2007")

    assert [(f.start, f.end) for f in found] == [(3, 14)]
    assert "as Kanbur 2007"[3:14] == "Kanbur 2007"


def test_a_label_that_says_NOTHING_leaves_the_citation_as_it_was():
    """This narrows a match; it never deletes one. A link wrapping the
    NAME and not the year — which is how a paper links an organisation
    it also cites — carries a label that is no citation at all, and
    dropping the match would lose a cited work silently.
    """
    text = "As Labor Force Surveys and ILOSTAT (2024) report, it rises."

    out = _trust_the_links(text, find_citations(text), ["ILOSTAT"])

    assert [text[c.start:c.end] for c in out] == ["Surveys and ILOSTAT (2024)"]


def test_an_UNLINKED_manuscript_is_still_read_by_the_pattern_alone():
    """Recorded, not celebrated: with no apparatus there is no fact to
    read, and the pattern is all there is. The backlog entry says so.
    """
    parts = make_parts(
        para(run(_SWALLOWED + "ILOSTAT (2024) data on employment."))
        + para(run("References")) + _entry_para())

    report = audit(parts)

    assert "missing-ref" in _codes(report.issues)

#
# `lab != span` in `_trust_the_links` is EQUIVALENT and left alive. A
# label equal to the span re-reads to the same citation at the same
# offsets — `_read_label` puts a parenthetical's parentheses back, so
# even the form that does not parse alone comes out unchanged. The guard
# is there to say what the function is FOR (a span that swallowed a
# linked one), and to skip the re-parse on every already-exact citation
# in a fully linked manuscript.


# ------------------------------------------------ converting, not just ---
#                                                       reporting
#
# `refstyle` reported per-entry, per-rule findings and could change none
# of them, so AFI r4 wrote ~250 lines across three scripts to convert 25
# entries and 14 citations. What it converts here is the mechanical
# half: punctuation and glyphs. Names are NOT touched — reducing "Till
# Von Wachter" by last-word-is-surname gives "Wachter, T.", a renamed
# author in a pass whose premise is that no author changes.

CHICAGO_ENTRY = ('Acemoglu, D. & P. Restrepo. 2020. "Robots and Jobs." '
                 "JPE, 128(6): 2188-2244.")


def test_convert_moves_the_punctuation_and_the_glyphs():
    out, fixes = convert_text(CHICAGO_ENTRY)

    assert [f.code for f in fixes] == ["ampersand", "and-comma",
                                       "year-parens", "en-dash"]
    assert out == ('Acemoglu, D., and P. Restrepo. (2020). "Robots and '
                   'Jobs." JPE, 128(6): 2188–2244.')


def test_convert_writes_an_ABBREVIATED_page_range_out_in_full():
    """"174–79" is the one change that legitimately alters DIGITS, which
    is why the invariant has to know about it rather than forbid it."""
    out, fixes = convert_text('N. (2023). "Ageing." AEJ, 15(2): pp.174-79.')

    assert "pp. 174–179" in out
    assert {f.code for f in fixes} == {"en-dash", "page-space"}


def test_convert_leaves_a_DOI_and_a_YEAR_RANGE_alone():
    """A DOI keeps its hyphens, and "1875–1912" is already a full range —
    AFI's own linker read Lai 1912 out of one and Riekhoff 0233 out of a
    DOI once the year moved into parentheses."""
    entry = ('Lai, K. (1990). "A history, 1875-1912." Journal. '
             "https://doi.org/10.1007/s11205-023-03089-7")
    out, fixes = convert_text(entry)

    assert "10.1007/s11205-023-03089-7" in out, out
    assert "1875–1912" in out, out
    assert [f.code for f in fixes] == ["en-dash"]


def test_a_range_whose_SECOND_number_is_longer_only_gets_its_dash_fixed():
    """Expansion carries the first number's leading digits onto the
    second, which is nonsense when the second is already longer — an
    ordinary "998-1024" would come out "998–991024", a page nobody
    wrote, inside a pass whose whole claim is that it changes
    punctuation only."""
    out, _ = convert_text('A. (2020). "T." Journal, 1(1): 998-1024.')

    assert "998–1024" in out, out


def test_convert_does_NOT_touch_author_names():
    """The trap that would rename an author. `check_entry` still reports
    the spelled-out given name; this refuses to be the thing that acts
    on it."""
    entry = 'Von Wachter, Till. (2020). "Lost generations." JEP, 34(4): 1-10.'
    out, _ = convert_text(entry)

    assert "Von Wachter, Till." in out
    assert any(i.code == "initials" for i in check_entry(entry))


def test_an_entry_that_KEEPS_its_ampersand_is_not_refused():
    """A title's "&" is not an author separator and this does not touch
    it — but the invariant normalised "&" to "and" on one side only, so
    the entry read as changed and refused although nothing had been done
    to it. Found by review an hour after the converter landed."""
    entry = 'Smith, J. (2020). "Robots & Jobs." Journal, 1(1): 1-10.'

    assert convert_text(entry) == (entry, [])


def test_the_AUTHORS_ampersand_is_converted_and_the_TITLE_keeps_its_own():
    """Both in one entry, which is what says the rule is about WHERE the
    ampersand is rather than about the character."""
    out, fixes = convert_text(
        'Smith, J. & A. Lee. 2020. "Robots & Jobs." Journal, 1(1): 1-10.')

    assert out.startswith("Smith, J., and A. Lee. (2020).")
    assert '"Robots & Jobs."' in out
    assert [f.code for f in fixes] == ["ampersand", "and-comma",
                                       "year-parens"]


def test_convert_writes_the_BARE_year_when_the_style_says_so():
    out, fixes = convert_text('Smith, J. (2020). "A title." Journal.',
                              CHICAGO)

    assert out.startswith("Smith, J. 2020.")
    assert [f.code for f in fixes] == ["year-parens"]


def test_an_entry_ALREADY_in_the_style_is_not_touched():
    assert convert_text(CLEAN_ARTICLE) == (CLEAN_ARTICLE, [])


def test_a_conversion_that_would_change_what_the_entry_SAYS_is_REFUSED(
        monkeypatch):
    """The invariant is the valuable part: letters and digits identical
    before and after, once "&"-to-"and" and a written-out page range are
    accounted for. A dropped author, a lost DOI or a truncated title
    fails here rather than in the file."""
    monkeypatch.setattr(
        refstyle, "convert_entry",
        lambda text, style=HOUSE: [
            refstyle.Fix("year-parens", "Restrepo", "")])

    with pytest.raises(ConversionRefused, match="would change what it SAYS"):
        convert_text(CHICAGO_ENTRY)


# ------------------------------------------------- and into a document ---

def _list_parts(*entries: str, italic: str = ""):
    """The entries as a document — with the ampersand ESCAPED, because
    a bare `&` in a `w:t` is not XML and not a file Word can produce.
    The converter reads through `visible_text`, which unescapes, and
    writes through `set_run_text`, which escapes again."""
    body = [para(run("Prose citing something.")), para(run("References"))]
    for text in entries:
        body.append(para(run(text.replace("&", "&amp;"))
                         + (irun(italic) if italic else "")))
    return make_parts("".join(body))


def test_convert_writes_the_fixes_into_the_reference_block():
    parts = _list_parts(CHICAGO_ENTRY)

    report = convert(parts)

    assert [line.split(": ")[1] for line in report.changed] == [
        "ampersand", "and-comma", "year-parens", "en-dash"]
    assert "and P. Restrepo. (2020)." in parts["word/document.xml"].decode()


def test_the_ITALIC_outlet_survives_the_conversion():
    """The reason a fix is a FRAGMENT and not a rewritten entry: putting
    the new text into the paragraph wholesale flattens every run, and
    the italic journal name it also audits for would be gone — the
    conversion would create the finding beside it."""
    parts = _list_parts(CHICAGO_ENTRY, italic="Journal of Political Economy")

    convert(parts)

    doc = parts["word/document.xml"].decode()
    assert "<w:i/>" in doc
    assert "Journal of Political Economy" in doc


def test_PROSE_is_not_converted_only_the_entries():
    """The in-text rules change what a sentence SAYS and belong to the
    author. Only the reference block is written."""
    parts = make_parts(
        para(run("As Smith & Jones 2020. argue, it rose."))
        + para(run("References"))
        + para(run(CHICAGO_ENTRY)))

    convert(parts)

    assert "Smith & Jones 2020." in parts["word/document.xml"].decode()


def test_a_fix_that_would_cross_a_LINK_is_skipped_and_named():
    """`replace_in_para` refuses a span that meets a hyperlink label,
    for reasons this module does not get to overrule — an entry whose
    DOI is linked keeps its link, and the report says which."""
    linked = ('<w:hyperlink w:anchor="doi1"><w:r><w:t>2188-2244</w:t>'
              "</w:r></w:hyperlink>")
    parts = make_parts(
        para(run("Prose.")) + para(run("References"))
        + para(run('Acemoglu, D. (2020). "Robots." JPE, 128(6): ') + linked
               + run(".")))

    report = convert(parts)

    assert report.skipped and "en-dash" in report.skipped[0]
    assert "2188-2244" in parts["word/document.xml"].decode()


def test_the_convert_report_PRINTS_what_it_did():
    parts = _list_parts(CHICAGO_ENTRY)

    text = convert(parts).format()

    assert text.startswith("4 fix(es) written, 0 entr(ies) refused")
    assert "ampersand" in text


# ---------------------------------------- what the mutation round found ---
#
# refstyle's 2026-08-21 measurement put 19 of its 24 real survivors in
# the converter that had landed an hour earlier. These are the gaps.

def test_the_CONVERTER_leaves_an_ISBN_alone():
    """Three hyphens or more is not a range, and the token test is an
    OR: a DOI, a URL, *or* an ISBN. Read as an `and` it protects only
    the tokens that are both, and rewrites the rest."""
    entry = ('Smith, J. (2020). Robots. Oxford: OUP. ISBN 978-0-19-874017-4.')

    out, fixes = convert_text(entry)

    assert "978-0-19-874017-4" in out, out
    assert not fixes


def test_a_URL_that_is_not_a_DOI_keeps_its_hyphens_too():
    """The token test is three alternatives and each one earns its
    place: a plain URL carries no "doi" and need not start with "10.",
    and an en-dash written into one is a link that 404s."""
    entry = ('World Bank. (2024). "Data." '
             "https://data.worldbank.org/reports/2020-2024/summary")

    out, fixes = convert_text(entry)

    assert "2020-2024" in out, out
    assert not fixes


@pytest.mark.parametrize("doi", [
    "doi:10.1111/j.1467-9787.2010.00713.x",   # the "doi" spelling
    "10.1111/j.1467-9787.2010.00713.x",       # bare, the "10." spelling
])
def test_a_DOI_written_WITHOUT_a_URL_keeps_its_hyphens(doi):
    """Wiley's suffix carries ONE hyphen between two four-digit groups —
    "1467-9787" is exactly the shape of a page range, and the
    three-hyphens-is-a-number test does not reach it. A DOI with an
    en-dash in it resolves to nothing."""
    out, fixes = convert_text(f'A. (2020). "T." Journal. {doi}')

    assert doi in out, out
    assert not fixes


def test_et_al_takes_its_period():
    out, fixes = convert_text(
        'Smith, J. et al 2019. "A title." Journal, 1(1): 45-48.')

    assert "Smith, J. et al. (2019)." in out
    assert "et-al-period" in [f.code for f in fixes]


def test_TWO_bare_et_als_are_reported_as_two_fixes():
    """One fix per occurrence, each applied once. Applying the first
    twice reaches the same text and reports one — and the count is what
    a caller reads to know what was done to their manuscript."""
    out, fixes = convert_text(
        'Smith, J. et al 2019. "As Jones et al showed." Journal, 1(1): 45-48.')

    assert out.count("et al.") == 2, out
    assert [f.code for f in fixes].count("et-al-period") == 2


def test_an_AMPERSAND_and_an_EXPANSION_in_one_entry_still_pass():
    """The invariant's per-fix accounting is for the range expansion
    ONLY. Letting an ampersand fix through it inserts "and" into a
    string the ampersand has already been dropped from, and the entry
    refuses although both changes are exactly what was asked for."""
    out, fixes = convert_text(
        'Smith, J. & A. Lee. 2020. "T." Journal, 1(1): 174-79.')

    assert out.endswith("174–179.")
    assert [f.code for f in fixes] == ["ampersand", "and-comma",
                                       "year-parens", "en-dash"]


def test_a_fix_whose_WINDOW_an_earlier_fix_rewrote_is_still_applied():
    """`year-parens` quotes the eight characters in front of the year to
    make its fragment unique, and those eight are copied from the text
    as `convert_entry` was given it. Here they hold the ampersand — so
    the ampersand fix ran first and the window vanished, the single pass
    skipped the fix as "already covered", `--fix` reported two written
    with no REFUSED or SKIPPED line, and the next `audit` reported the
    same entry's year again. Nothing said the fix had been dropped.
    """
    out, fixes = convert_text("Smith, J. & Lee 2020. Title here.")

    assert out == "Smith, J., and Lee (2020). Title here."
    assert [f.code for f in fixes] == ["ampersand", "and-comma",
                                       "year-parens"]
    assert not convert_entry(out), "the entry still reads as unconverted"


def test_the_fixes_of_a_converted_entry_are_applied_ONCE():
    """The re-read must not become a second application: `convert_entry`
    is asked again for exactly as long as it finds something new, and a
    fix it keeps returning unchanged is one that has already run."""
    entry = 'Smith, J. & A. Lee. 2020. "Robots & Jobs." Journal, 1(1): 1-10.'

    out, fixes = convert_text(entry)

    assert out.count("and A. Lee") == 1
    assert '"Robots & Jobs."' in out, "a title's ampersand is not an author's"
    assert len(fixes) == len(set(fixes)) == 3


def test_a_conversion_that_ADDS_text_is_refused_too(monkeypatch):
    """The invariant is an inequality in both directions: a fix that
    inserts words is as much a change to what the entry SAYS as one that
    drops them."""
    monkeypatch.setattr(
        refstyle, "convert_entry",
        lambda text, style=HOUSE: [
            refstyle.Fix("year-parens", "Restrepo", "Restrepo and Others")])

    with pytest.raises(ConversionRefused, match="would change what it SAYS"):
        convert_text(CHICAGO_ENTRY)


def test_a_range_expands_from_the_FULL_leading_number():
    """"1874-79" is 1874–1879, not 1874–79 and not 1874–1479: the digits
    carried over are the leading ones the short form left off."""
    out, _ = convert_text('A. (2020). "T." Journal, 1(1): 1874-79.')

    assert out.endswith("1874–1879.")


# ----------------------------------------------- and into the document ---

def test_the_report_names_the_PARAGRAPH_each_fix_landed_in():
    """A report is read to go and look. "¶3" that is really ¶4 sends a
    reader to the entry above the one that changed."""
    parts = _list_parts("Kanbur, R. (2007). Poverty. Journal, 1(1): 45–48.",
                        CHICAGO_ENTRY)

    report = convert(parts)

    assert {line.split(":")[0] for line in report.changed} == {"¶4"}


def test_convert_REPORTS_an_entry_it_refused_and_writes_nothing(monkeypatch):
    """One bad entry does not stop the pass and does not go in: the
    refusal is per entry, and the file keeps what it had."""
    parts = _list_parts(CHICAGO_ENTRY)
    before = parts["word/document.xml"]
    monkeypatch.setattr(
        refstyle, "convert_entry",
        lambda text, style=HOUSE: [
            refstyle.Fix("year-parens", "Restrepo", "")])

    report = convert(parts)

    assert report.refused and "¶3" in report.refused[0]
    assert not report.changed
    assert parts["word/document.xml"] == before


def test_an_entry_whose_ONLY_fix_shortens_it_is_still_written():
    """The write is guarded on "did this paragraph change", not on which
    way it sorts: "pp.174" -> "pp. 174" puts a space where a digit was,
    and an ordering test reads that as nothing to do."""
    parts = _list_parts('Kanbur, R. (2007). "Poverty." Journal, 1(1): pp.45.')

    convert(parts)

    assert "pp. 45" in parts["word/document.xml"].decode()


def test_a_linked_citation_ELSEWHERE_in_the_paragraph_is_not_borrowed():
    """The label has to be inside the span it narrows. A paragraph
    routinely carries two citations with one of them linked, and reading
    the link's label as the OTHER one's answer rewrites a citation the
    apparatus has said nothing about."""
    text = ("As Kanbur 2007 and Labor Force Surveys and ILOSTAT (2024) "
            "report, it rises.")

    out = _trust_the_links(text, find_citations(text), ["Kanbur 2007"])

    assert [text[c.start:c.end] for c in out] == [
        text[c.start:c.end] for c in find_citations(text)]


def test_a_label_whose_citation_starts_INSIDE_it_keeps_its_place():
    """A hand-made link swallows a leading word often enough — "and
    ILOSTAT (2024)" — and the citation then begins four characters into
    the label. The offset a caller gets has to be the CITATION's: every
    prose check reports `text[c.start:c.end]`, so the label's own start
    points the finding at the wrong words."""
    text = ("Employment is consolidated from national Labor Force Surveys "
            "and ILOSTAT (2024) data on employment.")

    out = _trust_the_links(text, find_citations(text),
                           ["and ILOSTAT (2024)"])

    assert [text[c.start:c.end] for c in out] == ["ILOSTAT (2024)"]


def test_a_bookmark_in_PROSE_is_not_read_as_an_entry_anchor():
    """The gap read for an entry is the one immediately above it. A
    wider slice picks up markers that belong to no entry at all — and a
    link to one of those is a cross-reference, which has resolved
    nothing about the citation beside it."""
    stray = ('<w:bookmarkStart w:id="9" w:name="ref_note_1"/>'
             '<w:bookmarkEnd w:id="9"/>')
    linked = ('<w:hyperlink w:anchor="ref_note_1"><w:r>'
              "<w:t>ILOSTAT (2024)</w:t></w:r></w:hyperlink>")
    parts = make_parts(
        para(run("An opening paragraph."))
        + para(run("From national Labor Force Surveys and "), linked,
               run(" data."))
        + stray                      # body level, and no entry's
        + para(run("References"))
        + _entry_para())

    report = audit(parts)

    assert "missing-ref" in _codes(report.issues), [
        (i.code, i.snippet) for i in report.issues]


def test_the_gap_read_for_an_entry_is_the_one_ABOVE_IT():
    """Word hoists a marker out of the paragraph head, so the bookmark
    belonging to entry N sits between N-1 and N. Reading any other gap
    finds a marker belonging to a different work — or none, and then the
    swallowed citation is not recognised at all."""
    linked = ('<w:hyperlink w:anchor="ref_ilostat_2024"><w:r>'
              "<w:t>ILOSTAT (2024)</w:t></w:r></w:hyperlink>")
    hoisted = ('<w:bookmarkStart w:id="3" w:name="ref_ilostat_2024"/>'
               '<w:bookmarkEnd w:id="3"/>')
    parts = make_parts(
        para(run("Employment is consolidated from national Labor Force "
                 "Surveys and "), linked, run(" data."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal, 1(1): 45–48."))
        + para(run("Maestas, N. (2023). Ageing. Journal, 2(1): 1–9."))
        + hoisted
        + para(run('ILOSTAT. (2024). "Statistics." ') + irun("ILO")))

    report = audit(parts)

    assert "missing-ref" not in _codes(report.issues), [
        (i.code, i.snippet) for i in report.issues]


# refstyle's remaining converter survivors, argued rather than pinned
# (2026-08-21 round):
#
# `lead = text[max(0, at - 8):at]` in `convert_entry` — eight characters
# of context in front of the year, mutated to nine, to `at ** 8` and to
# `at << 8`. The lead makes the fragment UNIQUE; it is not what decides
# which span is the year's, and every spelling still replaces the first
# occurrence, which in a reference entry is the year. A test would pin
# the number, not the behaviour.
#
# Same for the three characters after `p.` in the page-space fix
# (`sp.end() + 3` -> `^ 3`): the digits are there to tell one "p." from
# another, and both spellings reach the same one on every entry that
# has a single page reference.
#
# `if fix.code is "en-dash"` — the codes are literals in this module,
# so the identity comparison and the equality are the same test on the
# same interned string.
#
# `max((r.index for r in entries), default=-1)` -> `-2` in `audit`: the
# default is reached only when there are NO entries, and `head_idx` is
# then None, so the range `head_idx <= i <= last_entry` is never asked.


# refstyle's survivors after the second round of 2026-08-21, argued:
#
# `at, end = max(0, et.start() - 1), et.end() + 1` read as `et.start()
# + 1`. The fragment then opens inside the words — "t al " for "et al "
# — and its replacement is "t al. ", so the text that lands is the same
# text. What the leading character buys is an anchor: the fragment is
# unique in the entry, which is what stops the second of two fixes
# meeting the first one's output. That property is pinned by the
# two-et-als test; the offset itself is not a behaviour.
#
# `lead = text[max(0, at - 8):at]` read as `+ 8`, `- 9` and `^ 8`, and
# the three characters after `p.` read as `^ 3` and `| 3`: both are
# uniqueness aids in front of a fragment whose FIRST occurrence is the
# one meant. Freezing the number would pin the fixture, not the rule.
#
# `find_citations(f"({label})") if f.start >= 1` read as `>= 0`: the
# parenthetical grammar's span excludes the parentheses it needs, so
# nothing it finds inside "(label)" can start at the "(" itself.


# --- a link IS a citation ---------------------------------------------


def _group_cite_paper() -> str:
    """A work cited only as a bare year inside a multi-year group.

    "Sen's capability approach (1985, 1999, 2009)" puts four words
    between the name and the parenthesis, so no grammar here reaches it;
    the paper's own apparatus links each year to its entry.
    """
    def link(anchor: str, label: str) -> str:
        return (f'<w:hyperlink w:anchor="{anchor}">'
                f'<w:r><w:t>{label}</w:t></w:r></w:hyperlink>')

    return (
        para(run("This definition draws on Sen's capability approach ("),
             link("Sen1985", "1985"), run(", "),
             link("Sen2009", "2009"), run(")."))
        + para(run("References"))
        + para('<w:bookmarkStart w:id="1" w:name="Sen1985"/>'
               '<w:bookmarkEnd w:id="1"/>'
               + run("Sen, A. (1985). "), irun("Commodities and Capabilities"),
               run(". Amsterdam: North-Holland."))
        + para('<w:bookmarkStart w:id="2" w:name="Sen2009"/>'
               '<w:bookmarkEnd w:id="2"/>'
               + run("Sen, A. (2009). "), irun("The Idea of Justice"),
               run(". Cambridge, MA: Harvard University Press."))
    )


def test_a_work_LINKED_from_the_prose_is_cited_whatever_the_grammar_reads():
    """`citations` counted these links and reported the file fully
    linked while this audit called both entries uncited. Two tools
    disagreeing about one document, and a paper acting on the finding
    would delete a cited entry."""
    report = audit(make_parts(_group_cite_paper()), page_layout=None)

    assert "uncited-ref" not in _codes(report.issues)
    assert report.n_cited == 2


def test_the_grammar_still_answers_where_there_are_no_links():
    """The link is FALLBACK evidence. An unlinked manuscript has only
    the pattern, and it still runs."""
    body = (para(run("Robots displace workers (Acemoglu and Restrepo 2020)."))
            + para(run("References"))
            + para(run("Acemoglu, D., and P. Restrepo. (2020). "),
                   irun("JPE"), run(", 128(6): 2188–2244.")))
    report = audit(make_parts(body), page_layout=None)
    assert "uncited-ref" not in _codes(report.issues)


def test_a_LINKED_citation_keeps_the_snippet_the_prose_scan_read():
    """`setdefault`: the link is not the better evidence, only the one
    that is there when the pattern finds nothing."""
    body = (para(run("Robots displace workers ("),
                 '<w:hyperlink w:anchor="Acemoglu2020">'
                 "<w:r><w:t>Acemoglu and Restrepo 2020</w:t></w:r>"
                 "</w:hyperlink>", run(")."))
            + para(run("References"))
            + para('<w:bookmarkStart w:id="1" w:name="Acemoglu2020"/>'
                   '<w:bookmarkEnd w:id="1"/>'
                   + run("Acemoglu, D., and P. Restrepo. (2021). "),
                   irun("JPE"), run(", 128(6): 2188–2244.")))
    # The entry is dated 2021 and the citation says 2020: the prose scan
    # and the link disagree, and the finding that survives is the one
    # about the YEAR, not a phantom uncited entry.
    report = audit(make_parts(body), page_layout=None)
    assert "uncited-ref" not in _codes(report.issues)


def test_the_same_paper_WITHOUT_the_links_does_report_them_uncited():
    """The negative control, and the proof the links are what clear it:
    strip the hyperlinks out of the fixture above and the grammar has
    nothing left, so both entries report."""
    stripped = re.sub(r"</?w:hyperlink[^>]*>", "", _group_cite_paper())
    report = audit(make_parts(stripped), page_layout=None)
    assert [i.code for i in report.issues].count("uncited-ref") == 2


def _appended_run() -> str:
    """The shape that defeated the neighbour test: two entries added at
    the END of a filed list, so only the first pair inverts."""
    def entry(text: str) -> str:
        return para(run(text + " "), irun("J"), run(", 1(1): 1-2."))

    return (para(run("Cited: (Currie 1999), (Diller 2016), (Sen 2004), "
                     "(Sen 2009) and (Zaidi 2013)."))
            + para(run("References"))
            + entry("Currie, J. (1999). “Health.”")
            + entry("Sen, A. (2009). “Justice.”")
            + entry("Zaidi, A. (2013). “Active Ageing.”")
            + entry("Diller, R. (2016). “Legal Capacity.”")
            + entry("Sen, A. (2004). “Human Rights.”"))


def test_every_misfiled_entry_is_named_not_just_the_first_inversion():
    """Aging_Well, 2026-08-23: the author appended Diller (2016) and Sen
    (2004) after Zaidi and the audit named Diller alone, because the
    check compared each entry with the one above it and the appended run
    inverts only at its first pair. Fixing the named one and re-running
    to a clean report says the list is sorted when it is not."""
    report = audit(make_parts(_appended_run()), page_layout=None)

    named = {i.snippet.split(",")[0] for i in report.issues
             if i.code == "order"}
    assert named == {"Diller", "Sen"}


def test_a_same_author_entry_out_of_order_is_caught_at_all():
    """"Sen, A. (2004)" after "Sen, A. (2009)" has nothing for a surname
    comparison to see, and the year check that would is restricted to
    continuation entries for a reason of its own."""
    def entry(text: str) -> str:
        return para(run(text + " "), irun("J"), run(", 1(1): 1-2."))

    body = (para(run("Cited: (Sen 2004) and (Sen 2009)."))
            + para(run("References"))
            + entry("Sen, A. (2009). “Justice.”")
            + entry("Sen, A. (2004). “Human Rights.”"))
    report = audit(make_parts(body), page_layout=None)
    assert [i.code for i in report.issues].count("order") == 1


def test_an_institutional_name_still_files_where_the_manuals_put_it():
    """The tie-break is the whole text, punctuation kept -- but the
    SURNAME decides first, folded. Sorting raw text alone puts "U.S.
    Census Bureau" before "United Nations", because `.` sorts ahead of a
    letter."""
    body = (para(run("Cited (United Nations 2019) and (Bureau 2023)."))
            + para(run("References"))
            + para(run("United Nations (2019). "), irun("World Population"),
                   run(". New York: UN."))
            + para(run("U.S. Census Bureau. (2023). "), irun("Age Heaping"),
                   run(". Washington, DC.")))
    report = audit(make_parts(body), page_layout=None)
    assert not [i for i in report.issues if i.code == "order"]


def test_a_solo_entry_files_before_the_same_author_with_co_authors():
    """`(` sorts before `,`, which is what an author's own list does --
    and what the surname alone cannot settle."""
    body = (para(run("Cited (Scott 2024) and (Scott et al. 2021)."))
            + para(run("References"))
            + para(run("Scott, A. (2024). "), irun("The Longevity Imperative"),
                   run(". Dublin: Murray."))
            + para(run("Scott, A., Ellison, M., and D. Sinclair. (2021). "),
                   irun("Nature Aging"), run(", 1(7): 616-623.")))
    report = audit(make_parts(body), page_layout=None)
    assert not [i for i in report.issues if i.code == "order"]


def test_a_continuation_list_is_left_to_the_year_check():
    """"---. (2015)." files under the name above it, so the whole-text
    key would scatter the group; `refile` refuses such a list too."""
    body = (para(run("Cited (WHO 2015) and (WHO 2002)."))
            + para(run("References"))
            + para(run("WHO. (2015). "), irun("World Report"),
                   run(". Geneva: WHO."))
            + para(run("———. (2002). "), irun("Active Ageing"),
                   run(". Geneva: WHO.")))
    report = audit(make_parts(body), page_layout=None)
    assert not [i for i in report.issues if i.code == "order"]
    assert [i.code for i in report.issues].count("year-order") == 1


def test_the_order_message_names_BOTH_neighbours_of_where_it_belongs():
    """Mutation analysis, 2026-08-23: `order[j - 1]` and `order[j + 1]`
    survived every arithmetic mutation, because the fixtures were two
    entries long and every index collided. Five entries, and the one
    that moves belongs in the MIDDLE, so `j-1` and `j+1` are distinct
    surnames a message can be wrong about."""
    def entry(text: str) -> str:
        return para(run(text + " "), irun("J"), run(", 1(1): 1-2."))

    body = (para(run("Cited: (Anders 2001), (Baker 2002), (Currie 1999), "
                     "(Diller 2016) and (Evans 2020)."))
            + para(run("References"))
            + entry("Anders, A. (2001). “First.”")
            + entry("Baker, B. (2002). “Second.”")
            + entry("Evans, E. (2020). “Fifth.”")
            + entry("Currie, C. (1999). “Third.”")
            + entry("Diller, D. (2016). “Fourth.”"))
    report = audit(make_parts(body), page_layout=None)

    (found,) = [i for i in report.issues if i.code == "order"]
    assert found.message == ('"Evans" is out of alphabetical order — '
                             'it files after "Diller"')


def test_an_entry_that_belongs_FIRST_is_told_what_it_belongs_before():
    """`j` is 0 there, so `order[j - 1]` would read the LAST entry and
    the message would send a reader to the wrong end of the list."""
    def entry(text: str) -> str:
        return para(run(text + " "), irun("J"), run(", 1(1): 1-2."))

    body = (para(run("Cited: (Anders 2001), (Baker 2002) and (Currie 1999)."))
            + para(run("References"))
            + entry("Baker, B. (2002). “Second.”")
            + entry("Currie, C. (1999). “Third.”")
            + entry("Anders, A. (2001). “First.”"))
    report = audit(make_parts(body), page_layout=None)

    (found,) = [i for i in report.issues if i.code == "order"]
    assert found.message == ('"Anders" is out of alphabetical order — '
                             'it files before "Baker"')


def test_the_order_finding_points_at_the_paragraph_it_is_about():
    def entry(text: str) -> str:
        return para(run(text + " "), irun("J"), run(", 1(1): 1-2."))

    body = (para(run("Cited: (Anders 2001) and (Baker 2002)."))
            + para(run("References"))
            + entry("Baker, B. (2002). “Second.”")
            + entry("Anders, A. (2001). “First.”"))
    report = audit(make_parts(body), page_layout=None)

    (found,) = [i for i in report.issues if i.code == "order"]
    assert found.where == "¶4"
    assert found.snippet.startswith("Anders, A. (2001).")



# --- a year-labelled COLUMN HEADER is not a citation (BACKLOG S4) --------

def _cells(*texts: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc>{para(run(t))}</w:tc>"
                              for t in texts) + "</w:tr>"


def _with_table(*rows_: str) -> dict[str, bytes]:
    """`body_paragraphs` with one table dropped in before the list."""
    head, _, rest = body_paragraphs().partition(
        para(run("References")))
    return make_parts(head + "<w:tbl>" + "".join(rows_) + "</w:tbl>"
                      + para(run("References")) + rest)


def test_a_year_labelled_column_HEADER_is_not_a_missing_citation():
    """`Base 1990` is Table A4's column head. A cell whose whole content
    is <Capitalised word> <four digits> is exactly the shape a narrative
    citation takes, which the scanner has to accept — so before this the
    audit reported two "cited but not in the reference list" findings per
    paper, cleared by adding "Base" and "Max" to a per-paper ignore list,
    which is where a real miss goes to hide."""
    report = audit(_with_table(_cells("Country", "Base 1990", "Base 2000"),
                               _cells("Poland", "54.1", "57.3")))

    assert "Base" not in str(report.cited), report.cited
    assert not [i for i in report.issues
                if i.code == "missing-ref" and "Base" in i.snippet], \
        [i.snippet for i in report.issues if i.code == "missing-ref"]


def test_a_bare_citation_in_a_BODY_row_is_still_found():
    """The suppression is the header row only. A table of studies lists
    its sources in the body, one per cell, and those are real citations
    the audit must still cross-check — narrowing to the first row is
    what keeps this working."""
    report = audit(_with_table(_cells("Study", "Estimate"),
                               _cells("Kowalski 2021", "0.4")))

    # A surname the surrounding prose does NOT carry. The first version
    # of this test used one that did, so `report.cited` held it whatever
    # the table did, and a mutation that swallowed the whole document
    # into the header span survived it (2026-08-24).
    assert any("kowalski" in k for k in report.cited), report.cited


def test_a_citation_inside_a_header_SENTENCE_is_still_found():
    """Only the whole-paragraph FALLBACK is suppressed. A header cell
    carrying a real citation in prose is found the ordinary way, so the
    fix cannot hide one."""
    report = audit(_with_table(
        _cells("Source", "Rates as reported by Kowalski et al. (2021)"),
        _cells("Poland", "54.1")))

    assert any("kowalski" in k for k in report.cited), report.cited


def test_a_NESTED_table_gets_its_own_header_row():
    """A non-greedy `<w:tbl>...</w:tbl>` closes on the INNER end tag, so
    a whole-table match reads the rest of the outer table as body and
    the outer header stops being one. Walked from each opening tag to
    the next row instead."""
    from docxkit.refstyle import _header_rows

    doc = ("<w:body><w:tbl><w:tr><w:tc>outer head</w:tc></w:tr>"
           "<w:tr><w:tc><w:tbl><w:tr><w:tc>inner head</w:tc></w:tr>"
           "</w:tbl></w:tc></w:tr></w:tbl></w:body>")

    spans = _header_rows(doc)

    assert len(spans) == 2, "one header per table, the nested one included"
    assert "outer head" in doc[spans[0][0]:spans[0][1]]
    assert "inner head" in doc[spans[1][0]:spans[1][1]]


def test_table_PROPERTIES_do_not_open_a_table():
    """`<w:tblPr>` starts with the same six characters as `<w:tbl>`; an
    unguarded pattern opens a table at every table's properties and the
    first row it then finds is the wrong one."""
    from docxkit.refstyle import _header_rows

    doc = ("<w:tbl><w:tblPr><w:tblW w:w=\"5000\"/></w:tblPr>"
           "<w:tr><w:tc>head</w:tc></w:tr></w:tbl>")

    (span,) = _header_rows(doc)

    assert "head" in doc[span[0]:span[1]]



def test_a_table_with_NO_ROWS_OF_ITS_OWN_borrows_the_next_one_harmlessly():
    """Worth pinning because it is not what the code looks like it does.

    The row is searched for from the table's opening tag to the END of
    the document, not within that table, so an empty `<w:tbl>` finds the
    NEXT table's first row and records it as its own header. The spans
    then coincide, and membership is a union of spans, so nothing
    downstream can tell — but a reader of the loop cannot see that, and
    the `if tr is None: continue` beside it is therefore reachable only
    when no row follows anywhere, which is why `continue` and `break`
    are equivalent there rather than untested.

    Bounding the search to the table would need a whole-table match, and
    a non-greedy one closes on a NESTED table's end tag — the failure
    the walk-forward shape exists to avoid."""
    from docxkit.refstyle import _header_rows

    doc = ("<w:body><w:tbl><w:tblPr/></w:tbl>"
           "<w:tbl><w:tr><w:tc>real head</w:tc></w:tr></w:tbl></w:body>")

    spans = _header_rows(doc)

    assert len(spans) == 2 and spans[0] == spans[1], spans
    assert "real head" in doc[spans[0][0]:spans[0][1]]


def test_a_row_that_NEVER_CLOSES_still_bounds_a_header():
    """`doc.find` answers -1, and the span then has to be SOMETHING.
    It runs to the end of the document, which is the fail-safe
    direction: this span decides where a bare author-year pair is a
    column label rather than a citation, so an empty span invents
    citations out of table cells while an over-long one only declines to
    find some — and the audit's whole complaint about column heads is
    false positives.

    Eleven survivors sat on that `-1`, every one of them turning the
    span into `(start, -1)`, which contains nothing at all."""
    from docxkit.refstyle import _header_rows

    doc = "<w:body><w:tbl><w:tr><w:tc>Base 1990</w:tc></w:body>"

    (span,) = _header_rows(doc)

    assert span[1] == len(doc), "an unterminated row bounds at the end"
    assert span[0] < span[1], "and the span is not empty or inverted"
