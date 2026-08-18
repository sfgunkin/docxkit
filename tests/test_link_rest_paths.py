"""`link_rest`'s engine, stated as values.

`rewrite` carried 36 survivors on 2026-08-16 — the largest single
cluster in the package. It is the second linking pass: `link_all` wires
each work's FIRST mention and bookmarks it, and this forward-links every
LATER mention to the entry. Its existing tests checked that some link
appeared; nothing checked WHICH span was wrapped, which paragraph was
reported, or that a second run changes nothing.

Four decisions live in it, and each was unasserted:

* which citations are already inside a link, read off a MASK rather than
  the text — that is what makes the pass idempotent;
* how far a mention is widened over an institution's name, and when the
  widening is abandoned because it would reach into a link;
* the order spans are applied in, bottom-up per paragraph AND
  bottom-up across paragraphs, so earlier offsets stay valid;
* which paragraph a report line names, in the body and in a footnote.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run

from docxkit._xml import internal_links, visible_text
from docxkit.citations import link_all, link_rest

ENTRIES = (
    para(run("References"))
    + para(run("Kanbur, R. (2007). Poverty and distribution. Journal."))
    + para(run("World Bank Group. (2024). World Development Report.")))


def _linked(parts: dict[str, bytes], part: str = "word/document.xml"):
    """(anchor, label) for every internal link, in document order."""
    return internal_links(parts[part].decode("utf-8"))


def _wired(body: str, footnotes: str | None = None) -> dict[str, bytes]:
    """A document with link_all already run, which is link_rest's input."""
    parts = make_parts(body + ENTRIES, footnotes=footnotes)
    link_all(parts)
    return parts


FILLER = para(run("A sentence with nothing to link in it.")) * 2


def test_a_LATER_mention_is_linked_and_the_first_one_is_left_alone():
    """The reported paragraph sits at index 3. `¶{i + 1}` mutates to
    eleven arithmetic operators and several agree with the original at
    any given index — this assertion read ¶2 until 2026-08-16, where
    `i << 1` gives the same 2 and lived through the round.
    """
    parts = _wired(
        para(run("First (Kanbur 2007) here."))
        + FILLER
        + para(run("Again (Kanbur 2007) there.")))

    before = _linked(parts)
    report = link_rest(parts)
    after = _linked(parts)

    assert len(after) == len(before) + 1, report.format()
    # the in-text label is the citation INSIDE its parentheses; the
    # entry's own back-link is the `…txt` one link_all wrote
    assert [a for a, _ in after].count("Kanbur2007") == 2
    assert ("Kanbur2007txt", "Kanbur, R. (2007)") in after
    assert report.linked == ["Kanbur2007 @ ¶4"], report.linked


def test_the_span_wrapped_is_the_CITATION_not_the_sentence():
    parts = _wired(para(run("First (Kanbur 2007)."))
                   + para(run("The point recurs (Kanbur 2007) later on.")))
    link_rest(parts)

    labels = [label for a, label in _linked(parts) if a == "Kanbur2007"]
    assert labels == ["Kanbur 2007", "Kanbur 2007"], labels
    assert not any("recurs" in label or "later" in label for label in labels)


def test_a_mention_is_WIDENED_over_the_institutions_whole_name():
    """The citation grammar refuses free capitalised adjacency, so
    "World Bank Group (2024)" is captured as "Group (2024)" — and a link
    labelled "Group (2024)" is not what the entry is called."""
    parts = _wired(para(run("First (World Bank Group 2024)."))
                   + para(run("Again World Bank Group (2024) reports.")))
    link_rest(parts)

    labels = [label for _, label in _linked(parts)]
    assert any("World Bank Group" in label for label in labels), labels


def test_running_it_TWICE_changes_nothing():
    """Idempotence is the property the mask exists for: a linked
    citation is masked out of the next scan, so a build can run this
    every round."""
    parts = _wired(para(run("First (Kanbur 2007)."))
                   + para(run("Again (Kanbur 2007).")))
    link_rest(parts)
    once = parts["word/document.xml"]

    report = link_rest(parts)

    assert parts["word/document.xml"] == once
    assert not report.linked, report.format()


def test_TWO_mentions_in_one_paragraph_are_both_wrapped():
    """Spans are applied bottom-up within the paragraph; applying them
    top-down invalidates every offset after the first."""
    parts = _wired(
        para(run("First (Kanbur 2007) and (World Bank Group 2024)."))
        + para(run("Again (Kanbur 2007) and again (World Bank Group 2024).")))

    link_rest(parts)

    text = visible_text(parts["word/document.xml"].decode("utf-8"))
    assert "Again (Kanbur 2007) and again (World Bank Group 2024)." in text, \
        "an offset went stale and the second wrap landed wrong"
    anchors = [a for a, _ in _linked(parts)]
    assert anchors.count("Kanbur2007") >= 2
    assert sum(1 for a in anchors if a.startswith("World")) >= 2


