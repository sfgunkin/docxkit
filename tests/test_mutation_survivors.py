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
import tomllib
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


def _database(path: Path,
              *rows: (tuple[int, str] | tuple[int, str, int]
                      | tuple[int, str, int, str]
                      | tuple[int, str, int, str, str])) -> Path:
    """A cosmic-ray database holding just what the report reads.

    A row is (line, outcome); where the COLUMN is what the report
    classifies on, (line, outcome, column); where the report quotes the
    mutation itself, (line, outcome, column, diff); and where the
    OPERATOR is what settles it, (line, outcome, column, diff,
    operator).
    """
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE mutation_specs (job_id TEXT, "
               "start_pos_row INT, start_pos_col INT, operator_name TEXT)")
    db.execute("CREATE TABLE work_results (job_id TEXT, test_outcome TEXT, "
               "diff TEXT)")
    for i, spec in enumerate(rows):
        row, outcome = spec[0], spec[1]
        col = spec[2] if len(spec) > 2 else 0
        diff = spec[3] if len(spec) > 3 else ""
        job = f"job{i}"
        operator = spec[4] if len(spec) > 4 else "core/NumberReplacer"
        db.execute("INSERT INTO mutation_specs VALUES (?, ?, ?, ?)",
                   (job, row, col, operator))
        db.execute("INSERT INTO work_results VALUES (?, ?, ?)",
                   (job, outcome, diff))
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


def test_a_session_with_no_snapshot_SAYS_the_lines_are_unverified(tmp_path):
    """The fallback is not an error, but it must not be silent either.

    An empty note reads as "this is the source the run used". It is not:
    it is whatever is on disk today, and the line numbers below index
    into the file the mutants were generated from. The two are the same
    file only until somebody edits it, and nothing here can tell.
    """
    done = _script_report(tmp_path, (5, "SURVIVED"))

    assert done.returncode == 0, done.stderr
    assert "no pristine copy" in done.stdout
    assert "kept no snapshot" in done.stdout


def test_a_PRUNED_snapshot_is_named_as_such(tmp_path):
    """A `.pristine` that exists without the file is a pruning mistake,
    and reads differently from a session that never kept one: there is
    somewhere to go and look. Both fall back to the live file; only this
    one means a `.sqlite` was kept while its snapshot was deleted."""
    src = tmp_path / "runnable.py"
    src.write_text(SCRIPT, encoding="utf-8")
    (tmp_path / ".mutation-run.pristine").mkdir()      # emptied, not absent
    db = _database(tmp_path / ".mutation-run.sqlite", (5, "SURVIVED"))

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 0, done.stderr
    assert "no pristine copy" in done.stdout
    assert "does not hold runnable.py" in done.stdout
    assert "kept no snapshot" not in done.stdout


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


