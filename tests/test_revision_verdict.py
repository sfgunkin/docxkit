"""`baseline` records what the author decided, in the paper's own log.

The evidence stops existing at exactly this moment. After adjudication
the manuscript reads 0 pending whether every revision was accepted,
every one rejected, or half of each — and `baseline`'s next act is to
replace `prev.docx`, the only other copy of what it grew out of. The
verdict was reconstructible right up to that line and recorded nowhere:
`log.md`'s outcome column was filled in by hand, when it was filled in
at all.

The counting is per PARAGRAPH and not per revision, deliberately. A
revision's identity does not survive the author's Word session; the text
of the paragraph it proposed does.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run, write

from docxkit import package, revision
from docxkit.revision import verdict


def ins(text: str, rid: int = 90) -> str:
    return (f'<w:ins w:id="{rid}" w:author="Revision" '
            f'w:date="2026-08-07T00:00:00Z">{run(text)}</w:ins>')


def dele(text: str, rid: int = 91) -> str:
    return (f'<w:del w:id="{rid}" w:author="Revision" '
            f'w:date="2026-08-07T00:00:00Z"><w:r><w:delText>{text}'
            f"</w:delText></w:r></w:del>")


@pytest.fixture
def cycle(tmp_path):
    """A paper mid-cycle: a baseline, and a batch built ON that baseline.

    The batch proposes replacing "the old sentence" with "the new
    sentence" and leaves a second paragraph alone.
    """
    root = tmp_path / "HCW"
    root.mkdir()
    base = make_parts(para(run("the old sentence"))
                      + para(run("an untouched paragraph")))
    src = write(root / "HCW.docx", base)
    paper = revision.init(root, src, name="HCW")

    redline = make_parts(
        para(dele("the old sentence"), ins("the new sentence"))
        + para(run("an untouched paragraph")))
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, redline)
    # the stamp is what ties a batch to the baseline it was built on
    from docxkit import guard
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    return paper


def _adjudicated(paper, body):
    """The author's hand-back: no markup left, whatever they decided."""
    write(paper.working, make_parts(body))


# -------------------------------------------------------------- verdict

def test_accepting_everything_reads_as_accepted_in_full(cycle):
    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph")))

    result = verdict(cycle)

    assert result.kept == 1 and result.reverted == 0
    assert result.outcome == "accepted in full"


def test_rejecting_everything_reads_as_rejected_in_full(cycle):
    _adjudicated(cycle, para(run("the old sentence"))
                 + para(run("an untouched paragraph")))

    result = verdict(cycle)

    assert result.kept == 0 and result.reverted == 1
    assert result.outcome == "rejected in full"


def test_accepting_AND_editing_is_still_accepted_in_full(cycle):
    """The ordinary shape of a round: every revision taken, plus a
    sentence of the author's own. Reporting that as "partly
    adjudicated" would be wrong about the part that matters."""
    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph"))
                 + para(run("and a thought of my own")))

    result = verdict(cycle)

    assert result.kept == 1 and result.reverted == 0 and result.authored == 1
    assert result.outcome == "accepted in full, +1 authored"


def test_a_SPLIT_verdict_is_counted_both_ways(tmp_path):
    root = tmp_path / "P"
    root.mkdir()
    base = make_parts(para(run("first old")) + para(run("second old")))
    src = write(root / "P.docx", base)
    paper = revision.init(root, src)
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(
        para(dele("first old"), ins("first new"))
        + para(dele("second old"), ins("second new"))))
    from docxkit import guard
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    _adjudicated(paper, para(run("first new")) + para(run("second old")))

    result = verdict(paper)

    assert (result.kept, result.reverted) == (1, 1)
    assert result.outcome == "1 of 2 kept as proposed"


def test_a_STALE_batch_is_not_counted_as_this_rounds_proposal(cycle):
    """The verdict is only as good as its link to the proposal. A
    `batch.docx` left over from an earlier round is the exact file the
    stale-batch guards exist for, and counting one round's verdict
    against another's proposal would be a wrong answer written
    permanently into the paper's record."""
    other = cycle.build_dir / "other.docx"
    write(other, make_parts(para(run("a different baseline"))))
    from docxkit import guard
    guard.stamp(cycle.batch,                      # built on something else
                base_sha256=guard.sha256(other))
    _adjudicated(cycle, para(run("the new sentence")))

    result = verdict(cycle)

    assert result.batch is None
    assert result.outcome == "adjudicated (no batch to compare against)"


