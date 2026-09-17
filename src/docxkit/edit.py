r"""Editing ``document.xml`` as text, with the anchors asserted.

House rule across the papers: raw string surgery on WordprocessingML,
never python-docx, and every anchor asserted so a drifted source fails
loudly instead of producing a subtly wrong manuscript.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from html import unescape
from typing import NamedTuple

from ._xml import (
    _FIELD_RE,
    _HYPERLINK_EL_RE,
    _T_EMPTY_RE,
    HYPERLINK_ANY_RE,
    INSTR_ANCHOR_RE,
    INSTR_RE,
    RUN_OPEN_RE,
    RUN_RE,
    SEPARATE_RE,
    T_RUN_RE,
    XML_WS,
    editable_text,
    escape,
    field_spans,
    in_span,
    internal_links,
    live_properties,
    normalize_glyphs,
    overlaps,
    own_properties,
    run_open_before,
    run_spans,
    set_run_property,
    set_run_text,
    span_holding,
    visible_text,
)
from .errors import AnchorError

__all__ = [
    "RUN_RE",
    "T_RUN_RE",
    "AnchorError",
    "editable_text",
    "field_spans",
    "find_normalized",
    "insert_in_para",
    "internal_links",
    "is_field_run",
    "italicize",
    "own_properties",
    "preserve_space",
    "relabel_link",
    "remove_link",
    "remove_links",
    "rep",
    "replace_in_para",
    "replace_keeping_links",
    "rstrip_para",
    "run_spans",
    "set_run_properties",
    "set_run_text",
    "subscript",
    "superscript",
    "visible_text",
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
#: The regions an insertion must not land inside, as
#: (spans, is-it-allowed, what a refusal should say).
_Protected = tuple[tuple[list[tuple[int, int]], bool, str], ...]
#: A note's MARKER in the body: the element that says "footnote 11 is
#: anchored here". It carries no visible text at all, which is the whole
#: problem — a visible-text match spans one with nothing to see. The id
#: is read separately because attribute order is not meaningful in XML
#: and a `w:id`-second spelling has already read as zero once here.
_NOTE_REF_RE = re.compile(r"<w:(footnote|endnote|comment)Reference\b[^>]*/>")
_ID_ATTR_RE = re.compile(r'\bw:id="([^"]+)"')


def _note_in(run_xml: str) -> str | None:
    """``"footnote 11"`` if this run anchors a note, else None."""
    if (m := _NOTE_REF_RE.search(run_xml)) is None:
        return None
    nid = _ID_ATTR_RE.search(m.group(0))
    return f"{m.group(1)} {nid.group(1)}" if nid else m.group(1)


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
    runs, spans, _cursor = run_spans(para_xml)

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
#: Any `w:i`, on or off, in either spelling Word writes.
_ITALIC_ANY_RE = re.compile(r"<w:i(?: [^>]*)?(?:/>|></w:i>)")
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
    if (hits := list(_ITALIC_ANY_RE.finditer(live))):
        if len(hits) == 1 and not _ITALIC_OFF_RE.fullmatch(hits[0].group(0)):
            return run_xml                   # already italic
        # EVERY copy: `w:i` twice in one `w:rPr` is invalid and does
        # happen — a style states it off and a writer that could not see
        # that put a second beside it — and taking one out leaves the
        # stale element sorting FIRST, which is the reading Word takes.
        for m in reversed(hits[1:]):
            inner = inner[:m.start()] + inner[m.end():]
        inner = inner[:hits[0].start()] + "<w:i/>" + inner[hits[0].end():]
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
    if (hits := list(_VERT_ALIGN_RE.finditer(live))):
        for m in reversed(hits[1:]):         # every copy — see _run_italic
            inner = inner[:m.start()] + inner[m.end():]
        inner = inner[:hits[0].start()] + tag + inner[hits[0].end():]
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
        if not overlaps((start, stop), (at, end)):
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


def _locate_anchor(para_xml: str, visible: str, old: str, *,
                   normalize: bool, who: str = "replace_in_para",
                   ) -> tuple[int, int]:
    """Where `old` sits in the paragraph's EDITABLE text.

    Raises rather than returning a sentinel, and names the confusing
    case when it is the reason: the phrase IS in the paragraph as a
    reader (and `docxkit text`, and `para_slice`) sees it, and is not
    addressable by a run walk because it spans an equation.
    """
    def missing(reason: str) -> AnchorError:
        if old in visible_text(para_xml):
            return AnchorError(
                f"{who}: {old[:60]!r} {reason} — it IS in the "
                f"paragraph a reader sees, but it spans an equation "
                f"(m:oMath), which this pass rewrites nothing inside. "
                f"Anchor on prose either side of the maths.")
        return AnchorError(f"{who}: {old[:60]!r} {reason}")

    if normalize:
        hits = find_normalized(visible, old)
        if not hits:
            raise missing("not in paragraph")
        if len(hits) > 1:
            raise AnchorError(
                f"{who}: {old[:60]!r} occurs twice")
        return hits[0]
    at = visible.find(old)
    if at < 0:
        raise missing("not in paragraph")
    if visible.find(old, at + 1) >= 0:
        raise AnchorError(f"{who}: {old[:60]!r} occurs twice")
    return at, at + len(old)


def _label_end(idx: int, runs: list[re.Match[str]],
               spans: list[tuple[int, int]],
               link_spans: list[tuple[int, int]]) -> int:
    """Where the VISIBLE label the idx-th run belongs to ENDS.

    Element form first: every run inside the ``w:hyperlink`` is part of
    one label, and Word fragments a label across runs as freely as it
    fragments prose. Field form has no element to ask, so the label is
    the run's styled neighbours — the same answer for the same reason.

    The END alone, not the span. This returned a ``(start, end)`` pair
    and walked LEFT to find the start, which no caller ever read — the
    one question asked of it is "does the match run on past the label",
    and a match reaching this guard already starts inside one. Mutation
    testing found it: 58 survivors sat in `replace_in_para` on
    2026-08-15, and hand-mutating the leftward walk changed nothing
    observable, because nothing observed it.
    """
    run = runs[idx]
    if (element := span_holding(run.start(), link_spans)) is not None:
        inside = [i for i, r in enumerate(runs)
                  if in_span(r.start(), element)]
        return spans[inside[-1]][1]

    def styled(i: int) -> bool:
        return 0 <= i < len(runs) and _HYPERLINK_RUN in runs[i].group(0)

    hi_i = idx
    while styled(hi_i + 1):
        hi_i += 1
    return spans[hi_i][1]


def _refuse_crossed_note(runs: list[re.Match[str]],
                         spans: list[tuple[int, int]],
                         match: tuple[int, int], new: str,
                         who: str = "replace_in_para") -> None:
    """Refuse a match that CROSSES a footnote/endnote/comment reference.

    A note reference is a run of ZERO visible width, so overlapping the
    match is exactly "the marker sits strictly inside it" — a match that
    merely ABUTS one does not touch it and is not refused. A single
    touched run cannot move a marker either: the text is rewritten where
    it stands and nothing is emptied after it, which is why this asks
    for more than one touched run before it looks.
    """
    touched = [i for i, span in enumerate(spans) if overlaps(span, match)]
    if len(touched) <= 1:
        return
    for i in touched:
        if (note := _note_in(runs[i].group(0))) is not None:
            raise AnchorError(
                f"{who}: the match crosses {note} — the "
                f"replacement goes into the run holding the start of "
                f"the match and the text after the marker is emptied, "
                f"so the marker MOVES to the end of {new[:30]!r}. "
                f"Nothing downstream shows that: the words read in "
                f"the same order and the note still resolves. Anchor "
                f"on one side of the marker, or pass allow_notes=True.")


def replace_in_para(para_xml: str, old: str, new: str,
                    *, allow_hyperlink: bool = False,
                    grow_link_label: bool = False,
                    allow_notes: bool = False,
                    normalize: bool = False) -> str:
    """Run-aware text replace inside one paragraph.

    Word splits prose across runs, so `old` rarely lives in a single
    ``<w:t>``. This matches against the paragraph's visible text, writes
    `new` into the run holding the START of the match, and empties the
    remainder of the matched span in the following runs — which preserves
    the paragraph's hyperlinks, bookmarks, footnote references and italic
    runs.

    The anchor is matched against :func:`docxkit._xml.editable_text` —
    the ``w:r`` runs' text — which is NOT what `find.para_slice` and
    `docxkit text` show you. An equation's text lives in an ``m:r``
    inside a sibling ``m:oMath``, so a phrase spanning maths is findable
    there and not here; the refusal says so when that is the reason.

    Refuses when the match TOUCHES a hyperlink, in either of the two ways
    it can, because both are invisible to a text diff:

    * the match STARTS in a link — the replacement lands inside it and
      turns the whole sentence into a hyperlink;
    * the match CROSSES one — the following runs are emptied, and the
      link's own label run is one of them, so the document keeps a
      ``<w:hyperlink w:anchor="Table5">`` with nothing inside it. The
      words are still on the page, as plain text, and nothing catches it:
      the anchor resolves, so `citations` and `crossrefs` both pass, and
      `lint` is clean (Parental Style 2026-08-11). Split the replacement
      into one call on each side of the link.

    The label is found by the run's style AND by the enclosing element:
    a field-form link (``fldChar``/``instrText``) styles its result run,
    while an element-form one may state no style at all.

    Anchor on plain text outside the link, or pass ``allow_hyperlink=True``
    to edit the link's label deliberately.

    ``allow_hyperlink`` permits the match to TOUCH a link; it does not
    permit the link to grow. The write puts the whole replacement into
    the run holding the start of the match, so when that run is a label
    and the match runs on past the link, the label ends up owning words
    that were never the link's: the Parental Style Table 4 caption
    opened with a ``Table4txt`` back-link labelled "Table 4", and one
    ``allow_hyperlink=True`` call on the whole caption rendered two
    thirds of it blue and underlined. Every gate passed — the anchor
    still resolves and the words still read correctly — exactly as in
    the emptying case above. So a match that starts in a label and ends
    outside it is refused; ``grow_link_label=True`` is the deliberate
    retitle, and the usual answer is to replace only a span lying wholly
    on one side of the link.

    Refuses for the same reason when the match CROSSES a footnote,
    endnote or comment REFERENCE. A hyperlink at least has a label to
    see; a ``w:footnoteReference`` carries no visible text at all, so
    the anchor reads as contiguous prose and nothing signals that a
    marker sits inside it. The reference itself survives — it lives in
    its own run, which `set_run_text` leaves alone — but the whole
    replacement is written into the run holding the START of the match
    and the text after the marker is emptied, so the MARKER MOVES to the
    end of the new text. On LI7 (2026-08-15) the anchor ``"). The left
    panel of "`` spanned footnote 11 in the Figure 1 paragraph; Word's
    Compare then re-emitted footnote 12 — a note holding an equation —
    as an insertion with no matching deletion, and reject-all stopped
    reproducing the baseline, so the author could not refuse it. `lint`
    was clean, `compare` reported no hyperlink difference, and the
    caller's own assertion passed because the words really were in that
    order. Anchor after the marker, or pass ``allow_notes=True``.

    `normalize` matches through Word's typographic substitutions (curly vs
    straight quotes, dash variants) — see :func:`find_normalized`. `new` is
    written verbatim either way.
    """
    runs, spans = _run_walk(para_xml)

    # `editable_text`, NOT `visible_text`: this pass rewrites w:r runs,
    # and an equation's text is in an m:r inside a sibling m:oMath. The
    # two readings differ on 256 of 399 manuscripts. Counting the maths
    # here would find phrases this function then could not write, which
    # is the worse failure — see the note in `_xml.editable_text`.
    visible = editable_text(para_xml)

    at, end = _locate_anchor(para_xml, visible, old, normalize=normalize)
    return _rewrite_span(para_xml, runs, spans, (at, end), new,
                         allow_hyperlink=allow_hyperlink,
                         grow_link_label=grow_link_label,
                         allow_notes=allow_notes)


def _run_walk(para_xml: str) -> tuple[list[re.Match[str]],
                                      list[tuple[int, int]]]:
    """Each ``w:r`` and its span in EDITABLE text — the runs alone.

    Not :func:`run_spans`, whose cursor also crosses the maths between
    runs: these offsets index :func:`editable_text`, the string
    `replace_in_para` matches in, and a span that counted an equation
    would write one glyph early per maths character before it.
    """
    runs: list[re.Match[str]] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for r in RUN_RE.finditer(para_xml):
        body = visible_text(r.group(0))
        runs.append(r)
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)
    return runs, spans


def _rewrite_span(para_xml: str, runs: list[re.Match[str]],
                  spans: list[tuple[int, int]], match: tuple[int, int],
                  new: str, *, allow_hyperlink: bool, grow_link_label: bool,
                  allow_notes: bool, who: str = "replace_in_para") -> str:
    """Write `new` over the EDITABLE span `match`: the write of
    :func:`replace_in_para`, addressed by offset rather than by text.

    Split out so that a caller which already KNOWS where the words are —
    :func:`replace_keeping_links`, editing the pieces between labels —
    need not find them again by a text search, which cannot tell two
    equal pieces of one paragraph apart. Every guard is the same one:
    this is where they live.

    **A field's result is a label** as a hyperlink's is — the one
    definition, :func:`_label_spans_in`, that `replace_keeping_links`
    edits around. Until 2026-09-17 this asked only for the Hyperlink
    style or a ``w:hyperlink`` element, and Word's own cross-reference
    (``REF _Ref… \\h``) writes an unstyled result: the match emptied it
    and put its words in the run before, and the next field update wrote
    "Table 3" back beside the new text. A field-only label gets its own
    refusal wording and the same ``allow_hyperlink`` opt-in; everything
    the old question caught is refused exactly as before.

    **A match may not CROSS an equation** (:func:`_refuse_crossed_maths`).
    """
    at, end = match
    link_spans = [(m.start(), m.end())
                  for m in HYPERLINK_ANY_RE.finditer(para_xml)]
    label_of = {i: label for label in _label_spans_in(para_xml, runs, spans)
                for i in range(label.first, label.last + 1)}

    def a_hyperlink(run: re.Match[str]) -> bool:
        return (_HYPERLINK_RUN in run.group(0)
                or span_holding(run.start(), link_spans) is not None)

    def labels_a_link(idx: int, run: re.Match[str]) -> bool:
        return a_hyperlink(run) or idx in label_of

    def field_only(idx: int, run: re.Match[str]) -> str | None:
        """The field's instruction, when only the field makes it a label."""
        label = label_of.get(idx)
        if a_hyperlink(run) or label is None or label.field is None:
            return None
        lo, hi = label.field
        return " ".join(unescape(t).strip()
                        for t in INSTR_RE.findall(para_xml[lo:hi]))[:40]

    def label_end(idx: int, run: re.Match[str]) -> int:
        if field_only(idx, run) is not None:
            return label_of[idx].end
        return _label_end(idx, runs, spans, link_spans)

    if not allow_notes:
        _refuse_crossed_note(runs, spans, (at, end), new, who)
    if not allow_hyperlink:
        _refuse_crossed_empty_field(para_xml, runs, spans, (at, end), new,
                                    who=who)
    _refuse_crossed_maths(para_xml, runs, spans, (at, end), new, who=who)

    edits, first = [], True
    for idx, ((start, stop), run) in enumerate(zip(spans, runs, strict=True)):
        if not overlaps((start, stop), (at, end)):
            continue
        run_xml = run.group(0)
        body = visible_text(run_xml)
        tail = body[end - start:] if stop > end else ""
        instruction = field_only(idx, run)
        if instruction is not None and not allow_hyperlink:
            raise AnchorError(
                f"{who}: the match {'starts in' if first else 'crosses'} "
                f"the result of a field ({instruction}) -- Word writes "
                f"that result back on its next update, so "
                f"{visible_text(run_xml)[:30]!r} would return beside the "
                f"new words. Replace on each side of the field "
                f"(replace_keeping_links does), or pass "
                f"allow_hyperlink=True to rewrite the cached result "
                f"deliberately.")
        if first:
            if not allow_hyperlink and labels_a_link(idx, run):
                raise AnchorError(
                    f"{who}: the match starts inside a hyperlink "
                    "run -- the replacement would bleed into the link. "
                    "Anchor on plain text outside the link, or pass "
                    "allow_hyperlink=True if the replacement lies wholly "
                    "inside the label and retitling it is the point.")
            # The opt-in above answers "may this match touch a link?".
            # It must not also answer "may the label ABSORB text?" — the
            # whole replacement lands in this run, so a match that runs
            # on past the link ends with the label owning words that
            # were outside it (Parental Style's Table 4 caption, two
            # thirds of it drawn as a link).
            if (labels_a_link(idx, run) and not grow_link_label
                    and end > label_end(idx, run)):
                raise AnchorError(
                    f"{who}: the match starts in a hyperlink's "
                    f"label and ends outside it -- writing {new[:40]!r} "
                    "into the label would make the link swallow the text "
                    "beyond it, which no text diff and no anchor check "
                    "shows. Replace a span lying wholly on one side of "
                    "the link, or pass grow_link_label=True to retitle "
                    "the link deliberately.")
            edits.append((run, set_run_text(run_xml, body[:at - start] + new
                                            + tail)))
            first = False
        else:
            if not allow_hyperlink and labels_a_link(idx, run):
                raise AnchorError(
                    f"{who}: the match spans a hyperlink -- "
                    f"emptying {visible_text(run_xml)[:30]!r} would leave "
                    "the link with no label, which no text diff shows and "
                    "no link check catches. Replace on each side of the "
                    "link separately, or pass allow_hyperlink=True to "
                    "rewrite the label itself -- same anchor, same "
                    "bookmark, new words.")
            edits.append((run, set_run_text(run_xml, tail)))

    out = para_xml
    for run, replacement in reversed(edits):
        out = out[:run.start()] + replacement + out[run.end():]
    return out


