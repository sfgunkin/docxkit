r"""The single-file revision protocol: one manuscript, two states.

Every paper on this protocol revises through ONE file —
``revision/working.docx`` — and its state is readable from the file
itself, so nobody has to remember which copy is current:

======================  ==========================================
``revisions == 0``      **truth**: this is the paper, and an agent
                        may start a batch on it
``revisions > 0``       a **proposal** awaiting the author's verdict
======================  ==========================================

The cycle is: truth -> checkpoint -> apply the batch to a clean copy in
``build/`` -> Word Compare -> the tracked result *is* the new
``working.docx`` -> the author adjudicates in Word -> accept-all ->
truth again. There is no separate redline file and no baseline file;
``build/prev.docx`` is the last accepted truth and the compare
reference.

This module is the engine. What stays with the paper is
``revision/paper.toml`` — its name, its author string, and the list of
its own gates. The protocol itself is identical in every project, which
is why it is here: it was copied verbatim into a second paper within a
day of being written, and a third copy would have been the point where
they started to disagree with each other.

Four operations, in the order a batch meets them::

    ingest    what the author changed while I was away   (read-only)
    build     clean edit -> redline, via Word Compare
    validate  the gate ladder, fast to slow, failing early
    promote   put a validated batch onto working.docx

plus ``state`` (which of the two states is this file in?),
``baseline`` (the author accepted — this is the new truth) and ``init``
(scaffold the layout for a paper that has not migrated yet).

Every refusal in here was a real incident. They are worth reading as a
list, because each one is silent if you skip it:

* a batch built on a baseline that still carries pending revisions
  flattens those revisions into plain text — the author's open verdicts
  are decided for them, and nothing says so;
* Word's Compare cannot serialize tracked math, so a batch that touches
  equations bakes them in with nothing to reject;
* a copy made while Word holds the file is overwritten the moment Word
  saves, and the promotion silently vanishes;
* a batch promoted onto a working.docx the author has edited since
  destroys those edits.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tomllib
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import lint as _lint
from . import package, revisions, tracked
from . import word as _word
from ._xml import DOCUMENT, ENDNOTES, FOOTNOTES
from .errors import (
    BaselinePending,
    DocumentLocked,
    MathResolved,
    ProtocolError,
    StaleBatch,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

__all__ = [
    "IngestReport",
    "Paper",
    "PromoteReport",
    "State",
    "ValidateReport",
    "baseline",
    "build",
    "find_config",
    "ingest",
    "init",
    "load_paper",
    "promote",
    "prune_rescues",
    "rescue_path",
    "rescues",
    "state",
]

#: Parts that carry revisable text. ``document.xml`` is not the whole
#: manuscript: Word's Review > Next button walks the body only, and both
#: Simple Markup and No Markup hide footnote balloons entirely, so a
#: revision left in a footnote is invisible from the author's chair
#: while still making the file a proposal rather than the truth. Any
#: count that reads only the body will call such a file "truth" and let
#: the next batch flatten it.
TEXT_PARTS = (DOCUMENT, FOOTNOTES,
              ENDNOTES)

#: Parts a Word save rewrites whether or not anything was edited —
#: rsids, the editing-time total, the namespace prefix order. Reporting
#: these as author edits cried wolf on every round-trip.
SAVE_NOISE = ("docProps/app.xml", "docProps/core.xml", "word/settings.xml")

_CONFIG = "paper.toml"
_DIR = "revision"

#: How many rescue copies survive a promote, newest first. Five covers
#: "undo the last few promotes", which is all a rescue is for: anything
#: older is better served by the safekit vault, the attic and git, none
#: of which sit in the author's working folder.
RESCUE_KEEP = 5

#: Rescue copies are named by TIME, not by a counter, and that is not a
#: cosmetic choice. The counter form takes the first FREE number, so the
#: moment pruning removes 1 to 3 the next promote writes a *new* file
#: called ``_rescue1``, older than the ``_rescue5`` beside it. Numbering and
#: pruning cannot both be right. A timestamp sorts correctly no matter
#: what has been deleted.
#:
#: **Every name is the same width, down to the microsecond**, which is
#: what makes sorting them as strings give chronological order. The first
#: version stamped whole seconds and appended ``-2``, ``-3`` on collision,
#: and that inverted the order it existed to preserve: ``-`` (0x2D) sorts
#: before ``.`` (0x2E), so ``…224455-2.docx`` came before
#: ``…224455.docx`` and the OLDEST copy read as the newest. Seven promotes
#: inside one second on a real paper is how that surfaced — prune then
#: deletes from the wrong end, which for an undo file is the whole game.
#:
#: Sorting by mtime instead is not an option either: `shutil.copy2`
#: carries the SOURCE's timestamp onto the copy, so every rescue would
#: claim the manuscript's mtime rather than its own.
_RESCUE_STAMP = "%Y%m%d-%H%M%S-%f"
_RESCUE_GLOB = "*_rescue_*"


# --------------------------------------------------------------- config

@dataclass(frozen=True)
class Paper:
    """A paper's own end of the protocol, read from ``paper.toml``."""

    root: Path
    """The project root — the folder that CONTAINS ``revision/``."""
    config: Path
    working: Path
    prev: Path
    build_dir: Path
    name: str
    author: str
    language: str
    gates: tuple[str, ...]
    """The paper's own verification commands. Recorded, never run — see
    :func:`validate`."""
    attic: Path | None
    rescue_keep: int = RESCUE_KEEP
    """How many rescue copies to keep. See :func:`prune_rescues`."""

    @property
    def batch(self) -> Path:
        """Where a batch is staged before it is promoted."""
        return self.build_dir / "batch.docx"

    @property
    def rescue_dir(self) -> Path:
        """Where `promote` puts the file it is about to overwrite.

        Its OWN folder under ``build/``, for two reasons. It keeps the
        undo copies out of the author's line of sight — the whole point
        of this layout is that there is one file to open, and five
        ``working_rescueN.docx`` beside the manuscript is exactly the
        ambiguity it removed. And it means :func:`prune_rescues` deletes
        inside a folder that holds nothing else, so no bug in it can
        reach ``prev.docx``, whose loss would silently break every
        reject-all check that follows.
        """
        return self.build_dir / "rescue"


