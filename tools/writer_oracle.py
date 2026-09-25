#!/usr/bin/env python
"""Old-vs-new oracle for the WRITERS, over real manuscripts.

    python tools/writer_oracle.py [ROOT ...] [--base REV] [--limit N]
                                  [--probe NAME ...] [--show K]
                                  [--expect-same]

`sweep.py` runs the READERS over the corpus; a writer change had nothing
that runs it across real documents against the commit before it. Each
fix hand-rolled its own: the 2026-09-24 review wrote `real_insert.py`
(insert before every hoisted head bookmark, count the stranded) and
2026-09-25 wrote `cell_probe.py` (rewrite every cell with its own text
under HEAD and under the fix). Both found what the unit tests could not —
the first `insert_before` fix had been checked on captions only, and 220
of 327 reference-entry bookmarks were still stranded.

The base (default ``HEAD``) is extracted with ``git archive`` into a
temporary directory and the working tree's ``src`` is the other side;
each side runs the same PROBES in its own interpreter, over the same
strided sample (`sweep.sample`, ``DOCXKIT_CORPUS`` / ``--limit``), and
the answers are diffed key by key. Every probe is an IDEMPOTENT write
whose answer should not change unless the writer did:

* ``set_cell`` — every cell rewritten with its own text: the refusal, or
  each line's runs as (text, superscript, italic).
* ``insert_before`` — a probe paragraph inserted before every paragraph
  that a run of body-level markers precedes: which bookmark names end up
  in front of the probe (stranded) rather than behind it.

Read-only: every manuscript is read into memory, nothing is written.
Differences are REPORTED, not judged — a fix is supposed to change
something; ``--expect-same`` makes any difference exit 1, for a
refactor that claims to change nothing. Exit 3 is SKIPPED (no corpus),
as `sweep.py` has it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKIPPED = 3
PROBE_PARA = "<w:p><w:r><w:t>WRITER ORACLE PROBE</w:t></w:r></w:p>"

Answers = dict[str, str]


# ---------------------------------------------------------------- probes --
# Run in the WORKER, after `sys.path` names the side's own `src`. They
# import only names both sides have had for months, so an old base can
# answer the same questions.


def _runs_signature(xml: str) -> str:
    from docxkit._xml import PARA_RE, RUN_RE, visible_text  # noqa: PLC0415
    lines = []
    for p in PARA_RE.finditer(xml):
        runs = []
        for r in RUN_RE.finditer(p.group(0)):
            text = visible_text(r.group(0))
            if text.strip():
                run = r.group(0)
                runs.append([text, 'w:val="superscript"' in run,
                             bool(re.search(r'<w:i(?: w:val="(?:1|true)")?/>',
                                            run))])
        lines.append(runs)
    return json.dumps(lines, ensure_ascii=False)


def probe_set_cell(xml: str) -> Answers:
    """Every cell rewritten with its own text."""
    from docxkit import tables  # noqa: PLC0415
    from docxkit._xml import element_spans  # noqa: PLC0415
    out: Answers = {}
    for t in tables.read_all(xml):
        for r, row in enumerate(t.rows):
            for c, text in enumerate(row):
                key = f"table {t.index} row {r} cell {c}"
                try:
                    new = tables.set_cell(xml, t, r, c, text)
                except Exception as exc:
                    out[key] = (f"refused: {type(exc).__name__}: "
                                f"{str(exc)[:60]}")
                    continue
                seg = new[t.start:t.end + len(new) - len(xml)]
                trs = element_spans(seg, "tr")
                if r >= len(trs):
                    out[key] = "row not found"
                    continue
                tr = seg[trs[r][0]:trs[r][1]]
                tcs = element_spans(tr, "tc")
                out[key] = (_runs_signature(tr[tcs[c][0]:tcs[c][1]])
                            if c < len(tcs) else "cell not found")
    return out


_GAP_RE = re.compile(
    r"</w:p>((?:\s*<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart"
    r"|commentRangeEnd|permStart|permEnd|proofErr)\b[^<>]*/>)+)\s*(?=<w:p\b)")
_NAME_RE = re.compile(r'<w:bookmarkStart\b[^>]*w:name="([^"]+)"')


def probe_insert_before(xml: str) -> Answers:
    """A probe paragraph before each paragraph a marker run precedes."""
    from docxkit._xml import PARA_RE, visible_text  # noqa: PLC0415
    from docxkit.body import insert_before  # noqa: PLC0415
    out: Answers = {}
    for gap in _GAP_RE.finditer(xml):
        names = _NAME_RE.findall(gap.group(1))
        para = PARA_RE.match(xml, gap.end())
        if not names or para is None:
            continue
        sig = visible_text(para.group(0)).strip()[:60]
        if len(sig) < 12:
            continue
        key = f"before {sig[:40]!r}"
        try:
            new = insert_before(xml, sig, PROBE_PARA)
        except Exception as exc:
            out[key] = f"refused: {type(exc).__name__}"
            continue
        at = new.index(PROBE_PARA)
        stranded = sorted(n for n in names
                          if new.find(f'w:name="{n}"') < at)
        out[key] = f"stranded {stranded}" if stranded else "kept"
    return out


PROBES: dict[str, Callable[[str], Answers]] = {
    "set_cell": probe_set_cell,
    "insert_before": probe_insert_before,
}


def worker(src: str, out: str, probes: list[str], files: list[str]) -> int:
    """One side: run the probes over the files with `src` first on path."""
    sys.path.insert(0, src)
    result: dict[str, dict[str, Answers]] = {}
    for f in files:
        try:
            xml = zipfile.ZipFile(f).read("word/document.xml").decode("utf-8")
        except Exception as exc:
            result[f] = {"_": {"unreadable": type(exc).__name__}}
            continue
        result[f] = {}
        for name in probes:
            try:
                result[f][name] = PROBES[name](xml)
            except Exception as exc:
                result[f][name] = {"_probe": f"crashed: {exc!r}"[:200]}
    Path(out).write_bytes(json.dumps(result, ensure_ascii=False).encode())
    return 0


# ------------------------------------------------------------------ diff --


def diff(base: dict[str, dict[str, Answers]],
         head: dict[str, dict[str, Answers]]
         ) -> dict[str, list[tuple[str, str, str | None, str | None]]]:
    """probe -> [(file, key, base answer, head answer)] where they differ."""
    out: dict[str, list[tuple[str, str, str | None, str | None]]] = {}
    for f in sorted(set(base) | set(head)):
        b, h = base.get(f, {}), head.get(f, {})
        for probe in sorted(set(b) | set(h)):
            pb, ph = b.get(probe, {}), h.get(probe, {})
            for key in sorted(set(pb) | set(ph)):
                if pb.get(key) != ph.get(key):
                    out.setdefault(probe, []).append(
                        (f, key, pb.get(key), ph.get(key)))
    return out


def _extract(rev: str, into: Path) -> Path:
    """`rev`'s `src` tree, via git archive, under `into`."""
    tar = into / "src.tar"
    with tar.open("wb") as fh:
        subprocess.run(["git", "-C", str(ROOT), "archive", rev, "src"],
                       stdout=fh, check=True)
    with tarfile.open(tar) as t:
        t.extractall(into, filter="data")
    return into / "src"


