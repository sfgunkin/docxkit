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
from typing import ClassVar

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

    def __init__(self, lines: list[str], log: list[tuple[str, str]],
                 env: dict[str, str] | None = None,
                 code: int = 0) -> None:
        self._lines, self._log = list(lines), log
        self.env = env or {}
        self.returncode = self._code = code

    @property
    def stdout(self):
        for line in self._lines:
            self._log.append(("emitted", line.strip()))
            yield line + "\n"

    def wait(self) -> int:
        self._log.append(("waited", ""))
        return self._code


@pytest.fixture
def sweep(monkeypatch):
    """Run `measure_all.run` over a fake session.

    Returns the log: ("emitted", line) for each line the child produced
    and ("printed", text) for each line the sweep wrote, in the order
    the two happened.
    """
    def go(lines: list[str], *, db: bool = False, tag: bool = False,
           code: int = 0) -> list[tuple[str, str]]:
        log: list[tuple[str, str]] = []
        monkeypatch.setattr(measure_all, "harness_for",
                            lambda module: ["tests/test_a.py"])
        monkeypatch.setattr(subprocess, "Popen",
                            lambda *a, **kw: _Child(lines, log,
                                                    kw.get("env"),
                                                    code))
        monkeypatch.setattr(measure_all.Path, "exists", lambda self: db)
        monkeypatch.setattr(
            measure_all, "print",
            lambda *a, **kw: log.append(("printed", " ".join(map(str, a)))),
            raising=False)
        measure_all.run("tracked.py", minutes=1, tag=tag)
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


def test_a_REFUSAL_is_printed_WHOLE_not_its_last_300_characters(sweep):
    """A traceback is the diagnosis. Six lines cut to their last 300
    characters reported a lost stream as `ath, target) | ... CopyFile2(...)`,
    the end of one call with nothing to say whose (BACKLOG S4). Every line
    kept is printed whole, and the last forty are kept."""
    lines = [f"frame {n:02d} " + "x" * 90 for n in range(45)]
    lines.append("FileNotFoundError: [WinError 3] " + "p" * 320)

    said = _said(sweep(lines))

    assert lines[-1] in said
    assert all(line in said for line in lines[6:-1])
    assert "frame 05" not in said


def test_a_graded_run_does_NOT_repeat_the_diagnosis_line(sweep):
    """The fallback is for the case with no progress at all. Printed
    beside a real chunk line it would put "verifying the unmutated
    harness..." under the final figure, where it reads as the state the
    run ended in."""
    said = _said(sweep(CHUNKS))

    assert "verifying the unmutated harness" not in said


def test_a_run_that_GRADED_and_then_refused_still_says_WHY(sweep):
    """The diagnosis above prints only when NO chunk graded, so a
    session that ran a while and then stopped reported a bare "REFUSED
    (exit 1)" with nothing to say what stopped it — `word.py` and
    `revision/_validate.py` both did, over two graded chunks each
    (2026-09-18). The successful run is the one that must stay quiet;
    a refusal is worth the same lines whether it arrives first or last,
    and it is the only place the reason is ever printed."""
    said = _said(sweep([*CHUNKS, "the worktree is gone"], code=1))

    assert "the worktree is gone" in said
    assert "REFUSED (exit 1)" in said
    assert said.index("the worktree is gone") < said.index("REFUSED")


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


# --- whose line is this? -------------------------------------------------


def test_a_TAGGED_line_names_its_own_module(sweep):
    """Under `--in` the streams interleave, so a heading from one lands
    between another's heading and its numbers. The first fan-out to
    finish printed `_cite_build`'s 8.9 % under `_table_core`'s heading,
    and the only thing that said which was which was the function names
    in the tally beneath it — a figure attributed to the wrong module is
    the one kind of wrong number this whole apparatus exists to avoid."""
    said = _said(sweep(CHUNKS, tag=True))

    assert said.startswith("### tracked.py"), "the heading is unchanged"
    for line in said.splitlines()[1:]:
        assert line.startswith("tracked.py "), line


def test_an_UNTAGGED_line_is_left_alone(sweep):
    """One sweep at a time is the ordinary case and there is nothing to
    disambiguate: the module is in the heading above."""
    said = _said(sweep(CHUNKS))

    assert "tracked.py     " not in said
    assert said.count("tracked.py") == 1


def test_the_streams_of_a_FAN_OUT_are_told_to_tag(monkeypatch):
    """The flag is not the caller's to remember. `--in` is the only way
    to produce interleaved output, so it is what turns tagging on."""
    launched: list[list[str]] = []

    class _Stream:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, cwd=None, env=None):
        launched.append(cmd)
        return _Stream()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    measure_all.fan_out(["D:/a"], ["one.py"], minutes=1, sample=0)

    assert "--tag" in launched[0], launched[0]


