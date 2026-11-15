#!/usr/bin/env python
"""Does an ORACLE reach what this change changed?

    python tools/oracle_reach.py [--base REV] [--verbose]

A unit test runs the case its author thought of; the two oracles run the
writers (`writer_oracle.py`) and the readers (`sweep.py`) over real
manuscripts against the commit before. But each runs only what it names.
On 2026-11-14 a batch rewrote `tables.house`, `crossrefs.link` and
`citations.link_all`, and the writer oracle probed `set_cell` and
`insert_before` and nothing else — run as CONTRIBUTING said, it would
have printed "0 differ" about two writers the batch never touched. The
old `house` pass, it turned out, dropped 72,484 alignments on 911
corpus tables. Nothing said the measurement could not see the change.

This says it. Every function, method, class body and module-level
constant under `src/docxkit` whose code differs from `--base` (comments
and docstrings aside) is CHANGED. Each is then looked up in a static
call graph of the package, walked from the docxkit names the two oracles
call. A change nothing walks to is UNMEASURED: no corpus run can show
what it did, whatever the run prints. Exit 1 lists them, with the public
callers that do reach each one, which is where a probe goes.

The graph over-approximates on purpose: `obj.format()` reaches every
method called `format`, a class reaches all its methods, and a constant
reaches the functions that read it. A false "reached" lets one change
through unmeasured; a false "unreached" fails a sound change and gets
the gate switched off, and that is the worse error for a gate.

`EXEMPT` names what no corpus oracle can run, each with its reason —
the CLI layer, Word automation. An exemption is a decision written down
in review, not a flag on the command line.
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
PACKAGE = "docxkit"
#: The oracles, as source: the docxkit names they reference are the roots.
ORACLES = (HERE / "writer_oracle.py", HERE / "sweep.py")

#: Module -> why no corpus oracle can run it. A change here is reported
#: as exempt, never as a failure.
#: A key ending in "." covers the package under it.
EXEMPT: dict[str, str] = {
    "docxkit.cli": "argument parsing and printing; the commands' engines "
                   "are what the oracles reach, and tests/test_cli*.py "
                   "hold the layer",
    "docxkit.console": "terminal encoding",
    "docxkit.timings": "records gate timings; touches no document",
    "docxkit.word": "drives Microsoft Word through COM, which neither "
                    "oracle starts",
    "docxkit.tracked": "a redline is Word's CompareDocuments; the oracles "
                       "start no Word",
    "docxkit.moves": "a tracked move is made by Word; the oracles start "
                     "no Word",
    "docxkit.pages": "reads a render Word exports",
    "docxkit.repack": "ranks placements by rendering each through Word",
    "docxkit.revision.": "the protocol over ONE paper's files — its "
                         "batch, baseline, ledger and verdicts; a corpus "
                         "of manuscripts has none of them, and "
                         "tests/test_revision*.py run it end to end",
    "docxkit._tracked_gates": "the gates inside `tracked.build`, which "
                              "runs Word's Compare first",
    "docxkit._tracked_report": "what `tracked.build` reports",
    "docxkit.package:next_backup_path": "names a backup FILE on disk; "
                                        "reads and writes no document",
}


def exempt(node: Node) -> str | None:
    """Why `node` (or its module, or a package above it) is exempt."""
    module = node.split(":")[0]
    for key, why in EXEMPT.items():
        if key in (node, module) or (key.endswith(".")
                                     and module.startswith(key)):
            return why
    return None

Node = str          # "docxkit.mod:Qual.name", "docxkit.mod:<NAME>" for a constant


def module_name(path: Path, src: Path = SRC) -> str:
    rel = path.relative_to(src).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return body[1:]
    return body


def _fingerprint(node: ast.AST) -> str:
    """The code of a def or statement, docstrings and comments aside."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef)):
        clone = type(node)(**{f: getattr(node, f) for f in node._fields})
        clone.body = _strip_docstring(node.body)
        if isinstance(clone, ast.ClassDef):
            # A class's own fingerprint is its NON-def statements: fields,
            # class constants. Its methods are nodes of their own.
            clone.body = [s for s in clone.body if not isinstance(
                s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        node = clone
    return ast.dump(node, include_attributes=False)


@dataclass
class Module:
    name: str
    is_package: bool
    tree: ast.Module
    #: qualname -> def node (functions, methods, classes)
    defs: dict[str, ast.AST] = field(default_factory=dict)
    #: constant name -> its module-level assignment
    consts: dict[str, ast.stmt] = field(default_factory=dict)
    #: local alias -> (module, name or None for "the module itself")
    imports: dict[str, tuple[str, str | None]] = field(default_factory=dict)


def _target_names(stmt: ast.stmt) -> list[str]:
    targets: list[ast.expr] = []
    if isinstance(stmt, ast.Assign):
        targets = list(stmt.targets)
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    return [t.id for t in targets if isinstance(t, ast.Name)]


def _collect_imports(mod: Module, tree: ast.AST) -> None:
    pkg = mod.name if mod.is_package else mod.name.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    mod.imports[a.asname] = (a.name, None)
                else:
                    head = a.name.split(".")[0]
                    mod.imports.setdefault(head, (head, None))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg
                for _ in range(node.level - 1):
                    base = base.rpartition(".")[0]
                source = f"{base}.{node.module}" if node.module else base
            else:
                source = node.module or ""
            for a in node.names:
                mod.imports[a.asname or a.name] = (source, a.name)


def parse(name: str, source: str, *, is_package: bool = False) -> Module:
    tree = ast.parse(source)
    mod = Module(name, is_package, tree)
    _collect_imports(mod, tree)

    def walk(body: Iterable[ast.stmt], prefix: str) -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod.defs[prefix + stmt.name] = stmt
            elif isinstance(stmt, ast.ClassDef):
                mod.defs[prefix + stmt.name] = stmt
                walk(stmt.body, f"{prefix}{stmt.name}.")
            elif not prefix:
                for t in _target_names(stmt):
                    mod.consts[t] = stmt
    walk(tree.body, "")
    return mod


def load_tree(src: Path = SRC) -> dict[str, Module]:
    out = {}
    for path in sorted((src / PACKAGE).rglob("*.py")):
        name = module_name(path, src)
        out[name] = parse(name, path.read_text(encoding="utf-8"),
                          is_package=path.name == "__init__.py")
    return out


def load_rev(rev: str) -> dict[str, Module]:
    """The package as it stands at `rev`, from git, without a checkout."""
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", rev,
         f"src/{PACKAGE}"], capture_output=True, text=True, check=True)
    rels = [r for r in listing.stdout.split() if r.endswith(".py")]
    # ONE process for every blob: a `git show` per module was 73 spawns
    # on every gate run, most of its five seconds on Windows.
    batch = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        input="".join(f"{rev}:{r}\n" for r in rels).encode("utf-8"),
        capture_output=True, check=True).stdout
    out, pos = {}, 0
    for rel in rels:
        header_end = batch.index(b"\n", pos)
        header = batch[pos:header_end].split()
        if len(header) != 3:                    # "<name> missing"
            raise RuntimeError(f"git cat-file: {batch[pos:header_end]!r}")
        size = int(header[2])
        blob = batch[header_end + 1:header_end + 1 + size]
        pos = header_end + 1 + size + 1         # the blob's trailing newline
        path = ROOT / rel
        name = module_name(path)
        out[name] = parse(name, blob.decode("utf-8"),
                          is_package=path.name == "__init__.py")
    return out


