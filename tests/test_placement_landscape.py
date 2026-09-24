"""`placement.landscape` — one exhibit on a landscape page of its own.

The section around the exhibit is split into three, and the traps are all
about what each piece carries. Aging_Well found two of them by printing
the paper: a `titlePg` cloned into every piece blanked the page number
on each one's first sheet, and a page break left beside a `nextPage`
section break printed an empty page.
"""
from __future__ import annotations

import re

import pytest
from conftest import make_parts, para, run, table

from docxkit import placement
from docxkit._xml import DOCUMENT
from docxkit.errors import PackageError
from docxkit.lint import lint_parts

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

FOOTERS = ('<w:footerReference xmlns:r="urn:r" w:type="default" r:id="rId8"/>'
           '<w:footerReference xmlns:r="urn:r" w:type="first" r:id="rId9"/>')


def sect(*, extra: str = "", landscape: bool = False,
         restart: bool = True) -> str:
    size = ('<w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/>'
            if landscape else '<w:pgSz w:w="12240" w:h="15840"/>')
    start = ' w:start="1"' if restart else ""
    return (f"<w:sectPr>{FOOTERS}{size}"
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
            'w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
            f'<w:pgNumType{start}/><w:cols w:space="720"/>{extra}'
            "<w:titlePg/></w:sectPr>")


DRAWING = ('<w:p><w:r><w:drawing><wp:inline xmlns:wp="urn:wp">'
           '<wp:extent cx="5486400" '
           'cy="3657600"/><wp:docPr id="1" name="Picture 1"/>'
           "</wp:inline></w:drawing></w:r></w:p>")


def figure(*, first_ppr: str = "") -> str:
    caption = (f"<w:p>{first_ppr}{run('Figure 1. Wages by region')}</w:p>"
               if first_ppr else para(run("Figure 1. Wages by region")))
    return caption + DRAWING + para(run("Source: Survey data."))


def document(*middle: str, final: str | None = None) -> dict[str, bytes]:
    body = "".join(middle) + (final if final is not None else sect())
    return make_parts(body)


def sections(parts: dict[str, bytes]) -> list[str]:
    """Every sectPr, in order: paragraph-level ones, then the body's."""
    xml = parts[DOCUMENT].decode()
    return re.findall(r"<w:sectPr\b.*?</w:sectPr>", xml, re.DOTALL)


def paragraph_holding(parts: dict[str, bytes], words: str) -> str:
    xml = parts[DOCUMENT].decode()
    for m in re.finditer(r"<w:p\b(?:(?!<w:p\b).)*?</w:p>", xml, re.DOTALL):
        if words in m.group(0):
            return m.group(0)
    raise AssertionError(words)


BASIC = (para(run("Title page.")), para(run("Prose before it.")), figure(),
         para(run("Prose after it.")))


def test_three_sections_portrait_LANDSCAPE_portrait():
    parts = document(*BASIC)

    got = placement.landscape(parts, "Figure 1.")

    first, turned, rest = sections(parts)
    assert got.sections == 3
    assert 'w:orient="landscape"' in turned
    assert '<w:pgSz w:w="15840" w:h="12240"' in turned
    assert "orient" not in first and "orient" not in rest
    assert "<w:sectPr" in paragraph_holding(parts, "Prose before it")
    assert "<w:sectPr" in paragraph_holding(parts, "Source: Survey")
    assert lint_parts(parts) == []


def test_what_only_a_section_START_carries_stays_with_the_FIRST_piece():
    """Cloned into every piece, titlePg blanks the number on each one's
    first sheet and a pgNumType start restarts the count."""
    parts = document(*BASIC)

    placement.landscape(parts, "Figure 1.")

    first, turned, rest = sections(parts)
    assert "<w:titlePg/>" in first and 'w:start="1"' in first
    for piece in (turned, rest):
        assert "titlePg" not in piece and "w:start" not in piece
        assert "<w:pgNumType/>" in piece