def _refuse_crossed_maths(para_xml: str, runs: list[re.Match[str]],
                          spans: list[tuple[int, int]],
                          match: tuple[int, int], new: str, *,
                          who: str) -> None:
    """Refuse a match that CROSSES an equation.

    The match is found in EDITABLE text — the runs' — and an inline
    ``m:oMath`` is a sibling of the runs, not in one, so a phrase with
    maths in the middle of it reads as contiguous there. Written the
    ordinary way, the replacement goes into the run before the equation
    and the runs after it are emptied, so the EQUATION MOVES to the end
    of the new text. Measured 2026-09-17: "where [x] is the rate." with
    "where  is" -> "here, is" became "here, isx the rate.", and nothing
    that reads prose order in a gate reads maths.

    Where the maths sits is read off the two walks together: a seam
    between two runs is an equation exactly when the READER's offsets
    (:func:`run_spans`, which count maths) jump across it. Touching the
    equation at either edge is not crossing it.
    """
    at, end = match
    _vruns, vspans, _cursor = run_spans(para_xml)
    for i in range(len(runs) - 1):
        if at < spans[i][1] < end and vspans[i + 1][0] > vspans[i][1]:
            maths = visible_text(para_xml[runs[i].end():runs[i + 1].start()])
            raise AnchorError(
                f"{who}: the match crosses an equation ({maths[:30]!r}) -- "
                f"it was found in the runs' text, where the maths is not, "
                f"so writing {new[:40]!r} would put the equation after "
                f"the new words. Anchor on one side of the equation.")


