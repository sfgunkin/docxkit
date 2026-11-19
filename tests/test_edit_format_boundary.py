"""A replacement that crosses a change of character formatting.

`replace_in_para` writes the whole replacement into the run holding the
START of the match and empties the rest. When that run is a bold label
and the match runs on into plain prose, every new word comes out bold.
On Parental Style (2026-11-16) the keywords line, stored as a bold
``Keywords:`` and a plain list, was replaced whole and the list printed
bold. The text contract held, `lint` was clean, and `compare` reported no
FORMAT change, because it compares formatting only where the text is
equal. Nothing saw it until the runs were dumped by hand (BACKLOG S2).

These tests assert which RUN each word ends up in, which is the thing
that was wrong. A text assertion passes on the broken write.
"""
from __future__ import annotations

import pytest
from conftest import para

from docxkit._xml import RUN_RE
from docxkit.edit import (
    _common_edges,
    _look,
    replace_in_para,
    replace_keeping_links,
    visible_text,
)
from docxkit.errors import AnchorError

BOLD = "<w:rPr><w:b/></w:rPr>"


def _r(text: str, rpr: str = "") -> str:
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _faces(p: str) -> list[tuple[str, bool]]:
    """(text, bold?) per run that shows anything."""
    out = []
    for m in RUN_RE.finditer(p):
        text = visible_text(m.group(0))
        if text:
            out.append((text, "<w:b/>" in m.group(0)))
    return out


KEYWORDS = para(_r("Keywords:", BOLD),
                _r(" child discipline; coercive discipline; family size; "
                   "Central Asia"))


def test_the_parental_style_keywords_line_keeps_its_list_plain() -> None:
    out = replace_in_para(
        KEYWORDS,
        "Keywords: child discipline; coercive discipline; family size; "
        "Central Asia",
        "Keywords: child discipline; parenting style; family size; "
        "informal institutions; Central Asia")
    assert _faces(out) == [
        ("Keywords:", True),
        (" child discipline; parenting style; family size; informal "
         "institutions; Central Asia", False)]


def test_the_natural_anchor_writes_what_the_workaround_wrote() -> None:
    whole = replace_in_para(
        KEYWORDS,
        "Keywords: child discipline; coercive discipline; family size; "
        "Central Asia",
        "Keywords: child discipline; parenting style; family size; "
        "informal institutions; Central Asia")
    plain_only = replace_in_para(
        KEYWORDS, "coercive discipline; family size; Central Asia",
        "parenting style; family size; informal institutions; Central Asia")
    assert whole == plain_only


def test_a_match_in_runs_that_print_alike_is_written_as_before() -> None:
    p = para(_r("ab"), _r("cd"))
    out = replace_in_para(p, "bc", "bX")
    # NOT narrowed: the whole replacement goes into the first run and the
    # second is emptied of what the match covered, byte for byte as ever
    assert out == para(_r("abX"), _r("d"))


def test_proofing_marks_and_complex_script_mirrors_are_not_a_look() -> None:
    lang = '<w:rPr><w:lang w:val="en-US"/><w:szCs w:val="24"/></w:rPr>'
    p = para(_r("ab", lang), _r("cd"))
    assert replace_in_para(p, "bc", "bX") == para(_r("abX", lang), _r("d"))


def test_a_change_that_still_crosses_the_boundary_is_refused() -> None:
    with pytest.raises(AnchorError, match="change of character formatting"):
        replace_in_para(KEYWORDS, "Keywords: child", "Key words: kid")


def test_the_opt_in_writes_only_the_changed_middle() -> None:
    out = replace_in_para(KEYWORDS, "Keywords: child", "Key words: kid",
                          allow_format_boundary=True)
    assert visible_text(out).startswith("Key words: kid discipline;")
    # the shared head "Key" and tail "d" stay in their runs; the middle
    # takes the look of the run it starts in, as the caller asked
    assert _faces(out)[0] == ("Key words: ki", True)
    assert _faces(out)[1][0].startswith("d discipline;")
    assert not _faces(out)[1][1]


def test_a_pure_deletion_across_the_boundary_needs_no_opt_in() -> None:
    p = para(_r("Keywords:", BOLD), _r(" a; b"))
    out = replace_in_para(p, "Keywords: a; b", "Keywords: b")
    assert _faces(out) == [("Keywords:", True), (" b", False)]


def test_an_insertion_at_a_seam_between_two_LOOKS_is_refused() -> None:
    """Backlog S1, 2026-11-19 (a /code-review of f2b009c, reproduced):
    words inserted where a bold label meets a plain list belong to
    either, and the text cannot say which. "Keywords: " + "a; b" ->
    "Keywords: x; a; b" wrote `x; ` bold — the Parental Style failure
    this narrowing exists to stop, with nothing refusing."""
    p = para(_r("Keywords: ", BOLD), _r("a; b"))
    with pytest.raises(AnchorError, match="between two runs that print"):
        replace_in_para(p, "Keywords: a; b", "Keywords: x; a; b")
    # anchoring on one side says which, and needs no opt-in
    out = replace_in_para(p, "a; b", "x; a; b")
    assert _faces(out) == [("Keywords: ", True), ("x; a; b", False)]


def test_the_opt_in_continues_the_run_before_the_seam() -> None:
    """What typing there in Word does, when the caller says so."""
    p = para(_r("Keywords:", BOLD), _r(" a"))
    out = replace_in_para(p, "Keywords: a", "Keywords:! a",
                          allow_format_boundary=True)
    assert _faces(out) == [("Keywords:!", True), (" a", False)]


