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
