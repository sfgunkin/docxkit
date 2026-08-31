#!/usr/bin/env python
"""Run the eight gates in order and say which one stopped.

    python tools/gates.py

CI runs them on 3.12, 3.13 and 3.14 with every step reporting
independently. Locally they are a chain, and the chain is where they go
wrong:

* `pyright | tail -1` returns TAIL's status, so a type error read as a
  pass. Written up in CONTRIBUTING, and then done again on 2026-08-20 as
  `pytest -q | tail -2`, which put a red suite into master;
* `;` instead of `&&` runs every gate whatever the last one said, and
  has shipped a lint failure twice;
* `mypy`'s exit code is not usable here — it is non-zero for a run that
  found nothing but notes — so the gate is "no line matching `: error`",
  which is what this applies.

Nothing here is new: it is the same commands CONTRIBUTING lists, run so
that the answer cannot be lost between them. Exit status is 0 only when
all of them pass, and the first failure stops the run — a gate after a
red one tells you nothing you can act on yet.

Two of the eight can SKIP. `sweep` needs a corpus of real manuscripts,
which no CI runner has and most machines do not either, so it exits 3
and prints what to set. That is a third state on purpose: `ok` over
zero documents and `ok` over 347 are the same line, and the corpus gate
is the one where the difference is the entire point. `api` skips the
same way, and for the same reason: with neither a tag nor an upstream
branch there is no baseline to compare a public surface against, and a
comparison against nothing must not print the word a clean one prints.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]

#: (name, argv, reads-stdout). The third says the gate is judged by its
#: OUTPUT rather than its exit code — `mypy` is the only one.
Gate = tuple[str, list[str], bool]

#: Where the one coverage run puts its report, for the floors gate to
#: read. In the temp directory rather than the tree: it is derived, it is
#: rewritten on every run, and a stray copy in the repo would be
#: committed by somebody eventually.
#:
#: Per PROCESS, and that is not decoration. A fixed name is one shared
#: file, and two gate runs on one machine — two sessions on this repo is
#: the ordinary case, not the exotic one — would clobber each other's
#: report and hand `floors` somebody else's coverage. It would read as a
#: floor failure in code the reader had not touched, or worse as a pass.
#: Written as a fixed name first, and caught while scoping a review of
#: the change: the same one-shared-resource shape as the `kill_check`
#: lock, hours later, in a different costume.
COVERAGE_JSON = (Path(tempfile.gettempdir())
                 / f"docxkit-gates-coverage-{os.getpid()}.json")


def _workers() -> str:
    """How many pytest workers, measured on this suite rather than
    assumed.

    4971 tests: serial 108 s, `-n 4` 45.5 s, `-n 8` 37.1 s, `-n auto`
    (16 logical) 53.4 s. The knee is at the PHYSICAL core count —
    oversubscribing costs more than it buys, so `auto` is the wrong
    default on an SMT machine. Half the logical count is the physical
    count wherever SMT is on and a safe under-estimate where it is not.
    """
    return str(max(2, min(8, (os.cpu_count() or 4) // 2)))


GATES: list[Gate] = [
    ("ruff", [sys.executable, "-m", "ruff", "check", "."], False),
    ("mypy", [sys.executable, "-m", "mypy"], True),
    ("pyright", [sys.executable, "-m", "pyright"], False),
    # ONE run of the suite, under coverage, across the cores. It used to
    # be two: this gate bare, and `floors` running the whole thing again
    # with the tracer attached — 108 s + 126 s of a 247 s chain, for the
    # same tests over the same code. `floors` reads the report this
    # writes. Coverage under `-n 8` was checked against serial and is
    # identical: 98.102 % both, not one file lower.
    ("pytest", [sys.executable, "-m", "pytest", "-q", "-n", _workers(),
                "--cov=docxkit", f"--cov-report=json:{COVERAGE_JSON}"],
     False),
    ("floors", [sys.executable, "tools/coverage_floor.py",
                "--from-json", str(COVERAGE_JSON)], False),
    # Cheap (2 s) and about the OTHER consumer: nine papers import this
    # package from an editable install, so they run the tip, and a
    # signature that moved under a name `test_api_surface` still finds
    # is an error at their next round rather than at this edit. Only the
    # eleven breakage kinds that break a CALL fail it — the twelfth,
    # a constant's value, is reported. See the tool for the measurement.
    ("api", [sys.executable, "tools/api_check.py"], False),
    # The corpus. It SKIPS without `DOCXKIT_CORPUS` (exit 3, printed as
    # `skip`), which is why it can sit in the chain at all — CI has no
    # manuscripts and never will. Named here even when it cannot run,
    # because that is the whole repair: it was a documented tool bound
    # to nothing, and an unrun gate is invisible in a way an unrunnable
    # one is not. Every chain now prints a line asking for a corpus.
    ("sweep", [sys.executable, "tools/sweep.py"], False),
    # Last on purpose. It reports on HEAD rather than on the work
    # in hand, and a broken HEAD must not stand between the author
    # and the lint error they are actually here to fix.
    ("committed", [sys.executable, "tools/verify_committed.py"],
     False),
]

#: A gate's way of saying "I did not run, and here is why". Distinct
#: from 0 so that "swept 347 documents, nothing raised" and "there were
#: no documents" cannot print the same word — which is the difference
#: between a gate and a decoration.
SKIPPED = 3


#: What mypy prints when it has finished having an opinion — either
#: one. Anything else on a non-zero exit is mypy not having run.
_MYPY_SPOKE = re.compile(r"^(Success: no issues found|Found \d+ error)",
                         re.MULTILINE)


def _failed(gate: Gate, out: str, code: int) -> bool:
    """Did this gate fail?

    `mypy`'s exit code alone is not usable: it is non-zero for a run
    that found nothing but notes, which is why this gate reads its
    LINES. Reading only the lines is not usable either, and that half
    was missing until 2026-08-24.

    `python -m mypy` on a checkout installed without `[dev]` prints
    "No module named mypy", exits 1, and contains no `: error` — so the
    gate said `ok` and the chain moved on to the next one. A bad config
    key (exit 2) and a run the OOM killer took (exit 137, no output at
    all) both did the same. That is "a type error read as a pass", the
    defeat this module's docstring exists to describe, reached without
    a pipe being involved.

    So: the lines decide when mypy SPOKE, and a non-zero exit with
    nothing that looks like mypy's own verdict is a failure of the gate
    itself.
    """
    if code == SKIPPED:
        return False
    if gate[2]:
        if any(": error" in line for line in out.splitlines()):
            return True
        return code != 0 and not _MYPY_SPOKE.search(out)
    return code != 0


#: What a gate's own summary looks like when it has one. The LAST line
#: is usually it — and once was not: a pytest run under load ended with
#: "<cannot get C stack on this system>", an interpreter note about the
#: machine rather than about the suite, and the gate reported that
#: instead of "4430 passed". A passing gate prints one line here, so
#: the one line has to be the answer.
_SUMMARY = re.compile(r"\b(passed|failed|error|no issues|All checks|"
                      r"0 errors|at or above|SKIPPED|swept|breaking)\b")


def _summary(out: str) -> str:
    """The line a reader wants from a gate that PASSED."""
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    said = [ln for ln in lines if _SUMMARY.search(ln)]
    return (said or lines or [""])[-1]


def run(gates: Sequence[Gate] = tuple(GATES),
        say: Callable[[str], None] = print) -> int:
    """Run each gate until one fails; return the number that failed."""
    try:
        for gate in gates:
            name, argv, _reads = gate
            done = subprocess.run(argv, cwd=ROOT, capture_output=True,
                                  text=True, encoding="utf-8",
                                  errors="replace", check=False)
            out = done.stdout + done.stderr
            if _failed(gate, out, done.returncode):
                say(f"FAILED  {name}")
                say(out.strip()[-3000:])
                return 1
            if done.returncode == SKIPPED:
                # The reason, not a summary line: a skip is only useful
                # if it says what to set to un-skip it.
                say(f"skip    {name}  {_summary(out)[:90]}")
                continue
            say(f"ok      {name}  {_summary(out)[:90]}")
        return 0
    finally:
        # The report is scratch between two gates, and a chain that
        # stops early still wrote it. `missing_ok` because most runs of
        # this function in the tests never reach the pytest gate at all.
        COVERAGE_JSON.unlink(missing_ok=True)


if __name__ == "__main__":                  # pragma: no cover
    # A gate's output is full of what this package works on — em dashes,
    # Cyrillic captions, the U+FFFD a decode left behind — and a
    # console that is cp1252 dies printing it. The first failure this
    # runner ever reported crashed here instead of showing itself, and
    # the pipe it was invoked through swallowed the crash as well.
    utf8_stdout()
    raise SystemExit(run())
