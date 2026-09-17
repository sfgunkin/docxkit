#!/usr/bin/env python
"""Re-check every argued equivalence in `tools/equivalents.toml`.

    python tools/verify_equivalents.py refstyle.py
    python tools/verify_equivalents.py _xml.py snapshot.py
    python tools/verify_equivalents.py --jobs 4            # the whole file

A claim there says a mutation changes the source and cannot change
behaviour. `mutation_survivors` takes those out of the denominator, so a
claim that is WRONG quietly improves the module's figure — which is the
one direction of error nobody notices, because the number moves the way
everyone hoped.

So each one is applied for real and expected to SURVIVE. A claim that is
now killed has not been vindicated: the code or the harness moved and the
argument no longer describes them. Delete it, read the mutant again, and
decide it afresh.

**What it costs.** One harness run per claim, in `kill_check`'s private
worktree, plus one unmutated run per harness — about ten seconds each on
this machine, and more for the heaviest harnesses. Scoped to a module
that is minutes, which is the everyday use CONTRIBUTING calls for after
changing a module whose claims touch the lines you moved. The WHOLE file
was 899 claims across 46 modules on 2026-09-18: hours, not minutes, and
the count only grows. This docstring said
"a minutes-long job" until 2026-09-18, the day a whole-file run went
unmade for that reason and ten claims orphaned by `effef6c` sat
unreported.

`--jobs N` is the answer to the size of it: N worker processes, each
with a kill_check checkout of its OWN (`<worktree>-1`, `-2`, …) and
therefore its own lock, since two callers in one checkout read each
other's mutations and both finish with a plausible number. Modules are
dealt out longest-first so one 62-claim module does not hold the run
open while three workers idle, and the report is assembled in the file's
own order, so two runs over one tree print the same thing. Measured
2026-09-18: 341 claims over 18 modules took 12 minutes at four workers,
against an hour and more sequentially — `cli.py` alone was 7 of those 12.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import kill_check  # pyright: ignore[reportMissingImports]
from harness_map import harness_for  # pyright: ignore[reportMissingImports]
from kill_check import check  # pyright: ignore[reportMissingImports]

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "tools" / "equivalents.toml"

#: What a worker adds after a module's block so the parent can total the
#: run without re-reading `kill_check`'s formatting. Stripped before the
#: block is printed, so it never reaches a reader.
TALLY = "::not-as-argued"

Case = tuple[str, str, str, bool]


def anchored(src: Path, stripped: str) -> str | None:
    """The claim's line as it appears in the file, indentation and all.

    A claim stores its lines stripped, because that is how
    `mutation_survivors.became` renders a mutant and the two have to
    match on sight. `kill_check` needs the real text: it insists the
    anchor occur EXACTLY once, and a stripped line either misses (the
    file has indentation) or hits several places at once.
    """
    hits = [ln for ln in src.read_text(encoding="utf-8").splitlines()
            if ln.strip() == stripped]
    return hits[0] if len(hits) == 1 else None


def cases_for(module: str, claims: list[dict[str, str]],
              say: Callable[[str], None]) -> list[Case] | None:
    """This module's claims as `kill_check` cases, None if it is gone.

    Anchoring is pure text and needs no checkout, so it happens in the
    process that REPORTS. That is what keeps the diagnostics and the
    tally in the file's own order when the checks themselves are farmed
    out to workers.
    """
    src = ROOT / "src" / "docxkit" / module
    if not src.is_file():
        say(f"MODULE GONE  {module} — its claims describe nothing")
        return None
    cases: list[Case] = []
    for claim in claims:
        old = anchored(src, claim["was"])
        if old is None:
            # Not a failure of the argument — a failure to FIND what it
            # was about, which is the same thing for a reader and must
            # not pass quietly as "survived, as claimed".
            say(f"ANCHOR GONE  {module}: {claim['was'][:60]!r} is no "
                f"longer a line of that file, or is now several")
            continue
        indent = old[:len(old) - len(old.lstrip())]
        cases.append((f"{claim['was'][:40]} -> {claim['line'][:40]}",
                      old, indent + claim["line"], False))
    return cases


def groups(sizes: dict[str, int], jobs: int) -> list[list[str]]:
    """Deal the modules into `jobs` groups of roughly equal CLAIM count.

    Longest first, each to the lightest group so far — the standard
    greedy schedule, and enough here: a run is as long as its longest
    group, and one module of 62 claims beside nineteen of two is the
    shape this file actually has. Ties break on the name, so two runs
    over one tree deal the same way.
    """
    out: list[list[str]] = [[] for _ in range(jobs)]
    load = [0] * jobs
    for module in sorted(sizes, key=lambda m: (-sizes[m], m)):
        at = load.index(min(load))
        out[at].append(module)
        load[at] += sizes[module]
    return [g for g in out if g]


def worker_env(base: Path, n: int) -> dict[str, str]:
    """A worker's environment: its OWN kill_check checkout.

    `kill_check` reads the path once, at import, so setting it here is
    what gives the child a checkout no other worker touches — and a lock
    file of its own with it, which is the rule that module states for
    itself: one caller per checkout, or each reads the other's
    mutations and both report a plausible number.
    """
    return {**os.environ, "DOCXKIT_KILL_CHECK_WORKTREE": f"{base}-{n}"}


def by_module(text: str, modules: list[str]) -> dict[str, str]:
    """A worker's output, split back into one block per module.

    Keyed on the module, with anything said BEFORE the first block —
    a checkout that would not build, a lock another caller holds — under
    the empty string, because a worker that dies says why exactly once
    and dropping it would leave the parent reporting silence.
    """
    out: dict[str, str] = dict.fromkeys(modules, "")
    out[""] = ""
    current = ""
    for line in text.splitlines(keepends=True):
        if line.startswith("--- "):
            name = line[4:].split(":", 1)[0].strip()
            if name in out:
                current = name
        out[current] += line
    return out


def tally_of(block: str) -> tuple[str, int]:
    """A module's block without its trailer, and what the trailer said.

    Counting the `!!` lines would do for the ordinary case and not for
    the worst one: when the UNMUTATED harness fails, `check` writes off
    every case at once and says so in a single line about the harness.
    Its RETURN value knows that, so the worker prints it and the parent
    adds it up — and the trailer never reaches a reader.
    """
    lines = block.splitlines()
    kept = [ln for ln in lines if not ln.startswith(TALLY)]
    said = sum(int(ln.split()[-1]) for ln in lines if ln.startswith(TALLY))
    return "\n".join(kept).strip("\n"), said


def run_here(module: str, cases: list[Case], *, worker: bool) -> int:
    """Apply this module's claims in THIS process's checkout."""
    print(f"--- {module}: {len(cases)} claim(s)", flush=True)
    bad = check(f"src/docxkit/{module}", harness_for(module), cases)
    if worker:
        print(f"{TALLY} {module} {bad}")
    return bad


def fan_out(todo: dict[str, list[Case]], jobs: int) -> int:
    """Farm the checks out to `jobs` workers; report in module order."""
    dealt = groups({m: len(c) for m, c in todo.items()}, jobs)
    base = kill_check.ROOT
    print(f"{len(todo)} module(s), {sum(len(c) for c in todo.values())} "
          f"claim(s), {len(dealt)} worker(s) under {base}-N", flush=True)

    def one(job: tuple[int, list[str]]) -> tuple[list[str], str, str]:
        n, modules = job
        began = time.perf_counter()
        done = subprocess.run(
            [sys.executable, __file__, "--worker", *modules],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=worker_env(base, n + 1), check=False)
        print(f"  worker {n + 1} done in "
              f"{round(time.perf_counter() - began)}s: {', '.join(modules)}",
              file=sys.stderr, flush=True)
        return modules, done.stdout, done.stderr

    with ThreadPoolExecutor(max_workers=len(dealt)) as pool:
        answers = list(pool.map(one, enumerate(dealt)))

    blocks: dict[str, str] = {}
    loose: list[str] = []
    bad = 0
    for modules, text, complained in answers:
        # stdout only: a mutant's own SyntaxWarning goes to stderr, and
        # attributing it to whatever block was open put `authors.py`'s
        # warnings under `compare.py`'s heading.
        found = by_module(text, modules)
        if aside := (found.pop("") + complained).strip():
            loose.append(aside)
        for module, block in found.items():
            blocks[module], said = tally_of(block)
            bad += said
    for module in sorted(todo):
        print("\n" + (blocks.get(module)
                      or f"--- {module}: its worker said nothing — it died "
                         f"before this module ran"))
        if not blocks.get(module):
            bad += len(todo[module])
    for aside in loose:
        print(f"\na worker also said:\n{aside}")
    return bad


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Apply every argued equivalence and expect it to "
                    "SURVIVE.")
    ap.add_argument("modules", nargs="*",
                    help="e.g. refstyle.py revision/_promote.py "
                         "(default: every module with claims)")
    ap.add_argument("--jobs", type=int, default=1, metavar="N",
                    help="check N modules at once, each in a kill_check "
                         "checkout of its own (default 1)")
    ap.add_argument("--worker", action="store_true",
                    help=argparse.SUPPRESS)   # one group, blocks only
    args = ap.parse_args(argv)
    if args.jobs < 1:
        ap.error("--jobs must be at least 1")

    if not CLAIMS.exists():
        print(f"no claims file at {CLAIMS}")
        return 0
    with CLAIMS.open("rb") as fh:
        doc = tomllib.load(fh)
    wanted = args.modules or sorted(doc)
    if unknown := [m for m in wanted if m not in doc]:
        # Named and refused rather than checked in silence: asking for a
        # module with no claims used to print nothing and exit 0, which
        # reads exactly like "all good".
        ap.error(f"no claims in {CLAIMS.name} for: {', '.join(unknown)}")

    # A worker prints the blocks and nothing else: the parent did the
    # anchoring and owns the diagnostics, so saying them again would
    # double every one of them in the report.
    def say(line: str) -> None:
        if not args.worker:
            print(line)

    bad = 0
    todo: dict[str, list[Case]] = {}
    for module in sorted(wanted):
        claims = doc[module].get("claims", [])
        cases = cases_for(module, claims, say)
        if cases is None:
            bad += 1
            continue
        if not args.worker:      # in a worker the parent has counted them
            bad += len(claims) - len(cases)
        if cases:
            todo[module] = cases

    if args.jobs > 1 and not args.worker:
        bad += fan_out(todo, min(args.jobs, len(todo) or 1))
    else:
        for module, cases in todo.items():
            print()
            bad += run_here(module, cases, worker=args.worker)
    if bad and not args.worker:
        # The exit code, not only the `!!` lines: this is the check a
        # caller runs to be TOLD, and `check`'s answer — how many did not
        # match their expectation — was read by nobody until 2026-09-18.
        # A killed claim is the finding this tool exists for.
        print(f"\n{bad} claim(s) are not what they were argued to be, or "
              f"could not be checked at all — see above")
    return 1 if bad else 0


if __name__ == "__main__":                  # pragma: no cover
    raise SystemExit(main())
