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
from collections.abc import Iterable, Iterator

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
    "NOTE_DEF_RE",
    "PARA_RE",
    "PRINTED_CHILDREN",
    "RPR_ORDER",
    "RUN_OPEN_RE",
    "RUN_RE",
    "TEXT_PARTS",
    "T_PARTS_RE",
    "T_RE",
    "T_RUN_RE",
    "XML_WS",
    "delta_text",
    "editable_text",
    "element_spans",
    "escape",
    "escape_attr",
    "field_spans",
    "in_span",
    "internal_links",
    "live_properties",
    "matching_close",
    "normalize_glyphs",
    "overlaps",
    "own_properties",
    "printed_text",
    "run_open_before",
    "run_spans",
    "set_para_property",
    "set_run_property",
    "set_run_text",
    "span_holding",
    "split_run",
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

#: A note DEFINITION, per store: (id, body). Word renumbers note ids on
#: save, so several passes match a definition by its TEXT and then work
#: with the id beside it — the ingest remap, and the walk that finds a
#: note Compare emitted as one insertion. Written twice until
#: 2026-08-20, in the two modules that do those two things.
NOTE_DEF_RE = {
    FOOTNOTES: re.compile(
        r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>',
        re.DOTALL),
    ENDNOTES: re.compile(
        r'<w:endnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:endnote>', re.DOTALL),
}


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
# `(?<!/)>` — a SELF-CLOSING `<w:p/>` is an empty paragraph, not an open
# tag, and `[^>]*>` swallowed the slash and then ran on to the next
# paragraph's close. The span therefore began at the blank line BEFORE
# the paragraph a caller asked for: `para_slice` handed back a slice
# whose replacement deletes the author's blank line, and probe's block
# walk reported "(no table follows)" for a table sitting right under its
# caption with a spacer between.
#
# Measured 2026-08-11 over 399 manuscripts: 28 hold a self-closing
# paragraph, 87 blocks in all. `_compare_read.P_RE` had the guard by
# accident of spelling (`<w:p[ >]`) and was the only walk that was
# right; the shared definition was the one with the defect, which is
# why consolidating onto it had to be measured rather than assumed.
#
# An empty paragraph is now invisible to the walk rather than reported
# as its own: that keeps the paragraph NUMBERING every report prints
# (`¶133`) exactly as it was, where returning it would renumber every
# finding after it in those 28 documents. Nothing in this package has
# anything to do to an empty paragraph.
PARA_RE = re.compile(r"<w:p\b[^>]*(?<!/)>.*?</w:p>", re.DOTALL)
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
# `(?<!/)>` — the same guard PARA_RE carries, for the same reason and
# with the same evidence. A SELF-CLOSING `<w:r/>` is an EMPTY run, not
# an open tag: `[^>]*` swallowed the slash and paired it with the next
# `</w:r>` downstream, so the walk returned one match spanning the empty
# run AND the real run after it.
#
# Measured 2026-08-15 over 899 manuscripts: 28 carry a `<w:r/>` (32
# carry the `<w:p/>` PARA_RE was fixed for). The damage is subtler than
# the paragraph case and that is why it survived: an empty run
# contributes no visible text, so every OFFSET stayed correct and every
# text assertion passed. What was wrong was run IDENTITY — the count,
# the boundaries, and which `w:rPr` a walk believes belongs to a run,
# which is the empty one's when two are merged. Fourteen call sites in
# nine modules walk runs with this.
RUN_RE = re.compile(r"<w:r\b[^>]*(?<!/)>.*?</w:r>", re.DOTALL)
# A w:t split into (open tag, close tag) so the body can be swapped.
T_RUN_RE = re.compile(r"(<w:t[^>]*>)[^<]*(</w:t>)")
# …and the EMPTY form Word writes beside it. `<w:t/>` is what a run
# whose text was deleted looks like, and the paired pattern above cannot
# see it: `set_run_text` then rewrote nothing and reported success —
# `tables.set_cell` into a blank cell came back with the document
# unchanged (2026-08-19).
_T_EMPTY_RE = re.compile(r"<w:t\b([^>]*?)\s*/>")
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
# `(?<!/)` for the same reason as RUN_RE above: `<w:r/>` opens nothing.
RUN_OPEN_RE = re.compile(r"<w:r\b[^>]*(?<!/)>")
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
#: Every bookmark NAME. This module holds the one definition of a
#: bookmark and had three by id and none by name, so four modules grew
#: their own — `_cite_audit`, `probe`, `tracked` and `revision`, in two
#: spellings. That is the shape this package has been bitten by
#: repeatedly: the field walk existed three times with three different
#: guards, and only one of them defended against a missing end tag.
BOOKMARK_NAME_RE = re.compile(r'<w:bookmarkStart\b[^>]*w:name="([^"]+)"')
COMMENT_ID_RE = re.compile(r'<w:comment\b[^>]*w:id="(\d+)"')
#: A section's properties. `figures` reads the LAST one as the template
#: for a new section; `probe` reports how many there are.
SECTPR_RE = re.compile(r"<w:sectPr\b.*?</w:sectPr>", re.DOTALL)
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

