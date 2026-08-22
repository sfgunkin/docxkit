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


