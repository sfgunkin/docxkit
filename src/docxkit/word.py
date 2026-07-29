r"""Driving Word through COM, with the traps already paid for.

Word is needed for exactly three things no XML pass can do: diff two
documents into a tracked-changes redline, lay pages out (page counts), and
render to PDF. Everything else is faster and safer in XML.

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
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

from lxml import etree

from .errors import PackageError

__all__ = [
    "compare_documents",
    "export_pdf",
    "extract_flat_opc",
    "flat_opc_to_docx",
    "open_doc",
    "page_count",
    "revisions",
    "session",
]

PKG = "{http://schemas.microsoft.com/office/2006/xmlPackage}"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

WD_NORMAL_VIEW = 1
WD_WITHIN_TABLE = 12
WD_COMPARE_TO_NEW = 2
WD_FORMAT_DOCX = 16
WD_EXPORT_PDF = 17
WD_STATISTIC_PAGES = 2

# Word options switched off for bulk edits; restored on exit so an
# interactive Word is not left reconfigured.
_FAST_OPTIONS = {
    "Pagination": False,
    "CheckSpellingAsYouType": False,
    "CheckGrammarAsYouType": False,
    "BackgroundSave": False,
}


@contextlib.contextmanager
def session(*, fast: bool = True) -> Iterator:
    """A private, invisible Word instance, always quit on the way out.

    Uses DispatchEx so an interactive Word the user has open is neither
    reused nor closed.
    """
    import pythoncom
    import win32com.client as com

    with contextlib.suppress(Exception):
        pythoncom.CoInitialize()
    word = com.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    saved = {}
    if fast:
        for name, value in _FAST_OPTIONS.items():
            with contextlib.suppress(Exception):
                saved[name] = getattr(word.Options, name)
                setattr(word.Options, name, value)
        with contextlib.suppress(Exception):
            word.ScreenUpdating = False
    try:
        yield word
    finally:
        for name, value in saved.items():
            with contextlib.suppress(Exception):
                setattr(word.Options, name, value)
        with contextlib.suppress(Exception):
            word.Quit()


@contextlib.contextmanager
def open_doc(word, path: str | Path, *, read_only: bool = True,
             local: bool = True) -> Iterator:
    """Open `path`, yielding the Document; closed without saving.

    `local` stages the file through TEMP first (the default) because COM
    against a OneDrive path is a documented source of flaky failures.
    """
    path = Path(path)
    td = Path(tempfile.mkdtemp(prefix="docxkit_word_")) if local else None
    target = td / path.name if td else path
    if td:
        shutil.copy2(path, target)
    doc = word.Documents.Open(str(target), ReadOnly=read_only,
                              AddToRecentFiles=False)
    try:
        yield doc
    finally:
        with contextlib.suppress(Exception):
            doc.Close(SaveChanges=0)
        if td:
            shutil.rmtree(td, ignore_errors=True)


def revisions(doc) -> Iterator:
    """Iterate revisions through the enumerator, never by index.

    Indexing ``Revisions(i)`` is O(i); a full indexed scan of a
    316-revision document costs ~280s against ~6s here.
    """
    yield from doc.Revisions


def draft_view(doc) -> None:
    """Draft view with markup hidden — balloon layout is pure cost."""
    with contextlib.suppress(Exception):
        view = doc.ActiveWindow.View
        view.Type = WD_NORMAL_VIEW
        view.ShowRevisionsAndComments = False


def compare_documents(word, original, revised, *, author: str = "Revision"):
    """``CompareDocuments`` into a new tracked-changes document.

    Fast (a few seconds even on a book-length manuscript) — if a redline
    build is slow, the cost is in what you do with the revisions, not here.
    """
    return word.CompareDocuments(
        original, revised,
        Destination=WD_COMPARE_TO_NEW,
        Granularity=1,                 # word level
        CompareFormatting=True, CompareCaseChanges=True,
        CompareWhitespace=True, CompareTables=True, CompareHeaders=True,
        CompareFootnotes=True, CompareTextboxes=True, CompareFields=True,
        CompareComments=True, CompareMoves=True,
        RevisedAuthor=author, IgnoreAllComparisonWarnings=True)


def extract_flat_opc(doc, out_xml: str | Path) -> Path:
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

    ct_root = etree.Element(f"{{{CT_NS}}}Types", nsmap={None: CT_NS})
    for ext, ctype in (
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
        d.set("ContentType", ctype)

    entries = []
    for part in parts:
        name = part.get(PKG + "name")
        ctype = part.get(PKG + "contentType")
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
    """
    out_pdf = Path(out_pdf)
    with session() as word, open_doc(word, path) as doc:
        if first and last:
            doc.ExportAsFixedFormat(str(out_pdf), WD_EXPORT_PDF, False, 0, 0,
                                    first, last)
        else:
            doc.ExportAsFixedFormat(str(out_pdf), WD_EXPORT_PDF)
    return out_pdf


def page_count(path: str | Path) -> int:
    """Laid-out page count (needs Word; no XML pass can tell you this)."""
    with session() as word, open_doc(word, path) as doc:
        doc.Repaginate()
        return int(doc.ComputeStatistics(WD_STATISTIC_PAGES))
