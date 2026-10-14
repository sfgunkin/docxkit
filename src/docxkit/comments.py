r"""Attaching a comment to every tracked revision, in XML.

Word's ``Comments.Add`` is unusable at scale: ~0.5s per call at the 50th
comment and ~3.4s at the 250th, because each call relays out the comment
story (and because the surrounding loop indexed the O(i) ``Revisions``
collection). Three hundred comments took 15-20 minutes and eventually
provoked "Call was rejected by callee".

Writing the comment package directly takes about a second. Word still does
the diff; this module does the annotation.

The classification rules stay with the project — a paper's comments name
its own referee points — so callers pass a ``classify(ctx)`` function and
get :class:`RevisionContext` for each revision.
"""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from . import revisions as _revisions
from ._xml import (
    COMMENT_ID_RE,
    COMMENTS,
    DOCUMENT,
    MATH_ZONE_RE,
    PARA_RE,
    Parts,
    delta_text,
    element_spans,
    escape_attr,
    normalize_glyphs,
    own_properties,
    set_run_text,
    text_parts,
    visible_text,
)
from ._xml import (
    append_before_close as _append_before_close,
)
from .errors import AnchorError, PackageError, ScaffoldMissing
from .find import para_text_at, table_index_at, table_spans

__all__ = [
    "ALL",
    "COALESCE",
    "GENERIC",
    "SCAFFOLD",
    "AnchorError",
    "Block",
    "Comment",
    "Credit",
    "PackageError",
    "RevisionContext",
    "ScaffoldMissing",
    "Thread",
    "add_at",
    "annotate",
    "annotate_blocks",
    "has_scaffold",
    "match",
    "read_all",
    "reclassify",
    "remove",
    "set_done",
    "threads",
]

GENERIC = "Revision (unclassified)"
#: What Word writes where a build has no reason and was told to leave a
#: revision bare (``generic=None``): Word cannot add an empty comment,
#: and the build needs one to clone. `tracked.build` takes every comment
#: still reading this out of the package before it is written.
SCAFFOLD = "docxkit: no reason given; this comment is removed by the build"

#: `tables` policies for :func:`annotate`.
COALESCE = "coalesce"   # one balloon per distinct comment text per table
ALL = "all"             # comment every changed cell (pre-coalescing builds)

# CT_Comment's content is optional, so `<w:comment w:id="1" .../>` is a
# comment with nothing in it — and read as an open tag it ran on to the
# NEXT comment's close: that comment's words were filed under the empty
# one's id, and whatever this module did to "comment 1" it did to both
# (2026-09-17). Every comment pattern here now reads the empty form for
# what it is: PARA_RE's `(?<!/)>` guard where the caller wants a comment
# with text, as this one does, and a captured slash where the caller must
# still see the comment (`_comment_records`, `remove`).
_COMMENT_RE = re.compile(
    r'(<w:comment [^>]*w:id="(\d+)"[^>]*(?<!/)>)(.*?)(</w:comment>)',
    re.DOTALL)
_ANCHOR_SLACK = 60          # chars scanned either side for an existing range
_WINDOW_BACK = 3000         # context behind the anchor, in chars of markup

# Word writes four parts per comment; the last three are extensions keyed
# by paraId/durableId. Ids are derived from the comment id in reserved
# high ranges so they cannot collide with Word's own.
_PARA_ID_BASE = 0x5A000000
_DURABLE_ID_BASE = 0x6B000000


@dataclass(frozen=True)
class RevisionContext:
    """What a classifier gets to decide a revision's comment."""

    text: str                # the revision's own text, deletions included
    para: str                # visible text of the containing paragraph
    window: str              # surrounding prose, tags stripped
    table_index: int | None  # which manuscript table, if any
    start: int
    end: int

    @property
    def haystack(self) -> str:
        """Everything searchable, widest scope — a LAST resort.

        Matching a rule table straight against this labels a revision by
        whatever signature appears anywhere nearby, so when two points edit
        the same paragraph the first rule in the table wins both. On the AFI
        r2 round that mislabelled 4 of 19 points, and a comment naming the
        wrong point is worse than none: it is what the reviewer reads.
        Prefer :func:`match`, which tries the revision's own text first.
        """
        return f"{self.para} {self.window} {self.text}"


class _Planned(NamedTuple):
    """One revision, the comment decided for it, and the table it sits in."""

    start: int
    end: int
    comment: str | None
    table: int | None


def match(rules: Iterable[tuple[str, str]],
          tables: dict[int, str] | None = None,
          *, normalize: bool = True
          ) -> Callable[[RevisionContext], str | None]:
    """A classifier that tries the narrowest scope first.

    `rules` is (signature, comment) in priority order, as papers already
    write them. Each scope is searched in turn — the revision's own text,
    then its paragraph, then the surrounding window — so a revision is
    labelled by the point that produced it rather than by a neighbour's
    signature that happens to sit in the same paragraph.

    `tables` maps a table index to the comment for revisions inside it.
    Cells of a regenerated table are bare numbers that no prose signature
    can match, and without this they fall through to the generic balloon.

    Keep signatures SHORT. Word splits a long insertion into fragments
    ("growth slowdown that" / "is projected to cause..."), and a needle
    spanning the split matches neither.
    """
    rules = list(rules)
    fold = normalize_glyphs if normalize else (lambda s: s)
    folded = [(fold(sig), comment) for sig, comment in rules]

    def classify(ctx: RevisionContext) -> str | None:
        for scope in (ctx.text, ctx.para, ctx.window):
            if not scope:
                continue
            hay = fold(scope)
            for sig, comment in folded:
                if sig in hay:
                    return comment
        if tables and ctx.table_index is not None:
            return tables.get(ctx.table_index)
        return None

    return classify


def _context(doc: str, start: int, end: int,
             spans: list[tuple[int, int]]) -> RevisionContext:
    return RevisionContext(
        text=delta_text(doc[start:end]),
        para=para_text_at(doc, start),
        window=re.sub("<[^>]+>", "", doc[max(0, start - _WINDOW_BACK):end]),
        table_index=table_index_at(spans, start),
        start=start, end=end)


