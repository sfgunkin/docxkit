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

import html
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from . import revisions as _revisions
from ._xml import (
    COMMENT_ID_RE,
    COMMENT_RANGE_END_RE,
    COMMENT_RANGE_START_RE,
    COMMENTS,
    DOCUMENT,
    MATH_ZONE_RE,
    P_TAG_RE,
    PARA_RE,
    RUN_RE,
    Parts,
    delta_text,
    element_spans,
    escape_attr,
    live_properties,
    normalize_glyphs,
    overlaps,
    own_properties,
    set_run_text,
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
    """One revision, the comment decided for it, and the table it sits in.

    `cid` is an existing comment the revision's balloon IS — Word's own,
    re-decided here (:func:`_annotate`'s `reuse`) — and None for a new
    one."""

    start: int
    end: int
    comment: str | None
    table: int | None
    cid: str | None = None


class _Decided(NamedTuple):
    """A balloon to write: its span, its text, and the comment it is if
    one is already defined."""

    start: int
    end: int
    text: str
    cid: str | None = None


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
             spans: list[tuple[int, int]],
             paras: _Paragraphs | None = None) -> RevisionContext:
    return RevisionContext(
        text=delta_text(doc[start:end]),
        para=paras.text_at(start) if paras else para_text_at(doc, start),
        window=re.sub("<[^>]+>", "", doc[max(0, start - _WINDOW_BACK):end]),
        table_index=table_index_at(spans, start),
        start=start, end=end)


class _Paragraphs:
    """:func:`docxkit.find.para_text_at`, for many offsets of one part.

    That function walks the part from its first paragraph for every
    offset, and the classified build asks once per span: 47 of the 52 s
    the comment pass took on an HPPA-sized redline (2,142 spans, 6.5 MB;
    review of 2026-10-24). The same paragraphs, found once — `PARA_RE`'s
    matches do not overlap, so the one holding an offset is the last to
    start at or before it — and each one's text read once."""

    def __init__(self, doc: str) -> None:
        self.matches = list(PARA_RE.finditer(doc))
        self.starts = [m.start() for m in self.matches]
        self.texts: dict[int, str] = {}

    def text_at(self, pos: int) -> str:
        i = bisect_right(self.starts, pos) - 1
        if i < 0 or pos >= self.matches[i].end():
            return ""
        if i not in self.texts:
            self.texts[i] = visible_text(self.matches[i].group(0))
        return self.texts[i]


#: Every comment this package writes carries a paraId in
#: ``[_PARA_ID_BASE, _PARA_ID_TOP)`` and keeps it: Word renumbers comment
#: IDS on save and leaves paraIds alone (HPPA's Word-saved copy,
#: 2026-10-10: 45 of 46 ids changed, every paraId kept). It is the one
#: mark that tells a balloon docxkit wrote from one a person wrote — the
#: author's name cannot, since an author annotating their own file
#: shares it with every query they typed themselves.
_PARA_ID_TOP = 0x5B000000


def _ours(para_id: str) -> bool:
    """Is `para_id` one this package mints?"""
    try:
        value = int(para_id, 16)
    except ValueError:
        return False
    return _PARA_ID_BASE <= value < _PARA_ID_TOP


class _Range(NamedTuple):
    """A comment's anchored range in ``document.xml``."""

    start: int       # just past its start marker
    end: int         # where its end marker begins
    cid: str


_RANGE_OPEN_RE = COMMENT_RANGE_START_RE
_RANGE_SHUT_RE = COMMENT_RANGE_END_RE


def _ranges(doc: str) -> list[_Range]:
    """Every anchored comment range, in any spelling of its markers."""
    shut: dict[str, list[int]] = {}
    for m in _RANGE_SHUT_RE.finditer(doc):
        shut.setdefault(m.group(1), []).append(m.start())
    out = []
    for m in _RANGE_OPEN_RE.finditer(doc):
        if later := [at for at in shut.get(m.group(1), ()) if at >= m.end()]:
            out.append(_Range(m.end(), later[0], m.group(1)))
    return out


def _about(ranges: Sequence[_Range], zones: list[tuple[int, int]],
           start: int, end: int, ids: set[str]) -> list[str]:
    """Which of the comments `ids` are anchored on the span `start`..`end`?

    Asked of the range the span's balloon is WRITTEN on — widened round
    the equation it touches, `_outside_math` — because that is where an
    earlier run put it. Asked of the raw span, a balloon round an
    equation was never found again: re-running `annotate` on a copy of
    LI7 added 949, then 133, then 133 balloons, and a second
    `annotate_blocks` on an all-maths proposal was not refused (review
    of 2026-10-24). `_ANCHOR_SLACK` either side is for the markers a
    range sits beside: a revision's own, another comment's.
    """
    return _Anchored(ranges, ids).on(zones, start, end)


