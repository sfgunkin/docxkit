"""`replace_with_runs`: a stretch of visible text replaced by STYLED runs.

Backlog S4, 2026-11-18. Month_of_birth R15 wrote 19 spans of the form
"Let *x*\\ :sub:`i` be the child's date of birth" by composing
`replace_in_para(old, "")`, `insert_in_para` at a re-derived offset and a
regex over the emptied runs; R14 had done the same a third way.
"""
from __future__ import annotations

import re

import pytest

from docxkit import text_of
from docxkit.edit import replace_with_runs
from docxkit.errors import AnchorError

ITALIC = "<w:rPr><w:i/></w:rPr>"
SUB = '<w:rPr><w:i/><w:vertAlign w:val="subscript"/></w:rPr>'


def P(*inner: str) -> str:
    return "<w:p>" + "".join(inner) + "</w:p>"


def R(text: str, rpr: str = "") -> str:
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f"<w:r>{rpr}<w:t{space}>{text}</w:t></w:r>"


def _runs(para: str) -> list[tuple[str, str]]:
    """(text, rPr) of each run, in order."""
    return [(re.sub(r"<[^>]+>", "", m.group(2)), m.group(1) or "")
            for m in re.finditer(r"<w:r>(<w:rPr>.*?</w:rPr>)?(.*?)</w:r>",
                                 para)]


def test_the_R15_shape_writes_each_run_in_its_own_look():
    p = P(R("Let the date be "), R("x", ITALIC), R(" for each child."))

    out = replace_with_runs(p, "the date be x for each",
                            [("x", ITALIC), ("i", SUB),
                             (" be the child's date of birth, for each", "")])

    assert text_of(out) == ("Let xi be the child's date of birth, for each "
                            "child.")
    assert _runs(out) == [("Let ", ""), ("x", ITALIC), ("i", SUB),
                          (" be the child's date of birth, for each", ""),
                          (" child.", "")]


def test_the_runs_the_deletion_EMPTIED_are_removed():
    """`replace_in_para(old, "")` leaves `<w:r><w:rPr/><w:t></w:t></w:r>`
    behind for each run it emptied; R15's script swept those up with a
    regex of its own."""
    p = P(R("A "), R("b", ITALIC), R(" c "), R("d."))

    out = replace_with_runs(p, "b c ", [("B", ITALIC), (" ", "")])

    assert "<w:t></w:t>" not in out
    assert _runs(out) == [("A ", ""), ("B", ITALIC), (" ", ""), ("d.", "")]


def test_an_empty_run_the_paragraph_ALREADY_had_is_left_alone():
    """Only the bytes the edit touched change."""
    shell = "<w:r><w:rPr><w:b/></w:rPr><w:t></w:t></w:r>"
    p = P(R("Keep "), shell, R("this word."))

    out = replace_with_runs(p, "word", [("term", ITALIC)])

    assert shell in out
    assert text_of(out) == "Keep this term."


def test_the_runs_land_OUTSIDE_a_link_whose_edge_the_match_starts_at():
    link = '<w:hyperlink w:anchor="Table2">' + R("Table 2") + "</w:hyperlink>"
    p = P(R("See "), link, R(" for x here."))

    out = replace_with_runs(p, " for x", [(" for ", ""), ("x", ITALIC)])

    assert text_of(out) == "See Table 2 for x here."
    label = out[out.index("<w:hyperlink"):out.index("</w:hyperlink>")]
    assert text_of(P(label)) == "Table 2", "the link did not grow"


def test_a_match_that_CROSSES_a_link_is_refused_as_replace_in_para_does():
    link = '<w:hyperlink w:anchor="Table2">' + R("Table 2") + "</w:hyperlink>"
    p = P(R("See "), link, R(" here."))

    with pytest.raises(AnchorError, match="spans a hyperlink"):
        replace_with_runs(p, "See Table 2 here", [("x", ITALIC)])


def test_an_absent_anchor_is_refused():
    with pytest.raises(AnchorError):
        replace_with_runs(P(R("Nothing here.")), "absent", [("x", "")])


def test_properties_that_are_not_a_whole_rPr_are_refused():
    with pytest.raises(AnchorError, match="whole <w:rPr>"):
        replace_with_runs(P(R("A b c.")), "b", [("x", "<w:i/>")])


def test_no_runs_is_a_deletion_that_leaves_no_shell():
    p = P(R("A "), R("gone", ITALIC), R(" b."))

    out = replace_with_runs(p, "gone", [])

    assert text_of(out) == "A  b."
    assert "<w:t></w:t>" not in out and ITALIC not in out
