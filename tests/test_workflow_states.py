"""The revision protocol's workflow states, built once and pinned.

BACKLOG, "Not four defects — one missing class of test": a batch built
on the current baseline and deliberately HELD was a state no fixture
produced, and `revision baseline` read it as the author rejecting the
batch — a wrong verdict, pre-formatted for the paper's permanent log and
hand-corrected three times (Aging_Well, 2026-08-28). The fix came with a
fixture that reached that one state. What was still missing was the SET,
built once and shared, so a future question about a verdict starts from
a state that exists instead of a fourth private way of reaching one.

The states are `conftest.py`'s `held_round`, `promoted_round`,
`accepted_round`, `rejected_round` and `partly_round`, reached through
the protocol's own verbs where a verb exists — `init`, the stamp `build`
writes, the real `promote`. Only the author's Word session is written by
hand, because the tool never accepts or rejects on their behalf.

What this file pins is what each state IS, read through the public
surface: `state`, `status`, `verdict`, the promote's record, and what
`build` and `baseline` refuse. Every assertion here is one a test
elsewhere would otherwise have to re-establish before asking its own
question.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, revision_round, run, write

from docxkit import guard, package, revision
from docxkit.errors import BaselinePending, ProtocolError, WorkingPending
from docxkit.revision import state, status, verdict


def _clean_edit(paper):
    """The next round's clean copy, staged where `build` would read it."""
    edit = paper.build_dir / "clean.docx"
    write(edit, make_parts(para(run("a new proposal"))))
    return edit


# ----------------------------------------------------------------- held

def test_HELD_is_the_truth_with_a_batch_stamped_beside_it(held_round):
    paper = held_round.paper

    assert state(paper.working).is_truth
    assert status(paper).exit_code == 0, "a held batch is not a pending one"
    assert paper.batch.is_file()
    assert guard.base_of(paper.batch) == guard.sha256(paper.prev), (
        "the batch is built on THIS baseline — the stamp `build` writes")
    assert paper.redlines() == [], "nothing was promoted"
    (row,) = revision.survey([paper.config])
    assert row.staged and row.verdict == "truth"


def test_HELD_is_not_this_rounds_proposal(held_round):
    """The state the whole entry is about. The batch is stamped against
    the current baseline — the hash guard answers yes, rightly — and it
    never reached the manuscript; its absence there reads exactly like
    a rejection, and only the promote's record can tell them apart."""
    held_round.hand_back(*held_round.baseline, "a sentence of my own")

    result = verdict(held_round.paper)

    assert result.batch is None
    assert result.outcome == "adjudicated (no batch to compare against)"
    assert "rejected" not in result.outcome


# ------------------------------------------------------------- promoted

def test_PROMOTED_is_a_proposal_and_the_record_of_one(promoted_round):
    paper = promoted_round.paper

    st = state(paper.working)
    assert not st.is_truth and st.pending == 4       # two ins, two del
    assert status(paper).exit_code == 1
    assert paper.working.read_bytes() == paper.batch.read_bytes(), (
        "the manuscript IS the batch, byte for byte")
    (redline,) = paper.redlines()
    assert redline.read_bytes() == paper.batch.read_bytes(), (
        "the record `verdict` reads: the batch's own bytes, kept")
    assert revision.rescues(paper), "and the file it replaced, kept"


def test_PROMOTED_refuses_the_next_build_and_the_baseline(promoted_round):
    """Both doors out of this state are the author's, not the tool's —
    except `withdraw`, below, for a proposal the author never opened."""
    paper = promoted_round.paper

    with pytest.raises(WorkingPending):
        revision.build(paper, _clean_edit(paper))
    with pytest.raises(BaselinePending):
        revision.baseline(paper)


# ------------------------------------------------------------ withdrawn
#
# BACKLOG S4, Month_of_birth, 2026-09-15: R1 was promoted, three
# statements in it turned out wrong before the author had opened the
# file, and every route the CLI offered refused — `build
# --allow-pending-working` then failed on `drift`, whose advice
# (baseline) would adopt the unaccepted proposal as the truth, and
# `promote` wanted a base that both the live file and the new batch
# answered to. The way out was copying a rescue over the manuscript by
# hand, after checking three hashes.