class _Anchored:
    """The ranges of the comments `ids`, sorted by where they open, so
    :func:`_about` is a bisection per span and not a walk over every
    range: per span over every range was quadratic in the balloons a
    package already carries (2026-10-24)."""

    def __init__(self, ranges: Sequence[_Range], ids: set[str]) -> None:
        self.ranges = sorted((r for r in ranges if r.cid in ids),
                             key=lambda r: r.start)
        self.starts = [r.start for r in self.ranges]

    def on(self, zones: list[tuple[int, int]], start: int,
           end: int) -> list[str]:
        """:func:`_about` of one span."""
        lo, hi = _outside_math(zones, start, end)
        first = bisect_left(self.starts, lo - _ANCHOR_SLACK)
        last = bisect_right(self.starts, lo)
        return [r.cid for r in self.ranges[first:last]
                if hi <= r.end <= hi + _ANCHOR_SLACK]


def _ours_by(com: str, author: str | None) -> set[str]:
    """Ids of the comments this package wrote — by `author`, if given."""
    return {r["cid"] for r in _comment_records(com)
            if _ours(r["para_id"])
            and (author is None or html.unescape(r["author"]) == author)}


class _Minted:
    """paraIds and durableIds no part of the package already uses.

    They were ``BASE + comment id``, and the comment id is ``1 + max``
    of the ids Word left — which Word renumbers on save while keeping
    the paraIds. A later round's balloons took the paraIds and
    durableIds of earlier ones the author kept, and `threads`,
    `set_done` and `remove` — the remedy `annotate_blocks`' refusal
    names — then read or changed the OLD comment (review of 2026-10-24).
    """

    def __init__(self, parts: Parts) -> None:
        blob = "".join(b.decode("utf-8", "replace")
                       for name, b in parts.items() if name.endswith(".xml"))
        self.paras = {int(x, 16) for x in _PARA_ATTR_RE.findall(blob)}
        self.durables = {int(x, 16) for x in _DURABLE_ATTR_RE.findall(blob)}

    def take(self, cid: int) -> tuple[str, str]:
        """``(paraId, durableId)`` for comment `cid`, both fresh."""
        para, durable = _PARA_ID_BASE + cid, _DURABLE_ID_BASE + cid
        while para in self.paras:
            para += 1
        while durable in self.durables:
            durable += 1
        self.paras.add(para)
        self.durables.add(durable)
        return f"{para:08X}", f"{durable:08X}"


_PARA_ATTR_RE = re.compile(r'paraId="([0-9A-Fa-f]{1,8})"')
_DURABLE_ATTR_RE = re.compile(r'durableId="([0-9A-Fa-f]{1,8})"')
_STYLE_BLOCK_RE = re.compile(
    r'<w:style\b[^>]*?\bw:styleId="([^"]+)"[^>]*(?<!/)>(.*?)</w:style>',
    re.DOTALL)
_REFERENCE_NAME_RE = re.compile(
    r'<w:name\b[^>]*\bw:val="annotation reference"[^>]*/>', re.IGNORECASE)


def _reference_style(parts: Parts) -> str:
    """The style id of Word's "annotation reference" character style.

    Found by its NAME, which Word never localizes, and not assumed to be
    ``CommentReference``, which it does: 10 of 513 manuscripts with
    comments on this machine define it under another id (Russian Word's
    is ``af``), and a mark styled with an id the package does not define
    renders in the body's font, full size (review of 2026-10-24)."""
    styles = parts.get("word/styles.xml", b"").decode("utf-8", "replace")
    for m in _STYLE_BLOCK_RE.finditer(styles):
        if _REFERENCE_NAME_RE.search(m.group(2)):
            return m.group(1)
    return "CommentReference"


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


def _annotation_ref(style: str) -> str:
    """The run Word opens every comment paragraph with: the balloon's
    mark."""
    return (f'<w:r><w:rPr><w:rStyle w:val="{style}"/></w:rPr>'
            "<w:annotationRef/></w:r>")




