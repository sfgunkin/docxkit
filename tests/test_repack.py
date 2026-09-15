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


def test_a_BLANK_under_the_closing_break_does_not_part_an_owner_from_it():
    """`exhibits` absorbs a blank paragraph under the closing break into
    the span, and judged with it the exhibit read as SHARING its section:
    every trial moved the figure without either break, leaving an empty
    landscape section behind and measuring the figure set in portrait
    (code review, 2026-09-13). The blank is the next section's, and stays."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True) + P("") + P("After.")
                + P("Later."))

    assert moved(doc, 7) == ["Figure 1 shows it.", "Before.", "blank",
                             "After.", "SECT", "Figure 1. Cap", "IMG", "SECT",
                             "Later."]


def test_a_NOTE_under_the_closing_break_goes_WITH_its_owner():
    """The blank's twin, found by the mutation sweep (2026-09-13).
    `exhibits` gives the block a note under its closing break, and judged
    by the note the exhibit read as SHARING its section again: the caption
    and the figure moved alone, and both breaks and the note stayed. No
    body follows that break, so the section is the exhibit's, and the
    note it was given travels with it."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True)
                + P("Note: drawn from the survey.") + P("After.")
                + P("Later."))

    assert moved(doc, 7) == ["Figure 1 shows it.", "Before.", "After.",
                             "SECT", "Figure 1. Cap", "IMG", "SECT",
                             "Note: drawn from the survey.", "Later."]


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


# --- what the first mutation sweep found unpinned (2026-09-13) -------------
#
# 121 of 425 real mutants survived a sample of 460. The report's words were
# pinned by substring, the verdict's edges were never built, the search loop
# ran down one path per test, and the lead paragraph that keeps a QUOTED
# caption from passing for the exhibit was never made to matter.


def _move(**kw):
    """A measured move: `Figure 1` after `z`, one short sheet fewer."""
    import dataclasses

    base = repack.Move(name="Figure 1", after="z", target=3, drift=1,
                       drift_before=None, underfull_before=1,
                       underfull_after=0, sheets_before=3, sheets_after=5)
    return dataclasses.replace(base, **kw)


def _found(doc):
    from docxkit.exhibits import exhibits

    body = repack._body(doc)
    return body, list(body), exhibits(body, labels=repack.LABELS,
                                      note=repack.NOTE)


def _span(doc, name="Figure 1"):
    _body, kids, found = _found(doc)
    return repack._move_span(kids, next(x for x in found if x.name == name))


def _places(doc, name):
    """The places `_candidates` offers exhibit `name`, nearest first."""
    from docxkit.exhibits import mention_of

    body, kids, found = _found(doc)
    x = next(e for e in found if e.name == name)
    span = repack._move_span(kids, x)
    assert not isinstance(span, str), span
    anchor = mention_of(body, x)
    assert anchor is not None
    return [label for _j, label in repack._candidates(
        kids, body, found, x, span=span, anchor=anchor, limit=9)]


def test_a_sheet_a_landing_and_a_move_are_FROZEN():
    """Measurements of one render: the ranking and the report read them
    after the search has moved on."""
    import dataclasses

    for value in (repack.Sheet(1, 2), repack.Landing("Figure 1", 1, 2, 1),
                  _move()):
        first = dataclasses.fields(value)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, first, None)


@pytest.mark.parametrize(("before", "after", "cost"),
                         [(3, 5, 2), (5, 3, -2), (4, 4, 0)])
def test_a_moves_sheet_cost_is_the_DIFFERENCE(before, after, cost):
    assert _move(sheets_before=before,
                 sheets_after=after).costs_a_sheet == cost


def test_a_move_is_described_WHOLE_and_its_sheets_only_when_they_change():
    """A substring test for "1 MORE" passes over "-1 MORE" too."""
    assert repack._describe(_move()) == (
        "Figure 1 after 'z': 1 fewer under-filled sheet(s), 3 -> 5 sheets, "
        "drift +1")
    assert repack._describe(_move(sheets_after=3)) == (
        "Figure 1 after 'z': 1 fewer under-filled sheet(s), drift +1")
    assert repack._describe(_move(underfull_after=3, drift_before=-2)) == (
        "Figure 1 after 'z': 2 MORE under-filled sheet(s), 3 -> 5 sheets, "
        "drift +1 (was -2)")


def test_the_BEST_move_is_the_top_one_and_only_when_it_gains():
    ranked = repack.RepackReport(moves=[_move(), _move(underfull_after=2)])

    assert ranked.best is ranked.moves[0]
    assert repack.RepackReport(moves=[_move(underfull_after=1)]).best is None


def test_a_short_sheet_is_reported_by_ITS_numbers():
    """The sheet a line is about, its share of the yardstick and the sheet
    the blamed exhibit starts on — each read off the right sheet."""
    rep = repack.RepackReport(
        sheets=[repack.Sheet(n, lines=n, chars=10 * n) for n in range(1, 6)],
        underfull=[3], blamed={3: "Figure 1"}, full_chars=100)

    assert ("  sheet 3: 3 line(s), 30 characters, 30% full — Figure 1 "
            "starts on sheet 4") in rep.format()
    rep.full_chars = 0
    assert "30 characters, 0% full" in rep.format()


