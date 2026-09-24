r"""What a redline must reproduce — the XML side of :mod:`docxkit.tracked`.

Split out of ``tracked.py`` on 2026-09-11; import from
:mod:`docxkit.tracked`, which re-exports every name here. Nothing in
this file opens Word: it reads a package the build already has and
answers the questions the build refuses on — does rejecting everything
give back the original (:func:`untracked`), does accepting everything
give back the clean copy (:func:`unaccepted`, :func:`accepted_losses`,
:func:`accepted_math`), what did Compare drop (:func:`compare_collateral`),
and what does the package hold (:func:`package_counts`,
:func:`structure_counts`). That is why a paper driving `tracked.build`
directly is gated by the same computation the protocol gates on — the
one copy is here, and `revision._validate` imports it too.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # lxml is imported lazily in `_root`; named here so the stubs see
    # every walk over what it returns.
    from lxml.etree import _Element

from . import footnotes as _footnotes
from ._xml import (
    BOOKMARK_NAME_RE,
    COMMENT_ID_RE,
    COMMENTS,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    TEXT_PARTS,
    Parts,
    internal_links,
    text_parts,
    visible_text,
    word_minted,
)
from .equations import OMATH_RE
from .hygiene import CARRIED_PROPERTIES
from .package import core_property, regenerated_by_word
from .revisions import accept as _accept
from .revisions import reject as _reject
from .revisions import revision_elements

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _anchors(parts: Parts) -> tuple[set[str], set[str]]:
    """Every AUTHORED bookmark name and internal link target in a package.

    Word's own — `_Ref…`, `_Toc…`, `_Hlk…` — are left out on both sides,
    because Compare re-mints them: comparing those by name reports a
    bookmark dropped and another gained on every single build, and
    `accepted_losses` is a gate `build` REFUSES on. It would fail every
    paper that uses Insert ▸ Cross-reference, for doing nothing.
    """
    names: set[str] = set()
    targets: set[str] = set()
    for name, blob in parts.items():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        xml = blob.decode("utf-8", "replace")
        names |= {n for n in BOOKMARK_NAME_RE.findall(xml)
                  if not word_minted(n)}
        targets |= {a for a, _ in internal_links(xml) if not word_minted(a)}
    return names, targets


def compare_collateral(revised: Parts,
                       redline: Parts) -> list[str]:
    """What Word's Compare removed on the way from `revised` to `redline`.

    Compare rebuilds the document rather than annotating it, and what it
    declines to carry over it drops in silence. Three kinds turned up on
    ONE manuscript in one day, none of them visible in any text diff:

    * a bookmark — LI7's ``OECD2021txt``, whose start had no matching
      end, so Word discarded it and the entry's back-link pointed at
      nothing;
    * a hyperlink — the link to ``Hadiyana2021`` simply absent, 162
      links in and 161 out;
    * whole PARTS — ``word/header1.xml`` and three customXml items.

    Every one was found afterwards, by hand, because the build reported
    revisions and comments and nothing else. This is advisory and does
    NOT fail a build: Word legitimately drops an empty header and the
    customXml a template left behind, and a redline nobody can produce
    is worse than one with a note on it. But it must be SAID, because
    the alternative is finding it in the deliverable.

    **A part Word REGENERATES is not a part that was lost**, and mixing
    the two is how a real loss goes unread: the same "part dropped" line
    was printed for ``docProps/app.xml``, ``core.xml`` and ``custom.xml``
    — which Word rewrites on every save and nobody needs to care about —
    and for the customXml data store, which nothing puts back. Those are
    named separately and first, because a signal buried in ignorable
    noise is not a signal.

    **But "regenerated" is a claim about the PART, not about what was in
    it.** Word rewrites ``docProps/core.xml`` with only
    ``lastModifiedBy``/``revision``/``created``/``modified``: the part is
    present, the same size class, and every property the document
    actually carried — ``dc:title``, ``dc:creator``, ``dc:subject``,
    ``cp:keywords`` — is gone. LI7's ``dc:title`` was set deliberately in
    a batch of its own on 2026-08-08 and was missing for four days
    afterwards, twice, unnoticed: metadata is not tracked-changeable, so
    there is no revision for an author to reject and no text, link or
    format layer looks at ``docProps``. So the properties are compared
    by VALUE here, and :func:`docxkit.hygiene.carry_properties` puts
    them back in :func:`build` before this runs — what survives to be
    reported is what the carry could not reach.
    """
    lost = sorted(set(revised) - set(redline))
    notes = [f"part LOST: {p} — nothing regenerates this; it is gone from "
             f"the redline unless you put it back"
             for p in lost if not regenerated_by_word(p)]
    notes += [f"part dropped: {p} (Word regenerates it on save)"
              for p in lost if regenerated_by_word(p)]
    was_names, was_targets = _anchors(revised)
    now_names, now_targets = _anchors(redline)
    notes += [f"bookmark dropped: {b}"
              for b in sorted(was_names - now_names)]
    notes += [f"link dropped: -> {t}"
              for t in sorted(was_targets - now_targets)]
    notes += [f"property LOST: {tag} = {was!r} — the part is there and "
              f"the value is not; nothing else in this build looks at "
              f"docProps"
              for tag in CARRIED_PROPERTIES
              if (was := core_property(revised, tag))
              and not core_property(redline, tag)]
    return notes


def accepted_losses(revised: Parts,
                    accepted: Parts) -> list[str]:
    """Anchors the clean copy has that ACCEPTING the redline does not.

    The gap between the two checks that already exist.
    :func:`compare_collateral` compares the clean copy with the redline
    AS BUILT, so a link that survives into the redline inside a deletion
    is present there and gone the moment the author accepts;
    :func:`unaccepted` compares the accepted view with the clean copy by
    paragraph TEXT, and a bookmark or a hyperlink carries no text at
    all. A batch that moved four captions passed both while all four of
    their hyperlinks had been stripped (backlog S1, AFI 2026-08-19).

    The accepted view is the deliverable — the document the author
    reads — so this is not advisory: `build` refuses on it under
    `accept_check`, like the text comparison beside it.

    Link targets are counted by ANCHOR through :func:`internal_links`,
    which reads the element form and the field form alike, so Compare
    re-representing one as the other is not a loss and does not report
    as one.
    """
    was_names, was_targets = _anchors(revised)
    now_names, now_targets = _anchors(accepted)
    return ([f"bookmark LOST on accept: {b}"
             for b in sorted(was_names - now_names)]
            + [f"link LOST on accept: -> {t}"
               for t in sorted(was_targets - now_targets)])


def _math_texts(parts: Parts) -> list[str]:
    """Every equation's rendered characters, in document order."""
    return [visible_text(m.group(0))
            for _name, xml in text_parts(parts)
            for m in OMATH_RE.finditer(xml)]


