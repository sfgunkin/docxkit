#!/usr/bin/env python
"""Run the five gates in order and say which one stopped.

    python tools/gates.py

CI runs them on 3.12, 3.13 and 3.14 with every step reporting
independently. Locally they are a chain, and the chain is where they go
wrong:

* `pyright | tail -1` returns TAIL's status, so a type error read as a
  pass. Written up in CONTRIBUTING, and then done again on 2026-08-20 as
  `pytest -q | tail -2`, which put a red suite into master;
* `;` instead of `&&` runs every gate whatever the last one said, and
  has shipped a lint failure twice;
* `mypy`'s exit code is not usable here — it is non-zero for a run that
  found nothing but notes — so the gate is "no line matching `: error`",
  which is what this applies.

Nothing here is new: it is the same five commands CONTRIBUTING lists,
run so that the answer cannot be lost between them. Exit status is 0
only when all five pass, and the first failure stops the run — a gate
after a red one tells you nothing you can act on yet.
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]

#: (name, argv, reads-stdout). The third says the gate is judged by its
#: OUTPUT rather than its exit code — `mypy` is the only one.
Gate = tuple[str, list[str], bool]

GATES: list[Gate] = [
    ("ruff", [sys.executable, "-m", "ruff", "check", "."], False),
    ("mypy", [sys.executable, "-m", "mypy"], True),
    ("pyright", [sys.executable, "-m", "pyright"], False),
    ("pytest", [sys.executable, "-m", "pytest", "-q"], False),
    ("floors", [sys.executable, "tools/coverage_floor.py"], False),
]


def _failed(gate: Gate, out: str, code: int) -> bool:
    """Did this gate fail? `mypy` is judged on its lines, not its code."""
    if gate[2]:
        return any(": error" in line for line in out.splitlines())
    return code != 0


def run(gates: Sequence[Gate] = tuple(GATES),
        say: Callable[[str], None] = print) -> int:
    """Run each gate until one fails; return the number that failed."""
    for gate in gates:
        name, argv, _reads = gate
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
        out = done.stdout + done.stderr
        if _failed(gate, out, done.returncode):
            say(f"FAILED  {name}")
            say(out.strip()[-3000:])
            return 1
        tail = [ln for ln in out.strip().splitlines() if ln.strip()]
        say(f"ok      {name}  {tail[-1][:90] if tail else ''}")
    return 0


if __name__ == "__main__":                  # pragma: no cover
    # A gate's output is full of what this package works on — em dashes,
    # Cyrillic captions, the U+FFFD a decode left behind — and a
    # console that is cp1252 dies printing it. The first failure this
    # runner ever reported crashed here instead of showing itself, and
    # the pipe it was invoked through swallowed the crash as well.
    utf8_stdout()
    raise SystemExit(run())
