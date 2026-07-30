"""WordprocessingML primitives, defined once.

Every module here reads and rewrites the same handful of constructs. When
each defined its own regexes and helpers they drifted: the glyph table
existed twice and disagreed about U+00A0, so ``compare`` called a
non-breaking-space change a Word artifact while ``ingest`` treated it as
an author edit and wrote it into the source.

Internal module — the public API is :mod:`docxkit.find`,
:mod:`docxkit.edit`, :mod:`docxkit.revisions`.
"""
from __future__ import annotations

import html
import re

__all__ = [
    "GLYPH_MAP",
    "PARA_RE",
    "RUN_RE",
    "T_DEL_RE",
    "T_RE",
    "T_RUN_RE",
    "XML_WS",
    "delta_text",
    "escape",
    "matching_close",
    "normalize_glyphs",
    "set_run_text",
    "visible_text",
]

# The whitespace XML actually trims: space, tab, CR, LF. NOT Python's
# str.strip() set, which also eats U+00A0 and the other Unicode spaces —
# those are ordinary characters to a conforming XML reader, so a leading
# NBSP needs no xml:space="preserve" and flagging one is a false positive.
# (Word fills empty table cells with NBSP, so this is not a rare case.)
XML_WS = " \t\r\n"

# A paragraph. Non-greedy, so nested content stops at the first close.
PARA_RE = re.compile(r"<w:p\b[^>]*>.*?</w:p>", re.DOTALL)
# Text nodes: w:t is prose, m:t is math.
T_RE = re.compile(r"<(?:w|m):t[^>]*>([^<]*)</(?:w|m):t>")
# Text nodes including deletions — what a tracked revision spans.
T_DEL_RE = re.compile(
    r"<(?:w|m):(?:t|delText)[^>]*>([^<]*)</(?:w|m):(?:t|delText)>")
RUN_RE = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.DOTALL)
# A w:t split into (open tag, close tag) so the body can be swapped.
T_RUN_RE = re.compile(r"(<w:t[^>]*>)[^<]*(</w:t>)")

# Substitutions Word applies on save. They are artifacts of the editor,
# not author intent, so a diff that vanishes under them is not an edit and
# a build should keep the typographically correct glyph.
GLYPH_MAP = {
    "−": "-",    # MINUS SIGN -> hyphen (Word does this to math)
    "∗": "*",    # ASTERISK OPERATOR
    "’": "'",    # RIGHT SINGLE QUOTATION MARK
    "‘": "'",    # LEFT SINGLE QUOTATION MARK
    "“": '"',    # LEFT DOUBLE QUOTATION MARK
    "”": '"',    # RIGHT DOUBLE QUOTATION MARK
    "–": "-",    # EN DASH
    "—": "-",    # EM DASH
    " ": " ",    # NO-BREAK SPACE
}


def visible_text(xml: str) -> str:
    """Text a reader sees (``w:t`` + ``m:t``), deletions excluded.

    Entities are unescaped so anchors read the way the document reads:
    ``"R&D spending"`` matches a paragraph stored as ``R&amp;D spending``.
    """
    return html.unescape("".join(T_RE.findall(xml)))


def delta_text(xml: str) -> str:
    """Visible text INCLUDING ``w:delText`` — the span of a revision."""
    return html.unescape("".join(T_DEL_RE.findall(xml)))


def normalize_glyphs(text: str) -> str:
    """Fold the substitutions Word makes on save."""
    for a, b in GLYPH_MAP.items():
        text = text.replace(a, b)
    return text


def escape(text: str) -> str:
    """Escape for an XML text node."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def set_run_text(xml: str, text: str) -> str:
    """Put `text` in the fragment's first ``w:t``, blanking any others.

    Keeps the run structure and formatting intact, and adds
    ``xml:space="preserve"`` when the text has edge whitespace — a bare
    ``<w:t> x</w:t>`` loses that space on every Word save, which then
    reappears as a phantom author edit each round.
    """
    runs = list(T_RUN_RE.finditer(xml))
    if not runs:
        return xml
    for i, m in enumerate(reversed(runs)):
        idx = len(runs) - 1 - i
        body = text if idx == 0 else ""
        open_tag = m.group(1)
        if body != body.strip() and "xml:space" not in open_tag:
            open_tag = '<w:t xml:space="preserve">'
        xml = xml[:m.start()] + open_tag + escape(body) + m.group(2) \
            + xml[m.end():]
    return xml


def matching_close(xml: str, pos: int, tag: str) -> int:
    """End offset of the ``</w:tag>`` closing the element opened before pos.

    Depth-counted, and self-closing opens are skipped: a ``<w:ins/>`` with
    no content is a property-level mark, which neither nests nor closes.
    """
    open_re = re.compile(rf"<w:{tag}\b[^>]*?(/?)>")
    close = f"</w:{tag}>"
    depth = 1
    while depth:
        nxt = xml.index(close, pos)
        m = open_re.search(xml, pos, nxt)
        while m and m.group(1) == "/":
            m = open_re.search(xml, m.end(), nxt)
        if m:
            depth += 1
            pos = m.end()
        else:
            depth -= 1
            pos = nxt + len(close)
    return pos
