"""The survivors of the first `exhibits.py` sweep (2026-09-13).

17.9 % of a 460-mutant sample lived against `test_exhibits.py` and
`test_placement.py`. Most sat where the fixtures were too tidy to tell a
mutant from the code: a caption never first in the body, an index never
odd, a bookmark id never two characters long, no element outside the
WordprocessingML namespace, and no document where the captions' majority
decided anything.
"""
from __future__ import annotations

from test_exhibits import BS, IMG, TBL, P, body, cell, spans

from docxkit import exhibits as ex

LABELS = ("Figure", "Table", "Box")


# --- what an element is ------------------------------------------------------


def test_text_of_reads_what_the_page_SHOWS_and_not_a_fields_code():
    """`w:instrText` and `w:delText` hold text as well, and both tags sort
    before `w:t`; the page shows neither."""
    (para,) = body('<w:p><w:r><w:instrText> SEQ Table </w:instrText></w:r>'
                   "<w:r><w:t>Table 1.</w:t></w:r>"
                   '<w:del w:id="1" w:author="A"><w:r><w:delText>old'
                   "</w:delText></w:r></w:del></w:p>")

    assert ex.text_of(para) == "Table 1."


def test_a_body_is_a_TABLE_or_a_picture_paragraph_with_no_words():
    """A picture inside a content control or custom XML is not a body at
    body level, and a paragraph with words is prose whatever it holds."""
    kids = list(body(TBL("a") + IMG
                     + "<w:sdt><w:sdtContent>" + IMG
                     + "</w:sdtContent></w:sdt>"
                     + '<w:customXml w:element="x">' + IMG + "</w:customXml>"
                     + "<w:p><w:r><w:t>Words</w:t></w:r>"
                     "<w:r><w:drawing/></w:r></w:p>"))

    assert [ex.is_body(k) for k in kids] == [True, True, False, False, False]


def test_a_body_child_in_ANOTHER_namespace_is_passed_over_as_a_marker():
    """Its tag sorts after every WordprocessingML tag, `w:tbl` included,
    and it is no table: the caption reaches past it to its body."""
    found = spans(P("Table 1. Rates") + '<x:mark xmlns:x="urn:x"/>'
                  + TBL("a"))

    assert found == {"Table 1": ["p:Table 1. Rates", "mark", "tbl:a"]}


def test_a_FRAME_is_one_cell_and_two_cells_holding_only_a_caption_a_box():
    two = ("<w:tbl><w:tr>" + cell("Box 1. Checklist") + cell("")
           + "</w:tr></w:tbl>")

    (x,) = ex.exhibits(body(P("Box 1 lists it.") + two + P("After.")),
                       labels=LABELS)

    assert (x.kind, x.body_at) == ("box", 1)


def test_a_table_caption_takes_no_PICTURE_and_a_figure_caption_no_TABLE():
    found = spans(P("Table 1. Rates") + IMG + P("Prose.")
                  + P("Figure 1. Map") + TBL("a"))

    assert found == {"Table 1": ["p:Table 1. Rates"],
                     "Figure 1": ["p:Figure 1. Map"]}


# --- where a span opens and closes -------------------------------------------


def test_a_caption_FIRST_in_the_body_looks_no_further_up_than_the_top():
    """Index -1 is the LAST element: a scan or a walk that runs past the top
    reads the end of the document instead — a table there, a bookmark
    there."""
    scan = spans(P("Table 1. Rates") + P("Prose.") + TBL("a"))
    walk = spans(P("Table 1. Rates") + TBL("a")
                 + '<w:bookmarkStart w:id="9" w:name="x"/>')

    assert scan == {"Table 1": ["p:Table 1. Rates"]}
    assert walk == {"Table 1": ["p:Table 1. Rates", "tbl:a"]}


def test_the_bookmark_hoisted_in_front_OPENS_the_span_at_index_1_and_3():
    """At 1 the walk ends at the top; at 3 it has to look at index 2, where
    `k >> 1` would look at 1."""
    first = spans(BS() + P("Table 1. Rates") + TBL("a"))
    later = spans(P("One.") + P("Two.") + BS() + P("Table 1. Rates")
                  + TBL("a"))

    assert first["Table 1"] == ["bookmarkStart", "p:Table 1. Rates", "tbl:a"]
    assert later["Table 1"] == ["bookmarkStart", "p:Table 1. Rates", "tbl:a"]