#: The structural OMML elements — the ones that change a formula's SHAPE
#: rather than its symbols. Their sequence is an equation's skeleton, and
#: two modules computed it from two hand-kept copies of this tuple:
#: `equations.skeleton` and `compare`'s FORMULA layer, which decides
#: whether an equation was rewritten or merely re-typeset. They agreed
#: exactly on the day they were merged, which is the point — the next
#: element added to one of them would have split the two answers, and
#: the layer that reports "structure" would have stopped agreeing with
#: the function that defines it.
#:
#: A different question from :data:`MATH_OBJECTS`, which is about what
#: renders a box and may be pruned when empty; `borderBox`, `phant`,
#: `sPre` and the bare run belong there and not here.
OMML_STRUCT = ("sSub", "sSup", "sSubSup", "nary", "f", "d", "rad", "func",
               "acc", "bar", "groupChr", "limLow", "limUpp", "m", "eqArr",
               "box")
OMML_STRUCT_RE = re.compile(r"<m:(" + "|".join(OMML_STRUCT) + r")\b")

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


def in_span(pos: int, span: tuple[int, int]) -> bool:
    """Does something starting at `pos` begin inside `span`?

    Start-INCLUSIVE, end-EXCLUSIVE, and both halves are load-bearing.

    A span here is XML offsets around an element — a ``w:hyperlink``, a
    fldChar field, a bookmark pair, an ``m:oMath``. The element's own
    opening tag occupies the first bytes, so nothing can start exactly
    at `lo` for an element span and the inclusive end is free there; a
    span from :func:`field_spans` has RUN boundaries, and its begin run
    starts exactly at `lo`, so the inclusive end is the whole answer.
    At the other edge the run after an element begins exactly at `hi`,
    and it is OUTSIDE — an exclusive end is what keeps a cross-reference
    from swallowing the rest of the sentence.

    Written out eight times across `edit`, `footnotes` and
    `_cite_grammar` before it was named. Unlike :func:`run_spans` the
    copies had not drifted, which is the honest reason this is one
    function now: not a defect already paid for, but one place to state
    a convention that four of the eight sites had no test for.
    """
    lo, hi = span
    return lo <= pos < hi


def span_holding(pos: int, spans: Iterable[tuple[int, int]]
                 ) -> tuple[int, int] | None:
    """The first of `spans` that `pos` starts inside, or None."""
    return next((span for span in spans if in_span(pos, span)), None)


def overlaps(span: tuple[int, int], other: tuple[int, int]) -> bool:
    """Do two half-open spans share a position?

    The question `edit` asks of every run against the span being
    rewritten, and the ZERO-WIDTH case is the one that matters: a
    footnote reference is a run of no visible width, so its span is
    ``(s, s)``, and it overlaps only when ``s`` lies STRICTLY inside the
    other. That is what makes "the match merely abuts a marker" a
    different answer from "the match crosses it" — and crossing one is
    what moves the marker to the end of the replacement, silently,
    which is the LI7 regression the note guard exists for.
    """
    return span[0] < other[1] and other[0] < span[1]


