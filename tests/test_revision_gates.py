"""`validate --run-gates` — the paper's own checks, when asked.

`[verify] commands` has always been a list the protocol RECORDS and does
not run, and the reasoning is sound: what a paper checks is the paper's
business, and a shared tool that runs per-project commands is a larger
promise than the protocol makes. It holds for the default. It does not
hold for the capability — with nine papers on the protocol, "listed, and
you run them yourself" means they run when someone remembers, which is
not what a gate is for.

So the boundary moved by exactly one flag, and these tests hold it
there: nothing runs without `--run-gates`, and what does run is the
author's own text, from the project root, bounded by a timeout, with a
failure that a script can tell apart from a bad redline.
"""
from __future__ import annotations

import sys
import threading
import time
import types

import pytest
from conftest import make_parts, para, run, write

from docxkit import revision
from docxkit.revision import run_gates

#: Forward slashes even on Windows: a `\\` in a TOML basic string is an
#: escape, and the first version of this helper wrote
#: `"C:\\Users\\...python.exe"` into paper.toml and could not parse it
#: back. Windows takes `/` in a path perfectly well.
_EXE = sys.executable.replace("\\", "/")


def _py(code: str) -> str:
    """A gate command that works wherever the suite does."""
    return f'"{_EXE}" -c "{code}"'


def paper_with(tmp_path, *commands):
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx", make_parts(para(run("The paper."))))
    paper = revision.init(root, src, name="P")
    # multi-line LITERAL strings: these commands carry both kinds
    # of quote, and every one would need escaping in a basic string
    listed = ",\n  ".join("'''" + c + "'''" for c in commands)
    config = paper.config.read_text(encoding="utf-8")
    paper.config.write_text(
        config.replace("commands = []", f"commands = [\n  {listed},\n]"),
        encoding="utf-8")
    return revision.load_paper(root)


# ----------------------------------------------------------- run_gates

def test_a_passing_gate_and_a_failing_one_are_told_apart(tmp_path):
    paper = paper_with(tmp_path,
                       _py("print('fine')"),
                       _py("import sys; sys.exit(3)"))

    good, bad = run_gates(paper)

    assert good.ok and good.verdict == "pass"
    assert not bad.ok and bad.code == 3 and bad.verdict == "FAIL (3)"


def test_the_gate_runs_from_the_PROJECT_ROOT(tmp_path):
    """A paper's gates are written relative to it — "pytest tests/",
    "python scripts/qa_links.py". Run from anywhere else they do not
    fail, they check nothing."""
    paper = paper_with(tmp_path, _py("import os; print(os.getcwd())"))

    (gate,) = run_gates(paper)

    assert gate.ok
    assert str(paper.root) in gate.output


def test_a_gate_that_HANGS_is_a_gate_that_fails(tmp_path):
    """This ladder runs before every hand-back. A gate with no timeout
    is one that can stop that happening at all.

    **Asserts the CLOCK, and that is the point of it.** The first
    version checked `code == -1` and nothing else, so it passed — in
    30.09 seconds — against an implementation whose timeout bounded
    nothing: `subprocess.run(shell=True, timeout=1)` on a 20-second
    sleep returned after 20.08s, because the kill reached cmd.exe and
    the surviving grandchild held the pipes open. A test that certifies
    a timeout has to fail when the timeout does not fire.
    """
    paper = paper_with(tmp_path, _py("import time; time.sleep(30)"))

    started = time.monotonic()
    (gate,) = run_gates(paper, timeout=1)
    elapsed = time.monotonic() - started

    assert gate.code == -1 and gate.verdict == "TIMED OUT"
    assert "within 1s" in gate.output
    assert elapsed < 15, (
        f"the gate slept 30s and the timeout was 1s; run_gates took "
        f"{elapsed:.1f}s, so it waited for the child rather than "
        f"killing it")
    assert gate.seconds < 15, "and the report agrees with the clock"


def test_a_timed_out_gate_leaves_NO_ORPHAN_behind(tmp_path):
    """`_kill_tree`, and the reason `proc.kill()` is not enough.

    Under a shell the gate is a GRANDCHILD, so killing the child ends
    cmd.exe and leaves the real work running — still holding the pipes,
    still writing files, invisible to the ladder that thinks it stopped
    it. The elapsed-time assertion above cannot see that: the parent
    stops waiting either way. Only the orphan's own side effect can,
    which is what this watches for. A mutant that downgraded the tree
    kill to `proc.kill()` survived every other test here.
    """
    marker = tmp_path / "the_orphan_was_here.txt"
    paper = paper_with(tmp_path, _py(
        f"import time; time.sleep(3); "
        f"open('{marker.as_posix()}','w').write('still running')"))

    (gate,) = run_gates(paper, timeout=1)
    assert gate.code == -1

    time.sleep(5)                     # past when the orphan would write
    assert not marker.exists(), (
        "the gate was killed but its grandchild kept running — "
        "`proc.kill()` reaches the shell, not the work")


