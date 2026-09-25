"""What a build did, and the refusals that read it.

Split out of ``tracked.py`` on 2026-09-11; import from
:mod:`docxkit.tracked`. :class:`BuildReport` is what :func:`tracked.build`
fills in phase by phase and hands back; :func:`_refuse_accept_side` is
the accept-side gate's voice — three questions about the ACCEPTED view,
kept together because the answer to all three is the same: that view
is what the author reads, so a difference there is not a note to print
and continue past.
"""
from __future__ import annotations

import time
from typing import NamedTuple

from . import footnotes as _footnotes
from ._tracked_gates import Unaccepted, Untracked
from .errors import PackageError

#: How to build the file anyway — and the warning that goes with it.
#:
#: It used to say "Pass accept_check=False", which is a Python keyword
#: argument. The CLI's flags are `--allow-math-resolve`,
#: `--allow-stale-baseline`, `--keep-math`, `--allow-pending-baseline`
#: and `--force`, none of which is it, so a CLI reader had been told to
#: do something the CLI does not offer — and the honest workaround,
#: writing a throwaway script that imports `docxkit.revision`, is the
#: thing the CLI exists to avoid.
#:
#: The second sentence is the half worth keeping. Met 2026-08-29 on
#: Life_Expectancy, where the refusal was RIGHT — two unterminated
#: bookmarks Compare would have dropped — and the repair was to fix the
#: manuscript, not to bypass the gate.
_ACCEPT_ESCAPE = (
    "To build it anyway and look at it, call `tracked.build(..., "
    "accept_check=False)` from Python; the CLI has no flag for this on "
    "purpose. The refusal is usually right, and the repair is usually "
    "in the manuscript rather than in the switch.")

#: The same sentence for the LINT gate, which had no escape at all.
#:
#: Found by the refusal audit of 2026-09-18: it named no action, no
#: command and no switch, and unlike its three siblings it took no
#: parameter either, so there was nothing to pass even from Python —
#: and a refused build writes nothing, so it left not so much as an
#: artefact to look at. Measured over 400 real manuscripts, 20 carry a
#: finding of a class no docxkit verb repairs (empty `m:oMath` shells,
#: empty `w:ins`/`w:del`), which is how reachable the dead end was.
#:
#: What the escape COSTS is spelled out rather than implied, because
#: this gate's claim is the strongest one in the build: not that the
#: deliverable is wrong, but that Word will refuse to open it.
_LINT_ESCAPE = (
    "To build it anyway and look at it, call `tracked.build(..., "
    "lint_check=False)` from Python; the CLI has no flag for this on "
    "purpose. What that costs is this gate's whole claim: the package "
    "may be one Word will not open at all, and the findings above are "
    "the classes that say so here rather than in a dialog on a "
    "reader's screen.")


def _also_unaccepted(report: BuildReport) -> str:
    """The paragraphs, when the ANCHOR refusal fires ahead of them.

    An anchor does not go missing on its own: it goes with the words
    that carried it. On Aging_Well (2026-08-31) a scored move truncated
    a paragraph in the accepted view — a clause, a link and the sentence
    after it — and the build refused with `link LOST on accept: ->
    Ravallion2011`, which names the smallest visible symptom of it. The
    reader spends the round on the link.

    So when both findings are present, the anchor refusal carries the
    paragraphs too, and names the switch that fixed that case.
    """
    if not report.unaccepted:
        return ""
    listed = "\n  ".join(str(u) for u in report.unaccepted)
    return (f"\n{len(report.unaccepted)} paragraph(s) also differ, and they "
            f"are the finding to read first — an anchor goes missing with "
            f"the words that carried it:\n  {listed}\n"
            f"Word's move detection can truncate a paragraph it scored as "
            f"moved. If this round relocated a passage, rebuild with "
            f"moves=False (`revision build --no-moves`) before looking "
            f"anywhere else. ")