def _refuse_crossed_empty_field(para_xml: str, runs: list[re.Match[str]],
                                spans: list[tuple[int, int]],
                                match: tuple[int, int], new: str, *,
                                who: str) -> None:
    r"""Refuse a match that CROSSES a field showing nothing yet.

    A field's cached result is a label (:func:`_label_spans_in`), and
    this module refuses to write through one because Word regenerates it.
    A field that has no result yet has no run to BE that label: every run
    it owns is zero width — the ``begin``, the instruction, the
    ``separate``, the ``end``, and an empty result run when there is one
    — so the match reads straight through the field and no guard here
    knew it was there.

    Written the ordinary way, the replacement goes into the run holding
    the START of the match and the runs after it are emptied, so the
    field ends up after the new words and Word writes its result THERE
    on the next update. That is the ``REF _Ref… \h`` failure of
    2026-09-17 one update later: the words read correctly until the
    field comes back in the wrong place, and no text diff, no anchor
    check and no link gate says anything.

    An empty ``w:hyperlink`` ELEMENT in the same position is refused
    already — the element's run is a hyperlink run whatever its width —
    and two forms of one construct must answer alike.
    """
    at, end = match
    for lo, hi, _body in field_spans(para_xml):
        held = [i for i, r in enumerate(runs) if in_span(r.start(), (lo, hi))]
        if not held or any(spans[i][0] != spans[i][1] for i in held):
            continue                # it shows something: that IS its label
        where = spans[held[0]][0]
        if not at < where < end:
            continue                # beside the match, not across it
        instruction = " ".join(unescape(t).strip()
                               for t in INSTR_RE.findall(para_xml[lo:hi]))[:40]
        raise AnchorError(
            f"{who}: the match crosses a field that shows nothing yet "
            f"({instruction}) -- the replacement goes into the run "
            f"holding the start of the match and the text after the "
            f"field is emptied, so the field ends up after {new[:40]!r} "
            f"and Word writes its result THERE on its next update. "
            f"Nothing downstream shows that: the field still resolves "
            f"and the words read in the same order. Anchor on one side "
            f"of the field, or pass allow_hyperlink=True to write "
            f"through it deliberately.")


class _Label(NamedTuple):
    """What a link or a field SHOWS, in editable offsets and run indices."""

    start: int
    end: int
    first: int
    last: int
    #: the XML span of the field that makes this a label, when a field
    #: does (the outermost one); None for an element or a styled run
    field: tuple[int, int] | None


