#!/usr/bin/env python
"""Old-vs-new oracle for the accept/reject VIEWS, over real redlines.

    python tools/view_oracle.py [ROOT ...] [--base REV] [--limit N]
                                [--contains TEXT] [--word [moved|all]]
                                [--show K] [--expect-same]

"Measure a shape before changing a view" is the rule for `revisions`,
and until 2026-10-31 nothing implemented it: the session that processed
the latent shapes of the 2026-10-24 review hand-rolled four probes
(~300 lines) to do it, and the first of them measured NOTHING —
`_simulate_clean` is ``lru_cache``d on the XML, so a probe that
monkeypatched the engine and called `accept` again was handed the
cached unpatched view, and reported 0 changed views with full
confidence for a shape that changes two views of a real file.

So nothing here is patched and nothing shares a cache. The base
(default ``HEAD``) is extracted with ``git archive`` and the working
tree's ``src`` is the other side; each side computes, in its own
interpreters, the accepted and rejected view of every text part with a
tracked change (``word/document.xml``, notes, comments, headers,
footers) of every distinct redline under the roots (``DOCXKIT_CORPUS``
or the command line; byte-identical copies counted once). The views
are compared by hash, and a profile of each ``document.xml`` view is
kept for Word:

* ``objects`` — equation objects (`_xml.MATH_OBJECTS` as of 2026-10-31)
  and whole equations, by kind; ``shells`` — the same, holding no
  glyph, math runs included (Word re-splits runs, so only an EMPTY run
  is comparable);
* ``equations`` — every glyph of every equation, in order, joined.
  Word merges adjacent equations on Reject All, so a per-equation list
  differs where the maths does not;
* ``bookmarks`` — the names, sorted; ``text`` — a hash of every
  ``w:t`` of the body.

``--word`` (``moved``, the default, or ``all``) then asks Word itself:
Accept All and Reject All on a staged read-only copy, read through
``Content.WordOpenXML`` — nothing is saved — profiled the same way, and
each profile field reported as which side agrees with Word. Word is
slow (two opens a file), so ``--contains`` narrows the corpus to parts
holding a substring, e.g. ``--contains "ctrlPr><w:ins"``.

Read-only. Differences are REPORTED, not judged — a fix is supposed to
change views; ``--expect-same`` makes any difference exit 1, for a
refactor that claims to change none. Exit 3 is SKIPPED (no corpus), as
`sweep.py` has it.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKIPPED = 3
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
PKG = "{http://schemas.microsoft.com/office/2006/xmlPackage}"
PART_RE = re.compile(r"^word/(document|footnotes|endnotes|comments"
                     r"|header\d*|footer\d*)\.xml$")
#: A tracked change of any kind — a base that predates `_has_revisions`
#: must answer the same question.
REVISION_RE = re.compile(r"<w:(?:ins|del|moveFrom|moveTo|rPrChange|pPrChange"
                         r"|sectPrChange|tblPrChange|trPrChange|tcPrChange"
                         r"|tblGridChange|numberingChange)\b")
#: Equation objects, as `_xml.MATH_OBJECTS` lists them on 2026-10-31 —
#: math runs (``r``) included, which the prune removes too — and whole
#: equations (``oMath``). Fixed here, not imported, so both sides profile
#: the same kinds.
OBJECTS = ("acc", "bar", "borderBox", "box", "d", "eqArr", "f", "func",
           "groupChr", "limLow", "limUpp", "m", "nary", "oMath", "phant",
           "r", "rad", "sPre", "sSub", "sSubSup", "sSup")
#: Counted as shells only: Word re-splits math runs as it writes, so
#: the NUMBER of runs differs from the engine's where nothing else does
#: (38 of 47 accepted views, 2026-10-31); an EMPTY one is still a fact.
SHELL_ONLY = frozenset({"r"})
VIEWS = ("accept", "reject")

Profile = dict[str, Any]
#: file -> "part|view" -> [sha1 or "ERROR ...", profile or None]
Views = dict[str, dict[str, list[Any]]]


# --------------------------------------------------------------- profile --


def profile(root: Any) -> Profile:
    """What Word and the engine are compared on, for one document view."""
    body = root if root.tag == W + "body" else root.find(W + "body")
    if body is None:
        body = root
    objects: Counter[str] = Counter()
    shells: Counter[str] = Counter()
    for kind in OBJECTS:
        for el in body.iter(M + kind):
            if kind not in SHELL_ONLY:
                objects[kind] += 1
            if not any(t.text for t in el.iter(M + "t")):
                shells[kind] += 1
    text = "".join(t.text or "" for t in body.iter(W + "t"))
    return {
        "objects": dict(sorted(objects.items())),
        "shells": dict(sorted(shells.items())),
        "equations": "".join(t.text or "" for t in body.iter(M + "t")),
        "bookmarks": sorted(b.get(W + "name") or ""
                            for b in body.iter(W + "bookmarkStart")),
        "text": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
    }


def profile_xml(xml: str) -> Profile:
    from lxml import etree  # noqa: PLC0415
    return profile(etree.fromstring(xml.encode("utf-8")))


# ---------------------------------------------------------------- worker --
# Run in the side's own interpreters, after `sys.path` names its `src`.


def _init(src: str) -> None:
    sys.path.insert(0, src)


def views_of(path: str, contains: str = "") -> tuple[str, dict[str, list[Any]]]:
    """Every view of every revised text part of one redline."""
    from docxkit import revisions as rv  # noqa: PLC0415
    out: dict[str, list[Any]] = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(Path(path).read_bytes()))
    except Exception as exc:
        return path, {"_": [f"ERROR unreadable: {type(exc).__name__}", None]}
    for name in z.namelist():
        if not PART_RE.match(name):
            continue
        try:
            xml = z.read(name).decode("utf-8")
        except Exception:
            continue
        if not REVISION_RE.search(xml) or (contains and contains not in xml):
            continue
        for view in VIEWS:
            try:
                got = getattr(rv, view)(xml)
            except Exception as exc:
                out[f"{name}|{view}"] = [
                    f"ERROR {type(exc).__name__}: {exc}"[:200], None]
                continue
            prof = (profile_xml(got) if name == "word/document.xml"
                    else None)
            out[f"{name}|{view}"] = [
                hashlib.sha1(got.encode("utf-8")).hexdigest(), prof]
    return path, out


def worker(src: str, listing: str, out: str, contains: str) -> int:
    """One side: the views of every listed file, in parallel."""
    files: list[str] = json.loads(Path(listing).read_bytes())
    result: Views = {}
    jobs = max(1, min(len(files), (os.cpu_count() or 2) - 2))
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init,
                             initargs=(src,)) as ex:
        for path, views in ex.map(views_of, files,
                                  [contains] * len(files), chunksize=4):
            if views:
                result[path] = views
    Path(out).write_bytes(json.dumps(result, ensure_ascii=False).encode())
    return 0


# ------------------------------------------------------------------ diff --


def diff(base: Views, head: Views) -> list[tuple[str, str]]:
    """(file, "part|view") wherever the two sides' views differ."""
    out = []
    for f in sorted(set(base) | set(head)):
        b, h = base.get(f, {}), head.get(f, {})
        for key in sorted(set(b) | set(h)):
            if (b.get(key) or [None])[0] != (h.get(key) or [None])[0]:
                out.append((f, key))
    return out