# ------------------------------------------------------------- changes --


def fingerprints(mods: dict[str, Module]) -> dict[Node, str]:
    out: dict[Node, str] = {}
    for m in mods.values():
        for qual, node in m.defs.items():
            out[f"{m.name}:{qual}"] = _fingerprint(node)
        for const, stmt in m.consts.items():
            # `__version__`, `__all__`: a release stamp and the export
            # list, no behaviour — the `api` gate answers for the second
            if not (const.startswith("__") and const.endswith("__")):
                out[f"{m.name}:<{const}>"] = _fingerprint(stmt)
    return out


def changed(base: dict[str, Module], head: dict[str, Module]) -> list[Node]:
    """Nodes new in `head`, or whose code differs from `base`'s."""
    b, h = fingerprints(base), fingerprints(head)
    return sorted(n for n, fp in h.items() if b.get(n) != fp)


# --------------------------------------------------------------- graph --


class Graph:
    """Static references between the package's defs and constants."""

    def __init__(self, mods: dict[str, Module]) -> None:
        self.mods = mods
        self.methods: dict[str, set[Node]] = defaultdict(set)
        for m in mods.values():
            for qual in m.defs:
                if "." in qual:
                    self.methods[qual.rsplit(".", 1)[1]].add(
                        f"{m.name}:{qual}")
        self.edges: dict[Node, set[Node]] = defaultdict(set)
        self._back: dict[Node, set[Node]] | None = None
        for m in mods.values():
            for qual, node in m.defs.items():
                self.edges[f"{m.name}:{qual}"] |= self._refs(m, node, qual)
            for const, stmt in m.consts.items():
                self.edges[f"{m.name}:<{const}>"] |= self._refs(m, stmt, "")

    def resolve(self, module: str, name: str, depth: int = 0) -> set[Node]:
        """What `name` means in `module`: defs, a constant, a re-export."""
        m = self.mods.get(module)
        if m is None or depth > 12:
            return set()
        if name in m.defs:
            return self._def(m, name)
        if name in m.consts:
            return {f"{module}:<{name}>"}
        if name in m.imports:
            return self._imported(*m.imports[name], depth)
        sub = f"{module}.{name}"
        return {f"<module {sub}>"} if sub in self.mods else set()

    def _imported(self, source: str, attr: str | None,
                  depth: int) -> set[Node]:
        """An import's target: a module, or a name resolved where it lives."""
        if attr is None:
            return {f"<module {source}>"}
        if f"{source}.{attr}" in self.mods:
            return {f"<module {source}.{attr}>"}
        return self.resolve(source, attr, depth + 1)

    def _def(self, m: Module, qual: str) -> set[Node]:
        node = f"{m.name}:{qual}"
        if isinstance(m.defs[qual], ast.ClassDef):
            # A class reaches its methods: `Report(...)` constructs, and
            # `report.format()` reads, and neither names the method's class.
            return {node} | {f"{m.name}:{q}" for q in m.defs
                             if q.startswith(qual + ".")}
        return {node}

    def _refs(self, m: Module, tree: ast.AST, qual: str) -> set[Node]:
        out: set[Node] = set()
        cls = qual.rsplit(".", 1)[0] if "." in qual else None
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                out |= self.resolve(m.name, node.id)
            elif isinstance(node, ast.Attribute):
                base = node.value
                if isinstance(base, ast.Name):
                    if base.id in ("self", "cls") and cls is not None:
                        q = f"{cls}.{node.attr}"
                        if q in m.defs:
                            out |= self._def(m, q)
                            continue
                    for target in self.resolve(m.name, base.id):
                        if target.startswith("<module "):
                            out |= self.resolve(target[8:-1], node.attr)
                # an attribute of anything else: every method of that name
                out |= self.methods.get(node.attr, set())
        out.discard(f"{m.name}:{qual}")
        return out

    def reach(self, roots: Iterable[Node]) -> set[Node]:
        seen: set[Node] = set()
        todo = deque(roots)
        while todo:
            n = todo.popleft()
            if n in seen:
                continue
            seen.add(n)
            if n.startswith("<module "):
                continue
            todo.extend(self.edges.get(n, ()))
            # a constant is reached when a reached def reads it — the edge
            # runs def -> constant already; a constant that names a def
            # (a dispatch table) reaches that def through its own edges
        return seen

    def callers(self, target: Node) -> set[Node]:
        """Public defs from which `target` is reachable."""
        if self._back is None:              # built once, on the first ask
            self._back = defaultdict(set)
            for src, dsts in self.edges.items():
                for d in dsts:
                    self._back[d].add(src)
        back = self._back
        seen, todo = {target}, deque([target])
        while todo:
            n = todo.popleft()
            for p in back.get(n, ()):
                if p not in seen:
                    seen.add(p)
                    todo.append(p)
        # the target's own public spelling counts: a public writer nothing
        # calls is still the place its probe goes
        return {s for n in seen
                if (s := self._public_spelling(n)) is not None}

    def _public_spelling(self, node: Node) -> Node | None:
        """`node` as a paper imports it: itself, or a public re-export.

        `tables.house` is defined in `_table_layout`, and a caller list
        that only knew the definition said "no public caller" about the
        writer a probe has to name.
        """
        if _public(node):
            return node
        module, _, qual = node.partition(":")
        for m in self.mods.values():
            if not _public(f"{m.name}:x"):
                continue
            for alias, (source, attr) in m.imports.items():
                if (attr == qual and source == module
                        and not alias.startswith("_")):
                    return f"{m.name}:{alias}"
        return None


