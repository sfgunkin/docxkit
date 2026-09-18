"""Where the reference list ENDS, and what may be filed as an entry.

The S1 behind this file: a journal's back matter sits after the
references, "The data are drawn from Eurostat (2023)." carries a year,
`parse_reference` cannot tell that shape from "World Bank Group.
(2024)." — and the sentence became an entry. `_entry_keys` then licensed
every word run of the supposed institutional name, `eurostat_2023`
among them, so a real "(Eurostat 2023)" in the paper resolved through it
and linked to the data-availability line. The anchor resolved, so
`crossrefs --audit` passed; the words read correctly, so no text diff
moved; and the report said "linked 1, unmatched 0".

Two layers, because the first cannot be complete:

* the block bounds — the back-matter headings now end the list, matched
  as a prefix so "Data availability statement" ends it too;
* `reads_as_prose`, for the case with no heading at all, which no bound
  can catch. It does not refuse the entry; it REPORTS it, because
  refusing would mean deciding on a rule that has to hold across
  languages, and this one deliberately does not.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run

from docxkit._cite_grammar import _reads_as_prose as reads_as_prose
from docxkit._xml import internal_links
from docxkit.citations import link_all

BODY = para(run("Employment rates come from the register (Eurostat 2023)."))
ENTRIES = (para(run("References"))
           + para(run("Kanbur, R. (2007). Poverty and distribution. "
                      "Journal of Development Economics.")))
DATA_NOTE = para(run("The data are drawn from Eurostat (2023)."))


def _links(parts: dict[str, bytes]) -> list[tuple[str, str]]:
    return internal_links(parts["word/document.xml"].decode("utf-8"))


# ------------------------------------------------------- the block bounds --

@pytest.mark.parametrize("heading", [
    "Data availability",
    "Data availability statement",       # the prefix, not the whole heading
    "Acknowledgements",
    "Funding",
    "Author contributions",
    "Notes",
    "Благодарности",
])
def test_back_matter_does_not_extend_the_reference_list(heading):
    parts = make_parts(BODY + ENTRIES + para(run(heading)) + DATA_NOTE)

    report = link_all(parts)

    assert not any(a.startswith("Thedata") for a, _ in _links(parts)), (
        f"the citation linked to the {heading!r} sentence: {report.format()}")
    # both are reported, and the second is the point: the note is read as
    # PROSE now, so its own "(2023)" is a citation with no entry rather
    # than an entry that other citations resolve through
    assert report.unmatched == ["'Eurostat 2023' (¶1)",
                                "'Eurostat (2023)' (¶5)"], report.unmatched
    assert not report.suspect, report.format()


def test_the_citation_still_links_when_the_work_IS_listed():
    """The bound must not cost a real link: the same document with a
    genuine Eurostat entry inside the block still resolves."""
    parts = make_parts(
        BODY + ENTRIES
        + para(run("Eurostat. (2023). Labour force survey. Luxembourg."))
        + para(run("Data availability")) + DATA_NOTE)

    link_all(parts)

    assert ("Eurostat2023", "Eurostat 2023") in _links(parts)


def test_an_author_named_Notes_does_not_end_the_list():
    """A stop word at the start only ends the list when the paragraph is
    not itself an entry — otherwise adding back-matter headings would
    quietly truncate somebody's reference list at the letter N."""
    parts = make_parts(
        para(run("As shown (Notes 2019) and (Kanbur 2007)."))
        + ENTRIES
        + para(run("Notes, A. (2019). A real entry. Journal of Things.")))

    link_all(parts)

    anchors = [a for a, _ in _links(parts)]
    assert "Notes2019" in anchors, anchors
    assert "Kanbur2007" in anchors, anchors


# ------------------------------------------- what may be filed as an entry --