def _plain(comment: str, style: str = "CommentReference") -> str:
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
    paragraph style, the annotation mark and one empty text run. The
    mark is the template's own run where it has one, and otherwise
    written in `style`; the style is the LIVE one, not the old one a
    ``w:pPrChange`` snapshot holds; and the text run keeps the live run
    properties of the template's first text — its language, its
    direction (review of 2026-10-24).
    """
    head = re.match(r"<w:comment\b[^>]*(?<!/)>", comment)
    para = PARA_RE.search(comment)
    assert head is not None              # _Scaffold.read matched one
    if para is None:
        return (f"{head.group(0)}<w:p>{_annotation_ref(style)}<w:r><w:t>"
                "</w:t></w:r></w:p></w:comment>")
    body = para.group(0)
    p_open = re.match(r"<w:p\b[^>]*(?<!/)>", body)
    assert p_open is not None            # PARA_RE opens on one
    p_style = ""
    if (own := own_properties(body, "pPr")) is not None:
        found = re.search(r'<w:pStyle\b[^>]*w:val="([^"]*)"',
                          live_properties(own[2]))
        if found:
            p_style = (f'<w:pPr><w:pStyle w:val="{found.group(1)}"/>'
                       "</w:pPr>")
    mark, text_props = _annotation_ref(style), ""
    for run in RUN_RE.finditer(body):
        xml = run.group(0)
        if "<w:annotationRef" in xml:
            if not re.search(r"<w:t\b", xml):
                mark = xml
        elif re.search(r"<w:t\b", xml):
            if (props := own_properties(xml, "rPr")) is not None:
                text_props = f"<w:rPr>{live_properties(props[2])}</w:rPr>"
            break
    return (f"{head.group(0)}{p_open.group(0)}{p_style}{mark}"
            f"<w:r>{text_props}<w:t></w:t></w:r></w:p></w:comment>")


def _anchor(cid: int, style: str = "CommentReference") -> tuple[str, str]:
    """(range start, range end + reference run) for comment `cid`."""
    start = f'<w:commentRangeStart w:id="{cid}"/>'
    end = (f'<w:commentRangeEnd w:id="{cid}"/>'
           f'<w:r><w:rPr><w:rStyle w:val="{style}"/></w:rPr>'
           f'<w:commentReference w:id="{cid}"/></w:r>')
    return start, end


def _plan(doc: str, classify: Callable[[RevisionContext], str | None],
          spans: list[tuple[int, int]], *, done: set[str],
          reuse: dict[int, str]) -> list[_Planned]:
    """Every revision that still needs a comment, with its verdict.

    A revision one of the comments `done` is anchored on (:func:`_about`)
    has its balloon already. Any other comment there is a person's —
    a referee's query that happens to bracket the change — and the
    change still gets a reason of its own; skipping it on any nearby
    range left it bare while the build counted it (review of
    2026-10-24). `reuse` maps a span's index to the comment its balloon
    already is.

    ``''`` from the classifier is no answer, the same as None: kept
    apart, the two coalesced as different texts and a table read as two
    unclassified balloons.
    """
    zones, paras = _math_zones(doc), _Paragraphs(doc)
    anchored = _Anchored(_ranges(doc), done)
    out = []
    for i, (s, e) in enumerate(_revisions.spans(doc)):
        if i not in reuse and anchored.on(zones, s, e):
            continue
        out.append(_Planned(s, e, classify(_context(doc, s, e, spans, paras))
                            or None, table_index_at(spans, s), reuse.get(i)))
    return out


def _table_balloons(com: str, doc: str, tspans: list[tuple[int, int]],
                    done: set[str], generic: str | None,
                    ) -> set[tuple[int, str | None]]:
    """``(table, reason)`` of every balloon in `done` anchored in a table,
    the reason None where it is the generic one — the key
    :func:`_coalesce_tables` coalesces on.

    A re-run skips the one cell of each table that carries the table's
    balloon, so without these the NEXT cell was the first of its kind
    and got one: `annotate` twice on LI7 added 10 balloons, then 4 more,
    one table at a time (2026-10-24)."""
    texts = {m.group(2): " ".join(visible_text(m.group(3)).split())
             for m in _COMMENT_RE.finditer(com) if m.group(2) in done}
    out: set[tuple[int, str | None]] = set()
    for r in _ranges(doc):
        table = table_index_at(tspans, r.start)
        if r.cid in texts and table is not None:
            text = texts[r.cid]
            out.add((table, None if text in (generic, GENERIC) else text))
    return out


def _coalesce_tables(planned: list[_Planned],
                     seen: set[tuple[int, str | None]] | None = None,
                     ) -> list[_Planned]:
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

    `seen` holds the ``(table, reason)`` balloons already written
    (:func:`_table_balloons`).
    """
    seen = set(seen or ())
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


def _coalesce_zones(doc: str, planned: list[_Planned]) -> list[_Planned]:
    """One balloon per equation per reason.

    Every span touching an equation is anchored round the WHOLE equation
    (`_outside_math`), so the spans of one equation shared one range and
    each wrote a balloon on it: 20 of LI7's equations carried stacks of
    3 to 25 identical balloons (review of 2026-10-24). Spans with
    different reasons keep one each — they say different things."""
    zones = _math_zones(doc)
    seen: set[tuple[int, int, str | None]] = set()
    kept = []
    for entry in planned:
        lo, hi = _outside_math(zones, entry.start, entry.end)
        if not any(overlaps(zone, (entry.start, entry.end))
                   for zone in zones):
            kept.append(entry)              # touches no equation
            continue
        if (lo, hi, entry.comment) not in seen:
            seen.add((lo, hi, entry.comment))
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
    #: the "annotation reference" style's id (:func:`_reference_style`)
    style: str = "CommentReference"

    @classmethod
    def read(cls, parts: Parts) -> _Scaffold:
        blob = parts.get(COMMENTS)
        if blob is None:
            # named, not a KeyError: `add_at`, and the advice that points
            # at it, met a comment-less package that way (2026-10-24)
            raise ScaffoldMissing(
                "the package has no comments part - Word must create at "
                "least one comment before the XML pass can clone it")
        com = blob.decode("utf-8")
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
        style = _reference_style(parts)
        # `default`: `\d+` reads no id from a comment `w:id="-1"`, and
        # `max` of nothing raised ValueError out of `has_scaffold`, which
        # promises a bool (review of 2026-10-24)
        ids = [int(i) for i in COMMENT_ID_RE.findall(com)]
        return cls(
            comments_xml=com,
            template=_plain(tm.group(0), style),
            next_id=1 + max(ids, default=-1),
            date_utc=utc.group(1) if utc else None,
            style=style)