def test_a_timed_out_gate_keeps_WHAT_IT_PRINTED(tmp_path):
    """The lines before the hang are the diagnosis. A pytest gate wedged
    on test 340 of 500 names that test; the first version replaced it
    with the literal string "no output within 1s"."""
    paper = paper_with(tmp_path, _py(
        "import sys, time; print('phase 1 ok'); sys.stdout.flush(); "
        "time.sleep(30)"))

    (gate,) = run_gates(paper, timeout=2)

    assert gate.code == -1
    assert "phase 1 ok" in gate.output, gate.output
    assert "no further output within 2s" in gate.output


def test_a_gate_whose_PROJECT_ROOT_is_gone_says_so(tmp_path, monkeypatch):
    """Not 127. "Command not found" sends the author hunting for a
    missing tool when the real problem is that the root moved or its
    drive is offline — and under a shell a missing cwd is the ONLY
    thing that raises OSError, so the old handler's comment described
    a case it never saw."""
    paper = paper_with(tmp_path, _py("print('never runs')"))
    from dataclasses import replace
    gone = replace(paper, root=tmp_path / "no_such_dir_xyz")

    (gate,) = run_gates(gone)

    assert not gate.ok and gate.code == 126
    assert "not a directory" in gate.output
    assert "moved" in gate.output or "offline" in gate.output


def test_a_command_that_does_not_EXIST_is_reported_not_raised(tmp_path):
    paper = paper_with(tmp_path, "definitely_not_a_command --flag")

    (gate,) = run_gates(paper)

    assert not gate.ok


def test_the_output_kept_is_the_TAIL(tmp_path):
    """Twenty lines: enough to act on, and not a build log pasted into
    the middle of a verdict."""
    paper = paper_with(
        tmp_path,
        _py("import sys; [print(i) for i in range(100)]; sys.exit(1)"))

    (gate,) = run_gates(paper)

    lines = gate.output.splitlines()
    assert len(lines) == 20
    assert lines[-1] == "99", gate.output


def test_a_paper_with_no_gates_runs_nothing(tmp_path):
    root = tmp_path / "P"
    root.mkdir()
    src = write(root / "P.docx", make_parts(para(run("The paper."))))
    paper = revision.init(root, src)

    assert list(run_gates(paper)) == []


def test_each_gate_is_REPORTED_before_the_next_one_starts(tmp_path):
    """Streaming, and the reason it matters: a caller printing results
    as they arrive is the only thing standing between the author and a
    silent terminal for the length of a pytest suite. The list version
    announced every gate up front and delivered every verdict at the
    end."""
    paper = paper_with(tmp_path,
                       _py("import time; time.sleep(0.6); print('one')"),
                       _py("print('two')"))
    seen: list[str] = []

    for gate in run_gates(paper, progress=seen.append):
        seen.append(f"result {gate.command[-12:]}")

    # announced, run, reported — then the NEXT one announced
    assert seen[0].startswith("gate: "), seen
    assert seen[1].startswith("result "), seen
    assert seen[2].startswith("gate: "), seen


def test_gates_run_in_the_ORDER_the_paper_lists_them(tmp_path):
    """A paper's list is a sequence — regenerate, then check — and
    running it out of order checks the wrong generation."""
    marks = tmp_path / "order.txt"
    paper = paper_with(
        tmp_path,
        _py(f"open('{marks.as_posix()}','a').write('first ')"),
        _py(f"open('{marks.as_posix()}','a').write('second')"))

    # `list(...)`, because run_gates STREAMS: discarding the iterator
    # runs nothing at all, which is how this test first failed.
    list(run_gates(paper))

    assert marks.read_text(encoding="utf-8") == "first second"


# ----------------------------------------------------------- the ladder

def _cli(monkeypatch, project, *args):
    from test_cli import run_cli
    return run_cli(monkeypatch, "revision", "validate", "--no-word",
                   "--paper", str(project.root), *args)


@pytest.fixture
def batch_ready(tmp_path):
    """A paper whose staged batch passes the ladder, with two gates."""
    marker = tmp_path / "ran.txt"
    paper = paper_with(
        tmp_path, _py(f"open('{marker.as_posix()}','w').write('yes')"))
    ins = ('<w:ins w:id="90" w:author="Revision" '
           f'w:date="2026-08-07T00:00:00Z">{run("and more")}</w:ins>')
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(para(run("The paper."), ins)))
    return paper, marker


