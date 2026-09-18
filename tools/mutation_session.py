#!/usr/bin/env python
"""Run a cosmic-ray session safely, in bounded chunks.

    python tools/mutation_session.py src/docxkit/edit.py \
        --tests tests/test_find_edit.py tests/test_edit_boundaries.py \
        --sample 460 --minutes 9

    python tools/mutation_session.py src/docxkit/edit.py --report

`tools/mutate.py` is the curated list — every mutation in it re-introduces
a defect this package has really shipped, and CI gates on all of them
dying. This is the other half: cosmic-ray generates every mutation it can
think of, which finds the gaps nobody thought to curate. Read the result
with `tools/mutation_survivors.py`, which discounts the annotation
mutants PEP 563 makes un-killable; the raw percentage is close to
meaningless here.

Four things have to be right or the run produces a plausible wrong
number, and each cost a run to learn (2026-08-15/16):

**Isolate, and ASSERT the isolation.** cosmic-ray mutates the module in
place, and docxkit is installed editable — so a paper script importing
docxkit mid-run imports a mutant. This works in a `git worktree` with
`PYTHONPATH` pointing at it (the editable install is a plain-path
``.pth``, so PYTHONPATH wins) and refuses to start unless
``docxkit.__file__`` really resolves there.

**Verify the baseline before every chunk.** cosmic-ray restores the file
after each mutant but NOT when it is terminated, so a killed run leaves
its mutation in the tree. The next session then has a red baseline,
every mutant "fails the tests" for a reason that has nothing to do with
it, and the result is a 99.9 % kill rate that looks like a triumph:
measured, 1383 of 1385 "killed" off one stray `>=` turned into `is not`.

**Clear the unfinished rows.** A termination also leaves rows with a
null outcome, and cosmic-ray treats a spec with any row as done — so
`exec` resumes nothing at all and reports instant completion.

**Count what FINISHED, not what was graded.** A mutant can come back
INCOMPETENT — cosmic-ray could not run it at all — which is neither a
kill nor a survival and is still done. Treating "killed + survived" as
the progress made `--chunks 0` spin forever on the last mutant of
`package.py`, asking for another chunk every few seconds while `exec`
had nothing left to run, and the sequential sweep behind it never
reached its next module.

**Restore the module from the SNAPSHOT, not from the live tree.** The
chunk loop puts the module back before each chunk, to undo a mutation a
terminated run left behind — and it used to copy it from the working
tree. So an edit made while a sweep ran was picked up half way through:
the plan in the session describes one source, the next chunk mutates
another, and the harness in the worktree is still the one copied at
startup. Measured 2026-08-19 on `tracked.py`: a module standing at 4.9 %
came back at 28.9 % (237/821), with every cluster a multiple of eleven —
a plausible number, and pure artefact. The snapshot taken when the
session was created is what the plan is about, so it is what each chunk
restores; the live tree moving is now a warning, not a silent regrade.

**Force UTF-8 out of the child.** When a mutant is KILLED, cosmic-ray
decodes pytest's output as UTF-8 while pytest writes the console
codepage; this package's messages are full of em-dashes, the decode
raises, and the kill is recorded as INCOMPETENT — dropping out of the
denominator. It also costs 60x in wall clock (1 mutant/minute against
0.46/second). ``PYTHONIOENCODING=utf-8`` fixes both.

The chunking is not a nicety either: a full module is tens of minutes,
and a session that is interrupted half way is exactly how hazards two
and three bite. Each chunk is restartable and leaves the tree clean.
"""
from __future__ import annotations

import argparse
import atexit
import contextlib
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
WORKTREE = Path(os.environ.get("DOCXKIT_MUT_WORKTREE", r"D:/docxkit-mut"))
#: One session at a time, because they share the worktree.
#:
#: Two runs measuring DIFFERENT modules still mutate one checkout, so
#: each reads the other's mutation and every result is suspect —
#: silently, because both complete and both print a plausible number.
#: Four batches were launched on 2026-08-17 behind shell wait-loops that
#: did not match, and the tell was a later batch finishing before an
#: earlier one. A lock in the tool is worth more than care in the caller.
LOCK = WORKTREE.parent / f"{WORKTREE.name}.lock"