def test_an_EMPTY_report_measures_against_zero_characters():
    assert ("the fullest text sheet carries 0 characters"
            in repack.RepackReport().format())


def test_a_sheet_at_EXACTLY_the_threshold_is_not_short():
    rep = repack.repack(parts(P("prose")), render=lambda _p: [
        FULL, FULL, "x" * 1200, FULL, FULL])

    assert (rep.full_chars, rep.underfull) == (2000, [])


def test_a_render_with_NO_text_sheet_has_a_yardstick_of_zero():
    rep = repack.repack(parts(P("Figure 1. Cap") + IMG),
                        render=lambda _p: ["Figure 1. Cap"])

    assert (rep.full_chars, rep.underfull) == (0, [])


def test_an_exhibit_on_NO_sheet_does_not_hide_the_ones_after_it():
    doc = parts(P("Figure 9. Elsewhere") + IMG + P("Figure 1 shows it.")
                + P("Figure 1. Cap") + IMG + P("End."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL])

    assert rep.sheets[2].exhibits == ("Figure 1",)


def test_a_mention_at_the_very_START_of_the_render_is_on_sheet_one():
    rep = repack.repack(parts(FIGURE + P("tail")), render=lambda _p: [
        "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL])

    (landing,) = rep.landings
    assert (landing.mention, landing.first, landing.drift) == (1, 2, 1)


@pytest.mark.parametrize(("head", "pages", "said"), [
    (P("Prose.") + P("6. Caveats"),
     [FULL, "Prose.", "6. Caveats " + FULL], ""),
    (P("Figure 2 shows it.") + P("Figure 2. Cap") + P("Just prose under it."),
     [FULL, "Figure 2 shows it.",
      "Figure 2. Cap Just prose under it. " + FULL],
     "Figure 2 has no table or image of its own"),
    (P("prose") + P("Figure 2. Cap") + IMG,
     [FULL, "short", "Figure 2. Cap"], "Figure 2 is mentioned nowhere"),
])
def test_a_short_sheet_nothing_can_help_does_not_END_the_search(
        head, pages, said):
    """One with no exhibit after it, one whose exhibit cannot move and one
    whose exhibit has no mention: each is reported, and the next short
    sheet is still tried."""
    doc = parts(head + P("Figure 1 shows it.") + P("Figure 1. Cap") + IMG
                + P("End.") + P("tail"))

    rep = repack.repack(doc, render=lambda _p: [
        *pages, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL])

    assert rep.underfull == [2, 4] and rep.trials == 2
    assert not said or any(said in p for p in rep.problems)


def test_a_place_too_FAR_does_not_END_the_search_for_a_nearer_drift():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        if len(calls) == 2:                          # after "z": drift 3
            return [FULL, "Figure 1 shows it. " + FULL, FULL, FULL,
                    "Figure 1. Cap"]
        return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]

    rep = repack.repack(parts(FIGURE + P("z") + P("w")), render=render)

    assert [m.after for m in rep.moves] == ["w"]


def test_failed_renders_are_COUNTED_and_only_two_IN_A_ROW_end_the_search():
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) in (2, 4):
            raise DocxKitError(f"render {len(calls)} failed")
        return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]

    rep = repack.repack(parts(FIGURE + P("a") + P("b") + P("c") + P("d")),
                        render=render, max_drift=9)

    assert (rep.trials, rep.renders) == (4, 3)
    assert not any("in a row" in p for p in rep.problems)


def test_the_search_renders_at_most_EIGHT_places_by_default():
    render, _seen = recording(lambda _o: [
        FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL])

    rep = repack.repack(
        parts(FIGURE + "".join(P(f"place {k}") for k in range(10))),
        render=render, max_drift=9)

    assert rep.trials == 8


def test_a_BOX_whose_end_is_on_no_sheet_is_said_so_too():
    box = table(row("Box 1. Terms"), row("Capability: a thing."))

    rep = repack.repack(parts(P("Box 1 says so.") + box + P("After.")),
                        render=lambda _p: [FULL, "Box 1 says so.",
                                           "Box 1. Terms", FULL, FULL])

    assert any("Box 1: its last row was found on no sheet" in p
               for p in rep.problems)


def test_moving_an_exhibit_that_is_not_there_NAMES_it():
    with pytest.raises(PackageError,
                       match="no exhibit Figure 7 with a caption"):
        repack._moved(parts(FIGURE), ("Figure", "7"), 0,
                      labels=repack.LABELS, note=repack.NOTE)


def test_a_moved_document_keeps_its_XML_DECLARATION():
    out = repack._moved(parts(FIGURE + P("z")), ("Figure", "1"), 3,
                        labels=repack.LABELS, note=repack.NOTE)

    assert out["word/document.xml"].startswith(b"<?xml")


