"""The gate ladder over a built batch.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import html
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .. import guard as _guard
from .. import lint as _lint
from .. import package, revisions, tracked
from .. import word as _word
from .._xml import FOOTNOTES, PARA_RE, WT_RE, Parts, text_parts
from ..equations import OMATH_RE, tokens
from ..hygiene import _downgraded

# The reject-all comparison and its three helpers live in `tracked`, with
# the code that MAKES a redline, so that a paper calling `tracked.build`
# directly is gated by the same computation this protocol gates on. LI7
# was such a paper, and shipped an unrejectable redline while this
# module held the only copy of the check. Imported rather than
# re-implemented: two readings of "what does this paragraph say" is a
# defect this package has already paid for once.
from ..tracked import (
    Untracked,
    _paras,
    _root,
    _simulate,
    bookmark_changes,
    bookmark_names,
    structure_counts,
    structure_diff,
    untracked,
)
from ._gates import GateResult
from ._losses import (
    _counts,
    _glyph,
    _links,
    _norm,
    emptied_footnotes,
    glyph_runs,
    moved_footnotes,
)

# ------------------------------------------------------------- validate

@dataclass
class ValidateReport:
    """The gate ladder's verdict, gate by gate."""

    path: Path
    baseline: Path | None
    lint: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    word_opened: bool | None = None
    word_error: str = ""
    word_revisions: int | None = None
    accepted: dict[str, int] = field(default_factory=dict)
    reject_matches_baseline: bool | None = None
    reject_detail: dict[str, bool] = field(default_factory=dict)
    #: WHICH paragraphs gate 5 disagrees on, and the named cause when
    #: there is one. Three booleans do not say whether the batch is
    #: salvageable, which is the decision their reader has to make.
    reject_diff: list[Untracked] = field(default_factory=list)
    #: Notes Compare re-emitted as one insertion — a SHAPE, and the one
    #: this report used to warn on. Kept, because it is what a reader
    #: chasing "why is this note an insertion" is looking for.
    moved_footnotes: list[int] = field(default_factory=list)
    #: Of those, the ones rejecting really empties — the CONDITION the
    #: warning describes. The shape is necessary and not sufficient, and
    #: warning on it contradicted `reject_detail["footnotes"]` two lines
    #: later, twice on Aging_Well.
    emptied_footnotes: list[int] = field(default_factory=list)
    #: Links the rejected view does not have and the baseline does. See
    #: :func:`_links` for why rejecting a batch can lose one.
    lost_links: list[str] = field(default_factory=list)
    #: WHICH characters the glyph gate disagrees on. One boolean for a
    #: 68,000-character stream tells its reader only that something
    #: moved: on AFI the answer was two characters, and finding them
    #: took a bespoke difflib script over private imports while three
    #: builds went by blaming the edits. See :func:`glyph_runs`.
    glyph_diff: list[str] = field(default_factory=list)
    #: Every glyph difference is a MATH downgrade — the substitution
    #: Word makes when it re-serialises OMML, not an edit. See the note
    #: in `validate`.
    glyph_math_only: bool = False
    #: Structure the rejected view does not carry in the same numbers
    #: as the baseline: a table DUPLICATED by a move, a moved
    #: paragraph's bookmarks, a destroyed section break. None of those
    #: is a character, so the other four comparisons here are blind to
    #: all of them. See :func:`docxkit.tracked.structure_counts`.
    structure_diff: list[str] = field(default_factory=list)
    #: Could a bookmark the rejected view GAINED be judged? Only against
    #: what the clean copy added, which the build stamps; a batch whose
    #: stamp predates that field is judged against its own accepted
    #: view, which explains every gain. False says so, rather than
    #: letting a green structure gate claim a check it could not make.
    bookmarks_judged: bool | None = None
    #: Whole PARTS the baseline has and the batch does not. See
    #: :func:`docxkit.package.missing_parts`.
    lost_parts: list[str] = field(default_factory=list)
    accept_paths_agree: bool | None = None
    #: Was this batch built on the baseline it is being validated
    #: against? None when the batch carries no stamp to say — a batch
    #: built before `base_sha256` existed, or one nothing built. The
    #: whole ladder below describes the wrong pair when this is False,
    #: which is why it aborts. See :func:`docxkit.guard.base_of`.
    built_on_this_baseline: bool | None = None
    #: The baseline hash the batch says it was built on, when that is
    #: not the one it was handed.
    built_on: str = ""
    #: Is the batch still the bytes its stamp was written for? False
    #: after a tool pass over it that nothing restamped — which `promote`
    #: refuses, so it is said here, where that pass has usually just run
    #: (DSI's relink, 2026-09-16). None with no stamp to ask. Never the
    #: exit code: every gate above reads the bytes that are there, and
    #: their verdict stands; the stamp is `promote`'s question.
    stamp_describes_batch: bool | None = None
    #: The paper's OWN gates, when the caller ran them — `validate
    #: --run-gates` does, and the ladder never does (:func:`run_gates`
    #: says why). Appended as each finishes, so `ok` and `exit_code`
    #: read them; empty means "not run", which is not "passed".
    gates: list[GateResult] = field(default_factory=list)
    #: The phrases that find the pages of the equations this batch ADDS
    #: or CHANGES, in the accepted view — what `revision validate`
    #: renders by default for a paper carrying maths. Empty when the
    #: batch touches no equation. See :func:`math_anchors`.
    math_anchors: list[str] = field(default_factory=list)

    @property
    def empty_shells(self) -> int:
        return self.accepted.get("empty_shells", 0)

    @property
    def aborted(self) -> str:
        """Which gate STOPPED the ladder before its end, or "".

        ``"baseline"`` — gate 0, built on another baseline; ``"lint"``
        — gate 1; ``"word"`` — gate 3, Word could not open the batch.
        Nothing below the stop ran, so an abort is not a failure of
        the gates beneath it and not a pass either: the paper's own
        gates are skipped after one, and the reader is told so.
        """
        if self.built_on_this_baseline is False:
            return "baseline"
        if self.lint:
            return "lint"
        if self.word_opened is False:
            return "word"
        return ""

    @property
    def _ladder_ok(self) -> bool:
        """The ladder alone — the paper's own gates aside."""
        return (not self.aborted
                and not self.empty_shells
                and not self.lost_parts
                and self.reject_matches_baseline is not False
                and self.accept_paths_agree is not False)

    @property
    def ok(self) -> bool:
        """Every gate that ran said yes — the ladder's, and the paper's
        own when they were run (`gates`)."""
        return self._ladder_ok and all(gate.ok for gate in self.gates)

    @property
    def exit_code(self) -> int:
        """The contract a script reads: what `revision validate` exits.

        ======  ======================================================
        ``0``   every gate that ran said yes
        ``1``   the ladder said no — the batch is not fully reviewable
        ``2``   aborted before Word: built on another baseline, or lint
        ``3``   Word could not open the batch
        ``5``   the ladder passed and one of the paper's OWN gates
                failed
        ======  ======================================================

        5 and not 1 for the last: "the redline is unshippable" and
        "the manuscript is wrong" want different responses, and a
        script that only knows non-zero cannot tell them apart. A
        ladder failure outranks a gate failure — when the redline is
        the problem, that is the answer a caller needs.

        The numbers lived in `cli.cmd_revision_validate` and
        `cli._paper_gates` until 2026-09-11, as a chain of returns
        tested only through `argv` — the shape
        :class:`~docxkit.revision.StatusReport` moved out of first.
        """
        aborted = self.aborted
        if aborted == "word":
            return 3
        if aborted:
            return 2
        if not self._ladder_ok:
            return 1
        return 0 if self.ok else 5


