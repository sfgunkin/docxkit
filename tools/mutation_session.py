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
from collections import Counter
from pathlib import Path
from typing import Any

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


def _take_lock() -> None:
    """Refuse to start while another session holds the worktree."""
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = LOCK.read_text(encoding="utf-8").strip() or "unknown"
        sys.exit(f"another mutation session holds {WORKTREE} (pid {holder}). "
                 f"They share one checkout, so running both makes each read "
                 f"the other's mutations. Wait for it, or delete {LOCK} if "
                 f"it is stale.")
    with os.fdopen(fd, "w") as fh:
        fh.write(str(os.getpid()))
    atexit.register(lambda: LOCK.unlink(missing_ok=True))


def _run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        cmd, text=True, capture_output=True, **kw)
    return proc


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(WORKTREE / "src")
    env["PYTHONIOENCODING"] = "utf-8"      # see the module docstring
    return env


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
    for src in sorted(ROOT.glob("src/docxkit/*.py")):
        shutil.copy2(src, WORKTREE / "src" / "docxkit" / src.name)
    for rel in [str(module), *tests]:
        target = WORKTREE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)

    probe = ("import docxkit, sys; "
             "sys.exit(0 if r'docxkit-mut' in docxkit.__file__ else 1)")
    if _run([sys.executable, "-c", probe], cwd=WORKTREE, env=_env()).returncode:
        sys.exit("the worktree does not win on sys.path — refusing to "
                 "mutate, because the live tree is what would be mutated")


def write_config(module: Path, tests: list[str], config: Path) -> None:
    command = ("python -m pytest -q -x --timeout=30 " + " ".join(tests))
    config.write_text(
        "[cosmic-ray]\n"
        f'module-path = "{(WORKTREE / module).as_posix()}"\n'
        "timeout = 30.0\n"
        f'test-command = "{command}"\n'
        "excluded-modules = []\n\n"
        "[cosmic-ray.distributor]\nname = \"local\"\n", encoding="utf-8")


def sample(session: Path, keep: int, seed: int) -> None:
    """Mark all but `keep` mutants SKIPPED, reproducibly.

    A seeded sample is a measurement that can be REPEATED: the same draw
    against a later suite is a paired comparison, which is a far stronger
    claim than two independent samples of the same module.
    """
    con = sqlite3.connect(session)
    jobs = [r[0] for r in con.execute("select job_id from mutation_specs")]
    if keep >= len(jobs):
        return
    random.seed(seed)
    skip = random.sample(jobs, len(jobs) - keep)
    con.executemany(
        "insert into work_results (job_id, worker_outcome, test_outcome, "
        "output) values (?, 'SKIPPED', 'SKIPPED', '')", [(j,) for j in skip])
    con.commit()
    print(f"  sampling {keep} of {len(jobs)} mutants (seed {seed})",
          flush=True)


def progress(session: Path) -> tuple[int, int, int]:
    con = sqlite3.connect(session)
    counts = Counter((r[0] or "PENDING").upper() for r in
                     con.execute("select test_outcome from work_results"))
    total = con.execute("select count(*) from mutation_specs").fetchone()[0]
    return counts["KILLED"], counts["SURVIVED"], total - counts["SKIPPED"]


def chunk(module: Path, tests: list[str], config: Path, session: Path,
          seconds: int) -> bool:
    """One bounded run. True while there is more to do."""
    con = sqlite3.connect(session)
    cleared = con.execute(
        "delete from work_results where test_outcome is null").rowcount
    con.commit()
    if cleared:
        print(f"  cleared {cleared} row(s) a terminated chunk left "
              f"unfinished", flush=True)

    shutil.copy2(ROOT / module, WORKTREE / module)      # undo any mutation
    print(f"  verifying the unmutated harness ({len(tests)} files)...",
          flush=True)
    baseline = _run([sys.executable, "-m", "pytest", "-q", *tests],
                    cwd=WORKTREE, env=_env())
    if baseline.returncode:
        sys.exit("the UNMUTATED harness fails — refusing to mutate, because "
                 "every mutant would then read KILLED:\n"
                 + baseline.stdout[-2000:])

    # bounded on purpose: the timeout IS the chunk, and the next call
    # picks up where this one stopped
    with contextlib.suppress(subprocess.TimeoutExpired):
        _run([sys.executable, "-m", "cosmic_ray.cli", "exec",
              str(config), str(session)], cwd=WORKTREE, env=_env(),
             timeout=seconds)
    killed, survived, planned = progress(session)
    done = killed + survived
    rate = f" ({survived / done:.1%} survive)" if done else ""
    # flushed, because a chunk is minutes long and these runs are
    # backgrounded: block-buffered stdout makes an hour-long session look
    # like a hung one, and `--report` should be the second question, not
    # the only way to ask the first
    print(f"  {done}/{planned} run — killed {killed}, "
          f"survived {survived}{rate}", flush=True)
    return done < planned


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
    ap.add_argument("--fresh", action="store_true",
                    help="discard an existing session and start over")
    ap.add_argument("--report", action="store_true",
                    help="just print where the session got to")
    args = ap.parse_args()

    module = Path(args.module)
    stem = module.stem.lstrip("_") or module.stem
    config = ROOT / f".mutation-{stem}.toml"
    session = ROOT / f".mutation-{stem}.sqlite"

    if args.report:
        if not session.exists():
            return print(f"no session at {session.name}") or 1
        killed, survived, planned = progress(session)
        print(f"{session.name}: {killed + survived}/{planned} run — "
              f"killed {killed}, survived {survived}")
        print(f"read it with:\n  python tools/mutation_survivors.py "
              f"{session.name} {module}")
        return 0

    if not args.tests:
        return print("--tests is required: the harness decides which "
                     "mutants CAN be killed") or 2
    if args.fresh:
        session.unlink(missing_ok=True)

    _take_lock()
    ensure_worktree(module, args.tests)
    write_config(module, args.tests, config)
    if not session.exists():
        out = _run([sys.executable, "-m", "cosmic_ray.cli", "init",
                    str(config), str(session)], cwd=WORKTREE, env=_env())
        if out.returncode:
            sys.exit(f"cosmic-ray init failed: {out.stderr.strip()[:400]}")
        if args.sample:
            sample(session, args.sample, args.seed)

    more, n = True, 0
    while more and (args.chunks == 0 or n < args.chunks):
        more = chunk(module, args.tests, config, session,
                     int(args.minutes * 60))
        n += 1
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