def test_a_place_is_named_by_its_first_SIXTY_characters():
    long = ("A long paragraph of prose that goes on well past sixty "
            "characters.")

    assert _places(parts(FIGURE + P(long)), "Figure 1") == [long[:60]]


def test_a_table_with_NO_caption_is_not_a_place():
    doc = parts(FIGURE + table(row("stray cell")) + P("prose"))

    assert _places(doc, "Figure 1") == ["prose"]


def test_the_end_of_an_exhibit_that_SORTS_before_this_one_is_a_place_too():
    doc = parts(P("Table 1 and Figure 1 show it.") + P("Body prose.")
                + P("Table 1. T") + table(row("cell")) + P("Figure 1. Cap")
                + IMG + P("Source: f."))

    assert "Figure 1 and its notes" in _places(doc, "Table 1")


def test_a_figure_owning_NO_section_stays_in_its_own_beside_the_same_page():
    doc = parts(P("Figure 1 shows it.") + P("Figure 1. Cap") + IMG
                + P("same") + SECT() + P("next section, same page")
                + BODY_SECT)

    assert _places(doc, "Figure 1") == ["same"]


@pytest.mark.parametrize("lead", ["", P("More body.")])
def test_after_an_owners_closing_break_is_the_section_the_break_OPENS(lead):
    """Built at an even and an odd index, where `j ^ 1` and `j | 1` part
    company with `j + 1`."""
    doc = parts(P("Table 1 and Figure 1 show it.") + lead + SECT()
                + P("Table 1. T") + table(row("cell")) + SECT(True)
                + P("Portrait prose.") + P("Figure 1. Cap") + IMG
                + P("After.") + BODY_SECT)

    assert _places(doc, "Figure 1") == ["Table 1 and its notes", "After."]


BOOKMARK = '<w:bookmarkStart w:id="9" w:name="_Toc1"/>'


def test_an_owner_whose_span_ends_on_TWO_breaks_moves_with_all_of_them():
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True) + SECT()
                + P("After."))

    assert _span(doc) == (2, 7)


def test_an_owner_in_PANELS_with_a_break_BETWEEN_them_moves_whole():
    """The section closes on the LAST break: a panel under an earlier one
    is still the exhibit's own."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True) + P("Panel B.")
                + IMG + SECT(True) + P("After."))

    assert _span(doc) == (2, 9)


def test_a_PANEL_after_the_last_break_leaves_the_section_OPEN():
    """The second panel shares its section with the prose after it, so no
    section closes on the exhibit's last break and the opening break is
    not the exhibit's to take — and then neither is the break between its
    panels, so the exhibit cannot move without parting them. This used to
    assert only where the move STARTED, and the move it pinned was the one
    that left Panel B behind (BACKLOG, 2026-09-15)."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True) + P("Panel B.")
                + IMG + P("After."))

    assert _span(doc) == PARTED_WHY


