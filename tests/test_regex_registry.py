"""One element, one reading of its open tag, across the whole package.

158 compiled patterns live in `src/docxkit`, 157 of them distinct, and
22 OOXML elements are spelled by more than one of them. Most of that
divergence is harmless: measured over 899 manuscripts (2026-08-15), not
one carries an attribute on ``m:oMath``, ``w:rPr``, ``w:tc``, ``w:sz``,
``w:pStyle`` or ``w:rStyle``, so a pattern that tolerates attributes and
one that does not agree on every real document.

**The self-closing form is the divergence that bites**, and it has bitten
twice:

* ``PARA_RE`` read ``<w:p/>`` as an open tag and paired it with the next
  ``</w:p>``, so a slice began at the blank line BEFORE the paragraph
  asked for (fixed 6acc545). 32 of 899 manuscripts carry one;
* ``RUN_RE`` did the same with ``<w:r/>`` and merged an empty run with
  the run after it, so the walk read the EMPTY run's properties as that
  run's (fixed 2026-08-15). 28 of 899 carry one.

Both were found by hand, twice, years apart. This finds the third.
"""
from __future__ import annotations

import ast
import itertools
import pathlib
import re
from collections.abc import Callable
from typing import Any, ClassVar

import pytest

import docxkit

SRC = pathlib.Path(docxkit.__file__).parent

#: Elements that CONTAIN other elements. A self-closing spelling of one
#: of these is an EMPTY container — never an opening tag — so a pattern
#: that matches ``<w:p/>`` as if it opened something is wrong.
#: Self-closing-only elements (`w:sz`, `w:gridCol`, `w:bookmarkStart`,
#: `w:pgSz`) are deliberately absent: there, the self-closing form is
#: the only form.
CONTAINERS = ("p", "r", "tbl", "tr", "tc", "hyperlink", "ins", "del",
              "moveFrom", "moveTo", "footnote", "endnote", "comment",
              "sdt", "sdtContent", "body", "rPr", "pPr", "tblPr", "trPr",
              "tcPr", "customXml", "smartTag", "fldSimple")


#: The `re` calls whose first argument is a pattern. A pattern written
#: inline — `re.finditer(r"<w:comment ([^>]*)>(.*?)</w:comment>", com)` —
#: reads an element exactly as a compiled one does.
_RE_CALLS = ("compile", "search", "match", "fullmatch", "finditer",
             "findall", "sub", "subn", "split")


#: What an f-string's `{hole}` is probed AS when the walk cannot fold it:
#: a value, a tag name, an id. `<w:bookmarkStart w:id="(\d+)"
#: w:name="{name}"/>` read as a plain literal matches no probe, and was
#: invisible to both gates while carrying the order defect its literal
#: twin in the same module had.
_HOLE = r"\w+"

#: Past this many readings a pattern built from alternatives is not
#: worth enumerating; none in the package comes near it.
_MAX_READINGS = 64

#: Every module's syntax tree, by POSIX path under the package: the walk
#: follows an imported name into the module that binds it.
_TREES = {p.relative_to(SRC).as_posix():
          ast.parse(p.read_text(encoding="utf-8"))
          for p in sorted(SRC.rglob("*.py"))}

_COMPREHENSIONS = (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module,
           *_COMPREHENSIONS)

#: A binding: "value" (the name IS this expression), "item" (the name is
#: each item of this sequence, a loop target), or None (unreadable).
_Binding = tuple["_Folder", str, ast.expr] | None


def _product(parts: list[list[str]]) -> list[str] | None:
    readings = [""]
    for alternatives in parts:
        readings = [r + a for r in readings for a in alternatives]
        if len(readings) > _MAX_READINGS:
            return None
    return readings


def _is_re_call(node: ast.AST, *attrs: str) -> bool:
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re"
            and node.func.attr in attrs)


