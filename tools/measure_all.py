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
import hashlib
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness_map import harness_for, session_stem

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(module: str, tests: list[str]) -> str:
    """The bytes a figure is ABOUT: the module and its harness.

    Taken before the session starts and again when it ends. The session
    checks the same thing, but only at the start of each chunk — so a
    run that fits in ONE chunk never re-checks, and an edit made while
    it ran goes unmentioned. `placement` did exactly that on
    2026-08-20: one chunk, two tests added to its harness halfway
    through, and a figure that quietly described neither tree.
    """
    h = hashlib.sha256()
    for name in [f"src/docxkit/{module}", *tests]:
        path = ROOT / name
        h.update(path.read_bytes() if path.exists() else b"")
    return h.hexdigest()


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
    before = fingerprint(module, tests)

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
    # `--fast`, always. `mutant_tests` runs the tests that COVER the
    # mutated line first and falls through to the whole harness when
    # none of them fails, so a survivor is never declared by the short
    # run — it is declared by the same command this would have used
    # anyway. The only thing a wrong or stale coverage map can cost is
    # time, which is the asymmetry the flag exists for: kills are the
    # common case and a kill decided by three tests costs what pytest's
    # start-up costs.
    #
    # A sweep is where that matters most and this is the one caller that
    # did not pass it. Left off, a 13-module round over an 8-file
    # harness spends most of its wall clock re-running tests that cannot
    # reach the mutated line.
    proc = subprocess.Popen(
        [sys.executable, "tools/mutation_session.py", f"src/docxkit/{module}",
         "--tests", *tests, "--minutes", str(minutes), "--chunks", "0",
         "--fresh", "--fast",
         *(["--sample", str(sample)] if sample else [])],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=child)
    assert proc.stdout is not None
    last, moved, others = "", "", deque[str](maxlen=40)
    for raw in proc.stdout:
        line = raw.strip()
        if " run — " in line:
            last = line
            say(f"    {last}")
        elif line.startswith("NOTE:"):
            # The session ALREADY refuses to measure an edit made while
            # it ran: it works from a snapshot taken when the session was
            # planned, and says so when the tree no longer agrees. That
            # warning used to land in `others`, which is printed only
            # when NO chunk graded — so a sweep whose module was edited
            # mid-run printed a clean figure and swallowed the one line
            # saying what the figure was of. (2026-08-20: `_table_layout`
            # was edited during its own re-measurement, by the person who
            # wrote the rule against it.)
            if not moved:                       # once, not per chunk
                say(f"    {line}")
            moved = line
        elif line:
            others.append(line)
    code = proc.wait()
    said_why = not last
    if said_why:                 # no chunk ever graded: say why, not "0%"
        # Every line kept, each one WHOLE. The last six cut to their final
        # 300 characters reported a lost stream as `ath, target) | ...
        # CopyFile2(src_, dst_, flags)`: the end of one call, and no
        # traceback to say whose (BACKLOG S4, 2026-09-12). A refusal is
        # a few lines and its traceback a score, so forty keeps both.
        for line in others or ["no output"]:
            say(f"    {line}")

    if code:
        if not said_why:
            # A session that graded a while and THEN stopped had its
            # reason swallowed: the diagnosis above prints only when no
            # chunk graded, so `word.py` and `revision/_validate.py`
            # each reported a bare "REFUSED (exit 1)" over two graded
            # chunks and nothing to say what stopped them
            # (2026-09-18). A refusal is worth the same lines whether
            # it arrives first or last — the successful run is the one
            # that must not carry them, since "verifying the unmutated
            # harness..." under a final figure reads as the state the
            # run ended in.
            for line in others or ["no output"]:
                say(f"    {line}")
        # A session that REFUSED is not a measurement, and returning here
        # is the whole point. `mutation_session` guards `--fresh --sample
        # N` against discarding a session that graded more than N, and it
        # returns BEFORE the unlink — so the old database is still on
        # disk, `db.exists()` below is still true, and this function used
        # to walk straight past into `mutation_survivors.py` and print
        # months-old numbers as this round's figure. The guard against
        # regressing a figure would have caused one.
        #
        # Eight of fifty live sessions have graded more than the
        # `--sample 460` CONTRIBUTING calls usual, so this is the
        # ordinary path for the most-measured modules, not a corner.
        say(f"    REFUSED (exit {code}) — no measurement taken, and the "
            f"existing session is untouched. Read it with --report, "
            f"re-measure it whole, or pass --force.")
        return

    if not moved and fingerprint(module, tests) != before:
        # The session checks this at the START of each chunk, so a run
        # that fits in ONE chunk never re-checks. Said here even when
        # there is no session file to read: a tree that moved is worth
        # knowing about whatever else went wrong.
        moved = ("NOTE: the module or its harness changed while this ran. "
                 "The figure describes the tree as it was PLANNED.")
        say(f"    {moved}")

    stem = session_stem(module)
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
            f"({real.group(2)}/{real.group(3)})"
            + ("   [OF THE TREE AS PLANNED — see the NOTE above]"
               if moved else ""))
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
        # `rglob`, and the name kept RELATIVE to `src/docxkit` — which
        # is the spelling `harness_map` keys on and `run` interpolates
        # back into a path. A `glob("*.py")` swept 43 modules and none
        # of `revision/`'s fourteen halves on the day it became a
        # subpackage: `--all` would have reported a whole-package sweep
        # over 3,118 lines it never opened.
        src = ROOT / "src/docxkit"
        found = sorted((p.stat().st_size,
                        p.relative_to(src).as_posix())
                       for p in src.rglob("*.py")
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
