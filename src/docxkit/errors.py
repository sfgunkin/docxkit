"""Exceptions docxkit raises.

A library must not call ``SystemExit``: that kills the caller's process
rather than letting it decide. Everything here is catchable, and the CLI
turns a :class:`DocxKitError` into a clean message with no traceback.

:class:`AnchorError` also derives from ``AssertionError`` on purpose. A
missing or ambiguous anchor means a build invariant broke — the same class
of failure as a bare ``assert`` in a build script — so existing
``except AssertionError`` and ``pytest.raises(AssertionError)`` around
build code keep working.
"""
from __future__ import annotations

__all__ = [
    "AnchorError",
    "DocumentLocked",
    "DocxKitError",
    "PackageError",
    "ScaffoldMissing",
]


class DocxKitError(Exception):
    """Base for every error docxkit raises deliberately."""


class DocumentLocked(DocxKitError):
    """The .docx is held open by another process (almost always Word).

    Worth failing on before any write: Word holds an exclusive handle, so
    the write dies half-way and leaves a truncated file where the
    manuscript used to be.
    """


class AnchorError(DocxKitError, AssertionError):
    """An anchor was not found, or matched more times than expected.

    Silence here is the dangerous outcome: a replace that matches nothing
    lets a build keep "succeeding" while quietly dropping an edit.
    """


class PackageError(DocxKitError):
    """The .docx package is missing a part, or is not what it claims."""


class ScaffoldMissing(PackageError):
    """The package carries no Word-made comment to clone.

    Comment parts, styles and relationships have to come from Word itself;
    hand-rolling them is how a file ends up "repaired" on open.
    """
