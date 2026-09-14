r"""A promote must not destroy its own undo.

Measured twice on Aging_Well — 2026-08-31 23:57 and 2026-09-01 21:01.
`revision promote` reported

    rescue copy of the previous live file:
      …\rescue\working_rescue_20260831-235728-542622.docx
    pruned 3 older rescue(s), keeping 5

and the file named in the first line was gone afterwards. The undo for
that promote had to come from a copy another session happened to leave.

Two causes, and the count printed was right both times, which is why
nothing looked wrong.

`rescues()` globbed `*_rescue_*` and sorted the NAMES. Uniform-width
stamps sort chronologically among themselves — but the glob also
catches the hand-named copies a session writes, and `-` (0x2D) sorts
before `_` (0x5F):

    working_rescue_20260831-235728-542622.docx   23:57, the newest
    working_rescue_20260831_pre_COMP.docx        18:44
    working_rescue_20260831_pre_REF2.docx        21:51

so the newest read as the oldest and went into the doomed slice. And
nothing said "never delete the copy this promote just made", which is
the invariant that holds whatever else is in the folder.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from conftest import make_parts, para, run, write

from docxkit import revision
from docxkit.revision import _promote

STAMPED = "working_rescue_20260831-235728-542622.docx"
BY_HAND = ("working_rescue_20260831_pre_COMP.docx",
           "working_rescue_20260831_pre_REF2.docx",
           "working_rescue_20260901_pre_POL.docx")


def _paper(tmp_path):
    (tmp_path / "proj").mkdir()
    src = write(tmp_path / "proj" / "working.docx",
                make_parts(para(run("The index rose."))))
    return revision.init(tmp_path / "proj", src, name="Test Paper",
                         author="Agent", attic=tmp_path / "attic")


def _fill(paper, *names: str) -> list[Path]:
    paper.rescue_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for name in names:
        path = paper.rescue_dir / name
        write(path, make_parts(para(run(name))))
        made.append(path)
    return made


# ------------------------------------------------------------ the order


def test_a_stamped_rescue_is_not_sorted_by_its_NAME(tmp_path):
    """The whole defect in one assertion. `rescues` answers OLDEST
    FIRST, the stamped copy here is the newest of the four, and sorting
    the strings put it first — because `-` is 0x2D and `_` is 0x5F. It
    was then the head of `prune_rescues`' doomed slice."""
    paper = _paper(tmp_path)
    made = _fill(paper, *BY_HAND)
    # the hand-named copies are older than the stamped one, which is
    # what their names say and what mtime has to agree with
    old = datetime(2026, 8, 31, 18, 44).timestamp()
    for i, path in enumerate(made):
        os.utime(path, (old + i, old + i))
    _fill(paper, STAMPED)               # stamped 23:57, the newest

    order = [p.name for p in _promote.rescues(paper)]

    assert order[-1] == STAMPED, (
        "the newest copy sorted as the oldest, which is where pruning "
        f"looks for what to delete: {order}")


def test_stamped_copies_sort_chronologically_among_themselves(tmp_path):
    paper = _paper(tmp_path)
    _fill(paper,
          "working_rescue_20260901-210134-674000.docx",
          "working_rescue_20260831-235728-542622.docx",
          "working_rescue_20260901-090000-000000.docx")

    order = [p.name for p in _promote.rescues(paper)]

    assert order == ["working_rescue_20260831-235728-542622.docx",
                     "working_rescue_20260901-090000-000000.docx",
                     "working_rescue_20260901-210134-674000.docx"]


# ----------------------------------------------------------- the pruning


def test_a_hand_named_rescue_is_never_deleted(tmp_path):
    """A file the tool did not write is not the tool's to remove. The
    papers worked around this by prefixing `working_keep_`, which the
    glob does not match — a rename to dodge a deletion."""
    paper = _paper(tmp_path)
    _fill(paper, *BY_HAND, STAMPED)

    gone = revision.prune_rescues(paper, keep=0)

    assert [p.name for p in gone] == [STAMPED]
    for name in BY_HAND:
        assert (paper.rescue_dir / name).is_file(), name


def test_the_protected_copy_survives_even_at_keep_zero(tmp_path):
    """`promote` passes the rescue it has just written. Nothing else in
    the folder can change that answer."""
    paper = _paper(tmp_path)
    (stamped,) = _fill(paper, STAMPED)

    gone = revision.prune_rescues(paper, keep=0, protect=stamped)

    assert gone == [] and stamped.is_file()


