r"""Driving Word through COM, with the traps already paid for.

Word is needed for exactly three things no XML pass can do: diff two
documents into a tracked-changes redline, lay pages out (how many pages,
and which page a given sentence lands on), and render to PDF. Everything
else is faster and safer in XML.

Three hard-won rules are baked in here:

* **Never index ``Document.Revisions(i)`` in a loop.** That collection is
  O(i) to index inside Word. Measured on a 316-revision compare: 280.3s to
  scan by index versus 5.9s through the enumerator, for an identical result
  set — and the indexed loop eventually provoked "Call was rejected by
  callee" as Word fell behind. :func:`revisions` uses the enumerator.
* **Work on local copies.** COM and OneDrive-backed paths interact badly;
  every entry point here stages files through TEMP.
* **Saving may hang.** Word's file-save path on this machine can spin
  indefinitely (any drive, any document), and it flatly refuses to
  serialize a compare result containing tracked math ("A file error has
  occurred"). :func:`extract_flat_opc` + :func:`flat_opc_to_docx` bypass
  Word's save machinery entirely.
"""
from __future__ import annotations

import base64
import contextlib
import logging
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, NamedTuple, cast

from lxml import etree

from .errors import AnchorError, FontMissing, PackageError

__all__ = [
    "Location",
    "RevisionLocation",
    "compare_documents",
    "draft_view",
    "export_pdf",
    "extract_flat_opc",
    "flat_opc_to_docx",
    "locate",
    "locate_in",
    "locate_revisions",
    "open_doc",
    "page_count",
    "paginate",
    "revision_locations",
    "revisions",
    "ruler",
    "search_text",
    "session",
]

PKG = "{http://schemas.microsoft.com/office/2006/xmlPackage}"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

# A library gets a logger and nothing else: no handler, no level, no
# basicConfig. Configuring logging at import time is the caller's
# decision, and taking it here would hijack the logging of every paper
# script that imports docxkit.
_log = logging.getLogger(__name__)


@contextlib.contextmanager
def _suppress_com(what: str) -> Iterator[None]:
    """Swallow a COM failure the way the bare suppress did, but say so.

    Every use of this is a call whose failure genuinely does not matter
    to the caller: restoring a Word option, switching a view, closing a
    document Word has already lost. Letting one of those abort a
    1,400-revision build would be the worse outcome, so the control flow
    is unchanged — this only ends the SILENCE. A machine where Word quits
    badly, or refuses to set an option, used to look identical to one
    where everything worked.

    DEBUG, because on a healthy run these fire routinely (Word raises on
    ScreenUpdating in some versions) and a warning nobody can act on is
    noise. `python -m logging` config or `logging.basicConfig(
    level=logging.DEBUG)` in a script turns them on.
    """
    try:
        yield
    except Exception as exc:
        _log.debug("COM call failed and was skipped — %s: %s: %s",
                   what, type(exc).__name__, exc)

WD_NORMAL_VIEW = 1
WD_PRINT_VIEW = 3
WD_WITHIN_TABLE = 12
WD_COMPARE_TO_NEW = 2
WD_FORMAT_DOCX = 16
WD_EXPORT_PDF = 17
#: WdExportRange. `ExportAsFixedFormat`'s 5th positional decides whether
#: From/To are read at all; 0 (wdExportAllDocument) makes Word ignore
#: them, which silently turned every page range into a full render.
WD_EXPORT_ALL_DOCUMENT = 0
WD_EXPORT_FROM_TO = 3
WD_STATISTIC_PAGES = 2
WD_COLLAPSE_START = 1
WD_FIND_STOP = 0
# Range.Information() keys.
WD_INFO_ADJUSTED_PAGE = 1     # the number PRINTED on the page
WD_INFO_PAGE = 3              # the page's position in the file
WD_INFO_LINE = 10             # line number, counted from the top of the page
WD_HORIZ_POS_PAGE = 5         # x of the range, in points from the page edge

# Word's Find box takes at most 255 characters.
FIND_LIMIT = 255

# A paragraph is the unit both `search_text` and `ruler` work in.
_LINE_BREAK = re.compile(r"[\r\n\v]")

