"""The survivors of the first `_tracked_gates` and `_tracked_report` sweeps
(2026-09-13).

9.5 % and 10.1 %, and the shapes the suite had not built: an anchor the
redline ADDS rather than loses, an equation longer than its quote, a
difference whose clean side sorts first, two strings that part only in
length, a paper with more than 256 equations, Word counting MORE body
revisions than the package holds, and the accept-side refusals for a
lost note and an unaccepted paragraph, which no build in the suite had
tripped.
"""
from __future__ import annotations

import re
from collections import Counter

import pytest
from conftest import ins, make_parts, para, run
from test_tracked_gates import MARK, _compare_output

from docxkit._report import Report, Severity
from docxkit._tracked_gates import (
    _first_difference,
    _revision_gap,
    _same_props,
    accepted_losses,
    accepted_math,
    bookmark_changes,
    cell_property_changes,
    compare_collateral,
    return_note_spaces,
    unaccepted,
)
from docxkit._tracked_report import (
    _ACCEPT_ESCAPE,
    ADVISORY,
    BLOCKING,
    BuildReport,
    _refuse_accept_side,
)
from docxkit._xml import DOCUMENT
from docxkit.errors import PackageError

# --- what the redline loses, and not what it gains --------------------------


def test_a_bookmark_the_redline_ADDS_is_not_reported_as_lost():
    """Dropped means in the clean copy and gone from the other: a set
    difference, one way. An anchor only the redline or the accepted view
    carries is not a loss."""
    clean = make_parts(para(run("Text.")))
    marked = make_parts(para('<w:bookmarkStart w:id="1" w:name="Added"/>'
                             + run("Text.") + '<w:bookmarkEnd w:id="1"/>'))

    assert compare_collateral(clean, marked) == []
    assert accepted_losses(clean, marked) == []


# --- equations ---------------------------------------------------------------


def _equations(*texts: str) -> dict[str, bytes]:
    return make_parts("".join(f"<w:p><m:oMath><m:r><m:t>{t}</m:t></m:r>"
                              "</m:oMath></w:p>" for t in texts))


def test_an_equation_is_quoted_at_SIXTY_characters_either_side_first():
    """The clean copy's hyphen sorts BELOW the accepted minus sign, and the
    difference sits past the quote, which is sixty characters of each."""
    clean = "x" * 64 + "-" + "y" * 5
    accepted = "x" * 64 + "−" + "y" * 5

    assert accepted_math(_equations(clean), _equations(accepted)) == [
        f"equation 1: {clean[:60]!r} in the clean copy, {accepted[:60]!r} "
        "accepted — differs at char 64: '-' U+002D (HYPHEN-MINUS) vs '−' "
        "U+2212 (MINUS SIGN)"]


def test_257_equations_that_all_agree_are_no_finding():
    """Past 256 two equal counts are two objects, so only equality can say
    the clean copy and the accepted view hold as many equations."""
    both = _equations(*["a + b"] * 257)

    assert accepted_math(both, both) == []


@pytest.mark.parametrize(("was", "now", "said"), [
    ("−x", "−y", " — differs at char 1: 'x' U+0078 (LATIN SMALL LETTER X) "
                 "vs 'y' U+0079 (LATIN SMALL LETTER Y)"),
    ("ab", "a", " — one is longer: 'b' U+0062 (LATIN SMALL LETTER B) at "
                "char 1"),
    ("a", "ab", " — one is longer: 'b' U+0062 (LATIN SMALL LETTER B) at "
                "char 1"),
], ids=["an equal minus sign first", "the clean side longer",
        "the accepted side longer"])
def test_the_first_difference_is_named_by_CODEPOINT_or_by_the_longer_side(
        was, now, said):
    """A minus sign read twice is two objects, so characters are compared by
    value; and two strings that agree as far as the shorter goes differ in
    the character the longer one carries next, on either side."""
    assert _first_difference(was, now) == said


# --- the revision count Word and the package disagree on ---------------------


def test_Word_counting_MORE_body_revisions_than_the_package_groups_none():
    """Grouping explains Word counting FEWER elements than the body holds;
    counting more is not grouping, and no remainder is offered."""
    parts = make_parts(para(ins("one")) + para(ins("two"))
                       + para(ins("three")))

    assert _revision_gap(parts, 5, 3) == (
        "  (Word counts 5 in the body; the package holds 3 revision "
        "elements)")


# --- the accept-side refusals ------------------------------------------------


