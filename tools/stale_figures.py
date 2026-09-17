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
from harness_map import HARNESS, session_stem

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]

#: What a module's session file is called. `_table_core.py` measures
#: into `.mutation-table_core.sqlite` — the leading underscore goes, and
#: a subpackage half keeps its folder. The rule is `harness_map`'s, and
#: this used to hold a third copy of it (without the fallback the other
#: two had).
def session_file(module: str) -> Path:
    return ROOT / f".mutation-{session_stem(module)}.sqlite"


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


def snapshot_of(module: str) -> Path:
    """Where the session kept the source and harness it planned against."""
    return ROOT / f".mutation-{session_stem(module)}.pristine"


def moved_by_content(module: str, tests: list[str]) -> list[str] | None:
    """Which watched files the working tree no longer AGREES with.

    Bytes, not mtimes — the rule `mutation_session.moved_since` already
    applies to the same question, with the same reason: *"a file
    rewritten with identical content has not moved for this purpose"*.

    None when the session kept no snapshot OF THE MODULE, which is the
    eight runs here that predate the mechanism; the caller falls back to
    timestamps and says so.

    **A test file the snapshot does not hold is a DIFFERENCE, not an
    unanswerable question.** It used to void the whole answer, and the
    cost was `replay_survivors --tests`: naming any file outside the
    harness of the day — which is the one thing that flag exists for,
    asking a stored survivor list against a different harness — made
    this return None, and the timestamp fallback then called the MODULE
    moved (a commit re-dates every file), so the replay refused to run
    at all. Measured 2026-09-17 on `revision/_gates.py` and
    `revision/_doctor.py`: both replayed fine against their own
    harnesses and refused against the superset, and the comparison had
    to be done by hand.

    The concern that put it there is kept: a file the run never had is
    reported, so nothing reads `fresh` over a harness the run did not
    use. What it no longer does is answer a question about the module
    with silence about the module.

    **A COMMIT is not a change, and the timestamp rule cannot tell.**
    `last_touched` is `max(mtime, last commit time)`, so committing a
    file re-dates it and voids every figure measured before the commit —
    measured 2026-08-30: `revision/_build.py` untouched on disk since
    01:35, measured at 15:48, committed unchanged at 21:41, and read
    `stale`. A whole round goes void the moment it is recorded, which
    makes the tool's real signal unreadable exactly when it matters.
    """
    kept = snapshot_of(module)
    # the MODULE is what the answer is about — a survivor is a line
    # number into it — so its absence is the one that answers nothing
    if not (kept / f"src/docxkit/{module}").is_file():
        return None
    out: list[str] = []
    for rel in [f"src/docxkit/{module}", *tests]:
        was, now = kept / rel, ROOT / rel
        if (not was.is_file()                    # the run never had it
                or not now.is_file()
                or was.read_bytes() != now.read_bytes()):
            out.append(rel)
    return out


def state(module: str, tests: list[str]) -> tuple[str, list[str]]:
    """``("fresh" | "stale" | "never measured", what changed since)``.

    "Changed since" includes a file the run did not have: asked about a
    harness other than the one measured — `replay_survivors --tests` —
    the honest answer is that this is not the run's harness, which is
    `stale` naming that file, not a refusal to answer.
    """
    db = session_file(module)
    if not db.exists():
        return "never measured", []
    by_content = moved_by_content(module, tests)
    if by_content is not None:
        return "stale" if by_content else "fresh", by_content
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
        # A facade has nothing to mutate — `tables.py` re-exports two
        # modules and states no logic of its own — and that is a
        # different answer from a run that graded nothing.
        planned = sqlite3.connect(db).execute(
            "SELECT count(*) FROM mutation_specs").fetchone()[0]
        return "no mutants" if not planned else "graded nothing"
    # A run that stopped early reports whatever its first mutants said,
    # and it flatters: `_table_core` read 1.0 % from 209 of 903 against
    # a true 2.7 % from all of them.
    mark = " PARTIAL" if counts.partial else ""
    # A SAMPLED figure is an estimate over a fraction, and until
    # 2026-08-24 it printed like a measurement of the whole module:
    # `refstyle.py` read 13.1% from 460 of its 1750 mutants and said so
    # nowhere. `partial` cannot catch it, because a sample marks the
    # rest SKIPPED and a skip is a row.
    if not mark and counts.sampled:
        mark = f" SAMPLED {counts.ran}/{counts.graded}"
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
