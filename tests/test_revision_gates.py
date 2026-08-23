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
    """This ladder is meant to run before every hand-back. A gate with
    no timeout is one that can stop it happening at all."""
    paper = paper_with(tmp_path, _py("import time; time.sleep(30)"))

    (gate,) = run_gates(paper, timeout=1)

    assert gate.code == -1 and gate.verdict == "TIMED OUT"
    assert "within 1s" in gate.output


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

    assert run_gates(paper) == []


def test_gates_run_in_the_ORDER_the_paper_lists_them(tmp_path):
    """A paper's list is a sequence — regenerate, then check — and
    running it out of order checks the wrong generation."""
    marks = tmp_path / "order.txt"
    paper = paper_with(
        tmp_path,
        _py(f"open('{marks.as_posix()}','a').write('first ')"),
        _py(f"open('{marks.as_posix()}','a').write('second')"))

    run_gates(paper)

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
