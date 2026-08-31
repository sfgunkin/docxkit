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
    _promote(paper)
    return paper


def _promote(paper):
    """Record the promote the way `promote` does: a copy of the batch in
    `build/redlines/`.

    A batch is only the round's proposal once it has been PUT ON the
    paper, and that copy is the only record of it — see
    `_verdict._proposal`. This fixture staged one and never promoted it,
    which is the state the whole entry is about: the verdict machinery
    read the unpromoted batch's absence from the manuscript as the
    author having rejected it."""
    import shutil
    paper.redline_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paper.batch,
                 paper.redline_dir / f"{paper.working.stem}_redline_"
                 f"20260831-120000-000000{paper.working.suffix}")


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
    _promote(paper)
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


def test_a_batch_that_was_never_PROMOTED_is_not_this_rounds_proposal(cycle):
    """The measured case, and the one the hash cannot catch.

    Aging_Well, 2026-08-28. `build/batch.docx` held a build made on the
    current baseline and deliberately NOT promoted — held back because
    it named a symbol the paper already used. The author's own Word
    round was ingested, two untracked repairs ran, and `revision
    baseline` printed

        | 2026-08-28 | batch | 1 ¶ changed, from 304 revisions (197 ins,
          107 del) | — | rejected in full, +2 authored → truth |

    Nothing had been rejected and there had been no batch to reject.
    The revisions are absent from the manuscript for the obvious reason,
    and absence reads as rejection — a batch REJECTED in full leaves
    exactly the same file. Content cannot tell them apart, so the record
    has to: `promote` copies the batch into `build/redlines/` and that
    copy is the only evidence it was ever put on.

    It is worth refusing rather than guessing because the row is
    pre-formatted for `revision/log.md` — the paper's permanent record,
    and the first thing the next session reads. It was hand-corrected
    three times."""
    for redline in cycle.redlines():              # un-promote it
        redline.unlink()
    _adjudicated(cycle, para(run("the old sentence"))
                 + para(run("an untouched paragraph")))

    result = verdict(cycle)

    assert result.batch is None
    assert result.outcome == "adjudicated (no batch to compare against)"
    assert "rejected" not in result.outcome


def test_another_ROUNDS_redline_does_not_certify_this_batch(cycle):
    """The folder is never pruned, so by round five it holds five
    redlines and none of them need be this one. Identity is the batch's
    own bytes: a redline of a different length is skipped on the size,
    and one that happens to match on length is still refused on the
    hash."""
    (promoted,) = cycle.redlines()
    stem, suffix = cycle.working.stem, cycle.working.suffix
    blob = promoted.read_bytes()
    def kept(stamp: str):
        return cycle.redline_dir / f"{stem}_redline_{stamp}{suffix}"

    kept("20260101-000000-000000").write_bytes(blob[:-64])   # another size
    kept("20260102-000000-000000").write_bytes(            # the same size
        blob[:-1] + bytes([blob[-1] ^ 0xFF]))
    promoted.unlink()
    _adjudicated(cycle, para(run("the old sentence"))
                 + para(run("an untouched paragraph")))

    result = verdict(cycle)

    assert result.batch is None
    assert result.outcome == "adjudicated (no batch to compare against)"


def test_a_batch_promoted_under_ANOTHER_name_still_counts(cycle):
    """The redline is stamped with the time it was promoted, so the
    check is on its CONTENT — a name comparison would answer no for
    every real round."""
    (only,) = cycle.redlines()
    only.rename(only.with_name(only.name.replace("120000", "235959")))

    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph")))

    assert verdict(cycle).outcome == "accepted in full"


def test_an_UNSTAMPED_batch_answers_cannot_tell(cycle):
    """The hand-authored vehicle carries no stamp. "Cannot tell" is the
    honest answer, and it is not the same as "nothing was proposed"."""
    from docxkit import guard
    guard.stamp_path(cycle.batch).unlink()
    _adjudicated(cycle, para(run("the new sentence")))

    result = verdict(cycle)

    assert result.batch is None


