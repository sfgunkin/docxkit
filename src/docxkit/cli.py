r"""``docxkit`` command line — the one-off jobs, without a throwaway script.

    docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json R.json]
    docxkit citations PAPER.docx
    docxkit crossrefs PAPER.docx [--write] [--audit]
    docxkit inspect PAPER.docx [--comments] [--revisions]
    docxkit locate PAPER.docx ANCHOR... | --revisions
    docxkit text PAPER.docx [--tracked final|original]
    docxkit lint PAPER.docx
    docxkit verify PAPER.docx
    docxkit pdf PAPER.docx OUT.pdf [--pages 1-3]
    docxkit pages PAPER.docx
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from .console import utf8_stdout
from .errors import DocxKitError
from .find import P_RE, text_of


def cmd_compare(args: argparse.Namespace) -> int:
    from .compare import compare, render
    rep = compare(args.built, args.edited)
    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    # compare is a verbatim port and untyped; render returns the exit code
    return int(render(rep, args.expect_clean))


def cmd_citations(args: argparse.Namespace) -> int:
    from .citations import check_citations
    return 1 if check_citations(args.docx) > 0 else 0


def cmd_crossrefs(args: argparse.Namespace) -> int:
    """Link every figure and table to its first mention, and back."""
    from . import crossrefs
    from .lint import lint_parts
    from .package import backup, read_parts, write_docx

    parts = read_parts(args.docx)
    doc = parts["word/document.xml"].decode("utf-8")
    name = Path(args.docx).name

    if args.audit:
        state = crossrefs.audit(doc)
        print(name)
        for key in ("linked", "caption_only", "mention_only", "dangling"):
            found = state[key]
            print(f"  {key:<13} {len(found):>3}"
                  f"{'  ' + ', '.join(found) if found else ''}")
        return 1 if state["dangling"] else 0

    linked, report = crossrefs.link(doc)
    print(name)
    print("  " + report.format().replace("\n", "\n  "))

    if not args.write:
        print("  (dry run - pass --write to save)")
        return 0 if report.complete else 1

    parts["word/document.xml"] = linked.encode("utf-8")
    if problems := lint_parts(parts):
        for problem in problems:
            print(f"  - {problem}")
        return 1
    # this writes over the author's file, so snapshot it first
    kept = backup(args.docx, tag="pre_crossrefs")
    write_docx(args.docx, parts)
    print(f"  written; previous version kept at {kept.name}")
    return 0 if report.complete else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    with zipfile.ZipFile(args.docx) as z:
        names = z.namelist()
        doc = z.read("word/document.xml").decode("utf-8")
        com = (z.read("word/comments.xml").decode("utf-8")
               if "word/comments.xml" in names else "")
    from .revisions import counts
    ins, dele = counts(doc)
    starts = re.findall(r'<w:bookmarkStart w:id="(\d+)"', doc)
    ends = re.findall(r'<w:bookmarkEnd w:id="(\d+)"', doc)
    omath = len(re.findall(r"<m:oMath>", doc))
    n_com = len(re.findall(r"<w:comment w:id=", com))
    print(f"{Path(args.docx).name}")
    print(f"  parts       {len(names)}")
    print(f"  paragraphs  {len(P_RE.findall(doc))}")
    print(f"  tables      {doc.count('<w:tbl>')}")
    print(f"  equations   {omath}")
    print(f"  revisions   {ins} ins / {dele} del")
    print(f"  bookmarks   {len(starts)}/{len(ends)}"
          f"{'  UNBALANCED' if sorted(starts) != sorted(ends) else ''}")
    print(f"  comments    {n_com}")
    if args.comments and com:
        for m in re.finditer(r"<w:comment [^>]*>(.*?)</w:comment>", com,
                             re.DOTALL):
            print(f"    - {text_of(m.group(1)).strip()[:110]}")
    if args.revisions:
        from .revisions import revision_text, spans
        for span in spans(doc)[:200]:
            kind = "ins" if doc[span[0]:span[0] + 6] == "<w:ins" else "del"
            print(f"    [{kind}] {revision_text(doc, span)[:100]!r}")
    return 0


_LocateRows = tuple[list[dict[str, object]], list[str], list[str]]


def _revision_rows(doc: object, limit: int | None) -> _LocateRows:
    """(json rows, report lines, misses) for every tracked revision."""
    from .word import revision_locations
    rows: list[dict[str, object]] = []
    lines = []
    for rev in revision_locations(doc, limit=limit):
        rows.append(rev._asdict())
        text = " ".join(rev.text.split())[:60]
        lines.append(f"  {rev.number:>4}  p.{rev.page:>4}  l.{rev.line:>3}  "
                     f"[{rev.kind}] {text}")
    return rows, lines, []


def _anchor_rows(doc: object, anchors: list[str], ordered: bool
                 ) -> _LocateRows:
    """(json rows, report lines, misses) for the anchors the user gave."""
    from .word import locate_in
    located = locate_in(doc, anchors, ordered=ordered, strict=False)
    rows: list[dict[str, object]] = []
    lines = []
    for loc in located:
        rows.append(loc._asdict())
        note = "  (repeats)" if loc.repeats else ""
        lines.append(f"  p.{loc.page:>4}  l.{loc.line:>3}  "
                     f"{' '.join(loc.anchor.split())[:60]}{note}")
    hit = {loc.anchor for loc in located}
    return rows, lines, [a for a in anchors if a not in hit]


def cmd_locate(args: argparse.Namespace) -> int:
    """Which page (and line) does this text land on, once Word lays it out?"""
    from .word import WD_STATISTIC_PAGES, open_doc, session

    anchors = list(args.anchor)
    if args.anchors_from:
        anchors += [ln.strip() for ln
                    in Path(args.anchors_from).read_text(
                        encoding="utf-8").splitlines() if ln.strip()]
    if not anchors and not args.revisions:
        print("docxkit locate: give an anchor, --anchors-from or --revisions")
        return 2

    # One session for both the lookups and the page total, so the file is
    # opened once rather than once per question.
    with session() as word, open_doc(word, args.docx) as doc:
        rows, lines, missing = (
            _revision_rows(doc, args.limit) if args.revisions
            else _anchor_rows(doc, anchors, args.ordered))
        pages = int(doc.ComputeStatistics(WD_STATISTIC_PAGES))

    print(f"{Path(args.docx).name}  ({pages} pages)")
    for line in lines:
        print(line)
    for anchor in missing:
        print(f"  NOT FOUND  {anchor[:60]!r}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if missing else 0


def cmd_text(args: argparse.Namespace) -> int:
    """Dump visible text from one side of the tracked changes."""
    from .revisions import text
    with zipfile.ZipFile(args.docx) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    for line in text(doc, args.tracked):
        print(line)
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Structural checks for the markup Word refuses to open."""
    from .lint import lint_parts
    from .package import read_parts
    problems = lint_parts(read_parts(args.docx))
    print(f"{Path(args.docx).name}")
    if not problems:
        print("  clean - no structural problems found")
        return 0
    for problem in problems:
        print(f"  - {problem}")
    return 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Does Word read this file back as written, or repair it on open?"""
    from .tracked import verify
    report = verify(args.docx)
    pkg, wrd = report["package"], report["word"]
    print(f"{Path(args.docx).name}")
    print(f"  package : {pkg['insertions']} ins / {pkg['deletions']} del / "
          f"{pkg['comments']} comments")
    print(f"  Word    : {wrd['revisions']} revisions / {wrd['comments']} "
          f"comments / {wrd['paragraphs']} paragraphs")
    if not report["comments_match"]:
        print("  VERDICT : MISMATCH - Word altered the file on open")
        return 1
    if pkg["comments"] == 0:
        # Word merges adjacent revisions, so its revision count legitimately
        # differs from the element count; comments are the one exact
        # cross-check, and with none there is nothing to compare.
        print("  VERDICT : opened without error (no comments to cross-check; "
              "revision counts differ legitimately - Word merges adjacent "
              "revisions)")
        return 0
    print("  VERDICT : clean - Word reads back every comment the package "
          "holds")
    return 0


def cmd_pdf(args: argparse.Namespace) -> int:
    from .word import export_pdf
    first = last = None
    if args.pages:
        a, _, b = args.pages.partition("-")
        first, last = int(a), int(b or a)
    out = export_pdf(args.docx, args.out, first=first, last=last)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_pages(args: argparse.Namespace) -> int:
    from .word import page_count
    print(page_count(args.docx))
    return 0


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(
        prog="docxkit", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("compare", help="multi-layer diff of two .docx")
    p.add_argument("built")
    p.add_argument("edited")
    p.add_argument("--json", metavar="PATH")
    p.add_argument("--expect-clean", action="store_true")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("citations", help="citation / reference link audit")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_citations)

    p = sub.add_parser(
        "crossrefs",
        help="link figures/tables to their first mention (and back)")
    p.add_argument("docx")
    p.add_argument("--write", action="store_true",
                   help="save the result; without it this is a dry run")
    p.add_argument("--audit", action="store_true",
                   help="report the current state and change nothing")
    p.set_defaults(fn=cmd_crossrefs)

    p = sub.add_parser("inspect", help="structural summary")
    p.add_argument("docx")
    p.add_argument("--comments", action="store_true")
    p.add_argument("--revisions", action="store_true")
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser(
        "locate", help="page/line of a phrase, laid out (needs Word)")
    p.add_argument("docx")
    p.add_argument("anchor", nargs="*",
                   help="visible text to find; repeatable")
    p.add_argument("--anchors-from", metavar="FILE",
                   help="read anchors from a file, one per line")
    p.add_argument("--revisions", action="store_true",
                   help="locate every tracked revision instead "
                        "(the redline's own pages)")
    p.add_argument("--limit", type=int, metavar="N",
                   help="stop after N revisions")
    p.add_argument("--ordered", action="store_true",
                   help="anchors are in document order: search forward from "
                        "the last hit, which is faster and picks the right "
                        "occurrence of a repeated phrase")
    p.add_argument("--json", metavar="PATH")
    p.set_defaults(fn=cmd_locate)

    p = sub.add_parser("text", help="dump the visible text")
    p.add_argument("docx")
    p.add_argument("--tracked", choices=("final", "original"),
                   default="final",
                   help="which side of tracked changes to show")
    p.set_defaults(fn=cmd_text)

    p = sub.add_parser("lint",
                       help="structural checks (no Word needed)")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("verify",
                       help="does Word read this back unchanged? (needs Word)")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("pdf", help="render to PDF via Word")
    p.add_argument("docx")
    p.add_argument("out")
    p.add_argument("--pages", metavar="A-B")
    p.set_defaults(fn=cmd_pdf)

    p = sub.add_parser("pages", help="laid-out page count (needs Word)")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_pages)

    args = ap.parse_args()
    try:
        sys.exit(args.fn(args))
    except DocxKitError as exc:
        sys.exit(f"docxkit: {exc}")


if __name__ == "__main__":
    main()
