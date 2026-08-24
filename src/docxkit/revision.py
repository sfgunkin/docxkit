r"""The single-file revision protocol: one manuscript, two states.

Every paper on this protocol revises through ONE file — **the author's
own file, under its own name, wherever they keep it** — and its state is
readable from the file itself, so nobody has to remember which copy is
current:

======================  ==========================================
``revisions == 0``      **truth**: this is the paper, and an agent
                        may start a batch on it
``revisions > 0``       a **proposal** awaiting the author's verdict
======================  ==========================================

The cycle is: truth -> checkpoint -> apply the batch to a clean copy in
``build/`` -> Word Compare -> the tracked result *is* the new manuscript
-> the author adjudicates in Word -> accept-all -> truth again.
``build/prev.docx`` is the last accepted truth and the compare
reference. The manuscript is never shadowed by a "current" copy under
another name — what ``build/`` holds is the baseline, the staged batch,
the rescue copies and, since 2026-08-23, the redlines kept for the
record (:attr:`Paper.redline_dir`), none of which is a second place to
edit the paper.

**Which file is the paper is the author's choice, not this module's.**
``revision/paper.toml`` says so in one line (``working = ...``) and every
command reads it from there. The first shape of this protocol imposed
one name on every project — ``revision/working.docx`` — and it cost the
thing it was meant to buy: with nine papers on it, Explorer, the Word
title bar and the taskbar all say ``working.docx``, and the author
cannot tell which paper is open (author, 2026-08-23). So :func:`init`
adopts the manuscript IN PLACE by default: no copy is made, the name
stays the author's, and there is no second file to go stale. Papers
scaffolded under the old default keep their configured path and are not
touched — the declaration is what matters, never the spelling.

This module is the engine. What stays with the paper is
``revision/`` — its config, its log, ``build/prev.docx``, its own gates
and notes. That folder is MACHINERY; the manuscript does not have to
live in it and by default does not. The protocol itself is identical in
every project, which is why it is here: it was copied verbatim into a
second paper within a day of being written, and a third copy would have
been the point where they started to disagree with each other.

Four operations, in the order a batch meets them::

    ingest    what the author changed while I was away   (read-only)
    build     clean edit -> redline, via Word Compare
    validate  the gate ladder, fast to slow, failing early
    promote   put a validated batch onto the manuscript

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
* a batch promoted onto a manuscript the author has edited since
  destroys those edits;
* an accept the author made in Word leaves NOTHING pending on either
  side, so a pending count alone calls a baseline the paper has already
  outgrown "the truth" — see :func:`drift`.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import tomllib
import unicodedata
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from . import footnotes, package, revisions, tracked
from . import guard as _guard
from . import lint as _lint
from . import word as _word
from ._xml import (
    BOOKMARK_NAME_RE,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    NOTE_DEF_RE,
    WORD_ANCHOR,
    internal_links,
    text_parts,
    visible_text,
    word_minted,
)
from .errors import (
    BaselinePending,
    DocumentLocked,
    HandbackLoss,
    MathResolved,
    ProtocolError,
    StaleBatch,
)
from .hygiene import _MATH_T_RE, _downgraded, restore_math_glyphs

# The reject-all comparison and its three helpers live in `tracked`, with
# the code that MAKES a redline, so that a paper calling `tracked.build`
# directly is gated by the same computation this protocol gates on. LI7
# was such a paper, and shipped an unrejectable redline while this
# module held the only copy of the check. Imported rather than
# re-implemented: two readings of "what does this paragraph say" is a
# defect this package has already paid for once.
from .tracked import (
    Untracked,
    _paras,
    _root,
    _simulate,
    structure_counts,
    structure_diff,
    untracked,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

__all__ = [
    "REGISTRY_ENV",
    "RESCUE_KEEP",
    "SAVE_NOISE",
    "TEXT_PARTS",
    "BaselinePending",
    "DocumentLocked",
    "Doubt",
    "GateResult",
    "HandbackLoss",
    "IngestReport",
    "Loss",
    "MathResolved",
    "Paper",
    "PromoteReport",
    "ProtocolError",
    "Relabelled",
    "StaleBatch",
    "State",
    "Survey",
    "ValidateReport",
    "Verdict",
    "baseline",
    "build",
    "doctor",
    "drift",
    "find_config",
    "glyph_runs",
    "ingest",
    "init",
    # re-exported like TEXT_PARTS and ProtocolError beside it: the
    # reports here talk about links, so the callers of this module ask
    # about them, and `from docxkit._xml import ...` is a private
    # spelling Pyright is right to refuse. `docxkit.find` is the home
    # for a new caller; this is where the existing ones already look.
    "internal_links",
    "load_paper",
    "log_batch",
    "losses",
    "moved_footnotes",
    "promote",
    "prune_rescues",
    "redline_path",
    "redlines",
    "register",
    "registered",
    "registry_path",
    "relabelled_links",
    "render_accepted",
    "rescue_path",
    "rescues",
    "restored_bookmarks",
    "run_gates",
    "scan",
    "state",
    "survey",
    "validate",
    "verdict",
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

#: Directories a paper keeps SPENT builders in, skipped unless
#: ``[doctor] skip`` says otherwise. "applied" is already the protocol's
#: word for a batch that has been used, and under the forward-only rule
#: a spent script naming an old generation is the record rather than a
#: defect. AFI reported 134 selections with three worth reading, and
#: about 130 of the rest were an archive of exactly this kind.
_DOCTOR_SPENT = ("scripts/applied",)

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
    """THE paper, wherever the author keeps it and whatever they call it.

    Declared by ``[paper] working`` and nowhere else. It is deliberately
    not a fixed name: nine papers sharing one filename is how an author
    ends up unable to tell, from Explorer or the Word title bar, which
    project is open.
    """
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
    doctor_skip: tuple[str, ...] = ()
    """Directories `doctor` should not survey, from ``[doctor] skip``.

    A paper accumulates SPENT builders — the phase scripts of a
    restructure, a shipped replication package with its own frozen copy
    of the manuscript — and under the forward-only rule those are not
    defects but the record. AFI reported 134 selections with three worth
    reading; declaring the archive is how the three stay visible.
    """
    """How many rescue copies to keep. See :func:`prune_rescues`."""
    carry: tuple[str, ...] = ()
    """Parts THIS paper's Compare eats, from ``[batch] carry``.

    Added to :data:`docxkit.tracked.CARRIED_PARTS`, which every paper
    gets. A header or footer belongs here and not in the default,
    because it is reached from the section properties as well as through
    a relationship: `restore_parts` puts that reference back or refuses,
    but whether the section it lands in is the section the author meant
    is a question about the rendered page. Aging_Well's Compare drops
    ``word/footer3.xml`` — the first-page footer — on every rebuild, and
    the paper carried a 130-line script to put it back.
    """

    @property
    def batch(self) -> Path:
        """Where a batch is staged before it is promoted."""
        return self.build_dir / "batch.docx"

    @property
    def redline_dir(self) -> Path:
        """Where `promote` keeps the REDLINE it just put onto the paper.

        The rescue ladder does not hold one. It rescues the previous
        LIVE file, and once a cycle completes that file is clean — so
        measured across eight protocol papers on 2026-08-23, every
        ``working.docx`` and every rescue copy in all of them carried 0
        insertions and 0 deletions. The markup existed between `build`
        and the author's accept and then nowhere at all, and the
        protocol's own "delete ``batch.docx`` after every promote" rule
        finished the job. An author who opened the manuscript afterwards
        could not see what had changed, and nothing in the package could
        tell them.

        A copy kept here is the audit trail: the one artifact that shows
        a batch as a batch. **It is never pruned** — :func:`prune_rescues`
        does not look in this folder, and thinning it would recreate
        exactly the gap it closes. Redlines are small next to what they
        record, and the folder is the answer to "what did that batch
        actually change?" long after `prev.docx` has moved on.

        Rebuilding one later is not a substitute. Word Compare over two
        clean generations reproduces a word-only batch, but a span that
        crosses an untracked apparatus pass cannot be rebuilt as an
        adjudicable redline at all: Compare will not serialize a
        bookmark insertion, so reject-all leaves the new anchors behind
        (``bookmarkStart 132 -> 142``, Aging_Well 2026-08-23).
        """
        return self.build_dir / "redlines"

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

    # The fallback is the shape every paper scaffolded before 2026-08-23
    # was given, and it stays a fallback rather than a default anyone
    # should rely on: `init` now adopts the author's file where it is,
    # and writes the path it adopted. A config that says nothing is an
    # old config, and it still resolves.
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
        doctor_skip=tuple(data.get("doctor", {}).get("skip", _DOCTOR_SPENT)),
        carry=tuple(batch_cfg.get("carry", ())),
    )


# ------------------------------------------------------------- registry

#: Where the list of papers on the protocol lives, and the environment
#: variable that moves it. The variable is not a convenience: without it
#: every test that scaffolds a paper would write into the real one, and
#: a registry the suite edits is a registry nobody can trust.
REGISTRY_ENV = "DOCXKIT_PAPERS"


def registry_path() -> Path:
    """The registry file: one absolute ``paper.toml`` path per line.

    Plain text, because it is a list a person edits — commenting a
    finished paper out with a `#` should not require knowing a format.
    """
    override = os.environ.get(REGISTRY_ENV)
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "docxkit" / "papers.txt"


def registered() -> list[Path]:
    """Every paper.toml the registry names, in the order it names them.

    Paths that no longer exist are KEPT and reported by :func:`survey`
    rather than dropped here: a project on a drive that happens to be
    disconnected is not a project that has been retired, and silently
    shrinking the list is how a paper stops being watched without
    anyone deciding that it should.
    """
    path = registry_path()
    if not path.is_file():
        return []
    out: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            out.append(Path(entry))
    return out


def register(config: str | Path) -> bool:
    """Add a paper's ``paper.toml`` to the registry; True if it is new."""
    config = Path(config).resolve()
    known = {p.resolve() if p.is_absolute() else p for p in registered()}
    if config in known:
        return False
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if path.stat().st_size == 0:
            fh.write("# Papers on the single-file revision protocol.\n"
                     "# `docxkit revision status --all` surveys these.\n"
                     "# One paper.toml per line; # comments one out.\n")
        fh.write(f"{config}\n")
    return True


def scan(root: str | Path, *, depth: int = 4) -> list[Path]:
    """Every ``paper.toml`` under `root`, registered and returned.

    Bounded by `depth` because the roots these live under are cloud
    folders with tens of thousands of files below them: an unbounded
    walk of one took over two minutes, and a survey nobody waits for is
    a survey nobody runs. Four levels reaches
    ``<root>/<area>/<project>/revision/paper.toml``.
    """
    root = Path(root)
    found: list[Path] = []
    for candidate in (f"{'*/' * n}{_CONFIG}" for n in range(depth + 1)):
        found += [p for p in root.glob(candidate) if p.is_file()]
    for config in sorted(found):
        register(config)
    return sorted(found)


@dataclass(frozen=True)
class Survey:
    """One paper's answer to "is anything waiting for me?"."""

    config: Path
    paper: Paper | None
    """None when the config could not be read — the row still appears."""
    state: State | None
    stale: tuple[str, ...] = ()
    """Parts where `prev.docx` no longer matches a SETTLED manuscript."""
    locked: bool = False
    staged: bool = False
    """A built batch is sitting in `build/`, promoted or not."""
    missing: bool = False
    """The config resolved and the file it names is not there."""
    error: str = ""

    @property
    def name(self) -> str:
        """The paper's name, and a usable one even when nothing loaded.

        `config.parent` is the `revision` FOLDER, so falling back to it
        labelled every broken row "revision" — the one row that most
        needs to say which paper it is.
        """
        if self.paper:
            return self.paper.name
        parent = self.config.parent
        return (parent.parent.name if parent.name == _DIR else parent.name) \
            or str(self.config)

    @property
    def verdict(self) -> str:
        """The single word this row is read for.

        "unreadable" and "missing" are different answers and want
        different responses: one is a config or a package this tool
        could not parse, the other is a manuscript that is not where the
        paper says it is — a moved file, or a drive not mounted.
        """
        if self.missing:
            return "missing"
        if self.error or self.paper is None or self.state is None:
            return "unreadable"
        if not self.state.is_truth:
            return "PROPOSAL"
        return "stale" if self.stale else "truth"


