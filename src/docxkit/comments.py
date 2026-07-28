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

from .find import delta_text_of, para_text_at, table_index_at, table_spans

__all__ = [
    "GENERIC",
    "RevisionContext",
    "annotate",
    "reclassify",
    "revision_spans",
]

GENERIC = "Revision (unclassified)"

_REV_OPEN_RE = re.compile(r"<w:(ins|del)\b[^>]*?(/?)>")
_T_RUN_RE = re.compile(r"(<w:t[^>]*>)[^<]*(</w:t>)")
_COMMENT_RE = re.compile(
    r'(<w:comment [^>]*w:id="(\d+)"[^>]*>)(.*?)(</w:comment>)', re.DOTALL)
_ANCHOR_SLACK = 60          # chars scanned either side for an existing range
_WINDOW_BACK = 3000         # context behind the anchor, in chars of markup


@dataclass(frozen=True)
class RevisionContext:
    """What a classifier gets to decide a revision's comment."""

    text: str               # the revision's own text, deletions included
    para: str               # visible text of the containing paragraph
    window: str             # surrounding prose, tags stripped
    table_index: int | None  # which manuscript table, if any
    start: int
    end: int

    @property
    def haystack(self) -> str:
        """Everything searchable, for simple substring rules."""
        return f"{self.para} {self.window} {self.text}"


def _matching_close(xml: str, pos: int, tag: str) -> int:
    """End offset of the ``</w:tag>`` closing the element opened before pos."""
    open_re = re.compile(rf"<w:{tag}\b[^>]*?(/?)>")
    close = f"</w:{tag}>"
    depth = 1
    while depth:
        nxt = xml.index(close, pos)
        m = open_re.search(xml, pos, nxt)
        while m and m.group(1) == "/":      # property marks don't nest
            m = open_re.search(xml, m.end(), nxt)
        if m:
            depth += 1
            pos = m.end()
        else:
            depth -= 1
            pos = nxt + len(close)
    return pos


def revision_spans(doc: str) -> list[tuple[int, int]]:
    """(start, end) of every run-level ``w:ins`` / ``w:del``, outermost only.

    Self-closing marks are skipped. A ``<w:ins/>`` with no content is a
    property-level revision — an inserted paragraph mark, table row, or run
    property — which is not a text range and cannot carry a comment anchor.
    That one test is what separates the two kinds.
    """
    spans, pos = [], 0
    while (m := _REV_OPEN_RE.search(doc, pos)):
        if m.group(2) == "/":
            pos = m.end()
            continue
        end = _matching_close(doc, m.end(), m.group(1))
        spans.append((m.start(), end))
        pos = end                           # nested revisions ride along
    return spans


def _already_anchored(doc: str, start: int, end: int) -> bool:
    return ("commentRangeStart" in doc[max(0, start - _ANCHOR_SLACK):start]
            and "commentRangeEnd" in doc[end:end + _ANCHOR_SLACK])


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _context(doc: str, start: int, end: int,
             spans: list[tuple[int, int]]) -> RevisionContext:
    return RevisionContext(
        text=delta_text_of(doc[start:end]),
        para=para_text_at(doc, start),
        window=re.sub("<[^>]+>", "", doc[max(0, start - _WINDOW_BACK):end]),
        table_index=table_index_at(spans, start),
        start=start, end=end)


def _comment_element(template: str, cid: int, para_id: str, text: str) -> str:
    """A copy of Word's own comment element carrying `text`.

    Cloning Word's element rather than hand-writing one keeps the author,
    date, style and namespace prefixes exactly as Word wrote them.
    """
    x = re.sub(r'w:id="\d+"', f'w:id="{cid}"', template, count=1)
    x = re.sub(r'w14:paraId="[0-9A-Fa-f]{8}"', f'w14:paraId="{para_id}"',
               x, count=1)
    runs = list(_T_RUN_RE.finditer(x))
    if not runs:
        raise AssertionError("comment template has no text run")
    for i, tm in enumerate(reversed(runs)):
        idx = len(runs) - 1 - i
        body = _esc(text) if idx == 0 else ""
        x = x[:tm.start()] + tm.group(1) + body + tm.group(2) + x[tm.end():]
    return x


def _append_before_close(xml: str, close_tag: str, addition: str) -> str:
    i = xml.rindex(close_tag)
    return xml[:i] + addition + xml[i:]


def annotate(parts: dict[str, bytes],
             classify: Callable[[RevisionContext], str | None],
             *, generic: str = GENERIC) -> tuple[int, int]:
    """Comment every run-level revision in ``document.xml``.

    The package must already carry Word's comment scaffold — at least one
    comment Word itself created — so the parts, styles and relationships
    are Word's own rather than hand-rolled. :func:`docxkit.tracked.build`
    arranges that.

    Returns (comments added, revisions no rule matched).
    """
    doc = parts["word/document.xml"].decode("utf-8")
    com = parts["word/comments.xml"].decode("utf-8")
    tm = re.search(r"<w:comment .*?</w:comment>", com, re.DOTALL)
    if not tm:
        raise AssertionError(
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
               for s, e in revision_spans(doc)
               if not _already_anchored(doc, s, e)]
    unclassified = sum(1 for *_, c in planned if c is None)

    elements, exts, ids, exls = [], [], [], []
    # insert back-to-front so the earlier offsets stay valid
    for i, (start, end, comment) in reversed(list(enumerate(planned))):
        cid = next_id + i
        para_id, durable = f"{0x5A000000 + cid:08X}", f"{0x6B000000 + cid:08X}"
        doc = (doc[:start] + f'<w:commentRangeStart w:id="{cid}"/>'
               + doc[start:end] + f'<w:commentRangeEnd w:id="{cid}"/>'
               '<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
               f'<w:commentReference w:id="{cid}"/></w:r>' + doc[end:])
        elements.append(_comment_element(template, cid, para_id,
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
    body = m.group(2)
    runs = list(_T_RUN_RE.finditer(body))
    for i, tm in enumerate(reversed(runs)):
        idx = len(runs) - 1 - i
        repl = tm.group(1) + (_esc(new_text) if idx == 0 else "") + tm.group(2)
        body = body[:tm.start()] + repl + body[tm.end():]
    return com[:m.start()] + m.group(1) + body + m.group(3) + com[m.end():]


def reclassify(parts: dict[str, bytes],
               classify: Callable[[RevisionContext], str | None],
               *, generic: str = GENERIC) -> tuple[int, list[str]]:
    """Re-derive the text of comments still carrying the generic marker.

    Repairs comments written without full context — a comment Word added
    on a math-only paragraph, or an older build. Idempotent.
    """
    doc = parts["word/document.xml"].decode("utf-8")
    com = parts["word/comments.xml"].decode("utf-8")
    stale = [m.group(2) for m in _COMMENT_RE.finditer(com)
             if generic in delta_text_of(m.group(3))]
    if not stale:
        return 0, []

    spans = table_spans(doc)
    done, still = 0, []
    for cid in stale:
        # anchor on the range START, not the reference run: for a revision
        # spanning a table row Word puts the reference past the table, which
        # would classify it by the following paragraph instead of the table
        m = (re.search(f'<w:commentRangeStart w:id="{cid}"/>', doc)
             or re.search(f'<w:commentReference w:id="{cid}"/>', doc))
        if not m:
            still.append(cid)
            continue
        end = m.end()
        new = classify(_context(doc, m.start(), end, spans))
        if new is None:
            still.append(cid)
        else:
            com = _set_comment_text(com, cid, new)
            done += 1
    parts["word/comments.xml"] = com.encode("utf-8")
    return done, still
