"""`tools/backlog_status.py` — is each entry in the section that
describes it?

Nothing checked this, and it failed in BOTH directions inside one week.
`--sample` and the `Table` handle sat under `## Fixed` while still open,
three days each, and were found by reading rather than by any tool. On
2026-08-24 the reverse: a close-helper that cut an entry "to the next
`### `" took the `## Fixed` heading with it, so every closed entry sat
inside `## Open` for three commits — struck through, in order, and
looking entirely right. What caught THAT was a count of open sections
coming back 187 when six were open.

The obvious gate was built first and thrown away, which is the finding
this holds. A resolution-detector over all 209 entries scored 93
findings, 2 of them real: every false positive came from a convention the
file grew rather than declared. So the status is DECLARED, and what is
tested here is that the declaration is enforced and that the enforcement
is narrow enough not to fire on the file's own records.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is how its scripts are reached, here and by each other.
import backlog_status as bs  # noqa: E402  # pyright: ignore[reportMissingImports]

ROOT = Path(docxkit.__file__).resolve().parents[2]


def doc(*entries: str) -> str:
    """A miniature BACKLOG with the two sections in file order."""
    return "\n".join(entries)


OPEN = "## Open\n"
FIXED = "## Fixed\n"

#: The two halves, since 2026-08-30. Sections are file-scoped now:
#: `## Open` lives in one, `## Fixed` in the other, and `problems` is
#: told which file it is reading.
WORKING = "BACKLOG.md"
ARCHIVE = "BACKLOG-ARCHIVE.md"


def entry(head: str, status: str | None) -> str:
    mark = f"\n<!-- status: {status} -->" if status else ""
    return f"\n### {head}{mark}\n\nSome prose.\n"


# --- the two failures that really happened -------------------------------


def test_an_OPEN_entry_under_Fixed_is_refused():
    """`--sample` and the `Table` handle, three days each. `## Fixed`
    exists to answer "did we ever fix that?", and an open entry sitting
    there answers it wrongly — worse than not answering."""
    text = doc(FIXED, entry("A `--sample` run OVERWRITES a complete one",
                            "open"))

    (found,) = bs.problems(text, ARCHIVE)

    assert "'open' under `## Fixed`" in found
    assert "--sample" in found, "the reader has to see WHICH entry"


def test_a_FIXED_entry_under_Open_is_refused():
    """The 2026-08-24 direction, and the more expensive one: the batch
    order is set by severity within `## Open`, so a closed entry left
    there sets the wrong order. That is how 2026-08-27 began — the
    top-severity entry was one already fixed."""
    text = doc(OPEN, entry("Already done", "fixed"))

    (found,) = bs.problems(text, WORKING)

    assert "'fixed' under `## Open`" in found


def test_the_ordinary_file_is_SILENT():
    """The half that decides whether a gate survives its first week."""
    assert bs.problems(doc(OPEN, entry("A live one", "open")),
                       WORKING) == []
    assert bs.problems(doc(FIXED, entry("A closed one", "fixed")),
                       ARCHIVE) == []


# --- the split, and the one failure it can introduce ---------------------


def test_a_FIXED_section_in_the_WORKING_file_is_refused():
    """The only new way to be wrong after 2026-08-30.

    Status and section AGREE here — a `fixed` entry under `## Fixed` —
    and the entry is still in the wrong file. Nothing in the original
    check could see that, because it was written when there was one
    file; the archive would then answer "did we ever fix that?" over a
    subset, which is the exact reading `## Fixed` exists to prevent.
    """
    text = doc(OPEN, entry("A live one", "open"),
               FIXED, entry("Closed, and left behind", "fixed"))

    (found,) = bs.problems(text, WORKING)

    assert "`## Fixed` in BACKLOG.md" in found
    assert "BACKLOG-ARCHIVE.md" in found
    assert "left behind" in found


def test_an_OPEN_section_in_the_ARCHIVE_is_refused():
    """The other direction. An open entry filed into the archive is off
    the working list entirely — not misordered, invisible."""
    text = doc(OPEN, entry("Filed into the wrong file", "open"))

    (found,) = bs.problems(text, ARCHIVE)

    assert "`## Open` in BACKLOG-ARCHIVE.md" in found
    assert "BACKLOG.md" in found


def test_the_FILE_rule_is_checked_BEFORE_the_status_rule():
    """One finding per entry, and it must be the actionable one. An
    entry in the wrong file also has the wrong section for its status,
    so reporting both says "move it to `## Fixed`" beside "move it to
    the other file" — and the first is advice that makes it worse."""
    text = doc(FIXED, entry("Closed, left behind", "fixed"))

    found = bs.problems(text, WORKING)

    assert len(found) == 1
    assert "`## Fixed` in BACKLOG.md" in found[0]


# --- narrow on purpose ---------------------------------------------------


