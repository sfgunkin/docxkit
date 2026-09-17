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


#: The `re` calls whose first argument is a pattern. A pattern written
#: inline — `re.finditer(r"<w:comment ([^>]*)>(.*?)</w:comment>", com)` —
#: reads an element exactly as a compiled one does.
_RE_CALLS = ("compile", "search", "match", "fullmatch", "finditer",
             "findall", "sub", "subn", "split")


#: What an f-string's `{hole}` is probed AS: a value, a tag name, an id.
#: `<w:bookmarkStart w:id="(\d+)" w:name="{name}"/>` read as a plain
#: literal matches no probe, and was invisible to both gates while
#: carrying the order defect its literal twin in the same module had.
_HOLE = r"\w+"


def _pattern_of(node: ast.expr) -> tuple[str, str] | None:
    """(source, probe) of a literal pattern argument, or None.

    The source is the pattern as written, an f-string's holes spelled
    `{expr}` — what a reader finds with a search, and what the allowlist
    below is keyed by. The probe is what the gate compiles: the same
    text, each hole a run of name characters.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    source, probe = [], []
    for part in node.values:
        if isinstance(part, ast.Constant):
            source.append(str(part.value))
            probe.append(str(part.value))
        else:
            assert isinstance(part, ast.FormattedValue)
            source.append("{" + ast.unparse(part.value) + "}")
            probe.append(_HOLE)
    return "".join(source), "".join(probe)


def _patterns(path: pathlib.Path) -> list[tuple[str, str, str, int]]:
    """(name, source, probe, line) for EVERY `re` call on a literal.

    Not only `NAME = re.compile(...)`: `_xml.NOTE_DEF_RE` compiles its
    two patterns inside a dict literal, and six more read comments,
    rows and cells through `re.finditer(r"…")` inline. A walk that asked
    for an assignment of `re.compile` itself saw none of them — the same
    self-closing defect sat in them beside the copies this gate did find
    (2026-09-17). Nor only plain literals: an f-string is a literal with
    holes, and three of them carried the defects their plain twins were
    flagged for. The name is the nearest assignment target around the
    call, or `?`.
    """
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            name = next((t.id for t in targets if isinstance(t, ast.Name)),
                        "?")
            for inner in ast.walk(node):
                names.setdefault(id(inner), name)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.func.attr in _RE_CALLS
                and node.args
                and (literal := _pattern_of(node.args[0])) is not None):
            continue
        out.append((names.get(id(node), "?"), *literal, node.lineno))
    return out


#: Every module, the subpackage's halves included: a `*.py` glob is a
#: claim that the package is flat, and `revision/` has not been since
#: 2026-08-30 (BACKLOG, "Not seven defects — one habit"). POSIX paths,
#: so an allowlist key reads the same on every machine.
ALL_PATTERNS = [(p.relative_to(SRC).as_posix(), name, src, probe, line)
                for p in sorted(SRC.rglob("*.py"))
                for name, src, probe, line in _patterns(p)]


def test_an_f_string_is_read_with_its_holes():
    """The walk's own instrument: a hole is kept in the source, filled
    in the probe, and a pattern built any other way is not a literal."""
    call = ast.parse('re.search(rf\'<w:x w:id="{bid}"/>\', xml)').body[0]
    assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)
    assert _pattern_of(call.value.args[0]) == (
        '<w:x w:id="{bid}"/>', f'<w:x w:id="{_HOLE}"/>')
    concat = ast.parse('re.compile(A + "b")').body[0]
    assert isinstance(concat, ast.Expr) and isinstance(concat.value, ast.Call)
    assert _pattern_of(concat.value.args[0]) is None


def test_there_are_patterns_to_check():
    """A walk that silently found nothing would pass forever."""
    assert len(ALL_PATTERNS) > 100


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
    ("_cite_grammar.py", r"<w:r\b[^>]*>"): (
        "isolated input: `_add_style` gets a run matched by the guarded "
        "RUN_RE, or a half `split_run` rebuilt from one, which always "
        "carries that run's open tag and a `</w:r>`"),
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
             for module, name, source, _probe, line in ALL_PATTERNS
             if (pairs := _order_bound(source))]
    assert bound == [], (
        "an element written in another attribute order is the same "
        "element, and Word writes both orders (5 of 150 manuscripts for "
        "w:tcW). Spell the attribute you want as `\\b[^>]*\\bw:name=`, or "
        "match the whole tag with `<w:tag\\b[^>]*/>` and read it after:\n  "
        + "\n  ".join(bound))
