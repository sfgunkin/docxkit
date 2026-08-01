"""Citation detection, reference parsing and the link XML."""
from __future__ import annotations

import pytest

from docxkit.citations import (
    anchor_names,
    bookmark,
    find_citations,
    hyperlink_field,
    key_for,
    parse_reference,
    references,
)


def _found(text):
    return [(c.authors, c.year, c.narrative) for c in find_citations(text)]


def test_parenthetical_and_narrative_are_both_found():
    """A paper mixes the two forms, often in one paragraph."""
    text = ("Older workers value flexibility (Maestas et al. 2023). "
            "Acemoglu and Restrepo (2022) disagree.")
    assert _found(text) == [("Maestas et al.", "2023", False),
                            ("Acemoglu and Restrepo", "2022", True)]


@pytest.mark.parametrize("text", [
    "(Smith 2020)",
    "(Smith and Jones 2020)",
    "(Smith, Jones and Brown 2020)",
    "(Smith, Jones, and Brown 2020)",     # Oxford comma
    "(Smith & Jones 2020)",
    "(Smith et al. 2020)",
    "(Smith et al 2020)",                 # no final period
])
def test_author_list_forms(text):
    assert len(find_citations(text)) == 1


def test_accented_and_extended_latin_surnames():
    """These papers cite Mühlbach; a plain [A-Z] class misses it."""
    assert _found("(Mühlbach 2022)") == [("Mühlbach", "2022", False)]
    assert find_citations("Šimek (2019) reports")[0].surname == "Šimek"


def test_year_suffixes_are_kept():
    assert find_citations("(Smith 2020a)")[0].year == "2020a"


def test_a_narrative_inside_a_parenthetical_is_reported_once():
    text = "(see Maestas et al. (2023))"
    assert len(find_citations(text)) == 1


def test_a_semicolon_list_yields_each_work():
    """'(Bernheim and Rangel 2009; Chetty 2015)' — a whole-group pattern
    found neither, and the LE audit read both entries as uncited."""
    assert _found("(Bernheim and Rangel 2009; Chetty 2015)") == [
        ("Bernheim and Rangel", "2009", False),
        ("Chetty", "2015", False)]


def test_a_comma_list_yields_each_work():
    """'(Cameron et al. 2008, Roodman et al. 2019)' — LE fn7."""
    assert _found("(Cameron et al. 2008, Roodman et al. 2019)") == [
        ("Cameron et al.", "2008", False),
        ("Roodman et al.", "2019", False)]


def test_a_prefixed_aside_is_still_a_citation():
    """'(e.g., Cahill et al. 2015)' — the lowercase prefix is skipped."""
    assert _found("(e.g., Cahill et al. 2015)") == [
        ("Cahill et al.", "2015", False)]
    assert _found("(see also Chetty 2015)") == [("Chetty", "2015", False)]


def test_a_page_suffix_does_not_hide_the_citation():
    assert _found("(Smith 2020, p. 45)") == [("Smith", "2020", False)]
    assert _found("Maestas et al. (2023, p. 45) estimate") == [
        ("Maestas et al.", "2023", True)]


def test_a_year_mid_phrase_does_not_cite():
    """The year must close its segment: '(in Almaty 2005 the reform...)'
    is prose, not a citation."""
    assert find_citations("(established in Almaty 2005 by decree)") == []


def test_prefix_particle_surnames():
    """'(Apicella and De Giorgi 2024)' — 'De Giorgi' is one surname, and
    the citation files under Apicella (LE le15 ¶28)."""
    cites = find_citations("(Apicella and De Giorgi 2024)")
    assert [c.surname for c in cites] == ["Apicella"]
    assert find_citations("Van Reenen (2012) shows")[0].surname == "Van Reenen"


def test_a_lowercase_particle_can_lead_a_joined_surname():
    """'(Picchio and van Ours 2013)' — the join must accept 'van Ours',
    or the citation is captured as just 'Ours 2013' (API10 ¶54). But
    'of' must not lead: 'the work of Smith (2020)' files under Smith."""
    cites = find_citations("(Picchio and van Ours 2013)")
    assert [(c.surname, c.authors) for c in cites] == [
        ("Picchio", "Picchio and van Ours")]
    assert find_citations("the work of Smith (2020)")[0].surname == "Smith"


def test_a_lowercase_join_carries_the_institution():
    """'Bank of England (2019)' is one author; plain adjacency is not
    joined — 'As Smith (2020)' must still file under Smith."""
    assert find_citations("Bank of England (2019) warns")[0].surname == \
        "Bank of England"
    assert find_citations("As Smith (2020) shows")[0].surname == "Smith"


def test_surname_is_the_first_author():
    for text, want in [("(Smith and Jones 2020)", "Smith"),
                       ("(Smith et al. 2020)", "Smith"),
                       ("Smith, Jones, and Brown (2020)", "Smith")]:
        assert find_citations(text)[0].surname == want


def test_citations_are_returned_in_document_order():
    text = "Alpha (2001) then (Beta 2002) then Gamma (2003)."
    assert [c.year for c in find_citations(text)] == ["2001", "2002", "2003"]


def test_prose_without_citations_finds_none():
    assert find_citations("The index rose in 2024 by 0.18 points.") == []


def test_key_folds_case_and_punctuation():
    """'Mühlbach', 'Muhlbach,' and 'MÜHLBACH' must reach one anchor."""
    assert key_for("Maestas", "2023") == "maestas_2023"
    assert key_for("O’Neill", "2020") == key_for("O'Neill", "2020")
    assert key_for("van der Berg", "2019") == "vanderberg_2019"


