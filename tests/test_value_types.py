"""Which of the package's types are values, and which accumulate.

Two kinds of dataclass live in docxkit and they are used in opposite
ways. A VALUE is an answer — a `Citation`, a `Caption`, an `Issue`, a
`Counts` — handed back from a scan and then passed around a paper's own
code, often into a dict or a set. An ACCUMULATOR is a report being built
up during a walk: `report.issues.append(...)`, `report.linked.append(...)`.

The values are frozen, and that is a decision rather than a detail. A
paper's script holds the answer and hands it on; a value that can be
assigned to would let whatever runs last rewrite what the audit found,
and the two places this was already pinned by hand (`figures.AltText` in
test_alt_text, `wordcount.Counts` in test_wordcount) say exactly that.
Frozen is also what makes them hashable, which several of them are
counted in a `set` for.

`frozen=True` is one keyword and nothing but these two tests reads it:
every `@dataclass(frozen=True)` in the package carried a live mutant
into the 2026-08-19 sweep, one per class, six of them in `comments.py`
alone.
"""
from __future__ import annotations

import dataclasses
import importlib
import pkgutil

import pytest

import docxkit

# Every value type in the package, module by module. A name here is a
# claim that the type is an ANSWER: something a caller may keep, hash or
# compare, and never edit.
VALUES = [
    "batch.Edit",
    "batch.Step",
    "batch.Verdict",
    "_cite_build._Mentions",        # bound once; its report is what moves
    "_cite_grammar.Citation",
    "_cite_grammar.Reference",
    "_table_core.RowsReport",       # a count of what changed, not a builder
    "_table_core.Table",
    "_table_core._Span",
    "comments.Comment",
    "comments.RevisionContext",
    "comments.Thread",
    "crossrefs.Caption",
    "equations.Equation",
    "equations.ProseMath",
    "figures.AltText",
    "figures.Figure",
    "find.Site",                # a survey a caller keeps and compares
    "refstyle.Fix",             # one span and what it should say
    "footnotes.SizeOutlier",
    "placement.Block",          # an exhibit's span, and what moving it costs
    "refstyle.Issue",
    "refstyle.Style",
    "revision.IngestReport",
    "revision.Loss",
    "revision.Paper",
    "revision.PromoteReport",
    "revision.Relabelled",
    "revision.State",
    "revisions.Revision",
    "styles.Resolved",
    "styles.Style",
    "tracked.Unaccepted",
    "tracked.Untracked",
    "wordcount.Counts",
]

# The other kind: filled in during a walk, then read. Listed rather than
# derived, so that a new dataclass has to be put on one side or the
# other deliberately — the same rule `test_harness_map` applies to a new
# test file.
ACCUMULATORS = {
    "batch.Report",
    "_cite_build.LinkAllReport",
    "_cite_build.LinkRestReport",
    "_table_layout.HouseReport",
    "crossrefs.LinkReport",
    "footnotes.FontReport",
    "footnotes.SizeReport",
    "hygiene.SmartenReport",
    "hygiene.SpacingReport",
    "placement.Placement",
    "placement.PlacementReport",
    "probe.Probe",
    "refstyle.ConvertReport",
    "refstyle.RefStyleReport",
    "renumber.ShiftReport",
    "revision.Doubt",
    "revision.ValidateReport",
    "styles.StyleReport",
}


def _dataclasses() -> dict[str, type]:
    """Every dataclass DEFINED in the package, by `module.Name`."""
    found: dict[str, type] = {}
    for info in pkgutil.iter_modules(docxkit.__path__):
        try:
            mod = importlib.import_module(f"docxkit.{info.name}")
        except ImportError:                     # pragma: no cover - optional
            continue
        for name, obj in vars(mod).items():
            if (isinstance(obj, type) and dataclasses.is_dataclass(obj)
                    and obj.__module__ == mod.__name__):
                found[f"{info.name}.{name}"] = obj
    return found


@pytest.mark.parametrize("path", VALUES)
def test_a_value_type_cannot_be_assigned_to(path: str):
    found = _dataclasses()
    assert path in found, f"{path} is gone or has moved — update the list"
    cls = found[path]

    params = cls.__dataclass_params__          # type: ignore[attr-defined]
    assert params.frozen, (
        f"{path} is a value: an answer a caller keeps, and one that can "
        "be assigned to lets whatever runs last rewrite what was found")


def test_every_dataclass_is_a_value_or_an_ACCUMULATOR():
    """A new one has to be put on a side. Reports are built by appending
    to them and are read once; everything else is an answer."""
    listed = set(VALUES) | ACCUMULATORS

    unlisted = sorted(set(_dataclasses()) - listed)

    assert not unlisted, (
        f"{unlisted}: frozen (a value) or listed as an accumulator?")


def test_a_frozen_value_actually_refuses_the_assignment():
    """`frozen=True` is read from the class above; this is the behaviour
    it buys, on one instance, so the parametrised check above is not
    asserting a flag against itself."""
    from docxkit.refstyle import Issue

    issue = Issue("order", "out of order", where="¶4")

    with pytest.raises(dataclasses.FrozenInstanceError):
        issue.where = "¶5"          # type: ignore[misc]