def _label_spans_in(para_xml: str, runs: list[re.Match[str]],
                    spans: list[tuple[int, int]],
                    ) -> list[_Label]:
    """Every LABEL in the paragraph, in order.

    A label is the text a link or a field SHOWS: the visible runs inside
    one ``w:hyperlink`` element, the visible runs of one fldChar field
    (its cached result — the outermost field, when fields nest), or a
    run styled ``Hyperlink`` that is in neither, together with its
    styled neighbours. Runs of ONE link merge into one label; two links
    side by side stay two, so words can still go between them.

    A field's result is what Word regenerates on update, so words
    written into it were never the author's to keep: a label, for
    `replace_keeping_links` to edit around and for `replace_in_para`
    (through :func:`_rewrite_span`) to refuse. Word's own
    ``REF _Ref… \\h`` states no style on its result, which is why the
    style alone was never the answer. Offsets are EDITABLE, the spans
    `runs` / `spans` carry.
    """
    elements = [(m.start(), m.end())
                for m in HYPERLINK_ANY_RE.finditer(para_xml)]
    # outermost first: `field_spans` sorts by (start, -end), so the first
    # holding span of a nested pair is the parent
    fields = [(lo, hi) for lo, hi, _ in field_spans(para_xml)]
    out: list[_Label] = []
    last_key: object = None
    for idx, (run, (start, stop)) in enumerate(zip(runs, spans, strict=True)):
        if start == stop:
            continue                # zero width: never splits a label
        key: object
        fld: tuple[int, int] | None = None
        if (element := span_holding(run.start(), elements)) is not None:
            key = ("element", element)
        elif (fld := span_holding(run.start(), fields)) is not None:
            key = ("field", fld)
        elif _HYPERLINK_RUN in run.group(0):
            key = ("styled",)
        else:
            last_key = None
            continue
        if out and key == last_key and out[-1].end == start:
            out[-1] = out[-1]._replace(end=stop, last=idx)
        else:
            out.append(_Label(start, stop, idx, idx, fld))
        last_key = key
    return out


def _live_rpr(run_xml: str) -> str:
    """A run's properties as they are NOW, as an element — or ``""``."""
    found = own_properties(run_xml, "rPr")
    if found is None:
        return ""
    live = live_properties(found[2])
    return f"<w:rPr>{live}</w:rPr>" if live else ""


def replace_keeping_links(para_xml: str, old: str, new: str, *,
                          normalize: bool = False,
                          allow_notes: bool = False) -> str:
    """Replace `old` by `new` in one paragraph, editing AROUND every link.

    What :func:`replace_in_para`'s refusal asks for — "replace on each
    side of the link separately" — done for the caller. `old` is split
    at every link label inside it, `new` must carry each of those labels
    in the same order, and each piece between two labels is edited on
    its own. The labels, their ``w:hyperlink`` elements or fields, and
    the bookmarks round them are never written to. DSI's UNFPA batch
    (2026-09-16) replaced two paragraphs holding linked citations this
    way, in ninety hand-written lines.

    A label here is what a link or a FIELD shows — see
    :func:`_label_spans_in` for why that is wider than the Hyperlink
    style `replace_in_para` asks about. An `old` that crosses no label
    is handed to `replace_in_para` itself, so the answer is identical.

    **Pieces are edited by OFFSET, right to left.** The version this
    replaces found each piece again by a text search and refused a bare
    ``").`` because the paragraph held another. A changed piece is
    written the way `replace_in_para` writes — all of it into the run
    holding its start, the rest of its runs emptied — so it keeps that
    run's face. An EMPTY piece (`old` opens or closes on a label, or two
    labels touch) has no run to write into: the new words go in as a
    run of their own through :func:`insert_in_para`, OUTSIDE the link and
    its bookmark, carrying the live properties of the nearest plain run
    (a bare run would drop the direct formatting a manuscript sets on
    every run).

    **Which occurrence of a label in `new` is the link** is decided by
    position: a label whose text occurs k times in `old` and is the j-th
    of them must occur k times in `new`, and becomes the j-th there. A
    different count is AMBIGUOUS — `new` mentioning "Sen 1999" twice
    where `old` did once cannot say which one is the link — and refused
    rather than guessed. Refused too, with :class:`AnchorError`:

    * `old` is not in the paragraph, or is there more than once;
    * a label STRADDLES an edge of `old` (half of it cannot be kept);
    * `new` drops a label, or carries them in a different order;
    * a rewritten piece crosses an EQUATION (as in `replace_in_para`), or
      new words for an empty piece would land between two labels with
      an equation between them;
    * a note, endnote or comment REFERENCE is crossed by a rewritten
      piece — the same refusal, for the same reason, as
      `replace_in_para`'s — or sits exactly where an empty piece's new
      words go, where "Sen 1999¹ and others" and "Sen 1999 and others¹"
      are both readings of one `new`. ``allow_notes=True`` accepts both:
      a crossed marker moves to the end of the piece, and inserted words
      go after a marker at their offset.

    `normalize` matches `old`, and the labels inside `new`, through
    Word's glyph substitutions (:func:`find_normalized`); `new` is
    written verbatim, and a label keeps the glyphs the document has.
    """
    runs, spans = _run_walk(para_xml)
    visible = editable_text(para_xml)
    at, end = _locate_anchor(para_xml, visible, old, normalize=normalize,
                             who="replace_keeping_links")
    labels = [lab for lab in _label_spans_in(para_xml, runs, spans)
              if overlaps((lab.start, lab.end), (at, end))]
    if not labels:
        return replace_in_para(para_xml, old, new, allow_notes=allow_notes,
                               normalize=normalize)

    for lab in labels:
        if lab.start < at or lab.end > end:
            raise AnchorError(
                f"replace_keeping_links: the link label "
                f"{visible[lab.start:lab.end]!r} straddles the "
                f"{'start' if lab.start < at else 'end'} of {old[:60]!r} "
                f"— half a label cannot be kept whole by editing around "
                f"it. Widen `old` to take the whole label, or narrow it "
                f"to leave the label out.")

    old_text = visible[at:end]
    placed: list[tuple[int, int]] = []          # each label's span in `new`
    after = 0
    for lab in labels:
        lo = lab.start
        label = visible[lo:lab.end]
        in_old = [s for s, _e in _hits(old_text, label, normalize)]
        in_new = _hits(new, label, normalize)
        if not in_new:
            raise AnchorError(
                f"replace_keeping_links: the replacement drops the link "
                f"label {label!r}. Keep it in `new`, or remove the link "
                f"first (remove_link) if it is meant to go.")
        if len(in_new) != len(in_old):
            raise AnchorError(
                f"replace_keeping_links: {label!r} is a link label, and it "
                f"occurs {len(in_old)} time(s) in `old` and {len(in_new)} "
                f"in `new` — which of them is the link is ambiguous. Make "
                f"the counts agree, or split the call.")
        where = in_new[in_old.index(lo - at)]
        if where[0] < after:
            raise AnchorError(
                f"replace_keeping_links: the replacement carries the link "
                f"labels in a different order ({label!r} comes earlier) — "
                f"a link cannot be moved by editing around it. Keep the "
                f"order, or move the link in Word.")
        placed.append(where)
        after = where[1]

    # the pieces: before the first label, between labels, after the last
    bounds = [at] + [x for lab in labels for x in (lab.start, lab.end)] \
        + [end]
    cuts = [0] + [x for span in placed for x in span] + [len(new)]
    pieces = [((bounds[2 * i], bounds[2 * i + 1]),
               new[cuts[2 * i]:cuts[2 * i + 1]])
              for i in range(len(labels) + 1)]

    out = para_xml
    for (lo, hi), words in reversed(pieces):
        if visible[lo:hi] == words:
            continue
        runs, spans = _run_walk(out)
        if lo < hi:
            out = _rewrite_span(out, runs, spans, (lo, hi), words,
                                allow_hyperlink=False, grow_link_label=False,
                                allow_notes=allow_notes,
                                who="replace_keeping_links")
        else:
            out = _insert_between_labels(out, runs, spans, lo, words,
                                         allow_notes=allow_notes)
    return out


