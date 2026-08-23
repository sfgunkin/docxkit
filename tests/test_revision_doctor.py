"""`revision doctor` — who else in the repo thinks they know the paper.

The S3 this closes was seen three times before it was written down, and
each time by someone who happened to look. A migration renames the
manuscript to `working.docx` and the migrator greps for the old name —
which finds every reference that SPELLS it and none of the ones that
matter. Those select the paper by pattern, and a pattern that stops
matching does not fail: it falls back to whatever else is on disk,
which is an older generation of the same paper sitting right there.

On AFI that was `Report/afi_v11.docx`, three generations stale, chosen
by a glob for the highest `afi_vN.docx`. Eleven tests failed with
messages about caption counts and table cells; not one named the
rename. And red was luck — the two generations happened to disagree on
those counts.
"""
from __future__ import annotations

import pytest

from docxkit.revision import doctor, init


@pytest.fixture
def paper(tmp_path):
    """A migrated project: the manuscript is `Report/afi_v14.docx`.

    Adopted in place, which is what `init` does now: the paper keeps
    its own name and its own folder, and `paper.toml` records them.
    That is also the shape this survey was written for — the doubts
    below name OTHER generations of the same paper, beside it.
    """
    source = tmp_path / "Report" / "afi_v14.docx"
    source.parent.mkdir(parents=True)
    from conftest import make_parts, para, run, write
    write(source, make_parts(para(run("The paper."))))
    return init(tmp_path, source)


def _write(paper, rel: str, text: str) -> None:
    path = paper.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_clean_project_reports_nothing(paper):
    _write(paper, "scripts/build.py",
           'PAPER = "Report/afi_v14.docx"\n')

    assert doctor(paper) == []


def test_a_stale_LITERAL_is_reported_with_its_line(paper):
    """The Parental_style and API/HPPA shape: a script pinned to the
    name the paper used to have."""
    _write(paper, "scripts/build.py",
           "import docxkit\n\nOLD = 'Report/afi_v11.docx'\n")

    found = doctor(paper)

    assert len(found) == 1, found
    assert found[0].path.as_posix() == "scripts/build.py"
    assert found[0].line == 3
    assert found[0].text == "Report/afi_v11.docx"
    assert found[0].kind == "literal"


def test_a_GLOB_that_misses_the_manuscript_is_reported(paper):
    """The AFI shape, and the one no grep for the filename can find:
    the reference never spells it."""
    _write(paper, "tests/helpers.py",
           'CANDIDATES = sorted(root.glob("archive/afi_v*.docx"))\n')

    found = doctor(paper)

    assert [d.kind for d in found] == ["pattern"], found
    assert found[0].text == "archive/afi_v*.docx"


def test_a_glob_that_DOES_select_the_manuscript_is_left_alone(paper):
    """A resolver written against the declared layout is the fix, not
    the finding — reporting it would train the reader to ignore this."""
    _write(paper, "tests/helpers.py",
           'PAPER = next(root.glob("Report/*.docx"))\n')

    assert doctor(paper) == []


def test_the_BUILD_directory_is_not_surveyed(paper):
    """`build/` holds this protocol's own artefacts — prev.docx, the
    batch, the rescues — and naming them is what it is for."""
    _write(paper, "revision/build/notes.py", 'OLD = "afi_v11.docx"\n')

    assert doctor(paper) == []


def test_a_bare_filename_matching_the_manuscript_is_not_a_doubt(paper):
    _write(paper, "scripts/open.py", 'NAME = "afi_v14.docx"\n')

    assert doctor(paper) == []


def test_several_doubts_come_back_in_PATH_order(paper):
    _write(paper, "a_first.py", 'X = "old_a.docx"\n')
    _write(paper, "z_last.py", 'Y = "old_z.docx"\n')

    found = doctor(paper)

    assert [d.path.as_posix() for d in found] == ["a_first.py", "z_last.py"]


def test_a_doubt_prints_as_a_line_a_human_can_act_on(paper):
    _write(paper, "scripts/build.py", 'OLD = "Report/afi_v11.docx"\n')

    line = str(doctor(paper)[0])

    assert "scripts/build.py:1" in line
    assert "afi_v11.docx" in line
    assert "literal" in line


def test_PATTERNS_come_before_literals(paper):
    """The output is ranked because the first version was not. AFI
    answered with 134 lines, three of them patterns, and they were
    buried among 131 literals — an unreadable gate is one people stop
    running, which is the whole reason this is an S3 and not an S4.
    """
    _write(paper, "z_pattern.py",
           'P = root.glob("archive/afi_v*.docx")\n')
    _write(paper, "a_literal.py", 'P = "Report/afi_v11.docx"\n')

    found = doctor(paper)

    assert [d.kind for d in found] == ["pattern", "literal"], found


