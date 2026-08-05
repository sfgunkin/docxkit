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
