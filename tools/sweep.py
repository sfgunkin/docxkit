r"""Run every read-only docxkit routine over a corpus of real manuscripts.

    python tools/sweep.py [<root> ...] [--limit N] [--slow MS]
    python tools/sweep.py [<root> ...] --findings after.json [--diff before.json]
    python tools/sweep.py --diff before.json after.json

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

**What did a change to an audit do to the corpus?** ``--findings OUT``
runs the AUDITS instead of the routines — citations, crossrefs, lint —
and records each document's (kind, subject) findings, with the commit
they were made at. Record once at each version; ``--diff BEFORE`` prints
what went and what came, by audit and kind, with the shape of the names
involved (exhibit, author-year key, in-text citation) and the documents.
It exits 0 whatever it finds: it is a measurement, not a gate, and
"how many findings may a change move?" has no right number.
``--jobs N`` (default 6) runs the documents in N processes.

**Where the corpus is.** With no roots on the command line this reads
``DOCXKIT_CORPUS`` — one or more directories, separated the way the
platform separates ``PATH``. Unset, the sweep SKIPS (exit 3) and says
so, because there is no corpus to sweep and pretending otherwise is
worse than not running: this is the gate whose whole subject is
documents nobody anticipated, and a green line over zero of them reads
exactly like a green line over 347.

Wired into ``tools/gates.py`` on 2026-08-30. Until then it was a
documented tool bound to nothing — CONTRIBUTING said "run it before a
release" and no chain, workflow or gate ever did, which is the shape the
curated mutations were in until 2026-08-27. CI cannot run it (there is
no corpus on a runner and a checkout cannot carry one), so the local
chain is the only place it can live.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
import traceback
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docxkit import (
    citations,
    comments,
    compare,
    crossrefs,
    equations,
    figures,
    footnotes,
    hygiene,
    lint,
    refstyle,
    revisions,
    tables,
)
from docxkit.console import utf8_stdout
from docxkit.testing import read_bytes

SKIP = re.compile(r"~\$|backup|_old|_pre_|\.tmp|userbackup|bak_",
                  re.IGNORECASE)


Routine = Callable[[], object]
#: A findings record as `--findings` writes it: the commit, and per
#: document either {audit: [[kind, subject], ...]} or an error string.
Record = dict[str, Any]


def _self_diff(raw: dict[str, bytes]) -> int:
    """Gated differences between a document and itself — always 0.

    `compare.GATED` rather than a tuple of the same four names spelled
    out here: two copies would be two answers to "did anything change?".
    """
    doc = compare.load_parts(raw)
    report = compare.compare_docs(doc, doc)
    return sum(len(report[k]) for k in compare.GATED)


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
        "citations.audit": lambda: len(citations.audit_links(dict(raw))[0]),
        "refstyle.audit": lambda: len(refstyle.audit(dict(raw)).issues),
        "crossrefs.captions": lambda: len(crossrefs.find_captions(doc)),
        "crossrefs.linked": lambda: len(crossrefs.audit(doc)["linked"]),
        "crossrefs.dangling": lambda: len(
            crossrefs.audit(doc)["dangling"]),
        "comments.read_all": lambda: len(comments.read_all(dict(raw))),
        # A document against ITSELF must report nothing. It is the cheapest
        # false-positive gate the authoritative diff has: the day headers,
        # footers and endnotes were included, this caught a Word-written
        # endnotes.xml holding only separator entries being reported as a
        # whole part gained.
        "compare.self": lambda: _self_diff(dict(raw)),
        "footnotes.find_all": lambda: len(footnotes.find_all(foot))
        if foot else 0,
        # How many DISTINCT face/size combinations the notes state. A
        # house rule ("footnotes are Times New Roman 10") is a claim
        # about this number being one.
        "footnotes.fonts": lambda: len(footnotes.fonts(foot)) if foot else 0,
        "hygiene.strip": lambda: len(hygiene.strip_parts(dict(raw))),
    }


def sweep(paths: list[Path], slow_ms: float) -> int:
    failures: list[tuple[Path, str, str]] = []
    skipped: list[Path] = []
    anomalies: list[tuple[Path, str]] = []
    timings: dict[str, list[float]] = defaultdict(list)
    results: dict[Path, dict[str, object]] = {}

    for i, path in enumerate(paths, 1):
        print(f"[{i:3}/{len(paths)}] {path.name[:62]:<62}", end="", flush=True)
        try:
            blob = read_bytes(path, skip_if_locked=False)
            calls = routines(blob)
        except zipfile.BadZipFile as exc:
            # Not a manuscript: a `.docx` with a zip header and no
            # central directory (`SPI_Case-Ezhik-PC.docx`, 2021) made
            # this gate exit 1 on every run that reached it — the
            # permanently-red shape BACKLOG ranks above a wrong answer.
            # Skipped, COUNTED and named, and only this exception: a
            # PermissionError or a raise inside docxkit is still a
            # failure. Skipping `OSError` too would have swallowed the
            # locked-file case the sweep exists to exercise.
            print(f"  NOT A DOCUMENT ({exc})")
            skipped.append(path)
            continue
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

    report(failures, skipped, anomalies, timings, results, slow_ms=slow_ms)
    return 1 if failures else 0


def check(row: dict[str, object]) -> list[str]:
    """Implausible results — the interesting half of a sweep."""
    out = []
    if row.get("lint") not in (0, "FAIL"):
        out.append(f"lint reports {row['lint']} structural problem(s)")
    if row.get("compare.self") not in (0, "FAIL"):
        out.append(f"compare reports {row['compare.self']} difference(s) "
                   "between the document and ITSELF")
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


def report(failures, skipped, anomalies, timings, results, *,
           slow_ms) -> None:
    # The skip count is on the SAME line as the sweep count, so "swept
    # 300, skipped 1" and "swept 1, skipped 300" cannot read alike — a
    # skip path in a gate is the S3 shape, and the count is what keeps
    # it honest.
    print(f"\n{'=' * 72}\nSWEPT {len(results)} documents"
          + (f", SKIPPED {len(skipped)} not a document" if skipped else ""))
    for path in skipped:
        print(f"  skipped: {path.name} (not a zip — a .docx with no "
              f"central directory)")

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


# --- findings: what an audit change does to the corpus ------------------
#
# Narrowing an audit rule is measured over the corpus before and after,
# and until 2026-10-08 every measurement was hand-rolled: `_no_backlink`
# over 100 manuscripts, the UNLINKED label rule over 397, the exhibit-
# anchor fix over 1,784. The routines above keep no findings, so they
# cannot answer "which findings did this change remove or add, and in
# which documents" — and on 2026-10-05 the hand-rolled answer is what
# caught a fix's first version ADDING 11,470 findings while removing
# 2,691. Two runs, one at each version, and a diff.

#: The audits whose findings are recorded. Each returns (kind, subject)
#: pairs; `subject` is what the finding is ABOUT — a bookmark, a
#: citation — so the same finding at both versions is the same pair.
AUDITS = ("citations", "crossrefs", "lint")


def findings_of(blob: bytes) -> dict[str, list[list[str]]]:
    """Every audit's findings for one document, sorted, as JSON pairs.

    crossrefs' ``linked`` bucket is the one that is not a finding: it is
    the exhibits that are RIGHT. lint's messages carry no kind of their
    own, so they file under one, with the message as the subject.

    crossrefs reads the notes too, as `docxkit crossrefs --audit` does:
    a work cited only in a footnote keeps its bookmark there, and the
    body alone reports it DANGLING — a finding no reader of the command
    ever sees, recorded on every run (review of 2026-10-08).
    """
    from docxkit._cite_audit import _audit_findings  # noqa: PLC0415

    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = {n: z.read(n) for n in z.namelist()}
    doc = raw["word/document.xml"].decode("utf-8")
    cite, _ = _audit_findings(dict(raw))
    notes = [raw[n].decode("utf-8") for n in
             ("word/footnotes.xml", "word/endnotes.xml") if n in raw]
    xref = crossrefs.audit(doc, also=notes)
    return {
        "citations": sorted([f.kind, f.subject] for f in cite),
        "crossrefs": sorted([kind.upper(), subject]
                            for kind, subjects in xref.items()
                            if kind != "linked" for subject in subjects),
        "lint": sorted(["LINT", m] for m in lint.lint_parts(dict(raw))),
    }


def _findings_job(path: str) -> tuple[str, dict[str, list[list[str]]] | str]:
    """One document's findings, or the error that stopped them.

    Module level, so a worker process can import it by name.
    """
    try:
        return path, findings_of(read_bytes(path, skip_if_locked=False))
    except Exception as exc:          # recorded, and diffed
        return path, f"ERROR {type(exc).__name__}: {exc}"


def record_findings(paths: list[Path], out: Path, jobs: int, *,
                    roots: Sequence[str | Path] = ()) -> Record:
    """Run the audits over `paths` and write what they found to `out`.

    The record carries the commit it was made at and whether the tree
    was dirty: a before/after pair is two runs at two versions, and a
    file that cannot say which version it is a measurement of is the
    mistake this exists to prevent.

    Documents are keyed by :func:`document_key` — relative to their
    root — so two records of one corpus meet whichever way the root was
    spelled.
    """
    docs: dict[str, object] = {}
    names = [str(p) for p in paths]
    keys = {name: document_key(Path(name), roots) for name in names}
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for i, (path, res) in enumerate(
                    pool.map(_findings_job, names, chunksize=4), 1):
                docs[keys[path]] = res
                _progress(i, len(names))
    else:
        for i, name in enumerate(names, 1):
            path, res = _findings_job(name)
            docs[keys[path]] = res
            _progress(i, len(names))
    record = {"commit": _commit(), "documents": docs}
    out.write_text(json.dumps(record, ensure_ascii=False, indent=0,
                              sort_keys=True), encoding="utf-8")
    errors = sum(isinstance(v, str) for v in docs.values())
    total = sum(len(pairs) for v in docs.values() if isinstance(v, dict)
                for pairs in v.values())
    print(f"\nRECORDED {len(docs)} documents, {total} findings, "
          f"{errors} error(s) -> {out}  (at {record['commit']})")
    return record


def document_key(path: Path, roots: Sequence[str | Path]) -> str:
    """A document's name in a record: its path under the root holding it.

    Not the path as the root was TYPED. `D:\\corpus` from the
    environment and `D:/corpus` on the command line are one corpus, and
    keyed raw the two records shared no document, so the diff compared
    nothing and said so in one line (review of 2026-10-08). With several
    roots the root's own name leads, so two roots' `paper.docx` stay two.
    """
    resolved = path.resolve()
    for root in roots:
        base = Path(root).resolve()
        if resolved.is_relative_to(base):
            rel = resolved.relative_to(base).as_posix()
            return f"{base.name}/{rel}" if len(roots) > 1 else rel
    return resolved.as_posix()


def _progress(done: int, total: int) -> None:
    if done == total or done % 50 == 0:
        print(f"  {done}/{total}", flush=True)


def _commit() -> str:
    """HEAD, with `+dirty` when what decides the findings differs from it.

    That is `src`, and this file: `findings_of` chooses which audits run
    and which buckets count, so an edit to it between two records is a
    change the diff would otherwise attribute to `src`.
    """
    repo = Path(__file__).resolve().parents[1]
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo, capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src",
                                "tools/sweep.py"],
                               cwd=repo, capture_output=True, text=True,
                               check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("+dirty" if dirty else "")


# The exhibit word must END there: `Figlio2010` and `Boxell2017` are
# authors. Two lowercase letters after it mean the word goes on;
# `TableA7` and `figure2txt` do not.
_EXHIBIT = re.compile(
    r"^(?i:table|figure|fig|box|chart|map|exhibit|panel|appendix|section|"
    r"eq)(?![a-z]{2})")
# Any script's letters: `Mühlbach2020` and a Cyrillic surname are keys.
_KEY = re.compile(r"^[^\W\d_](?:[^\W\d_]|\.)*?\d{4}[a-z]?"
                  r"(?:_\d+)?(?:txt)?$")
_CITATION = re.compile(r"\s.*\d{4}")


def shape(subject: str) -> str:
    """What KIND of name a finding is about, for the breakdown.

    The question a delta raises first is "which names went?": the
    exhibit-anchor fix was right to drop `Table4` and `figure2txt`, and
    wrong to drop the 119 author-year keys among them.
    """
    if _KEY.match(subject):
        return "author-year key"
    if _EXHIBIT.match(subject):
        return "exhibit"
    if _CITATION.search(subject):
        return "in-text citation"
    return "other"


def _pairs(entry: object) -> Counter[tuple[str, str, str]] | None:
    if not isinstance(entry, dict):
        return None
    return Counter((audit, kind, subject)
                   for audit, pairs in entry.items()
                   for kind, subject in pairs)


def diff_findings(before: Record, after: Record, *,
                  show: int = 5) -> dict[str, Any]:
    """Print what changed between two records; return the delta.

    Compared over the documents BOTH records hold, and the ones only one
    holds are counted out loud — two strided samples of different sizes
    are different documents, and their difference is not the change's.
    """
    b_docs, a_docs = before["documents"], after["documents"]
    common = sorted(set(b_docs) & set(a_docs))
    only = len(set(b_docs) ^ set(a_docs))
    gone: list[tuple[str, tuple[str, str, str]]] = []
    new: list[tuple[str, tuple[str, str, str]]] = []
    errors: list[tuple[str, object, object]] = []
    changed = 0
    for path in common:
        b, a = _pairs(b_docs[path]), _pairs(a_docs[path])
        if b is None or a is None:
            if b_docs[path] != a_docs[path]:
                errors.append((path, b_docs[path], a_docs[path]))
            continue
        if b != a:
            changed += 1
        gone += [(path, k) for k, n in (b - a).items() for _ in range(n)]
        new += [(path, k) for k, n in (a - b).items() for _ in range(n)]

    print(f"\n{'=' * 72}\nFINDINGS {before.get('commit')} -> "
          f"{after.get('commit')}: {len(common)} documents compared, "
          f"{changed} changed"
          + (f", {only} in ONE record only (not compared)" if only else ""))
    print(f"  GONE {len(gone)}   NEW {len(new)}")
    for label, rows in (("GONE", gone), ("NEW", new)):
        by_kind: dict[tuple[str, str], list[tuple[str, str]]] = \
            defaultdict(list)
        for path, (audit, kind, subject) in rows:
            by_kind[(audit, kind)].append((path, subject))
        for (audit, kind), hits in sorted(by_kind.items(),
                                          key=lambda kv: -len(kv[1])):
            shapes = Counter(shape(s) for _, s in hits)
            files = len({p for p, _ in hits})
            print(f"\n  {label} {len(hits):6}  {audit} {kind}  "
                  f"({files} document(s))")
            print("          " + ", ".join(
                f"{s} {n}" for s, n in shapes.most_common()))
            for path, subject in hits[:show]:
                print(f"          {subject[:40]!r}  {Path(path).name[:40]}")
    for path, was, now in errors:
        print(f"\n  ERROR CHANGED {Path(path).name}\n      before: "
              f"{str(was)[:100]}\n      after:  {str(now)[:100]}")
    return {"gone": gone, "new": new, "errors": errors, "changed": changed,
            "only": only}


#: Exit code for "this did not run, and here is why" — distinct from
#: both 0 (swept, nothing failed) and 1 (a routine raised). `gates.py`
#: prints it as `skip`, so a chain over a machine with no corpus reads
#: as six gates and one nag rather than seven greens.
SKIPPED = 3

#: Where the corpus is, when it is not on the command line. Several
#: roots separated the way the platform separates PATH.
CORPUS_ENV = "DOCXKIT_CORPUS"

#: An upper bound for the gate. A full sweep of a manuscript tree on a
#: sync-on-demand drive is minutes of enumeration alone, and a gate that
#: slow gets switched off, which costs more than a bounded one.
LIMIT_ENV = "DOCXKIT_CORPUS_LIMIT"


def corpus_roots(argv_roots: Sequence[str]) -> list[str]:
    """Roots from the command line, else from the environment."""
    if argv_roots:
        return list(argv_roots)
    raw = os.environ.get(CORPUS_ENV, "")
    return [part for part in raw.split(os.pathsep) if part.strip()]


def sample(paths: list[Path], limit: int) -> list[Path]:
    """At most `limit` documents, STRIDED across the corpus.

    Not `paths[:limit]`, which is what this did. Sorted paths are
    alphabetical, so a prefix is one corner of one directory — and a
    bounded sweep that reads the same corner every time is a sweep that
    can never find anything it has not already found. That is the exact
    failure this tool exists to avoid: its whole subject is the document
    nobody anticipated, and those are distributed through the corpus,
    not gathered under A.
    """
    if limit <= 0 or len(paths) <= limit:
        return paths
    stride = len(paths) / limit
    return [paths[int(i * stride)] for i in range(limit)]


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--slow", type=float, default=250.0,
                    help="flag routines whose p95 exceeds this, in ms")
    ap.add_argument("--findings", type=Path, metavar="OUT",
                    help="record the audits' findings to OUT instead of "
                         "running the routines")
    ap.add_argument("--diff", type=Path, nargs="+", metavar="RECORD",
                    help="BEFORE (with --findings), or BEFORE AFTER")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()

    if args.diff and len(args.diff) > 2:
        ap.error("--diff takes BEFORE, or BEFORE AFTER")
    if args.diff and len(args.diff) == 2:
        if args.findings or args.roots:
            ap.error("--diff BEFORE AFTER compares two records; it sweeps "
                     "nothing")
        diff_findings(*(_load(p) for p in args.diff))
        return 0
    if args.diff and not args.findings:
        ap.error("--diff BEFORE needs --findings OUT to compare it with")

    roots = corpus_roots(args.roots)
    if not roots:
        # The FIRST line is the one `gates.py` shows, so it carries the
        # instruction; the rest is for somebody reading the tool's own
        # output and wondering whether to bother.
        print(f"SKIPPED: no corpus — set {CORPUS_ENV} to the manuscript "
              f"root(s)")
        print(f"  Several roots separate with {os.pathsep!r}, or pass "
              f"them as arguments.")
        print("  The synthetic suite cannot answer what this asks: it "
              "holds only the")
        print("  shapes somebody already knew to write.")
        return SKIPPED

    missing = [r for r in roots if not Path(r).is_dir()]
    if missing:
        # A configured root that is not there is a MISCONFIGURATION, not
        # an empty corpus: silently sweeping the roots that do resolve
        # would report a clean sweep over a fraction of the documents.
        print("FAILED: configured corpus root(s) do not exist:")
        for root in missing:
            print(f"  {root}")
        return 1

    limit = args.limit or int(os.environ.get(LIMIT_ENV, "0") or 0)
    paths: list[Path] = []
    for root in roots:
        base = Path(root)
        paths.extend(sorted(p for p in base.rglob("*.docx")
                            if not SKIP.search(str(p))))
    if not paths:
        print(f"SKIPPED: no .docx under {', '.join(roots)}")
        return SKIPPED
    chosen = sample(paths, limit)
    if len(chosen) < len(paths):
        print(f"  ({len(chosen)} of {len(paths)} documents, strided)")
    if args.findings:
        # Read BEFORE the run: a bad path should cost a second, not the
        # ten minutes of a corpus.
        before = _load(args.diff[0]) if args.diff else None
        after = record_findings(chosen, args.findings, max(1, args.jobs),
                                roots=roots)
        if before is not None:
            diff_findings(before, after)
        return 0
    return sweep(chosen, args.slow)


def _load(path: Path) -> Record:
    record: Record = json.loads(path.read_text(encoding="utf-8"))
    return record


if __name__ == "__main__":
    sys.exit(main())