def find_config(start: str | Path | None = None) -> Path:
    """Locate ``revision/paper.toml`` from `start`, walking upwards.

    Accepts the project root, the ``revision`` folder, ``scripts/``
    inside it, or anywhere below — an agent's working directory during
    a batch is rarely the project root, and requiring one more argument
    on every command is how a path gets hard-coded into a script that
    then outlives the layout.
    """
    here = Path(start or Path.cwd()).resolve()
    if here.is_file():
        here = here.parent
    for folder in (here, *here.parents):
        for candidate in (folder / _DIR / _CONFIG, folder / _CONFIG):
            if candidate.is_file():
                return candidate
    raise ProtocolError(
        f"no {_DIR}/{_CONFIG} at or above {here} — this paper has not "
        f"migrated to the single-file protocol yet. "
        f"`docxkit revision init` scaffolds it.")


def load_paper(start: str | Path | None = None) -> Paper:
    """Read the paper's configuration; paths come back absolute."""
    config = find_config(start)
    root = config.parent.parent if config.parent.name == _DIR \
        else config.parent
    with config.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)

    paper = data.get("paper", {})
    batch_cfg = data.get("batch", {})
    verify = data.get("verify", {})

    def _abs(value: str, fallback: str) -> Path:
        return (root / (value or fallback)).resolve()

    working = _abs(paper.get("working", ""), f"{_DIR}/working.docx")
    prev = _abs(paper.get("prev", ""), f"{_DIR}/build/prev.docx")
    attic = data.get("attic", {}).get("path")
    return Paper(
        root=root,
        config=config,
        working=working,
        prev=prev,
        build_dir=prev.parent,
        name=paper.get("name", root.name),
        author=batch_cfg.get("author", "Revision"),
        language=paper.get("language", "en"),
        gates=tuple(verify.get("commands", ())),
        attic=Path(attic) if attic else None,
        rescue_keep=int(batch_cfg.get("rescue_keep", RESCUE_KEEP)),
    )


