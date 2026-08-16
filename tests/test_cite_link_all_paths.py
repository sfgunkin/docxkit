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

from conftest import make_parts, para, run

from docxkit._xml import BOOKMARK_NAME_RE, internal_links
from docxkit.citations import link_all, link_rest

ENTRIES = (
    para(run("References"))
    + para(run("Kanbur, R. (2007). Poverty and distribution. Journal."))
    + para(run("Ravallion, M. (2016). The Economics of Poverty. OUP.")))


def _notes(*texts: str) -> str:
    body = "".join(f'<w:footnote w:id="{i + 2}">{para(run(t))}</w:footnote>'
                   for i, t in enumerate(texts))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
            f'wordprocessingml/2006/main">{body}</w:footnotes>')


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
    note = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:footnote w:id="2"><w:p>'
            + run("See ") + linked + "</w:p></w:footnote></w:footnotes>")
    parts = make_parts(
        para(run("A point (Kanbur 2007).")) + ENTRIES, footnotes=note)

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
    assert not any("removed" in note for note in report.skipped), \
        report.format()


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
