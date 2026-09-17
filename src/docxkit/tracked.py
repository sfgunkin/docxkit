r"""Building a tracked-changes deliverable from two clean documents.

The journal wants a redline: the original, the revision, and — when the
paper works that way — a comment on every change saying why. The reliable
way to produce one is Word's own ``CompareDocuments``; hand-authored
``w:ins``/``w:del`` markup has failed to open in Word repeatedly across
these papers, so it is not attempted here.

Generating the redline from the two clean documents also means the two
deliverables cannot disagree: accepting every revision reproduces the
revised document by construction. Hand-authoring does not give that, and
on the Life Expectancy paper the tracked and clean files had silently
drifted apart in three paragraphs.

The pipeline:

1. Word compares the two documents (seconds).
2. The MATH revisions are resolved — accepted, and commented first if
   the paper annotates. This also leaves behind Word's own comment
   scaffold for step 4. Only revisions CONTAINED in an equation: see
   :func:`_accept_math_via_equations` for what accepting a merely
   overlapping one costs.
3. The package is extracted as Flat OPC, bypassing Word's save path.
4. Every remaining revision is commented in XML (:mod:`docxkit.comments`).
5. The result is linted, and REJECT-ALL must reproduce the original —
   a redline whose changes the author cannot refuse is the one failure
   a redline exists to prevent (:func:`untracked`).
6. The result is reopened in Word: it must read back exactly the comment
   count the package holds, or Word repaired it on open.

The premise the math step was built on — *Word cannot serialize a
compare result containing tracked math at all* — is not general. On LI7
(2026-08-15) both ``SaveAs2`` and Flat OPC serialized 1870 revisions
with the math left tracked, and both round-tripped exactly. Hence
``resolve_math=False``: a paper that has measured its own case can keep
the math tracked and lose nothing.
"""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import comments as _comments
from . import footnotes as _footnotes
from . import guard as _guard
from . import hygiene as _hygiene
from . import word as _word
from ._tracked_gates import _EQ_QUOTE as _EQ_QUOTE
from ._tracked_gates import _PART_LABELS as _PART_LABELS
from ._tracked_gates import STRUCTURE_TAGS as STRUCTURE_TAGS
from ._tracked_gates import Unaccepted as Unaccepted
from ._tracked_gates import Untracked as Untracked
from ._tracked_gates import W as W
from ._tracked_gates import _anchors as _anchors
from ._tracked_gates import _first_difference as _first_difference
from ._tracked_gates import _math_texts as _math_texts
from ._tracked_gates import _mismatched_paras as _mismatched_paras
from ._tracked_gates import _paras as _paras
from ._tracked_gates import _revision_gap as _revision_gap
from ._tracked_gates import _root as _root
from ._tracked_gates import _simulate as _simulate
from ._tracked_gates import accepted_losses as accepted_losses
from ._tracked_gates import accepted_math as accepted_math
from ._tracked_gates import compare_collateral as compare_collateral
from ._tracked_gates import package_counts as package_counts
from ._tracked_gates import revisions_by_part as revisions_by_part
from ._tracked_gates import structure_counts as structure_counts
from ._tracked_gates import structure_diff as structure_diff
from ._tracked_gates import unaccepted as unaccepted
from ._tracked_gates import untracked as untracked
from ._tracked_report import _ACCEPT_ESCAPE as _ACCEPT_ESCAPE
from ._tracked_report import _LINT_ESCAPE as _LINT_ESCAPE
from ._tracked_report import BuildReport as BuildReport
from ._tracked_report import MathOutcome as MathOutcome
from ._tracked_report import _also_unaccepted as _also_unaccepted
from ._tracked_report import _refuse_accept_side as _refuse_accept_side
from .comments import RevisionContext
from .errors import PackageError
from .lint import lint_parts
from .package import USER_PROPERTIES, read_parts, write_docx
from .revisions import accept as _accept
from .revisions import reject as _reject

# Bound directly, NOT reached through `_word`: tests replace that
# module attribute with a COM fake, and a fake has no reason to
# carry a suppression helper. The seam is for Word, not for this.
from .word import _suppress_com

