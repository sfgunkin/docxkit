"""Scope-ordered revision classification.

Matching a rule table against ``ctx.haystack`` labels a revision by whatever
signature sits anywhere nearby, so when two referee points edit one paragraph
the first rule wins both. On the AFI r2 round that mislabelled 4 of 19 points,
and a comment naming the wrong point is worse than none — it is what the
reviewer reads next to the change.
"""
from __future__ import annotations

from collections.abc import Callable

from docxkit.comments import RevisionContext, match

RULES = (
    ("unused capacity", "A7: transition rewritten."),
    ("growth slowdown", "A9: drag claim now attributed."),
)


def ctx(text: str, para: str = "", window: str = "",
        table: int | None = None) -> RevisionContext:
    return RevisionContext(text=text, para=para or text, window=window or para,
                           table_index=table, start=0, end=0)


def point(classify: Callable[[RevisionContext], str | None],
          c: RevisionContext) -> str:
    """The comment `classify` gives `c`, asserted present.

    Every caller here is checking WHICH point was named, so an unmatched
    revision is a failure of the test's premise, not the assertion.
    """
    out = classify(c)
    assert out is not None, f"no rule matched {c.text[:40]!r}"
    return out


def test_revision_text_wins_over_a_neighbour_in_the_same_paragraph():
    """The failure this exists to stop: A7 and A9 edit one paragraph, so a
    haystack match gives the A9 revision A7's comment."""
    shared = ("Whether this unused capacity translates ... "
              "the growth slowdown that")
    c = ctx(text="growth slowdown that", para=shared, window=shared)
    assert point(match(RULES), c).startswith("A9")
    # and the wide scope is exactly what would have got it wrong
    assert next(cm for sig, cm in RULES if sig in c.haystack).startswith("A7")


def test_falls_back_to_paragraph_then_window():
    by_para = point(match(RULES), ctx(text="0.42", para="the growth slowdown"))
    assert by_para.startswith("A9")
    by_window = point(
        match(RULES), ctx(text="0.42", para="0.42", window="unused capacity"))
    assert by_window.startswith("A7")


def test_rule_order_still_decides_within_one_scope():
    rules = (("alpha", "first"), ("beta", "second"))
    assert match(rules)(ctx("alpha and beta")) == "first"


def test_unmatched_returns_none():
    assert match(RULES)(ctx("nothing relevant")) is None


def test_an_EMPTY_scope_is_stepped_over_not_stopped_at():
    """`continue`, not `break`. The scopes are tried narrowest first,
    and the narrowest is often empty: a revision that changes only
    formatting, or one Word records as a property change, has no delta
    text of its own. Under `break` the walk ends on that empty string
    and the paragraph and window are never read — so the revisions with
    the least to say for themselves are exactly the ones that go
    unlabelled."""
    c = ctx(text="", para="the growth slowdown that", window="")

    assert point(match(RULES), c).startswith("A9")


def test_a_revision_in_a_table_with_NO_table_rules_is_simply_unmatched():
    """`tables and ctx.table_index is not None`. A paper that writes no
    table rules passes None, and every revision inside a table reaches
    this line; under `or` the guard is true for them and the lookup runs
    against None. What a classifier returns for an unlabelled revision
    is None — not an AttributeError from inside the annotate pass, which
    stops the whole round.

    Every fixture here that puts a revision in a table also supplies the
    rules for one."""
    assert match(RULES)(ctx("-0.037", table=8)) is None


def test_table_fallback_labels_bare_cells():
    """A regenerated table's cells are numbers no prose signature can match."""
    classify = match(RULES, {8: "A11: new Table A3."})
    assert point(classify, ctx("-0.037", table=8)).startswith("A11")
    assert classify(ctx("-0.037", table=None)) is None


def test_prose_rules_take_precedence_over_the_table_fallback():
    classify = match(RULES, {8: "A11: new Table A3."})
    assert point(classify, ctx("growth slowdown", table=8)).startswith("A9")


def test_signatures_match_through_typography():
    """Rules are written once; Word may have autocorrected the manuscript."""
    rules = (("workers' productivity", "A27: training split out."),)
    assert match(rules)(ctx("maintain workers’ productivity")) is not None
    assert match(rules, normalize=False)(
        ctx("maintain workers’ productivity")) is None
