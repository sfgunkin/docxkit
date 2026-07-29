r"""Building a tracked-changes deliverable from two clean documents.

The journal wants a redline: the original, the revision, and a comment on
every change saying why. The reliable way to produce one is Word's own
``CompareDocuments`` — hand-authored ``w:ins``/``w:del`` markup has failed
to open in Word repeatedly across these papers, so it is not attempted here.

The pipeline:

1. Word compares the two documents (seconds).
2. Word comments and accepts the MATH revisions. It cannot serialize a
   compare result containing tracked math at all, so those must go — and
   they must be commented first, while they still exist. This also leaves
   behind Word's own comment scaffold for step 4.
3. The package is extracted as Flat OPC, bypassing Word's save path.
4. Every remaining revision is commented in XML (``docxkit.comments``).
5. The result is reopened in Word and checked: it must read back exactly
   the comment count the package contains, or the file was repaired on
   open and the build fails.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import comments as _comments
from . import word as _word
from .comments import RevisionContext
from .errors import DeliverableModified, PackageError
from .lint import lint_parts
from .package import backup as _backup
from .package import read_parts, write_docx

__all__ = ["BuildReport", "build", "guard_deliverable", "verify"]


def verify(path: str | Path) -> dict[str, Any]:
    """Open a document in Word and report what Word actually reads back.

    The check that matters for any tracked-changes file, however it was
    produced: Word silently "repairs" markup it dislikes, and the damage
    only shows up when the editor opens the deliverable. Hand-authored
    ``w:ins``/``w:del`` has failed this way repeatedly across these
    papers, so a file built that way should be run through here before it
    is sent anywhere.

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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stamp_path(out: Path) -> Path:
    return out.with_name(out.name + ".buildinfo.json")


def guard_deliverable(out: Path, *, force: bool = False,
                      backup_tag: str = "user_edited") -> Path | None:
    """Refuse to overwrite a deliverable someone has edited since the build.

    The tracked file is derived, but it is also what the author opens in
    Word to review — accepting revisions, leaving some pending, fixing a
    word. Rebuilding over that destroys the review with no trace, which is
    exactly what happened on the AFI paper on 2026-07-29.

    A stamp written next to the file records the hash of what the build
    produced. If the file no longer matches, it was edited: back it up and
    stop. Returns the backup path when one was taken.
    """
    if not out.exists():
        return None
    stamp = _stamp_path(out)
    if stamp.exists():
        try:
            recorded = json.loads(stamp.read_text(encoding="utf-8"))["sha256"]
        except (ValueError, KeyError):
            recorded = None
        if recorded == _sha256(out):
            return None                      # untouched since we built it
    # Either edited, or built before stamping existed: keep a copy either way.
    saved = _backup(out, backup_tag)
    if force:
        return saved
    raise DeliverableModified(
        f"{out.name} has changed since docxkit built it — someone edited it "
        f"in Word. Backed up to {saved.name}; rebuilding would discard those "
        "edits. Fold them into the build source first, then re-run with "
        "force=True (CLI: --force).")


def _write_stamp(out: Path, original: Path, revised: Path) -> None:
    _stamp_path(out).write_text(json.dumps({
        "sha256": _sha256(out),
        "original": original.name,
        "revised": revised.name,
    }, indent=1), encoding="utf-8")


class BuildReport:
    """What a redline build did, and how long each phase took."""

    def __init__(self) -> None:
        self.revisions = 0
        self.math_seeded = 0
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


