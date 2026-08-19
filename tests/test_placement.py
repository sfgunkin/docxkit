"""Where a table lands, and what it takes with it."""
from __future__ import annotations

import re

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


def order(out: dict[str, bytes]) -> list[str]:
    """Каждый body child as 'p:<text>' or 'tbl:<first cell>', in order."""
    from lxml import etree
    NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = etree.fromstring(out["word/document.xml"]).find(NS + "body")
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
    from lxml import etree
    NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = etree.fromstring(out["word/document.xml"]).find(NS + "body")
    keeps = {}
    for el in body:
        if el.tag == NS + "p":
            text = "".join(t.text or "" for t in el.iter(NS + "t"))
            kn = el.find(NS + "pPr/" + NS + "keepNext")
            keeps[text[:12]] = kn is not None
    assert keeps["Таблица 1. З"] is True, "the caption must hold its table"
    assert keeps["Примечание. "] is False, "the note ends the block"
    rows = body.find(NS + "tbl").findall(NS + "tr")
    assert all(r.find(NS + "trPr/" + NS + "cantSplit") is not None
               for r in rows)
    last = rows[-1].find(NS + "p/" + NS + "pPr/" + NS + "keepNext")
    assert last is None, "the last ROW must not keep with what follows either"


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
    from lxml import etree
    NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = etree.fromstring(out["word/document.xml"]).find(NS + "body")
    caption = [e for e in body if e.tag == NS + "p"][1]
    assert caption.find(NS + "pPr/" + NS + "pageBreakBefore") is not None
    head = body.find(NS + "tbl").findall(NS + "tr")[0]
    assert head.find(NS + "trPr/" + NS + "tblHeader") is not None


def test_drift_beyond_the_limit_is_reported_rather_than_hidden():
    def render(_parts):
        return ["См. таблицу 1.", "x", "x", "Таблица 1. Заголовок шапка"]

    _out, rep = placement.place(
        parts(P("См. таблицу 1.") + P("Таблица 1. Заголовок") + TBL("шапка")),
        render=render, max_drift=1)
    assert rep.placements[0].drift == 3
    assert any("sheets after its mention" in x for x in rep.problems)


def test_only_and_skip_select_without_touching_the_rest():
    body = (P("В таблице 1 и таблице 2 всё есть.")
            + P("Разделитель.")
            + P("Таблица 1. Первая") + TBL("a")
            + P("Таблица 2. Вторая") + TBL("b"))
    out, _ = placement.place(parts(body), only=[2])
    seq = order(out)
    assert seq[1] == "p:Таблица 2. Вторая", "table 2 moved to the mention"
    assert "p:Разделитель." in seq and seq.index("p:Таблица 1. Первая") > 1


def test_a_caption_with_no_table_under_it_is_not_a_block():
    """«Таблица 1» opening a sentence in prose is not a caption to move."""
    out, rep = placement.place(parts(
        P("Таблица 1. Это просто предложение, а не подпись.")
        + P("Больше прозы.")))
    assert order(out) == ["p:Таблица 1. Это просто предло",
                          "p:Больше прозы."]
    assert rep.placements == []


def test_the_report_says_when_nothing_was_rendered():
    _out, rep = placement.place(parts(
        P("См. таблицу 1.") + P("Таблица 1. З") + TBL("a")))
    assert "not rendered" in rep.format()
    assert rep.placements[0].drift is None


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
    from lxml import etree
    NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = (P("Как показано в таблице 1.")
            + P("Разделитель.")
            + '<w:bookmarkStart w:id="7" w:name="Таблица1"/>'
            + P('Таблица 1. Заголовок<w:bookmarkEnd w:id="7"/>')
            + TBL("шапка"))
    out, _ = placement.place(parts(body))
    root = etree.fromstring(out["word/document.xml"]).find(NS + "body")
    seq = list(root.iter())
    start = next(i for i, e in enumerate(seq) if e.tag == NS + "bookmarkStart")
    end = next(i for i, e in enumerate(seq) if e.tag == NS + "bookmarkEnd")
    assert start < end, "the bookmark must still open before it closes"
    kids = list(root)
    assert kids[1].tag == NS + "bookmarkStart", (
        "the hoisted bookmark moved with its caption, not left behind")
    caption = "".join(t.text or "" for t in kids[2].iter(NS + "t"))
    assert "Таблица 1." in caption