def _insert_between_labels(para_xml: str, runs: list[re.Match[str]],
                           spans: list[tuple[int, int]], at: int, words: str,
                           *, allow_notes: bool) -> str:
    """New words for an EMPTY piece at editable offset `at`, as a run.

    The piece is empty because a label begins or ends there, so the
    offset is converted to the reader's through that LABEL's own runs —
    the start of the label after it, the end of the label before it.
    With both, and an equation between them, the two answers differ and
    the words have no one place to go.
    """
    labels = _label_spans_in(para_xml, runs, spans)
    left = right = None
    for lab in labels:
        if lab.end == at:
            left = lab.last
        if lab.start == at:
            right = lab.first
    _vruns, vspans, _cursor = run_spans(para_xml)
    places = ({vspans[left][1]} if left is not None else set()) \
        | ({vspans[right][0]} if right is not None else set())
    if len(places) != 1:
        raise AnchorError(
            f"replace_keeping_links: {words[:40]!r} would go between two "
            f"link labels with an equation between them — before the "
            f"maths or after it is not something the text can say. Edit "
            f"that gap by hand, or anchor on one label.")
    (place,) = places
    if not allow_notes:
        for run, (lo, hi) in zip(runs, spans, strict=True):
            if lo == hi == at and (note := _note_in(run.group(0))):
                raise AnchorError(
                    f"replace_keeping_links: {note} sits exactly where "
                    f"{words[:40]!r} would go, and whether the words go "
                    f"before the marker or after it is not something the "
                    f"text can say. Anchor so the marker is outside `old`, "
                    f"or pass allow_notes=True (the words then go after "
                    f"it).")
    # the face the words take: the nearest PLAIN run, before them if
    # there is one — prose the sentence already has, never a label
    in_label = {i for lab in labels for i in range(lab.first, lab.last + 1)}
    plain = [i for i, (lo, hi) in enumerate(spans)
             if lo < hi and i not in in_label]
    before = [i for i in plain if spans[i][1] <= at]
    source = before[-1] if before else (plain[0] if plain else None)
    rpr = _live_rpr(runs[source].group(0)) if source is not None else ""
    space = ' xml:space="preserve"' if words != words.strip() else ""
    return insert_in_para(
        para_xml, place,
        f"<w:r>{rpr}<w:t{space}>{escape(words)}</w:t></w:r>")


class _Link(NamedTuple):
    """One link to an anchor: the words it shows, and the whole of it.

    Two spans because a caller wants one or the other and never both by
    accident. `relabel_link` rewrites the LABEL and must leave the
    machinery standing; `remove_link` takes the machinery away and must
    keep the label. Reading either span off the wrong one produces a
    paragraph Word opens and a reader cannot use.
    """

    anchor: str                 # the bookmark it points at
    label: tuple[int, int]      # the words on the page
    outer: tuple[int, int]      # the construct that makes them a link
    field: bool                 # a Word FIELD rather than an element


def _links_to(para_xml: str, anchor: str | None = None) -> list[_Link]:
    """Every link to `anchor` in this paragraph, in BOTH forms.

    `anchor=None` answers for EVERY internal link, which is what a sweep
    over a whole part needs — and it is the same scan, because a sweep
    that read links its own single-link sibling cannot see would unwrap
    a different set from the one `remove_link` reports.

    Which form a paragraph holds depends on who saved the file last, so
    a routine that reads one of them works until the author opens the
    document. `crossrefs.unlink` is what that costs: it refuses a
    field-form exhibit link outright rather than remove half of one,
    because "24 removed" over a document whose caption links were all
    still live was found much later and by hand (Parental_style).

    The OUTER span is run-aligned for a field, and it has to be: a field
    is four runs — begin, instruction, separate, end — and `_FIELD_RE`
    matches from the `begin` fldChar to the `end` one, INSIDE the runs
    that hold them. Cutting at the match leaves two empty `w:r` shells
    around the words.
    """
    out: list[_Link] = []
    for m in _HYPERLINK_EL_RE.finditer(para_xml):
        found = unescape(m.group(1))
        if anchor is None or found == anchor:
            out.append(_Link(found, (m.start(2), m.end(2)),
                             (m.start(), m.end()), field=False))
    for m in _FIELD_RE.finditer(para_xml):
        instr = unescape("".join(INSTR_RE.findall(m.group(1))))
        am = INSTR_ANCHOR_RE.search(instr)
        sep = SEPARATE_RE.search(m.group(1))
        if am is None or sep is None:
            continue
        if anchor is not None and am.group(1) != anchor:
            continue
        start = run_open_before(para_xml, m.start())
        end = para_xml.find("</w:r>", m.end())
        if start < 0 or end < 0:            # pragma: no cover - defensive
            continue
        out.append(_Link(am.group(1), (m.start(1) + sep.end(), m.end(1)),
                         (start, end + len("</w:r>")), field=True))
    return sorted(out, key=lambda link: link.label)


def _label_spans(para_xml: str, anchor: str) -> list[tuple[int, int]]:
    """Where each link to `anchor` keeps the words it SHOWS.

    Both forms, because which one a paragraph holds depends on who saved
    the file last: the element's content, and everything a field puts
    after its `separate` marker.
    """
    return [link.label for link in _links_to(para_xml, anchor)]


#: The run property that makes a link LOOK like one. Attribute-order
#: tolerant, per CONTRIBUTING's second trap: `<w:rStyle w:val="Hyperlink"/>`
#: written the other way round is the same element, and a pattern that
#: spells one order leaves the blue underline on words that no longer
#: link anywhere.
_HYPERLINK_STYLE_RE = re.compile(
    r'<w:rStyle\b[^>]*\bw:val="Hyperlink"[^>]*/>')


def _renders_nothing(run_xml: str) -> bool:
    """A run with properties and NO content — the shell a label leaves."""
    found = own_properties(run_xml, "rPr")
    start = found[1] if found else run_xml.index(">") + 1
    return not run_xml[start:len(run_xml) - len(_RUN_CLOSE)].strip(XML_WS)


def _plain_runs(span_xml: str) -> str:
    """The span with what makes it a LINK gone, and everything else kept.

    Three things are the link's own: the ``w:hyperlink`` element's own
    tags, a field's four machinery runs (begin, instruction, separate,
    end — :func:`is_field_run`, so a run carrying words is never one),
    and the Hyperlink style with the empty ``w:rPr`` shell it leaves
    behind. Everything else the span holds is the PARAGRAPH's, whatever
    it is, and a reader keeps it when the link goes.

    Until 2026-09-18 this kept the runs holding ``<w:t`` and dropped
    every other byte, which took away with the link: a footnote
    reference inside a label — its note then orphaned in footnotes.xml,
    no marker in the body, and no gate that reads one — a line break
    inside a two-line caption's label, a bookmark, and, an element being
    no run, the ``w:ins`` round a tracked insertion, whose words then
    read as the author's own. A field span that crosses one ``w:ins``
    tag and not the other lost that tag alone, which Word calls an
    unreadable part.

    A run that renders NOTHING still goes: a styled run with no content
    is a label Word has already emptied, and keeping it would leave
    `<w:r></w:r>` standing in the prose.
    """
    if span_xml.startswith("<w:hyperlink") \
            and span_xml.endswith("</w:hyperlink>"):
        # the ELEMENT's own tags — and only the outermost pair, so a
        # link nested inside a field's result keeps its own
        span_xml = span_xml[span_xml.index(">") + 1:-len("</w:hyperlink>")]
    kept, at = [], 0
    for r in RUN_RE.finditer(span_xml):
        if is_field_run(r.group(0)) or _renders_nothing(r.group(0)):
            kept.append(span_xml[at:r.start()])
            at = r.end()
    kept.append(span_xml[at:])
    # …and the shell the style leaves behind. A run whose only property
    # WAS the link style now carries `<w:rPr></w:rPr>`, which Word opens
    # and a diff reports; an rPr that was empty before this is empty
    # after it, so removing the shell says nothing new either way.
    return _EMPTY_RPR_RE.sub(
        "", _HYPERLINK_STYLE_RE.sub("", "".join(kept)))


