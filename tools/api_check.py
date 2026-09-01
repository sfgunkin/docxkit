#!/usr/bin/env python
r"""Did this change BREAK the API the papers import?

    python tools/api_check.py [--against REF]

`test_api_surface.py` pins that a public name is LISTED. It cannot see a
signature move under a name that is still there — and that is the change
which reaches a paper silently: nine manuscripts on this machine import
`docxkit` from an editable install, so they get the tip, and a renamed
parameter is an error at the next round rather than at the edit.

griffe loads the package twice — once from a git ref, once from the
working tree — and reports what a caller would notice.

**Not every finding it reports is a break, and that was measured before
this gate existed.** Over the last fourteen commits griffe reports
**21 findings, every one of them `ATTRIBUTE_CHANGED_VALUE`, and not one
breaking**: a member added to `GATED`, a slot added to `Para`, a slot
added to `Cascade`. All additive, none breaks a caller — and the CLI
exits non-zero on them, so wired raw this gate would have been RED on
half of that history for the ordinary act of adding a member to a data
table. This package's public constants ARE data tables (`GATED`,
`STRUCTURE_TAGS`, `VOLATILE_FIELDS`, `PPR_ORDER`, `CARRIED_PARTS`), and
a gate that reddens whenever one grows is a gate people learn to push
past — CONTRIBUTING's "measure a proposed CHECK before writing it",
applied before the check shipped rather than after.

So the eleven kinds that break a CALL fail the gate, and the value of a
constant is REPORTED under its own heading. Both are printed either
way: the split decides the exit code, not what the reader is shown.

**The baseline is named in the output, always.** A comparison against
nothing and a comparison against the last release print the same word
otherwise — the `sweep` lesson, in the gate beside it. With no tag and
no upstream there IS no baseline, and this exits 3 (`skip`) rather than
inventing one.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import consumers as _consumers  # noqa: E402  # pyright: ignore[reportMissingImports]

from docxkit.console import utf8_stdout  # noqa: E402

PACKAGE = "docxkit"
SEARCH = str(ROOT / "src")
#: The same directory, spelled relative — what `load_git` needs. See
#: :func:`compare`.
SRC_REL = "src"

#: A gate's way of saying "I did not run, and here is why" — the same
#: third state `tools/sweep.py` uses, for the same reason.
SKIPPED = 3

#: The one kind that does not break a call. A module-level constant
#: whose value changed is worth SEEING — it is how `GATED` gaining a
#: layer shows up, and a paper reading `compare.GATED` really is
#: affected — but a caller's code still runs, and this package edits
#: such tables as ordinary work.
ADVISORY = {"ATTRIBUTE_CHANGED_VALUE"}

#: What the papers actually import, from `tools/consumers.txt` — 128
#: names of the 626 `__all__` declares (2026-09-01).
#:
#: **The tier the 2026-09-01 review asked for.** Guarding all 626
#: equally makes an internal rename cost a release, and the gate is then
#: something to be got past rather than read; guarding none is what let
#: `test_api_surface` pass while a signature moved under a name a paper
#: calls. So a breakage in a CONSUMED name fails, and one elsewhere in
#: the public surface is reported — the same split this file already
#: makes for a constant's value, along the other axis.
#:
#: The list is derived from the papers rather than chosen, so nothing a
#: paper uses can be classed advisory by an oversight, and it is
#: refreshed by `tools/consumers.py` when the papers move.
def consumed(pkg: Any) -> set[str]:
    """Definition paths of every name a paper imports.

    Resolved through the aliases, because the two ends are spelled
    differently: a paper imports `docxkit.tables.house` and griffe
    reports a breakage at `docxkit._table_core.house`, where the
    function is DEFINED. Matching the strings as written would put
    every facade name in the advisory tier — which is most of the
    package, and exactly the names a paper calls.

    A wholesale `from docxkit import body` contributes the module's own
    path and not every name in it: removing the module is breaking, and
    the names inside it are guarded when a paper is measured importing
    them. Widening that would return the whole surface to the strict
    tier by another route.
    """
    try:
        pairs = _consumers.load()
    except (OSError, ValueError):
        # No snapshot: guard EVERYTHING. The gate falling back to
        # strict is the safe direction — a missing consumer list must
        # not quietly turn a breakage into a note.
        return set()
    out: set[str] = set()
    for module, name in pairs:
        key = f"{module}.{name}".removeprefix("docxkit.")
        try:
            obj = pkg[key]
        except (KeyError, AttributeError):
            continue                        # a name test_consumers reports
        out.add(obj.path)
        try:
            if obj.is_alias:
                out.add(obj.final_target.path)
        except Exception:
            pass                            # alias: its own path is enough
    return out


def baseline(explicit: str | None = None) -> tuple[str, str] | None:
    """`(ref, how it was chosen)`, or None when there is nothing to
    compare against.

    A tag first — a release is what a consumer would have pinned — then
    the upstream branch, which answers the question that actually bites
    here: nine papers import the tip, so "does my working tree break
    what is already pushed?" is the live version of "did I break the
    API".
    """
    if explicit:
        return explicit, "asked for"
    tag = _git("describe", "--tags", "--abbrev=0")
    if tag:
        return tag, "the latest tag"
    upstream = _git("rev-parse", "--abbrev-ref", "@{upstream}")
    if upstream:
        return upstream, "the upstream branch (no tags in this repo)"
    return None


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


def compare(ref: str) -> list[tuple[str, str, bool]]:
    """`(kind, explanation, is-consumed)` for every difference griffe finds.

    The two search paths are spelled differently on purpose and it is
    load-bearing. `load_git` checks the ref out into a temp worktree and
    resolves its search paths INSIDE it, so an absolute
    ``D:\\docxkit\\src`` sends it to the live tree and it loads the
    working copy twice — which reports zero differences, for any ref,
    forever. Written that way first: the measurement over fourteen
    commits came back all-zero, including against a ref the griffe CLI
    reported three findings for.
    """
    from griffe import find_breaking_changes, load, load_git

    old = load_git(PACKAGE, ref=ref, repo=ROOT, search_paths=[SRC_REL])
    new = load(PACKAGE, search_paths=[SEARCH])
    strict = consumed(new)
    return [(b.kind.name, _plain(b.explain()), b.obj.path in strict)
            for b in find_breaking_changes(old, new)]


#: griffe colours its explanations, and this gate's output is read in a
#: CI log as often as in a terminal — where the codes are literal noise
#: around the sentence that matters.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="did this change break the API the papers import?")
    ap.add_argument("--against", metavar="REF",
                    help="git ref to compare against (default: latest tag, "
                         "else the upstream branch)")
    args = ap.parse_args()

    chosen = baseline(args.against)
    if chosen is None:
        print("SKIPPED: no baseline to compare against — this repo has no "
              "tags and no upstream branch.")
        print("  Tag a release (`git tag v1.0.0`) or pass --against REF.")
        return SKIPPED
    ref, why = chosen

    found = compare(ref)
    # Two axes, and a finding fails only when both say so: the KIND has
    # to break a call, and the NAME has to be one a paper imports.
    breaking = [f for f in found if f[0] not in ADVISORY and f[2]]
    unused = [f for f in found if f[0] not in ADVISORY and not f[2]]
    advisory = [f for f in found if f[0] in ADVISORY]

    print(f"compared the working tree against {ref} ({why})")
    for _kind, text, _consumed in breaking:
        print(f"  BREAKING  {text}")
    for _kind, text, _consumed in unused:
        print(f"  unused    {text}")
    for _kind, text, _consumed in advisory:
        print(f"  value     {text}")
    if not found:
        print("  no API differences at all")
    print(f"{len(breaking)} breaking, {len(unused)} in names no paper "
          f"imports, {len(advisory)} value change(s) against {ref}")
    if breaking:
        print("A caller written against the baseline would stop working. "
              "Nine papers import this package from an editable install, "
              "so they are that caller.")
    if unused:
        print("The `unused` lines break a call too — in a name "
              "tools/consumers.txt says no paper imports. Refresh that "
              "snapshot if a paper started using one.")
    return 1 if breaking else 0


if __name__ == "__main__":                  # pragma: no cover
    utf8_stdout()
    raise SystemExit(main())
