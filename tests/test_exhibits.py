"""What the exhibits are: which caption owns which body, and the span.

Every shape here was met on a manuscript or named by the code review of
`a90be3a` (repack's own detection), and the docstring of each test says
which. The bodies are built from the body-level elements Word actually
writes — hoisted bookmarks, range markers, blank paragraphs, section
breaks — because the defects all lived between the caption and its body.
"""
from __future__ import annotations

import re

from lxml import etree

from docxkit import exhibits as ex

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"')
W = ex.W


def body(xml: str) -> etree._Element:
    root = etree.fromstring(f"<w:document {NS}><w:body>{xml}</w:body>"
                            "</w:document>")
    found = root.find(W + "body")
    assert found is not None
    return found


def P(text: str, ppr: str = "") -> str:
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def cell(*paras: str) -> str:
    inner = "".join(P(t) if t else "<w:p/>" for t in paras)
    return f"<w:tc>{inner}</w:tc>"


def TBL(*rows: str) -> str:
    inner = "".join(f"<w:tr>{cell(r)}</w:tr>" for r in rows)
    return f"<w:tbl>{inner}</w:tbl>"


def BOX(*paras: str) -> str:
    """A box: one cell, the caption first, then its text."""
    return f"<w:tbl><w:tr>{cell(*paras)}</w:tr></w:tbl>"


IMG = "<w:p><w:r><w:drawing/></w:r></w:p>"
BLANK = "<w:p/>"
SECT = "<w:p><w:pPr><w:sectPr/></w:pPr></w:p>"
PANELS = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:drawing/></w:r></w:p></w:tc>"
          "<w:tc><w:p><w:r><w:drawing/></w:r></w:p></w:tc></w:tr></w:tbl>")


def BS(bid: int = 7) -> str:
    return f'<w:bookmarkStart w:id="{bid}" w:name="Figure{bid}"/>'


def BE(bid: int = 7) -> str:
    return f'<w:bookmarkEnd w:id="{bid}"/>'


def describe(el: etree._Element) -> str:
    tag = el.tag.split("}")[1]
    if tag == "p":
        if el.find(".//" + W + "drawing") is not None:
            return "img"
        if el.find(W + "pPr/" + W + "sectPr") is not None:
            return "sect"
        text = ex.text_of(el).strip()
        return f"p:{text[:20]}" if text else "blank"
    if tag == "tbl":
        return f"tbl:{ex.text_of(el).strip()[:12]}"
    return tag


def spans(xml: str, **kw: object) -> dict[str, list[str]]:
    """{'Figure 1': [described elements]} for every exhibit found."""
    return {x.name: [describe(e) for e in x.elements]
            for x in ex.exhibits(body(xml), **kw)}   # type: ignore[arg-type]


# ------------------------------------------------ which side the body is on

def test_a_table_captioned_ABOVE_owns_the_table_below():
    found = spans(P("Prose.") + P("Table 1. Rates") + TBL("a", "b")
                  + P("More."))

    assert found == {"Table 1": ["p:Table 1. Rates", "tbl:ab"]}


def test_a_figure_captioned_UNDER_its_image_owns_the_image_above():
    """Aging_Well: image, the bookmark Word hoisted, then the caption.
    `placement.exhibit_block` walked forward only and refused every
    figure in that paper; `figures.caption_side` knew, per document."""
    found = spans(P("Prose.") + IMG + BS() + P("Figure 1. From resources")
                  + BLANK + P("More."))

    assert found == {"Figure 1": ["img", "bookmarkStart",
                                  "p:Figure 1. From resou", "blank"]}


def test_a_PANEL_exhibit_spans_every_panel_under_its_one_caption():
    """HCW's Table 9 and AFI's Table A3: caption, `Panel A.`, a table,
    `Panel B.`, another table, the note. Read as prose, the panel
    heading ended the search and both captions had no body. A body a
    panel heading introduces is the next panel; one without stays
    somebody else's."""
    panels = (P("Table 9. Estimates") + P("Panel A. Health-based")
              + TBL("a") + BLANK + P("Panel B. Mortality-based") + TBL("b")
              + P("Note: both.") + P("Prose."))
    plain = P("Table 1. A") + TBL("a") + TBL("stray") + P("Prose.")

    assert spans(panels) == {"Table 9": [
        "p:Table 9. Estimates", "p:Panel A. Health-base", "tbl:a", "blank",
        "p:Panel B. Mortality-b", "tbl:b", "p:Note: both."]}
    assert spans(plain) == {"Table 1": ["p:Table 1. A", "tbl:a"]}
    assert spans(P("Panel data allow it.") + P("Table 1. A") + TBL("a")) == {
        "Table 1": ["p:Table 1. A", "tbl:a"]}


