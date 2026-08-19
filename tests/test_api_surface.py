"""The package's public surface, held to what it declares.

``py.typed`` is in force, so a name a module defines publicly and does
not list in ``__all__`` is a name Pyright REJECTS in a consumer, and the
fix it suggests is to import a private module instead. That has cost the
papers twice — `edit.RUN_RE`, then `visible_text` and `editable_text` —
and both times the diagnostic was worse advice than the code it flagged.

So this walks the package instead of trusting anyone to remember.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import docxkit

SRC = pathlib.Path(docxkit.__file__).parent
MODULES = sorted(p for p in SRC.glob("*.py")
                 if p.name != "__init__.py" and not p.name.startswith("_"))

#: Namespace-URI shorthands several modules define for themselves. Not
#: API: a caller wants `_xml`'s spelling, not four copies of it — and
#: declaring them would bless the duplication.
NOT_API = {"W", "M", "WP", "MATH"}

#: `cli` is an entry point, not a library surface: its commands are
#: reached through argparse, and every one of them would have to be
#: listed for nothing.
NO_ALL = {"cli.py"}


def _public_names(path: pathlib.Path, *, callables_only: bool = False
                  ) -> tuple[set[str], set[str] | None]:
    """(defined publicly, declared in __all__ or None if there is none).

    `callables_only` drops the module-level CONSTANTS, which is the
    right reading for the facade check below: a half's compiled regexes
    are its workings, and a facade that had to re-export every one of
    them would be a facade over nothing.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    declared = None
    public: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) \
                and not node.name.startswith("_"):
            public.add(node.name)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "__all__":
                    declared = {str(e.value) for e in node.value.elts  # type: ignore[attr-defined]
                                if isinstance(e, ast.Constant)}
                elif (target.id.isupper() and not callables_only
                        and not target.id.startswith("_")):
                    public.add(target.id)
    return public, declared


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_public_name_is_DECLARED(path):
    """Defined public and not in `__all__` = unreachable for a typed
    caller, and reachable only through a private module for anyone
    else."""
    public, declared = _public_names(path)
    if path.name in NO_ALL:
        pytest.skip("an entry point, not a library surface")
    assert declared is not None, f"{path.name} declares no __all__"
    missing = sorted(public - declared - NOT_API)
    assert not missing, (
        f"{path.name} defines {missing} publicly and does not declare "
        f"them — Pyright rejects `from docxkit.{path.stem} import "
        f"{missing[0]}` in a py.typed consumer")


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_everything_DECLARED_can_actually_be_imported(path):
    """The mirror: a name in `__all__` that is not there is an import
    that fails at the point of use rather than here."""
    module = __import__(f"docxkit.{path.stem}", fromlist=["*"])
    for name in getattr(module, "__all__", ()):
        assert hasattr(module, name), \
            f"docxkit.{path.stem}.__all__ names {name}, which is not there"


#: Every module, including the private halves: a positional bool is as
#: bad in `_cite_build.link_all` as in `edit.replace_in_para`, and the
#: papers import both.
ALL_MODULES = sorted(p for p in SRC.glob("*.py") if p.name != "__init__.py")


