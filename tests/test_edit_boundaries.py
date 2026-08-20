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


def test_italic_lands_AFTER_the_properties_that_must_precede_it():
    """`at = m.end() - len("<w:rPr>")` — the offset that puts `<w:i/>`
    in its schema slot. EG_RPrBase orders rStyle, rFonts, b, bCs, i:
    written before `<w:b/>` the run properties are out of order, which
    is a document Word repairs on open.

    Three mutants lived on that subtraction because every italicize
    fixture here uses a run with NO properties, where the whole
    expression is skipped."""
    p = ('<w:p><w:r><w:rPr><w:rStyle w:val="Emphasis"/><w:b/>'
         '<w:sz w:val="20"/></w:rPr>'
         "<w:t>Journal of Ageing</w:t></w:r></w:p>")

    out = italicize(p, "Journal of Ageing")

    # `w:sz` sorts AFTER `w:i`, and it is what makes the offset visible:
    # with nothing behind the insertion point, an offset past the end of
    # the properties appends to the same place the correct one writes to
    assert ('<w:rPr><w:rStyle w:val="Emphasis"/><w:b/><w:i/>'
            '<w:sz w:val="20"/></w:rPr>' in out), out


def test_a_label_that_ENDS_the_paragraph_stops_the_walk():
    """`0 <= i < len(runs)` in `styled`. The walk climbs run by run
    while the NEXT one carries the Hyperlink style, and a styled run
    that ends the paragraph asks about an index that does not exist.

    Styled runs with no link around them are the ordinary case for this
    walk — Word leaves the character style behind when the author
    deletes a link's address — and a citation closing a sentence is
    where citations sit. Without the upper bound that is an IndexError
    out of a guard whose whole job is to say "no"."""
    p = ("<w:p>" + '<w:r><w:t xml:space="preserve">as </w:t></w:r>'
         + _styled("Kan") + _styled("bur (2007)") + "</w:p>")

    out = replace_in_para(p, "Kanbur (2007)", "Kanbur (2007a)",
                          allow_hyperlink=True)

    assert text_of(out) == "as Kanbur (2007a)"


# --- the run of 2026-08-20: the insert guards ---------------------------


def test_an_insert_BEFORE_a_hyperlink_is_not_INSIDE_it():
    """`lo < pos < hi` in `_enclosing`, and the mutant that reads it as
    `lo != pos`. Everything before a protected region satisfies that —
    every offset in the paragraph up to the link — so an insert at the
    very start of a paragraph whose second half carries a link is
    refused as "inside a hyperlink".

    A refusal a caller cannot act on is worse than a wrong edit: there
    is nowhere else to put it."""
    para_xml = ("<w:p><w:r><w:t>Lead in </w:t></w:r>"
                '<w:hyperlink w:anchor="a"><w:r><w:t>label</w:t></w:r>'
                "</w:hyperlink><w:r><w:t> tail</w:t></w:r></w:p>")

    out = insert_in_para(para_xml, 0, "NEW ")

    assert text_of(out) == "NEW Lead in label tail"


def test_the_ALLOW_flag_is_what_opens_a_protected_region():
    """`elif not allowed:`. Inverted, the refusals fire for the caller
    who passed the flag and stay silent for the one who did not — which
    is the same code path answering both callers with the other's
    answer, and the silent half writes into the link."""
    # the label in TWO runs, so offset 11 falls between them: a position
    # at the link's EDGE is moved outside instead of refused, which is
    # `_outside`'s job and not this branch's
    para_xml = ("<w:p><w:r><w:t>Lead in </w:t></w:r>"
                '<w:hyperlink w:anchor="a"><w:r><w:t>lab</w:t></w:r>'
                "<w:r><w:t>el</w:t></w:r></w:hyperlink>"
                "<w:r><w:t> tail</w:t></w:r></w:p>")

    with pytest.raises(AnchorError, match="falls inside a hyperlink"):
        insert_in_para(para_xml, 11, "X")

    out = insert_in_para(para_xml, 11, "X", allow_hyperlink=True)
    assert text_of(out) == "Lead in labXel tail"


def test_italics_land_where_the_RUN_starts_and_not_at_zero():
    """`at - start`, the offset of the span inside THIS run. Every
    arithmetic mutant of it agrees when `start` is 0 — the first run —
    and the first run is where a one-run fixture puts everything.

    Wrong, the italics open in the middle of a word and the split runs
    carry the wrong halves; the paragraph still reads the same, which is
    why nothing downstream shows it."""
    para_xml = ("<w:p><w:r><w:t>Lead in </w:t></w:r>"
                "<w:r><w:t>the target word</w:t></w:r>"
                "<w:r><w:t> tail</w:t></w:r></w:p>")

    out = italicize(para_xml, "target")

    assert text_of(out) == "Lead in the target word tail"
    assert '<w:r><w:rPr><w:i/></w:rPr><w:t>target</w:t></w:r>' in out, out


