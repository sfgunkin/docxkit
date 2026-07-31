"""renumber.shift — exhibit numbers move everywhere or nowhere.

The traps pinned here: single-pass shifting (5,6 -> 6,7 without the
double-shift a sequential replace produces), digits hidden by run
fragmentation, inflected prose labels, and the range mentions that must
be REFUSED rather than half-shifted.
"""
from __future__ import annotations

import pytest
from conftest import NS, para, run

from docxkit.errors import AnchorError
from docxkit.renumber import shift
from docxkit.tables import read_all


def doc(body: str) -> str:
    return f"<w:document {NS}><w:body>{body}</w:body></w:document>"


def caption(n: int, label: str = "Table") -> str:
    return para(run(f"{label} {n}. Something about it"))


def text_of_doc(xml: str) -> str:
    import re

    from docxkit._xml import visible_text
    return " | ".join(visible_text(m.group(0)) for m in
                      re.finditer(r"<w:p\b.*?</w:p>", xml, re.DOTALL))


def test_captions_and_mentions_from_frm_shift_once():
    xml = doc(caption(5) + caption(6)
              + para(run("As Table 5 shows, and Table 6 confirms, "
                         "Table 4 stays.")))
    out, report = shift(xml, "Table", frm=5)
    text = text_of_doc(out)
    assert "Table 6. " in text and "Table 7. " in text
    assert "As Table 6 shows, and Table 7 confirms, Table 4 stays." in text
    assert report.mentions == 4
    assert not report.flagged


def test_a_fragmented_mention_still_shifts():
    # "Table 12" stored as three runs, the digits split across two
    body = ("<w:p><w:r><w:t>see Table </w:t></w:r>"
            "<w:r><w:t>1</w:t></w:r><w:r><w:t>2</w:t></w:r>"
            "<w:r><w:t> here</w:t></w:r></w:p>")
    out, report = shift(doc(body), "Table", frm=3)
    assert "see Table 13 here" in text_of_doc(out)
    assert report.mentions == 1


def test_ten_is_not_one():
    xml = doc(para(run("Table 1 and also Table 10.")))
    out, _ = shift(xml, "Table", frm=10)
    assert "Table 1 and also Table 11." in text_of_doc(out)


def test_inflected_russian_prose_keeps_its_case_ending():
    xml = doc(para(run("Таблица 4. Итоги"))
              + para(run("как показано в таблице 4 выше")))
    out, report = shift(xml, "Таблица", frm=4)
    text = text_of_doc(out)
    assert "Таблица 5. " in text
    assert "в таблице 5 выше" in text
    assert report.mentions == 2


def test_bookmarks_anchors_and_ref_fields_follow():
    body = (
        '<w:p><w:bookmarkStart w:id="1" w:name="Table5"/>'
        + run("Table 5. Cap") + '<w:bookmarkEnd w:id="1"/></w:p>'
        + '<w:p><w:bookmarkStart w:id="2" w:name="Table5txt"/>'
          '<w:hyperlink w:anchor="Table5">' + run("Table 5")
        + "</w:hyperlink>"
          '<w:bookmarkEnd w:id="2"/>'
          '<w:r><w:instrText xml:space="preserve"> REF Table5 \\h '
          "</w:instrText></w:r></w:p>")
    out, report = shift(doc(body), "Table", frm=5)
    assert 'w:name="Table6"' in out and 'w:name="Table6txt"' in out
    assert 'w:anchor="Table6"' in out
    assert " REF Table6 \\h " in out
    assert "Table5" not in out
    assert (report.bookmarks, report.anchors, report.fields) == (2, 1, 1)


def test_appendix_prefix_shifts_its_own_sequence_only():
    xml = doc(caption(2) + para(run("Table A2. Extra"))
              + para(run("see Table A2 and Table 2")))
    out, _ = shift(xml, "Table", frm=2, prefix="A")
    text = text_of_doc(out)
    assert "Table A3. Extra" in text
    assert "see Table A3 and Table 2" in text
    assert "Table 2. " in text                    # main sequence untouched


def test_ranges_are_flagged_not_half_shifted():
    xml = doc(para(run("Tables 5–7 report the results.")))
    out, report = shift(xml, "Table", frm=5)
    assert "Tables 5–7 report" in text_of_doc(out)     # untouched
    assert report.mentions == 0
    assert report.flagged and "5–7" in report.flagged[0]


def test_lists_are_flagged_not_half_shifted():
    xml = doc(para(run("Tables 5 and 6 agree.")))
    out, report = shift(xml, "Table", frm=5)
    text = text_of_doc(out)
    assert "Tables 5 and 6 agree." in text
    assert report.mentions == 0
    assert report.flagged


def test_negative_shift_closes_a_gap():
    xml = doc(caption(4) + caption(5) + para(run("see Table 4 and then "
                                                 "read Table 5")))
    out, _ = shift(xml, "Table", frm=4, by=-1)
    text = text_of_doc(out)
    assert "Table 3. " in text and "Table 4. " in text
    assert "see Table 3 and then read Table 4" in text


def test_a_shift_that_collides_captions_refuses():
    xml = doc(caption(3) + caption(4))
    with pytest.raises(AnchorError, match="collide"):
        shift(xml, "Table", frm=4, by=-1)


def test_by_zero_refuses():
    with pytest.raises(AnchorError, match="by=0"):
        shift(doc(caption(1)), "Table", frm=1, by=0)


def test_tables_content_is_untouched():
    tbl = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>5</w:t></w:r></w:p>"
           "</w:tc></w:tr></w:tbl>")
    xml = doc(caption(5) + tbl)
    out, _ = shift(xml, "Table", frm=5)
    assert read_all(out)[0].rows == [["5"]]       # a bare cell "5" is data