# Through a name rather than `if sys.platform == "win32":` at the branch:
# mypy folds that comparison to the platform it is RUNNING on, so the
# posix half reads as plain unreachable code on Windows (`warn_unreachable`
# fails the gate) and the Windows half goes unchecked on the Linux CI.
# A `bool` is opaque to both, so each arm is type-checked on both.
_WINDOWS = sys.platform == "win32"

#: A mutant whose harness runs longer than this is KILLED — cosmic-ray's
#: own verdict for a timeout. Under `--fast` the wrapper enforces it
#: (`mutant_tests.py --deadline`) with cosmic-ray's limit `BACKSTOP` above;
#: otherwise cosmic-ray does, with pytest as the immediate child its kill
#: reaches.
MUTANT_SECONDS = 30
BACKSTOP = 10
#: How much of `MUTANT_SECONDS` the UNMUTATED harness may take. A mutant
#: that survives is one whose tests all had to run, so a harness near the
#: deadline turns survivors into timeouts, and a timeout reads KILLED.
#: Measured 2026-09-17: the revision/ superset harness ran 29.4 s single-
#: process on a loaded machine, and `revision/_promote.py` graded 24 of 24
#: killed, "0.0% survive", with nothing said. The headroom is for the load
#: a sweep runs beside — other streams, a gate run, a replay.
BASELINE_SHARE = 0.6
#: A chunk this long has room to end any mutant twice over, so one that
#: ends none is stuck, not slow.
_STUCK_AFTER = 2 * (MUTANT_SECONDS + BACKSTOP)


def _alive(pid: int) -> bool:
    """Is that process still running? NOT `os.kill(pid, 0)` on Windows,
    where any signal other than CTRL_C/CTRL_BREAK calls TerminateProcess
    — the existence check would kill the holder it asked about."""
    if _WINDOWS:
        out = _run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _take_lock() -> None:
    """Refuse to start while another session holds the worktree.

    A lock whose holder is GONE is taken over rather than obeyed: the
    release is an `atexit` handler, so a session that is killed — which
    is how an unattended sweep gets stopped — leaves the file behind,
    and the next run then refuses for a process that no longer exists.
    """
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = LOCK.read_text(encoding="utf-8").strip() or "unknown"
        if holder.isdigit() and not _alive(int(holder)):
            print(f"  taking over a stale lock on {WORKTREE} — pid {holder} "
                  f"is gone", flush=True)
            LOCK.unlink(missing_ok=True)
            return _take_lock()
        sys.exit(f"another mutation session holds {WORKTREE} (pid {holder}). "
                 f"They share one checkout, so running both makes each read "
                 f"the other's mutations. Wait for it, or delete {LOCK} if "
                 f"it is stale.")
    with os.fdopen(fd, "w") as fh:
        fh.write(str(os.getpid()))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    return None


def _mark_running(stem: str) -> None:
    """Say, in the repository, which module is being swept right now.

    The lock says a WORKTREE is busy and holds only a pid; it lives
    beside whatever directory `--in` named, so nothing in the checkout
    can find it, and nothing in the checkout could name the module even
    if it did. What was missing is the other direction: *is this file
    under a stream at this moment*, asked by somebody about to merge.

    On 2026-09-18 a survivor round was cherry-picked onto master at
    04:17, two of its commits touching `_table_core.py`, which had been
    planned from master at 04:00 and went on grading until 04:42. The
    figure — 1,372 mutants — was void the moment the merge landed, and
    nothing anywhere could have been asked beforehand. `stale_figures.py
    --running` is that question; this is what answers it.

    A killed session leaves the marker behind, exactly as it leaves the
    lock, so the reader checks the pid rather than trusting the file.
    """
    mark = ROOT / f".mutation-{stem}.running"
    mark.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: mark.unlink(missing_ok=True))


