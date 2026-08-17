r"""Protecting a generated document that a human also edits.

A redline is derived — the build rewrites it — but it is also the file the
author opens in Word to review, accepting some revisions and leaving
others pending. Rebuilding over that destroys the review with no trace.
It happened on the AFI paper on 2026-07-29: six rebuilds during a
refactor each restored the full markup over an author's accepted state.

The defence is a stamp beside the output recording the hash of what the
build produced. If the file no longer matches, a human changed it: back
it up and stop.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import DeliverableModified
from .package import backup as _backup

__all__ = [
    "DeliverableModified",
    "check",
    "stamp",
    "stamp_path",
]


def stamp_path(out: str | Path) -> Path:
    return Path(out).with_name(Path(out).name + ".buildinfo.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(out: str | Path, *, force: bool = False,
          backup_tag: str = "user_edited") -> Path | None:
    """Refuse to overwrite `out` if it changed since the build wrote it.

    Returns the backup path when one was taken, None when the file is
    untouched (or absent). A deliverable with no stamp cannot be verified
    either way, so it is treated as possibly edited — the cautious
    reading.
    """
    out = Path(out)
    if not out.exists():
        return None
    stamp_file = stamp_path(out)
    if stamp_file.exists():
        try:
            recorded = json.loads(
                stamp_file.read_text(encoding="utf-8"))["sha256"]
        except (ValueError, KeyError):
            recorded = None
        if recorded == _sha256(out):
            return None                      # untouched since we built it
    saved = _backup(out, backup_tag)
    if force:
        return saved
    raise DeliverableModified(
        f"{out.name} has changed since docxkit built it — someone edited it "
        f"in Word. Backed up to {saved.name}; rebuilding would discard those "
        f"edits. Three ways on, in the order they are usually right: fold "
        f"the edits into the build SOURCE and re-run with force=True (CLI: "
        f"--force), which is safe because {saved.name} already holds what "
        f"was here; build somewhere else with out=/--out; or delete "
        f"{out.name} if that batch is already promoted.")


def stamp(out: str | Path, **provenance: str) -> Path:
    """Record what the build just produced, so :func:`check` can tell."""
    out = Path(out)
    path = stamp_path(out)
    path.write_text(
        json.dumps({"sha256": _sha256(out), **provenance}, indent=1),
        encoding="utf-8")
    return path
