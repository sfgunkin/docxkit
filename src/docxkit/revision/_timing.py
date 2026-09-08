r"""How long each protocol step took, recorded where the paper lives.

    @timed("build")
    def build(paper, ...):
        ...
        mark("preflight")
        report = tracked.build(...)
        mark("compare")

The decorator opens a session for the whole call; `mark` closes the
segment since the previous mark. A verb therefore describes its own
phases in the order they run, in one line each, with **no reindenting of
the body** — which matters here, because these functions are 200-line
files whose comments carry most of the protocol's reasoning, and a diff
that moves every line of one hides whatever else it changed.

`mark` reaches the open session through a :class:`~contextvars.ContextVar`
rather than a passed-in object, so it is a no-op when nothing is being
timed. Tests and direct library callers therefore need no special case,
and a nested call cannot record into its parent's session.

**Why this lives in the protocol and not in each paper.** The per-paper
alternative was measured on Aging_Well on 2026-09-07 by watching the
file system from outside: two rounds, and the result was ±20s per step,
could not tell a rewrite from a touch, and could not name the command
that caused either. It cost an afternoon and produced one defensible
number — a Word Compare at 141s cold against 40s warm. The same
measurement from inside is exact, names the step, and costs a
`perf_counter` call.

**Nothing here gates, and nothing raises.** A slow step is a fact about
the machine's afternoon — Word starting cold, OneDrive syncing, a sweep
in the next window — and a protocol that failed on a threshold over
that would be failing for the weather. Every error in this module is
swallowed deliberately: a round that fell over because it could not
write a performance note would be the tail wagging the dog.

**A paper turns it off** with ``[paper] timings = false``, or a machine
with ``DOCXKIT_TIMINGS=0``. Not a courtesy: `repkit` ships a replication
package out of a paper tree, and a folder of JSON nobody declared is
exactly what rides along into one.
"""
from __future__ import annotations

import contextlib
import functools
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, TypeVar

from .. import timings
from ._config import Paper

__all__ = ["mark", "session", "timed"]

#: Set `DOCXKIT_TIMINGS=0` for a machine or a CI run that should leave
#: no trace in the tree.
ENV = "DOCXKIT_TIMINGS"

F = TypeVar("F", bound=Callable[..., Any])


class Session:
    """The marks of one protocol command, in the order they happened."""

    def __init__(self) -> None:
        self.steps: list[tuple[str, float]] = []
        self.began = time.perf_counter()
        self._last = self.began

    def mark(self, name: str) -> float:
        now = time.perf_counter()
        span = round(now - self._last, 2)
        self._last = now
        self.steps.append((name, span))
        return span

    def finish(self) -> list[tuple[str, float]]:
        """The marks, with the command's whole wall clock last.

        `total` is measured from the start rather than summed from the
        marks: a verb need not mark everything, and the gap between what
        it did mark is real time somebody may want to go looking for.
        """
        return [*self.steps,
                ("total", round(time.perf_counter() - self.began, 2))]


_CURRENT: ContextVar[Session | None] = ContextVar("docxkit_timing",
                                                  default=None)


def mark(name: str) -> None:
    """Close the segment since the previous mark, if anything is timing."""
    if (live := _CURRENT.get()) is not None:
        live.mark(name)


def _wanted(paper: Paper | None) -> bool:
    if os.environ.get(ENV, "").strip().lower() in {"0", "false", "no"}:
        return False
    return paper is None or paper.timings


@contextmanager
def session(kind: str, paper: Paper | None,
            root: Path | str | None = None,
            name: str = "") -> Iterator[Session]:
    """Time a protocol command and record it beside the paper.

    `paper` is the usual source of both the root and the opt-out;
    `root` covers the two verbs that never see one — `validate` and
    `ingest` take paths, so their caller supplies the root it resolved.

    The command's own outcome is not this module's business: a `build`
    that refused still took time, and the refusal is the interesting
    row. The record is written whether the body raised or returned, with
    the exception's name as the outcome.
    """
    live = Session()
    where = root if root is not None else (paper.root if paper else None)
    token = _CURRENT.set(live if where is not None and _wanted(paper)
                         else None)
    outcome = "ok"
    try:
        yield live
    except BaseException as exc:
        outcome = type(exc).__name__
        raise
    finally:
        _CURRENT.reset(token)
        if where is not None and _wanted(paper):
            # Suppressed on purpose: a round that fell over because it
            # could not write a performance note would be the tail
            # wagging the dog. `timings.record` already swallows the
            # ordinary I/O failures; this is the belt to that braces.
            with contextlib.suppress(Exception):
                timings.record(
                    kind, name or (paper.name if paper else kind),
                    live.finish(), Path(where) / timings.FOLDER,
                    outcome=outcome)


def timed(kind: str) -> Callable[[F], F]:
    """Time a verb whose FIRST argument is the `Paper`.

    Only that shape, and deliberately: guessing which argument is the
    paper is how a decorator starts silently recording nothing. The two
    verbs that take paths instead — `validate` and `ingest` — use
    :func:`session` at the call site, where a root has been resolved.
    """
    def decorate(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kw: Any) -> Any:
            paper = args[0] if args and isinstance(args[0], Paper) else None
            with session(kind, paper):
                return fn(*args, **kw)
        return wrapper                                    # type: ignore[return-value]
    return decorate
