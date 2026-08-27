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


def entry(head: str, status: str | None) -> str:
    mark = f"\n<!-- status: {status} -->" if status else ""
    return f"\n### {head}{mark}\n\nSome prose.\n"


# --- the two failures that really happened -------------------------------


def test_an_OPEN_entry_under_Fixed_is_refused():
    """`--sample` and the `Table` handle, three days each. `## Fixed`
    exists to answer "did we ever fix that?", and an open entry sitting
    there answers it wrongly — worse than not answering."""
    text = doc(OPEN, entry("A live one", "open"),
               FIXED, entry("A `--sample` run OVERWRITES a complete one",
                            "open"))

    (found,) = bs.problems(text)

    assert "'open' under `## Fixed`" in found
    assert "--sample" in found, "the reader has to see WHICH entry"


def test_a_FIXED_entry_under_Open_is_refused():
    """The 2026-08-24 direction, and the more expensive one: the batch
    order is set by severity within `## Open`, so a closed entry left
    there sets the wrong order. That is how 2026-08-27 began — the
    top-severity entry was one already fixed."""
    text = doc(OPEN, entry("Already done", "fixed"), FIXED)

    (found,) = bs.problems(text)

    assert "'fixed' under `## Open`" in found


def test_the_ordinary_file_is_SILENT():
    """The half that decides whether a gate survives its first week."""
    text = doc(OPEN, entry("A live one", "open"),
               FIXED, entry("A closed one", "fixed"))

    assert bs.problems(text) == []


# --- narrow on purpose ---------------------------------------------------


def test_a_RECORD_may_sit_in_either_section():
    """`withdrawn`, `not-a-defect` and `note` are records rather than
    defects, and some are kept in `## Open` deliberately — a retraction,
    and a Word behaviour worth not chasing twice. Refusing those would be
    a gate firing on the file's own conventions, which is exactly what
    the regex did."""
    text = doc(OPEN,
               entry("A retraction kept on purpose", "withdrawn"),
               entry("Not a defect, recorded so it is not chased twice",
                     "not-a-defect"),
               entry("A framing note", "note"),
               FIXED,
               entry("Withdrawn the day it was filed", "withdrawn"),
               entry("Checked and NOT defects", "not-a-defect"))

    assert bs.problems(text) == []


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


def test_THIS_backlog_is_consistent():
    """The gate itself, over the file it exists for."""
    text = bs.FILE.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert bs.problems(text) == []


def test_EVERY_entry_declares_a_status():
    """Stated separately from the check above so the failure says which
    of the two things went wrong: an unstamped entry and a misfiled one
    are different mistakes with different fixes."""
    text = bs.FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    found = bs.entries(text)

    assert found, "the backlog has entries"
    assert [h for _s, status, h in found if status is None] == []


def test_the_tool_runs_and_reports_its_own_verdict():
    out = subprocess.run([sys.executable, str(TOOLS / "backlog_status.py")],
                         capture_output=True, text=True, encoding="utf-8",
                         cwd=ROOT, check=False)

    assert out.returncode == 0, out.stdout + out.stderr
    assert "entries" in out.stdout
