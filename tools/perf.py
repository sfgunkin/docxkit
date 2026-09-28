#!/usr/bin/env python
r"""The library's own timings, on one large manuscript, kept as history.

    python tools/perf.py           # time, record, report what got slower
    python tools/perf.py --report  # history only, nothing run

Timings were recorded for the GATES and never for the library
(REVIEW_2026-09-28 §6), so a change that made `para_slice` or a batch of
edits twice as slow on a long paper would show up only as an author's
wait. This builds one synthetic manuscript at the size of the long real
ones — thousands of paragraphs, tables, notes, tracked insertions —
deterministically, times the operations papers lean on, records them in
`.timings/library-*.json` through `docxkit.timings`, and prints what
`timings.regressions` says has moved.

It REPORTS and does not fail: a hard threshold on wall-clock time turns
red on a loaded machine and green on a quiet one for the same code — the
weather, as `timings.regressions` calls it. The history is the check;
this is how it gets written.

The shape the review names is O(k·n): `batch` locates every edit by
scanning the whole part again. `locate_50` and `edit_50` are that, and
the numbers to watch as the manuscript grows.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from docxkit import export, lint, revisions  # noqa: E402
from docxkit import timings as timings_mod  # noqa: E402
from docxkit._xml import DOCUMENT, element_spans  # noqa: E402
from docxkit.console import utf8_stdout  # noqa: E402
from docxkit.edit import rep  # noqa: E402
from docxkit.find import para_slice  # noqa: E402
from docxkit.tracked import accepted_view  # noqa: E402

TIMINGS = ROOT / timings_mod.FOLDER
KIND = "library"
#: The manuscript's length, and what a library operation has to lose
#: before it is named: the gates' two-second floor would never name a
#: 0.9 s locate that doubled.
PARAGRAPHS = 6000
FLOOR_SECONDS = 0.05
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')


def manuscript(paragraphs: int = 6000, every_table: int = 100) -> str:
    """A long manuscript, the same bytes on every run."""
    body: list[str] = []
    for i in range(paragraphs):
        words = " ".join(f"word{(i * 7 + k) % 997}" for k in range(24))
        run = (f'<w:r><w:t xml:space="preserve">Paragraph {i}: {words}. '
               f"</w:t></w:r>")
        if i % 10 == 3:
            run += (f'<w:ins w:id="{10_000 + i}" w:author="A" '
                    f'w:date="2026-09-01T00:00:00Z">'
                    f"<w:r><w:t>inserted</w:t></w:r></w:ins>")
        body.append(f"<w:p>{run}</w:p>")
        if i % every_table == every_table // 2:
            rows = "".join(
                "<w:tr>" + "".join(
                    f"<w:tc><w:p><w:r><w:t>{r}.{c}</w:t></w:r></w:p></w:tc>"
                    for c in range(6)) + "</w:tr>" for r in range(12))
            body.append(f"<w:tbl><w:tblPr/>{rows}</w:tbl>")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {NS}><w:body>{''.join(body)}</w:body></w:document>")


def _cold() -> None:
    """Empty the view caches, so a repeat is measured, not remembered.

    `revisions` caches the simulated views by string, and the first
    version of this timed the second and third runs as cache hits:
    0.0 ms for a view that costs tens of milliseconds to build.
    """
    for name in ("_simulate_clean", "_text_cached"):
        cached = getattr(revisions, name, None)
        if cached is not None:
            cached.cache_clear()


def _time(fn: Callable[[], object], reps: int = 3) -> float:
    """The median of `reps` COLD runs, in seconds."""
    seen = []
    for _ in range(reps):
        _cold()
        start = time.perf_counter()
        fn()
        seen.append(time.perf_counter() - start)
    return statistics.median(seen)


def measure(paragraphs: int = PARAGRAPHS) -> list[tuple[str, float]]:
    xml = manuscript(paragraphs)
    parts = {DOCUMENT: xml.encode("utf-8")}
    anchors = [f"Paragraph {i}:"
               for i in range(0, paragraphs, max(1, paragraphs // 50))]

    def edit_50() -> None:
        out = xml
        for a in anchors:
            out = rep(out, a, a.replace("Paragraph", "Para"))

    return [
        ("locate_50", _time(lambda: [para_slice(xml, a) for a in anchors])),
        ("edit_50", _time(edit_50)),
        ("table_spans", _time(lambda: element_spans(xml, "tbl"))),
        ("text_final", _time(lambda: revisions.text(xml, "final"))),
        ("text_original", _time(lambda: revisions.text(xml, "original"))),
        ("lint", _time(lambda: lint.lint_parts(dict(parts)))),
        ("markdown", _time(lambda: export.to_markdown(dict(parts)))),
        ("accepted_view", _time(lambda: accepted_view(dict(parts)))),
    ]


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--report", action="store_true",
                    help="print the recorded history's regressions only")
    args = ap.parse_args(argv)
    if not args.report:
        steps = measure(PARAGRAPHS)
        size = len(manuscript(PARAGRAPHS)) / 1e6
        print(f"library timings on a {size:.1f} MB manuscript "
              f"(median of 3):")
        for name, seconds in steps:
            print(f"  {seconds * 1e3:9.1f} ms  {name}")
        timings_mod.record(KIND, "library", steps, TIMINGS)
    moved = timings_mod.regressions(timings_mod.read(TIMINGS, KIND),
                                    floor=FLOOR_SECONDS)
    for delta, name, was, now, samples in moved:
        print(f"slower  {name}  {was:.3f}s -> {now:.3f}s (+{delta:.3f}s) "
              f"over {samples} runs")
    if not moved:
        print("no library operation has moved against its history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
