"""`scan`, the pass that decides which mention of a work is the FIRST.

Twenty-three mutants survived here on 2026-08-16 — the largest cluster
left in `_cite_build.py`, and the decision the whole first-mention
convention rests on. Eighteen of them sit outside the annotations PEP
563 makes unkillable, in three groups:

* four `continue`s turned into `break`, in the four places the scan
  skips something: a reference paragraph, a citation with no entry, a
  work already claimed, an anchor already linked;
* ten on the two report lines, where `¶{i + 1}` mutates six ways;
* four on the ambiguity finding — whether a collision is noticed at all,
  and which of the two entries the line then names.

`continue` and `break` differ only in what happens to the REST of the
list, so a fixture with one interesting citation per paragraph cannot
tell them apart — and every fixture this had was one per paragraph. The
tests here put a citation the pass must still find AFTER the one it
skips, in each of the four cases. Two of them are the arrangements real
manuscripts arrive in: a table note below the reference block, and a
sentence citing a new work alongside one already cited upstream.

The report lines name a paragraph, and `¶{i + 1}` mutates to seven
different arithmetic operators — `*`, `|`, `^`, `&`, `<<`, `//`, `**` —
several of which agree with the original at any particular `i`. Index 0
agrees with `|`, index 1 with `<<`, index 2 with `|` again. **Index 3 is
the smallest that separates all seven**, so that is where the reported
citations in this file sit, four paragraphs down a fixture that would
otherwise be two lines long. Index 1 was the first choice and it left
`i << 1` alive, which is how the number is known.
"""
from __future__ import annotations

from conftest import make_parts, para, run

from docxkit._xml import internal_links
from docxkit.citations import link_all

ENTRIES = (
    para(run("References"))
    + para(run("Kanbur, R. (2007). Poverty and distribution. Journal of "
               "Development Economics."))
    + para(run("Ravallion, M. (2016). The Economics of Poverty. Oxford "
               "University Press.")))


def _anchors(parts: dict[str, bytes]) -> list[str]:
    return [a for a, _ in internal_links(parts["word/document.xml"]
                                         .decode("utf-8"))]


def _linked_from_prose(parts: dict[str, bytes]) -> set[str]:
    """The in-text ends only: `link_all` also writes each entry a
    back-link, and that is not what this pass is being asked about."""
    return {a for a in _anchors(parts) if not a.endswith("txt")}


# ------------------------------------------------- the four skips, in turn --

def test_a_first_mention_BELOW_the_reference_block_is_still_linked():
    """The scan skips the reference block because an entry is not a
    mention. Stopping there instead would silently drop everything
    printed after it — and these papers put their exhibits after the
    references, so the source line under a table sits below the block
    and is exactly where a data source is first cited.

    The caption is what ENDS the block: `references` runs to the next
    caption or appendix heading, or to the end of the document. Without
    one the note is parsed as an entry itself, under the surname "Note:
    the poverty line follows (Kanbur" — which is why it is here.
    """
    parts = make_parts(
        para(run("Loneliness rises with age."))
        + ENTRIES
        + para(run("Table 1: Poverty headcounts by country"))
        + para(run("Note: the poverty line follows (Kanbur 2007).")))

    report = link_all(parts)

    assert _linked_from_prose(parts) == {"Kanbur2007"}, report.format()


def test_an_UNMATCHED_citation_does_not_stop_the_paragraph():
    """A citation with no entry is a finding, not a full stop. It is
    also the commonest thing in a draft — the reference list is written
    last — so a scan that gave up at the first one would link almost
    nothing in the manuscripts that need it most.
    """
    parts = make_parts(
        para(run("Both (Nobody 1999) and (Kanbur 2007) make the point."))
        + ENTRIES)

    report = link_all(parts)

    assert report.unmatched, "the citation with no entry went unreported"
    assert _linked_from_prose(parts) == {"Kanbur2007"}, (
        f"the scan stopped at the unmatched citation: {report.format()}")