@pytest.mark.parametrize(("field", "words"), [
    ("orphan_notes", "note definition(s) with nothing referencing them"),
    ("unaccepted", "paragraph(s) differ"),
])
def test_the_accept_side_REFUSES_a_lost_note_and_an_unaccepted_paragraph(
        field, words):
    """Both refusals name the escape last, and neither fires when only the
    equations are being judged."""
    report = BuildReport()
    setattr(report, field, ["the finding"])

    with pytest.raises(PackageError, match=re.escape(words)) as refused:
        _refuse_accept_side(report, "clean.docx")

    assert str(refused.value).endswith(_ACCEPT_ESCAPE)
    _refuse_accept_side(report, "clean.docx", math_only=True)


# --- which lists block, said once --------------------------------------------


def _list_fields() -> set[str]:
    return {name for name, value in vars(BuildReport()).items()
            if isinstance(value, list)}


def test_every_list_on_the_report_is_BLOCKING_or_ADVISORY_and_not_both():
    """The table is the one place a reader learns which findings block.
    A list added to the report without a side is the omission
    `compare-probe` shipped with — five of seven read by hand."""
    blocking = {field for field, _ in BLOCKING}

    assert blocking | set(ADVISORY) == _list_fields()
    assert not blocking & set(ADVISORY)
    assert len(blocking) == len(BLOCKING)


def test_whatever_the_accept_side_REFUSES_on_is_in_the_table():
    """Asked of the refusal itself rather than copied from it: plant each
    list alone and see whether `_refuse_accept_side` raises."""
    refused = set()
    for field in sorted(_list_fields() - {"phases"}):
        report = BuildReport()
        setattr(report, field, ["the finding"])
        try:
            _refuse_accept_side(report, "clean.docx")
        except PackageError:
            refused.add(field)

    assert refused == {"accepted_losses", "orphan_notes", "unaccepted",
                       "accepted_math"}
    assert refused <= {field for field, _ in BLOCKING}


def test_blocking_labels_every_item_of_every_blocking_list_IN_ORDER():
    empty = BuildReport()
    assert empty.blocking() == [] and empty.ok

    report = BuildReport()
    for field, _ in BLOCKING:
        setattr(report, field, [f"{field} 1", f"{field} 2"])
    report.dropped = ["advisory, never a finding"]

    assert [str(f) for f in report.blocking()] == [
        f"{label} {field} {n}" for field, label in BLOCKING for n in (1, 2)]
    assert not report.ok
    assert all(f.severity is Severity.BLOCKING for f in report.blocking())


def test_the_report_names_parts_from_the_BASELINE_only_when_there_are_some():
    report = BuildReport()
    assert "come from the BASELINE" not in report.format()

    report.carried_from_baseline = ["customXml/item1.xml"]

    assert ("come from the BASELINE: customXml/item1.xml"
            in report.format())


def test_the_report_IS_a_Report_and_its_advisories_do_not_block():
    """The shared protocol, and the other side of the table: a dropped
    part is a WARNING a person should look at, a returned space a NOTE,
    and neither makes the build not ok."""
    report = BuildReport()
    report.dropped = ["part LOST: customXml/item1.xml"]
    report.returned_spaces = ["returned the space after a note mark"]
    report.phases = [("compare", 1.0)]

    assert isinstance(report, Report)
    assert report.ok and report.blocking() == []
    assert [(f.code, f.severity) for f in report.findings()] == [
        ("DROPPED", Severity.WARNING), ("RETURNED_SPACES", Severity.NOTE)]


# --- the sweep of 2026-09-29: shapes the gates had not been handed -------
#
# `_tracked_gates` measured whole: 94 real survivors of 829, nearly all in
# code written after its last sweep (09-14) — the cell-property gate, the
# bookmark-by-name gate, the note-space repair. Each block below builds
# the shape its survivors needed; the argued rest is in equivalents.toml.

_NOTE_CLEAN = para(run("(Latre 2017)."), MARK,
                   run(" Japan suspended.", preserve=True))


def _note_paras(n: int) -> tuple[str, str]:
    """`n` paragraphs of Compare's note-space shape, and the clean copy.

    Each with a word of its own: paragraphs of IDENTICAL text let the
    accept-side alignment pair a repaired paragraph with its twin, so
    the count does not fall and the repair is dropped — a fixture of
    copies once read as "only one space is ever returned"."""
    words = [f"Word{i}" for i in range(n)]
    return ("".join(_compare_output().replace("Japan", w) for w in words),
            "".join(_NOTE_CLEAN.replace("Japan", w) for w in words))


