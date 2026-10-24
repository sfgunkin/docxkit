"""What an author's Word session destroyed.

Split out of the single-file ``revision.py`` on 2026-08-30. The module
is part of :mod:`docxkit.revision`; import from there.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    # lxml arrives through `_tracked_gates._root`, lazily; named here so
    # the stubs see the walks in `_glyph` and `_counts`.
    from lxml.etree import _Element

    from ..footnotes import Footnote

from .. import tracked
from .._xml import (
    BOOKMARK_NAME_RE,
    ENDNOTES,
    FOOTNOTES,
    INSTR_ANCHOR_RE,
    NOTE_DEF_RE,
    WORD_ANCHOR,
    Parts,
    internal_links,
    ref_anchor,
    text_parts,
    visible_text,
    word_minted,
)
from ..hygiene import _MATH_T_RE, _comment_counts, _downgraded
from ._common import TEXT_PARTS, WP, M, W

# Word's Range.Text and the raw XML spell the same document differently,
# and every difference here is presentational. Fold them before
# comparing, or the accept-paths gate reports a mismatch on every
# document containing a footnote or an equation: \x02 is a footnote
# reference mark and \x07 a cell mark; Word returns math letters from
# the Mathematical Italic block while the XML stores ASCII with m:
# markup around it; and Word gives U+2212 where the XML holds a hyphen.
#
# U+2217 is the same story one character further: Word renders the
# asterisk inside math as ASTERISK OPERATOR, which NFKC does NOT fold
# because the two are distinct characters rather than compatibility
# variants. LI7 writes its prospective-age threshold "T*" eighteen times,
# so the gate failed on that paper with ZERO revisions in the file \u2014 and
# a gate that cannot pass is one its reader learns to skip.
#
# Each entry costs a little of what the gate can see, so each one is
# here because a real document produced it. Do not add a fold on
# suspicion.
_FOLD = str.maketrans({"\u2212": "-", "\u2010": "-", "\u2011": "-",
                       "\u00a0": " ", "\u2217": "*",
                       # PRIME vs APOSTROPHE. Word's Range.Text returns
                       # U+2032 where the XML stores U+0027 in derivative
                       # notation. Parental_style writes V', S', a^E'(x)
                       # and a^X'(x) throughout its theory section, so the
                       # gate failed there with ZERO revisions in the file
                       # -- the same shape as the T* case above.
                       "\u2032": "'"})


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return "".join(re.sub(r"[\x00-\x1f]", "", folded).split())


#: What Word's ``Range.Text`` returns where an INLINE ``w:drawing``
#: sits: one U+002F SOLIDUS, measured on a synthetic package whose only
#: content was a picture and two letters (``'A/B\r'``, ord 47).
#:
#: This is deliberately NOT a `_FOLD` entry. Folding ``/`` away would
#: blind the gate to every "and/or" and every URL in the manuscript;
#: emitting the same character the other side emits keeps both.
#:
#: Three things the same probe settled, each of which would otherwise
#: have been guessed:
#:
#: * an ANCHORED drawing (``wp:anchor``, a floating figure) contributes
#:   NOTHING — it is not in the text stream at all;
#: * the legacy inline forms, ``w:pict`` and ``w:object``, give U+0001
#:   instead, which `_norm` already strips as a control character. They
#:   need no placeholder, and giving them this one would break them;
#: * a TEXT BOX's prose is a different STORY, and `doc.Paragraphs` does
#:   not walk it — hence `main_story` below.
_DRAWING_GLYPH = "/"


def _glyph(root: _Element | None, *, main_story: bool = False) -> str:
    """Every rendered character, prose and math alike, in document order.

    `main_story` narrows the walk to what Word's ``doc.Paragraphs``
    covers, for the gate that compares this stream against Word's own:
    a text box is a separate story, so its prose is absent from
    ``Range.Text`` while it sits in ``document.xml`` like any other
    paragraph. Left in, the gate reports a difference for every text box
    in the manuscript — and it is off by default because the XML-to-XML
    gate above WANTS that prose compared.

    Pruning `w:txbxContent` also disposes of an `mc:AlternateContent`
    hazard for free: Word writes a shape's text twice, once under
    `mc:Choice` and once in the VML `mc:Fallback`, and only one of them
    is ever rendered.
    """
    if root is None:
        return ""
    out: list[str] = []
    stack: list[_Element] = [root]
    while stack:
        el = stack.pop()
        # `object`, not the stubs' `str`: a comment's tag is the FUNCTION
        # `etree.Comment`, and the guard below is live on every file
        # Word wrote with one in it
        tag: object = el.tag
        if not isinstance(tag, str):
            continue                       # a comment or a PI
        if tag in (W + "t", M + "t"):
            out.append(el.text or "")
            continue                       # a leaf: nothing below it
        if tag == W + "drawing":
            if el.find(WP + "inline") is not None:
                out.append(_DRAWING_GLYPH)
        elif main_story and tag == W + "txbxContent":
            continue
        stack.extend(reversed(list(el)))   # depth-first, document order
    return "".join(out)


def _counts(root: _Element | None) -> dict[str, int]:
    if root is None:
        return {}
    return {
        "oMath": len(root.findall(".//" + M + "oMath")),
        "tables": len(root.findall(".//" + W + "tbl")),
        "ins": len(root.findall(".//" + W + "ins")),
        "del": len(root.findall(".//" + W + "del")),
        # an OMML element with no text renders as a blank box. A
        # mechanical XML accept can leave these where Word's own accept
        # prunes them, and a manuscript once shipped with visibly broken
        # equations that way.
        "empty_shells": sum(1 for om in root.iter(M + "oMath")
                            if not any((t.text or "")
                                       for t in om.iter(M + "t"))),
    }


def _links(parts: Parts) -> Counter[tuple[str, str]]:
    """``(anchor, label)`` for every internal link, every text part.

    The fourth thing gate 5 compares, and the one it was blind to: the
    words of a link can come back from reject-all without the link, and
    paragraphs and glyphs both compare TEXT. Parental Style T4(3) came
    back 227 links against the baseline's 229, with `reject-all`
    reporting OK and `citations` ALL CHECKS PASSED — both later
    mentions, so nothing dangled — and the author two links short with
    nothing anywhere saying so (2026-08-12).

    That measurement, and Aging_Well R24's after it, were taken through
    THIS package's reject, and until 2026-10-12 it did not restore a
    deleted field's ``w:delInstrText`` — which is how Compare writes
    almost every link it deletes. Word's Reject All does restore it. So
    "Compare does not rebuild a link inside a rejected deletion", which
    this docstring said, was the model's defect and not Word's; a link
    still LOST here is one that went with no tracked change around it.

    Measured with Word afterwards (2026-10-12): Reject All on each of
    the 115 kept redlines on this machine, 17 of them carrying 119
    deleted link fields, gave the same multiset as this package's
    reject on 114 (21,772 links against 21,773).
    The 115th (HPPA 2026-10-10) differs by a HYPERLINK field nested in
    another to the same anchor, which Word's reject keeps as one link.
    The build warning that predicted those losses ("shorten the move")
    was retired the same day.

    Counted as a MULTISET of pairs, not as a total: a link that survives
    at a different place is not a link that was lost, and a total hides
    a swap. Both link forms are read, because Word rewrites a field into
    an element on every author save and the two must not read as one
    lost and one gained.
    """
    out: Counter[tuple[str, str]] = Counter()
    for _name, xml in text_parts(parts):
        # Word's own anchor is re-minted on every Compare, so the NAME
        # is not a fact about the document; the visible label is, and it
        # is what a reader would miss. Keyed under one stand-in, a
        # cross-reference that really went still reports as lost, and a
        # rebuild of the same one does not.
        out.update((WORD_ANCHOR if word_minted(a) else a, label)
                   for a, label in internal_links(xml))
    return out


def _bookmarks(parts: Parts) -> set[str]:
    return {n for name, blob in parts.items()
            if name in TEXT_PARTS
            for n in BOOKMARK_NAME_RE.findall(blob.decode("utf-8", "replace"))
            if not word_minted(n)}          # Word's own _Toc/_Ref names


@dataclass(frozen=True)
class Loss:
    """Structure the hand-back no longer carries, named so it can be OK'd."""

    kind: str        # link | footnote | endnote | bookmark |
                     # comment | glyph
    what: str        # the anchor, the note's text, the bookmark's name
    #: Do the WORDS this thing carried survive in the hand-back? The
    #: report's whole explanation turns on it — "the words all survive,
    #: so no content layer above shows it" is the signature of Word
    #: collapsing a paragraph, and is false of a passage the author
    #: deleted. `None` where the question does not apply (a glyph, a
    #: comment count) and the explanation must not claim either.
    words: bool | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.what}"

    def __str__(self) -> str:
        return f"{self.kind} {self.what[:70]!r}"


