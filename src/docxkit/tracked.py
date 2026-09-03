r"""Building a tracked-changes deliverable from two clean documents.

The journal wants a redline: the original, the revision, and — when the
paper works that way — a comment on every change saying why. The reliable
way to produce one is Word's own ``CompareDocuments``; hand-authored
``w:ins``/``w:del`` markup has failed to open in Word repeatedly across
these papers, so it is not attempted here.

Generating the redline from the two clean documents also means the two
deliverables cannot disagree: accepting every revision reproduces the
revised document by construction. Hand-authoring does not give that, and
on the Life Expectancy paper the tracked and clean files had silently
drifted apart in three paragraphs.

The pipeline:

1. Word compares the two documents (seconds).
2. The MATH revisions are resolved — accepted, and commented first if
   the paper annotates. This also leaves behind Word's own comment
   scaffold for step 4. Only revisions CONTAINED in an equation: see
   :func:`_accept_math_via_equations` for what accepting a merely
   overlapping one costs.
3. The package is extracted as Flat OPC, bypassing Word's save path.
4. Every remaining revision is commented in XML (:mod:`docxkit.comments`).
5. The result is linted, and REJECT-ALL must reproduce the original —
   a redline whose changes the author cannot refuse is the one failure
   a redline exists to prevent (:func:`untracked`).
6. The result is reopened in Word: it must read back exactly the comment
   count the package holds, or Word repaired it on open.

The premise the math step was built on — *Word cannot serialize a
compare result containing tracked math at all* — is not general. On LI7
(2026-08-15) both ``SaveAs2`` and Flat OPC serialized 1870 revisions
with the math left tracked, and both round-tripped exactly. Hence
``resolve_math=False``: a paper that has measured its own case can keep
the math tracked and lose nothing.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, NamedTuple

from . import comments as _comments
from . import footnotes as _footnotes
from . import guard as _guard
from . import hygiene as _hygiene
from . import word as _word
from ._xml import (
    BOOKMARK_NAME_RE,
    COMMENT_ID_RE,
    COMMENTS,
    DOCUMENT,
    ENDNOTES,
    FOOTNOTES,
    TEXT_PARTS,
    internal_links,
    text_parts,
    visible_text,
    word_minted,
)
from .comments import RevisionContext
from .equations import OMATH_RE
from .errors import PackageError
from .hygiene import CARRIED_PROPERTIES
from .lint import lint_parts
from .package import (
    USER_PROPERTIES,
    core_property,
    read_parts,
    regenerated_by_word,
    write_docx,
)
from .revisions import accept as _accept
from .revisions import reject as _reject
from .revisions import revision_elements

# Bound directly, NOT reached through `_word`: tests replace that
# module attribute with a COM fake, and a fake has no reason to
# carry a suppression helper. The seam is for Word, not for this.
from .word import _suppress_com

__all__ = [
    "CARRIED_PARTS",
    "STRUCTURE_TAGS",
    "BuildReport",
    "MathOutcome",
    "PackageError",
    "Unaccepted",
    "Untracked",
    "accepted_losses",
    "accepted_math",
    "build",
    "compare_collateral",
    "package_counts",
    "revisions_by_part",
    "structure_counts",
    "structure_diff",
    "unaccepted",
    "untracked",
    "verify",
]

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: What :func:`build` copies back from the revised input when Word's
#: Compare declines to carry it: the ``customXml/`` data store, dropped
#: on every single rebuild, and the user-defined properties, which on a
#: Bank manuscript are the sensitivity label. A paper whose Compare eats
#: something else says so once — see ``[batch] carry`` in paper.toml.
CARRIED_PARTS = (_hygiene.CUSTOM_XML, USER_PROPERTIES)



def _anchors(parts: dict[str, bytes]) -> tuple[set[str], set[str]]:
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


def compare_collateral(revised: dict[str, bytes],
                       redline: dict[str, bytes]) -> list[str]:
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


def accepted_losses(revised: dict[str, bytes],
                    accepted: dict[str, bytes]) -> list[str]:
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


def _math_texts(parts: dict[str, bytes]) -> list[str]:
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
    if len(was) != len(now):
        longer, at = (was, len(now)) if len(was) > len(now) else (now,
                                                                 len(was))
        extra = longer[at]
        return (f" — one is longer: {extra!r} U+{ord(extra):04X} "
                f"({unicodedata.name(extra, 'unnamed')}) at char {at}")
    return ""


def accepted_math(revised: dict[str, bytes],
                  accepted: dict[str, bytes]) -> list[str]:
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


#: How to build the file anyway — and the warning that goes with it.
#:
#: It used to say "Pass accept_check=False", which is a Python keyword
#: argument. The CLI's flags are `--allow-math-resolve`,
#: `--allow-stale-baseline`, `--keep-math`, `--allow-pending-baseline`
#: and `--force`, none of which is it, so a CLI reader had been told to
#: do something the CLI does not offer — and the honest workaround,
#: writing a throwaway script that imports `docxkit.revision`, is the
#: thing the CLI exists to avoid.
#:
#: The second sentence is the half worth keeping. Met 2026-08-29 on
#: Life_Expectancy, where the refusal was RIGHT — two unterminated
#: bookmarks Compare would have dropped — and the repair was to fix the
#: manuscript, not to bypass the gate.
_ACCEPT_ESCAPE = (
    "To build it anyway and look at it, call `tracked.build(..., "
    "accept_check=False)` from Python; the CLI has no flag for this on "
    "purpose. The refusal is usually right, and the repair is usually "
    "in the manuscript rather than in the switch.")


def _also_unaccepted(report: BuildReport) -> str:
    """The paragraphs, when the ANCHOR refusal fires ahead of them.

    An anchor does not go missing on its own: it goes with the words
    that carried it. On Aging_Well (2026-08-31) a scored move truncated
    a paragraph in the accepted view — a clause, a link and the sentence
    after it — and the build refused with `link LOST on accept: ->
    Ravallion2011`, which names the smallest visible symptom of it. The
    reader spends the round on the link.

    So when both findings are present, the anchor refusal carries the
    paragraphs too, and names the switch that fixed that case.
    """
    if not report.unaccepted:
        return ""
    listed = "\n  ".join(str(u) for u in report.unaccepted)
    return (f"\n{len(report.unaccepted)} paragraph(s) also differ, and they "
            f"are the finding to read first — an anchor goes missing with "
            f"the words that carried it:\n  {listed}\n"
            f"Word's move detection can truncate a paragraph it scored as "
            f"moved. If this round relocated a passage, rebuild with "
            f"moves=False (`revision build --no-moves`) before looking "
            f"anywhere else. ")


def _refuse_accept_side(report: BuildReport, revised: str, *,
                        math_only: bool = False) -> None:
    """Raise for whatever the ACCEPTED view does not reproduce.

    Three questions about one view, kept together because the answer to
    all three is the same: the accepted document is what the author
    reads, so a difference there is not a note to print and continue
    past. They are separate checks because each is blind to the others —
    the text comparison cannot see an anchor, the anchor comparison
    cannot see a number, and neither reads `m:t`.

    `math_only` runs the last of them alone, because the equations can
    only be judged after the glyph restore.
    """
    if not math_only and report.accepted_losses:
        listed = "\n  ".join(report.accepted_losses)
        raise PackageError(
            f"accepting every revision LOSES anchors the clean copy "
            f"has:\n  {listed}\n"
            f"A bookmark and a hyperlink carry no text, so the paragraph "
            f"comparison beside this one cannot see them go, and they "
            f"are present in the redline as built — inside a deletion, "
            f"until the author accepts it. " + _also_unaccepted(report)
            + _ACCEPT_ESCAPE)
    if not math_only and report.orphan_notes:
        listed = "\n  ".join(str(o) for o in report.orphan_notes)
        raise PackageError(
            f"accepting every revision leaves {len(report.orphan_notes)} "
            f"note definition(s) with nothing referencing them:\n  "
            f"{listed}\n"
            f"The marker was deleted and the words were not, so the note "
            f"is in the file and on no page. Delete the note in the CLEAN "
            f"copy — reference and definition together, which is what "
            f"Word does when you delete the marker — and rebuild. "
            + _ACCEPT_ESCAPE)
    if not math_only and report.unaccepted:
        listed = "\n  ".join(str(u) for u in report.unaccepted)
        raise PackageError(
            f"accepting every revision does NOT reproduce {revised} — "
            f"{len(report.unaccepted)} paragraph(s) differ, so the "
            f"deliverable the author reads is not the document this "
            f"redline was built from:\n  {listed}\n"
            f"Word rewriting content while it derives the redline is the "
            f"usual cause, and the reject-all gate cannot see it: "
            f"rejecting deletes the insertion the damage is inside. "
            + _ACCEPT_ESCAPE)
    if report.accepted_math:
        listed = "\n  ".join(report.accepted_math)
        raise PackageError(
            f"accepting every revision does not reproduce the EQUATIONS "
            f"of {revised}:\n  {listed}\n"
            f"Word's Compare diffs inside an inline m:oMath at character "
            f"level, so a changed number can come out as the old digits "
            f"with the new ones inserted beside them. Apply the math "
            f"edit to the built batch instead, or pass accept_check="
            f"False to build the file anyway and inspect it.")


def _root(parts: dict[str, bytes], name: str = DOCUMENT) -> Any | None:
    from lxml import etree

    blob = parts.get(name)
    return etree.fromstring(blob) if blob else None


def _paras(root: Any | None) -> list[str]:
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


def _simulate(parts: dict[str, bytes], how: Any) -> dict[str, bytes]:
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


def _mismatched_paras(got: dict[str, bytes], want: dict[str, bytes],
                      make: Any, limit: int,
                      fold: Callable[[str], str] | None = None) -> list[Any]:
    """Paragraph-by-paragraph differences between two simulated views.

    One walk for both gates: the reject side compares against the
    baseline and the accept side against the clean copy, and the only
    thing that differs is which record says so — and, on the accept
    side, whether runs of whitespace count (see :func:`unaccepted`).
    """
    keep = fold or (lambda t: t)
    out: list[Any] = []
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


def unaccepted(parts: dict[str, bytes], revised: dict[str, bytes], *,
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


def untracked(parts: dict[str, bytes], baseline: dict[str, bytes], *,
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


Classifier = Callable[[RevisionContext], str | None]


def package_counts(parts: dict[str, bytes]) -> dict[str, int]:
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
        "insertions": text_xml.count("<w:ins "),
        "deletions": text_xml.count("<w:del "),
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


def revisions_by_part(parts: dict[str, bytes]) -> dict[str, int]:
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


def _revision_gap(parts: dict[str, bytes], body: int, total: int) -> str:
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


def structure_counts(parts: dict[str, bytes]) -> dict[str, int]:
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


def structure_diff(was: dict[str, int], now: dict[str, int]) -> list[str]:
    """``"tbl: 27 -> 28"`` for every count that moved, in tag order."""
    return [f"{tag}: {was.get(tag, 0)} -> {now.get(tag, 0)}"
            for tag in STRUCTURE_TAGS if was.get(tag, 0) != now.get(tag, 0)]


def _bounded(deadline: float | None, doing: str) -> dict[str, Any]:
    """The keywords for `_word.session` — only when a ceiling is asked
    for, so a caller (or a fake) that knows no `deadline` is untouched."""
    return {"deadline": deadline, "doing": doing} if deadline else {}


def verify(path: str | Path, *,
           word_deadline: float | None = None) -> dict[str, Any]:
    """Open a document in Word and report what Word actually reads back.

    The check that matters for any tracked-changes file, however it was
    produced: Word silently "repairs" markup it dislikes, and the damage
    only shows up when the editor opens the deliverable.

    Returns the counts Word reports alongside the counts the package
    contains; when they disagree, Word altered the file on open.
    `word_deadline` bounds the session (see :func:`docxkit.word.session`).
    """
    path = Path(path)
    parts = read_parts(path)
    in_package = package_counts(parts)
    with _word.session(**_bounded(word_deadline, f"verifying {path.name}")) \
            as word, _word.open_doc(word, path) as opened:
        in_word = {
            "revisions": int(opened.Revisions.Count),
            "comments": int(opened.Comments.Count),
            "paragraphs": int(opened.Paragraphs.Count),
        }
    return {
        "path": str(path),
        "package": in_package,
        "word": in_word,
        "comments_match": in_word["comments"] == in_package["comments"],
    }


class BuildReport:
    """What a redline build did, and how long each phase took."""

    def __init__(self) -> None:
        #: Every pending revision the built package carries, of every
        #: kind and in every text-bearing part. Word's own
        #: `Revisions.Count` — which is what this used to hold — walks
        #: the MAIN STORY only, so a batch of 25 footnote formatting
        #: revisions reported 0 and read as a Compare that had failed.
        #: Kept beside it as `body_revisions`, labelled, because the two
        #: disagreeing is worth seeing rather than resolving silently.
        self.revisions = 0
        self.body_revisions = 0
        self.math_resolved = 0
        #: Revisions that TOUCH an equation and were left tracked because
        #: they are not of it. Accepting these is what cost LI7 315
        #: revisions — see :func:`_accept_math_via_equations`.
        self.math_kept = 0
        self.comments_added = 0
        self.unclassified = 0
        self.comments_total = 0
        self.verified_comments: int | None = None
        self.verified_revisions: int | None = None
        #: What Word refused to do. Every COM call here is wrapped in a
        #: suppression because one hostile revision must not abort a
        #: 1400-revision build — but suppressing SILENTLY let a
        #: half-finished build report success-shaped numbers, so what
        #: was swallowed is recorded and printed.
        self.suppressed: list[str] = []
        #: What Word's Compare removed rather than carried over — parts,
        #: bookmarks, links. See :func:`compare_collateral`. Advisory:
        #: some of it is legitimate tidying, and only a person can tell.
        self.dropped: list[str] = []
        #: Paragraphs a reject-all does not restore. Always computed, so
        #: the report carries the finding either way; NOT advisory when
        #: `reject_check` is on, which is the default — the build then
        #: refuses to publish while this is non-empty.
        self.unrejectable: list[Untracked] = []
        #: Paragraphs an accept-all does not reproduce from the CLEAN
        #: copy. Always computed, and not advisory while `accept_check`
        #: is on: a defect Compare baked into an insertion is invisible
        #: to `unrejectable`, because rejecting deletes the insertion
        #: before that comparison happens. See :func:`unaccepted`.
        self.unaccepted: list[Unaccepted] = []
        #: Counts of the glyph-less carriers — tables, rows, bookmarks,
        #: section breaks — that the built redline does not resolve back
        #: to the documents it came from. See :func:`structure_counts`.
        self.structure_diff: list[str] = []
        #: Equations the ACCEPTED view does not reproduce from the
        #: clean copy. Refused with `accept_check`. See
        #: :func:`accepted_math`.
        self.accepted_math: list[str] = []
        #: Bookmarks and internal links the CLEAN copy has and the
        #: ACCEPTED view does not. Refused with `accept_check`, because
        #: the accepted view is the deliverable. See
        #: :func:`accepted_losses`.
        self.accepted_losses: list[str] = []
        #: Note definitions the ACCEPTED view keeps with nothing left
        #: pointing at them, and words still in them: a footnote whose
        #: marker went and whose text stayed, which renders nowhere and
        #: reads as lost. The empty shells accepting leaves behind are
        #: pruned instead — see :func:`_simulate` and
        #: :func:`docxkit.footnotes.orphans`.
        self.orphan_notes: list[_footnotes.Orphan] = []
        #: Part-trees Compare dropped and the build put BACK — the
        #: customXml data store, by default. See
        #: :func:`docxkit.hygiene.restore_parts`.
        self.carried: list[str] = []
        #: Part-trees neither the redline NOR the clean copy still has,
        #: taken from the BASELINE. Named apart from `carried` because
        #: it is a different sentence: this build went back a version
        #: for these, and that is the one case where an author might
        #: want to look. See the note on the fallback in `build`.
        self.carried_from_baseline: list[str] = []
        #: Core properties Compare's regenerated ``docProps/core.xml``
        #: no longer carried, and the build copied back by VALUE. See
        #: :func:`docxkit.hygiene.carry_properties`.
        self.carried_properties: list[str] = []
        #: Math runs whose glyph Word flattened while rewriting the
        #: OMML, put back from what a source really spells. See
        #: :func:`docxkit.hygiene.restore_math_glyphs`.
        self.restored_glyphs: list[str] = []
        #: Comments Compare kept TWICE because both inputs carried them.
        #: See :func:`docxkit.hygiene.dedupe_comments`.
        self.deduped_comments: list[str] = []
        self.phases: list[tuple[str, float]] = []
        self._t0 = self._last = time.perf_counter()

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self.phases.append((label, now - self._last))
        self._last = now

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self._t0

    def format(self) -> str:
        lines = [f"  [{secs:6.1f}s] {label}" for label, secs in self.phases]
        lines.append(f"revisions {self.revisions}, comments "
                     f"{self.comments_total} ({self.unclassified} "
                     f"unclassified), {self.seconds:.0f}s total")
        if self.suppressed:
            lines.append(f"  {len(self.suppressed)} Word call(s) failed "
                         "and were skipped:")
            lines += [f"    - {note}" for note in self.suppressed[:10]]
            if len(self.suppressed) > 10:
                lines.append(f"    ... and {len(self.suppressed) - 10} more")
        if self.math_kept:
            lines.append(f"  {self.math_kept} revision(s) overlap an "
                         "equation without being of it, and stay tracked")
        if self.carried:
            lines.append(f"  carried back across the Compare: "
                         f"{', '.join(self.carried)}")
        if self.carried_from_baseline:
            lines.append(f"  the clean copy had lost these too, so they "
                         f"come from the BASELINE: "
                         f"{', '.join(self.carried_from_baseline)}")
        if self.carried_properties:
            lines.append(f"  properties carried back into core.xml: "
                         f"{', '.join(self.carried_properties)}")
        if self.dropped:
            lines.append(f"  Word's Compare dropped {len(self.dropped)} "
                         "thing(s) the revised copy had:")
            lines += [f"    - {note}" for note in self.dropped[:10]]
            if len(self.dropped) > 10:
                lines.append(f"    ... and {len(self.dropped) - 10} more")
        return "\n".join(lines)


class MathOutcome(NamedTuple):
    """What the math pass accepted, and what it deliberately left alone."""

    accepted: int
    kept: int = 0


def _resolve_math(doc: Any, classify: Classifier | None,
                  generic: str | None,
                  notes: list[str] | None = None) -> MathOutcome:
    """Comment (if the paper annotates) and accept the math revisions.

    Word's save path cannot always serialize a compare result containing
    tracked math, and where it cannot, these have to go. Commenting them
    is the only chance to explain an equation change, and it leaves the
    comment scaffold the XML pass clones.

    The two routes below look like duplicates and are NOT: they select
    different revisions. Walking the equations finds revisions in a math
    RANGE; asking each revision whether it contains math finds revisions
    that CONTAIN one. Substituting the first for the second on the AFI
    paper left 41 extra revisions un-accepted (291 annotated became 332),
    so each path keeps the scan it was verified with. The equation walk
    is much cheaper — ~15ms per equation against ~20ms per revision,
    which was 27s of a 1359-revision compare — and is used where no
    comments are needed and it was validated.
    """
    notes = [] if notes is None else notes
    if classify is None:
        return _accept_math_via_equations(doc, notes)
    return _comment_and_accept_math_revisions(doc, classify, generic, notes)


def _accept_math_via_equations(doc: Any,
                               notes: list[str] | None = None
                               ) -> MathOutcome:
    """Accept revisions CONTAINED in an equation, walking ``doc.OMaths``.

    CONTAINED, not overlapping, and the difference is the whole entry.
    A revision appears in an equation's ``Range.Revisions`` if it merely
    TOUCHES that range, and accepting one applies its ENTIRE span — so a
    long formatting or move revision that happens to run through an
    equation is applied whole, along with every revision inside it.

    **Measured on LI7, 2026-08-15**, one compare of the same pair: with
    the math kept tracked the package held 1870 revisions and reject-all
    reproduced the submitted paper 319/319; with the math "resolved" by
    the overlapping rule, thirteen ``Accept()`` calls left 1555 and
    reject-all FAILED on 35 units. The collateral reached the abstract,
    which contains no equation at all — its rejected text came back as
    "…in aging populations.  the theoretical foundation…", the words
    "The paper presents" simply gone and unrejectable. Nothing failed:
    the deliverable opened, the counts looked plausible, and only a
    reject-all diff against the baseline said otherwise. Hence
    :func:`untracked`, which now runs on every build.

    A revision left tracked is COUNTED and returned, not swallowed: the
    caller reports it, and if the save then refuses the math, the number
    is the first thing to look at.
    """
    notes = [] if notes is None else notes
    try:
        if not doc.OMaths.Count:
            return MathOutcome(0)
    except Exception as exc:
        notes.append(f"could not read doc.OMaths: {exc}")
        return MathOutcome(0)
    accepted = kept = 0
    for i in range(doc.OMaths.Count, 0, -1):   # backwards: accepting shifts
        try:
            math_range = doc.OMaths(i).Range
            revisions = math_range.Revisions
        except Exception as exc:
            notes.append(f"equation {i}: unreachable ({exc})")
            continue
        for j in range(revisions.Count, 0, -1):
            try:
                revision = revisions(j)
                # re-read per revision: accepting one inside the equation
                # shifts the range's own end, and a stale bound is a
                # bound that over-includes
                lo, hi = int(math_range.Start), int(math_range.End)
                span = (int(revision.Range.Start), int(revision.Range.End))
            except Exception as exc:
                notes.append(f"equation {i} revision {j}: "
                             f"could not be placed ({exc})")
                continue
            if not (lo <= span[0] and span[1] <= hi):
                kept += 1          # overlaps the equation; is not OF it
                continue
            try:
                revision.Accept()
                accepted += 1
            except Exception as exc:
                notes.append(f"equation {i} revision {j}: "
                             f"not accepted ({exc})")
    return MathOutcome(accepted, kept)


def _comment_and_accept_math_revisions(
        doc: Any, classify: Classifier, generic: str | None,
        notes: list[str] | None = None) -> MathOutcome:
    """Comment then accept each revision that CONTAINS math.

    Scans the revisions rather than the equations — see
    :func:`_resolve_math` for why the cheaper walk is not a substitute.

    This route selects a revision by what it CONTAINS, so a long one
    that runs through an equation is still applied whole, with the same
    collateral :func:`_accept_math_via_equations` documents. It is not
    narrowed here because the selection was verified revision by
    revision on AFI and narrowing it blind would change a shipped
    deliverable's shape; :func:`untracked` is what catches the case, on
    every build, before anything is published.
    """
    notes = [] if notes is None else notes
    math_revs = []
    for n, rev in enumerate(_word.revisions(doc), 1):  # enumerator: O(i)
        try:
            if rev.Range.OMaths.Count:
                math_revs.append(rev)
        except Exception as exc:
            notes.append(f"revision {n}: could not be inspected ({exc})")

    seeded = 0
    for rev in reversed(math_revs):       # last first: accepting shifts rest
        _comment_revision(doc, rev, classify, generic, notes)
        seeded += 1
        try:
            rev.Accept()
        except Exception as exc:
            notes.append(f"math revision not accepted ({exc}) — Word "
                         "cannot serialize a compare result containing "
                         "tracked math, so this build may fail to save")
    return MathOutcome(seeded or _seed_scaffold(doc, classify, generic, notes))


def _comment_revision(doc: Any, rev: Any, classify: Classifier,
                      generic: str | None,
                      notes: list[str] | None = None) -> None:
    """Attach the paper's comment to one revision, through Word."""
    notes = [] if notes is None else notes
    rng = rev.Range
    text = para = ""
    with _suppress_com("read a revision's own text"):
        text = rng.Text or ""
    with _suppress_com("read a revision's paragraph"):
        para = rng.Paragraphs(1).Range.Text or ""
    comment = classify(RevisionContext(
        text=text, para=para, window=para, table_index=None,
        start=-1, end=-1))
    # The fallback matters even when the paper passes generic=None: this
    # comment is also the scaffold the XML pass clones, and Word cannot
    # add one with no text, so the build would fail with ScaffoldMissing.
    try:
        doc.Comments.Add(rng, comment or generic or _comments.GENERIC)
    except Exception as exc:
        # NOT cosmetic: if this was to be the scaffold, the build fails
        # later with ScaffoldMissing and no hint of the real cause
        notes.append(f'comment not added to "{text[:30]}": {exc}')


