r"""Editing ``document.xml`` as text, with the anchors asserted.

House rule across the papers: raw string surgery on WordprocessingML,
never python-docx, and every anchor asserted so a drifted source fails
loudly instead of producing a subtly wrong manuscript.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from ._xml import (
    RUN_OPEN_RE,
    RUN_RE,
    T_RUN_RE,
    XML_WS,
    live_properties,
    normalize_glyphs,
    own_properties,
    set_run_text,
    visible_text,
)
from .errors import AnchorError

__all__ = [
    # re-exported: callers building a run from scratch need the same rule
    "T_RUN_RE",
    "find_normalized",
    "italicize",
    "preserve_space",
    "rep",
    "replace_in_para",
    "set_run_text",
    "subscript",
    "superscript",
]

# any <w:t ...> that does NOT carry a real xml:space="preserve". The
# attribute-tolerant form matters: a wrong-namespace w:space="preserve"
# (one misplaced set() in a build script) is meaningless to Word — which
# trims the edge space on save — while an attribute-blind regex here made
# the tag invisible to the check, so the same typo caused the fragility
# AND hid it. Found on Parental Style: ten reference-list spaces eaten in
# one author round.
_ANY_T_RE = re.compile(r"<w:t((?:\s+[^<>]*?)?)>([^<]*)</w:t>")
_XML_SPACE_RE = re.compile(r"""xml:space\s*=\s*["']preserve["']""")
_JUNK_SPACE_RE = re.compile(r"""\s+w:space\s*=\s*["']preserve["']""")
_HYPERLINK_RUN = 'w:val="Hyperlink"'


def rep(xml: str, old: str, new: str, n: int = 1, tag: str = "",
        *, normalize: bool = False) -> str:
    """Replace `old` with `new`, asserting it occurs exactly `n` times.

    The assert is the point. A silent zero-match replace is how a build
    keeps "succeeding" while quietly dropping an edit.

    `normalize` matches through Word's typographic substitutions — see
    :func:`find_normalized`. `new` is always written verbatim.
    """
    if normalize:
        spans = find_normalized(xml, old)
        if len(spans) != n:
            raise AnchorError(
                f"[{tag}] anchor found {len(spans)}x (need {n}): {old[:90]!r}")
        for start, end in reversed(spans):
            xml = xml[:start] + new + xml[end:]
        return xml
    count = xml.count(old)
    if count != n:
        raise AnchorError(
            f"[{tag}] anchor found {count}x (need {n}): {old[:90]!r}")
    return xml.replace(old, new)


def find_normalized(haystack: str, needle: str) -> list[tuple[int, int]]:
    """Offsets of `needle` in `haystack`, ignoring Word's glyph choices.

    A manuscript mixes straight and curly apostrophes, hyphens and en
    dashes, because Word's autocorrect ran on some paragraphs and not
    others — so an anchor written one way silently misses the other. On
    the AFI paper the curly form of "maintain workers' productivity"
    failed while the ASCII form matched, in the same document.

    Every substitution in ``GLYPH_MAP`` is one character for one character,
    so normalizing cannot move an offset: the spans returned index the
    ORIGINAL string and the caller writes back its own text unchanged.
    """
    hay, need = normalize_glyphs(haystack), normalize_glyphs(needle)
    out, at = [], hay.find(need)
    while at >= 0:
        out.append((at, at + len(need)))
        at = hay.find(need, at + 1)
    return out


def preserve_space(xml: str) -> tuple[str, int]:
    """Add ``xml:space="preserve"`` to bare ``<w:t>`` with edge whitespace.

    A leading or trailing space in a bare ``<w:t>`` is fragile: Word trims
    it on every open+save, so the space vanishes ("work. Only" becomes
    "work.Only") and reappears as a phantom author edit every round. Run
    this as the last step of a build.

    Only real XML whitespace counts (:data:`XML_WS`) — a leading NBSP is
    not trimmed by anything and marking it would add noise, notably to the
    NBSP-filled empty table cells Word produces.
    """
    fixed = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal fixed
        attrs, body = m.group(1), m.group(2)
        if _XML_SPACE_RE.search(attrs):
            return m.group(0)
        # w:space="preserve" is a wrong-namespace no-op Word ignores;
        # strip it so it cannot mask an unprotected edge space again
        attrs = _JUNK_SPACE_RE.sub("", attrs)
        if body != body.strip(XML_WS):
            fixed += 1
            return f'<w:t{attrs} xml:space="preserve">{body}</w:t>'
        if attrs != m.group(1):
            fixed += 1
            return f"<w:t{attrs}>{body}</w:t>"
        return m.group(0)

    return _ANY_T_RE.sub(sub, xml), fixed


def _hits(visible: str, old: str, normalize: bool) -> list[tuple[int, int]]:
    if normalize:
        return find_normalized(visible, old)
    hits, at = [], visible.find(old)
    while at >= 0:
        hits.append((at, at + len(old)))
        at = visible.find(old, at + 1)
    return hits


def _locate(para_xml: str, old: str, *, normalize: bool = False,
            within: str | None = None,
            ) -> tuple[list[re.Match[str]], list[tuple[int, int]], int, int]:
    """The paragraph's runs, their visible spans, and `old`'s ONE span.

    `within` scopes the search to the ONE span of a longer anchor, so a
    target that is not unique in the paragraph — a single letter, a
    repeated word — can still be addressed unambiguously. Both anchors
    are asserted: ambiguity is an error, never a silent first-match.

    OFFSETS ARE INTO ``visible_text(para_xml)``, which counts everything a
    reader sees — including the maths, which lives in ``m:r`` INSIDE an
    ``m:oMath`` sibling of the runs, not in a ``w:r``. Joining the runs alone
    gave a shorter string, and its offsets then meant something different from
    the ones :func:`_cite_grammar.wrap_visible_span` consumes: on a DSI §6.3
    paragraph carrying five inline symbols the citation link wrapped
    «ему (Friedman» instead of «(Friedman 1992)», four characters early. That
    function had already been fixed to count between-run content; this one had
    not, and two definitions of "visible" in one call path is one too many.
    """
    runs, spans, cursor, prev_end = [], [], 0, 0
    for r in RUN_RE.finditer(para_xml):
        cursor += len(visible_text(para_xml[prev_end:r.start()]))
        body = visible_text(r.group(0))
        runs.append(r)
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)
        prev_end = r.end()

    visible = visible_text(para_xml)
    base = 0
    if within is not None:
        scope = _hits(visible, within, normalize)
        if not scope:
            raise AnchorError(f"within={within[:60]!r} not in paragraph")
        if len(scope) > 1:
            raise AnchorError(f"within={within[:60]!r} occurs twice in "
                              "paragraph")
        base = scope[0][0]
        visible = visible[base:scope[0][1]]

    hits = _hits(visible, old, normalize)
    where = "paragraph" if within is None else f"within={within[:40]!r}"
    if not hits:
        raise AnchorError(f"{old[:60]!r} not in {where}")
    if len(hits) > 1:
        raise AnchorError(f"{old[:60]!r} occurs twice in {where}")
    return runs, spans, base + hits[0][0], base + hits[0][1]


