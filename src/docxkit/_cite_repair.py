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
    field_spans,
    own_properties,
)
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
def wrap_link_in_bookmark(xml: str, anchor: str, name: str, bid: int,
                          *, which: str = "only") -> str:
    """Recreate `name` around the ONE link that points at `anchor`.

    The ``<key>txt`` convention's in-text end, rebuilt exactly where the
    surviving hyperlink sits — element form, or a complete fldChar
    field whose instruction carries the anchor.

    ``which="first"`` wraps the FIRST of several links to one anchor
    rather than refusing. Refusing is right as the default — the tool
    will not guess which mention owns the bookmark — but the house
    convention has an answer: the ``<key>txt`` bookmark belongs on the
    first in-text mention, later ones stay forward-only. With no way to
    say that, the same regex was hand-rolled twice in ONE paper
    (`repair_round3_links.py`, then `_wrap_first` in `repair_round5.py`).

    The two forms are counted together for that decision. A work linked
    once each way is two mentions — Word rewrites a field into an
    element whenever the author saves, so a manuscript mid-round holds
    both — and taking the element because it happened to be unique
    would put the bookmark wherever form churn left it.
    """
    if which not in ("only", "first"):
        raise ValueError(f"which={which!r}: expected 'only' or 'first'")
    start = f'<w:bookmarkStart w:id="{bid}" w:name="{name}"/>'
    end = f'<w:bookmarkEnd w:id="{bid}"/>'

    # `(?<!/)>` — a self-closing `<w:hyperlink w:anchor=".."/>` is an
    # empty ghost Word leaves behind, and pairing one with the next
    # `</w:hyperlink>` downstream wraps the bookmark around everything
    # between: the prose, and whatever OTHER link is in it. The same
    # guard is on `_xml._HYPERLINK_EL_RE` and for the same reason
    # (Parental Style, 14 paragraphs). A ghost is not a link to wrap, so
    # not matching it is the right answer and the refusal below says so.
    el = re.compile(rf'<w:hyperlink\b[^>]*w:anchor="{anchor}"[^>]*(?<!/)>'
                    r".*?</w:hyperlink>", re.DOTALL)
    spans = [(m.start(), m.end()) for m in el.finditer(xml)]
    spans += [(s, e) for s, e, body in field_spans(xml)
              if f'"{anchor}"' in body]
    if not spans:
        raise AnchorError(f"wrap_link_in_bookmark: no link to {anchor}")
    if len(spans) > 1 and which == "only":
        raise AnchorError(
            f"wrap_link_in_bookmark: {anchor} matched {len(spans)} links "
            f"— pass which='first' for the house convention (the bookmark "
            f"goes on the first mention), or name a narrower anchor")
    s, e = min(spans)
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
    m = re.search(rf'<w:hyperlink\b[^>]*w:anchor="{inner}"[^>]*(?<!/)>'
                  r".*?</w:hyperlink>", body, re.DOTALL)
    assert m is not None
    return xml[:s] + m.group(0) + xml[e:]