def _already_anchored(doc: str, start: int, end: int) -> bool:
    return ("commentRangeStart" in doc[max(0, start - _ANCHOR_SLACK):start]
            and "commentRangeEnd" in doc[end:end + _ANCHOR_SLACK])


def _clone_comment(template: str, cid: int, para_id: str, text: str) -> str:
    """A copy of Word's own comment element carrying `text`.

    Cloning rather than hand-writing keeps the author, date, style and
    namespace prefixes exactly as Word wrote them. `template` is
    :func:`_plain`'s: one paragraph and one text run, so the id, the
    paraId and the text each have exactly one place to go.
    """
    x = re.sub(r'w:id="\d+"', f'w:id="{cid}"', template, count=1)
    x = re.sub(r'w14:paraId="[0-9A-Fa-f]{8}"', f'w14:paraId="{para_id}"',
               x, count=1)
    return set_run_text(x, text)


#: The run Word opens every comment paragraph with: the balloon's mark.
_ANNOTATION_REF = ('<w:r><w:rPr><w:rStyle w:val="CommentReference"/>'
                   "</w:rPr><w:annotationRef/></w:r>")


def _plain(comment: str) -> str:
    """`comment` cut down to what a clone may carry from it.

    The comment cloned is whichever the package holds first, and that
    is the author's or a referee's as often as Word's seed (review of
    2026-10-14). Copied whole, a TWO-paragraph comment gave every clone
    an empty second paragraph carrying the template's last paraId — the
    one Word and :func:`threads` key the done state on, so new balloons
    read resolved and a reply landed on the referee's; a comment with
    no text kept the referee's words in every clone; one holding a
    ``w:ins`` duplicated its revision id. 17 of 274 Word-saved
    manuscripts with a comment open on a multi-paragraph one.

    So: the element's own open tag, its FIRST paragraph's open tag and
    paragraph style, the annotation mark and one empty text run.
    """
    head = re.match(r"<w:comment\b[^>]*(?<!/)>", comment)
    para = PARA_RE.search(comment)
    assert head is not None              # _Scaffold.read matched one
    if para is None:
        return (f"{head.group(0)}<w:p>{_ANNOTATION_REF}<w:r><w:t></w:t>"
                "</w:r></w:p></w:comment>")
    body = para.group(0)
    p_open = re.match(r"<w:p\b[^>]*(?<!/)>", body)
    assert p_open is not None            # PARA_RE opens on one
    style = ""
    if (own := own_properties(body, "pPr")) is not None:
        found = re.search(r'<w:pStyle\b[^>]*w:val="([^"]*)"', own[2])
        if found:
            style = (f'<w:pPr><w:pStyle w:val="{found.group(1)}"/>'
                     "</w:pPr>")
    return (f"{head.group(0)}{p_open.group(0)}{style}{_ANNOTATION_REF}"
            "<w:r><w:t></w:t></w:r></w:p></w:comment>")


def _anchor(cid: int) -> tuple[str, str]:
    """(range start, range end + reference run) for comment `cid`."""
    start = f'<w:commentRangeStart w:id="{cid}"/>'
    end = (f'<w:commentRangeEnd w:id="{cid}"/>'
           '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
           f'<w:commentReference w:id="{cid}"/></w:r>')
    return start, end


def _plan(doc: str, classify: Callable[[RevisionContext], str | None],
          spans: list[tuple[int, int]]) -> list[_Planned]:
    """Every revision that still needs a comment, with its verdict."""
    return [_Planned(s, e, classify(_context(doc, s, e, spans)),
                     table_index_at(spans, s))
            for s, e in _revisions.spans(doc)
            if not _already_anchored(doc, s, e)]


def _coalesce_tables(planned: list[_Planned]) -> list[_Planned]:
    """Keep one comment per distinct text per table; leave prose alone.

    Word emits a separate revision for every changed CELL, so a
    regenerated table arrives as hundreds of revisions that all mean the
    same thing — AFI's R2 round had 153 in one table and 105 in another,
    281 of its 368 revisions in total. Commenting each one costs almost
    nothing to store (the repetition compresses away) but buries the
    handful of balloons that carry meaning.

    Coalescing on the comment TEXT rather than simply taking the first
    revision matters: AFI's Table 4 has both a columns-removed comment
    and a different one for the header relabel, and keeping only the
    first would silently drop whichever came second.

    Prose is never coalesced. Two paragraphs answering the same referee
    point are two places the reader has to be shown.
    """
    seen: set[tuple[int, str | None]] = set()
    kept = []
    for entry in planned:
        if entry.table is None:
            kept.append(entry)
            continue
        key = (entry.table, entry.comment)
        if key not in seen:
            seen.add(key)
            kept.append(entry)
    return kept


class _Scaffold(NamedTuple):
    """Word's own comment parts, which new comments are cloned from.

    The template, author, date, styles and namespace prefixes have to come
    from a comment Word created; hand-writing them is how a package ends
    up "repaired" on open.
    """

    comments_xml: str
    template: str
    next_id: int
    date_utc: str | None

    @classmethod
    def read(cls, parts: Parts) -> _Scaffold:
        com = parts[COMMENTS].decode("utf-8")
        # A comment WITH content: an empty one has no paragraph to carry
        # the new text, and read as an open tag it cloned as two.
        tm = re.search(r"<w:comment [^>]*(?<!/)>.*?</w:comment>", com,
                       re.DOTALL)
        if not tm:
            raise ScaffoldMissing(
                "no comment scaffold - Word must create at least one comment "
                "before the XML pass can clone it")
        extensible = parts.get("word/commentsExtensible.xml", b"")
        utc = re.search(r'w16cex:dateUtc="([^"]+)"',
                        extensible.decode("utf-8") or "")
        return cls(
            comments_xml=com,
            template=_plain(tm.group(0)),
            next_id=1 + max(int(i) for i in COMMENT_ID_RE.findall(com)),
            date_utc=utc.group(1) if utc else None)


