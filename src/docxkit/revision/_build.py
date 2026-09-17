"""Clean edit -> redline, via Word Compare.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import footnotes, package, revisions, tracked
from .._xml import DOCUMENT, ENDNOTES, FOOTNOTES, text_parts
from ..errors import (
    BaselinePending,
    MathResolved,
    ProtocolError,
    StaleBatch,
    WorkingPending,
)
from ..tracked import _simulate, untracked
from . import _ledger, _timing
from ._config import Paper
from ._losses import (
    emptied_footnotes,
    links_in_deletions,
    moved_footnotes,
    restored_bookmarks,
)
from ._state import drift

# ---------------------------------------------------------------- build


def _pending(parts: dict[str, bytes]) -> dict[str, int]:
    """What is pending in this package, by kind — EVERY kind.

    Both of this module's pending refusals read
    `tracked.package_counts(...)["insertions"]` and `["deletions"]`
    until 2026-09-18, and those are two substring counts: `<w:ins ` and
    `<w:del `. There are fourteen kinds in
    :data:`revisions._REVISION_NAMES`, so a baseline or a manuscript
    whose only open change was a move, a formatting change or one of the
    cell revisions passed BOTH refusals — while `baseline`, which asks
    `state`, refused the same file. Compare was then handed an
    unadjudicated verdict and flattened it: the author was never offered
    the change, and the redline that came back did not contain it as a
    proposal (BACKLOG S1).

    The same question `state` answers, over parts already read — the
    caller has them, and reading the file twice to ask one question of
    it is how the two counts drifted apart in the first place.
    """
    found: dict[str, int] = {}
    for _name, xml in text_parts(parts):
        for kind, n in revisions.revision_kinds(xml).items():
            found[kind] = found.get(kind, 0) + n
    return found


def _listed(kinds: dict[str, int]) -> str:
    """`w:pPrChange (1), w:rPrChange (35)` — what a refusal must name.

    "36 pending revision(s)" over a file whose changes are all
    formatting sends an author through the body hunting for an
    insertion that is not there: ten of the fourteen kinds are
    invisible in Simple Markup until they go looking. The same reason
    `baseline`'s refusal names them (2026-09-18).
    """
    return ", ".join(f"w:{kind} ({n})" for kind, n in sorted(kinds.items()))


def _word_only_note(kinds: dict[str, int]) -> str:
    """The sentence for pending kinds no path through this tool clears.

    `accept` and `reject` leave a `w:cellMerge` exactly where it was
    (:data:`docxkit.revisions.WORD_ONLY`), so "have the author accept or
    reject first" is advice they cannot take, and the reader goes
    looking for the docxkit flag that settles it. There is none.
    `--allow-pending-*` is not it either: that builds ON the open
    verdict, which is what the refusal is about.

    Empty when the file carries none, because a sentence about a kind
    that is not there sends a reader to Word for an insertion they can
    resolve where they are.
    """
    only = _listed({k: n for k, n in kinds.items()
                    if k in revisions.WORD_ONLY})
    if not only:
        return ""
    return (f"\nOf those, only Word can clear {only}: `accept` and "
            f"`reject` here leave that kind standing, so no docxkit "
            f"command settles it. Open the file in Word, accept or "
            f"reject the table change there, and save.")


@_timing.timed("build")
def build(paper: Paper, revised: str | Path, out: str | Path | None = None,
          *, allow_math_resolve: bool = False,
          allow_pending_baseline: bool = False,
          allow_pending_working: bool = False,
          allow_stale_baseline: bool = False, resolve_math: bool = True,
          moves: bool = True, force: bool = False,
          progress: Any = None) -> tracked.BuildReport:
    """Clean-build plus Word Compare: a redline from an edited copy.

    Edit ``build/prev.docx`` into `revised` normally — no revision
    bookkeeping, no ``w:id`` collisions, no insert-then-delete ordering
    — and let Word's ``CompareDocuments`` derive the redline. This is
    the default path because hand-authored ``w:ins``/``w:del`` is the
    historical source of "Word says the file is corrupted": it failed to
    open on one paper four times and on another once.

    It is NOT the whole answer, and the exception is measured rather
    than suspected. On a real batch that converted five plain-text
    subscripts to OMML::

        hand-authored     4 w:ins + 4 w:del   reject-all == baseline  OK
        clean + compare   0 w:ins + 4 w:del   reject-all == baseline  FAIL

    Word cannot serialize tracked math, so the new equation is simply
    present in the deliverable with no insertion to review. Hence the
    two refusals below: a batch that touches equations must be authored
    by hand instead, and one built on a baseline that still carries
    pending revisions must wait for the author to adjudicate them.

    `resolve_math=False` is the third answer to the first of those, and
    the one to try first now: it leaves the equation revisions TRACKED
    rather than accepting them, so there is something to review and
    reject-all still restores the baseline. It is off by default only
    because the premise above held for years on Word's own save path;
    the Flat OPC route this build uses carried 1870 tracked revisions
    with the math kept on LI7 (2026-08-15), reject-all included.

    A third refusal has nothing to do with equations: a baseline that is
    no longer the generation the manuscript grew out of
    (:func:`drift`). `allow_stale_baseline=True` overrides it, and
    almost nothing should: the redline would present the author's own
    edits as the agent's proposals, and `promote` refuses such a batch
    on the hash anyway — one Word Compare later.
    `allow_pending_baseline` implies it, because a baseline that
    legitimately carries a proposal CANNOT match a clean manuscript —
    they are two names for one unusual state, and refusing the second
    after being told about the first is a gate arguing with its own
    override.

    `moves=False` takes Word's move detection out of the comparison.
    A round that RELOCATES a passage is the case for it: move detection
    is a heuristic, and on Aging_Well (2026-08-31) a batch moving ~200
    characters and five inline equations out of a section and into an
    appendix accepted to a paragraph that stopped mid-sentence, losing a
    clause, a hyperlink and the sentence after it. The same pair with
    moves off reproduced it exactly. The cost is a longer redline — a
    deletion and an insertion where Word would have drawn one move — and
    that is the trade to make, because a compression round is mostly
    moves and there was no way to build one through the CLI at all.

    `force` overrides the fourth refusal — the one
    :func:`docxkit.guard.check` raises when ``build/batch.docx`` has
    changed since docxkit wrote it. That guard is what stopped a spent
    batch being silently overwritten (Parental Style 2026-08-12) and it
    is worth keeping; what was NOT worth keeping is that the message
    named ``--force`` while neither this function nor the CLI had one,
    so the only way out the reader was told about did not exist.
    """
    out = Path(out) if out else paper.batch
    # `build/batch.docx` is where a BUILT batch is staged, and the stamp
    # beside it is how `guard.check` tells "docxkit wrote this" from
    # "someone edited it in Word". A hand-built clean edit written there
    # collides with that: the build refuses its own output as modified,
    # and the message sends the reader looking for a Word session that
    # never happened (2026-08-09, a cycle to diagnose). The path is
    # reserved; say so where the mistake is made.
    if Path(revised).resolve() == out.resolve():
        raise ProtocolError(
            f"{out.name} is where `revision build` STAGES its output, so it "
            f"cannot also be the clean edit it builds FROM — the provenance "
            f"stamp beside it would read the edit as a Word session. Write "
            f"the clean edit anywhere else in build/ (build/clean.docx is "
            f"the usual name) and pass that.")

    pending = _pending(package.read_parts(paper.prev))
    if pending and not allow_pending_baseline:
        raise BaselinePending(
            f"{paper.prev.name} still carries {sum(pending.values())} "
            f"pending revision(s) — {_listed(pending)}. Word "
            f"Compare rebuilds the redline from ACCEPTED content, so "
            f"those would be flattened into plain text and could never "
            f"be rejected — the author's open verdicts decided for them. "
            f"Have them accept or reject first."
            + _word_only_note(pending))

    # The same question of the LIVE file, and it is the commoner way to
    # the same harm. Promote a batch, have the author not adjudicate it
    # yet, pick up the next protocol: `prev` is clean, `working` carries
    # the proposal, and what happens depends on which file the caller
    # stages as the clean edit. From `prev`, the new round is built on
    # the PREVIOUS truth and the pending batch drops out of the redline
    # entirely; from `working`, Compare is handed revision marks and
    # flattens the batch in as accepted, unreviewable text. Either way
    # an author's open verdict is decided for them.
    #
    # It has to come BEFORE the drift check, which fires on this state
    # too — a pending working file cannot match a clean baseline — and
    # says the wrong thing about it. Measured 2026-09-02: `StaleBatch`
    # sends the reader to `revision baseline`, and `baseline` REFUSES a
    # file carrying a proposal. The advice was a loop.
    live = _pending(package.read_parts(paper.working)) \
        if paper.working.exists() else {}
    if live and not allow_pending_working:
        raise WorkingPending(
            f"{paper.working.name} still carries {sum(live.values())} "
            f"pending revision(s) — {_listed(live)} — a batch "
            f"the author has not adjudicated. Building the next round now "
            f"either drops it from the redline (if the clean edit came "
            f"from {paper.prev.name}) or flattens it in as accepted, "
            f"unreviewable text (if it came from {paper.working.name}). "
            f"Either way their open verdict is decided for them."
            + _word_only_note(live) + "\n"
            "    docxkit revision status     (where this round stands)\n"
            "then have the author accept or reject, and\n"
            "    docxkit revision baseline   (adopt the result)\n"
            "before building again.")

    # Is the baseline still the file the manuscript grew out of? The
    # check above asks whether `prev` carries a proposal; this asks
    # whether it is the right generation at all. `drift`'s own docstring
    # named this gap and nothing closed it: after an accept in Word both
    # files read 0 pending while their content has diverged, and the
    # redline built then shows the AUTHOR's edits as the agent's
    # proposals. `promote` refuses it on the hash — but only after a
    # full Word Compare has been paid for, and after a reader has spent
    # the round trying to make sense of a redline about the wrong pair.
    if not (allow_stale_baseline or allow_pending_baseline) \
            and paper.working.exists() and paper.prev.exists() \
            and (moved := drift(paper.working, paper.prev)):
        listed = ", ".join(moved[:4])
        if len(moved) > 4:
            listed += f" and {len(moved) - 4} more"
        raise StaleBatch(
            f"{paper.prev.name} is no longer what {paper.working.name} "
            f"grew out of — {listed} differ(s). Something was "
            f"accepted or edited since the last baseline, so a redline "
            f"built on this baseline would present the author's own "
            f"changes as proposals, and `promote` would refuse it on the "
            f"hash afterwards. First:\n"
            f"    docxkit revision ingest     (what changed, read-only)\n"
            f"    docxkit revision baseline   (adopt it as the truth)\n"
            f"then build again.")

    notes: list[str] = []

    def _say(line: str) -> None:
        notes.append(line)
        if progress:
            progress(line)

    # Before Word sees it: a note whose DEFINITION sits out of reference
    # order renders correctly and passes every read-only gate, and
    # Compare then rewrites the definitions INTO document order — so the
    # part no longer lines up with the baseline's and reads as moved. On
    # AFI that was 81 glyph runs and a STRUCTURE count for a one-line
    # prose batch, reported against the batch that came after the one
    # that appended the note. Said here, where it is still cheap.
    for side, path in (("baseline", paper.prev), ("clean edit", revised)):
        side_parts = package.read_parts(path)
        doc = side_parts.get(DOCUMENT, b"").decode("utf-8", "replace")
        for kind, part in (("footnote", FOOTNOTES), ("endnote", ENDNOTES)):
            blob = side_parts.get(part)
            if not blob:
                continue
            moved = footnotes.out_of_order(
                doc, blob.decode("utf-8", "replace"), kind=kind)
            if moved:
                _say(f"{side}: {kind} definitions are not in document order "
                     f"({', '.join(moved[:6])}"
                     f"{' ...' if len(moved) > 6 else ''}) — Word's Compare "
                     f"will rewrite them, and the whole part then reads as "
                     f"MOVED. Reorder the definitions to match the "
                     f"references before building.")

    # `accept_check` is left ON, and the asymmetry is deliberate. The
    # reject side has a legitimate cause the protocol can see and gate 5
    # can judge (below); the accept side has none — a redline whose
    # accepted text is not the clean copy is not a batch to hand back,
    # and no later gate looks at that view.
    #
    # `reject_check=False` — the refusal, not the check: `tracked.build`
    # computes it either way and its notes come through `_say`. The
    # protocol REPORTS an unrejectable paragraph and lets gate 5 decide,
    # because one cause of it is legitimate and only visible from here:
    # a moved footnote REFERENCE makes Compare emit the whole note as an
    # insertion, so rejecting empties it. Refusing to produce the batch
    # would leave the author with the paragraph names and no file to look
    # at. A paper calling `tracked.build` directly has no gate 5, which
    # is why the default there is to refuse.
    _timing.mark("preflight")
    report = tracked.build(paper.prev, revised, out, None,
                           author=paper.author, verify_in_word=True,
                           resolve_math=resolve_math, moves=moves,
                           reject_check=False,
                           force=force, progress=_say,
                           carry=tracked.CARRIED_PARTS + paper.carry,
                           # `[batch] word_deadline`; 0 is no ceiling
                           word_deadline=paper.word_deadline or None)
    # The one mark that has already earned its place. Measured from
    # outside on Aging_Well, 2026-09-07: this call was 141s on the first
    # build of a session and 40s on the second, same manuscript — the
    # difference being Word's cold start, which nothing downstream can
    # see and no other step pays.
    _timing.mark("compare")

    for name in restored_bookmarks(package.read_parts(paper.prev),
                                   package.read_parts(revised),
                                   package.read_parts(out)):
        _say(f"bookmark {name!r}: your clean edit removed it and Compare "
             f"put it back — a bookmark is carried over from the ORIGINAL "
             f"side and cannot ship through a redline. Apply the deletion "
             f"to working.docx AFTER the promote; the revision count is "
             f"unaffected, a bookmark is not tracked content.")

    # Said HERE and not at the end of the ladder. By then the author has
    # a batch to throw away and the only act available to them is the
    # one this sentence would have prevented.
    if carried := links_in_deletions(package.read_parts(out)):
        targets = ", ".join(sorted({a for a, _ in carried})[:4])
        _say(f"{len(carried)} link(s) sit inside a tracked deletion "
             f"({targets}{' ...' if len(carried) > 4 else ''}) — Compare "
             f"does not track an anchor, so REJECTING one of these "
             f"restores its words as plain text and does not rebuild the "
             f"link. Accept-all is unaffected; gate 5 is not. Measured: "
             f"the same clause moved across a section fails, and folded "
             f"into the paragraph above it passes, because only the "
             f"DISTANCE changed. Shorten the move, or mint the links "
             f"after the handback.")

    # What Compare baked in with no revision on it, named paragraph by
    # paragraph. The math count alone understated this badly: a merged,
    # rewritten math-bearing paragraph shipped WHOLE and untracked while
    # the batch read "7 revisions, 6 of them in the body". Read off the
    # WRITTEN file, so what is said describes the deliverable the author
    # is about to open rather than the parts that made it.
    base_parts = package.read_parts(paper.prev)
    built = package.read_parts(out)
    lost = untracked(built, base_parts)
    # The shape Compare leaves, and then whether it MATTERS. Warning on
    # the shape alone said "gate 5 will fail on it" about notes gate 5
    # went on to pass, twice on Aging_Well — a prediction the toolkit's
    # own reject-all layer contradicts, printed where it reads as
    # blocking. Rejecting here costs an in-memory XML pass beside a
    # Word Compare that costs 40-141s.
    if (shaped := moved_footnotes(built, base_parts)):
        emptied = emptied_footnotes(_simulate(built, revisions.reject),
                                    base_parts, shaped)
        for note in emptied:
            _say(f"footnote {note}: Compare emitted the whole note as an "
                 f"insertion with no matching deletion — its REFERENCE "
                 f"moved, and rejecting MEASURABLY empties it, so gate 5 "
                 f"will fail on it. Accepting is right.")
        for note in (n for n in shaped if n not in emptied):
            _say(f"footnote {note}: Compare emitted the whole note as an "
                 f"insertion with no matching deletion — its REFERENCE "
                 f"moved. Reject-all restores it here, so gate 5 is not "
                 f"at risk from this one; nothing to do.")
    for u in lost:
        _say(f"UNTRACKED {u}")
    if lost:
        _say(f"{len(lost)} paragraph(s) above differ from the baseline "
             f"with no revision on them: the author cannot refuse those "
             f"edits, and reject-all will not restore the baseline.")

    # The REPORT's own number, not a grep over the progress lines. The
    # note it used to match is a sentence `tracked.build` is free to
    # rewrite, and rewriting it would have disabled this refusal in
    # silence — a guard whose trigger is another module's prose is a
    # guard that stops guarding without anybody editing it.
    if report.math_resolved and not allow_math_resolve:
        raise MathResolved(
            f"{report.math_resolved} math revision(s) were accepted while "
            f"building {out.name}: those edits are baked in with nothing "
            f"to accept or reject, and reject-all will not restore the "
            f"baseline. This batch has NO reviewable redline as built. "
            f"Three ways on, in order: rebuild with "
            f"resolve_math=False, which keeps them tracked and is what "
            f"the Flat OPC route measured on LI7 supports; ship the batch "
            f"clean and record that in the log; or make the edit by "
            f"hand-authored markup on working.docx (the DSI vehicle).")
    # The round's record, written and not yet read — see `_ledger`. It
    # goes AFTER the refusals: a batch that was refused is not a batch
    # that was built, and a ledger that says otherwise would be worse
    # than none. `revisions` is what the author will be offered.
    _ledger.record(paper, _ledger.BUILT,
                   batch=out.name,
                   batch_sha256=_ledger.sha256_of(out),
                   base_sha256=_ledger.sha256_of(paper.prev),
                   revised=Path(revised).name,
                   revisions=report.revisions,
                   moves=moves, resolve_math=resolve_math)
    return report
