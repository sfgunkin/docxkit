#!/usr/bin/env python
"""Is every BACKLOG.md entry in the section that describes it?

    python tools/backlog_status.py

**Why this is a declared field and not a regex.** The obvious gate was
built first, measured, and thrown away. A resolution-detector over all
209 entries — strikethrough, `FIXED`, `WITHDRAWN`, `RETRACTED`,
`CORRECTED`, a commit hash in the heading — produced **93 findings, 2 of
them real**. Every false positive came from a convention the file GREW
rather than declared: an entry closed by a bare hash, twelve closed
together under one struck parent, a record that was never a defect, and —
the one that settles it — an entry whose body says *"Raised by the same
review, and not fixed"* in its first paragraph and *"Closed 2026-08-18"*
in its fifth. Entries accumulate history and only the last word counts.
No pattern can know which sentence is the verdict; the author can, once,
at the moment of writing.

So each entry carries `<!-- status: … -->` on the line after its
heading. Invisible in rendered markdown, exact to a parser, and the check
becomes a lookup rather than an inference about English.

**What it refuses**, and it is deliberately narrow — `open` under
`## Fixed`, or `fixed` under `## Open`. Those are the two failures that
really happened, in the same week and in both directions: `--sample` and
the `Table` handle sat under `## Fixed` while open, three days each; and
on 2026-08-24 a close-helper that cut an entry "to the next `### `" took
the `## Fixed` heading with it, so every closed entry sat inside
`## Open` for three commits, struck through, in order, looking right.

`withdrawn`, `not-a-defect` and `note` are records rather than defects
and may sit in either section, because some are kept in `## Open` on
purpose — a retraction and a Word behaviour worth not chasing twice.
Refusing those would be a gate firing on the file's own conventions,
which is what the regex did.

Why it matters at all: the batch order is set by severity WITHIN
`## Open`, so a misfiled list orders the work wrongly — that is exactly
how 2026-08-27 began, with the top-severity entry being one already
fixed. And `## Fixed` exists to answer "did we ever fix that?"; an open
entry sitting there answers it wrongly, which is worse than not
answering.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "BACKLOG.md"

#: The vocabulary. Small on purpose: a status nobody can tell apart from
#: its neighbour is a status people guess at.
STATUSES = frozenset({"open", "fixed", "withdrawn", "not-a-defect", "note"})

#: Which statuses each section may hold. Everything not named here is a
#: record and may sit in either.
ONLY_IN = {"open": "Open", "fixed": "Fixed"}

SECTION = re.compile(r"^## (.+)$", re.MULTILINE)
ENTRY = re.compile(r"^### (.+)$", re.MULTILINE)
MARKER = re.compile(r"^<!-- status: ([a-z-]+) -->$")


def entries(text: str) -> list[tuple[str, str | None, str]]:
    """(section, status, heading) for every entry, in file order.

    `status` is None when the heading carries no marker — which is a
    finding in itself, and the one that keeps this from decaying: a new
    entry written without one fails rather than being assumed open.
    """
    out: list[tuple[str, str | None, str]] = []
    marks = list(SECTION.finditer(text))
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        section = m.group(1).strip()
        for e in ENTRY.finditer(text, m.end(), stop):
            # the line IMMEDIATELY after the heading, so an entry that is
            # moved without its marker is a miss rather than inheriting
            # whatever the next one declares
            rest = text[e.end():].lstrip("\n").splitlines()
            found = MARKER.match(rest[0]) if rest else None
            out.append((section, found.group(1) if found else None,
                        e.group(1)))
    return out


def problems(text: str) -> list[str]:
    """Every entry whose declared status and section disagree."""
    out = []
    for section, status, head in entries(text):
        if status is None:
            out.append(f"no status declared: [{section}] {head[:70]}")
        elif status not in STATUSES:
            out.append(f"unknown status {status!r}: [{section}] {head[:70]}")
        elif (want := ONLY_IN.get(status)) and want != section:
            out.append(f"{status!r} under `## {section}`, belongs in "
                       f"`## {want}`: {head[:70]}")
    return out


def main() -> int:
    utf8_stdout()
    if not FILE.exists():
        print(f"no {FILE.name} here — nothing to check")
        return 0
    text = FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    found = problems(text)
    if not found:
        print(f"{len(entries(text))} entries, each in the section its "
              f"declared status names")
        return 0
    print(f"{len(found)} entry/entries are not where their status says:\n")
    for line in found:
        print(f"  {line}")
    print("\nMove the entry, or correct its `<!-- status: … -->`. The status "
          "is declared rather than inferred because inferring it scored 2 "
          "real findings out of 93.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
