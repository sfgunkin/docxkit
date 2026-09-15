"""Where a table lands, and what it takes with it."""
from __future__ import annotations

import re

import pytest
from lxml import etree

from docxkit import placement

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def P(text: str, ppr: str = "") -> str:
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def TBL(*rows: str) -> str:
    cells = "".join(
        f"<w:tr><w:tc><w:p><w:r><w:t>{r}</w:t></w:r></w:p></w:tc></w:tr>"
        for r in rows)
    return f"<w:tbl>{cells}</w:tbl>"


def parts(body: str) -> dict[str, bytes]:
    return {"word/document.xml":
            (f"<w:document {W}><w:body>{body}</w:body></w:document>"
             ).encode()}


NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def body_of(out: dict[str, bytes]) -> etree._Element:
    """The `w:body` these parts carry, asserted present.

    Written once because every test that reads the tree needs it, and
    because `find` answers `None`: a test that walks that reads as a
    failure of the thing under test rather than of its own setup.
    """
    body = etree.fromstring(out["word/document.xml"]).find(NS + "body")
    assert body is not None, "no w:body in the parts under test"
    return body


def tbl_of(body: etree._Element) -> etree._Element:
    """The `w:tbl` in this body, asserted present — same reason as
    `body_of`: a test that walks a None reads as the module's failure."""
    tbl = body.find(NS + "tbl")
    assert tbl is not None, "no w:tbl in the body under test"
    return tbl


def order(out: dict[str, bytes]) -> list[str]:
    """Каждый body child as 'p:<text>' or 'tbl:<first cell>', in order."""
    body = body_of(out)
    seq = []
    for el in body:
        text = "".join(t.text or "" for t in el.iter(NS + "t"))
        seq.append(("tbl:" if el.tag == NS + "tbl" else "p:") + text[:28])
    return seq


def test_a_table_moves_to_the_paragraph_that_first_mentions_it():
    out, rep = placement.place(parts(
        P("Как показано в таблице 1, всё сходится.")
        + P("Совершенно другой абзац.")
        + P("Таблица 1. Заголовок") + TBL("шапка", "строка")
        + P("Примечание. Что-то.")))
    assert order(out) == [
        "p:Как показано в таблице 1, вс",
        "p:Таблица 1. Заголовок",
        "tbl:шапкастрока",
        "p:Примечание. Что-то.",
        "p:Совершенно другой абзац.",
    ], "the caption, the table AND its note travel together, in that order"
    assert rep.placements[0].moved


def test_a_table_already_beside_its_mention_is_not_moved():
    body = (P("Смотри таблицу 1.")
            + P("Таблица 1. Заголовок") + TBL("шапка"))
    out, rep = placement.place(parts(body))
    assert order(out) == ["p:Смотри таблицу 1.", "p:Таблица 1. Заголовок",
                          "tbl:шапка"]
    assert not rep.placements[0].moved, (
        "a table that is already in place must report no move, or every run "
        "of an idempotent pass looks like it did work")


def test_the_caption_is_not_mistaken_for_the_mention():
    """The caption says «Таблица 1» too. Anchoring on it would be a no-op
    that reports success, and the table would never reach the prose."""
    out, rep = placement.place(parts(
        P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Результаты приведены в таблице 1.")))
    assert order(out)[0] == "p:Результаты приведены в табли"
    assert rep.placements[0].moved


def test_a_table_nothing_mentions_is_left_alone_and_reported():
    out, rep = placement.place(parts(
        P("Проза, не упоминающая ничего.")
        + P("Таблица 7. Сирота") + TBL("шапка")))
    assert order(out) == ["p:Проза, не упоминающая ничего",
                          "p:Таблица 7. Сирота", "tbl:шапка"]
    assert any("table 7" in x and "mentions it" in x for x in rep.problems)


def test_keep_together_binds_the_block_but_frees_its_last_paragraph():
    """The last paragraph must NOT keep with next, or Word drags the text
    after the table up onto the table's page — the opposite of the fix."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка", "строка")
        + P("Примечание. Что-то.")
        + P("Следующий абзац.")))
    body = body_of(out)
    keeps = {}
    for el in body:
        if el.tag == NS + "p":
            text = "".join(t.text or "" for t in el.iter(NS + "t"))
            kn = el.find(NS + "pPr/" + NS + "keepNext")
            keeps[text[:12]] = kn is not None
    assert keeps["Таблица 1. З"] is True, "the caption must hold its table"
    assert keeps["Примечание. "] is False, "the note ends the block"
    rows = tbl_of(body).findall(NS + "tr")
    assert all(r.find(NS + "trPr/" + NS + "cantSplit") is not None
               for r in rows)
    last = rows[-1].find(NS + "p/" + NS + "pPr/" + NS + "keepNext")
    assert last is None, "the last ROW must not keep with what follows either"


def test_no_paragraph_property_is_ever_written_INTO_a_table():
    """`el.tag == W + "p"` is what decides who gets paragraph
    properties, and every loop here asks it: the block walk, the
    keep-together pass, the spacing pass, the page break.

    Read as an ordering or an identity — `>=` is true for `w:tbl`,
    `is not` is true for everything, because `W + "p"` builds a fresh
    string every time — a `w:tbl` takes the branch and gets a `w:pPr`
    as its first child. That is well-formed XML and unreadable content:
    CT_Tbl has no pPr, and Word repairs the document on open. Nothing
    in the report changes, because nothing here counts elements."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка", "строка")
        + P("Примечание. Что-то.")
        + P("Следующий абзац.")))

    body = body_of(out)
    for tbl in body.iter(NS + "tbl"):
        assert tbl.find(NS + "pPr") is None, "a table has no w:pPr"
        assert tbl.find(NS + "keepNext") is None
        assert tbl.find(NS + "spacing") is None
        assert tbl.find(NS + "pageBreakBefore") is None
    for row in body.iter(NS + "tr"):
        assert row.find(NS + "pPr") is None, "nor has a row"


def test_every_row_but_the_LAST_keeps_with_the_one_after_it():
    """`last = n == len(rows) - 1`, where twenty mutants sat.

    keepNext on a row binds it to the row below. On the last row it
    binds the TABLE to whatever follows, which drags the next paragraph
    onto the table's page — the thing this module exists to stop. Off
    by one the other way and the second-to-last row is free, so Word
    may break there.

    Three rows, because two cannot tell `len(rows) - 1` from `len(rows)
    // 2` or from `n == 1`."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка", "строка", "итого")))

    rows = tbl_of(body_of(out)).findall(NS + "tr")
    keeps = [any(para.find(NS + "pPr/" + NS + "keepNext") is not None
                 for para in row.iter(NS + "p"))
             for row in rows]
    assert keeps == [True, True, False], keeps
    assert all(r.find(NS + "trPr/" + NS + "cantSplit") is not None
               for r in rows), "and no row may straddle a page"


def test_keep_together_can_be_turned_OFF_row_by_row():
    """`on and not last` — the flag reaches the rows too, which is what
    a caller undoing a previous pass needs. `or` in its place leaves
    every row but the last one bound however it was called."""
    body = body_of(parts(P("Таблица 1. Заголовок")
                         + TBL("шапка", "строка", "итого")))
    block = list(body)
    placement.keep_together(block)

    placement.keep_together(block, on=False)

    rows = tbl_of(body).findall(NS + "tr")
    assert not any(
        para.find(NS + "pPr/" + NS + "keepNext") is not None
        for row in rows for para in row.iter(NS + "p")), "every row let go"
    assert not any(r.find(NS + "trPr/" + NS + "cantSplit") is not None
                   for r in rows)
    assert body.find(NS + "p/" + NS + "pPr/" + NS + "keepNext") is None


def test_an_english_manuscript_needs_no_new_code():
    """The vocabulary is a pattern the caller owns — that is the seam."""
    out, rep = placement.place(parts(
        P("Estimates appear in Table 2.")
        + P("Filler.")
        + P("Table 2. Estimates") + TBL("head", "row")
        + P("Note. Robust errors.")))
    assert order(out)[1:4] == ["p:Table 2. Estimates", "tbl:headrow",
                               "p:Note. Robust errors."]
    assert rep.placements[0].moved


def test_a_split_table_is_given_its_own_page_and_a_repeating_header():
    """The renderer is the only thing that knows where a page ends, so the
    fix is driven by what it reports, not by counting rows."""
    calls = []

    def render(_parts):
        calls.append(1)
        if len(calls) == 1:                    # first look: it straddles
            return ["См. таблицу 1. Таблица 1. Заголовок шапка", "строка"]
        return ["См. таблицу 1.", "Таблица 1. Заголовок шапка строка"]

    out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок")
              + TBL("шапка", "строка")),
        render=render)
    assert len(calls) == 2, (
        "the report must come from a re-render, not a guess")
    pl = rep.placements[0]
    assert pl.own_page and not pl.split
    body = body_of(out)
    caption = [e for e in body if e.tag == NS + "p"][1]
    assert caption.find(NS + "pPr/" + NS + "pageBreakBefore") is not None
    head = tbl_of(body).findall(NS + "tr")[0]
    assert head.find(NS + "trPr/" + NS + "tblHeader") is not None


def test_drift_beyond_the_limit_is_reported_rather_than_hidden():
    def render(_parts):
        return ["См. таблицу 1.", "x", "x", "Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render, max_drift=1)
    assert rep.placements[0].drift == 3
    assert any("sheets after its mention" in x for x in rep.problems)


def test_drift_AT_the_limit_is_not_a_problem():
    """`drift > max_drift`, and the boundary is the whole of what the
    limit means: one sheet away is the ordinary result of anchoring a
    table — the caption goes after the mention, and a page turns. Read
    as `>=`, the default limit reports every table that landed exactly
    where it was put."""
    def render(_parts):
        return ["См. таблицу 1.", "Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render, max_drift=1)

    assert rep.placements[0].drift == 1
    assert rep.problems == [], rep.problems


def test_a_long_caption_is_matched_on_its_FIRST_forty_characters():
    """`_caption_of(block)[:40]`. The needle is cut because a renderer
    lays the caption out its own way — a line break, a hyphenation, a
    non-breaking space where the markup had a plain one — and the tail
    is where that happens. Cut longer and a caption that Word broke
    across two lines is reported "not found", which reads as a table
    the render could not see at all."""
    # the 41st character is a LETTER, deliberately: cut one longer and
    # the needle runs into the word the renderer broke, which is the
    # difference this cut exists to survive
    long_caption = "Таблица 1. Занятость населения по возрасту и полу"
    assert long_caption[40].strip(), "the cut must land mid-word"

    def render(_parts):
        return ["См. таблицу 1.", long_caption[:40] + " ...перенос шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P(long_caption) + TBL("шапка")),
        render=render)

    assert rep.placements[0].caption_sheet == 2, rep.format()


def test_only_and_skip_select_without_touching_the_rest():
    body = (P("В таблице 1 и таблице 2 всё есть.")
            + P("Разделитель.")
            + P("Таблица 1. Первая") + TBL("a")
            + P("Таблица 2. Вторая") + TBL("b"))
    out, _ = placement.place(parts(body), only=[2])
    seq = order(out)
    assert seq[1] == "p:Таблица 2. Вторая", "table 2 moved to the mention"
    assert "p:Разделитель." in seq and seq.index("p:Таблица 1. Первая") > 1


def test_skip_leaves_a_table_alone_and_only_selects_one():
    """`set(only) & set(blocks)` and `wanted -= set(skip)`. The test
    beside this one passes `only` and reads the ORDER, which cannot
    tell a selection from a coincidence — both tables move to the same
    mention paragraph, so table 1 lands next to table 2 either way.
    What decides it is which placements the report holds."""
    body = (P("В таблице 1 и таблице 2 всё есть.")
            + P("Разделитель.")
            + P("Таблица 1. Первая") + TBL("a")
            + P("Таблица 2. Вторая") + TBL("b"))

    _out, only_two = placement.place(parts(body), only=[2])
    _out2, not_two = placement.place(parts(body), skip=[2])

    assert [p.number for p in only_two.placements] == [2]
    assert [p.number for p in not_two.placements] == [1]


def test_a_mention_in_the_paragraph_that_ENDS_a_section_is_inside_it():
    """`index <= end` — a paragraph's `pPr/sectPr` describes the section
    that ends AT it, so that paragraph is the last one INSIDE it, not
    the first of the next. Read as `<`, the mention that closes a
    section is read as belonging to the following one and the move is
    refused as crossing a boundary — with a message naming a boundary
    the table is on the same side of."""
    landscape = ('<w:pPr><w:sectPr><w:pgSz w:orient="landscape"/>'
                 "</w:sectPr></w:pPr>")
    out, rep = placement.place(parts(
        P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Как показано в таблице 1, всё сходится.", landscape)
        + P("Проза второй секции.")))

    assert rep.problems == [], rep.problems
    assert rep.placements[0].moved
    assert order(out)[:2] == ["p:Как показано в таблице 1, вс",
                              "p:Таблица 1. Заголовок"]


def test_the_last_row_is_looked_for_AFTER_the_caption_not_before():
    """`range(start, …)`. A table's last row is searched for from the
    caption's sheet onward, because the same words can appear earlier —
    a row's value quoted in the prose that introduces the table is the
    ordinary case. Searched from the top, the table reads as ending
    before it began, which comes back as `split` and buys the table a
    page break it did not need."""
    def render(_parts):
        return ["См. таблицу 1. Значение 42 обсуждается ниже.",
                "Таблица 1. Заголовок шапка 42"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1. Значение 42 обсуждается ниже.")
              + P("Таблица 1. Заголовок") + TBL("шапка", "42")),
        render=render)

    pl = rep.placements[0]
    assert (pl.caption_sheet, pl.last_sheet) == (2, 2), (
        "the row is on the caption's sheet, not on the one that quotes it")
    assert not pl.split and not pl.own_page


def test_the_render_is_matched_through_its_WHITESPACE():
    """`" ".join(needle.split())` on both sides. A renderer returns the
    text of a page as it laid it out — one space where the markup had a
    line break, a tab or two spaces — so a caption is found only if the
    comparison ignores the difference. Unmatched, every table reads as
    "not found" and the whole rendered half of the report goes blank."""
    def render(_parts):
        return ["См. таблицу 1.", "Таблица 1. Заголовок таблицы шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.")
              + P("Таблица 1.  Заголовок\tтаблицы") + TBL("шапка")),
        render=render)

    assert rep.placements[0].caption_sheet == 2, rep.format()


def test_a_caption_with_no_table_under_it_is_not_a_block():
    """«Таблица 1» opening a sentence in prose is not a caption to move."""
    out, rep = placement.place(parts(
        P("Таблица 1. Это просто предложение, а не подпись.")
        + P("Больше прозы.")))
    assert order(out) == ["p:Таблица 1. Это просто предло",
                          "p:Больше прозы."]
    assert rep.placements == []


def test_the_headline_counts_each_thing_it_names():
    """Four counters in one sentence, and nothing distinguished them:
    every fixture until now moved, kept and spaced the same tables, so
    any counter would do for any of the four. Here one table moves and
    one does not, and the problems are printed under the head — a
    report that lists a table and swallows the reason is worse than
    one that says nothing."""
    out, rep = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Первая") + TBL("a")
        + P("Таблица 2. Никем не упомянута") + TBL("b")))

    assert (rep.placements[0].moved, rep.placements[1].moved) == (
        False, False), "1 is already in place; 2 has no mention"
    head = rep.format().splitlines()[0]
    assert head == ("2 table(s): 0 moved, 2 kept together, 2 spaced, "
                    "0 given their own page"), head
    assert any("table 2" in line for line in rep.format().splitlines()[1:]), (
        rep.format())
    assert order(out)[0] == "p:См. таблицу 1."


def test_the_caption_a_placement_carries_is_trimmed_and_cut():
    """`_text(el).strip()[:70]` — what the report prints for a table.
    A caption is a sentence and Word indents it with whitespace inside
    the run; uncut, one line of the report becomes three, and untrimmed
    it starts in the middle of the column."""
    long_caption = ("Таблица 1. Занятость населения по возрасту, полу, "
                    "городу и селу, 2019 и 2024")
    assert len(long_caption) > 71
    _out, rep = placement.place(parts(
        P("См. таблицу 1.") + P("   " + long_caption) + TBL("шапка")))

    assert rep.placements[0].caption == long_caption[:70]


def test_the_report_says_when_nothing_was_rendered():
    _out, rep = placement.place(parts(
        P("См. таблицу 1.") + P("Таблица 1. З") + TBL("a")))
    assert "not rendered" in rep.format()
    assert rep.placements[0].drift is None


def test_a_caption_pattern_only_matches_at_the_START_of_a_paragraph():
    """`^` in CAPTION. «…приведены в таблице 1. Далее…» is a sentence,
    not a caption, and prose that says it mid-paragraph is everywhere in
    a paper that discusses tables. Unanchored, that paragraph becomes a
    block — the prose around it travels with the next table, and the
    real caption below is never seen because the number is taken."""
    out, rep = placement.place(parts(
        P("Результаты приведены в Таблица 1. Далее следует разбор.")
        + TBL("шапка")
        + P("Таблица 1. Настоящая подпись") + TBL("данные")))

    assert [p.caption for p in rep.placements] == [
        "Таблица 1. Настоящая подпись"], rep.placements
    assert order(out)[0].startswith("p:Результаты приведены")


def test_a_caption_in_CAPITALS_is_still_a_caption():
    """IGNORECASE, and the manuscripts need it: «ТАБЛИЦА 1.» is how a
    Russian paper writes a caption in a small-caps style, and "TABLE 1."
    is how an English one does. Case-sensitive, those papers get no
    placement at all and a report that says nothing is wrong."""
    out, rep = placement.place(parts(
        P("Как показано в ТАБЛИЦЕ 1, всё сходится.")
        + P("Разделитель.")
        + P("ТАБЛИЦА 1. Заголовок") + TBL("шапка")))

    assert rep.placements[0].moved
    assert order(out)[1] == "p:ТАБЛИЦА 1. Заголовок"


def test_a_property_lands_BEFORE_one_the_schema_puts_after_it():
    """`sib.addprevious(node)` — inserted before the first sibling that
    outranks it. `addnext` puts it after that sibling instead, which is
    the same wrong order the `_in_order` docstring was written about:
    CT_PPr is a sequence, and Word calls a pPr in the wrong order
    unreadable content.

    The paragraph has to CARRY a later-ranked property already —
    `w:spacing` here — or keepNext is simply appended and both
    spellings agree."""
    spaced = '<w:pPr><w:spacing w:after="100"/></w:pPr>'
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок", spaced) + TBL("шапка")))

    kids = [x.tag.split("}")[-1] for x in ppr_of(out, "Таблица 1.")]
    assert kids.index("keepNext") < kids.index("spacing"), kids


def test_a_paragraph_that_had_no_properties_gets_them_FIRST():
    """`el.insert(0, ppr)`. `w:pPr` is CT_P's first child; appended
    after the runs it is unreadable content, and `find` cannot see the
    difference — every assertion in this file would still pass."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Следующий абзац.")))

    for para in body_of(out).iter(NS + "p"):
        ppr = para.find(NS + "pPr")
        if ppr is not None:
            assert para[0] is ppr, "w:pPr is CT_P's first child"


