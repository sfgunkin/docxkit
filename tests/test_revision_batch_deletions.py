"""What the promoted batch deleted, and the author accepted, is not a LOSS.

HPPA_Index, 2026-10-09: a batch deleted footnote 8, the author accepted
it in Word, and `ingest --check` exited 5 while `baseline` refused until
it was handed `--accept-loss` for the batch's own proposal. The first
fix (344f49c) matched each loss to a deletion by `Loss.key` and was
reverted (4deb0f9) because a key is not an identity: real losses went
through. These tests pin the redesign's whole contract, and most of
them are the cases the review of that attempt reproduced: the excuse
holds only when the hand-back IS the proposal with everything of that
kind accepted, and every doubtful case still refuses.
"""
from __future__ import annotations

import pytest
from conftest import comment, make_parts, para, run, write
from test_cli import run_cli

from docxkit import guard, package, revision
from docxkit.errors import HandbackLoss
from docxkit.tracked import accepted_view

_STAMP = 'w:author="Revision" w:date="2026-10-09T00:00:00Z"'
_NS_W = ('xmlns:w="http://schemas.openxmlformats.org/'
         'wordprocessingml/2006/main"')

#: Seven notes, each saying something no other does.
NOTES = {k: f"Note {k} names source number {k} and nothing else."
         for k in range(1, 8)}


def _del(inner: str, rid: int) -> str:
    return f'<w:del w:id="{rid}" {_STAMP}>{inner}</w:del>'


def _ins(inner: str, rid: int) -> str:
    return f'<w:ins w:id="{rid}" {_STAMP}>{inner}</w:ins>'


def _ref(k: int) -> str:
    return f'<w:r><w:footnoteReference w:id="{k}"/></w:r>'


def _link(anchor: str, label: str, *, deleted: bool = False) -> str:
    tag = "delText" if deleted else "t"
    return (f'<w:hyperlink w:anchor="{anchor}"><w:r>'
            f"<w:{tag}>{label}</w:{tag}></w:r></w:hyperlink>")


def _footnotes(notes: dict[int, str], deleted: frozenset[int] = frozenset()
               ) -> str:
    body = ""
    for k, text in notes.items():
        inner = (_del(f"<w:r><w:delText>{text}</w:delText></w:r>", 500 + k)
                 if k in deleted else run(text))
        body += f'<w:footnote w:id="{k}"><w:p>{inner}</w:p></w:footnote>'
    return f"<w:footnotes {_NS_W}>{body}</w:footnotes>"


def _body(notes, deleted=frozenset(), *, links=(), cut_links=(),
          extra=""):
    """One paragraph per note, then the link paragraphs.

    `links` are kept; `cut_links` are `(anchor, label)` whose sentence
    the batch deletes, a `Xtxt` back-link bookmark round each one."""
    out = ""
    for k in notes:
        ref = _del(_ref(k), 400 + k) if k in deleted else _ref(k)
        sentence = (_del(f"<w:r><w:delText>Claim {k}.</w:delText></w:r>",
                         300 + k) if k in deleted else run(f"Claim {k}."))
        out += para(sentence, ref)
    for anchor, label in links:
        out += para(run("As "), _link(anchor, label), run(" showed."))
    for i, (anchor, label) in enumerate(cut_links):
        cut = (f'<w:bookmarkStart w:id="{80 + i}" w:name="{anchor}txt"/>'
               + _link(anchor, label, deleted=True)
               + f'<w:bookmarkEnd w:id="{80 + i}"/>')
        out += para(run("Kept. "), _del(cut, 200 + i))
    return out + extra


def _before(notes, *, links=(), cut_links=(), extra=""):
    """The truth the batch was built on: the same shapes, nothing cut."""
    out = "".join(para(run(f"Claim {k}."), _ref(k)) for k in notes)
    for anchor, label in links:
        out += para(run("As "), _link(anchor, label), run(" showed."))
    for i, (anchor, label) in enumerate(cut_links):
        out += para(run("Kept. "),
                    f'<w:bookmarkStart w:id="{80 + i}" w:name="{anchor}txt"/>'
                    + _link(anchor, label)
                    + f'<w:bookmarkEnd w:id="{80 + i}"/>')
    return out + extra


