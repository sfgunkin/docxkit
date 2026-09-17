"""Bookmark and hyperlink SURGERY.

The primitives every repair is built from: write a bookmark, wrap a
link in one, retarget a field, un-nest a doubled link, allocate an id.
Each asserts what it matched, because a repair that silently finds
nothing is how a manuscript ships half-linked.
"""
from __future__ import annotations

import re
from collections import Counter

from ._cite_grammar import bookmark, citation_shape
from ._xml import (
    BOOKMARK_END_ID_RE,
    BOOKMARK_ID_RE,
    BOOKMARK_NAME_RE,
    BOOKMARK_START_ID_RE,
    HYPERLINK_ANY_RE,
    PARA_RE,
    _shows_nothing,
    field_spans,
    fields,
    internal_links,
    own_properties,
    run_open_before,
    run_spans,
    set_run_text,
    span_holding,
    visible_text,
)
from .edit import _links_to, insert_in_para, relabel_link
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
    """Remove the Start/End pair `name` (id read off the Start).

    Either attribute order and either close, `/>` or ` />`, as
    `respan_link` reads them: a pair another producer wrote was "not
    found" here while it sat in the file.
    """
    m = re.search(rf'<w:bookmarkStart\b(?=[^>]*\bw:name="{re.escape(name)}")'
                  r'[^>]*\bw:id="(\d+)"[^>]*/>', xml)
    if m is None:
        raise AnchorError(f"delete_bookmark: {name} not found")
    xml = xml[:m.start()] + xml[m.end():]
    ends = list(re.finditer(rf'<w:bookmarkEnd\b[^>]*\bw:id="{m.group(1)}"'
                            r"[^>]*/>", xml))
    if len(ends) != 1:
        raise AnchorError(f"delete_bookmark: end of {name} not unique")
    return xml[:ends[0].start()] + xml[ends[0].end():]


