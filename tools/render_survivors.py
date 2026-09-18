#!/usr/bin/env python
"""What a session's survivors WOULD be against the module as it stands.

Two questions, and the difference between them is the whole reason this
file exists beside `replay_survivors.py`:

    replay_survivors.py   are these mutants still alive, AS RECORDED?
    render_survivors.py   what are these mutations against the file TODAY?

`replay_survivors` anchors each case on the line text the session stored
and REFUSES outright once the module itself has moved — correctly, because
a stored diff applied to changed source grades a mutation nobody made.
That refusal leaves a round with two bad choices: re-sweep (an hour, and
the session is then a different session) or work blind. Three rounds hit
it in one day, on `pages.py`, on `word.py` and on `revision/_gates.py`,
and one of them had to rebuild the list by hand to get on with the round.

So: rebuild each mutant instead of replaying it. cosmic-ray records the
OPERATOR and the OCCURRENCE, not just the text, and both are re-appliable
— `mutate_code(source, operator, occurrence)` produces the mutated source
for whatever the file says now. The one line that differs is the pair a
`kill_check` case needs.

    python tools/render_survivors.py src/docxkit/word.py
    python tools/render_survivors.py src/docxkit/word.py --replay
    python tools/render_survivors.py src/docxkit/word.py --json cases.json

`--replay` puts them through `kill_check` expecting a KILL, which is the
same answer `replay_survivors` gives, against anchors that exist. `--json`
writes the cases out for a round that wants a verdict per mutant — which
is what a survivor round actually does, since its whole job is deciding
which ones SHOULD be killed.

**It refuses rather than guesses, per mutant.** An occurrence is a
position in a list of the operator's sites, so an edit that adds or
removes a site of that operator makes occurrence N name a different
place. Every mutant is therefore rebuilt against the SNAPSHOT first and
checked against what the session recorded for it: a pair that no longer
reproduces its own record is reported and left out, never rendered on the
assumption that it still means what it meant. What comes out is a list
whose every entry has been shown to be the mutation the session ran.

**And it says which mutants stand on a line that has itself changed**,
which is the case this tool is usually reached for. That is not a
refusal: the line moved, the mutation is still the mutation, and a round
that added a trailing comment to make a claim anchor unique needs exactly
that rendering. It is a note because the reader is the one who can judge
it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# cosmic-ray ships no type information AND is in no extra: it is
# installed on the machine that runs the sweeps and nowhere else, which
# makes it absent more often than an optional extra, not less. Both
# checkers are told so in pyproject's override list, beside pymupdf and
# latex2mathml — an inline `type: ignore[import-untyped]` here said the
# opposite and took CI down with it (2026-09-18).
#
# Left at module level rather than deferred into the functions: this
# tool does nothing at all without cosmic-ray, and a lazy import would
# buy an `--help` that works on a machine where no command does.
from cosmic_ray.mutating import (
    mutate_code,  # pyright: ignore[reportMissingImports]
)
from cosmic_ray.plugins import (
    get_operator,  # pyright: ignore[reportMissingImports]
)
from harness_map import harness_for  # pyright: ignore[reportMissingImports]
from kill_check import check  # pyright: ignore[reportMissingImports]
from mutation_survivors import (  # pyright: ignore[reportMissingImports]
    became,
    classify,
    pristine_source,
)
from replay_survivors import (
    module_key,  # pyright: ignore[reportMissingImports]
)
from stale_figures import (  # pyright: ignore[reportMissingImports]
    ROOT,
    session_file,
)

from docxkit.console import utf8_stdout


class Rendered(NamedTuple):
    """One survivor, rebuilt against the file as it stands."""

    label: str
    #: the line it stands on TODAY, with its indentation
    old: str
    #: that line as the mutation writes it today
    new: str
    #: which of the identical copies of `old` this is, 1-based, the way
    #: `kill_check` counts them: on the WHOLE line, indentation included
    nth: int
    #: where it stands today, and where the session had it
    row: int
    run_row: int
    #: None when the line is the one the session mutated, or the line as
    #: the session had it when it is not
    was: str | None


def _operator(name: str, args: str | None):
    """cosmic-ray's operator instance for a stored spec.

    `operator_args` is JSON holding a JSON string — the session writes
    `'"{}"'` — so it is decoded until it stops being one.
    """
    kwargs = json.loads(args or "{}")
    while isinstance(kwargs, str):
        kwargs = json.loads(kwargs)
    return get_operator(name)(**kwargs)


def _one_change(before: str, after: str) -> tuple[int, str, str] | None:
    """`(index, old, new)` for the single line that differs, else None.

    A mutation that rewrites more than one line cannot be rendered as a
    `kill_check` case, which anchors on exactly one, and is reported
    rather than trimmed to its first line — trimming would hand back an
    anchor that mutates half of what the session ran.
    """
    pairs = [(i, a, b) for i, (a, b) in enumerate(
        zip(before.splitlines(), after.splitlines(), strict=False)) if a != b]
    if len(pairs) != 1:
        return None
    return pairs[0]


def survivors(module: Path, db: Path | None = None,
              src: Path | None = None) -> tuple[list[Rendered], list[str]]:
    """Every real survivor rebuilt against today's `module`, and the
    problems: one string per mutant that could not be rebuilt.

    `db` and `src` are for a test, which cannot use this repo's own
    session — the same shape `replay_survivors.cases_for` takes.
    """
    key = module_key(module)
    session = db or session_file(key)
    today = (src or ROOT / module).read_text(encoding="utf-8")
    counts = classify(str(session), str(src or ROOT / module))
    if counts is None:
        return [], ["the session graded nothing"]
    snapshot, _ = pristine_source(str(session), str(src or ROOT / module))
    before = Path(snapshot).read_text(encoding="utf-8")
    # Keyed on what the mutation PRODUCED as well as where it stood: two
    # mutants of one operator can share a row and a column — `capture_
    # output=True` and `text=True` on one call are both a True replaced
    # by a False — and a key that cannot tell them apart renders a
    # claimed mutant as though it were still open. Counted rather than
    # set, so one recorded mutant answers for one row and no more.
    recorded = Counter((row, col, operator, became(diff).strip())
                       for row, col, operator, _outcome, diff in counts.real)

    rows = sqlite3.connect(str(session)).execute("""
        SELECT s.start_pos_row, s.start_pos_col, s.operator_name,
               s.occurrence, s.operator_args, r.diff
        FROM mutation_specs s JOIN work_results r ON s.job_id = r.job_id
        WHERE r.test_outcome = 'SURVIVED'
        ORDER BY s.start_pos_row, s.operator_name, s.occurrence
    """).fetchall()

    out: list[Rendered] = []
    problems: list[str] = []
    lines = today.splitlines()
    for row, col, name, occurrence, args, diff in rows:
        mutant = (row, col, name, became(diff).strip())
        if not recorded[mutant]:          # annotation, claimed, cosmetic
            continue
        recorded[mutant] -= 1
        label = f"L{row} {name.split('.')[-1]}"
        operator = _operator(name, args)
        # the SNAPSHOT first: a pair that no longer reproduces its own
        # record names a different site now, and rendering it against
        # today's file would be a confident answer about another mutant
        then = mutate_code(before, operator, occurrence)
        was = _one_change(before, then) if then else None
        if was is None or was[2].strip() != became(diff).strip():
            problems.append(
                f"{label}: occurrence {occurrence} no longer reproduces what "
                f"the session recorded for it — not rendered")
            continue
        now = mutate_code(today, operator, occurrence)
        change = _one_change(today, now) if now else None
        if change is None:
            problems.append(
                f"{label}: rewrites more than one line today, so it cannot "
                f"be anchored — not rendered")
            continue
        at, old, new = change
        out.append(Rendered(
            label=label, old=old, new=new, row=at + 1, run_row=row,
            nth=sum(1 for ln in lines[:at] if ln == old) + 1,
            was=None if old.strip() == was[1].strip() else was[1].strip()))
    return out, problems


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Rebuild a session's survivors against the file today.")
    ap.add_argument("module", help="e.g. src/docxkit/word.py")
    ap.add_argument("--replay", action="store_true",
                    help="put them through kill_check expecting a KILL")
    ap.add_argument("--json", metavar="PATH",
                    help="write the cases out for a round's own driver")
    ap.add_argument("--tests", nargs="+", default=[],
                    help="override the harness from harness_map.py")
    args = ap.parse_args(argv)

    module = Path(args.module)
    if not (ROOT / module).is_file():
        print(f"no module at {module}")
        return 2
    session = session_file(module_key(module))
    if not session.is_file():
        # `sqlite3.connect` CREATES a missing file, so the refusal comes
        # before anything opens it — `mutation_survivors`' rule.
        print(f"no session at {session.name}: nothing was read, and "
              f"nothing was created")
        return 2

    rendered, problems = survivors(module)
    print(f"{len(rendered)} survivor(s) rebuilt against {module.as_posix()} "
          f"as it stands")
    print("  (what these mutations ARE today — `replay_survivors.py` "
          "answers\n  whether they are still alive as the session recorded "
          "them)\n")
    for one in rendered:
        where = f"L{one.row}" + ("" if one.row == one.run_row
                                 else f" (the run had it at L{one.run_row})")
        print(f"  {one.label.split(' ', 1)[1]:<38} {where}")
        print(f"    was  {one.old.strip()[:70]}")
        print(f"    ->   {one.new.strip()[:70]}")
        if one.was is not None:
            print(f"    the LINE has changed since the run, which had: "
                  f"{one.was[:40]}")
    for problem in problems:
        print(f"  !! {problem}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            [{"label": r.label, "row": r.row, "old": r.old, "new": r.new,
              "nth": r.nth, "was": r.was} for r in rendered], indent=1),
            encoding="utf-8")
        print(f"\n  cases written to {args.json}")

    if args.replay and rendered:
        tests = args.tests or harness_for(module_key(module))
        print(f"\nreplaying {len(rendered)} rebuilt case(s) against "
              f"{len(tests)} test file(s)\n")
        alive = check(str(module), tests,
                      [(r.label, r.old, r.new, True, r.nth)
                       for r in rendered])
        print(f"\n{len(rendered) - alive} now KILLED, {alive} still alive")
    # A mutant that could not be rebuilt is a hole in the answer, not a
    # detail: the list below it reads as complete either way.
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
