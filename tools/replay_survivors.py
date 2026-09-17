#!/usr/bin/env python
"""Ask a survivor list again, against the harness as it stands today.

A survivor list is a photograph of the tree it was taken from.
`tools/stale_figures.py` says when the photograph has aged; this says
what the answer is NOW, by replaying every real survivor through
`kill_check` — one mutation, a private checkout, a compile check, and
the name of the test that noticed.

Measured on `_compare_diff.py`, 2026-08-24: 60 reported survivors, and
**17 of them already dead** against a harness three tests newer than the
run. Mining that list as it stood would have spent the afternoon writing
tests for mutants that were killed twenty minutes after the sweep began.
`mutation_survivors.py` records the same failure at the scale of ONE
mutant — a reader guessing which `!=` an operator name meant, and
writing a duplicate test that passed for the wrong reason. This is that
failure at the scale of a round.

    python tools/replay_survivors.py src/docxkit/guard.py

It prints the answer and does NOT write it back into the session. A
session file is the record of one run against one tree, and editing its
verdicts would make it a record of nothing in particular — the table
would then show a figure no single run ever produced. Quote the replayed
number where you use it, and re-sweep when you want the record itself to
move.

With 39 of this package's 42 modules holding a stale figure, replaying
is the difference between minutes and re-sweeping everything.

A session that is NOT beside this tree is named with `--db`, and the
source it measured with `--src`:

    python tools/replay_survivors.py src/docxkit/revision/_config.py \
        --db D:/docxkit/.mutation-revision_config.sqlite

Which is the branch-worktree case, and it is the ordinary one during a
campaign: the tests being replayed are on a branch, the session is in
the checkout that measured it, and a worktree holds neither the session
nor its snapshot. Three people hit that wall on 2026-09-18 — once as
`no session at <worktree>/.mutation-<stem>.sqlite`, and twice more as a
refusal saying the module had moved when it had not, because
`git worktree add` stamps every file's mtime to now. `cases_for` took
both paths already, "for a test, which cannot use this repo's own
session"; only the command line did not.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_map import harness_for  # pyright: ignore[reportMissingImports]
from kill_check import (  # pyright: ignore[reportMissingImports]
    _places,
    check,
)
from mutation_survivors import (  # pyright: ignore[reportMissingImports]
    LINELESS_OPERATORS,
    became,
    classify,
)
from stale_figures import (  # pyright: ignore[reportMissingImports]
    ROOT,
    lines_of,
    session_file,
    snapshot_of,
    state,
)

from docxkit.console import utf8_stdout

Case = tuple[str, str, str, bool, int]


def module_key(module: Path) -> str:
    """How `harness_map` and the session files name `module`: its path
    under `src/docxkit`, so a subpackage half keeps its folder.

    `module.name` read `revision/_timing.py` as `_timing.py` — a session
    that does not exist — and `revision/_ingest.py` as the flat
    `ingest.py`'s (BACKLOG, 2026-09-13). A path outside the package, as a
    test hands one over, is its own name.
    """
    posix = module.as_posix()
    marker = "src/docxkit/"
    return posix.split(marker, 1)[1] if marker in posix else module.name


def cases_for(module: Path, db: Path | None = None,
              src: Path | None = None,
              say: Callable[[str], None] | None = None) -> list[Case]:
    """Every real survivor, as a `kill_check` case expecting a KILL.

    The anchor is the whole line INCLUDING its indentation, and the
    occurrence index is computed rather than guessed: a survivor list is
    full of lines a module repeats — `elif tag == "insert":` and
    `return None` — and `kill_check` skips an ambiguous anchor rather
    than mutating the wrong one. Thirteen of `_compare_diff`'s sixty
    went unanswered on the first pass for exactly that reason.

    A survivor this cannot build a case for is REPORTED through `say`,
    never dropped in silence. It dropped them for as long as this tool
    existed, and the cost is a report that covers less than it claims:
    `cite_grammar` has 35 open survivors and one of them renders no
    line, so a replay answered for 34 and said nothing about the 35th,
    leaving its own count quietly disagreeing with the survivor list. A
    tool that reports nothing gets questioned; one that is
    nearly-complete gets believed.
    """
    # `session_file` already answers with an absolute path; `db` and
    # `src` are for a test, which cannot use this repo's own session.
    counts = classify(str(db or session_file(module_key(module))),
                      str(src or ROOT / module))
    if counts is None:
        return []
    text = "\n".join(counts.lines)
    cases: list[Case] = []
    for row, _col, operator, _outcome, diff in counts.real:
        # cosmic-ray numbers rows from 1, as `mutation_survivors` reads
        # them (`lines[row - 1]`). Adding one here anchored every case on
        # the line AFTER its mutation, and the dry run said so: a
        # `continue` paired with `if tag is "equal":`.
        old = counts.lines[row - 1]
        new = became(diff)
        if not new and operator in LINELESS_OPERATORS:
            # A mutation that REMOVES its line renders none, which is
            # why no claim can key on one by `line` — and applying it is
            # deleting the anchor. `equivalents.toml` settled that
            # spelling for these operators and `verify_equivalents`
            # applies a claim exactly this way; two tools beside each
            # other cannot answer one question differently. `kill_check`
            # compiles before it runs, so the shape this cannot express
            # — a decorator spread over several lines — is refused
            # loudly there rather than replayed as some other mutation.
            new = ""
        elif not new or new.strip() == old.strip():
            what = ("renders no line, and "
                    f"{operator.split('/')[-1]} is not one of the "
                    f"operators a deletion can stand for"
                    if not new else "renders the line it replaces")
            _tell(say, f"  -- L{row} {operator.split('.')[-1]}: SKIPPED, it "
                       f"{what}")
            continue
        else:
            # `became` gives the line unparsed, so it carries no
            # indentation.
            new = old[:len(old) - len(old.lstrip())] + new.strip()
        # Counted by the function that then matches the anchor. `count`
        # also finds an indented line inside a DEEPER copy of it, where
        # `kill_check` takes an indented anchor only as a whole line, and
        # four of `revision/_gates.py`'s eleven asked for the second of
        # one and were skipped (BACKLOG, 2026-09-14).
        offset = sum(len(line) + 1 for line in counts.lines[:row - 1])
        nth = sum(1 for at in _places(text, old) if at < offset) + 1
        cases.append((f"L{row} {operator.split('.')[-1]}",
                      old, new, True, nth))
    return cases


def _tell(say: Callable[[str], None] | None, line: str) -> None:
    """Say it, where a caller asked to be told. Default silence is for
    the callers that only want the cases — a test, and the script a
    round writes to ask a session one question."""
    if say is not None:
        say(line)


def source_moved(module: Path, moved: list[str]) -> bool:
    """Is the MODULE among what changed since the run, not just tests?

    `state` reports POSIX-relative paths; `str(Path("src/docxkit/x.py"))`
    on Windows is backslashed, so comparing the two directly is a guard
    that never fires on the platform this package is developed on.
    """
    key = module_key(module)
    return any(m == key or m.endswith(f"/{key}") for m in moved)


def measured_source(key: str, db: Path | None = None,
                    src: Path | None = None) -> Path | None:
    """The module AS THE RUN MEASURED IT, where the run kept a copy.

    `--src` names it; otherwise it is the copy `mutation_session` keeps
    beside its session, in ``.mutation-<stem>.pristine/``. None when
    there is neither — the runs that predate the snapshot mechanism, and
    a session handed over without its folder.
    """
    if src is not None:
        return src if src.is_file() else None
    kept = (db.with_suffix(".pristine") if db is not None
            else snapshot_of(key)) / "src" / "docxkit" / key
    return kept if kept.is_file() else None


def module_moved(module: Path, moved: list[str], *,
                 was: Path | None) -> tuple[bool, str]:
    """Has the MODULE itself changed since the run — and by which test?

    BYTES wherever the run kept the source it measured, because
    timestamps answer this question wrongly in the place it is now asked
    from: a fresh `git worktree add` stamps every file's mtime to now,
    so an unchanged module reads as moved and the replay refuses for a
    reason that is not true. `stale_figures.moved_by_content` already
    applies the byte rule inside `state`; this brings it to the sessions
    `state` cannot see — one named with `--db`, and one whose snapshot
    predates the mechanism.

    Timestamps remain the fallback, and the refusal NAMES which test it
    applied. The refusal itself must keep refusing: replaying a list
    against a moved module grades mutations nobody made, and a false
    refusal costs a re-sweep while a false pass costs a wrong answer
    nobody can see.
    """
    here = ROOT / module
    if was is not None and here.is_file():
        # `lines_of`, not a byte comparison and not a copy of one: the
        # same question is asked by `stale_figures.moved_by_content` and
        # by `mutation_session.moved_since`, and three spellings of it
        # is three places for a checkout's line endings to read as an
        # edit. It lives where `state` does.
        return lines_of(was) != lines_of(here), "bytes"
    return source_moved(module, moved), "timestamps"


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Replay a session's survivors against today's tests.")
    ap.add_argument("module", help="e.g. src/docxkit/guard.py")
    ap.add_argument("--tests", nargs="+", default=[],
                    help="override the harness from harness_map.py")
    ap.add_argument("--db", type=Path, default=None,
                    help="the session to replay, when it is not the one "
                         "beside this tree — a branch worktree's case")
    ap.add_argument("--src", type=Path, default=None,
                    help="the module as that session measured it; what the "
                         "moved check compares against")
    args = ap.parse_args()

    module = Path(args.module)
    key = module_key(module)
    # `harness_for`, not `HARNESS[...]`: two modules have no entry and
    # are measured through its named-after fallback, and reading the
    # dict directly refused them where `mutation_session` would have
    # run. It raises SystemExit with the remedy when nothing names the
    # module, which is the right answer and not this tool's to reword.
    tests = args.tests or harness_for(key)

    # `state` asks about the session beside THIS tree. A session named on
    # the command line is one this tree does not have, so there is no
    # freshness to report about it — what still has to hold is that the
    # module has not moved, which is asked below against the source that
    # session measured.
    if args.db is None:
        verdict, moved = state(key, tests)
        print(f"{key}: the run is {verdict}"
              + (f" ({', '.join(moved)} moved since)" if moved else ""))
    else:
        verdict, moved = "named on the command line", []
        print(f"{key}: the run is {verdict} ({args.db})")

    # Replay answers "did the TESTS catch up with this list". It cannot
    # answer anything once the SOURCE has moved: the survivors are line
    # numbers into a file that no longer has those lines, so every
    # anchor either misses — `kill_check` skips it and the run reports a
    # tidy nothing — or, worse, still matches a line that has since
    # shifted underneath it, and the verdict is about a mutation the
    # session never ran. That is the wrong-line failure this tool's own
    # test exists for, arriving through the other door.
    gone, how = module_moved(module, moved,
                             was=measured_source(key, args.db, args.src))
    if gone:
        print(f"\nREFUSING: {key} itself has moved since the run, by "
              f"{how}.\n"
              f"  A survivor is a line number, and they are line numbers "
              f"into a file that no longer\n  has those lines. Re-sweep "
              f"instead:\n"
              f"    python tools/mutation_session.py {module} --tests "
              f"{' '.join(tests)} --fresh --fast --chunks 0")
        if how == "timestamps":
            # The false refusal, and the one shape it takes. Said here
            # rather than left to be rediscovered: it cost three people
            # an afternoon between them on 2026-09-18.
            print(f"\n  Read by TIMESTAMPS, because nothing holds the "
                  f"module as that run measured it\n  to compare against. "
                  f"A fresh `git worktree add` stamps every file's mtime "
                  f"to now,\n  so an UNCHANGED module reads as moved in "
                  f"one. If it is unchanged, say so by\n  naming the "
                  f"session and that source:\n"
                  f"    python tools/replay_survivors.py {module} "
                  f"--db <the session>.sqlite \\\n"
                  f"        --src <the tree it measured>/{module}")
        return 2

    skipped: list[str] = []
    # positionally, as `verify_equivalents` passes its own `say`: the
    # tests here stand in for this function with `lambda module, *named`,
    # and a keyword argument would be the one shape those cannot take.
    cases = cases_for(module, args.db, args.src, skipped.append)
    for line in skipped:
        print(line)
    if not cases:
        # NOT "no real survivors on record" when some were skipped: that
        # is a count covering less than it claims, and it reads as a
        # clean module. The lines above say which and why.
        print(f"nothing to replay — {len(skipped)} real survivor(s) on "
              f"record, none of them replayable" if skipped else
              "nothing to replay — no real survivors on record")
        return 0
    print(f"replaying {len(cases)} survivor(s) against {len(tests)} test "
          f"file(s)"
          + (f", {len(skipped)} skipped above" if skipped else "") + "\n")

    # `check` returns how many did NOT match their expectation, and every
    # case here expects a KILL — so its return value IS the number still
    # alive, and the ones it reports as unexpected are the list to mine.
    alive = check(str(module), tests, list(cases))
    print(f"\n{len(cases) - alive} now KILLED, {alive} still alive")
    if alive:
        print("The still-alive ones above are the round's real list; the "
              "rest were killed by tests written since the sweep.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
