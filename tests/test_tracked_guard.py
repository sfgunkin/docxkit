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


def test_carry_gives_the_copy_the_stamp_its_bytes_deserve(built, tmp_path):
    """`promote` copies the batch onto the manuscript byte for byte; the
    stamp beside the batch describes the manuscript just as well from
    then on, repairs included. Verbatim, and the source keeps its own —
    `verdict` still asks `base_of(batch)` after the promote."""
    from docxkit.guard import carry, restamp

    restamp(built, why="the repair the stamp must carry")
    copy = tmp_path / "manuscript.docx"
    copy.write_bytes(built.read_bytes())

    stamp = carry(built, copy)

    assert stamp == _stamp_path(copy) and stamp is not None
    assert stamp.read_bytes() == _stamp_path(built).read_bytes()
    assert _stamp_path(built).exists()
    assert guard_deliverable(copy) is None
    assert not list(tmp_path.glob("*user_edited*"))


def test_carry_refuses_a_stamp_that_does_not_describe_the_target(
        built, tmp_path):
    """A stamp is a claim about a hash. Carried onto other bytes it
    would make the guard certify a file nobody built — and it would do
    so from then on, every time `check` was asked."""
    from docxkit.guard import carry

    other = write(tmp_path / "other.docx",
                  make_parts(para(run("not the batch"))))

    with pytest.raises(DeliverableModified, match="does not describe"):
        carry(built, other)

    assert not _stamp_path(other).exists()


@pytest.mark.parametrize("stamp_text,edited,answer", [
    pytest.param(None, False, None, id="no_stamp"),
    pytest.param("{not json", False, None, id="unparseable"),
    pytest.param('["sha256"]', False, None, id="not_an_object"),
    pytest.param('{"original": "prev.docx"}', False, None, id="no_hash"),
    pytest.param("OWN", False, True, id="its_own_bytes"),
    pytest.param("OWN", True, False, id="changed_since"),
])
def test_describes_says_whether_a_stamp_is_about_THESE_bytes(
        tmp_path, stamp_text, edited, answer):
    """`promote` refuses on False BEFORE it writes, so the three kinds of
    "nothing to ask" must not read as False — an unstamped batch is the
    hand-authored vehicle and promotes — and a hash that matches must not
    read as None, or a changed file would pass beside it. `is`, because
    a truthy non-bool from `==` is a different contract."""
    from docxkit.guard import describes, stamp

    out = write(tmp_path / "batch.docx", make_parts(para(run("as built"))))
    if stamp_text == "OWN":
        stamp(out, base_sha256="0" * 64)
    elif stamp_text is not None:
        _stamp_path(out).write_text(stamp_text, encoding="utf-8")
    if edited:
        write(out, make_parts(para(run("as a tool left it"))))

    assert describes(out) is answer


def test_carry_from_an_UNSTAMPED_source_removes_the_stale_stamp(tmp_path):
    """The incident's shape (HCW, 2026-09-04): a stamp beside the
    manuscript naming an earlier round's inputs, still there after a
    later promote. With nothing to carry, the stale one has to go —
    `check` reading "no stamp" is the cautious answer; a stale hash is
    another file's provenance presented as this one's."""
    from docxkit.guard import base_of, carry

    live, hand_authored = tmp_path / "manuscript.docx", tmp_path / "v.docx"
    write(live, make_parts(para(run("the last promote"))))
    _write_stamp(live, original="prev.docx", base_sha256="0" * 64)
    write(hand_authored, make_parts(para(run("hand-authored"))))
    live.write_bytes(hand_authored.read_bytes())

    assert carry(hand_authored, live) is None

    assert not _stamp_path(live).exists()
    assert base_of(live) is None


@pytest.mark.parametrize("stamp_text", ['{"sha256": "a", "base_sha',
                                        '{"original": "prev.docx"}',
                                        '["not", "a", "stamp"]'])
def test_carry_treats_a_stamp_that_certifies_nothing_as_none(
        built, tmp_path, stamp_text):
    """Unparseable, no hash, not an object: none of these can say what
    file they describe, so each is the unstamped case — nothing carried,
    the stale stamp beside the target removed, and no refusal, because
    a refusal here would stop a promote over a side-file."""
    from docxkit.guard import carry

    _stamp_path(built).write_text(stamp_text, encoding="utf-8")
    copy = tmp_path / "manuscript.docx"
    copy.write_bytes(built.read_bytes())
    _write_stamp(copy, original="prev.docx", base_sha256="0" * 64)

    assert carry(built, copy) is None
    assert not _stamp_path(copy).exists()


@pytest.mark.parametrize("stamp_text", [
    pytest.param(None, id="no_stamp"),
    pytest.param('{"sha256": "a", "base_sha', id="unparseable"),
    pytest.param('["not", "a", "stamp"]', id="not_an_object"),
    pytest.param('{"original": "prev.docx"}', id="no_hash"),
])
def test_carry_with_nothing_to_carry_onto_a_target_with_NO_stamp_either(
        tmp_path, stamp_text):
    """The first promote of a hand-authored batch: the batch has no
    stamp that certifies anything, and neither does the manuscript. For
    the three `target.unlink(missing_ok=True)` in `carry`, each read as
    `missing_ok=False` — every earlier carry test put a stale stamp
    beside the target, so the removal always found a file. Here there is
    none, and the mutant raises FileNotFoundError after `promote` has
    already replaced the manuscript. One case per early return."""
    from docxkit.guard import carry

    batch, live = tmp_path / "v.docx", tmp_path / "manuscript.docx"
    write(batch, make_parts(para(run("hand-authored"))))
    live.write_bytes(batch.read_bytes())
    if stamp_text is not None:
        _stamp_path(batch).write_text(stamp_text, encoding="utf-8")

    assert carry(batch, live) is None

    assert not _stamp_path(live).exists()


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
