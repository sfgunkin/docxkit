r"""Saying what the comparison found.

Layer 3 of :mod:`docxkit.compare`: the human-facing report, and the
exit code `--expect-clean` gates on. Every layer prints in full — a
report a reader has to guess at is the failure this tool exists to
prevent, so nothing here truncates a list or summarises a count in
place of the entries.
"""
from __future__ import annotations

from typing import Any

from ._compare_diff import Report


def _in(entry: dict[str, Any]) -> str:
    """Where it happened: ' (footnotes, table 3 r2c1)'.

    Empty for a body paragraph outside a table, so an ordinary prose
    document reads exactly as it did before either was recorded. The
    cell address is the difference between "a number changed somewhere
    in Table 3" and a reader landing on the cell.
    """
    inside = ", ".join(x for x in (entry.get("part"), entry.get("at")) if x)
    return f" ({inside})" if inside else ""


def _head(title: str) -> None:
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)


def _structure(report: Report) -> int:
    _head("STRUCTURE  (paragraph insert / delete / move, part added / "
          "removed)")
    for s in report["structure"]:
        lost = s.get("lost_fields", {})
        moved = f"  (move ratio {s['ratio']})" if s["type"] == "MOVE" else ""
        fields = (f"  LOST FIELDS: {lost}"
                  if lost.get("cites") or lost.get("anchors") else "")
        print(f"  [{s['type']}]{_in(s)} {s.get('text', '')}{moved}{fields}")
    if not report["structure"]:
        print("  (none)")
    return len(report["structure"])


def _text(report: Report) -> int:
    _head("TEXT  (word-level, every paragraph)")
    for t in report["text"]:
        print(f"\n  in{_in(t)}: \"{t['context']}…\"")
        for d in t["word_diff"]:
            print(f"      {d}")
        if t.get("WARNING_stripped"):
            print("      ** RESTORE ON INTEGRATE: "
                  f"{t['WARNING_stripped']} **")
        if t.get("formula"):
            print("      ** formula also changed in this paragraph: "
                  f"{t['formula']} **")
    if not report["text"]:
        print("  (none)")
    return len(report["text"])


def _formula(report: Report) -> int:
    _head("FORMULA  (OMML tokens + structure)")
    for f in report["formula"]:
        print(f"  [{f['change']}]{_in(f)} from={f['from']}  ->  to={f['to']}")
    if not report["formula"]:
        print("  (none)")
    return len(report["formula"])


def _formula_format(report: Report) -> int:
    _head("FORMULA TYPOGRAPHY  (upright/italic/bold/script inside an "
          "equation — gated)")
    print("  The equation says the same thing and is SET differently. "
          "Nothing else sees this: FORMULA compares tokens and structure, "
          "FORMAT walks <w:t> runs and an equation has none.")
    for f in report["formula_format"]:
        print(f"  [{f['change']}]{_in(f)} {f['from']!r}\n"
              f"                 -> {f['to']!r}")
    if not report["formula_format"]:
        print("  (none)")
    return len(report["formula_format"])


def _format(report: Report) -> int:
    _head("FORMAT  (italic/bold/super/sub/strike, size, colour — "
          "text-matched paras)")
    for f in report["format"]:
        print(f"  '{f['text']}'{_in(f)}: {f['from'] or '∅'} -> "
              f"{f['to'] or '∅'}")
    if not report["format"]:
        print("  (none)")
    return len(report["format"])


def _review(report: Report) -> None:
    """The layers that inform without gating."""
    _head("HYPERLINK  (link-label differences — REVIEW; not gated)")
    print("  built-only = a link the build has but the user copy lost "
          "(restored citation) or fixed; user-only = a link only in the "
          "user copy (a build regression, OR the user's own bled link). "
          "Eyeball these.")
    print("  grew/shrank = ONE label, both sides of it: the link now "
          "draws more (or less) of the sentence than it did. A label "
          "that grew is prose swallowed into the link — blue and "
          "underlined on the page, invisible to every other layer.")
    for h in report["hyperlinks"]:
        times = f" x{h['n']}" if h["n"] > 1 else ""
        if "to" in h:
            print(f"  [{h['side']}] {h['label']!r} -> {h['to']!r}{times}")
            continue
        print(f"  [{h['side']}] {h['label']!r}{times}")
    if not report["hyperlinks"]:
        print("  (none)")

    _head("COMMENTS  (present on one side only — REVIEW; not gated)")
    print("  user-only = the author left a comment on this round; "
          "built-only = a comment the build carries and the author's copy "
          "does not.")
    for c in report["comments"]:
        times = f" x{c['n']}" if c["n"] > 1 else ""
        print(f"  [{c['side']}] {c['text']!r}{times}")
    if not report["comments"]:
        print("  (none)")

    _head("GLYPH  (normalization-only — likely Word artifact, usually NOT "
          "a user edit)")
    for g in report["glyph"]:
        print(f"  ~{_in(g)} {g['from']}\n    {g['to']}")
    for g in report["formula_glyph"]:
        print(f"  ~ formula: {g['from'][1]!r} -> {g['to'][1]!r}  "
              "(keep generator glyph)")
    if not report["glyph"] and not report["formula_glyph"]:
        print("  (none)")

    _head("BUILT-DOC INTEGRITY  (gate: must be clean)")
    for i in report["integrity"]:
        print(f"  ** {i}")
    if not report["integrity"]:
        print("  (clean: bookmarks balanced, no dangling anchors)")

    # Not "Word stripped these in your copy": that named a cause, and a
    # direction — built against author-edited — which is only one of the
    # ways this command is used. Comparing two builds, the sentence sent
    # a reader looking for a Word save that never happened.
    _head("FIELD DIFFERENCES  (informational — machinery in A that B no "
          "longer has anywhere; usually a Word save dropping a link)")
    for s in report["stripped_fields"]:
        where = f" {s['context']}…" if s["context"] else ""
        print(f"  ·{_in(s)}{where}  {s['lost']}")
    if not report["stripped_fields"]:
        print("  (none)")


def render(report: Report, expect_clean: bool) -> int:
    """Print every layer; return the exit code."""
    real = _structure(report) + _text(report)
    real += _formula(report) + _formula_format(report) + _format(report)
    _review(report)

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
              "residuals (and Word-stripped fields the build restores) "
              "remain.")
    return 0