def _decide(planned: list[_Planned],
            generic: str | None) -> list[tuple[int, int, str]]:
    """Settle each revision's final text, dropping what stays bare.

    Resolving the fallback once here rather than at each insertion is what
    lets `generic=None` mean "leave it uncommented" without the write step
    having to know about it. An EMPTY answer is no answer: `''` became
    "Revision (unclassified)" under `generic=None`, the one outcome the
    flag exists to prevent, while the build counted it classified.
    """
    return [(p.start, p.end, p.comment or generic or GENERIC)
            for p in planned
            if p.comment or generic is not None]


class Credit(NamedTuple):
    """Who a comment this package writes is from, and when."""

    author: str
    initials: str
    date: str        # w:date, ISO 8601 UTC


def _math_zones(doc: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every equation, display or inline, outermost."""
    return [m.span() for m in MATH_ZONE_RE.finditer(doc)]


def _outside_math(zones: list[tuple[int, int]], start: int,
                  end: int) -> tuple[int, int]:
    """`start`..`end` widened to the equation it touches, if any.

    A comment range marker may sit beside an equation and not inside
    one: ``m:r`` admits no ``w:commentRangeStart``, and ``m:ctrlPr``
    holds only properties and their revision flags. `revisions.spans`
    finds both kinds of ``w:ins`` inside equations — 446 of LI7's 1,759
    — and anchoring on them wrote maths Word renders as blank boxes
    (review of 2026-10-14). The balloon goes round the whole equation.
    """
    for lo, hi in zones:
        if lo < end and start < hi:
            start, end = min(start, lo), max(end, hi)
    return start, end


def _place(doc: str, anchors: Sequence[tuple[int, int, int]]) -> str:
    """`doc` with each ``(start, end, cid)`` comment range written in.

    In ONE ascending pass over every insertion point rather than back
    to front: two ranges widened to the same equation share their
    offsets, and a back-to-front splice put the second one's end inside
    the first one's range start.
    """
    zones = _math_zones(doc)
    events: list[tuple[int, int, int, str]] = []
    for n, (at_start, at_end, cid) in enumerate(anchors):
        start, end = _outside_math(zones, at_start, at_end)
        open_tag, close_tag = _anchor(cid)
        # at one offset: a range that ENDS there closes before one opens
        events += [(start, 1, n, open_tag), (end, 0, -n, close_tag)]
    out, at = [], 0
    for pos, _kind, _n, tag in sorted(events):
        out += [doc[at:pos], tag]
        at = pos
    return "".join(out) + doc[at:]


def _write(parts: Parts, doc: str,
           decided: list[tuple[int, int, str]],
           scaffold: _Scaffold, *, credit: Credit | None = None,
           extra: Sequence[tuple[int, int, int]] = ()) -> list[str]:
    """Anchor each comment in the body and add its four part entries;
    returns the new comment ids.

    `credit` restamps every new comment's author, initials and date.
    Without it a clone is credited to whoever wrote the comment it was
    cloned from — Word's user for a seed, a referee when theirs came
    first. `extra` anchors ``(start, end, id)`` for comments that are
    already defined, in the same pass."""
    elements, exts, ids, exls = [], [], [], []
    anchors = list(extra)
    date_utc = credit.date if credit else scaffold.date_utc
    for i, (start, end, comment) in enumerate(decided):
        cid = scaffold.next_id + i
        para_id = f"{_PARA_ID_BASE + cid:08X}"
        durable = f"{_DURABLE_ID_BASE + cid:08X}"
        anchors.append((start, end, cid))
        element = _clone_comment(scaffold.template, cid, para_id, comment)
        if credit:
            element = _stamp(element, credit)
        elements.append(element)
        exts.append(f'<w15:commentEx w15:paraId="{para_id}" w15:done="0"/>')
        ids.append(f'<w16cid:commentId w16cid:paraId="{para_id}" '
                   f'w16cid:durableId="{durable}"/>')
        if date_utc:
            exls.append('<w16cex:commentExtensible w16cex:durableId='
                        f'"{durable}" w16cex:dateUtc="{date_utc}"/>')
    doc = _place(doc, anchors)

    parts[DOCUMENT] = doc.encode("utf-8")
    parts[COMMENTS] = _append_before_close(
        scaffold.comments_xml, "</w:comments>",
        "".join(elements)).encode("utf-8")
    # The three side parts must stay in step with comments.xml or Word
    # reports unreadable content.
    for name, close, add in (
            ("word/commentsExtended.xml", "</w15:commentsEx>", exts),
            ("word/commentsIds.xml", "</w16cid:commentsIds>", ids),
            ("word/commentsExtensible.xml", "</w16cex:commentsExtensible>",
             exls)):
        if name in parts and add:
            parts[name] = _append_before_close(
                parts[name].decode("utf-8"), close, "".join(add)
            ).encode("utf-8")
    return [str(scaffold.next_id + i) for i in range(len(decided))]


def _stamp(element: str, credit: Credit) -> str:
    """A comment element's open tag credited to `credit`, whatever it
    carried; an attribute it lacks is added."""
    head = re.match(r"<w:comment\b[^>]*?(/?)>", element)
    assert head is not None
    tag = head.group(0)
    for name, value in (("w:author", credit.author),
                        ("w:initials", credit.initials),
                        ("w:date", credit.date)):
        attr = f'{name}="{escape_attr(value)}"'
        # a function, not a template: a backslash in a name is not a group
        tag, found = re.subn(rf'\b{name}="[^"]*"', _constant(attr), tag)
        if not found:
            cut = len(tag) - len(head.group(1)) - 1
            tag = f"{tag[:cut]} {attr}{tag[cut:]}"
    return tag + element[head.end():]


def _constant(text: str) -> Callable[[re.Match[str]], str]:
    """A replacement that is `text` verbatim, backslashes and all."""
    return lambda _m: text


def annotate(parts: Parts,
             classify: Callable[[RevisionContext], str | None],
             *, generic: str | None = GENERIC,
             tables: str = COALESCE,
             credit: Credit | None = None) -> tuple[int, int]:
    """Comment the run-level revisions in ``document.xml``.

    The package must already carry Word's comment scaffold — at least one
    comment Word itself created — so the parts, styles and relationships
    are Word's own rather than hand-rolled. :func:`docxkit.tracked.build`
    arranges that.

    ``generic`` is the comment for revisions no rule matched. Pass ``None``
    to leave those **uncommented** instead.

    ``tables`` decides what happens inside a table, where Word makes every
    changed cell its own revision:

    ``COALESCE`` (default)
        One balloon per distinct comment text per table.
    ``ALL``
        Comment every cell. Reproduces a deliverable built before
        coalescing existed; not what you want for a new round.

    Returns (comments added, comments that fell back to `generic`). The
    second number counts COMMENTS, not revisions, so a table whose cells
    match no rule reports 1 — one missing rule — instead of 153. Getting
    that wrong made AFI's "add a signature to SIG_MAP" warning fire 272
    times for cells that were deliberately bare.

    ``credit`` restamps the new comments' author, initials and date (see
    :func:`_write`).

    Idempotent: revisions that already carry an anchor are skipped.
    """
    if tables not in (COALESCE, ALL):
        raise ValueError(f"tables must be {COALESCE!r} or {ALL!r}, "
                         f"not {tables!r}")
    doc = parts[DOCUMENT].decode("utf-8")
    scaffold = _Scaffold.read(parts)

    planned = _plan(doc, classify, table_spans(doc))
    if tables == COALESCE:
        planned = _coalesce_tables(planned)
    unclassified = sum(1 for p in planned if not p.comment)
    decided = _decide(planned, generic)

    _write(parts, doc, decided, scaffold, credit=credit)
    return len(decided), unclassified


def add_at(parts: Parts, anchor: str, comment: str, *,
           normalize: bool = True) -> int:
    """Comment the paragraph containing `anchor`. Returns its comment id.

    :func:`annotate` can only reach text that a revision touched, so a
    paragraph the round left ALONE cannot be flagged with it — and
    "unchanged, but the author needs to look at this" is exactly the case
    a review round has to be able to express. This anchors on visible
    text instead, so the paragraph needs no revision.

    The whole paragraph is the anchor range: a comment on an unchanged
    paragraph is about the paragraph, and a sub-span would need offset
    arithmetic across the run fragmentation Word applies at rsid
    boundaries.

    Like the rest of this module it needs Word's own comment scaffold
    already in the package (see :class:`_Scaffold`).
    """
    doc = parts[DOCUMENT].decode("utf-8")
    fold = normalize_glyphs if normalize else (lambda s: s)
    needle = fold(anchor)
    hits = [m for m in PARA_RE.finditer(doc)
            if needle in fold(visible_text(m.group(0)))]
    if not hits:
        raise AnchorError(f"no paragraph contains {anchor!r}")
    if len(hits) > 1:
        raise AnchorError(
            f"{len(hits)} paragraphs contain {anchor!r} - narrow the anchor")

    para = hits[0]
    body = para.group(0)
    # after <w:pPr>...</w:pPr> if present, else straight after <w:p ...>.
    # Depth-aware: a tracked formatting change nests a snapshot of the
    # old pPr inside the live one, and stepping to the first close tag
    # opened the comment range INSIDE that historical record.
    own = own_properties(body, "pPr")
    if own is not None:
        at = own[1]
    else:
        popen = re.match(r"<w:p(?: [^>]*)?>", body)
        assert popen is not None    # PARA_RE guarantees the <w:p opens
        at = popen.end()
    start = para.start() + at
    end = para.end() - len("</w:p>")

    scaffold = _Scaffold.read(parts)
    _write(parts, doc, [(start, end, comment)], scaffold)
    return scaffold.next_id


Block = tuple[Sequence[int], str]
"""``(span indices, comment)``: one balloon over a group of revisions.
The indices are positions in :func:`docxkit.revisions.spans` of the
package's ``document.xml``; the balloon anchors on the group's first."""


def annotate_blocks(parts: Parts, blocks: Iterable[Block], *, author: str,
                    initials: str, reuse: str | None = None,
                    date: str | None = None,
                    partial: bool = False) -> list[str]:
    """One balloon per block of revision spans; returns the comment ids.

    The parts-level half of :func:`docxkit.tracked.annotate_in_place`,
    which says why it exists (HPPA_Index, 2026-10-10). `blocks` must
    cover every span of ``document.xml`` exactly once, so a reason
    cannot silently miss a change: Word splits one edit into many
    fragments (a merged paragraph is a dozen ins/del pairs, a rebuilt
    table hundreds), and the caller groups them. Anchored by span INDEX
    rather than by searching near the text, because `_already_anchored`
    misses a comment Word made, whose range spans a whole group.

    `reuse` names a comment already in ``comments.xml`` with no anchor,
    the one Word made on a seeded copy; it becomes the first block's
    balloon, so nothing is left anchored nowhere. New comments are
    credited to `author` and `initials`, never to whoever wrote the
    comment that was cloned, which can be a referee's.

    Refuses, leaving `parts` as it was, unless ``document.xml`` minus
    the new anchors is byte-identical to before; the tracked views and
    the revision counts are then unchanged by construction.

    Refuses as well, before anything is anchored (review of 2026-10-14):

    * when a span already carries a balloon credited to `author` — a
      second run would put the stale and the corrected reason side by
      side on every change and report a clean count;
    * when the package holds revisions NO block can name: property-only
      changes, moves and paragraph marks in a paragraph (or a table row)
      with no span, and every revision outside ``document.xml``.
      HPPA's own script covered such a change with :func:`add_at`, and
      this function had promised full coverage over 58 ``rPrChange``
      and 91 ``pPrChange`` it could not see. ``partial=True`` accepts
      that the balloons explain the spans only.

    `date` is the new comments' ``w:date`` (UTC, ISO 8601), now when
    omitted.
    """
    blocks = [(list(indices), text) for indices, text in blocks]
    work = dict(parts)
    before = work[DOCUMENT]
    doc = before.decode("utf-8")
    spans = _revisions.spans(doc)
    ordered = _cover(blocks, len(spans))
    if commented := _commented_spans(work, doc, spans, author):
        raise AnchorError(
            f"{len(commented)} span(s) already carry a comment by "
            f"{author!r} (comment(s) {', '.join(commented[:8])}): this was "
            f"annotated before. Remove those comments first "
            f"(docxkit.comments.remove) to replace them; nothing was "
            f"written")
    if not partial and (unreachable := _unreachable(work, doc, spans)):
        raise AnchorError(
            "no block can name " + "; ".join(unreachable) + ". Comment "
            "those with docxkit.comments.add_at, or pass partial=True to "
            "explain the spans only; nothing was written")
    credit = Credit(author, initials, date or _now())
    pre: list[tuple[int, int, int]] = []
    added: list[str] = []
    if reuse is not None:
        first, text = ordered.pop(0)
        com = _set_comment_text(work[COMMENTS].decode("utf-8"), reuse, text)
        work[COMMENTS] = _restamp(com, {reuse}, credit).encode("utf-8")
        pre.append((*spans[first], int(reuse)))
        added.append(reuse)
    scaffold = _Scaffold.read(work)
    added += _write(work, doc, [(*spans[i], text) for i, text in ordered],
                    scaffold, credit=credit, extra=pre)

    doc = work[DOCUMENT].decode("utf-8")
    for cid in added:
        open_tag, close_tag = _anchor(int(cid))
        doc = doc.replace(open_tag, "", 1).replace(close_tag, "", 1)
    if doc.encode("utf-8") != before:
        raise PackageError("annotating changed document.xml beyond its "
                           "comment anchors; nothing was written")
    parts.update(work)
    return added


def _now() -> str:
    """A comment's ``w:date`` for this moment."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commented_spans(parts: Parts, doc: str, spans: list[tuple[int, int]],
                     author: str) -> list[str]:
    """Ids of the comments by `author` whose range opens on a span."""
    starts = {start for start, _end in spans}
    mine = {m.group(2) for m in _COMMENT_HEAD_RE.finditer(
        parts.get(COMMENTS, b"").decode("utf-8"))
        if (who := re.search(r'\bw:author="([^"]*)"', m.group(0)))
        and who.group(1) == escape_attr(author)}
    found = []
    for cid in sorted(mine, key=int):
        if m := _anchor_re("commentRangeStart", cid).search(doc):
            # past this and any other range opening at the same place;
            # a pattern of `*` always matches
            more = _RANGE_STARTS_RE.match(doc, m.end())
            if m.end() + (len(more.group(0)) if more else 0) in starts:
                found.append(cid)
    return found


