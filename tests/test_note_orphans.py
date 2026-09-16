"""A note's reference and its definition are ONE object to Word.

They are two parts to us, and `revisions.accept` works a part at a time.
So a revision that deletes a footnote — the reference inside a `w:del`,
the definition's runs as `w:delText`, which is exactly how Word writes
one — accepts to a document with the marker gone and an empty definition
still in the part. Word's own accept removes both.

Measured on Aging_Well, 2026-08-31: `tracked.build` refused a redline
that was correct, and quoted its evidence as

    footnotes P6: intended ''
                accepted ''

two empty strings that look identical, under a sentence blaming Word for
rewriting content. The reader goes looking in the body for damage that is
not there. Four of them on the full round, one per note whose marker the
batch touched.

The fix is on `accept`'s CALLER, because `accept(xml)` takes one part and
cannot know what another part references. Shells only: an unreferenced
definition with WORDS in it is a footnote that lost its marker, which is
a real loss and gets reported rather than tidied away.
"""
from __future__ import annotations

import pytest
from conftest import NS, dele, make_parts, notes, para, run

from docxkit import footnotes as fn
from docxkit import tracked
from docxkit.errors import PackageError
from docxkit.tracked import unaccepted, untracked

#: Word's separator and continuation notes, in every document, referenced
#: by nothing. A pruner that counted these as orphans would strip the
#: part every manuscript needs.
RESERVED = ('<w:footnote w:id="-1" w:type="continuationSeparator">'
            "<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>"
            '<w:footnote w:id="0" w:type="separator">'
            "<w:p><w:r><w:separator/></w:r></w:p></w:footnote>")

REF = '<w:r><w:footnoteReference w:id="2"/></w:r>'
DEL_REF = ('<w:del w:id="70" w:author="Revision" '
           f'w:date="2026-07-29T00:00:00Z">{REF}</w:del>')
#: The definition's own leading mark. Present in every note, and the
#: reason "is this definition empty" cannot be answered by "has it any
#: runs" — it always has this one.
NOTE_MARK = '<w:r><w:footnoteRef/></w:r>'


def _note(inner: str, nid: int = 2, kind: str = "footnote") -> str:
    return f'<w:{kind} w:id="{nid}">{para(inner)}</w:{kind}>'


def _paper(body: str, *note_items: str, kind: str = "footnotes",
           extra: dict[str, str] | None = None) -> dict[str, bytes]:
    parts = make_parts(body, extra=extra)
    part = notes(kind, RESERVED if kind == "footnotes" else "", *note_items)
    parts[f"word/{kind}.xml"] = part.encode("utf-8")
    return parts


# --------------------------------------------------------------- the gate


def test_a_DELETED_footnote_is_not_a_paragraph_the_accept_failed():
    """The repro, and the whole entry. The clean copy has no note at
    all — Word removes the definition with the marker — and accepting
    the redline has to reach the same document."""
    intended = _paper(para(run("A claim.")))
    redline = _paper(para(run("A claim.")) + DEL_REF,
                     _note(NOTE_MARK + dele(" The note's words.")))

    assert unaccepted(redline, intended) == []


def test_an_ADDED_footnote_leaves_no_shell_on_the_REJECT_side_either():
    """Same object, other direction: a note the batch adds has its
    reference in a `w:ins` and its text inserted too, so rejecting
    empties the definition and removes the marker. The baseline never
    had the note, and `untracked` — the gate that decides whether the
    author's veto is real — must not read the shell as an edit nobody
    can refuse."""
    ins_ref = ('<w:ins w:id="71" w:author="Revision" '
               f'w:date="2026-07-29T00:00:00Z">{REF}</w:ins>')
    baseline = _paper(para(run("A claim.")))
    batch = _paper(para(run("A claim.")) + ins_ref,
                   _note(NOTE_MARK + '<w:ins w:id="72" w:author="Revision" '
                         'w:date="2026-07-29T00:00:00Z">'
                         "<w:r><w:t>A new note.</w:t></w:r></w:ins>"))

    assert untracked(batch, baseline) == []


def test_a_note_the_accept_KEEPS_still_has_to_reproduce_its_words():
    """The pruning may not buy its silence by going blind. A note whose
    marker survives is compared exactly as before."""
    intended = _paper(para(run("A claim.")) + REF,
                      _note(NOTE_MARK + run(" The intended words.")))
    redline = _paper(para(run("A claim.")) + REF,
                     _note(NOTE_MARK + run(" Something else entirely.")))

    (missed,) = unaccepted(redline, intended)

    assert missed.part == "footnotes"
    assert missed.accepted == " Something else entirely."


# ------------------------------------------------------------- the reader


def test_a_definition_nothing_references_is_an_orphan():
    parts = _paper(para(run("A claim.")),
                   _note(NOTE_MARK + run(" Unreferenced.")))

    (orphan,) = fn.orphans(parts)

    assert (orphan.kind, orphan.id) == ("footnote", "2")
    assert orphan.text == "Unreferenced."
    assert not orphan.empty


def test_word_s_own_separator_notes_are_not_orphans():
    """Ids 0 and -1 are referenced by nothing in any document ever
    written, and pruning them takes the part apart."""
    parts = _paper(para(run("A claim.")))

    assert fn.orphans(parts) == []
    assert fn.prune_orphans(parts) == []
    assert b'w:id="0"' in parts["word/footnotes.xml"]


