"""``revision/paper.toml`` — which file IS the paper.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ProtocolError
from ._common import _CONFIG, _DIR, _DOCTOR_SPENT, RESCUE_KEEP, WORD_DEADLINE

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
    word_deadline: float = WORD_DEADLINE
    """Seconds a Word session may take in `build` or `validate` before
    it is killed and the step fails; ``0`` is no ceiling. See
    :data:`docxkit.revision._common.WORD_DEADLINE`."""
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
    render_math: bool = True
    """Render the pages of the equations a batch adds or changes, on
    every `validate`, from ``[verify] render_math``.

    On by default, because the opt-in render stayed unused while four
    defects only a page can show went through a green ladder (see
    :func:`docxkit.revision.math_anchors`). Off is for a paper whose
    batches rewrite whole equation sets every round and whose author
    reads the PDF anyway; `--render ANCHOR` still works with it off.
    """
    timings: bool = True
    """Record how long each protocol step took, in ``<root>/.timings/``.

    On by default, from ``[paper] timings``. The measurement is worth
    having by default because the alternative is what happened on
    Aging_Well on 2026-09-07: an afternoon spent inferring step
    durations from file mtimes at ±20s, unable to tell a rewrite from a
    touch or name the command that caused either.

    Off is a real need rather than a courtesy. `repkit` ships a
    replication package out of a paper tree, and a folder of JSON
    nobody declared is exactly what rides along into one; a paper whose
    tree must stay exactly as declared turns this off and loses nothing
    but the history.
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

    def redlines(self) -> list[Path]:
        """Every redline `promote` kept, oldest first.

        The listing lives on `Paper` rather than beside `promote`
        because it is not only promote's question. `verdict` asks it to
        find out whether a staged batch ever REACHED the manuscript —
        it sits below `_promote` in the subpackage order and cannot
        import it, and a second glob written there would be a second
        answer to where the redlines are. :func:`docxkit.revision.
        redlines` is this, under the name callers already use.

        Stamped rather than numbered, so sorting the names as strings
        sorts them chronologically. See :data:`_RESCUE_STAMP`.
        """
        if not self.redline_dir.is_dir():
            return []
        return sorted(self.redline_dir.glob(
            f"{self.working.stem}_redline_*{self.working.suffix}"))

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


#: Every key `load_paper` reads, by section — the protocol's end of the
#: file. The rest of ``paper.toml`` is the paper's: measured over the
#: nine registered papers on 2026-09-03, their configs carry 29 distinct
#: keys and these are the 10 docxkit reads; `[deliverable]`, `[git]`,
#: `[analysis]`, `[verify] audits`, `[batch] text_only` are all real and
#: all theirs, kept beside the protocol's on purpose (see `_set_key`).
#: So this is not a schema to refuse on. It is what `doctor` measures a
#: key AGAINST: one within a typo of a name here is a typo, and a typo
#: takes its default in silence — `rescue_kep = 3` is a rescue ladder
#: five deep that nobody set. `_read` holds the table to the code: a
#: key read here and not listed raises, so the list cannot fall behind.
KNOWN: dict[str, frozenset[str]] = {
    "paper": frozenset({"name", "language", "working", "prev", "timings"}),
    "batch": frozenset({"author", "rescue_keep", "carry", "word_deadline"}),
    "verify": frozenset({"commands", "render_math"}),
    "attic": frozenset({"path"}),
    "doctor": frozenset({"skip"}),
}


def _read(data: dict[str, Any], section: str, key: str,
          default: Any) -> Any:
    """``[section] key``, or `default` — through :data:`KNOWN`, always."""
    if key not in KNOWN.get(section, frozenset()):
        raise KeyError(f"[{section}] {key} is read but not declared in "
                       f"KNOWN — add it there, so `doctor` can see a typo "
                       f"of it")
    return data.get(section, {}).get(key, default)


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

    def _abs(value: str, fallback: str) -> Path:
        return (root / (value or fallback)).resolve()

    # The fallback is the shape every paper scaffolded before 2026-08-23
    # was given, and it stays a fallback rather than a default anyone
    # should rely on: `init` now adopts the author's file where it is,
    # and writes the path it adopted. A config that says nothing is an
    # old config, and it still resolves.
    working = _abs(_read(data, "paper", "working", ""),
                   f"{_DIR}/working.docx")
    prev = _abs(_read(data, "paper", "prev", ""), f"{_DIR}/build/prev.docx")
    attic = _read(data, "attic", "path", None)
    return Paper(
        root=root,
        config=config,
        working=working,
        prev=prev,
        build_dir=prev.parent,
        name=_read(data, "paper", "name", root.name),
        author=_read(data, "batch", "author", "Revision"),
        language=_read(data, "paper", "language", "en"),
        gates=tuple(_read(data, "verify", "commands", ())),
        attic=Path(attic) if attic else None,
        rescue_keep=int(_read(data, "batch", "rescue_keep", RESCUE_KEEP)),
        word_deadline=float(_read(data, "batch", "word_deadline",
                                  WORD_DEADLINE)),
        doctor_skip=tuple(_read(data, "doctor", "skip", _DOCTOR_SPENT)),
        carry=tuple(_read(data, "batch", "carry", ())),
        render_math=bool(_read(data, "verify", "render_math", True)),
        timings=bool(_read(data, "paper", "timings", True)),
    )