# Word options switched off for bulk edits; restored on exit so an
# interactive Word is not left reconfigured.
_FAST_OPTIONS = {
    "Pagination": False,
    "CheckSpellingAsYouType": False,
    "CheckGrammarAsYouType": False,
    "BackgroundSave": False,
}


@contextlib.contextmanager
def session(*, fast: bool = True) -> Iterator[Any]:
    """A private, invisible Word instance, always quit on the way out.

    Uses DispatchEx so an interactive Word the user has open is neither
    reused nor closed.
    """
    # The `word` extra, Windows-only, so it is absent wherever CI runs.
    # No pyright directive needed and none wanted: pyright BUNDLES stubs
    # for pywin32, so the import resolves against those and it reports
    # reportMissingModuleSource — a warning, which does not fail the run.
    # An ignore here suppressed nothing and said otherwise.
    import pythoncom
    import win32com.client as com

    with _suppress_com("CoInitialize"):
        pythoncom.CoInitialize()
    word = com.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    saved = {}
    if fast:
        for name, value in _FAST_OPTIONS.items():
            with _suppress_com(f"set Word option {name}"):
                saved[name] = getattr(word.Options, name)
                setattr(word.Options, name, value)
        with _suppress_com("disable ScreenUpdating"):
            word.ScreenUpdating = False
    try:
        yield word
    finally:
        for name, value in saved.items():
            with _suppress_com(f"restore Word option {name}"):
                setattr(word.Options, name, value)
        with _suppress_com("Word.Quit"):
            word.Quit()


@contextlib.contextmanager
def open_doc(word: Any, path: str | Path, *,
             read_only: bool = True,
             local: bool | None = None) -> Iterator[Any]:
    """Open `path`, yielding the Document; closed without saving.

    `local` stages the file through TEMP first because COM against a
    OneDrive path is a documented source of flaky failures. It defaults
    to `read_only`: staging is right for reading and WRONG for writing,
    because a ``Save()`` then lands on the staged copy and the file the
    caller named is never touched — no error, no warning, and the
    document reports the same counts either way.

    That silence cost a reviewer a false conclusion: an accept/reject
    comparison "proved" a divergence from Word that turned out to be
    entirely this default. A write that does not happen must not look
    like one that did, so passing ``local=True`` with
    ``read_only=False`` is refused rather than quietly staged.

    Closing never saves. A caller that wants to write calls ``Save()``
    itself; ``SaveChanges=0`` only discards what was left unsaved.
    """
    path = Path(path)
    if local is None:
        local = read_only
    elif local and not read_only:
        raise ValueError(
            "open_doc(read_only=False, local=True): a staged copy is "
            "discarded on close, so Save() would not reach "
            f"{path.name} - pass local=False to write it")
    td = Path(tempfile.mkdtemp(prefix="docxkit_word_")) if local else None
    try:
        target = td / path.name if td else path
        if td:
            shutil.copy2(path, target)
        # Documents.Open inside the try: it raises on a locked or corrupt
        # file, and the staged copy has to be cleaned up on that path too
        doc = word.Documents.Open(str(target), ReadOnly=read_only,
                                  AddToRecentFiles=False)
        try:
            yield doc
        finally:
            with _suppress_com(f"close {Path(path).name}"):
                doc.Close(SaveChanges=0)
    finally:
        if td:
            shutil.rmtree(td, ignore_errors=True)


def revisions(doc: Any) -> Iterator[Any]:
    """Iterate revisions through the enumerator, never by index.

    Indexing ``Revisions(i)`` is O(i); a full indexed scan of a
    316-revision document costs ~280s against ~6s here.

    READ ONLY. Do not Accept() or Reject() what this yields to apply a
    subset — use :func:`docxkit.revisions.accept` with a ``where``
    predicate (``accept(xml, where=by_author("A"))``) instead.

    Accepting or rejecting through COM one revision at a time does not
    do what the filter says. A paragraph-level insert/delete is a PAIR,
    and handling one side of it leaves the other applied as plain
    untracked text; Word then reports a plausible number — 4 of 9
    processed — for an outcome nobody asked for. The count is the trap:
    it describes revisions Word touched, not text the reader ends up
    with. Whatever route is taken, verify with
    :func:`docxkit.revisions.changed_paragraphs`, which compares the
    resulting TEXT.
    """
    yield from doc.Revisions


