#!/usr/bin/env python
"""Re-measure the C901 pins and print the DEBT dict to paste back.

    python tools/complexity_pins.py

`tests/test_complexity_debt.py` pins every function over the complexity
threshold as `Pin(<complexity>, '<date measured>')`. The gate there is
one-directional by design: it fires when a pinned number GROWS, never
when one shrinks, because a build that goes red for making code simpler
teaches people to edit the number without reading it.

The cost is that a pin can rot downward in silence, and it did. Measured
2026-09-03, three of the five entries then pinned overstated their
functions — `_cite_audit._audit_findings` 31 against 30,
`refstyle.audit` 26 against 25, `edit.replace_in_para` 26 against 24 —
each simplified under the pin, none of them moved. `replace_in_para` had
carried a number 2 too high for ten days. Nothing was wrong with the
code and nothing was wrong with the gate; the numbers were corrected
only because somebody happened to re-measure before paying the debt
down. This is that re-measurement, on demand instead of by luck.

**It exits 0 whatever it finds, and that is deliberate.** A non-zero
exit here is one line in `tools/gates.py` away from becoming the
exact-equality gate that was considered and rejected. What it reports is
for a reader to act on, not for CI to enforce.

The measurement itself is imported from the test rather than repeated:
the gate is the authority on what "over the threshold" means, and two
copies of that ruff invocation would be free to disagree.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from docxkit.console import utf8_stdout  # noqa: E402


class Pin(Protocol):
    """The gate's `Pin` NamedTuple, structurally — it lives in the test
    module and is loaded by path, so it cannot be imported for typing."""

    @property
    def complexity(self) -> int: ...
    @property
    def measured(self) -> str: ...


def _gate() -> ModuleType:
    """The test module, loaded by path — `tests/` is not a package."""
    path = ROOT / "tests" / "test_complexity_debt.py"
    spec = importlib.util.spec_from_file_location("_complexity_debt", path)
    if spec is None or spec.loader is None:            # pragma: no cover
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(now: dict[str, int], debt: dict[str, Pin],
           today: str) -> list[str]:
    """One line per function, saying what moved and in which direction.

    SHRANK is the finding this tool exists for — it is the one state the
    gate cannot see, and the one that misleads a reader deciding whether
    a split is worth the afternoon.
    """
    lines = []
    for name in sorted(set(now) | set(debt)):
        pin = debt.get(name)
        measured = now.get(name)
        if pin is None:
            lines.append(f"  NEW      {name:<40} {measured}  "
                         f"(not pinned — add it, or split the function)")
        elif measured is None:
            lines.append(f"  PAID     {name:<40} {pin.complexity} -> under "
                         f"the threshold  (delete the pin)")
        elif measured > pin.complexity:
            lines.append(f"  GREW     {name:<40} {pin.complexity} -> "
                         f"{measured}  (pinned {pin.measured}; the gate "
                         f"is red on this)")
        elif measured < pin.complexity:
            lines.append(f"  SHRANK   {name:<40} {pin.complexity} -> "
                         f"{measured}  (pinned {pin.measured}; the pin "
                         f"OVERSTATES the job and nothing is red)")
        elif pin.measured == today:
            lines.append(f"  same     {name:<40} {measured}  "
                         f"(measured today)")
        else:
            lines.append(f"  same     {name:<40} {measured}  "
                         f"(pinned {pin.measured}, confirmed today)")
    return lines


def paste(now: dict[str, int], today: str) -> str:
    """The DEBT literal as it should read after this walk.

    Every date is today's, including the ones whose number did not move:
    the field records the day the walk was run, so an unchanged number
    re-measured today is a fresher fact than the same number pinned in
    the spring.
    """
    if not now:
        return "DEBT: dict[str, Pin] = {}"
    body = "".join(f'    "{name}": Pin({n}, "{today}"),\n'
                   for name, n in sorted(now.items()))
    return f"DEBT: dict[str, Pin] = {{\n{body}}}"


def main() -> int:
    utf8_stdout()
    gate = _gate()
    try:
        now = gate._over_threshold()
    except BaseException as exc:                        # pytest.skip.Exception
        if type(exc).__name__ != "Skipped":
            raise
        print(f"could not measure: {exc}")
        return 0

    debt = gate.DEBT
    today = dt.date.today().isoformat()

    print(f"C901 > {gate.MAX_COMPLEXITY}, package-wide, exemptions ignored "
          f"— measured {today}\n")
    if not now and not debt:
        print("  nothing over the threshold, and nothing pinned.\n")
        print("That is the strongest state this gate has: with DEBT empty "
              "the\nassertion reads \"no function in docxkit exceeds "
              f"{gate.MAX_COMPLEXITY}\".")
        return 0

    for line in report(now, debt, today):
        print(line)

    stale = [n for n, m in now.items()
             if n in debt and m < debt[n].complexity]
    print(f"\n{paste(now, today)}")
    if stale:
        print(f"\n{len(stale)} pin(s) overstate their function and no test "
              f"says so.\nPaste the block above into "
              f"tests/test_complexity_debt.py and move the\nsame numbers "
              f"and dates in pyproject.toml's C901 comment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