def _round(tmp_path, *, deleted=frozenset({2, 4, 6}), links=(),
           cut_links=(), promote=True, notes=None, extra="",
           comments=(), batch_comments=None, batch_extra=None):
    """A paper whose promoted batch deletes `deleted` notes and the
    sentences in `cut_links`, built on a truth that has all of them.
    `extra` ends both bodies (the batch's is `batch_extra`, if given);
    `comments` are the truth's comment texts and `batch_comments` the
    batch's (the same, unless given)."""
    notes = NOTES if notes is None else notes
    root = tmp_path / "HPPA"
    root.mkdir()
    src = write(root / "HPPA.docx",
                make_parts(_before(notes, links=links, cut_links=cut_links,
                                   extra=extra),
                           footnotes=_footnotes(notes),
                           comment_items=_comments(comments)))
    paper = revision.init(root, src, name="HPPA")
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(
        _body(notes, deleted, links=links, cut_links=cut_links,
              extra=extra if batch_extra is None else batch_extra),
        footnotes=_footnotes(notes, deleted),
        comment_items=_comments(comments if batch_comments is None
                                else batch_comments)))
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    if promote:
        revision.promote(paper)
    return paper


def _comments(texts):
    return tuple(comment(i, text, para_id=f"AAAA{i:04d}")
                 for i, text in enumerate(texts, 1))


def _accept_all(paper, source=None):
    """The author's hand-back: the proposal with everything accepted."""
    parts = accepted_view(package.read_parts(source or paper.batch))
    write(paper.working, parts)
    return parts


def _without_note(parts, k):
    """`parts` with note `k` gone, reference and definition — what Word
    does to a note when it collapses the paragraph carrying it."""
    doc = parts["word/document.xml"].decode()
    notes = parts["word/footnotes.xml"].decode()
    doc = doc.replace(f'<w:r><w:footnoteReference w:id="{k}"/></w:r>', "")
    start = notes.index(f'<w:footnote w:id="{k}">')
    end = notes.index("</w:footnote>", start) + len("</w:footnote>")
    return {**parts, "word/document.xml": doc.encode(),
            "word/footnotes.xml": (notes[:start] + notes[end:]).encode()}


# ------------------------------------------------------------ notes

def test_the_batch_s_own_note_deletions_do_not_block_the_baseline(tmp_path):
    """Three notes deleted of seven, all accepted: recorded, not
    refused, and no `--accept-loss` typed."""
    paper = _round(tmp_path)
    _accept_all(paper)

    report = revision.baseline(paper, log=False)

    assert sorted(loss.what for loss in report.deleted) == sorted(
        NOTES[k] for k in (2, 4, 6))
    assert {loss.kind for loss in report.deleted} == {"footnote"}
    assert package.read_parts(paper.prev) == package.read_parts(
        paper.working)


def test_a_note_WORD_ate_beside_them_still_refuses(tmp_path):
    """One note the batch did not touch is gone too. The kind is no
    longer the proposal accepted in full, so nothing of it is excused:
    the refusal names the note Word ate (and, honestly, the three the
    batch deleted, since nothing can tell them apart any more)."""
    paper = _round(tmp_path)
    write(paper.working, _without_note(_accept_all(paper), 5))

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert NOTES[5][:40] in str(caught.value)


def test_a_REJECTED_deletion_reworded_does_not_cover_a_note_Word_ate(
        tmp_path):
    """The review's case against the first attempt. The author rejected
    the deletion of note 2 and reworded it; Word ate note 5. Counted,
    one note is missing and note 2's old text is gone, so the old code
    paired that text with the batch's proposal and passed. WHICH note
    the refusal names is `_lost_notes`' best effort — here it is note
    2's old text — and the refusal is what matters."""
    paper = _round(tmp_path, deleted=frozenset({2}))
    parts = make_parts(_before(NOTES), footnotes=_footnotes(
        {**NOTES, 2: "Note 2, reworded by the author on reading it."}))
    write(paper.working, _without_note(parts, 5))

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "lost 1 thing(s)" in str(caught.value)


def test_a_REJECTED_cut_whose_note_Word_ate_is_still_LOST(tmp_path):
    """Review 2026-10-14, finding 1. The batch cut "Claim 2." with note
    2; the author REJECTED the cut, and Word, collapsing the paragraph,
    ate note 2 anyway. The hand-back's notes now equal the proposal's
    accepted view, and the kind-level test excused it as the batch's
    deletion. The cut's words are still on the page, so it was not
    accepted, and the note is a loss."""
    paper = _round(tmp_path, deleted=frozenset({2}))
    write(paper.working, _without_note(
        make_parts(_before(NOTES), footnotes=_footnotes(NOTES)), 2))

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert NOTES[2][:40] in str(caught.value)


def test_a_REJECTED_cut_s_note_is_LOST_through_ingest_check(
        monkeypatch, tmp_path, capsys):
    paper = _round(tmp_path, deleted=frozenset({2}))
    write(paper.working, _without_note(
        make_parts(_before(NOTES), footnotes=_footnotes(NOTES)), 2))

    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(paper.root))

    assert code == HandbackLoss.exit_code
    assert "DELETED BY THE BATCH" not in capsys.readouterr().out