def _run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        cmd, text=True, capture_output=True, **kw)
    return proc


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(WORKTREE / "src")
    env["PYTHONIOENCODING"] = "utf-8"      # see the module docstring
    # Every mutant pays pytest's start-up, and five installed plugins
    # (cov, xdist, benchmark, hypothesis, anyio) are loaded for each one
    # and used by none: 1.81s becomes 0.75s per mutant, measured on one
    # test, which is eight minutes off a 460-mutant sweep and about
    # fifty off a whole module. The plugin the command DOES need is
    # named explicitly in `write_config`.
    #
    # Verified equal, not assumed: the harness that uses hypothesis
    # reports the same 373 passed, 14 skipped either way.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.update(sandboxed_appdata(WORKTREE))
    return env


def sandboxed_appdata(tree: Path) -> dict[str, str]:
    """Where a MUTANT may keep per-user state: beside `tree`, never in the
    author's own profile.

    The suite isolates the machine-wide paper registry through
    ``DOCXKIT_PAPERS`` (conftest's `_isolated_paper_registry`), and for an
    unmutated tree that is enough. It is not enough for a mutant OF the
    isolation. Measured 2026-09-11: one mutant of
    `revision/_registry.registry_path` ignored the variable, fell through
    to ``%LOCALAPPDATA%``, and the harness it went on to run appended 160
    throwaway papers to the author's real registry — every
    `revision.init` in the run, one line each, until
    `test_init_registers_the_paper` failed at the end — and `status --all`
    then listed every one of them as a paper gone missing. Nothing in the
    run said so: the mutant was KILLED, which is the right verdict.

    A mutation run mutates exactly the code that guards against it, so the
    guard has to sit outside that code. Every root the registry can fall
    back to is pointed here — the override itself too, so an UNMUTATED
    registry lands in the same place — and the one it cannot reach this
    way, the POSIX ``~/.local/share`` behind both, is a path the Windows
    registry never reads.
    """
    home = tree.parent / f"{tree.name}.appdata"
    return {"LOCALAPPDATA": str(home), "XDG_DATA_HOME": str(home),
            "DOCXKIT_PAPERS": str(home / "docxkit" / "papers.txt")}


def snapshot_dir(stem: str) -> Path:
    """Where the files this session's PLAN was built from are kept."""
    return ROOT / f".mutation-{stem}.pristine"


def take_snapshot(snapshot: Path, module: Path, tests: list[str]) -> None:
    """Copy the module and its harness as they are, once per session."""
    for rel in [str(module), *tests]:
        target = snapshot / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)


def moved_since(snapshot: Path, module: Path, tests: list[str]) -> list[str]:
    """Which of those files the working tree no longer agrees with.

    Bytes, not mtimes: a file rewritten with identical content has not
    moved for this purpose, and `shutil.copy2` preserves the mtime
    anyway.

    Through `stale_figures.lines_of`, which is where that comparison
    lives for every caller that asks this question — a resume here, a
    figure there, a replay in the third place. A checkout's line endings
    are not an edit, and answering otherwise refused a resume in a
    worktree where nothing had been touched. Imported inside the
    function, the way `kill_check` reaches back into this module: these
    tools are each other's, and nothing here is needed at import time.
    """
    from stale_figures import lines_of  # noqa: PLC0415

    out = []
    for rel in [str(module), *tests]:
        kept = snapshot / rel
        if (not kept.exists()
                or lines_of(kept) != lines_of(ROOT / rel)):
            out.append(rel)
    return out


def mirror_src(live: Path, tree: Path) -> None:
    """`tree`'s ``src/docxkit`` made the same as `live`'s: every module
    at every depth copied in, and every module `live` no longer has
    deleted. The reasons for both halves are at the call in
    :func:`ensure_worktree`.

    A function, because there are two checkouts and the second copied
    the package with `glob("*.py")` long after the first stopped — see
    `kill_check.sync`, where that cost six false verdicts in a row.

    **Walked from the package, not from `live`.** `rglob` puts `**/` in
    front of its pattern, so `live.rglob("src/docxkit/**/*.py")` matched a
    `src/docxkit` at ANY depth, and every session's snapshot keeps one:
    `.mutation-<stem>.pristine/src/docxkit/<module>.py`. On 2026-09-12 that
    was 52 of the 119 files mirrored, into a worktree that has no use for
    them. It is also why a fan-out lost a stream at startup (BACKLOG S4):
    every stream starts `--fresh`, which deletes its OWN snapshot, and a
    stream mirroring at that moment listed the snapshot and then copied from
    a directory that had gone, `[WinError 3]`.
    """
    package = {p.relative_to(live)
               for p in (live / "src" / "docxkit").rglob("*.py")}
    for path in sorted(package):
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live / path, target)
    for stale in sorted((tree / "src" / "docxkit").rglob("*.py")):
        if stale.relative_to(tree) not in package:
            stale.unlink()


