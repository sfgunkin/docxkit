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
    "base_of",
    "carry",
    "check",
    "restamp",
    "sha256",
    "stamp",
    "stamp_path",
]


def stamp_path(out: str | Path) -> Path:
    return Path(out).with_name(Path(out).name + ".buildinfo.json")


def sha256(path: str | Path) -> str:
    """The file's hash, as every stamp in this module records it."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        if recorded == sha256(out):
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
        f"{out.name} if that batch is already promoted. If a docxkit "
        f"routine wrote it — a math-glyph repair run after the build — "
        f"that is not a Word session: call guard.restamp() there, and "
        f"the next build reads it as the tool's own work.")


def restamp(out: str | Path, *, why: str) -> Path:
    """Re-record a deliverable a TOOL repaired after the build stamped it.

    Not every change to a redline is a Word session. AFI's rounds end
    with a repair the build cannot do — the minus glyph Compare
    downgrades on the REJECTED side, which `restore_math_glyphs` will
    not infer — and running it changes `batch.docx` after `build`
    stamped it. The next build then refuses with "someone edited it in
    Word", backs the file up as `batch_user_edited1.docx`, and the
    author who edited nothing is told they did. Three rounds, three
    spurious artifacts (backlog S3).

    So a repair says so here. The stamp keeps the build's own
    provenance and grows a `repairs` list — reason, the hash it replaced
    and the hash now — because "the tool changed it" must be READABLE
    afterwards, not just assumed: this is the one call that can retire a
    guard, and it should leave the evidence for doing so.

    It is an assertion, and only the caller can make it. If a human
    edited the file in Word as well, that edit is inside the hash being
    recorded and this will adopt it — so call it in the repair, next to
    the write, and never to clear a refusal you did not cause.
    """
    out = Path(out)
    path = stamp_path(out)
    old: dict[str, object] = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            old = {}
    now = sha256(out)
    if old.get("sha256") == now:
        return path              # nothing moved: the repair changed nothing
    was = old.get("repairs")
    repairs = list(was) if isinstance(was, list) else []
    repairs.append({"why": why, "was": old.get("sha256", ""), "now": now})
    path.write_text(
        json.dumps({**old, "sha256": now, "repairs": repairs}, indent=1),
        encoding="utf-8")
    return path


def stamp(out: str | Path, **provenance: str) -> Path:
    """Record what the build just produced, so :func:`check` can tell."""
    out = Path(out)
    path = stamp_path(out)
    path.write_text(
        json.dumps({"sha256": sha256(out), **provenance}, indent=1),
        encoding="utf-8")
    return path


def carry(src: str | Path, dst: str | Path) -> Path | None:
    """Give `dst`, which now holds `src`'s bytes, `src`'s stamp as well.

    `promote` copies a batch onto the manuscript byte for byte, and from
    that moment the stamp beside the batch — hash, inputs,
    `base_sha256`, any repairs — describes the manuscript exactly as
    well. Left beside the batch alone, the manuscript keeps whatever
    stamp the LAST thing that wrote it left there. Health_Capacity_to_
    Work, 2026-09-04: after a promote, `working.docx.buildinfo.json`
    still named a batch from an earlier round, and the paper's own lane
    script — which builds with `out=working.docx` — had to pass
    `force=True` to get past :func:`check`'s refusal. A guard that
    refuses every time is a guard everybody forces, and forcing it
    retires it for the author's real edits too.

    The batch KEEPS its stamp: `verdict` and `validate` still ask
    `base_of(batch)` after the promote. What is written beside `dst` is
    the same bytes, so the two stamps cannot disagree.

    Returns the stamp written beside `dst`. When `src` has no stamp, or
    one that does not parse, there is nothing to carry — and a stamp
    already beside `dst` describes a file that is no longer there, so it
    is REMOVED. :func:`check` then answers "cannot verify", which is the
    cautious reading and the truthful one; a stale stamp would answer
    with another file's provenance, and `base_of` would name a baseline
    this file was never built on.

    Refuses when the stamp's hash is not `dst`'s. A stamp is a claim
    about a hash, and carrying it onto other content would make the
    guard certify a file nobody built. The caller has already verified
    the copy; this is the check on the caller.
    """
    src, dst = Path(src), Path(dst)
    source, target = stamp_path(src), stamp_path(dst)
    if not source.exists():
        target.unlink(missing_ok=True)
        return None
    try:
        recorded = json.loads(source.read_text(encoding="utf-8"))
    except ValueError:
        target.unlink(missing_ok=True)
        return None
    if not isinstance(recorded, dict) or "sha256" not in recorded:
        target.unlink(missing_ok=True)
        return None
    if recorded["sha256"] != sha256(dst):
        raise DeliverableModified(
            f"{source.name} does not describe {dst.name}: the stamp "
            f"records {str(recorded['sha256'])[:16]} and the file hashes "
            f"to {sha256(dst)[:16]}. A stamp is carried only onto the "
            f"bytes it was written for.")
    target.write_bytes(source.read_bytes())
    return target


def base_of(out: str | Path) -> str | None:
    """The hash of the ORIGINAL this deliverable was built from, if stamped.

    The stamp has always named the original as a FILE — ``"original":
    "prev.docx"`` — and that path legitimately holds different content
    after every `baseline`, so it cannot answer "is this batch about the
    current truth". Nothing else recorded the link either, which is how
    a refused build left the previous redline in place and `validate`
    then validated it in full detail against a baseline two rounds
    newer: twenty findings, all describing a batch nobody was working
    on. `promote` was the dangerous half — its own staleness check asks
    whether the AUTHOR moved, and both files were in sync, so it would
    have copied a redline built before an entire author round over the
    manuscript (Aging_Well R5, 2026-08-21).

    None when there is no stamp, or when it predates this field: a
    caller cannot then tell stale from fresh, and should say so rather
    than assume either.
    """
    path = stamp_path(out)
    if not path.exists():
        return None
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    got = recorded.get("base_sha256")
    return got if isinstance(got, str) and got else None