def test_TWIN_notes_the_batch_cut_one_and_Word_ate_the_other(tmp_path):
    """Notes 2 and 3 say the same words. The batch cuts note 2, the
    author rejects the cut, and Word eats note 3. Counted by text, the
    hand-back is the proposal accepted; by position it is not."""
    twins = {**NOTES, 3: NOTES[2]}
    paper = _round(tmp_path, deleted=frozenset({2}), notes=twins)
    write(paper.working, _without_note(
        make_parts(_before(twins), footnotes=_footnotes(twins)), 3))

    with pytest.raises(HandbackLoss):
        revision.baseline(paper, log=False)


def test_ONE_of_two_cuts_rejected_excuses_neither(tmp_path):
    """Two notes cut, one cut accepted and one rejected with its note
    eaten: a note cannot be told from the other by the loss list, so
    the kind is excused whole or not at all."""
    paper = _round(tmp_path, deleted=frozenset({2, 4}))
    accepted = _accept_all(paper)
    doc = accepted["word/document.xml"].decode().replace(
        para(run("Claim 3."), _ref(3)),
        para(run("Claim 3."), _ref(3)) + para(run("Claim 4.")))
    write(paper.working, {**accepted, "word/document.xml": doc.encode()})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "lost 2 thing(s)" in str(caught.value)


def test_a_cut_of_the_note_MARK_alone_is_not_proven_accepted(tmp_path):
    """The batch deletes only the reference, no words. Accepted, or
    rejected and eaten by Word, the page reads the same, so nothing
    proves which: it stays a loss, and `--accept-loss` is the way on."""
    paper = _round(tmp_path, deleted=frozenset(), promote=False)
    batch = package.read_parts(paper.batch)
    doc = batch["word/document.xml"].decode().replace(
        para(run("Claim 2."), _ref(2)),
        para(run("Claim 2."), _del(_ref(2), 402)))
    notes = _footnotes(NOTES, frozenset({2}))
    write(paper.batch, {**batch, "word/document.xml": doc.encode(),
                        "word/footnotes.xml": notes.encode()})
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    revision.promote(paper)
    _accept_all(paper)

    report = revision.ingest(paper.working, paper.prev, paper=paper)

    assert report.deleted == []
    assert [x.kind for x in report.lost] == ["footnote"]


def test_the_excused_note_is_NAMED_by_its_own_words(tmp_path):
    """The batch rewords note 1 and cuts note 2, all accepted. By the
    texts the hand-back no longer has, note 1's OLD words are as gone as
    note 2's, and the best-effort name took the first in sorted order:
    the ledger said note 1 was deleted. The cut is known by its
    reference, so it is named by its own definition."""
    paper = _round(tmp_path, deleted=frozenset({2}), promote=False)
    batch = package.read_parts(paper.batch)
    notes = batch["word/footnotes.xml"].decode().replace(
        run(NOTES[1]),
        _del(f"<w:r><w:delText>{NOTES[1]}</w:delText></w:r>", 601)
        + _ins(run("Note 1, as the batch rewords it."), 602))
    write(paper.batch, {**batch, "word/footnotes.xml": notes.encode()})
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    revision.promote(paper)
    _accept_all(paper)

    report = revision.baseline(paper, log=False)

    assert [loss.what for loss in report.deleted] == [NOTES[2]]


def test_a_batch_that_was_never_PROMOTED_excuses_nothing(tmp_path):
    """No promote, no proposal: `_verdict._proposal` cannot name one,
    and every loss blocks as it did before."""
    paper = _round(tmp_path, promote=False)
    _accept_all(paper)

    with pytest.raises(HandbackLoss):
        revision.baseline(paper, log=False)


def test_a_hand_back_with_revisions_PENDING_excuses_nothing(tmp_path):
    """An unopened proposal is not an accepted one. The notes are gone
    from the accepted text and one insertion is still waiting, so the
    report keeps all three as losses."""
    paper = _round(tmp_path)
    parts = _accept_all(paper)
    doc = parts["word/document.xml"].decode().replace(
        "</w:body>", para(_ins(run("still pending"), 900)) + "</w:body>")
    write(paper.working, {**parts, "word/document.xml": doc.encode()})

    report = revision.ingest(paper.working, paper.prev, paper=paper)

    assert report.deleted == []
    assert len([x for x in report.lost if x.kind == "footnote"]) == 3


def test_baseline_says_PENDING_before_it_says_LOST(tmp_path):
    """Review 2026-10-14. One stray pending revision makes the batch's
    excuse refuse (an unopened proposal is not an accepted one), and the
    loss gate ran first: the author was told to `--accept-loss` the
    batch's own deletions, when what stands between them and a baseline
    is the revision they have not decided."""
    from docxkit.errors import BaselinePending

    paper = _round(tmp_path)
    parts = _accept_all(paper)
    doc = parts["word/document.xml"].decode().replace(
        "</w:body>", para(_ins(run("still pending"), 900)) + "</w:body>")
    write(paper.working, {**parts, "word/document.xml": doc.encode()})

    with pytest.raises(BaselinePending):
        revision.baseline(paper, log=False)


