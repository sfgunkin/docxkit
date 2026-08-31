r"""Footnotes: locating them, editing them, and surviving Word's renumbering.

Twenty-four files across the papers touch footnotes. Two things make it
awkward, and both are encoded here:

* **Word renumbers footnote ids on save.** An author's paragraph spliced
  raw carries ids that mean a different note in the build, so a splice
  silently repoints the reference. :func:`remap` matches by definition
  TEXT instead.
* **A footnote is a block container.** Its content lives in ``w:p``
  children; putting a run directly inside ``w:footnote`` makes Word
  reject the part — which is why :mod:`docxkit.lint` checks for it.

Ids 0 and -1 are the separator and continuation notes Word keeps in every
document, not real footnotes; :func:`find_all` skips them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NamedTuple

from ._xml import (
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    NOTE_REF_RE,
    PARA_RE,
    RUN_RE,
    escape,
    escape_attr,
    live_properties,
    own_properties,
    set_run_property,
    span_holding,
    visible_text,
)
from .edit import insert_in_para
from .errors import AnchorError
from .find import para_slice
from .styles import STYLE as _STYLE
from .styles import Cascade

__all__ = [
    "AnchorError",
    "FontReport",
    "Footnote",
    "Orphan",
    "SizeOutlier",
    "SizeReport",
    "add",
    "append",
    "find",
    "find_all",
    "fonts",
    "orphans",
    "out_of_order",
    "prune_orphans",
    "remap",
    "renumber_map",
    "set_font",
    "sizes",
]

_FOOTNOTE_RE = re.compile(r'<w:footnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)'
                          r"</w:footnote>", re.DOTALL)
_ENDNOTE_RE = re.compile(r'<w:endnote\b[^>]*w:id="(-?\d+)"[^>]*>(.*?)'
                         r"</w:endnote>", re.DOTALL)
#: An endnote is a footnote at the back of the paper: same element shape,
#: same reserved ids, same reason a lost one is invisible. A check that
#: covered only the footnotes would be a gate that cannot fail for any
#: paper that uses the other kind.
_NOTE_RE = {"footnote": _FOOTNOTE_RE, "endnote": _ENDNOTE_RE}
_REFERENCE_RE = re.compile(r'(w:footnoteReference\b[^>]*?w:id=")(-?\d+)(")')
# Word's own separator/continuation notes, present in every document
_RESERVED_IDS = {"0", "-1"}


class Footnote:
    """One footnote: its id, its text, and where it sits in the part."""

    __slots__ = ("end", "id", "start", "text", "xml")

    def __init__(self, id: str, xml: str, start: int, end: int) -> None:
        self.id = id
        self.xml = xml
        self.start = start
        self.end = end
        self.text = visible_text(xml).strip()

    def __repr__(self) -> str:
        return f"Footnote(id={self.id!r}, text={self.text[:40]!r})"


def find_all(footnotes_xml: str, *, include_reserved: bool = False,
             kind: str = "footnote") -> list[Footnote]:
    """Every real footnote, Word's separator notes excluded.

    `kind` reads ``word/endnotes.xml`` instead — the same element shape
    under a different name, and the caller that must not stop at the
    footnotes is the hand-back gate.
    """
    out = []
    for m in _NOTE_RE[kind].finditer(footnotes_xml):
        if not include_reserved and m.group(1) in _RESERVED_IDS:
            continue
        out.append(Footnote(m.group(1), m.group(0), m.start(), m.end()))
    return out


#: Both kinds, keyed the way `find_all` keys them. The expressions
#: themselves live in `_xml`: this module and `export` had a copy
#: each, and a third was about to be written in `find`.
_REFERENCE_OF = NOTE_REF_RE


def out_of_order(document_xml: str, notes_xml: str, *,
                 kind: str = "footnote") -> list[str]:
    """Ids whose DEFINITION sits out of reference order, in that order.

    Word numbers notes by where their REFERENCES are and stores the
    definitions in whatever order the file happens to hold them — so a
    note appended to the end of ``footnotes.xml`` with its reference in
    the middle of the body renders perfectly, and every read-only gate
    passes: the render, the counts, the text.

    Word's Compare then rewrites the definitions INTO document order,
    so the redline's part no longer lines up with the baseline's and
    the whole thing reads as moved. On AFI that was 81 glyph runs and a
    structure count for a one-line prose batch, reported against the
    innocent batch that came after it (backlog, 2026-08-20).

    Answers the ids that would MOVE — every one of them, not the
    smallest set that could be reordered — so a caller can name them.
    Definitions nothing references and references with no definition are
    not this question and are left out of it.
    """
    seen: list[str] = []
    for note in _REFERENCE_OF[kind].findall(document_xml):
        if note not in _RESERVED_IDS and note not in seen:
            seen.append(note)
    defined = [f.id for f in find_all(notes_xml, kind=kind)]
    wanted = [i for i in seen if i in set(defined)]
    have = [i for i in defined if i in set(wanted)]
    return [i for i, j in zip(have, wanted, strict=True) if i != j]


#: What makes a definition worth keeping when nothing references it.
#: Text is the obvious one; the rest are carriers with no text of their
#: own, and dropping a definition that holds one silently loses an
#: anchor a link still points at. `w:footnoteRef` is deliberately not
#: here — it is the mark Word puts at the head of EVERY definition, so
#: counting it would make every note look occupied.
_NOTE_CONTENT_RE = re.compile(
    r"<(?:w:bookmarkStart|w:hyperlink|w:drawing|w:tbl|m:oMath)\b")


@dataclass(frozen=True)
class Orphan:
    """A note DEFINITION nothing in the package references."""

    kind: str               # "footnote" or "endnote"
    id: str
    text: str               # what the definition says, "" for a shell
    carriers: int           # bookmarks, links, drawings, tables, equations

    @property
    def empty(self) -> bool:
        """A shell: nothing a reader could see, and nothing to lose."""
        return not self.text and not self.carriers

    def __str__(self) -> str:
        what = "empty" if self.empty else f"holds {self.text[:50]!r}"
        return f"{self.kind} {self.id} ({what})"


def orphans(parts: dict[str, bytes], *,
            kind: str | None = None) -> list[Orphan]:
    """Note definitions no reference in the package points at.

    Word represents a DELETED footnote the only way it can: the
    reference run goes inside a ``w:del`` and the definition's text
    becomes ``w:delText``. Accepting that in Word removes the definition
    too — Word knows the two are one object. An XML accept does not:
    :func:`docxkit.revisions.accept` works one part at a time, empties
    the note, and leaves the shell behind, so the accepted view has one
    footnote more than the document it is meant to reproduce and the
    paragraph gate reports ``'' vs ''`` — two empty strings that look
    identical (Aging_Well, 2026-08-31).

    Every part is searched for references, not just the body: a header
    can carry one, and a definition pruned because the body had gone
    quiet about it would take a note the page still shows.

    Ids 0 and -1 are Word's separator and continuation notes. Nothing
    ever references those and they are not orphans.
    """
    out: list[Orphan] = []
    for k in ((kind,) if kind else ("footnote", "endnote")):
        part = FOOTNOTES if k == "footnote" else ENDNOTES
        blob = parts.get(part)
        if not blob:
            continue
        referenced = {
            i for name, xml in parts.items()
            if name != part and name.endswith(".xml")
            for i in _REFERENCE_OF[k].findall(xml.decode("utf-8"))}
        out += [Orphan(k, note.id, note.text,
                       len(_NOTE_CONTENT_RE.findall(note.xml)))
                for note in find_all(blob.decode("utf-8"), kind=k)
                if note.id not in referenced]
    return out


def prune_orphans(parts: dict[str, bytes]) -> list[Orphan]:
    """Drop the EMPTY orphan definitions, in place. Returns what went.

    Only the shells. An unreferenced definition with words in it is a
    footnote that lost its marker — a real loss, and the caller's to
    report — while a shell is an artifact of accepting or rejecting part
    by part and says nothing about the manuscript. Read the ones left
    behind with :func:`orphans`.
    """
    gone: list[Orphan] = []
    for orphan in orphans(parts):
        if not orphan.empty:
            continue
        part = FOOTNOTES if orphan.kind == "footnote" else ENDNOTES
        xml = parts[part].decode("utf-8")
        for note in find_all(xml, kind=orphan.kind):
            if note.id == orphan.id:
                xml = xml[:note.start] + xml[note.end:]
                parts[part] = xml.encode("utf-8")
                gone.append(orphan)
                break
    return gone


#: The reference run Word writes, and the definition's opening run.
_REF_RUN = ('<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            '<w:footnoteReference w:id="{id}"/></w:r>')
_DEF = ('<w:footnote w:id="{id}"><w:p><w:pPr>'
        '<w:pStyle w:val="FootnoteText"/></w:pPr><w:r><w:rPr>'
        '<w:rStyle w:val="FootnoteReference"/></w:rPr><w:footnoteRef/>'
        '</w:r><w:r><w:t xml:space="preserve"> {text}</w:t></w:r>'
        "</w:p></w:footnote>")


def add(parts: dict[str, bytes], *, after: str, text: str) -> str:
    """Create a footnote and its reference AS A PAIR. Returns the id.

    `after` is visible text in the body; the reference goes immediately
    behind it, in the one paragraph that contains it.

    The definition is written in REFERENCE order rather than appended,
    which is the whole reason this exists. Appending is what a paper
    hand-rolled, and it costs a batch: the file renders correctly and
    passes every read-only gate, then Word's Compare rewrites the
    definitions into document order and the next redline reads the
    whole part as moved (see :func:`out_of_order`).

    The id is one past the highest the part already holds — not the
    count of notes, which repeats an id after a deletion, and not a
    reused free one, because `commentsExtended`-style parts elsewhere
    key on ids and a reused id inherits whatever they still say.

    Mutates `parts`; needs `word/footnotes.xml` to exist, which it does
    in any document Word has ever put a note in.
    """
    if FOOTNOTES not in parts:
        raise AnchorError(
            "no word/footnotes.xml: this package has never held a footnote, "
            "and the scaffold Word writes for one is not built here. Add a "
            "note in Word once, or copy the part from a document that has "
            "them.")
    doc = parts[DOCUMENT].decode("utf-8")
    notes_xml = parts[FOOTNOTES].decode("utf-8")

    start, end = para_slice(doc, after)
    para = doc[start:end]
    at = visible_text(para).index(after) + len(after)

    # One past the highest, and never below 1: Word's separator notes
    # are -1 and 0, so a part that holds only those would otherwise hand
    # back an id the document reserves — and a reference to 0 renders as
    # the separator line.
    used = {int(f.id) for f in find_all(notes_xml, include_reserved=True)}
    new_id = str(max({*used, 0}) + 1)

    para = insert_in_para(para, at, _REF_RUN.format(id=new_id))
    doc = doc[:start] + para + doc[end:]

    # WHERE the definition goes: right after the definition of the note
    # whose reference now precedes this one. That keeps the part in
    # reference order by construction, which is what `out_of_order`
    # measures and what Compare would otherwise impose.
    order = [i for i in _REFERENCE_OF["footnote"].findall(doc)
             if i not in _RESERVED_IDS]
    before = order[order.index(new_id) - 1] if order.index(new_id) else None
    body = _DEF.format(id=new_id, text=escape(text))
    if before is None:
        first = find_all(notes_xml)
        at_def = first[0].start if first else len(notes_xml) - len(
            "</w:footnotes>")
    else:
        prev = next(f for f in find_all(notes_xml, include_reserved=True)
                    if f.id == before)
        at_def = prev.end
    parts[FOOTNOTES] = (notes_xml[:at_def] + body
                        + notes_xml[at_def:]).encode("utf-8")
    parts[DOCUMENT] = doc.encode("utf-8")
    return new_id


def find(footnotes_xml: str, contains: str) -> Footnote:
    """The single footnote whose text contains `contains`."""
    hits = [f for f in find_all(footnotes_xml) if contains in f.text]
    if len(hits) != 1:
        raise AnchorError(
            f"footnote containing {contains!r}: {len(hits)} hits, need 1")
    return hits[0]


def append(footnotes_xml: str, contains: str, text: str) -> str:
    """Append `text` to the end of a footnote's last paragraph.

    Adds a run inside the existing ``w:p`` rather than after it: a run
    placed directly in ``w:footnote`` is what makes Word reject the part.
    """
    note = find(footnotes_xml, contains)
    paras = list(PARA_RE.finditer(note.xml))
    if not paras:
        raise AnchorError(f"footnote {note.id} has no paragraph to append to")
    last = paras[-1]
    run = f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
    patched = (note.xml[:last.end() - len("</w:p>")] + run
               + note.xml[last.end() - len("</w:p>"):])
    return (footnotes_xml[:note.start] + patched
            + footnotes_xml[note.end:])


def renumber_map(source_xml: str, target_xml: str) -> dict[str, str]:
    """Footnote id in `source_xml` -> the id of the same note in `target_xml`.

    Matched on definition text, because the ids themselves are not
    stable: Word renumbers them on save.
    """
    target = {f.text: f.id for f in find_all(target_xml) if f.text}
    return {f.id: target[f.text] for f in find_all(source_xml)
            if f.text in target}


def remap(xml: str, mapping: dict[str, str]) -> str:
    """Rewrite every ``w:footnoteReference`` id through `mapping`.

    Apply to a paragraph taken from another document before splicing it
    in, or its footnote markers will point at whatever note happens to
    hold that id here.
    """
    return _REFERENCE_RE.sub(
        lambda m: m.group(1) + mapping.get(m.group(2), m.group(2))
        + m.group(3), xml)


# --------------------------------------------------------------- the font
# "Footnotes are Times New Roman 10" is a house rule, and the house is the
# PAPER's — so the size and the face are arguments. They are also the
# defaults, because that is the rule every manuscript here has asked for.
#
# This writes DIRECT run formatting rather than editing the FootnoteText
# style. The style is the tidier XML and the less reliable outcome: it
# only reaches a run if styles.xml actually defines FootnoteText AND the
# footnote's paragraph carries a pStyle referencing it, and manuscripts
# that satisfy neither are ordinary. Direct formatting is what wins in
# Word, which is the only test that counts.

_MATH_RE = re.compile(r"<m:oMath\b.*?</m:oMath>", re.DOTALL)
_RFONTS_RE = re.compile(r"<w:rFonts\b[^>]*?/>")
# `[^>]*` before w:val, not `<w:sz w:val=`: XML attribute order carries no
# meaning, and patterns here that hard-coded Word's habitual order have
# silently matched nothing on a conforming document before.
_SZ_RE = re.compile(r'<w:sz\b[^>]*w:val="(\d+)"[^>]*/>')
_ASCII_RE = re.compile(r'w:ascii="([^"]*)"')


@dataclass
class FontReport:
    """What :func:`set_font` changed, and what it deliberately did not."""

    notes: int = 0
    runs_set: int = 0
    math_runs_skipped: int = 0

    def format(self) -> str:
        out = [f"{self.runs_set} run(s) in {self.notes} footnote(s) set"]
        if self.math_runs_skipped:
            out.append(f"  {self.math_runs_skipped} equation run(s) left "
                       "alone (Cambria Math is not interchangeable with a "
                       "text face)")
        return "\n".join(out)


def _half_points(size: float) -> int:
    """Word stores a point size doubled: 10pt is ``w:val="20"``.

    Half-point steps are the finest Word records, so 10.5 is expressible
    and 10.3 is not — rounding here rather than truncating keeps the
    error under a quarter point instead of losing a half.
    """
    return round(size * 2)


def _math_spans(xml: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _MATH_RE.finditer(xml)]


def set_font(footnotes_xml: str, *, name: str = "Times New Roman",
             size: float = 10, include_reserved: bool = False,
             ) -> tuple[str, FontReport]:
    """Set the face and size of every run in every real footnote.

    An equation's runs keep their face. A footnote carrying OMML holds
    runs declared in Cambria Math, and the text faces do not have those
    glyphs — rewriting them to the body font is how an equation turns
    into boxes.

    Two things prevent it, and both are deliberate. OMML's own runs are
    ``m:r``, which ``RUN_RE`` does not match at all; and a ``w:r`` that
    sits inside an ``m:oMath`` — legal, and how Word writes literal text
    in a formula — is skipped explicitly and COUNTED, so "some runs were
    left" is visible rather than inferred from a total that looks low.

    Measured over the 1,940 footnote parts on this machine: 495 contain
    OMML and none of them put a ``w:r`` inside it, so the explicit skip
    never fired and the ``m:r`` rule did all the work. Keep both. The
    day someone widens the run pattern to reach math runs, the skip is
    the only thing standing between a formula and the body font.

    Word's separator and continuation notes (ids 0 and -1) are not
    footnotes and are left alone unless `include_reserved`.
    """
    sz = _half_points(size)
    face = escape_attr(name)
    rfonts = (f'<w:rFonts w:ascii="{face}" w:hAnsi="{face}" w:cs="{face}"/>')
    report = FontReport()

    out: list[str] = []
    cursor = 0
    for note in find_all(footnotes_xml, include_reserved=include_reserved):
        out.append(footnotes_xml[cursor:note.start])
        cursor = note.end
        report.notes += 1

        math = _math_spans(note.xml)
        pieces: list[str] = []
        at = 0
        for m in RUN_RE.finditer(note.xml):
            if span_holding(m.start(), math) is not None:
                report.math_runs_skipped += 1
                continue
            fixed = set_run_property(m.group(0), "rFonts", rfonts)
            fixed = set_run_property(fixed, "sz", f'<w:sz w:val="{sz}"/>')
            fixed = set_run_property(fixed, "szCs", f'<w:szCs w:val="{sz}"/>')
            pieces.append(note.xml[at:m.start()])
            pieces.append(fixed)
            at = m.end()
            report.runs_set += 1
        pieces.append(note.xml[at:])
        out.append("".join(pieces))

    out.append(footnotes_xml[cursor:])
    return "".join(out), report


def _run_font(run_xml: str) -> tuple[str | None, int | None]:
    """The face and half-point size this run carries ITSELF.

    ``None`` means the run states nothing and inherits — which is not
    the same claim as "conforms", and reporting it as the latter would
    be a guess about styles.xml, a part this module is never given.
    """
    own = own_properties(run_xml, "rPr")
    if own is None:
        return None, None
    live = live_properties(own[2])
    face = None
    if (m := _RFONTS_RE.search(live)) and (a := _ASCII_RE.search(m.group(0))):
        face = a.group(1)
    sz = int(s.group(1)) if (s := _SZ_RE.search(live)) else None
    return face, sz


def fonts(footnotes_xml: str, *, include_reserved: bool = False
          ) -> dict[str, int]:
    """Every distinct face/size a footnote run states, with run counts.

    The question "are the footnotes Times New Roman 10?" asked of a file
    rather than imposed on it. A run that states nothing is reported as
    ``"inherited"`` and never folded into a face it might well render
    as: the answer lives in styles.xml and docDefaults, and claiming it
    from here would be a guess.
    """
    seen: dict[str, int] = {}
    for note in find_all(footnotes_xml, include_reserved=include_reserved):
        math = _math_spans(note.xml)
        for m in RUN_RE.finditer(note.xml):
            if span_holding(m.start(), math) is not None:
                continue
            face, sz = _run_font(m.group(0))
            if face is None and sz is None:
                key = "inherited"
            else:
                pts = "inherited" if sz is None else f"{sz / 2:g}pt"
                key = f"{face or 'inherited face'} {pts}"
            seen[key] = seen.get(key, 0) + 1
    return seen


# ------------------------------------------------- do they AGREE on a size
# A different question from `fonts`, and the one a manuscript fails
# silently: one footnote rendered at 12pt among 10pt neighbours, and it
# carried NO `w:sz` at all — it inherited the body size — so searching
# for a wrong value found nothing. What gives it away is not the value
# but the DISAGREEMENT, which needs no styles.xml to see.
#
# Only text-bearing runs are asked for the BODY size. The run holding
# `w:footnoteRef` is formatted by the FootnoteReference style and
# normally states no size, so counting it among the body runs would put
# every conforming document on the list — the mark is superscript and a
# point or two smaller by design.
#
# The mark is asked SEPARATELY, and it earned that after the exclusion
# was recorded as a known edge with "Evidence: none". Measured over 331
# manuscripts with footnotes (2026-08-11): 26 state a size on the mark,
# and in 22 of them exactly ONE mark resolves to 10pt where every other
# resolves to 11pt — IGM, TCC and Parental Style, several of them
# submitted. So the marks are compared to each OTHER, which keeps the
# quiet the exclusion was protecting: a document whose marks all resolve
# alike reports nothing, however they are styled.


#: the run that DRAWS the little number, in a footnote's own first
#: paragraph. `w:footnoteReference` is the other end — the mark in the
#: body — and is deliberately not this.
_MARK_RE = re.compile(r"<w:footnoteRef\s*/>")


@dataclass(frozen=True)
class SizeOutlier:
    """A footnote that does not resolve to what its neighbours state."""

    id: str
    stated: tuple[int | None, ...]     # half-points; None = unresolvable
    text: str
    via: str = ""                      # what supplied it, if not the run

    def __str__(self) -> str:
        if self.stated == (None,):
            what = "states no size — inherits whatever the body is"
        else:
            sizes_ = ", ".join("nothing" if s is None else f"{s / 2:g}pt"
                               for s in self.stated)
            what = (f"resolves to {sizes_} through {self.via}" if self.via
                    else f"states {sizes_}")
        return f"footnote {self.id}: {what} — {self.text!r}"


@dataclass
class SizeReport:
    """What the footnotes agree on, and which ones do not."""

    house: int | None = None           # half-points, or None if none agree
    counted: int = 0
    outliers: list[SizeOutlier] = field(default_factory=list)
    #: the reference MARK, compared to the other marks rather than to the
    #: body — a different question with a different house size
    mark_house: int | None = None
    mark_outliers: list[SizeOutlier] = field(default_factory=list)
    #: how :attr:`mark_house` was decided: ``"style"`` when some marks
    #: resolve through a paragraph or character style and those set it,
    #: ``"majority"`` when none do and the commonest value is all there
    #: is to go on
    mark_house_from: str = ""
    #: ids of footnotes whose paragraphs carry NO ``w:pStyle``. The
    #: actionable fact behind most mark disagreements, and one attribute
    #: lookup — a note that lost its style falls through `Normal` to
    #: `docDefaults`, and its mark is drawn at whatever the document
    #: default is.
    unstyled: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.outliers and not self.mark_outliers

    def format(self) -> str:
        house = ("none stated" if self.house is None
                 else f"{self.house / 2:g}pt")
        head = (f"{self.counted} footnote(s), house size {house}, "
                f"{len(self.outliers)} disagreeing")
        lines = [head] + [f"  {o}" for o in self.outliers]
        if self.mark_outliers:
            # An outlier is a mark that differs FROM `mark_house`, so
            # through `sizes()` the house is never None here and two
            # mutants live in the other arm. It stays anyway: this is a
            # public dataclass with public fields and `format()` is a
            # public method, so a caller that fills the list itself gets
            # a report rather than an exception — and an `assert` here
            # would be stripped by `python -O` and leave `None / 2`.
            mark = ("none stated" if self.mark_house is None
                    else f"{self.mark_house / 2:g}pt")
            how = (" (the marks that resolve through a STYLE, whatever "
                   "their number — the styled ones are the well-formed "
                   "ones)" if self.mark_house_from == "style"
                   else " (the commonest value: no mark here resolves "
                        "through a style, so there is nothing better to "
                        "go on)")
            lines.append(f"reference marks: house {mark}{how}, "
                         f"{len(self.mark_outliers)} disagreeing")
            lines += [f"  {o}" for o in self.mark_outliers]
        if self.unstyled:
            lines.append(
                f"  footnote(s) with NO w:pStyle: "
                f"{', '.join(self.unstyled)} — these fall through Normal to "
                f"the document default; give them the footnote style rather "
                f"than writing a size onto the mark")
        return "\n".join(lines)


class _Mark(NamedTuple):
    """One reference mark: what it resolves to, and through what."""

    id: str
    size: int | None            # half-points; None = does not resolve
    text: str
    via: str
    kind: str                   # styles.RUN | STYLE | DEFAULT | NOWHERE


def _judge_marks(report: SizeReport, marks: list[_Mark]) -> None:
    """Decide the marks' house size, and name the ones that miss it.

    **The styled marks set the house, however few they are.** The rule
    used to be "whatever most marks resolve to", and on Parental Style
    that was exactly backwards: five footnote paragraphs carried no
    `w:pStyle` at all, fell through `Normal` to a 12pt `docDefaults`,
    and took the majority with them; the two the check FLAGGED were the
    two carrying `pStyle FootnoteText` — the well-formed ones. Acting on
    that report would have stripped the correct style off the correct
    notes (2026-08-12).

    A count cannot tell malformed from house; how a value RESOLVES can.
    With no styled mark in the document there is nothing better to go on
    and the commonest value stands — said out loud in
    :attr:`SizeReport.mark_house_from`, because the two answers deserve
    different confidence.
    """
    resolved = [m for m in marks if m.size is not None]
    if not resolved:
        # A mark whose size does not resolve is not judged: without
        # styles.xml nothing here resolves, and calling that a
        # disagreement would report every document read without the
        # part. The body half declines the same way.
        return
    styled = [m.size for m in resolved if m.kind == _STYLE]
    pool = styled or [m.size for m in resolved]
    report.mark_house_from = "style" if styled else "majority"
    report.mark_house = max(set(pool), key=pool.count)
    report.mark_outliers = [
        SizeOutlier(f"{m.id} (reference mark)", (m.size,), m.text, m.via)
        for m in resolved if m.size != report.mark_house]


def sizes(footnotes_xml: str, *, styles_xml: str | None = None,
          include_reserved: bool = False) -> SizeReport:
    """Which footnotes disagree with the rest about their size.

    Reported as a disagreement rather than as a wrong value, because the
    footnote that went out at 12pt among 10pt neighbours stated NOTHING:
    it inherited the body size, and a search for a wrong number cannot
    find an absent one. The house size is what most footnotes resolve
    to, so a document whose footnotes all inherit — every size living in
    styles.xml, which is perfectly ordinary — has nothing to report.

    **Pass `styles_xml`.** A run that states nothing in a paragraph
    whose ``w:pStyle`` chain supplies a size resolves to that size, and
    without the part there is no way to know: Parental_style's footnote
    6 carries ``pStyle FootnoteText``, that style says ``w:sz 20``, and
    it has always rendered at 10pt like its neighbours. Reported as a
    finding, it was a false positive on the first real manuscript this
    was pointed at. The document default is the last fallback, which is
    what the two REAL offenders in that file resolve through.

    Without the part the disagreement is still reported, because the
    answer genuinely is not in ``footnotes.xml``.

    Repair with :func:`set_font`, which writes direct run formatting.
    """
    # ONE cascade, shared with the FORMAT layer of `compare`. This module
    # grew its own for an hour and it was already the narrower of the
    # two: paragraph styles only, where a run's own character style can
    # carry a size just as well.
    cascade = Cascade(styles_xml)

    stated: list[tuple[str, tuple[int | None, ...], str, str]] = []
    marks: list[_Mark] = []
    unstyled: list[str] = []
    for note in find_all(footnotes_xml, include_reserved=include_reserved):
        math = _math_spans(note.xml)
        seen: set[int | None] = set()
        sources: set[str] = set()
        paras = list(PARA_RE.finditer(note.xml))
        if paras and not any(Cascade.paragraph_style(p.group(0))
                             for p in paras):
            unstyled.append(note.id)
        for para in paras:
            pstyle = Cascade.paragraph_style(para.group(0))
            for r in RUN_RE.finditer(para.group(0)):
                at = para.start() + r.start()
                if any(s <= at < e for s, e in math):
                    continue
                own = own_properties(r.group(0), "rPr")
                rpr = live_properties(own[2]) if own else None
                got = cascade.resolve(
                    "sz", rpr=rpr, rstyle=cascade.style_of(rpr),
                    pstyle=pstyle)
                value = got.value
                if _MARK_RE.search(r.group(0)):
                    text = " ".join(visible_text(note.xml).split())[:48]
                    marks.append(_Mark(
                        note.id,
                        int(value) if value is not None else None,
                        text, got.via, got.kind))
                    continue           # judged against the other MARKS
                if not visible_text(r.group(0)).strip():
                    continue           # nothing on the page to size
                seen.add(int(value) if value is not None else None)
                if got.via:
                    sources.add(got.via)
        if not seen:
            continue                   # nothing a reader sees: nothing to say
        # `None` sorts last, and never against an int: the first key
        # element already separates the two cases
        found = tuple(sorted(seen, key=lambda s: (s is None, s)))
        text = " ".join(visible_text(note.xml).split())[:48]
        stated.append((note.id, found, text, ", ".join(sorted(sources))))

    report = SizeReport(counted=len(stated), unstyled=unstyled)
    _judge_marks(report, marks)

    agreed = [s[0] for _, s, _, _ in stated
              if len(s) == 1 and s[0] is not None]
    if not agreed:
        return report                  # nothing states a size: nothing to say
    report.house = max(set(agreed), key=agreed.count)
    report.outliers = [SizeOutlier(fid, s, text, via)
                       for fid, s, text, via in stated
                       if s != (report.house,)]
    return report