def test_a_figure_captioned_above_keeps_the_hoisted_END_between():
    """HCW's shape: caption, `bookmarkEnd`, image, source. The marker
    sits between caption and body and is part of the span."""
    found = spans(P("Figure 2. Rates") + BE() + IMG + P("Source: authors.")
                  + P("Prose."))

    assert found == {"Figure 2": ["p:Figure 2. Rates", "bookmarkEnd", "img",
                                  "p:Source: authors."]}


def test_stacked_tables_each_keep_their_OWN_table():
    """The review's case 2: repack looked backwards first, so Table 2
    claimed Table 1's table and every trial moved the wrong one. Table 1
    has one candidate and takes it; that settles Table 2."""
    found = spans(P("Table 1. A") + TBL("a1") + P("Table 2. B") + TBL("b1")
                  + P("Prose."))

    assert found == {"Table 1": ["p:Table 1. A", "tbl:a1"],
                     "Table 2": ["p:Table 2. B", "tbl:b1"]}


def test_a_run_of_tables_captioned_UNDERNEATH_is_read_from_its_end():
    """`tables._beside`'s case: nothing stands between a caption and the
    next table down, so the last caption — with no table below it —
    settles the run from the end."""
    found = spans(P("Prose.") + TBL("t3") + P("Table 3. A") + TBL("a3")
                  + P("Table A3. B") + P("Prose."))

    assert found == {"Table 3": ["tbl:t3", "p:Table 3. A"],
                     "Table A3": ["tbl:a3", "p:Table A3. B"]}


def test_an_uncaptioned_chart_above_a_table_caption_is_NOBODYS():
    """LE_trends: a chart image sits directly above `Table 1.`'s caption
    and repack took it as the body, leaving the real table out. A table
    caption wants a table; the image is a body of the other kind and
    ends the search on that side."""
    found = spans(P("Chart 3 plots it.") + IMG + P("Table 1. Duration")
                  + TBL("row") + P("Prose."))

    assert found == {"Table 1": ["p:Table 1. Duration", "tbl:row"]}


def test_a_figure_caption_between_two_images_follows_the_DOCUMENT():
    """Neither neighbour is claimed by anything else, so propagation
    cannot settle it. Two other figures in the paper are captioned
    underneath, so this one is read that way too; with no such evidence
    the body is below the caption."""
    ambiguous = (P("Prose.") + IMG + P("Figure 2. Cap") + IMG + P("Prose."))
    below_paper = (P("Prose.") + IMG + P("Figure 1. Cap") + P("Prose.")
                   + P("Prose.") + IMG + P("Figure 3. Cap") + P("Prose."))

    assert spans(ambiguous)["Figure 2"] == ["p:Figure 2. Cap", "img"]
    assert spans(ambiguous + below_paper)["Figure 2"] == [
        "img", "p:Figure 2. Cap"]


def test_a_figure_can_be_a_TABLE_of_panels():
    """HCW's and AFI's Figure 5: a 2x2 grid of drawings under the
    caption, and no `w:drawing` paragraph anywhere."""
    found = spans(P("Figure 5. Panels") + PANELS + P("Note: panels a-d.")
                  + P("Prose."))

    assert found == {"Figure 5": ["p:Figure 5. Panels", "tbl:",
                                  "p:Note: panels a-d."]}
    (fig,) = ex.exhibits(body(P("Figure 5. Panels") + PANELS))
    assert fig.kind == "figure"


def test_a_caption_paragraph_holding_its_own_image_is_its_own_body():
    own = ("<w:p><w:r><w:t>Figure 2. Cap</w:t></w:r><w:r><w:drawing/></w:r>"
           "</w:p>")

    (fig,) = ex.exhibits(body(P("Prose.") + own + P("Prose.")))

    assert fig.body_at == fig.caption_at
    assert [describe(e) for e in fig.elements] == ["img"]


def test_prose_with_a_chart_ANCHORED_in_it_is_not_a_body():
    """The review's gap: a floating chart anchored in a sentence made
    that sentence the figure's body, and every trial moved the sentence.
    A caption with no body of its own gets only itself."""
    anchored = ("<w:p><w:r><w:t>The trend is clear.</w:t></w:r>"
                "<w:r><w:drawing/></w:r></w:p>")

    (fig,) = ex.exhibits(body(P("Figure 1. Cap") + anchored + P("More.")))

    assert fig.body_at is None
    assert [describe(e) for e in fig.elements] == ["p:Figure 1. Cap"]


