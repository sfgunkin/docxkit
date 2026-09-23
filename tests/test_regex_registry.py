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
from typing import Any, ClassVar, NamedTuple

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
#: question, asked by the name-END gate at the bottom of this file.
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
    return [(what, line) for what, text, line in _literal_reads(module)
            if not _SPELLING_FREE.match(text)]


def _literal_reads(module: str) -> list[tuple[str, str, int]]:
    """(description, literal, line) for each read of a markup literal."""
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
                if _MARKUP_LITERAL.search(text):
                    where = functions.get(id(node), "<module>")
                    out.append((f"{where}: {how}({text})", text,
                                node.lineno))
    return out


#: Every read of a markup literal in the package, and the spelling-bound
#: ones among them.
ALL_LITERAL_READS = sorted({(module, what, text, line) for module in _TREES
                            for what, text, line in _literal_reads(module)})
ALL_MARKUP_READS = sorted({(module, what, line)
                           for module, what, text, line in ALL_LITERAL_READS
                           if not _SPELLING_FREE.match(text)})

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


# --- what a probe is built FROM: the pattern's own spellings -------------
#
# A fixed probe, `<w:x ATTRS>text</w:x>`, matched nothing a pattern needed
# MORE of — a link's `w:anchor`, a field's `w:instr`, a run holding a
# `w:commentReference` — and such a pattern was read as "not about this
# element" and skipped, with nothing saying so. The probe is now built
# from what the pattern itself spells: its attributes, with the literal
# value where it gives one, and the other elements it names, as content.
# Every container a pattern opens is exercised, or declared below.

#: `w:name`, `(?:w|m):name`, `w:(?:a|b)` and `w:(a|b)Suffix`, over
#: `_hole_masked` text; followed by `=`, an attribute.
_SPELLED = re.compile(
    r"(?<![\w.-])(?P<prefix>[A-Za-z]\w*|\((?:\?:)?\w+(?:\|\w+)+\)):"
    r"(?:(?P<name>[A-Za-z]\w*)|\((?:\?:)?(?P<names>\w+(?:\|\w+)*)\)"
    r"(?P<suffix>\w*))(?P<attr>=?)")

#: `(m:nor|m:sty|w:i)`: qualified names as one group's alternatives.
_QUALIFIED_ALTERNATIVES = re.compile(r"\((?:\?:)?(\w+:\w+(?:\|\w+:\w+)+)\)")

#: An element name the pattern leaves OPEN — `<w:\w+\b`, `<\w[^>]*>`,
#: `<[^>]+>` — which any container's name fills. A hole followed by
#: letters (`<w:\w+PrChange`) names a family, not a container.
_ANY_NAME = re.compile(
    r"<(?:\(/\?\)|/\?)?(?:(?:[A-Za-z]\w*|\0{2,}+|\[[^\]]*\][*+?]?):)?"
    r"(?:\0{2,}+|\[[^\]]*\][*+?]?)(?![A-Za-z])")

#: A name spelled as a group `_SPELLED` cannot read — one holding
#: another group, `<w:(?:ins|move(?:From|To))` — which may be any
#: container's name as far as this gate can tell.
_TANGLED_NAME = re.compile(r"<(?:[A-Za-z]\w*|\((?:\?:)?\w+(?:\|\w+)+\)):"
                           r"\((?:\?:)?[^()]*\(")

#: `name="value"` with a plain value, which a probe has to repeat:
#: `w:type="dxa"` matches no `w:type="1"`.
_LITERAL_VALUE = re.compile(
    r"(?<![\w:.-])((?:[A-Za-z]\w*:)?[A-Za-z]\w*)=\"([\w.-]*)\"")

#: An opening tag a healthy match passes through.
_OPENING = re.compile(r"<(\w+):(\w+)(\s[^<>]*?)?(?<!/)>")


def _hole_masked(source: str) -> str:
    """`_masked`, blanked with NUL: a class escape is a hole, and must not
    read as the whitespace a pattern spells for real."""
    return _ESCAPES.sub(lambda m: "\0" * len(m.group(0)), source)


def _spellings(probe: str) -> tuple[set[tuple[str, str]], list[str]]:
    """The (prefix, name) of each element `probe` spells where a tag OPENS,
    and ` name="value"` for each attribute it spells."""
    masked = _hole_masked(probe)
    values = dict(_LITERAL_VALUE.findall(masked))
    elements: set[tuple[str, str]] = set()
    attributes: list[str] = []
    for m in _SPELLED.finditer(masked):
        prefixes = m.group("prefix").strip("()?:").split("|")
        names = ([m.group("name")] if m.group("name") else
                 [n + m.group("suffix") for n in m.group("names").split("|")])
        if m.group("attr"):
            attributes += [f' {p}:{n}="{values.get(f"{p}:{n}", "1")}"'
                           for p in prefixes for n in names]
        elif masked[max(0, m.start() - 2):m.start()] != "</":
            elements |= {(p, n) for p in prefixes for n in names}
    for m in _QUALIFIED_ALTERNATIVES.finditer(masked):
        for qualified in m.group(1).split("|"):
            prefix, _, name = qualified.partition(":")
            elements.add((prefix, name))
    return elements, list(dict.fromkeys(attributes))


def _contents(elements: set[tuple[str, str]], attributes: str) -> list[str]:
    """What a healthy container holds: nothing, text, or one or two of the
    elements the pattern names, each empty, holding text, or open and shut.

    Nothing is a reading in its own right — `_xml._BARE_RUN_RE` is about
    a run that holds exactly that — and a probe that always puts content
    in never reaches such a pattern.
    """
    singles = [form
               for prefix, name in sorted(elements)
               for attrs in dict.fromkeys(("", attributes))
               for form in (f"<{prefix}:{name}{attrs}/>",
                            f"<{prefix}:{name}{attrs}>text</{prefix}:{name}>",
                            f"<{prefix}:{name}{attrs}></{prefix}:{name}>")]
    return ["", "text", *singles,
            *(a + b for a, b in itertools.product(singles, repeat=2))]


