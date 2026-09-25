r"""What the tracked-changes DELIVERABLE has to satisfy.

Split out of `test_tracked_build.py` on 2026-09-02, at that file's own
theme boundary: everything here is about the gates a redline must pass —
reject-all against the original, accept-all against the clean copy, the
structure counts, the anchors and equations neither of those can see —
and everything left there is about producing one.

The two halves share the fake Word module and the `sources` fixture,
which stay in `test_tracked_build` and are imported below. That is the
convention `test_cli_revision.py` already follows with `test_cli`: one
definition, imported, rather than a second copy that drifts.
"""
from __future__ import annotations

import itertools
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest
from conftest import (
    NS,
    clean_document,
    dele,
    ins,
    make_parts,
    notes,
    para,
    run,
)
from test_tracked_build import (
    _build,
    _Count,
    _FakeDoc,
    _FakeWordModule,
    _MathRange,
    _OMath,
    _Rev,
)

from docxkit import tracked
from docxkit.errors import PackageError
from docxkit.tracked import unaccepted, untracked


def _parts(*paras: str, footnotes: str | None = None) -> dict[str, bytes]:
    return make_parts("".join(paras), footnotes=footnotes)


def test_a_paragraph_changed_with_NO_revision_is_named():
    baseline = _parts(para(run("The index rose to 0.35 in 2024.")))
    batch = _parts(para(run("The index rose to 0.37 in 2024.")))

    (found,) = untracked(batch, baseline)

    assert found.part == "body"
    assert found.index == 0
    assert found.baseline == "The index rose to 0.35 in 2024."
    assert found.batch == "The index rose to 0.37 in 2024."


def test_a_properly_TRACKED_change_is_not_a_finding():
    """Rejecting it restores the baseline, which is the whole test."""
    baseline = _parts(para(run("The index rose.")))
    batch = _parts(para(dele("The index rose.") + ins("The index fell.")))

    assert untracked(batch, baseline) == []


def test_a_paragraph_the_batch_ADDED_reports_an_empty_baseline():
    """The two sides are what a reader compares, and one of them being
    empty is the finding: nothing was there before."""
    baseline = _parts(para(run("Alpha.")))
    batch = _parts(para(run("Alpha.")), para(run("Beta, out of nowhere.")))

    (found,) = untracked(batch, baseline)

    assert (found.baseline, found.batch) == ("", "Beta, out of nowhere.")
    assert found.index == 1


