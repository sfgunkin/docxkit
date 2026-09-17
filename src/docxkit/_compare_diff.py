r"""Comparing what :mod:`docxkit._compare_read` produced.

Layer 2 of :mod:`docxkit.compare`: one function per layer of the report
(text, formatting, formula, fields, hyperlink labels, integrity), and
the paragraph alignment that drives them. Nothing here reads a file and
nothing here prints.
"""
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from collections.abc import Collection
from difflib import SequenceMatcher
from typing import Any, Literal, NamedTuple

from ._compare_read import (
    P_RE,
    WT_RE,
    Doc,
    Para,
    _fields,
)
from ._xml import (
    BOOKMARK_END_ID_RE,
    BOOKMARK_START_ID_RE,
    INSTR_ANCHOR_RE,
    INSTR_RE,
    normalize_glyphs,
)

#: A report is buckets of entries: dicts for the layers, plain strings
#: for INTEGRITY. Typed loosely on purpose — it is written straight to
#: JSON, and papers read it with `report["text"]`.
Report = dict[str, list[Any]]

#: The layers whose entries are REAL differences and raise the exit code
#: under --expect-clean. Hyperlink labels, comments and glyph residuals
#: are reported for review and deliberately do not gate. Defined once
#: here because the sweep gates on the same four, and two copies of this
#: tuple would be two answers to "did anything change?".
#:
#: `formula_format` gates: an author who made a variable upright made an
#: edit, and a rebuild that drops it has lost one. It is a separate
#: bucket from `formula` because "the equation now says something else"
#: and "the equation is set differently" want different responses.
#: Every bucket a report carries. Stated once because it was stated
#: twice — `compare_docs` built the dict and `tests/test_compare.py`
#: built its own copy for the renderer, so the PARAGRAPH layer passed
#: its unit tests and raised KeyError on every real report.
BUCKETS = ("structure", "text", "glyph", "formula", "formula_glyph",
           "formula_format", "format", "paragraph", "hyperlinks",
           "integrity", "stripped_fields", "comments", "media")

#: `paragraph` gates too, and that is the whole point of it: the layer
#: was added because `--expect-clean` printed OK over 7 reference
#: entries that had lost their hanging indent. A layer that reports and
#: does not gate would have printed the same OK.
GATED = ("structure", "text", "formula", "formula_format", "format",
         "paragraph", "media")

_norm_glyph = normalize_glyphs


def word_diff(a: str, b: str) -> list[str]:
    # autojunk=False, as the paragraph-level matchers below already do.
    # With it left on, difflib treats any token filling >1% of a long
    # sequence as noise — "the", "of", a repeated technical phrase — and
    # a one-word edit in a long repetitive paragraph comes back as one
    # enormous replace block instead of the word that changed. Measured
    # on a 440-word paragraph with a single word altered: the whole
    # paragraph was reported as replaced. That is a report a human
    # cannot audit, which is the only thing this function is for.
    aw, bw = a.split(), b.split()
    sm = SequenceMatcher(None, aw, bw, autojunk=False)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":                  # unchanged words: not an edit
            continue
        o, n = " ".join(aw[i1:i2]), " ".join(bw[j1:j2])
        if tag == "replace":
            out.append(f'"{o}" -> "{n}"')
        elif tag == "delete":               # words only `a` has
            out.append(f'DEL "{o}"')
        else:
            out.append(f'INS "{n}"')
    return out


def edge_diff(pa: Para, pb: Para) -> list[str]:
    """The whitespace a paragraph opens or closes on, when it moved.

    Word prints a leading space as an INDENT, and nothing else in this
    layer can see one: `Para.text` is stripped for the matchers, and
    `word_diff` tokenises on whitespace, so a space added in front of
    the first word changes no token and no gap between tokens. An
    author hand pass that opened A.4 with ` The following…` passed
    `--expect-clean` with `TEXT (none)` and was found on page 32 of the
    render (Aging_Well, 2026-09-11, backlog S1). Interior double spaces
    already failed; the gap was at the paragraph's edge.
    """
    out = []
    for side, a, b in zip(("leading", "trailing"), pa.edges, pb.edges,
                          strict=True):
        if a != b:
            out.append(f"EDGE {side}: {a!r} -> {b!r}")
    return out


