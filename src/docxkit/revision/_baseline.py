"""The author accepted — this is the new truth.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import package
from ..errors import BaselinePending, DocumentLocked, HandbackLoss
from ..hygiene import restore_math_glyphs
from ._config import Paper
from ._losses import _names, _unmet, losses
from ._state import state
from ._verdict import log_batch, verdict


def baseline(paper: Paper, *, force: bool = False,
             accept_loss: tuple[str, ...] = (),
             repair_math: bool = False, note: str = "",
             log: bool = True) -> Path:
    """Record the current ``working.docx`` as the new accepted truth.

    Run this after the author has accepted (or rejected) everything: it
    closes the cycle by making ``build/prev.docx`` the file the next
    batch will be compared and rejected against.

    It refuses while revisions are pending, because a baseline that
    contains a proposal is how the next Compare flattens that proposal
    into plain text. `force` is for the one legitimate case — adopting a
    file that already carries revisions the author intends to keep as
    the starting point, which is what a MIGRATION does.

    It also refuses while the file is open in Word, which `promote`
    already did and this did not. A .docx is a zip, and copying one that
    Word is part-way through rewriting captures an archive that is
    internally inconsistent — enshrined here as `prev.docx`, the file
    every later Compare and every reject-all is measured against. `force`
    does NOT override this: a locked file is not a decision the author
    has made, it is a file that cannot be copied safely.

    And it refuses while the hand-back has LOST something — a link, a
    note, a bookmark, a comment (:func:`losses`). This is the step that
    makes such a loss permanent: `prev.docx` is what the compare chain
    measures against afterwards, so a link Word ate on the way in
    becomes a link that was never there. `accept_loss` names the ones
    that are deliberate, by anchor, note text or ``kind:what`` key —
    including the case that made the check hard to write, a loss that is
    a REPAIR (LI7's link whose label had bled across a whole sentence).
    Naming something that is NOT lost is itself refused: a stale
    exemption is a switched-off gate that reads as a switched-on one.

    `force` does not override this either. The unacknowledged loss is
    exactly the case `force` would be reached for by reflex, and the
    acknowledgement costs one anchor.

    `repair_math` is the one loss this tool may put back itself, and
    the reason it may is that it is not an author's decision: Word
    downgrades an equation's U+2212 on accept-and-save, `build` already
    restores the same glyph on the redline it produces, and doing it
    here is that repair on the other side of the hand-back. It rewrites
    `working.docx` — every run whose text the baseline spells with the
    glyph put back — and the gates above run against the repair, so
    anything it could NOT reach still refuses.

    It also RECORDS the round, in `log.md`'s batch table, unless
    `log=False`. That is not bookkeeping for its own sake: this is the
    moment the evidence stops existing. After adjudication the
    manuscript reads 0 pending whether every revision was accepted,
    every one rejected or half of each, and the next line of this
    function replaces the only other copy of what it grew out of. The
    verdict was reconstructible until now and unrecorded — `log.md`'s
    outcome column was filled in by hand, when it was filled in at all.
    `note` names the batch in that row; without one it takes the
    proposal's filename.

    They run against it IN MEMORY, and the write waits for all of them.
    Writing first meant that `--repair-math` on a manuscript with a
    revision still pending, or with a loss nobody had acknowledged,
    refused — correctly — having ALREADY changed the author's live
    file, and with no backup of it: the one command in this package that
    both edits `working.docx` and then declines to say so. It is backed
    up before the write now, as `build --force` and `refstyle --fix` do.
    """
    if package.is_locked(paper.working):
        raise DocumentLocked(
            f"{paper.working.name} is open in Word. Close it first — a "
            f"baseline copied mid-save is a zip nothing can reject "
            f"against.")
    repaired: dict[str, bytes] | None = None
    if paper.prev.exists():
        work, base = (package.read_parts(paper.working),
                      package.read_parts(paper.prev))
        if repair_math and restore_math_glyphs(work, base):
            repaired = work        # written below, once every gate has passed
        gone = losses(work, base)
        if stale := _unmet(accept_loss, gone):
            raise HandbackLoss(
                f"--accept-loss named {', '.join(stale)}, which "
                f"{paper.working.name} has NOT lost. A declared loss that "
                f"did not happen is an exemption with nothing under it, "
                f"and it would pass the next real one through in silence.")
        unacknowledged = [loss for loss in gone
                          if not any(_names(token, loss)
                                     for token in accept_loss)]
        if unacknowledged:
            # Print the token that WORKS, not a description of it. The
            # first version printed a 70-character truncation and the
            # hatch then rejected the words it had just shown.
            listed = "\n  - ".join(
                f"{loss}\n      --accept-loss {loss.key[:60]!r}"
                for loss in unacknowledged)
            raise HandbackLoss(
                f"{paper.working.name} lost {len(unacknowledged)} thing(s) "
                f"since {paper.prev.name}, and baselining makes that "
                f"permanent — the compare chain measures against prev.docx, "
                f"so a link Word ate becomes a link that was never there:"
                f"\n  - {listed}\n"
                f"Word does this silently when it collapses a paragraph to "
                f"make an edit. Put them back, or name the deliberate ones "
                f"with the flag shown above (a prefix is enough).")
    current = state(paper.working)
    if not current.is_truth and not force:
        where = ", ".join(f"{n} in {p.split('/')[-1]}"
                          for p, n in current.by_part.items())
        raise BaselinePending(
            f"{paper.working.name} is a proposal, not the truth: "
            f"{current.pending} revision(s) pending ({where}). The "
            f"author accepts or rejects them; this tool never does.")
    if repaired is not None:
        # `state` above read the file on disk, which is the unrepaired
        # one — and reads the same either way: restoring a glyph rewrites
        # run TEXT and touches no `w:ins` or `w:del`, so it cannot move
        # the count this gate is about.
        package.backup(paper.working, tag="pre_math_repair")
        package.write_docx(paper.working, repaired)
    # BEFORE the copy: the whole computation is against the truth the
    # batch was built on, and the next line overwrites it.
    recorded = verdict(paper) if log else None
    paper.build_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paper.working, paper.prev)
    if recorded is not None:
        log_batch(paper, recorded, note)
    return paper.prev
