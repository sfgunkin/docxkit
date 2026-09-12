r"""``docxkit`` command line — the one-off jobs, without a throwaway script.

    docxkit compare BUILT.docx EDITED.docx [--expect-clean] [--json R.json]
    docxkit citations PAPER.docx
    docxkit link PAPER.docx [--write] [--only NAME,...] [--alias "A=B"]
    docxkit linkfix PAPER.docx
    docxkit refstyle PAPER.docx [--chicago] [--json R.json]
    docxkit crossrefs PAPER.docx [--write] [--audit]
    docxkit authors PAPER.docx [--set NAME] [--only A,B] [--write]
    docxkit inspect PAPER.docx [--comments] [--revisions]
    docxkit locate PAPER.docx ANCHOR... | --revisions
    docxkit api [TOPIC] [--signatures]   # the public surface by subject
    docxkit sites PAPER.docx "sig" [--part body|footnotes]
    docxkit text PAPER.docx [--tracked final|original] [--md]
    docxkit count PAPER.docx [--exclude references,tables] [--limit N]
    docxkit tasks PAPER.docx [--all] [--check] [--done ID,ID]
    docxkit figures PAPER.docx [--check]
    docxkit footnotes PAPER.docx [--check]
    docxkit smarten PAPER.docx [--write]
    docxkit lint PAPER.docx
    docxkit probe PAPER.docx [ANCHOR...]
    docxkit math PAPER.docx [--check]
    docxkit verify PAPER.docx
    docxkit pdf PAPER.docx OUT.pdf [--pages 1-3]
    docxkit fit PAPER.docx [--render] [--check]
    docxkit repack PAPER.docx [--threshold 0.6] [--max-drift 1]
    docxkit sections PAPER.docx
    docxkit pages PAPER.docx [--sheets] [--check] [--expect-sheets N]

and the single-file revision protocol, which finds its own paths in
``revision/paper.toml`` and so takes almost no arguments::

    docxkit revision status [--all] [--scan FOLDER]
    docxkit revision doctor
    docxkit revision ingest [--check] [--json R.json]
    docxkit revision build REVISED.docx [--out PATH] [--keep-math] [--no-moves]
    docxkit revision validate [BATCH.docx] [--no-word] [--render ANCHOR...]
    docxkit revision ship REVISED.docx   # both, one Word session
    docxkit revision promote [BATCH.docx]
    docxkit revision baseline [--force] [--accept-loss A,... ]...
    docxkit revision rescues [--prune KEEP]
    docxkit revision redlines
    docxkit revision init PAPER.docx [--root DIR] [--name NAME] [--working P]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path

from ._xml import (
    BOOKMARK_END_ID_RE,
    BOOKMARK_START_ID_RE,
    COMMENT_ID_RE,
    COMMENTS,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
)
from .console import utf8_console
from .errors import (
    DocxKitError,
    HandbackLoss,
    PackageError,
    ProtocolError,
)
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


# --- argument types -------------------------------------------------
#
# Checked HERE rather than in the command, because argparse turns an
# ArgumentTypeError into "docxkit pdf: error: argument --pages: ..." and
# exit 2, where the command turned the same mistake into a traceback with
# the user's typo nowhere in it.

def _page_range(text: str) -> tuple[int, int]:
    """``A`` or ``A-B`` — one-based, inclusive, and ordered."""
    a, sep, b = text.partition("-")
    if sep and not b.strip():
        raise argparse.ArgumentTypeError(
            f"{text!r}: a range needs a last page, e.g. 1-3 (there is no "
            f"'to the end' form; pass the page count)")
    try:
        first = int(a)
        last = int(b) if sep else first
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r}: expected a page or a range, e.g. 3 or 1-3") from None
    if first < 1:
        raise argparse.ArgumentTypeError(
            f"{text!r}: pages are numbered from 1")
    if last < first:
        raise argparse.ArgumentTypeError(
            f"{text!r}: the range ends before it begins")
    return first, last


def _word_limit(text: str) -> int:
    """A journal's word cap: a whole, non-negative number."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r}: expected a number of words") from None
    if n < 0:
        raise argparse.ArgumentTypeError(
            f"{text}: a word limit cannot be negative")
    return n


def cmd_compare(args: argparse.Namespace) -> int:
    from .compare import compare_docs, load_parts, render
    # Both sides checked FIRST. `compare.load` reads only the text parts
    # it knows, so two files that are not manuscripts compared as two
    # empty documents and reported no differences — and `--expect-clean`
    # in CI passed on them. A gate that cannot fail on garbage input is
    # not a gate.
    #
    # And each side is read ONCE, through the read-only path: `load`
    # opened the zip again itself, so a comparison against the file the
    # author has open in Word refused — the one moment an author round
    # is adjudicated. `load_parts` takes the package this already holds
    # and is given the real path, so the report names the manuscript
    # rather than the temporary copy it may have been read from.
    sides = [load_parts(_package(side, read_only=True), side)
             for side in (args.built, args.edited)]
    rep = compare_docs(*sides)
    if args.json:
        _write_json(args.json, rep)
    # compare is a verbatim port and untyped; render returns the exit code
    return int(render(rep, args.expect_clean))


def cmd_citations(args: argparse.Namespace) -> int:
    from .citations import check_citations
    # The parts are PASSED on, not just validated: read twice, the
    # second read was of the live path and refused the moment Word held
    # it — under the snapshot banner the first read had already printed.
    parts = _package(args.docx, read_only=True)
    found = check_citations(args.docx, parts=parts,
                            later_mentions=args.later_mentions,
                            ignore=_ignore(args))
    return 1 if found > 0 else 0


def _aliases(args: argparse.Namespace) -> dict[str, str]:
    """--alias CITED=FILED, for every command that cross-checks the two sides.

    `link` took it and `refstyle` did not, so the same document that linked
    cleanly was audited as citing three works it has no entries for, and
    listing three entries nothing cites.

    Each entry is checked: `--alias WHO` (no ``=``) used to reach `dict()`
    as a one-element sequence and come back as a bare ValueError
    traceback, and `--alias WHO=` mapped the acronym to nothing at all,
    which reads in the audit as an entry no one cites.
    """
    pairs = getattr(args, "alias", None) or []
    out: dict[str, str] = {}
    for kv in pairs:
        cited, sep, filed = kv.partition("=")
        cited, filed = cited.strip(), filed.strip()
        if not sep or not cited or not filed:
            raise DocxKitError(
                f"--alias {kv!r}: expected CITED=FILED, as in "
                f'--alias "WHO=World Health Organization"')
        # A repeat that AGREES is harmless (two commands sharing a script);
        # one that disagrees is a mistake with a silent winner.
        if out.get(cited, filed) != filed:
            raise DocxKitError(
                f"--alias {cited!r} given twice, as {out[cited]!r} and "
                f"{filed!r}: pick one")
        out[cited] = filed
    return out


def cmd_link(args: argparse.Namespace) -> int:
    """Build the bidirectional citation-link apparatus document-wide.

    Dry by default: reports what it WOULD do. ``--write`` applies, with
    a numbered backup beside the manuscript.
    """
    from .citations import link_all
    # `read_only` follows the FLAG, as it does in `authors` and `tasks`:
    # the dry run is a report and answers from a snapshot, and only the
    # writing form needs the file to itself. It was an unconditional
    # read, so `link` on a manuscript the author had open refused to say
    # what it WOULD do — the `citations` defect of 2026-08-23, in the
    # command citations sends people to next.
    parts = _package(args.docx, read_only=not args.write)
    # --only scopes a REPAIR. Turned loose on a whole manuscript this
    # builder took one paper's audit from 26 findings to 56, so "wire
    # these six" has to be sayable.
    only = [t.strip() for t in (args.only or "").split(",") if t.strip()]
    report = link_all(parts, aliases=_aliases(args), only=only or None)
    print(report.format())
    if not args.write:
        print("(dry run — nothing written; pass --write to apply)")
        return 0
    # Link surgery splices hyperlink and bookmark elements across runs,
    # which is precisely the class that has produced an unopenable file
    # here before — and lint is the only gate that catches it offline.
    return 0 if _save(args.docx, parts, "pre_link") else 1


def cmd_linkfix(args: argparse.Namespace) -> int:
    """The audit's findings classified into proposed repairs — a plan
    for a human to review, never an edit."""
    from .citations import repair_plan
    # "never an edit" — so there is no invocation of this that needs the
    # file to itself, and it read it as though there were.
    print(repair_plan(_package(args.docx, read_only=True)))
    return 0


def cmd_refstyle(args: argparse.Namespace) -> int:
    """Citation and reference FORMAT, against the house author-date style.

    ``citations`` audits the links; this audits the writing — initials,
    "and" not "&", "(2020).", en-dashes, alphabetical order, and the
    cited/listed cross-check.
    """
    from .refstyle import CHICAGO, HOUSE, audit, convert, layout, refile
    style = CHICAGO if args.chicago else HOUSE
    parts = _package(args.docx, read_only=not getattr(args, "fix", False))
    print(Path(args.docx).name)
    if args.fix:
        # BEFORE the audit, so what is printed is what is LEFT
        # rather than what was there: a report of findings this
        # command has just repaired reads as a failed run.
        #
        # Text, then order, then layout — each one reads the list the
        # one before it left, and only the last two move paragraphs.
        written = convert(parts, style)
        print("  " + written.format().replace("\n", "\n  "))
        filed = refile(parts)
        print("  " + filed.format().replace("\n", "\n  "))
        set_out = layout(parts)
        print("  " + set_out.format().replace("\n", "\n  "))
        if ((written or filed or set_out)
                and not _save(args.docx, parts, "pre_refstyle")):
            return 1
    report = audit(parts, style, aliases=_aliases(args),
                   ignore=_ignore(args))
    print("  " + report.format().replace("\n", "\n  "))
    if args.json:
        _write_json(args.json, report.as_rows())
    return 1 if report.issues else 0


def _ignore(args: argparse.Namespace) -> frozenset[str]:
    """`IGNORED_LEADS` plus the words THIS paper's prose puts before "and".

    The grammar reads "<Capitalised noun> and <Source> (Year)" as a
    two-author citation, and in an UNLINKED manuscript there is no fact
    to settle it with: *"consolidated from standardized national Labor
    Force Surveys and ILOSTAT (2024) data"* is reported as a citation of
    "Surveys and ILOSTAT", against a list that holds ILOSTAT — a
    `missing-ref` a reader acts on by hunting for a reference that is
    already there, and one the paper cannot clear (Aging_Well,
    2026-08-21).

    A LINKED manuscript settles it from its own apparatus: a link to an
    entry is the document saying what it means, and `_trust_the_links`
    re-reads the span at the label's offsets. An unlinked one has to be
    told, and that is the right side of the seam — which words a paper's
    prose puts before "and" is the paper's vocabulary, not the engine's.
    The other answer is to run `docxkit link --write` first.
    """
    from .citations import IGNORED_LEADS
    extra = {w.strip() for w in (getattr(args, "ignore", "") or "").split(",")
             if w.strip()}
    return frozenset(IGNORED_LEADS | extra)