def test_text_that_ALREADY_EXISTS_elsewhere_does_not_fake_a_verdict(
        tmp_path):
    """The multiset asks "is this text in the document", and the
    question is "is it where the batch put it".

    Found by probing rather than by review. A batch proposing text that
    already appears elsewhere reported "1 of 2 kept as proposed" BOTH
    when the author accepted everything and when they rejected
    everything — a wrong verdict, written permanently into the paper's
    log. Table cells make this ordinary rather than exotic: "0.00" and
    a repeated country name are paragraphs too.
    """
    dup = "a sentence that appears twice"
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx",
                make_parts(para(run("old")) + para(run(dup))))
    paper = revision.init(root, src)
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(
        para(dele("old"), ins(dup)) + para(run(dup))))
    from docxkit import guard
    guard.stamp(paper.batch, base_sha256=guard.sha256(paper.prev))
    _promote(paper)
    # the author rejected: the manuscript still reads "old"
    write(paper.working, make_parts(para(run("old")) + para(run(dup))))

    result = verdict(paper)

    assert (result.kept, result.reverted) == (0, 1), result
    assert result.outcome == "rejected in full"


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


# ------------------------------------------------- the apparatus pass

def _linked(anchor: str, label: str) -> str:
    """A citation link and the bookmark it resolves to — the shape a
    linking pass adds, and the shape Word's Compare cannot serialize."""
    return (f'<w:bookmarkStart w:id="7" w:name="{anchor}"/>'
            f'<w:bookmarkEnd w:id="7"/>'
            f'<w:hyperlink w:anchor="{anchor}">{run(label)}</w:hyperlink>')


def test_a_pass_that_adds_LINKS_and_BOOKMARKS_is_named_as_one(tmp_path):
    """The one round no redline can show. Word's Compare will not
    serialize a bookmark insertion — `tracked.build` refuses the batch
    with `bookmarkStart 132 -> 142` — so the citation apparatus goes on
    untracked and in place, and until now the row it produced said
    "no visible change" and stopped there.
    """
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx",
                make_parts(para(run("As Lari (2023) shows, ..."))))
    paper = revision.init(root, src)
    # the pass: same words, now carrying an apparatus
    write(paper.working, make_parts(
        para(run("As "), _linked("Lari2023", "Lari (2023)"),
             run(" shows, ..."))))

    result = verdict(paper)

    assert result.changed == 0, "the pass changed no visible word"
    assert result.links == (1, 0) and result.bookmarks == (1, 0)
    assert result.apparatus_only
    assert result.outcome == "untracked apparatus pass (nothing to adjudicate)"
    assert "+1 link" in result.summary()
    assert "+1 bookmark" in result.summary()


def test_an_apparatus_pass_that_LOSES_a_link_says_so(tmp_path):
    """Word strips run-level hyperlinks out of every paragraph whose
    text the author rewrites, which is why the pass is re-run every
    round. A round that came back with fewer is worth a number."""
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx", make_parts(
        para(run("As "), _linked("Lari2023", "Lari (2023)"), run(" shows"))))
    paper = revision.init(root, src)
    write(paper.working, make_parts(para(run("As Lari (2023) shows"))))

    result = verdict(paper)

    assert result.links == (0, 1)
    assert "-1 link" in result.summary()


def test_a_link_SWAP_is_two_facts_and_not_a_net_zero(tmp_path):
    """`_links`' own docstring: "a total hides a swap". It hid one.

    A round that keeps one link, drops another to plain text and adds a
    third reported `links=0` and printed nothing about links at all,
    while `_link_changes` in the same module named the lost one
    correctly. That is the class this module was built for — Parental
    Style T4(3), 227 against 229.
    """
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx", make_parts(
        para(run("As "), _linked("Lari2023", "Lari (2023)"))
        + para(run("and "), _linked("Deaton2019", "Deaton (2019)"))))
    paper = revision.init(root, src)
    write(paper.working, make_parts(
        para(run("As "), _linked("Lari2023", "Lari (2023)"))
        + para(run("and Deaton (2019)"))
        + para(run("see "), _linked("Sen2020", "Sen (2020)"))))

    result = verdict(paper)

    assert result.links == (1, 1), "one added, one lost — not zero"
    assert "+1 link" in result.summary() and "-1 link" in result.summary()