def survey(configs: Sequence[str | Path] | None = None) -> list[Survey]:
    """Every registered paper's state, in one pass.

    The protocol is single-paper by design and every command takes one
    `--paper`; nothing answered "which of them is waiting on me?". With
    nine papers open at once that question is the one an author actually
    has, and the answer was nine invocations of `status`.

    Read-only, and it never raises for one paper: a config that has
    moved, a manuscript that has been deleted or a package Word is
    part-way through writing all come back as a ROW rather than a
    traceback, because the row is the point — a survey that dies on the
    first bad entry cannot tell you about the eight good ones.
    """
    out: list[Survey] = []
    for entry in (configs if configs is not None else registered()):
        config = Path(entry)
        try:
            paper = load_paper(config)
        except Exception as exc:
            out.append(Survey(config=config, paper=None, state=None,
                              error=f"{type(exc).__name__}: {exc}"[:120]))
            continue
        if not paper.working.is_file():
            out.append(Survey(config=config, paper=paper, state=None,
                              missing=True,
                              error=f"no manuscript at {paper.working}"))
            continue
        try:
            current = state(paper.working)
            stale = tuple(drift(paper.working, paper.prev)) \
                if current.is_truth and paper.prev.is_file() else ()
        except Exception as exc:
            out.append(Survey(config=config, paper=paper, state=None,
                              error=f"{type(exc).__name__}: {exc}"[:120]))
            continue
        out.append(Survey(config=config, paper=paper, state=current,
                          stale=stale,
                          locked=package.is_locked(paper.working),
                          staged=paper.batch.is_file()))
    return out


# ---------------------------------------------------------------- state

@dataclass(frozen=True)
class State:
    """Which of the two states a file is in, and where the proof is."""

    path: Path
    by_part: dict[str, int]
    by_author: dict[str, int]
    #: kind -> the note ids whose DEFINITION is out of reference order.
    #: Empty for a file Word wrote; see :func:`footnotes.out_of_order`
    #: for what a file it did not costs.
    notes_unordered: dict[str, list[str]] = field(default_factory=dict)
    #: Was this read from a COPY, because Word holds the file? A
    #: snapshot mid-edit is a true statement about a moment and the
    #: alternative was no answer at all — but the reader has to be told
    #: which one they are looking at.
    from_snapshot: bool = False

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
    # READ-ONLY, and the moment it is most worth running is while the
    # author has the file open in Word — so a lock takes a snapshot and
    # says so rather than refusing (see `package.readable`).
    with package.readable(path) as (readable, snapshot):
        parts = package.read_parts(readable)
    return _state(parts, path, snapshot)


def _state(parts: dict[str, bytes], path: Path, snapshot: bool) -> State:
    """:func:`state` over parts already read.

    The state a caller reports has to name the AUTHOR'S file. `ingest`
    called `state(live)` with the snapshot copy it was reading from, so
    the report came back pointing at
    `<temp>/docxkit_snapshot_xxxx/working.docx` — deleted the moment
    the context manager closed — and said `from_snapshot=False` inside a
    report whose own flag said True. Two flags on one report, disagreeing
    about the same fact.
    """
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
    unordered = {}
    doc = parts.get(DOCUMENT, b"").decode("utf-8", "replace")
    for kind, part in (("footnote", FOOTNOTES), ("endnote", ENDNOTES)):
        blob = parts.get(part)
        if not blob:
            continue
        moved = footnotes.out_of_order(
            doc, blob.decode("utf-8", "replace"), kind=kind)
        if moved:
            unordered[kind] = moved
    return State(path=path, by_part=by_part, by_author=by_author,
                 notes_unordered=unordered, from_snapshot=snapshot)


