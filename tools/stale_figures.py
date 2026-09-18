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
import re
import sqlite3
import subprocess
import sys
import tomllib
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
def session_file(module: str, beside: Path | None = None) -> Path:
    return (beside or ROOT) / f".mutation-{session_stem(module)}.sqlite"


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


def snapshot_of(module: str, beside: Path | None = None) -> Path:
    """Where the session kept the source and harness it planned against.

    `beside` is the directory the session file itself sits in, for a
    reader working from somewhere else — see :func:`state`.
    """
    return (beside or ROOT) / f".mutation-{session_stem(module)}.pristine"


#: A test file named in a session's recorded command. The command is one
#: string — the interpreter, `mutant_tests.py`, its flags, then pytest's
#: — and the test files are the only `tests/...py` words in it.
_TEST_FILE_RE = re.compile(r"tests/[\w.\-/]+\.py")


def planned_tests(module: str,
                  beside: Path | None = None) -> list[str] | None:
    """The test files the session for `module` was PLANNED against.

    `mutation_session.write_config` writes the whole test command into
    `.mutation-<stem>.toml`, so the harness of the day is recorded
    beside the verdicts it produced. None when no config sits beside the
    session: a run from before it was written, or one driven by hand.
    """
    config = (beside or ROOT) / f".mutation-{session_stem(module)}.toml"
    if not config.is_file():
        return None
    with config.open("rb") as fh:
        command = tomllib.load(fh).get("cosmic-ray", {}).get(
            "test-command", "")
    return sorted(set(_TEST_FILE_RE.findall(command.replace("\\", "/"))))


def drifted(module: str, tests: list[str],
            beside: Path | None = None) -> tuple[list[str], list[str]]:
    """``(added, dropped)``: how the harness `tests` names TODAY differs
    from the one the session was planned against. Two empty lists when
    they agree, or when there is no config to read.

    The two directions are different findings, and only the first is
    safe:

    * ADDED — the map names tests the run never used. An added test can
      only KILL, so every figure the run produced is an upper bound and
      a survivor on the list may already be dead.
    * DROPPED — the map no longer names a test the run used. The figure
      was measured against a harness this module no longer has, so a
      replay or a `kill_check` run today asks a different question than
      the session did, and a claim verified now is not the claim the
      session's survivor list was drawn against.

    Nothing reported this before. `state` compares TIMES — the module
    and the named tests against the snapshot — so a harness that gained
    a file, or swapped one for a renamed copy, looks exactly like a
    harness that did not move: the files it compares are the ones it is
    told to compare. Worked example, and how this was noticed: word.py's
    session was planned against seven test files, and the map named
    fifteen by the time the round was mined — `test_equations.py`
    renamed to `test_equations_typography.py`, and eight files added —
    all of it invisible, and found only because the round happened to
    read the toml (2026-09-18).
    """
    planned = planned_tests(module, beside)
    if planned is None:
        return [], []
    now = {t.replace("\\", "/") for t in tests}
    return sorted(now - set(planned)), sorted(set(planned) - now)


def lines_of(path: Path) -> bytes:
    """A file's LINES, with the checkout's line endings taken out.

    THE comparison for "has this file moved since the run", shared by
    everything that asks it: `moved_by_content` below,
    `mutation_session.moved_since`, and `replay_survivors.module_moved`.

    A survivor is a row number and the text of that row, and neither
    moves when a file is written with CRLF instead of LF. A raw byte
    comparison calls it a different module anyway, and on this platform
    that is not hypothetical: Git for Windows sets `core.autocrlf=true`
    in its SYSTEM config, so a `git worktree add` wrote CRLF while
    D:/docxkit held LF, and a `.pristine` snapshot copied from either
    one then disagreed with the other about every line.

    Measured 2026-09-18, against a fresh worktree at master: of the 65
    stored snapshots, 10 agreed byte for byte, 21 held a module that had
    really changed — and **34 differed in nothing but newlines**. Every
    one of those refused to replay, in a checkout where nothing had been
    edited at all. `.gitattributes` pins `eol=lf` for every checkout
    from that day on; this keeps the sessions taken BEFORE it readable,
    which is all of them.

    Safe in the direction that matters: git normalises newlines on the
    way in, so a difference that is only newlines cannot reach a commit,
    and a module that really moved still reads as moved.
    """
    return path.read_bytes().replace(b"\r\n", b"\n")