@dataclass(frozen=True)
class Relabelled:
    """A link whose ANCHOR survived and whose visible text changed."""

    anchor: str
    was: str
    now: str

    @property
    def unbalanced(self) -> str:
        """The bracket the new label opens or closes and the other does not.

        RE-LABELLED exists to say "the anchor is intact, nothing is
        lost, do not block the baseline" — which is right about the
        anchor and silent about the SPAN. An author turning a narrative
        citation parenthetical leaves Word holding the old right-hand
        boundary, so the link covers `Klimaviciute and Pestieau 2023)`:
        a closing bracket with no opening one inside the blue. That is
        damage wearing a re-label's clothes, and this is what tells the
        two apart.
        """
        from ..citations import unbalanced_span

        return unbalanced_span(self.now)

    def __str__(self) -> str:
        return f"link {self.anchor}: {self.was[:40]!r} -> {self.now[:40]!r}"


def _link_changes(working: Parts, prev: Parts,
                  ) -> tuple[list[Loss], list[Relabelled]]:
    """Links the hand-back LOST, and links it merely RE-LABELLED.

    `_links` keys a link by the (anchor, label) pair, which is right for
    finding a link Word ate — and reads an author's own edit of the
    visible text as a loss. DSI's R24.1 re-labelled four back-link
    fields on purpose («UN 2026» -> «United Nations 2026»); all four
    bookmarks were present, all four fields still named them, and
    `citations.audit_links` reported 152 links and 0 broken. `baseline`
    refused anyway, and the paper passed `--accept-loss` four times
    after checking each anchor by hand (2026-08-19).

    A gate that refuses a legitimate edit teaches the person to wave it
    through, and the next real loss goes the same way. So the pair is
    split on the one fact that decides it: a link is LOST when its
    anchor is no longer linked from anywhere in the hand-back, and
    RE-LABELLED when it is. Only the first blocks.

    Paired off one for one, so an anchor that was linked twice and comes
    back once still reports the link that went: each gone label consumes
    one gained label for the same anchor, and what is left over is a
    loss.
    """
    was, now = _links(prev), _links(working)
    gained = Counter(now - was)
    still_linked = {anchor for anchor, _label in now}
    # Do the link's WORDS survive somewhere in the hand-back? That is
    # what separates the two causes a lost link has, and the report
    # asserted one of them for both. See `losses` for the measurement.
    surviving = _visible(working)
    lost: list[Loss] = []
    relabelled: list[Relabelled] = []
    for anchor, label in sorted((was - now).elements()):
        fresh = sorted(lab for (a, lab), n in gained.items()
                       if a == anchor and n > 0)
        if anchor in still_linked and fresh:
            gained[(anchor, fresh[0])] -= 1
            relabelled.append(Relabelled(anchor, label, fresh[0]))
        else:
            lost.append(Loss("link", f"{anchor} ({label[:40]})",
                             words=bool(label.strip())
                             and label.strip() in surviving))
    return lost, relabelled