def _drifted(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    """Which parts differ in MEANING, save-noise excluded."""
    parts = package.changed_parts(before, after)
    return sorted(name for bucket in ("changed", "added", "removed")
                  for name in parts[bucket] if name not in SAVE_NOISE)


def drift(working: str | Path, prev: str | Path) -> list[str]:
    """Which parts of the live file the baseline no longer matches.

    "Is anything still pending?" and "is the baseline still the file this
    one grew out of?" look like one question and are two. :func:`state`
    answers only the first, so the moment the author accepts everything
    in Word and saves, BOTH files read 0 pending -> truth while their
    content has diverged — ``prev.docx`` is still the pre-accept copy.
    A batch built then is built on a stale base, and nothing says so
    until ``promote`` refuses on a hash mismatch, *after* a Word Compare
    has been paid for.

    The accept is not the only way in. A batch whose revisions are all
    math-resolved leaves nothing pending either, so ``prev`` goes stale
    the instant that batch is promoted.

    Read-only, and compares MEANING rather than bytes
    (:func:`package.part_fingerprint`), skipping :data:`SAVE_NOISE` —
    a Word save re-mints rsids and the editing-time total in every
    round-trip, and a staleness warning that fires on all of them is one
    nobody reads.

    Returns the part names, because a warning is worth little without
    WHERE: ``word/document.xml`` is an edit to the paper, while
    ``word/footnotes.xml`` alone is one to a note.
    """
    return _drifted(package.read_parts(Path(prev)),
                    package.read_parts(Path(working)))


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
    #: Links, notes, bookmarks and comments the hand-back no longer
    #: carries. The one part of this report that is a FINDING rather
    #: than a description — see :func:`losses`.
    lost: list[Loss] = field(default_factory=list)
    #: Links the author re-labelled — anchor intact, visible text
    #: changed. A finding too, and deliberately NOT a loss: it does not
    #: block `baseline`. See :func:`relabelled_links`.
    relabelled: list[Relabelled] = field(default_factory=list)
    #: Was `working` read from a COPY, because the author has it open in
    #: Word? See :func:`docxkit.package.readable`.
    from_snapshot: bool = False

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
    # A SNAPSHOT while Word holds the file, rather than the refusal this
    # used to give at the one moment the command is most useful: the
    # protocol's resume ritual is "status, then ingest, both read-only",
    # and the author is usually still in the manuscript. Every read below
    # goes through the same copy, `compare` included — reading half the
    # answer from a file being edited and half from a snapshot of it
    # would be worse than either.
    with package.readable(working) as (live, snapshot):
        prev_parts = package.read_parts(prev)
        working_parts = package.read_parts(live)
        content = dict(_compare.compare(str(prev), str(live)))
    # Named for the author's file and built from the parts already read
    # out of the snapshot: one read, and a path the caller can open.
    working_state = _state(working_parts, working, snapshot)
    parts = package.changed_parts(prev_parts, working_parts)
    return IngestReport(
        lost=losses(working_parts, prev_parts),
        relabelled=relabelled_links(working_parts, prev_parts),
        working=working,
        prev=prev,
        from_snapshot=snapshot,
        content=content,
        changed_parts=[p for p in parts["changed"] if p not in SAVE_NOISE],
        noise_parts=[p for p in parts["changed"] if p in SAVE_NOISE],
        resaved=len(parts["resaved"]),
        added=parts["added"],
        removed=parts["removed"],
        working_state=working_state,
        prev_state=state(prev),
    )


# ---------------------------------------------------------------- build

def build(paper: Paper, revised: str | Path, out: str | Path | None = None,
          *, allow_math_resolve: bool = False,
          allow_pending_baseline: bool = False,
          allow_stale_baseline: bool = False, resolve_math: bool = True,
          force: bool = False,
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

    `resolve_math=False` is the third answer to the first of those, and
    the one to try first now: it leaves the equation revisions TRACKED
    rather than accepting them, so there is something to review and
    reject-all still restores the baseline. It is off by default only
    because the premise above held for years on Word's own save path;
    the Flat OPC route this build uses carried 1870 tracked revisions
    with the math kept on LI7 (2026-08-15), reject-all included.

    A third refusal has nothing to do with equations: a baseline that is
    no longer the generation the manuscript grew out of
    (:func:`drift`). `allow_stale_baseline=True` overrides it, and
    almost nothing should: the redline would present the author's own
    edits as the agent's proposals, and `promote` refuses such a batch
    on the hash anyway — one Word Compare later.
    `allow_pending_baseline` implies it, because a baseline that
    legitimately carries a proposal CANNOT match a clean manuscript —
    they are two names for one unusual state, and refusing the second
    after being told about the first is a gate arguing with its own
    override.

    `force` overrides the fourth refusal — the one
    :func:`docxkit.guard.check` raises when ``build/batch.docx`` has
    changed since docxkit wrote it. That guard is what stopped a spent
    batch being silently overwritten (Parental Style 2026-08-12) and it
    is worth keeping; what was NOT worth keeping is that the message
    named ``--force`` while neither this function nor the CLI had one,
    so the only way out the reader was told about did not exist.
    """
    out = Path(out) if out else paper.batch
    # `build/batch.docx` is where a BUILT batch is staged, and the stamp
    # beside it is how `guard.check` tells "docxkit wrote this" from
    # "someone edited it in Word". A hand-built clean edit written there
    # collides with that: the build refuses its own output as modified,
    # and the message sends the reader looking for a Word session that
    # never happened (2026-08-09, a cycle to diagnose). The path is
    # reserved; say so where the mistake is made.
    if Path(revised).resolve() == out.resolve():
        raise ProtocolError(
            f"{out.name} is where `revision build` STAGES its output, so it "
            f"cannot also be the clean edit it builds FROM — the provenance "
            f"stamp beside it would read the edit as a Word session. Write "
            f"the clean edit anywhere else in build/ (build/clean.docx is "
            f"the usual name) and pass that.")

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

    # Is the baseline still the file the manuscript grew out of? The
    # check above asks whether `prev` carries a proposal; this asks
    # whether it is the right generation at all. `drift`'s own docstring
    # named this gap and nothing closed it: after an accept in Word both
    # files read 0 pending while their content has diverged, and the
    # redline built then shows the AUTHOR's edits as the agent's
    # proposals. `promote` refuses it on the hash — but only after a
    # full Word Compare has been paid for, and after a reader has spent
    # the round trying to make sense of a redline about the wrong pair.
    if not (allow_stale_baseline or allow_pending_baseline) \
            and paper.working.exists() and paper.prev.exists() \
            and (moved := drift(paper.working, paper.prev)):
        listed = ", ".join(moved[:4])
        if len(moved) > 4:
            listed += f" and {len(moved) - 4} more"
        raise StaleBatch(
            f"{paper.prev.name} is no longer what {paper.working.name} "
            f"grew out of — {listed} differ(s). Something was "
            f"accepted or edited since the last baseline, so a redline "
            f"built on this baseline would present the author's own "
            f"changes as proposals, and `promote` would refuse it on the "
            f"hash afterwards. First:\n"
            f"    docxkit revision ingest     (what changed, read-only)\n"
            f"    docxkit revision baseline   (adopt it as the truth)\n"
            f"then build again.")

    notes: list[str] = []

    def _say(line: str) -> None:
        notes.append(line)
        if progress:
            progress(line)

    # Before Word sees it: a note whose DEFINITION sits out of reference
    # order renders correctly and passes every read-only gate, and
    # Compare then rewrites the definitions INTO document order — so the
    # part no longer lines up with the baseline's and reads as moved. On
    # AFI that was 81 glyph runs and a STRUCTURE count for a one-line
    # prose batch, reported against the batch that came after the one
    # that appended the note. Said here, where it is still cheap.
    for side, path in (("baseline", paper.prev), ("clean edit", revised)):
        side_parts = package.read_parts(path)
        doc = side_parts.get(DOCUMENT, b"").decode("utf-8", "replace")
        for kind, part in (("footnote", FOOTNOTES), ("endnote", ENDNOTES)):
            blob = side_parts.get(part)
            if not blob:
                continue
            moved = footnotes.out_of_order(
                doc, blob.decode("utf-8", "replace"), kind=kind)
            if moved:
                _say(f"{side}: {kind} definitions are not in document order "
                     f"({', '.join(moved[:6])}"
                     f"{' ...' if len(moved) > 6 else ''}) — Word's Compare "
                     f"will rewrite them, and the whole part then reads as "
                     f"MOVED. Reorder the definitions to match the "
                     f"references before building.")

    # `accept_check` is left ON, and the asymmetry is deliberate. The
    # reject side has a legitimate cause the protocol can see and gate 5
    # can judge (below); the accept side has none — a redline whose
    # accepted text is not the clean copy is not a batch to hand back,
    # and no later gate looks at that view.
    #
    # `reject_check=False` — the refusal, not the check: `tracked.build`
    # computes it either way and its notes come through `_say`. The
    # protocol REPORTS an unrejectable paragraph and lets gate 5 decide,
    # because one cause of it is legitimate and only visible from here:
    # a moved footnote REFERENCE makes Compare emit the whole note as an
    # insertion, so rejecting empties it. Refusing to produce the batch
    # would leave the author with the paragraph names and no file to look
    # at. A paper calling `tracked.build` directly has no gate 5, which
    # is why the default there is to refuse.
    report = tracked.build(paper.prev, revised, out, None,
                           author=paper.author, verify_in_word=True,
                           resolve_math=resolve_math, reject_check=False,
                           force=force, progress=_say,
                           carry=tracked.CARRIED_PARTS + paper.carry)

    for name in restored_bookmarks(package.read_parts(paper.prev),
                                   package.read_parts(revised),
                                   package.read_parts(out)):
        _say(f"bookmark {name!r}: your clean edit removed it and Compare "
             f"put it back — a bookmark is carried over from the ORIGINAL "
             f"side and cannot ship through a redline. Apply the deletion "
             f"to working.docx AFTER the promote; the revision count is "
             f"unaffected, a bookmark is not tracked content.")

    # What Compare baked in with no revision on it, named paragraph by
    # paragraph. The math count alone understated this badly: a merged,
    # rewritten math-bearing paragraph shipped WHOLE and untracked while
    # the batch read "7 revisions, 6 of them in the body". Read off the
    # WRITTEN file, so what is said describes the deliverable the author
    # is about to open rather than the parts that made it.
    base_parts = package.read_parts(paper.prev)
    built = package.read_parts(out)
    lost = untracked(built, base_parts)
    for note in moved_footnotes(built, base_parts):
        _say(f"footnote {note}: Compare emitted the whole note as an "
             f"insertion with no matching deletion — its REFERENCE moved. "
             f"Accepting is right; rejecting empties the note, so gate 5 "
             f"will fail on it.")
    for u in lost:
        _say(f"UNTRACKED {u}")
    if lost:
        _say(f"{len(lost)} paragraph(s) above differ from the baseline "
             f"with no revision on them: the author cannot refuse those "
             f"edits, and reject-all will not restore the baseline.")

    # The REPORT's own number, not a grep over the progress lines. The
    # note it used to match is a sentence `tracked.build` is free to
    # rewrite, and rewriting it would have disabled this refusal in
    # silence — a guard whose trigger is another module's prose is a
    # guard that stops guarding without anybody editing it.
    if report.math_resolved and not allow_math_resolve:
        raise MathResolved(
            f"{report.math_resolved} math revision(s) were accepted while "
            f"building {out.name}: those edits are baked in with nothing "
            f"to accept or reject, and reject-all will not restore the "
            f"baseline. This batch has NO reviewable redline as built. "
            f"Three ways on, in order: rebuild with "
            f"resolve_math=False, which keeps them tracked and is what "
            f"the Flat OPC route measured on LI7 supports; ship the batch "
            f"clean and record that in the log; or make the edit by "
            f"hand-authored markup on working.docx (the DSI vehicle).")
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
    #: WHICH paragraphs gate 5 disagrees on, and the named cause when
    #: there is one. Three booleans do not say whether the batch is
    #: salvageable, which is the decision their reader has to make.
    reject_diff: list[Untracked] = field(default_factory=list)
    moved_footnotes: list[int] = field(default_factory=list)
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

    @property
    def empty_shells(self) -> int:
        return self.accepted.get("empty_shells", 0)

    @property
    def ok(self) -> bool:
        """Every gate that ran said yes."""
        return (not self.lint
                and self.built_on_this_baseline is not False
                and self.word_opened is not False
                and not self.empty_shells
                and not self.lost_parts
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
                       "\u00a0": " ", "\u2217": "*",
                       # PRIME vs APOSTROPHE. Word's Range.Text returns
                       # U+2032 where the XML stores U+0027 in derivative
                       # notation. Parental_style writes V', S', a^E'(x)
                       # and a^X'(x) throughout its theory section, so the
                       # gate failed there with ZERO revisions in the file
                       # -- the same shape as the T* case above.
                       "\u2032": "'"})


@dataclass(frozen=True)
class GateResult:
    """One of the paper's own verification commands, and how it went."""

    command: str
    code: int
    """The process's exit code; -1 when it ran out of time."""
    seconds: float
    output: str
    """The tail of what it printed — enough to act on a failure."""

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def verdict(self) -> str:
        if self.code == -1:
            return "TIMED OUT"
        return "pass" if self.ok else f"FAIL ({self.code})"


def run_gates(paper: Paper, *, timeout: float = 900,
              progress: Any = None) -> Iterator[GateResult]:
    """Run ``[verify] commands`` from the paper's own config, streaming.

    **An iterator, so a caller reports each gate as it finishes.** The
    first version returned a list, which meant the CLI could only print
    after every gate had run: the `progress` heartbeat announced all of
    them up front and the verdicts arrived together at the end, which
    is precisely the "twelve silent minutes" the heartbeat was added to
    prevent. Consuming this drives the run — a caller that discards it
    runs nothing.

    **This module deliberately did not shell out**, and the reason is
    written into its docstring: what a paper checks is the paper's
    business, and a shared tool that runs per-project commands is a
    larger promise than the protocol makes. That reasoning holds for the
    DEFAULT and not for the capability. With nine papers on the
    protocol, "the gates are listed and you run them yourself" means
    they run when someone remembers, which is not what a gate is for.

    So: still not part of the ladder, still not run by `validate` unless
    asked (`--run-gates`), and when asked they run exactly as the config
    spells them, through the shell, from the project root. The commands
    are the author's own text in the author's own file; this neither
    parses nor sanitises them, and a caller who did not intend to run
    arbitrary commands should not pass the flag.

    A gate that hangs is a gate that fails: `timeout` bounds each one,
    and a timeout reports as code -1 rather than blocking a ladder that
    exists to be run before every hand-back.

    **`subprocess.run(..., timeout=)` does not deliver that on its own,
    and the first version of this shipped believing it did.** With
    `shell=True` the real gate is a GRANDCHILD — cmd.exe is the child —
    so the kill on timeout reaches the shell and not the process doing
    the work, and the surviving grandchild holds the stdout and stderr
    pipes open, which blocks the cleanup `run` performs before it
    re-raises. Measured on this machine: a `timeout=1` against a
    20-second sleep returned after **20.08s**. The same call without a
    shell returns in 1.03s. So the whole process TREE is killed here,
    and the reader is drained on a thread that cannot deadlock the
    parent.

    The test that certified the old behaviour passed for 30 seconds
    while asserting the exit code and never the clock — see
    `test_a_gate_that_HANGS`, which now asserts elapsed time.
    """
    import subprocess
    import threading
    import time

    for command in paper.gates:
        if progress:
            progress(f"gate: {command}")
        started = time.monotonic()
        code, text = _run_one(command, paper.root, timeout, subprocess,
                              threading)
        yield GateResult(command=command, code=code,
                         seconds=round(time.monotonic() - started, 1),
                         output="\n".join(text.splitlines()[-20:]))


def _kill_tree(proc: Any, subprocess: Any) -> None:
    """Kill the gate AND whatever the shell started for it.

    `proc.kill()` reaches cmd.exe and leaves the grandchild running with
    the pipes open. On Windows only `taskkill /T` walks the tree; on a
    POSIX box the session started by `start_new_session` is the handle.
    Best effort by construction — the point is to stop WAITING for it,
    and a kill that fails must not become a second hang.
    """
    import contextlib
    import sys
    # `sys.platform` rather than `os.name`: the type checker narrows on
    # it, and `os.killpg` / `signal.SIGKILL` do not exist on Windows at
    # all, so the branch has to be invisible there rather than merely
    # unreached.
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False, timeout=10)
        else:
            import os
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(Exception):
        proc.kill()


def _run_one(command: str, cwd: Path, timeout: float,
             subprocess: Any, threading: Any) -> tuple[int, str]:
    """One gate: its exit code and the text it printed.

    The reader runs on a daemon thread rather than through
    `communicate(timeout=)`, because that call is the one that waits on
    the pipes the orphaned grandchild is holding.
    """
    if not cwd.is_dir():
        # NOT 127: "command not found" sends the author hunting for a
        # missing tool when the real problem is that the project root
        # moved or its drive is offline.
        return 126, (f"cannot run gates: {cwd} is not a directory — the "
                     f"project root moved, or its drive is offline")
    import sys
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, shell=True, cwd=cwd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            **kwargs)
    chunks: list[str] = []

    def drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc, subprocess)
        reader.join(timeout=5)
        # What it printed BEFORE it hung is the whole diagnosis: a
        # pytest gate wedged on test 340 of 500 names that test here,
        # and the first version threw it away for the literal string
        # "no output within Ns".
        printed = "".join(chunks).rstrip()
        return -1, (f"{printed}\n[no further output within {timeout:g}s]"
                    if printed else f"no output within {timeout:g}s")
    reader.join(timeout=5)
    return proc.returncode, "".join(chunks)


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return "".join(re.sub(r"[\x00-\x1f]", "", folded).split())


#: What Word's ``Range.Text`` returns where an INLINE ``w:drawing``
#: sits: one U+002F SOLIDUS, measured on a synthetic package whose only
#: content was a picture and two letters (``'A/B\r'``, ord 47).
#:
#: This is deliberately NOT a `_FOLD` entry. Folding ``/`` away would
#: blind the gate to every "and/or" and every URL in the manuscript;
#: emitting the same character the other side emits keeps both.
#:
#: Three things the same probe settled, each of which would otherwise
#: have been guessed:
#:
#: * an ANCHORED drawing (``wp:anchor``, a floating figure) contributes
#:   NOTHING — it is not in the text stream at all;
#: * the legacy inline forms, ``w:pict`` and ``w:object``, give U+0001
#:   instead, which `_norm` already strips as a control character. They
#:   need no placeholder, and giving them this one would break them;
#: * a TEXT BOX's prose is a different STORY, and `doc.Paragraphs` does
#:   not walk it — hence `main_story` below.
_DRAWING_GLYPH = "/"

WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def _glyph(root: Any | None, *, main_story: bool = False) -> str:
    """Every rendered character, prose and math alike, in document order.

    `main_story` narrows the walk to what Word's ``doc.Paragraphs``
    covers, for the gate that compares this stream against Word's own:
    a text box is a separate story, so its prose is absent from
    ``Range.Text`` while it sits in ``document.xml`` like any other
    paragraph. Left in, the gate reports a difference for every text box
    in the manuscript — and it is off by default because the XML-to-XML
    gate above WANTS that prose compared.

    Pruning `w:txbxContent` also disposes of an `mc:AlternateContent`
    hazard for free: Word writes a shape's text twice, once under
    `mc:Choice` and once in the VML `mc:Fallback`, and only one of them
    is ever rendered.
    """
    if root is None:
        return ""
    out: list[str] = []
    stack: list[Any] = [root]
    while stack:
        el = stack.pop()
        tag = el.tag
        if not isinstance(tag, str):
            continue                       # a comment or a PI
        if tag in (W + "t", M + "t"):
            out.append(el.text or "")
            continue                       # a leaf: nothing below it
        if tag == W + "drawing":
            if el.find(WP + "inline") is not None:
                out.append(_DRAWING_GLYPH)
        elif main_story and tag == W + "txbxContent":
            continue
        stack.extend(reversed(list(el)))   # depth-first, document order
    return "".join(out)


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


def _links(parts: dict[str, bytes]) -> Counter[tuple[str, str]]:
    """``(anchor, label)`` for every internal link, every text part.

    The fourth thing gate 5 compares, and the one it was blind to.
    Rejecting a batch that DELETED linked text restores the sentence as
    PLAIN TEXT: Word's Compare does not rebuild a hyperlink inside a
    rejected deletion, so the words come back and the link does not.
    Parental Style T4(3) came back 227 links against the baseline's 229,
    with `reject-all` reporting OK and `citations` ALL CHECKS PASSED —
    both later mentions, so nothing dangled — and the author two links
    short with nothing anywhere saying so (2026-08-12).

    Counted as a MULTISET of pairs, not as a total: a link that survives
    at a different place is not a link that was lost, and a total hides
    a swap. Both link forms are read, because Word rewrites a field into
    an element on every author save and the two must not read as one
    lost and one gained.
    """
    out: Counter[tuple[str, str]] = Counter()
    for _name, xml in text_parts(parts):
        # Word's own anchor is re-minted on every Compare, so the NAME
        # is not a fact about the document; the visible label is, and it
        # is what a reader would miss. Keyed under one stand-in, a
        # cross-reference that really went still reports as lost, and a
        # rebuild of the same one does not.
        out.update((WORD_ANCHOR if word_minted(a) else a, label)
                   for a, label in internal_links(xml))
    return out


def _bookmarks(parts: dict[str, bytes]) -> set[str]:
    return {n for name, blob in parts.items()
            if name in TEXT_PARTS
            for n in BOOKMARK_NAME_RE.findall(blob.decode("utf-8", "replace"))
            if not word_minted(n)}          # Word's own _Toc/_Ref names


@dataclass(frozen=True)
class Loss:
    """Structure the hand-back no longer carries, named so it can be OK'd."""

    kind: str        # link | footnote | endnote | bookmark |
                     # comment | glyph
    what: str        # the anchor, the note's text, the bookmark's name

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.what}"

    def __str__(self) -> str:
        return f"{self.kind} {self.what[:70]!r}"


@dataclass(frozen=True)
class Relabelled:
    """A link whose ANCHOR survived and whose visible text changed."""

    anchor: str
    was: str
    now: str

    def __str__(self) -> str:
        return f"link {self.anchor}: {self.was[:40]!r} -> {self.now[:40]!r}"


def _link_changes(working: dict[str, bytes], prev: dict[str, bytes],
                  ) -> tuple[list[Loss], list[Relabelled]]:
    """Links the hand-back LOST, and links it merely RE-LABELLED.

    `_links` keys a link by the (anchor, label) pair, which is right for
    finding a link Word ate — and reads an author's own edit of the
    visible text as a loss. DSI's R24.1 re-labelled four back-link
    fields on purpose («UN 2026» -> «United Nations 2026»); all four
    bookmarks were present, all four fields still named them, and
    `citations.audit_links` reported 152 links and 0 broken. `baseline`
    refused anyway, and the paper passed `--accept-loss` four times
    after checking each anchor by hand (2026-08-19).

    A gate that refuses a legitimate edit teaches the person to wave it
    through, and the next real loss goes the same way. So the pair is
    split on the one fact that decides it: a link is LOST when its
    anchor is no longer linked from anywhere in the hand-back, and
    RE-LABELLED when it is. Only the first blocks.

    Paired off one for one, so an anchor that was linked twice and comes
    back once still reports the link that went: each gone label consumes
    one gained label for the same anchor, and what is left over is a
    loss.
    """
    was, now = _links(prev), _links(working)
    gained = Counter(now - was)
    still_linked = {anchor for anchor, _label in now}
    lost: list[Loss] = []
    relabelled: list[Relabelled] = []
    for anchor, label in sorted((was - now).elements()):
        fresh = sorted(lab for (a, lab), n in gained.items()
                       if a == anchor and n > 0)
        if anchor in still_linked and fresh:
            gained[(anchor, fresh[0])] -= 1
            relabelled.append(Relabelled(anchor, label, fresh[0]))
        else:
            lost.append(Loss("link", f"{anchor} ({label[:40]})"))
    return lost, relabelled


def relabelled_links(working: dict[str, bytes],
                     prev: dict[str, bytes]) -> list[Relabelled]:
    """Links whose visible text an author changed, anchors intact.

    Reported, never refused — see :func:`_link_changes` for why the two
    are told apart at all.
    """
    return _link_changes(working, prev)[1]


def losses(working: dict[str, bytes],
           prev: dict[str, bytes]) -> list[Loss]:
    """What an author's Word session destroyed, and no text diff shows.

    The protocol's safety claim is that ``working.docx`` is the one file
    and its state is readable. Between the hand-back and
    :func:`baseline`, nothing used to fail on lost CONTENT: `ingest`
    printed it, `validate` checked the batch (and on a hand-back there
    is no batch), and `baseline` copied.

    **LI7, 2026-08-15.** The manuscript came back missing three Figure 4
    cross-references, a European Commission 2024 citation, and footnote
    15 entire — note, reference, and the link inside it. Measured
    through the chain, nothing the toolkit built had lost them:

    ======================  =====  =====  =====
    stage                   body   note   notes
                            links  links
    ======================  =====  =====  =====
    prev                    33     15     19
    the edited clean build  33     15     19
    the Compare redline     33     15     19
    after the author's      **28** **14** **18**
    session
    ======================  =====  =====  =====

    Word had collapsed one paragraph into a single run to make four
    copyedits, and every link and the note reference in it went at once.
    Then it RENUMBERED: 19 notes became 18 with the ids still
    contiguous, so there is no gap to notice and no id to miss. Counting
    is the only way to see it, which is why the notes are matched on
    their TEXT here rather than on their id.

    Returns one entry per lost thing. Empty is the ordinary case: an
    author who edits prose loses none of this — and, since 2026-08-19,
    an author who RE-LABELS a link keeps it: see
    :func:`relabelled_links`, which is reported rather than refused.
    """
    out: list[Loss] = []
    out += _link_changes(working, prev)[0]
    out += _lost_notes(working, prev)
    out += _downgraded_math(working, prev)
    out += [Loss("bookmark", name)
            for name in sorted(_bookmarks(prev) - _bookmarks(working))]
    lost_comments = (tracked.package_counts(prev)["comments"]
                     - tracked.package_counts(working)["comments"])
    if lost_comments > 0:
        out.append(Loss("comment", f"{lost_comments} comment(s) gone"))
    return out


def _downgraded_math(working: dict[str, bytes],
                     prev: dict[str, bytes]) -> list[Loss]:
    """Equation runs the author's Word session flattened to ASCII.

    Word rewrites OMML on accept-and-save as readily as on Compare, and
    downgrades U+2212 MINUS SIGN to a hyphen while it is there. It is
    not a content change and no text gate sees it: `losses` counted
    links, notes, bookmarks and comments, and the paper still rendered.

    AFI lost all four of its minus signs this way, twice — wave 1 and
    wave 2 — and `baseline` copied the result over `prev.docx` both
    times, after which the hyphens ARE the truth and the next reject-all
    measures against them. The paper's own log records the workaround as
    "not optional on this manuscript".

    Reported as a LOSS rather than repaired here, and matched the way
    `restore_math_glyphs` matches: a run the baseline has is gone, and a
    run has appeared that is exactly it with the glyphs flattened. An
    author who genuinely rewrote an equation is not reported, because
    the two texts would not correspond that way.
    """
    def runs(parts: dict[str, bytes]) -> Counter[str]:
        found: Counter[str] = Counter()
        for name, blob in parts.items():
            if name.endswith(".xml"):
                found.update(m.group(2) for m in
                             _MATH_T_RE.finditer(blob.decode("utf-8",
                                                             "replace")))
        return found

    was, now = runs(prev), runs(working)
    gained = now - was
    return [Loss("glyph", f"{text} -> {_downgraded(text)}")
            for text, _n in sorted((was - now).items())
            if _downgraded(text) != text and gained.get(_downgraded(text))]


def _notes(parts: dict[str, bytes], part: str, kind: str) -> list[Any]:
    from .footnotes import find_all

    blob = parts.get(part)
    if blob is None:
        return []
    return [f for f in find_all(blob.decode("utf-8", "replace"), kind=kind)
            if f.text]


def _lost_notes(working: dict[str, bytes],
                prev: dict[str, bytes]) -> list[Loss]:
    """Notes the hand-back no longer HAS — never merely reworded ones.

    The first version compared note TEXT as a multiset, so editing one
    character inside a footnote read as the old note having vanished.
    LI7 hit it the same day (2026-08-15) and it BLOCKED the paper: gate
    D4 split a section, footnote 13's "throughout Sections 4-6" became
    "4-7", and `baseline` refused to record a manuscript that had lost
    nothing. Text is the right identity for a link LABEL and the wrong
    one for a note, because a note is prose an author edits.

    So the decision is made on the REFERENCE: a note whose marker is
    still in the body has not been lost, however much its wording
    changed. Counting rather than matching ids, because Word renumbers
    ids on save — that is the whole reason the ids cannot be trusted
    here (see :func:`docxkit.renumber.footnotes`).

    The text is still used, but only to SAY which note went: a
    description for the reader, never the test.
    """
    out: list[Loss] = []
    for kind, part in (("footnote", FOOTNOTES), ("endnote", ENDNOTES)):
        was = _notes(prev, part, kind)
        now = _notes(working, part, kind)
        gone = len(was) - len(now)
        if gone <= 0:
            continue
        # which ones, best effort: the notes whose text no longer
        # appears anywhere. A reworded note matches nothing either, so
        # take only as many as the COUNT says are really missing, and
        # say plainly when we cannot name them.
        texts = Counter(f.text for f in now)
        missing = [f.text for f in was if not texts[f.text]]
        named = sorted(missing)[:gone]
        out += [Loss(kind, text) for text in named]
        if len(named) < gone:
            out.append(Loss(kind, f"{gone - len(named)} more, unnamed — "
                                  f"{len(was)} {kind}s before, {len(now)} now"))
    return out


def _unmet(accepted: tuple[str, ...], found: list[Loss]) -> list[str]:
    """Declared losses that did NOT happen.

    A stale exemption is worse than no exemption: it is a switched-off
    gate that reads as a switched-on one, and the next real loss goes
    through it silently. So naming something that is still present is
    itself a refusal.

    Matched by PREFIX, in both directions, because the refusal prints a
    truncated description and a reader copies what they were shown. A
    hatch that will not accept the message's own words is not a hatch —
    LI7 tried all three documented forms of the same footnote and every
    one came back "has NOT lost" while the refusal insisted it had
    (2026-08-15).
    """
    return [token for token in accepted
            if not any(_names(token, loss) for loss in found)]