def run_spans(para_xml: str) -> tuple[
        list[re.Match[str]], list[tuple[int, int]], int]:
    """Each ``w:r`` and the span it occupies in VISIBLE text, plus the end.

    THE run walk. Offsets index :func:`visible_text`, which counts
    everything a reader sees — including the maths, which lives in an
    ``m:r`` inside an ``m:oMath`` SIBLING of the runs, not in a ``w:r``.
    So the cursor has to advance across what sits BETWEEN the runs as
    well as across the runs themselves, or every span after an equation
    is short by its glyph count.

    That defect was diagnosed and fixed twice, in two copies of this
    walk: DSI §6.2, where a citation link wrapped the closing full stop
    instead of "(Foster et al. 2013a)" twenty characters earlier, and
    DSI §6.3, where it wrapped «ему (Friedman» four characters early. A
    THIRD copy, in `edit.insert_in_para`, never got either fix and was
    still placing content by its own count on 2026-08-16 — the same
    failure, silent, in the one function that inserts rather than
    replaces.

    One walk now. `_locate`, `insert_in_para` and `wrap_visible_span`
    all read it, which is why it lives here rather than in any of them.
    """
    runs: list[re.Match[str]] = []
    spans: list[tuple[int, int]] = []
    cursor = prev_end = 0
    for r in RUN_RE.finditer(para_xml):
        cursor += len(visible_text(para_xml[prev_end:r.start()]))
        body = visible_text(r.group(0))
        runs.append(r)
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)
        prev_end = r.end()
    return runs, spans, cursor


def editable_text(para_xml: str) -> str:
    """What a RUN-WALKING edit can address: the ``w:r`` runs' text alone.

    The other answer to "what does this paragraph say", and the package
    has always had both. :func:`visible_text` counts everything a reader
    sees, maths included; an equation's text lives in ``m:r`` inside an
    ``m:oMath`` SIBLING of the runs, so a pass that rewrites ``w:r``
    cannot address it and must not pretend otherwise.

    Which door gives which:

    * :func:`docxkit.find.para_slice`, `crossrefs`, `citations` and the
      compare layers read :func:`visible_text` — they LOCATE and report;
    * :func:`docxkit.edit.replace_in_para` reads this one — it REWRITES
      runs, and writing prose into an equation's run is a worse failure
      than not finding the phrase.

    Measured over 399 manuscripts (2026-08-11): the two readings differ
    on 256 of them, and the maths is the ONLY thing they differ over —
    both unescape entities, because this one is built from
    :func:`visible_text` per run rather than from a raw `w:t` walk.
    (`probe` had such a walk of its own and so disagreed with both; that
    is a third reading, now gone.)

    `italicize` and its siblings take the READER's offsets through
    `_locate`, which was fixed for that in the DSI §6.3 round; this
    function is the other half of that fix, named rather than inlined.
    """
    return "".join(visible_text(r.group(0))
                   for r in RUN_RE.finditer(para_xml))


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
    # An empty `w:t` arrives self-closing, and a run with one is exactly
    # the run a caller writes INTO — a blank table cell, a run an edit
    # emptied. Expanding it first is what makes the write land.
    xml = _T_EMPTY_RE.sub(r"<w:t\1></w:t>", xml)
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
#: Any hyperlink ELEMENT, whatever it points at. Public because
#: :func:`docxkit.edit.replace_in_para` needs the wider question — is
#: this run somebody's LABEL — and an external link's label is destroyed
#: exactly as easily as an internal one's. Same ghost guard.
HYPERLINK_ANY_RE = re.compile(r"<w:hyperlink\b[^>]*(?<!/)>.*?</w:hyperlink>",
                              re.DOTALL)
_FIELD_RE = re.compile(
    r'<w:fldChar\b[^>]*w:fldCharType="begin"[^>]*/>(.*?)'
    r'<w:fldChar\b[^>]*w:fldCharType="end"[^>]*/>', re.DOTALL)
# Public: the compare layers read field instructions too, and kept a
# second copy of this until it was promoted here.
INSTR_RE = re.compile(r"<w:instrText[^>]*>([^<]*)</w:instrText>")
INSTR_ANCHOR_RE = re.compile(r'HYPERLINK\s+\\l\s+"([^"]+)"')
#: Public: `_compare_read` masks a volatile field's cached RESULT, which
#: starts here, and kept its own copy of this until it was promoted.
SEPARATE_RE = re.compile(r'<w:fldChar\b[^>]*w:fldCharType="separate"[^>]*/>')
_SEPARATE_RE = SEPARATE_RE