def test_the_document_is_written_back_with_the_declaration_word_wants():
    """`xml_declaration=True, standalone=True`. Word writes
    `standalone="yes"` on every part it produces and reads a part
    without a declaration as damaged. Nothing else here looks at the
    bytes — every other test parses them straight back, which cannot
    see a missing prolog at all."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")))

    head = out["word/document.xml"][:80].decode("utf-8")
    assert head.startswith(
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"), head


# Four spellings in this module are equivalent by construction, each
# confirmed with `tools/kill_check.py` (expect_kill=False) rather than
# assumed, and each looks like a gap:
#
# * CAPTION's leading `^`. `_blocks` applies the pattern with `match`,
#   which anchors at the start already — the `^` says so twice. The
#   test above still earns its place: what it pins is that a caption
#   mid-sentence is not a block, which is the reason the anchoring
#   matters however it is written.
# * `_in_order`'s `> rank` as `>=`. `_PPR_RANK` gives every known tag a
#   distinct index and the function returns early when the tag is
#   already there, so equal ranks mean the same tag — and two UNKNOWN
#   tags share the fallback rank, where the order between them is not
#   something CT_PPr has an opinion about.
# * the fallback rank itself, `len(PPR_ORDER)` as `0`. Every tag this
#   module writes — keepNext, spacing, pageBreakBefore — is in the
#   table, so nothing reaches it.
# * `freeze`'s `xml_declaration=True`. lxml writes the declaration
#   whenever `standalone` is set, which it is on the line above; the
#   flag is the belt to that brace, and the test pins the prolog Word
#   actually needs.


def test_a_custom_caption_pattern_overrides_the_default():
    out, rep = placement.place(
        parts(P("See Exhibit 3.") + P("Filler.")
              + P("Exhibit 3. Something") + TBL("a")),
        caption=re.compile(r"^\s*Exhibit\s*(\d+)\s*\.", re.IGNORECASE),
        mention=re.compile(r"Exhibit\s*(\d+)", re.IGNORECASE))
    assert order(out)[1] == "p:Exhibit 3. Something"
    assert rep.placements[0].moved


def test_a_hoisted_bookmark_travels_with_its_table():
    """Word puts a table's bookmarkStart at BODY level, before the caption,
    not inside it. Leaving it behind while the caption moves inverts the
    bookmark — end before start — and `citations.audit_links` reports
    nothing, because it checks that bookmarks PAIR and that links resolve,
    not that one opens before it closes. All twelve of DSI's did this."""
    body = (P("Как показано в таблице 1.")
            + P("Разделитель.")
            + '<w:bookmarkStart w:id="7" w:name="Таблица1"/>'
            + P('Таблица 1. Заголовок<w:bookmarkEnd w:id="7"/>')
            + TBL("шапка"))
    out, _ = placement.place(parts(body))
    root = body_of(out)
    seq = list(root.iter())
    start = next(i for i, e in enumerate(seq) if e.tag == NS + "bookmarkStart")
    end = next(i for i, e in enumerate(seq) if e.tag == NS + "bookmarkEnd")
    assert start < end, "the bookmark must still open before it closes"
    kids = list(root)
    assert kids[1].tag == NS + "bookmarkStart", (
        "the hoisted bookmark moved with its caption, not left behind")
    caption = "".join(t.text or "" for t in kids[2].iter(NS + "t"))
    assert "Таблица 1." in caption


# --- what the report SAYS, and the answers it gives on bad input --------


def test_the_rendered_report_names_every_table_and_where_it_landed():
    """The unrendered branch had a test and the rendered one had none —
    which is the half a person actually reads: sheet, whole or split,
    and how far the table drifted from the words that mention it."""
    def render(_parts):
        return ["См. таблицу 1.", "x", "Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render, max_drift=5)

    out = rep.format()
    assert "1 table(s):" in out
    assert "table 1: sheet 3, whole, drift +2" in out, out
    assert "not rendered" not in out


def test_a_table_the_render_could_not_FIND_says_so():
    """A caption the renderer's text does not carry — Word laid it out
    as an image, or the callback returned prose the block is not in. The
    line says "not found" rather than printing sheet None, which reads
    as sheet zero."""
    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=lambda _p: ["nothing that matches"])

    assert "table 1: not found" in rep.format(), rep.format()
    assert rep.placements[0].caption_sheet is None
    assert rep.placements[0].drift is None, "no sheet, no distance"


def test_a_table_that_STILL_splits_after_its_own_page_is_reported():
    """`own_page` is the last thing this module can do about a table
    taller than the page. When it does not work the report has to say
    so, or the paper reads "1 given their own page" and takes it as
    fixed."""
    def render(_parts):
        return ["См. таблицу 1.", "Таблица 1. Заголовок шапка", "строка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок")
              + TBL("шапка", "строка")),
        render=render)

    pl = rep.placements[0]
    assert pl.own_page and pl.split
    assert any("still splits across sheets 2-3" in x
               for x in rep.problems), rep.problems


def test_parts_with_no_document_are_refused_by_name():
    """`place` is handed a package's parts, and a caller that passes the
    wrong dict gets a sentence rather than a KeyError from three frames
    down."""
    import pytest

    with pytest.raises(placement.PackageError, match=r"no word/document\.xml"):
        placement.place({})

    with pytest.raises(placement.PackageError, match="no w:body"):
        placement.place({"word/document.xml":
                         f"<w:document {W}></w:document>".encode()})


def test_a_caption_in_the_LAST_paragraph_is_not_a_block():
    """`j >= len(kids)`: a caption with nothing after it at all. The
    other half of this guard — a caption followed by prose — has a test;
    this one runs off the end of the body instead, which is what a
    paper whose last line opens «Таблица 5. …» does."""
    out, rep = placement.place(parts(
        P("См. таблицу 5.") + P("Таблица 5. Это последний абзац.")))

    assert rep.placements == []
    assert [s[:16] for s in order(out)] == ["p:См. таблицу 5.",
                                            "p:Таблица 5. Это"]


def test_a_BLANK_paragraph_between_the_caption_and_the_table_is_stepped_over():
    """Word writers put an empty paragraph under a caption as spacing,
    and it is the block's, not the prose's: the caption must still find
    its table, and the blank must travel with them or it is left behind
    in the middle of the sentence the block used to sit in."""
    out, rep = placement.place(parts(
        P("Как показано в таблице 1, всё сходится.")
        + P("Совершенно другой абзац.")
        + P("Таблица 1. Заголовок") + P("") + TBL("шапка")
        + P("Примечание. Что-то.")))

    assert rep.placements[0].moved
    assert order(out) == [
        "p:Как показано в таблице 1, вс",
        "p:Таблица 1. Заголовок",
        "p:",
        "tbl:шапка",
        "p:Примечание. Что-то.",
        "p:Совершенно другой абзац.",
    ]


def test_space_block_on_a_block_with_no_PARAGRAPH_does_nothing():
    """`space_block` is public and takes any block. Spacing is a
    paragraph property, so a block of nothing but a table has nowhere
    to put it — the answer is to do nothing, not to raise from an index
    into an empty list."""
    body = body_of(parts(TBL("шапка")))
    tbl = tbl_of(body)
    before = etree.tostring(tbl)

    placement.space_block([tbl], None)

    assert etree.tostring(tbl) == before


def test_own_page_writes_the_row_properties_a_raw_block_has_none_of():
    """`own_page` is public too, and `place` only ever calls it after
    `keep_together` has already given every row a `w:trPr`. Called on
    its own — which is what a paper does when it knows a table is
    oversized — it has to create them."""
    body = body_of(parts(P("Таблица 1. Заголовок") + TBL("шапка", "строка")
              ))
    block = list(body)

    placement.own_page(block)

    rows = tbl_of(body).findall(NS + "tr")
    assert rows[0].find(NS + "trPr/" + NS + "tblHeader") is not None
    assert rows[0][0].tag == NS + "trPr", (
        "and CT_Row wants it FIRST: a w:trPr after the first cell is "
        "unreadable content, which `find` cannot see")
    assert body.find(NS + "p/" + NS + "pPr/" + NS + "pageBreakBefore") \
        is not None


