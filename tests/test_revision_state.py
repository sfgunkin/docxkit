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

The same lesson one level up, 2026-09-18: `KINDS` below held eight
documents and `_REVISION_NAMES` holds fourteen, so the guards here ran
over a subset that happened to exclude the one kind the SIMULATOR
cannot apply. `w:cellMerge` is counted as pending and survives both
accept and reject, which made a manuscript carrying one a proposal for
ever. It now carries all fourteen, with that kind declared as the
exception it is — `revisions.WORD_ONLY`, reported by `state` and named
by the refusals, because the way out of it is Word.
"""
from __future__ import annotations

import pytest
from conftest import document, make_parts, notes, para, run, write

from docxkit import revision
from docxkit.revisions import (
    _CONTENT_MARKERS,
    _PROPERTY_MARKERS,
    _REVISION_NAMES,
    WORD_ONLY,
    _has_revisions,
    revision_elements,
)

D = 'w:id="7" w:author="Reviewer" w:date="2026-01-01T00:00:00Z"'

CELL = para(run("cell"))

#: One document per way Word records an unresolved change, KEYED BY THE
#: ELEMENT NAME — so `test_every_revision_name_has_a_document_here` can
#: compare this set with `_REVISION_NAMES` and fail the day one grows
#: without the other.
#:
#: It held eight of the fourteen until 2026-09-18, and the six table
#: kinds were therefore never asked the property the three guards below
#: exist to enforce. Five of them hold it. `cellMerge` does not, and
#: nothing had said so: BACKLOG S1, found by an audit of the lists this
#: package parametrizes over, because a list of kinds cannot notice the
#: kind it does not name.
#:
#: Built here rather than from the conftest helpers so every kind
#: carries the SAME author, which is what the attribution test is about
#: — bar `tblGridChange`, whose element has no author to carry (see
#: :data:`NAMELESS`).
KINDS = {
    "ins": f'<w:p><w:ins {D}>{run("added")}</w:ins></w:p>',
    "del": (f'<w:p><w:del {D}>'
            f"<w:r><w:delText>gone</w:delText></w:r></w:del></w:p>"),
    "moveTo": f'<w:p><w:moveTo {D}>{run("moved")}</w:moveTo></w:p>',
    "moveFrom": (f'<w:p><w:moveFrom {D}>'
                 f"<w:r><w:delText>moved</w:delText></w:r></w:moveFrom>"
                 f"</w:p>"),
    "rPrChange": (f"<w:p><w:r><w:rPr><w:i/>"                  # a run's own
                  f"<w:rPrChange {D}><w:rPr/></w:rPrChange></w:rPr>"
                  f"<w:t>styled</w:t></w:r></w:p>"),
    "pPrChange": (f'<w:p><w:pPr><w:jc w:val="center"/>'       # a paragraph's
                  f"<w:pPrChange {D}><w:pPr/></w:pPrChange>"
                  f"</w:pPr>{run('aligned')}</w:p>"),
    "sectPrChange": (f"<w:p>{run('body')}</w:p><w:sectPr>"    # a section's
                     f"<w:sectPrChange {D}><w:sectPr/>"
                     f"</w:sectPrChange></w:sectPr>"),
    "tcPrChange": (f"<w:tbl><w:tr><w:tc><w:tcPr>"             # a cell's
                   f"<w:tcPrChange {D}><w:tcPr/></w:tcPrChange>"
                   f"</w:tcPr>{CELL}</w:tc></w:tr></w:tbl>"),
    "trPrChange": (f"<w:tbl><w:tr><w:trPr>"                   # a row's
                   f"<w:trPrChange {D}><w:trPr/></w:trPrChange>"
                   f"</w:trPr><w:tc>{CELL}</w:tc></w:tr></w:tbl>"),
    "tblPrChange": (f"<w:tbl><w:tblPr>"                       # the table's
                    f"<w:tblPrChange {D}><w:tblPr/></w:tblPrChange>"
                    f"</w:tblPr><w:tr><w:tc>{CELL}</w:tc></w:tr></w:tbl>"),
    "tblGridChange": (f'<w:tbl><w:tblGrid><w:gridCol w:w="4675"/>'
                      f'<w:tblGridChange w:id="7"><w:tblGrid/>'
                      f"</w:tblGridChange></w:tblGrid><w:tr><w:tc>{CELL}"
                      f"</w:tc></w:tr></w:tbl>"),
    "cellIns": (f"<w:tbl><w:tr><w:tc><w:tcPr><w:cellIns {D}/></w:tcPr>"
                f"{CELL}</w:tc></w:tr></w:tbl>"),
    "cellDel": (f"<w:tbl><w:tr><w:tc><w:tcPr><w:cellDel {D}/></w:tcPr>"
                f"{CELL}</w:tc></w:tr></w:tbl>"),
    "cellMerge": (f"<w:tbl><w:tr><w:tc><w:tcPr>"
                  f'<w:cellMerge {D} w:vMerge="cont"/></w:tcPr>'
                  f"{CELL}</w:tc></w:tr></w:tbl>"),
}

#: The kinds whose element carries no author. `CT_TblGridChange` is a
#: `CT_Markup`: it has `w:id` and nothing else, so a document whose only
#: revision is a grid change is pending and attributed to nobody. That
#: is the format's doing, and reporting it as "by: (unknown)" would be
#: this test file inventing a name Word never wrote.
NAMELESS = ("tblGridChange",)


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


@pytest.mark.parametrize("kind", sorted(set(KINDS) - set(NAMELESS)))
def test_the_reviewer_is_named_for_every_kind(kind, tmp_path):
    """`status` prints who a pending change belongs to. Reading the author
    off `<w:ins>` alone left the new kinds attributed to nobody."""
    path = write(tmp_path / "working.docx", make_parts(KINDS[kind]))
    assert set(revision.state(path).by_author) == {"Reviewer"}


@pytest.mark.parametrize("kind", NAMELESS)
def test_a_grid_change_is_pending_and_belongs_to_NOBODY(kind, tmp_path):
    """The exception to the test above, pinned rather than left to be
    rediscovered: `w:tblGridChange` carries an id and nothing else, so
    there is a pending revision here and no author to print beside it."""
    path = write(tmp_path / "working.docx", make_parts(KINDS[kind]))

    st = revision.state(path)

    assert st.pending == 1 and not st.is_truth
    assert st.by_author == {}


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
    body = KINDS["ins"] + KINDS["del"] + KINDS["rPrChange"]
    path = write(tmp_path / "working.docx", make_parts(body))
    assert revision.state(path).pending == 3


# ------------------------------------------------------ the drift guard --


def test_every_revision_name_has_a_document_here():
    """The audit's own finding, as a guard. `KINDS` held eight of the
    fourteen names, so the three properties below were enforced on a
    SUBSET — and the one kind that breaks them was in the half nobody
    asked. A name added to `_REVISION_NAMES` without a document here
    fails this instead of being tested by nothing."""
    assert set(KINDS) == set(_REVISION_NAMES)


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


def test_a_content_revision_is_seen_whatever_follows_its_NAME():
    """Read as `<w:ins `/`<w:ins/`, an insertion whose name was followed
    by a tab or a newline was not a revision, and a table holding one was
    fitted and ruled as though clean. `<w:insideH`, a table BORDER, is
    still not one."""
    assert _has_revisions(f'<w:p><w:ins\n{D}>{run("added")}</w:ins></w:p>')
    assert _has_revisions(f'<w:p><w:del\t{D}><w:r><w:delText>x</w:delText>'
                          "</w:r></w:del></w:p>")
    assert not _has_revisions('<w:tblBorders><w:insideH w:val="single"/>'
                              "</w:tblBorders>")


def test_a_move_s_RANGE_markers_are_a_revision_in_their_own_right():
    """They were read by the bare names `w:moveFrom`/`w:moveTo`, which
    they happen to begin. `accept` and `reject` remove them, so a
    document holding only markers is one with something to apply — and
    that has to survive spelling the names with an end."""
    ranges = (f'<w:p><w:moveFromRangeStart {D} w:name="move1"/>{run("x")}'
              '<w:moveToRangeEnd w:id="7"/></w:p>')

    from docxkit.revisions import accept

    assert _has_revisions(ranges)
    assert "moveFromRange" not in accept(document(ranges))


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_anything_has_revisions_calls_dirty_is_something_state_counts(kind):
    """The property the guard above protects, checked on real markup."""
    xml = KINDS[kind]
    assert _has_revisions(xml)
    assert revision_elements(xml), f"{kind}: dirty, but nothing counted"


@pytest.mark.parametrize("kind", sorted(set(KINDS) - set(WORD_ONLY)))
@pytest.mark.parametrize("view", ["accept", "reject"])
def test_anything_state_counts_is_something_the_simulator_applies(kind, view):
    """The third face of the same guard, and the one that was missing.

    `state` learned all seven kinds; the SIMULATOR knew three, so a
    formatting revision survived both views untouched. Two gates are
    built on those views: `reject-all == baseline` could not fail on a
    formatting-only batch, and an XML-accepted file still counted as a
    proposal because the marker was still in it.

    :data:`revisions.WORD_ONLY` is the declared exception, and the test
    below is what holds it to being one.
    """
    from docxkit import revisions as R

    applied = getattr(R, view)(KINDS[kind])
    assert not revision_elements(applied), (
        f"{kind}: {view} left the revision standing")


@pytest.mark.parametrize("kind", WORD_ONLY)
@pytest.mark.parametrize("view", ["accept", "reject"])
def test_a_WORD_ONLY_kind_survives_both_views_and_is_reported_as_such(
        kind, view, tmp_path):
    """The documented exception, pinned from both ends.

    `w:cellMerge` records a merge or a split rather than an appearance
    or a disappearance: applying one means recomputing `gridSpan` and
    `vMerge` across the row, no manuscript in the corpus carries one to
    measure against, and `revisions._CELL_FLAG` leaves it out on
    purpose. So this is not a hole to be plugged by teaching the
    simulator a fourteenth kind — it is a kind the toolkit counts and
    cannot clear, and the file has to SAY so, because otherwise the
    manuscript is a proposal for ever and every refusal quotes a number
    the author cannot act on (BACKLOG S1, 2026-09-18).
    """
    from docxkit import revisions as R

    assert revision_elements(getattr(R, view)(KINDS[kind])), (
        f"{kind}: the simulator applied it — if that is now true, take "
        f"it out of WORD_ONLY and the exception with it")

    path = write(tmp_path / "working.docx", make_parts(KINDS[kind]))
    st = revision.state(path)

    assert st.pending == 1, "counted, because it IS an open verdict"
    assert st.word_only == {kind: 1}, "and named as not ours to clear"


def test_an_ordinary_proposal_has_nothing_only_word_can_clear(tmp_path):
    """The field is empty for every kind the simulator applies, so a
    reader who sees it knows they are looking at the exception."""
    path = write(tmp_path / "working.docx",
                 make_parts(KINDS["ins"] + KINDS["tcPrChange"]))

    st = revision.state(path)

    assert st.pending == 2 and st.word_only == {}


def test_a_word_only_kind_is_counted_among_the_pending_not_beside_them(
        tmp_path):
    """It is still an open verdict: Word's Compare rebuilds a redline
    from ACCEPTED content, so a baseline taken with a merge pending
    flattens it exactly as it would flatten an insertion. The separate
    field says who can clear it, not whether it counts."""
    path = write(tmp_path / "working.docx",
                 make_parts(KINDS["ins"] + KINDS["cellMerge"]))

    st = revision.state(path)

    assert st.pending == 2
    assert st.word_only == {"cellMerge": 1}
    assert not st.is_truth and st.label == "proposal"


# ------------------------------------------ a baseline taken mid-save ----


def _scaffold(tmp_path, body: str):
    """A migrated project whose working.docx holds `body`."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "src.docx", make_parts(body))
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

    paper = _scaffold(tmp_path, KINDS["ins"])
    monkeypatch.setattr("docxkit.package.is_locked", lambda p: True)
    with pytest.raises(DocumentLocked):
        revision.baseline(paper, force=True)


