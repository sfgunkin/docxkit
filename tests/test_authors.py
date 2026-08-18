"""Restamping who a document credits with its changes.

A deliverable goes out under one name. A pipeline writes several — the
DSI revision folder carried six ("Claude (эмпирика)", "Claude
(заключение)", "Claude (индексы)"...) across 370 revisions — and every
place that records one has to move together, or Word shows the new name
in the margin and the old one in the reviewing pane.
"""
from __future__ import annotations

import pytest
from conftest import comment, dele, ins, make_parts, para, run

from docxkit.authors import initials_for, read_authors, set_author

CORE = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        b'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/'
        b'dc/elements/1.1/"><dc:creator>sfgunkin@hotmail.com</dc:creator>'
        b"<cp:lastModifiedBy>Fel'dsher Gun'kin</cp:lastModifiedBy>"
        b"</cp:coreProperties>")


def parts(*, with_core: bool = True, with_people: bool = True):
    body = (para(run("Kept "), ins("added"), dele("removed"))
            + para(run("tail")))
    p = make_parts(body, comment_items=(comment(1, "please check"),))
    if with_core:
        p["docProps/core.xml"] = CORE
    if with_people:
        p["word/people.xml"] = (
            b'<w15:people xmlns:w15="http://schemas.microsoft.com/office/'
            b'word/2012/wordml"><w15:person w15:author="Tester">'
            b'<w15:presenceInfo w15:providerId="None" w15:userId="Tester"/>'
            b"</w15:person>"
            b'<w15:person w15:author="Revision"><w15:presenceInfo '
            b'w15:providerId="None" w15:userId="Revision"/></w15:person>'
            b"</w15:people>")
    return p


def text(p, name):
    return p[name].decode("utf-8")


def test_every_revision_and_comment_is_credited_to_the_new_author():
    p = parts()
    report = set_author(p, "Michael Lokshin")
    assert report.revisions >= 3          # w:ins, w:del, w:comment
    assert read_authors(p) == {"Michael Lokshin": report.revisions}
    assert 'w:author="Michael Lokshin"' in text(p, "word/document.xml")
    assert 'w:author="Michael Lokshin"' in text(p, "word/comments.xml")


def test_comment_initials_move_with_the_name():
    """Word prints the initials in the margin balloon, so a renamed
    comment with stale initials shows the new name over the old
    person's monogram."""
    p = parts()
    set_author(p, "Michael Lokshin")
    assert 'w:initials="ML"' in text(p, "word/comments.xml")
    assert 'w:initials="T"' not in text(p, "word/comments.xml")


@pytest.mark.parametrize("name,expected", [
    ("Michael Lokshin", "ML"),
    ("Michael  Lokshin", "ML"),
    ("M. Lokshin", "ML"),
    ("Lokshin", "L"),
    ("Jean-Luc Picard", "JP"),
])
def test_initials_are_derived_from_the_name(name, expected):
    assert initials_for(name) == expected


def test_people_xml_is_rewritten_and_collapsed():
    """Renaming several reviewers to one leaves several identical
    w15:person entries; the reviewing pane then lists the same name
    once per entry, reading as several people who share a name."""
    p = parts()
    report = set_author(p, "Michael Lokshin")
    people = text(p, "word/people.xml")
    assert people.count("<w15:person") == 1 == report.people
    assert 'w15:author="Michael Lokshin"' in people
    assert "Revision" not in people


def test_the_document_properties_are_rewritten():
    """dc:creator and cp:lastModifiedBy are what File > Info shows, and
    what follows the file into a journal's submission system."""
    p = parts()
    report = set_author(p, "Michael Lokshin")
    core = text(p, "docProps/core.xml")
    assert "<dc:creator>Michael Lokshin</dc:creator>" in core
    assert "<cp:lastModifiedBy>Michael Lokshin</cp:lastModifiedBy>" in core
    assert report.properties == 2


def test_only_restricts_the_rewrite_to_named_authors():
    """A document carrying a real co-author's edits alongside a
    pipeline's: absorbing everyone would credit their work to someone
    else, which is worse than leaving the pipeline's name in place."""
    p = make_parts(para(run("x "), ins("mine", rid=1))
                   + para(run("y "), dele("theirs", rid=2)))
    doc = text(p, "word/document.xml").replace(
        'w:author="Revision" w:date="2026-07-29T00:00:00Z">'
        "<w:r><w:delText>theirs", 'w:author="A Co-Author" '
        'w:date="2026-07-29T00:00:00Z"><w:r><w:delText>theirs')
    p["word/document.xml"] = doc.encode()
    set_author(p, "Michael Lokshin", only={"Revision"})
    after = read_authors(p)
    assert after == {"Michael Lokshin": 1, "A Co-Author": 1}


def test_an_empty_name_is_refused():
    """Word would attribute every change to nobody, and the reviewing
    pane shows a blank entry that cannot be filtered."""
    with pytest.raises(ValueError, match="empty author"):
        set_author(parts(), "   ")


def test_a_name_with_xml_syntax_is_escaped():
    p = parts()
    set_author(p, 'Smith & "Co" <ML>')
    doc = text(p, "word/document.xml")
    assert 'w:author="Smith &amp; &quot;Co&quot; &lt;ML&gt;"' in doc
    assert read_authors(p) == {'Smith & "Co" <ML>': 3}


