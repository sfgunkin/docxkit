#!/usr/bin/env python
r"""compare_docx.py — authoritative multi-layer diff between two .docx files.

Built for the `integrate-edits` workflow: compare a freshly *built* document
(from the generation script / source) against the *user-edited* document and
surface EVERY change across every layer, so none is lost.

It compares two .docx files directly (not a docx-vs-script), so it is
architecture-agnostic: it works whether the doc is produced by a python-docx
script (mkp/omath helpers) or a raw-`document.xml` transform (e.g. AFI's
build_v10 + v9_prose_edits.json + an OMML generator).

Parts compared
  Every part a reader sees: document.xml, footnotes, endnotes, and each
  header and footer — paired part by part, so a header paragraph is never
  matched against a body one. Comments are read too, but reported for
  review rather than gated. Cached PAGE/DATE field results are masked
  first: Word stores whatever page an instance last rendered on, and two
  copies of one document disagree (see VOLATILE_FIELDS).

Layers reported
  STRUCTURE  paragraph insert / delete / MOVE (a delete whose text reappears
             as an insert elsewhere), and a whole part added or removed
  TEXT       word-level diff of EVERY paragraph in each replace block
             (never truncated — the para 9-11 class of misses)
  GLYPH      text diffs that vanish under minus/asterisk/quote normalization
             are split out as likely Word artifacts (U+2212->-, ∗->*, curly
             quotes) — usually NOT user edits; keep the generator's glyph
  FORMULA    per-equation OMML: token stream AND structural skeleton
             (sSub/sSup/nary/f/d/rad/...). Catches the omath_display blind
             spot and structure-only rewrites
  FORMAT     character-level run formatting (italic/bold/super/sub/strike/
             smallCaps) on text-matched paragraphs, ignoring Hyperlink styling
  INTEGRITY  bookmark start/end balance, dangling hyperlink anchors, cite_/ref_
             pairing, and citation/footnote fields STRIPPED by Word's edit
             (a paragraph that had a field in A but is plain text in B)

Usage
  python compare_docx.py BUILT.docx USER_EDITED.docx
  python compare_docx.py BUILT.docx USER_EDITED.docx --json report.json
  python compare_docx.py BUILT.docx USER_EDITED.docx --expect-clean
        # exit 1 if any non-glyph difference remains (use to gate the
        # rebuild->verify loop: after integration this MUST pass)

Conventions: A = first file = the BUILT/baseline doc; B = second = USER-edited.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import zipfile
from collections import Counter
from difflib import SequenceMatcher

# One glyph table for the whole toolkit. While compare and ingest
# each kept their own copy they drifted apart on U+00A0, so this
# gate called a non-breaking-space change a Word artifact while
# ingest treated the same change as an author edit.
# field_spans likewise: THE field walk, depth-matched for nesting. A
# fourth local copy is how the other three came to disagree.
from ._cite_repair import field_spans
from ._xml import BOOKMARK_END_ID_RE, GLYPH_MAP, T_PARTS_RE, normalize_glyphs
from .comments import read_all as _read_comments

# ----------------------------------------------------------------- extraction
P_RE = re.compile(r"<w:p[ >].*?</w:p>", re.DOTALL)
WT_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
MT_RE = re.compile(r"<m:t[^>]*>([^<]*)</m:t>")
OMATH_RE = re.compile(r"<m:oMath>.*?</m:oMath>", re.DOTALL)
RUN_RE = re.compile(r"<w:r\b[^>]*>(.*?)</w:r>", re.DOTALL)
RPR_RE = re.compile(r"<w:rPr>(.*?)</w:rPr>", re.DOTALL)
PARAID_RE = re.compile(r'w14:paraId="([0-9A-Fa-f]+)"')
# structural OMML elements that change a formula's meaning/shape
OMML_STRUCT = ("sSub", "sSup", "sSubSup", "nary", "f", "d", "rad", "func",
               "acc", "bar", "groupChr", "limLow", "limUpp", "m", "eqArr", "box")
OMML_STRUCT_RE = re.compile(r"<m:(" + "|".join(OMML_STRUCT) + r")\b")

_norm_glyph = normalize_glyphs


def _flags(rpr: str | None) -> frozenset:
    if not rpr:
        return frozenset()
    f = set()

    def on(tag):
        m = re.search(rf'<w:{tag}(?:/>|\s+w:val="([^"]*)"\s*/>)', rpr)
        return bool(m) and (m.group(1) not in ("0", "false", "none"))

    for tag, name in (("i", "italic"), ("b", "bold"), ("strike", "strike"),
                      ("smallCaps", "smallCaps")):
        if on(tag):
            f.add(name)
    va = re.search(r'<w:vertAlign w:val="([^"]+)"/>', rpr)
    if va:
        f.add(va.group(1))
    return frozenset(f)


def _char_fmt(p_xml: str):
    """Per-character formatting over the prose (<w:t>) text. Hyperlink-styled
    runs contribute empty formatting (their underline/colour is structural)."""
    text, fmt = [], []
    for run in RUN_RE.finditer(p_xml):
        body = run.group(1)
        rpr_m = RPR_RE.search(body)
        rpr = rpr_m.group(1) if rpr_m else None
        is_hyper = bool(rpr) and 'w:val="Hyperlink"' in rpr
        fs = frozenset() if is_hyper else _flags(rpr)
        for t in WT_RE.findall(body):
            for ch in html.unescape(t):
                text.append(ch)
                fmt.append(fs)
    return "".join(text), fmt


def _omml(p_xml: str):
    """List of (struct_skeleton, token_stream) for each oMath in the paragraph."""
    out = []
    for m in OMATH_RE.finditer(p_xml):
        block = m.group(0)
        skel = "/".join(OMML_STRUCT_RE.findall(block))
        toks = html.unescape("".join(MT_RE.findall(block)))
        out.append((skel, toks))
    return out


def _fields(p_xml: str):
    """Citation/cross-ref machinery present in the paragraph."""
    anchors = re.findall(r'w:anchor="([^"]+)"', p_xml)
    hl = re.findall(r'HYPERLINK[^"]*"([^"]+)"', p_xml)
    cites = re.findall(r'w:name="(cite_[^"]+)"', p_xml)
    fns = p_xml.count("w:footnoteReference")
    return {"anchors": anchors + hl, "cites": cites, "footnotes": fns}


class Para:
    __slots__ = ("xml", "wtext", "wtext_f", "mtext", "text", "fmt", "omml",
                 "fields", "pid")

    def __init__(self, xml: str):
        self.xml = xml
        self.wtext = html.unescape("".join(WT_RE.findall(xml)))
        self.mtext = html.unescape("".join(MT_RE.findall(xml)))
        self.text = (self.wtext + self.mtext).strip()
        self.wtext_f, self.fmt = _char_fmt(xml)
        self.omml = _omml(xml)
        self.fields = _fields(xml)
        m = PARAID_RE.search(xml)
        self.pid = m.group(1) if m else None


# ---------------------------------------------------------------- the parts
#: Every part that carries prose a reader sees. Until 2026-08-06 this
#: comparison covered `word/document.xml` ALONE: footnotes.xml was read
#: and then dropped on the floor (its locals were never used), and
#: headers, footers and endnotes were never opened. Across the 507 real
#: manuscripts here that is 1,111 header/footer parts, 340 footnote parts
#: and 306 endnote parts the authoritative gate certified as "unchanged"
#: without ever looking at them — a false negative in the one tool whose
#: whole job is to certify that no edit was lost.
TEXT_PART_RE = re.compile(
    r"^word/(document|footnotes|endnotes|header\d*|footer\d*)\.xml$")
COMMENTS_PART = "word/comments.xml"

#: Report order, so two runs list their parts the same way.
_PART_RANK = ("document", "footnotes", "endnotes", "header", "footer")

#: Field types whose cached RESULT is a rendering artifact, not content.
#: Word stores the page an instance last happened to be laid out on, so
#: two copies of one document disagree: in this corpus DSI's footer1.xml
#: caches "2" in 34 files and "11" in 38, and LI's caches "2", "1",
#: "Page 1" and "Page  of" (that last from a field never rendered).
#: Diffing those raw would have failed every paper's --expect-clean on
#: the day headers were included. Only the RESULT is masked — the field
#: code is left alone, so a field the author replaced with typed text
#: still reports as a text change.
VOLATILE_FIELDS = frozenset({
    "PAGE", "NUMPAGES", "SECTIONPAGES", "PAGEREF", "DATE", "TIME",
    "CREATEDATE", "SAVEDATE", "PRINTDATE", "EDITTIME", "REVNUM",
    "FILENAME", "FILESIZE", "LASTSAVEDBY", "NUMCHARS", "NUMWORDS",
})

INSTR_RE = re.compile(r"<w:instrText[^>]*>([^<]*)</w:instrText>")
SEPARATE_RE = re.compile(r'<w:fldChar\b[^>]*w:fldCharType="separate"[^>]*/>')
FLDSIMPLE_RE = re.compile(
    r'<w:fldSimple\b[^>]*w:instr="([^"]*)"[^>]*>(?:(?!</?w:fldSimple).)*'
    r"</w:fldSimple>", re.DOTALL)


def _keyword(instr: str) -> str:
    """A field instruction's type: ' PAGE  \\* MERGEFORMAT ' -> 'PAGE'."""
    words = html.unescape(instr).split()
    return words[0].upper() if words else ""