def _public(node: Node) -> bool:
    module, _, qual = node.partition(":")
    return (not qual.startswith(("_", "<"))
            and "." not in qual
            and not any(p.startswith("_") for p in module.split(".")[1:]))


def oracle_roots(graph: Graph, oracles: Iterable[Path] = ORACLES
                 ) -> set[Node]:
    """The docxkit defs and constants the oracle scripts name."""
    roots: set[Node] = set()
    for path in oracles:
        shim = parse(f"<oracle {path.stem}>", path.read_text(encoding="utf-8"))
        graph.mods[shim.name] = shim
        try:
            # what it imports (a probe imports a writer to call it) ...
            for alias in shim.imports:
                roots |= graph.resolve(shim.name, alias)
            # ... and what it names, the way the package's own defs do:
            # `crossrefs.link(...)` through the module, `report.format()`
            # by the method name on whatever object it is
            for node in ast.walk(shim.tree):
                if isinstance(node, ast.Name):
                    roots |= graph.resolve(shim.name, node.id)
                elif isinstance(node, ast.Attribute):
                    roots |= graph.methods.get(node.attr, set())
                    if isinstance(node.value, ast.Name):
                        for t in graph.resolve(shim.name, node.value.id):
                            if t.startswith("<module "):
                                roots |= graph.resolve(t[8:-1], node.attr)
        finally:
            del graph.mods[shim.name]
    return {r for r in roots if r.split(":")[0].startswith(PACKAGE)}


