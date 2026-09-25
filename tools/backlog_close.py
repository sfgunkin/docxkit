#!/usr/bin/env python
"""Close a BACKLOG entry: move it from `## Open` to the archive's `## Fixed`.

    python tools/backlog_close.py "S2 — the thing" --commit 3f81c97 \\
        --note-file close.md [--stamp "FIXED 25.09"] [--dry-run]

The heading argument is the START of the entry's heading after ``### ``
and must name exactly one entry under ``## Open`` whose status is
``open``. The entry is struck through, stamped ``— FIXED dd.mm,
`hash``` (today's date unless ``--stamp`` says otherwise), re-marked
``fixed``, given the note, and inserted at the top of the archive's
``## Fixed`` — newest first, as the archive keeps them. Both files are
then checked by `backlog_status.problems` BEFORE anything is written, and
the commit must exist.

**Why a tool.** Every session hand-rolled this move: `close_entry.py` and
`close_s1.py` on 2026-09-24, `close_entries.py` on 2026-09-25 — three
copies in two days, in scratchpads nobody reviews, one of which wrote
CRLF on Windows through `Path.write_text` and let git normalise it
silently. The 2026-08-24 incident is the reason the section is found by
its heading and the entry cut at the next ``### `` OR ``## ``: a helper
that cut "to the next `### `" once carried the `## Fixed` heading along.
Written as bytes, so the files stay LF.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import backlog_status as bs  # pyright: ignore[reportMissingImports]

from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]
FIXED = "## Fixed\n"


class CloseError(Exception):
    """The entry cannot be closed as asked; nothing was written."""


def _cut(text: str, start: int) -> int:
    """Where the entry starting at `start` ends: the next heading."""
    nxt = [text.find(mark, start + 1) for mark in ("\n### ", "\n## ")]
    found = [n for n in nxt if n >= 0]
    return min(found) + 1 if found else len(text)


def close(backlog: str, archive: str, heading: str, *, commit: str,
          note: str, stamp: str) -> tuple[str, str]:
    """Both files' new text, with the entry moved and closed."""
    open_at = backlog.find("\n## Open\n")
    if open_at < 0:
        raise CloseError("BACKLOG.md has no `## Open` section")
    end_open = backlog.find("\n## ", open_at + 1)
    end_open = len(backlog) if end_open < 0 else end_open
    hits = []
    pos = open_at
    while (at := backlog.find(f"\n### {heading}", pos, end_open)) >= 0:
        hits.append(at + 1)
        pos = at + 1
    if len(hits) != 1:
        raise CloseError(f"{len(hits)} entries under `## Open` begin "
                         f"{heading!r}; name exactly one")
    start = hits[0]
    stop = _cut(backlog, start)
    entry = backlog[start:stop]
    lines = entry.split("\n")
    if len(lines) < 2 or lines[1] != "<!-- status: open -->":
        raise CloseError(f"that entry's status is not `open`: {lines[1:2]}")
    title = lines[0][len("### "):]
    body = "\n".join(lines[2:]).strip("\n")
    closed = (f"### ~~{title}~~ — {stamp}, `{commit}`\n\n"
              f"<!-- status: fixed -->\n\n{body}\n\n{note.strip()}\n\n")
    if archive.count(FIXED) != 1:
        raise CloseError("the archive must hold exactly one `## Fixed`")
    at = archive.index(FIXED) + len(FIXED)
    at += len(archive[at:]) - len(archive[at:].lstrip("\n"))
    new_archive = archive[:at] + closed + archive[at:]
    new_backlog = backlog[:start] + backlog[stop:]
    found = (bs.problems(new_backlog, "BACKLOG.md")
             + bs.problems(new_archive, "BACKLOG-ARCHIVE.md"))
    if found:
        raise CloseError("the result would fail backlog_status:\n  "
                         + "\n  ".join(found))
    return new_backlog, new_archive


def _commit_exists(root: Path, commit: str) -> bool:
    return subprocess.run(["git", "-C", str(root), "cat-file", "-e",
                           f"{commit}^{{commit}}"],
                          capture_output=True).returncode == 0


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Close a BACKLOG entry: move it from `## Open` to the "
                    "archive's `## Fixed`.")
    ap.add_argument("heading", help="the start of the entry's heading")
    ap.add_argument("--commit", required=True, help="the fixing commit")
    note = ap.add_mutually_exclusive_group(required=True)
    note.add_argument("--note-file", type=Path)
    note.add_argument("--note")
    ap.add_argument("--stamp",
                    default=f"FIXED {date.today():%d.%m}",
                    help="what follows the struck heading, before the hash")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not _commit_exists(root, args.commit):
        print(f"no commit {args.commit!r} in {root}")
        return 2
    text = args.note if args.note is not None else \
        args.note_file.read_bytes().decode("utf-8")
    b_path, a_path = root / "BACKLOG.md", root / "BACKLOG-ARCHIVE.md"
    try:
        backlog, archive = close(
            b_path.read_bytes().decode("utf-8"),
            a_path.read_bytes().decode("utf-8"), args.heading,
            commit=args.commit, note=text, stamp=args.stamp)
    except CloseError as exc:
        print(f"not closed: {exc}")
        return 1
    if args.dry_run:
        print("dry run: would close", repr(args.heading))
        return 0
    b_path.write_bytes(backlog.encode("utf-8"))
    a_path.write_bytes(archive.encode("utf-8"))
    print(f"closed {args.heading!r} ({args.commit})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
