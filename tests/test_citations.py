"""Citation detection, reference parsing and the link XML."""
from __future__ import annotations

import itertools
import re

import pytest

from docxkit._xml import PARA_RE, visible_text
from docxkit.citations import (
    _BOOKMARK_NAME_RE,
    Reference,
    anchor_names,
    audit_links,
    bookmark,
    check_citations,
    find_citations,
    hyperlink_field,
    key_for,
    parse_reference,
    references,
    wrap_link_in_bookmark,
)
from docxkit.errors import AnchorError


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


def test_a_citation_after_an_equation_is_wrapped_at_the_right_place():
    """Offsets come from visible_text, which counts OMML; the run walk sees
    `w:r` only, and maths lives in `m:r`. Every span after an equation was
    short by its glyph count — on a real paragraph the link wrapped the closing
    full stop instead of the citation, and rendered as a blue «).»."""
    from docxkit._xml import visible_text
    from docxkit.citations import wrap_visible_span

    math = ('<m:oMath><m:r><m:t>γ∈{0,25}</m:t></m:r></m:oMath>')
    para = ("<w:p><w:r><w:t>Weights </w:t></w:r>" + math
            + "<w:r><w:t> vary (Smith 2020).</w:t></w:r></w:p>")
    text = visible_text(para)
    at = text.index("Smith 2020")
    out = wrap_visible_span(para, at, at + len("Smith 2020"), "Smith2020")
    inner = re.search(r"<w:hyperlink[^>]*>(.*?)</w:hyperlink>", out, re.DOTALL)
    assert inner is not None
    assert visible_text(inner.group(1)) == "Smith 2020"


def test_locate_counts_the_maths_too():
    """The other half of the same bug, and the half that shipped. Fixing
    `wrap_visible_span` left `edit._locate` joining the `w:r` runs alone, so it
    returned offsets into a SHORTER string than the one the wrapper consumes.
    Two definitions of "visible" in one call path is one too many."""
    from docxkit._xml import visible_text
    from docxkit.edit import _locate

    math = "<m:oMath><m:r><m:t>αβγ</m:t></m:r></m:oMath>"
    para = ("<w:p><w:r><w:t>where </w:t></w:r>" + math
            + "<w:r><w:t> are weights (Smith 2020).</w:t></w:r></w:p>")
    _runs, _spans, at, end = _locate(para, "Smith 2020")
    assert visible_text(para)[at:end] == "Smith 2020"


def test_link_all_places_a_citation_that_follows_inline_symbols():
    """End to end, on the shape that shipped: a «where y — …, α and β — …»
    gloss carrying five inline symbols, then the citation. The link came out
    four characters early, over «ему (Friedman», and no glyph-identity gate can
    see that — a displaced wrap moves no characters. The audit caught it."""
    from docxkit._xml import visible_text
    from docxkit.citations import link_all

    def sym(g):
        return f"<m:oMath><m:r><m:t>{g}</m:t></m:r></m:oMath>"

    cite = ("<w:p><w:r><w:t>where </w:t></w:r>" + sym("y")
            + "<w:r><w:t> is the index, </w:t></w:r>" + sym("c")
            + "<w:r><w:t> the region, </w:t></w:r>" + sym("α")
            + "<w:r><w:t> and </w:t></w:r>" + sym("β")
            + "<w:r><w:t> the coefficients, </w:t></w:r>" + sym("e")
            + "<w:r><w:t> the residual. Regression to the mean can produce "
              "it (Friedman 1992).</w:t></w:r></w:p>")
    head = "<w:p><w:r><w:t>References</w:t></w:r></w:p>"
    entry = ('<w:p><w:r><w:t>Friedman, M. (1992). "Do Old Fallacies Ever '
             'Die?" Journal of Economic Literature, 30(4): 2129-2132.'
             "</w:t></w:r></w:p>")
    body = ('<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main" xmlns:m="http://schemas.'
            'openxmlformats.org/officeDocument/2006/math"><w:body>'
            + cite + head + entry + "</w:body></w:document>")
    parts = {"word/document.xml": body.encode("utf-8")}
    link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")
    inner = re.search(r"<w:hyperlink[^>]*>(.*?)</w:hyperlink>", out, re.DOTALL)
    assert inner is not None
    assert visible_text(inner.group(1)) == "Friedman 1992"


def test_a_bookmark_whose_entry_was_deleted_reads_as_stale():
    """The author removed an entry in Word. The marker did not go with it —
    Word hoists a paragraph-head bookmark to body level rather than dropping
    it — so the audit went on reporting a work that is not in the document, as
    an UNCITED REFERENCE. Twice I relayed that to the author as a real finding
    before checking whether the entry existed at all."""
    from conftest import make_parts, para, run

    body = (para(run("A claim (Card 1999)."))
            + para(run("References"))
            + '<w:bookmarkStart w:id="9" w:name="Ravallion2012"/>'
              '<w:bookmarkEnd w:id="9"/>'
            + para(run("Card, D. (1999). Education. Amsterdam: Elsevier.")))
    issues, _stats = audit_links(make_parts(body))
    stale = [m for m in issues if m.startswith("STALE BOOKMARK")]
    assert len(stale) == 1
    assert "Ravallion2012" in stale[0]
    assert not any("REF WITHOUT CITE: 'Ravallion2012'" in m for m in issues)


def test_a_live_entry_hoisted_to_body_level_is_not_stale():
    """Word hoists markers whose entry is very much still there — 52 of them in
    DSI — so placement cannot be the test. The year is."""
    from conftest import make_parts, para, run

    body = (para(run("A claim (Card 1999)."))
            + para(run("References"))
            + '<w:bookmarkStart w:id="9" w:name="Card1999"/>'
              '<w:bookmarkEnd w:id="9"/>'
            + para(run("Card, D. (1999). Education. Amsterdam: Elsevier.")))
    issues, _stats = audit_links(make_parts(body))
    assert not any(m.startswith("STALE BOOKMARK") for m in issues)


def test_a_bookmark_name_survives_a_non_latin_surname():
    """A Cyrillic institution gave no Latin stem at all, so its name became the
    bare year «2026» — not key-shaped, so link_all could not recognise its own
    marker next run and minted «2026_2», then «2026_3». The pass advertises
    idempotency and quietly lost it. Accents fold rather than vanish, too:
    «Aczél» was becoming «Aczl»."""
    from docxkit._cite_audit import _KEY_SHAPE_RE
    from docxkit._cite_build import _ascii_stem

    assert _ascii_stem("Aczél") == "Aczel"
    assert _ascii_stem("Mühlbach") == "Muhlbach"
    assert _ascii_stem("Министерство иностранных дел")[:12] == "Ministerstvo"
    assert _ascii_stem("Ұлытау").isascii()
    for surname in ("Министерство", "Ұлытау", "—", "2026", "Ministry 4"):
        stem = _ascii_stem(surname)
        assert stem.isalpha(), surname
        assert _KEY_SHAPE_RE.fullmatch(stem + "2026"), surname
    assert _ascii_stem("———") == "Ref"


def test_a_cyrillic_citation_is_found():
    """A Russian paper cites «(МИД РК 2026)». `\\w` already admitted Cyrillic
    for the REST of a name, so only the initial capital's character class stood
    between the finder and every Cyrillic citation — and the entry it pointed
    at read as an orphan nobody cites. Multi-word institutions are captured
    from their last word, here as everywhere."""
    text = "В мае 2026 года объявлено о создании хаба (МИД РК 2026)."
    assert _found(text) == [("РК", "2026", False)]


@pytest.mark.parametrize("text", [
    "Результаты приведены в таблице 3.",
    "Ориентиры фиксируются (раздел 5.3).",
    "Доказательство дано в Приложении Б.",
    "Перепись 2021 года дала оценку.",
])
def test_russian_structural_parentheticals_are_not_citations(text):
    """What admitting Cyrillic must NOT do: a section or table reference is not
    a citation, and neither is a bare year in running prose."""
    assert _found(text) == []


def test_a_TITLED_stop_heading_ends_the_list():
    """The stop word used to have to be the whole paragraph, so «Приложение А.
    Характеристика показателей» did not end anything. The list ran on into the
    appendix, a prose paragraph citing «(Jensen 1906)» parsed as an entry, and
    the real Jensen entry then read as never cited."""
    ru = ["Литература", "Jensen, J.L.W.V. (1906). Sur les fonctions convexes.",
          "Приложение А. Характеристика и значимость показателей",
          "Индекс вогнут. По неравенству Йенсена (Jensen 1906) он не меньше."]
    assert [r.surname for r in references(ru)] == ["Jensen"]

    en = ["References", "Aksoy, Cevat. 2026. Title.",
          "Appendix B. Robustness checks",
          "Prose that cites (Brown 2020) in passing."]
    assert [r.surname for r in references(en)] == ["Aksoy"]


def test_an_author_named_like_a_stop_word_still_files():
    """The stop test only fires on a paragraph that is not itself an entry, so
    a real author called Tables does not end the list she is listed in."""
    doc = ["References", "Aksoy, Cevat. 2026. Title.",
           "Tables, A.B. (2019). A real surname. J. Odd, 1: 1-2."]
    assert [r.surname for r in references(doc)] == ["Aksoy", "Tables"]


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


def xml_parts(body: str) -> dict[str, bytes]:
    """A one-part package around a body — the audit fixtures' shape."""
    return {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>"
        ).encode("utf-8")}


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


def _links(parts: dict[str, bytes]) -> list[str]:
    """What each link in the body actually WRAPS, in document order.

    A link's target can be right while its span is wrong, and only the
    label shows that.
    """
    from docxkit._xml import internal_links
    return [label for _, label
            in internal_links(parts["word/document.xml"].decode("utf-8"))]


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


def test_an_entry_nobody_links_to_and_nobody_marks_is_ONE_finding():
    """ORPHAN REF and REF WITHOUT CITE were one fact said twice, and the
    redundancy is a theorem: a work nothing links to is not in
    `cited_keys`, so every REF WITHOUT CITE arrived with an ORPHAN REF
    beside it. Measured over five manuscripts, `uncited-only` is 0 every
    time; after a `link_all` run li7 carried 20 such pairs, le14 16 and
    AFI's baseline 5 (2026-08-21).

    The line that survives is the one a reader can act on — a reference
    nobody cites is a decision about the bibliography — and it carries
    what the other one said."""
    parts = make_doc(
        P(R("Prose without the citation.")),
        P(R("References")),
        P(bookmark("Ghost2019", 30) + R("Ghost, A. (2019). Unseen.")))

    issues, _ = audit_links(parts)

    (ghost,) = [i for i in issues if "Ghost2019" in i]
    assert ghost.startswith("REF WITHOUT CITE")
    assert "no in-text hyperlink" in ghost and "Ghost2019txt" in ghost


def test_an_ORPHAN_REF_still_speaks_when_the_work_IS_cited():
    """What is left of it is the case that is NOT the same fact: the
    `<key>txt` marker is in the prose, so the work is cited, and the
    hyperlink to the entry is gone — the reader clicking that citation
    arrives nowhere."""
    parts = make_doc(
        P(bookmark("Ghost2019txt", 40) + R("As Ghost (2019) showed.")),
        P(R("References")),
        P(bookmark("Ghost2019", 30) + R("Ghost, A. (2019). Unseen.")))

    issues, _ = audit_links(parts)

    orphan = next(i for i in issues if i.startswith("ORPHAN REF"))
    assert "the work IS cited" in orphan
    assert "'Ghost2019txt' is at ¶6" in orphan
    assert not [i for i in issues if i.startswith("REF WITHOUT CITE")]


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
    assert unlinked == ['UNLINKED: "Mühlbach 2022" (¶6) — looks like a '
                        "citation but is not hyperlinked"]


def test_the_FIRST_FIVE_paragraphs_are_not_scanned_for_citations():
    """A title page carries "(2024)" and an affiliation carries a year in
    brackets; treating those as unlinked citations put a finding at the
    top of every report, which is where a reader decides whether to keep
    reading. Five is the window, and the sixth paragraph IS scanned."""
    cite = P(R("Ranges shift with age (Mühlbach 2022)."))
    filler = "".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                     for i in range(4))
    quiet = xml_parts(filler + cite + P(R("References")))       # ¶5
    scanned = xml_parts(filler + P(R("One more.")) + cite
                        + P(R("References")))                   # ¶6

    assert not [i for i in audit_links(quiet)[0] if i.startswith("UNLINKED")]
    assert [i for i in audit_links(scanned)[0] if i.startswith("UNLINKED")]


def test_a_citation_whose_LABEL_is_linked_elsewhere_is_not_UNLINKED():
    """The convention links a work's FIRST mention only. A later mention
    in the same words is deliberate, and reporting it turns the audit
    into a list of the house style."""
    parts = make_doc(
        P(_linked_cite("Muhlbach2022", "(Mühlbach 2022)")),
        P(R("Repeated later (Mühlbach 2022) without a link.")),
        P(R("References")),
        P(_entry("Muhlbach2022", "Mühlbach, I. (2022). Ranges.")))

    unlinked = [i for i in audit_links(parts)[0] if i.startswith("UNLINKED")]

    assert unlinked == []


def _own_scheme(entry: str, cite: str, label: str, text: str, *,
                in_text: bool = True,
                marked: bool = True) -> tuple[str, str]:
    """A work under a paper's OWN naming — `ref_x_2018` / `cite_x_2018`.

    `in_text=False` is the mention after a Word round-trip with track
    changes off: the bookmark and its link are gone and the words are
    still there. `marked=False` takes the ENTRY's marker too, leaving
    only its back-link — which still names the mention Word deleted.
    """
    prose = (P(bookmark(cite, 11, hfield(entry, label))) if in_text
             else P(R(f"As {label} shows, the pattern holds.")))
    body = hfield(cite, text)
    return prose, P(bookmark(entry, 21, body) if marked else body)


def test_link_all_creates_the_name_a_BROKEN_BACK_LINK_demands():
    """A Word round-trip with track changes off drops in-text links and
    the bookmarks they carried while every word on the page survives.
    `link_all` then minted `ref_noone_2018txt` beside the entry, reported
    `linked 7`, and left all six back-links broken — the manuscript came
    out worse than it went in (AFI r4 hand-back, 2026-08-21).

    The evidence was in the file the whole time: the entry's back-link
    points at `cite_noone_2018`, a broken link naming the exact anchor
    that has to be created.
    """
    whole = _own_scheme("ref_alba_2015", "cite_alba_2015",
                        "(Alba 2015)", "Alba, R. (2015). Whole.")
    lost_cite = _own_scheme("ref_barr_2018", "cite_barr_2018",
                            "(Barr 2018)", "Barr, S. (2018). Half.",
                            in_text=False)
    lost_both = _own_scheme("ref_cox_2022", "cite_cox_2022",
                            "(Cox 2022)", "Cox, T. (2022). Both.",
                            in_text=False, marked=False)
    parts = make_doc(whole[0], lost_cite[0], lost_both[0],
                     P(R("References")), whole[1], lost_cite[1],
                     lost_both[1])

    from docxkit.citations import link_all
    link_all(parts)

    marks = set(_BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8")))
    # the twin each entry's own back-link asked for, and no orphan beside it
    assert {"cite_barr_2018", "cite_cox_2022"} <= marks
    assert not [n for n in marks if n.endswith("txt")], sorted(marks)
    # …and the entry Word un-marked comes back under the document's rule,
    # not as a minted `Cox2022`
    assert "ref_cox_2022" in marks
    assert not [n for n in marks if n.startswith(("Cox", "Barr"))]
    # every link resolves: that is the finding class this was leaving open
    issues, _ = audit_links(parts)
    assert not [i for i in issues if i.startswith("BROKEN LINK")], issues


def test_a_work_whose_FIRST_mention_lost_its_link_is_still_a_candidate():
    """"Already linked" is a fact about a MENTION, not about a work.

    Word drops links UNEVENLY: on the AFI hand-back it took the FIRST
    Maestas mention and left one twelve pages on, so the work read as
    `already linked`, the first-mention pass skipped it, and the
    bookmark its entry's back-link demands was never written. Measured
    AFTER the lost-link repair landed — five of six came back and this
    one did not (2026-08-21).
    """
    from docxkit.citations import link_all

    parts = make_doc(
        P(R("Maestas et al. (2023) estimate willingness to pay.")),  # plain
        P(R("Twelve pages on, ")
          + hfield("ref_maestas_2023", "Maestas et al. (2023)")
          + R(" again.")),                       # this one Word left alone
        P(R("References")),
        P(bookmark("ref_maestas_2023", 21, hfield(
            "cite_maestas_2023", "Maestas, N. (2023). Wages. A Journal."))))

    report = link_all(parts)

    doc = parts["word/document.xml"].decode("utf-8")
    marks = set(_BOOKMARK_NAME_RE.findall(doc))
    assert "cite_maestas_2023" in marks, report.format()
    assert report.already == [], report.format()
    # the FIRST mention is the one wired, and the later link is untouched
    first = PARA_RE.findall(doc)[5]
    assert "cite_maestas_2023" in first and "willingness to pay" in first


def test_a_paper_with_NO_in_text_bookmarks_is_a_convention_not_a_loss():
    """The guard on the fix above. A document wired `ref_x` / link with
    no in-text bookmark anywhere is fully linked under its own
    convention — nothing DEMANDS a twin — and re-wiring its mentions
    would nest a link inside a link."""
    from docxkit.citations import link_all

    parts = make_doc(
        P(R("A point (") + hfield("ref_kanbur_2007", "Kanbur 2007")
          + R(").")),
        P(R("References")),
        P(bookmark("ref_kanbur_2007", 21, R(
            "Kanbur, R. (2007). Poverty and distribution. Journal."))))

    report = link_all(parts)

    assert report.already == ["ref_kanbur_2007"], report.format()
    assert report.linked == []


def test_an_entry_whose_YEAR_carries_a_letter_finds_its_own_bookmark():
    """A paper citing two works by one author in one year writes 2023a
    and 2023b, and its bookmarks were minted BEFORE the split —
    `ref_maestas_mp_2023` and `ref_maestas_2023`. The fold has to END
    with the work's year, and "refmaestas2023" does not end with
    "2023b", so NEITHER entry matched its own marker and `link_rest`
    skipped five mentions with "entry has no bookmark" — which is false,
    and sends the reader looking for a bookmark that is there (AFI batch
    28, 2026-08-21).
    """
    from docxkit.citations import _entry_names_from_document, link_rest

    first = P(bookmark("ref_maestas_mp_2023", 21, hfield(
        "cite_maestas_mp_2023",
        "Maestas, N. (2023a). Market power. A Journal.")))
    second = P(bookmark("ref_maestas_2023", 22, hfield(
        "cite_maestas_2023", "Maestas, N. (2023b). Something else. B.")))
    parts = make_doc(
        P(_linked_cite("cite_maestas_2023", "Maestas (2023b)")),
        P(R("And again, Maestas (2023b) reports, plainly this time.")),
        P(R("References")), first, second)

    doc = parts["word/document.xml"].decode("utf-8")
    paras = list(PARA_RE.finditer(doc))
    entries = references([visible_text(m.group(0)) for m in paras])
    names = _entry_names_from_document(doc, entries, paras)

    assert names == {"maestas_2023a": "ref_maestas_mp_2023",
                     "maestas_2023b": "ref_maestas_2023"}

    report = link_rest(parts)

    assert not [s for s in report.skipped if "no bookmark" in s], \
        report.skipped
    assert report.linked, "the later mention is linked now"


def _named_entries(parts):
    from docxkit.citations import _entry_names_from_document
    doc = parts["word/document.xml"].decode("utf-8")
    paras = list(PARA_RE.finditer(doc))
    return _entry_names_from_document(
        doc, references([visible_text(m.group(0)) for m in paras]), paras)


def test_a_LETTERED_year_never_takes_a_name_another_entry_MATCHED():
    """Two works by one author in one year is precisely when a wrong
    guess is undetectable, so the relaxed pass yields to a strict match.

    Reachable because a damaged manuscript really does carry the same
    bookmark name twice — that is the coin-flip `_bookmark_names`
    describes — and the bare year cannot tell the two copies apart."""
    parts = make_doc(
        P(R("Both (Maestas 2023) and (Maestas 2023b) are cited.")),
        P(R("References")),
        P(bookmark("Maestas2023", 21, R(
            "Maestas, N. (2023). The first one. A Journal."))),
        P(bookmark("Maestas2023", 22, R(
            "Maestas, N. (2023b). Something else. B."))))

    # the unlettered entry matches strictly and keeps the name; the
    # lettered one is left unnamed rather than pointed at a coin flip
    assert _named_entries(parts) == {"maestas_2023": "Maestas2023"}


def test_TWO_lettered_entries_reaching_for_one_name_both_yield():
    """Neither can match strictly, so nothing distinguishes them —
    "whichever came first" is not an answer here."""
    parts = make_doc(
        P(R("Both (Maestas 2023a) and (Maestas 2023b) are cited.")),
        P(R("References")),
        P(bookmark("Maestas2023", 21, R(
            "Maestas, N. (2023a). Market power. A Journal."))),
        P(bookmark("Maestas2023", 22, R(
            "Maestas, N. (2023b). Something else. B."))))

    assert _named_entries(parts) == {}


def test_the_pair_RULE_is_learned_by_majority_from_whole_pairs():
    """One damaged pair must not teach the wrong shape, and a document
    with no whole pair at all keeps this module's own `txt` suffix —
    which is the only convention it can claim to know."""
    from docxkit._cite_build import _entry_of, _pair_rule, _twin_of

    assert _pair_rule("ref_alba_2015", "cite_alba_2015") == ("ref", "cite")
    assert _pair_rule("Alba2015", "Alba2015txt") == ("", "")
    assert _pair_rule("Alba2015", "Zzz9") is None      # nothing shared
    assert _twin_of("ref_cox_2022", ("ref", "cite")) == "cite_cox_2022"
    assert _twin_of("Cox2022", None) == "Cox2022txt"
    assert _entry_of("cite_cox_2022", ("ref", "cite")) == "ref_cox_2022"
    assert _entry_of("Cox2022txt", ("", "")) == "Cox2022"
    assert _entry_of("elsewhere", ("ref", "cite")) is None


def test_a_LATER_mention_is_COUNTED_always_and_reported_when_asked():
    """The audit could not tell a half-linked paper from a finished one.

    "Unlinked" was evaluated per WORK, so after `link_all` — which wires
    each work's FIRST mention only — Aging_Well printed "ALL CHECKS
    PASSED" while 20 of its 73 in-text mentions were plain text, and the
    author found one by clicking it (2026-08-21). The count says which
    state the document is in; the FINDING is opt-in, because whether
    later mentions link at all is the paper's house style, and a gate
    nobody can satisfy stops being read.
    """
    parts = make_doc(
        P(_linked_cite("Muhlbach2022", "(Mühlbach 2022)")),
        P(R("Repeated later (Mühlbach 2022) without a link.")),
        P(R("References")),
        P(_entry("Muhlbach2022", "Mühlbach, I. (2022). Ranges.")))

    issues, stats = audit_links(parts)

    assert (stats["mentions"], stats["mentions_linked"],
            stats["later_unlinked"]) == (2, 1, 1)
    assert not [i for i in issues if i.startswith("LATER-MENTION")]

    asked, _ = audit_links(parts, later_mentions=True)

    assert [i for i in asked if i.startswith("LATER-MENTION")] == [
        'LATER-MENTION UNLINKED: "Mühlbach 2022" (¶7) — the work is '
        "linked elsewhere but this mention is plain text"]


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
    (found,) = [i for i in issues if "Ghost2019" in i]
    assert "(body)" in found and "(fn)" not in found


def test_a_bookmark_defined_in_a_FOOTNOTE_is_located_as_fn():
    """The mirror of the body-level case: -1 means "between paragraphs
    of the body" and -2 means "in footnotes.xml", and the repair goes to
    a different file for each."""
    from conftest import NS, make_parts

    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5)) + P(R("Prose.")))
    foot = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:footnotes {NS}><w:footnote w:id="2"><w:p>'
            + bookmark("Ghost2019", 30) + R("Ghost, A. (2019). Unseen.")
            + "</w:p></w:footnote></w:footnotes>")

    issues, _report = audit_links(make_parts(body, footnotes=foot))

    (found,) = [i for i in issues if "Ghost2019" in i]
    assert "(fn)" in found and "(body)" not in found