def test_the_paragraph_number_counts_in_the_view_the_reader_OPENS():
    """`label, j1 + k` — the index into the REJECTED view, not into the
    baseline. The two part company as soon as the batch adds a
    paragraph above the difference, and they are the same number in
    every fixture that does not.

    A person takes this number to `working.docx` and counts down. Read
    off the baseline it is short by every insertion above it, which on
    a real batch is most of them."""
    # TWO insertions with an unchanged paragraph between them: the
    # second is where the two indices part company, because by then the
    # batch is one paragraph ahead of the baseline
    baseline = _parts(para(run("Alpha.")), para(run("Gamma.")))
    batch = _parts(para(run("Alpha.")), para(run("Inserted one.")),
                   para(run("Gamma.")), para(run("Inserted two.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.batch) for f in found] == [
        (1, "Inserted one."), (3, "Inserted two.")], found
    assert "¶2" in str(found[0]) and "¶4" in str(found[1])


def test_an_unaccepted_paragraph_is_quoted_at_seventy_characters():
    """The accept side's own record, and the same cut as the reject
    side's: two paragraphs, side by side, on one line each. Uncut, one
    finding fills the terminal and the eight the limit allows fill a
    screen nobody reads."""
    long_line = ("The revised sentence, at some length, because a "
                 "paragraph in a paper usually is.")
    assert len(long_line) > 71
    intended = _parts(para(run(long_line)))
    parts = _parts(para(run("Employment rises "),
                        ins("sharply, and not what was asked for")))

    (missed,) = unaccepted(parts, intended)

    assert missed.intended == long_line
    assert repr(long_line[:70]) in str(missed)
    assert repr(long_line[:71]) not in str(missed)


def test_unaccepted_stops_at_EIGHT_findings_by_default():
    """`limit: int = 8`. The refusal prints every finding it is given,
    and a batch that went wrong at the top goes wrong all the way down
    — a document whose accept reproduces nothing would print a page per
    paragraph. Eight is what a person reads before going to look at the
    file, and the reject side has stopped there since it was written."""
    intended = _parts(*[para(run(f"Intended {i}.")) for i in range(12)])
    parts = _parts(*[para(run(f"Accepted {i}.")) for i in range(12)])

    assert len(unaccepted(parts, intended)) == 8
    assert len(unaccepted(parts, intended, limit=3)) == 3


def test_unaccepted_compares_the_SPACING_too_unless_told_not_to():
    """`fold_space: bool = False`. The default is the exact comparison,
    because a build that tracks whitespace must reproduce it — only a
    `whitespace=False` build legitimately accepts to the original's
    spacing, and `build` passes the flag for exactly that case.

    Defaulted the other way, respacing inside an insertion — which is
    Word rewriting content, the thing this gate exists to catch — would
    pass every build."""
    intended = _parts(para(run("Employment rises sharply here.")))
    parts = _parts(para(run("Employment  rises sharply here.")))

    (missed,) = unaccepted(parts, intended)
    assert missed.accepted == "Employment  rises sharply here."

    assert unaccepted(parts, intended, fold_space=True) == []


def test_a_paragraph_the_batch_LOST_reports_an_empty_batch():
    baseline = _parts(para(run("Alpha.")), para(run("Beta, now gone.")))
    batch = _parts(para(run("Alpha.")))

    (found,) = untracked(batch, baseline)

    assert (found.baseline, found.batch) == ("Beta, now gone.", "")


def test_a_MERGE_reports_every_paragraph_of_the_block():
    """Three paragraphs replaced by one is the shape that shipped: the
    walk covers the LONGER side, so the two that vanished are named as
    well as the one that stayed."""
    baseline = _parts(para(run("First.")), para(run("Second.")),
                      para(run("Third.")))
    batch = _parts(para(run("All three, merged.")))

    found = untracked(batch, baseline)

    assert [(f.baseline, f.batch) for f in found] == [
        ("First.", "All three, merged."), ("Second.", ""), ("Third.", "")]


def test_the_FOOTNOTES_are_checked_too_and_labelled():
    """An edit the author cannot refuse is as bad in a note as in the
    body, and the label is which file to open."""
    notes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<w:footnotes {NS}><w:footnote w:id="2">'
             f"{para(run('The note, as built.'))}</w:footnote></w:footnotes>")
    changed = notes.replace("as built", "as edited")

    (found,) = untracked(_parts(para(run("x")), footnotes=changed),
                         _parts(para(run("x")), footnotes=notes))

    assert found.part == "footnotes"
    assert found.batch == "The note, as edited."


def test_the_list_STOPS_at_eight():
    """A batch that lost its revisions entirely would otherwise print
    the manuscript, and the first eight are enough to say the batch is
    not reviewable."""
    baseline = _parts(*(para(run(f"Paragraph {i}.")) for i in range(12)))
    batch = _parts(*(para(run(f"Paragraph {i} rewritten."))
                     for i in range(12)))

    assert len(untracked(batch, baseline)) == 8
    assert len(untracked(batch, baseline, limit=3)) == 3


def test_the_finding_PRINTS_where_it_is_and_both_sides():
    """One-based in the message, because that is how Word counts, and
    zero-based in the field, because that is how a caller indexes."""
    baseline = _parts(para(run("Alpha.")), para(run("Beta.")))
    batch = _parts(para(run("Alpha.")), para(run("Beta, changed.")))

    (found,) = untracked(batch, baseline)

    printed = str(found)
    assert printed.startswith("body ¶2: baseline 'Beta.'")
    assert "batch    'Beta, changed.'" in printed


# --- the second round, from the re-measurement of 2026-08-18 -------------
#
# 36.3 % -> 28.5 % after the tests above, and `untracked` was STILL the
# largest cluster with 23. Seventeen of them sat on `i1 + k` and `j1 + k`
# mutated to `|`, `^`, `>>` — which agree with `+` whenever the left
# operand is 0, and every fixture above starts its changed block at
# paragraph 0 or 1. A paper's untracked edit is on page nine.


def test_a_block_deep_in_the_document_reports_the_paragraphs_it_IS():
    """`i1 + k` with `i1` at 3: `3|1` is 3 and `3^1` is 2, where `3+1`
    is 4. At index 0 every one of those is the same number, which is why
    a fixture that starts at the top cannot tell them apart — and the
    report would then name the wrong three paragraphs of a manuscript
    whose author is looking for the one nobody offered them."""
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    baseline = _parts(*keep, para(run("Alpha original.")),
                      para(run("Beta original.")),
                      para(run("Gamma original.")), para(run("Tail.")))
    batch = _parts(*keep, para(run("Alpha rewritten.")),
                   para(run("Beta rewritten.")),
                   para(run("Gamma rewritten.")), para(run("Tail.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.baseline, f.batch) for f in found] == [
        (3, "Alpha original.", "Alpha rewritten."),
        (4, "Beta original.", "Beta rewritten."),
        (5, "Gamma original.", "Gamma rewritten.")]


def test_an_INSERTED_paragraph_shifts_the_batch_side_and_not_the_other():
    """The two offsets are different numbers here, so `j1` cannot stand
    in for `i1`: the batch has one paragraph more, the baseline runs out
    first, and the last finding is a paragraph that exists on one side
    only. It is also what an untracked insertion looks like — the
    paragraphs after it all read as changed, because they have moved."""
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    baseline = _parts(*keep, para(run("Alpha original.")),
                      para(run("Beta original.")), para(run("Tail.")))
    batch = _parts(*keep, para(run("New paragraph.")),
                   para(run("Alpha rewritten.")),
                   para(run("Beta rewritten.")), para(run("Tail.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.baseline, f.batch) for f in found] == [
        (3, "Alpha original.", "New paragraph."),
        (4, "Beta original.", "Alpha rewritten."),
        (5, "", "Beta rewritten.")]


def test_the_limit_is_KEYWORD_only():
    """A bare number at the call site would read as a third document."""
    baseline = _parts(para(run("Alpha.")))
    batch = _parts(para(run("Beta.")))

    with pytest.raises(TypeError):
        untracked(batch, baseline, 3)          # type: ignore[call-arg]


def test_a_MERGE_deep_in_the_document_covers_the_LONGER_side():
    """`max(i2 - i1, j2 - j1)` decides how far the walk goes, and only a
    block where the two sides differ in LENGTH says which term won: three
    paragraphs became one, so the baseline side is the longer one. With
    `i1` at 3, `i2 >> i1` is 0 and the walk stops after the first — the
    two paragraphs that vanished go unnamed, which is the Parental Style
    shape exactly, one page further in."""
    keep = [para(run(f"Paragraph {i} is untouched.")) for i in range(3)]
    baseline = _parts(*keep, para(run("First.")), para(run("Second.")),
                      para(run("Third.")), para(run("Tail.")))
    batch = _parts(*keep, para(run("All three, merged.")),
                   para(run("Tail.")))

    found = untracked(batch, baseline)

    assert [(f.index, f.baseline, f.batch) for f in found] == [
        (3, "First.", "All three, merged."),
        (4, "Second.", ""),
        (5, "Third.", "")]


# --- the Word path's own report, from the same re-measurement ------------
#
# `_comment_revision` 13 survivors and `_accept_math_via_equations` 11,
# the two largest after `untracked`. Both run only through Word, so the
# fakes above are the whole harness — and they asserted what the
# functions DID (a comment added, a revision accepted) and never what
# they were told. Eight of the thirteen sat on the two sentinels the
# context carries, which is what a paper's classifier reads.


class _ClassifierRange:
    """A revision's range: its own text, and the paragraph around it."""

    Text: str | None = "the revised phrase"
    PARAGRAPHS: ClassVar[dict[int, str]] = {
        1: "The paragraph the revision sits in.",
        2: "A different paragraph entirely."}

    def Paragraphs(self, i):
        text = self.PARAGRAPHS[i]
        return type("P", (), {"Range": type("R", (), {"Text": text})})


class _NullTextRange(_ClassifierRange):
    """Word hands back None for an empty range, not an empty string."""

    Text = None


class _CommentDoc:
    def __init__(self):
        self.added: list[str] = []
        self.Comments = type("C", (), {
            "Add": lambda _s, rng, text: self.added.append(text),
            "Count": 0})()


def test_what_the_CLASSIFIER_is_handed_on_the_Word_path():
    """The paper's own function reads this, and a build makes one call
    per revision. `window` is the paragraph because Word gives no wider
    scope here, `table_index` is None because it cannot say, and the two
    offsets are -1: a sentinel that means "not located", where 0 and 1
    are real positions a rule could match on."""
    from docxkit.comments import RevisionContext
    from docxkit.tracked import _comment_revision
    seen: list[RevisionContext] = []

    def classify(ctx):
        seen.append(ctx)
        return "R1: the comment"

    doc = _CommentDoc()
    _comment_revision(doc, type("Rev", (), {"Range": _ClassifierRange()}),
                      classify, None)

    (ctx,) = seen
    assert ctx.text == "the revised phrase"
    assert ctx.para == "The paragraph the revision sits in."
    assert ctx.window == ctx.para
    assert ctx.table_index is None
    assert (ctx.start, ctx.end) == (-1, -1)
    assert doc.added == ["R1: the comment"]


def test_a_range_Word_reports_as_None_reaches_the_classifier_as_TEXT():
    """`rng.Text or ""` — with `and` in its place the context carries
    None, and a classifier doing `"table" in ctx.text` raises inside the
    paper's own code, one revision into a build of fourteen hundred."""
    from docxkit.tracked import _comment_revision
    seen = []

    def classify(ctx):
        seen.append(ctx.text)
        return "R1"

    _comment_revision(_CommentDoc(),
                      type("Rev", (), {"Range": _NullTextRange()}),
                      classify, None)

    assert seen == [""]


class _BoundedMathDoc:
    """One equation at 100-200 and four revisions around its edges."""

    def __init__(self):
        self.exact = _Rev("exactly the equation", span=(100, 200))
        self.inside = _Rev("well within it", span=(120, 150))
        self.overhangs_left = _Rev("starts in the prose", span=(90, 150))
        self.overhangs_right = _Rev("runs past the end", span=(150, 250))
        self.revisions = [self.exact, self.inside,
                          self.overhangs_left, self.overhangs_right]
        self.OMaths = _Count([_OMath(revisions=self.revisions,
                                     span=(100, 200))])
        self.Revisions = _Count(self.revisions)


def test_a_revision_ON_the_equation_boundary_is_OF_the_equation():
    """`lo <= span[0] and span[1] <= hi`, at the two places it is
    decided. A revision that covers the equation exactly is the whole of
    it and must be accepted; one that starts a character earlier, or
    ends a character later, carries prose with it — and `Accept()`
    applies the WHOLE span, which is how thirteen accepts destroyed 315
    revisions on LI7."""
    from docxkit.tracked import _accept_math_via_equations

    doc = _BoundedMathDoc()
    outcome = _accept_math_via_equations(doc)

    assert doc.exact.accepted, "a revision covering it exactly is OF it"
    assert doc.inside.accepted
    assert not doc.overhangs_left.accepted, "it starts in the prose"
    assert not doc.overhangs_right.accepted, "it ends in the prose"
    assert outcome == (2, 2)          # accepted, kept


# --- the report itself, from the same re-measurement --------------------
#
# `format` 9 survivors, `__init__` 8, `mark` and `seconds` 5 between
# them, `__str__` 4. This is the text a paper's author reads to decide
# whether a redline is worth opening, and the numbers in it were free:
# every counter's initial 0, the cap on the two lists, the "and N more"
# arithmetic, and every phase duration.


def test_a_FRESH_report_counts_nothing():
    """Every counter starts at 0 and every list empty, so a build that
    fails before its first phase reports a build that did nothing —
    rather than one that resolved a revision it never saw."""
    report = tracked.BuildReport()

    assert (report.revisions, report.body_revisions) == (0, 0)
    assert (report.math_resolved, report.math_kept) == (0, 0)
    assert (report.comments_added, report.comments_total) == (0, 0)
    assert report.unclassified == 0
    assert report.verified_comments is None
    assert report.verified_revisions is None
    assert report.suppressed == report.dropped == []
    assert report.carried == report.carried_properties == []
    assert report.restored_glyphs == []
    assert report.unrejectable == []
    assert report.phases == []


@pytest.mark.parametrize("field,head", [
    ("suppressed", "Word call(s) failed"),
    ("dropped", "thing(s) the revised copy had"),
])
def test_the_two_lists_print_TEN_and_then_a_count(field, head):
    """Ten is the cap, and the line after it is a subtraction, not a
    remainder: with 21 notes `21 % 10` also reads "1 more", which is
    what a 12-item fixture cannot tell apart from `21 - 10`."""
    def rendered(n: int) -> list[str]:
        report = tracked.BuildReport()
        setattr(report, field, [f"note {i}" for i in range(n)])
        return report.format().splitlines()

    at_three = rendered(3)
    assert sum("- note" in ln for ln in at_three) == 3
    assert not [ln for ln in at_three if "more" in ln], (
        "under the cap there is no remainder, and `!= 10` prints -7 more")

    at_ten = rendered(10)
    assert sum("- note" in ln for ln in at_ten) == 10
    assert not [ln for ln in at_ten if "more" in ln], "ten is not capped"
    assert any(head in ln for ln in at_ten)

    at_eleven = rendered(11)
    assert sum("- note" in ln for ln in at_eleven) == 10
    assert "    ... and 1 more" in at_eleven

    assert "    ... and 11 more" in rendered(21)


def test_the_HEADER_line_carries_all_four_of_its_numbers(monkeypatch):
    """The one line every build prints, held WHOLE.

    The data census of 2026-09-18 took each of its four numbers out in
    turn and only the revision count was pinned: the comment total, the
    unclassified count and the elapsed seconds could each be dropped
    from the f-string and nothing here noticed. A report cannot fail by
    saying less — it just says less — and these three are what a reader
    decides on: how many comments came through, how many of them nobody
    could classify, and whether the build took twenty seconds or twenty
    minutes.

    Asserted as the whole line rather than by substring, so a number
    ADDED without a case fails here too, which is the half a
    parametrisation over the fields cannot give.
    """
    ticks = itertools.chain([1.0], itertools.repeat(8.5))
    from docxkit import _tracked_report
    monkeypatch.setattr(_tracked_report, "time", type("T", (), {
        "perf_counter": staticmethod(lambda: next(ticks))}))
    report = tracked.BuildReport()          # 1.0
    report.revisions = 12
    report.comments_total = 5
    report.unclassified = 2

    assert report.format() == (
        "revisions 12, comments 5 (2 unclassified), 8s total")


def test_the_math_KEPT_line_appears_only_when_something_was_kept():
    """A revision that overlaps an equation without being of it is left
    tracked on purpose, and saying so is how a reader knows the number
    is a decision rather than a failure. Saying it when the count is
    zero — "0 revision(s) overlap an equation" — is noise on every
    clean build there is."""
    quiet = tracked.BuildReport()
    loud = tracked.BuildReport()
    loud.math_kept = 3

    assert "overlap an equation" not in quiet.format()
    assert "3 revision(s) overlap an equation" in loud.format()


def test_a_phase_is_timed_from_the_one_BEFORE_it(monkeypatch):
    """`now - self._last` is the phase; `now - self._t0` is the build.
    Mutated to `+` the phases read as clock readings, and every one of
    them looks like the slowest step there has ever been."""
    # every reading after the marks is 10.0, because `seconds` is a
    # property and the assertions below ask for it more than once.
    #
    # The numbers are chosen so each reading is more than TWICE the one
    # before: `a % b` is `a - b` for every b <= a < 2b, so a clock that
    # ticks 100, 101, 103 cannot tell the subtraction from a modulo —
    # which is what the first version of this test did, and four
    # mutants lived behind it.
    ticks = itertools.chain([1.0, 3.0, 8.0], itertools.repeat(10.0))
    # The one seam the 2026-09-11 split moved: `BuildReport` reads the
    # clock from its OWN module, which is the report half now.
    from docxkit import _tracked_report
    monkeypatch.setattr(_tracked_report, "time", type("T", (), {
        "perf_counter": staticmethod(lambda: next(ticks))}))

    report = tracked.BuildReport()       # 1.0
    report.mark("compare")               # 3.0
    report.mark("comments")              # 8.0

    assert report.phases == [("compare", 2.0), ("comments", 5.0)]
    assert report.seconds == 9.0         # 10.0, from the start
    assert "[   2.0s] compare" in report.format()


def test_an_untracked_finding_names_the_paragraph_WORD_shows():
    """Word numbers the third paragraph 3, and the field counts from 0,
    so the message adds one — `index << 1` is 4 for the same finding,
    and the author opens the wrong paragraph. Both sides are cut at 70
    characters, and the second line is padded to the width of the first
    so the two read as a column."""
    long_baseline = "The sentence as the baseline has it, " + "x" * 60
    finding = tracked.Untracked("body", 2, long_baseline,
                                "What the batch has instead.")

    first, second = str(finding).splitlines()

    assert first.startswith("body ¶3: baseline ")
    assert first.endswith(repr(long_baseline[:70]))
    assert len(long_baseline) > 70, "the fixture has to be cut to say so"
    assert second == (" " * len("body ¶3") + "  batch    "
                      + repr("What the batch has instead."))


def test_an_unaccepted_finding_names_the_paragraph_WORD_shows():
    """The accept side's own message, and the same arithmetic: thirteen
    mutants sat on that `+ 1` — `index | 1`, `index ^ 1`, `index << 1`
    and the rest — because nothing had ever read a paragraph number
    out of an Unaccepted, only out of an Untracked.

    Both sides are cut at 70 and the second line is padded to the width
    of the first, so intended and accepted read as a column."""
    long_accepted = "What accepting everything leaves there, " + "x" * 60
    # index 3, not 2: `2 | 1` and `2 ^ 1` are both 3, so an even index
    # is a paragraph number two of the spellings agree on
    finding = tracked.Unaccepted("body", 3, "What the clean copy says.",
                                 long_accepted)

    first, second = str(finding).splitlines()

    assert first.startswith("body ¶4: intended ")
    assert len(long_accepted) > 70, "the fixture has to be cut to say so"
    assert second == (" " * len("body ¶4") + "  accepted "
                      + repr(long_accepted[:70]))


# --- the move that duplicates a table (DSI, 2026-08-19) -----------------
#
# Word's Compare answers a moved block by writing the table TWICE and
# marking neither copy. On DSI the redline carried 28 tables against the
# baseline's 27, and BOTH accept and reject left 28 — so the author could
# not get rid of it, and every other signal read as success. A move whose
# rows Word DOES flag is handled (`revisions._row_flag` reads `w:trPr`);
# this is the shape that cannot be resolved, only refused.


def _table_xml(cell: str = "cell") -> str:
    return ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>" + cell
            + "</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")


def test_build_REFUSES_a_redline_that_carries_a_table_twice(monkeypatch,
                                                            sources):
    """The refusal names both counts. Nothing here can tell which copy
    is the spurious one — an unmarked table is not a revision — so the
    answer is to say so before the file reaches an author."""
    doubled = clean_document().replace(
        "</w:body>", _table_xml() + _table_xml() + "</w:body>")
    with pytest.raises(PackageError, match="STRUCTURE"):
        _build(monkeypatch, doubled, sources)


# --- bookmarks are judged by NAME (BACKLOG S3, 2026-09-24) --------------
#
# A bookmark is not revisable: Compare carries the clean copy's bookmark
# ADDITIONS into both views and its DELETIONS into neither. Counted, that
# refused every batch that linked a citation (Misconceptions: rejected
# 121 -> 165, the 44 being exactly what `link_all` added) and every batch
# that deleted a reference entry (accepted +2, `McNemar1947` and its txt).


def _marked(*names: str) -> str:
    """The clean document, its sentence wrapped in these bookmarks."""
    starts = "".join(f'<w:bookmarkStart w:id="{i}" w:name="{n}"/>'
                     for i, n in enumerate(names, 1))
    ends = "".join(f'<w:bookmarkEnd w:id="{i}"/>'
                   for i in range(1, len(names) + 1))
    return clean_document().replace("<w:r>", starts + "<w:r>", 1) \
        .replace("</w:p>", ends + "</w:p>", 1)


def _pair(tmp_path, original: str, revised: str):
    for name, xml in (("original.docx", original), ("revised.docx", revised)):
        with zipfile.ZipFile(tmp_path / name, "w") as z:
            z.writestr("word/document.xml", xml)
    return (tmp_path / "original.docx", tmp_path / "revised.docx",
            tmp_path / "redline.docx")


def test_a_bookmark_the_CLEAN_COPY_ADDED_survives_reject_and_is_allowed(
        monkeypatch, tmp_path):
    """The link repair: the clean copy gains `Smith2020` and its `txt`,
    Compare carries both into the redline, and rejecting cannot remove
    them. That is not a loss and not a duplicate."""
    added = _marked("Smith2020", "Smith2020txt")
    sources = _pair(tmp_path, clean_document(), added)

    report, _ = _build(monkeypatch, added, sources)

    assert report.structure_diff == []


def test_a_bookmark_the_clean_copy_DELETED_survives_accept_and_is_allowed(
        monkeypatch, tmp_path):
    """The mirror: the clean copy drops a deleted entry's bookmarks and
    Compare keeps them, so the accepted view has two the clean copy does
    not — exactly two the original had."""
    had = _marked("McNemar1947", "McNemar1947txt")
    sources = _pair(tmp_path, had, clean_document())

    report, _ = _build(monkeypatch, had, sources)

    assert report.structure_diff == []


def test_a_bookmark_NEITHER_document_has_is_still_refused(monkeypatch,
                                                          tmp_path):
    sources = _pair(tmp_path, clean_document(), clean_document())

    with pytest.raises(PackageError, match="gained 'Stray2001'"):
        _build(monkeypatch, _marked("Stray2001"), sources)


def test_a_bookmark_LOST_on_either_side_is_still_refused(monkeypatch,
                                                        tmp_path):
    """The DSI class: both documents keep `Moran1950`, the redline drops
    it — rejecting cannot give it back, and neither can accepting."""
    kept = _marked("Moran1950")
    sources = _pair(tmp_path, kept, kept)

    report, _ = _build(monkeypatch, clean_document(), sources,
                       reject_check=False, accept_check=False)

    assert report.structure_diff == [
        "rejected: bookmarkStart: lost 'Moran1950'",
        "accepted: bookmarkStart: lost 'Moran1950'"]


def test_Words_own_bookmarks_are_judged_by_COUNT(monkeypatch, tmp_path):
    """`_Ref`/`_Hlk` names are re-minted on every save: the same bookmark
    under a new name is not a loss and a gain."""
    sources = _pair(tmp_path, _marked("_Ref111"), _marked("_Ref111"))

    report, _ = _build(monkeypatch, _marked("_Ref222"), sources)

    assert report.structure_diff == []


def _cross_referenced(*names: str) -> str:
    """`_marked(*names)` with a `REF _Ref111 \\h` field after the sentence."""
    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> REF _Ref111 \\h '
             '</w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:t>Table 1</w:t></w:r>'
             '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    return _marked(*names).replace("</w:p>", field + "</w:p>", 1)


def test_a_LOST_Ref_a_field_still_names_is_refused_whatever_the_count(
        monkeypatch, tmp_path):
    """Review of 2026-09-24. `_` names are judged by count because Word
    re-mints them — but a lost `_Ref111` that a REF field still names is
    not re-minted, it is "Error! Reference source not found." on the next
    field update. Counted, the two `_Ref` targets the clean copy added
    hid it: 1 -> 2 sits inside the allowance."""
    sources = _pair(tmp_path, _cross_referenced("_Ref111"),
                    _cross_referenced("_Ref222", "_Ref333"))

    report, _ = _build(monkeypatch, _cross_referenced("_Ref222", "_Ref333"),
                       sources, reject_check=False, accept_check=False)

    assert report.structure_diff == [
        "rejected: bookmarkStart: lost '_Ref111'"]


def test_a_lost_Ref_NOTHING_names_is_still_judged_by_count(monkeypatch,
                                                           tmp_path):
    """The allowance stays for what it was for: an unreferenced `_Ref`
    under a new name is Word re-minting, not a loss."""
    sources = _pair(tmp_path, _marked("_Ref111"),
                    _marked("_Ref222", "_Ref333"))

    report, _ = _build(monkeypatch, _marked("_Ref222", "_Ref333"), sources)

    assert report.structure_diff == []


def test_build_STAMPS_the_bookmarks_the_clean_copy_added(monkeypatch,
                                                        tmp_path):
    """What `revision validate` judges a gained bookmark against — it has
    no clean copy, and this is the one call that does. One entry per
    extra occurrence, so a duplicate is recorded as one."""
    sources = _pair(tmp_path, _marked("Moran1950"),
                    _marked("Moran1950", "Smith2020", "Smith2020txt"))

    _build(monkeypatch, _marked("Moran1950", "Smith2020", "Smith2020txt"),
           sources)

    assert tracked._guard.bookmarks_added(sources[2]) == [
        "Smith2020", "Smith2020txt"]


def test_the_structure_refusal_can_be_turned_off_like_the_other_one(
        monkeypatch, sources):
    """`reject_check=False` builds the file anyway, which is what a
    person inspecting the damage needs."""
    doubled = clean_document().replace(
        "</w:body>", _table_xml() + _table_xml() + "</w:body>")

    report, _ = _build(monkeypatch, doubled, sources, reject_check=False,
                       accept_check=False)

    assert report.structure_diff, "still reported, just not fatal"
    assert any("tbl:" in d for d in report.structure_diff)


# --- the structure counts, read directly (2026-08-19) -------------------
#
# `structure_counts` and `structure_diff` were added on 2026-08-18 to
# close the S1 where Word's Compare duplicated a moved table and every
# gate passed. They went in through `build` and `validate`, which is
# where they matter, and were never called directly — so the module came
# back at 12.0 % with 7 of its 39 survivors in a two-line function.
#
# Both are public (`__all__`), and a per-paper script is the caller the
# docstring is written for.


def test_a_tag_MISSING_from_a_count_reads_as_zero():
    """`was.get(tag, 0)`. `structure_counts` fills every tag in, but the
    function is public and takes any two mappings — a script that
    counted only the tags it cared about is the ordinary caller, and a
    default of anything but zero turns "this document has no tables"
    into "this document has one"."""
    from docxkit.tracked import structure_diff

    assert structure_diff({"tbl": 1}, {}) == ["tbl: 1 -> 0"]
    assert structure_diff({}, {"tbl": 1}) == ["tbl: 0 -> 1"]
    assert structure_diff({}, {}) == []


def test_the_diff_reads_in_TAG_order_not_dict_order():
    """The order is STRUCTURE_TAGS', so two runs over two documents
    produce lines a person can compare down the column."""
    from docxkit.tracked import STRUCTURE_TAGS, structure_diff

    was = {"drawing": 2, "tbl": 27}
    now = {"drawing": 1, "tbl": 28}

    assert structure_diff(was, now) == ["tbl: 27 -> 28", "drawing: 2 -> 1"]
    assert STRUCTURE_TAGS.index("tbl") < STRUCTURE_TAGS.index("drawing")


def test_counts_that_are_EQUAL_and_large_are_not_a_difference():
    """`!=`, not `is not`. Python caches small integers and creates the
    rest, so two counts of 300 are equal and are not the same object —
    and under `is not` every long manuscript reports a structural change
    that did not happen, which `build` raises on under `reject_check`.
    A paper with 300 table rows is an ordinary paper."""
    from docxkit.tracked import structure_diff

    was = {"tr": len(range(300))}
    now = {"tr": len([0] * 300)}

    assert was["tr"] == now["tr"] and was["tr"] is not now["tr"]
    assert structure_diff(was, now) == []


def test_the_counts_come_from_every_text_bearing_part():
    """A bookmark in a footnote is a bookmark, and a batch that edits
    only the notes must not read as a batch that changed nothing."""
    from docxkit.tracked import structure_counts

    parts = make_parts(
        para(run("body")),
        footnotes=notes("footnotes",
                        '<w:footnote w:id="2"><w:p>'
                        '<w:bookmarkStart w:id="4" w:name="InANote"/>'
                        "<w:r><w:t>note</w:t></w:r></w:p></w:footnote>"))

    assert structure_counts(parts)["bookmarkStart"] == 1


def test_a_row_PROPERTY_is_not_counted_as_a_row():
    """`<w:tr\\b` does not match `<w:trPr` — there is no word boundary
    between two word characters — and a table whose rows all carry
    properties would otherwise count double."""
    from docxkit.tracked import structure_counts

    parts = make_parts(
        "<w:tbl><w:tblPr/><w:tr><w:trPr><w:cantSplit/></w:trPr>"
        "<w:tc><w:tcPr/><w:p/></w:tc></w:tr></w:tbl>")

    counts = structure_counts(parts)
    assert (counts["tbl"], counts["tr"], counts["tc"]) == (1, 1, 1)


# --- what `untracked` prints, and how it matches --------------------------

def test_a_long_document_matches_without_the_junk_heuristic():
    """`autojunk=False`. difflib treats an element appearing in more
    than 1 % of a sequence longer than 200 as junk and refuses to anchor
    on it — and a manuscript is exactly that: two hundred paragraphs of
    which many repeat. With the heuristic on, the ONE paragraph the
    batch really changed is reported along with a stretch of its
    neighbours, and the finding a person is meant to act on is buried in
    a list of paragraphs that are identical on both sides."""
    same = [para(run("The same boilerplate sentence.")) for _ in range(250)]
    baseline = _parts(*same)
    changed = list(same)
    changed[200] = para(run("The one sentence the batch rewrote."))
    batch = _parts(*changed)

    found = untracked(batch, baseline)

    # an insert at 200 and the delete that balances it at the end: two
    # findings, not the eight the limit truncates a whole-tail replace to
    assert len(found) == 2
    assert found[0].index == 200
    assert found[0].batch == "The one sentence the batch rewrote."


def test_the_printed_finding_cuts_each_side_at_seventy_characters():
    """A finding is one line per side in a report a person reads next to
    the document; a paragraph printed whole would be the manuscript."""
    long_line = ("The decomposition is sensitive to the ranking of its "
                 "components, which the appendix sets out in full.")
    baseline = _parts(para(run(long_line)))
    batch = _parts(para(run(long_line.replace("sensitive", "robust"))))

    (found,) = untracked(batch, baseline)

    lines = str(found).splitlines()
    assert lines[0] == ("body ¶1: baseline 'The decomposition is sensitive "
                        "to the ranking of its components, which'")
    assert lines[1].endswith("'The decomposition is robust to the ranking "
                             "of its components, which th'")


def test_a_part_OUTSIDE_word_is_not_read_for_anchors():
    """`startswith("word/") AND endswith(".xml")` — both. Under `or`,
    `[Content_Types].xml` and `docProps/core.xml` join the walk, and a
    bookmark named in a custom XML data store reads as one the document
    carries. The collateral check then compares two different sets."""
    from docxkit.tracked import _anchors

    parts = make_parts(para('<w:bookmarkStart w:id="1" w:name="Real"/>'
                            + run("text") + '<w:bookmarkEnd w:id="1"/>'))
    parts["customXml/item1.xml"] = (
        b'<b:Sources><w:bookmarkStart w:name="NotOurs"/></b:Sources>')

    names, _targets = _anchors(parts)

    assert names == {"Real"}

# --- what the build SAYS when Word refuses ------------------------------
#
# Every COM call in the math pass is wrapped, and each one appends to
# `notes` — which `build` prints as "WARNING:" and puts on the report.
# None of those arms had a test: a Word that refuses one equation would
# have been silent, and the pass would have reported a clean resolve.


class _Refuses:
    """A COM object that raises on the one thing it is asked."""

    def __init__(self, what: str) -> None:
        self._what = what

    @property
    def Count(self):
        raise RuntimeError(f"Call was rejected by callee ({self._what})")


def test_a_document_whose_OMaths_cannot_be_read_says_so():
    """`doc.OMaths.Count` is the first COM call of the math pass, and
    Word refuses it on a document it is still repairing. The pass
    answers "nothing resolved" — which is right — and the reason has to
    reach the report, or the build says it resolved no math on a
    document full of it."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    notes: list[str] = []
    doc = type("D", (), {"OMaths": _Refuses("OMaths")})()

    assert _accept_math_via_equations(doc, notes) == T.MathOutcome(0)
    assert any("could not read doc.OMaths" in n for n in notes), notes


def test_a_revision_that_cannot_be_PLACED_is_named_and_stepped_over():
    """The offsets decide whether a revision is inside the equation or
    merely runs through it. When Word will not give them, the revision
    cannot be judged — so it is left tracked, named in the notes, and
    the walk carries on to the rest of the equation."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    class _NoSpan:
        accepted = False

        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee (Range)")

        def Accept(self):                            # pragma: no cover
            raise AssertionError("a revision that could not be placed "
                                 "must not be accepted")

    good = _Rev("of the equation", span=(120, 150))
    # the revisions are walked BACKWARDS, so the unplaceable one is
    # LAST in the list and FIRST in the walk — placed the other way
    # round `continue` and `break` do the same thing here
    doc = type("D", (), {
        "OMaths": _Count([_OMath(revisions=[good, _NoSpan()],
                                 span=(100, 200))])})()
    notes: list[str] = []

    out = _accept_math_via_equations(doc, notes)

    assert good.accepted, "the revision beside it is still resolved"
    assert out == T.MathOutcome(1)
    assert any("could not be placed" in n for n in notes), notes


def test_a_revision_word_will_not_ACCEPT_is_named_not_counted():
    """`Accept()` is where Word refuses a compare result it cannot
    serialise. The count must not include it — a build that reports
    "resolved 3" and resolved 2 sends the paper on with tracked math in
    it, which is the save hang this whole pass exists to avoid."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    class _Stubborn(_Rev):
        def Accept(self):
            raise RuntimeError("Word refused")

    doc = type("D", (), {
        "OMaths": _Count([_OMath(revisions=[_Stubborn(span=(120, 150))],
                                 span=(100, 200))])})()
    notes: list[str] = []

    assert _accept_math_via_equations(doc, notes) == T.MathOutcome(0)
    assert any("not accepted" in n for n in notes), notes


def test_a_revision_that_cannot_be_INSPECTED_is_named_by_number():
    """The other walk, the one that selects by what a revision
    CONTAINS. `rev.Range.OMaths` is a COM call per revision, and the
    number in the note is how a person finds the one Word choked on."""
    from docxkit import tracked as T

    class _Opaque:
        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee")

    doc = type("D", (), {
        "Revisions": _Count([_Opaque()]),
        "Comments": type("C", (), {"Count": 0, "Add": lambda *a: None})()})()
    notes: list[str] = []

    T._comment_and_accept_math_revisions(doc, lambda ctx: "x", None, notes)

    assert any("revision 1: could not be inspected" in n
               for n in notes), notes


def test_a_scaffold_that_cannot_be_SEEDED_says_what_it_costs():
    """The XML pass CLONES a Word-made comment, so a build that
    annotates and could not seed one fails later with ScaffoldMissing, a
    long way from here. The note is what connects the two."""
    from docxkit import tracked as T

    doc = type("D", (), {"Revisions": _Refuses("Revisions")})()
    notes: list[str] = []

    assert T._seed_scaffold(doc, lambda ctx: "x", None, notes) == 0
    assert any("no comment scaffold could be seeded" in n
               for n in notes), notes


def test_the_report_names_the_revisions_that_merely_OVERLAP_an_equation():
    """`math_kept` on the report, and the line `format()` prints for it.
    Accepting one of those applies its whole span — the LI7 collateral —
    so a build that keeps some has to say how many, or the number that
    matters is the one nobody sees."""
    report = tracked.BuildReport()
    report.math_resolved, report.math_kept = 4, 2

    out = report.format()

    assert "2 revision(s) overlap an equation" in out, out

def test_the_report_names_what_was_CARRIED_back_across_the_compare():
    """Compare drops the customXml data store on every rebuild and
    `build` puts it back. What went back is a change to the deliverable
    that no gate reports, so `format()` is the only place a person can
    read it."""
    report = tracked.BuildReport()
    report.carried = ["customXml/item1.xml"]
    report.carried_properties = ["title"]

    out = report.format()

    assert "carried back across the Compare: customXml/item1.xml" in out
    assert "properties carried back into core.xml" in out and "title" in out


def test_a_math_revision_word_will_not_accept_says_the_build_may_not_SAVE():
    """The other walk's `Accept()`, and the note that names the
    consequence rather than the call: Word cannot serialise a compare
    result containing tracked math, so a build that could not resolve
    one may hang on save. A person reading "resolved 3" learns nothing
    about the one that stayed."""
    from docxkit import tracked as T

    class _Stubborn:
        def __init__(self):
            self.Range = _MathRange("has math", omaths=1)

        def Accept(self):
            raise RuntimeError("Word refused")

    doc = type("D", (), {
        "Revisions": _Count([_Stubborn()]),
        "Comments": type("C", (), {"Count": 0,
                                   "Add": lambda *a: None})()})()
    notes: list[str] = []

    T._comment_and_accept_math_revisions(doc, lambda ctx: "x", None, notes)

    assert any("may fail to save" in n for n in notes), notes


def test_the_build_SAYS_what_it_resolved_and_what_it_kept(monkeypatch,
                                                          sources):
    """The two numbers the math pass produces, on the progress line a
    person watches. `math_kept` is the LI7 number — revisions that
    merely overlap an equation and stay tracked — and a build that
    resolved some and kept some has to say both, or the ones that
    stayed are invisible until the save hangs."""
    said: list[str] = []
    monkeypatch.setattr(tracked, "_resolve_math",
                        lambda *a, **kw: tracked.MathOutcome(3, 2))
    fake = _FakeWordModule(clean_document())
    monkeypatch.setattr(tracked, "_word", fake)

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=False, progress=said.append)

    assert (report.math_resolved, report.math_kept) == (3, 2)
    assert any("resolved 3 math revisions" in line for line in said), said
    assert any("2 revision(s) merely OVERLAP" in line for line in said), said


def test_the_build_says_which_math_GLYPH_it_put_back(monkeypatch, sources):
    """Word flattens U+2212 to an ASCII hyphen while deriving a redline
    — measured on AFI: 2 in the baseline, 0 in the build, the 57 in the
    prose untouched. `restore_math_glyphs` puts back only what a source
    really spells that way, and what it did is on the progress line,
    because nothing else in the build would ever mention it."""
    said: list[str] = []
    monkeypatch.setattr(tracked._hygiene, "restore_math_glyphs",
                        lambda *a: ["equation 3: U+2212 restored"])
    fake = _FakeWordModule(clean_document())
    monkeypatch.setattr(tracked, "_word", fake)

    report = tracked.build(sources[0], sources[1], sources[2],
                           verify_in_word=False, progress=said.append)

    assert report.restored_glyphs == ["equation 3: U+2212 restored"]
    assert any("restored math glyph — equation 3" in line
               for line in said), said

def test_an_unreachable_equation_does_not_end_the_math_pass():
    """`continue`, not `break`. `doc.OMaths(i).Range` is a COM call per
    equation and Word refuses one on a document it is repairing; the
    rest of the paper still has math in it. Under `break` the first
    refusal ends the pass, and the revisions after it stay tracked —
    which is the save hang this pass exists to avoid, reported as a
    clean resolve."""
    from docxkit import tracked as T
    from docxkit.tracked import _accept_math_via_equations

    class _Unreachable:
        @property
        def Range(self):
            raise RuntimeError("Call was rejected by callee")

    good = _Rev("of the equation", span=(120, 150))
    # OMaths is walked BACKWARDS, so the unreachable one is second in
    # the list and first in the walk
    doc = type("D", (), {"OMaths": _Count([
        _OMath(revisions=[good], span=(100, 200)), _Unreachable()])})()
    notes: list[str] = []

    out = _accept_math_via_equations(doc, notes)

    assert good.accepted, "the equation before it is still resolved"
    assert out == T.MathOutcome(1)
    assert any("unreachable" in n for n in notes), notes


def test_an_unclassified_math_revision_still_gets_the_GENERIC_comment():
    """`comment or generic or _comments.GENERIC`, and the last term is
    what makes the chain safe: the XML pass CLONES a Word-made comment,
    so this one exists to be cloned. `and` in its place hands Word None
    and the comment is never made — the build then fails much later
    with ScaffoldMissing."""
    from docxkit import tracked as T

    added: list[str] = []
    doc = type("D", (), {
        "Comments": type("C", (), {
            "Add": lambda _s, rng, text: added.append(text), "Count": 0})(),
        "Paragraphs": _Count([])})()
    rev = _Rev("some math")

    T._comment_revision(doc, rev, lambda ctx: None, None, [])

    assert added == [T._comments.GENERIC], added


def test_a_comment_word_refuses_names_THIRTY_characters_of_the_revision():
    """The note is how a person finds the revision Word would not
    comment, and a revision's text is a sentence: thirty characters is
    the quote, and uncut every refusal prints a paragraph."""
    from docxkit import tracked as T

    long_text = "The sentence this revision rewrites, at length."
    assert len(long_text) > 31

    class _Refusing:
        Count = 0

        def Add(self, rng, text):
            raise RuntimeError("Word refused")

    doc = type("D", (), {"Comments": _Refusing(),
                         "Paragraphs": _Count([])})()
    notes: list[str] = []

    T._comment_revision(doc, _Rev(long_text), lambda ctx: "x", None, notes)

    assert any(f'"{long_text[:30]}"' in n for n in notes), notes
    assert not any(long_text[:31] in n for n in notes), notes


def test_a_build_verifies_in_word_and_closes_the_compare_UNSAVED(
        monkeypatch, sources):
    """Two defaults nothing named. `verify_in_word=True` reopens the
    result and fails the build if Word had to repair it — passed
    explicitly by every test here, so the default was free — and the
    compare result is closed with `SaveChanges=0`, because 1 is
    wdSaveChanges and Word would write the scratch redline somewhere."""
    closes: list[dict[str, int]] = []
    checked: list[Path] = []

    class _Recording(_FakeDoc):
        def Close(self, SaveChanges: int = 0) -> None:
            closes.append({"SaveChanges": SaveChanges})
            self.closed = True

    class _RecordingWord(_FakeWordModule):
        def compare_documents(self, word, orig, rev, **kw):
            return _Recording()

    monkeypatch.setattr(tracked, "_word",
                        _RecordingWord(clean_document()))

    def fake_verify(path):
        checked.append(Path(path))
        return {"word": {"comments": 0, "revisions": 0},
                "comments_match": True}

    monkeypatch.setattr(tracked, "verify", fake_verify)

    tracked.build(sources[0], sources[1], sources[2])

    assert checked, "the default reopens the result in Word"
    assert closes == [{"SaveChanges": 0}], closes


# --- what is left in tracked.py, and why ---------------------------------
#
# Four survivors after this round, each argued rather than tested:
#
#   `if tag == "equal"` -> `is`. The tags come from difflib as its own
#   string literals; both sides are identifier-like constants, so
#   CPython hands out one object and the two spellings cannot disagree.
#   A test would pin the interning, not the walk.
#
#   `if len(out) >= limit` -> `==`, and -> `is`. `out` grows one finding
#   at a time and the check runs after each, so it meets the limit
#   exactly and never passes it; `is` adds the small-int cache, and a
#   caller asking for more than 256 findings has already given up on
#   reading them.
#
#   `if report.body_revisions != report.revisions` -> `<`. ARGUED WRONG,
#   and killed on 2026-09-17. The argument was "Word's count walks the
#   main story and the package's counts every text-bearing part, so the
#   body count is a subset by construction: it can be lower, never
#   higher" — but Word's figure was read BEFORE the math pass and the
#   package's after it, so every accepted equation revision made Word's
#   the higher one. That was a defect in the note as well as a hole in
#   the argument; both are in test_tracked_build.py
#   (`test_Word_counting_MORE_than_the_package_is_said_aloud_too`,
#   `test_the_count_note_reads_Word_AFTER_the_math_pass`). The identity
#   spelling of the same comparison is tested too, above the small-int
#   cache, because that one differs on any batch of 257 revisions or
#   more.


# --- the parts the gates SIMULATE, and the parts they used to READ -------
#
# `_simulate` accepts and rejects all three text-bearing parts — body,
# footnotes AND endnotes — and the walk that reads the result read two
# of them. So an accept-all defect was a finding in a footnote and
# invisible in an endnote, which is where several journals put the whole
# apparatus. Nothing else covers it: the tag counts do not move for a
# retyped sentence, `compare` runs on the deliverable rather than inside
# the build, and the reject gate's own text check stops at the same two
# parts. `revision.TEXT_PARTS` carries the same warning beside its own
# list — a count that reads only the body calls such a file truth.


def _endnote_parts(text: str, *, tracked_as: str | None = None
                   ) -> dict[str, bytes]:
    """A one-paragraph body and one endnote holding `text`."""
    inner = para(run(text)) if tracked_as is None else para(
        dele(tracked_as) + ins(text))
    return make_parts(
        para(run("The body says the same in every version of this.")),
        extra={"word/endnotes.xml": notes("endnotes",
                                          f'<w:endnote w:id="2">{inner}'
                                          "</w:endnote>")})


def test_an_untracked_change_in_an_ENDNOTE_is_a_finding():
    """The reject side: a sentence the batch retyped, in a part the
    walk did not open."""
    baseline = _endnote_parts("The elasticity is 0.35.")
    batch = _endnote_parts("The elasticity is 0.37.")

    (found,) = untracked(batch, baseline)

    assert found.part == "endnotes"
    assert found.baseline == "The elasticity is 0.35."
    assert found.batch == "The elasticity is 0.37."
    assert str(found).startswith("endnotes ¶1:")


def test_a_TRACKED_change_in_an_endnote_is_still_not_a_finding():
    """The other half, and the one that says the widened walk did not
    just start crying wolf: rejecting the batch restores the baseline
    endnote, so there is nothing to report."""
    baseline = _endnote_parts("The elasticity is 0.35.")
    batch = _endnote_parts("The elasticity is 0.37.",
                           tracked_as="The elasticity is 0.35.")

    assert untracked(batch, baseline) == []


def test_an_endnote_accept_all_does_not_reproduce_is_a_finding():
    """The accept side, which is the one that ships: the reader opens
    the accepted document, and until now nothing compared its endnotes
    against the clean copy at all."""
    revised = _endnote_parts("The elasticity is 0.37.")
    # accepting the batch leaves a mangled sentence behind — the shape
    # `hygiene.restore_math_glyphs` and `compare_collateral` both exist
    # for, in the one part neither gate was reading
    batch = _endnote_parts("The elasticity is 0.7.",
                           tracked_as="The elasticity is 0.35.")

    (missed,) = unaccepted(batch, revised)

    assert missed.part == "endnotes"
    assert missed.intended == "The elasticity is 0.37."
    assert missed.accepted == "The elasticity is 0.7."


def test_every_part_the_gates_SIMULATE_has_a_name_to_report_it_under():
    """`_PART_LABELS` is keyed by part name rather than zipped against
    `TEXT_PARTS`, so a fourth text-bearing part cannot arrive and be
    reported under its neighbour's label — it fails here instead."""
    from docxkit._xml import TEXT_PARTS
    from docxkit.tracked import _PART_LABELS

    assert set(_PART_LABELS) == set(TEXT_PARTS)
    assert len(set(_PART_LABELS.values())) == len(TEXT_PARTS)


# --- what ACCEPTING loses that neither other check can see ---------------
#
# BACKLOG S1, AFI 2026-08-19: a batch that moved four captions passed the
# text comparison and the collateral one while all four caption
# hyperlinks had been stripped. Each of those two is blind here by
# construction — `compare_collateral` looks at the redline AS BUILT,
# where the link is still present inside a deletion, and `unaccepted`
# compares paragraph TEXT, which a hyperlink does not carry.

_WHEN = 'w:id="7" w:author="R" w:date="2026-01-01T00:00:00Z"'


def _link_rebuilt_as_plain_text() -> tuple[dict[str, bytes],
                                           dict[str, bytes]]:
    """(clean copy, redline) for the shape Compare produces when it
    rebuilds a hyperlink as prose: the link deleted, the same words
    inserted beside it."""
    link = ('<w:hyperlink w:anchor="Table1"><w:r><w:delText>Table 1'
            "</w:delText></w:r></w:hyperlink>")
    redline = make_parts(
        f"<w:p><w:del {_WHEN}>{link}</w:del>"
        f'<w:ins {_WHEN}><w:r><w:t>Table 1</w:t></w:r></w:ins>'
        "<w:r><w:t> shows the gradient.</w:t></w:r></w:p>")
    revised = make_parts(
        '<w:p><w:hyperlink w:anchor="Table1"><w:r><w:t>Table 1</w:t></w:r>'
        "</w:hyperlink><w:r><w:t> shows the gradient.</w:t></w:r></w:p>")
    return revised, redline


def test_a_link_the_ACCEPT_loses_is_a_finding():
    """The accepted view is the deliverable — the document the author
    reads — and this is the only check that looks at its anchors."""
    from docxkit.tracked import _accept, _simulate, accepted_losses

    revised, redline = _link_rebuilt_as_plain_text()

    found = accepted_losses(revised, _simulate(redline, _accept))

    assert found == ["link LOST on accept: -> Table1"]


def test_the_other_two_checks_are_BLIND_to_it():
    """Stated as a test because it is the whole reason the third one
    exists: the words survive the accept, so the text comparison is
    silent, and the link is present in the redline as built, so the
    collateral comparison is too."""
    from docxkit.tracked import compare_collateral, unaccepted

    revised, redline = _link_rebuilt_as_plain_text()

    assert unaccepted(redline, revised) == []
    assert compare_collateral(revised, redline) == []


def test_a_BOOKMARK_inside_a_deletion_survives_the_accept():
    """The other carrier, and it needs no finding: `revisions` LIFTS a
    bookmark out of an element it is about to remove, which is the fix
    for "a moved paragraph carrying bookmarks loses them" two entries
    up in the same backlog.

    Worth a test beside the link one because it says why the link is
    the case that needed a check: nothing lifts a `w:hyperlink`, and
    nothing can — the element carries the words, so lifting it would
    leave the deleted text on the page."""
    from docxkit.tracked import _accept, _simulate, accepted_losses

    mark = ('<w:bookmarkStart w:id="3" w:name="Table1"/>'
            "<w:r><w:delText>Table 1</w:delText></w:r>"
            '<w:bookmarkEnd w:id="3"/>')
    redline = make_parts(f"<w:p><w:del {_WHEN}>{mark}</w:del>"
                         f'<w:ins {_WHEN}><w:r><w:t>Table 1</w:t></w:r>'
                         "</w:ins></w:p>")
    revised = make_parts('<w:p><w:bookmarkStart w:id="3" w:name="Table1"/>'
                         "<w:r><w:t>Table 1</w:t></w:r>"
                         '<w:bookmarkEnd w:id="3"/></w:p>')

    accepted = _simulate(redline, _accept)

    assert accepted_losses(revised, accepted) == []
    assert b'w:name="Table1"' in accepted["word/document.xml"]


def test_a_link_RE_REPRESENTED_in_the_other_form_is_not_a_loss():
    """Word's Compare rewrites a field-form hyperlink as an element,
    and that is harmless — the backlog says so in its own words. The
    anchors are compared by NAME through `internal_links`, which reads
    both forms, so the count of `w:hyperlink` elements moving is not
    what this asks."""
    from docxkit.tracked import accepted_losses

    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             "<w:r><w:instrText> HYPERLINK "
             + chr(92) + 'l "Table1" </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             "<w:r><w:t>Table 1</w:t></w:r>"
             '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    revised = make_parts(f"<w:p>{field}</w:p>")
    accepted = make_parts('<w:p><w:hyperlink w:anchor="Table1">'
                          "<w:r><w:t>Table 1</w:t></w:r></w:hyperlink></w:p>")

    assert accepted_losses(revised, accepted) == []


def test_a_batch_that_loses_nothing_reports_nothing():
    from docxkit.tracked import accepted_losses

    same = make_parts('<w:p><w:hyperlink w:anchor="Table1">'
                      "<w:r><w:t>Table 1</w:t></w:r></w:hyperlink></w:p>")

    assert accepted_losses(same, dict(same)) == []


# --- the equation Compare diffed INSIDE ---------------------------------


def _mangled_equation() -> tuple[dict[str, bytes], dict[str, bytes]]:
    """(clean copy, redline) for what Compare does to an inline field.

    It matches the common prefix `-0.` of `-0.20` and `-0.398` and
    emits the rest as an insertion BESIDE the old digits — so accepting
    reads `-0.20398` and rejecting reads `-0.20`, which is right. AFI
    R3/T3.2, 2026-08-19."""
    redline = make_parts(
        "<w:p><m:oMath><m:r><m:t>-0.</m:t></m:r><m:r><m:t>20</m:t></m:r>"
        f'<w:ins {_WHEN}><m:r><m:t>398</m:t></m:r></w:ins></m:oMath>'
        "<w:r><w:t> in every year.</w:t></w:r></w:p>")
    revised = make_parts(
        "<w:p><m:oMath><m:r><m:t>-0.398</m:t></m:r></m:oMath>"
        "<w:r><w:t> in every year.</w:t></w:r></w:p>")
    return revised, redline


def test_an_equation_the_accept_MANGLES_is_a_finding():
    """The number in the paper. Accepting gives `-0.20398` — the old
    digits with the new ones inserted after them — and that is the
    document the author reads."""
    from docxkit.tracked import _accept, _simulate, accepted_math

    revised, redline = _mangled_equation()

    found = accepted_math(revised, _simulate(redline, _accept))

    # The line also names the first character that differs, as of
    # 24.08: the two quoted forms are near-identical by construction —
    # that is what makes it a glyph problem — so a reader was being
    # asked to diff them by eye. Here the difference is a digit rather
    # than a lookalike, which is the case where the addition says least
    # and still costs nothing.
    (line,) = found

    assert line.startswith("equation 1: '-0.398' in the clean copy, "
                           "'-0.20398' accepted")
    assert "differs at char" in line, line


def test_every_OTHER_check_passes_that_document():
    """Which is why the number reached the paper. The reject view is
    CORRECT — it restores the original `-0.20` — so the reject gate is
    right to pass; the counts do not move; the equation renders; and
    `unaccepted` compares `w:t`, which an equation's characters are
    not."""
    from docxkit.tracked import (
        _accept,
        _reject,
        _simulate,
        accepted_losses,
        structure_counts,
        structure_diff,
        unaccepted,
    )

    revised, redline = _mangled_equation()
    accepted = _simulate(redline, _accept)

    assert unaccepted(redline, revised) == []
    assert accepted_losses(revised, accepted) == []
    assert structure_diff(structure_counts(revised),
                          structure_counts(accepted)) == []
    from docxkit.tracked import _math_texts
    assert _math_texts(_simulate(redline, _reject)) == ["-0.20"], (
        "the ORIGINAL number, which is what makes the reject gate right "
        "to pass")


def test_an_equation_the_accept_reproduces_is_not_a_finding():
    """A math edit applied to the built batch — the trade a paper makes
    for a redline it can hand back — comes out equal on both sides."""
    from docxkit.tracked import accepted_math

    same = make_parts("<w:p><m:oMath><m:r><m:t>-0.398</m:t></m:r>"
                      "</m:oMath></w:p>")

    assert accepted_math(same, dict(same)) == []


def test_an_equation_the_accept_LOSES_is_reported_as_a_count():
    """Position-by-position comparison needs the two lists to be the
    same length, and when they are not the count is the finding — an
    equation gone is not an equation changed."""
    from docxkit.tracked import accepted_math

    revised = make_parts("<w:p><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath>"
                         "<m:oMath><m:r><m:t>y</m:t></m:r></m:oMath></w:p>")
    accepted = make_parts("<w:p><m:oMath><m:r><m:t>x</m:t></m:r>"
                          "</m:oMath></w:p>")

    (found,) = accepted_math(revised, accepted)

    assert found == ("the clean copy has 2 equation(s) and accepting the "
                     "redline gives 1")


def test_the_gap_counts_the_grouped_revisions_by_SUBTRACTION():
    """Word's number and the package's differ by however many elements
    it folded into one. Anything that happens to agree on small numbers
    — and several bitwise spellings do — is a different sentence on the
    next batch."""
    parts = make_parts(
        para(ins(run("one"))) + para(ins(run("two")))
        + para(ins(run("three"))) + para(dele(run("go"))))

    said = tracked._revision_gap(parts, body=2, total=4)

    assert "the remaining 2 are in word/document.xml too" in said, said


def test_accepted_math_reports_an_equation_the_accept_ADDED():
    """Compare duplicates as readily as it drops. A count test that only
    looks one way calls the extra equation no difference at all."""
    eq = "<w:p><m:oMath><m:r><m:t>%s</m:t></m:r></m:oMath></w:p>"
    was = make_parts(eq % "x")
    now = make_parts(eq % "x" + eq % "y")

    said = tracked.accepted_math(was, now)

    assert said and "1 equation(s)" in said[0] and "gives 2" in said[0]


def test_accepted_losses_does_not_report_an_anchor_the_accept_GAINED():
    """A link the accepted view has and the clean copy does not is not
    a LOSS — Word re-representing a field as an element adds targets
    this way, and reporting them refuses a build for nothing."""
    linked = ('<w:hyperlink w:anchor="Extra"><w:r><w:t>x</w:t>'
              "</w:r></w:hyperlink>")
    was = make_parts(para(run("text")))
    now = make_parts(para(run("text"), linked))

    assert tracked.accepted_losses(was, now) == []


def test_the_ANCHOR_refusal_carries_the_paragraphs_when_there_are_any():
    """An anchor does not go missing on its own. On Aging_Well a scored
    move truncated a paragraph in the accepted view — a clause, a link
    and the sentence after it — and the build refused with `link LOST on
    accept: -> Ravallion2011`, the smallest visible symptom of it. The
    round was spent on the link. The refusal now hands over the
    paragraphs and names the switch that fixed that case."""
    report = tracked.BuildReport()
    report.accepted_losses = ["link LOST on accept: -> Ravallion2011"]
    report.unaccepted = [tracked.Unaccepted(
        "body", 5, "The floor itself is set weakly relatively to income.",
        "The floor itself is set weakly relatively")]

    with pytest.raises(PackageError) as caught:
        tracked._refuse_accept_side(report, "v12.docx")

    said = str(caught.value)
    assert "1 paragraph(s) also differ" in said
    assert "set weakly relatively to income" in said, "quote BOTH sides"
    assert "--no-moves" in said


def test_the_anchor_refusal_is_silent_about_paragraphs_when_there_are_none():
    """The common case is an anchor loss alone, and a sentence about
    paragraphs that do not differ sends the reader looking for them."""
    report = tracked.BuildReport()
    report.accepted_losses = ["bookmark LOST on accept: Table1"]

    with pytest.raises(PackageError) as caught:
        tracked._refuse_accept_side(report, "v12.docx")

    assert "also differ" not in str(caught.value)


def test_the_MATH_ONLY_refusal_speaks_only_about_the_maths():
    """It runs after the glyph restore, when the other two have already
    been asked and answered. Letting it re-raise the anchor loss reports
    the same finding twice and blames the equation pass for it."""
    report = tracked.BuildReport()
    report.accepted_losses = ["link LOST on accept: -> Table1"]
    report.accepted_math = ["equation 1: '-0.20' in the clean copy"]

    with pytest.raises(PackageError, match="EQUATIONS"):
        tracked._refuse_accept_side(report, "v12.docx", math_only=True)


# tracked's other survivors from the 2026-08-21 round, argued:
#
# `if grouped > 0` -> `!= 0` in `_revision_gap`. Argued as "the body
# figure is a subset by construction", the same argument as the note
# above, and WRONG for the same reason: the body figure was read before
# the math pass, so it could exceed the body's elements and `!= 0` would
# name a negative remainder. Killed by the tests that give Word the
# higher number: `test_Word_counting_MORE_than_the_package_is_said_
# aloud_too` in test_tracked_build.py, and `test_Word_counting_MORE_
# body_revisions_than_the_package_groups_none` in test_tracked_edges.py.
#
# `zip(was, now, strict=True)` -> `strict=False` in `accepted_math`: the
# length check three lines above has already returned when they differ,
# so there is no ragged pair left for either spelling to meet.


# --- Word MERGING a changed footnote (BACKLOG S2, 2026-08-23) ------------
#
# A footnote whose text changed comes back as a wholly-deleted copy plus
# a wholly-inserted one — right — with the SAME character-merged string
# written into both. On LI7 `(4)` and `(A1.1)` both came back `(4A1.1)`,
# a string in neither document, so accept-all and reject-all each
# produce text that exists nowhere.
#
# The entry filed it as undetectable. It is detected twice, and these
# pin that: a person cannot see it (Review > Next walks the body, and
# footnote balloons are hidden under Simple Markup), so the only thing
# standing between the merge and the deliverable is these two gates.

_FN_WAS = "The decomposition in (4) weights each component."
_FN_NOW = "The decomposition in (A1.1) weights each component."
#: The divergent fragment in a run of its own, which is the shape that
#: makes the damage machine-detectable at all.
_FN_PIECES = ("The decomposition in (", "4", "A1.1) weights each component.")
_STAMP = 'w:author="R" w:date="2026-08-23T00:00:00Z"'


def _one_run(tag: str) -> str:
    return "<w:r>" + "".join(
        f"<w:{tag}>{t}</w:{tag}>" for t in _FN_PIECES) + "</w:r>"


def _run_each(tag: str) -> str:
    return "".join(f"<w:r><w:{tag}>{t}</w:{tag}></w:r>" for t in _FN_PIECES)


def _merged_note(shape, one_para: bool) -> str:
    gone = f'<w:del w:id="90" {_STAMP}>{shape("delText")}</w:del>'
    added = f'<w:ins w:id="91" {_STAMP}>{shape("t")}</w:ins>'
    body = (f"<w:p>{gone}{added}</w:p>" if one_para
            else f"<w:p>{gone}</w:p><w:p>{added}</w:p>")
    return f'<w:footnote w:id="2">{body}</w:footnote>'


def _note_parts(inner: str) -> dict[str, bytes]:
    return make_parts(para(run("The paper as it stands.")),
                      footnotes=notes("footnotes", inner))


def _plain_note(text: str) -> str:
    return f'<w:footnote w:id="2">{para(run(text))}</w:footnote>'


@pytest.mark.parametrize("shape", [_one_run, _run_each],
                         ids=["one-run", "run-per-fragment"])
@pytest.mark.parametrize("one_para", [True, False],
                         ids=["one-paragraph", "two-paragraphs"])
def test_a_MERGED_footnote_is_caught_on_both_sides(shape, one_para):
    """Whichever way Compare spells it. The fragments arrive as one run
    with three children or as a run each, and the two copies land in one
    paragraph or in two — four spellings, and a gate that caught only
    the one that was reported would be worth very little."""
    redline = _note_parts(_merged_note(shape, one_para))

    rejected = untracked(redline, _note_parts(_plain_note(_FN_WAS)))
    accepted = unaccepted(redline, _note_parts(_plain_note(_FN_NOW)))

    assert rejected, "reject-all must not reproduce the original silently"
    assert accepted, "accept-all must not reproduce the clean copy silently"
    assert any("4A1.1" in str(u) for u in rejected), rejected
    assert any("4A1.1" in str(u) for u in accepted), accepted


def test_the_merged_footnote_gate_names_the_PART_not_just_the_paragraph():
    """`(4A1.1)` is a string in neither document, and a reader told only
    "paragraph 1 differs" would look in the body, where nothing is
    wrong. The footnote is the one place a person cannot check by eye,
    so the note has to say where to look."""
    redline = _note_parts(_merged_note(_one_run, True))

    (found,) = untracked(redline, _note_parts(_plain_note(_FN_WAS)))

    assert "footnote" in str(found).lower(), found


def test_the_accept_refusal_does_not_name_a_flag_the_CLI_LACKS():
    """It said "Pass accept_check=False", which is a Python keyword
    argument. The CLI's flags are `--allow-math-resolve`,
    `--allow-stale-baseline`, `--keep-math`, `--allow-pending-baseline`
    and `--force`, none of which is it — so a CLI reader had been told
    to do something the CLI does not offer, and the honest workaround
    (a throwaway script importing `docxkit.revision`) is the thing the
    CLI exists to avoid."""
    said = tracked._ACCEPT_ESCAPE

    assert "tracked.build(" in said, "name where the switch really lives"
    assert "from Python" in said
    assert "the CLI has no flag for this" in said
    assert "usually right" in said, (
        "the refusal was RIGHT on Life_Expectancy — two unterminated "
        "bookmarks — and the repair was the manuscript, not the switch")


def test_every_accept_side_refusal_carries_the_same_escape():
    """One sentence, not four that can drift.

    Counted against the RAISES rather than pinned at a number: it was
    pinned, and a third refusal — the orphan note — then failed this
    test for carrying the escape correctly, which is the opposite of
    what it is for.

    The math refusal used to be an exception here, on the grounds that
    its repair is a math edit rather than a switch. It named the switch
    anyway — "or pass accept_check=False to build the file anyway" — so
    the exception's own reason did not hold, and the wording was the
    Python keyword argument `_ACCEPT_ESCAPE` exists to stop quoting at a
    CLI reader. The refusal audit of 2026-09-18 found it standing.

    This test did not, because it read the SOURCE and the sentence was
    split across two lines: `accept_check=` ended one and `False to
    build` began the next, so neither the substring nor the regex could
    match what the message actually says. The lines are joined first
    now — a search for what a reader sees has to read what a reader
    sees.
    """
    import re as _re

    from docxkit import _tracked_report  # the refusal's home since 09-11

    src = Path(_tracked_report.__file__).read_text(encoding="utf-8")
    body = src.split("def _refuse_accept_side")[1].split("\ndef ")[0]
    said = _re.sub(r'"\s*\n\s*(?:\+ )?f?"', "", body)     # as it prints

    assert "accept_check=False to build" not in said
    assert body.count("_ACCEPT_ESCAPE") == body.count("raise PackageError")
    assert not _re.search(r"(?i)pass accept_check", said)
