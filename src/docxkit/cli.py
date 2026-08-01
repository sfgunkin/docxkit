r"""``docxkit`` command line — the one-off jobs, without a throwaway script.

    docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json R.json]
    docxkit citations PAPER.docx
    docxkit refstyle PAPER.docx [--chicago] [--json R.json]
    docxkit crossrefs PAPER.docx [--write] [--audit]
    docxkit inspect PAPER.docx [--comments] [--revisions]
    docxkit locate PAPER.docx ANCHOR... | --revisions
    docxkit text PAPER.docx [--tracked final|original] [--md]
    docxkit count PAPER.docx [--exclude references,tables] [--limit N]
    docxkit tasks PAPER.docx [--all] [--check] [--done ID,ID]
    docxkit figures PAPER.docx [--check]
    docxkit smarten PAPER.docx [--write]
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


def cmd_refstyle(args: argparse.Namespace) -> int:
    """Citation and reference FORMAT, against the house author-date style.

    ``citations`` audits the links; this audits the writing — initials,
    "and" not "&", "(2020).", en-dashes, alphabetical order, and the
    cited/listed cross-check.
    """
    from .package import read_parts
    from .refstyle import CHICAGO, HOUSE, audit
    report = audit(read_parts(args.docx),
                   CHICAGO if args.chicago else HOUSE)
    print(Path(args.docx).name)
    print("  " + report.format().replace("\n", "\n  "))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report.as_rows(), ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 1 if report.issues else 0


def cmd_crossrefs(args: argparse.Namespace) -> int:
    """Link every figure and table to its first mention, and back."""
    from . import crossrefs
    from .package import read_parts

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

    if not _write_document(args.docx, parts, linked, "pre_crossrefs"):
        return 1
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
    # \b, not ">": an oMath can carry attributes, and the bare-tag form
    # undercounted AFI v13 by two
    omath = len(re.findall(r"<m:oMath[ >]", doc))
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
    if args.md:
        from .export import to_markdown
        from .package import read_parts
        print(to_markdown(read_parts(args.docx), view=args.tracked), end="")
        return 0
    from .revisions import text
    with zipfile.ZipFile(args.docx) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    for line in text(doc, args.tracked):
        print(line)
    return 0


def _write_back(path: str, parts: dict[str, bytes], tag: str) -> str:
    """Backup, then save — the one way an in-place command writes."""
    from .package import backup, write_docx
    kept = backup(path, tag=tag)
    write_docx(path, parts)
    return kept.name


def _write_document(path: str, parts: dict[str, bytes], doc_xml: str,
                    tag: str) -> bool:
    """The save path for a command that edited ``document.xml``.

    Runs ``preserve_space`` first — the mandatory last build step, and
    without it a PRE-EXISTING fragile edge space blocks an unrelated
    write at the lint gate (found by smartening le14, whose references
    carried four) — then lints, backs up and writes. Returns False when
    the lint refused and nothing was written.
    """
    from .edit import preserve_space
    from .lint import lint_parts
    doc_xml, protected = preserve_space(doc_xml)
    if protected:
        print(f"  protected {protected} edge-whitespace run(s) "
              f"(preserve_space)")
    parts["word/document.xml"] = doc_xml.encode("utf-8")
    if problems := lint_parts(parts):
        for problem in problems:
            print(f"  - {problem}")
        return False
    kept = _write_back(path, parts, tag)
    print(f"  written; previous version kept at {kept}")
    return True


def cmd_tasks(args: argparse.Namespace) -> int:
    """The margin comments as a work list; --check gates a submission."""
    from .comments import set_done, threads
    from .package import read_parts

    parts = read_parts(args.docx)
    if args.done:
        n = set_done(parts, [i.strip() for i in args.done.split(",")])
        if n == 0:
            print("no comment matched those ids; nothing written")
            return 1
        kept = _write_back(args.docx, parts, "pre_tasks")
        print(f"marked {n} comment(s) done; previous version kept at "
              f"{kept}")
        return 0

    found = threads(parts)
    open_threads = [t for t in found if not t.done]
    print(f"{Path(args.docx).name}  ({len(found)} thread(s), "
          f"{len(open_threads)} open)")
    for t in found:
        if t.done and not args.all:
            continue
        box = "x" if t.done else " "
        head = f"  [{box}] #{t.comment.cid} {t.comment.author}: "
        line = " ".join(t.comment.text.split())[:70]
        print(head + line)
        if t.comment.anchor:
            print(f"        on: {' '.join(t.comment.anchor.split())[:60]!r}")
        for r in t.replies:
            print(f"        re: {r.author}: "
                  f"{' '.join(r.text.split())[:60]}")
    if args.json:
        rows = [{
            "cid": t.comment.cid, "author": t.comment.author,
            "date": t.comment.date, "text": t.comment.text,
            "anchor": t.comment.anchor, "done": t.done,
            "replies": [{"cid": r.cid, "author": r.author, "text": r.text}
                        for r in t.replies],
        } for t in found]
        Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.check and open_threads:
        print(f"CHECK FAILED: {len(open_threads)} open comment thread(s) - "
              f"a submission should carry none")
        return 1
    return 0


def cmd_count(args: argparse.Namespace) -> int:
    """Bucketed word count — the number a journal cap is phrased in."""
    from .package import read_parts
    from .wordcount import count
    counts = count(read_parts(args.docx), view=args.tracked)
    print(Path(args.docx).name)
    for name, n in counts.as_dict().items():
        print(f"  {name:<11}{n:>8,}")
    print(f"  {'total':<11}{counts.total():>8,}")
    drop = [e.strip() for e in (args.exclude or "").split(",") if e.strip()]
    counted = counts.total(exclude=drop)
    if drop:
        print(f"  {'counted':<11}{counted:>8,}  "
              f"(excluding {', '.join(drop)})")
    # the cap applies to whatever is being counted: the exclusion set if
    # one was given, the full total otherwise
    if args.limit and counted > args.limit:
        print(f"  OVER the {args.limit:,}-word limit by "
              f"{counted - args.limit:,}")
        return 1
    if args.json:
        Path(args.json).write_text(
            json.dumps(counts.as_dict(), indent=2), encoding="utf-8")
    return 0


def cmd_figures(args: argparse.Namespace) -> int:
    """Figures and their alt text; --check gates on missing descriptions."""
    from .figures import alt_texts
    with zipfile.ZipFile(args.docx) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    drawings = alt_texts(doc)
    missing = [d for d in drawings if d.missing]
    print(f"{Path(args.docx).name}  ({len(drawings)} drawing(s), "
          f"{len(missing)} without alt text)")
    for d in drawings:
        mark = " " if not d.missing else "!"
        where = d.caption or "(no caption window)"
        has_alt = (d.descr or "").strip()
        alt = f" alt: {(d.descr or '')[:50]!r}" if has_alt else ""
        print(f"  {mark} {where[:56]}  [{d.name or d.embed or '?'}]{alt}")
    if args.check and missing:
        print(f"CHECK FAILED: {len(missing)} drawing(s) without alt text")
        return 1
    return 0


def cmd_smarten(args: argparse.Namespace) -> int:
    """Straight quotes to typographic ones; dry run unless --write."""
    from .hygiene import smarten
    from .package import read_parts

    parts = read_parts(args.docx)
    doc = parts["word/document.xml"].decode("utf-8")
    fixed, report = smarten(doc)
    print(Path(args.docx).name)
    print("  " + report.format().replace("\n", "\n  "))
    if not args.write:
        print("  (dry run - pass --write to save)")
        return 0
    if fixed == doc:
        print("  nothing to write")
        return 0
    return 0 if _write_document(args.docx, parts, fixed, "pre_smarten") \
        else 1


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
        "refstyle",
        help="citation / reference FORMAT audit (house author-date style)")
    p.add_argument("docx")
    p.add_argument("--chicago", action="store_true",
                   help="AFI's variant: full names, bare year, "
                        "et al. from 4 authors")
    p.add_argument("--json", metavar="PATH")
    p.set_defaults(fn=cmd_refstyle)

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
    p.add_argument("--md", action="store_true",
                   help="structured markdown: headings, pipe tables, "
                        "LaTeX equations, footnotes")
    p.set_defaults(fn=cmd_text)

    p = sub.add_parser(
        "tasks", help="margin comments as a checklist")
    p.add_argument("docx")
    p.add_argument("--all", action="store_true",
                   help="show resolved threads too")
    p.add_argument("--check", action="store_true",
                   help="exit 1 while any thread is open (submission gate)")
    p.add_argument("--done", metavar="ID,ID,...",
                   help="mark these comment ids resolved and save "
                        "(a backup is taken first)")
    p.add_argument("--json", metavar="PATH")
    p.set_defaults(fn=cmd_tasks)

    p = sub.add_parser(
        "count", help="word count by bucket, journal-cap style")
    p.add_argument("docx")
    p.add_argument("--exclude", metavar="A,B,...",
                   help="buckets to leave out of the counted total, e.g. "
                        "references,tables,captions,footnotes,appendix")
    p.add_argument("--limit", type=int, metavar="N",
                   help="with --exclude: exit 1 if the counted total "
                        "exceeds N words")
    p.add_argument("--tracked", choices=("final", "original"),
                   default="final",
                   help="which side of tracked changes to count")
    p.add_argument("--json", metavar="PATH")
    p.set_defaults(fn=cmd_count)

    p = sub.add_parser("lint",
                       help="structural checks (no Word needed)")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser(
        "figures", help="figures and their alt text")
    p.add_argument("docx")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if any drawing lacks alt text")
    p.set_defaults(fn=cmd_figures)

    p = sub.add_parser(
        "smarten", help="straight quotes -> typographic, the safe cases")
    p.add_argument("docx")
    p.add_argument("--write", action="store_true",
                   help="save the result; without it this is a dry run")
    p.set_defaults(fn=cmd_smarten)

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