# ---------------------------------------------------------------- state

@dataclass(frozen=True)
class State:
    """Which of the two states a file is in, and where the proof is."""

    path: Path
    by_part: dict[str, int]
    by_author: dict[str, int]

    @property
    def pending(self) -> int:
        return sum(self.by_part.values())

    @property
    def is_truth(self) -> bool:
        return self.pending == 0

    @property
    def label(self) -> str:
        return "truth" if self.is_truth else "proposal"

    @property
    def hidden(self) -> int:
        """Pending revisions the author cannot reach with Review > Next.

        Reported separately because "there are 4 left" sends an author
        looking through the body for something that is in a footnote.
        """
        return sum(n for part, n in self.by_part.items()
                   if part != DOCUMENT)


_AUTHOR_RE = re.compile(r'w:author="([^"]*)"')


def state(path: str | Path) -> State:
    """Count the pending revisions in every text-bearing part.

    Every KIND of pending revision, via ``revisions.revision_elements``.
    This counted `<w:ins ` and `<w:del ` itself, which meant a manuscript
    whose only open change was a MOVE or a FORMATTING one — `w:moveTo`,
    `w:rPrChange`, `w:pPrChange`, `w:sectPrChange` — reported "0 pending
    -> TRUTH" and was treated as settled. `revisions` already had the
    full list, and said in a comment why the short one is wrong; the
    protocol's own truth test was the place still using it.
    """
    path = Path(path)
    parts = package.read_parts(path)
    by_part: dict[str, int] = {}
    by_author: dict[str, int] = {}
    for name in TEXT_PARTS:
        blob = parts.get(name)
        if not blob:
            continue
        xml = blob.decode("utf-8", "replace")
        # count the elements, not the authors: a single <w:ins> may hold
        # several runs, and every one of them carries the attribute
        found = revisions.revision_elements(xml)
        if found:
            by_part[name] = len(found)
        for chunk in found:
            who = _AUTHOR_RE.search(chunk)
            if who:
                by_author[who.group(1)] = by_author.get(who.group(1), 0) + 1
    return State(path=path, by_part=by_part, by_author=by_author)


# --------------------------------------------------------------- ingest

@dataclass(frozen=True)
class IngestReport:
    """What the author did to the manuscript while the agent was away.

    Every field is required. An ingest that ran always has all of them,
    and making the states optional bought nothing but a ``None`` check
    at each of the two places that read them.
    """

    working: Path
    prev: Path
    content: dict[str, list[Any]]
    changed_parts: list[str]
    noise_parts: list[str]
    resaved: int
    added: list[str]
    removed: list[str]
    working_state: State
    prev_state: State

    @property
    def style_edit(self) -> bool:
        """Did they change the document's STYLES, not just its text?

        Worth calling out on its own: a style edit changes every
        paragraph that uses it, so a batch that rebuilds paragraphs can
        undo far more than it appears to touch.
        """
        return any(p in self.changed_parts
                   for p in ("word/styles.xml", "word/numbering.xml"))

    @property
    def untouched(self) -> bool:
        return not any(self.content.values()) and not self.changed_parts


