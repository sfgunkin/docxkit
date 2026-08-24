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
from docxkit.guard import restamp as _restamp
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


# ------------------------------------------- a repair is not a session ---

def test_a_TOOL_repair_re_stamps_and_the_next_build_is_content(built):
    """AFI's rounds end with a repair `build` cannot do — the minus
    glyph Compare downgrades on the rejected side. Running it changed
    `batch.docx` after the build stamped it, so the next build said
    "someone edited it in Word" and wrote a `_user_edited` backup, three
    rounds running, of an edit nobody made.
    """
    built.write_bytes(built.read_bytes() + b" ")     # the repair's write
    _restamp(built, why="restored U+2212 on the rejected side")

    assert guard_deliverable(built) is None
    assert not list(built.parent.glob("*user_edited*"))


def test_the_re_stamp_says_WHAT_changed_the_file_and_from_what(built):
    """The one call that can retire a guard leaves the evidence for
    doing so — and keeps the provenance the build recorded."""
    before = json.loads(_stamp_path(built).read_text(encoding="utf-8"))
    built.write_bytes(built.read_bytes() + b" ")

    _restamp(built, why="restored U+2212 on the rejected side")

    data = json.loads(_stamp_path(built).read_text(encoding="utf-8"))
    assert data["original"] == "v11.docx"          # the build's, kept
    assert data["sha256"] != before["sha256"]
    assert data["repairs"] == [
        {"why": "restored U+2212 on the rejected side",
         "was": before["sha256"], "now": data["sha256"]}]


def test_a_SECOND_repair_is_appended_not_overwritten(built):
    for n in (1, 2):
        built.write_bytes(built.read_bytes() + b" ")
        _restamp(built, why=f"repair {n}")

    data = json.loads(_stamp_path(built).read_text(encoding="utf-8"))
    assert [r["why"] for r in data["repairs"]] == ["repair 1", "repair 2"]
    assert data["repairs"][0]["now"] == data["repairs"][1]["was"]


def test_a_repair_that_changed_NOTHING_records_nothing(built):
    """A repair routine that found nothing to do has not touched the
    deliverable, and a `repairs` entry saying it did would be a lie in
    the one file kept to be read after the fact."""
    _restamp(built, why="found nothing")

    data = json.loads(_stamp_path(built).read_text(encoding="utf-8"))
    assert "repairs" not in data


def test_a_corrupt_stamp_does_not_stop_a_repair_recording_itself(built):
    """`check` already treats an unreadable stamp as unverifiable. The
    repair still has to be able to leave one, or the file is stuck
    refusing every build."""
    _stamp_path(built).write_text("{not json", encoding="utf-8")

    _restamp(built, why="after a corrupt stamp")

    assert guard_deliverable(built) is None


# --- guard's whole survivor list, 2026-08-20: 4.1 % (2/49) -------------
#
# Four now, and all four are `json.dumps(..., indent=1)` — two in
# `stamp` and two in `restamp` — read as 0 and as 2.
# The stamp is written for `check` to read back with `json.loads`, and
# every indent round-trips to the same dict — so the number is a choice
# about reading the file BY EYE, which no test should freeze. One space
# is what a `.buildinfo.json` beside a deliverable wants: enough to see
# the keys down the left, not enough to make the file look like data
# anyone should edit.
#
# Nothing else in the module survives, which makes this one CLOSED.


# --------------------------------------------------------------- base_of
# The staleness gate. Every one of these is a way of saying "cannot
# tell", and each has to answer None rather than guess, because the
# caller's fallback for None is to allow — an unstamped batch is the
# hand-authored vehicle and is legitimate. A wrong string here is worse
# than no answer: it would let `promote` believe a stale redline is
# about the current truth.


def test_base_of_returns_the_baseline_the_batch_was_built_from(built):
    """The happy path, which nothing asserted."""
    from docxkit.guard import base_of, stamp

    stamp(built, original="v11.docx", base_sha256="c0ffee")

    assert base_of(built) == "c0ffee"


def test_base_of_says_CANNOT_TELL_for_a_batch_with_no_stamp(tmp_path):
    from docxkit.guard import base_of

    assert base_of(tmp_path / "never_built.docx") is None


def test_base_of_says_CANNOT_TELL_for_a_stamp_that_PREDATES_the_field(built):
    """`built` stamps the original as a FILE NAME, which is what every
    stamp did before this field existed and is exactly the thing that
    could not answer the question."""
    from docxkit.guard import base_of

    assert json.loads(_stamp_path(built).read_text(encoding="utf-8"))
    assert base_of(built) is None


def test_base_of_says_CANNOT_TELL_for_a_stamp_that_will_not_PARSE(built):
    """A truncated write, or a file someone opened and saved. The
    cautious answer is the same as no stamp — and this path had no test
    and no coverage, so a mutant turning the `except` into a re-raise
    would have turned an unreadable stamp into a crash inside
    `validate`."""
    from docxkit.guard import base_of

    _stamp_path(built).write_text('{"sha256": "a", "base_sha',
                                  encoding="utf-8")

    assert base_of(built) is None


@pytest.mark.parametrize("value", ["", None, 12345, ["c0ffee"]])
def test_base_of_says_CANNOT_TELL_for_a_field_that_is_not_A_HASH(built, value):
    """Empty string, absent, and the two shapes a hand-edited stamp
    produces. `""` is the interesting one: it is falsy but present, so
    an `isinstance` check alone would return it and a caller comparing
    hashes would find no match and call a FRESH batch stale."""
    from docxkit.guard import base_of

    path = _stamp_path(built)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["base_sha256"] = value
    path.write_text(json.dumps(data), encoding="utf-8")

    assert base_of(built) is None


def test_restamp_records_a_repair_on_a_deliverable_with_NO_stamp(tmp_path):
    """The branch where there is nothing to carry forward. `was` is
    empty because there is no previous hash — not omitted, because the
    repairs list is the evidence a guard was retired and a missing key
    reads as a different event from a known-absent one."""
    from docxkit.guard import restamp, sha256

    out = tmp_path / "batch.docx"
    write(out, make_parts(para(run("repaired, never stamped"))))

    path = restamp(out, why="restore_math_glyphs")

    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert recorded["sha256"] == sha256(out)
    assert recorded["repairs"] == [
        {"why": "restore_math_glyphs", "was": "", "now": sha256(out)}]