def moved_by_content(module: str, tests: list[str],
                     beside: Path | None = None) -> list[str] | None:
    """Which watched files the working tree no longer AGREES with.

    Bytes, not mtimes — the rule `mutation_session.moved_since` already
    applies to the same question, with the same reason: *"a file
    rewritten with identical content has not moved for this purpose"*.
    Through :func:`lines_of`, so a checkout's line endings are not
    mistaken for an edit; the same function answers for all three
    callers that ask this.

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
    kept = snapshot_of(module, beside)
    # the MODULE is what the answer is about — a survivor is a line
    # number into it — so its absence is the one that answers nothing
    if not (kept / f"src/docxkit/{module}").is_file():
        return None
    out: list[str] = []
    for rel in [f"src/docxkit/{module}", *tests]:
        was, now = kept / rel, ROOT / rel
        if (not was.is_file()                    # the run never had it
                or not now.is_file()
                or lines_of(was) != lines_of(now)):
            out.append(rel)
    return out


def state(module: str, tests: list[str],
          db: Path | None = None) -> tuple[str, list[str]]:
    """``("fresh" | "stale" | "never measured", what changed since)``.

    "Changed since" includes a file the run did not have: asked about a
    harness other than the one measured — `replay_survivors --tests` —
    the honest answer is that this is not the run's harness, which is
    `stale` naming that file, not a refusal to answer.

    **Pass `db` when the session is not in THIS checkout**, and the
    banner then works where rounds are actually worked. Left to find the
    session itself, this looks in the tool's own tree — which is right
    for a reader in `D:/docxkit` and wrong for every other one. Sweeps
    run in `docxkit-mut-a/b/d` and rounds in their own worktrees, so the
    ordinary invocation is an ABSOLUTE session path read from somewhere
    else, and there the file simply is not found, the answer is "never
    measured", and `mutation_survivors` prints no STALE banner at all.

    Measured 2026-09-18 on `guard.py`, same session and same module:
    from `D:/docxkit` it named `test_tracked_guard.py` and
    `test_cli_guards.py`; from a round worktree, with the session given
    by absolute path, identical counts and no banner. The warning was
    off exactly where it is needed, and a round briefed to "read the
    staleness banner first" would have seen nothing and mined a list
    whose three survivors were already dead.

    What is compared stays relative to THIS checkout, and deliberately:
    the question a reader in a worktree is asking is whether the tree
    they are about to work in still agrees with the run.
    """
    db = db or session_file(module)
    if not db.exists():
        return "never measured", []
    by_content = moved_by_content(module, tests, db.parent)
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


@cache
def main_checkout() -> Path:
    """The repository's MAIN working tree, from any worktree of it.

    `--git-common-dir` answers with the main repo's `.git` wherever it
    is asked from, so its parent is the checkout the sessions live
    beside. Falls back to this tree when git cannot answer — a tarball,
    or no git at all — which is the same answer as today for anyone
    working in the main checkout anyway.
    """
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    common = out.stdout.strip()
    return Path(common).parent if common else ROOT


def running() -> list[tuple[str, int]]:
    """Which modules a sweep is grading RIGHT NOW, and under which pid.

    `mutation_session._mark_running` writes `.mutation-<stem>.running`
    beside the session and removes it on the way out. A killed session
    leaves the file, so the pid is checked rather than the file trusted
    — through `_alive`, which on Windows is a `tasklist` query and not
    `os.kill(pid, 0)`, that call being a kill there.

    Imported inside the function, the way `mutation_session` reaches
    back here for `lines_of`: these tools are each other's.

    **The markers are looked for in the MAIN checkout, not in this
    one**, and that is the whole reliability of the check. Sessions live
    in the main repository; a round is worked in a worktree. Globbing
    the tool's own `ROOT` therefore found nothing from anywhere except
    `D:/docxkit`, and answered *"nothing is being swept"* — a FALSE SAFE
    in the one check whose entire job is to refuse an unsafe merge.
    Reported 2026-09-18 by an agent who noticed the answer did not match
    four live streams and checked by hand anyway: *"the tool answered
    safe for a reason unrelated to the question."*

    It is the same defect as the staleness banner's, found the same day
    and fixed the same way — a tool resolving state against the checkout
    it happens to be running from rather than the one the state is in.
    """
    from mutation_session import _alive  # noqa: PLC0415

    by_stem = {session_stem(m): m for m in HARNESS}
    out = []
    for mark in sorted(main_checkout().glob(".mutation-*.running")):
        stem = mark.name[len(".mutation-"):-len(".running")]
        try:
            pid = int(mark.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        if _alive(pid):
            out.append((by_stem.get(stem, f"{stem} (not in the map)"), pid))
    return out


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stale", action="store_true",
                    help="print only the modules whose figure is void")
    ap.add_argument("--figures", action="store_true",
                    help="print each module's real-survival figure too")
    ap.add_argument("--running", action="store_true",
                    help="name the modules a sweep is grading right now, "
                         "and exit 1 if any is — ask BEFORE a merge")
    ap.add_argument("paths", nargs="*",
                    help="with --running: the files a merge would touch. "
                         "Exit 1 only if one of them is a live sweep's "
                         "module or harness")
    args = ap.parse_args()

    if args.running:
        # Exit 1 while a stream is live, so the question chains:
        #
        #     python tools/stale_figures.py --running && git cherry-pick ...
        #
        # A merge that touches a module under a stream voids its figure
        # however far it has got. `_table_core.py` lost 1,372 mutants to
        # a cherry-pick twenty-five minutes before the run would have
        # finished (2026-09-18), and the round that landed was itself
        # fine — there was simply nothing to ask.
        live = running()
        if not args.paths:
            for module, pid in live:
                print(f"{module:24s} being swept now (pid {pid})")
            if not live:
                print("nothing is being swept")
            return 1 if live else 0

        # With PATHS the question narrows from "is anything live" to
        # "does THIS merge void a figure", which is the one worth
        # chaining: during a campaign something is always live, and a
        # check that refuses every merge is a check people route around.
        #
        #     python tools/stale_figures.py --running $(git show --name-only
        #         --format= <ref>) && git cherry-pick <ref>
        #
        # The HARNESS counts as much as the module. A session snapshots
        # its test files too, so a round that only adds tests still
        # voids the figure of every module whose harness names the file
        # it added them to — which is the ordinary shape of a survivor
        # round, and the one that looks harmless.
        want = {Path(p).as_posix().lstrip("./") for p in args.paths}
        hit = False
        for module, pid in live:
            owned = {f"src/docxkit/{module}", *HARNESS.get(module, [])}
            if shared := sorted(owned & want):
                hit = True
                print(f"{module:24s} being swept now (pid {pid}) — "
                      f"{', '.join(shared)}")
        if not hit:
            what = "nothing is being swept" if not live else (
                f"{len(live)} sweep(s) live, none touched by these "
                f"{len(want)} path(s)")
            print(what)
        return 1 if hit else 0

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
        # In the listing rather than in `--figures`: the figures table is
        # one screen of numbers and these are names, which is what makes
        # them worth printing at all.
        added, dropped = drifted(module, tests)
        for label, files in (("dropped", dropped), ("added", added)):
            if files:
                detail += (f"{';' if detail else ':'} harness {label} "
                           f"{', '.join(files)}")
        print(f"{module:24s} {verdict}{detail}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
