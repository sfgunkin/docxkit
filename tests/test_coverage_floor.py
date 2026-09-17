"""`tools/coverage_floor.py` — a number from a RED suite is not a number.

The tool runs the suite itself and reads the JSON report, so it is the
one gate that can be handed a partial measurement and not notice.
`check=False` is deliberate — the report has to be readable even when
pytest exits non-zero — and the exit code was thrown away with it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import coverage_floor  # noqa: E402  # pyright: ignore[reportMissingImports]

REPORT = {"files": {"src/docxkit/_table_core.py":
                    {"summary": {"percent_covered": 55.8}}}}


def _fake_run(returncode: int, stdout: str = ""):
    """Stand in for the pytest subprocess, writing the report it would."""
    def run(cmd, **kw):
        out = next(a.split(":", 1)[1] for a in cmd if a.startswith(
            "--cov-report=json:"))
        Path(out).write_text(json.dumps(REPORT), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")
    return run


def test_a_TEST_file_in_the_report_is_not_a_module_with_a_floor(tmp_path):
    """The report is shared. Since 2026-09-18 the `pytest` gate measures
    `--cov=docxkit --cov=tests`, so `unrun_assertions` can ask which
    assertion did not run — and every test file then arrived here to be
    judged against DEFAULT. Four were under it and the chain went red
    over the coverage of test files, which is not a thing this tool has
    an opinion about.
    """
    report = tmp_path / "cov.json"
    report.write_text(json.dumps({"files": {
        "src/docxkit/_table_core.py": {"summary": {"percent_covered": 99.0}},
        "tests/test_width_model.py": {"summary": {"percent_covered": 31.5}},
    }}), encoding="utf-8")

    measured = coverage_floor.measure(from_json=report)

    assert measured == {"_table_core.py": 99.0}


def test_a_RED_suite_measures_NOTHING(monkeypatch):
    """Seen once, 2026-08-21: one failing test in the tables suite, and
    the tool reported `_table_core.py: 55.8% is below its floor of 85%`
    — a module whose tests were all there, most of them simply never
    reached. That reading sends a reader to write tests that exist."""
    monkeypatch.setattr(coverage_floor.subprocess, "run", _fake_run(
        1, "FAILED tests/test_tables_api.py::test_a_figure\n"
           "1 failed, 4575 passed in 70s\n"))

    with pytest.raises(SystemExit) as exc:
        coverage_floor.measure()

    said = str(exc.value)
    assert "RED" in said and "measures nothing" in said
    assert "55.8" not in said, "a partial number must not be quoted as one"
    assert "test_a_figure" in said, "and the failure it stopped on is named"


def test_a_GREEN_suite_is_read_as_before(monkeypatch):
    monkeypatch.setattr(coverage_floor.subprocess, "run", _fake_run(0))

    assert coverage_floor.measure() == {"_table_core.py": 55.8}


def test_a_MISSING_report_still_says_so_first(monkeypatch):
    """The environment question comes before the suite's verdict: a
    pytest that rejects `--cov` also exits non-zero, and "the suite is
    RED" would send that reader somewhere there is nothing wrong."""
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 4, "", "")

    monkeypatch.setattr(coverage_floor.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        coverage_floor.measure()

    assert re.search("pytest-cov", str(exc.value))


def test_a_COLLECTION_error_is_not_diagnosed_as_a_missing_plugin(
        monkeypatch):
    """The other way to finish with no report. A collection error exits
    2 and writes no cov.json, and the environment message then sent the
    reader to install a plugin that is already there — the same
    misdiagnosis the RED guard was added to kill, one exit code over."""
    def run(cmd, **kw):
        return subprocess.CompletedProcess(
            cmd, 2, "", "ERROR tests/test_x.py - ImportError: no module foo")

    monkeypatch.setattr(coverage_floor.subprocess, "run", run)

    with pytest.raises(SystemExit) as exc:
        coverage_floor.measure()

    assert "pytest-cov" not in str(exc.value)
    assert "the suite is RED (pytest exit 2)" in str(exc.value)
    # …with the evidence, which lives on stderr for this kind of exit
    assert "ImportError" in str(exc.value)


def test_a_report_the_CALLER_produced_is_read_instead_of_re_running(
        tmp_path, monkeypatch):
    """`gates.py` runs the suite once, under coverage, and hands the
    report here. Without that the chain ran 4,971 tests TWICE — bare and
    then again with the tracer attached — which measured 108 s + 126 s
    of a 247 s chain for the same tests over the same code.

    The test that matters is that reading a report does not quietly run
    the suite anyway: a subprocess call here would make the saving
    imaginary and nothing else would notice."""
    def _explode(*a, **kw):
        raise AssertionError("the suite must not be run again")

    monkeypatch.setattr(coverage_floor.subprocess, "run", _explode)
    report = tmp_path / "cov.json"
    report.write_text(json.dumps(REPORT), encoding="utf-8")

    found = coverage_floor.measure(report)

    assert found == {"_table_core.py": 55.8}


def test_a_report_that_is_NOT_THERE_says_so_rather_than_measuring_zero(
        tmp_path):
    """The caller was supposed to write it. An empty measurement would
    read as "every module is at 0%" and fail every floor at once, which
    sends a reader looking at their code instead of at the run that did
    not happen."""
    with pytest.raises(SystemExit) as exc:
        coverage_floor.measure(tmp_path / "never-written.json")

    assert "no coverage report" in str(exc.value)


def test_a_module_in_a_SUBPACKAGE_keeps_its_folder_in_the_key():
    """`revision/` arrived on 2026-08-30 and a basename key stopped
    being unique. `revision/__init__.py` and the package's own
    `__init__.py` collide head-on: one silently overwrites the other in
    the dict, and a module is then measured against a percentage
    belonging to a different file — a confident pass, or a confident
    failure, about neither of them."""
    assert coverage_floor._key(
        "src/docxkit/revision/_losses.py") == "revision/_losses.py"
    assert coverage_floor._key(
        "src/docxkit/revision/__init__.py") == "revision/__init__.py"


def test_a_TOP_LEVEL_module_is_keyed_the_way_it_always_was():
    """The other half of the change, and the reason the FLOORS list did
    not have to be rewritten: 40 entries keep their spelling."""
    assert coverage_floor._key("src/docxkit/cli.py") == "cli.py"
    assert coverage_floor._key("src/docxkit/__init__.py") == "__init__.py"


def test_the_two_INIT_files_do_not_collapse_into_one_key():
    """Stated as the collision rather than as two spellings, because
    what is being prevented is a dict with one entry where two files
    were measured."""
    keys = {coverage_floor._key(p) for p in
            ("src/docxkit/__init__.py", "src/docxkit/revision/__init__.py")}

    assert len(keys) == 2, keys


def test_EVERY_floor_names_a_module_that_exists():
    """The direction the split breaks. A floor keyed on a file that is
    gone cannot be met by anything, and the entry for `revision.py` at
    97 — the highest in the package after cli and word — would have gone
    on describing 3,118 lines that are now fourteen files.

    `test_a_floored_module_MISSING_from_the_report_is_a_failure` below
    catches it at RUN time, off the coverage report. This catches it
    from the tree, which is the cheaper answer and the one that does not
    need a green suite first.
    """
    src = Path(docxkit.__file__).parent
    gone = sorted(name for name in coverage_floor.FLOORS
                  if not (src / name).is_file())

    assert not gone, (
        f"floors for modules that do not exist: {gone}. A renamed or "
        f"split module leaves its floor behind, and the new name "
        f"inherits DEFAULT — the protection is given back silently.")


def test_a_floored_module_MISSING_from_the_report_is_a_failure():
    """`check` used to walk the measurement, so a floor whose module is
    absent was not passed — it was unasked. Two ways that happens and
    both are quiet: a suite that died half way writes a report covering
    the files it reached, and a renamed module leaves its floor behind
    while the new name inherits DEFAULT. word.py and revision.py
    carry the highest floors in the file and are exactly the ones
    that would go, with nothing red."""
    below = coverage_floor.check({"cli.py": 100.0})

    assert len(below) == len(coverage_floor.FLOORS) - 1, below
    assert all("NOT in the coverage report" in line for line in below)


def test_REPORT_does_not_end_with_an_all_clear_under_its_own_failures(
        tmp_path, monkeypatch, capsys):
    """The all-clear was printed unconditionally, so `--report` closed
    with "every module is at or above its floor" directly beneath the
    rows it had just flagged BELOW FLOOR — exit 0, which is right for a
    report, under a sentence that is not.

    That sentence is also what `gates.py`'s summary regex picks out of a
    gate's output ("at or above"), so it could have been the last word
    shown for a floors gate that had just listed failures."""
    every = {f"src/docxkit/{m}": {"summary": {"percent_covered": 99.0}}
             for m in coverage_floor.FLOORS}
    every["src/docxkit/word.py"]["summary"]["percent_covered"] = 12.0
    report = tmp_path / "cov.json"
    report.write_text(json.dumps({"files": every}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["coverage_floor.py", "--report",
                         "--from-json", str(report)])

    code = coverage_floor.main()

    said = capsys.readouterr().out
    assert code == 0, "a report still reports"
    assert "BELOW FLOOR" in said
    assert "every module is at or above its floor" not in said, said


# --- the ratchet failing UPWARD (2026-09-09) -----------------------------

@pytest.fixture
def floors(monkeypatch):
    """A FLOORS of this test's own. Asserting against the live one would
    pin today's numbers into the suite, and re-ratcheting — which is the
    act this whole section exists to encourage — would then turn it red."""
    monkeypatch.setattr(coverage_floor, "FLOORS", {"a.py": 85, "b.py": 97})
    return coverage_floor.FLOORS


def test_a_floor_the_suite_has_OUTGROWN_is_reported(floors):
    """`check` only ever looks DOWN. Coverage rises, nobody re-runs
    `--update`, and the floor stays where it was while the module moves
    away from it — so the guard protects a band the code left behind.

    Measured 2026-09-09: `_cite_build.py` sat at a floor of 85 while the
    suite covered it at 98.8. That module builds every paper's citation
    apparatus, and at 85 it could have lost about sixty statements of
    coverage with this tool printing "every module is at or above its
    floor" over it."""
    assert coverage_floor.slack({"a.py": 98.8}) == [("a.py", 85.0, 98.8)]


def test_slack_is_measured_against_an_EXPLICIT_floor_only(floors):
    """`DEFAULT` is the bar a module clears before anyone has ratcheted
    it — "a NEW module starts held to the same standard as the rest" —
    so a module well above it is that policy working, not a floor going
    stale. Reading slack against DEFAULT too was the first version of
    this and it reported eighteen modules, every one of them fine."""
    assert coverage_floor.slack({"not_floored.py": 100.0}) == []


def test_a_STALE_floor_is_a_failure_and_a_small_one_is_only_a_note(floors):
    """Not a hard gate on every point of improvement — an afternoon that
    adds tests must be able to land without a red chain, which is what
    the complexity pins settled on for the same tension. Ten points is
    past that argument."""
    def stale(actual):
        return [x for x in coverage_floor.slack(actual)
                if x[2] - x[1] >= coverage_floor.SLACK]

    assert coverage_floor.slack({"b.py": 100.0}) != [], "3 points is a note"
    assert stale({"b.py": 100.0}) == [], "…and only a note"
    assert stale({"a.py": 98.8}), "13.8 points is the ratchet not tightened"


def test_update_reaches_a_floor_whose_key_has_a_FOLDER_in_it(tmp_path,
                                                             monkeypatch):
    """`--update` is the one mechanism this file offers for recording
    that the debt shrank, and its key pattern was `[\\w.]+` — which
    matches `tracked.py` and not `revision/_build.py`.

    Measured 2026-09-09: it reached 8 of the 24 floors and silently
    skipped 16, every module of the revision package — the half that
    touches manuscripts — while printing "floors updated from this run"
    over the skip. Re-ratcheting after the split could never have
    worked."""
    src = tmp_path / "coverage_floor.py"
    src.write_text('FLOORS = {\n    "tracked.py": 90,\n'
                   '    "revision/_build.py": 90,\n}\n', encoding="utf-8")
    monkeypatch.setattr(coverage_floor, "__file__", str(src))

    coverage_floor.update({"tracked.py": 96.0, "revision/_build.py": 99.0})

    now = src.read_text(encoding="utf-8")
    assert '"tracked.py": 96,' in now
    assert '"revision/_build.py": 99,' in now, now


def test_update_never_ratchets_a_floor_DOWN(tmp_path, monkeypatch):
    """A run against a suite that is temporarily worse must not hand
    back the guard. Lowering is the deliberate act the module docstring
    asks for, made by hand with a reason beside it."""
    src = tmp_path / "coverage_floor.py"
    src.write_text('FLOORS = {\n    "revision/_build.py": 100,\n}\n',
                   encoding="utf-8")
    monkeypatch.setattr(coverage_floor, "__file__", str(src))

    coverage_floor.update({"revision/_build.py": 41.0})

    assert '"revision/_build.py": 100,' in src.read_text(encoding="utf-8")