class _Reading(NamedTuple):
    """How one pattern reads the containers it may open."""

    flagged: str | None     # the first EMPTY one it reads as an opening tag
    by_name: frozenset[str]  # read by name or attribute alone: undecidable
    unreached: frozenset[str]  # named, but no probe reached it


def _slash(hit: re.Match[str]) -> bool:
    return any(g == "/" for g in hit.groups() if g is not None)


def _tails(probe: str) -> list[str]:
    """`probe`, and every part of it from a `<` at its OWN level on.

    A pattern whose match starts on something else — a field's
    `<w:fldChar …/>` — opens its runs only after context no probe builds,
    and was never reached. Cut at the level of the pattern itself, the
    rest is a pattern of its own that starts on the tag.
    """
    tails, depth, at, in_class = [probe], 0, 0, False
    while at < len(probe):
        char = probe[at]
        if char == "\\":
            at += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
            if probe.startswith("[^]", at):
                at += 2             # a `]` first in a class is a member
            elif probe.startswith("[]", at):
                at += 1
        elif char in "()":
            depth += 1 if char == "(" else -1
        elif char == "<" and not depth and at:
            tails.append(probe[at:])
        at += 1
    return tails


def _reading(probe: str) -> _Reading | None:
    """What `probe` does with an empty container, or None if it names none.

    Probed rather than read off the source, so an alternation
    (`<(/?)w:(tbl|tr|tc|p)\\b…`) is covered too. The container a match
    STARTS on is asked as it always was — the empty form, then a healthy
    element — and a container the match opens further in is asked by
    swapping its opening tag for the empty form, unless the pattern never
    needed that tag (it sat in a wildcard).
    """
    elements, attributes = _spellings(probe)
    named = {(p, n) for p, n in elements if n in CONTAINERS}
    masked = _hole_masked(probe)
    any_name = (_ANY_NAME.search(masked) is not None
                or _TANGLED_NAME.search(masked) is not None)
    if not named and not any_name:
        return None
    wanted = named | ({(p, c) for p in ("w", "m") for c in CONTAINERS}
                      if any_name else set())
    reached: set[tuple[str, str]] = set()
    by_name: set[str] = set()
    for tail in _tails(probe):
        try:
            compiled = re.compile(tail, re.DOTALL)
        except re.error:
            continue                # it names a group the cut left behind
        flagged = _exercise(compiled, wanted, elements, attributes,
                            reached, by_name)
        if flagged is not None:
            return _Reading(flagged, frozenset(), frozenset())
    unreached = {f"{p}:{n}" for p, n in named - reached}
    if any_name and not reached:
        unreached.add("any element name")
    return _Reading(None, frozenset(by_name), frozenset(unreached))


def _exercise(compiled: re.Pattern[str], wanted: set[tuple[str, str]],
              elements: set[tuple[str, str]], attributes: list[str],
              reached: set[tuple[str, str]], by_name: set[str]) -> str | None:
    """The first empty container `compiled` reads as an opening tag, or
    None; what it reached, or read by name alone, is added to the sets."""
    own = "".join(attributes)
    for (prefix, tag), attrs in itertools.product(
            sorted(wanted), dict.fromkeys((*ATTRIBUTE_SPELLINGS, own,
                                           *attributes))):
        empty = f"<{prefix}:{tag}{attrs}/>"
        others = {(p, n) for p, n in elements if n != tag}
        for inner in _contents(others, own):
            healthy = f"<{prefix}:{tag}{attrs}>{inner}</{prefix}:{tag}>"
            well = compiled.search(healthy)
            if well is None or well.start():
                alone = compiled.search(empty)
                if well is None and alone is not None \
                        and alone.group(0) == empty:
                    reached.add((prefix, tag))   # reads the EMPTY form only
                continue
            hit = compiled.search(empty + healthy)
            if (hit is None or hit.start() or _slash(hit)
                    or (well.group(0) == healthy and hit.group(0) == empty)):
                reached.add((prefix, tag))
            elif ">" in well.group(0):
                return empty
            else:
                by_name.add(f"{prefix}:{tag}")
            for opening in _OPENING.finditer(well.group(0), 1):
                if opening.group(2) not in CONTAINERS:
                    continue
                gone = compiled.search(healthy[:opening.start()]
                                       + healthy[opening.end():])
                if gone is not None and not gone.start():
                    continue            # wildcard content, not a token
                twin = (f"<{opening.group(1)}:{opening.group(2)}"
                        f"{opening.group(3) or ''}/>")
                sick = healthy[:opening.start()] + twin \
                    + healthy[opening.end():]
                hit = compiled.search(sick)
                if hit is not None and not hit.start() and not _slash(hit):
                    return f"{twin} in {sick}"
                reached.add((opening.group(1), opening.group(2)))
    return None


def _reads_empty_as_open(probe: str) -> str | None:
    """The first EMPTY container `probe` reads as an opening tag."""
    reading = _reading(probe)
    return reading.flagged if reading is not None else None


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
        re.compile(probe, re.DOTALL)
    except re.error:                                    # pragma: no cover
        pytest.skip("built from another pattern at import time")
    empty = _reads_empty_as_open(probe)
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
    probes: dict[tuple[str, str], list[str]] = {}
    for module, _, source, probe, _ in ALL_PATTERNS:
        probes.setdefault((module, source), []).append(probe)
    for key, reason in NOT_AN_OPENING_TAG.items():
        assert len(reason) > 40, (key, reason)
        assert key in probes, f"exempt, but no longer in the package: {key}"
        assert any(_reads_empty_as_open(p) for p in probes[key]), (
            f"exempt, but the gate no longer flags it: {key}")


