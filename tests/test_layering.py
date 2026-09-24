"""The layering, which until now lived only in comments.

`_xml` is the bottom (33 modules import it, it imports nothing) and
`errors` sits beside it; `cli` is the top. In between, the order is real
and load-bearing — `import docxkit` must not pay for lxml, pandas,
pywin32 or the comparison's chain, which is why several modules import
inside their functions. Nothing checked any of it.

The import COST half of that sentence is checked by
`tests/test_import_cost.py` since 2026-08-31, and it had to be: this
file asserted the layering and the sentence about what the layering
buys went on being false for lxml, which `package.py` imported at
module level. What is here is the SHAPE of the graph; what is there is
what the shape was for.

Written against the standard library rather than `import-linter`: the
contract is small enough to state as data, and a gate that needs no
extra dependency is a gate that actually runs. Function-level imports
count — they are exactly where the cycles hide.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from conftest import PACKAGE as SRC
from conftest import source_files

#: Top first. A module may import anything BELOW it and nothing above.
#: Names on one line are siblings and must not import each other, with
#: one exception, `_CYCLE` below.
LAYERS: tuple[tuple[str, ...], ...] = (
    ("cli", "compare", "revision"),
    # reads the ACCEPTED view through `tracked`, and nothing imports it
    # but `cli`
    ("snapshot",),
    ("tracked", "export", "wordcount", "renumber", "pages", "probe",
     "refstyle", "testing", "repack"),
    ("tables", "crossrefs", "equations", "footnotes", "figures", "ingest",
     "placement"),
    ("citations", "exhibits", "sections"),
    ("comments", "body", "paragraph", "guard", "hygiene", "authors",
     "batch"),
    ("edit", "find", "revisions", "styles", "package", "lint", "word"),
    ("_xml", "errors", "console", "timings"),
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
#:
#: BOTTOM FIRST — the tuples are an order, not a list, and the test
#: below holds the halves to it. `citations` used to be spelled here in
#: a different order from the one `test_citations.py` enforced, because
#: nothing read this one as an order; reading it as a set is what let
#: the two disagree unnoticed.
FACADE_HALVES = {
    "citations": ("_cite_grammar", "_cite_repair", "_cite_audit",
                  "_cite_build"),
    "tables": ("_table_core", "_table_layout"),
    "compare": ("_compare_read", "_compare_diff", "_compare_render"),
    # 2026-09-11: the XML gates and the report behind the Word pipeline,
    # which stays in the facade — the suite's fake seam is `tracked._word`
    # and the names `build` reads beside it, rebound on that module.
    "tracked": ("_tracked_gates", "_tracked_report"),
}

#: A facade whose halves are a SUBPACKAGE rather than files beside it.
#: `revision.py` was 3,118 lines and the top of the layering; on
#: 2026-08-30 it became `revision/`, fourteen halves behind
#: `revision/__init__.py`. Same rule, one directory down — and it has to
#: be stated here, because `SRC.glob("*.py")` does not see a directory
#: and the whole module would otherwise have dropped out of every check
#: in this file the day it was split. It did: the cycle test was the
#: only thing that noticed, and only because `revision` is named in
#: `_CYCLE`.
#:
#: BOTTOM FIRST, like FACADE_HALVES.
SUBPACKAGE_HALVES = {
    "revision": ("_common", "_config", "_ledger", "_losses", "_state",
                 "_verdict", "_timing", "_baseline", "_build", "_doctor",
                 "_gates",
                 "_ingest", "_registry", "_init", "_promote", "_validate"),
}

#: The nodes of the graph: every top-level module, plus each subpackage
#: as ONE node (its halves are ordered among themselves further down).
#: Both halves are filters over `conftest.source_files`, which is the
#: package's one walk since 2026-09-18 — the narrowing to the top level
#: is a line written here rather than a property of the glob, which is
#: how `test_part_names` lost a sixth of the package without noticing.
_TOP = [p for p in source_files() if p.parent == SRC]
MODULES = ({p.stem for p in _TOP}
           | {p.parent.name for p in source_files(include_init=True)
              if p.parent != SRC and p.name == "__init__.py"})


def _imports(path: pathlib.Path, *, depth: int = 1) -> set[str]:
    """Sibling modules this one imports, at ANY depth in the file.

    `depth` is how far the file sits below `docxkit/`: a subpackage
    half reaches its siblings with `from ..x import y`, so what counts
    as "one level up" is one dot more.
    """
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level == depth and node.module:      # from .x import y
                out.add(node.module.split(".")[0])
            elif node.level == depth:                    # from . import x
                out.update(a.name for a in node.names)
            elif node.module and node.module.startswith("docxkit."):
                out.add(node.module.split(".")[1])
    return {m for m in out if m in MODULES}


def _package_imports(folder: pathlib.Path) -> set[str]:
    """What a SUBPACKAGE reaches outside itself, over all its halves.

    The union, because the layering question is about `import
    docxkit.revision` — which executes every half — not about any one
    of them. A half deferring an import inside a function is still an
    edge the facade owns.
    """
    out: set[str] = set()
    for path in _halves_of(folder.name):
        out |= _imports(path, depth=2)
    return out - {folder.name}


def _halves_of(facade: str) -> list[pathlib.Path]:
    """The subpackage's own modules, off the shared walk."""
    return [p for p in source_files() if p.parent.name == facade]


