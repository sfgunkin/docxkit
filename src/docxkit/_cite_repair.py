"""Bookmark and hyperlink SURGERY.

The primitives every repair is built from: write a bookmark, wrap a
link in one, retarget a field, un-nest a doubled link, allocate an id.
Each asserts what it matched, because a repair that silently finds
nothing is how a manuscript ships half-linked.
"""
from __future__ import annotations

import re

from ._cite_grammar import bookmark
from ._xml import (
    BOOKMARK_ID_RE,
    FLDCHAR_RE,
    own_properties,
)
from .edit import _RUN_OPEN_RE
from .errors import AnchorError
from .find import para_slice

# ------------------------------------------------- link/bookmark repair ---
# Grown in the API10 and LE link-repair rounds, where each paper script
# carried its own copy — the second use is what moved them here.

_BOOKMARK_ID_RE = BOOKMARK_ID_RE       # the shared definition


def next_bookmark_id(*xmls: str) -> int:
    """One above the highest bookmark id across the given parts.

    Ids must be unique across the WHOLE document, so pass every part you
    will write bookmarks into — a footnote bookmark clashing with a body
    id is the same "unreadable content" failure as a body duplicate.
    """
    ids = [int(m) for xml in xmls for m in _BOOKMARK_ID_RE.findall(xml)]
    return max(ids, default=0) + 1


def _mark_para_head(para: str, name: str, bid: int) -> str:
    """A zero-length bookmark at the paragraph's head (after pPr)."""
    own = own_properties(para, "pPr")
    if own is not None:
        at = own[1]
    else:
        m = re.match(r"<w:p\b[^>]*>", para)
        assert m is not None
        at = m.end()
    return para[:at] + bookmark(name, bid) + para[at:]


def marker_bookmark(xml: str, sig: str, name: str, bid: int) -> str:
    """A zero-length bookmark at the head of the ONE paragraph matching
    `sig` — INSIDE the paragraph, so it travels with any future move.

    Body-level markers between paragraphs do NOT travel: reordering
    API10's reference list stranded thirteen of them one entry off,
    because a paragraph cut takes the ``<w:p>`` and nothing beside it.
    """
    s, e = para_slice(xml, sig)
    return xml[:s] + _mark_para_head(xml[s:e], name, bid) + xml[e:]


# The run OPEN tag, never <w:rPr>: rfind("<w:r") inside a run that
# carries run properties lands on the rPr and the cut leaves mismatched
# tags — LI7's round-2 field removal produced XML Word refuses before
# this. (lint caught it; the audit and compare are regex-blind to it.)
def _run_open_before(xml: str, pos: int) -> int:
    starts = [m.start() for m in _RUN_OPEN_RE.finditer(xml, 0, pos)]
    return starts[-1] if starts else -1


def field_spans(xml: str) -> list[tuple[int, int, str]]:
    """Every fldChar field as ``(start, end, body)``, run boundaries in.

    THE field walk. It existed three times with three different guards
    — only one defended against a field whose end tag is missing — and a
    walk that lives in three places is a walk that will disagree with
    itself. An unclosable span is SKIPPED rather than guessed at:
    `xml.find(...) + len(...)` on a miss yields 5, which slices from the
    top of the document, and a splice built on that lands mid-element.

    Fields NEST — Word writes a HYPERLINK inside a REF, and everything
    inside a TOC — so the end is matched by depth, not by taking the
    first one after the begin. Taking the first ended the outer field at
    the INNER field's end: a fragment with two begins and one end, which
    never reached the content past the nested field. The repair that
    consumed it then cut there, leaving the outer field's tail and its
    now-unmatched end marker behind in the document.

    Nested fields are returned alongside their parents, in document
    order, each with its own correct extent. The callers here all
    demand a UNIQUE match and raise otherwise, so a nested hit surfaces
    as a loud "found 2 fields" rather than a quiet half-field splice.
    """
    out: list[tuple[int, int, str]] = []
    open_marks: list[re.Match[str]] = []
    for m in FLDCHAR_RE.finditer(xml):
        kind = m.group(1)
        if kind == "begin":
            open_marks.append(m)
        elif kind == "end" and open_marks:
            bm = open_marks.pop()
            r_start = _run_open_before(xml, bm.start())
            close = xml.find("</w:r>", m.end())
            if r_start < 0 or close < 0:
                continue
            r_end = close + len("</w:r>")
            out.append((r_start, r_end, xml[r_start:r_end]))
    out.sort(key=lambda span: (span[0], -span[1]))
    return out


def wrap_link_in_bookmark(xml: str, anchor: str, name: str,
                          bid: int) -> str:
    """Recreate `name` around the ONE link that points at `anchor`.

    The ``<key>txt`` convention's in-text end, rebuilt exactly where the
    surviving hyperlink sits — element form, or a complete fldChar
    field whose instruction carries the anchor.
    """
    start = f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
    end = f'<w:bookmarkEnd w:id="{bid}"/>'

    el = re.compile(rf'<w:hyperlink\b[^>]*w:anchor="{anchor}"[^>]*>'
                    r".*?</w:hyperlink>", re.DOTALL)
    hits = list(el.finditer(xml))
    if len(hits) == 1:
        m = hits[0]
        return xml[:m.start()] + start + m.group(0) + end + xml[m.end():]
    if hits:
        raise AnchorError(
            f"wrap_link_in_bookmark: {anchor} matched {len(hits)} elements")

    spans = [(s, e) for s, e, body in field_spans(xml)
             if f'"{anchor}"' in body]
    if len(spans) != 1:
        raise AnchorError(
            f"wrap_link_in_bookmark: {anchor} found {len(spans)} fields")
    s, e = spans[0]
    return xml[:s] + start + xml[s:e] + end + xml[e:]


def delete_bookmark(xml: str, name: str) -> str:
    """Remove the Start/End pair `name` (id read off the Start)."""
    m = re.search(rf'<w:bookmarkStart w:id="(\d+)" w:name="{name}"/>', xml)
    if m is None:
        raise AnchorError(f"delete_bookmark: {name} not found")
    xml = xml[:m.start()] + xml[m.end():]
    endtag = f'<w:bookmarkEnd w:id="{m.group(1)}"/>'
    if xml.count(endtag) != 1:
        raise AnchorError(f"delete_bookmark: end of {name} not unique")
    return xml.replace(endtag, "")


def remove_outer_field(xml: str, outer: str, inner: str) -> str:
    """Remove the ONE field targeting `outer` whose result wraps the
    element link to `inner`; the element survives, un-nested.

    The DOUBLED LINK repair: a stale or mistargeted field wrapping the
    correct link, so the click goes to the wrong place — API10's WHO
    back-link buried in a dead OneDrive-URL field, LI7's Hudiyana
    back-link inside a typo'd predecessor and its OECD source note
    inside a link to the WRONG entry. Third paper's need moved it here.
    """
    spans = [(s, e, body) for s, e, body in field_spans(xml)
             if f'"{outer}"' in body and f'w:anchor="{inner}"' in body]
    if len(spans) != 1:
        raise AnchorError(
            f"remove_outer_field: {outer}>{inner}: {len(spans)} fields")
    s, e, body = spans[0]
    m = re.search(rf'<w:hyperlink\b[^>]*w:anchor="{inner}"[^>]*>'
                  r".*?</w:hyperlink>", body, re.DOTALL)
    assert m is not None
    return xml[:s] + m.group(0) + xml[e:]


