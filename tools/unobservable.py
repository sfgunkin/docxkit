"""Lines where EVERY mutant survived — the fourth answer, from stored runs.

Killable, equivalent and cosmetic all assume the line can do something.
A fourth answer turned up three times on 2026-09-18 and was found by
hand each time: a line that CANNOT ACT, because a value it depends on is
fixed by a caller or a callee rather than by the input.

    wrap_visible_span's right guard   10 mutants, 10 survived —
        `split_run` returns '' for the right half of a cut at a run's
        own end, so the `after = ""` beneath it assigns '' to ''
    _xml.fields' `else m.end()`        4 of 4 — a mid-tag truncation
        means no end marker can follow, so the field never closes and
        the value is never read
    field_spans' `if f.end < 0`        4 of 4 — the field is refused a
        line later by `close < 0` anyway

Each cost an hour of reasoning that the session files already held, and
each has the same signature in them: every mutant on that SUB-EXPRESSION
survived and none was killed. This reads every stored session and ranks
those clusters.

A CLUSTER IS A CANDIDATE, NOT A VERDICT. The line may equally be one
nothing tests. What tells the two apart is reading the callee — see
`docs/mutation-testing.md`, "probe the callee before reasoning about the
caller's guard" — and the report says so where a hurried reader meets it.

THREE SPECIES COME OUT OF ONE SIGNATURE, and the report separates them
because they ask for different work:

* on a line the harness never executes — a test that reaches it, or a
  deletion. Read off the run's own coverage file, and the reason the
  label exists: the first whole run's top candidates were eleven
  mutants turning `para_xml[:lo] + para_xml[hi:]` into `-`, `*` and `/`
  between two STRINGS, which raises the moment the line runs;
* inside a MESSAGE — untested wording, the cosmetic answer, and five of
  those took the top of the first ranking and buried everything else;
* the rest — read the callee. This is the one the tool is named for.

A session's line numbers are ITS snapshot's, not today's, so every
cluster is reported with the session's staleness beside it. A cluster
from a void session names a line that may no longer exist; it is still
evidence that something on that function could not act, and
`render_survivors` is what re-anchors it.

    python tools/unobservable.py [--min N] [MODULE ...]
"""
from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_map import HARNESS, harness_for
from mutation_survivors import (
    annotation_spans,
    became,
    claimed_by_operator,
    claimed_equivalents,
    definitions,
    excluded_patterns,
    excluded_spans,
    main_guard_spans,
    marker_positions,
    owner_of,
    pristine_source,
    within,
)
from stale_figures import (
    ROOT,
    main_checkout,
    session_file,
    state,
)

#: Sessions live beside the MAIN checkout, not beside whatever worktree a
#: round is being worked in — the same reason `--running` had to be
#: taught to look there. Every session file, snapshot and staleness
#: verdict below is resolved against it.
SESSIONS = main_checkout()


@dataclass
class Cluster:
    """One SUB-EXPRESSION on which every mutant that ran survived.

    Keyed on (row, column) rather than on the row alone, and that is the
    correction the first run of this tool earned. Of the three known
    instances it was built from, a row-keyed signature found ONE: the
    other two sit on lines that do act, and only a part of them cannot.

        `stack[-1].sep_end = close + 1 if close >= 0 else m.end()`
            23 mutants killed on that row, 4 survived — the `+ 1` is
            observable and the `else m.end()` is not
        `if f.end < 0:` in `field_spans`
            4 killed, 4 survived — the guard runs, and the half of it
            that would refuse a cut field is refused again a line later

    Cosmic-ray records the column it mutated, so the two halves of such
    a line are two clusters, and the one that cannot act is visible.
    """

    module: str
    line: int
    col: int
    owner: str
    survived: int
    killed_here: int        # on the same ROW, at other columns
    text: str
    mutants: list[str]
    staleness: str
    in_message: bool = False
    uncovered: bool = False

    def show(self) -> str:
        rest = (f", {self.killed_here} killed elsewhere on the line"
                if self.killed_here else "")
        where = ("NOT COVERED, " if self.uncovered else
                 "in a MESSAGE, " if self.in_message else "")
        head = (f"{self.survived:3d}x  {self.module}:{self.line}:{self.col}"
                f"  in {self.owner}   [{where}{self.staleness}{rest}]")
        body = [f"        {self.text.strip()[:70]}"]
        body += [f"     -> {m[:70]}" for m in self.mutants[:4]]
        if len(self.mutants) > 4:
            body.append(f"        … and {len(self.mutants) - 4} more")
        return "\n".join([head, *body])


