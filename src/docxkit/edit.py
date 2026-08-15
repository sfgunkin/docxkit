r"""Editing ``document.xml`` as text, with the anchors asserted.

House rule across the papers: raw string surgery on WordprocessingML,
never python-docx, and every anchor asserted so a drifted source fails
loudly instead of producing a subtly wrong manuscript.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from ._xml import (
    HYPERLINK_ANY_RE,
    RUN_OPEN_RE,
    RUN_RE,
    T_RUN_RE,
    XML_WS,
    editable_text,
    escape,
    field_spans,
    live_properties,
    normalize_glyphs,
    own_properties,
    set_run_text,
    visible_text,
)
from .errors import AnchorError

__all__ = [
    "RUN_RE",
    "T_RUN_RE",
    "editable_text",
    "find_normalized",
    "insert_in_para",
    "italicize",
    "preserve_space",
    "rep",
    "replace_in_para",
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
    runs, spans, cursor = [], [], 0
    for r in RUN_RE.finditer(para_xml):
        body = visible_text(r.group(0))
        runs.append(r)
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)

    # `editable_text`, NOT `visible_text`: this pass rewrites w:r runs,
    # and an equation's text is in an m:r inside a sibling m:oMath. The
    # two readings differ on 256 of 399 manuscripts. Counting the maths
    # here would find phrases this function then could not write, which
    # is the worse failure — see the note in `_xml.editable_text`.
    visible = editable_text(para_xml)

    def missing(reason: str) -> AnchorError:
        # The confusing case, named: the phrase IS in the paragraph as a
        # reader (and `docxkit text`, and `para_slice`) sees it, and is
        # not addressable by a run walk.
        if old in visible_text(para_xml):
            return AnchorError(
                f"replace_in_para: {old[:60]!r} {reason} — it IS in the "
                f"paragraph a reader sees, but it spans an equation "
                f"(m:oMath), which this pass rewrites nothing inside. "
                f"Anchor on prose either side of the maths.")
        return AnchorError(f"replace_in_para: {old[:60]!r} {reason}")

    if normalize:
        hits = find_normalized(visible, old)
        if not hits:
            raise missing("not in paragraph")
        if len(hits) > 1:
            raise AnchorError(
                f"replace_in_para: {old[:60]!r} occurs twice")
        at, end = hits[0]
    else:
        at = visible.find(old)
        if at < 0:
            raise missing("not in paragraph")
        if visible.find(old, at + 1) >= 0:
            raise AnchorError(f"replace_in_para: {old[:60]!r} occurs twice")
        end = at + len(old)

    link_spans = [(m.start(), m.end())
                  for m in HYPERLINK_ANY_RE.finditer(para_xml)]

    def labels_a_link(run: re.Match[str]) -> bool:
        return (_HYPERLINK_RUN in run.group(0)
                or any(lo <= run.start() < hi for lo, hi in link_spans))

    def label_extent(idx: int) -> tuple[int, int]:
        """The VISIBLE span of the whole label the idx-th run belongs to.

        Element form first: every run inside the ``w:hyperlink`` is part
        of one label, and Word fragments a label across runs as freely
        as it fragments prose. Field form has no element to ask, so the
        label is the run's styled neighbours — which is the same answer
        for the same reason.
        """
        run = runs[idx]
        for lo, hi in link_spans:
            if lo <= run.start() < hi:
                inside = [i for i, r in enumerate(runs)
                          if lo <= r.start() < hi]
                return spans[inside[0]][0], spans[inside[-1]][1]

        def styled(i: int) -> bool:
            return 0 <= i < len(runs) and _HYPERLINK_RUN in runs[i].group(0)

        lo_i = hi_i = idx
        while styled(lo_i - 1):
            lo_i -= 1
        while styled(hi_i + 1):
            hi_i += 1
        return spans[lo_i][0], spans[hi_i][1]

    # A note reference is a run of ZERO visible width, so `at < p < end`
    # below is exactly "the marker sits strictly inside the match" — a
    # match that merely ABUTS one does not touch it and is not refused.
    # A single touched run cannot move a marker either: the text is
    # rewritten where it stands and nothing is emptied after it.
    touched = [i for i, (start, stop) in enumerate(spans)
               if not (stop <= at or start >= end)]
    if not allow_notes and len(touched) > 1:
        for i in touched:
            if (note := _note_in(runs[i].group(0))) is not None:
                raise AnchorError(
                    f"replace_in_para: the match crosses {note} — the "
                    f"replacement goes into the run holding the start of "
                    f"the match and the text after the marker is emptied, "
                    f"so the marker MOVES to the end of {new[:30]!r}. "
                    f"Nothing downstream shows that: the words read in "
                    f"the same order and the note still resolves. Anchor "
                    f"on one side of the marker, or pass allow_notes=True.")

    edits, first = [], True
    for idx, ((start, stop), run) in enumerate(zip(spans, runs, strict=True)):
        if stop <= at or start >= end:
            continue
        run_xml = run.group(0)
        body = visible_text(run_xml)
        tail = body[end - start:] if stop > end else ""
        if first:
            if not allow_hyperlink and labels_a_link(run):
                raise AnchorError(
                    "replace_in_para: the match starts inside a hyperlink "
                    "run -- the replacement would bleed into the link. "
                    "Anchor on plain text outside the link.")
            # The opt-in above answers "may this match touch a link?".
            # It must not also answer "may the label ABSORB text?" — the
            # whole replacement lands in this run, so a match that runs
            # on past the link ends with the label owning words that
            # were outside it (Parental Style's Table 4 caption, two
            # thirds of it drawn as a link).
            if (labels_a_link(run) and not grow_link_label
                    and end > label_extent(idx)[1]):
                raise AnchorError(
                    "replace_in_para: the match starts in a hyperlink's "
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
            if not allow_hyperlink and labels_a_link(run):
                raise AnchorError(
                    "replace_in_para: the match spans a hyperlink -- "
                    f"emptying {visible_text(run_xml)[:30]!r} would leave "
                    "the link with no label, which no text diff shows and "
                    "no link check catches. Replace on each side of the "
                    "link separately.")
            edits.append((run, set_run_text(run_xml, tail)))

    out = para_xml
    for run, replacement in reversed(edits):
        out = out[:run.start()] + replacement + out[run.end():]
    return out


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
    inner = [r for r in runs if span[0] <= r.start() < span[1]
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
    """
    runs, spans, cursor = [], [], 0
    for r in RUN_RE.finditer(para_xml):
        runs.append(r)
        body = visible_text(r.group(0))
        spans.append((cursor, cursor + len(body)))
        cursor += len(body)
    if at < 0 or at > cursor:
        raise AnchorError(
            f"insert_in_para: offset {at} is outside the paragraph's "
            f"{cursor} visible characters")
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
    if not runs:
        close = para_xml.rindex("</w:p>")
        return para_xml[:close] + content + para_xml[close:]
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
        if not allowed and any(lo <= run.start() < hi for lo, hi in regions):
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