def test_the_gate_tells_an_opening_tag_from_an_element():
    """The gate's own instrument, both ways round — and for the patterns
    a fixed `<w:x>text</w:x>` probe never reached: one that needs an
    attribute, one that needs content, one that opens its container
    after another."""
    flagged = [r"<w:p\b[^>]*>", r"<w:comment [^>]*>(.*?)</w:comment>",
               r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>',
               r'<w:hyperlink\b[^>]*w:anchor="(\w+)"[^>]*>.*?</w:hyperlink>',
               r'<w:fldSimple\b[^>]*w:type="dxa"[^>]*>',
               r"<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:commentReference\b[^>]*/>",
               r"<w:tc>\s*<w:p\b[^>]*>"]
    for source in flagged:
        assert _reads_empty_as_open(source), source
    clean = [r"<w:p\b[^>]*(?<!/)>.*?</w:p>",
             r"<w:tc\b[^>]*?(/?)>",
             r"<w:p\b[^>]*?(?:/>|>.*?</w:p>)",
             r"<w:sz\b[^>]*/>",
             r'<w:hyperlink\b[^>]*w:anchor="(\w+)"[^>]*(?<!/)>.*?</w:hyperlink>',
             r"<w:tc>\s*<w:p\b[^>]*(?<!/)>",
             r"<w:p\b[^>]*(?<!/)>.*?</w:p>|<w:tbl\b[^>]*(?<!/)>"]
    for source in clean:
        assert _reads_empty_as_open(source) is None, source


def test_the_gate_says_what_it_CANNOT_decide():
    """A pattern that reads a container's name and stops before the tag
    ends matches the empty form exactly as the open one; one that opens a
    container only after context no probe builds is never reached. Both
    are reported, never passed as clean."""
    by_name = _reading(r"<w:ins(?=[\s/>])")
    assert by_name is not None and by_name.by_name == {"w:ins"}
    unreached = _reading(r"(?:<w:fldChar\b[^>]*/>\s*<w:r\b[^>]*(?<!/)>)+")
    assert unreached is not None and unreached.unreached == {"w:r"}
    # ...but cut at its own level, a pattern opens its container in a tail
    assert _reads_empty_as_open(r"<w:fldChar\b[^>]*/>\s*<w:r\b[^>]*>")
    assert _reading(r"<w:\w+PrChange\b") is None, "a family, not a container"
    assert _reading(r"<w:sz\b[^>]*/>") is None
    # a name spelled as a group inside a group is read as ANY name, not
    # as none: `_SPELLED` cannot take it apart, and skipping it is how a
    # container goes unexercised with nothing said
    tangled = _reading(r"<w:(?:ins|move(?:From|To))(?=[\s/>])")
    assert tangled is not None and tangled.by_name