def draft_view(doc: Any) -> None:
    """Draft view with markup hidden — balloon layout is pure cost."""
    with _suppress_com("switch to draft view"):
        view = doc.ActiveWindow.View
        view.Type = WD_NORMAL_VIEW
        view.ShowRevisionsAndComments = False


def compare_documents(word: Any, original: Any, revised: Any, *,
                      author: str = "Revision",
                      whitespace: bool = True,
                      formatting: bool = True) -> Any:
    """``CompareDocuments`` into a new tracked-changes document.

    Fast (a few seconds even on a book-length manuscript) — if a redline
    build is slow, the cost is in what you do with the revisions, not here.

    `whitespace` and `formatting` are exposed because they change the
    deliverable, not just its speed, and papers disagree: the Life
    Expectancy recipe compares with whitespace OFF, so that respacing at
    an edit boundary is not shown to an editor as a revision. Two routes
    built with different settings produce different redlines from the
    same pair of documents.
    """
    return word.CompareDocuments(
        original, revised,
        Destination=WD_COMPARE_TO_NEW,
        Granularity=1,                 # word level
        CompareFormatting=formatting, CompareCaseChanges=True,
        CompareWhitespace=whitespace, CompareTables=True,
        CompareHeaders=True,
        CompareFootnotes=True, CompareTextboxes=True, CompareFields=True,
        CompareComments=True, CompareMoves=True,
        RevisedAuthor=author, IgnoreAllComparisonWarnings=True)


def extract_flat_opc(doc: Any, out_xml: str | Path) -> Path:
    """Write ``Content.WordOpenXML`` — the save-hang / tracked-math bypass.

    Word cannot SaveAs2 a compare result containing tracked math, and its
    save path can hang outright. Reading the Flat OPC package out of the
    open document sidesteps both.
    """
    out_xml = Path(out_xml)
    out_xml.write_text(doc.Content.WordOpenXML, encoding="utf-8")
    return out_xml


def flat_opc_to_docx(flat_path: str | Path, out_path: str | Path) -> int:
    """Repack a Flat OPC package as a .docx zip. Returns the part count."""
    tree = etree.parse(str(flat_path))
    parts = tree.getroot().findall(PKG + "part")
    if not parts:
        raise PackageError(
            "no pkg:part elements - not a Flat OPC package?")

    # To lxml a None key means "the default namespace" — what serializes
    # as a bare xmlns= rather than a prefix, which is how Word writes
    # [Content_Types].xml — but lxml-stubs 0.5 has no spelling for that
    # key, so the mapping is cast.
    nsmap = cast("dict[str, str]", {None: CT_NS})
    ct_root = etree.Element(f"{{{CT_NS}}}Types", nsmap=nsmap)
    for ext, default_ct in (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
        ("png", "image/png"), ("jpeg", "image/jpeg"), ("jpg", "image/jpeg"),
        ("gif", "image/gif"),
        ("bin", "application/vnd.openxmlformats-officedocument.oleObject"),
        ("wmf", "image/x-wmf"), ("emf", "image/x-emf"),
        ("odttf",
         "application/vnd.openxmlformats-officedocument.obfuscatedFont"),
    ):
        d = etree.SubElement(ct_root, f"{{{CT_NS}}}Default")
        d.set("Extension", ext)
        d.set("ContentType", default_ct)

    entries = []
    for part in parts:
        name = part.get(PKG + "name")
        ctype = part.get(PKG + "contentType")
        if name is None or ctype is None:
            raise PackageError(
                "pkg:part missing its pkg:name or pkg:contentType - not a "
                "Flat OPC package Word produced")
        xml_data = part.find(PKG + "xmlData")
        bin_data = part.find(PKG + "binaryData")
        if xml_data is not None:
            children = list(xml_data)
            if len(children) != 1:
                raise PackageError(
                    f"{name}: expected 1 xmlData child, got {len(children)}")
            payload = (b'<?xml version="1.0" encoding="UTF-8" '
                       b'standalone="yes"?>\r\n'
                       + etree.tostring(children[0], encoding="utf-8"))
        elif bin_data is not None:
            payload = base64.b64decode(bin_data.text or "")
        else:
            raise PackageError(f"{name}: neither xmlData nor binaryData")
        entries.append((name.lstrip("/"), payload))
        if not ctype.endswith("relationships+xml"):
            ov = etree.SubElement(ct_root, f"{{{CT_NS}}}Override")
            ov.set("PartName", name)
            ov.set("ContentType", ctype)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   b"\r\n" + etree.tostring(ct_root, encoding="utf-8"))
        for name, payload in entries:
            z.writestr(name, payload)
    return len(entries)


