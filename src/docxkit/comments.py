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
from collections.abc import Callable
from dataclasses import dataclass

from . import revisions as _revisions
from ._xml import delta_text, set_run_text
from .errors import ScaffoldMissing
from .find import para_text_at, table_index_at, table_spans

__all__ = [
    "GENERIC",
    "RevisionContext",
    "annotate",
    "reclassify",
]

GENERIC = "Revision (unclassified)"

_COMMENT_RE = re.compile(
    r'(<w:comment [^>]*w:id="(\d+)"[^>]*>)(.*?)(</w:comment>)', re.DOTALL)
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
        """Everything searchable, for simple substring rules."""
        return f"{self.para} {self.window} {self.text}"


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
    namespace prefixes exactly as Word wrote them.
    """
    x = re.sub(r'w:id="\d+"', f'w:id="{cid}"', template, count=1)
    x = re.sub(r'w14:paraId="[0-9A-Fa-f]{8}"', f'w14:paraId="{para_id}"',
               x, count=1)
    return set_run_text(x, text)


def _append_before_close(xml: str, close_tag: str, addition: str) -> str:
    i = xml.rindex(close_tag)
    return xml[:i] + addition + xml[i:]


def _anchor(cid: int) -> tuple[str, str]:
    """(range start, range end + reference run) for comment `cid`."""
    start = f'<w:commentRangeStart w:id="{cid}"/>'
    end = (f'<w:commentRangeEnd w:id="{cid}"/>'
           '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
           f'<w:commentReference w:id="{cid}"/></w:r>')
    return start, end


def annotate(parts: dict[str, bytes],
             classify: Callable[[RevisionContext], str | None],
             *, generic: str = GENERIC) -> tuple[int, int]:
    """Comment every run-level revision in ``document.xml``.

    The package must already carry Word's comment scaffold — at least one
    comment Word itself created — so the parts, styles and relationships
    are Word's own rather than hand-rolled. :func:`docxkit.tracked.build`
    arranges that.

    Returns (comments added, revisions no rule matched). Idempotent:
    revisions that already carry an anchor are skipped.
    """
    doc = parts["word/document.xml"].decode("utf-8")
    com = parts["word/comments.xml"].decode("utf-8")
    tm = re.search(r"<w:comment .*?</w:comment>", com, re.DOTALL)
    if not tm:
        raise ScaffoldMissing(
            "no comment scaffold - Word must create at least one comment "
            "before the XML pass can clone it")
    template = tm.group(0)
    utc = re.search(r'w16cex:dateUtc="([^"]+)"',
                    parts.get("word/commentsExtensible.xml", b"").decode(
                        "utf-8") or "")
    next_id = 1 + max(int(i) for i in
                      re.findall(r'<w:comment w:id="(\d+)"', com))
    spans = table_spans(doc)

    planned = [(s, e, classify(_context(doc, s, e, spans)))
               for s, e in _revisions.spans(doc)
               if not _already_anchored(doc, s, e)]
    unclassified = sum(1 for *_, c in planned if c is None)

    elements, exts, ids, exls = [], [], [], []
    # insert back-to-front so the earlier offsets stay valid
    for i, (start, end, comment) in reversed(list(enumerate(planned))):
        cid = next_id + i
        para_id = f"{_PARA_ID_BASE + cid:08X}"
        durable = f"{_DURABLE_ID_BASE + cid:08X}"
        open_tag, close_tag = _anchor(cid)
        doc = doc[:start] + open_tag + doc[start:end] + close_tag + doc[end:]
        elements.append(_clone_comment(template, cid, para_id,
                                       comment or generic))
        exts.append(f'<w15:commentEx w15:paraId="{para_id}" w15:done="0"/>')
        ids.append(f'<w16cid:commentId w16cid:paraId="{para_id}" '
                   f'w16cid:durableId="{durable}"/>')
        if utc:
            exls.append('<w16cex:commentExtensible w16cex:durableId='
                        f'"{durable}" w16cex:dateUtc="{utc.group(1)}"/>')

    parts["word/document.xml"] = doc.encode("utf-8")
    parts["word/comments.xml"] = _append_before_close(
        com, "</w:comments>", "".join(elements)).encode("utf-8")
    for name, close, add in (
            ("word/commentsExtended.xml", "</w15:commentsEx>", exts),
            ("word/commentsIds.xml", "</w16cid:commentsIds>", ids),
            ("word/commentsExtensible.xml", "</w16cex:commentsExtensible>",
             exls)):
        if name in parts and add:
            parts[name] = _append_before_close(
                parts[name].decode("utf-8"), close, "".join(add)
            ).encode("utf-8")
    return len(planned), unclassified


def _set_comment_text(com: str, cid: str, new_text: str) -> str:
    m = re.search(
        f'(<w:comment [^>]*w:id="{cid}"[^>]*>)(.*?)(</w:comment>)',
        com, re.DOTALL)
    # set_run_text escapes; passing pre-escaped text would double-encode
    body = set_run_text(m.group(2), new_text)
    return com[:m.start()] + m.group(1) + body + m.group(3) + com[m.end():]


def reclassify(parts: dict[str, bytes],
               classify: Callable[[RevisionContext], str | None],
               *, generic: str = GENERIC) -> tuple[int, list[str]]:
    """Re-derive the text of comments still carrying the generic marker.

    Repairs comments written without full context — one Word added on a
    math-only paragraph, or an older build. Idempotent.
    """
    doc = parts["word/document.xml"].decode("utf-8")
    com = parts["word/comments.xml"].decode("utf-8")
    stale = [m.group(2) for m in _COMMENT_RE.finditer(com)
             if generic in delta_text(m.group(3))]
    if not stale:
        return 0, []

    spans = table_spans(doc)
    done, still = 0, []
    for cid in stale:
        # anchor on the range START, not the reference run: for a revision
        # spanning a table row Word puts the reference past the table,
        # which would classify it by the following paragraph
        m = (re.search(f'<w:commentRangeStart w:id="{cid}"/>', doc)
             or re.search(f'<w:commentReference w:id="{cid}"/>', doc))
        if not m:
            still.append(cid)
            continue
        new = classify(_context(doc, m.start(), m.end(), spans))
        if new is None:
            still.append(cid)
        else:
            com = _set_comment_text(com, cid, new)
            done += 1
    parts["word/comments.xml"] = com.encode("utf-8")
    return done, still