def ingest(working: str | Path, prev: str | Path) -> IngestReport:
    """Compare the author's file against the last accepted truth.

    **Read-only**, and that is what makes it safe to run before every
    task without asking. Silently rebuilding over an author's edits is
    the one unrecoverable mistake in this workflow, so the routine that
    detects them must never be the one that risks them.

    Three layers, because each is blind to what the next one sees:
    :mod:`docxkit.compare` for content (structure, word-level text,
    glyphs, formulas and character formatting),
    :func:`package.changed_parts` for which parts differ *in meaning*,
    and :func:`state` for what is still pending on either side.

    The middle layer earns its place: a byte comparison of the package
    reports "styles.xml changed — a STYLE-level edit" on every author
    round-trip, because a Word save re-declares namespace prefixes and
    re-mints rsids in nearly every part. It cried wolf for a whole
    session before ``changed_parts`` learned to compare meaning.
    """
    from . import compare as _compare  # deferred: heavy import chain

    working, prev = Path(working), Path(prev)
    parts = package.changed_parts(package.read_parts(prev),
                                  package.read_parts(working))
    return IngestReport(
        working=working,
        prev=prev,
        content=dict(_compare.compare(str(prev), str(working))),
        changed_parts=[p for p in parts["changed"] if p not in SAVE_NOISE],
        noise_parts=[p for p in parts["changed"] if p in SAVE_NOISE],
        resaved=len(parts["resaved"]),
        added=parts["added"],
        removed=parts["removed"],
        working_state=state(working),
        prev_state=state(prev),
    )


# ---------------------------------------------------------------- build

def build(paper: Paper, revised: str | Path, out: str | Path | None = None,
          *, allow_math_resolve: bool = False,
          allow_pending_baseline: bool = False,
          progress: Any = None) -> tracked.BuildReport:
    """Clean-build plus Word Compare: a redline from an edited copy.

    Edit ``build/prev.docx`` into `revised` normally — no revision
    bookkeeping, no ``w:id`` collisions, no insert-then-delete ordering
    — and let Word's ``CompareDocuments`` derive the redline. This is
    the default path because hand-authored ``w:ins``/``w:del`` is the
    historical source of "Word says the file is corrupted": it failed to
    open on one paper four times and on another once.

    It is NOT the whole answer, and the exception is measured rather
    than suspected. On a real batch that converted five plain-text
    subscripts to OMML::

        hand-authored     4 w:ins + 4 w:del   reject-all == baseline  OK
        clean + compare   0 w:ins + 4 w:del   reject-all == baseline  FAIL

    Word cannot serialize tracked math, so the new equation is simply
    present in the deliverable with no insertion to review. Hence the
    two refusals below: a batch that touches equations must be authored
    by hand instead, and one built on a baseline that still carries
    pending revisions must wait for the author to adjudicate them.
    """
    out = Path(out) if out else paper.batch
    counts = tracked.package_counts(package.read_parts(paper.prev))
    if (counts["insertions"] or counts["deletions"]) \
            and not allow_pending_baseline:
        raise BaselinePending(
            f"{paper.prev.name} still carries {counts['insertions']} "
            f"insertion(s) and {counts['deletions']} deletion(s). Word "
            f"Compare rebuilds the redline from ACCEPTED content, so "
            f"those would be flattened into plain text and could never "
            f"be rejected — the author's open verdicts decided for them. "
            f"Have them accept or reject first.")

    notes: list[str] = []

    def _say(line: str) -> None:
        notes.append(line)
        if progress:
            progress(line)

    report = tracked.build(paper.prev, revised, out, None,
                           author=paper.author, verify_in_word=True,
                           progress=_say)

    # docxkit emits this note even when the count is zero, so read the
    # number rather than matching the sentence
    resolved = [n for n in notes if "math revision" in n
                and any(int(t) > 0 for t in re.findall(r"\b(\d+)\b", n))]
    if resolved and not allow_math_resolve:
        raise MathResolved(
            "; ".join(resolved) + f" — Word cannot serialize tracked "
            f"math, so those edits are baked into {out.name} with "
            f"nothing to accept or reject, and reject-all will not "
            f"restore the baseline. Author this batch by hand instead.")
    return report


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
    accept_paths_agree: bool | None = None

    @property
    def empty_shells(self) -> int:
        return self.accepted.get("empty_shells", 0)

    @property
    def ok(self) -> bool:
        """Every gate that ran said yes."""
        return (not self.lint
                and self.word_opened is not False
                and not self.empty_shells
                and self.reject_matches_baseline is not False
                and self.accept_paths_agree is not False)