def test_own_page_breaks_ONCE_and_lets_the_rows_split():
    """Three decisions in four lines, and each is the opposite of what
    `keep_together` wrote:

    * the page break goes on the FIRST paragraph and stops there.
      `continue` in place of the `break` puts one in front of every
      paragraph in the block, so the note starts its own sheet too;
    * `cantSplit` is CLEARED. An oversized table has to split, and the
      goal changes from "do not split" to "split as late as possible";
    * the header row's `w:trPr` is the row's FIRST child, which CT_Row
      requires — inserted anywhere else it is unreadable content, and
      the header that repeats is the whole point of the pass."""
    body = body_of(parts(P("Таблица 1. Заголовок")
                         + TBL("шапка", "строка")
                         + P("Примечание. Что-то.")))
    block = list(body)
    placement.keep_together(block)          # what own_page has to undo

    placement.own_page(block)

    breaks = [el.find(NS + "pPr/" + NS + "pageBreakBefore") is not None
              for el in body if el.tag == NS + "p"]
    assert breaks == [True, False], "one break, on the caption"
    rows = tbl_of(body).findall(NS + "tr")
    assert not any(r.find(NS + "trPr/" + NS + "cantSplit") is not None
                   for r in rows), "an oversized table must be free to split"
    assert rows[0][0].tag == NS + "trPr", "trPr is CT_Row's first child"
    assert rows[0].find(NS + "trPr/" + NS + "tblHeader") is not None


def test_own_page_on_a_table_with_no_rows_is_not_an_error():
    """An empty `w:tbl` is what a half-built table or a stripped one
    leaves, and a header row cannot be marked on it. The page break in
    front still goes on, because that part is about the caption."""
    body = body_of(parts(P("Таблица 1. Заголовок") + "<w:tbl/>"))

    placement.own_page(list(body))

    assert body.find(NS + "p/" + NS + "pPr/" + NS + "pageBreakBefore") \
        is not None


# ------------------------------------------- notes, sections and the gaps --
#
# All three came from one manuscript on 2026-08-19: DSI's таблица 4 lost its
# `*` note and its landscape orientation to a single `place()` call, and
# nothing in the report or the gates said so.

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def SECT(orient: str = "landscape") -> str:
    """A paragraph-level section break — it ENDS the section it sits in."""
    w, h = ("16838", "11906") if orient == "landscape" else ("11906", "16838")
    return (f'<w:pPr><w:sectPr><w:pgSz w:w="{w}" w:h="{h}" '
            f'w:orient="{orient}"/></w:sectPr></w:pPr>')


def ppr_of(out: dict[str, bytes], starts: str) -> etree._Element:
    """The `w:pPr` of the paragraph that opens with `starts`.

    Asserted present rather than answered as None: every caller reads a
    property out of it, and a paragraph this module has written to has
    one by construction."""
    for el in body_of(out):
        if el.tag != W_NS + "p":
            continue
        text = "".join(t.text or "" for t in el.iter(W_NS + "t"))
        if text.startswith(starts):
            ppr = el.find(W_NS + "pPr")
            assert ppr is not None, f"{starts!r} has no w:pPr"
            return ppr
    raise AssertionError(f"no paragraph starts {starts!r}")


def spacing_of(out: dict[str, bytes], starts: str) -> dict[str, str | None]:
    sp = ppr_of(out, starts).find(W_NS + "spacing")
    if sp is None:
        return {}
    return {str(k).split("}")[-1]: (None if v is None else str(v))
            for k, v in sp.attrib.items()}


def test_a_hoisted_bookmark_at_the_TOP_of_the_body_stops_the_walk():
    """`head > 0`. The walk back over hoisted bookmarks has to stop at
    the start of the body; `>= 0` reads `kids[-1]` there, which is the
    LAST child — and Word closes a bookmark at the end of a document
    often enough that the walk then runs backwards from it."""
    out, rep = placement.place(parts(
        '<w:bookmarkStart w:id="7" w:name="Таблица1"/>'
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Как показано в таблице 1, всё сходится.")
        + '<w:bookmarkEnd w:id="7"/>'))

    assert rep.placements[0].moved
    kinds = [el.tag.split("}")[-1] for el in body_of(out)]
    assert kinds == ["p", "bookmarkStart", "p", "tbl", "bookmarkEnd"], kinds


def test_a_star_note_travels_with_its_table():
    """DSI's таблица 4 carries «Примечание…» AND a `*` gloss under it. The
    keyword-only pattern ended the block at the first, and the second was
    left behind where the table used to be."""
    out, _ = placement.place(parts(
        P("Как показано в таблице 1, всё сходится.")
        + P("Совершенно другой абзац.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Примечание. Ориентация.")
        + P("* Высокая доля самостоятельной занятости.")))
    assert order(out) == [
        "p:Как показано в таблице 1, вс",
        "p:Таблица 1. Заголовок",
        "tbl:шапка",
        "p:Примечание. Ориентация.",
        "p:* Высокая доля самостоятельн",
        "p:Совершенно другой абзац.",
    ]


def test_prose_after_a_note_is_NOT_absorbed():
    """The other half of the same rule. DSI's таблица 2 is followed by a
    note and then by ordinary prose, and a looser pattern moves the prose."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Разделитель.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Примечание. Всё перечисленное.")
        + P("Геометрическая форма не является единственной.")))
    seq = order(out)
    assert seq[3] == "p:Примечание. Всё перечисленно"
    assert seq[4] == "p:Разделитель.", (
        "the prose after the note stayed where it was")


def test_a_block_that_owns_a_SECTION_is_not_moved():
    """таблица 4 is wide and owns a landscape section: the note under it
    carries the sectPr. Moving the block left the break behind, so the
    section came to hold one stranded paragraph — a blank landscape sheet —
    and the table was typeset portrait."""
    out, rep = placement.place(parts(
        P("Как показано в таблице 1.")
        + P("Разделитель.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Примечание. Ориентация.", SECT("landscape"))))
    seq = order(out)
    assert seq[0] == "p:Как показано в таблице 1."
    assert seq[1] == "p:Разделитель.", "the block did NOT move"
    assert not rep.placements[0].moved
    assert any("section break" in x for x in rep.problems)


def test_a_move_that_would_cross_a_section_boundary_is_refused():
    out, rep = placement.place(parts(
        P("Как показано в таблице 1.")
        + P("Конец раздела.", SECT("portrait"))
        + P("Таблица 1. Заголовок") + TBL("шапка")))
    assert order(out)[1] == "p:Конец раздела.", "the block did NOT move"
    assert not rep.placements[0].moved
    assert any("another section" in x for x in rep.problems)


def test_the_gap_below_the_block_sits_on_the_last_NOTE():
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Примечание. Ориентация.")
        + P("* Гло сса.")
        + P("Следующий абзац.")))
    assert spacing_of(out, "* Гло")["after"] == "160", "8pt under the block"
    assert spacing_of(out, "Следующий")["before"] == "0", (
        "the resuming paragraph is zeroed, so the gap is 8pt and not 8pt "
        "plus whatever it already carried")


def test_a_blank_paragraph_INSIDE_the_block_is_not_where_the_gap_goes():
    """`block[-1].tag == W + "p"` asks whether the block ENDS with a
    paragraph — whether the table has a note under it. Asked of
    `block[0]` it answers about the caption instead, which is a
    paragraph in nearly every block there is.

    The two part company on a note-less table whose caption is followed
    by the blank paragraph Word writers leave there: the gap then lands
    on that blank, between the caption and its own table, and the
    paragraph that resumes after the table gets none."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + P("") + TBL("шапка")
        + P("Следующий абзац.")))

    assert spacing_of(out, "Следующий")["before"] == "160", (
        "the gap sits under the table, on the paragraph that resumes")
    assert spacing_of(out, "Таблица 1.")["after"] == "40", "the caption's 2pt"


def test_a_table_with_NO_note_puts_the_gap_on_the_next_paragraph():
    """A table cannot carry spacing — w:spacing is a paragraph property —
    so this is the only place the gap can live."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Следующий абзац.")))
    assert spacing_of(out, "Следующий")["before"] == "160"


def test_a_HEADING_after_a_block_keeps_its_own_spacing():
    """A heading's space-before belongs to its style. Overriding it here
    would leave the two headings that happen to follow a table sitting
    closer to the text above them than every other heading in the paper."""
    heading = ('<w:pPr><w:pStyle w:val="Heading2"/>'
               '<w:spacing w:before="280" w:after="80"/></w:pPr>')
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Примечание. Ориентация.")
        + P("5.2. Источники данных", heading)))
    assert spacing_of(out, "Примечание.")["after"] == "160"
    assert spacing_of(out, "5.2.")["before"] == "280", "untouched"


def test_the_caption_is_single_spaced_with_two_points_under_it():
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок") + TBL("шапка")))
    sp = spacing_of(out, "Таблица 1.")
    assert sp["after"] == "40" and sp["line"] == "240"
    assert sp["lineRule"] == "auto"


def test_keepNext_lands_AFTER_pStyle_in_CT_PPr_order():
    """`_flag` inserted at index 0, which is right for pStyle and wrong for
    everything else — it put keepNext ahead of a pStyle already there. lint
    did not catch it: its CT_PPr check asks only that nothing which must
    precede w:rPr follows it."""
    styled = '<w:pPr><w:pStyle w:val="Caption"/></w:pPr>'
    out, _ = placement.place(parts(
        P("См. таблицу 1.")
        + P("Таблица 1. Заголовок", styled) + TBL("шапка")))
    kids = [x.tag.split("}")[-1] for x in ppr_of(out, "Таблица 1.")]
    assert kids.index("pStyle") < kids.index("keepNext")
    assert kids.index("keepNext") < kids.index("spacing")


def test_the_gap_looks_PAST_a_hoisted_bookmark_to_the_next_paragraph():
    """Word hoists a table's bookmark to body level, so the element after a
    block is usually the NEXT table's bookmarkStart, not its caption. A rule
    that only inspects `getnext()` then does nothing, silently — which is how
    DSI's таблица 7 caption kept the before-spacing this rule zeroes."""
    out, _ = placement.place(parts(
        P("См. таблицу 1 и таблицу 2.")
        + P("Таблица 1. Первая") + TBL("a")
        + P("Примечание. Первое.")
        + '<w:bookmarkStart w:id="9" w:name="Таблица2"/>'
        + P("Таблица 2. Вторая") + TBL("b")
        + '<w:bookmarkEnd w:id="9"/>'),
        move=False)
    assert spacing_of(out, "Примечание. Первое")["after"] == "160"
    assert spacing_of(out, "Таблица 2.")["before"] == "0", (
        "the next block's caption was found past the hoisted bookmark")


# --- the run of 2026-08-20: 9.6 % (41/426), the package's worst -------


def test_a_caption_with_NO_TABLE_does_not_end_the_walk():
    """`continue`, on the caption whose table is missing. A paper gets
    one by deleting a table and leaving its caption behind, or by
    numbering a figure caption "Таблица" — and `break` there abandons
    every table further down the document, silently: the report lists
    the ones it found, and the ones it never reached are not mentioned
    at all."""
    out, rep = placement.place(parts(
        P("См. таблицу 2.")
        + P("Таблица 1. Заголовок без таблицы")
        + P("Проза.")
        + P("Таблица 2. Заголовок") + TBL("шапка")))

    assert [pl.number for pl in rep.placements] == [2]
    assert order(out)[:3] == ["p:См. таблицу 2.", "p:Таблица 2. Заголовок",
                              "tbl:шапка"]


