"""The layering, which until now lived only in comments.

`_xml` is the bottom (33 modules import it, it imports nothing) and
`errors` sits beside it; `cli` is the top. In between, the order is real
and load-bearing — `import docxkit` must not pay for lxml, pandas,
pywin32 or the comparison's chain, which is why several modules import
inside their functions. Nothing checked any of it.

Written against the standard library rather than `import-linter`: the
contract is small enough to state as data, and a gate that needs no
extra dependency is a gate that actually runs. Function-level imports
count — they are exactly where the cycles hide.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import docxkit

SRC = pathlib.Path(docxkit.__file__).parent

#: Top first. A module may import anything BELOW it and nothing above.
#: Names on one line are siblings and must not import each other, with
#: one exception, `_CYCLE` below.
LAYERS: tuple[tuple[str, ...], ...] = (
    ("cli", "compare", "revision"),
    ("tracked", "export", "wordcount", "renumber", "pages", "probe",
     "refstyle", "testing"),
    ("tables", "crossrefs", "equations", "footnotes", "figures", "ingest"),
    ("citations",),
    ("comments", "body", "guard", "hygiene", "authors"),
    ("edit", "find", "revisions", "styles", "package", "lint", "word"),
    ("_xml", "errors", "console"),
)

#: The one place the layering is genuinely circular, and it is
#: deliberate: `compare` exposes a `main`, `cli` dispatches to it, and
#: `revision.ingest` uses the comparison for its content layers. Each
#: edge is a function-level import for that reason. Pinned as a SET so a
#: fourth module joining the knot fails this test rather than joining
#: quietly.
_CYCLE = frozenset({"cli", "compare", "revision"})

#: A facade and the private modules only it may reach into. The halves
#: exist to keep one file readable, not to widen the surface.
FACADE_HALVES = {
    "citations": ("_cite_grammar", "_cite_audit", "_cite_build",
                  "_cite_repair"),
    "tables": ("_table_core", "_table_layout"),
    "compare": ("_compare_read", "_compare_diff", "_compare_render"),
}

MODULES = {p.stem for p in SRC.glob("*.py") if p.stem != "__init__"}


def _imports(path: pathlib.Path) -> set[str]:
    """Sibling modules this one imports, at ANY depth in the file."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module:          # from .x import y
                out.add(node.module.split(".")[0])
            elif node.level == 1:                        # from . import x
                out.update(a.name for a in node.names)
            elif node.module and node.module.startswith("docxkit."):
                out.add(node.module.split(".")[1])
    return {m for m in out if m in MODULES}


GRAPH = {p.stem: _imports(p) for p in sorted(SRC.glob("*.py"))
         if p.stem != "__init__"}

#: Half of the package is layered; the private halves belong to their
#: facade's layer and are checked by the facade rule instead.
_LAYER_OF = {name: i for i, layer in enumerate(LAYERS) for name in layer}


def test_every_module_is_placed():
    """A module nobody put in a layer is a module this gate ignores."""
    unplaced = sorted(m for m in GRAPH
                      if m not in _LAYER_OF and not m.startswith("_"))
    assert not unplaced, (
        f"{unplaced} are in no layer — add them to LAYERS (and decide "
        f"where they belong) rather than leaving them unchecked")


@pytest.mark.parametrize("module", sorted(_LAYER_OF))
def test_a_module_imports_only_what_is_BELOW_it(module):
    here = _LAYER_OF[module]
    for dep in sorted(GRAPH.get(module, ())):
        if dep.startswith("_") and not dep.startswith("_xml"):
            continue                      # facade halves: see below
        if {module, dep} <= _CYCLE:
            continue                      # the declared knot
        assert _LAYER_OF[dep] > here, (
            f"docxkit.{module} imports docxkit.{dep}, which is at or "
            f"above its layer. Either it belongs lower, or the import "
            f"belongs somewhere else — `import docxkit` pays for every "
            f"edge added here.")


def _tangled() -> set[str]:
    """Every module on a cycle, however long.

    The pairwise reading is not enough and the difference is this
    package: only `cli` and `compare` import each other, while the knot
    is three modules — cli -> revision -> compare -> cli. So this is
    reachability both ways, which is what a cycle actually is.
    """
    reach = {m: set(deps) for m, deps in GRAPH.items()}
    for k in GRAPH:                                 # Warshall, 40 nodes
        for m in GRAPH:
            if k in reach[m]:
                reach[m] |= reach[k]
    return {m for m in GRAPH if m in reach[m]}


def test_the_import_CYCLE_is_still_exactly_the_declared_one():
    """cli -> revision -> compare -> cli is deliberate, and every edge
    of it is a deferred import. A fourth module joining would be an
    accident, and invisible."""
    assert _tangled() == _CYCLE, (
        f"the modules on an import cycle are {sorted(_tangled())}, not "
        f"{sorted(_CYCLE)}")


@pytest.mark.parametrize("facade,halves", sorted(FACADE_HALVES.items()))
def test_a_private_half_is_reached_only_through_its_facade(facade, halves):
    for half in halves:
        importers = {m for m, deps in GRAPH.items() if half in deps}
        allowed = {facade, *halves}
        assert importers <= allowed, (
            f"{sorted(importers - allowed)} import docxkit.{half} "
            f"directly — it exists to keep {facade}.py readable, not to "
            f"widen the surface. Import docxkit.{facade}.")
