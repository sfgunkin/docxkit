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
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_map import harness_for  # pyright: ignore[reportMissingImports]
from kill_check import check  # pyright: ignore[reportMissingImports]
from mutation_survivors import (  # pyright: ignore[reportMissingImports]
    became,
    classify,
)
from stale_figures import (  # pyright: ignore[reportMissingImports]
    ROOT,
    session_file,
    state,
)

from docxkit.console import utf8_stdout

Case = tuple[str, str, str, bool, int]


def cases_for(module: Path, db: Path | None = None,
              src: Path | None = None) -> list[Case]:
    """Every real survivor, as a `kill_check` case expecting a KILL.

    The anchor is the whole line INCLUDING its indentation, and the
    occurrence index is computed rather than guessed: a survivor list is
    full of lines a module repeats — `elif tag == "insert":` and
    `return None` — and `kill_check` skips an ambiguous anchor rather
    than mutating the wrong one. Thirteen of `_compare_diff`'s sixty
    went unanswered on the first pass for exactly that reason.
    """
    # `session_file` already answers with an absolute path; `db` and
    # `src` are for a test, which cannot use this repo's own session.
    counts = classify(str(db or session_file(module.name)),
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
        if not new or new.strip() == old.strip():
            continue
        # `became` gives the line unparsed, so it carries no indentation.
        new = old[:len(old) - len(old.lstrip())] + new.strip()
        offset = sum(len(line) + 1 for line in counts.lines[:row - 1])
        nth = text.count(old, 0, offset) + 1
        cases.append((f"L{row} {operator.split('.')[-1]}",
                      old, new, True, nth))
    return cases


def source_moved(module: Path, moved: list[str]) -> bool:
    """Is the MODULE among what changed since the run, not just tests?

    `state` reports POSIX-relative paths; `str(Path("src/docxkit/x.py"))`
    on Windows is backslashed, so comparing the two directly is a guard
    that never fires on the platform this package is developed on.
    """
    name = module.name
    return any(m == name or m.endswith(f"/{name}") for m in moved)


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Replay a session's survivors against today's tests.")
    ap.add_argument("module", help="e.g. src/docxkit/guard.py")
    ap.add_argument("--tests", nargs="+", default=[],
                    help="override the harness from harness_map.py")
    args = ap.parse_args()

    module = Path(args.module)
    # `harness_for`, not `HARNESS[...]`: two modules have no entry and
    # are measured through its named-after fallback, and reading the
    # dict directly refused them where `mutation_session` would have
    # run. It raises SystemExit with the remedy when nothing names the
    # module, which is the right answer and not this tool's to reword.
    tests = args.tests or harness_for(module.name)

    verdict, moved = state(module.name, tests)
    print(f"{module.name}: the run is {verdict}"
          + (f" ({', '.join(moved)} moved since)" if moved else ""))

    # Replay answers "did the TESTS catch up with this list". It cannot
    # answer anything once the SOURCE has moved: the survivors are line
    # numbers into a file that no longer has those lines, so every
    # anchor either misses — `kill_check` skips it and the run reports a
    # tidy nothing — or, worse, still matches a line that has since
    # shifted underneath it, and the verdict is about a mutation the
    # session never ran. That is the wrong-line failure this tool's own
    # test exists for, arriving through the other door.
    if source_moved(module, moved):
        print(f"\nREFUSING: {module.name} itself has moved since the run.\n"
              f"  A survivor is a line number, and they are line numbers "
              f"into a file that no longer\n  has those lines. Re-sweep "
              f"instead:\n"
              f"    python tools/mutation_session.py {module} --tests "
              f"{' '.join(tests)} --fresh --fast --chunks 0")
        return 2

    cases = cases_for(module)
    if not cases:
        print("nothing to replay — no real survivors on record")
        return 0
    print(f"replaying {len(cases)} survivor(s) against {len(tests)} test "
          f"file(s)\n")

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
