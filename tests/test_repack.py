"""`repack` reports which sheet is short and which move would fill it.

Every test drives a FAKE renderer returning one string per sheet, so the
search is exercised without Word. That is the shape `test_placement` uses,
and for the same reason: the thing under test is the decision, not the
renderer. Where a test needs the trial DOCUMENT rather than its pages, the
fake records what it was handed.

The shapes come from the code review of `a90be3a` (the first version of
this module) and from the eight manuscripts it was then measured on; each
docstring says which.
"""
from __future__ import annotations

import pytest
from conftest import make_parts, para, row, run, table
from lxml import etree

from docxkit import repack
from docxkit.errors import DocxKitError, PackageError

W = repack.W


def P(text: str, ppr: str = "") -> str:
    return para(ppr + run(text))


IMG = "<w:p><w:r><w:drawing/></w:r></w:p>"
HEADING = ('<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>')


def SECT(landscape: bool = False) -> str:
    orient = ' w:orient="landscape"' if landscape else ""
    return ('<w:p><w:pPr><w:sectPr>'
            f'<w:pgSz w:w="12240" w:h="15840"{orient}/>'
            "</w:sectPr></w:pPr></w:p>")


def parts(body: str) -> dict[str, bytes]:
    return make_parts(body)


#: a sheet's worth of prose, so the fixtures have a yardstick to be short
#: against — and a leading one, since sheet 1 is a title page by convention
FULL = "word " * 400

#: a figure captioned ABOVE its image, mentioned first
FIGURE = P("Figure 1 shows it.") + P("Figure 1. Cap") + IMG


def order(parts_: dict[str, bytes]) -> list[str]:
    """Each body child as text, 'IMG' or 'SECT', in order."""
    root = etree.fromstring(parts_["word/document.xml"])
    body = root.find(W + "body")
    assert body is not None
    out = []
    for el in body:
        if el.find(".//" + W + "drawing") is not None:
            out.append("IMG")
        elif el.find(W + "pPr/" + W + "sectPr") is not None:
            out.append("SECT")
        else:
            out.append(repack.text_of(el).strip() or "blank")
    return out


def recording(pages_for):
    """A renderer that keeps the ORDER of every document it was handed
    and answers with `pages_for(order)`."""
    seen: list[list[str]] = []

    def render(p):
        seen.append(order(p))
        return pages_for(seen[-1])
    return render, seen


# ------------------------------------------------------- the verdict

def test_a_full_document_reports_nothing_and_pays_ONE_render():
    calls = []

    def render(_p):
        calls.append(1)
        return [FULL, FULL, FULL]

    rep = repack.repack(parts(FIGURE), render=render)

    assert rep.underfull == []
    assert rep.renders == 1, "a clean document must not pay for a search"
    assert "nothing to repack" in rep.format()


def test_the_figures_own_sheet_and_the_two_edges_are_never_short():
    """A full-page figure carries three lines of caption; the title page
    is short because it is one; a document ends where it ends."""
    def render(_p):
        return ["Title", FULL, "Figure 1. Cap", FULL, "tail"]

    rep = repack.repack(parts(FIGURE), render=render)

    assert rep.underfull == []
    assert rep.sheets[2].exhibits == ("Figure 1",)


def test_a_long_tables_continuation_sheets_are_its_own_and_not_short():
    """LE_trends: Table 6 runs from sheet 8 to 12, and sheets 9-11 —
    nothing but rows, 25 % full by characters — were reported short and
    blamed on Table 3, which starts on sheet 13. Every sheet from the
    caption to the last row with text is the table's."""
    rows = [row(f"Country {k}", f"{k}.0") for k in range(1, 30)]
    doc = parts(P("Table 6 reports it. " + FULL) + P("Table 6. Quantile")
                + table(row("Country", "Value"), *rows, row("N", "202"))
                + P("Prose after."))

    def render(_p):
        return [FULL, "Table 6 reports it. " + FULL,
                "Table 6. Quantile Country Value Country 1 1.0",
                "Country 2 2.0 Country 3 3.0", "Country 4 4.0",
                "Country 29 29.0 N 202 Prose after. " + FULL, FULL]

    rep = repack.repack(doc, render=render)

    (landing,) = [z for z in rep.landings if z.name == "Table 6"]
    assert (landing.first, landing.last) == (3, 6)
    assert rep.underfull == []