# Word's Range.Text and the raw XML spell the same document differently,
# and every difference here is presentational. Fold them before
# comparing, or the accept-paths gate reports a mismatch on every
# document containing a footnote or an equation: \x02 is a footnote
# reference mark and \x07 a cell mark; Word returns math letters from
# the Mathematical Italic block while the XML stores ASCII with m:
# markup around it; and Word gives U+2212 where the XML holds a hyphen.
#
# U+2217 is the same story one character further: Word renders the
# asterisk inside math as ASTERISK OPERATOR, which NFKC does NOT fold
# because the two are distinct characters rather than compatibility
# variants. LI7 writes its prospective-age threshold "T*" eighteen times,
# so the gate failed on that paper with ZERO revisions in the file \u2014 and
# a gate that cannot pass is one its reader learns to skip.
#
# Each entry costs a little of what the gate can see, so each one is
# here because a real document produced it. Do not add a fold on
# suspicion.
_FOLD = str.maketrans({"\u2212": "-", "\u2010": "-", "\u2011": "-",
                       "\u00a0": " ", "\u2217": "*"})


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return "".join(re.sub(r"[\x00-\x1f]", "", folded).split())


def _root(parts: dict[str, bytes], name: str = DOCUMENT
          ) -> Any | None:
    from lxml import etree

    blob = parts.get(name)
    return etree.fromstring(blob) if blob else None


def _glyph(root: Any | None) -> str:
    """Every rendered character, prose and math alike, in document order."""
    if root is None:
        return ""
    return "".join((t.text or "") for t in root.iter()
                   if t.tag in (W + "t", M + "t"))


def _paras(root: Any | None) -> list[str]:
    if root is None:
        return []
    return ["".join((t.text or "") for t in p.iter(W + "t"))
            for p in root.iter(W + "p")]


def _counts(root: Any | None) -> dict[str, int]:
    if root is None:
        return {}
    return {
        "oMath": len(root.findall(".//" + M + "oMath")),
        "tables": len(root.findall(".//" + W + "tbl")),
        "ins": len(root.findall(".//" + W + "ins")),
        "del": len(root.findall(".//" + W + "del")),
        # an OMML element with no text renders as a blank box. A
        # mechanical XML accept can leave these where Word's own accept
        # prunes them, and a manuscript once shipped with visibly broken
        # equations that way.
        "empty_shells": sum(1 for om in root.iter(M + "oMath")
                            if not any((t.text or "")
                                       for t in om.iter(M + "t"))),
    }


def _simulate(parts: dict[str, bytes], how: Any) -> dict[str, bytes]:
    """XML-level accept/reject of every text-bearing part."""
    out = dict(parts)
    for name in TEXT_PARTS:
        if name in out:
            out[name] = how(out[name].decode("utf-8")).encode("utf-8")
    return out


def validate(path: str | Path, baseline: str | Path | None = None,
             *, use_word: bool = True) -> ValidateReport:
    """Run the gate ladder over a batch, fast to slow, failing early.

    1. offline OOXML lint — cheap, and aborts before Word is opened;
    2. tracked counts, package-wide;
    3. does Word open it without repairing it;
    4. accept-all: residual revisions, and empty OMML shells;
    5. reject-all: paragraph text and the glyph stream against the
       baseline;
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
    ``paper.toml``) are NOT run from here: what a paper checks is the
    paper's business, and a shared tool that shells out to per-project
    commands is a different, larger promise than this one.
    """
    path = Path(path)
    parts = package.read_parts(path)
    report = ValidateReport(path=path,
                            baseline=Path(baseline) if baseline else None)

    report.lint = _lint.lint_parts(parts)
    if report.lint:
        return report                      # abort before Word

    report.counts = tracked.package_counts(parts)

    word_accept_glyph: str | None = None
    if use_word:
        try:
            with _word.session() as app, \
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

    if report.baseline is not None:
        rejected = _simulate(parts, revisions.reject)
        base = package.read_parts(report.baseline)
        detail = {
            "paragraphs": _paras(_root(rejected)) == _paras(_root(base)),
            "glyphs": _glyph(_root(rejected)) == _glyph(_root(base)),
            "footnotes": (_glyph(_root(rejected, FOOTNOTES))
                          == _glyph(_root(base, FOOTNOTES))),
        }
        report.reject_detail = detail
        report.reject_matches_baseline = all(detail.values())

    if word_accept_glyph is not None:
        report.accept_paths_agree = (
            _norm(_glyph(acc_root)) == _norm(word_accept_glyph))
    return report


