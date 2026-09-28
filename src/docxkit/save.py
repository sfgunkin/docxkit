"""THE save: protect edge spaces, lint, back up, write — for any caller.

It lived in ``cli._save`` alone until 2026-09-29. Every CLI command that
writes came through it, and the library's own entry point for a paper
script, :func:`edit_in_place`, did none of it: no ``preserve_space``, no
lint, no backup. A script could write spliced markup Word will not open,
offline and in silence, through the function the README tells papers to
use (REVIEW_2026-09-28 §3). The policy is here now and both call it; the
CLI prints the :class:`SaveReport` it gets back.

Where a backup lands is the CALLER's to say: the CLI resolves a paper's
rescue folder from ``paper.toml``, which this layer does not read.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import lint as _lint
from . import package as _package
from ._report import Finding, Severity, blocking_of
from ._xml import DOCUMENT, Parts
from .edit import preserve_space
from .errors import PackageError
from .package import assert_unlocked, backup, write_docx

__all__ = ["PackageError", "SaveReport", "edit_in_place", "save"]


@dataclass(frozen=True)
class SaveReport:
    """What :func:`save` did — or why it wrote nothing."""

    path: Path
    #: Edge-whitespace runs `preserve_space` protected before the lint.
    protected: int = 0
    #: Lint findings this edit INTRODUCED. Any one refuses the write,
    #: whatever `allow_existing_lint` says.
    fresh: tuple[str, ...] = ()
    #: Lint findings the file on disk already carried.
    existing: tuple[str, ...] = ()
    allowed_existing: bool = False
    written: bool = False
    #: Where the previous version went; None when no backup was asked for
    #: or nothing was written.
    backup: Path | None = None

    def findings(self) -> list[Finding]:
        """What the lint found, as :class:`~docxkit._report.Finding`.

        A finding the edit INTRODUCED always blocks. One the file already
        carried blocks unless the caller allowed those, and is then a
        warning: written over, and still there.
        """
        carried = (Severity.WARNING if self.allowed_existing
                   else Severity.BLOCKING)
        return ([Finding("LINT", p) for p in self.fresh]
                + [Finding("LINT", p, carried, where="already in the file")
                   for p in self.existing])

    def blocking(self) -> list[Finding]:
        """The findings that stopped the write — empty when it went ahead."""
        return blocking_of(self.findings())

    @property
    def ok(self) -> bool:
        return not self.blocking()

    def refusal(self, *, flag: str = "allow_existing_lint=True") -> str:
        """Why nothing was written, and what to do about it; "" if written.

        The two cases are told apart. A finding this edit introduced is
        refused whatever the flag says — that is what makes the flag
        safe, since the most it can do is leave a file as damaged as it
        already was. A finding the file ALREADY carried is not this
        edit's doing, and no docxkit verb repairs those classes, so Word
        is the repair: over 400 real manuscripts, 20 carry one (the
        refusal audit of 2026-09-18).
        """
        if self.written:
            return ""
        if self.fresh:
            return ("REFUSED: this edit would leave markup Word will not "
                    "open; nothing was written")
        name = self.path.name
        return (f"REFUSED: {name} already carried the finding(s) above "
                f"before this run, and nothing was written. This edit did "
                f"not cause them and no docxkit verb repairs these "
                f"classes, so Word is the repair: open {name}, resolve "
                f"what the finding names — accepting or deleting the "
                f"thing it points at — and save; `docxkit lint {name}` "
                f"then says whether it is clear. To write this edit and "
                f"leave the findings as they are, pass {flag}.")


def _already_carried(path: Path, problems: list[str]) -> set[str]:
    """Which of these findings the file on disk ALREADY had.

    Read again rather than remembered: the parts were edited, and the
    file is still exactly what they were read from — nothing is written
    until every check has passed. Only ever asked when there is a
    finding, so an ordinary write pays nothing for it.

    Matched on the finding TEXT, which quotes its specimen, so a finding
    whose specimen this edit rewrote reads as a new one. That is the
    conservative direction: the file is refused rather than written.
    """
    try:
        return set(_lint.lint_parts(_package.read_parts(path))) & set(problems)
    except (PackageError, OSError):
        return set()              # cannot tell; every finding counts as new


def save(path: str | Path, parts: Parts, *, backup_tag: str | None = None,
         backup_into: Path | None = None, allow_existing_lint: bool = False,
         order: list[str] | None = None) -> SaveReport:
    """Protect edge spaces, lint, back up, then write `parts` to `path`.

    ``document.xml`` is indexed, not fetched: a package without it is a
    broken caller and should say so rather than skip the whitespace pass.
    `backup_tag` names the backup and asks for one; `backup_into` is
    where it goes (None: beside the file). Returns what happened —
    `written` is False, and nothing touched, when the lint refused.
    """
    path = Path(path)
    fixed, protected = preserve_space(parts[DOCUMENT].decode("utf-8"))
    parts[DOCUMENT] = fixed.encode("utf-8")
    # through the module, so a caller (or a test) that replaces the
    # lint sees it replaced here too
    problems = _lint.lint_parts(parts)
    carried = _already_carried(path, problems) if problems else set()
    fresh = tuple(p for p in problems if p not in carried)
    existing = tuple(p for p in problems if p in carried)
    if fresh or (existing and not allow_existing_lint):
        return SaveReport(path, protected, fresh, existing,
                          allow_existing_lint)
    kept = (backup(path, tag=backup_tag, into=backup_into)
            if backup_tag is not None else None)
    write_docx(path, parts, order=order)
    return SaveReport(path, protected, fresh, existing, allow_existing_lint,
                      written=True, backup=kept)


def edit_in_place(path: str | Path, transform: Callable[[Parts], object],
                  *, dry: bool = False, allow_existing_lint: bool = True,
                  backup_tag: str | None = None,
                  backup_into: Path | None = None) -> object:
    """Hand `path`'s parts to `transform` and write them back through
    :func:`save`. Returns whatever `transform` returned.

    The transform mutates the dict and returns whatever report it likes;
    every part it does not touch survives byte for byte, and the file is
    replaced by a rename only after the checks pass. Raises
    :class:`~docxkit.errors.PackageError`, having written nothing, when
    the lint refuses. `dry=True` returns the report without writing.

    `allow_existing_lint` defaults to True here and False in the CLI, and
    on purpose: a paper script re-run on a manuscript that already
    carries a finding wrote before this function saved through the
    lint, and a refusal it cannot act on would break every such script
    for a condition it did not cause. A finding the EDIT introduces is
    refused either way. :func:`docxkit.package.edit_in_place` is the raw
    write, kept for the scripts that import it from there.
    """
    path = Path(path)
    if not path.exists():
        raise PackageError(f"Target docx missing: {path}")
    assert_unlocked(path)
    parts = _package.read_parts(path)
    order = list(parts)
    report = transform(parts)
    if dry:
        return report
    saved = save(path, parts, backup_tag=backup_tag, backup_into=backup_into,
                 allow_existing_lint=allow_existing_lint, order=order)
    if not saved.written:
        listed = "\n  - ".join(f.message for f in saved.blocking())
        raise PackageError(f"{path.name}: nothing written. The lint found:"
                           f"\n  - {listed}\n{saved.refusal()}")
    return report
