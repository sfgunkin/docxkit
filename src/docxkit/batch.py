r"""A batch of edits as one gated unit of work.

Every module here is a VERB. This is the sentence they make, which each paper
was otherwise writing for itself:

    locate -> preflight every edit -> apply -> gate the invariants -> write

Measured across the four papers on this machine on 2026-08-20: 237 python files
under ``revision/``, **126** of which do ``read_parts`` -> edit ->
``write_docx`` themselves and 63 of which reach past this package into raw
XML. AFI's r4 batches
average ~230 lines each; the one written against a harness is 50. AFI has
``_batch.py``, DSI ``quickfix.py`` and ``tc_lib.py``, Life_Expectancy
``buildkit.py``, Parental_style ``cleanup_pass{,2,3}`` -- four divergent
partial implementations of this, the failure the ``revision``
consolidation already fixed once for the protocol scripts.

Two things make it worth having beyond the line count.

**Preflight.** ``replace_in_para`` refuses a match spanning or starting
inside a hyperlink; ``para_slice`` refuses a signature matching 0 or 2+
paragraphs. Both refusals are right, and both arrive ONE AT A TIME at
apply time, so three anchor problems cost three cycles. :func:`preflight`
applies every edit cumulatively, in order, in memory, and reports them all
at once -- by attempting the real replace and catching what it raises, so
it uses the guards the apply will and cannot drift from them. Edits in one
batch also break each other's anchors (an edit removes the sentence a later
signature names; a cross-reference added in phase 1 makes a phase-2 label
ambiguous), which only a cumulative pass can see.

**Both application paths.** Word's Compare cannot serialize tracked math,
it drops links from paragraphs it edits, renumbers footnotes whose
reference moved, and cannot carry a figure swap or a moved table row. So a
real round needs BOTH a clean copy for the redline ladder and direct
application to the accepted file -- in AFI's r4 every batch after the
twentieth was direct. A harness offering only the Compare path gets
abandoned rather than half-used, which is what happened.

This module is deliberately path-agnostic and shells out to nothing: what a
paper checks is the paper's business -- the line ``revision.validate``
draws too. Callers pass the bytes and the destination.

    from docxkit import batch, package

    parts = package.read_parts(src)
    edits = [batch.Edit("R12", "Figure 1 shows", " the old clause.", "")]
    report = batch.run("r4v", edits, parts=parts, out=dst)
    if not report.ok:
        print(report.text())
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from ._xml import DOCUMENT, ENDNOTES, FOOTNOTES, PARA_RE, internal_links
from .console import utf8_stdout
from .edit import preserve_space, replace_in_para, visible_text
from .find import edit_para
from .package import write_docx

__all__ = [
    # Re-exported so a batch script has ONE import line. Bookmark ids
    # must be unique across the whole document, notes included, so
    # `next_bookmark_id` wants every part that can hold one — and
    # `DOCUMENT` alone sent the caller either into private `_xml` or
    # back to spelling the note part's name by hand, which is the thing
    # these constants exist to stop.
    "DOCUMENT",
    "ENDNOTES",
    "FOOTNOTES",
    "Edit",
    "Report",
    "Step",
    "Verdict",
    "apply_steps",
    "diagnose",
    "invariants",
    "preflight",
    "run",
]

# `PARA_RE` deliberately excludes a self-closing `<w:p/>`; the invariant below
# must still COUNT one, because an "empty" paragraph in these papers is usually
# a section break carrying orientation and page-number footers. So the guarded
# container branch is reused verbatim -- it cannot drift from `_xml` -- and the
# empty-element branch is appended AFTER it. The order is load-bearing: putting
# an unguarded branch first makes `<w:p/><w:p>x</w:p>` read as one paragraph.
_PARA = re.compile(PARA_RE.pattern + r"|<w:p\b[^>]*/>", re.DOTALL)
# `\s*/>`: a Hyperlink style closed ` />` (739 in 20 of 2,954 corpus
# packages) is a label too, and unread the refusal named no cause.
# And the style need not be the run's LAST property: Word writes it first
# and then whatever else the run wears — `w:noProof` on every
# cross-reference, `w:b`, `w:color`, `w14:ligatures`. Demanding `</w:rPr>`
# straight after it left 9,161 of 25,802 corpus labels (35%) unread
# (backlog S2, 2026-09-18). The run's other properties are read up to its
# OWN `</w:rPr>` and no further — the `_compare_diff._FIELD_END_RE` shape —
# so the match cannot run on into the next run.
_LABEL = re.compile(
    r'<w:rStyle w:val="Hyperlink"\s*/>(?:[^<]|<(?!/w:rPr>))*</w:rPr>'
    r"<w:t[^>]*>([^<]*)</w:t>")
_TRACKED = re.compile(r"<w:(ins|del)\b")


@dataclass(frozen=True)
class Edit:
    """One text replacement, in the single paragraph `sig` identifies."""

    task: str
    sig: str
    old: str
    new: str


@dataclass(frozen=True)
class Step:
    """Anything preflight cannot model: a figure swap, a row move, a relabel.

    `fn(xml, parts) -> xml` and may mutate `parts` in place, which is what
    embedding an image or adding a footnote part needs.
    """

    label: str
    fn: Callable[[str, dict[str, bytes]], str]


@dataclass(frozen=True)
class Verdict:
    task: str
    ok: bool
    reason: str = ""


@dataclass
class Report:
    """What a batch did, and whether it may be written."""

    name: str
    ok: bool = True
    verdicts: list[Verdict] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    before: dict[str, int] = field(default_factory=dict)
    after: dict[str, int] = field(default_factory=dict)
    spaces_fixed: int = 0
    written: Path | None = None
    #: `(label, seconds)` per step, in the order they ran. Recorded and
    #: never written anywhere: this module is path-agnostic and shells
    #: out to nothing, so where a paper KEEPS its timings is the paper's
    #: business (`docxkit.timings.record` is the one-liner for it).
    durations: list[tuple[str, float]] = field(default_factory=list)

    def slowest(self, limit: int = 3) -> list[tuple[str, float]]:
        """The costliest steps first. Empty for a batch of pure Edits,
        which are one regex each and never the reason a round is slow."""
        return sorted(self.durations, key=lambda d: -d[1])[:limit]

    def text(self) -> str:
        out = [f"{self.name}:"]
        out += [f"  {'ok  ' if v.ok else 'BLOCKED'} {v.task}"
                + (f"\n          -> {v.reason}" if v.reason else "")
                for v in self.verdicts]
        out += [f"  OK   {a}" for a in self.applied]
        out += [f"  FAIL {f}" for f in self.failures]
        if self.before:
            moved = {k: (self.before[k], self.after.get(k))
                     for k in self.before
                     if self.before[k] != self.after.get(k)}
            out.append(f"  invariants {moved or 'unchanged'}"
                       f"; preserve_space fixed {self.spaces_fixed}")
        # Only when a step actually cost something. A batch of Edits
        # runs in milliseconds and a "slowest" line under it would be
        # noise in every report this paper prints.
        if (slow := [d for d in self.slowest() if d[1] >= 0.5]):
            out.append("  slowest  " + ", ".join(f"{label} {secs:.1f}s"
                                                 for label, secs in slow))
        if self.written:
            out.append(f"  wrote {self.written}")
        return "\n".join(out)


def invariants(xml: str) -> dict[str, int]:
    """The counts an edit must not move unless it declares which, and by
    how much.

    Chosen because each is a carrier that no TEXT diff can see moving: a batch
    can delete a bookmark, drop a footnote mark, orphan a link or lose a table
    row while every word on the page stays the same.
    """
    return {
        "paragraphs": len(_PARA.findall(xml)),
        "bookmarks": len(re.findall(r"<w:bookmarkStart\b", xml)),
        "bookmark_ends": len(re.findall(r"<w:bookmarkEnd\b", xml)),
        "links": len(internal_links(xml)),
        "footnote_refs": len(re.findall(r"<w:footnoteReference\b", xml)),
        "math": len(re.findall(r"<m:oMath[ >]", xml)),
        "rows": len(re.findall(r"<w:tr\b", xml)),
        "drawings": len(re.findall(r"<w:drawing\b", xml)),
    }


def diagnose(xml: str, sig: str, old: str) -> str:
    """Why an edit will fail, in the terms that would fix it.

    The refusals this reports are correct and their messages are good; what
    they do not say is which of several causes applies to YOUR anchor, and
    finding that out is the round-trip preflight exists to remove.
    """
    hits = [m for m in _PARA.finditer(xml) if sig in visible_text(m.group(0))]
    if not hits:
        return ("signature matches NO paragraph -- an earlier edit in this "
                "batch may have rewritten the sentence it names")
    if len(hits) > 1:
        return (f"signature matches {len(hits)} paragraphs; para_slice needs "
                f"exactly one. Lengthen it, or anchor on a sentence no edit "
                f"in this batch touches")
    para = hits[0].group(0)
    if old not in visible_text(para):
        near = [s for s in re.split(r"(?<=[.:])\s", visible_text(para))
                if old[:20] and old[:20] in s]
        return ("`old` is not in that paragraph"
                + (f"; nearest text: {near[0][:80]!r}" if near else ""))
    for label in _LABEL.findall(para):
        if label and (label in old or old in label):
            return (f"the match meets hyperlink label {label!r}. Anchor "
                    f"strictly outside it, or pass allow_hyperlink=True "
                    f"if the replacement lies wholly INSIDE the label")
    if "<m:oMath" in para and old not in "".join(
            re.findall(r"<w:t[^>]*>([^<]*)</w:t>", para)):
        return ("the match spans an equation -- anchor on the prose either "
                "side; this module never rewrites OMML")
    return "refused for a reason preflight does not model; see the exception"


def preflight(edits: Sequence[Edit], xml: str) -> list[Verdict]:
    """Try every edit, cumulatively and in order, and report all verdicts.

    Cumulative is the point: an edit that rewrites the sentence a later
    signature names is invisible to a per-edit check, and it is the single most
    common way a batch fails on its second run rather than its first.
    """
    out: list[Verdict] = []
    for e in edits:
        try:
            after = edit_para(
                xml, e.sig,
                partial(replace_in_para, old=e.old, new=e.new))
        except Exception as exc:
            out.append(Verdict(e.task, False,
                               f"{type(exc).__name__}: "
                               f"{diagnose(xml, e.sig, e.old)}"))
            continue
        if after == xml:
            out.append(Verdict(e.task, False, "matched but changed nothing"))
            continue
        xml = after
        out.append(Verdict(e.task, True))
    return out


def apply_steps(
    xml: str, parts: dict[str, bytes], steps: Sequence[Edit | Step],
    durations: list[tuple[str, float]] | None = None,
) -> tuple[str, list[str], list[str]]:
    """Run every step, keeping going so one failure does not hide the rest."""
    # `run` has already done this, but this is public and papers call it
    # directly — and it is the one place the library hands control to
    # caller code that prints.
    utf8_stdout()
    applied: list[str] = []
    failures: list[str] = []
    for s in steps:
        was = xml
        began = time.perf_counter()
        try:
            if isinstance(s, Edit):
                xml = edit_para(
                    xml, s.sig,
                    partial(replace_in_para, old=s.old, new=s.new))
                label = s.task
            else:
                xml = s.fn(xml, parts)
                label = s.label
        except Exception as exc:
            failures.append(f"{getattr(s, 'task', getattr(s, 'label', '?'))}  "
                            f"{type(exc).__name__}: {exc}")
            xml = was
            # Timed even though it failed. A step that raises after
            # thirty seconds is the interesting one — the round is slow
            # AND broken — and dropping it here would leave the report
            # blaming whichever step ran next.
            if durations is not None:
                durations.append(
                    (getattr(s, "task", getattr(s, "label", "?")),
                     round(time.perf_counter() - began, 2)))
            continue
        if durations is not None:
            durations.append((label, round(time.perf_counter() - began, 2)))
        if xml == was and isinstance(s, Edit):
            failures.append(f"{s.task}  matched but changed nothing")
            continue
        applied.append(label)
    return xml, applied, failures


def run(name: str, steps: Sequence[Edit | Step], *,
        parts: dict[str, bytes],
        out: Path | str | None = None,
        allow: dict[str, int] | None = None,
        require_settled: bool = True,
        dry: bool = False) -> Report:
    """Preflight, apply, gate, and write. The whole unit of work.

    `allow` names the invariants this batch MEANS to move, as deltas --
    ``{"paragraphs": -2}`` for a batch that deletes two. Anything else moving
    is a failure, because a carrier moving silently is the class of damage no
    text diff shows.

    `require_settled` refuses a batch on a file that still has tracked
    revisions pending: Word's Compare treats a pending revision as ACCEPTED, so
    stacking a second batch decides the author's open verdicts for them.
    """
    # Before anything can print. `console` calls making stdout safe the
    # toolkit's job, and they sat only at the CLI boundary — `cli.main`
    # and `compare.main` — while the printing sits here, in the library
    # every per-paper batch script drives directly. On a cp1252 console
    # a step that printed the typographic minus it was restoring raised
    # inside `apply_steps`, which caught it, rolled the step back and
    # reported a step failure: same file, same code, `ok=False` against
    # `ok=True`, and the only variable the terminal's code page. It
    # reads as a fault in the manuscript at exactly the moment — a
    # close-out after the author's accept — when a glyph problem is what
    # you are looking for (Aging_Well R96, 2026-09-05).
    #
    # At the TOP, not beside `apply_steps`, because a preflight refusal
    # returns before that — and one refusal echoes the DOCUMENT back:
    # `diagnose` quotes the hyperlink label it met, verbatim. On the DSI
    # manuscript that label is Cyrillic ('Таблица 3'), which cp1252
    # cannot encode either, and `print(report.text())` is the documented
    # way to read a Report. The other refusals are the toolkit's own
    # English and would survive; this one would not.
    utf8_stdout()

    xml = parts[DOCUMENT].decode("utf-8")
    report = Report(name=name)

    if require_settled:
        pending = len(_TRACKED.findall(xml))
        if pending:
            report.ok = False
            report.failures.append(
                f"{pending} tracked revision(s) still pending -- accept or "
                f"reject them before stacking another batch")
            return report

    edits = [s for s in steps if isinstance(s, Edit)]
    report.verdicts = preflight(edits, xml)
    if any(not v.ok for v in report.verdicts):
        report.ok = False
        return report

    report.before = invariants(xml)
    xml, report.applied, report.failures = apply_steps(
        xml, parts, steps, report.durations)
    xml, report.spaces_fixed = preserve_space(xml)
    report.after = invariants(xml)

    allow = allow or {}
    for key, was in report.before.items():
        want = was + allow.get(key, 0)
        if report.after[key] != want:
            report.failures.append(
                f"{key} {was} -> {report.after[key]}, expected {want}")
    for key in allow:
        if key not in report.before:
            report.failures.append(
                f"allow names an unknown invariant: {key!r}")

    report.ok = not report.failures
    if not report.ok or dry:
        return report

    parts[DOCUMENT] = xml.encode("utf-8")
    if out is not None:
        write_docx(Path(out), parts)
        report.written = Path(out)
    return report