class _Folder:
    """What a pattern argument evaluates to, read without running it.

    A pattern is often not a literal at the call: `PARA_RE.pattern +
    '|<w:p\\b[^>]*/>'`, `r"<m:(" + "|".join(OMML_STRUCT) + r")\\b"`,
    `rf"{_AUTHORS},?\\s+{_YEARS}"`, or a local `forms` tuple a loop walks.
    Every one of those is a literal a few names away, and a gate that
    stops at the call reads none of them — `hyperlink_labels` paired a
    self-closing ghost link with the next link's close behind exactly
    that (2026-09-17). Folded here: string literals, `+`, f-string holes,
    `"sep".join` of a literal sequence, `"…".format` of literals,
    `re.escape` of one, `X.pattern` of a compiled literal, a name bound
    ONCE in its function or at module level (an imported name followed
    into its module), and a loop or comprehension target over a literal
    sequence, which reads as each of its items.
    """

    _cache: ClassVar[dict[str, _Folder]] = {}

    def __init__(self, module: str) -> None:
        self.module = module
        self.tree = _TREES[module]
        self.parent: dict[int, ast.AST] = {
            id(child): node for node in ast.walk(self.tree)
            for child in ast.iter_child_nodes(node)}

    @classmethod
    def of(cls, module: str) -> _Folder:
        if module not in cls._cache:
            cls._cache[module] = cls(module)
        return cls._cache[module]

    # -- where a name is bound ------------------------------------------
    def _module_binding(self, name: str, depth: int) -> _Binding:
        """The ONE module-level binding of `name`, imports followed."""
        found: list[_Binding] = []
        for stmt in self.tree.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        found.append((self, "value", stmt.value))
            elif isinstance(stmt, ast.AnnAssign):
                if (isinstance(stmt.target, ast.Name)
                        and stmt.target.id == name and stmt.value is not None):
                    found.append((self, "value", stmt.value))
            elif isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    if (alias.asname or alias.name) == name:
                        found.append(self._imported(stmt, alias.name, depth))
        return found[0] if len(found) == 1 else None

    def _imported(self, stmt: ast.ImportFrom, name: str,
                  depth: int) -> _Binding:
        dotted = stmt.module.split(".") if stmt.module else []
        if stmt.level:
            package = self.module.split("/")[:-1]
            base = package[:len(package) - (stmt.level - 1)]
        elif dotted[:1] == ["docxkit"]:
            base, dotted = [], dotted[1:]
        else:
            return None                         # outside the package
        stem = "/".join([*base, *dotted])
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if candidate in _TREES and depth < 30:
                return _Folder.of(candidate)._module_binding(name, depth + 1)
        return None

    def _scope_of(self, node: ast.AST) -> ast.AST:
        at = self.parent.get(id(node))
        while at is not None and not isinstance(at, _SCOPES):
            at = self.parent.get(id(at))
        return at if at is not None else self.tree

    def _local_bindings(self, function: ast.AST, name: str) -> list[_Binding]:
        """Each binding of `name` in `function`'s own body."""
        out: list[_Binding] = []
        stack = list(ast.iter_child_nodes(function))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.ClassDef, *_SCOPES)):
                continue
            named = any(isinstance(t, ast.Name) and t.id == name
                        for t in ast.walk(node)
                        if isinstance(t, ast.Name)
                        and isinstance(t.ctx, ast.Store))
            if isinstance(node, ast.Assign) and named:
                simple = [t for t in node.targets
                          if isinstance(t, ast.Name) and t.id == name]
                out.append((self, "value", node.value) if simple
                           and len(node.targets) == 1 else None)
                continue
            if isinstance(node, ast.For | ast.AsyncFor):
                if isinstance(node.target, ast.Name) \
                        and node.target.id == name:
                    out.append((self, "item", node.iter))
                elif any(isinstance(t, ast.Name) and t.id == name
                         for t in ast.walk(node.target)):
                    out.append(None)
            elif isinstance(node, ast.AnnAssign | ast.AugAssign
                            | ast.NamedExpr | ast.withitem
                            | ast.ExceptHandler) and (
                    named or getattr(node, "name", None) == name):
                out.append(None)
            elif isinstance(node, ast.Import | ast.ImportFrom):
                for alias in node.names:
                    if (alias.asname or alias.name).split(".")[0] == name:
                        out.append(self._imported(node, alias.name, 0)
                                   if isinstance(node, ast.ImportFrom)
                                   else None)
            stack.extend(ast.iter_child_nodes(node))
        return out

    def _binding(self, node: ast.Name, depth: int) -> _Binding:
        scope: ast.AST = node
        while True:
            scope = self._scope_of(scope)
            if isinstance(scope, ast.Module):
                return self._module_binding(node.id, depth)
            if isinstance(scope, _COMPREHENSIONS):
                for gen in scope.generators:
                    if isinstance(gen.target, ast.Name) \
                            and gen.target.id == node.id:
                        return (self, "item", gen.iter)
                continue
            assert isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef
                              | ast.Lambda)
            args = scope.args
            if node.id in {a.arg for a in [*args.posonlyargs, *args.args,
                                           *args.kwonlyargs]}:
                return None
            if isinstance(scope, ast.Lambda):
                continue
            bindings = self._local_bindings(scope, node.id)
            if not bindings:
                continue
            return bindings[0] if len(bindings) == 1 else None

    # -- what an expression reads as ------------------------------------
    def fold_items(self, node: ast.expr, depth: int = 0) -> list[str] | None:
        """The items of a literal sequence, each read as a string."""
        if depth > 30:
            return None
        if isinstance(node, ast.Tuple | ast.List):
            items: list[str] = []
            for element in node.elts:
                got = self.fold(element, depth + 1)
                if got is None:
                    return None
                items += got
            return items
        if isinstance(node, ast.Name):
            bound = self._binding(node, depth)
            if bound is not None and bound[1] == "value":
                return bound[0].fold_items(bound[2], depth + 1)
        return None

    def fold(self, node: ast.expr, depth: int = 0) -> list[str] | None:
        """Every string `node` can evaluate to, or None."""
        readers: dict[type, Callable[[Any, int], list[str] | None]] = {
            ast.Constant: self._fold_constant,
            ast.JoinedStr: self._fold_fstring,
            ast.BinOp: self._fold_concatenation,
            ast.Name: self._fold_name,
            ast.Attribute: self._fold_compiled,
            ast.Call: self._fold_call,
        }
        reader = readers.get(type(node))
        return None if reader is None or depth > 30 else reader(node,
                                                                depth + 1)

    @staticmethod
    def _fold_constant(node: ast.Constant, _depth: int) -> list[str] | None:
        return [node.value] if isinstance(node.value, str) else None

    def _fold_fstring(self, node: ast.JoinedStr,
                      depth: int) -> list[str] | None:
        parts: list[list[str]] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append([str(part.value)])
                continue
            assert isinstance(part, ast.FormattedValue)
            got = (self.fold(part.value, depth)
                   if part.conversion == -1 and part.format_spec is None
                   else None)
            if got is None:
                return None
            parts.append(got)
        return _product(parts)

    def _fold_concatenation(self, node: ast.BinOp,
                            depth: int) -> list[str] | None:
        if not isinstance(node.op, ast.Add):
            return None
        left, right = self.fold(node.left, depth), self.fold(node.right, depth)
        return None if left is None or right is None else _product([left,
                                                                    right])

    def _fold_name(self, node: ast.Name, depth: int) -> list[str] | None:
        bound = self._binding(node, depth)
        if bound is None:
            return None
        folder, kind, expr = bound
        return (folder.fold(expr, depth) if kind == "value"
                else folder.fold_items(expr, depth))

    def _fold_compiled(self, node: ast.Attribute,
                       depth: int) -> list[str] | None:
        """`X.pattern`, where `X` is `re.compile` of something foldable."""
        bound = (self._binding(node.value, depth)
                 if node.attr == "pattern" and isinstance(node.value, ast.Name)
                 else None)
        if bound is None or bound[1] != "value" \
                or not _is_re_call(bound[2], "compile"):
            return None
        call = bound[2]
        assert isinstance(call, ast.Call)
        return bound[0].fold(call.args[0], depth) if call.args else None

    def _fold_call(self, node: ast.Call, depth: int) -> list[str] | None:
        func = node.func
        if not isinstance(func, ast.Attribute):
            return None
        if _is_re_call(node, "escape") and len(node.args) == 1:
            got = self.fold(node.args[0], depth)
            return None if got is None else [re.escape(g) for g in got]
        if func.attr == "join" and len(node.args) == 1 and not node.keywords:
            sep = self.fold(func.value, depth)
            items = self.fold_items(node.args[0], depth)
            return (None if sep is None or len(sep) != 1 or items is None
                    else [sep[0].join(items)])
        return self._fold_format(node, func, depth)

    def _fold_format(self, node: ast.Call, func: ast.Attribute,
                     depth: int) -> list[str] | None:
        template = (self.fold(func.value, depth) if func.attr == "format"
                    else None)
        args = [self.fold(a, depth) for a in node.args]
        kwargs = [(k.arg, self.fold(k.value, depth)) for k in node.keywords]
        positional = [a[0] for a in args if a is not None and len(a) == 1]
        keyword = {k: v[0] for k, v in kwargs
                   if k is not None and v is not None and len(v) == 1}
        if (template is None or len(template) != 1
                or len(positional) != len(args)
                or len(keyword) != len(kwargs)):
            return None
        return [template[0].format(*positional, **keyword)]

    def probes(self, node: ast.expr) -> tuple[str, list[str]] | None:
        """(source as written, the readings the gate compiles), or None.

        An f-string whose hole cannot be folded is still read, the hole
        probed as `_HOLE` — at the call, or bound once to the name the
        call is given; anything else the walk cannot fold is not.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value, [node.value]
        if isinstance(node, ast.Name):
            bound = self._binding(node, 0)
            if bound is not None and bound[1] == "value" \
                    and isinstance(bound[2], ast.JoinedStr) \
                    and self.fold(node) is None:
                return bound[0].probes(bound[2])
        if isinstance(node, ast.JoinedStr):
            source: list[str] = []
            parts: list[list[str]] = []
            for part in node.values:
                if isinstance(part, ast.Constant):
                    source.append(str(part.value))
                    parts.append([str(part.value)])
                    continue
                assert isinstance(part, ast.FormattedValue)
                source.append("{" + ast.unparse(part.value) + "}")
                got = (self.fold(part.value)
                       if part.conversion == -1 and part.format_spec is None
                       else None)
                parts.append(got if got is not None else [_HOLE])
            readings = _product(parts)
            return ("".join(source), readings if readings is not None
                    else ["".join(p[0] for p in parts)])
        readings = self.fold(node)
        return None if readings is None else (ast.unparse(node), readings)


def _walk(module: str) -> tuple[list[tuple[str, str, str, int]],
                                list[tuple[str, int]]]:
    """(name, source, probe, line) for EVERY `re` call the walk can read,
    and (description, line) for every one it cannot.

    Not only `NAME = re.compile(...)`: `_xml.NOTE_DEF_RE` compiles its
    two patterns inside a dict literal, and six more read comments,
    rows and cells through `re.finditer(r"…")` inline. A walk that asked
    for an assignment of `re.compile` itself saw none of them — the same
    self-closing defect sat in them beside the copies this gate did find
    (2026-09-17). Nor only plain literals: an f-string is a literal with
    holes, and three of them carried the defects their plain twins were
    flagged for; and a pattern built from names is folded (`_Folder`).
    The name is the nearest assignment target around the call, or `?`.
    An unreadable call is described by its function and the call as
    written, which move only when that code does.
    """
    folder = _Folder.of(module)
    names: dict[int, str] = {}
    functions: dict[int, str] = {}
    for node in ast.walk(folder.tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            name = next((t.id for t in targets if isinstance(t, ast.Name)),
                        "?")
            for inner in ast.walk(node):
                names.setdefault(id(inner), name)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(node):
                functions[id(inner)] = node.name
    read, unread = [], []
    for node in ast.walk(folder.tree):
        if not _is_re_call(node, *_RE_CALLS):
            continue
        assert isinstance(node, ast.Call)
        assert isinstance(node.func, ast.Attribute)
        pattern = (node.args[0] if node.args else next(
            (k.value for k in node.keywords if k.arg == "pattern"), None))
        got = folder.probes(pattern) if pattern is not None else None
        if got is None:
            written = ast.unparse(pattern) if pattern is not None else ""
            unread.append((f"{functions.get(id(node), '<module>')}: "
                           f"re.{node.func.attr}({written})", node.lineno))
            continue
        source, readings = got
        read += [(names.get(id(node), "?"), source, probe, node.lineno)
                 for probe in readings]
    return read, unread


_WALKED = {module: _walk(module) for module in _TREES}

#: Every module, the subpackage's halves included: a `*.py` glob is a
#: claim that the package is flat, and `revision/` has not been since
#: 2026-08-30 (BACKLOG, "Not seven defects — one habit"). POSIX paths,
#: so an allowlist key reads the same on every machine.
ALL_PATTERNS = [(module, name, src, probe, line)
                for module, (read, _) in _WALKED.items()
                for name, src, probe, line in read]

#: Every `re` call whose pattern the walk could not read.
ALL_UNREAD = [(module, what, line)
              for module, (_, unread) in _WALKED.items()
              for what, line in unread]


def _folded(code: str) -> tuple[str, list[str]] | None:
    """`probes` of the pattern in the last `re` call of `code`."""
    _TREES["_probe_.py"] = ast.parse(code)
    _Folder._cache.pop("_probe_.py", None)
    try:
        folder = _Folder.of("_probe_.py")
        calls = [n for n in ast.walk(folder.tree)
                 if _is_re_call(n, *_RE_CALLS)]
        assert isinstance(calls[-1], ast.Call)
        return folder.probes(calls[-1].args[0])
    finally:
        del _TREES["_probe_.py"]
        _Folder._cache.pop("_probe_.py", None)


def test_an_f_string_is_read_with_its_holes():
    """The walk's own instrument: a hole is kept in the source, filled
    in the probe, and a pattern built from something it cannot see
    into is not read at all."""
    assert _folded('re.search(rf\'<w:x w:id="{bid}"/>\', xml)') == (
        '<w:x w:id="{bid}"/>', [f'<w:x w:id="{_HOLE}"/>'])
    assert _folded('def f(p):\n    re.compile(p + "b")') is None


def test_a_pattern_built_from_LITERALS_is_folded():
    """Each spelling the package uses, read to the string the call gets."""
    assert _folded('A = "<w:"\nre.compile(A + "p>")') == (
        "A + 'p>'", ["<w:p>"])
    assert _folded('N = ("ins", "del")\n'
                   're.compile("<w:(" + "|".join(N) + ")")') == (
        "'<w:(' + '|'.join(N) + ')'", ["<w:(ins|del)"])
    assert _folded('Y = r"\\d{4}"\nre.compile(rf"\\(({Y})\\)")') == (
        "\\(({Y})\\)", ["\\((\\d{4})\\)"])
    assert _folded('R = re.compile("<w:p>")\n'
                   're.compile(R.pattern + "|x")') == (
        "R.pattern + '|x'", ["<w:p>|x"])
    assert _folded('re.compile("<w:{0}>".format("tc"))') == (
        "'<w:{0}>'.format('tc')", ["<w:tc>"])
    assert _folded('def f(x):\n    forms = ("<a>", "<b>")\n'
                   '    return [m for form in forms\n'
                   '            for m in re.finditer(form, x)]') == (
        "form", ["<a>", "<b>"])
    assert _folded('def f(x):\n    w = "<a>"\n    w = "<b>"\n'
                   '    re.search(w, x)') is None, "bound twice: unreadable"
    block = next(p for m, n, s, p, _ in ALL_PATTERNS
                 if m == "probe.py" and n == "_BLOCK_RE")
    assert block.startswith(r"<w:p\b"), "an imported name is followed"


def test_there_are_patterns_to_check():
    """A walk that silently found nothing would pass forever."""
    assert len(ALL_PATTERNS) > 100


#: The `re` calls whose pattern the walk cannot read, each with what the
#: pattern is and why no gate here needs to read it. Keyed by (module,
#: the function and the call as written). A blind spot declared is one a
#: reader can argue with; a silent one hid a ghost-link defect in
#: `_compare_diff.hyperlink_labels` until the walk learned to fold a
#: local tuple (2026-09-17).
UNREADABLE: dict[tuple[str, str], str] = {
    ("_cite_build.py", "unlink_by_anchor: re.compile(pattern)"): (
        "the CALLER's pattern for bookmark and anchor NAMES (a paper passes "
        "`bookmark=id\\..*` to clear a Google Docs export), matched against "
        "an attribute value already read out of the markup — never "
        "against a tag, so neither an empty element nor an attribute "
        "order can reach it"),
}


def test_every_pattern_the_walk_cannot_read_is_DECLARED():
    """A new unreadable call fails until it is listed with its reason,
    and a listed one the walk now reads — or that is gone — fails too."""
    unread = {(module, what) for module, what, _line in ALL_UNREAD}
    assert unread - set(UNREADABLE) == set(), (
        "the regex registry cannot read these patterns; fold them "
        "(`_Folder`), write them as literals, or declare them in "
        "UNREADABLE with the reason no gate needs to:\n  " + "\n  ".join(
            f"{module}:{line} {what}" for module, what, line in ALL_UNREAD
            if (module, what) not in UNREADABLE))
    assert set(UNREADABLE) - unread == set(), "declared, but now read"
    for key, reason in UNREADABLE.items():
        assert len(reason) > 40, (key, reason)


# --- plain string READS of markup ----------------------------------------
#
# The gates above read patterns. A literal handed to `in`, `find`, `index`,
# `count`, `replace` and their kin reads markup too, with no pattern
# syntax to widen it: `"<w:cantSplit/>" not in row` gave a row closing it
# ` />` a second one, `"<w:trackRevisions/>" in settings` lost Track
# Changes spelled otherwise, and `"<w:rPr>" in run` gave a run with an
# EMPTY `<w:rPr/>` — 18,172 of them in 248 of 2,954 corpus packages — a
# second properties element (2026-09-17). Every such read is enumerated,
# and one bound to a spelling is either widened or declared here.

#: The `str` methods whose first argument is text to FIND.
_STR_READS = frozenset({"find", "rfind", "index", "rindex", "count",
                        "replace", "startswith", "endswith", "split",
                        "rsplit", "partition", "rpartition",
                        "removeprefix", "removesuffix"})

#: Markup, as opposed to a `<` in prose, in a pattern's `(?<=`, or in an
#: XML declaration. f-string holes read as `{}`.
_MARKUP_LITERAL = re.compile(r"</?(?:[A-Za-z]|\{\})")

#: A literal no producer can spell another way: an element NAME prefix
#: (`<w:ins`, `<w:{}Reference`) or a closing tag (`</w:p>`). Whether a
#: name prefix also begins another element's name is a different
#: question, and not this gate's.
_SPELLING_FREE = re.compile(r"^(?:<[\w.:{}-]+|</[\w.:{}-]+>)$")


def _literal_texts(folder: _Folder, node: ast.expr) -> list[str]:
    """Every literal string `node` can be, f-string holes as `{}`."""
    if isinstance(node, ast.Tuple | ast.List):
        return [t for e in node.elts for t in _literal_texts(folder, e)]
    if isinstance(node, ast.JoinedStr):
        return ["".join(str(v.value) if isinstance(v, ast.Constant) else "{}"
                        for v in node.values)]
    if (folded := folder.fold(node)) is not None:
        return folded
    if isinstance(node, ast.Name):
        bound = folder._binding(node, 0)
        if bound is not None and bound[1] == "value" and isinstance(
                bound[2], ast.JoinedStr | ast.Tuple | ast.List):
            return _literal_texts(bound[0], bound[2])
    return []


def _markup_reads(module: str) -> list[tuple[str, int]]:
    """(description, line) for each read of a spelling-bound markup
    literal: the function, the operation, and the literal."""
    folder = _Folder.of(module)
    functions: dict[int, str] = {}
    for node in ast.walk(folder.tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(node):
                functions[id(inner)] = node.name
    out = []
    for node in ast.walk(folder.tree):
        if not isinstance(node, ast.Compare | ast.Call):
            continue
        checked: list[tuple[str, ast.expr]] = []
        if isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators, strict=True):
                if isinstance(op, ast.In | ast.NotIn):
                    checked.append(("in", node.left))
                elif isinstance(op, ast.Eq | ast.NotEq):
                    checked += [("==", node.left), ("==", right)]
        elif (isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr in _STR_READS and node.args
              and not _is_re_call(node, *_STR_READS)):
            checked.append((node.func.attr, node.args[0]))
        for how, arg in checked:
            for text in _literal_texts(folder, arg):
                if _MARKUP_LITERAL.search(text) \
                        and not _SPELLING_FREE.match(text):
                    where = functions.get(id(node), "<module>")
                    out.append((f"{where}: {how}({text})", node.lineno))
    return out


#: Every spelling-bound read of a markup literal in the package.
ALL_MARKUP_READS = sorted({(module, what, line) for module in _TREES
                           for what, line in _markup_reads(module)})

#: The reads that are exact ON PURPOSE, each with the reason: the text
#: searched is markup docxkit itself built, whose spelling is ours, or
#: the literal is not markup at all. A read of what an author's Word or
#: another producer wrote belongs in the code, widened — not here.
EXACT_READS: dict[tuple[str, str], str] = {
    ("body.py", "cell: in(<w:tcPr>)"): (
        "builder input: `body.cell` checks the `tcpr` a paper hands a "
        "builder that writes a new cell, markup the paper spelled for "
        "docxkit, never read out of a document"),
    ("body.py", "cell: replace(<w:tcPr>)"): (
        "builder input: the same `tcpr`, rewritten to carry a gridSpan "
        "into a cell docxkit is building from scratch"),
    ("equations.py", "_char: startswith(<font> )"): (
        "not markup: `unicodedata.decomposition` of a math-alphanumeric "
        "glyph begins `<font> ` followed by the base code point"),
}


def test_every_EXACT_markup_read_is_DECLARED():
    """A new spelling-bound read fails until it is widened or listed
    with its reason, and a listed one that is gone fails too."""
    found = {(module, what) for module, what, _line in ALL_MARKUP_READS}
    assert found - set(EXACT_READS) == set(), (
        "these read markup by one exact spelling. Another producer writes "
        "` />`, other attribute orders, `w:val` forms and empty elements: "
        "read with a pattern (`<w:tag\\b[^>]*/>`, a shared `_xml` reader) "
        "or, for markup docxkit itself built, declare it in EXACT_READS:"
        "\n  " + "\n  ".join(
            f"{module}:{line} {what}" for module, what, line
            in ALL_MARKUP_READS if (module, what) not in EXACT_READS))
    assert set(EXACT_READS) - found == set(), "declared, but no longer read"
    for key, reason in EXACT_READS.items():
        assert len(reason) > 40, (key, reason)


def test_the_markup_read_walk_sees_a_bound_literal_and_not_a_free_one():
    """The walk's own instrument."""
    _TREES["_probe_.py"] = ast.parse(
        'TAG = "<w:cantSplit/>"\n'
        "def f(row, cid, spans):\n"
        '    a = TAG not in row\n'
        '    b = row.find(f\'<w:bookmarkEnd w:id="{cid}"/>\')\n'
        '    c = row.count("<w:ins ")\n'
        '    d = "<w:ins" in row and row.rfind("</w:p>")\n'
        '    e = "(?<=[.:])" in row and row.startswith("<?xml")\n'
        '    g = any(m in row for m in ("<w:del/", "<w:pPrChange"))\n')
    _Folder._cache.pop("_probe_.py", None)
    try:
        found = sorted(what for what, _ in _markup_reads("_probe_.py"))
    finally:
        del _TREES["_probe_.py"]
        _Folder._cache.pop("_probe_.py", None)
    assert found == ["f: count(<w:ins )",
                     'f: find(<w:bookmarkEnd w:id="{}"/>)',
                     "f: in(<w:cantSplit/>)", "f: in(<w:del/)"]


