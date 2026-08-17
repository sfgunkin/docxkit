"""`footnote_audit`, stated as the lines it prints.

`renumber.py` was measured for the first time on 2026-08-17: 815
mutants, 15.1 % real survival — the least-pinned module measured so far
— and 40 of the 123 survivors are this one function. Thirty of those
forty sit on a single line, the message that says WHERE the ids stop
following the reference order.

That is the whole output for the case. A note out of order is invisible
in the document — the marks still render 1, 2, 3 down the page, because
Word numbers them by position — and the only sign is this audit line
naming the reference to look at. Nothing asserted it.

The window it prints is `referenced[max(at - 1, 0):at + 3]` and the
position is `at + 1`: four separate pieces of arithmetic in one f-string,
each of which a mutation can move without any other test noticing.
"""
from __future__ import annotations

from conftest import make_parts, note, notes, para, run

from docxkit.renumber import footnote_audit


def _doc(referenced: list[int], stored: list[int] | None = None
         ) -> dict[str, bytes]:
    """A body referencing notes in the given ORDER, and the notes."""
    body = "".join(
        f"<w:p>{run(f's{i}')}"
        f'<w:r><w:footnoteReference w:id="{i}"/></w:r></w:p>'
        for i in referenced)
    stored = sorted(referenced) if stored is None else stored
    return make_parts(body, footnotes=notes(
        "footnotes", *(note(f"note {i}", i) for i in stored)))


def test_ids_in_reference_order_are_no_finding():
    assert footnote_audit(_doc([1, 2, 3, 4])) == []


def test_a_document_with_no_notes_at_all_is_no_finding():
    """The early return. A paper without footnotes is not a paper with
    a problem, and an audit that says otherwise is one nobody runs."""
    assert footnote_audit(make_parts(para(run("no notes here")))) == []


def test_notes_with_NO_references_at_all_are_still_reported():
    """The early return is `not referenced AND not stored` — both, not
    either. A document whose body lost every reference still HAS its
    notes, and that is the loudest version of the problem, not a reason
    to stay quiet."""
    findings = footnote_audit(_doc([], [1, 2]))

    assert findings == ["note 1 has no reference in the body",
                        "note 2 has no reference in the body"], findings


def test_references_with_NO_notes_at_all_are_still_reported():
    """The mirror: a footnotes part that went missing leaves every
    reference dangling, and each one is a mark on the page pointing at
    nothing."""
    findings = footnote_audit(_doc([3, 4], []))

    assert findings == ["reference to footnote 3, which has no note",
                        "reference to footnote 4, which has no note"], findings


def test_a_note_nobody_references_is_named_by_its_id():
    assert footnote_audit(_doc([1, 2], [1, 2, 9])) == [
        "note 9 has no reference in the body"]


def test_a_reference_to_a_note_that_is_not_there_is_named_too():
    assert footnote_audit(_doc([1, 2, 8], [1, 2])) == [
        "reference to footnote 8, which has no note"]


def test_the_FIRST_descent_is_reported_with_its_window_and_position():
    """The line, exactly. Every number in it is arithmetic:

    * `at` is the index of the first pair where the ids go DOWN — the
      first descent, not the first ascent, and not the last of either;
    * the window is `[at - 1 : at + 3]`, so it shows the pair that
      broke and enough either side to recognise the place;
    * the position is `at + 1`, because an author counts references
      from one.

    The ids here descend at the fourth reference out of seven, which is
    far enough from both ends that a window slipping either way shows
    different numbers.
    """
    findings = footnote_audit(_doc([1, 2, 3, 5, 4, 6, 7]))

    assert findings == [
        "footnote ids do not follow reference order: [3, 5, 4, 6] at "
        "reference 4 of 7 — anything addressing a note BY ID is reading "
        "the wrong one"], findings


def test_a_descent_at_the_very_FIRST_reference_clamps_the_window():
    """`max(at - 1, 0)` is why: at index 0 there is nothing before the
    pair, and a slice from -1 would wrap to the END of the list and
    print the last ids as though they were the first."""
    findings = footnote_audit(_doc([2, 1, 3, 4]))

    assert findings == [
        "footnote ids do not follow reference order: [2, 1, 3] at "
        "reference 1 of 4 — anything addressing a note BY ID is reading "
        "the wrong one"], findings


def test_only_the_FIRST_descent_is_reported():
    """Two descents, one line: the audit names where to start, and the
    second is usually a consequence of the first."""
    findings = footnote_audit(_doc([1, 3, 2, 5, 4]))

    assert len(findings) == 1, findings
    assert "at reference 2 of 5" in findings[0], findings[0]


def test_a_REPEATED_id_is_not_a_descent():
    """The test is `b < a`, strictly. Two references to one note id are
    not out of order — they are the same note twice — and reporting the
    pair as the break would send the author to a reference that is fine
    while the real descent sits further down.
    """
    findings = footnote_audit(_doc([1, 2, 2, 4, 3], [1, 2, 3, 4]))

    assert "at reference 4 of 5" in findings[-1], findings


# `if referenced != sorted(referenced)` mutated to `>` is EQUIVALENT and
# left alive: ascending order is the lexicographically SMALLEST
# permutation of a list, so any list that differs from its own sorted
# form is also greater than it. The two comparisons cannot disagree.
