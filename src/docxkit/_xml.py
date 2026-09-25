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
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from typing import NamedTuple

__all__ = [
    "BOOKMARK_END_ID_RE",
    "BOOKMARK_ID_RE",
    "BOOKMARK_START_ID_RE",
    "COMMENTS",
    "COMMENT_ID_RE",
    "DEL_RE",
    "DOCUMENT",
    "ENDNOTES",
    "FLDCHAR_RE",
    "FOOTNOTES",
    "GLYPH_MAP",
    "INSTR_ANCHOR_RE",
    "INSTR_RE",
    "INSTR_REF_RE",
    "MATH_OBJECTS",
    "NOTE_DEF_RE",
    "PARA_OPEN_RE",
    "PARA_RE",
    "PRINTED_CHILDREN",
    "RPR_ORDER",
    "RUN_OPEN_RE",
    "RUN_RE",
    "SECTPR_ORDER",
    "TEXT_PARTS",
    "T_PARTS_RE",
    "T_RE",
    "T_RUN_RE",
    "WORD_ANCHOR",
    "XML_WS",
    "ZIP_STAMP",
    "Field",
    "Parts",
    "delta_text",
    "editable_text",
    "element_spans",
    "escape",
    "escape_attr",
    "field_anchors",
    "field_spans",
    "fields",
    "in_span",
    "internal_links",
    "isolate_field",
    "live_properties",
    "matching_close",
    "normalize_glyphs",
    "overlaps",
    "own_properties",
    "printed_text",
    "ref_anchor",
    "run_holds_content",
    "run_open_before",
    "run_spans",
    "set_para_property",
    "set_run_property",
    "set_run_text",
    "set_sect_property",
    "span_holding",
    "split_run",
    "text_parts",
    "used_prefixes",
    "visible_text",
    "word_minted",
    "zip_entry",
]

#: The package as this toolkit works on it: every member of the .docx
#: zip, name -> bytes, in stored order. What `package.read_parts`
#: returns and every editing path is handed. Spelt out 179 times across
#: the package before it had a name (2026-09-03), and still 160 times a
#: release later, because it was named in `package` — which `styles`,
#: `lint` and `word` sit BESIDE in the layering and may not import.
#: Defined here, at the bottom, so every module can say it; `package`
#: re-exports it, which is where the papers import it from.
type Parts = dict[str, bytes]

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

#: The timestamp every zip entry docxkit writes carries — the zip
#: epoch, the earliest a member can be stamped. `writestr` defaults to
#: `time.localtime()`, which made a docx a function of the clock:
#: measured on Aging_Well 2026-08-26, two runs of the SAME idempotent
#: pass over an unchanged manuscript produced different md5s with every
#: entry's CONTENT identical, and two runs finishing inside one second
#: produced the same one. So "byte-identical" could never prove
#: "changed nothing" — and could not be trusted to prove the opposite
#: either, which is the half that reads as intermittent.
#:
#: Word does not read these; it stamps its own on save. What they cost
#: while they moved was every cheap check built on a file hash: the
#: house idiom "a re-run that reports no work IS the check that nothing
#: was eaten", any skip-if-unchanged render cache, and deduplicating
#: rescue copies — six no-op passes in one round-close wrote six
#: distinct files of identical content, each a sync event on a
#: OneDrive-backed tree.
ZIP_STAMP = (1980, 1, 1, 0, 0, 0)


def zip_entry(name: str,
              *, compress_type: int = zipfile.ZIP_DEFLATED
              ) -> zipfile.ZipInfo:
    """A `ZipInfo` for `name`, stamped so the bytes are reproducible.

    Everything `writestr` would set from a bare string name, with the
    clock taken out of it. Defined here rather than in `package`
    because `word`'s Flat OPC writer needs the same stamp and the two
    are siblings — and a constant spelled in two places is the drift
    this module exists to prevent.
    """
    info = zipfile.ZipInfo(name, date_time=ZIP_STAMP)
    info.compress_type = compress_type
    info.external_attr = 0o600 << 16
    return info


