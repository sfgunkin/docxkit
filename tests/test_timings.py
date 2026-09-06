"""`tools/timings.py` — what the gate chain spends its time on.

Two things are worth gating here, and neither is arithmetic.

**That the history holds one kind of event.** `gates.run` defaults to
writing nothing, because `tests/test_gates.py` drives it with synthetic
gates and the first version defaulted to the real folder: one chain run
produced "3 chain runs recorded", the medians mixed a real chain with
two suites of fakes, and the real `mypy` gate sorted into "under 0.5s
and not worth optimising".

**That a regression needs more than one slow afternoon.** The same green
`pytest` gate has measured 27.8s and 33.5s an hour apart on one tree.
A reader who is told that is a regression stops reading the section.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

from conftest import document, para, run

import docxkit
from docxkit import timings

ROOT = pathlib.Path(docxkit.__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T = _load("timings")
GATES = _load("gates")

OK = ["python", "-c", "print('All checks passed!')"]


def _run(folder, when, **seconds):
    """One recorded chain run, with the gates named as keyword args."""
    entries = [{"name": n, "seconds": s, "status": "ok"}
               for n, s in seconds.items()]
    path = folder / f"gates-{when}-1.json"
    path.write_text(json.dumps({
        "kind": "gates", "name": "chain", "when": when, "outcome": "green",
        "total_seconds": sum(seconds.values()), "steps": entries,
    }), encoding="utf-8")
    return path


# --- the history holds one kind of event ---------------------------------

def test_running_the_chain_as_a_LIBRARY_writes_no_record(tmp_path):
    """The defect that shipped for ten minutes. The test suite drives
    `gates.run` with fake gates; if that files a record, every median
    afterwards is computed over a real chain and a pile of fakes."""
    before = list(tmp_path.glob("*.json"))

    GATES.run([("first", OK, False)], say=lambda _s: None)

    assert list(tmp_path.glob("*.json")) == before
    assert not list((ROOT / ".timings").glob("gates-*-fake.json"))


def test_a_record_is_written_when_a_caller_ASKS_for_one(tmp_path):
    GATES.run([("first", OK, False)], say=lambda _s: None, timings=tmp_path)

    written = list(tmp_path.glob("gates-*.json"))
    assert len(written) == 1
    got = json.loads(written[0].read_text(encoding="utf-8"))
    assert got["outcome"] == "green"
    assert [g["name"] for g in got["steps"]] == ["first"]
    assert got["steps"][0]["seconds"] >= 0


def test_a_FAILED_chain_still_records_what_it_measured(tmp_path):
    """The run that matters most: a chain that died at gate four still
    says how long the three before it took."""
    red = ["python", "-c", "raise SystemExit(1)"]

    GATES.run([("first", OK, False), ("second", red, False),
               ("third", OK, False)],
              say=lambda _s: None, timings=tmp_path)

    got = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert got["outcome"] == "failed:second"
    assert [g["name"] for g in got["steps"]] == ["first", "second"], \
        "the gate that failed is timed too; the ones never reached are not"
    assert got["steps"][1]["status"] == "failed"


def test_an_unwritable_folder_does_not_bring_the_CHAIN_down(tmp_path):
    """A gate runner that fell over because it could not write a
    performance note would be the tail wagging the dog."""
    wall = tmp_path / "nope.txt"
    wall.write_text("not a directory", encoding="utf-8")

    code = GATES.run([("first", OK, False)], say=lambda _s: None,
                     timings=wall / "under-a-file")

    assert code == 0


# --- reading it ----------------------------------------------------------

def test_a_corrupt_record_is_SKIPPED_not_fatal(tmp_path):
    """A torn file is one lost afternoon, not a dead tool."""
    _run(tmp_path, "20260901-100000", pytest=30.0)
    (tmp_path / "gates-20260901-110000-1.json").write_text(
        "{not json", encoding="utf-8")

    assert len(T.records(tmp_path)) == 1


def test_the_ranking_is_by_MEDIAN_not_by_the_latest_run(tmp_path):
    """One cold-cache run must not rewrite the number a reader plans
    against. `ruff` is last here on the median and first on the newest
    run; the report is about the habit, not the afternoon."""
    for i, (pt, rf) in enumerate([(30.0, 1.0), (31.0, 1.0), (29.0, 90.0)]):
        _run(tmp_path, f"2026090{i + 1}-100000", pytest=pt, ruff=rf)

    ranked = T.by_gate(T.records(tmp_path))

    assert sorted(ranked) == ["pytest", "ruff"]
    import statistics
    assert statistics.median(ranked["pytest"]) == 30.0
    assert statistics.median(ranked["ruff"]) == 1.0


def test_only_GREEN_gate_runs_are_counted(tmp_path):
    """A gate that failed fast is not a gate that got faster."""
    path = tmp_path / "gates-20260901-100000-1.json"
    path.write_text(json.dumps({"when": "x", "total_seconds": 1, "steps": [
        {"name": "pytest", "seconds": 0.2, "status": "failed"},
        {"name": "sweep", "seconds": 0.1, "status": "skipped"},
        {"name": "ruff", "seconds": 1.0, "status": "ok"}]}), encoding="utf-8")

    assert list(T.by_gate(T.records(tmp_path))) == ["ruff"]


# --- regressions ---------------------------------------------------------

def test_a_gate_that_really_slowed_is_named(tmp_path):
    for i in range(6):
        _run(tmp_path, f"2026090{i + 1}-100000",
             pytest=30.0 if i < 4 else 45.0)

    moved = T.regressions(T.records(tmp_path))

    assert [m[1] for m in moved] == ["pytest"]
    assert moved[0][2] == 30.0 and moved[0][3] == 45.0


def test_a_SMALL_gate_doubling_is_not_a_regression(tmp_path):
    """0.4s to 0.8s doubled and does not matter. Reporting it teaches
    the reader to skim the section that matters."""
    for i in range(6):
        _run(tmp_path, f"2026090{i + 1}-100000", ruff=0.4 if i < 4 else 0.8)

    assert T.regressions(T.records(tmp_path)) == []


def test_ONE_slow_afternoon_is_not_a_regression(tmp_path):
    """The spread on this chain is real — 27.8s and 33.5s an hour apart
    on the same tree — so the newest run alone cannot be the verdict."""
    for i in range(6):
        _run(tmp_path, f"2026090{i + 1}-100000",
             pytest=30.0 if i < 5 else 60.0)

    assert T.regressions(T.records(tmp_path)) == [], \
        "a single slow run was reported as a regression"


def test_too_few_runs_to_call_a_median_a_fact(tmp_path):
    for i in range(4):
        _run(tmp_path, f"2026090{i + 1}-100000",
             pytest=30.0 if i < 2 else 90.0)

    assert T.regressions(T.records(tmp_path)) == []


# --- the report ----------------------------------------------------------

def test_an_empty_history_says_what_to_RUN_not_just_that_it_is_empty(
        tmp_path):
    said: list[str] = []

    T.report(T.records(tmp_path), say=said.append)

    assert "tools/gates.py" in "\n".join(said)


def test_the_report_names_the_slowest_tests_from_the_pytest_gate(tmp_path):
    path = tmp_path / "gates-20260901-100000-1.json"
    path.write_text(json.dumps({"when": "x", "total_seconds": 30,
                                "steps": [{"name": "pytest", "seconds": 30.0,
                                           "status": "ok",
                                           "slowest_tests": [
                                               {"seconds": 6.19,
                                                "phase": "call",
                                                "test": "tests/t.py::slow"}]}]
                                }), encoding="utf-8")
    said: list[str] = []

    T.report(T.records(tmp_path), say=said.append)
    out = "\n".join(said)

    assert "tests/t.py::slow" in out and "6.19" in out


# --- docxkit.timings, the format both producers write -------------------

def test_record_takes_the_PAIRS_a_batch_Report_hands_back(tmp_path):
    """`batch.Report.durations` is `[(label, seconds), ...]`, and going
    through a dict conversion at every call site is how two producers
    end up with two shapes."""
    path = timings.record("batch", "R22 maths typography",
                          [("upright operators", 0.2),
                           ("maths glyphs", 4.25)], tmp_path)

    assert path is not None
    got = json.loads(path.read_text(encoding="utf-8"))
    assert got["kind"] == "batch" and got["name"] == "R22 maths typography"
    assert got["total_seconds"] == 4.45
    assert [s["name"] for s in got["steps"]] == ["upright operators",
                                                 "maths glyphs"]


def test_record_writes_into_the_folder_it_was_GIVEN(tmp_path):
    """It took a root and appended `.timings` once. Every test that
    handed it a tmp_path then wrote beside that path instead of in it,
    and read nothing back."""
    timings.record("batch", "x", [("a", 1.0)], tmp_path)

    assert len(list(tmp_path.glob("batch-*.json"))) == 1
    assert not (tmp_path / timings.FOLDER).exists()


def test_record_returns_None_rather_than_raising_into_a_BUILD(tmp_path):
    """A round that failed because it could not write a performance note
    would be the tail wagging the dog."""
    wall = tmp_path / "a-file"
    wall.write_text("not a directory", encoding="utf-8")

    assert timings.record("batch", "x", [("a", 1.0)], wall / "under") is None


def test_read_skips_a_file_that_is_not_one_of_OURS(tmp_path):
    """The folder is a directory on disk; something else will put a
    JSON file in it eventually."""
    timings.record("batch", "mine", [("a", 1.0)], tmp_path)
    (tmp_path / "batch-notes.json").write_text('{"hello": 1}',
                                               encoding="utf-8")

    assert [r["name"] for r in timings.read(tmp_path)] == ["mine"]


def test_read_can_ask_for_ONE_KIND(tmp_path):
    """One folder holds a paper's batches and, if it has them, its gate
    runs; comparing a batch against a chain would be nonsense."""
    timings.record("batch", "a batch", [("a", 1.0)], tmp_path)
    timings.record("gates", "chain", [("ruff", 1.0)], tmp_path)

    assert [r["name"] for r in timings.read(tmp_path, kind="batch")] == \
        ["a batch"]
    assert len(timings.read(tmp_path)) == 2


def test_a_batch_run_carries_its_step_timings_back(tmp_path):
    """The whole paper-side path in one test: `batch.run` measures, the
    Report holds it, `timings.record` keeps it."""
    from docxkit import batch

    def slow(xml, _parts):
        return xml.replace("Intro", "Introduction")

    parts = {batch.DOCUMENT: document(
        para(run("Intro paragraph."), pid="A1")).encode("utf-8")}
    report = batch.run("r1", [batch.Step("relabel", slow)], parts=parts)

    assert [d[0] for d in report.durations] == ["relabel"]
    assert report.durations[0][1] >= 0
    path = timings.record("batch", report.name, report.durations, tmp_path)
    assert path is not None
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == "r1"


def test_a_step_that_FAILED_is_timed_too(tmp_path):
    """A step that raises after thirty seconds is the interesting one —
    the round is slow AND broken. Dropping it leaves the report blaming
    whichever step ran next."""
    from docxkit import batch

    def boom(_xml, _parts):
        raise ValueError("no")

    parts = {batch.DOCUMENT: document(
        para(run("Intro."), pid="A1")).encode("utf-8")}
    report = batch.run("r1", [batch.Step("swap the figure", boom)],
                       parts=parts)

    assert not report.ok
    assert [d[0] for d in report.durations] == ["swap the figure"]


def test_prune_keeps_the_NEWEST(tmp_path):
    for i in range(5):
        _run(tmp_path, f"2026090{i + 1}-100000", ruff=1.0)

    gone = T.prune(2, tmp_path)

    kept = sorted(p.name for p in tmp_path.glob("*.json"))
    assert gone == 3
    assert kept == ["gates-20260904-100000-1.json",
                    "gates-20260905-100000-1.json"]