def fmt_diff(pa: Para,
             pb: Para) -> list[tuple[str, frozenset[str], frozenset[str]]]:
    """(segment, old flags, new flags) where char formatting differs.

    Requires identical prose text; otherwise returns [], because a
    character-by-character comparison of two different strings reports
    the offset, not the emphasis.
    """
    if pa.wtext_f != pb.wtext_f or len(pa.fmt) != len(pb.fmt):
        return []
    res: list[tuple[str, frozenset[str], frozenset[str]]] = []
    start: int | None = None
    for i in range(len(pa.fmt)):
        if pa.fmt[i] != pb.fmt[i]:
            if start is None:
                start = i
        elif start is not None:
            res.append((pa.wtext_f[start:i], pa.fmt[start], pb.fmt[start]))
            start = None
    if start is not None:
        res.append((pa.wtext_f[start:], pa.fmt[start], pb.fmt[start]))
    return res


def _marker_segments(text: str, before: list[str],
                     after: list[str]) -> list[tuple[str, str, str]]:
    """(symbols, old markers, new markers) per contiguous run of
    characters whose typography differs — the equation-side twin of
    `fmt_diff`, so a report names the symbol that changed rather than
    the whole formula."""
    if len(before) != len(after) or len(before) != len(text):
        return [(text, ",".join(sorted(set(before))),
                 ",".join(sorted(set(after))))]
    segs: list[tuple[str, str, str]] = []
    start: int | None = None
    for i in range(len(before)):
        if before[i] != after[i]:
            if start is None:
                start = i
        elif start is not None:
            segs.append((text[start:i], before[start], after[start]))
            start = None
    if start is not None:
        segs.append((text[start:], before[start], after[start]))
    return segs


class FormulaChange(NamedTuple):
    """One equation that differs, and in which of the three ways."""

    kind: str                    # "tokens", "structure", "formatting"
    glyph_only: bool
    before: tuple[str, str]      # (skeleton, tokens)
    after: tuple[str, str]
    fmt_before: list[str]        # per-character typography, which is
    fmt_after: list[str]         # what "formatting" means here

    @property
    def bucket(self) -> str:
        if self.glyph_only:
            return "formula_glyph"
        return "formula_format" if self.kind == "formatting" else "formula"

    def entry(self) -> dict[str, Any]:
        """What the report shows. For a typography change the skeleton
        and tokens are identical by definition, so printing them would
        show two identical sides; the symbols whose markers moved are
        what a reader needs."""
        if self.kind != "formatting":
            return {"change": self.kind, "from": self.before,
                    "to": self.after}
        segs = _marker_segments(self.before[1], self.fmt_before,
                                self.fmt_after)
        return {"change": self.kind,
                "from": ", ".join(f"{t}:{a or 'plain'}" for t, a, _ in segs),
                "to": ", ".join(f"{t}:{b or 'plain'}" for t, _, b in segs)}


