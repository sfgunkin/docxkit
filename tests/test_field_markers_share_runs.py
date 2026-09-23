"""A field's markers can share their runs with prose — read the MARKERS.

`field_spans` answers with run boundaries, and Word writes a field's
`begin` into the run that already holds the words before it as often as
not, and its `end` into the run carrying the words after. Three readers
wanted the field and got the runs (backlog S3, 2026-09-18):

* D2 `wrap_link_in_bookmark` put `<key>txt` round the whole sentence;
* D3 `respan_link` refused a repair it could make;
* `edit._label_spans_in` counted the prose as the field's label, so
  `replace_in_para` and `replace_keeping_links` refused to edit it.

All three now cut at the markers through `_xml.isolate_field`.
"""
from __future__ import annotations

import re

import pytest

from docxkit import edit
from docxkit._cite_repair import respan_link, wrap_link_in_bookmark
from docxkit._xml import RUN_RE, fields, isolate_field, visible_text
from docxkit.edit import _label_spans_in
from docxkit.errors import AnchorError

BEGIN = '<w:fldChar w:fldCharType="begin"/>'
SEP = '<w:fldChar w:fldCharType="separate"/>'
END = '<w:fldChar w:fldCharType="end"/>'
ITALIC = "<w:rPr><w:i/></w:rPr>"


def _field(anchor: str = "Smith2020", label: str = "(Smith 2020)", *,
           head: str = "As ", tail: str = " found, the index rose.",
           rpr: str = "") -> str:
    """A field link whose markers share their runs with prose."""
    return (f'<w:r>{rpr}<w:t xml:space="preserve">{head}</w:t>{BEGIN}</w:r>'
            f'<w:r><w:instrText> HYPERLINK \\l "{anchor}" </w:instrText>'
            f"</w:r><w:r>{SEP}</w:r><w:r><w:t>{label}</w:t></w:r>"
            f'<w:r>{rpr}{END}<w:t xml:space="preserve">{tail}</w:t></w:r>')


SHARED = "<w:p>" + _field() + "</w:p>"
TEXT = "As (Smith 2020) found, the index rose."


def _bookmarked(out: str) -> str:
    return visible_text(out[out.index("<w:bookmarkStart"):
                            out.index("<w:bookmarkEnd")])


def _inside_a_run(xml: str, pos: int) -> bool:
    return any(m.start() < pos < m.end() for m in RUN_RE.finditer(xml))


# ------------------------------------------------------------ the reading


def test_isolate_splits_each_shared_run_at_its_marker():
    (f,) = fields(SHARED)

    out, s, e = isolate_field(SHARED, f)

    assert visible_text(out) == TEXT             # nothing on the page moves
    assert visible_text(out[s:e]) == "(Smith 2020)"
    assert out[s:e].count(BEGIN) == out[s:e].count(END) == 1
    assert out[s:e].startswith("<w:r>") and out[s:e].endswith("</w:r>")


def test_both_halves_of_a_split_run_keep_its_properties():
    para = "<w:p>" + _field(rpr=ITALIC) + "</w:p>"
    (f,) = fields(para)

    out, s, e = isolate_field(para, f)

    # the prose halves outside, the marker halves inside: all still italic
    assert out[:s].count(ITALIC) == 1 and out[e:].count(ITALIC) == 1
    assert out[s:e].count(ITALIC) == 2


@pytest.mark.parametrize(("head", "tail", "runs_added"), [
    ("", "", 0), ("As ", "", 1), ("", " found.", 1), ("As ", " found.", 2)])
def test_only_a_run_that_SHARES_is_split(head, tail, runs_added):
    """A marker alone in its run (with or without the run's properties)
    leaves that run as it is: the ordinary field comes back unchanged."""
    para = "<w:p>" + _field(head=head, tail=tail, rpr=ITALIC) + "</w:p>"
    para = para.replace('<w:t xml:space="preserve"></w:t>', "")
    (f,) = fields(para)

    out, s, e = isolate_field(para, f)

    assert out.count("<w:r>") == para.count("<w:r>") + runs_added
    assert visible_text(out[s:e]) == "(Smith 2020)"
    if not runs_added:
        assert out == para


def test_a_field_with_no_end_marker_is_refused():
    cut = SHARED.replace(END, "")
    (f,) = fields(cut)

    with pytest.raises(ValueError, match="no end marker"):
        isolate_field(cut, f)


# --------------------------------------------------------- D2, the bookmark


def test_the_txt_bookmark_wraps_the_FIELD_not_the_sentence():
    out = wrap_link_in_bookmark(SHARED, "Smith2020", "Smith2020txt", 9)

    assert _bookmarked(out) == "(Smith 2020)"
    assert visible_text(out) == TEXT
    for tag in ("<w:bookmarkStart", "<w:bookmarkEnd"):
        assert not _inside_a_run(out, out.index(tag)), tag


def test_the_bookmark_on_an_ORDINARY_field_is_where_it_always_was():
    para = ("<w:p><w:r><w:t xml:space=\"preserve\">As </w:t></w:r>"
            + f"<w:r>{BEGIN}</w:r>"
            + '<w:r><w:instrText> HYPERLINK \\l "Smith2020" </w:instrText>'
            + f"</w:r><w:r>{SEP}</w:r><w:r><w:t>(Smith 2020)</w:t></w:r>"
            + f"<w:r>{END}</w:r><w:r><w:t> found.</w:t></w:r></w:p>")

    out = wrap_link_in_bookmark(para, "Smith2020", "Smith2020txt", 9)

    s = para.index(f"<w:r>{BEGIN}")
    e = para.index(f"<w:r>{END}</w:r>") + len(f"<w:r>{END}</w:r>")
    assert out == (para[:s] + '<w:bookmarkStart w:id="9" '
                   'w:name="Smith2020txt"/>' + para[s:e]
                   + '<w:bookmarkEnd w:id="9"/>' + para[e:])


# ---------------------------------------------------------- D3, the respan


def test_respan_REPAIRS_a_field_whose_markers_share_runs():
    out = respan_link(SHARED, "Smith2020", "Smith 2020")

    assert visible_text(out) == TEXT
    link = re.search(r'<w:hyperlink w:anchor="Smith2020">(.*?)</w:hyperlink>',
                     out, re.DOTALL)
    assert link is not None
    assert visible_text(link.group(1)) == "Smith 2020"


# ---------------------------------------------------------- the edit label


def test_the_LABEL_is_what_the_field_shows_and_no_more():
    runs, spans, _ = edit.run_spans(SHARED)

    labels = _label_spans_in(SHARED, runs, spans)

    assert [(lab.start, lab.end) for lab in labels] == [(3, 15)]


def test_prose_sharing_a_run_with_a_marker_can_be_edited():
    out = edit.replace_in_para(SHARED, "index", "level")

    assert visible_text(out) == "As (Smith 2020) found, the level rose."
    assert out.count(BEGIN) == out.count(END) == 1


def test_replace_keeping_links_edits_that_prose_too():
    out = edit.replace_keeping_links(SHARED, "index rose", "index fell")

    assert visible_text(out) == "As (Smith 2020) found, the index fell."


def test_the_field_s_OWN_words_are_still_refused():
    """The label shrank to the field; it did not go away."""
    with pytest.raises(AnchorError, match="result of a field"):
        edit.replace_in_para(SHARED, "Smith 2020", "Jones 2021")