# a comment's open tag, empty or not; group 2 is its id
_COMMENT_HEAD_RE = re.compile(
    r'<w:comment\b([^>]*?)\bw:id="(\d+)"[^>]*?(/?)>')
_RANGE_STARTS_RE = re.compile(r"(?:<w:commentRangeStart\b[^>]*/>)*")


def _unreachable(parts: Parts, doc: str,
                 spans: list[tuple[int, int]]) -> list[str]:
    """What carries a revision no block can name, said in words."""
    found = [f"{sum(kinds.values())} revision(s) in {name} "
             f"({', '.join(sorted(kinds))})"
             for name, xml in text_parts(parts) if name != DOCUMENT
             if (kinds := _revisions.revision_kinds(xml))]
    starts = [start for start, _end in spans]
    holders = sorted([m.span() for m in PARA_RE.finditer(doc)]
                     + element_spans(doc, "tr"),
                     key=lambda span: span[1] - span[0])

    def in_span(at: int) -> bool:
        i = bisect_right(starts, at) - 1
        return i >= 0 and at < spans[i][1]

    def holds_span(lo: int, hi: int) -> bool:
        i = bisect_left(starts, lo)
        return i < len(starts) and starts[i] < hi

    bare: dict[tuple[int, int], set[str]] = {}
    for m in _revisions.REVISION_RE.finditer(doc):
        if in_span(m.start()):
            continue
        # the innermost paragraph, else row, that holds it
        box = next(((lo, hi) for lo, hi in holders
                    if lo <= m.start() < hi), (m.start(), m.start()))
        if not holds_span(*box):
            bare.setdefault(box, set()).update(
                _revisions.revision_kinds(m.group(0)))
    if bare:
        named = sorted(set().union(*bare.values()))
        found.append(f"{len(bare)} paragraph(s) or row(s) of document.xml "
                     f"changed with no span in them ({', '.join(named)})")
    return found


