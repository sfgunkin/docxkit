#!/usr/bin/env python
r"""Authoritative multi-layer diff between two .docx files.

Built for the `integrate-edits` workflow: compare a freshly *built*
document (from the generation script / source) against the *user-edited*
document and surface EVERY change across every layer, so none is lost.

It compares two .docx files directly (not a docx-vs-script), so it is
architecture-agnostic: it works whether the doc is produced by a
python-docx script (mkp/omath helpers) or a raw-`document.xml` transform
(e.g. AFI's build_v10 + v9_prose_edits.json + an OMML generator).

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
  FORMULA TYPOGRAPHY
             an equation that says the same thing and is SET differently:
             upright against math-italic, bold, script, size. Nothing else
             sees this — FORMULA compares tokens and structure, FORMAT
             walks <w:t> runs and an equation has none
  FORMAT     character-level run formatting (italic/bold/super/sub/strike/
             smallCaps) on text-matched paragraphs, ignoring Hyperlink styling
  INTEGRITY  bookmark start/end balance, dangling hyperlink anchors, cite_/ref_
             pairing, and citation/footnote fields STRIPPED by Word's edit
             (a paragraph that had a field in A but is plain text in B)

Usage
  docxkit compare BUILT.docx USER_EDITED.docx
  docxkit compare BUILT.docx USER_EDITED.docx --json report.json
  docxkit compare BUILT.docx USER_EDITED.docx --expect-clean
        # exit 1 if any non-glyph difference remains (use to gate the
        # rebuild->verify loop: after integration this MUST pass)

Every entry says where it happened: which part, and which cell of which
table ("table 3 r2c1"), because a results table has hundreds of cells
that all read like `0.312`.

Conventions: A = first file = the BUILT/baseline doc; B = second = USER-edited.

This module is the FACADE. The work is in three layers behind it, and
they may only be imported downwards: `_compare_read` (a package to
paragraphs) knows nothing of differences, `_compare_diff` (paragraphs to
a report) knows nothing of files or printing, `_compare_render` (a report
to a page and an exit code) knows nothing of XML. `tests/test_compare.py`
asserts that layering stays acyclic, because a layering nobody checks is
a layering that will not hold.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from ._compare_diff import GATED as GATED
from ._compare_diff import Report as Report
from ._compare_diff import bookmark_names as bookmark_names
from ._compare_diff import compare_comments as compare_comments
from ._compare_diff import compare_paras as compare_paras
from ._compare_diff import fmt_diff as fmt_diff
from ._compare_diff import formula_diff as formula_diff
from ._compare_diff import hyperlink_labels as hyperlink_labels
from ._compare_diff import integrity as integrity
from ._compare_diff import label_moves as label_moves
from ._compare_diff import stripped_fields as stripped_fields
from ._compare_diff import word_diff as word_diff
from ._compare_read import COMMENTS_PART as COMMENTS_PART
from ._compare_read import TEXT_PART_RE as TEXT_PART_RE
from ._compare_read import VOLATILE_FIELDS as VOLATILE_FIELDS
from ._compare_read import Doc as Doc
from ._compare_read import Para as Para
from ._compare_read import Part as Part
from ._compare_read import load as load
from ._compare_read import load_parts as load_parts
from ._compare_read import mask_volatile_fields as mask_volatile_fields
from ._compare_read import pair_parts as pair_parts
from ._compare_render import render as render


def compare(path_a: str, path_b: str) -> Report:
    return compare_docs(load(path_a), load(path_b))


def compare_docs(a: Doc, b: Doc) -> Report:
    report: Report = {"structure": [], "text": [], "glyph": [], "formula": [],
                      "formula_glyph": [], "formula_format": [], "format": [],
                      "hyperlinks": [], "integrity": [],
                      "stripped_fields": [], "comments": []}

    # Every field name side B still carries, PACKAGE-wide. A target the
    # author moved is not a target the author lost, and it can move
    # between parts as easily as within one — a citation that went from
    # the prose into a footnote accounted for the last 27 of the false
    # "lost" claims over 748 real comparisons. Bookmarks are package-wide
    # in Word too, so the narrower reading was never the right one.
    surviving = {n for part in b.parts for p in part.paras
                 for key in ("anchors", "cites") for n in p.fields[key]}

    for pa, pb in pair_parts(a.parts, b.parts):
        # A part that exists on one side only and carries no visible text
        # is not a difference: Word writes endnotes.xml into nearly every
        # document (306 of the 507 here) holding nothing but the
        # separator entries, so a build that does not emit the part has
        # lost nothing. Gating on it would fail --expect-clean over a
        # part with no reader-visible content.
        if pa is not None and pb is not None:
            compare_paras(pa.paras, pb.paras, report, pa.label,
                          surviving=surviving)
        elif pa is not None and pa.paras:
            report["structure"].append({"type": "PART REMOVED",
                                        "part": pa.label,
                                        "text": pa.blob[:110]})
        elif pb is not None and pb.paras:
            report["structure"].append({"type": "PART ADDED",
                                        "part": pb.label,
                                        "text": pb.blob[:110]})

    compare_comments(a, b, report)

    # Hyperlink-label diff: a link whose visible text differs between the
    # built and user docs (a content-fix that bled prose into a link grows
    # its label, but the prose text still matches, so TEXT and FORMAT both
    # miss it). Set difference, so legitimately long but identical labels
    # (reference entries) never show.
    la: Counter[str] = sum((hyperlink_labels(p.xml) for p in a.parts),
                           Counter())
    lb: Counter[str] = sum((hyperlink_labels(p.xml) for p in b.parts),
                           Counter())
    gone, gained = la - lb, lb - la
    for pair in label_moves(gone, gained):
        report["hyperlinks"].append(pair)
    for lab, n in gone.items():
        report["hyperlinks"].append({"side": "built-only",
                                     "label": lab[:90], "n": n})
    for lab, n in gained.items():
        report["hyperlinks"].append({"side": "user-only",
                                     "label": lab[:90], "n": n})

    # Validate the BUILT doc (A): it is the authoritative output. The
    # user's doc (B) often has Word-stripped citation bookmarks and
    # renumbered ids — that damage is what the build RESTORES, so
    # checking B would false-alarm. A dangling anchor in A means a
    # citation the build itself failed to keep. Names are collected
    # across every part first: bookmarks are package-wide, and resolving
    # a footnote's citation link against the footnote part alone calls
    # every one of them dangling.
    names: set[str] = (set().union(*(bookmark_names(p.xml) for p in a.parts))
                       if a.parts else set())
    for part in a.parts:
        label = "BUILT" if part.label == "body" else f"BUILT/{part.label}"
        report["integrity"] += integrity(part.xml, label, names)
    return report


def main() -> None:
    # UTF-8 first: --help prints the (∗/−/arrow-bearing) docstring during
    # parse_args, before any later reconfigure would take effect.
    from .console import utf8_stdout
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("built", help="A: freshly built / baseline .docx")
    ap.add_argument("edited", help="B: user-edited .docx")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the report as JSON")
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
