"""`repack` reports which sheet is short and which move would fill it.

Every test drives a FAKE renderer returning one string per sheet, so the
search is exercised without Word. That is the shape `test_placement` uses, and
for the same reason: the thing under test is the decision, not the renderer.
"""
from __future__ import annotations

import re

import pytest
from conftest import make_parts, para, row, run, table

from docxkit import repack
from docxkit.errors import PackageError

FIG = re.compile(r"^\s*(?:Figure|Table|Box)\s*(\d+)\s*\.", re.IGNORECASE)
MEN = re.compile(r"(?:figure|table|box)\s*(\d+)", re.IGNORECASE)


def P(text: str) -> str:
    return para(run(text))


def DRAWING() -> str:
    """A paragraph carrying an image, which is what makes it an exhibit body.

    Deliberately bare: `wp:inline` and its extent live in a namespace this
    fixture does not declare, and what decides the question is the presence of
    a `w:drawing`, not what is inside it.
    """
    return "<w:p><w:r><w:drawing/></w:r></w:p>"


def SECT(landscape: bool = False) -> str:
    orient = ' w:orient="landscape"' if landscape else ""
    return ('<w:p><w:pPr><w:sectPr>'
            f'<w:pgSz w:w="12240" w:h="15840"{orient}/>'
            "</w:sectPr></w:pPr></w:p>")


def parts(body: str) -> dict[str, bytes]:
    return make_parts(body)


#: a figure: image first, caption under it — the layout `placement._blocks`
#: cannot see, and the reason this module finds its own blocks
FIGURE = DRAWING() + P("Figure 1. Cap")
#: a table: caption first, body under it
TABLE = P("Table 1. Cap") + table(row("cell"))


def test_a_figure_is_found_though_its_caption_sits_under_the_image():
    body = repack._body(parts(P("Figure 1 shows it.") + FIGURE))
    found = repack._exhibits(body, FIG)
    assert list(found) == [("figure", 1)], "caption-below must be recognised"


def test_a_table_is_found_with_its_caption_above():
    body = repack._body(parts(P("Table 1 shows it.") + TABLE))
    assert list(repack._exhibits(body, FIG)) == [("table", 1)]


def test_figure_1_and_table_1_are_two_exhibits_not_one():
    """Found by running the routine on a real manuscript, not by a fixture.

    Keyed by number alone a dict keeps only the last, so a paper with Figure 1,
    Table 1 and Box 1 reported ONE exhibit; the figure pages were then never
    excluded from the fill verdict, and the anchor search matched "Figure 1
    shows…" against TABLE 1's block and offered a move for it.
    """
    body = repack._body(parts(P("Figure 1 shows it. Table 1 lists them.")
                              + FIGURE + TABLE))
    found = repack._exhibits(body, FIG)
    assert sorted(found) == [("figure", 1), ("table", 1)]


def test_the_anchor_is_the_mention_of_THIS_exhibit():
    body = repack._body(parts(P("Table 1 lists them.")
                              + P("Figure 1 shows it.") + FIGURE + TABLE))
    blocks = repack._exhibits(body, FIG)
    anchor = repack._anchor_of(body, "figure", 1, blocks[("figure", 1)], MEN)
    assert anchor is not None
    assert "Figure 1 shows it." in repack._text(anchor), (
        "the figure must anchor to its own mention, not to Table 1's")


def test_a_box_carries_its_caption_in_its_own_first_cell():
    """Measured: two boxes in the manuscript were invisible while only
    body-level PARAGRAPHS were considered as captions."""
    body = repack._body(parts(P("Box 1 defines them.")
                              + table(row("Box 1. Key terms"), row("cell"))))
    found = repack._exhibits(body, FIG)
    assert list(found) == [("box", 1)]
    assert repack._caption_text(found[("box", 1)], FIG).startswith("Box 1.")


def test_a_hoisted_bookmark_does_not_hide_the_figure_above_the_caption():
    """Word lifts a bookmark out of the paragraph it marks, so a captioned
    figure reads `bookmarkStart, caption` at body level. A walk that stopped
    there made one figure invisible and sent the OTHER figure's caption
    forward to claim the next exhibit body it found — a box's table.
    """
    body = repack._body(parts(
        P("Figure 1 shows it.") + DRAWING()
        + '<w:bookmarkStart w:id="9" w:name="Figure1"/>'
        + '<w:bookmarkEnd w:id="9"/>' + P("Figure 1. Cap")
        + table(row("Box 1. Key terms"))))
    found = repack._exhibits(body, FIG)
    assert ("figure", 1) in found
    assert any(e.tag.endswith("}drawing") or e.find(".//" + repack.W
                                                    + "drawing") is not None
               for e in found[("figure", 1)]), (
        "the figure's block must be the image above it, not the box below")


def test_a_full_document_reports_nothing_to_repack():
    def render(_parts):
        return ["a b c", "d e f"]

    rep = repack.repack(parts(P("Figure 1 shows it.") + FIGURE),
                        render=render, caption=FIG, mention=MEN)
    assert rep.underfull == []
    assert rep.renders == 1, "a clean document must not pay for a search"
    assert "nothing to repack" in rep.format()


def test_the_sheet_holding_an_exhibit_is_not_called_under_filled():
    """The fault this guards is the naive line count: a full-page figure
    carries only its caption, so counted by lines it is the emptiest sheet in
    the document when it is the fullest."""
    def render(_parts):
        return ["x\n" * 20, "Figure 1. Cap", "y\n" * 20]

    rep = repack.repack(parts(P("Figure 1 shows it.") + FIGURE + P("after")),
                        render=render, caption=FIG, mention=MEN)
    assert rep.underfull == [], "the figure's own sheet is full by design"
    assert rep.sheets[1].carries_exhibit


