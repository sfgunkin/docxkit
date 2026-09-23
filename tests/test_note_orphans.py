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


#: Word's third special note, written when a document sets a continuation
#: notice. It takes the next id — 1 — so only its TYPE says what it is,
#: and it holds one empty paragraph by design.
NOTICE = ('<w:{kind} w:id="1" w:type="continuationNotice">'
          "<w:p><w:r><w:continuationNotice/></w:r></w:p></w:{kind}>")


@pytest.mark.parametrize("kind", ["footnote", "endnote"])
def test_a_CONTINUATION_NOTICE_is_known_by_its_type_not_its_id(kind):
    """Misconceptions, 2026-09-23: id 1, typed `continuationNotice`, read
    as a real, empty, unreferenced note — so `prune_orphans` cut it."""
    parts = _paper(para(run("A claim.")), NOTICE.format(kind=kind),
                   kind=f"{kind}s")

    assert fn.orphans(parts) == []
    assert fn.prune_orphans(parts) == []
    assert b"continuationNotice" in parts[f"word/{kind}s.xml"]


@pytest.mark.parametrize("kind", ["footnote", "endnote"])
def test_BOTH_gates_pass_an_unchanged_document_with_a_continuation_notice(
        kind):
    """The refusal it caused: each gate simulated ONE side, the prune
    took the notice from that side only, and the two were misaligned by
    a paragraph — quoted as `'' vs ''`. A document compared with itself
    must pass both."""
    doc = _paper(para(run("A claim.")) + REF,
                 NOTICE.format(kind=kind),
                 _note(NOTE_MARK + run(" Its words."), kind=kind),
                 kind=f"{kind}s")

    assert untracked(doc, doc) == []
    assert unaccepted(doc, doc) == []


def test_a_new_footnote_does_not_take_the_notice_s_id():
    """`add` allocates past every id, special ones included — excluding
    the notice from `find_all` must not hand its id out again."""
    parts = _paper(para(run("A claim here.")), NOTICE.format(kind="footnote"))

    assert fn.add(parts, after="claim", text="New.") == "2"


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


#: Content Word still writes that has no `w:t` and none of the modern
#: carriers. Each was cut as litter on ordinary DISTINCT ids until
#: 2026-09-17 — `_NOTE_CONTENT_RE` named `w:drawing` and `m:oMath` and not
#: their legacy twins.
LEGACY = {
    "vml_picture": ('<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-'
                    'com:vml" id="_x0000_i1025"/></w:pict></w:r>'),
    # an Equation Editor 3.0 equation, which these papers carry
    "ole_equation": ('<w:r><w:object w:dxaOrig="1200" w:dyaOrig="400">'
                     '<o:OLEObject xmlns:o="urn:schemas-microsoft-com:office'
                     ':office" Type="Embed" ProgID="Equation.3"/>'
                     "</w:object></w:r>"),
    "symbol": '<w:r><w:sym w:font="Symbol" w:char="F062"/></w:r>',
    "ink": '<w:r><w:contentPart r:id="rId9"/></w:r>',
}


@pytest.mark.parametrize("inner", LEGACY.values(), ids=LEGACY.keys())
def test_an_orphan_holding_LEGACY_content_is_not_a_shell(inner):
    """The note that holds only an old picture, an OLE equation, a
    symbol glyph or ink has nothing `visible_text` reads, and it is not
    a shell: pruning it takes a picture or an equation off the page, and
    `orphans` — which exists to report the note that KEPT its content —
    said nothing about it."""
    parts = _paper(para(run("A claim.")), _note(NOTE_MARK + inner))

    (orphan,) = fn.orphans(parts)

    assert (orphan.text, orphan.carriers, orphan.empty) == ("", 1, False)
    assert fn.prune_orphans(parts) == []
    assert b'w:id="2"' in parts["word/footnotes.xml"]


