"""Scaffolding the paper value-test suites share."""
from __future__ import annotations

import pytest
from conftest import make_parts, para, run, write

from docxkit.errors import PackageError
from docxkit.testing import (
    latest_version,
    load_xml,
    load_zip,
    prose_numbers,
    read_bytes,
)


@pytest.fixture
def report_dir(tmp_path):
    for name in ("afi_v2.docx", "afi_v9.docx", "afi_v10.docx",
                 "afi_v10_pre_fig8_backup.docx", "afi_v9_user_edited1.docx",
                 "li7_v3.docx"):
        write(tmp_path / name, make_parts(para(run(name))))
    return tmp_path


def test_latest_version_sorts_numerically_not_lexically(report_dir):
    """v10 beats v9 -- string sorting would pick v9 and quietly test a
    superseded paper."""
    assert latest_version(report_dir, "afi").name == "afi_v10.docx"


def test_latest_version_ignores_backups_and_snapshots(report_dir):
    """A backup must never be mistaken for the live version."""
    picked = latest_version(report_dir, "afi").name
    assert "backup" not in picked and "user_edited" not in picked


def test_latest_version_can_select_by_stem(report_dir):
    assert latest_version(report_dir, "li7").name == "li7_v3.docx"


def test_latest_version_without_a_stem_takes_the_highest(report_dir):
    assert latest_version(report_dir).name == "afi_v10.docx"


def test_latest_version_raises_when_nothing_matches(tmp_path):
    with pytest.raises(PackageError, match=r"no afi_vN\.docx"):
        latest_version(tmp_path, "afi")


def test_read_bytes_returns_the_file(report_dir):
    assert read_bytes(report_dir / "afi_v10.docx")[:2] == b"PK"


def test_missing_paper_skips_rather_than_fails(report_dir):
    """A suite should not go red because the paper is not on disk, or
    because the author happens to have it open in Word."""
    with pytest.raises(pytest.skip.Exception, match="missing"):
        read_bytes(report_dir / "absent.docx")


def test_missing_paper_raises_when_skipping_is_declined(report_dir):
    with pytest.raises(PackageError, match="missing"):
        read_bytes(report_dir / "absent.docx", skip_if_locked=False)


def test_load_xml_and_zip_work_on_an_in_memory_copy(report_dir):
    xml = load_xml(report_dir / "afi_v10.docx")
    assert "afi_v10.docx" in xml
    with load_zip(report_dir / "afi_v10.docx") as z:
        assert "word/document.xml" in z.namelist()


def test_prose_numbers_finds_values_with_context():
    text = ("The ECA average AFI has risen from 0.17 in 2014 to 0.35 in "
            "2024, a gain of 0.18.")
    found = prose_numbers(text, context=12)
    values = [v for v, _ in found]
    assert values == [0.17, 2014.0, 0.35, 2024.0, 0.18]
    assert "risen from" in found[0][1]


def test_prose_numbers_handles_signs_and_percentages():
    found = dict(prose_numbers("fell by −0.147 (about 39%) and +0.056"))
    assert -0.147 in found
    assert 39.0 in found
    assert 0.056 in found
