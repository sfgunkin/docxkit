#!/usr/bin/env python
"""Which mutation figures still describe the code they were measured on.

    python tools/stale_figures.py           # every module, one line each
    python tools/stale_figures.py --stale   # only the ones to re-measure
    python tools/stale_figures.py --figures # the FIGURE beside the verdict

A survivor list is a photograph of ONE tree: this source, this harness.
Change either side and the list keeps its old answers — mutants a new
test now kills go on reading as survivors, and the next round mines them
and finds nothing. CONTRIBUTING already says to check the source's
commit time against the session file; it did not say the same about the
HARNESS, and on 2026-08-19 every module in the package was stale on that
side while most were fresh on the other.

The check is the rule, mechanised. For each module it compares the
session file's mtime against the newest change to the module and to
every test file `harness_map` names for it — the COMMIT time and the
working-tree mtime both, because an uncommitted test counts exactly as
much as a committed one.

It answers "is this figure worth quoting", nothing else. What to do
about a stale one is a judgement: re-measure before the round starts, or
mine it anyway and let `kill_check` dispose of what has since died.

`--figures` prints the figure itself alongside, read out of each session
file through `mutation_survivors.classify` — the same arithmetic the
survivor list uses, so the two cannot disagree. It exists because the
numbers get QUOTED: CONTRIBUTING's tables are written by hand from
whatever the last round printed into a terminal, and a table written
that way is out of date the moment a round lands. This is the state of
the package as of right now, in one screen.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness_map import HARNESS

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]

#: What a module's session file is called. `_table_core.py` measures
#: into `.mutation-table_core.sqlite` — the leading underscore goes.
def session_file(module: str) -> Path:
    return ROOT / f".mutation-{module[:-3].lstrip('_')}.sqlite"


@cache
def commit_times() -> dict[str, float]:
    """Newest commit time for every path in the history, in ONE call.

    A `git log` per path costs ~190 ms on Windows, nearly all of it
    process spawn, and this tool asks about ninety of them — seventeen
    seconds for a question that is meant to be asked before every round.
    One `--name-only` pass answers all of them; the log is newest first,
    so the FIRST time a path appears is its latest commit.
    """
    out = subprocess.run(
        ["git", "log", "--format=%ct", "--name-only"],
        cwd=ROOT, capture_output=True, text=True, check=False).stdout
    times: dict[str, float] = {}
    when = 0.0
    for line in out.splitlines():
        if not line:
            continue
        if line.isdigit():
            when = float(line)
        else:
            times.setdefault(line.replace("\\", "/"), when)
    return times


@cache
def last_touched(path: Path) -> float:
    """The later of: last commit, and the file on disk.

    An uncommitted test is as much a change as a committed one — more,
    if anything, since it is the one a run picked up by accident.
    """
    on_disk = path.stat().st_mtime if path.exists() else 0.0
    try:
        rel = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return on_disk          # outside the repo: git knows nothing
    return max(on_disk, commit_times().get(rel, 0.0))


def newer_than(when: float, paths: list[Path]) -> list[Path]:
    return [p for p in paths if last_touched(p) > when]


def state(module: str, tests: list[str]) -> tuple[str, list[str]]:
    """``("fresh" | "stale" | "never measured", what changed since)``."""
    db = session_file(module)
    if not db.exists():
        return "never measured", []
    watched = [ROOT / "src" / "docxkit" / module,
               *(ROOT / t for t in tests)]
    moved = newer_than(db.stat().st_mtime, watched)
    return ("stale" if moved else "fresh",
            [str(p.relative_to(ROOT)).replace("\\", "/") for p in moved])


def figure(module: str) -> str:
    """`real survival` for one module, or why there is none to print."""
    from mutation_survivors import classify  # noqa: PLC0415

    db = session_file(module)
    src = ROOT / "src" / "docxkit" / module
    try:
        counts = classify(str(db), str(src))
    except (sqlite3.DatabaseError, SyntaxError, OSError) as exc:
        return f"unreadable ({type(exc).__name__})"
    if counts is None:
        return "graded nothing"
    # A run that stopped early reports whatever its first mutants said,
    # and it flatters: `_table_core` read 1.0 % from 209 of 903 against
    # a true 2.7 % from all of them.
    mark = " PARTIAL" if counts.partial else ""
    return f"{counts.share:5.1f}%  ({len(counts.real)}/{counts.base}){mark}"


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stale", action="store_true",
                    help="print only the modules whose figure is void")
    ap.add_argument("--figures", action="store_true",
                    help="print each module's real-survival figure too")
    args = ap.parse_args()

    worst = 0
    for module, tests in sorted(HARNESS.items()):
        verdict, moved = state(module, tests)
        if args.stale and verdict == "fresh":
            continue
        worst = max(worst, {"fresh": 0, "stale": 1, "never measured": 1}[
            verdict])
        if args.figures:
            # The figure of a STALE run is still the last thing measured;
            # the verdict beside it is what says whether to quote it.
            got = figure(module) if verdict != "never measured" else ""
            print(f"{module:24s} {got:>18s}  {verdict}")
            continue
        detail = f": {', '.join(moved)}" if moved else ""
        print(f"{module:24s} {verdict}{detail}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
