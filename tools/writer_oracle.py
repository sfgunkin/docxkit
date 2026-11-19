#!/usr/bin/env python
"""Old-vs-new oracle for the WRITERS, over real manuscripts.

    python tools/writer_oracle.py [ROOT ...] [--base REV] [--limit N]
                                  [--probe NAME ...] [--show K]
                                  [--expect-same]

`sweep.py` runs the READERS over the corpus; a writer change had nothing
that runs it across real documents against the commit before it. Each
fix hand-rolled its own: the 2026-09-24 review wrote `real_insert.py`
(insert before every hoisted head bookmark, count the stranded) and
2026-09-25 wrote `cell_probe.py` (rewrite every cell with its own text
under HEAD and under the fix). Both found what the unit tests could not —
the first `insert_before` fix had been checked on captions only, and 220
of 327 reference-entry bookmarks were still stranded.

The base (default ``HEAD``) is extracted with ``git archive`` into a
temporary directory and the working tree's ``src`` is the other side;
each side runs the same PROBES in its own interpreter, over the same
strided sample (`sweep.sample`, ``DOCXKIT_CORPUS`` / ``--limit``), and
the answers are diffed key by key. Every probe is a deterministic write
whose answer should not change unless the writer did:

* ``set_cell`` — every cell rewritten with its own text: the refusal, or
  each line's runs as (text, superscript, italic).
* ``insert_before`` — a probe paragraph inserted before every paragraph
  that a run of body-level markers precedes: which bookmark names end up
  in front of the probe (stranded) rather than behind it.
* ``house`` — `tables.house` on every table: whether the visible text
  survived, the count of each property the pass must not drop (italic,
  bold, alignment, keep-with-next, sub/superscript) before -> after, and
  the table's hash.
* ``crossrefs`` — `crossrefs.link` on the document: each caption
  paragraph's hash afterwards, and the audit's buckets before and after.
* ``link_all`` — `citations.link_all` on the package: every mention it
  linked and every one it skipped, one key each, and the body's hash.
* ``replace`` — `edit.replace_in_para` and `replace_keeping_links`
  across run seams: each run's text and properties afterwards, which is
  where a replacement given the wrong run's look shows (added
  2026-11-17, BACKLOG S2).

``house``, ``crossrefs`` and ``link_all`` were added 2026-11-14 (BACKLOG S4: "probes two writers").
The batch that changed those writers had to measure them with a scratch
probe, and that probe caught a false positive before commit — 32 new
`misplaced_anchor` findings, all on a cached soft-break marker.

Read-only: every manuscript is read into memory, nothing is written.
Differences are REPORTED, not judged — a fix is supposed to change
something; ``--expect-same`` makes any difference exit 1, for a
refactor that claims to change nothing. Exit 3 is SKIPPED (no corpus),
as `sweep.py` has it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKIPPED = 3
PROBE_PARA = "<w:p><w:r><w:t>WRITER ORACLE PROBE</w:t></w:r></w:p>"

Answers = dict[str, str]
Package = dict[str, bytes]
DOCUMENT = "word/document.xml"


# ---------------------------------------------------------------- probes --
# Run in the WORKER, after `sys.path` names the side's own `src`. They
# import only names both sides have had for months, so an old base can
# answer the same questions.


def _runs_signature(xml: str) -> str:
    from docxkit._xml import PARA_RE, RUN_RE, visible_text  # noqa: PLC0415
    lines = []
    for p in PARA_RE.finditer(xml):
        runs = []
        for r in RUN_RE.finditer(p.group(0)):
            text = visible_text(r.group(0))
            if text.strip():
                run = r.group(0)
                runs.append([text, 'w:val="superscript"' in run,
                             bool(re.search(r'<w:i(?: w:val="(?:1|true)")?/>',
                                            run))])
        lines.append(runs)
    return json.dumps(lines, ensure_ascii=False)


def probe_set_cell(xml: str) -> Answers:
    """Every cell rewritten with its own text."""
    from docxkit import tables  # noqa: PLC0415
    from docxkit._xml import element_spans  # noqa: PLC0415
    out: Answers = {}
    for t in tables.read_all(xml):
        for r, row in enumerate(t.rows):
            for c, text in enumerate(row):
                key = f"table {t.index} row {r} cell {c}"
                try:
                    new = tables.set_cell(xml, t, r, c, text)
                except Exception as exc:
                    out[key] = (f"refused: {type(exc).__name__}: "
                                f"{str(exc)[:60]}")
                    continue
                seg = new[t.start:t.end + len(new) - len(xml)]
                trs = element_spans(seg, "tr")
                if r >= len(trs):
                    out[key] = "row not found"
                    continue
                tr = seg[trs[r][0]:trs[r][1]]
                tcs = element_spans(tr, "tc")
                out[key] = (_runs_signature(tr[tcs[c][0]:tcs[c][1]])
                            if c < len(tcs) else "cell not found")
    return out


_GAP_RE = re.compile(
    r"</w:p>((?:\s*<w:(?:bookmarkStart|bookmarkEnd|commentRangeStart"
    r"|commentRangeEnd|permStart|permEnd|proofErr)\b[^<>]*/>)+)\s*(?=<w:p\b)")
_NAME_RE = re.compile(r'<w:bookmarkStart\b[^>]*w:name="([^"]+)"')


def probe_insert_before(xml: str) -> Answers:
    """A probe paragraph before each paragraph a marker run precedes."""
    from docxkit._xml import PARA_RE, visible_text  # noqa: PLC0415
    from docxkit.body import insert_before  # noqa: PLC0415
    out: Answers = {}
    for gap in _GAP_RE.finditer(xml):
        names = _NAME_RE.findall(gap.group(1))
        para = PARA_RE.match(xml, gap.end())
        if not names or para is None:
            continue
        sig = visible_text(para.group(0)).strip()[:60]
        if len(sig) < 12:
            continue
        key = f"before {sig[:40]!r}"
        try:
            new = insert_before(xml, sig, PROBE_PARA)
        except Exception as exc:
            out[key] = f"refused: {type(exc).__name__}"
            continue
        at = new.index(PROBE_PARA)
        stranded = sorted(n for n in names
                          if new.find(f'w:name="{n}"') < at)
        out[key] = f"stranded {stranded}" if stranded else "kept"
    return out


def _sha(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha1(data).hexdigest()[:12]


#: What `tables.house` must leave alone: it sets face, size and spacing,
#: and on 911 corpus tables its old wholesale replace dropped 72,484
#: alignments and 35,337 italics with every unit test green.
_KEPT_PROPS = {
    "italic": r'<w:i(?:\s+w:val="(?:1|true|on)")?\s*/>',
    "bold": r'<w:b(?:\s+w:val="(?:1|true|on)")?\s*/>',
    "jc": r"<w:jc\b",
    "keepNext": r"<w:keepNext\b",
    "vertAlign": r"<w:vertAlign\b",
}


def _prop_counts(xml: str) -> dict[str, int]:
    return {k: len(re.findall(p, xml)) for k, p in _KEPT_PROPS.items()}


def probe_house(parts: Package) -> Answers:
    """`tables.house` on every table: text kept, properties kept, hash."""
    from docxkit import tables  # noqa: PLC0415
    from docxkit._xml import visible_text  # noqa: PLC0415
    xml = parts[DOCUMENT].decode("utf-8")
    out: Answers = {}
    for t in tables.read_all(xml):
        key = f"table {t.index}"
        body = xml[t.start:t.end]
        try:
            new, _ = tables.house(xml, t)
        except Exception as exc:
            out[key] = f"refused: {type(exc).__name__}: {str(exc)[:60]}"
            continue
        seg = new[t.start:t.end + len(new) - len(xml)]
        before, after = _prop_counts(body), _prop_counts(seg)
        props = " ".join(f"{k} {before[k]}->{after[k]}" for k in before)
        text = "same" if visible_text(seg) == visible_text(body) else "CHANGED"
        out[key] = f"text {text}; {props}; sha {_sha(seg)}"
    return out


#: The audit buckets a link pass is meant to move, or must not.
_XREF_BUCKETS = ("linked", "unlinked", "dangling", "misplaced_anchor")


def probe_crossrefs(parts: Package) -> Answers:
    """`crossrefs.link`: each caption afterwards, the audit both sides."""
    from docxkit import crossrefs  # noqa: PLC0415
    xml = parts[DOCUMENT].decode("utf-8")
    new, _ = crossrefs.link(xml)
    out: Answers = {}
    for cap in crossrefs.find_captions(new):
        out[f"caption {cap.name}"] = _sha(new[cap.start:cap.end])
    for side, doc in (("before", xml), ("after", new)):
        found = crossrefs.audit(doc)
        for bucket in _XREF_BUCKETS:
            out[f"audit {side} {bucket}"] = str(len(found.get(bucket, ())))
    return out


def probe_link_all(parts: Package) -> Answers:
    """`citations.link_all`: one key per mention linked or skipped."""
    from docxkit.citations import link_all  # noqa: PLC0415
    copy = dict(parts)
    report = link_all(copy)
    out: Answers = {"body": _sha(copy[DOCUMENT])}
    for item in report.linked:
        out[f"linked {item}"[:120]] = "yes"
    for item in report.backlinked:
        out[f"back-linked {item}"[:120]] = "yes"
    for item in report.skipped:
        out[f"skipped {item}"[:120]] = "yes"
    return out


def probe_link_more(parts: Package) -> Answers:
    """`crossrefs.link_more` after `link`: the mentions it linked, each
    marker it re-homed, and the same with the markers held in place."""
    from docxkit import crossrefs  # noqa: PLC0415
    from docxkit.lint import lint_parts  # noqa: PLC0415
    xml, _ = crossrefs.link(parts[DOCUMENT].decode("utf-8"))
    new, counts = crossrefs.link_more(xml)
    out: Answers = {"body": _sha(new)}
    out.update({f"count {k}"[:120]: str(n) for k, n in counts.items()})
    # Held in place, only where holding CHANGED something: a base older
    # than `rehome=` has no such switch, and a key on one side only is a
    # difference that is not one.
    try:
        held, held_counts = crossrefs.link_more(xml, rehome=False)
    except TypeError:
        held, held_counts = new, counts
    if held != new:
        out["held body"] = _sha(held)
    out.update({f"held {k}"[:120]: str(n) for k, n in held_counts.items()
                if counts.get(k) != n})
    for finding in lint_parts({**parts, DOCUMENT: new.encode("utf-8")}):
        out[f"lint {finding}"[:120]] = "yes"
    return out


def probe_link_rest(parts: Package) -> Answers:
    """`citations.link_rest` after `link_all`: one key per mention."""
    from docxkit.citations import link_all, link_rest  # noqa: PLC0415
    copy = dict(parts)
    link_all(copy)
    report = link_rest(copy)
    out: Answers = {"body": _sha(copy[DOCUMENT])}
    for item in report.linked:
        out[f"linked {item}"[:120]] = "yes"
    for item in report.unmatched:
        out[f"unmatched {item}"[:120]] = "yes"
    for item in report.skipped:
        out[f"skipped {item}"[:120]] = "yes"
    return out


def probe_renumber(parts: Package) -> Answers:
    """`renumber.shift` of every Table and Figure from 1 by one.

    The renumbering a revision does when it inserts Table 1: what moved,
    and every mention it refused as a range or a list rather than
    half-shifting it. That refusal is where "Table 23, 0.217" used to be
    left behind (Month_of_birth R12).
    """
    from docxkit import renumber  # noqa: PLC0415
    xml = parts[DOCUMENT].decode("utf-8")
    out: Answers = {}
    for label in ("Table", "Figure"):
        new, report = renumber.shift(xml, label, frm=1, by=1)
        out[f"{label} counts"] = (
            f"mentions {report.mentions} bookmarks {report.bookmarks} "
            f"anchors {report.anchors} fields {report.fields}")
        out[f"{label} body"] = _sha(new)
        for snippet in report.flagged:
            out[f"{label} flagged {snippet}"[:120]] = "yes"
    return out


def probe_builders(parts: Package) -> Answers:
    """The property elements the writers stamp into a document.

    `tables.house_rpr` is public and papers build cells with it, but no
    document writer above calls it any more, so a change to it — the
    bold that sat ahead of `w:rFonts`, out of schema order — reached no
    probe. Constant per side, so it answers once, on the first document.
    """
    from docxkit import tables  # noqa: PLC0415
    del parts
    return {f"house_rpr {bold=}": tables.house_rpr("Arial Narrow", 10,
                                                   bold=bold)
            for bold in (False, True)}


def probe_house_apply(parts: Package) -> Answers:
    """`house.apply` on the package: what it set, and the audit after."""
    from docxkit import house  # noqa: PLC0415
    copy = dict(parts)
    # The figure rule is opt-in, so the probe opts in; a base older than
    # the rule has no such field and runs the house it had.
    # spelled as an attribute, not getattr(…, "FIGURE_SIZE"): a string is
    # invisible to `oracle_reach`, which would call the constant unreached
    size = (house.FIGURE_SIZE if hasattr(house, "FIGURE_SIZE")
            else (6.0, 4.0))
    try:
        rules = house.Rules(figure_size=size)
    except TypeError:
        rules = house.HOUSE
    report = house.apply(copy, rules)
    out: Answers = {
        "report": (f"captions {report.captions} notes {report.notes} "
                   f"figure_notes {report.figure_notes} runs {report.runs}"),
        "body": _sha(copy[DOCUMENT]),
    }
    # Only when some were: a base older than the figure rule has no count
    # at all, and "n/a" against "0" is a difference that is not one.
    if hasattr(report, "figures") and report.figures:
        out["figures resized"] = str(report.figures)
    for finding in house.audit(copy, rules):
        out[f"after {finding}"[:120]] = "yes"
    return out


def probe_table_layout(parts: Package) -> Answers:
    """`booktabs`, `fit_columns` and `clone_row` on every table."""
    from docxkit import tables  # noqa: PLC0415
    xml = parts[DOCUMENT].decode("utf-8")
    out: Answers = {}
    writers: tuple[tuple[str, Callable[[Any], str]], ...] = (
        ("booktabs", lambda t: tables.booktabs(xml, t)[0]),
        ("fit_columns", lambda t: tables.fit_columns(xml, t)[0]),
        ("clone_row", lambda t: tables.clone_row(xml, t, 0)),
        ("keep_together", lambda t: tables.keep_together(xml, t)[0]))
    for t in tables.read_all(xml)[:12]:
        for name, write in writers:
            key = f"table {t.index} {name}"
            try:
                new = write(t)
            except Exception as exc:
                out[key] = f"refused: {type(exc).__name__}: {str(exc)[:60]}"
                continue
            out[key] = _sha(new[t.start:t.end + len(new) - len(xml)])
    return out


def probe_footnotes(parts: Package) -> Answers:
    """`footnotes.prune_orphans`, then `renumber.footnotes`."""
    from docxkit import footnotes, renumber  # noqa: PLC0415
    copy = dict(parts)
    out: Answers = {}
    for orphan in footnotes.prune_orphans(copy):
        out[f"pruned {orphan}"[:120]] = "yes"
    moved = renumber.footnotes(copy)
    out["renumbered"] = str(sorted(moved.items()))[:200]
    for part in ("word/document.xml", "word/footnotes.xml",
                 "word/endnotes.xml"):
        if part in copy:
            out[f"sha {part}"] = _sha(copy[part])
    return out


#: A comment's timestamp is the clock's, so the two sides never agree on
#: it; everything else a comment writer puts down must.
_DATE_RE = re.compile(r'\bw:date="[^"]*"')
_COMMENT_PARTS = ("word/document.xml", "word/comments.xml",
                  "word/commentsExtended.xml")


def _stamped(parts: Package, out: Answers, label: str) -> None:
    for part in _COMMENT_PARTS:
        if part in parts:
            text = _DATE_RE.sub("", parts[part].decode("utf-8"))
            out[f"{label} sha {part}"] = _sha(text)


def _refusal(exc: Exception) -> str:
    return f"refused: {type(exc).__name__}: {str(exc)[:60]}"


def probe_comments(parts: Package) -> Answers:
    """The comment writers: annotate, annotate_blocks, reclassify, add_at,
    and `hygiene.dedupe_comments`. Each on its own copy."""
    from docxkit import comments, hygiene, revisions  # noqa: PLC0415
    out: Answers = {}
    xml = parts[DOCUMENT].decode("utf-8")

    def attempt(label: str, write: Callable[[Package], object]) -> None:
        copy = dict(parts)
        try:
            out[label] = str(write(copy))[:200]
        except Exception as exc:
            out[label] = _refusal(exc)
            return
        _stamped(copy, out, label)

    attempt("annotate", lambda p: comments.annotate(p, lambda ctx: "probe"))
    attempt("reclassify",
            lambda p: comments.reclassify(p, lambda ctx: "probe"))
    attempt("dedupe_comments", hygiene.dedupe_comments)
    spans = revisions.spans(xml)
    attempt("annotate_blocks", lambda p: comments.annotate_blocks(
        p, [(range(len(spans)), "probe")], author="Oracle", initials="O",
        date="2026-01-01T00:00:00Z", partial=True))
    def add_at(anchor: str) -> Callable[[Package], object]:
        return lambda p: comments.add_at(p, anchor, "probe")

    for i, anchor in enumerate(_anchors(xml, 3)):
        attempt(f"add_at {i}", add_at(anchor))
    return out


def _anchors(xml: str, n: int) -> list[str]:
    """Up to `n` body paragraphs' opening words, each unique in the body."""
    from docxkit._xml import PARA_RE, visible_text  # noqa: PLC0415
    texts = [visible_text(m.group(0)) for m in PARA_RE.finditer(xml)]
    body = "\n".join(texts)
    picked: list[str] = []
    step = max(1, len(texts) // (n * 3 or 1))
    for text in texts[::step]:
        sig = text.strip()[:30]
        if len(text.strip()) >= 60 and body.count(sig) == 1:
            picked.append(sig)
        if len(picked) == n:
            break
    return picked


def probe_paragraphs(parts: Package) -> Answers:
    """`paragraph.split`, `merge`, `drop` and `footnotes.add` on a few
    body paragraphs, each on its own copy."""
    from docxkit import footnotes, paragraph  # noqa: PLC0415
    from docxkit._xml import PARA_RE, visible_text  # noqa: PLC0415
    xml = parts[DOCUMENT].decode("utf-8")
    texts = [visible_text(m.group(0)).strip()
             for m in PARA_RE.finditer(xml)]
    out: Answers = {}
    for i, sig in enumerate(_anchors(xml, 3)):
        text = next(t for t in texts if t.startswith(sig))
        mid = text[len(text) // 2:len(text) // 2 + 12]
        after = texts[texts.index(text) + 1] if text != texts[-1] else ""
        # attribute calls, never getattr(paragraph, name): `oracle_reach`
        # reads which writers this probe names off the source
        ops: tuple[tuple[str, Callable[[str, str, str], str]], ...] = (
            ("split", lambda s, m, _a: paragraph.split(xml, s, m)),
            ("merge", lambda s, _m, a: paragraph.merge(xml, s, a)),
            ("drop", lambda s, _m, _a: paragraph.drop(xml, s)))
        for name, op in ops:
            try:
                out[f"{name} {i}"] = _sha(op(sig, mid, after[:20]))
            except Exception as exc:
                out[f"{name} {i}"] = _refusal(exc)
        copy = dict(parts)
        try:
            nid = footnotes.add(copy, after=sig, text="probe")
            out[f"footnotes.add {i}"] = f"id {nid}"
            for part in ("word/document.xml", "word/footnotes.xml"):
                out[f"footnotes.add {i} sha {part}"] = _sha(copy[part])
        except Exception as exc:
            out[f"footnotes.add {i}"] = _refusal(exc)
    return out


def _faced_runs(para_xml: str) -> str:
    """Each run that shows text, as (text, hash of its own ``w:rPr``)."""
    from docxkit._xml import RUN_RE, own_properties, visible_text  # noqa: PLC0415
    runs = []
    for r in RUN_RE.finditer(para_xml):
        text = visible_text(r.group(0))
        if text:
            props = own_properties(r.group(0), "rPr")
            runs.append([text, _sha(props[2]) if props else ""])
    return json.dumps(runs, ensure_ascii=False)


def probe_replace(parts: Package) -> Answers:
    """`edit.replace_in_para` and `replace_keeping_links` across run SEAMS.

    For up to 60 seams between two runs that show text, a 10-character
    anchor straddling the seam is replaced twice: upper-cased whole (a
    change on both sides) and with its last two characters changed (a
    change after the seam only). The answer is the refusal, or every
    run's text and properties afterwards — the question BACKLOG S2
    (2026-11-16) asked, which a text answer cannot see: whose look the
    new words took.
    """
    from docxkit import edit  # noqa: PLC0415
    from docxkit._xml import PARA_RE, RUN_RE, visible_text  # noqa: PLC0415
    xml = parts[DOCUMENT].decode("utf-8")
    out: Answers = {}
    seams = 0
    for n, p in enumerate(PARA_RE.finditer(xml)):
        para = p.group(0)
        if "<w:ins " in para or "<w:del " in para or "<m:oMath" in para:
            continue
        text = edit.editable_text(para)
        cursor = 0
        for r in RUN_RE.finditer(para):
            width = len(visible_text(r.group(0)))
            cursor += width
            if not width or not 5 <= cursor <= len(text) - 5:
                continue
            old = text[cursor - 5:cursor + 5]
            if text.count(old) != 1 or not old.strip():
                continue
            for label, new in (("both", old.upper() + "~"),
                               ("after", old[:-2] + "~~")):
                key = f"p{n} seam {cursor} {label}"
                for name, write in (("in_para", edit.replace_in_para),
                                    ("keeping_links",
                                     edit.replace_keeping_links),
                                    ("with_runs", _styled_replace)):
                    try:
                        out[f"{key} {name}"] = _faced_runs(
                            write(para, old, new))
                    except Exception as exc:
                        out[f"{key} {name}"] = _refusal(exc)
            seams += 1
            if seams == 60:
                return out
    return out


def _styled_replace(para: str, old: str, new: str) -> str:
    """`edit.replace_with_runs` with `new` split italic + plain, so the
    answer shows each run's look (added 2026-11-19, BACKLOG S4). A base
    that predates the writer answers with its AttributeError."""
    from docxkit import edit  # noqa: PLC0415
    return edit.replace_with_runs(
        para, old, [(new[:3], "<w:rPr><w:i/></w:rPr>"), (new[3:], "")])


def _on_document(probe: Callable[[str], Answers]
                 ) -> Callable[[Package], Answers]:
    """A probe of the body XML alone, given the package."""
    def run(parts: Package) -> Answers:
        return probe(parts[DOCUMENT].decode("utf-8"))
    return run


PROBES: dict[str, Callable[[Package], Answers]] = {
    "set_cell": _on_document(probe_set_cell),
    "insert_before": _on_document(probe_insert_before),
    "house": probe_house,
    "crossrefs": probe_crossrefs,
    "link_all": probe_link_all,
    "link_more": probe_link_more,
    "link_rest": probe_link_rest,
    "renumber": probe_renumber,
    "builders": probe_builders,
    "house_apply": probe_house_apply,
    "table_layout": probe_table_layout,
    "footnotes": probe_footnotes,
    "comments": probe_comments,
    "paragraphs": probe_paragraphs,
    "replace": probe_replace,
}


def _read_package(path: str) -> Package:
    """The package's XML parts, and its PNG and JPEG media.

    The images are what the figure rule reads: without them every
    picture's own size is unknown, `house_apply` skipped every figure on
    both sides, and a broken resize printed "0 differ" while
    `oracle_reach` counted `_resize_figures` as measured (review,
    2026-11-15). Other media (EMF, WMF, embedded workbooks) nothing
    reads, and they can run to megabytes."""
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()
                if n.endswith((".xml", ".rels"))
                or (n.startswith("word/media/")
                    and n.lower().endswith((".png", ".jpg", ".jpeg")))}


def worker(src: str, out: str, probes: list[str], files: list[str]) -> int:
    """One side: run the probes over the files with `src` first on path."""
    sys.path.insert(0, src)
    result: dict[str, dict[str, Answers]] = {}
    spent: dict[str, float] = {}
    for f in files:
        try:
            parts = _read_package(f)
            parts[DOCUMENT].decode("utf-8")
        except Exception as exc:
            result[f] = {"_": {"unreadable": type(exc).__name__}}
            continue
        result[f] = {}
        for name in probes:
            t0 = time.perf_counter()
            try:
                result[f][name] = PROBES[name](parts)
            except Exception as exc:
                result[f][name] = {"_probe": f"crashed: {exc!r}"[:200]}
            spent[name] = spent.get(name, 0.0) + time.perf_counter() - t0
    result["_seconds"] = {k: {"total": f"{v:.1f}"} for k, v in spent.items()}
    Path(out).write_bytes(json.dumps(result, ensure_ascii=False).encode())
    return 0


# ------------------------------------------------------------------ diff --


def diff(base: dict[str, dict[str, Answers]],
         head: dict[str, dict[str, Answers]]
         ) -> dict[str, list[tuple[str, str, str | None, str | None]]]:
    """probe -> [(file, key, base answer, head answer)] where they differ."""
    out: dict[str, list[tuple[str, str, str | None, str | None]]] = {}
    for f in sorted(set(base) | set(head)):
        b, h = base.get(f, {}), head.get(f, {})
        for probe in sorted(set(b) | set(h)):
            pb, ph = b.get(probe, {}), h.get(probe, {})
            for key in sorted(set(pb) | set(ph)):
                if pb.get(key) != ph.get(key):
                    out.setdefault(probe, []).append(
                        (f, key, pb.get(key), ph.get(key)))
    return out


def _extract(rev: str, into: Path) -> Path:
    """`rev`'s `src` tree, via git archive, under `into`."""
    tar = into / "src.tar"
    with tar.open("wb") as fh:
        subprocess.run(["git", "-C", str(ROOT), "archive", rev, "src"],
                       stdout=fh, check=True)
    with tarfile.open(tar) as t:
        t.extractall(into, filter="data")
    return into / "src"


def _side(src: Path, probes: list[str], files: list[str],
          out: Path) -> dict[str, dict[str, Answers]]:
    # The paths go in a FILE: on argv, 1,813 manuscript paths are 183,290
    # characters, and Windows refuses a command line past 32,767 with
    # WinError 206 before the worker starts (2026-11-14).
    listing = out.with_suffix(".files.json")
    listing.write_text(json.dumps(files), encoding="utf-8")
    subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(src), str(out), ",".join(probes),
                    str(listing)], check=True)
    loaded: dict[str, dict[str, Answers]] = json.loads(out.read_bytes())
    return loaded


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    if args_in[:1] == ["--worker"]:
        src, out, names, listing = args_in[1:]
        files = json.loads(Path(listing).read_text(encoding="utf-8"))
        return worker(src, out, names.split(","), files)

    sys.path.insert(0, str(HERE))
    import sweep  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

    from docxkit.console import utf8_stdout  # noqa: PLC0415
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Old-vs-new oracle for the writers, over real "
                    "manuscripts.")
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--probe", action="append", choices=sorted(PROBES))
    ap.add_argument("--show", type=int, default=5)
    ap.add_argument("--expect-same", action="store_true")
    args = ap.parse_args(args_in)

    roots = sweep.corpus_roots(args.roots)
    if not roots:
        print(f"SKIPPED: no corpus — set {sweep.CORPUS_ENV} or pass roots")
        return SKIPPED
    # `get(…, "0") or 40` never reached the 40: "0" is a truthy string, so
    # an unset variable meant NO limit and the whole corpus (2026-11-14).
    limit = args.limit or int(os.environ.get(sweep.LIMIT_ENV) or 40)
    paths = sorted(p for root in roots for p in Path(root).rglob("*.docx")
                   if not sweep.SKIP.search(str(p)))
    chosen = [str(p) for p in sweep.sample(paths, limit)]
    if not chosen:
        print("SKIPPED: no .docx under the roots")
        return SKIPPED
    probes = args.probe or sorted(PROBES)
    with tempfile.TemporaryDirectory() as tmp:
        base_src = _extract(args.base, Path(tmp))
        base = _side(base_src, probes, chosen, Path(tmp) / "base.json")
        head = _side(ROOT / "src", probes, chosen, Path(tmp) / "head.json")
    seconds = head.pop("_seconds", {})
    base.pop("_seconds", None)
    found = diff(base, head)
    print(f"{len(chosen)} of {len(paths)} documents; base {args.base} vs "
          f"the working tree")
    for probe in probes:
        answers = sum(len(v.get(probe, {})) for v in head.values())
        rows = found.get(probe, [])
        # A probe that crashes on every document answers ONE key per
        # document, the same on both sides, and reads "0 differ".
        crashed = sum(1 for v in head.values() if "_probe" in v.get(probe, {}))
        spent = seconds.get(probe, {}).get("total", "?")
        print(f"  {probe}: {answers} answers, {len(rows)} differ"
              + (f", CRASHED on {crashed}" if crashed else "")
              + f" ({spent} s)")
        for f, key, b, h in rows[:args.show]:
            print(f"    {Path(f).name} {key}\n      base: {b}\n      "
                  f"head: {h}")
    return 1 if args.expect_same and found else 0


if __name__ == "__main__":
    sys.exit(main())
