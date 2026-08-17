#!/usr/bin/env python
"""Measure several modules, one after another, and print each result.

    python tools/measure_all.py body.py find.py ingest.py
    python tools/measure_all.py --all          # every module in src

Each module runs to completion against the harness `harness_map` names
for it, and its real-survival line is printed as soon as it is known —
which for a big module is half an hour after the one before it, so this
is meant to be started and left.

SEQUENTIAL on purpose: the sessions share one worktree, and two of them
mutating it at once makes each read the other's mutations. The session
tool holds a lock and would refuse, but the reason it refuses is here.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_map import harness_for

ROOT = Path(__file__).resolve().parents[1]


def run(module: str, minutes: float) -> None:
    tests = harness_for(module)
    print(f"### {module}  ({len(tests)} test file(s))", flush=True)
    session = subprocess.run(
        [sys.executable, "tools/mutation_session.py", f"src/docxkit/{module}",
         "--tests", *tests, "--minutes", str(minutes), "--chunks", "0",
         "--fresh"],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    tail = [ln for ln in session.stdout.splitlines() if " run — " in ln]
    print("   ", tail[-1].strip() if tail else session.stderr[-300:],
          flush=True)

    stem = module[:-3].lstrip("_") or module[:-3]
    db = ROOT / f".mutation-{stem}.sqlite"
    if not db.exists():
        print("    NO SESSION", flush=True)
        return
    out = subprocess.run(
        [sys.executable, "tools/mutation_survivors.py", db.name,
         f"src/docxkit/{module}"],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace").stdout
    real = re.search(r"REAL SURVIVAL ([\d.]+)% \((\d+)/(\d+)\)", out)
    by = re.search(r"by definition: (.+)", out)
    if real:
        print(f"    REAL SURVIVAL {real.group(1)}%  "
              f"({real.group(2)}/{real.group(3)})", flush=True)
    if by:
        print(f"    {by.group(1)[:150]}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*", help="e.g. body.py find.py")
    ap.add_argument("--all", action="store_true",
                    help="every module in src/docxkit, smallest first")
    ap.add_argument("--minutes", type=float, default=7,
                    help="per chunk; each one is restartable")
    args = ap.parse_args()

    modules = list(args.modules)
    if args.all:
        found = sorted((p.stat().st_size, p.name)
                       for p in (ROOT / "src/docxkit").glob("*.py")
                       if p.name != "__init__.py")
        modules += [name for _size, name in found if name not in modules]
    if not modules:
        ap.error("name some modules, or pass --all")
    for module in modules:
        run(module, args.minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