def _seed_scaffold(doc: Any, classify: Classifier | None,
                   generic: str | None,
                   notes: list[str] | None = None) -> int:
    """Ensure ONE Word-made comment exists, for the XML pass to clone.

    The comment parts, styles and relationships have to come from Word
    itself; hand-rolling them is how a file ends up repaired on open.
    """
    notes = [] if notes is None else notes
    if classify is None:
        return 0
    try:
        if not doc.Revisions.Count:
            return 0
        _comment_revision(doc, doc.Revisions(1), classify, generic, notes)
        return 1
    except Exception as exc:
        notes.append(f"no comment scaffold could be seeded ({exc}) — the "
                     "XML pass has nothing to clone and will refuse")
        return 0


def _carry_rewrites(parts: dict[str, bytes], original: str | Path,
                    report: BuildReport, say: Any) -> None:
    """What Compare REWRITES rather than drops, so nothing else sees it.

    `compare_collateral` answers "what is missing", and neither of these
    is missing. `settings.xml` is present and rebuilt with Track Changes
    off; the comments part is present and carrying one note twice. Both
    reach the author, and both were per-paper scripts before they were
    here (HCW's `dedupe_comments.py` and the settings patch in its
    `redline.py`).
    """
    if _hygiene.keep_tracking(parts, read_parts(original)):
        report.carried_properties.append("w:trackRevisions")
        say("  carried across: Track Changes was ON and Compare wrote a "
            "fresh settings.xml with it off — an author editing a "
            "'tracked' manuscript whose typing is not being recorded is "
            "the quietest way to lose a round")
    report.deduped_comments = _hygiene.dedupe_comments(parts)
    for note in report.deduped_comments:
        say(f"  de-duplicated a comment present in BOTH inputs: {note}")