# ---------------------------------------------------------------------
# The facade. `tracked.py` was one 1,494-line module until 2026-09-11;
# every name it defined stays reachable as `docxkit.tracked.<name>`,
# private helpers included, so the import path callers and tests use
# does not change. Two halves sit behind it, and they may only import
# DOWNWARDS (`tests/test_layering.py`, FACADE_HALVES): `_tracked_gates`
# (what a redline must reproduce — pure XML, no Word) and
# `_tracked_report` (what a build did, and the refusals that read it).
# What stays HERE is the Word pipeline — `build`, `verify` and the math
# pass — and that is not an accident: the suite fakes Word by rebinding
# `tracked._word`, `tracked.verify`, `tracked.package_counts` and the
# rest on THIS module, and every one of those names is read by `build`
# at call time from this module's globals. A split that moved `build`
# out would have moved the seam with it, test by test.

__all__ = [
    "CARRIED_PARTS",
    "STRUCTURE_TAGS",
    "BuildReport",
    "MathOutcome",
    "PackageError",
    "Unaccepted",
    "Untracked",
    "accepted_losses",
    "accepted_math",
    "build",
    "compare_collateral",
    "package_counts",
    "revisions_by_part",
    "structure_counts",
    "structure_diff",
    "unaccepted",
    "untracked",
    "verify",
]

#: What :func:`build` copies back from the revised input when Word's
#: Compare declines to carry it: the ``customXml/`` data store, dropped
#: on every single rebuild, and the user-defined properties, which on a
#: Bank manuscript are the sensitivity label. A paper whose Compare eats
#: something else says so once — see ``[batch] carry`` in paper.toml.
CARRIED_PARTS = (_hygiene.CUSTOM_XML, USER_PROPERTIES)


Classifier = Callable[[RevisionContext], str | None]


def _bounded(deadline: float | None, doing: str) -> dict[str, Any]:
    """The keywords for `_word.session` — only when a ceiling is asked
    for, so a caller (or a fake) that knows no `deadline` is untouched."""
    return {"deadline": deadline, "doing": doing} if deadline else {}


def verify(path: str | Path, *,
           word_deadline: float | None = None) -> dict[str, Any]:
    """Open a document in Word and report what Word actually reads back.

    The check that matters for any tracked-changes file, however it was
    produced: Word silently "repairs" markup it dislikes, and the damage
    only shows up when the editor opens the deliverable.

    Returns the counts Word reports alongside the counts the package
    contains; when they disagree, Word altered the file on open.
    `word_deadline` bounds the session (see :func:`docxkit.word.session`).
    """
    path = Path(path)
    parts = read_parts(path)
    in_package = package_counts(parts)
    with _word.session(**_bounded(word_deadline, f"verifying {path.name}")) \
            as word, _word.open_doc(word, path) as opened:
        in_word = {
            "revisions": int(opened.Revisions.Count),
            "comments": int(opened.Comments.Count),
            "paragraphs": int(opened.Paragraphs.Count),
        }
    return {
        "path": str(path),
        "package": in_package,
        "word": in_word,
        "comments_match": in_word["comments"] == in_package["comments"],
    }


def _resolve_math(doc: Any, classify: Classifier | None,
                  generic: str | None,
                  notes: list[str] | None = None) -> MathOutcome:
    """Comment (if the paper annotates) and accept the math revisions.

    Word's save path cannot always serialize a compare result containing
    tracked math, and where it cannot, these have to go. Commenting them
    is the only chance to explain an equation change, and it leaves the
    comment scaffold the XML pass clones.

    The two routes below look like duplicates and are NOT: they select
    different revisions. Walking the equations finds revisions in a math
    RANGE; asking each revision whether it contains math finds revisions
    that CONTAIN one. Substituting the first for the second on the AFI
    paper left 41 extra revisions un-accepted (291 annotated became 332),
    so each path keeps the scan it was verified with. The equation walk
    is much cheaper — ~15ms per equation against ~20ms per revision,
    which was 27s of a 1359-revision compare — and is used where no
    comments are needed and it was validated.
    """
    notes = [] if notes is None else notes
    if classify is None:
        return _accept_math_via_equations(doc, notes)
    return _comment_and_accept_math_revisions(doc, classify, generic, notes)