def ensure_worktree(module: Path, tests: list[str]) -> None:
    """A private checkout that imports ITSELF, with the live files in it."""
    if not WORKTREE.exists():
        out = _run(["git", "worktree", "add", "-q", str(WORKTREE),
                    "HEAD", "--detach"], cwd=ROOT)
        if out.returncode:
            sys.exit(f"could not create the worktree: {out.stderr.strip()}")
    # the point of measuring is to measure what is in the working tree,
    # including what is not committed yet.
    #
    # ALL of src/, not just the module under test. The worktree is created
    # once at HEAD and reused, so refreshing only the target left every
    # other module at whatever HEAD was that day — invisible until a
    # harness contains a test that reads the WHOLE package. Measuring
    # `errors.py` on 2026-08-17 did: `test_api_surface`'s exception gate
    # walks every module, read 42 stale ones, and failed the baseline
    # check with sixteen errors that had nothing to do with the mutation.
    #
    # RECURSIVE, and stale files are DELETED. Both halves were wrong the
    # day `revision.py` became `revision/` (2026-08-30): a `*.py` glob
    # copied none of the fourteen halves, and nothing removed the
    # 144 KB `revision.py` the worktree still held from 24 August. A run
    # would then have imported the pre-split module — the same source
    # the session's plan does not describe — and produced a number for
    # it. That is this file's own opening hazard, arriving through the
    # one path it did not guard: not a stale MODULE, a stale LAYOUT.
    mirror_src(ROOT, WORKTREE)
    # `tests/conftest.py` is in no module's harness — nothing names it —
    # and every test file copied here imports it. Without it the
    # worktree runs TODAY's tests against whatever conftest was in the
    # commit it was created at, and the first helper added to conftest
    # aborts every sweep at the baseline check, on a module the session
    # was not asked about.
    for rel in [str(module), "tests/conftest.py", *tests]:
        target = WORKTREE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    # and the documents the SUITE reads: the worktree is at HEAD, and a
    # test that holds the README to this parser then reads an older
    # README and fails the baseline. See REPO_FILES.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from harness_map import REPO_FILES  # noqa: PLC0415
    for name in REPO_FILES:
        shutil.copy2(ROOT / name, WORKTREE / name)

    probe = ("import docxkit, sys; "
             "sys.exit(0 if r'docxkit-mut' in docxkit.__file__ else 1)")
    if _run([sys.executable, "-c", probe], cwd=WORKTREE, env=_env()).returncode:
        sys.exit("the worktree does not win on sys.path — refusing to "
                 "mutate, because the live tree is what would be mutated")


def write_config(module: Path, tests: list[str], config: Path,
                 stem: str = "", fast: bool = False) -> None:
    # `-p pytest_timeout` because autoload is off in `_env` and
    # `--timeout` is that plugin's flag; `-p no:cacheprovider`
    # so a mutant run writes nothing into the worktree.
    pytest_args = ("-q -x -p no:cacheprovider -p pytest_timeout "
                   f"--timeout={MUTANT_SECONDS} " + " ".join(tests))
    command = "python -m pytest " + pytest_args
    timeout = float(MUTANT_SECONDS)
    if fast:
        # The covering tests first, the whole harness behind them — see
        # tools/mutant_tests.py. POSIX separators on purpose: cosmic-ray
        # splits this string with `shlex`, which eats backslashes.
        wrapper = (Path(__file__).resolve().parent
                   / "mutant_tests.py").as_posix()
        command = (f"python {wrapper} --deadline {MUTANT_SECONDS} {stem} "
                   f"{module.as_posix()} -- " + pytest_args)
        # The wrapper ends its pytest at the deadline, so cosmic-ray's own
        # limit sits ABOVE it: on Windows cosmic-ray can end only the
        # wrapper, and then waits for ever on the pytest still holding its
        # pipe (BACKLOG, 2026-09-13).
        timeout += BACKSTOP
    config.write_text(
        "[cosmic-ray]\n"
        f'module-path = "{(WORKTREE / module).as_posix()}"\n'
        f"timeout = {timeout}\n"
        f'test-command = "{command}"\n'
        "excluded-modules = []\n\n"
        "[cosmic-ray.distributor]\nname = \"local\"\n", encoding="utf-8")