def _decide(planned: Sequence[_Planned], generic: str | None,
            ) -> tuple[list[_Decided], set[str]]:
    """Settle each revision's final text: ``(balloons, comments to drop)``.

    Resolving the fallback once here rather than at each insertion is what
    lets `generic=None` mean "leave it uncommented" without the write step
    having to know about it. An EMPTY answer is no answer, and an empty
    `generic` is None: `''` became "Revision (unclassified)" under
    `generic=None`, the one outcome the flag exists to prevent, while
    the build counted it classified. A revision left bare whose balloon
    was an existing comment drops that comment.
    """
    keep, drop = [], set()
    for p in planned:
        if text := p.comment or generic:
            keep.append(_Decided(p.start, p.end, text, p.cid))
        elif p.cid is not None:
            drop.add(p.cid)
    return keep, drop


class Credit(NamedTuple):
    """Who a comment this package writes is from, and when."""

    author: str
    initials: str
    date: str        # w:date, Word's way: local time labelled Z (`_now`)


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
        if overlaps((lo, hi), (start, end)):
            start, end = min(start, lo), max(end, hi)
    return start, end


def _place(doc: str, anchors: Sequence[tuple[int, int, int]],
           style: str = "CommentReference") -> str:
    """`doc` with each ``(start, end, cid)`` comment range written in.

    In ONE ascending pass over every insertion point rather than back
    to front: two ranges widened to the same equation share their
    offsets, and a back-to-front splice put the second one's end inside
    the first one's range start.
    """
    return _placed(doc, anchors, style)[0]


def _placed(doc: str, anchors: Sequence[tuple[int, int, int]],
            style: str) -> tuple[str, list[tuple[int, str]]]:
    """:func:`_place`, and where in the result each tag was written."""
    zones = _math_zones(doc)
    events: list[tuple[int, int, int, str]] = []
    for n, (at_start, at_end, cid) in enumerate(anchors):
        start, end = _outside_math(zones, at_start, at_end)
        open_tag, close_tag = _anchor(cid, style)
        # at one offset: a range that ENDS there closes before one opens
        events += [(start, 1, n, open_tag), (end, 0, -n, close_tag)]
    out, at, size = [], 0, 0
    written: list[tuple[int, str]] = []
    for pos, _kind, _n, tag in sorted(events):
        out += [doc[at:pos], tag]
        size += pos - at
        written.append((size, tag))
        size += len(tag)
        at = pos
    return "".join(out) + doc[at:], written


_SIDE_PARTS = (("word/commentsExtended.xml", "</w15:commentsEx>"),
               ("word/commentsIds.xml", "</w16cid:commentsIds>"),
               ("word/commentsExtensible.xml",
                "</w16cex:commentsExtensible>"))


def _write(parts: Parts, doc: str, decided: Sequence[_Decided],
           scaffold: _Scaffold, *, credit: Credit | None = None,
           ) -> list[str]:
    return _write_checked(parts, doc, decided, scaffold, credit=credit,
                          original=parts[DOCUMENT].decode("utf-8"))