def test_the_gates_are_NOT_run_without_the_flag(monkeypatch, batch_ready,
                                                capsys):
    """The default is the old promise, unchanged."""
    paper, marker = batch_ready

    _cli(monkeypatch, paper)
    out = capsys.readouterr().out

    assert not marker.exists(), "a gate ran without being asked"
    assert "NOT run (--run-gates)" in out
    assert "1 listed" in out


def test_the_flag_runs_them_and_says_so(monkeypatch, batch_ready, capsys):
    paper, marker = batch_ready

    code, _ = _cli(monkeypatch, paper, "--run-gates")
    out = capsys.readouterr().out

    assert marker.exists(), out
    assert "the paper's own gates" in out and "[pass]" in out
    assert code == 0, out


def test_a_failed_paper_gate_exits_5_not_1(monkeypatch, tmp_path, capsys):
    """"The redline is unshippable" and "the manuscript is wrong" want
    different responses, and a script that only knows non-zero cannot
    tell them apart."""
    paper = paper_with(tmp_path, _py("print('nope'); import sys; "
                                     "sys.exit(2)"))
    ins = ('<w:ins w:id="90" w:author="Revision" '
           f'w:date="2026-08-07T00:00:00Z">{run("and more")}</w:ins>')
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(para(run("The paper."), ins)))

    code, _ = _cli(monkeypatch, paper, "--run-gates")
    out = capsys.readouterr().out

    assert code == 5, out
    assert "nope" in out, "the failing gate's output was not shown"
    assert "1 of 1 of the paper's gates failed" in out


def test_a_BATCH_failure_still_outranks_a_passing_gate(monkeypatch,
                                                       tmp_path, capsys):
    """Exit 1 is about the redline and 5 is about the paper; when the
    redline is the problem, that is the answer a caller needs."""
    paper = paper_with(tmp_path, _py("print('fine')"))
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(para(run("nothing like the baseline"))))

    code, _ = _cli(monkeypatch, paper, "--run-gates")

    assert code == 1, capsys.readouterr().out


def test_an_ABORTED_ladder_says_the_gates_did_not_run(monkeypatch, tmp_path,
                                                      capsys):
    """Silence after the flag was passed reads as "they ran and were
    fine", which is the one thing it must not read as."""
    marker = tmp_path / "ran.txt"
    paper = paper_with(
        tmp_path, _py(f"open('{marker.as_posix()}','w').write('yes')"))
    # edge whitespace with no xml:space: the ladder aborts at lint
    bad = ('<w:p><w:r><w:t>a trailing space </w:t></w:r></w:p>')
    paper.batch.parent.mkdir(parents=True, exist_ok=True)
    write(paper.batch, make_parts(bad))

    code, _ = _cli(monkeypatch, paper, "--run-gates")
    out = capsys.readouterr().out

    assert code == 2, out
    assert not marker.exists(), "a gate ran on a batch that did not lint"
    assert "NOT run: the ladder aborted above" in out


# --- the Windows halves, on any platform --------------------------------
#
# `_kill_tree` and `_run_one` branch on `sys.platform`. The POSIX halves
# carry `pragma: no cover`; the Windows halves did not, so a Linux runner
# measured this module at 97.3 % against a floor set from a Windows run —
# the Coverage floors step, the fifth layer of the red CI of 2026-09-03,
# reached only once pytest itself was green there. Faking the platform
# and the module executes the Windows lines anywhere. A pragma would
# have done it in one line and hidden the `taskkill` argv — a constant
# that belongs to another program — from the mutation lists.


class _FakeProc:
    pid = 4242
    returncode = 0

    def __init__(self) -> None:
        self.stdout = iter(["hello\n"])
        self.killed = False

    def wait(self, timeout: float) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


class _FakeSubprocess:
    """Only what the two functions call."""

    PIPE, STDOUT = object(), object()
    CREATE_NEW_PROCESS_GROUP = 0x200

    class TimeoutExpired(Exception):
        pass

    def __init__(self) -> None:
        self.runs: list[list[str]] = []
        self.popen_kwargs: dict[str, object] = {}

    def run(self, argv, **_kw):
        self.runs.append(argv)
        return types.SimpleNamespace(returncode=0)

    def Popen(self, _command, **kw):
        self.popen_kwargs = kw
        return _FakeProc()


