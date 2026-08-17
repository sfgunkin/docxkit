"""The mutation harness map, held to the tree it describes.

`tools/harness_map.py` says which test files exercise each module, and
every figure in CONTRIBUTING's calibration table is a statement about a
module AND that set of files. A renamed test file therefore does not
just break a run — it makes the next number quietly incomparable with
the recorded one, which is the failure this gate exists for.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

import docxkit

ROOT = pathlib.Path(docxkit.__file__).resolve().parents[2]
SRC = ROOT / "src" / "docxkit"


def _harness_map():
    spec = importlib.util.spec_from_file_location(
        "harness_map", ROOT / "tools" / "harness_map.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARNESS_MAP = _harness_map()


@pytest.mark.parametrize("module", sorted(HARNESS_MAP.HARNESS))
def test_a_mapped_module_still_exists(module):
    assert (SRC / module).is_file(), f"{module} is not a module any more"


@pytest.mark.parametrize("module,files", sorted(HARNESS_MAP.HARNESS.items()))
def test_every_test_file_in_a_harness_exists(module, files):
    missing = [f for f in files if not (ROOT / f).is_file()]

    assert not missing, (
        f"{module}'s harness names {missing}, which is gone or renamed — "
        f"a run against the rest is not comparable with the recorded one")


def test_a_module_with_no_entry_falls_back_to_what_NAMES_it():
    """The fallback is what keeps a new module measurable at all; it is
    a starting point, not a checked harness."""
    found = HARNESS_MAP.harness_for("styles.py")     # deliberately unmapped

    assert "tests/test_styles.py" in found


def test_a_module_nothing_names_is_an_ERROR_not_an_empty_run():
    """An empty --tests would report every mutant as killed, because a
    suite of nothing passes."""
    with pytest.raises(SystemExit, match="no harness"):
        HARNESS_MAP.harness_for("no_such_module.py")


@pytest.mark.parametrize("module", sorted(HARNESS_MAP.HARNESS))
def test_a_test_file_NAMED_after_a_module_is_in_its_harness(module):
    """`tests/test_tables_update.py` was missing from `_table_core`'s
    entry, and the sweep came back with 216 survivors in `update` and
    the module reported as the worst in the package — because the file
    that tests it was not in the run.

    A test file named after a module is a claim about what it covers.
    Answer it: put it in the entry, or list it in EXCLUDED with the
    reason (the layout half's fixtures are slow and cover the other
    module, which is a reason).
    """
    entry = set(HARNESS_MAP.HARNESS[module])
    excluded = set(HARNESS_MAP.EXCLUDED.get(module, ()))
    named = set(HARNESS_MAP.named_after(module))

    assert named <= entry | excluded, (
        f"{module}: {sorted(named - entry - excluded)} is named after it "
        f"and is neither in its harness nor excluded — a run without it "
        f"invents survivors in whatever it covers")