def test_a_RECORD_may_sit_in_either_section():
    """`withdrawn`, `not-a-defect` and `note` are records rather than
    defects, and some are kept in `## Open` deliberately — a retraction,
    and a Word behaviour worth not chasing twice. Refusing those would be
    a gate firing on the file's own conventions, which is exactly what
    the regex did."""
    working = doc(OPEN,
                  entry("A retraction kept on purpose", "withdrawn"),
                  entry("Not a defect, recorded so it is not chased twice",
                        "not-a-defect"),
                  entry("A framing note", "note"))
    archive = doc(FIXED,
                  entry("Withdrawn the day it was filed", "withdrawn"),
                  entry("Checked and NOT defects", "not-a-defect"))

    assert bs.problems(working, WORKING) == []
    assert bs.problems(archive, ARCHIVE) == []


def test_an_entry_with_NO_status_is_a_finding():
    """What keeps this from decaying. A new entry written without a
    marker fails rather than being assumed to be whatever its section
    is — otherwise the field stops being declared the first time
    somebody forgets."""
    text = doc(OPEN, entry("Written in a hurry", None), FIXED)

    (found,) = bs.problems(text)

    assert found.startswith("no status declared")


def test_a_status_outside_the_VOCABULARY_is_a_finding():
    """A typo has to fail loudly. `fixd` silently unknown would pass the
    section check by not being `open` or `fixed`, which is the quiet way
    a declared field becomes decorative."""
    text = doc(OPEN, entry("A typo", "fixd"), FIXED)

    (found,) = bs.problems(text)

    assert "unknown status 'fixd'" in found


def test_the_marker_must_FOLLOW_ITS_OWN_heading():
    """An entry moved without its marker would otherwise inherit
    whatever the next one declares — and moving entries between sections
    is the operation this whole gate is about."""
    text = OPEN + "\n### Orphaned\n\nProse first.\n<!-- status: open -->\n"

    (found,) = bs.problems(text)

    assert found.startswith("no status declared")


# --- the live file -------------------------------------------------------


def _live(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_THIS_backlog_is_consistent():
    """The gate itself, over the files it exists for — BOTH of them."""
    for path in bs.FILES:
        assert bs.problems(_live(path), path.name) == [], path.name


def test_EVERY_entry_declares_a_status():
    """Stated separately from the check above so the failure says which
    of the two things went wrong: an unstamped entry and a misfiled one
    are different mistakes with different fixes."""
    for path in bs.FILES:
        found = bs.entries(_live(path))

        assert found, f"{path.name} has entries"
        assert [h for _s, status, h in found if status is None] == []


def test_BOTH_halves_of_the_backlog_exist():
    """The split's own invariant. A checker reading a file that is not
    there answers "nothing to check" — which is how a gate dies — so the
    tool refuses, and this pins that the pair is really the shape on
    disk rather than only the shape the tool wants."""
    assert [path.name for path in bs.FILES] == ["BACKLOG.md",
                                                "BACKLOG-ARCHIVE.md"]
    for path in bs.FILES:
        assert path.is_file(), f"{path.name} is missing"


#: What the two files held the moment the archive was split out of
#: BACKLOG.md, 2026-08-30. A FLOOR, not a target — see below.
AT_THE_SPLIT = 224


def test_NO_ENTRY_was_lost_when_the_archive_was_split_out():
    """The split moved 9,852 lines between two files. The way that goes
    wrong is not a crash: it is a boundary off by one section, which
    reads as a tidy file and a checker that never sees the entries it
    dropped. The total is the only thing that notices.

    `>=`, and the first spelling of this was `== 224` — which went red
    within the hour, on somebody filing an ordinary entry. A gate that
    fires on the normal use of the thing it guards is a gate that gets
    deleted, and it would have been deleted for being wrong. What is
    actually invariant is the archive's own rule: nothing is ever
    removed, so the total can only grow.
    """
    total = sum(len(bs.entries(_live(path))) for path in bs.FILES)

    assert total >= AT_THE_SPLIT, (
        f"{AT_THE_SPLIT - total} entries fewer than the split produced. "
        f"Entries are never deleted — check the `## Fixed` boundary.")


def test_FIXED_is_a_heading_in_the_ARCHIVE_ONLY():
    """What makes the split gated rather than merely tidy.

    A closed entry left in BACKLOG.md needs a `## Fixed` to sit under.
    If BACKLOG.md still had one, that entry would be legal — right
    status, right section, wrong file — so the working file's pointer
    paragraph is deliberately headed something else.
    """
    working, archive = (_live(path) for path in bs.FILES)

    assert "\n## Fixed\n" in archive
    assert "\n## Fixed\n" not in working
    assert "\n## Open\n" in working
    assert "\n## Open\n" not in archive


def test_the_tool_runs_and_reports_its_own_verdict():
    out = subprocess.run([sys.executable, str(TOOLS / "backlog_status.py")],
                         capture_output=True, text=True, encoding="utf-8",
                         cwd=ROOT, check=False)

    assert out.returncode == 0, out.stdout + out.stderr
    assert "entries" in out.stdout
