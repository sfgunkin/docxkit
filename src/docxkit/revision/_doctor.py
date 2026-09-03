"""Who else on this machine thinks they know this paper.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from ._common import _SECTION_RE
from ._config import KNOWN, Paper, load_paper

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
    """``"literal"``, ``"pattern"``, or ``"key"`` — a config key within
    a typo of one docxkit reads, which took its default in silence."""

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


#: A bare `key =` at the start of a line. Quoted and dotted keys are not
#: matched and not reported: docxkit never writes either.
_KEY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


def _key_doubts(paper: Paper) -> list[Doubt]:
    """Keys in the sections docxkit reads that are within a typo of a
    key it reads — and NOT every key it does not read.

    `load_paper` takes every key through `.get` with a default, so
    `rescue_kep = 3` is a rescue ladder five deep that nobody set, and
    nothing says so. The broad rule — report any key not in
    :data:`KNOWN` — was measured before it was written, against the nine
    registered papers (2026-09-03): 29 distinct keys, 10 of them
    docxkit's. `[deliverable]`, `[git]`, `[analysis]`, `[verify] audits`,
    `[batch] text_only` are the papers' own, kept beside the protocol's
    on purpose, and a report that named them all would be AFI's 134
    lines again. A near-miss is a typo; a stranger is a neighbour.
    """
    out: list[Doubt] = []
    section: str | None = None
    for n, line in enumerate(
            paper.config.read_text(encoding="utf-8").splitlines(), 1):
        if header := _SECTION_RE.match(line):
            section = header.group(1).strip()
            continue
        known = KNOWN.get(section or "")
        if not known or not (m := _KEY_RE.match(line)):
            continue
        key = m.group(1)
        if key in known:
            continue
        close = difflib.get_close_matches(key, sorted(known), n=1,
                                          cutoff=0.8)
        if close:
            out.append(Doubt(paper.config.relative_to(paper.root), n,
                             f"[{section}] {key} — {close[0]}?", "key"))
    return out


def doctor(paper: Paper | None = None, *,
           start: str | Path | None = None) -> list[Doubt]:
    """Every place in the project that selects a manuscript OTHER than
    the declared one — and, first, every key in ``paper.toml`` that is
    a typo of one the protocol reads (see :func:`_key_doubts`).

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

    out = _key_doubts(paper)
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
    # KEYS first, then PATTERNS. A typo'd key changes what the protocol
    # DOES; a pattern is the dangerous kind of selection, and the first
    # report buried three of them among 131 literals on AFI — an
    # unreadable gate is one people stop running, which is the failure
    # this whole file reserves an S3 for.
    return sorted(out, key=lambda d: (d.kind != "key", d.kind != "pattern",
                                      d.path, d.line))
