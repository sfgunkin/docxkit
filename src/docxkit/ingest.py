r"""Folding the author's Word edits back into the build source.

The recurring workflow: the author edits the BUILT .docx in Word, and those
edits have to end up in whatever generates it, so the next build reproduces
them. The recurring failure is losing an edit — one hidden inside a
multi-paragraph block, a citation field Word stripped, a formula reverted.

The defence is mechanical, never visual: build a baseline from the current
source, align it against the author's file paragraph by paragraph, and gate
the result with :mod:`docxkit.compare` ``--expect-clean``. If you find
yourself reading truncated paragraph text to decide whether something
changed, stop — that is the habit that loses edits.

Overrides are ``{"old": <paragraph xml>, "new": <paragraph xml>}`` pairs
anchored on the BUILD OUTPUT, so they compose with whatever footnotes,
links and fixes the pipeline already applied. ``new: ""`` deletes. An
entry may carry ``"part"``; without one it means ``word/document.xml``,
which is what every store written before that key existed says.

The anchor is therefore a paragraph's XML, which assumes two paragraphs
are never byte-identical. Word's own files satisfy that — every
paragraph carries its own ``w14:paraId`` — but a baseline BUILT here
need not: :func:`docxkit.body.para` emits none, so two identical "Notes:"
lines under two tables are the same anchor, and an edit to the second is
applied to the first. Give generated paragraphs a paraId, or gate the
round with ``compare --expect-clean``, which sees the moved text.
"""
from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from ._xml import (
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    NOTE_DEF_RE,
    PARA_RE,
    Parts,
    normalize_glyphs,
    visible_text,
)
from .errors import AnchorError, NoteEdit

__all__ = [
    "AnchorError",
    "NoteEdit",
    "apply_overrides",
    "apply_part_overrides",
    "build_overrides",
    "build_part_overrides",
    "load_paragraphs",
    "update_overrides",
]

#: How a note is REFERENCED, and how it is DEFINED, per store. Word
#: renumbers both stores' ids on save, so an author's paragraph carries
#: ids that mean something else in the build — and until 2026-08-20 only
#: the footnote half was remapped, which spliced an endnote reference
#: raw and repointed it at whatever note the build had given that id.
_NOTE_REF_RE = {
    FOOTNOTES: re.compile(r'(w:footnoteReference\b[^>]*?w:id=")(\d+)(")'),
    ENDNOTES: re.compile(r'(w:endnoteReference\b[^>]*?w:id=")(\d+)(")'),
}

_cat = visible_text


def _norm(p: str) -> str:
    """Paragraph text with Word's save-time glyph substitutions folded.

    Shares one glyph table with `docxkit.compare`: when they diverged,
    `--expect-clean` called a non-breaking-space change an artifact while
    this function called it an author edit and wrote it into the source.

    NOT stripped. It was, and a leading space the author typed — which
    Word prints as an indent — then aligned as "equal", produced no
    override, and was dropped by the fold-back while `revision ingest`
    reported nothing either (Aging_Well A.4, 2026-09-11, backlog S1).
    A paragraph that is nothing but whitespace still compares as blank:
    a lone space prints as an empty line either way.
    """
    text = normalize_glyphs(_cat(p))
    return text if text.strip() else ""


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _cat(a), _cat(b)).ratio()


def load_paragraphs(path: str | Path) -> tuple[list[str], str]:
    """(BODY paragraph XML list, footnotes XML) for a .docx.

    The paragraphs are the body's. The footnotes come back whole and
    unparsed because the caller that wants them wants them for one
    thing — remapping the ids Word renumbered on save.

    Kept at this shape because it is public and unpacked by callers
    outside this package; :func:`build_part_overrides` reads every part
    a reader edits through `_part_paragraphs` instead.
    """
    with zipfile.ZipFile(path) as z:
        doc = z.read(DOCUMENT).decode("utf-8")
        try:
            foot = z.read(FOOTNOTES).decode("utf-8")
        except KeyError:
            foot = ""
    return PARA_RE.findall(doc), foot


