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