def test_a_sentence_filed_as_an_entry_is_REPORTED():
    """No heading at all — a source line sitting straight after the last
    entry. The bounds cannot see this one, so the report has to."""
    parts = make_parts(BODY + ENTRIES + DATA_NOTE)

    report = link_all(parts)

    assert len(report.suspect) == 1, report.format()
    assert "The data are drawn from Eurostat" in report.suspect[0]
    assert "¶4" in report.suspect[0], report.suspect
    assert "suspect 1" in report.format()


def test_the_suspect_line_QUOTES_the_surname_but_does_not_dump_it():
    """A surname that reads as prose is a sentence, and a sentence in a
    report line is a line nobody reads to the end. Cut at the same
    length the anchor refusals use."""
    long_name = ("The data in this table are drawn from the register held "
                 "by Eurostat and the national statistical offices")
    parts = make_parts(
        BODY + ENTRIES + para(run(f"{long_name} (2023).")))

    report = link_all(parts)

    assert len(report.suspect) == 1, report.format()
    assert long_name[:60] in report.suspect[0]
    assert long_name[:61] not in report.suspect[0], "the surname was not cut"


@pytest.mark.parametrize("surname", [
    "The data are drawn from Eurostat",
    "Note: the poverty line follows (Kanbur",
    "Estimates in this table are based on Rosstat",
])
def test_reads_as_prose_catches_a_sentence(surname):
    assert reads_as_prose(surname)


@pytest.mark.parametrize("surname", [
    "Kanbur",
    "World Bank Group",
    "van der Berg",
    "de Souza",
    "U.S. Census Bureau",
    "United Nations",
    "Ministry of Health of the Republic of Kazakhstan",
    "Organisation for Economic Co-operation and Development",
    "Институт демографии Национального исследовательского университета",
    "Министерство здравоохранения Республики Казахстан",
])
def test_reads_as_prose_leaves_a_NAME_alone(surname):
    """The false positives are what would make this report worthless.
    The Cyrillic pair is the reason the test is Latin-script only: a
    Russian institution is full of lowercase content words, and a line
    that fires on every DSI build is a line nobody reads.
    """
    assert not reads_as_prose(surname)


# --- the blank line in the middle of a reference list (2026-08-19) -----

def test_a_BLANK_paragraph_inside_the_list_does_not_end_it():
    """`continue`, not `break`. Word documents are full of empty spacer
    paragraphs and a reference list typed by hand has them between
    entries — under `break` the first one ends the list, every entry
    below it is invisible, and every citation to those works reports as
    having no entry."""
    from docxkit.citations import references

    entries = references(["Body prose.", "References",
                          "Aksoy, C. (2026). A first paper. JEP.",
                          "",
                          "Brown, A. (2020). A second paper. AER.",
                          "   ",
                          "Chen, D. (2019). A third paper. QJE."])

    assert [r.surname for r in entries] == ["Aksoy", "Brown", "Chen"]


def test_a_reference_parsed_on_its_own_carries_NO_paragraph():
    """`index: int = -1`: the default says "this came from nowhere in
    particular", and every report that prints a paragraph number adds
    one to it. A default of 0 or 1 makes a reference parsed in isolation
    claim to be the first paragraph of the document."""
    from docxkit.citations import parse_reference

    ref = parse_reference("Aksoy, C. (2026). A paper. JEP.")

    assert ref is not None
    assert ref.index == -1


# --- the run of 2026-08-20: 5.1 % --------------------------------------


def test_prose_needs_FOUR_words_before_it_is_prose():
    """`len(words) < 4`, the threshold under which an author field is
    too short to judge. Both sides of it are load-bearing and only one
    was pinned: three words is "World Bank Group", and four is where a
    sentence starts being one.

    Read as `== 4` the guard swallows exactly the four-word sentences it
    exists to catch; read as `< 3` it calls "Data are drawn" an author
    field that reads as prose, and every three-word institution with a
    lowercase word in it — "Bureau des Statistiques" — goes with it."""
    from docxkit._cite_grammar import _reads_as_prose

    assert _reads_as_prose("The data are drawn") is True
    assert _reads_as_prose("Data are drawn") is False
    assert _reads_as_prose("World Bank Group") is False