def _accept_math_via_equations(doc: Any,
                               notes: list[str] | None = None
                               ) -> MathOutcome:
    """Accept revisions CONTAINED in an equation, walking ``doc.OMaths``.

    CONTAINED, not overlapping, and the difference is the whole entry.
    A revision appears in an equation's ``Range.Revisions`` if it merely
    TOUCHES that range, and accepting one applies its ENTIRE span — so a
    long formatting or move revision that happens to run through an
    equation is applied whole, along with every revision inside it.

    **Measured on LI7, 2026-08-15**, one compare of the same pair: with
    the math kept tracked the package held 1870 revisions and reject-all
    reproduced the submitted paper 319/319; with the math "resolved" by
    the overlapping rule, thirteen ``Accept()`` calls left 1555 and
    reject-all FAILED on 35 units. The collateral reached the abstract,
    which contains no equation at all — its rejected text came back as
    "…in aging populations.  the theoretical foundation…", the words
    "The paper presents" simply gone and unrejectable. Nothing failed:
    the deliverable opened, the counts looked plausible, and only a
    reject-all diff against the baseline said otherwise. Hence
    :func:`untracked`, which now runs on every build.

    A revision left tracked is COUNTED and returned, not swallowed: the
    caller reports it, and if the save then refuses the math, the number
    is the first thing to look at.
    """
    notes = [] if notes is None else notes
    try:
        if not doc.OMaths.Count:
            return MathOutcome(0)
    except Exception as exc:
        notes.append(f"could not read doc.OMaths: {exc}")
        return MathOutcome(0)
    accepted = kept = 0
    for i in range(doc.OMaths.Count, 0, -1):   # backwards: accepting shifts
        try:
            math_range = doc.OMaths(i).Range
            revisions = math_range.Revisions
        except Exception as exc:
            notes.append(f"equation {i}: unreachable ({exc})")
            continue
        for j in range(revisions.Count, 0, -1):
            try:
                revision = revisions(j)
                # re-read per revision: accepting one inside the equation
                # shifts the range's own end, and a stale bound is a
                # bound that over-includes
                lo, hi = int(math_range.Start), int(math_range.End)
                span = (int(revision.Range.Start), int(revision.Range.End))
            except Exception as exc:
                notes.append(f"equation {i} revision {j}: "
                             f"could not be placed ({exc})")
                continue
            if not (lo <= span[0] and span[1] <= hi):
                kept += 1          # overlaps the equation; is not OF it
                continue
            try:
                revision.Accept()
                accepted += 1
            except Exception as exc:
                notes.append(f"equation {i} revision {j}: "
                             f"not accepted ({exc})")
    return MathOutcome(accepted, kept)


def _comment_and_accept_math_revisions(
        doc: Any, classify: Classifier, generic: str | None,
        notes: list[str] | None = None) -> MathOutcome:
    """Comment then accept each revision that CONTAINS math.

    Scans the revisions rather than the equations — see
    :func:`_resolve_math` for why the cheaper walk is not a substitute.

    This route selects a revision by what it CONTAINS, so a long one
    that runs through an equation is still applied whole, with the same
    collateral :func:`_accept_math_via_equations` documents. It is not
    narrowed here because the selection was verified revision by
    revision on AFI and narrowing it blind would change a shipped
    deliverable's shape; :func:`untracked` is what catches the case, on
    every build, before anything is published.
    """
    notes = [] if notes is None else notes
    math_revs = []
    for n, rev in enumerate(_word.revisions(doc), 1):  # enumerator: O(i)
        try:
            if rev.Range.OMaths.Count:
                math_revs.append(rev)
        except Exception as exc:
            notes.append(f"revision {n}: could not be inspected ({exc})")

    seeded = 0
    for rev in reversed(math_revs):       # last first: accepting shifts rest
        _comment_revision(doc, rev, classify, generic, notes)
        seeded += 1
        try:
            rev.Accept()
        except Exception as exc:
            notes.append(f"math revision not accepted ({exc}) — Word "
                         "cannot serialize a compare result containing "
                         "tracked math, so this build may fail to save")
    return MathOutcome(seeded or _seed_scaffold(doc, classify, generic, notes))


def _comment_revision(doc: Any, rev: Any, classify: Classifier,
                      generic: str | None,
                      notes: list[str] | None = None) -> None:
    """Attach the paper's comment to one revision, through Word."""
    notes = [] if notes is None else notes
    rng = rev.Range
    text = para = ""
    with _suppress_com("read a revision's own text"):
        text = rng.Text or ""
    with _suppress_com("read a revision's paragraph"):
        para = rng.Paragraphs(1).Range.Text or ""
    comment = classify(RevisionContext(
        text=text, para=para, window=para, table_index=None,
        start=-1, end=-1))
    # The fallback matters even when the paper passes generic=None: this
    # comment is also the scaffold the XML pass clones, and Word cannot
    # add one with no text, so the build would fail with ScaffoldMissing.
    try:
        doc.Comments.Add(rng, comment or generic or _comments.GENERIC)
    except Exception as exc:
        # NOT cosmetic: if this was to be the scaffold, the build fails
        # later with ScaffoldMissing and no hint of the real cause
        notes.append(f'comment not added to "{text[:30]}": {exc}')