def test_the_pending_refusal_NAMES_a_kind_only_word_can_clear(tmp_path):
    """It quoted a count and said "the author accepts or rejects them;
    this tool never does" — true, and useless for a cell merge, because
    accepting or rejecting one HERE leaves it standing. The author is
    left looking for a flag that does not exist, and there is none to
    find: the way out is Word. So the refusal names the kind and says
    so (BACKLOG S1, 2026-09-18)."""
    from docxkit.errors import BaselinePending

    paper = _scaffold(tmp_path, KINDS["cellMerge"])

    with pytest.raises(BaselinePending) as refused:
        revision.baseline(paper)

    said = str(refused.value)
    assert "1 revision(s) pending" in said, said
    assert "w:cellMerge" in said, said
    assert "Word" in said, said
    assert not paper.prev.exists()


def test_the_pending_refusal_says_nothing_about_word_when_it_need_not(
        tmp_path):
    """The common refusal stays the one it was. A sentence about a kind
    the file does not carry is a sentence that sends the reader to Word
    for an insertion they can resolve where they are."""
    from docxkit.errors import BaselinePending

    paper = _scaffold(tmp_path, KINDS["ins"])

    with pytest.raises(BaselinePending) as refused:
        revision.baseline(paper)

    assert "w:cellMerge" not in str(refused.value)
    assert "only Word" not in str(refused.value)


