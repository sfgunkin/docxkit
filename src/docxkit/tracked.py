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

import contextlib
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import comments as _comments
from . import guard as _guard
from . import word as _word
from .comments import RevisionContext
from .errors import PackageError
from .lint import lint_parts
from .package import read_parts, write_docx

__all__ = ["BuildReport", "build", "verify"]

Classifier = Callable[[RevisionContext], str | None]


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
    doc_xml = parts["word/document.xml"].decode("utf-8")
    com_xml = parts.get("word/comments.xml", b"").decode("utf-8")
    in_package = {
        "insertions": doc_xml.count("<w:ins "),
        "deletions": doc_xml.count("<w:del "),
        "comments": com_xml.count("<w:comment w:id="),
    }
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
        return "\n".join(lines)


def _resolve_math(doc: Any, classify: Classifier | None, generic: str) -> int:
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
    if classify is None:
        return _accept_math_via_equations(doc)
    return _comment_and_accept_math_revisions(doc, classify, generic)


def _accept_math_via_equations(doc: Any) -> int:
    """Accept revisions touching math, found by walking ``doc.OMaths``."""
    with contextlib.suppress(Exception):
        if not doc.OMaths.Count:
            return 0
    accepted = 0
    for i in range(doc.OMaths.Count, 0, -1):   # backwards: accepting shifts
        try:
            revisions = doc.OMaths(i).Range.Revisions
        except Exception:
            continue
        for j in range(revisions.Count, 0, -1):
            with contextlib.suppress(Exception):
                revisions(j).Accept()
                accepted += 1
    return accepted


def _comment_and_accept_math_revisions(
        doc: Any, classify: Classifier, generic: str) -> int:
    """Comment then accept each revision that CONTAINS math.

    Scans the revisions rather than the equations — see
    :func:`_resolve_math` for why the cheaper walk is not a substitute.
    """
    math_revs = []
    for rev in _word.revisions(doc):      # enumerator: indexing is O(i)
        try:
            if rev.Range.OMaths.Count:
                math_revs.append(rev)
        except Exception:
            pass

    seeded = 0
    for rev in reversed(math_revs):       # last first: accepting shifts rest
        _comment_revision(doc, rev, classify, generic)
        seeded += 1
        with contextlib.suppress(Exception):
            rev.Accept()
    return seeded or _seed_scaffold(doc, classify, generic)


def _comment_revision(doc: Any, rev: Any, classify: Classifier,
                      generic: str) -> None:
    """Attach the paper's comment to one revision, through Word."""
    rng = rev.Range
    text = para = ""
    with contextlib.suppress(Exception):
        text = rng.Text or ""
    with contextlib.suppress(Exception):
        para = rng.Paragraphs(1).Range.Text or ""
    comment = classify(RevisionContext(
        text=text, para=para, window=para, table_index=None,
        start=-1, end=-1))
    with contextlib.suppress(Exception):
        doc.Comments.Add(rng, comment or generic)


def _seed_scaffold(doc: Any, classify: Classifier | None,
                   generic: str) -> int:
    """Ensure ONE Word-made comment exists, for the XML pass to clone.

    The comment parts, styles and relationships have to come from Word
    itself; hand-rolling them is how a file ends up repaired on open.
    """
    if classify is None:
        return 0
    with contextlib.suppress(Exception):
        if not doc.Revisions.Count:
            return 0
        _comment_revision(doc, doc.Revisions(1), classify, generic)
        return 1
    return 0


def build(original: str | Path, revised: str | Path, out: str | Path,
          classify: Classifier | None = None,
          *, author: str = "Revision", generic: str = _comments.GENERIC,
          whitespace: bool = True, formatting: bool = True,
          verify_in_word: bool = True, force: bool = False,
          progress: Callable[[str], None] | None = None,
          ) -> BuildReport:
    """Produce a tracked-changes docx at `out` from `original` -> `revised`.

    `classify` receives each revision and returns its comment text (or
    None to fall back to `generic`). Pass ``classify=None`` for a plain
    redline with no comments at all — not every paper annotates, and 1300
    "unclassified" balloons would be worse than silence.

    `verify_in_word` reopens the result and fails the build if Word had to
    repair it. `force` overrides the refusal to overwrite a deliverable
    that has been edited since it was built.
    """
    original, revised, out = Path(original), Path(revised), Path(out)
    report = BuildReport()
    say = progress or (lambda _: None)

    if (saved := _guard.check(out, force=force)) is not None:
        say(f"note: previous deliverable backed up to {saved.name}")

    flat = Path(tempfile.mkdtemp(prefix="docxkit_tracked_")) / "flat.xml"

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

        report.math_resolved = _resolve_math(cmp_, classify, generic)
        report.mark("resolved math revisions")
        say(f"resolved {report.math_resolved} math revisions "
            "(Word cannot serialize tracked math)")

        # NOTE: keep orig/rev OPEN until after the extraction — the compare
        # result lazily references their parts, and closing them first
        # makes Content.WordOpenXML raise "A file error has occurred".
        _word.extract_flat_opc(cmp_, flat)
        report.mark("extracted Flat OPC")
        with contextlib.suppress(Exception):
            cmp_.Close(SaveChanges=0)

    n_parts = _word.flat_opc_to_docx(flat, out)
    report.mark(f"packed {n_parts} parts")

    parts = read_parts(out)
    if classify is not None:
        added, unclassified = _comments.annotate(parts, classify,
                                                 generic=generic)
        _comments.reclassify(parts, classify, generic=generic)
        report.comments_added, report.unclassified = added, unclassified
        report.mark(f"annotated {added} revisions in XML")
        say(f"comments: {added} added, unclassified: {unclassified}")

    # catch the "Word says unreadable content" classes offline, before the
    # file is written and long before anyone opens it
    if problems := lint_parts(parts):
        listed = "\n  - ".join(problems)
        raise PackageError(
            f"the package would not open cleanly in Word:\n  - {listed}")
    write_docx(out, parts)
    report.comments_total = parts.get("word/comments.xml", b"").decode(
        "utf-8").count("<w:comment w:id=")

    if verify_in_word:
        checked = verify(out)
        report.verified_comments = checked["word"]["comments"]
        report.verified_revisions = checked["word"]["revisions"]
        if not checked["comments_match"]:
            raise PackageError(
                f"Word read back {report.verified_comments} comments, the "
                f"package holds {report.comments_total} — it was repaired "
                "on open")
        report.mark("verified in Word")
        say(f"verified in Word: {report.verified_comments} comments, "
            f"{report.verified_revisions} revisions")

    _guard.stamp(out, original=original.name, revised=revised.name)
    return report