def test_naming_the_batch_s_deletion_in_accept_loss_is_not_STALE(tmp_path):
    """A flag written before this existed names something really gone,
    so it must not be refused as an exemption with nothing under it."""
    paper = _round(tmp_path)
    _accept_all(paper)

    report = revision.baseline(paper, accept_loss=(NOTES[2][:30],),
                               log=False)

    assert len(report.deleted) == 3


def test_the_deletion_named_AS_INGEST_PRINTS_it_is_not_STALE(tmp_path):
    """Review 2026-10-24. The batch rewords note 1 and cuts note 2;
    `ingest` names the cut by its own words, NOTES[2], while the loss
    list's best effort names note 1's old text. A flag copied from the
    "DELETED BY THE BATCH" line was refused as naming nothing lost."""
    paper = _round(tmp_path, deleted=frozenset({2}), promote=False)
    batch = package.read_parts(paper.batch)
    notes = batch["word/footnotes.xml"].decode().replace(
        run(NOTES[1]),
        _del(f"<w:r><w:delText>{NOTES[1]}</w:delText></w:r>", 601)
        + _ins(run("Note 1, as the batch rewords it."), 602))
    write(paper.batch, {**batch, "word/footnotes.xml": notes.encode()})
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    revision.promote(paper)
    _accept_all(paper)

    report = revision.baseline(paper, log=False,
                               accept_loss=(f"footnote:{NOTES[2][:30]}",))

    assert [loss.what for loss in report.deleted] == [NOTES[2]]


# ------------------------------------------------------------ comments

def test_a_comment_the_BATCH_does_not_carry_is_the_batch_s(tmp_path):
    """The build took a comment out (last round's reason balloons, say):
    the author was never offered it, and its absence is no loss."""
    paper = _round(tmp_path, deleted=frozenset(),
                   comments=("Referee: cite it.", "R1: hedged"),
                   batch_comments=("Referee: cite it.",))
    _accept_all(paper)

    report = revision.baseline(paper, log=False)

    assert [(x.kind, x.what) for x in report.deleted] == [
        ("comment", "Tester: R1: hedged")]


def test_a_comment_the_batch_CARRIED_and_the_hand_back_lost_is_LOST(
        tmp_path):
    """The batch kept the referee's comment and added a balloon; the
    hand-back has the balloon and not the referee's. Counted, nothing
    went; named, the referee's comment did."""
    paper = _round(tmp_path, deleted=frozenset(),
                   comments=("Referee: cite it.",),
                   batch_comments=("Referee: cite it.", "R1: hedged"))
    parts = _accept_all(paper)
    write(paper.working, {**parts, "word/comments.xml": make_parts(
        "", comment_items=_comments(("R1: hedged",)))["word/comments.xml"]})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Referee: cite it." in str(caught.value)


# ------------------------------------------------------- links, bookmarks

CUT = (("Barr2010", "Barr 2010"), ("Cox1987", "Cox 1987"),
       ("Holzmann2005", "Holzmann 2005"))


