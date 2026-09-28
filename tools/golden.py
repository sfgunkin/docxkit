#!/usr/bin/env python
r"""Golden end-to-end fingerprints of real manuscripts.

    python tools/golden.py            # check every golden (exit 1 on a move)
    python tools/golden.py --update   # re-record them, after reading the diff

Real manuscripts found more S1/S2 defects than every gate together — 63
of 116 attributed product defects came from paper use — and until
2026-09-29 no test held one: every document in the suite is synthetic
(REVIEW_2026-09-28 §6). This holds a handful of FROZEN ones, archived
versions of finished papers, end to end: what the package READS from
each — text in both views, the markdown export, word counts, revision
kinds, the counts of tables, notes, comments, equations, captions,
links and bookmarks, the lint findings, the accepted view — as counts
and SHA-256 digests.

Digests, never content: this repository is public, and a golden file
that quoted a manuscript would publish it. `tools/golden.toml` holds the
corpus-relative path, the input's own digest, and the fingerprint. Only
the machine with the corpus can run it, so it SKIPS without
`DOCXKIT_CORPUS` (exit 3), as `sweep` and `consumers` do.

A changed fingerprint is not automatically a regression — a fix changes
what the package reads, which is the point of it. It is a demand to
LOOK: the report names the fields that moved, and `--update` records
the new answer once someone has decided it is the right one. An input
whose own digest changed is reported as MOVED: the golden no longer
describes that file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from docxkit import export, lint, revisions, wordcount  # noqa: E402
from docxkit._xml import (  # noqa: E402
    BOOKMARK_NAME_RE,
    DOCUMENT,
    FOOTNOTES,
    internal_links,
)
from docxkit.comments import read_all  # noqa: E402
from docxkit.console import utf8_stdout  # noqa: E402
from docxkit.crossrefs import find_captions  # noqa: E402
from docxkit.find import body_elements, table_spans  # noqa: E402
from docxkit.footnotes import find_all  # noqa: E402
from docxkit.package import read_parts  # noqa: E402
from docxkit.tracked import accepted_view  # noqa: E402

MANIFEST = ROOT / "tools" / "golden.toml"
CORPUS_ENV = "DOCXKIT_CORPUS"
SKIPPED = 3
_OMATH_RE = re.compile(r"<m:oMath(?=[\s>])")


def _digest(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()[:16]


def fingerprint(path: Path) -> dict[str, object]:
    """What the package reads from one manuscript, as counts and digests."""
    parts = read_parts(path)
    doc = parts[DOCUMENT].decode("utf-8")
    notes = parts[FOOTNOTES].decode("utf-8") if FOOTNOTES in parts else ""
    findings = lint.lint_parts(dict(parts))
    words = wordcount.count(dict(parts))
    return {
        "text_final": _digest("\n".join(revisions.text(doc, "final"))),
        "text_original": _digest("\n".join(revisions.text(doc, "original"))),
        "markdown": _digest(export.to_markdown(dict(parts))),
        "words": _digest(json.dumps(words.as_dict(), sort_keys=True)),
        "revision_kinds": _digest(json.dumps(revisions.revision_kinds(doc),
                                             sort_keys=True)),
        "accepted_document": _digest(accepted_view(dict(parts))[DOCUMENT]),
        "paragraphs": sum(1 for kind, _s, _e in body_elements(doc)
                          if kind == "p"),
        "tables": len(table_spans(doc)),
        "footnotes": len(find_all(notes)) if notes else 0,
        "comments": len(read_all(dict(parts))),
        "equations": len(_OMATH_RE.findall(doc)),
        "captions": len(find_captions(doc)),
        "links": len(internal_links(doc)),
        "bookmarks": len(BOOKMARK_NAME_RE.findall(doc)),
        "lint": len(findings),
        "lint_findings": _digest("\n".join(sorted(findings))),
    }


def _corpus() -> Path | None:
    value = os.environ.get(CORPUS_ENV, "")
    first = value.split(os.pathsep)[0].strip() if value else ""
    return Path(first) if first else None


def _load() -> list[dict[str, object]]:
    if not MANIFEST.is_file():
        return []
    with MANIFEST.open("rb") as fh:
        return list(tomllib.load(fh).get("golden", []))


def _toml_value(value: object) -> str:
    return str(value) if isinstance(value, int) else json.dumps(value)


def _write(entries: list[dict[str, object]]) -> None:
    lines = ["# Golden fingerprints of frozen manuscripts: written by",
             "# tools/golden.py --update, read by tools/golden.py. Counts",
             "# and SHA-256 prefixes only — this repository is public.", ""]
    for entry in entries:
        lines.append("[[golden]]")
        lines.append(f"path = {json.dumps(entry['path'])}")
        lines.append(f"input = {json.dumps(entry['input'])}")
        fields = entry.get("fingerprint", {})
        assert isinstance(fields, dict)
        lines.append("[golden.fingerprint]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in sorted(fields.items())]
        lines.append("")
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--update", action="store_true",
                    help="re-record every fingerprint (and input digest)")
    args = ap.parse_args(argv)
    corpus = _corpus()
    if corpus is None or not corpus.is_dir():
        print(f"SKIPPED: no corpus — set {CORPUS_ENV}; the goldens are "
              f"real manuscripts and live in it, not in this repository.")
        return SKIPPED
    entries = _load()
    if not entries:
        print(f"no goldens in {MANIFEST.name}")
        return 1
    moved = 0
    for entry in entries:
        rel = str(entry["path"])
        path = corpus / rel
        if not path.is_file():
            print(f"  GONE   {rel}")
            moved += 1
            continue
        got_input = _digest(path.read_bytes())
        got = fingerprint(path)
        if args.update:
            entry["input"], entry["fingerprint"] = got_input, got
            print(f"  recorded {rel}")
            continue
        if got_input != entry["input"]:
            print(f"  MOVED  {rel}: the file itself changed, so this golden "
                  f"no longer describes it — re-pin with --update")
            moved += 1
            continue
        want = entry.get("fingerprint", {})
        assert isinstance(want, dict)
        diff = sorted(k for k in set(want) | set(got)
                      if want.get(k) != got.get(k))
        if diff:
            print(f"  CHANGED {rel}")
            for key in diff:
                print(f"      {key}: {want.get(key)} -> {got.get(key)}")
            moved += 1
        else:
            print(f"  ok     {rel}")
    if args.update:
        _write(entries)
        print(f"wrote {MANIFEST.name}")
        return 0
    if moved:
        print(f"{moved} golden(s) moved. A fix changes what the package "
              f"reads; decide the new answer is right, then --update.")
        return 1
    print(f"{len(entries)} golden(s) unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
