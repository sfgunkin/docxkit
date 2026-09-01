r"""`revision.status` — where a paper is, decided apart from its printing.

The decisions lived in `cli.cmd_revision_status` until 2026-09-01. That
is where the locked-file drift defect was fixed (BACKLOG S4, `39fe472`),
and it could only be tested through `argv`, with the exit code as the
one contract a script could read — every question about the protocol's
state asked by running a command and grepping its page.

So this file asks them directly, which is the whole point of the move:
`StatusReport` carries the two answers and `exit_code` derives from
them, and the CLI's job is to print. `tests/test_cli_revision.py` still
holds the RENDERING — the two files together are the contract, and
neither is redundant: 154 of its tests passed unchanged across the move,
which is what said the move was behaviour-preserving.
"""
from __future__ import annotations

from conftest import make_parts, para, run, write

from docxkit import package, revision

BODY = para(run("The index rose to 0.35 in 2024."))
INS = ('<w:p><w:ins w:id="7" w:author="Agent" '
       'w:date="2026-01-01T00:00:00Z">'
       "<w:r><w:t>proposed</w:t></w:r></w:ins></w:p>")


def _paper(tmp_path, body: str = BODY):
    """A migrated project whose manuscript holds `body`."""
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "src.docx", make_parts(body))
    return revision.init(tmp_path / "proj", src, name="Test Paper",
                         author="Agent", attic=tmp_path / "attic")


# ------------------------------------------------------ the two answers


def test_a_settled_paper_on_its_own_baseline_is_current(tmp_path):
    paper = _paper(tmp_path)

    report = revision.status(paper)

    assert report.working.is_truth
    assert report.drift_checked and report.stale == ()
    assert report.exit_code == 0


def test_a_pending_proposal_is_not_truth_and_exits_1(tmp_path):
    paper = _paper(tmp_path, BODY + INS)

    report = revision.status(paper)

    assert not report.working.is_truth
    assert report.working.pending == 1
    assert report.exit_code == 1


def test_a_baseline_that_no_longer_matches_is_STALE(tmp_path):
    """Both files count 0 pending and they are not the same paper —
    the state `state()` alone cannot see, and the reason `drift` exists."""
    paper = _paper(tmp_path)
    write(paper.working, make_parts(para(run("The author edited this."))))

    report = revision.status(paper)

    assert report.working.is_truth, "the live file carries no markup"
    assert report.drift_checked
    assert "word/document.xml" in report.stale
    assert report.exit_code == 4


def test_with_NO_baseline_there_is_nothing_to_compare(tmp_path):
    paper = _paper(tmp_path)
    paper.prev.unlink()

    report = revision.status(paper)

    assert report.prev is None
    assert report.exit_code == 0, "settled, and no baseline to be stale"


def test_drift_is_not_asked_of_a_PENDING_file(tmp_path):
    """While a proposal is open the two files are SUPPOSED to differ,
    and saying so every time is how a warning stops being read."""
    paper = _paper(tmp_path, BODY + INS)

    report = revision.status(paper)

    assert report.drift_checked, "the file was readable; the check ran"
    assert report.stale == (), "and had nothing to say about a proposal"
    assert report.exit_code == 1


# -------------------------------------------------------- under a lock


def test_a_LOCKED_file_names_the_check_that_could_not_run(monkeypatch,
                                                          tmp_path):
    """Measured on Aging_Well, 2026-08-30: the same pair minutes apart
    answered "both sides settled" locked and "baseline STALE: word/ (8
    parts)" closed. `drift` reads the SAVED bytes and cannot run at all
    while Word holds the file, and its absence used to be silent — the
    locked output had the exact shape of a healthy, current baseline."""
    paper = _paper(tmp_path)
    write(paper.working, make_parts(para(run("The author edited this."))))
    monkeypatch.setattr(package, "is_locked",
                        lambda p: str(p) == str(paper.working))

    report = revision.status(paper)

    assert report.working.from_snapshot, "the counts came from a copy"
    assert not report.drift_checked
    assert report.stale == (), "unasked is not the same as clean"
    assert report.exit_code == 1


def test_an_unchecked_drift_can_never_read_as_exit_0(tmp_path):
    """The rule the exit code exists for. A run that could not ask the
    second question is not a run that answered it — and 1 is what the
    lock produced before the check was named, so nothing gating on this
    command changes its mind."""
    paper = _paper(tmp_path)
    settled = revision.status(paper)
    assert settled.exit_code == 0

    unchecked = revision.StatusReport(working=settled.working,
                                      prev=settled.prev,
                                      drift_checked=False)

    assert unchecked.exit_code == 1


# ------------------------------------------------- the contract itself


def test_the_exit_codes_are_the_ones_scripts_already_read():
    """Pinned as a table, because they are an interface: a paper's
    protocol scripts branch on these, and a slipped code is silent until
    one misbehaves a round later. 0 settled and current, 1 pending or
    unchecked, 4 a stale baseline."""
    from docxkit.revision import State, StatusReport

    truth = State(path=None, by_part={}, by_author={})       # type: ignore[arg-type]
    proposal = State(path=None, by_part={"word/document.xml": 1},  # type: ignore[arg-type]
                     by_author={})

    cases = {
        (True, True, ()): 0,            # settled, checked, current
        (False, True, ()): 1,           # a proposal is pending
        (True, False, ()): 1,           # the check could not run
        (True, True, ("word/document.xml",)): 4,            # stale
        (False, True, ("word/document.xml",)): 4,           # stale wins
    }
    for (settled, checked, stale), expected in cases.items():
        report = StatusReport(working=truth if settled else proposal,
                              prev=truth, drift_checked=checked,
                              stale=stale)
        assert report.exit_code == expected, (settled, checked, stale)