def test_a_picture_straight_after_the_closing_break_does_not_REOPEN_it():
    """The span ends at the break, and what follows is the next section's
    even when it is a body: here the next figure, captioned below."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap") + IMG + SECT(True) + IMG
                + P("Figure 2. Below.") + P("After."))

    assert _span(doc) == (2, 6)


def test_the_final_section_is_read_PAST_the_bodys_own_sectPr():
    doc = parts(P("Figure 1 shows it.") + P("a") + SECT()
                + P("Figure 1. Cap") + IMG + BODY_SECT)

    assert _span(doc) == ("is alone in the final section, whose geometry "
                          "is the body's")


def test_after_a_final_figure_a_BLANK_is_nothing_and_an_empty_TABLE_is_not():
    head = P("Figure 1 shows it.") + SECT() + P("Figure 1. Cap") + IMG

    assert _span(parts(head + BOOKMARK + P("") + BODY_SECT)) == (
        "is alone in the final section, whose geometry is the body's")
    assert _span(parts(head + table(row("")) + BODY_SECT)) == (2, 4)


QUOTED = "As Table 1. Levels shows, rates fell."


@pytest.mark.parametrize("before", [P("Filler prose."),
                                    P("Figure 1. A") + IMG])
def test_a_QUOTED_caption_is_passed_over_from_the_prose_in_FRONT(before):
    """HCW's case, made to depend on the lead: the quote sits after the
    cursor, so only starting from the paragraph in front of the block
    reaches the table. At an even and an odd start, where `x.start & 1`
    and `x.start ^ 1` part company with `x.start - 1`."""
    doc = parts(before + P("More filler.") + P(QUOTED)
                + P("Lead para before table.") + P("Table 1. Levels")
                + table(row("Country", "Rate"), row("Serbia", "0.03"))
                + P("End."))
    top = "Figure 1. A" if "Figure 1. A" in before else "Filler prose."

    rep = repack.repack(doc, render=lambda _p: [
        top, "More filler. " + QUOTED + " " + FULL,
        "Lead para before table. Table 1. Levels Country Rate Serbia 0.03",
        FULL])

    (table_1,) = [z for z in rep.landings if z.name == "Table 1"]
    assert (table_1.first, table_1.last) == (3, 3)


def test_a_BLANK_in_front_of_the_block_is_no_lead_to_start_from():
    doc = parts(P("As Figure 2. Two shows.") + P("Figure 1. One") + IMG
                + P("Prose between.") + P("") + P("Figure 2. Two") + IMG
                + P("End."))

    rep = repack.repack(doc, render=lambda _p: [
        "As Figure 2. Two shows. " + FULL, "Figure 1. One",
        "Prose between. " + FULL, "Figure 2. Two", FULL])

    assert [(z.name, z.first) for z in rep.landings] == [("Figure 1", 2),
                                                         ("Figure 2", 4)]


def test_a_tables_END_is_looked_for_AFTER_its_caption_not_before_it():
    """The last row's text is in the paragraph in front of the table too.
    Thirteen characters on the second sheet, so that `at ^ len(probe)`
    lands on that earlier copy as well."""
    doc = parts(P("Serbia 0.03 abc") + P("Table 1. Levels")
                + table(row("Country", "Rate"), row("Serbia", "0.03"))
                + P("End."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Serbia 0.03 abc", "Table 1. Levels Country Rate",
        "Serbia 0.03 End.", FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, 4)


def test_a_tables_end_is_its_last_ROW_with_a_NOTE_under_it():
    rows = [row(f"Country {k}", f"{k}.0") for k in range(1, 30)]
    doc = parts(P("Table 6 reports it. " + FULL) + P("Table 6. Quantile")
                + table(row("Country", "Value"), *rows, row("N", "202"))
                + P("Source: survey.") + P("Prose after."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 6 reports it. " + FULL,
        "Table 6. Quantile Country Value Country 1 1.0",
        "Country 2 2.0 Country 3 3.0", "Country 4 4.0",
        "Country 29 29.0 N 202 Source: survey. Prose after. " + FULL, FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, 6)


def test_a_tables_end_is_read_by_ROW_and_not_by_its_last_cell():
    doc = parts(P("Table 1 shows it. " + FULL) + P("Table 1. X")
                + table(row("Country", "Value"), row("A", "1.0"),
                        row("Total", "1.0"))
                + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 1 shows it. " + FULL, "Table 1. X Country Value A 1.0",
        "Total 1.0 After. " + FULL, FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, 4)


def test_a_tables_end_is_looked_for_in_its_last_FIVE_rows():
    doc = parts(P("Table 1 shows it. " + FULL) + P("Table 1. X")
                + table(row("Head", "H"), row("Row two", "2"),
                        *[row(f"r{k}", "σ") for k in range(3, 7)])
                + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 1 shows it. " + FULL, "Table 1. X Head H",
        "Row two 2 After. " + FULL, FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, 4)


def test_a_table_in_PANELS_ends_where_its_LAST_panel_does():
    doc = parts(P("Table 1 shows it. " + FULL) + P("Table 1. X")
                + table(row("Panel A row", "1")) + P("Panel B.")
                + table(row("Panel B row", "2")) + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 1 shows it. " + FULL, "Table 1. X Panel A row 1",
        "Panel B. Panel B row 2 After. " + FULL, FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, 4)


def test_a_HEADING_STYLED_cell_does_not_end_the_reference_list():
    """`heading_level` reads the string it is handed, so a table whose
    cell is styled Heading1 reads as a heading — the zone walks
    paragraphs, and a table inside the list is neither."""
    styled = ('<w:tbl><w:tr><w:tc><w:p><w:pPr><w:pStyle w:val="Heading1"/>'
              "</w:pPr><w:r><w:t>Not a references heading</w:t></w:r></w:p>"
              "</w:tc></w:tr></w:tbl>")
    doc = parts(FIGURE + P("Body prose.") + P("References", HEADING)
                + P("Aaron, H. (2001). A paper.") + styled
                + P("Zed, Q. (1999). Another.")
                + P("Appendix A", HEADING) + P("Appendix prose."))

    assert _places(doc, "Figure 1") == ["Body prose.", "Appendix prose."]


def test_back_to_back_OWNERS_the_second_is_not_offered_where_it_is():
    """Two landscape tables share a break: Table 1's closing one is Table
    2's opening one, which is where Table 2's span starts. Past index 256,
    so that `ms is j` is not `ms == j` by accident of CPython's cache."""
    filler = "".join(P(f"filler {k}") for k in range(300))
    doc = parts(filler + P("Table 1 and Table 2 show it.") + SECT()
                + P("Table 1. A") + table(row("a")) + SECT(True)
                + P("Table 2. B") + table(row("b")) + SECT(True)
                + P("After.") + SECT() + P("Landscape text.") + SECT(True)
                + P("End.") + BODY_SECT)

    assert _places(doc, "Table 2") == ["Landscape text."]


def test_a_place_after_a_break_that_ENDS_the_document_is_looked_up_there():
    """At an odd index, so that `j | 1 < len(kids)` parts company with
    `j + 1 < len(kids)`: one past the last child is no section at all."""
    doc = parts(P("Figure 1 and Table 1 show it.") + P("Figure 1. Cap") + IMG
                + P("Portrait prose.") + SECT() + P("Table 1. T")
                + table(row("cell")) + SECT(True))

    assert _places(doc, "Figure 1") == ["Portrait prose."]