def export_pdf(path: str | Path, out_pdf: str | Path,
               *, first: int | None = None, last: int | None = None) -> Path:
    """Render to PDF via Word.

    The way to check equations visually: Word keeps OMML, LibreOffice does
    not. Works even when saving hangs, so it is also a liveness check.

    The destination is RESOLVED first. A relative path is relative to the
    caller's working directory and means nothing to Word, which has its
    own — so the render landed in Word's default folder while this
    returned a path with no file at it, and the caller went looking for a
    PDF that was never written there.
    """
    out_pdf = Path(out_pdf).resolve()
    with session() as word, open_doc(word, path) as doc:
        if first and last:
            doc.ExportAsFixedFormat(str(out_pdf), WD_EXPORT_PDF, False, 0,
                                    WD_EXPORT_FROM_TO, first, last)
        else:
            doc.ExportAsFixedFormat(str(out_pdf), WD_EXPORT_PDF)
    return out_pdf


def page_count(path: str | Path) -> int:
    """Laid-out page count (needs Word; no XML pass can tell you this)."""
    with session() as word, open_doc(word, path) as doc:
        paginate(doc)
        return int(doc.ComputeStatistics(WD_STATISTIC_PAGES))


@contextlib.contextmanager
def ruler(word: Any, *, size_pt: float = 10.0
          ) -> Iterator[Callable[[str, Sequence[str]], list[float]]]:
    """Ask Word how wide it ACTUALLY lays text out. Yields
    ``measure(font, texts) -> widths in dxa``.

    The column-width model in :mod:`docxkit.tables` approximates this;
    without a way to ask, an error in a metric table is invisible until a
    manuscript comes back with wrapped rows — which is how a 10% error in
    the Arial Narrow digits survived for months. `tests/test_width_model.py`
    is the gate built on this.

    Two traps are closed here rather than left to the caller:

    * **A font that is not installed is refused.** Word substitutes
      another face without a word of complaint and measures THAT one, so
      a calibration run would quietly describe the wrong typeface.
    * **A string that wraps is refused.** The end-of-text position would
      then be measured on the second line and come back far too small —
      a wrong number that looks entirely plausible.

    For a single character's advance, measure a repetition and take the
    difference: ``(w(c*40) - w(c*20)) / 20`` cancels the side bearings
    and any edge effect.

    Expect a passing run to print first-chance Windows exceptions
    (RPC_S_CALL_FAILED, RPC_S_SERVER_UNAVAILABLE) from Word's own
    teardown: an invisible instance that has been asked layout questions
    does not always survive to answer the Close and Quit. They are dumped
    by faulthandler, the suppressed handlers here and in :func:`session`
    absorb them, and the count is not stable between runs — measured 0,
    3 and 5 for the same work. Not worth chasing; worth knowing about
    before you do.
    """
    installed = {str(name) for name in word.FontNames}
    doc = word.Documents.Add()
    try:
        # Print layout explicitly: position information describes a page,
        # and a machine whose default view is draft would answer about a
        # layout that has no pages.
        with _suppress_com("set print layout on the measuring document"):
            doc.ActiveWindow.View.Type = WD_PRINT_VIEW
        setup = doc.PageSetup
        setup.PageWidth = 1584          # Word's maximum, in points
        setup.LeftMargin = setup.RightMargin = 18

        def measure(font: str, texts: Sequence[str]) -> list[float]:
            if font not in installed:
                raise FontMissing(
                    f"font {font!r} is not installed - Word would "
                    "substitute another face and the measurement would "
                    "describe that one instead")
            bad = [t for t in texts if _LINE_BREAK.search(t)]
            if bad:
                raise AnchorError(
                    f"ruler: {bad[0]!r} contains a line break; paragraphs "
                    "are the unit of measurement here")
            doc.Content.Delete()
            doc.Content.Text = "\r".join(texts)
            doc.Content.Font.Name = font
            doc.Content.Font.Size = size_pt
            doc.Content.ParagraphFormat.LeftIndent = 0
            out: list[float] = []
            for i, text in enumerate(texts, start=1):
                rng = doc.Paragraphs(i).Range
                head = doc.Range(rng.Start, rng.Start)
                # End-1 steps back over the paragraph mark itself.
                tail = doc.Range(max(rng.Start, rng.End - 1),
                                 max(rng.Start, rng.End - 1))
                if head.Information(WD_INFO_LINE) != tail.Information(
                        WD_INFO_LINE):
                    raise AnchorError(
                        f"ruler: {text!r} wraps at {size_pt}pt in {font} - "
                        "its width cannot be read off one line")
                out.append((tail.Information(WD_HORIZ_POS_PAGE)
                            - head.Information(WD_HORIZ_POS_PAGE)) * 20.0)
            return out

        yield measure
    finally:
        with _suppress_com("close the measuring document"):
            doc.Close(SaveChanges=0)


