#!/usr/bin/env python
"""The test command a mutation session runs: the covering tests FIRST.

    # once, when the session is planned
    python tools/mutant_tests.py --build tracked src/docxkit/tracked.py \
        -- -q tests/test_tracked_build.py tests/test_tracked_guard.py

    # per mutant, as cosmic-ray's test-command
    python tools/mutant_tests.py --deadline 30 tracked src/docxkit/tracked.py \
        -- -q -x --timeout=30 tests/test_tracked_build.py ...

cosmic-ray runs ONE fixed command for every mutant, and that command is
the whole harness: `tracked.py`'s takes 6.5s, of which 0.75s is pytest
starting up and the rest is 288 tests, nearly all of which cannot touch
the line that was mutated. There is no per-mutant test selection in
cosmic-ray — the config carries a single `test-command` string and the
worker never learns which mutation it is running.

It can find out for itself. The session snapshots the module when it
plans the run (`mutation_session.take_snapshot`), so the mutated line is
the first line where the file in the worktree differs from that
snapshot, and a coverage run with `--cov-context=test` says which tests
execute it.

**Two phases, and the second is what makes it safe.**

1. Run the tests that cover the mutated line. If one FAILS, the mutant
   is killed — that test is in the harness, so the full run would have
   failed too, and there is nothing more to learn.
2. Otherwise run the whole harness and report what it says.

So a survivor is never declared by the short run: it is declared by the
same command the session would have used anyway. The only thing the
coverage map can cost is time — a map that is wrong or stale sends work
to phase 2, which is where it would have been without this file.

That asymmetry is the point: kills are the common case, and a kill
decided by three tests costs what pytest's start-up costs.

**What it is worth, measured** (120 mutants, verdicts compared one by
one, zero differences):

    _table_layout   350s -> 306s   (13%)
    tracked         SLOWER

The second is the honest half. `_table_layout`'s harness is 302 tests in
2.4s — eight milliseconds each — so running three of them instead of all
of them saves nearly the whole run. `tracked`'s is 288 tests in 5.5s
because a handful drive a fake Word pipeline for five seconds each; when
one of those covers the mutated line, phase 1 costs almost what the
whole harness costs and phase 2 then runs anyway.

So: worth it for a harness of many cheap tests, not for one with a few
slow ones. It is opt-in (`--fast`) for that reason, and the bigger lever
was elsewhere — turning OFF pytest's plugin autoload took 15-46% off
every mutant of every module, unconditionally.

The map is keyed to the snapshot, so it ages exactly as the session
does: `--fresh` rebuilds both.

**It ends its own pytest at `--deadline`, and it has to.** cosmic-ray
ends a test command that outlives its timeout by killing the process
group; on Windows `os.killpg` does not exist, so it falls back to killing
the ONE process it started — this wrapper — and then waits, with no
timeout, on the pipes the pytest under it still holds. One mutant
(`rest - value` -> `rest ** value` in `sections._format`, a loop computing
in C, where pytest-timeout's thread cannot interrupt it) held a sweep at
459/460 for seventy minutes that way and left eleven such pytests running
(BACKLOG, 2026-09-13). A run still going at the deadline is ended here and
reads as KILLED, cosmic-ray's own verdict for a timeout; the session sets
cosmic-ray's limit above the deadline, so this one always acts first.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def map_path(stem: str) -> Path:
    return ROOT / f".mutation-{stem}.coverage.json"


def snapshot_path(stem: str, module: str) -> Path:
    return ROOT / f".mutation-{stem}.pristine" / module


def _enclosing(module: str, line: int,
               direct: dict[int, set[str]]) -> set[str]:
    """The tests that reach the FUNCTION a line sits in.

    A mutation on a `def` line — every default value lives there — or on
    a decorator runs at import time, where coverage records no test
    context at all. Falling back to the whole harness for those gives up
    the common case: a default argument is exactly the kind of mutant
    the covering tests kill.
    """
    for start, end in _function_spans(module):
        if start <= line <= end:
            return {t for ln in range(start, end + 1)
                    for t in direct.get(ln, ())}
    return set()


def _function_spans(module: str) -> list[tuple[int, int]]:
    import ast  # noqa: PLC0415  (only the builder needs it)

    tree = ast.parse(Path(module).read_text(encoding="utf-8"))
    spans = [(n.lineno, n.end_lineno or n.lineno) for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    return sorted(spans, key=lambda s: s[1] - s[0])   # innermost first


def build_map(stem: str, module: str, pytest_args: list[str]) -> int:
    """Record which tests execute each line of `module`.

    Run in the worktree, against the same harness the session uses, so
    the line numbers are the ones the mutants are recorded against.
    """
    import coverage  # noqa: PLC0415  (only the builder needs it)

    dotted = "docxkit." + Path(module).stem
    data_file = ROOT / f".mutation-{stem}.covdata"
    for stale in data_file.parent.glob(f"{data_file.name}*"):
        stale.unlink()
    env = {**os.environ, "COVERAGE_FILE": str(data_file)}
    subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         "-p", "pytest_cov", f"--cov={dotted}", "--cov-context=test",
         "--cov-report=", *pytest_args],
        env=env, check=False)

    data = coverage.CoverageData(basename=str(data_file))
    data.read()
    wanted = Path(module).name
    files = [f for f in data.measured_files() if Path(f).name == wanted]
    if not files:
        print(f"no coverage recorded for {module}", file=sys.stderr)
        return 1
    by_line = data.contexts_by_lineno(files[0])
    direct = {line: {c.split("|")[0] for c in contexts if c}
              for line, contexts in by_line.items()}
    out = {str(line): sorted(tests or _enclosing(module, line, direct))
           for line, tests in direct.items()}
    map_path(stem).write_text(json.dumps(out), encoding="utf-8")
    covered = sum(1 for tests in out.values() if tests)
    print(f"  covering tests recorded for {covered} line(s) of {module}",
          flush=True)
    return 0


def mutated_lines(stem: str, module: str) -> list[int]:
    """Which lines the live file no longer shares with the snapshot.

    A cosmic-ray mutation rewrites the module in place, so the answer is
    a plain line-by-line comparison. An empty answer means the tree is
    unmutated (the baseline run) or the snapshot is missing, and both
    take the whole harness.
    """
    kept = snapshot_path(stem, module)
    live = Path(module)
    if not (kept.is_file() and live.is_file()):
        return []
    was = kept.read_text(encoding="utf-8").splitlines()
    now = live.read_text(encoding="utf-8").splitlines()
    if len(was) != len(now):
        return []                  # a whole-file change: no line to pick
    return [i for i, (a, b) in enumerate(zip(was, now, strict=True), 1)
            if a != b]


def covering_tests(stem: str, lines: list[int]) -> list[str]:
    path = map_path(stem)
    if not lines or not path.is_file():
        return []
    covering = json.loads(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for line in lines:
        found.update(covering.get(str(line), ()))
    return sorted(found)


def run(args: list[str], deadline: float | None = None) -> int:
    """pytest over `args`. One still running at `deadline` (a
    `time.monotonic()`) is ended, and reads as a failure — see the module
    docstring for why that cannot be left to cosmic-ray."""
    left = None if deadline is None else max(0.0, deadline - time.monotonic())
    try:
        return subprocess.run([sys.executable, "-m", "pytest", *args],
                              check=False, timeout=left).returncode
    except subprocess.TimeoutExpired:
        print("mutant_tests: the harness ran past its deadline and was "
              "ended — a mutant that hangs the tests is killed", flush=True)
        return 1


def _is_test(arg: str) -> bool:
    return "::" in arg or Path(arg).exists()


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print(__doc__)
        return 2
    head, pytest_args = argv[:argv.index("--")], argv[argv.index("--") + 1:]
    if head and head[0] == "--build":
        return build_map(head[1], head[2], pytest_args)
    deadline: float | None = None
    if head[:1] == ["--deadline"]:
        deadline = time.monotonic() + float(head[1])    # ONE budget, both runs
        head = head[2:]
    stem, module = head[0], head[1]

    tests = covering_tests(stem, mutated_lines(stem, module))
    if tests:
        # Every flag the session passes, and only the tests that reach
        # the mutated line. The flags are whatever is not a test: a
        # value like `pytest_timeout` belongs to the `-p` before it, and
        # dropping it once turned a malformed command into 21 false
        # KILLS in an A/B run — which is why the exit code below is read
        # narrowly.
        quick = [a for a in pytest_args if not _is_test(a)] + tests
        # ONLY pytest's "tests failed" (1) settles a mutant. A usage
        # error (4), a collection error (2, 3), "no tests collected"
        # (5) — anything that is not a verdict falls through to the
        # whole harness, which is where this file's safety lives.
        if run(quick, deadline) == 1:
            return 1
    return run(pytest_args, deadline)



if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
