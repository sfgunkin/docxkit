r"""Comparing what :mod:`docxkit._compare_read` produced.

Layer 2 of :mod:`docxkit.compare`: one function per layer of the report
(text, formatting, formula, fields, hyperlink labels, integrity), and
the paragraph alignment that drives them. Nothing here reads a file and
nothing here prints.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from ._compare_read import (
    P_RE,
    WT_RE,
    Doc,
    Para,
    _fields,
)
from ._xml import BOOKMARK_END_ID_RE, normalize_glyphs

#: A report is buckets of entries: dicts for the layers, plain strings
#: for INTEGRITY. Typed loosely on purpose — it is written straight to
#: JSON, and papers read it with `report["text"]`.
Report = dict[str, list[Any]]

#: The layers whose entries are REAL differences and raise the exit code
#: under --expect-clean. Hyperlink labels, comments and glyph residuals
#: are reported for review and deliberately do not gate. Defined once
#: here because the sweep gates on the same four, and two copies of this
#: tuple would be two answers to "did anything change?".
GATED = ("structure", "text", "formula", "format")

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
        if tag == "equal":
            continue
        o, n = " ".join(aw[i1:i2]), " ".join(bw[j1:j2])
        if tag == "replace":
            out.append(f'"{o}" -> "{n}"')
        elif tag == "delete":
            out.append(f'DEL "{o}"')
        else:
            out.append(f'INS "{n}"')
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


def formula_diff(
    pa: Para, pb: Para,
) -> list[tuple[str, bool, tuple[str, str], tuple[str, str]]]:
    """(kind, glyph_only, before, after) per differing equation.

    `glyph_only` is True when the sole difference is a glyph
    normalization (the math minus U+2212 against a hyphen the user's
    Word produced) — an artifact rather than an edit, so the
    generator's glyph is the one to keep.
    """
    out: list[tuple[str, bool, tuple[str, str], tuple[str, str]]] = []
    for i in range(max(len(pa.omml), len(pb.omml))):
        ea = pa.omml[i] if i < len(pa.omml) else ("", "<none>")
        eb = pb.omml[i] if i < len(pb.omml) else ("", "<none>")
        if ea == eb:
            continue
        kind: list[str] = []
        if ea[1] != eb[1]:
            kind.append("tokens")
        if ea[0] != eb[0]:
            kind.append("structure")
        glyph_only = (ea[0] == eb[0]
                      and _norm_glyph(ea[1]) == _norm_glyph(eb[1]))
        out.append((", ".join(kind), glyph_only, ea, eb))
    return out


def stripped_fields(pa: Para, pb: Para) -> list[str]:
    """Machinery A had and B (same prose) lost — the classic 'Word
    deleted my hyperlink field' failure."""
    notes: list[str] = []
    if len(pa.fields["anchors"]) > len(pb.fields["anchors"]):
        lost = set(pa.fields["anchors"]) - set(pb.fields["anchors"])
        if lost:
            notes.append(f"lost hyperlink target(s): {sorted(lost)}")
    if len(pa.fields["cites"]) > len(pb.fields["cites"]):
        lost = set(pa.fields["cites"]) - set(pb.fields["cites"])
        if lost:
            notes.append(f"lost citation bookmark(s): {sorted(lost)}")
    if pa.fields["footnotes"] > pb.fields["footnotes"]:
        gone = pa.fields["footnotes"] - pb.fields["footnotes"]
        notes.append(f"lost {gone} footnote ref(s)")
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
    # at all on a conforming document — which reads as "balanced".
    bs = re.findall(
        r'<w:bookmarkStart\b[^>]*w:id="(\d+)"[^>]*?(?:\s+w:name="([^"]*)")?',
        xml)
    be = BOOKMARK_END_ID_RE.findall(xml)
    starts, ends = Counter(i for i, _ in bs), Counter(be)
    imbalance = [i for i in set(starts) | set(ends)
                 if starts[i] != ends[i]]
    if imbalance:
        issues.append(f"{label}: bookmark id imbalance {imbalance}")
    known = set(names) | {n for _, n in bs if n}
    anchors = set(re.findall(r'w:anchor="([^"]+)"', xml)) | \
        set(re.findall(r'HYPERLINK[^"]*"([^"]+)"', xml))
    dangling = sorted(a for a in anchors if a not in known)
    if dangling:
        issues.append(f"{label}: dangling anchors (no bookmark) {dangling}")
    # An unbalanced HYPERLINK field renders as literal field code.
    for p in P_RE.findall(xml):
        depth = 0
        for m in re.finditer(r'<w:fldChar w:fldCharType="(begin|end)"/>', p):
            depth += 1 if m.group(1) == "begin" else -1
        if depth != 0:
            text = html.unescape("".join(WT_RE.findall(p)))[:40]
            issues.append(f"{label}: unbalanced field ({depth:+d}) in "
                          f"{text!r}")
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
_FIELD_END_RE = (r'<w:r\b[^>]*>(?:<w:rPr\b(?:[^<]|<(?!/w:rPr>))*</w:rPr>|'
                 r'<w:rPr\b[^>]*/>)?<w:fldChar w:fldCharType="end"/>')


