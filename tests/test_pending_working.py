r"""`build` refused a pending BASELINE and not a pending WORKING file.

`_build.build` reads the baseline's revision counts and raises
`BaselinePending`, for a reason that is exactly right: Word's Compare
rebuilds the redline from ACCEPTED content, so a pending baseline's
revisions are flattened into plain text and can never be rejected.

The same harm arrives far more often from the other side. Promote a
batch, have the author not adjudicate it yet, pick up the next protocol:
`prev` is clean, `working` carries the proposal. What happens then
depends on which file the caller stages as the clean edit — built from
`prev`, the pending batch drops out of the redline entirely; built from
`working`, Compare is handed revision marks and flattens the batch in as
accepted, unreviewable text. Met on Aging_Well, 31 August, R75 promoted
and awaiting a verdict.

**And `build` was not silent about it — it said the wrong thing.**
Measured 2026-09-02, before the fix: the `drift` check fires on this
state too (a pending working file cannot match a clean baseline) and
raised `StaleBatch`, whose advice is to run `revision baseline` — which
REFUSES a file carrying a proposal. The reader was sent into a loop.
That is why this check goes BEFORE the drift check and carries its own
class, and why the test below pins the ORDER.
"""
from __future__ import annotations

import pytest
from conftest import dele, ins, make_parts, para, run, write

from docxkit import revision
from docxkit.errors import BaselinePending, StaleBatch, WorkingPending


@pytest.fixture
def paper(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    src = write(proj / "manuscript.docx",
                make_parts(para(run("The paper as it stands."))))
    return revision.init(proj, src, name="Test Paper", author="Agent",
                         attic=tmp_path / "attic")


def promoted_batch(paper) -> None:
    """The state after `promote`: `working` is the redline, `prev` the
    clean pre-batch truth."""
    write(paper.working, make_parts(
        para(run("The paper "), ins("as improved "), run("as it stands."))))


def clean_edit(paper):
    edit = paper.build_dir / "clean.docx"
    write(edit, make_parts(para(run("A new proposal."))))
    return edit


# ------------------------------------------------------------ the refusal


def test_a_promoted_batch_awaiting_a_verdict_stops_the_next_build(paper):
    promoted_batch(paper)

    with pytest.raises(WorkingPending) as exc:
        revision.build(paper, clean_edit(paper))

    said = str(exc.value)
    assert "1 insertion(s)" in said
    assert paper.working.name in said
    assert "not adjudicated" in said


def test_the_message_names_BOTH_ways_it_goes_wrong(paper):
    """Which harm you get depends on which file was staged as the clean
    edit, and a reader cannot tell from a message that names one."""
    promoted_batch(paper)

    with pytest.raises(WorkingPending) as exc:
        revision.build(paper, clean_edit(paper))

    said = str(exc.value)
    assert "drops it from the redline" in said
    assert "flattens it in as accepted" in said
    assert paper.prev.name in said and paper.working.name in said


def test_a_DELETION_pending_counts_too(paper):
    write(paper.working, make_parts(
        para(run("The paper "), dele("as it was "), run("stands."))))

    with pytest.raises(WorkingPending, match="1 deletion"):
        revision.build(paper, clean_edit(paper))


def test_it_comes_BEFORE_the_staleness_check(paper):
    """The order is the fix. `drift` fires on this state too — a pending
    working file cannot match a clean baseline — and its advice is to
    re-baseline, which `baseline` then refuses for carrying a proposal.
    Reverting the order puts the reader back in that loop."""
    promoted_batch(paper)

    with pytest.raises(WorkingPending):
        revision.build(paper, clean_edit(paper))

    # …and the loop it replaces is real: the advice StaleBatch gives is
    # a step that refuses this very file.
    with pytest.raises(BaselinePending):
        revision.baseline(paper)


def test_the_escape_is_its_OWN_switch(paper):
    """Not a widening of `allow_pending_baseline`. The two states want
    opposite advice, and one flag for both would be reached for over the
    commoner refusal and silence the rarer one."""
    promoted_batch(paper)

    # Past the working check, into the staleness one — which is the next
    # thing that is true about this pair, and says so.
    with pytest.raises(StaleBatch):
        revision.build(paper, clean_edit(paper), allow_pending_working=True)

    # and the baseline switch does NOT let it through
    with pytest.raises(WorkingPending):
        revision.build(paper, clean_edit(paper), allow_pending_baseline=True)


# ------------------------------------------------------ what it lets past


def test_a_clean_working_file_REACHES_the_comparison(paper):
    """The ordinary round. A refusal that fires on the common case is
    not a gate, and asserting "no WorkingPending" alone would pass on a
    build that died two lines earlier for some other reason."""
    seen: list[tuple[object, object, object]] = []

    def fake_build(original, revised, out, *a, **k):
        seen.append((original, revised, out))
        raise RuntimeError("Word stub")

    import docxkit.tracked
    original_build = docxkit.tracked.build
    docxkit.tracked.build = fake_build
    try:
        with pytest.raises(RuntimeError, match="Word stub"):
            revision.build(paper, clean_edit(paper))
    finally:
        docxkit.tracked.build = original_build

    assert seen, "the build never reached the comparison"


def test_a_missing_working_file_answers_zero_rather_than_raising(paper):
    """`init` adopts the manuscript in place, so `paper.working` is the
    author's own file — and a caller may point a Paper at a project
    whose manuscript has been moved. A refusal about revision counts
    that cannot be read is not the refusal to give them; reading them
    anyway raises `FileNotFoundError` from inside a gate, which is the
    shape this whole module exists to avoid."""
    paper.working.unlink()

    with pytest.raises(Exception) as exc:
        revision.build(paper, clean_edit(paper))

    assert not isinstance(exc.value, WorkingPending)
    assert not isinstance(exc.value, FileNotFoundError)


def test_the_exit_code_is_its_own(paper):
    """A script tells WHICH refusal it hit from the number, not by
    parsing English — which is why every ProtocolError carries one."""
    assert WorkingPending.exit_code not in {
        BaselinePending.exit_code, StaleBatch.exit_code}


def test_the_CLI_carries_the_switch(paper, monkeypatch):
    from docxkit.cli import build_parser

    monkeypatch.setattr(
        "sys.argv",
        ["docxkit", "revision", "build", "x.docx", "--allow-pending-working"])
    args = build_parser().parse_args(
        ["revision", "build", "x.docx", "--allow-pending-working"])

    assert args.allow_pending_working is True
