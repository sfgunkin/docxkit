"""`tools/stale_figures.py` — is a survivor list still about this code?

A mutation figure is a photograph of one tree, and the rule for quoting
one is in CONTRIBUTING: re-measure when the source has moved. The half
that was missing is the HARNESS. A test added after a run kills mutants
the list still calls survivors, so the next round mines them and finds
nothing — which is exactly what happened to `equations.py` on
2026-08-19, where the three-equation fixture committed an hour before
the run was not in the answers it gave.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed: the path insert above
# is how its scripts reach each other, and how they are reached here.
from stale_figures import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ROOT,
    commit_times,
    last_touched,
    newer_than,
    session_file,
    state,
)


def test_the_session_file_of_a_PRIVATE_module_drops_the_underscore():
    """`_table_core.py` measures into `.mutation-table_core.sqlite`;
    a check that looked for `.mutation-_table_core.sqlite` would call
    every private module "never measured"."""
    assert session_file("_table_core.py").name == ".mutation-table_core.sqlite"
    assert session_file("cli.py").name == ".mutation-cli.sqlite"


def test_a_module_with_no_session_file_is_never_measured(monkeypatch):
    verdict, moved = state("no_such_module.py", [])

    assert verdict == "never measured"
    assert moved == []


def test_a_file_CHANGED_after_the_run_is_reported(tmp_path):
    """The whole question: what has moved since the photograph."""
    old = tmp_path / "old.py"
    old.write_text("x = 1", encoding="utf-8")
    import os
    os.utime(old, (1_000_000, 1_000_000))

    assert newer_than(2_000_000, [old]) == []
    assert newer_than(500_000, [old]) == [old]


def test_an_UNCOMMITTED_file_counts_as_much_as_a_committed_one(tmp_path):
    """`last_touched` takes the later of the two. A test written and not
    yet committed is the one a run is most likely to have picked up by
    accident, and treating it as unchanged is how a figure quietly stops
    describing anything."""
    scratch = tmp_path / "untracked.py"
    scratch.write_text("y = 2", encoding="utf-8")

    assert last_touched(scratch) == pytest.approx(scratch.stat().st_mtime)


def test_a_file_that_does_not_exist_is_not_a_change(tmp_path):
    assert last_touched(tmp_path / "gone.py") == 0.0


def test_the_tool_RUNS_and_names_every_module_in_the_map(monkeypatch, capsys):
    """It is read by a person before a round, so the listing has to
    cover the map rather than whatever happens to be stale today."""
    import harness_map  # pyright: ignore[reportMissingImports]
    from stale_figures import main  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(sys, "argv", ["stale_figures.py"])
    code = main()

    out = capsys.readouterr().out
    for module in harness_map.HARNESS:
        assert module in out, module
    assert code in (0, 1)


def test_the_STALE_flag_prints_a_subset(monkeypatch, capsys):
    from stale_figures import main  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(sys, "argv", ["stale_figures.py", "--stale"])
    main()

    assert "fresh" not in capsys.readouterr().out


def test_the_commit_times_map_answers_for_a_TRACKED_file(tmp_path):
    """One `git log --name-only` pass instead of one `git log` per path.
    Process spawn is ~190 ms on Windows and this tool asks about ninety
    paths: the walk took 17 seconds, in a suite that runs 3,900 tests in
    under a minute, and it is meant to be run before every round.

    The map has to agree with the question it replaced — the newest
    commit that touched the file — so this asks it about a file the
    repository certainly has."""
    times = commit_times()

    assert times, "the map is empty — did `git log` run?"
    assert times["tools/stale_figures.py"] > 0
    assert times["tools/stale_figures.py"] <= last_touched(
        ROOT / "tools" / "stale_figures.py")


def test_a_path_OUTSIDE_the_repository_is_answered_from_disk(tmp_path):
    """`relative_to` raises for one, and git could not answer anyway.
    The mtime is still the honest answer: a session file written to a
    scratch directory is as much a change as a committed one."""
    outside = tmp_path / "elsewhere.py"
    outside.write_text("x = 1\n", encoding="utf-8")

    assert last_touched(outside) == pytest.approx(outside.stat().st_mtime)


# --- the figure beside the verdict --------------------------------------


def test_the_figures_mode_prints_a_figure_per_module():
    """CONTRIBUTING's tables are written by hand from whatever the last
    round printed into a terminal, so they are out of date the moment a
    round lands. `--figures` reads every session file through
    `mutation_survivors.classify` — the same arithmetic the survivor
    list uses, so the two cannot disagree — and prints the package's
    state in one screen."""
    import harness_map  # pyright: ignore[reportMissingImports]

    done = subprocess.run(
        [sys.executable, str(TOOLS / "stale_figures.py"), "--figures"],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    lines = [ln for ln in done.stdout.splitlines() if ln.strip()]
    assert lines, done.stderr
    for line in lines:
        assert line.endswith(("fresh", "stale", "never measured")), line
    # A CHECKOUT has no session files — they are local and none is
    # committed — so "every module has a figure" is a claim about the
    # machine, not about the tool. CI failed on exactly that. What holds
    # everywhere is the SHAPE of a line that does carry one.
    for line in [ln for ln in lines if "%" in ln]:
        assert re.search(r"\d+\.\d%\s+\(\d+/\d+\)", line), line
    assert len(lines) == len(harness_map.HARNESS), done.stdout


def test_a_partial_run_is_MARKED_in_the_table(tmp_path, monkeypatch):
    """The figure of a run that stopped early is whatever its first
    mutants said, and it flatters — 1.0 % against a true 2.7 % on
    `_table_core`. The table says so where a reader is most likely to
    quote it."""
    import sqlite3

    import stale_figures  # pyright: ignore[reportMissingImports]

    db = tmp_path / ".mutation-thing.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE mutation_specs (job_id TEXT, "
                 "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    conn.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
                 "diff TEXT)")
    for i in range(4):
        conn.execute("INSERT INTO mutation_specs VALUES (?, 2, 0, 'op')",
                     (f"job{i}",))
    conn.execute("INSERT INTO work_results VALUES ('job0', 'SURVIVED', '')")
    conn.commit()
    conn.close()

    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True)
    (src / "thing.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(stale_figures, "ROOT", tmp_path)
    monkeypatch.setattr(stale_figures, "session_file", lambda module: db)

    assert "PARTIAL" in stale_figures.figure("thing.py")


def test_a_facade_with_NOTHING_to_mutate_says_so(tmp_path, monkeypatch):
    """`tables.py` re-exports two modules and states no logic of its
    own, so cosmic-ray plans zero mutants for it. "graded nothing" reads
    as a run that failed; the module simply has nothing to grade, and a
    table that cannot tell them apart sends someone to re-measure a
    facade."""
    import sqlite3

    import stale_figures  # pyright: ignore[reportMissingImports]

    db = tmp_path / ".mutation-facade.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE mutation_specs (job_id TEXT, "
                 "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    conn.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
                 "diff TEXT)")
    conn.commit()
    conn.close()

    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True)
    (src / "facade.py").write_text("from x import y as y\n", encoding="utf-8")
    monkeypatch.setattr(stale_figures, "ROOT", tmp_path)
    monkeypatch.setattr(stale_figures, "session_file", lambda module: db)

    assert stale_figures.figure("facade.py") == "no mutants"



def _session_with(db, outcomes):
    """A session file whose rows carry the given outcomes, in order."""
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE mutation_specs (job_id TEXT, "
                 "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    conn.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
                 "diff TEXT)")
    for i, outcome in enumerate(outcomes):
        conn.execute("INSERT INTO mutation_specs VALUES (?, 2, 4, ?)",
                     (f"job{i}", "core/NumberReplacer"))
        conn.execute("INSERT INTO work_results VALUES (?, ?, ?)",
                     (f"job{i}", outcome, "--- a\n+++ b\n@@\n-was\n+now\n"))
    conn.commit()
    conn.close()


SRC_ONE_LINE = "def f(x):\n    return x + 1\n"


def test_a_SAMPLED_run_says_so_in_the_table(tmp_path, monkeypatch):
    """The figure of a sample is an estimate over a fraction, and it
    printed as a measurement of the whole module. A reader planning a
    round off that column cannot tell the two apart, and the whole
    column exists to be planned off."""
    import stale_figures  # pyright: ignore[reportMissingImports]

    db = tmp_path / ".mutation-thing.sqlite"
    _session_with(db, ["SURVIVED", "KILLED", "SKIPPED", "SKIPPED"])
    src = tmp_path / "thing.py"
    src.write_text(SRC_ONE_LINE, encoding="utf-8")
    monkeypatch.setattr(stale_figures, "ROOT", tmp_path)
    monkeypatch.setattr(stale_figures, "session_file", lambda _m: db)
    (tmp_path / "src" / "docxkit").mkdir(parents=True)
    (tmp_path / "src" / "docxkit" / "thing.py").write_text(
        SRC_ONE_LINE, encoding="utf-8")

    line = stale_figures.figure("thing.py")

    assert "SAMPLED 2/4" in line, line


def test_a_run_of_EVERY_mutant_is_not_marked(tmp_path, monkeypatch):
    """The mark has to mean something, so a complete run must not carry
    it — otherwise the column reads as "estimate" everywhere and the
    distinction is gone again."""
    import stale_figures  # pyright: ignore[reportMissingImports]

    db = tmp_path / ".mutation-thing.sqlite"
    _session_with(db, ["SURVIVED", "KILLED", "KILLED", "KILLED"])
    monkeypatch.setattr(stale_figures, "ROOT", tmp_path)
    monkeypatch.setattr(stale_figures, "session_file", lambda _m: db)
    (tmp_path / "src" / "docxkit").mkdir(parents=True)
    (tmp_path / "src" / "docxkit" / "thing.py").write_text(
        SRC_ONE_LINE, encoding="utf-8")

    line = stale_figures.figure("thing.py")

    assert "SAMPLED" not in line, line
    assert "PARTIAL" not in line, line


# --- a COMMIT is not a change --------------------------------------------


def _session(tmp_path, monkeypatch, *, module_now: str, module_then: str,
             test_now: str = "t", test_then: str = "t"):
    """A measured module, its snapshot, and a working tree beside it."""
    import stale_figures as sf  # pyright: ignore[reportMissingImports]

    (tmp_path / "src" / "docxkit").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "docxkit" / "thing.py").write_text(module_now)
    (tmp_path / "tests" / "test_thing.py").write_text(test_now)
    (tmp_path / ".mutation-thing.sqlite").write_text("")

    kept = tmp_path / ".mutation-thing.pristine"
    (kept / "src" / "docxkit").mkdir(parents=True)
    (kept / "tests").mkdir(parents=True)
    (kept / "src" / "docxkit" / "thing.py").write_text(module_then)
    (kept / "tests" / "test_thing.py").write_text(test_then)

    monkeypatch.setattr(sf, "ROOT", tmp_path)
    return sf


def test_a_file_COMMITTED_UNCHANGED_is_still_fresh(tmp_path, monkeypatch):
    """The defect this replaced, measured 2026-08-30.

    `last_touched` is `max(mtime, last commit time)`, so committing a
    file re-dates it. `revision/_build.py` was untouched on disk since
    01:35, measured at 15:48 and committed unchanged at 21:41 — and read
    `stale`. Every figure in the repository goes void the moment the
    round that produced it is recorded, which makes the real signal
    unreadable exactly when it is wanted.
    """
    sf = _session(tmp_path, monkeypatch, module_now="x = 1",
                  module_then="x = 1")

    verdict, moved = sf.state("thing.py", ["tests/test_thing.py"])

    assert verdict == "fresh", moved


def test_a_file_whose_CONTENT_moved_is_stale(tmp_path, monkeypatch):
    """The signal itself, which the change must not cost."""
    sf = _session(tmp_path, monkeypatch, module_now="x = 2",
                  module_then="x = 1")

    verdict, moved = sf.state("thing.py", ["tests/test_thing.py"])

    assert verdict == "stale"
    assert moved == ["src/docxkit/thing.py"]


def test_a_file_that_differs_only_in_its_NEWLINES_has_not_moved(
        tmp_path, monkeypatch):
    """A checkout's line endings are not an edit, and reading them as one
    took 34 of this repository's 65 stored sessions out of reach.

    Git for Windows sets `core.autocrlf=true` in its SYSTEM config, so
    `git worktree add` wrote CRLF where D:/docxkit held LF; a `.pristine`
    snapshot copied from either one then disagreed with the other about
    every line, `state` reported the MODULE as moved, and
    `replay_survivors` refused in a checkout where nothing had been
    edited. Measured against a fresh worktree at master, 2026-09-18: 10
    snapshots agreed byte for byte, 21 held a module that had really
    changed, and 34 differed in newlines alone.

    Written as BYTES on both sides, because `Path.write_text` translates
    on this platform and would give the two files the same endings —
    which is the test passing for the wrong reason.
    """
    sf = _session(tmp_path, monkeypatch, module_now="x = 1\n",
                  module_then="x = 1\n")
    (tmp_path / "src" / "docxkit" / "thing.py").write_bytes(b"x = 1\r\n")
    (tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
     / "thing.py").write_bytes(b"x = 1\n")

    verdict, moved = sf.state("thing.py", ["tests/test_thing.py"])

    assert verdict == "fresh", moved


def test_a_REAL_change_is_still_a_change_when_the_newlines_differ_too(
        tmp_path, monkeypatch):
    """The half that matters more. The refusal exists because replaying
    a survivor list against a module that moved grades mutations nobody
    made, so a comparison that stops refusing is worse than the wall it
    was put up against. One line of content apart, and written with
    different endings as well, is still moved."""
    sf = _session(tmp_path, monkeypatch, module_now="x = 1\n",
                  module_then="x = 1\n")
    (tmp_path / "src" / "docxkit" / "thing.py").write_bytes(b"x = 2\r\n")
    (tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
     / "thing.py").write_bytes(b"x = 1\n")

    verdict, moved = sf.state("thing.py", ["tests/test_thing.py"])

    assert verdict == "stale"
    assert moved == ["src/docxkit/thing.py"]


def test_a_HARNESS_that_moved_is_stale_too(tmp_path, monkeypatch):
    """The half this tool was written for: a test added after a run
    kills mutants the list still calls survivors."""
    sf = _session(tmp_path, monkeypatch, module_now="x = 1",
                  module_then="x = 1", test_now="t2", test_then="t")

    verdict, moved = sf.state("thing.py", ["tests/test_thing.py"])

    assert verdict == "stale"
    assert moved == ["tests/test_thing.py"]


def test_a_session_with_NO_snapshot_falls_back_to_timestamps(
        tmp_path, monkeypatch):
    """Eight of the fifty sessions here predate the snapshot mechanism.
    They cannot be answered by content, and the weaker rule is better
    than no answer."""
    import stale_figures as sf  # pyright: ignore[reportMissingImports]

    (tmp_path / "src" / "docxkit").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "docxkit" / "thing.py").write_text("x = 1")
    (tmp_path / "tests" / "test_thing.py").write_text("t")
    (tmp_path / ".mutation-thing.sqlite").write_text("")
    monkeypatch.setattr(sf, "ROOT", tmp_path)

    assert sf.moved_by_content("thing.py", ["tests/test_thing.py"]) is None
    # and `state` still answers rather than raising
    verdict, _moved = sf.state("thing.py", ["tests/test_thing.py"])
    assert verdict in {"fresh", "stale"}


def test_a_file_the_run_NEVER_HAD_is_a_difference_not_a_refusal(
        tmp_path, monkeypatch):
    """A run measured against a NARROWER harness than the question names
    leaves a snapshot that does not cover it — every `revision/` half is
    one since 2026-09-17, and `replay_survivors --tests` names such a
    file BY DESIGN: asking a stored survivor list against a different
    harness is what the flag is for.

    Answering None there voided the module comparison too, and the
    timestamp fallback then called the module moved (a commit re-dates
    every file), so the replay refused outright — measured on
    `revision/_gates.py` and `revision/_doctor.py`, both of which
    replayed fine against their own harness.

    The answer is `stale` NAMING the file: nothing reads `fresh` over a
    harness the run never used, and the question about the module is
    still answered.
    """
    sf = _session(tmp_path, monkeypatch, module_now="x = 1",
                  module_then="x = 1")

    verdict, moved = sf.state(
        "thing.py", ["tests/test_thing.py", "tests/test_other.py"])

    assert verdict == "stale"
    assert moved == ["tests/test_other.py"], (
        "the module and the file the run did have are unchanged")


def test_a_snapshot_without_the_MODULE_still_answers_nothing(tmp_path,
                                                             monkeypatch):
    """The module is what a survivor's line numbers index into, so its
    absence is the one that cannot be answered by content — the eight
    sessions here that predate the snapshot, and a pruned one."""
    sf = _session(tmp_path, monkeypatch, module_now="x = 1",
                  module_then="x = 1")
    (tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
     / "thing.py").unlink()

    assert sf.moved_by_content("thing.py", ["tests/test_thing.py"]) is None


# --- the harness a session was PLANNED with (2026-09-18) -------------------
#
# `state` above asks whether the module and the named tests have CHANGED.
# It cannot see the set of NAMES itself moving: a test added to the map
# after a run, or one the map has since dropped, leaves every file it
# compares untouched. The session records the command it was planned
# with, so the two lists can simply be compared. Three of this repo's 66
# configured sessions disagree with the map today, one of them in the
# direction that makes its figure an answer to a different question.

_COMMAND = ("python tools/mutant_tests.py --deadline 30 thing "
            "src/docxkit/thing.py -- -q -x tests/test_thing.py "
            "tests/test_other.py")
_CONFIG = ('[cosmic-ray]\n'
           'module-path = "src/docxkit/thing.py"\n'
           f'test-command = "{_COMMAND}"\n')


def _planned(tmp_path, monkeypatch, config: str = _CONFIG):
    import stale_figures  # pyright: ignore[reportMissingImports]

    if config:
        (tmp_path / ".mutation-thing.toml").write_text(config,
                                                       encoding="utf-8")
    monkeypatch.setattr(stale_figures, "ROOT", tmp_path)
    return stale_figures


def test_the_PLANNED_harness_is_read_out_of_the_session_config(tmp_path,
                                                               monkeypatch):
    """The test files are the only `tests/...py` words in the command —
    the rest is the interpreter, the wrapper, its deadline and pytest's
    own flags."""
    sf = _planned(tmp_path, monkeypatch)

    assert sf.planned_tests("thing.py") == ["tests/test_other.py",
                                            "tests/test_thing.py"]


def test_a_session_with_NO_config_beside_it_plans_nothing(tmp_path,
                                                          monkeypatch):
    """Sessions older than the config, and runs driven by hand. Not an
    error and not a drift: there is nothing to compare against."""
    sf = _planned(tmp_path, monkeypatch, config="")

    assert sf.planned_tests("thing.py") is None
    assert sf.drifted("thing.py", ["tests/test_thing.py"]) == ([], [])


def test_a_harness_that_GAINED_a_file_is_reported_as_ADDED(tmp_path,
                                                           monkeypatch):
    sf = _planned(tmp_path, monkeypatch)

    added, dropped = sf.drifted("thing.py", ["tests/test_thing.py",
                                             "tests/test_other.py",
                                             "tests/test_new.py"])

    assert (added, dropped) == (["tests/test_new.py"], [])


def test_a_harness_that_LOST_a_file_is_reported_as_DROPPED(tmp_path,
                                                           monkeypatch):
    """The direction that matters most: the figure was measured against
    a test this module's harness no longer names, so a replay today asks
    a different question than the session answered."""
    sf = _planned(tmp_path, monkeypatch)

    added, dropped = sf.drifted("thing.py", ["tests/test_thing.py"])

    assert (added, dropped) == ([], ["tests/test_other.py"])


def test_a_harness_that_has_not_moved_drifts_in_NEITHER_direction(
        tmp_path, monkeypatch):
    sf = _planned(tmp_path, monkeypatch)

    assert sf.drifted("thing.py", ["tests/test_other.py",
                                   "tests/test_thing.py"]) == ([], [])


def test_a_BACKSLASHED_test_path_is_the_SAME_file(tmp_path, monkeypatch):
    """The map is written with forward slashes and a Windows caller may
    hand over the other kind; a separator is not a difference between
    two harnesses."""
    sf = _planned(tmp_path, monkeypatch)
    windows = ["tests" + chr(92) + "test_thing.py",
               "tests" + chr(92) + "test_other.py"]

    assert sf.drifted("thing.py", windows) == ([], [])
