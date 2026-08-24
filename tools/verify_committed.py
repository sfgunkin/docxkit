#!/usr/bin/env python
"""Does the COMMITTED tree work, or only the one you are holding?

Every other gate reads the file the author has open. In a working tree
shared by two sessions that is a different file from the one the commit
contains, and on 2026-08-24 the difference was the whole CLI: an earlier
split-staging committed both calls to `_build_args` and left the
definition unstaged. Anyone holding only the commit would then have got
NameError from `docxkit <anything>`, for the two commits this script —
run backwards over the history — dates to f3a6fd4..01b1c7e, while every
gate here stayed green, because each of them read the working copy,
which had the function. The tip was repaired before the branch was
pushed, which was luck about timing rather than anything a gate did.

Nothing that reads the working tree can see that, however carefully it
reads. This exports a ref into a temp directory and asks two questions
of the EXPORT: does every module import, and does the CLI build its
parsers. The second is the one that mattered — `_build_args` is called
while `main()` declares subcommands, so the module imported fine and
only an actual invocation failed.

    python tools/verify_committed.py [--ref HEAD]

`--ref` takes anything `git archive` does, so a rebase can check each
commit it is about to keep.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docxkit.console import utf8_stdout

ROOT = Path(__file__).resolve().parents[1]


def export(ref: str, dest: Path) -> None:
    """The ref's tree, as committed, in `dest`.

    `git archive` rather than `checkout-index`, which reads the INDEX —
    a staged fix would hide the very defect this looks for. `filter`
    is "data": an archive of this repo holds no links or devices, and
    the default is a DeprecationWarning on 3.14 that the gate would
    report as output nobody can act on.
    """
    tar = subprocess.run(["git", "archive", ref], cwd=ROOT, check=True,
                         stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        tf.extractall(dest, filter="data")


def _run(argv: list[str], cwd: Path, env: dict[str, str]
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, env=env, text=True,
                          capture_output=True, encoding="utf-8",
                          errors="replace")


def check(ref: str = "HEAD") -> list[str]:
    """Everything wrong with the committed tree, in the order found."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        export(ref, tree)
        env = {**os.environ, "PYTHONPATH": str(tree / "src"),
               "PYTHONIOENCODING": "utf-8"}

        # Import first: a module that cannot be imported makes the CLI
        # check report the same fault in a longer traceback.
        names = sorted(p.stem for p in (tree / "src" / "docxkit").glob("*.py")
                       if p.stem != "__init__")
        script = "import importlib\n" + "".join(
            f"importlib.import_module('docxkit.{n}')\n" for n in names)
        got = _run([sys.executable, "-c", script], tree, env)
        if got.returncode:
            problems.append(f"{ref}: a module does not import\n"
                            + got.stderr.strip()[-800:])

        # Then the CLI, which is where a name used only inside `main()`
        # first gets looked up.
        got = _run([sys.executable, "-m", "docxkit.cli", "--help"], tree, env)
        if got.returncode:
            problems.append(f"{ref}: the CLI does not build its parsers\n"
                            + (got.stderr or got.stdout).strip()[-800:])
    return problems


def main() -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Does the COMMITTED tree work, or only the one you "
                    "are holding?")
    ap.add_argument("--ref", default="HEAD",
                    help="what to check; anything git archive takes")
    args = ap.parse_args()

    problems = check(args.ref)
    for p in problems:
        print(p)
    if not problems:
        print(f"{args.ref}: imports and the CLI build clean")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
