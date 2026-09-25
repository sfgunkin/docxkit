r"""Paragraph structure: split one, merge two, drop one.

`edit` works INSIDE a paragraph and `body` adds new ones; nothing here
could change how many there are. Six papers wrote it themselves —
Aging_Well's `_spans.py` (copied into `r73_compression.py`), Loneliness,
Month of Birth, Parental Style, AFI and DSI — and the copies differ in
exactly the places that cost something:

* **What a drop may take with it.** Parental Style's `delete_para`
  refused a paragraph holding a revision or a comment anchor and made
  the caller acknowledge a footnote mark; four of the others removed
  the slice and nothing else. A dropped footnote REFERENCE leaves its
  note behind with nothing pointing at it, a dropped bookmark leaves
  every link to it dangling, a dropped comment anchor orphans the
  comment — and the text of the document reads correctly in every one
  of those cases.
* **Where a split may fall.** Loneliness split at a RUN boundary found
  by a 30-character prefix; Aging_Well cut inside a run and refused a
  bookmark pair across the cut. A cut inside a field, a hyperlink or an
  equation writes a paragraph whose second half opens mid-element.
* **What a merge does with the second paragraph's runs.** Nothing —
  they carry over unchanged. Re-styling them from the first
  paragraph's opening run is how a Hyperlink or FootnoteReference
  character style strays onto prose.

What none of them handled, and all three operations here do: the
**section break**. A `w:sectPr` in a paragraph's properties is the
paragraph MARK ending a section, so it stays on whichever paragraph
ends where the original did — the second half of a split, the merged
paragraph of a merge — and a drop refuses rather than taking the
section's page setup with it.

**Every operation asserts its text contract**, the rule Aging_Well
wrote down after `sub_span` silently dropped four sentences: the
visible text afterwards is the text before, changed in exactly the
stated way. A refusal is an :class:`~docxkit.errors.AnchorError` that
names what was in the way.

These are CLEAN edits. In the revision protocol the redline is Word's
Compare of the clean copy against the baseline, which renders a split
or a merge as a paragraph-mark insertion or deletion; a paragraph that
already carries tracked changes is refused, because splitting a
revision's markup is not a clean edit of anything.
"""
from __future__ import annotations

import re

from ._xml import (
    PARA_OPEN_RE,
    escape,
    markers_before,
    own_properties,
    set_para_property,
    split_run,
    visible_text,
)
from .errors import AnchorError
from .find import para_slice

__all__ = ["AnchorError", "drop", "merge", "split"]

#: Any namespaced opening tag: a paragraph holds `w:`, `m:` (inline
#: maths), `mc:` (alternate content) and `w14:` children, and a walk
#: that knew only `w:` would read an equation as text between siblings.
_OPEN_RE = re.compile(r"<([A-Za-z][\w.-]*:[A-Za-z][\w.-]*)\b[^>]*?(/?)>")
#: The two ids Word mints per paragraph and requires to be unique. The
#: second half of a split gets neither, and Word mints fresh ones on
#: save, rather than a duplicate of the first half's.
_PARA_ID_RE = re.compile(r'\s+w14:(?:paraId|textId)="[^"]*"')

#: Markup that makes a paragraph not a clean-edit target: a revision's
#: content or its property-change snapshot.
_REVISION_RE = re.compile(
    r"<w:(?:ins|del|moveFrom|moveTo|pPrChange|rPrChange)\b")
_COMMENT_RE = re.compile(
    r"<w:(?:commentRangeStart|commentRangeEnd|commentReference)\b")
_NOTE_REF_RE = re.compile(r"<w:(?:footnoteReference|endnoteReference)\b")
#: A bookmark start's id and name, in whichever order the tag has them.
_BM_START_RE = re.compile(
    r'<w:bookmarkStart\b(?=[^>]*\bw:id="([^"]*)")'
    r'(?=[^>]*\bw:name="([^"]*)")[^>]*/>')
_BM_END_RE = re.compile(r'<w:bookmarkEnd\b[^>]*?\bw:id="([^"]*)"')
_FLD_BEGIN, _FLD_END = 'w:fldCharType="begin"', 'w:fldCharType="end"'

#: Zero-width children that OPEN what follows them. At a cut they ride
#: with the text after it; every other zero-width child — a bookmark or
#: comment END, a footnote mark, a proofing marker — belongs to the text
#: before it.
_OPENERS = ("w:bookmarkStart", "w:commentRangeStart", "w:permStart")

#: Word's own cursor bookmark, re-minted on every save and targeted by
#: nothing. A drop may take it without being asked.
_WORD_ONLY_BOOKMARKS = frozenset({"_GoBack"})

