r"""How long a build's steps took, kept so the next one can be compared.

    from docxkit import batch, timings

    report = batch.run("R22 maths typography", STEPS, parts=parts, out=OUT)
    timings.record("batch", report.name, report.durations, root=ROOT)

`batch.run` measures every step and puts the seconds in its Report; it
writes them nowhere, because that module is path-agnostic and shells out
to nothing. This is the one-liner that keeps them, and it is opt-in for
the same reason: where a paper stores its own history is the paper's
business.

**One file per run, never a shared append.** Two sessions on one tree is
the ordinary case here, not the exotic one — `tools/gates.py` learned
that with its coverage report, which had a fixed name until somebody
noticed two runs would hand `floors` each other's numbers. A JSONL line
is *usually* written atomically, and "usually" is the whole problem: a
torn line is an unparseable history discovered weeks later, with no way
to tell which run was lost.

**Nothing here gates, and nothing should.** A slow step is a fact about
the machine's afternoon — a laptop on battery, Word holding a document,
Defender reading the tree — and a build that failed on a threshold over
that would be failing for the weather. The numbers are for a reader
deciding where to spend an hour.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

__all__ = ["FLOOR_SECONDS", "FOLDER", "SLOWER", "by_step", "read", "record",
           "regressions"]

#: The folder, relative to whatever root the caller names.
FOLDER = ".timings"

#: A regression must clear BOTH. The ratio alone reports a 0.4s step
#: doubling; the floor alone reports a 30s one drifting 2s on a busy
#: machine. Together they name the thing a reader would act on.
SLOWER = 1.25
FLOOR_SECONDS = 2.0

#: One recorded run, as it comes back off disk.
Run = dict[str, Any]


def record(kind: str, name: str,
           steps: Iterable[Sequence[Any]] | Iterable[dict[str, Any]],
           folder: Path | str, *, extra: dict[str, Any] | None = None,
           outcome: str = "ok") -> Path | None:
    """Keep one run's step timings in `folder`, which is created.

    `folder` is the directory itself, not a tree to find one under —
    `<root>/timings.FOLDER` is the convention and composing it is the
    caller's line. The version that took a root and appended `.timings`
    internally read fine and made every test lie about where it was
    writing: a test handed a `tmp_path` got a folder beside it.

    `steps` takes either `(label, seconds)` pairs — which is exactly
    `batch.Report.durations` — or dicts already shaped like the record.

    Returns the path written, or None if it could not be. **Never
    raises**: a build that fell over because it could not write a
    performance note would be the tail wagging the dog.
    """
    rows: list[dict[str, Any]] = []
    for step in steps:
        if isinstance(step, dict):
            rows.append(step)
        else:
            label, seconds = step[0], step[1]
            rows.append({"name": str(label), "seconds": float(seconds),
                         "status": "ok"})
    try:
        now = dt.datetime.now()
        into = Path(folder)
        into.mkdir(parents=True, exist_ok=True)
        path = (into
                / f"{kind}-{now.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.json")
        path.write_text(json.dumps({
            "kind": kind,
            "name": name,
            "when": now.isoformat(timespec="seconds"),
            "outcome": outcome,
            "total_seconds": round(sum(float(r["seconds"]) for r in rows), 2),
            "steps": rows,
            **(extra or {}),
        }, indent=1), encoding="utf-8")
        return path
    except (OSError, TypeError, ValueError):
        return None


def read(folder: Path | str, kind: str | None = None,
         last: int | None = None) -> list[Run]:
    """Recorded runs in `folder`, oldest first.

    A file that will not parse is SKIPPED rather than fatal: one lost
    afternoon must not cost the whole history, and a reader that dies on
    a torn file is a reader nobody runs twice.
    """
    out: list[Run] = []
    for path in sorted(Path(folder).glob(f"{kind or '*'}-*.json")):
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(got, dict) and "steps" in got:
            out.append(got)
    return out[-last:] if last else out


def by_step(runs: list[Run]) -> dict[str, list[float]]:
    """Step name -> its seconds across the runs, in order.

    Only steps that finished OK. A step that failed fast is not a step
    that got faster, and a skipped one was never run at all.
    """
    seen: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for step in run.get("steps", []):
            if step.get("status") == "ok":
                seen[str(step["name"])].append(float(step["seconds"]))
    return dict(seen)


def regressions(
        runs: list[Run]) -> list[tuple[float, str, float, float, int]]:
    """Steps whose recent median stands clear of their earlier one.

    `(delta, name, was, now, samples)`, biggest first.

    **A median, never a mean, and never the newest run alone.** The
    spread is real: on 2026-09-06 the same green `pytest` gate measured
    30.5s and 40.3s ten minutes apart on one unchanged tree, purely
    because two other sessions were busy. A tool that called that a
    regression would be reporting the weather, and a reader told that
    once stops reading the section.
    """
    found = []
    for name, seconds in by_step(runs).items():
        if len(seconds) < 6:            # too few to call a median a fact
            continue
        # At least THREE in the recent window, whatever the third works
        # out to. A median over two values is their mean, so at six runs
        # a window of two let one slow afternoon carry the verdict — 30,
        # 30, 30, 30, 30, 60 reported as 30s -> 45s, which is the exact
        # coin-toss-as-a-finding this function exists to avoid.
        cut = max(3, len(seconds) // 3)
        recent, before = seconds[-cut:], seconds[:-cut]
        now, was = statistics.median(recent), statistics.median(before)
        if now >= was * SLOWER and now - was >= FLOOR_SECONDS:
            found.append((now - was, name, was, now, len(seconds)))
    return sorted(found, reverse=True)
