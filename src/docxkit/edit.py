r"""Editing ``document.xml`` as text, with the anchors asserted.

House rule across the papers: raw string surgery on WordprocessingML, never
python-docx, and every anchor asserted so a drifted source fails loudly
instead of producing a subtly wrong manuscript. The helpers here are the
ones that kept being re-implemented per paper.
"""
from __future__ import annotations

import re

from .find import P_RE, text_of

__all__ = [
    "preserve_space",
    "rep",
    "replace_in_para",
]

_T_OPEN_RE = re.compile(r"<w:t>([^<]*)</w:t>")
_RUN_RE = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.DOTALL)
_HYPERLINK_RUN = 'w:val="Hyperlink"'


def rep(xml: str, old: str, new: str, n: int = 1, tag: str = "") -> str:
    """Replace `old` with `new`, asserting it occurs exactly `n` times.

    The assert is the point. A silent zero-match replace is how a build
    keeps "succeeding" while quietly dropping an edit.
    """
    count = xml.count(old)
    if count != n:
        raise AssertionError(
            f"[{tag}] anchor found {count}x (need {n}): {old[:90]!r}")
    return xml.replace(old, new)


def preserve_space(xml: str) -> tuple[str, int]:
    """Add ``xml:space="preserve"`` to bare ``<w:t>`` with edge whitespace.

    A leading or trailing space in a bare ``<w:t>`` is fragile: Word trims
    it on every open+save, so the space vanishes ("work. Only" becomes
    "work.Only") and reappears as a phantom author edit every round. Run
    this as the last step of a build.
    """
    fixed = 0

    def sub(m: re.Match) -> str:
        nonlocal fixed
        body = m.group(1)
        if body != body.strip():
            fixed += 1
            return f'<w:t xml:space="preserve">{body}</w:t>'
        return m.group(0)

    return _T_OPEN_RE.sub(sub, xml), fixed


def replace_in_para(para_xml: str, old: str, new: str,
                    *, allow_hyperlink: bool = False) -> str:
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
    text outside the link, or edit the link's label separately.
    """
    runs = list(_RUN_RE.finditer(para_xml))
    spans, cursor = [], 0
    for r in runs:
        body = text_of(r.group(0))
        spans.append((cursor, cursor + len(body), r))
        cursor += len(body)

    visible = "".join(text_of(r.group(0)) for r in runs)
    at = visible.find(old)
    if at < 0:
        raise AssertionError(f"replace_in_para: {old[:60]!r} not in paragraph")
    if visible.find(old, at + 1) >= 0:
        raise AssertionError(f"replace_in_para: {old[:60]!r} occurs twice")
    end = at + len(old)

    out, consumed = para_xml, None
    edits = []
    for start, stop, run in spans:
        if stop <= at or start >= end:
            continue
        run_xml = run.group(0)
        if consumed is None:
            if not allow_hyperlink and _HYPERLINK_RUN in run_xml:
                raise AssertionError(
                    "replace_in_para: the match starts inside a hyperlink run "
                    "-- the replacement would bleed into the link. Anchor on "
                    "plain text outside the link.")
            head = text_of(run_xml)[:at - start]
            tail = text_of(run_xml)[end - start:] if stop > end else ""
            edits.append((run, _set_run_text(run_xml, head + new + tail)))
            consumed = True
        else:
            keep = text_of(run_xml)[end - start:] if stop > end else ""
            edits.append((run, _set_run_text(run_xml, keep)))

    for run, replacement in reversed(edits):
        out = out[:run.start()] + replacement + out[run.end():]
    return out


def _set_run_text(run_xml: str, text: str) -> str:
    """Put `text` in the run's first ``<w:t>``, blanking any others."""
    ts = list(re.finditer(r"(<w:t[^>]*>)([^<]*)(</w:t>)", run_xml))
    if not ts:
        return run_xml
    for i, m in enumerate(reversed(ts)):
        idx = len(ts) - 1 - i
        body = text if idx == 0 else ""
        open_tag = m.group(1)
        if body != body.strip() and "xml:space" not in open_tag:
            open_tag = '<w:t xml:space="preserve">'
        run_xml = (run_xml[:m.start()] + open_tag + _esc(body) + m.group(3)
                   + run_xml[m.end():])
    return run_xml


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def find_para(xml: str, sig: str) -> re.Match | None:
    """First paragraph match whose visible text contains `sig`."""
    return next((m for m in P_RE.finditer(xml) if sig in text_of(m.group(0))),
                None)