def sample(session: Path, keep: int, seed: int) -> None:
    """Mark all but `keep` mutants SKIPPED, reproducibly.

    A seeded sample is a measurement that can be REPEATED: the same draw
    against a later suite is a paired comparison, which is a far stronger
    claim than two independent samples of the same module.

    **Ordered by what the mutant IS, not by its job id.** The ids are
    fresh UUIDs per `init`, and `select job_id from mutation_specs` is
    answered from the primary key's covering index — so the list came
    back in sorted-UUID order, which is a different order every session.
    A seeded sample over it drew a different 120 mutants every time:
    measured 2026-08-19 on `_table_layout`, two draws from the same
    2,720 shared FIVE. Every "before and after" this tool has printed
    for a sampled module was two independent draws, and the promise in
    the paragraph above was not kept until this line was added.
    """
    with contextlib.closing(sqlite3.connect(session)) as con:
        jobs = [r[0] for r in con.execute(
            "select job_id from mutation_specs order by module_path, "
            "start_pos_row, start_pos_col, operator_name, occurrence")]
        if keep >= len(jobs):
            return
        random.seed(seed)
        skip = random.sample(jobs, len(jobs) - keep)
        con.executemany(
            "insert into work_results (job_id, worker_outcome, test_outcome, "
            "output) values (?, 'SKIPPED', 'SKIPPED', '')",
            [(j,) for j in skip])
        con.commit()
    print(f"  sampling {keep} of {len(jobs)} mutants (seed {seed})",
          flush=True)


def progress(session: Path) -> tuple[int, int, int, int]:
    """(killed, survived, FINISHED, planned) — finished, not killed+survived.

    A mutant can also come back INCOMPETENT: cosmic-ray could not even
    run it (the worker raised), which is neither a kill nor a survival
    and is still DONE. Counting only the two outcomes made
    ``--chunks 0`` spin forever on `package.py` — 434 of 435, one
    INCOMPETENT, nothing left for `exec` to run, and the loop asking for
    another chunk every few seconds for two hours (2026-08-17). The tell
    was a sequential sweep that never reached its next module.
    """
    # CLOSED, and that is not tidiness on Windows: an open handle makes
    # `session.unlink()` raise WinError 32, and `--fresh` reads the
    # session before deleting it. Refcount timing decided whether the
    # ordinary re-sample worked.
    with contextlib.closing(sqlite3.connect(session)) as con:
        counts = Counter((r[0] or "PENDING").upper() for r in
                         con.execute("select test_outcome from work_results"))
        total = con.execute(
            "select count(*) from mutation_specs").fetchone()[0]
    planned = total - counts["SKIPPED"]
    finished = sum(n for outcome, n in counts.items()
                   if outcome not in ("SKIPPED", "PENDING"))
    return counts["KILLED"], counts["SURVIVED"], finished, planned


class Discard(NamedTuple):
    """What a `--sample keep --fresh` run would throw away.

    Two numbers because they are worth two different answers. `graded` is
    verdicts — a measurement, and losing one is the regression this guard
    exists for, so it REFUSES. `planned` is a wider plan that has not
    been run yet: discarding it costs the planning time and nothing else,
    so it only warrants a note.
    """

    graded: int                  # verdicts that would be replaced by `keep`
    planned: int                 # a wider plan that would be re-planned


