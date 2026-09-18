"""`link_all`'s own body: the footnote part, the gap, and the report.

What was left in `link_all` after its two passes clustered on the parts
of the document that are NOT the body: the footnotes it also links and
also has to write back, and the body-level gap before each entry where
Word leaves a bookmark it has hoisted. Both are asserted here through
what a reader would see.

The report's `format` is here too. Every test in this suite reads the
LISTS on the report; none read the text it prints, so the loop that
prints the detail lines could be removed entirely and the suite would
not notice — and that text is what a paper's build log shows.
"""
from __future__ import annotations

from conftest import make_parts, note, notes, para, run

from docxkit._xml import BOOKMARK_NAME_RE, internal_links
from docxkit.citations import IGNORED_LEADS, link_all, link_rest

ENTRIES = (
    para(run("References"))
    + para(run("Kanbur, R. (2007). Poverty and distribution. Journal."))
    + para(run("Ravallion, M. (2016). The Economics of Poverty. OUP.")))


def _notes(*texts: str) -> str:
    return notes("footnotes",
                 *(note(t, i + 2) for i, t in enumerate(texts)))


def _links(parts: dict[str, bytes], part: str = "word/document.xml"):
    return internal_links(parts[part].decode("utf-8"))


# ---------------------------------------------------- the footnote part --

def test_a_link_ALREADY_in_a_footnote_is_recognised_as_a_link():
    """Existing links are read from both parts. Reading only the body
    makes the pass link a work a second time, in a second place, and
    the two links then compete for the same reader.
    """
    linked = ('<w:hyperlink w:anchor="Kanbur2007">'
              '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
              "<w:t>Kanbur 2007</w:t></w:r></w:hyperlink>")
    part = notes("footnotes", '<w:footnote w:id="2"><w:p>'
                 + run("See ") + linked + "</w:p></w:footnote>")
    parts = make_parts(
        para(run("A point (Kanbur 2007).")) + ENTRIES, footnotes=part)

    report = link_all(parts)

    assert "Kanbur2007" in report.already, report.format()
    assert not report.linked, report.format()


def test_TWO_footnote_paragraphs_are_rewritten_bottom_up():
    """Each rewrite changes the length of the part, so the offsets of
    everything after it go stale. Applied top-down the second splice
    lands wrong — and it lands INSIDE the note it was meant to follow,
    which reads as corruption rather than as a missing link.
    """
    parts = make_parts(
        para(run("Two works are used below.")) + ENTRIES,
        footnotes=_notes("The first is (Kanbur 2007) throughout.",
                         "The second is (Ravallion 2016) throughout."))

    report = link_all(parts)

    foot = parts["word/footnotes.xml"].decode("utf-8")
    # the notes hold the MENTIONS, so their links point AT the entries
    assert sorted(a for a, _ in _links(parts, "word/footnotes.xml")) == \
        ["Kanbur2007", "Ravallion2016"], report.format()
    assert "The first is (Kanbur 2007) throughout." in _visible(foot)
    assert "The second is (Ravallion 2016) throughout." in _visible(foot)


def _visible(xml: str) -> str:
    from docxkit._xml import visible_text
    return visible_text(xml)


def test_a_back_link_whose_target_is_in_a_FOOTNOTE_is_kept():
    """The undo pass looks for the in-text end of the pair before
    shipping a back-link, and that end can be in the footnotes — a work
    cited only in a note has its mention there. Looking in the body
    alone tears out a back-link that is perfectly good, and says in the
    report that the mention was never wrapped.
    """
    parts = make_parts(
        para(run("Loneliness rises with age.")) + ENTRIES,
        footnotes=_notes("The gradient is steeper still (Kanbur 2007)."))

    report = link_all(parts)

    assert report.backlinked == ["Kanbur2007"], report.format()
    assert ("Kanbur2007txt", "Kanbur, R. (2007)") in _links(parts), \
        "the entry lost its back-link"
    assert not any("removed" in line for line in report.skipped), \
        report.format()