def message_spans(tree: ast.Module) -> list[tuple[int, int, int, int]]:
    """Every string literal and f-string, as `within` spans.

    A cluster INSIDE one is a different species from a line that cannot
    act: the arithmetic in `f"other {len(members) - 1} in the series"`
    can be told from its neighbours by any test that reads the message,
    and none does. That is the COSMETIC answer — untested wording — and
    mixing it into a list about unobservable code buries the finding
    under the top of the ranking, which is where this tool's first whole
    run put it. Labelled rather than dropped: an arithmetic inside a
    message is still a question, just a different one.
    """
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) or (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)):
            out.append((node.lineno, node.col_offset,
                        node.end_lineno or node.lineno,
                        node.end_col_offset or node.col_offset))
    return out


def covered_lines(db: Path) -> set[int] | None:
    """Which lines the harness EXECUTED, from the run's own coverage.

    None when the session kept no coverage file, in which case nothing
    below claims anything about coverage.

    This is the third species and the one that changes what a reader
    should do. A cluster on a line nothing executes is not a line that
    cannot act: it is a line nothing runs, and the answer is a test that
    reaches it or a deletion — not a reading of the callee. Measured on
    the first whole run: `equations.py:1089`'s eleven mutants turn
    `para_xml[:lo] + para_xml[hi:]` into `-`, `*` and `/` between two
    STRINGS, which raises the moment the line executes. Eleven survivors
    is not subtlety; it is a line that never ran.
    """
    beside = db.with_suffix("").with_suffix(".coverage.json")
    if not beside.is_file():
        return None
    with beside.open(encoding="utf-8") as fh:
        return {int(line) for line in json.load(fh)}


#: How far a session's word can be trusted, for the sort. Anything the
#: staleness check does not call fresh or stale — "never measured", a
#: module that moved — ranks last: its line numbers are its own
#: snapshot's and the cluster may name a line that no longer exists.
_AGE = {"fresh": 0, "stale": 1}

#: What a session says about one row, once the discounts are applied.
_QUERY = """
    SELECT s.start_pos_row, s.start_pos_col, s.operator_name,
           r.test_outcome, r.diff
    FROM mutation_specs s JOIN work_results r ON s.job_id = r.job_id
    ORDER BY s.start_pos_row
"""


@dataclass
class Dropped:
    """What was filtered, so that nothing is subtracted in silence."""

    annotations: int = 0
    markers: int = 0
    excluded: int = 0
    claimed: int = 0
    mixed: int = 0          # the line also had a KILL, so it can act

    def show(self) -> str:
        return (f"discounted: {self.annotations} annotation, "
                f"{self.markers} keyword-only, {self.excluded} no-cover, "
                f"{self.claimed} already claimed; {self.mixed} line(s) had "
                f"a kill as well and can act")


def clusters_in(module: str, least: int, dropped: Dropped, *,
                keep_claimed: bool = False) -> list[Cluster]:
    """Every line of `module` on which nothing was killed and `least` or
    more mutants survived."""
    db = session_file(module, beside=SESSIONS)
    if not db.is_file():
        return []
    src = str(SESSIONS / "src" / "docxkit" / module)
    src, _note = pristine_source(str(db), src)
    text = Path(src).read_text(encoding="utf-8")
    tree = ast.parse(text)
    lines = text.splitlines()
    spans = annotation_spans(tree)
    guards = main_guard_spans(tree)
    markers = set(marker_positions(text, tree))
    nocov = excluded_spans(text, tree, excluded_patterns(ROOT))
    defs = definitions(tree)
    messages = message_spans(tree)
    covered = covered_lines(db)
    claims = claimed_equivalents(src)
    by_operator = claimed_by_operator(src)

    rows = sqlite3.connect(str(db)).execute(_QUERY).fetchall()
    ran = [r for r in rows if r[3] != "SKIPPED"]
    #: killed at this exact sub-expression, and anywhere on its row
    killed_at: set[tuple[int, int]] = {(r[0], r[1]) for r in ran
                                       if r[3] != "SURVIVED"}
    killed_row: dict[int, int] = defaultdict(int)
    for r in ran:
        if r[3] != "SURVIVED":
            killed_row[r[0]] += 1
    survivors: dict[tuple[int, int], list[tuple[str, str]]] = defaultdict(list)
    for row, col, operator, _outcome, diff in ran:
        if _outcome != "SURVIVED":
            continue
        if within(spans, row, col):
            dropped.annotations += 1
            continue
        if (row, col) in markers:
            dropped.markers += 1
            continue
        if within(guards, row, col) or within(nocov, row, col):
            dropped.excluded += 1
            continue
        mutant = became(diff)
        if (mutant in claims or operator in by_operator) and not keep_claimed:
            dropped.claimed += 1
            continue
        survivors[row, col].append((mutant, operator))

    verdict, _moved = state(module, HARNESS.get(module, harness_for(module)),
                            db=db)
    out = []
    for (row, col), found in survivors.items():
        if (row, col) in killed_at:
            dropped.mixed += 1
            continue
        if len(found) < least:
            continue
        out.append(Cluster(
            module=module, line=row, col=col, owner=owner_of(defs, row),
            survived=len(found), killed_here=killed_row.get(row, 0),
            text=lines[row - 1] if row <= len(lines) else "",
            mutants=[m or f"({op})" for m, op in found],
            staleness=verdict, in_message=within(messages, row, col),
            uncovered=covered is not None and row not in covered))
    return out


