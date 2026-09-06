"""The functions over the complexity threshold, named — and only those.

`C901` is selected at 20. Five functions exceeded it, exempted per FILE
in `pyproject.toml`, because that is the only scope ruff offers — and a
per-file exemption cannot say "this function only".

Which failed within hours of being written: `insert_in_para` was added
to `edit.py` the same afternoon, came out at 25, and was invisible
because `edit.py` carries the exemption for `replace_in_para`. An
exemption scoped to known debt had silently started covering new code.

So the debt is pinned as a SET here rather than described in a comment.
A new function over the threshold fails this test wherever it lives, and
paying one down fails it too — which is the right way round: the list
should only ever shrink, and shrinking it should be deliberate.

**It is empty now**, and that is a stronger gate than a short list, not
a reason to delete this file: `_over_threshold` walks the package with
`--isolated`, so with nothing pinned the assertion below reads "no
function in docxkit exceeds 20", exemptions and all. The last five were
paid down on 2026-09-03 (see the C901 note in `pyproject.toml` for what
each became). The next function to cross the line fails here, and adding
it back to DEBT is then a deliberate act with a number attached.

**And a DATE attached, which is the part that was missing.** The gate is
one-directional on purpose — it fires when a pin GROWS, never when one
shrinks — because demanding exact equality would turn every incidental
simplification red, and a build that goes red for making code simpler
teaches people to edit the number without reading it. The cost of that
choice is that a pin can rot downward in silence, and it did: measured
on 2026-09-03, three of the five entries then pinned were wrong
(`_cite_audit._audit_findings` 31 against 30, `refstyle.audit` 26
against 25, `edit.replace_in_para` 26 against 24). All three had been
simplified under the pin and none of them moved it. `replace_in_para`
carried a number 2 too high for ten days, which is the one that matters
— a reader deciding whether a split is worth it starts from the
recorded figure, and there it overstated the job.

A date does not close that gap; it makes it legible. A pin now says
WHEN it was true, so a reader meeting a nine-month-old number knows to
re-measure before trusting it, and `python tools/complexity_pins.py`
re-measures and prints the dict to paste back.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
from typing import NamedTuple

import pytest

import docxkit

ROOT = pathlib.Path(docxkit.__file__).parent.parent.parent
MAX_COMPLEXITY = 20


class Pin(NamedTuple):
    """A complexity number and the day somebody actually measured it.

    The date is not decoration. The number is described below as "what a
    later reader measures against", and a bare integer cannot say
    whether it was measured this week or last spring — which is how
    three of them came to overstate their functions for ten days.
    """

    complexity: int
    measured: str  #: ISO `YYYY-MM-DD`, the day the walk was run


#: function -> its complexity when it was pinned, and when that was.
#: Everything over :data:`MAX_COMPLEXITY`, package-wide, exemptions
#: ignored. Empty: see the module docstring. The next entry looks like
#:
#:     "edit.replace_in_para": Pin(24, "2026-09-03"),
#:
#: and `python tools/complexity_pins.py` writes that line for you.
DEBT: dict[str, Pin] = {}

_LINE = re.compile(r"^(?P<file>.+?):\d+:\d+: C901 `(?P<fn>[^`]+)` "
                   r"is too complex \((?P<n>\d+) > \d+\)$")

_REMEASURE = "re-measure with `python tools/complexity_pins.py`"


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
        f"deliberate addition to the debt, add it to DEBT here as "
        f"Pin(<complexity>, '<today>') and to pyproject.toml, where the "
        f"numbers are recorded. {_REMEASURE}.")


def test_the_pinned_functions_have_not_grown():
    grown = {name: (f"{DEBT[name].complexity} @ {DEBT[name].measured}", now)
             for name, now in _over_threshold().items()
             if name in DEBT and now > DEBT[name].complexity}
    assert not grown, (
        f"pinned functions grew: {grown}. The recorded number is what a "
        f"later reader measures against; a fix that adds a branch to one "
        f"of these should say so, and move the date with the number. "
        f"{_REMEASURE}.")


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
    than no comment. The DATE is checked with the number, for the same
    reason: a reader who meets the comment first and the test never
    would otherwise get the figure without its age."""
    recorded = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = recorded[recorded.index("# ---- C901"):
                     recorded.index("[tool.ruff.lint.isort]")
                     if "[tool.ruff.lint.isort]" in recorded
                     else recorded.index('"src/docxkit/compare.py"')]
    for name, pin in DEBT.items():
        fn = name.split(".", 1)[1]
        # The backtick is optional because the comment around it wraps
        # function names in one — `edit.replace_in_para` 24 — and a gate
        # that refuses the file's own prose style teaches nothing.
        anchor = rf"{re.escape(fn)}`?\s+{pin.complexity}\b"
        assert re.search(anchor, block), (
            f"pyproject.toml does not record {fn} at {pin.complexity}; the "
            f"comment there and DEBT here have drifted apart")
        assert re.search(rf"{anchor}[^\n]*{re.escape(pin.measured)}",
                         block), (
            f"pyproject.toml records {fn} at {pin.complexity} without the "
            f"date DEBT gives it ({pin.measured}) — write the measurement "
            f"date on the same line, so the comment says how old the "
            f"number is")


def test_every_pin_says_WHEN_it_was_measured():
    """The gap this shape closes. A pin that shrinks stays green — by
    design — so the only thing standing between a reader and a stale
    number is knowing how old it is."""
    for name, pin in DEBT.items():
        assert isinstance(pin, Pin), (
            f"{name} is pinned as {pin!r}; it wants "
            f"Pin(<complexity>, '<YYYY-MM-DD>') so the number carries "
            f"its date")
        try:
            when = dt.date.fromisoformat(pin.measured)
        except ValueError:
            pytest.fail(f"{name} records {pin.measured!r}, which is not an "
                        f"ISO date — write it YYYY-MM-DD, the day the walk "
                        f"was actually run")
        assert when <= dt.date.today(), (
            f"{name} claims it was measured on {pin.measured}, which has "
            f"not happened yet — the date is the day the walk was run, "
            f"not the day the debt is meant to be paid")


def test_json_is_importable_for_a_reader_who_wants_the_numbers():
    """A trivial guard on the shape of DEBT, so a typo in a name shows
    here rather than as a mysteriously empty diff."""
    assert json.dumps(DEBT)
    assert all("." in name for name in DEBT), \
        "names are module.function, which is how the walk reports them"