# EG_RPrBase orders run properties; italics goes after these.
_RPR_HEAD_RE = re.compile(
    r"<w:rPr>(?:<w:rStyle [^>]*/>)?(?:<w:rFonts [^>]*/>)?"
    r"(?:<w:b/>)?(?:<w:bCs/>)?")
_ITALIC_OFF_RE = re.compile(r'<w:i w:val="(?:0|false|none)"/>')
_RUN_OPEN_RE = RUN_OPEN_RE             # the shared definition


def _run_italic(run_xml: str) -> str:
    """The same run with italics ON, schema order respected."""
    # Every question below is about the run's OWN properties. A tracked
    # formatting change nests a snapshot of the old rPr inside the live
    # one, so a run whose italics were REMOVED still contains <w:i/> in
    # that historical record — and reading the whole run reported it as
    # already italic and skipped it.
    own = own_properties(run_xml, "rPr")
    if own is None:
        m = _RUN_OPEN_RE.search(run_xml)
        assert m is not None
        return run_xml[:m.end()] + "<w:rPr><w:i/></w:rPr>" + run_xml[m.end():]
    start, end, inner = own
    live = live_properties(inner)
    if (off := _ITALIC_OFF_RE.search(live)) is not None:
        inner = inner[:off.start()] + "<w:i/>" + inner[off.end():]
    elif re.search(r"<w:i[/ >]", live):
        return run_xml                       # already italic
    else:
        m = _RPR_HEAD_RE.search(f"<w:rPr>{live}")
        assert m is not None
        at = m.end() - len("<w:rPr>")
        inner = inner[:at] + "<w:i/>" + inner[at:]
    return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]


