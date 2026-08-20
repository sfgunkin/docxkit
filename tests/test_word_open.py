"""``open_doc``'s write target — the part that needs no Word to check.

Staging a document through TEMP is right for reading and WRONG for
writing: the ``Save()`` lands on the staged copy, the file the caller
named is never touched, and the Document reports the same counts either
way. A reviewer lost real time to that silence and drew a false
conclusion from it — an accept/reject comparison that "proved" a
divergence from Word was entirely this default.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

import pytest

from docxkit import word


def test_local_defaults_to_following_read_only():
    sig = inspect.signature(word.open_doc)
    assert sig.parameters["local"].default is None
    assert sig.parameters["read_only"].default is True


def test_writing_through_a_staged_copy_is_refused(tmp_path):
    """The combination that silently discards. Refused before Word is
    ever launched, so the guard holds on a machine without it."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    with pytest.raises(ValueError, match="local=False"), \
            word.open_doc(None, target, read_only=False, local=True):
        pass                                    # pragma: no cover


def test_reading_still_stages_by_default(tmp_path):
    """The default path is unchanged: a read opens the staged copy,
    because COM against a OneDrive path is flaky."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    opened: list[str] = []

    class _Docs:
        def Open(self, path, **kw):
            opened.append(path)
            return _Doc()

    class _Doc:
        def Close(self, **kw):
            pass

    class _App:
        Documents = _Docs()

    with word.open_doc(_App(), target):
        pass
    assert opened and str(target) != opened[0]  # a staged copy
    assert opened[0].endswith("paper.docx")


def test_writing_opens_the_file_itself(tmp_path):
    """read_only=False now reaches the named file rather than a copy."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    opened: list[str] = []

    class _Docs:
        def Open(self, path, **kw):
            opened.append(path)
            return _Doc()

    class _Doc:
        def Close(self, **kw):
            pass

    class _App:
        Documents = _Docs()

    with word.open_doc(_App(), target, read_only=False):
        pass
    assert opened == [str(target)]


class _Recorder:
    """A Word whose Documents.Open and Document.Close keep their kwargs.

    The tests above record the PATH only, which is what the staging
    question needs. What Open and Close are asked to DO is a separate
    set of promises — do not touch the user's recent-files list, never
    save on the way out — and neither had a witness.
    """

    def __init__(self) -> None:
        self.opened: list[tuple[str, dict[str, Any]]] = []
        self.closed: list[dict[str, Any]] = []
        recorder = self

        class _Doc:
            def Close(self, **kw):
                recorder.closed.append(kw)

        class _Docs:
            def Open(self, path, **kw):
                recorder.opened.append((path, kw))
                return _Doc()

        self.Documents = _Docs()


def test_a_read_may_ask_for_staging_EXPLICITLY(tmp_path):
    """`local and not read_only` — the refusal is for the ONE
    combination that discards a write, and `or` in its place refuses
    two more. This is the first of them: a caller naming the default
    out loud, which is what a script does when it wants the staging to
    survive a change to the default."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    app = _Recorder()

    with word.open_doc(app, target, read_only=True, local=True):
        pass

    (path, _kw), = app.opened
    assert path != str(target) and path.endswith("paper.docx")


def test_a_write_may_ask_for_the_file_itself_EXPLICITLY(tmp_path):
    """The other one `or` refuses, and the one that matters: writing
    with `local=False` is what the docstring tells a caller to pass.
    Under `or` the documented way to write raises the error written for
    the combination that cannot work."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    app = _Recorder()

    with word.open_doc(app, target, read_only=False, local=False):
        pass

    (path, kw), = app.opened
    assert path == str(target)
    assert kw["ReadOnly"] is False


def test_opening_does_not_touch_the_users_recent_files(tmp_path):
    """`AddToRecentFiles=False`. A batch opens a document per step —
    build, compare, locate, export — and a run over one paper would
    otherwise push everything else out of the user's recent list."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    app = _Recorder()

    with word.open_doc(app, target):
        pass

    (_path, kw), = app.opened
    assert kw["AddToRecentFiles"] is False


def test_closing_never_saves(tmp_path):
    """`SaveChanges=0` is wdDoNotSaveChanges; 1 is wdSaveChanges, and
    every close in this module would then write the file back. On a
    read of the author's own manuscript that is an edit nobody asked
    for — and on the staged copy it is a write that goes nowhere, which
    is worse, because it looks like it worked."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    app = _Recorder()

    with word.open_doc(app, target):
        pass

    assert app.closed == [{"SaveChanges": 0}]


# ----------------------------------------------- suppressed COM failures ---

def _com_call_fails() -> None:
    """A COM call Word refuses. Raised from a CALL rather than inline so
    the suppression is opaque to mypy: raising in the with-body makes
    everything after it statically unreachable, and the reachability IS
    what these tests are about."""
    raise RuntimeError("Call was rejected by callee")


def test_a_failed_com_call_is_still_suppressed(caplog):
    """The control flow does not change: a COM teardown failure must not
    propagate, or one hostile revision aborts a 1400-revision build."""
    with (caplog.at_level(logging.DEBUG, logger="docxkit.word"),
          word._suppress_com("Word.Quit")):
        _com_call_fails()
    assert True          # reaching here IS the assertion