def _seed_scaffold(doc: Any, classify: Classifier | None,
                   generic: str | None,
                   notes: list[str] | None = None) -> int:
    """Ensure ONE Word-made comment exists, for the XML pass to clone.

    The comment parts, styles and relationships have to come from Word
    itself; hand-rolling them is how a file ends up repaired on open.
    """
    notes = [] if notes is None else notes
    if classify is None:
        return 0
    try:
        if not doc.Revisions.Count:
            return 0
        _comment_revision(doc, doc.Revisions(1), classify, generic, notes)
        return 1
    except Exception as exc:
        notes.append(f"no comment scaffold could be seeded ({exc}) — the "
                     "XML pass has nothing to clone and will refuse")
        return 0


def _carry_rewrites(parts: dict[str, bytes], original: str | Path,
                    report: BuildReport, say: Any) -> None:
    """What Compare REWRITES rather than drops, so nothing else sees it.

    `compare_collateral` answers "what is missing", and neither of these
    is missing. `settings.xml` is present and rebuilt with Track Changes
    off; the comments part is present and carrying one note twice. Both
    reach the author, and both were per-paper scripts before they were
    here (HCW's `dedupe_comments.py` and the settings patch in its
    `redline.py`).
    """
    if _hygiene.keep_tracking(parts, read_parts(original)):
        report.carried_properties.append("w:trackRevisions")
        say("  carried across: Track Changes was ON and Compare wrote a "
            "fresh settings.xml with it off — an author editing a "
            "'tracked' manuscript whose typing is not being recorded is "
            "the quietest way to lose a round")
    report.deduped_comments = _hygiene.dedupe_comments(parts)
    for note in report.deduped_comments:
        say(f"  de-duplicated a comment present in BOTH inputs: {note}")


def _clear_staging(staging: Path, building: Path, published: bool,
                   say: Callable[[str], None]) -> None:
    """Tidy up after a build, keeping the artefact when one was REFUSED.

    A refused build is the one worth looking at, and this used to delete
    it. Word answering "the file appears to be corrupted" from `verify`
    left nothing to open, so the only way to see what it had been given
    was to rebuild with `verify_in_word=False` — which is how a
    comment-anchor defect cost a bisect rather than a look, twice in one
    day (2026-08-24).

    On success the file has already been renamed to `out`, so the unlink
    is a no-op and only the failure path ever loses anything. The kept
    file is a `~` temp name that the next build overwrites, so the cost
    of keeping it is one stale file at worst.
    """
    shutil.rmtree(staging, ignore_errors=True)
    if published:
        building.unlink(missing_ok=True)
    elif building.exists():
        say(f"  the refused build is kept at {building.name} — open it to "
            f"see what Word was given; the next build overwrites it")


def _carry_parts(parts: dict[str, bytes], revised_parts: dict[str, bytes],
                 original: str | Path, *, carry: tuple[str, ...],
                 report: BuildReport, say: Callable[[str], None]) -> None:
    """Put back what Compare dropped, from the clean copy or the baseline.

    Two sources on purpose. The clean copy is the usual one and is not
    always A source: when Word ate the part THERE too, restoring from it
    restores nothing and every gate agrees, because every gate compares
    the redline against that same clean copy. The baseline still has it,
    so it is asked second and reported apart — "this build went back a
    version for these" is a different sentence, and the one case where
    an author might want to look.

    Whether to fall back at all is a judgment, and it was made on
    measurement. Across 197 manuscripts in these projects `customXml/`
    holds Word's `<b:Sources>` bibliography store in 146 of them and
    `docProps/custom.xml` holds `ZOTERO_PREF` in 68 — the database
    behind every CITATION field, and what makes Zotero recognise a
    document as one it manages. Six carry an MSIP sensitivity label
    besides. Losing any of it stops the author's citation workflow with
    nothing red anywhere.

    Against that, "the author deleted it deliberately" is a thin story
    for these particular parts: Word barely exposes custom properties
    and does not expose the data store at all, so it is not something a
    prose edit does on purpose. The way to MEAN it stays explicit —
    `strip_parts`, and `[batch] carry` for a paper that wants something
    else.
    """
    report.carried = _hygiene.restore_parts(parts, revised_parts,
                                            prefixes=carry)
    for name in report.carried:
        # It said "it is not referenced from the body, so it goes back
        # with its content type and a free rId". True of the data
        # store, and false of the two parts where it matters: a header
        # or footer IS referenced from the body, from the section
        # properties, and that reference is the whole difficulty. The
        # sentence sent the one reader who would have looked at the
        # sectPr somewhere else.
        say(f"  carried across: {name} (Compare drops it; it goes back "
            f"with its content type, a free rId and — for a header or "
            f"footer — its section reference, reconciled against the "
            f"baseline's type map rather than appended beside whatever "
            f"Compare re-typed)")
    report.carried_from_baseline = _hygiene.restore_parts(
        parts, read_parts(original), prefixes=carry)
    for name in report.carried_from_baseline:
        say(f"  carried from the BASELINE: {name} (the clean copy no "
            f"longer has it either — `strip_parts` is how to mean "
            f"its removal)")


