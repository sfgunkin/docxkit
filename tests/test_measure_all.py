"""`tools/measure_all.py` — a sweep you can watch while it runs.

The sessions it drives are half an hour each and print one line per
chunk, flushed on purpose: `mutation_session` says in a comment that
block-buffered output makes an hour-long run look like a hung one. This
script then captured all of it and printed the last line when the child
exited, which put the silence back — a three-module sweep said nothing
for its first thirty-five minutes.

So the chunk lines are streamed through, and these tests hold the
INTERLEAVING rather than the plumbing: every print is recorded in the
same list as every line the child emitted, so "collect it all, then
print" fails here exactly like the version this replaced.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed: the path insert above
# is how its scripts reach each other, and how they are reached here.
import measure_all  # noqa: E402  # pyright: ignore[reportMissingImports]

CHUNKS = ["  verifying the unmutated harness (3 files)...",
          "  40/589 run — killed 38, survived 2 (5.0% survive)",
          "  589/589 run — killed 560, survived 29 (4.9% survive)"]


class _Child:
    """A session that emits its chunk lines one at a time."""

    def __init__(self, lines: list[str], log: list[tuple[str, str]]) -> None:
        self._lines, self._log = list(lines), log
        self.returncode = 0

    @property
    def stdout(self):
        for line in self._lines:
            self._log.append(("emitted", line.strip()))
            yield line + "\n"

    def wait(self) -> int:
        self._log.append(("waited", ""))
        return 0


@pytest.fixture
def sweep(monkeypatch):
    """Run `measure_all.run` over a fake session.

    Returns the log: ("emitted", line) for each line the child produced
    and ("printed", text) for each line the sweep wrote, in the order
    the two happened.
    """
    def go(lines: list[str], *, db: bool = False) -> list[tuple[str, str]]:
        log: list[tuple[str, str]] = []
        monkeypatch.setattr(measure_all, "harness_for",
                            lambda module: ["tests/test_a.py"])
        monkeypatch.setattr(subprocess, "Popen",
                            lambda *a, **kw: _Child(lines, log))
        monkeypatch.setattr(measure_all.Path, "exists", lambda self: db)
        monkeypatch.setattr(
            measure_all, "print",
            lambda *a, **kw: log.append(("printed", " ".join(map(str, a)))),
            raising=False)
        measure_all.run("tracked.py", minutes=1)
        return log
    return go


def _said(log: list[tuple[str, str]]) -> str:
    return "\n".join(text for kind, text in log if kind == "printed")


def test_each_chunk_is_printed_as_it_ARRIVES(sweep):
    """Not at the end. Both chunk lines are printed BEFORE the line
    after them is emitted, which is what a person watching a
    backgrounded sweep is actually asking for."""
    log = sweep(CHUNKS)

    kinds = [k for k, _ in log]
    first_chunk = next(i for i, (k, t) in enumerate(log)
                       if k == "emitted" and "40/589" in t)
    last_chunk = next(i for i, (k, t) in enumerate(log)
                      if k == "emitted" and "589/589" in t)
    assert any(k == "printed" and "40/589" in t
               for k, t in log[first_chunk:last_chunk]), log
    assert kinds.index("waited") > last_chunk
    assert _said(log).count("run —") == 2


def test_the_line_that_is_not_progress_is_kept_for_the_FAILURE_case(sweep):
    """A session that graded nothing has no chunk line at all — a lock
    it could not take, a harness that does not import, a worktree that
    is gone. Printing "0%" there would be a measurement; printing what
    the child said is a diagnosis."""
    said = _said(sweep(["  taking over a stale lock on D:/mut2 — pid 4",
                        "ERROR: the harness did not import"]))

    assert "the harness did not import" in said
    assert "run —" not in said


def test_a_session_that_says_NOTHING_still_reports(sweep):
    """`or "no output"`. The child can die before its first print, and
    an empty line under a module heading reads as a module with no
    mutants rather than as a run that never started."""
    assert "no output" in _said(sweep([]))


def test_a_graded_run_does_NOT_repeat_the_diagnosis_line(sweep):
    """The fallback is for the case with no progress at all. Printed
    beside a real chunk line it would put "verifying the unmutated
    harness..." under the final figure, where it reads as the state the
    run ended in."""
    said = _said(sweep(CHUNKS))

    assert "verifying the unmutated harness" not in said


def test_the_module_HEADING_names_the_harness_it_was_measured_against(sweep):
    """Every figure is a statement about a module AND a set of test
    files — the reason `stale_figures` exists. The count is what a
    reader compares against the map when the number looks wrong."""
    assert _said(sweep(CHUNKS)).startswith("### tracked.py  (1 test file(s))")


# --- one stream per checkout --------------------------------------------


def test_the_modules_are_DEALT_across_the_checkouts_not_blocked(monkeypatch):
    """Round-robin, because the module list is sorted smallest-first:
    dealt in blocks, every big module lands in the last stream and the
    others finish in minutes while it runs for hours.

    Each stream is this same script with `DOCXKIT_MUT_WORKTREE` set —
    restartable and locked like any other sweep — so the fan-out is a
    scheduling decision and nothing more."""
    launched: list[tuple[list[str], str]] = []

    class _Stream:
        def wait(self):
            return 0

    def fake_popen(cmd, cwd=None, env=None):
        assert env is not None
        mods = [a for a in cmd[2:] if a.endswith(".py")]
        launched.append((mods, env["DOCXKIT_MUT_WORKTREE"]))
        return _Stream()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    code = measure_all.fan_out(["D:/a", "D:/b"],
                               ["one.py", "two.py", "three.py", "four.py"],
                               minutes=1, sample=0)

    assert code == 0
    assert launched[0] == (["one.py", "three.py"], "D:/a")
    assert launched[1] == (["two.py", "four.py"], "D:/b")


def test_a_checkout_with_NOTHING_to_do_starts_no_stream(monkeypatch):
    """Three checkouts and two modules: the third would run a sweep over
    an empty list, which takes a lock and a worktree for nothing."""
    launched: list[dict[str, str]] = []

    class _Stream:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, cwd=None, env=None):
        assert env is not None
        launched.append(dict(env))
        return _Stream()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    measure_all.fan_out(["D:/a", "D:/b", "D:/c"], ["one.py", "two.py"],
                        minutes=1, sample=0)

    assert len(launched) == 2


def test_the_worst_exit_code_of_the_streams_is_the_answer(monkeypatch):
    """A sweep that failed in one checkout must not be reported as a
    clean run because the other finished."""
    codes = iter([0, 3])

    class _Stream:
        def __init__(self) -> None:
            self._code = next(codes)

        def wait(self) -> int:
            return self._code

    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, cwd=None, env=None: _Stream())

    assert measure_all.fan_out(["D:/a", "D:/b"], ["one.py", "two.py"],
                               minutes=1, sample=0) == 3
