"""`tools/kill_check.py` — the cases it must refuse to run.

The tool applies one mutation and reports whether the suite noticed. Two
of its answers are worthless unless it can tell them from a mistake in
the case itself:

* a mutation that does not COMPILE makes pytest exit non-zero on the
  import, which reads exactly like a test failure — a confident false
  KILL, and the docstring says one hid dead code for an afternoon;
* a mutation that changes NOTHING leaves the file as it was, so the
  suite passes and the case reports SURVIVED — a confident false
  SURVIVOR, which sends someone off to write a test that already
  exists. This happened twice on 2026-08-19, both times to a case built
  with `old.replace(...)` whose inner pattern did not match: the source
  reads `len(stack) - 1, -1, -1)` with a space after the minus, and the
  pattern was written without one.

Both are checked here on a scratch module, because a tool that reports
the wrong thing about the tests is worse than no tool.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"

_DRIVER = '''
import sys
sys.path.insert(0, {tools!r})
from kill_check import check
print("BAD", check({module!r}, {tests!r}, {cases!r}))
'''


def _run(tmp_path: Path, module: str, tests: list[str],
         cases: list[tuple[str, str, str, bool]]) -> str:
    """Drive `check` in a subprocess, the way a scratch script does."""
    script = tmp_path / "drive.py"
    script.write_text(_DRIVER.format(tools=str(TOOLS), module=module,
                                     tests=tests, cases=cases),
                      encoding="utf-8")
    done = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=TOOLS.parent, check=False)
    return done.stdout + done.stderr


def test_a_case_that_changes_NOTHING_is_refused(tmp_path):
    """The one that cost an hour: `old` and `new` identical, because the
    pattern the case meant to replace was not in the anchor."""
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("a no-op case", "def utf8_stdout", "def utf8_stdout", True)])

    assert "changes nothing" in out
    assert "SURVIVED" not in out
    assert "BAD 1" in out, "a refused case counts against the run"


def test_a_case_whose_anchor_is_AMBIGUOUS_is_refused(tmp_path):
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("an ambiguous case", "    return", "    pass", True)])

    assert "anchor occurs" in out
    assert "SURVIVED" not in out


def test_a_case_that_does_not_COMPILE_is_refused(tmp_path):
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("a broken case", "def utf8_stdout",
                 "def utf8_stdout(((", True)])

    assert "does not compile" in out
    assert "killed" not in out


_SYNC = '''
import sys
sys.path.insert(0, {tools!r})
import kill_check
kill_check.sync()
live, root = kill_check.LIVE, kill_check.ROOT
for name in sorted(p.name for p in (live / "tools").glob("*.py")):
    a = (live / "tools" / name).read_bytes()
    b = (root / "tools" / name).read_bytes() \
        if (root / "tools" / name).exists() else b""
    print(("SAME" if a == b else "STALE") + " " + name)
'''


def test_the_checkout_holds_TODAYS_tools_scripts(tmp_path):
    """A case can be aimed at a `tools/` script — the sweep tools have
    harnesses of their own — and the checkout is created once, detached,
    and reused for weeks. Copying only `src/` and `tests/` into it left
    every tools script at the commit the worktree was made from, so a
    case anchored on a line added since was refused with "anchor occurs
    0 times" for a line that is in the file. Refused, not answered
    wrongly — but the reason is invisible from the message."""
    script = tmp_path / "sync.py"
    script.write_text(_SYNC.format(tools=str(TOOLS)), encoding="utf-8")

    done = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=TOOLS.parent, check=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STALE" not in done.stdout, done.stdout
    assert "SAME kill_check.py" in done.stdout, done.stdout