def _ledger_lines(paper):
    import json

    from docxkit.revision import _ledger
    path = _ledger.ledger_path(paper)
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_WITHDRAWN_is_the_truth_again_and_the_proposal_is_KEPT(
        promoted_round):
    paper = promoted_round.paper
    proposal = paper.working.read_bytes()

    report = revision.withdraw(paper, why="three statements were wrong")

    assert paper.working.read_bytes() == paper.prev.read_bytes()
    assert state(paper.working).is_truth
    assert status(paper).exit_code == 0, "neither pending nor stale"
    (redline,) = paper.redlines()
    assert redline.read_bytes() == proposal, "the record of what was offered"
    assert report.withdrawn == redline and report.onto == paper.working
    # the batch file IS that proposal, and left staged it would be read
    # as this round's by `verdict` — "rejected in full" for a batch the
    # author never saw
    assert report.removed_batch and not paper.batch.exists()
    assert not guard.stamp_path(paper.batch).exists()
    # the stamp beside the manuscript described the proposal's bytes
    assert not guard.stamp_path(paper.working).exists()
    last = _ledger_lines(paper)[-1]
    assert last["event"] == "withdrawn"
    assert last["why"] == "three statements were wrong"
    assert last["withdrawn_sha256"] == guard.sha256(redline)
    assert last["restored_sha256"] == guard.sha256(paper.prev)


def test_WITHDRAWN_takes_the_next_promote_as_usual(promoted_round):
    """The whole point: the rebuilt proposal goes on through the
    ordinary door, with nothing forced."""
    paper = promoted_round.paper
    revision.withdraw(paper, why="rebuilding")

    write(paper.batch, make_parts(para(run("the corrected proposal"))))
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    revision.promote(paper)

    assert paper.working.read_bytes() == paper.batch.read_bytes()
    assert len(paper.redlines()) == 2


def test_WITHDRAWN_then_an_author_round_is_not_read_as_a_rejection(
        promoted_round):
    """What removing the staged batch buys. Left in place, the author's
    own later edits would be logged as the withdrawn batch "rejected in
    full" — the Aging_Well verdict defect by another road."""
    paper = promoted_round.paper
    revision.withdraw(paper, why="rebuilding")
    promoted_round.hand_back(*promoted_round.baseline, "the author's own")

    result = verdict(paper)

    assert result.batch is None
    assert "rejected" not in result.outcome


def test_WITHDRAW_refuses_once_the_author_has_SAVED_the_proposal(
        promoted_round):
    """The one thing withdrawing may never cost is an author's work. A
    manuscript that is no longer the promoted bytes has been opened and
    saved, and whatever was decided in it is theirs."""
    paper = promoted_round.paper
    promoted_round.hand_back(*promoted_round.partly)
    before = paper.working.read_bytes()
    lines = len(_ledger_lines(paper))

    with pytest.raises(ProtocolError, match="no longer the batch"):
        revision.withdraw(paper, why="too late")

    assert paper.working.read_bytes() == before
    assert paper.batch.exists()
    assert len(_ledger_lines(paper)) == lines


def test_WITHDRAW_refuses_a_manuscript_nothing_was_promoted_onto(
        held_round):
    paper = held_round.paper
    before = paper.working.read_bytes()

    with pytest.raises(ProtocolError, match="nothing has been promoted"):
        revision.withdraw(paper, why="nothing to withdraw")

    assert paper.working.read_bytes() == before
    assert paper.batch.exists()


def test_WITHDRAW_refuses_when_the_BASELINE_is_not_what_was_replaced(
        promoted_round):
    """Restoring means putting back the file the promote replaced, and
    that is `prev` only while `prev` is still the baseline the batch was
    built on. A baseline adopted since — or a promote made with another
    `--base` — would put a different generation on the paper."""
    paper = promoted_round.paper
    write(paper.prev, make_parts(para(run("another generation"))))
    for rescue in revision.rescues(paper):
        rescue.unlink()
    before = paper.working.read_bytes()

    with pytest.raises(ProtocolError, match="was not built on"):
        revision.withdraw(paper, why="stale baseline")

    assert paper.working.read_bytes() == before


def test_WITHDRAW_of_an_UNSTAMPED_proposal_is_proved_by_its_RESCUE(
        held_round):
    """The hand-authored vehicle carries no stamp to say what it was
    built on. The rescue the promote took says what it REPLACED, and a
    rescue holding the baseline's bytes is the same proof."""
    paper = held_round.paper
    guard.stamp_path(paper.batch).unlink()
    revision.promote(paper)

    revision.withdraw(paper, why="hand-authored, withdrawn")

    assert paper.working.read_bytes() == paper.prev.read_bytes()


