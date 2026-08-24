"""`tools/verify_committed.py` — the gate that reads the COMMIT.

Every other gate reads the working copy, and on 2026-08-24 that was a
different file: `_build_args` was called by a committed `main()` and
defined only in an unstaged edit, so for two commits the whole CLI
raised NameError for anyone holding only the commit, while five green
gates said nothing. The property under test is the one that makes this
gate worth having — a fix present in the tree you are holding does NOT make a
broken commit pass — and it is tested against the real history rather
than a fixture, because the fixture would be the thing that got it
wrong.
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
from verify_committed import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ROOT,
    check,
    export,
)

#: The first of the two commits that shipped the broken CLI. Immutable,
#: so pinning it is safe — but a clone made with `--depth` will not have
#: it, and neither will a rewritten history, so its absence is a skip.
BROKEN = "f3a6fd4"


def _have(ref: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"],
                          cwd=ROOT, capture_output=True,
                          check=False).returncode == 0


def test_HEAD_imports_and_builds_its_parsers():
    """The gate's own subject. A red line here means the last commit
    cannot be used by anyone who has only the commit."""
    assert check("HEAD") == []


@pytest.mark.skipif(not _have(BROKEN), reason="shallow or rewritten history")
def test_a_defect_the_WORKING_tree_HIDES_is_still_found():
    """The whole reason the gate exists, and the single change that
    would silently undo it: `git archive <ref>` reads the commit, while
    `git checkout-index` reads the index and a plain read reads the
    working copy. Under either of those this assertion passes for the
    wrong reason, because the definition is right there on disk."""
    live = (ROOT / "src" / "docxkit" / "cli.py").read_text(encoding="utf-8")
    assert "def _build_args" in live, (
        "the working copy has the definition — that is the premise")

    (problem,) = check(BROKEN)

    assert "does not build its parsers" in problem
    assert "_build_args" in problem, problem


@pytest.mark.skipif(not _have(BROKEN), reason="shallow or rewritten history")
def test_the_export_is_the_REF_and_not_the_checkout(tmp_path):
    """`export` is the half that could drift on its own."""
    export(BROKEN, tmp_path)
    was = (tmp_path / "src" / "docxkit" / "cli.py").read_text(encoding="utf-8")

    assert "_build_args(r)" in was, "the calls were committed"
    assert "def _build_args" not in was, "the definition was not"