def _cover(blocks: Sequence[Block], n: int) -> list[tuple[int, str]]:
    """``(first span, comment)`` per block, in document order — once
    every span 0..n-1 is in exactly one block."""
    if n == 0:
        raise AnchorError("the document carries no revision to comment")
    owner: dict[int, int] = {}
    for b, (indices, _text) in enumerate(blocks):
        if not indices:
            raise AnchorError(f"block {b} names no span")
        for i in indices:
            if not 0 <= i < n:
                raise AnchorError(f"block {b} names span {i}; the document "
                                  f"has {n} (0..{n - 1})")
            if i in owner:
                raise AnchorError(f"span {i} is in blocks {owner[i]} and {b}")
            owner[i] = b
    if missing := sorted(set(range(n)) - set(owner)):
        raise AnchorError(f"{len(missing)} span(s) in no block, from "
                          f"{missing[:8]}: a change would go unexplained")
    return sorted((min(indices), text) for indices, text in blocks)


def has_scaffold(parts: Parts) -> bool:
    """Does `parts` carry a Word-made comment this module can clone?"""
    try:
        _Scaffold.read(parts)
    except (KeyError, ScaffoldMissing):
        return False
    return True


def _restamp(com: str, ids: set[str], credit: Credit) -> str:
    """`credit` on the comments `ids`, and on no other.

    Open tags only, an EMPTY comment's as it stands: nothing here pairs
    a tag with a close."""
    return _COMMENT_HEAD_RE.sub(
        lambda m: _stamp(m.group(0), credit) if m.group(2) in ids
        else m.group(0), com)