def test_a_caption_QUOTED_in_earlier_prose_is_not_where_the_table_sits():
    """HCW: the prose on sheet 13 quotes the full captions of Tables 6
    and 7, which sit on sheets 29 and 30. The first sheet carrying the
    text was taken as the table's; now each exhibit is looked for from
    where the one before it ended."""
    quoted = "Table 2. Trends in rates"
    doc = parts(P(f"As {quoted} shows, rates fell.") + P("Table 1. Levels")
                + table(row("Country", "Rate"), row("Serbia", "0.03"))
                + P(quoted) + table(row("Country", "Rate"),
                                    row("Sweden", "0.02")) + P("End."))

    def render(_p):
        return [FULL, f"As {quoted} shows, rates fell. " + FULL,
                "Table 1. Levels Country Rate Serbia 0.03", FULL,
                f"{quoted} Country Rate Sweden 0.02", FULL]

    rep = repack.repack(doc, render=render)

    assert [(z.name, z.first) for z in rep.landings] == [("Table 1", 3),
                                                         ("Table 2", 5)]


def test_the_blamed_exhibit_STARTS_on_the_sheet_after_the_short_one():
    """A short sheet followed by a heading with a page break before it
    is nobody's (the review's case 8: Figure 1 on sheet 8 was blamed
    for it and eight renders went to trials that could not reach it).
    No exhibit, no trial."""
    doc = parts(P("Figure 1 shows it.") + P("Prose.") + P("6. Caveats")
                + P("Figure 1. Cap") + IMG + P("End."))
    calls = []

    def render(_p):
        calls.append(1)
        return [FULL, "Figure 1 shows it. Prose.", "6. Caveats " + FULL,
                "Figure 1. Cap", FULL]

    rep = repack.repack(doc, render=render)

    assert rep.underfull == [2]
    assert rep.blamed == {2: None}
    assert len(calls) == 1
    assert "no exhibit starts on the sheet after it" in rep.format()


def test_an_exhibit_whose_caption_is_on_no_sheet_is_said_so():
    def render(_p):
        return [FULL, FULL, FULL]

    rep = repack.repack(parts(P("Figure 9. Elsewhere") + IMG), render=render)

    assert any("Figure 9: its caption was found on no sheet" in p
               for p in rep.problems)


# ---------------------------------------------------------- the search

def test_a_short_sheet_before_an_exhibit_is_measured_by_RENDERING_the_move():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]

    rep = repack.repack(parts(FIGURE + P("Box text")), render=render,
                        max_candidates=1)

    assert rep.underfull == [2] and rep.blamed == {2: "Figure 1"}
    assert rep.renders == 2, "the saving must be rendered, not predicted"
    assert rep.moves and rep.moves[0].gain == 1
    assert rep.moves[0].after == "Box text"
    assert rep.best is rep.moves[0]
    # spelled out, not signed: `+1 under-filled sheet(s)` said the opposite
    # of what it meant, so the best move in a ranked list read as the worst
    assert "1 fewer under-filled sheet(s)" in rep.format()
    assert "+1 under-filled" not in rep.format()
    assert "1 placement(s) tried, 2 render(s)" in rep.format()


def test_a_move_beyond_the_drift_limit_is_not_offered():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        return [FULL, "Figure 1 shows it. " + FULL, "x", "y", "Figure 1. Cap"]

    rep = repack.repack(parts(FIGURE + P("z")), render=render, max_drift=1,
                        max_candidates=1)

    assert rep.moves == [], "drift 3 is past the limit"
    assert rep.renders == 2, "it still had to render to find that out"
    assert "none within the drift limit" in rep.format()


def test_drift_is_measured_in_the_TRIAL_and_a_missing_mention_is_unmeasured():
    """The review's case 10: drift subtracted the mention's sheet in the
    ORIGINAL render from the caption's sheet in the trial, and fell back
    to 0 — which passes any limit — when either was not found. Both are
    read off the trial, and a miss is reported, not scored."""
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        return [FULL, FULL, FULL, FULL, "Figure 1. Cap"]      # no mention

    rep = repack.repack(parts(FIGURE + P("z")), render=render,
                        max_candidates=1)

    assert rep.moves == []
    assert any("its mention was found on no sheet of the trial" in p
               and "unmeasured" in p for p in rep.problems)


def test_a_move_that_helps_nothing_is_reported_and_not_advised():
    def render(_p):
        return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]

    rep = repack.repack(parts(FIGURE + P("z")), render=render,
                        max_candidates=1)

    assert rep.moves[0].gain == 0 and rep.best is None
    assert "no change" in rep.format()