def _visible(parts: Parts) -> str:
    """Every word a reader can see, all text parts, one stream.

    Read once per hand-back and searched per loss: a manuscript has one
    or two dozen losses at most and re-reading the body for each was
    measurable on nothing, but the stream is the honest object — a
    citation moved from the body into a footnote has not been deleted.
    """
    return "\n".join(visible_text(xml) for _name, xml in text_parts(parts))


def relabelled_links(working: Parts,
                     prev: Parts) -> list[Relabelled]:
    """Links whose visible text an author changed, anchors intact.

    Reported, never refused — see :func:`_link_changes` for why the two
    are told apart at all.
    """
    return _link_changes(working, prev)[1]


def losses(working: Parts,
           prev: Parts) -> list[Loss]:
    """What an author's Word session destroyed, and no text diff shows.

    The protocol's safety claim is that ``working.docx`` is the one file
    and its state is readable. Between the hand-back and
    :func:`baseline`, nothing used to fail on lost CONTENT: `ingest`
    printed it, `validate` checked the batch (and on a hand-back there
    is no batch), and `baseline` copied.

    **LI7, 2026-08-15.** The manuscript came back missing three Figure 4
    cross-references, a European Commission 2024 citation, and footnote
    15 entire — note, reference, and the link inside it. Measured
    through the chain, nothing the toolkit built had lost them:

    ======================  =====  =====  =====
    stage                   body   note   notes
                            links  links
    ======================  =====  =====  =====
    prev                    33     15     19
    the edited clean build  33     15     19
    the Compare redline     33     15     19
    after the author's      **28** **14** **18**
    session
    ======================  =====  =====  =====

    Word had collapsed one paragraph into a single run to make four
    copyedits, and every link and the note reference in it went at once.
    Then it RENUMBERED: 19 notes became 18 with the ids still
    contiguous, so there is no gap to notice and no id to miss. Counting
    is the only way to see it, which is why the notes are matched on
    their TEXT here rather than on their id.

    Returns one entry per lost thing. Empty is the ordinary case: an
    author who edits prose loses none of this — and, since 2026-08-19,
    an author who RE-LABELS a link keeps it: see
    :func:`relabelled_links`, which is reported rather than refused.

    **A lost link has two causes, and they need opposite actions.** Word
    collapsing a paragraph strips the hyperlink and keeps the words, and
    `r2`/`r11` put such a link back. An author DELETING the sentence
    takes the words with it, and there is nothing to put back — the cut
    is the edit. `Loss.words` measures which: is the link's own label
    still visible anywhere in the hand-back? Measured 2026-09-08 on
    Aging_Well, one report holding both kinds — 4 links whose mentions
    were intact (`Robeyns2005`, `North1990`, `Box2` twice; r2/r11
    restored all four) and 5 whose mentions were gone (`Cox1987`,
    `WorldBank1994`, `Holzmann2005`, `Barr2010`, `OECD2006`, each cited
    in one place and that place cut). Reported as one list under one
    explanation, the reader either runs the repair lane hoping it covers
    everything or reads five deliberate cuts as damage.

    Notes, bookmarks, comments and glyphs leave `words` at `None`: Word
    eating a footnote takes the definition and its text together (LI7's
    note 15 above), so the question does not separate anything there and
    the report must not answer it.
    """
    out: list[Loss] = []
    out += _link_changes(working, prev)[0]
    out += _lost_notes(working, prev)
    out += _downgraded_math(working, prev)
    out += [Loss("bookmark", name)
            for name in sorted(_bookmarks(prev) - _bookmarks(working))]
    out += _lost_comments(working, prev)
    return out


def _comment_what(key: tuple[str, str]) -> str:
    """How a lost comment is NAMED: its author and its whole text."""
    return f"{key[0]}: {key[1]}"


def _lost_comments(working: Parts, prev: Parts) -> list[Loss]:
    """Comments `prev` holds that the hand-back does not — by WHICH
    comment, never by how many.

    Counted, a comment Word ate was offset by every comment the round
    ADDED, and since `[batch] classify` the protocol adds its own: two
    referee comments in `prev`, five comments in the hand-back after a
    classified batch put four balloons in, one referee comment gone with
    its anchor, and `baseline` made the loss permanent with nothing said
    (review of 2026-10-24). So a comment is its author and its text, the
    key `hygiene` already reads two copies of one note by, and the lost
    are the multiset difference.

    An EMPTY comment has no text to be known by, and is still counted.
    """
    was, now = _comment_counts(prev), _comment_counts(working)
    out = [Loss("comment", _comment_what(key))
           for key in sorted((was - now).elements())]
    empty = ((tracked.package_counts(prev)["comments"] - was.total())
             - (tracked.package_counts(working)["comments"] - now.total()))
    if empty > 0:
        out.append(Loss("comment", f"{empty} empty comment(s) gone"))
    return out


