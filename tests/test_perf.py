"""`tools/perf.py` — the library's own timings, kept as history."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import perf  # pyright: ignore[reportMissingImports]

from docxkit import timings as timings_mod


def test_the_manuscript_is_the_SAME_bytes_every_run():
    """A history of timings is only comparable over the same input."""
    assert perf.manuscript(40, 20) == perf.manuscript(40, 20)
    assert perf.manuscript(40, 20).count("<w:tbl>") == 2
    assert perf.manuscript(40, 20).count("<w:ins ") == 4


def test_it_records_every_operation_and_never_fails(tmp_path, monkeypatch,
                                                    capsys):
    monkeypatch.setattr(perf, "PARAGRAPHS", 200)
    monkeypatch.setattr(perf, "TIMINGS", tmp_path)

    assert perf.main([]) == 0

    (run,) = timings_mod.read(tmp_path, perf.KIND)
    names = [step["name"] for step in run["steps"]]
    assert names == ["locate_50", "edit_50", "table_spans", "text_final",
                     "text_original", "lint", "markdown", "accepted_view"]
    assert all(step["seconds"] >= 0 for step in run["steps"])
    assert "no library operation has moved" in capsys.readouterr().out


def test_a_repeat_is_timed_COLD_not_read_from_the_view_cache(monkeypatch):
    """The first version timed runs two and three as cache hits: 0.0 ms
    for a view that costs tens of milliseconds to build."""
    cleared: list[str] = []

    class Cache:
        def __init__(self, name: str) -> None:
            self.name = name

        def cache_clear(self) -> None:
            cleared.append(self.name)

    monkeypatch.setattr(perf.revisions, "_simulate_clean",
                        Cache("_simulate_clean"), raising=False)
    monkeypatch.setattr(perf.revisions, "_text_cached", Cache("_text_cached"),
                        raising=False)

    perf._time(lambda: None, reps=2)

    assert cleared == ["_simulate_clean", "_text_cached"] * 2


def test_REPORT_runs_nothing_and_names_a_SUB_SECOND_regression(
        tmp_path, monkeypatch, capsys):
    """By the library's floor, not the gates' two seconds: a 0.4 s
    locate that doubled is exactly what this exists to name."""
    import json

    monkeypatch.setattr(perf, "TIMINGS", tmp_path)

    def ran(*_a: object) -> list[tuple[str, float]]:
        raise AssertionError("--report measured")

    monkeypatch.setattr(perf, "measure", ran)
    for i, seconds in enumerate((0.4, 0.4, 0.4, 0.8, 0.8, 0.8)):
        (tmp_path / f"library-2026092{i}-000000-1.json").write_text(
            json.dumps({"kind": "library", "steps": [
                {"name": "locate_50", "seconds": seconds,
                 "status": "ok"}]}), encoding="utf-8")

    assert perf.main(["--report"]) == 0
    out = capsys.readouterr().out
    assert "slower  locate_50  0.400s -> 0.800s" in out
    assert timings_mod.regressions(timings_mod.read(tmp_path)) == [], (
        "and the gates' own floor would not have named it")
