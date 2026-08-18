"""`tools/mutation_survivors.py` against a console that is not UTF-8.

The report quotes the SOURCE LINE each surviving mutant sits on, which
is the whole reason it is readable — "L188, the glyph table" is an
answer and "L188" is not. It also means the tool prints characters it
did not choose: `_table_layout.py` lays out en dash, curly quotes and
the typographic minus by width, and `_compare_read.py` parses the glyphs
Word emits.

A Windows console is cp1252 and cannot encode any of them. The failure
is late and partial — the list prints down to the first offending line
and the `by definition:` tally at the end, which is what a round picks
its next tests from, never prints at all.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOL = (Path(docxkit.__file__).resolve().parents[2]
        / "tools" / "mutation_survivors.py")

# U+2212 on the surviving line, U+2013 on another: the two the glyph
# table carries, and neither survives the trip through cp1252.
MODULE = '''\
"""A module the report has to quote."""
WIDTHS = {564: "+<=>\u2212", 500: "abc\u2013"}


def widen(x: int) -> int:
    return x + 1
'''


def _database(path: Path, *rows: tuple[int, str]) -> Path:
    """A cosmic-ray database holding just what the report reads."""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE mutation_specs (job_id TEXT, "
               "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    db.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT)")
    for i, (row, outcome) in enumerate(rows):
        job = f"job{i}"
        db.execute("INSERT INTO mutation_specs VALUES (?, ?, ?, ?)",
                   (job, row, 0, "core/NumberReplacer"))
        db.execute("INSERT INTO work_results VALUES (?, ?)", (job, outcome))
    db.commit()
    db.close()
    return path


def _report(tmp_path: Path, encoding: str) -> subprocess.CompletedProcess[str]:
    src = tmp_path / "widths.py"
    src.write_text(MODULE, encoding="utf-8")
    db = _database(tmp_path / "run.sqlite", (2, "SURVIVED"), (6, "KILLED"))
    return subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": encoding})


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
def test_the_report_survives_a_console_that_cannot_hold_the_source(
        tmp_path, encoding):
    """Every survivor AND the tally, whatever the console claims to be.
    `console.utf8_stdout()` replaces the characters it cannot map, so an
    ascii console loses the glyph and keeps the report."""
    done = _report(tmp_path, encoding)

    assert done.returncode == 0, done.stderr
    assert "L2" in done.stdout
    assert "REAL SURVIVAL 50.0% (1/2)" in done.stdout
    assert "by definition:" in done.stdout, "the tally is the point of it"


def test_a_utf8_console_still_gets_the_characters_themselves(tmp_path):
    """The replacement is the fallback, not the behaviour: where the
    console can hold the minus sign it is printed as written."""
    done = _report(tmp_path, "utf-8")

    assert "\u2212" in done.stdout
