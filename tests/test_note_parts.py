"""Every reader that takes `parts` reads BOTH note parts — or is listed.

Word keeps two note stores, `word/footnotes.xml` and `word/endnotes.xml`,
and which one a manuscript uses is a journal's house style rather than
anything about the paper. A reader written for one of them is not wrong
about a document it read: it is silent about the half it never opened,
which is the failure this repository keeps writing down — a report that
reads as success.

Four readers were blind on 2026-08-19, found by moving one note from the
footnotes part to the endnotes part and running each of them:

    refstyle.audit          "2 works cited" became "1 works cited"
    export.to_markdown      the marker and the note both disappeared
    _cite_audit.audit_links bookmarks 1 -> 0, links 1 -> 0
    ingest.build_overrides  a note the author retyped: no override

The first two are fixed. `citations` is open in BACKLOG (S2), and `BLIND`
below is what keeps it honest: a reader may not JOIN that list without a
test failing, and a reader that is fixed fails it too, so the list can
only ever shrink and shrinking it is deliberate.

`ingest` is open too but not measured here: its blindness is NOTE versus
BODY rather than one note part versus the other — an edit inside either
kind of note produces no override — so the pair of fixtures this file is
built on cannot see it. It is pinned in `test_ingest.py` instead, by
`test_an_edit_inside_a_NOTE_is_not_ingested`.
"""
from __future__ import annotations

import pytest
from conftest import NS, note, notes, para, run

from docxkit import export, refstyle, wordcount
from docxkit._cite_audit import audit_links

#: Readers that do not read `word/endnotes.xml` yet, with the BACKLOG
#: entry that says why not. This one needs its WRITER moved at the same
#: time: an audit widened alone would report unlinked entries in
#: endnotes that `link_all` cannot reach.
BLIND = {
    "citations": "S2 the citation apparatus does not read ENDNOTES",
}

BODY = para(run("A Small Paper")) + para(run(
    "The trend is clear (Maestas et al. 2023)."))
NOTE_TEXT = ("See Smith, J (2020) The Paper, and Jones et al. 2021 for "
             "the wider argument.")


def _paper(kind: str, text: str = NOTE_TEXT) -> dict[str, bytes]:
    """The same manuscript with its one note filed as `kind`."""
    inner = note(text, 2, kind[:-1])
    return {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": (f"<w:document {NS}><w:body>{BODY}"
                              "</w:body></w:document>").encode(),
        f"word/{kind}.xml": notes(kind, inner).encode(),
    }


def _linked_paper(kind: str) -> dict[str, bytes]:
    """One with a bookmark and a link inside the note, for the audit."""
    inner = (para('<w:bookmarkStart w:id="1" w:name="Smith2020"/>'
                  + run("Smith, J. (2020). A paper. Journal, 1(1), 1-10.")
                  + '<w:bookmarkEnd w:id="1"/>')
             + para('<w:hyperlink w:anchor="Smith2020">'
                    + run("Smith (2020)") + "</w:hyperlink>"))
    parts = _paper(kind)
    parts[f"word/{kind}.xml"] = notes(
        kind, f'<w:{kind[:-1]} w:id="2">{inner}</w:{kind[:-1]}>').encode()
    return parts


def _cited(kind: str) -> str:
    """How many works refstyle counts — "2 works cited but no list"."""
    (issue,) = [i for i in refstyle.audit(_paper(kind)).issues
                if i.code == "no-list"]
    return issue.message.split()[0]


#: reader -> what it SAYS about the paper, as one comparable value.
#: Each is the smallest number that moved when the note was refiled.
READERS = {
    "refstyle": _cited,
    "export": lambda kind: "wider argument" in export.to_markdown(
        _paper(kind)),
    "wordcount": lambda kind: wordcount.count(_paper(kind)).footnotes,
    "citations": lambda kind: (
        audit_links(_linked_paper(kind))[1]["bookmarks"],
        audit_links(_linked_paper(kind))[1]["links"]),
}


@pytest.mark.parametrize("reader", [r for r in READERS if r not in BLIND])
def test_the_reader_says_the_same_thing_about_EITHER_note_part(reader):
    """The note is the same note; only the file it lives in changed."""
    say = READERS[reader]

    assert say("footnotes") == say("endnotes")


@pytest.mark.parametrize("reader", sorted(BLIND))
def test_a_reader_that_is_FIXED_is_removed_from_the_list(reader):
    """The list only ever shrinks, and shrinking it is deliberate — the
    same discipline `test_complexity_debt` applies to the complexity
    debt. A reader that has learned to read endnotes fails here, and the
    failure says what else to update: this list, and the BACKLOG entry
    it names."""
    say = READERS[reader]

    assert say("footnotes") != say("endnotes"), (
        f"{reader} reads endnotes now — delete it from BLIND and close "
        f"BACKLOG's \"{BLIND[reader]}\"")


def test_every_blind_reader_is_one_this_file_actually_MEASURES():
    """A name in `BLIND` that nothing exercises is a claim with no
    evidence — and it would silently exempt a reader that was never
    checked at all."""
    assert set(BLIND) <= set(READERS)