def test_a_cut_citation_s_LINK_and_BOOKMARK_are_the_batch_s_too(tmp_path):
    """The sentence goes with its link and its `*txt` back-link target,
    three times. Word drops a bookmark whose content was all deleted,
    and since 2026-10-12 so does the accepted view, so the hand-back's
    bookmarks equal the proposal's."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT,
                   links=(("Sen1999", "Sen 1999"),))
    _accept_all(paper)

    report = revision.baseline(paper, log=False)

    assert sorted((loss.kind, loss.what.split()[0])
                  for loss in report.deleted) == sorted(
        [("link", a) for a, _ in CUT] + [("bookmark", f"{a}txt")
                                         for a, _ in CUT])


def test_BOOKMARKS_of_REJECTED_cuts_removed_by_hand_are_LOST(tmp_path):
    """Review 2026-10-14, finding 1, the bookmark half. The author
    rejected all three cuts, and the `*txt` targets were deleted by hand
    afterwards (what `revision build`'s advice used to ask for). The
    hand-back's bookmarks equal the proposal's accepted view, but every
    cut's words are on the page: none of the three was the batch's."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT)
    doc = make_parts(_before(NOTES, cut_links=CUT),
                     footnotes=_footnotes(NOTES))
    body = doc["word/document.xml"].decode()
    for i, (anchor, _label) in enumerate(CUT):
        body = body.replace(
            f'<w:bookmarkStart w:id="{80 + i}" w:name="{anchor}txt"/>', "")
        body = body.replace(f'<w:bookmarkEnd w:id="{80 + i}"/>', "")
    write(paper.working, {**doc, "word/document.xml": body.encode()})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Barr2010txt" in str(caught.value)


def test_a_cut_link_whose_LABEL_survives_elsewhere_is_the_batch_s(tmp_path):
    """`Cox 1987` is cited twice and the batch cuts one, accepted. Until
    2026-10-24 a link whose label was still on the page stayed a loss,
    because Word stripping the OTHER copy leaves that shape too. Shown at
    its place, the cut was accepted; the stripped-other-copy case is the
    next test, and it refuses."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT,
                   links=(("Cox1987", "Cox 1987"),))
    _accept_all(paper)

    report = revision.baseline(paper, log=False)

    assert sorted(loss.what.split()[0] for loss in report.deleted
                  if loss.kind == "link") == sorted(a for a, _ in CUT)


def test_the_cut_accepted_and_Word_STRIPPED_the_other_copy_refuses(
        tmp_path):
    """The case the old words-survive rule stood for: the batch's cut of
    one `Cox 1987` accepted, and Word stripped the kept copy's link. Two
    gone where the accepted view says one: nothing of the kind is
    excused."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT,
                   links=(("Cox1987", "Cox 1987"),))
    parts = _accept_all(paper)
    doc = parts["word/document.xml"].decode().replace(
        _link("Cox1987", "Cox 1987"), run("Cox 1987"))
    write(paper.working, {**parts, "word/document.xml": doc.encode()})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Cox1987" in str(caught.value)


def test_a_REJECTED_cut_whose_citation_was_RETYPED_is_LOST(tmp_path):
    """Review 2026-10-24, finding 2. The batch cuts the Barr and the Cox
    sentences; the author accepts the Cox cut, rejects the Barr one and
    retypes its citation as "Barr (2010)", which drops the link. The
    links equal the accepted view's and the old label is no longer on
    the page, so the link was excused on those two facts alone. At its
    place the cut was rejected."""
    cut = CUT[:2]
    paper = _round(tmp_path, deleted=frozenset(), cut_links=cut)
    parts = _accept_all(paper)
    retyped = para(run("Kept. "),
                   '<w:bookmarkStart w:id="80" w:name="Barr2010txt"/>'
                   + run("Barr (2010)") + '<w:bookmarkEnd w:id="80"/>')
    doc = parts["word/document.xml"].decode().replace(
        para(run("Kept. ")), retyped, 1)
    write(paper.working, {**parts, "word/document.xml": doc.encode()})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Barr2010 (Barr 2010)" in str(caught.value)


def test_a_REJECTED_cut_at_the_END_of_the_part_is_LOST(tmp_path):
    """Review 2026-10-24, finding 1. The cut is the last text of the
    body, so the accepted reading had no right-hand side: the words
    before it, which every hand-back holds. The author rejects the cut,
    changes a character of the restored citation, and Word drops its
    bookmark — excused as the batch's deletion, and `baseline` wrote a
    truth whose citation links to a bookmark that is gone."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT[:1])
    doc = make_parts(_before(NOTES), footnotes=_footnotes(NOTES))
    body = doc["word/document.xml"].decode().replace(
        "</w:body>", para(run("Kept. "), _link("Barr2010", "Barr 2011"))
        + "</w:body>")
    write(paper.working, {**doc, "word/document.xml": body.encode()})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Barr2010txt" in str(caught.value)


def test_the_cut_at_the_END_of_the_part_ACCEPTED_is_the_batch_s(tmp_path):
    """The control: the same cut accepted, and the hand-back ends where
    the proposal accepted ends."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT[:1])
    _accept_all(paper)

    report = revision.baseline(paper, log=False)

    assert sorted(loss.kind for loss in report.deleted) == [
        "bookmark", "link"]


def test_a_context_the_proposal_holds_TWICE_shows_nothing(tmp_path):
    """Review 2026-10-24, finding 1, the second shape. The words around
    the cut are also a paragraph of their own elsewhere — duplicated
    table rows do it — so the hand-back's copy of the accepted reading
    may be the other one. The author rejected the cut and edited it, and
    Word dropped its bookmark: still LOST."""
    words = "These words are repeated in two places here."
    twin = para(run(f"{words} Kept. Then the paragraph goes on a while."))
    truth = para(run(f"{words} Kept. "),
                 '<w:bookmarkStart w:id="90" w:name="Zyl2019txt"/>'
                 + run("Zyl 2019") + '<w:bookmarkEnd w:id="90"/>',
                 run("Then the paragraph goes on a while."))
    cut = para(run(f"{words} Kept. "),
               _del('<w:bookmarkStart w:id="90" w:name="Zyl2019txt"/>'
                    "<w:r><w:delText>Zyl 2019</w:delText></w:r>"
                    '<w:bookmarkEnd w:id="90"/>', 299),
               run("Then the paragraph goes on a while."))
    paper = _round(tmp_path, deleted=frozenset(), extra=twin + truth,
                   batch_extra=twin + cut)
    hand = make_parts(_before(NOTES) + twin + para(
        run(f"{words} Kept. Zyl 2020Then the paragraph goes on a while.")),
        footnotes=_footnotes(NOTES))
    write(paper.working, hand)

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Zyl2019txt" in str(caught.value)