def _mask_text(xml: str, token: str) -> str:
    """Replace the <w:t> text in `xml` with `token`, once."""
    state = {"first": True}

    def sub(m):
        keep = token if state["first"] else ""
        state["first"] = False
        return m.group(1) + keep + m.group(3)

    return T_PARTS_RE.sub(sub, xml)


def mask_volatile_fields(xml: str) -> str:
    """Neutralise cached PAGE/DATE/... results, leaving the field intact."""
    regions: list[tuple[int, int, str]] = []
    for start, end, body in field_spans(xml):
        kw = _keyword(" ".join(INSTR_RE.findall(body)))
        if kw not in VOLATILE_FIELDS:
            continue
        sep = SEPARATE_RE.search(body)
        if not sep:                      # no cached result to mask
            continue
        result_at = start + sep.end()
        # field_spans yields outermost-first, so a nested field inside a
        # region already claimed is covered by it.
        if regions and result_at < regions[-1][1]:
            continue
        regions.append((result_at, end, kw))
    out = xml
    for s, e, kw in reversed(regions):   # right to left: offsets stay valid
        out = out[:s] + _mask_text(out[s:e], f"«F:{kw}»") + out[e:]
    return FLDSIMPLE_RE.sub(
        lambda m: (m.group(0) if _keyword(m.group(1)) not in VOLATILE_FIELDS
                   else _mask_text(m.group(0),
                                   f"«F:{_keyword(m.group(1))}»")),
        out)


