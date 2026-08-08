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
    "BOOKMARK_END_ID_RE",
    "BOOKMARK_ID_RE",
    "BOOKMARK_START_ID_RE",
    "COMMENTS",
    "COMMENT_ID_RE",
    "DOCUMENT",
    "ENDNOTES",
    "FLDCHAR_RE",
    "FOOTNOTES",
    "GLYPH_MAP",
    "INSTR_ANCHOR_RE",
    "INSTR_RE",
    "MATH_OBJECTS",
    "PARA_RE",
    "RPR_ORDER",
    "RUN_OPEN_RE",
    "RUN_RE",
    "TEXT_PARTS",
    "T_DEL_RE",
    "T_PARTS_RE",
    "T_RE",
    "T_RUN_RE",
    "XML_WS",
    "delta_text",
    "element_spans",
    "escape",
    "escape_attr",
    "internal_links",
    "live_properties",
    "matching_close",
    "normalize_glyphs",
    "own_properties",
    "set_run_property",
    "set_run_text",
    "text_parts",
    "used_prefixes",
    "visible_text",
]

# THE PART NAMES, ONCE. Every module used to spell them itself — 38
# occurrences of the body's name across 16 modules, 19 of the footnotes' —
# and the consequence was never a typo. It was that each site decided for
# itself what "the document" meant, and three of them decided wrong in the
# same week: `renumber` renumbered the body and left a footnote pointing at
# the old table, `tracked.package_counts` reported "0 pending revisions"
# for a batch that had edited only a footnote, and `compare`'s integrity
# layer read a field target out of raw XML because it never looked at the
# footnote's instruction as a whole. A name spelled in one place is a name
# that cannot mean different things in different places.
DOCUMENT = "word/document.xml"
FOOTNOTES = "word/footnotes.xml"
ENDNOTES = "word/endnotes.xml"
COMMENTS = "word/comments.xml"

#: Every part a READER sees text in, in reading order. An operation that
#: describes the document — counting revisions, renumbering an exhibit,
#: searching for a phrase — is wrong if it stops at the body.
TEXT_PARTS = (DOCUMENT, FOOTNOTES, ENDNOTES)


def text_parts(parts: dict[str, bytes]) -> list[tuple[str, str]]:
    """The (name, xml) of every text-bearing part present, in reading order.

    The iteration `TEXT_PARTS` exists for: callers that must cover the whole
    document rather than the body, without each one re-deciding which parts
    those are or whether an absent part is an error (it is not — a document
    with no footnotes simply has none).
    """
    return [(name, parts[name].decode("utf-8"))
            for name in TEXT_PARTS if name in parts]

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
# The same two separately, for the callers that must NOT mix them: the
# compare layers count prose and math apart, `equations` reads only
# math, and `_table_layout` measures only prose because an equation's
# advance is not a character width. Here rather than in each of them —
# `<w:t>` alone had three definitions and `<m:t>` two, which is C3 in
# ROBUSTNESS_PLAN and the exact class R1 was meant to close. A pattern
# that lives in two modules is a pattern that will disagree with itself.
WT_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
MT_RE = re.compile(r"<m:t[^>]*>([^<]*)</m:t>")
# Text nodes including deletions — what a tracked revision spans.
T_DEL_RE = re.compile(
    r"<(?:w|m):(?:t|delText)[^>]*>([^<]*)</(?:w|m):(?:t|delText)>")
