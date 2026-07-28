r"""Reading and writing the .docx package itself.

A .docx is a zip of XML parts. Everything in docxkit works on the parts
dict (member name -> bytes) rather than through python-docx, because
python-docx drops parts it does not model — saving through it loses
comments, and it cannot see text inside ``<w:ins>`` at all. Round-tripping
the parts dict preserves every byte the transform did not touch.
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

__all__ = [
    "assert_unlocked",
    "backup",
    "edit_in_place",
    "is_locked",
    "next_backup_path",
    "read_parts",
    "write_docx",
]


def is_locked(path: str | Path) -> bool:
    """True if `path` is held open by another process (usually Word)."""
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except FileNotFoundError:
        return False


def assert_unlocked(path: str | Path) -> None:
    """Raise if `path` is open in Word.

    Worth calling before any write: Word holds an exclusive handle, so the
    write fails half-way and leaves a truncated file where the manuscript
    used to be.
    """
    if is_locked(path):
        raise SystemExit(
            f"{Path(path).name} is locked (open in Word). Close it and retry.")


def read_parts(path: str | Path) -> dict[str, bytes]:
    """Every member of the package, in stored order."""
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def write_docx(path: str | Path, parts: dict[str, bytes],
               *, order: list[str] | None = None) -> None:
    """Repack `parts` as a .docx, atomically (temp file, then move).

    `order` preserves the original member order; parts not in it are
    appended, so a transform that ADDS a part (new media for a figure, a
    comments part) is written rather than silently dropped.
    """
    path = Path(path)
    names = list(parts) if order is None else (
        [n for n in order if n in parts]
        + [n for n in parts if n not in order])
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.writestr(name, parts[name])
    shutil.move(str(tmp), str(path))


def edit_in_place(path: str | Path,
                  transform: Callable[[dict[str, bytes]], object],
                  *, dry: bool = False) -> object:
    """Hand `path`'s parts to `transform` and rewrite the file in place.

    The transform mutates the dict and returns whatever report it likes.
    Every part it does not touch survives byte-for-byte, and parts it adds
    are written. Work happens on a copy in TEMP, so a crash mid-transform
    cannot damage the original — and `dry=True` returns the report without
    writing at all.
    """
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Target docx missing: {path}")
    assert_unlocked(path)
    with tempfile.TemporaryDirectory(prefix="docxkit_") as td:
        work = Path(td) / "in.docx"
        shutil.copy2(path, work)
        with zipfile.ZipFile(work) as z:
            order = z.namelist()
            parts = {n: z.read(n) for n in order}
        report = transform(parts)
        if dry:
            return report
        out = Path(td) / "out.docx"
        write_docx(out, parts, order=order)
        shutil.copy2(out, path)
        return report


def next_backup_path(path: str | Path, tag: str = "backup") -> Path:
    """First free ``<stem>_<tag>N.docx`` beside `path` (N starts at 1)."""
    path = Path(path)
    n = 1
    while True:
        cand = path.with_name(f"{path.stem}_{tag}{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def backup(path: str | Path, tag: str = "backup") -> Path:
    """Copy `path` to the next free numbered backup and return that path.

    Call this before any build that writes to the file the author edited —
    the build clobbers their work otherwise, and OneDrive version history
    is a poor substitute for a snapshot you took deliberately.
    """
    dest = next_backup_path(path, tag)
    shutil.copy2(path, dest)
    return dest