def cmd_crossrefs(args: argparse.Namespace) -> int:
    """Link every figure and table to its first mention, and back."""
    from . import crossrefs

    parts = _package(args.docx,
                      read_only=getattr(args, "audit", False)
                      or not getattr(args, "write", False))
    doc = parts[DOCUMENT].decode("utf-8")
    name = Path(args.docx).name
    # every other bookmarked part: a footnote-only citation keeps its
    # in-text bookmark there while the body links to it — and a new
    # bookmark id minted from the body ALONE can collide with one
    # already living there, which Word opens with a repair warning.
    # link() takes these for exactly that reason; this path used to
    # pass them only to audit().
    others = [v.decode("utf-8") for k, v in parts.items()
              if k in (FOOTNOTES, ENDNOTES)]
    # The labels a paper's own exhibits carry. `crossrefs.link` has taken
    # them since it was written — Aging_Well's fifth exhibit is a BOX,
    # and the caption grammar fits it — but the command baked
    # DEFAULT_LABELS in, so the paper needed a script to pass a tuple.
    labels = tuple(w.strip() for w in (args.labels or "").split(",")
                   if w.strip()) or crossrefs.DEFAULT_LABELS

    if args.audit:
        state = crossrefs.audit(doc, also=others, labels=labels)
        # WHICH labels, always. `--labels` REPLACES the defaults rather
        # than extending them, so a run that examined one exhibit kind
        # of three printed the same shape of clean report as one that
        # examined all three: 4 linked / 0 unlinked and 2 linked / 0
        # unlinked are both "nothing is unlinked" to a reader, and only
        # one of them means it.
        print(f"{name}   labels: {', '.join(labels)}")
        for key in ("linked", "unlinked", "caption_only", "mention_only",
                    "dangling"):
            found = state[key]
            print(f"  {key:<16} {len(found):>3}"
                  f"{'  ' + ', '.join(found) if found else ''}")
        # One finding per line: these carry a sentence, not a name, and
        # `misnamed` was computed and never printed at all — a check
        # nobody can read is a check nobody runs.
        for key in ("misnamed", "misplaced_anchor", "fieldless"):
            print(f"  {key:<16} {len(state[key]):>3}")
            for line in state[key]:
                print(f"    {line}")
        # `fieldless` gates: a caption that types its number in a
        # series that computes them is the defect that printed two
        # "Table 3"s while every other check reported zero.
        return 1 if (state["dangling"] or state["misplaced_anchor"]
                     or state["fieldless"]) else 0

    linked, report = crossrefs.link(doc, other_parts=others, labels=labels)
    print(name)
    print("  " + report.format().replace("\n", "\n  "))

    if not args.write:
        print("  (dry run - pass --write to save)")
        return 0 if report.complete else 1

    if not _write_document(args.docx, parts, linked, "pre_crossrefs"):
        return 1
    return 0 if report.complete else 1


def cmd_sections(args: argparse.Namespace) -> int:
    """The section numbering and every mention of it; exit 1 on a breach."""
    from .sections import audit

    report = audit(_package(args.docx, read_only=True))
    print(Path(args.docx).name)
    print("  " + report.format().replace("\n", "\n  "))
    if not report.ok:
        print("\n  A merged or deleted heading renumbers the sections in the "
              "reader's head and\n  nowhere in the file. Restore the heading, "
              "or renumber the headings AND every\n  mention in one pass: "
              "docxkit.sections.renumber(parts, merged_into={...}).")
    return 0 if report.ok else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    parts = _package(args.docx, read_only=True)
    names = list(parts)
    doc = parts[DOCUMENT].decode("utf-8")
    com = parts.get(COMMENTS, b"").decode("utf-8")
    from .revisions import counts
    from .tables import _table_spans
    ins, dele = counts(doc)
    starts = BOOKMARK_START_ID_RE.findall(doc)
    ends = BOOKMARK_END_ID_RE.findall(doc)
    # \b, not ">": an oMath can carry attributes, and the bare-tag form
    # undercounted AFI v13 by two
    omath = len(re.findall(r"<m:oMath[ >]", doc))
    n_com = len(COMMENT_ID_RE.findall(com))
    # Top-level, and nested said separately: a plain count of the open tag
    # disagreed with `tables.read_all`, which is what a reader goes on to
    # index, and a questionnaire's inner tables made the gap large.
    top = len(_table_spans(doc))
    nested = doc.count("<w:tbl>") - top
    print(f"{Path(args.docx).name}")
    print(f"  parts       {len(names)}")
    print(f"  paragraphs  {len(P_RE.findall(doc))}")
    print(f"  tables      {top}{f'  (+{nested} nested)' if nested else ''}")
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


def _bookmarks_in(path: str) -> frozenset[str]:
    """Every bookmark name in the package, for telling a reader that the
    "phrase" they asked for is one."""
    from ._xml import BOOKMARK_NAME_RE
    from .package import text_parts
    return frozenset(name for _part, xml in text_parts(_package(path))
                     for name in BOOKMARK_NAME_RE.findall(xml))


def cmd_locate(args: argparse.Namespace) -> int:
    """Which page (and line) does this text land on, once Word lays it out?"""
    from .word import WD_STATISTIC_PAGES, open_doc, session

    phrases = list(args.phrase)
    if args.phrases_from:
        phrases += [ln.strip() for ln
                    in Path(args.phrases_from).read_text(
                        encoding="utf-8").splitlines() if ln.strip()]
    if not phrases and not args.revisions:
        print("docxkit locate: give a phrase, --phrases-from or --revisions")
        return 2

    # One session for both the lookups and the page total, so the file is
    # opened once rather than once per question.
    with session() as word, open_doc(word, args.docx) as doc:
        rows, lines, missing = (
            _revision_rows(doc, args.limit) if args.revisions
            else _anchor_rows(doc, phrases, args.ordered))
        pages = int(doc.ComputeStatistics(WD_STATISTIC_PAGES))

    print(f"{Path(args.docx).name}  ({pages} pages)")
    for line in lines:
        print(line)
    # A phrase that is really a BOOKMARK name is the miss worth
    # explaining: this command searches the laid-out words, and
    # `docxkit locate prev.docx cite_kakwani_1977` answered NOT FOUND,
    # confidently, for a bookmark that is in the file (2026-08-21).
    marks = _bookmarks_in(args.docx) if missing else frozenset()
    for phrase in missing:
        print(f"  NOT FOUND  {phrase[:60]!r}"
              + (" — that is a BOOKMARK name, not words on the page; this "
                 "searches the laid-out text (try `docxkit citations` or "
                 "`docxkit probe`)" if phrase in marks else ""))
    if args.json:
        _write_json(args.json, rows)
    return 1 if missing else 0


def cmd_text(args: argparse.Namespace) -> int:
    """Dump visible text from one side of the tracked changes."""
    parts = _package(args.docx, read_only=True)
    if args.md:
        from .export import to_markdown
        print(to_markdown(parts, view=args.tracked), end="")
        return 0
    from .revisions import text
    doc = parts[DOCUMENT].decode("utf-8")
    for line in text(doc, args.tracked):
        print(line)
    return 0


def cmd_sites(args: argparse.Namespace) -> int:
    """Survey the paragraph an edit is about to be written against."""
    from .find import site
    parts = _package(args.docx, read_only=True)
    from ._xml import ENDNOTES, FOOTNOTES
    wanted = {"body": DOCUMENT, "footnotes": FOOTNOTES,
              "endnotes": ENDNOTES}[args.part]
    if wanted not in parts:
        print(f"no {wanted} in this package")
        return 1
    found = site(parts[wanted].decode("utf-8"), args.signature,
                 normalize=args.normalize)
    print(found.format())
    return 0 if found.matches == 1 else 1


def _public_surface() -> list[tuple[str, str, str, str]]:
    """(module, name, signature, first docstring line) for the package.

    Read off `__all__` and the objects themselves, so it cannot go
    stale: a curated index of what exists is a second thing to keep
    right, and the reason this command exists is that the first one was
    not kept right either.
    """
    import importlib
    import inspect
    import pkgutil

    import docxkit

    rows: list[tuple[str, str, str, str]] = []
    for info in pkgutil.iter_modules(docxkit.__path__):
        if info.name.startswith("_") or info.name == "cli":
            continue
        try:
            mod = importlib.import_module(f"docxkit.{info.name}")
        except ImportError:                  # pragma: no cover - optional dep
            continue
        for name in sorted(getattr(mod, "__all__", ())):
            obj = getattr(mod, name, None)
            try:
                sig = str(inspect.signature(obj)) if callable(obj) else ""
            except (TypeError, ValueError):  # pragma: no cover - C callables
                sig = ""
            doc = (getattr(obj, "__doc__", None) or "").strip()
            rows.append((info.name, name, sig,
                         doc.splitlines()[0] if doc else ""))
    return rows


def cmd_api(args: argparse.Namespace) -> int:
    """The public surface, by SUBJECT rather than by task.

    64 scripts across the four papers hand-write `<w:bookmarkStart>`
    while a bookmark API sits in `citations`, filed there because
    citations were what first needed one. A module that cannot be FOUND
    is a module that gets rewritten, and the rewrite is worse: the
    hand-rolled version misses the case the supported path handles.
    """
    if not args.topic:
        # The whole surface is ~200 lines and nobody reads it. What a
        # reader wants with no topic is where to LOOK.
        import importlib
        import pkgutil

        import docxkit
        for info in sorted(pkgutil.iter_modules(docxkit.__path__),
                           key=lambda i: i.name):
            if info.name.startswith("_") or info.name == "cli":
                continue
            doc = (importlib.import_module(
                f"docxkit.{info.name}").__doc__ or "").strip()
            first = doc.splitlines()[0] if doc else ""
            print(f"  {info.name:<12}  {first}")
        print("\n  a topic narrows it: docxkit api bookmark")
        return 0
    rows = _public_surface()
    topic = args.topic.casefold()
    # Every field, and each earns it: the SIGNATURE answers "which of
    # these takes a caption" (`exhibit_block`'s summary does not say the
    # word), and the MODULE name answers `docxkit api tables`, which is
    # what a reader who already knows where to look will type.
    hits = [r for r in rows
            if any(topic in field.casefold() for field in r)]
    if not hits:
        print(f"nothing in the public surface mentions {args.topic!r}. "
              f"`docxkit api` with no topic lists every module.")
        return 1
    width = max(len(name) for _m, name, _s, _d in hits)
    for module in sorted({m for m, _n, _s, _d in hits}):
        print(module)
        for _m, name, sig, doc in [r for r in hits if r[0] == module]:
            print(f"  {name:<{width}}  {doc}" if not args.signatures
                  else f"  {name}{sig}\n      {doc}")
    return 0


_SNAPSHOT_NOTE = (
    "  read from a SNAPSHOT: the author has the file open in Word, so this\n"
    "  describes the moment the copy was taken, not whatever they have "
    "typed since.")


def _package(path: str, *, read_only: bool = False) -> dict[str, bytes]:
    """Every part of a manuscript, or a refusal a reader can act on.

    `read_parts` already turns a missing file or a non-zip into a
    `PackageError` that ``main`` prints as one line — but `inspect`,
    `text` and `figures` opened the zip themselves and handed back a raw
    `BadZipFile` traceback instead. A zip that is not a Word document
    reached even further, dying on a `KeyError` naming a part the user
    never mentioned.

    **`read_only=True` reads a SNAPSHOT when Word holds the file**, and
    says so. The precedent is `revision status` and `ingest`, which
    learned this on 2026-08-21 — and the fix stopped at those two, so
    `citations`, `refstyle`, `crossrefs`, `math --check`,
    `footnotes --check` and `lint` all still exited 1 with "close it and
    retry". The author having the manuscript open is not an edge case,
    it is the NORMAL state during adjudication, which is exactly when
    someone wants to know whether a citation still resolves. A
    `[verify]` list that can only run when nobody is working on the
    paper is a list that gets run less.

    Not the default, and deliberately: a command that goes on to WRITE
    must read the live file, or it would compute its edit from one
    generation and save it over another.

    **The banner is printed LAST, and that order is the rule.** It is a
    promise that a result follows, so a run that cannot produce one must
    not carry it: `citations` printed the lock refusal AND the banner
    (Aging_Well, 2026-08-28) and its output then had the shape of every
    other gate's — a banner and no findings, which is what a clean run
    also looks like. A caller reading the tail of a six-gate sweep could
    not tell "clean" from "did not run" without counting lines. Once
    this returns, the manuscript is in memory and no lock downstream can
    refuse anything; what a command must not do is print the banner and
    then read the PATH again, which is exactly what `citations` did.
    """
    from .package import read_parts, readable
    copied = False
    if read_only:
        with readable(path) as (target, copied):
            parts = read_parts(target)
    else:
        parts = read_parts(path)
    if DOCUMENT not in parts:
        raise PackageError(
            f"{Path(path).name} is a zip, but not a Word document: "
            f"it has no {DOCUMENT}")
    if copied:
        print(_SNAPSHOT_NOTE)
    return parts