def _set_comment_text(com: str, cid: str, new_text: str) -> str:
    m = re.search(
        f'(<w:comment [^>]*w:id="{cid}"[^>]*(?<!/)>)(.*?)(</w:comment>)',
        com, re.DOTALL)
    if m is None:
        raise PackageError(
            f"comment {cid} is anchored in the document but has no "
            "definition in comments.xml")
    # set_run_text escapes; passing pre-escaped text would double-encode
    body = set_run_text(m.group(2), new_text)
    return com[:m.start()] + m.group(1) + body + m.group(3) + com[m.end():]


def reclassify(parts: Parts,
               classify: Callable[[RevisionContext], str | None],
               *, generic: str | None = GENERIC) -> tuple[int, list[str]]:
    """Re-derive the text of comments still carrying the generic marker.

    Repairs comments written without full context — one Word added on a
    math-only paragraph, or an older build. Idempotent.

    With ``generic=None`` there is no marker to look for — unmatched revisions
    were left uncommented rather than given a placeholder — so there is nothing
    to repair.
    """
    if generic is None:
        return 0, []
    doc = parts[DOCUMENT].decode("utf-8")
    com = parts[COMMENTS].decode("utf-8")
    stale = [m.group(2) for m in _COMMENT_RE.finditer(com)
             if generic in delta_text(m.group(3))]
    if not stale:
        return 0, []

    spans = table_spans(doc)
    done, still = 0, []
    for cid in stale:
        # anchor on the range START, not the reference run: for a revision
        # spanning a table row Word puts the reference past the table,
        # which would classify it by the following paragraph. Either
        # anchor in any spelling (`_anchor_re`).
        m = (_anchor_re("commentRangeStart", cid).search(doc)
             or _anchor_re("commentReference", cid).search(doc))
        if not m:
            still.append(cid)
            continue
        new = classify(_context(doc, m.start(), m.end(), spans))
        if not new:                     # '' is no answer either
            still.append(cid)
        else:
            com = _set_comment_text(com, cid, new)
            done += 1
    parts[COMMENTS] = com.encode("utf-8")
    return done, still


# ------------------------------------------------------------- removal ------
# A comment lives in SIX places, chained comment-id -> paraId -> durableId.
# Deleting it from comments.xml alone leaves anchors pointing at nothing,
# which Word reports as unreadable content. Worked out on the DSI paper
# when the author resolved five review comments.

_PARA_ID_RE = re.compile(r'<w:p [^>]*w14:paraId="([0-9A-Fa-f]+)"')


# `(?<!/)>`: `<w:r w:rsidR="00A1B2C3"/>` is an empty run, and it encloses
# nothing. Taken as the run around a bare mark after it, the cut ran from
# it to the next run's close; `_carries_more_than` refuses that cut on
# every well-formed body, so the guard is here for the walk to be right
# rather than rescued.
_RUN_START_RE = re.compile(r"<w:r(?:\s[^>]*)?(?<!/)>")


def _anchor_re(tag: str, cid: str) -> re.Pattern[str]:
    """Comment `cid`'s `tag` — a range start or end, or its reference —
    in any spelling.

    Every reader here matched the exact string `<w:{tag} w:id="{cid}"/>`,
    and other producers close the tag ` />` (30 of each anchor in 4 of
    2,954 corpus packages) or give a range `w:displacedByCustomXml` after
    the id. Not found, an anchor was not repaired, read or removed:
    `reclassify` left a generic comment generic, `threads` read no anchor
    text and sorted the comment last, and `remove` left a range and a
    reference to a comment that no longer exists (2026-09-17).
    """
    return re.compile(rf'<w:{tag}\b[^>]*\bw:id="{re.escape(cid)}"[^>]*/>')


def _drop_reference_run(doc: str, cid: str) -> str:
    """Remove the run carrying comment `cid`'s reference mark.

    Walks to the enclosing run boundaries rather than matching a run
    pattern around the mark: a regex written that way clipped the run
    short and left `Reference w:id="1"/></w:r>` behind in the document.
    """
    mark = _anchor_re("commentReference", cid)
    out, pos = [], 0
    while (hit := mark.search(doc, pos)) is not None:
        at, needle = hit.start(), hit.group(0)
        starts = [m.start() for m in _RUN_START_RE.finditer(doc, pos, at)]
        # The last run to START before the mark encloses it only if that
        # run is still OPEN there. A run that closed before the mark is a
        # NEIGHBOUR, and deleting from its start through the next
        # `</w:r>` takes the author's prose with it — measured on a
        # document whose reference mark sat bare in the paragraph: two
        # paragraphs of text gone, `remove` reporting success.
        inside = bool(starts) and doc.find("</w:r>", starts[-1], at) == -1
        if not inside:
            # no run to drop; drop the MARK, or the deleted comment
            # leaves a reference pointing at nothing and Word calls the
            # document unreadable
            out.append(doc[pos:at])
            pos = at + len(needle)
            continue
        close = doc.find("</w:r>", at)
        if close == -1:
            # Malformed: no run to end. Drop the MARK and carry on, for
            # the reason the branch above does — a reference to a comment
            # that no longer exists is what Word calls unreadable.
            out.append(doc[pos:at])
            pos = at + len(needle)
            continue
        run_end = close + len("</w:r>")
        run_xml = doc[starts[-1]:run_end]
        if _carries_more_than(run_xml, needle):
            # The mark shares its run with the author's own content —
            # Word writes it alone, another producer need not. Dropping
            # the run took the sentence with it and reported success,
            # which is the same loss as the neighbour case above.
            out.append(doc[pos:at])
            pos = at + len(needle)
            continue
        out.append(doc[pos:starts[-1]])
        pos = run_end
    out.append(doc[pos:])
    return "".join(out)