def would_lose(session: Path, keep: int) -> Discard:
    """What a `--sample keep --fresh` run would discard from `session`.

    Both zero when there is nothing to lose: no session, an unreadable
    one, or one no wider than the sample about to replace it.

    **Why this is worth a refusal.** A sample is the right thing to run
    on a 2,757-mutant module when the question is "roughly where is
    this"; it is the wrong thing to leave behind as that module's
    record. On 2026-08-24 `crossrefs.py` stood at 6.9 % measured over the
    WHOLE module — 57 of 822 — and a later `--sample 260` replaced it
    with 9.3 % over 259. `--fresh` discards the session and the sample
    writes a new plan, so 822 mutants' worth of verdicts became 259, the
    run printed a plausible number, and the only trace of the better
    measurement was a sentence in a document nobody diffs against the
    tool's output.

    That is the one failure mode which makes a figure WORSE over time
    while looking like maintenance, and the figures are what a round is
    planned from. Both numbers are in hand before the plan is written,
    so the check costs nothing.

    **An unreadable session is not something to protect.** `--fresh` is
    the documented way to clear a session that went wrong, and a
    zero-byte or truncated db is exactly what one looks like — there is
    one sitting in this repo root. Raising here would put the guard
    between the caller and the recovery it is asking for, so a db that
    cannot be read answers "nothing to lose", which is true.
    """
    if not session.exists():
        return Discard(0, 0)
    try:
        killed, survived, _, planned = progress(session)
    except sqlite3.Error:
        return Discard(0, 0)
    graded = killed + survived
    return Discard(graded if graded > keep else 0,
                   planned if planned > keep and graded <= keep else 0)


