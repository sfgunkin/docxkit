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
from conftest import make_parts, para, revision_round, run, write

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
    """A paper mid-cycle: a baseline, a batch built ON that baseline,
    and the batch PROMOTED — `conftest.revision_round` with this file's
    one-edit round, and the real `promote`.

    The batch proposes replacing "the old sentence" with "the new
    sentence" and leaves a second paragraph alone.

    A batch is only the round's proposal once it has been PUT ON the
    paper, and the redline copy `promote` keeps is the only record of
    it — see `_verdict._proposal`. Until 2026-08-31 this fixture staged
    a batch and never promoted it, which is the state the whole entry
    is about: the verdict machinery read the unpromoted batch's absence
    from the manuscript as the author having rejected it. It then faked
    the promote by copying a redline by hand; since 2026-09-11 it is
    the shared workflow-state machinery and the promote is real.
    """
    made = revision_round(
        tmp_path, name="HCW",
        baseline=("the old sentence", "an untouched paragraph"),
        proposed=("the new sentence", "an untouched paragraph"))
    revision.promote(made.paper)
    return made.paper


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


def test_a_SPLIT_verdict_is_counted_both_ways(partly_round):
    result = verdict(partly_round.paper)

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
    only.rename(only.with_name(f"{cycle.working.stem}_redline_"
                               f"20261231-235959-000000{only.suffix}"))

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
    made = revision_round(tmp_path, name="P", baseline=("old", dup),
                          proposed=(dup, dup))
    revision.promote(made.paper)
    made.hand_back("old", dup)     # rejected: the manuscript still reads "old"

    result = verdict(made.paper)

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

    assert written.prev == cycle.prev
    assert package.read_parts(cycle.prev) == package.read_parts(cycle.working)
    assert written.verdict is not None, "the verdict was still taken"
    assert written.row is None, "and there was no table to write it into"


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


# --- the survivors of 2026-09-14 ------------------------------------------
#
# The mutation sweep of `_verdict.py` left 94 real survivors with one
# cause: every case above is ONE round of one shape. None had no previous
# truth, moved two links, hashed a redline of another size, or kept its
# batch table above another table, so the defaults, the plurals, the
# size check and the walk down the table were free to say anything.


def _paper(tmp_path, body: str):
    root = tmp_path / "P"
    root.mkdir()
    return revision.init(root, write(root / "P.docx", make_parts(body)))


def test_a_paper_with_NO_PREVIOUS_TRUTH_reports_nothing_and_decides_nothing(
        tmp_path):
    """The first cycle of a paper migrated by hand has no `prev.docx` and
    nothing to compare against. Every count is zero, field by field,
    because each one is also a dataclass default a caller leans on: a
    default of one writes a revision nobody proposed into the log."""
    paper = _paper(tmp_path, para(run("The paper.")))
    paper.prev.unlink()

    result = verdict(paper)

    assert (result.changed, result.added, result.removed) == (0, 0, 0)
    assert (result.proposed, result.kept, result.reverted,
            result.authored) == ((0, 0), 0, 0, 0)
    assert (result.links, result.bookmarks) == ((0, 0), (0, 0))
    assert result.batch is None
    assert result.summary() == "no visible change"


def test_a_round_with_NO_BATCH_counts_what_moved_and_nothing_else(tmp_path):
    """An author's own Word round: text moved and no batch was put on the
    paper. The row says exactly that, and nothing more: a clause added or
    removed printed at zero, or a revision count, would be a claim about
    a batch that does not exist."""
    paper = _paper(tmp_path, para(run("the old sentence"))
                   + para(run("an untouched paragraph")))
    write(paper.working, make_parts(para(run("the new sentence"))
                                    + para(run("an untouched paragraph"))))

    result = verdict(paper)

    assert result.batch is None
    assert (result.proposed, result.kept, result.reverted,
            result.authored) == ((0, 0), 0, 0, 0)
    assert result.summary() == "1 ¶ changed", result.summary()
    assert result.outcome == "adjudicated (no batch to compare against)"


def test_the_summary_gives_every_count_its_own_PLURAL():
    """Built directly, every count at once, and each apparatus count at
    one AND at two, so a plural that tests the wrong number cannot print
    the same cell. The log's `changes` column is this string, and no
    round above moved two of anything."""
    result = revision.Verdict(changed=2, added=1, removed=3,
                              proposed=(4, 0), links=(1, 2),
                              bookmarks=(2, 1))

    assert result.summary() == (
        "2 ¶ changed, 1 added, 3 removed, "
        "from 4 revisions (4 ins, 0 del), "
        "+1 link, -2 links, +2 bookmarks, -1 bookmark")


