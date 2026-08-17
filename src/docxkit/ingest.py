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
links and fixes the pipeline already applied. ``new: ""`` deletes.

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
from difflib import SequenceMatcher
from pathlib import Path

from ._xml import DOCUMENT, FOOTNOTES, PARA_RE, normalize_glyphs, visible_text
from .errors import AnchorError

__all__ = [
    "AnchorError",
    "apply_overrides",
    "build_overrides",
    "load_paragraphs",
    "update_overrides",
]

_FN_RE = re.compile(r'(w:footnoteReference\b[^>]*?w:id=")(\d+)(")')

_cat = visible_text


def _norm(p: str) -> str:
    """Paragraph text with Word's save-time glyph substitutions folded.

    Shares one glyph table with `docxkit.compare`: when they diverged,
    `--expect-clean` called a non-breaking-space change an artifact while
    this function called it an author edit and wrote it into the source.
    """
    return normalize_glyphs(_cat(p)).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _cat(a), _cat(b)).ratio()


def load_paragraphs(path: str | Path) -> tuple[list[str], str]:
    """(paragraph XML list, footnotes XML) for a .docx."""
    with zipfile.ZipFile(path) as z:
        doc = z.read(DOCUMENT).decode("utf-8")
        try:
            foot = z.read(FOOTNOTES).decode("utf-8")
        except KeyError:
            foot = ""
    return PARA_RE.findall(doc), foot


def _footnote_remap(user_foot: str, build_foot: str) -> dict[str, str]:
    """Author footnote id -> build id, matched on definition TEXT.

    Word renumbers footnote ids on save, so an author's paragraph carries
    ids that mean something else in the build. Splicing it raw silently
    repoints footnotes.
    """
    def defs(f: str) -> dict[str, str]:
        return {i: _cat(m) for i, m in re.findall(
            r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)</w:footnote>',
            f, re.DOTALL)}

    ud, bd = defs(user_foot), defs(build_foot)
    return {ui: bi for ui, ut in ud.items() for bi, bt in bd.items()
            if ut.strip() and ut.strip() == bt.strip()}


def build_overrides(baseline: str | Path,
                    edited: str | Path) -> list[tuple[str, str]]:
    """Align a baseline build against the author's file.

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
    * remap footnote ids by definition text.
    """
    base_paras, base_foot = load_paragraphs(baseline)
    user_paras, user_foot = load_paragraphs(edited)
    remap = _footnote_remap(user_foot, base_foot)

    def fix(s: str) -> str:
        return _FN_RE.sub(
            lambda m: m.group(1) + remap.get(m.group(2), m.group(2))
            + m.group(3), s)

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

    Returns (this round's overrides, chained, appended, total stored).
    """
    overrides_path = Path(overrides_path)
    fresh = build_overrides(baseline, edited)
    data = (json.loads(overrides_path.read_text(encoding="utf-8"))
            if overrides_path.exists() else [])
    chained = appended = 0
    for old, new in fresh:
        existing = next((e for e in data if e["new"] and e["new"] == old),
                        None)
        if existing:
            existing["new"] = new
            chained += 1
        else:
            data.append({"old": old, "new": new})
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
    """
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
