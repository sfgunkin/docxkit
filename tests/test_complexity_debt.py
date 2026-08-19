"""The six functions over the complexity threshold, named — and only six.

`C901` is selected at 20, and six functions already exceed it. They are
exempted per FILE in `pyproject.toml`, because that is the only scope
ruff offers — and a per-file exemption cannot say "this function only".

Which failed within hours of being written: `insert_in_para` was added
to `edit.py` the same afternoon, came out at 25, and was invisible
because `edit.py` carries the exemption for `replace_in_para`. An
exemption scoped to known debt had silently started covering new code.

So the debt is pinned as a SET here rather than described in a comment.
A new function over the threshold fails this test wherever it lives, and
paying one down fails it too — which is the right way round: the list
should only ever shrink, and shrinking it should be deliberate.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

import docxkit

ROOT = pathlib.Path(docxkit.__file__).parent.parent.parent
MAX_COMPLEXITY = 20

#: function -> its complexity when it was pinned. Everything over
#: :data:`MAX_COMPLEXITY`, package-wide, exemptions ignored.
DEBT = {
    "_cite_audit._audit_findings": 38,
    "lint.lint": 31,
    "_cite_build.link_all": 29,
    "refstyle.audit": 25,
    "edit.replace_in_para": 26,
    "revisions._simulate_where": 24,
}

_LINE = re.compile(r"^(?P<file>.+?):\d+:\d+: C901 `(?P<fn>[^`]+)` "
                   r"is too complex \((?P<n>\d+) > \d+\)$")


def _over_threshold() -> dict[str, int]:
    """Every function over the threshold, ignoring the per-file exemptions.

    `--isolated` is the point: it reads no configuration, so the
    per-file ignores cannot hide anything from this walk.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated",
         "--select", "C901",
         "--config", f"lint.mccabe.max-complexity = {MAX_COMPLEXITY}",
         "--output-format", "concise", "src/"],
        capture_output=True, text=True, cwd=ROOT, check=False)
    if proc.returncode not in (0, 1):                    # 2 = ruff itself
        pytest.skip(f"ruff did not run: {proc.stderr.strip()[:200]}")
    out = {}
    for line in proc.stdout.splitlines():
        if (m := _LINE.match(line.strip())) is not None:
            module = pathlib.Path(m["file"]).stem
            out[f"{module}.{m['fn']}"] = int(m["n"])
    return out


def test_no_function_has_joined_the_debt():
    """The failure this file exists for: a NEW complex function landing
    in a file that already carries the exemption."""
    new = sorted(set(_over_threshold()) - set(DEBT))
    assert not new, (
        f"{new} exceed the complexity threshold and are not pinned. If "
        f"the function is new, split it — the per-file C901 exemption it "
        f"is hiding behind was written for something else. If it is a "
        f"deliberate addition to the debt, add it to DEBT here and to "
        f"pyproject.toml, where the numbers are recorded.")


def test_the_pinned_functions_have_not_grown():
    grown = {name: (DEBT[name], now)
             for name, now in _over_threshold().items()
             if name in DEBT and now > DEBT[name]}
    assert not grown, (
        f"pinned functions grew: {grown}. The recorded number is what a "
        f"later reader measures against; a fix that adds a branch to one "
        f"of these should say so.")


def test_a_paid_debt_is_REMOVED_from_the_list():
    """The list only ever shrinks, and shrinking it is deliberate: a
    stale entry reads as debt that is still there."""
    paid = sorted(set(DEBT) - set(_over_threshold()))
    assert not paid, (
        f"{paid} are no longer over the threshold — delete them from "
        f"DEBT here and from the pyproject comment, and drop the C901 "
        f"per-file ignore if nothing else in that file needs it.")


def test_the_pinned_numbers_match_what_pyproject_records():
    """One list, not two. The comment in pyproject.toml is what a reader
    meets first, and a comment that disagrees with the gate is worse
    than no comment."""
    recorded = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = recorded[recorded.index("# ---- C901"):
                     recorded.index("[tool.ruff.lint.isort]")
                     if "[tool.ruff.lint.isort]" in recorded
                     else recorded.index('"src/docxkit/compare.py"')]
    for name, complexity in DEBT.items():
        fn = name.split(".", 1)[1]
        assert re.search(rf"{re.escape(fn)}\s+{complexity}\b", block), (
            f"pyproject.toml does not record {fn} at {complexity}; the "
            f"comment there and DEBT here have drifted apart")


def test_json_is_importable_for_a_reader_who_wants_the_numbers():
    """A trivial guard on the shape of DEBT, so a typo in a name shows
    here rather than as a mysteriously empty diff."""
    assert json.dumps(DEBT)
    assert all("." in name for name in DEBT), \
        "names are module.function, which is how the walk reports them"