RUN_RE = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.DOTALL)
# A w:t split into (open tag, close tag) so the body can be swapped.
T_RUN_RE = re.compile(r"(<w:t[^>]*>)[^<]*(</w:t>)")
# The same, keeping the text as its own group, for callers that rewrite
# it. THE definition: hygiene and tables each had their own copy, and a
# pattern that lives in two modules is a pattern that will disagree with
# itself — the drift that once split the glyph table between compare and
# ingest, and the reason the sibling-safe form in edit._ANY_T_RE had to
# be back-ported here by hand.
T_PARTS_RE = re.compile(r"(<w:t[^>]*>)([^<]*)(</w:t>)")
# An opening run tag. `\b` is load-bearing: without it this matches the
# `<w:rPr` INSIDE a styled run, and a field-boundary scan that cut there
# split the XML mid-element and produced a file Word would not open.
RUN_OPEN_RE = re.compile(r"<w:r\b[^>]*>")
# A bookmark id, on either end of the pair, and each end on its own.
# `[^>]*` before every w:id here is load-bearing, not defensive noise:
# XML attribute order carries no meaning, so `<w:comment w:author="A"
# w:id="7">` is exactly as valid as the id-first form Word happens to
# write. Patterns that hard-coded the order silently matched NOTHING on
# a conforming document — the comment count read zero, and building a
# comment scaffold died on max() of an empty sequence.
BOOKMARK_ID_RE = re.compile(r'<w:bookmark(?:Start|End)[^>]*w:id="(\d+)"')
BOOKMARK_START_ID_RE = re.compile(r'<w:bookmarkStart\b[^>]*w:id="(\d+)"')
BOOKMARK_END_ID_RE = re.compile(r'<w:bookmarkEnd\b[^>]*w:id="(\d+)"')
COMMENT_ID_RE = re.compile(r'<w:comment\b[^>]*w:id="(\d+)"')
# A field character, which is how Word writes a HYPERLINK before it
# churns to element form on the next save.
FLDCHAR_RE = re.compile(r'<w:fldChar\b[^>]*w:fldCharType="(\w+)"')

# OMML objects: the things that RENDER A BOX. Each is optional wherever
# it appears, so an empty one can be dropped and the markup stays valid.
#
# The slots they contain — num, den, e, sub, sup, deg, lim, fName, mr —
# are deliberately absent: those are REQUIRED by their parent's content
# model, so removing an emptied m:den turns a fraction into schema-
# invalid markup, where removing the whole emptied m:f is clean. So are
# the *Pr property elements, which never hold glyphs and belong to
# whatever survives.
MATH_OBJECTS = frozenset({
    "acc", "bar", "box", "borderBox", "d", "eqArr", "f", "func",
    "groupChr", "limLow", "limUpp", "m", "nary", "phant", "r", "rad",
    "sPre", "sSub", "sSubSup", "sSup",
})

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


def escape_attr(value: str) -> str:
    """Escape for a double-quoted XML ATTRIBUTE value.

    Not the same job as :func:`escape`, which is for text nodes and
    leaves ``"`` alone — correct there, fatal here: a name carrying a
    quote closes the attribute early and Word declares the document
    unreadable. Anything interpolated into ``w:author="..."`` comes
    through this.
    """
    return escape(value).replace('"', "&quot;")


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


# (?<!/)> — a SELF-CLOSING <w:hyperlink w:anchor=".."/> (Word leaves these
# behind as empty ghosts) must not read as an open tag: pairing one with
# the next </w:hyperlink> anywhere downstream spanned 14 paragraphs on
# Parental Style and an unwrap built on the match deleted a close tag that
# belonged to another link entirely.
_HYPERLINK_EL_RE = re.compile(
    r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>(.*?)</w:hyperlink>',
    re.DOTALL)