def test_WITHDRAW_leaves_a_batch_REBUILT_since_alone(promoted_round):
    """Only the withdrawn batch is unstaged. One rebuilt on the baseline
    before withdrawing is the next proposal, not litter."""
    paper = promoted_round.paper
    write(paper.batch, make_parts(para(run("already rebuilt"))))
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    rebuilt = paper.batch.read_bytes()

    report = revision.withdraw(paper, why="rebuilt first")

    assert not report.removed_batch
    assert paper.batch.read_bytes() == rebuilt
    assert guard.stamp_path(paper.batch).exists()


def test_WITHDRAW_needs_its_baseline(promoted_round):
    paper = promoted_round.paper
    paper.prev.unlink()

    with pytest.raises(ProtocolError, match="missing"):
        revision.withdraw(paper, why="no baseline")


def test_WITHDRAW_that_did_not_LAND_says_where_the_proposal_still_is(
        promoted_round, monkeypatch):
    """A copy that did not land has put neither generation on the paper,
    and the one thing worth saying is where the proposal's bytes are.
    Nothing after it runs: the ledger is not told of a withdrawal that
    did not happen, and the staged batch stays."""
    import shutil

    paper = promoted_round.paper
    lines = len(_ledger_lines(paper))
    monkeypatch.setattr(shutil, "copyfile",
                        lambda _s, d, *a, **k: d.write_bytes(b"half"))

    with pytest.raises(ProtocolError, match="still holds the proposal"):
        revision.withdraw(paper, why="bad disk")

    assert len(_ledger_lines(paper)) == lines
    assert paper.batch.exists()


def test_WITHDRAW_refuses_while_word_holds_the_manuscript(promoted_round,
                                                           monkeypatch):
    from docxkit.errors import DocumentLocked

    paper = promoted_round.paper
    monkeypatch.setattr(revision.package, "is_locked", lambda _p: True)
    before = paper.working.read_bytes()

    with pytest.raises(DocumentLocked):
        revision.withdraw(paper, why="open in Word")

    assert paper.working.read_bytes() == before


# ------------------------------------------------------------- accepted

def test_ACCEPTED_reads_as_accepted_in_full(accepted_round):
    result = verdict(accepted_round.paper)

    assert (result.kept, result.reverted, result.authored) == (2, 0, 0)
    assert result.outcome == "accepted in full"
    assert "2 ¶ changed" in result.summary()
    assert "from 4 revisions (2 ins, 2 del)" in result.summary()


def test_ACCEPTED_is_settled_on_a_baseline_it_has_OUTGROWN(accepted_round):
    """Both files read 0 pending and they are not the same paper: the
    state `drift` exists for, and the one `baseline` closes."""
    paper = accepted_round.paper
    assert status(paper).exit_code == 4

    report = revision.baseline(paper, note="R1")

    assert report.row and "accepted in full" in report.row
    assert status(paper).exit_code == 0


# ------------------------------------------------------------- rejected

def test_REJECTED_reads_as_rejected_in_full(rejected_round):
    result = verdict(rejected_round.paper)

    assert (result.kept, result.reverted) == (0, 2)
    assert result.outcome == "rejected in full"


def test_REJECTED_and_HELD_leave_the_SAME_manuscript(rejected_round,
                                                     tmp_path):
    """Content cannot tell the two apart. The record can, and does.

    A second, independent round for the held side: asking for
    `held_round` beside `rejected_round` hands back the SAME round —
    the held one is the rejected one's ancestor fixture, promoted in
    between — which is a fact about pytest and not about the protocol.
    """
    held = revision_round(tmp_path, name="held")
    assert (package.read_parts(rejected_round.paper.working)
            == package.read_parts(held.paper.working))

    assert verdict(rejected_round.paper).outcome == "rejected in full"
    assert verdict(held.paper).batch is None


def test_REJECTED_is_still_a_round_worth_a_row(rejected_round):
    """Nothing visible changed, so `status` calls the baseline current
    — and the log still gets the verdict, because "the author said no
    to all of it" is a fact about the round."""
    paper = rejected_round.paper
    assert status(paper).exit_code == 0

    report = revision.baseline(paper, note="R1")

    assert report.row and "rejected in full" in report.row


# --------------------------------------------------------------- partly

def test_PARTLY_reads_as_one_of_two_kept(partly_round):
    result = verdict(partly_round.paper)

    assert (result.kept, result.reverted) == (1, 1)
    assert result.outcome == "1 of 2 kept as proposed"
    assert "1 ¶ changed" in result.summary()


def test_PARTLY_is_settled_and_stale_like_an_accept(partly_round):
    paper = partly_round.paper
    assert state(paper.working).is_truth
    assert status(paper).exit_code == 4

    report = revision.baseline(paper, note="R1")

    assert report.row and "1 of 2 kept as proposed" in report.row