# --- where a sentence falls on the page ------------------------------------
#
# What a response letter needs is "R2a - revised, p. 14", and only Word can
# say where page 14 starts. Three things make that harder than it looks, and
# all three are handled below rather than left to the caller:
#
# * `session(fast=True)` turns Options.Pagination OFF, so an unrepaginated
#   document answers from a stale layout. Measured on le14_clean (41 pages):
#   the end of the document reported page 3 before `Repaginate()` and 41
#   after. A wrong page number is worse than none, so `paginate()` is not
#   optional and every entry point here calls it.
# * `Information()` answers for the range's ACTIVE END, so asking a whole
#   document for its page returns the LAST one. Ranges are collapsed to
#   their start first.
# * Page numbers belong to the file you measured. A redline paginates
#   longer than its clean twin because the deleted text is still laid out
#   (le14: 47 pages against 41), and switching the window to a no-markup
#   view does NOT change that - ShowRevisionsAndComments=False,
#   RevisionsFilter.Markup=0 and RevisionsView=Final all still measured 47.
#   So for numbers an editor will recognise, locate the revision's inserted
#   text in the CLEAN build; `locate_revisions` reports the redline's own
#   pages, which is what you want for navigating the redline itself.


class Location(NamedTuple):
    """Where an anchor sits in the laid-out document."""

    anchor: str
    page: int          # as printed: section restarts are taken into account
    line: int          # counted from the top of THAT page, not the document
    doc_page: int      # the page's position in the file
    repeats: bool      # the anchor occurs again later; this is the first hit

    def __str__(self) -> str:
        where = f"p. {self.page}, line {self.line}"
        return where if self.page == self.doc_page \
            else f"{where} (file page {self.doc_page})"


class RevisionLocation(NamedTuple):
    """Where one tracked revision sits, in the redline's own pagination.

    The position in the scan is ``number``, not ``index``: a NamedTuple
    field called ``index`` would shadow ``tuple.index``.
    """

    number: int
    kind: str
    text: str
    page: int
    line: int
    doc_page: int


_REVISION_KINDS = {
    1: "insert", 2: "delete", 3: "property", 4: "paragraph-number",
    5: "display-field", 6: "reconcile", 7: "conflict", 8: "style",
    9: "replace", 10: "paragraph-property", 11: "table-property",
    12: "section-property", 13: "style-definition", 14: "move-from",
    15: "move-to", 16: "cell-insertion", 17: "cell-deletion",
    18: "cell-merge", 19: "cell-split",
}


def paginate(doc: Any) -> None:
    """Force a real page layout, the prerequisite for any page number.

    ``Repaginate()`` is what makes the answer correct, and it is not
    optional: `session(fast=True)` turns background pagination off, so an
    untouched document answers from a stale layout.

    Print layout is set as well, but measurement says that part is
    insurance rather than the fix — on le14_clean, draft view returned the
    same page and line for every anchor once repaginated. It is set anyway
    because these numbers are meant to describe the printed page, and
    :func:`draft_view` leaves documents in the other view.
    """
    with _suppress_com("set print layout before repaginating"):
        doc.ActiveWindow.View.Type = WD_PRINT_VIEW
    doc.Repaginate()