def _write_back(path: str, parts: dict[str, bytes], tag: str) -> str:
    """Backup, then save — the one way an in-place command writes.

    Where the backup lands is decided by :func:`_prior_generations`, and
    it is one fix rather than four: `link --write`, `crossrefs --write`,
    `authors --set --write`, `refstyle --fix`, `tasks --done` and
    `smarten --write` all come through here.
    """
    from .package import backup, write_docx
    kept = backup(path, tag=tag, into=_prior_generations(path))
    write_docx(path, parts)
    # Relative to the manuscript, because that is what makes the
    # DIFFERENCE legible: a bare name reads as "beside your file"
    # wherever it actually went.
    return os.path.relpath(kept, Path(path).resolve().parent)


def _prior_generations(path: str) -> Path | None:
    """Where this paper keeps prior generations, or None for beside it.

    Beside the manuscript is right for a file the author keeps in a
    folder of their own. It is wrong in a revision-protocol folder,
    whose first rule is ONE file: `working.docx` never changes name,
    round names live in git tags and `export/`, and `build/rescue/` is
    where earlier generations go. `docxkit smarten working.docx --write`
    dropped `working_pre_smarten1.docx` beside it (Aging_Well,
    2026-08-29) — exactly the second .docx that rule exists to prevent,
    one keystroke from being the file the author opens next. It was
    moved by hand, which is a workaround and not a resolution.

    Resolved from ``paper.toml``, the way `revision status` finds its
    own paths, and only for the file that config NAMES as the working
    manuscript: a build artifact or an export that happens to sit under
    the same project keeps its backup beside itself.
    """
    from .revision import ProtocolError, load_paper
    target = Path(path).resolve()
    try:
        paper = load_paper(target.parent)
    except (ProtocolError, OSError, ValueError):
        return None           # no protocol here, or an unreadable config
    return paper.rescue_dir if paper.working.resolve() == target else None


def _save(path: str, parts: dict[str, bytes], tag: str) -> bool:
    """THE save path: preserve_space, lint, back up, write.

    Every mutating command lands here, because the three that did not
    each guaranteed something different and a document accepted by one
    was refused by another:

    * ``link`` and ``authors`` linted but skipped ``preserve_space``, so
      a PRE-EXISTING fragile edge space — nothing to do with the edit
      being made — failed their lint and blocked the write. That is what
      the step exists to prevent, found by smartening le14, whose
      references carried four;
    * ``tasks --done`` wrote with NEITHER, which is the gap P0-5 closed
      for ``link`` and did not notice here. Lint is the only thing that
      catches spliced markup Word will not open, offline.

    Returns False when the lint refused, in which case nothing was
    written and the previous file stands.
    """
    from .edit import preserve_space
    from .lint import lint_parts
    # Indexed, not `.get`: every command reads its manuscript through
    # `_package`, which refuses a package without this part, so an
    # absent one is a broken caller and should say so rather than
    # silently skip the whitespace pass.
    fixed, protected = preserve_space(parts[DOCUMENT].decode("utf-8"))
    if protected:
        print(f"  protected {protected} edge-whitespace run(s) "
              f"(preserve_space)")
    parts[DOCUMENT] = fixed.encode("utf-8")
    if problems := lint_parts(parts):
        for problem in problems:
            print(f"  - {problem}")
        print("REFUSED: the package would not open cleanly in Word; "
              "nothing was written")
        return False
    kept = _write_back(path, parts, tag)
    print(f"  written; previous version kept at {kept}")
    return True


def _write_document(path: str, parts: dict[str, bytes], doc_xml: str,
                    tag: str) -> bool:
    """:func:`_save`, for a command holding an edited ``document.xml``."""
    parts[DOCUMENT] = doc_xml.encode("utf-8")
    return _save(path, parts, tag)


def cmd_tasks(args: argparse.Namespace) -> int:
    """The margin comments as a work list; --check gates a submission."""
    from .comments import set_done, threads

    parts = _package(args.docx, read_only=not args.done)
    if args.done:
        n = set_done(parts, [i.strip() for i in args.done.split(",")])
        if n == 0:
            print("no comment matched those ids; nothing written")
            return 1
        if not _save(args.docx, parts, "pre_tasks"):
            return 1
        print(f"marked {n} comment(s) done")
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
        _write_json(args.json, rows)
    if args.check and open_threads:
        print(f"CHECK FAILED: {len(open_threads)} open comment thread(s) - "
              f"a submission should carry none")
        return 1
    return 0


def cmd_count(args: argparse.Namespace) -> int:
    """Bucketed word count — the number a journal cap is phrased in."""
    from .wordcount import count
    counts = count(_package(args.docx, read_only=True), view=args.tracked)
    print(Path(args.docx).name)
    for name, n in counts.as_dict().items():
        print(f"  {name:<11}{n:>8,}")
    print(f"  {'total':<11}{counts.total():>8,}")
    drop = [e.strip() for e in (args.exclude or "").split(",") if e.strip()]
    counted = counts.total(exclude=drop)
    if drop:
        print(f"  {'counted':<11}{counted:>8,}  "
              f"(excluding {', '.join(drop)})")
    # Written BEFORE the verdict: the report used to sit after the
    # over-limit `return 1`, so the one run whose numbers a caller most
    # wants to read — the failing one — was the run that produced no
    # file. That is the failure `_json_default` exists to prevent, in
    # another form: the work all done and the record never written.
    if args.json:
        _write_json(args.json, counts.as_dict())
    # the cap applies to whatever is being counted: the exclusion set if
    # one was given, the full total otherwise
    if args.limit is not None and counted > args.limit:
        # `is not None`, not truthiness: `--limit 0` is a real cap that
        # every document exceeds, and it used to read as "no limit set"
        print(f"  OVER the {args.limit:,}-word limit by "
              f"{counted - args.limit:,}")
        return 1
    return 0


def cmd_math(args: argparse.Namespace) -> int:
    """Symbols as prose, and display equations Word will set inline."""
    from .equations import (
        display_equations,
        document_symbols,
        inline_display,
        prose_math,
        tokens,
    )
    doc = _package(args.docx, read_only=True)[DOCUMENT].decode("utf-8")
    findings = prose_math(doc)
    vocabulary = "".join(sorted(document_symbols(doc)))
    print(f"{Path(args.docx).name}  (math vocabulary: "
          f"{vocabulary or 'none — the document typesets no symbols'})")

    # A separate question from prose-math, and invisible to every other
    # check: a bare m:oMath is INLINE to Word, and the house rule is
    # display + centred. Word promotes a lone one on save SOMETIMES,
    # which is why it has to be set rather than trusted.
    displays = display_equations(doc, in_tables=args.in_tables)
    stranded = inline_display(doc, in_tables=args.in_tables)
    at = {m.start(): i for i, m in enumerate(P_RE.finditer(doc), 1)}
    print(f"  {len(displays)} display equation(s), "
          f"{len(stranded)} still in INLINE mode")
    # A redline is classified on its ACCEPTED side — a paragraph on its
    # way out reads as maths-only once `visible_text` drops its
    # `w:delText`, and used to be reported as a stranded display with a
    # remedy that would have wrapped an equation being deleted. Say so:
    # a count that silently answers about a different view of the file
    # than the one named on the command line is the shape this file's
    # backlog keeps finding.
    if "<w:del " in doc:
        print("  (tracked file — read on its ACCEPTED side, so a "
              "paragraph being deleted is not a finding)")
    # Say what was left out. A notation table is the ordinary reason a
    # paper has maths-only cells, and excluding them silently reads as
    # "there are none" — the shape this file's backlog keeps finding.
    if not args.in_tables:
        skipped = (len(display_equations(doc, in_tables=True))
                   - len(displays))
        if skipped:
            print(f"  ({skipped} maths-only paragraph(s) inside tables not "
                  "counted — a cell is not a stranded display; --in-tables "
                  "to include them)")
    for m in stranded:
        print(f"     ¶{at[m.start()]:<5} {tokens(m.group(0))[:60]!r}")
    if stranded:
        print("     -> equations.display(para) wraps them in m:oMathPara "
              "(one m:oMath per paragraph; it refuses more)")

    if not findings:
        print("  clean — every symbol in the text is OMML")
        return 1 if (args.check and stranded) else 0
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
    from .figures import alt_texts, caption_side
    doc = _package(args.docx, read_only=True)[DOCUMENT].decode("utf-8")
    drawings = alt_texts(doc)
    missing = [d for d in drawings if d.missing]
    # Which convention was read, because it decides every attribution
    # below it and the paper is the only thing that knows if it is
    # wrong. Silence here is what made "(no caption window)" read as
    # "this drawing has no caption" on a paper whose captions all sit
    # one paragraph away, on the other side.
    sits = "above" if caption_side(doc) == "after" else "below"
    print(f"{Path(args.docx).name}  ({len(drawings)} drawing(s), "
          f"{len(missing)} without alt text; captions read as sitting "
          f"{sits} their figures)")
    for d in drawings:
        mark = " " if not d.missing else "!"
        where = d.caption or f"(no caption {sits} it)"
        has_alt = (d.descr or "").strip()
        alt = f" alt: {(d.descr or '')[:50]!r}" if has_alt else ""
        print(f"  {mark} {where[:56]}  [{d.name or d.embed or '?'}]{alt}")
    if args.check and missing:
        print(f"CHECK FAILED: {len(missing)} drawing(s) without alt text")
        return 1
    return 0


def cmd_footnotes(args: argparse.Namespace) -> int:
    """What the footnotes are set in, and which one disagrees."""
    from .footnotes import fonts, sizes
    parts = _package(args.docx, read_only=True)
    notes = parts.get(FOOTNOTES)
    if not notes:
        print(f"{Path(args.docx).name}: no footnotes part")
        return 0
    xml = notes.decode("utf-8")
    # WITH the styles: a run that states nothing, in a paragraph whose
    # pStyle supplies a size, is not a finding. Without them every
    # style-formatted footnote reads as an outlier.
    styles = parts.get("word/styles.xml")
    report = sizes(xml, styles_xml=styles.decode("utf-8") if styles else None)
    print(f"{Path(args.docx).name}\n{report.format()}")
    print("\n== every face and size a run states ==")
    for key, count in sorted(fonts(xml).items(), key=lambda kv: -kv[1]):
        print(f"  {count:>5}  {key}")
    if args.check and not report.ok:
        n, m = len(report.outliers), len(report.mark_outliers)
        # The two findings need different repairs, so the failure says
        # which it met: `set_font` writes the BODY runs, and a mark that
        # resolves differently is usually a paragraph that lost its
        # FootnoteText style rather than anything stated on the mark.
        what = []
        if n:
            what.append(f"{n} footnote(s) do not agree with the rest — "
                        f"footnotes.set_font(xml, size=...) writes the size "
                        f"onto every run")
        if m:
            what.append(f"{m} reference MARK(s) resolve differently from the "
                        f"other marks — check the paragraph's w:pStyle "
                        f"before writing anything onto the mark")
        print("\nCHECK FAILED: " + "\n  ".join(what))
        return 1
    return 0


def cmd_smarten(args: argparse.Namespace) -> int:
    """Straight quotes to typographic ones; dry run unless --write."""
    from .hygiene import smarten_parts

    parts = _package(args.docx, read_only=not args.write)
    before = dict(parts)
    report = smarten_parts(parts)
    print(Path(args.docx).name)
    print("  " + report.format().replace("\n", "\n  "))
    if not args.write:
        print("  (dry run - pass --write to save)")
        return 0
    if parts == before:
        print("  nothing to write")
        return 0
    return 0 if _save(args.docx, parts, "pre_smarten") else 1


