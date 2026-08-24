#!/usr/bin/env python
"""Re-check every argued equivalence in `tools/equivalents.toml`.

    python tools/verify_equivalents.py
    python tools/verify_equivalents.py refstyle.py

A claim there says a mutation changes the source and cannot change
behaviour. `mutation_survivors` takes those out of the denominator, so a
claim that is WRONG quietly improves the module's figure — which is the
one direction of error nobody notices, because the number moves the way
everyone hoped.

So each one is applied for real and expected to SURVIVE. A claim that is
now killed has not been vindicated: the code or the harness moved and the
argument no longer describes them. Delete it, read the mutant again, and
decide it afresh.

This runs the harness once per claim, in `kill_check`'s private
worktree. It is a minutes-long job, not a gate — CONTRIBUTING calls for
it after a module the claims touch has changed.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_map import harness_for  # pyright: ignore[reportMissingImports]
from kill_check import check  # pyright: ignore[reportMissingImports]

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "tools" / "equivalents.toml"


def anchored(src: Path, stripped: str) -> str | None:
    """The claim's line as it appears in the file, indentation and all.

    A claim stores its lines stripped, because that is how
    `mutation_survivors.became` renders a mutant and the two have to
    match on sight. `kill_check` needs the real text: it insists the
    anchor occur EXACTLY once, and a stripped line either misses (the
    file has indentation) or hits several places at once.
    """
    hits = [ln for ln in src.read_text(encoding="utf-8").splitlines()
            if ln.strip() == stripped]
    return hits[0] if len(hits) == 1 else None


def main() -> int:
    utf8_stdout()
    if not CLAIMS.exists():
        print(f"no claims file at {CLAIMS}")
        return 0
    with CLAIMS.open("rb") as fh:
        doc = tomllib.load(fh)
    only = sys.argv[1] if len(sys.argv) > 1 else None

    bad = 0
    for module, entry in sorted(doc.items()):
        if only and module != only:
            continue
        src = ROOT / "src" / "docxkit" / module
        if not src.is_file():
            print(f"MODULE GONE  {module} — its claims describe nothing")
            bad += 1
            continue
        cases = []
        for claim in entry.get("claims", ()):
            old = anchored(src, claim["was"])
            if old is None:
                # Not a failure of the argument — a failure to FIND what
                # it was about, which is the same thing for a reader and
                # must not pass quietly as "survived, as claimed".
                print(f"ANCHOR GONE  {module}: {claim['was'][:60]!r} is no "
                      f"longer a line of that file, or is now several")
                bad += 1
                continue
            indent = old[:len(old) - len(old.lstrip())]
            cases.append((f"{claim['was'][:40]} -> {claim['line'][:40]}",
                          old, indent + claim["line"], False))
        if not cases:
            continue
        print(f"\n--- {module}: {len(cases)} claim(s)")
        check(f"src/docxkit/{module}", harness_for(module), cases)
    if bad:
        print(f"\n{bad} claim(s) could not be checked at all — see above")
    return 1 if bad else 0


if __name__ == "__main__":                  # pragma: no cover
    raise SystemExit(main())