def _write_checked(parts: Parts, doc: str, decided: Sequence[_Decided],
                   scaffold: _Scaffold, *, credit: Credit | None,
                   original: str) -> list[str]:
    """THE writer: every balloon this module puts in a package is
    written here, by `annotate`, `annotate_blocks` and `add_at` alike.
    Returns the ids written, in `decided`'s order.

    The two comment paths each held guards the other lacked, and their
    fixes kept adding guards to one path or the other (reviews of
    2026-10-14 and 2026-10-24). So every guard is here, once:

    * the range goes round the equation a span touches (`_place`), and
      the re-run questions are asked of that range (:func:`_about`);
    * paraIds and durableIds are fresh, and in the range `_ours` reads
      (:class:`_Minted`) — an existing comment that becomes a balloon
      is given one too, so it is found again as one;
    * `credit` is on every new comment and every reused one — author,
      initials, ``w:date``, and the ``dateUtc`` beside it, which a
      restamp left as it was. Without it a clone is credited to whoever
      wrote the comment it was cloned from;
    * ``document.xml`` minus the anchors written must be the part as it
      stood when `_write` was CALLED — `original`, read from `parts` by
      :func:`_write` itself, not the `doc` it was handed — byte for byte,
      or nothing is written: the tracked views and the revision counts
      are then unchanged by construction. Checked against `doc`, a
      step that changed the text before handing it over passed, and
      only an unrelated lint finding stopped it (2026-10-24).
    """
    minted = _Minted(parts)
    com = scaffold.comments_xml
    side = {name: parts[name].decode("utf-8")
            for name, _close in _SIDE_PARTS if name in parts}
    adds: dict[str, list[str]] = {name: [] for name, _close in _SIDE_PARTS}
    elements, anchors, written = [], [], []
    date_utc = _utc_of(credit.date) if credit else scaffold.date_utc
    next_id = scaffold.next_id
    for d in decided:
        if d.cid is not None:
            cid = int(d.cid)
            com = _set_comment_text(com, d.cid, d.text)
            com = _remint(com, side, d.cid, minted)
            if credit:
                com = _restamp(com, {d.cid}, credit)
                _set_date_utc(com, side, d.cid, _utc_of(credit.date))
        else:
            cid, next_id = next_id, next_id + 1
            para_id, durable = minted.take(cid)
            element = _clone_comment(scaffold.template, cid, para_id, d.text)
            if credit:
                element = _stamp(element, credit)
            elements.append(element)
            adds["word/commentsExtended.xml"].append(
                f'<w15:commentEx w15:paraId="{para_id}" w15:done="0"/>')
            adds["word/commentsIds.xml"].append(
                f'<w16cid:commentId w16cid:paraId="{para_id}" '
                f'w16cid:durableId="{durable}"/>')
            if date_utc:
                adds["word/commentsExtensible.xml"].append(
                    '<w16cex:commentExtensible w16cex:durableId='
                    f'"{durable}" w16cex:dateUtc="{date_utc}"/>')
        anchors.append((d.start, d.end, cid))
        written.append(str(cid))
    placed, placed_at = _placed(doc, anchors, scaffold.style)
    if _without_anchors(placed, placed_at) != original:
        raise PackageError("annotating changed document.xml beyond its "
                           "comment anchors; nothing was written")
    parts[DOCUMENT] = placed.encode("utf-8")
    parts[COMMENTS] = _append_before_close(
        com, "</w:comments>", "".join(elements)).encode("utf-8")
    # The three side parts must stay in step with comments.xml or Word
    # reports unreadable content.
    for name, close in _SIDE_PARTS:
        if name in side:
            parts[name] = _append_before_close(
                side[name], close, "".join(adds[name])).encode("utf-8")
    return written


def _without_anchors(doc: str,
                     placed_at: Sequence[tuple[int, str]]) -> str:
    """`doc` less the tags `_place` says it wrote at those offsets, or
    ``""`` when one is not there — in one pass: a `str.replace` per
    anchor was 7.7 s of an HPPA-sized build (2026-10-24)."""
    out, at = [], 0
    for pos, tag in placed_at:
        if doc[pos:pos + len(tag)] != tag:
            return ""                       # not where it was put: refuse
        out.append(doc[at:pos])
        at = pos + len(tag)
    out.append(doc[at:])
    return "".join(out)


def _remint(com: str, side: dict[str, str], cid: str,
            minted: _Minted) -> str:
    """Comment `cid` given one of this package's paraIds, everywhere it
    is keyed by its old one; `side` is changed in place."""
    m = re.search(rf'<w:comment\b[^>]*\bw:id="{cid}"[^>]*(?<!/)>.*?'
                  r"</w:comment>", com, re.DOTALL)
    if m is None or not (old := _PARA_ID_RE.findall(m.group(0))):
        return com
    if all(_ours(pid) for pid in old):
        return com
    new, _durable = minted.take(int(cid))
    # the LAST paragraph's: the one the side parts key the comment by
    last = old[-1]
    element = m.group(0).replace(f'paraId="{last}"', f'paraId="{new}"')
    for name in ("word/commentsExtended.xml", "word/commentsIds.xml"):
        if name in side:
            side[name] = side[name].replace(f'paraId="{last}"',
                                            f'paraId="{new}"')
    return com[:m.start()] + element + com[m.end():]