def test_kill_tree_on_WINDOWS_walks_the_tree_with_taskkill(monkeypatch):
    from docxkit.revision._gates import _kill_tree

    monkeypatch.setattr(sys, "platform", "win32")
    sub, proc = _FakeSubprocess(), _FakeProc()

    _kill_tree(proc, sub)

    assert sub.runs == [["taskkill", "/F", "/T", "/PID", "4242"]]
    assert proc.killed, "the shell itself is killed too, after the tree"


def test_run_one_on_WINDOWS_starts_the_gate_in_its_own_PROCESS_GROUP(
        monkeypatch, tmp_path):
    """`CREATE_NEW_PROCESS_GROUP` is what makes `taskkill /T` able to
    reach the grandchild; on POSIX the same job is `start_new_session`,
    and a Windows gate must not be started with that."""
    from docxkit.revision._gates import _run_one

    monkeypatch.setattr(sys, "platform", "win32")
    sub = _FakeSubprocess()

    code, out = _run_one("echo hi", tmp_path, 5, sub, threading)

    assert (code, out) == (0, "hello\n")
    assert sub.popen_kwargs["creationflags"] == sub.CREATE_NEW_PROCESS_GROUP
    assert "start_new_session" not in sub.popen_kwargs


# --- the platform branches OFF Windows, the clock, and the defaults --------
#
# The survivors of the 2026-09-14 replay: ten mutants alive against the
# tests above. The fakes above held the Windows half of each branch and
# nothing held the other; nothing read `seconds` against a clock it
# controlled, or asked what a caller naming no timeout gets.


class _FakeThreading:
    """A reader that drains when started and records what each `join`
    was allowed."""

    def __init__(self) -> None:
        self.joins: list[float | None] = []

    def Thread(self, target, daemon):
        joins = self.joins

        class _Reader:
            def start(self) -> None:
                target()

            def join(self, timeout: float | None = None) -> None:
                joins.append(timeout)

        return _Reader()


class _HungProc(_FakeProc):
    def wait(self, timeout: float) -> int:
        raise _FakeSubprocess.TimeoutExpired


class _HungSubprocess(_FakeSubprocess):
    def Popen(self, _command, **kw):
        self.popen_kwargs = kw
        return _HungProc()


def test_a_caller_naming_NO_TIMEOUT_gets_the_CLI_s_fifteen_minutes(
        monkeypatch, tmp_path):
    """`--gate-timeout` documents "default 900", and a paper's script
    calling `run_gates` without the CLI gets the same bound."""
    from docxkit.revision import _gates

    given: list[float] = []

    def run_one(command, cwd, timeout, subprocess, threading):
        given.append(timeout)
        return 0, "ok"

    monkeypatch.setattr(_gates, "_run_one", run_one)

    list(run_gates(paper_with(tmp_path, "echo hi")))

    assert given == [900]


def test_SECONDS_are_the_difference_of_two_clock_readings(monkeypatch,
                                                          tmp_path):
    """`time.monotonic` has no defined zero, and a real one has been
    counting since boot: against it `now / started` is 1.0 to a decimal
    for any gate shorter than the uptime, which reads as a plausible
    second. `run_gates` imports `time` when it is called, so the clock
    is handed over through `sys.modules`."""
    from docxkit.revision import _gates

    monkeypatch.setattr(_gates, "_run_one", lambda *_a: (0, "ok"))
    paper = paper_with(tmp_path, "echo hi")
    ticks = iter([2.0, 5.0])
    monkeypatch.setitem(sys.modules, "time", types.SimpleNamespace(
        monotonic=lambda: next(ticks)))

    (gate,) = run_gates(paper)

    assert gate.seconds == 3.0


def test_kill_tree_off_WINDOWS_kills_the_SESSION_and_never_runs_taskkill(
        monkeypatch):
    """`os.killpg` is faked as well as the platform: CI's runner IS a
    POSIX box, and a real `killpg` on the group of pid 4242 would kill
    whatever holds it. `taskkill` does not exist there; asked for, it
    fails quietly inside the suppress and the grandchild lives on."""
    import os
    import signal

    from docxkit.revision._gates import _kill_tree

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "getpgid", lambda pid: pid + 1, raising=False)
    monkeypatch.setattr(os, "killpg",
                        lambda pgid, sig: killed.append((pgid, sig)),
                        raising=False)
    monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
    sub, proc = _FakeSubprocess(), _FakeProc()

    _kill_tree(proc, sub)

    assert sub.runs == [], "taskkill is a Windows program"
    assert killed == [(4243, 9)], "the group of the session it started"
    assert proc.killed