# ---------------------------------------------------------------- main --


@dataclass
class Verdict:
    changed: list[Node]
    reached: list[Node]
    exempt: list[tuple[Node, str]]
    unmeasured: list[tuple[Node, list[Node]]]


def check(base: dict[str, Module], head: dict[str, Module], *,
          oracles: Iterable[Path] = ORACLES) -> Verdict:
    graph = Graph(head)
    reached_set = graph.reach(oracle_roots(graph, oracles))
    v = Verdict(changed(base, head), [], [], [])
    for n in v.changed:
        if n in reached_set:
            v.reached.append(n)
        elif (why := exempt(n)) is not None:
            v.exempt.append((n, why))
        else:
            # the library's own writers first: a CLI command is a caller,
            # but the probe belongs on the engine it calls
            ranked = sorted(graph.callers(n),
                            key=lambda c: (c.startswith("docxkit.cli:"), c))
            v.unmeasured.append((n, ranked[:6]))
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Does an oracle reach what this change changed?")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    v = check(load_rev(args.base), load_tree())
    print(f"{len(v.changed)} changed against {args.base}: {len(v.reached)} "
          f"reached by an oracle, {len(v.exempt)} exempt, "
          f"{len(v.unmeasured)} UNMEASURED")
    if args.verbose:
        for n in v.reached:
            print(f"  reached  {n}")
        for n, why in v.exempt:
            print(f"  exempt   {n} — {why}")
    for n, callers in v.unmeasured:
        via = ", ".join(c.split(":", 1)[1] for c in callers) or "no public caller"
        print(f"  UNMEASURED {n}  (reached from: {via})")
    if v.unmeasured:
        print("No writer probe and no sweep routine reaches these, so no "
              "corpus run can show what the change did. Add a probe to "
              "tools/writer_oracle.py PROBES for the public writer above "
              "(or a routine to sweep.py for a reader), or an EXEMPT entry "
              "in this tool with the reason no oracle can run it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