def test_a_pass_that_adds_only_BOOKMARKS_is_an_apparatus_pass_too(tmp_path):
    """Links OR bookmarks. Every apparatus case above moves both, since a
    citation link arrives with the anchor it resolves to; a pass that
    anchors cross-references before anything links to them moves only
    the bookmarks, which Compare cannot serialize either."""
    paper = _paper(tmp_path, para(run("Table 3 shows the split.")))
    write(paper.working, make_parts(para(
        '<w:bookmarkStart w:id="7" w:name="Table3"/>',
        run("Table 3 shows the split."), '<w:bookmarkEnd w:id="7"/>')))

    result = verdict(paper)

    assert (result.links, result.bookmarks) == ((0, 0), (1, 0))
    assert result.apparatus_only
    assert result.outcome == "untracked apparatus pass (nothing to adjudicate)"


def test_redlines_of_ANOTHER_SIZE_are_passed_over_UNHASHED(monkeypatch,
                                                          tmp_path):
    """"Sizes first, hashes only for a file that could match." A paper
    keeps a redline per round and each is the whole manuscript, so a
    hash of every one is a cost every verdict pays. A smaller and a
    larger one sort ahead of the real copy here: the search goes past
    both, hashing neither, and finds it."""
    from docxkit import guard
    from docxkit.revision._verdict import _promoted

    made = revision_round(tmp_path)
    batch, folder = made.paper.batch, made.paper.redline_dir
    folder.mkdir(parents=True, exist_ok=True)
    stem, size = made.paper.working.stem, batch.stat().st_size
    (folder / f"{stem}_redline_a.docx").write_bytes(b"x" * (size - 1))
    (folder / f"{stem}_redline_b.docx").write_bytes(b"x" * (size + 1))
    (folder / f"{stem}_redline_c.docx").write_bytes(batch.read_bytes())
    hashed: list[str] = []
    real = guard.sha256

    def sha256(path):
        hashed.append(path.name)
        return real(path)

    monkeypatch.setattr(guard, "sha256", sha256)

    assert _promoted(made.paper, batch)
    assert hashed == ["batch.docx", f"{stem}_redline_c.docx"]


def test_a_redline_of_the_SAME_SIZE_counts_only_if_its_hash_is_EQUAL(
        monkeypatch, tmp_path):
    """Digests are hex strings, and a comparison that orders them takes a
    redline whose digest merely sorts first for a copy of the batch: a
    batch never put on the paper, reported as promoted."""
    from docxkit import guard
    from docxkit.revision._verdict import _promoted

    made = revision_round(tmp_path)
    batch, folder = made.paper.batch, made.paper.redline_dir
    folder.mkdir(parents=True, exist_ok=True)
    decoy = folder / f"{made.paper.working.stem}_redline_a.docx"
    decoy.write_bytes(b"x" * batch.stat().st_size)
    monkeypatch.setattr(guard, "sha256", lambda path: (
        "f" * 64 if path == batch else "0" * 64))

    assert not _promoted(made.paper, batch)


def test_a_proposal_needs_a_PREVIOUS_TRUTH_on_its_own_account(tmp_path):
    """`verdict` returns before asking when `prev.docx` is missing, and
    `_proposal` does not lean on that: with no truth for a batch to have
    been built on it identifies nothing, rather than hashing a file that
    is not there."""
    from docxkit.revision._verdict import _proposal

    made = revision_round(tmp_path)
    made.paper.prev.unlink()

    assert _proposal(made.paper) is None


HEADER = "| date | batch | changes | gates | outcome |"
RULE = "| --- | --- | --- | --- | --- |"
R13 = "| 2026-08-01 | R13 | 2 ¶ changed | — | accepted in full → truth |"
R14 = "| 2026-08-08 | R14 | 1 ¶ changed | — | accepted in full → truth |"
ROUND = revision.Verdict(changed=1, added=0, removed=0)


def _paper_with_log(tmp_path, lines: list[str]):
    paper = _paper(tmp_path, para(run("The paper.")))
    log = paper.config.parent / "log.md"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return paper, log


def test_the_row_follows_the_LAST_row_of_its_table_not_a_later_table(
        tmp_path):
    """A log carries more than one table, and every `|` line after the
    heading looks like a row: DSI's holds fourteen more five-column
    tables under later headings (measured 2026-09-14). The batch table
    is the run of rows CONTIGUOUS with its header: the header is read
    from that run's first row, and the new row goes after its last, not
    after a table further down.

    Two dated rows put the last one on an odd line, where `last | 1`
    and `last ^ 1` are not `last + 1`; on an even line they are."""
    theirs = ["# Log", "", "## Batches", "", HEADER, RULE, R13, R14, "",
              "## Sources", "", "| file | from | note |",
              "| --- | --- | --- |", "| data.xlsx | the author | v3 |"]
    paper, log = _paper_with_log(tmp_path, theirs)

    row = revision.log_batch(paper, ROUND, note="R15")

    at = theirs.index(R14) + 1
    assert at % 2 == 0, "the last row sits on an odd line"
    assert row is not None
    assert log.read_text(encoding="utf-8").splitlines() == \
        [*theirs[:at], row.rstrip("\n"), *theirs[at:]]