def test_the_reference_ENTRIES_are_never_rewritten_as_prose():
    """The block bounds are what tell an entry from a sentence. The
    entry paragraph legitimately carries link_all's back-link; what it
    must not gain is a FORWARD link from this pass, which would point
    the entry's own head at itself."""
    from docxkit._xml import PARA_RE

    parts = _wired(para(run("First (Kanbur 2007).")))
    entries_before = [internal_links(m.group(0)) for m
                      in PARA_RE.finditer(parts["word/document.xml"]
                                          .decode("utf-8"))][2:]

    link_rest(parts)

    entries_after = [internal_links(m.group(0)) for m
                     in PARA_RE.finditer(parts["word/document.xml"]
                                         .decode("utf-8"))][2:]
    assert entries_after == entries_before
    assert all(a.endswith("txt") for links in entries_after
               for a, _ in links), entries_after


def test_a_footnotes_LATER_mention_is_linked_and_reported_as_fn():
    note = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:footnote w:id="2">'
            + para(run("See also (Kanbur 2007) on this."))
            + "</w:footnote></w:footnotes>")
    parts = _wired(para(run("First (Kanbur 2007).")), footnotes=note)

    report = link_rest(parts)

    assert _linked(parts, "word/footnotes.xml"), report.format()
    assert any(entry.endswith("fn¶1") or "fn¶" in entry
               for entry in report.linked), report.linked


def test_a_citation_with_NO_entry_is_reported_with_its_paragraph():
    parts = _wired(para(run("First (Kanbur 2007)."))
                   + para(run("But (Nobody 1999) has no entry here.")))

    report = link_rest(parts)

    # the EXACT paragraph, not merely "a paragraph": a finding whose
    # location is off by one sends the reader to the sentence before,
    # and an off-by-one is what an index arithmetic slip produces
    assert report.unmatched == ["'Nobody 1999' (¶2)"], report.unmatched


def test_link_rests_options_are_KEYWORD_only():
    """The third function in this package found with the same hole:
    cosmic-ray mutates the keyword-only `*` to a positional-only `/`,
    and `link_rest(parts, aliases)` then becomes legal. `aliases`,
    `heading` and `ignore` each change which works are found, and a
    caller that passes one by position says nothing about which.
    """
    parts = make_parts(para(run("A point (Kanbur 2007).")) + ENTRIES)

    with pytest.raises(TypeError):
        link_rest(parts, {"WHO": "World Health Organization"})  # type: ignore[call-arg]


def test_link_rest_REFUSES_a_document_link_all_has_not_touched():
    """It resolves anchor names from the entry bookmarks `link_all`
    wrote, so running it first is not a suggestion."""
    parts = make_parts(para(run("A mention (Kanbur 2007).")) + ENTRIES)

    report = link_rest(parts)

    assert not report.linked
    assert any("link_all" in note for note in report.skipped), report.skipped


def test_widening_is_ABANDONED_when_it_would_reach_into_a_link():
    """The guard behind the widening. "World Bank Group (2024)" is
    captured narrowly as "Group (2024)", and widening it over the
    institution's name is an improvement — unless the earlier words are
    already inside somebody else's link, where widening would wrap a
    span that overlaps it. Then the narrow span stands: linking less
    prettily, never worse."""
    linked = ('<w:hyperlink w:anchor="Kanbur2007">'
              '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
              "<w:t>World Bank</w:t></w:r></w:hyperlink>")
    parts = _wired(
        para(run("First (World Bank Group 2024) and (Kanbur 2007)."))
        + "<w:p>" + linked + run(" Group (2024) reports again.") + "</w:p>")

    report = link_rest(parts)

    labels = [label for a, label in _linked(parts)
              if a == "WorldBankGroup2024"]
    assert "Group (2024)" in labels or "Group 2024" in labels, (
        f"the narrow span should have been used: {labels} / "
        f"{report.format()}")
    assert not any("World Bank Group (2024)" in label for label in labels), \
        "the widening crossed into the existing link"
    # and nothing nested: every link element still closes before the next
    doc = parts["word/document.xml"].decode("utf-8")
    depth = 0
    for token in doc.split("<w:hyperlink")[1:]:
        depth += 1
        assert "</w:hyperlink>" in token, "an unclosed link element"
        depth -= 1
    assert depth == 0