def test_an_impossible_span_QUOTES_the_paragraph_it_could_not_wrap():
    """`visible_text(para_xml)[:40]`. The refusal names offsets, and
    offsets belong to a paragraph the caller computed them from — which
    is the one thing they cannot check by reading the message unless it
    quotes the text as well."""
    from docxkit._cite_grammar import wrap_visible_span
    from docxkit.errors import AnchorError

    para_xml = ("<w:p><w:r><w:t>The Age-Friendly Index for the Republic "
                "of Kazakhstan, second draft</w:t></w:r></w:p>")

    with pytest.raises(AnchorError) as caught:
        wrap_visible_span(para_xml, 5, 500, "Name")

    assert "'The Age-Friendly Index for the Republic '" in str(caught.value)


# Argued rather than pinned, from the same run:
#
# * `authors == c.authors` in `resolve_lead`, written `is`. `authors` is
#   what `strip_lead` (and then `_drop_unlisted_head`) returned, and a
#   str method that strips nothing hands back the string it was given —
#   so when there is nothing to trim the two ARE one object.
# * `len(_CHAIN_SPLIT_RE.split(...)) > 1` written `!= 1`: a split
#   returns at least one piece.
# * `len(words) < 2` in `extend_to_name` written `< 1`. Below two the
#   walk can only extend over a REPETITION of the entry's single word —
#   "Kanbur Kanbur (2007)" — which no reference list contains, and the
#   settle loop then hands back the span it started with.
# * `at = m.start(1)` written `m.start(0)`. `_PREV_WORD_RE` is
#   `(\\S+)[ \\u00a0]+$`: the group opens where the match does.
# * the six mutants on `len(flat) == len(stop)` in `_ends_the_list`.
#   That equality is only true when `flat` IS the stop word, and
#   `if flat in stops: return True` two lines above has already
#   answered that paragraph — so the comparison is reached only where
#   it is false, and every reading of it agrees there.
# * `range(start + 1, …)` in `references`, written `+ 0`, `// 1` and
#   `| 1` — all of which include the HEADING paragraph. It is not a
#   stop word and it does not parse as an entry, so the loop's
#   `continue` takes it and the list comes out the same.
# * `zip(spans, runs, strict=True)` in `wrap_visible_span`:
#   `run_spans` returns one span per run by construction.
# * `at > fs` and `end < le` there, written `!=`. `fs` is the start of
#   the first run the span covers and `le` the end of the last, so
#   `at < fs` and `end > le` are both outside the coverage test that
#   selected them.
# * `if first is last:` written `==`. `re.Match` defines no `__eq__`,
#   so equality IS identity for it.
# * `run_xml.replace("<w:rPr>", …, 1)` written 2: a run has one `w:rPr`.


def test_a_line_that_merely_STARTS_LIKE_a_stop_word_does_not_end_the_list():
    """The bound is a PREFIX match, so "Data availability statement"
    ends the list — and the guard beside it is what keeps the prefix
    from swallowing a longer word: the character after the stop word
    has to be a non-alphanumeric one.

    "Notes" is a stop word and Notestein is a demographer, so a
    reference list that files his archive — a line with no year, which
    `parse_reference` therefore reads as no entry at all — is exactly
    the shape that tells the two readings apart. Without the guard the
    list ends there and every work below it reports as having no entry,
    which is the S1 this file exists for, running the other way."""
    from docxkit.citations import references

    entries = references(["Body prose.", "References",
                          "Aksoy, C. (2026). A first paper. JEP.",
                          "Notestein Papers, Princeton University Library.",
                          "Brown, A. (2020). A second paper. AER."])

    assert [r.surname for r in entries] == ["Aksoy", "Brown"]


def test_a_stop_word_with_a_SPACE_after_it_still_ends_the_list():
    """The other side of the same character: a heading is the stop word
    and then something else, and that is the case the prefix match is
    FOR."""
    from docxkit.citations import references

    entries = references(["Body prose.", "References",
                          "Aksoy, C. (2026). A first paper. JEP.",
                          "Notes on the sources",
                          "Brown, A. (2020). A second paper. AER."])

    assert [r.surname for r in entries] == ["Aksoy"]


