"""What counts as a PENDING revision, for the number the protocol trusts.

`revision.state()` answers one question — truth or proposal — and every
other rule in the single-file protocol is decided on its answer. `build`
refuses a baseline with pending revisions because Word's Compare rebuilds
a redline from ACCEPTED content, so building on a pending one flattens
the author's open verdicts into plain text and decides them for them.

It counted `<w:ins ` and `<w:del ` and nothing else. Word has seven ways
to leave a verdict open, and five of them — both moves, and the
formatting and section changes — reported "0 pending -> TRUTH".

`revisions` already held the full list, and already said in a comment why
the short one is wrong ("a guard that looked for insertions alone called
the table clean"). `_table_layout` had learned it. The protocol's own
truth test had not, which is the one place the cost is the author's work.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, notes, para, run, write

from docxkit import revision
from docxkit.revisions import (
    _CONTENT_MARKERS,
    _PROPERTY_MARKERS,
    _REVISION_NAMES,
    _has_revisions,
    revision_elements,
)

D = 'w:id="7" w:author="Reviewer" w:date="2026-01-01T00:00:00Z"'

#: One document per way Word records an unresolved change. Built here
#: rather than from the conftest helpers so every kind carries the SAME
#: author, which is what the attribution test below is about.
KINDS = {
    "insertion": f'<w:p><w:ins {D}>{run("added")}</w:ins></w:p>',
    "deletion": (f'<w:p><w:del {D}>'
                 f"<w:r><w:delText>gone</w:delText></w:r></w:del></w:p>"),
    "move-to": f'<w:p><w:moveTo {D}>{run("moved")}</w:moveTo></w:p>',
    "move-from": (f'<w:p><w:moveFrom {D}>'
                  f"<w:r><w:delText>moved</w:delText></w:r></w:moveFrom>"
                  f"</w:p>"),
    "run formatting": (f"<w:p><w:r><w:rPr><w:i/>"
                       f"<w:rPrChange {D}><w:rPr/></w:rPrChange></w:rPr>"
                       f"<w:t>styled</w:t></w:r></w:p>"),
    "paragraph formatting": (f'<w:p><w:pPr><w:jc w:val="center"/>'
                             f"<w:pPrChange {D}><w:pPr/></w:pPrChange>"
                             f"</w:pPr>{run('aligned')}</w:p>"),
    "section formatting": (f"<w:p>{run('body')}</w:p><w:sectPr>"
                           f"<w:sectPrChange {D}><w:sectPr/>"
                           f"</w:sectPrChange></w:sectPr>"),
    "table cell formatting": (f"<w:tbl><w:tr><w:tc><w:tcPr>"
                              f"<w:tcPrChange {D}><w:tcPr/></w:tcPrChange>"
                              f"</w:tcPr>{para(run('cell'))}</w:tc></w:tr>"
                              f"</w:tbl>"),
}


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_kind_of_pending_revision_makes_it_a_proposal(kind, tmp_path):
    path = write(tmp_path / "working.docx", make_parts(KINDS[kind]))
    st = revision.state(path)
    assert st.pending >= 1, f"{kind} read as settled"
    assert not st.is_truth
    assert st.label == "proposal"


def test_a_document_with_nothing_tracked_is_truth(tmp_path):
    path = write(tmp_path / "working.docx",
                 make_parts(para(run("plain prose"))))
    st = revision.state(path)
    assert st.pending == 0 and st.is_truth and st.label == "truth"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_reviewer_is_named_for_every_kind(kind, tmp_path):
    """`status` prints who a pending change belongs to. Reading the author
    off `<w:ins>` alone left the new kinds attributed to nobody."""
    path = write(tmp_path / "working.docx", make_parts(KINDS[kind]))
    assert set(revision.state(path).by_author) == {"Reviewer"}


def test_a_formatting_change_in_a_footnote_is_reported_as_hidden(tmp_path):
    """Review > Next walks the body, and Simple Markup hides a footnote
    balloon — so "1 pending" without the part sends an author hunting
    through prose for something that is not there."""
    body = para(run("Body prose."))
    foot = notes("footnotes",
                 f'<w:footnote w:id="2"><w:p><w:pPr>'
                 f'<w:jc w:val="center"/><w:pPrChange {D}><w:pPr/>'
                 f"</w:pPrChange></w:pPr>{run('note')}</w:p></w:footnote>")
    path = write(tmp_path / "working.docx",
                 make_parts(body, footnotes=foot))
    st = revision.state(path)
    assert st.pending == 1
    assert st.hidden == 1


def test_a_move_is_counted_once_not_once_per_range_marker(tmp_path):
    """Word brackets a move with `w:moveFromRangeStart`/`End` as well as
    the element itself. `w:moveFrom` as a substring matches all three, so
    a count built on it would treble every move."""
    body = (f'<w:moveFromRangeStart {D} w:name="m1"/>'
            f'<w:p><w:moveFrom {D}>'
            f"<w:r><w:delText>moved</w:delText></w:r></w:moveFrom></w:p>"
            f'<w:moveFromRangeEnd w:id="7"/>')
    path = write(tmp_path / "working.docx", make_parts(body))
    assert revision.state(path).pending == 1


def test_several_revisions_are_counted_separately(tmp_path):
    body = KINDS["insertion"] + KINDS["deletion"] + KINDS["run formatting"]
    path = write(tmp_path / "working.docx", make_parts(body))
    assert revision.state(path).pending == 3


# ------------------------------------------------------ the drift guard --


def test_the_two_definitions_of_a_revision_cannot_drift():
    """`_has_revisions` answers "is anything tracked here?" and
    `REVISION_RE` answers "which elements, and whose?". They are the same
    question asked two ways, and they disagreed for as long as both
    existed. This fails the moment a marker is added to one and not the
    other.
    """
    named = set(_REVISION_NAMES)
    for marker in _CONTENT_MARKERS + _PROPERTY_MARKERS:
        tag = marker.lstrip("<").removeprefix("w:").rstrip(" /")
        assert tag in named, (
            f"{marker!r} makes `_has_revisions` say a document is dirty, "
            f"but `revision.state` will count 0 of them and call it truth")


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_anything_has_revisions_calls_dirty_is_something_state_counts(kind):
    """The property the guard above protects, checked on real markup."""
    xml = KINDS[kind]
    assert _has_revisions(xml)
    assert revision_elements(xml), f"{kind}: dirty, but nothing counted"


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("view", ["accept", "reject"])
def test_anything_state_counts_is_something_the_simulator_applies(kind, view):
    """The third face of the same guard, and the one that was missing.

    `state` learned all seven kinds; the SIMULATOR knew three, so a
    formatting revision survived both views untouched. Two gates are
    built on those views: `reject-all == baseline` could not fail on a
    formatting-only batch, and an XML-accepted file still counted as a
    proposal because the marker was still in it.
    """
    from docxkit import revisions as R

    applied = getattr(R, view)(KINDS[kind])
    assert not revision_elements(applied), (
        f"{kind}: {view} left the revision standing")


# ------------------------------------------ a baseline taken mid-save ----


def _scaffold(tmp_path, body: str):
    """A migrated project whose working.docx holds `body`."""
    src = write(tmp_path / "src.docx", make_parts(body))
    paper = revision.init(tmp_path / "proj", src, name="Test Paper",
                          author="Agent", attic=tmp_path / "attic")
    paper.prev.unlink(missing_ok=True)      # init seeds one; start clean
    return paper


def test_baseline_refuses_a_file_that_is_open_in_word(monkeypatch,
                                                      tmp_path):
    """`promote` checked this and `baseline` did not.

    A .docx is a zip. Copying one Word is part-way through rewriting
    captures an archive that is internally inconsistent — and this one is
    kept as `prev.docx`, which every later Compare and every reject-all
    is measured against.
    """
    from docxkit.errors import DocumentLocked

    paper = _scaffold(tmp_path, para(run("settled prose")))
    monkeypatch.setattr("docxkit.package.is_locked", lambda p: True)
    with pytest.raises(DocumentLocked, match="open in Word"):
        revision.baseline(paper)
    assert not paper.prev.exists()


def test_force_does_not_override_the_lock(tmp_path, monkeypatch):
    """`force` is for adopting a file that CARRIES revisions on purpose.
    A locked file is not a decision the author made."""
    from docxkit.errors import DocumentLocked

    paper = _scaffold(tmp_path, KINDS["insertion"])
    monkeypatch.setattr("docxkit.package.is_locked", lambda p: True)
    with pytest.raises(DocumentLocked):
        revision.baseline(paper, force=True)


def test_an_unlocked_settled_file_still_baselines(tmp_path):
    paper = _scaffold(tmp_path, para(run("settled prose")))
    written = revision.baseline(paper)
    assert written.exists()
    assert written.read_bytes() == paper.working.read_bytes()


# ------------------------------------------- a baseline left behind ----


def test_drift_is_empty_when_the_baseline_is_the_file(tmp_path):
    body = para(run("The paper as it stands."))
    working = write(tmp_path / "working.docx", make_parts(body))
    prev = write(tmp_path / "prev.docx", make_parts(body))
    assert revision.drift(working, prev) == []


def test_drift_sees_what_counting_pending_revisions_cannot(tmp_path):
    """The author accepted everything in Word and saved. Both files now
    count 0 pending -> TRUTH, and they are not the same paper."""
    working = write(tmp_path / "working.docx",
                    make_parts(para(run("The paper, as accepted."))))
    prev = write(tmp_path / "prev.docx",
                 make_parts(KINDS["insertion"]))
    assert revision.state(working).is_truth
    assert revision.drift(working, prev) == ["word/document.xml"]


def test_drift_names_the_part_not_just_the_fact(tmp_path):
    """An edit confined to a footnote is a different message to the
    author than an edit to the body."""
    body = para(run("Body prose."))
    working = write(tmp_path / "working.docx", make_parts(
        body, footnotes=notes("footnotes", '<w:footnote w:id="2">'
                              + para(run("revised note")) + "</w:footnote>")))
    prev = write(tmp_path / "prev.docx", make_parts(
        body, footnotes=notes("footnotes", '<w:footnote w:id="2">'
                              + para(run("the old note")) + "</w:footnote>")))
    assert revision.drift(working, prev) == ["word/footnotes.xml"]


def test_a_word_resave_is_not_drift(tmp_path):
    """The guard that keeps the warning worth reading: a Word round-trip
    re-mints rsids and the editing-time total in nearly every part, and a
    staleness check that fires on all of them is one nobody reads."""
    body = para(run("Identical prose."))
    working = write(tmp_path / "working.docx", make_parts(body, extra={
        "docProps/app.xml": "<Properties><TotalTime>91</TotalTime>"
                            "</Properties>",
        "word/settings.xml": '<w:settings w:rsid="00AF12C4"/>'}))
    prev = write(tmp_path / "prev.docx", make_parts(body, extra={
        "docProps/app.xml": "<Properties><TotalTime>17</TotalTime>"
                            "</Properties>",
        "word/settings.xml": '<w:settings w:rsid="00119933"/>'}))
    assert revision.drift(working, prev) == []


def test_a_part_the_author_added_is_drift(tmp_path):
    """Not every divergence is an edited part. A footnote added where
    there were none leaves every shared part identical."""
    body = para(run("Body prose."))
    working = write(tmp_path / "working.docx", make_parts(
        body, footnotes=notes("footnotes", '<w:footnote w:id="2">'
                              + para(run("a new note")) + "</w:footnote>")))
    prev = write(tmp_path / "prev.docx", make_parts(body))
    assert revision.drift(working, prev) == ["word/footnotes.xml"]