class Part:
    """One text-bearing part, with its paragraphs already extracted."""

    __slots__ = ("name", "label", "xml", "paras", "blob")

    def __init__(self, name: str, xml: str):
        self.name = name
        stem = name[len("word/"):-len(".xml")]
        # The body keeps an unlabelled report: a body-only document must
        # read exactly as it did before parts existed.
        self.label = "body" if stem == "document" else stem
        self.xml = mask_volatile_fields(xml)
        self.paras = [p for p in (Para(x) for x in P_RE.findall(self.xml))
                      if p.text]
        self.blob = " ".join(p.text for p in self.paras)


class Doc:
    __slots__ = ("path", "parts", "comments")

    def __init__(self, path: str, parts: list[Part],
                 comments: list[tuple[str, str, str]]):
        self.path = path
        self.parts = parts
        self.comments = comments


def _rank(name: str) -> tuple[int, str]:
    stem = name[len("word/"):-len(".xml")]
    for i, kind in enumerate(_PART_RANK):
        if stem.startswith(kind):
            return (i, name)
    return (len(_PART_RANK), name)


def load_parts(raw: dict[str, bytes], path: str = "") -> Doc:
    """The parts dict view, so a caller holding a package (the sweep, a
    build in memory) can diff without writing a file first."""
    parts = [Part(n, raw[n].decode("utf-8"))
             for n in sorted(raw, key=_rank) if TEXT_PART_RE.match(n)]
    return Doc(path, parts, _read_comments(raw))


