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


#: Every module, the subpackage's halves included: a `*.py` glob is a
#: claim that the package is flat, and `revision/` has not been since
#: 2026-08-30 (BACKLOG, "Not seven defects — one habit").
ALL_PATTERNS = [(str(p.relative_to(SRC)), name, src, line)
                for p in sorted(SRC.rglob("*.py"))
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

#: An attribute spelling: prefix, local name, `=`.
_ATTR = re.compile(r"\b(?:w|m|r|a|wp|w14|w15|mc|v|o|pic|xml):\w+=")

#: The ways this package writes "other attributes may sit here". Between
#: two attribute spellings of ONE element, any of these makes the
#: pattern order-free; a literal space or `\s+` makes it order-bound.
_ANY_ATTRS = ("[^>]", ".*", "(?=")


def _order_bound(source: str) -> list[tuple[str, str]]:
    """The attribute pairs `source` insists on in sequence."""
    out = []
    for a, b in itertools.pairwise(_ATTR.finditer(source)):
        between = source[a.end():b.start()]
        if "<" in between:              # the next element's, not this one's
            continue
        if any(free in between for free in _ANY_ATTRS):
            continue
        out.append((a.group(0), b.group(0)))
    return out


def test_the_detector_sees_an_order_bound_pair_and_not_a_free_one():
    """The gate's own instrument: every assertion below is a NEGATIVE."""
    assert _order_bound(r'<w:tcW w:w="[^"]*" w:type="\w+"/>') == [
        ("w:w=", "w:type=")]
    assert _order_bound(r'<w:tblW\b[^>]*/>') == []
    assert _order_bound(r'<w:style\b(?=[^>]*\bw:type="p")'
                        r'(?=[^>]*\bw:default="1")[^>]*\bw:styleId=') == []
    assert _order_bound(r'<w:fldChar\b[^>]*w:fldCharType="begin"[^>]*/>'
                        r'(.*?)<w:fldChar\b[^>]*w:fldCharType="end"') == []


def test_no_pattern_binds_two_attributes_of_one_element_to_an_ORDER():
    bound = [f"{module}:{line} {name} insists on {pairs}"
             for module, name, source, line in ALL_PATTERNS
             if (pairs := _order_bound(source))]
    assert bound == [], (
        "an element written in another attribute order is the same "
        "element, and Word writes both orders (5 of 150 manuscripts for "
        "w:tcW). Spell the attribute you want as `\\b[^>]*\\bw:name=`, or "
        "match the whole tag with `<w:tag\\b[^>]*/>` and read it after:\n  "
        + "\n  ".join(bound))