# --------------------------- the skips, and what a refusal has to say --

CROSS_CITING = (
    para(run("References"))
    + para(run("Kanbur, R. (2007). Poverty, extending Ravallion (2016). "
               "Journal of Development Economics."))
    + para(run("Ravallion, M. (2016). The Economics of Poverty, after "
               "Kanbur (2007). Oxford University Press.")))


def test_the_reference_BLOCK_is_skipped_at_both_of_its_ends():
    """Entries cite each other — "extending Ravallion (2016)" inside a
    reference is ordinary — and those are not mentions to link. The
    block is skipped as a RANGE, and a range has two ends: mutated to
    an equality it protects one entry and rewrites the rest, which
    turns the bibliography into cross-linked prose.
    """
    parts = make_parts(para(run("A point (Kanbur 2007) and (Ravallion "
                                "2016).")) + CROSS_CITING)
    link_all(parts)
    entries_before = parts["word/document.xml"]

    report = link_rest(parts)

    assert parts["word/document.xml"] == entries_before, report.format()
    assert not report.linked, report.format()


def test_an_IGNORED_citation_does_not_stop_the_paragraph():
    """`ignore` drops a lead the grammar mistakes for an author. The
    citation after it in the same paragraph is a different work and
    still has to be linked."""
    parts = _wired(
        para(run("First (Kanbur 2007) and (World Bank Group 2024)."))
        + FILLER
        + para(run("Again (Kanbur 2007), and (World Bank Group 2024).")))

    report = link_rest(parts, ignore={"Kanbur"})

    assert not any("Kanbur" in entry for entry in report.linked), report.linked
    assert any(entry.startswith("WorldBankGroup2024") for entry in
               report.linked), report.format()


def test_an_ALREADY_linked_citation_does_not_stop_the_paragraph():
    """The mask is what makes this pass idempotent, and a paragraph
    holding one linked citation and one plain one is what every round
    after the first looks like."""
    parts = _wired(
        para(run("First (World Bank Group 2024) here."))
        + para(run("Then (Kanbur 2007) and again (World Bank Group 2024).")))

    report = link_rest(parts)

    assert any(entry.startswith("WorldBankGroup2024") for entry in
               report.linked), report.format()


def test_an_entry_with_NO_bookmark_is_reported_with_its_paragraph():
    """`link_all(only=...)` names some entries and not others, and the
    second pass cannot link to a bookmark that was never written. It
    says which citation and where, because the fix is to widen `only`.
    """
    parts = make_parts(
        para(run("First (Kanbur 2007) and (World Bank Group 2024)."))
        + FILLER
        + para(run("Again (Kanbur 2007) and (World Bank Group 2024)."))
        + ENTRIES)
    link_all(parts, only=["kanbur_2007"])

    report = link_rest(parts)

    # the NARROW capture, because the widening over an institution's
    # name happens after this check — the citation grammar refuses free
    # capitalised adjacency, so "(World Bank Group 2024)" is caught as
    # "Group 2024" and the line quotes what was caught
    assert "'Group 2024' (¶4): entry has no bookmark" in report.skipped, \
        report.skipped


def test_a_citation_INSIDE_an_equation_is_reported_not_crashed():
    """The span comes from `visible_text`, which counts the maths; the
    wrap walks `w:r` runs, which do not contain it. So a citation typed
    into an equation object has offsets that no run covers. It is
    reported with its paragraph and the document is left exactly as it
    was — the alternative is an AnchorError out of `link_rest` and a
    build that stops on one odd paragraph.
    """
    maths = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
             'officeDocument/2006/math"><m:r><m:t>(Kanbur 2007)</m:t>'
             "</m:r></m:oMath>")
    parts = _wired(
        para(run("First (Kanbur 2007) here."))
        + FILLER
        + "<w:p>" + run("As ") + maths + run(" shows.") + "</w:p>")
    before = parts["word/document.xml"]

    report = link_rest(parts)

    assert any(entry.startswith("¶4: wrap_visible_span:")
               for entry in report.skipped), report.format()
    assert parts["word/document.xml"] == before, "the paragraph was rewritten"


# `sorted(todo, reverse=True)` in `rewrite` is deliberately NOT pinned.
# A mutation to `sorted(todo)` survives, and it survives because it is
# EQUIVALENT: `wrap_visible_span` takes VISIBLE offsets and wrapping
# changes no visible text, so applying the spans in either order gives
# the same document for the non-overlapping spans this pass produces.
# The reverse ordering is belt-and-braces against a future overlapping
# case. Recorded here so the next reader does not write a contrived test
# to kill an equivalent mutant -- which is how a suite gets slower
# without getting stronger.