def test_what_was_suppressed_says_which_call_and_why(caplog):
    """It used to say nothing at all, so a machine where Word quits badly
    looked exactly like one where everything worked."""
    with (caplog.at_level(logging.DEBUG, logger="docxkit.word"),
          word._suppress_com("restore Word option Pagination")):
        _com_call_fails()
    assert len(caplog.records) == 1
    line = caplog.records[0].getMessage()
    assert "restore Word option Pagination" in line
    assert "RuntimeError" in line and "rejected by callee" in line
    assert caplog.records[0].levelno == logging.DEBUG


def test_a_call_that_works_logs_nothing(caplog):
    with (caplog.at_level(logging.DEBUG, logger="docxkit.word"),
          word._suppress_com("CoInitialize")):
        pass
    assert caplog.records == []


def test_the_library_configures_no_logging_of_its_own():
    """A library takes a logger and no handler: docxkit must not hijack
    the logging of a paper script that imports it."""
    log = logging.getLogger("docxkit.word")
    assert log.handlers == []
    assert log.level == logging.NOTSET


# ------------------------------------------------ Word's own numbers ----
# These are not this package's values to choose: each is a member of a
# documented WdEnum, and Word reads the NUMBER. A wrong one does not
# raise — Word does something else, quietly and plausibly. That is how
# `wdExportAllDocument` (0) sat in the argument that decides whether
# From/To are read at all and turned every page range into a full
# render, and the two families below are one digit apart in exactly the
# way that produces it: wdFormatXMLDocument is 12 and
# wdFormatDocumentDefault is 16, wdWithInTable is 12 and wdPrintView
# is 3.
#
# So they are pinned by NAME here. A mutation of any of them is a
# silently different Word instruction, and no other test can see it
# without Word running.
WD_ENUM_MEMBERS = [
    ("WD_NORMAL_VIEW", 1, "WdViewType.wdNormalView"),
    ("WD_PRINT_VIEW", 3, "WdViewType.wdPrintView"),
    ("WD_WITHIN_TABLE", 12, "WdInformation.wdWithInTable"),
    ("WD_COMPARE_TO_NEW", 2, "WdCompareTarget.wdCompareTargetNew"),
    ("WD_FORMAT_DOCX", 16, "WdSaveFormat.wdFormatDocumentDefault"),
    ("WD_EXPORT_PDF", 17, "WdExportFormat.wdExportFormatPDF"),
    ("WD_EXPORT_ALL_DOCUMENT", 0, "WdExportRange.wdExportAllDocument"),
    ("WD_EXPORT_FROM_TO", 3, "WdExportRange.wdExportFromTo"),
    ("WD_STATISTIC_PAGES", 2, "WdStatistic.wdStatisticPages"),
    ("WD_COLLAPSE_START", 1, "WdCollapseDirection.wdCollapseStart"),
    ("WD_FIND_STOP", 0, "WdFindWrap.wdFindStop"),
    ("WD_INFO_ADJUSTED_PAGE", 1,
     "WdInformation.wdActiveEndAdjustedPageNumber"),
    ("WD_INFO_PAGE", 3, "WdInformation.wdActiveEndPageNumber"),
    ("WD_INFO_LINE", 10, "WdInformation.wdFirstCharacterLineNumber"),
    ("WD_HORIZ_POS_PAGE", 5,
     "WdInformation.wdHorizontalPositionRelativeToPage"),
]


@pytest.mark.parametrize("name,value,member", WD_ENUM_MEMBERS)
def test_a_word_constant_is_the_number_word_documents(name, value, member):
    """Pinned against the enum member it stands for, not against
    itself: the number belongs to Word, and the name is the only thing
    that says which number is right."""
    assert getattr(word, name) == value, f"{name} is {member}"


def test_every_word_constant_is_pinned():
    """The table is the point, so it has to stay complete: a constant
    added without a line here is one nothing checks, and the reason
    these are pinned at all is that nothing else can check them."""
    declared = {n for n in vars(word) if n.startswith("WD_")}
    assert declared == {n for n, _, _ in WD_ENUM_MEMBERS}


def test_the_find_limit_is_words_own_ceiling():
    """255 is what Word's Find box accepts; a longer pattern is not
    truncated by it but refused, and the caller splits the search."""
    assert word.FIND_LIMIT == 255


@pytest.mark.parametrize("option", sorted(word._FAST_OPTIONS))
def test_every_bulk_edit_option_is_switched_OFF(option):
    """All four are speed, and all four are False. One left True is a
    Word that repaginates or spell-checks between every edit — minutes
    on a manuscript, and nothing to see in the output."""
    assert word._FAST_OPTIONS[option] is False


def test_a_staged_copy_WORD_still_holds_does_not_fail_the_call(tmp_path):
    """`ignore_errors=True` on the staging directory. Word is the one
    holding the file — `Close` returns before it has let go of the
    handle often enough — and on Windows a directory holding an open
    file cannot be removed. Without the flag, that PermissionError
    comes out of the `finally`, which means it also REPLACES whatever
    the body was raising: the caller is told about a temp directory
    instead of about their document.

    The stand-in keeps the handle open for the same reason Word does."""
    target = tmp_path / "paper.docx"
    target.write_bytes(b"not really a docx")
    handles: list[Any] = []

    class _Docs:
        def Open(self, path, **kw):
            handles.append(open(path, "rb"))    # noqa: SIM115 - Word's grip
            return _Doc()

    class _Doc:
        def Close(self, **kw):
            pass

    class _App:
        Documents = _Docs()

    try:
        with word.open_doc(_App(), target):
            pass
    finally:
        for fh in handles:
            fh.close()

    assert handles, "the fixture has to have opened the staged copy"