#: A note DEFINITION, per store: (id, body). Word renumbers note ids on
#: save, so several passes match a definition by its TEXT and then work
#: with the id beside it — the ingest remap, and the walk that finds a
#: note Compare emitted as one insertion. Written twice until
#: 2026-08-20, in the two modules that do those two things.
#:
#: `(?<!/)>`, PARA_RE's guard: both readers want a note with TEXT, and
#: an EMPTY `<w:footnote w:id="3"/>` has none. Without it the `/>` read
#: as an open tag and ran on to the next note's close, so note 4's words
#: were filed under id 3 — the remap repointed a reference at the wrong
#: note, and a moved note was reported under the empty one's id
#: (2026-09-17).
NOTE_DEF_RE = {
    FOOTNOTES: re.compile(
        r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*(?<!/)>(.*?)</w:footnote>',
        re.DOTALL),
    ENDNOTES: re.compile(
        r'<w:endnote\b[^>]*w:id="(-?\d+)"[^>]*(?<!/)>(.*?)</w:endnote>',
        re.DOTALL),
}


def append_before_close(xml: str, close_tag: str, addition: str) -> str:
    """Splice `addition` in just before the LAST `close_tag`.

    Three lines, and it lived in `comments` while `hygiene` wrote the
    body out again four times — twice for `</Types>` and twice for
    `</Relationships>`, each with its own `rindex` and two-slice
    concatenation. Every copy was correct; four is the count at which a
    fifth gets written without anyone deciding to, and this package has
    already paid for that once (see the CT_PPr order entry in BACKLOG).

    `rindex`, not `index`: a part's closing tag is its last, and a
    `</Relationships>` inside a Target string would otherwise take it.
    """
    at = xml.rindex(close_tag)
    return xml[:at] + addition + xml[at:]