def test_a_FOOTNOTE_paragraph_is_never_marked_as_an_entry():
    """Paragraph indices are per PART, so footnote ¶3 and body ¶3 are
    different paragraphs with the same number — and the entries are
    indexed by body number. Only `where == "¶"` keeps the entry-marking
    branch off the footnotes; loosen it and a note carrying a citation
    is stamped with the entry's own bookmark name, so the document ends
    up with that name twice and Word resolves every link to it by
    whichever it finds first.

    The fixture puts a cited footnote at the index an entry occupies.
    """
    parts = make_parts(
        para(run("Two works are discussed."))          # ¶0
        + ENTRIES,                                     # ¶1 heading, ¶2, ¶3
        footnotes=_notes("A note with nothing in it.",          # fn ¶0
                         "Another note with nothing.",          # fn ¶1
                         "See (Kanbur 2007) here.",             # fn ¶2
                         "And (Ravallion 2016) too."))          # fn ¶3

    report = link_all(parts)

    marks = BOOKMARK_NAME_RE.findall(
        parts["word/footnotes.xml"].decode("utf-8"))
    assert marks, report.format()
    assert all(n.endswith("txt") for n in marks), (
        f"an ENTRY bookmark was written into the footnotes: {marks}")


# ------------------------------------------------ the gap before an entry --

