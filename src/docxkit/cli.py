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
    docxkit pages PAPER.docx [--sheets] [--check]

and the single-file revision protocol, which finds its own paths in
``revision/paper.toml`` and so takes almost no arguments::

    docxkit revision status [--all] [--scan FOLDER]
    docxkit revision doctor
    docxkit revision ingest [--check] [--json R.json]
    docxkit revision build REVISED.docx [--out PATH] [--keep-math]
    docxkit revision validate [BATCH.docx] [--no-word] [--render ANCHOR...]
    docxkit revision ship REVISED.docx   # both, one Word session
    docxkit revision promote [BATCH.docx]
    docxkit revision baseline [--force] [--accept-loss A,...]
    docxkit revision rescues [--prune KEEP]
    docxkit revision init PAPER.docx [--root DIR] [--name NAME] [--working P]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
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
    from .compare import compare, render
    # Both sides checked FIRST. `compare.load` reads only the text parts
    # it knows, so two files that are not manuscripts compared as two
    # empty documents and reported no differences — and `--expect-clean`
    # in CI passed on them. A gate that cannot fail on garbage input is
    # not a gate.
    for side in (args.built, args.edited):
        _package(side)
    rep = compare(args.built, args.edited)
    if args.json:
        _write_json(args.json, rep)
    # compare is a verbatim port and untyped; render returns the exit code
    return int(render(rep, args.expect_clean))