#: Markers Word writes BETWEEN paragraphs at body level — a reference
#: entry's head bookmark is hoisted out of its `w:p` on save.
_BODY_MARKER_RE = re.compile(
    r"\s*<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd"
    r"|permStart|permEnd|proofErr)\b[^>]*/>")

#: Containers that must hold at least one paragraph: Word refuses a cell,
#: a note, a comment, a text box or a header left with none.
_NEEDS_PARA_RE = re.compile(
    r"<w:(tc|footnote|endnote|comment|txbxContent|hdr|ftr)\b[^>]*>"
    r"(?:\s*<w:tcPr\b[^>]*/>|\s*<w:tcPr\b[^>]*(?<!/)>.*?</w:tcPr>)?"
    r"\s*\Z", re.DOTALL)
_CONTAINER_CLOSE_RE = re.compile(
    r"\s*</w:(?:tc|footnote|endnote|comment|txbxContent|hdr|ftr)>")
#: How far back the container's opening tag can be: a `w:tcPr` with
#: borders, shading and width runs to a few hundred bytes.
_CONTAINER_WINDOW = 4096

#: What a run holding ONLY text is made of: its tags, its properties
#: (full or empty) and its text nodes. Whatever is left is not text.
_RUN_SHELL_RE = re.compile(
    r"<w:rPr\b[^>]*/>|<w:rPr\b[^>]*(?<!/)>.*?</w:rPr>"
    r"|<w:t\b[^>]*(?<!/)>[^<]*</w:t>|<w:r\b[^>]*(?<!/)>|</w:r>",
    re.DOTALL)

#: Run properties a join's separator must NOT inherit: they belong to a
#: link or a note mark, and on prose they print a blue underline or a
#: superscript that no text-layer check can see.
_NOT_PROSE_RPR = ('w:val="Hyperlink"', 'w:val="FootnoteReference"',
                  'w:val="EndnoteReference"', "<w:vertAlign")


# ------------------------------------------------------------ the walk --


def _close(xml: str, pos: int, qname: str) -> int:
    """End of the `</qname>` closing the element opened before `pos`."""
    opener = re.compile(rf"<{re.escape(qname)}\b[^>]*?(/?)>")
    close = f"</{qname}>"
    depth = 1
    while depth:
        nxt = xml.find(close, pos)
        if nxt == -1:
            raise AnchorError(f"paragraph: <{qname}> is never closed")
        for m in opener.finditer(xml, pos, nxt):
            if m.group(1) != "/":
                depth += 1
        depth -= 1
        pos = nxt + len(close)
    return pos


def _children(para: str) -> tuple[str, list[tuple[str, str]]]:
    """``(open tag, [(qname, xml), ...])`` — every DIRECT child, in order.

    Whitespace between children is kept as ``("", ws)`` so the pieces
    reassemble the paragraph byte for byte, which is asserted: a walk
    that silently dropped a child would delete it on the first edit.
    """
    m = PARA_OPEN_RE.match(para)
    if m is None:
        raise AnchorError("paragraph: not a <w:p>")
    if m.group(1) == "/":
        return m.group(0), []
    inner = para[m.end():para.rindex("</w:p>")]
    kids: list[tuple[str, str]] = []
    pos = 0
    while (om := _OPEN_RE.search(inner, pos)) is not None:
        if inner[pos:om.start()].strip():
            raise AnchorError("paragraph: text outside any element")
        if om.start() > pos:
            kids.append(("", inner[pos:om.start()]))
        qname = om.group(1)
        end = om.end() if om.group(2) == "/" else _close(
            inner, om.end(), qname)
        kids.append((qname, inner[om.start():end]))
        pos = end
    if inner[pos:].strip():
        raise AnchorError("paragraph: text outside any element")
    if pos < len(inner):
        kids.append(("", inner[pos:]))
    if m.group(0) + "".join(x for _t, x in kids) + "</w:p>" != para:
        raise AnchorError("paragraph: the child walk does not round-trip")
    return m.group(0), kids


def _refuse_revisions(para: str, doing: str) -> None:
    if _REVISION_RE.search(para):
        raise AnchorError(
            f"{doing}: the paragraph carries tracked changes. Accept or "
            f"reject them first — this is a clean edit, and the redline "
            f"is Compare's to make.")


def _ppr(kids: list[tuple[str, str]]) -> str:
    return next((x for t, x in kids if t == "w:pPr"), "")


def _sect_pr(para: str) -> str:
    """The `w:sectPr` in this paragraph's own properties, or ``""``."""
    own = own_properties(para, "pPr")
    if own is None:
        return ""
    m = re.search(r"<w:sectPr\b.*?</w:sectPr>|<w:sectPr\b[^>]*/>",
                  own[2], re.DOTALL)
    return m.group(0) if m else ""