def test_EVERY_note_space_is_returned_not_only_the_last_one():
    """Two paragraphs, one space each. The count that decides whether a
    repair helped is `unaccepted` with no cap: capped at one, the first
    repair leaves the count at one and is thrown away, and so is every
    repair after it."""
    redline, fixed = _note_paras(2)
    parts, clean = make_parts(redline), make_parts(fixed)

    done = return_note_spaces(parts, clean)

    assert len(done) == 2
    assert unaccepted(parts, clean) == []


def test_thirty_two_note_spaces_are_all_returned():
    """Past thirty: a cap of 30 or 31 on the count reads 32 failing
    paragraphs as 30 before and after the first repair."""
    redline, fixed = _note_paras(32)
    parts, clean = make_parts(redline), make_parts(fixed)

    assert len(return_note_spaces(parts, clean)) == 32


def test_a_repair_that_HELPS_no_paragraph_is_not_kept():
    """`after < before`, not `<=`: the paragraph fails for a reason of its
    own, so giving the space back leaves the count where it was — and the
    redline has to stay as Compare wrote it."""
    parts = make_parts(_compare_output())
    before = parts[DOCUMENT]
    clean = make_parts(para(run("(Latre 2017)."), MARK,
                            run(" Japan suspended entirely.", preserve=True)))

    assert return_note_spaces(parts, clean) == []
    assert parts[DOCUMENT] == before


def test_a_repair_that_makes_things_WORSE_is_not_kept():
    """`<`, not `!=`: this clean copy really does mean `.[mark]Japan`, so
    the repair would break a paragraph that passes. Another paragraph
    fails, so the loop runs at all."""
    parts = make_parts(para(run("Unrelated words.")) + _compare_output())
    before = parts[DOCUMENT]
    clean = make_parts(para(run("Other words entirely."))
                       + para(run("(Latre 2017)."), MARK,
                              run("Japan suspended.")))

    assert return_note_spaces(parts, clean) == []
    assert parts[DOCUMENT] == before


def test_cell_properties_that_DIFFER_differ_in_either_order():
    """A base whose text sorts BELOW the view's: the equality short-cut
    and the canonical comparison were both read as `<` by the survivors,
    and every test had the other order."""
    assert not _same_props('<w:vAlign w:val="bottom"/>',
                           '<w:vAlign w:val="top"/>')
    assert not _same_props('<w:vAlign w:val="top"/>',
                           '<w:vAlign w:val="bottom"/>')


def test_attribute_ORDER_alone_is_not_a_cell_property_change():
    """Canonical XML compared by value: two bytes objects are equal and
    never the same object."""
    assert _same_props('<w:tcW w:w="900" w:type="dxa"/>',
                       '<w:tcW w:type="dxa" w:w="900"/>')


def test_a_property_under_an_UNDECLARED_prefix_reads_as_changed():
    """A prefix the wrapper does not declare cannot be canonicalised; the
    comparison says 'changed', and does not raise out of a build."""
    assert not _same_props("<w14:a/>", "<w14:b/>")


def _cells(*rows: tuple[str, ...]) -> str:
    """A table whose cells carry the given `w:tcPr` contents."""
    body = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:tcPr>{pr}</w:tcPr><w:p/></w:tc>"
                           for pr in row) + "</w:tr>" for row in rows)
    return f"<w:tbl>{body}</w:tbl><w:p/>"


_TOP = '<w:vAlign w:val="top"/>'
_BOTTOM = '<w:vAlign w:val="bottom"/>'


def test_a_view_with_FEWER_rows_is_left_to_the_structure_counts():
    base = make_parts(_cells((_TOP,), (_TOP,)))
    view = make_parts(_cells((_TOP,)))

    assert cell_property_changes(base, view) == []


def test_a_changed_cell_is_named_by_its_OWN_table_row_and_cell():
    """Past the first of each: `t ^ 1` and `t | 1` agree with `t + 1` at
    index 0 and nowhere after."""
    base = make_parts(_cells((_TOP,)) + _cells((_TOP, _TOP), (_TOP, _TOP)))
    view = make_parts(_cells((_TOP,)) + _cells((_TOP, _TOP), (_TOP, _BOTTOM)))

    assert cell_property_changes(base, view) == [
        "cell properties: 1 cell(s) differ — table 2 row 2 cell 2"]