def report(modules: list[str], least: int, keep_claimed: bool = False) -> int:
    dropped = Dropped()
    found: list[Cluster] = []
    read = 0
    for module in modules:
        if not session_file(module, beside=SESSIONS).is_file():
            continue
        read += 1
        found += clusters_in(module, least, dropped,
                             keep_claimed=keep_claimed)

    print(f"{read} session(s) read, {len(found)} line(s) where {least} or "
          f"more mutants ran and NONE was killed\n")
    print("A cluster is a CANDIDATE, not a verdict: a line that cannot act "
          "and a line\nnothing tests look the same from here. What tells "
          "them apart is reading the\nCALLEE — the value the line depends "
          "on may be fixed before the input arrives.\n")
    # Read-the-callee clusters first, then messages, then the lines
    # nothing runs: three species, and only the first is what this tool
    # is named for. Within each, FRESH before stale before void, and
    # only then by size.
    #
    # The staleness belongs in the SORT and not only in the label, which
    # the first run by a second reader found: the two 11x clusters at
    # the top were `equations.py`'s, from a stale session, and both had
    # been killed hours earlier by another round. A reader sorting by
    # count met a settled cluster first, twice. A FRESH 2x is a better
    # candidate than a stale 11x — the stale one may already be dead,
    # and the fresh one cannot be.
    for cluster in sorted(found, key=lambda c: (c.uncovered, c.in_message,
                                                _AGE.get(c.staleness, 2),
                                                -c.survived, c.module,
                                                c.line)):
        print(cluster.show())
        print()
    kinds = (sum(1 for c in found if not c.uncovered and not c.in_message),
             sum(1 for c in found if c.in_message and not c.uncovered),
             sum(1 for c in found if c.uncovered))
    print(f"{kinds[0]} to READ THE CALLEE for, {kinds[1]} inside a message "
          f"(untested wording), {kinds[2]} on a line the harness never "
          f"executes (a test or a deletion, not a reading)")
    print(dropped.show())
    stale = [c for c in found if c.staleness != "fresh"]
    if stale:
        print(f"{len(stale)} of them come from a session that is not fresh "
              f"— its line numbers are its own snapshot's, so re-anchor "
              f"with render_survivors before quoting a line.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Lines where every mutant survived — candidates for a "
                    "line that cannot act.")
    ap.add_argument("modules", nargs="*",
                    help="e.g. _xml.py revision/_promote.py "
                         "(default: every module with a session)")
    ap.add_argument("--min", type=int, default=2, metavar="N",
                    help="how many survivors make a cluster (default 3)")
    ap.add_argument("--claimed", action="store_true",
                    help="keep mutants already argued in equivalents.toml. "
                         "The triage list drops them — they are settled — "
                         "but a line whose whole cluster is claimed is "
                         "where this signature was learned, so checking it "
                         "against a KNOWN answer needs them back")
    args = ap.parse_args(argv)
    modules = args.modules or sorted(HARNESS)
    return report(modules, args.min, keep_claimed=args.claimed)


if __name__ == "__main__":
    sys.exit(main())
