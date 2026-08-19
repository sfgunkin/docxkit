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


def _database(path: Path, *rows: tuple[int, str] | tuple[int, str, int],
              ) -> Path:
    """A cosmic-ray database holding just what the report reads.

    A row is (line, outcome) or, where the COLUMN is what the report
    classifies on, (line, outcome, column).
    """
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE mutation_specs (job_id TEXT, "
               "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    db.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT)")
    for i, spec in enumerate(rows):
        row, outcome, col = (*spec, 0)[:3] if len(spec) == 2 else spec
        job = f"job{i}"
        db.execute("INSERT INTO mutation_specs VALUES (?, ?, ?, ?)",
                   (job, row, col, "core/NumberReplacer"))
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


SCRIPT = '''\
"""A module that can also be run as a script."""


def widen(x: int) -> int:
    return x + 1


if __name__ == "__main__":
    raise SystemExit(widen(1))
'''


def _script_report(tmp_path: Path, *rows: tuple[int, str]):
    src = tmp_path / "runnable.py"
    src.write_text(SCRIPT, encoding="utf-8")
    db = _database(tmp_path / "run.sqlite", *rows)
    return subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_the_script_guard_is_not_counted_as_a_gap(tmp_path):
    """`if __name__ == "__main__":` and its body cannot be reached by a
    test run, which IMPORTS the module: `__name__` is the dotted name,
    so the guard is False however the comparison is mutated and the body
    never runs. Counted as real, every module with a `main()` carries
    two or three permanent survivors, and a reader who cannot tell those
    from a missing test stops reading the number — which is the reason
    this tool exists."""
    done = _script_report(tmp_path, (8, "SURVIVED"), (9, "SURVIVED"),
                          (5, "KILLED"))

    assert done.returncode == 0, done.stderr
    assert "2 are inside" in done.stdout
    assert "REAL SURVIVAL 0.0% (0/1)" in done.stdout, done.stdout
    assert "L8" not in done.stdout and "L9" not in done.stdout


def test_a_survivor_OUTSIDE_the_guard_is_still_a_gap(tmp_path):
    """The classification is a span, not the whole file: the same module
    reports its ordinary survivor, and reports it alone."""
    done = _script_report(tmp_path, (5, "SURVIVED"), (9, "SURVIVED"))

    assert "1 is inside" in done.stdout, "one, and it says so in English"
    assert "REAL SURVIVAL 100.0% (1/1)" in done.stdout, done.stdout
    assert "L5" in done.stdout

SIGNATURES = '''\
"""A module whose functions take keyword-only arguments."""


def widen(x: int, *, by: int = 1) -> int:
    return x + by


def scale(x: int, factor: int = 2 * 3, *, twice: bool = False) -> int:
    return x * factor
'''


def _signature_report(tmp_path: Path,
                      *rows: tuple[int, str] | tuple[int, str, int]):
    src = tmp_path / "kwonly.py"
    src.write_text(SIGNATURES, encoding="utf-8")
    db = _database(tmp_path / "run.sqlite", *rows)
    return subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_the_keyword_only_marker_is_counted_apart(tmp_path):
    """`*` mutated to `/` makes the parameters before it positional-only.
    Nothing this package calls changes meaning — the arguments after the
    marker were keyword-only already and the ones before are passed
    positionally — so the mutant survives every suite, one per
    keyword-only signature. Fifty-six of them stood in the sixth
    sweep's lists, which is enough to move every module's figure.

    Counted apart from the annotations rather than with them: a reader
    may decide a public function's calling convention IS a contract."""
    marker = SIGNATURES.splitlines()[3].index("*")     # `def widen(...)`
    done = _signature_report(tmp_path, (4, "SURVIVED", marker),
                             (5, "KILLED", 0))

    assert done.returncode == 0, done.stderr
    assert "1 is the keyword-only" in done.stdout, done.stdout
    assert "REAL SURVIVAL 0.0% (0/1)" in done.stdout, done.stdout


def test_a_multiplication_in_a_DEFAULT_is_not_the_marker(tmp_path):
    """The marker is the `*` with a comma straight after it. A default
    value doing arithmetic sits in the same signature, and mutating THAT
    changes what the function does."""
    line = SIGNATURES.splitlines()[7]                  # `def scale(...)`
    times = line.index("2 * 3") + 2

    done = _signature_report(tmp_path, (8, "SURVIVED", times))

    assert "keyword-only" not in done.stdout, done.stdout
    assert "REAL SURVIVAL 100.0% (1/1)" in done.stdout, done.stdout
    assert "L8" in done.stdout


# --- the source the RUN was planned against -----------------------------