def test_anchor_names_follow_the_house_pairing():
    cite, ref = anchor_names("maestas_2023")
    assert (cite, ref) == ("cite_maestas_2023", "ref_maestas_2023")


# ----------------------------------------------------------- references ---

def test_reference_entry_parses_to_surname_and_year():
    ref = parse_reference(
        "Maestas, Nicole, Kathleen J. Mullen, and David Powell. 2023. "
        "“The Effect of Population Aging.” AEJ: Macro 15 (2): 306–32.")
    assert ref is not None
    assert (ref.surname, ref.year) == ("Maestas", "2023")
    assert ref.key == "maestas_2023"


def test_institutional_entry_without_a_comma():
    """'Eurofound. 2021.' has no comma before the year."""
    ref = parse_reference("Eurofound. 2021. Working conditions report.")
    assert ref is not None
    assert ref.surname == "Eurofound"


def test_zotero_field_preamble_is_stripped():
    """Zotero leaves this in the first entry's text when re-run in Word."""
    raw = ('ADDIN ZOTERO_BIBL {"uncited":[],"custom":[]} CSL_BIBLIOGRAPHY '
           "Acemoglu, Daron. 2022. “Tasks and technologies.” Econometrica.")
    ref = parse_reference(raw)
    assert ref is not None
    assert (ref.surname, ref.year) == ("Acemoglu", "2022")


def test_an_entry_with_no_year_is_not_a_reference():
    assert parse_reference("A heading, not a reference entry") is None


def test_reference_and_citation_keys_meet():
    """The whole point: the in-text key must equal the entry's key."""
    cited = find_citations("as shown by Maestas et al. (2023)")[0]
    entry = parse_reference("Maestas, Nicole, and others. 2023. Title.")
    assert entry is not None
    assert cited.key == entry.key


# ----------------------------------------------------------------- XML ---

def test_hyperlink_field_is_a_field_not_an_element():
    """Word writes cross-references as fields; mixing the two forms makes
    the back-link audit fail."""
    xml = hyperlink_field("ref_maestas_2023", "Maestas et al. (2023)")
    assert 'HYPERLINK \\l "ref_maestas_2023" \\h' in xml
    assert xml.count('w:fldCharType="begin"') == 1
    assert xml.count('w:fldCharType="end"') == 1
    assert "Maestas et al. (2023)" in xml
    assert 'w:val="Hyperlink"' in xml


def test_hyperlink_field_escapes_its_label():
    xml = hyperlink_field("ref_x", "Smith & Jones <2020>")
    assert "&amp;" in xml and "&lt;" in xml


def test_bookmark_wraps_and_balances():
    xml = bookmark("cite_maestas_2023", 42, "<w:r><w:t>text</w:t></w:r>")
    assert xml.startswith('<w:bookmarkStart w:id="42" '
                          'w:name="cite_maestas_2023"/>')
    assert xml.endswith('<w:bookmarkEnd w:id="42"/>')
    assert xml.count("bookmarkStart") == xml.count("bookmarkEnd")


def test_zero_length_bookmark_is_a_valid_marker():
    xml = bookmark("ref_x", 7)
    assert 'w:id="7"' in xml
    assert "bookmarkStart" in xml and "bookmarkEnd" in xml


# --------------------------------------------------- the reference SECTION ---

BODY = [
    "Introduction",
    "Older workers value flexibility (Maestas et al. 2023).",
    "The index rose to 0.35 in 2024, up from 0.17 (Aksoy 2026).",
    "References",
    "Aksoy, Cevat. 2026. “Working from home around the world.” JEP.",
    "Maestas, Nicole, and David Powell. 2023. “Population aging.” AEJ.",
    "———. 2021. “An earlier paper by the same author.” JOLE.",
    "Figure 1. Average AFI by country",
    "Smith, John. 1999. “Should not be picked up — after the figures.”",
]


def test_references_are_read_from_the_section_only():
    """Body prose containing '(2023).' parses as an entry; scanning the
    whole document found 63 in a paper with 28."""
    keys = [r.key for r in references(BODY)]
    assert keys == ["aksoy_2026", "maestas_2023", "maestas_2021"]


def test_a_repeated_author_entry_inherits_the_name():
    """'———. 2021.' stands in for the author above; without this it files
    under a row of dashes and reads as never cited."""
    repeated = next(r for r in references(BODY) if r.year == "2021")
    assert repeated.surname == "Maestas"


def test_a_repeated_author_entry_without_a_space_still_inherits():
    """API10 writes '________.(2024).' — no space after the period; the
    entry filed under a row of underscores and read as never cited."""
    doc = ["References",
           "World Bank Group. (2022). Charting a Course. Washington, DC.",
           "________.(2024). Women, Business and the Law. Washington, DC."]
    assert [r.surname for r in references(doc)] == [
        "World Bank Group", "World Bank Group"]


def test_captions_below_the_references_end_the_list():
    assert all(r.surname != "Smith" for r in references(BODY))


def test_a_stop_heading_ends_the_list():
    doc = ["References", "Aksoy, Cevat. 2026. Title.", "Appendix",
           "Brown, A. 2020. Not a reference."]
    assert [r.surname for r in references(doc)] == ["Aksoy"]


def test_a_document_with_no_reference_heading_yields_nothing():
    assert references(["Introduction", "Body text (Smith 2020)."]) == []


def test_a_russian_reference_heading_is_recognised():
    doc = ["Литература", "Иванов, И. 2020. Название."]
    assert len(references(doc)) == 1


def test_the_body_citations_and_the_entries_agree():
    """End to end on the little document above."""
    cited = {c.key for p in BODY[:3] for c in find_citations(p)}
    listed = {r.key for r in references(BODY)}
    assert cited <= listed, f"cited but not listed: {cited - listed}"