def test_an_insertion_at_a_seam_between_LIKE_runs_needs_no_opt_in() -> None:
    """Narrowing happens because the match crosses a look somewhere;
    a seam between two runs that print alike is not that place."""
    p = para(_r("Keywords:", BOLD), _r(" a; "), _r("b"))
    out = replace_in_para(p, "Keywords: a; b", "Keywords: a; x; b")
    assert _faces(out) == [("Keywords:", True), (" a; x; ", False),
                           ("b", False)]


LINK = ('<w:hyperlink w:anchor="Table2">'
        '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
        '<w:t xml:space="preserve">Table 2</w:t></w:r></w:hyperlink>')


def test_an_insertion_INSIDE_a_label_is_named_and_honours_the_opt_in() -> None:
    """The refusal said "at the edge of a link's label" for a position
    strictly inside one, and `allow_hyperlink=True` — retitling the
    label — did not let it through (review, 2026-11-19)."""
    p = para(_r("See "), LINK, _r(" here", BOLD))
    with pytest.raises(AnchorError, match="inside a link's label"):
        replace_in_para(p, "See Table 2 here", "See Tabble 2 here")
    out = replace_in_para(p, "See Table 2 here", "See Tabble 2 here",
                          allow_hyperlink=True)
    label = out[out.index("<w:hyperlink"):out.index("</w:hyperlink>")]
    assert visible_text(label) == "Tabble 2"


INS = '<w:ins w:id="7" w:author="Other" w:date="2026-11-01T00:00:00Z">'


def test_an_insertion_at_the_EDGE_of_a_revision_stays_out_of_it() -> None:
    """`_insert_at` wrote into the run before the seam even when that run
    sat inside another author's `w:ins`, so the new words became part of
    that insertion and reject-all deleted them. `insert_in_para` has kept
    content out of a revision at its edge since 2026-09-18."""
    p = para(INS + _r("We ") + "</w:ins>", _r("now see"), _r(" x", BOLD))
    out = replace_in_para(p, "We now see x", "We clearly now see x")
    ins = out[out.index("<w:ins"):out.index("</w:ins>")]
    assert visible_text(ins) == "We "
    assert visible_text(out) == "We clearly now see x"


def test_an_insertion_that_opens_the_match_joins_its_first_run() -> None:
    p = para(_r("x "), _r("Keywords:", BOLD), _r(" a"))
    out = replace_in_para(p, "Keywords: a", "My Keywords: a")
    assert _faces(out) == [("x ", False), ("My Keywords:", True),
                           (" a", False)]


def test_an_insertion_inside_a_run_stays_in_that_run() -> None:
    out = replace_in_para(KEYWORDS, "Keywords: child discipline",
                          "Keywords: child-rearing discipline")
    assert _faces(out)[0] == ("Keywords:", True)
    assert _faces(out)[1][0].startswith(" child-rearing discipline;")


def test_an_unchanged_replacement_leaves_the_paragraph_alone() -> None:
    assert replace_in_para(KEYWORDS, "Keywords: child",
                           "Keywords: child") == KEYWORDS


def test_replace_keeping_links_carries_the_same_guard() -> None:
    with pytest.raises(AnchorError, match="change of character formatting"):
        replace_keeping_links(KEYWORDS, "Keywords: child", "Key words: kid")
    out = replace_keeping_links(KEYWORDS, "Keywords: child", "Key words: kid",
                                allow_format_boundary=True)
    assert visible_text(out).startswith("Key words: kid discipline;")


@pytest.mark.parametrize(("a", "b", "same"), [
    ("", "<w:rPr><w:b w:val=\"0\"/></w:rPr>", True),       # off == absent
    ("<w:rPr><w:b/></w:rPr>", "<w:rPr><w:b w:val=\"true\"/></w:rPr>", True),
    ("", '<w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr>', True),
    # another script's font: Latin text prints alike (writer oracle)
    ("", '<w:rPr><w:rFonts w:eastAsiaTheme="majorEastAsia"/></w:rPr>', True),
    ('<w:rPr><w:rFonts w:ascii="Arial" w:cs="Arial"/></w:rPr>',
     '<w:rPr><w:rFonts w:ascii="Arial"/></w:rPr>', True),
    ('<w:rPr><w:rFonts w:ascii="Arial"/></w:rPr>', "", False),
    ('<w:rPr><w:color w:val="000000"/></w:rPr>', "", True),
    ('<w:rPr><w:color w:val="auto"/></w:rPr>', "", True),
    ('<w:rPr><w:color w:val="FF0000"/></w:rPr>', "", False),
    ("<w:rPr><w:b/></w:rPr>", "", False),
    ("<w:rPr><w:i/></w:rPr>", "<w:rPr><w:b/></w:rPr>", False),
    ('<w:rPr><w:sz w:val="20"/></w:rPr>', "", False),
    # a tracked change's snapshot is history: the live face is plain
    ("", "<w:rPr><w:rPrChange w:id=\"1\" w:author=\"A\"><w:rPr><w:b/>"
         "</w:rPr></w:rPrChange></w:rPr>", True),
])
def test_look_compares_how_a_run_prints(a: str, b: str, same: bool) -> None:
    assert (_look(_r("x", a)) == _look(_r("x", b))) is same


@pytest.mark.parametrize(("seen", "new", "edges"), [
    ("aXa", "aa", (1, 1)),          # never counts a character twice
    ("abc", "abc", (3, 0)),
    ("abc", "xbz", (0, 0)),
    ("ab", "aXb", (1, 1)),
    ("", "x", (0, 0)),
])
def test_common_edges(seen: str, new: str, edges: tuple[int, int]) -> None:
    assert _common_edges(seen, new) == edges
