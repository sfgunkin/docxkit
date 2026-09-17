"""`tools/unrun_assertions.py` — the gate that reads the test files.

Its whole subject is the difference between "nothing is wrong" and
"nothing was checked", so the cases here are the three answers it has to
keep apart: a test that ran and did not assert, a test the run never
entered, and a test that stood down in the open.

The reports are synthetic. A coverage JSON is two lists of line numbers
per file, and building them by hand is what lets a case say exactly
which line ran — which is the thing under test.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import docxkit

ROOT = Path(docxkit.__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "unrun_assertions.py"


def _module():
    """The tool, loaded by path — `tools/` is not a package.

    Registered in `sys.modules` before it is executed, because
    `@dataclass` looks its own module up there to resolve annotations:
    without the line the class raises at import and the whole file fails
    at collection.
    """
    spec = importlib.util.spec_from_file_location("unrun_assertions", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


UNRUN = _module()

SOURCE = '''\
def test_the_loop_had_nothing_in_it():
    """One that ran."""
    found = []
    for item in found:
        assert item, "never reached"


def test_the_run_never_entered_this_one():
    marks = ["a"]
    assert marks


def test_this_one_stands_down():
    import pytest

    if not []:
        pytest.skip("nothing to check today")
    assert False, "below the skip"
'''

#: line numbers in SOURCE, so a case can say what ran
RAN_LOOP, ASSERT_IN_LOOP = 3, 5
ENTERED_SECOND, ASSERT_SECOND = 8, 9
ENTERED_THIRD, ASSERT_THIRD = 14, 19


@pytest.fixture
def tree(tmp_path):
    """A test file on disk, and a report builder for it."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(SOURCE,
                                                       encoding="utf-8")

    def report(executed: list[int], missing: list[int]) -> dict[str, object]:
        return {"files": {"tests/test_sample.py": {
            "executed_lines": executed, "missing_lines": missing}}}

    return tmp_path, report


def test_an_unrun_assertion_in_a_test_that_RAN_is_a_finding(tree):
    """The whole point: the test passed, and the assertion inside its
    loop was never made."""
    root, report = tree

    (found,) = UNRUN.findings(report([RAN_LOOP, RAN_LOOP + 1],
                                     [ASSERT_IN_LOOP]), root)

    assert found.test == "test_the_loop_had_nothing_in_it"
    assert found.line == ASSERT_IN_LOOP
    assert "never reached" in found.source
    assert found.file == "tests/test_sample.py"


def test_a_test_the_run_NEVER_ENTERED_is_not_a_finding(tree):
    """Deselected, skipped, or a parametrize with no cases: the run
    summary says so already, and this reads it off the report rather
    than off markers — a test that ran has its first statement
    covered."""
    root, report = tree

    assert UNRUN.findings(report([], [ENTERED_SECOND, ASSERT_SECOND]),
                          root) == []


def test_a_test_that_SKIPS_ITSELF_is_not_a_finding(tree):
    """`pytest.skip` in the body is standing down in the open, which is
    what the empty-`DEBT` tests were changed to. Its first lines RUN, so
    the entered check cannot cover this case and the tool looks for the
    call."""
    root, report = tree

    assert UNRUN.findings(report([ENTERED_THIRD], [ASSERT_THIRD]), root) == []


def test_the_allowlist_is_keyed_by_TEST_and_not_by_LINE(tree, monkeypatch):
    """A line number is moved by the next edit above it, and an
    allowlist that stops matching goes quietly back to failing. The key
    is the file and the test name, as `tools/equivalents.toml` keys its
    claims on the line TEXT for the same reason."""
    root, report = tree
    (found,) = UNRUN.findings(report([RAN_LOOP], [ASSERT_IN_LOOP]), root)

    assert found.key == "test_sample.py::test_the_loop_had_nothing_in_it"


def test_a_report_with_NO_test_files_refuses_instead_of_passing(tmp_path,
                                                                capsys):
    """The failure it exists to catch, one level up: without
    `--cov=tests` every assertion is unseen, and "0 findings" would be
    the same line as a clean tree. Exit 3, the state `sweep` uses."""
    path = tmp_path / "cov.json"
    path.write_text(json.dumps({"files": {"src/docxkit/cli.py": {
        "executed_lines": [1], "missing_lines": []}}}), encoding="utf-8")

    code = UNRUN.main(["--from-json", str(path)])

    assert code == 3
    assert "--cov=tests" in capsys.readouterr().out


def test_every_ALLOWED_entry_names_a_test_that_EXISTS():
    """An allowlist entry for a renamed test guards nothing and reads as
    though it still does — the shape `test_part_names` keeps its own
    allowlist honest against."""
    for key in UNRUN.ALLOWED:
        file, _, name = key.partition("::")
        path = ROOT / "tests" / file
        assert path.is_file(), key
        assert f"def {name}(" in path.read_text(encoding="utf-8"), key


def test_the_gate_answers_CLEANLY_on_this_suites_own_report(tmp_path):
    """The tool on a report shaped like the real one: a src file, a test
    file whose assertions all ran, and nothing to say."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(SOURCE,
                                                       encoding="utf-8")
    path = tmp_path / "cov.json"
    path.write_text(json.dumps({"files": {"tests/test_sample.py": {
        "executed_lines": [RAN_LOOP, ASSERT_IN_LOOP], "missing_lines": []}}}),
        encoding="utf-8")

    assert UNRUN.main(["--from-json", str(path)]) == 0