def test_a_marker_is_owned_only_when_ONE_entry_fits_it():
    """`_marker_owner` is shared by MISPLACED MARKER and the UNLINKED
    scan, and it stays quiet unless exactly one entry matches by surname
    prefix AND year — two entries fitting is a guess, and a wrong owner
    reports a marker as stranded when it is where it belongs."""
    from docxkit._cite_audit import _marker_owner
    from docxkit.citations import parse_reference

    def ref(text: str) -> Reference:
        """`parse_reference` returns None on a line it cannot read, and
        an unparsed fixture would make every assertion below vacuous —
        `_marker_owner` matches nothing against a list of Nones."""
        parsed = parse_reference(text)
        assert parsed is not None, text
        return parsed

    buys = ref("Buys, L. (2012). Active ageing. J, 1(1): 3-4.")
    buys_other = ref("Buys, R. (2012). Another paper. J, 2: 1.")
    burnes = ref("Burnes, D. (2019). Interventions. J, 1: 1-2.")

    assert _marker_owner("Buys2012", [buys, burnes]) is buys
    assert _marker_owner("Buys2012", [buys, buys_other]) is None
    assert _marker_owner("Buys2019", [buys, burnes]) is None   # wrong year
    # the same surname in a LATER year is a different work, and an
    # ordering comparison would hand the marker to it
    later = ref("Buys, L. (2019). A later paper. J, 3: 5-6.")
    assert _marker_owner("Buys2012", [later, burnes]) is None
    assert _marker_owner("notakey", [buys, burnes]) is None


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
    parts = xml_parts(body)
    issues, _ = audit_links(parts)
    mis = [i for i in issues if i.startswith("MISPLACED MARKER")]
    assert not mis            # marker precedes the RIGHT entry: quiet
    body = body.replace('w:name="Buys2012"', 'w:name="stranded_x"')
    body = body.replace("Burnes, D. (2019). Interventions",
                        '</w:t></w:r><w:bookmarkStart w:id="42" '
                        'w:name="Buys2012"/><w:bookmarkEnd w:id="42"/>'
                        '<w:r><w:t>Burnes, D. (2019). Interventions')
    parts = xml_parts(body)
    issues, _ = audit_links(parts)
    mis = [i for i in issues if i.startswith("MISPLACED MARKER")]
    # the whole sentence: both paragraph numbers are what a reader acts
    # on — one to take the marker from, one to put it at — and thirty
    # characters of the entry it landed at to recognise it by
    assert mis == ["MISPLACED MARKER: 'Buys2012' sits at ¶8 "
                   '("Burnes, D. (2019). Interventio") but its entry is ¶9']


# The two boundary comparisons that locate the marker — `start() <= pos`
# and the body-level fallback's `start() >= pos` — are EQUIVALENT to
# their strict forms: `pos` is the offset of a `w:name="…"` ATTRIBUTE,
# which is inside a tag and can never equal a paragraph's own start.


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
    parts = xml_parts(body)
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
    parts = xml_parts(body)
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
    parts = xml_parts(body)
    report = link_all(parts)
    assert any("Ghost 2019" in u for u in report.unmatched)


def test_a_lead_particle_needs_a_word_boundary():
    """'...whiLE Yang's (2018)' — the lowercase lead matched mid-word
    and produced surname 'le Yang' on the Missing Market dry run."""
    assert find_citations("worthwhile Yang (2018) results")[0].surname \
        == "Yang"


# ------------------------------------------------------- resolve_lead ---
#
# "Word, First and Second" is the shape of a three-author citation, so a
# capitalised word before the comma is swallowed into the chain. The head
# of a real chain is what the bibliography files the work under; the
# swallowed word is not, and that is the only thing telling them apart.

UK = "In the United Kingdom, Chan and Koo (2011) find a gradient."


def _resolved(text, known=()):
    from docxkit.citations import resolve_lead
    return resolve_lead(find_citations(text)[0], known=known)


def test_an_unlisted_lead_word_is_dropped_on_the_bibliographys_evidence():
    """Parental Style: 'Kingdom, Chan and Koo (2011)' — the grammar can
    only take 'United Kingdom' from its last word, and the comma welds
    it to the authors."""
    c = _resolved(UK, {"chan_2011"})
    assert c.authors == "Chan and Koo" and c.surname == "Chan"
    assert UK[c.start:c.end] == "Chan and Koo (2011)"


def test_a_real_three_author_chain_keeps_its_lead():
    """Same string shape, and the head IS what the list files it under."""
    text = "Work by Chan, Koo and Smith (2011) finds a gradient."
    c = _resolved(text, {"chan_2011", "koo_2011"})
    assert c.authors == "Chan, Koo and Smith"


def test_a_lead_filed_at_another_year_is_never_dropped():
    """'Kingdom' as a real surname, cited for a different work: the
    evidence is that the list files SOMETHING under it, not that this
    year matches — a 2011 entry missing from the list must not silently
    re-point the citation at its co-author."""
    c = _resolved(UK, {"kingdom_1999", "chan_2011"})
    assert c.authors == "Kingdom, Chan and Koo"


@pytest.mark.parametrize("known", [
    (),                                  # no bibliography to consult
    {"nobody_2011"},                     # neither name listed
    {"kingdom_2011"},                    # the head itself is listed
])
def test_without_evidence_the_citation_is_left_exactly_as_found(known):
    """The honest answer is UNMATCHED. Guessing here would link a
    citation whose lead author is merely missing from the list to
    whatever co-author happens to be in it."""
    assert _resolved(UK, known).authors == "Kingdom, Chan and Koo"


def test_link_all_links_a_citation_behind_a_swallowed_lead_word():
    from docxkit.citations import link_all
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R(UK))
            + P(R("References"))
            + P(R("Chan, T. W., and A. Koo. (2011). Parenting style. "
                  "EJP, 27(3): 385-99.")))
    parts = xml_parts(body)
    report = link_all(parts)
    assert report.unmatched == [] and len(report.linked) == 1
    assert _links(parts)[0] == "Chan and Koo (2011)"
    issues, _ = audit_links(parts)
    assert issues == [], issues


# ------------------------------------------------ the possessive form ---
#
# "Becker's (1981) model" is a citation of Becker 1981. The apostrophe is
# a NAME character — D'Souza, O'Brien — so the grammar takes "Becker's"
# whole and the key came out `beckers_1981`, matching no entry. Found on
# Parental Style ¶92, 2026-08-10, where it cost a hand-written
# link_in_para in the paper's repair script.

FILLER = "".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                 for i in range(5))
BECKER = ("Becker, G. S. (1981). A Treatise on the Family. "
          "Harvard University Press.")


@pytest.mark.parametrize("text, surname, year", [
    ("Becker’s (1981) model", "Becker", "1981"),          # typographic
    ("Becker's (1981) model", "Becker", "1981"),          # straight
    ("Doepke et al.'s (2019) model", "Doepke", "2019"),   # on a CHAIN
    ("the Smiths' (1981) model", "Smiths", "1981"),       # plural
    ("D'Souza (1981) argues", "D'Souza", "1981"),         # a JOINING one
])
def test_a_possessive_citation_files_under_the_plain_surname(
        text, surname, year):
    c = find_citations(text)[0]
    assert c.surname == surname and c.key == key_for(surname, year)


def test_link_all_links_a_possessive_citation():
    """It reported `unmatched` — right, and unlinkable: no entry answers
    to `beckers_1981`."""
    from docxkit.citations import link_all
    body = (FILLER
            + P(R("Becker’s (1981) model explains the gradient."))
            + P(R("References")) + P(R(BECKER)))
    parts = xml_parts(body)
    report = link_all(parts)
    assert report.unmatched == [] and len(report.linked) == 1
    # the span keeps the possessive: it is what the sentence says
    assert _links(parts)[0] == "Becker’s (1981)"


def test_a_later_mention_worded_differently_is_not_reported_unlinked():
    """The convention links a work's FIRST mention only, so UNLINKED asks
    whether the WORK is linked — and asking it of the label text read the
    possessive mention as unlinked while the entry was linked twice
    elsewhere."""
    from docxkit.citations import link_all
    body = (FILLER
            + P(R("Fertility responds to income (Becker 1981)."))
            + P(R("Becker’s (1981) framework explains it."))
            + P(R("References")) + P(R(BECKER)))
    parts = xml_parts(body)
    link_all(parts)
    issues, stats = audit_links(parts)
    assert issues == [], issues
    assert stats["unlinked"] == 0


def test_a_work_with_no_link_at_all_is_still_reported():
    """The guard above must not silence the finding it was built around:
    with nothing linked, the possessive mention IS unlinked."""
    body = (FILLER
            + P(R("Becker’s (1981) framework explains it."))
            + P(R("References")) + P(R(BECKER)))
    issues, stats = audit_links(xml_parts(body))
    assert stats["unlinked"] == 1
    assert any("UNLINKED" in i and "Becker" in i for i in issues)


def test_the_audit_reports_a_link_with_no_label():
    """The S1 the audit could not see: the anchor resolves, so nothing
    else in here fires. Parental Style 2026-08-11."""
    dead = ('<w:p><w:r><w:t xml:space="preserve">as shown in </w:t></w:r>'
            '<w:bookmarkStart w:id="3" w:name="Table1"/>'
            '<w:bookmarkEnd w:id="3"/>'
            '<w:hyperlink w:anchor="Table1"><w:r><w:t></w:t></w:r>'
            "</w:hyperlink>"
            '<w:r><w:t>Table 1, the gap is wide.</w:t></w:r></w:p>')
    parts = xml_parts(FILLER + dead + P(R("References")) + P(R(BECKER)))
    issues, stats = audit_links(parts)
    assert stats["empty"] == 1
    assert any(i.startswith("EMPTY LINK") and "Table1" in i for i in issues), \
        issues


def test_the_audit_reads_footnotes_for_dead_links_too():
    """Five of the real ones are in a footnote: LI's "(Catalano 2003)"
    and its four neighbours read as plain text, each followed by an
    empty field still holding its <key>txt bookmark. A body-only scan
    reports none of them."""
    from conftest import NS, make_parts, para, run
    body = (FILLER + P(R("References")) + P(R(BECKER))
            + '<w:p><w:bookmarkStart w:id="3" w:name="Catalano2003"/>'
              "<w:bookmarkEnd w:id=\"3\"/><w:r><w:t>Catalano, R. (2003). "
              "Sex ratios. Human Reproduction.</w:t></w:r></w:p>")
    dead = (para(run("Stress selects fetal loss (Catalano 2003).")
                 + '<w:hyperlink w:anchor="Catalano2003"><w:r><w:t></w:t>'
                   "</w:r></w:hyperlink>"))
    foot = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:footnotes {NS}><w:footnote w:id="2">{dead}'
            f"</w:footnote></w:footnotes>")
    issues, stats = audit_links(make_parts(body, footnotes=foot))
    assert stats["empty"] == 1
    assert any(i.startswith("EMPTY LINK") and "(fn)" in i for i in issues), \
        issues


def test_a_link_inside_deleted_text_is_not_evidence_of_a_link():
    """LE le12 ¶195: the author retyped the sentence, which dropped its
    hyperlink, and the tracked DELETION beside it still carried the old
    one. A link the final document does not show cannot answer "is this
    work linked"."""
    deleted = (
        '<w:p><w:del w:id="9" w:author="A" w:date="2026-07-01T00:00:00Z">'
        '<w:r><w:delText xml:space="preserve">Longevity is endogenous ('
        "</w:delText></w:r>"
        '<w:hyperlink w:anchor="Becker1981"><w:r>'
        "<w:delText>Becker 1981</w:delText></w:r></w:hyperlink>"
        "<w:r><w:delText>).</w:delText></w:r></w:del></w:p>")
    retyped = P(R("Longevity is endogenous to investment (Becker 1981)."))
    parts = xml_parts(FILLER + retyped + deleted
                      + P(R("References")) + P(R(BECKER)))
    issues, stats = audit_links(parts)
    assert stats["unlinked"] == 1
    assert any("UNLINKED" in i and "Becker" in i for i in issues), issues


# ----------------------------------------------------- extend_to_name ---
#
# The mirror of the same grammar rule: a plain multi-word institution is
# captured from its LAST word, which finds the entry and underlines the
# wrong words.

GICP = "Global Initiative to End All Corporal Punishment of Children"


def _extended(text, name=GICP):
    from docxkit.citations import extend_to_name
    c = extend_to_name(text, find_citations(text)[0], name)
    return text[c.start:c.end]


def test_an_institutional_citation_is_widened_to_its_whole_name():
    """Parental Style: the underline began at "Punishment", mid-name."""
    assert _extended("Still lawful (End Corporal Punishment 2024).") \
        == "End Corporal Punishment 2024"


def test_the_widening_settles_on_a_capital():
    """"to" and "of" are words of the name, but no institution's name
    begins with one."""
    want = "Initiative to End All Corporal Punishment (2024)"
    assert _extended(f"See {want} on the law.") == want


@pytest.mark.parametrize("text, want", [
    # prose the entry does not name stops the walk
    ("Reported in the recent Punishment (2024) review.", "Punishment (2024)"),
    # so does punctuation, however well the words match
    ("Ending all corporal punishment. Punishment (2024) reports.",
     "Punishment (2024)"),
    # and the citation group's own bracket is taken, never crossed
    ("Children (End Corporal Punishment 2024).",
     "End Corporal Punishment 2024"),
])
def test_the_widening_stops_where_the_name_does(text, want):
    assert _extended(text) == want


def test_a_chain_of_authors_is_never_widened():
    """The words to the left may belong to an institution and the
    citation still be two people: widening here would weld a name onto a
    co-author chain."""
    text = "End Corporal Punishment and Koo (2011) agree."
    assert _extended(text) == "Punishment and Koo (2011)"


def test_an_acronym_the_name_does_not_spell_is_not_widened():
    """"(WHO 2015)" resolves to "World Health Organization" through the
    entry's initialism — there is nothing to its left to take."""
    assert _extended("As reported (WHO 2015).",
                     "World Health Organization") == "WHO 2015"


def test_link_all_underlines_an_institutions_whole_name():
    from docxkit.citations import link_all
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Corporal punishment is still lawful in the home "
                  "(End Corporal Punishment 2024)."))
            + P(R("References"))
            + P(R(f"{GICP}. (2024). Global report. London.")))
    parts = xml_parts(body)
    assert len(link_all(parts).linked) == 1
    assert _links(parts)[0] == "End Corporal Punishment 2024"


def test_a_stripped_lead_takes_the_span_with_it():
    """The strip fixed the KEY and left the SPAN, so the hyperlink went
    on "Similarly, Liebman and Luttmer (2015)" — right target, wrong
    words, in every paper linked before this."""
    from docxkit.citations import link_all
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Similarly, Liebman and Luttmer (2015) show a gap."))
            + P(R("References"))
            + P(R("Liebman, J., and E. Luttmer. (2015). A title. JEP.")))
    parts = xml_parts(body)
    assert len(link_all(parts).linked) == 1
    assert _links(parts)[0] == "Liebman and Luttmer (2015)"


# --- where the widening stops, and what it settles on (2026-08-19) ------
#
# `extend_to_name` had 12 survivors, second only to the wrapper it feeds.
# Every fixture above uses one long institution name whose words are all
# lower-case except the first, and that shape hides three separate
# decisions: how short a name may be, whose word the walk starts from,
# and which word the span finally settles on.


def test_a_TWO_word_institution_is_widened_too():
    """`len(words) < 2` — two is enough to be a name; the rule exists to
    exclude a name of ONE word, where there is nothing to widen to and
    every capitalised word before the citation would be swallowed."""
    text = "Still lawful (Corporal Punishment 2024)."

    assert _extended(text, "Corporal Punishment") == "Corporal Punishment 2024"


def test_a_ONE_word_name_widens_to_nothing():
    """The other side of the same number. `_extended` reads the span
    back, so a name of one word must leave it exactly where the grammar
    put it."""
    text = "Reported by the Punishment (2024) review."

    assert _extended(text, "Punishment") == "Punishment (2024)"


def test_an_acronym_is_not_widened_over_the_name_it_stands_for():
    """`len(words) < 2 OR the lead word is not one of them` — either
    disqualifies. The acronym case is the second: "WHO" is not a word of
    "World Health Organization", so there is nothing here to take.

    Under `and` the walk runs anyway, and the second sentence is where
    that shows: the words to its left ARE the name, so the link would be
    underlined from "Global" — over the spelled-out name as well as the
    acronym, which is the defect this function exists to fix, in the
    other direction. Papers write the pair that way ("the Global Burden
    of Disease GBD (2019) study") whenever the acronym is the one the
    reference list files under."""
    bracketed = "As the World Health Organization (WHO 2015) reports."
    spelled = "Estimates from the Global Burden of Disease GBD (2019) agree."

    assert _extended(bracketed, "World Health Organization") == "WHO 2015"
    assert _extended(spelled, "Global Burden of Disease") == "GBD (2019)"


def test_a_SENTENCE_BOUNDARY_stops_the_walk_however_well_the_words_match():
    """`word[-1] in _STOPS_A_NAME` — the LAST character of the word, and
    the check that cannot be replaced by "is this word one of the
    name's": `_bare` strips punctuation, so "Punishment." reads as
    "punishment" and matches.

    The previous fixture for this crossed only lower-case words, and the
    settle-on-a-capital rule then put the span back where it started —
    so every index into `word` passed. Here the words before the full
    stop are capitalised, and a walk that crosses it underlines a
    sentence that belongs to the author."""
    text = "The report covers Corporal Punishment. Punishment (2024) says."

    assert _extended(text) == "Punishment (2024)"


def test_a_name_that_OPENS_with_a_number_settles_on_the_first_letter():
    """Two lines, one fixture. The settle loop skips a word with no
    letter in it — "2030 Water Resources Group" is an institution, and
    `first` is None for its first word — so `first is not None AND
    isupper()` has to be an AND, or the check reads a group off None.
    And the span lands at `at + wm.start() + first.start()`: the offset
    of the word it settled on, which is zero in every fixture where the
    first word settles."""
    text = "See 2030 Water Resources Group (2024) for the target."

    assert _extended(text, "2030 Water Resources Group") == (
        "Water Resources Group (2024)")


def test_a_SHORT_name_behind_a_long_lead_moves_the_span_by_the_lead():
    """`c.start + len(c.authors) - len(authors)`: the span moves right
    by exactly what was trimmed off its front. `%` agrees with `-`
    whenever the lead is shorter than what remains, which is every
    fixture written so far — "Similarly, Liebman and Luttmer" trims 11
    characters off 30 and `30 % 19` is 11 too. One short surname is
    where they part: 16 and 5, `-` gives 11 and `%` gives 1."""
    from docxkit.citations import resolve_lead

    text = "Similarly, Smith (2015) shows a gap."
    c = resolve_lead(find_citations(text)[0])

    assert c.authors == "Smith"
    assert text[c.start:c.end] == "Smith (2015)"


# ---------------------------------------------------------- repair_plan ---

def test_repair_plan_classifies_the_known_damage_classes():
    from docxkit.citations import repair_plan
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Cites (Aksoy 2026) here."))
            + P(R("References"))
            + P(bookmark("Ghost2019", 71)          # entry text deleted
                + bookmark("Aksoy2026", 72)
                + hfield("Aksoy2026txt", "Aksoy, C. (2026)")   # back-link
                + R("Aksoy, C. (2026). Working from home. JEP."))
            )
    parts = xml_parts(body)
    plan = repair_plan(parts)
    assert "debris of a deleted entry" in plan and "Ghost2019" in plan
    assert "recreate the lost link" in plan       # Aksoy cited, unlinked
    assert "Review EVERY anchor" in plan


def test_repair_plan_on_a_clean_document():
    from docxkit.citations import repair_plan
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Nothing cited here."))
            + P(R("References"))
            + P(R("Aksoy, C. (2026). Working from home. JEP.")))
    parts = xml_parts(body)
    plan = repair_plan(parts)
    assert "investigate" in plan or "nothing to repair" in plan


def test_wrap_link_survives_a_styled_field_run():
    """A begin-fldChar run carrying <w:rPr>: rfind("<w:r") landed on the
    rPr and the wrap cut mid-run — LI7 round 2 shipped malformed XML
    before the fix. The result must PARSE, not just look right."""
    from lxml import etree


    styled_field = (
        '<w:r><w:rPr><w:noProof/></w:rPr>'
        '<w:fldChar w:fldCharType="begin"/></w:r>'
        r'<w:r><w:instrText>HYPERLINK \l "Smith2020"</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + R("Smith 2020")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    out = wrap_link_in_bookmark(P(R("see ") + styled_field),
                                "Smith2020", "Smith2020txt", 9)
    etree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>' + out
        + "</w:body></w:document>")
    assert out.index('w:name="Smith2020txt"') < out.index("noProof")


def test_remove_outer_field_unnests_and_still_parses():
    """The DOUBLED LINK repair: the stale outer field goes, the correct
    element link survives — and the result must PARSE (the first field
    surgery shipped malformed XML that only lint caught)."""
    from lxml import etree

    from docxkit.citations import remove_outer_field
    outer = (
        '<w:r><w:rPr><w:noProof/></w:rPr>'
        '<w:fldChar w:fldCharType="begin"/></w:r>'
        r'<w:r><w:instrText>HYPERLINK \l "Stale2021txt"</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:hyperlink w:anchor="Fresh2022txt">' + R("Head. (2022)")
        + "</w:hyperlink>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    out = remove_outer_field(P(outer), "Stale2021txt", "Fresh2022txt")
    etree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>' + out
        + "</w:body></w:document>")
    from docxkit._xml import internal_links
    assert internal_links(out) == [("Fresh2022txt", "Head. (2022)")]
    import pytest as _pytest

    from docxkit.errors import AnchorError
    with _pytest.raises(AnchorError):
        remove_outer_field(out, "Stale2021txt", "Fresh2022txt")


def test_repair_plan_names_the_unnest_call():
    from docxkit.citations import repair_plan
    fld = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           r'<w:r><w:instrText>HYPERLINK \l "Old2020"</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:hyperlink w:anchor="New2021">' + R("New 2021")
           + "</w:hyperlink>"
           '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5)) + P(fld))
    plan = repair_plan(xml_parts(body))
    assert 'remove_outer_field(doc, "Old2020", "New2021")' in plan


# --- link_rest: every later citation, forward only ---------------------

def test_link_rest_links_every_later_citation_forward_only():
    parts = make_doc(
        P(R("Maestas et al. (2023) estimate willingness to pay.")),
        P(R("Later work concurs (Maestas et al. 2023).")),
        P(R("References")),
        P(R("Maestas, N., and K. Mullen. (2023). Willingness to pay.")),
    )
    from docxkit import citations as C
    C.link_all(parts)
    rep = C.link_rest(parts)
    assert len(rep.linked) == 1, rep.format()
    body = parts["word/document.xml"].decode("utf-8")
    assert body.count('"Maestas2023"') >= 2      # entry + both mentions
    later = next(p for p in re.findall(r"<w:p\b.*?</w:p>", body, re.DOTALL)
                 if "concurs" in p)
    assert 'w:anchor="Maestas2023"' in later
    assert "Maestas2023txt" not in later         # no second bookmark
    rep2 = C.link_rest(parts)
    assert rep2.linked == [], rep2.format()      # idempotent


# --- wrap_link_in_bookmark: which mention owns the <key>txt bookmark ---
#
# It refuses on several links by design. The house convention has an
# answer — the FIRST mention — and with no way to say so the same regex
# was hand-rolled twice in one paper.

def _two_links(anchor: str = "Table5") -> str:
    return ("<w:document><w:body>"
            + P(R("The wealth gradient is in ")
                + f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>Table 5'
                  "</w:t></w:r></w:hyperlink>" + R("."))
            + P(R("The age profile repeats it (")
                + f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>Table 5'
                  "</w:t></w:r></w:hyperlink>" + R(").").rstrip())
            + "</w:body></w:document>")


def test_wrap_link_still_refuses_to_guess_by_default():

    with pytest.raises(AnchorError, match="matched 2 links"):
        wrap_link_in_bookmark(_two_links(), "Table5", "Table5txt", 9200)