def formula_diff(pa: Para, pb: Para) -> list[FormulaChange]:
    """Every equation that differs, in the three ways one can.

    `glyph_only` is True when the sole difference is a glyph
    normalization (the math minus U+2212 against a hyphen the user's
    Word produced) — an artifact rather than an edit, so the
    generator's glyph is the one to keep.

    Typography is consulted ONLY when the skeleton and the tokens both
    match. Otherwise an equation that was genuinely rewritten would be
    reported twice, once for its content and once for the formatting
    that moved with it.
    """
    out: list[FormulaChange] = []
    for i in range(max(len(pa.omml), len(pb.omml))):
        ea = pa.omml[i] if i < len(pa.omml) else ("", "<none>")
        eb = pb.omml[i] if i < len(pb.omml) else ("", "<none>")
        fa = pa.omml_fmt[i] if i < len(pa.omml_fmt) else []
        fb = pb.omml_fmt[i] if i < len(pb.omml_fmt) else []
        if ea == eb:
            if fa != fb:
                out.append(FormulaChange("formatting", False, ea, eb,
                                         fa, fb))
            continue
        kind: list[str] = []
        if ea[1] != eb[1]:
            kind.append("tokens")
        if ea[0] != eb[0]:
            kind.append("structure")
        glyph_only = (ea[0] == eb[0]
                      and _norm_glyph(ea[1]) == _norm_glyph(eb[1]))
        out.append(FormulaChange(", ".join(kind), glyph_only, ea, eb,
                                 fa, fb))
    return out


def stripped_fields(pa: Para, pb: Para) -> list[str]:
    """Machinery A had and B (same prose) lost — the classic 'Word
    deleted my hyperlink field' failure.

    The pair form. :func:`stripped_block` is what the alignment uses:
    inside a replace run the pairing is positional, and a pair is the
    wrong unit to ask this of.
    """
    return [note for note, _ in stripped_block([pa], [pb])]


def stripped_block(left: list[Para], right: list[Para], *,
                   present: Collection[str] = (),
                   ) -> list[tuple[str, Para | None]]:
    """Machinery the whole block had and lost, with the paragraph that
    held it.

    Asked of the BLOCK because that is the unit the answer is true of. A
    link the author moved to the next paragraph — or one that only looks
    moved, because an inserted heading shifted the positional pairing by
    one — has not been lost, and saying it has costs a diagnosis every
    time: a dangling-link flag is one this project may never wave away.

    `present` is every name the OTHER SIDE's whole part still carries,
    and a name in it is not lost however far it moved. Measured over 748
    real comparisons, the three rules together are what make this layer
    worth reading:

        per pair    1,463 named lost, 594 of them still in the file  59%
        per block   1,764 named lost, 246 still in the file          86%
        + present   what remains is what is really gone

    It also names MORE true losses than the pair form did (869 -> 1,518):
    a pair whose prose came through glyph-identical never reached the old
    test at all, so machinery lost there was invisible.

    The holder is the LEFT paragraph the target was last seen in, so the
    report can still say where to look. It is None for a footnote count,
    which is a number rather than a name.
    """
    notes: list[tuple[str, Para | None]] = []
    #: `Fields` is a TypedDict, so the key has to stay a literal for the
    #: type checkers to follow it through the loop.
    named: tuple[tuple[Literal["anchors", "cites"], str], ...] = (
        ("anchors", "hyperlink target"), ("cites", "citation bookmark"))

    def holder_of(key: Literal["anchors", "cites"],
                  name: str) -> Para | None:
        return next((p for p in reversed(left) if name in p.fields[key]),
                    None)

    for key, label in named:
        before = Counter(n for p in left for n in p.fields[key])
        after = Counter(n for p in right for n in p.fields[key])
        # Counter subtraction keeps only the positive side: a name whose
        # count merely MOVED between paragraphs cancels out.
        gone = sorted(n for n in (before - after).elements()
                      if n not in present)
        if gone:
            notes.append((f"lost {label}(s): {sorted(set(gone))}",
                          holder_of(key, gone[0])))
    short = (sum(p.fields["footnotes"] for p in left)
             - sum(p.fields["footnotes"] for p in right))
    if short > 0:
        notes.append((f"lost {short} footnote ref(s)", None))
    return notes


# --------------------------------------------------------------- integrity
def bookmark_names(xml: str) -> set[str]:
    return set(re.findall(r'<w:bookmarkStart\b[^>]*w:name="([^"]*)"', xml))


