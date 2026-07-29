#!/usr/bin/env python
r"""compare_docx.py — authoritative multi-layer diff between two .docx files.

Built for the `integrate-edits` workflow: compare a freshly *built* document
(from the generation script / source) against the *user-edited* document and
surface EVERY change across every layer, so none is lost.

It compares two .docx files directly (not a docx-vs-script), so it is
architecture-agnostic: it works whether the doc is produced by a python-docx
script (mkp/omath helpers) or a raw-`document.xml` transform (e.g. AFI's
build_v10 + v9_prose_edits.json + an OMML generator).

Layers reported
  STRUCTURE  paragraph insert / delete / MOVE (a delete whose text reappears
             as an insert elsewhere)
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
import json
import re
import sys
import zipfile
from collections import Counter
from difflib import SequenceMatcher

# One glyph table for the whole toolkit. While compare and ingest
# each kept their own copy they drifted apart on U+00A0, so this
# gate called a non-breaking-space change a Word artifact while
# ingest treated the same change as an author edit.
from ._xml import GLYPH_MAP, normalize_glyphs

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


def load(path: str):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        try:
            foot = z.read("word/footnotes.xml").decode("utf-8")
        except KeyError:
            foot = ""
    paras = [Para(p) for p in P_RE.findall(xml)]
    paras = [p for p in paras if p.text]
    return xml, foot, paras


# -------------------------------------------------------------------- diffing
def word_diff(a: str, b: str):
    aw, bw = a.split(), b.split()
    sm = SequenceMatcher(None, aw, bw)
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
def integrity(xml: str, label: str):
    issues = []
    bs = re.findall(r'<w:bookmarkStart w:id="(\d+)"(?:\s+w:name="([^"]*)")?', xml)
    be = re.findall(r'<w:bookmarkEnd w:id="(\d+)"', xml)
    sc, ec = Counter(i for i, _ in bs), Counter(be)
    imbalance = [i for i in set(sc) | set(ec) if sc[i] != ec[i]]
    if imbalance:
        issues.append(f"{label}: bookmark id imbalance {imbalance}")
    names = {n for _, n in bs if n}
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


def hyperlink_labels(xml: str) -> Counter:
    """Visible text of every hyperlink (both <w:hyperlink> elements and
    field-based HYPERLINK results). A label that bled (a content-fix dumped
    prose into a link run) shows up as a changed label vs the user's doc."""
    labels = []
    for m in re.finditer(r"<w:hyperlink\b[^>]*>(.*?)</w:hyperlink>", xml, re.DOTALL):
        labels.append(html.unescape("".join(WT_RE.findall(m.group(1)))))
    for m in re.finditer(r'<w:fldChar w:fldCharType="separate"/></w:r>(.*?)'
                         r'<w:r[^>]*><w:fldChar w:fldCharType="end"/>', xml, re.DOTALL):
        labels.append(html.unescape("".join(WT_RE.findall(m.group(1)))))
    return Counter(labels)