def load(path: str) -> Doc:
    with zipfile.ZipFile(path) as z:
        raw = {n: z.read(n) for n in z.namelist()
               if TEXT_PART_RE.match(n) or n == COMMENTS_PART}
    return load_parts(raw, path)


def pair_parts(a: list[Part], b: list[Part]):
    """(A part, B part) pairs; None on either side means it exists once.

    Name first — document/footnotes/endnotes are fixed names and always
    pair. Headers and footers are NOT: their numbering follows the
    section that references them, so a section edit renumbers header2 to
    header3 and a name-only pairing would report both as
    added-and-removed. Leftovers therefore pair on text similarity.
    """
    b_by_name = {p.name: p for p in b}
    pairs: list[tuple[Part | None, Part | None]] = []
    matched: set[str] = set()
    spare_a: list[Part] = []
    for pa in a:
        pb = b_by_name.get(pa.name)
        if pb is None:
            spare_a.append(pa)
        else:
            pairs.append((pa, pb))
            matched.add(pb.name)
    spare_b = [pb for pb in b if pb.name not in matched]

    for pa in list(spare_a):
        best, score = None, 0.0
        for pb in spare_b:
            r = SequenceMatcher(None, pa.blob, pb.blob, autojunk=False).ratio()
            if r > score:
                best, score = pb, r
        if best is not None and score >= 0.6:
            pairs.append((pa, best))
            spare_a.remove(pa)
            spare_b.remove(best)
    pairs.extend((pa, None) for pa in spare_a)
    pairs.extend((None, pb) for pb in spare_b)
    return pairs


# -------------------------------------------------------------------- diffing
def word_diff(a: str, b: str):
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
    out = []
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


def fmt_diff(pa: Para, pb: Para):
    """Return list of (segment_text, old_flags, new_flags) where char formatting
    differs. Requires identical prose text; otherwise returns []."""
    if pa.wtext_f != pb.wtext_f or len(pa.fmt) != len(pb.fmt):
        return []
    res, s = [], None
    for i in range(len(pa.fmt)):
        if pa.fmt[i] != pb.fmt[i]:
            if s is None:
                s = i
        elif s is not None:
            res.append((pa.wtext_f[s:i], pa.fmt[s], pb.fmt[s]))
            s = None
    if s is not None:
        res.append((pa.wtext_f[s:], pa.fmt[s], pb.fmt[s]))
    return res


def formula_diff(pa: Para, pb: Para):
    """Returns (kind, glyph_only, ea, eb) per differing equation. glyph_only
    is True when the sole difference is a glyph normalization (e.g. the math
    minus U+2212 vs a hyphen the user's Word produced) — those are artifacts,
    not edits, so the generator's correct glyph should be kept."""
    out = []
    n = max(len(pa.omml), len(pb.omml))
    for i in range(n):
        ea = pa.omml[i] if i < len(pa.omml) else ("", "<none>")
        eb = pb.omml[i] if i < len(pb.omml) else ("", "<none>")
        if ea == eb:
            continue
        kind = []
        if ea[1] != eb[1]:
            kind.append("tokens")
        if ea[0] != eb[0]:
            kind.append("structure")
        glyph_only = (ea[0] == eb[0]
                      and _norm_glyph(ea[1]) == _norm_glyph(eb[1]))
        out.append((", ".join(kind), glyph_only, ea, eb))
    return out


