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


def test_the_runner_prints_a_failure_that_is_NOT_ascii(capsys):
    """The first failure this runner ever reported was a Cyrillic
    fixture, and printing it died: a cp1252 console cannot encode the
    U+FFFD a decode left behind, so the traceback replaced the report.
    The entry point asks for UTF-8 before it says anything — the same
    `utf8_stdout` every other script here calls — and `say` must carry
    whatever a gate wrote."""
    import sys

    # written as BYTES: a child told to print this to a cp1252 console
    # dies before the runner ever sees it, which is a different bug —
    # what is under test is the runner's own stdout.
    loud = [sys.executable, "-c",
            "import sys; sys.stdout.buffer.write("
            "'Таблица �'.encode()); raise SystemExit(1)"]
    said: list[str] = []

    code = gates.run([("pytest", loud, False)], say=said.append)

    assert code == 1
    assert any("Таблица" in line
               for line in said), said


def test_the_line_a_passing_gate_SHOWS_is_its_own_summary():
    """Once it was not. A pytest run under load ended with "<cannot get
    C stack on this system>" — an interpreter note about the MACHINE,
    not about the suite — and the runner reported that in place of
    "4430 passed". A gate that passed prints one line here, so the one
    line has to be the answer."""
    out = "4430 passed, 17 skipped in 74s\n<cannot get C stack on this>"

    assert gates._summary(out) == "4430 passed, 17 skipped in 74s"


def test_a_gate_saying_something_NEW_still_shows_its_last_line():
    """The shapes are a preference, not a filter: a tool that starts
    saying something else must not be reported as silent."""
    new = "something entirely new"
    assert gates._summary(new + chr(10)) == new
    assert gates._summary("  \n\n") == ""


def test_the_LAST_summary_line_wins_when_a_gate_prints_several():
    """pytest prints a per-file line and then its total; the total is
    the one a reader wants."""
    out = "tests/test_a.py 3 passed\n" + "12 passed, 1 skipped in 2s"

    assert gates._summary(out) == "12 passed, 1 skipped in 2s"