def hyperlink_labels(xml: str) -> Counter[str]:
    """Visible text of every hyperlink, element form and field form.

    A label that bled — a content-fix that dumped prose into a link run
    — shows up here as a changed label even though the prose text still
    matches, which is why this layer exists alongside TEXT.
    """
    labels: list[str] = []
    for m in re.finditer(r"<w:hyperlink\b[^>]*>(.*?)</w:hyperlink>", xml,
                         re.DOTALL):
        labels.append(html.unescape("".join(WT_RE.findall(m.group(1)))))
    for m in re.finditer(r'<w:fldChar w:fldCharType="separate"/>\s*</w:r>'
                         r"(.*?)" + _FIELD_END_RE, xml, re.DOTALL):
        labels.append(html.unescape("".join(WT_RE.findall(m.group(1)))))
    return Counter(labels)


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

    __slots__ = ("deleted", "inserted", "report", "where")

    def __init__(self, report: Report, where: str) -> None:
        self.report = report
        self.where = where
        self.deleted: list[Para] = []
        self.inserted: list[Para] = []

    def place(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Stamp an entry with its part, unless it is the body — a
        body-only document must read as it did before parts existed."""
        if self.where != "body":
            entry["part"] = self.where
        return entry

    def add(self, bucket: str, entry: dict[str, Any]) -> None:
        self.report[bucket].append(self.place(entry))

    def matched(self, pa: Para, pb: Para) -> None:
        """Two paragraphs the alignment considers to be the same one."""
        for seg, old, new in fmt_diff(pa, pb):
            self.add("format", {"text": seg, "from": sorted(old),
                                "to": sorted(new)})
        for kind, glyph_only, ea, eb in formula_diff(pa, pb):
            self.add("formula_glyph" if glyph_only else "formula",
                     {"change": kind, "from": ea, "to": eb})
        if pa.text != pb.text:          # equal under glyph-norm only
            self.add("glyph", {"from": pa.text[:120], "to": pb.text[:120]})

    def replaced(self, left: list[Para], right: list[Para]) -> None:
        """A replace run: pair positionally, word-diff EVERY paragraph.

        Never truncated and never summarised — a block reported as
        changed that listed only its first difference is the "para 9-11"
        class of misses this layer exists to prevent.
        """
        for off in range(max(len(left), len(right))):
            pa = left[off] if off < len(left) else None
            pb = right[off] if off < len(right) else None
            if pa is None:
                if pb is not None:
                    self.inserted.append(pb)
                continue
            if pb is None:
                self.deleted.append(pa)
                continue
            if _norm_glyph(pa.text) == _norm_glyph(pb.text):
                self.add("glyph", {"from": pa.text[:120],
                                   "to": pb.text[:120]})
                continue
            entry = self.place({"context": pa.text[:60],
                                "word_diff": word_diff(pa.text, pb.text)})
            strip = stripped_fields(pa, pb)
            if strip:
                entry["WARNING_stripped"] = strip
                self.add("stripped_fields", {"context": pa.text[:60],
                                             "lost": strip})
            changed = [k for k, glyph, _, _ in formula_diff(pa, pb)
                       if not glyph]
            if changed:
                entry["formula"] = changed
            self.report["text"].append(entry)

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
                                           "text": da.text[:90]})
                    matched.add(id(ib))
                    matched.add(id(da))
                    break
        for da in self.deleted:
            if id(da) not in matched:
                self.add("structure", {"type": "DELETE",
                                       "text": da.text[:110],
                                       "lost_fields": _fields(da.xml)})
        for ib in self.inserted:
            if id(ib) not in matched:
                self.add("structure", {"type": "INSERT",
                                       "text": ib.text[:110]})


def compare_paras(a: list[Para], b: list[Para], report: Report,
                  where: str = "body") -> Report:
    """Every paragraph layer, for ONE pair of parts.

    Paragraphs are matched WITHIN a part: a running head is not a
    candidate match for a body sentence, and pooling them would invent
    moves between the two.

    Two passes of difflib, not one. The outer pass aligns on
    glyph-normalised text; inside a replace block it runs again over
    that block alone, because difflib's opcodes over a whole manuscript
    call a reworded paragraph and its unchanged neighbours one big
    replacement, and the second pass separates them.
    """
    align = _Alignment(report, where)
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
            inner = SequenceMatcher(
                None, [_norm_glyph(p.text) for p in a[i1:i2]],
                [_norm_glyph(p.text) for p in b[j1:j2]], autojunk=False)
            for t2, a1, a2, b1, b2 in inner.get_opcodes():
                if t2 == "equal":
                    for off in range(a2 - a1):
                        align.matched(a[i1 + a1 + off], b[j1 + b1 + off])
                elif t2 == "delete":
                    align.deleted += a[i1 + a1:i1 + a2]
                elif t2 == "insert":
                    align.inserted += b[j1 + b1:j1 + b2]
                else:
                    align.replaced(a[i1 + a1:i1 + a2], b[j1 + b1:j1 + b2])

    align.structure()
    return report


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