#: The attributes a pattern may REQUIRE before it will match at all. Probed
#: with none, the note-definition patterns (`w:id="(-?\d+)"`) matched no
#: healthy spelling, were read as "not about this element", and skipped —
#: so `<w:footnote w:id="3"/>` swallowed the note after it for as long as
#: this gate existed (found by a survivor round, 2026-09-17). The same
#: attribute sits on both spellings, as it would in a document.
ATTRIBUTE_SPELLINGS = ("", ' w:id="1"',
                       ' w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z"',
                       ' w:type="separator" w:id="1"')


def _reads_empty_as_open(compiled: re.Pattern[str]) -> str | None:
    """The first EMPTY container `compiled` reads as an opening tag."""
    for prefix, tag, attrs in itertools.product(("w", "m"), CONTAINERS,
                                                ATTRIBUTE_SPELLINGS):
        healthy = f"<{prefix}:{tag}{attrs}>text</{prefix}:{tag}>"
        # Probed rather than read off the source, so an alternation
        # (`<(/?)w:(tbl|tr|tc|p)\b…`) is covered too.
        if (well := compiled.search(healthy)) is None:
            continue                    # not about this element
        if ">" not in well.group(0):
            continue                    # a counter: it pairs nothing
        empty = f"<{prefix}:{tag}{attrs}/>"
        hit = compiled.search(empty + healthy)
        if hit is None or hit.start() != 0:
            continue
        if any(g == "/" for g in hit.groups() if g is not None):
            continue        # it CAPTURES the slash: the caller is told
        if well.group(0) == healthy and hit.group(0) == empty:
            continue        # an ELEMENT matcher reading both forms whole
        return empty
    return None