def test_a_reference_in_a_HEADER_keeps_its_definition():
    """The reason this reads every part rather than the body. A running
    head can carry a note reference, and a definition pruned because
    `document.xml` had gone quiet about it takes a note the page shows."""
    header = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f"<w:hdr {NS}>{para(run('Head'), REF)}</w:hdr>")
    parts = _paper(para(run("A claim.")),
                   _note(NOTE_MARK + run(" In the header.")),
                   extra={"word/header1.xml": header})

    assert fn.orphans(parts) == []


def test_prune_drops_the_SHELL_and_keeps_the_one_with_words():
    parts = _paper(para(run("A claim.")),
                   _note(NOTE_MARK, nid=2), _note(NOTE_MARK + run(" Kept."),
                                                  nid=3))

    (gone,) = fn.prune_orphans(parts)

    assert (gone.id, gone.empty) == ("2", True)
    assert b'w:id="2"' not in parts["word/footnotes.xml"]
    assert b'w:id="3"' in parts["word/footnotes.xml"]
    assert [o.id for o in fn.orphans(parts)] == ["3"]


@pytest.mark.parametrize("order", ["worded first", "shell first"])
def test_prune_cuts_the_SHELL_when_it_shares_an_id_with_a_WORDED_note(order):
    """A part answering to ONE id twice is malformed, and the pruner
    still may not cut the half with the words in it.

    Measured 2026-09-16: the cut was looked up by id and took the FIRST
    definition answering to it, while the orphan being pruned was the
    second one. With the author's note stored first, the words went and
    the shell stayed — and `gone` named the SHELL, so the record said
    the harmless one had been removed:

        orphans before:   [('12', 'The lost note.', False), ('12', '', True)]
        reported gone:    [('12', '', True)]
        left in the part: [('12', '')]

    The order is parametrized because the order IS the defect: stored
    shell-first the same call was already right, by accident. Emptiness
    belongs to a DEFINITION, not to an id.
    """
    worded = _note(NOTE_MARK + run(" The lost note."), nid=12)
    shell = _note(NOTE_MARK, nid=12)
    items = (worded, shell) if order == "worded first" else (shell, worded)

    parts = _paper(para(run("A claim.")), *items)
    (gone,) = fn.prune_orphans(parts)

    left = fn.find_all(parts["word/footnotes.xml"].decode("utf-8"))
    assert [(f.id, f.text) for f in left] == [("12", "The lost note.")]
    assert (gone.id, gone.text, gone.empty) == ("12", "", True)


@pytest.mark.parametrize("spec,gone_ids,left", [
    pytest.param((("12", ""), ("12", "")), ["12", "12"], [],
                 id="two_shells_on_one_id"),
    pytest.param((("12", " The lost note."), ("13", "")), ["13"],
                 [("12", "The lost note.")], id="distinct_ids"),
    pytest.param((("12", ""),), ["12"], [], id="one_ordinary_shell"),
])
def test_prune_leaves_the_inputs_that_were_ALREADY_right_ALONE(
        spec, gone_ids, left):
    """The three inputs the defect never touched.

    Cutting by DEFINITION rather than by id could have moved any of
    them — two shells sharing an id are pruned one after the other, and
    the ordinary cases go through the same changed line — so all three
    are pinned here rather than argued.
    """
    parts = _paper(para(run("A claim.")),
                   *[_note(NOTE_MARK + (run(text) if text else ""),
                           nid=int(nid)) for nid, text in spec])

    gone = fn.prune_orphans(parts)

    part = parts["word/footnotes.xml"].decode("utf-8")
    assert [o.id for o in gone] == gone_ids
    assert [(f.id, f.text) for f in fn.find_all(part)] == left


def test_a_shell_holding_a_BOOKMARK_is_not_empty():
    """No visible text and still something to lose: a link elsewhere in
    the paper points at that anchor, and dropping the definition breaks
    it where no text comparison can see it."""
    parts = _paper(para(run("A claim.")),
                   _note(NOTE_MARK + '<w:bookmarkStart w:id="9" '
                         'w:name="Smith2020"/><w:bookmarkEnd w:id="9"/>'))

    (orphan,) = fn.orphans(parts)

    assert orphan.text == "" and orphan.carriers == 1 and not orphan.empty
    assert fn.prune_orphans(parts) == []


def test_an_ENDNOTE_orphan_is_the_same_object():
    """Which store a paper uses is a journal's house style. A gate that
    covered only the footnotes cannot fail for the other half of them."""
    parts = _paper(para(run("A claim.")),
                   _note("<w:r><w:endnoteRef/></w:r>", kind="endnote"),
                   kind="endnotes")

    (gone,) = fn.prune_orphans(parts)

    assert gone.kind == "endnote"
    assert b'w:id="2"' not in parts["word/endnotes.xml"]


def test_orphans_of_a_document_with_no_note_part_is_empty():
    assert fn.orphans(make_parts(para(run("A claim.")))) == []


# ------------------------------------------------------ what is REPORTED


def test_a_note_that_lost_its_marker_and_kept_its_words_is_refused():
    """The other half of the fix. Pruning the shells must not also
    swallow the real loss: a definition left unreferenced with words in
    it renders on no page, and the refusal says so instead of quoting
    two empty strings."""
    report = tracked.BuildReport()
    report.orphan_notes = [fn.Orphan("footnote", "6", "The lost note.", 0)]

    with pytest.raises(PackageError, match="nothing referencing them"):
        tracked._refuse_accept_side(report, "v12.docx")
