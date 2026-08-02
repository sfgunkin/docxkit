"""Citation detection, reference parsing and the link XML."""
from __future__ import annotations

import re

import pytest

from docxkit.citations import (
    anchor_names,
    audit_links,
    bookmark,
    check_citations,
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


# ------------------------------------------------------ the link audit ---

hfield = hyperlink_field


def _linked_cite(key: str, label: str) -> str:
    """An in-text citation on the papers' convention: <key>txt bookmark
    wrapping a field link to the <key> entry bookmark."""
    return bookmark(f"{key}txt", 10, hfield(key, label))


def _entry(key: str, text: str) -> str:
    """A reference entry: <key> bookmark + back-link to <key>txt."""
    return bookmark(key, 20, hfield(f"{key}txt", text))


def _codes_of(issues):
    return {i.split(":", 1)[0] for i in issues}


def make_doc(*paras: str) -> dict[str, bytes]:
    from conftest import make_parts
    filler = "".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                     for i in range(5))
    return make_parts(filler + "".join(paras))


def P(inner: str) -> str:
    return f"<w:p>{inner}</w:p>"


def R(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def test_internal_links_reads_both_forms():
    """The builds write fldChar HYPERLINK fields; Word converts them to
    w:hyperlink elements on save. An audit reading one form misses half
    the links depending on who saved last."""
    from docxkit._xml import internal_links
    xml = (P(hfield("Smith2020", "Smith 2020"))
           + P('<w:hyperlink w:anchor="Jones2021"><w:r><w:t>Jones '
               "2021</w:t></w:r></w:hyperlink>"))
    assert internal_links(xml) == [("Jones2021", "Jones 2021"),
                                   ("Smith2020", "Smith 2020")] or \
           internal_links(xml) == [("Smith2020", "Smith 2020"),
                                   ("Jones2021", "Jones 2021")]


def test_a_fully_linked_document_audits_clean():
    parts = make_doc(
        P(R("Robots displace workers (") + _linked_cite("Smith2020",
            "Smith 2020") + R(").")),
        P(R("References")),
        P(_entry("Smith2020", "Smith, J. (2020). Robots. JPE.")))
    issues, stats = audit_links(parts)
    assert issues == []
    assert stats["ref_bookmarks"] == 1 and stats["cite_bookmarks"] == 1


def test_a_link_to_words_own_heading_bookmark_is_not_broken():
    """THE regression: the ported audit excluded underscore names from
    its index and reported links to them as BROKEN — LE le15 shipped an
    audit round with nine '_Heading' false positives."""
    parts = make_doc(
        P(bookmark("_Heading1", 3) + R("Introduction")),
        P(R("See the ")
          + '<w:hyperlink w:anchor="_Heading1"><w:r><w:t>intro'
            "</w:t></w:r></w:hyperlink>" + R(" above.")))
    issues, _ = audit_links(parts)
    assert not any(i.startswith("BROKEN LINK") for i in issues)
    # and the heading bookmark is not dragged into the citation checks
    assert not any(i.startswith("REF WITHOUT CITE") for i in issues)


def test_a_link_to_a_missing_bookmark_is_broken():
    parts = make_doc(
        P(R("See ") + hfield("Nowhere2020", "Nowhere 2020") + R(".")))
    issues, stats = audit_links(parts)
    assert any(i.startswith("BROKEN LINK") and "Nowhere2020" in i
               for i in issues)
    assert stats["broken"] == 1


def test_an_entry_nobody_links_to_is_an_orphan():
    parts = make_doc(
        P(R("Prose without the citation.")),
        P(R("References")),
        P(bookmark("Ghost2019", 30) + R("Ghost, A. (2019). Unseen.")))
    issues, _ = audit_links(parts)
    assert any(i.startswith("ORPHAN REF") and "Ghost2019" in i
               for i in issues)
    assert any(i.startswith("REF WITHOUT CITE") for i in issues)


def test_a_cite_mark_without_entry_or_backlink_reports_both():
    parts = make_doc(
        P(bookmark("Lost2020txt", 40)
          + hfield("Lost2020", "Lost 2020")))
    issues, _ = audit_links(parts)
    codes = _codes_of(issues)
    assert "NO BACK-LINK" in codes       # nothing links to Lost2020txt
    assert "MISSING REF" in codes        # Lost2020 bookmark absent
    assert "BROKEN LINK" in codes        # the forward link dangles too


def test_unlinked_citation_text_is_reported_on_the_shared_grammar():
    parts = make_doc(
        P(R("Ranges shift with age (Mühlbach 2022).")),
        P(R("Shown in Table (2020) format.")),   # IGNORED_LEADS
        P(R("References")))
    issues, _ = audit_links(parts)
    unlinked = [i for i in issues if i.startswith("UNLINKED")]
    assert len(unlinked) == 1
    assert "Mühlbach 2022" in unlinked[0]


def test_a_footnote_link_keeps_the_entry_cited():
    from conftest import NS, make_parts, para, run
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("References"))
            + P(_entry("Card1999", "Card, D. (1999). Education.")))
    foot = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:footnotes {NS}><w:footnote w:id="2">'
            f"{para(run('See '), hfield('Card1999', 'Card 1999'))}"
            f"</w:footnote></w:footnotes>")
    issues, _ = audit_links(make_parts(body, footnotes=foot))
    assert not any(i.startswith("ORPHAN REF") for i in issues)
    assert not any(i.startswith("REF WITHOUT CITE") for i in issues)


