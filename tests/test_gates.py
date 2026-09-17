"""`tools/gates.py` — the ten gates, run so the answer cannot be lost.

The runner exists because the CHAIN is where they go wrong, and every
failure it guards against has happened here: a piped gate whose status
was the pipe's, a `;` that ran the next gate over a red one, and mypy's
exit code, which is non-zero for a run that found nothing but notes.

So what is tested is the joining, not the tools: that a red gate stops
the run, that the gates after it do not run, and that mypy is judged on
its LINES.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import gates  # noqa: E402  # pyright: ignore[reportMissingImports]

OK = [sys.executable, "-c", "print('fine')"]
RED = [sys.executable, "-c", "import sys; print('boom'); sys.exit(1)"]
NOTES = [sys.executable, "-c", "print('note: a note is not an error')"]
ERRORS = [sys.executable, "-c", "print('x.py:1: error: no')"]

#: Any path that is NOT this checkout's src, so the assertions below
#: cannot pass by inheriting the runner's own environment.
ELSEWHERE = "/some/other/checkout/src"


def _run(*gate_list):
    said: list[str] = []
    code = gates.run(gate_list, say=said.append)
    return code, "\n".join(said)


def _gate_saw_pythonpath(tmp_path: Path) -> str:
    """What `PYTHONPATH` a gate is actually run with.

    Through a FILE rather than the gate's printed line, because the
    runner truncates that line: the first version of these tests read it
    and so passed in a short checkout and failed in one whose path was
    long — the same shape of environment-dependent answer the fix below
    is about.
    """
    out = tmp_path / "pythonpath.txt"
    gates.run((("env", [sys.executable, "-c",
                        "import os, pathlib; pathlib.Path(r'" + str(out) +
                        "').write_text(os.environ.get('PYTHONPATH', ''),"
                        " encoding='utf-8')"], False),),
              say=lambda _line: None)
    return out.read_text(encoding="utf-8")


def test_a_gate_imports_THIS_checkouts_source_not_the_installed_one(
        monkeypatch, tmp_path):
    """The defect this closes is the worst shape a gate can have: it did
    not fail, it answered a different question.

    `gates.py` puts its own `src` on `sys.path`, but a gate is a
    SUBPROCESS and inherited none of that. The package is installed
    editable, so `import docxkit` in the child resolved through the
    install — to the one checkout the install points at — whatever
    worktree the chain was started from. Measured 2026-09-18: with a
    worktree's own `wordcount.py` deliberately broken, a bare pytest in
    that worktree reported 18 passed, because it imported another
    checkout's source. Every branch in that day's campaign that ran this
    chain without setting `PYTHONPATH` by hand gated master and said ok.
    """
    monkeypatch.setenv("PYTHONPATH", ELSEWHERE)

    got = _gate_saw_pythonpath(tmp_path)

    assert got.split(os.pathsep)[0] == str(gates.ROOT / "src"), (
        f"this checkout's src must come FIRST in a gate's PYTHONPATH; "
        f"the gate saw {got!r}")


def test_a_gate_KEEPS_a_PYTHONPATH_the_caller_already_set(
        monkeypatch, tmp_path):
    """Prepended, not replaced. The mutation tools point `PYTHONPATH` at
    a measurement worktree, and a gate run under one must not lose it."""
    monkeypatch.setenv("PYTHONPATH", ELSEWHERE)

    assert ELSEWHERE in _gate_saw_pythonpath(tmp_path).split(os.pathsep)


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


def test_the_real_list_is_the_ten_CONTRIBUTING_names():
    """A runner that drifts from the documented gates is worse than
    none: it would report a pass over a gate nobody ran.

    `optionals` joined on 2026-09-18: it asks whether an `X | None` can
    ever BE None, which no type checker asks — mypy and pyright both
    pass over `PromoteReport.redline: Path | None = None`, written
    beside a `promote` that either raised or returned a real path, and
    over the `if report.redline is not None:` that grew in
    `cmd_revision_promote` and could not be taken. The second of that
    shape was found in the same file the same afternoon, which is what
    makes it a gate and not a note. Mutation testing cannot see it
    either: a branch no input reaches has no mutant that dies.

    `deps` joined on 2026-09-02: it asks whether the SHIPPED package
    imports anything it does not declare, which no other gate sees and
    running the code here cannot either — the package is installed on
    this machine, which is exactly why three extras shipped undeclared
    and only a clean checkout ever noticed.

    `api` joined on 2026-08-31: it asks whether the public surface
    still matches what a consumer was written against, which no other
    gate here can see — `test_api_surface` pins that a name is LISTED,
    not that its signature held.

    `sweep` joined on 2026-08-30. It is the one that usually SKIPS —
    there is no corpus on most machines and none on any CI runner — and
    it is in the list precisely because of that: an unrun gate is
    invisible, an unrunnable one prints a line asking to be given a
    corpus on every single chain.
    """
    assert [name for name, _argv, _reads in gates.GATES] == [
        "ruff", "mypy", "pyright", "optionals", "pytest", "floors", "api",
        "deps", "sweep", "committed"]
    assert [g for g in gates.GATES if g[2]] == [g for g in gates.GATES
                                                if g[0] == "mypy"]


def test_sweep_runs_AFTER_the_suite_and_BEFORE_committed():
    """Order is the contract. It costs minutes over a real corpus, so it
    must not stand in front of the gates that answer in seconds; and
    `committed` stays last for the reason its own comment gives."""
    names = [name for name, _argv, _reads in gates.GATES]

    assert names.index("sweep") > names.index("pytest")
    assert names.index("sweep") < names.index("committed")


# --- a gate that did not run --------------------------------------------


SKIP = [sys.executable, "-c",
        "import sys; print('SKIPPED: no corpus'); sys.exit(3)"]


def test_a_SKIPPED_gate_is_not_a_failure():
    """Exit 3 means "I did not run". The chain continues, because there
    is nothing to fix — the machine has no corpus."""
    code, said = _run(("sweep", SKIP, False), ("committed", OK, False))

    assert code == 0
    assert "committed" in said, "a skip must not stop the chain"


def test_a_SKIPPED_gate_does_not_print_ok():
    """The whole reason for the third exit code.

    `ok sweep` over zero documents and `ok sweep` over 347 are the same
    line, and this is the gate whose entire subject is the document
    nobody anticipated. If a skip reads as a pass, the corpus never gets
    configured and nobody finds out.
    """
    _code, said = _run(("sweep", SKIP, False))

    assert "skip    sweep" in said
    assert "ok      sweep" not in said


def test_a_SKIPPED_gate_shows_its_REASON():
    """A skip is only useful if it says what to set to un-skip it."""
    _code, said = _run(("sweep", SKIP, False))

    assert "SKIPPED: no corpus" in said


def test_a_gate_that_FAILS_is_still_a_failure_beside_the_skip_code():
    """3 is the skip; 1 is still red. Read as "non-zero is fine now" the
    change would have disarmed every gate in the chain."""
    code, said = _run(("sweep", RED, False))

    assert code == 1
    assert "FAILED  sweep" in said


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


def test_two_PROCESSES_do_not_share_one_coverage_report():
    """The report is a handoff between two gates, and its name used to
    be fixed. Two gate runs on one machine — two sessions on this repo
    is the ordinary case here, not the exotic one — would then clobber
    each other's report and hand `floors` somebody ELSE's coverage:
    read as a floor failure in code the reader never touched, or read
    as a pass. Asked of a real second process, because that is the
    thing being claimed."""
    argv = [sys.executable, "-c",
            "import sys; sys.path.insert(0, 'tools'); "
            "import gates; print(gates.COVERAGE_JSON)"]
    done = subprocess.run(argv, cwd=gates.ROOT, capture_output=True,
                          text=True, check=True)

    assert done.stdout.strip() != str(gates.COVERAGE_JSON)


def test_the_chain_does_not_LEAVE_its_coverage_report_behind(tmp_path):
    """Scratch between two gates, and a chain that stops at gate one
    still wrote it. Left behind, it accumulates a copy per run in the
    temp directory forever."""
    gates.COVERAGE_JSON.write_text("{}", encoding="utf-8")
    stop = ("stop", [sys.executable, "-c", "raise SystemExit(1)"], False)

    assert gates.run([stop], say=lambda _: None) == 1
    assert not gates.COVERAGE_JSON.exists()


@pytest.mark.parametrize("out, code, why", [
    ("python.exe: No module named mypy", 1, "not installed"),
    ("mypy: error: unrecognized config option", 2, "a bad config key"),
    ("", 137, "killed by the OOM killer, no output at all"),
])
def test_a_mypy_that_did_NOT_RUN_is_not_a_mypy_that_found_nothing(out, code,
                                                                  why):
    """This gate reads mypy's LINES because its exit code is not usable:
    non-zero for a run that found nothing but notes. Reading only the
    lines is not usable either, and that half was missing.

    A checkout installed without `[dev]` prints "No module named mypy",
    exits 1, and contains no `: error` — so the gate said `ok` and the
    chain went on to the next one. That is "a type error read as a
    pass", the defeat this module exists to describe, reached without a
    pipe being involved."""
    mypy = next(g for g in gates.GATES if g[0] == "mypy")

    assert gates._failed(mypy, out, code), why


def test_mypy_NOTES_on_a_non_zero_exit_are_still_not_a_failure():
    """The reason the gate reads lines at all. Losing this to the fix
    above would make every run with a note in it red."""
    mypy = next(g for g in gates.GATES if g[0] == "mypy")
    out = ("src/x.py:3: note: a hint\n"
           "Success: no issues found in 1 source file")

    assert not gates._failed(mypy, out, 1)


def test_a_chatty_TAIL_does_not_push_the_failure_out_of_the_window():
    """The window used to be `out[-3000:]`, anchored to the END, so a
    gate that says anything after its verdict buries it.

    Measured 2026-09-06: a red pytest under `-n 8` printed sixteen
    `PytestBenchmarkWarning` lines after the summary, and the assertion
    that had failed was outside the window entirely — the chain had to
    be re-run piped through `grep` to find out what broke. That plugin
    is fixed at source; this holds the RUNNER to it, for the next gate
    that grows a tail."""
    noise = "\n".join(f"  PytestBenchmarkWarning: line {i}"
                      for i in range(400))
    out = ("FAILED tests/test_readme.py::test_every_module_has_a_row\n"
           "E   assert 'timings' in rows\n" + noise)
    assert len(out) > 3000, "the fixture has to overflow the window"

    shown = gates._failure(out)

    assert "FAILED tests/test_readme.py::test_every_module_has_a_row" in shown
    assert "E   assert 'timings' in rows" in shown
    assert len(shown) <= 3400


def test_the_failure_window_keeps_the_TAIL_when_nothing_is_cut():
    """The tail is the default and stays it: a gate whose last words
    ARE its verdict must not be rearranged, and short output passes
    through whole."""
    short = "boom\n1 failed in 0.4s"
    assert gates._failure(short) == short

    quiet = "prelude\n" * 2000 + "FAILED tests/test_z.py::test_end"
    shown = gates._failure(quiet)

    assert shown.endswith("FAILED tests/test_z.py::test_end")
    assert "characters omitted" not in shown