def test_a_section_break_is_a_wall_for_the_search_and_travels_behind():
    """An exhibit does not reach into the section before its own — and
    the break paragraph UNDER it is the block's, which is the whole
    point of `exhibit_block` (AFI's landscape panels)."""
    found = spans(P("Prose.") + TBL("stray") + SECT + P("Table 1. Wide")
                  + TBL("w") + SECT + P("Prose."))

    assert found == {"Table 1": ["p:Table 1. Wide", "tbl:w", "sect"]}


# ---------------------------------------------------------- the span's edges

def test_a_box_does_not_absorb_the_next_figures_IMAGE():
    """Aging_Well, the defect that opened the review: an image is a
    paragraph with no text, and a walk absorbing blank paragraphs took
    Figure 1's picture into Box 1's block. No element may be in two."""
    found = spans(BOX("Box 1. Key terms", "Capability: what a person can do.")
                  + BLANK + IMG + BS() + P("Figure 1. From resources")
                  + P("Prose."), labels=("Figure", "Table", "Box"))

    assert found == {"Box 1": ["tbl:Box 1. Key t", "blank"],
                     "Figure 1": ["img", "bookmarkStart",
                                  "p:Figure 1. From resou"]}


def test_notes_and_blanks_under_the_body_travel_with_it():
    found = spans(P("Table 1. A") + TBL("a") + P("Note: x.") + BLANK
                  + P("* p below 0.05") + P("Prose resumes."))

    assert found["Table 1"] == ["p:Table 1. A", "tbl:a", "p:Note: x.", "blank",
                                "p:* p below 0.05"]


def test_the_NOTE_pattern_is_the_callers():
    tight = re.compile(r"^Note\b")

    found = spans(P("Table 1. A") + TBL("a") + P("Source: x.") + P("Prose."),
                  note=tight)

    assert found["Table 1"] == ["p:Table 1. A", "tbl:a"]


def test_a_trailing_END_marker_goes_with_the_block_only_when_opened_in_it():
    """A caption's bookmark Word hoisted both halves of: the end sits
    after the caption and closes a start inside the span. One that
    closes something earlier stays where it is."""
    paired = spans(P("Prose.") + IMG + BS(3) + P("Figure 3. Cap") + BE(3)
                   + P("Prose."))
    foreign = spans(BS(9) + P("Prose.") + IMG + P("Figure 3. Cap") + BE(9)
                    + P("Prose."))

    assert paired["Figure 3"] == ["img", "bookmarkStart", "p:Figure 3. Cap",
                                  "bookmarkEnd"]
    assert foreign["Figure 3"] == ["img", "p:Figure 3. Cap"]


def test_a_leading_END_marker_closes_something_earlier_and_stays():
    """Hoisted STARTS in front of a caption are the caption's (DSI's
    twelve inverted bookmarks); an END in front of them is not."""
    found = spans(BS(1) + P("Prose.") + BE(1) + BS(2) + BE(2)
                  + P("Table 2. Cap") + TBL("a"))

    assert found["Table 2"] == ["bookmarkStart", "bookmarkEnd",
                                "p:Table 2. Cap", "tbl:a"]


def test_range_markers_between_caption_and_body_are_transparent():
    """The review's case 13: Word writes `commentRangeStart` and
    `moveToRangeStart` at body level too, and repack's walk stopped at
    either — Aging_Well's own redline lost Figure 2 to one."""
    comment = '<w:commentRangeStart w:id="4"/>'
    move = '<w:moveToRangeStart w:id="5" w:name="move1"/>'

    found = spans(IMG + comment + P("Figure 1. Cap") + P("Prose.")
                  + P("Table 1. Cap") + move + TBL("a") + P("Prose."))

    assert found["Figure 1"][:3] == ["img", "commentRangeStart",
                                     "p:Figure 1. Cap"]
    assert found["Table 1"] == ["p:Table 1. Cap", "moveToRangeStart",
                                "tbl:a"]


# --------------------------------------------------------- what a caption is

def test_every_caption_the_toolkit_knows_is_recognised():
    """`find.caption_re` is THE definition: colon captions, appendix and
    dotted numbers. repack's own regex saw none of these, which is how
    it found 0 of Loneliness Index's 10 exhibits."""
    found = ex.exhibits(body(P("Table 3.1: A") + TBL("a") + P("Table A2. B")
                             + TBL("b") + P("Figure 1-A: C") + IMG))

    assert [(x.label, x.number, x.kind) for x in found] == [
        ("Table", "3.1", "table"), ("Table", "A2", "table"),
        ("Figure", "1-A", "figure")]


def test_a_caption_set_with_a_TAB_is_a_caption():
    tabbed = ("<w:p><w:r><w:t>Table 2.</w:t></w:r><w:r><w:tab/></w:r>"
              "<w:r><w:t>Every group</w:t></w:r></w:p>")

    (tbl,) = ex.exhibits(body(tabbed + TBL("a")))

    assert tbl.caption == "Table 2.\tEvery group"