def integrity(xml: str, label: str,
              names: set[str] | None = None) -> list[str]:
    """Structural checks on one part.

    `names` is the bookmark names defined ACROSS THE PACKAGE. Bookmarks
    are package-wide but were resolved against the body alone, so a
    footnote's citation link — pointing at a reference-list bookmark in
    document.xml — reads as dangling the moment footnotes are checked.
    Omitting it falls back to this part's own names (the old behaviour).
    """
    issues: list[str] = []
    if names is None:
        names = bookmark_names(xml)
    # `\b[^>]*` before each w:id: attribute order is not meaningful in
    # XML, and hard-coding it made the INTEGRITY layer find no bookmarks
    # at all on a conforming document — which reads as "balanced". The
    # names are read on their own for the same reason: an optional
    # `w:name` straight after `w:id` named nothing on a start written
    # name-first, and its links read as dangling (2026-09-17).
    starts = Counter(BOOKMARK_START_ID_RE.findall(xml))
    ends = Counter(BOOKMARK_END_ID_RE.findall(xml))
    imbalance = [i for i in set(starts) | set(ends)
                 if starts[i] != ends[i]]
    if imbalance:
        issues.append(f"{label}: bookmark id imbalance {imbalance}")
    known = set(names) | bookmark_names(xml)
    # REASSEMBLE THE FIELD INSTRUCTION BEFORE READING ITS TARGET. Word splits
    # one instruction across runs on save — `HYPERLINK` in the first,
    # ` \l "Munda2009" \h` in the next — and a pattern run over the raw XML
    # then walks straight through the intervening tags: the old
    # `HYPERLINK[^"]*"([^"]+)"` returned the RSID of the following run, and
    # every footnote whose field Word had fragmented reported
    # a dangling anchor named `00C04908`. Join the instrText nodes per
    # paragraph first, exactly as the citation layer does.
    targets: set[str] = set()
    for para_xml in P_RE.findall(xml):
        joined = html.unescape("".join(INSTR_RE.findall(para_xml)))
        targets |= set(INSTR_ANCHOR_RE.findall(joined))
    anchors = set(re.findall(r'w:anchor="([^"]+)"', xml)) | targets
    dangling = sorted(a for a in anchors if a not in known)
    if dangling:
        issues.append(f"{label}: dangling anchors (no bookmark) {dangling}")
    # An unbalanced HYPERLINK field renders as literal field code.
    #
    # A field that spills does so into the paragraph NEXT DOOR, and the
    # paragraph next door is a spacer or a section break with no text in
    # it — so the half of the defect that says WHERE was reported as
    # `in ''`, and locating it took a script counting fldCharType per
    # paragraph (HCW, 2026-08-23). An empty paragraph is named by its
    # position and by the last paragraph that HAS text, which is the
    # same thing the TEXT layer does when it says `in (footnotes, table
    # 3 r2c1)`.
    paras = P_RE.findall(xml)
    last_text = ""
    for i, p in enumerate(paras):
        depth = 0
        # Any spelling of the marker: `<w:fldChar w:fldCharType="begin"
        # />` from another producer, or a locked field's `w:fldLock`, was
        # not counted and left its partner unbalanced.
        for m in re.finditer(r'<w:fldChar\b[^>]*\bw:fldCharType="(begin|end)"'
                             r"[^>]*/>", p):
            depth += 1 if m.group(1) == "begin" else -1
        text = html.unescape("".join(WT_RE.findall(p)))
        if depth != 0:
            where = (f"{text[:40]!r}" if text.strip() else
                     (f"the empty paragraph {i + 1}, after "
                      f"{last_text[:40]!r}" if last_text else
                      f"the empty paragraph {i + 1}"))
            issues.append(f"{label}: unbalanced field ({depth:+d}) in "
                          f"{where}")
        if text.strip():
            last_text = text
    if re.search(r"<w:t[^>]*>[^<]*HYPERLINK[^<]*</w:t>", xml):
        issues.append(f"{label}: literal HYPERLINK field code in body text")
    return issues