def _names(token: str, loss: Loss) -> bool:
    """Does `token` identify `loss`? Prefixes count, either way round."""
    token = token.strip()
    for candidate in (loss.key, loss.what, f"{loss.kind}:{loss.what}"):
        if token == candidate or candidate.startswith(token) \
                or token.startswith(candidate):
            return True
    return False


def restored_bookmarks(baseline: dict[str, bytes], clean: dict[str, bytes],
                       built: dict[str, bytes]) -> list[str]:
    """Bookmarks the clean edit REMOVED and Compare put back.

    Word's Compare carries bookmarks over from the ORIGINAL side, so a
    deletion made in the clean copy is silently undone in the redline —
    and nothing in the counts shows it, because a bookmark is not
    tracked content. The orphan `Lari2023` survived two full rounds that
    way, and dropping the `Conley1999` and `Ingoglia2021` entries hit it
    again: `citations` on the built batch reported STALE BOOKMARK and
    REF WITHOUT CITE for entries that were no longer in the document.

    Three sides are needed, and the BASELINE is the one that makes the
    answer mean something: "in the build, not in the clean edit" also
    describes a name Word MINTED during the compare, and reporting that
    as the author's deletion sends them looking for an edit they never
    made. Only a name the baseline already carried is one the clean edit
    can have removed.
    """
    return sorted((_bookmarks(baseline) & _bookmarks(built))
                  - _bookmarks(clean))


#: A footnote Compare emitted as one insertion with nothing to delete.
#: The shape of a note definition is `_xml`'s to state.
_MOVED_NOTE_RE = NOTE_DEF_RE[FOOTNOTES]


def moved_footnotes(parts: dict[str, bytes],
                    baseline: dict[str, bytes]) -> list[int]:
    """Footnote ids whose whole body Compare wrapped in ``w:ins``.

    When a footnote's REFERENCE moves — same note, new position in the
    text — Word's Compare treats the note as brand new: its body is one
    insertion with **no matching deletion**. Accepting is right;
    rejecting empties the footnote, so a batch carrying one cannot pass
    gate 5 and the reason is invisible in the counts (Parental Style
    2026-08-10, footnote 2 re-anchored onto a new opening sentence).

    A footnote that carries insertions AND deletions is an ordinary
    edit; one that is new in this batch is a genuinely new note. So the
    shape is: insertions, no deletions, and the id already had text in
    the baseline.
    """
    was = {int(m.group(1)): visible_text(m.group(2))
           for m in _MOVED_NOTE_RE.finditer(
               baseline.get(FOOTNOTES, b"").decode("utf-8"))}
    out: list[int] = []
    for m in _MOVED_NOTE_RE.finditer(
            parts.get(FOOTNOTES, b"").decode("utf-8")):
        nid, body = int(m.group(1)), m.group(2)
        if nid < 1 or not was.get(nid, "").strip():
            continue                    # separators, and notes that are new
        if "<w:ins " in body and "<w:del " not in body:
            out.append(nid)
    return out


def _shown(text: str, *, limit: int = 12) -> str:
    """A run of characters, with its code points when it is short.

    The code points are the point: a hyphen-minus and a MINUS SIGN print
    identically in a terminal at 10pt, and telling them apart is the
    whole finding.
    """
    cut = text[:limit]
    tail = "..." if len(text) > limit else ""
    points = (" " + " ".join(f"U+{ord(c):04X}" for c in cut)
              if 0 < len(cut) <= 4 else "")
    return f"{cut + tail!r}{points}"


def glyph_runs(before: str, after: str, *, limit: int = 6,
               context: int = 24) -> list[str]:
    """Where two rendered-character streams differ, in reading order.

    The glyph gate compares two streams tens of thousands of characters
    long and answers with one boolean, which tells its reader only that
    SOMETHING moved. On AFI the answer was two characters — a minus sign
    Word's Compare had rewritten as a hyphen inside an equation — and
    finding them took a bespoke difflib script over private imports,
    three builds after the gate first went red.

    `limit` runs, because a batch that really did lose a paragraph would
    otherwise print the paragraph; the count of the rest is kept.
    """
    if before == after:
        return []
    out: list[str] = []
    blocks = SequenceMatcher(None, before, after,
                             autojunk=False).get_opcodes()
    changed = [op for op in blocks if op[0] != "equal"]
    for _tag, i1, i2, j1, j2 in changed[:limit]:
        lead = before[max(0, i1 - context):i1].replace("\n", " ")
        out.append(f"at {i1}: {_shown(before[i1:i2])} -> "
                   f"{_shown(after[j1:j2])}   after ...{lead}")
    if len(changed) > limit:
        out.append(f"... and {len(changed) - limit} more run(s)")
    return out


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
    from . import pages as _pages
    from . import word as _word

    batch = Path(batch)
    wanted = [a for a in anchors if a.strip()]
    if not wanted:
        return {}
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


def validate(path: str | Path, baseline: str | Path | None = None,
             *, use_word: bool = True) -> ValidateReport:
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
    """
    path = Path(path)
    parts = package.read_parts(path)
    report = ValidateReport(path=path,
                            baseline=Path(baseline) if baseline else None)

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
        # The PACKAGE, before its text: the reject-all gate below proves
        # the words round-trip, and a part that is not there has no words
        # for it to read.
        report.lost_parts = package.missing_parts(parts, base)
        was, now = _links(base), _links(rejected)
        body_now, body_was = _glyph(_root(rejected)), _glyph(_root(base))
        notes_now = _glyph(_root(rejected, FOOTNOTES))
        notes_was = _glyph(_root(base, FOOTNOTES))
        struct_was = structure_counts(base)
        struct_now = structure_counts(rejected)
        detail = {
            "paragraphs": _paras(_root(rejected)) == _paras(_root(base)),
            "glyphs": body_now == body_was,
            "footnotes": notes_now == notes_was,
            "links": was == now,
            "structure": struct_was == struct_now,
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
            report.lost_links = [f"-> {a} ({label[:40]!r})"
                                 for a, label in sorted((was - now).elements())]
            report.structure_diff = structure_diff(
                struct_was, struct_now)

    if word_accept_glyph is not None:
        report.accept_paths_agree = (
            _norm(_glyph(acc_root, main_story=True))
            == _norm(word_accept_glyph))
    return report


# -------------------------------------------------------------- promote

@dataclass(frozen=True)
class PromoteReport:
    promoted: Path
    onto: Path
    rescue: Path
    redline: Path | None = None
    pruned: tuple[Path, ...] = ()


def redline_path(paper: Paper, when: datetime | None = None) -> Path:
    """The next redline file: ``build/redlines/working_redline_<stamp>.docx``.

    Same stamped shape as :func:`rescue_path`, and for the same reason:
    a counter takes the first FREE number, so pruning would make the
    next name older than the one beside it. Nothing prunes this folder,
    but the two are read together — a redline and the rescue taken in
    the same promote sort adjacent — and one shape is easier to read
    than two.
    """
    return _stamped(paper, paper.redline_dir, "redline", when)


def rescue_path(paper: Paper, when: datetime | None = None) -> Path:
    """The next rescue file: ``build/rescue/working_rescue_<stamp>.docx``.

    A taken name advances the stamp by a microsecond rather than gaining
    a suffix, so every rescue in a folder has the SAME shape and sorts
    chronologically as a plain string. See :data:`_RESCUE_STAMP` for the
    version that did not and what it cost.
    """
    return _stamped(paper, paper.rescue_dir, "rescue", when)


def _stamped(paper: Paper, folder: Path, kind: str,
             when: datetime | None = None) -> Path:
    """``<folder>/<stem>_<kind>_<stamp><suffix>``, first free stamp."""
    moment = when or datetime.now()
    stem, suffix = paper.working.stem, paper.working.suffix
    for _ in range(1000):
        name = f"{stem}_{kind}_{moment.strftime(_RESCUE_STAMP)}{suffix}"
        candidate = folder / name
        if not candidate.exists():
            return candidate
        moment += timedelta(microseconds=1)
    raise ProtocolError(
        f"no free {kind} name near {moment:%Y-%m-%d %H:%M:%S} in {folder}")


def rescues(paper: Paper) -> list[Path]:
    """Every rescue copy, oldest first."""
    if not paper.rescue_dir.is_dir():
        return []
    return sorted(paper.rescue_dir.glob(_RESCUE_GLOB + paper.working.suffix))


def redlines(paper: Paper) -> list[Path]:
    """Every kept redline, oldest first.

    The counterpart of :func:`rescues`, and it exists for the same reason
    that one does: the copies are stamped rather than numbered, so sorting
    them as strings sorts them chronologically, and a caller should not
    have to know that to list them.

    The asymmetry with rescues is deliberate and worth stating here, since
    the two folders sit side by side. A rescue is TRANSIENT — it undoes the
    promote that just happened, and `prune_rescues` thins it to
    ``[batch] rescue_keep``. A redline is the RECORD, it is what a batch
    actually proposed, and nothing prunes it: see :attr:`Paper.redline_dir`
    for what it cost to learn that.
    """
    if not paper.redline_dir.is_dir():
        return []
    return sorted(paper.redline_dir.glob(
        f"{paper.working.stem}_redline_*{paper.working.suffix}"))


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

    **Two copies are made, and they are not the same kind of thing.** The
    rescue above holds the file being REPLACED, and it is transient. The
    REDLINE — the batch itself — is copied into ``build/redlines/``
    before the manuscript is overwritten, and it is permanent: nothing
    prunes that folder, and :func:`redlines` lists it. It is taken here
    because this is the last moment the markup exists as a file of its
    own; the author's accept then flattens it, and after that no gate,
    no diff and no rescue copy can say what the batch proposed. See
    :attr:`Paper.redline_dir` for the measurement that established it.

    So there is a third refusal beside the lock and the hash: **if the
    redline copy does not verify, the promote is refused and the partial
    file is deleted.** A truncated copy left in the one folder nothing
    prunes, stamped and named exactly like a good one, would be an audit
    trail that lies — worse than a gap, because a gap is visible.
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

    live_hash, base_hash = _guard.sha256(live), _guard.sha256(base)
    if live_hash != base_hash:
        raise StaleBatch(
            f"{live.name} no longer matches the baseline this batch was "
            f"built on (live {live_hash[:16]}, baseline "
            f"{base_hash[:16]}). The author has edited it. Re-baseline "
            f"from the live file, rebuild the batch on top of it, "
            f"re-validate, then promote.")

    # …and the other direction, which is the one that loses work
    # silently. The check above asks whether the AUTHOR moved; this asks
    # whether the BATCH did. A refused build leaves the previous redline
    # in `build/batch.docx`, live and base stay in sync, and promoting
    # copies a generation from before an entire author round over the
    # manuscript with the rescue copy as the only way back and no gate
    # having said a word (Aging_Well R5, 2026-08-21).
    built_on = _guard.base_of(batch)
    if built_on is not None and built_on != base_hash:
        raise StaleBatch(
            f"{batch.name} was not built on {base.name}: it says it was "
            f"built on {built_on[:16]} and this baseline is "
            f"{base_hash[:16]}. It is a redline of an older truth — "
            f"promoting it would replace {live.name} with a generation "
            f"from before whatever has been baselined since. Rebuild the "
            f"batch on the current baseline and re-validate. (If the "
            f"build was REFUSED, this file is the previous batch: delete "
            f"it and build again.)")

    paper.rescue_dir.mkdir(parents=True, exist_ok=True)
    rescue = rescue_path(paper)
    shutil.copy2(live, rescue)
    if _guard.sha256(rescue) != _guard.sha256(live):
        raise ProtocolError(
            f"the rescue copy did not land: {rescue} — refusing to "
            f"overwrite {live.name} with nothing to undo it")

    # Keep the redline BEFORE the batch stops being a separate file.
    # `promote` is the last moment the markup exists anywhere: the
    # rescue above is the previous LIVE file and is clean, `live` is
    # about to become a proposal that the author's accept will flatten,
    # and the protocol used to delete `batch.docx` right after this.
    # Copy first, verify the hash, and only then overwrite — a redline
    # that did not land is worth refusing the promote for, because the
    # thing it records is about to be the only copy.
    paper.redline_dir.mkdir(parents=True, exist_ok=True)
    redline = redline_path(paper)
    shutil.copy2(batch, redline)
    if _guard.sha256(redline) != _guard.sha256(batch):
        # Take the bad copy with us. A truncated file left here would sit
        # in the ONE folder nothing prunes, stamped and named exactly like
        # a good redline, and the batch it claims to record would be the
        # thing nobody could reconstruct. An audit trail with a corrupt
        # entry in it is worse than a gap, because a gap is visible.
        redline.unlink(missing_ok=True)
        raise ProtocolError(
            f"the redline copy did not land: {redline.name} — refusing to "
            f"promote, because after the author accepts, this batch's "
            f"markup would exist nowhere. The partial copy has been "
            f"removed; {rescue.name} still holds the file this would have "
            f"replaced.")

    shutil.copyfile(batch, live)
    if _guard.sha256(live) != _guard.sha256(batch):
        raise ProtocolError(f"the copy did not land: {live}")

    # only after the promote has landed: a prune that ran first could
    # delete the one copy this promote was about to need. Redlines are
    # not pruned at all — see `Paper.redline_dir`.
    return PromoteReport(promoted=batch, onto=live, rescue=rescue,
                         redline=redline,
                         pruned=tuple(prune_rescues(paper)))


@dataclass(frozen=True)
class Verdict:
    """What one cycle did to the manuscript, and what the author decided.

    Both halves are recoverable from the files and neither was recorded
    anywhere: after adjudication the manuscript reads 0 pending whether
    every revision was accepted, every one rejected, or half of each,
    and `log.md`'s outcome column was filled in by hand or not at all.
    """

    changed: int
    """Paragraphs whose text differs from the previous truth."""
    added: int
    removed: int
    proposed: tuple[int, int] = (0, 0)
    """(insertions, deletions) the batch carried, when one can be read."""
    kept: int = 0
    """Paragraphs the author kept AS PROPOSED."""
    reverted: int = 0
    """Paragraphs the author kept as they were."""
    authored: int = 0
    """Paragraphs in neither view — the author's own words."""
    links: tuple[int, int] = (0, 0)
    """(added, lost) citation links — an apparatus pass, not prose.

    A PAIR, and not the net total the first version reported, because
    `_links`' own docstring says why: "Counted as a MULTISET of pairs,
    not as a total ... a total hides a swap". It hid one. Measured: a
    round that keeps Lari's link, drops Deaton's to plain text and adds
    Sen's reported `links=0` and printed nothing, while
    `_link_changes` in the same module correctly named the lost one.
    That is the Parental Style T4(3) class — 227 against 229 — which
    this module exists to catch.
    """
    bookmarks: tuple[int, int] = (0, 0)
    """(added, lost) bookmarks, by NAME.

    Word's Compare cannot serialize a bookmark insertion, so a pass that
    adds them runs untracked and no redline can show it. Counted as a
    set difference rather than a length delta for the same reason as
    the links: re-keying a bibliography removes N anchors and adds N
    others, and `len(a) - len(b)` is zero for it.
    """
    batch: Path | None = None
    """The proposal this verdict is about, when it could be identified."""

    @property
    def offered(self) -> int:
        return self.kept + self.reverted

    @property
    def apparatus_only(self) -> bool:
        """A pass that moved the machinery and not one visible word.

        The shape Word's Compare cannot carry: linking the citations
        adds bookmarks, `tracked.build` refuses the batch
        (`bookmarkStart 132 -> 142`), so the pass runs untracked and in
        place. Nothing was left for the author to adjudicate and nothing
        recorded that it happened — which is the point of naming it.

        **Requires that no batch was identified**, and that is a real
        condition rather than an implementation detail: with a staged
        proposal in `build/`, this round is a batch round whatever else
        happened to the apparatus, and calling it an apparatus pass
        would name the wrong event. The cost is that a linking pass run
        in place while a valid batch sits unpromoted is reported as an
        adjudication of a batch nobody acted on — resolve before
        extend, and the two are not meant to overlap.
        """
        return (not self.changed and not self.added and not self.removed
                and self.batch is None
                and bool(any(self.links) or any(self.bookmarks)))

    @property
    def outcome(self) -> str:
        """The verdict, in the words a log row wants.

        "accepted in full" survives the author ALSO having edited: those
        are counted separately, because "31 accepted and two sentences
        of my own" is the ordinary shape of a round and reporting it as
        "partly adjudicated" would be wrong about the part that matters.
        """
        if self.apparatus_only:
            return "untracked apparatus pass (nothing to adjudicate)"
        if self.batch is None:
            return "adjudicated (no batch to compare against)"
        if not self.offered:
            return "nothing to adjudicate"
        if not self.reverted:
            verdict = "accepted in full"
        elif not self.kept:
            verdict = "rejected in full"
        else:
            verdict = f"{self.kept} of {self.offered} kept as proposed"
        extra = f", +{self.authored} authored" if self.authored else ""
        return verdict + extra

    def summary(self) -> str:
        """The `changes` cell: what moved between the two truths."""
        bits = [f"{self.changed} ¶ changed"] if self.changed else []
        if self.added:
            bits.append(f"{self.added} added")
        if self.removed:
            bits.append(f"{self.removed} removed")
        ins, dele = self.proposed
        if ins or dele:
            bits.append(f"from {ins + dele} revisions ({ins} ins, {dele} del)")
        for (added, lost), what in ((self.links, "link"),
                                    (self.bookmarks, "bookmark")):
            if added:
                bits.append(f"+{added} {what}{'' if added == 1 else 's'}")
            if lost:
                bits.append(f"-{lost} {what}{'' if lost == 1 else 's'}")
        return ", ".join(bits) or "no visible change"