def test_a_table_on_its_MENTIONS_OWN_SHEET_is_not_a_problem():
    """`drift > max_drift` read as `is not`. Zero drift is the outcome
    the whole pass is FOR — the table landed on the sheet that mentions
    it — and inequality reports it as a problem needing a hand. The
    boundary case (drift == limit) is pinned above and agrees with
    either reading; this is the one that does not."""
    def render(_parts):
        return ["См. таблицу 1. Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render, max_drift=1)

    assert rep.placements[0].drift == 0
    assert rep.problems == [], rep.problems


def test_properties_are_inserted_FIRST_not_before_the_last_child():
    """`insert(0, ...)` for both `w:trPr` and `w:pPr`. CT_Row and CT_P
    put their properties first, and Word rejects a row or a paragraph
    that states them anywhere else — but a fixture whose row has one
    cell and whose paragraph has one run cannot see the difference:
    `insert(-1)` and `insert(0)` are the same position there.

    Two cells and two runs are what a table out of a paper has."""
    row = ("<w:tr><w:tc><w:p><w:r><w:t>a</w:t></w:r>"
           "<w:r><w:t>b</w:t></w:r></w:p></w:tc>"
           "<w:tc><w:p><w:r><w:t>c</w:t></w:r></w:p></w:tc></w:tr>")
    body = body_of(parts(P("Таблица 1. Заголовок") + f"<w:tbl>{row}</w:tbl>"))

    placement.keep_together(list(body))

    tr = tbl_of(body).find(NS + "tr")
    assert tr is not None
    assert [etree.QName(c).localname for c in tr] == ["trPr", "tc", "tc"]
    para = tr.find(NS + "tc/" + NS + "p")
    assert para is not None
    assert [etree.QName(c).localname for c in para] == ["pPr", "r", "r"]


def test_a_body_of_THREE_HUNDRED_children_walks_off_neither_end():
    """Two identity comparisons against `len(kids)`, one per loop in
    `_blocks`. CPython caches the integers up to 256, so `j is
    len(kids)` answers the same as `j == len(kids)` for every fixture in
    this file — and differently for every real manuscript, where the
    body has hundreds of children. Past 256 the guard stops firing and
    the walk indexes off the end of the list.

    Both loops reach the end of the body under an ordinary shape: a
    caption at the very bottom with its table lost, and a table that IS
    the last thing in the document. The first is a deleted table's
    caption left behind; the second is an appendix."""
    prose = "".join(P(f"Прозаический абзац {i}.") for i in range(296))

    ends_with_caption = parts(P("См. таблицу 1.") + prose
                              + P("Таблица 1. Заголовок"))
    _out, rep = placement.place(ends_with_caption)
    assert rep.placements == []

    ends_with_table = parts(P("См. таблицу 1.") + prose
                            + P("Таблица 1. Заголовок") + TBL("шапка"))
    out, rep = placement.place(ends_with_table)
    assert [pl.number for pl in rep.placements] == [1]
    assert order(out)[:3] == ["p:См. таблицу 1.", "p:Таблица 1. Заголовок",
                              "tbl:шапка"]


def test_a_table_OWN_PAGE_fixed_is_not_reported_as_still_splitting():
    """The second measurement, after the fix. The table's end is searched
    from the table's own first row, never from the top of the document,
    where a row's value quoted in the prose matches first. That was
    `_sheet_of(..., start=pl.caption_sheet - 1)` until `_locate` replaced
    it, and the arithmetic readings of that expression each put the start
    somewhere else: `% 1` and `& 1` at the top of the document, `* 1` one
    sheet LATE, where the row on the caption's own sheet is no longer
    visible and the answer is None.

    Every one of them turns a table that own_page FIXED into a problem
    line — "still splits across sheets 2-1", or 2-None. The paper then
    says a table nothing can fix is unfixed, about the one table the
    module just fixed.

    The renderer answers differently on the two calls because the
    document CHANGED between them; a fixture whose render is constant
    cannot see this branch at all."""
    calls: list[int] = []

    def render(_parts):
        calls.append(1)
        if len(calls) == 1:
            return ["См. таблицу 1. строка обсуждается ниже.",
                    "Таблица 1. Заголовок шапка", "строка"]
        return ["См. таблицу 1. строка обсуждается ниже.",
                "Таблица 1. Заголовок шапка строка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1. строка обсуждается ниже.")
              + P("Таблица 1. Заголовок") + TBL("шапка", "строка")),
        render=render)

    pl = rep.placements[0]
    assert len(calls) == 2, "the fix has to be measured again"
    assert pl.own_page is True
    assert (pl.caption_sheet, pl.last_sheet) == (2, 2)
    assert pl.split is False
    assert rep.problems == [], rep.problems


def test_a_hoisted_bookmark_travels_from_an_EVEN_index_too():
    """`kids[head - 1]`, the walk back over the bookmarks Word hoists to
    body level. Read as `kids[head ^ 1]` it walks FORWARD whenever the
    caption sits at an even index — xor with 1 is minus one for an odd
    number and PLUS one for an even one — and the bookmark is left
    where it stood while the caption moves off, which is the inverted
    bookmark this loop exists to prevent.

    The test above has its caption at index 3, where the two readings
    agree. This one puts it at index 2."""
    body = (P("См. таблицу 1.")
            + '<w:bookmarkStart w:id="9" w:name="Таблица1"/>'
            + P("Таблица 1. Заголовок") + TBL("шапка")
            + '<w:bookmarkEnd w:id="9"/>'
            + P("Следующий абзац."))

    out, _rep = placement.place(parts(body))

    kids = list(body_of(out))
    names = [etree.QName(el).localname for el in kids]
    assert names.index("bookmarkStart") < names.index("tbl"), names
    assert names.index("bookmarkStart") < names.index("bookmarkEnd")
    assert names == ["p", "bookmarkStart", "p", "tbl", "bookmarkEnd", "p"]


def test_a_mention_in_an_EARLIER_section_is_refused_too():
    """`here != there`, read as `>`. The guard is about crossing a
    section boundary, and a boundary has two sides: `>` refuses the
    table that sits AFTER its mention and moves the one that sits
    before it — into another section, which is what the message beside
    it says must not happen. A table in the body mentioned from an
    appendix is the ordinary shape of that."""
    section_end = ('<w:p><w:pPr><w:sectPr>'
                   '<w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:pPr>'
                   "<w:r><w:t>Конец первого раздела.</w:t></w:r></w:p>")
    body = (P("Таблица 1. Заголовок") + TBL("шапка") + section_end
            + P("См. таблицу 1 в основном тексте."))

    out, rep = placement.place(parts(body))

    assert rep.placements[0].moved is False
    assert any("another section" in x for x in rep.problems), rep.problems
    assert order(out)[:2] == ["p:Таблица 1. Заголовок", "tbl:шапка"]


def test_a_report_says_NOTHING_was_spaced_when_nothing_was():
    """`Placement.spaced` defaults to False because only the branch
    that spaces a block sets it. Defaulted the other way the summary
    line reads "1 spaced" for a run called with `space=False` — the
    same shape as `house`'s width flag, one module over."""
    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок")
              + TBL("шапка")), space=False)

    assert rep.placements[0].spaced is False
    assert "0 spaced" in rep.format().splitlines()[0]


def test_the_report_quotes_SEVENTY_characters_of_the_mention():
    """`anchor_text` is what a caller prints to say WHICH sentence the
    table was anchored to — the paragraph a paper's own script names in
    its log. Seventy characters is a line; a mention runs longer than
    that whenever it is a real sentence."""
    long_mention = ("Как показано в таблице 1, доля занятых в сельском "
                    "хозяйстве снижается во всех регионах выборки.")
    assert len(long_mention) > 71

    _out, rep = placement.place(
        parts(P(long_mention) + P("Таблица 1. Заголовок") + TBL("шапка")))

    assert rep.placements[0].anchor_text == long_mention[:70]
    assert len(rep.placements[0].anchor_text) == 70


def test_a_TABLE_that_mentions_the_table_is_not_the_anchor():
    """`if el.tag != W + "p" or id(el) in owned: continue`. Read as an
    identity — `el.tag is W + "p"`, which is False for every element,
    since the right-hand side is a fresh concatenation — the guard
    collapses to the `owned` half and a `w:tbl` becomes eligible.

    A layout table with no caption is not owned by any block, and a
    note row that says "См. таблицу 1" is an ordinary thing to write
    inside one. The table would then be anchored to a TABLE rather than
    to the sentence that introduces it — moved above the prose that
    mentions it, which is the opposite of the whole pass."""
    body = (P("Прочая проза.")
            + TBL("См. таблицу 1.")            # a layout table, uncaptioned
            + P("См. таблицу 1 в тексте.")     # the mention
            + P("Таблица 1. Заголовок") + TBL("шапка"))

    out, rep = placement.place(parts(body))

    assert rep.placements[0].anchor_text.startswith("См. таблицу 1 в тексте")
    assert order(out) == ["p:Прочая проза.", "tbl:См. таблицу 1.",
                          "p:См. таблицу 1 в тексте.",
                          "p:Таблица 1. Заголовок", "tbl:шапка"]


def test_the_row_and_the_MENTION_are_matched_on_forty_characters_too():
    """The caption's cut has a test; the other two keys — the last row,
    found now by `_locate`, and the mention, by `_sheet_of` — did not.
    All three are cut for the same reason — a
    renderer lays text out its own way, and the tail is where a line
    break or a hyphenation lands — and cutting longer turns "found on
    sheet 2" into "not found", which reads as a table that split
    (`last_sheet`) or a mention nobody can locate (`drift is None`).

    Both needles here agree with the render for forty characters and
    diverge after it."""
    mention = "См. таблицу 1, где занятость населения по возрасту и полу"
    last_row = "Итого по всем регионам выборки за периоды наблюдения"
    caption = "Таблица 1. Заголовок"
    assert mention[40].strip() and last_row[40].strip(), "cut mid-word"

    def render(_parts):
        return [mention[:40] + " ...перенос",
                caption + " шапка " + last_row[:40] + " ...перенос"]

    _out, rep = placement.place(
        parts(P(mention) + P(caption) + TBL("шапка", last_row)),
        render=render)

    pl = rep.placements[0]
    assert (pl.mention_sheet, pl.caption_sheet, pl.last_sheet) == (1, 2, 2)
    assert pl.drift == 1 and pl.split is False
    assert rep.problems == [], rep.problems


# --- the argued half of placement's 41 ---------------------------------
#
# Thirty-five are left after the six tests above, and most of them are
# ONE argument: a tag test standing in front of a structural lookup
# that answers empty for the wrong element anyway.
#
# `_section_ends` reads `el.tag == W + "p" and el.find("pPr/sectPr")`.
# Read as `>=` it also admits `w:tbl` and `w:sectPr`; read as `<=`,
# `w:bookmarkStart` — and none of them HAS a `pPr/sectPr` child, so the
# second half of the condition answers the same. `own_page`'s
# `e.tag == W + "tbl"` generator read as `is not` admits every element
# in the block, and `findall(W + "tr")` answers `[]` for all of them
# except the table it was already going to find. `space_block`'s three
# `following.tag == W + "p"` tests guard a `find("pPr/pStyle")` that is
# None for a table.
#
# The tag test is a fast path, not a decision. Where it IS a decision —
# `_blocks`' `el.tag != W + "p"` in front of the caption match, and
# `_anchor`'s in front of the mention match — a mutant reads a TABLE's
# text as a caption or a mention, which needs a table whose own text
# matches the pattern. Those are named here rather than argued: a note
# row reading "см. таблицу 2" is a real thing to write, and no fixture
# in this file has one.
#
# Also argued and checked: `already = anchor.getnext() is block[0]` read
# as `==`. lxml elements define no `__eq__`, so equality IS identity.
#
# The not-worked list is empty. It held twelve entries this afternoon
# and every one of them came off it: the three arithmetic readings of
# the re-measure's start index, `Placement.spaced`, `here != there`,
# `_anchor`'s tag guard, and the four `[:40]` match keys — pinned by a
# render that agrees with the block for forty characters and diverges
# after, which is the shape the caption test already had.
#
# (Three other entries were on this list and came off it the same
# afternoon: `pl.caption_sheet - 1`, `Placement.spaced`'s default, and
# `here != there`. A list of what is not done is worth keeping for that
# reason — it is the next round's starting point, and it shrinks.)


# --------------------------------------------------- the exhibit block ---
#
# AFI moved four figures to the appendix on 2026-08-19 by hand-rolling
# the span, and the span was wrong: two landscape orientations and eight
# footer parts went with it. Every word survived, so the caption
# inventory balanced, the text diff was clean and a 560-check verifier
# passed. `validate` caught it on a count nobody read.

DRAW = "<w:p><w:r><w:drawing/></w:r></w:p>"
LANDSCAPE = ('<w:p><w:pPr><w:sectPr><w:pgSz w:orient="landscape"/>'
             "</w:sectPr></w:pPr></w:p>")


def test_a_FIGURE_block_carries_the_paragraph_that_looks_empty():
    """That paragraph is the section break, and for the wide panels the
    section it ends is the landscape one. Read as a spacer and left
    behind, the figure lands in a portrait section."""
    block = placement.exhibit_block(
        parts(P("Prose before.") + P("Figure 5. Lorenz curves") + DRAW
              + P("Source: World Bank.") + LANDSCAPE + P("Prose after.")),
        "Figure 5.")

    assert len(block.elements) == 4, [e.tag for e in block.elements]
    assert block.ends_a_section
    assert block.caption == "Figure 5. Lorenz curves"


def test_a_TABLE_block_is_the_same_walk_it_always_was():
    """The rule generalises by one clause — the exhibit's body is a
    `w:tbl` OR a paragraph holding a drawing — and must not change what
    a table's block has always been."""
    block = placement.exhibit_block(
        parts(P("Prose.") + P("Table 3. Counts") + TBL("a")
              + P("Source: mine.") + P("Prose resumes here.")),
        "Table 3.")

    assert [e.tag.split("}")[1] for e in block.elements] == ["p", "tbl", "p"]
    assert not block.ends_a_section


def test_the_block_takes_the_bookmarks_WORD_HOISTED_in_front_of_it():
    """Word puts a table's bookmarkStart at body level, before the
    caption. Leaving it behind inverts the bookmark, and `audit_links`
    reports nothing — it checks pairing, not order."""
    block = placement.exhibit_block(
        parts(P("Prose.") + '<w:bookmarkStart w:id="1" w:name="Table3"/>'
              + '<w:bookmarkEnd w:id="1"/>'
              + P("Table 3. Counts") + TBL("a")),
        "Table 3.")

    assert [e.tag.split("}")[1] for e in block.elements] == [
        "bookmarkStart", "bookmarkEnd", "p", "tbl"]


def test_a_block_whose_OWN_PAGE_comes_from_the_one_before_says_so():
    """No `pageBreakBefore` anywhere: the figure gets its own page only
    because the block in front ends a section. Moved somewhere with
    nothing in front, it shares a page with whatever it lands under."""
    block = placement.exhibit_block(
        parts(P("Prose.") + LANDSCAPE + P("Figure 5. Curves") + DRAW),
        "Figure 5.")

    assert block.shares_a_page


def test_a_block_with_its_OWN_page_break_does_not():
    brk = "<w:pPr><w:pageBreakBefore/></w:pPr>"
    block = placement.exhibit_block(
        parts(P("Prose.") + LANDSCAPE + P("Figure 5. Curves", brk) + DRAW),
        "Figure 5.")

    assert not block.shares_a_page