def test_an_unlocked_settled_file_still_baselines(tmp_path):
    paper = _scaffold(tmp_path, para(run("settled prose")))
    written = revision.baseline(paper).prev
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
                 make_parts(KINDS["ins"]))
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


# --- notes stored out of REFERENCE order (backlog S1, 2026-08-20) ------
#
# AFI r4 batch 17 appended a `<w:footnote>` to the end of footnotes.xml
# and put its reference in the middle of the body. Word renders that
# perfectly — notes are numbered by where their REFERENCES sit — so the
# render was right, the paper's own verifier passed 560/560, and every
# read-only gate here said truth.
#
# The NEXT batch's build then failed like a catastrophe: 81 glyph runs
# and `STRUCTURE footnoteReference: 7 -> 6`, because Word's Compare
# rewrites the definitions into document order and the part stopped
# lining up with the baseline's. The innocent batch got the blame.


def _noted(order: tuple[int, ...],
           refs: tuple[int, ...]) -> dict[str, bytes]:
    notes = ("<w:footnotes>" + "".join(
        f'<w:footnote w:id="{i}"><w:p><w:r><w:t>note {i}</w:t></w:r>'
        f"</w:p></w:footnote>" for i in order) + "</w:footnotes>")
    body = "".join(
        para(run(f"Sentence {i}."),
             f'<w:r><w:footnoteReference w:id="{i}"/></w:r>') for i in refs)
    return make_parts(body, extra={"word/footnotes.xml": notes})