def test_a_move_that_makes_it_WORSE_says_so_and_ranks_last():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        if len(calls) == 2:                          # after "z": two short
            return [FULL, "Figure 1 shows it.", "z", "Figure 1. Cap", FULL]
        return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]

    rep = repack.repack(parts(FIGURE + P("z") + P("w")), render=render,
                        max_drift=2)

    assert [(m.after, m.gain) for m in rep.moves] == [("w", 1), ("z", -1)]
    assert "1 MORE under-filled sheet(s)" in rep.format()


def test_candidates_are_PROSE_outside_every_exhibit_and_after_the_mention():
    """The review's case 12: a trial that put Figure 1 between Table 1's
    caption and its table ranked first. Not another exhibit's caption or
    note, not a heading, not the paragraph the exhibit already follows."""
    doc = parts(FIGURE + P("Table 1. T") + table(row("cell"))
                + P("Source: x") + P("2. Results", HEADING) + P("prose")
                + P("more"))
    render, seen = recording(lambda _o: [FULL, "Figure 1 shows it.",
                                         "Figure 1. Cap", FULL, FULL])

    rep = repack.repack(doc, render=render, max_drift=9)

    assert [m.after for m in rep.moves] == ["Table 1 and its notes", "prose",
                                            "more"]
    assert seen[2] == ["Figure 1 shows it.", "Table 1. T", "cell", "Source: x",
                       "2. Results", "prose", "Figure 1. Cap", "IMG", "more"]


def test_a_REFERENCE_entry_is_not_a_place_for_an_exhibit():
    """Parental_style: tables at the back, so the nearest prose to
    Table 1 was the reference list, and it was offered eight entries to
    follow. From the References heading to the next heading is out."""
    doc = parts(FIGURE + P("Body prose.") + P("References", HEADING)
                + P("Aaron, H. (2001). A paper.")
                + P("Zed, Q. (1999). Another.")
                + P("Appendix A", HEADING) + P("Appendix prose."))
    render, _ = recording(lambda _o: [FULL, "Figure 1 shows it.",
                                      "Figure 1. Cap", FULL, FULL])

    rep = repack.repack(doc, render=render, max_drift=9)

    assert [m.after for m in rep.moves] == ["Body prose.", "Appendix prose."]


def test_the_target_is_an_INDEX_so_repeated_text_cannot_misplace_the_move():
    """The review's case 13: the target was resolved by text to the first
    paragraph reading it, so with three figures each followed by the same
    `Source:` line Figure 2 landed under Figure 1's."""
    doc = parts(P("Same text.") + FIGURE + P("Middle.") + P("Same text."))
    render, seen = recording(lambda _o: [FULL, "Figure 1 shows it.",
                                         "Figure 1. Cap", FULL, FULL])

    rep = repack.repack(doc, render=render, max_drift=9)

    assert [m.after for m in rep.moves] == ["Middle.", "Same text."]
    assert seen[2] == ["Same text.", "Figure 1 shows it.", "Middle.",
                       "Same text.", "Figure 1. Cap", "IMG"]


def test_a_box_is_an_exhibit_and_its_mention_anchors_it():
    """Aging_Well's two boxes: repack's stem compared four characters of
    a three-letter label, so neither ever found its mention."""
    box = table(row("Box 1. Key terms"), row("Capability: what one can do."))
    doc = parts(P("Box 1 defines them.") + box + P("after"))
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Box 1 defines them.", "Box 1. Key terms", FULL,
                    FULL]
        return [FULL, "Box 1 defines them. " + FULL, "Box 1. Key terms", FULL]

    rep = repack.repack(doc, render=render)

    assert rep.blamed == {2: "Box 1"}
    assert rep.moves and rep.moves[0].name == "Box 1"
    assert not any("mentioned nowhere" in p for p in rep.problems)


def test_a_caption_with_NO_body_is_reported_and_left_where_it_is():
    """A caption over prose is a numbering defect for `crossrefs`, not a
    block to move — and it can still be the exhibit blamed for a short
    sheet, since its caption is on the page."""
    doc = parts(P("Figure 1 shows it.") + P("Figure 1. Cap")
                + P("Just prose under it.") + P("More."))

    def render(_p):
        return [FULL, "Figure 1 shows it.", "Figure 1. Cap Just prose", FULL,
                FULL]

    rep = repack.repack(doc, render=render)

    assert rep.blamed == {2: "Figure 1"} and rep.renders == 1
    assert any("has no table or image of its own — left where it is" in p
               for p in rep.problems)
    assert "not rendered" not in rep.format()