#: The carriers `_NOTE_CONTENT_RE` has named since it was written, and
#: which nothing pinned until 2026-09-18. Cosmic-ray plans NO mutant on
#: a regex — the sweep of that day placed none on any of the four lines
#: the pattern spans — so no survival figure grades them, and the module
#: read 0.6% with these open. Deleting each alternative by hand
#: (`kill_check`, twelve cases) left the whole harness green for
#: `w:hyperlink`, `w:drawing`, `w:tbl` and `m:oMath`, while every legacy
#: twin added the day before was killed by the test above. Under the
#: deletion a note holding one of them and no words reads as a shell,
#: and `prune_orphans` cuts it: the link, the figure or the equation
#: goes off the page with it.
#:
#: Each fixture holds ONE carrier and nothing else a reader sees. With
#: two, dropping either alternative leaves the note occupied by the
#: other and the case says nothing about the one it aimed at.
MODERN = {
    # the label deleted and the deletion accepted: the run is emptied
    # and the link element stays, its `r:id` still naming a relationship
    # in footnotes.xml.rels
    "link_with_no_label": ('<w:hyperlink r:id="rId7"><w:r><w:t/></w:r>'
                           "</w:hyperlink>"),
    "picture": ('<w:r><w:drawing><wp:inline xmlns:wp="http://schemas.'
                'openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
                '<wp:docPr id="7" name="Figure 1"/></wp:inline></w:drawing>'
                "</w:r>"),
    # An equation with no glyph in it, which is the only shape that
    # reaches this question: `visible_text` reads `m:t` as well as
    # `w:t`, so an equation that HAS its glyphs gives the note TEXT and
    # is not a shell for that reason instead — leaving the carrier
    # untested exactly as it is today.
    "equation": "<m:oMath><m:r><m:t/></m:r></m:oMath>",
}


@pytest.mark.parametrize("inner", MODERN.values(), ids=MODERN.keys())
def test_an_orphan_holding_a_MODERN_carrier_is_not_a_shell(inner):
    """A link whose words are gone, a figure and an empty equation are
    each something to lose, and none of them is anything
    `visible_text` reads. The legacy twins were named beside these
    because these were already there; that they were never pinned is
    what the hand-mutation of the pattern found."""
    parts = _paper(para(run("A claim.")), _note(NOTE_MARK + inner))

    (orphan,) = fn.orphans(parts)

    assert (orphan.text, orphan.carriers, orphan.empty) == ("", 1, False)
    assert fn.prune_orphans(parts) == []
    assert b'w:id="2"' in parts["word/footnotes.xml"]


#: A table with nothing to read in it — the grid is still ruled lines on
#: the page. `w:tblPr` is deliberately in the fixture: `<w:tbl\b` does
#: not match it, so the carrier count stays 1 and the case isolates the
#: alternative it aims at.
TABLE = ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
         '<w:tr><w:tc><w:p w14:paraId="33333333"/></w:tc>'
         '<w:tc><w:p w14:paraId="44444444"/></w:tc></w:tr></w:tbl>')


def test_an_orphan_holding_only_a_TABLE_is_not_a_shell():
    """The fourth carrier, and the one that cannot sit where the others
    do: a `w:tbl` is a sibling of the paragraphs, not a child of one, so
    this note is built by hand rather than through `_note` — and it ends
    in the paragraph Word writes after a table."""
    inner = (f'<w:footnote w:id="2">{para(NOTE_MARK)}{TABLE}'
             f'{para(pid="55555555")}</w:footnote>')
    parts = _paper(para(run("A claim.")), inner)

    (orphan,) = fn.orphans(parts)

    assert (orphan.text, orphan.carriers, orphan.empty) == ("", 1, False)
    assert fn.prune_orphans(parts) == []
    assert b'w:id="2"' in parts["word/footnotes.xml"]


def test_an_orphan_whose_words_are_all_DELETED_is_not_a_shell():
    """Deleted words are content on every document `prune_orphans` can
    meet. The package's own callers simulate a view first, and neither
    view keeps a `w:delText` — accepting removes the deletion, rejecting
    turns it back into `w:t` — so the only file where the pruner sees
    one is a RAW tracked document, and there rejecting the revision
    brings the words back. Cutting the definition loses them."""
    parts = _paper(para(run("A claim.")),
                   _note(NOTE_MARK + dele(" Words a reject restores.")))

    (orphan,) = fn.orphans(parts)

    assert orphan.text == "" and not orphan.empty
    assert fn.prune_orphans(parts) == []


@pytest.mark.parametrize("deleted", [
    pytest.param('<w:del w:id="5" w:author="A" w:date="2026-09-17T00:00:00Z">'
                 '<w:r><w:delText xml:space="preserve">  </w:delText></w:r>'
                 "</w:del>", id="blank"),
    pytest.param('<w:del w:id="5" w:author="A" w:date="2026-09-17T00:00:00Z">'
                 "<w:r><w:delText/></w:r></w:del>", id="self_closing"),
])
def test_a_DELETION_of_nothing_visible_still_leaves_a_shell(deleted):
    """The other side of counting deleted words: a deletion of blanks is
    a shell the same way a run of blanks is (`text` is stripped), and
    `<w:delText/>` is an element with nothing in it — read as an opening
    tag, it would keep every such shell forever."""
    parts = _paper(para(run("A claim.")), _note(NOTE_MARK + deleted))

    (gone,) = fn.prune_orphans(parts)

    assert (gone.id, gone.empty) == ("2", True)


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