def test_a_bookmark_REKEY_is_not_zero_change(tmp_path):
    """Same shape one layer down: re-keying a bibliography removes N
    anchors and adds N others, and `len(a) - len(b)` is zero for it. An
    apparatus pass that re-keys and changes no visible word has to be
    reported, because nothing else can see it."""
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx", make_parts(
        para(run("As "), _linked("Lari2023", "Lari (2023)"))))
    paper = revision.init(root, src)
    write(paper.working, make_parts(
        para(run("As "), _linked("lari_2023", "Lari (2023)"))))

    result = verdict(paper)

    assert result.bookmarks == (1, 1), "one anchor gone, one arrived"
    assert result.apparatus_only, "no visible word changed"


def test_the_apparatus_is_NOT_the_headline_when_words_moved_too(cycle):
    """`apparatus_only` is about a round that changed nothing visible.
    A batch that was adjudicated is still reported as adjudicated, with
    the apparatus counted beside it rather than instead of it."""
    _adjudicated(cycle, para(run("the new sentence"))
                 + para(run("an untouched paragraph")))

    result = verdict(cycle)

    assert not result.apparatus_only
    assert result.outcome == "accepted in full"


def test_baseline_logs_an_apparatus_pass_as_such(tmp_path):
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx", make_parts(para(run("As Lari (2023)."))))
    paper = revision.init(root, src)
    write(paper.working, make_parts(
        para(run("As "), _linked("Lari2023", "Lari (2023)."))))

    revision.baseline(paper, note="apparatus")

    row = next(ln for ln in (root / "revision" / "log.md")
               .read_text(encoding="utf-8").splitlines() if "apparatus" in ln)
    assert "untracked apparatus pass" in row
    assert "+1 link" in row and "+1 bookmark" in row


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



def test_a_paper_with_NO_log_file_still_baselines(cycle):
    """A paper migrated by hand has no `log.md`. Baselining is the act
    that matters and must not depend on the record existing — and this
    must not CREATE one either, because a log this tool scaffolds
    somewhere the author did not ask for it is a second place the
    history lives."""
    log = cycle.root / "revision" / "log.md"
    log.unlink()
    _adjudicated(cycle, para(run("the new sentence")))

    revision.baseline(cycle, note="R15")

    assert not log.exists(), "no log was asked for and none was invented"
    assert cycle.prev.read_bytes() == cycle.working.read_bytes()


def test_a_batch_heading_with_NO_TABLE_under_it_is_left_alone(cycle):
    """The heading is there and the table is not — an author who
    emptied it, or a scaffold half written. There is no row to append
    after, and guessing a position under a heading is the same mangling
    as guessing one in prose."""
    log = cycle.root / "revision" / "log.md"
    log.write_text("# Log\n\n## Batches\n\nNothing yet.\n", encoding="utf-8")
    _adjudicated(cycle, para(run("the new sentence")))

    revision.baseline(cycle, note="R15")

    assert log.read_text(encoding="utf-8") == \
        "# Log\n\n## Batches\n\nNothing yet.\n"


def test_a_batch_table_of_a_DIFFERENT_SHAPE_is_left_alone(cycle):
    """Five columns is the shape the row is built for. Appending it to a
    four-column table produces a row that renders wrong and reads as
    data — the failure mode is not a crash, it is a record that looks
    fine and says something else."""
    log = cycle.root / "revision" / "log.md"
    theirs = ("# Log\n\n## Batches\n\n"
              "| date | round | note |\n"
              "| --- | --- | --- |\n"
              "| 2026-08-01 | R14 | by hand |\n")
    log.write_text(theirs, encoding="utf-8")
    _adjudicated(cycle, para(run("the new sentence")))

    revision.baseline(cycle, note="R15")

    assert log.read_text(encoding="utf-8") == theirs
