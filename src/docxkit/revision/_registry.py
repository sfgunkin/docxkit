"""Which papers on this machine are on the protocol.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import package
from ._common import _CONFIG, _DIR
from ._config import Paper, load_paper
from ._state import State, drift, state

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