#: The `w:t` elements a split walks past, and the pieces between
#: them. Its own pair rather than `T_RUN_RE`, which matches only a
#: `w:t` with text and would swallow an empty one whole.
_SPLIT_T_RE = re.compile(r"(<w:t\b[^>]*>)([^<]*)</w:t>")
_SPLIT_PIECE_RE = re.compile(r"(<w:t\b[^>]*>[^<]*</w:t>)")


#: Run children that PRINT something and are not `w:t`, and the
#: character each one puts on the page. None of them contributes
#: anything to :func:`visible_text`, which walks `w:t` — and that is the
#: whole difficulty: a text gate built on it cannot see one arrive or
#: leave. See :func:`printed_text`.
#:
#: `w:sym` is deliberately absent: the character it prints lives in a
#: `w:char` attribute against a font, so rendering one is a lookup and
#: not a constant, and a wrong guess here would report a difference that
#: is not there.
PRINTED_CHILDREN = {
    "noBreakHyphen": "\u2011",
    "softHyphen": "\u00ad",
    "tab": "\t",
    "br": "\n",
    "cr": "\n",
}

_PRINTED_RE = re.compile(
    r"<w:t[^>]*>([^<]*)</w:t>"
    r"|<w:(noBreakHyphen|softHyphen|tab|br|cr)\b[^>]*/?>")


def printed_text(xml: str) -> str:
    """Everything a reader SEES in `xml`, in document order.

    :func:`visible_text` walks `w:t`, which is the right reading for an
    anchor — a caller writes the words, not the typography. It is the
    wrong reading for a COMPARISON, because a no-break hyphen, a tab and
    a line break are all characters on the page that it renders as
    nothing at all.

    What that costs, measured: comparing Aging_Well before and after a
    repair that deleted six printed hyphens from inside its citations
    gave `REAL change locations: 0 | glyph-only: 0`. The tool called two
    documents identical while the printed page differed, and that is why
    the defect that put them there shipped through four rounds — every
    pass reported `TEXT: (none)` and was believed (backlog S1).

    Used by `compare`'s TEXT layer and nothing else so far. It is
    deliberately NOT what `visible_text` returns: every anchor in four
    paper trees is written against that reading, and a tab appearing in
    it would move every offset after it.
    """
    out = []
    for m in _PRINTED_RE.finditer(xml):
        if m.group(2) is not None:
            out.append(PRINTED_CHILDREN[m.group(2)])
        else:
            out.append(html.unescape(m.group(1)))
    return "".join(out)



def split_run(run_xml: str, at: int) -> tuple[str, str]:
    """One run cut at VISIBLE offset `at`, into two whole runs.

    Both halves keep the run's own `w:rPr` — that is formatting, and it
    belongs to every fragment of what it formatted. Everything else is
    CONTENT and goes to exactly one side, decided by document order:
    what stands before the cut rides left, what stands after rides
    right.

    That last sentence is the fix. Rebuilding each fragment with
    :func:`set_run_text` keeps the run's structure — which is right for
    a fragment that IS the whole run and wrong for one of three, because
    a `w:noBreakHyphen` is structure by that reading and a printed
    character by every other. `wrap_visible_span` split one run into
    before/inner/after and gave all three a copy: Aging_Well's §1 turned
    one hyphen into seven over four citation wraps, printed them inside
    the citations, and `compare` reported the before and after documents
    as IDENTICAL through four rounds (backlog S1).

    An offset past the run's visible text yields the whole run and an
    empty right half; a negative one is refused, because a caller
    computing a negative split has miscounted somewhere the halves
    cannot show.
    """
    if at < 0:
        # ValueError, not AnchorError: this module is the bottom
        # layer and imports nothing, which is why every walk in it
        # is importable from anywhere else.
        raise ValueError(f"split_run: offset {at} is before the run")
    m = RUN_OPEN_RE.search(run_xml)
    if m is None:                     # not a run: nothing to split
        return run_xml, ""
    open_tag, close = m.group(0), "</w:r>"
    body_from = m.end()
    body_to = run_xml.rfind(close)
    if body_to == -1:
        body_to = len(run_xml)
    body = run_xml[body_from:body_to]

    rpr = ""
    if (own := own_properties(run_xml, "rPr")) is not None:
        rpr = run_xml[own[0]:own[1]]
        body = body.replace(rpr, "", 1)

    # Walk the content in document order, cutting the `w:t` that spans
    # the offset. `seen` counts VISIBLE characters, so the printing
    # children above land wherever their position puts them rather than
    # wherever a length happens to fall.
    left: list[str] = []
    right: list[str] = []
    seen, cut = 0, False
    for piece in _SPLIT_PIECE_RE.split(body):
        if not piece:
            continue
        if not piece.startswith("<w:t"):
            (right if cut else left).append(piece)
            continue
        tm = _SPLIT_T_RE.fullmatch(piece)
        text = html.unescape(tm.group(2)) if tm else ""
        if cut or seen + len(text) <= at:
            (right if cut else left).append(piece)
            seen += len(text)
            continue
        head, tail = text[:at - seen], text[at - seen:]
        open_t = tm.group(1) if tm else "<w:t>"
        if head:
            left.append(_t(open_t, head))
        if tail:
            right.append(_t(open_t, tail))
        seen += len(text)
        cut = True
    if not cut and at > seen:
        pass                          # past the end: everything rides left
    return (open_tag + rpr + "".join(left) + close,
            open_tag + rpr + "".join(right) + close if right else "")


