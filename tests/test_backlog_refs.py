"""`tools/backlog_refs.py` — the gate on the clause that gets dropped.

`BACKLOG.md` says done means fix + test + workaround deleted + entry
moved to `## Fixed` with its commit. On 2026-08-27 the `## Open` section
listed ten entries of which five were already fixed, each in a commit
whose message describes the defect in the file's own words and none of
which touched the file. The batch that morning was ordered off a stale
list, so the first job it picked was the one already done.

What is tested here is the shape of the check as much as the check:
the rule has to pass the workflow people actually use (code first, entry
in the next commit) and fail the one state that matters (a fix at the tip
with the record never written). A gate that fires on the ordinary case
gets turned off within a week, which this package has an entry about too.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

# `tools/` is not a package and is not installed; the path insert above
# is how its scripts are reached, here and by each other.
import backlog_refs as br  # noqa: E402  # pyright: ignore[reportMissingImports]

ROOT = Path(docxkit.__file__).resolve().parents[2]

FIX = f"Repair the half-eaten pair\n\n{br.MARKER}"
PLAIN = "Tidy an import"


def test_a_fix_at_the_TIP_with_no_record_is_the_state_that_fails():
    """The defect itself: the code shipped, the entry never moved. Newest
    first, so this commit is the tip."""
    found = br.unrecorded([("aaa1111", FIX, False),
                           ("bbb2222", PLAIN, False)])

    assert [sha for sha, _ in found] == ["aaa1111"]
    assert found[0][1] == "Repair the half-eaten pair", \
        "the SUBJECT, so the reader can see which fix went unrecorded"


def test_the_entry_moved_in_the_NEXT_commit_is_recorded():
    """The workflow every real adopter used. All six commits carrying the
    marker on 2026-08-27 landed the code first and moved the entry after,
    so a rule demanding both in ONE commit would have been red six times
    for six correctly-closed defects."""
    assert br.unrecorded([("ccc3333", "Move the entry", True),
                          ("aaa1111", FIX, False)]) == []


def test_both_in_ONE_commit_is_recorded_too():
    """The other correct workflow. The rule is about the record existing,
    not about how it was split."""
    assert br.unrecorded([("aaa1111", FIX, True)]) == []


def test_a_LATER_backlog_edit_does_not_cover_an_EARLIER_fix():
    """Order is the whole content of the rule, and the easy way to get it
    backwards. Here the file was touched, then a fix shipped on top of
    it — the record is older than the thing it would have to describe,
    so the fix is still unrecorded."""
    found = br.unrecorded([("aaa1111", FIX, False),
                           ("ddd4444", "Reword an entry", True)])

    assert [sha for sha, _ in found] == ["aaa1111"]


def test_every_unrecorded_fix_is_named_not_just_the_first():
    """Two fixes can ship before anyone opens the file, and a gate that
    names one of them gets closed by moving one entry."""
    found = br.unrecorded([("aaa1111", FIX, False),
                           ("eee5555", PLAIN, False),
                           ("fff6666", f"Another\n\n{br.MARKER}", False),
                           ("ggg7777", "The last record", True)])

    assert [sha for sha, _ in found] == ["aaa1111", "fff6666"]


def test_a_commit_that_does_not_OPT_IN_is_not_judged():
    """The check binds commits that name the file, and that limit is
    deliberate: matching commit prose against open entries is a guess
    about English. A commit saying nothing is outside the rule."""
    assert br.unrecorded([("aaa1111", "A fix, quietly", False)]) == []


def test_FILING_a_new_entry_is_not_RECORDING_a_fix():
    """The regression review found, and it would have made this gate
    green over the exact history it was written for.

    The flag used to mean "this commit edited BACKLOG.md at all", and
    filing a NEW defect is the most frequent reason to open the file —
    so one filing commit retroactively marked every pending fix as
    recorded. What the rule names is *entry moved to `## Fixed`*, and
    that is what has to be asked.
    """
    filing = ("ccc3333", "File a new S4: nothing checks section placement",
              False)
    fix = ("aaa1111", FIX, False)

    assert [sha for sha, _ in br.unrecorded([filing, fix])] == ["aaa1111"]


def test_a_CLOSED_heading_is_what_counts_as_the_record():
    """The discriminator itself, against the four shapes a real commit
    to this file produces. Only an added heading that says the entry is
    resolved is a record; prose that happens to contain the word is not,
    and neither is a heading being FILED."""
    closes = "+### ~~S3 — a `--sample` run OVERWRITES~~ — FIXED 27.08\n"
    also = "+### S1 an ENDNOTE id was spliced in — FIXED 24.08\n"
    files = "+### S4 — nothing checks that an entry sits in the SECTION\n"
    prose = "+The entry above was FIXED in another commit entirely.\n"

    assert br._CLOSES.search(closes)
    assert br._CLOSES.search(also), "a heading can close without the strike"
    assert not br._CLOSES.search(files), "filing is not closing"
    assert not br._CLOSES.search(prose), "a heading, not any line"


def test_a_closure_is_looked_for_in_BOTH_backlog_files(monkeypatch):
    """After the 2026-08-30 split a closure is an entry APPEARING in
    `BACKLOG-ARCHIVE.md`, not a heading struck in place.

    Restricted to BACKLOG.md this gate would see a deletion where the
    closure was, find no closure at any depth of the walk, and report
    every `Refs BACKLOG.md` commit in 200 of history as unrecorded —
    permanently red, which by this repo's own severity scale outranks a
    wrong answer nobody sees.
    """
    seen: list[list[str]] = []

    class _Done:
        returncode = 0
        stdout = ""

    def fake_run(argv, **_kw):
        seen.append(list(argv))
        return _Done()

    monkeypatch.setattr(br.subprocess, "run", fake_run)
    br._closes(br.ROOT, "aaa1111")

    (argv,) = seen
    assert "BACKLOG.md" in argv
    assert "BACKLOG-ARCHIVE.md" in argv
    assert argv.count("--") == 1, "one show, both paths — not two walks"


def test_the_commit_MARKER_still_names_BACKLOG_md_only():
    """The convention is a literal string people copy into a commit
    message. Repointing it at the archive would invalidate every commit
    that already carries it, for no gain: what the marker opts into is
    the rule, not a file."""
    assert br.MARKER == "Refs BACKLOG.md"
    assert br.FILES[0] == "BACKLOG.md"


def test_a_git_FAILURE_is_not_reported_as_an_empty_history(monkeypatch):
    """`fatal: detected dubious ownership` is ordinary for a repo on a
    second drive, in a container, or under another user — and it used to
    make this answer "no history", print nothing to check, and exit 0
    while the live-repo test took its skip. Green suite, green tool,
    dead gate. That is the shape a suppressed git error always has: a
    fatal error looks exactly like a true nothing."""
    class _Failed:
        returncode = 128
        stdout = ""
        stderr = ("fatal: detected dubious ownership in repository at "
                  "'D:/docxkit'")

    monkeypatch.setattr(br.subprocess, "run", lambda *a, **kw: _Failed())

    with pytest.raises(RuntimeError, match="dubious ownership"):
        br.read_log(ROOT)


def test_a_directory_that_is_simply_NOT_a_repo_still_answers_None(
        monkeypatch):
    """The other half: the case the None is FOR has to keep working, or
    the fix above turns a source export into a failing suite."""
    class _NoRepo:
        returncode = 128
        stdout = ""
        stderr = ("fatal: not a git repository (or any of the parent "
                  "directories): .git")

    monkeypatch.setattr(br.subprocess, "run", lambda *a, **kw: _NoRepo())

    assert br.read_log(ROOT) is None


def test_no_git_history_is_not_a_FAILURE(tmp_path):
    """A source export has no history to read, and a gate that fails
    there is reporting on the packaging rather than on the backlog."""
    assert br.read_log(tmp_path) is None


# --- the live repository -------------------------------------------------


def test_THIS_repo_has_no_unrecorded_fix():
    """The gate itself, against the history it exists for.

    It goes red between shipping a fix that names the backlog and moving
    its entry, which is the whole point: the gap is a state to be closed
    within the batch, not a thing to be noticed weeks later.
    """
    commits = br.read_log(ROOT)
    if commits is None:
        pytest.skip("no git history in this checkout")

    found = br.unrecorded(commits)

    assert found == [], (
        "these commits say " + br.MARKER + " and nothing since has touched "
        + br.FILE + ": " + ", ".join(f"{sha[:8]} {subject}"
                                     for sha, subject in found))


def test_the_tool_runs_and_reports_its_own_verdict():
    """`main` is what CI and a person both invoke, and its exit code is
    the answer. Run as a subprocess because that is the only way to see
    the status the caller sees."""
    out = subprocess.run([sys.executable, str(TOOLS / "backlog_refs.py")],
                         capture_output=True, text=True, encoding="utf-8",
                         cwd=ROOT, check=False)

    assert out.returncode == 0, out.stdout + out.stderr
    assert br.FILE in out.stdout