# --- the whole sweep of 2026-09-15 -----------------------------------------
#
# The first time the module was measured whole: 85 of 1100 real mutants
# survived, most of them where no fixture had put the shape — an XML
# comment in the body, a document past index 256, a paired end marker at
# the tail of an owner's span, a box holding two tables. Three claims
# argued on 2026-09-13 fell to the same shapes.


def test_the_probe_is_the_WIDTH_placement_reads():
    """Forty characters of a caption, a row or a mention: no fixture here
    tells 39 from 40 from 41, and the width is placement's, described
    word for word in both modules. Held equal, as `pages` is held."""
    from docxkit import placement

    assert repack._PROBE == placement._PROBE


def test_a_sheet_and_a_report_start_from_ZERO():
    """`_profile` always passes `chars` and `repack` always sets
    `renders`, so only a caller building one by hand reads the defaults."""
    assert repack.Sheet(1, 2).chars == 0
    report = repack.RepackReport()
    assert (report.renders, report.trials) == (0, 0)


def test_a_move_that_made_it_WORSE_is_never_the_best():
    """`gain > 0`, not `gain != 0`: a loss at the top of a list with
    nothing better in it is reported and not advised."""
    assert repack.RepackReport(moves=[_move(underfull_after=2)]).best is None


def test_none_within_the_limit_is_said_only_of_TRIALS_that_found_none():
    """A report with a move, or one that tried nothing, has no business
    saying the drift limit turned everything away."""
    sheets = [repack.Sheet(1, 1, chars=10)]
    tried = repack.RepackReport(sheets=sheets, trials=1, moves=[_move()])
    untried = repack.RepackReport(sheets=sheets)

    assert "none within the drift limit" not in tried.format()
    assert "none within the drift limit" not in untried.format()


def test_an_XML_COMMENT_in_the_body_is_not_a_place_and_breaks_nothing():
    """`exhibits` counts a comment as a body child, so every walk over
    the body meets one — and a comment's `tag` is lxml's `Comment`
    function, which `==` and `!=` answer and `<`, `<=`, `>`, `>=` refuse
    with a TypeError. Word does not write one; other tools do."""
    doc = parts(FIGURE + "<!-- generated -->" + P("prose"))

    assert _places(doc, "Figure 1") == ["prose"]


def test_a_comment_HOISTED_in_front_of_a_caption_leaves_the_end_readable():
    """`_leading` takes the markers in front of a caption into the span, a
    comment among them, so a table's end is read from a span opening on
    one."""
    doc = parts(P("Table 1 shows it. " + FULL) + "<!-- c -->"
                + P("Table 1. X")
                + table(row("Country", "Value"), row("Total", "1.0"))
                + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 1 shows it. " + FULL,
        "Table 1. X Country Value Total 1.0", "After. " + FULL])

    assert [(z.name, z.first, z.last) for z in rep.landings] == [
        ("Table 1", 3, 3)]


@pytest.mark.parametrize(("opens", "closes"), [
    ('<w:bookmarkStart w:id="7" w:name="_Ref1"/>',
     '<w:bookmarkEnd w:id="7"/>'),
    ('<w:permStart w:id="3" w:edGrp="everyone"/>', '<w:permEnd w:id="3"/>'),
])
def test_an_owner_ENDING_on_a_paired_marker_moves_with_it(opens, closes):
    """`exhibits` gives a block the end marker under it when the marker's
    start is inside the block, and `_move_span` trims only BLANK
    paragraphs off the tail. Trimmed as one, the marker is left behind
    and the pair inverts. `bookmarkEnd` sorts before `w:p` and `permEnd`
    after it, which is why the test takes both."""
    doc = parts(P("Figure 1 shows it.") + P("Before.") + SECT()
                + P("Figure 1. Cap", opens) + IMG + SECT(True) + closes
                + P("After.") + P("Later."))

    assert _span(doc) == (2, 7)


def test_a_box_ends_on_its_last_PARAGRAPH_not_on_its_last_row():
    """A box's end probes are read by paragraph, a table's by row. With
    one paragraph per cell the two agree, which is every box above; a
    last cell of TWO paragraphs, the first longer than the probe, tells
    them apart — by row the probe is the first paragraph, a sheet early."""
    cap = "Capability: what a person is able to do and to be."
    box = ("<w:tbl><w:tr><w:tc>" + P("Box 1. Terms") + "</w:tc></w:tr>"
           "<w:tr><w:tc>" + P(cap) + P("Second para.") + "</w:tc></w:tr>"
           "</w:tbl>")
    doc = parts(P("Box 1 says so. " + FULL) + box + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Box 1 says so. " + FULL, "Box 1. Terms " + cap,
        "Second para. After. " + FULL, FULL])

    assert [(z.name, z.first, z.last) for z in rep.landings] == [
        ("Box 1", 3, 4)]