_VERT_ALIGN_RE = re.compile(r'<w:vertAlign w:val="[^"]*"/>')
# vertAlign sorts late in EG_RPrBase: after sz/szCs, before rtl and lang.
_RPR_TAIL_RE = re.compile(r"(?=(?:<w:rtl[/ >]|<w:lang[ /]|</w:rPr>))")


def _run_vert_align(run_xml: str, val: str) -> str:
    """The same run raised or lowered, schema order respected."""
    tag = f'<w:vertAlign w:val="{val}"/>'
    # Confined to the run's OWN properties: the tail search below stops
    # at the first `</w:rPr>`, which inside a tracked formatting change
    # is the close of the nested OLD-properties snapshot — so the run
    # was raised in the historical record and left flat on the page.
    own = own_properties(run_xml, "rPr")
    if own is None:
        m = _RUN_OPEN_RE.search(run_xml)
        assert m is not None
        return run_xml[:m.end()] + f"<w:rPr>{tag}</w:rPr>" + run_xml[m.end():]
    start, end, inner = own
    live = live_properties(inner)
    if (was := _VERT_ALIGN_RE.search(live)) is not None:
        inner = inner[:was.start()] + tag + inner[was.end():]
    else:
        m = _RPR_TAIL_RE.search(live)
        at = m.start() if m is not None else len(live)
        inner = inner[:at] + tag + inner[at:]
    return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]


def _restyle(para_xml: str, text: str, style: Callable[[str], str],
             *, normalize: bool = False, within: str | None = None) -> str:
    """Apply `style` to the runs covering exactly `text`, splitting the
    runs at the span's edges so nothing outside it is touched."""
    runs, spans, at, end = _locate(para_xml, text, normalize=normalize,
                                   within=within)

    edits = []
    for (start, stop), run in zip(spans, runs, strict=True):
        if stop <= at or start >= end:
            continue
        run_xml = run.group(0)
        body = visible_text(run_xml)
        lo, hi = max(at - start, 0), min(end - start, len(body))
        if lo == 0 and hi == len(body):
            edits.append((run, style(run_xml)))
            continue
        pieces = [(body[:lo], False), (body[lo:hi], True),
                  (body[hi:], False)]
        built = "".join(
            style(set_run_text(run_xml, part)) if inside
            else set_run_text(run_xml, part)
            for part, inside in pieces if part)
        edits.append((run, built))

    out = para_xml
    for run, replacement in reversed(edits):
        out = out[:run.start()] + replacement + out[run.end():]
    return out


