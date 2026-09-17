#!/usr/bin/env python
"""Per-module coverage floors, as a ratchet.

    python tools/coverage_floor.py            # measure and check
    python tools/coverage_floor.py --report   # just print, never fail
    python tools/coverage_floor.py --update   # rewrite the floors below

A single global number hides the thing worth knowing. This package sat
at 88% overall while `tracked.py` — which builds the deliverable that
ships to journals — was at 0%, because 300 well-covered statements
elsewhere paid for it. The floor is per module for that reason.

The floors are the CURRENT numbers, not aspirations: a module may never
lose coverage, and the exceptions below say out loud where the debt is
rather than hiding it in an average. Raise one when you cover more;
`--update` rewrites them all from a fresh run, which is the honest way
to record that the debt shrank.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
#: pytest's USAGE error — what a missing plugin looks like.
_PYTEST_USAGE_ERROR = 4

#: A module may not fall below its floor. Anything not listed here must
#: clear DEFAULT — a NEW module starts held to the same standard as the
#: rest, which is what stops the next tracked.py landing at 0%.
DEFAULT = 85

FLOORS = {
    # The mutating --write paths are the least-covered code in the
    # package AND the code that touches a manuscript. This is the debt
    # worth paying down first; the number is here so it cannot quietly
    # get worse while it waits.
    "cli.py": 100,
    # Was 73 and described as reachable "the same way tracked.py went
    # 0 -> 99% on a fake". It was: 99% now, faking COM in `sys.modules`
    # because `session` imports pythoncom and win32com INSIDE the
    # function. The one statement left is `_Finder.find`'s early return,
    # which needs the fuller document fake `test_locate.py` already
    # carries — worth folding in when something else touches that class.
    "word.py": 100,
    # ---- the revision protocol, held above DEFAULT deliberately: every
    # refusal in here is a thing that failed SILENTLY in a real paper,
    # and an uncovered refusal is one nobody would notice had stopped
    # working.
    #
    # `revision.py` was ONE line here, at 97, until it became
    # `revision/` on 2026-08-30. Restating it as fourteen is not
    # bookkeeping: a floor keyed on a file that no longer exists is a
    # floor that cannot be met, and a half with no entry falls to
    # DEFAULT — so the split would have handed back twelve points on the
    # highest-risk module in the package with the gate still green.
    #
    # The numbers are MEASURED, not apportioned, and the measurement is
    # the interesting part: the 97 was an average, and it was hiding
    # `_build.py` at 84.7 — below the package DEFAULT, in the half that
    # drives Word's Compare. Nothing was lost in the split; that module
    # had been the least-tested thing in the protocol all along, and one
    # aggregate over 3,118 lines could not say so.
    #
    # It is at 100 now (2026-08-30). What was uncovered was four
    # WARNINGS and the long-list arm of one refusal — a note definition
    # out of document order, links inside a tracked deletion, a footnote
    # whose reference moved — which is the exact class this block is
    # held above DEFAULT for. Each had failed silently in a real paper
    # once; none had a test.
    "revision/__init__.py": 100,
    "revision/_baseline.py": 100,
    "revision/_build.py": 100,
    "revision/_common.py": 100,
    "revision/_config.py": 100,
    "revision/_ledger.py": 100,
    "revision/_gates.py": 100,
    "revision/_ingest.py": 100,
    "revision/_promote.py": 100,
    "revision/_registry.py": 100,
    "revision/_validate.py": 100,
    "revision/_doctor.py": 100,
    "revision/_state.py": 99,
    "revision/_losses.py": 97,
    "revision/_verdict.py": 97,
    "revision/_init.py": 94,
    # Was 73, described as "the branches are for a machine with no
    # console attached, which pytest always has". They are not: a real
    # `io.TextIOWrapper` over a `BytesIO` IS what a console stream is,
    # and reconfiguring one is the whole function. 100% since
    # `tests/test_console.py` (2026-08-17).
    "console.py": 100,
    # The facade. Its main() is the CLI's job and is covered there.
    "compare.py": 98,
    # `tracked.py` had no entry and sat on DEFAULT until it split on
    # 2026-09-11; these are what the three files MEASURED that day, held
    # so the split cannot hand back points in silence — the reason the
    # `revision/` block above restates fourteen floors. The Word pipeline
    # stayed in the facade; the halves are the XML gates and the report.
    "tracked.py": 97,
    "_tracked_gates.py": 94,
    "_tracked_report.py": 97,
    # Report renderers: every branch prints, and pinning the exact
    # wording of 11 sections would test the prose, not the logic.
    "_compare_render.py": 97,
    # A day old and the least-tested thing in the package when it
    # landed (20.2 % real survival, 90 % lines). The floor is here so
    # the climb out of that cannot be given back quietly; the one
    # statement short of 100 is `_caption_of`'s empty return, which no
    # block can reach — a block always holds the caption that found it.
    "placement.py": 97,
    "_cite_build.py": 98,
    "_compare_diff.py": 98,
}


def measure(from_json: Path | None = None) -> dict[str, float]:
    """Run the suite under coverage and return module -> percent.

    `from_json` reads a report the CALLER already produced instead of
    running the suite again. `tools/gates.py` uses it: without it the
    chain runs 4,971 tests twice — once bare and once under coverage —
    which measured 108 s + 126 s of a 247 s chain. The two runs execute
    the same tests over the same code and differ only in whether the
    tracer is attached, and coverage under `-n 8` was verified identical
    to serial (98.102 % both, no file lower).

    A RED suite produces no measurement. `check=False` is deliberate —
    the report has to be read even when pytest exits non-zero — but the
    exit code was then thrown away, so a run that failed part-way was
    compared against the floors as though it had finished. Seen once on
    2026-08-21: a single failing test in the tables suite, and this tool
    reported `_table_core.py: 55.8% is below its floor of 85%`, which
    sent a reader looking for tests that were there all along. A number
    from a partial run is not a low number, it is not a number.
    """
    if from_json is not None:
        if not from_json.exists():
            sys.exit(f"no coverage report at {from_json} — the run that was "
                     f"supposed to write it did not")
        data = json.loads(from_json.read_text(encoding="utf-8"))
        return _measured(data)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cov.json"
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--cov=docxkit",
             f"--cov-report=json:{out}"],
            cwd=ROOT, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        # Two ways to finish with no report, and they need opposite
        # answers. Exit 4 is pytest's USAGE error, which is what a
        # missing pytest-cov looks like ("unrecognized arguments:
        # --cov") — telling that reader the suite is red sends them
        # somewhere nothing is wrong. Any other non-zero exit with no
        # report is a collection error or an abort: the plugin is fine
        # and the run never got far enough to measure anything, and
        # naming the plugin there is the same misdiagnosis in reverse.
        if not out.exists() and done.returncode == _PYTEST_USAGE_ERROR:
            sys.exit("coverage produced no report; is pytest-cov installed? "
                     "(pip install -e .[dev])")
        if done.returncode:
            # stderr as well as stdout: an internal error writes its
            # traceback there, and dropping it left the reader the
            # verdict with none of the evidence.
            tail = "\n".join(
                ln for ln in ((done.stdout or "") + (done.stderr or "")
                              ).splitlines()
                if ln.startswith(("FAILED", "ERROR", "INTERNALERROR"))
                or " passed" in ln or " failed" in ln)
            sys.exit(f"the suite is RED (pytest exit {done.returncode}), so "
                     f"coverage from this run measures nothing. Fix the "
                     f"tests, then read the floors.\n{tail}")
        if not out.exists():
            sys.exit("coverage produced no report; is pytest-cov installed? "
                     "(pip install -e .[dev])")
        data = json.loads(out.read_text(encoding="utf-8"))
    return _measured(data)


def _measured(data: dict[str, Any]) -> dict[str, float]:
    """The PACKAGE's files, by floor key.

    Filtered, because the report is shared: the `pytest` gate measures
    `--cov=docxkit --cov=tests` so that `unrun_assertions` can ask which
    assertion did not run (2026-09-18), and every test file then arrived
    here to be judged against DEFAULT. Four were under it and the gate
    went red over the coverage of test files, which is not a thing this
    tool has an opinion about: a test file is not a module with a floor.
    """
    return {_key(name): info["summary"]["percent_covered"]
            for name, info in data["files"].items()
            if "docxkit" in Path(name).parts}


def _key(path: str) -> str:
    """How a module is named in :data:`FLOORS`.

    The BASENAME until 2026-08-30, which stopped working the moment
    `revision.py` became `revision/`: fourteen halves, plus a second
    `__init__.py` that collides head-on with the package's own. A
    collision here does not crash — one entry overwrites the other in
    the dict, and a module is then measured against a percentage
    belonging to a different file. The gate reports a confident pass, or
    a confident failure, about neither of them.

    So a module inside a subpackage keeps its folder:
    `revision/_losses.py`. Every other key is unchanged, which is why
    the FLOORS list above did not have to be rewritten.
    """
    parts = Path(path).parts
    if len(parts) >= 2 and parts[-2] != "docxkit":
        return f"{parts[-2]}/{parts[-1]}"
    return Path(path).name


def check(actual: dict[str, float]) -> list[str]:
    """Every floor, against what was measured — and every floor.

    Walking `actual` alone answers only about modules the report
    happens to contain, so a floor whose module is MISSING is not
    passed, it is unasked. Two ways that happens and both are quiet:
    a suite that died half way writes a report covering the files it
    reached, and a renamed module leaves its floor behind while the new
    name inherits DEFAULT. `word.py` at 99 and `revision.py` at 97 are
    exactly the floors that would go, and nothing would be red.

    So a floor with no measurement is a failure of its own, worded as
    what it is rather than as a coverage number nobody has.
    """
    below = []
    for module, pct in sorted(actual.items()):
        floor = FLOORS.get(module, DEFAULT)
        if pct + 0.05 < floor:          # rounding, not a real regression
            below.append(f"{module}: {pct:.1f}% is below its floor of "
                         f"{floor}%")
    for module in sorted(set(FLOORS) - set(actual)):
        below.append(f"{module}: has a floor of {FLOORS[module]}% and is "
                     f"NOT in the coverage report — a run that stopped "
                     f"early, or a module that was renamed and left its "
                     f"floor behind")
    return below


#: How far a floor may sit below what the suite actually covers before
#: it has stopped being "the CURRENT number" this file says it is. Slack
#: is not a defect in itself — coverage moves a little between runs, and
#: an afternoon that adds tests SHOULD be able to land without a red
#: chain, which is the reasoning the complexity pins settled on for the
#: same tension. Ten points is past that argument: it is the ratchet not
#: being tightened for weeks, and every point of it is protection the
#: module has silently lost.
SLACK = 10.0

#: Reported from here, so looseness is visible long before it is a
#: failure. The floors rotted precisely because nothing ever mentioned
#: them while they were passing.
SLACK_NOTE = 2.0


def slack(actual: dict[str, float]) -> list[tuple[str, float, float]]:
    """Floors the suite has outgrown: `(module, floor, actual)`.

    `check` only ever looks DOWN — it asks whether a module fell below
    its floor, which is the regression the ratchet exists to stop. It
    cannot see the other way, and the other way is how a ratchet fails:
    coverage rises, nobody re-runs `--update`, and the floor stays where
    it was while the module it guards moves away from it.

    Measured 2026-09-09, and this file's own docstring is what makes it
    a defect rather than a preference — *"The floors are the CURRENT
    numbers, not aspirations"*:

        _cite_build.py     floor 85   actual 98.8   13.8 points
        _compare_diff.py   floor 92   actual 98.6    6.6 points

    `_cite_build` builds every paper's citation apparatus. At a floor of
    85 it could lose about sixty statements of coverage — `link_all`'s
    whole mention-wiring pass, say — and the gate would print "every
    module is at or above its floor" over it.

    Same shape as the complexity pins rotting downward in silence, and
    the same answer: not a hard gate on every point of improvement, but
    it must not be possible for the number to go stale unremarked.

    Only modules with an EXPLICIT floor are asked. `DEFAULT` is the bar a
    module clears before anyone has ratcheted it — "a NEW module starts
    held to the same standard as the rest" — so a module sitting well
    above it is that policy working, not a floor going stale. Reading
    slack against `DEFAULT` too was the first version of this, and it
    reported eighteen modules, every one of them fine.
    """
    out = []
    for module, pct in sorted(actual.items()):
        if module not in FLOORS:
            continue
        floor = float(FLOORS[module])
        if pct - floor >= SLACK_NOTE:
            out.append((module, floor, pct))
    return out


def update(actual: dict[str, float]) -> None:
    """Rewrite FLOORS from a fresh run, keeping the comments.

    Raises only — `max(floor, …)` — so a run against a suite that is
    temporarily worse cannot ratchet the guard DOWN. Lowering a floor is
    the deliberate act the module docstring asks for, made by hand and
    with a reason beside it.

    **The key pattern has to allow a `/`.** It was `[\\w.]+`, which
    matches `tracked.py` and not `revision/_build.py`, so `--update`
    reached 8 of the 24 floors and silently skipped 16 — every module of
    the revision package, which is the half that touches manuscripts.
    It printed "floors updated from this run" over that, so the one
    mechanism this file offers for recording that the debt shrank did
    not work for two thirds of the debt, and said it had. Measured
    2026-09-09.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    raised: list[str] = []

    def one(m: re.Match[str]) -> str:
        module, floor = m.group(1), int(m.group(2))
        now = actual.get(module)
        if now is None:
            return m.group(0)
        if int(now) > floor:
            raised.append(f"{module}: {floor} -> {int(now)}")
        return f'    "{module}": {max(floor, int(now))},'

    src = re.sub(r'    "([\w./]+)": (\d+),', one, src)
    Path(__file__).write_text(src, encoding="utf-8")
    # Say WHICH, not just that something happened: the silent version is
    # what let the skipped sixteen go unnoticed.
    for line in raised:
        print(f"  raised {line}")
    print(f"floors updated from this run — {len(raised)} raised")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    utf8_stdout()
    ap.add_argument("--report", action="store_true",
                    help="print the table and exit 0 whatever it says")
    ap.add_argument("--update", action="store_true",
                    help="raise the floors to match this run")
    ap.add_argument("--from-json", metavar="PATH", type=Path,
                    help="read a coverage report the caller already "
                         "produced instead of running the suite again")
    args = ap.parse_args()

    actual = measure(args.from_json)
    if args.update:
        update(actual)
        return 0

    for module, pct in sorted(actual.items(), key=lambda kv: kv[1]):
        floor = FLOORS.get(module, DEFAULT)
        room = pct - floor
        flag = "  <-- BELOW FLOOR" if room < -0.05 else ""
        if args.report or room < 5:
            print(f"  {pct:6.1f}%  (floor {floor:3}%)  {module}{flag}")

    loose = slack(actual)
    if loose:
        print("\nfloors the suite has OUTGROWN — run --update to re-ratchet:")
        for name, was, now in loose:
            gap = now - was
            mark = "  <-- STALE" if gap >= SLACK else ""
            print(f"  {name}: floor {was:.0f}%, actual {now:.1f}% "
                  f"({gap:.1f} points of slack){mark}")

    below = check(actual)
    below += [f"{name}: floor {was:.0f}% is {now - was:.1f} points below "
              f"the {now:.1f}% the suite actually reaches — the ratchet "
              f"has not been tightened, and that much of the module is "
              f"unguarded"
              for name, was, now in loose if now - was >= SLACK]
    if below:
        # Printed on `--report` too, and the exit code is what differs.
        # The all-clear used to be unconditional, so a `--report` run
        # closed with "every module is at or above its floor" directly
        # under the rows it had just flagged BELOW FLOOR — and that
        # sentence is also the line `gates.py` picks out as a gate's
        # summary, so it could be the last word on a red one.
        print("\nCOVERAGE FLOOR FAILED")
        for line in below:
            print(f"  {line}")
        print("\nAdd the test, or — if the drop is deliberate — lower the "
              "floor in tools/coverage_floor.py and say why.")
        return 0 if args.report else 1
    print("\nevery module is at or above its floor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
