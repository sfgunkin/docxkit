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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]

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
    "word.py": 99,
    # Held above DEFAULT deliberately: every refusal in here is a thing
    # that failed SILENTLY in a real paper, and an uncovered refusal is
    # one nobody would notice had stopped working.
    "revision.py": 97,
    # Was 73, described as "the branches are for a machine with no
    # console attached, which pytest always has". They are not: a real
    # `io.TextIOWrapper` over a `BytesIO` IS what a console stream is,
    # and reconfiguring one is the whole function. 100% since
    # `tests/test_console.py` (2026-08-17).
    "console.py": 100,
    # The facade. Its main() is the CLI's job and is covered there.
    "compare.py": 98,
    # Report renderers: every branch prints, and pinning the exact
    # wording of 11 sections would test the prose, not the logic.
    "_compare_render.py": 97,
    # A day old and the least-tested thing in the package when it
    # landed (20.2 % real survival, 90 % lines). The floor is here so
    # the climb out of that cannot be given back quietly; the one
    # statement short of 100 is `_caption_of`'s empty return, which no
    # block can reach — a block always holds the caption that found it.
    "placement.py": 97,
    "_cite_build.py": 85,
    "_compare_diff.py": 92,
}


def measure() -> dict[str, float]:
    """Run the suite under coverage and return module -> percent.

    A RED suite produces no measurement. `check=False` is deliberate —
    the report has to be read even when pytest exits non-zero — but the
    exit code was then thrown away, so a run that failed part-way was
    compared against the floors as though it had finished. Seen once on
    2026-08-21: a single failing test in the tables suite, and this tool
    reported `_table_core.py: 55.8% is below its floor of 85%`, which
    sent a reader looking for tests that were there all along. A number
    from a partial run is not a low number, it is not a number.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cov.json"
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--cov=docxkit",
             f"--cov-report=json:{out}"],
            cwd=ROOT, check=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        if not out.exists():
            sys.exit("coverage produced no report; is pytest-cov installed? "
                     "(pip install -e .[dev])")
        if done.returncode:
            tail = "\n".join(
                ln for ln in (done.stdout or "").splitlines()
                if ln.startswith("FAILED") or " passed" in ln
                or " failed" in ln)
            sys.exit(f"the suite is RED (pytest exit {done.returncode}), so "
                     f"coverage from this run measures nothing. Fix the "
                     f"tests, then read the floors.\n{tail}")
        data = json.loads(out.read_text(encoding="utf-8"))
    return {Path(name).name: info["summary"]["percent_covered"]
            for name, info in data["files"].items()}


def check(actual: dict[str, float]) -> list[str]:
    below = []
    for module, pct in sorted(actual.items()):
        floor = FLOORS.get(module, DEFAULT)
        if pct + 0.05 < floor:          # rounding, not a real regression
            below.append(f"{module}: {pct:.1f}% is below its floor of "
                         f"{floor}%")
    return below


def update(actual: dict[str, float]) -> None:
    """Rewrite FLOORS from a fresh run, keeping the comments."""
    src = Path(__file__).read_text(encoding="utf-8")

    def one(m: re.Match[str]) -> str:
        module, floor = m.group(1), int(m.group(2))
        now = actual.get(module)
        if now is None:
            return m.group(0)
        return f'    "{module}": {max(floor, int(now))},'

    src = re.sub(r'    "([\w.]+)": (\d+),', one, src)
    Path(__file__).write_text(src, encoding="utf-8")
    print("floors updated from this run")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    utf8_stdout()
    ap.add_argument("--report", action="store_true",
                    help="print the table and exit 0 whatever it says")
    ap.add_argument("--update", action="store_true",
                    help="raise the floors to match this run")
    args = ap.parse_args()

    actual = measure()
    if args.update:
        update(actual)
        return 0

    for module, pct in sorted(actual.items(), key=lambda kv: kv[1]):
        floor = FLOORS.get(module, DEFAULT)
        room = pct - floor
        flag = "  <-- BELOW FLOOR" if room < -0.05 else ""
        if args.report or room < 5:
            print(f"  {pct:6.1f}%  (floor {floor:3}%)  {module}{flag}")

    below = check(actual)
    if below and not args.report:
        print("\nCOVERAGE FLOOR FAILED")
        for line in below:
            print(f"  {line}")
        print("\nAdd the test, or — if the drop is deliberate — lower the "
              "floor in tools/coverage_floor.py and say why.")
        return 1
    print("\nevery module is at or above its floor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
