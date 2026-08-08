r"""Helpers for the paper value-test suites.

Every paper has a ``test_paper_values.py`` that recomputes the
manuscript's numbers from the data, and each one had rebuilt the same
scaffolding: resolve which docx is current, read it without tripping over
Word's lock, find a table, pull a number out of a cell or out of prose,
compare to data within the tolerance the rendering implies.

Importing pytest is optional. With pytest present, a missing or locked
paper SKIPS rather than fails — a suite should not go red because the
author happens to have the manuscript open.
"""
from __future__ import annotations

import io
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, NoReturn

from ._xml import DOCUMENT
from .errors import DocumentLocked, PackageError

__all__ = [
    "latest_version",
    "load_document",
    "load_xml",
    "load_zip",
    "prose_numbers",
    "read_bytes",
]

# "afi_v11.docx" -> 11. A backup such as afi_v11_pre_fig8_backup.docx must
# NOT match, or the tests would silently read a snapshot.
_VERSION_RE = re.compile(r"^(?P<stem>.+)_v(?P<n>\d+)\.docx$", re.IGNORECASE)
# a number as it appears in prose, with its sign and decimals
_PROSE_NUM_RE = re.compile(r"[-−+]?\d+(?:\.\d+)?%?")


def latest_version(directory: str | Path, stem: str | None = None) -> Path:
    """Highest-numbered ``<stem>_vN.docx`` in `directory`.

    Papers roll forward (afi_v9 -> afi_v10 -> ...), so tests must never
    name a version: they would keep passing against a stale file after
    the paper moved on. Backup and working snapshots do not match the
    pattern and so are never picked up.
    """
    directory = Path(directory)
    found = []
    for p in directory.glob("*.docx"):
        m = _VERSION_RE.match(p.name)
        if m and (stem is None or m.group("stem").lower() == stem.lower()):
            found.append((int(m.group("n")), p))
    if not found:
        raise PackageError(
            f"no {stem or '<stem>'}_vN.docx in {directory}")
    return max(found)[1]


def read_bytes(path: str | Path, *, skip_if_locked: bool = True) -> bytes:
    """Read a .docx into memory, tolerating Word having it open.

    Copies through TEMP first: Word holds a lock that makes a direct read
    fail. With pytest importable and `skip_if_locked`, a locked file
    skips the test rather than failing it.
    """
    path = Path(path)
    if not path.exists():
        _skip_or_raise(f"paper docx missing: {path}", skip_if_locked,
                       PackageError)
    with tempfile.TemporaryDirectory(prefix="docxkit_test_") as td:
        tmp = Path(td) / path.name
        try:
            shutil.copy2(path, tmp)
        except PermissionError:
            _skip_or_raise(f"{path.name} is locked by Word; close it and "
                           "retry.", skip_if_locked, DocumentLocked)
        return tmp.read_bytes()


def _skip_or_raise(message: str, allow_skip: bool,
                   error: type) -> NoReturn:
    if allow_skip:
        try:
            import pytest
        except ImportError:
            pass
        else:
            pytest.skip(message)
    raise error(message)


def load_xml(path: str | Path, part: str = DOCUMENT) -> str:
    """One part of the package as text, lock-safe."""
    with zipfile.ZipFile(io.BytesIO(read_bytes(path))) as z:
        return z.read(part).decode("utf-8")


def load_zip(path: str | Path) -> zipfile.ZipFile:
    """The package, backed by an in-memory copy, lock-safe."""
    return zipfile.ZipFile(io.BytesIO(read_bytes(path)))


def load_document(path: str | Path) -> Any:
    """A python-docx ``Document``, lock-safe.

    Use for layout-level work only. It cannot see text inside ``w:ins``,
    so for anything with tracked changes read the XML instead
    (:mod:`docxkit.tables`, :mod:`docxkit.revisions`).
    """
    # python-docx is not a dependency — it was dropped when word_edits
    # retired, and this helper is the only caller left. Absent on a plain
    # install, so pyright must be told at the site; mypy has `docx.*` in
    # ignore_missing_imports.
    from docx import Document  # pyright: ignore[reportMissingImports]

    return Document(io.BytesIO(read_bytes(path)))


def prose_numbers(text: str, *, context: int = 60) -> list[tuple[float, str]]:
    """Every number in prose, with the words around it.

    The raw material for a coverage test: each figure quoted in the text
    should be traceable to the data, and the context is what lets a
    failure say WHICH claim is stale rather than just which number.
    """
    out = []
    for m in _PROSE_NUM_RE.finditer(text):
        raw = m.group(0).rstrip("%").replace("−", "-")
        try:
            value = float(raw)
        except ValueError:
            continue
        lo = max(0, m.start() - context)
        out.append((value, text[lo:m.end() + context].replace("\n", " ")))
    return out