#: Patterns about a container that no probe can DECIDE, each with what
#: its caller does with an empty one. Two kinds, and only two. A reader of
#: the tag's NAME or ATTRIBUTES stops before the tag ends, so `<w:ins …/>`
#: and `<w:ins …>` match it alike, and whether that matters is the
#: caller's question — the reason answers it. A pattern that opens a
#: container only after context no probe builds is never reached, and the
#: reason says why its reading is right. Keyed like the exemptions above.
#: A paragraph mark's insertion or deletion is the EMPTY `<w:ins …/>` in
#: its `w:rPr`, and it is a revision like any other — which is what most
#: of the name readers below count.
NOT_EXERCISED: dict[tuple[str, str], str] = {
    ("_tracked_gates.py", r"<w:ins(?=[\s/>])"): (
        "name reader: `package_counts` counts insertions as Word does, and "
        "a paragraph mark's empty one is an insertion"),
    ("_tracked_gates.py", r"<w:del(?=[\s/>])"): (
        "name reader: `package_counts` counts deletions as Word does, and "
        "a paragraph mark's empty one is a deletion"),
    ("_tracked_gates.py", r"<w:{tag}\b"): (
        "name reader: `structure_counts` compares element counts before "
        "and after a batch; an empty table, row or cell is one element on "
        "both sides alike, and nothing is paired"),
    ("_xml.py", r'<w:comment\b[^>]*w:id="(\d+)"'): (
        "attribute reader: COMMENT_ID_RE takes every comment's id, for the "
        "next free id and the comment count, and an empty comment holds "
        "an id like any other"),
    ("batch.py", r"<w:(ins|del)\b"): (
        "name reader: `run` refuses to stack a batch on pending revisions, "
        "and a paragraph mark's empty insertion is one still pending"),
    ("batch.py", r"<w:tr\b"): (
        "name reader: `invariants` counts rows before and after an edit; "
        "an empty row is one row on both sides, and nothing is paired"),
    ("batch.py", r'<w:rStyle w:val="Hyperlink"\s*/>(?:[^<]|<(?!/w:rPr>))*'
                 r"</w:rPr><w:t[^>]*>([^<]*)</w:t>"): (
        "label reader: `diagnose` names the text of a Hyperlink-styled "
        "run, reading the rest of that run's OWN rPr up to its close; an "
        "empty `<w:rPr/>` holds no style, so it is no label to name"),
    ("body.py", r"<w:p(?=[\s/>])"): (
        "name reader: `cell` asks whether its content STARTS as a "
        "paragraph, and an empty `<w:p/>` is one to pass through as is"),
    ("cli.py", r"<w:del(?=[\s/>])"): (
        "name reader: `cmd_math` says a file is read accepted when "
        "it carries any deletion, a paragraph mark's empty one included"),
    ("comments.py", r'<w:p [^>]*w14:paraId="([0-9A-Fa-f]+)"'): (
        "attribute reader: a comment's paragraph ids, the LAST of which "
        "commentsExtended keys on; an empty last paragraph holds that id"),
    ("equations.py", r"<w:del(?=[\s/>])"): (
        "name reader: `_accepted_side` asks only whether any deletion is "
        "there; `element_spans`, which steps over empty ones, cuts them"),
    ("footnotes.py",
     r"<(?:w:bookmarkStart|w:hyperlink|w:drawing|w:tbl|m:oMath|w:pict"
     r"|w:object|w:sym|w:contentPart)\b"
     r"|<w:delText\b[^>]*(?<!/)>(?!\s*</w:delText>)"): (
        "name reader: counts a note's carriers so a note holding one is "
        "never cut as a shell; an empty link or table counted can only "
        "KEEP a note (none is kept so in 2,954 corpus packages)"),
    ("refstyle.py", r"<w:p[\s/]"): (
        "name reader: `refile` names an EMPTY paragraph in the gap above a "
        "reference, and `<w:p/>` is exactly what it is written to find"),
    ("refstyle.py", r'<w:{tag}\b[^>]*?\bw:{attr}="([^"]*)"'): (
        "attribute reader: `_declared` reads the `w:ind` and `w:spacing` "
        "attributes `_LAYOUT_RULES` names out of one live pPr; no "
        "container is ever named"),
    ("renumber.py", r'(<w:footnote\b[^>]*?w:id=")(-?\d+)(")'): (
        "attribute reader: `remap_ids` rewrites every note's id, and an "
        "empty `<w:footnote w:id=…/>` holds an id and a place in the order "
        "like any other (see `_FN_EL_RE`)"),
    ("revision/_losses.py", r"<w:ins(?=[\s/>])"): (
        "name reader: `moved_footnotes` takes a note with an insertion and "
        "no deletion as a CANDIDATE only, which `emptied_footnotes` then "
        "measures by rejecting"),
    ("revision/_losses.py", r"<w:del(?=[\s/>])"): (
        "name reader: the other half of `moved_footnotes`' candidate shape; "
        "a paragraph mark's empty deletion is a deletion there too"),
    ("revisions.py",
     r"<w:(?:ins|del|moveFrom|moveTo|moveFromRangeStart|moveFromRangeEnd"
     r"|moveToRangeStart|moveToRangeEnd)(?=[\s/>])"): (
        "name reader: `_has_content_revisions` asks whether there is any "
        "insertion, deletion or move to simulate, and a paragraph mark's "
        "empty insertion is one"),
    ("revisions.py", "<w:ins "): (
        "name reader: `counts` is the (insertions, deletions) element count "
        "`cli` prints, and a paragraph mark's empty insertion is one"),
    ("revisions.py", "<w:del "): (
        "name reader: `counts` is the (insertions, deletions) element count "
        "`cli` prints, and a paragraph mark's empty deletion is one"),
    ("sections.py", r"<w:(?:ins|del|moveFrom|moveTo)\b"): (
        "name reader: `renumber` refuses a paragraph carrying tracked "
        "changes, and a revision on its mark is one; refusing is safe"),
    ("sections.py", r'<w:{tag} w:val="([^"]*)"'): (
        "attribute reader: a numbering level's `w:val` properties (start, "
        "numFmt, lvlText…); `w:val` is on no container at all"),
    ("styles.py", r'<w:{name} w:val="([^"]*)"'): (
        "attribute reader: a style's `w:name`/`w:basedOn` value; `w:val` "
        "is on no container at all"),
    ("styles.py", r'<w:{prop}\b[^>]*\bw:val="([^"]*)"'): (
        "attribute reader: one run property's `w:val` inside an rPr; "
        "`w:val` is on no container at all"),
    ("styles.py", r'<w:{tag}\b[^>]*?\bw:{attr}="([^"]*)"'): (
        "attribute reader: `paragraph_property` reads the property "
        "attributes its callers name (`w:ind`, `w:spacing`) out of one "
        "pPr; no container is ever named"),
}


def _undecided() -> dict[tuple[str, str], str]:
    """(module, source) -> what the probes could not decide about it."""
    out: dict[tuple[str, str], set[str]] = {}
    for module, _, source, probe, _ in ALL_PATTERNS:
        try:
            reading = _reading(probe)
        except re.error:                                # pragma: no cover
            continue
        if reading is None or reading.flagged is not None:
            continue
        said = {f"read by name: {n}" for n in reading.by_name} | {
            f"never reached: {n}" for n in reading.unreached}
        if said:
            out.setdefault((module, source), set()).update(said)
    return {key: "; ".join(sorted(said)) for key, said in out.items()}


def test_every_container_a_pattern_opens_is_EXERCISED_or_declared():
    """Nothing silently skipped: a pattern the probes cannot decide is
    declared in NOT_EXERCISED with its caller's reason, or it fails."""
    new = {key: said for key, said in _undecided().items()
           if key not in NOT_EXERCISED and key not in NOT_AN_OPENING_TAG}
    assert not new, "\n".join(f"{m}: {s!r}: {said}"
                              for (m, s), said in sorted(new.items()))


def test_every_declared_pattern_is_still_one_the_probes_cannot_decide():
    """A stale declaration fails: gone from the package, or exercised now,
    it would cover the next pattern written that way for no reason."""
    undecided = _undecided()
    for key, reason in NOT_EXERCISED.items():
        assert len(reason) > 40, (key, reason)
        assert key in undecided, f"declared, but gone or exercised: {key}"


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


# --- element NAMES read without an END ----------------------------------
#
# `<w:t` also begins `<w:tab`, `<w:tbl` and forty more names; `<w:p`
# begins `<w:pPr`, `<w:proofErr` and `<w:permStart`; `w:moveFrom` begins
# `w:moveFromRangeStart`. A pattern or a plain read that spells a name
# and nothing to END it — `\b`, `[\s/>]`, a space, `>`, `/` — reads the
# longer names too. `probe` placed bookmarks by `rfind("<w:p")` and called
# 347 of them in 98 corpus packages nested (2026-09-17).

