"""The round's record: what happened to a batch, written as it happens.

**Write-only in this release.** Nothing reads it yet, and a test holds
that: `tests/test_revision_ledger.py` refuses an importer other than the
three writers. That is the staging the 2026-09-01 review asked for —
record real rounds for a release before any reader trusts the record —
and it is the difference between the one high-danger change on that
list and a safe one.

Why it exists. The protocol's state is inferred from artifacts: which
files are in ``build/``, and what they hash to. Two of the last three S2
defects were inference bugs of exactly that shape. `verdict` could not
tell a batch the author REJECTED from one that was never promoted,
because both leave the manuscript identical — its only evidence was the
redline copy `promote` happens to keep (`39fe472`). And `build` is
silent on a pending working file, because "adjudication pending" and
"clean" look the same from the files (BACKLOG, open). A record of the
transitions is the thing neither could ask.

One JSON object per line, appended, never rewritten: ``build/ledger.jsonl``
beside the batch it describes. Each line carries the event, the moment,
and the hashes of every file the event touched — enough that a reader
next release can reconstruct a round without trusting anything but the
hashes, and can tell when the ledger and the files disagree.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import guard as _guard
from ._config import Paper

#: The file, under ``build/``: with the batch, the rescues and the
#: redlines, and not beside the manuscript.
LEDGER = "ledger.jsonl"

#: The events a round is made of, in the order they happen. Named here
#: so a writer cannot misspell one and a reader next release has the
#: vocabulary in one place.
BUILT = "built"
PROMOTED = "promoted"
#: A promoted proposal taken back before the author opened it — see
#: `revision.withdraw`. Out of order by design: it follows PROMOTED and
#: returns the round to where BUILT found it.
WITHDRAWN = "withdrawn"
BASELINED = "baselined"


def ledger_path(paper: Paper) -> Path:
    return paper.build_dir / LEDGER


def record(paper: Paper, event: str, **facts: Any) -> Path:
    """Append one event with its facts; return the ledger's path.

    Hashes are the caller's to supply, by name — ``batch_sha256`` and
    the like — because the caller holds the files at the moment that
    matters and this module must not re-read a file that may already
    have been replaced by the step it is recording.
    """
    if event not in (BUILT, PROMOTED, WITHDRAWN, BASELINED):
        raise ValueError(f"not a ledger event: {event!r}")
    path = ledger_path(paper)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"event": event,
            "at": datetime.now().isoformat(timespec="seconds"),
            **facts}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def sha256_of(path: Path) -> str | None:
    """A hash for a file that may not exist — the ledger records absence
    as ``null`` rather than refusing to record the event."""
    return _guard.sha256(path) if path.is_file() else None