def respan_link(xml: str, anchor: str, want: str) -> str:
    """Move the boundary of the ONE link on `anchor` so it covers `want`.

    The UNBALANCED SPAN repair. The audit has named this defect since
    2026-08-25 and nothing could fix it, so the papers did: Aging_Well
    is on its THIRD in-paper span repair, and that script's own
    docstring records why the first two died — "tables of hard-coded
    signatures, and both went stale and killed the script". The third
    reads the links instead, and still cannot see this case, because it
    can only TRIM: it computes the balanced label from the label alone,
    which cannot know that the ``)`` the span is missing sits one
    character to its right.

    So the desired span comes from :func:`docxkit.citations.balanced_span`,
    which reads the paragraph, and this MOVES the boundary to it —
    trimming or extending, whichever the span needs.

    The visible text is not touched: this is a markup repair, and the
    guard below holds it to that. What changes is which characters are
    blue.

    Element form only. A field-form link is five runs and Word rewrites
    it to an element on the author's next save anyway, which is why
    :func:`docxkit.citations.link_in_para` writes elements too; a field
    is refused by name rather than half-repaired.
    """
    from ._cite_grammar import wrap_visible_span
    from ._xml import PARA_RE, visible_text

    el = re.compile(rf'<w:hyperlink\b[^>]*w:anchor="{anchor}"[^>]*(?<!/)>'
                    r".*?</w:hyperlink>", re.DOTALL)
    hits = [(pm.start(), pm.end(), m.start(), m.end())
            for pm in PARA_RE.finditer(xml)
            for m in el.finditer(pm.group(0))]
    fields = [1 for s, e, body in field_spans(xml) if f'"{anchor}"' in body]
    if len(hits) + len(fields) != 1:
        raise AnchorError(
            f"respan_link: {anchor} matched {len(hits) + len(fields)} "
            f"link(s), need exactly 1")
    if not hits:
        raise AnchorError(
            f"respan_link: the link to {anchor} is in FIELD form, which "
            f"this does not rewrite. Word converts it to an element on "
            f"the next save; re-run then, or relink the mention.")
    p0, p1, s, e = hits[0]
    para = original = xml[p0:p1]
    text = visible_text(para)
    at = len(visible_text(para[:s]))
    label = visible_text(para[s:e])
    end = at + len(label)
    if want == label:
        return xml

    # Which EDGE moved. Derived from the two strings rather than searched
    # for, because a label can repeat in one paragraph — "(2019)" twice —
    # and a locate would then wrap whichever came first.
    if want.startswith(label) or label.startswith(want):
        new_at, new_end = at, at + len(want)
    elif want.endswith(label) or label.endswith(want):
        new_at, new_end = end - len(want), end
    else:
        raise AnchorError(
            f"respan_link: {want[:40]!r} is not {label[:40]!r} with an edge "
            f"moved — this repair widens or narrows a span, it does not "
            f"retype one")
    if text[new_at:new_end] != want:
        raise AnchorError(
            f"respan_link: {anchor}: the paragraph does not read "
            f"{want[:40]!r} at the moved boundary")

    # CARRY the bookmark that wraps this link, if one does. The house
    # convention puts `<key>txt` — the reference entry's back-link
    # target — around the first mention, which is this hyperlink. Moving
    # the link's edge without it leaves the link reaching PAST the
    # bookmark: measured, and every count stays right, because a
    # bookmark that no longer wraps its mention is still a bookmark. The
    # per-paper repair this replaces dropped and re-added it for the
    # same reason.
    carried = ""
    bm = re.search(r'<w:bookmarkStart w:id="(\d+)" w:name="[^"]+"/>\s*$',
                   para[:s])
    if bm is not None:
        shut = f'<w:bookmarkEnd w:id="{bm.group(1)}"/>'
        if para[e:].startswith(shut):
            carried = bm.group(0)
            para = para[:bm.start()] + para[bm.end():s] + para[s:]
            s -= len(carried)
            e -= len(carried)
            para = para[:e] + para[e + len(shut):]

    # Unwrap, then re-wrap at the new edges. The character the span gives
    # up keeps the Hyperlink CHARACTER STYLE otherwise — still blue,
    # still underlined, linking nowhere, and no layer that reads anchors
    # would see it.
    inner = para[s:e]
    inner = inner[inner.index(">") + 1:-len("</w:hyperlink>")]
    inner = re.sub(r'<w:rStyle w:val="Hyperlink"/>', "", inner)
    bare = para[:s] + inner + para[e:]
    fixed = wrap_visible_span(bare, new_at, new_end, anchor)

    if carried:
        shut = f'<w:bookmarkEnd w:id="{bm.group(1)}"/>'  # type: ignore[union-attr]
        link = re.search(rf'<w:hyperlink\b[^>]*w:anchor="{anchor}"'
                         r'[^>]*(?<!/)>.*?</w:hyperlink>', fixed, re.DOTALL)
        if link is None:                     # pragma: no cover - defensive
            raise AnchorError(f"respan_link: {anchor}: lost the link")
        fixed = (fixed[:link.start()] + carried + link.group(0) + shut
                 + fixed[link.end():])

    if visible_text(fixed) != text:
        raise AnchorError(
            f"respan_link: {anchor}: the paragraph's visible text moved — "
            f"this repair changes which characters are LINKED, never what "
            f"the page says")
    for tag in ("<w:bookmarkStart", "<w:bookmarkEnd"):
        if fixed.count(tag) != original.count(tag):
            raise AnchorError(
                f"respan_link: {anchor}: {tag} count moved — the txt "
                f"bookmark rides inside the link and must survive it")
    return xml[:p0] + fixed + xml[p1:]