def test_a_SPENT_directory_can_be_declared_and_is_skipped(paper):
    """`[doctor] skip`. A paper accumulates one-off builders — the phase
    scripts of a restructure, a shipped replication package with its own
    frozen copy of the manuscript — and under the forward-only rule
    those name an old generation correctly.
    """
    _write(paper, "v8_restructure/phase1.py", 'P = "Report/afi_v8.docx"\n')
    assert len(doctor(paper)) == 1, "the fixture should be found by default"

    config = paper.config.read_text(encoding="utf-8")
    paper.config.write_text(
        config + '\n[doctor]\nskip = ["v8_restructure"]\n', encoding="utf-8")

    from docxkit.revision import load_paper
    assert doctor(load_paper(paper.root)) == []


def test_scripts_applied_is_skipped_by_DEFAULT(paper):
    """"applied" is already the protocol's word for a batch that has been
    used, so a paper that follows the layout needs no configuration."""
    _write(paper, "scripts/applied/r1_captions.py",
           'P = "Report/afi_v11.docx"\n')

    assert doctor(paper) == []


# --- which names count as the declared manuscript (2026-08-19) ---------
#
# `_selects_declared` decides what `doctor` stays quiet about, and six
# of revision.py's fifty survivors were in it. Everything it is asked
# about here is either the bare name of the manuscript or a name from
# another paper entirely — and between those two lies the case the
# function was written for: a path that ENDS in the right file name and
# points somewhere else.


def test_a_path_whose_DIRECTORY_is_wrong_is_still_a_doubt(paper):
    """`len(candidate.parts) == 1` — a BARE name is the tail of every
    path and matches by definition; a two-part path has to match as a
    path. Under `> 1` or `>= 1` the length test carries the decision on
    its own and any file called `working.docx`, in any directory, reads
    as the declared manuscript. A script pointing at a copy under
    `backup/` is the whole reason this survey exists."""
    _write(paper, "scripts/build.py", 'PAPER = "backup/afi_v14.docx"\n')

    (doubt,) = doctor(paper)

    assert doubt.text == "backup/afi_v14.docx"


def test_a_LONGER_path_ending_in_the_right_two_parts_is_not_a_doubt(paper):
    """`candidate.parts[-2:]`: a script that spells the project out from
    somewhere else ("proj/Report/afi_v14.docx") is naming the declared
    manuscript, and the last two components are what say so."""
    _write(paper, "scripts/build.py",
           'PAPER = "some_project/Report/afi_v14.docx"\n')

    assert doctor(paper) == []


def test_naming_the_BASELINE_is_not_a_doubt(paper):
    """`continue`, not `break`: the loop looks at working.docx and then
    at prev.docx, and a script naming the baseline is doing the right
    thing — every reject-all check reads it. Under `break` the pair
    stops at its first member and every mention of prev.docx is
    reported, which trains a reader to skim this list."""
    _write(paper, "scripts/check.py", 'BASE = "prev.docx"\n')

    assert doctor(paper) == []


def test_the_ATTIC_is_not_surveyed(tmp_path):
    """It legitimately holds older manuscripts — that is what an attic
    is. Reporting the retired names stored there is reporting the
    project for being tidy.

    Its own project, because the fixture's attic defaults to a path
    outside the root (the paper attic on another drive), where the
    survey would never look whatever this skip did.
    """
    from conftest import make_parts, para, run, write
    source = tmp_path / "proj" / "Report" / "afi_v14.docx"
    source.parent.mkdir(parents=True)
    write(source, make_parts(para(run("The paper."))))
    paper = init(tmp_path / "proj", source, attic=tmp_path / "proj" / "attic")
    stale = 'PAPER = "afi_v11.docx"\n'
    (paper.root / "attic").mkdir(parents=True, exist_ok=True)
    (paper.root / "attic" / "old_build.py").write_text(stale,
                                                       encoding="utf-8")

    assert doctor(paper) == []

    # and the same file OUTSIDE the attic is reported, so the test above
    # is the skip talking and not the survey missing the file
    (paper.root / "live_build.py").write_text(stale, encoding="utf-8")
    assert [d.text for d in doctor(paper)] == ["afi_v11.docx"]


def test_a_file_in_a_SKIPPED_directory_does_not_end_the_walk(paper):
    """`continue`, on the `.git`/`__pycache__` skip. The walk is over
    `sorted(rglob("*"))`, so a hook or a cached module sorts near the
    top of a repository — and `break` there returns an empty report for
    a project with doubts in it, which reads exactly like a clean one.

    The gate this belongs to exists because a stale reference does not
    fail: it picks up an older generation of the same paper. A gate
    that answers "nothing" is worse than no gate."""
    line = 'P = "Report/afi_v11.docx"'
    _write(paper, ".git/hooks/pre-commit.py", line)
    _write(paper, "scripts/build.py", line)

    found = doctor(paper)

    assert [d.path.as_posix() for d in found] == ["scripts/build.py"]
