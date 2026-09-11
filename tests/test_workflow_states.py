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
from docxkit.errors import BaselinePending, WorkingPending
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
    """Both doors out of this state are the author's, not the tool's."""
    paper = promoted_round.paper

    with pytest.raises(WorkingPending):
        revision.build(paper, _clean_edit(paper))
    with pytest.raises(BaselinePending):
        revision.baseline(paper)


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
