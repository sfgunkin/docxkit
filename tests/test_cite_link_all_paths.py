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
from docxkit.citations import link_all, link_rest

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
