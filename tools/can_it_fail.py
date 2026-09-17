#!/usr/bin/env python
"""Break what a test checks, and see whether the test notices.

    python tools/can_it_fail.py <test id> --in FILE --replace OLD --with NEW
    python tools/can_it_fail.py <test id> --in FILE --insert TEXT --before ANCHOR

One test, named the way pytest names it, and one break. The run is:
the test alone (it must be GREEN), the break applied to one file, the
test alone again, and the file restored with `git checkout` whatever
the answer was.

    0   it can fail   — the test went red on the break
    1   CANNOT FAIL   — the test stayed green, which is the finding
    2   refused, or could not answer

**Why a tool and not a paragraph.** A test that reads source can fail in
a way no assertion catches: it can read nothing, or match nothing, and
both look exactly like a tree with nothing wrong in it. Five in this
suite did (BACKLOG, 2026-09-18), one of them green over a live defect
since the day it was written. Arguing about which ones are real costs an
afternoon; this costs a minute, and the answer is a verdict rather than
an opinion. CONTRIBUTING's "A test that reads SOURCE carries two
canaries" is where the convention lives; this is how to settle it.

**It refuses over a file with uncommitted work in it**, because the
restore is `git checkout` and that would discard the work. The tool is
reached for in the middle of exactly the kind of afternoon where
something is half-written; the refusal says so rather than being clever
about stashing, which is a second way to lose it.

**It pins this checkout's `src` on PYTHONPATH**, for the reason
`tools/gates.py` does: the package is installed editable, so a bare
pytest in a worktree otherwise imports another checkout's source and
answers a question about that one.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def apply_break(text: str, old: str, new: str) -> str | None:
    """`text` with the FIRST `old` replaced, or None if it is not there.

    None rather than the text unchanged: writing the file back as it was
    and reporting a verdict would be a verdict about a break that never
    happened, which is the failure this tool exists to catch, one level
    up.
    """
    if old not in text:
        return None
    return text.replace(old, new, 1)


def verdict(green_before: bool, green_after: bool) -> str:
    """The sentence for the two runs, and it has three cases.

    "already red" is its own, because a test that was failing before the
    break says nothing about the break — and "red afterwards" would read
    as the healthy answer.
    """
    if not green_before:
        return "already red — this answers nothing about the break"
    if green_after:
        return "CANNOT FAIL for this change — the test stayed green"
    return "can fail — the test went red on the break"


def _root() -> Path:
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit("not inside a git repository: the restore is "
                         "`git checkout`, so this needs one")
    return Path(done.stdout.strip())


def _dirty(root: Path, path: Path) -> bool:
    done = subprocess.run(
        ["git", "status", "--porcelain", "--", str(path)],
        cwd=root, capture_output=True, text=True, check=True)
    return bool(done.stdout.strip())


def _restore(root: Path, path: Path) -> None:
    subprocess.run(["git", "checkout", "--", str(path)], cwd=root,
                   check=True, capture_output=True)


def _run_test(root: Path, test: str) -> bool:
    """True when the test PASSED. Its output goes nowhere by design —
    what is being asked is red or green, and a pytest report per run
    buries that in two screens."""
    env = dict(os.environ)
    src = root / "src"
    if src.is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            [str(src), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--no-header", test],
        cwd=root, capture_output=True, text=True, env=env)
    return done.returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="can_it_fail", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("test", help="one test, as pytest names it: "
                                 "tests/test_x.py::test_y")
    ap.add_argument("--in", dest="path", required=True,
                    help="the file to break, relative to the repo root")
    ap.add_argument("--replace", metavar="OLD",
                    help="text to replace (the first occurrence)")
    ap.add_argument("--with", dest="new", default="",
                    help="what to put there; omit to delete OLD")
    ap.add_argument("--insert", metavar="TEXT",
                    help="text to insert, with --before")
    ap.add_argument("--before", metavar="ANCHOR",
                    help="insert --insert in front of this")
    args = ap.parse_args(argv)

    if bool(args.replace) == bool(args.insert):
        ap.error("give either --replace OLD --with NEW, or "
                 "--insert TEXT --before ANCHOR")
    old = args.replace or args.before
    new = args.new if args.replace else f"{args.insert}{args.before}"
    if args.insert and not args.before:
        ap.error("--insert needs --before ANCHOR to say where")

    root = _root()
    path = (root / args.path).resolve()
    if not path.is_file():
        print(f"no such file: {args.path}")
        return 2
    if _dirty(root, path):
        print(f"{args.path} has uncommitted changes, and the restore here "
              f"is `git checkout`, which would discard them. Commit or "
              f"stash first.")
        return 2

    original = path.read_text(encoding="utf-8")
    broken = apply_break(original, old, new)
    if broken is None:
        print(f"{old!r} is not in {args.path} — nothing was broken, so "
              f"there is nothing to report about the test")
        return 2

    print(f"test    {args.test}")
    before = _run_test(root, args.test)
    print(f"before  {'PASSED' if before else 'FAILED'}")
    if not before:
        print(f"result  {verdict(before, before)}")
        return 2
    try:
        path.write_text(broken, encoding="utf-8")
        print(f"break   {args.path}: {old!r} -> {new!r}")
        after = _run_test(root, args.test)
    finally:
        _restore(root, path)
    print(f"after   {'PASSED' if after else 'FAILED'}   (file restored)")
    print(f"result  {verdict(before, after)}")
    return 1 if after else 0


if __name__ == "__main__":
    raise SystemExit(main())
