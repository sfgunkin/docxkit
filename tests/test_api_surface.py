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
