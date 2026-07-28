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
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from . import comments as _comments
from . import word as _word
from .comments import RevisionContext
from .package import read_parts, write_docx

__all__ = ["BuildReport", "build"]


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


def _seed_math_comments(doc, classify, generic: str) -> int:
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


def build(original: str | Path, revised: str | Path, out: str | Path,
          classify: Callable[[RevisionContext], str | None],
          *, author: str = "Revision", generic: str = _comments.GENERIC,
          verify: bool = True, progress: Callable[[str], None] | None = None,
          ) -> BuildReport:
    """Produce a tracked-changes docx at `out` from `original` -> `revised`.

    `classify` receives each revision and returns its comment text (or None
    to fall back to `generic`). `verify` reopens the result in Word and
    fails the build if Word had to repair it.
    """
    original, revised, out = Path(original), Path(revised), Path(out)
    report = BuildReport()
    say = progress or (lambda _: None)

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

        report.math_seeded = _seed_math_comments(cmp_, classify, generic)
        report.mark("seeded math comments")
        say(f"seeded {report.math_seeded} math-revision comments")

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
    added, unclassified = _comments.annotate(parts, classify, generic=generic)
    _comments.reclassify(parts, classify, generic=generic)
    write_docx(out, parts)
    report.comments_added = added
    report.unclassified = unclassified
    report.comments_total = parts["word/comments.xml"].decode(
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
    return report


def _verify(path: Path) -> tuple[int, int]:
    """Reopen in Word and report what it actually reads back."""
    with _word.session() as word, _word.open_doc(word, path) as doc:
        return int(doc.Comments.Count), int(doc.Revisions.Count)
