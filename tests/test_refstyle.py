"""Reference-format audit: the house author-date style, checked."""
from __future__ import annotations

import pytest
from conftest import NS, make_parts, note, notes, para, run

from docxkit.refstyle import (
    CHICAGO,
    HOUSE,
    audit,
    check_entry,
    check_prose,
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
    assert report.entries == 3
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
    assert report.cited == 3     # acemoglu, maestas, angrist — no echoes


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
    assert '"Aksoy" is filed after "Zebra"' in order[0].message


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
    every other, that is worse than no location at all."""
    report = audit(make_parts(_entry_paragraphs()))

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

    assert report.entries == 0
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
