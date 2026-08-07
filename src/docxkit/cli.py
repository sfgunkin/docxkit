r"""``docxkit`` command line — the one-off jobs, without a throwaway script.

    docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json R.json]
    docxkit citations PAPER.docx
    docxkit refstyle PAPER.docx [--chicago] [--json R.json]
    docxkit crossrefs PAPER.docx [--write] [--audit]
    docxkit authors PAPER.docx [--set NAME] [--only A,B] [--write]
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

and the single-file revision protocol, which finds its own paths in
``revision/paper.toml`` and so takes almost no arguments::

    docxkit revision status
    docxkit revision ingest [--json R.json]
    docxkit revision build REVISED.docx [--out PATH]
    docxkit revision validate [BATCH.docx] [--no-word]
    docxkit revision promote [BATCH.docx]
    docxkit revision baseline [--force]
    docxkit revision rescues [--prune KEEP]
    docxkit revision init PAPER.docx [--root DIR] [--name NAME]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, is_dataclass
from pathlib import Path

from ._xml import BOOKMARK_END_ID_RE, BOOKMARK_START_ID_RE, COMMENT_ID_RE
from .console import utf8_console
from .errors import DocxKitError, ProtocolError
from .find import P_RE, text_of


def _json_default(value: object) -> object:
    """Last-resort encoder, so a finished comparison is never lost.

    The reports here sort their sets before storing them, but the cost
    of one that does not is losing the whole run at the final step —
    the comparison already done, the report never written. In CI that
    is the worst possible moment to fail.
    """
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _write_json(path: str, payload: object) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2,
                   default=_json_default),
        encoding="utf-8")


def cmd_compare(args: argparse.Namespace) -> int:
    from .compare import compare, render
    rep = compare(args.built, args.edited)
    if args.json:
        _write_json(args.json, rep)
    # compare is a verbatim port and untyped; render returns the exit code
    return int(render(rep, args.expect_clean))


def cmd_citations(args: argparse.Namespace) -> int:
    from .citations import check_citations
    return 1 if check_citations(args.docx) > 0 else 0


def _aliases(args: argparse.Namespace) -> dict[str, str]:
    """--alias CITED=FILED, for every command that cross-checks the two sides.

    `link` took it and `refstyle` did not, so the same document that linked
    cleanly was audited as citing three works it has no entries for, and
    listing three entries nothing cites.
    """
    pairs = getattr(args, "alias", None) or []
    return dict(kv.split("=", 1) for kv in pairs)


def cmd_link(args: argparse.Namespace) -> int:
    """Build the bidirectional citation-link apparatus document-wide.

    Dry by default: reports what it WOULD do. ``--write`` applies, with
    a numbered backup beside the manuscript.
    """
    from .citations import link_all
    from .lint import lint_parts
    from .package import backup, read_parts, write_docx
    parts = read_parts(args.docx)
    report = link_all(parts, aliases=_aliases(args))
    print(report.format())
    if not args.write:
        print("(dry run — nothing written; pass --write to apply)")
        return 0
    # Link surgery splices hyperlink and bookmark elements across runs,
    # which is precisely the class that has produced an unopenable file
    # here before — and lint is the only gate that catches it offline.
    # Every other mutating command goes through _write_document, which
    # lints; this one used to write straight through edit_in_place.
    if problems := lint_parts(parts):
        for problem in problems:
            print(f"  - {problem}")
        print("REFUSED: the package would not open cleanly in Word; "
              "nothing was written")
        return 1
    print(backup(args.docx, "pre_link"))
    write_docx(args.docx, parts)
    return 0


def cmd_linkfix(args: argparse.Namespace) -> int:
    """The audit's findings classified into proposed repairs — a plan
    for a human to review, never an edit."""
    from .citations import repair_plan
    from .package import read_parts
    print(repair_plan(read_parts(args.docx)))
    return 0


def cmd_refstyle(args: argparse.Namespace) -> int:
    """Citation and reference FORMAT, against the house author-date style.

    ``citations`` audits the links; this audits the writing — initials,
    "and" not "&", "(2020).", en-dashes, alphabetical order, and the
    cited/listed cross-check.
    """
    from .package import read_parts
    from .refstyle import CHICAGO, HOUSE, audit
    report = audit(read_parts(args.docx),
                   CHICAGO if args.chicago else HOUSE,
                   aliases=_aliases(args))
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
    # every other bookmarked part: a footnote-only citation keeps its
    # in-text bookmark there while the body links to it — and a new
    # bookmark id minted from the body ALONE can collide with one
    # already living there, which Word opens with a repair warning.
    # link() takes these for exactly that reason; this path used to
    # pass them only to audit().
    others = [v.decode("utf-8") for k, v in parts.items()
              if k in ("word/footnotes.xml", "word/endnotes.xml")]

    if args.audit:
        state = crossrefs.audit(doc, also=others)
        print(name)
        for key in ("linked", "caption_only", "mention_only", "dangling"):
            found = state[key]
            print(f"  {key:<13} {len(found):>3}"
                  f"{'  ' + ', '.join(found) if found else ''}")
        return 1 if state["dangling"] else 0

    linked, report = crossrefs.link(doc, other_parts=others)
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
    starts = BOOKMARK_START_ID_RE.findall(doc)
    ends = BOOKMARK_END_ID_RE.findall(doc)
    # \b, not ">": an oMath can carry attributes, and the bare-tag form
    # undercounted AFI v13 by two
    omath = len(re.findall(r"<m:oMath[ >]", doc))
    n_com = len(COMMENT_ID_RE.findall(com))
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


def cmd_math(args: argparse.Namespace) -> int:
    """Symbols and expressions typeset as prose instead of as OMML."""
    from .equations import document_symbols, prose_math
    from .package import read_parts
    doc = read_parts(args.docx)["word/document.xml"].decode("utf-8")
    findings = prose_math(doc)
    vocabulary = "".join(sorted(document_symbols(doc)))
    print(f"{Path(args.docx).name}  (math vocabulary: "
          f"{vocabulary or 'none — the document typesets no symbols'})")
    if not findings:
        print("  clean — every symbol in the text is OMML")
        return 0
    order = ["split expression", "typed script", "symbol", "interval"]
    for kind in order:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        print(f"\n{kind.upper()} ({len(group)})")
        for f in group:
            print(f"  ¶{f.para:<5} {f.symbol!r}")
            print(f"        …{f.context}…")
    print(f"\n{len(findings)} finding(s). Advisory: the house rule is that "
          "a symbol belongs in an\nequation, but only a person can tell a "
          "model parameter from a label.")
    return 1 if args.check else 0


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


def cmd_authors(args: argparse.Namespace) -> int:
    """Who the document credits; ``--set`` restamps every one of them."""
    from .authors import read_authors, set_author
    from .lint import lint_parts
    from .package import read_parts

    parts = read_parts(args.docx)
    print(Path(args.docx).name)
    for who, n in read_authors(parts).most_common():
        print(f"  {n:5}  {who}")
    if not read_authors(parts):
        print("  (no tracked changes or comments)")
    if not args.set:
        return 0

    only = set(args.only.split(",")) if args.only else None
    report = set_author(parts, args.set, initials=args.initials, only=only)
    print(f"  -> {args.set}: {report.revisions} change(s), "
          f"{report.comments} comment initial(s), "
          f"{report.properties} document propert(ies), "
          f"{report.people} people entr(ies)")
    if not args.write:
        print("  (dry run - pass --write to save)")
        return 0
    if problems := lint_parts(parts):
        for problem in problems:
            print(f"  - {problem}")
        return 1
    kept = _write_back(args.docx, parts, "pre_authors")
    print(f"  written; previous version kept at {kept}")
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


# --- the single-file revision protocol -------------------------------
#
# These read revision/paper.toml and take no paths, on purpose. Every
# path the protocol needs is derivable from it, and the alternative —
# passing filenames on each call — is exactly how one paper ended up
# with twenty scripts pinned to a manuscript two generations stale.

def _paper(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    from .revision import load_paper
    return load_paper(getattr(args, "paper", None))


def _show_state(label: str, st: object) -> None:
    from .revision import State
    assert isinstance(st, State)
    print(f"  {label:<9} {st.pending} pending -> {st.label.upper()}")
    for part, count in st.by_part.items():
        where = part.split("/")[-1].replace(".xml", "")
        note = "" if where == "document" else \
            "   <- Review>Next SKIPS these, and Simple Markup hides them"
        print(f"      {count:>4} in {where}{note}")
    if st.by_author:
        who = ", ".join(f"{a} ({n})" for a, n in st.by_author.items())
        print(f"      by: {who}")


def cmd_revision_status(args: argparse.Namespace) -> int:
    """Truth or proposal? The one question the layout answers by itself."""
    from .revision import state
    paper = _paper(args)
    print(f"{paper.name}\n  {paper.working}")
    st = state(paper.working)
    _show_state("working", st)
    if paper.prev.exists():
        _show_state("prev", state(paper.prev))
    else:
        print("  prev      MISSING - no baseline to compare or reject "
              "against; run `docxkit revision baseline`")
    return 0 if st.is_truth else 1


def cmd_revision_ingest(args: argparse.Namespace) -> int:
    """What did the author change while I was away? (read-only)"""
    from .revision import ingest
    paper = _paper(args)
    report = ingest(paper.working, paper.prev)
    print(f"{paper.name}: {paper.prev.name} -> {paper.working.name}")

    print("\n== content ==")
    for bucket, items in report.content.items():
        if not items:
            continue
        print(f"-- {bucket} ({len(items)})")
        for item in items[:12]:
            print("   ", str(item)[:200])
        if len(items) > 12:
            print(f"    ... and {len(items) - 12} more")
    if report.untouched:
        print("   no differences - working.docx is still the baseline")

    print("\n== package ==")
    if report.added:
        print("   added  :", report.added)
    if report.removed:
        print("   removed:", report.removed)
    print("   changed:", report.changed_parts or "(only save-noise)")
    if report.resaved:
        print(f"   re-saved, meaning unchanged: {report.resaved} part(s)")
    if report.style_edit:
        print("   ** a STYLE-level edit, not just content **")

    print("\n== state ==")
    _show_state("working", report.working_state)
    _show_state("prev", report.prev_state)
    if report.working_state.is_truth and not report.untouched:
        print("\n   The author has accepted everything. Record it as the "
              "new truth:\n     docxkit revision baseline")
    if args.json:
        _write_json(args.json, {
            "content": report.content,
            "changed_parts": report.changed_parts,
            "working_pending": report.working_state.pending,
        })
    return 0


def cmd_revision_build(args: argparse.Namespace) -> int:
    """Clean edit -> redline, via Word Compare."""
    from .revision import build
    paper = _paper(args)
    report = build(paper, args.revised, args.out,
                   allow_math_resolve=args.allow_math_resolve,
                   allow_pending_baseline=args.allow_pending_baseline,
                   progress=lambda line: print("   ", line))
    out = Path(args.out) if args.out else paper.batch
    print(f"\nbuilt {out} ({report.revisions} revisions)")
    print(f"\nNow run:  docxkit revision validate {out}")
    return 0


def cmd_revision_validate(args: argparse.Namespace) -> int:
    """The gate ladder. Gate 5 is the one that proves reviewability."""
    from .revision import validate
    paper = _paper(args)
    target = Path(args.batch) if args.batch else paper.batch
    base = Path(args.baseline) if args.baseline else paper.prev
    report = validate(target, base if base.exists() else None,
                      use_word=not args.no_word)

    print(f"{target.name}")
    print("== lint ==", "clean" if not report.lint
          else f"{len(report.lint)} problem(s)")
    for problem in report.lint:
        print("   FAIL:", problem)
    if report.lint:
        print("\nABORT before Word - fix lint first.")
        return 2
    print("== counts ==", report.counts)
    if report.word_opened is False:
        print("== Word ==  FAILED (corrupted):", report.word_error)
        return 3
    if report.word_opened:
        print(f"== Word ==  opened, {report.word_revisions} revision groups")
    print("== accept-all ==", report.accepted)
    if report.empty_shells:
        print("   ** WARNING: empty OMML shells after accept **")
    if report.reject_matches_baseline is not None:
        verdict = "OK" if report.reject_matches_baseline else "MISMATCH"
        print(f"== reject-all == baseline ?  {report.reject_detail} "
              f"-> {verdict}")
        if not report.reject_matches_baseline:
            print("   the batch is NOT fully reviewable: rejecting "
                  "everything does not restore the baseline")
    if report.accept_paths_agree is not None:
        print("== XML accept == Word accept ?",
              "OK" if report.accept_paths_agree else "MISMATCH")
    if paper.gates:
        print("\nThe paper's own gates (run these too):")
        for gate in paper.gates:
            print("   ", gate)
    print("\nVERDICT:", "PASS" if report.ok else "FAIL")
    return 0 if report.ok else 1


def cmd_revision_promote(args: argparse.Namespace) -> int:
    """Put a validated batch onto working.docx, lock- and hash-guarded."""
    from .revision import promote
    paper = _paper(args)
    report = promote(paper, args.batch, args.base)
    print(f"promoted {report.promoted.name} -> {report.onto.name}")
    print(f"rescue copy of the previous live file: "
          f"{report.rescue.relative_to(paper.root)}")
    if report.pruned:
        print(f"pruned {len(report.pruned)} older rescue(s), keeping "
              f"{paper.rescue_keep}")
    print("\nworking.docx is now a PROPOSAL. The author adjudicates it in "
          "Word;\nthis tool never accepts on their behalf.")
    return 0


def cmd_revision_rescues(args: argparse.Namespace) -> int:
    """List the undo copies, and optionally thin them."""
    from .revision import prune_rescues, rescues
    paper = _paper(args)
    if args.prune is not None:
        gone = prune_rescues(paper, args.prune)
        for path in gone:
            print(f"  removed {path.name}")
        print(f"pruned {len(gone)}, keeping {max(0, args.prune)}")
        return 0
    found = rescues(paper)
    if not found:
        print(f"no rescue copies in {paper.rescue_dir}")
        return 0
    print(f"{paper.rescue_dir}  (keeping {paper.rescue_keep})")
    for path in found:
        print(f"  {path.name:<44} {path.stat().st_size:>9,} bytes")
    return 0


def cmd_revision_baseline(args: argparse.Namespace) -> int:
    """The author accepted: record working.docx as the new truth."""
    from .revision import baseline
    paper = _paper(args)
    written = baseline(paper, force=args.force)
    print(f"baseline updated: {written}")
    return 0


def cmd_revision_init(args: argparse.Namespace) -> int:
    """Scaffold the layout around a manuscript that has not migrated."""
    from .revision import init
    paper = init(args.root or Path(args.source).resolve().parent,
                 args.source, name=args.name or "", author=args.author,
                 language=args.language, attic=args.attic, force=args.force)
    print(f"scaffolded {paper.config.parent}")
    print(f"  working.docx  <- {Path(args.source).name}")
    print("  build/prev.docx (baseline, same bytes)")
    print("\nNothing was moved or deleted. Retire the old filename only "
          "after\nthe paper's own gates pass against working.docx.")
    return 0


def main() -> None:
    utf8_console()
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
        "link",
        help="build citation<->entry links document-wide (dry by default)")
    p.add_argument("docx")
    p.add_argument("--write", action="store_true")
    p.add_argument("--alias", action="append", metavar="CITED=FILED",
                   help='e.g. --alias "WHO=World Health Organization"')
    p.set_defaults(fn=cmd_link)

    p = sub.add_parser(
        "linkfix",
        help="classify link-audit findings into a proposed repair plan")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_linkfix)

    p = sub.add_parser(
        "refstyle",
        help="citation / reference FORMAT audit (house author-date style)")
    p.add_argument("docx")
    p.add_argument("--chicago", action="store_true",
                   help="AFI's variant: full names, bare year, "
                        "et al. from 4 authors")
    p.add_argument("--json", metavar="PATH")
    p.add_argument("--alias", action="append", metavar="CITED=FILED",
                   help='e.g. --alias "WHO=World Health Organization" — '
                        "without it the acronym in the prose and the full "
                        "name in the list read as two different works")
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
        "math", help="symbols typeset as prose instead of OMML")
    p.add_argument("docx")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if anything is found")
    p.set_defaults(fn=cmd_math)

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

    p = sub.add_parser(
        "authors",
        help="who is credited with the changes; --set restamps them")
    p.add_argument("docx")
    p.add_argument("--set", metavar="NAME",
                   help='credit every change and comment to NAME')
    p.add_argument("--initials", metavar="XX",
                   help="comment initials; derived from the name by default")
    p.add_argument("--only", metavar="A,B",
                   help="restamp only these existing authors, leaving a "
                        "real co-author's edits credited to them")
    p.add_argument("--write", action="store_true",
                   help="save the result; without it this is a dry run")
    p.set_defaults(fn=cmd_authors)

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

    p = sub.add_parser(
        "revision",
        help="the single-file protocol: one working.docx, two states")
    rev = p.add_subparsers(dest="rcmd", required=True)

    def _rev(name: str, fn: object, help_: str) -> argparse.ArgumentParser:
        r = rev.add_parser(name, help=help_)
        # every one of these finds its own paths in revision/paper.toml;
        # --paper is only for driving a paper from outside its tree
        r.add_argument("--paper", metavar="DIR",
                       help="the project root (default: search upwards "
                            "from the working directory)")
        r.set_defaults(fn=fn)
        return r

    _rev("status", cmd_revision_status,
         "truth or proposal? (exit 1 while a proposal is pending)")

    r = _rev("ingest", cmd_revision_ingest,
             "what the author changed since the last truth (read-only)")
    r.add_argument("--json", metavar="PATH")

    r = _rev("build", cmd_revision_build,
             "clean edit -> redline, via Word Compare")
    r.add_argument("revised", help="the edited CLEAN copy of prev.docx")
    r.add_argument("--out", metavar="PATH",
                   help="default: revision/build/batch.docx")
    r.add_argument("--allow-math-resolve", action="store_true",
                   help="ship equations Word baked in unreviewable "
                        "(they almost never are meant to be)")
    r.add_argument("--allow-pending-baseline", action="store_true",
                   help="absorb the baseline's pending revisions "
                        "deliberately")

    r = _rev("validate", cmd_revision_validate, "run the gate ladder")
    r.add_argument("batch", nargs="?",
                   help="default: revision/build/batch.docx")
    r.add_argument("--baseline", metavar="PATH",
                   help="default: revision/build/prev.docx")
    r.add_argument("--no-word", action="store_true",
                   help="offline gates only; skips the two that need Word")

    r = _rev("promote", cmd_revision_promote,
             "put a validated batch onto working.docx")
    r.add_argument("batch", nargs="?")
    r.add_argument("--base", metavar="PATH",
                   help="the baseline the batch was built on")

    r = _rev("baseline", cmd_revision_baseline,
             "the author accepted: record working.docx as the new truth")
    r.add_argument("--force", action="store_true",
                   help="adopt a file that still carries revisions "
                        "(migration only)")

    r = _rev("rescues", cmd_revision_rescues,
             "the undo copies promote leaves in build/rescue/")
    r.add_argument("--prune", type=int, metavar="KEEP", nargs="?", const=0,
                   help="delete all but the newest KEEP (default 0: all)")

    r = rev.add_parser("init",
                       help="scaffold the layout around a manuscript")
    r.add_argument("source", help="the paper as it stands today")
    r.add_argument("--root", metavar="DIR",
                   help="project root (default: the manuscript's folder)")
    r.add_argument("--name", metavar="NAME")
    r.add_argument("--author", default="Revision", metavar="NAME",
                   help="who tracked changes are credited to")
    r.add_argument("--language", default="en", metavar="XX")
    r.add_argument("--attic", metavar="PATH",
                   help="where retired snapshots go")
    r.add_argument("--force", action="store_true",
                   help="rewrite an existing configuration")
    r.set_defaults(fn=cmd_revision_init)

    args = ap.parse_args()
    try:
        sys.exit(args.fn(args))
    except ProtocolError as exc:
        # a distinct code per refusal, so a caller can tell WHICH one it
        # hit without parsing English
        print(f"docxkit: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except DocxKitError as exc:
        sys.exit(f"docxkit: {exc}")


if __name__ == "__main__":
    main()