def _para_counts(parts: dict[str, bytes], view: str) -> Counter[str]:
    """Every paragraph's visible text on one side of the markup.

    Named apart from `tracked._paras`, which this module already
    imports and which answers a different question. The checkers caught
    the collision; a silent redefinition would have sent one of the two
    callers to the wrong function.
    """
    out: Counter[str] = Counter()
    for name in TEXT_PARTS:
        blob = parts.get(name)
        if blob:
            out.update(t for t in revisions.text(blob.decode("utf-8"), view)
                       if t.strip())
    return out


def _proposal(paper: Paper) -> Path | None:
    """The batch this manuscript grew out of, or None if it cannot be
    identified with certainty.

    The stamp is what makes it certain: `guard.base_of` says which
    baseline a batch was built on, so a `batch.docx` left over from an
    earlier round — the exact file the stale-batch guards exist for — is
    not mistaken for the proposal the author just adjudicated. An
    unstamped batch answers "cannot tell", and this returns None rather
    than counting one round's verdict against another's proposal.
    """
    batch = paper.batch
    if not batch.is_file() or not paper.prev.is_file():
        return None
    built_on = _guard.base_of(batch)
    return batch if built_on == _guard.sha256(paper.prev) else None


def verdict(paper: Paper) -> Verdict:
    """What this cycle changed, and what the author did with the batch.

    Read-only, and called BEFORE `prev.docx` is replaced — the whole
    computation is against the truth the batch was built on.

    The adjudication is counted per PARAGRAPH rather than per revision,
    and that is the honest unit here: a revision's identity does not
    survive the author's Word session, but the text of the paragraph it
    proposed does. Paragraphs the accepted and rejected views disagree
    about are the ones the batch touched; which version of each the
    manuscript now holds is the verdict. Counted as multisets, so a
    paragraph moved rather than edited is not read as one of each.
    """
    from . import compare as _compare  # deferred: heavy import chain

    work = package.read_parts(paper.working)
    if not paper.prev.is_file():
        return Verdict(changed=0, added=0, removed=0)
    base = package.read_parts(paper.prev)
    # `compare_docs` on parts already in hand, rather than `compare` on
    # two paths: these manuscripts run to several MB and the path form
    # unzips and parses both again, on top of the two reads here and
    # the four walks below. Same answer, half the reading.
    report = _compare.compare_docs(_compare.load_parts(base),
                                   _compare.load_parts(work))
    structure = Counter(entry["type"] for entry in report["structure"])

    batch = _proposal(paper)
    kept = reverted = authored = 0
    proposed = (0, 0)
    if batch is not None:
        parts = package.read_parts(batch)
        counts = tracked.package_counts(parts)
        proposed = (counts["insertions"], counts["deletions"])
        final, original = _para_counts(parts, revisions.FINAL), \
            _para_counts(parts, revisions.ORIGINAL)
        live = _para_counts(work, revisions.FINAL)
        # Subtract the CONTEXT — the paragraphs both views share —
        # before asking which version the manuscript kept. Without it
        # the question degrades from "is this text where the batch put
        # it" to "is this text anywhere in the document", and a
        # paragraph that already existed elsewhere answers yes whatever
        # the author decided. Measured on a synthetic pair: a batch
        # proposing text that appears elsewhere reported "1 of 2 kept
        # as proposed" both when the author accepted everything and
        # when they rejected everything. Table cells make this the
        # ordinary case, not a corner one — "0.00" and a repeated
        # country name are paragraphs too.
        context = final & original
        rest = live - context
        kept = sum(((final - original) & rest).values())
        reverted = sum(((original - final) & rest).values())
        authored = sum((live - final - original).values())
    # The apparatus, which no other layer of this verdict can see: a
    # link or a bookmark is invisible to the text comparison above, and
    # a pass that adds 116 of them reports as "no visible change" —
    # which is true, and is the whole reason the round left no trace.
    was, now = _links(base), _links(work)
    was_bm, now_bm = _bookmarks(base), _bookmarks(work)
    return Verdict(
        changed=len(report["text"]),
        added=structure.get("INSERT", 0),
        removed=structure.get("DELETE", 0),
        proposed=proposed, kept=kept, reverted=reverted, authored=authored,
        links=(sum((now - was).values()), sum((was - now).values())),
        bookmarks=(len(now_bm - was_bm), len(was_bm - now_bm)),
        batch=batch)


#: The log's batch table, as every paper's `log.md` spells it.
_BATCH_HEADING = "## Batches"
_ROW_RE = re.compile(r"^\s*\|")


def log_batch(paper: Paper, result: Verdict, note: str = "") -> str | None:
    """Append one row to `log.md`'s batch table; return it, or None.

    None when the paper's log has no table to append to — a log this
    tool did not scaffold is the author's document, and guessing where a
    row belongs in it is how a record gets mangled. The caller says so
    rather than this writing a table nobody asked for.

    The row lands after the LAST row of the table and not at the end of
    the file: three of the nine papers carry prose after their batch
    table, and an appended line would have been read as part of it.
    """
    log = paper.config.parent / "log.md"
    if not log.is_file():
        return None
    lines = log.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip() == _BATCH_HEADING), None)
    if start is None:
        return None
    rows = [i for i in range(start, len(lines)) if _ROW_RE.match(lines[i])]
    if not rows:
        return None
    header = [c.strip() for c in lines[rows[0]].strip().strip("|").split("|")]
    if len(header) != 5:
        return None                     # not the table this row is shaped for
    # contiguous from the header: a second table further down the file
    # is not this one
    last = rows[0]
    for i in rows[1:]:
        if i != last + 1:
            break
        last = i
    row = (f"| {_today()} | {note or (result.batch.stem if result.batch else '—')} "
           f"| {result.summary()} | — | {result.outcome} → truth |\n")
    lines.insert(last + 1, row)
    log.write_text("".join(lines), encoding="utf-8")
    return row


