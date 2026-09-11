r"""What the exhibits ARE: every caption, and the span each one owns.

Five modules answered parts of this question and none answered it.
`placement._blocks` knows a table captioned above it; `placement.exhibit_block`
knows one exhibit named by its caption, captioned above; `figures.find_all`
knows a figure's drawings by embed id; `tables.by_caption` knows which table
a caption owns; `crossrefs.find_captions` knows the captions and nothing
about their bodies. `repack` then wrote a sixth, and the code review of
`a90be3a` found eight defects in it — a caption claiming the exhibit above
it, an image absorbed as a spacer, a box that never finds its mention. This
is the one definition, a layer below all of them.

* **A caption** is a paragraph `find.caption_re` matches — THE caption
  definition — or a table whose first cell opens with one: a Box, which
  IS its own exhibit, or a one-cell frame holding nothing but the
  caption, which owns a body like a paragraph does.
* **A body** is a table, or a paragraph holding a drawing and no words. A
  prose paragraph with a chart anchored in it is prose; moving it would
  move the sentence.
* **Which side the body is on is read off the document, per caption.**
  A caption sees at most one candidate on each side — the nearest body of
  its kind, across blank paragraphs, notes and markers only — and a
  caption with ONE candidate takes it, which takes that body out of every
  other caption's reach (the propagation `tables._beside` settles a run
  of tables with). What is still ambiguous follows the document's own
  majority, and sits below the caption where the document has no opinion.
  Aging_Well captions its figures underneath, HCW above, LE_trends has an
  uncaptioned chart directly above a table's caption, and all three read
  correctly without being told.
* **The span** is caption and body, the bookmarks Word hoisted in front,
  and the notes and blank paragraphs behind — up to the next BODY. That
  clause is where the sixth copy went wrong: an image is a paragraph with
  no text, and a walk absorbing blank paragraphs took Figure 1's picture
  into Box 1's block.

Read-only. It answers what is there; `placement` moves it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from .find import (
    DEFAULT_LABELS,
    TABLE_LABELS,
    caption_re,
    continuation_re,
    mention_re,
)

__all__ = [
    "NOTE",
    "PANEL",
    "Exhibit",
    "exhibits",
    "is_body",
    "mention_of",
    "text_of",
]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: A note BELONGS to the exhibit above it and travels with it.
#:
#: The keywords are not enough, and a manuscript proved it: DSI's таблица 4
#: carries «Примечание. Ориентация…» AND, under it, «* Высокая доля
#: самостоятельной занятости…» — the gloss on the `*` marking one of its rows.
#: The keyword-only pattern ended the block at the first note, so the second
#: was left behind when the table moved, and nothing reported it: an orphaned
#: note is still a paragraph, so no count changes.
#:
#: A LEADING FOOTNOTE MARKER is therefore a note too. The set is deliberately
#: small — `*`, `†`, `‡` and the `a)` / `1)` forms — because this pattern
#: decides where a block ENDS, and anything looser starts swallowing prose:
#: the paragraph after таблица 2 opens «Геометрическая форма не является…»
#: and must stay behind.
NOTE = re.compile(
    r"^\s*(?:(?:Примечание|Источник|Note|Source)\b"
    r"|[*†‡]"
    r"|[0-9]{1,2}\)"
    # the class spans BOTH alphabets on purpose: a Russian manuscript
    # letters its notes with Cyrillic, an English one with Latin
    r"|[a-zа-яё]\))", re.IGNORECASE)  # noqa: RUF001

#: A PANEL heading: one caption over several bodies, each introduced by
#: `Panel A.` / `Panel B:`. HCW's Table 9 and AFI's Table A3 are two
#: tables and two of these under one caption, and a walk that read the
#: heading as prose found no body for either. Short label and a
#: separator, so "Panel data allow…" stays prose.
PANEL = re.compile(r"^\s*(?:Panel|Панель)\s+[A-Za-zА-Яа-я0-9]{1,3}[.:)]",  # noqa: RUF001
                   re.IGNORECASE)

#: body-level elements that carry no content of their own: the halves of
#: a bookmark, a comment range, a tracked move, a permission range, and
#: Word's spelling marks. Transparent between a caption and its body.
_END_TAGS = frozenset(W + t for t in (
    "bookmarkEnd", "commentRangeEnd", "moveFromRangeEnd", "moveToRangeEnd",
    "permEnd"))
_OPAQUE_TAGS = frozenset(W + t for t in ("sdt", "customXml"))

# what one body-level element IS, decided once per element
_CAPTION, _BOX, _FRAME, _BODY = "caption", "box", "frame", "body"
_SPACER, _BREAK, _NOTE, _PROSE = "spacer", "break", "note", "prose"
_PANEL, _MARKER, _OPAQUE = "panel", "marker", "opaque"
_TRANSPARENT = frozenset({_SPACER, _NOTE, _PANEL, _MARKER})


@dataclass(frozen=True)
class Exhibit:
    """One captioned exhibit: what it is called, and the body-level span
    that is its own.

    `start`/`stop` are body-child indices, half-open, of `elements`.
    `body_at` is None for a caption with no table or image beside it — a
    numbering defect for `crossrefs` to report, and not a block to move.
    """

    label: str                  # as captioned: "Figure", "Table", "Box"
    number: str                 # "1", "A2", "3.2"
    caption: str                # the caption's visible text, stripped
    kind: str                   # "table" | "figure" | "box"
    start: int
    stop: int
    caption_at: int
    body_at: int | None
    elements: tuple[etree._Element, ...]

    @property
    def name(self) -> str:
        """``Table 3`` — the label as prose spells it."""
        return f"{self.label} {self.number}"

    @property
    def key(self) -> tuple[str, str]:
        return (self.label, self.number)


def text_of(el: etree._Element) -> str:
    """The visible text under `el`, tabs and breaks as whitespace.

    `w:t` alone drops a tab, and a caption set as ``Table 2.<tab>Every
    group`` then reads `Table 2.Every` — which `caption_re` refuses,
    since a caption's separator is followed by a space or the end.
    """
    out: list[str] = []
    for node in el.iter():
        if node.tag == W + "t":
            out.append(node.text or "")
        elif node.tag == W + "tab":
            out.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out)


def _has_picture(el: etree._Element) -> bool:
    return any(el.find(f".//{W}{t}") is not None
               for t in ("drawing", "pict", "object"))


def is_body(el: etree._Element) -> bool:
    """A table, or a paragraph carrying a picture and no words."""
    if el.tag == W + "tbl":
        return True
    return (el.tag == W + "p" and not text_of(el).strip()
            and _has_picture(el))


def _first_cell_text(tbl: etree._Element) -> str:
    cell = tbl.find(f"{W}tr/{W}tc")
    return text_of(cell) if cell is not None else ""


def _classify(el: etree._Element, caption: re.Pattern[str],
              note: re.Pattern[str]) -> tuple[str, re.Match[str] | None]:
    """What this body-level element is, and the caption match if any."""
    if isinstance(el, etree._Comment):
        return _MARKER, None
    if el.tag == W + "tbl":
        return _classify_table(el, caption)
    if el.tag != W + "p":
        return (_OPAQUE if el.tag in _OPAQUE_TAGS else _MARKER), None
    return _classify_paragraph(el, caption, note)


def _classify_table(el: etree._Element, caption: re.Pattern[str],
                    ) -> tuple[str, re.Match[str] | None]:
    """A body, or — captioned in its own first cell — a box or a frame.

    A FRAME is one cell holding nothing but the caption: some papers set
    the caption over an exhibit that way, and it owns a body like a
    paragraph does. A BOX has words of its own under its title and IS
    the exhibit.
    """
    m = caption.match(_first_cell_text(el).strip())
    if m is None:
        return _BODY, None
    cells = el.findall(f".//{W}tc")
    texts = [p for p in el.iter(W + "p") if text_of(p).strip()]
    return (_FRAME if len(cells) == 1 and len(texts) == 1 else _BOX), m


def _classify_paragraph(el: etree._Element, caption: re.Pattern[str],
                        note: re.Pattern[str],
                        ) -> tuple[str, re.Match[str] | None]:
    text = text_of(el).strip()
    m = caption.match(text)
    if m is not None:
        return _CAPTION, m
    if text:
        return (_NOTE if note.match(text) else
                _PANEL if PANEL.match(text) else _PROSE), None
    if _has_picture(el):
        return _BODY, None
    is_break = el.find(f"{W}pPr/{W}sectPr") is not None
    return (_BREAK if is_break else _SPACER), None


def _fits(el: etree._Element, kind: str) -> bool:
    """Can this body element be the body of a caption of `kind`?"""
    if kind == "table":
        return el.tag == W + "tbl"
    return el.tag == W + "p" or _has_picture(el)


def _scan(kids: list[etree._Element], kinds: list[str], i: int,
          step: int, kind: str) -> int | None:
    """The nearest body of `kind` on one side of caption `i`, or None.

    Only what carries nothing may stand between — blank paragraphs,
    notes, markers. Anything else ends the search: prose, another
    caption, a body of the other kind, a section break (an exhibit does
    not reach into the section before its own), a content control.
    """
    j = i + step
    while 0 <= j < len(kids):
        cat = kinds[j]
        if cat in _TRANSPARENT:
            j += step
            continue
        if cat == _BODY and _fits(kids[j], kind):
            return j
        return None
    return None


def _assign(heads: list[int], options: dict[int, list[int]],
            kinds_of: dict[int, str]) -> dict[int, int | None]:
    """Each caption's body, by propagation first and convention second.

    A caption with one free candidate takes it, which can leave another
    caption with one, so the pass repeats until nothing moves. Then the
    document's majority — below or above, per kind, counted over what
    propagation settled — decides the rest, below where there is no
    majority. A caption whose candidates are all taken has no body.
    """
    assigned: dict[int, int | None] = {}
    taken: set[int] = set()
    moved = True
    while moved:
        moved = False
        for i in heads:
            if i in assigned:
                continue
            free = [c for c in options[i] if c not in taken]
            if len(free) == 1:
                assigned[i], moved = free[0], True
                taken.add(free[0])
            elif not free:
                assigned[i] = None
    above: dict[str, int] = {}
    for i, b in assigned.items():
        if b is not None and b != i:
            above[kinds_of[i]] = above.get(kinds_of[i], 0) + (1 if b < i
                                                              else -1)
    for i in heads:
        if i in assigned:
            continue
        free = [c for c in options[i] if c not in taken]
        # the free list holds one body per side, and a caption still here
        # has both: the near one (candidates come below-first) unless
        # the document mostly captions underneath
        pick = free[-1] if above.get(kinds_of[i], 0) > 0 else free[0]
        assigned[i] = pick
        taken.add(pick)
    return assigned


def _leading(kids: list[etree._Element], kinds: list[str], start: int) -> int:
    """Where the span opens: the markers Word hoisted in front of it.

    Word puts a caption's bookmarkStart at body level, before the
    paragraph. Leaving it behind inverts the bookmark — on DSI all twelve
    came back END BEFORE START, and `audit_links` reported nothing,
    because it checks pairing, not order. An END marker in front closes
    something earlier and stays: only from the first START on is the run
    this exhibit's.
    """
    k = start
    while k > 0 and kinds[k - 1] == _MARKER:
        k -= 1
    while k < start and kids[k].tag in _END_TAGS:
        k += 1
    return k


def _trailing(kids: list[etree._Element], kinds: list[str], start: int,
              end: int, kind: str) -> int:
    """One past the span: the notes, blanks and paired markers under it.

    A section-break paragraph looks blank and is absorbed — it is the
    block's own, and the reason `exhibit_block` exists. A BODY is never
    absorbed, whatever it looks like: an image is a paragraph with no
    text, and this is the clause the sixth copy lacked. The one exception
    is a PANEL: a body of the same kind that a panel heading introduces
    is the next panel of this exhibit. An end marker goes with the block
    only when its start is inside the block.
    """
    j = end + 1
    panel = False
    while j < len(kids):
        cat = kinds[j]
        if cat == _PANEL:
            panel = True
        elif cat == _BODY:
            if not (panel and _fits(kids[j], kind)):
                break
            panel = False
        elif (cat not in (_SPACER, _NOTE, _BREAK)
              and not _paired_end(kids, kinds, start, j)):
            break
        j += 1
    return j


def _paired_end(kids: list[etree._Element], kinds: list[str], start: int,
                at: int) -> bool:
    """Is `kids[at]` an end marker whose start lies inside the span?"""
    el = kids[at]
    bid = el.get(W + "id")
    if kinds[at] != _MARKER or el.tag not in _END_TAGS or bid is None:
        return False
    opener = el.tag.replace("End", "Start")
    return any(node.get(W + "id") == bid
               for e in kids[start:at] for node in e.iter(opener))


def exhibits(body: etree._Element, *,
             labels: tuple[str, ...] = DEFAULT_LABELS,
             note: re.Pattern[str] = NOTE) -> list[Exhibit]:
    """Every exhibit in `body`, in document order.

    `labels` are the caption words this paper uses (`--labels` in the
    CLI); a Box is found by where its caption sits, not by its word, so
    naming "Box" is what makes one an exhibit at all.
    """
    kids = list(body)
    pattern = caption_re(labels)
    classified = [_classify(el, pattern, note) for el in kids]
    kinds = [cat for cat, _ in classified]
    heads = [i for i, cat in enumerate(kinds) if cat in (_CAPTION, _FRAME,
                                                          _BOX)]
    kind_of: dict[int, str] = {}
    options: dict[int, list[int]] = {}
    preset: dict[int, int] = {}
    for i in heads:
        m = classified[i][1]
        assert m is not None
        if kinds[i] == _BOX:
            kind_of[i], preset[i] = "box", i
        elif kinds[i] == _CAPTION and _has_picture(kids[i]):
            kind_of[i], preset[i] = "figure", i
        else:
            kind_of[i] = "table" if m.group(1) in TABLE_LABELS else "figure"
            options[i] = [c for c in (_scan(kids, kinds, i, +1, kind_of[i]),
                                      _scan(kids, kinds, i, -1, kind_of[i]))
                          if c is not None]
    bodies = _assign([i for i in heads if i not in preset], options, kind_of)
    bodies.update(preset)
    return _spans(kids, kinds, classified, heads=heads, bodies=bodies,
                  kind_of=kind_of)


def _spans(kids: list[etree._Element], kinds: list[str],
           classified: list[tuple[str, re.Match[str] | None]], *,
           heads: list[int], bodies: dict[int, int | None],
           kind_of: dict[int, str]) -> list[Exhibit]:
    """The spans, and a caption with no body gets only itself.

    Two spans cannot share an element; if the walks ever meet, the
    later exhibit keeps what is in front of its caption.
    """
    spans: list[tuple[int, int, int]] = []          # (start, stop, head)
    for i in heads:
        b = bodies.get(i)
        if b is None:
            spans.append((i, i + 1, i))
            continue
        start = _leading(kids, kinds, min(i, b))
        stop = _trailing(kids, kinds, start, max(i, b), kind_of[i])
        spans.append((start, stop, i))
    spans.sort()
    out: list[Exhibit] = []
    for n, (start, walked, i) in enumerate(spans):
        stop = min(walked, spans[n + 1][0]) if n + 1 < len(spans) else walked
        m = classified[i][1]
        assert m is not None
        out.append(Exhibit(
            label=m.group(1), number=m.group(2),
            caption=text_of(kids[i]).strip() if kinds[i] != _BOX
            else _first_cell_text(kids[i]).strip(),
            kind=kind_of[i], start=start, stop=stop, caption_at=i,
            body_at=bodies.get(i), elements=tuple(kids[start:stop])))
    return out


def mention_of(body: etree._Element, exhibit: Exhibit) -> int | None:
    """The body-child index of the first element that mentions `exhibit`
    from outside its own span, or None.

    A paragraph or a table — a mention inside a box's text is still where
    the reader met the exhibit. "Figures 1 and 2 show" mentions Figure 2
    as much as "Figure 2 shows" does, so the range form counts too.
    """
    plain = mention_re(exhibit.label, exhibit.number)
    ranged = continuation_re(exhibit.label, exhibit.number)
    for i, el in enumerate(body):
        if exhibit.start <= i < exhibit.stop or el.tag not in (W + "p",
                                                               W + "tbl"):
            continue
        text = text_of(el)
        if plain.search(text) or ranged.search(text):
            return i
    return None
