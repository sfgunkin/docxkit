#!/usr/bin/env python
"""What the gate chain spends its time on, and what got slower.

    python tools/timings.py              # slowest gates, slowest tests
    python tools/timings.py --runs 20    # over the last 20 chain runs
    python tools/timings.py --regressions
    python tools/timings.py --prune 50   # keep the newest 50 records

`tools/gates.py` writes one JSON file per chain run into `.timings/`.
This reads them. Nothing here gates, and that is deliberate: a slow gate
is a fact about the machine's afternoon — a laptop on battery, a
mutation sweep in the next window, Defender reading the tree — and a
threshold over that would fail builds for the weather.

**A median, never a mean, and never the latest run alone.** The spread
on this chain is real: the same green `pytest` gate has been measured at
27.8s and 33.5s within one hour of the same tree, which is 20% of
nothing happening. A mean lets one cold-cache run rewrite the number a
reader plans against, and "the last run was slower" is a coin toss
reported as a finding. What is worth acting on is a gate whose MEDIAN
has moved against the runs before it.

So `--regressions` compares the median of the newest third against the
median of the rest, and says nothing unless the gap clears both a ratio
AND an absolute floor: a gate that went from 0.4s to 0.8s doubled and
does not matter, and reporting it teaches the reader to skim.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: One chain run as `gates.py` wrote it.
Run = dict[str, Any]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from docxkit import timings as timings_mod  # noqa: E402
from docxkit.console import utf8_stdout  # noqa: E402

TIMINGS = ROOT / timings_mod.FOLDER

#: A regression must clear BOTH. The ratio alone reports a 0.4s gate
#: doubling; the floor alone reports the pytest gate drifting 2s on a
#: busy machine. Together they name the thing a reader would act on.
SLOWER = 1.25
FLOOR_SECONDS = 2.0

#: Below this a gate is not worth a line in the report. Measured: five
#: of the nine gates are under a second and always will be.
NOTABLE = 0.5


def records(folder: Path = TIMINGS, runs: int | None = None,
            kind: str | None = None) -> list[Run]:
    """Runs, oldest first. A corrupt file is skipped, not fatal.

    `folder` is the `.timings` directory itself, so the reader can be
    pointed at a PAPER's — every producer writes the same shape through
    `docxkit.timings.record`, which is the whole reason there is one
    reader rather than two.
    """
    return timings_mod.read(folder, kind=kind, last=runs)


def by_gate(runs: list[Run]) -> dict[str, list[float]]:
    """Step name -> its seconds across the runs, in order."""
    seen: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for gate in run.get("steps", []):
            if gate.get("status") == "ok":
                seen[str(gate["name"])].append(float(gate["seconds"]))
    return dict(seen)


def slowest_tests(
        runs: list[Run],
        limit: int = 15) -> list[tuple[float, str, str, int]]:
    """The costliest tests, by median across every run that named them.

    Median again, and for a sharper reason than the gates: these come
    from a parallel run, so a test's measured cost includes whatever
    else landed on its worker.
    """
    seen: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        for gate in run.get("steps", []):
            for row in gate.get("slowest_tests", []):
                key = (str(row["test"]), str(row["phase"]))
                seen[key].append(float(row["seconds"]))
    ranked = sorted(((statistics.median(v), k[0], k[1], len(v))
                     for k, v in seen.items()), reverse=True)
    return ranked[:limit]


def regressions(
        runs: list[Run]) -> list[tuple[float, str, float, float, int]]:
    """Gates whose recent median stands clear of their earlier one."""
    found = []
    for name, seconds in by_gate(runs).items():
        if len(seconds) < 6:            # too few to call a median a fact
            continue
        # At least THREE in the recent window, whatever the third works
        # out to. A median over two values is their mean, so at six runs
        # a window of two let one slow afternoon carry the verdict — 30,
        # 30, 30, 30, 30, 60 reported as 30s -> 45s, which is the exact
        # coin-toss-as-a-finding this function exists to avoid. Caught
        # by `test_ONE_slow_afternoon_is_not_a_regression`.
        cut = max(3, len(seconds) // 3)
        recent, before = seconds[-cut:], seconds[:-cut]
        now, was = statistics.median(recent), statistics.median(before)
        if now >= was * SLOWER and now - was >= FLOOR_SECONDS:
            found.append((now - was, name, was, now, len(seconds)))
    return sorted(found, reverse=True)


def report(runs: list[Run],
           say: Callable[[str], None] = print) -> None:
    if not runs:
        # Both halves, because this reader serves both producers and the
        # message that named only the gate chain was actively wrong when
        # pointed at a paper: a paper does not run tools/gates.py.
        say("no runs recorded yet — .timings/ is empty.\n"
            "  this repo:  python tools/gates.py   (records every chain "
            "run)\n"
            "  a paper:    timings.record('batch', report.name, "
            "report.durations, ROOT / timings.FOLDER)")
        return

    gates = by_gate(runs)
    total = [float(r["total_seconds"]) for r in runs if "total_seconds" in r]
    say(f"{len(runs)} chain run(s) recorded, "
        f"{runs[0].get('when', '?')} to {runs[-1].get('when', '?')}")
    if total:
        say(f"whole chain: median {statistics.median(total):.1f}s "
            f"(fastest {min(total):.1f}s, slowest {max(total):.1f}s)")

    say("\nWHERE THE TIME GOES  (median seconds per gate, green runs only)")
    ranked = sorted(((statistics.median(v), n, len(v))
                     for n, v in gates.items()), reverse=True)
    share = sum(m for m, _, _ in ranked) or 1.0
    for median, name, n in ranked:
        if median < NOTABLE:
            continue
        say(f"  {median:7.1f}s  {100 * median / share:4.1f}%  {name}"
            f"   (n={n})")
    quiet = [n for m, n, _ in ranked if m < NOTABLE]
    if quiet:
        say(f"  under {NOTABLE}s and not worth optimising: "
            f"{', '.join(sorted(quiet))}")

    tests = slowest_tests(runs)
    if tests:
        say("\nSLOWEST TESTS  (median of the runs that named them; the "
            "pytest gate is most of the chain)")
        for median, test, phase, n in tests:
            tag = "" if phase == "call" else f" [{phase}]"
            say(f"  {median:7.2f}s  {test}{tag}   (n={n})")

    moved = regressions(runs)
    say("\nREGRESSIONS  (recent median vs earlier, both a ratio and a "
        "floor)")
    if not moved:
        say("  (none — no gate's median has moved enough to act on)")
    for delta, name, was, now, n in moved:
        say(f"  +{delta:.1f}s  {name}: {was:.1f}s -> {now:.1f}s "
            f"over {n} runs")


def prune(keep: int, folder: Path = TIMINGS) -> int:
    """Delete all but the newest `keep` records. Returns how many went."""
    paths = sorted(folder.glob("*.json"))
    doomed = paths[:-keep] if keep else paths
    for path in doomed:
        path.unlink(missing_ok=True)
    return len(doomed)


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse
                                 .RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="a tree with a .timings/ folder — this repo by "
                         "default, or a paper that keeps its batch "
                         "durations")
    ap.add_argument("--kind", default=None,
                    help="only records of this kind (gates, batch, ...)")
    ap.add_argument("--runs", type=int, default=None,
                    help="only the newest N chain runs")
    ap.add_argument("--regressions", action="store_true",
                    help="only the regression section")
    ap.add_argument("--prune", type=int, metavar="N",
                    help="delete all but the newest N records")
    args = ap.parse_args(argv)
    folder = Path(args.root) / timings_mod.FOLDER

    if args.prune is not None:
        print(f"pruned {prune(args.prune, folder)} record(s); "
              f"{len(records(folder))} kept")
        return 0

    runs = records(folder, runs=args.runs, kind=args.kind)
    if args.regressions:
        moved = regressions(runs)
        for delta, name, was, now, n in moved:
            print(f"+{delta:.1f}s  {name}: {was:.1f}s -> {now:.1f}s "
                  f"over {n} runs")
        if not moved:
            print("no gate's median has moved enough to act on")
        return 0

    report(runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