def _note_stores(path: str | Path) -> dict[str, str]:
    """Both note parts, whole and unparsed, for the id remap.

    Read here rather than through `load_paragraphs`, whose two-value
    answer is public and whose callers outside this module unpack it.
    """
    out = {}
    with zipfile.ZipFile(path) as z:
        for part in (FOOTNOTES, ENDNOTES):
            try:
                out[part] = z.read(part).decode("utf-8")
            except KeyError:
                out[part] = ""
    return out


def _note_remap(user: str, build: str, part: str) -> dict[str, str]:
    """Author note id -> build id, matched on definition TEXT.

    Word renumbers note ids on save, so an author's paragraph carries
    ids that mean something else in the build. Splicing it raw silently
    repoints the note.
    """
    def defs(f: str) -> dict[str, str]:
        return {i: _cat(m) for i, m in NOTE_DEF_RE[part].findall(f)}

    ud, bd = defs(user), defs(build)
    return {ui: bi for ui, ut in ud.items() for bi, bt in bd.items()
            if ut.strip() and ut.strip() == bt.strip()}


def _part_paragraphs(path: str | Path) -> dict[str, list[str]]:
    """Every part a reader edits, as its own paragraph list.

    The body and both note stores. `load_paragraphs` above answers for
    the body alone and is public, so this is the widened reader rather
    than a changed signature.
    """
    out: dict[str, list[str]] = {}
    with zipfile.ZipFile(path) as z:
        for part in (DOCUMENT, FOOTNOTES, ENDNOTES):
            try:
                out[part] = PARA_RE.findall(z.read(part).decode("utf-8"))
            except KeyError:
                continue
    return out


def _remapper(baseline: str | Path,
              edited: str | Path) -> Callable[[str], str]:
    """Rewrite an author paragraph's note ids into the build's numbering."""
    base_notes, user_notes = _note_stores(baseline), _note_stores(edited)
    remaps = {part: _note_remap(user_notes[part], base_notes[part], part)
              for part in _NOTE_REF_RE}

    def fix(s: str) -> str:
        for part, pattern in _NOTE_REF_RE.items():
            remap = remaps[part]

            def one(m: re.Match[str], remap: dict[str, str] = remap) -> str:
                return (m.group(1) + remap.get(m.group(2), m.group(2))
                        + m.group(3))

            s = pattern.sub(one, s)
        return s

    return fix


def build_part_overrides(baseline: str | Path, edited: str | Path,
                         ) -> dict[str, list[tuple[str, str]]]:
    """Align a baseline build against the author's file, PART by part.

    ``{part name: [(old_xml, new_xml), …]}``, and only for parts that
    moved. The body is aligned exactly as :func:`build_overrides`
    aligns it — same rules, same code — and each note store is aligned
    the same way, which is what makes an edit inside a footnote
    DEFINITION land somewhere instead of nowhere.

    A part on one side only is skipped rather than read as a wholesale
    delete or insert: a missing part is a package loss, which
    `revision.ingest` and `package.missing_parts` already gate, and a
    note store that appears for the first time has no baseline
    paragraph to anchor an insert on.
    """
    base, user = _part_paragraphs(baseline), _part_paragraphs(edited)
    fix = _remapper(baseline, edited)
    out: dict[str, list[tuple[str, str]]] = {}
    for part, base_paras in base.items():
        if part not in user:
            continue
        pairs = _align(base_paras, user[part], fix)
        if pairs:
            out[part] = pairs
    return out