#: Patterns the gate above flags and that are right as written, each
#: with the reason. Keyed by (module, pattern source) — never a line
#: number, which moves with every edit above it — so one entry covers
#: every call of that pattern in that module, and its reason must hold
#: for all of them. Only two reasons are admissible: the pattern is a
#: GENERIC TOKENIZER that never pairs an open tag with a close, or its
#: input has ALREADY been isolated as one non-empty element by a guarded
#: walk. Anything less certain is guarded in the code instead: a guard on
#: an isolated input costs nothing, an exemption that was wrong costs a
#: swallowed element.
NOT_AN_OPENING_TAG: dict[tuple[str, str], str] = {
    ("_cite_grammar.py", r"\S+"): (
        "generic tokenizer: splits VISIBLE text on whitespace to find the "
        "capitalised word a name starts on; it never sees markup"),
    ("_cite_repair.py", r"<w:p\b[^>]*>"): (
        "isolated input: `_mark_para_head` gets a paragraph matched by the "
        "guarded PARA_RE, through `para_slice` or `_cite_build`'s rebuild, "
        "so its open tag is never self-closing"),
    ("_table_layout.py", r"<w:r\b[^>]*>"): (
        "isolated input: `_run_superscripted` gets the last text run of a "
        "cell matched by the guarded RUN_RE, rewritten by `set_run_text`, "
        "which keeps the open tag as it was"),
    ("_table_layout.py", r"<w:tc\b[^>]*>"): (
        "isolated input: `_set_tc_w`, `_set_span` and `_set_borders` get a "
        "cell from `cells_of`, whose depth-counted `element_spans` walk "
        "steps over a self-closing `<w:tc/>` and returns only closed cells"),
    ("comments.py", r"<w:p(?: [^>]*)?>"): (
        "isolated input: `comment_paragraph` reads the open tag of a "
        "paragraph matched by the guarded PARA_RE, as the assert beside "
        "it says"),
    ("comments.py", "<[^>]+>"): (
        "generic tokenizer: strips every tag from the markup before a "
        "revision to leave the words a classifier reads, pairing nothing"),
    ("crossrefs.py", r"</?w:hyperlink[^>]*>"): (
        "generic tokenizer: deletes every hyperlink tag, open, close or "
        "self-closing ghost, inside one link element HYPERLINK_ANY_RE has "
        "already isolated with its own `(?<!/)>` guard"),
    ("equations.py", r"<\w[^>]*>"): (
        "generic tokenizer: the part's first element tag, read for its "
        "xmlns declarations, which a self-closing root carries identically"),
    ("revisions.py",
     "'<w:(?:' + '|'.join(_REVISION_NAMES) + ')(?=[ />])[^>]*>'"): (
        "generic tokenizer: `revision_elements` lists every pending "
        "revision's OWN tag and pairs nothing — a self-closing `<w:ins/>` "
        "in a paragraph mark's properties is a pending revision too, and "
        "is meant to be counted"),
    ("styles.py", r"<w:{prop}(?:\s*/>|\s+[^>]*?/>|\s*>)"): (
        "generic tokenizer: one toggle property's tag in any of its forms, "
        "read for `w:val` alone and never paired with a close tag"),
}


