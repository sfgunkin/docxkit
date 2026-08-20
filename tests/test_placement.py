"""Where a table lands, and what it takes with it."""
from __future__ import annotations

import re

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
    """The second measurement, after the fix — `_sheet_of(..., start=
    pl.caption_sheet - 1)`. The start is the caption's own sheet, in
    0-based terms, and all three arithmetic readings of that expression
    put it somewhere else: `% 1` and `& 1` start at the top of the
    document, where a row's value quoted in the prose matches first,
    and `* 1` starts one sheet LATE, where the row on the caption's own
    sheet is no longer visible and the answer is None.

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
# NOT worked, and listed so the next round starts here: the four
# `[:40]` widths on the text handed to `_sheet_of`. Each is a match KEY
# against a rendered sheet, so pinning one means a render whose text
# differs from the block's beyond that character — which is what the
# caption test above does, and the other three want the same shape.
#
# (Three other entries were on this list and came off it the same
# afternoon: `pl.caption_sheet - 1`, `Placement.spaced`'s default, and
# `here != there`. A list of what is not done is worth keeping for that
# reason — it is the next round's starting point, and it shrinks.)