def _side(src: Path, probes: list[str], files: list[str],
          out: Path) -> dict[str, dict[str, Answers]]:
    subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(src), str(out), ",".join(probes),
                    *files], check=True)
    loaded: dict[str, dict[str, Answers]] = json.loads(out.read_bytes())
    return loaded


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    if args_in[:1] == ["--worker"]:
        src, out, names, *files = args_in[1:]
        return worker(src, out, names.split(","), files)

    sys.path.insert(0, str(HERE))
    import sweep  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

    from docxkit.console import utf8_stdout  # noqa: PLC0415
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Old-vs-new oracle for the writers, over real "
                    "manuscripts.")
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--probe", action="append", choices=sorted(PROBES))
    ap.add_argument("--show", type=int, default=5)
    ap.add_argument("--expect-same", action="store_true")
    args = ap.parse_args(args_in)

    roots = sweep.corpus_roots(args.roots)
    if not roots:
        print(f"SKIPPED: no corpus — set {sweep.CORPUS_ENV} or pass roots")
        return SKIPPED
    limit = args.limit or int(os.environ.get(sweep.LIMIT_ENV, "0") or 40)
    paths = sorted(p for root in roots for p in Path(root).rglob("*.docx")
                   if not sweep.SKIP.search(str(p)))
    chosen = [str(p) for p in sweep.sample(paths, limit)]
    if not chosen:
        print("SKIPPED: no .docx under the roots")
        return SKIPPED
    probes = args.probe or sorted(PROBES)
    with tempfile.TemporaryDirectory() as tmp:
        base_src = _extract(args.base, Path(tmp))
        base = _side(base_src, probes, chosen, Path(tmp) / "base.json")
        head = _side(ROOT / "src", probes, chosen, Path(tmp) / "head.json")
    found = diff(base, head)
    print(f"{len(chosen)} of {len(paths)} documents; base {args.base} vs "
          f"the working tree")
    for probe in probes:
        answers = sum(len(v.get(probe, {})) for v in head.values())
        rows = found.get(probe, [])
        print(f"  {probe}: {answers} answers, {len(rows)} differ")
        for f, key, b, h in rows[:args.show]:
            print(f"    {Path(f).name} {key}\n      base: {b}\n      "
                  f"head: {h}")
    return 1 if args.expect_same and found else 0


if __name__ == "__main__":
    sys.exit(main())
