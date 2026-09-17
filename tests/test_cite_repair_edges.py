"""`_cite_repair`'s edges: the survivors of the 2026-09-12 sweep.

The back-link marker and self-link repairs landed that day, and
`respan_link` had carried survivors since August. Each test here is aimed
at a mutant that lived: a naming branch no fixture used, a guard no test had
tripped, or a slice whose wrong answer still READ right, because every test
before it looked at visible text and none asked whether the XML parses.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

import docxkit._cite_grammar as grammar
import docxkit._cite_repair as repair
from docxkit._xml import internal_links, visible_text
from docxkit.citations import (
    bookmark,
    hyperlink_field,
    respan_link,
    retarget_self_link,
    rewrap_marker,
)
from docxkit.errors import AnchorError


def R(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def P(inner: str) -> str:
    return f"<w:p>{inner}</w:p>"


def _doc(*paras: str) -> str:
    return "<w:document><w:body>" + "".join(paras) + "</w:body></w:document>"


def _link(anchor: str, label: str) -> str:
    return (f'<w:hyperlink w:anchor="{anchor}"><w:r>'
            f'<w:t xml:space="preserve">{label}</w:t></w:r></w:hyperlink>')


def _inside(xml: str, name: str) -> str:
    """What a reader sees between bookmark `name`'s start and its end."""
    start = re.search(rf'<w:bookmarkStart w:id="(\d+)" w:name="{name}"/>',
                      xml)
    assert start is not None
    shut = xml.index(f'<w:bookmarkEnd w:id="{start.group(1)}"/>')
    return visible_text(xml[start.end():shut])


def _parses(xml: str) -> None:
    """Well-formed, and no text outside a `w:t`. A stray `>` or half a
    closing tag left between runs is legal XML character data, so parsing
    alone passed eleven broken rebuilds; Word keeps such text nowhere."""
    root = ET.fromstring(f'<root xmlns:w="w">{xml}</root>')
    for el in root.iter():
        if el.tag not in ("{w}t", "{w}instrText"):
            assert not (el.text or "").strip(), (el.tag, el.text)
        assert not (el.tail or "").strip(), (el.tag, el.tail)


def _sabotage(monkeypatch, module, name, change):
    """Make `module.<name>` hand back `change(result)`."""
    real = getattr(module, name)
    monkeypatch.setattr(module, name, lambda *a, **k: change(real(*a, **k)))


# --- the naming a paper uses: cite_x beside ref_x ------------------------


@pytest.mark.parametrize(("name", "pair"), [
    ("cite_adams_2001", "ref_adams_2001"),
    ("ref_adams_2001", "cite_adams_2001"),
    ("Adams2001txt", "Adams2001"),
    ("Adams2001", "Adams2001txt"),
])
def test_pair_of_reads_BOTH_namings_both_ways(name, pair):
    assert repair._pair_of(name) == pair


@pytest.mark.parametrize("anchor", ["Adams2001txt", "cite_adams_2001"])
def test_a_BACK_link_carries_no_marker_of_its_own(anchor):
    assert repair._own_marker(anchor) is None


def test_rewrap_marker_on_a_papers_own_cite_and_ref_naming():
    xml = _doc(P(bookmark("cite_adams_2001", 60, R("in the older workforce ")
                          + _link("ref_adams_2001", "(Adams 2001)"))))

    out = rewrap_marker(xml, "cite_adams_2001")

    assert _inside(out, "cite_adams_2001") == "(Adams 2001)"
    assert visible_text(out) == visible_text(xml)
    assert out.count('w:id="60"') == 2


def test_marker_spans_ignores_an_END_whose_start_is_elsewhere():
    assert repair._marker_spans(
        P('<w:bookmarkEnd w:id="5"/>' + R("carried over"))) == {}


def test_self_link_spans_skips_a_NAMELESS_start_and_Words_own_bookmarks():
    nameless = ('<w:bookmarkStart w:id="1"/>' + R("x")
                + '<w:bookmarkEnd w:id="1"/>')
    word = ('<w:bookmarkStart w:id="2" w:name="_Toc2"/>'
            + _link("_Toc2", "x") + '<w:bookmarkEnd w:id="2"/>')

    assert repair._self_link_spans(nameless) == []
    assert repair._self_link_spans(word) == []