def test_the_LAST_block_in_the_body_says_so():
    """Moving it leaves the body-level sectPr governing no content, and
    an empty final section renders as a blank page. The last block's
    geometry has to be promoted into the body sectPr instead."""
    last = placement.exhibit_block(
        parts(P("Prose.") + P("Figure 5. Curves") + DRAW), "Figure 5.")
    middle = placement.exhibit_block(
        parts(P("Prose.") + P("Figure 5. Curves") + DRAW + P("After.")),
        "Figure 5.")

    assert last.last_in_body
    assert not middle.last_in_body


def test_a_caption_that_is_ONLY_its_label_is_still_a_caption():
    """The title often sits in the next paragraph, which leaves a
    caption whose whole text is "Figure 1." — and the pattern was
    matched against STRIPPED text while ending in `\\s`, so the strip
    took the one character it needed. `exhibit_block` refused a real
    caption ("a mention of it in prose is not one") and `_beside` could
    not see such a caption standing between a table and another.
    """
    block = placement.exhibit_block(
        parts(P("Prose.") + P("Figure 1.") + DRAW + P("Source: mine.")),
        "Figure 1.")

    assert block.caption == "Figure 1."
    assert len(block.elements) == 3, [e.tag for e in block.elements]


def test_a_MENTION_of_the_caption_in_prose_is_not_a_caption():
    """A caption OPENS its paragraph. Taking a mention would return a
    span of prose and a caller would move it."""
    with pytest.raises(placement.PackageError, match="OPENS its paragraph"):
        placement.exhibit_block(
            parts(P("As Figure 5. shows, it rises.")), "Figure 5.")


def test_a_caption_with_NOTHING_under_it_is_refused():
    """This returns an exhibit's span. A caption over prose is a
    numbering defect for `crossrefs` to report, not a block to move."""
    with pytest.raises(placement.PackageError, match="no table or image"):
        placement.exhibit_block(
            parts(P("Figure 5. Curves") + P("Just prose here.")), "Figure 5.")


def test_TWO_captions_containing_the_string_are_refused():
    with pytest.raises(placement.PackageError, match="2 caption paragraphs"):
        placement.exhibit_block(
            parts(P("Figure 5. Curves") + DRAW
                  + P("Figure 5. Curves again") + DRAW), "Figure 5.")


def test_a_caption_written_INSIDE_A_TABLE_is_not_the_caption_paragraph():
    """Some papers put the caption in a one-cell table above the
    exhibit, so the string "Table 3." is inside a `w:tbl` as well. The
    caption is a PARAGRAPH; reading the table as one makes the block
    start at the wrong element and swallow the caption's own table."""
    boxed = ("<w:tbl><w:tr><w:tc>" + P("Table 3. Distribution")
             + "</w:tc></w:tr></w:tbl>")
    block = placement.exhibit_block(
        parts(P("Prose.") + boxed + P("Table 3. Distribution")
              + TBL("a") + P("Prose after.")),
        "Table 3.")

    assert [e.tag.split("}")[1] for e in block.elements] == ["p", "tbl"]
    assert block.elements[1].findall(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr")


def test_exhibit_block_steps_over_the_BLANKS_under_a_caption():
    """Word leaves them behind constantly — a spacer someone typed, an
    empty paragraph left by a deletion. The exhibit is still the
    caption's, and the blanks travel with it."""
    block = placement.exhibit_block(
        parts(P("Prose.") + P("Table 3. Distribution") + P("") + P("")
              + TBL("a") + P("Prose after.")),
        "Table 3.")

    assert [e.tag.split("}")[1] for e in block.elements] == [
        "p", "p", "p", "tbl"]


def test_a_blank_paragraph_before_a_FIGURE_is_stepped_over_too():
    """The drawing clause and the table clause are one rule."""
    block = placement.exhibit_block(
        parts(P("Prose.") + P("Figure 5. Curves") + P("") + DRAW),
        "Figure 5.")

    assert len(block.elements) == 3, [e.tag for e in block.elements]


def test_a_block_never_absorbs_the_NEXT_exhibits_image():
    """An image is a paragraph with no text, and both walks here read
    "no text" as "a spacer": the table's block took the next figure's
    picture with its notes, and `place` then moved it. Aging_Well's Box 1
    and Figure 1, found by the code review of repack's copy of the walk.
    """
    doc = parts(P("См. таблицу 1.") + P("Прочая проза.")
                + P("Таблица 1. Заголовок") + TBL("шапка")
                + P("Примечание. Что-то.") + DRAW + P("Figure 1. Cap")
                + P("After."))

    out, _ = placement.place(dict(doc))
    block = placement.exhibit_block(doc, "Таблица 1.")

    assert order(out) == ["p:См. таблицу 1.", "p:Таблица 1. Заголовок",
                          "tbl:шапка", "p:Примечание. Что-то.",
                          "p:Прочая проза.", "p:", "p:Figure 1. Cap",
                          "p:After."]
    assert [e.tag.split("}")[1] for e in block.elements] == ["p", "tbl", "p"]


def test_exhibit_block_reads_a_figure_captioned_UNDER_its_image():
    """Aging_Well's and Parental_style's figures: image, hoisted
    bookmark, caption. The forward-only walk refused every one of them
    ("no table or image under it"), and each paper hand-rolled the span.
    """
    block = placement.exhibit_block(
        parts(P("Prose.") + DRAW + '<w:bookmarkStart w:id="1" w:name="F1"/>'
              + P("Figure 1. From resources") + P("") + P("After.")),
        "Figure 1.")

    assert [e.tag.split("}")[1] for e in block.elements] == [
        "p", "bookmarkStart", "p", "p"]
    assert block.caption == "Figure 1. From resources"


# `exhibit_block`'s remaining survivors from the 2026-08-21 round,
# argued rather than pinned:
#
# `el.tag == W + "p"` -> `<= W + "p"` in the caption walk. Body-level
# elements are `w:p`, `w:tbl`, `w:bookmarkStart`/`End` and `w:sectPr`,
# and of those only `p` sorts at or below "p" — a `w:tbl` sorts ABOVE
# it, and a bookmark carries no text for the caption test to find. The
# `is not` spelling of the same line is a different question and IS
# pinned, by the boxed-caption test above.
#
# `heads[0]` -> `heads[-1]`: reached only when exactly one paragraph
# opens with the caption, because two is refused three lines earlier.
#
# `if j >= len(kids)` -> `== len(kids)` and `while k < len(kids)` ->
# `!= len(kids)`: both indices are stepped by one from inside the
# bounds, so they meet the length exactly and never pass it.
#
# `_ends_section`'s `el.tag == W + "p"` -> `is not`: `W + "p"` builds a
# new string on every call, so the identity test is always True and the
# answer falls to the `pPr/sectPr` lookup — which no element other than
# a paragraph has as a direct child.


# --- tables with COLUMNS ------------------------------------------------
#
# `TBL` above builds one cell per row, and that is why the render path
# looked like it worked for so long: a single-column table has no cell
# boundary to lose. `_text` joins every `w:t` under an element with
# nothing between them, so a real row came out
# `'Social connectednessNussbaum Affiliation'` while the page reads
# `'Social connectedness Nussbaum Affiliation'` — the needle never
# matched, `last_sheet` stayed None, and None is not split, so no
# escalation, with `rendered` still True (Aging_Well, 2026-08-24).


def WIDE(*rows: tuple[str, ...]) -> str:
    """A table whose rows have more than one cell."""
    out = []
    for cells in rows:
        tcs = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>"
                      for c in cells)
        out.append(f"<w:tr>{tcs}</w:tr>")
    return f"<w:tbl>{''.join(out)}</w:tbl>"


def test_a_MULTI_COLUMN_table_that_splits_is_found_and_given_its_own_page():
    """The row text only matches the page when the cells are separated,
    which is what the fixtures above never asked for."""
    calls = []

    def render(_parts):
        calls.append(1)
        if len(calls) == 1:
            return ["See table 1. Table 1. Heading Capability Source",
                    "Social connectedness Affiliation 0.42"]
        return ["See table 1.",
                "Table 1. Heading Capability Source "
                "Social connectedness Affiliation 0.42"]

    out, rep = placement.place(
        parts(P("See table 1.") + P("Table 1. Heading")
              + WIDE(("Capability", "Source"),
                     ("Social connectedness", "Affiliation", "0.42"))),
        render=render)

    pl = rep.placements[0]
    assert pl.last_sheet is not None, "the last row was never located"
    assert pl.own_page, rep.format()
    assert not pl.unmeasured
    assert len(calls) == 2
    assert out is not None


def test_a_table_whose_END_is_not_on_any_sheet_says_so_instead_of_whole():
    """`split` has two states and a `None` `last_sheet` falls into the
    wrong one: not split, therefore whole, therefore nothing to fix —
    while `rendered` stays True, which is the report's own claim that
    the fit was measured. A check watching a proxy, and the proxy
    agreed."""
    def render(_parts):
        # the caption is on the page; the table's last row is not
        return ["See table 1. Table 1. Heading"]

    _out, rep = placement.place(
        parts(P("See table 1.") + P("Table 1. Heading")
              + WIDE(("Capability", "Source"), ("Nothing", "Rendered"))),
        render=render)

    pl = rep.placements[0]
    assert pl.unmeasured and not pl.split
    assert "END NOT FOUND" in rep.format(), rep.format()
    assert any("UNMEASURED" in p for p in rep.problems), rep.problems
    assert not pl.own_page, "nothing to escalate on a fit nobody measured"


def test_a_single_column_table_still_measures_as_it_did():
    """The shape that worked, and the reason the defect above hid: with
    one cell per row there is no separator to lose, so the old probe and
    the new one read the same string."""
    def render(_parts):
        return ["See table 1.", "Table 1. Heading head row"]

    _out, rep = placement.place(
        parts(P("See table 1.") + P("Table 1. Heading") + TBL("head", "row")),
        render=render)

    pl = rep.placements[0]
    assert pl.caption_sheet == 2 and pl.last_sheet == 2
    assert not pl.split and not pl.unmeasured


# --- the rule read BACK ------------------------------------------------
#
# `keep_together` writes cantSplit on every row, keepNext on every row
# but the last, and keepNext on the caption. Nothing audited for its
# ABSENCE: `refstyle` has `audit` beside its writers and the table rules
# had no equivalent, so the rule was enforceable only by remembering to
# run a writer. Aging_Well's Table 1 was hand-typed and dropped in
# whole, so no build ever styled it, and eight rounds of green gates
# went by while it straddled sheets 8 and 9.


def test_a_hand_typed_table_breaks_all_three_halves_of_the_rule():
    """The state a paper is really in when nobody has run a writer over
    it: no cantSplit anywhere, no keepNext binding the rows, and a
    caption that does not keep with its table."""
    report = placement.audit(parts(
        P("See table 1.") + P("Table 1. Heading")
        + WIDE(("Capability", "Source"), ("Health", "Nussbaum"))))

    kinds = sorted(f.kind for f in report.findings)
    assert kinds == ["caption unbound", "row may split", "row unbound"]
    assert not report.ok
    assert not report.rendered


def test_the_auditor_agrees_with_the_WRITER_it_reads_back():
    """The round trip is the point. An audit that disagreed with
    `place` would be a second opinion about the house rule, and the
    module would then have two."""
    raw = parts(P("See table 1.") + P("Table 1. Heading")
                + WIDE(("Capability", "Source"), ("Health", "Nussbaum")))

    styled, _ = placement.place(dict(raw))

    assert placement.audit(styled).ok, placement.audit(styled).format()


def test_a_property_switched_OFF_is_not_a_property_kept():
    """`<w:cantSplit w:val="false"/>` is the rule being declined, and
    reading a present element as a kept rule is how an audit comes back
    green over a document that says the opposite."""
    off = ('<w:tbl><w:tr><w:trPr><w:cantSplit w:val="false"/></w:trPr>'
           "<w:tc><w:p><w:r><w:t>a</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")

    report = placement.audit(parts(P("See table 1.")
                                   + P("Table 1. Heading") + off))

    assert any(f.kind == "row may split" for f in report.findings), \
        report.format()


def test_with_a_RENDERER_it_reports_what_actually_straddles():
    """The markup question is the one that PREVENTS a split. This is the
    one that catches a table too tall to fit at all, which no property
    can save."""
    def render(_parts):
        return ["See table 1. Table 1. Heading Capability Source",
                "Health Nussbaum"]

    report = placement.audit(
        parts(P("See table 1.") + P("Table 1. Heading")
              + WIDE(("Capability", "Source"), ("Health", "Nussbaum"))),
        render=render)

    assert report.rendered
    (straddle,) = [f for f in report.findings if f.kind == "straddles"]
    assert "sheet 1" in straddle.detail and "sheet 2" in straddle.detail


def test_a_table_the_render_cannot_LOCATE_is_said_so_not_passed():
    """The same third state `place` needed: a caption found and an end
    not found is unmeasured, and silence about it is a gate reporting
    that it checked."""
    def render(_parts):
        return ["See table 1. Table 1. Heading"]

    report = placement.audit(
        parts(P("See table 1.") + P("Table 1. Heading")
              + WIDE(("Capability", "Source"), ("Health", "Nussbaum"))),
        render=render)

    assert any(f.kind == "end not found" for f in report.findings), \
        report.format()


def rendered(report):
    """The findings only a render can make."""
    return [f for f in report.findings
            if f.kind in ("straddles", "end not found")]


#: HCW's shape: two tables opening on the SAME header row
HEAD = ("Country", "Year", "Rate")
QUOTED = "Table 2. Trends in mortality rates"
QUOTING = parts(P(f"As {QUOTED} shows, rates fell.")
                + P("Table 1. Levels") + WIDE(HEAD, ("Serbia", "2017", "0.03"))
                + P(QUOTED) + WIDE(HEAD, ("Sweden", "2017", "0.02")))