def italicize(para_xml: str, text: str, *, normalize: bool = False,
              within: str | None = None) -> str:
    """Set italics on exactly `text` inside one paragraph.

    The runs covering the span are split at its edges and only the
    inside pieces gain ``<w:i/>``; surrounding formatting, hyperlinks,
    bookmarks and fields survive, and the visible text is unchanged.
    Built for the refstyle "italics" finding — a reference entry whose
    journal or book title lost its italics (six entries on API10, and
    the same class on LE).

    `within` scopes an otherwise ambiguous target to one longer anchor.
    """
    return _restyle(para_xml, text, _run_italic, normalize=normalize,
                    within=within)


def subscript(para_xml: str, text: str, *, normalize: bool = False,
              within: str | None = None) -> str:
    """Lower exactly `text` into subscript inside one paragraph.

    Same run-splitting contract as :func:`italicize`. For variable
    subscripts an author typed flat — the "t" of a "Ct" that appears as
    real math elsewhere in the same sentence (Parental Style ¶100).
    A single letter is rarely unique in a paragraph, so this is the
    usual caller for `within`.
    """
    return _restyle(para_xml, text,
                    lambda r: _run_vert_align(r, "subscript"),
                    normalize=normalize, within=within)


def superscript(para_xml: str, text: str, *, normalize: bool = False,
                within: str | None = None) -> str:
    """Raise exactly `text` into superscript inside one paragraph."""
    return _restyle(para_xml, text,
                    lambda r: _run_vert_align(r, "superscript"),
                    normalize=normalize, within=within)


def replace_in_para(para_xml: str, old: str, new: str,
                    *, allow_hyperlink: bool = False,
                    normalize: bool = False) -> str:
    """Run-aware text replace inside one paragraph.

    Word splits prose across runs, so `old` rarely lives in a single
    ``<w:t>``. This matches against the paragraph's visible text, writes
    `new` into the run holding the START of the match, and empties the
    remainder of the matched span in the following runs — which preserves
    the paragraph's hyperlinks, bookmarks, footnote references and italic
    runs.

    Refuses when the receiving run is hyperlink-styled: the replacement
    would land inside the link and turn the whole sentence into a
    hyperlink, and no text-level diff would ever show it. Anchor on plain
    text outside the link, or edit the link's label separately with
    ``allow_hyperlink=True``.

    `normalize` matches through Word's typographic substitutions (curly vs
    straight quotes, dash variants) — see :func:`find_normalized`. `new` is
    written verbatim either way.
    """
    runs, spans, cursor = [], [], 0
    for r in RUN_RE.finditer(para_xml):
        body = visible_text(r.group(0))
        runs.append(r)
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)

    visible = "".join(visible_text(r.group(0)) for r in runs)
    if normalize:
        hits = find_normalized(visible, old)
        if not hits:
            raise AnchorError(
                f"replace_in_para: {old[:60]!r} not in paragraph")
        if len(hits) > 1:
            raise AnchorError(
                f"replace_in_para: {old[:60]!r} occurs twice")
        at, end = hits[0]
    else:
        at = visible.find(old)
        if at < 0:
            raise AnchorError(
                f"replace_in_para: {old[:60]!r} not in paragraph")
        if visible.find(old, at + 1) >= 0:
            raise AnchorError(f"replace_in_para: {old[:60]!r} occurs twice")
        end = at + len(old)

    edits, first = [], True
    for (start, stop), run in zip(spans, runs, strict=True):
        if stop <= at or start >= end:
            continue
        run_xml = run.group(0)
        body = visible_text(run_xml)
        tail = body[end - start:] if stop > end else ""
        if first:
            if not allow_hyperlink and _HYPERLINK_RUN in run_xml:
                raise AnchorError(
                    "replace_in_para: the match starts inside a hyperlink "
                    "run -- the replacement would bleed into the link. "
                    "Anchor on plain text outside the link.")
            edits.append((run, set_run_text(run_xml, body[:at - start] + new
                                            + tail)))
            first = False
        else:
            edits.append((run, set_run_text(run_xml, tail)))

    out = para_xml
    for run, replacement in reversed(edits):
        out = out[:run.start()] + replacement + out[run.end():]
    return out