def test_margins_columns_and_EVERY_footer_reference_are_cloned():
    parts = document(*BASIC)

    placement.landscape(parts, "Figure 1.")

    for piece in sections(parts):
        assert piece.count("<w:footerReference") == 2
        assert '<w:pgMar w:top="1440"' in piece and "<w:cols" in piece


def test_the_report_gives_the_LANDSCAPE_text_area():
    got = placement.landscape(document(*BASIC), "Figure 1.")

    assert (got.text_width_in, got.text_height_in) == (9.0, 6.5)


def test_a_PAGE_BREAK_beside_the_new_break_is_removed():
    breaker = ('<w:p><w:r><w:t>Prose before it.</w:t></w:r>'
               '<w:r><w:br w:type="page"/></w:r></w:p>')
    parts = document(para(run("Title page.")), breaker, figure(),
                     para(run("After.")))

    got = placement.landscape(parts, "Figure 1.")

    assert got.page_breaks_removed == 1
    assert 'w:type="page"' not in parts[DOCUMENT].decode()
    assert "Prose before it." in paragraph_holding(parts, "Prose before")


def test_pageBreakBefore_on_the_caption_is_removed_too():
    parts = document(para(run("Title page.")), para(run("Before.")),
                     figure(first_ppr="<w:pPr><w:pageBreakBefore/></w:pPr>"),
                     para(run("After.")))

    got = placement.landscape(parts, "Figure 1.")

    assert got.page_breaks_removed == 1
    assert "pageBreakBefore" not in parts[DOCUMENT].decode()


def test_a_TABLE_on_either_side_gets_a_paragraph_to_carry_the_break():
    """A table cannot hold a sectPr: one before the block, and the
    exhibit's own table as its last element, each need a carrier."""
    grid = table("<w:tr><w:tc>" + para(run("cell")) + "</w:tc></w:tr>")
    exhibit = para(run("Table 2. Long table")) + grid
    parts = document(para(run("Title.")), grid, exhibit,
                     para(run("After.")))

    got = placement.landscape(parts, "Table 2.")

    assert got.carriers_inserted == 2
    xml = parts[DOCUMENT].decode()
    assert xml.count("</w:tbl><w:p><w:pPr><w:sectPr>") == 2
    assert lint_parts(parts) == []


def test_the_section_CONTAINING_the_exhibit_is_cloned_not_the_last_one():
    """A later section break governs what comes before it."""
    middle = sect(extra='<w:vAlign w:val="center"/>', restart=False)
    parts = document(para(run("Title.")), para(run("Before.")), figure(),
                     f"<w:p><w:pPr>{middle}</w:pPr>{run('Ends part one.')}"
                     "</w:p>", para(run("Part two.")))

    placement.landscape(parts, "Figure 1.")

    first, turned, _closing, body_sect = sections(parts)
    assert "vAlign" in first and "vAlign" in turned
    assert "vAlign" not in body_sect


def test_an_exhibit_ALREADY_opening_a_section_makes_two_and_keeps_start():
    opener = f"<w:p><w:pPr>{sect()}</w:pPr>{run('End of part one.')}</w:p>"
    parts = document(para(run("Title.")), opener, figure(),
                     para(run("After.")))

    got = placement.landscape(parts, "Figure 1.")

    assert got.sections == 2
    _before, turned, rest = sections(parts)
    assert "<w:titlePg/>" in turned and "titlePg" not in rest


@pytest.mark.parametrize("build,match", [
    (lambda: document(para(run("Before.")), figure()[:-6]
                      + f"<w:pPr>{sect()}</w:pPr>" + "</w:p>",
                      para(run("After."))), "already ends a section"),
    (lambda: document(para(run("Before.")), figure(), para(run("After.")),
                      final=sect(landscape=True)), "already landscape"),
    (lambda: document(figure(), para(run("After."))), "opens the body"),
    (lambda: document(para(run("Figure 9 shows it."))), "no caption"),
])
def test_what_it_REFUSES(build, match):
    with pytest.raises(PackageError, match=match):
        placement.landscape(build(), "Figure")