_EMPTY_RPR_RE = re.compile(r"<w:rPr\s*/>|<w:rPr>\s*</w:rPr>")


def _drop_bookmark(para_xml: str, name: str) -> str:
    """Remove one named bookmark and the ``bookmarkEnd`` that closes it."""
    for m in _BOOKMARK_RE.finditer(para_xml):
        if m.group(1) != "Start" or f'w:name="{name}"' not in m.group(0):
            continue
        bid = _ID_ATTR_RE.search(m.group(0))
        out = para_xml[:m.start()] + para_xml[m.end():]
        if bid is None:                     # pragma: no cover - defensive
            return out
        closing = re.search(
            rf'<w:bookmarkEnd\b[^>]*\bw:id="{bid.group(1)}"[^>]*/>', out)
        return out[:closing.start()] + out[closing.end():] if closing else out
    return para_xml


def remove_link(para_xml: str, anchor: str, *,
                drop_twin: bool = True) -> tuple[str, str]:
    """Undo the link to `anchor`, keeping the words it showed.

    Returns the paragraph and the label that was on the page, because a
    caller removing a link is usually about to put a different one on
    the same words and would otherwise have to read them twice.

    The inverse of :func:`docxkit.citations.link_in_para`, and the
    operation this package could not do: `crossrefs.unlink` is
    document-wide, finds its targets through the exhibit captions, and
    REFUSES a field-form link rather than remove half of one. Aging_Well
    wrote its own for citations — 38 lines re-deriving the two-form scan
    that `_links_to` beside this already does — because the house wants
    one link per YEAR in "Rowe and Kahn (1987, 1997)" where `link_all`
    tiles the group, and re-narrowing has to happen on every pass: a
    tiled link is a CORRECT link, so no gate has an opinion about it.

    `drop_twin` also removes the ``<anchor>txt`` bookmark, which is this
    package's own convention for the in-text end of a link (see
    CONTRIBUTING). Left behind, `wrap_link_in_bookmark` adds a second on
    the next re-wire. Pass False when the bookmark is wanted without the
    link — an anchor a REF field still reaches.

    Refuses the two silent cases :func:`relabel_link` refuses, for the
    same reason: an anchor this paragraph does not link to (a removal
    that quietly does nothing is how a batch reports success and ships
    the link), and an anchor it links to twice, where nothing in the
    arguments says which.
    """
    links = _links_to(para_xml, anchor)
    if not links:
        have = sorted({a for a, _ in internal_links(para_xml)})
        raise AnchorError(
            f"remove_link: this paragraph has no link to {anchor!r}"
            + (f" — it links to {have}" if have else " — it has no links"))
    if len(links) > 1:
        raise AnchorError(
            f"remove_link: this paragraph links to {anchor!r} "
            f"{len(links)} times and nothing here says which to remove. "
            f"Split the paragraph's edits, or narrow the span first.")
    link = links[0]
    label = visible_text(para_xml[link.label[0]:link.label[1]])
    lo, hi = link.outer
    out = para_xml[:lo] + _plain_runs(para_xml[lo:hi]) + para_xml[hi:]
    return (_drop_bookmark(out, anchor + "txt") if drop_twin else out), label


def remove_links(xml: str, *, keep: Collection[str]) -> tuple[str, list[str]]:
    """Unwrap every internal link whose anchor is NOT in `keep`.

    The sweep :func:`remove_link` is the unit of. Splitting a manuscript
    into a main file and a supplement leaves links whose bookmark is now
    in the OTHER file — main-text mentions pointing at appendix
    captions, caption back-links pointing at their first mentions, a
    citation link inside a table note — and every one of them has to
    lose the link and keep the words. Parental_style hand-rolled this as
    `unlink_absent` on 2026-09-01 and it will recur for every journal
    that wants its appendices as a separate supplemental file.

    Returns the part and the anchors it unwrapped, in document order, so
    a caller can report and a dry run can print.

    **Build `keep` from every part a link may legitimately reach, not
    from the body.** Eleven of Parental_style's ``<key>txt`` markers
    live in ``footnotes.xml``: a name set read from ``document.xml``
    alone declared those eleven back-links dangling and would have
    unwrapped all of them, caught in a dry run. `docxkit.package.
    text_parts` is the iteration that gets this right.

    Unlike :func:`remove_link` this touches no bookmark: the anchors
    here are the ones being KEPT somewhere, and a sweep that also
    deleted their in-text twins would take the targets with the links.
    """
    gone: list[str] = []
    # Last first, so an earlier link's offsets are still good after a
    # later one is spliced out.
    for link in sorted(_links_to(xml), key=lambda lk: -lk.outer[0]):
        if link.anchor in keep:
            continue
        lo, hi = link.outer
        xml = xml[:lo] + _plain_runs(xml[lo:hi]) + xml[hi:]
        gone.append(link.anchor)
    return xml, gone[::-1]


def relabel_link(para_xml: str, anchor: str, new_label: str) -> str:
    """Rewrite what a link SHOWS, leaving what it points AT alone.

    The operation :func:`replace_in_para` allows and does not name: same
    anchor, same bookmark, same field, new words. Three AFI batches
    hand-rolled it against exact ``<w:t>`` matches before the
    `allow_hyperlink=True` flag was found (six citation relabels, then
    25 reference entries), and the hand-rolled version is not merely
    more code — it MISSES a label split across runs, which Word produces
    routinely and this handles in one call.

    Addressed by ANCHOR rather than by the words on the page, which is
    the difference from `replace_in_para(..., allow_hyperlink=True)`: a
    paragraph that says "Table 3" in prose and again as a link has one
    span this can mean, and matching the text would take the first.

    Refuses two things, both of them silent otherwise: an anchor this
    paragraph does not link to (a relabel that quietly does nothing is
    how a batch reports success and ships the old words), and an anchor
    it links to TWICE, where nothing in the arguments says which. An
    empty label is refused too — that is the shape `replace_in_para`
    guards the whole paragraph against, and it is no better done on
    purpose.
    """
    if not new_label:
        raise AnchorError(
            "relabel_link: a link with no label is invisible to a reader "
            "and to every text diff, while the anchor still resolves. "
            "Remove the link with crossrefs.unlink if that is the intent.")
    spans = _label_spans(para_xml, anchor)
    if not spans:
        have = sorted({a for a, _ in internal_links(para_xml)})
        raise AnchorError(
            f"relabel_link: this paragraph has no link to {anchor!r}"
            + (f" — it links to {have}" if have else " — it has no links"))
    if len(spans) > 1:
        raise AnchorError(
            f"relabel_link: this paragraph links to {anchor!r} "
            f"{len(spans)} times and nothing here says which to retitle. "
            f"Split the paragraph's edits, or use replace_in_para with "
            f"allow_hyperlink=True on the words you mean.")
    at, end = spans[0]
    return (para_xml[:at] + set_run_text(para_xml[at:end], new_label)
            + para_xml[end:])


def _enclosing(spans: list[tuple[int, int]], pos: int
               ) -> tuple[int, int] | None:
    """The span STRICTLY containing `pos`, if any."""
    return next(((lo, hi) for lo, hi in spans if lo < pos < hi), None)


_BOOKMARK_RE = re.compile(r"<w:bookmark(Start|End)\b[^>]*?/>")


def _bookmark_spans(xml: str) -> list[tuple[int, int]]:
    """``bookmarkStart`` -> its matching ``bookmarkEnd``, paired by id."""
    out: list[tuple[int, int]] = []
    open_at: dict[str, int] = {}
    for m in _BOOKMARK_RE.finditer(xml):
        bid = _ID_ATTR_RE.search(m.group(0))
        if bid is None:
            continue
        if m.group(1) == "Start":
            open_at[bid.group(1)] = m.start()
        elif (lo := open_at.pop(bid.group(1), None)) is not None:
            out.append((lo, m.end()))
    return out