def stripped_fields(pa: Para, pb: Para):
    """Citation/footnote machinery that A had and B (same prose) lost — the
    classic 'Word deleted my hyperlink field' failure."""
    notes = []
    if len(pa.fields["anchors"]) > len(pb.fields["anchors"]):
        lost = set(pa.fields["anchors"]) - set(pb.fields["anchors"])
        if lost:
            notes.append(f"lost hyperlink target(s): {sorted(lost)}")
    if len(pa.fields["cites"]) > len(pb.fields["cites"]):
        lost = set(pa.fields["cites"]) - set(pb.fields["cites"])
        if lost:
            notes.append(f"lost citation bookmark(s): {sorted(lost)}")
    if pa.fields["footnotes"] > pb.fields["footnotes"]:
        notes.append(f"lost {pa.fields['footnotes'] - pb.fields['footnotes']} footnote ref(s)")
    return notes


# ----------------------------------------------------------------- integrity
def bookmark_names(xml: str) -> set[str]:
    return set(re.findall(r'<w:bookmarkStart\b[^>]*w:name="([^"]*)"', xml))


def integrity(xml: str, label: str, names: set[str] | None = None):
    """Structural checks on one part.

    `names` is the bookmark names defined ACROSS THE PACKAGE. Bookmarks
    are package-wide but were resolved against the body alone, so a
    footnote's citation link — pointing at a reference-list bookmark in
    document.xml — reads as dangling the moment footnotes are checked.
    Omitting it falls back to this part's own names (the old behaviour).
    """
    issues = []
    if names is None:
        names = bookmark_names(xml)
    # `\b[^>]*` before each w:id: attribute order is not meaningful in
    # XML, and hard-coding it made the INTEGRITY layer find no bookmarks
    # at all on a conforming document — which reads as "balanced".
    bs = re.findall(
        r'<w:bookmarkStart\b[^>]*w:id="(\d+)"[^>]*?(?:\s+w:name="([^"]*)")?',
        xml)
    be = BOOKMARK_END_ID_RE.findall(xml)
    sc, ec = Counter(i for i, _ in bs), Counter(be)
    imbalance = [i for i in set(sc) | set(ec) if sc[i] != ec[i]]
    if imbalance:
        issues.append(f"{label}: bookmark id imbalance {imbalance}")
    names = set(names) | {n for _, n in bs if n}
    anchors = set(re.findall(r'w:anchor="([^"]+)"', xml)) | \
        set(re.findall(r'HYPERLINK[^"]*"([^"]+)"', xml))
    dangling = sorted(a for a in anchors if a not in names)
    if dangling:
        issues.append(f"{label}: dangling anchors (no bookmark) {dangling}")
    # field balance: an unbalanced HYPERLINK field renders as literal field code
    for p in P_RE.findall(xml):
        depth = 0
        for m in re.finditer(r'<w:fldChar w:fldCharType="(begin|end)"/>', p):
            depth += 1 if m.group(1) == "begin" else -1
        if depth != 0:
            issues.append(f"{label}: unbalanced field ({depth:+d}) in "
                          f"{html.unescape(''.join(WT_RE.findall(p)))[:40]!r}")
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


def hyperlink_labels(xml: str) -> Counter:
    """Visible text of every hyperlink (both <w:hyperlink> elements and
    field-based HYPERLINK results). A label that bled (a content-fix dumped
    prose into a link run) shows up as a changed label vs the user's doc."""
    labels = []
    for m in re.finditer(r"<w:hyperlink\b[^>]*>(.*?)</w:hyperlink>", xml, re.DOTALL):
        labels.append(html.unescape("".join(WT_RE.findall(m.group(1)))))
    for m in re.finditer(r'<w:fldChar w:fldCharType="separate"/>\s*</w:r>(.*?)'
                         + _FIELD_END_RE, xml, re.DOTALL):
        labels.append(html.unescape("".join(WT_RE.findall(m.group(1)))))
    return Counter(labels)


