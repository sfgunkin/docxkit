"""`tools/unobservable.py` — the lines where every mutant survived.

Killable, equivalent and cosmetic all assume the line can DO something.
The fourth answer — a line, or a part of one, whose effect is fixed by a
caller or a callee rather than by the input — was found by hand three
times on 2026-09-18, each time after an hour of reasoning that the
session files already held.

What is tested here is the SIGNATURE and what it refuses to flatten: a
sub-expression rather than a row (two of those three sit on lines that
do act), a cluster inside a message named as the different question it
is, and nothing subtracted in silence.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the insert above is
# how its scripts reach each other, and how they are reached here.
import unobservable  # noqa: E402  # pyright: ignore[reportMissingImports]

MODULE = '''
def guard(items, end, le):
    """Two questions on one line: one answerable, one not."""
    after = "" if end >= le else items
    if end >= le and not after:
        after = ""
    return f"kept {len(items) - 1} of them"
'''


def _session(tmp_path: Path, rows: list[tuple[int, int, str, str, str]],
             module: str = "thing.py") -> Path:
    """A synthetic run: `(row, col, operator, outcome, mutant line)`."""
    src = tmp_path / "src" / "docxkit"
    src.mkdir(parents=True, exist_ok=True)
    (src / module).write_text(MODULE, encoding="utf-8")
    db = tmp_path / f".mutation-{module.removesuffix('.py')}.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE mutation_specs (job_id TEXT, start_pos_row INT, "
                "start_pos_col INT, operator_name TEXT)")
    con.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
                "diff TEXT)")
    for n, (row, col, operator, outcome, line) in enumerate(rows):
        diff = f"--- a\n+++ b\n@@ -1 +1 @@\n-old\n+{line}\n"
        con.execute("INSERT INTO mutation_specs VALUES (?, ?, ?, ?)",
                    (f"j{n}", row, col, operator))
        con.execute("INSERT INTO work_results VALUES (?, ?, ?)",
                    (f"j{n}", outcome, diff))
    con.commit()
    con.close()
    return db


@pytest.fixture
def world(tmp_path, monkeypatch):
    """The tool pointed at a synthetic checkout rather than the real one."""
    monkeypatch.setattr(unobservable, "SESSIONS", tmp_path)
    monkeypatch.setattr(unobservable, "state",
                        lambda *a, **k: ("fresh", []))
    monkeypatch.setattr(unobservable, "harness_for", lambda module: [])
    return tmp_path


def test_a_SUB_EXPRESSION_that_never_dies_is_found_inside_a_line_that_acts(
        world):
    """The correction the tool's first run earned. Two of the three
    known instances sit on lines that DO act — 23 kills on one of them —
    and only a part of them cannot. Keyed on the row alone, both are
    invisible; keyed on the column cosmic-ray records, both are found.
    """
    _session(world, [
        (5, 20, "ReplaceComparisonOperator_GtE_Gt", "SURVIVED",
         "    if end > le and not after:"),
        (5, 20, "ReplaceComparisonOperator_GtE_Eq", "SURVIVED",
         "    if end == le and not after:"),
        (5, 35, "ReplaceTrueFalse", "KILLED", "    if end >= le and after:"),
    ])
    dropped = unobservable.Dropped()

    found = unobservable.clusters_in("thing.py", 2, dropped)

    assert len(found) == 1
    assert (found[0].line, found[0].col) == (5, 20)
    assert found[0].survived == 2
    assert found[0].killed_here == 1, "the rest of the line does act"
    assert found[0].owner == "guard"


def test_a_sub_expression_with_a_KILL_of_its_own_is_not_a_cluster(world):
    """It can act, which is the whole question. One kill at the same
    column is enough to answer it."""
    _session(world, [
        (5, 20, "A", "SURVIVED", "    if end > le and not after:"),
        (5, 20, "B", "SURVIVED", "    if end == le and not after:"),
        (5, 20, "C", "KILLED", "    if end < le and not after:"),
    ])
    dropped = unobservable.Dropped()

    assert unobservable.clusters_in("thing.py", 2, dropped) == []
    assert dropped.mixed == 1, "and it says so rather than dropping it quietly"


def test_a_cluster_inside_a_MESSAGE_is_named_as_the_other_question(world):
    """`f"kept {len(items) - 1} of them"` — an arithmetic any test that
    read the message could tell apart, and none does. That is the
    cosmetic answer, not an unobservable line, and on the first whole
    run five such clusters took the top of the ranking."""
    kept = '    return f"kept {len(items) %s 1} of them"'
    _session(world, [
        (7, 25, "A", "SURVIVED", kept % "+"),
        (7, 25, "B", "SURVIVED", kept % "*"),
    ])
    dropped = unobservable.Dropped()

    (found,) = unobservable.clusters_in("thing.py", 2, dropped)

    assert found.in_message
    assert "in a MESSAGE" in found.show()


def test_what_is_discounted_is_COUNTED(world, capsys):
    """A filter that removes the interesting case without saying so is
    the shape this campaign keeps meeting."""
    _session(world, [
        (5, 20, "A", "SURVIVED", "    if end > le and not after:"),
        (5, 20, "B", "SURVIVED", "    if end == le and not after:"),
        (5, 20, "C", "KILLED", "    if end < le and not after:"),
    ])

    unobservable.report(["thing.py"], 2)

    said = capsys.readouterr().out
    assert "discounted:" in said
    assert "1 line(s) had a kill as well" in said


def test_the_report_says_a_cluster_is_a_CANDIDATE(world, capsys):
    """The sentence belongs where a hurried reader meets it, which is
    the report rather than the docstring."""
    _session(world, [
        (5, 20, "A", "SURVIVED", "    if end > le and not after:"),
        (5, 20, "B", "SURVIVED", "    if end == le and not after:"),
    ])

    unobservable.report(["thing.py"], 2)

    said = capsys.readouterr().out
    assert "CANDIDATE, not a verdict" in said
    assert "CALLEE" in said, "and what tells the two apart"