def _outside(runs: list[re.Match[str]], span: tuple[int, int],
             pos: int) -> int | None:
    """The edge of `span` that holds `pos`'s VISIBLE position, or None.

    A position inside a protected element is only movable when nothing
    the element shows lies on one side of it: then the same place on the
    page is available outside, before or after the whole element. With
    text on BOTH sides the caller really is asking to split a label, and
    that is the refusal.
    """
    inner = [r for r in runs if in_span(r.start(), span)
             and visible_text(r.group(0))]
    if not any(r.end() <= pos for r in inner):
        return span[0]
    if not any(r.start() >= pos for r in inner):
        return span[1]
    return None


def insert_in_para(para_xml: str, at: int, content: str, *,
                   allow_hyperlink: bool = False,
                   allow_bookmark: bool = False) -> str:
    """Splice `content` into a paragraph at VISIBLE offset `at`.

    The other half of :func:`replace_in_para`, and it did not exist:
    `body` stops at whole paragraphs and `edit` had `set_run_text`,
    `replace_in_para`, `rep` and nothing that puts a run BETWEEN runs.
    So every caller wrote the string surgery itself, and the obvious
    version is wrong twice over — both failures on `Parental_style`,
    2026-08-13:

    * **prepending to a paragraph whose first run is a link label.** The
      Bhalotra-Clarke paragraph opens directly on its citation's
      field-form hyperlink, so its first ``w:t`` IS the label. Fronting
      the paragraph by prepending there put the sentence INSIDE the
      link — ``'A further consideration concerns the twin instrument
      itself. Bhalotra and Clarke (2020)'``, blue and underlined across
      the whole sentence. Every text-layer check passed, because the
      words really are in that order; only `compare`'s HYPERLINK layer
      sees it, and that layer is review-not-gated;
    * **finding the run boundary by hand.** ``head.rfind("<w:r")``
      matches ``<w:rPr`` too. That spliced a paragraph mid-properties
      and destroyed the ``(B.2)`` equation label two screens away.

    `content` goes in as XML when it starts with ``<`` — a run, an
    ``m:oMath``, a whole hyperlink — and is wrapped in a run otherwise,
    escaped, with ``xml:space="preserve"`` when it has edge whitespace.

    At a run boundary nothing is split. INSIDE a run the run is REBUILT
    as two through :func:`set_run_text` — never spliced — so its
    properties and its style survive on both halves.

    **Where the offset falls on the EDGE of a link or a bookmark, the
    content lands OUTSIDE it.** That is the first failure above: at
    offset 0 of a paragraph that opens on a link, "before the first run"
    is a position inside the ``w:hyperlink`` element, and what the
    caller means is before the element. Strictly inside a label or a
    bookmark span it refuses, mirroring `replace_in_para`;
    ``allow_hyperlink`` / ``allow_bookmark`` are the deliberate escapes.
    A fldChar FIELD is never split, flag or no flag: the halves are not
    two fields, they are one broken one.

    **The paragraph ENDS where its text ends, not where its last run
    does.** An ``m:oMath`` after the last ``w:r`` is text a reader sees,
    so the offset after it is the paragraph's end and the offset before
    it is the equation's: words go after the maths at the one and before
    it at the other. The paragraph that is only an equation — every
    display one — has both.
    """
    runs, spans, cursor = run_spans(para_xml)
    # Where the RUNS end is not where the PARAGRAPH ends. `run_spans`
    # advances its cursor across what sits between runs, so it stops at
    # the last `w:r` — and an equation AFTER that run is visible text no
    # run covers. Measured 2026-09-18, all three offsets past it wrong:
    # the paragraph's own end refused as "outside the paragraph's 6
    # visible characters" of a paragraph that reads seven, and — in the
    # paragraph that is ONLY an equation, which is every display
    # equation — offset 0 taken for the end, so the words went in
    # through the `not runs` branch AFTER the maths.
    end = len(visible_text(para_xml))
    if at < 0 or at > end:
        raise AnchorError(
            f"insert_in_para: offset {at} is outside the paragraph's "
            f"{end} visible characters")
    if not content.lstrip().startswith("<"):
        tag = ('<w:t xml:space="preserve">'
               if content != content.strip() else "<w:t>")
        content = f"<w:r>{tag}{escape(content)}</w:t></w:r>"

    protected = (
        ([(m.start(), m.end())
          for m in HYPERLINK_ANY_RE.finditer(para_xml)], allow_hyperlink,
         "a hyperlink — the content would become part of its label"),
        ([(lo, hi) for lo, hi, _ in field_spans(para_xml)], False,
         ("a fldChar field — the halves would not be two fields, they "
          "would be one broken one")),
        (_bookmark_spans(para_xml), allow_bookmark,
         "a bookmark — the anchor would grow to cover the new text"),
    )

    if (inside := next(((i, s) for i, (s, e) in enumerate(spans)
                        if s < at < e), None)) is not None:
        return _split_run(para_xml, runs[inside[0]], at - inside[1], content,
                          protected=protected,
                          allow_hyperlink=allow_hyperlink, at=at)
    if not any(s == at < e for s, e in spans) and (at != cursor or not runs):
        # No run holds the offset and no VISIBLE one starts there, so
        # what a reader sees next is MATHS — the reader's offsets count
        # an equation and it lives in no w:r — or nothing at all, the
        # offset being the paragraph's own end past a trailing one.
        # `_between_runs` asked for the last run starting here and raised
        # a bare ValueError when there was none (2026-09-17) — the
        # ordinary case of "insert before the maths" — and, with only a
        # zero-width marker starting here, put the words BEFORE the
        # marker it means to go after. `at == cursor` stays with the runs
        # (after the last one, before any equation that follows it);
        # only a paragraph with NO runs takes its offset 0 to the maths.
        if at == end:
            close = para_xml.rindex("</w:p>")
            return para_xml[:close] + content + para_xml[close:]
        pos = _shielded(runs, at, _maths_start(para_xml, at), protected)
        return para_xml[:pos] + content + para_xml[pos:]
    pos = _between_runs(runs, spans, at, cursor, protected)
    return para_xml[:pos] + content + para_xml[pos:]


def _split_run(para_xml: str, run: re.Match[str], offset: int, content: str,
               *, protected: _Protected, allow_hyperlink: bool,
               at: int) -> str:
    """Rebuild ONE run as two, with `content` between the halves.

    Rebuilt through `set_run_text` rather than spliced: locating the
    reopening tag by hand with ``rfind("<w:r")`` matches ``<w:rPr`` too,
    and that spliced a paragraph mid-properties and destroyed an
    equation label two screens away.
    """
    if not allow_hyperlink and _HYPERLINK_RUN in run.group(0):
        raise AnchorError(
            "insert_in_para: the offset falls INSIDE a hyperlink's "
            "label — splitting it there puts the new content in the "
            "link, blue and underlined, which no text diff shows. "
            "Insert on one side of the label, or pass "
            "allow_hyperlink=True.")
    for regions, allowed, what in protected:
        if not allowed and span_holding(run.start(), regions) is not None:
            raise AnchorError(
                f"insert_in_para: offset {at} splits a run that is inside "
                f"{what}. Insert on one side of it, or pass the matching "
                f"allow_ flag.")
    body = visible_text(run.group(0))
    return (para_xml[:run.start()]
            + set_run_text(run.group(0), body[:offset]) + content
            + set_run_text(run.group(0), body[offset:])
            + para_xml[run.end():])