def test_check_citations_prints_and_counts(tmp_path, capsys):
    from conftest import write
    parts = make_doc(
        P(R("See ") + hfield("Nowhere2020", "Nowhere 2020") + R(".")))
    path = write(tmp_path / "audit.docx", parts)
    n = check_citations(path)
    out = capsys.readouterr().out
    assert n == 1
    assert "BROKEN LINK" in out and "FOUND 1 ISSUE(S)" in out


# --------------------------------------------------------- link_in_para ---

def test_link_in_para_wraps_the_span_in_an_element_link():
    from docxkit._xml import internal_links
    from docxkit.citations import link_in_para
    p = P(R("as shown by UN 2024 and others."))
    out = link_in_para(p, "UN 2024", "UN2024")
    from docxkit._xml import visible_text
    assert visible_text(out) == "as shown by UN 2024 and others."
    assert internal_links(out) == [("UN2024", "UN 2024")]
    assert 'w:val="Hyperlink"' in out
    assert "as shown by " in out and " and others." in out


def test_link_in_para_asserts_its_anchor():
    import pytest as _pytest

    from docxkit.citations import link_in_para
    from docxkit.errors import AnchorError
    with _pytest.raises(AnchorError):
        link_in_para(P(R("no citation here")), "UN 2024", "UN2024")