GRAPH = {p.stem: _imports(p) for p in _TOP}
GRAPH |= {name: _package_imports(SRC / name)
          for name in sorted(SUBPACKAGE_HALVES)}

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


@pytest.mark.parametrize("facade,halves",
                         sorted(SUBPACKAGE_HALVES.items()))
def test_a_SUBPACKAGE_holds_exactly_the_halves_declared(facade, halves):
    """A half added to `revision/` without a line here is a half in no
    layer — the same hole `test_every_module_is_placed` closes upstairs,
    one directory down."""
    on_disk = tuple(sorted(p.stem for p in _halves_of(facade)))

    assert on_disk == tuple(sorted(halves)), (
        f"docxkit/{facade}/ holds {on_disk}; SUBPACKAGE_HALVES declares "
        f"{tuple(sorted(halves))}. Put the new half in the order, which "
        f"means deciding what it may import.")


@pytest.mark.parametrize("facade,halves",
                         sorted(SUBPACKAGE_HALVES.items()))
def test_a_SUBPACKAGE_half_imports_only_the_halves_below_it(facade, halves):
    """The order INSIDE the subpackage — the reason it is a package.

    `revision.py` was one file, so this order lived only in the reader's
    head and in the section banners. Splitting it is worth nothing if
    the halves may reach each other freely: that is the same 3,118 lines
    with more files.
    """
    folder = SRC / facade
    for i, half in enumerate(halves):
        path = folder / f"{half}.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or node.level != 1:
                continue
            deps = ([node.module.split(".")[0]] if node.module
                    else [a.name for a in node.names])
            for dep in deps:
                if dep not in halves:
                    continue
                assert halves.index(dep) < i, (
                    f"docxkit.{facade}.{half} imports .{dep}, which is "
                    f"not below it. Either it belongs lower, or the "
                    f"import belongs elsewhere.")


@pytest.mark.parametrize("facade,halves", sorted(FACADE_HALVES.items()))
def test_a_HALF_imports_only_the_halves_below_it(facade, halves):
    """The order INSIDE a family, which the layer rule above skips.

    `test_a_module_imports_only_what_is_BELOW_it` steps over any
    dependency whose name starts with an underscore, because the halves
    belong to their facade's layer — so nothing there says
    `_cite_build` may read `_cite_grammar` and not the reverse.

    Two files said it instead, `test_citations.py` and
    `test_compare.py`, each with its own copy of the walk and its own
    spelling of the order. The third family had NO check at all:
    `tables` was split the same way and its halves were never held to
    anything. That is what a per-family copy costs — not drift between
    the copies, which had not happened, but the family nobody wrote one
    for.
    """
    for i, half in enumerate(halves):
        for dep in sorted(GRAPH.get(half, ())):
            assert dep != facade, (
                f"docxkit.{half} imports its own facade docxkit.{facade} "
                f"— that is a cycle, and the halves exist to avoid one")
            if dep in halves:
                assert halves.index(dep) < i, (
                    f"docxkit.{half} imports docxkit.{dep}, which is not "
                    f"below it in {facade}'s halves. Either it belongs "
                    f"lower or the import belongs elsewhere; a layering "
                    f"nobody checks is a layering that will not hold")