def test_a_REPEAT_mention_does_not_stop_the_paragraph():
    """Once a work is claimed its later mentions are skipped — that is
    what makes the first mention the linked one. The sentence citing an
    old work and a new one together is ordinary prose, and the new one
    is a first mention that has to survive the skip.
    """
    parts = make_parts(
        para(run("Poverty measurement (Kanbur 2007) has a long history."))
        + para(run("As before (Kanbur 2007), and newly (Ravallion 2016)."))
        + ENTRIES)

    link_all(parts)

    assert _linked_from_prose(parts) == {"Kanbur2007", "Ravallion2016"}


def test_an_ALREADY_LINKED_anchor_does_not_stop_the_paragraph():
    """A rebuild runs over a document that is already part-linked, so
    this skip fires on every round after the first. Stopping here would
    make the pass progressively blinder the more of the paper was
    already done.
    """
    existing = ('<w:hyperlink w:anchor="Kanbur2007">'
                '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                "<w:t>Kanbur 2007</w:t></w:r></w:hyperlink>")
    parts = make_parts(
        "<w:p>" + run("An earlier pass linked ") + existing + "</w:p>"
        + para(run("Here again (Kanbur 2007) beside (Ravallion 2016)."))
        + ENTRIES)

    report = link_all(parts)

    assert "Kanbur2007" in report.already, report.format()
    assert "Ravallion2016" in _linked_from_prose(parts), (
        f"the scan stopped at the already-linked anchor: {report.format()}")


# ------------------------------------------------------ what a report says --

def test_an_unmatched_citation_is_reported_with_its_OWN_paragraph():
    """The paragraph number is the whole value of the line: the author
    goes there to fix it. An index one out sends them to the sentence
    before, and looks exactly as authoritative.
    """
    parts = make_parts(
        para(run("Ageing raises the risk of isolation."))
        + para(run("The gradient is steeper in the eastern countries."))
        + para(run("Two mechanisms have been proposed for it."))
        + para(run("But (Nobody 1999) has no entry in this list."))
        + ENTRIES)

    report = link_all(parts)

    assert report.unmatched == ["'Nobody 1999' (¶4)"], report.unmatched


def test_two_entries_under_ONE_key_are_reported_not_guessed():
    """Two entries the citation names equally well. Linking it to
    either sends the reader to a work the sentence may not mean, and
    nothing downstream shows it: the anchor resolves, the words read
    correctly. So it is reported, with the count and the entry — and
    with what to do about it, which is the author's to do.
    """
    parts = make_parts(
        para(run("Ageing raises the risk of isolation."))
        + para(run("The gradient is steeper in the eastern countries."))
        + para(run("Two mechanisms have been proposed for it."))
        + para(run("Poverty is measured thus (Kanbur 2007)."))
        + para(run("References"))
        + para(run("Kanbur, R. (2007). Poverty. Journal of Development."))
        + para(run("Kanbur, A. (2007). Distribution. Another Journal.")))

    report = link_all(parts)

    assert report.unmatched == [
        "'Kanbur 2007' (¶4) matches 2 entries (Kanbur 2007) "
        "-- give them 'a'/'b' year suffixes to tell them apart"
    ], report.unmatched
    assert not _linked_from_prose(parts), "the pass guessed one of the two"


def test_the_ambiguity_report_names_the_entry_as_the_LIST_spells_it():
    """The key ignores punctuation on purpose, so "O'Brien" and
    "OBrien" are one key and one collision — a reference list typed over
    two sittings really does hold both. The line names the FIRST of the
    colliding entries, spelled as the list spells it, because that is
    what the author scans the list for.
    """
    parts = make_parts(
        para(run("Ageing raises the risk of isolation."))
        + para(run("The gradient is steeper still (O'Brien 2019)."))
        + para(run("References"))
        + para(run("O'Brien, M. (2019). Isolation in later life. Ageing."))
        + para(run("OBrien, T. (2019). A different paper. Another Journal.")))

    report = link_all(parts)

    assert len(report.unmatched) == 1, report.format()
    line = report.unmatched[0]
    assert "matches 2 entries (O'Brien 2019)" in line, line


# The YEAR in that line -- `by_key[key][0].year` -- cannot be pinned, and
# the mutant that indexes a different entry for it is EQUIVALENT: two
# entries share a key only when `key_for(surname, year)` agrees, and the
# year goes into the key verbatim, so every entry in the list has the
# same one. The surname above is a different matter, because the key
# strips punctuation and case out of it first.