# -------------------------------------------------------------- promote

@dataclass(frozen=True)
class PromoteReport:
    promoted: Path
    onto: Path
    rescue: Path
    pruned: tuple[Path, ...] = ()


def rescue_path(paper: Paper, when: datetime | None = None) -> Path:
    """The next rescue file: ``build/rescue/working_rescue_<stamp>.docx``.

    A taken name advances the stamp by a microsecond rather than gaining
    a suffix, so every rescue in a folder has the SAME shape and sorts
    chronologically as a plain string. See :data:`_RESCUE_STAMP` for the
    version that did not and what it cost.
    """
    moment = when or datetime.now()
    stem, suffix = paper.working.stem, paper.working.suffix
    for _ in range(1000):
        name = f"{stem}_rescue_{moment.strftime(_RESCUE_STAMP)}{suffix}"
        candidate = paper.rescue_dir / name
        if not candidate.exists():
            return candidate
        moment += timedelta(microseconds=1)
    raise ProtocolError(
        f"no free rescue name near {moment:%Y-%m-%d %H:%M:%S} in "
        f"{paper.rescue_dir}")


def rescues(paper: Paper) -> list[Path]:
    """Every rescue copy, oldest first."""
    if not paper.rescue_dir.is_dir():
        return []
    return sorted(paper.rescue_dir.glob(_RESCUE_GLOB + paper.working.suffix))


def prune_rescues(paper: Paper, keep: int | None = None) -> list[Path]:
    """Delete all but the newest `keep` rescue copies; return what went.

    A rescue exists to undo the promote that just happened, or one of
    the few before it. Beyond that the safekit vault, the attic and git
    all hold the same history and hold it out of the working tree, so
    keeping more here buys nothing and costs the clarity this layout was
    built for.

    `keep=0` is honoured — someone may want none — but a NEGATIVE keep
    is treated as zero rather than slicing from the wrong end, which
    would delete the newest instead of the oldest.
    """
    limit = paper.rescue_keep if keep is None else keep
    limit = max(0, limit)
    doomed = rescues(paper)[:-limit] if limit else rescues(paper)
    for path in doomed:
        path.unlink()
    return doomed