def cmd_citations(args: argparse.Namespace) -> int:
    from .citations import check_citations
    _package(args.docx)          # a zip with no document.xml died on KeyError
    found = check_citations(args.docx, later_mentions=args.later_mentions,
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
    parts = _package(args.docx)
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
    print(repair_plan(_package(args.docx)))
    return 0


def cmd_refstyle(args: argparse.Namespace) -> int:
    """Citation and reference FORMAT, against the house author-date style.

    ``citations`` audits the links; this audits the writing — initials,
    "and" not "&", "(2020).", en-dashes, alphabetical order, and the
    cited/listed cross-check.
    """
    from .refstyle import CHICAGO, HOUSE, audit, convert, layout, refile
    style = CHICAGO if args.chicago else HOUSE
    parts = _package(args.docx)
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

    parts = _package(args.docx)
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
        print(name)
        for key in ("linked", "unlinked", "caption_only", "mention_only",
                    "dangling"):
            found = state[key]
            print(f"  {key:<16} {len(found):>3}"
                  f"{'  ' + ', '.join(found) if found else ''}")
        # One finding per line: these carry a sentence, not a name, and
        # `misnamed` was computed and never printed at all — a check
        # nobody can read is a check nobody runs.
        for key in ("misnamed", "misplaced_anchor"):
            print(f"  {key:<16} {len(state[key]):>3}")
            for line in state[key]:
                print(f"    {line}")
        return 1 if state["dangling"] or state["misplaced_anchor"] else 0

    linked, report = crossrefs.link(doc, other_parts=others, labels=labels)
    print(name)
    print("  " + report.format().replace("\n", "\n  "))

    if not args.write:
        print("  (dry run - pass --write to save)")
        return 0 if report.complete else 1

    if not _write_document(args.docx, parts, linked, "pre_crossrefs"):
        return 1
    return 0 if report.complete else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    parts = _package(args.docx)
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
    parts = _package(args.docx)
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
    parts = _package(args.docx)
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


def _package(path: str) -> dict[str, bytes]:
    """Every part of a manuscript, or a refusal a reader can act on.

    `read_parts` already turns a missing file or a non-zip into a
    `PackageError` that ``main`` prints as one line — but `inspect`,
    `text` and `figures` opened the zip themselves and handed back a raw
    `BadZipFile` traceback instead. A zip that is not a Word document
    reached even further, dying on a `KeyError` naming a part the user
    never mentioned.
    """
    from .package import read_parts
    parts = read_parts(path)
    if DOCUMENT not in parts:
        raise PackageError(
            f"{Path(path).name} is a zip, but not a Word document: "
            f"it has no {DOCUMENT}")
    return parts


def _write_back(path: str, parts: dict[str, bytes], tag: str) -> str:
    """Backup, then save — the one way an in-place command writes."""
    from .package import backup, write_docx
    kept = backup(path, tag=tag)
    write_docx(path, parts)
    return kept.name


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

    parts = _package(args.docx)
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
    counts = count(_package(args.docx), view=args.tracked)
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
    doc = _package(args.docx)[DOCUMENT].decode("utf-8")
    findings = prose_math(doc)
    vocabulary = "".join(sorted(document_symbols(doc)))
    print(f"{Path(args.docx).name}  (math vocabulary: "
          f"{vocabulary or 'none — the document typesets no symbols'})")

    # A separate question from prose-math, and invisible to every other
    # check: a bare m:oMath is INLINE to Word, and the house rule is
    # display + centred. Word promotes a lone one on save SOMETIMES,
    # which is why it has to be set rather than trusted.
    displays = display_equations(doc)
    stranded = inline_display(doc)
    at = {m.start(): i for i, m in enumerate(P_RE.finditer(doc), 1)}
    print(f"  {len(displays)} display equation(s), "
          f"{len(stranded)} still in INLINE mode")
    for m in stranded:
        print(f"     ¶{at[m.start()]:<5} {tokens(m.group(0))[:60]!r}")
    if stranded:
        print("     -> equations.display(para) wraps them in m:oMathPara")

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
    from .figures import alt_texts
    doc = _package(args.docx)[DOCUMENT].decode("utf-8")
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


def cmd_footnotes(args: argparse.Namespace) -> int:
    """What the footnotes are set in, and which one disagrees."""
    from .footnotes import fonts, sizes
    parts = _package(args.docx)
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
    from .hygiene import smarten

    parts = _package(args.docx)
    doc = parts[DOCUMENT].decode("utf-8")
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

    parts = _package(args.docx)
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
    _package(args.docx)          # a zip with no document.xml died on KeyError
    print(probe(args.docx, tuple(args.phrase)).report())
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Structural checks for the markup Word refuses to open, and the
    findings it opens fine and reads wrongly."""
    from .lint import audit_parts, lint_parts
    parts = _package(args.docx)
    problems = lint_parts(parts)
    advisory = audit_parts(parts)
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


def cmd_pages(args: argparse.Namespace) -> int:
    """The page COUNT, or -- with --check -- what the render looks like."""
    if not (args.check or args.sheets):
        from .word import page_count
        print(page_count(args.docx))
        return 0

    from .pages import problems, sheets
    rows = sheets(args.docx, keep_pdf=args.keep_pdf)
    print(f"{len(rows)} sheet(s)")
    for row in rows:
        print(f"  {row}")
    corner = getattr(args, "corner", "lower right")
    found = problems(rows, corner=None if corner == "any" else corner)
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


#: what the two read-only commands print when Word held the file
_SNAPSHOT_NOTE = (
    "  read from a SNAPSHOT: the author has the file open in Word, so this\n"
    "  describes the moment the copy was taken, not whatever they have "
    "typed since.")


#: The verdict column, widest first so the rows line up, and ordered by
#: what it costs to ignore: a proposal is somebody waiting on the author.
_VERDICT_RANK = {"unreadable": 0, "missing": 1, "PROPOSAL": 2, "stale": 3,
                 "truth": 4}


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

    Exit code is the worst state found, on the same scale one paper
    uses: 1 if anything is a proposal, 4 if a settled paper's baseline
    has drifted, 0 when every paper is truth on a current baseline. A
    row that could not be read exits 2 — it is neither of the states
    the protocol has, and reporting it as truth would be a lie.
    """
    from .revision import registered, registry_path, scan, survey
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
    rows.sort(key=lambda r: (_VERDICT_RANK.get(r.verdict, 9), r.name.lower()))
    for row in rows:
        print(_survey_row(row))
    worst = min((_VERDICT_RANK.get(r.verdict, 9) for r in rows), default=4)
    print(f"\n  {len(rows)} paper(s) · {registry_path()}")
    if worst <= 1:
        return 2
    return {2: 1, 3: 4}.get(worst, 0)


def cmd_revision_status(args: argparse.Namespace) -> int:
    """Truth or proposal? The one question the layout answers by itself.

    Exit 0 means both: settled AND built on a current baseline. A truth
    whose baseline has drifted exits 4, not 0 — the whole point of a
    non-zero status is to let a script refuse to start a batch, and a
    batch on a stale base is refused by `promote` only after a Word
    Compare has been paid for.
    """
    if getattr(args, "all", False) or getattr(args, "scan", None):
        return cmd_revision_survey(args)
    from .revision import drift, state
    paper = _paper(args)
    print(f"{paper.name}\n  {paper.working}")
    st = state(paper.working)
    if st.from_snapshot:
        print(_SNAPSHOT_NOTE)
    _show_state("working", st)
    if not paper.prev.exists():
        print("  prev      MISSING - no baseline to compare or reject "
              "against; run `docxkit revision baseline`")
        return 0 if st.is_truth else 1
    _show_state("prev", state(paper.prev))
    # Only worth asking of a settled file: while a proposal is pending
    # the two are SUPPOSED to differ, and saying so every time is how a
    # warning stops being read.
    stale = drift(paper.working, paper.prev) if st.is_truth else []
    if stale:
        print(f"\n  ** baseline STALE: {_summarize(stale)} differ(s) **")
        print(f"     Both files count 0 pending, and they are not the same "
              f"paper -\n     prev.docx is not what {paper.working.name} "
              f"grew out of. Building a batch\n     on it compares against "
              f"the wrong base. First:\n"
              "       docxkit revision ingest     (what changed, read-only)"
              "\n       docxkit revision baseline   (record it as the new "
              "truth)")
        return 4
    return 0 if st.is_truth else 1


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

    patterns = [d for d in found if d.kind == "pattern"]
    literals = [d for d in found if d.kind == "literal"]

    # PATTERNS in full, literals counted. The first version printed all
    # of them and AFI answered with 134 lines, three of which mattered;
    # about 130 were spent builders and a shipped replication package,
    # which under the forward-only rule are the record rather than a
    # defect. An unreadable gate is one people switch off.
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
        print(f"\n== LOST ({len(report.lost)}) ==")
        for loss in report.lost:
            print("   ", loss)
        print("   Word does this silently when it collapses a paragraph "
              "to make an edit;\n   the words all survive, so no content "
              "layer above shows it. `revision baseline`\n   will refuse "
              "until these are restored or named with --accept-loss.")

    if report.relabelled:
        print(f"\n== RE-LABELLED ({len(report.relabelled)}) ==")
        for change in report.relabelled:
            print("   ", change)
        print("   The anchors are intact and still linked, so nothing is "
              "lost and\n   `revision baseline` does not refuse: an author "
              "editing the visible\n   text of a citation is an ordinary "
              "edit, not damage.")

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
                   allow_stale_baseline=args.allow_stale_baseline,
                   resolve_math=not args.keep_math,
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
    with shared_session():
        if (code := cmd_revision_build(args)) != 0:
            # Third abort path, and the reason `_skipped_gates` is
            # called from each return rather than from one exit: every
            # new one has to remember. `ship` takes --run-gates too.
            return _skipped_gates(args, code)
        print()
        args.batch = str(Path(args.out) if args.out else _paper(args).batch)
        args.baseline = None
        return cmd_revision_validate(args)


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


def _paper_gates(args: argparse.Namespace, code: int) -> int:
    """The paper's OWN gates, after the ladder — listed, or run.

    Separate from the ladder in the output as well as in the code,
    because they answer different questions: everything above is about
    the BATCH, and these are about the paper. Listing them when they
    were not run is deliberate — a list of unrun checks is a reminder,
    and silence reads as "nothing to run".
    """
    paper = _paper(args)
    if not paper.gates:
        if getattr(args, "run_gates", False):
            print("\n== the paper's own gates ==  none listed in paper.toml")
        return code
    if not getattr(args, "run_gates", False):
        print(f"\n== the paper's own gates ==  {len(paper.gates)} listed, "
              f"NOT run (--run-gates)")
        for command in paper.gates:
            print(f"   · {command}")
        return code

    from .revision import run_gates
    print(f"\n== the paper's own gates ==  {len(paper.gates)}, from the "
          f"project root")
    failed = 0
    # A heartbeat, because `capture_output` swallows everything the gate
    # prints: a 12-minute pytest suite under a 900s timeout showed an
    # empty terminal, indistinguishable from a hang.
    def say(line: str) -> None:
        print(f"   · {line.removeprefix('gate: ')}", flush=True)

    for gate in run_gates(paper, timeout=args.gate_timeout, progress=say):
        print(f"     [{gate.verdict}] {gate.seconds}s")
        if gate.ok:
            continue
        failed += 1
        for line in gate.output.splitlines():
            print(f"        {line}")
    if not failed:
        return code
    print(f"\n{failed} of {len(paper.gates)} of the paper's gates failed.")
    # 5, not 1: "the redline is unshippable" and "the manuscript is
    # wrong" want different responses, and a script that only knows
    # non-zero cannot tell them apart.
    return code or 5


def cmd_revision_validate(args: argparse.Namespace) -> int:
    """The gate ladder. Gate 5 is the one that proves reviewability."""
    from . import guard as _g
    from .revision import validate
    paper = _paper(args)
    target = Path(args.batch) if args.batch else paper.batch
    base = Path(args.baseline) if args.baseline else paper.prev
    report = validate(target, base if base.exists() else None,
                      use_word=not args.no_word)

    print(f"{target.name}")
    if report.built_on_this_baseline is False:
        print(f"== baseline ==  {target.name} was NOT built on {base.name}")
        print(f"   it says it was built on {report.built_on[:16]}, and "
              f"{base.name} is {_g.sha256(base)[:16]}")
        print("   every gate below compares the two, so the whole ladder "
              "would describe a batch nobody is working on. Rebuild on "
              "this baseline — or, if the last build was REFUSED, delete "
              "the stale batch first.")
        code = _skipped_gates(args, 2)
        print("\nVERDICT: FAIL")
        return code
    print("== lint ==", "clean" if not report.lint
          else f"{len(report.lint)} problem(s)")
    for problem in report.lint:
        print("   FAIL:", problem)
    if report.lint:
        print("\nABORT before Word - fix lint first.")
        return _skipped_gates(args, 2)
    print("== counts ==", report.counts)
    if report.word_opened is False:
        print("== Word ==  FAILED (corrupted):", report.word_error)
        return _skipped_gates(args, 3)
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
        print("   Word's Compare rebuilds rather than annotates and drops "
              "what it will not carry; promote would copy this batch over "
              "the manuscript, so the part goes with it. Restore it with "
              "docxkit.hygiene.restore_parts and rebuild.")
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
            for note in report.moved_footnotes:
                print(f"   footnote {note}: the whole note is one "
                      f"insertion with no deletion — its REFERENCE moved, "
                      f"so rejecting empties it")
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
    if args.render:
        from .revision import render_accepted

        print(f"\n== render ==  {len(args.render)} anchor(s), accepted view")
        for anchor, png in render_accepted(target, args.render).items():
            print(f"   {anchor!r} -> {png.name}" if png
                  else f"   {anchor!r}: on no page — check the wording")
    # The paper's own gates are listed (or run) by `_paper_gates` below,
    # in ONE section rather than two: this used to print its own "run
    # these too" list, so with --run-gates the reader got the commands
    # once as a reminder and again with their verdicts.
    # The verdict is printed AFTER the paper's gates and reflects them.
    # It used to print here, before `_paper_gates` ran, so a run whose
    # paper gates failed said "VERDICT: PASS" and then exited 5 — and
    # both the log template and the README treat that line as the
    # answer.
    code = _paper_gates(args, 0 if report.ok else 1)
    print("\nVERDICT:", "PASS" if code == 0 else "FAIL")
    return code


def cmd_revision_promote(args: argparse.Namespace) -> int:
    """Put a validated batch onto the manuscript, lock- and hash-guarded."""
    from .revision import promote
    paper = _paper(args)
    report = promote(paper, args.batch, args.base)
    print(f"promoted {report.promoted.name} -> {report.onto.name}")
    print(f"rescue copy of the previous live file: "
          f"{report.rescue.relative_to(paper.root)}")
    if report.redline is not None:
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


def cmd_revision_baseline(args: argparse.Namespace) -> int:
    """The author accepted: record the manuscript as the new truth."""
    from .revision import baseline
    paper = _paper(args)
    accepted = tuple(t.strip() for t in args.accept_loss.split(",")
                     if t.strip())
    from .revision import log_batch, verdict
    recorded = verdict(paper) if not args.no_log else None
    written = baseline(paper, force=args.force, accept_loss=accepted,
                       repair_math=args.repair_math, log=False)
    row = log_batch(paper, recorded, args.note) if recorded else None
    for token in accepted:
        print(f"  accepted loss: {token}")
    print(f"baseline updated: {written}")
    if recorded is not None and row:
        print(f"\nlogged: {row.strip()}")
    elif recorded is not None:
        print("\nlog.md has no batch table to append to — record this "
              "round by hand:\n"
              f"  {recorded.summary()} · {recorded.outcome}")
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
        if saved:
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
                        "gap in the printed sequence, or a number printed "
                        "in the wrong corner")
    p.add_argument("--corner", default="lower right",
                   metavar='"lower right"|any',
                   help="where the page number belongs, checked against "
                        "the RENDER; the house rule is a right-aligned "
                        'footer. "any" turns the check off')
    p.add_argument("--keep-pdf", metavar="PATH",
                   help="keep the render instead of using a temp file")
    p.set_defaults(fn=cmd_pages)

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
             "truth or proposal? (exit 1 pending, 4 stale baseline)")
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
    r.add_argument("revised", help="the edited CLEAN copy of prev.docx")
    r.add_argument("--out", metavar="PATH",
                   help="default: revision/build/batch.docx")
    r.add_argument("--allow-math-resolve", action="store_true",
                   help="ship equations Word baked in unreviewable "
                        "(they almost never are meant to be)")
    r.add_argument("--allow-stale-baseline", action="store_true",
                   help="build even though prev.docx is no longer what the "
                        "manuscript grew out of (the redline would show the "
                        "author's own edits as proposals)")
    # The other answer to the same refusal, and the better one: keep the
    # equation revisions TRACKED instead of accepting them. Measured on
    # LI7 (2026-08-15) — the Flat OPC route serialized 1870 revisions
    # with the math kept, reject-all included.
    r.add_argument("--keep-math", action="store_true",
                   help="leave equation revisions TRACKED rather than "
                        "accepting them (try this before "
                        "--allow-math-resolve)")
    r.add_argument("--allow-pending-baseline", action="store_true",
                   help="absorb the baseline's pending revisions "
                        "deliberately")
    # The staleness refusal has named this flag since it was written,
    # and `build --help` did not list it: the one way out the reader was
    # told about was `error: unrecognized arguments: --force`. The
    # backup is taken either way, so the previous batch survives.
    r.add_argument("--force", action="store_true",
                   help="rebuild over a batch.docx that was edited since "
                        "docxkit wrote it (a backup is taken first)")

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
                        "check can make")
    r.add_argument("--run-gates", action="store_true",
                   help="also run [verify] commands from paper.toml, as\n"
                        "spelled, from the project root (exit 5 if one fails)")
    r.add_argument("--gate-timeout", type=_seconds, default=900,
                   metavar="SECONDS", help="per gate; default 900")

    r = _rev("ship", cmd_revision_ship,
             "build then validate, in one process and one Word session")
    r.add_argument("revised", help="the edited CLEAN copy of prev.docx")
    r.add_argument("--out", metavar="PATH",
                   help="default: revision/build/batch.docx")
    r.add_argument("--allow-math-resolve", action="store_true")
    r.add_argument("--keep-math", action="store_true")
    r.add_argument("--allow-pending-baseline", action="store_true")
    # `ship` re-declares `build`'s flags rather than sharing them, so a
    # flag added to one and not the other is an AttributeError on every
    # ship — which is how this line came to be written.
    r.add_argument("--allow-stale-baseline", action="store_true")
    r.add_argument("--force", action="store_true")
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
    r.add_argument("--accept-loss", metavar="ANCHOR,...", default="",
                   help="the hand-back lost these DELIBERATELY (anchor, "
                        "note text, or kind:what); naming one that is "
                        "still present is itself refused")
    r.add_argument("--repair-math", action="store_true",
                   help="put back the equation glyphs Word downgraded on "
                        "the author's save, before the loss gate runs")

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