def test_a_GHOST_link_inside_its_own_bookmark_is_no_SELF_LINK():
    """`<w:hyperlink w:anchor="…"/>` is the shell Word leaves of a link it
    emptied: it lands no reader anywhere. Read as a link's opening, alone
    in its own bookmark it was a SELF LINK the audit reported; beside a
    real one, `retarget_self_link` counted two links and refused the very
    repair the audit proposes."""
    ghost = '<w:hyperlink w:anchor="Adams2001txt"/>'
    alone = _doc(P(bookmark("Adams2001txt", 60, ghost + R("Adams (2001)"))))
    beside = _doc(P(bookmark("Adams2001txt", 60,
                             ghost + _link("Adams2001txt", "Adams (2001)"))),
                  P(bookmark("Adams2001", 61, R("A."))))

    assert repair._self_link_spans(alone) == []
    out = retarget_self_link(beside, "Adams2001txt")
    assert [a for a, _ in internal_links(out)] == ["Adams2001"]


# --- rewrap_marker: what it refuses, and its guards ----------------------


def test_rewrap_marker_REFUSES_what_it_cannot_do():
    link = _link("Adams2001", "Adams (2001)")
    twice = _doc(P(bookmark("Adams2001txt", 60, "") + link),
                 P(bookmark("Adams2001txt", 61, "") + link))
    alone = _doc(P(bookmark("Adams2001txt", 60, R("no link here"))))
    cases = [
        (_doc(P(link)), "cite_adams_2001txt", "not a link's own marker"),
        (twice, "Adams2001txt", "starts in 2 paragraph"),
        (alone, "Adams2001txt", "has 0 link"),
    ]
    for xml, name, message in cases:
        with pytest.raises(AnchorError, match=message):
            rewrap_marker(xml, name)


_MARKER = _doc(P(R("As ") + _link("Adams2001", "Adams (2001)") + R(" shows.")
                 + bookmark("Adams2001txt", 60, "")))


@pytest.mark.parametrize("change", [
    lambda x: x.replace(">As </w:t>", ">Aa </w:t>", 1),       # reads LOWER
    lambda x: x.replace(">As </w:t>", ">Az </w:t>", 1),       # ...and HIGHER
    lambda x: x.replace('w:anchor="Adams2001"', 'w:anchor="Aaa"', 1),
    lambda x: x.replace('w:anchor="Adams2001"', 'w:anchor="Zzz"', 1),
])
def test_rewrap_marker_REFUSES_a_rebuild_that_moved_text_or_a_link(
        monkeypatch, change):
    _sabotage(monkeypatch, repair, "wrap_link_in_bookmark", change)

    with pytest.raises(AnchorError, match="text or links would move"):
        rewrap_marker(_MARKER, "Adams2001txt")


# --- retarget_self_link: the bookmark it is named for, and only that -----


def test_retarget_self_link_takes_only_the_bookmark_it_is_NAMED_for():
    """Two self-links, one bookmark inside the other: the outer span holds
    the inner link too, so a filter that let the other name in counted that
    link twice and refused."""
    targets = P(bookmark("Adams2001", 62, R("A."))
                + bookmark("Brown2002txt", 63, R("B.")))
    adams_in_brown = _doc(
        P(bookmark("Brown2002", 61, _link("Brown2002", "b ")
                   + bookmark("Adams2001txt", 60,
                              _link("Adams2001txt", "a")))), targets)
    brown_in_adams = _doc(
        P(bookmark("Adams2001txt", 60, _link("Adams2001txt", "a ")
                   + bookmark("Brown2002", 61, _link("Brown2002", "b")))),
        targets)

    for xml, name, to in ((adams_in_brown, "Adams2001txt", "Adams2001"),
                          (brown_in_adams, "Brown2002", "Brown2002txt")):
        out = retarget_self_link(xml, name)

        assert [a for a, _ in internal_links(out)].count(to) == 1


# --- respan_link -----------------------------------------------------------

_LEAD = "Conversion factors: "                     # 20 characters


def test_respan_link_unwraps_a_FIELD_whose_end_run_carries_properties():
    """Word styles the run holding the `end` fldChar like the label it
    closes. The cut took the last `<w:r` before `fldCharType="end"` — that
    run's `<w:rStyle` — and left `<w:r><w:rPr>` behind: XML Word refuses,
    with the text and bookmark guards both passing (code review,
    2026-09-13)."""
    style = '<w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
    field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             r'<w:r><w:instrText xml:space="preserve"> HYPERLINK \l '
             '"Robeyns2005" </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             f"<w:r>{style}<w:t>(Robeyns 2005)</w:t></w:r>"
             f'<w:r>{style}<w:fldChar w:fldCharType="end"/></w:r>')
    xml = _doc(P(R("as in ") + field + R(".")))

    out = respan_link(xml, "Robeyns2005", "Robeyns 2005")

    _parses(out)
    assert visible_text(out) == "as in (Robeyns 2005)."
    assert [label for _a, label in internal_links(out)] == ["Robeyns 2005"]