def _set_date_utc(com: str, side: dict[str, str], cid: str,
                  date: str) -> None:
    """Comment `cid`'s ``dateUtc`` set to `date`, beside its ``w:date``."""
    m = re.search(rf'<w:comment\b[^>]*\bw:id="{cid}"[^>]*(?<!/)>.*?'
                  r"</w:comment>", com, re.DOTALL)
    pids = _PARA_ID_RE.findall(m.group(0)) if m else []
    ids = side.get("word/commentsIds.xml", "")
    if not pids or "word/commentsExtensible.xml" not in side:
        return
    dm = re.search(rf'<w16cid:commentId\b(?=[^>]*\bw16cid:paraId='
                   rf'"{pids[-1]}")[^>]*\bw16cid:durableId="([0-9A-Fa-f]+)"',
                   ids)
    if dm is None:
        return
    durable = f'w16cex:durableId="{dm.group(1)}"'

    def dated(tag: re.Match[str]) -> str:
        if durable not in tag.group(0):
            return tag.group(0)
        return _DATE_UTC_RE.sub(_constant(f'w16cex:dateUtc="{date}"'),
                                tag.group(0))

    side["word/commentsExtensible.xml"] = _EXTENSIBLE_RE.sub(
        dated, side["word/commentsExtensible.xml"])


_EXTENSIBLE_RE = re.compile(r"<w16cex:commentExtensible\b[^>]*/>")
_DATE_UTC_RE = re.compile(r'\bw16cex:dateUtc="[^"]*"')