def _carries_more_than(run_xml: str, needle: str) -> bool:
    """Does this run hold anything besides its properties and `needle`?"""
    rpr = own_properties(run_xml, "rPr")
    body_from = rpr[1] if rpr else run_xml.index(">") + 1
    body = run_xml[body_from:run_xml.rfind("</w:r>")]
    return bool(body.replace(needle, "").strip())


# ----------------------------------------------------- threads / tasks ------
# An author round arrives as margin comments; working through them means
# reading each one next to what it anchors, and knowing which are already
# resolved. The pieces live in three parts, chained the same way removal
# has to walk them: the definition in comments.xml, the done flag and the
# reply link in commentsExtended (keyed by the LAST paragraph's paraId of
# the comment body, not by the comment id), and the anchor range in
# document.xml.


@dataclass(frozen=True)
class Comment:
    """One comment, with everything the checklist view needs."""

    cid: str
    author: str
    initials: str
    date: str
    text: str
    done: bool
    para_id: str             # last body paragraph's w14:paraId
    parent_cid: str | None   # the comment this one replies to
    anchor: str              # visible text of the anchored range, "" if a
    #                          point comment


@dataclass(frozen=True)
class Thread:
    """A root comment and its replies, in document order."""

    comment: Comment
    replies: tuple[Comment, ...]

    @property
    def done(self) -> bool:
        """Resolved means the ROOT is marked done — how Word's UI works;
        replies carry flags too but the thread's state is the root's."""
        return self.comment.done


_EXT_RE = re.compile(r"<w15:commentEx [^/>]*/>")
_W15_ATTR = {
    "para": re.compile(r'w15:paraId="([0-9A-Fa-f]+)"'),
    "parent": re.compile(r'w15:paraIdParent="([0-9A-Fa-f]+)"'),
    "done": re.compile(r'w15:done="([^"]*)"'),
}
#: ST_OnOff, which is what `w15:done` is: Word writes 1 and 0, and the
#: schema also allows true/false and on/off. Reading only `"(\d)"` made
#: a comment resolved by another producer read as OPEN — and made
#: `set_done` add a SECOND `w15:done` beside the one it could not see,
#: which no XML parser accepts ("Attribute w15:done redefined").
_ON_VALUES = frozenset({"1", "true", "on"})


def _comment_records(com: str) -> list[dict[str, str]]:
    out = []
    # An EMPTY comment is still a comment — it has an id, an author and a
    # thread — so the slash is captured, not guarded away (see
    # `_COMMENT_RE`), and its body reads as "".
    for m in re.finditer(r"<w:comment ([^>]*?)"
                         r"(?:(/)>|(?<!/)>(.*?)</w:comment>)", com,
                         re.DOTALL):
        def attr(name: str, head: str = m.group(1)) -> str:
            a = re.search(rf'w:{name}="([^"]*)"', head)
            return a.group(1) if a else ""
        body = m.group(3) or ""
        para_ids = _PARA_ID_RE.findall(body)
        out.append({
            "cid": attr("id"), "author": attr("author"),
            "initials": attr("initials"), "date": attr("date"),
            "text": delta_text(body).strip(),
            "para_id": para_ids[-1] if para_ids else "",
        })
    return out


def threads(parts: Parts) -> list[Thread]:
    """Every comment thread, roots in document order.

    The anchor text is read from the range between
    ``commentRangeStart/End`` in the document — a comment placed at a
    point has no range and reads back with an empty anchor. Roots are
    ordered by where their anchor sits in the document, which is the
    order a reader works through them, not the id order Word assigned.
    """
    com = parts.get(COMMENTS, b"").decode("utf-8")
    if not com:
        return []
    doc = parts[DOCUMENT].decode("utf-8")
    ext = parts.get("word/commentsExtended.xml", b"").decode("utf-8")

    flags: dict[str, tuple[bool, str | None]] = {}
    for m in _EXT_RE.finditer(ext):
        pid = _W15_ATTR["para"].search(m.group(0))
        if pid is None:
            continue
        parent = _W15_ATTR["parent"].search(m.group(0))
        done_m = _W15_ATTR["done"].search(m.group(0))
        done = done_m is not None and done_m.group(1).lower() in _ON_VALUES
        flags[pid.group(1)] = (done,
                               parent.group(1) if parent else None)

    records = _comment_records(com)
    by_para = {r["para_id"]: r["cid"] for r in records if r["para_id"]}

    comments: dict[str, Comment] = {}
    position: dict[str, int] = {}
    for r in records:
        done, parent_pid = flags.get(r["para_id"], (False, None))
        cid = r["cid"]
        anchor_m = _anchor_re("commentRangeStart", cid).search(doc)
        anchor = ""
        if anchor_m:
            shut = _anchor_re("commentRangeEnd", cid).search(doc,
                                                             anchor_m.end())
            if shut is not None:
                anchor = visible_text(doc[anchor_m.end():shut.start()]).strip()
            position[cid] = anchor_m.start()
        else:
            ref = _anchor_re("commentReference", cid).search(doc)
            position[cid] = ref.start() if ref else len(doc)
        comments[cid] = Comment(
            cid=cid, author=r["author"], initials=r["initials"],
            date=r["date"], text=r["text"], done=done,
            para_id=r["para_id"],
            parent_cid=by_para.get(parent_pid or ""), anchor=anchor)

    roots = [c for c in comments.values() if c.parent_cid is None]
    roots.sort(key=lambda c: position.get(c.cid, len(doc)))
    out = []
    for root in roots:
        replies = tuple(sorted(
            (c for c in comments.values() if c.parent_cid == root.cid),
            key=lambda c: (c.date, int(c.cid) if c.cid.isdigit() else 0)))
        out.append(Thread(comment=root, replies=replies))
    return out


