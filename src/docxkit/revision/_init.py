"""Scaffold the layout for a paper that has not migrated yet.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .. import guard as _guard
from .. import package
from ..errors import ProtocolError
from ._common import _CONFIG, _DIR, _SECTION_RE, RESCUE_KEEP, _today
from ._config import Paper, load_paper
from ._registry import register

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
# Where retired generations of the manuscript go — older than the
# rescue ladder keeps — and what `doctor` should not survey. The
# paper's to name; left unset, nothing is skipped.
{attic}
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
            # No attic given: the key stays out, and the header stays
            # in for the day one is named. It used to default to
            # `D:\PaperAttic\<name>` — one machine's drive letter,
            # written into every paper's config (review 2026-09-03).
            attic=(f"path = {_toml_str(str(attic))}" if attic
                   else '# path = ""'),
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