def cmd_authors(args: argparse.Namespace) -> int:
    """Who the document credits; ``--set`` restamps every one of them."""
    from .authors import read_authors, set_author

    parts = _package(args.docx,
                     read_only=not getattr(args, "write", False))
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
    return 0 if _save(args.docx, parts, "pre_authors") else 1


def cmd_probe(args: argparse.Namespace) -> int:
    """What shape is this manuscript? Run it BEFORE choosing an approach."""
    from .probe import probe
    # a zip with no document.xml died on KeyError — and the parts are
    # PASSED on, or this reads the live path a second time and refuses
    # the moment Word holds it
    parts = _package(args.docx, read_only=True)
    print(probe(args.docx, tuple(args.phrase), parts=parts).report())
    return 0


def _raised_prose(parts: dict[str, bytes]) -> list[str]:
    """Advisory findings from :func:`styles.raised_prose`, for `lint`.

    Joined HERE rather than inside `lint.audit_parts`, which is where it
    reads: `lint` and `styles` are siblings in the layering, so `lint`
    may not import it, and the answer is unreachable without
    ``word/styles.xml`` — a run that carries no ``w:vertAlign`` of its
    own reads as clean in every lxml root `audit` is handed. The command
    is the layer that may see both.

    Advisory, and firmly so. Word opens the file, and the toolkit has no
    command that clears this: it is a formatting mistake for a person to
    fix, which is the shape `lint.audit` was split out of `lint` for.
    """
    from .styles import raised_prose
    return [f"{r.where}: prose renders {r.value} — it wears the "
            f"{r.style} character style, which supplies it, and states "
            f"no w:vertAlign of its own: {r.text[:60]!r}"
            for r in raised_prose(parts)]


def cmd_lint(args: argparse.Namespace) -> int:
    """Structural checks for the markup Word refuses to open, and the
    findings it opens fine and reads wrongly."""
    from .lint import audit_parts, lint_parts
    parts = _package(args.docx, read_only=True)
    problems = lint_parts(parts)
    advisory = audit_parts(parts) + _raised_prose(parts)
    print(f"{Path(args.docx).name}")
    if not problems and not advisory:
        print("  clean - no structural problems found")
        return 0
    for problem in problems:
        print(f"  - {problem}")
    # Named apart from the refusals, because they ARE apart: nothing
    # declines to write a document over these, and saying so is what
    # keeps the word "REFUSED" meaning one thing.
    if advisory:
        print("  advisory - Word opens the file; these are wrong, not broken:")
        for problem in advisory:
            print(f"  - {problem}")
        if not args.strict:
            print("  (advisory only; --strict to fail on these too)")
    # Advisory findings do not fail the command. `lint.audit` was split
    # out of `lint` precisely because the bookmark check bricked every
    # mutating command on a manuscript that already had a duplicate —
    # and returning 1 here put that gate straight back for any CI or
    # paper script keyed on `docxkit lint`, on a condition the toolkit
    # still offers no command to clear. --strict is for a caller who
    # HAS cleared them and wants them kept clear.
    return 1 if problems or (advisory and args.strict) else 0


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
    first, last = args.pages or (None, None)
    out = export_pdf(args.docx, args.out, first=first, last=last)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_repack(args: argparse.Namespace) -> int:
    """Which sheet is mostly empty, and what placement would fill it."""
    import shutil
    import tempfile
    from pathlib import Path as _Path

    from .package import is_locked, write_docx
    from .pages import page_texts
    from .repack import repack
    from .word import shared_session

    name = _Path(args.docx).name
    if is_locked(args.docx):
        # The one read-only command that does NOT fall back to a
        # snapshot: every number it prints is about the page layout, and
        # a report on sheets the author cannot see is worse than none.
        raise PackageError(
            f"{name} is open in Word. Close it and retry: `repack` measures "
            f"the layout, and a snapshot would describe sheets the author "
            f"cannot see")
    parts = _package(args.docx)
    labels = tuple(w.strip() for w in args.labels.split(",") if w.strip())
    staging = _Path(tempfile.mkdtemp(prefix="docxkit_repack_"))
    trials = [0]

    def render(trial: dict[str, bytes]) -> list[str]:
        # Each candidate is a DIFFERENT document, so the render has to go
        # through the trial's own bytes: `fit` renders the file on disk
        # because its parts never change, and that shortcut is wrong here.
        trials[0] += 1
        path = staging / f"trial{trials[0]}.docx"
        write_docx(path, trial)
        try:
            return page_texts(path)
        except DocxKitError:
            raise
        except Exception as exc:        # a COM error is not docxkit's
            raise DocxKitError(
                f"Word could not render {path.name}: {exc}") from exc

    try:
        # ONE Word for the whole search. A trial is a render, and each
        # render used to start and quit its own Word: nine cold starts
        # for one short sheet with the default eight candidates.
        with shared_session(doing=f"{name}: repack"):
            report = repack(parts, render=render, labels=labels,
                            threshold=args.threshold,
                            max_drift=args.max_drift,
                            max_candidates=args.max_candidates)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(name)
    print("  " + report.format().replace("\n", "\n  "))
    best = report.best
    if best is not None:
        print(f"\n  Nothing was changed. The best of these moves {best.name} "
              f"to just after the paragraph\n  {best.after!r}. Apply it by "
              "hand — `placement.exhibit_block` is the span — and\n  "
              "re-render; the placement is an editorial call, so it is "
              "yours to make.")
    elif report.moves:
        print("\n  Nothing was changed, and none of these helps: the layout "
              "stays as it is.")
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    """Does every exhibit obey the house fit rule? --check to gate on it."""
    from .placement import audit

    render: Callable[[dict[str, bytes]], list[str]] | None = None
    if args.render:
        from .pages import page_texts

        def _render(_parts: dict[str, bytes]) -> list[str]:
            # The parts are the file's own; render the FILE, which is the
            # same document and one conversion cheaper. It must be the
            # sheets' TEXT: `audit` looks for each caption in it, and
            # `sheets` rows (number, orientation, corner) hold none.
            return page_texts(args.docx)

        render = _render

    report = audit(_package(args.docx, read_only=True), render=render)
    print(Path(args.docx).name)
    print("  " + report.format().replace("\n", "\n  "))
    if not args.check:
        return 0
    if not report.ok:
        print("\n  The rule is `placement.keep_together` / `tables.house`, "
              "and nothing\n  audited for its ABSENCE until now: a house "
              "rule enforceable only by\n  remembering to run a writer is "
              "one that decays. Aging_Well's Table 1\n  was hand-typed and "
              "dropped in whole, so no build ever styled it.")
    return 2 if not report.ok else 0


def cmd_pages(args: argparse.Namespace) -> int:
    """The page COUNT, or -- with --check -- what the render looks like."""
    if not (args.check or args.sheets):
        from .word import page_count
        print(page_count(args.docx))
        return 0

    from .package import read_parts
    from .pages import caption_problems, problems, sheets_and_texts
    # ONE render for both: the rows say what each sheet looks like and the
    # texts say where each caption landed, and Word takes seconds a paper.
    rows, texts = sheets_and_texts(args.docx, keep_pdf=args.keep_pdf)
    print(f"{len(rows)} sheet(s)")
    for row in rows:
        print(f"  {row}")
    corner = getattr(args, "corner", "lower right")
    found = problems(rows, corner=None if corner == "any" else corner,
                     expect_sheets=getattr(args, "expect_sheets", None))
    found += caption_problems(read_parts(args.docx), rows, texts)
    for note in found:
        print(f"  ** {note}")
    if not args.check:
        return 0
    if found:
        print("\nPagination cannot be inferred from the markup: two "
              "plausible causes for a blank page were derived from the "
              "XML on Parental_style and BOTH were falsified by "
              "re-rendering. Fix, then re-run this.")
    return 2 if found else 0


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
    for kind, ids in st.notes_unordered.items():
        # Nothing else says this. The file renders correctly, the counts
        # are right and every text gate passes — and the next Compare
        # rewrites the definitions into document order, which reads as
        # the whole part having moved (81 glyph runs on AFI, blamed on
        # the batch after the one that did it).
        print(f"      {kind} definitions are NOT in document order: "
              f"{', '.join(ids[:6])}{' ...' if len(ids) > 6 else ''}"
              f" — Word's Compare will rewrite them, and the next build "
              f"reads the part as moved")


def _summarize(parts: list[str], *, keep: int = 4) -> str:
    """Part names as a line someone reads rather than skips.

    The first real staleness report listed sixteen, twelve of them
    ``word/fonts/font*.odttf`` from one tick of Word's embed-fonts box,
    on a single line. A directory that contributes more than one part is
    worth one entry.
    """
    folded: dict[str, int] = {}
    for name in parts:
        if "/" in name:                 # a part at the package ROOT has no
            folder = name.rsplit("/", 1)[0] + "/"   # directory to fold into,
            folded[folder] = folded.get(folder, 0) + 1   # and folding it
    out = [name for name in parts       # under "" dropped it from the line
           if "/" not in name or folded[name.rsplit("/", 1)[0] + "/"] == 1]
    out += [f"{folder} ({n} parts)" for folder, n in folded.items() if n > 1]
    out.sort()
    if len(out) <= keep:
        return ", ".join(out)
    return f"{', '.join(out[:keep])}, and {len(out) - keep} more"


def _survey_row(item: object) -> str:
    from .revision import Survey
    assert isinstance(item, Survey)
    marks = []
    if item.state is not None and not item.state.is_truth:
        where = ", ".join(
            f"{n} in {p.split('/')[-1].replace('.xml', '')}"
            for p, n in item.state.by_part.items())
        marks.append(f"{item.state.pending} pending ({where})")
    if item.stale:
        marks.append(f"baseline stale: {_summarize(list(item.stale))}")
    if item.staged:
        marks.append("batch staged in build/")
    if item.locked:
        marks.append("open in Word")
    if item.error:
        marks.append(item.error)
    tail = f"   {' · '.join(marks)}" if marks else ""
    # Say that it truncated. "Coercion or Persuasion? Dete" reads as a
    # name someone typed badly; the ellipsis says the row is short, not
    # the paper.
    name = item.name if len(item.name) <= 32 else item.name[:31] + "…"
    return f"  {item.verdict:<9} {name:<33}{tail}"


def cmd_revision_survey(args: argparse.Namespace) -> int:
    """Every registered paper in one view — `status --all`.

    The protocol is single-paper by design, and with nine papers on it
    the question an author actually has is which of them is waiting.
    Nine `status` invocations was the previous answer.

    Rows worst first, and the exit code is the worst row's — both are
    `revision.survey_exit_code`'s; this prints.
    """
    from .revision import (
        registered,
        registry_path,
        scan,
        survey,
        survey_exit_code,
    )
    for root in args.scan or []:
        found = scan(root)
        print(f"scanned {root}: {len(found)} paper(s)")
    configs = registered()
    if not configs:
        print(f"no papers registered yet ({registry_path()}).\n"
              f"`docxkit revision status --all --scan <FOLDER>` walks a "
              f"folder and adds what it finds;\n`revision init` registers "
              f"a new paper by itself.")
        return 0
    rows = survey(configs)
    rows.sort(key=lambda r: (r.rank, r.name.lower()))
    for row in rows:
        print(_survey_row(row))
    print(f"\n  {len(rows)} paper(s) · {registry_path()}")
    return survey_exit_code(rows)