def baseline(paper: Paper, *, force: bool = False,
             accept_loss: tuple[str, ...] = (),
             repair_math: bool = False, note: str = "",
             log: bool = True) -> Path:
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

    And it refuses while the hand-back has LOST something — a link, a
    note, a bookmark, a comment (:func:`losses`). This is the step that
    makes such a loss permanent: `prev.docx` is what the compare chain
    measures against afterwards, so a link Word ate on the way in
    becomes a link that was never there. `accept_loss` names the ones
    that are deliberate, by anchor, note text or ``kind:what`` key —
    including the case that made the check hard to write, a loss that is
    a REPAIR (LI7's link whose label had bled across a whole sentence).
    Naming something that is NOT lost is itself refused: a stale
    exemption is a switched-off gate that reads as a switched-on one.

    `force` does not override this either. The unacknowledged loss is
    exactly the case `force` would be reached for by reflex, and the
    acknowledgement costs one anchor.

    `repair_math` is the one loss this tool may put back itself, and
    the reason it may is that it is not an author's decision: Word
    downgrades an equation's U+2212 on accept-and-save, `build` already
    restores the same glyph on the redline it produces, and doing it
    here is that repair on the other side of the hand-back. It rewrites
    `working.docx` — every run whose text the baseline spells with the
    glyph put back — and the gates above run against the repair, so
    anything it could NOT reach still refuses.

    It also RECORDS the round, in `log.md`'s batch table, unless
    `log=False`. That is not bookkeeping for its own sake: this is the
    moment the evidence stops existing. After adjudication the
    manuscript reads 0 pending whether every revision was accepted,
    every one rejected or half of each, and the next line of this
    function replaces the only other copy of what it grew out of. The
    verdict was reconstructible until now and unrecorded — `log.md`'s
    outcome column was filled in by hand, when it was filled in at all.
    `note` names the batch in that row; without one it takes the
    proposal's filename.

    They run against it IN MEMORY, and the write waits for all of them.
    Writing first meant that `--repair-math` on a manuscript with a
    revision still pending, or with a loss nobody had acknowledged,
    refused — correctly — having ALREADY changed the author's live
    file, and with no backup of it: the one command in this package that
    both edits `working.docx` and then declines to say so. It is backed
    up before the write now, as `build --force` and `refstyle --fix` do.
    """
    if package.is_locked(paper.working):
        raise DocumentLocked(
            f"{paper.working.name} is open in Word. Close it first — a "
            f"baseline copied mid-save is a zip nothing can reject "
            f"against.")
    repaired: dict[str, bytes] | None = None
    if paper.prev.exists():
        work, base = (package.read_parts(paper.working),
                      package.read_parts(paper.prev))
        if repair_math and restore_math_glyphs(work, base):
            repaired = work        # written below, once every gate has passed
        gone = losses(work, base)
        if stale := _unmet(accept_loss, gone):
            raise HandbackLoss(
                f"--accept-loss named {', '.join(stale)}, which "
                f"{paper.working.name} has NOT lost. A declared loss that "
                f"did not happen is an exemption with nothing under it, "
                f"and it would pass the next real one through in silence.")
        unacknowledged = [loss for loss in gone
                          if not any(_names(token, loss)
                                     for token in accept_loss)]
        if unacknowledged:
            # Print the token that WORKS, not a description of it. The
            # first version printed a 70-character truncation and the
            # hatch then rejected the words it had just shown.
            listed = "\n  - ".join(
                f"{loss}\n      --accept-loss {loss.key[:60]!r}"
                for loss in unacknowledged)
            raise HandbackLoss(
                f"{paper.working.name} lost {len(unacknowledged)} thing(s) "
                f"since {paper.prev.name}, and baselining makes that "
                f"permanent — the compare chain measures against prev.docx, "
                f"so a link Word ate becomes a link that was never there:"
                f"\n  - {listed}\n"
                f"Word does this silently when it collapses a paragraph to "
                f"make an edit. Put them back, or name the deliberate ones "
                f"with the flag shown above (a prefix is enough).")
    current = state(paper.working)
    if not current.is_truth and not force:
        where = ", ".join(f"{n} in {p.split('/')[-1]}"
                          for p, n in current.by_part.items())
        raise BaselinePending(
            f"{paper.working.name} is a proposal, not the truth: "
            f"{current.pending} revision(s) pending ({where}). The "
            f"author accepts or rejects them; this tool never does.")
    if repaired is not None:
        # `state` above read the file on disk, which is the unrepaired
        # one — and reads the same either way: restoring a glyph rewrites
        # run TEXT and touches no `w:ins` or `w:del`, so it cannot move
        # the count this gate is about.
        package.backup(paper.working, tag="pre_math_repair")
        package.write_docx(paper.working, repaired)
    # BEFORE the copy: the whole computation is against the truth the
    # batch was built on, and the next line overwrites it.
    recorded = verdict(paper) if log else None
    paper.build_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paper.working, paper.prev)
    if recorded is not None:
        log_batch(paper, recorded, note)
    return paper.prev


# ----------------------------------------------------------------- init

_LOG_TEMPLATE = """# {name} — revision log

`{paper_file}` is the manuscript. It is the **only** file to open and
edit. It is in one of exactly two states, and the state is readable
from the file:

| revisions | state | who acts |
|-----------|-------|----------|
| 0 | **truth** — this is the paper | agent may start a batch |
| >0 | **proposal** — a batch awaiting a verdict | author accepts/rejects |

    docxkit revision status   # 0 settled · 1 pending · 4 stale baseline

Exit 4 means the two counts agree and the CONTENT does not: `prev.docx`
is no longer what `{paper_file}` grew out of (an accept in Word leaves
nothing pending on either side). Ingest, then baseline.

## Rules

1. **One file.** `{paper_file}` never changes name. Round names live in
   git tags and in `export/` copies, never in the live filename.
2. **Ingest before anything.** Every task begins with
   `docxkit revision ingest`; it is read-only and never writes to
   `{paper_file}`.
3. **Resolve before extend.** No new batch while revisions are pending.
4. **Forward-only.** A script in `scripts/applied/` is spent — a record
   of what was done, not a way to redo it. Recovery from a bad batch is
   reject-all, never a rebuild from an older generation.
5. **Close Word before a handback.**
6. **Text-only -> Compare; math -> hand-authored.**

## Layout

    {paper_path}{pad}THE paper — your file, your name, edited in place
    revision/log.md           this file
    revision/paper.toml       per-project configuration (says where the paper is)
    revision/scripts/         live tools and the paper's own gates
    revision/scripts/applied/ spent batch migrations — records only
    revision/notes/           response notes, drafts, QA records
    revision/build/           prev.docx (= last accepted truth) + scratch

`revision/` is MACHINERY. The manuscript is not in it and does not need
to be: `paper.toml` declares where it is, and every command reads that
one line.

## Batches

| date | batch | changes | gates | outcome |
|------|-------|---------|-------|---------|
| {date} | *(protocol migration — no manuscript change)* | — | {paper_file} unchanged `{digest}` | truth |
"""

_TOML_TEMPLATE = """# Unified revision protocol — per-project configuration.
# One of these per paper; the protocol itself is shared (docxkit.revision).

[paper]
name     = "{name}"
language = "{language}"
# THE paper: the author's own file, under the author's own name, edited
# in place. This line is the ONLY place that says where it is — every
# command reads it, so renaming or moving the manuscript is a one-line
# change here and nothing else.
working  = {working}
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
# The paper's OWN gates. Not part of the shared ladder — what this
# paper checks is this paper's business — but `docxkit revision
# validate --run-gates` runs them, exactly as spelled here, from the
# project root.
commands = [{gates}]

[attic]
path = '{attic}'
"""


def _toml_str(value: str) -> str:
    """`value` as a TOML basic string, quotes and backslashes escaped.

    A path reaches the config through here rather than through an
    f-string: on Windows the natural spelling of an absolute one is full
    of backslashes, and `"C:\\Users\\..."` is not the string it looks
    like — TOML reads `\\U` as a unicode escape and refuses the file.
    Every path this writes is normalised to forward slashes first, so
    the escaping matters only for the rare name carrying a quote.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


#: A `[section]` header on a line of its own, which is how every config
#: this package writes spells one. A key written in dotted form
#: (`paper.working = …`) or an inline table would not be seen — and is
#: not silently ignored either: :func:`_set_key` inserts the key it was
#: asked for, and `load_paper` then reads the LAST definition, so the
#: intended value wins rather than a duplicate being written into a file
#: that already said something else.
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _set_key(text: str, section: str, key: str, value: str) -> str:
    """`key = value` inside `[section]`, and NOTHING else touched.

    A line editor rather than a TOML round-trip, and deliberately:
    `tomllib` reads and does not write, and re-emitting a parsed
    document would drop every comment in the file. Half the value of
    these configs is in the comments — LI7's `[git] repo = ""` carries
    the sentence saying the project root is not under version control
    and the attic is the paper's only history, and `[deliverable]`
    records that its redline is cumulative rather than per-batch. A
    writer that loses those is not a writer worth having.

    Missing key: inserted under the section header. Missing section:
    appended. A key whose value opens a bracket is REFUSED rather than
    mangled — this edits scalars, and the one array in the template
    (`[verify] commands`) belongs to the paper, not to `init`.
    """
    lines = text.splitlines(keepends=True)
    key_re = re.compile(rf"^(\s*){re.escape(key)}(\s*)=(.*)$", re.DOTALL)
    current: str | None = None
    section_at: int | None = None       # the header line of our section
    for i, line in enumerate(lines):
        header = _SECTION_RE.match(line)
        if header:
            current = header.group(1).strip()
            if current == section:
                section_at = i
            continue
        if current != section:
            continue
        m = key_re.match(line)
        if not m:
            continue
        indent, pad, rest = m.groups()
        if rest.count("[") > rest.count("]"):
            raise ProtocolError(
                f"[{section}] {key} spans several lines; this writer "
                f"edits single-value keys only. Change it by hand.")
        # Keep a trailing comment: these lines explain themselves, and
        # the explanation is as much the file's content as the value.
        tail = rest.rstrip("\r\n")
        cut = tail.find("#", _value_end(tail))
        comment = f"  {tail[cut:].strip()}" if cut != -1 else ""
        lines[i] = f"{indent}{key}{pad}= {value}{comment}\n"
        return "".join(lines)

    entry = f"{key} = {value}\n"
    if section_at is not None:
        lines.insert(section_at + 1, entry)
        return "".join(lines)
    body = "".join(lines)
    join = "" if body.endswith("\n\n") else "\n" if body.endswith("\n") else "\n\n"
    return f"{body}{join}[{section}]\n{entry}"


def _value_end(tail: str) -> int:
    """Where a key's VALUE stops, so a `#` after it is a comment.

    A quoted value can hold a `#` — a Windows path cannot, but a paper's
    name can — and cutting at the first one would eat half the value and
    call the rest a comment.
    """
    quote = ""
    for i, ch in enumerate(tail):
        if quote:
            if ch == quote:
                return i + 1
        elif ch in "\"'":
            quote = ch
    return 0


def _declare(path: Path, root: Path) -> str:
    """How `path` is written in ``paper.toml`` — relative to `root` when
    it is under it, absolute when it is not, forward slashes either way.

    A relative declaration is what makes a project movable: the whole
    folder can be copied to another machine, or out of OneDrive onto a
    local clone, and the config still resolves. An absolute one is
    honest about a manuscript that genuinely lives elsewhere rather than
    inventing a `../../..` chain nobody can read.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def init(root: str | Path, source: str | Path, *,
         working: str | Path = "", name: str = "",
         author: str = "", language: str = "",
         attic: str | Path | None = None,
         force: bool = False) -> Paper:
    """Scaffold the protocol layout around an existing manuscript.

    `source` is the paper as it stands today. **By default it is adopted
    IN PLACE**: no copy of it is made, its name and location do not
    change, and ``paper.toml`` simply records where it is. The only file
    written beside it is ``revision/build/prev.docx``, the baseline, and
    the ``revision/`` machinery around it — so a migration is still
    abandonable by deleting one folder, and now without leaving a second
    copy of the manuscript behind at all.

    That default is a correction. The first shape of this protocol
    copied every paper to ``revision/working.docx``, which made "which
    file do I open" unanswerable in the other direction: nine papers,
    nine identical filenames, and nothing in Explorer or the Word title
    bar saying which project is on screen. It also left the author's
    original sitting in the project unread forever — the protocol called
    retiring it "a separate, deliberate step" and nothing ever performed
    that step, so `doctor` exists largely to find scripts still pointing
    at the abandoned twin.

    Pass `working` to put the manuscript somewhere else — a path,
    relative to `root` unless absolute. The source is then COPIED there
    and left where it was, which is the old migration shape and now has
    to be asked for. Ask the author for that name rather than choosing
    one: the filename is what they read in Explorer, and it is theirs.

    The baseline is seeded from the manuscript's own bytes on purpose:
    at migration time the paper IS the last accepted truth, whatever
    revisions it happens to carry.

    **`force` rewrites the CONFIG KEYS this function is given, and
    nothing else.** It used to rewrite the whole project: `paper.toml`
    from the template, `log.md` from the template, and `prev.docx` from
    the live file. Measured on a scratch paper carrying two rounds of
    history (2026-08-23): the batch table went from 3 rows to 1, the
    baseline was re-seeded to the CURRENT manuscript — so every later
    reject-all would have measured against the wrong generation — and
    the config came back with `commands = []` and no `[doctor]` section
    at all. Exit 0, no warning, no backup.

    Every live paper carried something the template cannot express:
    eight had gate lists, three had whole sections belonging to their
    own tooling, and Aging_Well had ``[batch] carry =
    ["word/footer3.xml"]``, which is the fix for a promote that once
    shipped a World Bank manuscript without its sensitivity label. So a
    forced re-init now MERGES: the keys it was given are rewritten in
    place by :func:`_set_key`, the rest of the file — other keys, other
    sections, every comment — is left byte-identical, and the config is
    backed up first. An existing `log.md` and an existing `prev.docx`
    are never touched: one is the paper's history and the other is its
    baseline, and neither is this function's to reset.

    A value not passed is not changed. That is why `author` and
    `language` default to empty rather than to "Revision" and "en": on a
    rewrite there is no way to tell a caller who means "en" from a
    caller who said nothing, and the paper that spells its author
    "Revision Agent" would lose it to a default nobody typed. The
    defaults apply when the config is being CREATED.
    """
    root, source = Path(root).resolve(), Path(source).resolve()
    if not source.is_file():
        raise ProtocolError(f"no manuscript at {source}")
    # Adopting in place means the paper lives in the project. Every
    # command finds its config by walking UP from wherever it is
    # started — including from the manuscript itself — so a paper
    # outside the root would be a declaration nothing could resolve
    # from the file the author actually has open.
    if not working and not source.is_relative_to(root):
        raise ProtocolError(
            f"{source} is not inside {root}. The protocol adopts the "
            f"manuscript where it is, so it has to be in the project: "
            f"give --root the folder that contains the paper, or "
            f"--working PATH to put a copy inside the project instead.")
    folder = root / _DIR
    config = folder / _CONFIG
    if config.exists() and not force:
        raise ProtocolError(
            f"{config} already exists — this paper is already on the "
            f"protocol. Pass force=True only to rewrite its config.")

    for sub in ("build", "notes", "scripts/applied"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    # No `working=`: the paper is where it already is. Naming one copies
    # the source there — and copying a file onto itself raises rather
    # than being a no-op, which is the case where the author names the
    # path the manuscript already occupies.
    live = source if not working else (root / working).resolve()
    if live != source and (not live.exists() or force):
        live.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, live)
    # NOT `or force`: a baseline that exists is the last accepted truth,
    # and re-seeding it from the live file is how every later reject-all
    # comes to measure against the wrong generation.
    prev = folder / "build" / "prev.docx"
    if not prev.exists():
        shutil.copyfile(live, prev)

    declared = _declare(live, root)
    if config.exists():
        package.backup(config, tag="pre_init")
        text = config.read_text(encoding="utf-8")
        given = [("paper", "working", _toml_str(declared))]
        if name:
            given.append(("paper", "name", _toml_str(name)))
        if language:
            given.append(("paper", "language", _toml_str(language)))
        if author:
            given.append(("batch", "author", _toml_str(author)))
        if attic:
            given.append(("attic", "path", _toml_str(str(attic))))
        for section, key, value in given:
            text = _set_key(text, section, key, value)
        config.write_text(text, encoding="utf-8")
    else:
        config.write_text(_TOML_TEMPLATE.format(
            name=(name or root.name).replace('"', "'"),
            language=language or "en", author=author or "Revision",
            gates="", working=_toml_str(declared),
            rescue_keep=RESCUE_KEEP,
            attic=str(attic) if attic else f"D:\\PaperAttic\\{root.name}",
        ), encoding="utf-8")

    # A paper the protocol scaffolded is a paper `status --all` should
    # know about. Registered HERE and in no read-only command: a survey
    # is worth having only if the list fills itself, and a `status` that
    # wrote to a machine-wide file would be a read command with a side
    # effect — including inside anyone's test suite.
    register(config)

    # Likewise never rewritten: `log.md` holds the batch history, and the
    # template would replace it with a single migration row.
    log = folder / "log.md"
    if not log.exists():
        log.write_text(_LOG_TEMPLATE.format(
            name=name or root.name,
            paper_file=live.name,
            paper_path=declared,
            pad=" " * max(1, 26 - len(declared)),
            date=_today(),
            digest=_guard.sha256(live)[:8].upper(),
        ), encoding="utf-8")
    return load_paper(root)


def _today() -> str:
    return date.today().isoformat()


# ------------------------------------------------ who else knows the paper --

#: Where a project keeps code, and what a survey should not read. `build`
#: holds this protocol's own artefacts and `attic` holds retired ones —
#: both legitimately name old manuscripts.
_DOCTOR_SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules",
                ".mypy_cache", ".pytest_cache", ".ruff_cache"}
#: Source that can SELECT a manuscript. Notebooks are read as text: a
#: glob in a cell selects a paper exactly as one in a module does.
_DOCTOR_SUFFIXES = {".py", ".ipynb", ".toml", ".cfg", ".ini", ".do",
                    ".sh", ".ps1", ".bat", ".R", ".r"}
_DOCX_LITERAL_RE = re.compile(r"""['"]([^'"\n]*?\.docx)['"]""")
#: A glob or regex that SELECTS by shape rather than by name — the case
#: no grep for the filename can find.
_DOCX_PATTERN_RE = re.compile(
    r"""['"]([^'"\n]*?\*[^'"\n]*?\.docx|[^'"\n]*?\.docx[^'"\n]*?\*)['"]""")


@dataclass
class Doubt:
    """One place that thinks it knows where the manuscript is."""

    path: Path
    """The file that selects it, relative to the project root."""
    line: int
    text: str
    """The literal or pattern as written."""
    kind: str
    """``"literal"`` or ``"pattern"``."""

    def __str__(self) -> str:
        # forward slashes whatever the platform, like every other path
        # this package prints — a report copied into an issue should
        # read the same on the machine that reads it
        return (f"{self.path.as_posix()}:{self.line}  {self.kind}  "
                f"{self.text!r}")


def _selects_declared(text: str, paper: Paper) -> bool:
    """Does this literal or glob select a manuscript the protocol owns?

    Both ends of the pair count. `prev.docx` is the baseline every
    reject-all check reads, so a script naming it is doing the right
    thing, and reporting it would train the reader to skim this.
    """
    candidate = Path(text)
    globbed = "*" in text or "?" in text
    for target in (paper.working.resolve(), paper.prev.resolve()):
        if globbed:
            if target.match(text) or target.match(f"**/{text.lstrip('/')}"):
                return True
            continue
        if candidate.name != target.name:
            continue
        # a bare name, or a path whose tail matches the declared one
        if len(candidate.parts) == 1 or target.match(
                str(Path(*candidate.parts[-2:]))):
            return True
    return False


def doctor(paper: Paper | None = None, *,
           start: str | Path | None = None) -> list[Doubt]:
    """Every place in the project that selects a manuscript OTHER than
    the declared one.

    The survey a migration needs and a grep cannot do. Retiring the old
    filename is left to the migrator, who searches for it — and the
    references that matter are the ones that never spell it: they pick
    the paper by PATTERN, and a pattern that stops matching falls back
    to whatever else is on disk, which is an older generation of the
    same paper sitting right there.

    Observed three times before this existed. `Parental_style` had 20
    scripts hard-coded to `ps5_r1.docx` with `ps5_r2.docx` live;
    API/HPPA defaulted every script to API10 with API11 live; and AFI's
    own pytest suite globbed the highest `afi_vN.docx`, so the rename to
    `working.docx` sent it to `Report/afi_v11.docx`, three generations
    stale. Eleven tests failed with messages about caption counts and
    table cells, and not one of them named the rename. Red was luck:
    had the two generations agreed on those counts, the suite would
    have stayed green while gating a manuscript untouched for a month.

    Reports rather than refuses, and reads only text — it opens no
    document and changes nothing. `build/` and the attic are skipped:
    both legitimately hold older manuscripts.
    """
    paper = paper or load_paper(start)
    # the config DECLARES the pair; it does not select one
    skip_files = {paper.config.resolve()}
    skip = {paper.build_dir.resolve()}
    if paper.attic is not None:
        skip.add(paper.attic.resolve())
    for spent in paper.doctor_skip:
        skip.add((paper.root / spent).resolve())

    out: list[Doubt] = []
    for path in sorted(paper.root.rglob("*")):
        if path.suffix not in _DOCTOR_SUFFIXES or not path.is_file():
            continue
        if any(part in _DOCTOR_SKIP for part in path.parts):
            continue
        if path.resolve() in skip_files:
            continue
        if any(parent in skip for parent in path.resolve().parents):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):        # pragma: no cover
            continue
        for n, line in enumerate(lines, 1):
            seen: set[str] = set()
            for rx, kind in ((_DOCX_PATTERN_RE, "pattern"),
                             (_DOCX_LITERAL_RE, "literal")):
                for m in rx.finditer(line):
                    text = m.group(1)
                    if text in seen or _selects_declared(text, paper):
                        continue
                    seen.add(text)
                    out.append(Doubt(path.relative_to(paper.root), n,
                                     text, kind))
    # PATTERNS first. The docstring argues a pattern is the dangerous
    # kind and the first report buried three of them among 131 literals
    # on AFI — an unreadable gate is one people stop running, which is
    # the failure this whole file reserves an S3 for.
    return sorted(out, key=lambda d: (d.kind != "pattern", d.path, d.line))