def test_a_table_whose_END_is_on_no_sheet_says_so_and_counts_one_sheet():
    doc = parts(P("Table 1 shows it.") + P("Table 1. Cap")
                + table(row("Country", "Rate"), row("Serbia", "0.03"))
                + P("After."))

    def render(_p):                       # no row of it on any sheet
        return [FULL, "Table 1 shows it.", "Table 1. Cap", FULL, FULL]

    rep = repack.repack(doc, render=render)

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, None)
    assert rep.sheets[2].exhibits == ("Table 1",)
    assert any("its last row was found on no sheet after its caption "
               "(sheet 3)" in p for p in rep.problems)


def test_a_report_with_no_sheets_says_it_was_not_rendered():
    rep = repack.RepackReport()
    rep.problems.append("nothing came back")

    assert "not rendered — nothing to measure" in rep.format()
    assert "! nothing came back" in rep.format()


def test_an_exhibit_nobody_mentions_is_reported_not_moved():
    def render(_p):
        return [FULL, "short", "Figure 1. Cap", FULL, FULL]

    rep = repack.repack(parts(P("prose") + P("Figure 1. Cap") + IMG + P("x")
                              + P("tail")), render=render)

    assert rep.moves == []
    assert any("mentioned nowhere" in p for p in rep.problems)


def test_a_failing_trial_is_reported_and_two_in_a_row_stop_the_search():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        raise DocxKitError("Word could not render trial2.docx")

    rep = repack.repack(parts(FIGURE + P("a") + P("b") + P("c")),
                        render=render, max_drift=9)

    assert len(calls) == 3, "the third candidate was never rendered"
    assert sum("the render failed" in p for p in rep.problems) == 2
    assert any("two renders failed in a row" in p for p in rep.problems)


# ---------------------------------------------------------- sections

def moved(doc: dict[str, bytes], target: int) -> list[str]:
    return order(repack._moved(doc, ("Figure", "1"), target,
                               labels=repack.LABELS, note=repack.NOTE))


def test_an_exhibit_that_OWNS_its_section_moves_with_both_breaks():
    """AFI's landscape panels: a break paragraph on each side. Leave the
    opening one behind and the text before it inherits a landscape
    page; leave the closing one and the exhibit loses its own."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True) + P("After.")
                + P("Later."))

    assert moved(doc, 6) == ["Figure 1 shows it.", "Before.", "After.", "SECT",
                             "Figure 1. Cap", "IMG", "SECT", "Later."]


def test_a_break_SHARED_with_the_prose_above_stays_where_it_stands():
    """The review's case 3a: the main section's closing break travelled
    with the figure, and the paragraph after it was pulled back across
    the boundary onto the short sheet."""
    doc = parts(P("Figure 1 shows it.") + P("Main text ends.")
                + P("Figure 1. Cap") + IMG + SECT() + P("Discussed here.")
                + P("More."))

    assert moved(doc, 6) == ["Figure 1 shows it.", "Main text ends.", "SECT",
                             "Discussed here.", "More.", "Figure 1. Cap",
                             "IMG"]


def test_an_exhibit_alone_in_the_FINAL_section_cannot_move():
    """Its geometry is the body-level `sectPr`, which cannot travel: an
    empty final section renders as a blank page."""
    doc = parts(P("Figure 1 shows it.") + P("a") + P("b") + SECT()
                + P("Figure 1. Cap") + IMG)

    def render(_p):
        return [FULL, "Figure 1 shows it. a b", "Figure 1. Cap"]

    rep = repack.repack(doc, render=render)

    assert rep.renders == 1 and rep.moves == []
    assert any("alone in the final section" in p for p in rep.problems)
    with pytest.raises(PackageError, match="final section"):
        repack._moved(doc, ("Figure", "1"), 1, labels=repack.LABELS,
                      note=repack.NOTE)


def test_a_target_in_ANOTHER_section_is_not_offered():
    """The review's case 3d: a figure sharing a portrait section with its
    mention was offered a target in the landscape section after it."""
    doc = parts(P("Figure 1 shows it.") + P("Figure 1. Cap") + IMG + P("same")
                + SECT() + P("other section") + SECT(True) + P("third"))
    render, _ = recording(lambda _o: [FULL, "Figure 1 shows it.",
                                      "Figure 1. Cap", FULL, FULL])

    rep = repack.repack(doc, render=render, max_drift=9)

    assert [m.after for m in rep.moves] == ["same"]


BODY_SECT = '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'


def test_a_section_OWNER_may_go_anywhere_with_the_same_geometry():
    doc = parts(P("Figure 1 shows it.") + SECT() + P("Figure 1. Cap") + IMG
                + SECT(True) + P("portrait again") + SECT()
                + P("landscape text") + SECT(True) + P("end") + BODY_SECT)
    render, _ = recording(lambda _o: [FULL, "Figure 1 shows it.",
                                      "Figure 1. Cap", FULL, FULL])

    rep = repack.repack(doc, render=render, max_drift=9)

    assert [m.after for m in rep.moves] == ["portrait again", "end"]


def test_the_END_of_another_block_is_a_place_and_the_nearest_comes_first():
    """Every exhibit grouped at the back of a paper sits twenty sheets
    from its mention (HCW: +14 to +38). There the only places are the
    other blocks' ends, and a limit counted from the mention through
    the body's prose never reached them."""
    doc = parts(P("Figure 1 and Table 1 show it.") + P("Body prose one.")
                + P("Body prose two.") + P("Figure 1. Cap") + IMG
                + P("Source: f.") + P("Table 1. T") + table(row("cell"))
                + P("Note: t."))
    # paginated in the TRIAL's order, one exhibit per sheet, so a trial
    # that puts Figure 1 behind Table 1 renders it behind Table 1
    lines = {"Figure 1. Cap": "Figure 1. Cap", "Table 1. T": "Table 1. T cell"}
    render, seen = recording(lambda o: [
        FULL, "Figure 1 and Table 1 show it.",
        *[lines[p] for p in o if p in lines], FULL])

    rep = repack.repack(doc, render=render, max_drift=9, max_candidates=3)

    assert [m.after for m in rep.moves] == [
        "Body prose one.", "Figure 1 and Table 1 show it.",
        "Table 1 and its notes"]
    assert seen[3] == ["Figure 1 and Table 1 show it.", "Body prose one.",
                       "Body prose two.", "Table 1. T", "cell", "Note: t.",
                       "Figure 1. Cap", "IMG", "Source: f."]