@pytest.mark.parametrize("module,name,source,probe,line", ALL_PATTERNS,
                         ids=lambda v: str(v)[:40])
def test_no_pattern_reads_an_EMPTY_container_as_an_opening_tag(
        module, name, source, probe, line):
    if (module, source) in NOT_AN_OPENING_TAG:
        return
    try:
        compiled = re.compile(probe, re.DOTALL)
    except re.error:                                    # pragma: no cover
        pytest.skip("built from another pattern at import time")
    empty = _reads_empty_as_open(compiled)
    assert empty is None, (
        f"{module}:{line} {name} reads {empty} as an OPENING tag and "
        f"pairs it with the next close, swallowing the element after it. "
        f"An empty element opens nothing: add the `(?<!/)>` guard that "
        f"_xml.PARA_RE and _xml.RUN_RE carry, or capture the slash where "
        f"the caller must still see the empty element.")


def test_every_exemption_names_a_pattern_that_still_needs_it():
    """A stale exemption fails: gone from the package, or no longer
    flagged — either way it would silently cover the next pattern
    written with that spelling, and its reason describes nothing."""
    probes = {(module, source): probe
              for module, _, source, probe, _ in ALL_PATTERNS}
    for key, reason in NOT_AN_OPENING_TAG.items():
        assert len(reason) > 40, (key, reason)
        assert key in probes, f"exempt, but no longer in the package: {key}"
        assert _reads_empty_as_open(re.compile(probes[key], re.DOTALL)), (
            f"exempt, but the gate no longer flags it: {key}")