def render_accepted(batch: str | Path, anchors: Sequence[str], *,
                    dpi: int = 150,
                    out_dir: str | Path | None = None,
                    ) -> dict[str, Path | None]:
    """Rasterise the ACCEPTED page each anchor falls on. ``{anchor: png}``.

    The one check no gate in the ladder can make. Every gate here reads
    the markup, and a glyph that went the wrong way, an equation that
    renders wrong or a table that split across a page are all correct
    markup — they are defects of the PAGE, and only a render shows them.

    **Accepted, never the redline.** The page a reader will see is the
    accepted one; a redline's pagination is not the deliverable's, so
    checking a glyph against it reports on a page nobody will read.

    Word is the renderer because it keeps OMML — LibreOffice does not,
    and the papers this serves are equation-heavy. It runs read-only,
    on a copy written beside the batch, and both temporaries go away
    whatever happens; the PNGs are what is left.

    Moved here from DSI's `revision/scripts/render_pages.py`, which was
    the last piece of a private gate ladder still alive after that paper
    re-pointed onto the shared commands (2026-08-19). A capability one
    paper keeps in a script is one the next paper does without.
    """
    from .. import pages as _pages
    from .. import word as _word

    batch = Path(batch)
    wanted = [a for a in anchors if a.strip()]
    if not wanted:
        return {}
    # BEFORE Word is asked for anything: the reader is an optional extra,
    # and the render it would read costs a session and a PDF export. A
    # plain install used to pay for both and then fail on the import.
    _pages._import_pymupdf()
    parts = _simulate(package.read_parts(batch), revisions.accept)
    staging = Path(tempfile.mkdtemp(prefix="docxkit_render_"))
    try:
        accepted_docx = staging / f"{batch.stem}__accepted.docx"
        package.write_docx(accepted_docx, parts)
        pdf = _word.export_pdf(accepted_docx, staging / f"{batch.stem}.pdf")
        return _pages.render_anchors(
            pdf, wanted, dpi=dpi,
            out_dir=out_dir if out_dir is not None else batch.parent,
            stem=batch.stem)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