def _clear_staging(staging: Path, building: Path, published: bool,
                   say: Callable[[str], None]) -> None:
    """Tidy up after a build, keeping the artefact when one was REFUSED.

    A refused build is the one worth looking at, and this used to delete
    it. Word answering "the file appears to be corrupted" from `verify`
    left nothing to open, so the only way to see what it had been given
    was to rebuild with `verify_in_word=False` — which is how a
    comment-anchor defect cost a bisect rather than a look, twice in one
    day (2026-08-24).

    On success the file has already been renamed to `out`, so the unlink
    is a no-op and only the failure path ever loses anything. The kept
    file is a `~` temp name that the next build overwrites, so the cost
    of keeping it is one stale file at worst.
    """
    shutil.rmtree(staging, ignore_errors=True)
    if published:
        building.unlink(missing_ok=True)
    elif building.exists():
        say(f"  the refused build is kept at {building.name} — open it to "
            f"see what Word was given; the next build overwrites it")


def _carry_parts(parts: dict[str, bytes], revised_parts: dict[str, bytes],
                 original: str | Path, *, carry: tuple[str, ...],
                 report: BuildReport, say: Callable[[str], None]) -> None:
    """Put back what Compare dropped, from the clean copy or the baseline.

    Two sources on purpose. The clean copy is the usual one and is not
    always A source: when Word ate the part THERE too, restoring from it
    restores nothing and every gate agrees, because every gate compares
    the redline against that same clean copy. The baseline still has it,
    so it is asked second and reported apart — "this build went back a
    version for these" is a different sentence, and the one case where
    an author might want to look.

    Whether to fall back at all is a judgment, and it was made on
    measurement. Across 197 manuscripts in these projects `customXml/`
    holds Word's `<b:Sources>` bibliography store in 146 of them and
    `docProps/custom.xml` holds `ZOTERO_PREF` in 68 — the database
    behind every CITATION field, and what makes Zotero recognise a
    document as one it manages. Six carry an MSIP sensitivity label
    besides. Losing any of it stops the author's citation workflow with
    nothing red anywhere.

    Against that, "the author deleted it deliberately" is a thin story
    for these particular parts: Word barely exposes custom properties
    and does not expose the data store at all, so it is not something a
    prose edit does on purpose. The way to MEAN it stays explicit —
    `strip_parts`, and `[batch] carry` for a paper that wants something
    else.
    """
    report.carried = _hygiene.restore_parts(parts, revised_parts,
                                            prefixes=carry)
    for name in report.carried:
        # It said "it is not referenced from the body, so it goes back
        # with its content type and a free rId". True of the data
        # store, and false of the two parts where it matters: a header
        # or footer IS referenced from the body, from the section
        # properties, and that reference is the whole difficulty. The
        # sentence sent the one reader who would have looked at the
        # sectPr somewhere else.
        say(f"  carried across: {name} (Compare drops it; it goes back "
            f"with its content type, a free rId and — for a header or "
            f"footer — its section reference, reconciled against the "
            f"baseline's type map rather than appended beside whatever "
            f"Compare re-typed)")
    report.carried_from_baseline = _hygiene.restore_parts(
        parts, read_parts(original), prefixes=carry)
    for name in report.carried_from_baseline:
        say(f"  carried from the BASELINE: {name} (the clean copy no "
            f"longer has it either — `strip_parts` is how to mean "
            f"its removal)")