#: A field's closing run, whose <w:fldChar end/> may be preceded by run
#: properties. Requiring a BARE run here used to make the label overshoot
#: to the next field's end, so an untouched citation was reported as a
#: 90-character bled link — Word adds an <w:rPr> to that run whenever the
#: author saves (Parental Style, 2026-08-05: three false positives, and
#: the machine build showed none only because it had never been through
#: Word).
#:
#: `(?<!/)>` on both openings: the open-and-shut branch comes first, and
#: an EMPTY `<w:rPr/>` read as its opening ran on to the next `</w:rPr>`
#: — the next field's end run's, when nothing between carries properties
#: — so the match swallowed that field and its label was never read.
_FIELD_END_RE = (r"<w:r\b[^>]*(?<!/)>"
                 r"(?:<w:rPr\b[^>]*(?<!/)>(?:[^<]|<(?!/w:rPr>))*</w:rPr>|"
                 r'<w:rPr\b[^>]*/>)?<w:fldChar\b[^>]*\bw:fldCharType="end"'
                 r"[^>]*/>")


def hyperlink_labels(xml: str) -> Counter[str]:
    """Visible text of every hyperlink, element form and field form.

    A label that bled — a content-fix that dumped prose into a link run
    — shows up here as a changed label even though the prose text still
    matches, which is why this layer exists alongside TEXT.
    """
    # The element form, then the field form, and ONE reading of a label
    # for both: a fix to how a label is read lands on both forms at once.
    # `(?<!/)>`: a self-closing ghost `<w:hyperlink …/>` labels nothing,
    # and read as an open tag it lent the prose up to the NEXT link's close
    # to that link. The field markers in any spelling, as `integrity`
    # counts them.
    forms = (r"<w:hyperlink\b[^>]*(?<!/)>(.*?)</w:hyperlink>",
             r'<w:fldChar\b[^>]*\bw:fldCharType="separate"[^>]*/>\s*</w:r>'
             r"(.*?)" + _FIELD_END_RE)
    return Counter(html.unescape("".join(WT_RE.findall(m.group(1))))
                   for form in forms
                   for m in re.finditer(form, xml, re.DOTALL))


#: Below this, containment is a coincidence rather than a survival: a
#: two-character label sits inside half the prose in the document.
_LABEL_KEEP = 3


def label_moves(gone: Counter[str],
                gained: Counter[str]) -> list[dict[str, Any]]:
    """Pair a label that lost text with the one that gained it.

    Both sides of the same edit, said once. A label that SWALLOWS
    surrounding prose is the S1 defect `edit.replace_in_para` now
    refuses: the replacement is written into the run holding the start
    of the match, so when that run is the link's label the link ends up
    owning every word — Parental Style's Table 4 caption came back with
    two thirds of it drawn blue and underlined, and this layer was the
    ONLY place it was visible.

    It was visible as two unrelated lines, though: ``[built-only] 'Table
    4'`` somewhere in the list and ``[user-only] 'Table 4: The likelihood
    of using non-violent and coercive discipline'`` somewhere else, for
    the reader to correlate. Pairing them names the defect instead.

    Containment decides the pairing, because that is what the mechanism
    leaves: the old label's own text survives inside the new one. Both
    directions are reported — a label that SHRANK is the emptying case
    caught partway, and `citations` reports the fully emptied one as
    EMPTY LINK. `gone` and `gained` are consumed, so a pair is never
    also printed as two singletons.

    A static rule was tried first and measured before shipping: "no
    label may contain a sentence-ending ':' or '.' followed by more
    words" fires **5,378 times across 718 of 1,873 manuscripts**, because
    many papers link the WHOLE caption by convention and the damaged
    label is indistinguishable from that. Restricting it to exhibit
    back-links and to labels that disagree with their own document's
    majority still left 936 in 332. The difference is not a property of
    one document, so only a comparison can see it.
    """
    out: list[dict[str, Any]] = []
    for new in sorted(gained, key=lambda s: (-len(s), s)):
        if len(new) < _LABEL_KEEP:
            continue                        # longest first: so is the rest
        olds = sorted((o for o in gone
                       if len(o) >= _LABEL_KEEP and o != new
                       and (o in new or new in o)),
                      key=lambda s: (-len(s), s))
        for old in olds:
            while gained[new] and gone[old]:
                gained[new] -= 1
                gone[old] -= 1
                side = "grew" if len(new) > len(old) else "shrank"
                out.append({"side": side, "label": old[:90],
                            "to": new[:90], "n": 1})
            if not gained[new]:
                break                       # nothing of it left to pair
    # Counter arithmetic leaves zero counts behind, and `for lab, n in
    # gone.items()` would then print a label nothing lost.
    for counter in (gone, gained):
        for label in [k for k, n in counter.items() if not n]:
            del counter[label]
    return out