#: How wide a quoted equation may be before the difference in it is
#: impossible to spot. The two strings in this refusal are near-
#: identical by construction — that is what makes it a glyph problem —
#: so the reader is being asked to diff them by eye.
_EQ_QUOTE = 60


def _first_difference(was: str, now: str) -> str:
    """Where two near-identical strings part, by CODEPOINT.

    The refusal below quotes both forms, which is genuinely useful and
    is how the U+2032 gap in `MATH_DOWNGRADES` was found at all. What it
    could not say is WHICH CHARACTER differs. PRIME and APOSTROPHE are
    the same handful of pixels at a terminal's font size, and so are
    MINUS SIGN and HYPHEN-MINUS, the pair this toolkit hits most —
    which is also why the two are named here rather than shown, since
    a docstring is read in the same font as the refusal. Twenty minutes
    to diagnose what a codepoint answers in ten seconds (Aging_Well,
    2026-08-24).
    """
    import unicodedata
    for i, (a, b) in enumerate(zip(was, now, strict=False)):
        if a == b:
            continue
        return (f" — differs at char {i}: {a!r} U+{ord(a):04X} "
                f"({unicodedata.name(a, 'unnamed')}) vs {b!r} "
                f"U+{ord(b):04X} ({unicodedata.name(b, 'unnamed')})")
    if len(was) != len(now):            # one is a prefix of the other
        longer, at = (was, len(now)) if len(was) > len(now) else (now,
                                                                 len(was))
        extra = longer[at]
        return (f" — one is longer: {extra!r} U+{ord(extra):04X} "
                f"({unicodedata.name(extra, 'unnamed')}) at char {at}")
    return ""