def test_a_bookmark_deleted_by_hand_as_BUILD_ADVISES_keeps_the_rest(
        tmp_path):
    """Review 2026-10-24, finding 4. `revision build` asks for a bookmark
    Compare restored to be deleted by hand after the promote. Done, the
    hand-back's bookmarks no longer equal the accepted view's, and every
    bookmark the batch cut was refused with them. That one is flagged;
    the batch's are the batch's."""
    lari = ('<w:bookmarkStart w:id="70" w:name="Lari2023"/>'
            + run("Lari") + '<w:bookmarkEnd w:id="70"/>')
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT,
                   extra=para(lari))
    parts = _accept_all(paper)
    doc = parts["word/document.xml"].decode().replace(lari, run("Lari"))
    write(paper.working, {**parts, "word/document.xml": doc.encode()})

    report = revision.baseline(paper, log=False,
                               accept_loss=("bookmark:Lari2023",))

    assert sorted(loss.what for loss in report.deleted
                  if loss.kind == "bookmark") == sorted(
        f"{a}txt" for a, _ in CUT)


def test_a_link_Word_STRIPPED_beside_the_cuts_refuses_them_all(tmp_path):
    """A kept citation lost its link and kept its words: the hand-back's
    links are no longer the proposal's, so no link is excused."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT,
                   links=(("Sen1999", "Sen 1999"),))
    parts = _accept_all(paper)
    doc = parts["word/document.xml"].decode().replace(
        _link("Sen1999", "Sen 1999"), run("Sen 1999"))
    write(paper.working, {**parts, "word/document.xml": doc.encode()})

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Sen1999" in str(caught.value)


# ------------------------------------------------------ the evidence

def test_the_stream_skips_comments_snapshots_and_field_codes():
    """What `_accepted_here` compares is what a reader sees: an XML
    comment, a formatting snapshot and a field's code are not text, and
    the note mark's place and state are kept."""
    from lxml import etree

    from docxkit.revision._losses import _DEL, _SAME, _stream

    xml = (f'<w:body {_NS_W}><w:p><!-- a remark -->'
           '<w:r><w:rPr><w:rPrChange w:id="1"><w:rPr/></w:rPrChange>'
           '</w:rPr><w:instrText>REF x</w:instrText><w:t>Kept.</w:t></w:r>'
           + _del('<w:r><w:delText>Cut.</w:delText></w:r>' + _ref(3), 7)
           + "</w:p></w:body>")
    texts, marks = _stream(etree.fromstring(xml))

    assert texts == [("Kept.", _SAME), ("Cut.", _DEL)]
    assert [(m.kind, m.key, m.state, m.at) for m in marks] == [
        ("footnote", "3", _DEL, 2)]


def _field(instr, label, *, deleted=False, separate=True):
    """A field-form link, Compare's way: the code split over two runs,
    and `deleted` puts the whole field in a `w:del` with `delInstrText`."""
    code, text = ("delInstrText", "delText") if deleted else ("instrText",
                                                               "t")
    half = len(instr) // 2
    runs = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f"<w:r><w:{code}>{instr[:half]}</w:{code}></w:r>"
            f"<w:r><w:{code}>{instr[half:]}</w:{code}></w:r>"
            + ('<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
               if separate else "")
            + f"<w:r><w:{text}>{label}</w:{text}></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    return _del(runs, 777) if deleted else runs


def test_the_stream_marks_FIELD_links_where_they_start():
    """A link Compare deletes is almost always a field whose code is
    deleted with it, so the code is read from `delInstrText` too, joined
    across runs. HYPERLINK and REF \\h are links; PAGEREF is not; a field
    with no `separate` is marked at its end; a field nested in another is
    a link of its own."""
    from lxml import etree

    from docxkit.revision._losses import _DEL, _SAME, _stream

    nested = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
              "<w:r><w:instrText>REF Outer \\h</w:instrText></w:r>"
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
              + _field('HYPERLINK \\l "Inner"', "in")
              + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    xml = (f'<w:body {_NS_W}><w:p>'
           + _field('HYPERLINK \\l "Cut2020"', "Cut 2020", deleted=True)
           + _field("REF Table1 \\h", "Table 1")
           + _field("PAGEREF Table1 \\h", "3")
           + _field('HYPERLINK \\l "Late"', "late", separate=False)
           + nested + "</w:p></w:body>")
    _texts, marks = _stream(etree.fromstring(xml))

    assert [(m.kind, m.key, m.state, m.at) for m in marks] == [
        ("link", "Cut2020", _DEL, 0), ("link", "Table1", _SAME, 1),
        ("link", "Late", _SAME, 4), ("link", "Outer", _SAME, 4),
        ("link", "Inner", _SAME, 4)]