def test_an_UNSTAMPED_batch_answers_cannot_tell(cycle):
    """The hand-authored vehicle carries no stamp. "Cannot tell" is the
    honest answer, and it is not the same as "nothing was proposed"."""
    from docxkit import guard
    guard.stamp_path(cycle.batch).unlink()
    _adjudicated(cycle, para(run("the new sentence")))

    result = verdict(cycle)

    assert result.batch is None


def test_the_verdict_reports_what_MOVED_as_well(cycle):
    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph")))

    result = verdict(cycle)

    assert result.changed == 1, "one paragraph's text differs from the truth"
    assert "1 ¶ changed" in result.summary()
    assert "from 2 revisions (1 ins, 1 del)" in result.summary()


def test_the_verdict_writes_NOTHING(cycle):
    _adjudicated(cycle, para(run("the new sentence")))
    before = {p: p.stat().st_mtime_ns for p in cycle.root.rglob("*")
              if p.is_file()}

    verdict(cycle)

    assert {p: p.stat().st_mtime_ns for p in cycle.root.rglob("*")
            if p.is_file()} == before


# ------------------------------------------------------------ the record

def test_baseline_files_the_round_in_the_log(cycle):
    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph")))

    revision.baseline(cycle, note="R15")

    log = (cycle.root / "revision" / "log.md").read_text(encoding="utf-8")
    row = [ln for ln in log.splitlines() if "R15" in ln]
    assert len(row) == 1, log
    assert "accepted in full → truth" in row[0]
    assert "1 ¶ changed" in row[0]


def test_the_row_lands_IN_the_table_and_not_at_the_end_of_the_file(cycle):
    """Three of the nine papers carry prose after their batch table. A
    line appended to the file would have been read as part of it."""
    log = cycle.root / "revision" / "log.md"
    log.write_text(log.read_text(encoding="utf-8")
                   + "\n## Notes\n\nA closing note, not a table row.\n",
                   encoding="utf-8")
    _adjudicated(cycle, para(run("the new sentence")))

    revision.baseline(cycle, note="R15")

    lines = log.read_text(encoding="utf-8").splitlines()
    row = next(i for i, ln in enumerate(lines) if "R15" in ln)
    notes = next(i for i, ln in enumerate(lines) if ln == "## Notes")
    assert row < notes, "the row landed after the prose"
    assert lines[row - 1].startswith("|"), "the row is not in the table"


def test_a_log_with_NO_batch_table_is_left_alone(cycle):
    """A log this tool did not scaffold is the author's document, and
    guessing where a row belongs in it is how a record gets mangled."""
    log = cycle.root / "revision" / "log.md"
    log.write_text("# My own notes\n\nNo table here.\n", encoding="utf-8")
    _adjudicated(cycle, para(run("the new sentence")))

    revision.baseline(cycle, note="R15")

    assert log.read_text(encoding="utf-8") == \
        "# My own notes\n\nNo table here.\n"


def test_the_verdict_is_computed_BEFORE_prev_is_replaced(cycle):
    """The order is the whole trick: `baseline`'s next act destroys the
    comparison. Computed after the copy, every round would report
    "no visible change"."""
    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph")))

    revision.baseline(cycle, note="R15")

    row = next(ln for ln in (cycle.root / "revision" / "log.md")
               .read_text(encoding="utf-8").splitlines() if "R15" in ln)
    assert "no visible change" not in row, row
    assert "1 ¶ changed" in row


def test_no_log_leaves_the_record_untouched(cycle):
    log = cycle.root / "revision" / "log.md"
    before = log.read_text(encoding="utf-8")
    _adjudicated(cycle, para(run("the new sentence")))

    revision.baseline(cycle, log=False)

    assert log.read_text(encoding="utf-8") == before


def test_baseline_still_records_the_truth_when_the_log_cannot_take_a_row(
        cycle):
    """The row is a record, not a gate: a log that cannot take it must
    not stop the cycle from closing."""
    (cycle.root / "revision" / "log.md").unlink()
    _adjudicated(cycle, para(run("the new sentence")))

    written = revision.baseline(cycle)

    assert written == cycle.prev
    assert package.read_parts(cycle.prev) == package.read_parts(cycle.working)


def test_the_CLI_prints_the_row_it_wrote(monkeypatch, cycle, capsys):
    from test_cli import run_cli
    _adjudicated(cycle, para(run("the new sentence")))

    code, _ = run_cli(monkeypatch, "revision", "baseline",
                      "--paper", str(cycle.root), "--note", "R15")
    out = capsys.readouterr().out

    assert code == 0
    assert "logged:" in out and "R15" in out
    assert "accepted in full" in out
