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


class _Ok:
    """A finished subprocess that succeeded."""

    returncode = 0
    stderr = ""
