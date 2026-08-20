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
    "BaselinePending",
    "ConversionGap",
    "ConversionRefused",
    "DeliverableModified",
    "DocumentLocked",
    "DocxKitError",
    "FontMissing",
    "HandbackLoss",
    "MathResolved",
    "PackageError",
    "ProtocolError",
    "ScaffoldMissing",
    "StaleBatch",
]


class DocxKitError(Exception):
    """Base for every error docxkit raises deliberately."""


class DocumentLocked(DocxKitError):
    """The .docx is held open by another process (almost always Word).

    Worth failing on before any write: Word holds an exclusive handle, so
    the write dies half-way and leaves a truncated file where the
    manuscript used to be.
    """


class FontMissing(DocxKitError):
    """A font asked of Word is not installed on this machine.

    Its own class because the honest response differs by caller: a
    calibration run SKIPS the face (Word would substitute another and
    the measurement would describe that one), while a build that needs
    the manuscript's font should stop.
    """


class AnchorError(DocxKitError, AssertionError):
    """An anchor was not found, or matched more times than expected.

    Silence here is the dangerous outcome: a replace that matches nothing
    lets a build keep "succeeding" while quietly dropping an edit.
    """


class DeliverableModified(DocxKitError):
    """The output file changed since docxkit last built it.

    A tracked-changes deliverable is derived, but it is also a document
    someone reads and reviews in Word — accepting revisions, leaving
    others pending. Rebuilding over that silently destroys the review.
    The build stops instead, having first taken a backup.
    """


class ConversionGap(DocxKitError):
    """A conversion met a construct it has no faithful rendering for.

    Raised only under ``strict``; the default is to mark the gap inline
    so one exotic element does not hide the rest of the equation.
    """


class ConversionRefused(DocxKitError):
    """A conversion would have changed what the document SAYS.

    `refstyle.convert_text` moves punctuation and glyphs and nothing
    else, and proves it: the entry's letters and digits must be
    identical afterwards, once "&" becoming "and" and a page range
    written out in full are accounted for. A dropped author, a lost DOI
    or a truncated title lands here instead of in the file.

    Its own class because the honest response differs from every other
    refusal in this package: nothing is wrong with the DOCUMENT, and
    re-running will not help — the converter is what has to change.
    """


class PackageError(DocxKitError):
    """The .docx package is missing a part, or is not what it claims."""


class ScaffoldMissing(PackageError):
    """The package carries no Word-made comment to clone.

    Comment parts, styles and relationships have to come from Word itself;
    hand-rolling them is how a file ends up "repaired" on open.
    """


class ProtocolError(DocxKitError):
    """The single-file revision protocol was about to be broken.

    Its subclasses are the three refusals in :mod:`docxkit.revision`,
    and each one exists because the alternative is SILENT: the batch is
    produced, it looks finished, and what it cost — an author's pending
    verdict, an equation nobody can reject, an edit overwritten — is
    discovered later or not at all.

    Each carries its own ``exit_code`` so a script can tell WHICH
    refusal it hit without parsing the message. The two numbers below
    are the ones the protocol's own documentation already quotes.
    """

    exit_code = 1


class BaselinePending(ProtocolError):
    """The baseline still carries revisions nobody has adjudicated.

    Word's Compare rebuilds a redline from ACCEPTED content, so building
    on such a baseline flattens those revisions into plain text: the
    author's open verdicts are decided for them, and the change can
    never be rejected again.
    """

    exit_code = 3


class MathResolved(ProtocolError):
    """Compare resolved tracked math instead of marking it.

    Word cannot serialize a tracked equation, so the new math is simply
    present in the deliverable with nothing to accept or reject, and
    reject-all no longer reproduces the baseline. Author the batch by
    hand instead.
    """

    exit_code = 2


class HandbackLoss(ProtocolError):
    """The author's Word session destroyed structure no text diff shows.

    Word collapses a paragraph into a single run to make an edit, and
    every hyperlink, note reference and bookmark inside it goes at once
    — then it renumbers the notes so the ids stay contiguous and there
    is no gap to notice. The words are all still there, so `ingest`'s
    content layers, `citations` and `crossrefs` are all clean. Raised by
    `revision.baseline`, which is the step that would make the loss
    permanent — `prev.docx` is what the compare chain measures against
    afterwards, so a link Word ate becomes a link that was never there.

    ``revision ingest --check`` reports the same finding one step
    earlier and without touching anything; it exits on this code.
    """

    exit_code = 5


class StaleBatch(ProtocolError):
    """The live file moved on while the batch was being built.

    Promoting anyway overwrites whatever the author did in the
    meantime — the one unrecoverable mistake in this workflow.
    """

    exit_code = 4