def test_only_names_a_co_author_the_way_a_person_writes_it():
    """`only` takes the name, not the markup. "Smith & Co" is stored as
    "Smith &amp; Co", and a caller protecting their edits spells it the
    way it appears in the reviewing pane."""
    p = make_parts(para(run("x "), ins("mine", rid=1)))
    doc = text(p, "word/document.xml").replace(
        'w:author="Revision"', 'w:author="Smith &amp; Co"')
    p["word/document.xml"] = doc.encode()
    assert read_authors(p) == {"Smith & Co": 1}
    set_author(p, "Michael Lokshin", only={"Smith & Co"})
    assert read_authors(p) == {"Michael Lokshin": 1}


def test_dates_are_left_alone():
    """When an edit happened does not change because who made it was
    restamped, and a rewritten date makes a redline's history a
    fiction."""
    p = parts()
    before = text(p, "word/document.xml").count('w:date="2026-07-29')
    set_author(p, "Michael Lokshin")
    assert text(p, "word/document.xml").count('w:date="2026-07-29') == before


def test_a_package_without_people_or_core_is_handled():
    p = parts(with_core=False, with_people=False)
    report = set_author(p, "Michael Lokshin")
    assert report.people == 0 and report.properties == 0
    assert report.revisions >= 3


def test_reading_authors_names_everyone_before_a_rewrite():
    """The last chance to notice that one of those names is a real
    co-author whose edits are about to be absorbed."""
    p = parts()
    assert read_authors(p) == {"Revision": 2, "Tester": 1}


# --------------------------------- a property that is missing, not wrong ---
#
# Word's Compare drops docProps entirely, and the copy Word writes back on
# the next save carries a cp:lastModifiedBy and NO dc:creator. Renaming
# then credited the machine account and left authorship empty, while the
# report said one property had been set. LI7 shipped in that state.

_HEAD = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
         b'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/'
         b'dc/elements/1.1/">')


def _core(inner: bytes) -> bytes:
    return _HEAD + inner + b"</cp:coreProperties>"


def test_a_missing_creator_is_created_not_skipped():
    p = parts()
    p["docProps/core.xml"] = _core(
        b"<cp:lastModifiedBy>Fel'dsher Gun'kin</cp:lastModifiedBy>")
    report = set_author(p, "Michael Lokshin")
    core = text(p, "docProps/core.xml")
    assert "<dc:creator>Michael Lokshin</dc:creator>" in core
    assert "<cp:lastModifiedBy>Michael Lokshin</cp:lastModifiedBy>" in core
    assert report.properties == 2


def test_a_created_creator_precedes_lastModifiedBy():
    """CT_CoreProperties is a SEQUENCE: creator comes before
    lastModifiedBy. Word tolerates other orders; a validator does not."""
    p = parts()
    p["docProps/core.xml"] = _core(
        b"<cp:lastModifiedBy>Someone</cp:lastModifiedBy>")
    set_author(p, "Michael Lokshin")
    core = text(p, "docProps/core.xml")
    assert core.index("<dc:creator>") < core.index("<cp:lastModifiedBy>")


def test_a_missing_lastModifiedBy_is_created_after_the_creator():
    p = parts()
    p["docProps/core.xml"] = _core(b"<dc:creator>Someone</dc:creator>")
    set_author(p, "Michael Lokshin")
    core = text(p, "docProps/core.xml")
    assert "<cp:lastModifiedBy>Michael Lokshin</cp:lastModifiedBy>" in core
    assert core.index("<dc:creator>") < core.index("<cp:lastModifiedBy>")


def test_both_missing_are_both_created():
    p = parts()
    p["docProps/core.xml"] = _core(b"<dc:title>A paper</dc:title>")
    report = set_author(p, "Michael Lokshin")
    core = text(p, "docProps/core.xml")
    assert "<dc:creator>Michael Lokshin</dc:creator>" in core
    assert "<cp:lastModifiedBy>Michael Lokshin</cp:lastModifiedBy>" in core
    assert core.index("<dc:creator>") < core.index("<cp:lastModifiedBy>")
    assert report.properties == 2


def test_the_result_still_parses():
    from lxml import etree
    p = parts()
    p["docProps/core.xml"] = _core(
        b"<cp:lastModifiedBy>Someone</cp:lastModifiedBy>")
    set_author(p, "Michael Lokshin")
    etree.fromstring(p["docProps/core.xml"])      # raises if malformed


# --- what the first mutation run found (2026-08-17, 8.3 % survival) -----

def test_the_revision_count_counts_REVISIONS_not_people_entries():
    """`m.group(1) == "w"`. The same attribute name lives in two
    namespaces: `w:author` on a change, `w15:author` on a people-registry
    entry. Counting both makes the report claim more revisions than the
    document has — and the count is what a caller checks to see the
    restamp reached anything."""
    p = parts()
    ins_del_comment = 3          # w:ins, w:del, and the comment

    report = set_author(p, "Michael Lokshin")

    assert report.revisions == ins_del_comment
    assert "w15:person" in text(p, "word/people.xml")     # still there


def test_people_entries_for_DIFFERENT_authors_are_both_kept():
    """The collapse folds duplicates of ONE name, keyed on the name
    itself. Keying on anything else — the namespace prefix, the whole
    element — either folds two real reviewers into one or folds
    nothing."""
    p = parts()

    report = set_author(p, "Michael Lokshin", only={"Tester"})

    people = text(p, "word/people.xml")
    assert report.people == 2
    assert 'w15:author="Michael Lokshin"' in people
    assert 'w15:author="Revision"' in people


# `m.group(1) == "w"` mutated to `is "w"` survives and is EQUIVALENT:
# CPython interns single-character strings, so the group really is that
# object. Recorded here rather than chased — it is a property of the
# interpreter, not a gap in these tests.