def test_wrap_link_takes_the_first_mention_when_asked():

    out = wrap_link_in_bookmark(_two_links(), "Table5", "Table5txt", 9200,
                                which="first")
    assert out.count('w:name="Table5txt"') == 1
    first, second = re.findall(r"<w:p>.*?</w:p>", out, re.DOTALL)
    assert "Table5txt" in first and "Table5txt" not in second


def test_wrap_link_counts_both_link_FORMS_as_mentions():
    """Word rewrites a field into an element on every author save, so a
    manuscript mid-round holds one of each. Counting only the elements
    made the element unique — and the bookmark would land wherever form
    churn had left it."""
    from docxkit.citations import hyperlink_field, wrap_link_in_bookmark
    mixed = ("<w:document><w:body>"
             + P(R("Field form: ") + hyperlink_field("Table5", "Table 5"))
             + P(R("Element form: ")
                 + '<w:hyperlink w:anchor="Table5"><w:r><w:t>Table 5'
                   "</w:t></w:r></w:hyperlink>")
             + "</w:body></w:document>")
    with pytest.raises(AnchorError, match="matched 2 links"):
        wrap_link_in_bookmark(mixed, "Table5", "Table5txt", 9200)
    out = wrap_link_in_bookmark(mixed, "Table5", "Table5txt", 9200,
                                which="first")
    first = re.findall(r"<w:p>.*?</w:p>", out, re.DOTALL)[0]
    assert "Table5txt" in first, "the FIELD-form mention came first"


def test_wrap_link_rejects_an_unknown_mode():

    with pytest.raises(ValueError, match="which="):
        wrap_link_in_bookmark(_two_links(), "Table5", "t", 1, which="last")


def test_wrap_link_says_so_when_there_is_no_link_at_all():

    with pytest.raises(AnchorError, match="no link to"):
        wrap_link_in_bookmark("<w:document><w:body/></w:document>",
                              "Ghost2019", "Ghost2019txt", 1)


def test_link_rest_sees_an_entry_bookmark_word_hoisted_out():
    """Word lifts a collapsed bookmark out of the paragraph it marks, so
    a settled manuscript keeps the entry's marker BETWEEN paragraphs.
    Reading the paragraph alone, link_rest declined every later mention
    of those works as "entry has no bookmark" — nine mentions across six
    works on Parental Style, and the author found it before any tool
    did."""
    from docxkit import citations as C
    parts = make_doc(
        P(R("Straus et al. (1998) report the same gradient.")),
        P(R("Later work concurs (Straus et al. 1998).")),
        P(R("References")),
        # the marker hoisted clear of its entry, as Word leaves it
        '<w:bookmarkStart w:id="7" w:name="Straus1998"/>'
        '<w:bookmarkEnd w:id="7"/>',
        P(R("Straus, M., Sugarman, D., and J. Giles-Sims. (1998). "
            "Spanking and antisocial behavior. APAM.")),
    )
    rep = C.link_rest(parts)
    assert rep.skipped == [], rep.format()
    assert len(rep.linked) == 2, rep.format()
    body = parts["word/document.xml"].decode("utf-8")
    assert body.count('w:anchor="Straus1998"') == 2


def test_link_rest_handles_repeats_within_one_paragraph():
    # link_all's unique-anchor locate cannot place a citation that
    # repeats inside one paragraph; the positional pass can.
    parts = make_doc(
        P(R("One (Chetty 2015). Two (Chetty 2015). Three (Chetty 2015).")),
        P(R("References")),
        P(R("Chetty, R. (2015). Behavioral economics.")),
    )
    from docxkit import citations as C
    C.link_all(parts)
    rep = C.link_rest(parts)
    body = parts["word/document.xml"].decode("utf-8")
    assert body.count('w:anchor="Chetty2015"') == 3
    assert len(rep.skipped) == 0, rep.format()


def test_unlink_by_anchor_removes_a_legacy_scheme():
    xml = ('<w:document><w:body><w:p>'
           '<w:hyperlink w:anchor="bookmark=id.abc123">'
           "<w:r><w:t>(Smith 2020)</w:t></w:r></w:hyperlink>"
           "<w:r><w:t> stays; </w:t></w:r>"
           '<w:hyperlink w:anchor="Table1">'
           "<w:r><w:t>Table 1</w:t></w:r></w:hyperlink>"
           "</w:p>"
           '<w:p><w:bookmarkStart w:id="4" w:name="bookmark=id.abc123"/>'
           '<w:bookmarkEnd w:id="4"/>'
           "<w:r><w:t>Smith, J. (2020). Title.</w:t></w:r></w:p>"
           "</w:body></w:document>")
    from docxkit import citations as C
    out, links, marks = C.unlink_by_anchor(xml, r"^bookmark=id\.")
    assert links == 1 and marks == 1
    assert "bookmark=id.abc123" not in out
    assert 'w:anchor="Table1"' in out
    assert "(Smith 2020)" in out


