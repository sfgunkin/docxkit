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
2. The MATH revisions are resolved — Word cannot serialize a compare
   result that contains tracked math at all, so they must be accepted,
   and commented first if the paper annotates. This also leaves behind
   Word's own comment scaffold for step 4.
3. The package is extracted as Flat OPC, bypassing Word's save path.
4. Every remaining revision is commented in XML (:mod:`docxkit.comments`).
5. The result is linted, then reopened in Word: it must read back exactly
   the comment count the package holds, or Word repaired it on open.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import comments as _comments
from . import guard as _guard
from . import word as _word
from ._xml import COMMENT_ID_RE, internal_links
from .comments import RevisionContext
from .errors import PackageError
from .lint import lint_parts
from .package import read_parts, write_docx

# Bound directly, NOT reached through `_word`: tests replace that
# module attribute with a COM fake, and a fake has no reason to
# carry a suppression helper. The seam is for Word, not for this.
from .word import _suppress_com

__all__ = ["BuildReport", "build", "compare_collateral", "package_counts",
           "verify"]

_BOOKMARK_RE = re.compile(r'<w:bookmarkStart[^>]*w:name="([^"]+)"')


def _anchors(parts: dict[str, bytes]) -> tuple[set[str], set[str]]:
    """Every bookmark NAME and every internal link TARGET in a package."""
    names: set[str] = set()
    targets: set[str] = set()
    for name, blob in parts.items():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        xml = blob.decode("utf-8", "replace")
        names |= set(_BOOKMARK_RE.findall(xml))
        targets |= {a for a, _ in internal_links(xml)}
    return names, targets


def compare_collateral(revised: dict[str, bytes],
                       redline: dict[str, bytes]) -> list[str]:
    """What Word's Compare removed on the way from `revised` to `redline`.

    Compare rebuilds the document rather than annotating it, and what it
    declines to carry over it drops in silence. Three kinds turned up on
    ONE manuscript in one day, none of them visible in any text diff:

    * a bookmark — LI7's ``OECD2021txt``, whose start had no matching
      end, so Word discarded it and the entry's back-link pointed at
      nothing;
    * a hyperlink — the link to ``Hadiyana2021`` simply absent, 162
      links in and 161 out;
    * whole PARTS — ``word/header1.xml`` and three customXml items.

    Every one was found afterwards, by hand, because the build reported
    revisions and comments and nothing else. This is advisory and does
    NOT fail a build: Word legitimately drops an empty header and the
    customXml a template left behind, and a redline nobody can produce
    is worse than one with a note on it. But it must be SAID, because
    the alternative is finding it in the deliverable.
    """
    notes = [f"part dropped: {p}" for p in sorted(set(revised) - set(redline))]
    was_names, was_targets = _anchors(revised)
    now_names, now_targets = _anchors(redline)
    notes += [f"bookmark dropped: {b}"
              for b in sorted(was_names - now_names)]
    notes += [f"link dropped: -> {t}"
              for t in sorted(was_targets - now_targets)]
    return notes

Classifier = Callable[[RevisionContext], str | None]


def package_counts(parts: dict[str, bytes]) -> dict[str, int]:
    """What the PACKAGE holds: insertions, deletions, comments.

    Half of the "did Word repair this file?" check, and the half that
    actually detects the damage — Word's side is just a number it hands
    back. Pure, so it can be tested without Word, which is why it lives
    here instead of inline in :func:`verify` and :func:`build`, where it
    had been written twice.
    """
    doc_xml = parts["word/document.xml"].decode("utf-8")
    com_xml = parts.get("word/comments.xml", b"").decode("utf-8")
    return {
        "insertions": doc_xml.count("<w:ins "),
        "deletions": doc_xml.count("<w:del "),
        # not count("<w:comment w:id=") — attribute order is not
        # meaningful in XML, and the id-second form counted as zero
        "comments": len(COMMENT_ID_RE.findall(com_xml)),
    }


def verify(path: str | Path) -> dict[str, Any]:
    """Open a document in Word and report what Word actually reads back.

    The check that matters for any tracked-changes file, however it was
    produced: Word silently "repairs" markup it dislikes, and the damage
    only shows up when the editor opens the deliverable.

    Returns the counts Word reports alongside the counts the package
    contains; when they disagree, Word altered the file on open.
    """
    path = Path(path)
    parts = read_parts(path)
    in_package = package_counts(parts)
    with _word.session() as word, _word.open_doc(word, path) as opened:
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


class BuildReport:
    """What a redline build did, and how long each phase took."""

    def __init__(self) -> None:
        self.revisions = 0
        self.math_resolved = 0
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
        if self.dropped:
            lines.append(f"  Word's Compare dropped {len(self.dropped)} "
                         "thing(s) the revised copy had:")
            lines += [f"    - {note}" for note in self.dropped[:10]]
            if len(self.dropped) > 10:
                lines.append(f"    ... and {len(self.dropped) - 10} more")
        return "\n".join(lines)


