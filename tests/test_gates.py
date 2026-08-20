"""`tools/gates.py` — the five gates, run so the answer cannot be lost.

The runner exists because the CHAIN is where they go wrong, and every
failure it guards against has happened here: a piped gate whose status
was the pipe's, a `;` that ran the next gate over a red one, and mypy's
exit code, which is non-zero for a run that found nothing but notes.

So what is tested is the joining, not the tools: that a red gate stops
the run, that the gates after it do not run, and that mypy is judged on
its LINES.
"""
from __future__ import annotations

import sys
from pathlib import Path

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import gates  # noqa: E402  # pyright: ignore[reportMissingImports]

OK = [sys.executable, "-c", "print('fine')"]
RED = [sys.executable, "-c", "import sys; print('boom'); sys.exit(1)"]
NOTES = [sys.executable, "-c", "print('note: a note is not an error')"]
ERRORS = [sys.executable, "-c", "print('x.py:1: error: no')"]


def _run(*gate_list):
    said: list[str] = []
    code = gates.run(gate_list, say=said.append)
    return code, "\n".join(said)


def test_all_green_is_zero():
    code, said = _run(("first", OK, False), ("second", OK, False))

    assert code == 0
    assert said.count("ok  ") == 2
    assert "fine" in said, "the last line of each gate is worth seeing"


def test_a_RED_gate_stops_the_run_and_is_named():
    code, said = _run(("first", OK, False), ("second", RED, False),
                      ("third", OK, False))

    assert code == 1
    assert "FAILED  second" in said
    assert "boom" in said, "and what it said, which is the whole point"
    assert "third" not in said, "a gate after a red one tells you nothing"


def test_mypy_is_judged_on_its_LINES_not_its_exit_code():
    """It exits non-zero for a run whose only output is notes, which is
    why CONTRIBUTING's command for it is a grep. The runner applies the
    same rule rather than trusting the code."""
    quiet, said = _run(("mypy", NOTES, True))
    assert quiet == 0, said

    loud, said = _run(("mypy", ERRORS, True))
    assert loud == 1
    assert "FAILED  mypy" in said


def test_the_real_list_is_the_five_CONTRIBUTING_names():
    """A runner that drifts from the documented gates is worse than
    none: it would report a pass over a gate nobody ran."""
    assert [name for name, _argv, _reads in gates.GATES] == [
        "ruff", "mypy", "pyright", "pytest", "floors"]
    assert [g for g in gates.GATES if g[2]] == [g for g in gates.GATES
                                                if g[0] == "mypy"]