def build(original: str | Path, revised: str | Path, out: str | Path,
          classify: Classifier | None = None,
          *, author: str = "Revision", generic: str | None = _comments.GENERIC,
          tables: str = _comments.COALESCE,
          whitespace: bool = True, formatting: bool = True,
          moves: bool = True,
          resolve_math: bool = True, reject_check: bool = True,
          accept_check: bool = True, lint_check: bool = True,
          verify_in_word: bool = True, force: bool = False,
          carry: tuple[str, ...] = CARRIED_PARTS,
          progress: Callable[[str], None] | None = None,
          word_deadline: float | None = None,
          ) -> BuildReport:
    """Produce a tracked-changes docx at `out` from `original` -> `revised`.

    `classify` receives each revision and returns its comment text (or
    None to fall back to `generic`). Pass ``classify=None`` for a plain
    redline with no comments at all — not every paper annotates, and 1300
    "unclassified" balloons would be worse than silence. Pass
    ``generic=None`` to keep the matched comments but leave unmatched
    revisions bare.

    `tables` handles the case a modified table creates: Word makes every
    changed cell its own revision, so a regenerated table arrives as
    hundreds of them. The default coalesces those to one balloon per
    distinct comment per table. Pass ``tables=comments.ALL`` only to
    reproduce a deliverable built before that existed.

    `moves` is Word's move detection, and it is a heuristic that can
    produce a wrong deliverable rather than merely a differently-shaped
    one: on Aging_Well a scored move truncated the moved paragraph in
    the ACCEPTED view, taking a clause, a hyperlink and the sentence
    after it, and the same pair with ``moves=False`` reproduced the
    paragraph exactly. The accept-side gate below is what catches it —
    if this build refuses with a lost anchor or an unreproduced
    paragraph and the round moved a passage, try ``moves=False`` before
    anything else.

    `resolve_math` accepts the revisions inside an equation, because
    Word's save path may refuse to serialize them. Pass ``False`` where
    the paper has MEASURED that it does not have to: on LI7 the Flat OPC
    route carried 1870 revisions with the math tracked and reject-all
    reproduced the submitted paper exactly, while resolving the math cost
    315 revisions. Every accepted revision is one the author can no
    longer refuse, so the burden of proof is on resolving, not on
    keeping.

    `reject_check` is the gate that would have caught that: rejecting
    every revision in the built package must reproduce `original`, and
    the build refuses to publish when it does not (:func:`untracked`).
    Turn it off only to obtain the artifact for diagnosis — the paragraph
    listing in the error says what differs without it.

    `accept_check` is the same gate on the other side: ACCEPTING every
    revision must reproduce `revised`, the clean document the redline
    was derived from. The reject side cannot cover for it — rejecting
    removes every insertion, so a defect Compare baked INSIDE one is
    deleted before that comparison happens and cannot appear there
    however wrong it is — and the accepted document is the one the
    author reads. A build made with ``whitespace=False`` compares with
    runs of whitespace collapsed, because Word then treats respacing as
    no revision and accepting legitimately leaves the original's
    spacing. See :func:`unaccepted`.

    `lint_check` is the offline gate on the package itself — the
    "unreadable content" classes, caught here rather than in a dialog
    on a reader's screen. It is the strongest claim the build makes, so
    it is the last one to turn off; pass ``False`` only to obtain the
    artefact for diagnosis. It had no switch at all until 2026-09-18,
    which made a refusal here the one dead end in this function: the
    two gates below can be turned off, the findings this one reports
    are classes no docxkit verb repairs, and nothing is written, so the
    round produced nothing to look at either. Like them, it turns off
    the REFUSAL and not the check — `report.lint` carries the findings
    and the progress line says them.

    `verify_in_word` reopens the result and fails the build if Word had to
    repair it. `force` overrides the refusal to overwrite a deliverable
    that has been edited since it was built.

    `carry` names part-trees to copy back from `revised` when Compare
    drops them: the ``customXml/`` data store, which it drops on every
    single rebuild, and ``docProps/custom.xml``, whose user-defined
    properties carry a Bank manuscript's sensitivity label. Pass
    ``carry=()`` to get the raw Compare output and only a warning. See
    :func:`docxkit.hygiene.restore_parts` for why the default is not
    "warn and leave it to the reader".

    **Widening it to a header or a footer is a decision, not a default.**
    Those are reached from a ``w:headerReference`` in the section
    properties as well as through a relationship, and Compare rewrites
    the sectPr when it rebuilds the document. `restore_parts` puts that
    reference back — reading the type off the source's own sectPr — or
    refuses; what it cannot do is tell you whether the section the
    reference lands in is still the section the author meant. That case
    wants a person to look at the rendered page.
    """
    original, revised, out = Path(original), Path(revised), Path(out)
    report = BuildReport()
    say = progress or (lambda _: None)

    if (saved := _guard.check(out, force=force)) is not None:
        say(f"note: previous deliverable backed up to {saved.name}")

    # Build BESIDE the target and move it into place only once every gate
    # has passed. Writing the deliverable first and validating it second
    # means a failed lint or a Word repair leaves the previous good
    # redline already destroyed — and guard.check only takes a backup
    # when the file looks hand-edited, so the ordinary case has no copy
    # to fall back to. Staging in `out`'s own directory keeps the final
    # move atomic; a temp directory could be on another volume.
    staging = Path(tempfile.mkdtemp(prefix="docxkit_tracked_"))
    building = out.with_name(f"~{out.stem}.building{out.suffix}")
    published = False
    try:
        flat = staging / "flat.xml"

        with _word.session(**_bounded(
                word_deadline,
                f"comparing {Path(revised).name} against "
                f"{Path(original).name}")) as word, \
                _word.open_doc(word, original) as orig, \
                _word.open_doc(word, revised) as rev:
            cmp_ = _word.compare_documents(
                word, orig, rev, author=author,
                whitespace=whitespace, formatting=formatting, moves=moves)
            report.mark("compared")
            _word.draft_view(cmp_)

            if resolve_math:
                math = _resolve_math(cmp_, classify, generic,
                                     report.suppressed)
                report.math_resolved, report.math_kept = math
                report.mark("resolved math revisions")
                say(f"resolved {report.math_resolved} math revisions "
                    "(Word's save path may refuse to serialize them)")
                if report.math_kept:
                    say(f"  {report.math_kept} revision(s) merely OVERLAP "
                        f"an equation and stay tracked — accepting one "
                        f"applies its whole span")
            else:
                # The scaffold is not optional for an annotated build:
                # `comments.annotate` CLONES a Word-made comment, and
                # without one the build fails later with ScaffoldMissing,
                # a long way from the flag that caused it. It is NOT
                # counted as a resolved math revision — nothing was
                # resolved, and `revision.build` refuses a batch on that
                # number.
                _seed_scaffold(cmp_, classify, generic, report.suppressed)
                report.mark("math left tracked")
                say("math left tracked (resolve_math=False)")
            for note in report.suppressed:
                say(f"  WARNING: {note}")

            # Word's body count, of the document about to be EXTRACTED —
            # the one the package is counted from below. It was read
            # straight after the Compare, and every revision the math
            # pass accepted then counted in Word's figure and in no
            # element of the package: the note compared two documents,
            # its grouping remainder came out short by the math
            # accepted, and when that equalled the footnote and grouping
            # gap it said nothing at all. Re-read from Word rather than
            # decremented, because an accept applies its whole span and
            # can take other revisions with it (see
            # `_accept_math_via_equations`), and Word's grouping is what
            # the note exists to report.
            report.body_revisions = int(cmp_.Revisions.Count)

            # NOTE: keep orig/rev OPEN until after the extraction — the
            # compare result lazily references their parts, and closing
            # them first makes Content.WordOpenXML raise "A file error
            # has occurred".
            _word.extract_flat_opc(cmp_, flat)
            report.mark("extracted Flat OPC")
            with _suppress_com("close the compare result"):
                cmp_.Close(SaveChanges=0)

        n_parts = _word.flat_opc_to_docx(flat, building)
        report.mark(f"packed {n_parts} parts")

        parts = read_parts(building)
        # The count that matters, read off the PACKAGE: every kind, every
        # text-bearing part. Word's is the body only, so it is said aloud
        # separately when the two disagree rather than quietly replaced.
        report.revisions = package_counts(parts)["revisions"]
        say(f"revisions: {report.revisions}")
        if report.body_revisions != report.revisions:
            say(_revision_gap(parts, report.body_revisions,
                              report.revisions))

        # Before anything is added to it: what did Compare decline to
        # carry over? Checked against the REVISED input, which is the
        # document the redline is supposed to be able to reproduce.
        revised_parts = read_parts(revised)
        # The data store is not referenced from the body, so putting it
        # back is three mechanical edits and no judgment — which is
        # exactly the sort of thing that belongs here rather than in a
        # paper's script directory, hand-run after every single build.
        _carry_parts(parts, revised_parts, original, carry=carry,
                     report=report, say=say)
        # And the same argument one level down, on the FIELDS of
        # docProps/core.xml: Word rebuilds that part with its own four
        # save fields and nothing else, so a titled manuscript becomes an
        # untitled deliverable with the part still in place. Timestamps
        # are left to the redline; only what the document says about
        # itself is carried.
        report.carried_properties = _hygiene.carry_properties(parts,
                                                              revised_parts)
        if report.carried_properties:
            say(f"  carried across: {', '.join(report.carried_properties)} "
                f"(Compare regenerates core.xml with only its own save "
                f"fields; metadata is not tracked-changeable, so nothing "
                f"else would ever report this)")
        _carry_rewrites(parts, original, report, say)
        report.dropped = compare_collateral(revised_parts, parts)
        for note in report.dropped:
            say(f"  WARNING: Compare {note}")

        if classify is not None:
            added, unclassified = _comments.annotate(parts, classify,
                                                     generic=generic,
                                                     tables=tables)
            _comments.reclassify(parts, classify, generic=generic)
            report.comments_added, report.unclassified = added, unclassified
            report.mark(f"annotated {added} revisions in XML")
            say(f"comments: {added} added, unclassified: {unclassified}")

        # catch the "Word says unreadable content" classes offline,
        # before the file is written and long before anyone opens it
        report.lint = lint_parts(parts)
        if report.lint and lint_check:
            listed = "\n  - ".join(report.lint)
            raise PackageError(
                f"the package would not open cleanly in Word:\n  - {listed}\n"
                + _LINT_ESCAPE)
        for problem in report.lint:
            say(f"  LINT (kept, lint_check=False): {problem}")

        # The gate the whole deliverable exists for: everything in it
        # must be REFUSABLE. A redline that cannot be rejected back to
        # the original carries edits the author was never offered, and
        # every other signal here reads as success while it does — LI7
        # shipped one, and found it two rounds later with a hand-written
        # difflib script.
        base_parts = read_parts(original)
        report.unrejectable = untracked(parts, base_parts)
        # What a MOVE can duplicate, and what neither view can undo.
        # Word's Compare answers a moved block by writing the table
        # TWICE and marking neither copy: on DSI (2026-08-19) a redline
        # carried 28 tables against the baseline's 27 and BOTH accept and
        # reject left 28, so the author could not get rid of it and
        # nothing said it was there. A move whose rows Word DOES flag is
        # handled — `revisions._row_flag` reads `w:trPr` — and this is
        # the shape it cannot: an unmarked copy is not a revision, so it
        # is refused rather than resolved.
        accepted_view = _simulate(parts, _accept)
        report.structure_diff = (
            [f"rejected: {d}" for d in structure_diff(
                structure_counts(base_parts),
                structure_counts(_simulate(parts, _reject)))]
            + [f"accepted: {d}" for d in structure_diff(
                structure_counts(revised_parts),
                structure_counts(accepted_view))])
        # The carriers those counts do not hold: a hyperlink is not in
        # STRUCTURE_TAGS, because Word legitimately re-represents a
        # field-form link as an element and counting the tag would
        # refuse that. Anchors are compared by NAME instead, which is
        # blind to which form carries them.
        report.accepted_losses = accepted_losses(revised_parts,
                                                 accepted_view)
        # And the carrier neither of those reads: a definition whose
        # only reference the accept removed. `_simulate` has already
        # dropped the empty shells, so what is left here has words in
        # it — a footnote that will render nowhere. Measured against
        # the CLEAN copy rather than reported outright, because a
        # manuscript that already carries one is not this build's doing.
        report.orphan_notes = [
            o for o in _footnotes.orphans(accepted_view)
            if o not in set(_footnotes.orphans(revised_parts))]
        # And the same question of the OTHER view. `revised_parts` is
        # the clean document this redline claims to reproduce; what an
        # accept leaves has to be it, word for word.
        report.unaccepted = unaccepted(parts, revised_parts,
                                       fold_space=not whitespace)
        report.mark("checked reject-all against the original")
        for para in report.unrejectable:
            say(f"  UNREJECTABLE {para}")
        for missed in report.unaccepted:
            say(f"  UNACCEPTED {missed}")
        if report.structure_diff and reject_check:
            listed = "\n  ".join(report.structure_diff)
            raise PackageError(
                f"the redline does not carry the same STRUCTURE as the "
                f"documents it was built from:\n  {listed}\n"
                f"A move is the usual cause: Word's Compare answers a "
                f"moved block by writing the table twice and marking "
                f"neither copy, so neither accepting nor rejecting "
                f"removes the duplicate. Build with moves=False "
                f"(`revision build --no-moves`), which takes Word's move "
                f"detection out of it and shows the block as a deletion "
                f"and an insertion; move it in the CLEAN copy in a "
                f"separate round; or pass reject_check=False to build "
                f"the file anyway and inspect it.")
        if report.unrejectable and reject_check:
            listed = "\n  ".join(str(u) for u in report.unrejectable)
            raise PackageError(
                f"rejecting every revision does NOT reproduce "
                f"{original.name} — {len(report.unrejectable)} paragraph(s) "
                f"differ with no revision on them, so the author cannot "
                f"refuse those edits:\n  {listed}\n"
                f"An over-eager math accept is the usual cause: try "
                f"resolve_math=False. Pass reject_check=False to build the "
                f"file anyway and inspect it.")
        if accept_check:
            _refuse_accept_side(report, revised.name)
        # Word rewrites the OMML while deriving the redline and flattens
        # U+2212 to an ASCII hyphen doing it — measured on AFI: 2 minus
        # signs in the baseline, 0 in the built batch, and the 57 in the
        # PROSE of both untouched. Nothing else sees it: the text layer
        # reads the same words, `validate`'s glyph gate says only that
        # SOMETHING moved, and the equation still renders. Put back only
        # what a source really spells that way (see the docstring for
        # what is deliberately not inferred).
        report.restored_glyphs = _hygiene.restore_math_glyphs(
            parts, revised_parts, read_parts(original))
        for note in report.restored_glyphs:
            say(f"  restored math glyph — {note}")

        # AFTER the glyph restore, and after the write below would be too
        # late. Compare diffs INSIDE an inline equation, so accepting can
        # leave a number nobody wrote — see `accepted_math`. Refused with
        # the other accept-side gate, because a wrong number in the
        # deliverable is not something to report and continue past.
        report.accepted_math = accepted_math(
            revised_parts, _simulate(parts, _accept))
        if accept_check:
            _refuse_accept_side(report, revised.name, math_only=True)

        write_docx(building, parts)
        report.comments_total = package_counts(parts)["comments"]

        if verify_in_word:
            # the keyword only when a ceiling is asked for — `_bounded`'s
            # rule, so a fake `verify` that knows no keyword is untouched
            checked = verify(building, **({"word_deadline": word_deadline}
                                          if word_deadline else {}))
            report.verified_comments = checked["word"]["comments"]
            report.verified_revisions = checked["word"]["revisions"]
            if not checked["comments_match"]:
                raise PackageError(
                    f"Word read back {report.verified_comments} comments, "
                    f"the package holds {report.comments_total} — it was "
                    "repaired on open")
            report.mark("verified in Word")
            say(f"verified in Word: {report.verified_comments} comments, "
                f"{report.verified_revisions} revisions in the body")

        building.replace(out)          # every gate passed: publish
        published = True
        # `base_sha256` is the batch's link to the BASELINE it was built
        # on. The names alone cannot answer "is this batch about the
        # current truth" — `prev.docx` is a path whose content changes
        # on every `baseline` — and without it a refused build left the
        # PREVIOUS redline in place for `validate` and `promote` to take
        # as this one (Aging_Well R5). See `guard.base_of`.
        _guard.stamp(out, original=original.name, revised=revised.name,
                     base_sha256=_guard.sha256(original))
        return report
    finally:
        _clear_staging(staging, building, published, say)