def test_masked_visible_text_masks_both_link_forms():
    para_xml = ('<w:p><w:hyperlink w:anchor="a">'
                "<w:r><w:t>linked</w:t></w:r></w:hyperlink>"
                "<w:r><w:t> plain </w:t></w:r>"
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                r'<w:r><w:instrText>HYPERLINK \l "b" \h</w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                "<w:r><w:t>field</w:t></w:r>"
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    from docxkit import citations as C
    masked = C.masked_visible_text(para_xml)
    assert masked == "\x00" * 6 + " plain " + "\x00" * 5


def test_unlink_by_anchor_removes_field_form_links_too():
    # A Google export writes reference-entry links as fldChar fields;
    # leaving them vetoes link_all's entry back-links.
    from docxkit import citations as C
    xml = ("<w:document><w:body><w:p>"
           '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText>HYPERLINK \l "bookmark=id.zzz" \h'
           "</w:instrText></w:r>"
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           "<w:r><w:rPr><w:u w:val=\"single\"/></w:rPr>"
           "<w:t>Smith, J. (2020)</w:t></w:r>"
           '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
           "<w:r><w:t>. Title.</w:t></w:r>"
           "</w:p></w:body></w:document>")
    out, links, marks = C.unlink_by_anchor(xml, r"^bookmark=id\.")
    assert links == 1 and marks == 0
    assert "fldChar" not in out and "instrText" not in out
    assert "Smith, J. (2020)" in out and ". Title." in out


def test_link_all_is_idempotent_after_a_deduped_name():
    # A stale bookmark holds the plain name, so the entry's bookmark is
    # minted as Surname2023_2; the own-name scan must recognise the _N
    # suffix or every later run mints another and re-wraps the citation
    # (the Parental Style Kazenin spiral).
    from docxkit import citations as C
    body = ('<w:p><w:bookmarkStart w:id="1" w:name="Kazenin2023txt"/>'
            '<w:bookmarkEnd w:id="1"/>'
            "<w:r><w:t>Old round left this bookmark elsewhere.</w:t></w:r>"
            "</w:p>"
            "<w:p><w:r><w:t>Fertility changed (Kazenin 2023).</w:t>"
            "</w:r></w:p>"
            "<w:p><w:r><w:t>References</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Kazenin, K. (2023). Son preference. "
            "Asian Population Studies.</w:t></w:r></w:p>")
    parts = {"word/document.xml": (
        "<w:document><w:body>" + body + "</w:body></w:document>").encode()}
    C.link_all(parts)
    rep2 = C.link_all(parts)
    assert rep2.linked == [], rep2.format()
    doc = parts["word/document.xml"].decode()
    import re as _re
    minted = set(_re.findall(r'w:name="(Kazenin2023_\d+)"', doc))
    assert len(minted) <= 1, minted


def test_self_closing_hyperlink_ghost_does_not_eat_a_later_close():
    # Word leaves empty <w:hyperlink .../> ghosts behind; treating one as
    # an open tag pairs it with the NEXT </w:hyperlink> anywhere
    # downstream — 14 paragraphs on Parental Style — and an unwrap then
    # deletes a close tag belonging to another link entirely.
    from docxkit import citations as C
    from docxkit._xml import internal_links
    xml = ("<w:document><w:body>"
           '<w:p><w:hyperlink w:anchor="bookmark=id.ghost"/>'
           "<w:r><w:t>twins are rare.</w:t></w:r></w:p>"
           '<w:p><w:hyperlink w:anchor="bookmark=id.real">'
           "<w:r><w:t>Agostinelli (2024)</w:t></w:r></w:hyperlink>"
           "<w:r><w:t> tail.</w:t></w:r></w:p>"
           "</w:body></w:document>")
    # the reader must see exactly one real link
    assert internal_links(xml) == [("bookmark=id.real", "Agostinelli (2024)")]
    out, links, _marks = C.unlink_by_anchor(xml, r"^bookmark=id\.")
    assert links == 2                      # one unwrap + one ghost dropped
    opens = out.count("<w:hyperlink")
    closes = out.count("</w:hyperlink>")
    assert opens == closes == 0, (opens, closes)
    assert "Agostinelli (2024)" in out and "twins are rare." in out


def test_the_facade_still_offers_every_name_it_ever_did():
    """citations.py was split into layers; the import path is the API.

    Every paper's build script imports from `docxkit.citations`, so a
    split that moved a name would be a split that broke a build. This
    pins the contract rather than trusting that nobody noticed.
    """
    import docxkit.citations as C
    for name in C.__all__:
        assert hasattr(C, name), f"{name} vanished from the facade"

    # the private names other modules and tests reach through it
    for name in ("_ACRONYM_RE", "_entry_keys", "strip_lead",
                 "_doubled_links", "_KEY_SHAPE_RE", "_BOOKMARK_NAME_RE",
                 "_audit_findings", "DISCOURSE_LEADS", "link_rest",
                 "unlink_by_anchor", "masked_visible_text",
                 "wrap_visible_span", "next_bookmark_id"):
        assert hasattr(C, name), f"{name} vanished from the facade"




def _parts(*paras):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    return {"word/document.xml":
            f"<w:document {ns}><w:body>{body}</w:body></w:document>"
            .encode()}


def test_an_entry_bookmark_must_match_the_surname_not_just_the_year():
    """link_all reused any key-shaped bookmark whose YEAR matched.

    A stray `Jones2020` left on a "Smith, A. (2020)" entry by an earlier
    round made every "(Smith 2020)" in the text link to the wrong work —
    and the report said "linked 1" while doing it.
    """
    from docxkit.citations import link_all
    parts = _parts("Smith (2020) argues the point.",
                   "References",
                   "Smith, A. (2020). A title. Journal.")
    doc = parts["word/document.xml"].decode("utf-8")
    doc = doc.replace(
        "<w:p><w:r><w:t>Smith, A. (2020)",
        '<w:p><w:bookmarkStart w:id="90" w:name="Jones2020"/>'
        '<w:bookmarkEnd w:id="90"/><w:r><w:t>Smith, A. (2020)')
    parts["word/document.xml"] = doc.encode("utf-8")

    link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")
    assert 'w:anchor="Jones2020"' not in out, "linked to the wrong entry"
    assert 'w:name="Smith2020"' in out       # its own bookmark was minted


def test_a_SHORT_surname_does_not_adopt_a_name_it_merely_SITS_INSIDE():
    """A foreign scheme's name is read by folding it to letters and
    digits, and the surname was then looked for ANYWHERE in that fold —
    so "Ho, B. (2019)" adopted a stray `ref_thompson_2019` ("ho" is
    inside "refthompson") and every "(Ho 2019)" in the manuscript
    pointed at another work's entry, reported as linked. Li and
    `ref_polinelli_2020` is the same shape, and so is every surname of
    two or three letters: An, Xu, Ng, Wu.
    """
    from docxkit.citations import link_all
    parts = _parts("Ho (2019) argues the point.",
                   "References",
                   "Ho, B. (2019). A title. Journal.")
    doc = parts["word/document.xml"].decode("utf-8")
    doc = doc.replace(
        "<w:p><w:r><w:t>Ho, B. (2019)",
        '<w:p><w:bookmarkStart w:id="90" w:name="ref_thompson_2019"/>'
        '<w:bookmarkEnd w:id="90"/><w:r><w:t>Ho, B. (2019)')
    parts["word/document.xml"] = doc.encode("utf-8")

    link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")
    assert 'w:anchor="ref_thompson_2019"' not in out, "linked to another work"
    assert 'w:name="Ho2019"' in out           # its own bookmark was minted


def test_a_FOREIGN_name_whose_OWN_WORD_is_the_surname_is_still_reused():
    """The tightening must not cost the reuse it was written for. AFI's
    104 entry bookmarks are all `ref_<surname>_<year>`, and adopting
    them is what stops link_all writing a second bookmark beside each —
    the DOUBLED LINK that made this reader necessary. A separated
    institution ("World Bank") has to answer too, so the surname is
    matched against the name's words JOINED as well as one at a time.
    """
    from docxkit.citations import link_all
    for name, cite, entry in (
            ("ref_kanbur_2007", "Kanbur (2007) argues the point.",
             "Kanbur, R. (2007). Poverty. Journal."),
            ("ref_world_bank_2024", "World Bank (2024) reports as much.",
             "World Bank. (2024). A report. Washington DC.")):
        parts = _parts(cite, "References", entry)
        doc = parts["word/document.xml"].decode("utf-8")
        # the ENTRY's paragraph, which its opening names uniquely — the
        # citation above it opens with the surname too.
        head = f"<w:p><w:r><w:t>{entry}"
        assert doc.count(head) == 1, "the fixture's own anchor is ambiguous"
        doc = doc.replace(
            head, f'<w:p><w:bookmarkStart w:id="90" w:name="{name}"/>'
                  f'<w:bookmarkEnd w:id="90"/><w:r><w:t>{entry}')
        parts["word/document.xml"] = doc.encode("utf-8")

        link_all(parts)
        out = parts["word/document.xml"].decode("utf-8")
        assert out.count(f'w:name="{name}"') == 1, f"{name}: not reused"
        assert f'w:anchor="{name}"' in out, f"{name}: not linked"


def test_an_entrys_own_bookmark_is_still_reused():
    """The guard must not stop link_all reusing the RIGHT bookmark —
    the document is the authority on anchor names."""
    from docxkit.citations import link_all
    parts = _parts("Smith (2020) argues the point.",
                   "References",
                   "Smith, A. (2020). A title. Journal.")
    doc = parts["word/document.xml"].decode("utf-8")
    doc = doc.replace(
        "<w:p><w:r><w:t>Smith, A. (2020)",
        '<w:p><w:bookmarkStart w:id="90" w:name="Smith2020"/>'
        '<w:bookmarkEnd w:id="90"/><w:r><w:t>Smith, A. (2020)')
    parts["word/document.xml"] = doc.encode("utf-8")

    link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")
    assert out.count('w:name="Smith2020"') == 1     # reused, not duplicated
    assert 'w:anchor="Smith2020"' in out


# --------------------------------- a back-link whose target never landed -


def test_no_backlink_survives_a_refused_in_text_wrap():
    """The back-link is decided while PLANNING, but the wrap that creates
    its <name>txt target runs later and can refuse — a citation occurring
    twice in one paragraph is ambiguous, so link_in_para raises. Entries
    are rebuilt bottom-up and the reference list sits below the prose, so
    the back-link is already written by then. Shipping it leaves a
    dangling anchor that only an audit finds (Parental Style: Bhalotra
    and Clarke, welded by hand).
    """
    from docxkit.citations import audit_links, link_all
    parts = _parts(
        "Smith (2020) shows one thing, and Smith (2020) shows another.",
        "References",
        "Smith, A. (2020). A title. Journal.")
    rep = link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")

    assert "Smith2020txt" not in out or 'w:name="Smith2020txt"' in out, \
        "a Smith2020txt anchor exists with no such bookmark"
    assert rep.backlinked == [], f"back-linked anyway: {rep.backlinked}"
    assert any("back-link" in s for s in rep.skipped), rep.skipped

    findings = audit_links(parts)
    broken = [f for f in findings if "BROKEN LINK" in str(f)]
    assert not broken, broken


def test_a_normal_backlink_is_untouched():
    """The repair must not fire when the wrap succeeded."""
    from docxkit.citations import link_all
    parts = _parts("Smith (2020) shows one thing.",
                   "References",
                   "Smith, A. (2020). A title. Journal.")
    rep = link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")
    assert rep.backlinked == ["Smith2020"], rep.backlinked
    assert 'w:name="Smith2020txt"' in out
    assert 'w:anchor="Smith2020txt"' in out


# ------------------------------------- markers Word hoisted out of the ¶ -


def _hoist_markers(parts):
    """Move every paragraph-head bookmark out to body level, the way Word
    normalizes them when the author saves."""
    doc = parts["word/document.xml"].decode("utf-8")
    doc = re.sub(
        r"(<w:p\b[^>]*>)((?:<w:bookmarkStart[^>]*/><w:bookmarkEnd[^>]*/>)+)",
        r"\2\1", doc)
    parts["word/document.xml"] = doc.encode("utf-8")
    return doc


def test_link_all_reuses_a_marker_word_hoisted_out_of_the_paragraph():
    """_mark_para_head writes the marker INSIDE the entry paragraph, but
    Word moves it to body level on save — 86 of 167 on Parental Style's
    second handback. Reading only the paragraph found nothing, so a
    top-up run minted a second name for every entry and re-wrapped all
    71 citations (Baumrind1991_2txt), silently doubling the scheme.
    """
    from docxkit.citations import link_all
    parts = _parts("As Smith (2020) argues, and Jones (2019) agrees.",
                   "References",
                   "Jones, B. (2019). Another title. Journal.",
                   "Smith, A. (2020). A title. Journal.")
    link_all(parts)
    first = parts["word/document.xml"].decode("utf-8")
    assert 'w:name="Smith2020"' in first

    _hoist_markers(parts)
    hoisted = parts["word/document.xml"].decode("utf-8")
    assert '/><w:p' in hoisted, "fixture did not hoist anything"

    rep = link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")
    assert "_2" not in out, "the scheme was duplicated"
    assert rep.linked == [], f"re-wrapped: {rep.linked}"
    for name in ("Smith2020", "Jones2019"):
        assert out.count(f'w:name="{name}"') == 1, name


def test_a_hoisted_marker_is_not_stolen_by_the_next_entry():
    """Widening the search to the preceding gap is only safe because the
    surname AND year must match: entry N must not adopt N-1's marker."""
    from docxkit._cite_build import _own_bookmark
    from docxkit._cite_grammar import Reference

    gap = ('<w:bookmarkStart w:id="9" w:name="Jones2019"/>'
           '<w:bookmarkEnd w:id="9"/>')
    entry = ("<w:p><w:r><w:t>Smith, A. (2020). A title. Journal."
             "</w:t></w:r></w:p>")
    r = Reference(index=1, surname="Smith", year="2020",
                  text="Smith, A. (2020). A title. Journal.")
    assert _own_bookmark(entry, r, gap) is None


# -------------------------------------------- Word's 40-char name cap ----

_ORG = ("State Committee of the Republic of Uzbekistan on Statistics and "
        "United Nations Children's Fund (UNICEF)")


def test_a_minted_bookmark_name_fits_wordss_40_character_limit():
    """Word truncates a bookmark NAME to 40 chars when it saves, and does
    not retarget the anchors — every link to it dies silently.

    An institutional author mints a 90-character name, so the cap has to
    be applied when the name is created, not discovered when the author
    hands the file back (Parental Style: 4 entries, 8 dead anchors).
    """
    from docxkit._cite_build import WORD_BOOKMARK_LIMIT
    from docxkit.citations import link_all
    parts = _parts(f"The survey ({_ORG} 2022) covers households.",
                   "References",
                   f"{_ORG}. (2022). MICS 2021-2022. Tashkent.")
    link_all(parts)
    out = parts["word/document.xml"].decode("utf-8")

    names = re.findall(r'w:name="([^"]+)"', out)
    assert names, "no bookmark was minted"
    for n in names:
        assert len(n) <= WORD_BOOKMARK_LIMIT, f"{n!r} is {len(n)} chars"
    # and the link still points at a bookmark that exists
    for anchor in re.findall(r'w:anchor="([^"]+)"', out):
        assert anchor in names, f"{anchor!r} has no bookmark"


def test_the_in_text_partner_also_fits_the_limit():
    """The base name must leave room for the "txt" suffix: capping only
    the reference name would still ship a 41-character in-text one."""
    from docxkit._cite_build import WORD_BOOKMARK_LIMIT, _mint_name
    from docxkit._cite_grammar import Reference

    r = Reference(index=0, surname="A" * 200, year="2022",
                  text=f"{'A' * 200}. (2022).")
    name = _mint_name(r, set())
    assert len(name + "txt") <= WORD_BOOKMARK_LIMIT
    assert name.endswith("2022"), "the year must survive truncation"


def test_a_capped_name_still_dedupes_without_breaking_its_shape():
    """The _N collision suffix goes AFTER the year; trimming must eat the
    surname, never the year, or the name stops matching _KEY_SHAPE_RE and
    the audit can no longer pair it with its entry."""
    from docxkit._cite_audit import _KEY_SHAPE_RE
    from docxkit._cite_build import WORD_BOOKMARK_LIMIT, _mint_name
    from docxkit._cite_grammar import Reference

    taken: set[str] = set()
    r = Reference(index=0, surname="B" * 200, year="2022",
                  text=f"{'B' * 200}. (2022).")
    for _ in range(3):
        name = _mint_name(r, taken)
        taken.add(name)
        assert len(name + "txt") <= WORD_BOOKMARK_LIMIT
        km = _KEY_SHAPE_RE.match(name)
        assert km is not None, f"{name!r} lost its key shape"
        assert km.group(2) == "2022"
    assert len(taken) == 3, "collision suffixes did not stay unique"


# ---------------------------------------------------- span bounds --------


def test_wrap_visible_span_refuses_a_span_it_cannot_honour():
    """An inverted span used to pass silently and DUPLICATE text.

    The "before" and "after" slices overlapped, so the paragraph came
    out with a stretch of the manuscript repeated — no exception, and
    nothing in any report to say so.
    """
    from docxkit.citations import wrap_visible_span
    from docxkit.errors import AnchorError
    para = ('<w:p><w:r><w:t xml:space="preserve">Robots displace workers '
            "badly.</w:t></w:r></w:p>")
    for at, end in [(20, 5), (0, 999), (-1, 5), (31, 32)]:
        with pytest.raises(AnchorError, match="not inside"):
            wrap_visible_span(para, at, end, "Anchor")

    # the honest span still works
    out = wrap_visible_span(para, 0, 6, "Anchor")
    assert 'w:anchor="Anchor"' in out


# --------------------------------- limitations pinned, not fixed ---------


def test_the_reference_year_is_the_first_one_a_period_follows():
    """A KNOWN limitation, pinned deliberately.

    "Smith, J. Effects since 1990. (2020)." parses as 1990. Preferring
    a parenthesised year would fix it and break an entry whose TITLE
    carries a parenthesised range. Measured across the four live papers:
    296 entries, ZERO where the picked year differs from a
    parenthesised one — so the heuristic holds in practice and the
    'fix' is all risk. Change this only with a corpus that disagrees.
    """
    r = parse_reference("Smith, J. Effects since 1990. (2020). A title.")
    assert r is not None and r.year == "1990"


@pytest.mark.parametrize("text,seen", [
    ("(Smith 2020 and Jones 2021)", ["Jones"]),      # 'and' ends the scan
])
def test_multi_work_groups_the_grammar_does_not_split(text, seen):
    """Also pinned rather than fixed.

    A segment must end at its year, so a second work joined by "and" is
    not seen. Extending the grammar is exactly what this module's
    comments record as the source of its false positives, and this form
    occurs in none of the four live papers. Pinned so a future change is
    deliberate.

    The COMMA-separated year list used to be pinned here too, and was
    fixed instead when a fifth paper wrote it three times: see
    `test_a_year_LIST_is_one_citation_per_year`.
    """
    assert [c.surname for c in find_citations(text)] == seen


@pytest.mark.parametrize("text,seen", [
    # The three forms Aging_Well wrote, and the shapes around them.
    ("Sen (1985, 1992) distinguishes", [("Sen", "1985"), ("Sen", "1992")]),
    ("Rowe and Kahn (1987, 1997) nor",
     [("Rowe", "1987"), ("Rowe", "1997")]),
    ("(Sen 1985, 1992) and", [("Sen", "1985"), ("Sen", "1992")]),
    ("(Smith 2020a, 2020b)", [("Smith", "2020a"), ("Smith", "2020b")]),
    ("Sen (1985, 1999, 2009) sets out",
     [("Sen", "1985"), ("Sen", "1999"), ("Sen", "2009")]),
    # …and the neighbours a year list must not swallow.
    ("(Cameron et al. 2008, Roodman et al. 2019)",
     [("Cameron", "2008"), ("Roodman", "2019")]),
    ("(Sen 1999, 45) on capability", [("Sen", "1999")]),
    ("Maestas et al. (2023, p. 45) report", [("Maestas", "2023")]),
])
def test_a_year_LIST_is_one_citation_per_year(text, seen):
    """"Sen (1985, 1992)" is two works, and used to be NO citation.

    The group did not degrade to its first year — the whole match failed,
    so the name went missing with it. On Aging_Well that was 3 mentions
    covering 5 works: `refstyle` reported every one of them as an uncited
    entry, and `link_all` skipped them while reporting a clean sweep
    (2026-08-21).
    """
    assert [(c.surname, c.year) for c in find_citations(text)] == seen


@pytest.mark.parametrize("text,seen", [
    # A FOUR-DIGIT page is routine — AER, JPE and QJE volumes all run
    # past 1000 — and it reads exactly like a second year.
    ("Acemoglu and Robinson (2012, 1215) argue",
     [("Acemoglu", "2012")]),
    ("(Acemoglu and Robinson 2012, 1215)", [("Acemoglu", "2012")]),
    # …and the ordering rule is what tells them apart, so a real list
    # running forward is untouched even when the gap is a century.
    ("Sen (1899, 1992) and", [("Sen", "1899"), ("Sen", "1992")]),
    # the other direction: a locator that sorts AFTER the year
    ("Acemoglu (2012, 2500) argue", [("Acemoglu", "2012")]),
])
def test_a_four_digit_page_is_a_locator_and_not_another_work(text, seen):
    """It invented a citation of the year 1215: reported as
    `UNLINKED: "1215)"`, and counted in the `Mentions: X of Y linked`
    line, which is a completeness claim about the paper's links."""
    assert [(c.surname, c.year) for c in find_citations(text)] == seen


def test_the_locator_stays_inside_the_citations_span():
    """One citation, and its span is what the sentence says — the
    linker wraps that, and a span stopping at the year would leave
    ", 1215)" outside the link."""
    text = "Acemoglu and Robinson (2012, 1215) argue"
    (cite,) = find_citations(text)
    assert text[cite.start:cite.end] == "Acemoglu and Robinson (2012, 1215)"


def test_an_IGNORED_lead_is_STRIPPED_from_a_chain_not_dropped_with_it():
    """A caller that filtered on the surname dropped the whole citation,
    which takes the REAL half with it: "Surveys and ILOSTAT (2024)" then
    cites nothing, and ILOSTAT's entry is reported UNCITED — one false
    finding traded for another (Aging_Well, 2026-08-21)."""
    from docxkit.citations import resolve_lead

    text = "…national Labor Force Surveys and ILOSTAT (2024) data on…"
    (found,) = find_citations(text)
    assert found.authors == "Surveys and ILOSTAT"

    c = resolve_lead(found, ignore={"Surveys"})

    assert (c.authors, c.year) == ("ILOSTAT", "2024")
    assert text[c.start:c.end] == "ILOSTAT (2024)"
    # …and a lone ignored lead has no rest to keep: the caller's own
    # surname filter is what drops "Table (2020)".
    (only,) = find_citations("shown in Table (2020) format")
    assert resolve_lead(only, ignore={"Table"}).authors == "Table"

    # The contract is the ignore list's own — this word is NEVER an
    # author — so a paper that cites James March takes "March" off its
    # list. That is already true: filtering on the surname drops the
    # same citation whole. Pinned because the two answers differ.
    (chain,) = find_citations("March, Simon and Cyert (1958) argue")
    assert chain.surname == "March"
    assert resolve_lead(chain, ignore={"March"}).authors == "Simon and Cyert"


def test_a_year_LIST_gives_each_work_its_own_span():
    """The spans TILE the group; they never overlap.

    The reader clicks "1997" for the 1997 work, so each later year takes
    its own span rather than repeating the first's. Overlapping spans
    would be worse than the defect they fix: `link_all` wraps each one,
    and two hyperlinks over the same words is what `audit_links` reports
    as a DOUBLED LINK.
    """
    text = "Rowe and Kahn (1987, 1997) nor Sen (1985, 1992) alone"
    spans = [(c.start, c.end) for c in find_citations(text)]
    assert [text[a:b] for a, b in spans] == [
        "Rowe and Kahn (1987", "1997)", "Sen (1985", "1992)"]
    assert all(end <= nxt
               for (_, end), (nxt, _) in itertools.pairwise(spans))


@pytest.mark.parametrize("hoisted", [False, True])
def test_repair_plan_never_calls_a_LIVE_entry_debris(hoisted):
    """It proposed `delete_bookmark(doc, "BhlerNiederberger2022")` while
    both the entry and its citation were alive (2026-08-09). The
    evidence it used was the citation KEY, and the two spellings never
    meet: the bookmark was minted by an older strip-only stem, while
    "Bühler-Niederberger (2022)" keys as `bühlerniederberger_2022`.
    The reference LIST is the evidence the entry demanded.

    Both placements, because Word HOISTS a collapsed bookmark out of the
    paragraph it marks: reading the entry paragraph alone finds nothing
    and the false debris call comes straight back."""
    from docxkit.citations import repair_plan
    mark = ('<w:bookmarkStart w:id="4" w:name="BhlerNiederberger2022"/>'
            '<w:bookmarkEnd w:id="4"/>')
    entry = R("Bühler-Niederberger, D. (2022). Childhood studies. "
              "Routledge.")
    body = (FILLER
            + P(R("As Bühler-Niederberger (2022) shows, the gap is wide."))
            + P(R("References"))
            + (mark + P(entry) if hoisted else P(mark + entry)))
    plan = repair_plan(xml_parts(body))
    assert "BhlerNiederberger2022" in plan, plan
    assert "debris of a deleted entry" not in plan, plan
    assert "still in the list" in plan, plan


def test_repair_plan_still_calls_a_bookmark_with_no_entry_debris():
    """The other side: nothing in the list owns it, nothing cites it,
    and the plan must still say so — a guard that silences the true
    finding along with the false one is not a fix."""
    from docxkit.citations import repair_plan
    body = (FILLER
            + P(R("Prose that cites nobody."))
            + bookmark("Ghost2019", 30)
            + P(R("References"))
            + P(R("Aksoy, C. (2026). Working from home. JEP.")))
    plan = repair_plan(xml_parts(body))
    assert "Ghost2019" in plan and "debris" in plan.lower(), plan


def test_repair_plan_calls_BOTH_names_of_a_collided_entry_live():
    """Two entries under one key have two distinct bookmark names, and
    both belong to an entry still in the list — so neither is debris.

    The regression this pins is a refactor that nearly happened
    (2026-08-17). `repair_plan` walks the entries for their own
    bookmarks, and `_entry_names_from_document` does the same walk;
    sharing the latter looks obvious and is wrong, because it returns a
    mapping keyed by `r.key` and a collision keeps only the second name.
    The first would then be unaccounted for and proposed for DELETION —
    which is the 2026-08-09 failure the comment above that walk
    describes: a live reference proposed for deletion.
    """
    from conftest import make_parts, para, run

    from docxkit.citations import link_all, repair_plan

    parts = make_parts(
        para(run("Both (Kanbur 2007) agree."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal."))
        + para(run("Kanbur, A. (2007). Distribution. Another Journal.")))
    link_all(parts)

    plan = repair_plan(parts)

    for name in ("Kanbur2007", "Kanbur2007_2"):
        assert f'delete_bookmark(doc, "{name}"' not in plan, \
            f"{name} belongs to a live entry and was proposed for deletion"
    assert plan.count("not debris") == 2, plan


# --- what the first mutation run found (2026-08-17, 4.5 % survival) -----
#
# The repairs REFUSE rather than guess, and each refusal was asserted
# from one side only: the count that is too high, or the one that is too
# low, never both. A guard that fires in one direction and not the other
# is a repair that runs on a document it was never shown.

def test_delete_bookmark_refuses_a_pair_with_NO_end():
    """`count != 1`, not `> 1`. A Start with no End is what a half-done
    repair leaves behind, and removing the Start silently would balance
    the document by deleting the evidence."""
    from docxkit.citations import delete_bookmark

    xml = P('<w:bookmarkStart w:id="3" w:name="halfgone"/>' + R("text"))

    with pytest.raises(AnchorError, match="end of halfgone not unique"):
        delete_bookmark(xml, "halfgone")


def test_delete_bookmark_refuses_TWO_ends_with_one_id():
    """...and `< 1` is the same guard from the other side: Word writes a
    second End when a bookmark is copied, and removing both would close
    a bookmark that is still open somewhere else."""
    from docxkit.citations import delete_bookmark

    xml = P('<w:bookmarkStart w:id="3" w:name="twice"/>' + R("text")
            + '<w:bookmarkEnd w:id="3"/>' + R("more")
            + '<w:bookmarkEnd w:id="3"/>')

    with pytest.raises(AnchorError, match="not unique"):
        delete_bookmark(xml, "twice")


def _doubled(outer: str, inner: str, label: str = "Head. (2022)") -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            rf'<w:r><w:instrText>HYPERLINK \l "{outer}"</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:hyperlink w:anchor="{inner}">' + R(label)
            + "</w:hyperlink>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_remove_outer_field_needs_BOTH_halves_to_match():
    """`and`, not `or`. The repair is addressed by the PAIR — the stale
    outer target and the correct link inside it — because a manuscript
    holds several fields naming the same dead anchor. Matching either
    half alone unnests whichever field came first and leaves the
    doubled link the caller was pointing at."""
    from docxkit.citations import remove_outer_field

    other = P(_doubled("Stale2021txt", "Elsewhere2019txt", "Else (2019)"))

    with pytest.raises(AnchorError, match="0 fields"):
        remove_outer_field(other, "Stale2021txt", "Fresh2022txt")


def test_remove_outer_field_refuses_when_TWO_fields_match():
    """`!= 1`, not `< 1`. Two identical doubled links is the state a
    copy-pasted paragraph leaves, and repairing the first of them
    reports success while the second still clicks to the wrong place."""
    from docxkit.citations import remove_outer_field

    twice = P(_doubled("Stale2021txt", "Fresh2022txt")
              + R(" and again ")
              + _doubled("Stale2021txt", "Fresh2022txt"))

    with pytest.raises(AnchorError, match="2 fields"):
        remove_outer_field(twice, "Stale2021txt", "Fresh2022txt")


# `which == "only"` mutated to `>= "only"` or to `is "only"` survives and
# is EQUIVALENT: "first" sorts before "only" so the comparison agrees
# everywhere it is reached, and CPython interns the literal both sides
# come from.


# ------------------------------------------------- links nested in links ---
#
# `_cite_audit` measured 41.1 % real survival, the worst in the package,
# and 61 of its survivors are in `_doubled_links` — the walk that finds
# a link inside another link with a different target, where the click
# goes to the outer one. Two real shapes produced it: API10 P30, where
# two citations rendered as ONE link because the first field never
# ended, and LI7's WHO back-link nested inside a dead absolute-URL field
# Word had written around it.
#
# The walk keeps a STACK, and everything about the stack was free: which
# frame a close tag pops, whether a close pops the right KIND, and
# whether two links side by side look nested.

def _field(target: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            rf'<w:r><w:instrText> HYPERLINK \l "{target}" \h </w:instrText>'
            '</w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>')


_FIELD_END = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'


def _element(anchor: str, label: str = "x") -> str:
    return (_element_open(anchor) + f"<w:r><w:t>{label}</w:t></w:r>"
            + "</w:hyperlink>")


def _element_open(anchor: str) -> str:
    return f'<w:hyperlink w:anchor="{anchor}">'


def test_a_FIELD_inside_a_field_is_reported_with_both_targets():
    """API10 P30: the first field never ends, so the second citation is
    drawn inside it and both click through to the first."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("Finsel2023txt") + _field("Wohrmann2018txt")
            + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == [("Finsel2023txt", "Wohrmann2018txt")]


def test_an_ELEMENT_inside_a_field_is_reported():
    """LI7: the correct back-link, wrapped in a dead absolute-URL field
    Word had written around it."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("http://dead.example/old")
            + _element("WHO2019txt") + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == [("http://dead.example/old", "WHO2019txt")]


def test_the_SAME_target_twice_is_form_churn_and_stays_quiet():
    """Word rewrites a field into an element whenever the author saves,
    so a manuscript mid-round holds both forms of one link. That is not
    a doubled link."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("WHO2019txt") + _element("WHO2019txt")
            + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == []


def test_two_links_SIDE_BY_SIDE_are_not_nested():
    """The commonest paragraph in any of these papers — two citations in
    one sentence. A close tag that popped the wrong frame would report
    every later link as inside every earlier one."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("Smith2020txt") + _FIELD_END
            + _field("Jones2021txt") + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == []


def test_an_element_close_pops_the_ELEMENT_not_the_field_around_it():
    """`</w:hyperlink>` ends the innermost ELEMENT. Popping a field
    frame instead loses the outer field, and the citation that really is
    inside it goes unreported."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("Outer2020txt")
            + _element("First2019txt") + _element("Second2018txt")
            + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == [("Outer2020txt", "First2019txt"),
                                    ("Outer2020txt", "Second2018txt")]


def test_a_field_end_pops_the_INNERMOST_field():
    """Two fields open, one closes: the one still open is the OUTER, and
    a link after it is nested in that one and not in the closed one."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("Outer2020txt") + _field("Inner2019txt")
            + _FIELD_END + _element("Third2018txt") + _FIELD_END + "</w:p>")

    assert ("Outer2020txt", "Third2018txt") in _doubled_links(para)
    assert ("Inner2019txt", "Third2018txt") not in _doubled_links(para)


def test_an_element_close_pops_the_INNERMOST_element():
    """Nested element links are what the Kazenin spiral looked like on
    Parental Style — four deep before the audit caught it. Popping the
    outermost instead leaves the wrong frame open, and every link after
    it is attributed to a link that has already closed."""
    from docxkit.citations import _doubled_links

    para = ('<w:p><w:hyperlink w:anchor="Outer2020txt">'
            '<w:hyperlink w:anchor="Inner2019txt"><w:r><w:t>x</w:t></w:r>'
            "</w:hyperlink>" + _element("Third2018txt")
            + "</w:hyperlink></w:p>")

    found = _doubled_links(para)

    assert ("Outer2020txt", "Third2018txt") in found
    assert ("Inner2019txt", "Third2018txt") not in found


def test_a_link_with_no_target_yet_reports_nothing_about_itself():
    """A field frame carries no target until its instruction is read, so
    the frames above an inner link are asked for a target and the empty
    ones say nothing rather than reporting a pair with no outer."""
    from docxkit.citations import _doubled_links

    para = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            + _element("Inner2019txt") + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == []


# `open_fields = [f for f in stack if f[0] == "field"]` mutated to the
# whole stack survives, and is unreachable rather than untested: it
# would differ only where the innermost open frame at the moment an
# instruction is read is an ELEMENT, and a field's instruction always
# follows its own `begin`.


# ------------------------------------------- the audit's findings, as text --
#
# 106 of `_cite_audit`'s 188 survivors are in `_audit_findings`, and
# most of those are the MESSAGES: `¶{i + 1}`, `where(idx)`, `name[:-3]`,
# the cuts at 30 and 40. Every existing test asserts the CODE and that
# the name appears somewhere in the line, so the sentence a reader has
# to act on — which paragraph, which bookmark, what to do — was free.
#
# `docxkit citations PAPER.docx` prints exactly these lines, and a
# paragraph number one out sends the reader to the wrong place in a
# hundred-page manuscript.

def _messages(*paras: str) -> list[str]:
    issues, _report = audit_links(make_doc(*paras))
    return issues


def test_the_finding_names_the_bookmark_and_its_paragraph():
    """Five filler paragraphs come first, so the entry is ¶8 — one-based,
    as Word's own navigation counts."""
    msgs = _messages(P(R("Prose without the citation.")),
                     P(R("References")),
                     P(bookmark("Ghost2019", 30)
                       + R("Ghost, A. (2019). Unseen.")))

    assert ("REF WITHOUT CITE: 'Ghost2019' (¶8) in references and nothing "
            "points at it — no in-text hyperlink and no 'Ghost2019txt' "
            "marker") in msgs


def test_a_MISSING_REF_names_the_entry_bookmark_it_looked_for():
    """`name[:-3]` — the in-text mark is `<key>txt` and the entry it
    wants is `<key>`. Printing the mark twice tells the reader nothing
    about what is missing."""
    msgs = _messages(P(bookmark("Lost2020txt", 40)
                       + hfield("Lost2020", "Lost 2020")))

    assert ("MISSING REF: in-text citation 'Lost2020txt' (¶6) links to "
            "'Lost2020' but no reference bookmark exists") in msgs


def test_a_NO_BACK_LINK_names_the_in_text_bookmark():
    msgs = _messages(P(bookmark("Lost2020txt", 40)
                       + hfield("Lost2020", "Lost 2020")))

    assert ("NO BACK-LINK: in-text bookmark 'Lost2020txt' (¶6) has no "
            "reference back-link") in msgs


def test_a_BROKEN_LINK_quotes_the_LABEL_the_reader_will_see():
    """The label is how a person finds it on the page — the anchor is
    invisible in Word."""
    msgs = _messages(P(hfield("Nowhere2020", "Nowhere (2020)")))

    assert ("BROKEN LINK: hyperlink to 'Nowhere2020' (¶6, "
            '"Nowhere (2020)") — no such bookmark') in msgs


def test_a_BROKEN_LINK_label_is_cut_at_forty_characters():
    """A link that swallowed a sentence is exactly the case that
    produces a long label, and printing it whole buries the finding."""
    label = "Nowhere (2020) and a great deal of the sentence after it"
    msgs = _messages(P(hfield("Nowhere2020", label)))

    broken = next(m for m in msgs if m.startswith("BROKEN LINK"))
    assert f'"{label[:40]}"' in broken
    assert label[:41] not in broken


def test_a_DOUBLED_LINK_names_both_targets_and_the_paragraph():
    msgs = _messages(P(R("Prose. ")
                       + '<w:hyperlink w:anchor="Outer2020txt">'
                       + '<w:hyperlink w:anchor="Inner2019txt">'
                       + R("both") + "</w:hyperlink></w:hyperlink>"))

    assert ("DOUBLED LINK: 'Inner2019txt' is nested inside a link to "
            "'Outer2020txt' (¶6) — the click goes to the outer one") in msgs


def test_a_body_level_bookmark_is_located_as_BODY_not_a_paragraph():
    """Word hoists a collapsed bookmark out of the paragraph it marks,
    and the first audit round printed those as `fn` — which sent the
    API repair hunting in footnotes.xml for bookmarks that were never
    there."""
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("References"))
            + '<w:bookmarkStart w:id="30" w:name="Ghost2019"/>'
              '<w:bookmarkEnd w:id="30"/>'
            + P(R("Ghost, A. (2019). Unseen.")))

    issues, _report = audit_links(xml_parts(body))

    assert ("REF WITHOUT CITE: 'Ghost2019' (body) in references and "
            "nothing points at it — no in-text hyperlink and no "
            "'Ghost2019txt' marker") in issues


# --- one test per bucket of the repair plan (2026-08-19) ----------------
#
# citations re-measured at 32.2 % real survival, 27 of the 29 survivors
# inside `repair_plan` — and every one of them on a `f.kind == "..."`
# test, which is what a branch nothing ever reaches looks like from the
# outside. Three of the six damage classes had no fixture at all, so the
# routing could send a finding anywhere and the suite would agree.
#
# The plan is a script a person edits and runs against a real
# manuscript; a finding filed under the wrong heading is a wrong repair
# proposed with the confidence of a right one.

def _plan(*paras: str) -> str:
    from docxkit.citations import repair_plan
    filler = "".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                     for i in range(5))
    return repair_plan(xml_parts(filler + "".join(paras)))


def _bucket(plan: str, title: str) -> list[str]:
    """The lines under one `== heading`, without their indent."""
    keep, out = False, []
    for line in plan.splitlines():
        if line.startswith("== "):
            keep = title in line
        elif keep and line.startswith("  "):
            out.append(line.strip())
    return out


def test_a_broken_back_link_whose_citation_link_SURVIVES_is_a_wrap():
    """The commonest damage: the in-text bookmark went with an edit, so
    the entry's back-link points at nothing — but the citation still
    links to the entry, and that link is the anchor to wrap. Nothing has
    to be located by hand, which is what makes this its own bucket."""
    plan = _plan(
        P(R("As ") + hfield("Smith2020", "Smith (2020)") + R(" showed.")),
        P(R("References")),
        P(bookmark("Smith2020", 20,
                   hfield("Smith2020txt", "Smith, J. (2020). A paper."))))

    assert _bucket(plan, "wrap the surviving link") == [
        'wrap_link_in_bookmark(doc, "Smith2020", "Smith2020txt", bid)   '
        "# BROKEN LINK: hyperlink to 'Smith2020txt' "
        '(¶8, "Smith, J. (2020). A paper.") — no such bookmark']
    assert not _bucket(plan, "investigate")


def test_a_broken_back_link_with_NO_surviving_link_needs_the_citation_found():
    """Same broken back-link, but nothing in the prose links to the entry
    either — so there is no anchor to wrap and the repair has to start by
    locating the mention. Filed under wrap it would be handed to a helper
    that raises."""
    plan = _plan(
        P(R("As Smith (2020) showed.")),
        P(R("References")),
        P(bookmark("Smith2020", 20,
                   hfield("Smith2020txt", "Smith, J. (2020). A paper."))))

    assert not _bucket(plan, "wrap the surviving link")
    assert ('link_in_para(para, CITE_TEXT, "Smith2020") + wrap "Smith2020txt"'
            in "\n".join(_bucket(plan, "recreate the lost link")))


def test_a_back_link_whose_ENTRY_MARKER_is_gone_too_has_no_reading():
    """Neither conjunct holds: nothing links to `Smith2020` and no such
    bookmark exists, so both repairs would name an anchor that is not
    there. Which entry the back-link belonged to is a question for a
    person -- `investigate` is the honest answer, and a proposed
    `link_in_para` here is a wrong repair stated as a right one."""
    plan = _plan(
        P(R("As Smith (2020) showed.")),
        P(R("References")),
        P(hfield("Smith2020txt", "Smith, J. (2020). A paper.")))

    assert not _bucket(plan, "wrap the surviving link")
    assert not _bucket(plan, "recreate the lost link")
    assert any("BROKEN LINK" in ln for ln in _bucket(plan, "investigate"))


def test_a_link_to_a_name_that_is_no_back_link_at_all_is_INVESTIGATE():
    """`endswith("txt") AND base in anchors`, not `or`: every broken
    link's own target is in `anchors` by construction -- it is a link,
    and `anchors` is the set of everything linked to. Under `or` the
    first conjunct never has to hold, and a citation pointing at a
    deleted entry would be answered by wrapping it in a bookmark named
    after itself."""
    plan = _plan(
        P(R("As ") + hfield("Ghost2019", "Ghost (2019)") + R(" showed.")),
        P(R("References")),
        P(R("Smith, J. (2020). A paper.")))

    assert not _bucket(plan, "wrap the surviving link")
    assert any("BROKEN LINK: hyperlink to 'Ghost2019'" in ln
               for ln in _bucket(plan, "investigate"))


def test_a_marker_sitting_at_the_WRONG_entry_is_re_placed_not_deleted():
    """A paragraph move takes the `<w:p>` and nothing beside it, so a
    reordered reference list leaves body-level markers one entry off --
    13 of them on API10. The bookmark is not debris and the link to it
    is not broken; what is wrong is where it sits."""
    plan = _plan(
        P(R("As Smith (2020) and Zhang (2021) showed.")),
        P(R("References")),
        P(bookmark("Zhang2021", 21) + R("Smith, J. (2020). A paper.")),
        P(R("Zhang, Q. (2021). Another paper.")))

    assert _bucket(plan, "re-place") == [
        'delete_bookmark(doc, "Zhang2021") then marker_bookmark(doc, '
        "ENTRY_SIG, ...)   # MISPLACED MARKER: 'Zhang2021' sits at "
        '¶8 ("Smith, J. (2020). A paper.") but its entry is ¶9']
    assert not _bucket(plan, "debris")


