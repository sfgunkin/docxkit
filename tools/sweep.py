r"""Run every read-only docxkit routine over a corpus of real manuscripts.

    python tools/sweep.py <root> [<root> ...] [--limit N] [--slow MS]

A unit suite on synthetic fixtures proves the rules; this proves they
survive contact with documents nobody wrote them for — Russian
methodology papers, hand-authored redlines, forty-version histories.
Every routine is read-only and each file is copied to TEMP first, so a
sweep can never touch a manuscript.

Reports, in order of what is worth acting on:
  FAILED      a routine raised — a bug, unless the file is not a docx
  ANOMALY     it returned something implausible (a paper with no
              paragraphs, captions but no figures, citations but no
              reference list)
  SLOW        operations above the --slow threshold
"""
from __future__ import annotations

import argparse
import io
import re
import statistics
import sys
import time
import traceback
import zipfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docxkit import (
    citations,
    comments,
    crossrefs,
    equations,
    figures,
    footnotes,
    hygiene,
    lint,
    revisions,
    tables,
)
from docxkit.console import utf8_stdout
from docxkit.testing import read_bytes

SKIP = re.compile(r"~\$|backup|_old|_pre_|\.tmp|userbackup|bak_",
                  re.IGNORECASE)


Routine = Callable[[], object]


def routines(blob: bytes) -> dict[str, Routine]:
    """Every read-only routine, as name -> callable."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = set(z.namelist())
        raw = {n: z.read(n) for n in names}
    doc = raw["word/document.xml"].decode("utf-8")
    foot = raw.get("word/footnotes.xml", b"").decode("utf-8")

    return {
        "lint": lambda: len(lint.lint_parts(dict(raw))),
        "text.final": lambda: len(revisions.text(doc, revisions.FINAL)),
        "text.original": lambda: len(revisions.text(doc, revisions.ORIGINAL)),
        "revisions.counts": lambda: revisions.counts(doc),
        "revisions.spans": lambda: len(revisions.spans(doc)),
        "tables.read_all": lambda: len(tables.read_all(doc)),
        "figures.find_all": lambda: len(figures.find_all(doc)),
        "figures.shared": lambda: sum(
            1 for v in figures.shared_relationships(doc).values() if v > 1),
        "equations.all": lambda: len(equations.equations(doc)),
        "equations.display": lambda: len(equations.display_equations(doc)),
        "citations.find": lambda: sum(
            len(citations.find_citations(p))
            for p in revisions.text(doc, revisions.FINAL)),
        "citations.refs": lambda: len(
            citations.references(revisions.text(doc, revisions.FINAL))),
        "crossrefs.captions": lambda: len(crossrefs.find_captions(doc)),
        "crossrefs.linked": lambda: len(crossrefs.audit(doc)["linked"]),
        "crossrefs.dangling": lambda: len(
            crossrefs.audit(doc)["dangling"]),
        "comments.read_all": lambda: len(comments.read_all(dict(raw))),
        "footnotes.find_all": lambda: len(footnotes.find_all(foot))
        if foot else 0,
        "hygiene.strip": lambda: len(hygiene.strip_parts(dict(raw))),
    }


def sweep(paths: list[Path], slow_ms: float) -> int:
    failures: list[tuple[Path, str, str]] = []
    anomalies: list[tuple[Path, str]] = []
    timings: dict[str, list[float]] = defaultdict(list)
    results: dict[Path, dict[str, object]] = {}

    for i, path in enumerate(paths, 1):
        print(f"[{i:3}/{len(paths)}] {path.name[:62]:<62}", end="", flush=True)
        try:
            blob = read_bytes(path, skip_if_locked=False)
            calls = routines(blob)
        except Exception as exc:
            print(f"  UNREADABLE ({type(exc).__name__})")
            failures.append((path, "open", f"{type(exc).__name__}: {exc}"))
            continue

        row: dict[str, object] = {}
        for name, call in calls.items():
            start = time.perf_counter()
            try:
                row[name] = call()
            except Exception:
                failures.append((path, name, traceback.format_exc(limit=3)))
                row[name] = "FAIL"
            timings[name].append((time.perf_counter() - start) * 1000)
        results[path] = row
        print(f"  paras={row.get('text.final')}"
              f" tbl={row.get('tables.read_all')}"
              f" fig={row.get('figures.find_all')}"
              f" eq={row.get('equations.all')}"
              f" cite={row.get('citations.find')}")
        anomalies.extend((path, a) for a in check(row))

    report(failures, anomalies, timings, results, slow_ms)
    return 1 if failures else 0


def check(row: dict[str, object]) -> list[str]:
    """Implausible results — the interesting half of a sweep."""
    out = []
    if row.get("lint") not in (0, "FAIL"):
        out.append(f"lint reports {row['lint']} structural problem(s)")
    if row.get("text.final") == 0:
        out.append("no paragraphs of text")
    if isinstance(row.get("figures.shared"), int) and row["figures.shared"]:
        out.append(f"{row['figures.shared']} image relationship(s) shared by "
                   "several drawings — replacing one changes them all")
    cites, refs = row.get("citations.find"), row.get("citations.refs")
    if isinstance(cites, int) and isinstance(refs, int) and cites and not refs:
        out.append(f"{cites} citations but no reference list found")
    if row.get("hygiene.strip"):
        out.append(f"{row['hygiene.strip']} stray customXml part(s)")
    return out


def report(failures, anomalies, timings, results, slow_ms) -> None:
    print(f"\n{'=' * 72}\nSWEPT {len(results)} documents")

    print(f"\nFAILED ({len(failures)})")
    seen = set()
    for path, name, detail in failures:
        key = (name, detail.strip().splitlines()[-1] if detail else "")
        if key in seen:
            continue
        seen.add(key)
        print(f"  {path.name} :: {name}")
        for line in detail.strip().splitlines()[-2:]:
            print(f"      {line.strip()[:110]}")
    if not failures:
        print("  (none)")

    print(f"\nANOMALIES ({len(anomalies)})")
    by_kind: dict[str, list[str]] = defaultdict(list)
    for path, note in anomalies:
        by_kind[re.sub(r"^\d+", "N", note)].append(path.name)
    for kind, names in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        print(f"  [{len(names):3}] {kind}")
        for name in names[:3]:
            print(f"          {name[:66]}")
        if len(names) > 3:
            print(f"          ... and {len(names) - 3} more")
    if not anomalies:
        print("  (none)")

    print("\nTIMING (ms per document)")
    print(f"  {'routine':<22} {'median':>8} {'p95':>8} {'max':>8}")
    for name, raw in sorted(timings.items(),
                            key=lambda kv: -statistics.median(kv[1])):
        times = sorted(raw)
        p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
        flag = "  <-- SLOW" if p95 > slow_ms else ""
        print(f"  {name:<22} {statistics.median(times):8.1f} {p95:8.1f} "
              f"{times[-1]:8.1f}{flag}")


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--slow", type=float, default=250.0,
                    help="flag routines whose p95 exceeds this, in ms")
    args = ap.parse_args()

    paths: list[Path] = []
    for root in args.roots:
        base = Path(root)
        paths.extend(sorted(p for p in base.rglob("*.docx")
                            if not SKIP.search(str(p))))
    if args.limit:
        paths = paths[:args.limit]
    return sweep(paths, args.slow)


if __name__ == "__main__":
    sys.exit(main())