# -------------------------------------------------------------------- compare
def compare(path_a: str, path_b: str):
    xa, fa, A = load(path_a)
    xb, fb, B = load(path_b)
    report = {"structure": [], "text": [], "glyph": [], "formula": [],
              "formula_glyph": [], "format": [], "hyperlinks": [],
              "integrity": [], "stripped_fields": []}

    def add_formula(pa, pb):
        for kind, glyph_only, ea, eb in formula_diff(pa, pb):
            bucket = "formula_glyph" if glyph_only else "formula"
            report[bucket].append({"change": kind, "from": ea, "to": eb})

    sm = SequenceMatcher(None, [_norm_glyph(p.text) for p in A],
                         [_norm_glyph(p.text) for p in B], autojunk=False)
    del_pool, ins_pool = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                pa, pb = A[k], B[j1 + (k - i1)]
                for seg, of, nf in fmt_diff(pa, pb):
                    report["format"].append({"text": seg, "from": sorted(of),
                                             "to": sorted(nf)})
                add_formula(pa, pb)
                if pa.text != pb.text:  # equal under glyph-norm only
                    report["glyph"].append({"from": pa.text[:120], "to": pb.text[:120]})
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
                            report["format"].append({"text": seg, "from": sorted(of), "to": sorted(nf)})
                        add_formula(pa, pb)
                        if pa.text != pb.text:
                            report["glyph"].append({"from": pa.text[:120], "to": pb.text[:120]})
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
                            report["glyph"].append({"from": pa.text[:120], "to": pb.text[:120]})
                            continue
                        entry = {"context": pa.text[:60], "word_diff": word_diff(pa.text, pb.text)}
                        strip = stripped_fields(pa, pb)
                        if strip:
                            entry["WARNING_stripped"] = strip
                            report["stripped_fields"].append(
                                {"context": pa.text[:60], "lost": strip})
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
                report["structure"].append({"type": "MOVE", "ratio": round(r, 3),
                                             "text": da.text[:90]})
                matched.add(id(ib))
                matched.add(id(da))
                break
    for da in del_pool:
        if da is not None and id(da) not in matched:
            report["structure"].append({"type": "DELETE", "text": da.text[:110],
                                        "lost_fields": _fields(da.xml)})
    for ib in ins_pool:
        if ib is not None and id(ib) not in matched:
            report["structure"].append({"type": "INSERT", "text": ib.text[:110]})

    # Hyperlink-label diff: a link whose visible text differs between built and
    # user docs (a content-fix that bled prose into a link grows its label, but
    # the prose text still matches so TEXT/FORMAT miss it). Set difference, so
    # legitimately long but identical labels (references) never show.
    la, lb = hyperlink_labels(xa), hyperlink_labels(xb)
    for lab, n in (la - lb).items():
        report["hyperlinks"].append({"side": "built-only", "label": lab[:90], "n": n})
    for lab, n in (lb - la).items():
        report["hyperlinks"].append({"side": "user-only", "label": lab[:90], "n": n})

    # Validate the BUILT doc (A): it is the authoritative output. The user's
    # doc (B) often has Word-stripped citation bookmarks / renumbered ids — that
    # damage is what the build RESTORES, so checking B would false-alarm. A
    # dangling anchor in A means a citation the build itself failed to keep.
    report["integrity"] = integrity(xa, "BUILT")
    return report


# --------------------------------------------------------------------- output
def render(report, expect_clean):
    real = 0

    def head(s):
        print("\n" + "=" * 72 + f"\n{s}\n" + "=" * 72)

    head("STRUCTURE  (paragraph insert / delete / move)")
    for s in report["structure"]:
        real += 1
        print(f"  [{s['type']}] {s.get('text','')}"
              + (f"  (move ratio {s['ratio']})" if s["type"] == "MOVE" else "")
              + (f"  LOST FIELDS: {s['lost_fields']}"
                 if s.get("lost_fields", {}).get("cites") or s.get("lost_fields", {}).get("anchors")
                 else ""))
    if not report["structure"]:
        print("  (none)")

    head("TEXT  (word-level, every paragraph)")
    for t in report["text"]:
        real += 1
        print(f"\n  in: \"{t['context']}…\"")
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
        print(f"  [{f['change']}] from={f['from']}  ->  to={f['to']}")
    if not report["formula"]:
        print("  (none)")

    head("FORMAT  (italic/bold/super/sub/strike, text-matched paras)")
    for f in report["format"]:
        real += 1
        print(f"  '{f['text']}': {f['from'] or '∅'} -> {f['to'] or '∅'}")
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

    head("GLYPH  (normalization-only — likely Word artifact, usually NOT a user edit)")
    for g in report["glyph"]:
        print(f"  ~ {g['from']}\n    {g['to']}")
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
        print(f"  · {s['context']}…  {s['lost']}")
    if not report["stripped_fields"]:
        print("  (none)")

    print("\n" + "-" * 72)
    glyphs = len(report["glyph"]) + len(report["formula_glyph"])
    print(f"REAL change locations (excl. glyph): {real}   |   "
          f"glyph-only: {glyphs}   |   "
          f"built-doc integrity flags: {len(report['integrity'])}   |   "
          f"field-restores (info): {len(report['stripped_fields'])}   |   "
          f"hyperlink diffs (review): {len(report['hyperlinks'])}")
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
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
    sys.exit(render(rep, args.expect_clean))


if __name__ == "__main__":
    main()