def cmd_revision_status(args: argparse.Namespace) -> int:
    """Truth or proposal? The one question the layout answers by itself.

    Exit 0 means both: settled AND built on a current baseline. A truth
    whose baseline has drifted exits 4, not 0 — the whole point of a
    non-zero status is to let a script refuse to start a batch, and a
    batch on a stale base is refused by `promote` only after a Word
    Compare has been paid for.

    So a run that could not ASK the second question does not exit 0
    either. With the file open in Word the counts come from a snapshot
    and the drift check cannot run at all; it exits 1 and says which
    answer is missing, rather than printing the two lines that a settled,
    current paper prints.
    """
    if getattr(args, "all", False) or getattr(args, "scan", None):
        return cmd_revision_survey(args)
    from .revision import status
    paper = _paper(args)
    print(f"{paper.name}\n  {paper.working}")
    # Every DECISION here is `revision.status`; this renders it. The
    # locked-file defect below was fixed inside this function on
    # 2026-08-31 and could only be tested through `argv`, with the exit
    # code as the one contract a script could read — which is what the
    # structural review of 2026-09-01 asked to move, command by command.
    report = status(paper)
    st = report.working
    if st.from_snapshot:
        print(_SNAPSHOT_NOTE)
    _show_state("working", st)
    if report.prev is None:
        print("  prev      MISSING - no baseline to compare or reject "
              "against; run `docxkit revision baseline`")
        return report.exit_code
    _show_state("prev", report.prev)
    # The drift check needs the file's SAVED bytes and `drift` reads
    # them directly, so under a lock it raised and the command died —
    # after printing two "0 pending -> TRUTH" lines, which is exactly
    # the shape of a healthy, current baseline. Measured on Aging_Well,
    # 2026-08-30: the same pair, seconds apart, answered "both sides
    # settled" locked and "** baseline STALE: word/ (8 parts) **"
    # closed. The counts are right either way — they come from the
    # snapshot — and it is the missing check that has to be named, not
    # inferred from a warning that did not appear.
    #
    # Exit 1, which is what the lock produced before, so nothing
    # gating on this command changes its mind: what changed is that the
    # reader is told which question went unanswered.
    if not report.drift_checked:
        print("\n  drift     NOT CHECKED - the file is open in Word and "
              "this comparison\n            needs its saved bytes. The "
              "counts above are the snapshot's and\n            are right; "
              "whether prev.docx is still the baseline this paper\n"
              "            grew out of is unknown. Close the file and "
              "re-run.")
        return report.exit_code
    stale = list(report.stale)
    if stale:
        print(f"\n  ** baseline STALE: {_summarize(stale)} differ(s) **")
        print(f"     Both files count 0 pending, and they are not the same "
              f"paper -\n     prev.docx is not what {paper.working.name} "
              f"grew out of. Building a batch\n     on it compares against "
              f"the wrong base. First:\n"
              "       docxkit revision ingest     (what changed, read-only)"
              "\n       docxkit revision baseline   (record it as the new "
              "truth)")
    return report.exit_code


def cmd_revision_doctor(args: argparse.Namespace) -> int:
    """Who else in the repo thinks they know where the manuscript is.

    Exits 2 on a finding, so a migration can gate on it. It has to run
    on a tree that is otherwise GREEN, because that is the state it
    exists to break: the AFI suite that selected a manuscript three
    generations stale was red only by luck, and would have stayed green
    had the two generations agreed on the counts it happened to check.
    """
    from .revision import doctor
    paper = _paper(args)
    found = doctor(paper)
    print(f"{paper.name}")
    print(f"  declared  {paper.working}")
    if not found:
        print("  nothing else in the project selects a manuscript")
        return 0

    keys = [d for d in found if d.kind == "key"]
    patterns = [d for d in found if d.kind == "pattern"]
    literals = [d for d in found if d.kind == "literal"]

    # KEYS and PATTERNS in full, literals counted. The first version
    # printed all of them and AFI answered with 134 lines, three of which
    # mattered; about 130 were spent builders and a shipped replication
    # package, which under the forward-only rule are the record rather
    # than a defect. An unreadable gate is one people switch off.
    if keys:
        print(f"\n{len(keys)} config key(s) within a typo of one the "
              f"protocol reads — a misspelt key takes its\ndefault in "
              f"silence, so the value written here is not the one in "
              f"force.")
        for doubt in keys:
            print(f"  {doubt}")
    if patterns:
        print(f"\n{len(patterns)} PATTERN selection(s) — these name no "
              f"file, so a rename does\nnot break them: they quietly "
              f"select whatever else is on disk.")
        for doubt in patterns:
            print(f"  {doubt}")
    if literals and args.literals:
        print(f"\n{len(literals)} literal selection(s):")
        for doubt in literals:
            print(f"  {doubt}")
    elif literals:
        print(f"\n{len(literals)} literal selection(s) not shown — "
              f"`--literals` to list them.\nA spent builder naming an "
              f"old generation is the record, not a defect;\ndeclare its "
              f"folder under `[doctor] skip` in paper.toml to retire it.")
    return 2


#: The two things a lost link can BE, and they need opposite actions.
#: Reported as one list under the first of these, which is false of the
#: second in every clause — the words did not survive, no script can
#: restore them, and the content layers above did show it: the deletion
#: is in the same report's `text` section a few lines up.
_LOST_EATEN = ("Word does this silently when it collapses a paragraph to "
               "make an edit;\n   the words all survive, so no content "
               "layer above shows it — which is\n   also what lets the "
               "link be rebuilt (`citations.link_all`).")
_LOST_CUT = ("The WORDS are gone too, so this is not Word's doing: the "
             "passage itself\n   was deleted, and that deletion is in the "
             "text section above. Nothing to\n   put back — check each was "
             "meant, then name it with --accept-loss.")


def _say_lost(lost: Sequence[object]) -> None:
    """The LOST block, grouped by whether the words survived."""
    def words(loss: object) -> bool | None:
        return getattr(loss, "words", None)

    print(f"\n== LOST ({len(lost)}) ==")
    groups = [(_LOST_EATEN, [x for x in lost if words(x) is True]),
              (_LOST_CUT, [x for x in lost if words(x) is False]),
              ("", [x for x in lost if words(x) is None])]
    filled = [(why, items) for why, items in groups if items]
    for why, items in filled:
        # Headed only when the list is MIXED, which is the case the one
        # explanation got wrong: a report of 4 links Word ate and 5 the
        # author cut, described as though all 9 kept their words. A list
        # that is all one kind reads better flat.
        if len(filled) > 1:
            kind = ("the words SURVIVE" if why is _LOST_EATEN else
                    "the words are GONE" if why is _LOST_CUT else "structure")
            print(f"   -- {kind} ({len(items)})")
        for loss in items:
            print("   ", loss)
        if why:
            print(f"   {why}")
    print("   `revision baseline` will refuse until these are restored or "
          "named with\n   --accept-loss.")


def cmd_revision_ingest(args: argparse.Namespace) -> int:
    """What did the author change while I was away? (read-only)"""
    from .revision import ingest
    paper = _paper(args)
    report = ingest(paper.working, paper.prev)
    print(f"{paper.name}: {paper.prev.name} -> {paper.working.name}")
    if report.from_snapshot:
        print(_SNAPSHOT_NOTE)

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
        print(f"   no differences - {paper.working.name} is still the "
              f"baseline")

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

    if report.lost:
        _say_lost(report.lost)

    if report.relabelled:
        print(f"\n== RE-LABELLED ({len(report.relabelled)}) ==")
        for change in report.relabelled:
            print("   ", change)
        print("   The anchors are intact and still linked, so nothing is "
              "lost and\n   `revision baseline` does not refuse: an author "
              "editing the visible\n   text of a citation is an ordinary "
              "edit, not damage.")
        # …unless the new label does not close what it opens. Then the
        # anchor is fine and the SPAN has reached past its mention, and
        # this section's whole message — nothing is lost — is the one
        # thing that would send a reader past it.
        if odd := [c for c in report.relabelled if c.unbalanced]:
            print(f"\n   BUT {len(odd)} of these left the span "
                  f"UNBALANCED, which is not a re-label:")
            for change in odd:
                print(f"     {change.anchor}: {change.now[:48]!r} carries "
                      f"an unmatched {change.unbalanced!r}")
            print("   The link has reached past its mention — run "
                  "`docxkit citations` for\n   the UNBALANCED SPAN "
                  "findings, and repair the spans before the baseline.")

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
            "lost": [loss.key for loss in report.lost],
        })
    # HandbackLoss.exit_code: `ingest --check` and the `baseline` refusal
    # report the same finding, so a script reads one number for it
    return HandbackLoss.exit_code if (args.check and report.lost) else 0


def cmd_revision_build(args: argparse.Namespace) -> int:
    """Clean edit -> redline, via Word Compare."""
    from .revision import build
    paper = _paper(args)
    report = build(paper, args.revised, args.out,
                   allow_math_resolve=args.allow_math_resolve,
                   allow_pending_baseline=args.allow_pending_baseline,
                   allow_pending_working=args.allow_pending_working,
                   allow_stale_baseline=args.allow_stale_baseline,
                   resolve_math=not args.keep_math,
                   moves=not args.no_moves,
                   force=args.force,
                   progress=lambda line: print("   ", line))
    out = Path(args.out) if args.out else paper.batch
    print(f"\nbuilt {out} ({report.revisions} revisions)")
    print(f"\nNow run:  docxkit revision validate {out}")
    return 0


def cmd_revision_ship(args: argparse.Namespace) -> int:
    """`build` then `validate`, in ONE process and ONE Word session.

    The two steps run back to back on every batch, in that order, and
    each was paying its own Word cold start: 13.5 s + 38.9 s on a
    one-edit AFI batch, about 52 s of 95. Nothing about them changes
    here — the same two commands, the same output, the same exit
    codes — except that the second finds Word already open.

    Stops on a failed build rather than validating whatever the previous
    batch left in `build/batch.docx`, which is the file `validate`
    defaults to and the reason this is one command and not a shell `&&`.
    """
    from .word import shared_session
    paper = _paper(args)
    # The block that OPENS the instance owns the ceiling — the deadlines
    # `build` and `validate` would each set are nested requests here and
    # ignored, so it is passed once, over both.
    with shared_session(deadline=paper.word_deadline or None,
                        doing=f"{paper.name}: build and validate"):
        if (code := cmd_revision_build(args)) != 0:
            # Third abort path, and the reason `_skipped_gates` is
            # called from each return rather than from one exit: every
            # new one has to remember. `ship` takes --run-gates too.
            return _skipped_gates(args, code)
        print()
        args.batch = str(Path(args.out) if args.out else _paper(args).batch)
        args.baseline = None
        return cmd_revision_validate(args)


def _say_footnotes(report: object) -> None:
    """The footnote half of gate 5, keyed on what was MEASURED.

    `moved_footnotes` finds a shape — a definition Compare emitted as
    one insertion with no matching deletion — and the warning claimed
    the outcome: *"rejecting empties the note, so gate 5 will fail on
    it."* The shape is necessary and not sufficient, and this report's
    own reject-all layer already holds the answer, so the two could
    contradict each other two lines apart. Twice on Aging_Well they did,
    beside a genuine LINKS mismatch, where it reads as a second blocking
    finding and the batch gets thrown away.
    """
    emptied = getattr(report, "emptied_footnotes", [])
    for note in emptied:
        print(f"   footnote {note}: the whole note is one insertion with "
              f"no deletion — its REFERENCE moved, so rejecting empties it")
    benign = [n for n in getattr(report, "moved_footnotes", [])
              if n not in emptied]
    if benign:
        ids = ", ".join(str(n) for n in benign)
        print(f"   (footnote {ids}: re-emitted as an insertion, and "
              f"reject-all restores it — not part of this mismatch)")


def _say_glyphs(report: object) -> None:
    """The glyph half of gate 5, with the VIEW it is about named.

    A boolean for a 68,000-character stream says only that SOMETHING
    moved; on AFI the answer was two characters. And which view it is
    about is the rest of the question: Word downgrades U+2212 to a
    hyphen while re-serialising an equation, `build` puts it back in the
    accepted document — the one that ships — and the rejected one keeps
    what Compare wrote. Printing `glyphs: False` without saying so reads
    as a defect in the edit, and it failed three consecutive rounds on a
    manuscript whose author had touched nothing.
    """
    for run in getattr(report, "glyph_diff", []):
        print(f"   GLYPH (reject-all vs baseline) {run}")
    if getattr(report, "glyph_math_only", False):
        print("   every GLYPH above is a math character Word downgrades "
              "when it re-serialises an equation, not an edit: the "
              "ACCEPTED view has them restored and the REJECTED one "
              "does not.")


def _seconds(text: str) -> float:
    """A positive timeout. 0 is refused rather than taken literally.

    Under the near-universal convention that 0 means "no timeout", a
    caller typing `--gate-timeout 0` got the opposite: `subprocess`
    raises `TimeoutExpired` immediately, so every gate reported
    `[TIMED OUT] 0.0s` without running and a clean manuscript exited 5.
    """
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r}: expected a number of seconds") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(
            f"{text}: a gate timeout must be positive. There is no "
            f"'no timeout' setting — a gate that cannot be bounded can "
            f"stop a hand-back, which is what the bound is for.")
    return value


def _skipped_gates(args: argparse.Namespace, code: int) -> int:
    """Say that `--run-gates` did not get to run them.

    Four paths reach it: a batch built on another baseline (the FIRST
    abort, and the one this function was written for and did not
    cover), a lint failure, a batch Word cannot open, and a `ship`
    whose build half failed. None is a reason to run the paper's own
    checks — the thing under test is unshippable either way — but
    silence after a flag was passed reads as "they ran and were fine",
    which is the one thing it must not read as.

    Called from each return rather than from one exit point, which is
    structurally prone to missing the next one somebody adds. It has
    missed two already.
    """
    if getattr(args, "run_gates", False) and _paper(args).gates:
        print("\n== the paper's own gates ==  NOT run: the ladder aborted "
              "above")
    return code


def _paper_gates(args: argparse.Namespace, report: object) -> None:
    """The paper's OWN gates, after the ladder — listed, or run.

    Separate from the ladder in the output as well as in the code,
    because they answer different questions: everything above is about
    the BATCH, and these are about the paper. Listing them when they
    were not run is deliberate — a list of unrun checks is a reminder,
    and silence reads as "nothing to run".

    What ran lands on `report.gates`, and the verdict is the report's
    (`ValidateReport.exit_code`); this prints as each gate finishes.
    """
    from .revision import ValidateReport
    assert isinstance(report, ValidateReport)
    paper = _paper(args)
    if not paper.gates:
        if getattr(args, "run_gates", False):
            print("\n== the paper's own gates ==  none listed in paper.toml")
        return
    if not getattr(args, "run_gates", False):
        print(f"\n== the paper's own gates ==  {len(paper.gates)} listed, "
              f"NOT run (--run-gates)")
        for command in paper.gates:
            print(f"   · {command}")
        return

    from .revision import run_gates
    print(f"\n== the paper's own gates ==  {len(paper.gates)}, from the "
          f"project root")
    # A heartbeat, because `capture_output` swallows everything the gate
    # prints: a 12-minute pytest suite under a 900s timeout showed an
    # empty terminal, indistinguishable from a hang.
    def say(line: str) -> None:
        print(f"   · {line.removeprefix('gate: ')}", flush=True)

    for gate in run_gates(paper, timeout=args.gate_timeout, progress=say):
        report.gates.append(gate)
        print(f"     [{gate.verdict}] {gate.seconds}s")
        for line in ([] if gate.ok else gate.output.splitlines()):
            print(f"        {line}")
    failed = sum(1 for gate in report.gates if not gate.ok)
    if failed:
        print(f"\n{failed} of {len(paper.gates)} of the paper's gates "
              f"failed.")


def _render(args: argparse.Namespace, paper: object, report: object,
            target: Path) -> None:
    """The eye gate: the anchors asked for, and the equation pages.

    Two sources, one section. `--render ANCHOR` names pages by hand;
    `report.math_anchors` names the pages of the equations the batch
    adds or changes, and a paper renders those by DEFAULT (`[verify]
    render_math`) — the opt-in stayed unused while four defects only a
    page can show went through a green ladder. Never the exit code:
    what a render finds is for a person to read.

    Said aloud when it does NOT run, as `_skipped_gates` says its gates
    did not: under `--no-word` there is no Word to render with, and a
    silence there reads as "no equations changed".
    """
    from .revision import Paper, ValidateReport, render_accepted
    assert isinstance(paper, Paper) and isinstance(report, ValidateReport)
    anchors = list(args.render)
    auto = [a for a in report.math_anchors if a not in anchors]
    if auto and paper.render_math and args.no_word:
        print(f"\n== render ==  {len(auto)} equation page(s) NOT rendered "
              f"(--no-word)")
    elif auto and paper.render_math:
        anchors += auto
    if not anchors:
        return
    why = (f" — {len(auto)} for equations the batch adds or changes"
           if auto and paper.render_math and not args.no_word else "")
    print(f"\n== render ==  {len(anchors)} anchor(s), accepted view{why}")
    try:
        made = render_accepted(target, anchors)
    except ImportError as exc:
        # The reader is an optional extra. Not a failure of the batch —
        # the ladder above has spoken — but not silence either.
        print(f"   not rendered: {exc}")
        return
    for anchor, png in made.items():
        print(f"   {anchor!r} -> {png.name}" if png
              else f"   {anchor!r}: on no page — check the wording")


def cmd_revision_validate(args: argparse.Namespace) -> int:
    """The gate ladder. Gate 5 is the one that proves reviewability.

    Every DECISION here is `revision.validate`'s — which gate stopped
    the ladder (`ValidateReport.aborted`) and what a script is told
    (`ValidateReport.exit_code`); this prints. One precondition stays:
    a batch that is not there is not a batch the ladder can be asked
    about.
    """
    from . import guard as _g
    from .revision import state, validate
    paper = _paper(args)
    target = Path(args.batch) if args.batch else paper.batch
    base = Path(args.baseline) if args.baseline else paper.prev
    if not target.exists():
        # A TRUTH state is the normal state of a paper between rounds,
        # and there is no batch in it. The raw `cannot read …batch.docx:
        # [Errno 2]` reads as a broken installation or a lost file
        # rather than as "there is nothing pending" — it cost a real
        # detour on Life_Expectancy, whose round-2 protocol listed this
        # command as a PRECONDITION to be run green before any edit.
        # The protocol author reasonably assumed a gate ladder could be
        # run on a clean paper.
        here = state(paper.working) if paper.working.exists() else None
        print(f"no batch to validate: {target} is not there.")
        if here is not None:
            print(f"{paper.working.name} holds {here.pending} pending "
                  f"revision(s) — {here.label}.")
        print("`docxkit revision status` is the check for a paper between "
              "rounds; `revision build` is what makes a batch.")
        return 3
    # Timed HERE rather than in `revision.validate`, which takes two
    # paths and never sees a Paper — so it has neither a root to record
    # into nor the paper's opt-out. This is the layer that resolved
    # both. Same for `ingest`, and for the same reason.
    from .revision import _timing
    with _timing.session("validate", paper):
        report = validate(target, base if base.exists() else None,
                          use_word=not args.no_word,
                          word_deadline=paper.word_deadline or None)

    print(f"{target.name}")
    if report.aborted == "baseline":
        print(f"== baseline ==  {target.name} was NOT built on {base.name}")
        print(f"   it says it was built on {report.built_on[:16]}, and "
              f"{base.name} is {_g.sha256(base)[:16]}")
        print("   every gate below compares the two, so the whole ladder "
              "would describe a batch nobody is working on. Rebuild on "
              "this baseline — or, if the last build was REFUSED, delete "
              "the stale batch first.")
        code = _skipped_gates(args, report.exit_code)
        print("\nVERDICT: FAIL")
        return code
    print("== lint ==", "clean" if not report.lint
          else f"{len(report.lint)} problem(s)")
    for problem in report.lint:
        print("   FAIL:", problem)
    if report.aborted == "lint":
        print("\nABORT before Word - fix lint first.")
        return _skipped_gates(args, report.exit_code)
    print("== counts ==", report.counts)
    if report.aborted == "word":
        print("== Word ==  FAILED (corrupted):", report.word_error)
        return _skipped_gates(args, report.exit_code)
    if report.word_opened:
        # "in the body" is not a hedge: Word's Revisions collection walks
        # the main story, so a footnote-only batch reads 0 here while the
        # package count above says 25. Two numbers, both true, and the
        # unlabelled one read as "Compare produced nothing".
        print(f"== Word ==  opened, {report.word_revisions} revision "
              f"group(s) in the body")
    print("== accept-all ==", report.accepted)
    if report.empty_shells:
        print("   ** WARNING: empty OMML shells after accept **")
    if report.lost_parts:
        print(f"== parts ==  {len(report.lost_parts)} in the baseline and "
              f"NOT in the batch")
        for part in report.lost_parts:
            print(f"   LOST {part}")
        # Named at the layer the reader is STANDING on. This is
        # `revision validate`, so the paper is on the protocol and the
        # protocol drives the carry: pointing at `restore_parts` sent a
        # second session two floors down to write a per-paper script
        # for a paper that was already using `[batch] carry` three
        # lines above where it was looking (2026-08-24). The function
        # is the mechanism; the config is the instruction.
        print("   Word's Compare rebuilds rather than annotates and drops "
              "what it will not carry; promote would copy this batch over "
              "the manuscript, so the part goes with it.\n"
              "   Add it to [batch] carry in paper.toml and rebuild. The "
              "build then restores the part WITH its Content-Types "
              "override, a relationship on an id free in the target, and "
              "— for a header or footer — the section reference that puts "
              "it on the page. Copying the file alone is enough for some "
              "parts and not others: a footer restored without its sectPr "
              "reference is present, referenced by nothing, on no page, "
              "and this gate goes green because the file is there.")
    if report.reject_matches_baseline is not None:
        verdict = "OK" if report.reject_matches_baseline else "MISMATCH"
        print(f"== reject-all == baseline ?  {report.reject_detail} "
              f"-> {verdict}")
        if not report.reject_matches_baseline:
            print("   the batch is NOT fully reviewable: rejecting "
                  "everything does not restore the baseline")
            # Three booleans do not say whether the batch is salvageable
            # or has to ship clean, which is the decision waiting on
            # them — and finding out cost a bespoke difflib script.
            _say_footnotes(report)
            for u in report.reject_diff:
                print(f"   {u}")
            _say_glyphs(report)
            for moved in report.structure_diff:
                print(f"   STRUCTURE {moved}: the rejected batch does not "
                      f"carry what the baseline does, and it is not a "
                      f"character — a move can duplicate a table or drop a "
                      f"paragraph's bookmarks, and the text gates see "
                      f"neither")
            for link in report.lost_links:
                print(f"   LINK LOST {link}: the baseline has this "
                      f"hyperlink and the rejected batch does not — Word's "
                      f"Compare does not rebuild a link inside a rejected "
                      f"deletion, so the words come back as plain text")
    if report.accept_paths_agree is not None:
        print("== XML accept == Word accept ?",
              "OK" if report.accept_paths_agree else "MISMATCH")
    _render(args, paper, report, target)
    # The paper's own gates are listed (or run) by `_paper_gates` below,
    # in ONE section rather than two: this used to print its own "run
    # these too" list, so with --run-gates the reader got the commands
    # once as a reminder and again with their verdicts.
    # The verdict is printed AFTER the paper's gates and reflects them.
    # It used to print here, before `_paper_gates` ran, so a run whose
    # paper gates failed said "VERDICT: PASS" and then exited 5 — and
    # both the log template and the README treat that line as the
    # answer.
    _paper_gates(args, report)
    print("\nVERDICT:", "PASS" if report.exit_code == 0 else "FAIL")
    return report.exit_code