#: How much of a paragraph's prose an anchor takes. A paragraph starts a
#: line on the page, and `render_anchors` looks for the phrase in the
#: page's extracted text, where a line ends in a newline — so the phrase
#: has to sit inside the paragraph's FIRST line, and forty characters do
#: at any body size these papers use.
_ANCHOR_CHARS = 40
#: Prose shorter than this is a label, a number or a caption stub, and
#: matches the first page that mentions it rather than the one wanted.
_ANCHOR_MIN = 12


def _anchor_phrase(prose: str) -> str:
    """The first line's worth of `prose`, cut at a word boundary."""
    text = " ".join(prose.split()).strip(" ,;:.")
    if len(text) <= _ANCHOR_CHARS:
        return text
    cut = text.rfind(" ", 0, _ANCHOR_CHARS + 1)
    return text[:cut] if cut >= _ANCHOR_MIN else text[:_ANCHOR_CHARS]


def _paragraph_phrase(para_xml: str) -> str:
    """The first prose SEGMENT of a paragraph long enough to be found.

    Between the equations, never across one: joining a paragraph's
    ``w:t`` runs gives "where is employment of workers aged 50" for a
    sentence that reads "where *E* is employment …" on the page — the
    equation's characters sit in that hole, and the phrase is on no
    page at all. Measured on AFI, HCW and LE (2026-09-11): a third of
    the equation paragraphs open on "where <symbol>". So the paragraph
    is split at its ``m:oMath`` elements and the first segment that is
    a phrase rather than a label ("where", "(3)") is the anchor.
    """
    for chunk in OMATH_RE.split(para_xml):
        phrase = _anchor_phrase(html.unescape("".join(WT_RE.findall(chunk))))
        if len(phrase) >= _ANCHOR_MIN:
            return phrase
    return ""