@pytest.mark.parametrize("platform", ["linux", "darwin", "x-after-win32"])
def test_run_one_off_WINDOWS_starts_the_gate_in_a_NEW_SESSION(
        monkeypatch, tmp_path, platform):
    """The session is what `_kill_tree` kills by off Windows: without
    it the gate shares the caller's group, and `killpg` ends the caller.

    The third name is no platform's. None that CPython runs on sorts
    after "win32", so no real name tells this equality from `>=`, and
    the line is written twice in the module, so the equivalence cannot
    be argued in `equivalents.toml`, which anchors a claim at exactly
    one line."""
    from docxkit.revision._gates import _run_one

    monkeypatch.setattr(sys, "platform", platform)
    sub = _FakeSubprocess()

    assert _run_one("echo hi", tmp_path, 5, sub, threading) == (0, "hello\n")
    assert sub.popen_kwargs["start_new_session"] is True
    assert "creationflags" not in sub.popen_kwargs


def test_the_platform_is_compared_by_VALUE_not_by_identity(monkeypatch,
                                                           tmp_path):
    """`sys.platform` is built when the interpreter starts, and it is not
    the object a "win32" literal in this module is: `sys.platform is
    "win32"` is False on this machine. The fake above IS that object,
    interned, which is why `is` passed it. Built at run time here, as
    the real one is."""
    from docxkit.revision._gates import _run_one

    monkeypatch.setattr(sys, "platform", "win" + str(32))
    sub = _FakeSubprocess()

    _run_one("echo hi", tmp_path, 5, sub, threading)

    assert sub.popen_kwargs["creationflags"] == sub.CREATE_NEW_PROCESS_GROUP


def test_the_reader_is_given_FIVE_seconds_on_BOTH_paths(monkeypatch,
                                                        tmp_path):
    """A gate that exits can leave a grandchild holding its pipe, and one
    that timed out can leave a grandchild `taskkill` missed. Either way
    the reader gets five seconds and no more. Pinned rather than argued
    because the line is written twice."""
    from docxkit.revision._gates import _run_one

    monkeypatch.setattr(sys, "platform", "win32")
    reader = _FakeThreading()

    _run_one("echo hi", tmp_path, 5, _FakeSubprocess(), reader)
    code, _out = _run_one("sleep", tmp_path, 1, _HungSubprocess(), reader)

    assert code == -1
    assert reader.joins == [5, 5]


# --- the verdict is the REPORT's -------------------------------------
#
# The exit codes above were a chain of returns in `cli.cmd_revision_
# validate` and `cli._paper_gates` until 2026-09-11, testable only
# through `argv`. They are `ValidateReport.exit_code` now, and the CLI
# prints. These pin the numbers where they live; the `_cli` tests above
# still pin that the command hands them on unchanged.

def _report(**fields):
    from pathlib import Path
    return revision.ValidateReport(path=Path("batch.docx"), baseline=None,
                                   **fields)


def _gate(code: int) -> revision.GateResult:
    return revision.GateResult(command="x", code=code, seconds=0.1,
                               output="nope" if code else "")


def test_a_clean_ladder_with_no_gates_run_is_0():
    report = _report()
    assert report.aborted == "" and report.ok
    assert report.exit_code == 0


def test_a_ladder_that_said_no_is_1():
    report = _report(reject_matches_baseline=False)
    assert report.exit_code == 1 and not report.ok
    assert report.aborted == "", "a failed gate is not an abort"


def test_the_two_aborts_before_word_are_2_and_say_WHICH():
    assert _report(built_on_this_baseline=False).aborted == "baseline"
    assert _report(built_on_this_baseline=False).exit_code == 2
    assert _report(lint=["orphan bookmark 3"]).aborted == "lint"
    assert _report(lint=["orphan bookmark 3"]).exit_code == 2


def test_a_batch_word_cannot_open_is_3():
    report = _report(word_opened=False, word_error="corrupted")
    assert report.aborted == "word"
    assert report.exit_code == 3


def test_a_failed_PAPER_gate_is_5_only_when_the_ladder_passed():
    """"The redline is unshippable" and "the manuscript is wrong" want
    different responses; when the redline is the problem, that is the
    answer — a ladder failure outranks a gate failure."""
    report = _report(gates=[_gate(0), _gate(2)])
    assert report.exit_code == 5 and not report.ok

    report = _report(reject_matches_baseline=False, gates=[_gate(2)])
    assert report.exit_code == 1

    report = _report(gates=[_gate(0), _gate(0)])
    assert report.exit_code == 0 and report.ok


def test_the_abort_outranks_everything_beneath_it():
    """Nothing below the stop ran, so a report that also carries a
    reject-all mismatch is still an abort — and still 2, not 1."""
    report = _report(lint=["bad"], reject_matches_baseline=False,
                     gates=[_gate(2)])
    assert report.exit_code == 2