#: Each element name the package spells that begins a LONGER name, and
#: those names: every element name found in at least two of 2,954 corpus
#: packages (2026-09-17), by the name it begins with.
LONGER_NAMES: dict[str, str] = {
    "Relationship": "Relationships",
    "a:ext": "a:extLst a:extraClrSchemeLst",
    "m:acc": "m:accPr",
    "m:bar": "m:barPr",
    "m:box": "m:boxPr",
    "m:d": "m:dPr m:defJc m:deg m:degHide m:den m:dispDef",
    "m:eqArr": "m:eqArrPr",
    "m:f": "m:fName m:fPr m:func m:funcPr",
    "m:func": "m:funcPr",
    "m:groupChr": "m:groupChrPr",
    "m:limLow": "m:limLowPr",
    "m:limUpp": "m:limUppPr",
    "m:m": "m:mPr m:mathFont m:mathPr m:maxDist m:mc m:mcJc m:mcPr m:mcs m:mr",
    "m:nary": "m:naryLim m:naryPr",
    "m:oMath": "m:oMathPara m:oMathParaPr",
    "m:oMathPara": "m:oMathParaPr",
    "m:r": "m:rMargin m:rPr m:rad m:radPr",
    "m:rad": "m:radPr",
    "m:sSub": "m:sSubPr m:sSubSup m:sSubSupPr",
    "m:sSubSup": "m:sSubSupPr",
    "m:sSup": "m:sSupPr",
    "m:t": "m:type",
    "w:abstractNum": "w:abstractNumId",
    "w:b": (
        "w:bCs w:background w:balanceSingleByteDoubleByteWidth w:bar "
        "w:basedOn w:bdr w:behavior w:behaviors w:between w:bidi "
        "w:blockQuote w:body w:bodyDiv w:bookmarkEnd w:bookmarkStart "
        "w:bordersDoNotSurroundFooter w:bordersDoNotSurroundHeader w:bottom "
        "w:br"),
    "w:body": "w:bodyDiv",
    "w:comment": (
        "w:commentRangeEnd w:commentRangeStart w:commentReference "
        "w:comments"),
    "w:del": "w:delInstrText w:delText",
    "w:document": "w:documentProtection",
    "w:drawing": "w:drawingGridHorizontalSpacing w:drawingGridVerticalSpacing",
    "w:endnote": "w:endnotePr w:endnoteRef w:endnoteReference w:endnotes",
    "w:endnoteRef": "w:endnoteReference",
    "w:footnote": "w:footnotePr w:footnoteRef w:footnoteReference w:footnotes",
    "w:footnoteRef": "w:footnoteReference",
    "w:i": (
        "w:iCs w:id w:ilvl w:ind w:ins w:insideH w:insideV w:instrText "
        "w:isLgl"),
    "w:ins": "w:insideH w:insideV w:instrText",
    "w:lvl": "w:lvlJc w:lvlOverride w:lvlRestart w:lvlText",
    "w:moveFrom": "w:moveFromRangeEnd w:moveFromRangeStart",
    "w:moveTo": "w:moveToRangeEnd w:moveToRangeStart",
    "w:num": (
        "w:numFmt w:numId w:numIdMacAtCleanup w:numPr w:numRestart "
        "w:numbering"),
    "w:numId": "w:numIdMacAtCleanup",
    "w:p": (
        "w:pBdr w:pPr w:pPrChange w:pPrDefault w:pStyle w:pageBreakBefore "
        "w:panose1 w:pgBorders w:pgMar w:pgNum w:pgNumType w:pgSz w:pict "
        "w:pitch w:placeholder w:pos w:position w:proofErr w:proofState "
        "w:ptab"),
    "w:pPr": "w:pPrChange w:pPrDefault",
    "w:r": (
        "w:rFonts w:rPr w:rPrChange w:rPrDefault w:rStyle w:relyOnVML "
        "w:removeDateAndTime w:removePersonalInformation w:revisionView "
        "w:right w:rsid w:rsidRoot w:rsids w:rtl"),
    "w:rPr": "w:rPrChange w:rPrDefault",
    "w:sdt": "w:sdtContent w:sdtEndPr w:sdtPr",
    "w:sectPr": "w:sectPrChange",
    "w:space": "w:spaceForUL",
    "w:style": (
        "w:styleLink w:stylePaneFormatFilter w:stylePaneSortMethod w:styles"),
    "w:sz": "w:szCs",
    "w:t": (
        "w:tab w:tabs w:tag w:tbl w:tblBorders w:tblCellMar "
        "w:tblCellSpacing w:tblGrid w:tblGridChange w:tblHeader w:tblInd "
        "w:tblLayout w:tblLook w:tblOverlap w:tblPr w:tblPrChange w:tblPrEx "
        "w:tblPrExChange w:tblStyle w:tblStyleColBandSize w:tblStylePr "
        "w:tblStyleRowBandSize w:tblW w:tblpPr w:tc w:tcBorders w:tcMar "
        "w:tcPr w:tcPrChange w:tcW w:text w:textAlignment w:textDirection "
        "w:themeFontLang w:titlePg w:tl2br w:tmpl w:top w:tr w:tr2bl "
        "w:trHeight w:trPr w:trPrChange w:trackRevisions w:txbxContent "
        "w:type w:types"),
    "w:tab": "w:tabs",
    "w:tbl": (
        "w:tblBorders w:tblCellMar w:tblCellSpacing w:tblGrid "
        "w:tblGridChange w:tblHeader w:tblInd w:tblLayout w:tblLook "
        "w:tblOverlap w:tblPr w:tblPrChange w:tblPrEx w:tblPrExChange "
        "w:tblStyle w:tblStyleColBandSize w:tblStylePr "
        "w:tblStyleRowBandSize w:tblW w:tblpPr"),
    "w:tblGrid": "w:tblGridChange",
    "w:tblPr": "w:tblPrChange w:tblPrEx w:tblPrExChange",
    "w:tblStyle": "w:tblStyleColBandSize w:tblStylePr w:tblStyleRowBandSize",
    "w:tc": "w:tcBorders w:tcMar w:tcPr w:tcPrChange w:tcW",
    "w:tcPr": "w:tcPrChange",
    "w:tr": "w:trHeight w:trPr w:trPrChange w:trackRevisions",
    "w:trPr": "w:trPrChange",
}

