#!/usr/bin/env python
"""Which mutation figures still describe the code they were measured on.

    python tools/stale_figures.py           # every module, one line each
    python tools/stale_figures.py --stale   # only the ones to re-measure

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
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from functools import cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_map import HARNESS

ROOT = Path(__file__).resolve().parents[1]

#: What a module's session file is called. `_table_core.py` measures
#: into `.mutation-table_core.sqlite` — the leading underscore goes.
def session_file(module: str) -> Path:
    return ROOT / f".mutation-{module[:-3].lstrip('_')}.sqlite"


@cache
def last_touched(path: Path) -> float:
    """The later of: last commit, and the file on disk.

    An uncommitted test is as much a change as a committed one — more,
    if anything, since it is the one a run picked up by accident.
    """
    on_disk = path.stat().st_mtime if path.exists() else 0.0
    out = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    return max(on_disk, float(out) if out else 0.0)


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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stale", action="store_true",
                    help="print only the modules whose figure is void")
    args = ap.parse_args()

    worst = 0
    for module, tests in sorted(HARNESS.items()):
        verdict, moved = state(module, tests)
        if args.stale and verdict == "fresh":
            continue
        worst = max(worst, {"fresh": 0, "stale": 1, "never measured": 1}[
            verdict])
        detail = f": {', '.join(moved)}" if moved else ""
        print(f"{module:24s} {verdict}{detail}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