def _resolve_math(doc: Any, classify: Classifier | None,
                  generic: str | None,
                  notes: list[str] | None = None) -> int:
    """Comment (if the paper annotates) and accept every math revision.

    Word cannot serialize a compare result containing tracked math, so
    these have to go regardless. Commenting them is the only chance to
    explain an equation change, and it leaves the comment scaffold the
    XML pass clones.

    The two routes below look like duplicates and are NOT: they select
    different revisions. Walking the equations finds revisions that
    INTERSECT a math range; asking each revision whether it contains math
    finds revisions that CONTAIN one. Substituting the first for the
    second on the AFI paper left 41 extra revisions un-accepted (291
    annotated became 332), so each path keeps the scan it was verified
    with. The equation walk is much cheaper — ~15ms per equation against
    ~20ms per revision, which was 27s of a 1359-revision compare — and is
    used where no comments are needed and it was validated.
    """
    notes = [] if notes is None else notes
    if classify is None:
        return _accept_math_via_equations(doc, notes)
    return _comment_and_accept_math_revisions(doc, classify, generic, notes)


def _accept_math_via_equations(doc: Any,
                               notes: list[str] | None = None) -> int:
    """Accept revisions touching math, found by walking ``doc.OMaths``."""
    notes = [] if notes is None else notes
    try:
        if not doc.OMaths.Count:
            return 0
    except Exception as exc:
        notes.append(f"could not read doc.OMaths: {exc}")
        return 0
    accepted = 0
    for i in range(doc.OMaths.Count, 0, -1):   # backwards: accepting shifts
        try:
            revisions = doc.OMaths(i).Range.Revisions
        except Exception as exc:
            notes.append(f"equation {i}: unreachable ({exc})")
            continue
        for j in range(revisions.Count, 0, -1):
            try:
                revisions(j).Accept()
                accepted += 1
            except Exception as exc:
                notes.append(f"equation {i} revision {j}: "
                             f"not accepted ({exc})")
    return accepted


def _comment_and_accept_math_revisions(
        doc: Any, classify: Classifier, generic: str | None,
        notes: list[str] | None = None) -> int:
    """Comment then accept each revision that CONTAINS math.

    Scans the revisions rather than the equations — see
    :func:`_resolve_math` for why the cheaper walk is not a substitute.
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
    return seeded or _seed_scaffold(doc, classify, generic, notes)


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


def build(original: str | Path, revised: str | Path, out: str | Path,
          classify: Classifier | None = None,
          *, author: str = "Revision", generic: str | None = _comments.GENERIC,
          tables: str = _comments.COALESCE,
          whitespace: bool = True, formatting: bool = True,
          verify_in_word: bool = True, force: bool = False,
          progress: Callable[[str], None] | None = None,
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

    `verify_in_word` reopens the result and fails the build if Word had to
    repair it. `force` overrides the refusal to overwrite a deliverable
    that has been edited since it was built.
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
    try:
        flat = staging / "flat.xml"

        with _word.session() as word, \
                _word.open_doc(word, original) as orig, \
                _word.open_doc(word, revised) as rev:
            cmp_ = _word.compare_documents(
                word, orig, rev, author=author,
                whitespace=whitespace, formatting=formatting)
            report.revisions = cmp_.Revisions.Count
            report.mark("compared")
            say(f"revisions: {report.revisions}")
            _word.draft_view(cmp_)

            report.math_resolved = _resolve_math(
                cmp_, classify, generic, report.suppressed)
            report.mark("resolved math revisions")
            say(f"resolved {report.math_resolved} math revisions "
                "(Word cannot serialize tracked math)")
            for note in report.suppressed:
                say(f"  WARNING: {note}")

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
        # Before anything is added to it: what did Compare decline to
        # carry over? Checked against the REVISED input, which is the
        # document the redline is supposed to be able to reproduce.
        report.dropped = compare_collateral(read_parts(revised), parts)
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
        if problems := lint_parts(parts):
            listed = "\n  - ".join(problems)
            raise PackageError(
                f"the package would not open cleanly in Word:\n  - {listed}")
        write_docx(building, parts)
        report.comments_total = package_counts(parts)["comments"]

        if verify_in_word:
            checked = verify(building)
            report.verified_comments = checked["word"]["comments"]
            report.verified_revisions = checked["word"]["revisions"]
            if not checked["comments_match"]:
                raise PackageError(
                    f"Word read back {report.verified_comments} comments, "
                    f"the package holds {report.comments_total} — it was "
                    "repaired on open")
            report.mark("verified in Word")
            say(f"verified in Word: {report.verified_comments} comments, "
                f"{report.verified_revisions} revisions")

        building.replace(out)          # every gate passed: publish
        _guard.stamp(out, original=original.name, revised=revised.name)
        return report
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        building.unlink(missing_ok=True)   # gone already on success
