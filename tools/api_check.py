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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
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


def compare(ref: str) -> list[tuple[str, str]]:
    """`(kind, one-line explanation)` for every difference griffe finds.

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
    return [(b.kind.name, _plain(b.explain()))
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
    breaking = [(k, text) for k, text in found if k not in ADVISORY]
    advisory = [(k, text) for k, text in found if k in ADVISORY]

    print(f"compared the working tree against {ref} ({why})")
    for _kind, text in breaking:
        print(f"  BREAKING  {text}")
    for _kind, text in advisory:
        print(f"  value     {text}")
    if not found:
        print("  no API differences at all")
    print(f"{len(breaking)} breaking, {len(advisory)} value change(s) "
          f"against {ref}")
    if breaking:
        print("A caller written against the baseline would stop working. "
              "Nine papers import this package from an editable install, "
              "so they are that caller.")
    return 1 if breaking else 0


if __name__ == "__main__":                  # pragma: no cover
    utf8_stdout()
    raise SystemExit(main())