# -------------------------------------------------------------------- compare
def compare_paras(A: list[Para], B: list[Para], report, where: str = "body"):
    """Every paragraph layer, for ONE pair of parts.

    Paragraphs are matched WITHIN a part: a running head is not a
    candidate match for a body sentence, and pooling them would invent
    moves between the two.
    """
    def place(entry: dict) -> dict:
        if where != "body":
            entry["part"] = where
        return entry

    def add_formula(pa, pb):
        for kind, glyph_only, ea, eb in formula_diff(pa, pb):
            bucket = "formula_glyph" if glyph_only else "formula"
            report[bucket].append(place({"change": kind, "from": ea,
                                         "to": eb}))

    sm = SequenceMatcher(None, [_norm_glyph(p.text) for p in A],
                         [_norm_glyph(p.text) for p in B], autojunk=False)
    del_pool, ins_pool = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                pa, pb = A[k], B[j1 + (k - i1)]
                for seg, of, nf in fmt_diff(pa, pb):
                    report["format"].append(place({"text": seg,
                                                   "from": sorted(of),
                                                   "to": sorted(nf)}))
                add_formula(pa, pb)
                if pa.text != pb.text:  # equal under glyph-norm only
                    report["glyph"].append(place({"from": pa.text[:120],
                                                  "to": pb.text[:120]}))
        elif tag == "delete":
            del_pool += [A[k] for k in range(i1, i2)]
        elif tag == "insert":
            ins_pool += [B[k] for k in range(j1, j2)]
        elif tag == "replace":
            inner = SequenceMatcher(None, [_norm_glyph(A[k].text) for k in range(i1, i2)],
                                    [_norm_glyph(B[k].text) for k in range(j1, j2)],
                                    autojunk=False)
            for t2, a1, a2, b1, b2 in inner.get_opcodes():
                if t2 == "equal":
                    for off in range(a2 - a1):
                        pa, pb = A[i1 + a1 + off], B[j1 + b1 + off]
                        for seg, of, nf in fmt_diff(pa, pb):
                            report["format"].append(place({"text": seg, "from": sorted(of), "to": sorted(nf)}))
                        add_formula(pa, pb)
                        if pa.text != pb.text:
                            report["glyph"].append(place({"from": pa.text[:120], "to": pb.text[:120]}))
                    continue
                if t2 == "delete":
                    del_pool += [A[i1 + k] for k in range(a1, a2)]
                elif t2 == "insert":
                    ins_pool += [B[j1 + k] for k in range(b1, b2)]
                else:  # replace: pair up, word-diff EVERY paragraph
                    span = max(a2 - a1, b2 - b1)
                    for off in range(span):
                        pa = A[i1 + a1 + off] if a1 + off < a2 else None
                        pb = B[j1 + b1 + off] if b1 + off < b2 else None
                        if pa is None:
                            ins_pool.append(pb)
                            continue
                        if pb is None:
                            del_pool.append(pa)
                            continue
                        if _norm_glyph(pa.text) == _norm_glyph(pb.text):
                            report["glyph"].append(place({"from": pa.text[:120], "to": pb.text[:120]}))
                            continue
                        entry = place({"context": pa.text[:60], "word_diff": word_diff(pa.text, pb.text)})
                        strip = stripped_fields(pa, pb)
                        if strip:
                            entry["WARNING_stripped"] = strip
                            report["stripped_fields"].append(
                                place({"context": pa.text[:60], "lost": strip}))
                        fchg = [k for k, g, _, _ in formula_diff(pa, pb) if not g]
                        if fchg:
                            entry["formula"] = fchg
                        report["text"].append(entry)

    # move detection: a deleted paragraph whose (glyph-normalised) text reappears
    matched = set()
    for da in del_pool:
        if da is None:
            continue
        for ib in ins_pool:
            if ib is None or id(ib) in matched:
                continue
            r = SequenceMatcher(None, _norm_glyph(da.text), _norm_glyph(ib.text)).ratio()
            if r > 0.85:
                report["structure"].append(place({"type": "MOVE", "ratio": round(r, 3),
                                                  "text": da.text[:90]}))
                matched.add(id(ib))
                matched.add(id(da))
                break
    for da in del_pool:
        if da is not None and id(da) not in matched:
            report["structure"].append(place({"type": "DELETE", "text": da.text[:110],
                                              "lost_fields": _fields(da.xml)}))
    for ib in ins_pool:
        if ib is not None and id(ib) not in matched:
            report["structure"].append(place({"type": "INSERT",
                                              "text": ib.text[:110]}))
    return report


def compare_comments(a: Doc, b: Doc, report) -> None:
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


