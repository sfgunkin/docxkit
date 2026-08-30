"""What the author changed while I was away.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import package
from ._common import SAVE_NOISE
from ._losses import Loss, Relabelled, losses, relabelled_links
from ._state import State, _state, state

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
    from .. import compare as _compare  # deferred: heavy import chain

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