def math_anchors(accepted: Parts,
                 baseline: Parts | None) -> list[str]:
    """Phrases that find the pages of the equations `accepted` ADDS or
    CHANGES against `baseline` — every equation, when there is none.

    The eye gate `render_accepted` performs was opt-in and it stayed
    unused: three defects that only a rendered page can show — spacing
    dropped in conversion, operator names set italic, an expression
    authored half as maths and half as prose — shipped through a green
    ladder on the round that gave Aging_Well its first mathematics, and
    a fourth was found after a promote by a different agent (BACKLOG,
    "nothing renders by default"). Every one was in an equation the
    batch had just written. So the default is the pages of exactly
    those: an equation whose symbol stream (:func:`docxkit.equations.
    tokens`) the baseline does not carry.

    Tokens rather than the OMML itself, because Word re-serialises
    every equation on the way through Compare — run splits, rsids — so
    raw markup would name every equation in the paper, every round,
    and a render nobody looks at is the state this replaces. The cost
    is stated: an edit that changes only the SETTING of an equation —
    an operator name gone italic in place — has the same tokens and is
    not caught here; `--render` still names its page by hand.

    The phrase is the paragraph's own prose — a segment of its ``w:t``
    runs between the equations, never the maths, whose characters the
    page draws from the Mathematical Alphanumeric block
    (:func:`_paragraph_phrase`) — and, for a display equation standing
    alone, the phrase of the nearest paragraph above it: the lead-in,
    which is on the same page or the one before, and is what a reader
    finds it by. Deduplicated in document order.
    """
    known: set[str] = set()
    if baseline is not None:
        known = {tokens(m.group(0))
                 for _name, xml in text_parts(baseline)
                 for m in OMATH_RE.finditer(xml)}
    out: dict[str, None] = {}
    for _name, xml in text_parts(accepted):
        lead = ""                       # the last phrase seen, for a display
        for para in PARA_RE.finditer(xml):
            body = para.group(0)
            phrase = _paragraph_phrase(body)
            if any(tokens(m.group(0)) not in known
                   for m in OMATH_RE.finditer(body)) and (phrase or lead):
                out.setdefault(phrase or lead)
            lead = phrase or lead
    return list(out)