def test_a_caption_QUOTED_in_earlier_prose_is_not_where_its_table_starts():
    """HCW, measured on a render: the prose on sheet 13 quotes the full
    captions of Tables 6 and 7, and the first sheet carrying a caption's
    text was taken as its table's. Both tables sat whole on their own
    sheets and read "starts on sheet 13 and ends on sheet 29" — exit 2
    from `fit --render --check`, and `place` giving each a page break.
    Both tables here open on one header row, as five of HCW's do, so the
    row alone cannot say which table it is."""
    def render(_parts):
        return [f"As {QUOTED} shows, rates fell.",
                "Table 1. Levels Country Year Rate Serbia 2017 0.03",
                "prose", "prose",
                f"{QUOTED} Country Year Rate Sweden 2017 0.02"]

    assert rendered(placement.audit(QUOTING, render=render)) == []

    _out, rep = placement.place(QUOTING, render=render, move=False)
    table2 = next(p for p in rep.placements if p.number == 2)
    assert (table2.caption_sheet, table2.last_sheet) == (5, 5)
    assert not table2.own_page, "a whole table must not be given a page"


def test_a_QUOTED_caption_does_not_hide_the_straddle_of_the_real_one():
    """The other half, so the fix cannot pass by reporting less:
    LE_trends' real straddles have to survive it."""
    def render(_parts):
        return [f"As {QUOTED} shows, rates fell.",
                "Table 1. Levels Country Year Rate Serbia 2017 0.03",
                "prose",
                f"{QUOTED} Country Year Rate",
                "Sweden 2017 0.02"]

    (straddle,) = rendered(placement.audit(QUOTING, render=render))
    assert straddle.number == 2
    assert straddle.detail == "it starts on sheet 4 and ends on sheet 5"


def test_a_row_Word_WRAPPED_inside_its_cell_is_found_on_its_sheet():
    """LE_trends, measured: Table 1 ends on a narrow cell holding
    `Japan 1966-2000 (34y)`, and the page text reads `Japan 1966-` then
    `2000 (34y)`. Collapsing whitespace kept that break as a space the
    markup does not have; the table sat whole on sheet 4 and was reported
    UNMEASURED."""
    doc = parts(P("Table 1. Duration")
                + WIDE(("Start", "N", "Longest"),
                       ("70-75", "8", "Japan 1966-2000 (34y)")))

    def render(_parts):
        return ["prose", "prose", "prose",
                "Table 1. Duration\nStart \nN \nLongest \n70-75 \n8 \n"
                "Japan 1966-\n2000 (34y) \n"]

    assert rendered(placement.audit(doc, render=render)) == []


def test_a_BLANK_last_row_is_not_an_end_the_render_cannot_find():
    """A probe of nothing is found on no sheet, so a whole table whose
    last row is empty was reported UNMEASURED: exit 2 on a healthy
    document."""
    doc = parts(P("Table 1. Heading")
                + WIDE(("Capability", "Source"), ("Health", "Nussbaum"),
                       ("", "")))

    def render(_parts):
        return ["prose", "prose",
                "Table 1. Heading Capability Source Health Nussbaum"]

    assert rendered(placement.audit(doc, render=render)) == []


def test_a_caption_set_with_a_TAB_is_found_and_its_straddle_reported():
    """`w:t` carries no tab, so the caption reads `Table 1.Heading` in the
    markup and `Table 1. Heading` on the page, and was found on no sheet:
    no finding at all for a table that straddles."""
    doc = parts("<w:p><w:r><w:t>Table 1.</w:t><w:tab/><w:t>Heading</w:t>"
                "</w:r></w:p>"
                + WIDE(("Capability", "Source"), ("Health", "Nussbaum")))

    def render(_parts):
        return ["prose", "Table 1. Heading Capability Source",
                "Health Nussbaum"]

    (straddle,) = rendered(placement.audit(doc, render=render))
    assert straddle.detail == "it starts on sheet 2 and ends on sheet 3"


# --- the whole sweep of 2026-09-15 ------------------------------------
#
# 210 real survivors against dcbb6f7, most of them in `_locate`. The
# argued ones are in the claims file beside the round, not here.


def test_a_report_says_NOTHING_was_kept_together_when_fit_is_off():
    """`Placement.kept_together` defaults to False because only the
    branch that binds a block sets it — the shape `spaced` has, pinned
    above. Defaulted the other way, a run called with `fit=False`
    reports "1 kept together" over a table no property was written to,
    and a paper reads that as the fit having been handled."""
    out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок")
              + TBL("шапка")), fit=False)

    assert rep.placements[0].kept_together is False
    assert rep.format().splitlines()[0] == (
        "1 table(s): 0 moved, 0 kept together, 1 spaced, "
        "0 given their own page")
    assert tbl_of(body_of(out)).find(NS + "tr/" + NS + "trPr") is None


def test_the_FIT_REPORT_prints_its_head_and_every_finding_WHOLE():
    """`FitReport.format` had no test: every call to it in this file sat
    in an assertion MESSAGE, which is evaluated only when the assertion
    fails. So `[head] + findings` could be any operator — each of the
    eleven others raises TypeError on two lists — and the "markup only"
    tail could hang off the wrong condition, and nothing noticed. The
    unrendered report is what `fit --check` prints for a hand-typed
    table; a styled table measured whole has nothing to add to its head.
    """
    raw = parts(P("See table 1.") + P("Table 1. Heading")
                + WIDE(("Capability", "Source"), ("Health", "Nussbaum")))

    assert placement.audit(raw).format() == "\n".join([
        "1 table(s): 3 fit finding(s) — markup only; pass a renderer to "
        "see what STRADDLES",
        "  ! table 1 (Table 1. Heading): its caption does not keep with "
        "the table, so Word may leave the caption behind on the sheet "
        "above",
        "  ! table 1 (Table 1. Heading): 2 of 2 row(s) carry no "
        "cantSplit — a tall one will break ACROSS a page, mid-row",
        "  ! table 1 (Table 1. Heading): 1 row(s) do not keep with the "
        "row after — the table may break BETWEEN rows"])

    styled, _ = placement.place(dict(raw))
    whole = placement.audit(styled, render=lambda _p: [
        "See table 1.",
        "Table 1. Heading Capability Source Health Nussbaum"])
    assert whole.format() == "1 table(s): 0 fit finding(s)"


def test_an_EMPTY_fit_report_counts_no_tables():
    """`tables: int = 0`. `audit` always passes the count, so the default
    is what a caller gets who builds a report to fill in — the audits of
    several documents added up, say — and an empty report that says
    "1 table(s)" or "-1 table(s)" is a gate that miscounts."""
    report = placement.FitReport()

    assert report.ok
    assert report.format() == (
        "0 table(s): 0 fit finding(s) — markup only; pass a renderer to "
        "see what STRADDLES")


def test_a_BLOCK_and_a_FIT_FINDING_are_FROZEN():
    """Both are answers read after the tree they describe has moved on:
    a Block says what moving a span WOULD cost, and a finding is what a
    gate reported. Unfrozen, a caller that "fixes" a finding by editing
    it turns the report green without touching the document — and a
    finding stops being hashable, so two audits cannot be compared as
    sets."""
    import dataclasses

    doc = parts(P("Prose.") + P("Table 3. Counts") + TBL("a"))
    block = placement.exhibit_block(doc, "Table 3.")
    finding = placement.audit(doc).findings[0]

    for value in (block, finding):
        first = dataclasses.fields(value)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, first, None)
    assert hash(finding) == hash(dataclasses.replace(finding))


def test_the_probe_is_the_SAME_forty_characters_repack_reads_with():
    """`_PROBE` sets how much of a caption, a row and a mention is looked
    for on a sheet, and `repack` finds the same exhibits on the same
    renders with a probe of its own. The tests beside `repack` and
    `pages` hold theirs equal to this one; held from this side as well,
    a probe changed here alone is caught by this module's own harness
    rather than by a suite that does not measure it."""
    from docxkit import repack

    assert placement._PROBE == repack._PROBE


def test_the_default_drift_limit_is_ONE_sheet():
    """`max_drift: int = 1` — the limit a paper gets without naming one.
    Every render test above passes it explicitly, so the default could
    be two, and a table two sheets past its mention would read as
    placed."""
    def render(_parts):
        return ["См. таблицу 1.", "x", "Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render)

    assert rep.placements[0].drift == 2
    assert rep.problems == [
        "table 1: 2 sheets after its mention (limit 1) — place it by hand"]


def test_a_table_that_did_not_split_is_rendered_ONCE():
    """`fixed = False`: the second render is bought only by a page break
    this pass wrote. A render is Word laying out the whole document —
    minutes on a real paper — and started True, every call pays for two,
    the second measuring a document nothing changed."""
    calls: list[int] = []

    def render(_parts):
        calls.append(1)
        return ["См. таблицу 1. Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render)

    assert len(calls) == 1
    assert rep.placements[0].own_page is False


def test_a_whole_table_on_sheet_THREE_HUNDRED_neither_splits_nor_straddles():
    """`last_sheet != caption_sheet` in `split`, and `last != first` in
    the audit. Read as `is not`, each compares two sheet numbers computed
    apart — and CPython shares int objects only up to 256, so every
    table past sheet 256 reads as split: `place` gives it a page break
    and reports "still splits across sheets 300-300", and the audit calls
    a table that starts and ends on one sheet a straddle. A thesis with
    its appendix is that long."""
    sheets = (["См. таблицу 1."] + ["проза"] * 298
              + ["Таблица 1. Заголовок шапка строка"])
    doc = parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок")
                + TBL("шапка", "строка"))

    _out, rep = placement.place(doc, render=lambda _p: sheets,
                                max_drift=1000)

    pl = rep.placements[0]
    assert (pl.caption_sheet, pl.last_sheet) == (300, 300)
    assert pl.split is False and pl.own_page is False
    assert rep.problems == [], rep.problems
    assert rendered(placement.audit(doc, render=lambda _p: sheets)) == []


def test_a_measurement_that_ENDS_BEFORE_it_begins_is_not_a_whole_table():
    """`split` is "the end is not on the caption's sheet", and an end
    read on an EARLIER sheet is a measurement gone wrong — the row
    matched in prose above the table, which the search from the caption
    exists to prevent. Read as `>`, that answer comes back "whole" and
    nothing escalates; as inequality it is a split, which is what the
    test of the search from the caption has always called it."""
    pl = placement.Placement(number=1, caption="Таблица 1.",
                             caption_sheet=5, last_sheet=4)

    assert pl.split is True


def test_exhibit_block_steps_over_XML_COMMENTS_in_the_body():
    """lxml gives a comment its Comment FUNCTION as a tag. `==` answers
    False for it, and an ordering does not answer at all: `<=` raises
    TypeError. The caption search reads every child of the body, so a
    comment — which Word never writes and a converter does — stops the
    call dead. `exhibits` keeps a comment in front of a caption as a
    marker, which makes it the Block's FIRST element, and the
    section-break test reads that one too."""
    block = placement.exhibit_block(
        parts("<!-- generated -->" + P("Prose.") + "<!-- figure -->"
              + P("Figure 5. Curves") + DRAW + P("Source: mine.")),
        "Figure 5.")

    assert block.caption == "Figure 5. Curves"
    assert [("comment" if isinstance(e, etree._Comment) else e.tag)
            for e in block.elements] == ["comment", NS + "p", NS + "p",
                                         NS + "p"]
    assert not block.ends_a_section and not block.shares_a_page
    assert block.last_in_body


def test_the_block_IN_FRONT_is_the_element_just_above_the_caption():
    """`kids[head - 1]`. Read as `kids[head >> 1]` it is the element
    halfway up the body, which is the one just above only while the
    caption sits at index one or two — where the tests above have it. At
    index three the readings part: one sees the section break directly
    in front, the other a paragraph further up, and each fixture here is
    wrong under one of them."""
    after_break = placement.exhibit_block(
        parts(P("Prose.") + P("More prose.") + LANDSCAPE
              + P("Figure 5. Curves") + DRAW), "Figure 5.")
    after_prose = placement.exhibit_block(
        parts(P("Prose.") + LANDSCAPE + P("More prose.")
              + P("Figure 5. Curves") + DRAW), "Figure 5.")

    assert after_break.shares_a_page
    assert not after_prose.shares_a_page


def test_exhibit_block_finds_a_caption_past_child_THREE_HUNDRED():
    """`x.caption_at == i`: two indices counted apart, `exhibit_block`'s
    own and `exhibits`', equal only by value. Read as `is`, they are one
    object up to 256 and two after it, so every caption past the 256th
    body child has "no table or image beside it" — the back half of any
    real paper."""
    prose = "".join(P(f"Prose {i}.") for i in range(300))

    block = placement.exhibit_block(
        parts(prose + P("Figure 5. Curves") + DRAW + P("After.")),
        "Figure 5.")

    assert block.caption == "Figure 5. Curves"
    assert len(block.elements) == 2


def test_the_LAST_block_is_judged_by_its_LAST_element_not_its_second():
    """`content[-1] is block[-1]`. A caption and its image are two
    elements, and there `block[1]` IS `block[-1]` — the shape of the test
    above. A figure with its source line under it is three, and read as
    `block[1]` the block that ends the body says it does not, so nobody
    promotes its geometry and the move leaves a blank last page."""
    block = placement.exhibit_block(
        parts(P("Prose.") + P("Figure 5. Curves") + DRAW
              + P("Source: World Bank.")), "Figure 5.")

    assert len(block.elements) == 3
    assert block.last_in_body


def test_exhibit_block_never_answers_with_ANOTHER_captions_span():
    """`x.caption_at == i`, read as `>=`, takes the first exhibit captioned
    at or AFTER the paragraph asked about. The two agree wherever
    `exhibits` reads that paragraph as a caption too, and part company
    where it does not: a line break inside the number, "Table 1-" and
    "A." — `_text` drops the break and sees a caption, `text_of` keeps it
    and sees prose. The answer for Table 1-A may then be a refusal, but
    it is never Table 2's span, which a caller would move."""
    doc = parts(P("Prose.")
                + "<w:p><w:r><w:t>Table 1-</w:t><w:br/>"
                "<w:t>A. Counts</w:t></w:r></w:p>" + TBL("a")
                + P("More prose.") + P("Table 2. Other") + TBL("b"))

    try:
        block = placement.exhibit_block(doc, "Table 1-A.")
    except placement.PackageError as exc:
        assert "Table 1-A." in str(exc)
    else:
        assert block.caption.startswith("Table 1-"), block.caption


def test_a_table_of_PICTURES_under_a_caption_is_still_its_table():
    """The step over blanks under a caption asks `kids[j].tag == W + "p"`
    and whether the element has no text. A table whose cells hold only
    pictures has no text either: read as `is not` (true of every tag) the
    walk steps over the TABLE as though it were a blank paragraph, lands
    on the note, finds no table, and the caption is not a block at all."""
    pictures = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:drawing/></w:r></w:p>"
                "</w:tc></w:tr></w:tbl>")

    out, rep = placement.place(parts(
        P("Как показано в таблице 1, всё сходится.")
        + P("Совершенно другой абзац.")
        + P("Таблица 1. Карта") + pictures
        + P("Примечание. Картинки в ячейках.")))

    assert [p.moved for p in rep.placements] == [True]
    assert order(out) == [
        "p:Как показано в таблице 1, вс", "p:Таблица 1. Карта", "tbl:",
        "p:Примечание. Картинки в ячейк", "p:Совершенно другой абзац."]