def _fields_balanced(pieces: list[str]) -> bool:
    joined = "".join(pieces)
    return joined.count(_FLD_BEGIN) == joined.count(_FLD_END)


def _bookmarks(xml: str) -> tuple[dict[str, str], set[str]]:
    """``({id: name} started, {id} ended)`` in `xml`."""
    starts = {m.group(1): m.group(2) for m in _BM_START_RE.finditer(xml)}
    return starts, set(_BM_END_RE.findall(xml))


# --------------------------------------------------------------- split --


def _cut(kids: list[tuple[str, str]], lo: int, hi: int
         ) -> tuple[list[str], list[str]]:
    """Content before `lo` and from `hi`, with `[lo, hi)` removed.

    The removed span may only be text in plain runs — it is the
    whitespace at a split, never content anyone asked to lose.
    """
    head: list[str] = []
    tail: list[str] = []
    cursor = 0
    # A field is one unit to a reader: its `begin`, instruction and
    # `separate` runs have no width, and deciding their side one by one
    # would leave a citation's instruction in one paragraph and its label
    # in the next. They go wherever the `begin` went.
    depth, field_side = 0, head
    for tag, x in kids:
        if tag in ("", "w:pPr"):
            continue
        a = cursor
        b = cursor + len(visible_text(x))
        cursor = b
        begins = tag == "w:r" and _FLD_BEGIN in x
        if a == b:                                  # zero-width
            if depth > 0 and not begins:
                side = field_side
            elif a < lo or (a <= hi and tag not in _OPENERS
                            and not begins):
                side = head
            else:
                side = tail
            side.append(x)
            if begins:
                field_side = side
            if tag == "w:r":
                depth += x.count(_FLD_BEGIN) - x.count(_FLD_END)
            continue
        if depth > 0:
            # a field's RESULT — its visible label. The begin/end counts
            # on each side would balance with the label cut in two, or
            # with part of it moved across, so the side is checked here.
            natural = head if b <= lo else tail if a >= hi else None
            if natural is not field_side:
                raise AnchorError("split: the cut falls inside a field "
                                  "(a citation or cross-reference)")
            field_side.append(x)
            if tag == "w:r":
                depth += x.count(_FLD_BEGIN) - x.count(_FLD_END)
            continue
        if tag == "w:r":
            depth += x.count(_FLD_BEGIN) - x.count(_FLD_END)
        if b <= lo:
            head.append(x)
            continue
        if a >= hi:
            tail.append(x)
            continue
        if tag != "w:r":
            raise AnchorError(f"split: the cut falls inside a <{tag}>")
        if a < lo:
            head.append(split_run(x, lo - a)[0])
        if b > hi:
            tail.append(split_run(x, hi - a)[1])
        elif a >= lo:
            # wholly inside the removed span: whitespace, and only that
            body = _RUN_SHELL_RE.sub("", x)
            if body.strip():
                raise AnchorError("split: the space before the cut shares "
                                  "a run with something else")
    return head, tail


def split(xml: str, sig: str, before: str, *, also: str | None = None,
          normalize: bool = False) -> str:
    """Cut the ONE paragraph containing `sig` in two, before `before`.

    `before` must occur exactly once in that paragraph's visible text,
    and not at its start. The spaces immediately before the cut are
    dropped — they would end the first paragraph with invisible
    trailing whitespace, which Compare then reports as an edit — unless
    they share a run with something that is not text, in which case
    they stay.

    **The first half** keeps the paragraph's tag and its properties
    minus any `w:sectPr`; **the second half** gets the properties whole,
    including the section break, because its mark is the original mark.
    It gets no `w14:paraId`: two paragraphs may not share one, and Word
    mints a fresh id on save.

    Refused, by name: a cut inside a hyperlink, an equation or any
    element that is not a run; a cut inside a field; a bookmark pair
    whose two ends would land in different halves; a paragraph with
    tracked changes.
    """
    s, e = para_slice(xml, sig, also, normalize=normalize)
    para = xml[s:e]
    _refuse_revisions(para, "split")
    whole = visible_text(para)
    hits = whole.count(before)
    if hits != 1:
        raise AnchorError(f"split({before[:40]!r}): {hits} hits in the "
                          f"paragraph, need 1")
    at = whole.index(before)
    if at == 0 or not whole[:at].strip():
        raise AnchorError(f"split({before[:40]!r}): that is where the "
                          f"paragraph starts — nothing would be left before "
                          f"the cut")
    open_tag, kids = _children(para)

    lo = at
    while lo > 0 and whole[lo - 1] == " ":
        lo -= 1
    try:
        head, tail = _cut(kids, lo, at)
    except AnchorError:
        if lo == at:
            raise
        head, tail = _cut(kids, at, at)          # keep the spaces
        lo = at

    if not _fields_balanced(head) or not _fields_balanced(tail):
        raise AnchorError(f"split({before[:40]!r}): the cut falls inside a "
                          f"field (a citation or cross-reference)")
    starts, ends = _bookmarks(para)
    head_starts, head_ends = _bookmarks("".join(head))
    for bid in starts.keys() & ends:
        if (bid in head_starts) != (bid in head_ends):
            raise AnchorError(
                f"split({before[:40]!r}): bookmark {starts[bid]!r} would "
                f"start in one paragraph and end in the other")

    ppr = _ppr(kids)
    first = f"{open_tag}{ppr}{''.join(head)}</w:p>"
    if _sect_pr(first):
        first = set_para_property(first, "sectPr", "")
    second = f"{_PARA_ID_RE.sub('', open_tag)}{ppr}{''.join(tail)}</w:p>"

    got = visible_text(first) + visible_text(second)
    if got != whole[:lo] + whole[at:]:
        raise AnchorError(f"split({before[:40]!r}): the text changed — "
                          f"{got[:80]!r}")
    return xml[:s] + first + second + xml[e:]