def test_a_caption_with_NO_body_spans_itself_at_an_odd_index():
    found = spans(P("Prose.") + P("Table 1. Rates") + P("More prose."))

    assert found == {"Table 1": ["p:Table 1. Rates"]}


def test_the_MIDDLE_of_three_exhibits_keeps_its_whole_span():
    found = spans(P("Table 1. A") + TBL("a") + P("Table 2. B") + TBL("b")
                  + P("Table 3. C") + TBL("c"))

    assert found == {"Table 1": ["p:Table 1. A", "tbl:a"],
                     "Table 2": ["p:Table 2. B", "tbl:b"],
                     "Table 3": ["p:Table 3. C", "tbl:c"]}


def test_a_mention_just_PAST_the_span_and_one_further_on_are_both_found():
    first = body(P("Table 1. Rates") + TBL("a") + P("Table 1 shows it."))
    later = body(P("Table 1. Rates") + TBL("a") + P("Prose.")
                 + P("Table 1 shows it."))

    assert [ex.mention_of(b, ex.exhibits(b)[0]) for b in (first, later)] == [
        2, 3]


# --- which side a body is on, when the document has to say -------------------


def _below(n: int) -> str:
    return P(f"Prose {n}.") + P(f"Table {n}. Below") + TBL(f"b{n}")


def _above(n: int) -> str:
    return P(f"Prose {n}.") + TBL(f"a{n}") + P(f"Table {n}. Above")


def _either(n: int) -> str:
    return (P(f"Prose {n}.") + TBL(f"u{n}") + P(f"Table {n}. Either")
            + TBL(f"v{n}"))


def test_an_undecided_caption_follows_the_MAJORITY_and_below_on_a_tie():
    """Each settled caption votes once, +1 for a body above it and -1 for
    one below, and a caption with a body on both sides takes the side the
    sum leans to — below when it leans nowhere. One document per sign,
    with the votes cast in orders a running tally could misread."""
    below = ["p:Table 9. Either", "tbl:v9"]
    above = ["tbl:u9", "p:Table 9. Either"]
    for layout, want in [(_below(1) + _below(2) + _above(3), below),
                         (_below(1) + _above(2), below),
                         (_above(1) + _above(2) + _below(3), above)]:
        assert spans(layout + _either(9) + P("End."))["Table 9"] == want


def test_captions_settle_UPWARD_one_pass_at_a_time_to_the_top():
    """Table 6 takes the one table it can reach, which leaves Table 5 one,
    then 4, then 3, each in a later pass. A pass that stopped at the first
    caption already settled would hand 3, 4 and 5 to the majority, which
    here says below, until Table 5 had nothing left to take."""
    layout = (P("Table 1. Z1") + TBL("z1") + P("Prose.")
              + P("Table 2. Z2") + TBL("z2") + P("Prose.")
              + TBL("V") + P("Table 3. O") + TBL("W") + P("Table 4. P")
              + TBL("X") + P("Table 5. Q") + TBL("Y") + P("Table 6. R")
              + P("End."))

    bodies = {x.name: x.body_at for x in ex.exhibits(body(layout))}

    assert bodies == {"Table 1": 1, "Table 2": 4, "Table 3": 6,
                      "Table 4": 8, "Table 5": 10, "Table 6": 12}


def test_a_scan_and_a_walk_that_reach_the_END_of_a_long_body_stop_there():
    """Past 256 elements an index and a length are different objects, and
    only comparing them by value tells the walk it has arrived."""
    prose = P("Prose.") * 300
    tail = "<w:p/>" * 3

    bodyless = spans(prose + P("Figure 1. Last") + tail)
    walked = spans(prose + P("Table 1. Last") + TBL("a") + tail)

    assert bodyless == {"Figure 1": ["p:Figure 1. Last"]}
    assert walked == {"Table 1": ["p:Table 1. Last", "tbl:a", "blank",
                                  "blank", "blank"]}


def _bookmarked(start_id: str) -> str:
    return (f'<w:p><w:bookmarkStart w:id="{start_id}" w:name="t"/>'
            "<w:r><w:t>Table 1. Rates</w:t></w:r></w:p>")


