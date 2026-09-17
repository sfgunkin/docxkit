"""`tools/replay_survivors.py` — asking a survivor list again.

The bridge between the two halves that already existed: a session file
says what survived, and `kill_check` says whether one mutation still
does. What is worth pinning here is the arithmetic between them, because
it is silent when wrong — cosmic-ray numbers rows from 1, and an anchor
one line off does not fail, it mutates the NEXT statement and reports a
confident verdict about a mutation nobody made. The first draft did
exactly that, pairing a `continue` with `if tag is "equal":`.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is how its scripts are reached, here and by each other.
from replay_survivors import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    cases_for,
    source_moved,
)


def _session(tmp_path: Path, rows: list[tuple[int, str]]) -> Path:
    """A session file holding one SURVIVED row per (line, became)."""
    db = tmp_path / "session.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE mutation_specs (job_id TEXT, "
                "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    con.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
                "diff TEXT)")
    for i, (row, produced) in enumerate(rows):
        job = f"job{i}"
        con.execute("INSERT INTO mutation_specs VALUES (?, ?, 4, ?)",
                    (job, row, "core/ReplaceComparisonOperator_Eq_Is"))
        con.execute("INSERT INTO work_results VALUES (?, 'SURVIVED', ?)",
                    (job, f"--- a\n+++ b\n@@\n-was\n+{produced}\n"))
    con.commit()
    con.close()
    return db


SRC = '''def compare(tag):
    if tag == "equal":
        return 1
    return 0
'''


def test_the_anchor_is_the_line_the_mutation_was_ON(tmp_path):
    """Rows are 1-based. Treating them as 0-based anchors every case one
    line late, and every verdict it then reports is about a mutation the
    session never ran."""
    src = tmp_path / "compare.py"
    src.write_text(SRC, encoding="utf-8")
    db = _session(tmp_path, [(2, 'if tag is "equal":')])

    (case,) = cases_for(Path("compare.py"), db=db, src=src)
    _label, old, new, expect_kill, nth = case

    assert old == '    if tag == "equal":'
    assert new == '    if tag is "equal":', "indentation is carried over"
    assert expect_kill is True, "a survivor is replayed hoping it now dies"
    assert nth == 1


REPEATED = '''def compare(a, b):
    if a == b:
        return 1
    if a == b:
        return 2
    return 0
'''


def test_a_line_the_module_REPEATS_names_which_occurrence(tmp_path):
    """`kill_check` skips an ambiguous anchor rather than mutating the
    wrong one, so a survivor on a repeated line goes unanswered unless
    the occurrence is computed. Thirteen of `_compare_diff`'s sixty were
    lost that way on the first pass."""
    src = tmp_path / "repeated.py"
    src.write_text(REPEATED, encoding="utf-8")
    db = _session(tmp_path, [(4, "if a is b:")])

    (case,) = cases_for(Path("repeated.py"), db=db, src=src)

    assert case[1] == "    if a == b:"
    assert case[4] == 2, "the SECOND one is the one that was mutated"


SHADOWED = '''def compare(a, b):
    if a:
        if a == b:
            return 1
    if a == b:
        return 2
    return 0
'''


def test_a_line_repeated_DEEPER_first_is_still_the_first_of_its_kind(
        tmp_path):
    """The occurrence is counted the way `kill_check` counts, as WHOLE
    lines. Counted as a substring, `    if a == b:` also sits inside the
    deeper `        if a == b:` above it, the case asks for the second
    of one, and `kill_check` skips it: four of `revision/_gates.py`'s
    eleven went unanswered that way on 2026-09-14."""
    from kill_check import _places  # pyright: ignore[reportMissingImports]

    src = tmp_path / "shadowed.py"
    src.write_text(SHADOWED, encoding="utf-8")
    db = _session(tmp_path, [(5, "if a is b:")])

    (case,) = cases_for(Path("shadowed.py"), db=db, src=src)
    old, nth = case[1], case[4]

    assert old == "    if a == b:"
    assert nth == 1
    row_5 = SHADOWED.index("\n    if a == b:") + 1
    assert _places(SHADOWED, old)[nth - 1] == row_5, \
        "the case lands on the line the mutation was on"


def test_a_mutation_that_changes_NOTHING_is_not_replayed(tmp_path):
    """`kill_check` rewrites the file with itself for such a case, the
    suite passes, and it reports SURVIVED — a missing test where there
    is none. It guards that itself; this drops the case earlier, so the
    count of what was replayed stays honest."""
    src = tmp_path / "compare.py"
    src.write_text(SRC, encoding="utf-8")
    db = _session(tmp_path, [(2, 'if tag == "equal":')])

    assert cases_for(Path("compare.py"), db=db, src=src) == []


def test_a_session_that_graded_NOTHING_yields_no_cases(tmp_path):
    """A run killed before its first result. `classify` answers None,
    and a caller that indexed into it would raise instead of saying
    there is nothing on record."""
    src = tmp_path / "compare.py"
    src.write_text(SRC, encoding="utf-8")

    assert cases_for(Path("compare.py"), db=_session(tmp_path, []),
                     src=src) == []


def test_a_moved_TEST_file_is_what_replaying_is_for():
    """The whole point: the harness caught up, the list did not."""
    assert not source_moved(Path("src/docxkit/guard.py"),
                            ["tests/test_tracked_guard.py"])


def test_a_moved_SOURCE_file_means_re_sweep_not_replay():
    """A survivor is a line number. Once the module has moved they are
    line numbers into a file that no longer has those lines, and the
    anchors either miss or — worse — match a line that shifted
    underneath them, which is a confident verdict about a mutation the
    session never ran.

    Written as a test because the comparison is the kind that silently
    never fires: `state` reports POSIX-relative paths and
    `str(Path(...))` on Windows is backslashed, so the obvious spelling
    is a guard that is always False on the platform this is developed
    on.
    """
    assert source_moved(Path("src/docxkit/guard.py"),
                        ["src/docxkit/guard.py"])
    assert source_moved(Path("src/docxkit/guard.py"),
                        ["tests/test_tracked_guard.py",
                         "src/docxkit/guard.py"])
    assert not source_moved(Path("src/docxkit/guard.py"),
                            ["tests/test_guard.py"]), (
        "a test file whose name ENDS with the module's is not the module")


# --- asking the list against ANOTHER harness, which is what `--tests` is --


def _tree(tmp_path, monkeypatch, *, module_now="x = 1", module_then="x = 1"):
    """A measured module with a snapshot that holds ONE of two test files.

    Which is every narrowed harness: a session is a photograph of the
    files it ran, and `--tests` exists to ask its list against others.
    """
    import replay_survivors as rs  # pyright: ignore[reportMissingImports]
    import stale_figures as sf  # pyright: ignore[reportMissingImports]

    (tmp_path / "src" / "docxkit").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "docxkit" / "thing.py").write_text(module_now)
    for name in ("test_thing.py", "test_other.py"):
        (tmp_path / "tests" / name).write_text("t")
    (tmp_path / ".mutation-thing.sqlite").write_text("")

    kept = tmp_path / ".mutation-thing.pristine"
    (kept / "src" / "docxkit").mkdir(parents=True)
    (kept / "tests").mkdir(parents=True)
    (kept / "src" / "docxkit" / "thing.py").write_text(module_then)
    (kept / "tests" / "test_thing.py").write_text("t")

    monkeypatch.setattr(sf, "ROOT", tmp_path)
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    monkeypatch.setattr(rs, "cases_for",
                        lambda module, *named: [("L2 Eq_Is", "x = 1", "x = 2",
                                                 True, 1)])
    return rs


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["replay_survivors.py", *args])


def test_a_TEST_FILE_the_run_NEVER_HAD_is_replayed_not_refused(
        tmp_path, monkeypatch, capsys):
    """The flag's whole purpose, and it could not do it.

    A snapshot holds the harness of its day, so naming any other file —
    what `--tests` is for — made `moved_by_content` answer None, and the
    timestamp fallback then called the MODULE moved, because a commit
    re-dates every file. The replay refused outright. Measured
    2026-09-17 while narrowing the `revision/` halves: `_gates` and
    `_doctor` both replayed against their own harness and refused
    against the superset, and the comparison had to be done by hand.
    """
    rs = _tree(tmp_path, monkeypatch)
    ran: list[list[str]] = []

    def check(module: str, tests: list[str], cases: list[object]) -> int:
        ran.append(tests)
        return 0

    monkeypatch.setattr(rs, "check", check)
    _argv(monkeypatch, "src/docxkit/thing.py", "--tests",
          "tests/test_thing.py", "tests/test_other.py")

    assert rs.main() == 0
    assert ran == [["tests/test_thing.py", "tests/test_other.py"]]
    out = capsys.readouterr().out
    assert "REFUSING" not in out
    # and it still says the harness is not the one measured
    assert "the run is stale" in out and "tests/test_other.py" in out


def test_a_moved_MODULE_refuses_however_the_harness_is_named(
        tmp_path, monkeypatch, capsys):
    """The refusal this must not cost: the survivors are line numbers
    into a file that no longer has those lines, and `--tests` says
    nothing about that."""
    rs = _tree(tmp_path, monkeypatch, module_now="x = 9",
               module_then="x = 1")
    monkeypatch.setattr(rs, "check", lambda *a: 0)
    _argv(monkeypatch, "src/docxkit/thing.py", "--tests",
          "tests/test_thing.py", "tests/test_other.py")

    assert rs.main() == 2
    assert "REFUSING" in capsys.readouterr().out


# --- a module in a SUBPACKAGE (BACKLOG, 2026-09-13) ---------------------
#
# `revision/_timing.py` was read as `_timing.py`: "the run is never
# measured", then a crash on `.mutation-timing.sqlite`, while
# `.mutation-revision_timing.sqlite` sat beside it. `revision/_ingest.py`
# read as `_ingest.py` resolves to the flat `ingest.py`'s session.


def test_a_module_is_KEYED_by_its_path_under_the_package():
    from replay_survivors import (  # pyright: ignore[reportMissingImports]
        module_key,
    )

    assert module_key(Path("src/docxkit/revision/_timing.py")) == \
        "revision/_timing.py"
    assert module_key(Path("D:/docxkit/src/docxkit/guard.py")) == "guard.py"
    assert module_key(Path("compare.py")) == "compare.py"


def test_the_session_read_for_a_SUBPACKAGE_half_is_its_own(monkeypatch):
    import replay_survivors as rs  # pyright: ignore[reportMissingImports]

    read: list[str] = []

    def classify(db: str, src: str) -> None:
        read.append(Path(db).name)

    monkeypatch.setattr(rs, "classify", classify)

    assert rs.cases_for(Path("src/docxkit/revision/_timing.py")) == []
    assert read == [".mutation-revision_timing.sqlite"]


def test_main_asks_the_harness_and_the_run_by_that_same_KEY(monkeypatch,
                                                             capsys):
    import replay_survivors as rs  # pyright: ignore[reportMissingImports]

    asked: list[tuple[str, str]] = []

    def harness_for(key: str) -> list[str]:
        asked.append(("harness", key))
        return ["tests/test_revision.py"]

    def state(key: str, tests: list[str]) -> tuple[str, list[str]]:
        asked.append(("state", key))
        return "fresh", []

    monkeypatch.setattr(rs, "harness_for", harness_for)
    monkeypatch.setattr(rs, "state", state)
    monkeypatch.setattr(rs, "cases_for", lambda module, *named: [])
    monkeypatch.setattr(sys, "argv", ["replay_survivors.py",
                                      "src/docxkit/revision/_timing.py"])

    assert rs.main() == 0
    assert asked == [("harness", "revision/_timing.py"),
                     ("state", "revision/_timing.py")]
    assert "revision/_timing.py: the run is fresh" in capsys.readouterr().out


def test_a_moved_SUBPACKAGE_half_is_known_by_its_folder_too():
    half = Path("src/docxkit/revision/_ingest.py")

    assert source_moved(half, ["src/docxkit/revision/_ingest.py"])
    assert not source_moved(half, ["src/docxkit/_ingest.py"]), (
        "a file of the same name OUTSIDE its folder is another module")


# --- a session that is not beside this tree (2026-09-18) ----------------
#
# The campaign's ordinary shape: the tests being replayed are on a branch
# in a worktree, and the session that measured the module is in the
# checkout it was measured in. A worktree holds neither the session nor
# its snapshot, so the tool died on `no session at
# <worktree>/.mutation-<stem>.sqlite` — and the two people who copied the
# session in met the next wall, a refusal saying the module had moved
# when it had not: `git worktree add` stamps every file's mtime to now.


def _elsewhere(tmp_path: Path, *, snapshot: bool = True) -> Path:
    """A session in ANOTHER checkout, optionally with its snapshot."""
    other = tmp_path / "other-checkout"
    other.mkdir()
    db = other / ".mutation-thing.sqlite"
    db.write_text("")
    if snapshot:
        kept = other / ".mutation-thing.pristine" / "src" / "docxkit"
        kept.mkdir(parents=True)
        (kept / "thing.py").write_text("x = 1")
    return db


def test_a_session_ELSEWHERE_is_named_rather_than_copied(
        tmp_path, monkeypatch, capsys):
    """`--db`: the session the branch's tests are replayed against lives
    in the checkout that measured it. `cases_for` took a `db` and a
    `src` from the day it was written — "for a test, which cannot use
    this repo's own session" — and the command line did not pass them
    on, so every caller outside this repo's own tree wrote the same
    twelve-line script instead."""
    rs = _tree(tmp_path, monkeypatch)
    (tmp_path / ".mutation-thing.sqlite").unlink()   # a fresh worktree
    db = _elsewhere(tmp_path)
    asked: list[tuple[object, ...]] = []

    def cases_for(module: Path, *named: object) -> list[object]:
        asked.append(named)
        return [("L1", "x = 1", "x = 2", True, 1)]

    monkeypatch.setattr(rs, "cases_for", cases_for)
    monkeypatch.setattr(rs, "check", lambda *a: 0)
    _argv(monkeypatch, "src/docxkit/thing.py", "--db", str(db))

    assert rs.main() == 0

    assert asked == [(db, None)], "the session named is the one replayed"
    out = capsys.readouterr().out
    assert "REFUSING" not in out
    assert "named on the command line" in out and str(db) in out


def test_a_WORKTREES_fresh_mtimes_are_not_a_moved_module(
        tmp_path, monkeypatch, capsys):
    """The false refusal, and the half that matters most.

    Nothing here has changed: the module is byte for byte the source the
    run measured. Only the timestamps say otherwise, because every file
    in a new worktree was written a moment ago — so the answer has to
    come from the BYTES, which is the rule `moved_by_content` already
    applies to the sessions `state` can see.
    """
    rs = _tree(tmp_path, monkeypatch)
    (tmp_path / ".mutation-thing.sqlite").unlink()
    (tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
     / "thing.py").unlink()                          # no snapshot here
    db = _elsewhere(tmp_path)
    monkeypatch.setattr(rs, "state", lambda key, tests: (
        "stale", ["src/docxkit/thing.py"]))
    monkeypatch.setattr(rs, "check", lambda *a: 0)
    _argv(monkeypatch, "src/docxkit/thing.py", "--db", str(db))

    assert rs.main() == 0, "the module is unchanged; only its mtime moved"
    assert "REFUSING" not in capsys.readouterr().out


def test_a_module_that_REALLY_moved_still_refuses_and_says_by_what(
        tmp_path, monkeypatch, capsys):
    """The refusal is worth a false one and never a false pass: replaying
    a list against a moved module grades mutations nobody made. So the
    bytes deciding the easy case must not soften the real one."""
    rs = _tree(tmp_path, monkeypatch, module_now="x = 9")
    (tmp_path / ".mutation-thing.sqlite").unlink()
    db = _elsewhere(tmp_path)                        # snapshot says x = 1
    monkeypatch.setattr(rs, "check", lambda *a: 0)
    _argv(monkeypatch, "src/docxkit/thing.py", "--db", str(db))

    assert rs.main() == 2

    out = capsys.readouterr().out
    assert "REFUSING" in out and "by bytes" in out
    assert "mutation_session.py" in out, "and what to do instead"


def test_with_NOTHING_to_compare_against_it_refuses_by_TIMESTAMPS_and_says_so(
        tmp_path, monkeypatch, capsys):
    """The runs that predate the snapshot mechanism, and a session handed
    over without its folder. The verdict is then a timestamp's, which is
    exactly the one that is wrong in a worktree — so the message names
    the cause and the way through instead of leaving a wall."""
    rs = _tree(tmp_path, monkeypatch)
    (tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
     / "thing.py").unlink()
    monkeypatch.setattr(rs, "state", lambda key, tests: (
        "stale", ["src/docxkit/thing.py"]))
    monkeypatch.setattr(rs, "check", lambda *a: 0)
    _argv(monkeypatch, "src/docxkit/thing.py")

    assert rs.main() == 2

    out = capsys.readouterr().out
    assert "by timestamps" in out
    assert "git worktree add" in out, "the cause of the false refusal"
    assert "--db" in out and "--src" in out, "and the way past it"


def test_a_snapshot_written_CRLF_is_the_same_module_as_one_written_LF(
        tmp_path, monkeypatch, capsys):
    """The second false refusal, and the one that actually fired here.

    Git for Windows sets `core.autocrlf=true` in its SYSTEM config, so
    `git worktree add` wrote CRLF while D:/docxkit was LF, and a
    `.pristine` snapshot taken in one disagrees with the other about
    every line of every module. `.gitattributes` pins `eol=lf` from
    2026-09-18 on; every session measured before that is still on the
    other side of it. A row number and the text of a row are what a
    survivor is, and neither changes with the line ending.
    """
    rs = _tree(tmp_path, monkeypatch)
    (tmp_path / ".mutation-thing.sqlite").unlink()
    # written as BYTES on both sides: `write_text` on Windows would
    # translate the newlines and the two files would agree by accident
    (tmp_path / "src" / "docxkit" / "thing.py").write_bytes(b"x = 1\ny = 2\n")
    db = _elsewhere(tmp_path, snapshot=False)
    kept = db.with_suffix(".pristine") / "src" / "docxkit"
    kept.mkdir(parents=True)
    (kept / "thing.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    monkeypatch.setattr(rs, "check", lambda *a: 0)
    _argv(monkeypatch, "src/docxkit/thing.py", "--db", str(db))

    assert rs.main() == 0
    assert "REFUSING" not in capsys.readouterr().out


def test_the_source_the_run_measured_is_NAMED_then_KEPT_then_neither(
        tmp_path, monkeypatch):
    """Where `--src` sits among the answers: what the caller names beats
    the copy beside the session, which beats the copy beside this tree's
    own session, and none of the three is not an error — it is the
    timestamp fallback, said out loud."""
    rs = _tree(tmp_path, monkeypatch)
    db = _elsewhere(tmp_path)
    named = tmp_path / "named.py"
    named.write_text("x = 1")

    assert rs.measured_source("thing.py", db, named) == named
    assert rs.measured_source("thing.py", db) == (
        db.with_suffix(".pristine") / "src" / "docxkit" / "thing.py")
    assert rs.measured_source("thing.py") == (
        tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
        / "thing.py"), "this tree's own snapshot, when no session is named"

    (tmp_path / ".mutation-thing.pristine" / "src" / "docxkit"
     / "thing.py").unlink()
    assert rs.measured_source("thing.py") is None