def remove_outer_field(xml: str, outer: str, inner: str) -> str:
    """Remove the ONE field targeting `outer` whose result wraps the
    element link to `inner`; the element survives, un-nested.

    The DOUBLED LINK repair: a stale or mistargeted field wrapping the
    correct link, so the click goes to the wrong place — API10's WHO
    back-link buried in a dead OneDrive-URL field, LI7's Hudiyana
    back-link inside a typo'd predecessor and its OECD source note
    inside a link to the WRONG entry. Third paper's need moved it here.

    Cut at the MARKERS, not at `field_spans`' run boundaries. Word writes
    a field's `begin` into the run that already holds the words before
    it as often as not, and its `end` into the one carrying the words
    after: splicing the span out deleted the sentence around the field —
    "As Smith (2020) found, the index rose." came back as "Smith
    (2020)", silently, in a write path (S1, 2026-09-18). What goes is the
    field: its markers, its instruction, and the cached result it
    wrapped around the link. What stays is the link, and every character
    of prose that was only keeping it company in a run.
    """
    found = [f for f in fields(xml)
             if f'"{outer}"' in f.instr and f.result is not None
             and f'w:anchor="{inner}"' in f.result]
    if len(found) != 1:
        raise AnchorError(
            f"remove_outer_field: {outer}>{inner}: {len(found)} fields")
    field = found[0]
    m = re.search(rf'<w:hyperlink\b[^>]*w:anchor="{inner}"[^>]*(?<!/)>'
                  r".*?</w:hyperlink>", field.result or "", re.DOTALL)
    assert m is not None

    # The two runs the field shares with the paragraph: the one its
    # `begin` sits in and the one its `end` sits in. Each is kept, less
    # its marker, when anything a reader sees is left of it — and
    # dropped whole when the marker was all it held, so the ordinary
    # field (every marker in a run of its own) leaves nothing behind.
    end_at = xml.rindex("<w:fldChar", field.start, field.end)
    past_end = xml.index(">", field.end) + 1
    head = xml[run_open_before(xml, field.start):field.start] + "</w:r>"
    tail = (xml[run_open_before(xml, end_at):end_at]
            + xml[past_end:xml.index("</w:r>", past_end) + len("</w:r>")])
    return (xml[:run_open_before(xml, field.start)]
            + ("" if _shows_nothing(head) else head)
            + m.group(0)
            + ("" if _shows_nothing(tail) else tail)
            + xml[xml.index("</w:r>", past_end) + len("</w:r>"):])


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
    trimming or extending, at one edge or at both, whichever the span
    needs.

    The visible text is not touched: this is a markup repair, and the
    guard below holds it to that. What changes is which characters are
    blue.

    BOTH link forms, and the field form is the one that matters: on the
    manuscript this was written for, links are **173 field to 33
    element**, and the defect that prompted it was on a field. The first
    version refused fields, reasoning from
    :func:`docxkit.citations.link_in_para` that "Word converts a field to
    an element on the next save anyway" — true, and no use to a repair
    that has to run before that save. It would have covered 16% of that
    paper's links.

    A field is five runs (begin, instruction, separate, the LABEL, end)
    and is rebuilt as an ELEMENT, which is what `link_in_para` writes and
    what Word's own save would have made of it. So the repair leaves one
    form behind, deliberately, rather than splicing runs into a field
    whose instruction it would then have to keep in step.
    """
    from ._cite_grammar import wrap_visible_span

    el = re.compile(rf'<w:hyperlink\b[^>]*w:anchor="{anchor}"[^>]*(?<!/)>'
                    r".*?</w:hyperlink>", re.DOTALL)
    hits = [(pm.start(), pm.end(), m.start(), m.end(), "element")
            for pm in PARA_RE.finditer(xml)
            for m in el.finditer(pm.group(0))]
    hits += [(pm.start(), pm.end(), fs, fe, "field")
             for pm in PARA_RE.finditer(xml)
             for fs, fe, body in field_spans(pm.group(0))
             if f'"{anchor}"' in body]
    if len(hits) != 1:
        raise AnchorError(
            f"respan_link: {anchor} matched {len(hits)} link(s), need "
            f"exactly 1")
    p0, p1, s, e, form = hits[0]
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
    # …or BOTH, when one string sits exactly once inside the other. A link
    # that swallowed both brackets — `(Robeyns 2005)`, Aging_Well
    # 2026-09-11 — shares neither a start nor an end with `Robeyns 2005`,
    # and this used to refuse it as a RETYPE: the paper made two calls,
    # one edge each, and the text guard held on both. Neither moves a
    # character of the page, and the guard below still has to agree.
    elif label.count(want) == 1:
        new_at = at + label.index(want)
        new_end = new_at + len(want)
    elif want.count(label) == 1:
        new_at = at - want.index(label)
        new_end = new_at + len(want)
    else:
        raise AnchorError(
            f"respan_link: {want[:40]!r} is not {label[:40]!r} with an edge "
            f"moved, nor with both — this repair widens or narrows a span, "
            f"it does not retype one")
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
    #
    # Either attribute order and either close, `/>` or ` />`: other
    # producers write `w:name` first with a space before the slash (97
    # starts in 7 of 2,954 corpus packages), and a pair spelled only Word's
    # way was not found there, so it was not carried. Both tags go back
    # as they were written.
    carried = shut = ""
    bm = re.search(r'<w:bookmarkStart\b(?=[^>]*\bw:name="[^"]+")'
                   r'[^>]*\bw:id="(\d+)"[^>]*/>\s*$', para[:s])
    if bm is not None:
        bm_end = re.match(rf'<w:bookmarkEnd\b[^>]*\bw:id="{bm.group(1)}"'
                          r"[^>]*/>", para[e:])
        if bm_end is not None:
            carried, shut = bm.group(0), bm_end.group(0)
            para = para[:bm.start()] + para[bm.end():s] + para[s:]
            s -= len(carried)
            e -= len(carried)
            para = para[:e] + para[e + len(shut):]

    # Unwrap, then re-wrap at the new edges. The character the span gives
    # up keeps the Hyperlink CHARACTER STYLE otherwise — still blue,
    # still underlined, linking nowhere, and no layer that reads anchors
    # would see it.
    inner = para[s:e]
    if form == "element":
        inner = inner[inner.index(">") + 1:-len("</w:hyperlink>")]
    else:
        # The LABEL runs of a field: everything after the `separate`
        # fldChar, less the `end` one. The instruction run goes with the
        # field — it carries no visible text, so no offset moves. The end
        # run is found by its OPEN tag: Word styles it like the label, and
        # `rindex("<w:r")` stopped on its `<w:rStyle`, leaving `<w:r><w:rPr>`
        # in the paragraph (code review, 2026-09-13; the note above
        # `wrap_link_in_bookmark` is the same trap).
        cut = run_open_before(inner, inner.rindex("fldCharType=\"end\""))
        sep = inner.index("fldCharType=\"separate\"")
        inner = inner[inner.index("</w:r>", sep) + len("</w:r>"):cut]
    # `\s*/>`: the style closed ` />` (739 in 20 of 2,954 corpus packages)
    # stayed on the surrendered character otherwise (2026-09-17).
    inner = re.sub(r'<w:rStyle w:val="Hyperlink"\s*/>', "", inner)
    bare = para[:s] + inner + para[e:]
    fixed = wrap_visible_span(bare, new_at, new_end, anchor)

    if carried:
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


# ------------------------------------------------ the two citation forms ---


def to_narrative(xml: str, anchor: str) -> str:
    """``… (Name Year) …`` becomes ``… Name (Year) …``, on the ONE link to
    `anchor`: the brackets move onto the label, and the link keeps its form.

    A hand pass turns a parenthetical citation into the object of a
    sentence — "as in (Behrman et al. 1982)." — and the ruling is the
    narrative form, "as in Behrman et al. (1982).". Nothing did it:
    :func:`respan_link` moves an edge and does not retype one, and here
    the label's own words change. So the paper edited three runs by
    structure under a visible-text guard (Aging_Well R129, 2026-09-11),
    and hand passes make the conversion often — that day, once each way.

    The house convention has one right answer per form, and
    :func:`docxkit.citations.citation_shape` reads them: a NARRATIVE
    citation keeps its year brackets inside the link, ``Name (Year)``; a
    PARENTHETICAL one links ``Name Year`` and leaves the brackets black.
    This accepts either parenthetical spelling — brackets outside the
    link, or both swallowed inside it — and hands back `xml` itself when
    the link is narrative already.

    What it keeps is the point: the link's FORM — a field stays a field,
    where `respan_link` rebuilds one as an element — its ``<key>txt``
    bookmark around the label, and every other character. What it
    refuses: a link that is not one work and a year, and brackets that
    hold more than this citation, ``(Hood 1983; Hood and Margetts 2007)``,
    where moving them onto one label rewrites the other's sentence. The
    page is asserted to change by exactly the bracket move.
    """
    return _convert(xml, anchor, narrative=True)


def to_parenthetical(xml: str, anchor: str) -> str:
    """``… Name (Year) …`` becomes ``… (Name Year) …``, on the ONE link to
    `anchor`: the label loses its brackets, and a pair goes round the link
    OUTSIDE it and outside its ``<key>txt`` bookmark. Where that bookmark
    already starts earlier in the sentence, the opening bracket lands
    inside it: a conversion does not move a bookmark.

    The other direction of :func:`to_narrative`, for the same measured
    need, and the repair for the shape that passed every gate on
    2026-09-11: a link that swallowed both brackets, ``(Robeyns 2005)``,
    reads the same on the page afterwards and links ``Robeyns 2005``, the
    form the rest of that paper uses. Hands back `xml` itself when the
    link is parenthetical already, brackets outside.
    """
    return _convert(xml, anchor, narrative=False)


def _convert(xml: str, anchor: str, *, narrative: bool) -> str:
    """Both conversions: find the one link, read its shape, move the
    brackets, and prove the page changed by exactly that."""
    caller = "to_narrative" if narrative else "to_parenthetical"
    found = [(pm, link) for pm in PARA_RE.finditer(xml)
             for link in _links_to(pm.group(0), anchor)]
    if len(found) != 1:
        raise AnchorError(
            f"{caller}: {anchor} matched {len(found)} link(s), need exactly "
            f"1 — hand it the paragraph the citation is in")
    pm, link = found[0]
    para = original = pm.group(0)
    text = visible_text(para)
    at = len(visible_text(para[:link.label[0]]))
    label = visible_text(para[link.label[0]:link.label[1]])
    end = at + len(label)
    shape = citation_shape(label)
    if shape is None:
        raise AnchorError(
            f"{caller}: the link to {anchor} reads {label[:48]!r}, which is "
            f"not one work and a year")
    form, _names, years = shape
    if form == ("narrative" if narrative else "bare"):
        return xml
    # Both labels are made by EDITING this one, never rebuilt from its
    # parts, so every space in them is the author's. Rebuilt from `names`
    # and `years`, a real label ending "Schluter.  (2018)" came back with
    # one space — and passed the guard below, which was built from the same
    # rebuilt string (LI, 2026-09-11).
    bare = label if form == "bare" else _without_brackets(label)
    ends = len(bare.rstrip())
    told = bare[:ends - len(years)] + "(" + years + ")" + bare[ends:]

    if form == "bare":                      # (Name Year) -> Name (Year)
        if text[at - 1:at] != "(" or text[end:end + 1] != ")":
            raise AnchorError(
                f"{caller}: {label!r} is not inside a bracket pair of its "
                f"own — brackets holding several citations belong to all "
                f"of them, and moving them onto one label rewrites the rest")
        want = text[:at - 1] + told + text[end + 1:]
        para = _delete_char(para, end, ")", caller)     # the later one first
        para = _delete_char(para, at - 1, "(", caller)
        para = relabel_link(para, anchor, told)
    elif narrative:                         # swallowed pair -> Name (Year)
        want = text[:at] + told + text[end:]
        para = relabel_link(para, anchor, told)
    else:                                   # Name (Year), swallowed -> bare
        want = text[:at] + "(" + bare + ")" + text[end:]
        para = relabel_link(para, anchor, bare)
        # `allow_bookmark`: a citation's bookmark can START before its link
        # and end with it — `cite_riekhoff_2024` 29 characters early on
        # AFI, `Cosco2015txt` 46 on HPPA, a reference entry's own bookmark
        # one space early on LI, and no audit reports any of them. The
        # opening bracket then falls strictly inside it, with no outside to
        # go to short of moving the bookmark, which a conversion does not
        # do; refusing cost those three (2026-09-11). The closing bracket
        # still lands outside: at an EDGE `insert_in_para` goes outside
        # whatever the flag says.
        para = insert_in_para(para, at + len(bare), ")", allow_bookmark=True)
        para = insert_in_para(para, at, "(", allow_bookmark=True)

    if (got := visible_text(para)) != want:
        raise AnchorError(
            f"{caller}: {anchor}: the paragraph would read "
            f"{got[max(0, at - 24):end + 24]!r}, which is not the bracket "
            f"move asked for")
    for tag in ("<w:hyperlink", "<w:instrText", "<w:bookmarkStart",
                "<w:bookmarkEnd"):
        if para.count(tag) != original.count(tag):
            raise AnchorError(
                f"{caller}: {anchor}: the {tag} count moved — the link keeps "
                f"its form and its bookmark")
    if ([a for a, _ in internal_links(para)]
            != [a for a, _ in internal_links(original)]):
        raise AnchorError(f"{caller}: {anchor}: the paragraph's links moved")
    return xml[:pm.start()] + para + xml[pm.end():]


#: A run holding nothing once its text is gone: properties at most, and one
#: EMPTY ``w:t``. Kept, it is an empty run Word opens and every diff reports.
#: Empty, not blank: ` (` is a run Word leaves after a hand edit, and a
#: pattern allowing whitespace here removed the space with the bracket —
#: `countriesWHO (2025)`, 26 real citations over five papers, each refused
#: by the text guard before anything was written (2026-09-11).
_EMPTIED_RUN_RE = re.compile(
    r"<w:r\b[^>]*>(?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?"
    r"<w:t\b[^>]*></w:t></w:r>", re.DOTALL)


def _without_brackets(label: str) -> str:
    """`label` less its one opening and one closing bracket — the two a
    narrative or a swallowed citation carries, and nothing else moved."""
    opens, shuts = label.index("("), label.rindex(")")
    return label[:opens] + label[opens + 1:shuts] + label[shuts + 1:]


def _delete_char(para: str, pos: int, char: str, caller: str) -> str:
    """`para` without the ONE visible `char` at offset `pos`.

    From a run of prose only. A character inside a link's label or a
    field is not a bracket beside the citation, and removing it would
    rewrite the thing being kept; the bracket a conversion moves sits
    OUTSIDE the link and its bookmark, by the convention being enforced.
    """
    guarded = ([(m.start(), m.end()) for m in HYPERLINK_ANY_RE.finditer(para)]
               + [(lo, hi) for lo, hi, _ in field_spans(para)])
    runs, spans, _cursor = run_spans(para)
    for run, (lo, hi) in zip(runs, spans, strict=True):
        if not lo <= pos < hi:
            continue
        body = visible_text(run.group(0))
        if body[pos - lo] != char or span_holding(run.start(), guarded):
            break
        rebuilt = set_run_text(run.group(0),
                               body[:pos - lo] + body[pos - lo + 1:])
        if _EMPTIED_RUN_RE.fullmatch(rebuilt):
            rebuilt = ""
        return para[:run.start()] + rebuilt + para[run.end():]
    raise AnchorError(
        f"{caller}: no plain {char!r} at offset {pos} beside the link — "
        f"the brackets are not where a citation of that form keeps them")


# ------------------------------------------------- the back-link marker ---


def _own_marker(anchor: str) -> str | None:
    """The bookmark a link to `anchor` carries round itself, or None.

    `<key>txt` for a link to `<key>`, this package's naming, or `cite_x`
    for a link to `ref_x`, a paper's. A link that is itself a back-link,
    to `<key>txt` or `cite_x`, carries none of its own: the entry's
    bookmark round it is wide by design.
    """
    if anchor.endswith("txt") or anchor.startswith("cite_"):
        return None
    if anchor.startswith("ref_"):
        return "cite_" + anchor[4:]
    return anchor + "txt"


_BOOKMARK_TAG_RE = re.compile(r"<w:bookmark(?:Start|End)\b[^>]*/>")


def _marker_spans(para: str) -> dict[str, tuple[int, int, str]]:
    """Each bookmark that starts AND ends in this paragraph, by name:
    (visible start, visible end, id)."""
    opened: dict[str, tuple[str, int]] = {}
    out: dict[str, tuple[int, int, str]] = {}
    for m in _BOOKMARK_TAG_RE.finditer(para):
        at = len(visible_text(para[:m.start()]))
        if (start := BOOKMARK_START_ID_RE.match(m.group(0))) is not None:
            named = BOOKMARK_NAME_RE.match(m.group(0))
            opened[start.group(1)] = (named.group(1) if named else "", at)
        elif ((end := BOOKMARK_END_ID_RE.match(m.group(0))) is not None
              and end.group(1) in opened):
            mark, lo = opened.pop(end.group(1))
            out[mark] = (lo, at, end.group(1))
    return out


def rewrap_marker(xml: str, name: str) -> str:
    """Rebuild the back-link marker `name` round its own link.

    The reference entry's back-link lands on this bookmark, and Word
    selects what it covers, so a marker that has left its link sends the
    reader somewhere else. Over the eight real snapshots (2026-09-12) 17
    markers were off their link by real text, 12 of them on HPPA, where
    seven had collapsed to nothing at the END of their paragraph — the
    trace of a paragraph retyped in Word — one 496 characters past its
    citation. No audit said so. The audit's MARKER OFF LINK names them,
    and this is the repair it proposes.

    Same name, same id, now round exactly its link: the marker is deleted
    and rebuilt by :func:`wrap_link_in_bookmark`. Refused: a name that is
    not a link's own marker, one that does not start and end in a single
    paragraph, and a paragraph holding other than one link to its anchor.
    Nothing a reader sees moves, and no link changes.
    """
    anchor = (name[:-3] if name.endswith("txt")
              else "ref_" + name[5:] if name.startswith("cite_") else None)
    if anchor is None or _own_marker(anchor) != name:
        raise AnchorError(
            f"rewrap_marker: {name} is not a link's own marker — "
            f"`<key>txt`, or `cite_x` for a link to `ref_x`")
    homes = [pm for pm in PARA_RE.finditer(xml)
             if f'w:name="{name}"' in pm.group(0)]
    if len(homes) != 1:
        raise AnchorError(f"rewrap_marker: {name} starts in {len(homes)} "
                          f"paragraph(s), need exactly 1")
    pm = homes[0]
    para = pm.group(0)
    if name not in (spans := _marker_spans(para)):
        raise AnchorError(f"rewrap_marker: {name} does not end in the "
                          f"paragraph it starts in")
    if (n := len(_links_to(para, anchor))) != 1:
        raise AnchorError(f"rewrap_marker: {anchor} has {n} link(s) beside "
                          f"{name}, need exactly 1")
    bid = spans[name][2]
    bare = re.sub(rf'<w:bookmark(?:Start|End)\b[^>]*w:id="{bid}"[^>]*/>',
                  "", para, count=2)
    fixed = wrap_link_in_bookmark(bare, anchor, name, int(bid))
    if (visible_text(fixed) != visible_text(para)
            or internal_links(fixed) != internal_links(para)):
        raise AnchorError(f"rewrap_marker: {name}: the paragraph's text or "
                          f"links would move")
    return xml[:pm.start()] + fixed + xml[pm.end():]


# ---------------------------------------------------- a link to itself ---


def _pair_of(name: str) -> str:
    """The other end of a back-link pair: `<key>` for `<key>txt` and back,
    `ref_x` for `cite_x` and back."""
    if name.endswith("txt"):
        return name[:-3]
    if name.startswith("cite_"):
        return "ref_" + name[5:]
    if name.startswith("ref_"):
        return "cite_" + name[4:]
    return name + "txt"


def _link_openings(name: str) -> re.Pattern[str]:
    """Where a link to `name` STARTS: an element's opening tag, or the
    instruction of a HYPERLINK field. Group 1 or 2 is what precedes the
    name, so a rewrite keeps it."""
    n = re.escape(name)
    return re.compile(
        rf'(<w:hyperlink\b[^>]*w:anchor="){n}(?=")'
        rf'|(<w:instrText\b[^>]*>[^<]*HYPERLINK[^<]*\\l\s+"){n}(?=")')


def _self_link_spans(xml: str) -> list[tuple[str, int, int]]:
    """(name, inside start, inside end) for each bookmark that a link to
    ITSELF starts inside.

    By the link's opening, not by a whole parsed link: on HCW the fields
    start inside the bookmark and end outside it, and a reader of complete
    links found none of the three. Word's own `_Toc`, `_Ref` and `_Hlk`
    bookmarks are left out.
    """
    out: list[tuple[str, int, int]] = []
    for m in _BOOKMARK_TAG_RE.finditer(xml):
        start = BOOKMARK_START_ID_RE.match(m.group(0))
        named = BOOKMARK_NAME_RE.match(m.group(0))
        if start is None or named is None or named.group(1).startswith("_"):
            continue
        shut = re.compile(rf'<w:bookmarkEnd\b[^>]*w:id="{start.group(1)}"'
                          ).search(xml, m.end())
        if shut is not None and _link_openings(named.group(1)).search(
                xml, m.end(), shut.start()):
            out.append((named.group(1), m.end(), shut.start()))
    return out


def retarget_self_link(xml: str, name: str, to: str | None = None) -> str:
    """Point the link inside bookmark `name` at `to`, the other end of its
    pair by default, instead of at `name` itself.

    A link that starts inside the bookmark it targets lands the reader
    where they already are, and nothing reported it: the anchor resolves,
    and the link even counts its work as cited. HCW held three
    (2026-09-12): a prose citation inside its own `OECD2017txt` marker,
    and two reference entries whose back-link targets the entry. The
    audit's SELF LINK names them, and this is the repair it proposes.

    Only the anchor in the link's OPENING changes, the element's attribute
    or the field's instruction; the label and the field's result stay.
    Refused: a bookmark holding other than one link to itself, and a
    target no bookmark in `xml` carries — an entry whose in-text marker
    was never made needs its first mention linked and the marker minted
    before its back-link has anywhere to go.
    """
    to = to or _pair_of(name)
    spans = [(lo, hi) for n, lo, hi in _self_link_spans(xml) if n == name]
    hits = [h for lo, hi in spans
            for h in _link_openings(name).finditer(xml, lo, hi)]
    if len(hits) != 1:
        raise AnchorError(f"retarget_self_link: {name} holds {len(hits)} "
                          f"link(s) to itself, need exactly 1")
    if to not in BOOKMARK_NAME_RE.findall(xml):
        raise AnchorError(
            f"retarget_self_link: no bookmark {to} to point at — link the "
            f"first mention and mint {to} first")
    hit = hits[0]
    fixed = (xml[:hit.start()] + (hit.group(1) or hit.group(2)) + to
             + xml[hit.end():])
    before = Counter(anchor for anchor, _ in internal_links(xml))
    after = Counter(anchor for anchor, _ in internal_links(fixed))
    if (visible_text(fixed) != visible_text(xml)
            or before - after != Counter({name: 1})
            or after - before != Counter({to: 1})):
        raise AnchorError(f"retarget_self_link: {name}: more would move "
                          f"than the one link's target")
    return fixed


