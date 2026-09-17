"""A manuscript frozen as text, and a protocol's anchors resolved on it.

Two things every protocol round needs before its first edit, and every
round wrote again: DSI kept ``snapshot_t6.py`` and ``anchor_index_t6.py``
from 2026-09-07, then wrote ``snapshot_unfpa.py`` and
``anchor_index_unfpa.py`` on 2026-09-16 — the same two scripts with the
round's name in them (BACKLOG S4). What each is FOR:

* :func:`snapshot` — the state a round starts from, as a dump a text diff
  can read (``[P31]`` a body paragraph, ``[T4:2,3]`` a table cell, one
  :data:`MATH` per equation) and a structure record a count gate can read
  (paragraphs, tables, equations, notes; bookmark names and link targets
  in every form, per part). ``accepted=True`` freezes the view the
  tracked gates simulate, and ``insertions`` keeps a post-batch dump in
  the BASELINE's numbering, so the diff is the batch and not every label
  after its first new paragraph.
* :func:`resolve` — does each anchor a protocol quotes occur exactly once,
  inside the paragraph it names; and what does its span meet there — the
  equations, the links, a LABEL it crosses — a link's or a field's result,
  which :func:`docxkit.edit.replace_in_para` refuses — the run formats, the
  trailing whitespace. A protocol states anchors as :class:`Anchor`
  lines, :func:`parse_spec` reads a file of them.

**The numbering is the package's.** ``P<n>`` is the n-th body paragraph
:func:`docxkit.find.body_elements` walks — every ``¶n`` docxkit prints
counts the same way — so an EMPTY paragraph Word wrote self-closing,
``<w:p …/>``, is not numbered. It is counted in the structure record
(``empty_paragraphs``), because that is the number to reconcile with a
paragraph count taken in Word.

`find.site` answers the anchor question for one signature in one part,
first match described; this answers it for a protocol's whole list, in
every part a reader sees, against the scope each one names.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from ._xml import (
    BOOKMARK_NAME_RE,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    HYPERLINK_ANY_RE,
    INSTR_ANCHOR_RE,
    PARA_RE,
    element_spans,
    fields,
    internal_links,
    live_properties,
    normalize_glyphs,
    overlaps,
    own_properties,
    printed_text,
    ref_anchor,
    run_spans,
    visible_text,
)
from .edit import _label_spans_in, _run_walk
from .equations import OMATH_RE
from .errors import AnchorError
from .find import body_elements, table_index_at
from .footnotes import find_all as _notes

__all__ = [
    "KINDS",
    "MATH",
    "TABLE",
    "Anchor",
    "AnchorError",
    "Resolution",
    "Snapshot",
    "parse_anchor",
    "parse_spec",
    "read_spec",
    "resolve",
    "snapshot",
]

#: What an equation reads as in the dump. One per ``m:oMath``: an
#: equation's glyphs come from the Mathematical Alphanumeric block and
#: diff as noise, while "an equation was here, and still is" is the fact.
MATH = "⟦MATH⟧"
#: What a table NESTED inside a cell reads as. Its own cells are not
#: numbered — ``T<k>`` counts the tables a reader indexes, the top-level
#: ones — so the cell says that there is one rather than flattening it.
TABLE = "⟦TABLE⟧"

#: What a protocol asks of an anchor, and what OK means for each:
#:
#: ``replace``       exactly once document-wide, and that once in scope
#: ``append``        a paragraph in scope ENDS with it (trailing
#:                   whitespace excepted), and it is once document-wide
#: ``insert_after``  the same test as ``append`` — a new paragraph goes
#:                   after the one that ends with it
#: ``present``       the scope holds it at all
KINDS = ("replace", "append", "insert_after", "present")

#: A scope: ``P31`` (a body paragraph; ``P31a`` under insertions),
#: ``T4`` (a table) or ``T4:2,3`` (row 2, cell 3), ``FN3`` / ``EN2`` (a
#: note by id), or ``*`` (the whole document).
_SCOPE_RE = re.compile(r"\*|P\d+[a-z]*|T\d+(?::\d+,\d+)?|FN\d+|EN\d+")

#: What the dump prints beside ``w:t``: a tab CHARACTER, and nothing else
#: `printed_text` knows — a protocol copies its anchors out of this
#: reading and they are matched against `visible_text`, so a no-break
#: hyphen or a line break here would be a character no anchor can hold.
#: `printed_text` is also what tells a tab character from a tab STOP.
_DUMP_CHILDREN = {"tab": "\t"}
#: A body paragraph Word wrote EMPTY. `PARA_RE` cannot see one, which is
#: what keeps the package's paragraph numbering stable; counted apart.
_EMPTY_PARA_RE = re.compile(r"<w:p\b[^>]*/>")
#: The target of an internal link ELEMENT, read off its open tag.
_ANCHOR_ATTR_RE = re.compile(r'\bw:anchor="([^"]*)"')

_PARTS = (("body", DOCUMENT), ("footnotes", FOOTNOTES),
          ("endnotes", ENDNOTES))
_NOTE_KIND = {FOOTNOTES: ("footnote", "FN"), ENDNOTES: ("endnote", "EN")}


# ------------------------------------------------------------------ reading


def _prose(xml: str) -> str:
    """The text of `xml`: ``w:t``, and a tab character as ``\\t``."""
    return printed_text(xml, printing=_DUMP_CHILDREN)


def _reading(para_xml: str) -> str:
    """A paragraph as the dump prints it: prose, and :data:`MATH` per
    equation in place."""
    out, pos = [], 0
    for m in OMATH_RE.finditer(para_xml):
        out += [_prose(para_xml[pos:m.start()]), MATH]
        pos = m.end()
    out.append(_prose(para_xml[pos:]))
    return "".join(out)


class _Place(NamedTuple):
    """One paragraph a reader sees, and the label that addresses it."""

    label: str      # P31, P31a, T4:2,3, FN3, EN2
    xml: str


def _letters(n: int) -> str:
    """0 -> a, 25 -> z, 26 -> aa: the suffix of the n-th insertion."""
    out = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


def _labels(count: int, insertions: Sequence[int]) -> list[str]:
    """``P<n>`` for `count` body paragraphs, in BASELINE numbering.

    `insertions` lists, for every paragraph a batch inserted, the
    baseline paragraph it was inserted AFTER — ``0`` for before the first
    — in any order; a number given twice is two paragraphs inserted
    there, labelled ``a`` then ``b``. A paragraph is read as inserted
    exactly when the last baseline paragraph seen still has insertions
    owed: the batch's paragraphs follow the one they were put after.
    """
    for n in insertions:
        if n < 0:
            raise AnchorError(
                f"insertion after baseline ¶{n}: a paragraph is inserted "
                f"after ¶0 (before the first) or a later one")
    owed = Counter(insertions)
    out: list[str] = []
    baseline, used = 0, 0
    for _ in range(count):
        if used < owed[baseline]:
            out.append(f"P{baseline}{_letters(used)}")
            used += 1
        else:
            baseline, used = baseline + 1, 0
            out.append(f"P{baseline}")
    if used < owed[baseline] or any(n > baseline for n in owed):
        late = sorted(n for n in owed.elements() if n >= baseline)
        raise AnchorError(
            f"--insertions names a paragraph inserted after baseline "
            f"¶{late[-1]}, and this document runs out at baseline "
            f"¶{baseline} with {count} paragraphs in all. The list "
            f"describes another file, or counts a paragraph this walk "
            f"does not number (an empty one Word wrote as <w:p/>).")
    return out


def _cells(table_xml: str, k: int) -> Iterator[tuple[str, str]]:
    """``(T<k>:r,c, cell xml)`` for every cell of a top-level table."""
    for r, (rs, re_) in enumerate(element_spans(table_xml, "tr"), 1):
        tr = table_xml[rs:re_]
        for c, (cs, ce) in enumerate(element_spans(tr, "tc"), 1):
            yield f"T{k}:{r},{c}", tr[cs:ce]


def _walk(parts: Mapping[str, bytes], insertions: Sequence[int]
          ) -> tuple[list[str], list[str], list[_Place], dict[str, Any]]:
    """The dump, the notes dump, every paragraph by label, and the counts."""
    xml = parts[DOCUMENT].decode("utf-8") if DOCUMENT in parts else ""
    elements = body_elements(xml)
    labels = iter(_labels(sum(kind == "p" for kind, _s, _e in elements),
                          insertions))
    lines: list[str] = []
    places: list[_Place] = []
    tables = [(s, e) for kind, s, e in elements if kind == "tbl"]
    for kind, s, e in elements:
        chunk = xml[s:e]
        if kind == "p":
            label = next(labels)
            lines.append(f"[{label}] {_reading(chunk)}")
            places.append(_Place(label, chunk))
            continue
        k = tables.index((s, e)) + 1
        lines.append(f"[T{k}]")
        for label, cell in _cells(chunk, k):
            said = []
            for ckind, cs, ce in body_elements(cell):
                said.append(TABLE if ckind == "tbl"
                            else _reading(cell[cs:ce]))
            lines.append(f"[{label}] {' | '.join(said)}")
            places += [_Place(label, m.group(0))
                       for m in PARA_RE.finditer(cell)]

    note_lines: list[str] = []
    structure: dict[str, Any] = {
        "body": {"paragraphs": len(elements) - len(tables),
                 "empty_paragraphs": sum(
                     table_index_at(tables, m.start()) is None
                     for m in _EMPTY_PARA_RE.finditer(xml)),
                 "tables": len(tables), **_record(xml)}}
    for name, part in _PARTS[1:]:
        notes_xml = parts[part].decode("utf-8") if part in parts else ""
        kind, prefix = _NOTE_KIND[part]
        held = 0
        for n in _notes(notes_xml, kind=kind):
            paras = [m.group(0) for m in PARA_RE.finditer(n.xml)]
            text = " | ".join(_reading(p).strip() for p in paras).strip()
            places += [_Place(f"{prefix}{n.id}", p) for p in paras]
            if text:
                held += 1
                note_lines.append(f"[{prefix}{n.id}] {text}")
        structure[name] = {"notes": held, **_record(notes_xml)}
    return lines, note_lines, places, structure


def _record(xml: str) -> dict[str, Any]:
    """Equations, bookmark names and link targets in every FORM, one part.

    Form by form because Word turns a field-form link into an element
    when the author saves — the churn a before/after record exists to
    show. `_xml.field_anchors` reads both field forms as one list and
    `internal_links` both forms as one; neither says which a target was
    in, so the fields are walked here — through `_xml.fields`, which
    pairs their markers by DEPTH. That walk was written here, because
    this was the only reader that needed a nested field's own
    instruction; it now lives beside the readers that turned out to
    need it too.
    """
    elements: Counter[str] = Counter()
    for m in HYPERLINK_ANY_RE.finditer(xml):
        head = m.group(0)[:m.group(0).index(">")]
        if (a := _ANCHOR_ATTR_RE.search(head)) is not None:
            elements[html.unescape(a.group(1))] += 1

    hyperlinks: Counter[str] = Counter()
    refs: Counter[str] = Counter()

    def classify(instr: str) -> None:
        if (h := INSTR_ANCHOR_RE.search(instr)) is not None:
            hyperlinks[h.group(1)] += 1
        elif (target := ref_anchor(instr)) is not None:
            refs[target] += 1

    # Every field, its own instruction, nested ones included — and a
    # stray instruction on its own, which is a field an edit cut the
    # `begin` off and still names the bookmark it depends on.
    for f in fields(xml):
        classify(f.instr)

    return {"oMath": len(OMATH_RE.findall(xml)),
            "bookmarks": sorted(BOOKMARK_NAME_RE.findall(xml)),
            "hyperlink_fields": dict(sorted(hyperlinks.items())),
            "hyperlink_elements": dict(sorted(elements.items())),
            "ref_fields": dict(sorted(refs.items()))}


# ----------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class Snapshot:
    """A manuscript frozen as text: what :func:`snapshot` returns."""

    lines: tuple[str, ...]
    """The body in document order: ``[P<n>]``, ``[T<k>]``, ``[T<k>:r,c]``."""
    notes: tuple[str, ...]
    """Every note with something in it: ``[FN<id>]``, ``[EN<id>]``."""
    structure: Mapping[str, Any] = field(default_factory=dict)
    """The counts and the targets, per part — see :func:`snapshot`."""

    def write(self, stem: str | Path) -> tuple[Path, Path, Path]:
        """``<stem>.txt``, ``<stem>_notes.txt``, ``<stem>_structure.json``.

        The suffixes are APPENDED to the stem's name, never swapped for
        its suffix: `with_suffix` makes ``round.v2`` into ``round.txt``.
        """
        stem = Path(stem)
        stem.parent.mkdir(parents=True, exist_ok=True)
        out = (stem.with_name(stem.name + ".txt"),
               stem.with_name(stem.name + "_notes.txt"),
               stem.with_name(stem.name + "_structure.json"))
        out[0].write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        out[1].write_text("\n".join(self.notes) + "\n", encoding="utf-8")
        out[2].write_text(json.dumps(self.structure, ensure_ascii=False,
                                     indent=1), encoding="utf-8")
        return out


def snapshot(parts: Mapping[str, bytes], *, accepted: bool = False,
             insertions: Sequence[int] = ()) -> Snapshot:
    """Freeze `parts` as text and structure. Reads; changes nothing.

    `accepted` reads the view :mod:`docxkit.tracked` simulates for its
    gates — every revision accepted in every text part, and the shells
    that leaves of a deleted note pruned — rather than the markup as it
    stands, where inserted text reads as present and deleted text as
    gone but a row flagged deleted is still a row.

    `insertions` numbers the body in BASELINE numbering: see
    :func:`_labels` for how the list is read. Tables are numbered as they
    stand; a batch that inserts a TABLE shifts every ``T<k>`` after it.

    ``structure`` holds ``view``, ``insertions``, and one entry per part
    — ``body``, ``footnotes``, ``endnotes``, each present whether or not
    the package has that part, so two records diff key for key: the
    body's ``paragraphs`` (numbered), ``empty_paragraphs`` (not) and
    ``tables``; each notes part's ``notes`` with something in them; and
    in all three ``oMath``, ``bookmarks``, and the internal link targets
    by form — ``hyperlink_fields`` (``HYPERLINK \\l``), ``ref_fields``
    (``REF … \\h``, Word's own cross-reference) and
    ``hyperlink_elements`` (``w:hyperlink w:anchor``), each a count per
    target.
    """
    view = dict(parts)
    if accepted:
        from .revisions import accept
        from .tracked import _simulate
        view = _simulate(view, accept)
    lines, note_lines, _places, structure = _walk(view, insertions)
    return Snapshot(tuple(lines), tuple(note_lines),
                    {"view": "accepted" if accepted else "stored",
                     "insertions": sorted(insertions), **structure})


# ------------------------------------------------------------------ anchors


@dataclass(frozen=True)
class Anchor:
    """One anchor a protocol quotes: where, what for, and the words."""

    scope: str
    kind: str
    text: str
    name: str = ""
    """The protocol's own id for the step (``T1.2``), when it has one."""


@dataclass(frozen=True)
class Resolution:
    """Where one anchor resolved, the verdict, and what its span meets."""

    anchor: Anchor
    ok: bool
    reason: str
    """Empty when OK; otherwise why not, naming the places."""
    where: tuple[tuple[str, int], ...]
    """Every place it occurs, and how many times there."""
    in_scope: int
    total: int
    target: str
    """The paragraph measured below: the one in scope holding it, or the
    scope's first when none does; empty when the scope names nothing."""
    math: int
    links: tuple[str, ...]
    """The targets of the internal links in the target paragraph."""
    crossing: tuple[str, ...]
    """Each LABEL the anchor's span overlaps, whole: a link's, or a
    field's result — what `replace_in_para` refuses to write across."""
    formats: int
    """Distinct run properties across the span."""
    trailing: str
    """The target paragraph's trailing whitespace."""

    def format(self) -> str:
        """The verdict line, and a line of what the span meets if any."""
        a = self.anchor
        head = (f"{'OK' if self.ok else 'STOP':<5} "
                f"{a.name + '  ' if a.name else ''}{a.kind:<13} {a.scope}"
                f"  ·  in scope {self.in_scope}, document {self.total}"
                + (f"  ·  {self.reason}" if self.reason else ""))
        facts = [f"math {self.math}"] if self.math else []
        if self.links:
            facts.append("links " + ", ".join(self.links))
        if self.crossing:
            facts.append("crossing " + ", ".join(f"«{c}»"
                                                 for c in self.crossing))
        if self.formats:
            facts.append(f"formats {self.formats}")
        if self.trailing:
            facts.append(f"trailing {self.trailing!r}")
        return head + ("\n      " + " · ".join(facts) if facts else "")


def _in_scope(label: str, scope: str) -> bool:
    """``T4`` holds ``T4:2,3``; ``P3`` does not hold ``P31``."""
    return scope in ("*", label) or label.startswith(scope + ":")


def _spread(where: Iterable[tuple[str, int]]) -> str:
    return ", ".join(label + (f" ×{n}" if n > 1 else "")
                     for label, n in where)


def _span_facts(xml: str, span: tuple[int, int]
                ) -> tuple[tuple[str, ...], int]:
    """The labels a span crosses, and how many run formats it covers.

    The question is whether `replace_in_para` will refuse, so a label is
    ITS label — :func:`docxkit.edit._label_spans_in`, read here and not
    restated: a link's text styled or not, a field's result (Word's own
    ``REF … \\h`` styles none), and two links side by side kept two. The
    copy this held until 2026-09-17 knew the style and the element only,
    and joined any label runs that touched: an anchor across an unstyled
    cross-reference read ``crossing ()`` and the edit refused it, and two
    citations with only a tracked deletion of "; " between them crossed
    one label, «Sen 1999Deaton 2013», that no link has.

    Edit groups the runs in EDITABLE offsets and the anchor was found at
    the READER's (:func:`docxkit._xml.run_spans`), which also count the
    maths. Both walks number the same `RUN_RE` runs, so each label is
    measured back from its first run and its last.
    """
    runs, spans, _end = run_spans(xml)
    formats: set[str] = set()
    for run, (s, e) in zip(runs, spans, strict=True):
        if e <= s:
            continue
        if overlaps((s, e), span):
            own = own_properties(run.group(0), "rPr")
            formats.add(" ".join(live_properties(own[2]).split())
                        if own else "")
    labels = [(spans[label.first][0], spans[label.last][1])
              for label in _label_spans_in(xml, *_run_walk(xml))]
    text = visible_text(xml)
    crossing = tuple(text[s:e] for s, e in labels if overlaps((s, e), span))
    return crossing, len(formats)


def resolve(parts: Mapping[str, bytes], anchors: Iterable[Anchor], *,
            normalize: bool = False,
            insertions: Sequence[int] = ()) -> list[Resolution]:
    """Resolve each anchor over the body, the table cells and the notes.

    Found in the READER's text (:func:`docxkit._xml.visible_text`), which
    is what `para_slice` and `docxkit text` show — so an anchor spanning
    an equation is found here and refused by `replace_in_para`, and the
    ``math`` count is what says so. `normalize` folds Word's glyph
    substitutions on both sides first (curly quotes, dashes), as
    ``para_slice(normalize=True)`` does. `insertions` addresses paragraphs
    in baseline numbering, as :func:`snapshot` labels them.
    """
    _lines, _notes_dump, places, _structure = _walk(parts, insertions)
    fold = normalize_glyphs if normalize else (lambda s: s)
    texts = [fold(visible_text(p.xml)) for p in places]
    return [_resolve_one(a, places, texts, fold(a.text)) for a in anchors]


def _resolve_one(anchor: Anchor, places: list[_Place], texts: list[str],
                 needle: str) -> Resolution:
    where: dict[str, int] = {}
    in_scope, target, span = 0, -1, None
    scoped = [i for i, p in enumerate(places)
              if _in_scope(p.label, anchor.scope)]
    ending = anchor.kind in ("append", "insert_after")
    for place, text in zip(places, texts, strict=True):
        if n := text.count(needle):
            where[place.label] = where.get(place.label, 0) + n
    for i in scoped:
        text = texts[i]
        in_scope += text.count(needle)
        if ending:
            at = (len(text.rstrip()) - len(needle)
                  if text.rstrip().endswith(needle) else -1)
        else:
            at = text.find(needle)
        if at >= 0 and span is None:
            target, span = i, (at, at + len(needle))
    if target < 0 and scoped:
        target = scoped[0]
    total = sum(where.values())

    reason = ""
    if not scoped:
        reason = f"{anchor.scope} names nothing in this document"
    elif not total:
        reason = "not found"
    elif not in_scope:
        reason = f"not in {anchor.scope}: it is in {_spread(where.items())}"
    elif ending and span is None:
        reason = f"{anchor.scope} does not END with it"
    elif total > 1 and anchor.kind != "present":
        reason = f"occurs {total} times: {_spread(where.items())}"

    crossing: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    formats, math, trailing = 0, 0, ""
    if target >= 0:
        xml, text = places[target].xml, texts[target]
        if span is not None:
            crossing, formats = _span_facts(xml, span)
        math = len(OMATH_RE.findall(xml))
        links = tuple(a for a, _label in internal_links(xml))
        trailing = text[len(text.rstrip()):]
    return Resolution(
        anchor=anchor, ok=not reason, reason=reason,
        where=tuple(where.items()), in_scope=in_scope, total=total,
        target=places[target].label if target >= 0 else "", math=math,
        links=links, crossing=crossing, formats=formats, trailing=trailing)


# --------------------------------------------------------------- the spec


def _anchor(scope: str, kind: str, text: str, name: str, where: str
            ) -> Anchor:
    if not _SCOPE_RE.fullmatch(scope):
        raise AnchorError(
            f"{where}: {scope!r} is not a scope — P31, P31a, T4, T4:2,3, "
            f"FN3, EN2 or *")
    if kind not in KINDS:
        raise AnchorError(
            f"{where}: {kind!r} is not one of {', '.join(KINDS)}")
    if not text:
        raise AnchorError(f"{where}: the anchor text is empty")
    return Anchor(scope, kind, text, name=name)


def parse_spec(text: str) -> list[Anchor]:
    """Anchors from a spec: one per line, TAB-separated.

    ``scope<TAB>kind<TAB>anchor``, or with the protocol's step id first,
    ``name<TAB>scope<TAB>kind<TAB>anchor``. Blank lines and lines starting
    with ``#`` are skipped. The anchor is the rest of the line exactly as
    written — tabs, and leading and trailing spaces, included — because
    an anchor is matched byte for byte; only the line ending goes.

    Tab-separated rather than a protocol's own grammar: DSI's are
    markdown with «…» quotes and ¶ references, the next paper's will not
    be, and the three columns are what every one of them reduces to.
    """
    out: list[Anchor] = []
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.removesuffix("\r")
        if not line.strip() or line.startswith("#"):
            continue
        # A kind in the SECOND column is the three-column form: in the
        # four-column one that column is a scope, and no scope is a kind.
        cols = line.split("\t", 2)
        if len(cols) == 3 and cols[1] in KINDS:
            out.append(_anchor(cols[0], cols[1], cols[2], "", f"line {n}"))
            continue
        cols = line.split("\t", 3)
        if len(cols) != 4:
            raise AnchorError(
                f"line {n}: want scope<TAB>kind<TAB>anchor, optionally with "
                f"a name first — got {line[:60]!r}")
        out.append(_anchor(cols[1], cols[2], cols[3], cols[0], f"line {n}"))
    return out


def read_spec(path: str | Path) -> list[Anchor]:
    """:func:`parse_spec` on a UTF-8 file."""
    return parse_spec(Path(path).read_text(encoding="utf-8"))


def parse_anchor(text: str) -> Anchor:
    """One anchor as a command line writes it: ``[kind@]scope=anchor``.

    The kind defaults to ``replace``, the strictest. Split at the FIRST
    ``=``: no scope or kind holds one, and an anchor may.
    """
    head, eq, words = text.partition("=")
    if not eq:
        raise AnchorError(f"{text[:60]!r}: want [kind@]scope=anchor")
    kind, at, scope = head.rpartition("@")
    return _anchor(scope, kind if at else "replace", words, "",
                   repr(text[:60]))
