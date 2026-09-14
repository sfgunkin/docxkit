"""`tools/kill_check.py` — the cases it must refuse to run.

The tool applies one mutation and reports whether the suite noticed. Two
of its answers are worthless unless it can tell them from a mistake in
the case itself:

* a mutation that does not COMPILE makes pytest exit non-zero on the
  import, which reads exactly like a test failure — a confident false
  KILL, and the docstring says one hid dead code for an afternoon;
* a mutation that changes NOTHING leaves the file as it was, so the
  suite passes and the case reports SURVIVED — a confident false
  SURVIVOR, which sends someone off to write a test that already
  exists. This happened twice on 2026-08-19, both times to a case built
  with `old.replace(...)` whose inner pattern did not match: the source
  reads `len(stack) - 1, -1, -1)` with a space after the minus, and the
  pattern was written without one.

Both are checked here on a scratch module, because a tool that reports
the wrong thing about the tests is worse than no tool.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import docxkit

TOOLS = Path(docxkit.__file__).resolve().parents[2] / "tools"
# Everything below drives `kill_check` through `_DRIVER` in a SUBPROCESS,
# because it mutates files and a test that imported it would mutate this
# checkout. The lock tests are the exception and may import it: they
# monkeypatch ROOT and LOCK into `tmp_path` and touch nothing else.
sys.path.insert(0, str(TOOLS))

_DRIVER = '''
import sys
sys.path.insert(0, {tools!r})
from kill_check import check
print("BAD", check({module!r}, {tests!r}, {cases!r}))
'''


Case = tuple[str, str, str, bool] | tuple[str, str, str, bool, int]


def _driven(script: Path) -> subprocess.CompletedProcess[str]:
    """Run a driver script beside a `kill_check` checkout of its OWN.

    `kill_check` holds one checkout at a time, machine-wide, and a replay
    or a claim check holds it for as long as it runs. The tests that reach
    `sync()` used that one, and beside any such run they failed with
    "another caller holds", which turned `gates.py` red for a change they
    had nothing to do with (BACKLOG, 2026-09-14). A checkout is a worktree
    of the live repo, made in half a second, so each test makes one in its
    own directory, beside its own lock, and removes it after.
    """
    root = script.parent / f"{script.parent.name}-kc"
    try:
        return subprocess.run([sys.executable, str(script)],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=TOOLS.parent, check=False,
                              env={**os.environ,
                                   "DOCXKIT_KILL_CHECK_WORKTREE": str(root)})
    finally:
        if root.exists():
            subprocess.run(["git", "worktree", "remove", "--force",
                            str(root)], cwd=TOOLS.parent, check=False)


def test_a_driven_test_does_not_take_the_checkout_a_REPLAY_holds(
        tmp_path, monkeypatch):
    """Held here by ANOTHER live process, the parent, and named through
    the variable a caller sets to choose a checkout. A driven test must
    not take that one: the three tests that reach `sync()` failed this
    way beside every replay until each made its own."""
    held = tmp_path / "held"
    (tmp_path / "held.lock").write_text(str(os.getppid()), encoding="utf-8")
    monkeypatch.setenv("DOCXKIT_KILL_CHECK_WORKTREE", str(held))
    script = tmp_path / "sync.py"
    script.write_text(_SYNC.format(tools=str(TOOLS)), encoding="utf-8")

    done = _driven(script)

    out = done.stdout + done.stderr
    assert "another caller holds" not in out, out
    assert done.returncode == 0, out
    assert not held.exists(), "the held checkout was not touched"


def _run(tmp_path: Path, module: str, tests: list[str],
         cases: list[Case]) -> str:
    """Drive `check` in a subprocess, the way a scratch script does."""
    script = tmp_path / "drive.py"
    script.write_text(_DRIVER.format(tools=str(TOOLS), module=module,
                                     tests=tests, cases=cases),
                      encoding="utf-8")
    done = _driven(script)
    return done.stdout + done.stderr


def test_a_case_that_changes_NOTHING_is_refused(tmp_path):
    """The one that cost an hour: `old` and `new` identical, because the
    pattern the case meant to replace was not in the anchor."""
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("a no-op case", "def utf8_stdout", "def utf8_stdout", True)])

    assert "changes nothing" in out
    assert "SURVIVED" not in out
    assert "BAD 1" in out, "a refused case counts against the run"


def test_a_case_whose_anchor_is_AMBIGUOUS_is_refused(tmp_path):
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("an ambiguous case", "    return", "    pass", True)])

    assert "anchor occurs" in out
    assert "SURVIVED" not in out


def test_a_case_that_does_not_COMPILE_is_refused(tmp_path):
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("a broken case", "def utf8_stdout",
                 "def utf8_stdout(((", True)])

    assert "does not compile" in out
    assert "killed" not in out


def test_a_harness_that_fails_UNMUTATED_is_refused_not_read_as_a_kill(
        tmp_path):
    """A kill is read off a non-zero exit, and a checkout that cannot even
    collect its tests exits non-zero for every case. On 2026-09-11 the
    sync had left `revision/`'s halves a fortnight stale, every harness
    importing them failed to collect, and six argued equivalences came
    back "killed", `by: ?` — each a confident wrong verdict. A harness
    path that does not exist is the same failure, made on purpose: before
    the check, this case read "killed (wanted kill)" and counted as good."""
    out = _run(tmp_path, "src/docxkit/console.py",
               ["tests/test_no_such_harness.py"],
               [("a real mutation", "def utf8_stdout", "def utf8_stdout_",
                 True)])

    assert "UNMUTATED harness fails" in out, out
    assert "killed" not in out, out
    assert "BAD 1" in out, out


_SYNC = '''
import sys
sys.path.insert(0, {tools!r})
import kill_check
kill_check.sync()
live, root = kill_check.LIVE, kill_check.ROOT
for name in sorted(p.name for p in (live / "tools").glob("*.py")):
    a = (live / "tools" / name).read_bytes()
    b = (root / "tools" / name).read_bytes() \
        if (root / "tools" / name).exists() else b""
    print(("SAME" if a == b else "STALE") + " " + name)
'''


def test_the_checkout_holds_TODAYS_tools_scripts(tmp_path):
    """A case can be aimed at a `tools/` script — the sweep tools have
    harnesses of their own — and the checkout is created once, detached,
    and reused for weeks. Copying only `src/` and `tests/` into it left
    every tools script at the commit the worktree was made from, so a
    case anchored on a line added since was refused with "anchor occurs
    0 times" for a line that is in the file. Refused, not answered
    wrongly — but the reason is invisible from the message."""
    script = tmp_path / "sync.py"
    script.write_text(_SYNC.format(tools=str(TOOLS)), encoding="utf-8")

    done = _driven(script)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STALE" not in done.stdout, done.stdout
    assert "SAME kill_check.py" in done.stdout, done.stdout


_SYNC_SRC = '''
import sys
sys.path.insert(0, {tools!r})
import kill_check
kill_check.sync()
live, root = kill_check.LIVE, kill_check.ROOT
want = {{p.relative_to(live).as_posix()
         for p in (live / "src" / "docxkit").rglob("*.py")}}
have = {{p.relative_to(root).as_posix()
         for p in (root / "src" / "docxkit").rglob("*.py")}}
for rel in sorted(want):
    same = (root / rel).exists() and \
        (live / rel).read_bytes() == (root / rel).read_bytes()
    print(("SAME" if same else "STALE") + " " + rel)
for rel in sorted(have - want):
    print("EXTRA " + rel)
'''


def test_the_checkout_holds_TODAYS_subpackage_halves(tmp_path):
    """`revision.py` became `revision/` on 2026-08-30, and this sync went
    on copying `src/docxkit/*.py` — the top level. The halves stayed at
    the commit the checkout was made at, every harness that imports
    `docxkit.revision` failed to collect there, and a collection error
    exits non-zero like a kill: six argued equivalences in the halves
    came back "killed", `by: ?`, on 2026-09-11. Every depth, and nothing
    the live tree has since deleted."""
    script = tmp_path / "sync_src.py"
    script.write_text(_SYNC_SRC.format(tools=str(TOOLS)), encoding="utf-8")

    done = _driven(script)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "STALE" not in done.stdout, done.stdout
    assert "EXTRA" not in done.stdout, done.stdout
    assert "SAME src/docxkit/revision/_validate.py" in done.stdout, done.stdout


def test_sync_REBUILDS_a_checkout_whose_directory_was_deleted(tmp_path,
                                                              monkeypatch):
    """The checkout is a cache, created once and reused for weeks
    precisely so it can be thrown away. It could not rebuild from the
    one state a person puts it in by hand.

    `sync` guarded on `ROOT.exists()` — the DIRECTORY — while git also
    keeps a REGISTRATION. Delete the folder and the two disagree: `git
    worktree add` refuses with *"missing but already registered
    worktree"*, exit 128, surfacing as `CalledProcessError` three frames
    down a traceback, and the chain stops at `pytest` on every run until
    somebody who knows what a worktree is runs `git worktree prune`.

    Met 2026-09-08 removing stray `docxkit-*` folders from `D:`, which
    is how anyone meets it: nothing in the tree names the checkout
    (`ROOT` is built from the repo's own name), so it looks exactly like
    the abandoned scratch directories beside it.

    ROOT and LOCK go into `tmp_path`, as the lock tests do — this file's
    rule is that a test may import `kill_check` only when it touches
    nothing outside its own directory, and a real `sync()` here would
    mutate the live checkout."""
    import kill_check  # pyright: ignore[reportMissingImports]

    root = tmp_path / "wt"
    monkeypatch.setattr(kill_check, "ROOT", root)
    monkeypatch.setattr(kill_check, "LOCK", tmp_path / "wt.lock")
    try:
        # the state that was fatal: registered, and then deleted
        subprocess.run(["git", "worktree", "add", "-q", str(root),
                        "HEAD", "--detach"], cwd=TOOLS.parent, check=True)
        shutil.rmtree(root)

        kill_check.sync()           # used to raise CalledProcessError

        assert (root / "src" / "docxkit").is_dir()
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(root)],
                       cwd=TOOLS.parent, check=False)
        subprocess.run(["git", "worktree", "prune"], cwd=TOOLS.parent,
                       check=False)


def test_an_anchor_that_occurs_TWICE_says_how_to_pick_one(tmp_path):
    """The refusal is right — a case that mutates two places at once
    proves nothing about either — but "SKIPPED" alone leaves the reader
    to widen the anchor by hand, which costs a run each time. The two
    `if not wanted: return 0` blocks of `comments.set_done` and
    `comments.remove` are the same four lines; so are the two
    `pl.caption_sheet - 1` calls in `placement`, one per measurement."""
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("a doubled anchor", "import", "IMPORT", True)])

    assert "anchor occurs" in out
    assert "5th element" in out, out


def test_the_FIFTH_element_picks_which_occurrence_to_mutate(tmp_path):
    """And having picked one, the case runs like any other."""
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("the second import", "import", "IMPORT", True, 2)])

    assert "anchor occurs" not in out
    assert "does not compile" in out or "SURVIVED" in out or "killed" in out


def test_an_occurrence_that_is_not_THERE_is_refused(tmp_path):
    out = _run(tmp_path, "src/docxkit/console.py", ["tests/test_console.py"],
               [("the ninth import", "import", "IMPORT", True, 9)])

    assert "occurrence 9 of" in out
    assert "BAD 1" in out



# --- one checkout, one caller (2026-08-24) ------------------------------

def test_a_SECOND_caller_is_refused_rather_than_sharing_the_checkout(
        tmp_path, monkeypatch):
    """Two callers mutate and restore the SAME files, so each reads the
    other's state and both finish printing a plausible number. It is not
    hypothetical: a `kill_check` run beside a `replay_survivors` reported
    four mutants SURVIVED that its tests do kill.

    `replay_survivors` is this module called once per survivor, so a
    replay holds the checkout for twenty minutes while looking exactly
    like nothing is running — which is what makes a lock worth more than
    care in the caller.
    """
    import kill_check  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(kill_check, "ROOT", tmp_path / "wt")
    monkeypatch.setattr(kill_check, "LOCK", tmp_path / "wt.lock")
    # ANOTHER live process: the parent. Its own pid used to stand in for
    # one, and is now — correctly — a lock this process already holds.
    (tmp_path / "wt.lock").write_text(str(os.getppid()), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        kill_check._take_lock()

    assert "one checkout" in str(exc.value)
    assert str(tmp_path / "wt.lock") in str(exc.value), "say how to clear it"


def test_a_lock_this_process_ALREADY_holds_is_not_a_second_caller(
        tmp_path, monkeypatch):
    """`check` syncs, and so takes the lock, on every call, and
    `verify_equivalents` calls it once per module in one process. Read as
    a second caller, its own lock ended the run after the first module —
    met on 2026-09-11 with three modules of claims to check."""
    import kill_check  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(kill_check, "ROOT", tmp_path / "wt")
    monkeypatch.setattr(kill_check, "LOCK", tmp_path / "wt.lock")
    (tmp_path / "wt.lock").write_text(str(os.getpid()), encoding="utf-8")

    kill_check._take_lock()                    # used to raise SystemExit

    assert (tmp_path / "wt.lock").read_text(encoding="utf-8") == str(
        os.getpid())


def test_a_lock_whose_HOLDER_IS_GONE_is_taken_over(tmp_path, monkeypatch):
    """The release is an atexit handler, so a caller that is killed —
    which is how a long replay gets stopped — leaves the file behind.
    Obeying that forever would make one interrupted run cost every later
    one."""
    import kill_check  # pyright: ignore[reportMissingImports]

    monkeypatch.setattr(kill_check, "ROOT", tmp_path / "wt")
    monkeypatch.setattr(kill_check, "LOCK", tmp_path / "wt.lock")
    # a pid nothing can be running under
    (tmp_path / "wt.lock").write_text("999999999", encoding="utf-8")

    kill_check._take_lock()

    assert (tmp_path / "wt.lock").read_text(encoding="utf-8") == str(
        os.getpid()), "the live caller owns it now"


# `nth` picks an occurrence, and a reader arrives at one by counting
# LINES. The string does not agree, in two different ways, and each
# disagreement picks a line nobody meant — which reports SURVIVED about
# a mutation that was never applied. That is a false negative in the
# direction that reads as "no test needed here".

INDENTS = (
    "def f():\n"
    "    for x in xs:\n"
    "        if a:\n"
    "            continue\n"          # the one a reader means: #1
    "        for y in ys:\n"
    "            if b:\n"
    "                continue\n"      # deeper: NOT a match
    "        if c:\n"
    "            continue      # with a trailing note\n"   # longer: NOT one
    "        if d:\n"
    "            continue\n"          # #2
)


def test_an_indented_anchor_does_not_match_a_DEEPER_line():
    """`"            continue"` is a substring of
    `"                continue"`, so plain counting finds the deeper
    lines too and `nth` lands past where a reader is pointing."""
    from kill_check import _places  # pyright: ignore[reportMissingImports]

    assert len(_places(INDENTS, "            continue")) == 2


def test_an_indented_anchor_does_not_match_a_LONGER_line_either():
    """The other half, and the one that survives a line-start check: an
    anchor is a prefix of any longer line that begins the same way. Both
    ends have to be a line boundary."""
    from kill_check import _places  # pyright: ignore[reportMissingImports]

    places = _places(INDENTS, "            continue")
    starts = [INDENTS[:at].count(chr(10)) + 1 for at in places]

    assert starts == [4, 11], starts


def test_a_BARE_fragment_is_still_counted_wherever_it_appears():
    """An anchor written without leading whitespace is meant as a
    fragment — `hits[0]`, `!= want` — and narrowing it to whole lines
    would refuse every case in this file that uses one."""
    from kill_check import _places  # pyright: ignore[reportMissingImports]

    assert len(_places(INDENTS, "continue")) == 4


def test_the_nth_replacement_uses_the_same_counting_as_the_refusal():
    """The count that decides "anchor occurs N times" and the pick that
    applies the mutation have to be one rule. Two would refuse on one
    number and mutate by another."""
    from kill_check import (  # pyright: ignore[reportMissingImports]
        _nth_replace,
        _places,
    )

    anchor = "            continue"
    out = _nth_replace(INDENTS, anchor, "            break", 2)

    assert out.splitlines()[10].strip() == "break"
    assert out.splitlines()[3].strip() == "continue", "the first is untouched"
    assert len(_places(INDENTS, anchor)) == 2


def test_a_checked_mutant_gets_the_SAME_sandbox_as_a_session():
    """A case aimed at the registry's own isolation escapes it exactly as
    a session's mutant did (`mutation_session.sandboxed_appdata`, which
    says how). The guard was learned in the session tool; a checker
    beside it without one is the shape the lock took twice."""
    import kill_check  # pyright: ignore[reportMissingImports]
    import mutation_session  # pyright: ignore[reportMissingImports]

    env = kill_check._env()

    sandbox = mutation_session.sandboxed_appdata(kill_check.ROOT)
    assert sandbox.items() <= env.items(), env
    assert Path(env["LOCALAPPDATA"]).parent == kill_check.ROOT.parent
