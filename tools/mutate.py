#!/usr/bin/env python
"""Mutation testing with a survivor budget.

A green suite proves nothing until it fails on wrong code. Each mutation
below re-introduces a defect this codebase has really shipped, or
removes a guard that exists because one did. Every one of them must turn
the suite red; a survivor is either a missing test or — twice so far — a
second line of defence worth knowing about.

    python tools/mutate.py            # all mutations
    python tools/mutate.py --list     # just show them
    python tools/mutate.py -k ghost   # only matching ones

Exits non-zero if any mutation survives, so CI can gate on it.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "docxkit"


class Mutation(NamedTuple):
    module: str
    label: str
    old: str
    new: str
    tests: str = ""          # narrow the run when the whole suite is slow


MUTATIONS = [
    # --- the deliverable path ------------------------------------------
    Mutation("tracked.py",
             "the redline is published before it is validated",
             "        building.replace(out)          "
             "# every gate passed: publish",
             "        pass  # mutation"),
    Mutation("tracked.py", "the staging directory leaks again",
             "        shutil.rmtree(staging, ignore_errors=True)",
             "        pass  # mutation"),
    Mutation("tracked.py",
             "the AFI bug: the cheap math walk replaces the revision scan",
             "    if classify is None:\n"
             "        return _accept_math_via_equations(doc, notes)\n"
             "    return _comment_and_accept_math_revisions("
             "doc, classify, generic, notes)",
             "    return _accept_math_via_equations(doc, notes)"),
    Mutation("tracked.py", "a failed Word call is swallowed silently again",
             "        notes.append(f'comment not added to "
             '"{text[:30]}": {exc}\')',
             "        pass  # mutation"),
    Mutation("tracked.py", "package_counts stops counting comments",
             '        "comments": com_xml.count("<w:comment w:id="),',
             '        "comments": 0,'),
    # --- the write gate -------------------------------------------------
    Mutation("package.py", "malformed XML may be written again",
             "    if problems := malformed_parts(parts):",
             "    if False:"),
    # --- the XML walks --------------------------------------------------
    Mutation("_cite_audit.py",
             "a self-closing hyperlink opens a doubled-link frame",
             r"""    r'|<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>'""",
             r"""    r'|<w:hyperlink\b[^>]*w:anchor="([^"]+)"'"""),
    Mutation("_xml.py",
             "a self-closing hyperlink reads as an open element link",
             r'''    r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*(?<!/)>(.*?)</w:hyperlink>',''',
             r'''    r'<w:hyperlink\b[^>]*w:anchor="([^"]+)"[^>]*>(.*?)</w:hyperlink>','''),
    Mutation("_xml.py", "the run-open scan matches w:rPr again",
             'RUN_OPEN_RE = re.compile(r"<w:r\\b[^>]*>")',
             'RUN_OPEN_RE = re.compile(r"<w:r[^>]*>")'),
    Mutation("_xml.py", "escaping stops being applied to run text",
             '    return text.replace("&", "&amp;").replace("<", "&lt;")'
             '.replace(">", "&gt;")',
             "    return text"),
    # --- tables ---------------------------------------------------------
    Mutation("_table_core.py", "nested tables close on the first end tag",
             '        end = matching_close(xml, at + len("<w:tbl>"), "tbl")',
             '        end = xml.index("</w:tbl>", at) + len("</w:tbl>")'),
    Mutation("_table_core.py", "stale table offsets are used instead of refused",
             "    if table.source is not None and table.source != hash(xml):",
             "    if False:"),
    Mutation("_table_layout.py", "spans constrain by full width (the ~250 dxa bug)",
             "            spans.append((c, k, h))",
             "            spans.append((c, k, f))"),
    Mutation("_table_layout.py", "declared cell margins are ignored",
             "    side = 2 * margin if margin is not None "
             "else _side_margins(body)",
             "    side = 2 * margin if margin is not None else 216"),
    Mutation("_table_layout.py", "the closing rule lands on the first row",
             "    last = trs[-1]", "    last = trs[0]"),
    Mutation("_table_layout.py", "already-raised stars are wrapped again",
             '        if m is None or "<w:vertAlign" in last.group(0):',
             "        if m is None:"),
    # --- citations ------------------------------------------------------
    Mutation("_cite_build.py",
             "an entry bookmark matches on the year alone again",
             "        if alpha.startswith(got) or got.startswith(alpha):\n"
             "            return n",
             "        return n"),
    Mutation("_cite_grammar.py",
             "an inverted visible-text span is honoured, duplicating text",
             "    if not 0 <= at <= end <= text_len:",
             "    if False:"),
    # --- prose math -----------------------------------------------------
    Mutation("equations.py",
             "the sentinel stops surviving visible_text, so the pieces "
             "no longer line up with the equations",
             'OMATH_RE.sub("<w:t>' + chr(92) + 'u0000</w:t>", para)',
             'OMATH_RE.sub("", para)'),
    Mutation("equations.py",
             "prose math is judged against a fixed vocabulary again",
             "    known = document_symbols(xml) if symbols is None "
             "else symbols",
             "    known = _PROSE_GREEK"),
    # --- cross-references ----------------------------------------------
    Mutation("crossrefs.py", "bookmark ids stop clearing the other parts",
             "    return next_bookmark_id(xml, *others)",
             "    return next_bookmark_id(xml)"),
]


def run(tests: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", *(tests.split() or [])],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    return proc.returncode != 0, line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("-k", default="", help="substring filter on the label")
    args = ap.parse_args()

    chosen = [m for m in MUTATIONS if args.k.lower() in m.label.lower()]
    if args.list:
        for m in chosen:
            print(f"  {m.module:<14} {m.label}")
        return 0

    caught, survived, skipped = 0, [], []
    for m in chosen:
        path = SRC / m.module
        original = path.read_text(encoding="utf-8")
        if original.count(m.old) != 1:
            skipped.append(f"{m.label} (anchor {original.count(m.old)}x)")
            continue
        path.write_text(original.replace(m.old, m.new), encoding="utf-8",
                        newline="")
        try:
            died, line = run(m.tests)
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        print(f"  {'CAUGHT  ' if died else 'SURVIVED'} {m.label}")
        if died:
            caught += 1
        else:
            survived.append(m.label)

    print(f"\n{caught}/{len(chosen) - len(skipped)} mutations caught")
    for s in skipped:
        print(f"  SKIPPED (anchor drifted): {s}")
    for s in survived:
        print(f"  SURVIVOR: {s}")
    if skipped:
        print("\nA drifted anchor means the code moved; update the mutation "
              "so it keeps testing what it was written to test.")
    return 1 if survived or skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