@pytest.mark.parametrize(("changed", "tail"), [
    (4, "cell 4"),
    (5, "cell 4 and 1 more"),
    (9, "cell 4 and 5 more"),
], ids=["four-named", "one-more", "five-more"])
def test_the_first_FOUR_changed_cells_are_named_and_the_rest_counted(
        changed, tail):
    base = make_parts(_cells(tuple([_TOP] * 9)))
    view = make_parts(_cells(tuple([_BOTTOM] * changed
                                   + [_TOP] * (9 - changed))))

    (said,) = cell_property_changes(base, view)

    listed = ", ".join(f"table 1 row 1 cell {c}" for c in range(1, 5))
    assert said == (f"cell properties: {changed} cell(s) differ — "
                    + listed + tail.removeprefix("cell 4"))


def _marks(*names: str) -> str:
    return "".join(f'<w:bookmarkStart w:id="{i}" w:name="{n}"/>'
                   f'<w:bookmarkEnd w:id="{i}"/>'
                   for i, n in enumerate(names, 1))


def _field(instr: str) -> str:
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r><w:instrText xml:space="preserve">{instr}</w:instrText>'
            '</w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>1</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_a_lost_Ref_that_a_plain_REF_still_names_is_LOST():
    """`REF _Ref11` without `\\h`: not clickable, and still a field that
    prints "Error! Reference source not found." once its target goes."""
    base = make_parts(para(_marks("_Ref11") + run("x")))
    view = make_parts(para(run("x") + _field(" REF _Ref11 ")))

    assert "bookmarkStart: lost '_Ref11'" in bookmark_changes(base, view,
                                                              Counter())


def test_a_lost_Toc_a_PAGEREF_still_names_is_LOST_in_either_spelling():
    base = make_parts(para(_marks("_Toc22", "_Toc33") + run("x")))
    view = make_parts(para(run("x") + _field(' PAGEREF "_Toc22" \\h ')
                           + _field(" PAGEREF _Toc33 \\h ")))

    assert "bookmarkStart: lost '_Toc22', '_Toc33'" in bookmark_changes(
        base, view, Counter())


def test_a_referenced_Ref_that_was_KEPT_or_GAINED_is_not_lost():
    """`now < was`: a `_Ref` the view kept, or has one more of, is not
    lost however many fields name it."""
    base = make_parts(para(_marks("_Ref11") + _field(" REF _Ref11 ")))
    kept = make_parts(para(_marks("_Ref11") + _field(" REF _Ref11 ")))
    gained = make_parts(para(_marks("_Ref11", "_Ref11")
                             + _field(" REF _Ref11 ")))

    assert bookmark_changes(base, kept, Counter({"_Ref11": 1})) == []
    assert not any("lost" in line for line in bookmark_changes(
        base, gained, Counter({"_Ref11": 2})))


@pytest.mark.parametrize(("was", "other", "now", "gained"), [
    (1, 2, 3, True),        # one past what the witness explains
    (1, 2, 2, False),       # exactly what it explains
    (1, 4, 4, False),       # a larger allowance, used in full
], ids=["past-the-allowance", "at-it", "a-larger-one-used"])
def test_a_named_bookmark_GAINED_is_judged_by_what_the_witness_explains(
        was, other, now, gained):
    base = make_parts(para(_marks(*["Cite"] * was) + run("x")))
    view = make_parts(para(_marks(*["Cite"] * now) + run("x")))

    said = bookmark_changes(base, view, Counter({"Cite": other}))

    assert any("gained 'Cite'" in line for line in said) is gained


@pytest.mark.parametrize(("was", "other", "now", "flagged"), [
    (1, 1, 2, True),        # the witness allows none: one more is one too many
    (1, 2, 3, True),
    (1, 4, 4, False),
    (2, 3, 4, True),
    (1, 3, 2, False),       # inside the allowance, not at its edge
], ids=["no-allowance", "past-one", "a-larger-one-used", "base-of-two",
        "inside"])
def test_Word_s_own_names_are_judged_by_COUNT_within_the_allowance(
        was, other, now, flagged):
    base = make_parts(para(_marks(*[f"_Hlk{i}" for i in range(was)])
                           + run("x")))
    view = make_parts(para(_marks(*[f"_Hlk{9 + i}" for i in range(now)])
                           + run("x")))

    said = bookmark_changes(base, view, Counter({"_Hlk0": other}))

    assert any("Word's own _ names" in line for line in said) is flagged