#: An element name as pattern or literal text spells it: qualified, a
#: group of names (`w:(?:ins|del)`), a name with a group of endings
#: (`w:bookmark(?:Start|End)`), or an unprefixed name after `<`. An `=`
#: after it makes it an attribute.
_ELEMENT_NAME = re.compile(
    r"(?<![\w.-])(?P<prefix>[A-Za-z]\w*|\((?:\?:)?\w+(?:\|\w+)+\)):"
    r"(?:(?P<name>[A-Za-z]\w*+)(?:\((?:\?:)?(?P<tails>\w+(?:\|\w+)*)\))?"
    r"|\((?:\?:)?(?P<names>\w+(?:\|\w+)*)\)(?P<suffix>\w*+))(?!=)"
    r"|</?(?:\(\?:)?(?P<bare>[A-Z][A-Za-z]*+)(?![\w:])")

#: A character a name may hold, and so one that does not END it.
_NAME_CHAR = re.compile(r"[\w.-]")

#: Pattern escapes that end a name (`\b`, `\s`, `\W`, `\Z`, whitespace),
#: and those that may continue one.
_ENDS = frozenset("bsWZntrfv")
_CONTINUES = frozenset("BSwdDA")

_QUANTIFIER = re.compile(r"\?|\*\??|\+\??|\{\d*(?:,\d*)?\}\??")


def _names_spelled(text: str) -> list[tuple[str, int]]:
    """(name, the index just past it) for each element name `text` spells,
    over `_hole_masked` pattern text or a plain literal."""
    out = []
    for m in _ELEMENT_NAME.finditer(text):
        if m.group("bare"):
            out.append((m.group("bare"), m.end("bare")))
            continue
        prefixes = m.group("prefix").strip("()?:").split("|")
        if m.group("tails"):
            names = [m.group("name") + t for t in m.group("tails").split("|")]
            end = m.end()
        elif m.group("name"):
            names, end = [m.group("name")], m.end("name")
        else:
            names = [n + m.group("suffix")
                     for n in m.group("names").split("|")]
            end = m.end()
        out += [(f"{p}:{n}", end) for p in prefixes for n in names]
    return out


def _class_end(src: str, at: int) -> int:
    """The index of the `]` closing the class `src` opens at `at`."""
    at += 2 if src.startswith("[^", at) else 1
    at += 1 if src.startswith("]", at) else 0   # a `]` first is a member
    while at < len(src) and src[at] != "]":
        at += 2 if src[at] == "\\" else 1
    return at


def _group_end(src: str, at: int) -> int:
    """The index of the `)` closing the group `src` opens at `at`."""
    depth = 0
    while at < len(src):
        if src[at] == "\\":
            at += 2
            continue
        if src[at] == "[":
            at = _class_end(src, at) + 1
            continue
        if src[at] in "()":
            depth += 1 if src[at] == "(" else -1
            if not depth:
                return at
        at += 1
    return len(src)


def _class_takes_name_chars(body: str) -> bool:
    """Can the class `[body]` match a character a name holds?"""
    if body.startswith("^"):
        return "\\w" not in body            # only `[^\w…]` refuses them all
    at = 0
    while at < len(body):
        if body[at] == "\\":
            escape = body[at + 1:at + 2]
            if escape in _CONTINUES or (_NAME_CHAR.match(escape)
                                        and escape not in _ENDS
                                        and escape != "W"):
                return True
            at += 2
            continue
        if body[at + 1:at + 2] == "-" and at + 2 < len(body):
            if any(body[at] <= c <= body[at + 2] for c in "aA0_"):
                return True
            at += 3
            continue
        if _NAME_CHAR.match(body[at]):
            return True
        at += 1
    return False


def _optional(src: str, at: int) -> tuple[bool, int]:
    """(may the atom ending at `at` be absent, the index past its
    quantifier)."""
    m = _QUANTIFIER.match(src, at)
    if m is None:
        return False, at
    return m.group(0)[0] in "?*" or m.group(0).startswith("{0"), m.end()


def _alternatives(body: str) -> list[str]:
    """`body`'s alternatives at its own level."""
    out, start, at = [], 0, 0
    while at < len(body):
        if body[at] == "\\":
            at += 2
            continue
        if body[at] in "[(":
            at = (_class_end if body[at] == "[" else _group_end)(body, at)
        elif body[at] == "|":
            out.append(body[start:at])
            start = at + 1
        at += 1
    return [*out, body[start:]]


def _enclosing_end(src: str, at: int) -> int:
    """Past the `)`, and its quantifier, closing the group that holds
    `at`; the end of `src` when no group does."""
    while at < len(src):
        if src[at] == "\\":
            at += 2
            continue
        if src[at] in "[(":
            at = (_class_end if src[at] == "[" else _group_end)(src, at)
        elif src[at] == ")":
            return _optional(src, at + 1)[1]
        at += 1
    return len(src)


def _name_ends(src: str, at: int, *, enclosed: bool = True) -> bool:
    """Does the pattern `src` END the name it spells up to `at`?

    One construct at a time: an escape, a literal or a class decides; a
    lookbehind is stepped over; a lookahead decides when it ends the name;
    a group ends it only when every alternative does, and what follows it
    too when it may be absent; the end of an alternative reads on from
    where its group closes. The end of the pattern ends nothing.
    """
    while at < len(src):
        step = _read_construct(src, at, enclosed=enclosed)
        if isinstance(step, bool):
            return step
        at = step
    return False


def _read_construct(src: str, at: int, *, enclosed: bool) -> bool | int:
    """Whether the construct at `at` ends the name, or where to read on."""
    char = src[at]
    if char == "\\":
        escape = src[at + 1:at + 2]
        return escape in _ENDS or (escape not in _CONTINUES
                                   and not _NAME_CHAR.match(escape))
    if char == "[":
        end = _class_end(src, at)
        takes = _class_takes_name_chars(src[at + 1:end])
        optional, after = _optional(src, end + 1)
        return after if optional and not takes else not takes
    if char == "(":
        return _read_group(src, at, enclosed=enclosed)
    if char == "|":
        return enclosed and _name_ends(src, _enclosing_end(src, at))
    if char == ")":
        return _optional(src, at + 1)[1]
    return char not in ".?*+{^" and not _NAME_CHAR.match(char)