def test_a_footnote_DEFINITION_out_of_order_is_reported(tmp_path):
    """The one gate that can see it before Word does."""
    path = write(tmp_path / "working.docx", _noted((2, 3), (3, 2)))

    st = revision.state(path)

    assert st.notes_unordered == {"footnote": ["2", "3"]}
    assert st.pending == 0, "and it is not a pending revision"


def test_definitions_in_reference_order_report_NOTHING(tmp_path):
    """The ordinary file, which is every file Word wrote itself."""
    path = write(tmp_path / "working.docx", _noted((2, 3), (2, 3)))

    assert revision.state(path).notes_unordered == {}


def _end_noted(order: tuple[int, ...],
               refs: tuple[int, ...]) -> dict[str, bytes]:
    """The same document with ENDNOTES and no footnotes part at all.

    The shape matters: the order check walks footnotes first, and a
    document that has none is exactly the one that proves the walk goes
    on to the endnotes rather than stopping at the first part it cannot
    read.
    """
    notes_xml = ("<w:endnotes>" + "".join(
        f'<w:endnote w:id="{i}"><w:p><w:r><w:t>note {i}</w:t></w:r>'
        f"</w:p></w:endnote>" for i in order) + "</w:endnotes>")
    body = "".join(
        para(run(f"Sentence {i}."),
             f'<w:r><w:endnoteReference w:id="{i}"/></w:r>') for i in refs)
    return make_parts(body, extra={"word/endnotes.xml": notes_xml})


def test_an_ENDNOTE_out_of_order_is_reported_by_a_file_with_no_footnotes(
        tmp_path):
    """`continue`, not `break`, when a part is missing.

    Both kinds are walked in one loop, footnotes first, and a document
    with endnotes and no footnotes part is the only shape that can tell
    the two apart: with `break` the walk stops at the missing footnotes
    and the endnote order goes unasked — the whole warning silently off
    for a paper that uses endnotes, which is what Word's Compare then
    rewrites into document order. Every fixture here had footnotes, so
    the skipped kind had to come FIRST. Found by mutation, 2026-09-18.
    """
    path = write(tmp_path / "working.docx", _end_noted((2, 3), (3, 2)))

    st = revision.state(path)

    assert st.notes_unordered == {"endnote": ["2", "3"]}
    assert st.pending == 0, "and it is not a pending revision"


def test_a_STATE_nobody_told_about_a_snapshot_is_not_from_one(tmp_path):
    """The default of `from_snapshot`, which decides whether every
    reader of a State says "read from a copy while Word held the file".

    `_state` always passes the flag, so the default is only ever taken
    by a State built directly — which the CLI's own renderer tests do,
    and which is how a paper's script would hold one. Defaulting to True
    would have `status` print the mid-edit caveat over counts read from
    the file itself: a report that says it might be out of date when it
    is not, which is the direction nobody checks. Found by mutation,
    2026-09-18 — the `_state` harness never built one by hand.
    """
    st = revision.State(path=tmp_path / "working.docx", by_part={},
                        by_author={})

    assert st.from_snapshot is False
    assert st.notes_unordered == {}, "and nothing is out of order either"


def test_a_definition_nothing_REFERENCES_is_not_an_order_problem(tmp_path):
    """It is a different defect — a note the body lost its marker for —
    and reporting it here would make the order line fire on documents
    whose order is right."""
    path = write(tmp_path / "working.docx", _noted((2, 3, 9), (2, 3)))

    assert revision.state(path).notes_unordered == {}
