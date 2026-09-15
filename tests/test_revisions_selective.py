"""Selective accept/reject: apply the noise, keep the substance tracked."""
from __future__ import annotations

from conftest import NS, para, para_mark_ins, run

from docxkit.revisions import (
    accept,
    by_author,
    counts,
    reject,
    whitespace_only,
)


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def ins_by(author: str, text: str, rid: int) -> str:
    return (f'<w:ins w:id="{rid}" w:author="{author}" '
            f'w:date="2026-07-30T00:00:00Z">{run(text)}</w:ins>')


def del_by(author: str, text: str, rid: int) -> str:
    return (f'<w:del w:id="{rid}" w:author="{author}" '
            f'w:date="2026-07-30T00:00:00Z">'
            f"<w:r><w:delText>{text}</w:delText></w:r></w:del>")


MIXED = doc(para(run("Base "),
                 ins_by("Alice", "hers ", 1),
                 ins_by("Bob", "his ", 2),
                 del_by("Alice", "gone", 3),
                 run(" tail.")))


def test_accept_by_author_leaves_the_other_tracked():
    out = accept(MIXED, where=by_author("Alice"))
    # Alice's insertion is now plain text, her deletion applied
    assert "hers" in out and "<w:delText>gone" not in out
    # Bob's insertion is STILL tracked
    assert counts(out) == (1, 0)
    assert 'w:author="Bob"' in out


def test_reject_by_author_drops_hers_and_keeps_his_pending():
    out = reject(MIXED, where=by_author("Alice"))
    assert "hers" not in out
    assert "gone" in out and "<w:delText>" not in out   # restored to w:t
    assert counts(out) == (1, 0)                        # Bob still pending


def test_unselected_deletions_keep_their_deltext_on_reject():
    # the global delText->t conversion would de-track Bob's deletion
    # even though the predicate left it pending
    body = doc(para(run("A "), del_by("Alice", "hers", 1),
                    del_by("Bob", "his", 2)))
    out = reject(body, where=by_author("Alice"))
    assert "hers" in out and "<w:delText>his</w:delText>" in out


def test_whitespace_only_accepts_respacing_and_nothing_else():
    body = doc(para(run("Word"),
                    ins_by("R1", " ", 1),          # respacing noise
                    ins_by("R1", "substance", 2),
                    del_by("R1", " ", 3)))
    out = accept(body, where=whitespace_only)
    assert counts(out) == (1, 0)
    assert "substance" in out and 'w:author="R1"' in out


def test_a_paragraph_mark_is_not_whitespace():
    # accepting an inserted paragraph mark merges paragraphs — never a
    # trivial change, so whitespace_only must not select it
    body = doc(para(run("First")) + para_mark_ins())
    out = accept(body, where=whitespace_only)
    assert out.count("<w:p ") + out.count("<w:p>") == 2
    assert "<w:ins " in out or "<w:ins/" in out         # still pending


def test_paragraph_mark_merges_when_its_author_is_selected():
    body = doc(para(run("First")) + para_mark_ins())
    out = reject(body, where=by_author("Revision"))
    # rejecting the inserted mark joins the paragraphs back together
    assert out.count("<w:p ") + out.count("<w:p>") == 1


def test_moves_are_never_touched_under_a_predicate():
    body = doc(
        para('<w:moveFrom w:id="1" w:author="Alice" '
             'w:date="2026-07-30T00:00:00Z">'
             "<w:r><w:delText>moved text</w:delText></w:r></w:moveFrom>")
        + para('<w:moveTo w:id="2" w:author="Alice" '
               'w:date="2026-07-30T00:00:00Z">'
               + run("moved text") + "</w:moveTo>"))
    out = accept(body, where=by_author("Alice"))
    assert "<w:moveFrom" in out and "<w:moveTo" in out
    # the full pass still applies them
    full = accept(body)
    assert "<w:moveFrom" not in full and "<w:moveTo" not in full


def test_no_predicate_is_the_old_full_pass():
    assert accept(MIXED) == accept(MIXED, where=None)
    assert counts(accept(MIXED)) == (0, 0)


def test_a_revision_the_predicate_SKIPS_does_not_end_the_walk():
    """`continue`, not `break`, on the element a predicate did not
    select — and the skipped one has to come FIRST for a fixture to see
    it. Every selective test above puts the selected author first, where
    the two spellings agree.

    Under `break` a round that accepts one author's edits applies only
    those made before the first of anybody else's: the count reads
    "applied", the document still carries them, and the difference is
    invisible until the next build says the batch is not clean."""
    body = doc(para(run("Base "),
                    ins_by("Alice", "hers ", 1),
                    ins_by("Bob", "his ", 2),
                    ins_by("Bob", "and more ", 3)))

    out = accept(body, where=by_author("Bob"))

    assert "his " in out and "and more " in out, "both survive as text"
    assert counts(out) == (1, 0), "only Alice's stays tracked"
    assert 'w:author="Alice"' in out
    assert 'w:author="Bob"' not in out, "an accepted revision keeps no mark"


# --- what is left in the selective walk, and why ------------------------
#
# `if where is not None and tag in ("moveFrom", "moveTo"): continue` ->
# `break`, twice. The condition does not depend on the ELEMENT — the tag
# is fixed for the whole loop and `where` for the whole call — so either
# every item of that tag is skipped or none is, and stopping the walk at
# the first one skips exactly the same set. Argued rather than tested:
# no fixture can separate them.
#
# `not any(om is seen for seen in touched)` -> `om == seen`. lxml
# elements do not define equality, so `==` IS identity here. The `is
# not` spelling of the same line is a real defect and is tested.


def test_an_insertion_carrying_NO_TEXT_is_not_respacing_noise():
    """`r.text != ""`. A paragraph MARK is excluded a clause earlier —
    its kind is "paragraph-mark" — so this guard is about the other
    thing an insertion can be: a footnote reference, a drawing, a page
    break. None of them has text, all of them are substance, and a
    predicate written to sweep up respacing noise in bulk must not
    accept them on the author's behalf.

    A Compare of two drafts marks every new footnote this way."""
    note = ('<w:ins w:id="7" w:author="R1" w:date="2026-07-30T00:00:00Z">'
            '<w:r><w:footnoteReference w:id="3"/></w:r></w:ins>')
    body = doc(para(run("Base"), note))

    out = accept(body, where=whitespace_only)

    assert counts(out) == (1, 0), "the new footnote is still pending"
    assert "<w:ins " in out


# --- the whole sweep of 2026-09-15 ------------------------------------


def test_accepting_an_insertion_leaves_the_DELETION_inside_it_deleted():
    """`if mode == ORIGINAL` guards the one conversion a kept wrapper's
    unwrap makes: a rejected deletion's `w:delText` back to ordinary
    text. Read as `<=`, "final" qualifies too, and accepting an
    insertion converts every `w:delText` under it — including a
    deletion someone ELSE made inside the inserted text, which the
    predicate left pending. That deletion is still tracked and now reads
    as visible prose.

    Nested, and by two authors, because that is the only way a kept
    insertion still holds a deletion: without a predicate the pass
    removes the inner one before it unwraps the outer."""
    nested = ('<w:ins w:id="4" w:author="Alice" '
              'w:date="2026-07-30T00:00:00Z">'
              + run("kept ") + del_by("Bob", "struck", 5) + "</w:ins>")

    out = accept(doc(para(run("Base "), nested)), where=by_author("Alice"))

    assert "<w:delText>struck</w:delText>" in out, out
    assert counts(out) == (0, 1), "Bob's deletion is still pending"