def _read_group(src: str, at: int, *, enclosed: bool) -> bool | int:
    """`_read_construct` for a group, a lookahead or a lookbehind."""
    end = _group_end(src, at)
    inner = src[at + 3:end]
    if src.startswith(("(?<=", "(?<!"), at):
        return end + 1
    if src.startswith("(?=", at):
        return _name_ends(inner, 0, enclosed=False) or end + 1
    if src.startswith("(?!", at):
        return bool(re.match(r"\[?\\w|\[(?:A-Za-z|a-zA-Z)", inner)) or end + 1
    opener = re.match(r"\((?:\?:|\?P<\w+>)?", src[at:])
    body = src[at + (len(opener.group(0)) if opener else 1):end]
    optional, after = _optional(src, end + 1)
    rest = src[after:]
    return all(_name_ends(alternative + rest, 0, enclosed=enclosed)
               for alternative in _alternatives(body)) and (
        not optional or _name_ends(rest, 0, enclosed=enclosed))


def _literal_name_ends(text: str, at: int) -> bool:
    """Does a plain literal END the name it spells up to `at`? A hole
    (`{}`) may be empty, and the end of the literal ends nothing."""
    return at < len(text) and text[at] in " \t\r\n/>\"'"


def _endless_names(text: str, *, pattern: bool) -> set[str]:
    """The names `text` spells with no end, where a longer one exists."""
    spelled = _names_spelled(_hole_masked(text) if pattern else text)
    return {name for name, end in spelled
            if name in LONGER_NAMES and not (
                _name_ends(text, end) if pattern
                else _literal_name_ends(text, end))}


def _prefix_readers() -> dict[tuple[str, str], set[str]]:
    """(module, source or read) -> the names it reads with no end."""
    out: dict[tuple[str, str], set[str]] = {}
    for module, _, source, probe, _ in ALL_PATTERNS:
        if names := _endless_names(probe, pattern=True):
            out.setdefault((module, source), set()).update(names)
    for module, what, text, _ in ALL_LITERAL_READS:
        if names := _endless_names(text, pattern=False):
            out.setdefault((module, what), set()).update(names)
    return out


#: Reads that spell a name with no end ON PURPOSE, or where the longer
#: names cannot change the answer, each with why. Keyed by (module,
#: pattern source) or (module, read), like the lists above.
_TEXT_THEN_CLOSE = (
    "same answer: the name's `[^>]*>` must be followed by text and at once "
    "by `</w:t>`, and no other element — tab, tbl, tc, tr, tag, type — "
    "can stand straight before that close; only a `w:t` holds text")
_MATH_PRESENCE = (
    "same answer: a presence test, and `m:oMathPara` and `m:oMathParaPr` "
    "exist only around an `m:oMath`, so the prefix is there exactly when "
    "the name is")
_FIRST_ROW = (
    "same answer: the first `<w:tr` in a table's own markup is its first "
    "row, since `w:trPr` and `w:trHeight` sit inside rows and no table "
    "property or grid child begins `tr`")
