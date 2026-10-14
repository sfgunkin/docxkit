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
from conftest import make_parts, para, run, write
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


def _before(notes, *, links=(), cut_links=()):
    """The truth the batch was built on: the same shapes, nothing cut."""
    out = "".join(para(run(f"Claim {k}."), _ref(k)) for k in notes)
    for anchor, label in links:
        out += para(run("As "), _link(anchor, label), run(" showed."))
    for i, (anchor, label) in enumerate(cut_links):
        out += para(run("Kept. "),
                    f'<w:bookmarkStart w:id="{80 + i}" w:name="{anchor}txt"/>'
                    + _link(anchor, label)
                    + f'<w:bookmarkEnd w:id="{80 + i}"/>')
    return out


def _round(tmp_path, *, deleted=frozenset({2, 4, 6}), links=(),
           cut_links=(), promote=True, notes=None):
    """A paper whose promoted batch deletes `deleted` notes and the
    sentences in `cut_links`, built on a truth that has all of them."""
    notes = NOTES if notes is None else notes
    root = tmp_path / "HPPA"
    root.mkdir()
    src = write(root / "HPPA.docx",
                make_parts(_before(notes, links=links, cut_links=cut_links),
                           footnotes=_footnotes(notes)))
    paper = revision.init(root, src, name="HPPA")
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(
        _body(notes, deleted, links=links, cut_links=cut_links),
        footnotes=_footnotes(notes, deleted)))
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    if promote:
        revision.promote(paper)
    return paper


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


def test_a_cut_link_whose_LABEL_survives_elsewhere_still_refuses(tmp_path):
    """`Cox 1987` is cited twice and the batch cuts one. A label that is
    still on the page is the shape Word stripping the OTHER copy leaves
    too, so this one stays a loss."""
    paper = _round(tmp_path, deleted=frozenset(), cut_links=CUT,
                   links=(("Cox1987", "Cox 1987"),))
    _accept_all(paper)

    with pytest.raises(HandbackLoss) as caught:
        revision.baseline(paper, log=False)

    assert "Cox1987" in str(caught.value)
    assert "Barr2010 (" not in str(caught.value)


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


# ------------------------------------------------- a batch Word holds

def _word_holds_batch(monkeypatch, paper):
    """Word holding `batch.docx` with the read denied (HPPA, 2026-10-09)."""
    from pathlib import Path

    held, real = paper.batch.resolve(), guard.sha256

    def sha256(p):
        if Path(p).resolve() == held:
            raise PermissionError(13, "Permission denied", str(p))
        return real(p)

    monkeypatch.setattr(guard, "sha256", sha256)
    monkeypatch.setattr(package, "is_locked",
                        lambda p: Path(p).resolve() == held)


def test_a_LOCKED_batch_is_said_to_be_locked_not_LOST(monkeypatch, tmp_path):
    """Review 2026-10-14, finding 13. The batch's own deletions, all
    accepted, with batch.docx open in Word: the PermissionError from its
    hash was swallowed as "no excuse", `baseline` printed LOST with
    `--accept-loss` advice, and following it crashed with exit 70."""
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
