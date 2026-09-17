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
    python tools/mutate.py --restore  # after a killed run

Exits non-zero if any mutation survives OR if any anchor has drifted, and
CI gates on it — which for a long time nothing did. Three anchors had
drifted silently by 2026-08-27: the tool said so and exited 1 on every
run, and nobody was reading it, because `39/39 mutations caught` at the
top of the output is the number an eye lands on. A drifted anchor is a
curated defect whose regression cover has gone.

**In CI, not in `tools/gates.py`, and that is measured rather than
preferred.** 42 mutations at `-n <physical cores>` is **18m23s** —
`-x` means a CAUGHT mutation stops at its first red test, and 42 of
those still cost eighteen minutes. The local chain is about four, and a
pre-commit gate five times longer than the thing it guards is one people
route around. `tests/test_mutate.py` holds the half that IS fast: every
anchor still matches its module exactly once, which is the failure that
actually happened here.

**A killed run leaves its mutation in the tree**, because the restore is
a `finally` and a kill is not an exception. The pre-mutation bytes are
stashed in `.mutate-in-flight/` first, so the next run REFUSES and says
which file to put back; `--restore` does it.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "docxkit"

#: Where the pre-mutation bytes live while a mutation is applied.
#:
#: The restore is a `finally`, which covers an exception and does NOT
#: cover the process being killed — and an unattended run is stopped by
#: being killed. On 2026-08-27 a killed run left `_set_borders` in
#: `_table_layout.py` carrying the nested-borders defect it is named for,
#: through an hour of unrelated work and into a batch about to be
#: committed. It read as "my change broke five tests"; what caught it was
#: the diffstat having three more lines than the patch that made it.
#:
#: `mutation_session.py` treats exactly this as hazard two of six and
#: guards it by verifying the unmutated baseline before every chunk. This
#: tool runs the same risk in the checkout the author is EDITING, which
#: is worse, because a sabotage mutation is by construction one the suite
#: can catch — so the leftover looks like a real failure.
STASH = ROOT / ".mutate-in-flight"


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
    # Re-anchored 2026-08-27: the call moved into `_clear_staging`, so its
    # indentation went from eight spaces to four and the anchor stopped
    # matching. What it tests is unchanged.
    Mutation("tracked.py", "the staging directory leaks again",
             "    shutil.rmtree(staging, ignore_errors=True)",
             "    pass  # mutation"),
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
    # Re-anchored 2026-09-11: the XML gates moved to `_tracked_gates.py`.
    Mutation("_tracked_gates.py", "package_counts stops counting comments",
             '        "comments": len(COMMENT_ID_RE.findall(com_xml)),',
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
    # Re-anchored 2026-08-27: the pattern gained `(?<!/)` so a self-closing
    # `<w:r/>` no longer reads as an opening tag. Dropping `\b` is still
    # what makes it match `<w:rPr>`, which is what this tests.
    Mutation("_xml.py", "the run-open scan matches w:rPr again",
             'RUN_OPEN_RE = re.compile(r"<w:r\\b[^>]*(?<!/)>")',
             'RUN_OPEN_RE = re.compile(r"<w:r[^>]*(?<!/)>")'),
    Mutation("_xml.py", "escaping stops being applied to run text",
             '    return text.replace("&", "&amp;").replace("<", "&lt;")'
             '.replace(">", "&gt;")',
             "    return text"),
    # --- tables ---------------------------------------------------------
    # Re-anchored 2026-09-17: `_table_core._table_spans` found tables as
    # the exact string `<w:tbl>` and now reads them through
    # `_xml.element_spans`, which carries the depth count this tests —
    # for tables, rows and cells alike.
    Mutation("_xml.py", "nested tables close on the first end tag",
             "        end = matching_close(xml, m.end(), tag)",
             '        end = xml.index(f"</w:{tag}>", m.end()) '
             '+ len(f"</w:{tag}>")'),
    # Two, because the guard is now two questions. The first says "is
    # this the document it was read from"; the second, reached only when
    # it is not, says "are this table's own bytes still at its offsets".
    # Sabotaging either one makes a stale handle slice the wrong bytes,
    # and the single mutation that used to stand here was re-anchored on
    # 2026-08-27 — its old line had been rewritten out of the module, so
    # `mutate.py` skipped it and exited 1 while the regression cover for
    # the whole guard sat dead.
    Mutation("_table_core.py", "stale table offsets are used instead of refused",
             "    if table.source is None or table.source == hash(xml):",
             "    if True:"),
    Mutation("_table_core.py", "a MOVED table is rebound instead of refused",
             "    if hash(xml[table.start:table.end]) == table.body:",
             "    if True:"),
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
             "            if m is None or raised:",
             "            if m is None:"),
    Mutation("_table_layout.py",
             "a cmidrule is drawn under every cell, not just the span",
             "            elif i in shape.group_rows and j in spanned:",
             "            elif i in shape.group_rows:"),
    Mutation("_table_layout.py",
             "the three-line style stops clearing the rules it replaces",
             "    full = {side: spec.get(side, (\"nil\", 0)) "
             "for side in _SIDES}",
             "    full = dict(spec)"),
    Mutation("_table_layout.py",
             "only the expanded <w:tcBorders> is matched, so an empty "
             "one gets a second element beside it",
             r'_EDGE_RE = re.compile(r"<w:tcBorders\b[^>]*/>"',
             r'_EDGE_RE = re.compile(r"(?!x)x"'),
    Mutation("_table_layout.py",
             "borders are searched across the whole cell, so a nested "
             "table's rule is rewritten instead of the outer cell's",
             "    own = _own_properties(cell)",
             "\n".join([
                 "    if _EDGE_RE.search(cell):",
                 "        return _EDGE_RE.sub(lambda _: borders, cell,",
                 "                            count=1)",
                 "    own = _own_properties(cell)",
             ])),
    Mutation("revisions.py",
             "a formatting-only revision stops counting as a revision",
             "    return (_has_content_revisions(xml)\n"
             "            or any(marker in xml "
             "for marker in _PROPERTY_MARKERS))",
             "    return _has_content_revisions(xml)"),
    Mutation("_table_layout.py",
             "the border search reaches into a tracked property snapshot",
             "    hit = _EDGE_RE.search(masked)",
             "    hit = _EDGE_RE.search(inner)"),
    Mutation("_xml.py",
             "a properties element closes on the nested old-properties "
             "snapshot instead of its own end tag",
             "    close = matching_close(element, pr.end(), tag)",
             '    close = (element.index(f"</w:{tag}>", pr.end())\n'
             '             + len(f"</w:{tag}>"))'),
    Mutation("_xml.py",
             "the historical snapshot answers property questions for "
             "the formatting in force",
             "    m = _PROPERTY_CHANGE_RE.search(inner)\n"
             "    return inner if m is None else inner[:m.start()]",
             "    return inner"),
    # --- exhibit mentions -----------------------------------------------
    # in `find` since 2026-09-11, beside the caption grammar; `crossrefs`
    # re-exports and is where the tests that kill these two live
    Mutation("find.py",
             "a mention boundary rejects digits only, so Table 1 "
             "matches inside Table 1.1",
             r'NUMBER_END = r"(?!\w)(?!\.\w)(?!-[^\W\d_])"',
             r'NUMBER_END = r"(?!\d)"'),
    Mutation("find.py",
             "a hyphen-suffixed exhibit is matched by its prefix",
             r'NUMBER_END = r"(?!\w)(?!\.\w)(?!-[^\W\d_])"',
             r'NUMBER_END = r"(?!\w)(?!\.\w)"'),
    Mutation("crossrefs.py",
             "the run's other children are dropped when it is rebuilt",
             "                     post=run_xml[t_end:body_to])",
             '                     post="")'),
    Mutation("crossrefs.py",
             "the bookmark-exists check matches prose, not a bookmark",
             "    if _named_bookmark(name).search(para_xml):",
             "    if f'w:name=\"{name}\"' in para_xml:"),
    # --- composition and write targets ------------------------------------
    # Re-pointed 2026-08-12: `standalone` gained `source=` when harvest
    # learned to carry the document's namespace declarations, and the
    # anchor had been drifting — which the harness reports as a failure
    # precisely so it cannot rot unnoticed.
    Mutation("equations.py",
             "a harvested equation cannot be parsed on its own",
             "    return standalone(hits[index].xml, source=xml)",
             "    return hits[index].xml"),
    Mutation("word.py",
             "a write is staged to a copy and silently discarded",
             "    elif local and not read_only:",
             "    elif False:"),
    # --- attribute order -------------------------------------------------
    Mutation("_xml.py",
             "an id is only found when it is the first attribute",
             r"""COMMENT_ID_RE = re.compile(r'<w:comment\b[^>]*w:id="(\d+)"')""",
             r"""COMMENT_ID_RE = re.compile(r'<w:comment w:id="(\d+)"')"""),
    # --- fields ----------------------------------------------------------
    # Re-anchored 2026-08-27: the walk MOVED to `_xml.py`. The anchor text
    # is unchanged, which is why this drifted silently — the module name
    # is the part that went stale, and nothing checks a module still holds
    # the code its mutation names.
    #
    # Re-anchored again 2026-09-17: the pairing moved out of `field_spans`
    # into `fields`, which every reader of a field now shares — so this
    # one mutation covers `field_anchors`, `internal_links` and
    # `dead_links` too, which is what it could never reach while each of
    # them paired begin-to-first-end on its own.
    Mutation("_xml.py",
             "a field ends at the first end tag, so a nested field "
             "closes its parent",
             '        elif m.group(1) == "end" and stack:\n'
             "            top = stack.pop()",
             '        elif m.group(1) == "end" and stack:\n'
             "            top = stack.pop(0)"),
    # --- equation skeletons ----------------------------------------------
    Mutation("revisions.py",
             "accepting a deletion leaves the emptied equation shell "
             "standing, as it did in the DSI paper",
             "    if touched:\n        _prune_math(touched)",
             "    if False:\n        _prune_math(touched)"),
    Mutation("revisions.py",
             "a deliberate U+00A0 spacer counts as an empty shell",
             "    return any(t.text for t in el.iter(MATH + \"t\"))",
             "    return any((t.text or '').strip() "
             "for t in el.iter(MATH + \"t\"))"),
    # Re-pointed: check 7 is `lint._empty_math` now rather than a block
    # inside `lint`'s per-root loop, so the anchor lost four spaces of
    # indentation. The mutation is unchanged.
    Mutation("lint.py",
             "an empty object inside a surviving equation goes unreported",
             "        orphaned += sum(",
             "        orphaned += 0 * sum("),
    # --- new-content guards ----------------------------------------------
    Mutation("body.py",
             "an unstyled template silently builds an unstyled table",
             '    if require_style and "<w:tblStyle" not in tblpr:',
             "    if False:"),
    # --- citations ------------------------------------------------------
    # Re-pointed 2026-08-12: the check grew a SECOND stem (a document
    # linked before `_ascii_stem` existed carries «Aczl1966»), so the
    # single-alpha comparison the mutation named is gone. What it tests
    # is unchanged — drop the surname check and a bookmark matches on
    # its YEAR alone, which is how "(Smith 2020)" got wired to a stray
    # `Jones2020`.
    Mutation("_cite_build.py",
             "an entry bookmark matches on the year alone again",
             "        if any(a and (a.startswith(got) or got.startswith(a))"
             " for a in stems):\n"
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


def in_flight() -> list[tuple[Path, Path]]:
    """(source, saved copy) for every mutation a killed run left behind."""
    if not STASH.is_dir():
        return []
    return sorted((SRC / saved.name, saved) for saved in STASH.iterdir()
                  if saved.is_file())


def stash(path: Path, original: bytes) -> Path:
    """Keep `path`'s pre-mutation bytes where a later run will find them."""
    STASH.mkdir(exist_ok=True)
    saved = STASH / path.name
    saved.write_bytes(original)
    return saved


def unstash(saved: Path) -> None:
    saved.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        STASH.rmdir()                       # only when it is empty


def restore(say: Callable[[str], None] = print) -> int:
    """Put back everything a killed run left mutated."""
    for path, saved in in_flight():
        path.write_bytes(saved.read_bytes())
        unstash(saved)
        say(f"  restored {path.relative_to(ROOT).as_posix()}")
    return 0


def refuse_if_in_flight(say: Callable[[str], None] = print) -> bool:
    """True when a previous run died mid-mutation. Say what and how.

    Refusing rather than restoring silently: the saved bytes are right,
    but an author who has EDITED the file since the kill would have that
    edit overwritten by a tool they only asked to measure something.
    """
    left = in_flight()
    if not left:
        return False
    say("a previous run was killed while a mutation was applied, so these "
        "files carry a DEFECT on purpose:\n")
    for path, saved in left:
        say(f"  {path.relative_to(ROOT).as_posix()}   "
            f"(original in {saved.relative_to(ROOT).as_posix()})")
    say("\nDo not commit them. `python tools/mutate.py --restore` puts them "
        "back; check `git diff` first if you have edited them since.")
    return True


def _workers() -> str:
    """Same rule as `tools/gates.py`: the PHYSICAL core count.

    Measured there on this suite — serial 108 s, `-n 4` 45.5 s, `-n 8`
    37.1 s, `-n auto` (16 logical) 53.4 s. The knee is at the physical
    count, so `auto` is the wrong default on an SMT machine.
    """
    return str(max(2, min(8, (os.cpu_count() or 4) // 2)))


def run(tests: str) -> tuple[bool, str]:
    """The suite against the mutated tree. True when it went red.

    `-x` stops at the first failure, which is all a mutation needs: the
    question is whether ANY test notices. Across the workers, because
    this is 39 suite runs and it is now in the gate chain.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:randomly",
         "-n", _workers(), *(tests.split() or [])],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    line = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    return proc.returncode != 0, line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--restore", action="store_true",
                    help="put back what a killed run left mutated")
    ap.add_argument("-k", default="", help="substring filter on the label")
    args = ap.parse_args()

    chosen = [m for m in MUTATIONS if args.k.lower() in m.label.lower()]
    if args.list:
        for m in chosen:
            print(f"  {m.module:<14} {m.label}")
        return 0
    if args.restore:
        if not in_flight():
            return print("nothing in flight; the tree is as you left it") or 0
        return restore()
    if refuse_if_in_flight():
        return 2

    caught, survived, skipped = 0, [], []
    for m in chosen:
        path = SRC / m.module
        # BYTES, restored byte-for-byte. `read_text` decodes through
        # universal newlines and the restore wrote back with newline="",
        # so every module a run touched came back LF in a CRLF checkout —
        # twelve of them, from one run. Invisible here because
        # `core.autocrlf=true` normalises it away, and a twelve-file
        # whole-file diff on a checkout without it.
        original = path.read_bytes()
        crlf = b"\r\n" in original
        text = original.decode("utf-8").replace("\r\n", "\n")
        if text.count(m.old) != 1:
            skipped.append(f"{m.label} (anchor {text.count(m.old)}x)")
            continue
        mutant = text.replace(m.old, m.new)
        saved = stash(path, original)
        path.write_bytes(
            (mutant.replace("\n", "\r\n") if crlf else mutant).encode("utf-8"))
        try:
            died, _line = run(m.tests)
        finally:
            path.write_bytes(original)
            unstash(saved)
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