def test_an_END_marker_joins_the_span_only_when_its_START_is_inside():
    """Id for id and by value: "10" read twice is two strings, "1" before
    "2" and "3" after it pair nothing, and a START marker after the block
    is never the block's, whatever id it repeats."""
    base = ["p:Table 1. Rates", "tbl:a"]
    for start_id, after, want in [
            ("10", '<w:bookmarkEnd w:id="10"/>', [*base, "bookmarkEnd"]),
            ("1", '<w:bookmarkEnd w:id="2"/>', base),
            ("3", '<w:bookmarkEnd w:id="2"/>', base),
            ("5", '<w:bookmarkStart w:id="5" w:name="dup"/>', base)]:
        found = spans(_bookmarked(start_id) + TBL("a") + after + P("After."))
        assert found["Table 1"] == want, (start_id, after)


def test_where_two_walks_MEET_the_later_exhibit_keeps_its_own_body():
    """Table 2 is captioned under its table, and Table 1's walk reads that
    table as its next panel. The walks overlap by it, and it stays with the
    caption it stands in front of."""
    found = spans(P("Table 1. Rates") + TBL("a") + P("Panel B.") + TBL("b")
                  + P("Table 2. Under"))

    assert found == {"Table 1": ["p:Table 1. Rates", "tbl:a", "p:Panel B."],
                     "Table 2": ["tbl:b", "p:Table 2. Under"]}


# --- the whole sweep of 2026-09-17 -------------------------------------------


def test_is_body_refuses_a_tag_sorting_AFTER_a_table_and_a_comment():
    """`is_body` is public and the package hands it only paragraphs, so
    only its own test can ask. A tag in a namespace after
    WordprocessingML's sorts after `w:tbl`, and a comment's tag is a
    function that sorts against no string: neither is a body."""
    kids = list(body('<x:mark xmlns:x="urn:x"/><!-- a note to self -->'))

    assert [ex.is_body(k) for k in kids] == [False, False]


def test_a_picture_in_a_CONTENT_CONTROL_is_a_wall_and_not_the_figure():
    """`_scan` stops at a content control, so the caption has no body, and
    the picture behind the control is out of reach. `w:sdt` sorts after
    `w:p`, and read as a paragraph it is a picture with no words — the
    body the caption would take; the one other-namespace tag the edges
    had before read as a blank paragraph, transparent like a marker."""
    sdt = "<w:sdt><w:sdtContent>" + IMG + "</w:sdtContent></w:sdt>"

    (x,) = ex.exhibits(body(P("Figure 1. Map") + sdt + IMG + P("Prose.")))

    assert (x.body_at, x.start, x.stop) == (None, 0, 1)


def test_a_table_AFTER_the_last_panel_with_no_heading_of_its_own_stays_out():
    """A panel heading lets ONE body in, its panel; a table straight after
    that panel has no heading and is somebody else's. Every panel fixture
    before ended in a note, prose or a caption, where a heading that let
    in every later body read the same."""
    found = spans(P("Table 9. Estimates") + P("Panel A. Health") + TBL("a")
                  + P("Panel B. Mortality") + TBL("b") + TBL("stray")
                  + P("Prose."))

    assert found == {"Table 9": ["p:Table 9. Estimates", "p:Panel A. Health",
                                 "tbl:a", "p:Panel B. Mortality", "tbl:b"]}


def test_the_257TH_exhibit_is_the_LAST_and_ends_where_its_walk_does():
    """`n + 1` and `len(spans)` are equal ints computed apart, and past 256
    they are different objects: only comparing them by value tells the
    last span there is no next one to stop at. 257 captions with no body
    between them are the cheapest such document."""
    layout = "".join(P(f"Table {n}. Cap") for n in range(1, 258))

    found = ex.exhibits(body(layout + TBL("last")))

    assert len(found) == 257
    last = found[-1]
    assert (last.name, last.start, last.stop, last.body_at) == (
        "Table 257", 256, 258, 257)


def test_a_BOX_of_two_rows_is_captioned_by_its_FIRST_CELL_alone():
    """A box's caption is its first cell's text. A one-cell box holds
    nothing else, so on every box before the whole table's text read the
    same; the second row here is the box's own words, not its title."""
    box = ("<w:tbl><w:tr>" + cell("Box 1. Key terms") + "</w:tr><w:tr>"
           + cell("Capability: what a person can do.") + "</w:tr></w:tbl>")

    (x,) = ex.exhibits(body(P("Box 1 lists them.") + box), labels=LABELS)

    assert (x.kind, x.caption) == ("box", "Box 1. Key terms")