def cmd_revision_promote(args: argparse.Namespace) -> int:
    """Put a validated batch onto the manuscript, lock- and hash-guarded."""
    from .revision import promote
    paper = _paper(args)
    report = promote(paper, args.batch, args.base)
    # The hash, so that "the promoted file differs from the batch" can
    # be settled by re-hashing rather than by reading paragraphs — which
    # is how a promote was once filed as rewriting one (see `promote`).
    from .guard import sha256
    print(f"promoted {report.promoted.name} -> {report.onto.name} "
          f"(sha256 {sha256(report.onto)[:16]}, the batch's own bytes)")
    if report.stamp is not None:
        print(f"stamp carried beside it: {report.stamp.name}")
    print(f"rescue copy of the previous live file: "
          f"{report.rescue.relative_to(paper.root)}")
    print(f"redline kept (never pruned): "
          f"{report.redline.relative_to(paper.root)}")
    if report.pruned:
        print(f"pruned {len(report.pruned)} older rescue(s), keeping "
              f"{paper.rescue_keep}")
    print(f"\n{report.onto.name} is now a PROPOSAL. The author adjudicates "
          f"it in Word;\nthis tool never accepts on their behalf.")
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


def cmd_revision_redlines(args: argparse.Namespace) -> int:
    """List the kept redlines: what each batch actually proposed."""
    from .revision import redlines
    paper = _paper(args)
    found = redlines(paper)
    if not found:
        print(f"no redlines in {paper.redline_dir}")
        print("Kept from the first promote after docxkit learned to keep "
              "them; a paper whose batches all predate that has none.")
        return 0
    print(f"{paper.redline_dir}  (never pruned)")
    for path in found:
        print(f"  {path.name:<46} {path.stat().st_size:>9,} bytes")
    print(f"\n{len(found)} redline(s). Each is the batch as the author was "
          f"handed it — open one to see what a round proposed, including "
          f"what was rejected.")
    return 0


def cmd_revision_baseline(args: argparse.Namespace) -> int:
    """The author accepted: record the manuscript as the new truth."""
    from .revision import baseline
    paper = _paper(args)
    # Both forms, and mixtures of them: one flag per loss (what the
    # refusal prints, one line each) and one comma-separated list (what
    # the help has always documented).
    accepted = tuple(t.strip()
                     for chunk in (args.accept_loss or [])
                     for t in chunk.split(",") if t.strip())
    report = baseline(paper, force=args.force, accept_loss=accepted,
                      repair_math=args.repair_math, note=args.note,
                      log=not args.no_log)
    for token in accepted:
        print(f"  accepted loss: {token}")
    print(f"baseline updated: {report.prev}")
    if report.verdict is not None and report.row:
        print(f"\nlogged: {report.row.strip()}")
    elif report.verdict is not None:
        print("\nlog.md has no batch table to append to — record this "
              "round by hand:\n"
              f"  {report.verdict.summary()} · {report.verdict.outcome}")
    return 0


def cmd_revision_init(args: argparse.Namespace) -> int:
    """Scaffold the layout around a manuscript that has not migrated."""
    from .revision import _CONFIG, _DIR, init
    source = Path(args.source).resolve()
    root = Path(args.root).resolve() if args.root else source.parent
    # Asked BEFORE the call: afterwards the config exists either way, and
    # what a reader needs to know is which of the two things happened.
    rewrite = (root / _DIR / _CONFIG).is_file()
    paper = init(root, args.source, working=args.working or "",
                 name=args.name or "", author=args.author,
                 language=args.language, attic=args.attic, force=args.force)
    adopted = paper.working == source

    if rewrite:
        kept = paper.config.parent
        saved = sorted((kept.glob(f"{paper.config.stem}_pre_init*"
                                  f"{paper.config.suffix}")),
                       key=lambda p: p.stat().st_mtime)
        print(f"updated {paper.config}")
        print(f"  the paper   : {paper.working}")
        print("  only the keys you gave were rewritten; every other key, "
              "section\n  and comment is unchanged, and log.md and "
              "build/prev.docx were not\n  touched — they are the paper's "
              "history and its baseline.")
        # Unguarded on purpose. `rewrite` IS `config.exists()`, read
        # before the call, and `init` backs the config up under exactly
        # that condition — so by the time this prints there is always one
        # to name. It was `if saved:` until 2026-08-24, which is a branch
        # nothing can take: the third dead guard this package has grown
        # out of a construction invariant, and the first found by a
        # COVERAGE floor rather than by a mutation sweep, because a
        # branch that cannot be taken is exactly a floor that cannot be
        # reached.
        print(f"  previous config: {saved[-1].name}")
        return 0

    print(f"scaffolded {paper.config.parent}")
    print(f"  the paper   : {paper.working}"
          f"{'  (adopted in place — not copied)' if adopted else ''}")
    print("  build/prev.docx (baseline, same bytes)")
    if adopted:
        print("\nYour file keeps its name and its folder; revision/ holds the "
              "machinery\nonly. paper.toml is the one line that says where "
              "the paper is.")
        return 0
    print(f"\n{source.name} was COPIED, not moved: it is still in "
          f"{source.parent}\nand nothing reads it any more. Retire it to the "
          "record once the paper's\nown gates pass against the new location.")
    return 0


def _build_args(parser: argparse.ArgumentParser) -> None:
    """Every argument the BUILD half takes, declared once.

    `ship` runs `build` and then `validate`, and `cmd_revision_ship`
    delegates to `cmd_revision_build`, which reads `args.<flag>` — so a
    flag added to one parser and not the other is not a gap, it is an
    `AttributeError` on every ship. That is exactly what
    `--allow-stale-baseline` did the day it was added: four tests, and
    it would have been every real run.

    The two parsers were one parser written twice. This is the same
    "walk the change to every reader of the fact" lesson the backlog
    records five instances of — except here the walk can be deleted
    instead of remembered.
    """
    parser.add_argument("revised", help="the edited CLEAN copy of prev.docx")
    parser.add_argument("--out", metavar="PATH",
                        help="default: revision/build/batch.docx")
    parser.add_argument("--allow-math-resolve", action="store_true",
                        help="ship equations Word baked in unreviewable "
                             "(they almost never are meant to be)")
    parser.add_argument("--allow-stale-baseline", action="store_true",
                        help="build even though prev.docx is no longer what "
                             "the manuscript grew out of (the redline would "
                             "show the author's own edits as proposals)")
    # The other answer to the math refusal, and the better one: keep the
    # equation revisions TRACKED instead of accepting them. Measured on
    # LI7 (2026-08-15) — the Flat OPC route serialized 1870 revisions
    # with the math kept, reject-all included.
    parser.add_argument("--keep-math", action="store_true",
                        help="leave equation revisions TRACKED rather than "
                             "accepting them (try this before "
                             "--allow-math-resolve)")
    # Word's move detection is a heuristic, and a wrong one truncates
    # the paragraph it scored as moved — measured on Aging_Well, where
    # the accepted view lost a clause, a link and the sentence after it,
    # and the same pair with moves off reproduced it exactly. Until this
    # flag existed a round that MOVED a passage could not be built
    # through the CLI at all: the accept gate refused it, correctly, and
    # the only switch on offer turned the gate off.
    parser.add_argument("--no-moves", action="store_true",
                        help="compare without Word's move detection (a "
                             "longer redline, and the answer when a round "
                             "that RELOCATES text fails the accept gate)")
    parser.add_argument("--allow-pending-baseline", action="store_true",
                        help="absorb the baseline's pending revisions "
                             "deliberately")
    # Its own switch rather than a widening of the one above: the two
    # states want opposite advice, and a flag that turned off both would
    # be reached for over the commoner one and silence the rarer.
    parser.add_argument("--allow-pending-working", action="store_true",
                        help="build over a promoted batch the author has "
                             "not adjudicated (their open verdict is "
                             "decided for them either way)")
    # The staleness refusal has named this flag since it was written,
    # and `build --help` did not list it: the one way out the reader was
    # told about was `error: unrecognized arguments: --force`. The backup
    # is taken either way, so the previous batch survives.
    parser.add_argument("--force", action="store_true",
                        help="rebuild over a batch.docx that was edited "
                             "since docxkit wrote it (a backup is taken "
                             "first)")