def test_the_SESSION_is_told_to_write_utf8(monkeypatch):
    """Its stdout is a pipe, so Python hands it the locale's cp1252
    unless told otherwise, and the em dash in "4/4 run — killed 4"
    arrives here as a byte this end cannot decode. The chunk line then
    matches nothing, a sweep that graded every mutant reports "no chunk
    ever graded", and the fallback dies printing the U+FFFD to the same
    cp1252 console. Both streams of the 2026-08-20 fan-out did.

    The launcher's own environment is not the fix: a sweep started from
    a shell that happens to export PYTHONIOENCODING worked, and the same
    command from a plain `nohup` did not."""
    seen: dict[str, str] = {}

    class _Quiet:
        stdout: ClassVar[list[str]] = []
        returncode = 0

        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kw):
        seen.update(kw.get("env") or {})
        return _Quiet()

    monkeypatch.setattr(measure_all, "harness_for",
                        lambda module: ["tests/test_a.py"])
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(measure_all.Path, "exists", lambda self: False)
    monkeypatch.setattr(measure_all, "print", lambda *a, **kw: None,
                        raising=False)

    measure_all.run("tracked.py", minutes=1)

    assert seen.get("PYTHONIOENCODING") == "utf-8", "the child chooses cp1252"


def test_a_fanned_out_STREAM_is_told_the_same(monkeypatch):
    """It runs this script again, which spawns sessions of its own: the
    variable has to reach the grandchildren."""
    envs: list[dict[str, str]] = []

    class _Stream:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, cwd=None, env=None):
        envs.append(dict(env or {}))
        return _Stream()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    measure_all.fan_out(["D:/a"], ["one.py"], minutes=1, sample=0)

    assert envs[0].get("PYTHONIOENCODING") == "utf-8"


def test_the_warning_that_the_TREE_MOVED_is_not_swallowed(sweep):
    """The session already refuses to measure an edit made while it
    ran: it works from a snapshot taken when the session was PLANNED,
    and says NOTE when the working tree no longer agrees with it.

    That line used to land in the same deque as the failure diagnosis,
    which is printed only when NO chunk graded — so a sweep whose module
    was edited mid-run printed a clean figure and swallowed the one
    sentence saying what the figure was of. 2026-08-20, by the person
    who wrote the rule against editing a module under measurement."""
    note = ("  NOTE: src/docxkit/_table_layout.py changed since this "
            "session was planned. The figure describes the tree as it "
            "was then — re-run with --fresh to measure it as it is now.")

    said = _said(sweep([CHUNKS[0], note, CHUNKS[1], note, CHUNKS[2]]))

    assert "changed since this session was planned" in said
    assert said.count("NOTE:") == 1, "once, not once per chunk"
    assert said.count("run —") == 2, "and the chunk lines still come"


def test_a_harness_that_moves_DURING_the_run_is_reported_at_the_end(
        sweep, monkeypatch, tmp_path):
    """The session checks the tree at the START of each chunk, so a run
    that fits in ONE chunk never re-checks — and an edit made while it
    ran goes unmentioned. `placement` did exactly that on 2026-08-20:
    one chunk, two tests added to its harness halfway through, and a
    figure that described neither tree.

    The fingerprint is taken again when the session exits."""
    seen: list[int] = []

    def fingerprint(module, tests):
        seen.append(1)
        return f"hash-{len(seen)}"      # a different tree every time

    monkeypatch.setattr(measure_all, "fingerprint", fingerprint)

    said = _said(sweep(CHUNKS))

    assert len(seen) == 2, "taken before the run and again after it"

    assert "changed while this ran" in said, said
    assert "as it was PLANNED" in said


def _refusing(monkeypatch, code, lines):
    """`run` over a session that exits `code` with its database still on
    disk. Separate from the `sweep` fixture because that one answers
    `Path.exists` True for everything, and `fingerprint` then opens a
    harness file that does not exist."""
    log: list[tuple[str, str]] = []
    monkeypatch.setattr(measure_all, "harness_for",
                        lambda module: ["tests/test_a.py"])
    monkeypatch.setattr(measure_all, "fingerprint",
                        lambda module, tests: "same")
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **kw: _Child(lines, log, kw.get("env"),
                                                code))
    monkeypatch.setattr(measure_all.Path, "exists", lambda self: True)
    monkeypatch.setattr(
        measure_all, "print",
        lambda *a, **kw: log.append(("printed", " ".join(map(str, a)))),
        raising=False)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _Finished("REAL SURVIVAL 6.9% (57/822)"))
    measure_all.run("tracked.py", minutes=1)
    return log


class _Finished:
    """A completed `mutation_survivors.py`."""

    def __init__(self, stdout: str) -> None:
        self.stdout, self.returncode, self.stderr = stdout, 0, ""


