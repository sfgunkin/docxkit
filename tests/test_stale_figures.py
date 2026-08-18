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

import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed: the path insert above
# is how its scripts reach each other, and how they are reached here.
from stale_figures import (  # noqa: E402  # pyright: ignore[reportMissingImports]
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