# ----------------------------------------------------------------- aligning
class _Alignment:
    """One pair of parts, being aligned paragraph by paragraph.

    The state the alignment carries — which report, which part's label,
    and the paragraphs still looking for a partner — lives here instead
    of being threaded through every helper. The pools are what makes a
    MOVE detectable: a paragraph deleted in one place and inserted in
    another is one edit, not two, and only a pass that has seen both
    ends can say so.
    """

    __slots__ = ("deleted", "inserted", "report", "surviving", "where")

    def __init__(self, report: Report, where: str,
                 surviving: Collection[str] = ()) -> None:
        self.report = report
        self.where = where
        # every field name the OTHER side's part still holds, so a
        # target that moved out of its block is not called lost
        self.surviving = surviving
        self.deleted: list[Para] = []
        self.inserted: list[Para] = []

    def place(self, entry: dict[str, Any],
              at: Para | None = None) -> dict[str, Any]:
        """Stamp an entry with where it happened: its part, unless it is
        the body (a body-only document must read as it did before parts
        existed), and its cell, when it is in a table."""
        if self.where != "body":
            entry["part"] = self.where
        if at is not None and at.at:
            entry["at"] = at.at
        return entry

    def add(self, bucket: str, entry: dict[str, Any],
            at: Para | None = None) -> None:
        self.report[bucket].append(self.place(entry, at))

    def matched(self, pa: Para, pb: Para) -> None:
        """Two paragraphs the alignment considers to be the same one."""
        for seg, old, new in fmt_diff(pa, pb):
            self.add("format", {"text": seg, "from": sorted(old),
                                "to": sorted(new)}, pa)
        # The SYMMETRIC difference, not both sets: a paragraph states
        # half a dozen of these and one of them moved, and printing the
        # five that did not is how a layer becomes unreadable.
        if pa.ppr != pb.ppr:
            self.add("paragraph", {"context": pa.text[:60],
                                   "from": sorted(pa.ppr - pb.ppr),
                                   "to": sorted(pb.ppr - pa.ppr)}, pa)
        for change in formula_diff(pa, pb):
            self.add(change.bucket, change.entry(), pa)
        # A REAL text change, in the TEXT bucket, on a pair the matcher
        # called equal: the matcher reads stripped text, and an edge
        # space is exactly what stripping removes.
        if edges := edge_diff(pa, pb):
            self.add("text", {"context": pa.text[:60], "word_diff": edges},
                     pa)
        if pa.text != pb.text:          # equal under glyph-norm only
            self.add("glyph", {"from": pa.text[:120], "to": pb.text[:120]},
                     pa)

    def replaced(self, left: list[Para], right: list[Para]) -> None:
        """A replace run: pair positionally, word-diff EVERY paragraph.

        Never truncated and never summarised — a block reported as
        changed that listed only its first difference is the "para 9-11"
        class of misses this layer exists to prevent.

        The FIELD question is asked of the BLOCK, not of the pairs. The
        pairing here is positional, so a block of unequal length — one
        inserted heading in front of four rewritten paragraphs — pairs
        every paragraph after the insertion against its NEIGHBOUR, and
        the machinery then reads as lost while it sits one paragraph
        down. That is what put four present targets on the FIELD layer
        of Parental Style's comparison round (2026-08-10), where the
        standing rule that a dangling-link flag must never be waved away
        cost a diagnosis to disprove. Whether a target survived is a
        property of the block; which pair it sat in is not.
        """
        pending: dict[int, list[str]] = defaultdict(list)
        holders: dict[int, Para | None] = {}
        for note, holder in stripped_block(left, right,
                                           present=self.surviving):
            pending[id(holder)].append(note)
            holders[id(holder)] = holder
        for off in range(max(len(left), len(right))):
            pa = left[off] if off < len(left) else None
            pb = right[off] if off < len(right) else None
            if pa is None:
                if pb is not None:
                    self.inserted.append(pb)
                continue
            if pb is None:
                # `structure` reports a DELETE with its `lost_fields`
                # already; a second entry here would be the same loss
                # counted twice.
                pending.pop(id(pa), None)
                self.deleted.append(pa)
                continue
            # No glyph branch here. A `replace` opcode is BY
            # CONSTRUCTION a region with no matching elements, and the
            # matcher's elements ARE the glyph-normalized texts (see
            # `compare_paras`), so a pair inside one can never be
            # glyph-identical — `matched` is where that case lives.
            # There was one, and it was the second piece of dead code
            # this same invariant has produced: it could not be killed
            # by any input, and removing it changes no report.
            entry = self.place({"context": pa.text[:60],
                                "word_diff": word_diff(pa.text, pb.text)
                                + edge_diff(pa, pb)},
                               pa)
            # attributed to the paragraph that HELD the target, so the
            # report still says where to look
            strip = pending.pop(id(pa), [])
            if strip:
                entry["WARNING_stripped"] = strip
                self.add("stripped_fields", {"context": pa.text[:60],
                                             "lost": strip}, pa)
            changed = [c.kind for c in formula_diff(pa, pb)
                       if not c.glyph_only]
            if changed:
                entry["formula"] = changed
            self.report["text"].append(entry)
        # A loss whose paragraph never reached the text layer — its prose
        # came through glyph-identical while its machinery did not — is
        # still a loss, and silence would be worse than an entry with no
        # word diff beside it.
        for key, notes in pending.items():
            holder = holders[key]
            self.add("stripped_fields",
                     {"context": holder.text[:60] if holder else "",
                      "lost": notes}, holder)

    def structure(self) -> None:
        """What is left over: moves first, then plain inserts/deletes."""
        matched: set[int] = set()
        for da in self.deleted:
            for ib in self.inserted:
                if id(ib) in matched:
                    continue
                r = SequenceMatcher(None, _norm_glyph(da.text),
                                    _norm_glyph(ib.text)).ratio()
                if r > 0.85:
                    self.add("structure", {"type": "MOVE",
                                           "ratio": round(r, 3),
                                           "text": da.text[:90]}, da)
                    matched.add(id(ib))
                    matched.add(id(da))
                    break
        for da in self.deleted:
            if id(da) not in matched:
                self.add("structure", {"type": "DELETE",
                                       "text": da.text[:110],
                                       "lost_fields": _fields(da.xml)}, da)
        for ib in self.inserted:
            if id(ib) not in matched:
                self.add("structure", {"type": "INSERT",
                                       "text": ib.text[:110]}, ib)