# --------------------------------------------------------------- merge --


def _next_para(xml: str, pos: int) -> tuple[int, int, int] | None:
    """``(markers_end, start, end)`` of the paragraph right after `pos`.

    Body-level markers between the two are allowed — Word hoists them
    there — and nothing else is: a table, a section or the end of the
    container in between means there is no NEXT paragraph to merge with.
    """
    at = pos
    while (m := _BODY_MARKER_RE.match(xml, at)) is not None:
        at = m.end()
    ws = re.compile(r"\s*").match(xml, at)
    start = ws.end() if ws else at
    m = PARA_OPEN_RE.match(xml, start)
    if m is None:
        return None
    end = m.end() if m.group(1) == "/" else _close(xml, m.end(), "w:p")
    return at, start, end


def _separator_rpr(kids: list[tuple[str, str]]) -> str:
    """The rPr of the first paragraph's LAST prose run, or ``""``."""
    depth = 0
    candidates: list[str] = []
    for tag, x in kids:
        if tag != "w:r":
            continue
        opened_here = depth > 0 or _FLD_BEGIN in x
        depth += x.count(_FLD_BEGIN) - x.count(_FLD_END)
        if opened_here or not visible_text(x):
            continue
        own = own_properties(x, "rPr")
        rpr = x[own[0]:own[1]] if own else ""
        if not any(bad in rpr for bad in _NOT_PROSE_RPR):
            candidates.append(rpr)
    return candidates[-1] if candidates else ""


def merge(xml: str, first: str, second: str, *, sep: str = " ",
          normalize: bool = False) -> str:
    """Join the paragraph containing `first` with the one after it.

    `second` must be in that NEXT paragraph — naming both is how a merge
    states which two it means, and a merge with the wrong neighbour is
    refused rather than performed. The result reads as the first
    paragraph's text, then `sep`, then the second's: pass ``sep=""``
    when either side already carries the space.

    The merged paragraph keeps the first one's tag and properties; the
    second one's RUNS come across untouched. `sep` is written as a run
    with the first paragraph's last PROSE run's properties — never a
    link's or a note mark's. Body-level markers Word hoisted between the
    two paragraphs move into the join, where they stood in reading order.

    **Section breaks:** the second paragraph's mark is the merged one's,
    so a `w:sectPr` there is carried onto it. One on the FIRST paragraph
    is refused — the two paragraphs are in different sections, and a
    merge would erase the break between them.
    """
    s1, e1 = para_slice(xml, first, normalize=normalize)
    s2, e2 = para_slice(xml, second, normalize=normalize)
    nxt = _next_para(xml, e1)
    if nxt is None or nxt[1:] != (s2, e2):
        raise AnchorError(
            f"merge({first[:30]!r}, {second[:30]!r}): the second paragraph "
            f"is not the one immediately after the first")
    markers_end = nxt[0]
    p1, p2 = xml[s1:e1], xml[s2:e2]
    _refuse_revisions(p1, "merge")
    _refuse_revisions(p2, "merge")
    if _sect_pr(p1):
        raise AnchorError(
            f"merge({first[:30]!r}, ...): the first paragraph ends a "
            f"section; merging would erase the section break")

    open1, kids1 = _children(p1)
    _open2, kids2 = _children(p2)
    between = xml[e1:markers_end].strip()
    joint = ""
    if sep:
        space = ' xml:space="preserve"' if sep != sep.strip() else ""
        joint = (f"<w:r>{_separator_rpr(kids1)}<w:t{space}>{escape(sep)}"
                 f"</w:t></w:r>")
    body1 = "".join(x for t, x in kids1 if t != "w:pPr")
    body2 = "".join(x for t, x in kids2 if t != "w:pPr")
    merged = f"{open1}{_ppr(kids1)}{body1}{between}{joint}{body2}</w:p>"
    if sect := _sect_pr(p2):
        merged = set_para_property(merged, "sectPr", sect)

    want = visible_text(p1) + sep + visible_text(p2)
    if visible_text(merged) != want:
        raise AnchorError(f"merge({first[:30]!r}, ...): the text changed")
    return xml[:s1] + merged + xml[e2:]


