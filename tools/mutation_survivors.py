"""Sort a cosmic-ray run's survivors into the kinds worth acting on.

    python tools/mutation_survivors.py run.sqlite src/docxkit/styles.py

`cr-report` gives a survival PERCENTAGE, and in this package that number
is close to meaningless: every module carries
``from __future__ import annotations``, so annotations are strings that
are never evaluated and a mutation inside one cannot change behaviour.
Measured on ``styles.py``: 225 survivors, **187 of them inside a type
annotation** — equivalent by construction, not missing tests. A reader
who takes the headline at face value is reading 56% when the real figure
is 9.5%, and the usual response to a number like that is to stop running
the tool.

So this prints the survivors that are actually a question, grouped by
the definition they landed in, and says which line each is on. What to
do with them is in CONTRIBUTING: a real gap, an equivalent mutant, or
cosmetic — and only the first is a test.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def annotation_spans(tree: ast.Module) -> list[tuple[int, int, int, int]]:
    """Every (row, col, row, col) span that belongs to an annotation."""
    spans: list[tuple[int, int, int, int]] = []
    for node in ast.walk(tree):
        found: list[ast.expr] = []
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            found = [a.annotation for a in
                     args.args + args.posonlyargs + args.kwonlyargs
                     if a.annotation is not None]
            if node.returns is not None:
                found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found = [node.annotation]
        for ann in found:
            if ann.end_lineno is not None and ann.end_col_offset is not None:
                spans.append((ann.lineno, ann.col_offset,
                              ann.end_lineno, ann.end_col_offset))
    return spans


def definitions(tree: ast.Module) -> list[tuple[int, int, str]]:
    """Every def/class as (first line, last line, name)."""
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return [(n.lineno, n.end_lineno or n.lineno, n.name)
            for n in ast.walk(tree) if isinstance(n, kinds)]


def owner_of(defs: list[tuple[int, int, str]], line: int) -> str:
    """The INNERMOST definition containing `line`.

    By span, not by "the last `def` above it". A function with nested
    helpers — `replace_in_para` has four — otherwise hands every survivor
    in its own body to whichever helper was defined last, which is how
    three mutants sat under `label_end` in a report that decided which
    cluster to work on next.
    """
    holding = [(hi - lo, name) for lo, hi, name in defs if lo <= line <= hi]
    return min(holding)[1] if holding else "<module>"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    db_path, src_path = sys.argv[1], sys.argv[2]
    text = Path(src_path).read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    spans = annotation_spans(tree)

    def in_annotation(row: int, col: int) -> bool:
        return any(r1 <= row <= r2
                   and (row != r1 or col >= c1)
                   and (row != r2 or col <= c2)
                   for r1, c1, r2, c2 in spans)

    rows = sqlite3.connect(db_path).execute("""
        SELECT s.start_pos_row, s.start_pos_col, s.operator_name,
               r.test_outcome
        FROM mutation_specs s JOIN work_results r ON s.job_id = r.job_id
        ORDER BY s.start_pos_row
    """).fetchall()
    if not rows:
        print("no results in that database — has `cosmic-ray exec` run?")
        return 2

    # SKIPPED rows are the ones `mutation_session.py --sample` marked so
    # they would not run. Counting them as killed reads a 460-mutant
    # sample as 1361 mutants with 901 free kills, and the share then
    # answers a question nobody asked.
    skipped = [r for r in rows if r[3] == "SKIPPED"]
    ran = [r for r in rows if r[3] != "SKIPPED"]
    survived = [r for r in ran if r[3] == "SURVIVED"]
    real = [r for r in survived if not in_annotation(r[0], r[1])]
    annotated = len(survived) - len(real)
    killed = len(ran) - len(survived)
    sample = f" (sampled from {len(rows)})" if skipped else ""
    print(f"{len(ran)} mutants run{sample} · {killed} killed · "
          f"{len(survived)} survived")
    print(f"  {annotated} of the survivors are inside a TYPE "
          f"ANNOTATION — equivalent by\n  construction (PEP 563: never "
          f"evaluated), so they are not a question")
    # An annotation mutant cannot be killed, so every one that ran also
    # survived: taking them out of the numerator means taking the same
    # count out of the denominator, or the rate is quietly deflated.
    base = len(ran) - annotated
    share = len(real) / base * 100 if base else 0.0
    print(f"  {len(real)} to actually look at — REAL SURVIVAL "
          f"{share:.1f}% ({len(real)}/{base})\n")

    defs = definitions(tree)
    by_line: dict[int, list[str]] = {}
    for row, _col, op, _ in real:
        by_line.setdefault(row, []).append(op.replace("core/", ""))

    for line, ops in sorted(by_line.items()):
        print(f"  L{line:<5} x{len(ops):<3} in {owner_of(defs, line)}")
        print(f"          {lines[line - 1].strip()[:82]}")
        print(f"          {', '.join(sorted(set(ops)))[:82]}")

    per_def = Counter(owner_of(defs, line) for line in by_line
                      for _ in by_line[line])
    if per_def:
        print("\nby definition:",
              ", ".join(f"{n}x {name}" for name, n in per_def.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