def promote(paper: Paper, batch: str | Path | None = None,
            base: str | Path | None = None) -> PromoteReport:
    """Put a validated batch onto ``working.docx`` — safely.

    The author edits ``working.docx`` in Word between turns and during
    them, so a batch built minutes ago may already be stale. Two guards,
    both of which have caught a real loss:

    * **the lock.** A copy written over a document open in Word appears
      to succeed, and then Word writes its in-memory version on top and
      the promotion silently vanishes.
    * **the hash.** If the live file no longer matches the baseline the
      batch was built on, the author has edited it since, and promoting
      would destroy those edits.

    A rescue copy of the live file is taken first, into
    ``build/rescue/`` and stamped with the time. Not a fixed name: an
    earlier version overwrote its own rescue on every promote, so only
    the most recent live state was ever recoverable. Not beside the
    manuscript either, and not numbered — see :attr:`Paper.rescue_dir`
    and :data:`_RESCUE_STAMP`. Older copies are pruned to
    :attr:`Paper.rescue_keep`.
    """
    batch = Path(batch) if batch else paper.batch
    base = Path(base) if base else paper.prev
    live = paper.working

    for candidate in (batch, base, live):
        if not candidate.exists():
            raise ProtocolError(f"missing: {candidate}")

    if package.is_locked(live):
        raise DocumentLocked(
            f"{live.name} is open in Word. Close it first — a copy made "
            f"now would be overwritten the moment Word saves.")

    live_hash, base_hash = _sha(live), _sha(base)
    if live_hash != base_hash:
        raise StaleBatch(
            f"{live.name} no longer matches the baseline this batch was "
            f"built on (live {live_hash[:16]}, baseline "
            f"{base_hash[:16]}). The author has edited it. Re-baseline "
            f"from the live file, rebuild the batch on top of it, "
            f"re-validate, then promote.")

    paper.rescue_dir.mkdir(parents=True, exist_ok=True)
    rescue = rescue_path(paper)
    shutil.copy2(live, rescue)
    if _sha(rescue) != _sha(live):
        raise ProtocolError(
            f"the rescue copy did not land: {rescue} — refusing to "
            f"overwrite {live.name} with nothing to undo it")

    shutil.copyfile(batch, live)
    if _sha(live) != _sha(batch):
        raise ProtocolError(f"the copy did not land: {live}")

    # only after the promote has landed: a prune that ran first could
    # delete the one copy this promote was about to need
    return PromoteReport(promoted=batch, onto=live, rescue=rescue,
                         pruned=tuple(prune_rescues(paper)))


def _sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------- baseline

def baseline(paper: Paper, *, force: bool = False) -> Path:
    """Record the current ``working.docx`` as the new accepted truth.

    Run this after the author has accepted (or rejected) everything: it
    closes the cycle by making ``build/prev.docx`` the file the next
    batch will be compared and rejected against.

    It refuses while revisions are pending, because a baseline that
    contains a proposal is how the next Compare flattens that proposal
    into plain text. `force` is for the one legitimate case — adopting a
    file that already carries revisions the author intends to keep as
    the starting point, which is what a MIGRATION does.

    It also refuses while the file is open in Word, which `promote`
    already did and this did not. A .docx is a zip, and copying one that
    Word is part-way through rewriting captures an archive that is
    internally inconsistent — enshrined here as `prev.docx`, the file
    every later Compare and every reject-all is measured against. `force`
    does NOT override this: a locked file is not a decision the author
    has made, it is a file that cannot be copied safely.
    """
    if package.is_locked(paper.working):
        raise DocumentLocked(
            f"{paper.working.name} is open in Word. Close it first — a "
            f"baseline copied mid-save is a zip nothing can reject "
            f"against.")
    current = state(paper.working)
    if not current.is_truth and not force:
        where = ", ".join(f"{n} in {p.split('/')[-1]}"
                          for p, n in current.by_part.items())
        raise BaselinePending(
            f"{paper.working.name} is a proposal, not the truth: "
            f"{current.pending} revision(s) pending ({where}). The "
            f"author accepts or rejects them; this tool never does.")
    paper.build_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paper.working, paper.prev)
    return paper.prev


# ----------------------------------------------------------------- init