def test_a_box_holding_TWO_tables_ends_on_the_second():
    """A panel heading lets a body that fits the box into its span, and
    for a box a table holding a picture fits. The box then ends where
    its LAST table does, and its first table's end is a sheet early."""
    box = table(row("Box 1. Terms"), row("Capability: a thing."))
    panel = ("<w:tbl><w:tr><w:tc>" + IMG + "</w:tc><w:tc>"
             + P("Panel B data") + "</w:tc></w:tr></w:tbl>")
    doc = parts(P("Box 1 says so. " + FULL) + box + P("Panel B.") + panel
                + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Box 1 says so. " + FULL, "Box 1. Terms Capability: a thing.",
        "Panel B. Panel B data After. " + FULL, FULL])

    assert [(z.name, z.first, z.last) for z in rep.landings] == [
        ("Box 1", 3, 4)]


def test_a_tables_end_is_NOT_looked_for_past_its_last_five_rows():
    """The other side of the five-row bound: a sixth row from the end
    that IS on the page does not stand in for five that are not."""
    doc = parts(P("Table 1 shows it. " + FULL) + P("Table 1. X")
                + table(row("Head", "H"), row("Row two", "2"),
                        *[row(f"r{k}", "σ") for k in range(3, 8)])
                + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 1 shows it. " + FULL, "Table 1. X Head H",
        "Row two 2 After. " + FULL, FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, None)


def test_the_lead_is_the_paragraph_RIGHT_in_front_of_the_block():
    """`x.start - 1` and nothing near it: two before is the note of the
    exhibit above, which quotes this caption, and so is half the index;
    twice the index is inside the exhibit below. Taken for covered, the
    free lead is skipped and the table lands on the quote."""
    doc = parts(P("Figure 1. A") + IMG
                + P("Source: as Table 1. Levels shows.")
                + P("Lead para before table.") + P("Table 1. Levels")
                + table(row("Country", "Rate"), row("Serbia", "0.03"))
                + P("Note: survey.") + P("Figure 2. B") + IMG + P("End."))

    rep = repack.repack(doc, render=lambda _p: [
        "Figure 1. A", "Source: as Table 1. Levels shows. " + FULL,
        "Lead para before table. Table 1. Levels Country Rate Serbia 0.03 "
        "Note: survey.", "Figure 2. B", "End. " + FULL])

    assert [(z.name, z.first) for z in rep.landings] == [
        ("Figure 1", 1), ("Table 1", 3), ("Figure 2", 4)]


def test_an_exhibit_that_OPENS_the_body_has_no_lead_in_front_of_it():
    """`x.start and …`: at index 0 nothing is in front, and index -1 is
    the LAST paragraph — here one quoting the caption, where the exhibit
    would then be found."""
    doc = parts(P("Figure 1. Cap") + IMG + P("Prose.")
                + P("As Figure 1. Cap shows."))

    rep = repack.repack(doc, render=lambda _p: [
        "Figure 1. Cap", "Prose. " + FULL, "As Figure 1. Cap shows. " + FULL])

    assert [(z.name, z.first) for z in rep.landings] == [("Figure 1", 1)]


def test_a_tables_end_is_the_sheet_of_its_LAST_character():
    """Contrived on purpose: a render that breaks the sheet inside the
    last row's final cell, so its last character opens the next sheet.
    The end is where that character is, not the one before it."""
    doc = parts(P("Table 1 shows it. " + FULL) + P("Table 1. X")
                + table(row("Country", "Value"), row("N", "202"))
                + P("After."))

    rep = repack.repack(doc, render=lambda _p: [
        FULL, "Table 1 shows it. " + FULL, "Table 1. X Country Value N 20",
        "2 After. " + FULL, FULL])

    (landing,) = rep.landings
    assert (landing.first, landing.last) == (3, 4)


def test_blame_past_sheet_256_compares_sheet_NUMBERS():
    """`x.first == n + 1`: past 256 two equal ints computed apart are two
    objects, and identity then blames nobody."""
    blamed = repack._blame([int("280")],
                           [repack.Landing("Figure 1", int("281"),
                                           int("281"), int("280"))])

    assert blamed == {280: "Figure 1"}


def test_a_block_at_index_ZERO_does_not_read_the_last_child_as_its_break():
    """`start > 0`: in a body with no `sectPr` of its own — the schema's
    optional case, which Word never writes — the last child is the break
    this exhibit closes, and reading it as the opening one makes the
    exhibit an owner reaching back to index -1."""
    assert _span(parts(P("Figure 1. Cap") + IMG + SECT())) == (0, 2)


def test_an_owner_whose_opening_break_is_the_FIRST_child_takes_it():
    """Every owner above opens at index 2 or 3."""
    doc = parts(SECT() + P("Figure 1. Cap") + IMG + SECT(True) + P("After."))

    assert _span(doc) == (0, 4)


