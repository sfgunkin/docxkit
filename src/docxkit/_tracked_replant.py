"""A bookmark Compare moved onto RE-INSERTED text, set back over both copies.

Month_of_birth R19 (2026-11-19, backlog S2) trimmed words on both sides of
a first-mention label it kept, ``Chen and Park 2021`` inside its marker
bookmark ``Chen2021txt``. Word's Compare did not keep the label as common
text: it deleted the whole stretch, label included, and inserted
``"; " + label + ")."`` after it, with the bookmark only inside the
``w:ins``. Rejecting the round then dropped the bookmark, and the build
refused, correctly, on a clean edit that was not wrong. Compare at word
and at character level, with moves on and off, all did the same.

The repair rests on one property, measured on that redline in Word and in
the XML views (2026-11-19): **the order of an adjacent ``w:del`` and
``w:ins`` is invisible to both views** — accepting drops the one, rejecting
the other. So Word's own two elements are split at the label and
interleaved, and the bookmark is set over the pair::

    del[pre] ins[pre] <bookmarkStart> del[label] ins[label] <bookmarkEnd>
    ins[post] del[post]

Rejecting leaves the bookmark on the deleted copy, accepting on the
inserted one, and both views keep it over exactly the label: Word's
Accept All and Reject All gave ``'Chen and Park 2021'`` both ways. No
revision content is written — every run is one Compare wrote, in the
element kind Compare put it in — which is what CONTRIBUTING's rule against
hand-authored ``w:ins``/``w:del`` protects. The two placements that do
not reorder were measured too and each fails one view: the bookmark on
the deleted copy alone is lost on accept (Word and XML agree), and one
spanning both copies in Compare's order wraps the whole deleted sentence
on reject.

Each candidate is kept only when both views' visible text is unchanged
and both now hold the bookmark; anything else is left for the build's
refusal, which still names the cause (:func:`inserted_only_bookmarks`).

**Bookmark tags between the pair** (Month_of_birth R23, 2026-11-20). "(Table
A7 and Figure 4)." became "(Figure 4).", and Compare wrote
``del[Table A7 and Figure 4).] <start TableA7txt/> <start Figure4txt/>
<end TableA7txt/> ins[Figure 4 <end Figure4txt/> ).]``: the start of the
lost bookmark sits BETWEEN the two elements and only its end inside the
``w:ins``. Rejecting keeps that start, and only that, so the bookmark is
lost the same way. A gap of bookmark tags is therefore allowed between the
pair. The lost bookmark's half in it moves to the edge of the ``w:ins`` it
touches, which is the same place in the accepted view and nothing in the
rejected one. What remains of the gap must be point bookmarks (a start
followed directly by its own end), which cover no text. The gap goes back
on the side that leaves its accepted position as it was: in front of the
pair when the deletion comes first, after it when the insertion does.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from . import revisions as _revisions
from ._xml import (
    BOOKMARK_NAME_RE,
    BOOKMARK_TAG_RE,
    TEXT_PARTS,
    Parts,
    visible_text,
)

#: One top-level child of a ``w:ins``/``w:del`` as Compare writes it: a
#: run, or an empty element (a bookmark tag). Anything else — a nested
#: revision, a move range, a smart tag — fails the cover check and the
#: candidate is left alone.
_CHILD_RE = re.compile(
    r"(?P<run><w:r\b[^>]*/>|<w:r\b[^>]*(?<!/)>.*?</w:r>)"
    r"|<w:[A-Za-z]+\b[^>]*/>",
    re.DOTALL)
#: An element's body that never crosses its own close tag.
_DEL = r"(?P<do><w:del\b[^>]*(?<!/)>)(?P<db>(?:(?!</w:del>).)*)</w:del>"
_INS = r"(?P<io><w:ins\b[^>]*(?<!/)>)(?P<ib>(?:(?!</w:ins>).)*)</w:ins>"
#: Bookmark tags and nothing else between the two (R23's shape).
_GAP = r"(?P<gap>(?:<w:bookmark(?:Start|End)\b[^>]*/>)*)"
#: A deletion and an insertion with only bookmark tags between them, in
#: either order: Compare writes the deletion first.
_DEL_INS_RE = re.compile(_DEL + _GAP + _INS, re.DOTALL)
_INS_DEL_RE = re.compile(_INS + _GAP + _DEL, re.DOTALL)
_ID_RE = re.compile(r'\bw:id="(\d+)"')
_TAG_RE = BOOKMARK_TAG_RE


def _children(body: str) -> tuple[list[str], set[int]] | None:
    """`body` as its top-level children and which of them are runs, or
    None if anything else is in it."""
    found = list(_CHILD_RE.finditer(body))
    if "".join(m.group(0) for m in found) != body:
        return None
    return ([m.group(0) for m in found],
            {i for i, m in enumerate(found) if m.group("run")})


def _sig(run: str) -> str:
    """A run as the accepted view would read it, its own tag's attributes
    (rsids) dropped: the deleted copy of a label and the inserted one
    compare equal."""
    run = "<w:r>" + run[run.index(">") + 1:]
    return (run.replace("<w:delText", "<w:t").replace("</w:delText>", "</w:t>")
            .replace("<w:delInstrText", "<w:instrText")
            .replace("</w:delInstrText>", "</w:instrText>"))


@dataclass(frozen=True)
class _Candidate:
    name: str
    start: int          # span of the del + ins pair in the part
    end: int
    rewritten: str


def _rewrite(ins_open: str, ins: tuple[list[str], set[int]], del_open: str,
             dele: tuple[list[str], set[int]], *, name: str,
             next_id: Iterator[int]) -> str | None:
    """The interleaved pair, or None when the label is not in the deletion
    exactly once."""
    (ins_kids, ins_runs), (del_kids, del_runs) = ins, dele
    starts = [i for i, k in enumerate(ins_kids)
              if k.startswith("<w:bookmarkStart") and f'w:name="{name}"' in k]
    if len(starts) != 1:
        return None
    a = starts[0]
    bid = _ID_RE.search(ins_kids[a])
    if not bid:
        return None
    end_id = f'w:id="{bid.group(1)}"'
    ends = [i for i, k in enumerate(ins_kids)
            if k.startswith("<w:bookmarkEnd") and end_id in k]
    if len(ends) != 1 or ends[0] < a:
        return None
    b = ends[0]
    inner = range(a + 1, b)
    if not inner or any(i not in ins_runs for i in inner):
        return None
    label = [_sig(ins_kids[i]) for i in inner]
    sigs = [(i, _sig(k)) for i, k in enumerate(del_kids) if i in del_runs]
    hits = [n for n in range(len(sigs) - len(label) + 1)
            if [s for _, s in sigs[n:n + len(label)]] == label]
    if len(hits) != 1:
        return None
    d0 = sigs[hits[0]][0]
    d1 = sigs[hits[0] + len(label) - 1][0] + 1

    def wrap(opener: str, kids: list[str], kind: str) -> str:
        if not kids:
            return ""
        return (_ID_RE.sub(f'w:id="{next(next_id)}"', opener, count=1)
                + "".join(kids) + f"</w:{kind}>")

    return (wrap(del_open, del_kids[:d0], "del")
            + wrap(ins_open, ins_kids[:a], "ins")
            + ins_kids[a]
            + wrap(del_open, del_kids[d0:d1], "del")
            + wrap(ins_open, ins_kids[a + 1:b], "ins")
            + ins_kids[b]
            + wrap(ins_open, ins_kids[b + 1:], "ins")
            + wrap(del_open, del_kids[d1:], "del"))


def _is_points(tags: list[str]) -> bool:
    """Every start in `tags` directly followed by its own end, and nothing
    else: bookmarks that cover no text, so moving them moves no range."""
    if len(tags) % 2:
        return False
    for start, end in zip(tags[::2], tags[1::2], strict=True):
        sid, eid = _ID_RE.search(start), _ID_RE.search(end)
        if (not start.startswith("<w:bookmarkStart")
                or not end.startswith("<w:bookmarkEnd")
                or sid is None or eid is None or sid.group(1) != eid.group(1)):
            return False
    return True


def _pull(gap: list[str], ins_body: str, name: str, *,
          ins_first: bool) -> tuple[str, list[str]] | None:
    """`ins_body` with `name`'s half from the gap moved to the edge of the
    insertion it touches, and what stays in the gap; None when the rest of
    the gap is not point bookmarks or the half is on the wrong side."""
    tags = gap + _TAG_RE.findall(ins_body)
    starts = [t for t in tags if t.startswith("<w:bookmarkStart")
              and f'w:name="{name}"' in t]
    bid = _ID_RE.search(starts[0]) if len(starts) == 1 else None
    if bid is None:
        return None
    ends = [t for t in tags if t.startswith("<w:bookmarkEnd")
            and f'w:id="{bid.group(1)}"' in t]
    if len(ends) != 1:
        return None
    moved = [t for t in (starts[0], ends[0]) if t in gap]
    rest = [t for t in gap if t not in moved]
    if len(moved) > 1 or not _is_points(rest):
        return None
    if not moved:
        return ins_body, rest
    if moved[0] is starts[0]:           # a start before the insertion
        return None if ins_first else (moved[0] + ins_body, rest)
    return (ins_body + moved[0], rest) if ins_first else None  # an end after


def _candidates(xml: str, lost: set[str],
                next_id: Iterator[int]) -> Iterator[_Candidate]:
    """Each lost bookmark sitting inside a ``w:ins`` that has a ``w:del``
    for a neighbour, either side, with that pair rewritten. Bookmark tags
    between the two are allowed as the module docstring says."""
    for pattern, ins_first in ((_DEL_INS_RE, False), (_INS_DEL_RE, True)):
        for m in pattern.finditer(xml):
            gap = _TAG_RE.findall(m.group("gap"))
            names = [n for n in BOOKMARK_NAME_RE.findall(
                         m.group("ib") + m.group("gap")) if n in lost]
            dele = _children(m.group("db")) if names else None
            if dele is None:
                continue
            for name in dict.fromkeys(names):
                pulled = _pull(gap, m.group("ib"), name, ins_first=ins_first)
                ins = _children(pulled[0]) if pulled else None
                if pulled is None or ins is None:
                    continue
                new = _rewrite(m.group("io"), ins, m.group("do"), dele,
                               name=name, next_id=next_id)
                if new is not None:
                    rest = "".join(pulled[1])
                    new = new + rest if ins_first else rest + new
                    yield _Candidate(name, m.start(), m.end(), new)


def _names(xml: str) -> set[str]:
    return set(BOOKMARK_NAME_RE.findall(xml))


def replant_reinserted_bookmarks(parts: Parts, original: Parts) -> list[str]:
    """Set each bookmark of `original` that rejecting `parts` would lose,
    because Compare re-inserted the text it marks next to the deleted
    copy, over both copies. Rewrites `parts` in place; returns what was
    repaired. See the module docstring for the measurement it rests on.
    """
    wanted = set().union(*(_names(original[p].decode("utf-8"))
                           for p in TEXT_PARTS if p in original))
    done: list[str] = []
    for part in TEXT_PARTS:
        if part not in parts:
            continue
        xml = parts[part].decode("utf-8")
        if not _DEL_INS_RE.search(xml) and not _INS_DEL_RE.search(xml):
            continue
        tried: set[str] = set()
        while True:
            rejected = _revisions.reject(xml)
            lost = (wanted & _names(xml)) - _names(rejected) - tried
            if not lost:
                break
            top = max((int(i) for i in _ID_RE.findall(xml)), default=0)
            fresh = iter(range(top + 1, top + 1_000_000))
            accepted = _revisions.accept(xml)
            for c in _candidates(xml, lost, fresh):
                trial = xml[:c.start] + c.rewritten + xml[c.end:]
                t_acc = _revisions.accept(trial)
                t_rej = _revisions.reject(trial)
                if (visible_text(t_acc) == visible_text(accepted)
                        and visible_text(t_rej) == visible_text(rejected)
                        and c.name in _names(t_acc)
                        and c.name in _names(t_rej)):
                    xml = trial
                    done.append(
                        f"bookmark {c.name!r}: Compare deleted the text it "
                        f"marks and inserted it again; set over both copies "
                        f"so rejecting keeps it ({part})")
                    break
                tried.add(c.name)
            else:
                break
        if xml != parts[part].decode("utf-8"):
            parts[part] = xml.encode("utf-8")
    return done
