#!/usr/bin/env python
r"""What the papers actually import from docxkit — the consumer contract.

    python tools/consumers.py            # refresh tools/consumers.txt
    python tools/consumers.py --check    # exit 1 if the file is stale

`__all__` declares 626 names across 35 modules. The nine papers on this
machine — 274 scripts — use 86 of them (measured 2026-09-01), and 103 of
those imports reach into `docxkit._xml`, a module private by name. That
gap is the difference between what the package OFFERS and what it has
PROMISED, and nothing recorded the second half: `test_api_surface` pins
that a name is listed, `api_check` guards every listed name equally, and
neither knows which names a consumer is written against.

This writes the second half down. It walks the same roots `DOCXKIT_CORPUS`
names for the manuscript sweep — the scripts live beside the manuscripts
— for every `from docxkit… import …` and records `(module, name)` pairs,
one per line, sorted, into `tools/consumers.txt`. That file is COMMITTED,
so the tests and the `api` gate that read it run anywhere, and it is
refreshed here when the papers move.

Two readers: `tests/test_consumers.py` asserts every pair still resolves
and that the private-path imports are a known, shrinking set; and
`tools/api_check.py` treats a breakage in a consumed name as BREAKING
and one elsewhere in the public surface as advisory.

Without a corpus it exits 3, like the sweep, and for the same reason: a
consumer list refreshed over zero scripts would be an empty promise that
reads as a kept one.
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from docxkit.console import utf8_stdout  # noqa: E402

SNAPSHOT = ROOT / "tools" / "consumers.txt"
CORPUS_ENV = "DOCXKIT_CORPUS"
SKIPPED = 3

#: `from docxkit.edit import replace_in_para, rep` and the bare
#: `from docxkit import read_parts`. A parenthesised multi-line import is
#: matched across lines by the DOTALL group, closed at the `)`.
_IMPORT_RE = re.compile(
    r"^from (docxkit(?:\.[a-z_]+)*) import (\([^)]*\)|[^\n#]+)",
    re.MULTILINE)
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: The header the snapshot carries, so a reader of the file knows what
#: it is without opening this module.
HEADER = (
    "# What the papers import from docxkit: one `module<TAB>name` per line.\n"
    "# Written by tools/consumers.py; read by tests/test_consumers.py and\n"
    "# tools/api_check.py. Refresh it when the papers move, never by hand.\n")


def roots(argv_roots: list[str]) -> list[Path]:
    if argv_roots:
        return [Path(r) for r in argv_roots]
    raw = os.environ.get(CORPUS_ENV, "")
    return [Path(r) for r in raw.split(os.pathsep) if r.strip()]


def scan(folders: list[Path]) -> set[tuple[str, str]]:
    """Every `(module, name)` the scripts under `folders` import."""
    found: set[tuple[str, str]] = set()
    for folder in folders:
        for script in folder.rglob("*.py"):
            if "__pycache__" in script.parts:
                continue
            try:
                text = script.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for module, names in _IMPORT_RE.findall(text):
                for name in _NAME_RE.findall(names.strip("()")):
                    if name == "as":
                        continue
                    found.add((module, name))
    # `x as y` leaves `y` in the match too; drop the alias by keeping
    # only names that follow `import` or a comma — cheaper to do here
    # than in the pattern, and measured against the corpus: the aliases
    # papers use (`utf8_stdout as _stdout`) never collide with a real
    # name in the same statement.
    return {(m, n) for m, n in found if not _is_alias_target(m, n)}


def _is_alias_target(module: str, name: str) -> bool:
    """Is `name` only ever the RIGHT side of an `as`?

    Cheap and honest: an alias target is a LOCAL spelling
    (`utf8_stdout as _stdout`), and a local spelling is one that does
    not resolve in the module it was imported from. A submodule counts
    as resolving — `from docxkit import body` is a real import, and
    `hasattr(docxkit, "body")` is False until something imports it.
    """
    try:
        mod = importlib.import_module(module)
    except ImportError:
        return False
    if hasattr(mod, name):
        return False
    try:
        importlib.import_module(f"{module}.{name}")
    except ImportError:
        return True
    return False


#: What marks a script as SPENT — `revision._doctor`'s own word for it,
#: widened to the archive folders the papers use. A spent builder is the
#: RECORD of a round that ran, not a script anybody will run again.
#:
#: This matters for the private-path list. Measured 2026-09-02: of the
#: names the papers reach into `_xml` and the citation halves for, SIX
#: are imported only by spent builders — `set_run_text`,
#: `own_properties`, `RUN_RE`, `_cite_repair.field_spans` and both
#: `_table_layout` entries. Reading them as work to do sends somebody to
#: migrate a file that will never run, and under the forward-only rule
#: editing one falsifies the record. What is actionable is the LIVE
#: half, and it was seven files.
SPENT_MARKERS = ("applied", "archive", "_archive", "Archive", "Arichive",
                 "attic", "replication")


def live_private(folders: list[Path]) -> set[tuple[str, str]]:
    """Private imports made by a script that can still be run.

    The other half of `scan`'s answer. A name is live here if ANY
    non-spent script imports it; one spent copy does not retire a name
    another script still reaches for.
    """
    live: set[tuple[str, str]] = set()
    for folder in folders:
        for script in folder.rglob("*.py"):
            if "__pycache__" in script.parts:
                continue
            if any(part in SPENT_MARKERS for part in script.parts):
                continue
            try:
                text = script.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for module, names in _IMPORT_RE.findall(text):
                if not module.split(".")[-1].startswith("_"):
                    continue
                for name in _NAME_RE.findall(names.strip("()")):
                    if name != "as":
                        live.add((module, name))
    return live


def render(pairs: set[tuple[str, str]]) -> str:
    return HEADER + "".join(f"{m}\t{n}\n" for m, n in sorted(pairs))


def load(path: Path = SNAPSHOT) -> set[tuple[str, str]]:
    """The committed snapshot, as pairs."""
    out: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        module, name = line.split("\t")
        out.add((module, name))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="what the papers import from docxkit")
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed snapshot is stale")
    args = ap.parse_args()

    folders = roots(args.roots)
    if not folders:
        print(f"SKIPPED: no corpus — set {CORPUS_ENV} to the manuscript "
              f"root(s); the paper scripts live beside the manuscripts.")
        return SKIPPED
    missing = [f for f in folders if not f.is_dir()]
    if missing:
        print("FAILED: root(s) do not exist: "
              + ", ".join(str(m) for m in missing))
        return 1

    pairs = scan(folders)
    text = render(pairs)
    modules = {m for m, _ in pairs}
    private = sorted({(m, n) for m, n in pairs
                      if m.split(".")[-1].startswith("_")})
    live = live_private(folders)
    print(f"{len(pairs)} distinct imports across {len(modules)} modules, "
          f"{len(private)} through a private path "
          f"({len(live)} of them from a script that can still run)")
    for m, n in private:
        where = "LIVE   " if (m, n) in live else "spent  "
        print(f"  {where} private: from {m} import {n}")

    if args.check:
        current = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.is_file() else ""
        if current != text:
            print(f"STALE: {SNAPSHOT.name} does not match the papers — "
                  f"run tools/consumers.py to refresh it")
            return 1
        print(f"{SNAPSHOT.name} is current")
        return 0

    SNAPSHOT.write_text(text, encoding="utf-8")
    print(f"wrote {SNAPSHOT}")
    return 0


if __name__ == "__main__":                  # pragma: no cover
    utf8_stdout()
    raise SystemExit(main())