PREFIX_READS: dict[tuple[str, str], str] = {
    ("_compare_diff.py", r"<w:t[^>]*>[^<]*HYPERLINK[^<]*</w:t>"):
        _TEXT_THEN_CLOSE,
    ("_xml.py", r"(<w:t[^>]*>)([^<]*)(</w:t>)"): _TEXT_THEN_CLOSE,
    ("_xml.py", r"(<w:t[^>]*>)[^<]*(</w:t>)"): _TEXT_THEN_CLOSE,
    ("_xml.py",
     r"<(?:w|m):(?:t|delText)[^>]*>([^<]*)</(?:w|m):(?:t|delText)>"):
        _TEXT_THEN_CLOSE + " (`m:type` holds no text either)",
    ("_xml.py", r"<(?:w|m):t[^>]*>([^<]*)</(?:w|m):t>"):
        _TEXT_THEN_CLOSE + " (`m:type` holds no text either)",
    ("_xml.py", r"<m:t[^>]*>([^<]*)</m:t>"):
        _TEXT_THEN_CLOSE + " (`m:type` holds no text either)",
    ("_xml.py", r"<w:t[^>]*>([^<]*)</w:t>"): _TEXT_THEN_CLOSE,
    ("_xml.py", r"<w:tabs\b[^>]*(?<!/)>.*?</w:tabs>|<w:t[^>]*>([^<]*)</w:t>"
                r"|<w:(noBreakHyphen|softHyphen|tab|br|cr)\b[^>]*/?>"):
        _TEXT_THEN_CLOSE,
    ("batch.py", r'<w:rStyle w:val="Hyperlink"\s*/>(?:[^<]|<(?!/w:rPr>))*'
                 r"</w:rPr><w:t[^>]*>([^<]*)</w:t>"): _TEXT_THEN_CLOSE,
    ("batch.py", r"<w:t[^>]*>([^<]*)</w:t>"): _TEXT_THEN_CLOSE,
    ("hygiene.py", r"(<m:t[^>]*>)([^<]*)(</m:t>)"):
        _TEXT_THEN_CLOSE + " (`m:type` holds no text either)",
    ("_table_layout.py", "_own_grid: find(<w:tr)"): _FIRST_ROW,
    ("_table_layout.py", "_own_tblpr: find(<w:tr)"): _FIRST_ROW,
    ("_table_layout.py", "_set_tbl_pr: find(<w:tr)"): _FIRST_ROW,
    ("_table_layout.py", "drop_blank_rows: in(<w:drawing)"): (
        "same answer: the longer names are `w:drawingGrid…Spacing`, which "
        "live in settings and never in a table row"),
    ("_table_layout.py", "drop_blank_rows: in(<w:sdt)"): (
        "same answer: `w:sdtPr`, `w:sdtContent` and `w:sdtEndPr` occur "
        "only inside a `w:sdt`, so a row holds the prefix exactly when it "
        "holds a content control"),
    ("_xml.py", "split_run: startswith(<w:t)"): (
        "same answer: a piece beginning `<w:tab` or another `t` name fails "
        "`_SPLIT_T_RE.fullmatch`, reads as no text, and rides left or "
        "right exactly as a non-text piece does"),
    ("batch.py", "diagnose: in(<m:oMath)"): _MATH_PRESENCE,
    ("equations.py", "is_display: in(<m:oMath)"): _MATH_PRESENCE,
    ("find.py", "site: in(<m:oMath)"): _MATH_PRESENCE,
    ("body.py", "para: startswith(<w:pPr)"): (
        "builder input: the properties a caller spells for a new paragraph "
        "never begin with `w:pPrChange`, the LAST child of a pPr, or "
        "`w:pPrDefault`, which lives in styles' docDefaults"),
    ("cli.py", "cmd_inspect: ==(<w:ins)"): (
        "same answer: the slice starts where `revisions.spans` found "
        "`<w:(ins|del)\\b`, so it is never `<w:insideH` or `<w:instrText`"),
    ("edit.py", "_maths_start: find(<m:oMath)"): (
        "deliberate, and said beside it: `m:oMathPara` begins with the "
        "name too, and the FIRST occurrence at an offset is the outermost "
        "element, before which a run goes"),
    # `edit.py _plain_runs: in(<w:t)` stood here until 2026-09-18, with a
    # deliberate-in-effect argument: the run children beginning `t` are
    # `w:t` and `w:tab`, and a label run holding only a tab prints it. The
    # read is GONE — 9402cd1 rewrote `_plain_runs` to name what the LINK
    # owns and keep every other byte, so it no longer asks what a run
    # contains. This registry caught the declaration outliving its
    # subject, which is the same shape as an expired equivalence claim and
    # for the same reason: an argument about code that has moved reads as
    # a guarantee and is not one.
    ("probe.py", "probe: startswith(<w:tbl)"): (
        "same answer: `_blocks` yields whole paragraphs and whole tables, "
        "so a block beginning `<w:tbl` is a table; no `w:tblPr` or kin ever "
        "starts one"),
    ("refstyle.py", "_starts_a_page: in(<w:sectPr)"): (
        "same answer: `w:sectPrChange` exists only inside a `w:sectPr`, so "
        "the prefix is there exactly when a section break is"),
    ("revisions.py", "_parse: startswith(<w:document)"): (
        "same answer: this asks for the part's ROOT, and "
        "`w:documentProtection` is a settings child, never a root"),
}


def test_no_read_spells_an_element_name_without_an_END():
    new = {key: sorted(names) for key, names in _prefix_readers().items()
           if key not in PREFIX_READS}
    assert not new, (
        "these spell an element name and nothing to END it, so they read "
        "every longer name it begins (`<w:t` reads `<w:tab`, `<w:p` reads "
        "`<w:pPr`). End it — `\\b`, `(?=[\\s/>])`, or a space, `>` or `/` "
        "in a literal — or declare in PREFIX_READS why the longer names "
        "cannot change the answer:\n  " + "\n  ".join(
            f"{module}: {what!r} reads {names}"
            for (module, what), names in sorted(new.items())))


def test_every_PREFIX_READ_is_still_one():
    readers = _prefix_readers()
    for key, reason in PREFIX_READS.items():
        assert len(reason) > 40, (key, reason)
        assert key in readers, f"declared, but gone or now ended: {key}"


def test_every_name_that_begins_a_longer_one_is_LISTED():
    """A name the package spells that begins another name the list knows
    must be in it, and every name listed must still be spelled."""
    spelled = {name for *_, probe, _ in ALL_PATTERNS
               for name, _ in _names_spelled(_hole_masked(probe))}
    spelled |= {name for _, _, text, _ in ALL_LITERAL_READS
                for name, _ in _names_spelled(text)}
    known = spelled | set(LONGER_NAMES) | {
        name for names in LONGER_NAMES.values() for name in names.split()}
    unlisted = sorted(
        name for name in spelled - set(LONGER_NAMES)
        if any(other != name and other.startswith(name)
               and _NAME_CHAR.match(other[len(name)]) for other in known))
    assert unlisted == [], f"begin a longer name, not listed: {unlisted}"
    assert set(LONGER_NAMES) <= spelled, sorted(set(LONGER_NAMES) - spelled)


def test_the_name_END_detector_both_ways_round():
    """The gate's own instrument."""
    ended = [r"<w:t\b", r"<w:t[ >]", r"<w:t>", r"<w:t(?=[\s/>])",
             r"<w:t(?:\s|>)", r"<w:r(?: [^>]*)?(?<!/)>", r"<w:p\s*/>",
             r"<w:(?:ins|del)(?=[\s/>])", r"(<w:ins)\b", r"<w:p[\s/]",
             r"<w:t(?![\w.-])", r"<w:t [^>]*>", r"<w:tab(?:s)?\b"]
    for source in ended:
        assert not _endless_names(source, pattern=True), source
    endless = [r"<w:t[^>]*>", r"<w:t", r"<w:(?:ins|del)", r"<w:ins|<w:del\b",
               r"<w:t[^>]*?(/?)>", r"<w:tbl.*?>", r"<w:t\w*", r"w:moveFrom",
               r"(?:<w:ins)+x"]
    for source in endless:
        assert _endless_names(source, pattern=True), source
    assert _endless_names("<w:t", pattern=False) == {"w:t"}
    assert not _endless_names("<w:t>", pattern=False)
    assert not _endless_names("<w:ins ", pattern=False)
