r"""Editing ``document.xml`` as text, with the anchors asserted.

House rule across the papers: raw string surgery on WordprocessingML,
never python-docx, and every anchor asserted so a drifted source fails
loudly instead of producing a subtly wrong manuscript.
"""
from __future__ import annotations

import re

from ._xml import (
    RUN_RE,
    T_RUN_RE,
    XML_WS,
    normalize_glyphs,
    set_run_text,
    visible_text,
)
from .errors import AnchorError

__all__ = [
    # re-exported: callers building a run from scratch need the same rule
    "T_RUN_RE",
    "find_normalized",
    "preserve_space",
    "rep",
    "replace_in_para",
    "set_run_text",
]

_BARE_T_RE = re.compile(r"<w:t>([^<]*)</w:t>")
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
        body = m.group(1)
        if body != body.strip(XML_WS):
            fixed += 1
            return f'<w:t xml:space="preserve">{body}</w:t>'
        return m.group(0)

    return _BARE_T_RE.sub(sub, xml), fixed


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