def _bool_positionals(path: pathlib.Path) -> list[str]:
    """Public functions taking a bool that is not keyword-only."""
    out: list[str] = []

    def check(node: ast.FunctionDef | ast.AsyncFunctionDef,
              owner: str = "") -> None:
        if node.name.startswith("_"):
            return
        args = node.args
        positional = args.posonlyargs + args.args
        offset = len(positional) - len(args.defaults)
        for i, default in enumerate(args.defaults):
            if isinstance(default, ast.Constant) \
                    and isinstance(default.value, bool):
                out.append(f"{owner}{node.name}({positional[offset + i].arg})")

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            check(node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    check(sub, owner=f"{node.name}.")
    return out


@pytest.mark.parametrize("path", ALL_MODULES, ids=lambda p: p.name)
def test_a_BOOL_option_is_always_keyword_only(path):
    """Every flag in this package turns a guard OFF — `allow_hyperlink`,
    `allow_notes`, `grow_link_label`, `normalize`. Passed by position a
    bool says nothing about which guard it just disabled, and the diff
    that introduces it says nothing either.

    This is a gate rather than three tests because it was found three
    times: cosmic-ray mutates the keyword-only marker `*` to the
    positional-only `/`, which is valid Python, and the mutant survived
    in `replace_in_para`, then `insert_in_para`, then `link_rest`. The
    signature is the only place that can refuse it.
    """
    offenders = _bool_positionals(path)
    assert not offenders, (
        f"{path.name}: {offenders} take a bool by position — put a `*` "
        f"before it, or a caller will one day pass True and mean nothing "
        f"by it")


#: The facades and the halves they cover. `citations.py` is 275 lines of
#: which about a hundred are `from _x import y as y`; a hand-maintained
#: re-export list is exactly the thing that quietly falls behind.
FACADES = {
    "citations": ("_cite_grammar", "_cite_audit", "_cite_build",
                  "_cite_repair"),
    "tables": ("_table_core", "_table_layout"),
    "compare": ("_compare_read", "_compare_diff", "_compare_render"),
}


@pytest.mark.parametrize("facade,halves", sorted(FACADES.items()))
def test_a_facade_re_exports_everything_public_behind_it(facade, halves):
    front = __import__(f"docxkit.{facade}", fromlist=["*"])
    for half in halves:
        public, _ = _public_names(SRC / f"{half}.py",
                                  callables_only=True)
        missing = sorted(n for n in public - NOT_API
                         if not hasattr(front, n))
        assert not missing, (
            f"docxkit.{facade} does not re-export {missing} from "
            f"{half} — a caller has to import the private module")


#: Exception types this package defines. A module's contract includes
#: what it RAISES, and that is the one part of it that lives in another
#: module by design.
def _our_exceptions() -> set[str]:
    from docxkit import errors
    return {n for n in dir(errors) if not n.startswith("_")
            and isinstance(getattr(errors, n), type)
            and issubclass(getattr(errors, n), BaseException)}


def _raises(tree: ast.Module, known: set[str]) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        exc = node.exc
        name = (exc.func.id if isinstance(exc, ast.Call)
                and isinstance(exc.func, ast.Name)
                else exc.id if isinstance(exc, ast.Name) else None)
        if name in known:
            out.add(name)
    return out


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_an_exception_a_module_RAISES_is_importable_from_it(path):
    """`except` should name the module whose function raised.

    `docxkit.revision` raised six types and exported none, so a caller
    wrapping `load_paper` had to write `from docxkit.errors import
    ProtocolError` — importing the exception from a different module
    than the function whose contract raises it, and having to know
    `docxkit.errors` exists in order to guess it. Under `py.typed` the
    obvious spelling drew `reportPrivateImportUsage` instead.

    The facade rule above does not cover this and could not: the class
    is DEFINED in `errors` and only RAISED here, so no re-export clause
    reaches it. Exception types are the blind spot, and this is the
    clause that closes the class rather than the instance — the same
    move the `visible_text` entry needed.
    """
    if path.name in NO_ALL:
        pytest.skip("an entry point, not a library surface")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    _public, declared = _public_names(path)
    missing = sorted(_raises(tree, _our_exceptions()) - (declared or set()))
    assert not missing, (
        f"{path.name} raises {missing} and does not export them — a "
        f"caller writing `except` must import from docxkit.errors, a "
        f"module it never called. Add them to __all__.")


# --- the module table in the README --------------------------------------


def _documented_modules() -> set[str]:
    """Every module named in the FIRST cell of a README table row."""
    import re

    readme = (pathlib.Path(__file__).resolve().parents[1]
              / "README.md").read_text(encoding="utf-8")
    names: set[str] = set()
    for line in readme.splitlines():
        if line.startswith("| `"):
            first_cell = line.split("|")[1]
            names.update(re.findall(r"`([\w.]+)`", first_cell))
    return names


def test_every_module_has_a_row_in_the_README_table():
    """The table is the map of the package, and ten modules were not on
    it — `placement`, `probe`, `revision`, `cli`, and the two private
    families the citation and table facades are built from. A module
    nobody can find gets rewritten by the next person who needs it.

    Private ones count: the table already documented `_xml` and the
    three `_compare_*` layers, and a reader following a traceback into
    `_cite_grammar` needs the same one line about what it is for."""
    on_disk = {p.stem for p in SRC.glob("*.py")
               if p.stem not in {"__init__", "__main__"}}

    missing = sorted(on_disk - _documented_modules())
    assert not missing, f"no row in the README table: {missing}"


def test_the_README_table_names_no_module_that_is_GONE():
    """The direction a deletion breaks. A row for a module that no
    longer exists is worse than no row: it sends a reader looking for
    a file, and the search returns nothing to correct them with."""
    on_disk = {p.stem for p in SRC.glob("*.py")}
    documented = {n for n in _documented_modules() if "." not in n}

    gone = sorted(documented - on_disk)
    assert not gone, f"documented, but no such module: {gone}"