def test_a_FIELD_FORM_label_ends_where_its_styled_runs_do():
    """`styled(hi_i + 1)` walks off the end of a field-form link's
    label, one run at a time. `hi_i | 1` is the same number for an even
    index and the CURRENT one for an odd index — so from an odd start
    the walk takes an extra step without checking what it stepped onto,
    and the label swallows the plain run after it.

    Three styled runs and a plain one is the smallest fixture that
    starts odd and still has somewhere wrong to end. The consequence is
    the refusal below going missing: a replacement that ends outside the
    label is then written INTO it, and the link grows to cover text
    nobody linked."""
    hl = '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    para_xml = ("<w:p><w:r><w:t>See </w:t></w:r>"
                f"<w:r>{hl}<w:t>the </w:t></w:r>"
                f"<w:r>{hl}<w:t>label </w:t></w:r>"
                f"<w:r>{hl}<w:t>here</w:t></w:r>"
                "<w:r><w:t> and beyond.</w:t></w:r></w:p>")

    with pytest.raises(AnchorError, match="ends outside it"):
        replace_in_para(para_xml, "here and beyond", "X",
                        allow_hyperlink=True)


def test_an_insert_inside_a_LATER_run_splits_THAT_run():
    """`runs[inside[0]]` and `at - inside[1]`: the run's INDEX and the
    run's START, which are the same number only for the first run at
    offset 0. Indexed by the start, the split lands in another run
    entirely — or raises IndexError — and the offset arithmetic puts the
    content at the wrong character of it."""
    # six characters, then an insert three into the second run: 9 - 6 is
    # 3 and 9 ^ 6 is 15, which the run does not have. A first run whose
    # length is a power of two hides that — 12 - 8 and 12 ^ 8 agree.
    para_xml = ("<w:p><w:r><w:t>Lead: </w:t></w:r>"
                "<w:r><w:t>second run here</w:t></w:r></w:p>")

    out = insert_in_para(para_xml, 9, "|X|")

    assert text_of(out) == "Lead: sec|X|ond run here"


def test_LEADING_whitespace_keeps_its_xml_space_preserve():
    """`content != content.strip()`, which decides whether the new run
    declares `xml:space="preserve"`. An ordering comparison answers the
    same for TRAILING whitespace — "trail " sorts above "trail" — and
    the opposite for leading, where " lead" sorts below "lead".

    Without the declaration Word drops the space on the next save, and
    the two words run together in a document nobody edited."""
    para_xml = "<w:p><w:r><w:t>AB</w:t></w:r></w:p>"

    for content in (" lead", "trail "):
        out = insert_in_para(para_xml, 1, content)
        assert f'<w:t xml:space="preserve">{content}</w:t>' in out, out


# Argued rather than pinned, from the 2026-08-20 run:
#
# * `base = scope[0][0]` written `scope[-1][0]`, and `hits[0][1]` written
#   `hits[-1][1]`: both sit under a guard that has already raised for
#   anything but one hit, so the first IS the last.
# * `if lo == 0 and hi == len(body):` written `is`. Above 256 the
#   identity fails and the walk takes the slow path — which rebuilds the
#   same run: the empty pieces are dropped by `if part`, and
#   `set_run_text(run_xml, visible_text(run_xml))` round-trips a run
#   byte for byte (measured on a 300-character body).
# * `visible.find(old, at + 1) >= 0` written `>= 1`. The search starts at
#   `at + 1`, so a second occurrence cannot be found at offset 0.
# * `len(touched) > 1` written `> 0`. A marker is a run of zero visible
#   width and a match has width, so a `touched` list holding a marker
#   holds the run carrying the text as well — one touched run is never a
#   marker, and the loop under the guard finds nothing to refuse.
# * `tail = body[end - start:] if stop > end else ""` written `!=` and
#   `is not`. The two disagree only when `stop < end`, and there
#   `end - start` is past the end of `body`, so the slice is "" either
#   way.
# * `0 <= i < len(runs)` in `styled`, written `1 <= i` / `0 != i` /
#   `0 is not i`. Its one caller asks about `hi_i + 1` with `hi_i >= 0`,
#   so the lower bound is never the answer.
# * `zip(spans, runs, strict=True)` in the edit loop written
#   `strict=False`: `run_spans` returns one span per run by
#   construction.
