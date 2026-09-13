"""`tools/mutation_session.py` — the figure is about ONE tree.

The session's own docstring lists what has to be right or the run
produces a plausible wrong number. This holds the sixth of them, added
after `tracked.py` came back at 28.9 % on 2026-08-19 — a module standing
at 4.9 %, with every survivor cluster a multiple of eleven.

The cause was the restore between chunks. cosmic-ray leaves its mutation
behind when a run is terminated, so each chunk puts the module back
first — and it put back the LIVE file. An edit made while the sweep ran
was therefore picked up half way through: the plan in the session
describes one source, the next chunk mutates another, and the harness in
the worktree is still the copy taken at startup. Nothing failed, and the
number was nonsense.

So a session snapshots the module and its harness when it is planned,
and every chunk restores from that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed: the path insert above
# is how its scripts reach each other, and how they are reached here.
import mutation_session as ms  # noqa: E402  # pyright: ignore[reportMissingImports]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A miniature ROOT: one module, one test file, and a snapshot dir."""
    (tmp_path / "src" / "docxkit").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    module = tmp_path / "src" / "docxkit" / "thing.py"
    module.write_text("def f(a, b):\n    return a - b\n", encoding="utf-8")
    test = tmp_path / "tests" / "test_thing.py"
    test.write_text("def test_f():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(ms, "ROOT", tmp_path)
    return tmp_path, Path("src/docxkit/thing.py"), ["tests/test_thing.py"]


def test_the_snapshot_holds_the_module_AND_its_harness(tree):
    """Both, because both decide the figure: the module is what the
    plan's offsets are about, and the harness is what "killed" means.
    `stale_figures` calls a run void when either has moved, and this is
    the same rule enforced while it runs rather than after."""
    root, module, tests = tree
    snapshot = root / ".mutation-thing.pristine"

    ms.take_snapshot(snapshot, module, tests)

    assert (snapshot / module).read_text(encoding="utf-8") == \
        (root / module).read_text(encoding="utf-8")
    assert (snapshot / tests[0]).exists()


def test_an_edit_made_WHILE_the_sweep_runs_is_seen(tree):
    """The defect this file exists for, from the detection side: the
    tree moving is what has to be noticed. Bytes decide it — a file
    saved unchanged is not a change, and `copy2` keeps the mtime, so
    timestamps would report both the wrong way round."""
    root, module, tests = tree
    snapshot = root / ".mutation-thing.pristine"
    ms.take_snapshot(snapshot, module, tests)

    assert ms.moved_since(snapshot, module, tests) == []

    (root / module).write_text("def f(a, b):\n    return a + b\n",
                               encoding="utf-8")

    assert ms.moved_since(snapshot, module, tests) == [str(module)]


def test_a_HARNESS_that_moved_is_named_too(tree):
    """A test added mid-run kills mutants the plan has already graded as
    survivors, and the figure then mixes two harnesses. It does not
    invalidate the plan the way a source edit does — hence a note rather
    than a refusal — but it is not the same measurement either."""
    root, module, tests = tree
    snapshot = root / ".mutation-thing.pristine"
    ms.take_snapshot(snapshot, module, tests)

    (root / tests[0]).write_text("def test_f():\n    assert 1 == 1\n",
                                 encoding="utf-8")

    assert ms.moved_since(snapshot, module, tests) == [tests[0]]


def test_a_file_the_snapshot_never_took_counts_as_MOVED(tree):
    """A harness that grew a file, or a snapshot half written by an
    interrupted start. Absent is not the same as unchanged, and reading
    it as unchanged is how the check would pass over the one file it
    cannot vouch for."""
    root, module, tests = tree
    snapshot = root / ".mutation-thing.pristine"
    ms.take_snapshot(snapshot, module, tests)
    (root / "tests" / "test_more.py").write_text("", encoding="utf-8")

    moved = ms.moved_since(snapshot, module, [*tests, "tests/test_more.py"])

    assert moved == ["tests/test_more.py"]


def test_the_snapshot_is_named_for_the_SESSION_it_belongs_to(tree):
    """One directory per module, beside the session's own database and
    config, and under the `.mutation-` prefix the tree ignores. Two
    sweeps in different worktrees share this ROOT, so a single shared
    directory would have each restoring the other's source."""
    root, _module, _tests = tree

    assert ms.snapshot_dir("thing") == root / ".mutation-thing.pristine"
    assert ms.snapshot_dir("thing") != ms.snapshot_dir("other")


@pytest.fixture
def one_chunk(tree, monkeypatch, capsys):
    """Run `chunk` over fakes; return (what was copied, what was said)."""
    import shutil
    import sqlite3
    import subprocess

    root, module, tests = tree
    session = root / ".mutation-thing.sqlite"
    con = sqlite3.connect(session)
    con.execute("create table work_results (test_outcome text)")
    con.commit()
    con.close()
    # the real snapshot first: `copy2` is a recorder from here on
    ms.take_snapshot(root / ".mutation-thing.pristine", module, tests)

    copied: list[tuple[str, str]] = []
    monkeypatch.setattr(ms, "WORKTREE", root / "wt")
    monkeypatch.setattr(shutil, "copy2",
                        lambda a, b: copied.append((str(a), str(b))))
    monkeypatch.setattr(
        ms, "_run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(ms, "_bounded", lambda *a, **kw: None)  # the exec
    monkeypatch.setattr(ms, "progress", lambda s: (7, 1, 8, 8))

    def go(*, snapshot):
        ms.chunk(module, tests, root / "cfg.toml", session, 1,
                 snapshot=snapshot)
        return copied, capsys.readouterr().out
    return go


def test_the_chunk_restores_the_module_from_the_SNAPSHOT(one_chunk, tree):
    """The fix itself. Every chunk undoes the mutation cosmic-ray may
    have left behind, and the bytes it puts back have to be the ones the
    plan was built from — the live file is a different program the
    moment anyone saves an edit."""
    root, module, _tests = tree
    snapshot = root / ".mutation-thing.pristine"

    copied, _said = one_chunk(snapshot=snapshot)

    assert copied == [(str(snapshot / module), str(root / "wt" / module))]


def test_a_tree_that_MOVED_is_said_out_loud(one_chunk, tree):
    """Not a refusal: the run stays self-consistent, because the
    worktree keeps the harness it started with and the module now comes
    from the snapshot. But the figure describes the tree as it was
    planned, and a sweep left running for an hour has no other way to
    say so."""
    root, module, _tests = tree
    snapshot = root / ".mutation-thing.pristine"
    (root / module).write_text("def f(a, b):\n    return a + b\n",
                               encoding="utf-8")

    _copied, said = one_chunk(snapshot=snapshot)

    assert "changed since this session was planned" in said
    assert str(module) in said


def test_a_tree_that_did_NOT_move_says_nothing(one_chunk, tree):
    """The note has to be rare enough to read. Printed every chunk of
    every sweep it becomes part of the wallpaper, and the one run it
    matters for looks like all the others."""
    root, _module, _tests = tree
    snapshot = root / ".mutation-thing.pristine"

    _copied, said = one_chunk(snapshot=snapshot)

    assert "changed since" not in said


# --- the seeded sample, which has to be the SAME draw twice -------------


def _session(tmp_path, name, *, job_ids, order=None):
    """A session db holding 40 specs, ids and row order to taste."""
    import sqlite3

    path = tmp_path / name
    con = sqlite3.connect(path)
    con.execute("create table mutation_specs (module_path varchar, "
                "operator_name varchar, operator_args json, "
                "occurrence integer, start_pos_row integer, "
                "start_pos_col integer, job_id varchar not null primary key)")
    con.execute("create table work_results (worker_outcome varchar(9), "
                "output text, test_outcome varchar(11), diff text, "
                "job_id varchar not null primary key)")
    specs = [("m.py", "core/Op", "{}", i, 10 + i, 4) for i in range(40)]
    rows = list(zip(specs, job_ids, strict=True))
    if order is not None:
        rows = [rows[i] for i in order]
    con.executemany("insert into mutation_specs values (?,?,?,?,?,?,?)",
                    [(*spec, jid) for spec, jid in rows])
    con.commit()
    con.close()
    return path


def _kept(path):
    import sqlite3

    con = sqlite3.connect(path)
    rows = con.execute(
        "select ms.occurrence from mutation_specs ms "
        "left join work_results wr on ms.job_id = wr.job_id "
        "where wr.job_id is null order by 1").fetchall()
    con.close()
    return [r[0] for r in rows]


def test_the_seeded_sample_draws_the_same_mutants_from_a_NEW_session(
        tmp_path):
    """The claim `sample` makes about itself: a seeded draw is a paired
    comparison against a later suite. It was not one.

    `job_id` is a fresh UUID per `cosmic-ray init`, and
    `select job_id from mutation_specs` is answered from the primary
    key's COVERING INDEX — so the list arrives in sorted-UUID order,
    which is a different order every session. Seeded or not, the sample
    then drew a different set every time: measured on `_table_layout`,
    two draws from the same 2,720 mutants shared five of 120.

    Ordering by what the mutant IS makes the draw a function of the
    module and the seed, which is what the docstring promises."""
    import uuid

    first = _session(tmp_path, "a.sqlite",
                     job_ids=[uuid.uuid4().hex for _ in range(40)])
    # a second session over the SAME specs: new ids, and the rows
    # written in a different order for good measure
    second = _session(tmp_path, "b.sqlite",
                      job_ids=[uuid.uuid4().hex for _ in range(40)],
                      order=list(reversed(range(40))))

    ms.sample(first, 12, 20260816)
    ms.sample(second, 12, 20260816)

    assert len(_kept(first)) == 12
    assert _kept(first) == _kept(second)


def test_a_DIFFERENT_seed_is_a_different_draw(tmp_path):
    """The other half of "reproducible": the seed has to matter, or the
    sample is just the first N mutants in file order — which would make
    every figure a statement about the top of the module."""
    import uuid

    one = _session(tmp_path, "c.sqlite",
                   job_ids=[uuid.uuid4().hex for _ in range(40)])
    two = _session(tmp_path, "d.sqlite",
                   job_ids=[uuid.uuid4().hex for _ in range(40)])

    ms.sample(one, 12, 20260816)
    ms.sample(two, 12, 1)

    assert _kept(one) != _kept(two)


# --- what the worktree is given ------------------------------------------


def test_the_worktree_gets_todays_CONFTEST_too(tmp_path, monkeypatch):
    """The harness map names test FILES, and every one of them imports
    `tests/conftest.py`, which no map names. A worktree is created once
    and reused for weeks, so without this the fixtures are the ones from
    the commit it was created at — and the day conftest gains a helper,
    every sweep in that checkout fails its baseline check on a module
    nobody touched."""
    root, work = tmp_path / "root", tmp_path / "docxkit-mut9"
    (root / "src" / "docxkit").mkdir(parents=True)
    (root / "tests").mkdir()
    (work / "src" / "docxkit").mkdir(parents=True)
    (root / "src" / "docxkit" / "thing.py").write_text("x = 1\n")
    (root / "tests" / "test_thing.py").write_text("def test_f(): pass\n")
    (root / "tests" / "conftest.py").write_text("HELPER = 'today'\n")
    for name in ("README.md", "pyproject.toml"):
        (root / name).write_text("#\n")

    monkeypatch.setattr(ms, "ROOT", root)
    monkeypatch.setattr(ms, "WORKTREE", work)
    monkeypatch.setattr(ms, "_run", lambda *a, **kw: _Ok())

    ms.ensure_worktree(Path("src/docxkit/thing.py"), ["tests/test_thing.py"])

    assert (work / "tests" / "conftest.py").read_text() == "HELPER = 'today'\n"


def test_the_worktree_gets_a_SUBPACKAGE_too(tmp_path, monkeypatch):
    """`src/docxkit/*.py` copied the top level and nothing under it.

    `revision.py` became `revision/` on 2026-08-30 — fourteen halves,
    none of which a top-level glob can see. The session would then have
    planned against a module that is not in the worktree, or mutated
    whatever the checkout's own copy was.
    """
    root, work = tmp_path / "root", tmp_path / "docxkit-mut9"
    (root / "src" / "docxkit" / "revision").mkdir(parents=True)
    (root / "tests").mkdir()
    (work / "src" / "docxkit").mkdir(parents=True)
    (root / "src" / "docxkit" / "thing.py").write_text("x = 1\n")
    (root / "src" / "docxkit" / "revision" / "__init__.py").write_text("y=2\n")
    (root / "src" / "docxkit" / "revision" / "_build.py").write_text("z=3\n")
    (root / "tests" / "test_thing.py").write_text("def test_f(): pass\n")
    (root / "tests" / "conftest.py").write_text("HELPER = 'today'\n")
    for name in ("README.md", "pyproject.toml"):
        (root / name).write_text("#\n")

    monkeypatch.setattr(ms, "ROOT", root)
    monkeypatch.setattr(ms, "WORKTREE", work)
    monkeypatch.setattr(ms, "_run", lambda *a, **kw: _Ok())

    ms.ensure_worktree(Path("src/docxkit/revision/_build.py"),
                       ["tests/test_thing.py"])

    half = work / "src" / "docxkit" / "revision" / "_build.py"
    assert half.read_text() == "z=3\n", "the half under test is not there"
    assert (work / "src" / "docxkit" / "revision"
            / "__init__.py").read_text() == "y=2\n", "nor its facade"


def test_a_module_that_no_longer_EXISTS_is_removed_from_the_worktree(
        tmp_path, monkeypatch):
    """The other half, and the dangerous one.

    The worktree is created once at HEAD and reused for weeks, so a
    module that has since been split or renamed is still sitting in it —
    `revision.py`, 144 KB, dated six days before the split. Copying the
    new layout in beside it leaves BOTH, and `import docxkit.revision`
    resolves to whichever the loader prefers. A run then produces a
    number for source the session's plan does not describe, which is the
    hazard this module's docstring opens with, arriving as a stale
    LAYOUT rather than a stale module.
    """
    root, work = tmp_path / "root", tmp_path / "docxkit-mut9"
    (root / "src" / "docxkit").mkdir(parents=True)
    (root / "tests").mkdir()
    (work / "src" / "docxkit").mkdir(parents=True)
    (root / "src" / "docxkit" / "thing.py").write_text("x = 1\n")
    (root / "tests" / "test_thing.py").write_text("def test_f(): pass\n")
    (root / "tests" / "conftest.py").write_text("HELPER = 'today'\n")
    for name in ("README.md", "pyproject.toml"):
        (root / name).write_text("#\n")
    ghost = work / "src" / "docxkit" / "gone.py"
    ghost.write_text("the module that was split up\n")

    monkeypatch.setattr(ms, "ROOT", root)
    monkeypatch.setattr(ms, "WORKTREE", work)
    monkeypatch.setattr(ms, "_run", lambda *a, **kw: _Ok())

    ms.ensure_worktree(Path("src/docxkit/thing.py"), ["tests/test_thing.py"])

    assert not ghost.exists(), "a module the working tree does not have"
    assert (work / "src" / "docxkit" / "thing.py").exists(), \
        "and the live ones are still there"


class _Ok:
    """A finished subprocess that succeeded."""

    returncode = 0
    stderr = ""


# --- a SAMPLE must not quietly replace a better measurement --------------
#
# Found 2026-08-24, reading CONTRIBUTING's calibration table against the
# live session files. `crossrefs.py` was recorded at 6.9 % over the WHOLE
# module (57/822); `stale_figures` reported 9.3 % over 259. A later
# `--sample 260` had replaced the complete run — `--fresh` discards the
# session and the sample writes a new plan — and nothing about that is
# visible at the time or afterwards. The sample completes, prints a
# plausible number, and the only trace of the better run is a sentence in
# a document nobody diffs against the tool's output.


def _graded(path, killed=0, survived=0, other=0):
    """Write verdicts into a session db built by `_session`."""
    import sqlite3

    con = sqlite3.connect(path)
    jobs = [r[0] for r in con.execute("select job_id from mutation_specs")]
    outcomes = (["killed"] * killed + ["survived"] * survived
                + ["incompetent"] * other)
    con.executemany(
        "insert into work_results (job_id, worker_outcome, test_outcome, "
        "output) values (?, 'normal', ?, '')",
        list(zip(jobs, outcomes, strict=False)))
    con.commit()
    con.close()
    return path


def test_a_sample_SMALLER_than_what_was_already_graded_is_a_loss(tmp_path):
    """The measured case: 822 mutants' worth of verdicts, and a
    `--sample 260` about to stand in for them. The answer is the size of
    what would go, because that is the number the refusal has to say."""
    import uuid

    session = _graded(
        _session(tmp_path, "a.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        killed=30, survived=5)

    assert ms.would_lose(session, 12).graded == 35


def test_a_sample_at_LEAST_as_big_as_the_grading_loses_nothing(tmp_path):
    """Re-sampling at the same size, or wider, is the ordinary thing to
    do between suites — and a guard that stopped it would be turned off
    inside a week. 35 graded, 35 kept: nothing to protect."""
    import uuid

    session = _graded(
        _session(tmp_path, "b.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        killed=30, survived=5)

    assert ms.would_lose(session, 35).graded == 0
    assert ms.would_lose(session, 400).graded == 0


def test_only_a_VERDICT_counts_as_something_to_lose(tmp_path):
    """A mutant that came back INCOMPETENT is finished and is not an
    answer — cosmic-ray could not run it at all. A session holding
    nothing but those has measured nothing, so discarding it costs
    nothing, and refusing would be a gate firing on an empty hand."""
    import uuid

    session = _graded(
        _session(tmp_path, "c.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        other=20)

    assert ms.would_lose(session, 5).graded == 0


def test_there_is_nothing_to_lose_when_there_is_no_session(tmp_path):
    """The first run of a module, which is most of them."""
    assert ms.would_lose(tmp_path / "absent.sqlite", 5) == (0, 0)


def _sample_run(tree, monkeypatch, capsys, *argv):
    """`main` up to the point the session would be discarded."""
    _root, module, tests = tree
    monkeypatch.setattr(sys, "argv",
                        ["mutation_session.py", str(module).replace("\\", "/"),
                         "--tests", *tests, *argv])
    code = ms.main()
    return code, capsys.readouterr().out


def test_the_run_that_would_LOSE_the_better_figure_is_refused(
        tree, monkeypatch, capsys):
    """End to end, and the session file has to still be there afterwards:
    the refusal is only worth anything if it lands BEFORE the unlink."""
    import uuid

    root, _, _ = tree
    session = _graded(
        _session(root, ".mutation-thing.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        killed=30, survived=5)

    code, said = _sample_run(tree, monkeypatch, capsys,
                             "--fresh", "--sample", "12")

    assert code == 2, "a refusal, not a warning printed on the way past"
    assert session.exists(), "the session was discarded by the refused run"
    assert "35" in said and "12" in said, \
        "both numbers, or the reader cannot judge the trade"
    assert "--force" in said, "a refusal has to name the way through"


def test_force_discards_it_deliberately(tree, monkeypatch, capsys):
    """The same shape as `--force` on the protocol commands: the judgment
    is the caller's, and what the guard buys is that it is a judgment."""
    import uuid

    root, _, _ = tree
    session = _graded(
        _session(root, ".mutation-thing.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        killed=30, survived=5)
    drawn = []
    monkeypatch.setattr(ms, "_take_lock", lambda: None)
    monkeypatch.setattr(ms, "ensure_worktree", lambda *a: None)
    monkeypatch.setattr(ms, "take_snapshot", lambda *a: None)
    monkeypatch.setattr(ms, "write_config", lambda *a, **kw: None)
    monkeypatch.setattr(ms, "_run", lambda *a, **kw: _Ok())
    monkeypatch.setattr(ms, "chunk", lambda *a, **kw: False)
    # `init` is the mocked subprocess, so it writes no db for the real
    # `sample` to draw from; what is being asserted is that the run got
    # PAST the guard and re-planned, which is the whole of `--force`.
    monkeypatch.setattr(ms, "sample",
                        lambda session, keep, seed: drawn.append(keep))

    code, _ = _sample_run(tree, monkeypatch, capsys,
                          "--fresh", "--sample", "12", "--force")

    assert code == 0
    assert not session.exists(), "--force means discard it"
    assert drawn == [12], "and re-plan at the size the caller asked for"


def test_a_sample_handed_to_a_RESUME_says_it_is_doing_nothing(
        tree, monkeypatch, capsys):
    """The draw is planned at `init`, so `--sample` on a resume has never
    done anything — silently, which reads as "I sampled it" against a run
    measuring something else entirely."""
    import uuid

    root, _, _ = tree
    _graded(_session(root, ".mutation-thing.sqlite",
                     job_ids=[uuid.uuid4().hex for _ in range(40)]),
            killed=2)
    monkeypatch.setattr(ms, "_take_lock", lambda: None)
    monkeypatch.setattr(ms, "ensure_worktree", lambda *a: None)
    monkeypatch.setattr(ms, "take_snapshot", lambda *a: None)
    monkeypatch.setattr(ms, "write_config", lambda *a, **kw: None)
    monkeypatch.setattr(ms, "moved_since", lambda *a: [])
    monkeypatch.setattr(ms, "chunk", lambda *a, **kw: False)

    code, said = _sample_run(tree, monkeypatch, capsys, "--sample", "12")

    assert code == 0
    assert "not applied here" in said and "--fresh" in said


# --- a mutant that HANGS, 2026-09-13 (BACKLOG) ----------------------------
#
# `sections._format`'s `rest - value` -> `rest ** value` computes in C and
# never ends. cosmic-ray's timeout killed the --fast wrapper alone — on
# Windows it cannot kill a process group — and then waited for ever on the
# pytest under it, one chunk after another, each leaving that pytest running.


@pytest.fixture
def mt(tmp_path, monkeypatch):
    import mutant_tests  # pyright: ignore[reportMissingImports]
    # A child pytest started in the repo on a test file in %TEMP%, another
    # drive, collects down from that drive's root through the thousands of
    # entries other workers are making and deleting; one went between its
    # listing and its lstat, and the child failed collecting (2026-09-13).
    # It starts beside its test file instead.
    monkeypatch.chdir(tmp_path)
    return mutant_tests


def test_the_wrapper_ENDS_a_harness_that_runs_past_its_deadline(
        mt, tmp_path, capsys):
    """Against a real pytest that never finishes: the wrapper hands back a
    failure within seconds, so cosmic-ray reads the mutant as KILLED
    instead of waiting on it."""
    import time

    hang = tmp_path / "test_hang.py"
    hang.write_text("import time\n\n\ndef test_hangs():\n"
                    "    time.sleep(120)\n", encoding="utf-8")
    start = time.monotonic()

    code = mt.run(["-q", "-p", "no:cacheprovider", str(hang)],
                  deadline=start + 3)

    assert code == 1
    assert time.monotonic() - start < 30
    assert "ran past its deadline" in capsys.readouterr().out


def test_the_deadline_is_ONE_budget_for_both_phases(mt, monkeypatch):
    """Parsed off the front of the command and handed to the covering run
    AND the whole harness behind it: a fresh allowance each would let the
    pair outlive cosmic-ray's backstop."""
    import time

    seen: list[float | None] = []
    monkeypatch.setattr(mt, "mutated_lines", lambda stem, module: [2])
    monkeypatch.setattr(mt, "covering_tests", lambda stem, lines: ["t::a"])
    def run(args: list[str], deadline: float | None = None) -> int:
        seen.append(deadline)
        return 0

    monkeypatch.setattr(mt, "run", run)
    before = time.monotonic()

    assert mt.main(["--deadline", "30", "thing", "src/docxkit/thing.py",
                    "--", "-q", "tests/t.py"]) == 0

    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[0] is not None and before + 29 < seen[0] < before + 31
    seen.clear()
    mt.main(["thing", "src/docxkit/thing.py", "--", "-q"])
    assert seen == [None, None], "no --deadline, no limit"


def test_under_FAST_cosmic_rays_limit_sits_ABOVE_the_wrappers_deadline(
        tmp_path, monkeypatch):
    """The wrapper has to act first, and the 30-second line between a
    survivor and a kill must not move: plain runs keep cosmic-ray's 30."""
    monkeypatch.setattr(ms, "WORKTREE", tmp_path / "wt")
    fast, plain = tmp_path / "fast.toml", tmp_path / "plain.toml"
    module, tests = Path("src/docxkit/thing.py"), ["tests/test_thing.py"]

    ms.write_config(module, tests, fast, stem="thing", fast=True)
    ms.write_config(module, tests, plain)

    fast_text = fast.read_text(encoding="utf-8")
    plain_text = plain.read_text(encoding="utf-8")
    assert f"--deadline {ms.MUTANT_SECONDS} thing " in fast_text
    assert f"timeout = {float(ms.MUTANT_SECONDS + ms.BACKSTOP)}" in fast_text
    assert "--deadline" not in plain_text
    assert f"timeout = {float(ms.MUTANT_SECONDS)}" in plain_text


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the cap is a Windows job object's")
def test_a_mutant_that_ALLOCATES_past_the_cap_reads_as_a_failure(
        mt, tmp_path, monkeypatch):
    """`(n - 1) // 26 + 1` -> `(n - 1) << 26 + 1` in `sections._format`
    asks for a 3.1 GiB string and then a copy of it, inside a second: no
    deadline reaches that, and the host ended the whole sweep for memory
    (BACKLOG, 2026-09-13). Under the cap the allocation fails inside the
    test, while a harness that stays under it runs as it always did."""
    # The 2 GiB that fails is refused at commit, before a page is touched.
    monkeypatch.setattr(mt, "MEMORY_LIMIT", 1 << 30)
    big, small = tmp_path / "test_big.py", tmp_path / "test_small.py"
    big.write_text("def test_allocates():\n"
                   "    assert len(bytearray(2 << 30)) == 2 << 30\n",
                   encoding="utf-8")
    small.write_text("def test_allocates():\n"
                     "    assert len(bytearray(16 << 20)) == 16 << 20\n",
                     encoding="utf-8")
    args = ["-q", "-p", "no:cacheprovider"]

    assert mt.run([*args, str(big)]) == 1
    assert mt.run([*args, str(small)]) == 0


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the job object is Windows's")
def test_what_the_harness_STARTED_ends_with_a_run_past_its_deadline(
        mt, tmp_path):
    """Ending the pytest at the deadline left whatever it had started
    running on. Everything the run starts is in its job, and the job ends
    with the run."""
    import time

    pid_file = tmp_path / "grandchild.pid"
    spawns = tmp_path / "test_spawns.py"
    spawns.write_text(
        "import pathlib, subprocess, sys, time\n\n\n"
        "def test_spawns():\n"
        "    p = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(120)'])\n"
        f"    pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        "    time.sleep(120)\n", encoding="utf-8")

    assert mt.run(["-q", "-p", "no:cacheprovider", str(spawns)],
                  deadline=time.monotonic() + 8) == 1
    assert not ms._alive(int(pid_file.read_text(encoding="utf-8")))


def test_a_run_with_NO_job_to_hold_it_goes_uncapped_and_still_reports(
        mt, tmp_path, monkeypatch):
    """Off Windows no job is asked for at all, and on Windows a job that
    cannot be made leaves the harness running as it did before the cap."""
    ok = tmp_path / "test_ok.py"
    ok.write_text("def test_ok():\n    pass\n", encoding="utf-8")
    args = ["-q", "-p", "no:cacheprovider", str(ok)]

    monkeypatch.setattr(mt, "_job", lambda pid, limit: None)
    assert mt.run(args) == 0

    def refuse(pid: int, limit: int) -> None:
        raise AssertionError("a job was asked for off Windows")

    monkeypatch.setattr(mt, "_WINDOWS", False)
    monkeypatch.setattr(mt, "_job", refuse)
    assert mt.run(args) == 0


class _Hangs:
    """A `Popen` whose process never exits on its own."""

    pid = 4242

    def __init__(self) -> None:
        self.waits, self.killed = 0, False

    def wait(self, timeout: float | None = None) -> int:
        self.waits += 1
        if timeout is not None:
            raise ms.subprocess.TimeoutExpired("cosmic-ray", timeout)
        return -9

    def kill(self) -> None:
        self.killed = True


@pytest.mark.parametrize("windows", [True, False])
def test_a_chunk_that_runs_out_ends_cosmic_rays_TREE_on_windows(
        tmp_path, monkeypatch, windows):
    """`subprocess.run(timeout=)` ended cosmic-ray and nothing under it."""
    made: list[_Hangs] = []
    ran: list[list[str]] = []
    def popen(*a: object, **kw: object) -> _Hangs:
        made.append(_Hangs())
        return made[-1]

    monkeypatch.setattr(ms.subprocess, "Popen", popen)
    monkeypatch.setattr(ms, "_run", lambda cmd, **kw: ran.append(cmd))
    monkeypatch.setattr(ms, "_env", dict)
    monkeypatch.setattr(ms, "WORKTREE", tmp_path)
    monkeypatch.setattr(ms, "_WINDOWS", windows)

    ms._bounded(["cosmic-ray", "exec"], 1)

    (proc,) = made
    assert proc.killed and proc.waits == 2
    assert ran == ([["taskkill", "/PID", "4242", "/T", "/F"]] if windows
                   else [])


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the tree walk is taskkill's")
def test_a_REAL_grandchild_dies_with_the_chunk(tmp_path, monkeypatch):
    """What the stall needed: the command cosmic-ray was running, one
    level down, ends with it — not later, and not never."""
    import os

    pid_file = tmp_path / "grandchild.pid"
    script = ("import subprocess, sys, time\n"
              "p = subprocess.Popen([sys.executable, '-c', "
              "'import time; time.sleep(120)'])\n"
              f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
              "time.sleep(120)\n")
    monkeypatch.setattr(ms, "WORKTREE", tmp_path)
    monkeypatch.setattr(ms, "_env", os.environ.copy)

    ms._bounded([sys.executable, "-c", script], 5)

    assert not ms._alive(int(pid_file.read_text(encoding="utf-8")))


def _stuck_run(tree, monkeypatch, capsys, *argv):
    """`main` over fakes whose chunks never finish a mutant, with the
    worktree's module carrying one."""
    root, module, tests = tree
    ms.take_snapshot(root / ".mutation-thing.pristine", module, tests)
    live = root / "wt" / module
    live.parent.mkdir(parents=True)
    live.write_text("def f(a, b):\n    return a ** b\n", encoding="utf-8")
    chunks: list[int] = []

    def chunk(*a, **kw):
        chunks.append(1)
        if len(chunks) > 4:
            raise AssertionError("the loop asked for the stuck mutant again")
        return True

    monkeypatch.setattr(ms, "WORKTREE", root / "wt")
    monkeypatch.setattr(ms, "_take_lock", lambda: None)
    monkeypatch.setattr(ms, "ensure_worktree", lambda *a: None)
    monkeypatch.setattr(ms, "take_snapshot", lambda *a: None)
    monkeypatch.setattr(ms, "write_config", lambda *a, **kw: None)
    monkeypatch.setattr(ms, "moved_since", lambda *a: [])
    monkeypatch.setattr(ms, "_run", lambda *a, **kw: _Ok())
    monkeypatch.setattr(ms, "progress", lambda s: (1, 1, 2, 3))
    monkeypatch.setattr(ms, "chunk", chunk)
    code, said = _sample_run(tree, monkeypatch, capsys, *argv)
    return code, said, chunks, live


def test_a_chunk_that_ends_NO_mutant_stops_the_session_and_names_it(
        tree, monkeypatch, capsys):
    """459/460 for seventy minutes: `--chunks 0` asked for the same mutant
    ten times. A chunk long enough to end any mutant that ends none — read
    against the chunk before it — is the verdict: stop, say which line,
    put the module back."""
    code, said, chunks, live = _stuck_run(tree, monkeypatch, capsys,
                                          "--chunks", "0")

    assert code == 3
    assert "STUCK" in said and "line 2: return a ** b" in said
    assert len(chunks) == 2, "the first sets the mark, the second is judged"
    assert "return a - b" in live.read_text(encoding="utf-8")


def test_a_SHORT_chunk_that_ends_nothing_is_not_called_stuck(
        tree, monkeypatch, capsys):
    """A one-minute chunk can spend itself on one slow mutant and
    cosmic-ray's start-up; only a chunk with room for two is judged."""
    code, said, chunks, _live = _stuck_run(tree, monkeypatch, capsys,
                                           "--chunks", "3", "--minutes", "1")

    assert code == 0
    assert "STUCK" not in said
    assert len(chunks) == 3


def test_a_session_that_cannot_be_READ_is_nothing_to_protect(tmp_path):
    """`--fresh` is the documented way to clear a session that went
    wrong, and a zero-byte or truncated db is what one looks like —
    there is one in this repo root right now. Raising here would put the
    guard between the caller and the recovery they are asking for, so an
    unreadable session answers "nothing to lose", which is true."""
    empty = tmp_path / "empty.sqlite"
    empty.touch()
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a database at all, just bytes")

    assert ms.would_lose(empty, 5) == (0, 0)
    assert ms.would_lose(junk, 5) == (0, 0)


def test_a_wider_PLAN_barely_started_is_a_note_and_not_a_refusal(tmp_path):
    """Two numbers because they deserve two answers. Losing a VERDICT is
    the regression the guard exists for; re-planning 822 mutants that
    have produced five verdicts costs the planning time and nothing
    else, so it is said out loud and allowed."""
    import uuid

    session = _graded(
        _session(tmp_path, "plan.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        killed=5)

    lost = ms.would_lose(session, 12)

    assert lost.graded == 0, "five verdicts, and twelve are being kept"
    assert lost.planned == 40, "but the plan it replaces was wider"


def test_reading_the_session_does_not_BLOCK_deleting_it(tmp_path):
    """Windows, and the ordinary path rather than an exotic one.
    `progress` left its sqlite connection open; `--fresh` reads the
    session and then unlinks it, so the common re-sample raised
    WinError 32 whenever the refcount had not yet dropped. Whether it
    failed was decided by garbage-collection timing, which is the worst
    way for a tool to be intermittently broken."""
    import uuid

    session = _graded(
        _session(tmp_path, "lock.sqlite",
                 job_ids=[uuid.uuid4().hex for _ in range(40)]),
        killed=2)

    ms.would_lose(session, 12)
    session.unlink()               # raises WinError 32 with a handle open

    assert not session.exists()


# --- a MUTANT of the isolation cannot reach the author's profile --------


def test_a_mutant_that_IGNORES_the_registry_override_stays_in_the_sandbox(
        monkeypatch):
    """Measured 2026-09-11: a mutant of `revision/_registry.registry_path`
    that skipped the `DOCXKIT_PAPERS` override fell through to
    ``%LOCALAPPDATA%``, and the harness it ran appended 160 throwaway
    papers to the author's real registry. The mutant was KILLED — the
    right verdict — and nothing said a word about the file.

    Asserted as that mutant's own computation, under the environment a
    session hands every child it starts: with the override gone, the
    registry still lands beside the worktree and nowhere in the real
    profile. Not as a list of keys — a key list passes the day a new
    fallback root is added to `registry_path` and left out here."""
    import os

    from docxkit.revision import registry_path

    real = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    env = ms._env()
    sandbox = ms.WORKTREE.parent / f"{ms.WORKTREE.name}.appdata"
    for key in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(key, env[key])
    monkeypatch.delenv("DOCXKIT_PAPERS", raising=False)   # what the mutant did

    escaped = registry_path()

    assert escaped.is_relative_to(sandbox), escaped
    assert not escaped.is_relative_to(real), escaped
    assert Path(env["DOCXKIT_PAPERS"]).is_relative_to(sandbox), (
        "an UNMUTATED registry lands in the same place")


def test_mirror_src_copies_EVERY_depth_and_deletes_what_is_gone(tmp_path):
    """The package made the same in a checkout: a module at any depth
    copied in, a module the live tree no longer has deleted, and nothing
    outside `src/docxkit` touched. Three depths, because `glob("*.py")`
    passes a one-level fixture — which is how `kill_check.sync` copied the
    top level for a fortnight and left `revision/`'s halves behind."""
    live, tree = tmp_path / "live", tmp_path / "tree"
    for rel, text in (("src/docxkit/top.py", "A = 1\n"),
                      ("src/docxkit/revision/_half.py", "B = 2\n"),
                      ("src/docxkit/revision/deeper/_leaf.py", "C = 3\n")):
        (live / rel).parent.mkdir(parents=True, exist_ok=True)
        (live / rel).write_text(text, encoding="utf-8")
    behind = tree / "src" / "docxkit" / "revision" / "_half.py"
    behind.parent.mkdir(parents=True)
    behind.write_text("B = 0\n", encoding="utf-8")
    gone = behind.parent / "_gone.py"
    gone.write_text("D = 4\n", encoding="utf-8")
    kept = tree / "tests" / "test_x.py"
    kept.parent.mkdir(parents=True)
    kept.write_text("", encoding="utf-8")

    ms.mirror_src(live, tree)

    assert sorted(p.relative_to(tree).as_posix()
                  for p in (tree / "src").rglob("*.py")) == [
        "src/docxkit/revision/_half.py",
        "src/docxkit/revision/deeper/_leaf.py",
        "src/docxkit/top.py"]
    assert behind.read_text(encoding="utf-8") == "B = 2\n", "not refreshed"
    assert kept.exists(), "only the package is mirrored"


def test_mirror_src_walks_the_PACKAGE_not_a_snapshot_beside_it(tmp_path,
                                                               monkeypatch):
    """`rglob` puts `**/` in front of its pattern, so walking `live` for
    `src/docxkit/**/*.py` also found every session's snapshot,
    `.mutation-<stem>.pristine/src/docxkit/<module>.py`. Copied, it was
    junk in the checkout. Deleted by another stream's `--fresh` between
    the listing and the copy, it was a fan-out losing a stream at startup
    (BACKLOG S4) — so here the snapshot goes at the first copy, the way it
    went then."""
    live, tree = tmp_path / "live", tmp_path / "tree"
    snapshot = live / ".mutation-top.pristine"
    for rel in ("src/docxkit/top.py",
                ".mutation-top.pristine/src/docxkit/top.py"):
        (live / rel).parent.mkdir(parents=True, exist_ok=True)
        (live / rel).write_text("A = 1\n", encoding="utf-8")
    real_copy = ms.shutil.copy2

    def copy_while_a_stream_starts_fresh(src, dst, *args, **kwargs):
        ms.shutil.rmtree(snapshot, ignore_errors=True)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(ms.shutil, "copy2", copy_while_a_stream_starts_fresh)

    ms.mirror_src(live, tree)

    assert (tree / "src" / "docxkit" / "top.py").exists()
    assert not (tree / ".mutation-top.pristine").exists()
