#!/usr/bin/env python
"""Apply ONE mutation at a time and report whether the suite kills it.

The other half of `mutation_session.py`. That one asks "how much of this
module would nobody notice changing"; this one asks "does the test I
just wrote actually hold the line I aimed it at" — which is the step
CONTRIBUTING requires after writing a test, and the step that turns a
survivor list into a list of REAL gaps rather than harness artifacts.

    from tools.kill_check import check
    check("src/docxkit/edit.py", ["tests/test_find_edit.py"], [
        ("rep  count != n -> < n", "    if count != n:",
         "    if count < n:", True),          # True = expect a KILL
        ("hits[0] -> hits[-1]  [claimed equivalent]",
         "    at, end = hits[0]", "    at, end = hits[-1]", False),
    ])

Each case is `(label, old, new, expect_kill)`. The anchor must occur
EXACTLY once, or the case is skipped rather than mutating something
else — add a fifth element, `(label, old, new, expect_kill, 2)`, to say
WHICH occurrence you meant. `expect_kill=False` records an equivalence
you have argued for: the run then reports it as expected when it
survives, so the claim is checked rather than assumed.

Three things this does that a hand-rolled loop does not, each of which
produced a wrong answer first:

**A private checkout.** The live tree is what `mutation_session` copies
from at every chunk boundary, so mutating it while a measuring run is
going hands that run a mutation of a module it is not measuring; its
baseline check then fails and the whole module's measurement aborts.

**A compile check before running.** A mutation that does not parse makes
pytest exit non-zero on the import, which reads exactly like a test
failure — so a case with the wrong indentation reports a confident
false KILL. One did, and hid a piece of dead code for an afternoon.

**Naming the test that killed it.** "Killed" is not the finding; WHICH
test noticed is, because a kill by an unrelated test usually means the
mutation broke something else on the way.
"""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

LIVE = Path(__file__).resolve().parents[1]
#: Its own worktree, refreshed from the live tree on every call.
ROOT = Path(os.environ.get("DOCXKIT_KILL_CHECK_WORKTREE",
                           str(LIVE.parent / f"{LIVE.name}-kc")))

#: One checkout, so one caller at a time — the same rule
#: `mutation_session` states for its own worktree, and the same reason:
#: two callers mutate and restore the SAME files, each reads the other's
#: state, and both finish and print a plausible number.
#:
#: It matters more here than it looks, because `replay_survivors` IS
#: this module, called once per survivor: a replay holds the checkout
#: for twenty minutes while looking like nothing is running. Measured
#: 2026-08-24 — a `kill_check` beside a replay reported four mutants
#: SURVIVED that its tests do kill.
LOCK = ROOT.parent / f"{ROOT.name}.lock"


def _take_lock() -> None:
    """Refuse to start while another caller holds the checkout.

    A lock whose holder is GONE is taken over rather than obeyed: the
    release is an `atexit` handler, so a caller that is killed leaves
    the file behind and the next one would refuse for a process that no
    longer exists. `_alive` comes from `mutation_session` rather than
    being written again — on Windows it cannot be `os.kill(pid, 0)`,
    which TerminateProcess would make an existence check that kills the
    holder it asked about.
    """
    from mutation_session import _alive  # noqa: PLC0415

    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = LOCK.read_text(encoding="utf-8").strip() or "unknown"
        if holder.isdigit() and not _alive(int(holder)):
            LOCK.unlink(missing_ok=True)
            return _take_lock()
        sys.exit(f"another caller holds {ROOT} (pid {holder}). It is one "
                 f"checkout, so running both makes each read the other's "
                 f"mutations — a replay is this module 348 times over. "
                 f"Wait for it, or delete {LOCK} if it is stale.")
    with os.fdopen(fd, "w") as fh:
        fh.write(str(os.getpid()))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    return None


def sync() -> None:
    """Refresh the private checkout from the live tree, and CLAIM it."""
    _take_lock()
    if not ROOT.exists():
        subprocess.run(["git", "worktree", "add", "-q", str(ROOT),
                        "HEAD", "--detach"], cwd=LIVE, check=True)
    # `tools` as well as the package: the sweep scripts have harnesses
    # of their own now, so a case can be aimed at one of them — and a
    # checkout that copies only `src/` and `tests/` anchors such a case
    # against the version committed the day the worktree was made,
    # which reports "anchor occurs 0 times" for a line that is in the
    # file.
    for sub in ("src/docxkit", "tests", "tools"):
        for src in sorted((LIVE / sub).glob("*.py")):
            shutil.copy2(src, ROOT / sub / src.name)
    # and the documents the SUITE reads — see REPO_FILES
    sys.path.insert(0, str(LIVE / "tools"))
    from harness_map import REPO_FILES  # noqa: PLC0415
    for name in REPO_FILES:
        shutil.copy2(LIVE / name, ROOT / name)
    probe = (f"import docxkit, sys; "
             f"sys.exit(0 if {ROOT.name!r} in docxkit.__file__ else 1)")
    if subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                      env=_env()).returncode:
        sys.exit(f"{ROOT} does not win on sys.path — refusing to mutate, "
                 f"because the LIVE tree is what would be mutated")


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"),
            "PYTHONIOENCODING": "utf-8"}