@pytest.mark.parametrize("accepted", [True, False])
def test_a_cut_FIELD_link_accepted_is_the_batch_s_and_rejected_is_LOST(
        tmp_path, accepted):
    """The batch cuts a citation written as a field, the shape Compare
    writes; accepted it is the batch's, rejected and retyped without its
    link it is LOST."""
    kept = para(run("Kept. "), _field('HYPERLINK \\l "Cut2020"', "Cut 2020"),
                run(" and the sentence goes on."))
    cut = para(run("Kept. "),
               _field('HYPERLINK \\l "Cut2020"', "Cut 2020", deleted=True),
               run(" and the sentence goes on."))
    paper = _round(tmp_path, deleted=frozenset(), extra=kept,
                   batch_extra=cut)
    if accepted:
        _accept_all(paper)
        report = revision.baseline(paper, log=False)
        assert [x.kind for x in report.deleted] == ["link"]
        return
    write(paper.working, make_parts(_before(NOTES) + para(
        run("Kept. Cut (2020) and the sentence goes on.")),
        footnotes=_footnotes(NOTES)))
    with pytest.raises(HandbackLoss, match="Cut2020"):
        revision.baseline(paper, log=False)


def test_a_GLYPH_alone_is_handed_back_untouched():
    from docxkit.revision._losses import Loss, batch_deletions

    gone = [Loss("glyph", "− -> -")]
    parts = make_parts(para(run("x")))

    assert batch_deletions(gone, parts, parts, parts) == ([], gone)


def test_a_loss_no_batch_proposes_is_never_excused():
    """A glyph Word flattened is not a kind a batch deletes, and a
    comment no proposal lacks is not the batch's, so `batch_deletions`
    hands the list back untouched."""
    from docxkit.revision._losses import Loss, batch_deletions

    gone = [Loss("glyph", "− -> -"), Loss("comment", "1 comment(s)")]
    parts = make_parts(para(run("x")))

    assert batch_deletions(gone, parts, parts, parts) == ([], gone)


# ------------------------------------------------- a batch Word holds

def _word_holds_batch(monkeypatch, paper, *, copies=False, seen=True):
    """Word holding `batch.docx` with the read denied (HPPA, 2026-10-09).

    `copies`: a byte copy of it still reads, as one of a file Word holds
    usually does (`package.readable`). `seen`: `is_locked` answers True —
    False is a lock it cannot see, a read-only file something holds."""
    import shutil
    from pathlib import Path

    held, real, real_copy = paper.batch.resolve(), guard.sha256, \
        shutil.copyfile

    def sha256(p):
        if Path(p).resolve() == held:
            raise PermissionError(13, "Permission denied", str(p))
        return real(p)

    def copyfile(src, dst, *args, **kwargs):
        if not copies and Path(src).resolve() == held:
            raise PermissionError(13, "Permission denied", str(src))
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(guard, "sha256", sha256)
    monkeypatch.setattr(shutil, "copyfile", copyfile)
    monkeypatch.setattr(package, "is_locked",
                        lambda p: seen and Path(p).resolve() == held)
    monkeypatch.setattr(package, "_back_off", lambda *_a: None)


def test_a_LOCKED_batch_is_said_to_be_locked_not_LOST(monkeypatch, tmp_path):
    """Review 2026-10-14, finding 13. The batch's own deletions, all
    accepted, with batch.docx open in Word and no copy of it readable
    either: the PermissionError from its hash was swallowed as "no
    excuse", `baseline` printed LOST with `--accept-loss` advice, and
    following it crashed with exit 70."""
    from docxkit.errors import DocumentLocked

    paper = _round(tmp_path)
    _accept_all(paper)
    _word_holds_batch(monkeypatch, paper)

    with pytest.raises(DocumentLocked, match=r"batch\.docx is open"):
        revision.baseline(paper, log=False)
    with pytest.raises(DocumentLocked):
        revision.baseline(paper, log=False,
                          accept_loss=tuple(NOTES[k][:30] for k in (2, 4, 6)))