_LOG_TEMPLATE = """# {name} — revision log

`working.docx` is the manuscript. It is the **only** file to open and
edit. It is in one of exactly two states, and the state is readable
from the file:

| revisions | state | who acts |
|-----------|-------|----------|
| 0 | **truth** — this is the paper | agent may start a batch |
| >0 | **proposal** — a batch awaiting a verdict | author accepts/rejects |

    docxkit revision status

## Rules

1. **One file.** `working.docx` never changes name. Round names live in
   git tags and in `export/` copies, never in the live filename.
2. **Ingest before anything.** Every task begins with
   `docxkit revision ingest`; it is read-only and never writes to
   `working.docx`.
3. **Resolve before extend.** No new batch while revisions are pending.
4. **Forward-only.** A script in `scripts/applied/` is spent — a record
   of what was done, not a way to redo it. Recovery from a bad batch is
   reject-all, never a rebuild from an older generation.
5. **Close Word before a handback.**
6. **Text-only -> Compare; math -> hand-authored.**

## Layout

    revision/working.docx     THE paper
    revision/log.md           this file
    revision/paper.toml       per-project configuration
    revision/scripts/         live tools and the paper's own gates
    revision/scripts/applied/ spent batch migrations — records only
    revision/notes/           response notes, drafts, QA records
    revision/build/           prev.docx (= last accepted truth) + scratch

## Batches

| date | batch | changes | gates | outcome |
|------|-------|---------|-------|---------|
| {date} | *(protocol migration — no manuscript change)* | — | working.docx unchanged `{digest}` | truth |
"""

_TOML_TEMPLATE = """# Unified revision protocol — per-project configuration.
# One of these per paper; the protocol itself is shared (docxkit.revision).

[paper]
name     = "{name}"
language = "{language}"
working  = "revision/working.docx"      # THE paper; author edits here only
prev     = "revision/build/prev.docx"   # last accepted truth (compare baseline)

[batch]
# Word's Compare cannot serialize tracked math, so a batch touching
# equations must be hand-authored instead of built through it.
author = "{author}"
# Rescue copies kept in revision/build/rescue/, newest first. A rescue
# undoes the promote that just happened; older history is in the vault,
# the attic and git, none of which sit in the working folder.
rescue_keep = {rescue_keep}

[verify]
# The paper's OWN gates. Recorded here so there is one list; run them
# yourself — `docxkit revision validate` deliberately does not shell out.
commands = [{gates}]

[attic]
path = '{attic}'
"""


def init(root: str | Path, source: str | Path, *, name: str = "",
         author: str = "Revision", language: str = "en",
         attic: str | Path | None = None,
         force: bool = False) -> Paper:
    """Scaffold the protocol layout around an existing manuscript.

    `source` is the paper as it stands today — whatever it is called.
    It is COPIED to ``revision/working.docx`` and to
    ``revision/build/prev.docx``; nothing is moved and nothing is
    deleted, so a migration can be abandoned by removing one folder.
    Retiring the old filename is a separate, deliberate step, and it
    belongs after the gates have been run against the new location.

    The baseline is seeded from the same bytes on purpose: at migration
    time the manuscript IS the last accepted truth, whatever revisions
    it happens to carry.
    """
    root, source = Path(root).resolve(), Path(source).resolve()
    if not source.is_file():
        raise ProtocolError(f"no manuscript at {source}")
    folder = root / _DIR
    config = folder / _CONFIG
    if config.exists() and not force:
        raise ProtocolError(
            f"{config} already exists — this paper is already on the "
            f"protocol. Pass force=True only to rewrite its config.")

    for sub in ("build", "notes", "scripts/applied"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    # `source` may BE working.docx: re-running init on a migrated paper
    # to correct its config is a reasonable thing to do, and copying a
    # file onto itself raises rather than being a no-op
    working = folder / "working.docx"
    if (not working.exists() or force) and source != working:
        shutil.copyfile(source, working)
    prev = folder / "build" / "prev.docx"
    if not prev.exists() or force:
        shutil.copyfile(working, prev)

    config.write_text(_TOML_TEMPLATE.format(
        name=(name or root.name).replace('"', "'"),
        language=language, author=author, gates="",
        rescue_keep=RESCUE_KEEP,
        attic=str(attic) if attic else f"D:\\PaperAttic\\{root.name}",
    ), encoding="utf-8")

    log = folder / "log.md"
    if not log.exists() or force:
        log.write_text(_LOG_TEMPLATE.format(
            name=name or root.name,
            date=_today(),
            digest=_sha(working)[:8].upper(),
        ), encoding="utf-8")
    return load_paper(root)


def _today() -> str:
    return date.today().isoformat()