def accepted_math(revised: Parts,
                  accepted: Parts) -> list[str]:
    """Equations the ACCEPTED view does not reproduce from the clean copy.

    Word's Compare does not treat an inline ``m:oMath`` as a unit. It
    diffs INSIDE it at character level, and on AFI (2026-08-19) it
    matched the common prefix ``-0.`` of ``-0.20`` and ``-0.398`` and
    emitted the rest as an insertion BESIDE the old digits. Accepting
    then reads ``-0.20398``: a number nobody wrote, in the deliverable,
    as though the author had asked for it.

    Every other check is blind to it by construction. :func:`unaccepted`
    compares ``w:t`` and an equation's characters are ``m:t`` — that
    reading is deliberate, and :func:`_paras` says why. The reject view
    is CORRECT here (it restores ``-0.20``), so the reject gate passes.
    The counts do not move. The equation still renders.

    So the question this asks is the narrow one nothing else does: after
    accepting, does every equation say what the clean copy says? Run
    after :func:`docxkit.hygiene.restore_math_glyphs`, so the minus sign
    Compare flattens is not reported as a corruption twice over.
    """
    was, now = _math_texts(revised), _math_texts(accepted)
    if len(was) != len(now):
        return [(f"the clean copy has {len(was)} equation(s) and "
                 f"accepting the redline gives {len(now)}")]
    return [f"equation {i}: {w[:_EQ_QUOTE]!r} in the clean copy, "
            f"{n[:_EQ_QUOTE]!r} accepted{_first_difference(w, n)}"
            for i, (w, n) in enumerate(zip(was, now, strict=True), 1)
            if w != n]


def _root(parts: Parts, name: str = DOCUMENT) -> _Element | None:
    from lxml import etree

    blob = parts.get(name)
    return etree.fromstring(blob) if blob else None


def _paras(root: _Element | None) -> list[str]:
    """Every paragraph's ``w:t`` text, in order, empties included.

    ``w:t`` ONLY, and that is a decision rather than an oversight: this
    reading is what makes the reject-all gate blind to an equation whose
    glyphs changed — an accepted math revision legitimately leaves the
    revised equation behind — while it still sees every word of prose
    the same accept took with it. The empties stay so ``¶n`` counts the
    paragraph a reader would count.
    """
    if root is None:
        return []
    return ["".join((t.text or "") for t in p.iter(W + "t"))
            for p in root.iter(W + "p")]


def _simulate(parts: Parts, how: Callable[[str], str]) -> Parts:
    """XML-level accept/reject of every text-bearing part.

    Then the one thing a part-by-part walk cannot do: a note's reference
    and its definition are one object to Word and two parts to us. A
    revision that deletes a footnote empties the definition here and
    removes the reference there, and Word's own accept removes both — so
    the shell left behind is an artifact of simulating, not a difference
    between the documents. Prune it, or every such revision reads as a
    paragraph the accept failed to reproduce, quoted as `'' vs ''`
    (Aging_Well, 2026-08-31; the same shape on the reject side for a
    note the batch ADDS). Shells only: an unreferenced definition with
    words in it is a lost footnote, and it stays here to be reported.
    """
    out = dict(parts)
    for name in TEXT_PARTS:
        if name in out:
            out[name] = how(out[name].decode("utf-8")).encode("utf-8")
    _footnotes.prune_orphans(out)
    return out


@dataclass(frozen=True)
class Untracked:
    """A paragraph the batch changed with NO revision mark on it."""

    part: str               # "body", "footnotes" or "endnotes"
    index: int              # paragraph index in the rejected view, 0-based
    baseline: str           # what the baseline says there
    batch: str              # what rejecting everything leaves

    def __str__(self) -> str:
        where = f"{self.part} ¶{self.index + 1}"
        return (f"{where}: baseline {self.baseline[:70]!r}\n"
                f"{' ' * len(where)}  batch    {self.batch[:70]!r}")


@dataclass(frozen=True)
class Unaccepted:
    """A paragraph accept-all does NOT reproduce from the clean copy."""

    part: str               # "body", "footnotes" or "endnotes"
    index: int              # paragraph index in the accepted view, 0-based
    intended: str           # what the revised document says there
    accepted: str           # what accepting everything leaves

    def __str__(self) -> str:
        where = f"{self.part} ¶{self.index + 1}"
        return (f"{where}: intended {self.intended[:70]!r}\n"
                f"{' ' * len(where)}  accepted {self.accepted[:70]!r}")


