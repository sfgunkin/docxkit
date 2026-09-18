"""`tools/render_survivors.py` — a survivor list against today's file.

The tool exists for the case `replay_survivors` refuses: a module that
has moved since its session was planned. Replaying a stored diff there
grades a mutation nobody made, so the refusal is right — and it left
three rounds in one day choosing between an hour of re-sweeping and
working blind.

What is worth pinning is the part that is silent when wrong. An
occurrence is a position in the list of an operator's sites, so an edit
that adds or removes one makes occurrence N name a different place, and
a tool that rendered it anyway would produce a confident case about
another mutant entirely. Every mutant is therefore rebuilt against the
SNAPSHOT first and held to what the session recorded for it.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

import docxkit

# The tool is `mutate_code` and `get_operator` and little else, so it
# cannot be imported without them. cosmic-ray is in no extra — it lives
# on the machine that runs the sweeps — and CI went red on
# `ModuleNotFoundError` the day this file landed. A skip is honest here:
# the tool only ever runs where a SESSION exists, and a session only
# exists where cosmic-ray planned it.
pytest.importorskip("cosmic_ray",
                    reason="cosmic-ray is a sweep-machine dependency")

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is how its scripts are reached, here and by each other.
from render_survivors import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    main,
    survivors,
)

_EQ = "core/ReplaceComparisonOperator_Eq_Is"

#: the module as the run saw it
THEN = 'def compare(tag):\n    if tag == "equal":\n        return 1\n'

#: and with three lines added above it since
NOW = ('"""Added since the run."""\n\n\n'
       'def compare(tag):\n    if tag == "equal":\n        return 1\n')


def _session(tmp_path: Path, then: str, *,
             rows: list[tuple[int, int, str, int, str, str]]) -> Path:
    """A session file and its snapshot of `then`.

    Each row is `(line, column, operator, occurrence, outcome, produced)`
    — the columns this tool reads, which include the two
    `replay_survivors` has no use for: cosmic-ray records WHICH
    application of the operator a mutant is, and that is what makes it
    re-appliable to a file that has changed.
    """
    db = tmp_path / ".mutation-compare.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE mutation_specs (job_id TEXT, "
                "start_pos_row INT, start_pos_col INT, operator_name TEXT, "
                "occurrence INT, operator_args TEXT)")
    con.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
                "diff TEXT)")
    for i, (row, col, operator, occurrence, outcome, produced) in enumerate(
            rows):
        job = f"job{i}"
        con.execute("INSERT INTO mutation_specs VALUES (?, ?, ?, ?, ?, ?)",
                    (job, row, col, operator, occurrence, '"{}"'))
        con.execute("INSERT INTO work_results VALUES (?, ?, ?)",
                    (job, outcome, f"--- a\n+++ b\n@@\n-was\n+{produced}\n"))
    con.commit()
    con.close()
    kept = tmp_path / ".mutation-compare.pristine" / "src" / "docxkit"
    kept.mkdir(parents=True)
    (kept / "compare.py").write_text(then, encoding="utf-8")
    return db


def _live(tmp_path: Path, now: str) -> Path:
    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True, exist_ok=True)
    path = src / "compare.py"
    path.write_text(now, encoding="utf-8")
    return path


def test_a_survivor_is_rebuilt_where_the_line_stands_TODAY(tmp_path):
    """The whole point: the run had it at line 2, the file has three
    lines of docstring in front of it now, and the case has to anchor on
    line 5 — with the mutation cosmic-ray's own operator produces, not a
    stored diff pasted onto a moved line."""
    db = _session(tmp_path, THEN, rows=[
        (2, 7, _EQ, 0, "SURVIVED", 'if tag is "equal":')])
    src = _live(tmp_path, NOW)

    rendered, problems = survivors(Path("src/docxkit/compare.py"),
                                   db=db, src=src)

    assert problems == []
    (one,) = rendered
    assert (one.row, one.run_row) == (5, 2)
    assert one.old == '    if tag == "equal":', "indentation is carried over"
    assert one.new == '    if tag is "equal":'
    assert one.was is None, "the line itself has not changed"


def test_a_line_that_has_CHANGED_is_rendered_and_SAID_to_have_changed(
        tmp_path):
    """The case this is usually reached for: a round gives a repeated
    line a trailing comment so a claim can anchor on it, and the session
    then holds a rendering that no longer exists anywhere. The mutation
    is still the mutation, so it is rendered — and the reader is told,
    because they are the one who can judge whether the line still means
    what it meant."""
    db = _session(tmp_path, THEN, rows=[
        (2, 7, _EQ, 0, "SURVIVED", 'if tag is "equal":')])
    src = _live(tmp_path, THEN.replace('"equal":',
                                       '"equal":   # the only one'))

    (one,), problems = survivors(Path("src/docxkit/compare.py"),
                                 db=db, src=src)

    assert problems == []
    assert one.new == '    if tag is "equal":   # the only one'
    assert one.was == 'if tag == "equal":', "what the run had, for the reader"


def test_a_pair_that_NO_LONGER_REPRODUCES_its_record_is_refused(tmp_path):
    """The silent failure this tool could have. An occurrence is a
    position in the operator's sites, so an edit that adds or removes
    one makes it name a different place — and rendering it anyway gives
    a confident case about another mutant. Every one is rebuilt against
    the snapshot first and held to what the session recorded; this one
    recorded `!=`, which `Eq_Is` does not produce."""
    db = _session(tmp_path, THEN, rows=[
        (2, 7, _EQ, 0, "SURVIVED", 'if tag != "equal":')])
    src = _live(tmp_path, NOW)

    rendered, problems = survivors(Path("src/docxkit/compare.py"),
                                   db=db, src=src)

    assert rendered == []
    assert len(problems) == 1
    assert "no longer reproduces" in problems[0]
    assert "not rendered" in problems[0], "and it says what it did about it"


def test_the_OCCURRENCE_decides_which_of_two_identical_lines(tmp_path):
    """Two lines a file repeats are one anchor to `kill_check`, which
    takes an occurrence for exactly this reason. The second site must
    render as the second line, not the first."""
    twice = ('def compare(tag, other):\n'
             '    if tag == "equal":\n'
             '        return 1\n'
             '    if tag == "equal":\n'
             '        return 2\n')
    db = _session(tmp_path, twice, rows=[
        (4, 7, _EQ, 1, "SURVIVED", 'if tag is "equal":')])
    src = _live(tmp_path, twice)

    (one,), problems = survivors(Path("src/docxkit/compare.py"),
                                 db=db, src=src)

    assert problems == []
    assert (one.row, one.nth) == (4, 2), "the second copy of that line"


def test_a_mutant_the_run_KILLED_is_not_in_the_list(tmp_path):
    """The list is survivors. A killed mutant rendered beside them reads
    as work to do that was done."""
    db = _session(tmp_path, THEN, rows=[
        (2, 7, _EQ, 0, "KILLED", 'if tag is "equal":')])
    src = _live(tmp_path, NOW)

    rendered, problems = survivors(Path("src/docxkit/compare.py"),
                                   db=db, src=src)

    assert (rendered, problems) == ([], [])


def test_the_tool_EXITS_NON_ZERO_when_a_mutant_could_not_be_rebuilt(
        tmp_path, monkeypatch, capsys):
    """A hole in the answer is not a detail: the list reads as complete
    either way, so the exit code is what says it is not."""
    import render_survivors  # pyright: ignore[reportMissingImports]

    db = _session(tmp_path, THEN, rows=[
        (2, 7, _EQ, 0, "SURVIVED", 'if tag != "equal":')])
    _live(tmp_path, NOW)
    monkeypatch.setattr(render_survivors, "ROOT", tmp_path)
    monkeypatch.setattr(render_survivors, "session_file", lambda key: db)

    code = main(["src/docxkit/compare.py"])
    out = capsys.readouterr().out

    assert code == 1
    assert "no longer reproduces" in out
    assert "0 survivor(s) rebuilt" in out


def test_a_module_with_NO_session_is_refused_and_nothing_is_created(
        tmp_path, monkeypatch, capsys):
    """`sqlite3.connect` CREATES a missing file, so the refusal comes
    before anything opens it — `mutation_survivors`' rule, and the
    defect that put three 0-byte sessions in the repo root."""
    import render_survivors  # pyright: ignore[reportMissingImports]

    _live(tmp_path, NOW)
    missing = tmp_path / ".mutation-compare.sqlite"
    monkeypatch.setattr(render_survivors, "ROOT", tmp_path)
    monkeypatch.setattr(render_survivors, "session_file", lambda key: missing)

    code = main(["src/docxkit/compare.py"])

    assert code == 2
    assert "nothing was created" in capsys.readouterr().out
    assert not missing.exists()