def validate(path: str | Path, baseline: str | Path | None = None,
             *, use_word: bool = True,
             word_deadline: float | None = None) -> ValidateReport:
    """Run the gate ladder over a batch, fast to slow, failing early.

    1. offline OOXML lint — cheap, and aborts before Word is opened;
    2. tracked counts, package-wide;
    3. does Word open it without repairing it;
    4. accept-all: residual revisions, and empty OMML shells;
    5. reject-all: paragraph text, the glyph stream and the LINKS
       against the baseline, and the baseline's PART LIST;
    6. the XML accept against Word's own accept.

    Gate 5 is the one that proves a batch is fully REVIEWABLE: if
    rejecting everything does not reproduce the baseline exactly, then
    something in the batch cannot be refused, and the author's veto is
    not real. Gate 6 exists because accept can be simulated in XML
    (fast, deterministic) or performed by Word (authoritative), and a
    manuscript shipped broken equations back when those two disagreed.

    Accept and reject are simulated in XML, so Word is opened exactly
    once and read-only — a Word window the author has open is never
    touched. The paper's own gates (``[verify] commands`` in
    ``paper.toml``) are not part of this ladder: what a paper checks is
    the paper's business. They can be RUN, by asking — see
    :func:`run_gates` and `validate --run-gates` — which is a different
    thing from running them by default, and the difference is the whole
    of the promise.

    `word_deadline` bounds the one Word session (gate 3), in seconds —
    ``[batch] word_deadline`` when the CLI runs this; see
    :func:`docxkit.word.session`.
    """
    path = Path(path)
    parts = package.read_parts(path)
    report = ValidateReport(path=path,
                            baseline=Path(baseline) if baseline else None,
                            stamp_describes_batch=_guard.describes(path))

    # Gate 0: is this batch even ABOUT this baseline? Everything below
    # compares the two, so a mismatched pair produces a full, detailed,
    # entirely plausible verdict describing a batch nobody is working on
    # — twenty LINK LOST findings against a redline two baselines old,
    # several minutes read as if they were about the current round
    # (Aging_Well R5, 2026-08-21). It aborts for the same reason lint
    # does: the answer beneath it is not wrong, it is about the wrong
    # document.
    if report.baseline is not None:
        built_on = _guard.base_of(path)
        if built_on is not None:
            report.built_on_this_baseline = built_on == _guard.sha256(
                report.baseline)
            if not report.built_on_this_baseline:
                report.built_on = built_on
                return report

    report.lint = _lint.lint_parts(parts)
    if report.lint:
        return report                      # abort before Word

    report.counts = tracked.package_counts(parts)

    word_accept_glyph: str | None = None
    if use_word:
        try:
            with _word.session(**tracked._bounded(
                    word_deadline, f"validating {path.name}")) as app, \
                    _word.open_doc(app, path) as doc:
                report.word_opened = True
                report.word_revisions = int(doc.Revisions.Count)
                if not package.is_locked(path):
                    doc.AcceptAllRevisions()
                    # _norm strips control characters, so take it raw
                    word_accept_glyph = "".join(p.Range.Text
                                                for p in doc.Paragraphs)
        except Exception as exc:
            report.word_opened = False
            report.word_error = str(exc)[:200]
            return report

    accepted = _simulate(parts, revisions.accept)
    acc_root = _root(accepted)
    report.accepted = _counts(acc_root)
    base = (package.read_parts(report.baseline)
            if report.baseline is not None else None)
    report.math_anchors = math_anchors(accepted, base)

    if base is not None:
        rejected = _simulate(parts, revisions.reject)
        # The PACKAGE, before its text: the reject-all gate below proves
        # the words round-trip, and a part that is not there has no words
        # for it to read.
        report.lost_parts = package.missing_parts(parts, base)
        was, now = _links(base), _links(rejected)
        body_now, body_was = _glyph(_root(rejected)), _glyph(_root(base))
        notes_now = _glyph(_root(rejected, FOOTNOTES))
        notes_was = _glyph(_root(base, FOOTNOTES))
        # Bookmarks by NAME: Compare carries the clean copy's additions
        # into the rejected view, so a gain is judged against what the
        # clean copy ADDED — which only the build knew, and stamped. The
        # redline's own accepted view is no witness: a bookmark is not
        # revisable, both views carry the same ones, and with it as the
        # witness no gain could ever be refused (review of 2026-09-24).
        added = _guard.bookmarks_added(path)
        report.bookmarks_judged = added is not None
        witness = (bookmark_names(base) + Counter(added)
                   if added is not None else bookmark_names(accepted))
        struct_moved = (
            structure_diff(structure_counts(base),
                           structure_counts(rejected),
                           skip=("bookmarkStart",))
            + bookmark_changes(base, rejected, witness))
        detail = {
            "paragraphs": _paras(_root(rejected)) == _paras(_root(base)),
            "glyphs": body_now == body_was,
            "footnotes": notes_now == notes_was,
            "links": was == now,
            "structure": not struct_moved,
        }
        report.reject_detail = detail
        report.reject_matches_baseline = all(detail.values())
        if not report.reject_matches_baseline:
            report.reject_diff = untracked(parts, base)
            report.glyph_diff = (
                glyph_runs(body_was, body_now)
                + [f"(footnotes) {run}"
                   for run in glyph_runs(notes_was, notes_now)])
            # Word downgrades U+2212 to a hyphen while re-serialising an
            # equation, and `tracked.build` puts it back in the ACCEPTED
            # view. The rejected one keeps whatever Compare wrote, so a
            # batch whose edit is perfect fails this gate on a character
            # no author typed — three rounds running, on AFI. Downgrade
            # BOTH sides: if that makes them equal, every difference here
            # is that substitution and nothing else.
            report.glyph_math_only = bool(report.glyph_diff) and (
                _downgraded(body_was) == _downgraded(body_now)
                and _downgraded(notes_was) == _downgraded(notes_now))
            report.moved_footnotes = moved_footnotes(parts, base)
            # Measured against the REJECTED parts already computed
            # above, not predicted from the shape: `detail["footnotes"]`
            # is the same measurement taken whole, and the two must not
            # be able to disagree in one report.
            report.emptied_footnotes = emptied_footnotes(
                rejected, base, report.moved_footnotes)
            report.lost_links = [
                f"-> {a} ({label[:40]!r})"
                for a, label in sorted((was - now).elements())]
            report.structure_diff = struct_moved

    if word_accept_glyph is not None:
        report.accept_paths_agree = (
            _norm(_glyph(acc_root, main_story=True))
            == _norm(word_accept_glyph))
    return report