def _nth_replace(text: str, old: str, new: str, nth: int) -> str:
    """`text` with only the `nth` (1-based) occurrence of `old` replaced."""
    at = -1
    for _ in range(nth):
        at = text.index(old, at + 1)
    return text[:at] + new + text[at + len(old):]


def _vet(original: str, path: Path, label: str, *,
         old: str, new: str, nth: int) -> tuple[str | None, str | None]:
    """The mutated source, or why this case cannot be run.

    Every refusal here is a statement about the ARGUMENTS, and none of
    them needs a checkout to reach — which is why they happen before
    `sync()` claims one. Saying "you passed me the wrong string" is not
    worth a machine-wide lock, and taking one to say it made the tests
    for these refusals fight each other: the suite runs across eight
    workers, several land in this file at once, and the ones that lose
    the race report the lock message instead of the refusal they asked
    about. The lock and the `-n 8` landed the same morning.
    """
    n = original.count(old)
    if not nth and n != 1:
        return None, (f"  ?? {label}: anchor occurs {n} times — SKIPPED "
                      f"(pass a 5th element, 1..{n}, to pick one)")
    if nth and not 1 <= nth <= n:
        return None, (f"  ?? {label}: asked for occurrence {nth} of {n} — "
                      f"SKIPPED")
    if new == old:
        # A case built with `old.replace(...)` whose inner pattern does
        # not match leaves `new` identical to `old`: the file is
        # rewritten with itself, the suite passes, and the case reports
        # SURVIVED — a missing test where there is none. Twice on
        # 2026-08-19, both times on `len(stack) - 1, -1, -1)`, where the
        # source has a space after the minus and the pattern did not.
        return None, (f"  ?? {label}: the replacement changes nothing — "
                      f"SKIPPED, since an unmutated file always survives")
    mutated = (_nth_replace(original, old, new, nth) if nth
               else original.replace(old, new))
    try:
        compile(mutated, str(path), "exec")
    except SyntaxError as exc:
        return None, (f"  ?? {label}: does not compile ({exc.msg}) — "
                      f"SKIPPED, since pytest would exit non-zero on the "
                      f"import and that reads as a kill")
    return mutated, None


def check(module: str, tests: list[str],
          cases: Sequence[tuple[str, str, str, bool]
                          | tuple[str, str, str, bool, int]]) -> int:
    """Run every case; return how many did NOT match their expectation.

    A case is `(label, old, new, expect_kill)` and the anchor must occur
    EXACTLY once. A fifth element says WHICH occurrence to mutate when
    it does not: the two `if not wanted: return 0` blocks of
    `comments.set_done` and `comments.remove` are the same four lines,
    and so are the two `pl.caption_sheet - 1` calls in `placement`, one
    per measurement pass. Widening the anchor by hand until it is unique
    works and costs an iteration every time; naming the occurrence says
    what was meant.
    """
    # The LIVE tree, because `sync()` copies from it: the text a case is
    # vetted against is the text it will be applied to.
    original = (LIVE / module).read_text(encoding="utf-8")
    runnable: list[tuple[str, str, bool]] = []
    bad = 0
    for case in cases:
        label, old, new, expect_kill = case[:4]
        nth = case[4] if len(case) > 4 else 0
        mutated, why = _vet(original, LIVE / module, label,
                            old=old, new=new, nth=nth)
        if why is not None:
            print(why)
            bad += 1
            continue
        assert mutated is not None
        runnable.append((label, mutated, expect_kill))
    if not runnable:
        return bad

    sync()
    path = ROOT / module
    try:
        for label, mutated, expect_kill in runnable:
            path.write_text(mutated, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-x", "-q",
                 "-p", "no:cacheprovider", *tests],
                cwd=ROOT, capture_output=True, text=True,
                # utf-8 explicitly: `text=True` decodes with the PARENT's
                # locale, and this package's messages are full of
                # em-dashes — one in a failing test's output crashed the
                # reader thread mid-run
                encoding="utf-8", errors="replace", env=_env())
            killed = proc.returncode != 0
            mark = "OK " if killed == expect_kill else "!! "
            verb = "killed" if killed else "SURVIVED"
            want = "kill" if expect_kill else "equivalent"
            print(f"  {mark}{label}: {verb} (wanted {want})")
            if killed:
                first = [line.split(" - ")[0].removeprefix("FAILED ")
                         for line in proc.stdout.splitlines()
                         if line.startswith("FAILED")]
                print(f"       by: {(first or ['?'])[0].strip()[:88]}")
            if killed != expect_kill:
                bad += 1
    finally:
        path.write_text(original, encoding="utf-8")
    return bad
