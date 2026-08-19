"""The boundaries the link guards decide, asserted as VALUES.

Mutation testing `edit.py` on 2026-08-15: 1385 mutants, 17.3 % real
survival, and the survivors clustered on `label_extent` (58), `_outside`
(31) and `_restyle` (20). The harness reached 95 % of the module by
line, so those lines all RAN — nothing checked what they computed.

That matters here more than the percentage suggests. `label_extent`
decides where a field-form hyperlink's label ends, and `_outside`
decides whether an insertion may move outside a link or a bookmark.
Both exist to serve the two S1 entries about a link swallowing prose,
where the words read correctly, the anchor resolves, and only
`compare`'s review-not-gated HYPERLINK layer can see the damage. The
existing tests assert THAT a refusal happens; these assert WHERE the
boundary is, which is what the guard is actually computing — so an
off-by-one in the walk fails a test instead of shipping.
"""
from __future__ import annotations

import re

import pytest
from conftest import para, run

from docxkit import text_of
from docxkit._xml import RUN_RE
from docxkit.edit import (
    _outside,
    insert_in_para,
    italicize,
    replace_in_para,
    superscript,
)
from docxkit.errors import AnchorError

HL = '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'


def _styled(text: str) -> str:
    return f"<w:r>{HL}<w:t>{text}</w:t></w:r>"


#: A FIELD-form link whose label is fragmented across three styled runs,
#: with plain prose on both sides. Field form has no element to ask, so
#: `label_extent` must walk outward over the styled neighbours — which
#: is the walk the survivors sat in.
FIELD_LABEL = (
    "<w:p>"
    '<w:r><w:t xml:space="preserve">as </w:t></w:r>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "K2007" '
    "</w:instrText></w:r>"
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    + _styled("Kan") + _styled("bur ") + _styled("(2007)")
    + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    '<w:r><w:t xml:space="preserve"> shows</w:t></w:r></w:p>')

#: The same label in ELEMENT form, also across three runs.
ELEMENT_LABEL = (
    "<w:p>"
    '<w:r><w:t xml:space="preserve">as </w:t></w:r>'
    '<w:hyperlink w:anchor="K2007">'
    + _styled("Kan") + _styled("bur ") + _styled("(2007)")
    + "</w:hyperlink>"
    '<w:r><w:t xml:space="preserve"> shows</w:t></w:r></w:p>')


@pytest.mark.parametrize("paragraph", [FIELD_LABEL, ELEMENT_LABEL],
                         ids=["field-form", "element-form"])
def test_a_replacement_ending_EXACTLY_at_the_label_end_is_allowed(paragraph):
    """The label is "Kanbur (2007)" — three runs, one label. A rewrite
    that stops exactly there retitles the link and takes nothing with
    it, so it is permitted."""
    out = replace_in_para(paragraph, "Kanbur (2007)", "Kanbur (2007a)",
                          allow_hyperlink=True)
    assert text_of(out) == "as Kanbur (2007a) shows"


@pytest.mark.parametrize("paragraph", [FIELD_LABEL, ELEMENT_LABEL],
                         ids=["field-form", "element-form"])
def test_ONE_CHARACTER_past_the_label_end_is_refused(paragraph):
    """The boundary itself. If the walk that finds where the label ends
    is off by a run in either direction, this either stops refusing (the
    link silently swallows " s") or starts refusing the case above."""
    with pytest.raises(AnchorError, match="swallow"):
        replace_in_para(paragraph, "Kanbur (2007) s", "Kanbur (2007a) s",
                        allow_hyperlink=True)


@pytest.mark.parametrize("paragraph", [FIELD_LABEL, ELEMENT_LABEL],
                         ids=["field-form", "element-form"])
def test_the_walk_reaches_BACKWARDS_from_a_middle_run(paragraph):
    """Anchoring inside the label's SECOND run: the extent must still
    cover the whole label, which means walking left as well as right.
    A mutation that only walks one way leaves this passing when it
    should refuse."""
    with pytest.raises(AnchorError, match="swallow"):
        replace_in_para(paragraph, "bur (2007) s", "bur (2007a) s",
                        allow_hyperlink=True)


def test_growing_the_label_is_possible_but_must_be_ASKED_for():
    out = replace_in_para(FIELD_LABEL, "Kanbur (2007) s", "Kanbur (2007a) s",
                          allow_hyperlink=True, grow_link_label=True)
    assert text_of(out) == "as Kanbur (2007a) shows"