def test_an_exhibit_far_from_its_mention_may_move_but_not_FURTHER():
    """`--max-drift 1` would forbid every move of a back-of-paper
    exhibit; what the limit means there is "no further away than it
    already is"."""
    calls = []

    def render(_p):
        calls.append(1)
        pages = [FULL, "Figure 1 shows it. " + FULL, *([FULL] * 5), "short",
                 "Figure 1. Cap", FULL]
        if len(calls) == 2:                          # after "z": one nearer
            pages = [FULL, "Figure 1 shows it. " + FULL, *([FULL] * 5),
                     "Figure 1. Cap", FULL]
        if len(calls) == 3:                          # after "w": one further
            pages = [FULL, "Figure 1 shows it. " + FULL, *([FULL] * 7),
                     "Figure 1. Cap", FULL]
        return pages

    rep = repack.repack(parts(FIGURE + P("z") + P("w")), render=render,
                        max_drift=1)

    assert rep.landings[0].drift == 7
    assert [(m.after, m.drift) for m in rep.moves] == [("z", 6)]


def test_the_report_names_the_drift_it_had_before():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it. " + FULL, "short",
                    "Figure 1. Cap", FULL]
        return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]

    rep = repack.repack(parts(FIGURE + P("z")), render=render,
                        max_candidates=1)

    (m,) = rep.moves
    assert (m.drift_before, m.drift) == (2, 1)
    assert "drift +1 (was +2)" in rep.format()


def test_a_tables_end_is_found_by_an_EARLIER_row_when_the_last_is_not():
    """LE's Table 9 ends on a row of parameter symbols set in OMML,
    which `w:t` does not carry, so its last row is on no sheet; the row
    before it is where the table can be seen to end. A box's end is its
    last paragraph, not its first (Aging_Well's boxes, whose "last row"
    was the whole box, so its probe was the caption again)."""
    doc = parts(P("Table 9 sets it. " + FULL) + P("Table 9. Calibration")
                + table(row("Parameter", "Value"), row("beta", "0.9"),
                        row("", "7"))
                + P("Box 1 says so.")
                + table(row("Box 1. Terms"), row("Capability: a thing."),
                        row("Freedom: another.")) + P("End."))

    def render(_p):
        return [FULL, "Table 9 sets it. " + FULL, "Table 9. Calibration",
                "Parameter Value beta 0.9 σ 7",
                "Box 1 says so. Box 1. Terms", "Capability: a thing.",
                "Freedom: another. End. " + FULL, FULL]

    rep = repack.repack(doc, render=render, labels=repack.LABELS)

    assert [(z.name, z.first, z.last) for z in rep.landings] == [
        ("Table 9", 3, 4), ("Box 1", 5, 7)]
    assert rep.problems == []