def test_the_hand_named_copies_still_COUNT_toward_keep(tmp_path):
    """Five undos in the folder is five undos, whoever wrote them.
    Thinning the stamped ones to make room would be this function
    deciding which of the author's copies matter."""
    paper = _paper(tmp_path)
    _fill(paper, *BY_HAND,
          "working_rescue_20260901-090000-000000.docx",
          "working_rescue_20260901-210134-674000.docx")

    gone = revision.prune_rescues(paper, keep=5)

    assert gone == [], "five copies, keeping five"


# ------------------------------- the sweep's survivors (2026-09-14)


def test_a_taken_rescue_name_moves_ONE_microsecond_and_gives_up_after_1000(
        tmp_path):
    """The next free stamp is the smallest step away, and a thousand taken
    in a row is a refusal rather than a walk that never ends — with 999
    taken, the thousandth is still found."""
    from datetime import timedelta

    import pytest

    from docxkit.errors import ProtocolError

    paper = _paper(tmp_path)
    paper.rescue_dir.mkdir(parents=True, exist_ok=True)
    moment = datetime(2026, 9, 14, 12, 0, 0)

    def name(us: int) -> Path:
        stamp = (moment + timedelta(microseconds=us)).strftime(
            _promote._RESCUE_STAMP)
        return Path(paper.rescue_dir, f"working_rescue_{stamp}.docx")

    name(0).touch()
    assert _promote.rescue_path(paper, moment) == name(1)

    for us in range(1, 999):
        name(us).touch()
    assert _promote.rescue_path(paper, moment) == name(999)

    name(999).touch()
    with pytest.raises(ProtocolError, match="no free rescue name"):
        _promote.rescue_path(paper, moment)


def test_a_batch_stamped_on_a_HIGHER_hash_is_refused_quoting_both(tmp_path):
    """`!=`, not `<`: a stamp that sorts above the baseline's hash is as
    stale as one below it. The refusal quotes sixteen characters of each,
    the width a reader matches against the ledger."""
    import shutil

    import pytest

    from docxkit import guard
    from docxkit.errors import StaleBatch

    paper = _paper(tmp_path)
    write(paper.batch, make_parts(para(run("The index rose to 0.37."))))
    shutil.copyfile(paper.working, paper.prev)
    guard.stamp(paper.batch, base_sha256="f" * 64)
    base = guard.sha256(paper.prev)

    with pytest.raises(StaleBatch) as refused:
        revision.promote(paper)

    assert (f"built on {'f' * 16} and this baseline is {base[:16]}. It is"
            in str(refused.value))


def test_a_promote_makes_its_rescue_folder_under_a_build_dir_NOT_MADE(
        tmp_path):
    """The rescue folder hangs off `build_dir`, and with the batch and the
    baseline handed in from elsewhere nothing else has made that folder."""
    import dataclasses
    import shutil

    paper = _paper(tmp_path)
    write(paper.batch, make_parts(para(run("The index rose to 0.37."))))
    shutil.copyfile(paper.working, paper.prev)
    moved = dataclasses.replace(paper,
                                build_dir=tmp_path / "elsewhere" / "build")

    revision.promote(moved, paper.batch, paper.prev)

    assert list((tmp_path / "elsewhere" / "build" / "rescue").glob("*.docx"))


# --------------------------------------------------- the promote itself


def test_a_promote_never_deletes_the_rescue_it_just_wrote(tmp_path):
    """The measurement, end to end. A folder already holding five
    hand-named copies is the state Aging_Well was in, and the promote
    pruned its own undo out of it."""
    paper = _paper(tmp_path)
    _fill(paper, *BY_HAND,
          "working_rescue_20260901_post_POL_accept.docx",
          "working_rescue_20260901_pre_R77.docx")
    write(paper.batch, make_parts(para(run("The index rose to 0.37."))))
    import shutil
    shutil.copyfile(paper.working, paper.prev)

    report = revision.promote(paper)

    assert report.rescue.is_file(), (
        "the promote deleted the copy it had just made — the undo for "
        "the change it was in the middle of")
    assert report.rescue not in report.pruned