def test_an_entry_nothing_links_to_but_the_paper_CITES_is_relinked():
    """`key_for(km.group(1), km.group(2))` -- the surname and the year,
    in that order. The key is what decides between "the work is cited,
    so this is a lost link" and "nothing mentions it, so the bookmark is
    debris", and the two proposals are opposites: one restores a link,
    the other deletes the anchor a link would need."""
    plan = _plan(
        P(R("As Zhang (2021) showed.")),
        P(R("References")),
        P(bookmark("Zhang2021", 21) + R("Zhang, Q. (2021). Another paper.")))

    assert not _bucket(plan, "debris")
    # Through the ENTRY reading now: ORPHAN REF and REF WITHOUT CITE
    # collapsed into one finding, and `repair_plan` files it from the
    # same evidence — same bucket, and the comment says why it is not
    # debris.
    assert ('link_in_para(para, CITE_TEXT, "Zhang2021")'
            in "\n".join(_bucket(plan, "recreate the lost link")))


def test_a_bookmark_for_a_work_the_paper_never_mentions_is_debris():
    """The other side of the same test, and the destructive one: no
    citation, no back-link bookmark, no entry owning it. The proposal
    still says VERIFY -- two of three Lutz diagnoses were wrong before
    the right one -- but it says delete."""
    plan = _plan(
        P(bookmark("Zhang2021", 21) + R("As Smith (2020) showed.")),
        P(R("References")),
        P(R("Smith, J. (2020). A paper.")),
        P(R("Wong, Q. (2021). Another paper.")))

    assert any('delete_bookmark(doc, "Zhang2021")' in ln
               for ln in _bucket(plan, "debris"))
    assert not _bucket(plan, "recreate the lost link")


def _counted(plan: str) -> tuple[int, int]:
    """(what the header promises, how many proposals are printed)."""
    head = re.match(r"REPAIR PLAN — (\d+) audit issue", plan)
    assert head, plan
    return int(head.group(1)), sum(
        1 for ln in plan.splitlines()
        if ln.startswith("  ") and not ln.startswith("== "))


def test_the_two_uncited_kinds_are_routed_APART_by_the_entry_state():
    """`ORPHAN REF` and `REF WITHOUT CITE` reach the same branch and part
    on `name in live`, and the repairs are opposite: one recreates a lost
    citation link, the other proposes DELETING the bookmark once a person
    confirms the entry text is gone. Mutation analysis, 2026-08-23: both
    `f.kind ==` comparisons here survived, because the routing was only
    ever driven with one of the two kinds at a time."""
    marked = _plan(
        P(bookmark("Ghost2019txt", 40) + R("As Ghost (2019) showed.")),
        P(R("References")),
        P(bookmark("Ghost2019", 30) + R("Ghost, A. (2019). Unseen.")))
    joined = chr(10).join(_bucket(marked, "recreate the lost link"))
    assert "first mention, then wrap Ghost2019txt" in joined

    unmarked = _plan(
        P(R("Prose that never cites it.")),
        P(R("References")),
        P(bookmark("Ghost2019", 30) + R("Ghost, A. (2019). Unseen.")))
    joined = chr(10).join(_bucket(unmarked, "recreate the lost link"))
    assert "the ENTRY is still in the list" in joined
    assert not _bucket(unmarked, "debris")


def test_EVERY_finding_reaches_a_bucket():
    """The header counts findings and the buckets are what a person
    works through, so the two have to agree or the plan is a list that
    silently omits an item. `Anhang` is the shape that broke it: a
    bookmark whose name does not parse as author+year gets a REF WITHOUT
    CITE that no reading fits, and it fell out of the loop unfiled --
    three issues promised, two printed (2026-08-19).

    Asserted as an INVARIANT rather than on that one name: any later
    branch that forgets its `else` fails here, whatever the damage class
    turns out to be."""
    plan = _plan(
        P(R("As Smith (2020) showed.")),
        P(R("References")),
        P(R("Smith, J. (2020). A paper.")),
        P(bookmark("Anhang", 33) + R("Appendix material.")))

    promised, printed = _counted(plan)
    assert promised == 2
    assert printed == promised
    assert any("REF WITHOUT CITE" in ln for ln in _bucket(plan, "investigate"))


@pytest.mark.parametrize("body", [
    # a clean-ish paper with one unlinked mention
    (P(R("As Smith (2020) showed.")) + P(R("References"))
     + P(R("Smith, J. (2020). A paper."))),
    # a stranded marker and two unlinked mentions
    (P(R("As Smith (2020) and Zhang (2021) showed.")) + P(R("References"))
     + P(bookmark("Zhang2021", 21) + R("Smith, J. (2020). A paper."))
     + P(R("Zhang, Q. (2021). Another paper."))),
    # a bookmark for a work no longer in the list
    (P(R("As Smith (2020) showed.")) + P(R("References"))
     + P(bookmark("Ghost1899", 71) + R("Smith, J. (2020). A paper."))),
])
def test_the_header_count_and_the_printed_lines_agree(body):
    promised, printed = _counted(_plan(body))
    assert printed == promised


def test_an_unlinked_MENTION_is_not_offered_a_field_repair():
    """`f.kind == "DOUBLED LINK"`, not `>=`: UNLINKED, EMPTY LINK and NO
    BACK-LINK all sort above it, and under `>=` each would be answered
    by `remove_outer_field` naming an outer target that does not exist.
    The last bucket is deliberately the one with no call in it."""
    plan = _plan(
        P(R("As Smith (2020) showed.")),
        P(R("References")),
        P(R("Smith, J. (2020). A paper.")))

    assert not _bucket(plan, "doubled link")
    assert any('UNLINKED: "Smith (2020)"' in ln
               for ln in _bucket(plan, "investigate"))


# --- the stack, three deep (2026-08-19) --------------------------------
#
# The fixtures above open at most two links at once, and a stack of two
# hides most of what a stack does: which frame a close pops, whether the
# scan reaches every frame, and whether a close of one KIND can pop the
# other. `"element" <= "field"` and `"field" >= "element"` are both true,
# so a comparison written the wrong way round pops the wrong frame and
# the walk goes on with the outer link still open.

def _instr(code: str) -> str:
    """A field code that is NOT a hyperlink — a page reference."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f"<w:r><w:instrText> {code} </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')


def test_two_ELEMENT_links_side_by_side_are_not_nested():
    """The field pair has this test and the element pair did not. With
    one frame on the stack the close scan is `range(0, -1, -1)`, and a
    stop of 0 examines nothing — the first link stays open and every
    link after it in the paragraph reads as inside it."""
    from docxkit.citations import _doubled_links

    para = "<w:p>" + _element("Smith2020txt") + _element("Jones2021txt") \
        + "</w:p>"

    assert _doubled_links(para) == []


def test_a_field_END_reaches_past_an_element_to_the_field_below_it():
    """Three frames, and the one to close is in the MIDDLE: a field, a
    second field inside it, an element inside that. The end has to skip
    the element and take the field under it — `stack[i][0] == "field"`,
    scanned one at a time from the top.

    A step of -2 skips the element and lands on the OUTER field, so the
    wrong link stays open; `<=` stops at the element, because "element"
    sorts before "field". Both leave the rest of the paragraph reported
    against a link that is not around it."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _field("Outer2020txt") + _field("Inner2019txt")
            + _element_open("Middle2018txt") + _FIELD_END   # closes Inner
            + _element("Last2017txt")
            + "</w:hyperlink>" + _FIELD_END + "</w:p>")

    assert _doubled_links(para) == [
        ("Outer2020txt", "Inner2019txt"),
        ("Outer2020txt", "Middle2018txt"),
        ("Inner2019txt", "Middle2018txt"),
        ("Outer2020txt", "Last2017txt"),
        ("Middle2018txt", "Last2017txt")]


def test_an_element_CLOSE_does_not_pop_a_field_inside_it():
    """`stack[i][0] == "element"`, and "field" >= "element" is true — so
    under `>=` the close takes the field it contains and leaves the
    element open. The field here never ends, which is API10 P30's own
    shape: everything after it is drawn inside it, and which link the
    reader actually clicks is the finding."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _element_open("Outer2020txt") + _field("Inner2019txt")
            + "</w:hyperlink>" + _element("Last2018txt") + "</w:p>")

    assert _doubled_links(para) == [("Outer2020txt", "Inner2019txt"),
                                    ("Inner2019txt", "Last2018txt")]


def test_a_field_code_that_is_not_a_hyperlink_closes_nothing():
    """`fld is None AND instr is None AND el_anchor is None` — the
    `</w:hyperlink>` token is the one with nothing in it. Under `or` an
    ordinary field code inside a link closes the link, and the citation
    that really is inside it goes unreported."""
    from docxkit.citations import _doubled_links

    para = ("<w:p>" + _element_open("Outer2020txt")
            + _instr("PAGEREF _Ref1") + _FIELD_END
            + _element("Inner2019txt") + "</w:hyperlink></w:p>")

    assert _doubled_links(para) == [("Outer2020txt", "Inner2019txt")]


def test_a_marker_is_owned_by_the_entry_of_ITS_OWN_year():
    """`r.year == year`, not `>=` or `<=`: an author with two works is
    the ordinary reference list, and a comparison that matches both
    leaves two candidates — which the function reads as "cannot tell"
    and answers None. The MISPLACED MARKER check then goes quiet on
    exactly the lists most likely to have one."""
    from docxkit._cite_audit import _marker_owner
    from docxkit.citations import references

    entries = references(["References",
                          "Smith, J. (2018). An earlier paper. JEP.",
                          "Smith, J. (2019). A later paper. AER."])

    owner = _marker_owner("Smith2018", entries)

    assert owner is not None and owner.year == "2018"


# --- the parts a bookmark can live in (2026-08-19) ---------------------
#
# `_audit_findings` reads the body and then the FOOTNOTES, and the
# footnote half was free: the loop that registers a note's bookmarks
# could be emptied, and the sentinel that says WHERE one was found could
# be any number, and every fixture in this file went on passing. A
# citation living in a footnote is the ordinary case in these papers —
# the retracted backlog entry of 2026-08-19 was exactly that, a
# back-link reported missing because the check looked in one part.

def _with_note(body: str, note_body: str) -> dict[str, bytes]:
    from conftest import make_parts, notes
    return make_parts(
        body, footnotes=notes("footnotes",
                              f'<w:footnote w:id="2"><w:p>{note_body}'
                              "</w:p></w:footnote>"))


def test_a_bookmark_defined_in_a_FOOTNOTE_answers_a_body_link():
    """The loop that registers them, emptied, makes every link into the
    notes read as dangling — and the repair for a dangling link is to
    delete the anchor, which is the one thing that would really break
    it."""
    parts = _with_note(
        P(R("As shown ") + hfield("Moran1950txt", "Moran (1950)") + R(".")),
        bookmark("Moran1950txt", 9, R("Moran, P. (1950).")))

    issues, _stats = audit_links(parts)

    assert not [i for i in issues if i.startswith("BROKEN LINK")]


def test_a_finding_in_a_FOOTNOTE_says_fn_rather_than_a_paragraph():
    """The sentinel is -2 and the printed answer is "fn". The first
    audit round printed body-level bookmarks as "fn" too, and the repair
    went hunting in footnotes.xml for bookmarks that were never there —
    so the two have their own numbers and their own words."""
    parts = _with_note(P(R("Nothing links to it.")),
                       bookmark("Ghost1899", 9, R("A note.")))

    (found,) = [i for i in audit_links(parts)[0] if "Ghost1899" in i]

    assert "(fn)" in found, found


def test_a_BROKEN_link_in_a_footnote_says_fn_where_it_is():
    """The link's own sentinel, which is what a finding ABOUT the link
    prints. A dangling link is repaired by opening the part it is in,
    and "¶-1" sends a person to the top of the body."""
    parts = _with_note(
        P(R("Body prose.")),
        R("See ") + hfield("Ghost1899txt", "Ghost (1899)"))

    (broken,) = [i for i in audit_links(parts)[0]
                 if i.startswith("BROKEN LINK")]

    assert "(fn," in broken, broken


def test_a_LINK_in_a_footnote_counts_as_a_link_to_its_target():
    """The other half: a citation whose only mention is in a note still
    links its entry, and an entry linked from a note is not an ORPHAN
    REF."""
    parts = _with_note(
        P(R("Body prose.")) + P(R("References"))
        + P(bookmark("Moran1950", 20) + R("Moran, P. (1950). A paper. JRSS.")),
        R("See ") + hfield("Moran1950", "Moran (1950)"))

    issues, _stats = audit_links(parts)

    assert not [i for i in issues if i.startswith("ORPHAN REF")]


def test_an_Eq_bookmark_is_an_EQUATION_mark_and_not_a_reference_one():
    """`not n.startswith("_") and n.startswith("Eq")`: an equation
    anchor is not a reference marker, and reading it as one reports
    every numbered equation in the paper as an entry nothing cites."""
    body = (P(R("Body prose.")) + P(R("References"))
            + P(bookmark("Eq3", 30) + R("(3)")))

    issues, _stats = audit_links(xml_parts(body))

    assert not [i for i in issues if "Eq3" in i]


def test_a_SUFFIXED_year_in_the_list_is_not_a_missing_entry():
    """`r.year[:4]`: the entry is dated 2013a and the bookmark is
    `Foster2013`, so the years compared have to be the same four
    characters. Under `[:5]` the list's own year never matches a
    bookmark's and every marker in a paper that uses suffixes reads as
    STALE — the finding whose repair is to delete the anchor."""
    body = (P(R("Cited (Foster et al. 2013a).")) + P(R("References"))
            + P(bookmark("Foster2013", 20)
                + R("Foster, J. (2013a). A paper. JRSS.")))

    issues, _stats = audit_links(xml_parts(body))

    assert not [i for i in issues if i.startswith("STALE BOOKMARK")]


def test_an_entry_nothing_cites_is_not_reported_as_a_CITE_WITHOUT_REF():
    """`cited_keys - ref_marks.keys()`, not the symmetric difference:
    the two findings are opposites — one says the text cites a work the
    list does not carry, the other says the list carries a work nothing
    cites — and `^` reports every uncited entry as both."""
    body = (P(R("Body prose with no citations.")) + P(R("References"))
            + P(bookmark("Moran1950", 20)
                + R("Moran, P. (1950). A paper. JRSS.")))

    issues, _stats = audit_links(xml_parts(body))

    assert not [i for i in issues if i.startswith("CITE WITHOUT REF")]
    assert [i for i in issues if i.startswith("REF WITHOUT CITE")]


def test_unlink_takes_the_bookmarkEnd_of_ITS_OWN_bookmark_only():
    """`count=1`. A bookmark id is unique in a healthy document and this
    package has a lint check for the case where it is not, because Word
    merges revisions that share one. With two ends carrying the same id,
    removing both leaves the OTHER bookmark unclosed — a start with no
    end, which is what Word calls unreadable content and what
    `citations.integrity` reports."""
    xml = ('<w:document><w:body>'
           '<w:p><w:bookmarkStart w:id="4" w:name="bookmark=id.abc123"/>'
           '<w:bookmarkEnd w:id="4"/>'
           "<w:r><w:t>Smith, J. (2020). Title.</w:t></w:r></w:p>"
           '<w:p><w:bookmarkStart w:id="4" w:name="Kept2020"/>'
           '<w:bookmarkEnd w:id="4"/>'
           "<w:r><w:t>Jones, A. (2021). Title.</w:t></w:r></w:p>"
           "</w:body></w:document>")
    from docxkit import citations as C

    out, _links, marks = C.unlink_by_anchor(xml, r"^bookmark=id\.")

    assert marks == 1
    assert 'w:name="Kept2020"' in out
    assert out.count("<w:bookmarkEnd") == 1, "the other bookmark's end went"


def test_a_prose_line_read_as_an_entry_names_its_paragraph():
    """`¶{r.index + 1}` — one-based, because that is how Word counts,
    and the whole finding is WHICH line the reference block ran on to.
    The message is advisory (the rule cannot hold across scripts), so
    the paragraph number is the only actionable thing in it."""
    from docxkit._cite_build import _prose_entries
    from docxkit.citations import references

    texts = ["Body prose.", "References",
             "Smith, J. (2020). A real entry. JEP.",
             "The authors declare no competing interests. (2024). Note."]
    entries = references(texts)

    (note,) = _prose_entries(entries)

    assert note.startswith("¶4 is filed under 'The authors declare")


# --- the ghost hyperlink, in the repair helpers (2026-08-19) -----------
#
# S1. `<w:hyperlink w:anchor="X"/>` is an empty ghost Word leaves behind,
# and `_xml._HYPERLINK_EL_RE` carries a `(?<!/)>` guard because pairing
# one with the next `</w:hyperlink>` downstream spanned 14 paragraphs on
# Parental Style. The two repair helpers were written without it.

def test_a_GHOST_hyperlink_is_not_a_link_to_wrap():
    """The bookmark would otherwise open at the ghost and close at the
    next link's close tag — around the prose between them and around
    another work's citation, with no exception and nothing in any report
    to say so. A back-link to that anchor then lands on the wrong
    sentence, and the audit calls it healthy because the bookmark
    exists."""
    from docxkit.citations import wrap_link_in_bookmark
    from docxkit.errors import AnchorError

    para = ('<w:p><w:hyperlink w:anchor="Smith2020"/>'
            "<w:r><w:t>Prose between them.</w:t></w:r>"
            '<w:hyperlink w:anchor="Jones2021"><w:r><w:t>Jones 2021</w:t>'
            "</w:r></w:hyperlink><w:r><w:t> tail.</w:t></w:r></w:p>")

    with pytest.raises(AnchorError, match="no link to Smith2020"):
        wrap_link_in_bookmark(para, "Smith2020", "Smith2020txt", 9)


def test_a_REAL_link_beside_a_ghost_still_wraps():
    """The other half: a ghost in the paragraph must not stop the repair
    of the link that is really there."""
    from docxkit.citations import wrap_link_in_bookmark

    para = ('<w:p><w:hyperlink w:anchor="Ghost1899"/>'
            '<w:hyperlink w:anchor="Smith2020"><w:r><w:t>Smith 2020</w:t>'
            "</w:r></w:hyperlink></w:p>")

    out = wrap_link_in_bookmark(para, "Smith2020", "Smith2020txt", 9)

    assert out.index('w:name="Smith2020txt"') < out.index('"Smith2020"')
    assert out.index("</w:hyperlink>") < out.index("<w:bookmarkEnd")
    assert 'w:anchor="Ghost1899"/>' in out, "the ghost is left alone"


def test_remove_outer_field_keeps_the_REAL_inner_link_not_the_ghost():
    """The same guard on the inner link `remove_outer_field` keeps. A
    ghost carrying the inner anchor sits before the real one — Word
    leaves both when it rewrites a link it has already emptied — and
    without the guard the kept span runs from the GHOST to the real
    link's close tag, so the unwrapped result carries an empty
    hyperlink element beside the good one."""
    from docxkit.citations import remove_outer_field

    body = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            r'<w:r><w:instrText>HYPERLINK \l "Stale2021txt"</w:instrText>'
            '</w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:hyperlink w:anchor="Fresh2022txt"/>'
            '<w:hyperlink w:anchor="Fresh2022txt"><w:r><w:t>Head. (2022)'
            "</w:t></w:r></w:hyperlink>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')

    out = remove_outer_field("<w:p>" + body + "</w:p>",
                             "Stale2021txt", "Fresh2022txt")

    assert out.count("<w:hyperlink") == 1, out
    assert "Head. (2022)" in out


def test_the_link_that_CLOSES_is_the_innermost_one_still_open():
    """`range(len(stack) - 1, -1, -1)` — the walk that finds which open
    link a `fldChar end` belongs to, and it runs BACKWARDS because the
    innermost is the one that closes.

    Two nested fields cannot see it: with a stack of two the correct
    start (index 1) and a halved one (2 >> 1) are the same index. Three
    can, and three is not exotic — API10 nested a field inside a field
    inside a field where two `end` chars had gone missing.

    Closing the middle link instead leaves it open and the inner one
    closed, so everything after is reported against the wrong ancestor:
    the report names a link the click does not go to."""
    fld = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           r'<w:r><w:instrText>HYPERLINK \l "{a}"</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    body = P(fld.format(a="OuterA") + R("a ")
             + fld.format(a="MidB") + R("b ")
             + fld.format(a="InnerC") + R("c ") + end
             + '<w:hyperlink w:anchor="D">' + R("d") + "</w:hyperlink>"
             + end + end)
    parts = {"word/document.xml": ("<w:document><w:body>" + body
                                   + "</w:body></w:document>").encode()}

    issues, _ = audit_links(parts)

    about_d = [i for i in issues if i.startswith("DOUBLED LINK: 'D'")]
    named = {t for t in ("OuterA", "MidB", "InnerC")
             if any(f"'{t}'" in i for i in about_d)}

    assert named == {"OuterA", "MidB"}, about_d


# --- the _cite_audit run of 2026-08-20: 11.2 %, the package's worst -----

from conftest import make_parts, note, notes, para, run  # noqa: E402


def _audit(body: str, **extra: bytes) -> list[str]:
    parts = make_parts(body)
    parts.update(extra)
    return audit_links(parts)[0]


def test_a_finding_says_WHICH_note_store_it_is_in():
    """"(fn)" and "(en)" are what a person does the repair from: an
    anchor reported as "fn" that lives in endnotes.xml sends them into
    a part that does not hold it.

    Ten mutants sat on the two constants behind those labels — the
    sentinel index for each store and the map from it to the word — and
    every one of them is invisible to a test that only counts findings.
    The order is part of it too: the sentinels are negative so a note's
    findings sort before ¶1, and endnotes' below footnotes'."""
    body = (para(run("A claim (Card 1999).")) + para(run("References"))
            + para(run("Card, D. (1999). Education. Amsterdam: Elsevier.")))
    marked = ('<w:bookmarkStart w:id="7" w:name="{name}"/>'
              + run("{label}") + '<w:bookmarkEnd w:id="7"/>')

    # The endnote's name sorts AFTER the footnote's, so the order below
    # is the one the sentinels give and not the alphabetical one the
    # sort key mutates to.
    issues = _audit(
        body,
        **{"word/footnotes.xml": notes("footnotes", note(
            marked.format(name="Alpha2001txt", label="Alpha (2001)"),
            2)).encode(),
           "word/endnotes.xml": notes("endnotes", note(
               marked.format(name="Zulu2002txt", label="Zulu (2002)"), 3,
               "endnote")).encode()})

    assert [i for i in issues if "NO BACK-LINK" in i] == [
        "NO BACK-LINK: in-text bookmark 'Zulu2002txt' (en) has no reference "
        "back-link",
        "NO BACK-LINK: in-text bookmark 'Alpha2001txt' (fn) has no reference "
        "back-link"], issues


def test_the_findings_come_in_DOCUMENT_order_not_alphabetical():
    """The report is read top to bottom against the document, so the
    sort is by paragraph. Sorted by NAME it still contains everything
    and still reads as a list — which is why nothing noticed: the
    fixtures all had one finding, or names already in document order."""
    body = (para(run("A claim (Zed 1999) and (Abe 1998)."))
            + para(run("References"))
            + para('<w:bookmarkStart w:id="1" w:name="Zed1999"/>'
                   + run("Zed, Z. (1999). First entry. J.")
                   + '<w:bookmarkEnd w:id="1"/>')
            + para('<w:bookmarkStart w:id="2" w:name="Abe1998"/>'
                   + run("Abe, A. (1998). Second entry. J.")
                   + '<w:bookmarkEnd w:id="2"/>'))

    issues = _audit(body)

    named = [i.split("'")[1] for i in issues
             if i.startswith("REF WITHOUT CITE")]
    assert named == ["Zed1999", "Abe1998"], issues


def test_a_STALE_bookmark_does_not_end_the_walk():
    """`continue`: the stale finding replaces the orphan check for THAT
    key, not for the rest of the document. A `break` there reports the
    first stale marker and stops — and a document with one stale marker
    is exactly the document that has others."""
    body = (para(run("A claim (Card 1999)."))
            + para(run("References"))
            + para('<w:bookmarkStart w:id="1" w:name="Aaa2012"/>'
                   + run("Some prose the marker was hoisted into.")
                   + '<w:bookmarkEnd w:id="1"/>')
            + para('<w:bookmarkStart w:id="2" w:name="Card1999"/>'
                   + run("Card, D. (1999). Education. Amsterdam: Elsevier.")
                   + '<w:bookmarkEnd w:id="2"/>'))

    issues = _audit(body)

    assert any(i.startswith("STALE BOOKMARK: 'Aaa2012'") for i in issues)
    assert any(i.startswith("REF WITHOUT CITE: 'Card1999'")
               for i in issues), issues


def test_a_marker_NO_ENTRY_owns_does_not_end_the_misplacement_walk():
    """The same shape one loop down. A bookmark that does not parse as
    surname+year belongs to no entry and is skipped — and a document
    carrying one is not a document without misplaced markers. "notakey"
    is first here because the walk takes them in definition order."""
    body = (para(run("A claim (Card 1999) and (Buys 2012)."))
            + para(run("References"))
            + para('<w:bookmarkStart w:id="1" w:name="notakey"/>'
                   '<w:bookmarkStart w:id="2" w:name="Buys2012"/>'
                   + run("Card, D. (1999). Education. Amsterdam: Elsevier.")
                   + '<w:bookmarkEnd w:id="1"/><w:bookmarkEnd w:id="2"/>')
            + para('<w:bookmarkStart w:id="3" w:name="Card1999"/>'
                   + run("Buys, L. (2012). Loneliness. J, 1: 1-10.")
                   + '<w:bookmarkEnd w:id="3"/>'))

    issues = _audit(body)

    assert [i for i in issues if i.startswith("MISPLACED MARKER")] == [
        'MISPLACED MARKER: \'Buys2012\' sits at ¶3 ("Card, D. (1999). '
        'Education. Am") but its entry is ¶4',
        'MISPLACED MARKER: \'Card1999\' sits at ¶4 ("Buys, L. (2012). '
        'Loneliness. J") but its entry is ¶3'], issues


def test_a_year_SUFFIX_is_not_part_of_the_year():
    """`m.group(2)[:4]`. A 2020a/2020b pair is how a reference list tells
    two works of one author apart, and the entry's own year carries the
    letter too — so comparing five characters against four never
    matches, and every suffixed marker in the document reads as a work
    that has been deleted from the list."""
    body = (para(run("A claim (Card 1999a)."))
            + para(run("References"))
            + para('<w:bookmarkStart w:id="2" w:name="Card1999a"/>'
                   + run("Card, D. (1999a). Education. Amsterdam: Elsevier.")
                   + '<w:bookmarkEnd w:id="2"/>'))

    assert not [i for i in _audit(body) if i.startswith("STALE BOOKMARK")]


def test_a_HYPERLINK_instruction_inside_an_element_link_is_not_its_field():
    """`f[0] == "field"`, which an ordering comparison reads as true for
    "element" as well. Word leaves an instruction inside an element link
    behind when a field is converted, and taking the element for the
    field it is not writes the instruction's target over the anchor a
    reader clicks — then reports the pair as a doubled link."""
    from docxkit._cite_audit import _doubled_links

    para_xml = ('<w:p><w:hyperlink w:anchor="Outer2020">'
                + run("Outer")
                + r'<w:r><w:instrText>HYPERLINK \l "Inner2021"'
                "</w:instrText></w:r>"
                + run(" tail") + "</w:hyperlink></w:p>")

    assert _doubled_links(para_xml) == []


def test_the_element_link_that_closes_is_the_INNERMOST_one():
    """The walk runs from the top of the stack down, and starting it
    half way — `len(stack) >> 1` — closes an outer link instead. Two
    open links cannot see it (half of two is one, which is still the
    top), and the difference only shows in what is open AFTERWARDS: the
    next link nests inside the one that should have closed.

    Three deep is a real shape: a field around a back-link around a
    cross-reference is what Word leaves after two rounds of repair."""
    from docxkit._cite_audit import _doubled_links

    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             r'<w:r><w:instrText>HYPERLINK \l "F1"</w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
    para_xml = ("<w:p>" + field + run("f")
                + '<w:hyperlink w:anchor="E1">' + run("e1")
                + '<w:hyperlink w:anchor="E2">' + run("e2") + "</w:hyperlink>"
                + '<w:hyperlink w:anchor="E3">' + run("e3") + "</w:hyperlink>"
                + run(" more") + "</w:hyperlink>"
                + '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')

    assert _doubled_links(para_xml) == [
        ("F1", "E1"), ("F1", "E2"), ("E1", "E2"), ("F1", "E3"), ("E1", "E3")]


# Argued rather than pinned, from the same run:
#
# * both reverse walks written `range(len(stack) - 1, -2, -1)` (and `~1`,
#   which is the same -2). The extra index is `stack[-1]`, the element
#   the walk ALREADY checked first, and it is only reached when nothing
#   matched — so the repeat cannot match either. The walk deletes and
#   breaks on a match, so the list never moves under it.
# * `stack[i][0] == "field"` and `== "element"` as `is`, and the first
#   as `>=`. The kinds are two literals written in this module, and
#   "element" sorts before "field".
# * `owners[0]` written `owners[-1]`, under `if len(owners) == 1`.


FILLER = "".join(para(run(f"Filler paragraph {i}.")) for i in range(6))
TWO_ENTRIES = (para(run("References"))
               + para('<w:bookmarkStart w:id="1" w:name="Card1999"/>'
                      + run("Card, D. (1999). Education. Elsevier.")
                      + '<w:bookmarkEnd w:id="1"/>')
               + para(run("Buys, L. (2012). Loneliness. J, 1: 1-10.")))


def _unlinked(body: str) -> list[str]:
    return [i for i in _audit(body) if i.startswith("UNLINKED")]


def test_the_scan_skips_the_first_FIVE_paragraphs_and_no_more():
    """`i < 5` — a title page, an author block, an abstract heading: the
    front matter is where a "Smith (2020)" is a name rather than a
    citation. Written `!= 5` the scan skips everything EXCEPT paragraph
    six, which is the same silence for every real document and reports
    nothing at all where the fixtures put their prose."""
    body = (FILLER + para(run("A claim (Card 1999) and (Buys 2012)."))
            + TWO_ENTRIES)

    found = _unlinked(body)

    assert len(found) == 2, found
    assert all("(¶7)" in i for i in found), found


@pytest.mark.parametrize("prose,label", [
    ("(Card 1999)", "Card (1999)"),      # parenthetical cite, narrative label
    ("Card (1999)", "Card 1999"),        # narrative cite, parenthetical label
])
def test_a_link_LABEL_in_ANOTHER_spelling_counts_as_the_citation(prose,
                                                                 label):
    """The fallback for a document whose bookmarks are not key-shaped: a
    citation counts as linked if some link's LABEL carries it, in the
    prose's own spelling or in either of the two the pass builds —
    "author year" and "author (year)". A paper writes both forms and
    links one of them.

    The label sits in the SAME paragraph as an unlinked work, so the
    `continue` that skips the labelled citation has something after it
    to lose. `cite_x` as the anchor on purpose: a key-shaped one is
    answered by the marker walk above and never reaches this line."""
    body = (FILLER
            + para(run(f"As {prose} shows, and (Buys 2012) too. ")
                   + '<w:hyperlink w:anchor="cite_x">'
                   + run(label) + "</w:hyperlink>" + run(" appears again."))
            + TWO_ENTRIES)

    assert [i.split('"')[1] for i in _unlinked(body)] == ["Buys 2012"], \
        _unlinked(body)


@pytest.mark.parametrize("prose", [
    "As (April 2020) and (Buys 2012) show",     # a lead the grammar ignores
    "As Card (1999) shows, and (Buys 2012) too",             # linked already
])
def test_a_citation_the_scan_SKIPS_does_not_end_the_paragraph(prose):
    """Three `continue`s in one loop — an ignored lead, a work already
    linked, a label that carries the citation — and each of them, as a
    `break`, drops every mention AFTER it in that paragraph. A sentence
    citing two works is the ordinary case, and the second is the one
    that goes unreported."""
    body = (FILLER
            + para(run("As ") + '<w:hyperlink w:anchor="Card1999">'
                   + run("Card 1999") + "</w:hyperlink>" + run(" and more."))
            + para(run(f"{prose}."))
            + TWO_ENTRIES)

    assert [i for i in _unlinked(body) if "Buys" in i], _unlinked(body)


def test_a_cite_mark_with_NO_reference_bookmark_is_reported():
    """`cited_keys - ref_marks.keys()`: an in-text bookmark whose
    reference partner is gone. The loop over it was mutated to run over
    nothing at all and no test noticed, which means the check had never
    fired in this file."""
    body = (para(run("As ")
                 + '<w:bookmarkStart w:id="3" w:name="Nobody1899txt"/>'
                 + run("Nobody (1899)") + '<w:bookmarkEnd w:id="3"/>'
                 + run(" says."))
            + TWO_ENTRIES)

    assert [i for i in _audit(body)
            if i.startswith("CITE WITHOUT REF")] == [
        "CITE WITHOUT REF: 'Nobody1899' cited in text but no reference "
        "bookmark"]


def test_a_STALE_key_is_not_ALSO_reported_as_uncited():
    """`continue`: a marker whose entry is gone is reported once, as
    stale, and the uncited check skips it — but only it. The keys are
    walked in sorted order, so a stale one that sorts first ends the
    walk under `break` and every genuinely uncited marker after it goes
    unreported."""
    body = (para(run("A claim (Card 1999)."))
            + para(run("References"))
            + para('<w:bookmarkStart w:id="1" w:name="Aaa2012"/>'
                   + run("Prose the marker was hoisted into.")
                   + '<w:bookmarkEnd w:id="1"/>')
            + para('<w:bookmarkStart w:id="2" w:name="Zzz1999"/>'
                   + run("Card, D. (1999). Education. Elsevier.")
                   + '<w:bookmarkEnd w:id="2"/>'))

    issues = _audit(body)

    assert [i.split("'")[1] for i in issues
            if i.startswith("REF WITHOUT CITE")] == ["Zzz1999"], issues
    assert any(i.startswith("STALE BOOKMARK: 'Aaa2012'") for i in issues)


def test_a_BODY_LEVEL_marker_is_placed_by_the_entry_below_it():
    """Word hoists a marker out of its paragraph on save, so it sits
    between two of them and belongs to neither by offset. The fallback
    takes the next entry at or after it — an ordering comparison, and
    equality there finds nothing at all, which turns every misplaced
    body-level marker (13 of them on API10) into silence."""
    body = (para(run("A claim (Card 1999) and (Buys 2012)."))
            + para(run("References"))
            + para(run("Card, D. (1999). Education. Elsevier."))
            + '<w:bookmarkStart w:id="1" w:name="Card1999"/>'
              '<w:bookmarkEnd w:id="1"/>'
            + para(run("Buys, L. (2012). Loneliness. J, 1: 1-10.")))

    assert [i for i in _audit(body)
            if i.startswith("MISPLACED MARKER")] == [
        'MISPLACED MARKER: \'Card1999\' sits at ¶4 ("Buys, L. (2012). '
        'Loneliness. J") but its entry is ¶3']


# Argued rather than pinned, from the same run:
#
# * `paras[i].start() <= pos < paras[i].end()`, as `<`, `<=` on the
#   right, `!=` and `is not`. `pos` is where `w:name="…"` starts, and a
#   paragraph begins with its own `<w:p>` tag — so `pos` is never the
#   paragraph's first offset nor its last, and every one of those
#   readings agrees on the paragraphs that exist.
# * `at.index != owner.index` written `is not`: two paragraph indices,
#   and CPython hands out one object per integer below 257. A document
#   with 257 reference entries would part them; none of these papers
#   has 40.


# `citations.py` itself measured 5.6 % (6/107) the same day, and all six
# are argued:
#
# * the four `f.kind == "…"` comparisons in `repair_plan`, read as `<=`
#   or `>=`. The kinds are the literals `_Finding` is built with, and at
#   each branch the ones that can still reach it sort the same way
#   round: nothing the audit emits sorts at or below "BROKEN LINK" but
#   itself, and the pair inside the ORPHAN/REF-WITHOUT-CITE arm is "O"
#   against "R".
# * `print("=" * 60)` at 59 and 61 — the width of a rule, which is the
#   cosmetic third of the three kinds CONTRIBUTING names.


# --------------------------------- a paper wired under ANOTHER scheme ---
#
# Read on AFI's finished manuscript, 2026-08-21: 104 entry bookmarks,
# every one of them `ref_<surname>_<year>`, and the audit could resolve
# none of them — so no work counted as linked and two live citations
# were reported UNLINKED on a paper that links both.


def _foreign(body: str):
    from conftest import make_parts
    return make_parts(body)


_FOREIGN_ENTRIES = (
    '<w:bookmarkStart w:id="7" w:name="ref_kanbur_2007"/>'
    '<w:bookmarkEnd w:id="7"/>')


def test_a_citation_linked_under_a_FOREIGN_scheme_is_not_UNLINKED():
    from conftest import make_parts, para, run

    linked = ('<w:hyperlink w:anchor="ref_kanbur_2007"><w:r>'
              "<w:t>Kanbur (2007)</w:t></w:r></w:hyperlink>")
    body = (para(run("A point.")) + para(run("Prose.")) + para(run("More."))
            + para(run("Still more.")) + para(run("And more."))
            + para(run("As "), linked, run(" shows, it rises."))
            + para(run("References")) + _FOREIGN_ENTRIES
            + para(run("Kanbur, R. (2007). Poverty. Journal, 1(1): 45-48.")))

    issues, _stats = audit_links(make_parts(body))

    assert not [m for m in issues if m.startswith("UNLINKED")], issues


def test_a_MENTION_side_marker_in_prose_is_not_misplaced():
    """`cite_<surname>_<year>` is the back-link target and belongs at the
    MENTION. Reading it as the entry's marker reported six of AFI's as
    misplaced, every one correctly placed."""
    from conftest import make_parts, para, run

    # TWO entries, and the mention is of the SECOND: the check's fallback
    # for a body-level marker is "the next entry down", which for a
    # marker in prose is the FIRST entry — so a one-entry fixture cannot
    # tell a skipped marker from a marker whose owner it guessed right.
    body = (para(run("A point.")) + para(run("Prose.")) + para(run("More."))
            + para(run("Still more.")) + para(run("And more."))
            + '<w:bookmarkStart w:id="3" w:name="cite_ravallion_2016"/>'
              '<w:bookmarkEnd w:id="3"/>'
            + para(run("As Ravallion (2016) shows, it rises."))
            + para(run("References")) + _FOREIGN_ENTRIES
            + para(run("Kanbur, R. (2007). Poverty. Journal, 1(1): 45-48."))
            + para(run("Ravallion, M. (2016). Economics. OUP.")))

    issues, _stats = audit_links(make_parts(body))

    assert not [m for m in issues if m.startswith("MISPLACED")], issues


def test_a_FOREIGN_entry_marker_one_entry_early_is_still_reported():
    """The check exists for exactly this: a reorder takes the `w:p` and
    leaves the body-level marker behind, so it strands one entry up. Five
    of AFI's 104 are in that state on the finished paper."""
    from conftest import make_parts, para, run

    body = (para(run("A point (Kanbur 2007).")) + para(run("References"))
            + '<w:bookmarkStart w:id="7" w:name="ref_ravallion_2016"/>'
              '<w:bookmarkEnd w:id="7"/>'
            + para(run("Kanbur, R. (2007). Poverty. Journal, 1(1): 45-48."))
            + para(run("Ravallion, M. (2016). Economics. OUP.")))

    issues, _stats = audit_links(make_parts(body))

    misplaced = [m for m in issues if m.startswith("MISPLACED")]
    assert len(misplaced) == 1 and "ref_ravallion_2016" in misplaced[0]