def text_parts(parts: Parts) -> list[tuple[str, str]]:
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
# paragraph, 87 blocks in all. `_compare_read.P_RE` was then said to
# have the guard by accident of spelling (`<w:p[ >]`) and to be the
# only walk that was right.
#
# **It did not, and it was not** — corrected 2026-08-31. `[ >]` excludes
# `<w:pPr` and the BARE `<w:p/>`, which is the form that measurement
# looked for; it does not exclude `<w:p w14:paraId="…" …/>`, which is
# the form Word actually writes for an empty paragraph. That begins
# `<w:p ` and passes the class, so the compare's walk swallowed the
# empty paragraph and the real one after it as one match. Live instance:
# LI5.docx's "References" heading, whose `w:pPr` is byte-identical to
# LI6's and which the PARAGRAPH layer then reported as differing,
# because the merged element's first child is another `w:p` and it
# therefore has no properties of its own. `_compare_read.P_RE` is this
# pattern now.
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
# One tracked deletion, whole. `(?<!/)>` keeps a self-closing `<w:del/>`
# (a paragraph-mark flag in `w:rPr`) out of the walk, and the match is
# non-greedy so two deletions in one paragraph are two spans rather than
# everything between them. `styles` and `revision._losses` each had a
# copy, and the gate that refuses a second copy could not see
# `revision/` (2026-09-24).
DEL_RE = re.compile(r"<w:del\b[^>]*(?<!/)>.*?</w:del>", re.DOTALL)
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
#
# The tag has to CLOSE, and `[^<>]` rather than `[^>]` is what makes that
# mean anything. Ending at the type's quote matched a `<w:fldChar` that
# never closed — a part that never parsed — and both walks over this
# pattern then read it as a marker: `fields` gave the field a cached
# result beginning inside the broken tag, and `_compare_read`'s masking
# landed on the right text by luck, because it rewrites `w:t` and puts a
# region opening mid-tag back unchanged (S2, 2026-09-18). Nothing refuses
# such a part on the way in — `package.malformed_parts` gates WRITES, and
# its one caller is `package.write` — so the pattern is where it stops.
#
# Requiring `>` alone does NOT stop it: `[^>]*` runs happily past the end
# of the broken tag to the next element's `>` and matches anyway, which
# is the same wrong offset one character further on. A start tag cannot
# hold a `<` in well-formed XML, so excluding it is what makes the
# truncated marker unmatchable while every real one still matches.
#
# `m.end()` is therefore past the whole marker, which is the offset both
# walks want. One form is the exception, and it is the open-tag one: a
# `begin` carrying a `w:fldData` child is written `<w:fldChar
# w:fldCharType="begin">…</w:fldChar>`, and the match ends at that
# opening tag's `>`, with the binary blob after it. Harmless to both
# readers — `fldData` rides on a `begin` and a result starts at the
# `separate` — but a reader that took `m.end()` to the next marker as a
# field's content would find it there.
FLDCHAR_RE = re.compile(r'<w:fldChar\b[^<>]*w:fldCharType="(\w+)"[^<>]*/?>')

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
#: A link element's OPENING, by anchor, with the same ghost guard: for a
#: caller that wants where a link to X STARTS rather than what it wraps.
#: `probe` and `crossrefs` compiled one each, and the ghost guard is
#: exactly the kind of detail that gets fixed in one copy.
HYPERLINK_OPEN_RE = re.compile(
    r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>')
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
#: The OTHER field a reader clicks to reach a bookmark: Word's own
#: cross-reference, which Insert ▸ Cross-reference writes as
#: ``REF _Ref211944524 \h \* MERGEFORMAT``. It renumbers itself, which is
#: why an author uses it and why turning one into a hyperlink is a
#: downgrade.
#:
#: `\b` before REF is what keeps `PAGEREF` and `NOTEREF` out — both end
#: in those three letters with no word boundary before them.
#:
#: The name is normally unquoted, unlike HYPERLINK's, but a quoted one
#: reaches here from a nested field (`IF 1 = 1 "REF Table1" ""`), and a
#: bare `([^\s\]+)` took the quote with it and produced the anchor
#: `Table1"` — a name no bookmark has, reported as a broken link and
#: carried into the loss gates as a target that vanishes on rebuild.
INSTR_REF_RE = re.compile(r'\bREF\s+(?:"([^"]+)"|([^\s\\"]+))')
#: `\h` is the switch that makes the field a hyperlink. Without it Word
#: renders the reference as static text a reader cannot click, so it is
#: not a link and must not clear a bookmark that nothing reaches — but
#: it IS still a field that depends on the bookmark, which is a
#: different question and the one `crossrefs` asks before removing one.
REF_HYPERLINK_SWITCH_RE = re.compile(r"\\h(?![A-Za-z])")

#: Public: `edit` finds a field's cached RESULT, which starts here.
#: `_compare_read` was the reason it was promoted out of a private copy
#: and is no longer a user: since 2026-09-16 it pairs a separator with
#: its own field's `begin` by DEPTH, through `FLDCHAR_RE`, because the
#: FIRST separator in a field's body belongs to a field nested in the
#: instruction half when there is one.
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

#: The first alternative is consumed and yields nothing: `w:tabs`, the
#: paragraph property that DEFINES tab stops. Its children are spelled
#: `<w:tab …/>` exactly as the tab CHARACTER a run holds is, and the
#: pattern matched them wherever they stood — so every stop a paragraph
#: defined read as a tab at its start, and a paragraph whose stops changed
#: failed `compare --expect-clean` as a TEXT edit (2026-09-17). Matched as
#: an element rather than as "inside `w:pPr`", because `w:pPrChange` holds
#: a second `w:pPr` and the snapshot's stops are the same shape one level
#: down. `(?<!/)` because `<w:tabs/>` opens nothing: read as an opening
#: tag it would pair with the next paragraph's `</w:tabs>` and every word
#: between the two would drop out of the comparison.
_PRINTED_RE = re.compile(
    r"<w:tabs\b[^>]*(?<!/)>.*?</w:tabs>"
    r"|<w:t[^>]*>([^<]*)</w:t>"
    r"|<w:(noBreakHyphen|softHyphen|tab|br|cr)\b[^>]*/?>", re.DOTALL)


def printed_text(xml: str, *,
                 printing: Mapping[str, str] = PRINTED_CHILDREN) -> str:
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

    Used by `compare`'s TEXT layer. It is deliberately NOT what
    `visible_text` returns: every anchor in four paper trees is written
    against that reading, and a tab appearing in it would move every
    offset after it.

    `printing` narrows which of :data:`PRINTED_CHILDREN` are rendered,
    and to what; a child it does not name renders as nothing. `snapshot`
    asks for the tab alone — its dump is the reading a protocol copies
    anchors out of, so it has to be `visible_text`'s plus a tab — and
    asking here rather than walking runs of its own keeps one answer to
    "is this `<w:tab/>` a character or a tab stop".
    """
    out = []
    for m in _PRINTED_RE.finditer(xml):
        if m.group(2) is not None:
            out.append(printing.get(m.group(2), ""))
        elif m.group(1) is not None:
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
    # An offset at or past the end never cuts, and everything has ridden
    # left already — there is nothing to do about it, which is why the
    # `if` that used to say so here was ten mutants and no behaviour.
    return (open_tag + rpr + "".join(left) + close,
            open_tag + rpr + "".join(right) + close if right else "")


def _t(open_tag: str, text: str) -> str:
    """A `w:t` holding `text`, with the space guard `set_run_text` uses."""
    if text != text.strip() and "xml:space" not in open_tag:
        open_tag = '<w:t xml:space="preserve">'
    return f"{open_tag}{escape(text)}</w:t>"


#: A run holding nothing at all, once its own properties are out of it.
_BARE_RUN_RE = re.compile(r"<w:r\b[^>]*(?<!/)>\s*</w:r>")


def run_holds_content(run_xml: str) -> bool:
    """Is there anything in this run besides its own ``w:rPr``?

    The question a caller of :func:`split_run` has to ask before
    throwing a half away. The LEFT half is always a whole run, even when
    nothing rode left — ``<w:r><w:rPr>…</w:rPr></w:r>``, a zero-width
    formatting island the next edit inherits — so a wrap that cuts at a
    run's own start used to drop it on sight.

    What that half can ALSO hold is every printing child standing in
    front of the run's first ``w:t``: a tab, a no-break hyphen, a line
    break ride left with it, by the document order that keeps the END of
    a wrap whole. Dropping those deleted a character from the printed
    page while :func:`visible_text` read the same on both sides — the
    other side of the S1 that :func:`split_run` exists for, where the
    same children were COPIED into every fragment instead.
    """
    if not run_xml.strip():           # the empty RIGHT half, or nothing
        return False
    own = own_properties(run_xml, "rPr")
    bare = run_xml if own is None else run_xml[:own[0]] + run_xml[own[1]:]
    return _BARE_RUN_RE.fullmatch(bare) is None


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


class Marker(NamedTuple):
    """One zero-width range marker, as :func:`markers_before` reads it.

    ``family`` pairs a start with its end — ``bookmark``, ``commentRange``,
    ``perm`` — or is ``proofErr``, whose marks carry no id and pair with
    nothing a caller can check. ``opens`` is True for a start (and a
    ``spellStart``/``gramStart``), False for an end.
    """
    start: int
    end: int
    family: str
    id: str | None
    opens: bool


_MARKER_TAG_RE = re.compile(
    r"<w:(bookmark|commentRange|perm)(Start|End)\b[^<>]*/>"
    r"|<w:proofErr\b[^<>]*/>")
_MARKER_ID_RE = re.compile(r'\bw:id="([^"]*)"')
_PROOF_OPENS_RE = re.compile(r'\bw:type="(?:spell|gram)Start"')


def markers_before(xml: str, pos: int) -> list[Marker]:
    """The zero-width markers standing right before `pos`, in document order.

    Walked back ONE TAG AT A TIME, over whitespace, and stopped by the
    first thing that is not a self-closing range marker. There is no
    window: the regex-with-a-lookback it replaces read 2,048 characters,
    and a docxkit-built manuscript (API8) carries head bookmarks of about
    2,524 characters each — redeclared namespaces — so not one fitted
    and every one was stranded (review of 2026-09-24). An attribute
    value cannot hold a raw ``<``, so the tag's own ``<`` is the last one
    before its ``/>``.
    """
    out: list[Marker] = []
    i = pos
    while True:
        j = i
        while j > 0 and xml[j - 1] in XML_WS:
            j -= 1
        if j < 2 or xml[j - 2:j] != "/>":
            break
        lt = xml.rfind("<", 0, j)
        m = _MARKER_TAG_RE.fullmatch(xml, lt, j) if lt >= 0 else None
        if m is None:
            break
        tag = m.group(0)
        idm = _MARKER_ID_RE.search(tag)
        if m.group(1):
            out.append(Marker(lt, j, m.group(1), idm.group(1) if idm else None,
                              m.group(2) == "Start"))
        else:
            out.append(Marker(lt, j, "proofErr", None,
                              bool(_PROOF_OPENS_RE.search(tag))))
        i = lt
    out.reverse()
    return out


def owned(markers: list[Marker]) -> list[bool]:
    """For each marker in a run, does it belong to what FOLLOWS the run?

    A start opens something after it, and an end whose start is earlier
    in the same run — the collapsed pair `link_all` writes and Word
    hoists out of an entry's head — is that paragraph's own too. An END
    whose start is not in the run closes something before it, and a
    proofing end has nothing to pair with: those belong to what precedes.

    The run is zero-width — one point between two paragraphs — so the
    two groups can be separated without moving either range's extent:
    Word writes `[start X][end Y]` as readily as `[end Y][start X]`
    (Misconceptions: `DeLuca2011` over the previous entry's end).
    """
    opened: set[tuple[str, str | None]] = set()
    out: list[bool] = []
    for m in markers:
        if m.opens:
            opened.add((m.family, m.id))
            out.append(True)
        else:
            out.append(m.family != "proofErr"
                       and (m.family, m.id) in opened)
    return out


class Field(NamedTuple):
    """One fldChar field, its markers paired by DEPTH.

    ``instr`` is the field's OWN instruction, joined across the runs
    Word split it into and unescaped; a NESTED field's instruction
    belongs to that field's own entry, not to this one. ``at`` is where
    that instruction starts — the offset the link readers report, a few
    runs later than the ``begin`` and always still inside the field, so
    a bookmark that legitimately wraps the whole field cannot be read as
    sitting after it. It is -1 for a field with no instruction at all.

    ``result`` is the XML between the field's own ``separate`` and its
    ``end``: what the field SHOWS, nested fields and all. It is None
    when there is no result to read — no separator (an unrendered field,
    which Word fills on open) or no end (one an edit truncated). That is
    a different answer from an EMPTY result, which is the damage
    :func:`dead_links` exists to report.

    ``start`` is the ``begin`` marker, or the instruction itself for one
    whose ``begin`` an edit cut off; ``end`` is past the ``end`` marker's
    attribute, or -1 where nothing closed the field.
    """
    at: int
    instr: str
    result: str | None
    start: int
    end: int


class _Open:
    """A field on the walk's stack: its `end` has not been reached."""
    __slots__ = ("at", "pieces", "sep_end", "start")

    def __init__(self, start: int) -> None:
        self.start = start
        self.pieces: list[str] = []
        self.at = -1
        self.sep_end = -1


def fields(xml: str) -> list[Field]:
    r"""Every fldChar field, in document order, paired by DEPTH.

    THE pairing, and the reason it is a function: fields NEST. Word
    writes a HYPERLINK inside a REF whenever the text the REF copies
    held a link of its own, and everything inside a TOC. A begin-to-end
    regex, however lazily it is matched, ends the outer field at the
    INNER field's end — and every reader built on one then read the two
    instructions as a single string. ``REF Table1 \h HYPERLINK \l
    "Appendix"`` names ONE anchor, the HYPERLINK, so `crossrefs` never
    held Table1: `unlink` removed that bookmark, reported a healthy
    count and left the REF dangling, which is the exact answer its
    ConversionGap guard exists to refuse. The same mispairing ended a
    field whose ``end`` an edit had cut at the NEXT field's end,
    swallowing that field whole, and read a switchless REF as clickable
    because the ``\h`` it was judged by belonged to the field inside it.

    An instruction outside any open field is read ON ITS OWN, as before:
    it is a field an edit cut the ``begin`` off, and it still names the
    bookmark it depends on. So is one that follows its field's
    ``separate``, which belongs to no instruction at all.

    `snapshot._record` had the only walk that got this right and kept a
    copy of it to do so; this is that walk, in the module the readers
    live in.
    """
    out: list[Field] = []
    stack: list[_Open] = []
    marks = sorted([*FLDCHAR_RE.finditer(xml), *INSTR_RE.finditer(xml)],
                   key=lambda m: m.start())
    for m in marks:
        if m.re is INSTR_RE:
            if stack and stack[-1].sep_end < 0:
                top = stack[-1]
                top.pieces.append(html.unescape(m.group(1)))
                if top.at < 0:
                    top.at = m.start()
            else:
                out.append(Field(m.start(), html.unescape(m.group(1)),
                                 None, m.start(), -1))
        elif m.group(1) == "begin":
            stack.append(_Open(m.start()))
        elif m.group(1) == "separate" and stack:
            # `FLDCHAR_RE` ends past the marker's own tag, so this is
            # where the result starts and the caller can read it as XML.
            stack[-1].sep_end = m.end()
        elif m.group(1) == "end" and stack:
            top = stack.pop()
            out.append(Field(top.at, "".join(top.pieces),
                             xml[top.sep_end:m.start()] if top.sep_end > 0
                             else None, top.start, m.end()))
    for top in stack:                  # never closed: an edit cut the end
        out.append(Field(top.at, "".join(top.pieces), None, top.start, -1))
    out.sort(key=lambda f: f.start)
    return out


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

    The pairing itself is :func:`fields`, which every reader of a field
    shares; this asks it the one question about RUNS.
    """
    out: list[tuple[int, int, str]] = []
    for f in fields(xml):
        if f.end < 0:                # no end marker: nothing to close on
            continue
        r_start = run_open_before(xml, f.start)
        close = xml.find("</w:r>", f.end)
        if r_start < 0 or close < 0:
            continue
        r_end = close + len("</w:r>")
        out.append((r_start, r_end, xml[r_start:r_end]))
    out.sort(key=lambda span: (span[0], -span[1]))
    return out


def _run_shell(xml: str, run_start: int) -> str:
    """The open tag and own ``w:rPr`` of the run opening at `run_start`."""
    close = xml.index("</w:r>", run_start) + len("</w:r>")
    run = xml[run_start:close]
    own = own_properties(run, "rPr")
    open_tag = RUN_OPEN_RE.match(run)
    assert open_tag is not None
    return run[:own[1] if own is not None else open_tag.end()]


def isolate_field(xml: str, field: Field) -> tuple[str, int, int]:
    """`xml` with `field` standing in runs of its OWN, and those runs' span.

    :func:`field_spans` answers with RUN boundaries, and Word writes a
    field's ``begin`` into the run that already holds the words before it
    as often as not, and its ``end`` into the run carrying the words
    after. A caller that wants the FIELD — to put a bookmark round it, or
    to rebuild it as an element — got the prose too: `<key>txt` wrapped
    the whole sentence, and `respan_link` refused a repair it could make
    (backlog S3, 2026-09-18, D2 and D3).

    So the run holding each marker is SPLIT at the marker when anything a
    reader sees shares it — both halves keep the run's own ``w:rPr``, as
    :func:`split_run` does — and left alone when the marker was all it
    held. Nothing visible moves; the returned ``(start, end)`` is then a
    run-bounded span holding the field and nothing else. `field` must be
    one of ``fields(xml)`` with an ``end`` marker.
    """
    if field.end < 0:
        raise ValueError("isolate_field: the field has no end marker")
    close = "</w:r>"
    # The END first: splitting there does not move the begin's offsets.
    end = xml.index(close, field.end) + len(close)
    shell = _run_shell(xml, run_open_before(xml, field.end))
    if run_holds_content(shell + xml[field.end:end]):
        xml = xml[:field.end] + close + shell + xml[field.end:]
        end = field.end + len(close)

    begin_run = run_open_before(xml, field.start)
    if not run_holds_content(xml[begin_run:field.start] + close):
        return xml, begin_run, end
    shell = _run_shell(xml, begin_run)
    xml = xml[:field.start] + close + shell + xml[field.start:]
    shift = len(close) + len(shell)
    return xml, field.start + len(close), end + shift


#: The stand-in for a bookmark Word minted itself, where two versions of
#: one document are COMPARED. Word re-mints these on every Compare and
#: on every field update, so the name is not a fact about the document:
#: comparing it reports a loss and a gain on every build.
WORD_ANCHOR = "<Word's own anchor>"


def word_minted(name: str) -> bool:
    """Is this a bookmark Word mints and re-mints for itself?

    Word reserves the leading underscore — `_Ref211944524` for a
    cross-reference target, `_Toc…` for a heading in a table of
    contents, `_Hlk…` for a place it tracked. The name is regenerated,
    so it means nothing across two versions of a document: a gate that
    compares it by name reports a bookmark lost and another gained
    every time Compare runs, and `build` refuses on that.

    The same rule reads the other way in `_cite_audit._reached`, where
    the reserved prefix is what says two names are ONE destination.
    """
    return name.startswith("_")


def ref_anchor(instr: str, *, clickable: bool = True) -> str | None:
    r"""The bookmark a Word cross-reference field targets, or None.

    Two questions, one field, and they do not have the same answer.
    ``clickable`` (the default) asks what a READER can reach: a ``REF``
    without the ``\h`` switch renders as static text, so counting it as
    a link cleared bookmarks that nothing reaches and suppressed the
    findings that say so. ``clickable=False`` asks what DEPENDS on the
    bookmark, which is what `crossrefs` needs before removing one —
    a switchless field still breaks into "Error! Reference source not
    found" when its target goes.
    """
    m = INSTR_REF_RE.search(instr)
    if m is None:
        return None
    if clickable and not REF_HYPERLINK_SWITCH_RE.search(instr):
        return None
    return m.group(1) or m.group(2)


def field_anchors(xml: str, *,
                  clickable: bool = True) -> list[tuple[str, int]]:
    r"""``(anchor, offset of the instruction)`` for every FIELD-form link.

    Both field forms: ``HYPERLINK \l "X"`` and Word's own ``REF X \h``.
    ONE reader of both, because `crossrefs` kept a second regex that
    knew only the first — so `unlink` reported "removed 2", deleted the
    exhibit bookmarks and left the REF fields live and dangling, which
    is the exact answer its ConversionGap guard exists to refuse.

    The offset is the INSTRUCTION's, not the field's ``begin``: a few
    runs late, and always still inside the field, so a bookmark that
    legitimately wraps the whole field cannot be read as sitting after
    it. Instructions are joined across runs before matching, because
    Word splits them at rsid boundaries — and an instruction outside any
    begin/end pair is read on its own, so a field truncated by an edit
    still reports the bookmark it depends on.

    One entry per FIELD, which is what pairing by depth buys: a field
    nested in another names its own bookmark at its own offset, instead
    of both instructions being read as one string that names whichever
    anchor comes first.
    """
    out: list[tuple[str, int]] = []
    for f in fields(xml):
        hm = INSTR_ANCHOR_RE.search(f.instr)
        name = hm.group(1) if hm else ref_anchor(f.instr, clickable=clickable)
        if name is not None:
            out.append((name, f.at))
    return out


def internal_links(xml: str) -> list[tuple[str, str]]:
    """``(anchor, visible label)`` for every internal link, in BOTH forms.

    The builds write cross-references as fldChar ``HYPERLINK \\l`` fields
    (that is what Word itself produces), but Word converts them to
    ``<w:hyperlink>`` elements whenever the author saves — "form churn",
    documented on the LE rounds. An audit that reads one form misses half
    the links depending on who saved the file last, so this reads both.

    Fields NEST, and are paired by depth in :func:`fields`: a link
    inside another field is a link of its own, with its own label, and
    the field around it keeps its own anchor.

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
    for f in fields(xml):
        if f.end < 0:
            # A field an edit cut the `begin` or the `end` off is not
            # something a reader can click, whatever bookmark its
            # instruction still names. `field_anchors` answers that
            # other question — what would BREAK if the bookmark went.
            continue
        # Three forms reach a bookmark, not two. The third is Word's own
        # CROSS-REFERENCE — `REF _Ref211944524 \h` — and reading only the
        # first two made `citations` report four working mentions on HCW
        # as "the mention reaches nothing", while `crossrefs` called all
        # twenty exhibits linked: one tool said broken, the other said
        # fine, and neither was reading what a reader clicks
        # (2026-08-22). The repair the finding implied would have traded
        # Word's automatic renumbering for a static label.
        hm = INSTR_ANCHOR_RE.search(f.instr)
        anchor = hm.group(1) if hm else ref_anchor(f.instr)
        if anchor is None:
            continue        # PAGEREF, external link, TOC, no \h…
        out.append((anchor, visible_text(f.result) if f.result else ""))
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

    The field walk is :func:`fields`, shared with :func:`internal_links`
    — and a field's result ends at ITS end, not at the first one after
    it. Cut short at a NESTED field's end, a label sitting after that
    field was invisible and its link read as empty: damage reported
    where there is none, which is the costly direction here.
    """
    out: list[str] = []
    for m in _HYPERLINK_EL_RE.finditer(xml):
        if _shows_nothing(m.group(2)):
            out.append(html.unescape(m.group(1)))
    for f in fields(xml):
        am = INSTR_ANCHOR_RE.search(f.instr)
        # No result means the field has no result YET — no separator, an
        # unrendered field Word fills on open, or no end. Not the same
        # question as a result that shows nothing.
        if am is not None and f.result is not None \
                and _shows_nothing(f.result):
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
    pos = 0                             # from the top of the fragment
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
#: A paragraph's opening tag, capturing the slash of a self-closing
#: `<w:p/>` so a caller can tell an empty paragraph from one that opens.
PARA_OPEN_RE = re.compile(r"<w:p\b[^>]*?(/?)>")


def _own_children(inner: str) -> Iterator[tuple[str, int, int]]:
    """``(tag, start, end)`` of each DIRECT child of a properties element.

    Skipping over what a child contains is the point: ``w:tabs``,
    ``w:pBdr``, ``w:rPr`` and ``w:sectPr`` all hold elements of their
    own, and a flat scan for ``<w:...>`` reads those as siblings —
    ranking `w:top` inside `w:pBdr` as an unknown property and inserting
    the new one INSIDE the border definition.
    """
    pos = 0                             # from the first of those children
    while (m := _CHILD_OPEN_RE.search(inner, pos)) is not None:
        tag = m.group(1)
        end = m.end() if m.group(2) == "/" else matching_close(
            inner, m.end(), tag)
        yield tag, m.start(), end
        pos = end


def _para_with_properties(para_xml: str, element: str) -> str:
    """`para_xml` given a `w:pPr` holding `element`, or left alone."""
    m = PARA_OPEN_RE.match(para_xml)
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


#: ``CT_SectPr`` in schema order. The header and footer references come
#: first, in any order among themselves; everything after them has one
#: place. `titlePg` written at the END of a section — where a
#: `.replace("</w:sectPr>", ...)` puts it — sits after `w:docGrid`, which
#: is out of order.
SECTPR_ORDER = (
    "headerReference", "footerReference", "footnotePr", "endnotePr",
    "type", "pgSz", "pgMar", "paperSrc", "pgBorders", "lnNumType",
    "pgNumType", "cols", "formProt", "vAlign", "noEndnote", "titlePg",
    "textDirection", "bidi", "rtlGutter", "docGrid", "printerSettings",
    "sectPrChange",
)
_SECTPR_RANK = {name: i for i, name in enumerate(SECTPR_ORDER)}
_SECTPR_OPEN_RE = re.compile(r"<w:sectPr\b[^>]*?(/?)>")


def set_sect_property(sect_xml: str, tag: str, element: str) -> str:
    """The same `w:sectPr` carrying `element` as its ``w:tag`` property.

    The section's answer to :func:`set_para_property`: every existing
    ``w:tag`` child is taken out and `element` goes in at its
    :data:`SECTPR_ORDER` slot, so a property an older writer put in the
    wrong place is repaired rather than kept. ``element=""`` removes the
    property. For a header or footer REFERENCE, which a section holds
    one of per type, use a writer that knows the type — this replaces
    every reference of the tag.
    """
    m = _SECTPR_OPEN_RE.match(sect_xml)
    if m is None:
        raise ValueError("set_sect_property: not a w:sectPr")
    if m.group(1) == "/":                   # `<w:sectPr/>`: expand it
        return (sect_xml if not element else
                m.group(0)[:-2] + ">" + element + "</w:sectPr>"
                + sect_xml[m.end():])
    close = sect_xml.rindex("</w:sectPr>")
    inner = sect_xml[m.end():close]
    while (dup := next((c for c in _own_children(inner) if c[0] == tag),
                       None)) is not None:
        inner = inner[:dup[1]] + inner[dup[2]:]
    if element:
        rank = _SECTPR_RANK.get(tag, len(SECTPR_ORDER))
        at = len(inner)
        for name, c_start, _c_end in _own_children(inner):
            if _SECTPR_RANK.get(name, len(SECTPR_ORDER)) > rank:
                at = c_start
                break
        inner = inner[:at] + element + inner[at:]
    return m.group(0) + inner + sect_xml[close:]


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


def set_run_property(run_xml: str, tag: str, element: str) -> str:
    """The same run carrying `element` as its ``w:tag`` run property.

    Replaces the run's existing ``w:tag`` if it has one, otherwise
    inserts it at its ``EG_RPrBase`` position. Pass ``element=""`` to
    REMOVE the property. An existing one written PAIRED
    (``<w:b></w:b>``, which is the same element as ``<w:b/>``) is taken
    whole, close tag and all.

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

    # `_own_children`, as the paragraph writer does it, and not a scan
    # for opening tags: `<w:b></w:b>` is the same element as `<w:b/>` and
    # Word writes both, and a scan matches only the OPEN tag of the pair.
    # Cutting at its end left the `</w:b>` standing — properties that no
    # longer parse, which Word reports as unreadable content, from a call
    # that returned a string and looked like it had worked.
    # `set_para_property` was fixed for exactly this shape; this writer,
    # the same shape by its own docstring, was not.
    mine = [(c_start, c_end) for name, c_start, c_end in _own_children(live)
            if name == tag]
    if mine:                                # replace in place
        # Back to front, so the earlier offsets stay good. All of them:
        # a run salvaged out of two carries `w:sz` twice as often as not,
        # and leaving the second is a REMOVE that does not remove and a
        # SET that Word may read either way round.
        for c_start, c_end in reversed(mine[1:]):
            inner = inner[:c_start] + inner[c_end:]
        inner = inner[:mine[0][0]] + element + inner[mine[0][1]:]
        return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]

    at = len(live)                          # default: after every live child
    for name, c_start, _c_end in _own_children(live):
        if _RPR_RANK.get(name, len(RPR_ORDER)) > rank:
            at = c_start
            break

    if not element:
        return run_xml                      # nothing to remove
    inner = inner[:at] + element + inner[at:]
    return run_xml[:start] + f"<w:rPr>{inner}</w:rPr>" + run_xml[end:]