def _refuse_accept_side(report: BuildReport, revised: str, *,
                        math_only: bool = False) -> None:
    """Raise for whatever the ACCEPTED view does not reproduce.

    Three questions about one view, kept together because the answer to
    all three is the same: the accepted document is what the author
    reads, so a difference there is not a note to print and continue
    past. They are separate checks because each is blind to the others —
    the text comparison cannot see an anchor, the anchor comparison
    cannot see a number, and neither reads `m:t`.

    `math_only` runs the last of them alone, because the equations can
    only be judged after the glyph restore.
    """
    if not math_only and report.accepted_losses:
        listed = "\n  ".join(report.accepted_losses)
        raise PackageError(
            f"accepting every revision LOSES anchors the clean copy "
            f"has:\n  {listed}\n"
            f"A bookmark and a hyperlink carry no text, so the paragraph "
            f"comparison beside this one cannot see them go, and they "
            f"are present in the redline as built — inside a deletion, "
            f"until the author accepts it. " + _also_unaccepted(report)
            + _ACCEPT_ESCAPE)
    if not math_only and report.orphan_notes:
        listed = "\n  ".join(str(o) for o in report.orphan_notes)
        raise PackageError(
            f"accepting every revision leaves {len(report.orphan_notes)} "
            f"note definition(s) with nothing referencing them:\n  "
            f"{listed}\n"
            f"The marker was deleted and the words were not, so the note "
            f"is in the file and on no page. Delete the note in the CLEAN "
            f"copy — reference and definition together, which is what "
            f"Word does when you delete the marker — and rebuild. "
            + _ACCEPT_ESCAPE)
    if not math_only and report.unaccepted:
        listed = "\n  ".join(str(u) for u in report.unaccepted)
        raise PackageError(
            f"accepting every revision does NOT reproduce {revised} — "
            f"{len(report.unaccepted)} paragraph(s) differ, so the "
            f"deliverable the author reads is not the document this "
            f"redline was built from:\n  {listed}\n"
            f"Word rewriting content while it derives the redline is the "
            f"usual cause, and the reject-all gate cannot see it: "
            f"rejecting deletes the insertion the damage is inside. "
            + _ACCEPT_ESCAPE)
    if report.accepted_math:
        listed = "\n  ".join(report.accepted_math)
        raise PackageError(
            f"accepting every revision does not reproduce the EQUATIONS "
            f"of {revised}:\n  {listed}\n"
            f"Word's Compare diffs inside an inline m:oMath at character "
            f"level, so a changed number can come out as the old digits "
            f"with the new ones inserted beside them. Apply the math "
            f"edit to the built batch instead. " + _ACCEPT_ESCAPE)