def test_a_citation_the_two_author_pattern_SWALLOWED_is_not_UNLINKED():
    """"…national Labor Force Surveys and ILOSTAT (2024) data…" matches
    as a citation of "Surveys and ILOSTAT", and the LABEL sits inside
    that span rather than the other way round — which the guard tested
    one way and not the other."""
    from conftest import make_parts, para, run

    linked = ('<w:hyperlink w:anchor="ref_ilostat_2024"><w:r>'
              "<w:t>ILOSTAT (2024)</w:t></w:r></w:hyperlink>")
    body = (para(run("A point.")) + para(run("Prose.")) + para(run("More."))
            + para(run("Still more.")) + para(run("And more."))
            + para(run("Consolidated from national Labor Force Surveys "
                       "and "), linked, run(" data on employment."))
            + para(run("References"))
            + '<w:bookmarkStart w:id="7" w:name="ref_ilostat_2024"/>'
              '<w:bookmarkEnd w:id="7"/>'
            + para(run('ILOSTAT. (2024). "Statistics." ILO.')))

    issues, _stats = audit_links(make_parts(body))

    assert not [m for m in issues if m.startswith("UNLINKED")], issues


def test_a_cross_reference_inside_a_citation_span_does_NOT_clear_it():
    """The mirror guard needs the year in the label too. A "Table 1"
    link falling inside the span says nothing about the citation, and
    clearing on it would switch the check off wherever they overlap."""
    from conftest import make_parts, para, run

    linked = ('<w:hyperlink w:anchor="tbl1_caption"><w:r>'
              "<w:t>Table 1</w:t></w:r></w:hyperlink>")
    body = (para(run("A point.")) + para(run("Prose.")) + para(run("More."))
            + para(run("Still more.")) + para(run("And more."))
            + para(run("Reported in "), linked,
                   run(" and ILOSTAT (2024) besides."))
            + para(run("References"))
            + '<w:bookmarkStart w:id="3" w:name="tbl1_caption"/>'
              '<w:bookmarkEnd w:id="3"/>'
            + para(run('ILOSTAT. (2024). "Statistics." ILO.')))

    issues, _stats = audit_links(make_parts(body))

    assert [m for m in issues if m.startswith("UNLINKED")], issues


def test_a_SHORT_surnamed_entry_does_not_make_a_FOREIGN_marker_AMBIGUOUS():
    """The audit read a foreign name as loosely as the builder wrote
    one: `ref_thompson_2019` named Thompson's entry AND "Ho, B. (2019)",
    because "ho" sits inside "refthompson". Two entries answering is
    nobody's marker here — deliberately, silence beats a guess — so the
    marker cleared NEITHER — so Thompson's LATER mention, the possessive
    that no label carries, went back to being reported UNLINKED on a
    work this document links. Alone in the list, Ho would have been
    cleared by the same marker instead.
    """
    from conftest import make_parts, para, run

    linked = ('<w:hyperlink w:anchor="ref_thompson_2019"><w:r>'
              "<w:t>Thompson (2019)</w:t></w:r></w:hyperlink>")
    body = (para(run("A point.")) + para(run("Prose.")) + para(run("More."))
            + para(run("Still more.")) + para(run("And more."))
            + para(run("As "), linked, run(" shows, it rises."))
            + para(run("Thompson's (2019) estimate holds up well."))
            + para(run("But Ho (2019) disagrees on the point."))
            + para(run("References"))
            + '<w:bookmarkStart w:id="7" w:name="ref_thompson_2019"/>'
              '<w:bookmarkEnd w:id="7"/>'
            + para(run("Thompson, R. (2019). A title. Journal, 1(1): 45-48."))
            + para(run("Ho, B. (2019). Another. Journal, 2(2): 1-9.")))

    issues, _stats = audit_links(make_parts(body))

    unlinked = [m for m in issues if m.startswith("UNLINKED")]
    assert len(unlinked) == 1 and "Ho (2019)" in unlinked[0], issues


def test_a_LABEL_from_ANOTHER_PARAGRAPH_does_not_clear_a_mention():
    """The span test above asks whether the link sits inside THIS
    mention, which is a question about one mention — and it was asked of
    every label in the document. A single "ILOSTAT (2024)" anywhere then
    cleared any citation span that happened to contain those characters
    and that year, here a genuinely unlinked work two paragraphs down.
    (The work-level test above it is the one that reads the whole set,
    and it still does: a work linked ONCE is linked.)
    """
    from conftest import make_parts, para, run

    linked = ('<w:hyperlink w:anchor="ref_ilostat_2024"><w:r>'
              "<w:t>ILOSTAT (2024)</w:t></w:r></w:hyperlink>")
    body = (para(run("A point.")) + para(run("Prose.")) + para(run("More."))
            + para(run("Still more.")) + para(run("And more."))
            + para(run("Reported by "), linked, run(" for the year."))
            + para(run("Estimates from Gmyrek and ILOSTAT (2024) differ."))
            + para(run("References"))
            + '<w:bookmarkStart w:id="7" w:name="ref_ilostat_2024"/>'
              '<w:bookmarkEnd w:id="7"/>'
            + para(run("ILOSTAT. (2024). Statistics. ILO."))
            + para(run("Gmyrek, P. (2024). A working paper. ILO.")))

    issues, _stats = audit_links(make_parts(body))

    unlinked = [m for m in issues if m.startswith("UNLINKED")]
    assert len(unlinked) == 1 and "Gmyrek" in unlinked[0], issues


def test_a_marker_that_only_CONTAINS_a_year_owns_no_entry():
    """The fold is loose on purpose, so both halves have to hold: the
    year must END the name. `ref_kanbur_2007_notes` is a marker ABOUT
    the work, and adopting it would report it misplaced wherever it
    sits."""
    from conftest import make_parts, para, run

    body = (para(run("A point (Kanbur 2007).")) + para(run("References"))
            + '<w:bookmarkStart w:id="7" w:name="ref_kanbur_2007_notes"/>'
              '<w:bookmarkEnd w:id="7"/>'
            # Kanbur is the SECOND entry, so a marker read as his would
            # not sit where the fallback puts it — which is what makes
            # the mis-reading visible at all
            + para(run("Ravallion, M. (2016). Economics. OUP."))
            + para(run("Kanbur, R. (2007). Poverty. Journal, 1(1): 45-48.")))

    issues, _stats = audit_links(make_parts(body))

    assert not [m for m in issues if m.startswith("MISPLACED")], issues


def test_a_marker_TWO_entries_answer_to_belongs_to_neither():
    """Silence beats a guess, the same rule the key-shaped half states.
    "ref_kanbur_2007" holds the surname of both Kanbur and Bur."""
    from conftest import make_parts, para, run

    # The marker sits BETWEEN the two, so taking either as its owner is
    # a finding: the fallback answers Kanbur and the first match is Bur.
    body = (para(run("A point (Kanbur 2007).")) + para(run("References"))
            + para(run("Bur, A. (2007). A note. Journal, 1(1): 1-2."))
            + '<w:bookmarkStart w:id="7" w:name="ref_kanbur_2007"/>'
              '<w:bookmarkEnd w:id="7"/>'
            + para(run("Kanbur, R. (2007). Poverty. Journal, 1(1): 45-48.")))

    issues, _stats = audit_links(make_parts(body))

    assert not [m for m in issues if m.startswith("MISPLACED")], issues


# ---------------------------------------------- the hyphen a wrap copied --

_HYPHEN_PARA = ('<w:p><w:r><w:t xml:space="preserve">Neither trade</w:t>'
                "<w:noBreakHyphen/>"
                '<w:t xml:space="preserve">offs (Rowe 1987) nor the WHO '
                '(WHO 2002) framework</w:t></w:r></w:p>')


def _seen(xml: str) -> str:
    from docxkit._xml import visible_text
    return visible_text(xml)


def _wrap(para: str, needle: str, anchor: str) -> str:
    from docxkit._cite_grammar import wrap_visible_span
    from docxkit._xml import visible_text

    at = visible_text(para).index(needle)
    return wrap_visible_span(para, at, at + len(needle), anchor)


def test_wrapping_a_citation_does_not_COPY_the_paragraph_s_hyphen():
    """One hyphen in, one hyphen out. It used to come out three: the
    before, the inner and the after fragments were each rebuilt from the
    whole run, and `set_run_text` carries a run's children."""
    out = _wrap(_HYPHEN_PARA, "Rowe 1987", "ref_rowe_1987")

    assert out.count("<w:noBreakHyphen/>") == 1
    assert _seen(out) == _seen(_HYPHEN_PARA)


