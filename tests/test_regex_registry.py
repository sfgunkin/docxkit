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
import pathlib
import re

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


def _patterns(path: pathlib.Path) -> list[tuple[str, str, int]]:
    """(name, pattern source, line) for every module-level re.compile."""
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "compile"
                and node.value.args
                and isinstance(node.value.args[0], ast.Constant)
                and isinstance(node.value.args[0].value, str)):
            continue
        name = next((t.id for t in node.targets
                     if isinstance(t, ast.Name)), "?")
        out.append((name, node.value.args[0].value, node.lineno))
    return out


ALL_PATTERNS = [(p.name, name, src, line)
                for p in sorted(SRC.glob("*.py"))
                for name, src, line in _patterns(p)]


def test_there_are_patterns_to_check():
    """A walk that silently found nothing would pass forever."""
    assert len(ALL_PATTERNS) > 100


@pytest.mark.parametrize("module,name,source,line", ALL_PATTERNS,
                         ids=lambda v: str(v)[:40])
def test_no_pattern_reads_an_EMPTY_container_as_an_opening_tag(
        module, name, source, line):
    try:
        compiled = re.compile(source, re.DOTALL)
    except re.error:                                    # pragma: no cover
        pytest.skip("built from another pattern at import time")
    for prefix in ("w", "m"):
        for tag in CONTAINERS:
            healthy = f"<{prefix}:{tag}>text</{prefix}:{tag}>"
            # Probed rather than read off the source, so an alternation
            # (`<(/?)w:(tbl|tr|tc|p)\b…`) is covered too.
            if (well := compiled.search(healthy)) is None:
                continue                    # not about this element
            if ">" not in well.group(0):
                continue                    # a counter: it pairs nothing
            sick = f"<{prefix}:{tag}/>{healthy}"
            hit = compiled.search(sick)
            if hit is not None and any(g == "/" for g in hit.groups()
                                       if g is not None):
                continue    # it CAPTURES the slash: the caller is told
            assert hit is None or hit.start() != 0, (
                f"{module}:{line} {name} reads <{prefix}:{tag}/> as an "
                f"OPENING tag and pairs it with the next close, "
                f"swallowing the {prefix}:{tag} after it. An empty "
                f"element opens nothing: add the `(?<!/)>` guard that "
                f"_xml.PARA_RE and _xml.RUN_RE carry.")
