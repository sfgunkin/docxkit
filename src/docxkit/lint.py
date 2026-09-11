r"""Structural checks for the "Word says the file is corrupted" bug classes.

Ported from the DSI paper's ``dsidocx.lint``, which was built after
repeatedly shipping markup Word refused to open. Every check here
corresponds to something that actually happened: an offline lint catches
it in milliseconds, where the alternative is a Word round-trip and a
dialog that says only "unreadable content".

Run it before writing any document you edited structurally —
:func:`docxkit.tracked.build` does, and ``docxkit lint FILE`` does it to
an existing file.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # lxml is imported lazily in `_roots` so `import docxkit` does not
    # pay for it; the element type is still named, so the stubs see
    # every walk here rather than `Any` (until 2026-09-03 — review, row 7).
    from lxml.etree import _Element

from ._xml import COMMENTS, DOCUMENT, ENDNOTES, FOOTNOTES, MATH_OBJECTS, XML_WS

__all__ = [
    "XML_SPACE",
    "audit",
    "audit_parts",
    "lint",
    "lint_parts",
]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Containers that may hold only block-level children.
_BLOCK_CONTAINERS = ("footnote", "endnote", "body", "tc", "comment")
# Elements that belong inside a paragraph, never directly in the above.
_RUN_LEVEL = ("r", "ins", "del", "hyperlink")
_RUN_LEVEL_MATH = ("oMath", "oMathPara")
# CT_PPr fixes this order: all of these must precede w:rPr.
_PPR_BEFORE_RPR = frozenset({
    "pStyle", "keepNext", "keepLines", "numPr", "spacing", "ind", "jc",
    "outlineLvl", "contextualSpacing",
})
# Parts worth checking, in the order a reader would care about.
_PARTS = (DOCUMENT, FOOTNOTES, ENDNOTES,
          COMMENTS)


def _local(tag: object) -> str:
    # `object`, not `str`: a comment node's tag is the Comment factory,
    # and `str()` of it is what the split below expects.
    return str(tag).rsplit("}", 1)[-1]


def _math_has_glyph(el: _Element) -> bool:
    """Any descendant ``m:t`` carrying text; U+00A0 is a deliberate spacer."""
    return any(t.text for t in el.iter(M + "t"))


# Tag sets for the walks below, built once.
#: property containers whose children may each appear once
_PROPS = ("tcPr", "rPr", "pPr", "trPr", "tblPr")
#: each of these carries at most ONE properties element
_OWNER = {"tc": "tcPr", "tr": "trPr", "tbl": "tblPr",
          "p": "pPr", "r": "rPr"}
_RUN_LEVEL_TAGS = frozenset({W + t for t in _RUN_LEVEL}
                            | {M + t for t in _RUN_LEVEL_MATH})
_BLOCK_CHILDREN = frozenset({W + "p", W + "tbl", W + "tr", W + "tc"})
_MARKER_PARENTS = frozenset({W + "rPr", W + "trPr"})
#: Paragraph properties that are only ever legal INSIDE `w:pPr`. Named
#: from `_PPR_BEFORE_RPR` plus the rest of CT_PPr a builder reaches for,
#: and deliberately NOT the whole schema: `w:rPr` is legal directly in a
#: `w:p` (it is the paragraph mark's own run properties, which every
#: tracked paragraph-mark revision carries), and listing it here would
#: fail every redline in the corpus.
_PPR_STRAYS = frozenset(W + t for t in _PPR_BEFORE_RPR | {
    "pageBreakBefore", "widowControl", "pBdr", "shd", "tabs",
    "suppressLineNumbers", "textAlignment", "mirrorIndents",
    "adjustRightInd", "snapToGrid", "bidi",
})


def _stray_para_props(root: _Element) -> list[str]:
    """Check 1b — a paragraph PROPERTY sitting directly in the paragraph.

    Word keeps the runs and DISCARDS a schema-invalid child of ``w:p``
    without a word, so the paragraph renders with the default style and
    nothing anywhere says why: Parental_style's supplement shipped a
    title block left-aligned at 16pt (2026-09-01), found by rasterising
    the PDF. It came from ``body.para(ppr=…)`` splicing in a bare pPr,
    which is fixed — this is the check that catches the shape whatever
    wrote the paragraph, and it is check 1's shape one level down: a
    child in a container whose schema has no place for it.

    Its own function because inline it took `lint` from 31 to 34 and
    `test_complexity_debt` refused the commit.
    """
    return [f"w:{_local(child.tag)} sits directly in w:p, outside its "
            f"w:pPr — Word drops it silently"
            for paragraph in root.iter(W + "p") for child in paragraph
            if child.tag in _PPR_STRAYS]


def _run_level_in_block(root: _Element) -> list[str]:
    """Check 1 — a run-level element directly in a block-only container.

    Word rejects the part outright.
    """
    return [f"w:{_local(parent.tag)} has run-level child "
            f"{_local(child.tag)} (must be inside w:p)"
            for parent in root.iter(*(W + t for t in _BLOCK_CONTAINERS))
            for child in parent if child.tag in _RUN_LEVEL_TAGS]


def _revision_findings(
        root: _Element, revision_ids: dict[str | None, int],
) -> tuple[list[str], list[str], list[str]]:
    """Checks 2, 3 and 4, and the revision-id tally check 8 reads.

    ONE multi-tag C-filtered walk, which is the whole point of taking
    them together: what made the original slow was a full un-filtered
    ``root.iter()`` for the ids plus a pass per check. Returns the three
    check's findings separately because they are not emitted together —
    check 2 goes out before check 3b's walk and checks 3 and 4 after it,
    and that order is the report a reader has been reading for a year.

    ``revision_ids`` is accumulated ACROSS roots, so it is passed in and
    mutated rather than returned: check 8 asks whether an id repeats
    anywhere in the package, and a per-part tally cannot answer that.
    """
    c2: list[str] = []
    c3: list[str] = []
    c4: list[str] = []
    for element in root.iter(W + "ins", W + "del", W + "rPrChange",
                             W + "pPrChange"):
        rid = element.get(W + "id")
        revision_ids[rid] = revision_ids.get(rid, 0) + 1
        tag = element.tag
        if tag not in (W + "ins", W + "del"):
            continue
        parent = element.getparent()
        parent_tag = parent.tag if parent is not None else None
        if parent_tag in _MARKER_PARENTS:
            continue                           # a marker, not a range
        # 2. An empty w:ins / w:del that is not a marker.
        if len(element) == 0:
            c2.append(f"empty w:{_local(tag)} (not a marker)")
        # 3. Deleted text must be w:delText; a w:t inside w:del
        #    renders as live text that cannot be rejected.
        if tag == W + "del" and \
                element.find(".//" + W + "t") is not None:
            c3.append("w:del contains w:t (should be w:delText)")
        # 4. A block element inside a run-level revision.
        for child in element:
            if child.tag in _BLOCK_CHILDREN:
                c4.append(f"block w:{_local(child.tag)} inside "
                          f"run-level w:{_local(tag)}")
    return c2, c3, c4


def _edge_whitespace(root: _Element) -> list[str]:
    """Check 3b — a ``w:t`` with edge whitespace and no ``xml:space``.

    OOXML trims it, so the space survives in the tooling that wrote it
    but is dropped by every conforming reader — Word on open, on save,
    and inside CompareDocuments. On the LE paper this masqueraded as
    recurring "Word damage" for seven author rounds and shipped four
    typos into the journal's copy.

    Only real XML whitespace is trimmed: a leading NBSP is safe, and
    Word puts one in every empty table cell.
    """
    problems = []
    for element in root.iter(W + "t"):
        text = element.text or ""          # read ONCE: w:t is the most
        if (text != text.strip(XML_WS)     # numerous element in a paper
                and element.get(XML_SPACE) != "preserve"):
            problems.append(
                'w:t has edge whitespace without '
                'xml:space="preserve" '
                f"({text[:30]!r}) - run "
                "docxkit.edit.preserve_space as the last build step")
    return problems


def _child_order(root: _Element) -> list[str]:
    """Checks 5 and 6 — schema-fixed child order inside a properties
    element: nothing in ``_PPR_BEFORE_RPR`` may follow ``w:pPr``'s
    ``w:rPr``, and ``w:rPrChange`` must be the last child of its
    ``w:rPr``.
    """
    problems = []
    for ppr in root.iter(W + "pPr"):
        kids = [_local(c.tag) for c in ppr]
        if "rPr" in kids:
            after = set(kids[kids.index("rPr") + 1:])
            if bad := sorted(after & _PPR_BEFORE_RPR):
                problems.append(f"w:pPr: {bad} after w:rPr (CT_PPr order)")

    for rpr in root.iter(W + "rPr"):
        kids = [_local(c.tag) for c in rpr]
        if "rPrChange" in kids and kids[-1] != "rPrChange":
            problems.append("w:rPr: w:rPrChange is not the last child")
    return problems


def _empty_math(root: _Element) -> list[str]:
    """Check 7 — an empty oMath shell renders as garbage, or loses the math.

    Two counts, because asking only whether a WHOLE equation has gone
    textless misses the commoner and more visible case: a surviving
    equation carrying an emptied fraction, which Word draws as an empty
    box beside the real content. On the DSI paper the split was 53
    wholly-empty against 121 empty children, so the whole-equation test
    passed the large majority of the damage — and that document shipped.
    """
    problems = []
    empty = orphaned = 0
    for om in root.iter(M + "oMath"):
        if not _math_has_glyph(om):
            empty += 1
            continue
        orphaned += sum(
            1 for el in om.iter()
            if el is not om and _local(el.tag) in MATH_OBJECTS
            and not _math_has_glyph(el))
    if empty:
        problems.append(f"{empty} empty m:oMath shell(s)")
    if orphaned:
        problems.append(
            f"{orphaned} empty math object(s) inside a surviving "
            f"m:oMath (renders as a blank box)")
    return problems


def _repeated_props(root: _Element) -> list[str]:
    """Checks 7b and 7c — a properties element, and each of its children,
    may appear ONCE.

    7b: two ``w:tcBorders`` in one ``w:tcPr`` is schema-invalid and
    reads as "unreadable content", and neither the write gate (a
    duplicate is still well-formed) nor anything else here saw it — a
    border writer that matched only the expanded ``<w:tcBorders>`` and
    not the empty ``<w:tcBorders/>`` inserted a second one beside it.

    7c: ...and the properties element itself appears once in its parent.
    A self-closing ``<w:tcPr/>`` read as "absent" got a second one
    prepended beside it, which 7b cannot see because it inspects a
    properties element's CHILDREN.
    """
    problems = []
    for props in root.iter(*(W + t for t in _PROPS)):
        seen: set[str] = set()
        for child in props:
            tag = _local(child.tag)
            if tag in seen:
                problems.append(f"w:{_local(props.tag)} carries two w:{tag} "
                                "children (each may appear once)")
            seen.add(tag)

    for parent, prop in _OWNER.items():
        for owner in root.iter(W + parent):
            n = sum(1 for c in owner if c.tag == W + prop)
            if n > 1:
                problems.append(f"w:{parent} carries {n} w:{prop} elements "
                                "(it may carry one)")
    return problems


def lint(*roots: _Element | None) -> list[str]:
    """Problems found across the given lxml roots. Empty means clean.

    Iteration stays C-filtered: ``root.iter(tag, tag, ...)`` walks in
    lxml's C layer, and measured on real manuscripts it beats a single
    Python-level walk that dispatches on every element (that rewrite
    was tried and was SLOWER than the original). What made the original
    slow was one full un-filtered ``root.iter()`` just to collect
    revision ids, plus separate passes per revision check — both now
    share one multi-tag walk. Findings are collected per check and
    emitted in the original check order, so the report reads exactly as
    before.

    The checks are the functions above, one per numbered rule, and this
    is the order they are emitted in — which is the report itself, not
    an implementation detail: check 2 lands before check 3b and checks 3
    and 4 after it. Splitting them out is what took this function off
    `test_complexity_debt`'s list; the walk count is unchanged.
    """
    problems: list[str] = []
    revision_ids: dict[str | None, int] = {}

    for root in roots:
        if root is None:
            continue
        c2, c3, c4 = _revision_findings(root, revision_ids)
        problems += (_run_level_in_block(root)      # 1
                     + _stray_para_props(root)      # 1b
                     + c2                           # 2
                     + c3 + _edge_whitespace(root) + c4   # 3, 3b, 4
                     + _child_order(root)           # 5, 6
                     + _empty_math(root)            # 7
                     + _repeated_props(root))       # 7b, 7c

    # 8. Revision ids must be unique across the whole package; Word merges
    #    or drops revisions that share one.
    dups = sorted((i for i, n in revision_ids.items() if n > 1),
                  key=lambda x: (x is None, x))
    if dups:
        problems.append(f"duplicate revision w:id across parts: {dups}")

    return problems


def audit(*roots: _Element | None) -> list[str]:
    """Findings Word opens FINE. Reported, never refused.

    :func:`lint` answers one question — will Word refuse to open this —
    and three callers refuse a write on its answer. So a check that is
    about CORRECTNESS rather than openability cannot live there, however
    much it belongs beside it: the bookmark-name check below shipped
    inside `lint` for one commit and bricked every mutating command on a
    manuscript that already had a duplicate, under a message that was
    not true of it ("the package would not open cleanly in Word").
    Word opens it. The links are just wrong.

    That is the shape this file's own backlog ranks S3, above a wrong
    output: a gate nobody can satisfy, on a condition the toolkit
    offered no way to clear.
    """
    return _repeated_bookmarks(roots) + _unbalanced_fields(roots)


def audit_parts(parts: dict[str, bytes]) -> list[str]:
    """:func:`audit` over the text-bearing parts of a package.

    The malformed-XML message is the answer here too, and dropping it
    audited an EMPTY list of roots — "no duplicate bookmark names" for a
    document that could not be read at all. `lint_parts` returns it, and
    this is the half a caller can reach on its own.
    """
    roots, malformed = _roots(parts)
    if malformed:
        return malformed
    body = next((r for r in roots if r.tag == W + "document"), None)
    return audit(*roots) + _opens_on_whitespace(body)


def _opens_on_whitespace(body: _Element | None) -> list[str]:
    """Advisory — a BODY paragraph whose text opens on a space or a tab.

    Word prints it as an indent, and no text gate sees it: `compare`
    reports an edge that MOVED between two files (backlog S1), while a
    paper whose truth already carries one has nothing to compare
    against. An author hand pass opened Aging_Well's A.4 with ` The
    following…` and it was found on page 32 of the render.

    The BODY only. A footnote legitimately opens on the space after its
    note mark — 11 of 12 on that paper — so the other parts are not
    read, and a paragraph that is nothing but whitespace is a spacer,
    not a slip.
    """
    if body is None:
        return []
    out = []
    for p in body.iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t"))
        if text.strip() and text[0] in " \t":
            out.append(f"body paragraph opens on whitespace ({text[:40]!r}) "
                       "- Word prints it as an indent")
    return out


def _repeated_bookmarks(roots: tuple[_Element | None, ...]) -> list[str]:
    """Bookmark names defined more than once across the package.

    A name may be defined once. Word keeps whichever definition it meets
    first, so every link to a duplicated name lands on a coin flip — and
    Word's Compare discards the extras outright.

    Measured on 400 real manuscripts: 24 carry a duplicate and all 24
    are ONE paper, whose v34 defines 12 names twice or more — 20 extra
    definitions, `AykutEtAl2026txt` six times — in the file submitted to
    the journal as well. It runs back to v19 and nothing ever said so:
    `lint` was clean and `citations` reported ALL CHECKS PASSED, because
    an audit that keys bookmarks BY NAME cannot see a name twice. What
    did see it was a one-word Compare round, which came back 20
    bookmarks lighter and failed the structure gate blaming a move
    (2026-08-21).

    Counted across the whole package, because the namespace is: a
    citation's ``<key>txt`` marker legitimately sits in footnotes.xml
    while the entry links to it from the body.
    """
    seen: dict[str, int] = {}
    for root in roots:
        if root is None:
            continue
        for mark in root.iter(W + "bookmarkStart"):
            name = mark.get(W + "name")
            if name is not None:
                seen[name] = seen.get(name, 0) + 1
    # Worst first, not alphabetical: only eight are named, so sorting
    # by name means the offender that matters survives on luck. On the
    # paper this was found in it did - `AykutEtAl2026txt x6` sorts
    # first by accident - and had that name been `Zhang2024txt` the
    # message would have listed eight x2 entries and hidden the six
    # behind the ellipsis.
    repeated = sorted(((n, c) for n, c in seen.items() if c > 1),
                      key=lambda item: (-item[1], item[0]))
    if not repeated:
        return []
    named = ", ".join(f"{n} x{c}" for n, c in repeated[:8])
    return [(f"{len(repeated)} bookmark name(s) defined more than once: "
             f"{named}{' ...' if len(repeated) > 8 else ''} — Word keeps the "
             f"first and every link to the name is a coin flip")]


def _field_where(fld: _Element) -> str:
    """Name the paragraph an orphaned field half sits in.

    Its visible text is what a person searches for, and the field's
    INSTRUCTION is what identifies it when there is none — which is the
    usual case, because the half that survives a deleted sentence is
    the half with no display runs left.
    """
    para: _Element | None = fld
    while para is not None and para.tag != W + "p":
        para = para.getparent()
    if para is None:
        return "outside any paragraph"
    text = "".join(t.text or "" for t in para.iter(W + "t")).strip()
    instr = "".join(t.text or "" for t in para.iter(W + "instrText")).strip()
    where = f"¶ {text[:40]!r}" if text else "¶ with no visible text"
    return f"{where} [{instr[:40]}]" if instr else where


def _unbalanced_fields(roots: tuple[_Element | None, ...]) -> list[str]:
    """``w:fldChar`` begins with no end, and ends with no begin.

    A field is three runs — ``begin``, the ``instrText``, ``end`` — and
    deleting the sentence around one takes the display runs and leaves
    the rest standing. Word then decides where the field ends on its
    own, which in practice means swallowing the rest of the paragraph
    into it. Found on Aging_Well 2026-08-26, dropping a figure whose
    in-text mention was a field-form hyperlink; measured on that paper's
    own file with one ``end`` run removed, `lint` said "clean - no
    structural problems found" and exited 0.

    Nothing else names it either. `citations` did exit 1, for an
    UNBALANCED SPAN two paragraphs away — a link that is in fact fine —
    and `crossrefs --audit` called it a misplaced anchor, i.e. a live
    mention of a figure no longer in the paper. Three tools, three
    misleading descriptions, and none of them "a field has no end".

    Counted per PART and not per paragraph: a TOC or an index field
    legitimately spans many paragraphs, and a per-paragraph balance
    would report every one of them. ``w:fldSimple`` carries its
    instruction as an attribute and pairs with nothing, so it is not a
    ``w:fldChar`` and never reaches this walk.

    Advisory rather than a refusal, because Word opens the file — the
    same reason the bookmark check sits here. What it reads is wrong.
    """
    out: list[str] = []
    for root in roots:
        if root is None:
            continue
        # Nested fields are ordinary — a HYPERLINK inside a
        # cross-reference — so this is a depth walk and not two counts.
        # Two counts agree on `end begin`, which is two orphans.
        open_fields: list[_Element] = []
        for fld in root.iter(W + "fldChar"):
            kind = fld.get(W + "fldCharType")
            if kind == "begin":
                open_fields.append(fld)
            elif kind == "end":
                if open_fields:
                    open_fields.pop()
                else:
                    out.append("field END with no begin, in "
                               f"{_field_where(fld)} — Word reads the "
                               "run before it as part of the field")
        for fld in open_fields:
            out.append(f"field BEGIN with no end, in {_field_where(fld)} — "
                       "Word decides where it ends, and swallows the rest "
                       "of the paragraph into it")
    return out


def lint_parts(parts: dict[str, bytes]) -> list[str]:
    """Lint the text-bearing parts of a package.

    OPENABILITY only — the callers that refuse a write on this answer
    are entitled to assume every finding means Word will reject the
    file. What Word opens but reads wrongly is :func:`audit_parts`.
    """
    roots, malformed = _roots(parts)
    return malformed or lint(*roots)


def _roots(parts: dict[str, bytes]) -> tuple[list[_Element], list[str]]:
    """(parsed text-bearing parts, the message if one will not parse).

    A part that does not parse short-circuits: nothing below can read a
    document Word cannot, and one clear message beats a hundred
    consequential ones.
    """
    from lxml import etree

    roots: list[_Element] = []
    for name in _PARTS:
        if name in parts:
            try:
                roots.append(etree.fromstring(parts[name]))
            except etree.XMLSyntaxError as exc:
                return [], [f"{name} is not well-formed XML: {exc}"]
    return roots, []