def build_overrides(baseline: str | Path, edited: str | Path, *,
                    allow_note_loss: bool = False) -> list[tuple[str, str]]:
    """Align a baseline build against the author's file — the BODY.

    SUPERSEDED by :func:`build_part_overrides` + :func:`apply_part_overrides`,
    which carry the part an override belongs to. This pair raises
    :class:`docxkit.errors.NoteEdit` the moment the author touches a note
    definition, which is not a rare event, so a pipeline built on it
    stops at the next round rather than at a chosen moment.

    Returns (old_xml, new_xml) pairs; ``new == ""`` is a deletion. The
    alignment rules are the ones that took several rounds to get right:

    * align on glyph-normalized text, so a Word quote-normalization is not
      mistaken for an edit;
    * an EQUAL-sized change block pairs POSITIONALLY — a heavily reworded
      paragraph has a low similarity ratio but is still the same
      paragraph, and thresholding it splits it into a bogus delete+insert;
    * baseline > author (a merge or move) — ratio-pair the survivors, the
      rest are deletions;
    * author > baseline (an insert) — ratio-pair, then attach the extra
      paragraphs to the last paired override so they land in sequence;
    * remap footnote AND endnote ids by definition text.

    **Body paragraphs only, and it now SAYS so.** An override is anchored
    on a paragraph's XML with no room to name a part, and
    :func:`apply_overrides` takes ``document.xml`` alone — so an edit
    the author made inside a note DEFINITION produced no override, and
    the next clean build regenerated from a source that never received
    it. `revision.ingest` DESCRIBES such an edit, because `compare`
    reads every part a reader sees, which made this the worse half of
    the pair: named in the report and dropped by the fold-back, a
    combination that reads as "handled".

    So it raises :class:`docxkit.errors.NoteEdit` instead. Use
    :func:`build_part_overrides` with :func:`apply_part_overrides`, which
    carry the part; ``allow_note_loss=True`` is the old behaviour for a
    caller that has decided the note edit does not matter.
    """
    by_part = build_part_overrides(baseline, edited)
    notes = {p: len(v) for p, v in by_part.items() if p != DOCUMENT}
    if notes and not allow_note_loss:
        raise NoteEdit(
            "the author edited a note DEFINITION — "
            + ", ".join(f"{n} paragraph(s) in {p}" for p, n in notes.items())
            + " — and this fold-back writes document.xml only, so those "
              "edits would be dropped while `compare` reported them. Use "
              "build_part_overrides() + apply_part_overrides(), or pass "
              "allow_note_loss=True to keep the body-only behaviour "
              "deliberately.")
    return by_part.get(DOCUMENT, [])


def _align(base_paras: list[str], user_paras: list[str],
           fix: Callable[[str], str]) -> list[tuple[str, str]]:
    sm = SequenceMatcher(None, [_norm(p) for p in base_paras],
                         [_norm(p) for p in user_paras], autojunk=False)
    overrides: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        bls, us = list(range(i1, i2)), list(range(j1, j2))
        if len(bls) == len(us):
            for b, u in zip(bls, us, strict=True):
                overrides.append((base_paras[b], fix(user_paras[u])))
        elif len(bls) > len(us):
            remaining = set(bls)
            for u in us:
                b = max(remaining,
                        key=lambda b: _ratio(base_paras[b], user_paras[u]))
                remaining.discard(b)
                overrides.append((base_paras[b], fix(user_paras[u])))
            for b in sorted(remaining):
                overrides.append((base_paras[b], ""))
        else:
            remaining, block = set(us), []
            for b in bls:
                u = max(remaining,
                        key=lambda u: _ratio(base_paras[b], user_paras[u]))
                remaining.discard(u)
                block.append((base_paras[b], fix(user_paras[u])))
            extra = "".join(fix(user_paras[u]) for u in sorted(remaining))
            if block:
                block[-1] = (block[-1][0], block[-1][1] + extra)
                overrides.extend(block)
            elif extra and i1:
                # A PURE insert: nothing in this block came from the
                # baseline, so it has no override of its own to ride on
                # and must be anchored on the paragraph BEFORE it.
                #
                # This used to attach to `overrides[-1]`, the last
                # CHANGED paragraph — which is only the paragraph before
                # when the author's previous edit happened to be
                # adjacent. Fixing a typo in the introduction and adding
                # a paragraph in section 5 put the new paragraph in the
                # introduction, silently, with nothing raised (measured
                # 2026-08-17; 33 mutants were living on that line).
                # A second entry with the same `old` is safe even when
                # the manuscript repeats a paragraph verbatim (a bare
                # "Notes:" line under every table): `apply_overrides`
                # replaces ONE occurrence per entry, in order, so the
                # entries land on successive copies.
                overrides.append((base_paras[i1 - 1],
                                  base_paras[i1 - 1] + extra))
            elif extra:
                raise AnchorError(
                    "leading insert with no anchor paragraph: "
                    f"{_cat(user_paras[j1])[:60]!r}")
    return overrides