class BuildReport:
    """What a redline build did, and how long each phase took."""

    def __init__(self) -> None:
        #: Every pending revision the built package carries, of every
        #: kind and in every text-bearing part. Word's own
        #: `Revisions.Count` — which is what this used to hold — walks
        #: the MAIN STORY only, so a batch of 25 footnote formatting
        #: revisions reported 0 and read as a Compare that had failed.
        #: Kept beside it as `body_revisions`, labelled, because the two
        #: disagreeing is worth seeing rather than resolving silently.
        self.revisions = 0
        self.body_revisions = 0
        self.math_resolved = 0
        #: Revisions that TOUCH an equation and were left tracked because
        #: they are not of it. Accepting these is what cost LI7 315
        #: revisions — see :func:`_accept_math_via_equations`.
        self.math_kept = 0
        self.comments_added = 0
        self.unclassified = 0
        self.comments_total = 0
        self.verified_comments: int | None = None
        self.verified_revisions: int | None = None
        #: What Word refused to do. Every COM call here is wrapped in a
        #: suppression because one hostile revision must not abort a
        #: 1400-revision build — but suppressing SILENTLY let a
        #: half-finished build report success-shaped numbers, so what
        #: was swallowed is recorded and printed.
        self.suppressed: list[str] = []
        #: What Word's Compare removed rather than carried over — parts,
        #: bookmarks, links. See :func:`compare_collateral`. Advisory:
        #: some of it is legitimate tidying, and only a person can tell.
        self.dropped: list[str] = []
        #: What the offline lint found in the assembled package — the
        #: "Word says the file is corrupted" classes, caught before
        #: anything is written. Always computed, like the two gates
        #: below: `lint_check` turns off the REFUSAL, not the check, so
        #: a build that asked for the artefact still carries the reason
        #: it was refused.
        self.lint: list[str] = []
        #: Paragraphs a reject-all does not restore. Always computed, so
        #: the report carries the finding either way; NOT advisory when
        #: `reject_check` is on, which is the default — the build then
        #: refuses to publish while this is non-empty.
        self.unrejectable: list[Untracked] = []
        #: Paragraphs an accept-all does not reproduce from the CLEAN
        #: copy. Always computed, and not advisory while `accept_check`
        #: is on: a defect Compare baked into an insertion is invisible
        #: to `unrejectable`, because rejecting deletes the insertion
        #: before that comparison happens. See :func:`unaccepted`.
        self.unaccepted: list[Unaccepted] = []
        #: The glyph-less carriers — tables, rows, section breaks by
        #: count, bookmarks by NAME — that the built redline does not
        #: resolve back to the documents it came from. See
        #: :func:`structure_counts` and :func:`bookmark_changes`.
        self.structure_diff: list[str] = []
        #: Equations the ACCEPTED view does not reproduce from the
        #: clean copy. Refused with `accept_check`. See
        #: :func:`accepted_math`.
        self.accepted_math: list[str] = []
        #: Bookmarks and internal links the CLEAN copy has and the
        #: ACCEPTED view does not. Refused with `accept_check`, because
        #: the accepted view is the deliverable. See
        #: :func:`accepted_losses`.
        self.accepted_losses: list[str] = []
        #: Note definitions the ACCEPTED view keeps with nothing left
        #: pointing at them, and words still in them: a footnote whose
        #: marker went and whose text stayed, which renders nowhere and
        #: reads as lost. The empty shells accepting leaves behind are
        #: pruned instead — see :func:`_simulate` and
        #: :func:`docxkit.footnotes.orphans`.
        self.orphan_notes: list[_footnotes.Orphan] = []
        #: Part-trees Compare dropped and the build put BACK — the
        #: customXml data store, by default. See
        #: :func:`docxkit.hygiene.restore_parts`.
        self.carried: list[str] = []
        #: Part-trees neither the redline NOR the clean copy still has,
        #: taken from the BASELINE. Named apart from `carried` because
        #: it is a different sentence: this build went back a version
        #: for these, and that is the one case where an author might
        #: want to look. See the note on the fallback in `build`.
        self.carried_from_baseline: list[str] = []
        #: Core properties Compare's regenerated ``docProps/core.xml``
        #: no longer carried, and the build copied back by VALUE. See
        #: :func:`docxkit.hygiene.carry_properties`.
        self.carried_properties: list[str] = []
        #: Math runs whose glyph Word flattened while rewriting the
        #: OMML, put back from what a source really spells. See
        #: :func:`docxkit.hygiene.restore_math_glyphs`.
        self.restored_glyphs: list[str] = []
        #: Spaces Compare deleted after a note mark and the build gave
        #: back. See :func:`return_note_spaces`.
        self.returned_spaces: list[str] = []
        #: Comments Compare kept TWICE because both inputs carried them.
        #: See :func:`docxkit.hygiene.dedupe_comments`.
        self.deduped_comments: list[str] = []
        self.phases: list[tuple[str, float]] = []
        self._t0 = self._last = time.perf_counter()

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self.phases.append((label, now - self._last))
        self._last = now

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self._t0

    def format(self) -> str:
        lines = [f"  [{secs:6.1f}s] {label}" for label, secs in self.phases]
        lines.append(f"revisions {self.revisions}, comments "
                     f"{self.comments_total} ({self.unclassified} "
                     f"unclassified), {self.seconds:.0f}s total")
        if self.suppressed:
            lines.append(f"  {len(self.suppressed)} Word call(s) failed "
                         "and were skipped:")
            lines += [f"    - {note}" for note in self.suppressed[:10]]
            if len(self.suppressed) > 10:
                lines.append(f"    ... and {len(self.suppressed) - 10} more")
        if self.math_kept:
            lines.append(f"  {self.math_kept} revision(s) overlap an "
                         "equation without being of it, and stay tracked")
        if self.carried:
            lines.append(f"  carried back across the Compare: "
                         f"{', '.join(self.carried)}")
        if self.carried_from_baseline:
            lines.append(f"  the clean copy had lost these too, so they "
                         f"come from the BASELINE: "
                         f"{', '.join(self.carried_from_baseline)}")
        if self.carried_properties:
            lines.append(f"  properties carried back into core.xml: "
                         f"{', '.join(self.carried_properties)}")
        if self.dropped:
            lines.append(f"  Word's Compare dropped {len(self.dropped)} "
                         "thing(s) the revised copy had:")
            lines += [f"    - {note}" for note in self.dropped[:10]]
            if len(self.dropped) > 10:
                lines.append(f"    ... and {len(self.dropped) - 10} more")
        return "\n".join(lines)


class MathOutcome(NamedTuple):
    """What the math pass accepted, and what it deliberately left alone."""

    accepted: int
    kept: int = 0