def compare_paras(a: list[Para], b: list[Para], report: Report,
                  where: str = "body", *,
                  surviving: Collection[str] | None = None) -> Report:
    """Every paragraph layer, for ONE pair of parts.

    Paragraphs are matched WITHIN a part: a running head is not a
    candidate match for a body sentence, and pooling them would invent
    moves between the two.

    ONE pass of difflib, where there used to be two.

    The second pass re-ran SequenceMatcher inside each replace block, on
    the belief that difflib's whole-document opcodes lump a reworded
    paragraph together with its unchanged neighbours. They do not: a
    `replace` opcode is BY CONSTRUCTION a region containing no matching
    elements, because the matching blocks are exactly the `equal`
    opcodes. Re-running the same matcher over it can only return one
    `replace` spanning the whole block — measured over 3,735 replace
    blocks from 4,000 random pairs, every one came back as a single
    opcode — so the inner pass's equal/delete/insert branches were
    unreachable, and its `else` reduced to this call.

    Mutation testing is what surfaced it: 88 mutants sat on those three
    branches and none could be killed, because no input reaches them.
    Reports over 100 real comparisons are byte-identical without it.
    """
    # Package-wide when the caller has the whole package; this part's own
    # names otherwise, which is what a direct caller (a test, a paper's
    # own script) can honestly supply.
    align = _Alignment(report, where,
                       surviving if surviving is not None else
                       {n for p in b for key in ("anchors", "cites")
                        for n in p.fields[key]})
    sm = SequenceMatcher(None, [_norm_glyph(p.text) for p in a],
                         [_norm_glyph(p.text) for p in b], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                align.matched(a[k], b[j1 + (k - i1)])
        elif tag == "delete":
            align.deleted += a[i1:i2]
        elif tag == "insert":
            align.inserted += b[j1:j2]
        elif tag == "replace":
            align.replaced(a[i1:i2], b[j1:j2])

    align.structure()
    return report


def compare_media(a: Doc, b: Doc, report: Report) -> None:
    """Figures, by name and by content.

    Not compared at all until 2026-08-24, while the STRUCTURE layer's
    own header claimed "part added / removed". A figure swapped for a
    different chart, overwritten with a 48-byte stub, or deleted from
    the package reported as zero changes — on the one task whose whole
    deliverable was four replaced images (HCW, filed S1).

    **Paired by NAME, and that is measured rather than assumed.** The
    alternative was pairing by digest to absorb renumbering, and it
    would have hidden the case that matters: two figures whose contents
    swap places keep both names and both digests, and only a name
    pairing calls that two changes. Word does not renumber media parts
    on save — checked over 110 media parts in three real manuscripts,
    every one byte-identical through an open-and-save — so the noise
    the digest pairing would have absorbed does not arrive.

    No pixel diff, deliberately: "content differs, 66,203 -> 69,327
    bytes" is enough to send a person to look, which is all any other
    layer does.
    """
    for name in sorted(set(a.media) | set(b.media)):
        before, after = a.media.get(name), b.media.get(name)
        known = after or before
        label = known.label if known else ""
        if before is not None and after is not None:
            if before.digest != after.digest:
                report["media"].append(
                    {"type": "MEDIA CHANGED", "part": name, "label": label,
                     "from": before.size, "to": after.size})
        elif before is not None:
            report["media"].append(
                {"type": "MEDIA REMOVED", "part": name, "label": label,
                 "from": before.size, "to": 0})
        elif after is not None:
            report["media"].append(
                {"type": "MEDIA ADDED", "part": name, "label": label,
                 "from": 0, "to": after.size})


def compare_comments(a: Doc, b: Doc, report: Report) -> None:
    """Comments present on one side only — REVIEW, never gated.

    An author round legitimately adds comments the build cannot have, so
    gating on them would make --expect-clean unreachable; a comment the
    author left is still something the integrator must see before
    calling the round finished (`docxkit tasks` is the fuller view).
    """
    ca = Counter(f"{author}: {text}" for _, author, text in a.comments)
    cb = Counter(f"{author}: {text}" for _, author, text in b.comments)
    for note, n in (ca - cb).items():
        report["comments"].append({"side": "built-only", "text": note[:110],
                                   "n": n})
    for note, n in (cb - ca).items():
        report["comments"].append({"side": "user-only", "text": note[:110],
                                   "n": n})
