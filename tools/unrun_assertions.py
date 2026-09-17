#!/usr/bin/env python
"""Assertions the suite never ran.

    python tools/unrun_assertions.py                  # measure and check
    python tools/unrun_assertions.py --from-json PATH # the gate's report
    python tools/unrun_assertions.py --report         # print, never fail

A test can pass without making its assertions: the loop body that never
had an item, the `else` of a try whose `except` is the path that runs,
the branch a fixture cannot reach. Nothing else in the chain can see it.
Coverage floors ask whether the SOURCE ran; `pytest` reports a pass;
mutation testing measures what the suite kills and a test that asserts
nothing kills nothing, so it does not even move the figure. The evidence
is in the coverage report all along, about the test files rather than
the package: an `assert` line that never executed is an assertion nobody
made.

**The defect that put it here.** On 2026-09-18 `tools/can_it_fail.py`
was written to settle "this test cannot fail" by breaking the thing and
watching. An hour later its author used it on a test he had just
written to FIX one of these — `test_exhibit_block_never_answers_with_
ANOTHER_captions_span`, a happy-path version carrying the name of a
guarantee — and it could not fail for the mutant in its own docstring:
`==` and `>=` agree wherever `exhibits` reads the paragraph as a
caption, and differ exactly where `==` finds nothing, so the refusal is
the whole of the guarantee and a returned block can never show it. A
test that cannot fail, written by the person holding the detector, an
hour after building it. That is how ordinary this is, and why it wants
a gate rather than a habit.

**Three states, because there are three answers.**

* A test the run never ENTERED — deselected (`-m "not word"`), skipped,
  or a parametrize with no cases — is not a finding. The run summary
  already says so, and this reads it off the report rather than from
  markers: a test that ran has its first statement covered.
* A test that says so ITSELF, with `pytest.skip` or `importorskip`, is
  not a finding either. Standing down in the open is the honest shape,
  and it is what the suite's own empty-`DEBT` tests were changed to.
* An unrun assertion in a test that RAN and PASSED is the finding.

**It refuses rather than passing when it cannot see the tests**, which
is the failure it exists to catch, one level up: without `--cov=tests`
in the pytest gate the report holds no test files at all, every
assertion is unseen, and "0 findings" would be the same line as a clean
tree. That is exit 3, the state `sweep` uses for the same reason.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: A coverage JSON, as `--cov-report=json` writes it: per file, the
#: lines that ran and the lines that did not.
Report = dict[str, Any]

#: Unrun assertions that are deliberate, keyed by the test they are in —
#: not by line, which the next edit above them moves. Each entry says
#: why, and is the sentence somebody has to defend when the reason stops
#: being true. An exception that has to be written down is an exception
#: somebody has to defend.
ALLOWED: dict[str, str] = {
    "test_stale_figures.py::test_the_figures_mode_prints_a_figure_per_module":
        "a CHECKOUT has no session files — they are local and none is "
        "committed — so the shape of a line that carries a figure can "
        "only be asserted on a machine that has measured one. The test "
        "says this itself, beside the loop.",
}


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    test: str
    source: str

    @property
    def key(self) -> str:
        return f"{Path(self.file).name}::{self.test}"

    def __str__(self) -> str:
        return f"{self.file}:{self.line}  {self.test}\n      {self.source}"


def _body_span(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> range:
    """The function's statements, without its `def` line or decorators.

    Those run at IMPORT, so counting them would call every collected
    test "entered" — including the ones the run never reached, which is
    the distinction this whole tool turns on.
    """
    first = fn.body[0]
    start = first.lineno
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
            and isinstance(first.value.value, str) and len(fn.body) > 1:
        start = fn.body[1].lineno          # the docstring is not a statement
    return range(start, (fn.end_lineno or start) + 1)


def _stands_down(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Does the test declare its own skip? Then it is not hiding."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            shown = ast.unparse(node.func)
            if shown.endswith(("pytest.skip", "pytest.importorskip",
                               "pytest.xfail", "skip", "importorskip")):
                return True
    return False


def findings(report: Report, root: Path = ROOT) -> list[Finding]:
    """Every assertion a test that RAN did not make."""
    out: list[Finding] = []
    for name, entry in sorted(report.get("files", {}).items()):
        posix = Path(name).as_posix()
        if "tests/" not in posix and not posix.startswith("tests"):
            continue
        missing = set(entry.get("missing_lines", ()))
        executed = set(entry.get("executed_lines", ()))
        if not missing:
            continue
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        tree = ast.parse(text)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            span = _body_span(fn)
            if not executed.intersection(span):
                continue                   # the run never entered it
            if _stands_down(fn):
                continue                   # it says so itself
            for node in ast.walk(fn):
                if isinstance(node, ast.Assert) and node.lineno in missing:
                    out.append(Finding(posix, node.lineno, fn.name,
                                       lines[node.lineno - 1].strip()))
    return out


def _read(path: Path) -> Report:
    loaded: Report = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _measure() -> Report:
    """Run the suite and read the report, for a run of this tool alone."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cov.json"
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--cov=docxkit",
             "--cov=tests", f"--cov-report=json:{out}"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        if not out.is_file():
            raise SystemExit(f"the suite produced no report:\n{done.stdout}")
        return _read(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.
                                 RawDescriptionHelpFormatter)
    ap.add_argument("--from-json", metavar="PATH",
                    help="a coverage JSON the pytest gate already wrote")
    ap.add_argument("--report", action="store_true",
                    help="print what was found and exit 0")
    args = ap.parse_args(argv)

    report = (_read(Path(args.from_json)) if args.from_json else _measure())
    seen = [name for name in report.get("files", ())
            if Path(name).as_posix().startswith("tests")]
    if not seen:
        print("no test files in the coverage report, so every assertion in "
              "them is unseen — run the suite with `--cov=tests` (the "
              "pytest gate does). Refusing rather than reporting 0.")
        return 3

    found = findings(report)
    kept = [f for f in found if f.key not in ALLOWED]
    for finding in kept:
        print(f"  {finding}")
    for finding in (f for f in found if f.key in ALLOWED):
        print(f"  allowed  {finding.key}: {ALLOWED[finding.key][:60]}...")
    if args.report:
        print(f"\n{len(kept)} unrun assertion(s) in {len(seen)} test file(s)")
        return 0
    if kept:
        print(f"\n{len(kept)} assertion(s) above never ran, in tests that "
              f"did. Make the fixture reach them, assert what the test "
              f"actually proves, or skip with a reason — a green test that "
              f"asserts nothing reads as a guard standing.")
        return 1
    print(f"every assertion in {len(seen)} test file(s) ran")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