def search_text(anchor: str) -> str:
    """The anchor as Word's Find box will accept it.

    Find has exactly one escape (``^^`` for a caret) and raises rather than
    misses on the rest: an unescaped ``^`` is rejected as "not a valid
    special character", and anything over 255 characters as "String
    parameter too long". It cannot match across a paragraph mark either, so
    the anchor becomes its first NON-BLANK line — a revision's text often
    starts with the paragraph mark it inserted, and taking the first line
    literally would search for nothing.
    """
    for raw in _LINE_BREAK.split(anchor):
        text = raw.strip()
        if text:
            break
    else:
        raise AnchorError(
            f"anchor {anchor!r} has no searchable text - an empty Find "
            f"matches formatting, not text, and would report a page for "
            f"nothing")
    # Cut to the limit as Word counts it: an escaped caret costs two, and
    # cutting after escaping could split a "^^" pair in half.
    out: list[str] = []
    budget = FIND_LIMIT
    for ch in text:
        piece = "^^" if ch == "^" else ch
        budget -= len(piece)
        if budget < 0:
            break
        out.append(piece)
    return "".join(out)


class _Layout:
    """One paginated document, asked through two reused probe Ranges.

    Fresh COM objects are the expensive pattern, and it is the OBJECTS,
    not dynamic name lookup: makepy static binding measured no gain at
    all (5.8s vs 5.9s per 150 revisions, identical results), while a
    Find configured from scratch on a new Range costs ~105 ms per anchor
    against ~52 ms through one re-aimed Range/Find pair — measured
    interleaved on le14_clean, identical results. So the Find is
    configured once and re-aimed with ``SetRange``, and page questions go
    through one collapsed probe Range.

    Both probes live in the MAIN story (``doc.Range``), which is also the
    only story Find searches — an anchor that exists only in a footnote
    is reported missing, never mislocated. Revision ranges can live in
    other stories, which is why :func:`revision_locations` collapses each
    revision's own range instead of using this.
    """

    def __init__(self, doc: Any) -> None:
        paginate(doc)
        self.end = int(doc.Content.End)
        self._range = doc.Range(0, 0)
        find = self._range.Find
        find.ClearFormatting()
        find.Forward = True
        find.Wrap = WD_FIND_STOP   # never restart at the top behind our back
        find.Format = False
        find.MatchCase = True
        find.MatchWholeWord = False
        find.MatchWildcards = False
        find.MatchSoundsLike = False
        find.MatchAllWordForms = False
        self._find = find
        self._probe = doc.Range(0, 0)

    def find(self, text: str, start: int) -> tuple[int, int] | None:
        """Offsets of the first hit at or after `start`, else None."""
        if start >= self.end:
            return None
        self._range.SetRange(start, self.end)
        self._find.Text = text
        if not self._find.Execute():
            return None
        # Execute() rewrote the range in place to the match it found.
        return int(self._range.Start), int(self._range.End)

    def at(self, pos: int) -> tuple[int, int, int]:
        """(printed page, line on that page, file page) at an offset.

        The probe is collapsed because ``Information()`` answers for a
        range's ACTIVE END — asked about a spanning range it reports
        where the range ends, not where it starts.
        """
        self._probe.SetRange(pos, pos)
        return (int(self._probe.Information(WD_INFO_ADJUSTED_PAGE)),
                int(self._probe.Information(WD_INFO_LINE)),
                int(self._probe.Information(WD_INFO_PAGE)))


