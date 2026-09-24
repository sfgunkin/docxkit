"""`pages.number` — every page but the first, written by what is there.

Two ways a footer writer has cost these papers something. AFI's replaced
the footers wholesale, which on Aging_Well would take the first-page
footer's sensitivity label with it. And the rule it served was written
down as "every sectPr carries titlePg", which blanks the first sheet of
EVERY section — Aging_Well's landscape pages printed no number.
"""
from __future__ import annotations

import re

import pytest
from conftest import make_parts, para, run

from docxkit import pages
from docxkit._xml import DOCUMENT
from docxkit.errors import PackageError
from docxkit.lint import lint_parts

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELS = "word/_rels/document.xml.rels"
PAGE = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r>'
        '<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def sect(*refs: str, title: bool = False) -> str:
    return (f'<w:sectPr xmlns:r="{R_NS}">{"".join(refs)}'
            '<w:pgSz w:w="12240" w:h="15840"/><w:cols w:space="720"/>'
            + ("<w:titlePg/>" if title else "")
            + '<w:docGrid w:linePitch="360"/></w:sectPr>')


def ref(kind: str, rid: str) -> str:
    return f'<w:footerReference w:type="{kind}" r:id="{rid}"/>'


def footer_part(body: str) -> bytes:
    return (f'<w:ftr xmlns:w="{W_NS}">{body}</w:ftr>').encode()


def package(body: str, footers: dict[str, str] | None = None
            ) -> dict[str, bytes]:
    parts = make_parts(body)
    rels = "".join(
        f'<Relationship Id="{rid}" Type="{R_NS}/footer" Target="{name}"/>'
        for rid, name in {"rId8": "footer1.xml", "rId9": "footer2.xml",
                          "rId10": "footer3.xml"}.items())
    parts[RELS] = f"<Relationships>{rels}</Relationships>".encode()
    for name, xml in (footers or {}).items():
        parts[f"word/{name}"] = footer_part(xml)
    return parts


def sections(parts: dict[str, bytes]) -> list[str]:
    return re.findall(r"<w:sectPr\b.*?</w:sectPr>",
                      parts[DOCUMENT].decode(), re.DOTALL)


def test_a_document_with_NO_footer_gets_one_and_page_one_stays_blank():
    parts = make_parts(para(run("Title.")) + sect())

    got = pages.number(parts)

    assert got.created == ("word/footer1.xml",)
    footer = parts["word/footer1.xml"].decode()
    assert "PAGE" in footer and '<w:jc w:val="right"/>' in footer
    (only,) = sections(parts)
    rid = re.search(r'w:type="default" r:id="(rId\d+)"', only)
    assert rid and f'Id="{rid.group(1)}"' in parts[RELS].decode()
    assert "<w:titlePg/>" in only
    assert 'PartName="/word/footer1.xml"' in \
        parts["[Content_Types].xml"].decode()
    assert lint_parts(parts) == []


def test_an_existing_footer_is_EXTENDED_and_keeps_what_it_holds():
    """The Aging_Well case: a label in the footer that must survive."""
    label = para(run("Official Use Only"))
    parts = package(para(run("Body.")) + sect(ref("default", "rId8")),
                    {"footer1.xml": label})

    got = pages.number(parts)

    assert got.extended == ("word/footer1.xml",) and not got.created
    footer = parts["word/footer1.xml"].decode()
    assert "Official Use Only" in footer and "PAGE" in footer
    assert footer.index("Official Use Only") < footer.index("PAGE")


@pytest.mark.parametrize("numbered", [
    f"<w:p>{PAGE}</w:p>",
    '<w:p><w:fldSimple w:instr=" PAGE \\* MERGEFORMAT ">'
    "<w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>",
    '<w:p><w:fldSimple w:instr="PAGE"/></w:p>',
])
def test_a_footer_that_already_numbers_is_left_BYTE_for_byte(numbered):
    parts = package(para(run("Body.")) + sect(ref("default", "rId8")),
                    {"footer1.xml": numbered})
    before = parts["word/footer1.xml"]

    got = pages.number(parts)

    assert got.already == ("word/footer1.xml",)
    assert parts["word/footer1.xml"] == before


@pytest.mark.parametrize("instr",
                         ["NUMPAGES", "PAGEREF _Ref1", "SECTIONPAGES"])
def test_a_field_that_is_NOT_the_page_number_does_not_count(instr):
    field = PAGE.replace(" PAGE ", f" {instr} ")
    parts = package(para(run("Body.")) + sect(ref("default", "rId8")),
                    {"footer1.xml": f"<w:p>{field}</w:p>"})

    assert pages.number(parts).extended == ("word/footer1.xml",)


def test_titlePg_on_the_FIRST_section_only_unless_a_first_footer_numbers():
    """Three sections, each with titlePg. The first keeps it; the second
    loses it (its first sheet would print nothing); the third keeps it,
    because its own first-page footer prints the number."""
    body = (para(run("One."))
            + f"<w:p><w:pPr>{sect(ref('default', 'rId8'), title=True)}"
              "</w:pPr></w:p>"
            + para(run("Two."))
            + f"<w:p><w:pPr>{sect(title=True)}</w:pPr></w:p>"
            + para(run("Three."))
            + sect(ref("first", "rId10"), title=True))
    parts = package(body, {"footer1.xml": "<w:p/>",
                           "footer3.xml": f"<w:p>{PAGE}</w:p>"})

    got = pages.number(parts)

    first, second, third = sections(parts)
    assert got.title_pages_cleared == 1
    assert "<w:titlePg/>" in first
    assert "titlePg" not in second
    assert "<w:titlePg/>" in third


def test_titlePg_goes_in_at_its_SCHEMA_slot_replacing_a_switched_off_one():
    parts = make_parts(para(run("Body."))
                       + sect().replace("<w:docGrid",
                                        '<w:titlePg w:val="0"/><w:docGrid'))

    pages.number(parts)

    (only,) = sections(parts)
    assert only.count("titlePg") == 1
    assert '<w:cols w:space="720"/><w:titlePg/><w:docGrid' in only


def test_numbering_TWICE_changes_nothing_the_second_time():
    parts = make_parts(para(run("Title.")) + sect())
    pages.number(parts)
    once = dict(parts)

    again = pages.number(parts)

    assert parts == once
    assert again.already == ("word/footer1.xml",) and not again.created


def test_the_Footer_STYLE_is_used_when_the_document_has_one_and_align_obeyed():
    parts = make_parts(para(run("Body.")) + sect())
    parts["word/styles.xml"] = (b'<w:styles><w:style w:type="paragraph" '
                                b'w:styleId="Footer"/></w:styles>')

    pages.number(parts, align="center")

    footer = parts["word/footer1.xml"].decode()
    assert '<w:pStyle w:val="Footer"/><w:jc w:val="center"/>' in footer


def test_separate_EVEN_page_footers_are_refused():
    parts = make_parts(para(run("Body.")) + sect())
    parts["word/settings.xml"] = (b"<w:settings><w:evenAndOddHeaders/>"
                                  b"</w:settings>")

    with pytest.raises(PackageError, match="every other sheet"):
        pages.number(parts)


def test_a_switched_OFF_even_odd_setting_is_no_obstacle():
    parts = make_parts(para(run("Body.")) + sect())
    parts["word/settings.xml"] = (b'<w:settings><w:evenAndOddHeaders '
                                  b'w:val="0"/></w:settings>')

    assert pages.number(parts).created


def test_an_alignment_that_is_not_one_is_refused():
    with pytest.raises(ValueError, match="align"):
        pages.number(make_parts(para(run("x")) + sect()), align="middle")
