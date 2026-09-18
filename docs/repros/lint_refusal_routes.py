r"""How many real manuscripts would `cli._save` refuse to write to?

READ-ONLY. For each .docx it does exactly what the write path does
before writing — `preserve_space` over document.xml, then `lint_parts`
over the package — and records the findings that survive that repair.
A file with any is one where every mutating docxkit command refuses,
whatever the command was asked to do.

    python measure_save_refusals.py <root> [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
import zipfile
from pathlib import Path

SKIP = re.compile(r"~\$|backup|_old|_pre_|\.tmp|userbackup|bak_",
                  re.IGNORECASE)


def kind(finding: str) -> str:
    """The finding's class, without the quoted specimen."""
    for head in ("w:t has edge whitespace", "duplicate revision w:id",
                 "empty m:oMath shell", "empty math object",
                 "sits directly in w:p", "has run-level child",
                 "w:del contains w:t", "block w:", "after w:rPr",
                 "w:rPrChange is not the last child", "carries two",
                 "elements (it may carry one)", "not well-formed XML"):
        if head in finding:
            return head
    return finding[:40]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from docxkit.edit import preserve_space
    from docxkit.lint import lint_parts
    from docxkit.package import read_parts
    from docxkit._xml import DOCUMENT

    files = [p for root in args.roots
             for p in sorted(Path(root).rglob("*.docx"))
             if not SKIP.search(str(p))]
    if args.limit:
        files = files[:args.limit]

    refused: list[tuple[Path, list[str]]] = []
    classes: collections.Counter[str] = collections.Counter()
    unreadable = 0
    for path in files:
        try:
            parts = read_parts(path)
            if DOCUMENT not in parts:
                unreadable += 1
                continue
            fixed, _ = preserve_space(parts[DOCUMENT].decode("utf-8"))
            parts[DOCUMENT] = fixed.encode("utf-8")
            problems = lint_parts(parts)
        except (OSError, zipfile.BadZipFile, ValueError, UnicodeDecodeError):
            unreadable += 1
            continue
        if problems:
            refused.append((path, problems))
            for problem in problems:
                classes[kind(problem)] += 1

    print(f"{len(files)} manuscript(s) read, {unreadable} unreadable")
    print(f"{len(refused)} would be REFUSED every write "
          f"({100 * len(refused) / max(1, len(files)):.1f}%)\n")
    for name, n in classes.most_common():
        print(f"  {n:>5}  {name}")
    print("\nfirst 15 files:")
    for path, problems in refused[:15]:
        print(f"  {path.name}: {'; '.join(sorted({kind(p) for p in problems}))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