def _downgraded_math(working: Parts,
                     prev: Parts) -> list[Loss]:
    """Equation runs the author's Word session flattened to ASCII.

    Word rewrites OMML on accept-and-save as readily as on Compare, and
    downgrades U+2212 MINUS SIGN to a hyphen while it is there. It is
    not a content change and no text gate sees it: `losses` counted
    links, notes, bookmarks and comments, and the paper still rendered.

    AFI lost all four of its minus signs this way, twice — wave 1 and
    wave 2 — and `baseline` copied the result over `prev.docx` both
    times, after which the hyphens ARE the truth and the next reject-all
    measures against them. The paper's own log records the workaround as
    "not optional on this manuscript".

    Reported as a LOSS rather than repaired here, and matched the way
    `restore_math_glyphs` matches: a run the baseline has is gone, and a
    run has appeared that is exactly it with the glyphs flattened. An
    author who genuinely rewrote an equation is not reported, because
    the two texts would not correspond that way.
    """
    def runs(parts: Parts) -> Counter[str]:
        found: Counter[str] = Counter()
        for name, blob in parts.items():
            if name.endswith(".xml"):
                found.update(m.group(2) for m in
                             _MATH_T_RE.finditer(blob.decode("utf-8",
                                                             "replace")))
        return found

    was, now = runs(prev), runs(working)
    gained = now - was
    return [Loss("glyph", f"{text} -> {_downgraded(text)}")
            for text, _n in sorted((was - now).items())
            if _downgraded(text) != text and gained.get(_downgraded(text))]


def _notes(parts: Parts, part: str, kind: str) -> list[Footnote]:
    from ..footnotes import find_all

    blob = parts.get(part)
    if blob is None:
        return []
    return [f for f in find_all(blob.decode("utf-8", "replace"), kind=kind)
            if f.text]


def _lost_notes(working: Parts,
                prev: Parts) -> list[Loss]:
    """Notes the hand-back no longer HAS — never merely reworded ones.

    The first version compared note TEXT as a multiset, so editing one
    character inside a footnote read as the old note having vanished.
    LI7 hit it the same day (2026-08-15) and it BLOCKED the paper: gate
    D4 split a section, footnote 13's "throughout Sections 4-6" became
    "4-7", and `baseline` refused to record a manuscript that had lost
    nothing. Text is the right identity for a link LABEL and the wrong
    one for a note, because a note is prose an author edits.

    So the decision is made on the REFERENCE: a note whose marker is
    still in the body has not been lost, however much its wording
    changed. Counting rather than matching ids, because Word renumbers
    ids on save — that is the whole reason the ids cannot be trusted
    here (see :func:`docxkit.renumber.footnotes`).

    The text is still used, but only to SAY which note went: a
    description for the reader, never the test.
    """
    out: list[Loss] = []
    for kind, part in (("footnote", FOOTNOTES), ("endnote", ENDNOTES)):
        was = _notes(prev, part, kind)
        now = _notes(working, part, kind)
        gone = len(was) - len(now)
        if gone <= 0:
            continue
        # which ones, best effort: the notes whose text no longer
        # appears anywhere. A reworded note matches nothing either, so
        # take only as many as the COUNT says are really missing, and
        # say plainly when we cannot name them.
        texts = Counter(f.text for f in now)
        missing = [f.text for f in was if not texts[f.text]]
        named = sorted(missing)[:gone]
        out += [Loss(kind, text) for text in named]
        if len(named) < gone:
            out.append(Loss(kind,
                            f"{gone - len(named)} more, unnamed — "
                            f"{len(was)} {kind}s before, {len(now)} now"))
    return out


#: The kinds a batch can propose deleting, so the only ones
#: :func:`batch_deletions` may excuse. A glyph Word flattened is never a
#: batch's proposal. A comment is, since 2026-10-24: a batch that does
#: not carry a comment of the truth took it out, and the author was
#: never offered it.
BATCH_KINDS = ("footnote", "endnote", "bookmark", "link", "comment")


def _structure(parts: Parts, kind: str) -> Counter[str | tuple[str, str]]:
    """Everything of `kind` in `parts`, as the multiset `losses` reads."""
    found: Counter[str | tuple[str, str]] = Counter()
    if kind in ("footnote", "endnote"):
        part = FOOTNOTES if kind == "footnote" else ENDNOTES
        found.update(f.text for f in _notes(parts, part, kind))
    elif kind == "bookmark":
        found.update(_bookmarks(parts))
    else:
        found.update(_links(parts))
    return found


#: Where a run of text sits in a proposal: kept, inserted or deleted.
_SAME, _INS, _DEL = 0, 1, 2
_STATE_OF = {W + "ins": _INS, W + "moveTo": _INS,
             W + "del": _DEL, W + "moveFrom": _DEL}
#: Unchanged characters either side of a deletion that the hand-back
#: must still hold, folded by `_norm`. Enough that a short sentence
#: elsewhere cannot stand in for the place; short enough that a copyedit
#: a sentence away does not hide it.
_CONTEXT = 20


#: Where a part's text begins and ends, in a reading. A cut at the first
#: or last text of a part has nothing unchanged on that side, and read
#: without these its accepted reading was the other side alone — words
#: every hand-back holds, accepted or not (review of 2026-10-24). With
#: them, a cut at the end of the part is shown accepted only by a
#: hand-back that ENDS where the proposal accepted ends. Control
#: characters, so `_norm` never produces either.
_START, _END = "\x00", "\x01"


class _Mark(NamedTuple):
    """A note reference, a bookmark start or a link, where it sits in a
    stream."""

    kind: str        # footnote | endnote | bookmark | link
    key: str         # the note's id, the bookmark's name, the anchor
    state: int
    at: int          # index into the stream's text pieces it precedes