def test_a_MISSING_session_is_refused_and_NOT_created(tmp_path):
    """A session's file drops the module's leading underscore, so the
    obvious name for `_cite_repair.py` is the wrong one. Handed it, the
    report CREATED an empty database and died on "no such table"
    (BACKLOG S4, 2026-09-12)."""
    wrong = tmp_path / ".mutation-_cite_repair.sqlite"

    done = subprocess.run(
        [sys.executable, str(TOOL), str(wrong),
         "src/docxkit/_cite_repair.py"],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 2, done.stderr
    assert "Traceback" not in done.stderr, done.stderr
    assert ".mutation-cite_repair.sqlite" in done.stdout, done.stdout
    assert not wrong.exists(), "a refusal must not leave the file behind"


def test_classify_REFUSES_a_session_that_is_not_there(tmp_path):
    tool = _tool_module()
    src = tmp_path / "widths.py"
    src.write_text(MODULE, encoding="utf-8")
    missing = tmp_path / "nope.sqlite"

    with pytest.raises(FileNotFoundError, match="no session at"):
        tool.classify(str(missing), str(src))

    assert not missing.exists()


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


# --- which mutant, not which operator ------------------------------------

DIFF = """--- a/widths.py
+++ b/widths.py
@@ -1,4 +1,4 @@
 def narrow(x: int) -> int:
-    return x - 1
+    return x - 2
"""


def test_the_report_quotes_the_LINE_THE_MUTATION_MADE(tmp_path):
    """An operator name is ambiguous wherever a line holds two of the
    same operator: `ReplaceComparisonOperator_NotEq_Gt` on
    `if a != b or len(c) != len(d):` names one of two mutants and the
    reader picks the wrong one half the time.

    It happened on `_compare_diff`'s `fmt_diff` guard (2026-08-20): the
    test written from that list aimed at the first `!=`, which a test
    from an earlier round had already pinned, and `kill_check` reported
    a kill because the mutation broke that OTHER test. A duplicate test
    and a survivor still alive."""
    src = tmp_path / "widths.py"
    src.write_text(MODULE, encoding="utf-8")
    db = _database(tmp_path / "run.sqlite", (2, "SURVIVED", 0, DIFF))

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 0, done.stderr
    assert "-> return x - 2" in done.stdout, done.stdout
    assert "NumberReplacer" not in done.stdout, done.stdout


def test_a_mutant_with_NO_stored_diff_still_says_something(tmp_path):
    """A database from a run that did not store one — an older
    cosmic-ray, or a row the tool wrote itself — falls back to the
    operator name. A survivor list that silently drops the line it
    cannot quote is worse than one that names the operator."""
    src = tmp_path / "widths.py"
    src.write_text(MODULE, encoding="utf-8")
    db = _database(tmp_path / "run.sqlite", (2, "SURVIVED"))

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 0, done.stderr
    assert "-> NumberReplacer" in done.stdout, done.stdout


# --- lines coverage is told to skip --------------------------------------

DEFENSIVE = '''\
"""A module with a branch the package cannot reach."""


def clamp(lo: int, hi: int) -> int:
    if lo < 0 or hi < 0:                 # pragma: no cover - defensive
        lo = 0
        return lo
    return hi
'''


def _defensive_report(tmp_path, *rows):
    src = tmp_path / "defensive.py"
    src.write_text(DEFENSIVE, encoding="utf-8")
    db = _database(tmp_path / "run.sqlite", *rows)
    return subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def test_a_line_coverage_SKIPS_is_not_counted_as_a_gap(tmp_path):
    """`# pragma: no cover` is the author saying a branch is defensive,
    and the coverage floor is enforced with those lines taken out. No
    test executes them, so no test can kill a mutant on one — the same
    kind of permanent survivor as an annotation, and just as loud:
    `_cite_build` carried EIGHT on one `if` and the `continue` under it,
    a fifth of the module's figure, on a line the project has already
    declared unreachable."""
    done = _defensive_report(tmp_path, (5, "SURVIVED"), (8, "KILLED"))

    assert done.returncode == 0, done.stderr
    assert "1 is on a line coverage is told to SKIP" in done.stdout
    assert "REAL SURVIVAL 0.0% (0/1)" in done.stdout, done.stdout
    assert "L5" not in done.stdout


def test_the_pragma_covers_the_BLOCK_it_heads(tmp_path):
    """coverage.py's reading of a pragma on a compound statement: the
    whole block goes, not the header line. The `continue` under a
    defensive `if` is exactly as unreachable as the `if` itself, and
    counting it alone would leave half the cluster in the figure."""
    done = _defensive_report(tmp_path, (6, "SURVIVED"), (7, "SURVIVED"))

    assert "2 are on a line coverage is told to SKIP" in done.stdout
    assert "L6" not in done.stdout and "L7" not in done.stdout


def test_a_survivor_BELOW_the_defensive_block_is_still_a_gap(tmp_path):
    """The exclusion is a span, not everything after it: the `return`
    that follows the block is ordinary code and its survivor is
    ordinary work."""
    done = _defensive_report(tmp_path, (8, "SURVIVED"))

    assert "REAL SURVIVAL 100.0% (1/1)" in done.stdout, done.stdout
    assert "L8" in done.stdout


# --- a run that stopped early ------------------------------------------


def test_a_run_that_stopped_EARLY_says_so_before_its_figure(tmp_path):
    """A sampled run marks the mutants it will not run SKIPPED, so a
    FINISHED one has a row per spec either way. Fewer rows means the
    session was killed, timed out, or is still going — and the figure
    from a run that stopped is not the module's, it is whatever the
    first N mutants happened to say.

    It flatters, which is why it needs saying out loud: `_table_core`
    read 1.0 % (2/209) from 675 of its 903 mutants, ten minutes after a
    stream was stopped, against a true 2.7 % (11/415)."""
    src = tmp_path / "widths.py"
    src.write_text(MODULE, encoding="utf-8")
    db = _database(tmp_path / "partial.sqlite", (2, "SURVIVED"),
                   (6, "KILLED"))
    # two more mutants planned and never answered
    conn = sqlite3.connect(db)
    for i in (90, 91):
        conn.execute("INSERT INTO mutation_specs VALUES (?, ?, ?, ?)",
                     (f"job{i}", 6, 0, "core/NumberReplacer"))
    conn.commit()
    conn.close()

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert done.returncode == 0, done.stderr
    assert "INCOMPLETE: 2 of 4 mutants" in done.stdout, done.stdout
    assert "not the module" in done.stdout


def test_a_FINISHED_sample_is_not_called_incomplete(tmp_path):
    """The distinction the banner turns on: a sample says SKIPPED for
    what it chose not to run, and that is an answer. Calling it
    incomplete would put the warning on every sampled run in the
    package, which is all of the big ones."""
    src = tmp_path / "widths.py"
    src.write_text(MODULE, encoding="utf-8")
    db = _database(tmp_path / "sampled.sqlite", (2, "SURVIVED"),
                   (6, "KILLED"), (6, "SKIPPED"), (6, "SKIPPED"))

    done = subprocess.run(
        [sys.executable, str(TOOL), str(db), str(src)],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    assert "INCOMPLETE" not in done.stdout, done.stdout
    assert "(sampled from 4)" in done.stdout, done.stdout


# --- argued equivalences ------------------------------------------------

CLAIMED_SRC = """\
def widen(lo: int, hi: int) -> list[int]:
    listed = {hi}
    return [i for i in range(lo, hi + 1) if i not in listed]
"""

MUTANT = "return [i for i in range(lo, hi * 1) if i not in listed]"


def _claims_file(tmp_path, module, *lines):
    text = ['["' + module + '"]', "claims = ["]
    text += ['  { was = "x", line = "' + ln + '", why = "argued" },'
             for ln in lines]
    text.append("]")
    path = tmp_path / "equivalents.toml"
    path.write_text(chr(10).join(text), encoding="utf-8")
    return path


def _operator_claims_file(tmp_path, module, *pairs):
    """Claims keyed the second way: `operator` and the line it stood on."""
    text = ['["' + module + '"]', "claims = ["]
    text += ['  { was = "' + was + '", operator = "' + operator
             + '", why = "argued" },' for operator, was in pairs]
    text.append("]")
    path = tmp_path / "equivalents.toml"
    path.write_text(chr(10).join(text), encoding="utf-8")
    return path


def _claimed_counts(tmp_path, monkeypatch, *rows, claims=(MUTANT,)):
    """`classify` in process, so the claims file can be swapped."""
    tool = _tool_module()
    src = tmp_path / "widen.py"
    src.write_text(CLAIMED_SRC, encoding="utf-8")
    monkeypatch.setattr(tool, "CLAIMS",
                        _claims_file(tmp_path, "widen.py", *claims))
    return tool.classify(str(_database(tmp_path / "run.sqlite", *rows)),
                         str(src))


def test_a_mutant_argued_EQUIVALENT_is_not_counted_as_a_gap(tmp_path,
                                                            monkeypatch):
    """The same discount the annotations get, for the same reason: a
    mutant that cannot change behaviour is not a missing test, and a
    survivor list padded with settled ones gets re-triaged from scratch
    every sweep."""
    counts = _claimed_counts(tmp_path, monkeypatch,
                             (3, "SURVIVED", 0, "+    " + MUTANT))

    assert counts.claimed == 1
    assert counts.real == []
    assert counts.base == 0


def test_an_UNCLAIMED_mutant_on_the_same_line_is_still_a_gap(tmp_path,
                                                             monkeypatch):
    """The claim is about one mutation, not about the line it sits on.
    `hi ^ 1` and `hi * 1` differ — the first misses a stray above an
    odd-indexed last entry — so discounting by line would have hidden a
    real defect behind a neighbour's argument."""
    other = "return [i for i in range(lo, hi ^ 1) if i not in listed]"
    counts = _claimed_counts(tmp_path, monkeypatch,
                             (3, "SURVIVED", 0, "+    " + other))

    assert counts.claimed == 0
    assert len(counts.real) == 1


def test_a_claim_for_ANOTHER_module_does_not_reach_this_one(tmp_path,
                                                            monkeypatch):
    """Keyed by module, because the same line of code means different
    things in two files and an argument made about one of them is not
    evidence about the other."""
    tool = _tool_module()
    src = tmp_path / "widen.py"
    src.write_text(CLAIMED_SRC, encoding="utf-8")
    monkeypatch.setattr(tool, "CLAIMS",
                        _claims_file(tmp_path, "somewhere_else.py", MUTANT))

    counts = tool.classify(
        str(_database(tmp_path / "run.sqlite",
                      (3, "SURVIVED", 0, "+    " + MUTANT))), str(src))

    assert counts.claimed == 0
    assert len(counts.real) == 1


def test_a_SUBPACKAGE_halfs_claim_is_keyed_by_its_path_not_its_name(
        tmp_path, monkeypatch):
    """The key `verify_equivalents.py` resolves as ``src/docxkit/<key>``,
    read the same way here. Keyed by file name, a claim for
    `revision/_validate.py` was either discounted here and MODULE GONE
    there, or verified there and never discounted here — and a bare name
    is ambiguous the moment two halves share one."""
    tool = _tool_module()
    src = tmp_path / "src" / "docxkit" / "revision" / "widen.py"
    src.parent.mkdir(parents=True)
    src.write_text(CLAIMED_SRC, encoding="utf-8")
    row = (3, "SURVIVED", 0, "+    " + MUTANT)

    monkeypatch.setattr(tool, "CLAIMS",
                        _claims_file(tmp_path, "revision/widen.py", MUTANT))
    by_path = tool.classify(str(_database(tmp_path / "a.sqlite", row)),
                            str(src))
    monkeypatch.setattr(tool, "CLAIMS",
                        _claims_file(tmp_path, "widen.py", MUTANT))
    by_name = tool.classify(str(_database(tmp_path / "b.sqlite", row)),
                            str(src))

    assert by_path.claimed == 1
    assert by_name.claimed == 0, "the bare name no longer reaches a half"
    assert tool.claims_key(str(src)) == "revision/widen.py"
    assert tool.claims_key(str(tmp_path / "widen.py")) == "widen.py"


def test_a_claimed_mutant_inside_an_ANNOTATION_is_discounted_ONCE(tmp_path,
                                                                  monkeypatch):
    """Both discounts come out of the denominator, so counting a mutant
    under each one takes it out twice and the rate is quietly deflated —
    an error in the direction everybody is hoping for, which is the
    direction nobody checks. The claims are applied to what the earlier
    passes left, not to the whole survivor list."""
    col = CLAIMED_SRC.splitlines()[0].index("int")
    counts = _claimed_counts(tmp_path, monkeypatch,
                             (1, "SURVIVED", col, "+    " + MUTANT))

    assert counts.annotated == 1
    assert counts.claimed == 0, "discounted twice"
    assert counts.base == 0


@pytest.mark.parametrize("source,wanted", [
    pytest.param("def f(a: int) -> None:\n    pass\n", ["int", "None"],
                 id="ordinary"),
    pytest.param("def f(*roots: int | None) -> None:\n    pass\n",
                 ["int | None", "None"], id="vararg"),
    pytest.param("def f(**kw: str) -> None:\n    pass\n", ["str", "None"],
                 id="kwarg"),
])
def test_the_annotation_discount_covers_STAR_ARGS_too(source, wanted):
    """PEP 563 never evaluates an annotation, so a mutant inside one is
    equivalent by construction and comes out of the denominator. The
    discount was built from `args + posonlyargs + kwonlyargs` and never
    looked at `vararg` or `kwarg` — so `def lint(*roots: _Element | None)`
    and `def audit(*roots: ...)` presented 22 of `lint.py`'s 65 survivors
    as questions (2026-09-17). Its real survival was 5.0 %, and the round
    was briefed on 7.5 %: a discount that is incomplete does not read as
    incomplete, it reads as a module with more to answer for."""
    import ast

    tool = _tool_module()
    text = source.splitlines()
    spans = tool.annotation_spans(ast.parse(source))
    found = [text[row - 1][col:end_col]
             for row, col, _end_row, end_col in spans]

    assert sorted(found) == sorted(wanted)


# --- the second key: an operator, for the mutants no line can name ------

DECORATED = """\
from functools import lru_cache


@lru_cache(maxsize=8)
def widen(x: int) -> int:
    return x + 1


@lru_cache(maxsize=8)
def narrow(x: int) -> int:
    return x - 1
"""

REMOVE = "core/RemoveDecorator"


def _operator_counts(tmp_path, monkeypatch, *rows, claims):
    tool = _tool_module()
    src = tmp_path / "cached.py"
    src.write_text(DECORATED, encoding="utf-8")
    monkeypatch.setattr(tool, "CLAIMS",
                        _operator_claims_file(tmp_path, "cached.py", *claims))
    return tool.classify(str(_database(tmp_path / "run.sqlite", *rows)),
                         str(src))


def test_a_mutant_that_REMOVES_a_line_is_settled_by_its_OPERATOR(
        tmp_path, monkeypatch):
    """A removed decorator produces no line, so `became` answers "" and
    the line keying has nothing to key on. Three of find.py's survivors
    are this shape and would be reported by every sweep for ever —
    which teaches a reader to skim the list, the same way a gate that
    cannot fail stops being read."""
    counts = _operator_counts(
        tmp_path, monkeypatch, (4, "SURVIVED", 0, "", REMOVE),
        claims=[(REMOVE, "@lru_cache(maxsize=8)")])

    assert counts.claimed == 1
    assert counts.real == []
    assert counts.ambiguous == ()


def test_an_operator_key_naming_TWO_mutants_settles_NEITHER(tmp_path,
                                                            monkeypatch):
    """The hazard the line keying refuses by demanding a unique anchor,
    one level up: this module writes `@lru_cache(maxsize=8)` twice, so
    the pair (operator, line) names two mutations and cannot mean one.

    Settling both would hide a mutant nobody argued about, and what is
    missing from a survivor list is exactly what its reader cannot see.
    So neither is settled, and the report says which key over-matched.
    """
    counts = _operator_counts(
        tmp_path, monkeypatch,
        (4, "SURVIVED", 0, "", REMOVE), (9, "SURVIVED", 0, "", REMOVE),
        claims=[(REMOVE, "@lru_cache(maxsize=8)")])

    assert counts.claimed == 0
    assert len(counts.real) == 2
    assert counts.ambiguous == ((REMOVE, "@lru_cache(maxsize=8)"),)


def test_an_operator_claim_does_not_reach_a_mutant_that_NAMES_itself(
        tmp_path, monkeypatch):
    """Line keying stays authoritative. A mutant with a rendering of its
    own is matched on that rendering and by nothing else — otherwise an
    operator claim would quietly cover every OTHER mutation the same
    operator makes on that line, which for a NumberReplacer is several.
    """
    counts = _operator_counts(
        tmp_path, monkeypatch,
        (4, "SURVIVED", 0, "+@lru_cache(maxsize= 9)", REMOVE),
        claims=[(REMOVE, "@lru_cache(maxsize=8)")])

    assert counts.claimed == 0
    assert len(counts.real) == 1


def test_the_report_SAYS_when_an_operator_key_over_matches(
        tmp_path, monkeypatch, capsys):
    """The refusal reaches the person reading the list, with the remedy:
    the same trailing comment that makes a repeated line claimable.

    Counting it apart is not enough — a mutant that is neither settled
    nor explained reads as an ordinary survivor, and the next round
    re-argues a claim that is already written."""
    tool = _tool_module()
    src = tmp_path / "cached.py"
    src.write_text(DECORATED, encoding="utf-8")
    monkeypatch.setattr(tool, "CLAIMS", _operator_claims_file(
        tmp_path, "cached.py", (REMOVE, "@lru_cache(maxsize=8)")))
    db = _database(tmp_path / "run.sqlite", (4, "SURVIVED", 0, "", REMOVE),
                   (9, "SURVIVED", 0, "", REMOVE))
    monkeypatch.setattr(sys, "argv", ["mutation_survivors", str(db),
                                      str(src)])

    assert tool.main() == 0
    out = capsys.readouterr().out

    assert "MORE THAN ONE" in out, out
    assert "trailing comment" in out


def test_the_verifier_REFUSES_a_claim_whose_line_is_ambiguous(tmp_path):
    """`kill_check` needs the line as it really appears, and insists its
    anchor occur exactly once. A stripped claim matching two lines would
    otherwise mutate whichever came first and report "survived, as
    claimed" about a line nobody argued for."""
    _tools_on_path()
    import verify_equivalents  # pyright: ignore[reportMissingImports]

    src = tmp_path / "twice.py"
    src.write_text("def f():\n    x = 1\n    return x\n\n"
                   "def g():\n    x = 1\n    return x\n", encoding="utf-8")

    assert verify_equivalents.anchored(src, "return x") is None
    assert verify_equivalents.anchored(src, "def f():") == "def f():"


def test_the_SHIPPED_claims_file_parses_and_every_claim_is_complete():
    """A claim is prose about code, and prose in TOML is one stray
    double quote away from ending its own string. That is not a
    hypothetical: writing one of these with a quoted phrase inside it
    truncated the value and left an unclosed inline table, which
    surfaces as `mutation_survivors` crashing part way down a report
    rather than as anything about the file.

    Each claim also needs all three keys. `why` missing is a claim
    nobody can check; `was` missing hides it from
    `verify_equivalents.py`, which is the only thing that ever asks
    whether it is still true."""
    _tools_on_path()
    import verify_equivalents  # pyright: ignore[reportMissingImports]

    with verify_equivalents.CLAIMS.open("rb") as fh:
        doc = tomllib.load(fh)

    assert doc, "the claims file is empty"
    for module, entry in doc.items():
        assert module.endswith(".py"), module
        # the key as `verify_equivalents` resolves it — a half keyed by its
        # bare name would pass every other line here and verify nothing
        assert (verify_equivalents.ROOT / "src" / "docxkit" / module
                ).is_file(), f"{module} is not a path under src/docxkit"
        assert entry.get("claims"), f"{module} has no claims"
        for claim in entry["claims"]:
            assert set(claim) <= {"was", "line", "operator", "why",
                                  "kind"}, claim
            assert {"was", "why"} <= set(claim), claim
            assert claim.get("kind", "equivalent") in {"equivalent",
                                                       "cosmetic"}, claim
            assert len(claim["why"]) > 40, claim["why"]
            # exactly one key, and the second only for the operators
            # whose mutation removes its line — see the file's header
            assert ("line" in claim) != ("operator" in claim), claim
            if "line" in claim:
                assert claim["was"] != claim["line"], claim
            else:
                _tools_on_path()
                from mutation_survivors import (  # pyright: ignore[reportMissingImports]
                    LINELESS_OPERATORS,
                )
                assert claim["operator"] in LINELESS_OPERATORS, claim


def test_classify_reads_the_SNAPSHOT_even_when_handed_the_live_file(tmp_path):
    """Every row in the database indexes the source the run was PLANNED
    against, and the discounts are span tests — spans move. Handed a
    file that has since gained a line, `classify` tests each survivor's
    position against spans that have shifted underneath it, and the
    annotation discount collapses.

    It is not hypothetical and it was not small: `stale_figures
    --figures` passed the live path where the report passed the
    snapshot, and `_compare_read` printed 30.0% (128/426) beside a true
    6.0% (19/317) — one annotation mutant discounted where there were
    110. It read as the worst module in the package while being one of
    the better ones, in the table that decides where the effort goes.

    Sharing `classify` was not enough to stop that, because the two
    callers handed it different sources. So it resolves the snapshot
    itself, and this asks it the question the way the table did."""
    tool = _tool_module()
    kept = tmp_path / ".mutation-widen.pristine"
    kept.mkdir()
    (kept / "widen.py").write_text(CLAIMED_SRC, encoding="utf-8")
    # the live file, one line further down than the run measured
    live = tmp_path / "widen.py"
    live.write_text('"""A docstring nobody had written yet."""\n'
                    + CLAIMED_SRC, encoding="utf-8")
    col = CLAIMED_SRC.splitlines()[0].index("int")
    db = _database(tmp_path / ".mutation-widen.sqlite", (1, "SURVIVED", col))

    counts = tool.classify(str(db), str(live))

    assert counts.annotated == 1, "the annotation discount was lost"
    assert counts.real == []


def test_a_COSMETIC_claim_leaves_the_list_and_stays_in_the_rate(tmp_path,
                                                                monkeypatch):
    """The two kinds are not the same discount. An `equivalent` mutant
    CANNOT be killed, so it leaves numerator and denominator together.
    A `cosmetic` one — the width of a truncation, the length of a quoted
    snippet — really does change what the code does, and a test
    asserting the character count would kill it. Nobody is going to
    write that test, which is a decision about effort and not a fact
    about the code: discounting it from the rate would report the
    decision as though there had been nothing there."""
    tool = _tool_module()
    src = tmp_path / "widen.py"
    src.write_text(CLAIMED_SRC, encoding="utf-8")
    toml = tmp_path / "equivalents.toml"
    toml.write_text('["widen.py"]\nclaims = [\n'
                    '  { was = "x", line = ' + repr(MUTANT).replace("'", '"')
                    + ', kind = "cosmetic", why = "a width nobody chose" },\n'
                    "]\n", encoding="utf-8")
    monkeypatch.setattr(tool, "CLAIMS", toml)

    counts = tool.classify(
        str(_database(tmp_path / "run.sqlite",
                      (3, "SURVIVED", 0, "+    " + MUTANT))), str(src))

    assert counts.real == [], "a cosmetic mutant is not a queue entry"
    assert len(counts.skin) == 1
    assert counts.claimed == 0, "it is not equivalent, and must not say so"
    assert counts.base == 1, "the denominator keeps it"
    assert counts.share == 100.0, "and so does the rate"


# --- verify_equivalents: what a run of 897 claims needs ------------------
#
# The tool is scoped to a module in everyday use and that is minutes. The
# WHOLE file is hours, which is why the run that would have caught ten
# claims orphaned by effef6c was never made (2026-09-18). `--jobs N` is
# the answer, and what it needs from this file is that the dealing, the
# per-worker checkout and the splitting-back are right — the timing is
# not a thing to assert.


def _verifier():
    _tools_on_path()
    import verify_equivalents  # pyright: ignore[reportMissingImports]

    return verify_equivalents


def test_the_workers_get_roughly_equal_CLAIM_counts_not_module_counts():
    """A run is as long as its longest group, and the file's shape is one
    module of 62 claims beside nineteen of two — dealt by module count,
    three workers would idle while the 62 ran alone."""
    tool = _verifier()
    sizes = {"big.py": 62, "mid.py": 20, "a.py": 3, "b.py": 3, "c.py": 2}

    dealt = tool.groups(sizes, 3)

    assert sorted(m for g in dealt for m in g) == sorted(sizes), "each once"
    loads = sorted(sum(sizes[m] for m in g) for g in dealt)
    assert loads[-1] == 62, "the longest module sets the floor"
    assert loads[0] >= 8, loads
    assert dealt == tool.groups(sizes, 3), "the same tree deals the same way"


def test_a_group_is_never_EMPTY_when_there_are_fewer_modules_than_workers():
    """An empty group would spawn a worker to check nothing, take a
    checkout for it, and print a block nobody can read."""
    dealt = _verifier().groups({"one.py": 4}, 4)

    assert dealt == [["one.py"]]


def test_each_worker_is_pointed_at_a_CHECKOUT_OF_ITS_OWN():
    """`kill_check` states the rule for itself: one caller per checkout,
    or each reads the other's mutations and both finish with a plausible
    number. The lock is named after the directory, so distinct
    directories are also distinct locks."""
    tool = _verifier()
    base = Path("D:/docxkit-kc")

    first = tool.worker_env(base, 1)["DOCXKIT_KILL_CHECK_WORKTREE"]
    second = tool.worker_env(base, 2)["DOCXKIT_KILL_CHECK_WORKTREE"]

    assert first != second
    assert first.endswith("-1") and second.endswith("-2")
    assert "PATH" in tool.worker_env(base, 1), "the rest of the env stays"


def test_a_workers_output_is_split_back_into_the_module_blocks():
    """The parent prints in the file's own order, so two runs over one
    tree print the same thing whatever order the workers finished in."""
    tool = _verifier()
    text = ("--- a.py: 1 claim(s)\n  OK one: SURVIVED (wanted equivalent)\n"
            "--- b.py: 1 claim(s)\n  !! two: killed (wanted equivalent)\n")

    found = tool.by_module(text, ["a.py", "b.py"])

    assert "OK one" in found["a.py"] and "!! two" not in found["a.py"]
    assert "!! two" in found["b.py"]
    assert found[""] == "", "nothing was said before the first block"


def test_what_a_worker_says_BEFORE_its_first_block_is_not_dropped():
    """A worker that cannot take its checkout says so once and exits —
    `kill_check` refuses rather than sharing one. Dropped, the parent
    reports silence about a module nothing ran."""
    tool = _verifier()

    found = tool.by_module("another caller holds D:/docxkit-kc-2\n",
                           ["a.py"])

    assert "another caller holds" in found[""]
    assert found["a.py"] == ""


def test_the_parent_totals_a_worker_from_its_TRAILER_not_its_bang_lines():
    """The worst case is the one `!!` lines cannot see: when the
    UNMUTATED harness fails in a checkout, `check` writes off every case
    at once and says so in ONE line about the harness. Its return value
    knows that, so the worker prints it and the parent adds it up."""
    tool = _verifier()

    block, said = tool.tally_of(
        "--- a.py: 9 claim(s)\n  ?? the UNMUTATED harness fails in kc\n"
        f"{tool.TALLY} a.py 9\n")

    assert said == 9
    assert tool.TALLY not in block
    assert block.endswith("harness fails in kc"), "the block is untouched"


def test_a_claim_that_is_no_longer_what_it_was_argued_to_be_EXITS_nonzero(
        tmp_path, monkeypatch):
    """`check` returns how many cases did not match their expectation and
    the caller threw it away, so a run in which three claims were killed
    exited 0. The `!!` lines said so and the exit code did not, which is
    the half a script reads (2026-09-18)."""
    tool = _verifier()
    src = tmp_path / "src" / "docxkit" / "widen.py"
    src.parent.mkdir(parents=True)
    src.write_text("def f():\n    return 1\n", encoding="utf-8")
    claims = tmp_path / "equivalents.toml"
    claims.write_text('["widen.py"]\nclaims = [\n'
                      '  { was = "return 1", line = "return 2", '
                      'why = "an argument long enough to be a sentence" },\n'
                      "]\n", encoding="utf-8")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "CLAIMS", claims)
    monkeypatch.setattr(tool, "harness_for", lambda module: ["tests/t.py"])

    monkeypatch.setattr(tool, "check", lambda *a, **kw: 0)
    assert tool.main(["widen.py"]) == 0, "a claim that survives is the norm"

    monkeypatch.setattr(tool, "check", lambda *a, **kw: 1)
    assert tool.main(["widen.py"]) == 1


def test_the_key_a_module_in_a_SUBPACKAGE_is_named_by():
    """`Path(src_path).name` is what `staleness` read, and
    `revision/_gates.py` reduces to `_gates.py` — no HARNESS key and no
    session name, so it looked for `.mutation-gates.sqlite`, found
    nothing, read "never measured" and printed no banner. Every module
    in a subpackage was exempt from the staleness warning, silently
    (noticed 2026-09-18, mining `revision/_gates.py` against a run that
    WAS stale in its tests)."""
    tool = _tool_module()

    assert tool.harness_key("src/docxkit/revision/_gates.py") == \
        "revision/_gates.py"
    assert tool.harness_key("src/docxkit/word.py") == "word.py"
    assert tool.harness_key("widths.py") == "widths.py"


def _drift(monkeypatch, *, planned: list[str] | None, now: list[str]):
    """The banner for a module whose session planned `planned` and whose
    map names `now`."""
    _tools_on_path()
    import harness_map  # pyright: ignore[reportMissingImports]
    import stale_figures  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(harness_map, "harness_for", lambda mod: now)
    monkeypatch.setattr(stale_figures, "planned_tests", lambda mod: planned)
    return _tool_module().harness_drift("src/docxkit/thing.py")


def test_a_harness_that_GAINED_a_test_calls_the_figure_an_upper_bound(
        monkeypatch):
    """An added test can only KILL, so the run is safe to mine and its
    rate is conservative — but a survivor on the list may already be
    dead, which is the thing to know before spending the afternoon."""
    lines = _drift(monkeypatch, planned=["tests/test_thing.py"],
                   now=["tests/test_thing.py", "tests/test_new.py"])

    assert any("HARNESS DRIFT" in ln for ln in lines)
    assert any("ADDED since" in ln and "KILL" in ln for ln in lines)
    assert any("upper bound" in ln for ln in lines)
    assert any("tests/test_new.py" in ln for ln in lines), "by NAME"
    assert not any("DROPPED" in ln for ln in lines)


def test_a_harness_that_LOST_a_test_says_the_QUESTION_has_changed(
        monkeypatch):
    """The alarming direction: the figure was measured against a test
    this module's harness no longer names, so a replay or a kill_check
    run today is not asking what the session asked."""
    lines = _drift(monkeypatch,
                   planned=["tests/test_thing.py", "tests/test_gone.py"],
                   now=["tests/test_thing.py"])

    assert any("DROPPED since" in ln for ln in lines)
    assert any("tests/test_gone.py" in ln for ln in lines), "by NAME"
    assert any("different question" in ln for ln in lines)
    assert not any("ADDED" in ln for ln in lines)


def test_a_harness_that_has_not_moved_prints_NOTHING(monkeypatch):
    """A banner over every list is one nobody reads — the same rule the
    staleness banner keeps."""
    assert _drift(monkeypatch, planned=["tests/test_thing.py"],
                  now=["tests/test_thing.py"]) == []
    assert _drift(monkeypatch, planned=None,
                  now=["tests/test_thing.py"]) == []


def test_asking_for_a_module_with_NO_claims_is_refused_not_silent(tmp_path,
                                                                  monkeypatch):
    """It printed nothing and exited 0, which reads exactly like "every
    claim holds" — and is what a mistyped module name gives you."""
    tool = _verifier()
    claims = tmp_path / "equivalents.toml"
    claims.write_text('["widen.py"]\nclaims = []\n', encoding="utf-8")
    monkeypatch.setattr(tool, "CLAIMS", claims)

    with pytest.raises(SystemExit) as exc:
        tool.main(["widen.pyc"])

    assert exc.value.code == 2