#: the last child of every body Word writes: the final section's geometry
BODY_SECT = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
COMMENT = "<!-- written by a converter -->"


@pytest.mark.parametrize("note", ["", P("Примечание. Что-то.")],
                         ids=["no note", "a note"])
def test_the_BODY_sectPr_after_the_last_table_is_left_alone(note):
    """A table at the end of the body has the body's `w:sectPr` as the
    next element, and three tag tests stand between it and a write.

    The note walk reads `kids[k].tag == W + "p"`: as `>=`, a sectPr sorts
    above "p", carries no text, and is absorbed into the block — which
    then "carries a section break" and is refused. The two gap branches
    read `following.tag == W + "p"`: as `>=` or `is not`, the sectPr is
    handed a `w:pPr` with spacing in it, which CT_SectPr has no place
    for. One branch runs under a note and the other without one, which
    is why there are two cases."""
    out, rep = placement.place(parts(
        P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")
        + note + BODY_SECT))

    assert rep.problems == [], rep.problems
    sect = body_of(out)[-1]
    assert sect.tag == NS + "sectPr"
    assert [etree.QName(c).localname for c in sect] == ["pgSz"]


def test_the_table_under_a_BOX_does_not_travel_as_its_body():
    """`if el.tag != W + "p": continue`, ahead of the caption match. A box
    is a TABLE whose first cell reads like a caption, and `exhibits`
    makes it an exhibit of its own rather than the caption of what comes
    next. Read as `is` (False for every tag, the right-hand side being a
    fresh string) or as `<` (False for `w:tbl`), the box's text is
    matched as a caption, the table under it becomes its body, and the
    data table is moved to the box's mention and given row properties
    nobody asked for."""
    box = WIDE(("Таблица 2. Памятка", "Проверьте источники."))

    out, _rep = placement.place(parts(
        P("См. таблицу 2.") + P("Разделитель.") + box + P("")
        + TBL("данные")))

    seq = order(out)
    assert seq[-1] == "tbl:данные"
    assert seq.index("p:Разделитель.") < len(seq) - 1
    data = body_of(out).findall(NS + "tbl")[-1]
    assert data.find(NS + "tr/" + NS + "trPr") is None


def test_an_XML_COMMENT_anywhere_in_the_body_is_stepped_over_by_place():
    """lxml gives a comment its Comment FUNCTION as a tag: `==` answers
    False, an ordering raises TypeError, and `_ppr` cannot give a
    comment a child. Nearly every `el.tag == W + "p"` in this module
    reads a comment somewhere — the caption walk, the step over blanks
    under a caption, the note walk, the anchor search, the section
    count, and the paragraph after a block that the gap goes on.

    So one comment in front of everything, one under a note-less table,
    one under a caption with no table, and one under a note."""
    out, rep = placement.place(parts(
        COMMENT
        + P("Как показано в таблице 1, всё сходится.")
        + P("Таблица 1. Первая") + TBL("шапка", "строка")
        + COMMENT
        + P("Следующий абзац.")
        + P("Таблица 9. Подпись без таблицы")
        + COMMENT
        + P("См. таблицу 2.")
        + P("Таблица 2. Вторая") + TBL("b")
        + P("Примечание. Что-то.")
        + COMMENT))

    assert [(p.number, p.moved) for p in rep.placements] == [
        (1, False), (2, False)]
    assert rep.problems == [], rep.problems
    assert spacing_of(out, "Примечание.")["after"] == "160"
    assert sum(isinstance(el, etree._Comment) for el in body_of(out)) == 4
    assert placement.audit(out).ok


def test_the_block_writers_step_over_an_XML_COMMENT_in_the_block():
    """`keep_together`, `space_block` and `own_page` are public and take
    any list of elements — the tests here build theirs as `list(body)`.
    Each asks `el.tag == W + "p"` or `== W + "tbl"` of every element; a
    comment answers False, where an ordering raises TypeError and an
    identity sends the comment on to `_ppr`. So a comment first, one
    between the caption and the table, and one last."""
    body = body_of(parts(COMMENT + P("Таблица 1. Заголовок") + COMMENT
                         + TBL("шапка", "строка")
                         + P("Примечание. Что-то.") + COMMENT))
    block = list(body)

    placement.keep_together(block)
    placement.space_block(block, None)
    placement.own_page(block)

    caption, tbl, note = (el for el in block
                          if not isinstance(el, etree._Comment))
    assert [etree.QName(c).localname for c in caption[0]] == [
        "keepNext", "pageBreakBefore", "spacing"]
    assert note.find(NS + "pPr/" + NS + "keepNext") is None
    rows = tbl.findall(NS + "tr")
    assert [[etree.QName(c).localname for c in row[0]] for row in rows] == [
        ["tblHeader"], []]
    assert sum(isinstance(el, etree._Comment) for el in body) == 3


def test_a_HOISTED_bookmark_is_never_taken_for_the_caption_paragraph():
    """Word hoists a table's bookmarkStart to body level in front of the
    caption, and the block takes it along, so the block's FIRST element
    is not a paragraph. Five places look for "the first paragraph" with
    `el.tag == W + "p"`, and `w:bookmarkStart` sorts below "p": read as
    `<=` or as `is not`, each stops at the bookmark. The report's caption
    is then empty; keepNext, the caption's spacing and the page break
    are written INTO the bookmark, which CT_Bookmark has no room for;
    and the audit reads the bookmark's missing pPr as a caption that
    does not keep with its table.

    The first render straddles, so that `own_page` runs as well."""
    calls: list[int] = []

    def render(_parts):
        calls.append(1)
        if len(calls) == 1:
            return ["См. таблицу 1. Таблица 1. Заголовок шапка", "строка"]
        return ["См. таблицу 1.", "Таблица 1. Заголовок шапка строка"]

    out, rep = placement.place(parts(
        P("См. таблицу 1.") + '<w:bookmarkStart w:id="7" w:name="T1"/>'
        + P("Таблица 1. Заголовок") + TBL("шапка", "строка")
        + '<w:bookmarkEnd w:id="7"/>'), render=render)

    assert rep.placements[0].caption == "Таблица 1. Заголовок"
    start = body_of(out).find(NS + "bookmarkStart")
    assert start is not None and len(start) == 0
    assert [etree.QName(c).localname for c in ppr_of(out, "Таблица 1.")] \
        == ["keepNext", "pageBreakBefore", "spacing"]
    assert "caption unbound" not in [
        f.kind for f in placement.audit(out).findings]


def test_keep_together_frees_the_note_ABOVE_an_exhibit_blocks_end_marker():
    """`exhibit_block` hands back a span that can END with the bookmarkEnd
    paired with a start in front of the caption, and says its elements go
    straight to `keep_together`. The walk back from the end has to pass
    that marker and free the note. `w:bookmarkEnd` sorts below "p": read
    as `<=` or as `is not`, the walk stops at the marker, gives it an
    empty `w:pPr`, and leaves the note bound to whatever follows."""
    block = placement.exhibit_block(parts(
        P("Prose.") + '<w:bookmarkStart w:id="5" w:name="T3"/>'
        + P("Table 3. Counts") + TBL("a", "b") + P("Source: mine.")
        + '<w:bookmarkEnd w:id="5"/>' + P("Prose after.")), "Table 3.")
    start, caption, _tbl, note, end = block.elements

    placement.keep_together(block.elements)

    assert (len(start), len(end)) == (0, 0)
    assert caption.find(NS + "pPr/" + NS + "keepNext") is not None
    assert note.find(NS + "pPr/" + NS + "keepNext") is None


def test_only_the_LAST_note_is_freed_the_notes_above_it_stay_bound():
    """The walk back from the end clears keepNext on the first paragraph
    it meets and STOPS. `continue` in place of the `break` clears every
    note back to the table, so a note and the gloss under it can be
    parted by a page — and DSI's таблица 4 has exactly those two."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Примечание. Ориентация.") + P("* Высокая доля.")
        + P("Следующий абзац.")))

    def keeps(starts: str) -> bool:
        return ppr_of(out, starts).find(NS + "keepNext") is not None

    assert (keeps("Таблица 1."), keeps("Примечание."),
            keeps("* Высокая")) == (True, True, False)


@pytest.mark.parametrize("n", [2, 300])
def test_the_LAST_row_is_freed_in_a_table_of_EVEN_or_huge_length(n):
    """`last = n == len(rows) - 1`, and two readings the three-row test
    above cannot see. `len(rows) ^ 1` is `len(rows) - 1` only when the
    length is ODD: at two rows it is three, and no row is last. `is`
    holds only while the index is a cached int, so row 300 of an
    appendix table is never the last. Either way the last row keeps with
    the paragraph after the table.

    The first keep-together test looks for `w:p` as a CHILD of the row,
    where a cell always stands between, which is why it never said so."""
    out, _ = placement.place(parts(
        P("См. таблицу 1.") + P("Таблица 1. Заголовок")
        + TBL(*(f"строка {i}" for i in range(n)))))

    rows = tbl_of(body_of(out)).findall(NS + "tr")
    keeps = [row.find(f"{NS}tc/{NS}p/{NS}pPr/{NS}keepNext") is not None
             for row in rows]
    assert keeps == [True] * (n - 1) + [False]


def test_a_move_from_the_MIDDLE_section_into_the_LAST_one_is_refused():
    """`_section_of` answers the first section whose end is AT or after
    the index. Read as `index > end` it answers the first whose end is
    BEFORE it — zero for everything past the first break — so a table in
    the middle section and its mention in the last read as one section,
    and the move crosses a boundary. The fixtures above have a single
    break, where the two readings merely swap and still agree that the
    sections differ."""
    out, rep = placement.place(parts(
        P("Конец первого раздела.", SECT("portrait"))
        + P("Таблица 1. Заголовок") + TBL("шапка")
        + P("Конец второго раздела.", SECT("landscape"))
        + P("См. таблицу 1 в последнем разделе.")))

    assert rep.placements[0].moved is False
    assert any("another section" in x for x in rep.problems), rep.problems
    assert order(out)[1:3] == ["p:Таблица 1. Заголовок", "tbl:шапка"]


def test_a_table_after_THREE_HUNDRED_section_breaks_still_moves():
    """`here != there`: two section numbers from two calls, equal by
    value. Read as `is not`, they are one object only below 257, and past
    that every move is refused as crossing a section boundary it does
    not cross."""
    breaks = "".join(P(f"Раздел {i}.", SECT("portrait")) for i in range(300))

    out, rep = placement.place(parts(
        breaks + P("См. таблицу 1.") + P("Разделитель.")
        + P("Таблица 1. Заголовок") + TBL("шапка")))

    assert rep.problems == [], rep.problems
    assert rep.placements[0].moved is True
    assert order(out)[301] == "p:Таблица 1. Заголовок"


def test_the_anchor_is_a_mention_of_THIS_number_however_large():
    """`int(m.group(1)) == number`. Read as `>=`, a mention of a LATER
    table is taken for this one: «см. таблицу 2» above «см. таблицу 1»
    anchors table 1 under the wrong sentence. Read as `is`, the number
    parsed from the mention and the one parsed from the caption are one
    object only up to 256, and table 300 is mentioned by nothing in the
    paper that mentions it."""
    out, rep = placement.place(parts(
        P("См. таблицу 2.") + P("См. таблицу 1.") + P("Разделитель.")
        + P("Таблица 1. Заголовок") + TBL("шапка")))
    assert rep.placements[0].anchor_text == "См. таблицу 1."
    assert order(out)[2] == "p:Таблица 1. Заголовок"

    _out, rep = placement.place(parts(
        P("См. таблицу 300.") + P("Разделитель.")
        + P("Таблица 300. Заголовок") + TBL("шапка")))
    assert rep.placements[0].moved is True
    assert rep.placements[0].anchor_text == "См. таблицу 300."


def test_own_page_puts_a_NEW_trPr_first_in_a_row_of_TWO_cells():
    """`rows[0].insert(0, trpr)`. The own-page tests above build one cell
    per row, where `insert(-1)` — before the last child — is the same
    position. A header row out of a paper has several cells, and a
    `w:trPr` after the first of them is unreadable content that `find`
    cannot see."""
    body = body_of(parts(P("Таблица 1. Заголовок")
                         + WIDE(("Страна", "Год"), ("Сербия", "2017"))))

    placement.own_page(list(body))

    tr = tbl_of(body).find(NS + "tr")
    assert tr is not None
    assert [etree.QName(c).localname for c in tr] == ["trPr", "tc", "tc"]


def test_own_page_goes_on_PAST_a_table_with_no_rows():
    """`if not rows: continue`. `own_page` takes whatever list it is
    given, and a list can hold two tables; an empty one in front must not
    stop the next one's header being marked. `break` there leaves every
    table after the empty one without a header that repeats."""
    body = body_of(parts(P("Таблица 1. Заголовок") + "<w:tbl/>"
                         + TBL("шапка", "строка")))

    placement.own_page(list(body))

    rows = body.findall(NS + "tbl")[1].findall(NS + "tr")
    assert rows[0].find(NS + "trPr/" + NS + "tblHeader") is not None


def test_the_audit_reads_EVERY_row_but_the_last_not_just_the_first():
    """`rows[:-1]`: every row but the last must bind to the next. Read as
    `rows[:1]` only the first is asked, which agrees on the two-row
    tables above; a three-row table unbound in the MIDDLE — a row pasted
    in by hand after the writer ran — then audits clean."""
    styled, _ = placement.place(parts(
        P("See table 1.") + P("Table 1. Heading")
        + WIDE(("Country", "Rate"), ("Serbia", "0.03"), ("Sweden", "0.02"))))
    root = etree.fromstring(styled["word/document.xml"])
    middle = root.findall(f"{NS}body/{NS}tbl/{NS}tr")[1]
    for kn in list(middle.iter(NS + "keepNext")):
        parent = kn.getparent()
        assert parent is not None
        parent.remove(kn)

    report = placement.audit({"word/document.xml": etree.tostring(root)})

    assert [(f.kind, f.detail) for f in report.findings] == [(
        "row unbound",
        "1 row(s) do not keep with the row after — the table may break "
        "BETWEEN rows")]


def test_the_MENTION_is_found_on_the_sheet_that_carries_it():
    """`_sheet_of` answers the first sheet holding the needle, counted
    from one. `needle or ...` answers the first sheet searched whatever
    the needle, and `i ^ 1` and `i | 1` agree with `i + 1` only on the
    first sheet — which is where every earlier test put its mention. On
    the second, drift is reported from a sheet the mention is not on."""
    def render(_parts):
        return ["Проза.", "См. таблицу 1. Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("Проза.") + P("См. таблицу 1.") + P("Таблица 1. Заголовок")
              + TBL("шапка")), render=render)

    pl = rep.placements[0]
    assert (pl.mention_sheet, pl.caption_sheet, pl.drift) == (2, 2, 0)


def test_tables_are_measured_in_the_order_the_MOVES_left_them():
    """`_locate_tables` walks the tables by their CURRENT position, and
    each search starts where the table before it ended. A sort key that
    is always 0 keeps the order the captions had BEFORE the moves —
    table 2 first, here — and table 1, now in front of it, is looked for
    after table 2's last row and is never found."""
    def render(_parts):
        return ["См. таблицу 1. Таблица 1. Первая a",
                "Проза. См. таблицу 2. Таблица 2. Вторая b"]

    _out, rep = placement.place(parts(
        P("См. таблицу 1.") + P("Проза.") + P("См. таблицу 2.")
        + P("Таблица 2. Вторая") + TBL("b")
        + P("Таблица 1. Первая") + TBL("a")), render=render)

    assert [(p.number, p.moved, p.caption_sheet, p.last_sheet)
            for p in rep.placements] == [(1, True, 1, 1), (2, False, 2, 2)]


