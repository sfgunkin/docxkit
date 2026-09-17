"""Which `X | None` in this package can actually BE None — and who guards it.

An Optional the constructor cannot produce is a claim about the code that
is not true: every reader grows an `is not None` branch nothing can take,
mutation testing cannot tell that branch from its absence, and the real
contract hides behind it (`revision/_promote.py`, `PromoteReport.redline`,
2026-08-24 — the second of that shape found in `cmd_revision_*` in one
afternoon).

Answers the mechanical half over `src/docxkit`:

* a CLASS FIELD annotated Optional — does any constructor call pass
  something that can be None, leave a None default unfilled, assign None
  to it later, or `replace(..., field=None)`?
* a FUNCTION RETURN annotated Optional — is there a bare `return`, a fall
  off the end, or a `return` of something that can be None?

"Can be None" is a least fixpoint over the whole package, so evidence
only ever grows: a literal None, a local assigned from something
optional, a call to a package function that can return None, `re.search`
and friends, an attribute of a field this pass has already shown can be
None. A candidate printed here is one nothing makes None.

**The six rules that took it from ten candidates to one.** Nine of the
first ten were this tool's ignorance rather than the code's, and each
gap is a fact about THIS codebase that a reading by eye gets wrong the
same way. They are the reason the pass is worth more than a grep:

1. lxml navigation is optional. `getnext()` on the last child is None,
   so `_next_content` returns None and `_paragraph_or_table(el)` is
   passed one — three candidates, all of them wrong.
2. An optional `@property` is READ as an attribute. `rep.landings[i].drift`
   is `Landing.drift`, whose body returns None when the mention was
   found on no sheet (`Move.drift_before`).
3. `cls(...)` in a classmethod is a constructor. `_Scaffold.read` builds
   its own class that way, with `date_utc=utc.group(1) if utc else None`.
4. A tuple unpacked from a call takes its Optionals SLOT BY SLOT:
   `printed, corner = _printed_number(...)` returns
   `tuple[int | None, str | None]`, and `Sheet.printed` is the first of
   them.
5. So does an indexed one — `self.explain(prop, ...)[0]` is what
   `Cascade.of` returns.
6. A loop variable inherits the container's element type:
   `for x, index in zip(found, mentions)` over `mentions: list[int | None]`
   is how `_mention_sheet(index)` comes to be passed None.

**What it cannot see.** It reads syntax, not semantics: it does not know
which branch of a caller runs, it resolves calls by their plain name
(two functions of one name are one to it), it treats an attribute by
name alone (two classes with a `source` field share an answer), and it
cannot see a value arriving from outside what it was given — which is
why `--callers` exists and why a public class's Optional is a contract
rather than a finding. Assignments are read flow-insensitively: a name
assigned None anywhere in a body can be None everywhere in it. Every
one of those errs towards "this CAN be None", so the pass under-reports
rather than accusing.

**What it counts.** Only a candidate something READS as optional — a
field with an `is None` guard, a return a caller tests, a parameter its
own body tests. An Optional nobody reads that way has misled no one yet,
and failing on it would fail every Optional written before the test that
exercises it. That is the difference between this gate and a toll.

    python tools/optional_audit.py [--all] [--callers DIR] [PATH ...]

Exit code is the number of those, so `--callers tests` is a gate: with
the suite counted as a caller the expected answer here is 0.
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = next((p for p in (Path(__file__).resolve().parents[1], Path.cwd())
             if (p / "src" / "docxkit").is_dir()), Path.cwd())
#: Calls whose whole point is that they may find nothing: the standard
#: library's, and lxml's tree navigation — `getnext()` on the last child
#: is None, and a walk that ends there is a genuine Optional however the
#: annotation of the caller reads.
NONE_RETURNING = frozenset({"search", "match", "fullmatch", "get", "getattr",
                            "next", "pop", "find_one",
                            "getnext", "getprevious", "getparent", "find",
                            "findtext"})


def _rel(path: Path) -> str:
    """A path as the repo reads it, whether or not it was given absolute."""
    here = path if path.is_absolute() else (Path.cwd() / path)
    try:
        return here.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_optional(node: ast.expr | None) -> bool:
    """Does this annotation admit None? `X | None`, `Optional[X]`, `None`."""
    if node is None:
        return False
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return is_optional(node.left) or is_optional(node.right)
    if isinstance(node, ast.Subscript):
        head = ast.unparse(node.value).split(".")[-1]
        if head == "Optional":
            return True
        if head == "Union":
            parts = (node.slice.elts if isinstance(node.slice, ast.Tuple)
                     else [node.slice])
            return any(is_optional(el) for el in parts)
    return False


@dataclass
class Field:
    """One Optional field of one dataclass or NamedTuple."""

    cls: str
    name: str
    annotation: str
    file: str
    line: int
    default_is_none: bool
    order: int
    why: str = ""                 # how it comes to be None; "" = nothing does


@dataclass
class Func:
    """One function whose return annotation admits None."""

    name: str
    file: str
    line: int
    returns: str
    why: str = ""


@dataclass
class Param:
    """One Optional parameter of one function, and who tests it."""

    func: str
    name: str
    annotation: str
    file: str
    line: int
    order: int
    default_is_none: bool
    public: bool
    guards: list[str] = field(default_factory=list)
    why: str = ""


@dataclass
class Site:
    """One argument of one constructor call — or an omitted one."""

    cls: str
    fieldname: str
    expr: ast.expr | None         # None: the field was left to its default
    where: str
    scope: str


@dataclass
class Scope:
    """One function body: what it assigns, what it returns."""

    assigns: list[tuple[list[str], ast.expr]] = field(default_factory=list)
    returns: list[ast.expr | None] = field(default_factory=list)
    #: parameters that arrive None — annotated Optional, or defaulting to
    #: None. A caller's None reaches a constructor through one of these.
    optional_params: set[str] = field(default_factory=set)
    #: `a, b = f()`: (names, callee, annotation index) per position
    unpacks: list[tuple[str, str, int]] = field(default_factory=list)
    #: `for x in xs` / `for a, b in zip(xs, ys)`: (target, iterable)
    loops: list[tuple[ast.expr, ast.expr]] = field(default_factory=list)
    #: names holding a CONTAINER of optionals — `list[int | None]`, or a
    #: comprehension over something optional
    containers: set[str] = field(default_factory=set)


def _dataclass_like(node: ast.ClassDef) -> bool:
    return (any("dataclass" in ast.unparse(d) for d in node.decorator_list)
            or any(ast.unparse(b).split(".")[-1] in ("NamedTuple", "TypedDict")
                   for b in node.bases))


def _always_true(test: ast.expr) -> bool:
    return isinstance(test, ast.Constant) and bool(test.value)


def falls_off(body: list[ast.stmt]) -> bool:
    """Can control reach the end of `body` — an implicit `return None`?"""
    for stmt in body:
        if isinstance(stmt, ast.Return | ast.Raise | ast.Continue | ast.Break):
            return False
        if (isinstance(stmt, ast.If) and stmt.orelse
                and not falls_off(stmt.body)
                and not falls_off(stmt.orelse)):
            return False
        if (isinstance(stmt, ast.While) and _always_true(stmt.test)
                and not any(isinstance(n, ast.Break)
                            for n in ast.walk(stmt))):
            return False
        if (isinstance(stmt, ast.With | ast.AsyncWith)
                and not falls_off(stmt.body)):
            return False
        if (isinstance(stmt, ast.Match) and stmt.cases
                and all(not falls_off(case.body) for case in stmt.cases)):
            return False
    return True


def _tests_of(node: ast.AST, name: str) -> list[str]:
    """Every `name is None`, `if name:` and `if not name:` in one body."""
    out: list[str] = []
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Compare) and len(sub.ops) == 1
                and isinstance(sub.ops[0], ast.Is | ast.IsNot)
                and isinstance(sub.left, ast.Name) and sub.left.id == name
                and isinstance(sub.comparators[0], ast.Constant)
                and sub.comparators[0].value is None):
            out.append(f"line {sub.lineno}: {ast.unparse(sub)[:60]}")
        if (isinstance(sub, ast.If) and isinstance(sub.test, ast.Name)
                and sub.test.id == name):
            out.append(f"line {sub.lineno}: if {name}:")
        if (isinstance(sub, ast.UnaryOp) and isinstance(sub.op, ast.Not)
                and isinstance(sub.operand, ast.Name)
                and sub.operand.id == name):
            out.append(f"line {sub.lineno}: not {name}")
    return out


class Collect(ast.NodeVisitor):
    """One module: its Optional fields and functions, its calls and scopes."""

    def __init__(self, path: Path) -> None:
        self.rel = _rel(path)
        self.fields: list[Field] = []
        self.funcs: dict[str, Func] = {}
        self.params: list[Param] = []
        self.sites: list[Site] = []
        self.scopes: dict[str, Scope] = defaultdict(Scope)
        self.classes: set[str] = set()
        self.stack: list[str] = []
        #: every function's return annotation, for unpacked tuples
        self.returns_of: dict[str, ast.expr | None] = {}
        #: `@property` names — read as attributes, so an optional one makes
        #: `x.drift` optional wherever it is read
        self.props: set[str] = set()
        #: `self.x = ...` attributes: (name, value, scope)
        self.self_attrs: list[tuple[str, ast.expr, str]] = []

    @property
    def scope(self) -> str:
        return f"{self.rel}:{'.'.join(self.stack) or '<module>'}"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if _dataclass_like(node):
            self.classes.add(node.name)
            order = 0                      # the position in __init__
            for stmt in node.body:
                if not (isinstance(stmt, ast.AnnAssign)
                        and isinstance(stmt.target, ast.Name)):
                    continue
                if is_optional(stmt.annotation):
                    self.fields.append(Field(
                        cls=node.name, name=stmt.target.id,
                        annotation=ast.unparse(stmt.annotation),
                        file=self.rel, line=stmt.lineno,
                        default_is_none=isinstance(stmt.value, ast.Constant)
                        and stmt.value.value is None, order=order))
                order += 1
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.returns_of[node.name] = node.returns
        args = node.args
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        defaults = dict(zip([a.arg for a in [*args.posonlyargs, *args.args]
                             ][-len(args.defaults):] if args.defaults else [],
                            args.defaults, strict=True))
        defaults |= {a.arg: d for a, d in zip(args.kwonlyargs,
                                              args.kw_defaults, strict=True)
                     if d is not None}
        for order, arg in enumerate(every):
            default = defaults.get(arg.arg)
            none_default = (isinstance(default, ast.Constant)
                            and default.value is None)
            if is_optional(arg.annotation) or none_default:
                self.scopes[self.scope].optional_params.add(arg.arg)
            if (isinstance(arg.annotation, ast.Subscript)
                    and any(is_optional(el) for el in (
                        arg.annotation.slice.elts
                        if isinstance(arg.annotation.slice, ast.Tuple)
                        else [arg.annotation.slice]))):
                self.scopes[self.scope].containers.add(arg.arg)
            if is_optional(arg.annotation) and arg.arg not in ("self", "cls"):
                self.params.append(Param(
                    func=node.name, name=arg.arg,
                    annotation=ast.unparse(arg.annotation)
                    if arg.annotation else "",
                    file=self.rel, line=node.lineno, order=order,
                    default_is_none=none_default,
                    public=not node.name.startswith("_")
                    and not Path(self.rel).name.startswith("_"),
                    guards=_tests_of(node, arg.arg)))
        if is_optional(node.returns):
            if any(ast.unparse(d).split(".")[-1] in ("property",
                                                     "cached_property")
                   for d in node.decorator_list):
                self.props.add(node.name)
            fn = Func(name=node.name, file=self.rel, line=node.lineno,
                      returns=ast.unparse(node.returns) if node.returns
                      else "")
            if falls_off(node.body):
                fn.why = "falls off the end"
            self.funcs[self.scope] = fn
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            # `self._default_pstyle = ...`: an attribute no dataclass
            # declares, read later as `x._default_pstyle`
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                self.self_attrs.append((target.attr, node.value, self.scope))
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if names:
            self.scopes[self.scope].assigns.append((names, node.value))
        # `printed, corner = _printed_number(...)`: each name takes its own
        # element of the callee's return type, so the Optional is per slot
        for target in node.targets:
            if not isinstance(target, ast.Tuple):
                continue
            called = (ast.unparse(node.value.func).split(".")[-1]
                      if isinstance(node.value, ast.Call) else "")
            for i, element in enumerate(target.elts):
                if isinstance(element, ast.Name) and called:
                    self.scopes[self.scope].unpacks.append(
                        (element.id, called, i))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            self.scopes[self.scope].assigns.append(
                ([node.target.id], node.value))
        if (isinstance(node.target, ast.Attribute)
                and isinstance(node.target.value, ast.Name)
                and node.target.value.id == "self"):
            # `self._default_pstyle: str | None = None`
            value = node.value if node.value is not None else ast.Constant(
                None if is_optional(node.annotation) else 0)
            self.self_attrs.append((node.target.attr, value, self.scope))
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.scopes[self.scope].loops.append((node.target, node.iter))
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.scopes[self.scope].assigns.append(([node.target.id], node.value))
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.scopes[self.scope].returns.append(node.value)
        self.generic_visit(node)



def _call_sites(rel: str, tree: ast.Module, classes: dict[str, list[Field]],
                scope_of: dict[int, str]) -> list[Site]:
    """Every constructor call, argument by argument."""
    out: list[Site] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func).split(".")[-1]
        where = f"{rel}:{node.lineno}"
        scope = scope_of.get(node.lineno, f"{rel}:<module>")
        if name == "cls":
            # a classmethod constructor: `cls(...)` builds the class the
            # method is defined in, which is the scope's second-to-last
            # part. `rsplit`, because a path can hold a colon of its own —
            # `C:/…/thing.py:Scaffold.read` is what a Windows absolute
            # path makes of this key, and splitting from the left took
            # the drive letter for the file and `py:Scaffold` for a class.
            owner = scope.rsplit(":", 1)[-1].split(".")
            name = owner[-2] if len(owner) > 1 else name
        here = classes.get(name)
        if here is None:
            continue
        given = {kw.arg for kw in node.keywords if kw.arg}
        star = any(kw.arg is None for kw in node.keywords) or any(
            isinstance(a, ast.Starred) for a in node.args)
        for f in here:
            if star:                       # **kwargs: anything may arrive
                out.append(Site(f.cls, f.name, ast.Constant(None), where,
                                scope))
                continue
            kw = next((k for k in node.keywords if k.arg == f.name), None)
            if kw is not None:
                out.append(Site(f.cls, f.name, kw.value, where, scope))
            elif f.order < len(node.args):
                out.append(Site(f.cls, f.name, node.args[f.order], where,
                                scope))
            elif f.name not in given and f.default_is_none:
                out.append(Site(f.cls, f.name, None, where, scope))
    return out


def _scope_of(tree: ast.Module) -> dict[int, str]:
    """Which function each LINE belongs to, for local-variable lookup."""
    out: dict[int, str] = {}

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef
                          | ast.ClassDef):
                here = [*stack, child.name]
                end = child.end_lineno or child.lineno
                for line in range(child.lineno, end + 1):
                    out[line] = ".".join(here)
                walk(child, here)
            else:
                walk(child, stack)

    walk(tree, [])
    return out


@dataclass
class World:
    """Everything the pass knows, and what it has proved can be None."""

    fields: list[Field] = field(default_factory=list)
    funcs: dict[str, Func] = field(default_factory=dict)
    params: list[Param] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    scopes: dict[str, Scope] = field(default_factory=dict)
    #: every call in the package: (plain name, node, where, scope)
    calls: list[tuple[str, ast.Call, str, str]] = field(default_factory=list)
    #: functions whose first parameter is self/cls, so a call's positional
    #: arguments start one place along
    methods: set[str] = field(default_factory=set)
    #: every function's return annotation, by plain name
    returns_of: dict[str, ast.expr | None] = field(default_factory=dict)
    #: optional `@property` names, read as attributes rather than called
    props: set[str] = field(default_factory=set)
    #: `self.x = ...` attributes: (name, value, scope)
    self_attrs: list[tuple[str, ast.expr, str]] = field(default_factory=list)
    #: proved so far
    none_fields: set[str] = field(default_factory=set)      # attribute names
    none_funcs: set[str] = field(default_factory=set)       # plain names
    none_locals: dict[str, set[str]] = field(default_factory=dict)

    def can_be_none(self, node: ast.expr | None, scope: str) -> str:
        """Why `node` can be None, or "" when nothing here says it can.

        The three DIRECT readings — a name, an attribute, a call — are in
        :meth:`_directly`; what is left here combines them.
        """
        why = ""
        if node is None:
            why = "left to its None default"
        elif isinstance(node, ast.Constant):
            why = "passed None" if node.value is None else ""
        elif isinstance(node, ast.Name | ast.Attribute | ast.Call):
            why = self._directly(node, scope)
        elif isinstance(node, ast.IfExp):
            why = (self.can_be_none(node.body, scope)
                   or self.can_be_none(node.orelse, scope))
        elif isinstance(node, ast.BoolOp):
            why = next((found for v in node.values
                        if (found := self.can_be_none(v, scope))), "")
        elif isinstance(node, ast.NamedExpr | ast.Await):
            why = self.can_be_none(node.value, scope)
        elif (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Call)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, int)):
            # `explain(...)[0]`: the slot of the tuple, not the call
            called = ast.unparse(node.value.func).split(".")[-1]
            if self._slot(called, node.slice.value):
                why = f"passed `{called}(...)[{node.slice.value}]`, optional"
        return why

    def _directly(self, node: ast.Name | ast.Attribute | ast.Call,
                  scope: str) -> str:
        """A local, an attribute or a call read on its own."""
        why = ""
        if isinstance(node, ast.Name):
            why = (f"passed `{node.id}`, which can be None"
                   if node.id in self.none_locals.get(scope, ()) else "")
        elif isinstance(node, ast.Attribute):
            if node.attr in self.none_fields:
                why = f"passed `.{node.attr}`, itself optional"
            elif node.attr in self.props and node.attr in self.none_funcs:
                why = f"passed `.{node.attr}`, a property that can be None"
        else:
            called = ast.unparse(node.func).split(".")[-1]
            if called in NONE_RETURNING:
                why = f"passed `{called}(...)`, which can be None"
            elif called in self.none_funcs:
                why = f"passed `{called}(...)`, which can return None"
        return why

    def _slot(self, called: str, index: int) -> bool:
        """Is the `index`-th element of what `called` returns Optional?"""
        annotation = self.returns_of.get(called)
        if not isinstance(annotation, ast.Subscript):
            return False
        if ast.unparse(annotation.value).split(".")[-1].lower() != "tuple":
            return False
        parts = (annotation.slice.elts
                 if isinstance(annotation.slice, ast.Tuple) else [])
        return index < len(parts) and is_optional(parts[index])

    @staticmethod
    def _loop_names(target: ast.expr, source: ast.expr,
                    body: Scope) -> set[str]:
        """Loop variables that draw from a container of optionals."""
        if isinstance(source, ast.Name):
            if source.id in body.containers and isinstance(target, ast.Name):
                return {target.id}
            return set()
        if (isinstance(source, ast.Call)
                and ast.unparse(source.func).split(".")[-1] == "zip"
                and isinstance(target, ast.Tuple)):
            return {element.id
                    for element, iterable in zip(target.elts, source.args,
                                                 strict=False)
                    if isinstance(element, ast.Name)
                    and isinstance(iterable, ast.Name)
                    and iterable.id in body.containers}
        return set()

    def _passed_none(self, p: Param) -> str:
        """Why some call passes None for this parameter, or ""."""
        offset = 1 if p.func in self.methods else 0
        for name, node, where, scope in self.calls:
            if name != p.func:
                continue
            if any(kw.arg is None for kw in node.keywords) or any(
                    isinstance(a, ast.Starred) for a in node.args):
                return f"reached by *args/**kwargs at {where}"
            kw = next((k for k in node.keywords if k.arg == p.name), None)
            if kw is not None:
                if (why := self.can_be_none(kw.value, scope)):
                    return f"{why} at {where}"
                continue
            index = p.order - offset
            if 0 <= index < len(node.args):
                if (why := self.can_be_none(node.args[index], scope)):
                    return f"{why} at {where}"
            elif p.default_is_none:
                return f"left to its None default at {where}"
        return ""

    def settle(self) -> None:
        """Grow what is proved until one whole pass proves nothing new."""
        for scope, body in self.scopes.items():
            known = self.none_locals.setdefault(scope, set())
            known |= body.optional_params
            known |= {name for name, called, index in body.unpacks
                      if self._slot(called, index)}
        while (self._locals() | self._returns() | self._attributes()
               | self._arguments()):
            pass

    def _locals(self) -> bool:
        """Local names that can hold None, one pass."""
        changed = False
        for scope, body in self.scopes.items():
            known = self.none_locals.setdefault(scope, set())
            for names, value in body.assigns:
                if self.can_be_none(value, scope) and not set(names) <= known:
                    known |= set(names)
                    changed = True
                # `mentions = [mention_of(...) for x in found]` holds
                # optionals, so what a loop draws from it can be None
                if (isinstance(value, ast.ListComp | ast.SetComp
                               | ast.GeneratorExp)
                        and self.can_be_none(value.elt, scope)):
                    body.containers |= set(names)
            for target, source in body.loops:
                drawn = self._loop_names(target, source, body)
                if not drawn <= known:
                    known |= drawn
                    changed = True
        return changed

    def _returns(self) -> bool:
        """Functions that can return None, one pass."""
        changed = False
        for key, fn in self.funcs.items():
            if fn.why:
                continue
            for value in self.scopes.get(key, Scope()).returns:
                why = ("bare `return`" if value is None
                       else self.can_be_none(value, key))
                if why:
                    fn.why = why.replace("passed", "returns")
                    self.none_funcs.add(fn.name)
                    changed = True
                    break
        return changed

    def _attributes(self) -> bool:
        """`self.x = ...` attributes that can hold None, one pass."""
        changed = False
        for attr, value, scope in self.self_attrs:
            if attr not in self.none_fields and self.can_be_none(value, scope):
                self.none_fields.add(attr)
                changed = True
        return changed

    def _arguments(self) -> bool:
        """Parameters and fields something passes None to, one pass."""
        changed = False
        for p in self.params:
            if not p.why and (why := self._passed_none(p)):
                p.why = why
                changed = True
        for f in self.fields:
            if f.why:
                continue
            for site in self.sites:
                if site.cls != f.cls or site.fieldname != f.name:
                    continue
                if (why := self.can_be_none(site.expr, site.scope)):
                    f.why = f"{why} at {site.where}"
                    self.none_fields.add(f.name)
                    changed = True
                    break
        return changed


def _later_assignments(trees: dict[Path, ast.Module], world: World) -> None:
    """`obj.field = None` — the other way a field comes to be None."""
    names = {f.name for f in world.fields}
    for path, tree in trees.items():
        rel = _rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                targets = (list(node.targets) if isinstance(node, ast.Assign)
                           else [node.target])
                if not (isinstance(node.value, ast.Constant)
                        and node.value.value is None):
                    continue
                for target in targets:
                    if (isinstance(target, ast.Attribute)
                            and target.attr in names):
                        for f in world.fields:
                            if f.name == target.attr and not f.why:
                                f.why = (f"assigned None at "
                                         f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Call) and ast.unparse(
                    node.func).split(".")[-1] in ("replace", "_replace"):
                for kw in node.keywords:
                    if (kw.arg in names and isinstance(kw.value, ast.Constant)
                            and kw.value.value is None):
                        for f in world.fields:
                            if f.name == kw.arg and not f.why:
                                f.why = (f"replace(..., {kw.arg}=None) at "
                                         f"{rel}:{node.lineno}")


@dataclass
class Guard:
    where: str
    text: str
    kind: str


def _return_readers(trees: dict[Path, ast.Module]) -> dict[str, list[Guard]]:
    """Who tests what a function RETURNS for None, by function name.

    Both spellings: the result tested where it is made —
    ``if (m := f(x)) is not None`` — and the result kept in a local that
    is tested later in the same body.
    """
    out: dict[str, list[Guard]] = defaultdict(list)
    for path, tree in trees.items():
        rel = _rel(path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Compare) and len(node.ops) == 1
                    and isinstance(node.ops[0], ast.Is | ast.IsNot)
                    and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value is None):
                left = node.left
                if isinstance(left, ast.NamedExpr):
                    left = left.value
                if isinstance(left, ast.Call):
                    out[ast.unparse(left.func).split(".")[-1]].append(Guard(
                        f"{rel}:{node.lineno}", ast.unparse(node)[:72],
                        "at the call"))
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            made: dict[str, tuple[str, int]] = {}
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Assign | ast.NamedExpr)
                        and isinstance(sub.value, ast.Call)):
                    called = ast.unparse(sub.value.func).split(".")[-1]
                    targets = ([sub.target] if isinstance(sub, ast.NamedExpr)
                               else sub.targets)
                    for target in targets:
                        if isinstance(target, ast.Name):
                            made[target.id] = (called, sub.lineno)
            for name, (called, line) in made.items():
                for test in _tests_of(node, name):
                    out[called].append(Guard(f"{rel}:{line}", test, "on its "
                                             "local"))
    return out


def _guards(trees: dict[Path, ast.Module]) -> dict[str, list[Guard]]:
    """Every `X.attr is None` / `is not None` / `if X.attr:` by attribute."""
    out: dict[str, list[Guard]] = defaultdict(list)
    for path, tree in trees.items():
        rel = _rel(path)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Compare) and len(node.ops) == 1
                    and isinstance(node.ops[0], ast.Is | ast.IsNot)
                    and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value is None
                    and isinstance(node.left, ast.Attribute)):
                out[node.left.attr].append(Guard(
                    f"{rel}:{node.lineno}", ast.unparse(node)[:72],
                    "identity"))
            if isinstance(node, ast.If) and isinstance(node.test,
                                                       ast.Attribute):
                out[node.test.attr].append(Guard(
                    f"{rel}:{node.lineno}", f"if {ast.unparse(node.test)}:",
                    "truthiness"))
            if (isinstance(node, ast.UnaryOp)
                    and isinstance(node.op, ast.Not)
                    and isinstance(node.operand, ast.Attribute)):
                out[node.operand.attr].append(Guard(
                    f"{rel}:{node.lineno}", ast.unparse(node)[:72],
                    "truthiness"))
    return out


def build(paths: list[Path],
          callers: list[Path] | None = None
          ) -> tuple[World, dict[Path, ast.Module]]:
    """`paths` declare and call; `callers` only call.

    The second is how a candidate is told from a branch the TESTS reach:
    a default nothing in `src` omits, omitted by one test, is a live
    branch with no shipped caller — a different thing from a claim
    nothing can make true, and the report says which.
    """
    paths = [*paths, *(callers or [])]
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in paths}
    world = World()
    seen: list[tuple[str, ast.Module, Collect]] = []
    for path, tree in trees.items():
        collect = Collect(path)
        collect.visit(tree)
        world.fields += collect.fields
        world.funcs |= collect.funcs
        world.scopes |= collect.scopes
        world.returns_of |= collect.returns_of
        world.props |= collect.props
        world.self_attrs += collect.self_attrs
        seen.append((collect.rel, tree, collect))
    classes: dict[str, list[Field]] = defaultdict(list)
    for f in world.fields:
        classes[f.cls].append(f)
    for rel, tree, collect in seen:
        world.params += collect.params
        scope_of = {line: f"{rel}:{name}"
                    for line, name in _scope_of(tree).items()}
        world.sites += _call_sites(rel, tree, classes, scope_of)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                world.calls.append((
                    ast.unparse(node.func).split(".")[-1], node,
                    f"{rel}:{node.lineno}",
                    scope_of.get(node.lineno, f"{rel}:<module>")))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                first = [*node.args.posonlyargs, *node.args.args][:1]
                if first and first[0].arg in ("self", "cls"):
                    world.methods.add(node.name)
    _later_assignments(trees, world)
    for f in world.fields:                 # seed: proved before the fixpoint
        if f.why:
            world.none_fields.add(f.name)
    world.settle()
    return world, trees


def audit(paths: list[Path], show_all: bool = False,
          callers: list[Path] | None = None) -> int:
    """Print the findings; return how many a GATE should fail on.

    Only a candidate something READS as optional is counted. A field or
    a return nothing tests for None is an annotation nobody has been
    misled by yet — and failing on those would fail on every Optional
    written before the test that exercises it, which is a toll on
    ordinary work and not the defect. `PromoteReport.redline` had its
    reader (`cli.py: report.redline is not None`) the day it landed.
    """
    world, trees = build(paths, callers)
    guards = _guards(trees)
    readers = _return_readers(trees)
    declared = {_rel(p) for p in paths}
    dead_fields = [f for f in world.fields
                   if not f.why and f.file in declared]
    dead_funcs = [fn for fn in world.funcs.values()
                  if not fn.why and fn.file in declared]
    read_fields = [f for f in dead_fields if guards.get(f.name)]
    read_funcs = [fn for fn in dead_funcs if readers.get(fn.name)]

    print(f"{len(world.fields)} optional class fields · "
          f"{len(dead_fields)} nothing in src makes None "
          f"({len(read_fields)} of them read as optional somewhere)")
    for f in sorted(dead_fields, key=lambda f: (-len(guards.get(f.name, [])),
                                                f.file, f.line)):
        found = guards.get(f.name, [])
        print(f"\n  {f.file}:{f.line}  {f.cls}.{f.name}: {f.annotation}"
              f"{' = None' if f.default_is_none else ''}"
              f"  — {len(found) or 'no'} guard(s)"
              f"{'' if found else ', so nothing has been misled yet'}")
        for g in found:
            print(f"      {g.kind:11} {g.where}  {g.text}")

    print(f"\n{len(world.funcs)} optional returns · {len(dead_funcs)} with "
          f"no reachable None ({len(read_funcs)} of them tested for None "
          f"by a caller)")
    for fn in sorted(dead_funcs, key=lambda fn: (fn.file, fn.line)):
        found = readers.get(fn.name, [])
        print(f"  {fn.file}:{fn.line}  {fn.name}() -> {fn.returns}"
              f"  — {len(found) or 'no'} reader(s)")
        for g in found:
            print(f"      {g.kind:11} {g.where}  {g.text}")

    called = {name for name, *_ in world.calls}
    quiet = [p for p in world.params
             if not p.why and p.guards and p.func in called
             and p.file in declared]
    # A `= None` default is reachable by ANY caller that omits the
    # argument, papers included, so it is a sentinel rather than a claim
    # nothing can make true — counted, not listed.
    dead_params = [p for p in quiet if not p.default_is_none]
    print(f"\n{len(world.params)} optional parameters · {len(dead_params)} "
          f"that a caller must pass, that no call in src passes None, and "
          f"that TEST for None anyway ({len(quiet) - len(dead_params)} more "
          f"have a None default, which any caller reaches by omission)")
    sentinels = [p for p in quiet if p.default_is_none]
    for group in (dead_params, sentinels):
        if group is sentinels:
            print(f"\n  … and {len(sentinels)} with a None default that no "
                  f"call in src omits. Only reachable from OUTSIDE the "
                  f"package, so a private one's None branch is dead too:")
        for p in sorted(group, key=lambda p: (p.public, -len(p.guards),
                                              p.file)):
            print(f"\n  {p.file}:{p.line}  {p.func}({p.name}: {p.annotation}"
                  f"{' = None' if p.default_is_none else ''})"
                  f"  [{'public' if p.public else 'private'}]")
            for test in p.guards:
                print(f"      {test}")

    if show_all:
        print("\n--- and the ones something DOES make None ---")
        for f in sorted(world.fields, key=lambda f: (f.file, f.line)):
            if f.why:
                print(f"  {f.file}:{f.line} {f.cls}.{f.name}: {f.why}")
        for fn in sorted(world.funcs.values(), key=lambda fn: (fn.file,
                                                               fn.line)):
            if fn.why:
                print(f"  {fn.file}:{fn.line} {fn.name}(): {fn.why}")

    gating = len(read_fields) + len(read_funcs) + len(dead_params)
    read = len(world.fields) + len(world.funcs) + len(world.params)
    print(f"\n{gating} optional(s) nothing can make None, and something "
          f"reads as optional anyway — of {read} read")
    return gating


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Optionals nothing in this package can make None.")
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--all", action="store_true",
                    help="also list the optionals something does make None")
    ap.add_argument("--callers", type=Path, action="append", default=[],
                    metavar="DIR",
                    help="a directory that only CALLS (tests/), counted as "
                         "evidence but never reported on")
    args = ap.parse_args(argv)
    paths = args.paths or sorted((ROOT / "src" / "docxkit").rglob("*.py"))
    callers = [p for folder in args.callers
               for p in sorted(Path(folder).rglob("*.py"))]
    # 1, never the count: `gates.py` reads exit 3 as "I did not run", so a
    # run that found exactly three would report as a SKIP — a failure
    # printed as a shrug, which is the one outcome a gate may not have.
    return 1 if audit(paths, show_all=args.all, callers=callers) else 0


if __name__ == "__main__":
    sys.exit(main())