def _link_state(el: _Element, state: int) -> int:
    """A `w:hyperlink`'s state: its own, or DELETED when every word it
    shows is — Compare deletes a link's label inside the element as
    readily as it deletes the element."""
    if state != _SAME:
        return state
    shown = [t.tag for t in el.iter(W + "t", W + "delText")]
    return _DEL if shown and all(t == W + "delText" for t in shown) \
        else state


def _stream(root: _Element | None,
            ) -> tuple[list[tuple[str, int]], list[_Mark]]:
    """A part's text in document order, each piece with its state, and
    the note references, bookmark starts and internal links between the
    pieces.

    A link is marked where it starts: a ``w:hyperlink`` by its anchor, a
    field by the anchor its instruction names — read from ``instrText``
    and ``delInstrText`` both, since Compare writes almost every link it
    deletes as a field whose code is deleted with it — once the field's
    ``separate`` (or its ``end``) says the instruction is complete.
    """
    texts: list[tuple[str, int]] = []
    marks: list[_Mark] = []
    if root is None:
        return texts, marks
    note_kind = {W + "footnoteReference": "footnote",
                 W + "endnoteReference": "endnote"}
    fields: list[tuple[list[str], int] | None] = []    # instr, its state
    stack: list[tuple[_Element, int]] = [(root, _SAME)]
    while stack:
        el, state = stack.pop()
        tag: object = el.tag
        if not isinstance(tag, str):
            continue                       # a comment or a PI
        if tag in (W + "t", W + "delText", M + "t"):
            texts.append((el.text or "", state))
            continue
        if tag in note_kind:
            marks.append(_Mark(note_kind[tag], el.get(W + "id") or "",
                               state, len(texts)))
            continue
        if tag == W + "bookmarkStart":
            marks.append(_Mark("bookmark", el.get(W + "name") or "",
                               state, len(texts)))
            continue
        if tag == W + "fldChar":
            kind = el.get(W + "fldCharType")
            if kind == "begin":
                fields.append(([], state))
            elif kind in ("separate", "end") and fields:
                _field_mark(fields, marks, len(texts))
                if kind == "end":
                    fields.pop()
            continue
        if tag in (W + "instrText", W + "delInstrText"):
            if fields and fields[-1] is not None:
                instr, _ = fields[-1]
                if not instr:
                    fields[-1] = (instr, state)
                instr.append(el.text or "")
            continue                       # code, not text a reader sees
        if tag in (W + "rPrChange", W + "pPrChange"):
            continue                       # no text a reader sees
        if tag == W + "hyperlink" and el.get(W + "anchor"):
            marks.append(_Mark("link", el.get(W + "anchor") or "",
                               _link_state(el, state), len(texts)))
        inner = _STATE_OF.get(tag, state) if len(el) else state
        stack.extend((kid, inner) for kid in reversed(list(el)))
    return texts, marks


def _field_mark(fields: list[tuple[list[str], int] | None],
                marks: list[_Mark], at: int) -> None:
    """Mark the innermost open field as a link, once, if it is one."""
    top = fields[-1]
    if top is None:
        return                             # already marked, or not a link
    instr, state = top
    code = "".join(instr)
    hm = INSTR_ANCHOR_RE.search(code)
    anchor = hm.group(1) if hm else ref_anchor(code)
    if anchor is not None:
        marks.append(_Mark("link", anchor, state, at))
    fields[-1] = None


def _once(needle: str, hay: str) -> bool:
    """Does `needle` occur in `hay` exactly once, overlaps counted?"""
    at = hay.find(needle)
    return at >= 0 and hay.find(needle, at + 1) < 0


def _reading(texts: Sequence[tuple[str, int]], drop: int) -> str:
    """A whole stream as one reading, its ends marked."""
    return _START + _norm("".join(t for t, s in texts if s != drop)) + _END


def _accepted_here(texts: Sequence[tuple[str, int]], at: int,
                   handback: str, proposed: str) -> bool:
    """Does the hand-back read the proposal ACCEPTED at `at`, and not
    rejected?

    The changed text around `at` and `_CONTEXT` unchanged characters
    either side — or the part's own end, where it comes first — read
    both ways. Accepted, the hand-back holds the first reading and not
    the second. Anything else is not evidence, and the caller keeps the
    loss: the cut rejected, the place copyedited, a cut with no words
    (both readings are one), and a reading that is not ONE place — found
    twice in the hand-back, or twice in the proposal accepted
    (`proposed`), as a context repeated by duplicated table rows is
    (review of 2026-10-24).
    """
    def changed(i: int) -> bool:
        text, state = texts[i]
        return state != _SAME or not _norm(text)

    lo, hi = at, at
    while lo > 0 and changed(lo - 1):
        lo -= 1
    while hi < len(texts) and changed(hi):
        hi += 1
    for step in (-1, 1):
        kept = 0
        while kept < _CONTEXT:
            i = lo - 1 if step < 0 else hi
            if not 0 <= i < len(texts):
                break
            if texts[i][1] == _SAME:
                kept += len(_norm(texts[i][0]))
            if step < 0:
                lo -= 1
            else:
                hi += 1
    head = _START if lo == 0 else ""
    tail = _END if hi == len(texts) else ""
    window = texts[lo:hi]
    accepted = head + _norm("".join(t for t, s in window if s != _DEL)) + tail
    rejected = head + _norm("".join(t for t, s in window if s != _INS)) + tail
    return (accepted != rejected and _once(accepted, handback)
            and _once(accepted, proposed) and rejected not in handback)


_Read = tuple[list[tuple[str, int]], list[_Mark], str, str]