def judge(base: Profile | None, head: Profile | None,
          word: Profile) -> dict[str, str]:
    """Per profile field: which side Word agrees with."""
    verdict = {}
    for field in word:
        b = None if base is None else base.get(field)
        h = None if head is None else head.get(field)
        w = word[field]
        verdict[field] = ("both" if b == w and h == w else
                          "head" if h == w else
                          "base" if b == w else "neither")
    return verdict


# ------------------------------------------------------------------ word --


def word_profiles(path: str) -> dict[str, Profile]:
    """Word's Accept All and Reject All of `path`, profiled. Nothing saved."""
    from lxml import etree  # noqa: PLC0415

    from docxkit import word as _word  # noqa: PLC0415
    out: dict[str, Profile] = {}
    with _word.session(deadline=300, doing=f"view oracle {Path(path).name}"
                       ) as app:
        for view in VIEWS:
            with _word.open_doc(app, path) as doc:
                if view == "accept":
                    doc.AcceptAllRevisions()
                else:
                    doc.RejectAllRevisions()
                flat = etree.fromstring(
                    doc.Content.WordOpenXML.encode("utf-8"))
            for part in flat.iter(PKG + "part"):
                if part.get(PKG + "name") == "/word/document.xml":
                    out[view] = profile(next(part.iter(W + "document")))
    return out


