#!/usr/bin/env python
"""Measure several modules, one after another, and print each result.

    python tools/measure_all.py body.py find.py ingest.py
    python tools/measure_all.py --all          # every module in src

Each module runs to completion against the harness `harness_map` names
for it, and its real-survival line is printed as soon as it is known —
which for a big module is half an hour after the one before it, so this
is meant to be started and left.

Sequential within one worktree, because the sessions mutate the module
in place and two of them at once make each read the other's mutations.
The session tool holds a per-worktree lock and would refuse; the reason
it refuses is here.

    python tools/measure_all.py --in D:/docxkit-mut2,D:/docxkit-mut3 --all

`--in` deals the modules out to several checkouts and runs one stream in
each. The lock is per worktree and the session files are per module, so
streams over DIFFERENT modules never meet — and a whole-package sweep is
otherwise a day's wall clock for twenty minutes of thought.

Dealt round-robin rather than in blocks: the module list is sorted
smallest-first, so blocks would put every big module in the last stream.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness_map import harness_for

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]


def run(module: str, minutes: float, sample: int = 0, *,
        tag: bool = False) -> None:
    """Measure ONE module, streaming the session's chunk lines through.

    `tag` puts the module's name on every line. Under `--in` the streams
    interleave, and a heading printed by one lands between another's
    heading and its numbers: the first fan-out to finish (2026-08-20)
    reported `_cite_build`'s 8.9 % under `_table_core`'s heading, and
    only the function names in the tally said which was which.
    """
    tests = harness_for(module)

    def say(text: str) -> None:
        print(f"{module + ' ' if tag else ''}{text}", flush=True)

    print(f"### {module}  ({len(tests)} test file(s))", flush=True)
    # STREAMED, not captured: a module is half an hour and the session
    # prints one line per chunk. Swallowed until the end, a sweep that is
    # working looks exactly like a sweep that has hung — and the first
    # question about a long run is "how far in", which the chunk lines
    # already answer.
    # The child's ENCODING, not just this end of the pipe. Its stdout is
    # a pipe, so Python gives it the locale's cp1252 unless told
    # otherwise, and the em dash in "4/4 run — killed 4" then arrives as
    # a byte this end cannot decode. `errors="replace"` turns it into
    # U+FFFD, ` run — ` no longer matches, and a sweep that graded every
    # mutant reports "no chunk ever graded" — then dies printing that
    # U+FFFD to a cp1252 console. Both halves of a fan-out did on
    # 2026-08-20, and neither said a word about what went wrong.
    child = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, "tools/mutation_session.py", f"src/docxkit/{module}",
         "--tests", *tests, "--minutes", str(minutes), "--chunks", "0",
         "--fresh", *(["--sample", str(sample)] if sample else [])],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=child)
    assert proc.stdout is not None
    last, others = "", deque[str](maxlen=6)
    for raw in proc.stdout:
        line = raw.strip()
        if " run — " in line:
            last = line
            say(f"    {last}")
        elif line:
            others.append(line)
    proc.wait()
    if not last:                 # no chunk ever graded: say why, not "0%"
        say("    " + (" | ".join(others)[-300:] or "no output"))

    stem = module[:-3].lstrip("_") or module[:-3]
    db = ROOT / f".mutation-{stem}.sqlite"
    if not db.exists():
        say("    NO SESSION")
        return
    out = subprocess.run(
        [sys.executable, "tools/mutation_survivors.py", db.name,
         f"src/docxkit/{module}"],
        cwd=ROOT, capture_output=True, text=True, env=child,
        encoding="utf-8", errors="replace").stdout
    real = re.search(r"REAL SURVIVAL ([\d.]+)% \((\d+)/(\d+)\)", out)
    by = re.search(r"by definition: (.+)", out)
    if real:
        say(f"    REAL SURVIVAL {real.group(1)}%  "
            f"({real.group(2)}/{real.group(3)})")
    if by:
        say(f"    {by.group(1)[:150]}")


def fan_out(worktrees: list[str], modules: list[str], minutes: float,
            sample: int) -> int:
    """One stream per checkout, modules dealt round-robin.

    Each stream is this same script with `DOCXKIT_MUT_WORKTREE` set, so
    a stream is a sweep like any other — restartable, locked, and
    printing its own chunk lines. Their output is interleaved and every
    line is already prefixed by the module it belongs to.
    """
    streams = []
    for i, tree in enumerate(worktrees):
        mine = modules[i::len(worktrees)]
        if not mine:
            continue
        print(f"--- {tree}: {', '.join(mine)}", flush=True)
        streams.append(subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), *mine,
             "--minutes", str(minutes), "--tag",
             *(["--sample", str(sample)] if sample else [])],
            cwd=ROOT, env={**os.environ, "DOCXKIT_MUT_WORKTREE": tree,
                           "PYTHONIOENCODING": "utf-8"}))
    return max((p.wait() for p in streams), default=0)


def main() -> int:
    # Everything this prints came off another process's stdout, and a
    # session that failed prints the reason — a path, a traceback, a
    # pytest line — through `errors="replace"`, whose U+FFFD a cp1252
    # console cannot encode. The sweep then dies IN its own diagnosis,
    # which is where a fan-out of four modules went on 2026-08-20: two
    # streams, two tracebacks, and not one word about what went wrong.
    utf8_stdout(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*", help="e.g. body.py find.py")
    ap.add_argument("--all", action="store_true",
                    help="every module in src/docxkit, smallest first")
    ap.add_argument("--minutes", type=float, default=7,
                    help="per chunk; each one is restartable")
    ap.add_argument("--in", dest="worktrees", default="",
                    help="comma-separated checkouts to fan out across; "
                         "one stream per checkout, modules dealt "
                         "round-robin")
    ap.add_argument("--tag", action="store_true",
                    help="name the module on every line — set by --in, "
                         "whose streams interleave")
    ap.add_argument("--sample", type=int, default=0,
                    help="run N mutants per module instead of all of them; "
                         "the seed is the session tool's default, so two "
                         "sampled runs of one module draw the same mutants")
    args = ap.parse_args()

    modules = list(args.modules)
    if args.all:
        found = sorted((p.stat().st_size, p.name)
                       for p in (ROOT / "src/docxkit").glob("*.py")
                       if p.name != "__init__.py")
        modules += [name for _size, name in found if name not in modules]
    if not modules:
        ap.error("name some modules, or pass --all")
    if args.worktrees:
        return fan_out([w for w in args.worktrees.split(",") if w],
                       modules, args.minutes, args.sample)
    for module in modules:
        run(module, args.minutes, args.sample, tag=args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