def test_link_in_para_wraps_a_fragmented_span_whole():
    """Word splits entry heads at rsid boundaries (LI7's Hudiyana entry)
    — the wrap covers every fragment, splits the edge runs, and carries
    anything between runs (a bookmark) along inside the link."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import link_in_para
    split = P(R("as shown by UN ") + bookmark("mid", 77)
              + R("2024 and others."))
    out = link_in_para(split, "UN 2024", "UN2024")
    assert visible_text(out) == "as shown by UN 2024 and others."
    assert internal_links(out) == [("UN2024", "UN 2024")]
    assert "as shown by " in out and " and others." in out
    hl = out[out.index("<w:hyperlink"):out.index("</w:hyperlink>")]
    assert 'w:name="mid"' in hl          # the bookmark rides inside


# ---------------------------------------------- link/bookmark repair ---

def test_next_bookmark_id_spans_all_parts():
    from docxkit.citations import next_bookmark_id
    doc = P(bookmark("a", 7) + R("body"))
    foot = P(bookmark("b", 91) + R("note"))
    assert next_bookmark_id(doc, foot) == 92
    assert next_bookmark_id("") == 1


def test_marker_bookmark_travels_inside_the_paragraph():
    """Body-level markers between paragraphs do NOT travel with a
    paragraph move — reordering API10's reference list stranded 13 of
    them one entry off. The marker goes INSIDE the paragraph head."""
    from docxkit.citations import marker_bookmark
    xml = P(R("Smith, J. (2020). A title.")) + P(R("Other entry."))
    out = marker_bookmark(xml, "Smith, J.", "Smith2020", 5)
    pm = re.search(r"<w:p>.*?</w:p>", out, re.DOTALL)
    assert pm is not None
    para = pm.group(0)
    assert '<w:bookmarkStart w:id="5" w:name="Smith2020"/>' in para
    from docxkit.errors import AnchorError
    with pytest.raises(AnchorError):
        marker_bookmark(xml, "no such entry", "X", 6)


def test_wrap_link_in_bookmark_handles_both_forms():
    from docxkit._xml import internal_links
    from docxkit.citations import wrap_link_in_bookmark
    element = P(R("see ") + '<w:hyperlink w:anchor="Smith2020">'
                + R("Smith 2020") + "</w:hyperlink>")
    out = wrap_link_in_bookmark(element, "Smith2020", "Smith2020txt", 9)
    assert out.index('w:name="Smith2020txt"') < out.index("<w:hyperlink")
    field = P(R("see ") + hfield("Jones2021", "Jones 2021"))
    out = wrap_link_in_bookmark(field, "Jones2021", "Jones2021txt", 10)
    assert 'w:name="Jones2021txt"' in out
    assert internal_links(out) == [("Jones2021", "Jones 2021")]
    from docxkit.errors import AnchorError
    with pytest.raises(AnchorError):
        wrap_link_in_bookmark(P(R("no link")), "Nowhere", "X", 11)


def test_delete_bookmark_removes_the_pair():
    from docxkit.citations import delete_bookmark
    xml = P(bookmark("gone", 3) + R("text"))
    out = delete_bookmark(xml, "gone")
    assert "bookmarkStart" not in out and "bookmarkEnd" not in out
    assert "text" in out
    from docxkit.errors import AnchorError
    with pytest.raises(AnchorError):
        delete_bookmark(out, "gone")


def test_audit_distinguishes_body_level_from_footnote_bookmarks():
    """The first audit round printed body-level definitions as "(fn)"
    and the API repair went hunting in footnotes.xml for bookmarks that
    were never there."""
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + bookmark("Ghost2019", 30)          # between paragraphs
            + P(R("Ghost, A. (2019). Unseen.")))
    parts = {"word/document.xml":
             ("<w:document><w:body>" + body + "</w:body></w:document>"
              ).encode("utf-8")}
    issues, _ = audit_links(parts)
    orphan = next(i for i in issues if i.startswith("ORPHAN REF"))
    assert "(body)" in orphan and "(fn)" not in orphan


def test_a_dotted_acronym_lead_keeps_its_full_name():
    """'U.S. Census Bureau. (2023)' filed under "U" — the first-period
    split read the acronym's dot as a sentence end (LI7 fn6/¶184), which
    broke the order check and the cited/listed pairing."""
    ref = parse_reference('U.S. Census Bureau. (2023). "Age Heaping in '
                          'the 2020 Census of Population."')
    assert ref is not None
    assert ref.surname == "U.S. Census Bureau"


def test_a_nested_link_with_a_different_target_is_doubled():
    """API10 P30: the Finsel field never ends, so the Wöhrmann field
    renders inside it — ONE link, to Finsel. Same-target nesting (form
    churn caught mid-flight) stays quiet."""
    fld = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           r'<w:r><w:instrText>HYPERLINK \l "{a}"</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    nested = P(fld.format(a="Finsel2023") + R("Finsel et al. 2023; ")
               + fld.format(a="Wohrmann2018") + R("Wöhrmann et al. 2018")
               + end + end)
    parts = {"word/document.xml": (
        "<w:document><w:body>" + nested + "</w:body></w:document>"
        ).encode("utf-8")}
    issues, _ = audit_links(parts)
    doubled = [i for i in issues if i.startswith("DOUBLED LINK")]
    assert len(doubled) == 1 and "Wohrmann2018" in doubled[0]

    hybrid = P(fld.format(a="Nardo2008")
               + '<w:hyperlink w:anchor="Nardo2008">' + R("Nardo 2008")
               + "</w:hyperlink>" + end)
    parts = {"word/document.xml": (
        "<w:document><w:body>" + hybrid + "</w:body></w:document>"
        ).encode("utf-8")}
    issues, _ = audit_links(parts)
    assert not any(i.startswith("DOUBLED LINK") for i in issues)


def test_a_marker_stranded_at_the_wrong_entry_reports():
    """Reordering entry paragraphs strands body-level markers one entry
    off (13 of them on API10). Only confident mismatches report."""
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Cited (Buys 2012) and (Burnes 2019)."))
            + P(R("References"))
            + P(R("Burnes, D. (2019). Interventions. J, 1(1): 1-2."))
            + bookmark("Buys2012", 41)            # stranded: Buys moved
            + P(R("Buys, L. (2012). Active ageing. J, 1(1): 3-4.")))
    parts = {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>"
        ).encode("utf-8")}
    issues, _ = audit_links(parts)
    mis = [i for i in issues if i.startswith("MISPLACED MARKER")]
    assert not mis            # marker precedes the RIGHT entry: quiet
    body = body.replace('w:name="Buys2012"', 'w:name="stranded_x"')
    body = body.replace("Burnes, D. (2019). Interventions",
                        '</w:t></w:r><w:bookmarkStart w:id="42" '
                        'w:name="Buys2012"/><w:bookmarkEnd w:id="42"/>'
                        '<w:r><w:t>Burnes, D. (2019). Interventions')
    parts = {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>"
        ).encode("utf-8")}
    issues, _ = audit_links(parts)
    mis = [i for i in issues if i.startswith("MISPLACED MARKER")]
    assert len(mis) == 1 and "'Buys2012'" in mis[0] and "Burnes" in mis[0]


# ------------------------------------------------------------ link_all ---

def test_link_all_builds_the_full_apparatus_and_is_idempotent():
    from docxkit.citations import link_all
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Robots displace workers (Maestas et al. 2023)."))
            + P(R("Aksoy (2026) reports; see also (Maestas et al. "
                  "2023)."))
            + P(R("References"))
            + P(R("Aksoy, C. (2026). Working from home. JEP, 1(1): 1-2."))
            + P(R("Maestas, N., Mullen, K., and D. Powell. (2023). "
                  "The effect of population aging. AEJ, 15(2): 306-32.")))
    parts = {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>"
        ).encode("utf-8")}
    report = link_all(parts)
    assert len(report.linked) == 2 and len(report.backlinked) == 2
    issues, stats = audit_links(parts)
    assert issues == [], issues
    assert stats["links"] == 4          # 2 in-text + 2 back-links
    again = link_all(parts)
    assert not again.linked and not again.backlinked
    assert len(again.already) == 2


def test_link_all_reuses_an_entrys_existing_bookmark_name():
    from docxkit.citations import link_all
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("As shown (Smith 2020)."))
            + P(R("References"))
            + P(bookmark("SmithJ2020", 60)
                + R("Smith, J. (2020). A title. J, 1(1): 1-2.")))
    parts = {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>"
        ).encode("utf-8")}
    report = link_all(parts)
    assert report.linked == ["SmithJ2020 @ ¶6"]
    issues, _ = audit_links(parts)
    assert issues == []


def test_link_all_reports_rather_than_guesses():
    from docxkit.citations import link_all
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("An orphan citation (Ghost 2019)."))
            + P(R("References"))
            + P(R("Aksoy, C. (2026). Working from home. JEP.")))
    parts = {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>"
        ).encode("utf-8")}
    report = link_all(parts)
    assert any("Ghost 2019" in u for u in report.unmatched)


def test_a_lead_particle_needs_a_word_boundary():
    """'...whiLE Yang's (2018)' — the lowercase lead matched mid-word
    and produced surname 'le Yang' on the Missing Market dry run."""
    assert find_citations("worthwhile Yang (2018) results")[0].surname \
        == "Yang"
