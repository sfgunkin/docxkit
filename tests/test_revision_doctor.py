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
    """A migrated project: the manuscript is `revision/working.docx`."""
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
           'PAPER = "revision/working.docx"\n')

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
           'CANDIDATES = sorted(root.glob("Report/afi_v*.docx"))\n')

    found = doctor(paper)

    assert [d.kind for d in found] == ["pattern"], found
    assert found[0].text == "Report/afi_v*.docx"


def test_a_glob_that_DOES_select_the_manuscript_is_left_alone(paper):
    """A resolver written against the declared layout is the fix, not
    the finding — reporting it would train the reader to ignore this."""
    _write(paper, "tests/helpers.py",
           'PAPER = next(root.glob("revision/*.docx"))\n')

    assert doctor(paper) == []


def test_the_BUILD_directory_is_not_surveyed(paper):
    """`build/` holds this protocol's own artefacts — prev.docx, the
    batch, the rescues — and naming them is what it is for."""
    _write(paper, "revision/build/notes.py", 'OLD = "afi_v11.docx"\n')

    assert doctor(paper) == []


def test_a_bare_filename_matching_the_manuscript_is_not_a_doubt(paper):
    _write(paper, "scripts/open.py", 'NAME = "working.docx"\n')

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
