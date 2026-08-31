r"""Reading and writing the .docx package itself.

A .docx is a zip of XML parts. Everything in docxkit works on the parts
dict (member name -> bytes) rather than through python-docx, because
python-docx drops parts it does not model — saving through it loses
comments, and it cannot see text inside ``<w:ins>`` at all. Round-tripping
the parts dict preserves every byte the transform did not touch.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# `text_parts` is re-exported, not re-implemented: a build that
# post-processes its own output — protect every edge space, everywhere a
# reader looks — needs the text-bearing parts, and the alternative is the
# caller naming one part itself, the drift R6 removed from fourteen
# modules. It belongs here because it takes the parts dict, which is this
# module's subject.
from ._xml import escape, text_parts, zip_entry
from .errors import DocumentLocked, PackageError

__all__ = [
    "CORE_ORDER",
    "CORE_PART",
    "REGENERATED_BY_WORD",
    "USER_PROPERTIES",
    "DocumentLocked",
    "PackageError",
    "assert_unlocked",
    "backup",
    "changed_parts",
    "core_property",
    "edit_in_place",
    "is_locked",
    "malformed_parts",
    "missing_parts",
    "next_backup_path",
    "part_fingerprint",
    "read_parts",
    "readable",
    "regenerated_by_word",
    "same_part",
    "set_core_property",
    "text_parts",
    "write_docx",
]

CORE_PART = "docProps/core.xml"
#: Parts Word writes for itself on every save, so their absence from a
#: rebuilt package says nothing. Everything ELSE that goes missing is a
#: loss somebody has to put back — and both used to be reported with the
#: same "part dropped" line, which is how the customXml data store
#: disappeared from a manuscript inside a warning nobody could read
#: (see :func:`docxkit.tracked.compare_collateral`).
REGENERATED_BY_WORD = ("docProps/",)
#: …and the one part under that prefix that is NOT Word's bookkeeping.
USER_PROPERTIES = "docProps/custom.xml"


def regenerated_by_word(name: str) -> bool:
    """Is this a part Word rewrites for itself, so its absence says nothing?

    True of ``docProps/app.xml`` — Pages, Words, Lines, which Word
    recomputes on every save — and of the thumbnail beside it, which 39
    of 475 real manuscripts carry.

    False for ``docProps/custom.xml``, and that is the whole point of
    this being a function. Those are USER-DEFINED properties: Word does
    not synthesise them and neither does Compare. On a World Bank
    manuscript the part carries the sensitivity label and the "Official
    Use Only" content marking, so a document that loses it quietly stops
    being labelled. Under one prefix rule it read as "metadata,
    regenerated", the parts gate skipped it by design, and `promote`
    would have copied a redline without it over the manuscript with
    every gate green (Aging_Well R1, 2026-08-21).
    """
    return name.startswith(REGENERATED_BY_WORD) and name != USER_PROPERTIES


#: The order Word itself writes ``docProps/core.xml`` in, read off real
#: manuscripts rather than from the schema's element declarations — the
#: two disagree, and Word's file is what every other reader has to cope
#: with. A property inserted out of order opens fine and fails a strict
#: validator, which is the kind of defect that surfaces at a journal.
CORE_ORDER = ("dc:title", "dc:subject", "dc:creator", "cp:keywords",
              "dc:description", "cp:lastModifiedBy", "cp:revision",
              "dcterms:created", "dcterms:modified")
_CORE_OPEN_RE = re.compile(r"(<cp:coreProperties\b[^>]*>)")


def _core_re(tag: str) -> re.Pattern[str]:
    """The element, in either of the two forms Word writes it.

    An EMPTY property is `<dc:title/>`, and reading only the paired form
    made `set_core_property` take its "absent" branch on a document that
    HAS the element: the new value was inserted beside the empty one and
    the package came back with two `dc:title`s, which the schema forbids
    (2026-08-19). Group 1 is the value, and None for the empty form.
    """
    return re.compile(rf"<{tag}\b[^>]*?(?:/>|>([^<]*)</{tag}>)")


def core_property(parts: dict[str, bytes], tag: str) -> str | None:
    """A ``docProps/core.xml`` value — ``dc:title``, ``dc:creator``, …

    None when the part or the element is absent, which are different
    from an empty string and worth telling apart: Word's Compare drops
    the whole part, and the copy Word writes back afterwards is missing
    individual elements.
    """
    blob = parts.get(CORE_PART)
    if blob is None:
        return None
    m = _core_re(tag).search(blob.decode("utf-8"))
    return (m.group(1) or "") if m else None


def set_core_property(parts: dict[str, bytes], tag: str, value: str) -> bool:
    """Set a core property, CREATING it if absent. True if `parts` moved.

    Absent is the case that matters. A rewrite that only substitutes
    leaves a document with no title and no author while reporting
    success — see :func:`docxkit.authors.set_author`, which is built on
    this. The new element lands in :data:`CORE_ORDER` position; an
    unknown tag goes last, where it cannot displace anything Word wrote.
    """
    blob = parts.get(CORE_PART)
    if blob is None:
        return False
    core = blob.decode("utf-8")
    element = f"<{tag}>{escape(value)}</{tag}>"
    if (m := _core_re(tag).search(core)) is not None:
        if (m.group(1) or "") == escape(value):
            return False
        core = core[:m.start()] + element + core[m.end():]
    else:
        after = CORE_ORDER[CORE_ORDER.index(tag) + 1:] \
            if tag in CORE_ORDER else ()
        nxt = next((f"<{t}" for t in after if f"<{t}" in core), None)
        if nxt is not None:
            core = core.replace(nxt, element + nxt, 1)
        elif "</cp:coreProperties>" in core:
            core = core.replace("</cp:coreProperties>",
                                element + "</cp:coreProperties>", 1)
        else:
            core = _CORE_OPEN_RE.sub(lambda mm: mm.group(1) + element,
                                     core, count=1)
    parts[CORE_PART] = core.encode("utf-8")
    return True


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
        raise DocumentLocked(
            f"{Path(path).name} is locked (open in Word). Close it and retry.")


def read_parts(path: str | Path, *, retries: int = 6,
               delay: float = 0.2) -> dict[str, bytes]:
    """Every member of the package, in stored order.

    A missing path or a non-zip file raises :class:`PackageError` — the
    CLI turns that into a message, where a raw ``FileNotFoundError``
    walked straight through it as a traceback.

    A sharing violation is RETRIED, on the same bounded schedule
    :func:`_replace_atomically` uses for the write side. Two suites read
    a manuscript on a OneDrive-backed tree and failed with `[Errno 13]`
    with nothing holding the file; a retry read it on the first attempt
    seconds later (2026-08-20). One direction hardened and the other not
    is what makes a paper's suite randomly red, and a suite that is
    randomly red is one an author learns to re-run instead of read.

    The last failure says the file is LOCKED rather than unreadable,
    because after five retries that is what it is — and it is the
    wording the write side already uses for the same race.
    """
    last: PermissionError | None = None
    for attempt in range(retries):
        try:
            with zipfile.ZipFile(path) as z:
                return {n: z.read(n) for n in z.namelist()}
        except PermissionError as exc:       # sharing violation, or a lock
            last = exc
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
        except (OSError, zipfile.BadZipFile) as exc:
            raise PackageError(f"cannot read {path}: {exc}") from exc
    raise PackageError(
        f"{Path(path).name} is locked (open in Word). Close it and retry. "
        f"({last})") from last


@contextmanager
def readable(path: str | Path) -> Iterator[tuple[Path, bool]]:
    """A path a READ-ONLY routine can open; ``(path, copied)``.

    Word holds ``working.docx`` while the author edits it, and the two
    commands most worth running at exactly that moment — `revision
    status` and `revision ingest`, both documented read-only — refused
    with "close it and retry" (2026-08-21). The protocol's own resume
    ritual is to run them both.

    Measured the same minute: a byte COPY of the locked file succeeded
    and the full ingest ran on it — 43 changed paragraphs, 22 lost
    anchors — while a direct read of the original raised
    `PermissionError` seconds later. Word's share mode is not reliably
    read-permitting; the copy is what works.

    A snapshot taken mid-edit is a true statement about a moment, and
    the alternative is no answer at all — so the flag comes back with
    the path and the caller SAYS which it read. If the copy fails too,
    the original path is yielded and the caller gets the usual refusal.
    """
    path = Path(path)
    if not is_locked(path):
        yield path, False
        return
    tmp = Path(tempfile.mkdtemp(prefix="docxkit_snapshot_"))
    try:
        copy = tmp / path.name
        try:
            shutil.copy2(path, copy)
        except OSError:
            yield path, False        # nothing better to offer; refuse as usual
        else:
            yield copy, True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


#: Attributes Word rewrites on every save. They carry no meaning for a
#: reader: revision-save ids and the paragraph/text ids Word re-mints.
_VOLATILE_ATTR = re.compile(r"rsid|paraId|textId", re.IGNORECASE)


def _shape(el: Any) -> tuple[Any, ...]:
    kids = tuple(_shape(c) for c in el if isinstance(c.tag, str))
    attrs = tuple(sorted((k, v) for k, v in el.attrib.items()
                         if not _VOLATILE_ATTR.search(k)))
    # Text is significant in a leaf (a `w:t` holds the prose, spaces and
    # all); between child elements it is only Word's or a writer's
    # indentation, and comparing it would report every re-serialisation.
    text = (el.text or "") if not kids else (el.text or "").strip()
    return (el.tag, attrs, text, kids)


def part_fingerprint(blob: bytes) -> str:
    """A hash of what a part MEANS, blind to how it was serialised.

    Two questions look alike and are not: "do these bytes differ" and "did
    someone change this part". A Word save answers yes to the first for
    almost every part in the package — it re-declares namespace prefixes,
    re-mints `w:rsid*`/`w14:paraId`, reorders attributes, reindents — while
    changing nothing a reader could see. Comparing digests of the raw bytes
    therefore reports a style edit on every author round-trip, and the
    warning that cries wolf is the one nobody reads.

    This ignores namespace DECLARATIONS (the prefix bindings, not the
    resolved names), volatile attributes, attribute order and inter-element
    whitespace, and keeps everything else — including leaf text exactly as
    written, because a space inside a ``w:t`` is content.

    Non-XML members (images, the mimetype) hash their bytes directly.
    """
    # Imported HERE, as `malformed_parts` below already did. `package`
    # is what `import docxkit` reaches, so a module-level `from lxml
    # import etree` made the whole package pay ~9 ms for a parser most
    # of it never uses — against a docstring in `tests/test_layering.py`
    # saying it must not. That deferral was already written once and
    # bought nothing while line 24 stood above it.
    from lxml import etree

    try:
        root = etree.fromstring(blob)
    except etree.XMLSyntaxError:
        return hashlib.sha256(blob).hexdigest()
    return hashlib.sha256(repr(_shape(root)).encode("utf-8")).hexdigest()


def same_part(a: bytes, b: bytes) -> bool:
    """True if two versions of a part differ only by serialisation."""
    return part_fingerprint(a) == part_fingerprint(b)


def changed_parts(before: dict[str, bytes],
                  after: dict[str, bytes]) -> dict[str, list[str]]:
    """Which parts really changed, added or vanished between two packages.

    Returns ``{"changed": [...], "added": [...], "removed": [...],
    "resaved": [...]}`` — where `resaved` is the noise bucket: parts whose
    bytes differ but whose meaning does not. A Word round-trip puts nearly
    everything there, which is what makes the `changed` list worth reading.
    """
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed: list[str] = []
    resaved: list[str] = []
    for name in sorted(set(before) & set(after)):
        if before[name] == after[name]:
            continue
        bucket = resaved if same_part(before[name], after[name]) else changed
        bucket.append(name)
    return {"changed": changed, "added": added,
            "removed": removed, "resaved": resaved}


def malformed_parts(parts: dict[str, bytes]) -> list[str]:
    """Which XML parts do not parse, and why.

    Well-formedness only — not the structural rules :mod:`docxkit.lint`
    checks. A part that does not parse is never a legitimate output; a
    part that parses but breaks a schema rule sometimes is (a test
    fixture, an intermediate state), which is why the two are separate
    gates.
    """
    from lxml import etree

    bad = []
    for name, blob in parts.items():
        if not name.endswith((".xml", ".rels")):
            continue                      # media, fonts, embedded objects
        try:
            etree.fromstring(blob)
        except etree.XMLSyntaxError as exc:
            bad.append(f"{name}: {exc}")
    return bad


def missing_parts(parts: dict[str, bytes],
                  baseline: dict[str, bytes]) -> list[str]:
    """Parts the baseline has and `parts` does not, Word's own aside.

    "Did the package survive?" — the question nothing asked. The
    reject-all gate proves the TEXT round-trips; a whole part can go
    missing with every text check green, because no text check reads a
    part that is not there. Word's Compare drops the ``customXml/`` data
    store on every rebuild and `promote` then copies the batch over
    ``working.docx``, so the loss reaches the live manuscript in one
    step (Parental Style 2026-08-12).

    :func:`regenerated_by_word` is excluded: most of ``docProps/*`` is
    Word's own bookkeeping and its absence means nothing.
    ``docProps/custom.xml`` is not, and is gated like any other part.
    """
    return sorted(n for n in baseline
                  if n not in parts and not regenerated_by_word(n))


def write_docx(path: str | Path, parts: dict[str, bytes],
               *, order: list[str] | None = None) -> None:
    """Repack `parts` as a .docx, atomically (temp file, then move).

    `order` preserves the original member order; parts not in it are
    appended, so a transform that ADDS a part (new media for a figure, a
    comments part) is written rather than silently dropped.

    Refuses to write a package whose XML does not parse. Every editing
    path in the toolkit lands here eventually, so this is the one place
    that can make "a spliced element cut an ancestor in half" impossible
    to ship — the LI7 incident, where only a later `docxkit lint` run
    caught a file Word could not open, and the audit and the diff were
    both blind to it because they read with regexes.

    "Atomically" is load-bearing and has two halves. Staging beside the
    target and renaming is the visible one. The other is the fsync: a
    rename can reach the disk before the bytes it points at do, so an
    interrupted save could leave a manuscript-shaped file full of
    nothing while the old one was already gone. Flushing first closes
    that window — the machine this runs on has unreliable mains power,
    which is the whole reason it matters.

    The rename is also retried, because on a OneDrive-backed tree the
    sync engine intermittently holds the destination open or flips it
    read-only mid-write (the same race Stata reports as r(608)), and a
    save that gives up on the first refusal turns a hiccup into lost
    work.

    The bytes are REPRODUCIBLE: the same parts, in the same order, write
    the same file. `writestr` stamps each entry from the clock, which
    made an idempotent pass over an unchanged manuscript produce a
    different md5 every time it took longer than a second — see
    :data:`docxkit._xml.ZIP_STAMP`. With that out, `md5 before == md5
    after` is a legitimate gate, and a render cache keyed on the file
    hash is one line.
    """
    path = Path(path)
    if problems := malformed_parts(parts):
        listed = "\n  - ".join(problems)
        raise PackageError(
            f"refusing to write malformed XML to {path.name}:\n  - {listed}")
    names = list(parts) if order is None else (
        [n for n in order if n in parts]
        + [n for n in parts if n not in order])
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as z:
                for name in names:
                    z.writestr(zip_entry(name), parts[name])
            fh.flush()
            os.fsync(fh.fileno())
        _replace_atomically(tmp, path)
    except BaseException:
        _discard(tmp)
        raise


def _replace_atomically(tmp: Path, target: Path,
                        *, retries: int = 6, delay: float = 0.2) -> None:
    """Rename `tmp` over `target`, riding out transient Windows locks.

    `os.replace` is a real atomic rename within a volume, which
    `shutil.move` is not guaranteed to be — it falls back to copy when
    it thinks it must, and a copy is exactly the interruptible write
    being avoided. Staging is always a sibling of the target, so the
    volume is the same by construction.
    """
    last: OSError | None = None
    for attempt in range(retries):
        try:
            os.replace(tmp, target)
        except PermissionError as exc:      # sharing violation / read-only
            last = exc
            _clear_readonly(target)
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
        else:
            return
    assert last is not None
    raise last


def _clear_readonly(path: Path) -> None:
    try:
        if path.exists():
            os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    except OSError:
        pass


def _discard(path: Path) -> None:
    try:
        _clear_readonly(path)
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
        raise PackageError(f"Target docx missing: {path}")
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


def next_backup_path(path: str | Path, tag: str = "backup", *,
                     into: str | Path | None = None) -> Path:
    """First free ``<stem>_<tag>N.docx`` beside `path` (N starts at 1).

    `into` puts it in another folder instead, keeping the name. Beside
    the manuscript is right for a file the author keeps in a folder of
    their own, and wrong in a revision-protocol folder, whose first rule
    is ONE file: a second .docx there is one keystroke from being the
    one the author opens and edits. See :func:`backup`.
    """
    path, n = Path(path), 1
    folder = Path(into) if into is not None else path.parent
    while True:
        cand = folder / f"{path.stem}_{tag}{n}{path.suffix}"
        if not cand.exists():
            return cand
        n += 1


def backup(path: str | Path, tag: str = "backup", *,
           into: str | Path | None = None) -> Path:
    """Copy `path` to the next free numbered backup and return that path.

    Call this before any build that writes to the file the author edited —
    the build clobbers their work otherwise, and OneDrive version history
    is a poor substitute for a snapshot you took deliberately.

    `into` names the folder the copy goes to, created if it is not
    there. It is how a caller inside the single-file protocol keeps
    prior generations in ``build/rescue/`` rather than beside
    ``working.docx``, where `docxkit smarten --write` put one on
    Aging_Well and a hand `move` took it out again.
    """
    dest = next_backup_path(path, tag, into=into)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest
