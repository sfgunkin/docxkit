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
    monkeypatch.setattr(rs, "cases_for", lambda module: [])
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