def test_FOUR_wraps_in_one_paragraph_leave_one_hyphen():
    """The shape as it shipped: four citations wrapped in §1's third
    paragraph, one hyphen in "trade-offs", seven hyphens out — printed
    inside the citations, on the page, through four rounds."""
    out = _HYPHEN_PARA
    for needle, anchor in (("Rowe 1987", "ref_rowe_1987"),
                           ("WHO 2002", "ref_who_2002")):
        out = _wrap(out, needle, anchor)

    assert out.count("<w:noBreakHyphen/>") == 1
    assert _seen(out) == _seen(_HYPHEN_PARA)
    assert out.count("<w:hyperlink") == 2


def test_a_hyphen_INSIDE_the_wrapped_span_stays_inside_it():
    """The span is what the link shows, and a hyphen in the middle of it
    is one of the characters it shows."""
    para = ('<w:p><w:r><w:t xml:space="preserve">See Rowe</w:t>'
            "<w:noBreakHyphen/>"
            '<w:t xml:space="preserve">Kahn 1987 for this.</w:t>'
            "</w:r></w:p>")

    out = _wrap(para, "Rowe", "ref_rowe_1987")

    assert out.count("<w:noBreakHyphen/>") == 1
    assert _seen(out) == _seen(para)


def _ref_field(anchor: str, label: str) -> str:
    """Word's own cross-reference: what Insert > Cross-reference writes.

    The instruction is ``REF <name> \\h``, and the name is UNQUOTED —
    the one shape difference from a HYPERLINK field that matters to a
    reader of the instruction text.
    """
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            rf'<w:r><w:instrText xml:space="preserve"> REF {anchor} \h '
            '</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>{label}</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_internal_links_reads_a_word_cross_reference():
    """The THIRD form. Reading only the first two made `citations` call
    four working HCW mentions 'the mention reaches nothing' while
    `crossrefs`, which does read it, called the same exhibits linked."""
    from docxkit._xml import internal_links
    xml = P(_ref_field("_Ref211944524", "Table 6"))
    assert internal_links(xml) == [("_Ref211944524", "Table 6")]


def test_a_cross_reference_without_the_h_switch_is_not_a_link():
    r"""`\h` is what makes the field a hyperlink. Without it Word renders
    the reference as static text a reader cannot click — and counting it
    as a link cleared the house bookmark beside it, suppressing both the
    ORPHAN REF and the REF WITHOUT CITE line that say so."""
    from docxkit._xml import internal_links
    static = _ref_field("_Ref211944524", "Table 6").replace(
        r"\h ", r"\* MERGEFORMAT ")
    assert internal_links(P(static)) == []
    assert internal_links(P(_ref_field("_Ref211944524", "Table 6"))) == [
        ("_Ref211944524", "Table 6")]


def test_a_quoted_reference_name_arrives_without_its_quotes():
    """A nested field puts quotes round the instruction — `IF 1 = 1
    "REF Table1" ""`. Taking them with the name produced the anchor
    `Table1"`, which no bookmark has: a BROKEN LINK finding for a link
    that is fine, and a phantom target in the loss gates."""
    from docxkit._xml import INSTR_REF_RE, ref_anchor
    assert ref_anchor(r'REF "My Bookmark" \h') == "My Bookmark"
    nested = INSTR_REF_RE.search('IF 1 = 1 "REF Table1" ""')
    assert nested is not None and nested.group(2) == "Table1"


def test_a_switchless_reference_still_depends_on_the_bookmark():
    """Two questions, one field. It is not a link a reader follows, but
    removing its target still breaks it into 'Error! Reference source
    not found', which is what `crossrefs` asks before removing one."""
    from docxkit._xml import field_anchors
    static = P(_ref_field("Table1", "Table 6").replace(
        r"\h ", r"\* MERGEFORMAT "))
    assert field_anchors(static) == []
    assert [n for n, _ in field_anchors(static, clickable=False)] == \
        ["Table1"]


@pytest.mark.parametrize("instr", [r"PAGEREF _Ref1 \h",
                                   r"NOTEREF _Ref2 \h",
                                   "REFERENCE _Ref3"])
def test_a_field_that_merely_starts_like_REF_is_not_a_link(instr):
    """`PAGEREF` prints a PAGE NUMBER, not a jump to the bookmark, and a
    substring match would have counted all three as links — which is how
    a too-eager fix to the same defect would silently clear findings."""
    from docxkit._xml import internal_links
    xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
           f'<w:r><w:instrText> {instr} </w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
           '<w:r><w:t>12</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    assert internal_links(xml) == []


def test_a_word_cross_reference_beside_the_house_bookmark_is_not_orphaned():
    """HCW, measured 2026-08-22. Insert > Cross-reference mints its OWN
    anchor at the target and points a REF field at THAT, so the house
    bookmark beside it is targeted by nothing while the mention lands
    exactly where it should. The finding read 'has no in-text hyperlink
    pointing to it', which was true and not the reader's problem."""
    parts = make_doc(
        P(R("Robots displace workers (")
          + bookmark("Smith2020txt", 10, _ref_field("_Ref211944524",
                                                    "Smith 2020"))
          + R(").")),
        P(R("References")),
        P(bookmark("_Ref211944524", 21)
          + _entry("Smith2020", "Smith, J. (2020). Robots. JPE.")))
    issues, _stats = audit_links(parts)
    assert "ORPHAN REF" not in _codes_of(issues)


def test_a_link_at_the_TOP_does_not_clear_a_bookmark_at_the_BOTTOM():
    """Two gaps, one key.

    A marker Word hoists ABOVE the first paragraph belongs to the gap
    before paragraph 0; one hoisted past the LAST paragraph belongs to
    no paragraph at all. Both were filed under -1, so a linked `_Ref` at
    the top of the document cleared a bookmark at the far end of it —
    and the REF WITHOUT CITE line that says nothing reaches it went
    quiet. Suppressing a real finding is the wrong answer this function
    exists to avoid, said in its own docstring.
    """
    from docxkit._cite_audit import _reached
    from docxkit._xml import PARA_RE

    doc = ("<w:body>"
           # Word's own anchor, hoisted above the opening paragraph
           '<w:bookmarkStart w:id="1" w:name="_Ref211944524"/>'
           '<w:bookmarkEnd w:id="1"/>'
           "<w:p><w:r><w:t>Opening line.</w:t></w:r></w:p>"
           "<w:p><w:r><w:t>Zeta, A. 2020. A work. JPE.</w:t></w:r></w:p>"
           # …and the house bookmark at the other end of the document
           '<w:bookmarkStart w:id="2" w:name="Zeta2020"/>'
           '<w:bookmarkEnd w:id="2"/>'
           "</w:body>")
    links = {"_Ref211944524": [(0, "Table 6")]}

    assert _reached(doc, list(PARA_RE.finditer(doc)), links) == \
        {"_Ref211944524"}


def test_a_linked_ORDINARY_neighbour_clears_nothing():
    """The other direction, and the reason the rule names Word's own
    prefix rather than 'a linked bookmark nearby'. li7 hoists two
    entries' markers into one place; a click on the Kotze citation says
    nothing about whether anything reaches Luhmann's entry, and clearing
    it would be the same wrong answer with the sign flipped."""
    parts = make_doc(
        P(R("Two works (")
          + bookmark("Kotze2022txt", 10, hfield("Kotze2022", "Kotze 2022"))
          + R("; ")
          + bookmark("Luhmann2016txt", 11, R("Luhmann 2016"))
          + R(").")),
        P(R("References")),
        # HOISTED out of their paragraphs, into one gap, which is what
        # Word does to li7's entry markers and what puts two works at
        # what this audit can see as a single place.
        bookmark("Kotze2022", 20) + bookmark("Luhmann2016", 21),
        P(R("Kotze, A. (2022). X. JPE.")),
        P(R("Luhmann, M. (2016). Y. JPE.")))
    issues, _stats = audit_links(parts)
    assert any(i.startswith("ORPHAN REF") and "Luhmann2016" in i
               for i in issues), issues


def test_markers_sharing_a_place_report_in_a_stable_order():
    """Position alone is not a total order: several entry markers in one
    paragraph tie, a SET supplied the order among them, and
    PYTHONHASHSEED varies it per process. li7 reported the same 29
    findings in a different order run to run (2026-08-22) — phantom
    churn in a report a reader diffs between rounds."""
    parts = make_doc(
        P(R("Prose that cites nothing.")),
        P(R("References")),
        # One gap, so one position: the names are written Z then A, and
        # only a tie-break can decide the report's order.
        bookmark("Zeta2020", 20) + bookmark("Alpha2019", 21),
        P(R("Alpha, B. (2019). A. JPE.")),
        P(R("Zeta, A. (2020). Z. JPE.")))
    issues, _stats = audit_links(parts)
    named = [i.split("'")[1] for i in issues if i.startswith("REF WITHOUT")]
    assert named == ["Alpha2019", "Zeta2020"], issues


def test_check_citations_reports_later_mentions_only_when_ASKED(tmp_path,
                                                                capsys):
    """`later_mentions=False` is the default and nothing pinned it, so
    flipping it to True changed what a reader is told and no test moved.
    The MENTION COUNT prints either way — that is what stopped a
    half-linked paper reaching "ALL CHECKS PASSED" — but the per-mention
    findings are opt-in."""
    from conftest import write
    parts = make_doc(
        P(R("First shown (")
          + _linked_cite("Aksoy2026", "Aksoy 2026") + R(").")),
        P(R("It is shown again (Aksoy 2026) later on.")),
        P(R("References")),
        P(_entry("Aksoy2026", "Aksoy, C. (2026). Working from home. JEP.")))
    path = write(tmp_path / "later.docx", parts)

    quiet = check_citations(path)
    out = capsys.readouterr().out
    assert "Mentions: 1 of 2 linked (1 later mentions" in out
    assert "LATER-MENTION UNLINKED" not in out
    assert "ALL CHECKS PASSED" in out
    assert quiet == 0

    loud = check_citations(path, later_mentions=True)
    out = capsys.readouterr().out
    assert "LATER-MENTION UNLINKED" in out
    assert loud == 1


def test_the_report_rule_is_sixty_characters(tmp_path, capsys):
    """The line between the counts and the findings. A width nothing
    reads is a width that drifts, and this report is pasted into
    handovers."""
    from conftest import write
    path = write(tmp_path / "rule.docx",
                 make_doc(P(R("Nothing cited here."))))
    check_citations(path)
    rule = [ln for ln in capsys.readouterr().out.splitlines()
            if set(ln) == {"="}]
    assert rule == ["=" * 60]


# --- the half-eaten pair, one module over from `crossrefs` -------------
#
# The convention is a PAIR: the forward link on the first mention, and
# the `<Key>txt` bookmark wrapping it that the entry's back-link points
# at. Word drops them independently — it rewrites a paragraph, keeps the
# hyperlink and takes the bookmark — and the idempotence guard tested
# one half. `citations` then reported BROKEN LINK while `link_all`
# reported a benign skip, both exit 0 (Aging_Well R11, 2026-08-25).

def _half_eaten() -> dict[str, bytes]:
    """A wired document with the in-text bookmark taken back out."""
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("As shown (Smith 2020) the effect holds."))
            + P(R("References"))
            + P(R("Smith, J. (2020). A title. Journal, 1(1): 1-2.")))
    from docxkit.citations import link_all

    parts = xml_parts(body)
    link_all(parts)
    doc = parts["word/document.xml"].decode("utf-8")
    twin = next(n for n in re.findall(
        r'w:bookmarkStart[^>]*w:name="([^"]+)"', doc) if n.endswith("txt"))
    doc = re.sub(rf'<w:bookmarkStart[^>]*w:name="{twin}"/>', "", doc)
    doc = re.sub(r'<w:bookmarkEnd w:id="\d+"/>', "", doc, count=1)
    parts["word/document.xml"] = doc.encode("utf-8")
    return parts


def test_a_half_eaten_pair_is_REPAIRED_rather_than_skipped():
    """The skip message is true — wrapping a mention already inside a
    link would nest one link in another — and it is the wrong answer
    here, because the link that is there is this work's OWN and only its
    bookmark is missing. Rebuilding that bookmark adds no second link,
    so the nesting the branch refuses cannot happen."""
    from docxkit.citations import audit_links, link_all

    parts = _half_eaten()
    assert audit_links(parts)[0], "the fixture is not broken"

    report = link_all(parts)

    assert len(report.repaired) == 1, report.format()
    assert not report.skipped, report.format()
    assert audit_links(parts)[0] == [], audit_links(parts)[0]
    # a repair, not a second link
    assert parts["word/document.xml"].decode("utf-8").count(
        'w:anchor="Smith2020"') == 1


def test_the_repair_is_IDEMPOTENT_like_the_pass_it_belongs_to():
    """A third run has nothing to do. `link_all` runs after every author
    hand-back, and a repair that repeated would add a bookmark per
    round."""
    from docxkit.citations import link_all

    parts = _half_eaten()
    link_all(parts)

    again = link_all(parts)

    assert not again.repaired and not again.linked, again.format()
    assert len(again.already) == 1, again.format()


def test_a_twin_bookmark_in_the_FOOTNOTES_is_not_reported_missing():
    """Bookmarks are unique document-wide and a work cited only in a
    footnote carries its in-text twin in `footnotes.xml`. Read from the
    body alone that twin is missing — so the work reads as half-linked
    and the repair would put a SECOND bookmark of the same name in the
    body, which is the corruption this exists to prevent rather than
    cause."""
    from docxkit.citations import link_all

    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + P(R("Prose with no citation in it."))
            + P(R("References"))
            + P(R("Smith, J. (2020). A title. Journal, 1(1): 1-2.")))
    parts = xml_parts(body)
    parts["word/footnotes.xml"] = (
        b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
        b'wordprocessingml/2006/main"><w:footnote w:id="1"><w:p><w:r>'
        b"<w:t>As shown (Smith 2020).</w:t></w:r></w:p></w:footnote>"
        b"</w:footnotes>")

    link_all(parts)
    body_doc = parts["word/document.xml"].decode("utf-8")
    notes = parts["word/footnotes.xml"].decode("utf-8")
    twins = re.findall(r'w:bookmarkStart[^>]*w:name="(\w+txt)"',
                       body_doc + notes)

    assert twins.count("Smith2020txt") == 1, twins
    assert "Smith2020txt" not in re.findall(
        r'w:bookmarkStart[^>]*w:name="([^"]+)"', body_doc), body_doc


# --- the span nothing had an opinion about ------------------------------
#
# The author turns a narrative citation parenthetical — "Klimaviciute and
# Pestieau (2023)" becomes "(Klimaviciute and Pestieau 2023)" — and Word
# keeps the old right-hand boundary, so the link covers a closing bracket
# with no opening one inside the blue. `citations` counted a link whose
# anchor resolves, `refstyle` does not look at spans, `compare`'s TEXT
# layer saw no character move because none moved, and `ingest` filed it
# under RE-LABELLED (Aging_Well, 2026-08-25).

def _linked(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}"><w:r><w:t>{label}</w:t>'
            "</w:r></w:hyperlink>")


def _spanned(label: str) -> dict[str, bytes]:
    body = ("".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                    for i in range(5))
            + "<w:p>" + R("As shown ") + bookmark("Klim2023txt", 70)
            + _linked("Klim2023", label) + R(" the effect holds.")
            + "</w:p>"
            + P(R("References"))
            + P(bookmark("Klim2023", 71)
                + _linked("Klim2023txt",
                          "Klimaviciute, A. and P. Pestieau. (2023).")
                + R(" A title. Journal.")))
    return xml_parts(body)


def test_a_link_that_swallowed_a_CLOSING_BRACKET_is_a_finding():
    """The anchor resolves and the words are all there, so every other
    layer is content. The bracket is what says the span moved."""
    from docxkit.citations import audit_links

    issues, _ = audit_links(_spanned("Klimaviciute and Pestieau 2023)"))

    (found,) = [i for i in issues if "UNBALANCED SPAN" in i]
    assert "Klim2023" in found
    assert "unmatched ')'" in found, found


def test_a_link_left_OPEN_is_the_same_finding_the_other_way():
    """The mirror image, from an author who moved the left boundary
    instead: the blue opens a bracket the label never closes."""
    from docxkit.citations import audit_links

    issues, _ = audit_links(_spanned("(Klimaviciute and Pestieau 2023"))

    (found,) = [i for i in issues if "UNBALANCED SPAN" in i]
    assert "unmatched '('" in found, found


@pytest.mark.parametrize("label", [
    "Grossman (1972)",                            # the house narrative form
    "de São José et al. (2019)",                  # a particle and accents
    "Maestas et al. (2023, p. 45)",               # a locator
    "(Klimaviciute and Pestieau 2023)",           # parenthetical, whole
    "Klimaviciute and Pestieau 2023",             # bare, no brackets at all
])
def test_every_house_form_closes_what_it_opens(label):
    """The rule has to fire on the damage and never on the convention,
    or it is one more warning a reader learns to scroll past."""
    from docxkit.citations import audit_links

    issues, _ = audit_links(_spanned(label))

    assert not [i for i in issues if "UNBALANCED SPAN" in i], issues


# --- what right LOOKS like, and moving the edge to it (2026-09-09) -------
#
# The audit has named this defect since 2026-08-25 and nothing could fix
# it, so the papers did: Aging_Well is on its THIRD in-paper span repair.
# Its `_balanced` computes the desired label from the LABEL ALONE, which
# can only ever trim — and the case below cannot be trimmed.

def test_balanced_span_TRIMS_a_bracket_the_sentence_owns():
    """The parenthetical form. The author moved "Klimaviciute and
    Pestieau (2023)" to "(Klimaviciute and Pestieau 2023)" and Word kept
    the old right-hand boundary. The brackets belong to the SENTENCE
    here, so the link gives the stray one up."""
    from docxkit.citations import balanced_span

    text = "As shown (Klimaviciute and Pestieau 2023) the effect holds."
    at = text.index("Klimaviciute")

    assert balanced_span(text, at, at + len("Klimaviciute and Pestieau 2023)")
                         ) == "Klimaviciute and Pestieau 2023"


def test_balanced_span_EXTENDS_over_a_bracket_the_citation_owns():
    """The narrative form, and the case that proves trimming is not the
    whole rule. `Modigliani 1986` became `Modigliani (1986)`; Word kept
    the old boundary, so the blue stops one character short. The year's
    brackets ARE the house form — "Grossman (1972)" — so the span
    extends rather than gives anything up.

    Measured on Aging_Well 2026-09-09. The paper's own `_balanced` found
    no trailing ')' to trim and no leading '(' to drop, returned the
    label unchanged, and the repair skipped it; `linkfix` then filed it
    under "no mechanical reading — investigate"."""
    from docxkit.citations import balanced_span

    text = "following Modigliani (1986). Labor market policy"
    at = text.index("Modigliani")

    assert balanced_span(text, at, at + len("Modigliani (1986")
                         ) == "Modigliani (1986)"


def test_balanced_span_says_NOTHING_when_neither_reading_applies():
    """An unmatched bracket with no matching one adjacent is damage this
    cannot name, and a repair nobody measured is worse than a finding."""
    from docxkit.citations import balanced_span

    text = "a stray ( sits mid sentence with no partner anywhere near"
    at = text.index("stray")

    assert balanced_span(text, at, at + len("stray (")) is None
    # and a balanced span is returned unchanged, not flagged
    assert balanced_span("see Grossman (1972) here", 4, 19) == (
        "Grossman (1972)")


def _one_para(inner: str) -> str:
    return "<w:document><w:body>" + P(inner) + "</w:body></w:document>"


def test_respan_link_EXTENDS_the_blue_over_the_bracket_it_was_missing():
    """The repair the audit could describe and not perform."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import respan_link

    xml = _one_para(R("following ") + _linked("Modigliani1986",
                                              "Modigliani (1986")
                    + R("). Labor market policy"))
    was = visible_text(xml)

    fixed = respan_link(xml, "Modigliani1986", "Modigliani (1986)")

    assert internal_links(fixed) == [("Modigliani1986", "Modigliani (1986)")]
    assert visible_text(fixed) == was, "a markup repair moves no words"


def test_respan_link_TRIMS_and_leaves_no_blue_behind():
    """The character the span gives up must lose the Hyperlink character
    style with it. Kept, it is still blue and still underlined, linking
    nowhere — and no layer that reads ANCHORS would see it, which is the
    same blind spot the span defect itself lives in."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import respan_link

    inner = ('<w:hyperlink w:anchor="Klim2023"><w:r><w:rPr>'
             '<w:rStyle w:val="Hyperlink"/></w:rPr><w:t>'
             "Klimaviciute and Pestieau 2023)</w:t></w:r></w:hyperlink>")
    xml = _one_para(R("As shown (") + inner + R(" the effect holds."))
    was = visible_text(xml)

    fixed = respan_link(xml, "Klim2023", "Klimaviciute and Pestieau 2023")

    assert internal_links(fixed) == [("Klim2023",
                                      "Klimaviciute and Pestieau 2023")]
    assert visible_text(fixed) == was
    assert fixed.count('w:val="Hyperlink"') == 1, (
        "the surrendered ')' must not stay styled as a link")


def test_respan_link_CARRIES_the_back_link_bookmark_over_the_new_edge():
    """The `<key>txt` bookmark is the reference entry's back-link target
    and the house convention puts it around the first mention — this
    link. Move the link's edge without it and the link reaches PAST the
    bookmark, which every count still passes: a bookmark that no longer
    wraps its mention is still a bookmark, still balanced, still named.

    Measured while writing this, and it is why the guard counts were not
    enough — the first version shipped exactly that."""
    from docxkit.citations import respan_link

    xml = _one_para(
        R("following ")
        + '<w:bookmarkStart w:id="7" w:name="Mod1986txt"/>'
        + _linked("Mod1986", "Modigliani (1986")
        + '<w:bookmarkEnd w:id="7"/>' + R("). Labor"))

    out = respan_link(xml, "Mod1986", "Modigliani (1986)")

    assert out.index("bookmarkStart") < out.index("<w:hyperlink")
    assert out.index("bookmarkEnd") > out.index("</w:hyperlink>")
    assert out.count("bookmarkStart") == 1 and out.count("bookmarkEnd") == 1


def test_respan_link_moves_the_edge_of_a_FIELD_form_link_too():
    """The form that matters, and the one the first version refused.

    Measured on Aging_Well 2026-09-09: **173 field-form links to 33
    element-form**, and the live defect was on a field. The refusal
    reasoned from `link_in_para` — "Word converts a field to an element
    on the next save anyway" — which is true and no use to a repair that
    runs BEFORE that save. It would have covered 16% of that paper's
    links, including none of the one it was written for.

    Rebuilt as an element, which is what `link_in_para` writes and what
    Word's own save would have made of it."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import respan_link

    xml = _one_para(R("following ") + hfield("Mod1986", "Modigliani (1986")
                    + R("). Labor"))
    was = visible_text(xml)

    out = respan_link(xml, "Mod1986", "Modigliani (1986)")

    assert internal_links(out) == [("Mod1986", "Modigliani (1986)")]
    assert visible_text(out) == was


def test_respan_link_REFUSES_rather_than_retype_a_label():
    """It widens or narrows a span. A `want` that is not the label with
    an edge moved is a different repair, and doing it here would rewrite
    the manuscript's words under a markup-repair's name."""
    import pytest

    from docxkit.citations import respan_link
    from docxkit.errors import AnchorError

    xml = _one_para(R("see ") + _linked("A1", "Smith (2020") + R(")."))

    with pytest.raises(AnchorError, match="edge moved"):
        respan_link(xml, "A1", "Jones (2021)")


def test_respan_link_narrows_BOTH_edges_in_one_call():
    """`(Robeyns 2005)` to `Robeyns 2005` shares neither a start nor an
    end with the label, and was refused as a RETYPE — Aging_Well's R127
    made two calls, one edge each (2026-09-11). Narrowing both at once
    changes no character of the page, and the text guard says so."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import respan_link

    xml = _one_para(R("personal, social, and environmental ")
                    + hfield("Robeyns2005", "(Robeyns 2005)") + R("."))
    was = visible_text(xml)

    out = respan_link(xml, "Robeyns2005", "Robeyns 2005")

    assert internal_links(out) == [("Robeyns2005", "Robeyns 2005")]
    assert visible_text(out) == was