# --- what the run of 2026-08-20 left in `_cite_grammar` ----------------
#
# 4.2 % (18/428). Three of the six spellings of the stop-word guard are
# the tests above; the other three are equivalent, and for a reason
# worth writing down: `flat in stops` returns True a few lines EARLIER,
# so by the time that comparison runs, `len(flat) == len(stop)` is
# already known to be False — a prefix of equal length IS the stop word.
# `<`, `<=` and `is` all answer False there, which is what `==` answers;
# `!=`, `>=` and `is not` answer True, which short-circuits the `or` and
# ends the list on any line that merely begins like a stop word.
#
# The rest, each checked with kill_check:
#
# * `range(start + 1, ...)` in `references`, as `+ 0` and `| 1`. The
#   paragraph they would add back is the HEADING, and a heading is
#   neither an entry (`parse_reference("References")` is None) nor a
#   stop word for its own list — so including it changes nothing.
# * `len(_CHAIN_SPLIT_RE.split(...)) > 1` as `!= 1`: a split answers
#   with at least one piece.
# * `first is last` in `wrap_visible_span` as `==`: `re.Match` defines
#   no `__eq__`, so equality IS identity.
# * `at > fs` and `end < le` as `!=`: the span is inside the run it was
#   found in, so the offsets can only fall one way.


# --- the grammar's DATA census, 2026-09-18 ------------------------------


@pytest.mark.parametrize("dashes", ["---", "———", "___", "–––"])
def test_a_repeated_author_entry_inherits_whatever_dash_it_is_written_with(
        dashes):
    """`_CONTINUATION_RE`'s character class, taken apart a member at a
    time. The UNDERSCORE was pinned — API10 writes "________.(2024)." —
    and the ASCII HYPHEN was not, though "---." is the commonest form of
    the three in these lists.

    An unrecognised continuation does not fail: the entry files under a
    row of dashes, and the work it stands for reads as never cited. The
    module's own comment says exactly that about underscores; this is
    the same sentence for the other three characters.
    """
    from docxkit._cite_grammar import references

    entries = references(["References",
                          "Aksoy, C. (2026). A first paper. JEP.",
                          f"{dashes}. 2019. A later work."])

    assert [(r.surname, r.year) for r in entries] == [
        ("Aksoy", "2026"), ("Aksoy", "2019")]


@pytest.mark.parametrize("heading", ["References", "Bibliography",
                                     "Литература", "Список литературы"])
def test_the_reference_list_is_found_under_any_heading_the_grammar_knows(
        heading):
    """`_DEFAULT_HEADINGS` has four members and the suite pinned three:
    a list headed "Bibliography" was held by nothing. Unfound, the list
    is not parsed at all — every citation in the paper then reports as
    unmatched, which reads as a bibliography problem rather than a
    grammar one."""
    from docxkit._cite_grammar import references

    entries = references(["Body prose.", heading,
                          "Aksoy, C. (2026). A first paper. JEP."])

    assert [(r.surname, r.year) for r in entries] == [("Aksoy", "2026")]


@pytest.mark.parametrize("caption", ["Figure 1. A chart.", "Table 1. A table.",
                                     "Рисунок 1. A chart.",
                                     "Таблица 1. A table."])
def test_a_caption_ENDS_the_list_in_either_alphabet(caption):
    """In these papers the exhibits sit below the references, so a
    caption ends the list as a heading would. Three of the four labels
    were unpinned; unrecognised, the caption and everything after it is
    parsed as entries — the back-matter defect this file exists for,
    arriving through the other door."""
    from docxkit._cite_grammar import references

    entries = references(["References",
                          "Aksoy, C. (2026). A first paper. JEP.",
                          caption,
                          "Smith, J. (2020). Not an entry at all. QJE."])

    assert [r.surname for r in entries] == ["Aksoy"]
