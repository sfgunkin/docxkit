#!/usr/bin/env python
"""Old-vs-new oracle for `compare`, over real version PAIRS.

    python tools/pair_oracle.py [ROOTS...] [--base HEAD] [--limit N]
        [--bucket format] [--show 5] [--expect-same] [--jobs 4]

`sweep.py` reads one document at a time, and its only compare routine is
a document against ITSELF, so no corpus run could say what a change to a
layer that compares TWO documents does. `writer_oracle.py` probes the
writers. This is the third oracle: consecutive versions of one
manuscript, compared with the `base` revision's `src` and with the
working tree's, and every report bucket diffed as a multiset.

**Pairs.** Within one folder, the `.docx` files ordered by modification
time, each with the next one whose name matches once digits, dashes,
underscores, dots and spaces are dropped (`SequenceMatcher` ratio above
0.7) — the next of its OWN name, so another file saved in between does
not break the pair. Those are a manuscript's successive author rounds, which is where
a false alarm in a gated layer would come from. Redlines, tracked copies
and comparisons are left out (they are not versions), and so is what
`sweep.SKIP` leaves out. The sample is strided over the sorted pairs,
``--limit`` of them (``DOCXKIT_CORPUS_LIMIT``, else 40).

Filed as backlog S4 on 2026-11-19, after the batch that changed
`compare`'s FORMAT layer measured that change with three scratch scripts
of exactly this shape (240 pairs; 1,042, then 724 new entries).

Read-only: every manuscript is read, nothing is written. Differences are
REPORTED, not judged; ``--expect-same`` makes any exit 1. Exit 3 is
SKIPPED (no corpus), as `sweep.py` has it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKIPPED = 3
#: Not versions of a manuscript: a redline is two of them at once.
NOT_A_VERSION = re.compile(r"redline|tracked|compare", re.IGNORECASE)
_STEM_NOISE = re.compile(r"[\d_\-. ]+")

#: per pair "a -> b": {bucket: [entry as sorted JSON, ...]}, or an error
Answers = dict[str, dict[str, list[str]] | str]


def _stem(path: Path) -> str:
    return _STEM_NOISE.sub("", path.stem.lower())


def version_pairs(roots: list[str], *, skip: re.Pattern[str]
                  ) -> list[tuple[str, str]]:
    """Consecutive versions of one manuscript, per folder, by mtime."""
    pairs: list[tuple[str, str]] = []
    for root in roots:
        for folder, _dirs, files in os.walk(root):
            docs = [Path(folder, f) for f in files
                    if f.lower().endswith(".docx")
                    and not NOT_A_VERSION.search(f)
                    and not skip.search(str(Path(folder, f)))]
            docs.sort(key=lambda d: (d.stat().st_mtime, d.name))
            # each with the NEXT one of its own name: a cover letter
            # saved between two versions must not break their pair
            for k, a in enumerate(docs):
                nxt = next((b for b in docs[k + 1:] if SequenceMatcher(
                    None, _stem(a), _stem(b)).ratio() > 0.7), None)
                if nxt is not None:
                    pairs.append((str(a), str(nxt)))
    return sorted(pairs)


def stride(pairs: list[tuple[str, str]], limit: int
           ) -> list[tuple[str, str]]:
    """`limit` pairs spread evenly over the sorted list (all if fewer)."""
    if limit <= 0 or len(pairs) <= limit:
        return pairs
    step = len(pairs) / limit
    return [pairs[int(k * step)] for k in range(limit)]


# ---------------------------------------------------------------- worker --

def _compare_pair(pair: tuple[str, str]) -> tuple[str, dict[str, list[str]]
                                                  | str]:
    from docxkit import package  # noqa: PLC0415
    from docxkit.compare import compare_docs, load_parts  # noqa: PLC0415
    a, b = pair
    key = f"{a} -> {b}"
    try:
        report = compare_docs(load_parts(package.read_parts(a), a),
                              load_parts(package.read_parts(b), b))
    except Exception as exc:
        return key, f"error: {type(exc).__name__}: {exc}"[:200]
    return key, {bucket: sorted(json.dumps(e, sort_keys=True,
                                           ensure_ascii=False)
                                for e in entries)
                 for bucket, entries in report.items()}


def _use(src: str) -> None:
    sys.path.insert(0, src)


def worker(src: str, out: str, listing: str, jobs: int) -> int:
    """One side: compare every pair with `src` first on the path."""
    pairs = [tuple(p) for p in
             json.loads(Path(listing).read_text(encoding="utf-8"))]
    with ProcessPoolExecutor(jobs, initializer=_use,
                             initargs=(src,)) as pool:
        result = dict(pool.map(_compare_pair, pairs, chunksize=2))
    Path(out).write_bytes(json.dumps(result, ensure_ascii=False).encode())
    return 0


# ------------------------------------------------------------------ diff --

def diff(base: Answers, head: Answers
         ) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    """bucket -> [(pair, entries only head has, entries only base has)].

    A multiset per pair and bucket: one entry gained beside an identical
    one kept is still one gained. A pair either side could not compare
    files under ``"(error)"``."""
    out: dict[str, list[tuple[str, list[str], list[str]]]] = {}
    for key in sorted(set(base) | set(head)):
        b, h = base.get(key, {}), head.get(key, {})
        if isinstance(b, str) or isinstance(h, str):
            if b != h:
                out.setdefault("(error)", []).append(
                    (key, [str(h)], [str(b)]))
            continue
        for bucket in sorted(set(b) | set(h)):
            cb, ch = Counter(b.get(bucket, [])), Counter(h.get(bucket, []))
            new, gone = sorted((ch - cb).elements()), sorted(
                (cb - ch).elements())
            if new or gone:
                out.setdefault(bucket, []).append((key, new, gone))
    return out


def _side(src: Path, pairs: list[tuple[str, str]], out: Path,
          jobs: int) -> Answers:
    # paths in a FILE, as writer_oracle does: a command line past
    # 32,767 characters is refused on Windows (WinError 206)
    listing = out.with_suffix(".pairs.json")
    listing.write_text(json.dumps(pairs), encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(src), str(out), str(listing),
                    str(jobs)], check=True)
    loaded: Answers = json.loads(out.read_bytes())
    return loaded


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    if args_in[:1] == ["--worker"]:
        src, out, listing, jobs = args_in[1:]
        return worker(src, out, listing, int(jobs))

    sys.path.insert(0, str(HERE))
    import sweep  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    import writer_oracle  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

    from docxkit.console import utf8_stdout  # noqa: PLC0415
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Old-vs-new oracle for compare, over real version "
                    "pairs.")
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--bucket", action="append",
                    help="report only these buckets (default: all)")
    ap.add_argument("--show", type=int, default=5)
    ap.add_argument("--expect-same", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args(args_in)

    roots = sweep.corpus_roots(args.roots)
    if not roots:
        print(f"SKIPPED: no corpus — set {sweep.CORPUS_ENV} or pass roots")
        return SKIPPED
    limit = args.limit or int(os.environ.get(sweep.LIMIT_ENV) or 40)
    every = version_pairs(roots, skip=sweep.SKIP)
    chosen = stride(every, limit)
    if not chosen:
        print("SKIPPED: no version pairs under the roots")
        return SKIPPED
    with tempfile.TemporaryDirectory() as tmp:
        base_src = writer_oracle._extract(args.base, Path(tmp))
        base = _side(base_src, chosen, Path(tmp) / "base.json", args.jobs)
        head = _side(ROOT / "src", chosen, Path(tmp) / "head.json",
                     args.jobs)
    found = diff(base, head)
    if args.bucket:
        found = {k: v for k, v in found.items() if k in args.bucket}
    print(f"{len(chosen)} of {len(every)} version pairs; base {args.base} "
          f"vs the working tree")
    if not found:
        print("  no bucket differs")
    for bucket, rows in sorted(found.items()):
        new = sum(len(n) for _, n, _ in rows)
        gone = sum(len(g) for _, _, g in rows)
        print(f"  {bucket}: +{new} -{gone} entries in {len(rows)} pair(s)")
        for key, n, g in rows[:args.show]:
            a, b = key.split(" -> ")
            print(f"    {Path(a).name} -> {Path(b).name}")
            for e in n[:3]:
                print(f"      + {e[:160]}")
            for e in g[:3]:
                print(f"      - {e[:160]}")
    return 1 if args.expect_same and found else 0


if __name__ == "__main__":
    sys.exit(main())