def test_a_table_sheet_does_not_become_the_yardstick():
    """Measured on a real manuscript, and the reason fill counts CHARACTERS.

    A rendered table puts every cell on its own line, so by line count the
    appendix notation table scored 70 against a full prose page's 36, became
    the definition of "full", and put twenty ordinary pages at 51%. The same
    pages are 90-100% full of words.
    """
    prose = "word " * 400                      # 36 lines, ~2000 characters
    table_sheet = "\n".join(["cell"] * 70)     # 70 lines, ~280 characters

    def render(_parts):
        return [FULL, prose, table_sheet, prose, FULL]

    rep = repack.repack(parts(P("Figure 1 shows it.") + FIGURE),
                        render=render, caption=FIG, mention=MEN)
    assert 2 not in rep.underfull and 4 not in rep.underfull, (
        "a page full of prose is not under-filled because a table has "
        "more LINES than it")
    assert 3 in rep.underfull, "the table sheet is the sparse one, by words"


def test_the_first_sheet_is_never_under_filled():
    def render(_parts):
        return ["Title", FULL, FULL]

    rep = repack.repack(parts(P("Figure 1 shows it.") + FIGURE),
                        render=render, caption=FIG, mention=MEN)
    assert rep.underfull == [], "a title page is short because it is one"


def test_the_last_sheet_is_never_under_filled():
    def render(_parts):
        return ["x\n" * 20, "tail"]

    rep = repack.repack(parts(P("Figure 1 shows it.") + FIGURE),
                        render=render, caption=FIG, mention=MEN)
    assert rep.underfull == [], "a document ends where it ends"


#: a sheet's worth of prose, so the fixtures have a yardstick to be short
#: against — and a leading one, since sheet 1 is a title page by convention
FULL = "word " * 400


def test_a_short_sheet_before_a_figure_is_found_and_the_saving_is_rendered():
    calls = []

    def render(_parts):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]

    rep = repack.repack(
        parts(P("Figure 1 shows it.") + FIGURE + P("Box text")),
        render=render, caption=FIG, mention=MEN, max_candidates=1)
    assert rep.underfull == [2]
    assert rep.renders == 2, "the saving must be rendered, not predicted"
    assert rep.moves and rep.moves[0].gain == 1
    assert rep.moves[0].after == "Box text"
    # spelled out, not signed: `+1 under-filled sheet(s)` said the opposite
    # of what it meant, so the best move in a ranked list read as the worst
    assert "1 fewer under-filled sheet(s)" in rep.format()
    assert "+1 under-filled" not in rep.format()


def test_a_move_beyond_the_drift_limit_is_not_offered():
    calls = []

    def render(_parts):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        return [FULL, "Figure 1 shows it. " + FULL, "x", "y", "Figure 1. Cap"]

    rep = repack.repack(parts(P("Figure 1 shows it.") + FIGURE + P("z")),
                        render=render, caption=FIG, mention=MEN,
                        max_drift=1, max_candidates=1)
    assert rep.moves == [], "drift 3 is past the limit"
    assert rep.renders == 2, "it still had to render to find that out"
    assert "no placement improves it" in rep.format()


def test_an_exhibit_in_its_own_section_moves_with_the_break_that_opens_it():
    """The asymmetry the module exists to get right: the trailing break is
    obviously the block's, and the leading one is just as much."""
    body = P("Figure 1 shows it.") + SECT() + FIGURE + SECT(True) + P("Box")
    out = repack._moved(parts(body), ("figure", 1), "Box", FIG)
    xml = out["word/document.xml"].decode("utf-8")
    assert xml.index("Box") < xml.index("Figure 1. Cap"), (
        "the target paragraph now precedes the exhibit")
    before = xml[:xml.index("Figure 1. Cap")]
    assert before.count("<w:sectPr") == 1, (
        "the opening break travels with the figure rather than staying behind")


def test_moving_to_a_paragraph_that_is_not_there_is_refused():
    with pytest.raises(PackageError, match="no paragraph reads"):
        repack._moved(parts(P("Figure 1 shows it.") + FIGURE),
                      ("figure", 1), "nowhere", FIG)


def test_moving_an_exhibit_that_has_no_caption_is_refused():
    with pytest.raises(PackageError, match="no exhibit figure 9"):
        repack._moved(parts(P("Figure 1 shows it.") + FIGURE),
                      ("figure", 9), "x", FIG)


def test_an_exhibit_nobody_mentions_is_reported_not_moved():
    def render(_parts):
        return [FULL, "short", "Figure 1. Cap", FULL, FULL]

    rep = repack.repack(parts(P("prose") + FIGURE + P("x") + P("tail")),
                        render=render, caption=FIG, mention=MEN)
    assert rep.moves == []
    assert any("mentioned nowhere" in p for p in rep.problems)


def test_a_short_sheet_with_no_exhibit_after_it_says_so():
    def render(_parts):
        return [FULL, "Figure 1. Cap", "short", FULL, FULL]

    rep = repack.repack(
        parts(P("Figure 1 shows it.") + FIGURE + P("short") + P("tail")),
        render=render, caption=FIG, mention=MEN)
    assert any("not a placement this routine can move" in p
               for p in rep.problems)


def test_a_note_under_a_figure_travels_with_it():
    body = P("Figure 1 shows it.") + FIGURE + P("Source: author.") + P("next")
    out = repack._moved(parts(body), ("figure", 1), "next", FIG)
    xml = out["word/document.xml"].decode("utf-8")
    assert xml.index("next") < xml.index("Source: author."), (
        "an orphaned note is still a paragraph, so no count would catch it")