def build_parser() -> argparse.ArgumentParser:
    """Every command the CLI offers, as a parser nobody has run yet.

    Split out of :func:`main` so the command list can be ENUMERATED.
    `tests/test_cli_guards.py` sweeps every subcommand against a file
    Word holds and asserts one contract for all of them — answer from a
    snapshot and say so, or refuse in a way a clean run cannot be
    mistaken for. A hand-written list of commands to sweep is a list
    that stops covering the next command somebody adds, which is the
    property that sweep exists to have (BACKLOG: "one missing class of
    test: nothing exercises the toolkit AS A WORKFLOW").
    """
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
    p.add_argument("--ignore", metavar="WORD,...", default="",
                   help="capitalised words this paper's prose puts before "
                        '"and" — "<Word> and <Source> (Year)" reads as a '
                        "two-author citation, and an UNLINKED manuscript "
                        "has no apparatus to settle it with")
    p.add_argument("--later-mentions", action="store_true",
                   help="also report every LATER mention of a linked work "
                        "that is plain text (house style differs by paper, "
                        "so it is off by default; the mention count prints "
                        "either way)")
    p.set_defaults(fn=cmd_citations)

    p = sub.add_parser(
        "link",
        help="build citation<->entry links document-wide (dry by default)")
    p.add_argument("docx")
    p.add_argument("--write", action="store_true")
    p.add_argument("--alias", action="append", metavar="CITED=FILED",
                   help='e.g. --alias "WHO=World Health Organization"')
    p.add_argument("--only", metavar="NAME,...", default="",
                   help="wire these works only — key, surname or bookmark "
                        "name. A repair is usually six citations, not a "
                        "document")
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
    p.add_argument("--fix", action="store_true",
                   help="write the mechanical fixes: punctuation and "
                        "glyphs in the entries (never a name), the list "
                        "alphabetised, and the house layout — new page, "
                        '0.5" hanging indent, 4 pt after '
                        "(a backup is taken first)")
    p.add_argument("--json", metavar="PATH")
    p.add_argument("--alias", action="append", metavar="CITED=FILED",
                   help='e.g. --alias "WHO=World Health Organization" — '
                        "without it the acronym in the prose and the full "
                        "name in the list read as two different works")
    p.add_argument("--ignore", metavar="WORD,...", default="",
                   help="capitalised words this paper's prose puts before "
                        '"and" — "<Word> and <Source> (Year)" reads as a '
                        "two-author citation, and an UNLINKED manuscript "
                        "has no apparatus to settle it with")
    p.set_defaults(fn=cmd_refstyle)

    p = sub.add_parser(
        "crossrefs",
        help="link figures/tables to their first mention (and back)")
    p.add_argument("docx")
    p.add_argument("--write", action="store_true",
                   help="save the result; without it this is a dry run")
    p.add_argument("--audit", action="store_true",
                   help="report the current state and change nothing")
    p.add_argument("--labels", metavar="WORD,...", default="",
                   help="what THIS paper calls its exhibits — "
                        "\"Figure,Table,Box\". Default: "
                        "Figure,Table and the Russian pair")
    p.set_defaults(fn=cmd_crossrefs)

    p = sub.add_parser(
        "sections",
        help="the section numbering, and every mention of it: headings "
             "run 1..N, every 'Section N' resolves (exit 1 on a breach)")
    p.add_argument("docx")
    p.set_defaults(fn=cmd_sections)

    p = sub.add_parser("inspect", help="structural summary")
    p.add_argument("docx")
    p.add_argument("--comments", action="store_true")
    p.add_argument("--revisions", action="store_true")
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser(
        "locate", help="page/line of a phrase, laid out (needs Word)")
    p.add_argument("docx")
    p.add_argument("phrase", nargs="*",
                   help="visible text to find; repeatable. NOT a bookmark "
                        "name — this searches the laid-out words")
    p.add_argument("--phrases-from", "--anchors-from", dest="phrases_from",
                   metavar="FILE",
                   help="read phrases from a file, one per line")
    p.add_argument("--revisions", action="store_true",
                   help="locate every tracked revision instead "
                        "(the redline's own pages)")
    p.add_argument("--limit", type=int, metavar="N",
                   help="stop after N revisions")
    p.add_argument("--ordered", action="store_true",
                   help="phrases are in document order: search forward from "
                        "the last hit, which is faster and picks the right "
                        "occurrence of a repeated phrase")
    p.add_argument("--json", metavar="PATH")
    p.set_defaults(fn=cmd_locate)

    p = sub.add_parser(
        "sites", help="what is AT an edit site: matches, link labels, maths")
    p.add_argument("docx")
    p.add_argument("signature", help="the visible text an edit anchors on")
    p.add_argument("--part", choices=("body", "footnotes", "endnotes"),
                   default="body")
    p.add_argument("--normalize", action="store_true",
                   help="fold Word's typographic substitutions before "
                        "matching, as para_slice(normalize=True) does")
    p.set_defaults(fn=cmd_sites)

    p = sub.add_parser(
        "api", help="the public surface by SUBJECT: docxkit api bookmark")
    p.add_argument("topic", nargs="?", default="",
                   help="a word to look for in the names and their summaries")
    p.add_argument("--signatures", action="store_true",
                   help="show each one's parameters")
    p.set_defaults(fn=cmd_api)

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
    p.add_argument("--limit", type=_word_limit, metavar="N",
                   help="with --exclude: exit 1 if the counted total "
                        "exceeds N words")
    p.add_argument("--tracked", choices=("final", "original"),
                   default="final",
                   help="which side of tracked changes to count")
    p.add_argument("--json", metavar="PATH")
    p.set_defaults(fn=cmd_count)

    p = sub.add_parser(
        "probe", help="link form, exhibit blocks, sections, run splits")
    p.add_argument("docx")
    p.add_argument("phrase", nargs="*",
                   help="phrases to show the run split for")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("lint",
                       help="structural checks (no Word needed)")
    p.add_argument("docx")
    p.add_argument("--strict", action="store_true",
                   help="fail on advisory findings too (Word opens the "
                        "file; these are wrong, not broken)")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser(
        "math", help="symbols typeset as prose instead of OMML")
    p.add_argument("docx")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if anything is found")
    p.add_argument("--in-tables", action="store_true",
                   help="count maths-only TABLE CELLS as display equations "
                        "too (a notation table is not stranded maths)")
    p.set_defaults(fn=cmd_math)

    p = sub.add_parser(
        "footnotes", help="the size the footnotes agree on, and who does not")
    p.add_argument("docx")
    p.add_argument("--check", action="store_true",
                   help="exit 1 if a footnote disagrees with the rest")
    p.set_defaults(fn=cmd_footnotes)

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
    p.add_argument("--pages", metavar="A-B", type=_page_range,
                   help="a page or an inclusive range, e.g. 3 or 1-3")
    p.set_defaults(fn=cmd_pdf)

    p = sub.add_parser("pages",
                       help="laid-out page count, or --check the render")
    p.add_argument("docx")
    # The count alone shipped two pagination defects: nothing said which
    # sheets are blank, what each one PRINTS, or which way round it is.
    p.add_argument("--sheets", action="store_true",
                   help="one row per sheet: orientation, printed number, "
                        "BLANK (renders through Word)")
    p.add_argument("--check", action="store_true",
                   help="exit 2 on a blank sheet, a numbering restart, a "
                        "gap in the printed sequence, a number printed "
                        "in the wrong corner, or a figure caption a sheet "
                        "break parted from its figure")
    p.add_argument("--expect-sheets", type=int, metavar="N",
                   help="a problem when the render has any other number "
                        "of sheets, for a paper whose length is known")
    p.add_argument("--corner", default="lower right",
                   metavar='"lower right"|any',
                   help="where the page number belongs, checked against "
                        "the RENDER; the house rule is a right-aligned "
                        'footer. "any" turns the check off')
    p.add_argument("--keep-pdf", metavar="PATH",
                   help="keep the render instead of using a temp file")
    p.set_defaults(fn=cmd_pages)

    # The defaults are `repack.DEFAULT_THRESHOLD` and
    # `repack.DEFAULT_MAX_CANDIDATES`, restated: importing them here
    # pulled lxml into every CLI start, and a test pins the two pairs.
    p = sub.add_parser(
        "repack",
        help="which sheet is mostly empty, and which exhibit's placement "
             "would fill it (renders; reports, changes nothing)")
    p.add_argument("docx")
    p.add_argument("--threshold", type=float, default=0.6,
                   help="a sheet under this share of the fullest TEXT sheet "
                        "is reported (default %(default)s)")
    p.add_argument("--max-drift", type=int, default=1,
                   help="how many sheets an exhibit may sit from the text "
                        "that first mentions it (default %(default)s)")
    p.add_argument("--max-candidates", type=int, default=8,
                   help="placements to try per under-filled sheet; each one "
                        "is a full render (default %(default)s)")
    p.add_argument("--labels", default="Figure,Table,Box",
                   help="caption words to recognise; a Box is an exhibit "
                        "only when named (default %(default)s)")
    p.set_defaults(fn=cmd_repack)

    p = sub.add_parser(
        "fit",
        help="audit the house fit rule: cantSplit, keepNext, and (with "
             "--render) what actually straddles a sheet")
    p.add_argument("docx")
    p.add_argument("--render", action="store_true",
                   help="also render and report the exhibits that STRADDLE "
                        "a boundary — the only way to catch a table too "
                        "tall to fit at all, which no property can save")
    p.add_argument("--check", action="store_true",
                   help="exit 2 when an exhibit breaks the rule, so a "
                        "paper's [verify] block can carry it")
    p.set_defaults(fn=cmd_fit)


    p = sub.add_parser(
        "revision",
        help="the single-file protocol: one manuscript, two states")
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

    r = _rev("status", cmd_revision_status,
             "truth or proposal? (exit 1 pending or unchecked, 4 stale "
             "baseline)")
    r.add_argument("--all", action="store_true",
                   help="survey every registered paper instead of one")
    r.add_argument("--scan", metavar="FOLDER", action="append",
                   help="walk FOLDER for paper.toml, register what is "
                        "found, then survey (repeatable)")

    r = _rev("doctor", cmd_revision_doctor,
             "who else in the repo selects a manuscript (exit 2 on a finding)")
    r.add_argument("--literals", action="store_true",
                   help="list the literal selections too, not just the "
                        "patterns (a spent builder naming an old "
                        "generation is the record, not a defect)")

    r = _rev("ingest", cmd_revision_ingest,
             "what the author changed since the last truth (read-only)")
    r.add_argument("--json", metavar="PATH")
    # Reporting a loss and exiting 0 is what let six of them scroll past
    # on LI7. The report stays read-only either way; only the exit code
    # changes, so this is safe to wire into a paper's own gate list.
    r.add_argument("--check", action="store_true",
                   help="exit 2 when the hand-back LOST a link, a note, "
                        "a bookmark or a comment")

    r = _rev("build", cmd_revision_build,
             "clean edit -> redline, via Word Compare")
    _build_args(r)

    r = _rev("validate", cmd_revision_validate, "run the gate ladder")
    r.add_argument("batch", nargs="?",
                   help="default: revision/build/batch.docx")
    r.add_argument("--baseline", metavar="PATH",
                   help="default: revision/build/prev.docx")
    r.add_argument("--no-word", action="store_true",
                   help="offline gates only; skips the two that need Word")
    r.add_argument("--render", metavar="ANCHOR", nargs="+", default=[],
                   help="rasterise the ACCEPTED page each anchor falls on "
                        "(needs Word and PyMuPDF): the eye gate no markup "
                        "check can make. The pages of the equations the "
                        "batch adds or changes are rendered without asking "
                        "([verify] render_math)")
    r.add_argument("--run-gates", action="store_true",
                   help="also run [verify] commands from paper.toml, as\n"
                        "spelled, from the project root (exit 5 if one fails)")
    r.add_argument("--gate-timeout", type=_seconds, default=900,
                   metavar="SECONDS", help="per gate; default 900")

    r = _rev("ship", cmd_revision_ship,
             "build then validate, in one process and one Word session")
    _build_args(r)
    r.add_argument("--no-word", action="store_true",
                   help="offline gates only for the validate half")
    r.add_argument("--render", metavar="ANCHOR", nargs="+", default=[])
    r.add_argument("--run-gates", action="store_true",
                   help="also run [verify] commands from paper.toml, as\n"
                        "spelled, from the project root (exit 5 if one fails)")
    r.add_argument("--gate-timeout", type=_seconds, default=900,
                   metavar="SECONDS", help="per gate; default 900")

    r = _rev("promote", cmd_revision_promote,
             "put a validated batch onto the manuscript")
    r.add_argument("batch", nargs="?")
    r.add_argument("--base", metavar="PATH",
                   help="the baseline the batch was built on")

    r = _rev("baseline", cmd_revision_baseline,
             "the author accepted: record the manuscript as the new truth")
    r.add_argument("--note", default="", metavar="TEXT",
                   help="what to call this round in log.md's batch table "
                        "(default: the batch filename)")
    r.add_argument("--no-log", action="store_true",
                   help="do not append a row to log.md")
    r.add_argument("--force", action="store_true",
                   help="adopt a file that still carries revisions "
                        "(migration only)")
    # `action="append"` AND the comma split, because the tool prints one
    # suggested flag per loss, each on its own line, and the form a
    # reader copies out of that list is one flag per loss. Argparse kept
    # only the last, so the command refused again with the list one
    # shorter and nothing said why — the natural reading of "I named
    # four, it now says three" is that the anchors failed to match.
    # `default=None`, not `[]`: `append` mutates the default in place
    # and it would accumulate across parses in one process.
    r.add_argument("--accept-loss", metavar="ANCHOR,...", action="append",
                   default=None,
                   help="the hand-back lost these DELIBERATELY (anchor, "
                        "note text, or kind:what); repeatable, or one "
                        "comma-separated list; naming one that is "
                        "still present is itself refused")
    r.add_argument("--repair-math", action="store_true",
                   help="put back the equation glyphs Word downgraded on "
                        "the author's save, before the loss gate runs")

    _rev("redlines", cmd_revision_redlines,
         "the kept redlines in build/redlines/: what each batch proposed")

    r = _rev("rescues", cmd_revision_rescues,
             "the undo copies promote leaves in build/rescue/")
    r.add_argument("--prune", type=int, metavar="KEEP", nargs="?", const=0,
                   help="delete all but the newest KEEP (default 0: all)")

    r = rev.add_parser("init",
                       help="scaffold the layout around a manuscript")
    r.add_argument("source", help="the paper as it stands today")
    r.add_argument("--root", metavar="DIR",
                   help="project root (default: the manuscript's folder)")
    r.add_argument("--working", metavar="PATH",
                   help="copy the manuscript here and revise THAT (default: "
                        "adopt the author's file in place, under its own "
                        "name)")
    r.add_argument("--name", metavar="NAME")
    r.add_argument("--author", default="", metavar="NAME",
                   help="who tracked changes are credited to "
                        "(new config: Revision)")
    r.add_argument("--language", default="", metavar="XX",
                   help="new config: en")
    r.add_argument("--attic", metavar="PATH",
                   help="where retired snapshots go")
    r.add_argument("--force", action="store_true",
                   help="rewrite an existing configuration")
    r.set_defaults(fn=cmd_revision_init)

    return ap


def main() -> None:
    utf8_console()
    args = build_parser().parse_args()
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
