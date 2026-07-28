"""Package I/O: the round trip must not lose or reorder anything."""
from __future__ import annotations

import zipfile

import pytest
from conftest import make_parts, para, run, write

from docxkit import (
    backup,
    edit_in_place,
    is_locked,
    read_parts,
    write_docx,
)
from docxkit.package import next_backup_path


def test_round_trip_preserves_every_part(simple_docx, tmp_path):
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts)
    assert read_parts(out) == parts


def test_write_preserves_member_order(simple_docx, tmp_path):
    with zipfile.ZipFile(simple_docx) as z:
        order = z.namelist()
    parts = read_parts(simple_docx)
    out = tmp_path / "out.docx"
    write_docx(out, parts, order=order)
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == order


def test_write_includes_parts_the_transform_added(simple_docx, tmp_path):
    """A transform that adds media must not have it silently dropped."""
    with zipfile.ZipFile(simple_docx) as z:
        order = z.namelist()
    parts = read_parts(simple_docx)
    parts["word/media/image1.png"] = b"\x89PNG-not-really"
    out = tmp_path / "out.docx"
    write_docx(out, parts, order=order)
    assert "word/media/image1.png" in read_parts(out)


def test_edit_in_place_rewrites_and_preserves_untouched(simple_docx):
    before = read_parts(simple_docx)

    def transform(parts):
        xml = parts["word/document.xml"].decode("utf-8")
        parts["word/document.xml"] = xml.replace("Poland", "Romania").encode()
        return "done"

    assert edit_in_place(simple_docx, transform) == "done"
    after = read_parts(simple_docx)
    assert b"Romania" in after["word/document.xml"]
    assert after["[Content_Types].xml"] == before["[Content_Types].xml"]


def test_edit_in_place_dry_does_not_write(simple_docx):
    before = read_parts(simple_docx)

    def transform(parts):
        parts["word/document.xml"] = b"<destroyed/>"
        return "dry"

    assert edit_in_place(simple_docx, transform, dry=True) == "dry"
    assert read_parts(simple_docx) == before


def test_edit_in_place_leaves_file_intact_when_transform_raises(simple_docx):
    """A crash mid-transform must not truncate the manuscript."""
    before = read_parts(simple_docx)

    def transform(parts):
        parts["word/document.xml"] = b"<half-written/>"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        edit_in_place(simple_docx, transform)
    assert read_parts(simple_docx) == before


def test_backup_numbers_sequentially(tmp_path):
    src = tmp_path / "paper.docx"
    write(src, make_parts(para(run("x"))))
    first = backup(src, "user_edited")
    second = backup(src, "user_edited")
    assert first.name == "paper_user_edited1.docx"
    assert second.name == "paper_user_edited2.docx"
    assert next_backup_path(src, "user_edited").name == "paper_user_edited3.docx"


def test_is_locked_false_for_closed_file(simple_docx):
    assert is_locked(simple_docx) is False


def test_is_locked_false_for_missing_file(tmp_path):
    assert is_locked(tmp_path / "nope.docx") is False