def update_overrides(baseline: str | Path, edited: str | Path,
                     overrides_path: str | Path,
                     ) -> tuple[list[tuple[str, str]], int, int, int]:
    """Merge this round's overrides into the stored list.

    CHAINS rather than duplicates: if a stored override already PRODUCES
    the paragraph this round starts from (its ``new`` equals the new
    ``old``), that entry is updated in place. Appending instead would
    leave a dead entry whose anchor no longer exists.

    Every part is read, and an entry outside the body carries a ``part``
    key naming its store — a footnote the author retyped used to produce
    no entry at all. Body entries keep the two-key shape they have
    always had, so an existing store stays byte-comparable and
    :func:`apply_overrides` can still read one that has no note edits in
    it. `fresh` is every part's pairs, in part order.

    Returns (this round's overrides, chained, appended, total stored).
    """
    overrides_path = Path(overrides_path)
    by_part = build_part_overrides(baseline, edited)
    data = (json.loads(overrides_path.read_text(encoding="utf-8"))
            if overrides_path.exists() else [])
    chained = appended = 0
    fresh: list[tuple[str, str]] = []
    for part, pairs in by_part.items():
        for old, new in pairs:
            fresh.append((old, new))
            # Chain within the PART. Two stores' paragraphs can be
            # byte-identical — a note and a body line both reading
            # "Source: authors' calculations." — and chaining across
            # them would rewrite the wrong entry.
            existing = next(
                (e for e in data if e["new"] and e["new"] == old
                 and e.get("part", DOCUMENT) == part), None)
            if existing:
                existing["new"] = new
                chained += 1
            else:
                entry = {"old": old, "new": new}
                if part != DOCUMENT:
                    entry["part"] = part
                data.append(entry)
                appended += 1
    overrides_path.write_text(json.dumps(data, ensure_ascii=False),
                              encoding="utf-8")
    return fresh, chained, appended, len(data)


def apply_overrides(doc_xml: str, overrides: list[dict[str, str]],
                    *, strict: bool = True) -> tuple[str, int, list[str]]:
    """Apply stored overrides to ``document.xml``.

    Returns (xml, applied, missed) where `missed` lists the leading text of
    every override whose anchor was not found — a miss means the build
    changed under the override and the author's edit is being dropped, so
    `strict` raises rather than let that pass silently.

    An entry naming another PART is refused rather than counted as a
    miss: this function has one string to write into, so a footnote
    override handed to it can only be dropped, and "the build moved
    under them" would be the wrong reason. Read such a store with
    :func:`apply_part_overrides`.
    """
    stray = {e["part"] for e in overrides
             if e.get("part", DOCUMENT) != DOCUMENT}
    if stray:
        raise NoteEdit(
            f"this store carries overrides for {', '.join(sorted(stray))} "
            f"and apply_overrides writes {DOCUMENT} only — use "
            f"apply_part_overrides(parts, overrides), which takes the "
            f"whole package.")
    applied, missed = 0, []
    for entry in overrides:
        old, new = entry["old"], entry["new"]
        if old not in doc_xml:
            missed.append(_cat(old)[:70])
            continue
        doc_xml = doc_xml.replace(old, new, 1)
        applied += 1
    if strict and missed:
        raise AnchorError(
            f"{len(missed)} override anchor(s) not found - the build moved "
            f"under them: {missed[:3]}")
    return doc_xml, applied, missed


def apply_part_overrides(parts: Parts,
                         overrides: list[dict[str, str]],
                         *, strict: bool = True) -> tuple[int, list[str]]:
    """Apply stored overrides to the whole package; (applied, missed).

    Mutates `parts`. Each entry's ``part`` says where it belongs and
    defaults to ``word/document.xml``, so a store written before that
    key existed applies exactly as :func:`apply_overrides` applied it.

    An entry for a part the package does not carry is a MISS, not a
    KeyError: it is the same failure as an anchor that moved — the
    author's edit is not being written — and it is reported the same
    way.
    """
    applied, missed = 0, []
    for entry in overrides:
        part = entry.get("part", DOCUMENT)
        blob = parts.get(part)
        old, new = entry["old"], entry["new"]
        if blob is None or old not in (xml := blob.decode("utf-8")):
            missed.append(f"({part}) {_cat(old)[:70]}")
            continue
        parts[part] = xml.replace(old, new, 1).encode("utf-8")
        applied += 1
    if strict and missed:
        raise AnchorError(
            f"{len(missed)} override anchor(s) not found - the build moved "
            f"under them: {missed[:3]}")
    return applied, missed
