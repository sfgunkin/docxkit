"""`tools/can_it_fail.py` — break the thing, and see if the test notices.

The tool exists because this session needed the answer five times in a
day and each time it was a hand-made experiment. What it automates is
the only proof that settles "this test cannot fail": run the test, break
what it checks, run it again, put the file back.

The end-to-end cases build a throwaway git repo, because the revert is
`git checkout` and a tool that restores a file has to be watched doing
it on a real one.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

ROOT = Path(docxkit.__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "can_it_fail.py"


def _module():
    spec = importlib.util.spec_from_file_location("can_it_fail", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CAN_IT_FAIL = _module()

RULE = "PART = 'word/document.xml'\n"
TEST = ("from pathlib import Path\n\n\n"
        "def test_no_footnotes_part():\n"
        "    text = Path(__file__).with_name('rule.py').read_text()\n"
        "    assert 'word/footnotes.xml' not in text\n")


@pytest.fixture
def repo(tmp_path):
    """A one-rule, one-test repository with everything committed."""
    (tmp_path / "rule.py").write_text(RULE, encoding="utf-8")
    (tmp_path / "elsewhere.py").write_text("OTHER = 1\n", encoding="utf-8")
    (tmp_path / "test_rule.py").write_text(TEST, encoding="utf-8")
    for argv in (["init", "-q"],
                 ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "Tester"],
                 ["add", "-A"],
                 ["commit", "-qm", "the rule and its test"]):
        subprocess.run(["git", *argv], cwd=tmp_path, check=True,
                       capture_output=True)
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "test_rule.py::test_no_footnotes_part",
         *args],
        cwd=repo, capture_output=True, text=True, check=False)


# --------------------------------------------------------- the verdicts


def test_a_test_that_NOTICES_the_break_reports_that_it_can_fail(repo):
    """The healthy answer, and exit 0. The break is in the file the rule
    reads, so the rule has something to object to."""
    done = _run(repo, "--in", "rule.py",
                "--replace", "word/document.xml",
                "--with", "word/footnotes.xml")

    assert "can fail" in done.stdout, done.stdout
    assert done.returncode == 0
    assert (repo / "rule.py").read_text(encoding="utf-8") == RULE, (
        "and the file is back, which is the half a person has to trust")


def test_a_test_that_SLEEPS_through_it_is_the_finding(repo):
    """The shape this tool is for: the break lands somewhere the test
    never reads — a module outside its glob, a line above its slice —
    and the suite stays green. Exit 1, because it is a finding."""
    done = _run(repo, "--in", "elsewhere.py",
                "--replace", "OTHER = 1",
                "--with", "OTHER = 'word/footnotes.xml'")

    assert "CANNOT FAIL" in done.stdout, done.stdout
    assert done.returncode == 1
    assert (repo / "elsewhere.py").read_text(encoding="utf-8") == "OTHER = 1\n"


def test_a_test_that_is_ALREADY_RED_answers_nothing(repo):
    """The third state, and it has to be its own: a test that was
    failing before the break tells you nothing about the break, and
    "red after" would read as a pass."""
    (repo / "rule.py").write_text("PART = 'word/footnotes.xml'\n",
                                  encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "already broken"], cwd=repo,
                   check=True, capture_output=True)

    done = _run(repo, "--in", "rule.py",
                "--replace", "word/footnotes.xml", "--with", "word/x.xml")

    assert done.returncode == 2
    assert "already" in done.stdout.lower() + done.stderr.lower()


# --------------------------------------------------------- the refusals


def test_it_REFUSES_a_file_with_uncommitted_work_in_it(repo):
    """The revert is `git checkout`, so running this over an edited file
    would discard it. The refusal names that, because the tool is
    reached for in the middle of exactly that kind of afternoon."""
    (repo / "rule.py").write_text(RULE + "# a line I have not saved\n",
                                  encoding="utf-8")

    done = _run(repo, "--in", "rule.py",
                "--replace", "word/document.xml", "--with", "word/x.xml")

    assert done.returncode == 2
    assert "git checkout" in done.stdout + done.stderr
    assert "not saved" in (repo / "rule.py").read_text(encoding="utf-8"), (
        "and it did not touch the file it refused over")


def test_an_ANCHOR_that_is_not_there_is_a_refusal_not_a_verdict(repo):
    """A break that did not apply is not a test that cannot fail, and
    the two must never print the same thing."""
    done = _run(repo, "--in", "rule.py",
                "--replace", "not in this file", "--with", "x")

    assert done.returncode == 2
    assert "CANNOT FAIL" not in done.stdout


# ------------------------------------------------------- the pure parts


def test_the_break_is_applied_ONCE_and_at_the_first_occurrence():
    """One occurrence, because a break has to be a change a person can
    read back in the diff — and because the second occurrence is often
    in a comment about the first."""
    out = CAN_IT_FAIL.apply_break("a = 1\nb = 1\n", "1", "2")

    assert out == "a = 2\nb = 1\n"


def test_an_absent_anchor_is_None_rather_than_an_unchanged_FILE():
    """Returning the text unchanged would write the file back as it was
    and report a verdict on a break that never happened."""
    assert CAN_IT_FAIL.apply_break("a = 1\n", "zzz", "y") is None


@pytest.mark.parametrize("before,after,expected", [
    (True, False, "can fail"),
    (True, True, "CANNOT FAIL"),
    (False, False, "already red"),
    (False, True, "already red"),
])
def test_the_verdict_reads_off_the_two_runs(before, after, expected):
    assert CAN_IT_FAIL.verdict(before, after).startswith(expected)
