"""Exhibit links can be Word FIELD form, which link/unlink cannot see.

Parental_style holds 53 element-form and 160 field-form links at once.
`unlink` reported "24 bookmarks removed" there and left every caption
link live — a wrong answer wearing a healthy number.
"""

import re

import pytest
from conftest import make_parts, para, run

from docxkit import crossrefs
from docxkit.errors import ConversionGap


def field_link(anchor: str, shown: str) -> str:
    """A complete HYPERLINK field, as Word writes it."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">'
        f' HYPERLINK \\l "{anchor}" \\h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r><w:t>{shown}</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def doc(body: str) -> str:
    return make_parts(body)["word/document.xml"].decode("utf-8")


CAPTION_AND_MENTION = (
    para(run("As reported in ")) .replace("</w:p>", "") + field_link(
        "Table1", "Table 1") + "<w:r><w:t>, rates differ.</w:t></w:r></w:p>"
    + para(run("Table 1: Descriptive statistics.")))


def test_field_targets_finds_what_the_element_scan_misses():
    xml = doc(CAPTION_AND_MENTION)
    assert crossrefs.field_targets(xml) == {"Table1"}
    # and the element-form scan sees nothing at all
    assert 'w:anchor="Table1"' not in xml


def test_unlink_refuses_rather_than_reporting_a_healthy_count():
    xml = doc(CAPTION_AND_MENTION)
    with pytest.raises(ConversionGap) as exc:
        crossrefs.unlink(xml)
    assert "FIELD form" in str(exc.value)
    assert "Table1" in str(exc.value)


def test_unlink_still_works_on_an_ordinary_element_document():
    body = (para(run("See "))
            + para(run("Table 1: Descriptive statistics.")))
    xml = doc(body)
    linked, _ = crossrefs.link(xml)
    out, removed = crossrefs.unlink(linked)
    assert removed >= 0
    assert "FIELD" not in out


def test_link_reports_a_field_linked_object_instead_of_doubling_it():
    xml = doc(CAPTION_AND_MENTION)
    out, report = crossrefs.link(xml)
    assert report.field_form == ["Table1"]
    assert "Table1" not in report.linked
    # nothing added on top of the field
    assert out.count('w:anchor="Table1"') == 0
    assert "ALREADY LINKED BY A WORD FIELD" in report.format()


def test_a_field_linked_exhibit_does_not_stop_the_ones_after_it():
    """`continue`, not `break`. A field-linked object is reported and
    stepped over; under `break` it ends the linking run instead, and
    every exhibit after it in the document goes unlinked while the
    report says only that ONE was field form.

    That is the shape Parental_style is: 160 field-form links among 53
    element-form ones, the field ones scattered through the paper. The
    first of them would have ended the run at Table 1."""
    xml = doc(CAPTION_AND_MENTION
              + para(run("As reported in Table 2, rates differ."))
              + para(run("Table 2: Descriptive statistics.")))

    out, report = crossrefs.link(xml)

    assert report.field_form == ["Table1"]
    assert report.linked == ["Table2"], report.format()
    assert 'w:anchor="Table2"' in out and 'w:anchor="Table1"' not in out


# --- what the crossrefs sweeps of 2026-08-18 left in `unlink` -----------
#
# 13 survivors, and five of them on the ellipsis that says the refusal's
# list is not the whole list. The message is the whole of what a paper
# gets: `unlink` raises rather than removing bookmarks and leaving field
# links live, so the names in it are what a person goes and retargets.


def _exhibits(n: int, *, field: bool) -> str:
    """`n` exhibits, each mentioned once — as a field link or plainly."""
    out = ""
    for i in range(1, n + 1):
        mention = (field_link(f"Table{i}", f"Table {i}") if field
                   else run(f"Table {i}"))
        out += (para(run("As reported in ")).replace("</w:p>", "")
                + mention + "<w:r><w:t>, rates differ.</w:t></w:r></w:p>"
                + para(run(f"Table {i}: Descriptive statistics.")))
    return out


def test_the_refusal_names_SIX_and_says_there_are_more():
    """Six is what fits in a message a person reads; the ellipsis is what
    stops the seventh from being invisible. Without it a paper retargets
    the six it was told about, re-runs, and gets the same refusal."""
    xml = doc(_exhibits(7, field=True))

    with pytest.raises(ConversionGap) as exc:
        crossrefs.unlink(xml)

    message = str(exc.value)
    assert "7 exhibit link(s) are Word FIELD form" in message
    listed = message.split("remove: ", 1)[1].split(" ...", 1)[0]
    assert len(listed.split(", ")) == 6, listed
    assert " ..." in message, "and there are more than it listed"


def test_the_refusal_does_NOT_trail_off_when_it_named_them_all():
    """Six exactly: the list IS the whole list, and an ellipsis there
    sends a reader looking for a seventh that does not exist."""
    xml = doc(_exhibits(6, field=True))

    with pytest.raises(ConversionGap) as exc:
        crossrefs.unlink(xml)

    message = str(exc.value)
    assert "6 exhibit link(s) are Word FIELD form" in message
    assert " ..." not in message


def test_a_bookmark_that_is_already_gone_does_not_stop_the_removal():
    """`continue`, not `break`. The names come from the CAPTIONS, so a
    scheme half-removed by hand — or one where the mention was never
    bookmarked — leaves gaps in the middle of the list. Under `break`
    every bookmark after the first gap survives, and `unlink` reports the
    count it managed as if it were the whole job."""
    linked, _ = crossrefs.link(doc(_exhibits(3, field=False)))
    # take Table1's own bookmark out by hand, leaving the rest
    gapped = re.sub(r'<w:bookmarkStart[^>]*w:name="Table1"\s*/>', "",
                    linked, count=1)

    out, removed = crossrefs.unlink(gapped)

    assert removed == 5, "six names, one already gone"
    assert "w:bookmarkStart" not in out
    assert "w:anchor=" not in out, "and every hyperlink unwrapped"

def test_the_refusal_does_not_trail_off_below_six_either():
    """`len(fielded) > 6`, and the two fixtures either side of six
    cannot tell it from `!=`. Three field links is the ordinary case —
    a paper mid-conversion, where Word rewrote a handful of element
    links into fields — and `!= 6` prints an ellipsis after a list that
    is complete, which sends a person looking for links that are not
    there."""
    xml = doc(_exhibits(3, field=True))

    with pytest.raises(ConversionGap) as exc:
        crossrefs.unlink(xml)

    message = str(exc.value)
    assert "3 exhibit link(s) are Word FIELD form" in message
    assert " ..." not in message, message
    for i in (1, 2, 3):
        assert f"Table{i}" in message


def ref_field(anchor: str, shown: str) -> str:
    r"""Word's OWN cross-reference: what Insert > Cross-reference writes.

    The third form that reaches a bookmark. `field_targets` knew two,
    so `unlink` on a document using this one reported a healthy count,
    removed the exhibit bookmarks and left every REF field live and
    dangling — the exact answer the ConversionGap guard exists to
    refuse, arriving through the door the guard does not watch.
    """
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">'
        rf' REF {anchor} \h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r><w:t>{shown}</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


REF_CAPTION_AND_MENTION = (
    para(run("As reported in ")).replace("</w:p>", "") + ref_field(
        "Table1", "Table 1") + "<w:r><w:t>, rates differ.</w:t></w:r></w:p>"
    + para(run("Table 1: Descriptive statistics.")))


def test_field_targets_reads_words_own_cross_reference_too():
    xml = doc(REF_CAPTION_AND_MENTION)
    assert crossrefs.field_targets(xml) == {"Table1"}


def test_unlink_refuses_a_ref_field_as_it_refuses_a_hyperlink_one():
    xml = doc(REF_CAPTION_AND_MENTION)
    with pytest.raises(ConversionGap) as exc:
        crossrefs.unlink(xml)
    assert "FIELD form" in str(exc.value)
    assert "Table1" in str(exc.value)


def test_a_switchless_ref_is_still_a_dependency_unlink_must_see():
    # not clickable, so not a link — but removing the bookmark still
    # breaks it into "Error! Reference source not found"
    xml = doc(REF_CAPTION_AND_MENTION.replace(r"\h ", r"\* MERGEFORMAT "))
    assert crossrefs.field_targets(xml) == {"Table1"}
    with pytest.raises(ConversionGap):
        crossrefs.unlink(xml)
