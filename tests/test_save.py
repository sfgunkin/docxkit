"""`save` and the safe `edit_in_place` — the CLI's save path, for scripts.

Until 2026-09-29 `cli._save` was the only place the save policy lived,
and `docxkit.edit_in_place`, the entry point the README gives paper
scripts, did none of it: no edge-space protection, no lint, no backup
(REVIEW_2026-09-28 §3). These tests hold the library half; the CLI's
printing of the same report is tested in test_cli / test_cli_guards.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_parts, para, run, write

import docxkit
from docxkit import package, save
from docxkit._xml import DOCUMENT
from docxkit.errors import PackageError

#: A `w:del` holding live `w:t`: a lint finding no docxkit verb repairs.
LIVE_DEL = ('<w:p><w:del w:id="9" w:author="A. Editor" '
            'w:date="2026-09-01T00:00:00Z"><w:r><w:t>gone</w:t></w:r>'
            "</w:del></w:p>")


def _paper(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "paper.docx"
    write(path, make_parts(para(run("prose")) + body))
    return path


def _append(parts: dict[str, bytes], xml: str) -> None:
    doc = parts[DOCUMENT].decode("utf-8")
    parts[DOCUMENT] = doc.replace("</w:body>", xml + "</w:body>").encode()


def test_a_clean_save_writes_protects_edge_spaces_and_backs_up(tmp_path):
    path = _paper(tmp_path)
    parts = package.read_parts(path)
    _append(parts, para(run(" spaced ")))

    report = save.save(path, parts, backup_tag="pre_test")

    assert report.written and not report.blocking()
    assert report.protected == 1, "the edge-space run the edit brought"
    assert report.backup is not None and report.backup.exists()
    assert report.backup.parent == tmp_path, "beside it, when not told"
    written = package.read_parts(path)[DOCUMENT].decode("utf-8")
    assert '<w:t xml:space="preserve"> spaced </w:t>' in written


def test_no_backup_is_made_unless_one_is_ASKED_for(tmp_path):
    path = _paper(tmp_path)

    report = save.save(path, package.read_parts(path))

    assert report.written and report.backup is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["paper.docx"]


def test_a_finding_the_EDIT_brings_is_refused_whatever_the_flag(tmp_path):
    path = _paper(tmp_path)
    before = path.read_bytes()
    parts = package.read_parts(path)
    _append(parts, LIVE_DEL)

    report = save.save(path, parts, backup_tag="pre_test",
                       allow_existing_lint=True)

    assert not report.written and report.fresh and not report.existing
    assert report.blocking() == list(report.fresh)
    assert "this edit would leave markup" in report.refusal()
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["paper.docx"]


def test_a_finding_the_file_ALREADY_had_is_refused_unless_allowed(tmp_path):
    path = _paper(tmp_path, LIVE_DEL)
    before = path.read_bytes()

    refused = save.save(path, package.read_parts(path))

    assert not refused.written and refused.existing and not refused.fresh
    assert "--x" in refused.refusal(flag="--x"), "the caller's own words"
    assert path.read_bytes() == before

    allowed = save.save(path, package.read_parts(path),
                        allow_existing_lint=True)

    assert allowed.written and allowed.existing
    assert allowed.blocking() == [], "written, so nothing blocked it"
    assert allowed.refusal() == ""


def test_a_file_that_cannot_be_RE_READ_counts_every_finding_as_new(
        tmp_path, monkeypatch):
    """No answer to "was it already there" means the conservative one."""
    path = _paper(tmp_path, LIVE_DEL)
    parts = package.read_parts(path)

    def locked(*_args: object, **_kw: object) -> None:
        raise PackageError("paper.docx is locked (open in Word)")

    monkeypatch.setattr(package, "read_parts", locked)

    report = save.save(path, parts, allow_existing_lint=True)

    assert not report.written and report.fresh and not report.existing


def test_the_TOP_LEVEL_edit_in_place_is_the_safe_one(tmp_path):
    """`docxkit.edit_in_place` saves through the lint; the raw one in
    `package` is kept, unchanged, for the scripts that import it there."""
    assert docxkit.edit_in_place is save.edit_in_place
    assert package.edit_in_place is not save.edit_in_place
    path = _paper(tmp_path)
    before = path.read_bytes()

    with pytest.raises(PackageError, match="nothing written"):
        docxkit.edit_in_place(path, lambda parts: _append(parts, LIVE_DEL))

    assert path.read_bytes() == before


def test_edit_in_place_writes_OVER_a_finding_the_file_already_had(tmp_path):
    """The library default: a script re-run on a manuscript that already
    carries a finding wrote before the save was safe, and must not start
    failing for a condition it did not cause."""
    path = _paper(tmp_path, LIVE_DEL)

    def add(parts: dict[str, bytes]) -> str:
        _append(parts, para(run("added")))
        return "report"

    got = docxkit.edit_in_place(path, add)

    assert got == "report"
    assert "added" in package.read_parts(path)[DOCUMENT].decode("utf-8")
    with pytest.raises(PackageError, match="already carried"):
        docxkit.edit_in_place(path, lambda parts: None,
                              allow_existing_lint=False)


def test_edit_in_place_DRY_writes_nothing_and_a_missing_file_says_so(
        tmp_path):
    path = _paper(tmp_path)
    before = path.read_bytes()

    def add(parts: dict[str, bytes]) -> int:
        _append(parts, para(run("x")))
        return 7

    got = docxkit.edit_in_place(path, add, dry=True)

    assert got == 7 and path.read_bytes() == before
    with pytest.raises(PackageError, match="missing"):
        docxkit.edit_in_place(tmp_path / "gone.docx", lambda parts: None)