def test_the_gate_tells_an_opening_tag_from_an_element():
    """The gate's own instrument, both ways round."""
    flagged = [r"<w:p\b[^>]*>", r"<w:comment [^>]*>(.*?)</w:comment>",
               r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>']
    for source in flagged:
        assert _reads_empty_as_open(re.compile(source, re.DOTALL)), source
    clean = [r"<w:p\b[^>]*(?<!/)>.*?</w:p>",
             r"<w:tc\b[^>]*?(/?)>",
             r"<w:p\b[^>]*?(?:/>|>.*?</w:p>)",
             r"<w:sz\b[^>]*/>"]
    for source in clean:
        assert _reads_empty_as_open(re.compile(source, re.DOTALL)) is None, \
            source


# --- attribute ORDER, the second divergence that bit -------------------
#
# An element written in another attribute order is the same element.
# `<w:tblW w:type="auto" w:w="0"/>` is what one accepted manuscript
# holds, and a pattern spelling `w:w` before `w:type` matched nothing
# there — so the table kept an auto width while its columns were divided
# in fixed dxa (CONTRIBUTING, "Four traps"). `_TBLW_RE` was rewritten;
# `_TCW_RE`, twelve lines above it in the same file, was not, and on a
# type-first cell it inserted a SECOND width beside the one it could not
# see. Measured 2026-09-03: 5 of 150 manuscripts spell `w:tcW` that way.

#: An XML name as a pattern spells one: an optional prefix, a local name.
_NAME = r"(?:[A-Za-z][\w.-]*:)?[A-Za-z][\w.-]*"

#: An attribute spelling: a name, `=`, and the start of a value. ANY
#: prefix, or none — the list this replaced named twelve, and the
#: comment-part readers spell `w15:`, `w16cid:` and `w16cex:`, so
#: `<w16cid:commentId w16cid:paraId="…"[^>]*w16cid:durableId=` insisted
#: on its order in plain sight; DrawingML's `cx`/`cy` and a relationship's
#: `Id`/`Target` carry no prefix at all. It runs over `_masked` text:
#: `\bw:id=` is pattern for "a boundary, then w:id=", and read raw its
#: `b` sat against the prefix and hid every attribute written that way —
#: most of the package's — from the detector (2026-09-17).
_ATTR = re.compile(rf"(?<![\w:.-]){_NAME}=(?=[\"'(\[\\])")

#: Pattern syntax that reads as letters, `<` or `=` to a text scan: the
#: class escapes, the lookbehind openers and named groups. Blanked, same
#: length, so an offset in the masked text is an offset in the source.
_ESCAPES = re.compile(r"\\[bBsSwWdD][+*?]?|\(\?<[!=]|\(\?P<\w+>|\(\?P=\w+\)")


def _masked(source: str) -> str:
    return _ESCAPES.sub(lambda m: " " * len(m.group(0)), source)


def _lookaheads(text: str) -> list[tuple[int, int]]:
    """The (start, end) of every `(?=…)` and `(?!…)` in `text`."""
    spans = []
    for opener in re.finditer(r"\(\?[=!]", text):
        depth, at = 1, opener.end()
        while at < len(text) and depth:
            if text[at] == "\\":
                at += 2
                continue
            depth += {"(": 1, ")": -1}.get(text[at], 0)
            at += 1
        spans.append((opener.start(), at))
    return spans


def _alternated(between: str) -> bool:
    """Does a `|` at the pair's own level sit between them?"""
    depth = 0
    for char in between:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "|" and depth <= 0:
            return True
    return False


def _order_bound(source: str) -> list[tuple[str, str]]:
    """The attribute pairs `source` insists on in sequence.

    Two attributes of one tag are free of each other only when the first
    is merely LOOKED FOR — inside a lookahead the second is not in —
    so the second is matched from the same place whichever comes first
    in the document. `[^>]*` between them lets other attributes sit
    there and still demands this order; that reading passed
    `w16cid:paraId=…[^>]*w16cid:durableId=` as free.
    """
    text = _masked(source)
    looks = _lookaheads(text)

    def holder(at: int) -> tuple[int, int] | None:
        return next((span for span in looks if span[0] <= at < span[1]),
                    None)

    out = []
    for a, b in itertools.pairwise(_ATTR.finditer(text)):
        between = text[a.end():b.start()]
        if "<" in between:              # the next element's, not this one's
            continue
        if _alternated(between):        # either, not both
            continue
        first = holder(a.start())
        if first is not None and first != holder(b.start()):
            continue
        out.append((a.group(0), b.group(0)))
    return out


#: Elements the schema gives exactly ONE attribute, so naming it first
#: binds no order. Each is its complex type's only attribute in ECMA-376
#: (CT_String, CT_DecimalNumber, CT_OnOff, CT_HpsMeasure,
#: CT_VerticalAlignRun, CT_TblGridCol, CT_NumLvl, CT_Markup, CT_OMathJc,
#: CT_VMerge). `w:bookmarkEnd` and `w:commentRangeStart` are NOT here:
#: CT_MarkupRange adds `w:displacedByCustomXml`, which a real draft
#: carries after `w:id`.
ONE_ATTRIBUTE = frozenset({
    "w:pStyle", "w:rStyle", "w:basedOn", "w:numStyleLink",
    "w:numId", "w:ilvl", "w:outlineLvl", "w:abstractNumId", "w:gridSpan",
    "w:b", "w:i", "w:sz", "w:vertAlign", "w:gridCol", "w:lvlOverride",
    "w:vMerge", "w:commentReference", "m:jc"})

#: A tag whose FIRST attribute the pattern names: `<w15:commentEx
#: w15:paraId=`. Over masked text, so `\s+` between them counts.
_PINNED = re.compile(rf"<({_NAME}) +({_NAME})=(?=[\"'(\[\\])")


def _pinned_first(source: str) -> list[tuple[str, str]]:
    """(element, attribute) for each attribute `source` demands comes
    first, on an element that can carry others."""
    return [(m.group(1), m.group(2))
            for m in _PINNED.finditer(_masked(source))
            if m.group(1) not in ONE_ATTRIBUTE]


#: An attribute value that CLOSES its tag: `w:name="X"\s*/>`, room for a
#: space and for nothing else.
_VALUE_CLOSES = re.compile(r'"\)?\??\s*/>')


def _pinned_last(source: str) -> list[tuple[str, str]]:
    r"""(element, attribute) for each attribute `source` demands comes
    LAST, on an element that can carry others — the mirror of a pin.

    `<w:bookmarkStart[^>]*w:name="X"\s*/>` let anything stand before the
    name and nothing after it, so `crossrefs.unlink` could not see a
    start written name-first, and `<w:bookmarkEnd w:id="N"\s*/>` missed
    an end carrying `w:displacedByCustomXml` (2026-09-17).
    """
    text = _masked(source)
    out = []
    for close in _VALUE_CLOSES.finditer(text):
        opener = text.rfind("<", 0, close.start())
        tag = (re.match(rf"<({_NAME})(?![\w.:-])", text[opener:])
               if opener != -1 else None)
        if tag is None or tag.group(1) in ONE_ATTRIBUTE:
            continue
        if attrs := _ATTR.findall(text[opener:close.end()]):
            out.append((tag.group(1), attrs[-1][:-1]))
    return out


#: What may stand before a tag's `/>` so that a space can: `\s*`, `\s+`,
#: `\s?`, ` *`, `[^>]*` and its kin, `.*?`.
_ROOMY = re.compile(r"(?:\\s[*+?]|\s[*+?]|\[\^[^\]]*\][*+]\??|\.[*+]\??)$")

#: Group brackets at the end of what precedes a `/>`, looked through:
#: `(?: [^>]*)?(?:/>` has room for a space, `(?: w:val="1")?/>` has none.
_GROUP_EDGE = re.compile(r"(?:\(\?:|\(|\)[*+?]?)+$")


def _closes_tight(source: str) -> list[str]:
    r"""Each `<tag … />` in `source` whose `/>` allows no space before it.

    `<w:sz w:val="20" />` is the element `<w:sz w:val="20"/>` is, and
    other producers write the space — 16,373 `w:sz` in 32 of 2,954 corpus
    packages, 5,183 `w:gridSpan` in 8. A pattern that ends
    `w:val="(\d+)"/>` reads none of them.
    """
    out, in_class, at = [], False, 0
    while at < len(source):
        char = source[at]
        if char == "\\":
            at += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif source.startswith("/>", at):
            before = _GROUP_EDGE.sub("", source[:at])
            if not _ROOMY.search(before):
                out.append(source[max(source.rfind("<", 0, at), 0):at + 2])
        at += 1
    return out


def test_the_detector_sees_an_order_bound_pair_and_not_a_free_one():
    """The gate's own instrument, both ways round."""
    bound = {
        r'<w:tcW w:w="[^"]*" w:type="\w+"/>': [("w:w=", "w:type=")],
        r'<w16cid:commentId w16cid:paraId="1"[^>]*w16cid:durableId="(\w+)"':
            [("w16cid:paraId=", "w16cid:durableId=")],
        r'<w:x\b[^>]*\bw:a="1"[^>]*\bw:b="2"': [("w:a=", "w:b=")],
        r'<w:x\b[^>]*\bw:a="1"(?=[^>]*\bw:b="2")': [("w:a=", "w:b=")],
        r'<w:x\b(?=[^>]*\bw:a="1"[^>]*\bw:b="2")': [("w:a=", "w:b=")],
        r'<wp:extent cx="(\d+)" cy="(\d+)"/>': [("cx=", "cy=")],
        r'Id="\w+"[^>]*Target="([^"]+)"': [("Id=", "Target=")],
    }
    for source, pairs in bound.items():
        assert _order_bound(source) == pairs, source
    free = [r'<w:tblW\b[^>]*/>',
            r'<w:style\b(?=[^>]*\bw:type="p")(?=[^>]*\bw:default="1")'
            r'[^>]*\bw:styleId="([^"]+)"',
            r'<w:fldChar\b[^>]*w:fldCharType="begin"[^>]*/>(.*?)'
            r'<w:fldChar\b[^>]*w:fldCharType="end"',
            r'<w16du:x\b(?=[^>]*\bw16du:a="1")[^>]*\bw16se:b="2"',
            r'<w:x\b[^>]*(?:\bw:a="1"|\bw:b="2")',
            r'<w:p\b[^>]*(?<!/)>.*?<w:r\b[^>]*w:rsidR=',
            r'(?P<year>\d{4})(?P=year)',
            r'(?P<names>[^()]*?)\s+\((?P<years>\d{4})\)']
    for source in free:
        assert _order_bound(source) == [], source


def test_the_detector_reads_every_attribute_PREFIX():
    """Not a list of the ones someone thought of: every prefix the
    package's patterns spell is read, the Word 2012+ ones and none at
    all included."""
    for prefix in ("w:", "m:", "r:", "a:", "wp:", "mc:", "w14:", "w15:",
                   "w16cid:", "w16cex:", "w16du:", "w16se:", "xml:", ""):
        spelled = rf'<{prefix}x {prefix}a="1" {prefix}b="2"'
        assert _order_bound(spelled) == [(f"{prefix}a=", f"{prefix}b=")]
    seen = {m.group(0).rpartition(":")[0]
            for *_, probe, _line in ALL_PATTERNS
            for m in _ATTR.finditer(_masked(probe))}
    assert {"w", "w14", "w15", "w16cid", "w16cex", ""} <= seen, seen


def test_the_detector_sees_an_attribute_PINNED_first():
    assert _pinned_first(r'<w15:commentEx w15:paraId="{key}"[^>]*/>') == [
        ("w15:commentEx", "w15:paraId")]
    assert _pinned_first(r'<w:fldChar\s+w:fldCharType="end"\s*/>') == [
        ("w:fldChar", "w:fldCharType")]
    assert _pinned_first(r'<Override PartName="/word/x.xml"') == [
        ("Override", "PartName")]
    assert _pinned_first(r'<w:rStyle w:val="Hyperlink"/>') == []
    assert _pinned_first(r'<w:fldChar\b[^>]*\bw:fldCharType="end"') == []


def test_the_detector_sees_an_attribute_PINNED_last():
    assert _pinned_last(r'<w:bookmarkStart[^>]*w:name="\w+"\s*/>') == [
        ("w:bookmarkStart", "w:name")]
    assert _pinned_last(r'<w:bookmarkEnd w:id="(\d+)"\s*/>') == [
        ("w:bookmarkEnd", "w:id")]
    assert _pinned_last(r'<wp:extent cx="(\d+)" cy="(\d+)"/>') == [
        ("wp:extent", "cy")]
    for free in (r'<w:bookmarkEnd\b[^>]*\bw:id="(\d+)"[^>]*/>',
                 r'<w:vMerge(?:\s+w:val="(\w+)")?\s*/>',
                 r'<w:\w+(?:\s*/>|\s+w:val="([^"]*)"\s*/>)',
                 r'<w:vertAlign w:val="[^"]*"\s*/>'):
        assert _pinned_last(free) == [], free


def test_no_pattern_pins_an_attribute_LAST_on_an_element_with_others():
    pinned = sorted({f"{module}:{line} {name} pins {pairs}"
                     for module, name, _source, probe, line in ALL_PATTERNS
                     if (pairs := _pinned_last(probe))})
    assert pinned == [], (
        "`w:attr=\"…\"\\s*/>` demands that attribute come LAST, and "
        "another producer need not write it there (a bookmark end "
        "carrying `w:displacedByCustomXml` after its id). Close the tag "
        "`[^>]*/>`, or add the element to ONE_ATTRIBUTE if the schema "
        "gives it no other attribute:\n  " + "\n  ".join(pinned))


def test_the_detector_sees_a_self_close_with_no_room_for_a_SPACE():
    for tight in (r'<w:gridSpan w:val="(\d+)"/>',
                  r'<w:b(?: w:val="(?:1|true|on)")?/>',
                  r'<w:tab/>'):
        assert _closes_tight(tight) == [tight], tight
    for roomy in (r'<w:gridSpan w:val="(\d+)"\s*/>',
                  r'<w:tblW\b[^>]*/>',
                  r'<w:i(?: [^>]*)?(?:/>|>)',
                  r'<w:pgSz([^/]*)/>',
                  r'<w15:commentEx [^/>]*/>',
                  r'<w:tc\b[^>]*?(/?)>',
                  r'<w:p\b[^>]*(?<!/)>'):
        assert _closes_tight(roomy) == [], roomy


def test_no_pattern_binds_two_attributes_of_one_element_to_an_ORDER():
    bound = sorted({f"{module}:{line} {name} insists on {pairs}"
                    for module, name, _source, probe, line in ALL_PATTERNS
                    if (pairs := _order_bound(probe))})
    assert bound == [], (
        "an element written in another attribute order is the same "
        "element, and Word writes both orders (5 of 150 manuscripts for "
        "w:tcW). Spell the attribute you want as `\\b[^>]*\\bw:name=`, "
        "look for the others with `(?=[^>]*\\bw:other=…)`, or match the "
        "whole tag with `<w:tag\\b[^>]*/>` and read it after:\n  "
        + "\n  ".join(bound))


def test_no_pattern_pins_an_attribute_FIRST_on_an_element_with_others():
    pinned = sorted({f"{module}:{line} {name} pins {pairs}"
                     for module, name, _source, probe, line in ALL_PATTERNS
                     if (pairs := _pinned_first(probe))})
    assert pinned == [], (
        "`<w:tag w:attr=` demands that attribute come FIRST, and another "
        "producer need not write it there (25 `w15:commentEx` in 2 "
        "packages put `w15:done` before `w15:paraId`). Spell it "
        "`<w:tag\\b[^>]*\\bw:attr=`, or add the element to ONE_ATTRIBUTE "
        "if the schema gives it no other attribute:\n  "
        + "\n  ".join(pinned))


def test_no_pattern_closes_a_tag_with_no_room_for_a_SPACE():
    tight = sorted({f"{module}:{line} {name} spells {hits}"
                    for module, name, _source, probe, line in ALL_PATTERNS
                    if (hits := _closes_tight(probe))})
    assert tight == [], (
        "`<w:sz w:val=\"20\" />` is the same element as `<w:sz "
        "w:val=\"20\"/>`, and other producers write the space (32 of 2,954 "
        "corpus packages). Close the tag `\\s*/>`, or `[^>]*/>` where "
        "other attributes may follow:\n  " + "\n  ".join(tight))