def located(body: str, sheets: list[str],
            ) -> list[tuple[int, int | None, int | None]]:
    """Each table's (number, caption sheet, last sheet) as `place`
    measures them on `sheets`, moving nothing.

    `place` rather than `audit` because the audit says nothing about a
    table it could not find at all — and a search that loses its cursor
    loses the NEXT table, silently."""
    _out, rep = placement.place(parts(body), render=lambda _p: sheets,
                                move=False)
    return [(p.number, p.caption_sheet, p.last_sheet)
            for p in rep.placements]


LEVELS = P("Table 1. Levels") + WIDE(HEAD, ("Serbia", "2017", "0.03"))
TRENDS = P("Table 2. Trends") + WIDE(HEAD, ("Sweden", "2017", "0.02"))
#: longer than the forty-character probe, so a tail stands between the
#: probe and the header row
LONG = "Table 1. Levels of mortality in the sample by country"
PICTURES = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:drawing/></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>")


@pytest.mark.parametrize(("body", "sheets", "want"), [
    # the quote comes first; every search that does not measure the
    # distance to the rows takes it
    pytest.param(LEVELS, [
        "As Table 1. Levels shows, rates fell.", "prose",
        "Table 1. Levels Country Year Rate Serbia 2017 0.03"],
        [(1, 3, 3)], id="quoted before"),
    # the quote is followed by the LAST row's values: measured to the
    # last row instead of the first, the quote is the nearer one
    pytest.param(LEVELS, [
        "As Table 1. Levels shows, Serbia 2017 0.03 is the lowest.",
        "Table 1. Levels Country Year Rate Serbia 2017 0.03"],
        [(1, 2, 2)], id="quoted with its last row"),
    # the header row is not on the page (set hidden), so the distance is
    # taken to the last row — and without that fallback every occurrence
    # is equally far and the first, the quote, wins
    pytest.param(LEVELS, [
        "As Table 1. Levels shows, rates fell.", "prose",
        "Table 1. Levels Serbia 2017 0.03"],
        [(1, 3, 3)], id="header not on the page"),
    # quoted AFTER the table, just above a table with the same header row,
    # and once more at the end with nothing under it
    pytest.param(LEVELS + TRENDS, [
        "Prose that runs on for a good while before any table at all.",
        "Table 1. Levels Country Year Rate Serbia 2017 0.03",
        "As Table 1. Levels showed,",
        "Table 2. Trends Country Year Rate Sweden 2017 0.02",
        "Table 1. Levels again, in the conclusion."],
        [(1, 2, 2), (2, 4, 4)], id="quoted after"),
    # the gap as a RATIO to the offset: the quote is further from a row
    # than the caption is from its own header, but far down the text
    pytest.param(P(LONG) + WIDE(HEAD, ("Serbia", "2017", "0.03")) + TRENDS, [
        "Mortality is measured in two ways.",
        LONG + " Country Year Rate Serbia 2017 0.03",
        "The second table repeats the layout of " + LONG + ".",
        "Table 2. Trends Country Year Rate Sweden 2017 0.02"],
        [(1, 2, 2), (2, 4, 4)], id="a ratio takes the quote"),
    # the gap as a floor division, an `|` or an `^` of the two offsets:
    # thirty-four characters in front of the quote are where all three
    # rank the quote above the caption
    pytest.param(P(LONG) + WIDE(HEAD, ("Serbia", "2017", "0.03")), [
        "Death rates fell at every age; again, see Table 1. Levels of "
        "mortality in the sample, in all women and men.",
        LONG + " Country Year Rate Serbia 2017 0.03"],
        [(1, 2, 2)], id="a floor or a bit mix takes the quote"),
])
def test_the_caption_is_the_occurrence_its_ROWS_follow_most_closely(
        body, sheets, want):
    """`_locate` takes, of every place a caption's text appears, the one
    whose table rows come soonest after it: `gap = body - after`, kept
    while strictly smaller. Only the HCW fixture above had two
    occurrences in reach of one search, and there the cursor had already
    passed the quote — so the choice itself was never made by a test.

    Every other reading of that arithmetic — the distance to the last row
    instead of the first, a sum, a product, a ratio, a remainder, a bit
    mix, a comparison that keeps the later of two or the larger — ranks
    the occurrences by something that is not distance, and for some
    spacing of the page picks the quote. Each layout here is a spacing
    where some of them do; the sheet numbers are the table's own."""
    assert located(body, sheets) == want


@pytest.mark.parametrize(("body", "sheets", "want"), [
    # a table of pictures: no row has text, so there is no end to find
    pytest.param(P("Table 1. Map") + PICTURES + TRENDS, [
        "prose", "Table 1. Map",
        "Table 2. Trends Country Year Rate Sweden 2017 0.02",
        "As Table 1. Map showed."],
        [(1, 2, None), (2, 3, 3)], id="no text rows"),
    # rows with text, and the render carries none of them
    pytest.param(P("Table 1. Map") + WIDE(("Region", "Share"), ("North", "7"))
                 + TRENDS, [
        "prose", "Table 1. Map",
        "Table 2. Trends Country Year Rate Sweden 2017 0.02"],
        [(1, 2, None), (2, 3, 3)], id="rows not on the page"),
])
def test_a_table_whose_END_is_UNMEASURED_does_not_lose_the_next(
        body, sheets, want):
    """A table whose end is found on no sheet answers (caption sheet,
    None), and the next table's search starts just past its caption. The
    readings that break it do so quietly: a probe of nothing "found" at
    offset 0 or 1 reports a last sheet for a table with no text; a
    start of -1, or the caption's offset multiplied by its length, puts
    the cursor past everything, and table 2 — whole on sheet 3 — is not
    found at all; a tie between two equally unmeasurable occurrences
    that goes to the LATER one does the same. None of that reaches
    `audit`, which is silent about a table it cannot locate."""
    assert located(body, sheets) == want


@pytest.mark.parametrize(("body", "sheets", "want"), [
    # the caption runs past the probe and its tail says "Total", which is
    # also the last row: searched from the caption's probe instead of the
    # header, the end is found inside the caption and the straddle is lost
    pytest.param(P("Table 1. Mortality by country and year, with the Total")
                 + WIDE(("Country", "Rate"), ("Serbia", "0.03"),
                        ("Total", "")), [
        "prose",
        "Table 1. Mortality by country and year, with the Total Country "
        "Rate Serbia 0.03", "Total"],
        [(1, 2, 3)], id="the caption's tail holds the last row"),
    # no row on the page, and "Total" in the caption itself: any start
    # before the probe's end — a remainder, a difference, a floor, a bit
    # mix of the caption's offset (29) and its length (12) — finds the
    # end INSIDE the caption and calls an unmeasured table measured
    pytest.param(P("Table 1. Total") + WIDE(("Region", "Share"),
                                            ("Total", "")), [
        "Every share is shown by its region.", "Table 1. Total"],
        [(1, 2, None)], id="Total in the caption, no rows rendered"),
])
def test_the_last_row_is_looked_for_from_the_table_BODY_onward(
        body, sheets, want):
    """`start = body if body >= 0 else at + len(caption)`: the end search
    starts at the table's first row, or — when no row was found — just
    past the caption's probe, and never inside the caption. A caption is
    a sentence and a last row is often one word; "Total" is both."""
    assert located(body, sheets) == want


@pytest.mark.parametrize(("body", "sheets", "want"), [
    # the last row's final character is the last of sheet 2, at flat
    # offset 49; the next sheet starts at 50, an EVEN number, where
    # `stop ^ 1` is 51 and reads the table as ending on sheet 3
    pytest.param(P("Table 1. Heading")
                 + WIDE(("Capability", "Source"), ("Health", "Nussbaum")), [
        "prose.", "Table 1. Heading Capability Source Health Nussbaum",
        "Next sheet."],
        [(1, 2, 2)], id="the table ends a sheet"),
    # a last row of one figure, alone at the top of sheet 3, at flat offset
    # 35: `stop - 2` and `end | 1` both land on the character before it,
    # on sheet 2, and the straddle is lost
    pytest.param(P("Table 1. Ranks")
                 + WIDE(("Country", "Rank"), ("Serbia", "1"), ("", "2")), [
        "prose", "Table 1. Ranks Country Rank Serbia 1", "2"],
        [(1, 2, 3)], id="one figure on the next sheet"),
])
def test_the_last_sheet_is_the_one_holding_the_rows_LAST_character(
        body, sheets, want):
    """`_sheet_at(starts, stop - 1)` where `stop = end + len(last)`: the
    sheet of the last character of the last row. Every render test
    above ends its table somewhere in the middle of a sheet, where one
    character either way is the same sheet. At a sheet boundary it is
    the difference between a whole table and a straddle."""
    assert located(body, sheets) == want


def test_a_caption_at_the_very_TOP_of_the_first_sheet_is_found():
    """`while at >= 0` and `cursor = 0`. Offset 0 of the flowed text is
    a real place for a caption: a document that opens with its table, or
    a render that starts at the table's sheet. Read as `at > 0`, or with
    the first search starting at 1, that caption is on no sheet, and the
    straddle it makes is not reported.

    Last in the file, deliberately: three readings of `at + len(caption)`
    multiply by a zero offset and search the same place forever. The
    tests above kill those first, and `-x` stops there."""
    doc = parts(P("Table 1. Heading")
                + WIDE(("Capability", "Source"), ("Health", "Nussbaum")))

    def render(_parts):
        return ["Table 1. Heading Capability Source", "Health Nussbaum"]

    (straddle,) = rendered(placement.audit(doc, render=render))
    assert straddle.detail == "it starts on sheet 1 and ends on sheet 2"