def test_a_caption_in_a_one_cell_FRAME_owns_a_body_like_a_paragraph():
    """Some papers set the caption in a one-cell table above the
    exhibit. That is a caption in a frame, not a box: a box has words of
    its own under its title."""
    found = spans(P("Prose.") + BOX("Table 3. Distribution") + TBL("a")
                  + P("Prose."))

    assert found == {"Table 3": ["tbl:Table 3. Dis", "tbl:a"]}


def test_a_FRAMED_and_a_paragraph_caption_for_the_same_table_do_not_fight():
    """`test_placement`'s shape: both spellings present, the paragraph
    directly over the table. The frame finds nothing on either side and
    the paragraph owns the table."""
    found = spans(P("Prose.") + BOX("Table 3. Distribution")
                  + P("Table 3. Distribution") + TBL("a") + P("Prose."))

    assert found["Table 3"] == ["p:Table 3. Distributio", "tbl:a"]
    assert len(ex.exhibits(body(BOX("Table 3. D") + P("Table 3. D")
                                + TBL("a")))) == 2


def test_a_box_is_an_exhibit_only_when_its_word_is_asked_for():
    xml = BOX("Box 1. Key terms", "Capability: what a person can do.")

    assert ex.exhibits(body(xml)) == []
    (box,) = ex.exhibits(body(xml), labels=("Box",))
    assert (box.kind, box.name) == ("box", "Box 1")
    assert box.body_at == box.caption_at
    assert box.caption.startswith("Box 1. Key terms")


def test_a_caption_over_PROSE_gets_only_itself_and_document_order_holds():
    found = ex.exhibits(body(P("Figure 2. Cap") + P("Just prose.")
                             + P("Table 1. Cap") + TBL("a")))

    assert [(x.name, x.body_at is None) for x in found] == [
        ("Figure 2", True), ("Table 1", False)]
    assert [x.start for x in found] == [0, 2]


# -------------------------------------------------------------- the mention

def mention(xml: str, name: str, **kw: object) -> int | None:
    b = body(xml)
    found = {x.name: x for x in ex.exhibits(b, **kw)}   # type: ignore[arg-type]
    return ex.mention_of(b, found[name])


def test_the_mention_is_the_first_paragraph_naming_it_outside_its_span():
    xml = (P("Intro.") + P("Table 1 lists them.") + P("Table 1. Cap")
           + TBL("a") + P("Table 1 again."))

    assert mention(xml, "Table 1") == 1


def test_a_RANGE_mentions_its_last_member_too():
    """"Figures 1 and 2 show" is Figure 2's first mention. Matching only
    "Figure 2" made a later sentence the anchor, and every placement
    offered started after the figure."""
    xml = (P("Figures 1 and 2 show it.") + IMG + P("Figure 1. A") + IMG
           + P("Figure 2. B") + P("Figure 2 alone."))

    assert mention(xml, "Figure 2") == 0


def test_a_word_CONTAINING_the_label_is_not_a_mention():
    """"configure 2" is not Figure 2 and "stable 1" is not Table 1 —
    repack's bare pattern matched both."""
    xml = (P("We configure 2 servers.") + P("A stable 1 percent.")
           + P("Figure 2 shows it.") + IMG + P("Figure 2. B"))

    assert mention(xml, "Figure 2") == 2


def test_a_DECLINED_russian_mention_and_a_BOX_are_found():
    """Repack's stem compared four characters of a three-letter label,
    so no Box ever found its mention; the Russian case is `crossrefs`'
    and rides on the same grammar."""
    ru = (P("Как показано в таблице 5, всё сходится.") + P("Таблица 5. Итоги")
          + TBL("a"))
    box = (P("Box 1 defines the terms.")
           + BOX("Box 1. Key terms", "Capability: what a person can do."))

    assert mention(ru, "Таблица 5") == 0
    assert mention(box, "Box 1", labels=("Box",)) == 0


def test_a_mention_inside_a_TABLE_counts_and_the_own_span_does_not():
    xml = (P("Intro.") + TBL("See Figure 1 for the map.") + IMG
           + P("Figure 1. Map (see Figure 1)."))

    assert mention(xml, "Figure 1") == 1
    assert mention(P("Intro.") + IMG + P("Figure 1. Map"), "Figure 1") is None


def test_the_value_is_frozen_and_names_itself():
    (tbl,) = ex.exhibits(body(P("Table 4. Cap") + TBL("a")))

    assert (tbl.name, tbl.key) == ("Table 4", ("Table", "4"))
    assert hash(tbl) == hash(tbl)