def set_done(parts: Parts, ids: Iterable[str],
             *, done: bool = True) -> int:
    """Mark comments resolved (or reopen them) by comment id.

    Writes the ``w15:done`` flag in commentsExtended — the same bit
    Word's Resolve button sets — so the file opens in Word with the
    threads greyed out. Returns how many entries changed.
    """
    wanted = {str(i) for i in ids}
    if not wanted:
        return 0
    com = parts.get(COMMENTS, b"").decode("utf-8")
    if "word/commentsExtended.xml" not in parts:
        raise PackageError(
            "no commentsExtended.xml - the package carries no done flags "
            "to set (Word writes that part with the first comment)")
    ext = parts["word/commentsExtended.xml"].decode("utf-8")

    para_ids = {r["para_id"] for r in _comment_records(com)
                if r["cid"] in wanted and r["para_id"]}
    value = "1" if done else "0"
    changed = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal changed
        el = m.group(0)
        pid = _W15_ATTR["para"].search(el)
        if pid is None or pid.group(1) not in para_ids:
            return el
        if _W15_ATTR["done"].search(el):
            new = _W15_ATTR["done"].sub(f'w15:done="{value}"', el)
        else:
            new = el[:-2] + f' w15:done="{value}"/>'
        # Counted only when it MOVED. The number is printed back to the
        # author as how many comments were resolved, so re-running a
        # resolve pass on a finished round reported the whole round as
        # freshly resolved.
        changed += new != el
        return new

    parts["word/commentsExtended.xml"] = _EXT_RE.sub(sub, ext).encode("utf-8")
    return changed


def read_all(parts: Parts) -> list[tuple[str, str, str]]:
    """(id, author, text) for every comment, in part order.

    The compact view; :func:`threads` gives replies, done flags and
    anchors. Both read through the same parser, so they cannot disagree
    about what a comment's text is.
    """
    com = parts.get(COMMENTS, b"").decode("utf-8")
    return [(r["cid"], r["author"], r["text"])
            for r in _comment_records(com)]


def remove(parts: Parts, ids: Iterable[str]) -> int:
    """Delete comments by id from ALL the parts that reference them.

    Six places: the range start/end and the reference run in
    document.xml, the definition in comments.xml, and the extension
    entries in commentsExtended (by paraId), commentsIds (by paraId) and
    commentsExtensible (by durableId). Removing only the definition
    leaves dangling anchors, which Word calls unreadable content.

    Returns how many were removed.
    """
    wanted = {str(i) for i in ids}
    if not wanted:
        return 0
    com = parts.get(COMMENTS, b"").decode("utf-8")
    doc = parts[DOCUMENT].decode("utf-8")

    para_ids, durable_ids, removed = set(), set(), 0
    # The whole element, an EMPTY one included: removing it must cut
    # exactly it (see `_COMMENT_RE`).
    for m in list(re.finditer(r"<w:comment [^>]*w:id=\"(\d+)\"[^>]*?"
                              r"(?:(/)>|(?<!/)>.*?</w:comment>)", com,
                              re.DOTALL)):
        if m.group(1) not in wanted:
            continue
        removed += 1
        if pid := _PARA_ID_RE.search(m.group(0)):
            para_ids.add(pid.group(1))
        com = com.replace(m.group(0), "", 1)

    # The extension entries in EITHER attribute order. The schema fixes
    # none, and each of these patterns insisted on Word's — the paraId
    # first, the durableId after it — so an entry another producer wrote
    # was left behind for a comment that no longer exists, and a
    # commentsIds entry written durableId-first gave no durableId, which
    # left its commentsExtensible entry too (2026-09-17).
    ids_xml = parts.get("word/commentsIds.xml", b"").decode("utf-8")
    for para_id in para_ids:
        dm = re.search(rf'<w16cid:commentId\b'
                       rf'(?=[^>]*\bw16cid:paraId="{para_id}")'
                       r'[^>]*\bw16cid:durableId="([0-9A-Fa-f]+)"[^>]*/>',
                       ids_xml)
        if dm:
            durable_ids.add(dm.group(1))

    for cid in wanted:
        doc = _anchor_re("commentRangeStart", cid).sub("", doc)
        doc = _anchor_re("commentRangeEnd", cid).sub("", doc)
        doc = _drop_reference_run(doc, cid)
    parts[DOCUMENT] = doc.encode("utf-8")
    parts[COMMENTS] = com.encode("utf-8")

    # Spelled out per part rather than looped over a table of templates:
    # a pattern built by `.format` at run time is one the regex registry
    # cannot read, and these are exactly the ones that were order-bound.
    if "word/commentsExtended.xml" in parts:
        xml = parts["word/commentsExtended.xml"].decode("utf-8")
        for key in para_ids:
            xml = re.sub(rf'<w15:commentEx\b[^>]*\bw15:paraId="{key}"[^>]*/>',
                         "", xml)
        parts["word/commentsExtended.xml"] = xml.encode("utf-8")
    if "word/commentsIds.xml" in parts:
        xml = parts["word/commentsIds.xml"].decode("utf-8")
        for key in para_ids:
            xml = re.sub(
                rf'<w16cid:commentId\b[^>]*\bw16cid:paraId="{key}"[^>]*/>',
                "", xml)
        parts["word/commentsIds.xml"] = xml.encode("utf-8")
    if "word/commentsExtensible.xml" in parts:
        xml = parts["word/commentsExtensible.xml"].decode("utf-8")
        for key in durable_ids:
            xml = re.sub(rf'<w16cex:commentExtensible\b[^>]*'
                         rf'\bw16cex:durableId="{key}"[^>]*/>', "", xml)
        parts["word/commentsExtensible.xml"] = xml.encode("utf-8")
    return removed