#: What each simulated part is CALLED in a finding — "body ¶12". Keyed
#: rather than zipped: `_mismatched_paras` walks `TEXT_PARTS`, and a
#: part added there without a name here fails loudly in the gate's own
#: tests instead of being reported under its neighbour's label.
_PART_LABELS = {DOCUMENT: "body", FOOTNOTES: "footnotes",
               ENDNOTES: "endnotes"}


def _mismatched_paras[R](got: Parts, want: Parts,
                         make: Callable[[str, int, str, str], R], limit: int,
                         fold: Callable[[str], str] | None = None) -> list[R]:
    """Paragraph-by-paragraph differences between two simulated views.

    One walk for both gates: the reject side compares against the
    baseline and the accept side against the clean copy, and the only
    thing that differs is which record says so — and, on the accept
    side, whether runs of whitespace count (see :func:`unaccepted`).
    """
    keep = fold or (lambda t: t)
    out: list[R] = []
    # Every part `_simulate` accepted or rejected, keyed by part name so
    # a fourth one cannot arrive unlabelled — and for the reason
    # `revision.TEXT_PARTS` gives beside its own list: a gate that reads
    # the body and the footnotes calls a mangled ENDNOTE a clean build,
    # and endnotes are where several journals put the whole apparatus.
    for name in TEXT_PARTS:
        label = _PART_LABELS[name]
        mine = [keep(t) for t in _paras(_root(got, name))]
        theirs = [keep(t) for t in _paras(_root(want, name))]
        for tag, i1, i2, j1, j2 in SequenceMatcher(
                None, theirs, mine, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            for k in range(max(i2 - i1, j2 - j1)):
                out.append(make(
                    label, j1 + k,
                    theirs[i1 + k] if i1 + k < i2 else "",
                    mine[j1 + k] if j1 + k < j2 else ""))
                if len(out) >= limit:
                    return out
    return out


def unaccepted(parts: Parts, revised: Parts, *,
               limit: int = 8,
               fold_space: bool = False) -> list[Unaccepted]:
    """Paragraphs where accept-all does NOT reproduce `revised`.

    The mirror of :func:`untracked`, and it covers what that cannot by
    construction. Rejecting removes every insertion, so a defect INSIDE
    an insertion is deleted before the reject comparison happens and
    cannot appear there however wrong it is; the tag counts do not move
    either, since a mangled run is still one paragraph in one cell. The
    build then reports success, `reject-all == baseline` passes BY NAME,
    and the corruption ships in the ACCEPTED document — which is the one
    the author reads.

    That Word's Compare alters content while deriving a redline is not
    hypothetical: `hygiene.restore_math_glyphs` exists because it
    flattens U+2212 to an ASCII hyphen (AFI: 2 in the baseline, 0 in the
    build), and `compare_collateral` exists because it drops bookmarks,
    links and whole parts (LI7). Both were found by hand, after the
    fact.

    `fold_space` collapses runs of whitespace before comparing, which is
    right — and necessary — for a build made with ``whitespace=False``:
    Word then treats respacing as no revision at all, so accepting
    leaves the ORIGINAL's spacing where the clean copy had changed it.
    Every word-level difference is still seen. `build` passes it for
    exactly that case and compares exactly otherwise.
    """
    return _mismatched_paras(
        _simulate(parts, _accept), revised, Unaccepted, limit,
        (lambda t: " ".join(t.split())) if fold_space else None)


def untracked(parts: Parts, baseline: Parts, *,
              limit: int = 8) -> list[Untracked]:
    """Paragraphs where reject-all does NOT reproduce the baseline.

    The batch changed them and no revision covers the change, so the
    author cannot refuse it — and the headline revision count says
    nothing about it. Parental Style shipped a merged, rewritten
    math-bearing paragraph this way while its batch read "7 revisions, 6
    of them in the body": all six were two word-swaps in an unrelated
    paragraph, and the central edit had no marks at all. LI7 shipped 315
    revisions' worth the same way, from an over-eager math accept.

    The same computation gate 5 already performs, named and returned
    rather than reduced to a boolean — which is what made the failure
    cost a bespoke difflib script to diagnose. Three callers: :func:`build`
    REFUSES to publish on it, `revision.build` reports it before the
    handback (it turns the refusal off, and says why), and gate 5 says it
    after. It lives here, in the module that MAKES redlines, so that a
    paper driving `build` directly is gated too — LI7 was, and the check
    it needed sat one layer up, in a protocol it does not use.
    """
    return _mismatched_paras(_simulate(parts, _reject), baseline,
                             Untracked, limit)


def package_counts(parts: Parts) -> dict[str, int]:
    """What the PACKAGE holds: insertions, deletions, comments.

    Half of the "did Word repair this file?" check, and the half that
    actually detects the damage — Word's side is just a number it hands
    back. Pure, so it can be tested without Word, which is why it lives
    here instead of inline in :func:`verify` and :func:`build`, where it
    had been written twice.
    """
    # EVERY text-bearing part, not just the body. A batch that edits only a
    # footnote used to report "0 pending revisions" — the number this project
    # reads to decide whether a document is at truth — while the footnote
    # carried three. Word counts them; this must agree with Word.
    text_xml = "".join(xml for _name, xml in text_parts(parts))
    com_xml = parts.get(COMMENTS, b"").decode("utf-8")
    return {
        # The name, then anything that ends it: counted as `<w:ins ` with
        # a space, an insertion whose name a tab or a newline ended was
        # counted zero (2026-09-17).
        "insertions": len(re.findall(r"<w:ins(?=[\s/>])", text_xml)),
        "deletions": len(re.findall(r"<w:del(?=[\s/>])", text_xml)),
        # not count("<w:comment w:id=") — attribute order is not
        # meaningful in XML, and the id-second form counted as zero
        "comments": len(COMMENT_ID_RE.findall(com_xml)),
        # EVERY KIND, not just ins/del. A batch of nothing but footnote
        # `w:rPrChange` reported "revisions: 0" and read as a Compare
        # that had failed — the documented shape of the math refusal —
        # while carrying 25. Same lesson as the parts above, one axis
        # over: the two counts that decide whether a file is settled must
        # know the same seven kinds `revision.state` does.
        "revisions": len(revision_elements(text_xml)),
    }


def revisions_by_part(parts: Parts) -> dict[str, int]:
    """Revision elements per text-bearing part; empty parts omitted.

    :func:`package_counts` gives the total and Word gives the body's,
    and the two disagree for TWO different reasons — revisions outside
    the main story, and Word GROUPING adjacent ones inside it. Neither
    number can tell them apart, so a build that guessed sent a reader to
    inspect a footnotes part holding nothing (AFI r4 batch 13: 33 and
    15, and `footnotes.xml` was empty).
    """
    return {name: n for name, xml in text_parts(parts)
            if (n := len(revision_elements(xml)))}


def _revision_gap(parts: Parts, body: int, total: int) -> str:
    """Why Word's body count and the package's total differ, in full.

    Both causes are named, and only when they are actually present. A
    message that attributes the whole gap to footnotes is right often
    enough to be trusted, which is what makes being wrong about it
    expensive.
    """
    per_part = revisions_by_part(parts)
    lines = [(f"Word counts {body} in the body; the package holds {total} "
              f"revision elements")]
    lines += [(f"{n} of them are in {name}, where Word's own count and "
               f"Review > Next do not go")
              for name, n in per_part.items() if name != DOCUMENT]
    grouped = per_part.get(DOCUMENT, 0) - body
    if grouped > 0:
        lines.append(
            f"the remaining {grouped} are in {DOCUMENT} too: Word GROUPS "
            f"adjacent revisions, so one thing to accept can be several "
            f"elements")
    return "\n".join(f"  ({line})" for line in lines)


#: What a docx carries that a reader never reads AS CHARACTERS.
#:
#: `reject-all == baseline` — the gate that proves a batch is fully
#: reviewable — compared paragraph text, the glyph stream, footnotes and
#: links, and passed three different losses on one manuscript round (DSI,
#: 2026-08-19): a table DUPLICATED by a move (27 -> 28, in the accepted
#: and the rejected view alike), a moved paragraph's three citation
#: bookmarks dropped on reject (127 -> 125), and a destroyed section
#: break. None of them is a character, so none of them was compared.
#:
#: `w:hyperlink` is deliberately NOT here: Word rewrites a caption's
#: HYPERLINK FIELD into an element on an ordinary edit, the count moves,
#: and nothing is lost — `_links` already compares links by (anchor,
#: label) across both forms, which is the comparison that means
#: something.
STRUCTURE_TAGS = ("tbl", "tr", "tc", "bookmarkStart", "sectPr",
                  "drawing", "footnoteReference")


def structure_counts(parts: Parts) -> dict[str, int]:
    """Every glyph-less carrier in the package, counted.

    The sibling of :func:`package_counts`, and pure for the same reason:
    the check that needs it runs before Word is asked anything, and five
    paper scripts had copied a `counts()` helper to do this by hand.

    EVERY text-bearing part, as everywhere else here — a section break
    lives in the body, a bookmark can sit in a footnote, and a batch that
    edits only a note must not read as a batch that changed nothing.
    """
    text_xml = "".join(xml for _name, xml in text_parts(parts))
    # `<w:tr\b` does not match `<w:trPr` — the boundary is between two
    # word characters, so there is none — and the same holds for tbl/tc.
    return {tag: len(re.findall(rf"<w:{tag}\b", text_xml))
            for tag in STRUCTURE_TAGS}


def structure_diff(was: dict[str, int], now: dict[str, int], *,
                   skip: tuple[str, ...] = ()) -> list[str]:
    """``"tbl: 27 -> 28"`` for every count that moved, in tag order.

    `skip` leaves tags out — the gates pass ``("bookmarkStart",)`` and
    judge bookmarks by name instead, in :func:`bookmark_changes`.
    """
    return [f"{tag}: {was.get(tag, 0)} -> {now.get(tag, 0)}"
            for tag in STRUCTURE_TAGS
            if tag not in skip and was.get(tag, 0) != now.get(tag, 0)]


def _bookmark_names(parts: Parts) -> Counter[str]:
    return Counter(name for _part, xml in text_parts(parts)
                   for name in BOOKMARK_NAME_RE.findall(xml))


def bookmark_changes(base: Parts, view: Parts, carried: Parts) -> list[str]:
    """What `view` does to `base`'s bookmarks that `carried` does not explain.

    A bookmark is not revisable. Compare carries the clean copy's bookmark
    ADDITIONS into both views and its DELETIONS into neither, so counting
    them refused every batch that linked a citation: Misconceptions
    (2026-09-24) rejected to 165 bookmarks against the original's 121, the
    44 extra being exactly the ones the clean copy added (`link_all` makes
    two per work) — and a batch that deleted a reference entry accepted to
    two MORE than the clean copy, `McNemar1947` and its `txt`. With
    `reject_check` the only switch, the text gate went off with it.

    So by NAME, and each view against the document it must reproduce:

    * the REJECTED view against the original, where anything gained must
      be an addition of the clean copy — ``carried`` is the clean copy (or
      the accepted view, which adds the same names to the original);
    * the ACCEPTED view against the clean copy, where anything gained must
      be a deletion — ``carried`` is the original.

    Anything LOST is refused on either side: that is the DSI class, three
    citation bookmarks a move dropped on reject. Word's own `_Ref`/`_Toc`
    /`_Hlk` names are re-minted on every save (:func:`_xml.word_minted`),
    so they are judged by COUNT, with the same allowance.
    """
    was, now, other = (_bookmark_names(p) for p in (base, view, carried))
    out: list[str] = []
    named = [n for n in (was | now | other) if not word_minted(n)]
    lost = sorted(n for n in named if now[n] < was[n])
    gained = sorted(n for n in named
                    if now[n] > was[n] + max(0, other[n] - was[n]))
    if lost:
        out.append(f"bookmarkStart: lost {', '.join(map(repr, lost))}")
    if gained:
        out.append(f"bookmarkStart: gained {', '.join(map(repr, gained))}, "
                   f"which the other document does not explain")

    def minted(names: Counter[str]) -> int:
        return sum(k for n, k in names.items() if word_minted(n))

    b, v, c = minted(was), minted(now), minted(other)
    if not b <= v <= b + max(0, c - b):
        out.append(f"bookmarkStart (Word's own _ names): {b} -> {v}")
    return out