def _seed_math_comments(
        doc: Any,
        classify: Callable[[RevisionContext], str | None],
        generic: str) -> int:
    """Comment then accept every revision containing math.

    Word cannot serialize tracked math, so these have to be accepted before
    extraction — which erases them from the XML. Commenting them here is
    the only chance to explain an equation change, and it creates the
    comment scaffold the XML pass clones.
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
            seeded += 1
        with contextlib.suppress(Exception):
            rev.Accept()

    if not seeded and doc.Revisions.Count:
        # no math this time - still need one Word-made comment as scaffold
        rng = doc.Revisions(1).Range
        with contextlib.suppress(Exception):
            ctx = RevisionContext(text=rng.Text or "", para="", window="",
                                  table_index=None, start=-1, end=-1)
            doc.Comments.Add(rng, classify(ctx) or generic)
            seeded += 1
    return seeded


def _accept_math(doc: Any) -> int:
    """Accept every revision that touches math, commenting none.

    Word cannot serialize a compare result that still contains tracked
    math, so this has to happen whether or not the paper annotates.

    Driven from ``doc.OMaths`` rather than from the revisions: asking
    every revision whether it contains math costs ~20ms each, which is 27s
    on a 1359-revision compare, while walking the equations is ~15ms each
    and there are far fewer of them. Same shape as the Revisions(i)
    lesson — pick the collection that is small.
    """
    accepted = 0
    with contextlib.suppress(Exception):
        if not doc.OMaths.Count:
            return 0
    for i in range(doc.OMaths.Count, 0, -1):   # backwards: accepting shifts
        try:
            revisions = doc.OMaths(i).Range.Revisions
            for j in range(revisions.Count, 0, -1):
                revisions(j).Accept()
                accepted += 1
        except Exception:
            pass
    return accepted


def build(original: str | Path, revised: str | Path, out: str | Path,
          classify: Callable[[RevisionContext], str | None] | None = None,
          *, author: str = "Revision", generic: str = _comments.GENERIC,
          verify: bool = True, force: bool = False,
          progress: Callable[[str], None] | None = None,
          ) -> BuildReport:
    """Produce a tracked-changes docx at `out` from `original` -> `revised`.

    `classify` receives each revision and returns its comment text (or
    None to fall back to `generic`). Pass ``classify=None`` for a plain
    redline with no comments at all — not every paper annotates its
    revisions, and 1300 "unclassified" balloons would be worse than
    silence. `verify` reopens the result in Word and fails the build if
    Word had to repair it. `force` overrides the refusal to overwrite a
    deliverable that has been edited since it was built.
    """
    original, revised, out = Path(original), Path(revised), Path(out)
    report = BuildReport()
    say = progress or (lambda _: None)

    if (saved := guard_deliverable(out, force=force)) is not None:
        say(f"note: previous deliverable backed up to {saved.name}")

    td = Path(tempfile.mkdtemp(prefix="docxkit_tracked_"))
    flat = td / "tracked_flat.xml"

    with _word.session() as word, \
            _word.open_doc(word, original) as orig, \
            _word.open_doc(word, revised) as rev:
        cmp_ = _word.compare_documents(word, orig, rev, author=author)
        report.revisions = cmp_.Revisions.Count
        report.mark("compared")
        say(f"revisions: {report.revisions}")
        _word.draft_view(cmp_)

        if classify is not None:
            report.math_seeded = _seed_math_comments(cmp_, classify, generic)
            report.mark("seeded math comments")
            say(f"seeded {report.math_seeded} math-revision comments")
        else:
            # Word still cannot serialize tracked math, so those revisions
            # have to be accepted even when nothing is being commented.
            report.math_seeded = _accept_math(cmp_)
            report.mark("accepted math revisions")
            say(f"accepted {report.math_seeded} math revisions "
                "(Word cannot serialize tracked math)")

        # NOTE: keep orig/rev OPEN until after extraction - the compare
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
    else:
        added = unclassified = 0
    # catch the "Word says unreadable content" classes offline, before the
    # file is written and long before anyone opens it
    if problems := lint_parts(parts):
        listed = "\n  - ".join(problems)
        raise PackageError(
            f"the annotated package would not open cleanly in Word:\n"
            f"  - {listed}")
    write_docx(out, parts)
    report.comments_added = added
    report.unclassified = unclassified
    report.comments_total = parts.get("word/comments.xml", b"").decode(
        "utf-8").count("<w:comment w:id=")
    report.mark(f"annotated {added} revisions in XML")
    say(f"comments: {added} added, unclassified: {unclassified}")

    if verify:
        got, revs = _verify(out)
        report.verified_comments, report.verified_revisions = got, revs
        if got != report.comments_total:
            raise AssertionError(
                f"Word read back {got} comments, package has "
                f"{report.comments_total} - the file was repaired on open")
        report.mark("verified in Word")
        say(f"verified in Word: {got} comments, {revs} revisions")

    _write_stamp(out, original, revised)
    return report


def _verify(path: Path) -> tuple[int, int]:
    """Reopen in Word and report what it actually reads back."""
    with _word.session() as word, _word.open_doc(word, path) as doc:
        return int(doc.Comments.Count), int(doc.Revisions.Count)
