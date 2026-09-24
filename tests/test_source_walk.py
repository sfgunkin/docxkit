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


# ------------------------------------------ nothing else walks it flat --

#: Every flat enumeration left in the repository, by (file, receiver),
#: and why the folder it reads is flat. A new one fails
#: `test_no_gate_enumerates_the_package_FLAT` until it is added here with
#: a reason, or rewritten on `source_files()`.
FLAT_OK = {
    ("tests/test_can_it_fail.py", "tools.glob"):
        "tools/ is flat by design, and not a package",
    ("tests/test_optional_audit.py", "src.glob"):
        "a tmp_path fixture holding one module",
    ("tools/harness_map.py", "TESTS.glob"):
        "tests/ is flat: pytest collects it as one rootdir of test_*.py",
    ("tools/kill_check.py", "(LIVE / sub).glob"):
        "tests/ and tools/ are flat; the package goes through mirror_src",
    ("src/docxkit/cli.py", "pkgutil.iter_modules"):
        "the PUBLIC surface: a subpackage is its facade, and its private "
        "halves are exactly what `docxkit api` must not list",
}


def flat_enumerations(source: str) -> list[str]:
    """Each `<x>.glob("*.py")` and `iter_modules(...)` call, named by its
    receiver. Read off the AST, so the comments and docstrings that
    quote the trap — there are eight — are not findings."""
    import ast
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ast.unparse(func)
        py_glob = (isinstance(func, ast.Attribute) and func.attr == "glob"
                   and node.args and isinstance(node.args[0], ast.Constant)
                   and str(node.args[0].value).endswith(".py"))
        if py_glob or name.endswith("iter_modules"):
            found.append(name)
    return found


def test_the_flat_walk_check_sees_both_spellings_and_no_comment():
    """The canary. Three calls in, three out — and the comment and the
    `rglob` beside them are not among them."""
    source = ('# src.glob("*.py") in a comment\n'
              'a = SRC.glob("*.py")\n'
              'b = (root / "x").glob("test_*.py")\n'
              'c = list(pkgutil.iter_modules(docxkit.__path__))\n'
              'd = SRC.rglob("*.py")\n'
              'e = here.glob("*.docx")\n')
    assert flat_enumerations(source) == [
        "SRC.glob", "(root / 'x').glob", "pkgutil.iter_modules"]


def test_no_gate_enumerates_the_package_FLAT():
    """The rule the 2026-08-30 note asked for and nothing enforced.

    A walk that stops at a directory reads a package with a hole in it
    and reports on what it read. Seven tools did it the day `revision/`
    was split, and four more were still doing it on 2026-09-24 — the
    duplicate-pattern gate among them, over a duplicate it could not
    see. The allowlist is small because every other folder here is
    walked through `source_files()`.
    """
    root = PACKAGE.parent.parent
    seen = set()
    for folder in ("src", "tests", "tools"):
        for path in sorted((root / folder).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            for receiver in flat_enumerations(
                    path.read_text(encoding="utf-8")):
                seen.add((rel, receiver))
    assert len(seen) >= len(FLAT_OK) > 0, "the scan read nothing"

    unexplained = sorted(seen - set(FLAT_OK))
    assert not unexplained, (
        "a flat walk — rewrite it on conftest.source_files(), or add it "
        "to FLAT_OK with the reason its folder cannot hold a "
        f"subpackage: {unexplained}")
    assert not set(FLAT_OK) - seen, (
        f"FLAT_OK names a walk that is gone: {sorted(set(FLAT_OK) - seen)}")


def test_a_module_is_NAMED_the_way_it_is_imported():
    """`path.stem` answers `_promote` for two different files the day a
    second subpackage appears; the dotted name is what a failure can be
    traced from."""
    assert module_name(PACKAGE / "find.py") == "find"
    assert module_name(PACKAGE / "revision" / "_promote.py") == (
        "revision._promote")
