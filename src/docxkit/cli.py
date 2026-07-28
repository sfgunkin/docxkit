r"""``docxkit`` command line — the one-off jobs, without a throwaway script.

    docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json R.json]
    docxkit citations PAPER.docx
    docxkit inspect PAPER.docx [--comments] [--revisions]
    docxkit text PAPER.docx [--tracked final|original]
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

from .find import P_RE, text_of


def _print_utf8() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def cmd_compare(args) -> int:
    from .compare import compare, render
    rep = compare(args.built, args.edited)
    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return render(rep, args.expect_clean)


def cmd_citations(args) -> int:
    from .citations import check_citations
    return 1 if check_citations(args.docx) > 0 else 0


def cmd_inspect(args) -> int:
    with zipfile.ZipFile(args.docx) as z:
        names = z.namelist()
        doc = z.read("word/document.xml").decode("utf-8")
        com = (z.read("word/comments.xml").decode("utf-8")
               if "word/comments.xml" in names else "")
    ins = len(re.findall(r"<w:ins ", doc))
    dele = len(re.findall(r"<w:del ", doc))
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
        from .comments import revision_spans
        from .find import delta_text_of
        for s, e in revision_spans(doc)[:200]:
            kind = "ins" if doc[s:s + 6] == "<w:ins" else "del"
            print(f"    [{kind}] {delta_text_of(doc[s:e])[:100]!r}")
    return 0


_INS_RE = re.compile(r"<w:ins\b[^>]*?>.*?</w:ins>", re.DOTALL)
_DEL_RE = re.compile(r"<w:del\b[^>]*?>.*?</w:del>", re.DOTALL)
_DELTEXT_RE = re.compile(r"<w:delText([^>]*)>")


def cmd_text(args) -> int:
    """Dump visible text, choosing a side of any tracked changes.

    `final` accepts the revisions (drop deletions), `original` rejects them
    (drop insertions, restore deleted text) -- python-docx can do neither,
    since it never sees runs nested inside w:ins.
    """
    with zipfile.ZipFile(args.docx) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    for m in P_RE.finditer(doc):
        para = m.group(0)
        if args.tracked == "final":
            para = _DEL_RE.sub("", para)
        else:
            para = _INS_RE.sub("", para)
            para = _DELTEXT_RE.sub(r"<w:t\1>", para).replace("</w:delText>",
                                                             "</w:t>")
        if (t := text_of(para)).strip():
            print(t)
    return 0


def cmd_pdf(args) -> int:
    from .word import export_pdf
    first = last = None
    if args.pages:
        a, _, b = args.pages.partition("-")
        first, last = int(a), int(b or a)
    out = export_pdf(args.docx, args.out, first=first, last=last)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_pages(args) -> int:
    from .word import page_count
    print(page_count(args.docx))
    return 0


def main() -> None:
    _print_utf8()
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

    p = sub.add_parser("inspect", help="structural summary")
    p.add_argument("docx")
    p.add_argument("--comments", action="store_true")
    p.add_argument("--revisions", action="store_true")
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("text", help="dump the visible text")
    p.add_argument("docx")
    p.add_argument("--tracked", choices=("final", "original"),
                   default="final",
                   help="which side of tracked changes to show")
    p.set_defaults(fn=cmd_text)

    p = sub.add_parser("pdf", help="render to PDF via Word")
    p.add_argument("docx")
    p.add_argument("out")
    p.add_argument("--pages", metavar="A-B")
    p.set_defaults(fn=cmd_pdf)

    p = sub.add_parser("pages", help="laid-out page count (needs Word)")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_pages)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