def test_a_replacement_wholly_OUTSIDE_the_label_needs_no_flag():
    """The guard must not fire on the ordinary edit: same paragraph,
    same link, a span that never reaches it."""
    out = replace_in_para(FIELD_LABEL, " shows", " demonstrates")
    assert text_of(out) == "as Kanbur (2007) demonstrates"


# ------------------------------------------------- _outside, by value ----
#
# Three answers, and each is a different decision: the span's start (the
# position is available before the whole element), its end (available
# after it), or None (the caller really is splitting a label).

def _runs(para_xml: str) -> list[re.Match[str]]:
    return list(RUN_RE.finditer(para_xml))


def test_outside_answers_the_START_when_nothing_shown_precedes_the_offset():
    p = "<w:p>" + _styled("label") + "<w:r><w:t> tail</w:t></w:r></w:p>"
    runs = _runs(p)
    span = (p.index("<w:r>"), runs[0].end())
    assert _outside(runs, span, runs[0].start()) == span[0]


def test_outside_answers_the_END_when_nothing_shown_follows():
    p = "<w:p>" + _styled("label") + "<w:r><w:t> tail</w:t></w:r></w:p>"
    runs = _runs(p)
    span = (runs[0].start(), runs[0].end())
    assert _outside(runs, span, runs[0].end()) == span[1]


def test_outside_answers_NONE_with_visible_text_on_both_sides():
    """Text either side of the offset means the same place on the page
    is not available outside the element — that is the refusal."""
    p = "<w:p>" + _styled("Kan") + _styled("bur") + "</w:p>"
    runs = _runs(p)
    span = (runs[0].start(), runs[-1].end())
    assert _outside(runs, span, runs[1].start()) is None


def test_outside_ignores_runs_that_SHOW_nothing():
    """A bookmark whose span also holds a zero-width note reference: the
    marker shows nothing, so it cannot make a position un-movable."""
    marker = '<w:r><w:footnoteReference w:id="3"/></w:r>'
    p = "<w:p>" + marker + _styled("label") + "</w:p>"
    runs = _runs(p)
    span = (runs[0].start(), runs[-1].end())
    assert _outside(runs, span, runs[1].start()) == span[0]


def test_insert_at_a_label_edge_lands_outside_it():
    """The value `_outside` computes, seen through the public door."""
    out = insert_in_para(ELEMENT_LABEL, len("as "), "see ")
    assert text_of(out) == "as see Kanbur (2007) shows"
    label = out[out.index("<w:hyperlink"):out.index("</w:hyperlink>")]
    assert text_of(label) == "Kanbur (2007)", "the link grew"


# ------------------------------------------- _restyle's split, by value --

def test_italicize_splits_a_run_at_BOTH_edges_of_the_span():
    """Only the inside piece gains the style, and the run is split at
    the span's edges — so the text either side keeps its own formatting
    and the visible text is unchanged."""
    p = para(run("See the Journal of Ageing for more"))
    out = italicize(p, "Journal of Ageing")

    assert text_of(out) == "See the Journal of Ageing for more"
    pieces = [(text_of(m.group(0)), "<w:i/>" in m.group(0))
              for m in RUN_RE.finditer(out)]
    assert pieces == [("See the ", False), ("Journal of Ageing", True),
                      (" for more", False)]


def test_italicize_a_span_that_fills_its_run_adds_no_split():
    p = para(run("See the "), run("Journal of Ageing"), run(" for more"))
    out = italicize(p, "Journal of Ageing")
    pieces = [(text_of(m.group(0)), "<w:i/>" in m.group(0))
              for m in RUN_RE.finditer(out)]
    assert pieces == [("See the ", False), ("Journal of Ageing", True),
                      (" for more", False)]


def test_italicize_across_FRAGMENTED_runs_styles_every_piece():
    """Word splits at rsid boundaries, so the span routinely covers part
    of one run, all of another and part of a third."""
    p = para(run("See the Jour"), run("nal of Age"), run("ing for more"))
    out = italicize(p, "Journal of Ageing")

    assert text_of(out) == "See the Journal of Ageing for more"
    italic = "".join(text_of(m.group(0)) for m in RUN_RE.finditer(out)
                     if "<w:i/>" in m.group(0))
    assert italic == "Journal of Ageing"


# --- offsets that are not run boundaries (2026-08-19) ------------------
#
# Every `_outside` fixture above asks about a position that IS a run
# edge — `runs[0].end()`, `runs[1].start()` — and both of its tests are
# `<=` and `>=` against a position that satisfies them by equality. A
# position strictly INSIDE a run is the ordinary case: an insertion
# offset is a visible-text position and has nothing to do with where
# Word happened to split its runs.

