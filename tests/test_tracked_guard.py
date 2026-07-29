"""The guard that stops a rebuild discarding someone's review.

The failure it exists for: the tracked deliverable is derived, so the
build rewrites it — but it is also the file the author opens in Word to
review, accepting some revisions and leaving others pending. Rebuilding
over that destroys the review silently.
"""
from __future__ import annotations

import json

import pytest
from conftest import make_parts, para, run, write

from docxkit.errors import DeliverableModified
from docxkit.guard import check as guard_deliverable
from docxkit.guard import stamp as _write_stamp
from docxkit.guard import stamp_path as _stamp_path
from docxkit.package import read_parts


@pytest.fixture
def built(tmp_path):
    """A deliverable as the build left it: file plus its stamp."""
    out = tmp_path / "v12_tracked.docx"
    write(out, make_parts(para(run("as built"))))
    original = tmp_path / "v11.docx"
    revised = tmp_path / "v12_clean.docx"
    write(original, make_parts(para(run("before"))))
    write(revised, make_parts(para(run("after"))))
    _write_stamp(out, original=original.name, revised=revised.name)
    return out


def test_untouched_deliverable_rebuilds_without_complaint(built):
    assert guard_deliverable(built) is None
    assert not list(built.parent.glob("*user_edited*"))


def test_edited_deliverable_stops_the_build(built):
    write(built, make_parts(para(run("author accepted the revisions"))))
    with pytest.raises(DeliverableModified, match="edited it in Word"):
        guard_deliverable(built)


def test_the_edited_file_is_backed_up_before_refusing(built):
    write(built, make_parts(para(run("author's review"))))
    with pytest.raises(DeliverableModified):
        guard_deliverable(built)
    backups = list(built.parent.glob("*user_edited*"))
    assert len(backups) == 1
    saved_text = read_parts(backups[0])["word/document.xml"]
    assert b"author's review" in saved_text


def test_force_backs_up_and_proceeds(built):
    write(built, make_parts(para(run("author's review"))))
    saved = guard_deliverable(built, force=True)
    assert saved is not None and saved.exists()
    assert b"author's review" in read_parts(saved)["word/document.xml"]


def test_a_deliverable_with_no_stamp_is_backed_up_not_trusted(tmp_path):
    """Files built before stamping existed cannot be verified, so the
    cautious reading is that they may hold edits."""
    out = tmp_path / "legacy.docx"
    write(out, make_parts(para(run("built before stamps"))))
    with pytest.raises(DeliverableModified):
        guard_deliverable(out)
    assert list(tmp_path.glob("*user_edited*"))


def test_missing_output_is_a_clean_first_build(tmp_path):
    assert guard_deliverable(tmp_path / "not_yet.docx") is None


def test_a_corrupt_stamp_is_treated_as_unverifiable(built):
    _stamp_path(built).write_text("{not json", encoding="utf-8")
    with pytest.raises(DeliverableModified):
        guard_deliverable(built)


def test_stamp_records_what_it_was_built_from(built):
    data = json.loads(_stamp_path(built).read_text(encoding="utf-8"))
    assert data["original"] == "v11.docx"
    assert data["revised"] == "v12_clean.docx"
    assert len(data["sha256"]) == 64