def _places(proposal: Parts, working: Parts,
            wanted: Callable[[_Mark], bool],
            read: dict[str, _Read] | None = None,
            ) -> list[tuple[_Mark, bool]]:
    """Every `wanted` mark in the proposal's text parts, each with
    whether the hand-back shows its place ACCEPTED (:func:`_accepted_here`).

    A key the proposal holds twice in one part — a note id, a bookmark
    name — is no identity, and is never shown. A link's anchor is not
    one either (a citation repeated), and need not be: a link is shown
    by its place alone.

    `read` keeps each part's parse for the next call: `batch_deletions`
    asks once per kind, and parsed both packages afresh every time —
    3.9 to 5.1 s of a 10 MB hand-back (review of 2026-10-24).
    """
    from ..tracked import _root

    read = {} if read is None else read
    out: list[tuple[_Mark, bool]] = []
    for name in TEXT_PARTS:
        if name not in read:
            texts, marks = _stream(_root(proposal, name))
            here, _ = _stream(_root(working, name))
            read[name] = (texts, marks, _reading(here, _DEL),
                          _reading(texts, _DEL))
        texts, marks, handback, proposed = read[name]
        chosen = [m for m in marks if wanted(m)]
        if not chosen:
            continue
        seen = Counter((m.kind, m.key) for m in marks)
        for mark in chosen:
            unique = mark.kind == "link" or seen[(mark.kind, mark.key)] == 1
            out.append((mark, unique and _accepted_here(
                texts, mark.at, handback, proposed)))
    return out


def batch_deletions(gone: Sequence[Loss], working: Parts, prev: Parts,
                    proposal: Parts) -> tuple[list[Loss], list[Loss]]:
    """``(deleted by the batch, still lost)``: `gone`, split in two.

    HPPA_Index, 2026-10-09: a batch deleted footnote 8, the author
    accepted it, and `baseline` refused with ``LOST (1)`` until it was
    handed ``--accept-loss`` for the batch's own proposal. The loss gate
    is there for what WORD ate, and an exemption typed every round is the
    habit that waves the next real loss through.

    **One loss is never matched to one deletion**, which is what the
    first attempt did (344f49c, reverted in 4deb0f9): a `Loss.key` is
    not an identity. A repeated citation shares one key, and a reworded
    note's old text is named as lost beside the note Word really ate.
    So a whole KIND is excused or none of it, and only when the files
    prove the hand-back is the proposal with every change of that kind
    accepted:

    * the proposal's REJECTED view holds exactly what `prev` holds, so
      it was built on this truth;
    * its ACCEPTED view holds exactly what `working` holds, so nothing
      else of that kind came or went. A note the author reworded, a
      deletion rejected, a link Word stripped, any of these breaks the
      equality, and every loss of that kind then blocks as before.

    **And the equality is not enough, because it is a count** (review
    of 2026-10-14). The author REJECTS the cut of "Claim 2." and its
    note, Word collapses the paragraph and eats the note anyway, and the
    hand-back's notes equal the accepted view's to the letter; two notes
    of the same words, the batch cutting one and Word eating the other,
    do the same. So each deletion the batch made has to be shown
    ACCEPTED at its own place: the words around it read as the proposal
    accepted and not as it rejected (:func:`_accepted_here`).
    A note is excused only when EVERY note of its kind the batch cut is
    shown so, because the loss list cannot say which note is which; a
    LINK the same way, every link the batch cut, since an anchor is no
    identity either (a citation repeated). A bookmark, whose name is its
    identity, one by one — and against `prev` alone, not the accepted
    view: `revision build` asks for a bookmark Compare restored to be
    deleted by hand after the promote, and doing so made the bookmarks
    unequal and every bookmark the batch cut LOST (review of
    2026-10-24). A cut with no words in it — the reference mark alone,
    HPPA's footnote 8 — reads the same accepted, or rejected with its
    note eaten by Word, and is never shown: it stays a loss, and
    ``--accept-loss`` is the way past it.

    A link was excused on the equality and "its words are gone" alone
    until 2026-10-24, the one kind the place was never asked of: the
    author rejected a cut and RETYPED the citation in it, the link went
    with the retyping, the label no longer read verbatim, and the round
    baselined with the link recorded as the batch's deletion. Shown at
    its place, a rejected cut is not, and a citation whose label is
    still on the page elsewhere needs no special rule: Word stripping
    that other copy breaks the equality, and a rejected cut is no
    accepted one.

    A COMMENT has no tracked change, so no place to show: one the truth
    holds and the proposal does not, the batch took out, and the author
    was never offered it. As many of each as the proposal lacks, and no
    more — a comment the proposal still carried and the hand-back does
    not is Word's or the author's doing, and stays a loss.

    The views have to read the structure the way Word does, and that was
    measured (2026-10-12) with Word's Accept All and Reject All on 116
    kept redlines: notes on all of them, links on all but one (a doubled
    nested field), and bookmarks once `revisions` dropped the ones Word
    drops with their content. A disagreement makes a kind unequal, so
    it refuses rather than excuses.
    """
    from ..tracked import accepted_view, rejected_view

    kinds = {loss.kind for loss in gone if loss.kind in BATCH_KINDS}
    if not kinds:
        return [], list(gone)
    accepted, rejected = accepted_view(proposal), rejected_view(proposal)
    built_on = {kind for kind in kinds - {"comment"}
                if _structure(rejected, kind) == _structure(prev, kind)}
    equal = {kind for kind in built_on
             if _structure(accepted, kind) == _structure(working, kind)}
    shown: dict[str, list[Loss]] = {}
    read: dict[str, _Read] = {}
    for kind in sorted(equal & {"footnote", "endnote"}):
        cut = _places(proposal, working, _cut_of(kind), read)
        if cut and all(ok for _m, ok in cut):
            shown[kind] = _cut_named(kind, {m.key for m, _ok in cut},
                                     rejected, gone)
    links = "link" in equal and _links_shown(proposal, working, accepted,
                                             rejected, read)
    marks: set[str] = set()
    if "bookmark" in built_on:
        removed = _bookmarks(rejected) - _bookmarks(accepted)
        marks = {m.key for m, ok in _places(
            proposal, working,
            lambda m: m.kind == "bookmark" and m.key in removed, read) if ok}
    comments = _comments_cut(prev, proposal) if "comment" in kinds \
        else Counter()
    excused = [loss for loss in gone
               if (loss.kind in shown)
               or (loss.kind == "bookmark" and loss.what in marks)
               or (loss.kind == "link" and links)
               or (loss.kind == "comment" and _take(comments, loss.what))]
    still = [loss for loss in gone if not any(loss is d for d in excused)]
    deleted = [loss for loss in excused if loss.kind not in shown]
    for named in shown.values():
        deleted += named
    return deleted, still