def ask_word(files: list[str], base: Views, head: Views,
             show: int) -> Counter[str]:
    """Word's verdict on each file's document views; a tally by field."""
    tally: Counter[str] = Counter()
    for f in files:
        try:
            theirs = word_profiles(f)
        except Exception as exc:
            print(f"    {Path(f).name}: Word failed: {exc!r}"[:200])
            tally["word failed"] += 1
            continue
        for view in VIEWS:
            key = f"word/document.xml|{view}"
            b = (base.get(f, {}).get(key) or [None, None])[1]
            h = (head.get(f, {}).get(key) or [None, None])[1]
            if view not in theirs or (b is None and h is None):
                continue
            verdict = judge(b, h, theirs[view])
            for field, who in verdict.items():
                tally[f"{view} {field}: {who}"] += 1
            off = {k: v for k, v in verdict.items() if v != "both"}
            if off and show:
                print(f"    {Path(f).name} {view}: {off}")
                for field in off:
                    if field in ("objects", "shells"):
                        print(f"      {field}  base {b and b[field]}  "
                              f"head {h and h[field]}  "
                              f"word {theirs[view][field]}")
    return tally


# ------------------------------------------------------------------ main --


def _extract(rev: str, into: Path) -> Path:
    """`rev`'s `src` tree, via git archive, under `into`."""
    import tarfile  # noqa: PLC0415
    tar = into / "src.tar"
    with tar.open("wb") as fh:
        subprocess.run(["git", "-C", str(ROOT), "archive", rev, "src"],
                       stdout=fh, check=True)
    with tarfile.open(tar) as t:
        t.extractall(into, filter="data")
    return into / "src"


def _side(src: Path, listing: Path, out: Path, contains: str) -> Views:
    subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(src), str(listing), str(out), contains],
                   check=True)
    loaded: Views = json.loads(out.read_bytes())
    return loaded


def distinct(paths: list[Path]) -> list[str]:
    """One path per distinct content: the corpus holds copies."""
    seen: set[str] = set()
    out = []
    for p in paths:
        try:
            sha = hashlib.sha1(p.read_bytes()).hexdigest()
        except OSError:
            continue
        if sha not in seen:
            seen.add(sha)
            out.append(str(p))
    return out


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    if args_in[:1] == ["--worker"]:
        src, files_json, out, contains = args_in[1:5]
        return worker(src, files_json, out, contains)

    sys.path.insert(0, str(HERE))
    import sweep  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

    from docxkit.console import utf8_stdout  # noqa: PLC0415
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Old-vs-new oracle for the accept/reject views, over "
                    "real redlines.")
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--contains", default="")
    ap.add_argument("--word", nargs="?", const="moved",
                    choices=("moved", "all"))
    ap.add_argument("--show", type=int, default=5)
    ap.add_argument("--expect-same", action="store_true")
    args = ap.parse_args(args_in)

    roots = sweep.corpus_roots(args.roots)
    if not roots:
        print(f"SKIPPED: no corpus — set {sweep.CORPUS_ENV} or pass roots")
        return SKIPPED
    limit = args.limit or int(os.environ.get(sweep.LIMIT_ENV, "0") or 0)
    paths = sorted(p for root in roots for p in Path(root).rglob("*.docx")
                   if not sweep.SKIP.search(str(p)))
    chosen = distinct(sweep.sample(paths, limit))
    if not chosen:
        print("SKIPPED: no .docx under the roots")
        return SKIPPED
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "files.json"
        listing.write_text(json.dumps(chosen), encoding="utf-8")
        base_src = _extract(args.base, Path(tmp))
        base = _side(base_src, listing, Path(tmp) / "base.json",
                     args.contains)
        head = _side(ROOT / "src", listing, Path(tmp) / "head.json",
                     args.contains)
    moved = diff(base, head)
    views = sum(len(v) for v in head.values())
    print(f"{len(head)} redlines of {len(chosen)} distinct documents, "
          f"{views} views; base {args.base} vs the working tree")
    for view in VIEWS:
        n = sum(1 for _, key in moved if key.endswith("|" + view))
        print(f"  {view}: {n} views differ")
    errors = sorted({(f, k) for side in (base, head) for f, v in side.items()
                     for k, (h, _) in v.items() if str(h).startswith("ERROR")})
    if errors:
        print(f"  {len(errors)} views raised (either side)")
    moved_files = sorted({f for f, _ in moved})
    print(f"  {len(moved_files)} files moved")
    for f, key in moved[:args.show]:
        print(f"    {Path(f).name} {key}")
    if args.word:
        ask = moved_files if args.word == "moved" else sorted(head)
        print(f"Word: Accept All / Reject All of {len(ask)} files")
        tally = ask_word(ask, base, head, args.show)
        for line, n in sorted(tally.items()):
            print(f"  {line}: {n}")
    return 1 if args.expect_same and moved else 0


if __name__ == "__main__":
    sys.exit(main())