def test_the_gap_read_for_an_entry_is_ITS_OWN():
    """Word hoists a collapsed bookmark out of the paragraph it marks,
    so the gap in front of an entry counts as the entry's. The gap
    BEFORE that one belongs to the previous paragraph, and reaching
    into it finds a marker left by an earlier scheme — which the entry
    then answers to, while its own marker sits unused.
    """
    stale = ('<w:bookmarkStart w:id="7" w:name="Kanbur2007"/>'
             '<w:bookmarkEnd w:id="7"/>')
    own = ('<w:bookmarkStart w:id="9" w:name="Kanbur2007_2"/>'
           '<w:bookmarkEnd w:id="9"/>')
    parts = make_parts(
        para(run("A point (Kanbur 2007)."))
        + para(run("A sentence between."))
        + para(run("Another sentence."))
        + stale
        + para(run("References"))
        + own
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    link_all(parts)

    assert "Kanbur2007_2" in [a for a, _ in _links(parts)], \
        [a for a, _ in _links(parts)]
    names = BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8"))
    assert names.count("Kanbur2007_2") == 1, names


# ------------------------------------------- somebody else's apparatus --

def test_an_entry_wired_under_ANOTHER_scheme_is_read_as_already_linked():
    """A paper that arrives with `ref_kanbur_2007` / `cite_kanbur_2007`
    is fully linked. Reading only the names THIS module mints, the pass
    called every one of its works unlinked and wrote a second apparatus
    beside the first — 27 new bookmarks and 33 doubled links on AFI.
    """
    own = ('<w:bookmarkStart w:id="7" w:name="ref_kanbur_2007"/>'
           '<w:bookmarkEnd w:id="7"/>')
    linked = ('<w:hyperlink w:anchor="ref_kanbur_2007">'
              '<w:r><w:t>Kanbur 2007</w:t></w:r></w:hyperlink>')
    parts = make_parts(
        para(run("A point ("), linked, run(").")) + para(run("References"))
        + own
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    report = link_all(parts)

    assert report.already == ["ref_kanbur_2007"], report.format()
    assert not report.linked, report.format()
    names = BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8"))
    assert names == ["ref_kanbur_2007"], names


def test_a_name_ending_in_the_year_but_about_something_ELSE_is_not_adopted():
    """The fold is deliberately loose, so the two halves it keeps have
    to hold: the surname must be IN the name, and the year must END it.
    A marker for a different work must not be adopted as this entry's.
    """
    stray = ('<w:bookmarkStart w:id="7" w:name="ref_ravallion_2007"/>'
             '<w:bookmarkEnd w:id="7"/>')
    parts = make_parts(
        para(run("A point (Kanbur 2007).")) + para(run("References"))
        + stray
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    link_all(parts)

    assert "Kanbur2007" in [a for a, _ in _links(parts)], _links(parts)


def test_a_name_that_only_CONTAINS_the_year_is_not_adopted():
    """The year has to END the folded name. A paper marks more than its
    entries — `ref_kanbur_2007_notes` is an anchor ABOUT the work, and
    adopting it sends every citation of Kanbur to the wrong place.
    """
    about = ('<w:bookmarkStart w:id="7" w:name="ref_kanbur_2007_notes"/>'
             '<w:bookmarkEnd w:id="7"/>')
    parts = make_parts(
        para(run("A point (Kanbur 2007).")) + para(run("References"))
        + about
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    link_all(parts)

    assert "Kanbur2007" in [a for a, _ in _links(parts)], _links(parts)


def test_a_citation_INSIDE_another_link_is_refused_not_nested():
    """Wrapping it makes exactly the shape `audit_links` calls DOUBLED
    LINK, and the click goes to the OUTER link — so the new one is both
    invisible and wrong. The report says why instead.
    """
    outer = ('<w:hyperlink w:anchor="somewhere_else">'
             '<w:r><w:t>(Kanbur 2007)</w:t></w:r></w:hyperlink>')
    parts = make_parts(
        para(run("As shown "), outer, run(", it rises.")) + ENTRIES)

    report = link_all(parts)

    assert not report.linked, report.format()
    got = [a for a, _ in _links(parts)]
    assert got == ["somewhere_else"], got
    assert any("already inside a link" in note
               for note in report.skipped), report.format()


def test_a_citation_AFTER_an_IGNORED_one_is_still_linked():
    """`ignore` is a list the papers GROW — a name that reads as a
    citation and is not one. Stepping over it is the point; stopping
    there leaves every citation later in the paragraph unlinked, and the
    report says nothing because nothing was refused."""
    parts = make_parts(
        para(run("As Kanbur (2007) notes, poverty fell (Ravallion 2016)."))
        + ENTRIES)

    report = link_all(parts, ignore=IGNORED_LEADS | {"Kanbur"})

    assert [a for a, _ in _links(parts)] == [
        "Ravallion2016", "Ravallion2016txt"], report.format()


def test_an_entry_whose_TXT_anchor_comes_first_is_still_recognised():
    """The back-link anchor is skipped, not stopped at. A paper that
    keeps `<key>txt` above the entry's own marker would otherwise have
    its scheme read as absent, and `link_all` would mint a second one
    beside it — the defect this whole path exists to prevent."""
    own = ('<w:bookmarkStart w:id="7" w:name="Kanbur2007txt"/>'
           '<w:bookmarkEnd w:id="7"/>'
           '<w:bookmarkStart w:id="8" w:name="ref_kanbur_2007"/>'
           '<w:bookmarkEnd w:id="8"/>')
    linked = ('<w:hyperlink w:anchor="ref_kanbur_2007">'
              "<w:r><w:t>Kanbur 2007</w:t></w:r></w:hyperlink>")
    parts = make_parts(
        para(run("A point ("), linked, run(")."))
        + para(run("References")) + own
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    report = link_all(parts)

    assert report.already == ["ref_kanbur_2007"], report.format()
    assert not report.linked, report.format()


def test_the_nesting_refusal_names_the_PARAGRAPH():
    """A refusal is read to go and look. The paragraph number is the
    only part of it that says where."""
    outer = ('<w:hyperlink w:anchor="somewhere_else">'
             "<w:r><w:t>(Kanbur 2007)</w:t></w:r></w:hyperlink>")
    parts = make_parts(
        para(run("First paragraph."))
        + para(run("As shown "), outer, run(", it rises.")) + ENTRIES)

    report = link_all(parts)

    assert any("(¶2)" in note for note in report.skipped), report.format()


# ----------------------------------------------------------- the report --

def test_the_link_all_report_PRINTS_what_it_counted():
    parts = make_parts(
        para(run("But (Nobody 1999) has no entry.")) + ENTRIES)

    text = link_all(parts).format()

    assert "unmatched 1" in text
    assert "UNMATCHED: 'Nobody 1999' (¶1)" in text, text


def test_the_link_rest_report_PRINTS_what_it_counted():
    parts = make_parts(
        para(run("First (Kanbur 2007) here."))
        + para(run("But (Nobody 1999) has no entry.")) + ENTRIES)
    link_all(parts)

    text = link_rest(parts).format()

    assert "UNMATCHED: 'Nobody 1999' (¶2)" in text, text


# `bids = iter(range(bid, bid + 4096))` is EQUIVALENT under every
# mutation of its second operand and left alive: the pool starts at the
# first unused id either way, so the ids stay unique and unused, and
# nothing downstream reads their VALUES — only Word does, and only to
# tell them apart.
#
# `sorted(set(plan) | set(by_entry))` mutated to `^` is EQUIVALENT too:
# `plan` holds body paragraphs outside the reference block and
# `by_entry` holds entry paragraphs inside it, so the two sets are
# disjoint by construction and the symmetric difference is the union.

#
# `_foreign_bookmark`'s `n.endswith("txt")` skip is EQUIVALENT under
# every mutation and left alive. It mirrors the key-shaped path above
# it, where `<key>txt` is the BACK-LINK anchor this module mints and
# adopting one as the entry's would point every citation at itself. A
# foreign scheme's back-link is named by ITS own convention, so the
# guard fires on nothing a foreign paper contains — but it is what
# stops this module's own txt anchor being adopted on a package where
# the key-shaped path found no partner for it, and that is worth a line.


# `scan`'s `name = self.names[hits[0].index]` is EQUIVALENT under
# `hits[-1]` and left alive: two entries under one key is refused three
# lines above, so the list has exactly one element by the time this
# reads it.

# --- a surname the grammar cannot infer, and the entry list can -------
#
# Free capitalised adjacency is refused by the in-text grammar on
# purpose: it would file "As Smith (2020) shows" under "As Smith". That
# refusal is right for GUESSING and wrong when the answer is in the
# document, and the difference showed on Aging_Well as a link over half
# a name — `de São ` black, immediately before a blue underlined
# `José`. Nothing caught it: `citations` reported 82 of 82 mentions
# linked with 0 broken, because the anchor resolved and the label was
# not empty.

PARTICLE_ENTRIES = (
    para(run("References"))
    + para(run("de São José, J., and Timonen, V. 2019. \"Ageing well.\" "
               "Journal of Ageing 12: 1-20.")))


def _linked(parts):
    """(anchor, visible label) for every link in the body."""
    doc = parts["word/document.xml"]
    doc = doc.decode("utf-8") if isinstance(doc, bytes) else doc
    return internal_links(doc)


def test_a_PARTICLE_surname_is_linked_WHOLE():
    """The span, not just the anchor — which is what the old report
    got right while the page was wrong."""
    parts = make_parts(
        para(run("de São José et al. (2019) set out a framework."))
        + PARTICLE_ENTRIES)

    link_all(parts)

    labels = [label for _anchor, label in _linked(parts)]
    assert "de São José et al. (2019)" in labels, labels
    assert "José et al. (2019)" not in labels, "the particle was clipped"


def test_the_anchor_was_ALREADY_right_which_is_why_nothing_caught_it():
    """The entry side parsed the surname correctly all along, particle
    and all. Only the in-text side was guessing, so every check that
    reads the anchor agreed with itself."""
    parts = make_parts(
        para(run("de São José et al. (2019) set out a framework."))
        + PARTICLE_ENTRIES)

    link_all(parts)

    anchors = {anchor for anchor, _ in _linked(parts)}
    assert any(a.startswith("deSaoJose2019") for a in anchors), anchors


def test_a_bare_capitalised_adjacency_is_still_NOT_a_surname():
    """The refusal this fix must not undo. "As Smith (2020) shows" has
    to file under Smith, or every sentence-opening word joins the name
    of whoever it introduces."""
    from docxkit.citations import find_citations

    (found,) = find_citations("As Smith (2020) shows", ("Smith",))

    assert found.surname == "Smith"


def test_a_name_the_list_does_not_carry_is_left_to_the_grammar():
    """Told nothing, the scanner behaves exactly as before — the
    alternation is an addition, not a replacement."""
    from docxkit.citations import find_citations

    text = "van der Klaauw (2008) shows"

    assert [c.surname for c in find_citations(text)] == ["van der Klaauw"]
    assert [c.surname for c in find_citations(text, ("Ravallion",))] == \
        ["van der Klaauw"]


def test_the_LONGEST_known_name_wins():
    """With both "José" and "de São José" in the list, an alternation
    that settled for the shorter one would re-create the defect."""
    from docxkit.citations import find_citations

    (found,) = find_citations("de São José et al. (2019) argues",
                              ("José", "de São José"))

    assert found.surname == "de São José"


# --- the whole sweep of 2026-09-15 ------------------------------------


def test_a_foreign_own_marker_is_found_BEHIND_one_that_names_no_year():
    """`_foreign_bookmark` steps over a name that does not end with the
    work's year — a `_Toc` anchor, a comment range — and the entry's own
    `ref_kanbur_2007` can come after it. Stopping there reads a fully
    linked work as unmarked, and the pass mints `Kanbur2007` beside the
    paper's own marker: the second apparatus this reader exists to
    prevent. Every earlier fixture had the one name alone.
    """
    own = ('<w:bookmarkStart w:id="7" w:name="_Toc12345"/>'
           '<w:bookmarkEnd w:id="7"/>'
           '<w:bookmarkStart w:id="8" w:name="ref_kanbur_2007"/>'
           '<w:bookmarkEnd w:id="8"/>')
    linked = ('<w:hyperlink w:anchor="ref_kanbur_2007">'
              "<w:r><w:t>Kanbur 2007</w:t></w:r></w:hyperlink>")
    parts = make_parts(
        para(run("A point ("), linked, run(")."))
        + para(run("References")) + own
        + para(run("Kanbur, R. (2007). Poverty and distribution. Journal.")))

    report = link_all(parts)

    assert report.already == ["ref_kanbur_2007"], report.format()
    names = BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8"))
    assert names == ["_Toc12345", "ref_kanbur_2007"], names


def test_a_NEW_work_in_a_prefix_scheme_paper_gets_the_SUFFIX_twin():
    """A paper wired as `ref_<work>` / `cite_<work>` teaches the rule
    ("ref", "cite"), and a work added since has no name in that scheme:
    it is minted `Ravallion2016`, which does not start with "ref", so
    its twin is the suffix form. That branch of `_twin_of` had never
    been reached — its `+` could have been any operator at all, and the
    first document to need it would have stopped the pass with a
    TypeError.
    """
    mention = ('<w:bookmarkStart w:id="1" w:name="cite_kanbur_2007"/>'
               '<w:hyperlink w:anchor="ref_kanbur_2007">'
               "<w:r><w:t>Kanbur 2007</w:t></w:r></w:hyperlink>"
               '<w:bookmarkEnd w:id="1"/>')
    entry = ('<w:p><w:bookmarkStart w:id="2" w:name="ref_kanbur_2007"/>'
             '<w:bookmarkEnd w:id="2"/>'
             '<w:hyperlink w:anchor="cite_kanbur_2007">'
             "<w:r><w:t>Kanbur, R. (2007)</w:t></w:r></w:hyperlink>"
             + run(". Poverty and distribution. Journal.") + "</w:p>")
    parts = make_parts(
        para(run("A point ("), mention, run(") and (Ravallion 2016)."))
        + para(run("References")) + entry
        + para(run("Ravallion, M. (2016). The Economics of Poverty. OUP.")))

    report = link_all(parts)

    assert report.linked == ["Ravallion2016 @ ¶1"], report.format()
    assert sorted(BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8"))) == [
            "Ravallion2016", "Ravallion2016txt",
            "cite_kanbur_2007", "ref_kanbur_2007"]
    assert ("Ravallion2016txt", "Ravallion, M. (2016)") in _links(parts)


def test_an_INSTITUTIONAL_author_cited_with_its_own_acronym_is_wired():
    """BACKLOG S2, 2026-09-18: the entry got its bookmark and the
    mention stayed plain text.

    The author is an organisation that names itself with an acronym —
    the form `_entry_keys` already licenses, so "(UNICEF 2022)" linked
    and the acronym is not what was wrong. What failed is the mention
    that repeats the name as the entry spells it, parenthesis and all:
    that is a citation group holding a nested one, which the scanner
    refused to read (`test_a_work_BESIDE_a_nested_aside_is_still_cited`
    is the same defect at the grammar). Half the apparatus was built and
    the report said nothing, because the half that works is the half
    that leaves evidence.

    Asserted as the PAIR, both ends: the entry's bookmark alone is what
    the defect already produced.
    """
    org = ("State Committee of the Republic of Uzbekistan on Statistics "
           "and United Nations Children's Fund (UNICEF)")
    parts = make_parts(
        para(run(f"The survey ({org} 2022) covers households."))
        + para(run("References"))
        + para(run(f"{org}. (2022). MICS 2021-2022. Tashkent.")))

    report = link_all(parts)

    (name,) = [n for n in BOOKMARK_NAME_RE.findall(
        parts["word/document.xml"].decode("utf-8")) if not n.endswith("txt")]
    assert report.linked == [f"{name} @ ¶1"], report.format()
    anchors = dict(_links(parts))
    assert anchors[name].endswith("2022"), anchors
    assert anchors[f"{name}txt"].startswith("State Committee"), anchors


def test_the_HALF_LINKED_line_is_printed_only_when_something_WAS_repaired():
    """`if self.repaired`, in both directions: a clean round must not
    print the heading of a list with nothing after it, and a round that
    rebuilt a bookmark must say which. Whole values, because a substring
    test for the heading passes over its empty version too.
    """
    from docxkit._cite_build import LinkAllReport

    counts = ("linked 0, already linked 0, back-links added 0, "
              "unmatched 0, skipped 0")

    assert LinkAllReport().format() == counts
    assert LinkAllReport(repaired=["Kanbur2007 @ ¶1"]).format() == (
        counts + "\n  half-linked, bookmark rebuilt under the surviving "
        "link: Kanbur2007 @ ¶1")