def build(original: str | Path, revised: str | Path, out: str | Path,
          classify: Classifier | None = None,
          *, author: str = "Revision", generic: str | None = _comments.GENERIC,
          tables: str = _comments.COALESCE,
          whitespace: bool = True, formatting: bool = True,
          moves: bool = True,
          resolve_math: bool = True, reject_check: bool = True,
          accept_check: bool = True,
          verify_in_word: bool = True, force: bool = False,
          carry: tuple[str, ...] = CARRIED_PARTS,
          progress: Callable[[str], None] | None = None,
          word_deadline: float | None = None,
          ) -> BuildReport:
    """Produce a tracked-changes docx at `out` from `original` -> `revised`.

    `classify` receives each revision and returns its comment text (or
    None to fall back to `generic`). Pass ``classify=None`` for a plain
    redline with no comments at all — not every paper annotates, and 1300
    "unclassified" balloons would be worse than silence. Pass
    ``generic=None`` to keep the matched comments but leave unmatched
    revisions bare.

    `tables` handles the case a modified table creates: Word makes every
    changed cell its own revision, so a regenerated table arrives as
    hundreds of them. The default coalesces those to one balloon per
    distinct comment per table. Pass ``tables=comments.ALL`` only to
    reproduce a deliverable built before that existed.

    `moves` is Word's move detection, and it is a heuristic that can
    produce a wrong deliverable rather than merely a differently-shaped
    one: on Aging_Well a scored move truncated the moved paragraph in
    the ACCEPTED view, taking a clause, a hyperlink and the sentence
    after it, and the same pair with ``moves=False`` reproduced the
    paragraph exactly. The accept-side gate below is what catches it —
    if this build refuses with a lost anchor or an unreproduced
    paragraph and the round moved a passage, try ``moves=False`` before
    anything else.

    `resolve_math` accepts the revisions inside an equation, because
    Word's save path may refuse to serialize them. Pass ``False`` where
    the paper has MEASURED that it does not have to: on LI7 the Flat OPC
    route carried 1870 revisions with the math tracked and reject-all
    reproduced the submitted paper exactly, while resolving the math cost
    315 revisions. Every accepted revision is one the author can no
    longer refuse, so the burden of proof is on resolving, not on
    keeping.

    `reject_check` is the gate that would have caught that: rejecting
    every revision in the built package must reproduce `original`, and
    the build refuses to publish when it does not (:func:`untracked`).
    Turn it off only to obtain the artifact for diagnosis — the paragraph
    listing in the error says what differs without it.

    `accept_check` is the same gate on the other side: ACCEPTING every
    revision must reproduce `revised`, the clean document the redline
    was derived from. The reject side cannot cover for it — rejecting
    removes every insertion, so a defect Compare baked INSIDE one is
    deleted before that comparison happens and cannot appear there
    however wrong it is — and the accepted document is the one the
    author reads. A build made with ``whitespace=False`` compares with
    runs of whitespace collapsed, because Word then treats respacing as
    no revision and accepting legitimately leaves the original's
    spacing. See :func:`unaccepted`.

    `verify_in_word` reopens the result and fails the build if Word had to
    repair it. `force` overrides the refusal to overwrite a deliverable
    that has been edited since it was built.

    `carry` names part-trees to copy back from `revised` when Compare
    drops them: the ``customXml/`` data store, which it drops on every
    single rebuild, and ``docProps/custom.xml``, whose user-defined
    properties carry a Bank manuscript's sensitivity label. Pass
    ``carry=()`` to get the raw Compare output and only a warning. See
    :func:`docxkit.hygiene.restore_parts` for why the default is not
    "warn and leave it to the reader".

    **Widening it to a header or a footer is a decision, not a default.**
    Those are reached from a ``w:headerReference`` in the section
    properties as well as through a relationship, and Compare rewrites
    the sectPr when it rebuilds the document. `restore_parts` puts that
    reference back — reading the type off the source's own sectPr — or
    refuses; what it cannot do is tell you whether the section the
    reference lands in is still the section the author meant. That case
    wants a person to look at the rendered page.
    """
    original, revised, out = Path(original), Path(revised), Path(out)
    report = BuildReport()
    say = progress or (lambda _: None)

    if (saved := _guard.check(out, force=force)) is not None:
        say(f"note: previous deliverable backed up to {saved.name}")

    # Build BESIDE the target and move it into place only once every gate
    # has passed. Writing the deliverable first and validating it second
    # means a failed lint or a Word repair leaves the previous good
    # redline already destroyed — and guard.check only takes a backup
    # when the file looks hand-edited, so the ordinary case has no copy
    # to fall back to. Staging in `out`'s own directory keeps the final
    # move atomic; a temp directory could be on another volume.
    staging = Path(tempfile.mkdtemp(prefix="docxkit_tracked_"))
    building = out.with_name(f"~{out.stem}.building{out.suffix}")
    published = False
    try:
        flat = staging / "flat.xml"

        with _word.session(**_bounded(
                word_deadline,
                f"comparing {Path(revised).name} against "
                f"{Path(original).name}")) as word, \
                _word.open_doc(word, original) as orig, \
                _word.open_doc(word, revised) as rev:
            cmp_ = _word.compare_documents(
                word, orig, rev, author=author,
                whitespace=whitespace, formatting=formatting, moves=moves)
            report.body_revisions = int(cmp_.Revisions.Count)
            report.mark("compared")
            _word.draft_view(cmp_)

            if resolve_math:
                math = _resolve_math(cmp_, classify, generic,
                                     report.suppressed)
                report.math_resolved, report.math_kept = math
                report.mark("resolved math revisions")
                say(f"resolved {report.math_resolved} math revisions "
                    "(Word's save path may refuse to serialize them)")
                if report.math_kept:
                    say(f"  {report.math_kept} revision(s) merely OVERLAP "
                        f"an equation and stay tracked — accepting one "
                        f"applies its whole span")
            else:
                # The scaffold is not optional for an annotated build:
                # `comments.annotate` CLONES a Word-made comment, and
                # without one the build fails later with ScaffoldMissing,
                # a long way from the flag that caused it. It is NOT
                # counted as a resolved math revision — nothing was
                # resolved, and `revision.build` refuses a batch on that
                # number.
                _seed_scaffold(cmp_, classify, generic, report.suppressed)
                report.mark("math left tracked")
                say("math left tracked (resolve_math=False)")
            for note in report.suppressed:
                say(f"  WARNING: {note}")

            # NOTE: keep orig/rev OPEN until after the extraction — the
            # compare result lazily references their parts, and closing
            # them first makes Content.WordOpenXML raise "A file error
            # has occurred".
            _word.extract_flat_opc(cmp_, flat)
            report.mark("extracted Flat OPC")
            with _suppress_com("close the compare result"):
                cmp_.Close(SaveChanges=0)

        n_parts = _word.flat_opc_to_docx(flat, building)
        report.mark(f"packed {n_parts} parts")

        parts = read_parts(building)
        # The count that matters, read off the PACKAGE: every kind, every
        # text-bearing part. Word's is the body only, so it is said aloud
        # separately when the two disagree rather than quietly replaced.
        report.revisions = package_counts(parts)["revisions"]
        say(f"revisions: {report.revisions}")
        if report.body_revisions != report.revisions:
            say(_revision_gap(parts, report.body_revisions,
                              report.revisions))

        # Before anything is added to it: what did Compare decline to
        # carry over? Checked against the REVISED input, which is the
        # document the redline is supposed to be able to reproduce.
        revised_parts = read_parts(revised)
        # The data store is not referenced from the body, so putting it
        # back is three mechanical edits and no judgment — which is
        # exactly the sort of thing that belongs here rather than in a
        # paper's script directory, hand-run after every single build.
        _carry_parts(parts, revised_parts, original, carry=carry,
                     report=report, say=say)
        # And the same argument one level down, on the FIELDS of
        # docProps/core.xml: Word rebuilds that part with its own four
        # save fields and nothing else, so a titled manuscript becomes an
        # untitled deliverable with the part still in place. Timestamps
        # are left to the redline; only what the document says about
        # itself is carried.
        report.carried_properties = _hygiene.carry_properties(parts,
                                                              revised_parts)
        if report.carried_properties:
            say(f"  carried across: {', '.join(report.carried_properties)} "
                f"(Compare regenerates core.xml with only its own save "
                f"fields; metadata is not tracked-changeable, so nothing "
                f"else would ever report this)")
        _carry_rewrites(parts, original, report, say)
        report.dropped = compare_collateral(revised_parts, parts)
        for note in report.dropped:
            say(f"  WARNING: Compare {note}")

        if classify is not None:
            added, unclassified = _comments.annotate(parts, classify,
                                                     generic=generic,
                                                     tables=tables)
            _comments.reclassify(parts, classify, generic=generic)
            report.comments_added, report.unclassified = added, unclassified
            report.mark(f"annotated {added} revisions in XML")
            say(f"comments: {added} added, unclassified: {unclassified}")

        # catch the "Word says unreadable content" classes offline,
        # before the file is written and long before anyone opens it
        if problems := lint_parts(parts):
            listed = "\n  - ".join(problems)
            raise PackageError(
                f"the package would not open cleanly in Word:\n  - {listed}")

        # The gate the whole deliverable exists for: everything in it
        # must be REFUSABLE. A redline that cannot be rejected back to
        # the original carries edits the author was never offered, and
        # every other signal here reads as success while it does — LI7
        # shipped one, and found it two rounds later with a hand-written
        # difflib script.
        base_parts = read_parts(original)
        report.unrejectable = untracked(parts, base_parts)
        # What a MOVE can duplicate, and what neither view can undo.
        # Word's Compare answers a moved block by writing the table
        # TWICE and marking neither copy: on DSI (2026-08-19) a redline
        # carried 28 tables against the baseline's 27 and BOTH accept and
        # reject left 28, so the author could not get rid of it and
        # nothing said it was there. A move whose rows Word DOES flag is
        # handled — `revisions._row_flag` reads `w:trPr` — and this is
        # the shape it cannot: an unmarked copy is not a revision, so it
        # is refused rather than resolved.
        accepted_view = _simulate(parts, _accept)
        report.structure_diff = (
            [f"rejected: {d}" for d in structure_diff(
                structure_counts(base_parts),
                structure_counts(_simulate(parts, _reject)))]
            + [f"accepted: {d}" for d in structure_diff(
                structure_counts(revised_parts),
                structure_counts(accepted_view))])
        # The carriers those counts do not hold: a hyperlink is not in
        # STRUCTURE_TAGS, because Word legitimately re-represents a
        # field-form link as an element and counting the tag would
        # refuse that. Anchors are compared by NAME instead, which is
        # blind to which form carries them.
        report.accepted_losses = accepted_losses(revised_parts,
                                                 accepted_view)
        # And the carrier neither of those reads: a definition whose
        # only reference the accept removed. `_simulate` has already
        # dropped the empty shells, so what is left here has words in
        # it — a footnote that will render nowhere. Measured against
        # the CLEAN copy rather than reported outright, because a
        # manuscript that already carries one is not this build's doing.
        report.orphan_notes = [
            o for o in _footnotes.orphans(accepted_view)
            if o not in set(_footnotes.orphans(revised_parts))]
        # And the same question of the OTHER view. `revised_parts` is
        # the clean document this redline claims to reproduce; what an
        # accept leaves has to be it, word for word.
        report.unaccepted = unaccepted(parts, revised_parts,
                                       fold_space=not whitespace)
        report.mark("checked reject-all against the original")
        for para in report.unrejectable:
            say(f"  UNREJECTABLE {para}")
        for missed in report.unaccepted:
            say(f"  UNACCEPTED {missed}")
        if report.structure_diff and reject_check:
            listed = "\n  ".join(report.structure_diff)
            raise PackageError(
                f"the redline does not carry the same STRUCTURE as the "
                f"documents it was built from:\n  {listed}\n"
                f"A move is the usual cause: Word's Compare answers a "
                f"moved block by writing the table twice and marking "
                f"neither copy, so neither accepting nor rejecting "
                f"removes the duplicate. Build with moves=False "
                f"(`revision build --no-moves`), which takes Word's move "
                f"detection out of it and shows the block as a deletion "
                f"and an insertion; move it in the CLEAN copy in a "
                f"separate round; or pass reject_check=False to build "
                f"the file anyway and inspect it.")
        if report.unrejectable and reject_check:
            listed = "\n  ".join(str(u) for u in report.unrejectable)
            raise PackageError(
                f"rejecting every revision does NOT reproduce "
                f"{original.name} — {len(report.unrejectable)} paragraph(s) "
                f"differ with no revision on them, so the author cannot "
                f"refuse those edits:\n  {listed}\n"
                f"An over-eager math accept is the usual cause: try "
                f"resolve_math=False. Pass reject_check=False to build the "
                f"file anyway and inspect it.")
        if accept_check:
            _refuse_accept_side(report, revised.name)
        # Word rewrites the OMML while deriving the redline and flattens
        # U+2212 to an ASCII hyphen doing it — measured on AFI: 2 minus
        # signs in the baseline, 0 in the built batch, and the 57 in the
        # PROSE of both untouched. Nothing else sees it: the text layer
        # reads the same words, `validate`'s glyph gate says only that
        # SOMETHING moved, and the equation still renders. Put back only
        # what a source really spells that way (see the docstring for
        # what is deliberately not inferred).
        report.restored_glyphs = _hygiene.restore_math_glyphs(
            parts, revised_parts, read_parts(original))
        for note in report.restored_glyphs:
            say(f"  restored math glyph — {note}")

        # AFTER the glyph restore, and after the write below would be too
        # late. Compare diffs INSIDE an inline equation, so accepting can
        # leave a number nobody wrote — see `accepted_math`. Refused with
        # the other accept-side gate, because a wrong number in the
        # deliverable is not something to report and continue past.
        report.accepted_math = accepted_math(
            revised_parts, _simulate(parts, _accept))
        if accept_check:
            _refuse_accept_side(report, revised.name, math_only=True)

        write_docx(building, parts)
        report.comments_total = package_counts(parts)["comments"]

        if verify_in_word:
            # the keyword only when a ceiling is asked for — `_bounded`'s
            # rule, so a fake `verify` that knows no keyword is untouched
            checked = verify(building, **({"word_deadline": word_deadline}
                                          if word_deadline else {}))
            report.verified_comments = checked["word"]["comments"]
            report.verified_revisions = checked["word"]["revisions"]
            if not checked["comments_match"]:
                raise PackageError(
                    f"Word read back {report.verified_comments} comments, "
                    f"the package holds {report.comments_total} — it was "
                    "repaired on open")
            report.mark("verified in Word")
            say(f"verified in Word: {report.verified_comments} comments, "
                f"{report.verified_revisions} revisions in the body")

        building.replace(out)          # every gate passed: publish
        published = True
        # `base_sha256` is the batch's link to the BASELINE it was built
        # on. The names alone cannot answer "is this batch about the
        # current truth" — `prev.docx` is a path whose content changes
        # on every `baseline` — and without it a refused build left the
        # PREVIOUS redline in place for `validate` and `promote` to take
        # as this one (Aging_Well R5). See `guard.base_of`.
        _guard.stamp(out, original=original.name, revised=revised.name,
                     base_sha256=_guard.sha256(original))
        return report
    finally:
        _clear_staging(staging, building, published, say)