def test_a_session_that_REFUSED_is_not_reported_as_a_measurement(monkeypatch):
    """The guard against regressing a figure would have caused one.

    `mutation_session` refuses `--fresh --sample N` when the session it
    would discard graded more than N, and it returns BEFORE the unlink —
    so the old database is still on disk. The exit code was never read,
    so this function walked past the refusal into
    `mutation_survivors.py` and printed months-old numbers as this
    round's figure: the exact failure the guard was written to prevent,
    arriving from the other side.

    Eight of the fifty live sessions have graded more than the
    `--sample 460` CONTRIBUTING calls usual, so this is the ordinary path
    for the most-measured modules in the repo, not a corner of it.
    """
    log = _refusing(monkeypatch, 2,
                    ["refusing: --force to discard it anyway"])
    said = _said(log)

    assert "REFUSED (exit 2)" in said
    assert "no measurement taken" in said
    assert "REAL SURVIVAL" not in said, \
        "the old session must not be read back as this round's figure"


def test_a_session_that_SUCCEEDED_still_reports_as_before(monkeypatch):
    """The other half. Exit 0 with a database present is the ordinary
    completed run, and it has to reach the survivors report exactly as
    it did — a guard that also silenced the success path would be worse
    than the defect it fixes."""
    said = _said(_refusing(monkeypatch, 0, CHUNKS))

    assert "REFUSED" not in said
    assert "REAL SURVIVAL 6.9%  (57/822)" in said


# --- `--all` has to mean all of them -------------------------------------


def test_ALL_reaches_a_module_inside_a_SUBPACKAGE(tmp_path, monkeypatch):
    """`glob("*.py")` swept the top level and called it the package.

    `revision/` became a subpackage of fourteen halves on 2026-08-30,
    and `--all` would have reported a whole-package sweep without
    opening one of them — 3,118 lines of the protocol, silently outside
    the round. The name is kept RELATIVE to `src/docxkit`, because that
    is the spelling `harness_map` keys on and the one `run` puts back
    into a path.
    """
    src = tmp_path / "src" / "docxkit" / "revision"
    src.mkdir(parents=True)
    (src.parent / "__init__.py").write_text("x = 1")
    (src.parent / "edit.py").write_text("x = 1")
    (src / "__init__.py").write_text("x = 1")
    (src / "_build.py").write_text("x = 1")
    (src / "_losses.py").write_text("x = 1" * 40)        # the biggest

    monkeypatch.setattr(measure_all, "ROOT", tmp_path)
    asked: list[str] = []
    monkeypatch.setattr(measure_all, "run",
                        lambda m, *a, **k: asked.append(m))
    monkeypatch.setattr(sys, "argv", ["measure_all.py", "--all"])

    measure_all.main()

    assert "revision/_build.py" in asked
    assert "revision/_losses.py" in asked
    assert "edit.py" in asked
    assert not any(m.endswith("__init__.py") for m in asked), \
        "a facade has nothing to mutate"


def test_ALL_still_deals_the_SMALLEST_module_first(tmp_path, monkeypatch):
    """The order is a fan-out property: `--in` deals round-robin, and
    sorting largest-first would put every big module in the last
    stream. Adding the recursive walk must not disturb it."""
    src = tmp_path / "src" / "docxkit" / "revision"
    src.mkdir(parents=True)
    (src.parent / "big.py").write_text("x = 1" * 200)
    (src / "_small.py").write_text("x = 1")

    monkeypatch.setattr(measure_all, "ROOT", tmp_path)
    asked: list[str] = []
    monkeypatch.setattr(measure_all, "run",
                        lambda m, *a, **k: asked.append(m))
    monkeypatch.setattr(sys, "argv", ["measure_all.py", "--all"])

    measure_all.main()

    assert asked == ["revision/_small.py", "big.py"]


def test_a_sweep_runs_the_COVERING_tests_first(monkeypatch, tmp_path):
    """`--fast`, on the one caller that did not pass it.

    `mutant_tests` runs the tests covering the mutated line and falls
    through to the whole harness when none of them fails, so a survivor
    is never declared by the short run — it is declared by the same
    command the session would have used anyway. The verdict cannot
    move; only the wall clock can, and a sweep is where that is worth
    most: without it a 13-module round over an 8-file harness spends
    most of its time re-running tests that cannot reach the mutation.
    """
    seen: list[list[str]] = []

    class _Stream:
        stdout = iter(())

        def wait(self):
            return 0

    def fake_popen(cmd, **kw):
        seen.append(list(cmd))
        return _Stream()

    monkeypatch.setattr(measure_all, "ROOT", tmp_path)
    monkeypatch.setattr(measure_all, "harness_for", lambda m: ["tests/t.py"])
    monkeypatch.setattr(measure_all, "fingerprint", lambda m, t: "same")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    measure_all.run("revision/_losses.py", minutes=1)

    (cmd,) = seen
    assert "--fast" in cmd
    assert "--fresh" in cmd
    assert "src/docxkit/revision/_losses.py" in cmd