_HYPERLINK_GHOST_RE = re.compile(
    r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*/>')
_FIELD_RE = re.compile(
    r'<w:fldChar\b[^>]*w:fldCharType="begin"[^>]*/>(.*?)'
    r'<w:fldChar\b[^>]*w:fldCharType="end"[^>]*/>', re.DOTALL)
# Public: the compare layers read field instructions too, and kept a
# second copy of this until it was promoted here.
INSTR_RE = re.compile(r"<w:instrText[^>]*>([^<]*)</w:instrText>")
INSTR_ANCHOR_RE = re.compile(r'HYPERLINK\s+\\l\s+"([^"]+)"')
_SEPARATE_RE = re.compile(r'<w:fldChar\b[^>]*w:fldCharType="separate"[^>]*/>')


def internal_links(xml: str) -> list[tuple[str, str]]:
    """``(anchor, visible label)`` for every internal link, in BOTH forms.

    The builds write cross-references as fldChar ``HYPERLINK \\l`` fields
    (that is what Word itself produces), but Word converts them to
    ``<w:hyperlink>`` elements whenever the author saves — "form churn",
    documented on the LE rounds. An audit that reads one form misses half
    the links depending on who saved the file last, so this reads both.

    Field spans are matched begin-to-end non-greedily, which mispairs
    NESTED fields; a citation or cross-reference link never nests, so
    that stays out of scope here.
    """
    out: list[tuple[str, str]] = []
    for m in _HYPERLINK_EL_RE.finditer(xml):
        out.append((html.unescape(m.group(1)), visible_text(m.group(2))))
    for m in _FIELD_RE.finditer(xml):
        instr = html.unescape("".join(INSTR_RE.findall(m.group(1))))
        am = INSTR_ANCHOR_RE.search(instr)
        if am is None:
            continue                       # PAGEREF, REF, external link...
        sep = _SEPARATE_RE.search(m.group(1))
        label = visible_text(m.group(1)[sep.end():]) if sep else ""
        out.append((am.group(1), label))
    return out


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


def element_spans(xml: str, tag: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every ``w:tag`` at the OUTERMOST level.

    A non-greedy ``<w:tc>.*?</w:tc>`` closes on the first end tag it
    meets, which for a cell containing a nested table is the INNER
    cell's — so the outer cell reads as the inner one's content and
    every later cell in the row is lost. Questionnaires nest tables
    freely; :func:`docxkit.tables.read_all` hit this first for whole
    tables, and rows and cells need the same depth-counted walk.
    """
    spans: list[tuple[int, int]] = []
    open_re = re.compile(rf"<w:{tag}\b[^>]*?(/?)>")
    pos = 0
    while (m := open_re.search(xml, pos)) is not None:
        if m.group(1) == "/":
            pos = m.end()               # self-closing: no content, no close
            continue
        end = matching_close(xml, m.end(), tag)
        spans.append((m.start(), end))
        pos = end                       # nested elements ride along inside
    return spans


_ELEMENT_OPEN_RE = re.compile(r"<w:\w+\b[^>]*?(/?)>\s*")


def own_properties(element: str, tag: str) -> tuple[int, int, str] | None:
    """``(start, end, inner)`` of `element`'s OWN ``w:tag`` child, or None.

    Properties come first in ``CT_P``, ``CT_R`` and ``CT_Tc``, so the
    element's own ``w:pPr`` / ``w:rPr`` / ``w:tcPr`` is the child right
    after its open tag — and that is the ONLY one a writer may touch.

    Two shapes make the obvious searches wrong, and both are ordinary
    Word output rather than corner cases:

    * A tracked FORMATTING change stores the OLD properties as a
      complete snapshot NESTED inside the new ones, so ``w:rPr`` holds a
      second ``w:rPr``. A non-greedy ``<w:rPr>.*?</w:rPr>`` closes on the
      snapshot and returns an element cut in half; code that then copies
      that text into a rebuilt run emits XML Word cannot open, and code
      that inserts before its close writes the edit into the historical
      record instead of the live formatting.
    * A nested table puts another cell's ``w:tcPr`` inside this one, so a
      plain search finds the inner cell's properties first.

    The close tag is therefore found by depth count, and the search
    starts at the open tag rather than anywhere in the fragment. An empty
    ``<w:tcPr/>`` is real too: it reports ``inner == ""`` with a span
    covering the self-closing tag, so a caller can expand it in place
    rather than prepend a second properties element beside it.
    """
    open_tag = _ELEMENT_OPEN_RE.match(element)
    if open_tag is None or open_tag.group(1) == "/":
        return None
    pr = re.compile(rf"<w:{tag}\b[^>]*?(/?)>").match(element, open_tag.end())
    if pr is None:
        return None
    if pr.group(1) == "/":
        return pr.start(), pr.end(), ""
    close = matching_close(element, pr.end(), tag)
    return pr.start(), close, element[pr.end():close - len(f"</w:{tag}>")]


_ELEMENT_PREFIX_RE = re.compile(r"</?([A-Za-z][\w.-]*):")
_ATTR_PREFIX_RE = re.compile(r"\s([A-Za-z][\w.-]*):[\w.-]+=")


def used_prefixes(xml: str) -> set[str]:
    """Every namespace prefix a fragment uses, on elements or attributes.

    A fragment sliced out of a part inherits its declarations from that
    part's root and carries none of its own, so anything that parses one
    has to supply them — and first has to know which. Both callers
    needed the same answer and put different halves of it in different
    modules; what they do with the answer differs, and legitimately.
    """
    used = {m.group(1) for m in _ELEMENT_PREFIX_RE.finditer(xml)}
    used |= {m.group(1) for m in _ATTR_PREFIX_RE.finditer(xml)}
    return used - {"xmlns", "xml"}


_PROPERTY_CHANGE_RE = re.compile(r"<w:\w+PrChange\b")


def live_properties(inner: str) -> str:
    """The part of a properties element that is in force NOW.

    ``w:rPrChange`` / ``w:pPrChange`` / ``w:tcPrChange`` carries the
    formatting a tracked change replaced, and the schema puts it LAST in
    the properties element it revises, so everything before it is
    current. Take this before asking a property question — "is this run
    already italic?", "where does ``w:lang`` start?" — because the
    snapshot answers for the past and the answers differ; that is the
    whole reason it is recorded.

    The returned prefix shares offsets with `inner`, so a match found
    here indexes straight back into the full properties, and its length
    is the insertion point for a new child that sorts last.

    Writers that REPLACE an element rather than insert one mask the
    snapshot in place instead (see ``_table_layout._set_borders``):
    masking keeps the trailing bytes addressable, and it holds even in a
    document that puts the change element somewhere the schema does not.
    """
    m = _PROPERTY_CHANGE_RE.search(inner)
    return inner if m is None else inner[:m.start()]


#: ``EG_RPrBase`` in schema order. Word REJECTS a run whose properties
#: are out of it, so a new child cannot simply be appended to ``w:rPr``
#: — the position is part of the correctness. Only the members needed to
#: place one are listed; an unknown property sorts LAST, which keeps an
#: unfamiliar element from pushing a known one out of place.
RPR_ORDER = (
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
    "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
    "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
    "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
    "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
    "eastAsianLayout", "specVanish", "oMath",
)
_RPR_RANK = {name: i for i, name in enumerate(RPR_ORDER)}
_RPR_CHILD_RE = re.compile(r"<w:(\w+)\b[^>]*?(/?)>")


def set_run_property(run_xml: str, tag: str, element: str) -> str:
    """The same run carrying `element` as its ``w:tag`` run property.

    Replaces the run's existing ``w:tag`` if it has one, otherwise
    inserts it at its ``EG_RPrBase`` position. Pass ``element=""`` to
    REMOVE the property.

    Confined to the run's OWN, LIVE properties. A tracked formatting
    change nests a snapshot of the old ``w:rPr`` inside the new one, so
    a writer that searches the whole run edits the historical record and
    leaves the page exactly as it was — the bug ``_run_italic`` and
    ``_run_vert_align`` each had to learn separately.
    """
    own = own_properties(run_xml, "rPr")
    if own is None:
        if not element:
            return run_xml
        m = RUN_OPEN_RE.search(run_xml)
        if m is None:                       # not a run: nothing to carry it
            return run_xml
        return (run_xml[:m.end()] + f"<w:rPr>{element}</w:rPr>"
                + run_xml[m.end():])

    start, end, inner = own
    live = live_properties(inner)
    rank = _RPR_RANK.get(tag, len(RPR_ORDER))

    at = len(live)                          # default: after every live child
    for m in _RPR_CHILD_RE.finditer(live):
        name = m.group(1)
        if name == tag:                     # replace in place
            inner = inner[:m.start()] + element + inner[m.end():]
            return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]
        if _RPR_RANK.get(name, len(RPR_ORDER)) > rank:
            at = m.start()
            break

    if not element:
        return run_xml                      # nothing to remove
    inner = inner[:at] + element + inner[at:]
    return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]
