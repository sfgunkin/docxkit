"""The walk every source-reading test is built on, and its canaries.

A test that reads the package's own source can fail in a way no
assertion catches: it can read NOTHING and report that nothing is wrong.
Four in this suite did (BACKLOG, 2026-09-18) — one of them because
`SRC.glob("*.py")` stops at a directory, so `revision/`'s sixteen halves
were outside every scan the day the module was split.

So the walk is one function, and it is tested here for the two things a
scan has to be able to say: that it found files, and that it found the
ones a reader would be surprised to learn it had missed. A helper with
no canary moves the trap rather than closing it.
"""
from __future__ import annotations

from conftest import PACKAGE, module_name, source_files


def test_the_walk_finds_the_package():
    """The first canary: it read something. A path bug that returns an
    empty list passes every rule written on top of it."""
    found = source_files()

    assert len(found) > 40, f"only {len(found)} modules — is PACKAGE right?"
    assert all(p.suffix == ".py" and p.is_file() for p in found)


def test_the_walk_sees_a_SUBPACKAGES_halves_by_name():
    """The second canary, and the one this helper exists for. Named
    rather than counted: a count goes on passing when a directory drops
    out and another grows."""
    names = {module_name(p) for p in source_files()}

    assert "revision._promote" in names
    assert "revision._build" in names
    assert {n for n in names if n.startswith("revision.")} >= {
        "revision._common", "revision._config", "revision._state"}
    assert "find" in names and "cli" in names, "and the top level too"


def test_the_walk_LEAVES_OUT_the_facade_unless_it_is_asked():
    """`__init__.py` is a surface, not a module with rules of its own —
    and a test that means to read it says so."""
    assert not any(p.name == "__init__.py" for p in source_files())

    withinit = source_files(include_init=True)
    assert PACKAGE / "__init__.py" in withinit
    assert PACKAGE / "revision" / "__init__.py" in withinit


def test_a_module_is_NAMED_the_way_it_is_imported():
    """`path.stem` answers `_promote` for two different files the day a
    second subpackage appears; the dotted name is what a failure can be
    traced from."""
    assert module_name(PACKAGE / "find.py") == "find"
    assert module_name(PACKAGE / "revision" / "_promote.py") == (
        "revision._promote")
