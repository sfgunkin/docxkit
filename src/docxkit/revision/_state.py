"""Truth or proposal: which of the two states a file is in.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import footnotes, package, revisions
from .._xml import DOCUMENT, ENDNOTES, FOOTNOTES, Parts
from ._common import SAVE_NOISE, TEXT_PARTS
from ._config import Paper

# ---------------------------------------------------------------- state

@dataclass(frozen=True)
class State:
    """Which of the two states a file is in, and where the proof is."""

    path: Path
    by_part: dict[str, int]
    by_author: dict[str, int]
    #: kind -> the note ids whose DEFINITION is out of reference order.
    #: Empty for a file Word wrote; see :func:`footnotes.out_of_order`
    #: for what a file it did not costs.
    notes_unordered: dict[str, list[str]] = field(default_factory=dict)
    #: Of the pending revisions, the ones no path through this toolkit
    #: can clear: element name -> how many
    #: (:data:`revisions.WORD_ONLY`). They are counted in `pending` as
    #: well, because they ARE open verdicts — a baseline taken with one
    #: standing hands the next Compare a proposal to flatten, exactly as
    #: an insertion would. What is separate is WHOSE they are to
    #: resolve: `accept` and `reject` leave a `w:cellMerge` where it
    #: was, so the author's only way out is Word, and a refusal that
    #: repeats the count without saying so sends them looking for a flag
    #: that does not exist (BACKLOG S1, 2026-09-18).
    word_only: dict[str, int] = field(default_factory=dict)
    #: Was this read from a COPY, because Word holds the file? A
    #: snapshot mid-edit is a true statement about a moment and the
    #: alternative was no answer at all — but the reader has to be told
    #: which one they are looking at.
    from_snapshot: bool = False

    @property
    def pending(self) -> int:
        return sum(self.by_part.values())

    @property
    def is_truth(self) -> bool:
        return self.pending == 0

    @property
    def label(self) -> str:
        return "truth" if self.is_truth else "proposal"

    @property
    def hidden(self) -> int:
        """Pending revisions the author cannot reach with Review > Next.

        Reported separately because "there are 4 left" sends an author
        looking through the body for something that is in a footnote.
        """
        return sum(n for part, n in self.by_part.items()
                   if part != DOCUMENT)


_AUTHOR_RE = re.compile(r'w:author="([^"]*)"')


def state(path: str | Path) -> State:
    """Count the pending revisions in every text-bearing part.

    Every KIND of pending revision, via ``revisions.revision_elements``.
    This counted `<w:ins ` and `<w:del ` itself, which meant a manuscript
    whose only open change was a MOVE or a FORMATTING one — `w:moveTo`,
    `w:rPrChange`, `w:pPrChange`, `w:sectPrChange` — reported "0 pending
    -> TRUTH" and was treated as settled. `revisions` already had the
    full list, and said in a comment why the short one is wrong; the
    protocol's own truth test was the place still using it.
    """
    path = Path(path)
    # READ-ONLY, and the moment it is most worth running is while the
    # author has the file open in Word — so a lock takes a snapshot and
    # says so rather than refusing (see `package.readable`).
    with package.readable(path) as (readable, snapshot):
        parts = package.read_parts(readable)
    return _state(parts, path, snapshot)


def _state(parts: Parts, path: Path, snapshot: bool) -> State:
    """:func:`state` over parts already read.

    The state a caller reports has to name the AUTHOR'S file. `ingest`
    called `state(live)` with the snapshot copy it was reading from, so
    the report came back pointing at
    `<temp>/docxkit_snapshot_xxxx/working.docx` — deleted the moment
    the context manager closed — and said `from_snapshot=False` inside a
    report whose own flag said True. Two flags on one report, disagreeing
    about the same fact.
    """
    by_part: dict[str, int] = {}
    by_author: dict[str, int] = {}
    word_only: dict[str, int] = {}
    for name in TEXT_PARTS:
        blob = parts.get(name)
        if not blob:
            continue
        xml = blob.decode("utf-8", "replace")
        # count the elements, not the authors: a single <w:ins> may hold
        # several runs, and every one of them carries the attribute
        found = revisions.revision_elements(xml)
        if found:
            by_part[name] = len(found)
        for chunk in found:
            who = _AUTHOR_RE.search(chunk)
            if who:
                by_author[who.group(1)] = by_author.get(who.group(1), 0) + 1
        # `revisions` names the kinds; reading them off the tag here as
        # well was one rule in two places, and `revision/_build` wanted
        # the third copy (BACKLOG S1).
        for kind, n in revisions.revision_kinds(xml).items():
            if kind in revisions.WORD_ONLY:
                word_only[kind] = word_only.get(kind, 0) + n
    unordered = {}
    doc = parts.get(DOCUMENT, b"").decode("utf-8", "replace")
    for kind, part in (("footnote", FOOTNOTES), ("endnote", ENDNOTES)):
        blob = parts.get(part)
        if not blob:
            continue
        moved = footnotes.out_of_order(
            doc, blob.decode("utf-8", "replace"), kind=kind)
        if moved:
            unordered[kind] = moved
    return State(path=path, by_part=by_part, by_author=by_author,
                 notes_unordered=unordered, word_only=word_only,
                 from_snapshot=snapshot)


def _drifted(before: Parts, after: Parts) -> list[str]:
    """Which parts differ in MEANING, save-noise excluded."""
    parts = package.changed_parts(before, after)
    return sorted(name for bucket in ("changed", "added", "removed")
                  for name in parts[bucket] if name not in SAVE_NOISE)


def drift(working: str | Path, prev: str | Path) -> list[str]:
    """Which parts of the live file the baseline no longer matches.

    "Is anything still pending?" and "is the baseline still the file this
    one grew out of?" look like one question and are two. :func:`state`
    answers only the first, so the moment the author accepts everything
    in Word and saves, BOTH files read 0 pending -> truth while their
    content has diverged — ``prev.docx`` is still the pre-accept copy.
    A batch built then is built on a stale base, and nothing says so
    until ``promote`` refuses on a hash mismatch, *after* a Word Compare
    has been paid for.

    The accept is not the only way in. A batch whose revisions are all
    math-resolved leaves nothing pending either, so ``prev`` goes stale
    the instant that batch is promoted.

    Read-only, and compares MEANING rather than bytes
    (:func:`package.part_fingerprint`), skipping :data:`SAVE_NOISE` —
    a Word save re-mints rsids and the editing-time total in every
    round-trip, and a staleness warning that fires on all of them is one
    nobody reads.

    Returns the part names, because a warning is worth little without
    WHERE: ``word/document.xml`` is an edit to the paper, while
    ``word/footnotes.xml`` alone is one to a note.
    """
    return _drifted(package.read_parts(Path(prev)),
                    package.read_parts(Path(working)))


@dataclass(frozen=True)
class StatusReport:
    """Where a paper is — the answer `docxkit revision status` renders.

    The DECISIONS live here and the CLI prints them. They lived in
    `cli.cmd_revision_status` until 2026-09-01, which is where the
    locked-file drift defect (BACKLOG, S4, `39fe472`) was fixed — in a
    command function, tested through `argv`, with the exit code as the
    only contract a script could read. The first command moved out of
    `cli.py` under the structural review of the same day; the shape is
    the template for the rest.
    """

    working: State
    prev: State | None
    """None when there is no baseline yet."""
    drift_checked: bool
    """False when the file was open in Word: the counts above came from
    a snapshot and `drift` needs the saved bytes, so the second question
    was not asked. Named rather than inferred — the locked output used
    to have the exact shape of a healthy, current baseline."""
    stale: tuple[str, ...] = ()
    """Parts the baseline no longer matches, when the check ran."""

    @property
    def exit_code(self) -> int:
        """0 settled AND current; 1 pending, or unchecked; 4 stale.

        The contract scripts read. A run that could not ask the drift
        question does not exit 0 — 1 is what the lock produced before
        the check was named, so nothing gating on the command changes
        its mind.

        A file whose pending revisions include one only Word can clear
        (:attr:`State.word_only`) exits 1 too, and that is a decision:
        an exit code says what to DO, and there is nothing new to do.
        The file is a proposal, it must not be built on or baselined,
        and the author resolves it — which is true of every pending
        revision, because this tool never adjudicates on their behalf.
        A code of its own would send a paper that is merely waiting for
        its author down whatever branch a script keeps for codes it
        does not know. What that case needs is the explanation, and
        that is what `word_only` carries into the report and into the
        refusals that read it.
        """
        if self.stale:
            return 4
        if not self.drift_checked or not self.working.is_truth:
            return 1
        return 0


def status(paper: Paper) -> StatusReport:
    """Truth or proposal, and is the baseline still the file it grew from?

    Two questions, and the second is only asked of a settled file: while
    a proposal is pending the two files are SUPPOSED to differ, and
    saying so every time is how a warning stops being read.
    """
    working = state(paper.working)
    if not paper.prev.exists():
        return StatusReport(working=working, prev=None, drift_checked=True)
    prev = state(paper.prev)
    if working.from_snapshot:
        return StatusReport(working=working, prev=prev, drift_checked=False)
    stale = drift(paper.working, paper.prev) if working.is_truth else []
    return StatusReport(working=working, prev=prev, drift_checked=True,
                        stale=tuple(stale))