# ---------------------------------------------------------------- drop --


def _hoisted_head(xml: str, start: int) -> int:
    """Where the paragraph at `start` really begins, its hoisted marker in.

    Word moves a paragraph-head bookmark OUT of the `w:p` on save, to the
    gap just before it. A COMPLETE set there — every start with its end —
    belongs to this paragraph; a lone end is somebody else's, and then
    the gap is left alone.

    Read tag by tag (:func:`_xml.markers_before`), not through a 2,048-
    character lookback: a docxkit-built head bookmark redeclares its
    namespaces and runs to ~2,500 characters, so none fitted and the
    marker stayed behind when its paragraph was dropped.
    """
    markers = markers_before(xml, start)
    k = len(markers)
    while k > 0 and markers[k - 1].family == "bookmark":
        k -= 1
    run = markers[k:]
    if not run:
        return start
    starts = {m.id for m in run if m.opens}
    ends = {m.id for m in run if not m.opens}
    return run[0].start if starts == ends else start


def drop(xml: str, sig: str, *, also: str | None = None,
         normalize: bool = False, allow_bookmarks: bool = False,
         allow_notes: bool = False) -> str:
    """Remove the ONE paragraph containing `sig`.

    What goes with it has to be meant, so each of these is refused by
    name unless allowed:

    * **a bookmark** (`allow_bookmarks`) — every link to it would
      dangle. Word's own `_GoBack` is exempt. The paragraph-head
      bookmark Word hoists out of the paragraph goes with it, as it
      would have had Word not moved it.
    * **a footnote or endnote reference** (`allow_notes`) — the note
      stays in its part with nothing pointing at it; follow the drop
      with :func:`docxkit.footnotes.prune_orphans`.

    And these are refused outright: a section break (the paragraph's
    mark ends a section — move the `w:sectPr` first), a comment anchor
    (the comment would survive with nothing to annotate), a bookmark
    only HALF of which is in the paragraph, tracked changes, and the
    last paragraph of a table cell, a note, a comment, a text box or a
    header, none of which Word will open empty.
    """
    own_start, e = para_slice(xml, sig, also, normalize=normalize)
    s = _hoisted_head(xml, own_start)
    para = xml[s:e]
    what = f"drop({sig[:40]!r})"
    _refuse_revisions(para, "drop")
    if _sect_pr(xml[own_start:e]):
        raise AnchorError(f"{what}: the paragraph's mark ends a section; "
                          f"move its w:sectPr to a neighbour first")
    if _COMMENT_RE.search(para):
        raise AnchorError(f"{what}: the paragraph anchors a comment")
    if _NOTE_REF_RE.search(para) and not allow_notes:
        raise AnchorError(f"{what}: the paragraph holds a note reference "
                          f"(allow_notes=True, then footnotes.prune_orphans)")
    starts, ends = _bookmarks(para)
    halves = sorted(starts.keys() ^ ends)
    if halves:
        raise AnchorError(f"{what}: only half of bookmark id(s) {halves} "
                          f"is in the paragraph")
    named = sorted(n for n in starts.values()
                   if n not in _WORD_ONLY_BOOKMARKS)
    if named and not allow_bookmarks:
        raise AnchorError(f"{what}: the paragraph holds bookmark(s) "
                          f"{named}; links to them would dangle "
                          f"(allow_bookmarks=True)")
    if (_NEEDS_PARA_RE.search(xml, max(0, s - _CONTAINER_WINDOW), s)
            and _CONTAINER_CLOSE_RE.match(xml, e)):
        raise AnchorError(f"{what}: it is the only paragraph in its "
                          f"container, which Word will not open empty")
    return xml[:s] + xml[e:]