def test_ingest_check_says_the_batch_is_LOCKED(monkeypatch, tmp_path,
                                               capsys):
    paper = _round(tmp_path)
    _accept_all(paper)
    _word_holds_batch(monkeypatch, paper)

    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(paper.root))

    assert "batch.docx is open in Word" in str(code)
    assert "== LOST" not in capsys.readouterr().out


def test_a_batch_Word_holds_is_read_through_a_COPY(monkeypatch, tmp_path,
                                                   capsys):
    """Review 2026-10-24, finding 11. Refusing at once made the read-only
    `ingest` die with no report while Word held batch.docx, though a copy
    of it reads and hashes the same. Read through the copy, the round
    passes as it would with the batch closed."""
    paper = _round(tmp_path)
    _accept_all(paper)
    _word_holds_batch(monkeypatch, paper, copies=True)

    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(paper.root))

    out = capsys.readouterr().out
    assert code == 0, out
    assert "DELETED BY THE BATCH (3)" in out
    assert len(revision.baseline(paper, log=False).deleted) == 3


def test_a_lock_is_locked_UNSEEN_says_so_and_is_not_LOST(monkeypatch,
                                                         tmp_path):
    """Review 2026-10-24, finding 11, the other direction. A read-only
    file something holds is no lock `is_locked` can see, so the bare
    PermissionError went to the broad except, the batch's own deletions
    came back LOST, and `--accept-loss` then exited 70 in `verdict`. It
    is a file that cannot be read, named."""
    from docxkit.errors import PackageError

    paper = _round(tmp_path)
    _accept_all(paper)
    _word_holds_batch(monkeypatch, paper, seen=False)

    with pytest.raises(PackageError, match=r"cannot read batch\.docx"):
        revision.baseline(paper, log=False)
    with pytest.raises(PackageError, match=r"cannot read batch\.docx"):
        revision.baseline(paper, log=False,
                          accept_loss=tuple(NOTES[k][:30] for k in (2, 4, 6)))


def test_an_UNPARSEABLE_proposal_leaves_the_losses_where_they_are(tmp_path):
    """The proposal was read inside the guard and its views computed
    outside it: a text part that does not parse crashed the read-only
    `ingest` instead of reporting the loss."""
    paper = _round(tmp_path, deleted=frozenset({2}), promote=False)
    batch = package.read_parts(paper.batch)
    batch["word/endnotes.xml"] = (
        f'<w:endnotes {_NS_W}><w:ins w:id="9" {_STAMP}>').encode()
    write(paper.batch, batch)
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    revision.promote(paper)
    write(paper.working, _without_note(
        make_parts(_before(NOTES), footnotes=_footnotes(NOTES)), 2))

    report = revision.ingest(paper.working, paper.prev, paper=paper)

    assert report.deleted == []
    assert [x.kind for x in report.lost] == ["footnote"]


# -------------------------------------------------------------- the CLI

def test_ingest_check_PASSES_and_names_the_batch_s_deletions(
        monkeypatch, tmp_path, capsys):
    paper = _round(tmp_path)
    _accept_all(paper)

    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(paper.root))

    out = capsys.readouterr().out
    assert code == 0, out
    assert "DELETED BY THE BATCH (3)" in out
    assert "== LOST" not in out


def test_ingest_JSON_carries_the_batch_s_deletions_apart_from_the_losses(
        monkeypatch, tmp_path, capsys):
    """A script reads `--json`, and the review found its "deleted" key
    pinned by nothing: dropped or merged into "lost", the console would
    still have read right."""
    import json

    paper = _round(tmp_path)
    _accept_all(paper)
    out = tmp_path / "ingest.json"

    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--json", str(out), "--paper", str(paper.root))

    assert code == 0, capsys.readouterr().out
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["lost"] == []
    assert sorted(report["deleted"]) == sorted(
        f"footnote:{NOTES[k]}" for k in (2, 4, 6))


def test_baseline_LISTS_what_it_recorded_as_the_batch_s_deletion(
        monkeypatch, tmp_path, capsys):
    """Recorded, not refused, and said: the one decision `baseline` takes
    that no flag on the command line records."""
    paper = _round(tmp_path)
    _accept_all(paper)

    code, _ = run_cli(monkeypatch, "revision", "baseline", "--no-log",
                      "--paper", str(paper.root))

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.count("deleted by the batch: footnote") == 3


def test_ingest_check_still_EXITS_on_a_note_Word_ate(monkeypatch, tmp_path,
                                                     capsys):
    paper = _round(tmp_path)
    write(paper.working, _without_note(_accept_all(paper), 5))

    code, _ = run_cli(monkeypatch, "revision", "ingest", "--check",
                      "--paper", str(paper.root))

    assert code == HandbackLoss.exit_code
    assert "DELETED BY THE BATCH" not in capsys.readouterr().out