def _cut_of(kind: str) -> Callable[[_Mark], bool]:
    """Is a mark a `kind` note reference the proposal deletes?"""
    return lambda m: m.kind == kind and m.state == _DEL


def _links_shown(proposal: Parts, working: Parts, accepted: Parts,
                 rejected: Parts, read: dict[str, _Read]) -> bool:
    """Is every link the batch cut shown ACCEPTED at its own place?

    And are the links this reads as cut the ones the views say the
    accept removes, anchor for anchor? A link this stream cannot see
    would otherwise be excused without being asked about: a disagreement
    refuses.
    """
    def anchors(links: Counter[tuple[str, str]]) -> Counter[str]:
        return Counter(a for a, _label in links.elements())

    def named(mark: _Mark) -> str:
        return WORD_ANCHOR if word_minted(mark.key) else mark.key

    removed = anchors(_links(rejected)) - anchors(_links(accepted))
    placed = _places(proposal, working, lambda m: m.kind == "link"
                     and m.state != _SAME, read)
    cut = Counter(named(m) for m, _ok in placed if m.state == _DEL)
    put = Counter(named(m) for m, _ok in placed if m.state == _INS)
    return (bool(removed) and cut - put == removed
            and all(ok for m, ok in placed
                    if m.state == _DEL and named(m) in removed))


def _comments_cut(prev: Parts, proposal: Parts) -> Counter[str]:
    """The comments of the truth the proposal does not carry, by name."""
    return Counter(_comment_what(key) for key in (
        _comment_counts(prev) - _comment_counts(proposal)).elements())


def _take(budget: Counter[str], what: str) -> bool:
    """Spend one of `what` from `budget`, if there is one to spend."""
    if budget[what] <= 0:
        return False
    budget[what] -= 1
    return True


def _cut_named(kind: str, cut: set[str], rejected: Parts,
               gone: Sequence[Loss]) -> list[Loss]:
    """The `kind` notes the batch cut, named by THEIR words.

    `_lost_notes` names a lost note best-effort, by the texts the
    hand-back no longer has, and a note the batch REWORDED is one of
    those: excused under that name, the ledger recorded the reworded
    note as deleted and not the one that went (review of 2026-10-14).
    Here the cut is known by its reference, so it is named by its own
    definition — when there is one per loss. Otherwise the batch added
    notes as well, and the best-effort names stand.
    """
    part = FOOTNOTES if kind == "footnote" else ENDNOTES
    named = [Loss(kind, f.text) for f in _notes(rejected, part, kind)
             if f.id in cut]
    counted = [loss for loss in gone if loss.kind == kind]
    lost = sum(int(m.group(1)) if (m := re.match(r"(\d+) more, unnamed",
                                                 loss.what)) else 1
               for loss in counted)
    return sorted(named, key=lambda x: x.what) if len(named) == lost \
        else counted


def _unmet(accepted: tuple[str, ...], found: list[Loss]) -> list[str]:
    """Declared losses that did NOT happen.

    A stale exemption is worse than no exemption: it is a switched-off
    gate that reads as a switched-on one, and the next real loss goes
    through it silently. So naming something that is still present is
    itself a refusal.

    Matched by PREFIX, in both directions, because the refusal prints a
    truncated description and a reader copies what they were shown. A
    hatch that will not accept the message's own words is not a hatch —
    LI7 tried all three documented forms of the same footnote and every
    one came back "has NOT lost" while the refusal insisted it had
    (2026-08-15).
    """
    return [token for token in accepted
            if not any(_names(token, loss) for loss in found)]


def _names(token: str, loss: Loss) -> bool:
    """Does `token` identify `loss`? Prefixes count, either way round."""
    token = token.strip()
    for candidate in (loss.key, loss.what, f"{loss.kind}:{loss.what}"):
        if token == candidate or candidate.startswith(token) \
                or token.startswith(candidate):
            return True
    return False


def restored_bookmarks(baseline: Parts, clean: Parts,
                       built: Parts) -> list[str]:
    """Bookmarks the clean edit REMOVED and Compare put back.

    Word's Compare carries bookmarks over from the ORIGINAL side, so a
    deletion made in the clean copy is silently undone in the redline —
    and nothing in the counts shows it, because a bookmark is not
    tracked content. The orphan `Lari2023` survived two full rounds that
    way, and dropping the `Conley1999` and `Ingoglia2021` entries hit it
    again: `citations` on the built batch reported STALE BOOKMARK and
    REF WITHOUT CITE for entries that were no longer in the document.

    Three sides are needed, and the BASELINE is the one that makes the
    answer mean something: "in the build, not in the clean edit" also
    describes a name Word MINTED during the compare, and reporting that
    as the author's deletion sends them looking for an edit they never
    made. Only a name the baseline already carried is one the clean edit
    can have removed.

    And the build is read ACCEPTED (review of 2026-10-14). A bookmark
    round words the clean edit deleted sits round a ``w:del`` in the
    redline, and accepting drops it with them, as Word does
    (2026-10-12). Read off the raw redline, it was reported here and
    the author told to delete it by hand after the promote — which
    removes a back-link target from a deletion they can still REJECT.
    """
    return sorted((_bookmarks(baseline)
                   & _bookmarks(tracked.accepted_view(built)))
                  - _bookmarks(clean))