def compare(path_a: str, path_b: str):
    return compare_docs(load(path_a), load(path_b))


def compare_docs(a: Doc, b: Doc):
    report = {"structure": [], "text": [], "glyph": [], "formula": [],
              "formula_glyph": [], "format": [], "hyperlinks": [],
              "integrity": [], "stripped_fields": [], "comments": []}

    for pa, pb in pair_parts(a.parts, b.parts):
        # A part that exists on one side only and carries no visible text
        # is not a difference: Word writes endnotes.xml into nearly every
        # document (306 of the 507 here) holding nothing but the
        # separator entries, so a build that does not emit the part has
        # lost nothing. Gating on it would fail --expect-clean over a
        # part with no reader-visible content.
        if pa is not None and pb is not None:
            compare_paras(pa.paras, pb.paras, report, pa.label)
        elif pa is not None and pa.paras:
            report["structure"].append({"type": "PART REMOVED",
                                        "part": pa.label,
                                        "text": pa.blob[:110]})
        elif pb is not None and pb.paras:
            report["structure"].append({"type": "PART ADDED",
                                        "part": pb.label,
                                        "text": pb.blob[:110]})

    compare_comments(a, b, report)

    # Hyperlink-label diff: a link whose visible text differs between built and
    # user docs (a content-fix that bled prose into a link grows its label, but
    # the prose text still matches so TEXT/FORMAT miss it). Set difference, so
    # legitimately long but identical labels (references) never show.
    la = sum((hyperlink_labels(p.xml) for p in a.parts), Counter())
    lb = sum((hyperlink_labels(p.xml) for p in b.parts), Counter())
    for lab, n in (la - lb).items():
        report["hyperlinks"].append({"side": "built-only", "label": lab[:90], "n": n})
    for lab, n in (lb - la).items():
        report["hyperlinks"].append({"side": "user-only", "label": lab[:90], "n": n})

    # Validate the BUILT doc (A): it is the authoritative output. The user's
    # doc (B) often has Word-stripped citation bookmarks / renumbered ids — that
    # damage is what the build RESTORES, so checking B would false-alarm. A
    # dangling anchor in A means a citation the build itself failed to keep.
    names = set().union(*(bookmark_names(p.xml) for p in a.parts)) \
        if a.parts else set()
    for part in a.parts:
        label = "BUILT" if part.label == "body" else f"BUILT/{part.label}"
        report["integrity"] += integrity(part.xml, label, names)
    return report


# --------------------------------------------------------------------- output
def _in(entry) -> str:
    """' (header1)' for anything outside the body; '' for the body, so a
    body-only document reads exactly as it did before parts existed."""
    part = entry.get("part")
    return f" ({part})" if part else ""