def test_respan_link_wants_EXACTLY_one_link():
    one = _link("Robeyns2005", "Robeyns 2005")
    for xml, count in ((_doc(P(R("no link"))), 0),
                       (_doc(P(one + R(" and ") + one)), 2)):
        with pytest.raises(AnchorError, match=f"matched {count} link"):
            respan_link(xml, "Robeyns2005", "Robeyns 2005)")


def test_respan_link_moves_the_START_edge_from_offset_20():
    """The label opens at 20 and runs 13 characters to 33, and the new
    start is 33 - 12: offsets where every arithmetic spelling misses."""
    xml = _doc(P(R(_LEAD) + _link("Robeyns2005", "(Robeyns 2005")
                 + R(") are personal.")))

    out = respan_link(xml, "Robeyns2005", "Robeyns 2005")

    assert internal_links(out) == [("Robeyns2005", "Robeyns 2005")]
    assert visible_text(out) == visible_text(xml)
    _parses(out)


def test_respan_link_to_its_own_label_hands_back_the_SAME_document():
    xml = _doc(P(R("see ") + hyperlink_field("Robeyns2005", "Robeyns 2005")))
    same = " ".join(["Robeyns", "2005"])       # equal, and another object

    assert respan_link(xml, "Robeyns2005", same) is xml


def test_the_RETYPE_refusal_quotes_40_characters_of_each_side():
    label = "Organisation for Economic Co-operation and Development 2019"
    want = "The World Bank Group and the International Monetary Fund 2020"
    xml = _doc(P(R("see ") + _link("OECD2019", label) + R(".")))

    with pytest.raises(AnchorError, match="does not retype one") as caught:
        respan_link(xml, "OECD2019", want)

    assert repr(want[:40]) in str(caught.value)
    assert repr(label[:40]) in str(caught.value)


_TAIL = ") is the reference for the conversion factors of this framework."


@pytest.mark.parametrize(("page", "want"), [
    (_TAIL, "Robeyns 2005" + _TAIL.replace("this", "THIS")),  # page higher
    (_TAIL.replace("this", "THIS"), "Robeyns 2005" + _TAIL),  # ...and lower
])
def test_the_MOVED_BOUNDARY_guard_refuses_and_quotes_40_characters(
        page, want):
    xml = _doc(P(R("see ") + _link("Robeyns2005", "Robeyns 2005") + R(page)))

    with pytest.raises(AnchorError, match="at the moved boundary") as caught:
        respan_link(xml, "Robeyns2005", want)

    assert repr(want[:40]) in str(caught.value)


def test_the_REBUILD_leaves_well_formed_xml_for_either_link_form():
    """A slice one character out still READ right: the label's text
    survived, and a stray `>` or half a closing tag does not show on the
    page. Parsed, it does not survive. The anchor puts the element's `>` at
    35 and the field's closing tag at 154, where `| 1`, `^ 1`, `| 6` and
    `^ 6` all miss."""
    for link in (_link("Robeyns2005", "Robeyns 2005)"),
                 hyperlink_field("Robeyns2005", "Robeyns 2005)")):
        xml = _doc(P(R("see ") + link + R(" today.")))

        out = respan_link(xml, "Robeyns2005", "Robeyns 2005")

        _parses(out)
        assert internal_links(out) == [("Robeyns2005", "Robeyns 2005")]


@pytest.mark.parametrize("to", ["Aonversion", "Zonversion"])
def test_respan_link_REFUSES_a_rebuild_that_moved_the_text(monkeypatch, to):
    _sabotage(monkeypatch, grammar, "wrap_visible_span",
              lambda x: x.replace("Conversion", to, 1))
    xml = _doc(P(R(_LEAD) + _link("Robeyns2005", "Robeyns 2005)") + R(".")))

    with pytest.raises(AnchorError, match="visible text moved"):
        respan_link(xml, "Robeyns2005", "Robeyns 2005")


@pytest.mark.parametrize("change", [
    lambda x: x.replace('<w:bookmarkEnd w:id="3"/>', "", 1),     # one fewer
    lambda x: x.replace("</w:p>",
                        '<w:bookmarkStart w:id="9" w:name="x"/></w:p>'),
])
def test_respan_link_REFUSES_a_rebuild_that_lost_or_gained_a_bookmark(
        monkeypatch, change):
    _sabotage(monkeypatch, grammar, "wrap_visible_span", change)
    xml = _doc(P(bookmark("_Hlk3", 3, R(_LEAD))
                 + _link("Robeyns2005", "Robeyns 2005)") + R(".")))

    with pytest.raises(AnchorError, match="count moved"):
        respan_link(xml, "Robeyns2005", "Robeyns 2005")