def _bounded(cmd: list[str], seconds: int) -> None:
    """Run `cmd` in the worktree for at most `seconds`, then end it — on
    Windows with everything it started.

    `subprocess.run(timeout=)` ends the one process it started, and the
    test command cosmic-ray was running at that moment ran on
    unsupervised. `taskkill /T` walks the tree while cosmic-ray is still
    its root; once cosmic-ray is gone, nothing reaches the children
    (BACKLOG, 2026-09-13). On Linux cosmic-ray puts each test command in a
    session of its own, which a kill from here would not reach either; the
    wrapper's deadline bounds what that leaves.
    """
    proc = subprocess.Popen(cmd, cwd=WORKTREE, env=_env(),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        if _WINDOWS:
            _run(["taskkill", "/PID", str(proc.pid), "/T", "/F"])
        proc.kill()
        proc.wait()


def chunk(module: Path, tests: list[str], config: Path, session: Path,
          seconds: int, *, snapshot: Path | None = None) -> bool:
    """One bounded run. True while there is more to do."""
    con = sqlite3.connect(session)
    cleared = con.execute(
        "delete from work_results where test_outcome is null").rowcount
    con.commit()
    if cleared:
        print(f"  cleared {cleared} row(s) a terminated chunk left "
              f"unfinished", flush=True)

    # From the SNAPSHOT: the plan in the session was built against those
    # bytes, and copying the live file here is how a sweep silently
    # starts measuring an edit made while it ran (see the docstring).
    source = (snapshot / module) if snapshot else (ROOT / module)
    shutil.copy2(source, WORKTREE / module)             # undo any mutation
    if snapshot and (moved := moved_since(snapshot, module, tests)):
        print(f"  NOTE: {', '.join(moved)} changed since this session was "
              f"planned. The figure describes the tree as it was then — "
              f"re-run with --fresh to measure it as it is now.", flush=True)
    print(f"  verifying the unmutated harness ({len(tests)} files)...",
          flush=True)
    started = time.monotonic()
    baseline = _run([sys.executable, "-m", "pytest", "-q", *tests],
                    cwd=WORKTREE, env=_env())
    took = time.monotonic() - started
    if baseline.returncode:
        sys.exit("the UNMUTATED harness fails — refusing to mutate, because "
                 "every mutant would then read KILLED:\n"
                 + baseline.stdout[-2000:])
    if took > BASELINE_SHARE * MUTANT_SECONDS:
        sys.exit(f"the UNMUTATED harness took {took:.1f} s, more than "
                 f"{BASELINE_SHARE:.0%} of the {MUTANT_SECONDS} s deadline "
                 f"every mutant gets — refusing to mutate, because a "
                 f"survivor has to run the whole harness, crosses the "
                 f"deadline on a busy machine, and reads KILLED. The figure "
                 f"would be an artefact. Measure it when the machine is "
                 f"quiet, or with a harness that runs faster.")

    # bounded on purpose: the timeout IS the chunk, and the next call
    # picks up where this one stopped
    _bounded([sys.executable, "-m", "cosmic_ray.cli", "exec",
              str(config), str(session)], seconds)
    killed, survived, done, planned = progress(session)
    graded = killed + survived
    rate = f" ({survived / graded:.1%} survive)" if graded else ""
    other = f", {done - graded} INCOMPETENT" if done > graded else ""
    # flushed, because a chunk is minutes long and these runs are
    # backgrounded: block-buffered stdout makes an hour-long session look
    # like a hung one, and `--report` should be the second question, not
    # the only way to ask the first
    print(f"  {done}/{planned} run — killed {killed}, "
          f"survived {survived}{other}{rate}", flush=True)
    return done < planned


def _stuck(module: Path, snapshot: Path) -> int:
    """Stop a session no chunk can advance: name the mutant the worktree
    was carrying, put the module back, and exit 3."""
    kept, live = snapshot / module, WORKTREE / module
    lines = ["  (the module could not be read)"]
    if kept.is_file() and live.is_file():
        was = kept.read_text(encoding="utf-8").splitlines()
        now = live.read_text(encoding="utf-8").splitlines()
        lines = ([f"  line {i}: {b.strip()}"
                  for i, (a, b) in enumerate(zip(was, now, strict=True), 1)
                  if a != b] if len(was) == len(now)
                 else ["  (the module's length changed)"])
        shutil.copy2(kept, live)
    print("\nSTUCK: a whole chunk ended no mutant, so the next would not "
          "either. The worktree's module when it stopped:\n"
          + "\n".join(lines or ["  (unmutated — it stopped between mutants)"])
          + "\nNothing was graded for it, and the module is restored. "
          "Re-run once the reason is understood.", flush=True)
    return 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module", help="e.g. src/docxkit/edit.py")
    ap.add_argument("--tests", nargs="+", default=[],
                    help="the harness; its COVERAGE bounds the finding, so "
                         "quote it beside any number this produces")
    ap.add_argument("--sample", type=int, default=0,
                    help="run a random N mutants instead of all of them")
    ap.add_argument("--seed", type=int, default=20260816,
                    help="the sample is a measurement: keep the seed to "
                         "compare against a later suite pairwise")
    ap.add_argument("--minutes", type=float, default=9,
                    help="per chunk; each one is restartable")
    ap.add_argument("--chunks", type=int, default=1,
                    help="how many to run now (0 = until finished)")
    ap.add_argument("--fast", action="store_true",
                    help="run the tests that COVER the mutated line "
                         "first, and the whole harness only behind them "
                         "(tools/mutant_tests.py); the verdict is the "
                         "same, the wall clock is not")
    ap.add_argument("--fresh", action="store_true",
                    help="discard an existing session and start over")
    ap.add_argument("--force", action="store_true",
                    help="allow --fresh --sample N to discard a session that "
                         "graded MORE than N mutants; the coarser figure "
                         "then replaces the better one")
    ap.add_argument("--report", action="store_true",
                    help="just print where the session got to")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from harness_map import session_stem  # noqa: PLC0415

    module = Path(args.module)
    stem = session_stem(module)
    config = ROOT / f".mutation-{stem}.toml"
    session = ROOT / f".mutation-{stem}.sqlite"

    if args.report:
        if not session.exists():
            return print(f"no session at {session.name}") or 1
        killed, survived, done, planned = progress(session)
        print(f"{session.name}: {done}/{planned} run — "
              f"killed {killed}, survived {survived}")
        print(f"read it with:\n  python tools/mutation_survivors.py "
              f"{session.name} {module}")
        return 0

    if not args.tests:
        return print("--tests is required: the harness decides which "
                     "mutants CAN be killed") or 2
    snapshot = snapshot_dir(stem)
    # BEFORE the unlink, which is the step that makes it permanent.
    if args.fresh and args.sample and not args.force:
        lost = would_lose(session, args.sample)
        if lost.graded:
            return print(
                f"{session.name} has graded {lost.graded} mutants and "
                f"--sample {args.sample} would replace that with "
                f"{args.sample}. The coarser figure would then be the "
                f"module's record, and nothing afterwards could say a "
                f"better one had existed.\n"
                f"  --report            read what is there\n"
                f"  --fresh --chunks 0  re-measure it WHOLE\n"
                f"  --force             discard it anyway") or 2
        if lost.planned:
            # Not a refusal: no verdict is lost, only the planning time.
            # Said out loud because the figure this produces will be
            # about `args.sample` mutants where one about `lost.planned`
            # was already set up, and nothing downstream records which.
            print(f"  NOTE: {session.name} had a {lost.planned}-mutant plan "
                  f"barely started; --sample {args.sample} re-plans it "
                  f"narrower. No verdict is lost.", flush=True)
    if args.fresh:
        session.unlink(missing_ok=True)
        shutil.rmtree(snapshot, ignore_errors=True)
        (ROOT / f".mutation-{stem}.coverage.json").unlink(missing_ok=True)

    _take_lock()
    _mark_running(stem)
    # BEFORE the worktree is refreshed from the live tree: on a resume
    # the plan is already built, and a module that has changed since
    # makes every offset in it describe a different file.
    if (session.exists() and snapshot.exists()
            and str(module) in moved_since(snapshot, module, args.tests)):
        sys.exit(f"{module} has changed since this session was planned. "
                 f"Its mutants are recorded against the old source, so "
                 f"resuming would grade the wrong edits. Re-run with "
                 f"--fresh.")
    ensure_worktree(module, args.tests)
    if not snapshot.exists():
        take_snapshot(snapshot, module, args.tests)
    covering = ROOT / f".mutation-{stem}.coverage.json"
    if args.fast and not covering.exists():
        print("  recording which tests cover which line...", flush=True)
        _run([sys.executable,
              str(Path(__file__).resolve().parent / "mutant_tests.py"),
              "--build", stem, str(module), "--", "-q", *args.tests],
             cwd=WORKTREE, env=_env())
    write_config(module, args.tests, config, stem=stem, fast=args.fast)
    if not session.exists():
        out = _run([sys.executable, "-m", "cosmic_ray.cli", "init",
                    str(config), str(session)], cwd=WORKTREE, env=_env())
        if out.returncode:
            sys.exit(f"cosmic-ray init failed: {out.stderr.strip()[:400]}")
        if args.sample:
            sample(session, args.sample, args.seed)
    elif args.sample:
        # The draw is planned at `init`, so a `--sample` handed to a
        # RESUME does nothing at all — and used to do it silently, which
        # reads as "I sampled it" against a run that is measuring
        # something else entirely.
        print(f"  NOTE: --sample {args.sample} is not applied here. The draw "
              f"is planned when the session is created, and this run RESUMES "
              f"{session.name} as it was planned. --fresh to re-plan.",
              flush=True)

    more, n = True, 0
    seconds = int(args.minutes * 60)
    last: int | None = None
    while more and (args.chunks == 0 or n < args.chunks):
        more = chunk(module, args.tests, config, session, seconds,
                     snapshot=snapshot)
        n += 1
        # A chunk long enough to end ANY mutant that ended none is stuck,
        # and `--chunks 0` would ask for it again for ever: 2026-09-13's
        # sweep printed 459/460 for seventy minutes (BACKLOG). Judged
        # against the chunk BEFORE, so it reads a session only once a
        # chunk has said there is more to do.
        if more and seconds >= _STUCK_AFTER:
            done = progress(session)[2]
            if done == last:
                return _stuck(module, snapshot)
            last = done
    if more:
        print("\nmore to do — run again, or --chunks 0 to finish. "
              "The tree is clean either way.", flush=True)
    else:
        print(f"\nfinished. Read it with:\n"
              f"  python tools/mutation_survivors.py {session.name} {module}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