def _stamp(element: str, credit: Credit) -> str:
    """A comment element's open tag credited to `credit`, whatever it
    carried; an attribute it lacks is added. Either quote: an attribute
    another producer wrote in single quotes was not found and written a
    second time, which no parser accepts (review of 2026-10-24)."""
    head = re.match(r"<w:comment\b[^>]*?(/?)>", element)
    assert head is not None
    tag = head.group(0)
    for name, value in (("w:author", credit.author),
                        ("w:initials", credit.initials),
                        ("w:date", credit.date)):
        attr = f'{name}="{escape_attr(value)}"'
        # a function, not a template: a backslash in a name is not a group
        tag, found = re.subn(rf'\b{name}=(?:"[^"]*"|\'[^\']*\')',
                             _constant(attr), tag)
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

    Idempotent: a revision already carrying a balloon this package wrote
    — by `credit`'s author, when given — or one of the markers
    (`GENERIC`, `SCAFFOLD`, `generic`) is skipped, asked of the range the
    balloon is written on (:func:`_about`). A comment a PERSON wrote
    near a revision does not count: the revision still gets its reason.
    """
    return _annotate(parts, classify, generic=generic, tables=tables,
                     credit=credit, reuse={})


def _annotate(parts: Parts,
              classify: Callable[[RevisionContext], str | None], *,
              generic: str | None, tables: str, credit: Credit | None,
              reuse: dict[int, str]) -> tuple[int, int]:
    """:func:`annotate`, with `reuse`: span index -> an existing comment
    whose anchors are already gone, which becomes that span's balloon
    with the text decided here — or is removed, when nothing is (the
    classified build's Word-made comments, `tracked._comment_pass`)."""
    if tables not in (COALESCE, ALL):
        raise ValueError(f"tables must be {COALESCE!r} or {ALL!r}, "
                         f"not {tables!r}")
    generic = generic or None
    doc = parts[DOCUMENT].decode("utf-8")
    scaffold = _Scaffold.read(parts)
    com = scaffold.comments_xml
    markers = {SCAFFOLD, GENERIC, *([generic] if generic else [])}
    done = _ours_by(com, credit.author if credit else None) | {
        m.group(2) for m in _COMMENT_RE.finditer(com)
        if " ".join(visible_text(m.group(3)).split()) in markers}

    tspans = table_spans(doc)
    planned = _plan(doc, classify, tspans, done=done, reuse=reuse)
    kept = _coalesce_zones(doc, planned)
    if tables == COALESCE:
        kept = _coalesce_tables(kept, _table_balloons(com, doc, tspans,
                                                      done, generic))
    dropped = {p.cid for p in planned if p not in kept and p.cid}
    planned = kept
    unclassified = sum(1 for p in planned if not p.comment)
    decided, bare = _decide(planned, generic)

    _write(parts, doc, decided, scaffold, credit=credit)
    if gone := (bare | dropped) - {d.cid for d in decided}:
        remove(parts, {cid for cid in gone if cid is not None})
    # ADDED: a comment Word made and this pass re-decided was there before
    return sum(1 for d in decided if d.cid is None), unclassified


def add_at(parts: Parts, anchor: str, comment: str, *,
           normalize: bool = True, credit: Credit | None = None) -> int:
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

    ``credit`` is who the balloon is from (see :func:`_write`). Without
    it the balloon is credited to whoever wrote the comment it is cloned
    from — a referee's, when theirs comes first in the package.
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
    (cid,) = _write(parts, doc, [_Decided(start, end, comment)], scaffold,
                    credit=credit)
    return int(cid)


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
    rather than by searching near the text, because a comment Word made
    has a range spanning a whole group, which no nearness test reads as
    one span's.

    `reuse` names a comment already in ``comments.xml`` with no anchor,
    the one Word made on a seeded copy; it becomes the first block's
    balloon, so nothing is left anchored nowhere. New comments are
    credited to `author` and `initials`, never to whoever wrote the
    comment that was cloned, which can be a referee's.

    Refuses, leaving `parts` as it was, unless ``document.xml`` minus
    the new anchors is byte-identical to before; the tracked views and
    the revision counts are then unchanged by construction.

    Refuses as well, before anything is anchored (review of 2026-10-14):

    * when a span already carries a balloon this package wrote for
      `author` — a second run would put the stale and the corrected
      reason side by side on every change and report a clean count;
    * when the package holds revisions NO block can name
      (:func:`_unreachable`): property-only changes, moves and paragraph
      marks in a paragraph (or a table row) with no span, and every
      revision outside ``document.xml``. HPPA's own script covered such
      a change with :func:`add_at`, and this function had promised full
      coverage over 58 ``rPrChange`` and 91 ``pPrChange`` it could not
      see. ``partial=True`` accepts that the balloons explain the spans
      only.

    `date` is the new comments' ``w:date``, written Word's way — local
    time labelled Z (:func:`_now`) — now when omitted; their ``dateUtc``
    is its true UTC.
    """
    doc = parts[DOCUMENT].decode("utf-8")
    spans = _revisions.spans(doc)
    ordered = _check_blocks(parts, blocks, author=author, partial=partial)
    credit = Credit(author, initials, date or _now())
    decided = [_Decided(*spans[i], text,
                        reuse if reuse is not None and n == 0 else None)
               for n, (i, text) in enumerate(ordered)]
    return _write(parts, doc, decided, _Scaffold.read(parts), credit=credit)


def _check_blocks(parts: Parts, blocks: Iterable[Block], *, author: str,
                  partial: bool = False) -> list[tuple[int, str]]:
    """Every refusal :func:`annotate_blocks` makes, without writing:
    ``(first span, comment)`` per block, in document order.

    Apart, so a caller can ask BEFORE it pays for anything — the Word
    seed `tracked.annotate_in_place` starts for a package with no
    comment to clone was paid for, and then the coverage refusal came
    (review of 2026-10-24)."""
    blocks = [(list(indices), text) for indices, text in blocks]
    doc = parts[DOCUMENT].decode("utf-8")
    spans = _revisions.spans(doc)
    ordered = _cover(blocks, len(spans))
    if commented := _commented_spans(parts, doc, spans, author):
        raise AnchorError(
            f"{len(commented)} span(s) already carry a comment by "
            f"{author!r} (comment(s) {', '.join(commented[:8])}): this was "
            f"annotated before. Remove those comments first "
            f"(docxkit.comments.remove) to replace them; nothing was "
            f"written")
    if not partial and (unreached := _unreachable(parts)):
        raise AnchorError(
            "no block can name " + "; ".join(unreached) + ". No balloon "
            "anchored on a revision span can explain those; pass "
            "partial=True to explain the spans only (and, if a change "
            "needs a reason of its own, add it afterwards with "
            "docxkit.comments.add_at, which anchors on text); nothing was "
            "written")
    return ordered


def _now() -> str:
    """A comment's ``w:date`` for this moment, as WORD writes one: the
    local wall clock, labelled ``Z``.

    Measured 2026-10-24 over the papers on this machine (UTC+5): every
    Word-made comment beside a ``w16cex:dateUtc`` reads five hours
    ahead of it — ``w:date`` local, ``dateUtc`` true UTC. Written as
    true UTC, a docxkit balloon sorted and showed five hours before the
    author's own (review of 2026-10-24). :func:`_utc_of` gives the
    ``dateUtc`` beside it."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_of(word_date: str) -> str:
    """The true-UTC ``dateUtc`` for a ``w:date`` written Word's way
    (:func:`_now`); `word_date` itself when it does not parse."""
    try:
        local = datetime.strptime(word_date, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return word_date
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commented_spans(parts: Parts, doc: str, spans: list[tuple[int, int]],
                     author: str) -> list[str]:
    """Ids of the balloons this package wrote for `author` that are
    anchored on a span (:func:`_about`).

    The author's NAME alone was the test, and an author annotating their
    own file has typed comments under it: one on an inserted phrase was
    "annotated before" and refused (review of 2026-10-24). Compared
    unescaped, so ``O&apos;Brien`` is O'Brien however it is spelled."""
    mine = _ours_by(parts.get(COMMENTS, b"").decode("utf-8"), author)
    if not mine:
        return []
    zones, anchored = _math_zones(doc), _Anchored(_ranges(doc), mine)
    found: set[str] = set()
    for start, end in spans:
        found.update(anchored.on(zones, start, end))
    return sorted(found, key=int)


# a comment's open tag, empty or not; group 2 is its id
_COMMENT_HEAD_RE = re.compile(
    r'<w:comment\b([^>]*?)\bw:id="(\d+)"[^>]*?(/?)>')
_P_TAG_RE = P_TAG_RE
#: The parts a revision can sit in that no span of ``document.xml``
#: reaches: the notes `text_parts` names, and headers, footers and the
#: comments themselves, which it does not.
_OTHER_STORY_RE = re.compile(
    r"word/(?:footnotes|endnotes|comments|header\d*|footer\d*)\.xml")


def _paragraph_spans(doc: str) -> list[tuple[int, int]]:
    """Every ``w:p``'s ``(start, end)``, nested ones included, depth-
    counted: a lazy pairing ends a paragraph holding a text box at the
    box's first inner ``</w:p>``."""
    out: list[tuple[int, int]] = []
    stack: list[int] = []
    for m in _P_TAG_RE.finditer(doc):
        if m.group(0) == "</w:p>":
            if stack:
                out.append((stack.pop(), m.end()))
        elif m.group(1) != "/":
            stack.append(m.start())
    return out


def _unreachable(parts: Parts) -> list[str]:
    """What carries a revision no span of ``document.xml`` reaches, in
    words: other stories, and paragraphs or rows changed with no span.

    Every story is read, as the docstring had promised and the code had
    not — a tracked change in a header passed as covered — and a
    paragraph is measured whole: one holding a text box was cut at the
    box's first paragraph, so a span after the box was "no span" and a
    valid block table was refused (review of 2026-10-24)."""
    doc = parts[DOCUMENT].decode("utf-8")
    spans = _revisions.spans(doc)
    found = [f"{sum(kinds.values())} revision(s) in {name} "
             f"({', '.join(sorted(kinds))})"
             for name in sorted(parts) if _OTHER_STORY_RE.fullmatch(name)
             if (kinds := _revisions.revision_kinds(
                 parts[name].decode("utf-8", "replace")))]
    starts = [start for start, _end in spans]
    tiers = []
    for boxes in (sorted(_paragraph_spans(doc)),
                  sorted(element_spans(doc, "tr"))):
        reach, furthest = [], -1
        for _lo, hi in boxes:
            furthest = max(furthest, hi)
            reach.append(furthest)
        tiers.append((boxes, reach))

    def holder(at: int) -> tuple[int, int]:
        """The innermost paragraph holding `at`, else its row: the
        LAST-opening of those open at `at`, found by bisection rather
        than by a walk over every paragraph (2026-10-24). `reach` stops
        the walk back where nothing earlier extends to `at`."""
        for boxes, reach in tiers:
            i = bisect_right(boxes, (at, len(doc))) - 1
            while i >= 0 and reach[i] > at:
                lo, hi = boxes[i]
                if lo <= at < hi:
                    return lo, hi
                i -= 1
        return at, at

    def in_a_span(at: int) -> bool:
        i = bisect_right(starts, at) - 1
        return i >= 0 and at < spans[i][1]

    def holds_span(lo: int, hi: int) -> bool:
        i = bisect_left(starts, lo)
        return i < len(starts) and starts[i] < hi

    bare: dict[tuple[int, int], set[str]] = {}
    for m in _revisions.REVISION_RE.finditer(doc):
        if in_a_span(m.start()):
            continue
        box = holder(m.start())
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
    every span 0..n-1 is in exactly one block, and every block says
    something: a reason of no words was written as an empty balloon
    and counted (review of 2026-10-24)."""
    if n == 0:
        raise AnchorError("the document carries no revision to comment")
    owner: dict[int, int] = {}
    for b, (indices, text) in enumerate(blocks):
        if not indices:
            raise AnchorError(f"block {b} names no span")
        if not text.strip():
            raise AnchorError(f"block {b} gives no reason")
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
    except ScaffoldMissing:
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
    to repair; nor with ``''``.

    A comment is the marker when its WHOLE text is — never when the
    marker appears in it: as a substring, ``''`` matched every comment
    in the package and a referee's query that quoted "Revision
    (unclassified)" was rewritten with the rest (review of 2026-10-24).
    The classifier is shown the comment's RANGE — what it explains —
    and not the empty marker tag, which gave it no text and a window
    ending before the revision.
    """
    if not generic:
        return 0, []
    doc = parts[DOCUMENT].decode("utf-8")
    com = parts[COMMENTS].decode("utf-8")
    marker = " ".join(generic.split())
    stale = [m.group(2) for m in _COMMENT_RE.finditer(com)
             if " ".join(visible_text(m.group(3)).split()) == marker]
    if not stale:
        return 0, []

    spans = table_spans(doc)
    ranges = {r.cid: r for r in _ranges(doc)}
    done, still = 0, []
    for cid in stale:
        # the range, not the reference run: for a revision spanning a
        # table row Word puts the reference past the table, which would
        # classify it by the following paragraph. Either anchor in any
        # spelling (`_anchor_re`).
        if (r := ranges.get(cid)) is not None:
            start, end = r.start, r.end
        elif m := _anchor_re("commentReference", cid).search(doc):
            start, end = m.start(), m.end()
        else:
            still.append(cid)
            continue
        new = classify(_context(doc, start, end, spans))
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