def test_a_log_LONGER_than_256_lines_still_finds_the_end_of_its_table(
        tmp_path):
    """Line numbers are ints, and CPython keeps a single object only for
    the ints up to 256. Every log above is a dozen lines, where two line
    numbers compared by identity agree with the same two compared by
    value. Aging_Well's log keeps its batch table below line 3,190
    (measured 2026-09-14), and there they do not."""
    theirs = (["# Log", ""]
              + [f"- note {i} from an earlier round" for i in range(300)]
              + ["", "## Batches", "", HEADER, RULE, R14, "", "Prose."])
    paper, log = _paper_with_log(tmp_path, theirs)

    row = revision.log_batch(paper, ROUND, note="R15")

    at = theirs.index(R14) + 1
    assert at > 257
    assert row is not None
    assert log.read_text(encoding="utf-8").splitlines() == \
        [*theirs[:at], row.rstrip("\n"), *theirs[at:]]


def test_a_table_of_only_its_HEADER_takes_the_row_under_it(tmp_path):
    """The header is the FIRST row under the heading, and nothing else
    is read before it. A header with nothing under it yet is still the
    table this row is shaped for, and a second row that is not there is
    not asked for."""
    theirs = ["# Log", "", "## Batches", "", HEADER, "", "Nothing yet."]
    paper, log = _paper_with_log(tmp_path, theirs)

    row = revision.log_batch(paper, ROUND, note="R15")

    assert row is not None
    assert log.read_text(encoding="utf-8").splitlines() == \
        [*theirs[:5], row.rstrip("\n"), *theirs[5:]]


def test_a_batch_table_WIDER_than_five_columns_is_left_alone(tmp_path):
    """The shape check is exact. A six-column table, a paper that added a
    reviewer column, takes a five-cell row as badly as a four-column one
    does, and the case above asks only about a narrower table."""
    theirs = ["# Log", "", "## Batches", "",
              "| date | batch | changes | gates | outcome | reviewer |",
              "| --- | --- | --- | --- | --- | --- |",
              "| 2026-08-08 | R14 | 1 ¶ changed | — | accepted | R2 |"]
    paper, log = _paper_with_log(tmp_path, theirs)

    assert revision.log_batch(paper, ROUND, note="R15") is None
    assert log.read_text(encoding="utf-8").splitlines() == theirs


def test_a_rule_WITHOUT_END_PIPES_keeps_the_new_row_below_it(tmp_path):
    """GitHub's Markdown makes a row's end pipes optional, so
    `--- | ---` is a rule. Read as the end of the table it put the new
    row between the header and the rule, and the table stopped being a
    table (BACKLOG, 2026-09-14)."""
    rule = "--- | --- | --- | --- | ---"
    theirs = ["# Log", "", "## Batches", "", HEADER, rule, R14, "", "Prose."]
    paper, log = _paper_with_log(tmp_path, theirs)

    row = revision.log_batch(paper, ROUND, note="R15")

    at = theirs.index(R14) + 1
    assert row is not None
    assert log.read_text(encoding="utf-8").splitlines() == \
        [*theirs[:at], row.rstrip("\n"), *theirs[at:]]


def test_a_body_row_WITHOUT_END_PIPES_is_still_a_row_of_the_table(tmp_path):
    """The same reading one row down: the new row landed above it, out of
    date order."""
    bare = "2026-08-08 | R14 | 1 ¶ changed | — | accepted in full → truth"
    theirs = ["# Log", "", "## Batches", "", HEADER, RULE, R13, bare, "",
              "Prose."]
    paper, log = _paper_with_log(tmp_path, theirs)

    row = revision.log_batch(paper, ROUND, note="R15")

    at = theirs.index(bare) + 1
    assert row is not None
    assert log.read_text(encoding="utf-8").splitlines() == \
        [*theirs[:at], row.rstrip("\n"), *theirs[at:]]


def test_a_heading_with_no_table_does_not_borrow_a_LATER_SECTION_s(tmp_path):
    """The table is the one under `## Batches`. With nothing under the
    heading, a five-column table in a later section took the row, under
    another heading, as though it were a timing (BACKLOG, 2026-09-14)."""
    theirs = ["# Log", "", "## Batches", "", "Nothing yet.", "",
              "## Timings", "", "| step | run | cost | where | note |",
              RULE, "| build | r1 | 20s | Word | slow |"]
    paper, log = _paper_with_log(tmp_path, theirs)

    assert revision.log_batch(paper, ROUND, note="R15") is None
    assert log.read_text(encoding="utf-8").splitlines() == theirs