def render(report, expect_clean):
    real = 0

    def head(s):
        print("\n" + "=" * 72 + f"\n{s}\n" + "=" * 72)

    head("STRUCTURE  (paragraph insert / delete / move, part added / removed)")
    for s in report["structure"]:
        real += 1
        print(f"  [{s['type']}]{_in(s)} {s.get('text','')}"
              + (f"  (move ratio {s['ratio']})" if s["type"] == "MOVE" else "")
              + (f"  LOST FIELDS: {s['lost_fields']}"
                 if s.get("lost_fields", {}).get("cites") or s.get("lost_fields", {}).get("anchors")
                 else ""))
    if not report["structure"]:
        print("  (none)")

    head("TEXT  (word-level, every paragraph)")
    for t in report["text"]:
        real += 1
        print(f"\n  in{_in(t)}: \"{t['context']}…\"")
        for d in t["word_diff"]:
            print(f"      {d}")
        if t.get("WARNING_stripped"):
            print(f"      ** RESTORE ON INTEGRATE: {t['WARNING_stripped']} **")
        if t.get("formula"):
            print(f"      ** formula also changed in this paragraph: {t['formula']} **")
    if not report["text"]:
        print("  (none)")

    head("FORMULA  (OMML tokens + structure)")
    for f in report["formula"]:
        real += 1
        print(f"  [{f['change']}]{_in(f)} from={f['from']}  ->  to={f['to']}")
    if not report["formula"]:
        print("  (none)")

    head("FORMAT  (italic/bold/super/sub/strike, text-matched paras)")
    for f in report["format"]:
        real += 1
        print(f"  '{f['text']}'{_in(f)}: {f['from'] or '∅'} -> {f['to'] or '∅'}")
    if not report["format"]:
        print("  (none)")

    head("HYPERLINK  (link-label differences — REVIEW; not gated)")
    print("  built-only = a link the build has but the user copy lost (restored "
          "citation) or fixed; user-only = a link only in the user copy (a build "
          "regression, OR the user's own bled link). Eyeball these.")
    for h in report["hyperlinks"]:
        print(f"  [{h['side']}] {h['label']!r}" + (f" x{h['n']}" if h["n"] > 1 else ""))
    if not report["hyperlinks"]:
        print("  (none)")

    head("COMMENTS  (present on one side only — REVIEW; not gated)")
    print("  user-only = the author left a comment on this round; built-only "
          "= a comment the build carries and the author's copy does not.")
    for c in report["comments"]:
        print(f"  [{c['side']}] {c['text']!r}" + (f" x{c['n']}" if c["n"] > 1 else ""))
    if not report["comments"]:
        print("  (none)")

    head("GLYPH  (normalization-only — likely Word artifact, usually NOT a user edit)")
    for g in report["glyph"]:
        print(f"  ~{_in(g)} {g['from']}\n    {g['to']}")
    for g in report["formula_glyph"]:
        print(f"  ~ formula: {g['from'][1]!r} -> {g['to'][1]!r}  (keep generator glyph)")
    if not report["glyph"] and not report["formula_glyph"]:
        print("  (none)")

    head("BUILT-DOC INTEGRITY  (gate: must be clean)")
    for i in report["integrity"]:
        print(f"  ** {i}")
    if not report["integrity"]:
        print("  (clean: bookmarks balanced, no dangling anchors)")

    head("FIELD DIFFERENCES  (informational — Word stripped these in your copy; "
         "the build restores them)")
    for s in report["stripped_fields"]:
        print(f"  ·{_in(s)} {s['context']}…  {s['lost']}")
    if not report["stripped_fields"]:
        print("  (none)")

    print("\n" + "-" * 72)
    glyphs = len(report["glyph"]) + len(report["formula_glyph"])
    print(f"REAL change locations (excl. glyph): {real}   |   "
          f"glyph-only: {glyphs}   |   "
          f"built-doc integrity flags: {len(report['integrity'])}   |   "
          f"field-restores (info): {len(report['stripped_fields'])}   |   "
          f"hyperlink diffs (review): {len(report['hyperlinks'])}   |   "
          f"comment diffs (review): {len(report['comments'])}")
    if expect_clean and (real or report["integrity"]):
        print("EXPECT-CLEAN FAILED: unresolved real differences or integrity "
              "issues in the built doc.")
        return 1
    if expect_clean:
        print("EXPECT-CLEAN OK: build matches the user's content; only glyph "
              "residuals (and Word-stripped fields the build restores) remain.")
    return 0


def main():
    # UTF-8 first: --help prints the (∗/−/arrow-bearing) docstring during
    # parse_args, before any later reconfigure would take effect.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("built", help="A: freshly built / baseline .docx")
    ap.add_argument("edited", help="B: user-edited .docx")
    ap.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    ap.add_argument("--expect-clean", action="store_true",
                    help="exit 1 if any non-glyph difference remains")
    args = ap.parse_args()
    rep = compare(args.built, args.edited)
    if args.json:
        # Through cli._write_json, which carries the last-resort encoder:
        # a value json cannot serialise would otherwise lose a finished
        # comparison at the final step. That guard was added to the
        # `docxkit compare` path and NOT to this one, which is the
        # module's own entry point — the same bug, in the file the fix
        # was written for.
        from .cli import _write_json
        _write_json(args.json, rep)
    sys.exit(render(rep, args.expect_clean))


if __name__ == "__main__":
    main()
