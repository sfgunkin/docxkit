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
from conftest import PACKAGE as SRC
from conftest import source_files

import docxkit

ROOT = pathlib.Path(docxkit.__file__).resolve().parents[2]


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


def test_every_module_has_an_ENTRY_so_the_TABLE_can_see_it():
    """The other direction, and the one that fails silently.

    `harness_for` falls back to the files that NAME a module, so a
    module with no entry is still measurable — and invisible.
    `stale_figures` walks this dict, so the table a round is planned
    from simply had no line for it, and "not in the table" reads
    exactly like "nothing to do here".

    Two were, until 2026-08-24: `placement.py`, the largest module in
    the package, carrying the worst figure recorded in it; and
    `batch.py`, 327 lines that had never been measured at all. Neither
    was new — the fallback is how a module gets its FIRST run, not
    somewhere to leave one.
    """
    # Subpackage halves included — they are modules a run mutates like
    # any other. `revision/` arrived on 2026-08-30 and a top-level glob
    # stopped seeing fourteen of them at once, every one silently
    # unmapped, which this test exists to refuse. The walk is
    # `conftest.source_files` since 2026-09-18, so the four tests that
    # read the package share one definition of what is in it; HARNESS
    # keys a module by its path under docxkit/, which is what
    # `relative_to` spells.
    modules = {p.relative_to(SRC).as_posix() for p in source_files()}

    unmapped = sorted(modules - set(HARNESS_MAP.HARNESS))

    assert not unmapped, (
        f"{unmapped} have no entry in HARNESS, so `stale_figures` cannot "
        f"list them and no round will ever pick them. `harness_for` will "
        f"still run them off the files that name them — put that list in "
        f"the map once a run says which files actually reach the module.")


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


@pytest.mark.parametrize("module", sorted(
    m for m in HARNESS_MAP.HARNESS if m.startswith("revision/")))
def test_a_HALF_runs_a_SUBSET_of_the_superset_it_was_measured_against(module):
    """Each half's entry is a claim about `REVISION_SUPERSET`: these are
    the files of it that cover what it covers of the half and kill what
    it kills of the half (see the notes in the map). A file from outside
    that list is not narrowing, it is a different measurement — and the
    figures recorded per half are comparable only with this one.
    """
    outside = sorted(set(HARNESS_MAP.HARNESS[module])
                     - set(HARNESS_MAP.REVISION_SUPERSET))

    assert not outside, (
        f"{module}: {outside} is not in REVISION_SUPERSET, so this entry "
        f"is no longer the measured subset of it — add the file there "
        f"too, with what it was measured to cover or kill")


def test_a_HALF_s_tests_are_named_with_its_FOLDER():
    """`revision/_gates.py` is claimed by `test_revision_gates.py`, the
    way its session is `revision_gates`. The key itself as the stem
    globbed `test_revision/_gates*.py`, found nothing for every half, and
    the gate above held no half to its own test file — harmless while
    all of them ran one superset, and not once they were narrowed."""
    assert HARNESS_MAP.named_after("revision/_gates.py") == [
        "tests/test_revision_gates.py"]
    assert HARNESS_MAP.named_after("revision/_verdict.py") == [
        "tests/test_revision_verdict.py"]


def test_a_HALF_is_not_claimed_by_a_TOP_LEVEL_module_s_tests():
    """`revision/_ingest.py` and `ingest.py` share a basename, and
    `test_ingest.py` is about the second."""
    assert HARNESS_MAP.named_after("revision/_ingest.py") == []
    assert HARNESS_MAP.named_after("ingest.py") == ["tests/test_ingest.py"]


# --- the session name a module measures into -----------------------------


def test_a_TOP_LEVEL_module_keeps_the_session_name_it_has_always_had():
    """49 sessions exist on this machine. Renaming them would orphan
    every figure recorded against them, so the rule for a module beside
    the others is unchanged: drop the leading underscore, nothing more.
    """
    assert HARNESS_MAP.session_stem("edit.py") == "edit"
    assert HARNESS_MAP.session_stem("_table_core.py") == "table_core"
    assert HARNESS_MAP.session_stem("src/docxkit/edit.py") == "edit"


def test_a_SUBPACKAGE_half_keeps_its_folder_in_the_session_name():
    """`revision/` arrived on 2026-08-30 and the basename rule stopped
    being unique the same day."""
    assert HARNESS_MAP.session_stem(
        "revision/_build.py") == "revision_build"
    assert HARNESS_MAP.session_stem(
        "src/docxkit/revision/_losses.py") == "revision_losses"


def test_a_HALF_and_a_TOP_LEVEL_module_of_the_same_name_do_not_collide():
    """`revision/_ingest.py` and `ingest.py` both reduced to `ingest`.

    Stated as the collision rather than as two spellings, because the
    failure is not a crash: the second session to run resumes or
    overwrites the first's database, and `mutation_survivors` then
    pairs it with a `.pristine` holding the OTHER module's source —
    line numbers indexing into a file the run never saw, printed with
    complete confidence.
    """
    assert (HARNESS_MAP.session_stem("revision/_ingest.py")
            != HARNESS_MAP.session_stem("ingest.py"))


def test_EVERY_mapped_module_has_a_session_name_of_its_own():
    """The general form, over the map as it really is — so a future
    subpackage cannot reintroduce the collision unnoticed."""
    stems = [HARNESS_MAP.session_stem(m) for m in HARNESS_MAP.HARNESS]
    clashes = sorted({s for s in stems if stems.count(s) > 1})

    assert not clashes, (
        f"{clashes}: two modules would measure into one session file, "
        f"and the second run silently replaces the first")


def test_a_WINDOWS_path_is_read_the_same_as_a_posix_one():
    """`mutation_session` is handed a `Path`, which stringifies with
    backslashes on this platform; `measure_all` and `stale_figures`
    pass the map's own forward-slash keys."""
    posix = "src/docxkit/revision/_build.py"

    assert HARNESS_MAP.session_stem(pathlib.Path(posix)) == "revision_build"
    assert HARNESS_MAP.session_stem(
        posix.replace("/", chr(92))) == "revision_build"


def test_a_name_of_NOTHING_BUT_underscores_still_has_a_stem():
    """`lstrip("_")` on `_.py` leaves the empty string, and a session
    file called `.mutation-.sqlite` is one every such module shares.

    Two of the three copies of this rule carried the `or` fallback and
    `stale_figures` did not — which is the ordinary fate of a rule
    written out three times, and the reason it is written once now.
    """
    assert HARNESS_MAP.session_stem("_.py") == "_"
    assert HARNESS_MAP.session_stem("revision/_.py") == "revision__"