def test_a_span_ending_on_TWO_breaks_it_does_not_own_leaves_BOTH():
    """The block stops at the FIRST break under it; from the last, it
    would carry a section's close away with the figure."""
    doc = parts(P("Figure 1 shows it.") + P("Main text ends.")
                + P("Figure 1. Cap") + IMG + SECT() + SECT(True)
                + P("After."))

    assert _span(doc) == (2, 4)


def test_an_exhibits_OWN_closing_break_is_not_offered_as_a_place():
    """`y.key != x.key`: every OTHER block's end is a place. `Exhibit.key`
    builds its tuple afresh, so identity would offer the exhibit's own
    last index — here the break it closes, past the part that moves."""
    doc = parts(P("Figure 1 shows it.") + P("Main text ends.")
                + P("Figure 1. Cap") + IMG + SECT())

    assert _places(doc, "Figure 1") == ["Figure 1 shows it."]


def test_an_exhibit_INSIDE_the_reference_list_is_a_place_by_its_end_only():
    """Its caption is in both sets a place must avoid, the blocks and the
    reference list, so a place is outside EITHER, not outside exactly
    one of them."""
    doc = parts(FIGURE + P("Body prose.") + P("References", HEADING)
                + P("Aaron, H. (2001). A paper.") + P("Table 1. T")
                + table(row("cell")) + P("Zed, Q. (1999). Another.")
                + P("Appendix A", HEADING) + P("Appendix prose."))

    assert _places(doc, "Figure 1") == ["Body prose.",
                                        "Table 1 and its notes",
                                        "Appendix prose."]


def test_the_paragraph_ALREADY_followed_is_skipped_past_256():
    """`j == ms - 1`: that trial could only say "no change". Past index
    256 the two numbers are two objects, and identity offers it first."""
    filler = "".join(P(f"filler {k}") for k in range(300))
    doc = parts(filler + P("Figure 1 shows it.") + P("Just before.")
                + P("Figure 1. Cap") + IMG + P("After."))

    assert _places(doc, "Figure 1") == ["Figure 1 shows it.", "After."]


def test_a_BLANK_paragraph_between_two_places_is_not_one():
    """A blank that belongs to no exhibit. One directly under a figure is
    inside its span, which is why every fixture above missed it."""
    doc = parts(FIGURE + P("prose") + P("") + P("more"))

    assert _places(doc, "Figure 1") == ["prose", "more"]


def test_a_block_ending_the_document_on_a_break_is_read_past_256():
    """The break-at-the-end case above, behind 300 paragraphs: `j + 1 <
    len(kids)` compares two ints past CPython's cache."""
    filler = "".join(P(f"filler {k}") for k in range(300))
    doc = parts(filler + P("Figure 1 and Table 1 show it.")
                + P("Figure 1. Cap") + IMG + P("Portrait prose.") + SECT()
                + P("Table 1. T") + table(row("cell")) + SECT(True))

    assert _places(doc, "Figure 1") == ["Portrait prose."]


def test_a_block_closing_SECOND_to_last_is_looked_up_one_child_along():
    """The place after a block that ends on a break is in the section the
    break OPENS: one child along, and still inside the body. Two along,
    or twice the index, reads a different section or none."""
    doc = parts(P("Figure 1 and Table 1 show it.") + P("Figure 1. Cap") + IMG
                + P("Portrait prose.") + P("Table 1. T") + table(row("cell"))
                + SECT() + P("Tail."))

    assert _places(doc, "Figure 1") == ["Portrait prose."]


def test_places_are_ordered_by_DISTANCE_on_both_sides():
    """`abs(c[0] - ms)`. The distances in the ordering test above sort the
    same by XOR; from index 4, with places on both sides, they do not."""
    doc = parts(P("Figure 1 shows it.") + P("a") + P("b") + P("c")
                + P("Figure 1. Cap") + IMG + P("d") + P("e"))

    assert _places(doc, "Figure 1") == ["b", "d", "a", "e",
                                        "Figure 1 shows it."]


def test_the_exhibit_moved_is_the_one_ASKED_for_not_an_earlier_one():
    """`e.key == key` over every exhibit in document order: a Table 1 in
    front of Figure 1 sorts after it, and anything but equality takes
    the table."""
    doc = parts(P("Table 1. T") + table(row("cell")) + P("Figure 1. Cap")
                + IMG + P("prose"))

    assert moved(doc, 4) == ["Table 1. T", "cell", "prose", "Figure 1. Cap",
                             "IMG"]


@pytest.mark.parametrize("target", [1, 2])
def test_a_target_INSIDE_the_block_is_refused_at_either_end(target):
    """Never reached from `repack`, whose places skip the block, so the
    guard is asked directly, at the block's first child and its last."""
    with pytest.raises(PackageError, match="inside Figure 1's own block"):
        repack._moved(parts(FIGURE + P("z")), ("Figure", "1"), target,
                      labels=repack.LABELS, note=repack.NOTE)