def test_respan_link_widens_BOTH_edges_in_one_call():
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import respan_link

    xml = _one_para(R("as shown (") + _linked("Hood1983", "Hood 1983")
                    + R(")."))
    was = visible_text(xml)

    out = respan_link(xml, "Hood1983", "(Hood 1983)")

    assert internal_links(out) == [("Hood1983", "(Hood 1983)")]
    assert visible_text(out) == was


# --- the two citation FORMS, and a pair of brackets inside the blue ------
#
# BACKLOG S2 and S4 of 2026-09-11, both from Aging_Well's hand passes that
# day: a parenthetical citation whose link swallowed both brackets passed
# every gate, and no helper turned a citation from one form into the other.


def _cited(*paras: str, keys: tuple[str, ...]) -> dict[str, bytes]:
    """Citation paragraphs, and a reference list that resolves each key."""
    filler = "".join(f"<w:p><w:r><w:t>Filler {i}.</w:t></w:r></w:p>"
                     for i in range(5))
    entries = "".join(
        P(bookmark(key, 200 + n, R(f"{key[:-4]}, A. ({key[-4:]}). A title.")))
        for n, key in enumerate(keys))
    return xml_parts(filler + "".join(paras) + P(R("References")) + entries)


def _paren(key: str, label: str) -> str:
    """A parenthetical citation, its brackets OUTSIDE the link."""
    return P(R("Work pays (") + _linked(key, label) + R(")."))


def _swallowed() -> dict[str, bytes]:
    """Three citations keep their brackets out; one link swallowed its."""
    return _cited(
        _paren("Adams2001", "Adams 2001"), _paren("Brown2002", "Brown 2002"),
        _paren("Clark2003", "Clark 2003"),
        P(R("Conversion factors matter ")
          + _linked("Robeyns2005", "(Robeyns 2005)") + R(".")),
        keys=("Adams2001", "Brown2002", "Clark2003", "Robeyns2005"))


def _bracketed(parts: dict[str, bytes]) -> list[tuple[str, str]]:
    from docxkit._cite_audit import _audit_findings
    return [(f.subject, f.extra) for f in _audit_findings(parts)[0]
            if f.kind == "BRACKETED SPAN"]


@pytest.mark.parametrize(("label", "shape"), [
    ("Robeyns 2005", ("bare", "Robeyns", "2005")),
    ("Behrman et al. (1982)", ("narrative", "Behrman et al.", "1982")),
    ("(Klimaviciute and Pestieau 2023)",
     ("bracketed", "Klimaviciute and Pestieau", "2023")),
    ("de São José et al. (2019b)",
     ("narrative", "de São José et al.", "2019b")),
    ("Table 5", None),
    ("(2019)", None),
    ("Smith (2020", None),
])
def test_citation_shape_reads_the_three_house_forms(label, shape):
    from docxkit.citations import citation_shape

    assert citation_shape(label) == shape


def test_a_link_that_SWALLOWED_both_brackets_is_a_finding():
    """Balanced is not the same as right. `(Robeyns 2005)` closes what it
    opens, so UNBALANCED SPAN had nothing to say, `ingest` called it a
    re-label, and the rendered brackets were blue in a paper whose other
    parenthetical citations leave them black."""
    found = _bracketed(_swallowed())

    assert found == [("Robeyns2005", "Robeyns 2005")]
    from docxkit._cite_audit import _audit_findings
    (message,) = [f.message for f in _audit_findings(_swallowed())[0]
                  if f.kind == "BRACKETED SPAN"]
    assert "3 parenthetical" in message, message


def test_a_paper_that_keeps_its_brackets_INSIDE_the_link_is_not_flagged():
    """Judged against the document, not a rule: AFI links 8 citations as
    `(Name Year)` and 5 as `Name Year` (measured 2026-09-11), and a rule
    that called every swallowed pair wrong would have raised 8 findings on
    a paper following its own convention."""
    parts = _cited(
        P(R("a ") + _linked("Adams2001", "(Adams 2001)") + R(".")),
        P(R("b ") + _linked("Brown2002", "(Brown 2002)") + R(".")),
        P(R("c ") + _linked("Clark2003", "(Clark 2003)") + R(".")),
        _paren("Robeyns2005", "Robeyns 2005"),
        keys=("Adams2001", "Brown2002", "Clark2003", "Robeyns2005"))

    assert _bracketed(parts) == []


def test_the_plan_proposes_to_parenthetical_for_a_swallowed_pair():
    from docxkit.citations import repair_plan

    plan = repair_plan(_swallowed())

    assert 'to_parenthetical(doc, "Robeyns2005")' in plan, plan


def test_the_plan_files_CITE_WITHOUT_REF_under_investigate_not_DOUBLED():
    """"CITE WITHOUT REF" sorts before "DOUBLED LINK" and reaches that
    branch, so a `<=` there filed it as a doubled link to untangle — a
    survivor of the 2026-09-12 sweep, where the recorded argument said
    only DOUBLED LINK could arrive."""
    from docxkit.citations import repair_plan

    parts = _cited(P(R("as ") + bookmark("Ghost2020txt", 60, R("Ghost (2020)"))
                     + R(" shows.")), keys=("Adams2001",))

    plan = repair_plan(parts)

    assert "CITE WITHOUT REF: 'Ghost2020'" in plan, plan
    assert "remove_outer_field" not in plan, plan


def test_a_NARRATIVE_link_is_neither_side_of_the_majority():
    """`Dewey (2004)` carries its brackets inside the blue by the house
    rule; counted as a swallowed pair it would be reported beside the
    real one (a `>=` survived the 2026-09-12 sweep)."""
    parts = _cited(
        _paren("Adams2001", "Adams 2001"), _paren("Brown2002", "Brown 2002"),
        _paren("Clark2003", "Clark 2003"),
        P(R("as ") + _linked("Dewey2004", "Dewey (2004)") + R(" argues.")),
        P(R("Conversion factors matter ")
          + _linked("Robeyns2005", "(Robeyns 2005)") + R(".")),
        keys=("Adams2001", "Brown2002", "Clark2003", "Dewey2004",
              "Robeyns2005"))

    assert _bracketed(parts) == [("Robeyns2005", "Robeyns 2005")]


def test_a_TIE_between_the_two_forms_is_not_a_majority():
    parts = _cited(
        _paren("Adams2001", "Adams 2001"), _paren("Brown2002", "Brown 2002"),
        _paren("Clark2003", "Clark 2003"),
        P(R("d ") + _linked("Dewey2004", "(Dewey 2004)") + R(".")),
        P(R("e ") + _linked("Evans2005", "(Evans 2005)") + R(".")),
        P(R("f ") + _linked("Frank2006", "(Frank 2006)") + R(".")),
        keys=("Adams2001", "Brown2002", "Clark2003", "Dewey2004",
              "Evans2005", "Frank2006"))

    assert _bracketed(parts) == []


def test_a_BRACKETED_SPAN_quotes_the_first_48_characters_of_the_label():
    from docxkit._cite_audit import _audit_findings

    label = "(Organisation for Economic Co-operation and Development 2019)"
    parts = _cited(
        _paren("Adams2001", "Adams 2001"), _paren("Brown2002", "Brown 2002"),
        _paren("Clark2003", "Clark 2003"),
        P(R("see ") + _linked("OECD2019", label) + R(".")),
        keys=("Adams2001", "Brown2002", "Clark2003", "OECD2019"))

    (message,) = [f.message for f in _audit_findings(parts)[0]
                  if f.kind == "BRACKETED SPAN"]
    assert f'"{label[:48]}"' in message, message


def _footnote_f7(label: str = "Behrman et al. 1982") -> str:
    """Aging_Well's footnote 7 as R129 measured it: a `(` run, the
    `<key>txt` bookmark round a FIELD link, and a `).` run after it."""
    return _one_para(R("as in (")
                     + bookmark("Behrman1982txt", 9, hfield("Behrman1982",
                                                            label))
                     + R(")."))


def _inside_bookmark(xml: str, name: str) -> str:
    """What a reader sees between a bookmark's start and its end."""
    from docxkit._xml import visible_text
    start = re.search(rf'<w:bookmarkStart w:id="(\d+)" w:name="{name}"/>',
                      xml)
    assert start is not None
    shut = xml.index(f'<w:bookmarkEnd w:id="{start.group(1)}"/>')
    return visible_text(xml[start.end():shut])


def test_to_narrative_moves_the_brackets_ONTO_the_label_and_keeps_the_FIELD():
    """R129's F7, which the paper did by editing three runs by structure.
    A field stays a field — `respan_link` would have made it an element —
    and the back-link bookmark still wraps exactly the label."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import to_narrative

    out = to_narrative(_footnote_f7(), "Behrman1982")

    assert visible_text(out) == "as in Behrman et al. (1982)."
    assert internal_links(out) == [("Behrman1982", "Behrman et al. (1982)")]
    assert out.count("<w:instrText") == 1 and "<w:hyperlink" not in out
    assert _inside_bookmark(out, "Behrman1982txt") == "Behrman et al. (1982)"


def test_to_narrative_from_a_link_that_SWALLOWED_its_brackets():
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import to_narrative

    xml = _one_para(R("see ") + _linked("Robeyns2005", "(Robeyns 2005)")
                    + R("."))

    out = to_narrative(xml, "Robeyns2005")

    assert visible_text(out) == "see Robeyns (2005)."
    assert internal_links(out) == [("Robeyns2005", "Robeyns (2005)")]


def test_to_narrative_leaves_a_NARRATIVE_citation_alone():
    from docxkit.citations import to_narrative

    xml = _one_para(R("as ") + _linked("Robeyns2005", "Robeyns (2005)")
                    + R(" argues."))

    assert to_narrative(xml, "Robeyns2005") is xml


def test_to_narrative_REFUSES_brackets_that_hold_several_citations():
    """`(Hood 1983; Hood and Margetts 2007)`: the brackets belong to both,
    and moving them onto one label rewrites the other's sentence."""
    from docxkit.citations import to_narrative

    xml = _one_para(R("(") + _linked("Hood1983", "Hood 1983") + R("; ")
                    + _linked("Hood2007", "Hood and Margetts 2007") + R(")."))

    with pytest.raises(AnchorError, match="bracket pair of its own"):
        to_narrative(xml, "Hood1983")


def test_to_parenthetical_puts_the_brackets_OUTSIDE_link_and_bookmark():
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import to_parenthetical

    xml = _one_para(R("following ")
                    + bookmark("Mod1986txt", 7, hfield("Mod1986",
                                                       "Modigliani (1986)"))
                    + R(". Labor"))

    out = to_parenthetical(xml, "Mod1986")

    assert visible_text(out) == "following (Modigliani 1986). Labor"
    assert internal_links(out) == [("Mod1986", "Modigliani 1986")]
    assert out.count("<w:instrText") == 1 and "<w:hyperlink" not in out
    assert _inside_bookmark(out, "Mod1986txt") == "Modigliani 1986", (
        "the brackets sit outside the back-link target as well")


def test_to_parenthetical_repairs_a_link_that_SWALLOWED_both_brackets():
    """S2's shape: the page reads the same afterwards, and the blue no
    longer covers the brackets."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import to_parenthetical

    xml = _one_para(R("environmental ")
                    + hfield("Robeyns2005", "(Robeyns 2005)") + R("."))

    out = to_parenthetical(xml, "Robeyns2005")

    assert visible_text(out) == visible_text(xml)
    assert internal_links(out) == [("Robeyns2005", "Robeyns 2005")]


def test_the_two_conversions_are_each_others_INVERSE():
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import to_narrative, to_parenthetical

    xml = _footnote_f7()

    back = to_parenthetical(to_narrative(xml, "Behrman1982"), "Behrman1982")

    assert visible_text(back) == visible_text(xml)
    assert internal_links(back) == internal_links(xml)
    assert _inside_bookmark(back, "Behrman1982txt") == "Behrman et al. 1982"


def test_the_conversions_REFUSE_a_link_that_is_not_one_work_and_a_year():
    from docxkit.citations import to_narrative, to_parenthetical

    xml = _one_para(R("see ") + _linked("Table5", "Table 5") + R("."))

    for convert in (to_narrative, to_parenthetical):
        with pytest.raises(AnchorError, match="one work and a year"):
            convert(xml, "Table5")


def test_the_conversions_want_EXACTLY_one_link_to_the_anchor():
    from docxkit.citations import to_narrative

    xml = _one_para(R("(") + _linked("Adams2001", "Adams 2001") + R(") and (")
                    + _linked("Adams2001", "Adams 2001") + R(")."))

    with pytest.raises(AnchorError, match="matched 2 link"):
        to_narrative(xml, "Adams2001")


# Three found by running the conversions over every citation in eight real
# manuscripts before they landed (2026-09-11). The guards refused each one,
# so nothing was written wrongly — but a refusal on the ordinary shape is a
# helper nobody can use.


def test_to_narrative_keeps_the_SPACE_that_shared_a_run_with_the_bracket():
    """` (` in a run of its own is what Word leaves after a hand edit.
    Taking the bracket left a run holding one space, the first version
    called that run empty and removed it, and `countries (WHO 2025).`
    would have read `countriesWHO (2025).` — 26 citations, five papers."""
    from docxkit._xml import visible_text
    from docxkit.citations import to_narrative

    xml = _one_para(R("three in some countries")
                    + '<w:r><w:t xml:space="preserve"> (</w:t></w:r>'
                    + _linked("WHO2025", "WHO 2025") + R(")."))

    out = to_narrative(xml, "WHO2025")

    assert visible_text(out) == "three in some countries WHO (2025)."


def test_the_conversions_move_the_BRACKETS_and_not_the_spacing():
    """A label is edited, never rebuilt from its parts. Rebuilt, LI's
    "Schluter.  (2018)" came back with one space where the author typed
    two — and the text guard passed it, having been built from the same
    rebuilt string."""
    from docxkit._xml import internal_links
    from docxkit.citations import to_narrative, to_parenthetical

    xml = _one_para(R("as shown (") + _linked("J2018", "Jamieson  2018")
                    + R(")."))

    there = to_narrative(xml, "J2018")
    back = to_parenthetical(there, "J2018")

    assert internal_links(there) == [("J2018", "Jamieson  (2018)")]
    assert internal_links(back) == [("J2018", "Jamieson  2018")]


def test_to_parenthetical_under_a_bookmark_that_STARTS_EARLY():
    """A citation's bookmark can start before its link and end with it —
    29 characters early on AFI, 46 on HPPA, one space on an LI reference
    entry, and no audit reports it. The opening bracket has no outside to
    go to short of moving the bookmark, which a conversion does not do:
    it goes in, the closing one still lands outside. The first version
    refused all three."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import to_parenthetical

    xml = _one_para(bookmark("Mod1986txt", 7,
                             R("As argued by ")
                             + hfield("Mod1986", "Modigliani (1986)"))
                    + R(", it rises."))

    out = to_parenthetical(xml, "Mod1986")

    assert visible_text(out) == "As argued by (Modigliani 1986), it rises."
    assert internal_links(out) == [("Mod1986", "Modigliani 1986")]
    assert (_inside_bookmark(out, "Mod1986txt")
            == "As argued by (Modigliani 1986")


# The mutation sweep of 2026-09-12 over the lines the S4/S2 fix wrote. The
# guards in `_convert` had never tripped in a test, so each could be
# weakened to `<`, or deleted, with the whole suite green.


def test_a_conversion_REFUSAL_names_its_helper_and_the_label_it_read():
    from docxkit.citations import to_narrative, to_parenthetical

    with pytest.raises(AnchorError, match=r"^to_parenthetical: X matched 0 "):
        to_parenthetical(_one_para(R("No link at all.")), "X")

    title = "The Encyclopedia of Ageing and the Life Course, Volume Two"
    with pytest.raises(AnchorError) as caught:
        to_narrative(_one_para(R("see ") + _linked("Enc", title) + R(".")),
                     "Enc")

    assert str(caught.value).startswith("to_narrative: the link to Enc reads ")
    assert repr(title[:48]) in str(caught.value)


@pytest.mark.parametrize(("before", "after"), [
    ("see [", ")."),          # the character before sorts ABOVE "("
    ("see ", ")."),           # …and below it
    ("see (", " etc.)."),     # the character after sorts below ")"
])
def test_to_narrative_wants_the_bracket_pair_to_HUG_the_label(before, after):
    from docxkit.citations import to_narrative

    xml = _one_para(R(before) + _linked("Adams2001", "Adams 2001") + R(after))

    with pytest.raises(AnchorError, match="bracket pair of its own"):
        to_narrative(xml, "Adams2001")


def test_to_narrative_will_not_take_a_bracket_out_of_ANOTHER_link():
    from docxkit.citations import to_narrative

    xml = _one_para(R("see ") + _linked("Other", "Part (")
                    + _linked("Adams2001", "Adams 2001") + R(")."))

    with pytest.raises(AnchorError, match=r"no plain '\(' at offset 9"):
        to_narrative(xml, "Adams2001")


def test_to_parenthetical_inside_a_bookmark_round_the_WHOLE_sentence():
    """Both brackets fall strictly inside it, the closing one too."""
    from docxkit._xml import visible_text
    from docxkit.citations import to_parenthetical

    xml = _one_para(bookmark("_Hlk5", 3, R("As argued by ")
                             + hfield("Mod1986", "Modigliani (1986)")
                             + R(", it rises.")))

    out = to_parenthetical(xml, "Mod1986")

    assert visible_text(out) == "As argued by (Modigliani 1986), it rises."
    assert (_inside_bookmark(out, "_Hlk5")
            == "As argued by (Modigliani 1986), it rises.")


def test_to_parenthetical_keeps_a_space_the_author_left_INSIDE_the_link():
    from docxkit._xml import internal_links
    from docxkit.citations import to_parenthetical

    xml = _one_para(R("as ") + _linked("J2018", "Jamieson (2018) ")
                    + R("argues."))

    out = to_parenthetical(xml, "J2018")

    assert internal_links(out) == [("J2018", "Jamieson 2018 ")]


def _sabotage(monkeypatch, name, change):
    """Make `_cite_repair.<name>` hand back `change(result)`."""
    import docxkit._cite_repair as repair
    real = getattr(repair, name)
    monkeypatch.setattr(repair, name,
                        lambda *a, **k: change(real(*a, **k)))


@pytest.mark.parametrize(("content", "got"), [
    # doubled brackets sort BELOW the page asked for, swapped ones ABOVE
    ({"(": "((", ")": "))"}, "((Abramovitz 1986))"),
    ({"(": "[", ")": "]"}, "[Abramovitz 1986]"),
])
def test_the_TEXT_guard_refuses_and_quotes_24_characters_either_side(
        monkeypatch, content, got):
    import docxkit._cite_repair as repair
    from docxkit.citations import to_parenthetical

    real = repair.insert_in_para
    monkeypatch.setattr(repair, "insert_in_para",
                        lambda para, at, text, **kw: real(para, at,
                                                          content[text], **kw))
    far = "word " * 14                                  # the link at 70
    for prefix, start, stop in ((far, 46, 111), ("word ", 0, 46)):
        page = prefix + got + "tail " * 10
        xml = _one_para(R(prefix) + _linked("Abr1986", "Abramovitz (1986)")
                        + R("tail " * 10))
        with pytest.raises(AnchorError,
                           match="not the bracket move") as caught:
            to_parenthetical(xml, "Abr1986")
        assert repr(page[start:stop]) in str(caught.value)


@pytest.mark.parametrize(("change", "tag"), [
    (lambda p: p.replace('<w:bookmarkEnd w:id="7"/>', "", 1), "bookmarkEnd"),
    (lambda p: p.replace("</w:p>",
                         '<w:bookmarkStart w:id="99" w:name="x"/></w:p>'),
     "bookmarkStart"),
])
def test_the_COUNT_guard_refuses_a_bookmark_lost_or_gained(
        monkeypatch, change, tag):
    from docxkit.citations import to_parenthetical

    _sabotage(monkeypatch, "relabel_link", change)
    xml = _one_para(R("following ") + bookmark("Mod1986txt", 7, hfield(
        "Mod1986", "Modigliani (1986)")) + R(". Labor"))

    with pytest.raises(AnchorError, match=f"the <w:{tag} count moved"):
        to_parenthetical(xml, "Mod1986")


@pytest.mark.parametrize("renamed", ["Aaa", "Zzz"])
def test_the_LINKS_guard_refuses_a_link_that_now_points_elsewhere(
        monkeypatch, renamed):
    from docxkit.citations import to_narrative

    _sabotage(monkeypatch, "relabel_link", lambda p: p.replace(
        'w:anchor="Robeyns2005"', f'w:anchor="{renamed}"'))
    xml = _one_para(R("see ") + _linked("Robeyns2005", "(Robeyns 2005)")
                    + R("."))

    with pytest.raises(AnchorError, match="the paragraph's links moved"):
        to_narrative(xml, "Robeyns2005")


def test_respan_link_REFUSES_a_want_found_TWICE_inside_the_label():
    from docxkit.citations import respan_link

    xml = _one_para(R("as ") + _linked("Lee2001", "(Lee and Lee 2001)")
                    + R("."))

    with pytest.raises(AnchorError, match="does not retype one"):
        respan_link(xml, "Lee2001", "Lee")


def test_respan_link_REFUSES_a_label_found_TWICE_inside_want():
    from docxkit.citations import respan_link

    xml = _one_para(R("in (") + _linked("Y2001", "2001") + R(" 2001) it"))

    with pytest.raises(AnchorError, match="does not retype one"):
        respan_link(xml, "Y2001", "(2001 2001)")


def test_respan_link_narrows_both_edges_from_an_ODD_offset():
    """At 7, `7 ^ 1` and `7 | 1` both miss the 8 the label moves to."""
    from docxkit._xml import internal_links, visible_text
    from docxkit.citations import respan_link

    xml = _one_para(R("As in: ") + _linked("Robeyns2005", "(Robeyns 2005)")
                    + R("."))

    out = respan_link(xml, "Robeyns2005", "Robeyns 2005")

    assert internal_links(out) == [("Robeyns2005", "Robeyns 2005")]
    assert visible_text(out) == visible_text(xml)


def test_the_plan_now_PROPOSES_the_span_repair_instead_of_shrugging():
    """Every one of these fell through to "no mechanical reading —
    investigate" while the papers wrote the repair themselves."""
    from docxkit.citations import repair_plan

    plan = repair_plan(_spanned("Klimaviciute and Pestieau 2023)"))

    assert "respan_link" in plan, plan
    assert '"Klimaviciute and Pestieau 2023"' in plan, plan
    assert "investigate" not in plan.split("respan_link")[0][-200:], plan


def test_the_message_says_WHICH_WAY_the_boundary_went_wrong():
    """One sentence for two opposite defects. "reached past its mention"
    was printed over a span that stopped SHORT of it — the same shape as
    the LOST-link explanation fixed upstream on 2026-09-08, and wrong in
    the same way: the reader is told to look for the wrong damage."""
    from docxkit.citations import audit_links

    body = (P(R("following ") + _linked("Mod1986", "Modigliani (1986")
              + R("). Labor market policy."))
            + P(R("References"))
            + P(bookmark("Mod1986", 71)
                + R("Modigliani, F. (1986). A title.")))
    issues, _ = audit_links(xml_parts(body))

    (found,) = [i for i in issues if "UNBALANCED SPAN" in i]
    assert "stopped short of its mention" in found, found


def test_RE_LABELLED_says_when_a_re_label_left_the_span_unbalanced():
    """That section exists to say "the anchor is intact, nothing is
    lost, do not block the baseline" — right about the anchor and silent
    about the span, which is the one thing that would send a reader past
    this. An unbalanced label is damage wearing a re-label's clothes."""
    from docxkit.revision import Relabelled

    damage = Relabelled("Klim2023", "Klimaviciute and Pestieau (2023)",
                        "Klimaviciute and Pestieau 2023)")
    ordinary = Relabelled("Smith2020", "Smith (2020)", "(Smith 2020)")

    assert damage.unbalanced == ")"
    assert not ordinary.unbalanced
