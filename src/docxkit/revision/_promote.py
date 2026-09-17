"""Put a validated batch onto the manuscript.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .. import guard as _guard
from .. import package
from ..errors import DocumentLocked, ProtocolError, StaleBatch
from . import _ledger, _timing
from ._common import _RESCUE_GLOB, _RESCUE_STAMP
from ._config import Paper

# -------------------------------------------------------------- promote

@dataclass(frozen=True)
class PromoteReport:
    promoted: Path
    onto: Path
    rescue: Path
    #: Not optional. `promote` either RAISES — the copy did not land, and
    #: it says so rather than returning a report with a hole in it — or
    #: returns with the redline it made, and there is one construction
    #: site. It was `Path | None = None` until 2026-08-24, which made
    #: the CLI's `if report.redline is not None:` look necessary: a
    #: branch nothing could take, and the second of that shape found in
    #: `cmd_revision_*` in one afternoon. An Optional the constructor
    #: cannot produce is a claim about the code that is not true.
    redline: Path
    #: The batch's stamp, now beside the manuscript too — or None for an
    #: unstamped batch, in which case a stale stamp beside the manuscript
    #: was removed. See `guard.carry` for what a stale one cost.
    stamp: Path | None = None
    pruned: tuple[Path, ...] = ()


def redline_path(paper: Paper, when: datetime | None = None) -> Path:
    """The next redline file: ``build/redlines/working_redline_<stamp>.docx``.

    Same stamped shape as :func:`rescue_path`, and for the same reason:
    a counter takes the first FREE number, so pruning would make the
    next name older than the one beside it. Nothing prunes this folder,
    but the two are read together — a redline and the rescue taken in
    the same promote sort adjacent — and one shape is easier to read
    than two.
    """
    return _stamped(paper, paper.redline_dir, "redline", when)


def rescue_path(paper: Paper, when: datetime | None = None) -> Path:
    """The next rescue file: ``build/rescue/working_rescue_<stamp>.docx``.

    A taken name advances the stamp by a microsecond rather than gaining
    a suffix, so every rescue in a folder has the SAME shape and sorts
    chronologically as a plain string. See :data:`_RESCUE_STAMP` for the
    version that did not and what it cost.
    """
    return _stamped(paper, paper.rescue_dir, "rescue", when)


def _stamped(paper: Paper, folder: Path, kind: str,
             when: datetime | None = None) -> Path:
    """``<folder>/<stem>_<kind>_<stamp><suffix>``, first free stamp."""
    moment = when or datetime.now()
    stem, suffix = paper.working.stem, paper.working.suffix
    for _ in range(1000):
        name = f"{stem}_{kind}_{moment.strftime(_RESCUE_STAMP)}{suffix}"
        candidate = folder / name
        if not candidate.exists():
            return candidate
        moment += timedelta(microseconds=1)
    raise ProtocolError(
        f"no free {kind} name near {moment:%Y-%m-%d %H:%M:%S} in {folder}")


#: The stamp `_stamped` writes, read back. `%Y%m%d-%H%M%S-%f` is
#: uniform width, so these sort chronologically as strings — but only
#: among THEMSELVES, which is the whole of the S1 below.
_STAMPED_RE = re.compile(r"_rescue_(\d{8}-\d{6}-\d{6})(?=\.|$)")


def _stamp_of(path: Path) -> str | None:
    """The moment this rescue was written, or None if we did not write it."""
    m = _STAMPED_RE.search(path.stem + ".")
    return m.group(1) if m else None


def rescues(paper: Paper) -> list[Path]:
    """Every rescue copy in the folder, oldest first.

    **Ordered by the parsed stamp, not by the string**, and the ones
    this tool did not write sort last rather than wrongly.

    Sorting the names was true of names `_stamped` writes and false the
    moment the folder holds anything else — which it does, because a
    session copying a file by hand puts it here too. `-` is 0x2D and `_`
    is 0x5F, so `working_rescue_20260831-235728-542622.docx` (23:57)
    sorts BEFORE `working_rescue_20260831_pre_COMP.docx` (18:44): the
    newest file read as the oldest, and `prune_rescues` deleted it.
    Twice on Aging_Well, 2026-08-31 and 2026-09-01, each time taking the
    undo for the promote that had just run.
    """
    if not paper.rescue_dir.is_dir():
        return []
    return sorted(paper.rescue_dir.glob(
        _RESCUE_GLOB + paper.working.suffix), key=_written_at)


def _written_at(path: Path) -> datetime:
    """When a rescue was made: its stamp, or failing that its mtime.

    The stamp is preferred wherever there is one, and that is the whole
    reason `_stamped` writes one — an mtime is rewritten by a copy, and
    these folders live on a sync-on-demand drive. For a copy the tool
    did not write there is no stamp and the mtime is the best available
    answer; it is only used to ORDER the listing, never to decide a
    deletion.
    """
    stamp = _stamp_of(path)
    if stamp is not None:
        return datetime.strptime(stamp, _RESCUE_STAMP)
    return datetime.fromtimestamp(path.stat().st_mtime)


def redlines(paper: Paper) -> list[Path]:
    """Every kept redline, oldest first.

    The counterpart of :func:`rescues`, and it exists for the same reason
    that one does: the copies are stamped rather than numbered, so sorting
    them as strings sorts them chronologically, and a caller should not
    have to know that to list them.

    The asymmetry with rescues is deliberate and worth stating here, since
    the two folders sit side by side. A rescue is TRANSIENT — it undoes the
    promote that just happened, and `prune_rescues` thins it to
    ``[batch] rescue_keep``. A redline is the RECORD, it is what a batch
    actually proposed, and nothing prunes it: see :attr:`Paper.redline_dir`
    for what it cost to learn that.

    The listing itself is :meth:`Paper.redlines`, because `verdict` asks
    the same question from below this module in the layering.
    """
    return paper.redlines()


def prune_rescues(paper: Paper, keep: int | None = None, *,
                  protect: Path | None = None) -> list[Path]:
    """Delete all but the newest `keep` rescue copies; return what went.

    A rescue exists to undo the promote that just happened, or one of
    the few before it. Beyond that the safekit vault, the attic and git
    all hold the same history and hold it out of the working tree, so
    keeping more here buys nothing and costs the clarity this layout was
    built for.

    `keep=0` is honoured — someone may want none — but a NEGATIVE keep
    is treated as zero rather than slicing from the wrong end, which
    would delete the newest instead of the oldest.

    **Only copies this tool wrote are ever deleted**, and `protect` is
    never deleted at all. Both halves are the S1 of 2026-08-31: the glob
    is `*_rescue_*`, which catches the hand-named copies a session makes
    — those are somebody's deliberate undo and not this function's to
    remove — and the newest stamped file sorted as the oldest beside
    them, so `promote` twice deleted the rescue it had just written.
    `promote` passes the copy it just made as `protect`, because a
    promote destroying its own undo is the invariant that matters
    whatever else the folder holds.

    The hand-named copies still COUNT toward `keep`: a folder holding
    five of them is a folder with five undos in it, and thinning the
    stamped ones to make room would be this function deciding which of
    the author's copies matter.
    """
    limit = paper.rescue_keep if keep is None else keep
    limit = max(0, limit)
    ours = [p for p in rescues(paper) if _stamp_of(p) is not None]
    surplus = len(rescues(paper)) - limit
    doomed = [p for p in ours[:max(0, surplus)] if p != protect]
    for path in doomed:
        path.unlink()
    return doomed


@_timing.timed("promote")
def promote(paper: Paper, batch: str | Path | None = None,
            base: str | Path | None = None) -> PromoteReport:
    """Put a validated batch onto ``working.docx`` — safely.

    The author edits ``working.docx`` in Word between turns and during
    them, so a batch built minutes ago may already be stale. Two guards,
    both of which have caught a real loss:

    * **the lock.** A copy written over a document open in Word appears
      to succeed, and then Word writes its in-memory version on top and
      the promotion silently vanishes.
    * **the hash.** If the live file no longer matches the baseline the
      batch was built on, the author has edited it since, and promoting
      would destroy those edits.

    A rescue copy of the live file is taken first, into
    ``build/rescue/`` and stamped with the time. Not a fixed name: an
    earlier version overwrote its own rescue on every promote, so only
    the most recent live state was ever recoverable. Not beside the
    manuscript either, and not numbered — see :attr:`Paper.rescue_dir`
    and :data:`_RESCUE_STAMP`. Older copies are pruned to
    :attr:`Paper.rescue_keep`.

    **Two copies are made, and they are not the same kind of thing.** The
    rescue above holds the file being REPLACED, and it is transient. The
    REDLINE — the batch itself — is copied into ``build/redlines/``
    before the manuscript is overwritten, and it is permanent: nothing
    prunes that folder, and :func:`redlines` lists it. It is taken here
    because this is the last moment the markup exists as a file of its
    own; the author's accept then flattens it, and after that no gate,
    no diff and no rescue copy can say what the batch proposed. See
    :attr:`Paper.redline_dir` for the measurement that established it.

    So there is a third refusal beside the lock and the hash: **if the
    redline copy does not verify, the promote is refused and the partial
    file is deleted.** A truncated copy left in the one folder nothing
    prunes, stamped and named exactly like a good one, would be an audit
    trail that lies — worse than a gap, because a gap is visible.

    **What lands is the batch, byte for byte** — copied, then hashed
    against it, and the redline kept in ``build/redlines/`` is a third
    copy of the same bytes. Nothing here re-derives, re-compares or
    rewrites the redline. That is worth stating because it was once
    filed as doing so: a paragraph found without its revision marks in
    ``working.docx`` after a promote (Health_Capacity_to_Work,
    2026-09-04) turned out to be intact in the batch, in the kept
    redline and therefore in the file this wrote — the three hashes
    agreed, and reject-all on the batch reproduced the baseline in every
    paragraph. A file that differs from the batch after a promote was
    written by something else afterwards; look there. The batch's stamp
    is carried beside the manuscript so that :func:`docxkit.guard.check`
    can say so (``PromoteReport.stamp``).
    """
    batch = Path(batch) if batch else paper.batch
    base = Path(base) if base else paper.prev
    live = paper.working

    for candidate in (batch, base, live):
        if not candidate.exists():
            raise ProtocolError(f"missing: {candidate}")

    if package.is_locked(live):
        raise DocumentLocked(
            f"{live.name} is open in Word. Close it first — a copy made "
            f"now would be overwritten the moment Word saves.")

    live_hash, base_hash = _guard.sha256(live), _guard.sha256(base)
    if live_hash != base_hash:
        raise StaleBatch(
            f"{live.name} no longer matches the baseline this batch was "
            f"built on (live {live_hash[:16]}, baseline "
            f"{base_hash[:16]}). The author has edited it. Re-baseline "
            f"from the live file, rebuild the batch on top of it, "
            f"re-validate, then promote.")

    # …and the other direction, which is the one that loses work
    # silently. The check above asks whether the AUTHOR moved; this asks
    # whether the BATCH did. A refused build leaves the previous redline
    # in `build/batch.docx`, live and base stay in sync, and promoting
    # copies a generation from before an entire author round over the
    # manuscript with the rescue copy as the only way back and no gate
    # having said a word (Aging_Well R5, 2026-08-21).
    built_on = _guard.base_of(batch)
    if built_on is not None and built_on != base_hash:
        raise StaleBatch(
            f"{batch.name} was not built on {base.name}: it says it was "
            f"built on {built_on[:16]} and this baseline is "
            f"{base_hash[:16]}. It is a redline of an older truth — "
            f"promoting it would replace {live.name} with a generation "
            f"from before whatever has been baselined since. Rebuild the "
            f"batch on the current baseline and re-validate. (If the "
            f"build was REFUSED, this file is the previous batch: delete "
            f"it and build again.)")

    # …and whether the batch is still the bytes its stamp describes.
    # `carry` below refuses a stamp that is not — but only after the
    # manuscript has been replaced, the rescue taken and the redline
    # kept, so a promote that exited 1 had done the dangerous half of its
    # work and skipped the record (DSI, 2026-09-16: a relink pass over
    # the batch after `build`, which nothing restamped). Asked here,
    # nothing has been written when it refuses.
    if _guard.describes(batch) is False:
        raise StaleBatch(
            f"{batch.name} has changed since `revision build` stamped it, "
            f"so the stamp's baseline and inputs describe other bytes. "
            f"Nothing was written. If a docxkit tool changed it — a "
            f"citation relink, a glyph repair — record that and promote "
            f"again:\n"
            f"    docxkit revision restamp --why \"<what the tool did>\"\n"
            f"If it was opened and saved in Word, rebuild it instead: a "
            f"restamp would certify an edit nobody reviewed.")

    paper.rescue_dir.mkdir(parents=True, exist_ok=True)
    rescue = rescue_path(paper)
    shutil.copy2(live, rescue)
    if _guard.sha256(rescue) != _guard.sha256(live):
        raise ProtocolError(
            f"the rescue copy did not land: {rescue} — refusing to "
            f"overwrite {live.name} with nothing to undo it")

    # Keep the redline BEFORE the batch stops being a separate file.
    # `promote` is the last moment the markup exists anywhere: the
    # rescue above is the previous LIVE file and is clean, `live` is
    # about to become a proposal that the author's accept will flatten,
    # and the protocol used to delete `batch.docx` right after this.
    # Copy first, verify the hash, and only then overwrite — a redline
    # that did not land is worth refusing the promote for, because the
    # thing it records is about to be the only copy.
    paper.redline_dir.mkdir(parents=True, exist_ok=True)
    redline = redline_path(paper)
    shutil.copy2(batch, redline)
    if _guard.sha256(redline) != _guard.sha256(batch):
        # Take the bad copy with us. A truncated file left here would sit
        # in the ONE folder nothing prunes, stamped and named exactly like
        # a good redline, and the batch it claims to record would be the
        # thing nobody could reconstruct. An audit trail with a corrupt
        # entry in it is worse than a gap, because a gap is visible.
        redline.unlink(missing_ok=True)
        raise ProtocolError(
            f"the redline copy did not land: {redline.name} — refusing to "
            f"promote, because after the author accepts, this batch's "
            f"markup would exist nowhere. The partial copy has been "
            f"removed; {rescue.name} still holds the file this would have "
            f"replaced.")

    shutil.copyfile(batch, live)
    if _guard.sha256(live) != _guard.sha256(batch):
        raise ProtocolError(f"the copy did not land: {live}")

    # The stamp goes with the bytes. The manuscript now IS the batch, and
    # the batch's stamp describes it exactly; the one it was carrying —
    # from whatever last wrote it — describes a file that is gone. A
    # paper that builds with `out=working.docx` reads that stamp through
    # `guard.check`, and a stale one makes it refuse every round
    # (Health_Capacity_to_Work, 2026-09-04). `carry` also re-verifies the
    # hash against the stamp, a second reading of the check above.
    stamp = _guard.carry(batch, live)

    # The round's record, written and not yet read — see `_ledger`. The
    # question it exists for is this event: a batch REJECTED in full and
    # one that was never promoted leave the manuscript identical, so
    # `verdict` had to infer from the redline copy that this line makes
    # explicit. Written after the copy has landed and been verified,
    # because a ledger entry for a promote that did not happen is the
    # failure mode of recording one at all.
    _ledger.record(paper, _ledger.PROMOTED,
                   batch=batch.name,
                   batch_sha256=_guard.sha256(batch),
                   replaced_sha256=live_hash,
                   onto=live.name, base_sha256=base_hash,
                   redline=redline.name, rescue=rescue.name)

    # only after the promote has landed: a prune that ran first could
    # delete the one copy this promote was about to need. Redlines are
    # not pruned at all — see `Paper.redline_dir`.
    return PromoteReport(promoted=batch, onto=live, rescue=rescue,
                         redline=redline, stamp=stamp,
                         pruned=tuple(prune_rescues(paper,
                                                    protect=rescue)))


# ------------------------------------------------------------- withdraw

@dataclass(frozen=True)
class WithdrawReport:
    #: The kept redline that was on the manuscript — still in
    #: ``build/redlines/``, because it is the record of what was offered.
    withdrawn: Path
    onto: Path
    #: True when ``build/batch.docx`` WAS that proposal and was unstaged.
    removed_batch: bool
    why: str


def withdraw(paper: Paper, *, why: str) -> WithdrawReport:
    """Take back a promoted proposal the author has not opened.

    The one door out of the PROMOTED state that is not the author's, and
    it opens only while nothing the author did can be behind it. BACKLOG
    S4, Month_of_birth, 2026-09-15: a proposal turned out to be wrong
    before the author had looked at it, and every command refused the
    rebuild — `build --allow-pending-working` then failed on `drift`,
    whose advice was to baseline the unaccepted proposal as the truth,
    and `promote` wanted a base both the live file and the new batch
    answered to. The way out was a rescue copied over the manuscript by
    hand, after three hashes were checked by eye.

    So the three hashes are checked here, and it refuses unless all hold:

    * the manuscript is byte for byte the NEWEST kept redline — the last
      promote's bytes, untouched. A file the author has opened and saved
      is theirs, whatever they did in it;
    * that proposal was built on the CURRENT baseline: its stamp says so
      (`guard.base_of`), or — for the unstamped, hand-authored vehicle —
      a rescue holds the baseline's bytes, which is the promote saying
      what it replaced. Without one of them `prev` is not provably the
      file the promote replaced, and copying it back would put another
      generation on the paper;
    * Word does not hold the file.

    Then `prev`'s bytes go back onto the manuscript — the same bytes as
    the promote's rescue, by the check `promote` makes before it copies
    — and the stamp beside it, which described the proposal, is removed.
    The redline stays in ``build/redlines/`` (that folder is the record
    of what each round offered, withdrawn or not), and ``build/batch.docx``
    is removed when it IS the withdrawn proposal: staged, it would be read
    by `verdict` as this round's batch, and the author's next save logged
    as that batch "rejected in full". A batch rebuilt before withdrawing
    is left where it is.

    `why` goes into the ledger beside the hashes.
    """
    live = paper.working
    for candidate in (live, paper.prev):
        if not candidate.exists():
            raise ProtocolError(f"missing: {candidate}")
    kept = paper.redlines()
    if not kept:
        raise ProtocolError(
            f"nothing has been promoted onto {live.name}: "
            f"{paper.redline_dir.name}/ keeps no redline, so there is no "
            f"proposal here to withdraw.")
    newest, live_hash = kept[-1], _guard.sha256(live)
    if _guard.sha256(newest) != live_hash:
        raise ProtocolError(
            f"{live.name} is no longer the batch the last promote put on it "
            f"({newest.name}): it has been opened and saved since, or that "
            f"proposal was adjudicated already, and whatever the author did "
            f"in it is theirs. Withdrawing is only for a proposal nobody has "
            f"opened.")
    if package.is_locked(live):
        raise DocumentLocked(
            f"{live.name} is open in Word. Close it first — a copy made "
            f"now would be overwritten the moment Word saves.")

    base_hash = _guard.sha256(paper.prev)
    built_on = _guard.base_of(live)
    proved = built_on == base_hash or (
        built_on is None
        and any(_guard.sha256(r) == base_hash for r in rescues(paper)))
    if not proved:
        raise ProtocolError(
            f"{newest.name} was not built on {paper.prev.name} as it stands "
            f"— "
            + (f"its stamp names {built_on[:16]}, and the baseline is "
               f"{base_hash[:16]}" if built_on is not None
               else "it carries no stamp, and no rescue copy holds the "
                    "baseline's bytes")
            + f". Putting {paper.prev.name} back would not restore the "
            f"file that promote replaced. Restore the right copy from "
            f"{paper.rescue_dir.name}/ by hand, then rebuild.")

    shutil.copyfile(paper.prev, live)
    if _guard.sha256(live) != base_hash:
        raise ProtocolError(
            f"the copy did not land: {live} — {newest.name} still holds the "
            f"proposal")
    _guard.stamp_path(live).unlink(missing_ok=True)

    removed = paper.batch.is_file() and _guard.sha256(paper.batch) == live_hash
    if removed:
        paper.batch.unlink()
        _guard.stamp_path(paper.batch).unlink(missing_ok=True)

    _ledger.record(paper, _ledger.WITHDRAWN,
                   batch=newest.name, withdrawn_sha256=live_hash,
                   restored_sha256=base_hash, onto=live.name,
                   removed_batch=removed, why=why)
    return WithdrawReport(withdrawn=newest, onto=live, removed_batch=removed,
                          why=why)
