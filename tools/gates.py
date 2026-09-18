#!/usr/bin/env python
"""Run the nine gates in order and say which one stopped.

    python tools/gates.py

CI runs them on 3.14 with every step reporting
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

Two of the nine can SKIP. `sweep` needs a corpus of real manuscripts,
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
import time
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docxkit import timings as timings_mod
from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]


def _child_env() -> dict[str, str]:
    """The environment for a gate, with THIS checkout's `src` in front.

    The line above puts it on `sys.path` for this process; a gate is a
    SUBPROCESS and inherited none of it. The package is installed
    editable, so `import docxkit` in a child resolved through the
    install — to `D:/docxkit/src` — whatever checkout the chain was
    started from. A worktree therefore gated the source of ANOTHER
    checkout while reporting on its own: every branch in the 2026-09-18
    campaign that ran this chain without setting `PYTHONPATH` by hand
    tested master's `src` against its own tests, and said `ok`.

    That is the worst shape a gate can have. It does not fail, it
    answers a different question — and the answer it gives is the one
    the reader wanted for a different tree.
    """
    env = dict(os.environ)
    ahead = str(ROOT / "src")
    have = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{ahead}{os.pathsep}{have}" if have else ahead
    return env


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

#: Where a run's timings land. ONE FILE PER RUN, for the reason the
#: comment above gives about the coverage report: two sessions on this
#: repo is the ordinary case, and a shared append is a shared file. A
#: JSONL line is usually written atomically and "usually" is the whole
#: problem — a torn line is an unparseable history, discovered by the
#: reader weeks later with no way to tell which run was lost.
#:
#: Timing is recorded and never GATED. A slow gate is a fact about this
#: machine's afternoon — a laptop on battery, a sweep in the next
#: window, Defender reading the tree — and a threshold over that would
#: fail builds for the weather. `tools/timings.py` reads these; nothing
#: fails on them.
TIMINGS = ROOT / ".timings"


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
    # `--durations` costs nothing and is the only per-TEST cost anybody
    # gets: this gate is most of the chain, and "pytest took 30s" cannot
    # be acted on while "these six tests took 9s of it" can. The block
    # prints ABOVE the summary line, so `_summary` still finds the
    # count — checked, because that function takes the LAST matching
    # line and a durations line says "call".
    # A static read of the package — two seconds — asking the one
    # question the type checkers cannot: not "is this Optional handled"
    # but "can it ever BE None". `PromoteReport.redline` was
    # `Path | None = None` while `promote` either raised or returned a
    # real path, so `cmd_revision_promote` grew an `is not None` branch
    # nothing could take; the second of that shape turned up in the same
    # file the same afternoon. mypy and pyright pass over both, because
    # neither is a type error — it is a claim about the code that is not
    # true. In front of the suite because it costs two seconds and
    # answers about the source alone.
    #
    # `--callers tests`: the suite is a caller like any other, and a
    # default no shipped code omits but one test does is a live branch.
    # Expected answer 0; it fails only on an Optional something READS as
    # optional, so a field added before its first test is not a toll.
    ("optionals", [sys.executable, "tools/optional_audit.py",
                   "--callers", "tests"], False),
    # `--cov=tests` measures the TEST files as well, for `unrun` below.
    # It costs 14.5 s of this gate's 57 (measured 2026-09-18, alternating
    # arms at `-n 8`), and it is the price of the one question nothing
    # else in the chain can ask: did that assertion RUN. `floors` ignores
    # the extra entries — it walks its own declared list — so the two
    # readers of this report do not have to agree about what is in it.
    ("pytest", [sys.executable, "-m", "pytest", "-q", "-n", _workers(),
                "--durations=25", "--durations-min=0.05",
                "--cov=docxkit", "--cov=tests",
                f"--cov-report=json:{COVERAGE_JSON}"],
     False),
    ("floors", [sys.executable, "tools/coverage_floor.py",
                "--from-json", str(COVERAGE_JSON)], False),
    # The same report, the other question. `floors` asks whether a
    # module is still as covered as it was, in percentages; this asks
    # which ASSERTION did not run, in file:line — a test that passes
    # without asserting anything, which no other gate here can see and
    # mutation testing cannot either, since a test that asserts nothing
    # kills nothing and does not move the figure. One tool, one
    # question, which is why `sweep`, `api` and `deps` are three lines.
    # It refuses (exit 3) rather than passing if the report holds no
    # test files, because "0 findings" over nothing read is the failure
    # it exists to catch.
    ("unrun", [sys.executable, "tools/unrun_assertions.py",
               "--from-json", str(COVERAGE_JSON)], False),
    # Half a second, and it holds a rule nobody was keeping. A fix
    # EXPIRES the claims on the lines it changes, and deleting them
    # belongs in the fix's own commit — but nothing checked, because the
    # full `verify_equivalents` applies every claim and runs the harness
    # for each, which is minutes per module and cannot sit here.
    #
    # So it went unkept. `4ce85a7` added a conjunct to two claimed lines
    # of `_cite_grammar.py` and left four claims behind — three of them
    # arguing "the half is empty either way", the very assumption that
    # commit disproved by finding a tab and a no-break hyphen dropped
    # from the page. That module's claim check exited 1 for everyone
    # from then on and nobody saw it. Switching this on found four MORE
    # the same afternoon, in `find.py` and `probe.py`, from fixes nobody
    # had connected to a claim at all (2026-09-18).
    #
    # It asks only whether each `was` still names exactly one line of
    # its module. It cannot see a claim that has started being KILLED;
    # that is still the full check's job, per module, in a round.
    ("claims", [sys.executable, "tools/verify_equivalents.py",
                "--anchors"], False),
    # Cheap (2 s) and about the OTHER consumer: nine papers import this
    # package from an editable install, so they run the tip, and a
    # signature that moved under a name `test_api_surface` still finds
    # is an error at their next round rather than at this edit. Only the
    # eleven breakage kinds that break a CALL fail it — the twelfth,
    # a constant's value, is reported. See the tool for the measurement.
    ("api", [sys.executable, "tools/api_check.py"], False),
    # Does anything in this repository import what it does not declare?
    # The one question `pyproject.toml` has been wrong about four times
    # — latex2mathml, pymupdf, pandas and cosmic-ray — and every time it
    # was a clean checkout that found out, days later. It cannot be
    # noticed locally by running the code, because everything is
    # installed HERE; that is the whole reason this needs a tool.
    #
    # `tools` joined `src` on 2026-09-18, after the fourth one arrived
    # THERE and this gate reported success over it: `render_survivors.py`
    # imports cosmic-ray, which is in no extra and on no CI runner, and
    # the push that merged it took mypy and pytest down together. A gate
    # scoped to the shipped package answers for the shipped package; the
    # tools are how the shipped package is measured, and a tool that
    # cannot be imported is a gate that cannot run. Scoped and
    # configured in `[tool.deptry]`, where the reasoning is.
    ("deps", [sys.executable, "-m", "deptry", "src", "tools"], False),
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
                      r"0 errors|at or above|SKIPPED|swept|breaking|"
                      r"dependency issues)\b")


#: A gate is free to colour its own output — `deptry` does, and so does
#: griffe underneath `api`. Captured through a pipe those escapes are
#: literal noise around the one line this runner prints, and they reach
#: a CI log verbatim. Stripped HERE rather than argued with each gate:
#: the runner is what decides how a summary looks.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _summary(out: str) -> str:
    """The line a reader wants from a gate that PASSED."""
    lines = [_ANSI.sub("", ln).strip()
             for ln in out.strip().splitlines() if ln.strip()]
    said = [ln for ln in lines if _SUMMARY.search(ln)]
    return (said or lines or [""])[-1]


#: What a gate's own summary looks like when it FAILED. The mirror of
#: `_SUMMARY`, and it did not exist: the failing path printed a fixed
#: window anchored to the END of the output and hoped the reason was in
#: it. Measured 2026-09-06 — a red `pytest` under `-n 8` emitted sixteen
#: `PytestBenchmarkWarning` lines AFTER its summary, which is 3000
#: characters of nothing, and the assertion that had actually failed was
#: outside the window entirely. The plugin was the instance; a chatty
#: tail is the defect, and any gate may grow one.
_FAILURE = re.compile(r"^(FAILED|ERROR)\b"          # pytest's summary rows
                      r"|^E\s{3}"                    # its assertion detail
                      r"|^\s*File \""                # a traceback's frames
                      r"|\bFound \d+ error"          # ruff
                      r"|: error:"                   # mypy, pyright
                      r"|^=+ .*(failed|error).*=+$"  # pytest's last banner
                      r"|^\s*(assert|raise)\b",      # the line itself
                      re.IGNORECASE)


def _failure(out: str, limit: int = 3000) -> str:
    """What a reader needs from a gate that FAILED, within `limit`.

    The tail is kept — a gate's last words are usually its verdict — but
    never at the cost of the lines that say what broke. Those are
    selected the way `_summary` selects for the passing case, and any
    that the tail would have cut are printed above it under a marker
    saying how much was dropped between the two.
    """
    text = _ANSI.sub("", out.strip())
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    named = [ln.rstrip() for ln in text.splitlines()
             if ln.strip() and _FAILURE.search(ln)]
    missed = [ln for ln in named if ln not in tail]
    if not missed:
        return tail
    # The failure first, then as much of the tail as the budget leaves.
    # Both halves are bounded: a suite failing 300 tests would otherwise
    # push its own verdict out of the window a second way.
    head = "\n".join(missed[-25:])[:limit // 2]
    room = max(limit - len(head) - 80, 200)
    dropped = len(text) - room
    return (f"{head}\n"
            f"... [{dropped} characters omitted; the lines above are "
            f"outside the last {room}] ...\n"
            f"{text[-room:]}")


#: pytest's own `--durations` block, which the pytest gate asks for. The
#: per-TEST costs are the actionable half: that gate is most of the
#: chain, and "pytest took 30s" cannot be acted on while "these six
#: tests took 9s of it" can.
_DURATION = re.compile(r"^([\d.]+)s\s+(call|setup|teardown)\s+(\S+)",
                       re.MULTILINE)


def _durations(out: str, limit: int = 25) -> list[dict[str, object]]:
    """The slowest tests pytest named, as data."""
    found = [{"seconds": float(secs), "phase": phase, "test": test}
             for secs, phase, test in _DURATION.findall(out)]
    return found[:limit]


def _record(entries: list[dict[str, object]], outcome: str,
            into: Path) -> Path | None:
    """Write one chain run's timings, in the shape a paper's batch uses.

    `docxkit.timings` owns the format so that ONE reader serves both
    producers: this chain and any paper that keeps its `batch.run`
    durations. Two shapes would mean two readers, and the analyst on top
    of them would have to know which was which.

    **How loaded the machine was goes in with the numbers**, because
    without it the regression reader cannot tell a slow suite from a
    busy afternoon — and during a mutation campaign every afternoon is
    busy, for days. `mutation_session` writes a `.running` marker per
    live sweep, so counting them costs a `glob` and answers exactly the
    question the timings cannot answer for themselves.
    """
    live = len(list(ROOT.glob(".mutation-*.running")))
    return timings_mod.record("gates", "chain", entries, into,
                              outcome=outcome,
                              extra={"sweeps": live} if live else None)


def _say_behind(say: Callable[[str], None]) -> None:
    """Say how far this checkout is behind master, if it is behind.

    **A green chain on a stale base is not evidence that the work
    integrates**, and it reads exactly as though it were. On 2026-09-18
    a round came back with eleven gates green and `7411 passed` over a
    defect that master had already fixed hours earlier, in a worktree
    ~750 tests behind: the fix cherry-picked EMPTY, and the round's
    other conclusion — "a stale claim on master" — was true only of its
    own base. Nothing in the chain mentioned the gap, because every gate
    it runs is a question about the tree it is standing in.

    A worktree legitimately lags while a round is worked, so this never
    fails and never changes the exit code. It is said at the END, beside
    the timing regressions, for the same reason: the chain's verdict is
    about the code, and this is about the afternoon.
    """
    try:
        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..master"],
            cwd=ROOT, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace")
        behind = int(out.stdout.strip() or 0)
    except (OSError, ValueError):               # no git, no master, no answer
        return
    if behind:
        say(f"behind  master by {behind} commit(s) — a green chain here "
            f"is not evidence the work integrates; rebase before you "
            f"hand it over")


def _say_regressions(folder: Path, say: Callable[[str], None]) -> None:
    """Name any gate that has genuinely got slower, right here.

    **This is the monitor, and it is deliberately not an agent.** The
    history only changes when somebody runs this chain, so polling it on
    a clock watches unchanged data almost every time it wakes; and every
    scheduler available on the agent side — cron jobs, Monitor watches,
    cloud routines — lives only as long as one session, while this
    outlives every session and needs nothing switched on.

    The moment the data appears is the moment to read it, and the reader
    is already written. Silent when there is nothing, because a line
    that says "no regressions" after every green chain is a line people
    stop seeing.

    Never raises and never changes the exit code: the chain's verdict is
    about the code, and this is about the afternoon.
    """
    try:
        moved = timings_mod.regressions(timings_mod.read(folder))
    except Exception:
        return
    for delta, name, was, now, n in moved:
        say(f"slower  {name}  {was:.1f}s -> {now:.1f}s (+{delta:.1f}s) "
            f"over {n} runs — python tools/timings.py")


def run(gates: Sequence[Gate] = tuple(GATES),
        say: Callable[[str], None] = print,
        timings: Path | None = None) -> int:
    """Run each gate until one fails; return the number that failed.

    `timings` defaults to None — writing is opt-in, and only `__main__`
    opts in. It defaulted to the real folder for about ten minutes, and
    the first report off it read "3 chain runs recorded" after ONE:
    `tests/test_gates.py` drives this function with synthetic gates
    named `first`, `second`, `mypy`, and every one of those runs filed
    a record. The medians were then computed over a real chain and two
    suites of fakes, so the whole chain read as 0.0s and the real
    `mypy` gate — which takes seconds over 221 files — sorted into
    "under 0.5s and not worth optimising".

    A history is only worth keeping if everything in it is the same
    kind of event. The default is the guard on that, because the test
    suite is a caller like any other and should not have to know.
    """
    entries: list[dict[str, object]] = []
    outcome = "green"
    try:
        for gate in gates:
            name, argv, _reads = gate
            began = time.perf_counter()
            done = subprocess.run(argv, cwd=ROOT, capture_output=True,
                                  text=True, encoding="utf-8",
                                  errors="replace", check=False,
                                  env=_child_env())
            seconds = round(time.perf_counter() - began, 2)
            out = done.stdout + done.stderr
            entry: dict[str, object] = {"name": name, "seconds": seconds}
            entries.append(entry)
            if _failed(gate, out, done.returncode):
                entry["status"] = "failed"
                outcome = f"failed:{name}"
                say(f"FAILED  {name}")
                say(_failure(out))
                return 1
            if done.returncode == SKIPPED:
                entry["status"] = "skipped"
                # The reason, not a summary line: a skip is only useful
                # if it says what to set to un-skip it.
                say(f"skip    {name}  {_summary(out)[:90]}")
                continue
            entry["status"] = "ok"
            if (slowest := _durations(out)):
                entry["slowest_tests"] = slowest
            say(f"ok      {name}  {_summary(out)[:90]}")
        return 0
    finally:
        _say_behind(say)
        if timings is not None and entries:
            _record(entries, outcome, timings)
            _say_regressions(timings, say)
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
    raise SystemExit(run(timings=TIMINGS))