def test_outside_answers_the_END_from_INSIDE_the_last_run():
    """`r.end() <= pos`, not `== pos`. Nothing shown follows the offset,
    so the same place on the page is available after the whole element —
    and no run ends exactly there, which is what `<=` is for."""
    p = "<w:p>" + _styled("Kan") + _styled("bur") + "</w:p>"
    runs = _runs(p)
    span = (runs[0].start(), runs[-1].end())

    inside_last = runs[1].start() + 3

    assert _outside(runs, span, inside_last) == span[1]


def test_outside_answers_NONE_from_inside_a_MIDDLE_run():
    """`r.start() >= pos`, not `== pos`. A run still to come shows text
    after the offset, so the position cannot move outside the element —
    the refusal — and no run starts exactly at it."""
    p = ("<w:p>" + _styled("Kan") + _styled("bur") + _styled(" (2007)")
         + "</w:p>")
    runs = _runs(p)
    span = (runs[0].start(), runs[-1].end())

    inside_middle = runs[1].start() + 3

    assert _outside(runs, span, inside_middle) is None


# --- what a refusal QUOTES ----------------------------------------------
#
# Every message here cuts the anchor it is refusing, and the cuts were
# free: an anchor is a phrase a caller typed, so it is as long as
# whoever typed it. Uncut, one refusal prints a paragraph and the
# instruction after it scrolls away.


def _long(prefix: str, n: int) -> str:
    """A phrase of at least `n` characters, starting with `prefix`."""
    return prefix + " " + "x" * n


def test_a_MISSING_anchor_is_quoted_at_sixty_characters():
    """`_locate`: `{old[:60]!r} not in {where}`. Reached through
    `italicize` — `replace_in_para` has a refusal of its own, with its
    own cut, and the two messages are easy to mistake for each other."""
    anchor = _long("nowhere in this paragraph", 60)
    p = para(run("Some other sentence entirely."))

    with pytest.raises(AnchorError) as exc:
        italicize(p, anchor)

    assert repr(anchor[:60]) in str(exc.value)
    assert anchor[:61] not in str(exc.value)


def test_an_anchor_that_occurs_TWICE_is_quoted_at_sixty_too():
    """The other refusal from the same walk, and the one a caller meets
    when a phrase repeats — "the effect is significant" twice in one
    paragraph."""
    anchor = _long("the effect is significant", 60)
    p = para(run(f"{anchor} and again {anchor} here."))

    with pytest.raises(AnchorError) as exc:
        italicize(p, anchor)

    assert repr(anchor[:60]) in str(exc.value)
    assert anchor[:61] not in str(exc.value)


def test_a_NORMALIZED_anchor_that_misses_is_quoted_at_ninety():
    """`rep`, the document-wide replace: its anchor is a whole sentence
    more often than not, so it quotes ninety rather than sixty."""
    from docxkit.edit import rep

    anchor = _long("a sentence the author has since rewritten", 90)

    with pytest.raises(AnchorError) as exc:
        rep(para(run("Nothing like it.")), anchor, "x", normalize=True)

    assert repr(anchor[:90]) in str(exc.value)
    assert anchor[:91] not in str(exc.value)


def test_the_WITHIN_scope_is_quoted_at_forty_in_the_refusal():
    """`where = f"within={within[:40]!r}"` — the scope a caller narrowed
    to, echoed so they can see it was the scope and not the anchor that
    did not match."""
    scope = _long("A second one", 40)
    p = para(run(f"A first sentence. {scope}"))

    with pytest.raises(AnchorError) as exc:
        italicize(p, "nowhere", within=scope)

    assert repr(scope[:40]) in str(exc.value), str(exc.value)
    assert scope[:41] not in str(exc.value)


def test_superscript_does_NOT_fold_typography_unless_asked():
    """`normalize: bool = False`, as everywhere in this module: folding
    glyphs silently is how an anchor matches a paragraph the caller did
    not mean. The straight apostrophe against Word's curly one is the
    pair that keeps happening — autocorrect ran on some paragraphs and
    not on others."""
    p = para(run("the authors’ note 3 follows"))

    with pytest.raises(AnchorError):
        superscript(p, "authors' note")

    out = superscript(p, "authors' note", normalize=True)
    assert "<w:vertAlign" in out