def test_the_default_drift_limit_is_ONE_sheet():
    """Every search test above passes `max_drift` or starts a sheet from
    its mention, where `max(max_drift, abs(before))` hides the default.
    From a drift of 0 the default takes a move one sheet out and not one
    two sheets out."""
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "short", "Figure 1 shows it. Figure 1. Cap", FULL,
                    FULL]
        if len(calls) == 2:                          # after "z": drift 1
            return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]
        return [FULL, "Figure 1 shows it. " + FULL, FULL, "Figure 1. Cap"]

    rep = repack.repack(parts(FIGURE + P("z") + P("w")), render=render)

    assert rep.landings[0].drift == 0
    assert [(m.after, m.drift) for m in rep.moves] == [("z", 1)]


def test_a_render_that_WORKS_resets_the_count_of_failures_in_a_row():
    """`failed = 0` after a success, so two failures AFTER one still end
    the search; a count restarted below zero would take three."""
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) in (3, 4):
            raise DocxKitError(f"render {len(calls)} failed")
        return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]

    rep = repack.repack(parts(FIGURE + P("a") + P("b") + P("c") + P("d")),
                        render=render, max_drift=9)

    assert len(calls) == 4, "the fourth candidate was never rendered"
    assert any("two renders failed in a row" in p for p in rep.problems)


def test_the_drift_reported_is_the_MOVED_exhibits_not_an_earlier_ones():
    """`z.name == name` over the trial's landings in document order: a
    Figure 1 in front of the blamed Table 1 sorts before it, and anything
    but equality reads Figure 1's drift for Table 1's move."""
    doc = parts(P("Figure 1 and Table 1 show it.") + P("Figure 1. Cap") + IMG
                + P("prose z") + P("Table 1. T") + table(row("cell"))
                + P("w"))
    calls = []

    def render(_p):
        calls.append(1)
        pages = [FULL, "Figure 1 and Table 1 show it. Figure 1. Cap",
                 "Table 1. T cell", FULL, FULL]
        if len(calls) == 1:
            pages.insert(2, "prose z")
        return pages

    rep = repack.repack(doc, render=render, max_candidates=1)

    assert rep.blamed == {3: "Table 1"}
    assert [(m.name, m.drift) for m in rep.moves] == [("Table 1", 1)]


def test_an_UNMEASURED_trial_does_not_end_the_search():
    """The mention lost in one trial is reported, and the next candidate
    is still rendered and measured."""
    calls = []

    def render(_p):
        calls.append(1)
        if len(calls) == 1:
            return [FULL, "Figure 1 shows it.", "Figure 1. Cap", FULL, FULL]
        if len(calls) == 2:                          # after "z": no mention
            return [FULL, FULL, FULL, FULL, "Figure 1. Cap"]
        return [FULL, "Figure 1 shows it. " + FULL, "Figure 1. Cap", FULL]

    rep = repack.repack(parts(FIGURE + P("z") + P("w")), render=render)

    assert [m.after for m in rep.moves] == ["w"]


def test_a_move_with_NO_change_ranks_above_one_that_makes_it_worse():
    """`-m.gain`: the larger gain first, and a loss below no change at
    all. `not gain` ranks every non-zero gain alike and puts zero last."""
    rep = repack._ranked(repack.RepackReport(
        moves=[_move(underfull_after=2), _move(underfull_after=1)]))

    assert [m.gain for m in rep.moves] == [0, -1]


# --- an exhibit a move would PART (BACKLOG, 2026-09-15) ---------------------

PARTED_WHY = ("is parted by a section break it does not own: moving what "
              "stands before the break would leave the rest behind")


def test_an_exhibit_PARTED_by_a_break_it_does_not_own_is_left_where_it_is():
    """S2, found triaging the whole sweep. The figure closes a section it
    shares with the prose above, and its second panel sits after that
    break. The move stopped at the first break the block did not own, so
    a trial carried the caption and panel A away and left `Panel B.`,
    its picture and the landscape break behind — and the report offered
    it as a placement like any other. Refused now, and said."""
    doc = parts(P("Figure 1 shows it.") + P("Main text ends.")
                + P("Figure 1. Cap") + IMG + SECT() + P("Panel B.") + IMG
                + SECT(True) + P("After.") + P("Later."))
    render, seen = recording(lambda _o: [FULL, "Figure 1 shows it.",
                                         "Figure 1. Cap Panel B.", FULL,
                                         FULL])

    rep = repack.repack(doc, render=render, max_drift=9)

    assert rep.moves == [] and len(seen) == 1, "no trial may be rendered"
    assert f"Figure 1 {PARTED_WHY} — left where it is" in rep.problems
    with pytest.raises(PackageError, match="parted by a section break"):
        repack._moved(doc, ("Figure", "1"), 9, labels=repack.LABELS,
                      note=repack.NOTE)


def test_a_TABLE_panel_after_the_break_parts_its_exhibit_as_a_picture_does():
    """A table shows on the page as a picture does, so a table panel after
    the last break keeps that section open and is the exhibit's own."""
    doc = parts(P("Table 1 shows it.") + P("Before.") + SECT()
                + P("Table 1. Cap") + table(row("a", "1")) + SECT(True)
                + P("Panel B.") + table(row("b", "2")) + P("After."))

    assert _span(doc, "Table 1") == PARTED_WHY