def _t(open_tag: str, text: str) -> str:
    """A `w:t` holding `text`, with the space guard `set_run_text` uses."""
    if text != text.strip() and "xml:space" not in open_tag:
        open_tag = '<w:t xml:space="preserve">'
    return f"{open_tag}{escape(text)}</w:t>"


def run_open_before(xml: str, pos: int) -> int:
    """Where the run CONTAINING `pos` opens, or -1.

    Public and here rather than in a citation module because three
    of them need it and the fourth (`edit`) is where it was reached
    through a private alias — a splice that finds its own run
    boundary with `rfind("<w:r")` matches `<w:rPr` too, which cost
    Parental_style an equation label two screens away.
    """
    starts = [m.start() for m in RUN_OPEN_RE.finditer(xml, 0, pos)]
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
            r_start = run_open_before(xml, bm.start())
            close = xml.find("</w:r>", m.end())
            if r_start < 0 or close < 0:
                continue
            r_end = close + len("</w:r>")
            out.append((r_start, r_end, xml[r_start:r_end]))
    out.sort(key=lambda span: (span[0], -span[1]))
    return out


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

    ONE part's XML, not the parts mapping almost every sibling in this
    namespace takes — and the mapping is refused by name rather than by
    a `TypeError` from inside a regex, because "expected string or
    bytes-like object, got 'dict'" names this function's line and not
    the caller's mistake. Not accepted either: which parts it would read
    is a real question (the body alone, or the notes too?) and the two
    answers differ, so the caller states it.
    """
    if not isinstance(xml, str):
        raise TypeError(
            f"internal_links takes ONE part's XML as a str, not "
            f"{type(xml).__name__} — pass parts[DOCUMENT].decode('utf-8'), "
            f"and loop over text_parts(parts) if you want the notes too")
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


#: A note REFERENCE and its id, by kind — the mark in the text, not the
#: definition. THE definition: `footnotes` and `export` had a spelling
#: each and `find` was about to write a third, which is the drift this
#: module exists to stop (see the caption regex, moved down to `find`
#: for the same reason on 2026-08-20).
#:
#: Not anchored to `/>`: a reference is empty in every file Word writes,
#: and `export`'s copy required the self-closing form while
#: `footnotes`' did not — a difference neither of them meant.
NOTE_REF_RE = {
    "footnote": re.compile(r'<w:footnoteReference\b[^>]*w:id="(-?\d+)"'),
    "endnote": re.compile(r'<w:endnoteReference\b[^>]*w:id="(-?\d+)"'),
}

#: The same thing asked the other way: the WHOLE element, for a
#: caller that replaces it rather than reading its id. `export`
#: substitutes a markdown marker in, and the id-only form above
#: would leave the `/>` behind. Two expressions, one place — which
#: is the difference from the three files that each had one.
NOTE_REF_EL_RE = {
    "footnote": re.compile(
        r'<w:footnoteReference\b[^>]*w:id="(-?\d+)"[^>]*/>'),
    "endnote": re.compile(
        r'<w:endnoteReference\b[^>]*w:id="(-?\d+)"[^>]*/>'),
}


# Everything a link can legitimately wrap while showing no text of its
# own. `w:delText` is the important one: a link inside a tracked DELETION
# is not in the final document at all, and four of them sit in LE le12.
_SHOWS_SOMETHING_RE = re.compile(
    r"<w:(?:delText|drawing|pict|object|footnoteReference|endnoteReference)\b")


def dead_links(xml: str) -> list[str]:
    """Anchors of internal links that put NOTHING on the page.

    An empty label is what an edit across a link leaves behind: the
    replacement text lands in the run holding the start of the match and
    the rest of the span is emptied, the link's own label run included.
    The paragraph then reads exactly right — the words are still there,
    as plain text — while the document carries a
    ``<w:hyperlink w:anchor="Table5">`` with nothing inside it.

    Nothing else catches this. The anchor still resolves, so the link is
    not broken, the bookmark is not orphaned, and Word opens the file
    without complaint (Parental Style 2026-08-11). Both link forms are
    read, because both fail the same way — and the FIELD form is where
    the damage was found to be sitting already.

    Measured over 397 real manuscripts: 103 hits in 49 files, and they
    are ~10 distinct defects repeated across archived versions of three
    papers. Every one inspected was real, including two in submitted
    work: LE's ``Elder2013`` citation is an empty field standing where
    the citation used to be, and five of LI's footnote citations read as
    plain "(Catalano 2003)" followed by a train of empty fields still
    holding their ``<key>txt`` bookmarks. A link inside a tracked
    deletion (four in le12) is NOT reported: it is not in the final
    document at all.

    The field grammar is shared with :func:`internal_links` and carries
    its limitation — begin-to-end matched non-greedily, so a NESTED
    field mispairs. `citations` reports that separately as DOUBLED LINK.
    """
    out: list[str] = []
    for m in _HYPERLINK_EL_RE.finditer(xml):
        if _shows_nothing(m.group(2)):
            out.append(html.unescape(m.group(1)))
    for m in _FIELD_RE.finditer(xml):
        instr = html.unescape("".join(INSTR_RE.findall(m.group(1))))
        am = INSTR_ANCHOR_RE.search(instr)
        sep = _SEPARATE_RE.search(m.group(1))
        # No `separate` means the field has no result yet — an unrendered
        # field, not an emptied one. Word fills it on open.
        if am is not None and sep is not None \
                and _shows_nothing(m.group(1)[sep.end():]):
            out.append(am.group(1))
    return out


def _shows_nothing(inner: str) -> bool:
    return (not visible_text(inner).strip()
            and not _SHOWS_SOMETHING_RE.search(inner))


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


#: ``CT_PPr`` in schema order, the paragraph's answer to
#: :data:`RPR_ORDER`. Word repairs a paragraph whose properties are out
#: of it by DROPPING the misplaced one, which is silent and arrives a
#: save later: the caption stops travelling with its table, the spacing
#: stops applying, weeks after the edit and with nothing in any diff.
PPR_ORDER = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
    "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd",
    "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
    "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
    "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
    "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
    "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl",
    "divId", "cnfStyle", "rPr", "sectPr", "pPrChange",
)
_PPR_RANK = {name: i for i, name in enumerate(PPR_ORDER)}
_CHILD_OPEN_RE = re.compile(r"<w:(\w+)\b[^>]*?(/?)>")
_PARA_OPEN_RE = re.compile(r"<w:p\b[^>]*?(/?)>")


def _own_children(inner: str) -> Iterator[tuple[str, int, int]]:
    """``(tag, start, end)`` of each DIRECT child of a properties element.

    Skipping over what a child contains is the point: ``w:tabs``,
    ``w:pBdr``, ``w:rPr`` and ``w:sectPr`` all hold elements of their
    own, and a flat scan for ``<w:...>`` reads those as siblings —
    ranking `w:top` inside `w:pBdr` as an unknown property and inserting
    the new one INSIDE the border definition.
    """
    pos = 0
    while (m := _CHILD_OPEN_RE.search(inner, pos)) is not None:
        tag = m.group(1)
        end = m.end() if m.group(2) == "/" else matching_close(
            inner, m.end(), tag)
        yield tag, m.start(), end
        pos = end


def _para_with_properties(para_xml: str, element: str) -> str:
    """`para_xml` given a `w:pPr` holding `element`, or left alone."""
    m = _PARA_OPEN_RE.match(para_xml)
    if not element or m is None:            # nothing to add, or not a `w:p`
        return para_xml
    if m.group(1) == "/":                   # `<w:p/>`: expand it
        return (para_xml[:m.start()] + f"<w:p><w:pPr>{element}</w:pPr></w:p>"
                + para_xml[m.end():])
    return (para_xml[:m.end()] + f"<w:pPr>{element}</w:pPr>"
            + para_xml[m.end():])


def set_para_property(para_xml: str, tag: str, element: str) -> str:
    """The same paragraph carrying `element` as its ``w:tag`` property.

    The paragraph's answer to :func:`set_run_property`, and the one
    place CT_PPr order is known. Four writers had their own copy of this
    — `keepNext`, `jc`, `spacing`, `pageBreakBefore` — and every defect
    the copies had, they had separately: the flag read out of a
    ``w:pPrChange`` snapshot so the live properties never got it, a
    ``w:pStyle`` written with a closing tag that the slot regex did not
    recognise, an on/off property already present with ``w:val="0"``
    that got a SECOND element beside it, and a ``<w:pPr/>`` written past
    rather than expanded — which left two ``w:pPr`` in one paragraph.

    Pass ``element=""`` to REMOVE the property.

    The existing element is taken OUT and re-inserted at its slot rather
    than replaced where it stands: a property in the wrong place is
    exactly what an older writer leaves behind, and replacing in place
    cannot repair it. For one already in its slot the two cancel.
    """
    own = own_properties(para_xml, "pPr")
    if own is None:
        return _para_with_properties(para_xml, element)

    start, end, inner = own
    if not inner and para_xml[start:end].endswith("/>"):
        # `<w:pPr/>` is real Word output, and writing past its span left
        # two `w:pPr` in one paragraph. Expand it.
        return (para_xml if not element else
                para_xml[:start] + f"<w:pPr>{element}</w:pPr>"
                + para_xml[end:])

    live = live_properties(inner)
    while (dup := next((c for c in _own_children(live) if c[0] == tag),
                       None)) is not None:
        # EVERY copy, not the first: the same property present TWICE is
        # ordinary Word output — a style turns `keepNext` off with a
        # second `w:val="0"` element beside the one that turns it on —
        # and taking one out leaves the pair this function exists to
        # repair, with the stale copy sorting FIRST.
        inner = inner[:dup[1]] + inner[dup[2]:]
        live = live_properties(inner)
    if not element:
        return para_xml[:start] + f"<w:pPr>{inner}</w:pPr>" + para_xml[end:]

    rank = _PPR_RANK.get(tag, len(PPR_ORDER))
    at = len(live)                          # before `w:pPrChange`, if any
    for name, c_start, _c_end in _own_children(live):
        if _PPR_RANK.get(name, len(PPR_ORDER)) > rank:
            at = c_start
            break
    inner = inner[:at] + element + inner[at:]
    return para_xml[:start] + f"<w:pPr>{inner}</w:pPr>" + para_xml[end:]


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

    mine = [m for m in _RPR_CHILD_RE.finditer(live) if m.group(1) == tag]
    if mine:                                # replace in place
        # Back to front, so the earlier offsets stay good. All of them:
        # a run salvaged out of two carries `w:sz` twice as often as not,
        # and leaving the second is a REMOVE that does not remove and a
        # SET that Word may read either way round.
        for m in reversed(mine[1:]):
            inner = inner[:m.start()] + inner[m.end():]
        inner = inner[:mine[0].start()] + element + inner[mine[0].end():]
        return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]

    at = len(live)                          # default: after every live child
    for m in _RPR_CHILD_RE.finditer(live):
        if _RPR_RANK.get(m.group(1), len(RPR_ORDER)) > rank:
            at = m.start()
            break

    if not element:
        return run_xml                      # nothing to remove
    inner = inner[:at] + element + inner[at:]
    return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]