def _between_runs(runs: list[re.Match[str]], spans: list[tuple[int, int]],
                  at: int, cursor: int, protected: _Protected) -> int:
    """The XML offset for a visible position that falls BETWEEN runs.

    The LAST run that starts here, not the first: several can share one
    visible offset — a field's ``end`` marker, a note reference and a
    ``bookmarkEnd`` all have zero width — and "at offset N" means after
    everything that ended there.
    """
    pos = (runs[-1].end() if at == cursor else
           max(r.start() for r, (s, _) in zip(runs, spans, strict=True)
               if s == at))
    return _shielded(runs, at, pos, protected)


#: How every equation opens: `m:oMathPara` (display) starts with it too,
#: and holds its `m:oMath`, so the FIRST occurrence at an offset is the
#: outermost element there.
_OMATH_OPEN = "<m:oMath"


def _maths_start(para_xml: str, at: int) -> int:
    """The XML offset of the equation that BEGINS at visible offset `at`.

    A run goes before the outermost element — before an ``m:oMathPara``,
    never between it and its ``m:oMath``. An offset no equation begins
    at, and no run holds, is inside the maths itself: refused, since a
    run inside ``m:oMath`` is not something Word opens.
    """
    pos = para_xml.find(_OMATH_OPEN)
    while pos >= 0:
        before = len(visible_text(para_xml[:pos]))
        if before == at:
            return pos
        if before > at:
            break
        pos = para_xml.find(_OMATH_OPEN, pos + 1)
    raise AnchorError(
        f"insert_in_para: offset {at} falls inside an equation (m:oMath) — "
        f"a run cannot go inside the maths. Insert before or after the "
        f"equation.")


def _shielded(runs: list[re.Match[str]], at: int, pos: int,
              protected: _Protected) -> int:
    """`pos` moved OUTSIDE any protected region it merely touches.

    At an edge the same place on the page is available outside the link,
    field or bookmark; strictly inside, with its content on both sides,
    it is refused unless that region's flag allows it.
    """
    for regions, allowed, what in protected:
        if (span := _enclosing(regions, pos)) is None:
            continue
        if (edge := _outside(runs, span, pos)) is not None:
            pos = edge              # an EDGE is not "inside": go outside
        elif not allowed:
            raise AnchorError(
                f"insert_in_para: offset {at} falls inside {what}. Insert "
                f"on one side of it, or pass the matching allow_ flag.")
    return pos


#: A run belongs to a field's MACHINERY if it carries one of these.
_FIELD_MACHINERY_RE = re.compile(r"<w:(?:fldChar|instrText)\b")


def is_field_run(run_xml: str) -> bool:
    """Is this run a field's machinery rather than anything a reader sees?

    ``fldChar`` markers and ``instrText`` live in runs like any other
    content, and they carry no visible text. A formatting sweep that
    walks ``<w:r>`` therefore writes into them, Word's Compare marks
    every one it wrote into, and REJECTING that batch brings the words
    back as plain text with the field's anchor gone.

    Measured on AFI (2026-08-19): one caption of twenty-four is built as
    a field-code hyperlink, and formatting its machinery took a batch
    from 36 revisions to 136 — a hundred of them invisible field parts
    the author would have had to click through — and lost
    ``fig10_firstref``, which `revision validate` caught as LINK LOST.
    """
    return (_FIELD_MACHINERY_RE.search(run_xml) is not None
            and not visible_text(run_xml).strip())


#: What may sit between a paragraph's last run and its close without
#: being content: the ends of ranges, which render nothing. Anything
#: else there — an equation, the close of a link, a tracked insertion or
#: a content control — means the last run is not the paragraph's end.
_EMPTY_MARKER_RE = re.compile(
    r"<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart|commentRangeEnd"
    r"|proofErr|permStart|permEnd)\b[^>]*/>")
_RUN_CLOSE = "</w:r>"


def _plain_run(run_xml: str) -> bool:
    """A run holding nothing but properties and text, and not a label.

    Everything else a run can hold renders or means something — a tab,
    a break, a drawing, a symbol, a note or comment reference, a field's
    machinery, deleted text — and a trim that took the run would take it.
    """
    if _HYPERLINK_RUN in run_xml:
        return False
    body_start = run_xml.index(">") + 1
    body_end = len(run_xml) - len(_RUN_CLOSE)
    found = own_properties(run_xml, "rPr")
    body = (run_xml[body_start:body_end] if found is None
            else run_xml[found[1]:body_end])
    return not _T_EMPTY_RE.sub("", T_RUN_RE.sub("", body)).strip(XML_WS)


def rstrip_para(para_xml: str) -> str:
    """The paragraph with its TRAILING whitespace gone.

    Whole runs of blanks at the end are removed — empty runs too, which
    hide nothing — and the last run with words in it loses its trailing
    blanks. Only real XML whitespace (:data:`XML_WS`), as
    :func:`preserve_space` counts it: a no-break space is a glyph
    somebody typed.

    **Never past anything that is not plain prose.** The walk stops at a
    run holding more than properties and text (a note or comment
    reference, a tab, a drawing, a field's machinery), at a link label,
    and at anything between the last run and the paragraph's close that
    is not the end of a range (an equation, the close of a
    ``w:hyperlink``, a tracked insertion): the space before a footnote
    marker is the author's, a label's own trailing space belongs to the
    link, and trimming inside a ``w:ins`` edits a revision in place.

    DSI's UNFPA batch (2026-09-16) needed exactly this for ¶43 and wrote
    it by hand; `replace_in_para` cannot, since a trailing space run is
    not addressable by a unique anchor.
    """
    out = para_xml
    while runs := list(RUN_RE.finditer(out)):
        last = runs[-1]
        rest = _EMPTY_MARKER_RE.sub("", out[last.end():])
        if rest.replace("</w:p>", "", 1).strip(XML_WS) \
                or not _plain_run(last.group(0)):
            break
        text = visible_text(last.group(0))
        kept = text.rstrip(XML_WS)
        if not kept:
            out = out[:last.start()] + out[last.end():]
            continue
        if kept != text:
            out = (out[:last.start()] + set_run_text(last.group(0), kept)
                   + out[last.end():])
        break
    return out


def set_run_properties(para_xml: str, props: Mapping[str, str], *,
                       skip_fields: bool = True) -> tuple[str, int]:
    """`para_xml` with `props` on every run, and the count of runs changed.

    `props` maps a ``CT_RPr`` child tag to the element to write there —
    ``{"rFonts": '<w:rFonts w:ascii="Arial"/>', "sz": '<w:sz w:val="20"/>'}``
    — each landing in its schema slot, in the run's LIVE properties, and
    replacing what was there rather than sitting beside it. Pass ``""``
    for a tag to REMOVE it.

    The count is of runs this CHANGED, so a second call over the same
    paragraph answers 0: a sweep reports what it did, not what it
    visited.

    `skip_fields` is the reason this exists rather than a loop over
    ``RUN_RE`` in every paper script — see :func:`is_field_run`. It is
    the machinery that is skipped, not the field: the label a field
    DISPLAYS is text a reader sees, and a caption whose number lives
    inside a field still wants the face the rest of the caption has.
    Runs inside a ``w:hyperlink`` element are not skipped for the same
    reason; the damage recorded on AFI was the machinery.
    """
    out = para_xml
    written = 0
    # Back to front: each splice moves every offset after it.
    for m in reversed(list(RUN_RE.finditer(para_xml))):
        run = m.group(0)
        if skip_fields and is_field_run(run):
            continue
        new = run
        for tag, element in props.items():
            new = set_run_property(new, tag, element)
        if new == run:
            continue
        written += 1
        out = out[:m.start()] + new + out[m.end():]
    return out, written