def locate_in(doc: Any, anchors: Iterable[str], *,
              ordered: bool = False,
              strict: bool = True,
              unique: bool = True) -> list[Location]:
    """Page and line for each anchor, in an already-open Document.

    Returns a :class:`Location` per anchor it found, in the order given —
    so with `strict` the result lines up with `anchors`, and without it the
    misses are simply absent (each Location carries its own anchor, so a
    dict comprehension over the result is the intended way to read it).
    An anchor with no searchable text — a property-level revision's empty
    string, say — counts as a miss, not a crash; under `strict` it is
    reported with the rest. Find searches the main text story only, so a
    phrase living in a footnote is a miss too.

    `ordered` searches each anchor forward from the previous hit rather
    than from the top. For anchors already in document order — a scan of
    revisions, say — that resolves a repeated phrase to the right
    occurrence instead of the first, and keeps the search from being
    O(position) in a long document. An anchor not found ahead is retried
    over the whole document, so one out-of-order anchor costs speed, not
    results.

    `unique` costs one extra Find per anchor and sets `Location.repeats`;
    turn it off for bulk runs where the first hit is good enough.

    Measured on le14_clean (41 pages), pagination included: eight anchors
    in 1.5s from the top, 0.4s ordered.
    """
    layout = _Layout(doc)
    found: list[Location] = []
    missing: list[str] = []
    cursor = 0
    for anchor in anchors:
        try:
            text = search_text(anchor)
        except AnchorError:
            missing.append(anchor)
            continue
        hit = layout.find(text, cursor)
        if hit is None and cursor:
            hit = layout.find(text, 0)   # not ahead: try the whole document
        if hit is None:
            missing.append(anchor)
            continue
        page, line, doc_page = layout.at(hit[0])
        repeats = bool(unique and layout.find(text, hit[1]))
        found.append(Location(anchor, page, line, doc_page, repeats))
        if ordered:
            cursor = hit[1]
    if strict and missing:
        shown = ", ".join(repr(a[:60]) for a in missing[:5])
        raise AnchorError(
            f"{len(missing)} of {len(found) + len(missing)} anchors not "
            f"found in the laid-out document: {shown}"
            f"{' ...' if len(missing) > 5 else ''}")
    return found


def locate(path: str | Path, anchors: Iterable[str], *,
           ordered: bool = False,
           strict: bool = True,
           unique: bool = True) -> list[Location]:
    """Page and line for each anchor in `path` (needs Word).

    The page numbers are the ones this file prints, so for a response
    letter run it against the CLEAN manuscript the editor will read, not
    against the redline — see the note above :class:`Location`.
    """
    with session() as word, open_doc(word, path) as doc:
        return locate_in(doc, anchors, ordered=ordered, strict=strict,
                         unique=unique)


def revision_locations(doc: Any, *,
                       limit: int | None = None) -> list[RevisionLocation]:
    """Page and line for every tracked revision, in an open Document.

    No searching involved — a revision already knows its own Range. The
    page is asked of a collapsed COPY of that range (``Range`` hands back
    a fresh object, so the collapse touches nothing) rather than of a
    shared probe: a footnote revision's offsets are footnote-story
    coordinates, and re-basing them into the main story would name a
    wrong page. The reused-probe trick was measured against this and
    changed nothing (~55 ms per revision either way — the cost is Word's,
    not the extra object's), so budget a minute for a book-length redline:
    le14_tracked's 701 revisions take ~62s.
    """
    if limit is not None and limit < 1:
        return []
    paginate(doc)
    out: list[RevisionLocation] = []
    for number, rev in enumerate(revisions(doc), 1):
        rng = rev.Range                     # a fresh copy on every access
        text = str(rng.Text or "")          # before the collapse empties it
        rng.Collapse(WD_COLLAPSE_START)
        out.append(RevisionLocation(
            number,
            _REVISION_KINDS.get(int(rev.Type), f"type-{int(rev.Type)}"),
            text,
            int(rng.Information(WD_INFO_ADJUSTED_PAGE)),
            int(rng.Information(WD_INFO_LINE)),
            int(rng.Information(WD_INFO_PAGE))))
        if number == limit:
            break
    return out


def locate_revisions(path: str | Path, *,
                     limit: int | None = None) -> list[RevisionLocation]:
    """Page and line for every tracked revision in `path` (needs Word).

    These are the REDLINE's page numbers. It runs longer than the clean
    build because deleted text is still laid out, and no markup setting
    changes that (le14: 47 pages against the clean file's 41).
    """
    with session() as word, open_doc(word, path) as doc:
        return revision_locations(doc, limit=limit)