#: A footnote Compare emitted as one insertion with nothing to delete.
#: The shape of a note definition is `_xml`'s to state.
_MOVED_NOTE_RE = NOTE_DEF_RE[FOOTNOTES]


def moved_footnotes(parts: Parts,
                    baseline: Parts) -> list[int]:
    """Footnote ids whose whole body Compare wrapped in ``w:ins``.

    When a footnote's REFERENCE moves — same note, new position in the
    text — Word's Compare treats the note as brand new: its body is one
    insertion with **no matching deletion**. Accepting is right;
    rejecting empties the footnote, so a batch carrying one cannot pass
    gate 5 and the reason is invisible in the counts (Parental Style
    2026-08-10, footnote 2 re-anchored onto a new opening sentence).

    A footnote that carries insertions AND deletions is an ordinary
    edit; one that is new in this batch is a genuinely new note. So the
    shape is: insertions, no deletions, and the id already had text in
    the baseline.
    """
    was = {int(m.group(1)): visible_text(m.group(2))
           for m in _MOVED_NOTE_RE.finditer(
               baseline.get(FOOTNOTES, b"").decode("utf-8"))}
    out: list[int] = []
    for m in _MOVED_NOTE_RE.finditer(
            parts.get(FOOTNOTES, b"").decode("utf-8")):
        nid, body = int(m.group(1)), m.group(2)
        if nid < 1 or not was.get(nid, "").strip():
            continue                    # separators, and notes that are new
        # Either name in any spelling: asked for `<w:ins ` and `<w:del `,
        # an insertion whose name a tab or a newline ended was none.
        if re.search(r"<w:ins(?=[\s/>])", body) \
                and not re.search(r"<w:del(?=[\s/>])", body):
            out.append(nid)
    return out


def emptied_footnotes(rejected: Parts,
                      baseline: Parts,
                      candidates: Sequence[int]) -> list[int]:
    """Of `candidates`, the notes reject-all REALLY empties.

    :func:`moved_footnotes` finds a shape — a definition Compare emitted
    as one insertion with no matching deletion — and that shape was
    reported as though it were the outcome: *"rejecting empties the
    note, so gate 5 will fail on it."* It is not the outcome. The shape
    is necessary and not sufficient, and the reject-all layer beside it
    already holds the answer.

    Measured twice on Aging_Well, both times contradicted two lines
    later by ``'footnotes': True`` in the same run. 2026-09-03,
    footnote 2, when a batch ADDED a note and pushed the later
    definitions down; 2026-09-07 (R108), footnote 12, when no note was
    added at all — a task deleted a sentence from the paragraph
    carrying reference 12, Compare re-emitted the definition, reference
    order was ``2..13`` before and after, and reject-all restored the
    note byte for byte. Printed beside a genuine LINKS mismatch, the
    warning reads as a second blocking finding.

    So: reject, and compare the note's own words against the baseline's.
    What comes back is the condition the message describes — a
    definition rejecting would empty — and nothing else.
    """
    def words(parts: Parts) -> dict[int, str]:
        return {int(m.group(1)): visible_text(m.group(2)).strip()
                for m in _MOVED_NOTE_RE.finditer(
                    parts.get(FOOTNOTES, b"").decode("utf-8"))}

    was, now = words(baseline), words(rejected)
    return [nid for nid in candidates if now.get(nid, "") != was.get(nid, "")]


def _shown(text: str, *, limit: int = 12) -> str:
    """A run of characters, with its code points when it is short.

    The code points are the point: a hyphen-minus and a MINUS SIGN print
    identically in a terminal at 10pt, and telling them apart is the
    whole finding.
    """
    cut = text[:limit]
    tail = "..." if len(text) > limit else ""
    points = (" " + " ".join(f"U+{ord(c):04X}" for c in cut)
              if 0 < len(cut) <= 4 else "")
    return f"{cut + tail!r}{points}"


def glyph_runs(before: str, after: str, *, limit: int = 6,
               context: int = 24) -> list[str]:
    """Where two rendered-character streams differ, in reading order.

    The glyph gate compares two streams tens of thousands of characters
    long and answers with one boolean, which tells its reader only that
    SOMETHING moved. On AFI the answer was two characters — a minus sign
    Word's Compare had rewritten as a hyphen inside an equation — and
    finding them took a bespoke difflib script over private imports,
    three builds after the gate first went red.

    `limit` runs, because a batch that really did lose a paragraph would
    otherwise print the paragraph; the count of the rest is kept.
    """
    if before == after:
        return []
    out: list[str] = []
    blocks = SequenceMatcher(None, before, after,
                             autojunk=False).get_opcodes()
    changed = [op for op in blocks if op[0] != "equal"]
    for _tag, i1, i2, j1, j2 in changed[:limit]:
        lead = before[max(0, i1 - context):i1].replace("\n", " ")
        out.append(f"at {i1}: {_shown(before[i1:i2])} -> "
                   f"{_shown(after[j1:j2])}   after ...{lead}")
    if len(changed) > limit:
        out.append(f"... and {len(changed) - limit} more run(s)")
    return out