def test_the_report_quotes_the_source_the_run_was_PLANNED_against(tmp_path):
    """Every line number in a session indexes into the file the mutants
    were generated from. Read the live file instead and a source that
    has moved — a docstring added, a helper inserted — shifts every
    quote below the edit, and the report names the wrong line with
    complete confidence.

    Worse than a wrong quote: the annotation and script-guard spans are
    computed from that same text, so the classification moves too and
    the REAL SURVIVAL figure changes. Measured on `_table_layout` while
    it was being worked on: 13.4% against the live file, 9.7% against
    the source the run actually used.
    """
    src = tmp_path / "runnable.py"
    src.write_text(SCRIPT, encoding="utf-8")
    kept = tmp_path / ".mutation-run.pristine" / src.name
    kept.parent.mkdir()
    kept.write_text(SCRIPT, encoding="utf-8")
    db = _database(tmp_path / ".mutation-run.sqlite", (5, "SURVIVED"))
    # the live file grows a line ABOVE the survivor
    src.write_text("# a comment added while the sweep ran\n" + SCRIPT,
                   encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 0, done.stderr
    assert "the live file has moved since" in done.stdout
    quoted = [ln.strip() for ln in done.stdout.splitlines()
              if ln.startswith("          ")]
    assert quoted and "widen" not in quoted[0], done.stdout


def test_an_UNMOVED_source_is_reported_without_a_note(tmp_path):
    """The note has to be rare enough to read: printed on every run it
    is wallpaper, and the one run where the tree moved looks like all
    the others."""
    src = tmp_path / "runnable.py"
    src.write_text(SCRIPT, encoding="utf-8")
    kept = tmp_path / ".mutation-run.pristine" / src.name
    kept.parent.mkdir()
    kept.write_text(SCRIPT, encoding="utf-8")
    db = _database(tmp_path / ".mutation-run.sqlite", (5, "SURVIVED"))

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 0, done.stderr
    assert "moved since" not in done.stdout


def test_a_session_with_NO_snapshot_still_reports(tmp_path):
    """Sessions planned before the snapshot existed, and any run driven
    by hand. The fallback is the live file — which is what this tool
    always did — and it must not become an error."""
    done = _script_report(tmp_path, (5, "SURVIVED"))

    assert done.returncode == 0, done.stderr
    assert "REAL SURVIVAL" in done.stdout
    assert "moved since" not in done.stdout


# --- the banner that says the list is already void ----------------------


def _tools_on_path():
    """`tools/` is not a package and is not installed; the scripts reach
    each other through this insert, and so does this file."""
    import sys

    if str(TOOL.parent) not in sys.path:
        sys.path.insert(0, str(TOOL.parent))


def _tool_module():
    """The tool imported, not run: `staleness` is a pure function."""
    _tools_on_path()
    import mutation_survivors  # pyright: ignore[reportMissingImports]

    return mutation_survivors


def test_a_STALE_run_says_so_above_its_survivors(monkeypatch):
    """The rule is old — a figure is void when the source or the harness
    has moved — and the tool that PROPOSES the work is where it has to
    be said. Mining a stale list cost a round on 2026-08-20: `body.py`'s
    survivors named eleven mutants on one line a previous round had
    already killed, and the tests written for them duplicated tests
    already in the file."""
    _tools_on_path()
    import harness_map  # pyright: ignore[reportMissingImports]
    import stale_figures  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(harness_map, "harness_for",
                        lambda mod: ["tests/test_thing.py"])
    monkeypatch.setattr(stale_figures, "state",
                        lambda mod, tests: ("stale", ["tests/test_thing.py"]))

    lines = _tool_module().staleness("src/docxkit/thing.py")

    assert lines and "STALE" in lines[0]
    assert "tests/test_thing.py" in lines[0]
    assert any("kill_check" in ln for ln in lines)


def test_a_FRESH_run_says_nothing(monkeypatch):
    """A banner printed over every list is one nobody reads."""
    _tools_on_path()
    import harness_map  # pyright: ignore[reportMissingImports]
    import stale_figures  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(harness_map, "harness_for", lambda mod: ["t.py"])
    monkeypatch.setattr(stale_figures, "state",
                        lambda mod, tests: ("fresh", []))

    assert _tool_module().staleness("src/docxkit/thing.py") == []


def test_a_module_with_NO_harness_is_not_an_error(monkeypatch):
    """`harness_for` exits when the map has no entry and nothing in
    `tests/` names the module. A survivor list for such a module still
    has to print — the banner is a courtesy, not a gate."""
    _tools_on_path()
    import harness_map  # pyright: ignore[reportMissingImports]

    def refuse(mod):
        raise SystemExit(f"no harness for {mod}")

    monkeypatch.setattr(harness_map, "harness_for", refuse)

    assert _tool_module().staleness("src/docxkit/thing.py") == []
